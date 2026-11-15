"""Draft review through real routes, worker and storage. Fictional providers only."""

import re

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.workbench_fixture import FixtureDraftWriter
from outreach.adapters.workbench_research import SourcePolicy
from outreach.config import Settings
from outreach.wiring import build_workbench_app
from tests.test_workbench_parallel import PublicSources, public_resolver
from tests.test_workbench_spine import payload, settled, start

BAD_SENTENCE = "Because Cedar Works is clearly struggling with invoice errors, you need help."


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "workbench.db"),
        parallel_api_key="fictional",
        openrouter_api_key="fictional",
    )


def ready_run(client):
    path = start(client)
    run = settled(client, path)
    assert run["business_outcome"] == "ready_for_review", run["result"]
    assert run["review"]["state"] == "ready_for_review"
    return path, run


def approve(client, path, draft):
    return client.post(
        path + "/draft/approve",
        data={"revision": draft["revision"], "content_hash": draft["content_hash"]},
        follow_redirects=False,
    )


def check(client, path, draft, *, subject=None, body=None, base=None):
    return client.post(
        path + "/draft/check",
        data={
            "subject": draft["subject"] if subject is None else subject,
            "body": draft["body"] if body is None else body,
            "base_revision": draft["revision"] if base is None else base,
        },
        follow_redirects=False,
    )


def test_fixture_run_drafts_with_citations_and_export_requires_exact_approval(config):
    with TestClient(build_workbench_app(config)) as client:
        path, run = ready_run(client)
        draft = run["draft"]
        assert draft["origin"] == "fixture" and draft["revision"] == 1
        page = client.get(path).text
        assert ">Email</h2>" in page and "version 1, example draft" in page
        assert "not part of the copied email" in page and "fixture-invoice-review" in page
        assert 'href="#source-fixture-invoice-review"' in page  # citation opens its source
        assert re.search(r'<button type="submit" class="primary-action"\s*>Approve draft', page)
        assert client.get(path + "/export").status_code == 409
        forged = client.post(
            path + "/draft/approve", data={"revision": 1, "content_hash": "0" * 64}
        )
        assert forged.status_code == 409 and "Draft not approved" in forged.text
        assert client.get(path + "/export").status_code == 409
        assert approve(client, path, draft).status_code == 303
        approved = client.get(path + "/status").json()
        assert approved["review"]["state"] == "approved"
        assert approved["business_outcome"] == "approved"
        exported = client.get(path + "/export")
        assert exported.status_code == 200
        assert exported.text == f"Subject: {draft['subject']}\n\n{draft['body']}\n"
        assert "fixture-invoice-review" not in exported.text  # citations stay with the reviewer
        download = client.get(path + "/export?download=1")
        assert "attachment" in download.headers["content-disposition"]
        assert "Copy approved draft" in client.get(path).text
        assert ">Approved<" in client.get("/history").text


def test_edit_invalidates_approval_and_bad_edit_is_blocked(config):
    with TestClient(build_workbench_app(config)) as client:
        path, run = ready_run(client)
        original = run["draft"]
        assert approve(client, path, original).status_code == 303
        bad_body = original["body"].replace("That may be relevant", BAD_SENTENCE + " That may be")
        assert check(client, path, original, body=bad_body).status_code == 303
        edited = client.get(path + "/status").json()
        assert edited["draft"]["revision"] == 2 and edited["draft"]["origin"] == "reviewer"
        assert edited["review"]["state"] == "needs_revision"
        assert edited["business_outcome"] == "needs_revision"
        assert client.get(path + "/export").status_code == 409  # stale approval
        assert approve(client, path, original).status_code == 409  # old revision
        assert approve(client, path, edited["draft"]).status_code == 409  # blocked claims
        codes = {i["code"] for i in edited["draft"]["check"]["errors"]}
        assert {"unsupported_causal", "unsupported_pain", "unsupported_intent"} <= codes
        page = client.get(path).text
        assert "Blocks approval" in page and "states a cause or purpose" in page
        assert re.search(r"Approve draft", page) and "disabled" in page
        # Removing the unsupported wording passes again, but needs a fresh approval.
        assert check(client, path, edited["draft"], body=original["body"]).status_code == 303
        fixed = client.get(path + "/status").json()
        assert fixed["review"]["state"] == "ready_for_review" and fixed["draft"]["revision"] == 3
        assert client.get(path + "/export").status_code == 409
        assert approve(client, path, fixed["draft"]).status_code == 303
        assert client.get(path + "/export").text.startswith("Subject: ")


def test_concurrent_edit_is_refused_and_preserves_reviewer_text(config):
    with TestClient(build_workbench_app(config)) as client:
        path, run = ready_run(client)
        draft = run["draft"]
        assert check(client, path, draft, subject=draft["subject"] + " update").status_code == 303
        stale = check(client, path, draft, subject="My unsaved subject", base=1)
        assert stale.status_code == 409 and "Edits not saved" in stale.text
        assert 'value="My unsaved subject"' in stale.text
        assert client.get(path + "/status").json()["draft"]["revision"] == 2


def test_evidence_change_makes_draft_stale_until_rechecked(config):
    app = build_workbench_app(config)
    with TestClient(app) as client:
        path, run = ready_run(client)
        assert approve(client, path, run["draft"]).status_code == 303
        with app.state.open_workbench_store() as db:
            db.conn.execute(
                "UPDATE workbench_research_state SET evidence_version='changed' WHERE run_id=?",
                (run["id"],),
            )
        stale = client.get(path + "/status").json()
        assert stale["review"]["state"] == "stale"
        assert client.get(path + "/export").status_code == 409
        assert approve(client, path, stale["draft"]).status_code == 409
        assert "Evidence changed" in client.get(path).text
        assert check(client, path, stale["draft"]).status_code == 303  # same text, new basis
        rechecked = client.get(path + "/status").json()
        assert rechecked["review"]["state"] == "ready_for_review"
        assert approve(client, path, rechecked["draft"]).status_code == 303
        assert client.get(path + "/export").status_code == 200


def test_rejection_blocks_approval_until_a_new_checked_version(config):
    with TestClient(build_workbench_app(config)) as client:
        path, run = ready_run(client)
        response = client.post(
            path + "/draft/reject",
            data={"revision": 1, "note": "Tone is too formal"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        rejected = client.get(path + "/status").json()
        assert rejected["review"]["state"] == "rejected"
        assert rejected["business_outcome"] == "draft_rejected"
        assert approve(client, path, rejected["draft"]).status_code == 409
        assert client.get(path + "/export").status_code == 409
        assert "Tone is too formal" in client.get(path).text
        assert check(client, path, rejected["draft"]).status_code == 303
        assert client.get(path + "/status").json()["review"]["state"] == "ready_for_review"


def test_approval_is_bound_to_one_run_and_there_is_no_bulk_approval(config):
    app = build_workbench_app(config)
    with TestClient(app) as client:
        first, run_a = ready_run(client)
        second, run_b = ready_run(client)
        assert first != second
        assert approve(client, first, run_a["draft"]).status_code == 303
        assert client.get(second + "/export").status_code == 409
        # Same fixture text, but the approval and basis belong to the other run.
        assert client.get(second + "/status").json()["review"]["state"] == "ready_for_review"
        approve_routes = [r.path for r in app.routes if "approve" in getattr(r, "path", "")]
        assert approve_routes == ["/runs/{run_id}/draft/approve"]
        for url in ("/drafts/approve-all", "/runs/approve", "/campaigns/fake/approve-all"):
            assert client.post(url).status_code in (404, 405)
        assert client.get("/runs/missing/export").status_code == 404


def test_unresolved_false_inference_is_held_after_one_repair(config):
    app = build_workbench_app(config, writer=FixtureDraftWriter("persistent_false_inference"))
    with TestClient(app) as client:
        path = start(client)
        run = settled(client, path)
        assert run["business_outcome"] == "needs_revision"
        assert [d["supported"] for d in run["drafts"]] == [False, False]
        assert [s["name"] for s in run["stages"]].count("Repair draft") == 2
        assert approve(client, path, run["draft"]).status_code == 409
        page = client.get(path).text
        assert "slowing" in page and "Needs revision" in page


def test_restart_keeps_drafts_and_approval(config):
    with TestClient(build_workbench_app(config)) as client:
        path, run = ready_run(client)
        assert approve(client, path, run["draft"]).status_code == 303
    with TestClient(build_workbench_app(config)) as client:
        saved = client.get(path + "/status").json()
        assert saved["review"]["state"] == "approved"
        assert client.get(path + "/export").status_code == 200


def live_app(config, fake):
    return build_workbench_app(
        config,
        mode="live",
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake)),
    )


def draft_calls(fake):
    return [
        body
        for path, body in fake.calls
        if path.endswith("/chat/completions")
        and body["response_format"]["json_schema"]["name"] == "draftoutput"
    ]


def test_live_draft_uses_configured_model_inside_run_budget(config):
    fake = PublicSources(draft_variant="false_inference")
    with TestClient(live_app(config, fake)) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        assert run["business_outcome"] == "ready_for_review", run["result"]
        assert [d["origin"] for d in run["drafts"]] == ["model", "repair"]
        calls = draft_calls(fake)
        writer_model = config.workbench_draft_models.split(",")[0]
        assert len(calls) == 2 and all(c["model"] == writer_model for c in calls)
        research = [body for path, body in fake.calls if path.endswith("/chat/completions")]
        assert research[0]["model"] == config.workbench_research_models.split(",")[0]
        assert all("@" not in c["messages"][-1]["content"] for c in calls)
        assert run["usage"]["model_requests"] == 5 and run["usage"]["spent_micro"] <= 100000
        before = len(fake.calls)
        client.get(path)
    with TestClient(live_app(config, fake)) as client:
        client.get(path + "/status")
        assert len(fake.calls) == before


def test_held_draft_request_keeps_research_and_is_never_replayed(config):
    # The draft request is the first chat call after the two research model calls.
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        probe = settled(client, start(client, payload(live_consent="on")))
        draft_at = next(
            i + 1
            for i, (path, body) in enumerate(fake.calls)
            if path.endswith("/chat/completions")
            and body["response_format"]["json_schema"]["name"] == "draftoutput"
        )
        assert probe["draft"]
    held = PublicSources(timeout_at=draft_at)
    with TestClient(live_app(config, held)) as client:
        path = start(client, payload(live_consent="on"))
        run = settled(client, path)
        assert run["execution_status"] == "completed"
        assert run["result"]["hook"] and run["usage"]["held_requests"] == 1
        # The held model request is never replayed; the free template writes the email.
        assert [d["origin"] for d in run["drafts"]] == ["template"]
        assert any("built-in template" in item for item in run["result"]["limitations"])
        calls = len(held.calls)
    with TestClient(live_app(config, held)) as client:
        assert client.get(path + "/status").json()["usage"]["held_requests"] == 1
        assert len(held.calls) == calls


def test_daily_cap_is_separate_from_the_run_budget(config):
    """A second run the same day still researches when the day cap allows it."""
    fake = PublicSources()
    app = build_workbench_app(
        config,
        mode="live",
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake)),
        daily_budget_usd=0.5,
    )
    with TestClient(app) as client:
        first = settled(client, start(client, payload(live_consent="on")))
        second = settled(client, start(client, payload(live_consent="on")))
        assert first["usage"]["spent_micro"] > 0 and second["usage"]["spent_micro"] > 0
        assert second["business_outcome"] == "ready_for_review", second["result"]
    # With the old default (day cap = run budget), the same two runs exceed the day.
    tight = PublicSources()
    app = build_workbench_app(
        config,
        mode="live",
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(tight)),
        daily_budget_usd=first["usage"]["spent_micro"] / 1e6,
    )
    with TestClient(app) as client:
        third = settled(client, start(client, payload(live_consent="on")))
        assert third["usage"]["spent_micro"] == 0


def test_writer_falls_back_to_the_cheaper_model_when_the_limit_is_short(config):
    """The stronger writer is skipped, unpaid, when the run's limit cannot cover it."""
    fake = PublicSources()
    app = build_workbench_app(
        config,
        mode="live",
        limits={"budget_micro": 25000},
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake)),
    )
    with TestClient(app) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert run["business_outcome"] == "ready_for_review", run["result"]
        notes = [s["detail"] for s in run["stages"] if s["status"] == "failed"]
        writers = [c["model"] for c in draft_calls(fake)]
        assert writers == ["anthropic/claude-haiku-5.5"]
        assert any("claude-sonnet-5.5; trying the next model" in n for n in notes)
        assert run["draft"]["origin"] == "model" and run["usage"]["held_requests"] == 0


def test_default_writer_is_the_stronger_model_inside_the_default_limit(config):
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        run = settled(client, start(client, payload(live_consent="on")))
        assert [c["model"] for c in draft_calls(fake)] == ["anthropic/claude-sonnet-5.5"]
        assert run["usage"]["spent_micro"] <= run["limits"]["budget_micro"]
