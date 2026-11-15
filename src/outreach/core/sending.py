"""The only way to send an email.

Everything about suppression comes together here. There is one function, and
no other path to the mailbox, so "did we remember to check?" is not a question
anyone has to ask.

The order matters, and it is not the obvious one:

1. Normalise the address, so both guards compare the same text.
2. Ask storage whether the address is suppressed. Refuse if so.
3. Write a `pending` row. The database applies its own check at this moment
   and refuses the row if the address is suppressed after all.
4. Only now send the email.
5. Record the outcome — sent, or failed.

Writing the row *before* sending is what makes a crash survivable: a `pending`
row left behind is visible evidence that something was interrupted, instead of
an email that was sent with nothing to show for it, which would be sent again
on the next run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from outreach.core.models import MessageStatus, OutboundMessage, SentMessage
from outreach.core.normalize import normalize_email
from outreach.ports.mail import MailPort, MailUncertainError
from outreach.ports.store import StorePort


class SuppressedRecipientError(RuntimeError):
    """Raised when a send is attempted to an address on the do-not-contact list."""

    def __init__(self, email: str) -> None:
        super().__init__(f"{email} is on the do-not-contact list; refusing to send.")
        self.email = email


def send_message(
    *,
    store: StorePort,
    mailbox: MailPort,
    contact_id: int,
    to: str,
    subject: str,
    body_text: str,
    message_id: str,
    in_reply_to: str | None = None,
    attachments: tuple = (),
) -> SentMessage:
    """Send one email, or refuse. The single door described above."""
    recipient = normalize_email(to)

    # Guard one: refuse before anything is written or sent.
    if store.is_suppressed(recipient):
        raise SuppressedRecipientError(recipient)

    message = OutboundMessage(
        to=recipient,
        subject=subject,
        body_text=body_text,
        message_id=message_id,
        in_reply_to=in_reply_to,
        attachments=attachments,
    )
    # Guard two: the database gets a veto as this row is written, and the row
    # is written before the email leaves.
    store.record_pending_send(
        contact_id=contact_id,
        message_id=message_id,
        recipient_email=recipient,
        subject=subject,
        body_text=body_text,
        **({"attachments": attachments} if attachments else {}),
    )

    try:
        sent = mailbox.send(message)
    except MailUncertainError:
        # Reconcile with the Sent folder before considering a retry.
        raise
    except Exception:
        store.mark_send_outcome(message_id, MessageStatus.FAILED)
        raise

    store.mark_send_outcome(
        message_id, MessageStatus.SENT, sent_at=sent.sent_at or datetime.now(UTC)
    )
    return sent


class NotATestAddressError(RuntimeError):
    """Raised when a test send is aimed at someone in a campaign."""

    def __init__(self, email: str) -> None:
        super().__init__(
            f"{email} is a contact in a campaign. A test email can only go to someone "
            "who is not a prospect — use `outreach send` for real contacts."
        )
        self.email = email


def send_test(
    *,
    store: StorePort,
    mailbox: MailPort,
    to: str,
    subject: str,
    body_text: str,
    message_id: str,
    attachments: tuple = (),
) -> SentMessage:
    """Send one test email to yourself, through the real mailbox.

    This is the second, and only other, way to send (D-017). It exists so the
    connection to Zoho can be tested without importing, drafting and approving
    a fake contact. It is fenced so that it cannot be used to reach a prospect:

    - it refuses any address on the do-not-contact list;
    - it refuses any address that belongs to a contact in any campaign — so it
      cannot be used to get around "one email per contact, reviewed first";
    - the subject is marked [TEST];
    - it writes nothing, so it does not count against the daily cap and does
      not mark anyone as written to.
    """
    recipient = normalize_email(to)
    if store.is_suppressed(recipient):
        raise SuppressedRecipientError(recipient)
    if store.is_contact(recipient):
        raise NotATestAddressError(recipient)

    return mailbox.send(
        OutboundMessage(
            to=recipient,
            subject=f"[TEST] {subject}",
            body_text=body_text,
            message_id=message_id,
            attachments=attachments,
        )
    )
