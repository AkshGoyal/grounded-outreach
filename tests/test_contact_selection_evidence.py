"""Displayed evidence and enrollment must refer to the same published address."""

import json
import re

import pytest

from outreach.core.models import SuppressionReason
from tests.test_attachments_handoff import files_workspace as files_workspace
from tests.test_platform import db_for, saved_lead


def selected_second(db, *, facts=None):
    key = saved_lead(db)
    lead = db.lead(key)
    first = lead["emails"][0] | {"match_kind": "requested_role"}
    second = first | {"value": "office@mills.example", "match_kind": "general_fallback"}
    db.conn.execute(
        "UPDATE research_leads SET emails_json=?,selected_email=?,facts_json=? WHERE id=?",
        (json.dumps([first, second]), second["value"], json.dumps(facts or lead["facts"]), key),
    )
    return key, lead["run_id"]


@pytest.mark.parametrize(
    "page", ["/research/{run}", "/research/{run}/use", "/campaigns/files?tab=audience"]
)
def test_selected_address_and_role_agree_everywhere(files_workspace, page):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        key, run = selected_second(db)
    html = client.get(page.format(run=run)).text
    row = next(
        row for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S) if f'value="{key}"' in row
    )
    assert "office@mills.example" in row
    assert "General inbox" in row
    assert "Role matched" not in row
    assert "sales@mills.example" not in row
    response = client.post(
        f"/research/{run}/use", data={"lead_ids": key, "campaign_id": "files", "action": "existing"}
    )
    assert "1 contacts added" in response.text
    with db_for(config) as db:
        assert db.store.emails_in_campaign("files") == {"buyer@example.com", "office@mills.example"}
    assert not box.sent


@pytest.mark.parametrize(
    "page", ["/research/{run}", "/research/{run}/use", "/campaigns/files?tab=audience"]
)
def test_fit_exceptions_are_distinct_and_not_preselected(files_workspace, page):
    config, _, client, box, _, _ = files_workspace
    facts = [
        {
            "criterion": "Manufactures textiles",
            "status": "contradicted",
            "quote": "",
            "source_url": "",
        },
        {"criterion": "Exports products", "status": "unknown", "quote": "", "source_url": ""},
    ]
    with db_for(config) as db:
        key, run = selected_second(db, facts=facts)
        db.conn.execute(
            "UPDATE research_leads SET selected_email='sales@mills.example',"
            "review_status='approved' WHERE id=?",
            (key,),
        )
    html = client.get(page.format(run=run)).text
    row = next(
        row for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S) if f'value="{key}"' in row
    )
    assert "Audience fit mismatch: Manufactures textiles" in row
    assert "Audience criteria unconfirmed: Exports products" in row
    checkbox = re.search(r'<input[^>]*name="lead_ids"[^>]*>', row).group()
    assert "checked" not in checkbox
    assert not box.sent


@pytest.mark.parametrize("operation", ["direct", "legacy", "list"])
def test_stale_approved_address_cannot_be_substituted_or_enrolled(files_workspace, operation):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        key, run = selected_second(db)
        db.conn.execute(
            "UPDATE research_leads SET selected_email='missing@mills.example',"
            "review_status='approved' WHERE id=?",
            (key,),
        )
        with pytest.raises(ValueError):
            if operation == "list":
                db.add_list("Stale", None, [key])
            else:
                db.enroll("files", [key], accept_selected=operation == "direct")
        assert db.store.emails_in_campaign("files") == {"buyer@example.com"}
    page = client.get(f"/research/{run}").text
    assert "Selected email is no longer in the published evidence" in page
    assert ">Choose contact</span>" in page
    picker = client.get("/campaigns/files?tab=audience").text
    assert f'name="lead_ids" value="{key}"' not in picker
    assert not box.sent


def test_selected_suppression_does_not_fall_back_to_another_address(files_workspace):
    config, _, client, box, _, _ = files_workspace
    with db_for(config) as db:
        key, run = selected_second(db)
        db.store.add_suppression("office@mills.example", SuppressionReason.UNSUBSCRIBE)
        assert db.lead(key)["suppressed"]
        with pytest.raises(ValueError):
            db.enroll("files", [key], accept_selected=True)
        assert db.store.emails_in_campaign("files") == {"buyer@example.com"}
    assert not box.sent


def test_explicit_fit_exception_keeps_evidence_and_sends_nothing(files_workspace):
    config, _, client, box, _, _ = files_workspace
    facts = [
        {
            "criterion": "Manufactures textiles",
            "status": "contradicted",
            "quote": "",
            "source_url": "",
        }
    ]
    with db_for(config) as db:
        key, run = selected_second(db, facts=facts)
    response = client.post(
        f"/research/{run}/use", data={"lead_ids": key, "campaign_id": "files", "action": "existing"}
    )
    assert "1 contacts added" in response.text
    with db_for(config) as db:
        lead = db.lead(key)
        assert lead["facts"] == facts
        assert "contradicted criteria remain audience fit mismatches" in lead["review_note"]
    assert not box.sent
