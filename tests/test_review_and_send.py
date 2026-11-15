"""Review and sending — the last step before an email reaches a real person.

Every test here is a way the send step could hurt: an unreviewed draft going
out, an invented claim slipping through an edit, someone getting two emails,
someone on the do-not-contact list getting one, or an email going out with no
way to identify the sender or opt out.
"""

from datetime import UTC, datetime

import pytest

from outreach.core.dispatch import dispatch, footer, new_message_id, plan
from outreach.core.drafting import Draft, DraftSentence, check_draft
from outreach.core.models import Campaign, Contact, DraftStatus, SuppressionReason
from outreach.core.review import approval_blocker, recheck, split_sentences, storable_body
from outreach.ports.mail import MailAuthError, MailError
from tests.fakes.mail import FakeMailbox

EVIDENCE = {"City": "Hyderabad", "What they make": "Handloom and powerloom"}
COPY = "Star Threads makes RFD cotton thread in Ludhiana. We send free samples."
FOOTER = footer(name="Aksh Goyal", company="Star Threads", address="Tajpur Road, Ludhiana")


@pytest.fixture
def campaign(store):
    store.add_campaign(Campaign(id="c", name="c", created_at=datetime.now(UTC)))
    return "c"


def _contact(store, campaign, email, company="Deccan Weaves"):
    return store.add_contact(
        Contact(campaign_id=campaign, email=email, company=company, evidence=EVIDENCE)
    )


def _approved(store, contact_id, subject="RFD thread sample", body="Hello.\n\nWe make thread."):
    draft_id = store.save_draft(
        contact_id=contact_id, model="m", subject=subject, body=body, verdict="clean", checks=[]
    )
    store.set_draft_status(draft_id, DraftStatus.APPROVED)
    return draft_id


def _send(store, planned, mailbox=None):
    return dispatch(
        store,
        mailbox or FakeMailbox(),
        planned,
        sender_email="aksh@starthreads.in",
        tail=FOOTER,
        pause=lambda: None,
    )


# --- review: what reaches the review screen ---------------------------------


def test_lines_that_cannot_be_backed_up_never_reach_review():
    result = check_draft(
        Draft(
            subject="RFD thread sample",
            sentences=[
                DraftSentence(text="You are in Hyderabad.", cites="City"),
                DraftSentence(text="I saw your Coimbatore unit.", cites="City"),
            ],
        ),
        evidence=EVIDENCE,
        company="Deccan Weaves",
        campaign_copy=COPY,
    )
    body = storable_body(result)
    assert "Hyderabad" in body
    assert "Coimbatore" not in body


def test_the_body_is_laid_out_as_paragraphs_not_one_block():
    result = check_draft(
        Draft(subject="x", sentences=[DraftSentence(text="Hello."), DraftSentence(text="Bye.")]),
        evidence=EVIDENCE,
        campaign_copy=COPY,
    )
    assert storable_body(result) == "Hello.\n\nBye."


# --- review: editing and approving ------------------------------------------


def _recheck(subject, body):
    return recheck(
        subject, body, evidence=EVIDENCE, company="Deccan Weaves", campaign_copy=COPY, sender="Aksh"
    )


def test_a_clean_edit_can_be_approved():
    assert (
        approval_blocker(_recheck("RFD thread sample", "Hello.\n\nYou are in Hyderabad.")) is None
    )


def test_an_invented_claim_typed_during_review_blocks_approval():
    """The rule holds all the way to the send, including for text a person
    typed. If it is true, it belongs in the spreadsheet."""
    blocker = approval_blocker(_recheck("RFD thread sample", "We met at your Coimbatore office."))
    assert blocker is not None
    assert "coimbatore" in blocker.lower()


def test_an_empty_draft_cannot_be_approved():
    assert approval_blocker(_recheck("", "")) is not None


def test_sentences_split_on_full_stops_and_line_breaks():
    assert split_sentences("Hello.\n\nOne. Two?\nThree") == ["Hello.", "One.", "Two?", "Three"]


# --- sending: what is allowed to go out -------------------------------------


def test_only_approved_drafts_are_planned(store, campaign):
    a = _contact(store, campaign, "a@example.com")
    b = _contact(store, campaign, "b@example.com")
    _approved(store, a)
    store.save_draft(contact_id=b, model="m", subject="s", body="b", verdict="clean", checks=[])

    going = [
        p
        for p in plan(store, campaign, daily_cap=10, closing=None, campaign_copy="")
        if p.will_send
    ]
    assert [p.draft.email for p in going] == ["a@example.com"]


def test_a_suppressed_contact_is_held_back(store, campaign):
    a = _contact(store, campaign, "stop@example.com")
    _approved(store, a)
    store.add_suppression("stop@example.com", SuppressionReason.UNSUBSCRIBE)

    [item] = plan(store, campaign, daily_cap=10, closing=None, campaign_copy="")
    assert not item.will_send and "do-not-contact" in item.skip


def test_nobody_gets_two_emails(store, campaign):
    a = _contact(store, campaign, "a@example.com")
    _approved(store, a)
    assert _send(store, plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""))[0].sent

    # A second approved draft for the same person, on a later run.
    _approved(store, a)
    again = plan(store, campaign, daily_cap=10, closing=None, campaign_copy="")
    assert not any(p.will_send for p in again)


def test_an_interrupted_send_is_never_repeated(store, campaign):
    """A crash can leave a message 'pending' — it may or may not have gone.
    Sending again is the failure the pending status exists to prevent."""
    a = _contact(store, campaign, "a@example.com")
    _approved(store, a)
    store.record_pending_send(
        contact_id=a,
        message_id="<x@y>",
        recipient_email="a@example.com",
        subject="s",
        body_text="b",
    )
    [item] = plan(store, campaign, daily_cap=10, closing=None, campaign_copy="")
    assert not item.will_send and "already written to" in item.skip


def test_the_daily_cap_is_respected(store, campaign):
    for n in range(4):
        _approved(store, _contact(store, campaign, f"p{n}@example.com"))
    planned = plan(store, campaign, daily_cap=2, closing=None, campaign_copy="")
    assert sum(p.will_send for p in planned) == 2
    assert all("limit" in p.skip for p in planned if not p.will_send)


def test_the_cap_counts_what_was_already_sent_today(store, campaign):
    a = _contact(store, campaign, "a@example.com")
    b = _contact(store, campaign, "b@example.com")
    _approved(store, a)
    _send(store, plan(store, campaign, daily_cap=1, closing=None, campaign_copy=""))
    _approved(store, b)
    assert not any(
        p.will_send for p in plan(store, campaign, daily_cap=1, closing=None, campaign_copy="")
    )


# --- sending: what the email contains ---------------------------------------


def test_every_email_identifies_the_sender_and_offers_a_way_out(store, campaign):
    a = _contact(store, campaign, "a@example.com")
    _approved(store, a)
    mailbox = FakeMailbox()
    _send(store, plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""), mailbox)

    body = mailbox.sent[0].body_text
    assert "Aksh Goyal" in body
    assert "Tajpur Road, Ludhiana" in body
    assert "reply and say so" in body, "a working way to opt out"
    assert "hear from us" not in body, "newsletter wording pushes mail to Promotions"


def test_message_ids_are_unique_and_on_our_domain():
    ids = {new_message_id("aksh@starthreads.in") for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("<") and i.endswith("@starthreads.in>") for i in ids)


def test_a_sent_draft_is_marked_sent(store, campaign):
    a = _contact(store, campaign, "a@example.com")
    draft_id = _approved(store, a)
    _send(store, plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""))
    assert store.get_draft(draft_id).status is DraftStatus.SENT


# --- sending: when things go wrong ------------------------------------------


class _FailingMailbox(FakeMailbox):
    def __init__(self, error):
        super().__init__()
        self._error = error

    def send(self, message):
        raise self._error


def test_a_login_failure_stops_the_run_instead_of_failing_every_email(store, campaign):
    for n in range(3):
        _approved(store, _contact(store, campaign, f"p{n}@example.com"))
    outcomes = _send(
        store,
        plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""),
        _FailingMailbox(MailAuthError("no")),
    )
    assert len(outcomes) == 1 and "stopped" in outcomes[0].detail


def test_one_refused_address_does_not_stop_the_others(store, campaign):
    for n in range(2):
        _approved(store, _contact(store, campaign, f"p{n}@example.com"))

    class OneBad(FakeMailbox):
        def send(self, message):
            if message.to == "p0@example.com":
                raise MailError("refused")
            return super().send(message)

    outcomes = _send(
        store, plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""), OneBad()
    )
    assert [o.sent for o in outcomes] == [False, True]


def test_a_failed_send_can_be_tried_again_later(store, campaign):
    """Unlike an interrupted one: a clean failure is known not to have gone."""
    a = _contact(store, campaign, "a@example.com")
    _approved(store, a)
    _send(
        store,
        plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""),
        _FailingMailbox(MailError("refused")),
    )
    [item] = plan(store, campaign, daily_cap=10, closing=None, campaign_copy="")
    assert item.will_send


def test_there_is_a_pause_between_emails(store, campaign):
    for n in range(3):
        _approved(store, _contact(store, campaign, f"p{n}@example.com"))
    pauses = []
    dispatch(
        store,
        FakeMailbox(),
        plan(store, campaign, daily_cap=10, closing=None, campaign_copy=""),
        sender_email="a@starthreads.in",
        tail=FOOTER,
        pause=lambda: pauses.append(1),
    )
    assert len(pauses) == 2, "between three emails, not before the first"
