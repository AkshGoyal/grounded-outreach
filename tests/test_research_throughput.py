"""Deterministic throughput benchmark through the actual ledger and HTTP adapter."""

import json

import httpx
import pytest

from outreach.core.models import SuppressionReason
from outreach.core.research import ResearchStop
from outreach.core.research_scheduler import ready_count
from tests.test_research_staged import execute
from tests.test_research_staged import staged as staged


class ThroughputProvider:
    def __init__(self, *, empty_rounds=0, bad_companies=0, repeat=False):
        self.empty_rounds = empty_rounds
        self.bad_companies = bad_companies
        self.repeat = repeat
        self.rounds = 0
        self.calls = []
        self.pause = None

    def handler(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if self.pause:
            self.pause()
        if request.url.path.endswith("/search"):
            if "Discover additional companies" in body["objective"]:
                self.rounds += 1
                number = 1 if self.repeat else self.rounds
                results = (
                    []
                    if self.rounds <= self.empty_rounds
                    else [
                        {
                            "url": f"https://firm{number}.example/",
                            "full_content": f"Firm {number} builds business software.",
                        }
                    ]
                )
            else:
                results = []
            return httpx.Response(200, json={"results": results})
        if request.url.path.endswith("/extract"):
            url = body["urls"][0]
            number = int(url.split("firm")[1].split(".")[0])
            text = f"Firm {number} builds business software."
            if number > self.bad_companies:
                text += (
                    f" Recruiting: hr@firm{number}.example"
                    if "careers" in url
                    else f" Contact info@firm{number}.example [Contact](/contact) "
                    "[Team](/team) [Careers](/careers)"
                )
            return httpx.Response(200, json={"results": [{"url": url, "full_content": text}]})
        prompt = body["messages"][-1]["content"]
        context = json.loads(prompt.split("\nSOURCES: ", 1)[1])
        if "Find distinct company NAMES" in prompt:
            source = context["s1"]
            company = source["text"].split(" builds")[0]
            value = {
                "candidates": []
                if self.repeat
                else [
                    {
                        "company": company,
                        "website": source["url"],
                        "source_id": "s1",
                        "identity_quote": source["text"],
                    }
                ]
            }
        else:
            value = {
                "facts": [],
                "fit_summary": "Check published evidence.",
                "unknowns": [],
                "people": [],
                "addresses": [],
                "personalization": [],
            }
        return httpx.Response(
            200,
            json={
                "usage": {"cost": 0.001},
                "choices": [{"message": {"content": json.dumps(value)}}],
            },
        )


def configure(staged, *, target=1, budget=500000):
    db, key, _ = staged
    db.save_execution(key, strategy_version=6)
    db.set_run(key, target_count=target, budget_micro=budget)
    db.conn.execute(
        "INSERT INTO research_intakes VALUES (?,?)",
        (
            key,
            json.dumps(
                {
                    "contact_roles": ["hr"],
                    "research_mode": "focused",
                    "company_type": "Software companies",
                    "geography": "Bengaluru",
                }
            ),
        ),
    )
    return db, key


@pytest.mark.parametrize("empty_rounds,bad_companies,target", [(10, 0, 1), (0, 4, 1), (0, 0, 2)])
def test_continues_past_old_limits_until_real_role_target(
    staged, empty_rounds, bad_companies, target
):
    db, key = configure(staged, target=target)
    provider = ThroughputProvider(empty_rounds=empty_rounds, bad_companies=bad_companies)
    execute(staged, provider)
    run = db.run(key)
    assert run["execution"]["outcome"] == "target_reached"
    assert ready_count(db, key) == target
    assert len(db.leads(key)) == bad_companies + target
    assert run["spent_micro"] <= run["budget_micro"]
    urls = [b["urls"][0] for p, b in provider.calls if p.endswith("/extract")]
    assert any("careers" in url for url in urls)
    assert not any("/contact" in url or "/team" in url for url in urls)
    before = len(provider.calls)
    db.set_run(key, status="running")
    execute(staged, provider)
    assert len(provider.calls) == before
    print(
        json.dumps(
            {
                "empty_rounds": empty_rounds,
                "bad_companies": bad_companies,
                "target": target,
                "ready": ready_count(db, key),
                "requests": before,
                "cost_usd": run["spent_micro"] / 1e6,
            }
        )
    )


def test_empty_discovery_runs_to_budget_without_model_calls(staged):
    db, key = configure(staged, budget=9000)
    provider = ThroughputProvider(empty_rounds=100)
    execute(staged, provider)
    assert db.run(key)["execution"]["outcome"] == "budget_limit"
    assert db.run(key)["execution"]["round"] == 9
    assert db.run(key)["spent_micro"] == 9000
    assert len(provider.calls) == 9
    assert not db.leads(key)


def test_repeated_identical_sources_do_not_repeat_selection_model_cost(staged):
    db, key = configure(staged, budget=25000)
    provider = ThroughputProvider(repeat=True)
    execute(staged, provider)
    assert db.run(key)["execution"]["outcome"] == "budget_limit"
    assert len([p for p, _ in provider.calls if p.endswith("/chat/completions")]) == 1
    assert db.run(key)["spent_micro"] <= 25000


def test_continuous_search_honors_manual_pause(staged):
    db, key = configure(staged)
    provider = ThroughputProvider(empty_rounds=100)
    provider.pause = lambda: db.set_run(key, status="pause_requested")
    with pytest.raises(ResearchStop, match="paused"):
        execute(staged, provider)
    assert len(provider.calls) == 1


def test_target_does_not_count_duplicate_or_suppressed_addresses(staged):
    db, key = configure(staged, target=2)
    execute(staged, ThroughputProvider())
    leads = db.leads(key)
    shared = leads[0]["emails"]
    db.conn.execute(
        "UPDATE research_leads SET emails_json=? WHERE id=?", (json.dumps(shared), leads[1]["id"])
    )
    assert ready_count(db, key) == 1
    db.store.add_suppression(
        next(e["value"] for e in shared if e["match_kind"] == "requested_role"),
        SuppressionReason.UNSUBSCRIBE,
    )
    assert ready_count(db, key) == 0


def test_strategy6_keeps_only_literal_official_personalization(staged):
    from tests.test_contact_research import ADDRESS, EVENT, HOME, Provider, prepare

    db, key, _ = prepare(staged)
    db.save_execution(key, strategy_version=6)
    provider = Provider()
    original = provider.handler

    def handler(request):
        response = original(request)
        if not request.url.path.endswith("/chat/completions"):
            return response
        body = json.loads(request.content)
        context = json.loads(body["messages"][-1]["content"].split("\nSOURCES: ", 1)[1])
        official = next(k for k, source in context.items() if source["url"] == HOME)
        outside = next((k for k, source in context.items() if source["url"] == EVENT), None)
        data = response.json()
        value = json.loads(data["choices"][0]["message"]["content"])
        value["personalization"] = [
            {"source_id": official, "quote": "Cedar Labs builds business software."},
            {"source_id": official, "quote": "Invented claims must not be saved."},
        ]
        if outside:
            value["personalization"].append({"source_id": outside, "quote": ADDRESS})
        data["choices"][0]["message"]["content"] = json.dumps(value)
        return httpx.Response(200, json=data)

    provider.handler = handler
    execute(staged, provider)
    facts = [f for f in db.leads(key)[0]["facts"] if f.get("kind") == "personalization"]
    assert len(facts) == 1
    assert facts[0]["quote"] == "Cedar Labs builds business software."
    assert facts[0]["source_url"] == HOME
    assert ready_count(db, key) == 1


def test_strategy6_uncertain_search_is_never_replayed(staged):
    db, key = configure(staged)
    provider = ThroughputProvider(empty_rounds=100)
    original = provider.handler

    def handler(request):
        if len(provider.calls) == 1:
            provider.calls.append((request.url.path, json.loads(request.content)))
            raise httpx.ReadTimeout("Fictional uncertain search")
        return original(request)

    provider.handler = handler
    with pytest.raises(ResearchStop):
        execute(staged, provider)
    count = len(provider.calls)
    with pytest.raises(ResearchStop, match="uncertain"):
        execute(staged, provider)
    assert len(provider.calls) == count == 2
