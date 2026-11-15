"""Audience continuity and cost-effective page research; fictional providers only."""

import json

import pytest
from fastapi.testclient import TestClient

from outreach.core.audience_plan import local_plan
from outreach.core.intake import AudienceIntake
from outreach.core.research_scheduler import (
    ContactAssessment,
    attributed_emails,
    literal_brand_sites,
    ready_count,
)
from outreach.web.app import create_app
from outreach.web.research_view import request_summary
from tests.test_audience_intake import complete
from tests.test_platform import db_for, saved_lead
from tests.test_research_recovery import saved_zero_result
from tests.test_research_staged import (
    CONTACT,
    OFFICIAL,
    FictionalResearch,
    execute,
)
from tests.test_research_staged import (
    staged as staged,
)


@pytest.fixture
def workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(
        settings,
        research_api=lambda *a: pytest.fail("Unexpected paid request"),
        mailbox=lambda *a: pytest.fail("Unexpected mailbox operation"),
    )
    client = TestClient(app)
    response = client.post("/research/intake", data=complete(), follow_redirects=False)
    key = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    return settings, app, client, key


def revision(client, key):
    response = client.post(
        f"/research/{key}/revise",
        data=complete() | {"company_type": "Software startups"},
        follow_redirects=False,
    )
    return response.headers["location"].split("?")[0].rsplit("/", 1)[-1]


def test_free_plan_needs_no_provider_and_still_needs_paid_approval(workspace):
    config, app, client, key = workspace
    response = client.post(f"/research/{key}/intake", data=complete() | {"action": "plan_local"})
    assert "Plan prepared for free" in response.text
    assert "Review what we will research" in response.text
    with db_for(config) as db:
        run = db.run(key)
        assert run["status"] == "awaiting_approval" and not run["approved_at"]
        assert run["spent_micro"] == 0 and not db.rows("SELECT * FROM research_calls")
        assert run["execution"]["strategy_version"] == 6
        assert run["execution"]["plan_source"] == "local"
    assert not app.state.research.active


def test_local_plan_does_not_add_unrequested_hiring_or_role_criteria():
    intake = AudienceIntake(
        **{
            "goal": "Find founders at software startups to discuss a collaboration.",
            "company_type": "Software startups",
            "geography": "Anywhere",
            "contact_roles": ["founder"],
            "research_mode": "flexible",
        }
    )
    plan = local_plan(intake)
    assert plan.criteria == ["Software startups"]
    assert not plan.exclusions and "founder" in plan.queries[1]
    assert "vacanc" not in plan.model_dump_json().lower()


def test_revisions_share_one_card_and_original_ledger(workspace):
    config, _, client, key = workspace
    saved_zero_result(config, key)
    with db_for(config) as db:
        original = db.run(key)
        calls = db.rows("SELECT * FROM research_calls")
    second = revision(client, key)
    third = revision(client, second)
    with db_for(config) as db:
        assert len(db.audiences()) == 1
        assert db.audiences()[0]["id"] == third
        assert db.audiences()[0]["run_count"] == 3
        assert {r["id"] for r in db.audience_history(second)} == {key, second, third}
        assert db.run(key) == original and db.rows("SELECT * FROM research_calls") == calls
    assert "1 audiences" in client.get("/research").text
    home = client.get("/").text
    assert f'href="/research/{key}"' not in home
    assert f"/research/{third}" in home
    detail = client.get(f"/research/{key}").text
    assert "Continue latest version" in detail and f"/research/{third}" in detail


def test_latest_version_can_use_approved_contacts_from_older_run(workspace):
    config, _, client, key = workspace
    with db_for(config) as db:
        lead_id = saved_lead(db)
        db.conn.execute("UPDATE research_leads SET run_id=? WHERE id=?", (key, lead_id))
        db.review_leads([lead_id], action="approve", confirmed=True)
        db.save_campaign("target", "Target campaign", None, "sales", "", None)
    latest = revision(client, key)
    page = client.get(f"/research/{latest}/use").text
    assert "sales@mills.example" in page and "No approved contacts" not in page
    result = client.post(
        f"/research/{latest}/use",
        data={
            "lead_ids": [str(lead_id)],
            "campaign_id": "target",
            "action": "existing",
        },
    )
    assert "1 contacts added" in result.text
    with db_for(config) as db:
        assert db.store.emails_in_campaign("target") == {"sales@mills.example"}
    assert "Add emails to a campaign" in client.get(f"/research/{latest}").text


def test_existing_explicit_revision_message_groups_without_changing_rows(workspace):
    config, _, client, key = workspace
    child = revision(client, key)
    with db_for(config) as db:
        db.conn.execute("UPDATE research_execution SET state_json='{}' WHERE run_id=?", (child,))
        assert len(db.audiences()) == 1
        assert db.execution(child) == {"version": 2}
        assert len(db.audience_history(key)) == 2


def test_family_delete_and_restore_preserve_all_versions(workspace):
    config, _, client, key = workspace
    saved_zero_result(config, key)
    child = revision(client, key)
    response = client.post(
        f"/workspace/audience/{child}/remove",
        data={
            "action": "delete",
            "confirm_delete": "yes",
            "deletion_version": "trash-v1",
        },
    )
    assert response.status_code == 200
    with db_for(config) as db:
        assert db.run(key)["deleted"] and db.run(child)["deleted"]
        assert not db.audiences()
        assert db.rows("SELECT * FROM research_calls")
    client.post(f"/workspace/audience/{child}/remove", data={"action": "restore"})
    with db_for(config) as db:
        assert not db.run(key)["deleted"] and not db.run(child)["deleted"]
        assert len(db.audiences()) == 1


def test_family_delete_blocks_when_an_older_version_is_working(workspace):
    config, _, client, key = workspace
    child = revision(client, key)
    with db_for(config) as db:
        db.set_run(key, status="running")
    response = client.post(
        f"/workspace/audience/{child}/remove",
        data={
            "action": "delete",
            "confirm_delete": "yes",
            "deletion_version": "trash-v1",
        },
    )
    assert response.status_code == 409


def test_cap_extension_retains_ledger_and_makes_no_request(workspace):
    config, app, client, key = workspace
    saved_zero_result(config, key)
    with db_for(config) as db:
        db.save_execution(key, outcome="budget_limit")
        db.set_run(key, status="paused")
        calls = db.rows("SELECT * FROM research_calls")
        state = db.execution(key)
        spent = db.run(key)["spent_micro"]
    page = client.get(f"/research/{key}").text
    assert "Adjust the cap and continue this research" in page
    client.post(f"/research/{key}/limits", data={"target": "8", "budget": ".70", "confirm": "yes"})
    with db_for(config) as db:
        assert db.run(key)["target_count"] == 8 and db.run(key)["budget_micro"] == 700000
        assert db.run(key)["spent_micro"] == spent
        assert db.rows("SELECT * FROM research_calls") == calls and db.execution(key) == state
    assert not app.state.research.active


def test_cap_increase_requires_explicit_confirmation(workspace):
    config, _, client, key = workspace
    response = client.post(f"/research/{key}/limits", data={"target": "5", "budget": ".70"})
    assert "Confirm the larger total cap" in response.text
    with db_for(config) as db:
        assert db.run(key)["budget_micro"] == 200000


def test_uncertain_call_blocks_limit_changes(workspace):
    config, _, client, key = workspace
    with db_for(config) as db:
        db.set_run(key, status="running")
        db.reserve(key, "uncertain", "fixed-fingerprint", 1000, 5000000)
        db.set_run(key, status="paused")
    response = client.post(
        f"/research/{key}/limits", data={"target": "5", "budget": ".70", "confirm": "yes"}
    )
    assert "Check the uncertain provider request" in response.text
    with db_for(config) as db:
        assert db.run(key)["budget_micro"] == 200000
        assert db.call(key, "uncertain")["status"] != "complete"


def test_new_strategy_reaches_page_reads_on_ten_cent_cap(staged):
    db, key, _ = staged
    db.save_execution(key, strategy_version=3)
    db.set_run(key, budget_micro=100000)
    fake = FictionalResearch(search_email=True)
    execute(staged, fake)
    assert db.run(key)["execution"]["outcome"] == "target_reached"
    assert any(path.endswith("/extract") for path, _ in fake.calls)
    assert len([body for path, body in fake.calls if path.endswith("/chat/completions")]) == 2
    summary = request_summary(db, db.run(key), active=False)
    assert summary["fetches"] >= 1 and summary["searches"] == 3
    assert db.run(key)["spent_micro"] <= 100000


def test_founder_search_does_not_stop_at_general_search_excerpt(staged):
    db, key, _ = staged
    db.save_execution(key, strategy_version=3)
    db.conn.execute(
        "INSERT INTO research_intakes VALUES (?,?)",
        (key, json.dumps({"contact_roles": ["founder"], "research_mode": "flexible"})),
    )
    fake = FictionalResearch(search_email=True)
    execute(staged, fake)
    fetched = [body["urls"] for path, body in fake.calls if path.endswith("/extract")]
    assert [CONTACT["url"]] in fetched and [OFFICIAL["url"]] in fetched


def test_exact_brand_shortcut_never_guesses_or_uses_directories():
    source = {"url": OFFICIAL["url"], "text": OFFICIAL["full_content"], "title": OFFICIAL["title"]}
    assert literal_brand_sites([source], "Cedar Labs")[0]["website"] == OFFICIAL["url"]
    assert not literal_brand_sites(
        [source | {"url": "https://directory.example/cedar"}], "Cedar Labs"
    )
    assert not literal_brand_sites([source], "Unrelated Labs")
    assert not literal_brand_sites([source | {"text": "Other company"}], "Cedar Labs")
    assert not literal_brand_sites(
        [source, source | {"url": "https://cedarlabs.com/"}], "Cedar Labs"
    )


@pytest.mark.parametrize("bad", ["invented", "missing-name", "missing-role", "generic"])
def test_named_role_requires_literal_person_role_and_existing_address(bad):
    quote = "Alice Rivera, Founder, alice@cedar-labs.example"
    email = {"value": "alice@cedar-labs.example", "role_hint": "Role unconfirmed — review source"}
    claim = {
        "email": email["value"],
        "name": "Alice Rivera",
        "role": "founder",
        "source_id": "s1",
        "quote": quote,
    }
    if bad == "invented":
        claim["email"] = "invented@cedar-labs.example"
    elif bad == "missing-name":
        claim["name"] = "Other Person"
    elif bad == "missing-role":
        quote = "Alice Rivera, contact alice@cedar-labs.example"
        claim["quote"] = quote
    else:
        email["role_hint"] = "General business inbox"
    result = attributed_emails(
        [email],
        ContactAssessment(facts=[], fit_summary="", unknowns=[], contacts=[claim]),
        {"s1": {"text": quote, "url": OFFICIAL["url"]}},
    )
    assert result[0].get("contact_name") is None


def test_literal_founder_role_is_saved_and_counts_for_focused_target(staged):
    db, key, _ = staged
    quote = "Alice Rivera, Founder, alice@cedar-labs.example"
    email = {"value": "alice@cedar-labs.example", "role_hint": "Role unconfirmed — review source"}
    result = attributed_emails(
        [email],
        ContactAssessment(
            facts=[],
            fit_summary="",
            unknowns=[],
            contacts=[
                {
                    "email": email["value"],
                    "name": "Alice Rivera",
                    "role": "founder",
                    "source_id": "s1",
                    "quote": quote,
                }
            ],
        ),
        {"s1": {"text": quote, "url": OFFICIAL["url"]}},
    )
    assert result[0]["role_hint"] == "Founder / co-founder"
    assert result[0]["role_quote"] == quote
    candidate = {
        "company": "Cedar Labs",
        "website": OFFICIAL["url"],
        "identity_quote": "Cedar Labs",
        "source_url": OFFICIAL["url"],
    }
    lead = db.add_candidate(key, candidate)
    db.save_evidence(lead, facts=[], sources=[], emails=result, flags=[], summary="Needs review")
    db.conn.execute(
        "INSERT INTO research_intakes VALUES (?,?)",
        (
            key,
            json.dumps(
                {
                    "contact_roles": ["founder"],
                    "research_mode": "focused",
                }
            ),
        ),
    )
    assert ready_count(db, key) == 1


def test_known_companies_survive_free_plan_without_paid_calls(workspace):
    config, app, client, key = workspace
    seeds = "Cedar Labs | https://cedarlabs.example"
    response = client.post(
        f"/research/{key}/intake",
        data=complete() | {"seed_websites": seeds, "action": "plan_local"},
    )
    assert response.status_code == 200
    assert "cedarlabs.example" in response.text
    with db_for(config) as db:
        assert db.run(key)["intake"]["seed_websites"] == seeds
        assert db.run(key)["spent_micro"] == 0
        assert not db.rows("SELECT * FROM research_calls")


def test_invalid_seed_website_cannot_start_research(workspace):
    config, app, client, key = workspace
    client.post(
        f"/research/{key}/intake",
        data=complete() | {"seed_websites": "Internal | http://127.0.0.1", "action": "plan_local"},
    )
    with db_for(config) as db:
        assert db.run(key)["status"] == "draft"
        assert not db.rows("SELECT * FROM research_calls")
