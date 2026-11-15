"""The storage port.

What the rest of the system may ask of storage, described without mentioning
SQLite. Same idea as the mail and model ports: the thing above the line asks
for what it needs, and something below the line knows how to do it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from outreach.core.models import (
    Campaign,
    Contact,
    DraftRecord,
    DraftStatus,
    InboundMessage,
    MessageStatus,
    ReplyRecord,
    ReplyStatus,
    SentRecord,
    SuppressionReason,
)


@runtime_checkable
class StorePort(Protocol):
    # --- the do-not-contact list -------------------------------------------
    def is_suppressed(self, email: str) -> bool: ...

    def add_suppression(
        self, email: str, reason: SuppressionReason, note: str | None = None
    ) -> None: ...

    # --- campaigns and contacts --------------------------------------------
    def add_campaign(self, campaign: Campaign) -> None: ...

    def get_campaign(self, campaign_id: str) -> Campaign | None: ...

    def add_contact(self, contact: Contact) -> int: ...

    def get_contact(self, contact_id: int) -> Contact | None: ...

    def emails_in_campaign(self, campaign_id: str) -> set[str]: ...

    def is_contact(self, email: str) -> bool: ...

    def campaign_attachments(self, campaign_id: str) -> tuple: ...

    # --- sends --------------------------------------------------------------
    def record_pending_send(
        self,
        *,
        contact_id: int,
        message_id: str,
        recipient_email: str,
        subject: str,
        body_text: str,
        attachments: tuple = (),
    ) -> int: ...

    def mark_send_outcome(
        self, message_id: str, status: MessageStatus, sent_at: datetime | None = None
    ) -> None: ...

    # --- drafts and review --------------------------------------------------
    def save_draft(
        self,
        *,
        contact_id: int,
        model: str,
        subject: str,
        body: str,
        verdict: str,
        checks: list[dict],
        generation: dict | None = None,
    ) -> int: ...

    def get_draft(self, draft_id: int) -> DraftRecord | None: ...

    def drafts_in_campaign(self, campaign_id: str) -> list[DraftRecord]: ...

    def update_draft(
        self, draft_id: int, *, subject: str, body: str, verdict: str, checks: list[dict]
    ) -> None: ...

    def set_draft_status(self, draft_id: int, status: DraftStatus) -> None: ...

    # --- what the sender needs to stay safe --------------------------------
    def already_written_to(self, contact_id: int) -> bool: ...

    def sent_today(self) -> int: ...

    def sending_slots_today(self) -> int: ...

    # --- replies ------------------------------------------------------------
    def find_message(self, message_id: str) -> SentRecord | None: ...

    def last_message_to(self, email: str) -> SentRecord | None: ...

    def sent_subjects(self) -> set[str]: ...

    def first_send_at(self) -> datetime | None: ...

    def has_reply(self, provider_message_id: str) -> bool: ...

    def save_reply(self, message: InboundMessage, *, message_id: str | None) -> int: ...

    def save_triage(
        self,
        reply_id: int,
        *,
        contact_id: int | None,
        matched_by: str,
        category: str,
        summary: str = "",
        details: dict[str, str] | None = None,
        suggested_reply: str = "",
        action: str = "",
    ) -> None: ...

    def replies_needing_triage(self) -> list[int]: ...

    def get_reply(self, reply_id: int) -> ReplyRecord | None: ...

    def claim_reply_send(self, reply_id: int, message_id: str) -> bool: ...

    def list_replies(self) -> list[ReplyRecord]: ...

    def set_reply_status(self, reply_id: int, status: ReplyStatus) -> None: ...
