"""Hosted launcher: env-only settings, password, HTTPS origin, persistent dir, one worker.

Nothing here deploys or calls a provider; uvicorn and the app factory are captured.
"""

import pytest
from fastapi.testclient import TestClient

from outreach import workbench
from outreach.wiring import build_workbench_app

PASSWORD = "fictional-evaluator-pass"


def launch(monkeypatch, tmp_path, *args, env=None):
    for name in ("WORKBENCH_APP_PASSWORD", "WORKBENCH_PUBLIC_URL", "RENDER_EXTERNAL_URL", "WORKBENCH_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    base = {
        "WORKBENCH_APP_PASSWORD": PASSWORD,
        "RENDER_EXTERNAL_URL": "https://workbench-demo.example.com",
        "WORKBENCH_DATA_DIR": str(tmp_path / "disk"),
        "PORT": "10000",
    }
    for name, value in (base | (env or {})).items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["workbench", "--hosted", *args])
    captured = {}

    def factory(settings, **kwargs):
        captured["settings"] = settings
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(workbench, "build_workbench_app", factory)
    monkeypatch.setattr(workbench.uvicorn, "run", lambda app, **kw: captured.update(kw))
    workbench.main()
    return captured


def test_hosted_fixture_binds_publicly_behind_password_and_one_host(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OUTREACH_OPENROUTER_API_KEY=fictional-do-not-read\n")
    monkeypatch.chdir(tmp_path)
    captured = launch(monkeypatch, tmp_path)
    settings = captured["settings"]
    assert captured["host"] == "0.0.0.0" and captured["port"] == 10000
    assert captured["workers"] == 1 and captured["proxy_headers"] is True
    assert settings.app_password == PASSWORD
    assert settings.allowed_hosts == "workbench-demo.example.com"
    assert settings.db_path == str(tmp_path / "disk" / "workbench.db")
    assert settings.openrouter_api_key is None and captured["mode"] == "fixture"


@pytest.mark.parametrize(
    "env",
    [
        {"WORKBENCH_APP_PASSWORD": None},
        {"WORKBENCH_APP_PASSWORD": "short"},
        {"RENDER_EXTERNAL_URL": "http://workbench-demo.example.com"},
        {"RENDER_EXTERNAL_URL": "https://user:pw@workbench-demo.example.com"},
        {"RENDER_EXTERNAL_URL": None},
        {"WORKBENCH_DATA_DIR": "relative/dir"},
        {"PORT": "not-a-port"},
    ],
)
def test_hosted_refuses_unsafe_settings_without_echoing_secrets(monkeypatch, tmp_path, capsys, env):
    with pytest.raises(SystemExit):
        launch(monkeypatch, tmp_path, env=env)
    assert PASSWORD not in capsys.readouterr().err


def test_hosted_live_reads_keys_from_environment_only(monkeypatch, tmp_path):
    keys = tmp_path / "fake.env"
    keys.write_text("OUTREACH_PARALLEL_API_KEY=file\nOUTREACH_OPENROUTER_API_KEY=file\n")
    env = {"OUTREACH_PARALLEL_API_KEY": "env-fictional", "OUTREACH_OPENROUTER_API_KEY": "env-x"}
    captured = launch(
        monkeypatch, tmp_path, "--mode", "live", "--credential-file", str(keys), env=env
    )
    assert captured["settings"].parallel_api_key == "env-fictional"
    assert captured["mode"] == "live" and captured["limits"]["budget_micro"] == 50000


def test_hosted_live_without_keys_does_not_start(monkeypatch, tmp_path):
    env = {"OUTREACH_PARALLEL_API_KEY": None, "OUTREACH_OPENROUTER_API_KEY": None}
    with pytest.raises(SystemExit):
        launch(monkeypatch, tmp_path, "--mode", "live", env=env)


def test_password_gate_and_host_check_protect_the_hosted_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from outreach.config import Settings

    settings = Settings(
        _env_file=None,
        _env_prefix="WORKBENCH_",
        db_path=str(tmp_path / "workbench.db"),
        app_password=PASSWORD,
        allowed_hosts="testserver",
    )
    with TestClient(build_workbench_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        gated = client.get("/research/new", follow_redirects=False)
        assert gated.status_code == 303 and gated.headers["location"] == "/login"
        assert client.post("/research", data={}, follow_redirects=False).status_code == 303
        assert client.get("/runs/x/export", follow_redirects=False).status_code == 303
        login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert login.status_code == 303
        assert client.get("/research/new").status_code == 200
    with TestClient(build_workbench_app(settings), base_url="http://evil.example") as other:
        assert other.get("/health").status_code == 400
