from datetime import UTC, datetime

import pytest

from outreach.adapters.db import connect
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import Settings
from outreach.core.models import Campaign, Contact

# Values that look obviously fake, so a real credential never hides among them.
_TEST_ENV = {
    "anthropic_api_key": "sk-ant-test-not-a-real-key",
    "mail_smtp_host": "smtp.test.invalid",
    "mail_imap_host": "imap.test.invalid",
    "mail_username": "test@example.com",
    "mail_password": "test-password",
    "sender_name": "Test Sender",
    "sender_email": "test@example.com",
}


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Fully-populated settings that never read the developer's real .env."""
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "test.db"),
        **_TEST_ENV,
    )


@pytest.fixture
def store(tmp_path) -> SqliteStore:
    """A real SQLite database in a temp file — no network, no credentials."""
    return SqliteStore(connect(tmp_path / "test.db"))


@pytest.fixture
def contact_id(store: SqliteStore) -> int:
    """One campaign with one contact, ready to be written to."""
    store.add_campaign(
        Campaign(id="test-campaign", name="Test campaign", created_at=datetime.now(UTC))
    )
    return store.add_contact(
        Contact(campaign_id="test-campaign", email="buyer@example.com", company="Example Mills")
    )
