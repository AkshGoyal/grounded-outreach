"""The Zoho inbox reader: parsing raw mail, and reading without changing anything."""

from datetime import UTC, datetime

import pytest

from outreach.adapters.mail_smtp_imap import SmtpImapMailbox, parse_message
from outreach.ports.mail import MailAuthError

REPLY = b"""From: "R. Kumar" <Buyer@Sunrise.example>
To: aksh@starthreads.in
Subject: Re: RFD cotton sewing thread from Ludhiana
Date: Fri, 26 Sep 2026 10:15:00 +0530
Message-ID: <reply-1@sunrise.example>
In-Reply-To: <m0@starthreads.in>
References: <m0@starthreads.in>
Content-Type: text/plain; charset=utf-8

Yes, please send samples.
"""

AWAY = b"""From: info@lotus.example
Subject: Out of office
Date: Fri, 26 Sep 2026 10:15:00 +0000
Message-ID: <away-1@lotus.example>
Auto-Submitted: auto-replied
Content-Type: text/plain

I am away.
"""

BOUNCE = b"""From: MAILER-DAEMON@mx.zoho.in
Subject: Undelivered Mail Returned to Sender
Date: Fri, 26 Sep 2026 10:15:00 +0000
Message-ID: <bounce-1@mx.zoho.in>
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="B"

--B
Content-Type: text/plain

The mail could not be delivered.
--B
Content-Type: message/delivery-status

Status: 5.1.1

--B
Content-Type: text/rfc822-headers

Message-ID: <m1@starthreads.in>
To: info@lotus.example
--B--
"""


def test_a_reply_is_parsed_with_its_thread_headers():
    message = parse_message(REPLY)
    assert message.from_address == "buyer@sunrise.example"
    assert message.in_reply_to == "<m0@starthreads.in>"
    assert message.references == ["<m0@starthreads.in>"]
    assert message.body_text.strip() == "Yes, please send samples."
    assert message.received_at.utcoffset() is not None
    assert not message.auto_submitted


def test_an_automatic_reply_is_flagged():
    assert parse_message(AWAY).auto_submitted


def test_a_bounce_keeps_the_returned_headers_that_name_our_email():
    message = parse_message(BOUNCE)
    assert "<m1@starthreads.in>" in message.body_text
    assert "5.1.1" in message.body_text


def test_a_message_without_an_id_gets_the_same_stand_in_every_time():
    raw = REPLY.replace(b"Message-ID: <reply-1@sunrise.example>\n", b"")
    assert parse_message(raw).message_id == parse_message(raw).message_id


def _ready(settings, **update):
    return settings.model_copy(
        update={"sender_company": "Example Threads", "sender_address": "Ludhiana", **update}
    )


class FakeImap:
    """Records every command, so the test can prove nothing changes the inbox."""

    calls: list = []

    def __init__(self, host, port, timeout=None, ssl_context=None):
        self.ssl_context = ssl_context
        FakeImap.calls = [("connect", host, port)]

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"2"]

    def search(self, charset, criteria):
        self.calls.append(("search", criteria))
        return "OK", [b"1 2"]

    def fetch(self, number, what):
        self.calls.append(("fetch", number, what))
        return "OK", [(b"1 (BODY[] {100}", REPLY if number == b"1" else AWAY), b")"]

    def logout(self):
        self.calls.append(("logout",))


def test_the_inbox_is_read_without_changing_anything(settings, monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", FakeImap)
    box = SmtpImapMailbox(_ready(settings, mail_imap_host="imappro.zoho.in"))
    messages = box.fetch_replies(since=datetime(2026, 9, 24, tzinfo=UTC))

    assert [m.message_id for m in messages] == [
        "<reply-1@sunrise.example>",
        "<away-1@lotus.example>",
    ]
    assert ("select", "INBOX", True) in FakeImap.calls, "opened read-only"
    assert ("search", '(SINCE "24-Sep-2026")') in FakeImap.calls
    fetches = [c for c in FakeImap.calls if c[0] == "fetch"]
    assert fetches and all(c[2] == "(BODY.PEEK[])" for c in fetches), "PEEK leaves mail unread"
    commands = {c[0] for c in FakeImap.calls}
    assert commands <= {"connect", "login", "select", "search", "fetch", "logout"}, (
        "no store, copy, move, delete or expunge"
    )


def test_a_missing_inbox_server_is_explained(settings):
    box = SmtpImapMailbox(_ready(settings, mail_imap_host=None))
    with pytest.raises(MailAuthError, match="imappro.zoho.in"):
        box.fetch_replies()
