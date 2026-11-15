"""OAuth security and real adapter protocols against HTTP fakes; never live mail."""

import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.credential_vault import CredentialVault
from outreach.adapters.mailbox_store import MailboxStore
from outreach.adapters.oauth_mail import OAuthMail
from outreach.config import ConfigError
from outreach.core.models import MessageStatus, OutboundMessage
from outreach.core.sending import send_message
from outreach.ports.mail import MailAuthError, MailUncertainError
from outreach.web.app import create_app
from outreach.wiring import account_settings
from tests.helpers import confirm_launch
from tests.test_platform import VerifiedMailbox, db_for, verified_account

VALUES = {
    "label": "Career",
    "sender_name": "Candidate",
    "company": "Personal outreach",
    "address": "Test address",
}
RAW = (
    "From: candidate@example.com\r\nTo: own@example.com\r\nSubject: Test\r\n"
    "Message-ID: <remote@zoho>\r\nIn-Reply-To: <original@example.com>\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n\r\nHello."
)


@pytest.fixture
def oauth_settings(settings):
    return settings.model_copy(
        update={
            "send_gap_seconds": 0,
            "app_password": "test-login",
            "oauth_public_url": "https://app.example.com",
            "allowed_hosts": "app.example.com,testserver",
            "google_client_id": "fake-client",
            "google_client_secret": "fake-client-secret",
            "zoho_client_id": "fake-zoho-client",
            "zoho_client_secret": "fake-zoho-secret",
        }
    )


def provider_service(settings, provider="gmail", fail=None, scopes=True):
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/token"):
            token = {
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "expires_in": 3600,
            }
            if scopes:
                token["scope"] = (
                    "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
                    if provider == "gmail"
                    else "ZohoMail.accounts.READ ZohoMail.messages.READ ZohoMail.messages.CREATE"
                )
            return httpx.Response(200, json=token)
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "candidate@example.com"})
        if path.endswith("/api/accounts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "ZOHO_ACCOUNT",
                            "enabled": True,
                            "primaryEmailAddress": "candidate@example.com",
                            "accountId": "123",
                        }
                    ]
                },
            )
        if request.method == "POST":
            if fail == "timeout":
                raise httpx.ReadTimeout("secret-access", request=request)
            if fail:
                return httpx.Response(fail, json={"error": "secret-access"})
            return httpx.Response(
                200,
                json={"id": "gmail-id"} if provider == "gmail" else {"data": {"messageId": "987"}},
            )
        if path.endswith("originalmessage"):
            return httpx.Response(200, json={"data": {"content": RAW}})
        if path.endswith("/gmail-id"):
            return httpx.Response(
                200, json={"raw": base64.urlsafe_b64encode(RAW.encode()).decode().rstrip("=")}
            )
        if path.endswith("/messages/search"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"messages": []})

    return OAuthMail(settings, httpx.Client(transport=httpx.MockTransport(handler))), requests


def connected(settings, provider="gmail", fail=None):
    service, requests = provider_service(settings, provider, fail)
    url = service.begin(provider, "in", VALUES, "browser")
    state = parse_qs(urlsplit(url).query)["state"][0]
    payload = service.consume(provider, state, "browser")
    key = service.complete(provider, payload, "fake-code")
    return service, requests, key


def test_authorization_is_browser_bound_encrypted_one_time_and_pkce(oauth_settings):
    service, requests = provider_service(oauth_settings)
    url = service.begin("gmail", "com", VALUES, "browser")
    query = parse_qs(urlsplit(url).query)
    state = query["state"][0]
    assert query["code_challenge_method"] == ["S256"]
    assert "secret" not in url and "code_verifier" not in url
    with db_for(oauth_settings) as db:
        row = db.one("SELECT * FROM oauth_attempts")
        assert "Candidate" not in row["payload_cipher"] and state != row["state_hash"]
    for provider, browser in [("gmail", "wrong"), ("zoho", "browser")]:
        with pytest.raises(ConfigError):
            service.consume(provider, state, browser)
    payload = service.consume("gmail", state, "browser")
    assert len(payload["verifier"]) > 40
    with pytest.raises(ConfigError):
        service.consume("gmail", state, "browser")
    assert not requests


def test_expired_and_missing_state_never_exchange_tokens(oauth_settings):
    service, requests = provider_service(oauth_settings)
    state = parse_qs(urlsplit(service.begin("gmail", "com", VALUES, "browser")).query)["state"][0]
    with db_for(oauth_settings) as db:
        db.conn.execute("UPDATE oauth_attempts SET expires_at=0")
    for value in [state, "", "made-up"]:
        with pytest.raises(ConfigError):
            service.consume("gmail", value, "browser")
    assert not requests


@pytest.mark.parametrize(
    "update",
    [
        {"app_password": None},
        {"google_client_secret": None},
        {"oauth_public_url": "http://app.example.com"},
        {"oauth_public_url": "https://app.example.com/path"},
        {"oauth_public_url": "https://evil.example.com"},
    ],
)
def test_unconfigured_or_insecure_setup_is_not_ready(oauth_settings, update):
    assert not OAuthMail(oauth_settings.model_copy(update=update)).readiness()["gmail"]["ready"]


@pytest.mark.parametrize("provider", ["gmail", "zoho"])
def test_connection_verifies_identity_encrypts_tokens_without_sending(oauth_settings, provider):
    service, requests, key = connected(oauth_settings, provider)
    with db_for(oauth_settings) as db:
        account = db.account(key)
        secret = db.one("SELECT token_cipher FROM mail_oauth WHERE account_id=?", (key,))
        assert account["verified_at"] and account["oauth_provider"] == provider
        assert "token" not in json.dumps(account) and "secret-access" not in secret["token_cipher"]
        assert "secret-refresh" in CredentialVault(oauth_settings).decrypt(secret["token_cipher"])
    assert [r for r in requests if r.method == "POST"] == [requests[0]]
    identity = account_settings(oauth_settings, key, require_verified=True)
    assert identity.mail_account_id == key and identity.mail_password is None
    identity.require(*identity.send_requirements)
    service.mailbox(identity).verify_login()


def test_missing_refresh_token_never_saves_account(oauth_settings):
    def handler(request):
        return httpx.Response(200, json={"access_token": "secret", "expires_in": 3600})

    service = OAuthMail(oauth_settings, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MailAuthError, match="Offline access"):
        service.complete("gmail", {"region": "com", "values": VALUES, "verifier": "test"}, "code")
    with db_for(oauth_settings) as db:
        assert not db.accounts()


@pytest.mark.parametrize("provider", ["gmail", "zoho"])
def test_send_records_provider_mapping_and_uses_plaintext(oauth_settings, provider):
    service, requests, key = connected(oauth_settings, provider)
    identity = account_settings(oauth_settings, key)
    message = OutboundMessage(
        to="own@example.com", subject="Test", body_text="Hello.", message_id="<local@example.com>"
    )
    sent = service.mailbox(identity).send(message)
    assert sent.message_id == message.message_id
    sends = [r for r in requests if r.method == "POST" and not r.url.path.endswith("/token")]
    assert len(sends) == 1
    data = json.loads(sends[0].content)
    if provider == "gmail":
        raw = base64.urlsafe_b64decode(data["raw"])
        assert b"Message-ID: <local@example.com>" in raw and b"Hello." in raw
    else:
        assert data["mailFormat"] == "plaintext" and data["content"] == "Hello."
    with db_for(oauth_settings) as db:
        mapping = db.one("SELECT * FROM mail_api_ids WHERE account_id=?", (key,))
        assert mapping["mime_id"] == (
            message.message_id if provider == "gmail" else "<remote@zoho>"
        )


@pytest.mark.parametrize("fail", [500, "timeout"])
def test_uncertain_send_never_retries_and_retains_pending(oauth_settings, fail):
    service, requests, key = connected(oauth_settings, fail=fail)
    from datetime import UTC, datetime

    from outreach.core.models import Campaign, Contact

    with db_for(oauth_settings) as db:
        db.store.add_campaign(Campaign(id="test", name="test", created_at=datetime.now(UTC)))
        contact = db.store.add_contact(
            Contact(campaign_id="test", email="own@example.com", evidence={})
        )
        with pytest.raises(MailUncertainError) as exc:
            send_message(
                store=db.store,
                mailbox=service.mailbox(account_settings(oauth_settings, key)),
                contact_id=contact,
                to="own@example.com",
                subject="Test",
                body_text="Hello.",
                message_id="<local@example.com>",
            )
        assert "secret-access" not in str(exc.value)
        assert db.one("SELECT status FROM messages")["status"] == MessageStatus.PENDING
    assert (
        len([r for r in requests if r.method == "POST" and not r.url.path.endswith("/token")]) == 1
    )


def test_expired_access_refreshes_and_persists_without_exposing_secret(oauth_settings):
    service, requests, key = connected(oauth_settings)
    with db_for(oauth_settings) as db:
        row = db.one("SELECT token_cipher FROM mail_oauth WHERE account_id=?", (key,))
        tokens = json.loads(CredentialVault(oauth_settings).decrypt(row["token_cipher"]))
        tokens["expires_at"] = 0
        db.conn.execute(
            "UPDATE mail_oauth SET token_cipher=? WHERE account_id=?",
            (CredentialVault(oauth_settings).encrypt(json.dumps(tokens)), key),
        )
    service.mailbox(account_settings(oauth_settings, key)).verify_inbox()
    calls = [r for r in requests if r.url.path.endswith("/token")]
    assert len(calls) == 2 and b"grant_type=refresh_token" in calls[-1].content
    assert "secret-refresh" not in str(calls[-1].url)


def test_zoho_alias_lookup_and_reply_thread_are_account_scoped(oauth_settings):
    service, requests, key = connected(oauth_settings, "zoho")
    from datetime import UTC, datetime

    from outreach.core.models import Contact

    with db_for(oauth_settings) as db:
        db.save_campaign("test", "Test", None, "sales", "", key)
        contact = db.store.add_contact(
            Contact(campaign_id="test", email="own@example.com", evidence={})
        )
        db.store.record_pending_send(
            contact_id=contact,
            message_id="<local@example.com>",
            recipient_email="own@example.com",
            subject="Test",
            body_text="Hello.",
        )
        db.store.mark_send_outcome("<local@example.com>", MessageStatus.SENT, datetime.now(UTC))
    box = service.mailbox(account_settings(oauth_settings, key))
    box.remember("<local@example.com>", "987", "<remote@zoho>")
    with db_for(oauth_settings) as db:
        assert (
            MailboxStore(db.conn, key).find_message("<remote@zoho>").message_id
            == "<local@example.com>"
        )
        assert MailboxStore(db.conn, "different-account").find_message("<remote@zoho>") is None
    box.remember("inbound:<reply@zoho>", "888", "<reply@zoho>")
    box.send(
        OutboundMessage(
            to="own@example.com",
            subject="Re: Test",
            body_text="Reply.",
            message_id="<answer@example.com>",
            in_reply_to="<reply@zoho>",
        )
    )
    call = [r for r in requests if r.method == "POST" and not r.url.path.endswith("/token")][-1]
    assert call.url.path.endswith("/messages/888") and json.loads(call.content)["action"] == "reply"


def test_oauth_routes_require_login_and_bind_secure_callback_cookie(oauth_settings):
    service, requests = provider_service(oauth_settings)
    client = TestClient(
        create_app(oauth_settings, oauth_service=lambda: service),
        base_url="https://app.example.com",
    )
    assert (
        client.post("/accounts/oauth/gmail/start", data=VALUES, follow_redirects=False).headers[
            "location"
        ]
        == "/login"
    )
    client.post("/login", data={"password": "test-login"})
    assert client.get("/accounts").headers["referrer-policy"] == "same-origin"
    response = client.post("/accounts/oauth/gmail/start", data=VALUES, follow_redirects=False)
    assert (
        "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    )
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    client.cookies.delete("outreach_session")
    response = client.get(
        "/accounts/oauth/gmail/callback",
        params={"state": state, "code": "fake"},
        follow_redirects=False,
    )
    assert "connected" in response.headers["location"]
    assert response.headers["referrer-policy"] == "no-referrer"
    with db_for(oauth_settings) as db:
        assert len(db.accounts()) == 1
    count = len(requests)
    client.get("/accounts/oauth/gmail/callback", params={"state": state, "code": "fake"})
    assert len(requests) == count


def test_account_test_requires_confirmation_and_blocks_replayed_forms(oauth_settings):
    box = VerifiedMailbox()
    client = TestClient(
        create_app(oauth_settings, mailbox=lambda s: box), base_url="https://app.example.com"
    )
    client.post("/login", data={"password": "test-login"})
    with db_for(oauth_settings) as db:
        key = verified_account(db, oauth_settings)
    data = {"to": "own@example.com", "nonce": "a" * 40}
    client.post("/accounts/" + key + "/test", data=data)
    assert not box.sent
    data["confirmed"] = "on"
    client.post("/accounts/" + key + "/test", data=data)
    client.post("/accounts/" + key + "/test", data=data)
    assert len(box.sent) == 1 and box.sent[0].subject.startswith("[TEST]")
    with db_for(oauth_settings) as db:
        assert db.one("SELECT status FROM mail_test_runs")["status"] == "accepted"
        assert not db.one("SELECT 1 FROM messages")


def test_partial_google_consent_never_verifies_account(oauth_settings):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "access_token": "secret",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            },
        )

    service = OAuthMail(oauth_settings, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(MailAuthError, match="permissions"):
        service.complete("gmail", {"region": "com", "values": VALUES, "verifier": "test"}, "code")
    with db_for(oauth_settings) as db:
        assert not db.accounts()


@pytest.mark.parametrize("provider", ["gmail", "zoho"])
def test_inbox_reads_raw_replies_without_mutating_mail(oauth_settings, provider):
    service, requests, key = connected(oauth_settings, provider)
    raw = RAW.encode()
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/messages/search"):
            return httpx.Response(200, json={"data": [{"messageId": "11"}]})
        if request.url.path.endswith("originalmessage"):
            return httpx.Response(200, json={"data": {"content": RAW}})
        if request.url.path.endswith("/messages"):
            if request.url.params.get("pageToken"):
                return httpx.Response(200, json={"messages": []})
            return httpx.Response(200, json={"messages": [{"id": "11"}], "nextPageToken": "second"})
        return httpx.Response(200, json={"raw": base64.urlsafe_b64encode(raw).decode()})

    service.client = httpx.Client(transport=httpx.MockTransport(handler))
    replies = service.mailbox(account_settings(oauth_settings, key)).fetch_replies()
    assert len(replies) == 1 and replies[0].in_reply_to == "<original@example.com>"
    assert replies[0].body_text == "Hello."
    assert all(r.method == "GET" for r in calls)
    if provider == "gmail":
        assert any(r.url.params.get("pageToken") == "second" for r in calls)
    else:
        with db_for(oauth_settings) as db:
            assert (
                db.one("SELECT remote_id FROM mail_api_ids WHERE account_id=?", (key,))["remote_id"]
                == "11"
            )


def test_schema_seven_accounts_remain_password_accounts_after_upgrade(oauth_settings):
    with db_for(oauth_settings) as db:
        key = verified_account(db, oauth_settings)
        for table in ("mail_oauth", "oauth_attempts", "mail_api_ids", "mail_test_runs"):
            db.conn.execute("DROP TABLE " + table)
        db.conn.execute("UPDATE schema_meta SET value='7' WHERE key='schema_version'")
    with db_for(oauth_settings) as db:
        assert db.account(key)["verified_at"] and db.account(key)["oauth_provider"] is None
    identity = account_settings(oauth_settings, key)
    assert identity.mail_account_id is None and identity.mail_password == "fake-app-password"


def test_oauth_test_delivery_and_uncertainty_persist_without_duplicate_send(oauth_settings):
    service, requests, key = connected(oauth_settings, fail="timeout")
    app = create_app(oauth_settings, mailbox=service.mailbox, oauth_service=lambda: service)
    client = TestClient(app, base_url="https://app.example.com")
    client.post("/login", data={"password": "test-login"})
    data = {"to": "own@example.com", "nonce": "uncertain" * 5, "confirmed": "on"}
    for _ in range(2):
        client.post("/accounts/" + key + "/test", data=data)
    with db_for(oauth_settings) as db:
        assert db.one("SELECT status FROM mail_test_runs")["status"] == "uncertain"
    assert (
        len([r for r in requests if r.method == "POST" and not r.url.path.endswith("/token")]) == 1
    )


def test_approved_campaign_sends_through_its_oauth_identity(oauth_settings, monkeypatch, tmp_path):
    from outreach.core.models import Contact, DraftStatus
    from tests.test_campaign_workspace import BRIEF

    monkeypatch.chdir(tmp_path)
    service, requests, key = connected(oauth_settings)
    app = create_app(oauth_settings, mailbox=service.mailbox, oauth_service=lambda: service)
    client = TestClient(app, base_url="https://app.example.com")
    client.post("/login", data={"password": "test-login"})
    response = client.post(
        "/campaigns/new",
        data=BRIEF | {"name": "OAuth campaign", "purpose": "job search", "account_id": key},
        follow_redirects=False,
    )
    cid = response.headers["location"].split("/")[-1]
    with db_for(oauth_settings) as db:
        contact = db.store.add_contact(
            Contact(campaign_id=cid, email="owned@fictional.example", evidence={})
        )
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    confirm_launch(client, "/campaigns/" + cid + "/send")
    deadline = time.monotonic() + 5
    while app.state.sender.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    with db_for(oauth_settings) as db:
        assert db.one("SELECT status FROM messages")["status"] == "sent"
        assert db.store.get_draft(draft).status is DraftStatus.SENT
    request = [r for r in requests if r.url.path.endswith("/messages/send")][0]
    raw = base64.urlsafe_b64decode(json.loads(request.content)["raw"])
    assert b"candidate@example.com" in raw and b"owned@fictional.example" in raw
    assert b"test@example.com" not in raw


def test_reconnect_same_email_preserves_account_and_demotes_unsent_approvals(oauth_settings):
    from outreach.core.models import Contact, DraftStatus

    service, requests, key = connected(oauth_settings)
    with db_for(oauth_settings) as db:
        db.save_campaign("test", "Test", None, "job search", "", key)
        first = db.store.add_contact(
            Contact(campaign_id="test", email="owned@fictional.example", evidence={})
        )
        second = db.store.add_contact(
            Contact(campaign_id="test", email="sent@fictional.example", evidence={})
        )
        unsent = db.store.save_draft(
            contact_id=first,
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        sent = db.store.save_draft(
            contact_id=second,
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(unsent, DraftStatus.APPROVED)
        db.store.set_draft_status(sent, DraftStatus.SENT)
    service.complete(
        "gmail", {"region": "com", "values": VALUES, "verifier": "fake"}, "another-code"
    )
    with db_for(oauth_settings) as db:
        assert len(db.accounts()) == 1 and db.accounts()[0]["id"] == key
        assert db.store.get_draft(unsent).status is DraftStatus.REVIEW
        assert db.store.get_draft(sent).status is DraftStatus.SENT


def test_local_disconnect_keeps_history_blocks_cached_tokens_and_requires_confirmation(
    oauth_settings,
):
    from outreach.core.models import Contact, DraftStatus

    service, requests, key = connected(oauth_settings)
    cached_box = service.mailbox(account_settings(oauth_settings, key))
    with db_for(oauth_settings) as db:
        db.save_campaign("career", "Career", None, "job search", "", key)
        contact = db.store.add_contact(
            Contact(campaign_id="career", email="owned@fictional.example", evidence={})
        )
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    client = TestClient(
        create_app(oauth_settings, oauth_service=lambda: service),
        base_url="https://app.example.com",
    )
    client.post("/login", data={"password": "test-login"})
    client.post("/accounts/" + key + "/disconnect")
    with db_for(oauth_settings) as db:
        assert db.account(key)["verified_at"]
    client.post("/accounts/" + key + "/disconnect", data={"confirmed": "on"})
    with db_for(oauth_settings) as db:
        assert db.account(key)["verified_at"] is None
        assert db.campaign("career")["sender_account_id"] == key
        assert db.store.get_draft(draft).status is DraftStatus.REVIEW
        assert (
            db.one("SELECT token_cipher FROM mail_oauth WHERE account_id=?", (key,))["token_cipher"]
            == ""
        )
    count = len(requests)
    with pytest.raises(MailAuthError, match="disconnected"):
        cached_box.verify_inbox()
    assert len(requests) == count


def test_test_outcome_history_is_visible_after_a_new_app_instance(oauth_settings):
    with db_for(oauth_settings) as db:
        key = verified_account(db, oauth_settings)
        db.conn.execute(
            "INSERT INTO mail_test_runs VALUES (?,?,?,?,?)",
            ("a" * 40, key, "owned@fictional.example", "uncertain", "Inspect Sent; do not resend."),
        )
    client = TestClient(create_app(oauth_settings), base_url="https://app.example.com")
    client.post("/login", data={"password": "test-login"})
    page = client.get("/accounts/" + key + "/test")
    assert "Recent test requests" in page.text and "Inspect Sent; do not resend." in page.text


def test_refused_api_permissions_clear_verified_status_without_leaking_tokens(oauth_settings):
    service, requests, key = connected(oauth_settings)
    service.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"error": "secret-access"})
        )
    )
    with pytest.raises(MailAuthError) as exc:
        service.mailbox(account_settings(oauth_settings, key)).verify_inbox()
    assert "secret-access" not in str(exc.value)
    with db_for(oauth_settings) as db:
        assert db.account(key)["verified_at"] is None
        assert "reconnect" in db.account(key)["last_error"].lower()
