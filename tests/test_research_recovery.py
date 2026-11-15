"""Cached evidence recovery and editing must never replay paid work."""

import json

import pytest
from fastapi.testclient import TestClient

from outreach.core.discovery import checked_candidates, sources_of
from outreach.core.intake import lead_stage
from outreach.core.research import Candidates
from outreach.web.app import create_app
from tests.test_audience_intake import complete
from tests.test_platform import PLAN, SOURCE, db_for


@pytest.mark.parametrize(
    ("website", "source_url", "quote", "allowed"),
    [
        (
            "https://mills.example/",
            "https://mills.example/news",
            "Example Mills makes textiles",
            True,
        ),
        (
            "https://mills.example/",
            "https://www.mills.example/news",
            "Example Mills makes textiles",
            True,
        ),
        (
            "https://mills.example/contact",
            "https://mills.example/contact",
            "Example Mills makes textiles",
            True,
        ),
        (
            "https://mills.example/guessed",
            "https://mills.example/news",
            "Example Mills makes textiles",
            False,
        ),
        (
            "https://other.example/",
            "https://mills.example/news",
            "Example Mills makes textiles",
            False,
        ),
        (
            "https://linkedin.com/",
            "https://linkedin.com/posts",
            "Example Mills makes textiles",
            False,
        ),
        ("http://127.0.0.1/", "https://mills.example/news", "Example Mills makes textiles", False),
        (
            "https://mills.example/",
            "https://mills.example/news",
            "Invented evidence about this company",
            False,
        ),
    ],
)
def test_homepage_matching_preserves_domain_path_and_literal_guards(
    website, source_url, quote, allowed
):
    answer = Candidates(
        candidates=[
            {
                "company": "Example Mills",
                "website": website,
                "source_id": "s1",
                "identity_quote": quote,
            }
        ]
    )
    accepted, rejected = checked_candidates(
        sources_of({"results": [SOURCE | {"url": source_url}]}), answer
    )
    assert bool(accepted) is allowed
    assert bool(rejected) is not allowed


@pytest.fixture
def recovery_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(settings, research_api=lambda *args: pytest.fail("No paid requests allowed"))
    client = TestClient(app)
    response = client.post("/research/intake", data=complete(), follow_redirects=False)
    key = response.headers["location"].split("?")[0].split("/")[-1]
    return settings, app, client, key


def saved_zero_result(config, key):
    with db_for(config) as db:
        # This fixture represents cached requests from the original engine.
        db.conn.execute("DELETE FROM research_execution WHERE run_id=?", (key,))
        db.set_run(key, status="running", approved_at="2026-10-07", plan_json=json.dumps(PLAN))
        responses = {
            "discovery/1": {"results": [SOURCE | {"url": "https://mills.example/news"}]},
            "discovery-select/1": {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "company": "Example Mills",
                                            "website": "https://mills.example/",
                                            "source_id": "s1",
                                            "identity_quote": "Example Mills makes textiles",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        }
        for call, result in responses.items():
            db.reserve(key, call, call, 1000, 5000000)
            db.finish_call(key, call, result, 1000, "tariff")
        db.set_run(key, status="completed")


def test_saved_zero_result_recovery_is_local_idempotent_and_preserves_ledger(recovery_workspace):
    config, app, client, key = recovery_workspace
    saved_zero_result(config, key)
    with db_for(config) as db:
        calls = db.rows("SELECT * FROM research_calls")
        original = db.run(key)
    page = client.get(f"/research/{key}").text
    assert "All 2 requests finished. Nothing is waiting" in page
    assert "Recover saved suggestions (free)" in page
    client.post(f"/research/{key}/recover-discovery")
    with db_for(config) as db:
        assert db.rows("SELECT * FROM research_calls") == calls
        assert len(db.leads(key)) == 1 and not db.leads(key)[0]["emails"]
        assert lead_stage(db.leads(key)[0]) == "checking"
        assert db.run(key)["status"] == "paused"
        for field in ("spent_micro", "budget_micro", "plan_json", "approved_at"):
            assert db.run(key)[field] == original[field]
    assert (
        "0 company suggestions recovered" in client.post(f"/research/{key}/recover-discovery").text
    )
    with db_for(config) as db:
        assert len(db.leads(key)) == 1 and db.rows("SELECT * FROM research_calls") == calls


def test_inactive_reserved_request_is_not_described_as_a_queue(recovery_workspace):
    config, app, client, key = recovery_workspace
    with db_for(config) as db:
        db.set_run(key, status="planning")
        db.reserve(key, "plan/1", "fingerprint", 1000, 5000000)
        db.set_run(key, status="failed")
    page = client.get(f"/research/{key}").text
    assert "These are not queued requests" in page
    snapshot = client.get(f"/research/{key}/status").json()["requests"]
    assert snapshot["needs_check"] == 1 and snapshot["waiting"] == 0
    assert snapshot["unconfirmed"] == 0.001


def test_edit_started_audience_creates_free_revision_and_keeps_original(recovery_workspace):
    config, app, client, key = recovery_workspace
    saved_zero_result(config, key)
    with db_for(config) as db:
        original = db.run(key)
        calls = db.rows("SELECT * FROM research_calls")
    page = client.get(f"/research/{key}/edit").text
    assert (
        "Save next version of this audience" in page and f'action="/research/{key}/revise"' in page
    )
    assert "data-wizard" not in page
    response = client.post(
        f"/research/{key}/revise",
        data=complete() | {"geography": "Anywhere", "action": "plan", "planning_confirm": "on"},
        follow_redirects=False,
    )
    revised = response.headers["location"].split("?")[0].split("/")[-1]
    with db_for(config) as db:
        assert revised != key and db.run(key) == original
        assert db.rows("SELECT * FROM research_calls") == calls
        new = db.run(revised)
        assert new["status"] == "draft" and new["spent_micro"] == 0
        assert new["intake"]["geography"] == "Anywhere"
        assert not new["plan"] and not new["approved_at"]


def test_edit_unused_draft_updates_in_place_and_revision_errors_keep_inputs(recovery_workspace):
    config, app, client, key = recovery_workspace
    page = client.get(f"/research/{key}/edit").text
    assert "Save changes" in page and f'action="/research/{key}/intake"' in page
    client.post(
        f"/research/{key}/intake", data=complete() | {"geography": "Anywhere", "edit_view": "1"}
    )
    with db_for(config) as db:
        assert len(db.runs()) == 1 and db.run(key)["intake"]["geography"] == "Anywhere"
    response = client.post(
        f"/research/{key}/revise",
        data=complete() | {"budget": "9999", "geography": "Keep these new ideas"},
    )
    assert response.status_code == 400
    assert (
        "Keep these new ideas" in response.text
        and f'action="/research/{key}/revise"' in response.text
    )
    with db_for(config) as db:
        assert len(db.runs()) == 1
