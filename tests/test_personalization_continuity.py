"""Offline source-backed company context survives research-to-draft handoff."""

import json

from outreach.adapters.platform_store import enrollment_evidence
from outreach.core.drafting import Draft, DraftSentence, draft_email, recipient_facts
from outreach.core.models import SuppressionReason
from tests.fakes.llm import FakeLLM
from tests.test_platform import db_for, saved_lead


def context(quote, url="https://mills.example/contact", status="supported"):
    return {
        "criterion": "Company context",
        "kind": "personalization",
        "status": status,
        "quote": quote,
        "source_url": url,
    }


def test_company_context_survives_enrollment_and_drafting_with_provenance(settings):
    quotes = ["Example Mills makes textiles", "Example Mills supplies woven cotton fabrics."]
    with db_for(settings) as db:
        key = saved_lead(db)
        lead = db.lead(key)
        lead["sources"][0]["text"] += " " + quotes[1]
        db.save_evidence(
            key,
            facts=lead["facts"] + [context(quote) for quote in quotes],
            sources=lead["sources"],
            emails=lead["emails"],
            flags=[],
            summary="Unsupported recipient hiring intent must stay out",
        )
        db.save_campaign("context", "Context", None, "sales", "", None)
        assert db.enroll("context", [key], accept_selected=True) == (1, 0)
        contact_id = db.one("SELECT contact_id FROM contact_origins WHERE lead_id=?", (key,))[
            "contact_id"
        ]
        evidence = db.store.get_contact(contact_id).evidence
        assert evidence["Makes textiles"] == quotes[0]
        assert evidence["Company context 1"] == quotes[0]
        assert evidence["Company context 2"] == quotes[1]
        provenance = json.loads(evidence["research_sources"])
        assert provenance["Company context 2"] == {
            "source_url": "https://mills.example/contact",
            "retrieved_at": "2026-10-04",
            "kind": "personalization",
        }
    llm = FakeLLM(
        [
            Draft(
                subject="Hello",
                sentences=[DraftSentence(text=quotes[1], cites="Company context 2")],
            )
        ]
    )
    checked = draft_email(llm, company="Example Mills", evidence=evidence, campaign_copy="Hello")
    assert not checked.blocked
    assert quotes[1] in llm.prompts[0]
    assert "research_sources" not in llm.prompts[0]
    assert "2026-10-04" not in llm.prompts[0]
    assert "Unsupported recipient hiring intent" not in llm.prompts[0]
    assert "Selected by user" not in llm.prompts[0]
    assert "research_sources" not in recipient_facts(evidence)


def test_handoff_rechecks_personalization_sources_and_never_promotes_unknowns(settings):
    with db_for(settings) as db:
        lead = db.lead(saved_lead(db))
    lead["facts"] += [
        context("Invented quotation absent from every source"),
        context("Example Mills makes textiles", "https://directory.example/contact"),
        context("Example Mills makes textiles", status="unknown"),
        context("Example Mills makes textiles", status="contradicted"),
    ]
    evidence = enrollment_evidence(lead)
    assert not any(key.startswith("Company context") for key in evidence)
    assert evidence["Makes textiles"] == "Example Mills makes textiles"


def test_every_suppressed_address_is_reported_for_throughput_counting(settings):
    with db_for(settings) as db:
        key = saved_lead(db)
        lead = db.lead(key)
        second = {**lead["emails"][0], "value": "founder@mills.example"}
        db.save_evidence(
            key,
            facts=lead["facts"],
            sources=lead["sources"],
            emails=lead["emails"] + [second],
            flags=[],
            summary="Manufacturer",
        )
        db.store.add_suppression(second["value"], SuppressionReason.UNSUBSCRIBE)
        decoded = db.lead(key)
        assert decoded["suppressed_emails"] == [second["value"]]
        assert not decoded["suppressed"]
