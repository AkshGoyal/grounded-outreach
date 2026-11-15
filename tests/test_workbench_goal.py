"""Editable outreach goal: validation, immutable snapshots, and use in live research."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from outreach.core.workbench import DEMO_CAMPAIGN, CampaignGoal, goal_values
from outreach.core.workbench_claims import draft_context
from tests.test_workbench_parallel import PublicSources
from tests.test_workbench_research_routes import config, live_app  # noqa: F401
from tests.test_workbench_spine import payload, workbench_settings, settled, start  # noqa: F401

GOAL = {
    "sender_name": "Sam Lee",
    "sender_company": "Northbeam Demo",
    "offer": "Spend analytics for procurement teams",
    "intended_role": "Procurement leaders",
    "capabilities": "Group supplier spend by category.\n- Flag duplicate supplier records.",
    "proof_points": "",
    "looking_for": "new procurement leader, supplier consolidation",
    "cta": "Would a short look at your supplier spend be useful?",
}


def test_default_goal_round_trips_to_the_demo_snapshot():
    assert CampaignGoal.model_validate(goal_values(DEMO_CAMPAIGN)).campaign() == DEMO_CAMPAIGN


def test_custom_goal_is_content_addressed_and_feeds_the_checker():
    first = CampaignGoal.model_validate(GOAL).campaign()
    again = CampaignGoal.model_validate(dict(GOAL, offer=GOAL["offer"] + ".")).campaign()
    assert first == again and first["id"].startswith("goal-") and first["version"] == 1
    assert first["fixture"] is False
    assert first["supported_capabilities"] == [
        "Group supplier spend by category.",
        "Flag duplicate supplier records.",
    ]
    assert first["sender"] == "Sam Lee, Northbeam Demo"
    changed = CampaignGoal.model_validate(dict(GOAL, cta="Is this worth a short call?")).campaign()
    assert changed["id"] != first["id"]
    context = draft_context({"campaign": first, "prospect": {"name": "A", "company": "B"}})
    assert context["supports"]["capability-2"]["text"] == "Flag duplicate supplier records."
    assert context["cta"] == GOAL["cta"] and context["sender_company"] == "Northbeam Demo"


@pytest.mark.parametrize(
    "change",
    [
        {"cta": "Book a call."},
        {"cta": "Is this useful? Or not?"},
        {"capabilities": ""},
        {"capabilities": "a\nb\nc\nd\ne"},
        {"sender_company": "Acme, Inc"},
        {"offer": "Is it good?"},
        {"proof_points": "Cut errors?"},
    ],
)
def test_goal_rejects_claims_the_checker_could_not_enforce(change):
    with pytest.raises(ValidationError):
        CampaignGoal.model_validate(GOAL | change)


def test_goal_page_sets_the_goal_every_new_run_uses(config):  # noqa: F811
    fake = PublicSources()
    app = live_app(config, fake)
    with TestClient(app) as client:
        form = client.get("/research/new").text
        # The goal is on the first page: the three choices, the goal itself and its editor.
        for choice in ("Write an email for my goal", "Research for my goal", "Just research"):
            assert choice in form
        assert 'name="offer"' in form and DEMO_CAMPAIGN["cta"] in form
        page = client.get("/goal").text
        assert "Your goal" in page and DEMO_CAMPAIGN["cta"] in page and "Save goal" in page
        saved = client.post("/goal", data=GOAL, follow_redirects=False)
        assert saved.status_code == 303 and "Goal saved" in client.get("/goal?saved=1").text
        assert not fake.calls  # saving a goal costs nothing
        assert GOAL["offer"] in client.get("/research/new").text
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["campaign"]["offer"] == GOAL["offer"] + "."
        assert run["campaign"]["looking_for"] == GOAL["looking_for"]
        signal = [body for p, body in fake.calls if p.endswith("/search")][1]
        assert GOAL["looking_for"] in signal["objective"]
        assert any(GOAL["looking_for"] in q for q in signal["search_queries"])
        detail = client.get("/runs/" + run["id"]).text
        assert "Goal used for this run" in detail and "Your goal, from Sam Lee" in detail
        goal_page = client.get("/goal").text
        assert "Reset to the default goal" in goal_page
        reset = client.get("/goal?reset=default").text
        assert 'value="' + DEMO_CAMPAIGN["cta"] in reset
        # Posting goal fields with a run (older clients) also works and becomes current.
        other = GOAL | {"offer": "Supplier spend analytics for procurement"}
        run = settled(client, start(client, payload(live_consent="on", **other)))
        assert run["campaign"]["offer"] == other["offer"] + "."
        assert other["offer"] in client.get("/research/new").text


def test_invalid_goal_keeps_entries_and_spends_nothing(config):  # noqa: F811
    fake = PublicSources()
    app = live_app(config, fake)
    with TestClient(app) as client:
        response = client.post("/goal", data=GOAL | {"cta": "Book a call."})
        assert response.status_code == 422
        assert "Closing question:" in response.text and 'value="Book a call."' in response.text
        assert not fake.calls
        with app.state.open_workbench_store() as db:
            assert not db.list_workbench_runs()
        assert GOAL["offer"] not in client.get("/research/new").text


def test_example_mode_keeps_the_demo_goal(workbench_settings):  # noqa: F811
    from outreach.wiring import build_workbench_app

    with TestClient(build_workbench_app(workbench_settings)) as client:
        page = client.get("/research/new").text
        assert "Write an email for my goal" in page and 'name="offer"' not in page
        goal = client.get("/goal").text
        assert "Save goal" not in goal and "fixed here" in goal
        assert client.post("/goal", data=GOAL).status_code == 409
        run = settled(client, start(client, payload(**GOAL)))
        assert run["campaign"] == DEMO_CAMPAIGN


def test_new_demo_goal_saves_beside_an_older_stored_version(tmp_path):
    """A database seeded before the demo goal changed must still accept the new one."""
    import json

    from outreach.adapters.db import connect
    from outreach.adapters.workbench_store import WorkbenchStore
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.core.workbench import DEMO_CAMPAIGN

    store = WorkbenchStore(SqliteStore(connect(tmp_path / "workbench.db")))
    older = {**DEMO_CAMPAIGN, "version": 1, "proof_points": []}
    store.conn.execute(
        "INSERT OR REPLACE INTO workbench_campaign_versions VALUES (?,?,?,?)",
        (older["id"], 1, json.dumps(older, sort_keys=True), "2026-11-10T00:00:00+00:00"),
    )
    saved = store.set_current_goal("live", dict(DEMO_CAMPAIGN))
    assert saved["version"] == DEMO_CAMPAIGN["version"] and saved["proof_points"]
    assert store.latest_campaign("live")["proof_points"] == DEMO_CAMPAIGN["proof_points"]


def test_goal_lives_on_the_start_page_not_in_the_menu(config):  # noqa: F811
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        client.post("/goal", data=GOAL)
        for path in ("/research/new", "/batch/new"):
            page = client.get(path).text
            side = page.split('class="side-nav"', 1)[1].split("</nav>", 1)[0]
            assert 'href="/goal"' not in side
            assert GOAL["offer"] in page and 'href="?goal=default"' in page
            reset = client.get(path + "?goal=default").text
            assert DEMO_CAMPAIGN["offer"].rstrip(".") in reset
            assert '<details class="goal-edit" open' in reset
        assert not fake.calls
