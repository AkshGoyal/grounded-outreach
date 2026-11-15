"""The four labelled edge cases, end to end through routes, worker, pipeline and storage.

All people, companies and sources are fictional fixture data; the identity, hook, claim
and review logic is the same code that judges live provider responses.
"""

import pytest
from fastapi.testclient import TestClient

from outreach.adapters.workbench_fixture import SCENARIOS
from outreach.config import Settings
from outreach.wiring import build_workbench_app
from tests.test_workbench_spine import payload, settled, start

BY_KEY = {s["key"]: s for s in SCENARIOS}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Settings(_env_file=None, db_path=str(tmp_path / "workbench.db"))
    with TestClient(build_workbench_app(config)) as test_client:
        yield test_client


def run_scenario(client, key):
    prospect = BY_KEY[key]["prospect"]
    path = start(client, payload(**prospect))
    return path, settled(client, path)


def approve(client, path, draft):
    return client.post(
        path + "/draft/approve",
        data={"revision": draft["revision"], "content_hash": draft["content_hash"]},
        follow_redirects=False,
    )


def test_new_research_lists_labelled_scenarios_and_prefills_one(client):
    page = client.get("/research/new").text
    assert len(SCENARIOS) == 5
    for scenario in SCENARIOS:
        assert scenario["label"] in page
        assert f"/research/new?scenario={scenario['key']}" in page
    filled = client.get("/research/new?scenario=same-name").text
    assert 'value="Jordan Ellis"' in filled and 'value="Northwind Supply"' in filled
    assert client.get("/research/new?scenario=missing").status_code == 200


def test_live_mode_shows_no_fixture_scenarios(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Settings(_env_file=None, db_path=str(tmp_path / "live.db"))
    with TestClient(build_workbench_app(config, mode="live")) as live:
        page = live.get("/research/new").text
        assert "Demo scenarios" not in page and "Jordan Ellis" not in page
        assert 'value="Jordan Ellis"' not in live.get("/research/new?scenario=same-name").text


def test_same_name_changed_employer_requires_confirmation_and_never_uses_other_person(client):
    path, run = run_scenario(client, "same-name")
    assert run["business_outcome"] == "needs_identity_confirmation"
    assert not run["drafts"]
    candidates = run["result"]["identity"]["candidates"]
    right = next(c for c in candidates if c["company"] == "Northwind Supply")
    wrong = next(c for c in candidates if c["company"] == "Harbor Line Logistics")
    assert right["selectable"] and not wrong["selectable"]
    page = client.get(path).text
    assert "Confirm prospect" in page and "Harbor Line Logistics" in page
    refused = client.post(
        path + "/confirm-prospect",
        data={"candidate_id": wrong["id"], "evidence_version": run["evidence_version"]},
    )
    assert refused.status_code == 409
    confirmed = client.post(
        path + "/confirm-prospect",
        data={"candidate_id": right["id"], "evidence_version": run["evidence_version"]},
        follow_redirects=False,
    )
    assert confirmed.status_code == 303
    done = settled(client, path)
    assert done["business_outcome"] == "ready_for_review", done["result"]
    assert done["result"]["hook"]["source_ids"] == ["northwind-approvals"]
    held = {s.get("source_id"): s["reason"] for s in done["result"]["rejected_signals"]}
    assert "confirmed company" in held["harbor-line-matching"]
    draft = done["draft"]
    assert "Harbor" not in draft["subject"] + draft["body"]
    assert "Head of Finance" not in draft["body"]


def test_blocked_and_sparse_sources_fall_back_to_a_weaker_role_hook(client):
    path, run = run_scenario(client, "sparse")
    assert run["execution_status"] == "completed"
    assert run["business_outcome"] == "ready_for_review"
    hook = run["result"]["hook"]
    assert hook["strength"] == "weak" and hook["source_ids"] == ["fernhill-speakers"]
    assert hook["event_date"] is None and hook["temporal_label"] != "Recent event"
    assert run["result"]["identity"]["status"] == "matched"  # permitted alternative page
    status = {s["id"]: s["access_status"] for s in run["result"]["sources"]}
    assert status["fernhill-leadership"] == "blocked"
    assert status["fernhill-linkedin"] == "blocked"
    assert status["fernhill-press-preview"] == "preview"
    assert status["fernhill-speakers"] == "read"
    assert any("refused automated reading" in item for item in run["result"]["limitations"])
    page = client.get(path).text
    assert "Weaker hook" in page and "Not used as proof" in page
    assert "Research unavailable" not in page  # insufficient evidence, not provider failure


def test_republished_old_news_and_conflicting_detail_fall_back_to_evergreen_hook(client):
    path, run = run_scenario(client, "republished")
    result = run["result"]
    assert run["business_outcome"] == "ready_for_review", result
    assert result["hook"]["source_ids"] == ["larkspur-finance"]
    assert result["hook"]["temporal_label"] == "Evergreen evidence"
    reasons = {s.get("source_id"): s["reason"] for s in result["rejected_signals"]}
    assert "older than the recent-event window" in reasons["larkspur-republished"]
    assert "conflict" in reasons["larkspur-consolidation"]
    assert "conflict" in reasons["larkspur-trade-report"]
    body = run["draft"]["body"].lower()
    assert "recent" not in body and "2023" not in body and "consolidat" not in body
    # The checker still refuses to call the evergreen hook recent if a reviewer tries.
    draft = run["draft"]
    recent = draft["body"].replace("I read that", "I recently read that")
    response = client.post(
        path + "/draft/check",
        data={"subject": draft["subject"], "body": recent, "base_revision": draft["revision"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    rechecked = client.get(path + "/status").json()
    assert rechecked["review"]["state"] == "needs_revision"
    assert "recency" in {i["code"] for i in rechecked["draft"]["check"]["errors"]}


def test_true_signal_false_inference_is_repaired_once_then_blocked_until_fixed(client):
    path, run = run_scenario(client, "false-inference")
    assert run["result"]["hook"]["source_ids"] == ["ridgeway-review-queue"]
    assert run["business_outcome"] == "needs_revision"
    assert [d["supported"] for d in run["drafts"]] == [False, False]
    draft = run["draft"]
    assert approve(client, path, draft).status_code == 409
    assert client.get(path + "/export").status_code == 409
    page = client.get(path).text
    assert "slowing" in page and "Blocks approval" in page
    sentence = "The new review suggests unresolved exceptions are slowing your team down. "
    assert sentence in draft["body"]
    fixed = client.post(
        path + "/draft/check",
        data={
            "subject": draft["subject"],
            "body": draft["body"].replace(sentence, ""),
            "base_revision": draft["revision"],
        },
        follow_redirects=False,
    )
    assert fixed.status_code == 303
    saved = client.get(path + "/status").json()
    assert saved["review"]["state"] == "ready_for_review"
    assert approve(client, path, saved["draft"]).status_code == 303
    assert "slowing" not in client.get(path + "/export").text
