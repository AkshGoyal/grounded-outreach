"""Campaigns expose found emails directly; lists are optional legacy tools."""

import json

from tests.test_attachments_handoff import files_workspace as files_workspace
from tests.test_platform import db_for, saved_lead


def test_campaign_shows_pending_published_emails_inline(files_workspace):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        run = db.lead(lead)["run_id"]
    page = client.get("/campaigns/files?tab=audience")
    assert page.status_code == 200
    assert "Add emails from your audiences" in page.text
    assert f'action="/research/{run}/use"' in page.text
    assert 'name="campaign_id" value="files"' in page.text
    assert f'name="lead_ids" value="{lead}"' in page.text
    assert "sales@mills.example" in page.text
    response = client.post(
        f"/research/{run}/use",
        data={"lead_ids": str(lead), "campaign_id": "files", "action": "existing"},
    )
    assert "1 contacts added" in response.text
    assert not box.sent


def test_campaign_picker_omits_existing_members(files_workspace):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        db.enroll("files", [lead], accept_selected=True)
    page = client.get("/campaigns/files?tab=audience").text
    picker = page.split('id="add-contacts"', 1)[1].split("Other ways to add contacts", 1)[0]
    assert "0 emails available" in picker
    assert f'name="lead_ids" value="{lead}"' not in picker
    assert not box.sent


def test_new_campaign_does_not_require_a_contact_list(files_workspace):
    _, _, client, box, _, _ = files_workspace
    page = client.get("/campaigns/new").text
    assert "Describe what your emails should say" in page
    assert 'name="message_prompt"' in page and 'name="closing"' not in page
    assert "data-keep-selection" in page
    assert "<summary>Use an older saved contact list (optional)</summary>" in page
    assert "Start with an approved lead list" not in page
    assert not box.sent


def test_selected_contacts_have_no_list_choice_on_campaign_creation(files_workspace):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        lead = saved_lead(db)
        group = db.add_list("Selected", None, [lead], accept_selected=True)
    page = client.get(f"/campaigns/new?list_id={group}").text
    assert "1 contacts selected for this campaign." in page
    assert f'type="hidden" name="list_id" value="{group}"' in page
    assert '<select name="list_id">' not in page
    assert not box.sent


def test_campaign_keeps_contact_facts_and_evidence_link_without_raw_provenance(files_workspace):
    config, _, client, box, _, _ = files_workspace
    metadata = json.dumps(
        {
            "Company context 1": {
                "source_url": "https://mills.example/products",
                "retrieved_at": "2026-10-10",
            }
        }
    )
    with db_for(config) as db:
        lead = saved_lead(db)
        db.enroll("files", [lead], accept_selected=True)
        contact = db.one("SELECT contact_id FROM contact_origins WHERE lead_id=?", (lead,))[
            "contact_id"
        ]
        evidence = dict(db.store.get_contact(contact).evidence)
        evidence.update(
            {
                "Company context 1": "Fictional Mills supplies cotton fabrics.",
                "research_sources": metadata,
            }
        )
        db.conn.execute(
            "UPDATE contacts SET evidence=? WHERE id=?", (json.dumps(evidence), contact)
        )
    response = client.get("/campaigns/files?tab=audience")
    assert response.status_code == 200
    table = response.text.split('class="audience-table table-wrap"', 1)[1]
    assert "Fictional Mills supplies cotton fabrics." in table
    assert f'href="/leads/{lead}"' in table and "Research evidence" in table
    assert "research_sources" not in table and "source_url" not in table
    assert "https://mills.example/products" not in table
    assert "research_sources" not in client.get("/campaigns/files").text
    assert not box.sent
