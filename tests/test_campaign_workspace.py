"""Campaign preparation without a mailbox, scoped review and sender isolation."""

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from outreach.adapters.db import SCHEMA_VERSION
from outreach.campaigns import load_copy
from outreach.config import ConfigError
from outreach.core.drafting import Draft, DraftSentence
from outreach.core.message_brief import MessageBrief
from outreach.core.models import Contact, DraftStatus, MessageStatus
from outreach.web.app import create_app
from outreach.wiring import campaign_settings
from tests.fakes.llm import FakeLLM
from tests.helpers import confirm_launch
from tests.test_platform import VerifiedMailbox, db_for, make_account, saved_lead, verified_account

BRIEF = {
    "topic": "AI product career outreach",
    "introduction": "I am interested in AI product engineering.",
    "background": "I built a small document-search project.",
    "desired_response": "Reply if my background could be useful to your team.",
    "tone": "concise",
    "sender_name": "Candidate",
    "brief_mode": "structured",
}


@pytest.fixture
def workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = settings.model_copy(update={"openrouter_api_key": "fake", "send_gap_seconds": 0})
    llm = FakeLLM([Draft(subject="Hello", sentences=[DraftSentence(text="Hello.")])] * 20)
    monkeypatch.setattr("outreach.web.app.build_llm", lambda settings: llm)
    box = VerifiedMailbox()
    app = create_app(settings, mailbox=lambda identity: box)
    return settings, app, TestClient(app), box, llm


def create(client, name="Career", **extra):
    response = client.post(
        "/campaigns/new",
        data={"name": name, "purpose": "job search"} | BRIEF | extra,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("/")[-1]


def contact(db, cid, address="hr@fictional.example", company="Fictional AI"):
    return db.store.add_contact(
        Contact(campaign_id=cid, email=address, company=company, evidence={})
    )


def draft(db, contact_id, status=DraftStatus.REVIEW, body="Hello."):
    key = db.store.save_draft(
        contact_id=contact_id, model="fake", subject="Hello", body=body, verdict="clean", checks=[]
    )
    db.store.set_draft_status(key, status)
    return key


def test_campaign_saves_without_sender_and_never_falls_back_to_environment_mail(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        assert db.campaign(cid)["sender_account_id"] is None
        assert db.campaign(cid)["message_brief"]["background"] == BRIEF["background"]
        draft(db, contact(db, cid), DraftStatus.APPROVED)
    identity = campaign_settings(settings, cid, unlock=False)
    assert identity.sender_name == "Candidate"
    assert identity.sender_email is None and identity.mail_password is None
    with pytest.raises(ConfigError, match="Choose and verify"):
        campaign_settings(settings, cid, require_verified=True)
    page = client.get("/campaigns/" + cid + "/send")
    assert page.status_code == 200 and "Choose and verify" in page.text
    confirm_launch(client, "/campaigns/" + cid + "/send")
    assert not app.state.sender.busy and not box.sent
    assert not llm.prompts


def test_partial_message_saves_and_blocks_generation_until_completed(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client, topic="", desired_response="")
    assert load_copy(cid) is None
    with db_for(settings) as db:
        contact(db, cid)
    client.post("/campaigns/" + cid + "/draft")
    assert not llm.prompts
    response = client.post("/campaigns/" + cid + "/message", data=BRIEF)
    assert response.status_code == 200 and load_copy(cid)
    client.post("/campaigns/" + cid + "/draft")
    assert len(llm.prompts) == 1
    assert BRIEF["background"] in llm.prompts[0]
    assert settings.sender_name not in llm.prompts[0]
    with db_for(settings) as db:
        assert db.store.drafts_in_campaign(cid)[0].status is DraftStatus.REVIEW
    assert not box.sent


def test_whole_campaign_drafting_works_before_email_connection(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        contact(db, cid)
    client.post("/campaigns/" + cid + "/draft-all")
    deadline = time.monotonic() + 5
    while app.state.drafter.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.state.drafter.busy and not app.state.drafter.job.error
    assert app.state.drafter.job.completed == 1 and len(llm.prompts) == 1
    assert not box.sent


def test_approved_selection_hands_off_to_campaign_without_account(workspace):
    settings, app, client, box, llm = workspace
    with db_for(settings) as db:
        lead = saved_lead(db)
    client.post("/campaigns/from-selection", data={"lead_ids": str(lead)})
    with db_for(settings) as db:
        assert db.lists() == []
    client.post(
        "/leads/review", data={"lead_ids": str(lead), "action": "approve", "confirmed": "on"}
    )
    response = client.post(
        "/campaigns/from-selection", data={"lead_ids": str(lead)}, follow_redirects=False
    )
    audience = response.headers["location"].split("list_id=")[-1]
    cid = create(client, list_id=audience)
    with db_for(settings) as db:
        assert len(db.store.emails_in_campaign(cid)) == 1
        assert db.campaign(cid)["sender_account_id"] is None
    assert "Research evidence" in client.get("/campaigns/" + cid + "?tab=audience").text
    assert not box.sent and not llm.prompts


def test_message_and_sender_changes_demote_unsent_approvals_preserve_sent(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        first = draft(db, contact(db, cid), DraftStatus.APPROVED)
        sent = draft(db, contact(db, cid, "sent@fictional.example"), DraftStatus.SENT)
    client.post(
        "/campaigns/" + cid + "/message", data=BRIEF | {"background": "I built a real speech demo."}
    )
    with db_for(settings) as db:
        assert db.store.get_draft(first).status is DraftStatus.REVIEW
        assert db.store.get_draft(sent).status is DraftStatus.SENT
        db.store.set_draft_status(first, DraftStatus.APPROVED)
        account = verified_account(db, settings)
    client.post(
        "/campaigns/" + cid + "/settings",
        data={"name": "Career", "purpose": "job search", "account_id": account},
    )
    with db_for(settings) as db:
        assert db.store.get_draft(first).status is DraftStatus.REVIEW
        assert db.store.get_draft(sent).status is DraftStatus.SENT
        assert db.campaign(cid)["message_brief"]["background"] == "I built a real speech demo."
    assert "real speech demo" in load_copy(cid)


def test_unverified_accounts_can_be_saved_but_cannot_launch(workspace):
    settings, app, client, box, llm = workspace
    with db_for(settings) as db:
        account = make_account(db, settings)
    cid = create(client, account_id=account)
    with db_for(settings) as db:
        draft(db, contact(db, cid), DraftStatus.APPROVED)
    with pytest.raises(ConfigError, match="Verify this sending account"):
        campaign_settings(settings, cid, require_verified=True)
    confirm_launch(client, "/campaigns/" + cid + "/send")
    assert not app.state.sender.busy and not box.sent


def test_verified_sender_cannot_launch_an_incomplete_message(workspace):
    settings, app, client, box, llm = workspace
    with db_for(settings) as db:
        account = verified_account(db, settings)
    cid = create(client, account_id=account, desired_response="")
    with db_for(settings) as db:
        draft(db, contact(db, cid), DraftStatus.APPROVED)
    with pytest.raises(ConfigError, match="Complete the campaign message brief"):
        campaign_settings(settings, cid, require_verified=True)
    confirm_launch(client, "/campaigns/" + cid + "/send")
    assert not app.state.sender.busy and not box.sent


def test_schema_six_campaigns_survive_message_brief_migration(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        key = contact(db, cid)
        db.conn.execute("DROP TABLE campaign_briefs")
        db.conn.execute("UPDATE schema_meta SET value='6' WHERE key='schema_version'")
    with db_for(settings) as db:
        assert db.campaign(cid)["message_brief"] is None
        assert db.store.get_contact(key).company == "Fictional AI"
        assert db.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == str(SCHEMA_VERSION)
    assert BRIEF["background"] in load_copy(cid)


def test_sent_history_keeps_original_account(workspace):
    settings, app, client, box, llm = workspace
    with db_for(settings) as db:
        one = verified_account(db, settings, "one@gmail.com")
        two = verified_account(db, settings, "two@gmail.com")
    cid = create(client, account_id=one)
    with db_for(settings) as db:
        key = contact(db, cid)
        db.store.record_pending_send(
            contact_id=key,
            message_id="<fictional@one>",
            recipient_email="hr@fictional.example",
            subject="Hello",
            body_text="Hello.",
        )
        db.store.mark_send_outcome("<fictional@one>", MessageStatus.SENT, datetime.now(UTC))
    response = client.post(
        "/campaigns/" + cid + "/settings",
        data={"name": "Career", "purpose": "job search", "account_id": two},
    )
    assert response.status_code == 400
    with db_for(settings) as db:
        assert db.campaign(cid)["sender_account_id"] == one


def test_selected_approval_is_scoped_and_ambiguous_drafts_stay_pending(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    other = create(client, name="Other")
    with db_for(settings) as db:
        clean = draft(db, contact(db, cid))
        maybe = draft(
            db,
            contact(db, cid, "maybe@fictional.example"),
            body="Your business seems well established.",
        )
        untouched = draft(db, contact(db, cid, "untouched@fictional.example"))
        foreign = draft(db, contact(db, other))
    for ids in [[], [str(clean), str(foreign)]]:
        client.post(
            "/campaigns/" + cid + "/approve-all",
            data={"selection_required": "1", "confirm_selection": "on", "draft_ids": ids},
        )
    with db_for(settings) as db:
        assert db.store.get_draft(clean).status is DraftStatus.REVIEW
    client.post(
        "/campaigns/" + cid + "/approve-all",
        data={
            "selection_required": "1",
            "confirm_selection": "on",
            "draft_ids": [str(clean), str(maybe)],
        },
    )
    with db_for(settings) as db:
        assert db.store.get_draft(clean).status is DraftStatus.APPROVED
        assert all(
            db.store.get_draft(i).status is DraftStatus.REVIEW for i in [maybe, untouched, foreign]
        )
    assert not box.sent


def test_newer_draft_prevents_approval_of_old_version(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        key = contact(db, cid)
        old = draft(db, key, DraftStatus.REJECTED)
        latest = draft(db, key)
    page = client.post(
        "/drafts/" + str(old), data={"subject": "Hello", "body": "Hello.", "action": "approve"}
    )
    assert "A newer draft exists" in page.text
    with db_for(settings) as db:
        assert db.store.get_draft(old).status is DraftStatus.REJECTED
        assert db.store.get_draft(latest).status is DraftStatus.REVIEW


def test_review_navigation_filters_and_all_launch_previews(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        first = draft(db, contact(db, cid, company="Alpha"), DraftStatus.APPROVED)
        second = draft(db, contact(db, cid, "beta@fictional.example", "Beta"), DraftStatus.APPROVED)
    page = client.get("/drafts/" + str(first))
    assert "1 of 2" in page.text and 'href="/drafts/' + str(second) + '"' in page.text
    page = client.get("/campaigns/" + cid + "/drafts?status=review")
    assert "No drafts match this filter" in page.text
    page = client.get("/campaigns/" + cid + "/send")
    assert page.text.count("From:") == 2
    assert "hr@fictional.example" in page.text and "beta@fictional.example" in page.text
    assert not box.sent


def test_missing_sender_background_is_not_invented_and_validation_retains_text(workspace):
    settings, app, client, box, llm = workspace
    brief = MessageBrief(
        topic="Career", introduction="An introduction", desired_response="Please reply"
    )
    assert "do not invent qualifications" in brief.campaign_copy()
    cid = create(client)
    page = client.post("/campaigns/" + cid + "/message", data=BRIEF | {"tone": "invented"})
    assert page.status_code == 400 and BRIEF["background"] in page.text
    with db_for(settings) as db:
        assert db.campaign(cid)["message_brief"]["tone"] == "concise"


def test_legacy_text_editor_replaces_structured_brief_and_invalidates_approval(workspace):
    settings, app, client, box, llm = workspace
    cid = create(client)
    with db_for(settings) as db:
        key = draft(db, contact(db, cid), DraftStatus.APPROVED)
    client.post(
        "/campaigns/" + cid + "/texts", data={"offer": "A different truthful offer", "closing": ""}
    )
    with db_for(settings) as db:
        assert db.campaign(cid)["message_brief"] is None
        assert db.store.get_draft(key).status is DraftStatus.REVIEW
    assert load_copy(cid) == "A different truthful offer"


def test_legacy_review_notes_are_not_drafting_or_approval_evidence():
    from outreach.core.drafting import check_draft, draft_email
    from outreach.core.grounding import Verdict

    facts = {
        "Product": "An AI product",
        "review_note": "We met at your Coimbatore office.",
        "research_run": "internal-audit-token",
    }
    model = FakeLLM([Draft(subject="Hello", sentences=[DraftSentence(text="Hello.")])])
    draft_email(
        model,
        company="Fictional AI",
        evidence=facts,
        campaign_copy="An introduction",
        sender="Candidate",
    )
    assert "Coimbatore" not in model.prompts[0] and "internal-audit-token" not in model.prompts[0]
    checked = check_draft(
        Draft(
            subject="Hello",
            sentences=[
                DraftSentence(text="We met at your Coimbatore office.", cites="review_note")
            ],
        ),
        evidence=facts,
    )
    assert checked.checks[0].verdict is Verdict.UNSUPPORTED
