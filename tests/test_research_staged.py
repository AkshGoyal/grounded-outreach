"""Production research adapter/pipeline with fictional HTTP only."""

import json

import httpx
import pytest

from outreach.adapters.platform_store import PlatformStore, now
from outreach.adapters.research_api import ResearchAPI
from outreach.core.research import Candidates, ResearchStop
from outreach.core.research_flow import run_research
from outreach.core.research_scheduler import contact_links, supported_suggestions
from outreach.web.research_view import request_summary
from tests.test_platform import PLAN

DIRECTORY = {
    "url": "https://industry.example/members",
    "title": "Industry members",
    "full_content": "Cedar Labs builds business software in Bengaluru.",
}
OFFICIAL = {
    "url": "https://cedar-labs.example/",
    "title": "Cedar Labs",
    "full_content": (
        'Cedar Labs builds business software in Bengaluru. <a href="/contact">Contact</a>'
    ),
}
CONTACT = {
    "url": "https://cedar-labs.example/contact",
    "title": "Cedar Labs contact",
    "full_content": "Cedar Labs business enquiries: hello@cedar-labs.example",
}


class FictionalResearch:
    def __init__(self, *, no_names=False, ambiguous=False, search_email=False):
        self.calls = []
        self.no_names, self.ambiguous, self.search_email = no_names, ambiguous, search_email
        self.stop_at = None
        self.stop_callback = None

    def handler(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if self.stop_at and len(self.calls) == self.stop_at:
            raise httpx.ReadTimeout("fictional interrupted request")
        if request.url.path.endswith("/search"):
            objective = body["objective"]
            sources = (
                [OFFICIAL]
                if "Resolve the official" in objective
                else ([CONTACT] if self.search_email else [OFFICIAL])
                if "Find published" in objective
                else [DIRECTORY]
            )
            if "Find published" in objective:
                assert body["advanced_settings"]["source_policy"]["include_domains"] == [
                    "cedar-labs.example"
                ]
            result = {"results": sources}
        elif request.url.path.endswith("/extract"):
            result = {
                "results": [s for s in [OFFICIAL, CONTACT] if s["url"] in body["urls"]],
                "errors": [],
            }
        else:
            prompt = body["messages"][-1]["content"]
            if "Assess only" in prompt:
                result = {
                    "facts": [
                        {
                            "criterion_index": 1,
                            "status": "supported",
                            "source_id": "s1",
                            "quote": "Cedar Labs builds business software in Bengaluru.",
                        }
                    ],
                    "fit_summary": "Software company; review contact role.",
                    "unknowns": [],
                }
            else:
                resolve = "Resolve ONLY" in prompt
                result = {
                    "candidates": []
                    if self.no_names
                    else [
                        {
                            "company": "Cedar Labs",
                            "website": "" if not resolve else OFFICIAL["url"],
                            "source_id": "s1",
                            "identity_quote": "Cedar Labs builds business software in Bengaluru.",
                        }
                    ]
                }
                if resolve and self.ambiguous:
                    result = {"candidates": []}
            result = {
                "choices": [{"message": {"content": json.dumps(result)}}],
                "usage": {"cost": 0.001},
            }
        if self.stop_callback:
            self.stop_callback(request, body)
        return httpx.Response(200, json=result)


@pytest.fixture
def staged(store, settings):
    db = PlatformStore(store)
    key = db.new_run(
        title="Fictional staged run",
        brief="Find software companies in Bengaluru.",
        purpose="sales",
        tags="",
        project_id=None,
        target=1,
        budget=500000,
        engine_version=2,
    )
    db.set_run(key, plan_json=json.dumps(PLAN), approved_at=now(), status="running")
    config = settings.model_copy(update={"parallel_api_key": "fake", "openrouter_api_key": "fake"})
    return db, key, config


def execute(staged, fake):
    db, key, config = staged
    api = ResearchAPI(
        config, db, key, client=httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    try:
        run_research(db, api, key)
    finally:
        api.close()


def test_unknown_website_is_resolved_and_literal_contact_link_is_followed(staged):
    fake = FictionalResearch()
    execute(staged, fake)
    db, key, _ = staged
    assert db.run(key)["execution"]["outcome"] == "target_reached"
    assert db.suggestions(key)[0]["status"] == "resolved"
    lead = db.leads(key)[0]
    assert lead["emails"][0]["value"] == "hello@cedar-labs.example"
    assert lead["emails"][0]["source_url"] == CONTACT["url"]
    assert lead["processing_status"] == "complete"
    summary = request_summary(db, db.run(key), active=False)
    assert summary["suggested"] == summary["with_email"] == 1
    assert len([b for p, b in fake.calls if p.endswith("/extract")]) == 2


def test_search_email_avoids_extra_page_extraction(staged):
    fake = FictionalResearch(search_email=True)
    execute(staged, fake)
    assert staged[0].leads(staged[1])[0]["emails"]
    assert not any(p.endswith("/extract") for p, _ in fake.calls)


def test_no_names_stops_after_three_rounds_with_honest_empty_outcome(staged):
    fake = FictionalResearch(no_names=True)
    execute(staged, fake)
    run = staged[0].run(staged[1])
    assert run["execution"]["round"] == 3
    assert run["execution"]["outcome"] == "no_usable_results"
    assert "0 of 1" in run["progress"]
    assert len(fake.calls) == 6


def test_unresolved_names_remain_visible_and_duplicates_are_not_resolved_again(staged):
    fake = FictionalResearch(ambiguous=True)
    execute(staged, fake)
    db, key, _ = staged
    assert len(db.suggestions(key)) == 1
    assert db.suggestions(key)[0]["status"] == "unresolved"
    assert not db.leads(key)
    assert (
        len(
            [
                b
                for p, b in fake.calls
                if p.endswith("/search") and "Resolve the official" in b["objective"]
            ]
        )
        == 1
    )


def test_budget_limit_saves_queue_without_starting_unaffordable_call(staged):
    db, key, _ = staged
    db.conn.execute("UPDATE research_runs SET budget_micro=1000 WHERE id=?", (key,))
    fake = FictionalResearch()
    execute(staged, fake)
    assert len(fake.calls) == 1
    run = db.run(key)
    assert run["status"] == "paused"
    assert run["execution"]["outcome"] == "budget_limit"
    assert run["spent_micro"] == 1000
    assert len(db.rows("SELECT * FROM research_calls")) == 1


def test_budget_before_fit_keeps_emails_but_does_not_allow_approval(staged):
    db, key, _ = staged
    fake = FictionalResearch(search_email=True)

    def reduce_budget(request, body):
        if request.url.path.endswith("/search") and "Find published" in body["objective"]:
            amount = db.run(key)["spent_micro"]
            db.conn.execute("UPDATE research_runs SET budget_micro=? WHERE id=?", (amount, key))

    fake.stop_callback = reduce_budget
    execute(staged, fake)
    lead = db.leads(key)[0]
    assert lead["emails"]
    assert lead["processing_status"] == "pending"
    assert db.run(key)["execution"]["outcome"] == "budget_limit"
    with pytest.raises(ValueError, match="completed lead"):
        db.review_leads([lead["id"]], action="approve", confirmed=True)


def test_pause_and_restart_reuses_completed_paid_requests(staged):
    db, key, _ = staged
    fake = FictionalResearch()
    paused = False

    def pause(request, body):
        nonlocal paused
        if not paused and request.url.path.endswith("/extract"):
            paused = True
            db.set_run(key, status="pause_requested")

    fake.stop_callback = pause
    with pytest.raises(ResearchStop, match="paused"):
        execute(staged, fake)
    count = len(fake.calls)
    ledger = db.rows("SELECT * FROM research_calls")
    db.set_run(key, status="running")
    fake.stop_callback = None
    execute(staged, fake)
    assert db.run(key)["execution"]["outcome"] == "target_reached"
    assert len(fake.calls) == count + 2  # next page and fit, no discovery/domain replay
    assert db.rows("SELECT * FROM research_calls")[: len(ledger)] == ledger


def test_uncertain_request_is_not_replayed_after_restart(staged):
    fake = FictionalResearch()
    fake.stop_at = 2
    with pytest.raises(ResearchStop, match="connection failed"):
        execute(staged, fake)
    fake.stop_at = None
    with pytest.raises(ResearchStop, match="uncertain"):
        execute(staged, fake)
    assert len(fake.calls) == 2


def test_discovery_name_requires_literal_specific_identity():
    sources = [{"url": DIRECTORY["url"], "title": "Members", "text": DIRECTORY["full_content"]}]
    answer = Candidates(
        candidates=[
            {
                "company": "Invented Labs",
                "website": "",
                "source_id": "s1",
                "identity_quote": DIRECTORY["full_content"],
            }
        ]
    )
    assert supported_suggestions(sources, answer) == []


def test_contact_links_reject_external_private_and_invented_paths():
    sources = [
        {
            "url": OFFICIAL["url"],
            "text": '<a href="/careers">Jobs</a> <a href="http://127.0.0.1/contact">bad</a> '
            '<a href="https://directory.example/contact">external</a> [Team](/team)',
        }
    ]
    assert contact_links(sources, OFFICIAL["url"]) == [
        "https://cedar-labs.example/careers",
        "https://cedar-labs.example/team",
    ]


def test_legacy_run_keeps_engine_version_one(store):
    db = PlatformStore(store)
    key = db.new_run(
        title="Old",
        brief="Old approved audience.",
        purpose="sales",
        tags="",
        project_id=None,
        target=1,
        budget=100000,
    )
    assert db.run(key)["execution"] == {"version": 1}


def test_administrative_addresses_are_not_outreach_contacts():
    from outreach.core.research_scheduler import contact_emails

    source = {
        "url": CONTACT["url"],
        "retrieved_at": "2026-10-07",
        "text": "Privacy: privacy@cedar-labs.example. Legal: legal@cedar-labs.example. "
        "Recruiting: careers@cedar-labs.example. Contact: hello@cedar-labs.example.",
    }
    found = contact_emails([source], OFFICIAL["url"])
    assert {e["value"] for e in found} == {
        "careers@cedar-labs.example",
        "hello@cedar-labs.example",
    }
    assert found[0]["role_hint"] == "HR / recruiting department"


def test_company_aliases_share_one_domain_check_and_contact_result(staged):
    db, key, _ = staged
    db.conn.execute("UPDATE research_runs SET target_count=2 WHERE id=?", (key,))
    fake = FictionalResearch()
    execute(staged, fake)
    lead = db.leads(key)[0]
    item = db.suggestions(key)[0]["evidence"] | {
        "company": "Cedar Labs Limited",
        "identity_quote": "Cedar Labs Limited builds software.",
        "source_text": "Cedar Labs Limited builds software.",
        "website": OFFICIAL["url"],
        "source_url": OFFICIAL["url"],
    }
    db.add_suggestion(key, item)
    db.set_run(key, status="running")
    count = len(fake.calls)
    execute(staged, fake)
    assert len(db.leads(key)) == 1
    assert db.leads(key)[0]["id"] == lead["id"]
    assert len(fake.calls) == count


def test_provider_page_errors_are_kept_and_do_not_mean_no_email_exists(staged):
    db, key, config = staged
    fake = FictionalResearch()
    original = fake.handler

    def handler(request):
        if request.url.path.endswith("/extract"):
            body = json.loads(request.content)
            fake.calls.append((request.url.path, body))
            return httpx.Response(
                200,
                json={
                    "results": [],
                    "errors": [
                        {
                            "url": body["urls"][0],
                            "error_type": "fetch_error",
                            "http_status_code": 403,
                        }
                    ],
                },
            )
        return original(request)

    fake.handler = handler
    execute(staged, fake)
    assert db.run(key)["execution"]["outcome"] == "no_usable_results"
    assert any("not proof" in f for f in db.leads(key)[0]["flags"])


def test_focused_hr_does_not_count_a_support_inbox_as_hr(staged):
    from outreach.core.intake import AudienceIntake

    db, key, _ = staged
    intake = AudienceIntake(
        goal="Find business software companies in Bengaluru.",
        company_type="Software",
        geography="Bengaluru",
        contact_roles=["hr"],
        research_mode="focused",
    )
    db.conn.execute("INSERT INTO research_intakes VALUES (?,?)", (key, intake.model_dump_json()))
    fake = FictionalResearch(search_email=True)
    original = fake.handler

    def handler(request):
        response = original(request)
        data = response.json()
        if request.url.path.endswith(("/search", "/extract")):
            for source in data.get("results", []):
                source["full_content"] = source["full_content"].replace(
                    "hello@cedar-labs.example", "support@cedar-labs.example"
                )
        return httpx.Response(200, json=data)

    fake.handler = handler
    execute(staged, fake)
    run = db.run(key)
    assert run["execution"]["outcome"] == "partial_results"
    assert run["status"] == "completed"
    assert db.leads(key)[0]["emails"][0]["role_hint"] == "Support inbox"
    assert "0 of 1" in run["progress"]


def test_staged_page_and_status_show_real_funnel_counts(staged):
    from fastapi.testclient import TestClient

    from outreach.web.app import create_app

    db, key, config = staged
    execute(staged, FictionalResearch())
    app = create_app(config, research_api=lambda *args: pytest.fail("No new paid request"))
    client = TestClient(app)
    page = client.get("/research/" + key)
    assert page.status_code == 200
    assert "How this research works" in page.text
    assert "Contact target reached" in page.text
    assert "Company suggestions and website checks (1)" in page.text
    status = client.get("/research/" + key + "/status").json()
    assert status["requests"]["suggested"] == 1
    assert status["requests"]["email_count"] == 1
    assert status["requests"]["outcome"] == "target_reached"
    assert "contact preference" in status["detail"]
