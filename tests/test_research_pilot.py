"""Offline cost, replay and evidence invariants; all companies are fictional."""

import json
from decimal import Decimal

import httpx
import pytest
from experiments.pilot_runtime import PilotStop, Runtime, validate_shape
from experiments.research_pilot import PLAN_SCHEMA, public_url, validate_assessment


def runtime(tmp_path, handler):
    return Runtime(
        tmp_path,
        {"parallel": "test", "openrouter": "test", "model": "test"},
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


def call(r, key="a", amount="0.01", arm="textiles-custom"):
    return r.paid(key, arm, "parallel", "/v1/search", {}, Decimal(amount), tariff=True)


def test_reserved_before_network_and_cached_after_restart(tmp_path):
    requests = []

    def handler(request):
        ledger = json.loads((tmp_path / "ledger.json").read_text())
        assert ledger["calls"]["a"]["status"] == "reserved"
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    r = runtime(tmp_path, handler)
    assert call(r) == {"results": []}
    r.close()
    r = runtime(tmp_path, handler)
    assert call(r) == {"results": []}
    assert len(requests) == 1
    assert r.charged() == Decimal("0.01")
    r.close()


def test_ambiguous_failure_retains_cost_and_never_replays(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("fictional timeout")

    r = runtime(tmp_path, handler)
    with pytest.raises(PilotStop, match="network failure"):
        call(r)
    r.close()
    r = runtime(tmp_path, handler)
    with pytest.raises(PilotStop, match="uncertain outcome"):
        call(r)
    assert len(requests) == 1
    assert r.summary()["reserved_usd"] == "0.01"
    r.close()


def test_arm_and_total_budgets_prevent_requests(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    r = runtime(tmp_path, handler)
    call(r, amount="0.20")
    with pytest.raises(PilotStop, match="Budget reached"):
        call(r, "too-much")
    for i in range(4):
        call(r, str(i), amount="0.20", arm=f"other-{i}")
    with pytest.raises(PilotStop, match="Budget reached"):
        call(r, "total-too-much", arm="new")
    assert len(requests) == 5
    r.close()


def test_confirmed_rejection_recovery_retains_reservation_and_caches(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401 if len(requests) == 1 else 200, json={})

    r = runtime(tmp_path, handler)
    with pytest.raises(PilotStop, match="HTTP 401"):
        call(r)
    with pytest.raises(PilotStop, match="uncertain outcome"):
        call(r)
    assert len(requests) == 1
    r.state["calls"]["a"].update(status="rejected", http_status=401, recovery_key="a/recovery-1")
    r.save()
    assert call(r) == {}
    assert r.charged() == Decimal("0.02")
    r.close()
    r = runtime(tmp_path, handler)
    assert call(r) == {}
    assert len(requests) == 2
    assert r.state["calls"]["a"]["charged"] == "0.01"
    r.close()


def test_recovery_cannot_bypass_budget_or_retry_network_failure(tmp_path):
    r = runtime(tmp_path, lambda _: httpx.Response(401, json={}))
    with pytest.raises(PilotStop, match="HTTP 401"):
        call(r, amount="0.20")
    r.state["calls"]["a"].update(status="rejected", http_status=401, recovery_key="a/recovery-1")
    with pytest.raises(PilotStop, match="Budget reached"):
        call(r, amount="0.20")
    r.state["calls"]["a"]["http_status"] = None
    with pytest.raises(PilotStop, match="uncertain outcome"):
        call(r)
    r.close()


def test_overcharge_blocks_all_new_paid_requests(tmp_path):
    r = runtime(tmp_path, lambda _: httpx.Response(200, json={"usage": {"cost": 0.02}}))
    with pytest.raises(PilotStop, match="exceeded reservation"):
        call(r)
    with pytest.raises(PilotStop, match="reconciliation"):
        call(r, "b")
    assert r.charged() == Decimal("0.02")
    r.close()


def test_changed_cached_inputs_blocked(tmp_path):
    r = runtime(tmp_path, lambda _: httpx.Response(200, json={}))
    call(r)
    with pytest.raises(PilotStop, match="inputs changed"):
        r.paid("a", "textiles-custom", "parallel", "/v1/search", {"changed": True}, Decimal("0.01"))
    r.close()


def fixture_evidence():
    text = "Fictional Mills manufactures cotton apparel in Tiruppur. "
    text += "Fictional Mills contact: hello@example.com or +91 12345 67890."
    sources = {
        "s1": {"url": "https://example.com/contact", "text": text, "retrieved_at": "2026-10-03"}
    }
    answer = {
        "criteria": [
            {
                "criterion": "manufacturer",
                "status": "supported",
                "source_id": "s1",
                "quote": "Fictional Mills manufactures cotton apparel in Tiruppur.",
            }
        ],
        "contacts": [
            {
                "kind": "email",
                "value": "hello@example.com",
                "source_id": "s1",
                "quote": "contact: hello@example.com",
                "association_quote": "Fictional Mills contact:",
            }
        ],
    }
    return sources, answer


def test_supported_contact_remains_pending_not_campaign_ready():
    sources, answer = fixture_evidence()
    result = validate_assessment({}, answer, sources, {"manufacturer": "makes garments"})
    assert result["email_candidate"]
    assert not result["campaign_ready"]
    assert result["review_status"] == "pending"


def test_exact_criterion_description_is_accepted_but_ambiguity_is_unknown():
    sources, answer = fixture_evidence()
    criterion = {"manufacturer": "Manufactures garments, not only a trader."}
    answer["criteria"][0]["criterion"] = criterion["manufacturer"]
    result = validate_assessment({}, answer, sources, criterion)
    assert result["criteria"][0]["status"] == "supported"
    answer["criteria"][0]["criterion"] = criterion["manufacturer"].removesuffix(".")
    result = validate_assessment({}, answer, sources, criterion)
    assert result["criteria"][0]["status"] == "supported"
    answer["criteria"].append({**answer["criteria"][0], "criterion": "manufacturer"})
    result = validate_assessment({}, answer, sources, criterion)
    assert result["criteria"][0]["status"] == "unknown"
    answer["criteria"] = [{**answer["criteria"][0], "criterion": "manufacturer-ish"}]
    result = validate_assessment({}, answer, sources, criterion)
    assert result["criteria"][0]["status"] == "unknown"


@pytest.mark.parametrize("mutation", ["invented", "wrong_source", "association", "criterion"])
def test_missing_evidence_cannot_become_email_candidate(mutation):
    sources, answer = fixture_evidence()
    if mutation == "invented":
        answer["contacts"][0]["value"] = "guessed@example.com"
    elif mutation == "wrong_source":
        answer["contacts"][0]["source_id"] = "s99"
    elif mutation == "association":
        answer["contacts"][0]["association_quote"] = ""
    else:
        answer["criteria"][0]["quote"] = "Fictional Mills buys our sewing thread."
    result = validate_assessment({}, answer, sources, {"manufacturer": "makes garments"})
    assert not result["email_candidate"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
        "http://host.internal/",
        "http://example.com:22/",
    ],
)
def test_unsafe_urls_rejected(url):
    assert public_url(url) is None


def test_model_output_shape_checked_locally():
    with pytest.raises(PilotStop):
        validate_shape({"search_queries": "not an array"}, PLAN_SCHEMA)


def test_missing_key_never_reserves_or_calls(tmp_path):
    r = runtime(tmp_path, lambda _: pytest.fail("unexpected network"))
    r.config["parallel"] = ""
    with pytest.raises(PilotStop, match="Missing"):
        call(r)
    assert r.charged() == 0
    r.close()


@pytest.mark.parametrize("mode", ["custom", "findall"])
def test_research_flow_and_resume_with_fictional_provider_responses(tmp_path, mode):
    from experiments.research_pilot import Research

    requests = []
    sources, answer = fixture_evidence()
    answer["criteria"].append({**answer["criteria"][0], "criterion": "location"})
    answer.update(fit_inference="Potential fit only.", unknowns=["Buying intent unknown."])

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/search"):
            data = {
                "results": [{"url": "https://example.com/", "excerpts": [sources["s1"]["text"]]}]
            }
        elif path.endswith("/extract"):
            data = {
                "results": [{"url": "https://example.com/", "full_content": sources["s1"]["text"]}]
            }
        elif path.endswith("/runs"):
            data = {"findall_id": "findall_fake"}
        elif path.endswith("/findall_fake"):
            data = {"status": {"is_active": False}}
        elif path.endswith("/result"):
            data = {
                "candidates": [
                    {
                        "name": "Fictional Mills",
                        "url": "https://example.com/",
                        "match_status": "matched",
                    },
                    {
                        "name": "Pending Co",
                        "url": "https://example.org/",
                        "match_status": "pending",
                    },
                ]
            }
        else:
            body = json.loads(request.content)
            if "Select at most" in body["messages"][1]["content"]:
                content = {
                    "candidates": [
                        {
                            "company": "Fictional Mills",
                            "website": "https://example.com/",
                            "source_id": "s1",
                        }
                    ]
                }
            else:
                content = answer
            data = {
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"cost": 0.001},
            }
        return httpx.Response(200, json=data)

    r = runtime(tmp_path, handler)
    plan = {
        "search_queries": ["fictional manufacturer"],
        "alternate_queries": ["fictional directory"],
    }
    result = Research(r, "textiles", mode).run(plan)
    assert result["discovered"] == result["assessed"] == 1
    assert result["email_candidates_pending_review"] == 1
    assert result["human_verified_usable_leads"] is None
    count = len(requests)
    r.close()
    r = runtime(tmp_path, handler)
    assert Research(r, "textiles", mode).run(plan) == result
    assert len(requests) == count
    r.close()
