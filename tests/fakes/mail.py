"""A mailbox that records instead of sending.

This is what makes the suite run with no network and no credentials. It stands
in for the *port*, not for Zoho — so if the provider ever changes, not one test
changes with it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from outreach.core.models import InboundMessage, OutboundMessage, SentMessage


class FakeMailbox:
    """Implements `MailPort`. Records what would have been sent."""

    def __init__(self, replies: list[InboundMessage] | None = None) -> None:
        self.sent: list[OutboundMessage] = []
        self._replies = list(replies or [])
        self.fail_next: Exception | None = None

    def send(self, message: OutboundMessage) -> SentMessage:
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        self.sent.append(message)
        return SentMessage(
            message_id=message.message_id,
            to=message.to,
            sent_at=datetime.now(UTC),
            provider_reference=f"fake-{len(self.sent)}",
        )

    def fetch_replies(self, since: datetime | None = None) -> list[InboundMessage]:
        if since is None:
            return list(self._replies)
        return [r for r in self._replies if r.received_at > since]
