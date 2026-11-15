"""The live benchmark must share the original budget and never replay uncertainty."""

from decimal import Decimal

import httpx
import pytest
from experiments.founder_benchmark import (
    ARM,
    FounderProfile,
    PilotBoundedAPI,
    profile_context,
    validate_profile,
)
from experiments.pilot_runtime import Runtime

from outreach.core.research import ResearchStop, text_windows
from tests.test_platform import db_for, fake_provider


@pytest.fixture
def benchmark(settings, tmp_path):
    settings = settings.model_copy(
        update={"parallel_api_key": "fake", "openrouter_api_key": "fake"}
    )
    calls = []
    with db_for(settings) as db:
        key = db.new_run(
            title="Founders",
            brief="Find AI startup founders.",
            purpose="job search",
            tags="",
            project_id=None,
            target=3,
            budget=200000,
        )
        db.set_run(key, status="running")
        runtime = Runtime(tmp_path / "pilot", {"parallel": "unused", "openrouter": "unused"})
        api = PilotBoundedAPI(
            settings,
            db,
            key,
            runtime=runtime,
            client=httpx.Client(transport=httpx.MockTransport(fake_provider(calls))),
        )
        yield api, runtime, calls
        api.close()
        runtime.close()


@pytest.mark.parametrize("arm,charge", [("original-comparison", ".9995"), (ARM, ".1995")])
def test_existing_total_and_arm_charges_block_http(benchmark, arm, charge):
    api, runtime, calls = benchmark
    runtime.state["calls"]["old"] = {"arm": arm, "charged": charge, "status": "complete"}
    with pytest.raises(ResearchStop, match="Budget"):
        api.search("one", "founders", ["Bangalore AI founders"])
    assert not calls and api.store.call(api.run_id, "one") is None


def test_completed_calls_are_cached_in_both_ledgers(benchmark):
    api, runtime, calls = benchmark
    first = api.search("one", "founders", ["Bangalore AI founders"])
    assert api.search("one", "founders", ["Bangalore AI founders"]) == first
    assert len(calls) == 1 and runtime.charged() == Decimal(".001")
    with pytest.raises(ResearchStop, match="checkpoint"):
        api.search("one", "different input", ["Bangalore AI founders"])
    assert len(calls) == 1


def test_uncertain_call_retains_both_reservations_and_blocks_replay(benchmark):
    api, runtime, calls = benchmark
    attempts = []

    def timeout(request):
        attempts.append(request)
        raise httpx.ReadTimeout("synthetic timeout")

    api.client.close()
    api.client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(ResearchStop, match="reservation"):
        api.search("one", "founders", ["Bangalore AI founders"])
    with pytest.raises(ResearchStop, match="checkpoint"):
        api.search("one", "founders", ["Bangalore AI founders"])
    assert len(attempts) == 1 and not calls
    assert runtime.charged() == Decimal(".001")
    assert api.store.call(api.run_id, "one")["status"] == "reserved"


@pytest.mark.parametrize("path,count", [("/v1/search", 8), ("/v1/extract", 20)])
def test_request_and_page_limits_include_previous_records(benchmark, path, count):
    api, runtime, calls = benchmark
    for i in range(count):
        runtime.state["calls"][str(i)] = {
            "arm": ARM,
            "charged": ".001",
            "status": "complete",
            "path": path,
            "url_count": int(path == "/v1/extract"),
        }
    with pytest.raises(ResearchStop, match="limit"):
        if path == "/v1/search":
            api.search("one", "founders", ["Bangalore AI founders"])
        else:
            api.extract("one", ["https://example.com/"])
    assert not calls


def test_founder_excerpt_survives_repeated_demo_terminal_addresses():
    text = ("dev@macbook terminal demo " * 400) + "Asha Rao, Founder of Example AI."
    text += "Product documentation " * 400
    assert "Asha Rao, Founder of Example AI." in profile_context(text)


def test_production_excerpt_prioritises_founder_and_real_email_over_terminal_examples():
    text = "dev@macbook terminal demo " * 400
    text += "Asha Rao, Founder of Example AI. "
    text += "Product documentation " * 100
    text += "Contact Asha Rao at asha@sample.example. "
    text += "Product documentation " * 400
    excerpt = text_windows(text, 2500)
    assert "Asha Rao, Founder of Example AI." in excerpt
    assert "asha@sample.example" in excerpt
    assert len(excerpt) <= 2500


@pytest.mark.parametrize(
    "email,expected",
    [
        ("asha@sample.example", True),
        ("asha.rao@sample.example", False),
        ("hello@sample.example", False),
    ],
)
def test_founder_email_requires_named_literal_contact_not_pattern_or_general_inbox(email, expected):
    text = (
        "Asha Rao is the founder of Example AI. "
        "Contact Asha Rao at asha@sample.example. "
        "General office Asha Rao hello@sample.example. "
        "Example AI builds a voice transcription product."
    )
    profile = FounderProfile(
        founder_name="Asha Rao",
        founder_source_id="s1",
        founder_quote="Asha Rao is the founder of Example AI.",
        email=email,
        email_source_id="s1",
        email_quote=(
            "General office Asha Rao hello@sample.example."
            if email.startswith("hello")
            else "Contact Asha Rao at asha@sample.example."
        ),
        email_association_quote=(
            "General office Asha Rao hello@sample.example."
            if email.startswith("hello")
            else "Contact Asha Rao at asha@sample.example."
        ),
        personalisation=[
            {
                "summary": "Voice product",
                "source_id": "s1",
                "quote": "Example AI builds a voice transcription product.",
            },
            {
                "summary": "Unsupported funding",
                "source_id": "s1",
                "quote": "Example AI raised ten million dollars.",
            },
        ],
        unknowns=[],
    )
    checks = validate_profile(
        profile, {"s1": {"url": "https://sample.example/team", "text": text, "retrieved_at": "now"}}
    )
    assert checks["direct_founder_email_evidence_valid"] is expected
    assert len(checks["personalisation_facts"]) == 1
    assert checks["review_status"] == "pending" and not checks["campaign_ready"]
