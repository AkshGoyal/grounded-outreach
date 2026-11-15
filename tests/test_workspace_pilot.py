"""The production research test must obey the original ledger as well as SQLite."""

from decimal import Decimal

import httpx
import pytest
from experiments.pilot_runtime import PilotStop, Runtime
from experiments.workspace_pilot import ARM, bridge

from outreach.adapters.research_api import ResearchAPI
from outreach.core.research import ResearchStop
from tests.test_platform import db_for


def setup_bridge(settings, tmp_path, initial=".50"):
    calls = []

    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"results": []})

    runtime = Runtime(
        tmp_path / "pilot",
        {"parallel": "fake", "openrouter": "fake", "model": "fake"},
        client=httpx.Client(transport=httpx.MockTransport(response)),
    )
    runtime.state["calls"]["prior"] = {"arm": "prior", "charged": initial, "status": "complete"}
    runtime.save()
    config = settings.model_copy(update={"parallel_api_key": "fake", "openrouter_api_key": "fake"})
    db = db_for(config)
    key = db.new_run(
        title="Test",
        brief="Approved research test",
        purpose="job search",
        tags="",
        project_id=None,
        target=1,
        budget=120000,
    )
    db.set_run(key, status="running")
    api = ResearchAPI(config, db, key, client=bridge(runtime, db, key))
    return runtime, db, key, api, calls


def test_bridge_records_both_ledgers_and_reuses_production_cache(settings, tmp_path):
    runtime, db, key, api, calls = setup_bridge(settings, tmp_path)
    try:
        first = api.search("first", "Approved test", ["AI startups"])
        assert api.search("first", "Approved test", ["AI startups"]) == first
        assert calls == ["/v1/search"]
        assert runtime.charged() == Decimal(".501")
        assert runtime.charged(ARM) == Decimal(".001")
        assert db.run(key)["spent_micro"] == 1000
    finally:
        api.close()
        db.close()
        runtime.close()


def test_exhausted_original_ledger_blocks_production_network(settings, tmp_path):
    runtime, db, key, api, calls = setup_bridge(settings, tmp_path, initial="1.00")
    try:
        with pytest.raises(ResearchStop, match="Budget reached"):
            api.search("first", "Approved test", ["AI startups"])
        assert not calls and runtime.charged() == Decimal("1.00")
        assert db.call(key, "first")["status"] == "reserved"
        with pytest.raises(ResearchStop, match="uncertain"):
            api.search("first", "Approved test", ["AI startups"])
        assert not calls
    finally:
        api.close()
        db.close()
        runtime.close()


def test_bridge_cannot_send_without_production_reservation(settings, tmp_path):
    runtime, db, key, api, calls = setup_bridge(settings, tmp_path)
    try:
        with pytest.raises(PilotStop, match="reserved"):
            api.client.post("https://api.parallel.ai/v1/search", json={})
        assert not calls and runtime.charged() == Decimal(".50")
    finally:
        api.close()
        db.close()
        runtime.close()
