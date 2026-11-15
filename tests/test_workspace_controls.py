"""Removal and status are explicit, private and never trigger external operations."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from outreach.core.models import Contact
from outreach.web.app import create_app
from outreach.web.draft_jobs import DraftJob
from outreach.web.jobs import SendJob
from tests.test_audience_intake import complete
from tests.test_platform import db_for


@pytest.fixture
def workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(
        settings,
        research_api=lambda *args: pytest.fail("Must not use a provider"),
        mailbox=lambda *args: pytest.fail("Must not open a mailbox"),
    )
    client = TestClient(app)
    response = client.post("/research/intake", data=complete(), follow_redirects=False)
    key = response.headers["location"].split("?")[0].split("/")[-1]
    return settings, app, client, key


def test_delete_draft_requires_explicit_confirmation_and_removes_only_selected(workspace):
    config, app, client, key = workspace
    route = f"/workspace/audience/{key}/remove"
    response = client.get(route)
    assert "Delete audience" in response.text and "cannot be undone" in response.text
    assert client.post(route, data={"action": "delete"}).status_code == 409
    with db_for(config) as db:
        assert db.run(key)
        other = db.new_run(
            title="Keep",
            brief="Keep this draft.",
            purpose="other",
            tags="",
            project_id=None,
            target=1,
            budget=100000,
        )
    assert (
        "Unused draft deleted"
        in client.post(route, data={"action": "delete", "confirm_delete": "yes"}).text
    )
    with db_for(config) as db:
        assert not db.run(key) and db.run(other)
        assert not db.messages(key)
        assert not db.one("SELECT run_id FROM research_intakes WHERE run_id=?", (key,))


def test_archive_preserves_uncertain_spending_and_restore_never_restarts(workspace):
    config, app, client, key = workspace
    with db_for(config) as db:
        db.set_run(key, status="planning")
        db.reserve(key, "uncertain", "fingerprint", 100000, 5000000)
        db.set_run(key, status="failed")
        calls = db.rows("SELECT * FROM research_calls")
    route = f"/workspace/audience/{key}/remove"
    assert client.post(route, data={"action": "delete", "confirm_delete": "yes"}).status_code == 409
    assert "Archive audience" in client.get(route).text
    client.post(route, data={"action": "archive"})
    with db_for(config) as db:
        assert db.run(key)["archived"] and db.run(key)["spent_micro"] == 100000
        assert not db.runs() and len(db.runs(include_archived=True)) == 1
        assert db.rows("SELECT * FROM research_calls") == calls
    assert "Restore / delete" in client.get("/research?view=archived").text
    for action in ("refine", "approve", "resume"):
        assert "Restore this audience" in client.post(f"/research/{key}/{action}").text
    assert not app.state.research.start(key)
    client.post(route, data={"action": "restore"})
    with db_for(config) as db:
        assert not db.run(key)["archived"] and db.run(key)["status"] == "failed"
        assert db.rows("SELECT * FROM research_calls") == calls


def test_confirmation_is_rechecked_when_new_history_appears(workspace):
    config, app, client, key = workspace
    route = f"/workspace/audience/{key}/remove"
    assert "Delete audience" in client.get(route).text
    with db_for(config) as db:
        db.set_run(key, status="planning")
        db.reserve(key, "new-history", "fingerprint", 1000, 5000000)
        db.set_run(key, status="failed")
    assert client.post(route, data={"action": "delete", "confirm_delete": "yes"}).status_code == 409
    with db_for(config) as db:
        assert db.run(key) and db.call(key, "new-history")


def test_active_work_cannot_be_removed(workspace):
    config, app, client, key = workspace
    app.state.research.active.add(key)
    route = f"/workspace/audience/{key}/remove"
    assert "still running" in client.get(route).text
    assert client.post(route, data={"action": "archive"}).status_code == 409
    app.state.research.active.clear()


def test_empty_campaign_delete_and_saved_campaign_archive(workspace):
    config, app, client, key = workspace
    with db_for(config) as db:
        db.save_campaign("empty", "Empty", None, "sales", "", None)
        db.save_campaign("saved", "Saved", None, "sales", "", None)
        db.store.add_contact(Contact(campaign_id="saved", email="fictional@example.com"))
    route = "/workspace/campaign/empty/remove"
    settings_page = client.get("/campaigns/empty/settings").text
    assert "<title>Campaign settings · Outreach</title>" in settings_page
    assert settings_page.count("Tidy this campaign") == 1
    assert "Delete campaign" in client.get(route).text
    client.post(route, data={"action": "delete", "confirm_delete": "yes"})
    with db_for(config) as db:
        assert not db.campaign("empty") and db.campaign("saved")
    route = "/workspace/campaign/saved/remove"
    assert client.post(route, data={"action": "delete", "confirm_delete": "yes"}).status_code == 409
    client.post(route, data={"action": "archive"})
    assert 'href="/campaigns/saved"' not in client.get("/campaigns").text
    assert 'href="/campaigns/saved"' in client.get("/campaigns?status=archived").text
    client.post(route, data={"action": "restore"})
    with db_for(config) as db:
        assert db.campaign("saved")["status"] == "paused"
        assert db.one("SELECT id FROM contacts WHERE campaign_id='saved'")


def test_private_progress_snapshots_report_actual_counts_without_provider_calls(workspace):
    config, app, client, key = workspace
    with db_for(config) as db:
        db.set_run(key, status="running", progress="Checking evidence for a fictional company.")
    app.state.research.active.add(key)
    app.state.drafter.job = DraftJob("fictional", total=3, completed=1, failed=1)
    app.state.sender.job = SendJob("fictional", total=3, outcomes=[SimpleNamespace(sent=True)])
    response = client.get("/workspace/activity")
    assert response.headers["cache-control"] == "no-store"
    snapshot = response.json()
    assert {j["kind"] for j in snapshot["jobs"]} == {"research", "drafting", "sending"}
    assert snapshot["recent"]["drafting"]["completed"] == 1
    assert snapshot["recent"]["sending"]["sent"] == 1
    response = client.get(f"/research/{key}/status")
    assert response.json()["active"] and response.json()["companies"] == 0
    assert response.json()["spent"] == 0
    with db_for(config) as db:
        assert not db.rows("SELECT * FROM research_calls")
    app.state.research.active.clear()
    app.state.drafter.job.finished = app.state.sender.job.finished = True
    assert not client.get("/workspace/activity").json()["jobs"]


def test_remove_and_activity_require_authentication_and_same_origin(settings):
    config = settings.model_copy(update={"app_password": "fictional"})
    client = TestClient(create_app(config))
    assert client.get("/workspace/activity", follow_redirects=False).status_code == 303
    assert (
        client.post("/workspace/audience/no-such-item/remove", follow_redirects=False).status_code
        == 303
    )
    client.post("/login", data={"password": "fictional"})
    assert (
        client.post(
            "/workspace/audience/no-such-item/remove",
            headers={"Origin": "https://elsewhere.invalid"},
        ).status_code
        == 403
    )
    assert client.get("/workspace/audience/no-such-item/remove").status_code == 404
