"""The mail port (invariant I-1).

Everything above this line deals in `outreach.core.models` types only. No code
outside `outreach.adapters` may speak SMTP, IMAP, or any provider mail API.

That constraint is what keeps D-002 reversible: moving from Zoho to Google
Workspace, or to the Gmail API, means writing one new adapter and changing
configuration — not touching anything that uses mail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from outreach.core.models import InboundMessage, OutboundMessage, SentMessage


class MailError(RuntimeError):
    """One message could not be sent. Others may still succeed."""


class MailAuthError(MailError):
    """The mailbox refused to log in. Nothing will send until this is fixed,
    so a run should stop rather than fail every remaining message."""


class MailUncertainError(MailError):
    """The server may have accepted the email. Retain its pending record."""


@runtime_checkable
class MailPort(Protocol):
    """What the rest of the system is allowed to ask of a mailbox."""

    def send(self, message: OutboundMessage) -> SentMessage:
        """Send one message. Raises on failure; never partially succeeds."""
        ...

    def fetch_replies(self, since: datetime | None = None) -> list[InboundMessage]:
        """Return replies received since `since` (or all available if None).

        Reading is non-destructive: messages stay in the mailbox and remain
        readable in an ordinary mail client.
        """
        ...
