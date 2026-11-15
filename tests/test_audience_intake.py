"""Saved preferences and explicit payment gates through the real browser routes."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.core.intake import AudienceIntake, lead_stage
from outreach.web.app import create_app
from tests.test_platform import db_for, fake_provider, wait_for

GOAL = "Introduce myself to Bangalore AI product startups for job opportunities."


@pytest.fixture
def intake_app(settings):
    settings = settings.model_copy(
        update={"parallel_api_key": "fake", "openrouter_api_key": "fake"}
    )
    calls = []
    from outreach.adapters.research_api import ResearchAPI

    app = create_app(
        settings,
        research_api=lambda db, key: ResearchAPI(
            settings,
            db,
            key,
            client=httpx.Client(transport=httpx.MockTransport(fake_provider(calls))),
        ),
    )
    return settings, app, TestClient(app), calls


def save(client, **changes):
    values = {"brief": GOAL, "purpose": "job search", "target": "3", "budget": ".20"}
    values.update(changes)
    response = client.post("/research/intake", data=values, follow_redirects=False)
    key = response.headers["location"].split("?")[0].split("/")[-1]
    return key


def complete():
    return {
        "brief": GOAL,
        "purpose": "job search",
        "company_type": "AI product startups",
        "geography": "Bangalore",
        "contact_roles": ["founder", "hr", "management"],
        "target": "3",
        "budget": ".20",
    }


def test_goal_saved_without_mail_setup_or_api_and_survives_restart(intake_app):
    settings, app, client, calls = intake_app
    key = save(client)
    assert not calls
    page = TestClient(create_app(settings)).get("/research/" + key)
    assert page.status_code == 200
    assert "Before we research" in page.text and "Which contact roles" in page.text
    assert GOAL in page.text and "Audience draft saved" in page.text
    assert "Create plan for review" in page.text
    with db_for(settings) as db:
        run = db.run(key)
        assert run["status"] == "draft" and run["spent_micro"] == 0
        assert run["intake"]["goal"] == GOAL
        assert db.accounts() == []


@pytest.mark.parametrize("changes", [{}, {"action": "plan", "planning_confirm": "on"}])
def test_incomplete_intake_never_pays(intake_app, changes):
    settings, app, client, calls = intake_app
    key = save(client, **changes)
    assert not calls
    with db_for(settings) as db:
        assert db.run(key)["status"] == "draft"


def test_complete_preferences_need_paid_authorisation_and_are_in_actual_prompt(intake_app):
    settings, app, client, calls = intake_app
    key = save(client, **complete(), action="plan")
    assert not calls
    values = complete() | {"action": "plan", "planning_confirm": "on"}
    client.post("/research/" + key + "/intake", data=values)
    wait_for(app, key)
    assert len(calls) == 1
    assert "HR / recruiting" in json.dumps(calls[0][1])
    with db_for(settings) as db:
        run = db.run(key)
        assert run["status"] == "awaiting_approval" and not run["approved_at"]
        assert run["intake"]["contact_roles"] == ["founder", "hr", "management"]
        assert "HR / recruiting (department inbox accepted)" in run["brief"]
        assert "Do not guess addresses" in run["brief"]
        assert "do not" in run["brief"].lower()
        assert db.leads(key) == []
        before = run["brief"]
    # Editing a started audience is rejected, without changing approved scope or spending.
    client.post("/research/" + key + "/intake", data=complete() | {"geography": "Anywhere"})
    with db_for(settings) as db:
        assert db.run(key)["brief"] == before
    assert len(calls) == 1


def test_unknown_role_and_nonfinite_budget_do_not_create_runs(intake_app):
    settings, app, client, calls = intake_app
    for values in [complete() | {"contact_roles": ["made-up"]}, complete() | {"budget": "NaN"}]:
        client.post("/research/intake", data=values)
    with db_for(settings) as db:
        assert db.runs() == []
    assert not calls


def test_missing_provider_still_saves_complete_audience(settings):
    settings = settings.model_copy(update={"parallel_api_key": "", "openrouter_api_key": ""})
    client = TestClient(create_app(settings))
    key = save(client, **complete(), action="plan", planning_confirm="on")
    with db_for(settings) as db:
        assert db.run(key)["status"] == "draft" and db.run(key)["spent_micro"] == 0
    assert (
        "Configure the research providers"
        in client.get("/research/" + key + "?message=Configure%20the%20research%20providers").text
    )


def test_legacy_run_survives_additive_intake_schema(settings):
    with db_for(settings) as db:
        key = db.new_run(
            title="Legacy",
            brief=GOAL,
            purpose="job search",
            tags="",
            project_id=None,
            target=3,
            budget=200000,
        )
        db.conn.execute("DROP TABLE research_intakes")
        db.conn.execute("UPDATE schema_meta SET value='5' WHERE key='schema_version'")
    with db_for(settings) as db:
        assert db.run(key)["intake"] is None
    assert TestClient(create_app(settings)).get("/research/" + key).status_code == 200


def test_contact_roles_remain_separate_from_review_stage():
    lead = {"review_status": "pending", "emails": [{"value": "info@example.org"}]}
    assert lead_stage(lead) == "review"  # Publication doesn't establish the requested role.
    assert lead_stage(lead | {"emails": []}) == "missing"
    assert lead_stage(lead | {"review_status": "approved"}) == "approved"
    assert lead_stage(lead | {"review_status": "approved", "suppressed": True}) == "held"
    assert lead_stage(lead | {"review_status": "rejected"}) == "removed"
    brief = AudienceIntake(goal=GOAL, company_type="AI", geography="Anywhere", contact_roles=["hr"])
    assert brief.questions() == [] and "department" in brief.research_brief()


def test_refine_cannot_bypass_first_planning_gate(intake_app):
    settings, app, client, calls = intake_app
    key = save(client)
    client.post("/research/" + key + "/refine", data={"instruction": "Create the plan now"})
    assert not calls
    with db_for(settings) as db:
        assert db.run(key)["status"] == "draft"


def test_invalid_intake_keeps_entered_fields_without_creating_a_run(intake_app):
    settings, app, client, calls = intake_app
    response = client.post("/research/intake", data=complete() | {"budget": "9999"})
    assert response.status_code == 400
    assert GOAL in response.text and "AI product startups" in response.text
    assert 'value="hr" checked' in response.text and "Your entries are kept" in response.text
    assert not calls
    with db_for(settings) as db:
        assert db.runs() == []


def test_lead_review_redirect_preserves_filter():
    from outreach.web.platform import redirect

    response = redirect("/research/fixture?stage=review", "Saved")
    assert response.headers["location"] == "/research/fixture?stage=review&message=Saved"


def test_accepted_contact_roles_reach_company_contact_search(intake_app):
    from tests.test_platform import PLAN

    settings, app, client, calls = intake_app
    key = save(client, **complete(), action="plan", planning_confirm="on")
    wait_for(app, key)
    client.post(
        "/research/" + key + "/approve",
        data={
            "summary": PLAN["summary"],
            "criteria": "Makes textiles",
            "queries": PLAN["queries"][0],
            "alternate_queries": PLAN["alternate_queries"][0],
            "confirm": "on",
        },
    )
    wait_for(app, key)
    contact_search = next(
        body
        for path, body in calls
        if path.endswith("/search") and "professional emails" in body.get("objective", "")
    )
    assert "hr" in contact_search["objective"]
    assert "hr" in contact_search["search_queries"][0]
    with db_for(settings) as db:
        assert db.leads(key)[0]["review_status"] == "pending"
