"""`outreach check` is the first thing anyone runs. It must be honest about
what is missing, and must not pretend to succeed."""

import pytest

from outreach.cli import main


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in list(__import__("os").environ):
        if name.startswith("OUTREACH_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.chdir(tmp_path)  # so no real .env is picked up
    return tmp_path


def test_it_fails_and_names_what_is_missing(clean_env, capsys):
    assert main(["check", "--no-live"]) == 1
    out = capsys.readouterr().out
    assert "OUTREACH_OPENROUTER_API_KEY" in out
    assert "missing" in out


def test_it_passes_once_everything_is_set(clean_env, monkeypatch, capsys):
    for name, value in {
        "OPENROUTER_API_KEY": "sk-or-test",
        "SENDER_NAME": "Aksh Goyal",
        "SENDER_EMAIL": "aksh@example.com",
        "SENDER_COMPANY": "Star Threads Private Limited",
        "SENDER_ADDRESS": "Ludhiana, Punjab",
        "MAIL_SMTP_HOST": "smtp.example.com",
        "MAIL_USERNAME": "aksh@example.com",
        "MAIL_PASSWORD": "app-password",
    }.items():
        monkeypatch.setenv(f"OUTREACH_{name}", value)
    assert main(["check", "--no-live"]) == 0
    assert "Settings look complete" in capsys.readouterr().out


def test_it_shows_which_model_will_be_used(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("OUTREACH_LLM_MODEL", "openai/gpt-5.6-luna")
    main(["check", "--no-live"])
    assert "openai/gpt-5.6-luna" in capsys.readouterr().out


def test_sending_needs_a_physical_address(clean_env, monkeypatch, capsys):
    """Identifying the sender with a physical address is a legal baseline for
    outreach. It must be impossible to reach the send step without one."""
    monkeypatch.setenv("OUTREACH_OPENROUTER_API_KEY", "sk-or-test")
    assert main(["check", "--no-live"]) == 1
    assert "OUTREACH_SENDER_ADDRESS" in capsys.readouterr().out
