"""The fakes must satisfy the ports, and the ports must stay provider-free."""

from datetime import UTC, datetime

import pytest

from outreach.core.models import InboundMessage, OutboundMessage
from outreach.ports.llm import LLMError, LLMPort
from outreach.ports.mail import MailPort
from tests.fakes.llm import FakeLLM
from tests.fakes.mail import FakeMailbox


def _message(to: str = "buyer@example.com") -> OutboundMessage:
    return OutboundMessage(
        to=to,
        subject="RFD cotton thread — sample offer",
        body_text="Hello, ...",
        message_id="<test-1@starthreads.in>",
    )


def test_fake_mailbox_satisfies_mail_port():
    assert isinstance(FakeMailbox(), MailPort)


def test_fake_llm_satisfies_llm_port():
    assert isinstance(FakeLLM(), LLMPort)


def test_send_records_instead_of_sending():
    mailbox = FakeMailbox()
    sent = mailbox.send(_message())

    assert mailbox.sent == [_message()]
    assert sent.message_id == "<test-1@starthreads.in>"
    assert sent.sent_at.tzinfo is not None, "timestamps must be timezone-aware"


def test_send_failure_propagates():
    """A failed send must raise, never silently report success."""
    mailbox = FakeMailbox()
    mailbox.fail_next = ConnectionError("smtp unreachable")

    with pytest.raises(ConnectionError):
        mailbox.send(_message())

    assert mailbox.sent == []


def test_fetch_replies_filters_by_time():
    cutoff = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    older = InboundMessage(
        message_id="<a@x.example.com>",
        from_address="buyer@example.com",
        subject="Re: sample",
        body_text="earlier",
        received_at=datetime(2026, 9, 19, 11, 0, tzinfo=UTC),
    )
    newer = older.model_copy(
        update={
            "message_id": "<b@x.example.com>",
            "received_at": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        }
    )
    mailbox = FakeMailbox(replies=[older, newer])

    assert mailbox.fetch_replies() == [older, newer]
    assert mailbox.fetch_replies(since=cutoff) == [newer]


def test_llm_returns_validated_schema_instance():
    from pydantic import BaseModel

    class Draft(BaseModel):
        subject: str
        body: str

    llm = FakeLLM(responses=[Draft(subject="s", body="b")])
    result = llm.generate(prompt="write it", schema=Draft)

    assert isinstance(result, Draft)
    assert llm.prompts == ["write it"]


def test_llm_rejects_wrong_schema():
    """Returning the wrong shape is an error, not something to paper over."""
    from pydantic import BaseModel

    class Draft(BaseModel):
        subject: str

    class Classification(BaseModel):
        label: str

    llm = FakeLLM(responses=[Classification(label="interested")])
    with pytest.raises(LLMError):
        llm.generate(prompt="x", schema=Draft)
