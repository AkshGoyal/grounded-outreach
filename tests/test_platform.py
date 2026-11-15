"""Offline research-to-outreach acceptance, spending and mailbox isolation tests."""

import json
import time
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.credential_vault import CredentialVault
from outreach.adapters.db import connect
from outreach.adapters.mailbox_store import MailboxStore
from outreach.adapters.platform_store import PlatformStore
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.store_sqlite import SqliteStore
from outreach.core.dispatch import dispatch, plan
from outreach.core.models import DraftStatus, InboundMessage, MessageStatus, SuppressionReason
from outreach.core.research import (
    Assessment,
    ResearchStop,
    checked_facts,
    published_emails,
    text_windows,
)
from outreach.core.research_flow import run_research
from outreach.core.sending import send_message
from outreach.ports.mail import MailAuthError, MailUncertainError
from outreach.web.app import create_app
from outreach.wiring import campaign_settings
from tests.fakes.mail import FakeMailbox
from tests.helpers import confirm_launch

PLAN = {
    "summary": "Find textile manufacturers in Tiruppur.",
    "criteria": ["Makes textiles"],
    "queries": ["Tiruppur textile manufacturers"],
    "alternate_queries": ["Tiruppur mills"],
    "exclusions": ["Wholesalers"],
}
SOURCE = {
    "url": "https://mills.example/contact",
    "title": "Example Mills",
    "full_content": (
        "Example Mills makes textiles in Tiruppur. "
        "Contact sales@mills.example for business enquiries."
    ),
}


class VerifiedMailbox(FakeMailbox):
    def verify_login(self):
        pass

    def verify_inbox(self):
        pass


def db_for(settings):
    return PlatformStore(SqliteStore(connect(settings.db_path)))


def make_account(db, settings, email="sender@gmail.com"):
    return db.save_account(
        {
            "label": email,
            "email": email,
            "sender_name": "Verified Sender",
            "company": "Sender Co",
            "address": "123 Sender Street",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465,
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "username": email,
        },
        CredentialVault(settings).encrypt("fake-app-password"),
    )


def verified_account(db, settings, email="sender@gmail.com"):
    key = make_account(db, settings, email)
    db.conn.execute(
        "UPDATE mail_accounts SET verified_at=? WHERE id=?", (datetime.now(UTC).isoformat(), key)
    )
    return key


def saved_lead(db):
    run = db.new_run(
        title="Mills",
        brief="Find textile manufacturers in Tiruppur.",
        purpose="sales",
        tags="",
        project_id=None,
        target=1,
        budget=300000,
    )
    key = db.add_candidate(
        run,
        {
            "company": "Example Mills",
            "website": SOURCE["url"],
            "identity_quote": "Example Mills makes textiles",
            "source_id": "s1",
        },
    )
    db.save_evidence(
        key,
        facts=[
            {
                "criterion": "Makes textiles",
                "status": "supported",
                "quote": "Example Mills makes textiles",
                "source_url": SOURCE["url"],
            }
        ],
        sources=[
            {"text": SOURCE["full_content"], "url": SOURCE["url"], "retrieved_at": "2026-10-04"}
        ],
        emails=[
            {
                "value": "sales@mills.example",
                "quote": "Contact sales@mills.example",
                "source_url": SOURCE["url"],
                "retrieved_at": "2026-10-04",
            }
        ],
        flags=[],
        summary="Manufacturer",
    )
    return key


def wait_for(app, run_id):
    end = time.monotonic() + 5
    while run_id in app.state.research.active and time.monotonic() < end:
        time.sleep(0.01)
    assert run_id not in app.state.research.active, "Fake research worker did not finish."


def fake_provider(calls):
    def respond(request):
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith(("/search", "/extract")):
            return httpx.Response(200, json={"results": [SOURCE]})
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        value = (
            PLAN
            if name == "researchplan"
            else {
                "candidates": [
                    {
                        "company": "Example Mills",
                        "website": SOURCE["url"],
                        "source_id": "s1",
                        "identity_quote": "Example Mills makes textiles in Tiruppur.",
                    }
                ]
            }
            if name == "candidates"
            else {
                "facts": [
                    {
                        "criterion_index": 1,
                        "status": "supported",
                        "source_id": "s1",
                        "quote": "Example Mills makes textiles in Tiruppur.",
                    }
                ],
                "fit_summary": "A textile manufacturer.",
                "unknowns": [],
            }
        )
        return httpx.Response(
            200,
            json={
                "usage": {"cost": 0.001},
                "choices": [{"message": {"content": json.dumps(value)}}],
            },
        )

    return respond


def test_browser_research_requires_plan_and_lead_approvals_before_campaign(
    settings, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    settings = settings.model_copy(
        update={"parallel_api_key": "fake", "openrouter_api_key": "fake"}
    )
    calls = []
    app = create_app(
        settings,
        mailbox=lambda s: VerifiedMailbox(),
        research_api=lambda db, key: ResearchAPI(
            settings,
            db,
            key,
            client=httpx.Client(transport=httpx.MockTransport(fake_provider(calls))),
        ),
    )
    client = TestClient(app)
    for page in ("/research", "/lists", "/accounts", "/campaigns", "/campaigns/new"):
        assert client.get(page).status_code == 200
    response = client.post(
        "/research",
        data={"brief": "Find textile manufacturers in Tiruppur.", "target": "1", "budget": ".30"},
        follow_redirects=False,
    )
    key = response.headers["location"].split("/")[-1]
    wait_for(app, key)
    assert len(calls) == 1 and calls[0][0].endswith("/chat/completions")
    with db_for(settings) as db:
        assert db.run(key)["status"] == "awaiting_approval"
        assert db.leads(key) == []
    assert client.get("/research/" + key).status_code == 200
    client.post(
        "/research/" + key + "/approve",
        data={
            "summary": PLAN["summary"],
            "criteria": "Makes textiles",
            "queries": PLAN["queries"][0],
            "alternate_queries": PLAN["alternate_queries"][0],
            "confirm": "1",
        },
    )
    wait_for(app, key)
    with db_for(settings) as db:
        assert db.run(key)["status"] == "completed", db.run(key)["error"]
        lead = db.leads(key)[0]
        assert lead["review_status"] == "pending"
        assert lead["emails"][0]["value"] == "sales@mills.example"
        # Direct homepage read avoids a redundant contact search.
        assert db.run(key)["spent_micro"] == 5000
        account = verified_account(db, settings)
    assert client.get("/leads/" + str(lead["id"])).status_code == 200
    assert (
        client.post(
            "/lists", data={"name": "Audience", "lead_ids": str(lead["id"])}, follow_redirects=False
        )
        .headers["location"]
        .startswith("/lists?message=")
    )
    client.post(
        "/leads/review", data={"lead_ids": str(lead["id"]), "action": "approve", "confirmed": "1"}
    )
    response = client.post(
        "/lists", data={"name": "Audience", "lead_ids": str(lead["id"])}, follow_redirects=False
    )
    list_id = response.headers["location"].split("/")[-1]
    assert client.get("/lists/" + list_id).status_code == 200
    response = client.post(
        "/campaigns/new",
        data={
            "name": "October Textiles",
            "purpose": "sales",
            "account_id": account,
            "offer": "We supply cotton thread. Would you like a sample?",
            "list_id": list_id,
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/campaigns/october-textiles"
    page = client.get(response.headers["location"] + "?tab=audience")
    assert (
        page.status_code == 200
        and "Research evidence" in page.text
        and "sender@gmail.com" in page.text
    )
    assert client.get("/campaigns/october-textiles/settings").status_code == 200
    with db_for(settings) as db:
        assert len(db.store.emails_in_campaign("october-textiles")) == 1
        assert db.enroll("october-textiles", [lead["id"]]) == (0, 1)
        assert not db.conn.execute("SELECT 1 FROM messages").fetchone()
    assert client.get("/campaigns?purpose_filter=sales").status_code == 200


def test_research_budget_survives_restart_and_unknown_request_is_never_replayed(settings):
    with db_for(settings) as db:
        key = db.new_run(
            title="Test",
            brief="Research textile manufacturers.",
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        db.set_run(key, status="running")
        assert db.reserve(key, "paid", "fingerprint", 60000, 100000) is None
    with db_for(settings) as db:
        assert db.run(key)["spent_micro"] == 60000
        with pytest.raises(ResearchStop, match="uncertain"):
            db.reserve(key, "paid", "fingerprint", 60000, 100000)
        with pytest.raises(ResearchStop, match="Spending limit"):
            db.reserve(key, "next", "fingerprint2", 50000, 100000)
        db.finish_call(key, "paid", {"result": "saved"}, 2000, "reported")
        assert db.reserve(key, "paid", "fingerprint", 60000, 100000) == {"result": "saved"}
        with pytest.raises(ResearchStop, match="inputs changed"):
            db.reserve(key, "paid", "different", 1000, 100000)


def test_overcharge_blocks_other_runs(settings):
    with db_for(settings) as db:
        key = db.new_run(
            title="Test",
            brief="Research textile manufacturers.",
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        db.set_run(key, status="running")
        db.reserve(key, "paid", "a", 1000, 100000)
        with pytest.raises(ResearchStop, match="exceeded"):
            db.finish_call(key, "paid", {}, 2000, "reported")
        db.set_run(key, status="running")
        with pytest.raises(ResearchStop, match="reconciliation"):
            db.reserve(key, "new", "b", 1000, 100000)


def test_provider_timeout_retains_budget_and_cannot_send_again(settings):
    settings = settings.model_copy(update={"parallel_api_key": "fake"})
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("fake timeout")

    with db_for(settings) as db:
        key = db.new_run(
            title="Test",
            brief="Research manufacturers.",
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        db.set_run(key, status="running")
        api = ResearchAPI(
            settings, db, key, client=httpx.Client(transport=httpx.MockTransport(timeout))
        )
        with pytest.raises(ResearchStop, match="retained"):
            api.search("search", "Find manufacturers", ["query"])
        with pytest.raises(ResearchStop, match="uncertain"):
            api.search("search", "Find manufacturers", ["query"])
        assert len(calls) == 1 and db.run(key)["spent_micro"] == 1000
        api.close()


def test_research_flow_refuses_to_search_without_approval(settings):
    with db_for(settings) as db:
        key = db.new_run(
            title="Test",
            brief="Research manufacturers.",
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        with pytest.raises(ResearchStop, match="Approve"):
            run_research(db, None, key)


def test_email_extraction_uses_full_text_and_same_company_site():
    sources = [
        {
            "url": SOURCE["url"],
            "text": "Header " + ("long body " * 1500) + "Contact sales@mills.example",
            "retrieved_at": "now",
        },
        {
            "url": "https://unrelated.example/",
            "text": "owner@unrelated.example",
            "retrieved_at": "now",
        },
    ]
    assert [e["value"] for e in published_emails(sources, SOURCE["url"])] == ["sales@mills.example"]
    assert "sales@mills.example" in text_windows(sources[0]["text"], 1800)
    answer = Assessment(
        facts=[
            {
                "criterion_index": 1,
                "status": "supported",
                "source_id": "s1",
                "quote": "Model invented quotation",
            }
        ],
        fit_summary="",
        unknowns=[],
    )
    assert checked_facts(answer, ["Makes textiles"], {"s1": sources[0]})[0]["status"] == "unknown"


def test_unknown_fit_requires_review_note_and_global_suppression_wins(settings):
    with db_for(settings) as db:
        key = saved_lead(db)
        db.conn.execute(
            "UPDATE research_leads SET facts_json=? WHERE id=?",
            (json.dumps([{"status": "unknown", "criterion": "Makes textiles"}]), key),
        )
        with pytest.raises(ValueError, match="review note"):
            db.review_leads([key], action="approve", confirmed=True)
        db.review_leads(
            [key], action="approve", confirmed=True, note="I verified fit on the source site."
        )
        db.store.add_suppression("sales@mills.example", SuppressionReason.UNSUBSCRIBE)
        with pytest.raises(ValueError, match="do-not-contact"):
            db.review_leads([key], action="approve", confirmed=True, note="Verified")


def test_enrollment_requires_prior_outreach_acknowledgement_and_is_atomic(settings):
    with db_for(settings) as db:
        account = verified_account(db, settings)
        for cid in ("one", "two"):
            db.save_campaign(cid, cid, None, "sales", "", account)
        key = saved_lead(db)
        with pytest.raises(ValueError, match="Approve"):
            db.enroll("one", [key])
        db.review_leads([key], action="approve", confirmed=True)
        assert db.enroll("one", [key]) == (1, 0)
        with pytest.raises(ValueError, match="prior outreach"):
            db.enroll("two", [key])
        assert db.store.emails_in_campaign("two") == set()
        assert db.enroll("two", [key], acknowledge_prior=True) == (1, 0)


def test_account_password_encrypted_not_rendered_and_verification_required(settings):
    with db_for(settings) as db:
        key = make_account(db, settings)
        cipher = db.account(key, secret=True)["password_cipher"]
        assert "fake-app-password" not in cipher
        assert CredentialVault(settings).decrypt(cipher) == "fake-app-password"
        assert "password_cipher" not in db.account(key)
        db.save_campaign("new", "New", None, "sales", "", key)
        assert db.campaign("new")["status"] == "draft"
        with pytest.raises(ValueError, match="Verify"):
            db.save_campaign("new", "New", None, "sales", "", key, status="active")
    page = TestClient(create_app(settings)).get("/accounts")
    assert (
        page.status_code == 200 and cipher not in page.text and "fake-app-password" not in page.text
    )


def test_gmail_zoho_account_forms_verify_both_protocols_without_sending(settings):
    boxes = []

    def mailbox(profile):
        box = VerifiedMailbox()
        boxes.append((profile, box))
        return box

    client = TestClient(create_app(settings, mailbox=mailbox))
    for email, provider in (("sender@gmail.com", "gmail"), ("sender@mycompany.example", "zoho")):
        response = client.post(
            "/accounts",
            data={
                "email": email,
                "provider": provider,
                "region": "in",
                "zoho_paid": "1",
                "label": provider,
                "sender_name": "Sender",
                "company": "Sender Co",
                "address": "123 Street",
                "password": "fake-app-password",
            },
        )
        assert "access verified" in response.text
    assert [s.mail_smtp_host for s, b in boxes] == ["smtp.gmail.com", "smtppro.zoho.in"]
    assert all(not b.sent for s, b in boxes)
    with db_for(settings) as db:
        assert all(a["verified_at"] for a in db.accounts())


def test_verification_failure_does_not_unlock_campaign_sending(settings):
    class Refused(VerifiedMailbox):
        def verify_inbox(self):
            raise MailAuthError("Secret-bearing fake provider detail")

    client = TestClient(create_app(settings, mailbox=lambda s: Refused()))
    response = client.post(
        "/accounts",
        data={
            "email": "sender@gmail.com",
            "label": "Gmail",
            "sender_name": "Sender",
            "company": "Sender Co",
            "address": "123 Street",
            "password": "fake-app-password",
        },
    )
    assert "Verification failed" in response.text and "Secret-bearing" not in response.text
    with db_for(settings) as db:
        assert db.accounts()[0]["verified_at"] is None


def test_campaign_account_frozen_after_send_and_drafts_demoted_on_change(settings):
    with db_for(settings) as db:
        first = verified_account(db, settings)
        second = verified_account(db, settings, "other@gmail.com")
        db.save_campaign("one", "One", None, "sales", "", first)
        key = saved_lead(db)
        db.review_leads([key], action="approve", confirmed=True)
        db.enroll("one", [key])
        contact = db.store._conn.execute("SELECT id FROM contacts").fetchone()[0]
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello",
            verdict="pass",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
        db.save_campaign("one", "One", None, "sales", "", second)
        assert db.store.get_draft(draft).status is DraftStatus.REVIEW
        db.store.record_pending_send(
            contact_id=contact,
            message_id="<sent@sender.example>",
            recipient_email="sales@mills.example",
            subject="Hello",
            body_text="Hello",
        )
        with pytest.raises(ValueError, match="original account"):
            db.save_campaign("one", "One", None, "sales", "", first)
        assert campaign_settings(settings, "one").sender_email == "other@gmail.com"


def test_mailbox_reply_matching_cannot_cross_accounts(settings):
    with db_for(settings) as db:
        first = verified_account(db, settings)
        second = verified_account(db, settings, "other@gmail.com")
        db.save_campaign("one", "One", None, "sales", "", first)
        key = saved_lead(db)
        db.review_leads([key], action="approve", confirmed=True)
        db.enroll("one", [key])
        contact = db.store._conn.execute("SELECT id FROM contacts").fetchone()[0]
        db.store.record_pending_send(
            contact_id=contact,
            message_id="<sent@sender.example>",
            recipient_email="sales@mills.example",
            subject="Hello",
            body_text="Hello",
        )
        db.store.mark_send_outcome(
            "<sent@sender.example>", MessageStatus.SENT, sent_at=datetime.now(UTC)
        )
        assert MailboxStore(db.conn, first).find_message("<sent@sender.example>") is not None
        wrong = MailboxStore(db.conn, second)
        assert wrong.find_message("<sent@sender.example>") is None
        assert wrong.last_message_to("sales@mills.example") is None
        assert wrong.first_send_at() is None


def test_dispatch_rereads_approval_after_preview(store, contact_id):
    draft = store.save_draft(
        contact_id=contact_id,
        model="fake",
        subject="Hello",
        body="Hello",
        verdict="pass",
        checks=[],
    )
    store.set_draft_status(draft, DraftStatus.APPROVED)
    planned = plan(store, "test-campaign", daily_cap=10, closing=None, campaign_copy="")
    store.set_draft_status(draft, DraftStatus.REVIEW)
    box = FakeMailbox()
    outcomes = dispatch(
        store, box, planned, sender_email="sender@example.com", tail="Footer", pause=lambda: None
    )
    assert not box.sent and "approval" in outcomes[0].detail


def test_uncertain_smtp_delivery_stays_pending_and_cannot_reenroll_send(store, contact_id):
    box = FakeMailbox()
    box.fail_next = MailUncertainError("Connection interrupted")
    with pytest.raises(MailUncertainError):
        send_message(
            store=store,
            mailbox=box,
            contact_id=contact_id,
            to="buyer@example.com",
            subject="Hello",
            body_text="Hello",
            message_id="<uncertain@sender.example>",
        )
    assert store.already_written_to(contact_id)
    assert store._conn.execute("SELECT status FROM messages").fetchone()[0] == "pending"


def test_workspace_sign_in_and_same_origin_protection(settings):
    app = create_app(settings.model_copy(update={"app_password": "fake-workspace-password"}))
    client = TestClient(app)
    assert client.get("/research", follow_redirects=False).headers["location"] == "/login"
    assert client.post("/login", data={"password": "wrong"}).status_code == 401
    assert client.post("/login", data={"password": "fake-workspace-password"}).status_code == 200
    assert client.get("/research").status_code == 200
    assert (
        client.post(
            "/projects", data={"name": "Injected"}, headers={"Origin": "https://outside.example"}
        ).status_code
        == 403
    )
    assert client.get("/research", headers={"Host": "malicious.example"}).status_code == 400
    assert "fake-workspace-password" not in client.get("/setup").text


def test_crashed_research_surfaces_saved_budget_without_new_calls(settings):
    with db_for(settings) as db:
        key = db.new_run(
            title="Interrupted",
            brief="Find textile manufacturers.",
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        db.set_run(key, status="running", worker_pid=2147483647)
        db.reserve(key, "paid", "a", 50000, 100000)
    client = TestClient(create_app(settings))
    assert "worker stopped" in client.get("/research/" + key).text
    with db_for(settings) as db:
        assert db.run(key)["status"] == "failed" and db.run(key)["spent_micro"] == 50000


def test_browser_send_and_reply_use_campaign_account(settings, tmp_path, monkeypatch):
    from outreach.campaigns import save_texts

    monkeypatch.chdir(tmp_path)
    settings = settings.model_copy(update={"send_gap_seconds": 0, "openrouter_api_key": None})
    box = VerifiedMailbox()
    profiles = []

    def mailbox(identity):
        profiles.append(identity.sender_email)
        return box

    with db_for(settings) as db:
        account = verified_account(db, settings, "campaign@gmail.com")
        db.save_campaign("one", "One", None, "sales", "", account)
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", confirmed=True)
        db.enroll("one", [lead])
        contact_id = db.conn.execute("SELECT id FROM contacts").fetchone()[0]
        draft = db.store.save_draft(
            contact_id=contact_id,
            model="fake",
            subject="Hello",
            body="Hello",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    save_texts("one", copy="We supply cotton thread.", closing="")
    app = create_app(settings, mailbox=mailbox)
    client = TestClient(app)
    assert "campaign@gmail.com" in client.get("/campaigns/one/send").text
    confirm_launch(client, "/campaigns/one/send")
    deadline = time.monotonic() + 5
    while app.state.sender.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.state.sender.busy and len(box.sent) == 1
    assert profiles[0] == "campaign@gmail.com"
    assert box.sent[0].message_id.endswith("@gmail.com>")
    assert "Verified Sender" in box.sent[0].body_text
    box._replies.append(
        InboundMessage(
            message_id="<reply@mills.example>",
            from_address="sales@mills.example",
            subject="Re: Hello",
            body_text="Please send more information.",
            received_at=datetime.now(UTC),
            in_reply_to=box.sent[0].message_id,
        )
    )
    client.post("/inbox/check")
    with db_for(settings) as db:
        replies = db.store.list_replies()
        assert len(replies) == 1
        assert (
            db.one("SELECT account_id FROM reply_mailboxes WHERE reply_id=?", (replies[0].id,))[
                "account_id"
            ]
            == account
        )
    client.post(f"/replies/{replies[0].id}/send", data={"body": "Thank you. Here are the details."})
    assert len(box.sent) == 2 and profiles[-1] == "campaign@gmail.com"
    assert box.sent[-1].in_reply_to == "<reply@mills.example>"


def test_paused_campaign_cannot_send_approved_drafts(settings, tmp_path, monkeypatch):
    from outreach.campaigns import save_texts

    monkeypatch.chdir(tmp_path)
    box = VerifiedMailbox()
    with db_for(settings) as db:
        account = verified_account(db, settings)
        db.save_campaign("one", "One", None, "sales", "", account, "paused")
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", confirmed=True)
        db.enroll("one", [lead])
        contact = db.conn.execute("SELECT id FROM contacts").fetchone()[0]
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    save_texts("one", copy="We supply cotton thread.", closing="")
    client = TestClient(create_app(settings, mailbox=lambda s: box))
    response = confirm_launch(client, "/campaigns/one/send", follow_redirects=False)
    assert response.headers["location"] == "/campaigns/one/send" and not box.sent


def test_all_drafts_and_rewrites_return_to_human_review(settings, tmp_path, monkeypatch):
    from outreach.campaigns import save_texts
    from outreach.core.drafting import Draft, DraftSentence
    from tests.fakes.llm import FakeLLM

    monkeypatch.chdir(tmp_path)
    llm = FakeLLM([Draft(subject="Hello", sentences=[DraftSentence(text="Hello.")])] * 2)
    monkeypatch.setattr("outreach.web.app.build_llm", lambda settings: llm)
    with db_for(settings) as db:
        account = verified_account(db, settings)
        db.save_campaign("one", "One", None, "sales", "", account)
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", confirmed=True)
        db.enroll("one", [lead])
    save_texts("one", copy="We supply cotton thread.", closing="")
    app = create_app(settings)
    client = TestClient(app)
    for rewrite in ("", "1"):
        client.post("/campaigns/one/draft-all", data={"rewrite": rewrite})
        deadline = time.monotonic() + 5
        while app.state.drafter.busy and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not app.state.drafter.busy and not app.state.drafter.job.error
        assert app.state.drafter.job.completed == 1
        with db_for(settings) as db:
            drafts = db.store.drafts_in_campaign("one")
            assert drafts[0].status is DraftStatus.REVIEW
            if rewrite:
                assert drafts[1].status is DraftStatus.REJECTED
            else:
                db.store.set_draft_status(drafts[0].id, DraftStatus.APPROVED)
    assert len(llm.prompts) == 2


def test_campaign_content_change_demotes_approved_unsent_drafts(settings, tmp_path, monkeypatch):
    from outreach.campaigns import save_texts

    monkeypatch.chdir(tmp_path)
    with db_for(settings) as db:
        account = verified_account(db, settings)
        db.save_campaign("one", "One", None, "sales", "", account)
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", confirmed=True)
        db.enroll("one", [lead])
        contact = db.conn.execute("SELECT id FROM contacts").fetchone()[0]
        draft = db.store.save_draft(
            contact_id=contact,
            model="fake",
            subject="Hello",
            body="Hello",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    save_texts("one", copy="Old offer", closing="")
    client = TestClient(create_app(settings))
    client.post(
        "/campaigns/one/settings",
        data={"name": "One", "purpose": "sales", "account_id": account, "offer": "New offer"},
    )
    with db_for(settings) as db:
        assert db.store.get_draft(draft).status is DraftStatus.REVIEW


def test_campaign_creation_failure_leaves_no_partial_campaign(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with db_for(settings) as db:
        account = verified_account(db, settings)
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", confirmed=True)
        audience = db.add_list("Audience", None, [lead])
        db.store.add_suppression("sales@mills.example", SuppressionReason.UNSUBSCRIBE)
    client = TestClient(create_app(settings))
    client.post(
        "/campaigns/new",
        data={
            "name": "Blocked",
            "purpose": "sales",
            "account_id": account,
            "offer": "We supply cotton thread.",
            "list_id": audience,
        },
    )
    with db_for(settings) as db:
        assert db.campaign("blocked") is None


def test_tls_certificates_are_verified_by_mail_adapter(settings, monkeypatch):
    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox
    from tests.test_mail_smtp import FakeSMTP

    monkeypatch.setattr("outreach.adapters.mail_smtp_imap.smtplib.SMTP_SSL", FakeSMTP)
    FakeSMTP.instances = []
    ready = settings.model_copy(
        update={"sender_company": "Sender Co", "sender_address": "123 Street"}
    )
    SmtpImapMailbox(ready).verify_login()
    assert FakeSMTP.instances[0].context.check_hostname


def test_lost_credential_key_keeps_account_pages_readable_but_blocks_send(
    settings, tmp_path, monkeypatch
):
    from outreach.campaigns import save_texts

    monkeypatch.chdir(tmp_path)
    with db_for(settings) as db:
        account = verified_account(db, settings)
        db.save_campaign("one", "One", None, "sales", "", account)
    save_texts("one", copy="We supply cotton thread.", closing="")
    (tmp_path / "mail-credentials.key").unlink()
    client = TestClient(create_app(settings))
    assert client.get("/accounts").status_code == 200
    assert client.get("/campaigns/one").status_code == 200
    response = client.get("/campaigns/one/send")
    assert response.status_code == 200
    assert (
        confirm_launch(client, "/campaigns/one/send", follow_redirects=False).headers["location"]
        == "/campaigns/one/send"
    )


def test_daily_cap_is_checked_again_at_dispatch(store, contact_id):
    from outreach.core.models import Contact

    draft = store.save_draft(
        contact_id=contact_id,
        model="fake",
        subject="Hello",
        body="Hello",
        verdict="clean",
        checks=[],
    )
    store.set_draft_status(draft, DraftStatus.APPROVED)
    planned = plan(store, "test-campaign", daily_cap=1, closing=None, campaign_copy="")
    other = store.add_contact(
        Contact(campaign_id="test-campaign", email="other@example.com", company="Other")
    )
    store.record_pending_send(
        contact_id=other,
        message_id="<other@sender.example>",
        recipient_email="other@example.com",
        subject="Hello",
        body_text="Hello",
    )
    store.mark_send_outcome("<other@sender.example>", MessageStatus.SENT, sent_at=datetime.now(UTC))
    box = FakeMailbox()
    outcomes = dispatch(
        store,
        box,
        planned,
        sender_email="sender@example.com",
        tail="Footer",
        pause=lambda: None,
        daily_cap=1,
    )
    assert not box.sent and "limit" in outcomes[0].detail
