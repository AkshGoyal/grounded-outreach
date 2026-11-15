"""Saved-audience handoff and attachments through fake mail; no live operations."""

import base64
import json
import re
import sqlite3
import time
from email import policy
from email.parser import BytesParser

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.attachments import campaign_files, saved_files
from outreach.adapters.mail_smtp_imap import SmtpImapMailbox
from outreach.campaigns import save_texts
from outreach.core.attachments import MAX_ATTACHMENT_BYTES, EmailAttachment
from outreach.core.models import Contact, DraftStatus, OutboundMessage
from outreach.core.sending import send_message
from outreach.ports.mail import MailError, MailUncertainError
from outreach.web.app import create_app
from outreach.wiring import account_settings
from tests.helpers import confirm_draft_test, confirm_launch
from tests.test_oauth_mail import RAW, connected
from tests.test_oauth_mail import oauth_settings as oauth_settings
from tests.test_platform import VerifiedMailbox, db_for, saved_lead, verified_account


@pytest.fixture
def files_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = settings.model_copy(update={"send_gap_seconds": 0, "app_password": "fake-login"})
    box = VerifiedMailbox()
    app = create_app(config, mailbox=lambda identity: box)
    client = TestClient(app)
    client.post("/login", data={"password": config.app_password})
    with db_for(config) as db:
        account = verified_account(db, config)
        db.save_campaign("files", "File campaign", None, "sales", "", account, "draft")
        contact = db.store.add_contact(
            Contact(campaign_id="files", email="buyer@example.com", company="Example Buyer")
        )
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="grounded",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    save_texts("files", copy="We offer samples.", closing="")
    return config, app, client, box, contact, draft


def upload(client, name="Brochure.pdf", content=b"%PDF-1.4 fictional brochure"):
    return client.post(
        "/campaigns/files/attachments", files=[("files", (name, content, "application/pdf"))]
    )


def wait(app):
    deadline = time.monotonic() + 5
    while app.state.sender.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.state.sender.busy


def test_upload_review_test_send_launch_history_and_backup(files_workspace, tmp_path):
    config, app, client, box, contact, draft = files_workspace
    message = client.get("/campaigns/files/message").text
    assert "Add or manage attachments" in message and "Add attachments" in message
    assert "1 attachments added" in upload(client).text
    with db_for(config) as db:
        file = campaign_files(db.conn, "files")[0]
        assert db.store.get_draft(draft).status == DraftStatus.REVIEW
    url = f"/campaigns/files/attachments/{file.id}/download"
    download = client.get(url)
    assert download.content == file.content
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "Brochure.pdf" in client.get(f"/drafts/{draft}").text
    assert confirm_draft_test(client, draft, "sender@gmail.com").status_code == 200
    assert box.sent[0].attachments == (file,)
    with db_for(config) as db:
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
        receipt = db.one("SELECT id FROM draft_test_runs")
        assert saved_files(db.conn, receipt["id"], test=True)[0]["id"] == file.id
    assert "Brochure.pdf" in client.get("/campaigns/files/send").text
    confirm_launch(client, "/campaigns/files/send")
    wait(app)
    assert len(box.sent) == 2 and box.sent[-1].attachments == (file,)
    history = client.get("/campaigns/files/history").text
    assert "Attachment:" in history and "Brochure.pdf" in history
    client.post(f"/campaigns/files/attachments/{file.id}/remove")
    assert client.get(url).content == file.content
    assert "Brochure.pdf" in client.get("/campaigns/files/history").text
    with (
        sqlite3.connect(config.db_path) as source,
        sqlite3.connect(tmp_path / "restored.db") as target,
    ):
        source.backup(target)
        target.row_factory = sqlite3.Row
        assert (
            saved_files(target, box.sent[-1].message_id)[0]["sha256"] == file.manifest()["sha256"]
        )
        assert (
            bytes(target.execute("SELECT content FROM campaign_attachments").fetchone()[0])
            == file.content
        )
    assert not app.state.research.active


def test_changed_files_invalidate_launch_and_test_tokens(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    launch = client.get("/campaigns/files/send").text
    launch_token = re.search(r'name="launch_token" value="([^"]+)"', launch)[1]
    review = client.get(f"/drafts/{draft}").text
    test = {
        key: re.search(r'name="' + key + r'" value="([^"]+)"', review)[1]
        for key in ("test_nonce", "test_token")
    }
    upload(client)
    # Even if the draft is approved again, the older launch remains invalid.
    with db_for(config) as db:
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    reply = client.post(
        "/campaigns/files/send", data={"confirm_send": "on", "launch_token": launch_token}
    )
    assert "Launch review changed" in reply.text and not box.sent
    reply = client.post(
        f"/drafts/{draft}/test-send", data={**test, "confirmed": "on", "to": "sender@gmail.com"}
    )
    assert "confirm this test again" in reply.text and not box.sent
    assert not app.state.sender.busy


@pytest.mark.parametrize(
    "name,content",
    [
        ("bad.exe", b"binary"),
        ("bad\r\nname.pdf", b"fake"),
        ("empty.pdf", b""),
        ("big.pdf", b"x" * (MAX_ATTACHMENT_BYTES + 1)),
    ],
    ids=["executable", "header-injection", "empty", "too-large"],
)
def test_invalid_uploads_do_not_change_approval(files_workspace, name, content):
    config, app, client, box, contact, draft = files_workspace
    assert upload(client, name, content).status_code in (200, 400)
    with db_for(config) as db:
        assert not campaign_files(db.conn, "files")
        assert db.store.get_draft(draft).status == DraftStatus.APPROVED
    assert not box.sent


def test_file_count_total_size_duplicate_and_busy_guards(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    upload(client)
    upload(client)
    with db_for(config) as db:
        assert len(campaign_files(db.conn, "files")) == 1
    response = client.post(
        "/campaigns/files/attachments",
        files=[("files", (f"file{i}.txt", b"a", "text/plain")) for i in range(6)],
    )
    assert response.status_code == 400
    response = client.post(
        "/campaigns/files/attachments",
        files=[
            ("files", (f"big{i}.txt", b"x" * (6 * 1024 * 1024), "text/plain")) for i in range(2)
        ],
    )
    assert "10 MB" in response.text
    # Use a genuine runner job state rather than sending.
    from outreach.web.jobs import SendJob

    app.state.sender.job = SendJob(campaign_id="files", total=1)
    response = upload(client, "another.pdf", b"other")
    assert "Wait for sending" in response.text
    with db_for(config) as db:
        files = campaign_files(db.conn, "files")
        assert len(files) == 1
    client.post(f"/campaigns/files/attachments/{files[0].id}/remove")
    with db_for(config) as db:
        assert len(campaign_files(db.conn, "files")) == 1
    app.state.sender.job.finished = True


def test_attachment_download_requires_login_and_campaign_match(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    upload(client, "C:\\fakepath\\CV.pdf")
    with db_for(config) as db:
        file = campaign_files(db.conn, "files")[0]
        assert file.filename == "CV.pdf"
    assert client.get(f"/campaigns/other/attachments/{file.id}/download").status_code == 404
    other = TestClient(app)
    assert (
        other.get(
            f"/campaigns/files/attachments/{file.id}/download", follow_redirects=False
        ).headers["location"]
        == "/login"
    )


def test_atomic_pending_row_file_binding_and_uncertain_history(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    upload(client)
    with db_for(config) as db:
        file = campaign_files(db.conn, "files")[0]
        altered = file.model_copy(update={"content": b"tampered"})
        with pytest.raises(ValueError):
            send_message(
                store=db.store,
                mailbox=box,
                contact_id=contact,
                to="buyer@example.com",
                subject="Hello",
                body_text="Hello.",
                message_id="<bad@example.com>",
                attachments=(altered,),
            )
        assert not db.one("SELECT * FROM messages") and not box.sent
        box.fail_next = MailUncertainError("Fake uncertain result")
        with pytest.raises(MailUncertainError):
            send_message(
                store=db.store,
                mailbox=box,
                contact_id=contact,
                to="buyer@example.com",
                subject="Hello",
                body_text="Hello.",
                message_id="<pending@example.com>",
                attachments=(file,),
            )
        assert db.one("SELECT status FROM messages")["status"] == "pending"
        assert saved_files(db.conn, "<pending@example.com>")[0]["id"] == file.id


def test_mime_attachment_preserves_bytes_filename_and_threading(settings):
    file = EmailAttachment(
        id="fake", filename="CV.pdf", mime_type="application/pdf", content=b"CV bytes"
    )
    box = SmtpImapMailbox(
        settings.model_copy(update={"sender_company": "Fake", "sender_address": "Fake address"})
    )
    message = OutboundMessage(
        to="own@example.com",
        subject="Hello",
        body_text="Body.",
        message_id="<ours@example.com>",
        in_reply_to="<prior@example.com>",
        attachments=(file,),
    )
    raw = box.build(message).as_bytes()
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    attachment = list(parsed.iter_attachments())[0]
    assert (
        attachment.get_filename() == "CV.pdf"
        and attachment.get_payload(decode=True) == file.content
    )
    assert parsed["In-Reply-To"] == "<prior@example.com>"
    assert parsed.get_body(preferencelist=("plain",)).get_content().strip() == "Body."


@pytest.mark.parametrize("provider", ["gmail", "zoho"])
def test_oauth_attachment_wire_protocol(oauth_settings, provider):
    service, requests, key = connected(oauth_settings, provider)
    identity = account_settings(oauth_settings, key)
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/attachments"):
            assert request.content == b"CV bytes"
            assert request.url.params["fileName"] == "CV.pdf"
            assert request.headers["content-type"] == "application/octet-stream"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attachmentName": "CV.pdf",
                            "attachmentPath": "private/provider/path",
                            "storeName": "provider-file",
                        }
                    ]
                },
            )
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "gmail-id"} if provider == "gmail" else {"data": {"messageId": "987"}},
            )
        return httpx.Response(200, json={"data": {"content": RAW}})

    service.client = httpx.Client(transport=httpx.MockTransport(handler))
    file = EmailAttachment(
        id="fake", filename="CV.pdf", mime_type="application/pdf", content=b"CV bytes"
    )
    service.mailbox(identity).send(
        OutboundMessage(
            to="own@example.com",
            subject="Test",
            body_text="Hello.",
            message_id="<ours@example.com>",
            attachments=(file,),
        )
    )
    if provider == "gmail":
        raw = base64.urlsafe_b64decode(json.loads(calls[0].content)["raw"])
        assert (
            list(BytesParser(policy=policy.default).parsebytes(raw).iter_attachments())[
                0
            ].get_payload(decode=True)
            == file.content
        )
    else:
        assert len([r for r in calls if r.method == "POST"]) == 2
        payload = json.loads(calls[1].content)
        assert payload["attachments"] == [
            {
                "attachmentName": "CV.pdf",
                "attachmentPath": "private/provider/path",
                "storeName": "provider-file",
            }
        ]
        assert payload["content"] == "Hello."


def test_zoho_failed_upload_never_posts_email(oauth_settings):
    service, requests, key = connected(oauth_settings, "zoho")
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("fake-timeout", request=request)

    service.client = httpx.Client(transport=httpx.MockTransport(fail))
    file = EmailAttachment(
        id="fake", filename="CV.pdf", mime_type="application/pdf", content=b"CV bytes"
    )
    with pytest.raises(MailError) as error:
        service.mailbox(account_settings(oauth_settings, key)).send(
            OutboundMessage(
                to="own@example.com",
                subject="Test",
                body_text="Hello.",
                message_id="<ours@example.com>",
                attachments=(file,),
            )
        )
    assert not isinstance(error.value, MailUncertainError)
    assert len(calls) == 1 and calls[0].url.path.endswith("/attachments")


def test_saved_audience_handoff_checks_review_origin_reuse_and_duplicates(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        run = db.lead(lead)["run_id"]
    research_page = client.get("/research/" + run).text
    assert f'href="/research/{run}?stage=all#contact-review"' in research_page
    assert "Add selected to campaign" in research_page
    assert "sales@mills.example" in client.get("/research/" + run + "/use").text
    assert "1 ready to add" in client.get("/campaigns/files/audience").text
    client.post(
        "/research/" + run + "/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    with db_for(config) as db:
        assert len(db.store.emails_in_campaign("files")) == 2
        assert db.lead(lead)["review_status"] == "approved"
    page = client.get("/research/" + run + "/use?campaign_id=files").text
    assert "sales@mills.example" in page and 'value="files" selected' in page
    assert "1 ready to add" in client.get("/campaigns/files/audience").text
    response = client.post(
        "/research/" + run + "/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "1 already in this campaign" in response.text
    response = client.post(
        "/research/" + run + "/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "1 already in this campaign" in response.text
    with db_for(config) as db:
        assert len(db.store.emails_in_campaign("files")) == 2
        db.save_campaign("other", "Other campaign", None, "sales", "", "", "draft")
    response = client.post(
        "/research/" + run + "/use",
        data={"lead_ids": str(lead), "campaign_id": "other", "action": "existing"},
    )
    assert "acknowledge prior outreach" in response.text
    response = client.post(
        "/research/" + run + "/use",
        data={
            "lead_ids": str(lead),
            "campaign_id": "other",
            "action": "existing",
            "acknowledge_prior": "on",
        },
    )
    assert "1 contacts added" in response.text
    assert not box.sent


def test_handoff_empty_audience_new_campaign_and_cross_audience_guard(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        run = db.lead(lead)["run_id"]
        db.review_leads([lead], action="approve", confirmed=True)
        empty = db.new_run(
            title="Saved goal only",
            brief="Find manufacturers",
            purpose="sales",
            tags="",
            project_id=None,
            target=5,
            budget=100000,
        )
    assert "no researched contacts yet" in client.get("/research/" + empty + "/use").text
    reply = client.post(
        "/research/" + empty + "/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "Some contacts changed" in reply.text
    reply = client.post(
        "/research/" + run + "/use",
        data={"lead_ids": str(lead), "action": "new"},
        follow_redirects=False,
    )
    assert reply.headers["location"].startswith("/campaigns/new?list_id=")
    assert "Mills" in client.get(reply.headers["location"]).text
    assert not box.sent


def test_invalid_message_brief_keeps_uploaded_file_summary(files_workspace):
    config, app, client, box, contact, draft = files_workspace
    upload(client)
    response = client.post("/campaigns/files/message", data={"tone": "invalid-tone"})
    assert response.status_code == 400
    assert "Brochure.pdf" in response.text and "entries are kept" in response.text
    assert not box.sent
