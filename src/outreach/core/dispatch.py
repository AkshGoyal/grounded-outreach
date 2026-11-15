"""Sending the approved drafts in a campaign — safely, and slowly.

Planning and sending are separate on purpose. `plan` decides what would go out
and why anything would not, and writes nothing, so a dry run shows exactly
what a real run would do. `dispatch` then sends only what the plan allowed.

What stops a draft going out:

- it is not approved;
- the contact is on the do-not-contact list (checked again, twice, at the
  moment of sending, by `sending.send_message`);
- the contact has already been written to — including a send that was
  interrupted, because re-sending after a crash is exactly the failure the
  pending status exists to prevent;
- its text repeats the closing, or itself — checked again here against the
  closing as it is now, because a draft written before the closing existed
  carries its own offer and sign-off (D-020);
- today's cap has been reached.

Every email gets the same tail — the campaign's own closing if it has one,
otherwise a signature footer — and always a way to opt out. It is added here
rather than stored in the draft, so it cannot be edited away during review.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from outreach.core.email_composer import fixed_content, fixed_content_problem
from outreach.core.flow import repeated_lines
from outreach.core.generation import instruction_fingerprint
from outreach.core.models import DraftRecord, DraftStatus
from outreach.core.sending import SuppressedRecipientError, send_message
from outreach.ports.mail import MailAuthError, MailError, MailPort, MailUncertainError
from outreach.ports.store import StorePort


def footer(*, name: str, company: str, address: str) -> str:
    """Who is writing, from where, and how to say no — as a signature.

    Identifying the sender and offering a way out is a legal baseline. But
    newsletter boilerplate ("if you would rather not hear from us...") is also
    one of the things that sends an email to Promotions, so it is written the
    way one person would say it to another (D-018). Any reply saying no is
    added to the do-not-contact list, whatever words it uses.
    """
    return (
        f"{name}\n{company}\n{address}\n\n"
        "If this isn't relevant to you, just reply and say so, and I won't write again."
    )


# Added under a campaign's own closing. The closing identifies the sender;
# this is the one thing a closing can easily leave out and must not: a plain
# way to say no. Worded as a person would say it (D-018, D-019).
OPT_OUT = (
    "If this is not relevant to your unit, simply reply and let us know, "
    "and we will not write again."
)


def email_tail(*, closing: str | None, name: str, company: str, address: str) -> str:
    """Everything that follows the drafted text, exactly as sent.

    With a campaign closing: the closing word for word, then the opt-out line.
    Without one: the standard signature footer, which carries its own.
    """
    if closing and closing.strip():
        return f"{closing.strip()}\n\n{OPT_OUT}"
    return footer(name=name, company=company, address=address)


def new_message_id(sender_email: str) -> str:
    """A globally unique Message-ID on our own domain. Stored before sending,
    so a reply can later be matched back to this exact email."""
    domain = sender_email.rsplit("@", 1)[-1]
    return f"<{uuid.uuid4().hex}@{domain}>"


@dataclass
class Planned:
    draft: DraftRecord
    skip: str | None = None  # why it will not be sent, or None if it will

    @property
    def will_send(self) -> bool:
        return self.skip is None


def plan(
    store: StorePort,
    campaign_id: str,
    *,
    daily_cap: int,
    closing: str | None,
    campaign_copy: str,
) -> list[Planned]:
    """What a send would do right now. Writes nothing.

    `closing` and `campaign_copy` are required, not defaulted: a caller that
    forgot the closing would let repeated lines through unseen."""
    remaining = max(daily_cap - store.sending_slots_today(), 0)
    planned: list[Planned] = []
    seen_contacts: set[int] = set()

    # Oldest approval first, so the order is the order you approved them in.
    for draft in sorted(store.drafts_in_campaign(campaign_id), key=lambda d: d.id):
        if draft.status is not DraftStatus.APPROVED:
            continue
        if draft.contact_id in seen_contacts:
            planned.append(Planned(draft, "a second approved draft for the same contact"))
            continue
        seen_contacts.add(draft.contact_id)

        contact = store.get_contact(draft.contact_id)
        if contact is None or contact.campaign_id != campaign_id:
            planned.append(Planned(draft, "recipient does not belong to this campaign"))
            continue
        try:
            fixed_problem = fixed_content_problem(
                draft.body,
                fixed_content(campaign_copy, evidence=contact.evidence, company=contact.company),
            )
        except ValueError as exc:
            fixed_problem = str(exc)
        if draft.generation and draft.generation.get("instruction_hash") != instruction_fingerprint(
            campaign_id, campaign_copy, closing
        ):
            planned.append(Planned(draft, "campaign instructions changed; regenerate this draft"))
        elif fixed_problem:
            planned.append(Planned(draft, fixed_problem))
        elif draft.email and store.is_suppressed(draft.email):
            planned.append(Planned(draft, "on the do-not-contact list"))
        elif store.already_written_to(draft.contact_id):
            planned.append(Planned(draft, "already written to"))
        elif repeats := repeated_lines(draft.body, closing=closing, campaign_copy=campaign_copy):
            line, reason = repeats[0]
            more = f" (+{len(repeats) - 1} more)" if len(repeats) > 1 else ""
            planned.append(
                Planned(draft, f"repeats — “{_short(line)}”: {reason}{more} Edit or redraft it.")
            )
        elif remaining <= 0:
            planned.append(Planned(draft, f"today's limit of {daily_cap} is reached"))
        else:
            planned.append(Planned(draft))
            remaining -= 1
    return planned


def _short(line: str, limit: int = 60) -> str:
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


@dataclass
class Outcome:
    draft: DraftRecord
    sent: bool
    detail: str


def dispatch(
    store: StorePort,
    mailbox: MailPort,
    planned: list[Planned],
    *,
    sender_email: str,
    tail: str,
    pause: Callable[[], None],
    daily_cap: int | None = None,
    attachments: tuple | None = None,
    stop: Callable[[], bool] = lambda: False,
    report: Callable[[Outcome], None] = lambda outcome: None,
) -> list[Outcome]:
    """Send what the plan allowed, one at a time, pausing between each.

    `stop` is asked before every email, so a run started from the web page can
    be stopped between emails — never halfway through one. `report` hears
    each outcome as it happens, for live progress."""
    outcomes: list[Outcome] = []
    to_send = [p for p in planned if p.will_send]
    if attachments is None:
        attachments = (
            store.campaign_attachments(store.get_contact(to_send[0].draft.contact_id).campaign_id)
            if to_send
            else ()
        )

    def record(outcome: Outcome) -> None:
        outcomes.append(outcome)
        report(outcome)

    for position, item in enumerate(to_send):
        draft = item.draft
        if position > 0:
            pause()
        if stop():
            break
        if daily_cap is not None and store.sending_slots_today() >= daily_cap:
            record(Outcome(draft, False, "today's sending limit is reached"))
            break
        current = store.get_draft(draft.id)
        if (
            current is None
            or current.status is not DraftStatus.APPROVED
            or current.subject != draft.subject
            or current.body != draft.body
        ):
            record(Outcome(draft, False, "approval or draft changed after send preview"))
            continue
        if store.already_written_to(draft.contact_id):
            record(Outcome(draft, False, "already written to"))
            continue
        try:
            send_message(
                store=store,
                mailbox=mailbox,
                attachments=attachments,
                contact_id=draft.contact_id,
                to=draft.email or "",
                subject=draft.subject,
                body_text=f"{draft.body}\n\n{tail}",
                message_id=new_message_id(sender_email),
            )
        except MailUncertainError:
            record(
                Outcome(draft, False, "Delivery uncertain — stopped. Check saved history and Sent.")
            )
            break
        except MailAuthError as exc:
            # Every remaining message would fail the same way. Stop.
            record(Outcome(draft, False, f"stopped — {exc}"))
            break
        except SuppressedRecipientError:
            record(Outcome(draft, False, "on the do-not-contact list"))
            continue
        except MailError as exc:
            record(Outcome(draft, False, str(exc)))
            continue

        store.set_draft_status(draft.id, DraftStatus.SENT)
        record(Outcome(draft, True, "sent"))
    return outcomes
