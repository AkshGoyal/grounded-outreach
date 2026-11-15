"""Real routes and storage across the complete journey; every provider is offline."""

import io
import json
import re
import sqlite3
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.credential_vault import CredentialVault
from outreach.adapters.research_api import ResearchAPI
from outreach.campaigns import save_texts
from outreach.core.models import DraftStatus, InboundMessage, ReplyStatus
from outreach.ports.mail import MailUncertainError
from outreach.web.app import create_app
from tests.helpers import confirm_launch
from tests.test_campaign_workspace import contact, create, draft
from tests.test_platform import VerifiedMailbox, db_for, verified_account, wait_for

AI_PLAN = {
    "summary": "Find AI product startups in Bengaluru with published founder or HR emails.",
    "criteria": ["Builds an AI product", "Based in Bengaluru"],
    "queries": ["Bengaluru AI product companies"],
    "alternate_queries": ["Bangalore AI startup HR email"],
    "exclusions": ["Consulting-only companies"],
}
AI_SOURCES = [
    {
        "url": "https://atlas-ai.example/about",
        "title": "Atlas AI",
        "full_content": (
            "Atlas AI builds an AI document assistant in Bengaluru. "
            "HR and recruiting: careers@atlas-ai.example."
        ),
    },
    {
        "url": "https://beacon-ai.example/about",
        "title": "Beacon AI",
        "full_content": (
            "Beacon AI builds an AI voice assistant in Bengaluru. "
            "Customer support: support@beacon-ai.example."
        ),
    },
]


def ai_research(calls):
    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path.endswith(("/search", "/extract")):
            sources = AI_SOURCES
            if "urls" in body:
                sources = [s for s in sources if s["url"] in body["urls"]]
            return httpx.Response(200, json={"results": sources})
        schema = body["response_format"]["json_schema"]["name"]
        if schema == "researchplan":
            result = AI_PLAN
        elif schema == "candidates":
            result = {
                "candidates": [
                    {
                        "company": s["title"],
                        "website": s["url"],
                        "source_id": f"s{i}",
                        "identity_quote": s["full_content"].split(". ")[0] + ".",
                    }
                    for i, s in enumerate(AI_SOURCES, 1)
                ]
            }
        else:
            source = (
                AI_SOURCES[0]
                if "COMPANY: Atlas AI" in body["messages"][-1]["content"]
                else AI_SOURCES[1]
            )
            result = {
                "facts": [
                    {
                        "criterion_index": i,
                        "status": "supported",
                        "source_id": "s1",
                        "quote": source["full_content"].split(". ")[0] + ".",
                    }
                    for i in (1, 2)
                ],
                "fit_summary": "AI product company in Bengaluru.",
                "unknowns": [],
            }
        return httpx.Response(
            200,
            json={
                "usage": {"cost": 0.001},
                "choices": [{"message": {"content": json.dumps(result)}}],
            },
        )

    return handler


class CampaignLLM:
    def generate(self, *, prompt, schema, max_tokens=4096):
        if "sections" in schema.model_fields:
            layout = json.loads(prompt.split("\n", 1)[1])
            sections = []
            for part in layout["editor_layout"]:
                if part["kind"] != "generate":
                    continue
                sentences = [{"text": "Hello." if not sections else "Thank you."}]
                if not sections and "Builds an AI product" in layout["recipient_facts"]:
                    sentences.append(
                        {
                            "text": "Atlas AI builds an AI document assistant in Bengaluru.",
                            "cites": "Builds an AI product",
                        }
                    )
                sections.append({"index": part["index"], "sentences": sentences})
            return schema.model_validate({"subject": "An introduction", "sections": sections})
        if schema.__name__ == "ReplyReading":
            return schema.model_validate(
                {
                    "category": "not_interested" if "Please remove" in prompt else "interested",
                    "summary": "Asked to stop"
                    if "Please remove" in prompt
                    else "Interested in a conversation",
                    "postal_address": None,
                    "contact_person": None,
                    "phone": None,
                    "suggested_reply": "Thank you. I would be happy to talk.",
                }
            )
        sentences = [{"text": "Hello."}]
        if "Atlas AI" in prompt:
            sentences.append(
                {
                    "text": "Atlas AI builds an AI document assistant in Bengaluru.",
                    "cites": "Builds an AI product",
                }
            )
        return schema.model_validate({"subject": "An introduction", "sentences": sentences})


def finish(job):
    deadline = time.monotonic() + 5
    while not job.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.finished


@pytest.fixture
def complete_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = settings.model_copy(
        update={
            "parallel_api_key": "fake",
            "openrouter_api_key": "fake",
            "send_gap_seconds": 0,
            "app_password": "test-workspace-password",
        }
    )
    boxes = {"career@gmail.com": VerifiedMailbox(), "sales@example.com": VerifiedMailbox()}
    calls = []
    monkeypatch.setattr("outreach.web.app.build_llm", lambda s: CampaignLLM())

    def app_factory():
        return create_app(
            config,
            mailbox=lambda identity: boxes[str(identity.sender_email)],
            research_api=lambda db, key: ResearchAPI(
                config,
                db,
                key,
                client=httpx.Client(transport=httpx.MockTransport(ai_research(calls))),
            ),
        )

    app = app_factory()
    client = TestClient(app)
    client.post("/login", data={"password": config.app_password})
    return config, app, client, boxes, calls, app_factory


def test_complete_research_to_two_campaigns_reply_optout_and_restart(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    # Saved free intake, paid plan consent, then independent research consent.
    response = client.post(
        "/research/intake",
        data={
            "brief": "Find AI product startups in Bangalore for job outreach, accepting HR emails.",
            "company_type": "AI product startups",
            "geography": "Bengaluru",
            "contact_roles": ["founder", "hr", "management"],
            "purpose": "job search",
            "target": "2",
            "budget": ".20",
        },
        follow_redirects=False,
    )
    run = response.headers["location"].split("?")[0].split("/")[-1]
    assert not calls
    with db_for(config) as db:
        intake = db.run(run)["intake"]
    client.post(
        f"/research/{run}/intake",
        data={
            "brief": intake["goal"],
            "company_type": intake["company_type"],
            "geography": intake["geography"],
            "contact_roles": intake["contact_roles"],
            "purpose": "job search",
            "target": "2",
            "budget": ".20",
            "action": "plan",
            "planning_confirm": "on",
        },
    )
    wait_for(app, run)
    assert len(calls) == 1
    client.post(
        f"/research/{run}/approve",
        data={
            "summary": AI_PLAN["summary"],
            "criteria": "\n".join(AI_PLAN["criteria"]),
            "queries": AI_PLAN["queries"][0],
            "alternate_queries": AI_PLAN["alternate_queries"][0],
            "exclusions": AI_PLAN["exclusions"][0],
            "confirm": "on",
        },
    )
    wait_for(app, run)
    with db_for(config) as db:
        assert db.run(run)["status"] == "paused", db.run(run)["error"]
        assert db.run(run)["execution"]["outcome"] == "budget_limit"
        assert db.run(run)["spent_micro"] <= db.run(run)["budget_micro"]
        leads = db.leads(run)
        assert len(leads) == 2 and all(lead["review_status"] == "pending" for lead in leads)
        atlas = next(lead for lead in leads if lead["company"] == "Atlas AI")
        beacon = next(lead for lead in leads if lead["company"] == "Beacon AI")
        assert atlas["emails"][0]["value"] == "careers@atlas-ai.example"
    client.post("/leads/review", data={"lead_ids": str(beacon["id"]), "action": "reject"})
    client.post(
        "/leads/review", data={"lead_ids": str(atlas["id"]), "action": "approve", "confirmed": "on"}
    )
    response = client.post(
        "/lists",
        data={"name": "AI career audience", "lead_ids": str(atlas["id"])},
        follow_redirects=False,
    )
    audience = response.headers["location"].split("/")[-1]
    cid = create(client, name="AI Career", list_id=audience)
    client.post(f"/campaigns/{cid}/draft-all")
    finish(app.state.drafter.job)
    assert app.state.drafter.job.completed == 1 and not any(box.sent for box in boxes.values())
    with db_for(config) as db:
        current = db.store.drafts_in_campaign(cid)[0]
        assert "document assistant" in current.body
    client.post(
        f"/drafts/{current.id}",
        data={"subject": current.subject, "body": current.body, "action": "approve"},
    )
    assert "Launch is blocked" in client.get(f"/campaigns/{cid}/send").text
    # Both connections are created through the account form, with fake verification.
    for email, provider in (("career@gmail.com", "gmail"), ("sales@example.com", "zoho")):
        client.post(
            "/accounts",
            data={
                "provider": provider,
                "region": "in",
                "zoho_paid": "1",
                "email": email,
                "label": email,
                "sender_name": "Candidate",
                "company": "Personal outreach",
                "address": "Test address",
                "password": "fake-password",
            },
        )
    with db_for(config) as db:
        accounts = {a["email"]: a["id"] for a in db.accounts()}
        assert len(accounts) == 2 and all(a["verified_at"] for a in db.accounts())
    client.post(
        f"/campaigns/{cid}/settings",
        data={
            "name": "AI Career",
            "purpose": "job search",
            "account_id": accounts["career@gmail.com"],
        },
    )
    with db_for(config) as db:
        assert db.store.get_draft(current.id).status is DraftStatus.REVIEW
    client.post(
        f"/drafts/{current.id}",
        data={"subject": current.subject, "body": current.body, "action": "approve"},
    )
    confirm_launch(client, f"/campaigns/{cid}/send")
    finish(app.state.sender.job)
    career = boxes["career@gmail.com"]
    assert len(career.sent) == 1 and not boxes["sales@example.com"].sent
    with db_for(config) as db:
        assert db.campaign(cid)["status"] == "active"
    # Independently prepare and send a sales campaign through Zoho.
    second = create(
        client,
        name="Product Partnerships",
        purpose="partnerships",
        account_id=accounts["sales@example.com"],
    )
    upload = b"Company,Email,Product\nFictional Partner,hello@partner.example,Document tools\n"
    client.post(
        "/import",
        files={"file": ("audience.csv", upload, "text/csv")},
        data={"campaign": second, "commit": "1"},
    )
    client.post(f"/campaigns/{second}/draft-all")
    finish(app.state.drafter.job)
    client.post(f"/campaigns/{second}/approve-all")
    confirm_launch(client, f"/campaigns/{second}/send")
    finish(app.state.sender.job)
    assert len(boxes["sales@example.com"].sent) == 1
    # The reply matches the career account, is answered once, and remains saved.
    career._replies = [
        InboundMessage(
            message_id="<interest@atlas-ai.example>",
            from_address=career.sent[0].to,
            subject="Re: An introduction",
            body_text="Happy to talk.",
            received_at=datetime.now(UTC) + timedelta(minutes=1),
            in_reply_to=career.sent[0].message_id,
        )
    ]
    client.post("/inbox/check", data={"account_id": accounts["career@gmail.com"]})
    with db_for(config) as db:
        reply = db.store.list_replies()[0]
        assert reply.campaign_id == cid and reply.category == "interested"
    detail = client.get(f"/replies/{reply.id}").text
    assert "career@gmail.com" in detail and "Your answer" in detail
    client.post(f"/replies/{reply.id}/send", data={"body": "Thank you. I would be happy to talk."})
    client.post(f"/replies/{reply.id}/send", data={"body": "Thank you. I would be happy to talk."})
    assert len(career.sent) == 2 and len(boxes["sales@example.com"].sent) == 1
    career._replies.append(
        InboundMessage(
            message_id="<optout@atlas-ai.example>",
            from_address=career.sent[0].to,
            subject="Re: An introduction",
            body_text="Please remove me.",
            received_at=datetime.now(UTC) + timedelta(minutes=2),
            in_reply_to=career.sent[0].message_id,
        )
    )
    client.post("/inbox/check", data={"account_id": accounts["career@gmail.com"]})
    with db_for(config) as db:
        assert db.store.is_suppressed(career.sent[0].to)
        assert db.lead(beacon["id"])["review_status"] == "rejected"
        assert len(db.store.emails_in_campaign(cid)) == 1
    # Restart, re-login and inspect saved history. No additional provider request/send.
    before = len(calls)
    restarted = TestClient(app_factory())
    assert (
        restarted.get(f"/campaigns/{cid}/history", follow_redirects=False).headers["location"]
        == "/login"
    )
    restarted.post("/login", data={"password": config.app_password})
    history = restarted.get(f"/campaigns/{cid}/history").text
    assert (
        "document assistant" in history
        and "Reply answer" in history
        and "Accepted by provider" in history
    )
    restarted.post(f"/replies/{reply.id}/done", data={"undo": "1"})
    restarted.post(f"/replies/{reply.id}/send", data={"body": "Repeated answer"})
    assert len(career.sent) == 2 and len(calls) == before
    assert "Document tools" in restarted.get(f"/campaigns/{second}?tab=audience").text
    # A full download restores both account keys and campaign copy without API secrets.
    page = restarted.post("/backup")
    url = re.search(r'href="(/backups/[^"]+)"', page.text)[1]
    with zipfile.ZipFile(io.BytesIO(restarted.get(url).content)) as bundle:
        restore = config.model_copy(
            update={"db_path": str(config.db_path).replace("test.db", "restored/outreach.db")}
        )
        destination = Path(restore.db_path).parent
        destination.mkdir()
        bundle.extract("outreach.db", destination)
        bundle.extract("mail-credentials.key", destination)
        assert f"campaigns/{cid}.md" in bundle.namelist() and ".env" not in bundle.namelist()
        with sqlite3.connect(restore.db_path) as restored_db:
            restored_db.row_factory = sqlite3.Row
            encrypted = restored_db.execute(
                "SELECT password_cipher FROM mail_accounts LIMIT 1"
            ).fetchone()[0]
            assert CredentialVault(restore).decrypt(encrypted) == "fake-password"
            assert restored_db.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0] == 1


@pytest.mark.parametrize(
    "change",
    [
        "approve_more",
        "edit_draft",
        "changed_tail",
        "revoke",
        "expired",
        "restart",
        "tamper",
        "no_consent",
    ],
)
def test_stale_or_unconfirmed_launch_never_sends(complete_workspace, change, monkeypatch):
    config, app, client, boxes, calls, app_factory = complete_workspace
    with db_for(config) as db:
        account = verified_account(db, config, "career@gmail.com")
    cid = create(client, account_id=account)
    with db_for(config) as db:
        first = draft(db, contact(db, cid), DraftStatus.APPROVED)
        extra = draft(db, contact(db, cid, "extra@fictional.example"))
    token = re.search(
        r'name="launch_token" value="([^"]+)"', client.get(f"/campaigns/{cid}/send").text
    )[1]
    with db_for(config) as db:
        if change == "approve_more":
            db.store.set_draft_status(extra, DraftStatus.APPROVED)
        if change == "edit_draft":
            db.conn.execute("UPDATE drafts SET body='A changed email.' WHERE id=?", (first,))
        if change == "revoke":
            db.conn.execute("UPDATE mail_accounts SET verified_at=NULL WHERE id=?", (account,))
    if change == "changed_tail":
        save_texts(cid, copy="An introduction.", closing="New ending.")
    if change == "expired":
        future = time.time() + 1000
        monkeypatch.setattr("outreach.web.launch.time.time", lambda: future)
    if change == "restart":
        client = TestClient(app_factory())
        client.post("/login", data={"password": config.app_password})
    if change == "tamper":
        token += "broken"
    client.post(
        f"/campaigns/{cid}/send",
        data={"launch_token": token, "confirm_send": "" if change == "no_consent" else "on"},
    )
    assert not boxes["career@gmail.com"].sent and not app.state.sender.busy


def test_uncertain_reply_blocks_retry_after_restart_and_status_reopen(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    with db_for(config) as db:
        account = verified_account(db, config, "career@gmail.com")
    cid = create(client, account_id=account)
    with db_for(config) as db:
        draft(db, contact(db, cid), DraftStatus.APPROVED)
    confirm_launch(client, f"/campaigns/{cid}/send")
    finish(app.state.sender.job)
    box = boxes["career@gmail.com"]
    box._replies = [
        InboundMessage(
            message_id="<reply@fictional.example>",
            from_address=box.sent[0].to,
            subject="Re: Hello",
            body_text="Happy to talk.",
            received_at=datetime.now(UTC) + timedelta(minutes=1),
            in_reply_to=box.sent[0].message_id,
        )
    ]
    client.post("/inbox/check", data={"account_id": account})
    with db_for(config) as db:
        reply = db.store.list_replies()[0]
    box.fail_next = MailUncertainError("Unknown delivery outcome")
    client.post(f"/replies/{reply.id}/send", data={"body": "Thank you."})
    restart = TestClient(app_factory())
    restart.post("/login", data={"password": config.app_password})
    assert "Answer outcome is uncertain" in restart.get(f"/replies/{reply.id}").text
    restart.post(f"/replies/{reply.id}/send", data={"body": "Try again"})
    assert len(box.sent) == 1
    with db_for(config) as db:
        assert db.one("SELECT status FROM messages WHERE status='pending'")
        assert db.store.get_reply(reply.id).status is ReplyStatus.NEW


def test_import_rejects_unsafe_campaign_and_backup_download_requires_login(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    response = client.post(
        "/import",
        files={"file": ("contacts.csv", b"Email\nhello@example.com\n", "text/csv")},
        data={"campaign": "../outside", "commit": "1"},
    )
    assert response.status_code == 400
    with db_for(config) as db:
        assert not db.rows("SELECT * FROM campaigns")
    page = client.post("/backup")
    url = re.search(r'href="(/backups/[^"]+)"', page.text)[1]
    assert client.get(url).headers["content-type"] == "application/zip"
    unauthenticated = TestClient(app)
    assert unauthenticated.get(url, follow_redirects=False).headers["location"] == "/login"
    assert client.get("/backups/not-a-backup.zip").status_code == 404


def test_uncertain_campaign_stops_batch_and_reserves_daily_capacity(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    with db_for(config) as db:
        account = verified_account(db, config, "career@gmail.com")
    cid = create(client, account_id=account)
    with db_for(config) as db:
        draft(db, contact(db, cid), DraftStatus.APPROVED)
        draft(db, contact(db, cid, "another@fictional.example"), DraftStatus.APPROVED)
    boxes["career@gmail.com"].fail_next = MailUncertainError("Unknown delivery outcome")
    confirm_launch(client, f"/campaigns/{cid}/send")
    finish(app.state.sender.job)
    assert not boxes["career@gmail.com"].sent
    assert len(app.state.sender.job.outcomes) == 1
    assert "Delivery uncertain" in app.state.sender.job.outcomes[0].detail
    with db_for(config) as db:
        assert db.store.sent_today() == 0 and db.store.sending_slots_today() == 1
        assert len(db.rows("SELECT * FROM messages")) == 1
        from outreach.core.dispatch import plan

        assert not any(
            p.will_send
            for p in plan(db.store, cid, daily_cap=1, closing=None, campaign_copy="Introduction.")
        )
    assert "uncertain" in client.get("/").text
    assert "Unknown delivery outcome" not in client.get(f"/campaigns/{cid}/history").text


def test_draft_test_confirmation_and_repeated_request_are_fenced(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    with db_for(config) as db:
        account = verified_account(db, config, "career@gmail.com")
    cid = create(client, account_id=account)
    with db_for(config) as db:
        key = draft(db, contact(db, cid))
    page = client.get(f"/drafts/{key}").text
    values = {
        name: re.search(r'name="' + name + r'" value="([^"]+)"', page)[1]
        for name in ("test_nonce", "test_token")
    }
    url = f"/drafts/{key}/test-send"
    client.post(url, data=values | {"to": "own@fictional.example"})
    assert not boxes["career@gmail.com"].sent
    client.post(url, data=values | {"to": "own@fictional.example", "confirmed": "on"})
    client.post(url, data=values | {"to": "own@fictional.example", "confirmed": "on"})
    assert len(boxes["career@gmail.com"].sent) == 1
    with db_for(config) as db:
        assert db.one("SELECT status FROM draft_test_runs")["status"] == "accepted"
        assert db.store.sent_today() == 0


def test_backup_refuses_missing_key_or_campaign_symlink(complete_workspace):
    config, app, client, boxes, calls, app_factory = complete_workspace
    with db_for(config) as db:
        account = verified_account(db, config, "career@gmail.com")
    cid = create(client, account_id=account)
    key = Path(config.db_path).parent / "mail-credentials.key"
    saved_key = key.read_bytes()
    key.unlink()
    assert "Mailbox encryption key is missing" in client.post("/backup").text
    key.write_bytes(saved_key)
    copy = Path("campaigns") / f"{cid}.md"
    copy.unlink()
    try:
        copy.symlink_to(key)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege; missing-key check passed")
        raise
    assert "regular file" in client.post("/backup").text
    assert not list((Path(config.db_path).parent / "backups").glob("*.zip"))
