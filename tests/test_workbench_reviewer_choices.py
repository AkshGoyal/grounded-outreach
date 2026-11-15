"""The reviewer decides what stays: remove a sentence, or pick the facts to write from."""

from fastapi.testclient import TestClient

from outreach.adapters.workbench_fixture import FixtureResearchProvider
from outreach.core.workbench import DEMO_CAMPAIGN, run_pipeline
from outreach.core.workbench_claims import draft_context
from outreach.wiring import build_workbench_app
from tests.test_workbench_spine import payload, workbench_settings, settled, start  # noqa: F401

PROSPECT = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"}


def test_draft_context_offers_extra_facts_and_honours_exclusions():
    result = run_pipeline(PROSPECT, DEMO_CAMPAIGN, FixtureResearchProvider(), lambda *a: None)
    full = draft_context({"result": result, "campaign": DEMO_CAMPAIGN, "prospect": PROSPECT})
    assert {"capability-1", "capability-2"} <= set(full["supports"])
    trimmed = draft_context(
        {
            "result": result,
            "campaign": DEMO_CAMPAIGN,
            "prospect": PROSPECT,
            "exclude": ["capability-2", full["hook"]["source_id"]],
        }
    )
    assert "capability-2" not in trimmed["supports"]
    # The hook itself can never be excluded.
    assert full["hook"]["source_id"] in trimmed["supports"]


def test_remove_this_sentence_makes_a_checked_new_revision(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client, payload())
        run = settled(client, path)
        draft = run["draft"]
        page = client.get(path).text
        assert "Remove this sentence" in page and "Rewrite with the ticked facts" in page
        sentence = next(
            s["text"]
            for s in draft["check"]["segments"]
            if s["part"] == "body" and "It can also" in s["text"]
        )
        response = client.post(
            path + "/draft/check",
            data={"base_revision": draft["revision"], "remove": sentence},
            follow_redirects=False,
        )
        assert response.status_code == 303
        after = client.get(path + "/status").json()["draft"]
        assert after["revision"] == draft["revision"] + 1 and after["origin"] == "reviewer"
        assert sentence not in after["body"] and "Hi Maya," in after["body"]
        assert after["check"]["ok"], after["check"]["errors"]


def test_rewrite_with_ticked_facts_needs_at_least_one(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client, payload())
        draft = settled(client, path)["draft"]
        none = client.post(
            path + "/draft/write",
            data={"choose_facts": "1", "offered": ["capability-1", "capability-2"]},
        )
        assert none.status_code == 422 and "Tick at least one fact" in none.text
        response = client.post(
            path + "/draft/write",
            data={
                "choose_facts": "1",
                "offered": ["capability-1", "capability-2"],
                "use": ["capability-1"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        after = client.get(path + "/status").json()
        assert after["draft"]["revision"] > draft["revision"]
        assert after["execution_status"] == "completed"
