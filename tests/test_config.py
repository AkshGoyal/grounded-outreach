"""Settings must fail before a command does any work — and must ask only for
what that command actually needs."""

import pytest

from outreach.config import ConfigError, Settings, load_settings


def test_settings_load_without_any_secrets():
    """Importing a spreadsheet needs no API key. Demanding one would just be an
    obstacle between you and trying the tool."""
    settings = load_settings(_env_file=None)
    assert settings.db_path == "data/outreach.db"
    assert settings.anthropic_api_key is None


def test_require_raises_for_what_is_missing():
    settings = load_settings(_env_file=None)
    with pytest.raises(ConfigError) as exc:
        settings.require(*Settings.MAIL)

    message = str(exc.value)
    # It must name the environment variables, not the Python field names.
    assert "OUTREACH_MAIL_SMTP_HOST" in message
    assert "OUTREACH_SENDER_EMAIL" in message
    assert ".env.example" in message


def test_require_passes_when_everything_is_present(settings: Settings):
    settings.require(*Settings.MAIL, *Settings.LLM, "db_path")


def test_require_treats_a_blank_value_as_missing(monkeypatch):
    """An empty string is a missing value wearing a disguise."""
    monkeypatch.setenv("OUTREACH_ANTHROPIC_API_KEY", "")
    settings = load_settings(_env_file=None)
    with pytest.raises(ConfigError, match="OUTREACH_ANTHROPIC_API_KEY"):
        settings.require(*Settings.LLM)


def test_db_path_never_needs_configuring(monkeypatch):
    monkeypatch.delenv("OUTREACH_DB_PATH", raising=False)
    load_settings(_env_file=None).require("db_path")


def test_a_malformed_value_still_fails_at_load_time():
    """Absent is fine. Present-but-wrong is not."""
    with pytest.raises(ConfigError):
        load_settings(_env_file=None, sender_email="not-an-email")


def test_the_model_is_configuration_not_a_constant(settings: Settings):
    assert settings.anthropic_model == "claude-opus-5"
