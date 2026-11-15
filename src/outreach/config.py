"""Settings, loaded from the environment and validated at startup.

The point of this module is *when* it fails: immediately, before any work
starts, rather than halfway through a campaign with fourteen emails sent.

But a command should only need the secrets it actually uses. Importing a
spreadsheet touches no mailbox and no model, so demanding an API key for it
would just be an obstacle. So settings load without complaint, and each command
declares what it needs by calling `require()` as its first act. The failure is
still immediate — it is just scoped to the job in hand.

Base settings come from the environment; the web app also applies encrypted
provider-key overrides saved through Settings without rewriting .env.
`.env` is git-ignored; `.env.example` documents what exists.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when settings are missing or invalid."""


class Settings(BaseSettings):
    """Everything the application needs to run. No field has a secret default."""

    model_config = SettingsConfigDict(
        env_prefix="OUTREACH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The model, and who serves it (D-007, D-012).
    # `llm_provider` picks which adapter the entry point builds:
    #   "openrouter" — many models behind one key
    #   "anthropic"  — Claude directly
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-5.6-luna"  # measured winner, D-013
    openrouter_api_key: str | None = Field(default=None, repr=False)

    # Direct Anthropic, kept because the adapter exists and still works.
    anthropic_api_key: str | None = Field(default=None, repr=False)
    anthropic_model: str = "claude-opus-5"

    # Mailbox (D-002) — needed only by commands that send or read mail.
    mail_smtp_host: str | None = None
    mail_smtp_port: int = 465
    mail_imap_host: str | None = None
    mail_imap_port: int = 993
    mail_username: str | None = None
    mail_password: str | None = Field(default=None, repr=False)

    # Sender identity (D-008). Company and physical address go in the footer
    # of every email — identifying the sender is a legal baseline, not a style.
    sender_name: str | None = None
    sender_email: EmailStr | None = None
    sender_company: str | None = None
    sender_address: str | None = None

    # Sending limits. The domain had never sent email before this project, so
    # the default is low; raise it once replies show mail is being delivered.
    daily_send_cap: int = 10
    send_gap_seconds: int = 60

    # Storage (D-006) — always needed, and always has a sensible default.
    db_path: str = "data/outreach.db"

    # Research and browser access. Production runs have their own durable budgets.
    parallel_api_key: str | None = Field(default=None, repr=False)
    research_model: str = "anthropic/claude-haiku-4.5"
    # Workbench picks a model per job and falls back to the next one if a model is refused.
    # Prices are OpenRouter list prices per million tokens (input/output), Nov 2026.
    # Measured live: Claude Haiku 5.5 ($0.10/$0.50 per million
    # tokens) does each research and drafting step for about $0.001 and answered every
    # time. DeepSeek V4.1 Flash ($0.05/$0.57) is nominally cheaper but in three of five
    # steps spent its whole allowance reasoning and returned nothing, which cost more
    # than Haiku's answer. It stays as a fallback, after Haiku 4.5.
    workbench_research_models: str = (
        "anthropic/claude-haiku-5.5,anthropic/claude-haiku-4.5,deepseek/deepseek-v4.1-flash"
    )
    # Writing is where quality shows. Claude Sonnet 5.5 ($2/$10) writes the email, about
    # $0.013 each; Haiku 5.5 takes over if Sonnet is refused or the run's limit is short.
    workbench_draft_models: str = (
        "anthropic/claude-sonnet-5.5,anthropic/claude-haiku-5.5,anthropic/claude-haiku-4.5"
    )
    research_max_budget_usd: float = Field(default=5.0, ge=0.1, le=100)
    research_daily_budget_usd: float = Field(default=5.0, ge=0.1, le=100)
    local_network_restricted: bool = False
    credential_key: str | None = Field(default=None, repr=False)
    app_password: str | None = Field(default=None, repr=False)
    allowed_hosts: str = "localhost,127.0.0.1,::1,testserver"
    oauth_public_url: str | None = None
    google_client_id: str | None = Field(default=None, repr=False)
    google_client_secret: str | None = Field(default=None, repr=False)
    zoho_client_id: str | None = Field(default=None, repr=False)
    zoho_client_secret: str | None = Field(default=None, repr=False)
    mail_account_id: str | None = None

    @property
    def send_requirements(self):
        if self.mail_account_id:
            return (
                "mail_account_id",
                "sender_name",
                "sender_email",
                "sender_company",
                "sender_address",
            )
        return self.SEND

    # Groups of settings, named so a command can ask for what it needs without
    # listing individual fields.
    MAIL: ClassVar[tuple[str, ...]] = (
        "mail_smtp_host",
        "mail_imap_host",
        "mail_username",
        "mail_password",
        "sender_name",
        "sender_email",
    )
    SEND: ClassVar[tuple[str, ...]] = (
        "mail_smtp_host",
        "mail_username",
        "mail_password",
        "sender_name",
        "sender_email",
        "sender_company",
        "sender_address",
    )
    LLM: ClassVar[tuple[str, ...]] = ("anthropic_api_key",)
    OPENROUTER: ClassVar[tuple[str, ...]] = ("openrouter_api_key",)

    def llm_credentials(self) -> tuple[str, ...]:
        """Which key this configuration actually needs."""
        return self.OPENROUTER if self.llm_provider == "openrouter" else self.LLM

    def require(self, *names: str) -> None:
        """Check the settings this command needs, before it does any work.

        Raises `ConfigError` naming exactly what is missing — including the
        environment variable to set, because "sender_email is required" is not
        much help at the point you are trying to fix it.
        """
        missing = [name for name in names if getattr(self, name, None) in (None, "")]
        if missing:
            variables = "\n".join(f"  OUTREACH_{name.upper()}" for name in sorted(missing))
            raise ConfigError(
                "This command needs settings that are not set. Add these to your "
                f".env file (see .env.example):\n\n{variables}\n"
            )


def load_settings(**overrides: object) -> Settings:
    """Load settings, or raise `ConfigError` if a value present is malformed.

    Absent values are fine here — `require()` is what checks a command's needs.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except Exception as exc:  # pydantic ValidationError, and anything else
        raise ConfigError(
            "Configuration is invalid or incomplete. Copy .env.example to .env "
            f"and fill in every value.\n\n{exc}"
        ) from exc
