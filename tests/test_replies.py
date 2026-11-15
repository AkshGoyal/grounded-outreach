"""Reading replies: matching, sorting, acting — and never acting unsafely.

Everything runs against a fake mailbox and a fake model. Names and addresses
are made up.
"""

from datetime import UTC, datetime, timedelta

import pytest

from outreach.core.models import Campaign, Contact, InboundMessage, ReplyStatus
from outreach.core.replies import (
    CannotReplyError,
    ReplyReading,
    check_replies,
    new_part,
    send_reply,
)
from outreach.core.sending import SuppressedRecipientError, send_message
from tests.fakes.llm import FakeLLM
from tests.fakes.mail import FakeMailbox

NOW = datetime.now(UTC)
OURS = "aksh@starthreads.in"


@pytest.fixture
def sent(store):
    """Two contacts, one email sent to each."""
    store.add_campaign(Campaign(id="rfd", name="rfd", created_at=NOW))
    ids = {}
    for n, (company, email) in enumerate(
        [("Sunrise Knits", "buyer@sunrise.example"), ("Lotus Mills", "info@lotus.example")]
    ):
        contact_id = store.add_contact(Contact(campaign_id="rfd", email=email, company=company))
        send_message(
            store=store,
            mailbox=FakeMailbox(),
            contact_id=contact_id,
            to=email,
            subject="RFD cotton sewing thread from Ludhiana",
            body_text="Hello, we make RFD thread.",
            message_id=f"<m{n}@starthreads.in>",
        )
        ids[email] = contact_id
    return ids


def _reply(from_address, body, *, subject="Re: RFD cotton sewing thread from Ludhiana", **kw):
    return InboundMessage(
        message_id=kw.pop("message_id", f"<r{abs(hash(body))}@their.example>"),
        from_address=from_address,
        subject=subject,
        body_text=body,
        received_at=kw.pop("received_at", NOW + timedelta(hours=1)),
        **kw,
    )


def _reading(category, **kw):
    return ReplyReading(
        category=category,
        summary=kw.pop("summary", "summary"),
        postal_address=kw.pop("postal_address", None),
        contact_person=kw.pop("contact_person", None),
        phone=kw.pop("phone", None),
        suggested_reply=kw.pop("suggested_reply", "Thank you.\n\nWarm regards,\nAksh Goyal"),
    )


def _check(store, inbox, *readings):
    llm = FakeLLM(list(readings))
    result = check_replies(
        store,
        FakeMailbox(replies=inbox),
        llm,
        own_address=OURS,
        offer_for=lambda cid: "We make RFD thread.",
        sender="Aksh Goyal",
        sender_company="Star Threads",
    )
    return result, llm


# --- matching ---------------------------------------------------------------


def test_a_reply_in_the_thread_is_matched_and_read(store, sent):
    body = "Yes please send samples.\nAddress: Plot 4, Tiruppur 641604\nAsk for R. Kumar"
    reply = _reply("buyer@sunrise.example", body, in_reply_to="<m0@starthreads.in>")
    result, _ = _check(
        store,
        [reply],
        _reading(
            "wants_samples",
            postal_address="Plot 4, Tiruppur 641604",
            contact_person="R. Kumar",
            phone="+91 99999 00000",  # not in the reply: must be dropped
        ),
    )
    assert result.new == 1
    [stored] = store.list_replies()
    assert stored.company == "Sunrise Knits"
    assert stored.matched_by == "thread"
    assert stored.category == "wants_samples"
    assert stored.details == {
        "postal_address": "Plot 4, Tiruppur 641604",
        "contact_person": "R. Kumar",
    }
    assert not store.is_suppressed("buyer@sunrise.example")


def test_a_reply_without_thread_headers_is_matched_by_address(store, sent):
    _check(store, [_reply("info@lotus.example", "Tell me more.")], _reading("question"))
    [stored] = store.list_replies()
    assert stored.company == "Lotus Mills" and stored.matched_by == "address"


def test_ordinary_inbox_mail_is_not_stored(store, sent):
    newsletter = _reply("news@shop.example", "50% off!", subject="Big sale")
    result, llm = _check(store, [newsletter])
    assert result.ignored == 1
    assert store.list_replies() == []
    assert llm.prompts == [], "nothing unrelated is sent to the model"


def test_a_colleague_replying_is_kept_but_nobody_is_suppressed(store, sent):
    colleague = _reply("owner@sunrise.example", "Not interested, thanks.")
    result, _ = _check(store, [colleague], _reading("not_interested"))
    [stored] = store.list_replies()
    assert stored.contact_id is None and stored.matched_by == "subject"
    assert result.suppressed == []
    assert "Add the address yourself" in stored.action


def test_our_own_sent_copies_are_skipped(store, sent):
    result, _ = _check(store, [_reply(OURS, "copy", in_reply_to="<m0@starthreads.in>")])
    assert result.new == 0 and store.list_replies() == []


def test_checking_twice_stores_each_reply_once(store, sent):
    reply = _reply("info@lotus.example", "Price list?")
    _check(store, [reply], _reading("question"))
    _check(store, [reply])
    assert len(store.list_replies()) == 1


def test_nothing_is_read_before_anything_was_sent(store):
    result, _ = _check(store, [_reply("x@y.example", "hi")])
    assert result.new == 0 and result.ignored == 0


# --- acting safely ----------------------------------------------------------


def test_not_interested_goes_on_the_do_not_contact_list(store, sent):
    reply = _reply("buyer@sunrise.example", "Please remove us.", in_reply_to="<m0@starthreads.in>")
    result, _ = _check(store, [reply], _reading("not_interested", summary="Asked to be removed"))
    assert result.suppressed == ["buyer@sunrise.example"]
    assert store.is_suppressed("buyer@sunrise.example")
    assert store.list_replies()[0].status is ReplyStatus.DONE, "nothing left to do"
    with pytest.raises(SuppressedRecipientError):
        send_message(
            store=store,
            mailbox=FakeMailbox(),
            contact_id=sent["buyer@sunrise.example"],
            to="buyer@sunrise.example",
            subject="again",
            body_text="again",
            message_id="<again@starthreads.in>",
        )


def test_a_hard_bounce_is_suppressed_without_asking_the_model(store, sent):
    bounce = _reply(
        "MAILER-DAEMON@mx.zoho.in",
        "Delivery failed.\nStatus: 5.1.1 user unknown\nMessage-ID: <m1@starthreads.in>",
        subject="Undelivered Mail Returned to Sender",
    )
    result, llm = _check(store, [bounce])
    assert store.is_suppressed("info@lotus.example")
    assert llm.prompts == []
    [stored] = store.list_replies()
    assert stored.category == "bounce" and stored.company == "Lotus Mills"


def test_a_delayed_delivery_does_not_cost_a_lead(store, sent):
    delay = _reply(
        "postmaster@their.example",
        "Delivery to info@lotus.example delayed. Status: 4.2.2 mailbox full. Will retry.",
        subject="Delivery Status Notification (Delay)",
    )
    _check(store, [delay])
    assert not store.is_suppressed("info@lotus.example")


def test_an_out_of_office_is_never_read_as_an_answer(store, sent):
    away = _reply("info@lotus.example", "I am away until Monday.", auto_submitted=True)
    result, llm = _check(store, [away])
    assert llm.prompts == []
    assert store.list_replies()[0].category == "out_of_office"
    assert not store.is_suppressed("info@lotus.example")


def test_a_reply_the_model_cannot_read_is_kept_and_tried_again(store, sent):
    reply = _reply("info@lotus.example", "Send price list please.")
    result, _ = _check(store, [reply])  # the fake model has nothing queued: it fails
    assert result.unread == 1
    assert store.list_replies()[0].category == "unread"

    _check(store, [reply], _reading("interested"))
    assert store.list_replies()[0].category == "interested"


# --- the reply text ---------------------------------------------------------


def test_the_quoted_email_is_cut_off_before_reading():
    body = (
        "Yes, send samples.\n\nOn Thu, 25 Sep 2026 at 10:02, Aksh Goyal <aksh@x.in> wrote:\n"
        "> Hello, we make RFD thread.\n> We would be pleased to send a sample."
    )
    assert new_part(body) == "Yes, send samples."


# --- answering --------------------------------------------------------------


def test_an_answer_goes_in_the_same_thread_and_marks_it_handled(store, sent):
    reply = _reply("buyer@sunrise.example", "Samples please.", in_reply_to="<m0@starthreads.in>")
    _check(store, [reply], _reading("wants_samples"))
    stored = store.list_replies()[0]
    box = FakeMailbox()
    send_reply(store, box, stored, body="We'll dispatch them.", message_id="<a1@starthreads.in>")
    [message] = box.sent
    assert message.in_reply_to == reply.message_id
    assert message.subject == "Re: RFD cotton sewing thread from Ludhiana"
    assert message.to == "buyer@sunrise.example"
    assert store.get_reply(stored.id).status is ReplyStatus.DONE


def test_nobody_on_the_do_not_contact_list_can_be_answered(store, sent):
    reply = _reply("buyer@sunrise.example", "Remove us.", in_reply_to="<m0@starthreads.in>")
    _check(store, [reply], _reading("not_interested"))
    with pytest.raises(SuppressedRecipientError):
        send_reply(
            store, FakeMailbox(), store.list_replies()[0], body="Sorry!", message_id="<a2@x.in>"
        )


def test_an_unmatched_reply_is_answered_from_zoho_instead(store, sent):
    _check(store, [_reply("owner@sunrise.example", "Who are you?")], _reading("question"))
    with pytest.raises(CannotReplyError):
        send_reply(store, FakeMailbox(), store.list_replies()[0], body="Hi", message_id="<a3@x.in>")


def test_concurrent_answer_requests_send_only_one_email(store, sent):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from outreach.adapters.db import connect
    from outreach.adapters.store_sqlite import SqliteStore

    _check(
        store,
        [_reply("buyer@sunrise.example", "Hello", in_reply_to="<m0@starthreads.in>")],
        _reading("interested"),
    )
    reply = store.list_replies()[0]
    path = store._conn.execute("PRAGMA database_list").fetchone()["file"]
    entered, release = threading.Event(), threading.Event()

    class SlowMailbox(FakeMailbox):
        def send(self, message):
            entered.set()
            assert release.wait(5)
            return super().send(message)

    box = SlowMailbox()

    def answer(message_id):
        db = SqliteStore(connect(path))
        try:
            send_reply(db, box, reply, body="Thank you.", message_id=message_id)
        finally:
            db._conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(answer, "<first@sender.example>")
        try:
            assert entered.wait(5)
            second = pool.submit(answer, "<second@sender.example>")
            with pytest.raises(CannotReplyError, match="already sent or its outcome is uncertain"):
                second.result(timeout=5)
        finally:
            release.set()
        first.result(timeout=5)
    assert len(box.sent) == 1


def test_reply_respects_global_daily_cap_and_can_retry_known_failure(store, sent):
    from outreach.ports.mail import MailError

    _check(
        store,
        [_reply("buyer@sunrise.example", "Hello", in_reply_to="<m0@starthreads.in>")],
        _reading("interested"),
    )
    reply = store.list_replies()[0]
    box = FakeMailbox()
    with pytest.raises(CannotReplyError, match="limit"):
        send_reply(
            store, box, reply, body="Thank you.", message_id="<capped@sender.example>", daily_cap=2
        )
    box.fail_next = MailError("Provider refused the message")
    with pytest.raises(MailError):
        send_reply(
            store, box, reply, body="Thank you.", message_id="<failed@sender.example>", daily_cap=3
        )
    send_reply(
        store, box, reply, body="Thank you.", message_id="<retried@sender.example>", daily_cap=3
    )
    assert len(box.sent) == 1 and store.sent_today() == 3
