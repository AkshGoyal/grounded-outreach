"""Prompt-first creation preserves paid-action and approval boundaries."""

import pytest
from fastapi.testclient import TestClient

from outreach.campaigns import load_closing, load_copy
from outreach.core.audience_plan import local_plan
from outreach.core.message_brief import MessageBrief
from outreach.core.models import DraftStatus
from outreach.core.prompt_intake import audience_from_prompt
from outreach.web.app import create_app
from tests.test_campaign_workspace import contact, draft
from tests.test_campaign_workspace import workspace as workspace
from tests.test_platform import db_for

AUDIENCE = (
    "Find textile manufacturers in India. Contact founders or senior management "
    "about RFD cotton thread supply. Exclude trading-only businesses."
)
MESSAGE = (
    "Introduce our RFD cotton thread business in Ludhiana. Offer a sample and ask "
    "whether they would like to discuss supply. Keep it concise and professional."
)
EXACT = "Would you like a sample?\nRegards,\nStar Threads"


def test_one_audience_prompt_prepares_free_plan_without_any_provider(settings):
    app = create_app(settings, research_api=lambda *a: pytest.fail("Paid call"))
    client = TestClient(app)
    response = client.post(
        "/research/intake",
        data={"input_mode": "prompt", "action": "save_prompt", "brief": AUDIENCE},
        follow_redirects=False,
    )
    assert response.status_code == 303
    key = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        run = db.run(key)
        assert run["status"] == "awaiting_approval" and not run["approved_at"]
        assert run["intake"]["company_type"] == "textile manufacturers"
        assert run["intake"]["geography"] == "India"
        assert run["intake"]["contact_roles"] == ["founder", "management"]
        assert run["plan"]["summary"] == AUDIENCE
        assert run["plan"]["exclusions"] == ["trading-only businesses"]
        assert not db.rows("SELECT * FROM research_calls") and run["spent_micro"] == 0
    assert not app.state.research.active
    page = client.get(f"/research/{key}").text
    assert "Review what we will research" in page
    assert "authorize research" in page


def test_missing_scope_is_clarified_without_guessing(settings):
    client = TestClient(create_app(settings))
    response = client.post(
        "/research/intake",
        data={
            "input_mode": "prompt",
            "action": "save_prompt",
            "brief": "Find useful companies to discuss our business.",
        },
        follow_redirects=False,
    )
    key = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        run = db.run(key)
        assert run["status"] == "draft" and not run["plan"]
        assert run["intake"]["contact_roles"] == []
        assert run["intake"]["geography"] == ""
    assert "We need a little more detail" in client.get(f"/research/{key}").text


def test_prompt_changes_do_not_reuse_old_derived_scope(settings):
    client = TestClient(create_app(settings))
    response = client.post(
        "/research/intake",
        data={
            "input_mode": "prompt",
            "action": "save_prompt",
            "brief": "Find textile manufacturers in India. Contact HR.",
        },
        follow_redirects=False,
    )
    original = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        snapshot = db.run(original)
    response = client.post(
        f"/research/{original}/revise",
        data={
            "input_mode": "prompt",
            "action": "save_prompt",
            "brief": "Find software startups in Germany. Contact founders.",
            "company_type": "textile manufacturers",
            "geography": "India",
            "contact_roles": "hr",
        },
        follow_redirects=False,
    )
    revised = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        assert db.run(original) == snapshot
        assert db.run(revised)["intake"]["geography"] == "Germany"
        assert db.run(revised)["intake"]["contact_roles"] == ["founder"]
        assert not db.run(revised)["approved_at"]


def test_excluded_roles_are_not_selected_and_long_prompts_are_not_truncated():
    intake = audience_from_prompt(
        "Find AI startups in Bangalore. Contact HR. Do not contact founders."
    )
    assert intake.contact_roles == ["hr"]
    assert "founder" not in local_plan(intake).queries[1]
    with pytest.raises(ValueError, match="2,000"):
        audience_from_prompt("Find companies " + "x" * 2000)


def test_message_prompt_and_exact_lines_save_without_generation_or_mail(workspace):
    settings, _, client, box, llm = workspace
    response = client.post(
        "/campaigns/new",
        data={"message_prompt": MESSAGE, "brief_mode": "structured", "closing": EXACT},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cid = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        assert db.campaign(cid)["message_brief"]["message_prompt"] == MESSAGE
        assert db.campaign(cid)["sender_account_id"] is None
    assert MESSAGE in load_copy(cid) and load_closing(cid) == EXACT
    assert not llm.prompts and not box.sent
    page = client.get(f"/campaigns/{cid}/message").text
    assert MESSAGE in page and "Keep selected text exactly" in page and EXACT in page


def test_prompt_edit_invalidates_only_unsent_approvals(workspace):
    settings, _, client, box, llm = workspace
    client.post(
        "/campaigns/new",
        data={
            "name": "Prompt",
            "message_prompt": MESSAGE,
            "brief_mode": "structured",
            "closing": EXACT,
        },
    )
    with db_for(settings) as db:
        unsent = draft(db, contact(db, "prompt"), DraftStatus.APPROVED)
        sent = draft(db, contact(db, "prompt", "sent@fictional.example"), DraftStatus.SENT)
    client.post(
        "/campaigns/prompt/message",
        data={"message_prompt": MESSAGE + " Ask for a short call.", "closing": EXACT},
    )
    with db_for(settings) as db:
        assert db.store.get_draft(unsent).status is DraftStatus.REVIEW
        assert db.store.get_draft(sent).status is DraftStatus.SENT
    assert load_closing("prompt") == EXACT and not box.sent and not llm.prompts


def test_invalid_campaign_keeps_prompt_and_exact_lines(workspace):
    _, _, client, _, _ = workspace
    response = client.post(
        "/campaigns/new",
        data={
            "name": "!!!",
            "message_prompt": MESSAGE,
            "brief_mode": "structured",
            "closing": EXACT,
        },
    )
    assert response.status_code == 400 and MESSAGE in response.text and EXACT in response.text


def test_prompt_only_brief_and_legacy_structured_brief_both_compile():
    assert MessageBrief(message_prompt=MESSAGE).missing() == []
    assert MessageBrief(message_prompt=MESSAGE).campaign_copy() == MESSAGE
    assert MessageBrief(message_prompt="short").campaign_copy() == "short"
    assert MessageBrief().missing() == ["Email instructions"]
    legacy = MessageBrief(
        topic="Introduction", introduction="Our thread business", desired_response="Please reply"
    )
    assert "Our thread business" in legacy.campaign_copy()


def test_additional_campaign_batch_uses_the_shared_prompt_form(workspace):
    settings, _, client, box, llm = workspace
    client.post(
        "/campaigns/new",
        data={"name": "Prompt", "message_prompt": MESSAGE, "brief_mode": "structured"},
    )
    page = client.get("/campaigns/prompt/research").text
    assert 'name="input_mode" value="prompt"' in page and 'value="save_prompt"' in page
    response = client.post(
        "/campaigns/prompt/research",
        data={"input_mode": "prompt", "action": "save_prompt", "brief": AUDIENCE},
        follow_redirects=False,
    )
    assert response.status_code == 303
    key = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(settings) as db:
        assert db.research_campaign(key)["id"] == "prompt"
        assert db.run(key)["status"] == "awaiting_approval"
        assert not db.run(key)["approved_at"] and not db.rows("SELECT * FROM research_calls")
    assert not box.sent and not llm.prompts


def test_browser_crlf_exact_lines_do_not_gain_blank_lines(workspace):
    _, _, client, _, _ = workspace
    client.post(
        "/campaigns/new",
        data={
            "name": "Windows lines",
            "message_prompt": MESSAGE,
            "brief_mode": "structured",
            "closing": EXACT.replace("\n", "\r\n"),
        },
    )
    assert load_closing("windows-lines") == EXACT
    client.post(
        "/campaigns/windows-lines/message",
        data={"message_prompt": MESSAGE, "closing": EXACT.replace("\n", "\r\n")},
    )
    assert load_closing("windows-lines") == EXACT
