"""Reading replies: which email each one answers, what it says, what to do.

Three steps, each with its own rule:

1. **Match** a message in the inbox to an email we sent — by the thread
   headers first, then the original's Message-ID quoted inside a bounce, then
   the sender's address, then the subject. A message that matches none of
   these is not a reply to us and is not stored: the inbox also holds the
   operator's ordinary mail, which is none of this tool's business. A reply
   matched only by subject is kept, unattributed, for a person (I-4).
2. **Read** it. Bounces and automatic replies are sorted by code, from the
   headers and the delivery-status text. Everything else is read by the model,
   and any detail it pulls out (postal address, contact person, phone) is kept
   only if our code finds it written in the reply — the grounding rule again.
3. **Act**, only in the safe direction: a hard bounce or a "not interested"
   puts the address on the do-not-contact list at once. Nothing is ever sent
   on its own; a suggested answer waits for a person.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from outreach.core.drafting import load_prompt
from outreach.core.models import (
    InboundMessage,
    ReplyRecord,
    ReplyStatus,
    SentRecord,
    SuppressionReason,
)
from outreach.core.normalize import normalize_email
from outreach.core.sending import SuppressedRecipientError, send_message
from outreach.ports.llm import LLMError, LLMPort
from outreach.ports.mail import MailPort
from outreach.ports.store import StorePort


class ReplyCategory(StrEnum):
    WANTS_SAMPLES = "wants_samples"
    INTERESTED = "interested"
    QUESTION = "question"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    OTHER = "other"
    UNREAD = "unread"  # the model could not read it; tried again at the next check


LABELS = {
    ReplyCategory.WANTS_SAMPLES: "Wants samples",
    ReplyCategory.INTERESTED: "Interested",
    ReplyCategory.QUESTION: "Question",
    ReplyCategory.NOT_INTERESTED: "Not interested",
    ReplyCategory.OUT_OF_OFFICE: "Out of office",
    ReplyCategory.BOUNCE: "Bounced",
    ReplyCategory.OTHER: "Other",
    ReplyCategory.UNREAD: "Not read yet",
}


class ReplyReading(BaseModel):
    """What the model returns for one reply."""

    category: Literal[
        "wants_samples", "interested", "question", "not_interested", "out_of_office", "other"
    ]
    summary: str
    postal_address: str | None
    contact_person: str | None
    phone: str | None
    suggested_reply: str


# --- step 1: match ------------------------------------------------------------

_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s]+>")
_SUBJECT_PREFIX = re.compile(r"^\s*((re|fwd?|aw|wg|sv)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
_BOUNCE_SUBJECT = re.compile(
    r"undeliver|delivery status notification|mail delivery (failed|failure|subsystem)"
    r"|returned mail|delivery failure|failure notice|could not be delivered",
    re.IGNORECASE,
)
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass
class Match:
    matched_by: Literal["thread", "bounce", "address", "subject"]
    sent: SentRecord | None  # None when matched by subject only


def clean_subject(subject: str) -> str:
    return _SUBJECT_PREFIX.sub("", subject or "").strip()


def is_bounce(message: InboundMessage) -> bool:
    local = message.from_address.split("@", 1)[0].lower()
    return local in _BOUNCE_SENDERS or bool(_BOUNCE_SUBJECT.search(message.subject or ""))


def is_hard_bounce(body: str) -> bool:
    """Permanent (5.x.x) unless the report says only temporary (4.x.x) or
    'delayed'. A temporary failure must not cost a lead."""
    permanent = re.search(r"\b5\.\d{1,3}\.\d{1,3}\b", body)
    temporary = re.search(r"\b4\.\d{1,3}\.\d{1,3}\b", body) or re.search(
        r"delay(ed)?|will (be )?retr(y|ied)|temporar", body, re.IGNORECASE
    )
    return bool(permanent) or not temporary


def match(message: InboundMessage, store: StorePort) -> Match | None:
    """Which email of ours this answers, or None if it is not a reply to us."""
    for message_id in [message.in_reply_to, *message.references]:
        if message_id and (sent := store.find_message(message_id)):
            return Match("thread", sent)

    if is_bounce(message):
        for message_id in _MESSAGE_ID.findall(message.body_text):
            if sent := store.find_message(message_id):
                return Match("bounce", sent)
        for address in _ADDRESS.findall(message.body_text):
            if sent := store.last_message_to(address):
                return Match("bounce", sent)
        return None

    if sent := store.last_message_to(message.from_address):
        return Match("address", sent)
    if clean_subject(message.subject) in {clean_subject(s) for s in store.sent_subjects()}:
        return Match("subject", None)
    return None


# --- step 2: read -------------------------------------------------------------

_QUOTE_START = re.compile(
    r"^\s*(on\s.+wrote:?\s*$|-{2,}\s*original message\s*-{2,}|from:\s.+|sent from my\s)",
    re.IGNORECASE,
)


def new_part(body: str) -> str:
    """The reply without the quoted email under it."""
    kept: list[str] = []
    for line in (body or "").splitlines():
        if _QUOTE_START.match(line) and kept:
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    return text or (body or "").strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def found_in(value: str | None, text: str) -> str | None:
    """`value` if it is really written in `text` (spacing and case aside)."""
    if value and value.strip() and _squash(value) in _squash(text):
        return value.strip()
    return None


def read_reply(
    llm: LLMPort,
    *,
    reply: str,
    original: SentRecord | None,
    company: str | None,
    offer: str,
    sender: str,
    sender_company: str,
) -> ReplyReading:
    prompt = load_prompt("read_reply.md").format(
        sender=sender or "the sender",
        sender_company=sender_company or "",
        company=company or "them",
        original_subject=original.subject if original else "(unknown)",
        original_body=original.body_text if original else "(unknown)",
        reply=reply,
        offer=offer.strip() or "(nothing written)",
    )
    return llm.generate(prompt=prompt, schema=ReplyReading, max_tokens=1200)


# --- steps 2 and 3 together ---------------------------------------------------


@dataclass
class CheckResult:
    new: int = 0
    ignored: int = 0
    suppressed: list[str] = field(default_factory=list)
    unread: int = 0


def triage(
    store: StorePort,
    llm: LLMPort | None,
    reply_id: int,
    message: InboundMessage,
    found: Match,
    *,
    offer_for: Callable[[str], str],
    sender: str,
    sender_company: str,
    result: CheckResult,
) -> None:
    """Read one stored reply and act on it."""
    sent = found.sent
    contact = store.get_contact(sent.contact_id) if sent else None
    details: dict[str, str] = {}
    suggested = ""
    action = ""

    if found.matched_by == "bounce" or is_bounce(message):
        category = ReplyCategory.BOUNCE
        hard = is_hard_bounce(message.body_text)
        summary = "The address does not accept mail." if hard else "Delivery delayed; will retry."
        if hard and sent:
            store.add_suppression(
                sent.recipient_email, SuppressionReason.BOUNCE, f"bounced: {message.subject}"
            )
            action = f"{sent.recipient_email} added to the do-not-contact list."
            result.suppressed.append(sent.recipient_email)
    elif message.auto_submitted:
        category = ReplyCategory.OUT_OF_OFFICE
        summary = "Automatic reply."
    elif llm is None:
        category, summary = ReplyCategory.UNREAD, "Not read yet — the AI key isn't set."
        result.unread += 1
    else:
        reply = new_part(message.body_text)
        try:
            reading = read_reply(
                llm,
                reply=reply,
                original=sent,
                company=contact.company if contact else None,
                offer=offer_for(contact.campaign_id) if contact else "",
                sender=sender,
                sender_company=sender_company,
            )
        except LLMError as exc:
            category, summary = ReplyCategory.UNREAD, f"Couldn't read it yet ({exc})."
            result.unread += 1
        else:
            category = ReplyCategory(reading.category)
            summary = reading.summary.strip()
            suggested = reading.suggested_reply.strip()
            for key, value in (
                ("postal_address", reading.postal_address),
                ("contact_person", reading.contact_person),
                ("phone", reading.phone),
            ):
                if kept := found_in(value, reply):
                    details[key] = kept
            if category is ReplyCategory.NOT_INTERESTED and sent:
                store.add_suppression(
                    sent.recipient_email,
                    SuppressionReason.UNSUBSCRIBE,
                    f"replied: {summary}"[:300],
                )
                action = f"{sent.recipient_email} added to the do-not-contact list."
                result.suppressed.append(sent.recipient_email)
            elif category is ReplyCategory.NOT_INTERESTED:
                action = (
                    "Not matched to a contact, so nobody was added to the do-not-contact "
                    "list. Add the address yourself if it should be."
                )

    store.save_triage(
        reply_id,
        contact_id=sent.contact_id if sent else None,
        matched_by=found.matched_by,
        category=str(category),
        summary=summary,
        details=details,
        suggested_reply=suggested,
        action=action,
    )
    # Nothing for a person to do: the address is already on the do-not-contact
    # list, or it was an automatic message. Still listed under "All".
    if category is ReplyCategory.OUT_OF_OFFICE or (
        category in (ReplyCategory.BOUNCE, ReplyCategory.NOT_INTERESTED) and sent
    ):
        store.set_reply_status(reply_id, ReplyStatus.DONE)


def check_replies(
    store: StorePort,
    mailbox: MailPort,
    llm: LLMPort | None,
    *,
    own_address: str,
    offer_for: Callable[[str], str],
    sender: str,
    sender_company: str,
) -> CheckResult:
    """Read new replies from the inbox, store them, read them, act on them."""
    result = CheckResult()
    first = store.first_send_at()
    if first is None:
        return result  # nothing sent, so nothing can be a reply

    own = normalize_email(own_address) if own_address else ""
    read_now: set[int] = set()
    for message in mailbox.fetch_replies(since=first - timedelta(days=1)):
        if store.has_reply(message.message_id):
            continue
        if own and normalize_email(message.from_address) == own:
            continue
        found = match(message, store)
        if found is None:
            result.ignored += 1
            continue
        reply_id = store.save_reply(
            message, message_id=found.sent.message_id if found.sent else None
        )
        read_now.add(reply_id)
        result.new += 1
        triage(
            store,
            llm,
            reply_id,
            message,
            found,
            offer_for=offer_for,
            sender=sender,
            sender_company=sender_company,
            result=result,
        )

    # Replies whose reading failed at an earlier check get another go.
    for reply_id in store.replies_needing_triage():
        if reply_id in read_now:
            continue
        stored = store.get_reply(reply_id)
        if stored is None or stored.category not in (None, ReplyCategory.UNREAD):
            continue
        message = InboundMessage(
            message_id=stored.provider_message_id,
            from_address=stored.from_address,
            subject=stored.subject,
            body_text=stored.body_text,
            received_at=stored.received_at,
        )
        sent = store.find_message(stored.message_id) if stored.message_id else None
        found = Match(stored.matched_by or ("thread" if sent else "subject"), sent)  # type: ignore[arg-type]
        triage(
            store,
            llm,
            reply_id,
            message,
            found,
            offer_for=offer_for,
            sender=sender,
            sender_company=sender_company,
            result=result,
        )
    return result


# --- answering ----------------------------------------------------------------


class CannotReplyError(RuntimeError):
    """A reply that the tool cannot answer — say why, and answer it in Zoho."""


def send_reply(
    store: StorePort,
    mailbox: MailPort,
    reply: ReplyRecord,
    *,
    body: str,
    message_id: str,
    daily_cap: int | None = None,
) -> None:
    """Answer one reply, in the same thread, after a person has written or
    edited the text. Goes through `send_message`, so both suppression guards
    apply: someone who asked not to be contacted cannot be answered from here.
    """
    if not body.strip():
        raise CannotReplyError("The answer is empty.")
    if reply.contact_id is None:
        raise CannotReplyError(
            "This reply isn't matched to a contact, so answer it from Zoho directly."
        )
    if reply.category == ReplyCategory.BOUNCE:
        raise CannotReplyError("This is a bounce — there is nobody to answer.")
    if store.is_suppressed(reply.from_address):
        raise SuppressedRecipientError(reply.from_address)
    if daily_cap is not None and store.sending_slots_today() >= daily_cap:
        raise CannotReplyError("Today's sending limit is reached. Wait until tomorrow (UTC).")
    if not store.claim_reply_send(reply.id, message_id):
        raise CannotReplyError(
            "An answer was already sent or its outcome is uncertain. "
            "Check message history and the provider's Sent folder before doing anything else."
        )
    original = store.find_message(reply.message_id) if reply.message_id else None
    subject = clean_subject(original.subject if original else reply.subject) or reply.subject
    send_message(
        store=store,
        mailbox=mailbox,
        contact_id=reply.contact_id,
        to=reply.from_address,
        subject=f"Re: {subject}",
        body_text=body.strip(),
        message_id=message_id,
        in_reply_to=reply.provider_message_id,
    )
    store.set_reply_status(reply.id, ReplyStatus.DONE)
