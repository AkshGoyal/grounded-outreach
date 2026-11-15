"""Persistent hosted startup and guards; no external hosting or mail calls."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from outreach.adapters.credential_vault import CredentialVault
from outreach.campaigns import load_copy, save_texts
from outreach.config import ConfigError
from outreach.hosted import main, prepare_hosted
from outreach.web.app import create_app
from tests.test_platform import db_for


@pytest.fixture
def hosted_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTREACH_HOSTED_DATA_DIR", str(tmp_path / "persistent"))
    monkeypatch.setenv("OUTREACH_APP_PASSWORD", "fake-workspace-password-long")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://workspace.example.com")
    return tmp_path / "persistent"


def test_render_url_and_private_state_share_persistent_root(hosted_env):
    settings = prepare_hosted()
    assert Path.cwd() == hosted_env
    assert Path(settings.db_path).parent == hosted_env
    assert settings.oauth_public_url == "https://workspace.example.com"
    assert "workspace.example.com" in settings.allowed_hosts
    if os.name != "nt":
        assert hosted_env.stat().st_mode & 0o777 == 0o700


def test_restarts_keep_database_campaign_files_and_encryption_key(hosted_env):
    first = prepare_hosted()
    encrypted = CredentialVault(first).encrypt("fake-refresh-token")
    with db_for(first) as db:
        db.save_campaign("career", "Career", None, "job search", "", None)
    save_texts("career", copy="Supplied background.", closing="Candidate")
    second = prepare_hosted()
    assert CredentialVault(second).decrypt(encrypted) == "fake-refresh-token"
    assert load_copy("career") == "Supplied background."
    with db_for(second) as db:
        assert db.campaign("career")["name"] == "Career"


@pytest.mark.parametrize(
    "name,value",
    [
        ("OUTREACH_APP_PASSWORD", "short"),
        ("OUTREACH_HOSTED_DATA_DIR", "relative"),
        ("OUTREACH_DB_PATH", "/tmp/outside-persistent.db"),
        ("OUTREACH_DB_PATH", "relative.db"),
        ("OUTREACH_OAUTH_PUBLIC_URL", "http://unsafe.example.com"),
        ("OUTREACH_OAUTH_PUBLIC_URL", "https://unsafe.example.com/path"),
    ],
)
def test_hosted_startup_refuses_unsafe_configuration(hosted_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError):
        prepare_hosted()


def test_invalid_settings_do_not_echo_secret_values(hosted_env, monkeypatch):
    monkeypatch.setenv("OUTREACH_MAIL_SMTP_PORT", "fake-secret-accidentally-in-wrong-field")
    with pytest.raises(ConfigError) as exc:
        prepare_hosted()
    assert "fake-secret" not in str(exc.value)


def test_hosted_app_requires_login_and_keeps_paid_actions_explicit(hosted_env):
    client = TestClient(create_app(prepare_hosted()), base_url="https://workspace.example.com")
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/accounts", follow_redirects=False).headers["location"] == "/login"
    client.post("/login", data={"password": "fake-workspace-password-long"})
    assert client.get("/accounts/oauth").status_code == 200
    assert "Setup needed" in client.get("/accounts/oauth").text


def test_launcher_is_single_process_no_access_logs_and_no_polling(hosted_env, monkeypatch):
    import uvicorn

    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    main()
    assert captured["workers"] == 1 and captured["access_log"] is False
    assert captured["forwarded_allow_ips"] == "127.0.0.1"


def test_explicit_public_url_takes_precedence_over_render_url(hosted_env, monkeypatch):
    monkeypatch.setenv("OUTREACH_OAUTH_PUBLIC_URL", "https://custom.example.com")
    assert prepare_hosted().oauth_public_url == "https://custom.example.com"
