"""Workbench route, persistence and runtime isolation tests with disposable fixture data."""

import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from outreach.adapters.workbench_fixture import FixtureResearchProvider
from outreach.config import ConfigError, Settings
from outreach.wiring import build_workbench_app


@pytest.fixture
def workbench_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Settings(_env_file=None, db_path=str(tmp_path / "workbench.db"))


def payload(**changes):
    return {
        "name": "Maya Rao",
        "company": "Cedar Works",
        "role": "Finance Director",
        "email": "",
        "request_id": str(uuid4()),
        **changes,
    }


def settled(client, path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(path + "/status")
        assert response.status_code == 200
        run = response.json()
        if run["execution_status"] not in ("queued", "running"):
            return run
        time.sleep(0.01)
    pytest.fail("Fixture worker did not settle within five real seconds")


def start(client, data=None):
    response = client.post("/research", data=data or payload(), follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def test_no_email_prospect_reaches_saved_research_and_history(workbench_settings):
    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client:
        assert client.get("/research/new").status_code == 200
        path = start(client)
        run = settled(client, path)
        assert run["prospect"]["name"] == "Maya Rao"
        assert not run["prospect"]["email"]
        assert run["execution_status"] == "completed"
        assert run["business_outcome"] == "ready_for_review"
        assert run["mode"] == "fixture"
        assert run["result"]["sources"] and run["result"]["hook"]
        assert run["campaign"]["id"] == "invoice-review-demo"
        assert run["campaign"]["version"] == 2
        assert any(s["status"] == "started" for s in run["stages"])
        assert any(s["status"] == "completed" for s in run["stages"])
        page = client.get(path)
        assert "Maya Rao" in page.text and "Fixture" in page.text
        assert path in client.get("/history").text
        assert client.get(path + "/status").json() == run
        with app.state.open_workbench_store() as db:
            for table in ("contacts", "mail_accounts", "research_calls", "messages"):
                assert db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0


def test_completed_run_survives_app_restart_without_new_research(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client)
        original = settled(client, path)
    with TestClient(build_workbench_app(workbench_settings)) as client:
        assert client.get(path + "/status").json() == original
        assert path in client.get("/history").text


def test_immutable_snapshots_and_completed_run_cannot_be_replaced(workbench_settings):
    import sqlite3

    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client:
        path = start(client)
        run = settled(client, path)
        with app.state.open_workbench_store() as db:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.conn.execute(
                    "UPDATE workbench_runs SET prospect_json='{}' WHERE run_id=?", (run["id"],)
                )
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.conn.execute("UPDATE workbench_campaign_versions SET snapshot_json='{}'")
            assert not db.claim_workbench_run(run["id"])
            with pytest.raises(ValueError, match="no longer active"):
                db.finish_workbench_run(run["id"], {"outcome": "needs_more_evidence"})
        assert client.get(path + "/status").json() == run


def test_concurrent_duplicate_posts_create_one_run(workbench_settings):
    from concurrent.futures import ThreadPoolExecutor

    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=3) as workers:
        data = payload()
        paths = list(workers.map(lambda _: start(client, data), range(3)))
        assert len(set(paths)) == 1
        assert settled(client, paths[0])["business_outcome"] == "ready_for_review"
        with app.state.open_workbench_store() as db:
            assert len(db.list_workbench_runs()) == 1


def test_company_domain_and_unknown_role_need_no_email(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client, payload(company="cedar-works.example", role=""))
        assert settled(client, path)["business_outcome"] == "ready_for_review"


def test_conflicting_company_requires_confirmation_and_no_hook(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client, payload(company="Another Company"))
        run = settled(client, path)
        assert run["business_outcome"] == "needs_identity_confirmation"
        assert run["result"]["identity"]["status"] == "conflict"
        assert not run["result"]["hook"]


def test_repeated_submission_returns_same_run_and_changed_input_conflicts(workbench_settings):
    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client:
        data = payload()
        path = start(client, data)
        settled(client, path)
        assert start(client, data) == path
        changed = client.post("/research", data={**data, "name": "Different Person"})
        assert changed.status_code == 409
        assert 'value="Different Person"' in changed.text
        with app.state.open_workbench_store() as db:
            assert len(db.list_workbench_runs()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"company": ""},
        {"website": "javascript:alert(1)"},
        {"profile_url": "http://127.0.0.1/profile"},
        {"request_id": "invalid"},
    ],
)
def test_invalid_input_preserved_and_no_run_created(workbench_settings, changes):
    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client:
        response = client.post("/research", data=payload(**changes))
        assert response.status_code == 422
        assert "Cedar Works" in response.text or changes.get("company") == ""
        with app.state.open_workbench_store() as db:
            assert db.list_workbench_runs() == []


def test_unknown_prospect_does_not_inherit_fictional_evidence(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        path = start(client, payload(name="Different Person", company="Another Company"))
        run = settled(client, path)
        assert run["execution_status"] == "completed"
        # No fictional evidence is borrowed: the email uses only what was typed.
        assert not run["result"]["sources"]
        assert run["result"]["hook"]["basis"] == "as_entered"
        assert run["business_outcome"] == "ready_for_review"
        assert "Different Person" in client.get(path).text


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/accounts"),
        ("POST", "/accounts"),
        ("POST", "/accounts/fake/verify"),
        ("GET", "/accounts/oauth"),
        ("GET", "/accounts/oauth/gmail/start"),
        ("GET", "/accounts/oauth/gmail/callback"),
        ("GET", "/campaigns/fake/send"),
        ("POST", "/campaigns/fake/send"),
        ("POST", "/campaigns/fake/approve-all"),
        ("POST", "/drafts/1/test-send"),
        ("POST", "/setup/mail"),
        ("GET", "/inbox"),
        ("POST", "/inbox/check"),
        ("POST", "/replies/1/send"),
        ("POST", "/sending/stop"),
        ("GET", "/setup"),
        ("POST", "/setup/providers"),
    ],
)
def test_legacy_mail_and_account_routes_absent(workbench_settings, method, path):
    settings = workbench_settings.model_copy(
        update={
            "app_password": "fictional-password",
            "mail_smtp_host": "smtp.example.invalid",
            "mail_username": "fake@example.com",
            "mail_password": "fictional-secret",
        }
    )
    app = build_workbench_app(settings)
    assert not hasattr(app.state, "sender") and not hasattr(app.state, "inbox")
    with TestClient(app) as client:
        assert client.post("/login", data={"password": "fictional-password"}).status_code == 200
        assert client.request(method, path).status_code == 404


def test_cross_origin_start_rejected_and_missing_run_is_404(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        assert client.get("/runs/missing").status_code == 404
        assert client.get("/runs/missing/status").status_code == 404
        assert (
            client.post(
                "/research", data=payload(), headers={"origin": "https://other.example"}
            ).status_code
            == 403
        )


def test_unmarked_existing_database_refused_without_opening_it(workbench_settings):
    from pathlib import Path

    path = Path(workbench_settings.db_path)
    path.write_bytes(b"Do not read or modify this existing file")
    original = path.read_bytes()
    with pytest.raises(ConfigError, match="not marked for Workbench"):
        build_workbench_app(workbench_settings)
    assert path.read_bytes() == original


def test_queued_work_becomes_interrupted_on_restart_without_replay(workbench_settings):
    app = build_workbench_app(workbench_settings)
    with app.state.open_workbench_store() as db:
        data = payload()
        request_id = data.pop("request_id")
        key, _ = db.submit(data, request_id, db.get_campaign_brief())
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = client.get(f"/runs/{key}/status").json()
        assert run["execution_status"] == "interrupted"
        assert run["business_outcome"] != "research_ready"
        assert not run["result"].get("sources")


def test_running_status_and_duplicate_guard_during_provider_work(workbench_settings):
    entered, release = threading.Event(), threading.Event()

    class SlowFixture(FixtureResearchProvider):
        def research(self, prospect):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Fixture test release was not signalled")
            return super().research(prospect)

    app = build_workbench_app(workbench_settings, provider=SlowFixture())
    with TestClient(app) as client:
        try:
            data = payload()
            path = start(client, data)
            assert entered.wait(3)
            running = client.get(path + "/status").json()
            assert running["execution_status"] == "running"
            assert running["stages"]
            assert start(client, data) == path
            assert not app.state.workbench_runner.start(running["id"])
        finally:
            release.set()
        assert settled(client, path)["business_outcome"] == "ready_for_review"


def test_provider_failure_is_saved_and_not_false_completion(workbench_settings):
    class BrokenFixture:
        def research(self, prospect):
            raise RuntimeError("private provider details must not be rendered")

    with TestClient(build_workbench_app(workbench_settings, provider=BrokenFixture())) as client:
        path = start(client)
        run = settled(client, path)
        assert run["execution_status"] == "failed"
        assert run["business_outcome"] != "research_ready"
        assert "private provider details" not in client.get(path).text


def test_fixture_launcher_ignores_original_env_and_has_one_worker(tmp_path, monkeypatch):
    from outreach import workbench

    monkeypatch.setenv("OUTREACH_OPENROUTER_API_KEY", "fictional-do-not-use")
    monkeypatch.setenv("OUTREACH_DB_PATH", "owner.db")
    monkeypatch.setattr("sys.argv", ["workbench", "--data-dir", str(tmp_path), "--port", "8781"])
    captured = {}

    def capture_app(settings, **kwargs):
        captured["settings"] = settings
        captured.update(kwargs)
        return settings

    monkeypatch.setattr(workbench, "build_workbench_app", capture_app)
    monkeypatch.setattr(workbench.uvicorn, "run", lambda app, **kw: captured.update(kw))
    workbench.main()
    assert captured["settings"].openrouter_api_key is None
    assert captured["settings"].db_path == str(tmp_path / "workbench.db")
    assert captured["workers"] == 1 and captured["host"] == "127.0.0.1"


def test_prospect_email_is_not_collected(workbench_settings):
    with TestClient(build_workbench_app(workbench_settings)) as client:
        assert 'name="email"' not in client.get("/research/new").text
        path = start(client, payload(email="someone@cedar-works.example"))
        assert settled(client, path)["prospect"]["email"] == ""
