"""Provider connection and explicitly confirmed test delivery. Adapters are injected."""

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from pydantic import EmailStr, TypeAdapter
from starlette.concurrency import run_in_threadpool

from outreach.config import ConfigError
from outreach.core.dispatch import new_message_id
from outreach.core.sending import NotATestAddressError, SuppressedRecipientError, send_test
from outreach.ports.mail import MailError, MailUncertainError
from outreach.web.platform import redirect


def install_oauth(app, settings, templates, oauth, open_store, profile, mailbox, sender, drafter):
    @app.get("/accounts/oauth")
    def setup(request: Request):
        return templates.TemplateResponse(
            request,
            "oauth_setup.html",
            {
                "readiness": oauth().readiness(),
                "public_url": settings.oauth_public_url or "",
                "https_seen": request.url.scheme == "https",
                "peer": request.client.host if request.client else "unknown",
            },
        )

    @app.post("/accounts/oauth/{provider}/start")
    async def start(request: Request, provider: str):
        form = await request.form()
        try:
            if sender.busy or drafter.busy:
                raise ConfigError(
                    "Wait for drafting and sending to finish before connecting accounts."
                )
            service = oauth()
            config = service.configuration(provider, form.get("region", "com"))
            if request.url.scheme != "https" or urlsplit(
                config["redirect_uri"]
            ).netloc != request.headers.get("host"):
                raise ConfigError("Open the configured HTTPS app URL before connecting an account.")
            values = {
                k: form.get(k, "").strip() for k in ("label", "sender_name", "company", "address")
            }
            if any(not 1 <= len(v) <= 300 for v in values.values()):
                raise ConfigError("Supply the label, sender name, organization and postal address.")
            browser = secrets.token_urlsafe(32)
            url = service.begin(provider, form.get("region", "com"), values, browser)
            response = redirect(url)
            response.set_cookie(
                "outreach_oauth",
                browser,
                httponly=True,
                secure=True,
                samesite="lax",
                path="/accounts/oauth",
                max_age=600,
            )
            return response
        except ConfigError as exc:
            return redirect("/accounts/oauth", str(exc))

    @app.get("/accounts/oauth/{provider}/callback")
    async def callback(request: Request, provider: str):
        try:
            service = oauth()
            config = service.configuration(provider)
            if request.url.scheme != "https" or urlsplit(
                config["redirect_uri"]
            ).netloc != request.headers.get("host"):
                raise ConfigError("Open the configured HTTPS app URL before connecting.")
            payload = service.consume(
                provider,
                request.query_params.get("state", ""),
                request.cookies.get("outreach_oauth", ""),
            )
            if request.query_params.get("error") or not request.query_params.get("code"):
                raise ConfigError("Provider sign-in was cancelled. No account was connected.")
            if sender.busy or drafter.busy:
                raise ConfigError(
                    "A job started during sign-in. Finish it and reconnect the account."
                )
            await run_in_threadpool(
                service.complete, provider, payload, request.query_params["code"]
            )
            message = (
                "OAuth account connected. Sign into the workspace to continue. No email was sent."
            )
        except (ConfigError, MailError, ValueError, KeyError, TypeError):
            message = (
                "Account was not connected. Check setup and permissions, then start sign-in again."
            )
        response = redirect("/accounts", message)
        response.delete_cookie(
            "outreach_oauth", path="/accounts/oauth", secure=True, samesite="lax"
        )
        return response

    @app.get("/accounts/{account_id}/test")
    def test_page(request: Request, account_id: str):
        with open_store() as db:
            account = db.account(account_id)
            history = db.rows(
                "SELECT recipient,status,result FROM mail_test_runs "
                "WHERE account_id=? ORDER BY rowid DESC LIMIT 10",
                (account_id,),
            )
        if not account:
            raise HTTPException(404, "Account not found.")
        return templates.TemplateResponse(
            request,
            "mail_test.html",
            {
                "account": account,
                "nonce": secrets.token_urlsafe(32),
                "history": history,
            },
        )

    @app.post("/accounts/{account_id}/test")
    async def test_delivery(request: Request, account_id: str):
        form = await request.form()
        try:
            if sender.busy:
                raise ConfigError("Wait for campaign sending to finish before testing mail.")
            recipient = str(TypeAdapter(EmailStr).validate_python(form.get("to", ""))).casefold()
            nonce = form.get("nonce", "")
            if not form.get("confirmed") or not 32 <= len(nonce) <= 100:
                raise ConfigError("Confirm the recipient and test delivery before sending.")
            identity = profile(account_id)
            identity.require(*identity.send_requirements)
            with open_store() as db:
                account = db.account(account_id)
                if not account or not account["verified_at"]:
                    raise ConfigError("Verify this account before sending a test.")
                if db.store.is_suppressed(recipient) or db.store.is_contact(recipient):
                    raise ConfigError(
                        "Use your own inbox. Campaign and suppressed addresses are blocked."
                    )
                with db.transaction():
                    if db.one("SELECT 1 FROM mail_test_runs WHERE id=?", (nonce,)):
                        raise ConfigError(
                            "This request already ran. Check your inbox before another test."
                        )
                    db.conn.execute(
                        "INSERT INTO mail_test_runs VALUES (?,?,?,?,?)",
                        (nonce, account_id, recipient, "pending", ""),
                    )

            def perform():
                with open_store() as db:
                    return send_test(
                        store=db.store,
                        mailbox=mailbox(identity),
                        to=recipient,
                        subject="Outreach connection check",
                        body_text="This is a mail connection test you requested. "
                        "No campaign was launched. Confirm arrival and check spam. "
                        "Reply TEST REPLY to test receipt in your provider inbox.",
                        message_id=new_message_id(identity.sender_email),
                    )

            try:
                await run_in_threadpool(perform)
                status, message = (
                    "accepted",
                    "Provider accepted the test. Confirm arrival and spam placement in your inbox.",
                )
            except MailUncertainError:
                status, message = (
                    "uncertain",
                    "Delivery uncertain. Inspect Sent and the destination; do not retry yet.",
                )
            except (MailError, ConfigError, NotATestAddressError, SuppressedRecipientError):
                status, message = (
                    "failed",
                    "The test was refused. Check account verification and permissions.",
                )
            with open_store() as db:
                db.conn.execute(
                    "UPDATE mail_test_runs SET status=?,result=? WHERE id=?",
                    (status, message, nonce),
                )
            return redirect("/accounts/" + account_id + "/test", message)
        except (ConfigError, ValueError):
            return redirect(
                "/accounts/" + account_id + "/test",
                "Test not started. Check verification, confirmation and recipient.",
            )

    @app.post("/accounts/{account_id}/disconnect")
    async def disconnect(request: Request, account_id: str):
        form = await request.form()
        if not form.get("confirmed") or sender.busy or drafter.busy:
            return redirect("/accounts", "Confirm disconnect after active jobs finish.")
        with open_store() as db, db.transaction():
            if not db.one("SELECT 1 FROM mail_oauth WHERE account_id=?", (account_id,)):
                return redirect("/accounts", "Choose a connected OAuth account.")
            db.conn.execute(
                "UPDATE mail_oauth SET token_cipher='' WHERE account_id=?", (account_id,)
            )
            db.conn.execute(
                "UPDATE mail_accounts SET verified_at=NULL,last_error=? WHERE id=?",
                ("Disconnected from this tool. Reconnect OAuth to use this account.", account_id),
            )
            db.conn.execute(
                "UPDATE drafts SET status='review' WHERE status='approved' AND contact_id IN "
                "(SELECT c.id FROM contacts c JOIN campaign_settings s "
                "ON s.campaign_id=c.campaign_id "
                "WHERE s.sender_account_id=?)",
                (account_id,),
            )
        return redirect(
            "/accounts",
            "Disconnected from this tool. Campaign history is preserved. "
            "You can also revoke this app in your provider's connected-app settings.",
        )
