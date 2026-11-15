"""Additional campaign research must remain free until separate approval."""

import pytest
from fastapi.testclient import TestClient

from outreach.web.app import create_app
from tests.test_audience_intake import complete
from tests.test_platform import db_for, saved_lead
from tests.test_research_recovery import saved_zero_result


@pytest.fixture
def batch_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(
        settings,
        research_api=lambda *args: pytest.fail("Unexpected provider request"),
        mailbox=lambda *args: pytest.fail("Unexpected mail operation"),
    )
    with db_for(settings) as db:
        db.save_campaign("career", "Career", None, "job search", "", None)
    return settings, app, TestClient(app)


def batch(client, **values):
    response = client.post(
        "/campaigns/career/research", data=complete() | values, follow_redirects=False
    )
    assert response.status_code == 303
    return response.headers["location"].split("?")[0].rsplit("/", 1)[-1]


def test_more_batches_are_free_with_separate_caps_and_history_unchanged(batch_workspace):
    config, app, client = batch_workspace
    first = batch(client, target="3", budget="0.20")
    saved_zero_result(config, first)
    with db_for(config) as db:
        original = db.run(first)
        calls = db.rows("SELECT * FROM research_calls")
    second = batch(client, target="12", budget="0.75", action="plan", planning_confirm="yes")
    with db_for(config) as db:
        assert first != second and db.run(first) == original
        assert db.rows("SELECT * FROM research_calls") == calls
        new = db.run(second)
        assert new["status"] == "draft" and not new["plan"] and new["spent_micro"] == 0
        assert new["target_count"] == 12 and new["budget_micro"] == 750000
        assert db.research_campaign(second)["id"] == "career"
        assert len(db.campaign_runs("career")) == 2
        assert not db.store.emails_in_campaign("career")
    page = client.get("/campaigns/career/research").text
    assert "Your research batches" in page and "1 saved companies" not in page
    assert "Next batch size &amp; spending cap" in page
    assert "Save next research batch (free)" in page


def test_prefill_and_invalid_batch_preserve_inputs_and_campaign(batch_workspace):
    config, app, client = batch_workspace
    key = batch(client, geography="Anywhere")
    page = client.get("/campaigns/career/research").text
    assert 'value="Anywhere"' in page
    assert 'action="/campaigns/career/research"' in page
    assert "data-wizard" not in page
    response = client.post(
        "/campaigns/career/research",
        data=complete() | {"target": "26", "geography": "My new location"},
    )
    assert response.status_code == 400 and "My new location" in response.text
    assert 'action="/campaigns/career/research"' in response.text
    with db_for(config) as db:
        assert len(db.runs()) == 1
        assert db.research_campaign(key)["id"] == "career"


@pytest.mark.parametrize("status", ["archived", "completed"])
def test_closed_campaign_cannot_start_another_batch(batch_workspace, status):
    config, app, client = batch_workspace
    with db_for(config) as db:
        db.conn.execute(
            "UPDATE campaign_settings SET status=? WHERE campaign_id='career'", (status,)
        )
    response = client.post("/campaigns/career/research", data=complete())
    assert response.status_code == 409
    assert "Reopen" in client.get("/campaigns/career/research").text
    with db_for(config) as db:
        assert not db.runs()


def test_revision_keeps_campaign_and_family_removal_preserves_history(batch_workspace):
    config, app, client = batch_workspace
    first = batch(client)
    saved_zero_result(config, first)
    response = client.post(f"/research/{first}/revise", data=complete(), follow_redirects=False)
    revised = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    with db_for(config) as db:
        assert db.research_campaign(revised)["id"] == "career"
    client.post(
        f"/workspace/audience/{revised}/remove",
        data={"action": "delete", "confirm_delete": "yes", "deletion_version": "trash-v1"},
    )
    with db_for(config) as db:
        assert db.run(revised)["deleted"] and db.run(first)["deleted"]
        assert db.research_campaign(revised)["id"] == "career"
        assert db.rows("SELECT * FROM research_calls WHERE run_id=?", (first,))
    page = client.get("/workspace/campaign/career/remove").text
    assert "Delete campaign" not in page and "Archive campaign" in page


def test_prior_enrollment_links_evidence_and_more_results_skip_existing_members(batch_workspace):
    config, app, client = batch_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        db.review_leads([lead], action="approve", email="sales@mills.example", confirmed=True)
        assert db.enroll("career", [lead]) == (1, 0)
        assert len(db.campaign_runs("career")) == 1
        assert db.enroll("career", [lead]) == (0, 1)
        assert len(db.store.emails_in_campaign("career")) == 1
    key = batch(client)
    saved_zero_result(config, key)
    client.post(f"/research/{key}/recover-discovery")
    page = client.get(f"/research/{key}").text
    assert 'value="career" selected' in page
    assert "Find more contacts" in page
    assert client.get("/campaigns/missing/research").status_code == 404
    assert client.get("/campaigns/career/research?source=missing").status_code == 404


def test_controls_visible_for_old_backend_and_missing_routes_guide_restart(batch_workspace):
    config, app, client = batch_workspace
    key = batch(client)
    page = client.get("/campaigns/career").text
    assert 'href="/campaigns/career/research"' in page
    assert "Edit campaign" in page and "Delete / archive" in page
    client.get("/campaigns/career").template.environment.globals["feedback_enabled"] = False
    page = client.get("/campaigns/career").text
    assert "Edit campaign" in page and 'href="/campaigns/career/settings"' in page
    assert "Find more contacts" in page and 'href="/research/new"' in page
    assert 'href="#app-update"' in page
    page = client.get(f"/research/{key}").text
    assert "Edit audience" in page and "Delete / archive" in page
    assert "Restart needed" in page


def test_batch_routes_require_authentication_and_same_origin(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = settings.model_copy(update={"app_password": "offline-only"})
    app = create_app(config)
    client = TestClient(app)
    assert (
        client.get("/campaigns/career/research", follow_redirects=False).headers["location"]
        == "/login"
    )
    client.post("/login", data={"password": "offline-only"})
    response = client.post(
        "/campaigns/career/research", data=complete(), headers={"Origin": "https://other.invalid"}
    )
    assert response.status_code == 403
