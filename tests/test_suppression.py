"""Nobody on the do-not-contact list gets an email. Both guards, proven.

Guard one is the check inside `send_message`.
Guard two is the database rule, which fires even when guard one is bypassed.
"""

import sqlite3

import pytest

from outreach.adapters.store_sqlite import SqliteStore
from outreach.core.models import MessageStatus, SuppressionReason
from outreach.core.sending import SuppressedRecipientError, send_message
from tests.fakes.mail import FakeMailbox


def _send(store, mailbox, contact_id, to="buyer@example.com", message_id="<m1@starthreads.in>"):
    return send_message(
        store=store,
        mailbox=mailbox,
        contact_id=contact_id,
        to=to,
        subject="RFD cotton thread — sample offer",
        body_text="Hello ...",
        message_id=message_id,
    )


def _messages(store: SqliteStore):
    return store._conn.execute("SELECT * FROM messages").fetchall()


# --- the normal path --------------------------------------------------------


def test_send_to_a_clean_address_works(store, contact_id):
    mailbox = FakeMailbox()
    sent = _send(store, mailbox, contact_id)

    assert len(mailbox.sent) == 1
    assert sent.to == "buyer@example.com"

    rows = _messages(store)
    assert len(rows) == 1
    assert rows[0]["status"] == MessageStatus.SENT
    assert rows[0]["sent_at"] is not None


# --- guard one: the check in send_message -----------------------------------


def test_suppressed_address_is_refused(store, contact_id):
    store.add_suppression("buyer@example.com", SuppressionReason.UNSUBSCRIBE)
    mailbox = FakeMailbox()

    with pytest.raises(SuppressedRecipientError):
        _send(store, mailbox, contact_id)

    assert mailbox.sent == [], "no email may leave"
    assert _messages(store) == [], "and nothing may be recorded"


@pytest.mark.parametrize(
    "written_as",
    ["BUYER@example.com", " buyer@example.com ", "Buyer@Example.com"],
)
def test_suppression_ignores_case_and_spacing(store, contact_id, written_as):
    """Someone who unsubscribes in capitals is still unsubscribed."""
    store.add_suppression(written_as, SuppressionReason.UNSUBSCRIBE)
    mailbox = FakeMailbox()

    with pytest.raises(SuppressedRecipientError):
        _send(store, mailbox, contact_id, to="buyer@example.com")
    assert mailbox.sent == []


def test_suppression_applies_across_every_campaign(store, contact_id):
    """Opting out of one campaign opts you out of all of them."""
    from datetime import UTC, datetime

    from outreach.core.models import Campaign, Contact

    store.add_suppression("buyer@example.com", SuppressionReason.UNSUBSCRIBE)
    store.add_campaign(Campaign(id="other", name="Other", created_at=datetime.now(UTC)))
    other_contact = store.add_contact(Contact(campaign_id="other", email="buyer@example.com"))

    with pytest.raises(SuppressedRecipientError):
        _send(store, FakeMailbox(), other_contact)


# --- guard two: the database's own rule -------------------------------------


def test_database_refuses_even_when_the_code_is_bypassed(store, contact_id):
    """This is the backstop. It writes straight to the table, skipping
    send_message entirely — the way a future bug or a hand-typed command
    would."""
    store.add_suppression("buyer@example.com", SuppressionReason.UNSUBSCRIBE)

    with pytest.raises(sqlite3.IntegrityError, match="suppressed"):
        store.record_pending_send(
            contact_id=contact_id,
            message_id="<sneaky@starthreads.in>",
            recipient_email="buyer@example.com",
            subject="s",
            body_text="b",
        )
    assert _messages(store) == []


def test_database_refuses_an_update_onto_a_suppressed_address(store, contact_id):
    store.record_pending_send(
        contact_id=contact_id,
        message_id="<m1@starthreads.in>",
        recipient_email="buyer@example.com",
        subject="s",
        body_text="b",
    )
    store.add_suppression("later@example.com", SuppressionReason.COMPLAINT)

    with pytest.raises(sqlite3.IntegrityError, match="suppressed"):
        store._conn.execute(
            "UPDATE messages SET recipient_email = ? WHERE message_id = ?",
            ("later@example.com", "<m1@starthreads.in>"),
        )


# --- ordering and crash behaviour -------------------------------------------


def test_the_row_is_written_before_the_email_goes_out(store, contact_id):
    """If this order ever reversed, a crash would send an email we have no
    record of — and the next run would send it again."""
    seen: list[str] = []

    class InspectingMailbox(FakeMailbox):
        def send(self, message):
            row = store._conn.execute(
                "SELECT status FROM messages WHERE message_id = ?", (message.message_id,)
            ).fetchone()
            seen.append(row["status"] if row else "no row")
            return super().send(message)

    _send(store, InspectingMailbox(), contact_id)
    assert seen == [MessageStatus.PENDING]


def test_a_failed_send_is_recorded_as_failed(store, contact_id):
    mailbox = FakeMailbox()
    mailbox.fail_next = ConnectionError("smtp unreachable")

    with pytest.raises(ConnectionError):
        _send(store, mailbox, contact_id)

    rows = _messages(store)
    assert len(rows) == 1
    assert rows[0]["status"] == MessageStatus.FAILED
    assert rows[0]["sent_at"] is None


# --- the list itself --------------------------------------------------------


def test_first_reason_is_kept(store):
    """An explicit unsubscribe should not be overwritten by a later bounce."""
    store.add_suppression("x@example.com", SuppressionReason.UNSUBSCRIBE, note="clicked link")
    store.add_suppression("x@example.com", SuppressionReason.BOUNCE)

    row = store._conn.execute("SELECT * FROM suppressions WHERE email = 'x@example.com'").fetchone()
    assert row["reason"] == SuppressionReason.UNSUBSCRIBE
    assert row["note"] == "clicked link"


def test_an_unknown_reason_cannot_be_stored(store):
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO suppressions (email, reason, created_at) VALUES (?, ?, ?)",
            ("y@example.com", "because-i-felt-like-it", "2026-09-20T00:00:00+00:00"),
        )
