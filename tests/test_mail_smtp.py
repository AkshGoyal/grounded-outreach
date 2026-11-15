"""The Zoho adapter, against a fake SMTP server. Nothing here touches the
network — a real send would email a real person."""

import smtplib

import pytest

from outreach.adapters.mail_smtp_imap import SmtpImapMailbox
from outreach.core.models import OutboundMessage
from outreach.ports.mail import MailAuthError, MailError


@pytest.fixture
def mailbox(settings):
    ready = settings.model_copy(
        update={
            "sender_name": "Aksh Goyal",
            "sender_email": "aksh@starthreads.in",
            "sender_company": "Star Threads Private Limited",
            "sender_address": "Tajpur Road, Ludhiana",
            "mail_smtp_host": "smtp.test.invalid",
            "mail_smtp_port": 465,
        }
    )
    return SmtpImapMailbox(ready)


def _message():
    return OutboundMessage(
        to="buyer@example.com",
        subject="RFD cotton thread sample",
        body_text="Hello.\n\nWe make thread.",
        message_id="<abc@starthreads.in>",
    )


class FakeSMTP:
    instances: list = []
    fail_login = False
    refuse = False

    def __init__(self, host, port, timeout=None, context=None):
        self.context = context
        self.host, self.port, self.sent, self.closed = host, port, [], False
        FakeSMTP.instances.append(self)

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        if FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({"buyer@example.com": (550, b"no such user")})
        self.sent.append(msg)

    def quit(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_login, FakeSMTP.refuse = [], False, False
    monkeypatch.setattr("outreach.adapters.mail_smtp_imap.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_the_email_has_the_headers_that_matter(mailbox):
    built = mailbox.build(_message())
    assert built["From"] == "Aksh Goyal <aksh@starthreads.in>"
    assert built["To"] == "buyer@example.com"
    assert built["Message-ID"] == "<abc@starthreads.in>"
    assert built["Date"]


def test_there_is_no_mailing_list_header(mailbox):
    """On the first real test, a one-to-one email landed in Gmail's
    Promotions tab. List-Unsubscribe is what mailing lists carry, and Gmail
    reads it as bulk mail. It is only required above 5,000 emails a day."""
    built = mailbox.build(_message())
    assert built["List-Unsubscribe"] is None
    assert built["Precedence"] is None


def test_the_email_is_plain_text(mailbox):
    """HTML, images and tracking are what marketing email looks like."""
    built = mailbox.build(_message())
    assert built.get_content_type() == "text/plain"
    assert not built.is_multipart()


def test_a_send_goes_through_and_the_connection_is_closed(mailbox, fake_smtp):
    sent = mailbox.send(_message())
    assert sent.message_id == "<abc@starthreads.in>"
    [server] = fake_smtp.instances
    assert len(server.sent) == 1 and server.closed


def test_a_refused_login_says_what_to_do(mailbox, fake_smtp):
    fake_smtp.fail_login = True
    with pytest.raises(MailAuthError, match="app-specific password"):
        mailbox.send(_message())


def test_a_refused_address_is_a_per_message_failure(mailbox, fake_smtp):
    fake_smtp.refuse = True
    with pytest.raises(MailError) as exc:
        mailbox.send(_message())
    assert not isinstance(exc.value, MailAuthError), "one bad address must not stop the run"


def test_verify_login_sends_nothing(mailbox, fake_smtp):
    mailbox.verify_login()
    [server] = fake_smtp.instances
    assert server.sent == [] and server.closed


def test_it_refuses_to_exist_without_a_physical_address(settings):
    from outreach.config import ConfigError

    with pytest.raises(ConfigError, match="OUTREACH_SENDER_ADDRESS"):
        SmtpImapMailbox(settings.model_copy(update={"sender_address": None}))
