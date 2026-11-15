"""Running the whole loop from the browser: texts, setup, test email, sending.

A fake mailbox stands in for Zoho, so nothing here touches the network.
"""

import pathlib
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from outreach.core.drafting import Draft, DraftSentence
from outreach.web.app import create_app
from tests.fakes.llm import FakeLLM
from tests.fakes.mail import FakeMailbox
from tests.helpers import confirm_draft_test, confirm_launch

FIXTURE = pathlib.Path("tests/fixtures/sample_contacts.csv").resolve()


@pytest.fixture
def box():
    return FakeMailbox()


def _app(settings, box, tmp_path, monkeypatch, **overrides):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "campaigns").mkdir(exist_ok=True)
    (tmp_path / "campaigns" / "rfd.md").write_text(
        "Star Threads makes RFD cotton thread in Ludhiana. We send free samples."
    )
    ready = settings.model_copy(
        update={
            "sender_name": "Aksh Goyal",
            "sender_email": "aksh@starthreads.in",
            "sender_company": "Star Threads Private Limited",
            "sender_address": "Tajpur Road, Ludhiana",
            "send_gap_seconds": 0,
            "openrouter_api_key": "sk-or-test",
            **overrides,
        }
    )
    client = TestClient(create_app(ready, mailbox=lambda s: box))
    with open(FIXTURE, "rb") as handle:
        client.post(
            "/import",
            files={"file": ("c.csv", handle, "text/csv")},
            data={"campaign": "rfd", "sheet": "", "email_column": "", "commit": "1"},
        )
    draft = Draft(
        subject="RFD cotton thread sample",
        sentences=[DraftSentence(text="Hello."), DraftSentence(text="We make RFD cotton thread.")],
    )
    monkeypatch.setattr(
        "outreach.web.app.build_llm", lambda s, m=None: FakeLLM(responses=[draft] * 20)
    )
    client.post("/campaigns/rfd/draft")
    return client


@pytest.fixture
def web(settings, box, tmp_path, monkeypatch):
    return _app(settings, box, tmp_path, monkeypatch)


def _wait_until_finished(web, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        page = web.get("/sending").text
        if "Open campaign" in page:
            return page
        time.sleep(0.05)
    raise AssertionError("sending did not finish")


# --- sending from the browser -------------------------------------------------


def test_the_send_button_sends_every_approved_draft_once(web, box):
    web.post("/campaigns/rfd/approve-all")
    confirm_launch(web, "/campaigns/rfd/send")
    page = _wait_until_finished(web)
    assert "Done." in page
    assert len(box.sent) >= 2
    sent_to = [m.to for m in box.sent]
    assert len(sent_to) == len(set(sent_to))

    # Pressing Send again sends nobody a second email.
    confirm_launch(web, "/campaigns/rfd/send")
    time.sleep(0.2)
    assert [m.to for m in box.sent] == sent_to


def test_stop_takes_effect_between_emails(settings, box, tmp_path, monkeypatch):
    web = _app(settings, box, tmp_path, monkeypatch, send_gap_seconds=30)
    web.post("/campaigns/rfd/approve-all")
    confirm_launch(web, "/campaigns/rfd/send")
    deadline = time.time() + 5
    while not box.sent and time.time() < deadline:
        time.sleep(0.05)
    assert "Stop after this email" in web.get("/sending").text

    confirm_launch(web, "/sending/stop")
    page = _wait_until_finished(web)
    assert "Stopped." in page
    assert len(box.sent) == 1, "the 30-second wait ended at Stop, and nothing more went"


def test_nothing_sends_until_setup_is_complete(settings, box, tmp_path, monkeypatch):
    web = _app(settings, box, tmp_path, monkeypatch, mail_password=None)
    web.post("/campaigns/rfd/approve-all")
    page = confirm_launch(web, "/campaigns/rfd/send", follow_redirects=True).text
    assert "set up yet" in page
    assert box.sent == []


def test_the_send_button_asks_for_confirmation(web):
    web.post("/campaigns/rfd/approve-all")
    page = web.get("/campaigns/rfd/send").text
    assert "confirm(" in page and "to real people" in page


# --- a test email to yourself ------------------------------------------------


def _first_draft(web):
    import re

    return int(re.search(r'href="/drafts/(\d+)"', web.get("/campaigns/rfd/drafts").text).group(1))


def test_a_test_email_goes_to_you_marked_test(web, box):
    page = confirm_draft_test(web, _first_draft(web), "aksh@starthreads.in").text
    assert "marked [TEST]" in page
    [message] = box.sent
    assert message.to == "aksh@starthreads.in"
    assert message.subject.startswith("[TEST]")
    assert "Tajpur Road" in message.body_text
    assert "0 sent" in web.get("/").text.replace("<strong>", "").replace("</strong>", "")


def test_a_test_email_cannot_go_to_a_prospect(web, box):
    page = confirm_draft_test(web, _first_draft(web), "buying@meridiantex.example").text
    assert "Not sent" in page
    assert box.sent == []


def test_a_test_email_is_refused_while_the_draft_repeats_the_ending(web, box, tmp_path):
    (tmp_path / "campaigns" / "rfd.closing.md").write_text("Warm regards,\n\nAksh Goyal")
    draft_id = _first_draft(web)
    web.post(
        f"/drafts/{draft_id}",
        data={"subject": "RFD thread", "body": "Hello.\n\nBest regards, Aksh", "action": "save"},
    )
    page = confirm_draft_test(web, draft_id, "aksh@starthreads.in").text
    assert "repeat" in page
    assert box.sent == []


# --- the campaign's texts ----------------------------------------------------


def test_the_offer_and_ending_are_edited_in_the_browser(web, tmp_path):
    page = web.post(
        "/campaigns/rfd/texts",
        data={"offer": "We make RFD thread.", "closing": "Warm regards,\n\nAksh"},
        follow_redirects=True,
    ).text
    assert "Saved." in page
    assert (tmp_path / "campaigns" / "rfd.md").read_text() == "We make RFD thread.\n"
    assert (tmp_path / "campaigns" / "rfd.closing.md").read_text() == "Warm regards,\n\nAksh\n"

    web.post("/campaigns/rfd/texts", data={"offer": "We make RFD thread.", "closing": "  "})
    assert not (tmp_path / "campaigns" / "rfd.closing.md").exists(), (
        "an empty ending switches back to full-email drafting"
    )


def test_an_empty_offer_is_refused(web, tmp_path):
    page = web.post("/campaigns/rfd/texts", data={"offer": " ", "closing": ""}).text
    assert "Describe what you are offering" in page
    assert "free samples" in (tmp_path / "campaigns" / "rfd.md").read_text()


def test_a_campaign_name_cannot_write_outside_the_campaigns_folder(web, tmp_path):
    from outreach.campaigns import save_texts

    for bad in ("../escape", "..", "a/b", "Has Spaces", ""):
        with pytest.raises(ValueError):
            save_texts(bad, copy="x", closing="")
    page = web.post("/campaigns/Has Spaces/texts", data={"offer": "x", "closing": ""}).text
    assert "Not a usable campaign id" in page
    assert sorted(p.name for p in (tmp_path / "campaigns").iterdir()) == ["rfd.md"]
    assert web.post("/campaigns/..%2Fescape/texts", data={"offer": "x"}).status_code == 404


# --- setup and the dashboard -------------------------------------------------


def test_setup_shows_what_is_missing_without_showing_secrets(settings, box, tmp_path, monkeypatch):
    web = _app(settings, box, tmp_path, monkeypatch, mail_password=None)
    page = web.get("/setup").text
    assert "Research services" in page and "Gmail & Zoho" in page
    assert "Needs a key" in page
    assert "sk-or-test" not in page
    assert "Free · No research or emails yet" in web.get("/").text


def test_the_zoho_check_sends_nothing(web, box):
    page = web.post("/setup/mail", follow_redirects=True).text
    assert "Nothing was sent" in page
    assert box.sent == []


def test_the_dashboard_points_at_the_next_step(web):
    page = web.get("/").text
    assert "Review" in page and "/campaigns/rfd/drafts" in page
    web.post("/campaigns/rfd/approve-all")
    assert "approved →" in web.get("/").text


# --- the inbox ---------------------------------------------------------------


def test_a_reply_arrives_is_read_and_answered_from_the_browser(
    settings, box, tmp_path, monkeypatch
):
    from outreach.core.models import InboundMessage
    from outreach.core.replies import ReplyReading

    web = _app(settings, box, tmp_path, monkeypatch, mail_imap_host="imappro.zoho.in")
    web.post("/campaigns/rfd/approve-all")
    confirm_launch(web, "/campaigns/rfd/send")
    _wait_until_finished(web)
    first = box.sent[0]

    box._replies = [
        InboundMessage(
            message_id="<their-reply@buyer.example>",
            from_address=first.to,
            subject=f"Re: {first.subject}",
            body_text="Yes, send samples to Plot 4, Tiruppur.",
            received_at=datetime.now(UTC) + timedelta(minutes=5),
            in_reply_to=first.message_id,
        )
    ]
    reading = ReplyReading(
        category="wants_samples",
        summary="Wants samples",
        postal_address="Plot 4, Tiruppur",
        contact_person=None,
        phone=None,
        suggested_reply="Thank you — we'll dispatch this week.\n\nWarm regards,\nAksh Goyal",
    )
    monkeypatch.setattr("outreach.web.app.build_llm", lambda s, m=None: FakeLLM([reading]))

    page = web.post("/inbox/check", follow_redirects=True).text
    assert "1 new reply" in page and "Wants samples" in page
    assert "1 reply" in web.get("/").text  # the dashboard says so too

    import re

    reply_id = int(re.search(r'href="/replies/(\d+)"', page).group(1))
    detail = web.get(f"/replies/{reply_id}").text
    assert "Plot 4, Tiruppur" in detail and "we&#39;ll dispatch" in detail

    before = len(box.sent)
    web.post(f"/replies/{reply_id}/send", data={"body": "Dispatching today."})
    answer = box.sent[before]
    assert answer.to == first.to and answer.in_reply_to == "<their-reply@buyer.example>"
    assert "Nothing to handle" in web.get("/inbox").text


def test_the_inbox_explains_what_is_missing(settings, box, tmp_path, monkeypatch):
    web = _app(settings, box, tmp_path, monkeypatch, mail_imap_host=None)
    page = web.get("/inbox").text
    assert "Connect and verify an email account" in page
    assert 'href="/accounts"' in page
