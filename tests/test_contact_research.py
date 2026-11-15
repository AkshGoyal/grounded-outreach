"""Real scheduler/HTTP adapter with fictional cross-web evidence and durable calls."""

import json

import httpx
import pytest

from outreach.adapters.research_api import ResearchAPI
from outreach.core.contact_evidence import (
    AddressEvidence,
    ContactEvidenceAssessment,
    collect_addresses,
    link_contact_evidence,
    supported_people,
)
from outreach.core.intake import seed_companies
from outreach.core.research import ResearchStop
from outreach.core.research_flow import run_research
from tests.test_research_staged import staged as staged

HOME = "https://cedar-labs.example/"
TEAM = HOME + "team"
EVENT = "https://events.example/speakers/alice"
BIO = "Alice Rivera is the founder of Cedar Labs."
ADDRESS = "Alice Rivera: alice@cedar-labs.example"
PAGES = {
    HOME: "Cedar Labs builds business software. Email hello@cedar-labs.example. [Team](/team)",
    TEAM: BIO,
    EVENT: "Cedar Labs speaker contact. " + ADDRESS,
}


def source(url, text):
    return {"url": url, "title": "Public evidence", "text": text, "retrieved_at": "2026-10-07"}


class Provider:
    def __init__(self, *, timeout_web=False, invented=False):
        self.calls = []
        self.timeout_web = timeout_web
        self.invented = invented

    def handler(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path.endswith("/extract"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": url, "full_content": PAGES[url], "title": "Public evidence"}
                        for url in body["urls"]
                    ],
                    "errors": [],
                },
            )
        if request.url.path.endswith("/search"):
            official = "domains" in body.get("advanced_settings", {}).get("source_policy", {})
            official = official or bool(
                body.get("advanced_settings", {}).get("source_policy", {}).get("include_domains")
            )
            if self.timeout_web and not official:
                raise httpx.ReadTimeout("Fictional timeout")
            urls = [HOME, TEAM] if official else [EVENT]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": u, "full_content": PAGES[u], "title": "Public evidence"}
                        for u in urls
                    ]
                },
            )
        prompt = body["messages"][-1]["content"]
        context = json.loads(prompt.split("\nSOURCES: ", 1)[1])
        role_id = next(k for k, s in context.items() if s["url"] == TEAM)
        address_id = next((k for k, s in context.items() if s["url"] == EVENT), None)
        value = {
            "facts": [],
            "fit_summary": "Review source evidence.",
            "unknowns": [],
            "people": [
                {"name": "Alice Rivera", "role": "founder", "source_id": role_id, "quote": BIO}
            ],
            "addresses": []
            if not address_id
            else [
                {
                    "name": "Alice Rivera",
                    "email": "invented@cedar-labs.example"
                    if self.invented
                    else "alice@cedar-labs.example",
                    "source_id": address_id,
                    "quote": ADDRESS,
                }
            ],
        }
        return httpx.Response(
            200,
            json={
                "usage": {"cost": 0.001},
                "choices": [{"message": {"content": json.dumps(value)}}],
            },
        )


def prepare(staged):
    db, key, config = staged
    db.save_execution(key, strategy_version=4)
    db.conn.execute(
        "INSERT INTO research_intakes VALUES (?,?)",
        (
            key,
            json.dumps(
                {
                    "contact_roles": ["founder"],
                    "research_mode": "focused",
                    "seed_websites": "Cedar Labs | " + HOME,
                }
            ),
        ),
    )
    return db, key, config


def execute(staged, provider):
    db, key, config = staged
    api = ResearchAPI(
        config, db, key, client=httpx.Client(transport=httpx.MockTransport(provider.handler))
    )
    try:
        run_research(db, api, key)
    finally:
        api.close()


def test_seeded_founder_email_found_across_official_role_and_external_address(staged):
    db, key, _ = prepare(staged)
    provider = Provider()
    execute(staged, provider)
    lead = db.leads(key)[0]
    contact = lead["emails"][0]
    assert contact["value"] == "alice@cedar-labs.example"
    assert contact["role_source_url"] == TEAM and contact["ownership_source_url"] == EVENT
    assert contact["source_scope"] == "external" and contact["match_kind"] == "requested_role"
    assert lead["review_status"] == "pending" and lead["processing_status"] == "complete"
    assert db.run(key)["execution"]["outcome"] == "target_reached"
    search_bodies = [b for p, b in provider.calls if p.endswith("/search")]
    assert any("Alice Rivera" in " ".join(b["search_queries"]) for b in search_bodies)
    assert any("source_policy" not in b.get("advanced_settings", {}) for b in search_bodies)
    assert not any("Discover additional" in b.get("objective", "") for b in search_bodies)
    assert db.run(key)["spent_micro"] <= 100000


def test_invented_model_address_is_not_added_or_promoted(staged):
    db, key, _ = prepare(staged)
    execute(staged, Provider(invented=True))
    contacts = db.leads(key)[0]["emails"]
    assert not any(c["value"].startswith("invented") for c in contacts)
    assert not any(c["match_kind"] == "requested_role" for c in contacts)
    assert db.run(key)["execution"]["outcome"] == "partial_results"


def test_budget_stop_preserves_contacts_and_resume_reuses_requests(staged):
    db, key, _ = prepare(staged)
    db.set_run(key, budget_micro=4000)
    provider = Provider()
    execute(staged, provider)
    assert db.run(key)["status"] == "paused"
    assert db.leads(key)[0]["emails"][0]["value"] == "hello@cedar-labs.example"
    first_calls = list(provider.calls)
    db.set_run(key, budget_micro=100000, status="running")
    execute(staged, provider)
    assert db.leads(key)[0]["emails"][0]["value"] == "alice@cedar-labs.example"
    for path, body in first_calls:
        assert provider.calls.count((path, body)) == 1
    assert db.run(key)["spent_micro"] <= 100000


def test_uncertain_wider_search_is_not_replayed(staged):
    db, key, _ = prepare(staged)
    provider = Provider(timeout_web=True)
    with pytest.raises(ResearchStop, match="retained"):
        execute(staged, provider)
    before = len(provider.calls)
    with pytest.raises(ResearchStop, match="uncertain"):
        execute(staged, provider)
    assert len(provider.calls) == before
    assert db.leads(key)[0]["emails"]


def test_completed_run_resume_retains_stage_context_without_new_calls(staged):
    db, key, _ = prepare(staged)
    provider = Provider()
    execute(staged, provider)
    calls = len(provider.calls)
    db.set_run(key, status="running")
    execute(staged, provider)
    assert len(provider.calls) == calls
    assert db.leads(key)[0]["emails"][0]["match_kind"] == "requested_role"


def test_external_namesake_without_company_corroboration_stays_unconfirmed():
    role = source(TEAM, BIO)
    outside = source(EVENT, "Alice Rivera: alice@unrelated.example")
    context = {"s1": role, "s2": outside}
    assessment = ContactEvidenceAssessment(
        facts=[],
        fit_summary="",
        unknowns=[],
        people=[{"name": "Alice Rivera", "role": "founder", "source_id": "s1", "quote": BIO}],
    )
    people = supported_people(assessment, context, "Cedar Labs", HOME)
    contacts = collect_addresses([role, outside], HOME, "Cedar Labs", people)
    claims = [
        AddressEvidence(
            name="Alice Rivera",
            email="alice@unrelated.example",
            source_id="s2",
            quote=outside["text"],
        )
    ]
    result = link_contact_evidence(
        contacts, people, claims, context, "Cedar Labs", HOME, ["founder"]
    )
    assert result[0]["match_kind"] == "unconfirmed"
    assert "contact_name" not in result[0]


def test_duplicate_publication_sources_are_retained_and_generic_is_not_founder():
    pages = [
        source(HOME, "Cedar Labs contact: hello@cedar-labs.example"),
        source(EVENT, "Cedar Labs contact: hello@cedar-labs.example"),
    ]
    addresses = collect_addresses(pages, HOME, "Cedar Labs")
    assert len(addresses) == 1 and len(addresses[0]["publication_sources"]) == 2
    linked = link_contact_evidence(addresses, [], [], {}, "Cedar Labs", HOME, ["founder"])
    assert linked[0]["match_kind"] == "general_fallback"


@pytest.mark.parametrize(
    "value",
    [
        "Cedar | http://127.0.0.1/",
        "Cedar | file:///secret",
        "Cedar",
        "Cedar | https://user:password@company.example",
        "Cedar | https://linkedin.com/company/cedar",
    ],
)
def test_seed_input_rejects_unsafe_or_noncompany_urls(value):
    with pytest.raises(ValueError):
        seed_companies(value)


def test_seed_input_normalizes_and_deduplicates():
    assert seed_companies(
        "Cedar Labs | https://cedar-labs.example\nCedar Labs | https://cedar-labs.example/"
    ) == [{"company": "Cedar Labs", "website": HOME}]


def test_economical_empty_pages_skip_all_model_assessments(staged):
    db, key, _ = prepare(staged)
    db.save_execution(key, strategy_version=5)
    calls = []

    class EmptyPages:
        def handler(self, request):
            body = json.loads(request.content)
            calls.append(request.url.path)
            if request.url.path.endswith("/extract"):
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {"url": body["urls"][0], "full_content": "Cedar Labs software."}
                        ]
                    },
                )
            assert request.url.path.endswith("/search"), "Empty pages must not spend model tokens"
            return httpx.Response(200, json={"results": []})

    execute(staged, EmptyPages())
    assert len(calls) == 3
    assert db.run(key)["spent_micro"] == 3000
    assert not db.leads(key)[0]["emails"]


def test_new_strategy_keeps_cross_page_founder_quality(staged):
    db, key, _ = prepare(staged)
    db.save_execution(key, strategy_version=5)
    provider = Provider()
    execute(staged, provider)
    assert db.leads(key)[0]["emails"][0]["match_kind"] == "requested_role"
    assert db.leads(key)[0]["emails"][0]["value"] == "alice@cedar-labs.example"
    first = list(provider.calls)
    db.set_run(key, status="running")
    execute(staged, provider)
    assert provider.calls == first


def test_two_dry_discovery_rounds_pause_before_more_spending(staged):
    db, key, config = staged
    db.save_execution(key, strategy_version=5)
    calls = []

    class EmptyDiscovery:
        def handler(self, request):
            body = json.loads(request.content)
            calls.append(request.url.path)
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json={"results": []})
            assert body["response_format"]["json_schema"]["name"] == "candidates"
            return httpx.Response(
                200,
                json={
                    "usage": {"cost": 0.001},
                    "choices": [{"message": {"content": '{"candidates": []}'}}],
                },
            )

    execute(staged, EmptyDiscovery())
    assert db.run(key)["status"] == "paused"
    assert db.run(key)["execution"]["outcome"] == "low_email_yield"
    assert db.run(key)["execution"]["round"] == 2
    assert len(calls) == 2
