"""Free onboarding, private key entry and recovery never trigger paid work."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.provider_credentials import ProviderCredentials
from outreach.adapters.research_api import ResearchAPI
from outreach.core.research import ResearchStop
from outreach.web.app import create_app
from tests.test_audience_intake import complete
from tests.test_platform import PLAN, db_for


def test_browser_key_entry_is_encrypted_survives_restart_and_preserves_env(
    settings, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    env = Path(".env")
    original = b"# existing owner config\nOUTREACH_OPENROUTER_API_KEY=old-owner-value\n"
    env.write_bytes(original)
    config = settings.model_copy(update={"openrouter_api_key": "earlier-key"})
    client = TestClient(create_app(config))
    response = client.post(
        "/setup/providers", data={"parallel_api_key": "fake-parallel-private-key"}
    )
    assert response.status_code == 200
    assert "Keys saved privately" in response.text
    assert "fake-parallel-private-key" not in response.text
    assert config.openrouter_api_key == "earlier-key"
    assert config.parallel_api_key == "fake-parallel-private-key"
    encrypted = Path(config.db_path).parent / "provider-credentials.enc"
    assert b"fake-parallel-private-key" not in encrypted.read_bytes()
    assert env.read_bytes() == original
    restarted = settings.model_copy(update={"parallel_api_key": None})
    page = TestClient(create_app(restarted)).get("/setup")
    assert page.status_code == 200 and restarted.parallel_api_key == "fake-parallel-private-key"
    response = client.post("/setup/providers", data={"openrouter_api_key": "x" * 501})
    assert "x" * 501 not in response.text
    assert "between 1 and 500" in response.text
    assert env.read_bytes() == original


def test_key_updates_require_login_and_same_origin(settings):
    config = settings.model_copy(update={"app_password": "fictional-workspace-password"})
    client = TestClient(create_app(config))
    location = Path(config.db_path).parent / "provider-credentials.enc"
    response = client.post(
        "/setup/providers", data={"parallel_api_key": "fictional"}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert not location.exists()
    client.post("/login", data={"password": config.app_password})
    response = client.post(
        "/setup/providers",
        data={"parallel_api_key": "fictional"},
        headers={"Origin": "https://elsewhere.invalid"},
    )
    assert response.status_code == 403 and not location.exists()


def test_saved_key_damage_reports_no_secret_and_does_not_rewrite_env(settings):
    provider = ProviderCredentials(settings)
    provider.save({"parallel_api_key": "fictional-key"})
    provider.path.write_text("not-a-valid-ciphertext")
    with pytest.raises(Exception, match="Saved research keys could not be opened"):
        provider.apply()


def test_restricted_session_saves_audience_but_never_reserves_or_calls(settings):
    config = settings.model_copy(
        update={
            "local_network_restricted": True,
            "parallel_api_key": "fake",
            "openrouter_api_key": "fake",
        }
    )
    calls = []
    app = create_app(config, research_api=lambda *args: calls.append(args))
    client = TestClient(app)
    response = client.post(
        "/research/intake",
        data=complete() | {"action": "plan", "planning_confirm": "on"},
        follow_redirects=False,
    )
    key = response.headers["location"].split("?")[0].split("/")[-1]
    assert "START-OUTREACH.cmd" in client.get(response.headers["location"]).text
    with db_for(config) as db:
        assert db.run(key)["status"] == "draft"
        assert db.run(key)["spent_micro"] == 0
        assert db.rows("SELECT * FROM research_calls") == []
        db.set_run(key, status="awaiting_approval", plan_json=__import__("json").dumps(PLAN))
    for route in ["approve", "refine", "resume"]:
        client.post(
            f"/research/{key}/{route}", data={"instruction": "Change scope", "confirm": "on"}
        )
    with db_for(config) as db:
        assert not db.run(key)["approved_at"]
        assert db.run(key)["status"] == "awaiting_approval"
    assert not calls


def test_adapter_restriction_blocks_before_reservation(settings):
    config = settings.model_copy(update={"local_network_restricted": True})
    with db_for(config) as db:
        key = db.new_run(
            title="Fake",
            brief=complete()["brief"],
            purpose="sales",
            tags="",
            project_id=None,
            target=2,
            budget=100000,
        )
        api = ResearchAPI(
            config,
            db,
            key,
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: pytest.fail("Network must not be used")
                )
            ),
        )
        with pytest.raises(ResearchStop, match="No new spending was reserved"):
            api.paid("blocked", "parallel", "/v1/search", {}, 1000)
        api.close()
        assert db.rows("SELECT * FROM research_calls") == []


def test_copy_preserves_uncertain_attempt_and_needs_fresh_payment_approval(settings):
    app = create_app(settings)
    client = TestClient(app)
    response = client.post("/research/intake", data=complete(), follow_redirects=False)
    key = response.headers["location"].split("?")[0].split("/")[-1]
    with db_for(settings) as db:
        db.set_run(key, status="planning")
        db.reserve(key, "uncertain", "fingerprint", 1000, 5000000)
        db.set_run(key, status="failed", error="Provider connection failed.")
        original = db.run(key)
    response = client.post(f"/research/{key}/copy", follow_redirects=False)
    copied = response.headers["location"].split("?")[0].split("/")[-1]
    with db_for(settings) as db:
        assert copied != key and db.run(key) == original
        new = db.run(copied)
        assert new["intake"] == original["intake"]
        assert new["spent_micro"] == 0 and new["status"] == "draft"
        assert not new["approved_at"] and not new["plan"]
        assert len(db.rows("SELECT * FROM research_calls")) == 1


def test_graceful_restart_is_authenticated_and_refuses_active_work(settings):
    config = settings.model_copy(
        update={"local_network_restricted": True, "app_password": "fake-private-password"}
    )
    stopped = []
    app = create_app(config, local_shutdown=lambda: stopped.append(True))
    client = TestClient(app)
    assert client.post("/setup/restart-local", follow_redirects=False).status_code == 303
    assert not stopped
    client.post("/login", data={"password": config.app_password})
    app.state.research.active.add("fictional-active-worker")
    assert client.post("/setup/restart-local").status_code == 409
    assert not stopped
    app.state.research.active.clear()
    assert client.post("/setup/restart-local").status_code == 200
    assert stopped == [True]


def test_audience_error_names_field_and_keeps_entered_values(settings):
    client = TestClient(create_app(settings))
    response = client.post("/research/intake", data=complete() | {"brief": "too short"})
    assert response.status_code == 400
    assert "Goal: use 20–6,500 characters." in response.text
    assert "AI product startups" in response.text and "too short" in response.text
    assert 'data-server-values="true"' in response.text


def test_restricted_mail_verification_preserves_saved_account_without_network(settings):
    config = settings.model_copy(update={"local_network_restricted": True})
    app = create_app(config, mailbox=lambda value: pytest.fail("Mailbox must not be opened"))
    client = TestClient(app)
    response = client.post(
        "/accounts",
        data={
            "email": "fictional@gmail.com",
            "provider": "gmail",
            "label": "Test account",
            "sender_name": "Test Sender",
            "company": "Test Company",
            "address": "123 Fictional Street",
            "password": "fictional-password",
        },
    )
    assert "Restart using RESTART-OUTREACH.cmd" in response.text
    with db_for(config) as db:
        account = db.accounts()[0]
        assert not account["verified_at"]
        before = db.account(account["id"], secret=True)
    assert (
        "No network check or email was sent"
        in client.post(f"/accounts/{account['id']}/verify").text
    )
    with db_for(config) as db:
        assert db.account(account["id"], secret=True) == before
