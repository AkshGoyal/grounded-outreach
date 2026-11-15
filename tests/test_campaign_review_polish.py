"""Saved email previews and durable history use only fictional campaign data."""

import json

import pytest

from outreach.campaigns import save_texts
from outreach.core.models import DraftStatus
from tests.helpers import confirm_launch
from tests.test_attachments_handoff import files_workspace as files_workspace
from tests.test_attachments_handoff import upload, wait
from tests.test_platform import db_for


def test_saved_preview_combines_email_ending_and_attachments(files_workspace):
    _, _, client, box, _, draft = files_workspace
    save_texts("files", copy="Samples offered.", closing="Exact closing.\nSecond line.")
    upload(client)
    page = client.get(f"/drafts/{draft}").text
    preview = page.split('id="saved-email-preview"', 1)[1].split("</details>", 1)[0]
    assert "Full email preview · saved version" in preview
    assert "Subject: Hello\n\nHello.\n\nExact closing.\nSecond line." in preview
    assert "Brochure.pdf" in preview and "buyer@example.com" in preview
    assert "Save edits below to update this preview" in preview
    assert not box.sent


def test_sent_draft_points_to_original_history_not_current_campaign_files(files_workspace):
    config, app, client, box, _, draft = files_workspace
    save_texts("files", copy="Samples offered.", closing="Original ending.")
    upload(client)
    with db_for(config) as db:
        db.store.set_draft_status(draft, DraftStatus.APPROVED)
    confirm_launch(client, "/campaigns/files/send")
    wait(app)
    assert len(box.sent) == 1
    save_texts("files", copy="Changed campaign.", closing="Changed ending.")
    upload(client, "New-file.pdf", b"new file")
    page = client.get(f"/drafts/{draft}").text
    assert "Open saved message history" in page
    assert 'href="/campaigns/files/history"' in page
    assert "Changed ending." not in page and "New-file.pdf" not in page
    assert 'id="saved-email-preview"' not in page
    assert "Send me a test" not in page
    history = client.get("/campaigns/files/history").text
    assert "Original ending." in history and "Brochure.pdf" in history
    assert "Changed ending." not in history and "New-file.pdf" not in history
    app.state.sender.job = None
    recovery = client.get("/sending").text
    assert "Earlier sends remain" in recovery and "saved message history" in recovery
    assert "Nothing has been sent" not in recovery
    assert len(box.sent) == 1


def test_campaign_navigation_keeps_message_tab_without_duplicate_action(files_workspace):
    _, _, client, box, _, _ = files_workspace
    page = client.get("/campaigns/files").text
    header = page.split('class="section-heading"', 1)[1].split("</nav>", 1)[0]
    assert ">Message</a>" in header
    assert ">Edit message</a>" not in header
    assert not box.sent


def test_review_shows_source_links_without_promoting_provenance(files_workspace):
    config, _, client, box, contact, draft = files_workspace
    evidence = {
        "Company context 1": "Example Buyer builds textiles.",
        "research_sources": json.dumps(
            {
                "Company context 1": {
                    "source_url": "https://buyer.example/products",
                    "retrieved_at": "2026-10-10",
                }
            }
        ),
    }
    with db_for(config) as db:
        db.conn.execute(
            "UPDATE contacts SET evidence=? WHERE id=?", (json.dumps(evidence), contact)
        )
    page = client.get(f"/drafts/{draft}").text
    assert 'href="https://buyer.example/products"' in page
    assert "Research source" in page and "2026-10-10" in page
    assert 'class="key">research_sources' not in page
    assert not box.sent


@pytest.mark.parametrize(
    "metadata", ["invalid JSON", "[]", '{"Company context 1":{"source_url":"javascript:alert(1)"}}']
)
def test_invalid_imported_provenance_does_not_break_review(files_workspace, metadata):
    config, _, client, box, contact, draft = files_workspace
    with db_for(config) as db:
        db.conn.execute(
            "UPDATE contacts SET evidence=? WHERE id=?",
            (
                json.dumps(
                    {
                        "Company context 1": "Example Buyer builds textiles.",
                        "research_sources": metadata,
                    }
                ),
                contact,
            ),
        )
    response = client.get(f"/drafts/{draft}")
    assert response.status_code == 200
    assert "Research source</a>" not in response.text
    assert "javascript:alert" not in response.text
    assert not box.sent
