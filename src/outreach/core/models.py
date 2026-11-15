"""Domain types.

These are the project's own vocabulary for mail. Nothing here knows that Zoho,
SMTP or IMAP exist — that is the point. Adapters translate between these types
and whatever a provider actually speaks (invariant I-1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field, model_validator

from outreach.core.attachments import EmailAttachment, validate_bundle


class OutboundMessage(BaseModel):
    """An email we intend to send. Not yet sent."""

    to: EmailStr
    subject: str = Field(min_length=1)
    body_text: str = Field(min_length=1)

    # Threading (D-002): we generate our own Message-ID and keep it, so an
    # inbound reply's In-Reply-To / References can be matched back to the
    # recipient it belongs to. Phase 7 does the matching; this carries the key.
    message_id: str = Field(min_length=1)
    attachments: tuple[EmailAttachment, ...] = ()
    in_reply_to: str | None = None

    @model_validator(mode="after")
    def valid_attachment_bundle(self):
        validate_bundle(self.attachments)
        return self


class SentMessage(BaseModel):
    """The outcome of a send. Returned by the mail port, recorded by the caller."""

    message_id: str
    to: EmailStr
    sent_at: datetime
    provider_reference: str | None = None


class InboundMessage(BaseModel):
    """A reply, as the mail port hands it back — parsed, not yet interpreted.

    `in_reply_to` and `references` are what thread attribution is built on, and
    both are frequently absent or mangled by real mail clients. A message that
    cannot be attributed is surfaced to a human, never dropped (invariant I-4).
    """

    message_id: str
    from_address: EmailStr
    subject: str
    body_text: str
    received_at: datetime
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    # Set by the adapter from the Auto-Submitted / X-Autoreply headers: an
    # out-of-office message, which must never be read as a person's answer.
    auto_submitted: bool = False


class Campaign(BaseModel):
    """One outreach push: its own message, tone and rules."""

    id: str = Field(min_length=1, description="Short slug, e.g. 'rfd-buyers-q4'")
    name: str = Field(min_length=1)
    created_at: datetime


class Contact(BaseModel):
    """One business we may write to, within one campaign."""

    id: int | None = None
    campaign_id: str
    email: EmailStr
    company: str | None = None

    # Whatever we know about them, as given. Phase 4 may only make claims that
    # trace back to something in here (invariant I-3).
    evidence: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


class SuppressionReason(StrEnum):
    """Why someone is on the do-not-contact list.

    A closed set: an unrecognised reason cannot be stored, so this list is the
    whole truth about how people end up suppressed.
    """

    UNSUBSCRIBE = "unsubscribe"
    BOUNCE = "bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"


class Suppression(BaseModel):
    """An address we must never write to again. Global, never per-campaign."""

    email: EmailStr
    reason: SuppressionReason
    created_at: datetime
    note: str | None = None


class MessageStatus(StrEnum):
    """Where a send got to.

    `PENDING` exists so that a crash mid-send is visible afterwards rather than
    silently re-sent: the row is written *before* the email goes out.
    """

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class DraftStatus(StrEnum):
    """Where a draft is in review. Only APPROVED can be sent."""

    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


class DraftRecord(BaseModel):
    """A stored draft, as the review screen and the sender see it."""

    id: int
    contact_id: int
    model: str
    subject: str
    body: str
    verdict: str
    checks: list[dict] = Field(default_factory=list)
    status: DraftStatus
    created_at: datetime
    reviewed_at: datetime | None = None

    # Campaign identity and immutable instruction snapshot; None for historical drafts.
    campaign_id: str | None = None
    generation: dict | None = None

    # Filled in when listed alongside the contact, for display.
    company: str | None = None
    email: str | None = None


class SentRecord(BaseModel):
    """One email we sent, as a reply is matched back to it."""

    message_id: str
    contact_id: int
    recipient_email: str
    subject: str
    body_text: str
    sent_at: datetime | None = None


class ReplyStatus(StrEnum):
    NEW = "new"
    DONE = "done"


class ReplyRecord(BaseModel):
    """A stored reply with how it was read, for the Inbox."""

    id: int
    from_address: str
    subject: str
    body_text: str
    received_at: datetime
    provider_message_id: str
    message_id: str | None = None  # ours, that it answers; None if unmatched

    # From reply_triage; None until it has been read.
    contact_id: int | None = None
    matched_by: str | None = None
    category: str | None = None
    summary: str = ""
    details: dict[str, str] = Field(default_factory=dict)
    suggested_reply: str = ""
    action: str = ""
    status: ReplyStatus = ReplyStatus.NEW

    # Filled in for display.
    company: str | None = None
    campaign_id: str | None = None
    recipient_email: str | None = None
