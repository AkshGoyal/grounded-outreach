"""The research, campaign and reply workspace.

Runs locally or in a protected Cloud environment. Research and drafting use
configured external providers; campaign mail uses its assigned sending account.

Like `cli.py`, this file is a composition root: it is allowed to know that
storage means SQLite, because something has to wire the concrete pieces
together. Everything it calls is the same code the command line calls, so the
two can never disagree about what an import does.
"""

from __future__ import annotations

import json
import secrets
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr, TypeAdapter
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from outreach.adapters.attachments import campaign_files, manifests, saved_files
from outreach.adapters.backup import BackupError
from outreach.adapters.credential_vault import CredentialVault
from outreach.adapters.db import connect
from outreach.adapters.mailbox_store import MailboxStore
from outreach.adapters.platform_store import PlatformStore
from outreach.adapters.provider_connection import check_openrouter
from outreach.adapters.provider_credentials import ProviderCredentials
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.spreadsheet import SpreadsheetError, read_rows
from outreach.adapters.store_sqlite import SqliteStore
from outreach.adapters.workspace_backup import backup_workspace
from outreach.campaigns import (
    closing_path,
    copy_path,
    is_valid_id,
    load_closing,
    load_copy,
    read_raw,
    save_texts,
)
from outreach.config import ConfigError, Settings, load_settings
from outreach.core.dispatch import email_tail, new_message_id, plan
from outreach.core.drafting import DraftVerdict, draft_email
from outreach.core.flow import repeated_lines
from outreach.core.grounding import SentenceCheck, Verdict
from outreach.core.importing import (
    DEFAULT_SKIP,
    RowStatus,
    build_report,
    grouped_problems,
    plan_columns,
)
from outreach.core.models import Campaign, Contact, DraftStatus, ReplyStatus, SuppressionReason
from outreach.core.replies import LABELS, CannotReplyError, ReplyCategory, check_replies, send_reply
from outreach.core.research import public_url
from outreach.core.review import (
    approval_blocker,
    checks_for_display,
    recheck,
    storable_body,
)
from outreach.core.sending import NotATestAddressError, SuppressedRecipientError, send_test
from outreach.generation import (
    current_generation_matches,
    generation_snapshot,
    recipient_generation,
)
from outreach.ports.llm import LLMError
from outreach.ports.mail import MailError, MailPort, MailUncertainError
from outreach.web.draft_jobs import DraftRunner
from outreach.web.jobs import InboxChecker, SendRunner
from outreach.web.launch import LaunchReview
from outreach.web.oauth import install_oauth
from outreach.web.platform import install_platform
from outreach.web.research_jobs import ResearchRunner
from outreach.web.research_view import continuation
from outreach.web.security import install_security
from outreach.web.workspace_controls import install_workspace_controls
from outreach.wiring import account_settings, build_llm, build_mailbox, campaign_settings

HERE = Path(__file__).parent
DRAFT_BATCH = 10
templates = Jinja2Templates(directory=str(HERE / "templates"))


def _mailbox(settings: Settings) -> MailPort:
    return build_mailbox(settings)


def create_app(
    settings: Settings | None = None,
    *,
    mailbox: Callable[[Settings], MailPort] = _mailbox,
    poll_minutes: float | None = None,
    research_api=None,
    oauth_service=None,
    local_shutdown: Callable[[], None] | None = None,
    provider_check=None,
) -> FastAPI:
    """`mailbox` selects the account's real transport; tests pass a fake.
    `poll_minutes` checks the inbox for replies that often while running."""
    settings = settings or load_settings()
    settings.require("db_path")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    provider_credentials = ProviderCredentials(settings)
    provider_credentials.apply()

    app = FastAPI(title="Outreach")
    templates.env.globals["network_restricted"] = settings.local_network_restricted
    templates.env.globals["feedback_enabled"] = True
    templates.env.globals["flow_guidance_enabled"] = True
    templates.env.globals["research_v2_enabled"] = True
    templates.env.globals["audience_handoff_enabled"] = True
    templates.env.globals["audience_continuity_enabled"] = True
    templates.env.globals["contact_research_enabled"] = True
    templates.env.globals["simple_handoff_enabled"] = True
    templates.env.globals["campaign_contacts_enabled"] = True
    templates.env.filters["friendly_status"] = lambda value: {
        "draft": "Audience saved",
        "planning": "Preparing your plan",
        "awaiting_approval": "Plan ready to review",
        "running": "Finding companies",
        "failed": "Needs attention",
        "completed": "Finished",
        "paused": "Paused",
        "pause_requested": "Pausing",
        "active": "Active",
        "archived": "Archived",
    }.get(value, str(value).replace("_", " ").capitalize())
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    sender = SendRunner()
    inbox = InboxChecker()
    launch_review = LaunchReview()
    mail_action_lock = threading.Lock()

    def store() -> SqliteStore:
        return SqliteStore(connect(settings.db_path))

    def missing(*names: str) -> list[str]:
        return [n for n in names if getattr(settings, n, None) in (None, "")]

    def platform_store():
        return PlatformStore(store())

    def campaign_profile(cid, require_verified=False):
        return campaign_settings(
            settings, cid, require_verified=require_verified, unlock=require_verified
        )

    researcher = ResearchRunner(
        platform_store, research_api or (lambda db, key: ResearchAPI(settings, db, key))
    )
    drafter = DraftRunner()
    app.state.research = researcher
    app.state.sender = sender
    app.state.drafter = drafter
    install_workspace_controls(app, templates, platform_store, researcher, sender, drafter, inbox)
    install_security(app, settings, templates)
    from outreach.web.attachments import install_attachments

    install_attachments(app, templates, platform_store, sender, drafter, mail_action_lock)

    @app.get("/setup/local-status")
    def local_status():
        return {
            "restricted": settings.local_network_restricted,
            "restart_available": bool(local_shutdown),
        }

    @app.post("/setup/restart-local")
    def restart_local():
        if not settings.local_network_restricted or not local_shutdown or not settings.app_password:
            raise HTTPException(404, "This server does not need a local restart.")
        if researcher.active or sender.busy or drafter.busy:
            raise HTTPException(409, "Wait for current work to finish before restarting.")
        return JSONResponse({"status": "stopping"}, background=BackgroundTask(local_shutdown))

    install_platform(
        app,
        settings,
        templates,
        platform_store,
        lambda: CredentialVault(settings),
        mailbox,
        lambda key: account_settings(settings, key),
        researcher,
        sender,
        drafter,
    )

    from outreach.adapters.oauth_mail import OAuthMail

    install_oauth(
        app,
        settings,
        templates,
        oauth_service or (lambda: OAuthMail(settings)),
        platform_store,
        lambda key: account_settings(settings, key),
        mailbox,
        sender,
        drafter,
    )

    @app.post("/campaigns/{campaign_id}/draft-all")
    def draft_all(campaign_id: str, rewrite: str = Form("")):
        db = store()
        exists = db.get_campaign(campaign_id) is not None
        db._conn.close()
        if not exists:
            raise HTTPException(404, "Campaign not found.")
        if not sender.busy:
            drafter.start(
                campaign_id,
                store,
                lambda: build_llm(settings),
                campaign_profile,
                rewrite=bool(rewrite),
            )
        return RedirectResponse("/drafting", status_code=303)

    @app.get("/drafting", response_class=HTMLResponse)
    def drafting(request: Request):
        return templates.TemplateResponse(request, "drafting.html", {"job": drafter.job})

    @app.post("/drafting/stop")
    def stop_drafting():
        if drafter.job:
            drafter.job.stopped = True
        return RedirectResponse("/drafting", status_code=303)

    # --- overview -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        db = store()
        q = db._conn.execute
        campaigns = []
        for r in q(
            "SELECT c.* FROM campaigns c LEFT JOIN campaign_settings s ON s.campaign_id=c.id "
            "WHERE COALESCE(s.status,'draft')!='archived' ORDER BY c.created_at DESC"
        ):
            cid = r["id"]

            def count(sql: str, cid: str = cid) -> int:
                return q(sql, (cid,)).fetchone()[0]

            c = {
                "id": cid,
                "name": r["name"],
                "contacts": count("SELECT COUNT(*) FROM contacts WHERE campaign_id = ?"),
                "undrafted": count(
                    "SELECT COUNT(*) FROM contacts WHERE campaign_id = ? AND id NOT IN "
                    "(SELECT contact_id FROM drafts)"
                ),
                "review": count(
                    "SELECT COUNT(*) FROM drafts d JOIN contacts c ON c.id = d.contact_id "
                    "WHERE c.campaign_id = ? AND d.status = 'review'"
                ),
                "approved": count(
                    "SELECT COUNT(*) FROM drafts d JOIN contacts c ON c.id = d.contact_id "
                    "WHERE c.campaign_id = ? AND d.status = 'approved'"
                ),
                "sent": count(
                    "SELECT COUNT(DISTINCT m.contact_id) FROM messages m "
                    "JOIN contacts c ON c.id = m.contact_id "
                    "WHERE c.campaign_id = ? AND m.status = 'sent'"
                ),
                "has_copy": load_copy(cid) is not None,
                "replied": count(
                    "SELECT COUNT(DISTINCT t.contact_id) FROM reply_triage t "
                    "JOIN contacts c ON c.id = t.contact_id "
                    "WHERE c.campaign_id = ? AND t.category NOT IN ('bounce', 'out_of_office')"
                ),
            }
            metadata = PlatformStore(db).campaign(cid)
            c["status"] = metadata["status"]
            c["has_sender"] = bool(metadata["sender_account_id"] and metadata["verified_at"])
            if not metadata["workspace_campaign_id"]:
                c["has_sender"] = not missing(*settings.SEND)
            c["pending"] = count(
                "SELECT COUNT(*) FROM messages m JOIN contacts c ON c.id=m.contact_id "
                "WHERE c.campaign_id=? AND m.status='pending'"
            )
            c["next"] = _next_step(c)
            campaigns.append(c)
        suppressed = q("SELECT COUNT(*) AS n FROM suppressions").fetchone()["n"]
        setup_missing = missing(*settings.llm_credentials())
        if not any(a["verified_at"] for a in PlatformStore(db).accounts()):
            setup_missing += missing(*settings.SEND)
        pending_reviews = {
            r["run_id"]: r["n"]
            for r in q(
                "SELECT run_id,COUNT(*) AS n FROM research_leads "
                "WHERE review_status='pending' AND processing_status='complete' GROUP BY run_id"
            )
        }
        research_tasks = []
        for run in PlatformStore(db).audiences():
            run["review_count"] = pending_reviews.get(run["id"], 0)
            run["next_step"] = continuation(PlatformStore(db), run, run["id"] in researcher.active)
            if run["status"] != "completed" or run["review_count"]:
                research_tasks.append(run)
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "campaigns": campaigns,
                "research_tasks": research_tasks[:4],
                "default_research_budget": min(0.5, settings.research_max_budget_usd),
                "research_max_budget": settings.research_max_budget_usd,
                "suppressed": suppressed,
                "db_path": settings.db_path,
                "setup_missing": setup_missing,
                "sent_today": db.sent_today(),
                "cap": settings.daily_send_cap,
                "sending": sender.job if sender.busy else None,
                "new_replies": q(
                    "SELECT COUNT(*) FROM reply_triage WHERE status = 'new'"
                ).fetchone()[0],
            },
        )

    def _next_step(c):
        """The one thing to do next for a campaign, as (label, link)."""
        cid = c["id"]
        if c["pending"]:
            return ("Check uncertain sends", f"/campaigns/{cid}/history?status=pending")
        if c["status"] in ("paused", "completed"):
            return ("Open campaign", f"/campaigns/{cid}")
        if not c["contacts"]:
            return ("Add audience", f"/campaigns/{cid}?tab=audience")
        if not c["has_copy"]:
            return ("Complete message brief", f"/campaigns/{cid}/message")
        if c["review"]:
            return (
                f"Review {c['review']} draft{'s' * (c['review'] != 1)}",
                f"/campaigns/{cid}/drafts",
            )
        if c["approved"]:
            if not c["has_sender"]:
                return ("Choose a sending account", f"/campaigns/{cid}/settings")
            return (f"Send {c['approved']} approved", f"/campaigns/{cid}/send")
        if c["undrafted"]:
            return ("Write drafts", f"/campaigns/{cid}/drafts")
        if c["replied"]:
            return ("Open campaign replies", f"/inbox?campaign_id={cid}&show=all")
        return ("Manage audience", f"/campaigns/{cid}?tab=audience")

    # --- one campaign -------------------------------------------------------

    @app.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
    def campaign(request: Request, campaign_id: str, tab: str = "overview"):
        db = store()
        import json

        contacts = []
        for row in db._conn.execute(
            "SELECT * FROM contacts WHERE campaign_id = ? ORDER BY id", (campaign_id,)
        ):
            contacts.append(
                {
                    "id": row["id"],
                    "email": row["email"],
                    "company": row["company"],
                    "evidence": json.loads(row["evidence"]),
                    "suppressed": db.is_suppressed(row["email"]),
                }
            )
        metadata = PlatformStore(db).campaign(campaign_id)
        if not metadata:
            raise HTTPException(404, "Campaign not found.")
        latest = _latest_by_contact(db, campaign_id)
        draft_counts = {
            status.value: sum(d.status is status for d in latest) for status in DraftStatus
        }
        undrafted = len(contacts) - len(latest)
        available_audiences = []
        if tab == "audience":
            from outreach.core.campaign_selection import campaign_email

            workspace = PlatformStore(db)
            existing_emails = {contact["email"] for contact in contacts}
            for audience in workspace.audiences():
                available = []
                for lead in workspace.audience_leads(audience["id"]):
                    email = campaign_email(lead)
                    if email and email["value"] not in existing_emails:
                        available.append({**lead, "email": email})
                available_audiences.append(
                    {
                        "id": audience["id"],
                        "title": audience["title"],
                        "contacts": available[:250],
                        "has_prior": any(lead["prior_campaigns"] for lead in available[:250]),
                    }
                )
        return templates.TemplateResponse(
            request,
            "campaign.html",
            {
                "campaign_id": campaign_id,
                "contacts": contacts,
                "has_copy": load_copy(campaign_id) is not None,
                "has_closing": load_closing(campaign_id) is not None,
                "metadata": metadata,
                "tab": "audience" if tab == "audience" else "overview",
                "lists": PlatformStore(db).lists(),
                "available_audiences": available_audiences,
                "draft_counts": draft_counts,
                "undrafted": undrafted,
                "sender_ready": bool(metadata["sender_account_id"] and metadata["verified_at"])
                if metadata["workspace_campaign_id"]
                else not missing(*settings.SEND),
                "origins": {
                    r["contact_id"]: r["lead_id"]
                    for r in db._conn.execute(
                        (
                            "SELECT o.* FROM contact_origins o JOIN contacts c ON "
                            "c.id=o.contact_id WHERE c.campaign_id=?"
                        ),
                        (campaign_id,),
                    )
                },
                "sent_count": db._conn.execute(
                    (
                        "SELECT COUNT(DISTINCT m.contact_id) FROM messages m JOIN contacts "
                        "c ON c.id=m.contact_id WHERE c.campaign_id=? AND m.status='sent'"
                    ),
                    (campaign_id,),
                ).fetchone()[0],
                "reply_count": db._conn.execute(
                    (
                        "SELECT COUNT(*) FROM replies r JOIN reply_triage t ON "
                        "t.reply_id=r.id JOIN contacts c ON c.id=t.contact_id WHERE "
                        "c.campaign_id=?"
                    ),
                    (campaign_id,),
                ).fetchone()[0],
            },
        )

    # --- the campaign's own texts ---------------------------------------------

    @app.get("/campaigns/{campaign_id}/texts", response_class=HTMLResponse)
    def texts(request: Request, campaign_id: str, saved: str = ""):
        with platform_store() as db:
            if not db.campaign(campaign_id):
                raise HTTPException(404, "Campaign not found.")
        return templates.TemplateResponse(
            request,
            "texts.html",
            {
                "campaign_id": campaign_id,
                "copy": read_raw(copy_path(campaign_id)),
                "closing": read_raw(closing_path(campaign_id)),
                "saved": bool(saved),
                "error": None
                if is_valid_id(campaign_id)
                else "This campaign's name can't be used as a file name. Use lower-case "
                "letters, digits and dashes — import the list again under a name like rfd-buyers.",
            },
        )

    @app.post("/campaigns/{campaign_id}/texts", response_class=HTMLResponse)
    def save_campaign_texts(
        request: Request, campaign_id: str, offer: str = Form(""), closing: str = Form("")
    ):
        if not offer.strip():
            return templates.TemplateResponse(
                request,
                "texts.html",
                {
                    "campaign_id": campaign_id,
                    "copy": offer,
                    "closing": closing,
                    "saved": False,
                    "error": "Describe what you are offering — a draft may say nothing about "
                    "your business that is not written here.",
                },
            )
        try:
            from outreach.core.email_composer import parse_editor

            parse_editor(offer)
            if not is_valid_id(campaign_id):
                raise ValueError(f"Not a usable campaign id: {campaign_id!r}")
            if sender.busy or drafter.busy:
                raise ValueError("Stop sending or drafting before changing campaign content.")
            with platform_store() as db:
                if not db.campaign(campaign_id):
                    raise HTTPException(404, "Campaign not found.")
                db.invalidate_approvals(campaign_id)
                db.conn.execute("DELETE FROM campaign_briefs WHERE campaign_id=?", (campaign_id,))
            save_texts(campaign_id, copy=offer, closing=closing)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "texts.html",
                {
                    "campaign_id": campaign_id,
                    "copy": offer,
                    "closing": closing,
                    "saved": False,
                    "error": str(exc),
                },
            )
        return RedirectResponse(f"/campaigns/{campaign_id}/texts?saved=1", status_code=303)

    # --- importing ----------------------------------------------------------

    @app.get("/import", response_class=HTMLResponse)
    def import_form(request: Request, campaign_id: str = ""):
        with platform_store() as db:
            campaigns = db.rows("SELECT id,name FROM campaigns ORDER BY created_at DESC")
        return templates.TemplateResponse(
            request, "import.html", {"campaign": campaign_id, "campaigns": campaigns}
        )

    @app.post("/import", response_class=HTMLResponse)
    async def import_preview(
        request: Request,
        file: UploadFile,
        campaign: str = Form(...),
        sheet: str = Form(""),
        email_column: str = Form(""),
        commit: str = Form(""),
    ):
        """Preview by default; write only when the Import button was pressed.

        The uploaded file is written to a temporary location and deleted as
        soon as it has been read. It is never stored in the project folder,
        where it could be committed by accident.
        """
        if not is_valid_id(campaign):
            return templates.TemplateResponse(
                request,
                "import.html",
                {
                    "error": (
                        "Choose an existing campaign ID, or use lower-case "
                        "letters, digits and dashes."
                    ),
                    "campaign": campaign,
                },
                status_code=400,
            )
        if commit and (sender.busy or drafter.busy):
            return templates.TemplateResponse(
                request,
                "import.html",
                {
                    "error": (
                        "Wait for sending or drafting to finish before importing more contacts."
                    ),
                    "campaign": campaign,
                },
                status_code=409,
            )
        suffix = Path(file.filename or "upload.csv").suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            shutil.copyfileobj(file.file, handle)
            temporary = Path(handle.name)

        try:
            rows = read_rows(temporary, sheet=sheet or None)
        except SpreadsheetError as exc:
            return templates.TemplateResponse(
                request, "import.html", {"error": str(exc), "campaign": campaign}
            )
        finally:
            temporary.unlink(missing_ok=True)

        db = store()
        columns = plan_columns(rows, skip=DEFAULT_SKIP)
        if email_column:
            columns.email_column = email_column
            columns.evidence_columns = [c for c in columns.evidence_columns if c != email_column]

        report = build_report(rows, plan=columns, already_known=db.emails_in_campaign(campaign))
        committed = bool(commit)

        if committed:
            if db.get_campaign(campaign) is None:
                db.add_campaign(Campaign(id=campaign, name=campaign, created_at=datetime.now(UTC)))
            for email, company, evidence in report.accepted:
                db.add_contact(
                    Contact(campaign_id=campaign, email=email, company=company, evidence=evidence)
                )

        return templates.TemplateResponse(
            request,
            "import.html",
            {
                "campaign": campaign,
                "sheet": sheet,
                "report": report,
                "committed": committed,
                "problems": grouped_problems(report),
                "noted": [o for o in report.outcomes if o.status is RowStatus.ACCEPTED and o.note],
                "campaigns": PlatformStore(db).rows(
                    "SELECT id,name FROM campaigns ORDER BY created_at DESC"
                ),
            },
        )

    # --- drafts and review --------------------------------------------------

    def _approved_note(note):
        """'approved-3-2-1' -> (3, 2, 1): approved, left with a maybe, left to fix."""
        parts = note.split("-")
        if len(parts) == 4 and parts[0] == "approved" and all(p.isdigit() for p in parts[1:]):
            return tuple(int(p) for p in parts[1:])
        return None

    def _latest_by_contact(db, campaign_id):
        """The newest draft for each contact — the one that matters."""
        latest = {}
        for d in db.drafts_in_campaign(campaign_id):  # newest first
            latest.setdefault(d.contact_id, d)
        return sorted(latest.values(), key=lambda d: (d.company or "").lower())

    @app.get("/campaigns/{campaign_id}/drafts", response_class=HTMLResponse)
    def drafts(request: Request, campaign_id: str, note: str = "", status: str = "", q: str = ""):
        db = store()
        all_rows = _latest_by_contact(db, campaign_id)
        counts = {state.value: sum(d.status is state for d in all_rows) for state in DraftStatus}
        rows = [
            d
            for d in all_rows
            if (not status or d.status.value == status)
            and q.casefold()
            in ((d.company or "") + " " + (d.email or "") + " " + d.subject).casefold()
        ]
        undrafted = [
            r["id"]
            for r in db._conn.execute(
                "SELECT id FROM contacts WHERE campaign_id = ? AND id NOT IN "
                "(SELECT contact_id FROM drafts)",
                (campaign_id,),
            )
        ]
        return templates.TemplateResponse(
            request,
            "drafts.html",
            {
                "campaign_id": campaign_id,
                "drafts": rows,
                "draft_counts": counts,
                "filter_status": status,
                "q": q,
                "metadata": PlatformStore(db).campaign(campaign_id),
                "tab": "drafts",
                "undrafted": len(undrafted),
                "in_review": sum(1 for d in rows if d.status is DraftStatus.REVIEW),
                "approved_note": _approved_note(note),
                "batch": min(len(undrafted), DRAFT_BATCH),
                "has_copy": load_copy(campaign_id) is not None,
                "copy_path": str(copy_path(campaign_id)),
                "has_closing": load_closing(campaign_id) is not None,
                "closing_path": str(closing_path(campaign_id)),
                "model": settings.llm_model,
                "note": note,
                "configuration_error": request.query_params.get("configuration_error", "")[:300],
            },
        )

    @app.post("/campaigns/{campaign_id}/approve-all")
    async def approve_all(request: Request, campaign_id: str):
        """Approve every draft in review that passes every check, as it stands
        now. A draft with a "maybe" line is left for you: that line is your
        call by design, and a bulk click is not a decision about it. Sends
        nothing — sending is still `outreach send --really`."""
        db = store()
        form = await request.form()
        latest = _latest_by_contact(db, campaign_id)
        if form.get("selection_required") or "draft_ids" in form:
            try:
                selected = {int(value) for value in form.getlist("draft_ids")}
            except ValueError:
                selected = set()
            if (
                not 1 <= len(selected) <= 250
                or not selected <= {d.id for d in latest}
                or not form.get("confirm_selection")
            ):
                return RedirectResponse(f"/campaigns/{campaign_id}/drafts?note=select-drafts", 303)
            latest = [draft for draft in latest if draft.id in selected]
        approved = maybe = to_fix = 0
        for draft in latest:
            if draft.email and db.is_suppressed(draft.email):
                to_fix += 1
                continue
            if draft.status is not DraftStatus.REVIEW:
                continue
            checked = _recheck(db, draft, draft.subject, draft.body)
            if checked is not None:
                # Keep the Check column true to what was just checked.
                db.update_draft(
                    draft.id,
                    subject=draft.subject,
                    body=draft.body,
                    verdict=checked.verdict.value,
                    checks=checks_for_display(checked),
                )
            if approval_blocker(checked):
                to_fix += 1
            elif checked.verdict is DraftVerdict.NEEDS_YOUR_CALL:
                maybe += 1
            else:
                db.set_draft_status(draft.id, DraftStatus.APPROVED)
                approved += 1
        return RedirectResponse(
            f"/campaigns/{campaign_id}/drafts?note=approved-{approved}-{maybe}-{to_fix}",
            status_code=303,
        )

    @app.post("/campaigns/{campaign_id}/draft")
    def write_drafts(campaign_id: str):
        """Draft every contact that has no draft yet. Takes about as many
        seconds as there are contacts."""
        with drafter.lock:
            if sender.busy or drafter.busy:
                return RedirectResponse(
                    f"/campaigns/{campaign_id}/drafts?note=busy", status_code=303
                )
            drafter.inline_busy = True
        try:
            db = store()
            if db.get_campaign(campaign_id) is None:
                raise HTTPException(404, "Campaign not found.")
            campaign_copy = load_copy(campaign_id)
            if not campaign_copy:
                return RedirectResponse(
                    f"/campaigns/{campaign_id}/drafts?note=no-copy", status_code=303
                )
            generation = generation_snapshot(campaign_id)
            campaign_copy = generation["campaign_copy"]
            if missing(*settings.llm_credentials()):
                return RedirectResponse(
                    f"/campaigns/{campaign_id}/drafts?note=no-key", status_code=303
                )
            llm = build_llm(settings)

            # Ten per click. Drafting takes a few seconds per contact, and a web
            # request that runs for minutes looks exactly like one that has hung.
            rows = db._conn.execute(
                "SELECT id FROM contacts WHERE campaign_id = ? AND id NOT IN "
                "(SELECT contact_id FROM drafts) ORDER BY id LIMIT ?",
                (campaign_id, DRAFT_BATCH),
            ).fetchall()
            failed = 0
            configuration_error = ""
            for row in rows:
                contact = db.get_contact(row["id"])
                if db.is_suppressed(contact.email):
                    continue
                try:
                    result = draft_email(
                        llm,
                        company=contact.company,
                        evidence=contact.evidence,
                        campaign_copy=campaign_copy,
                        sender=campaign_profile(campaign_id).sender_name or "",
                        closing=generation["closing"],
                    )
                except ValueError as exc:
                    configuration_error = str(exc)[:300]
                    failed += 1
                    continue
                except LLMError:
                    failed += 1
                    continue
                try:
                    db.save_draft(
                        contact_id=contact.id,
                        model=settings.llm_model,
                        subject=result.draft.subject,
                        body=storable_body(result),
                        verdict=result.verdict.value,
                        checks=checks_for_display(result),
                        generation=recipient_generation(generation, contact),
                    )
                except ValueError as exc:
                    configuration_error = str(exc)[:300]
                    failed += 1
                    break
            note = f"failed-{failed}" if failed else "drafted"
            query = urlencode({"note": note, "configuration_error": configuration_error})
            return RedirectResponse(f"/campaigns/{campaign_id}/drafts?{query}", status_code=303)
        finally:
            with drafter.lock:
                drafter.inline_busy = False

    def _tail_for(campaign_id):
        identity = campaign_profile(campaign_id)
        return email_tail(
            closing=load_closing(campaign_id),
            name=identity.sender_name or "(your name)",
            company=identity.sender_company or "(your company)",
            address=identity.sender_address or "(your address — required before sending)",
        )

    def _review_context(db, draft, *, error=None, checked=None):
        contact = db.get_contact(draft.contact_id)
        queue = _latest_by_contact(db, contact.campaign_id)
        positions = [i for i, entry in enumerate(queue) if entry.id == draft.id]
        position = positions[0] if positions else None
        nonce = secrets.token_urlsafe(32)
        try:
            sources = json.loads(contact.evidence.get("research_sources", "{}"))
        except (ValueError, TypeError):
            sources = {}
        sources = {
            key: {
                "url": public_url(value.get("source_url", "")),
                "retrieved_at": str(value.get("retrieved_at") or ""),
            }
            for key, value in (sources.items() if isinstance(sources, dict) else [])
            if isinstance(value, dict)
            and isinstance(value.get("source_url"), str)
            and public_url(value["source_url"])
        }
        return {
            "research_sources": sources,
            "metadata": PlatformStore(db).campaign(contact.campaign_id),
            "tab": "drafts",
            "previous_draft": queue[position - 1].id
            if position is not None and position > 0
            else None,
            "next_draft": queue[position + 1].id
            if position is not None and position + 1 < len(queue)
            else None,
            "queue_position": position + 1 if position is not None else None,
            "queue_count": len(queue),
            "tail": _tail_for(contact.campaign_id),
            "has_closing": load_closing(contact.campaign_id) is not None,
            "draft": draft,
            "generation_current": current_generation_matches(draft.generation)
            if draft.generation
            else None,
            "contact": contact,
            "campaign_id": contact.campaign_id,
            "error": error,
            "checks": checks_for_display(checked) if checked else draft.checks,
            "suppressed": db.is_suppressed(contact.email),
            "sender_email": campaign_profile(contact.campaign_id).sender_email or "",
            "test_nonce": nonce,
            "attachments": manifests(campaign_files(db._conn, contact.campaign_id)),
            "test_token": launch_review.issue(
                [
                    draft.id,
                    draft.subject,
                    draft.body,
                    nonce,
                    manifests(campaign_files(db._conn, contact.campaign_id)),
                ]
            ),
            "test_history": [
                {**dict(row), "attachments": saved_files(db._conn, row["id"], test=True)}
                for row in db._conn.execute(
                    "SELECT * FROM draft_test_runs WHERE draft_id=? ORDER BY rowid DESC LIMIT 5",
                    (draft.id,),
                )
            ],
        }

    def _recheck(db, draft, subject, body):
        contact = db.get_contact(draft.contact_id)
        checked = recheck(
            subject,
            body,
            evidence=contact.evidence,
            company=contact.company,
            campaign_copy=load_copy(contact.campaign_id) or "",
            sender=campaign_profile(contact.campaign_id).sender_name or "",
            closing=load_closing(contact.campaign_id),
        )
        if checked and draft.generation and not current_generation_matches(draft.generation):
            checked.checks.append(
                SentenceCheck(
                    text="Campaign instructions changed since generation.",
                    verdict=Verdict.UNSUPPORTED,
                    reason="Regenerate this draft using the saved campaign instructions.",
                )
            )
            checked.verdict = DraftVerdict.BLOCKED
        return checked

    @app.get("/drafts/{draft_id}", response_class=HTMLResponse)
    def review(request: Request, draft_id: int):
        db = store()
        draft = db.get_draft(draft_id)
        error = None
        if draft.status is not DraftStatus.SENT:
            # Checked against the closing as it is now: a draft written before
            # the closing existed says the offer and the sign-off twice (D-020).
            campaign_id = _campaign_of(db, draft)
            repeats = repeated_lines(
                draft.body,
                closing=load_closing(campaign_id),
                campaign_copy=load_copy(campaign_id) or "",
            )
            if repeats:
                lines = "; ".join(f"“{line}” — {reason}" for line, reason in repeats)
                error = (
                    f"Delete {len(repeats)} line(s) before approving — they repeat "
                    f"something: {lines}"
                )
        return templates.TemplateResponse(
            request, "review.html", _review_context(db, draft, error=error)
        )

    @app.post("/drafts/{draft_id}", response_class=HTMLResponse)
    def decide(
        request: Request,
        draft_id: int,
        subject: str = Form(""),
        body: str = Form(""),
        action: str = Form(...),
    ):
        """Save, approve or reject. Every path re-checks the current text."""
        db = store()
        draft = db.get_draft(draft_id)
        if draft.status is DraftStatus.SENT:
            return templates.TemplateResponse(
                request,
                "review.html",
                _review_context(db, draft, error="This one has already been sent."),
            )

        if action == "reject":
            db.set_draft_status(draft_id, DraftStatus.REJECTED)
            return RedirectResponse(f"/campaigns/{_campaign_of(db, draft)}/drafts", status_code=303)

        body = body.replace("\r\n", "\n").replace("\r", "\n")
        checked = _recheck(db, draft, subject, body)
        if checked is not None:
            db.update_draft(
                draft_id,
                subject=subject.strip(),
                body=body,
                verdict=checked.verdict.value,
                checks=checks_for_display(checked),
            )
            if subject.strip() != draft.subject or body != draft.body:
                db.set_draft_status(draft_id, DraftStatus.REVIEW)
            draft = db.get_draft(draft_id)

        if action == "approve":
            latest_id = db._conn.execute(
                "SELECT MAX(id) FROM drafts WHERE contact_id=?", (draft.contact_id,)
            ).fetchone()[0]
            if draft.id != latest_id:
                return templates.TemplateResponse(
                    request,
                    "review.html",
                    _review_context(
                        db,
                        draft,
                        error=(
                            "A newer draft exists. Open the current draft "
                            "from the campaign queue before approving."
                        ),
                    ),
                )
            blocker = approval_blocker(checked)
            if blocker:
                return templates.TemplateResponse(
                    request,
                    "review.html",
                    _review_context(db, draft, error=blocker, checked=checked),
                )
            db.set_draft_status(draft_id, DraftStatus.APPROVED)
            return RedirectResponse(f"/campaigns/{_campaign_of(db, draft)}/drafts", status_code=303)

        # "save" — back to the same page, showing the fresh check
        return templates.TemplateResponse(
            request, "review.html", _review_context(db, draft, checked=checked)
        )

    def _campaign_of(db, draft):
        return db.get_contact(draft.contact_id).campaign_id

    # --- what a send would do ----------------------------------------------

    def _launch_snapshot(db, campaign_id, planned, identity):
        metadata = PlatformStore(db).campaign(campaign_id)
        if not metadata:
            raise HTTPException(404, "Campaign not found.")
        return {
            "campaign": campaign_id,
            "attachments": manifests(campaign_files(db._conn, campaign_id)),
            "account": metadata["sender_account_id"],
            "sender": [
                identity.sender_name,
                str(identity.sender_email or ""),
                identity.sender_company,
                identity.sender_address,
            ],
            "copy": load_copy(campaign_id),
            "tail": _tail_for(campaign_id),
            "cap": settings.daily_send_cap,
            "gap": settings.send_gap_seconds,
            "emails": [
                [p.draft.id, p.draft.email, p.draft.subject, p.draft.body]
                for p in planned
                if p.will_send
            ],
        }

    @app.get("/campaigns/{campaign_id}/send", response_class=HTMLResponse)
    def send_preview(request: Request, campaign_id: str):
        """Review current emails; bind explicit launch consent to this snapshot."""
        db = store()
        planned = plan(
            db,
            campaign_id,
            daily_cap=settings.daily_send_cap,
            closing=load_closing(campaign_id),
            campaign_copy=load_copy(campaign_id) or "",
        )
        identity = campaign_profile(campaign_id)
        readiness = [
            n for n in identity.send_requirements if getattr(identity, n, None) in (None, "")
        ]
        try:
            identity = campaign_profile(campaign_id, require_verified=True)
            readiness = [
                n for n in identity.send_requirements if getattr(identity, n, None) in (None, "")
            ]
        except ConfigError as exc:
            readiness = [str(exc)]
        foot = _tail_for(campaign_id)
        return templates.TemplateResponse(
            request,
            "send.html",
            {
                "campaign_id": campaign_id,
                "planned": planned,
                "metadata": PlatformStore(db).campaign(campaign_id),
                "tab": "launch",
                "going": [p for p in planned if p.will_send],
                "footer": foot,
                "attachments": manifests(campaign_files(db._conn, campaign_id)),
                "sender": f"{identity.sender_name} <{identity.sender_email}>"
                if identity.sender_email
                else "No sending account selected",
                "cap": settings.daily_send_cap,
                "gap": settings.send_gap_seconds,
                "setup_missing": readiness,
                "busy": sender.busy,
                "launch_token": launch_review.issue(
                    _launch_snapshot(db, campaign_id, planned, identity)
                ),
            },
        )

    @app.post("/campaigns/{campaign_id}/send")
    def start_sending(campaign_id: str, launch_token: str = Form(""), confirm_send: str = Form("")):
        with mail_action_lock:
            return _start_sending(campaign_id, launch_token, confirm_send)

    def _start_sending(campaign_id, launch_token, confirm_send):
        """The real send (D-022). Same plan, same guards as `send --really`."""
        try:
            identity = campaign_profile(campaign_id, require_verified=True)
            identity.require(*identity.send_requirements)
            if drafter.busy:
                raise ConfigError("Wait for drafting to finish before sending.")
        except ConfigError:
            return RedirectResponse(f"/campaigns/{campaign_id}/send", status_code=303)
        db = store()
        try:
            planned = plan(
                db,
                campaign_id,
                daily_cap=settings.daily_send_cap,
                closing=load_closing(campaign_id),
                campaign_copy=load_copy(campaign_id) or "",
            )
            snapshot = _launch_snapshot(db, campaign_id, planned, identity)
            files = campaign_files(db._conn, campaign_id)
        finally:
            db._conn.close()
        if not confirm_send or not launch_review.matches(launch_token, snapshot):
            from urllib.parse import urlencode

            query = urlencode(
                {
                    "message": (
                        "Launch review changed or expired. Review the emails and sender below, "
                        "then confirm again. Nothing was sent."
                    )
                }
            )
            return RedirectResponse(f"/campaigns/{campaign_id}/send?{query}", status_code=303)
        job = sender.start(
            campaign_id=campaign_id,
            open_store=store,
            open_mailbox=lambda: mailbox(identity),
            daily_cap=settings.daily_send_cap,
            closing=load_closing(campaign_id),
            campaign_copy=load_copy(campaign_id) or "",
            sender_email=identity.sender_email,
            tail=_tail_for(campaign_id),
            gap_seconds=settings.send_gap_seconds,
            reviewed=planned,
            attachments=files,
        )
        if job:
            with platform_store() as db:
                db.conn.execute(
                    "UPDATE campaign_settings SET status='active' "
                    "WHERE campaign_id=? AND status='draft'",
                    (campaign_id,),
                )
        return RedirectResponse("/sending", status_code=303)

    @app.get("/campaigns/{campaign_id}/history", response_class=HTMLResponse)
    def campaign_history(request: Request, campaign_id: str, status: str = ""):
        with platform_store() as db:
            metadata = db.campaign(campaign_id)
            if not metadata:
                raise HTTPException(404, "Campaign not found.")
            entries = db.rows(
                "SELECT m.*,c.company,a.reply_id FROM messages m JOIN contacts c "
                "ON c.id=m.contact_id LEFT JOIN reply_sends a ON a.message_id=m.message_id "
                "WHERE c.campaign_id=? ORDER BY m.created_at DESC,m.id DESC",
                (campaign_id,),
            )
            for entry in entries:
                entry["attachments"] = saved_files(db.conn, entry["message_id"])
        totals = {
            key: sum(m["status"] == key for m in entries) for key in ("sent", "pending", "failed")
        }
        return templates.TemplateResponse(
            request,
            "history.html",
            {
                "campaign_id": campaign_id,
                "metadata": metadata,
                "tab": "history",
                "entries": [m for m in entries if not status or m["status"] == status],
                "totals": totals,
                "status": status,
            },
        )

    @app.get("/sending", response_class=HTMLResponse)
    def sending(request: Request):
        with platform_store() as db:
            metadata = db.campaign(sender.job.campaign_id) if sender.job else None
        return templates.TemplateResponse(
            request,
            "sending.html",
            {"job": sender.job, "gap": settings.send_gap_seconds, "metadata": metadata},
        )

    @app.post("/sending/stop")
    def stop_sending():
        sender.stop()
        return RedirectResponse("/sending", status_code=303)

    # --- one test email to yourself -----------------------------------------

    @app.post("/drafts/{draft_id}/test-send", response_class=HTMLResponse)
    def test_send(
        request: Request,
        draft_id: int,
        to: str = Form(""),
        test_nonce: str = Form(""),
        test_token: str = Form(""),
        confirmed: str = Form(""),
    ):
        with mail_action_lock:
            return _test_send(request, draft_id, to, test_nonce, test_token, confirmed)

    def _test_send(request, draft_id, to, test_nonce, test_token, confirmed):
        """Send this draft to your own address, marked [TEST]. Fenced like
        `send-test`: never to a contact, never recorded as a send (D-017)."""
        db = store()
        draft = db.get_draft(draft_id)
        campaign_id = _campaign_of(db, draft)

        def done(error=None, note=None):
            context = _review_context(db, draft, error=error)
            context["test_note"] = note
            return templates.TemplateResponse(request, "review.html", context)

        try:
            if sender.busy:
                raise ConfigError("Wait for campaign sending to finish before testing mail.")
            identity = campaign_profile(campaign_id, require_verified=True)
            identity.require(*identity.send_requirements)
        except ConfigError as exc:
            return done(error=f"Sending is not set up yet. {exc} See the Setup page.")
        blocker = approval_blocker(_recheck(db, draft, draft.subject, draft.body))
        if blocker:
            return done(error="Not sent: " + blocker)
        repeats = repeated_lines(
            draft.body,
            closing=load_closing(campaign_id),
            campaign_copy=load_copy(campaign_id) or "",
        )
        if repeats:
            lines = "; ".join(f"“{line}” — {reason}" for line, reason in repeats)
            return done(error=f"Not sent: delete the lines that repeat first. {lines}")
        try:
            address = str(TypeAdapter(EmailStr).validate_python(to or identity.sender_email or ""))
        except ValueError:
            return done(error="Not sent: enter a valid email address for your own inbox.")
        if db.is_suppressed(address) or db.is_contact(address):
            return done(
                error="Not sent: use your own inbox; campaign and suppressed addresses are blocked."
            )
        if (
            not confirmed
            or not 32 <= len(test_nonce) <= 100
            or not launch_review.matches(
                test_token,
                [
                    draft.id,
                    draft.subject,
                    draft.body,
                    test_nonce,
                    manifests(campaign_files(db._conn, campaign_id)),
                ],
            )
        ):
            return done(error="Not sent: review the saved draft and confirm this test again.")
        files = campaign_files(db._conn, campaign_id)
        db._conn.execute("SAVEPOINT test_with_files")
        try:
            saved = db._conn.execute(
                "INSERT OR IGNORE INTO draft_test_runs VALUES (?,?,?,?,?)",
                (
                    test_nonce,
                    draft_id,
                    address,
                    "pending",
                    "Outcome not recorded; inspect Sent before retrying.",
                ),
            )
            if saved.rowcount:
                for file in files:
                    db._conn.execute(
                        "INSERT INTO draft_test_attachments VALUES (?,?)", (test_nonce, file.id)
                    )
            db._conn.execute("RELEASE test_with_files")
        except Exception:
            db._conn.execute("ROLLBACK TO test_with_files")
            db._conn.execute("RELEASE test_with_files")
            raise
        if not saved.rowcount:
            return done(error="This test request already ran. Check saved results and your inbox.")

        def outcome(status, message):
            db._conn.execute(
                "UPDATE draft_test_runs SET status=?,result=? WHERE id=?",
                (status, message, test_nonce),
            )
            return done(error=message) if status != "accepted" else done(note=message)

        try:
            send_test(
                store=db,
                mailbox=mailbox(identity),
                to=address,
                subject=draft.subject,
                attachments=files,
                body_text=f"{draft.body}\n\n{_tail_for(campaign_id)}",
                message_id=new_message_id(identity.sender_email),
            )
        except MailUncertainError:
            return outcome(
                "uncertain",
                "Test outcome uncertain. Inspect Sent and your inbox; do not retry yet.",
            )
        except (NotATestAddressError, SuppressedRecipientError, MailError):
            return outcome(
                "failed", "The test was refused. Check account verification and permissions."
            )
        return outcome(
            "accepted",
            f"Provider accepted the test to {address}, marked [TEST]. Check arrival and spam.",
        )

    # --- setup ----------------------------------------------------------------

    def _setup_rows():
        described = {
            "parallel_api_key": "Key for web research (Parallel)",
            "openrouter_api_key": "Key for the AI model (OpenRouter)",
            "anthropic_api_key": "Key for the AI model (Anthropic)",
            "mail_smtp_host": "Zoho sending server (smtppro.zoho.in)",
            "mail_imap_host": "Zoho inbox server, for replies (imappro.zoho.in)",
            "mail_username": "Zoho login (your email address)",
            "mail_password": "Zoho app password",
            "sender_name": "Your name, as it appears on emails",
            "sender_email": "Your email address",
            "sender_company": "Company name",
            "sender_address": "Company address",
        }
        names = ("parallel_api_key", *settings.llm_credentials(), *settings.SEND, "mail_imap_host")
        return [
            {"var": f"OUTREACH_{n.upper()}", "what": described.get(n, n), "set": not missing(n)}
            for n in dict.fromkeys(names)
        ]

    @app.get("/setup", response_class=HTMLResponse)
    def setup(request: Request, result: str = "", ok: str = ""):
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "rows": _setup_rows(),
                "model": settings.llm_model,
                "sender": f"{settings.sender_name or '(not set)'} <{settings.sender_email or '—'}>",
                "cap": settings.daily_send_cap,
                "gap": settings.send_gap_seconds,
                "result": result,
                "ok": ok == "1",
                "accounts": platform_store().accounts(),
                "research_budget": settings.research_daily_budget_usd,
                "parallel_ready": bool(settings.parallel_api_key),
                "openrouter_ready": bool(settings.openrouter_api_key),
                "openrouter_check_available": True,
                "max_budget": settings.research_max_budget_usd,
            },
        )

    @app.post("/setup/providers/check-openrouter")
    def check_provider():
        from urllib.parse import quote

        try:
            message = (provider_check or check_openrouter)(settings)
        except ConfigError as exc:
            return RedirectResponse("/setup?result=" + quote(str(exc)), 303)
        return RedirectResponse("/setup?ok=1&result=" + quote(message), 303)

    @app.post("/setup/providers")
    async def save_providers(request: Request):
        from urllib.parse import quote

        form = await request.form()
        if researcher.active or drafter.busy or sender.busy:
            return RedirectResponse(
                "/setup?result=" + quote("Finish current work before changing provider keys."), 303
            )
        updates = {
            name: form.get(name, "").strip()
            for name in ("parallel_api_key", "openrouter_api_key")
            if form.get(name, "").strip()
        }
        try:
            if not updates:
                raise ConfigError("Paste a new key to update a provider. Existing keys are kept.")
            provider_credentials.save(updates)
        except ConfigError as exc:
            return RedirectResponse("/setup?result=" + quote(str(exc)), 303)
        return RedirectResponse(
            "/setup?ok=1&result="
            + quote("Keys saved privately. No paid request was made. Existing .env is unchanged."),
            303,
        )

    @app.post("/setup/mail")
    def check_mail():
        from urllib.parse import quote

        try:
            settings.require(*settings.SEND)
            box = mailbox(settings)
            verify = getattr(box, "verify_login", None)
            if verify is not None:
                verify()
            checked = "Zoho accepted the login for sending"
            verify_inbox = getattr(box, "verify_inbox", None)
            if settings.mail_imap_host and verify_inbox is not None:
                verify_inbox()
                checked += " and for reading replies"
        except (ConfigError, MailError) as exc:
            return RedirectResponse(f"/setup?result={quote(str(exc))}", status_code=303)
        message = f"{checked}. Nothing was sent or read."
        return RedirectResponse(f"/setup?ok=1&result={quote(message)}", status_code=303)

    @app.post("/setup/model")
    def check_model():
        from urllib.parse import quote

        from pydantic import BaseModel

        class Ping(BaseModel):
            ok: bool

        try:
            settings.require(*settings.llm_credentials())
            build_llm(settings).generate(
                prompt="Reply with ok set to true. Nothing else.", schema=Ping, max_tokens=64
            )
        except (ConfigError, LLMError) as exc:
            return RedirectResponse(f"/setup?result={quote(str(exc))}", status_code=303)
        message = f"{settings.llm_model} answered. The key works."
        return RedirectResponse(f"/setup?ok=1&result={quote(message)}", status_code=303)

    # --- replies ------------------------------------------------------------

    def _check_inbox(account_filter=""):
        from outreach.core.replies import CheckResult

        with platform_store() as db:
            account_ids = [a["id"] for a in db.accounts() if a["verified_at"]]
        if account_filter:
            if account_filter not in account_ids:
                raise ConfigError("Choose a verified sending account to check.")
            account_ids = [account_filter]
        elif not missing(*settings.SEND, "mail_imap_host"):
            account_ids.append(None)
        if not account_ids:
            raise ConfigError("Connect and verify an email account first.")
        total = CheckResult()
        failures = []
        for account_id in account_ids:
            db = MailboxStore(connect(settings.db_path), account_id)
            try:
                identity = account_settings(settings, account_id, require_verified=True)
                llm = build_llm(settings) if not missing(*settings.llm_credentials()) else None
                result = check_replies(
                    db,
                    mailbox(identity),
                    llm,
                    own_address=identity.sender_email or "",
                    offer_for=lambda cid: load_copy(cid) or "",
                    sender=identity.sender_name or "",
                    sender_company=identity.sender_company or "",
                )
                total.new += result.new
                total.ignored += result.ignored
                total.unread += result.unread
                total.suppressed.extend(result.suppressed)
            except (ConfigError, MailError):
                failures.append(
                    "An account could not be checked. Verify its credentials and inbox "
                    "access in Email accounts."
                )
            finally:
                db._conn.close()
        if failures:
            raise MailError(f"{total.new} replies saved. " + failures[0])
        return total

    if poll_minutes:
        inbox.poll_every(poll_minutes, _check_inbox)

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox_page(
        request: Request,
        show: str = "new",
        campaign_id: str = "",
        category: str = "",
        account_id: str = "",
    ):
        with platform_store() as workspace_db:
            accounts = workspace_db.accounts()
            campaigns = workspace_db.rows("SELECT id,name FROM campaigns ORDER BY created_at DESC")
            mailbox_reply_ids = (
                {
                    r["reply_id"]
                    for r in workspace_db.rows(
                        "SELECT reply_id FROM reply_mailboxes WHERE account_id=?", (account_id,)
                    )
                }
                if account_id
                else None
            )
        replies = [
            r
            for r in store().list_replies()
            if (not campaign_id or r.campaign_id == campaign_id)
            and (not category or r.category == category)
            and (mailbox_reply_ids is None or r.id in mailbox_reply_ids)
        ]
        new = [r for r in replies if r.status is ReplyStatus.NEW]
        return templates.TemplateResponse(
            request,
            "inbox.html",
            {
                "replies": new if show == "new" else replies,
                "show": show,
                "new_count": len(new),
                "all_count": len(replies),
                "labels": LABELS,
                "checker": inbox,
                "accounts": accounts,
                "campaigns": campaigns,
                "account_id": account_id,
                "campaign_id": campaign_id,
                "category": category,
                "setup_missing": []
                if any(a["verified_at"] for a in accounts)
                else missing(*settings.SEND, "mail_imap_host"),
                "polling": poll_minutes,
            },
        )

    @app.post("/inbox/check")
    def check_inbox_now(
        account_id: str = Form(""),
        campaign_id: str = Form(""),
        category: str = Form(""),
        show: str = Form("new"),
    ):

        inbox.check(lambda: _check_inbox(account_id))
        query = urlencode(
            {
                "account_id": account_id,
                "campaign_id": campaign_id,
                "category": category,
                "show": show,
            }
        )
        return RedirectResponse("/inbox?" + query, status_code=303)

    def _reply_context(db, reply, *, error=None, note=None, draft=None):
        original = db.find_message(reply.message_id) if reply.message_id else None
        attempt = db._conn.execute(
            "SELECT a.message_id,m.status,m.body_text,m.created_at FROM reply_sends a "
            "LEFT JOIN messages m ON m.message_id=a.message_id WHERE a.reply_id=?",
            (reply.id,),
        ).fetchone()
        blocked_attempt = attempt and attempt["status"] != "failed"
        with platform_store() as workspace_db:
            account_row = workspace_db.one(
                "SELECT a.email,a.label FROM reply_mailboxes b JOIN mail_accounts a ON "
                "a.id=b.account_id WHERE b.reply_id=?",
                (reply.id,),
            )
            metadata = workspace_db.campaign(reply.campaign_id) if reply.campaign_id else None
        return {
            "reply": reply,
            "original": original,
            "label": LABELS.get(ReplyCategory(reply.category), reply.category)
            if reply.category
            else "Not read yet",
            "error": error,
            "note": note,
            "answer": draft if draft is not None else reply.suggested_reply,
            "can_answer": reply.contact_id is not None
            and reply.category != ReplyCategory.BOUNCE
            and not db.is_suppressed(reply.from_address)
            and not blocked_attempt,
            "suppressed": db.is_suppressed(reply.from_address),
            "attempt": dict(attempt) if attempt else None,
            "account": account_row,
            "metadata": metadata,
            "campaign_id": reply.campaign_id,
            "tab": "replies",
        }

    @app.get("/replies/{reply_id}", response_class=HTMLResponse)
    def reply_page(request: Request, reply_id: int):
        db = store()
        reply = db.get_reply(reply_id)
        return templates.TemplateResponse(request, "reply.html", _reply_context(db, reply))

    @app.post("/replies/{reply_id}/send", response_class=HTMLResponse)
    def answer_reply(request: Request, reply_id: int, body: str = Form("")):
        with mail_action_lock:
            return _answer_reply(request, reply_id, body)

    def _answer_reply(request, reply_id, body):
        db = store()
        reply = db.get_reply(reply_id)
        try:
            if sender.busy:
                raise CannotReplyError("Wait for campaign sending to finish before answering.")
            with platform_store() as platform:
                row = platform.one(
                    "SELECT account_id FROM reply_mailboxes WHERE reply_id=?", (reply_id,)
                )
                identity = account_settings(
                    settings, row["account_id"] if row else None, require_verified=True
                )
            identity.require(*identity.send_requirements)
            send_reply(
                db,
                mailbox(identity),
                reply,
                body=body,
                message_id=new_message_id(identity.sender_email),
                daily_cap=settings.daily_send_cap,
            )
        except MailUncertainError:
            return templates.TemplateResponse(
                request,
                "reply.html",
                _reply_context(
                    db,
                    reply,
                    error=(
                        "Answer outcome is uncertain. Check message history and the provider's "
                        "Sent folder; do not send it again."
                    ),
                    draft=body,
                ),
            )
        except (CannotReplyError, ConfigError, MailError, SuppressedRecipientError) as exc:
            return templates.TemplateResponse(
                request,
                "reply.html",
                _reply_context(db, reply, error=f"Not sent: {exc}", draft=body),
            )
        return RedirectResponse("/inbox?show=new", status_code=303)

    @app.post("/replies/{reply_id}/done")
    def reply_done(reply_id: int, undo: str = Form("")):
        store().set_reply_status(reply_id, ReplyStatus.NEW if undo else ReplyStatus.DONE)
        return RedirectResponse("/inbox" if not undo else f"/replies/{reply_id}", status_code=303)

    # --- the do-not-contact list -------------------------------------------

    @app.get("/suppressions", response_class=HTMLResponse)
    def suppressions(request: Request):
        db = store()
        rows = [
            dict(r) for r in db._conn.execute("SELECT * FROM suppressions ORDER BY created_at DESC")
        ]
        return templates.TemplateResponse(
            request, "suppressions.html", {"rows": rows, "reasons": list(SuppressionReason)}
        )

    @app.post("/suppressions")
    def add_suppression(email: str = Form(...), reason: str = Form(...), note: str = Form("")):
        store().add_suppression(email, SuppressionReason(reason), note or None)
        return RedirectResponse("/suppressions", status_code=303)

    # --- backup -------------------------------------------------------------

    @app.post("/backup", response_class=HTMLResponse)
    def backup(request: Request):
        db = store()
        try:
            if sender.busy or drafter.busy or researcher.active:
                raise BackupError(
                    "Wait for sending, drafting and research to finish before backing up."
                )
            destination, manifest = backup_workspace(db._conn, settings)
            context = {
                "destination": str(destination),
                "counts": manifest["counts"],
                "download": destination.name,
                "has_key": manifest["contains_mailbox_key"],
            }
        except BackupError as exc:
            context = {"error": str(exc)}
        finally:
            db._conn.close()
        return templates.TemplateResponse(request, "backup.html", context)

    @app.get("/backups/{name}")
    def download_backup(name: str):
        import re

        if not re.fullmatch(r"workspace-[a-f0-9]{32}\.zip", name):
            raise HTTPException(404, "Backup not found.")
        directory = Path(settings.db_path).resolve().parent / "backups"
        target = directory / name
        if not target.is_file() or target.is_symlink():
            raise HTTPException(404, "Backup not found.")
        return FileResponse(target, media_type="application/zip", filename=name)

    return app
