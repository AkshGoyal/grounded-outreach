"""Campaign file upload/remove/download, with no mail or provider calls."""

from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile

from outreach.core.attachments import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, manifests, upload_name
from outreach.web.platform import redirect


def install_attachments(app, templates, open_store, sender, drafter, action_lock):
    def editable(db, cid):
        item = db.campaign(cid)
        if not item:
            raise HTTPException(404, "Campaign not found.")
        if sender.busy or drafter.busy:
            raise ValueError("Wait for sending or drafting to finish before changing attachments.")
        if item["status"] in ("completed", "archived"):
            raise ValueError("Reopen this campaign in Settings before changing attachments.")

    @app.get("/campaigns/{campaign_id}/attachments")
    def attachment_page(request: Request, campaign_id: str):
        with open_store() as db:
            item = db.campaign(campaign_id)
            if not item:
                raise HTTPException(404, "Campaign not found.")
            return templates.TemplateResponse(
                request,
                "attachments.html",
                {
                    "campaign_id": campaign_id,
                    "metadata": item,
                    "tab": "message",
                    "attachments": manifests(db.attachment_files(campaign_id)),
                    "busy": sender.busy or drafter.busy,
                },
            )

    @app.post("/campaigns/{campaign_id}/attachments")
    async def upload(request: Request, campaign_id: str):
        uploads = []
        total = 0
        try:
            # Bound the entire multipart stream, including parser spool files.
            original_receive = request._receive
            received = 0

            async def limited_receive():
                nonlocal received
                message = await original_receive()
                received += len(message.get("body", b""))
                if received > MAX_ATTACHMENT_BYTES + 256 * 1024:
                    raise ValueError("Upload exceeds 10 MB. Choose smaller files.")
                return message

            request._receive = limited_receive
            # Starlette spools uploads to disk; bound both file count and content read.
            async with request.form(max_files=MAX_ATTACHMENTS, max_fields=5) as form:
                for value in form.getlist("files"):
                    if not isinstance(value, UploadFile) or not value.filename:
                        continue
                    name = upload_name(value.filename)
                    data = await value.read(MAX_ATTACHMENT_BYTES + 1 - total)
                    total += len(data)
                    if total > MAX_ATTACHMENT_BYTES:
                        raise ValueError(
                            "Use at most 5 attachments, with a combined size of 10 MB."
                        )
                    uploads.append((name, data))
            if not uploads:
                raise ValueError("Choose at least one attachment to upload.")
            with action_lock, open_store() as db:
                editable(db, campaign_id)
                with db.transaction():
                    count = db.add_attachments(campaign_id, uploads)
                    if count:
                        db.invalidate_approvals(campaign_id)
            return redirect(
                "/campaigns/" + campaign_id + "/attachments",
                f"{count} attachments added. Review and approve unsent drafts again.",
            )
        except ValueError as exc:
            return redirect("/campaigns/" + campaign_id + "/attachments", str(exc))

    @app.post("/campaigns/{campaign_id}/attachments/{file_id}/remove")
    def remove(campaign_id: str, file_id: str):
        try:
            with action_lock, open_store() as db:
                editable(db, campaign_id)
                with db.transaction():
                    changed = db.remove_attachment(campaign_id, file_id)
                    if changed:
                        db.invalidate_approvals(campaign_id)
            return redirect(
                "/campaigns/" + campaign_id + "/attachments",
                "File removed from future emails. Saved message history keeps its original files.",
            )
        except ValueError as exc:
            return redirect("/campaigns/" + campaign_id + "/attachments", str(exc))

    @app.get("/campaigns/{campaign_id}/attachments/{file_id}/download")
    def download(campaign_id: str, file_id: str):
        with open_store() as db:
            file = db.attachment(campaign_id, file_id)
            if not file:
                raise HTTPException(404, "Attachment not found.")
        return Response(
            file.content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(file.filename, safe=""),
                "X-Content-Type-Options": "nosniff",
            },
        )
