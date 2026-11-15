"""`outreach send-test` — the second way to send, and why it cannot reach a
prospect."""

from datetime import UTC, datetime

import pytest

from outreach.core.models import Campaign, Contact, SuppressionReason
from outreach.core.sending import NotATestAddressError, SuppressedRecipientError, send_test
from tests.fakes.mail import FakeMailbox


def _send(store, mailbox, to="me@personal.example"):
    return send_test(
        store=store,
        mailbox=mailbox,
        to=to,
        subject="Checking the tool",
        body_text="Hello.\n\n--\nAksh Goyal",
        message_id="<t@starthreads.in>",
    )


def test_a_test_email_goes_to_you(store):
    mailbox = FakeMailbox()
    _send(store, mailbox)
    assert [m.to for m in mailbox.sent] == ["me@personal.example"]


def test_the_subject_is_marked_as_a_test(store):
    mailbox = FakeMailbox()
    _send(store, mailbox)
    assert mailbox.sent[0].subject.startswith("[TEST]")


def test_it_cannot_reach_a_prospect(store):
    """Otherwise it would be a way around 'one email per contact, reviewed
    first'."""
    store.add_campaign(Campaign(id="c", name="c", created_at=datetime.now(UTC)))
    store.add_contact(Contact(campaign_id="c", email="Buyer@Mill.example"))
    mailbox = FakeMailbox()
    with pytest.raises(NotATestAddressError):
        _send(store, mailbox, to="buyer@mill.example")
    assert mailbox.sent == []


def test_it_cannot_reach_anyone_who_opted_out(store):
    store.add_suppression("me@personal.example", SuppressionReason.UNSUBSCRIBE)
    mailbox = FakeMailbox()
    with pytest.raises(SuppressedRecipientError):
        _send(store, mailbox)
    assert mailbox.sent == []


def test_it_leaves_no_trace(store):
    """A test must not count against the daily cap or mark anyone as written
    to — you may need to run it several times while fixing DNS."""
    _send(store, FakeMailbox())
    _send(store, FakeMailbox())
    assert store._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert store.sent_today() == 0


# --- the message when the draft number is wrong ------------------------------


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    import os

    for name in list(os.environ):
        if name.startswith("OUTREACH_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    for name, value in {
        "DB_PATH": str(tmp_path / "x.db"),
        "MAIL_SMTP_HOST": "smtp.test.invalid",
        "MAIL_USERNAME": "aksh@example.com",
        "MAIL_PASSWORD": "pw",
        "SENDER_NAME": "Aksh Goyal",
        "SENDER_EMAIL": "aksh@example.com",
        "SENDER_COMPANY": "Star Threads",
        "SENDER_ADDRESS": "Ludhiana",
    }.items():
        monkeypatch.setenv(f"OUTREACH_{name}", value)
    return tmp_path


def test_with_no_drafts_at_all_it_says_how_to_make_one(cli_env, capsys):
    """What actually happened on the first real try: --draft 1 before any
    drafts had been saved. 'No draft with id 1' did not say what to do."""
    from outreach.cli import main

    assert main(["send-test", "--to", "me@personal.example", "--draft", "1"]) == 1
    err = capsys.readouterr().err
    assert "no saved drafts at all" in err
    assert "draft --campaign" in err and "--save" in err
    assert "leave --draft off" in err


def test_with_drafts_it_lists_the_numbers_that_exist(cli_env, capsys):
    from outreach.adapters.db import connect
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.cli import main

    store = SqliteStore(connect(cli_env / "x.db"))
    store.add_campaign(Campaign(id="rfd", name="rfd", created_at=datetime.now(UTC)))
    cid = store.add_contact(Contact(campaign_id="rfd", email="b@mill.example", company="Mill"))
    real = store.save_draft(
        contact_id=cid, model="m", subject="s", body="b", verdict="clean", checks=[]
    )

    assert main(["send-test", "--to", "me@personal.example", "--draft", "999"]) == 1
    err = capsys.readouterr().err
    assert f"{real}" in err and "Mill" in err
