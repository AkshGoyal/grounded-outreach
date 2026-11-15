"""Explicit removal review and private, read-only background activity snapshots."""

from contextlib import ExitStack
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from outreach.campaigns import closing_path, copy_path, is_valid_id
from outreach.web.platform import redirect


def install_workspace_controls(app, templates, open_store, research, sender, drafter, inbox):
    def item(db, kind, key):
        if kind not in ("audience", "campaign"):
            raise HTTPException(404, "Choose an audience or campaign.")
        value = db.run(key) if kind == "audience" else db.campaign(key)
        if not value:
            raise HTTPException(404, "Saved work not found.")
        if kind == "audience":
            value["family"] = db.audience_history(key)
        return value

    def working(value, kind):
        return (
            any(
                r["id"] in research.active
                or r["status"] in ("planning", "running", "pause_requested", "approved")
                for r in value.get("family", [value])
            )
            if kind == "audience"
            else sender.busy or drafter.busy
        )

    def deletable(db, kind, value):
        key = value["id"]
        if kind == "audience":
            return (
                len(value.get("family", [value])) == 1
                and value["status"] in ("draft", "failed")
                and not value["plan"]
                and not value["approved_at"]
                and not db.one("SELECT run_id FROM research_calls WHERE run_id=?", (key,))
                and not db.one("SELECT id FROM research_leads WHERE run_id=?", (key,))
            )
        return (
            value["status"] in ("draft", "archived")
            and not db.one("SELECT id FROM contacts WHERE campaign_id=?", (key,))
            and not db.one("SELECT run_id FROM campaign_research_runs WHERE campaign_id=?", (key,))
            and is_valid_id(key)
            and not copy_path(key).exists()
            and not closing_path(key).exists()
        )

    @app.get("/workspace/{kind}/{key}/remove")
    def review_removal(request: Request, kind: str, key: str):
        with open_store() as db:
            value = item(db, kind, key)
            return templates.TemplateResponse(
                request,
                "remove_work.html",
                {
                    "item": value,
                    "kind": kind,
                    "key": key,
                    "can_delete": deletable(db, kind, value),
                    "can_trash": kind == "audience",
                    "deleted": value.get("deleted", False),
                    "deletion_version": "trash-v1",
                    "working": working(value, kind),
                    "return_to": ("/research/" if kind == "audience" else "/campaigns/") + key,
                    "archived": value.get("archived", False) or value["status"] == "archived",
                },
            )

    @app.post("/workspace/{kind}/{key}/remove")
    async def remove_work(request: Request, kind: str, key: str):
        form = await request.form()
        action = form.get("action")
        permanent = False
        with ExitStack() as locks:
            for lock in (research._lock, sender._lock, drafter.lock):
                locks.enter_context(lock)
            with open_store() as db, db.transaction():
                value = item(db, kind, key)
                if working(value, kind):
                    raise HTTPException(
                        409, "Finish or stop current work before removing this item."
                    )
                if action not in ("delete", "archive", "restore"):
                    raise HTTPException(400, "Choose delete, archive or restore.")
                if action == "delete":
                    if form.get("confirm_delete") != "yes":
                        raise HTTPException(409, "Confirm deletion before continuing.")
                    permanent = deletable(db, kind, value)
                    if not permanent and kind == "campaign":
                        raise HTTPException(
                            409,
                            "Confirm deletion of an unused draft. "
                            "Keep history by archiving other work.",
                        )
                    if kind == "audience" and not permanent:
                        if form.get("deletion_version") != "trash-v1":
                            raise HTTPException(
                                409,
                                "This audience now has history. Open Delete again to review "
                                "moving it to Deleted audiences instead of permanent deletion.",
                            )
                        for member in value["family"]:
                            db.conn.execute(
                                "INSERT OR IGNORE INTO research_trash VALUES (?,?)",
                                (member["id"], datetime.now(UTC).isoformat()),
                            )
                    elif kind == "audience":
                        for table in (
                            "research_trash",
                            "research_archives",
                            "research_intakes",
                            "research_messages",
                        ):
                            db.conn.execute(f"DELETE FROM {table} WHERE run_id=?", (key,))
                        db.conn.execute("DELETE FROM research_runs WHERE id=?", (key,))
                    else:
                        for table in ("campaign_briefs", "campaign_settings"):
                            db.conn.execute(f"DELETE FROM {table} WHERE campaign_id=?", (key,))
                        db.conn.execute("DELETE FROM campaigns WHERE id=?", (key,))
                elif kind == "audience":
                    if action == "archive":
                        for member in value["family"]:
                            db.conn.execute(
                                "INSERT OR IGNORE INTO research_archives VALUES (?,?)",
                                (member["id"], datetime.now(UTC).isoformat()),
                            )
                    else:
                        for member in value["family"]:
                            db.conn.execute(
                                "DELETE FROM research_archives WHERE run_id=?", (member["id"],)
                            )
                            db.conn.execute(
                                "DELETE FROM research_trash WHERE run_id=?", (member["id"],)
                            )
                else:
                    db.invalidate_approvals(key)
                    db.conn.execute(
                        "INSERT INTO campaign_settings (campaign_id,status) VALUES (?,?) "
                        "ON CONFLICT(campaign_id) DO UPDATE SET status=excluded.status",
                        (key, "archived" if action == "archive" else "paused"),
                    )
        destination = "/research" if kind == "audience" else "/campaigns"
        message = {
            "delete": "Unused draft deleted. No research or email was started."
            if permanent
            else "Audience deleted from active work. Restore it from Deleted audiences. "
            "Costs, evidence and campaign history were kept.",
            "archive": "Archived. History is preserved; find it in Archived work.",
            "restore": "Restored. Campaigns return paused; "
            "review settings and approvals before sending.",
        }[action]
        return redirect(destination, message)

    @app.get("/workspace/activity")
    def activity():
        jobs = []
        with open_store() as db:
            for key in list(research.active):
                run = db.run(key)
                if run:
                    jobs.append(
                        {
                            "kind": "research",
                            "title": run["title"],
                            "detail": run["progress"] or "Preparing research",
                            "href": "/research/" + key,
                        }
                    )
        draft = drafter.job
        if draft and not draft.finished:
            jobs.append(
                {
                    "kind": "drafting",
                    "title": "Writing email drafts",
                    "detail": f"{draft.completed} saved; {draft.failed} failed; "
                    f"{draft.total} eligible contacts. No emails sent.",
                    "href": "/drafting",
                }
            )
        send = sender.job
        if send and not send.finished:
            detail = f"{len(send.outcomes)} of {send.total} processed; {send.sent} accepted."
            if send.stop_requested:
                detail += " Stopping after the current email."
            elif send.seconds_to_next is not None:
                detail += f" Next email in {send.seconds_to_next} seconds."
            jobs.append(
                {
                    "kind": "sending",
                    "title": "Sending approved emails",
                    "detail": detail,
                    "href": "/sending",
                }
            )
        if inbox._lock.locked():
            jobs.append(
                {
                    "kind": "inbox",
                    "title": "Checking for replies",
                    "detail": "Matching replies to your campaigns.",
                    "href": "/inbox",
                }
            )
        recent = {}
        if draft:
            recent["drafting"] = {
                "finished": draft.finished,
                "completed": draft.completed,
                "failed": draft.failed,
                "total": draft.total,
                "detail": (
                    "Drafting stopped on an error. Open saved drafts and check the result."
                    if draft.error
                    else "Drafting stopped. Saved drafts remain ready for review."
                    if draft.stopped
                    else "Drafting finished. Review saved drafts before approving."
                ),
            }
        if send:
            recent["sending"] = {
                "finished": send.finished,
                "processed": len(send.outcomes),
                "sent": send.sent,
                "failed": send.failed,
                "total": send.total,
                "detail": (
                    "Sending stopped on an error. Check saved history for uncertain deliveries."
                    if send.crashed
                    else "Sending stopped. Check saved history before continuing."
                    if send.stop_requested
                    else "Sending finished. Check final results and saved history."
                ),
            }
        return JSONResponse({"jobs": jobs, "recent": recent}, headers={"Cache-Control": "no-store"})
