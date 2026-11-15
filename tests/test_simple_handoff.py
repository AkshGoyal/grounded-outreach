"""Direct handoff keeps database changes atomic and never sends mail."""

import pytest

from outreach.core.models import SuppressionReason
from tests.test_attachments_handoff import files_workspace as files_workspace
from tests.test_platform import db_for, saved_lead


def test_pending_email_adds_without_separate_review(files_workspace):
    config, app, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        key = db.lead(lead)["run_id"]
        db.conn.execute(
            "UPDATE research_leads SET facts_json=? WHERE id=?",
            ('[ {"criterion":"Fit","status":"unknown","quote":"","source_url":""} ]', lead),
        )
    response = client.post(
        f"/research/{key}/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "1 contacts added" in response.text
    with db_for(config) as db:
        assert db.lead(lead)["review_status"] == "approved"
        assert "sales@mills.example" in db.store.emails_in_campaign("files")
        assert "unknown" in db.lead(lead)["review_note"]
    assert not box.sent


def test_invalid_campaign_does_not_approve_selection(files_workspace):
    config, app, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        key = db.lead(lead)["run_id"]
    client.post(
        f"/research/{key}/use",
        data={"lead_ids": str(lead), "campaign_id": "missing", "action": "existing"},
    )
    with db_for(config) as db:
        assert db.lead(lead)["review_status"] == "pending"
    assert not box.sent


@pytest.mark.parametrize("status", ["rejected", "unfinished", "suppressed"])
def test_unusable_selection_is_blocked(files_workspace, status):
    config, app, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        key = db.lead(lead)["run_id"]
        if status == "rejected":
            db.review_leads([lead], action="reject")
        elif status == "unfinished":
            db.conn.execute(
                "UPDATE research_leads SET processing_status='pending' WHERE id=?", (lead,)
            )
        else:
            db.store.add_suppression("sales@mills.example", SuppressionReason.UNSUBSCRIBE)
    response = client.post(
        f"/research/{key}/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "Some contacts changed" in response.text
    with db_for(config) as db:
        assert "sales@mills.example" not in db.store.emails_in_campaign("files")
    assert not box.sent


def test_attachment_link_is_in_campaign_navigation(files_workspace):
    _, _, client, box, _, _ = files_workspace
    page = client.get("/campaigns/files").text
    assert 'href="/campaigns/files/attachments"' in page
    assert ">Attachments</a>" in page
    assert not box.sent
