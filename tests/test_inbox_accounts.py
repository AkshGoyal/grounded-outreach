"""Readable inbox context and targeted verification retain account isolation."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from outreach.adapters.mailbox_store import MailboxStore
from outreach.core.models import InboundMessage
from outreach.web.app import create_app
from tests.test_platform import VerifiedMailbox, db_for, verified_account


def test_named_campaign_account_filters_keep_reply_scope(settings):
    with db_for(settings) as db:
        one = verified_account(db, settings, "one@gmail.com")
        two = verified_account(db, settings, "two@gmail.com")
        db.save_campaign("career", "Readable career campaign", None, "job search", "", one)
        first = MailboxStore(db.conn, one).save_reply(
            InboundMessage(
                message_id="<one@fictional>",
                from_address="owned@fictional.example",
                subject="First",
                body_text="Hello.",
                received_at=datetime.now(UTC),
            ),
            message_id=None,
        )
        second = MailboxStore(db.conn, two).save_reply(
            InboundMessage(
                message_id="<two@fictional>",
                from_address="other@fictional.example",
                subject="Second",
                body_text="Hello.",
                received_at=datetime.now(UTC),
            ),
            message_id=None,
        )
    client = TestClient(create_app(settings, mailbox=lambda s: VerifiedMailbox()))
    page = client.get("/inbox", params={"account_id": one, "show": "all"})
    assert "Readable career campaign" in page.text and 'aria-label="Sending account"' in page.text
    assert f"/replies/{first}" in page.text and f"/replies/{second}" not in page.text
    assert f"account_id={one}" in page.text


def test_check_selected_account_does_not_open_other_accounts(settings):
    with db_for(settings) as db:
        one = verified_account(db, settings, "one@gmail.com")
        verified_account(db, settings, "two@gmail.com")
    called = []

    def mailbox(identity):
        called.append(identity.sender_email)
        return VerifiedMailbox()

    client = TestClient(create_app(settings, mailbox=mailbox))
    response = client.post(
        "/inbox/check",
        data={"account_id": one, "campaign_id": "career", "show": "all"},
        follow_redirects=False,
    )
    assert called == ["one@gmail.com"]
    assert "campaign_id=career" in response.headers["location"]
    assert "show=all" in response.headers["location"]
