"""Named-person research through real routes/worker/storage, with fictional HTTP only."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.workbench_fixture import FIXTURE_RESPONSE, FixtureResearchProvider
from outreach.adapters.workbench_research import SourcePolicy
from outreach.config import Settings
from outreach.wiring import build_workbench_app
from tests.test_workbench_parallel import PublicSources, public_resolver
from tests.test_workbench_spine import payload, settled, start


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "workbench.db"),
        parallel_api_key="fictional",
        openrouter_api_key="fictional",
    )


def live_app(config, fake, **kwargs):
    return build_workbench_app(
        config,
        mode="live",
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake)),
        **kwargs,
    )


def test_live_profile_requires_explicit_consent_and_preserves_input(config):
    fake = PublicSources()
    app = live_app(config, fake)
    with TestClient(app) as client:
        page = client.get("/research/new")
        assert 'class="mode-label">Live' in page.text
        assert 'value="Maya Rao"' not in page.text
        assert "live_consent" in page.text and "$0.05" in page.text
        invalid = client.post("/research", data=payload())
        assert invalid.status_code == 422 and 'value="Maya Rao"' in invalid.text
        assert not fake.calls
        with app.state.open_workbench_store() as db:
            assert not db.list_workbench_runs()


def test_live_named_prospect_without_email_reaches_attributed_hook(config):
    fake = PublicSources(restricted=True)
    app = live_app(config, fake)
    with TestClient(app) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        assert run["execution_status"] == "completed", run["result"]
        assert run["business_outcome"] == "ready_for_review", run["result"]
        assert run["mode"] == "live" and not run["prospect"]["email"]
        assert run["draft"]["origin"] == "model" and run["draft"]["supported"]
        # identity, news, one more news search (only one fact found), draft; no repair
        assert run["usage"]["model_requests"] == 4
        assert any(
            c["support_id"] in run["result"]["hook"]["source_ids"] for c in run["draft"]["claims"]
        )
        assert run["result"]["hook"]["source_ids"]
        assert run["result"]["limitations"]
        assert run["usage"]["search_queries"] <= 12
        assert run["usage"]["pages"] <= 8
        assert run["usage"]["spent_micro"] <= 100000
        page = client.get(path)
        assert page.status_code == 200
        assert 'class="mode-label">Live' in page.text
        assert "Source limitations" in page.text and "Not used as proof" in page.text
        assert "Published" in page.text and "Event date" in page.text
        assert 'rel="noopener noreferrer"' in page.text
        assert "Approve draft" in page.text and "Check edits" in page.text
        before = len(fake.calls)
        client.get(path)
        client.get(path + "/status")
        assert path in client.get("/history").text
        assert len(fake.calls) == before
        for url in ("/accounts", "/inbox", "/campaigns/fake/send"):
            assert client.get(url).status_code == 404


def test_uncertain_model_request_keeps_read_sources_and_never_replays_on_restart(config):
    fake = PublicSources(timeout_at=3)
    app = live_app(config, fake)
    with TestClient(app) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        # The model step is held, never replayed; the run still finishes from the page
        # that was read, with a free template email.
        assert run["execution_status"] == "completed"
        assert run["source_records"] and run["result"]["sources"]
        assert run["usage"]["held_requests"] == 1
        assert any("Research stopped early" in n for n in run["result"]["limitations"])
        assert run["result"]["identity"]["status"] == "matched"
        assert run["result"]["hook"]["strength"] == "weak"
        assert run["draft"]["origin"] == "template"
        assert len(fake.calls) == 3
    with TestClient(live_app(config, fake)) as client:
        saved = client.get(path + "/status").json()
        assert saved["usage"]["held_requests"] == 1
        assert saved["source_records"] == run["source_records"]
        assert len(fake.calls) == 3


class AmbiguousFixture(FixtureResearchProvider):
    def research(self, prospect):
        bundle = deepcopy(FIXTURE_RESPONSE)
        other = deepcopy(bundle["sources"][0])
        other.update(
            id="other-leadership",
            url="https://other-works.example/leadership",
            text="Maya Rao is Finance Director at Other Works.",
            passage="",
        )
        bundle["sources"].append(other)
        candidate = deepcopy(bundle["identity_candidates"][0])
        candidate.update(
            company="Other Works",
            domain="other-works.example",
            source_id="other-leadership",
            quote=other["text"],
        )
        bundle["identity_candidates"].append(candidate)
        return bundle


def waiting_identity(client):
    path = start(client)
    run = settled(client, path)
    assert run["business_outcome"] == "needs_identity_confirmation", run["result"]
    candidates = run["result"]["identity"]["candidates"]
    allowed = next(c for c in candidates if c["selectable"])
    rejected = next(c for c in candidates if not c["selectable"])
    return path, run, allowed, rejected


def test_confirmation_rejects_wrong_identity_and_stale_proof_then_continues(config):
    app = build_workbench_app(config, provider=AmbiguousFixture())
    with TestClient(app) as client:
        path, run, allowed, rejected = waiting_identity(client)
        assert "Confirm prospect" in client.get(path).text
        assert (
            client.post(
                path + "/confirm-prospect",
                data={
                    "candidate_id": rejected["id"],
                    "evidence_version": run["evidence_version"],
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                path + "/confirm-prospect",
                data={
                    "candidate_id": allowed["id"],
                    "evidence_version": "stale-proof",
                },
            ).status_code
            == 409
        )
        accepted = client.post(
            path + "/confirm-prospect",
            data={
                "candidate_id": allowed["id"],
                "evidence_version": run["evidence_version"],
            },
            follow_redirects=False,
        )
        assert accepted.status_code == 303
        finished = settled(client, path)
        assert finished["business_outcome"] == "ready_for_review", finished["result"]
        assert finished["confirmation"]["candidate_id"] == allowed["id"]
        assert not any("other" in s for s in finished["result"]["hook"]["source_ids"])
        with app.state.open_workbench_store() as db:
            assert len(db.list_workbench_runs()) == 1


def test_confirmation_refuses_held_request_without_turning_it_into_server_error(config):
    app = build_workbench_app(config, provider=AmbiguousFixture())
    with TestClient(app) as client:
        path, run, allowed, _ = waiting_identity(client)
        with app.state.open_workbench_store() as db:
            db.conn.execute(
                "INSERT INTO research_calls "
                "(run_id,call_key,fingerprint,status,reserved_micro,charged_micro,created_at) "
                "VALUES (?,'held','fictional','reserved',1000,1000,?)",
                (run["id"], run["created_at"]),
            )
        response = client.post(
            path + "/confirm-prospect",
            data={
                "candidate_id": allowed["id"],
                "evidence_version": run["evidence_version"],
            },
        )
        assert response.status_code == 409
        assert client.get(path + "/status").json()["execution_status"] == "completed"


def test_changed_identity_proof_during_confirmation_invalidates_the_selection(config):
    class ChangingProof(AmbiguousFixture):
        def __init__(self):
            self.calls = 0

        def research(self, prospect):
            bundle = super().research(prospect)
            self.calls += 1
            if self.calls > 1:
                bundle["sources"][0]["text"] += " New identity evidence was added."
            return bundle

    app = build_workbench_app(config, provider=ChangingProof())
    with TestClient(app) as client:
        path, run, allowed, _ = waiting_identity(client)
        response = client.post(
            path + "/confirm-prospect",
            data={
                "candidate_id": allowed["id"],
                "evidence_version": run["evidence_version"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        updated = settled(client, path)
        assert updated["business_outcome"] == "needs_identity_confirmation"
        assert not updated["confirmation"] and not updated["result"]["hook"]


def test_try_another_source_keeps_prospect_and_requires_new_consent(config):
    fake = PublicSources(sparse=True)

    def nothing_readable(request):
        if request.url.path.endswith("/extract"):
            return httpx.Response(200, json={"errors": [{"status_code": 403}], "results": []})
        return fake(request)

    with TestClient(live_app(config, nothing_readable)) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        assert run["result"]["hook"]["basis"] == "as_entered"
        assert run["draft"] and "Not personalised" in client.get(path).text
        assert "Try another source" in client.get(path).text
        page = client.get("/research/new?from_run=" + run["id"])
        assert 'value="Maya Rao"' in page.text
        assert 'name="live_consent" required' in page.text
        assert 'name="live_consent" required checked' not in page.text


def test_confirmation_cannot_research_live_record_using_fixture_runtime(config):
    app = build_workbench_app(config, mode="live", provider=AmbiguousFixture())
    with TestClient(app) as client:
        path = start(client, payload(live_consent="on"))
        settled(client, path)
    with TestClient(build_workbench_app(config, mode="fixture")) as client:
        assert client.post(path + "/confirm-prospect", data={}).status_code == 409


def test_live_profile_without_keys_disables_form_and_never_starts_worker(config):
    config = config.model_copy(update={"parallel_api_key": None, "openrouter_api_key": None})
    fake = PublicSources()
    app = live_app(config, fake)
    with TestClient(app) as client:
        assert "disabled>Start research" in client.get("/research/new").text
        assert client.post("/research", data=payload(live_consent="on")).status_code == 422
        assert not fake.calls


def test_live_launcher_requires_keys_but_does_not_start_work(tmp_path, monkeypatch):
    from outreach import workbench

    keys = tmp_path / "fake.env"
    keys.write_text("OUTREACH_PARALLEL_API_KEY=fictional\nOUTREACH_OPENROUTER_API_KEY=fictional\n")
    monkeypatch.setattr(
        "sys.argv",
        [
            "workbench",
            "--mode",
            "live",
            "--credential-file",
            str(keys),
            "--data-dir",
            str(tmp_path),
            "--port",
            "8782",
        ],
    )
    captured = {}

    def factory(settings, **kwargs):
        captured.update(kwargs)
        assert settings.parallel_api_key == "fictional"
        return object()

    monkeypatch.setattr(workbench, "build_workbench_app", factory)
    monkeypatch.setattr(workbench.uvicorn, "run", lambda app, **kw: captured.update(kw))
    workbench.main()
    assert captured["mode"] == "live" and captured["limits"]["budget_micro"] == 50000
    assert captured["workers"] == 1


def test_refused_confirmation_is_explained_on_the_saved_run_page(config):
    app = build_workbench_app(config, provider=AmbiguousFixture())
    with TestClient(app) as client:
        path, run, allowed, rejected = waiting_identity(client)
        for candidate_id, version in (
            (rejected["id"], run["evidence_version"]),
            (allowed["id"], "stale-proof"),
        ):
            response = client.post(
                path + "/confirm-prospect",
                data={"candidate_id": candidate_id, "evidence_version": version},
            )
            assert response.status_code == 409
            assert "text/html" in response.headers["content-type"]
            assert "Confirmation not accepted" in response.text
            assert "Confirm the prospect" in response.text
        saved = client.get(path + "/status").json()
        assert saved["business_outcome"] == "needs_identity_confirmation"
        assert not saved["confirmation"]


def test_one_malformed_model_candidate_is_dropped_not_fatal(config):
    fake = PublicSources(junk_candidate=True)
    app = live_app(config, fake)
    with TestClient(app) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["execution_status"] == "completed", run["result"]
        assert run["business_outcome"] == "ready_for_review", run["result"]
        assert any(
            "identity candidate from the research model lacked a usable quote" in note
            for note in run["result"]["limitations"]
        ), run["result"]["limitations"]
        assert run["usage"]["model_requests"] == 4


def test_salvage_rejects_a_response_that_is_not_findings():
    from outreach.core.workbench_evidence import IdentityFindings

    with pytest.raises(ValueError):
        IdentityFindings.salvage('{"answer": []}')
    kept = IdentityFindings.salvage('{"identity_candidates": [{"name": "x"}]}')
    assert kept.identity_candidates == [] and kept.dropped == 1


def test_rejected_draft_model_keeps_hook_and_write_draft_recovers(config):
    # Seen live: OpenRouter answered HTTP 404 for the draft model. Nothing was charged,
    # the hook was saved, and the page must offer "Write the draft".
    fake = PublicSources()
    rejected = {"on": True}

    def provider(request):
        body = json.loads(request.content)
        schema = (body.get("response_format") or {}).get("json_schema", {}).get("name")
        if schema == "draftoutput" and rejected["on"]:
            fake.calls.append((request.url.path, body))
            return httpx.Response(404, json={"error": {"message": "No such model"}})
        return fake(request)

    app = live_app(config, provider)
    with TestClient(app) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        # Every draft model was refused at no cost, so the free template wrote the email.
        assert run["result"]["hook"] and run["usage"]["held_requests"] == 0
        assert run["draft"]["origin"] == "template"
        assert any("built-in template" in note for note in run["result"]["limitations"])
        page = client.get(path).text
        assert "data-write-draft" in page and "Nothing was charged" in page
        rejected["on"] = False
        response = client.post(path + "/draft/write", follow_redirects=False)
        assert response.status_code == 303, response.text
        run = client.get(path + "/status").json()
        assert run["draft"]["origin"] == "model" and len(run["drafts"]) == 2
        assert run["execution_status"] == "completed"
        with app.state.open_workbench_store() as db:
            keys = {row["call_key"] for row in db.rows("SELECT call_key FROM research_calls")}
        assert {"workbench/draft/model", "workbench/draft-2/model"} <= keys
        again = client.post(path + "/draft/write", follow_redirects=False)
        assert again.status_code == 409 and "already has a draft" in again.text


def test_history_rows_open_the_run_and_say_what_is_next(config):
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        path = start(client, payload(live_consent="on"))
        settled(client, path)
        page = client.get("/history").text
        assert f'class="history-open" href="{path}"' in page
        assert "Review the draft" in page


def test_refused_model_falls_back_to_the_next_one_at_no_cost(config):
    config = config.model_copy(
        update={
            "workbench_research_models": "vendor/reader-a,vendor/reader-b",
            "workbench_draft_models": "vendor/writer-a,vendor/reader-a,vendor/reader-b",
        }
    )
    fake = PublicSources()
    first = config.workbench_research_models.split(",")[0]
    writer = config.workbench_draft_models.split(",")[0]

    def provider(request):
        body = json.loads(request.content)
        if body.get("model") in (first, writer):
            fake.calls.append((request.url.path, body))
            return httpx.Response(404, json={"error": {"message": "No endpoints found"}})
        return fake(request)

    app = live_app(config, provider)
    with TestClient(app) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["business_outcome"] == "ready_for_review", run["result"]
        assert run["usage"]["held_requests"] == 0
        # identity, signal and draft each did real work once; refusals use no quota.
        assert run["usage"]["model_requests"] == 4
        with app.state.open_workbench_store() as db:
            rows = db.rows(
                "SELECT call_key,cost_kind,charged_micro,response_json FROM research_calls"
            )
        refused = [r for r in rows if r["cost_kind"] == "rejected"]
        # research model refused three times (identity, news, news follow-up); the draft
        # chain skips two models.
        assert len(refused) == 5 and all(r["charged_micro"] == 0 for r in refused)
        assert "No endpoints found" in refused[0]["response_json"]
        assert {"workbench/identity/model~2", "workbench/signal/model~2", "workbench/draft/model~3"} <= {
            r["call_key"] for r in rows
        }


def test_claude_5_models_are_not_sent_a_temperature():
    from outreach.adapters.research_api import _accepts_temperature

    assert not _accepts_temperature("anthropic/claude-haiku-5.5")
    assert not _accepts_temperature("anthropic/claude-sonnet-5.5")
    assert _accepts_temperature("anthropic/claude-haiku-4.5")


def test_requests_to_newer_models_omit_temperature(config):
    config = config.model_copy(
        update={
            "workbench_research_models": "anthropic/claude-haiku-5.5,deepseek/deepseek-v4.1-flash",
            "workbench_draft_models": "deepseek/deepseek-v4.1-flash",
        }
    )
    fake = PublicSources()
    seen = []

    def provider(request):
        body = json.loads(request.content)
        if "model" in body:
            seen.append(body)
        return fake(request)

    with TestClient(live_app(config, provider)) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["business_outcome"] == "ready_for_review"
    first = {body["model"]: body for body in seen}
    assert "temperature" not in first["anthropic/claude-haiku-5.5"]
    assert first[config.workbench_draft_models.split(",")[0]]["temperature"] == 0


def test_unusable_model_answer_moves_to_the_next_model(config):
    # Seen live: a reasoning model used its whole allowance thinking and returned no answer.
    config = config.model_copy(
        update={
            "workbench_research_models": "deepseek/thinker,vendor/reader",
            "workbench_draft_models": "deepseek/thinker,vendor/reader",
        }
    )
    fake = PublicSources()
    bodies = []

    def provider(request):
        body = json.loads(request.content)
        if body.get("model") == "deepseek/thinker":
            bodies.append(body)
            fake.calls.append((request.url.path, body))
            return httpx.Response(
                200,
                json={
                    "usage": {"cost": 0.0005},
                    "choices": [{"finish_reason": "length", "message": {"content": None}}],
                },
            )
        return fake(request)

    with TestClient(live_app(config, provider)) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["business_outcome"] == "ready_for_review", run["result"]
        assert run["draft"]["origin"] == "model" and run["usage"]["held_requests"] == 0
        assert not any("stopped early" in n for n in run["result"]["limitations"])
        assert run["usage"]["model_requests"] == 8  # four steps, two models each
    assert bodies and all(b["reasoning"] == {"effort": "low"} for b in bodies)
    assert all(b["provider"]["max_price"]["completion"] == 5 for b in bodies)


def test_search_excerpts_confirm_identity_without_paid_page_reads_or_model(config):
    fake = PublicSources()

    def provider(request):
        response = fake(request)
        if request.url.path.endswith("/search"):
            data = response.json()
            for item in data["results"]:
                item.pop("full_content", None)
                item["excerpts"] = [
                    "Maya Rao is Finance Director at Cedar Works and oversees invoice review."
                ]
            return httpx.Response(200, json=data)
        return response

    app = live_app(config, provider)
    with TestClient(app) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["result"]["identity"]["status"] == "matched"
        excerpt = run["result"]["identity"]["selected"]["source_id"]
        assert excerpt.startswith("excerpt-")
        with app.state.open_workbench_store() as db:
            keys = [r["call_key"] for r in db.rows("SELECT call_key FROM research_calls")]
        assert not any(k.startswith("workbench/identity/extract") for k in keys)
        assert "workbench/identity/model" not in keys
        assert "Seen in a search excerpt" in str(run["result"]["hook"]["judgement"]) or run[
            "result"
        ]["hook"]["source_ids"] != [excerpt]


def test_model_reservation_uses_the_model_price_so_thorough_fits_the_cap():
    # Seen live: a thorough run's research step reserved $0.047 at a $1/$5 ceiling and was
    # stopped by the $0.05 cap. At Haiku 5.5's own ceiling the same request reserves cents.
    from outreach.adapters.workbench_research import _price_cap

    cap = _price_cap("anthropic/claude-haiku-5.5")
    assert cap == {"prompt": 0.125, "completion": 0.625}
    input_tokens = 30_000 // 3 + 1024
    reserve = int(input_tokens * cap["prompt"] + 3000 * cap["completion"])
    assert reserve < 5_000  # under half a cent of the $0.05 run limit
    assert _price_cap("vendor/unknown") == {"prompt": 1, "completion": 5}


def test_thorough_live_run_drafts_with_a_model_inside_the_cap(config):  # noqa: F811
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        run = settled(
            client,
            start(client, payload(live_consent="on", options="1", use_goal="on", write_draft="on")),
        )
        assert run["limits"]["thorough"] == 1
        assert run["draft"]["origin"] in ("model", "repair")
        assert not any("Spending limit" in n for n in run["result"]["limitations"])
