"""The review screen: where a person reads, edits, approves or rejects.

These drive the web pages end to end with a fake model, so nothing here calls
a real model or sends anything.
"""

import pytest
from fastapi.testclient import TestClient

from outreach.core.drafting import Draft, DraftSentence
from outreach.web.app import create_app
from tests.fakes.llm import FakeLLM

FIXTURE = "tests/fixtures/sample_contacts.csv"


@pytest.fixture
def web(settings, monkeypatch, tmp_path):
    """A web app with one imported campaign, campaign copy, and a fake model."""
    import pathlib

    fixture = pathlib.Path(FIXTURE).resolve()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "rfd.md").write_text(
        "Star Threads makes RFD cotton thread in Ludhiana. We send free samples."
    )
    ready = settings.model_copy(
        update={
            "openrouter_api_key": "sk-or-test",
            "sender_name": "Aksh Goyal",
            "sender_email": "aksh@starthreads.in",
            "sender_company": "Star Threads Private Limited",
            "sender_address": "Tajpur Road, Ludhiana",
        }
    )
    client = TestClient(create_app(ready))
    with open(fixture, "rb") as handle:
        client.post(
            "/import",
            files={"file": ("c.csv", handle, "text/csv")},
            data={"campaign": "rfd", "sheet": "", "email_column": "", "commit": "1"},
        )
    return client


def _model(monkeypatch, *sentences, subject="RFD cotton thread sample"):
    draft = Draft(subject=subject, sentences=[DraftSentence(text=t, cites=c) for t, c in sentences])
    monkeypatch.setattr(
        "outreach.web.app.build_llm", lambda s, m=None: FakeLLM(responses=[draft] * 20)
    )


def _first_draft_id(web):
    import re

    page = web.get("/campaigns/rfd/drafts").text
    return int(re.search(r'href="/drafts/(\d+)"', page).group(1))


# --- writing drafts ---------------------------------------------------------


def test_drafts_can_be_written_from_the_page(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None), ("We make RFD cotton thread in Ludhiana.", None))
    page = web.post("/campaigns/rfd/draft", follow_redirects=True).text
    assert "Drafts written" in page
    assert "Kohinoor Knits" in page


def test_without_campaign_copy_it_explains_instead_of_drafting(web, monkeypatch, tmp_path):
    (tmp_path / "campaigns" / "rfd.md").unlink()
    _model(monkeypatch, ("Hello.", None))
    page = web.post("/campaigns/rfd/draft", follow_redirects=True).text
    assert "no campaign copy" in page.lower()


# --- reviewing --------------------------------------------------------------


def test_an_invented_line_is_shown_as_removed_not_as_sendable(web, monkeypatch):
    _model(
        monkeypatch,
        ("Hello.", None),
        ("I saw your Coimbatore unit.", "City"),
    )
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    page = web.get(f"/drafts/{draft_id}").text
    assert "Removed" in page
    textarea = page.split("<textarea")[1].split("</textarea>")[0]
    assert "Coimbatore" not in textarea, "it must not be in the text that would be sent"


def test_a_clean_draft_can_be_approved(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None), ("We make RFD cotton thread in Ludhiana.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    page = web.post(
        f"/drafts/{draft_id}",
        data={"subject": "RFD cotton thread sample", "body": "Hello.", "action": "approve"},
        follow_redirects=True,
    ).text
    assert "approved" in page


def test_an_invented_claim_typed_in_review_cannot_be_approved(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    page = web.post(
        f"/drafts/{draft_id}",
        data={
            "subject": "RFD cotton thread sample",
            "body": "Hello.\n\nWe met at your Coimbatore office.",
            "action": "approve",
        },
    ).text
    assert "cannot back up" in page
    assert "coimbatore" in page.lower()


def test_saving_an_edit_keeps_it_and_rechecks_it(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    web.post(
        f"/drafts/{draft_id}",
        data={"subject": "A new subject", "body": "Hello again.", "action": "save"},
    )
    page = web.get(f"/drafts/{draft_id}").text
    assert "A new subject" in page and "Hello again." in page


def test_a_draft_can_be_rejected(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    page = web.post(f"/drafts/{draft_id}", data={"action": "reject"}, follow_redirects=True).text
    assert "rejected" in page


# --- what would be sent -----------------------------------------------------


def test_the_send_page_shows_the_email_with_its_footer(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    web.post(
        f"/drafts/{draft_id}",
        data={"subject": "RFD cotton thread sample", "body": "Hello.", "action": "approve"},
    )
    page = web.get("/campaigns/rfd/send").text
    assert "Tajpur Road, Ludhiana" in page
    assert "reply and say so" in page
    assert "Send 1 email now" in page


def test_the_send_page_sends_nothing(web, monkeypatch, settings):
    """There is deliberately no send button. Visiting the page, with an
    approved draft ready to go, must leave nothing in the messages table."""
    from outreach.adapters.db import connect

    _model(monkeypatch, ("Hello.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    web.post(
        f"/drafts/{draft_id}",
        data={"subject": "RFD cotton thread sample", "body": "Hello.", "action": "approve"},
    )
    web.get("/campaigns/rfd/send")
    web.get("/campaigns/rfd/send")

    conn = connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    conn.close()


def test_a_draft_from_before_the_closing_must_lose_its_sign_off(web, monkeypatch, tmp_path):
    """Drafted with no closing, so the sign-off was kept. Once the closing
    exists, the page says so and approval waits for the line to go (D-020)."""
    _model(monkeypatch, ("Hello.", None), ("Best regards, Aksh Goyal.", None))
    web.post("/campaigns/rfd/draft")
    draft_id = _first_draft_id(web)
    (tmp_path / "campaigns" / "rfd.closing.md").write_text("Warm regards,\n\nAksh Goyal")

    page = web.get(f"/drafts/{draft_id}").text
    assert "Delete 1 line(s) before approving" in page

    subject = "RFD cotton thread sample"
    old = {"subject": subject, "body": "Hello.\n\nBest regards, Aksh Goyal.", "action": "approve"}
    assert "repeat" in web.post(f"/drafts/{draft_id}", data=old).text
    fixed = {"subject": subject, "body": "Hello.", "action": "approve"}
    response = web.post(f"/drafts/{draft_id}", data=fixed, follow_redirects=True)
    assert "Regenerate this draft" in response.text
    assert "Campaign instructions have changed" in response.text


# --- approving in bulk ------------------------------------------------------


def _drafts_by_company(web):
    import re

    page = web.get("/campaigns/rfd/drafts").text
    rows = re.findall(
        r'<tr data-draft-id="(\d+)">.*?<td data-label="Recipient">([^<]+)<', page, re.DOTALL
    )
    return {company.strip(): int(i) for i, company in rows}


def test_approve_all_approves_only_drafts_that_pass_every_check(web, monkeypatch):
    _model(monkeypatch, ("Hello.", None), ("We make RFD cotton thread in Ludhiana.", None))
    web.post("/campaigns/rfd/draft")
    ids = _drafts_by_company(web)
    subject = "RFD cotton thread sample"
    maybe = "Hello.\n\nYour business seems well established."
    web.post(
        f"/drafts/{ids['Kohinoor Knits']}",
        data={"subject": subject, "body": maybe, "action": "save"},
    )
    invented = "Hello.\n\nWe met at your Coimbatore office."
    web.post(
        f"/drafts/{ids['Meridian Textiles']}",
        data={"subject": subject, "body": invented, "action": "save"},
    )

    page = web.post("/campaigns/rfd/approve-all", follow_redirects=True).text
    ready = len(ids) - 2
    assert f"Approved {ready}." in page
    assert "1 has a “maybe” line" in page
    assert "1 has a line to fix" in page
    assert "Nothing has been sent." in page

    statuses = {c: _draft_status(web, i) for c, i in ids.items()}
    assert statuses["Kohinoor Knits"] == "review"
    assert statuses["Meridian Textiles"] == "review"
    others = [s for c, s in statuses.items() if c not in {"Kohinoor Knits", "Meridian Textiles"}]
    assert others and all(s == "approved" for s in others)


def _draft_status(web, draft_id):
    import re

    page = web.get("/campaigns/rfd/drafts").text
    row = re.search(rf'<tr data-draft-id="{draft_id}">.*?class="status s-(\w+)"', page, re.DOTALL)
    return row.group(1)


def test_approve_all_holds_back_a_draft_that_repeats_the_closing(web, monkeypatch, tmp_path):
    _model(monkeypatch, ("Hello.", None), ("Best regards, Aksh Goyal.", None))
    web.post("/campaigns/rfd/draft")
    (tmp_path / "campaigns" / "rfd.closing.md").write_text("Warm regards,\n\nAksh Goyal")
    ids = _drafts_by_company(web)
    page = web.post("/campaigns/rfd/approve-all", follow_redirects=True).text
    assert "Approved 0." in page
    assert all(_draft_status(web, i) == "review" for i in ids.values())
