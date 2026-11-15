"""Choosing which concrete adapter to build. Shared by both entry points.

Like `cli.py` and `web/app.py`, this is a composition root: one of the few
files allowed to name a specific adapter (see tests/test_architecture.py).
"""

from __future__ import annotations

from outreach.config import Settings


def build_llm(settings: Settings, model: str | None = None):
    """The model adapter this configuration asks for."""
    if model:
        settings = settings.model_copy(update={"llm_model": model})
    if settings.llm_provider == "openrouter":
        from outreach.adapters.llm_openrouter import OpenRouterLLM

        return OpenRouterLLM(settings)
    from outreach.adapters.llm_anthropic import AnthropicLLM

    return AnthropicLLM(settings)


def account_settings(settings, account_id, *, require_verified=False, unlock=True):
    from outreach.adapters.credential_vault import CredentialVault
    from outreach.adapters.db import connect
    from outreach.adapters.platform_store import PlatformStore
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.config import ConfigError

    if not account_id:
        return settings
    with PlatformStore(SqliteStore(connect(settings.db_path))) as db:
        account = db.account(account_id, secret=unlock)
    if not account:
        raise ConfigError("Sending account not found.")
    if require_verified and not account["verified_at"]:
        raise ConfigError("Verify this sending account before sending or checking its inbox.")
    return settings.model_copy(
        update={
            "mail_account_id": account_id if account.get("oauth_provider") else None,
            "sender_email": account["email"],
            "sender_name": account["sender_name"],
            "sender_company": account["company"],
            "sender_address": account["address"],
            "mail_smtp_host": account["smtp_host"],
            "mail_smtp_port": account["smtp_port"],
            "mail_imap_host": account["imap_host"],
            "mail_imap_port": account["imap_port"],
            "mail_username": account["username"],
            "mail_password": CredentialVault(settings).decrypt(account["password_cipher"])
            if unlock and not account.get("oauth_provider")
            else None,
        }
    )


def campaign_settings(settings, campaign_id, *, require_verified=False, unlock=True):
    from outreach.adapters.db import connect
    from outreach.adapters.platform_store import PlatformStore
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.config import ConfigError

    with PlatformStore(SqliteStore(connect(settings.db_path))) as db:
        campaign = db.campaign(campaign_id)
    if campaign and require_verified and campaign["status"] in ("paused", "archived", "completed"):
        raise ConfigError("Reopen or resume the campaign before sending.")
    if campaign and campaign["workspace_campaign_id"] and require_verified:
        from outreach.campaigns import load_copy

        if not load_copy(campaign_id):
            raise ConfigError("Complete the campaign message brief before sending.")
    if campaign and campaign["workspace_campaign_id"] and not campaign["sender_account_id"]:
        if require_verified:
            raise ConfigError("Choose and verify this campaign's sending account before sending.")
        brief = campaign["message_brief"] or {}
        return settings.model_copy(
            update={
                "mail_account_id": None,
                "sender_name": brief.get("sender_name") or None,
                "sender_email": None,
                "sender_company": None,
                "sender_address": None,
                "mail_smtp_host": None,
                "mail_imap_host": None,
                "mail_username": None,
                "mail_password": None,
            }
        )
    return account_settings(
        settings,
        campaign["sender_account_id"] if campaign else None,
        require_verified=require_verified,
        unlock=unlock,
    )


def build_mailbox(settings):
    if settings.mail_account_id:
        from outreach.adapters.oauth_mail import OAuthMail

        return OAuthMail(settings).mailbox(settings)
    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox

    return SmtpImapMailbox(settings)


def build_workbench_app(
    settings,
    *,
    provider=None,
    mode="fixture",
    limits=None,
    research_client_factory=None,
    source_policy=None,
    writer=None,
    daily_budget_usd=None,
):
    """Compose a Workbench-only runtime without legacy app, accounts or mail workers."""
    from pathlib import Path

    from outreach.adapters.db import connect
    from outreach.adapters.workbench_fixture import (
        SCENARIOS,
        FixtureDraftWriter,
        FixtureResearchProvider,
    )
    from outreach.adapters.workbench_store import DEFAULT_LIMITS, WorkbenchStore
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.config import ConfigError
    from outreach.web.workbench import create_workbench_app

    if mode not in ("fixture", "live"):
        raise ConfigError("Choose fixture or live Workbench research.")
    limits = DEFAULT_LIMITS | (limits or {})

    path = Path(settings.db_path).resolve()
    marker = path.with_suffix(path.suffix + ".workbench")
    if path.exists() and not marker.is_file():
        raise ConfigError("Choose a new Workbench data directory; this database is not marked for Workbench.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open("x") as handle:
            handle.write("Outreach Workbench dedicated database\n")

    def open_store():
        return WorkbenchStore(SqliteStore(connect(path)))

    with open_store():
        pass

    def live_provider(store, key):
        from outreach.adapters.workbench_research import ParallelProspectProvider
        from outreach.adapters.research_api import ResearchAPI

        # The day cap is its own small, explicit limit (default: the run budget); no
        # transport is built until a worker starts.
        day_cap = daily_budget_usd if daily_budget_usd is not None else limits["budget_micro"] / 1e6
        bounded = settings.model_copy(
            update={
                "research_daily_budget_usd": min(settings.research_daily_budget_usd, day_cap),
            }
        )
        client = research_client_factory() if research_client_factory else None
        return ParallelProspectProvider(
            ResearchAPI(bounded, store, key, client=client), policy=source_policy
        )

    def live_writer(research_provider, attempt=1):
        from outreach.adapters.workbench_draft import ModelDraftWriter

        return ModelDraftWriter(research_provider, attempt)

    live_factory = mode == "live" and provider is None
    return create_workbench_app(
        settings,
        open_store,
        provider
        if provider is not None
        else (FixtureResearchProvider() if mode == "fixture" else None),
        mode=mode,
        limits=limits,
        provider_factory=live_provider if live_factory else None,
        # Fixture runs draft with the labelled fixture writer; live runs use the configured
        # draft model under the same run budget. An injected writer replaces either.
        writer=writer
        if writer is not None
        else (FixtureDraftWriter() if mode == "fixture" else None),
        writer_factory=live_writer if live_factory and writer is None else None,
        scenarios=SCENARIOS if mode == "fixture" else (),
    )
