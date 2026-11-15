"""Research reservations, migration and identity consent on disposable SQLite files."""

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from outreach.adapters.db import connect
from outreach.adapters.workbench_store import DEFAULT_LIMITS, WorkbenchStore, canonical
from outreach.adapters.store_sqlite import SqliteStore
from outreach.core.workbench_evidence import assess_identity
from outreach.core.research import ResearchStop

PROSPECT = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"}


@pytest.fixture
def state(tmp_path):
    clock = [datetime(2026, 11, 10, tzinfo=UTC)]
    db = WorkbenchStore(SqliteStore(connect(tmp_path / "research.db")), clock=lambda: clock[0])
    key, _ = db.submit(PROSPECT, "request", db.get_campaign_brief(), mode="live")
    assert db.claim_workbench_run(key)
    try:
        yield db, key, clock
    finally:
        db.close()


def complete(db, key, operation, kind="search", units=1):
    assert db.reserve_workbench_operation(key, operation, kind, units, operation)
    if kind != "followup":
        db.reserve(key, operation, "provider-" + operation, 1000, 100000)
        db.finish_call(key, operation, {"result": operation}, 1000, "tariff")
        db.mark_workbench_operation_complete(key, operation)


def test_phase_one_mode_migration_preserves_results_foreign_keys_and_idempotency(
    tmp_path, monkeypatch
):
    import outreach.adapters.workbench_store as module

    path = tmp_path / "phase-one.db"
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "WORKBENCH_SCHEMA",
            module.WORKBENCH_SCHEMA.replace("CHECK(mode IN ('fixture','live'))", "CHECK(mode='fixture')"),
        )
        patch.setattr(WorkbenchStore, "_migrate_live_mode", lambda self: None)
        with WorkbenchStore(SqliteStore(connect(path))) as old:
            campaign = old.get_campaign_brief()
            key, _ = old.submit(PROSPECT, "original", campaign)
            assert old.claim_workbench_run(key)
            old.add_stage(key, "Fixture source read", "completed", "Saved fictional evidence.")
            result = {"outcome": "research_ready", "next_action": "Review fixture result."}
            old.finish_workbench_run(key, result)
            # Phase 1 stored a two-part fingerprint before mode/options existed.
            prospect = old.get_workbench_run(key)["prospect"]
            legacy = hashlib.sha256(canonical([prospect, campaign]).encode()).hexdigest()
            old.conn.execute("DROP TRIGGER workbench_run_snapshot_immutable")
            old.conn.execute(
                "UPDATE workbench_runs SET request_fingerprint=? WHERE run_id=?", (legacy, key)
            )
            old.conn.executescript(module.WORKBENCH_SCHEMA)
            before = old.get_workbench_run(key)
    with WorkbenchStore(SqliteStore(connect(path))) as migrated:
        assert migrated.get_workbench_run(key) == before
        assert migrated.submit(PROSPECT, "original", campaign) == (key, False)
        assert migrated.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert migrated.conn.execute("PRAGMA foreign_key_check").fetchall() == []
        live, _ = migrated.submit(PROSPECT, "live", campaign, mode="live")
        assert migrated.get_workbench_run(live)["mode"] == "live"
        assert migrated.run(live)["budget_micro"] == DEFAULT_LIMITS["budget_micro"]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            migrated.conn.execute("UPDATE workbench_runs SET mode='live' WHERE run_id=?", (key,))


def test_query_page_model_followup_limits_and_cached_reuse(state):
    db, key, clock = state
    complete(db, key, "search-1", units=6)
    complete(db, key, "search-2", units=6)
    with pytest.raises(ResearchStop, match="limit"):
        db.reserve_workbench_operation(key, "search-3", "search", 1, "new")
    complete(db, key, "extract-1", "extract", 3)
    complete(db, key, "extract-2", "extract", 3)
    with pytest.raises(ResearchStop, match="limit"):
        db.reserve_workbench_operation(key, "extract-3", "extract", 1, "new")
    # Identity, signal, two follow-ups, one draft and one repair.
    assert DEFAULT_LIMITS["max_model_requests"] == 8
    for index in range(DEFAULT_LIMITS["max_model_requests"]):
        complete(db, key, "model-" + str(index), "model")
    with pytest.raises(ResearchStop, match="limit"):
        db.reserve_workbench_operation(key, "model-extra", "model", 1, "new")
    complete(db, key, "followup", "followup")
    complete(db, key, "signal-followup", "followup")
    with pytest.raises(ResearchStop, match="limit"):
        db.reserve_workbench_operation(key, "followup-3", "followup", 1, "new")
    before = db.usage(key)
    clock[0] += timedelta(seconds=181)
    assert db.reserve_workbench_operation(key, "search-1", "search", 6, "search-1") is False
    assert db.usage(key) == before
    with pytest.raises(ResearchStop, match="changed"):
        db.reserve_workbench_operation(key, "search-1", "search", 6, "changed")
    with pytest.raises(ResearchStop, match="time limit"):
        db.reserve_workbench_operation(key, "new", "search", 1, "new")


def test_request_count_cap_is_separate_from_query_count(state):
    db, key, _ = state
    for index in range(5):
        complete(db, key, str(index))
    assert db.usage(key)["search_queries"] == 5
    with pytest.raises(ResearchStop, match="limit"):
        db.reserve_workbench_operation(key, "fourth", "search", 1, "new")


def test_mode_and_limits_are_bound_to_submission_and_cannot_be_expanded(state):
    db, key, _ = state
    with pytest.raises(ValueError, match="different inputs"):
        db.submit(PROSPECT, "request", db.get_campaign_brief(), mode="fixture")
    with pytest.raises(ValueError, match="different inputs"):
        db.submit(
            PROSPECT, "request", db.get_campaign_brief(), mode="live", limits={"max_pages": 4}
        )
    with pytest.raises(ValueError, match="Invalid Workbench limit"):
        db.submit(PROSPECT, "new", db.get_campaign_brief(), mode="live", limits={"max_pages": 7})
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.conn.execute("UPDATE workbench_research_options SET limits_json='{}' WHERE run_id=?", (key,))


def test_held_request_refuses_replay_and_new_dispatch_without_resetting_accounting(state):
    db, key, _ = state
    assert db.reserve_workbench_operation(key, "uncertain", "search", 1, "same")
    db.reserve(key, "uncertain", "provider", 1000, 100000)
    for operation in ("uncertain", "other"):
        with pytest.raises(ResearchStop, match="held"):
            db.reserve_workbench_operation(key, operation, "search", 1, "same")
    assert db.usage(key)["spent_micro"] == 1000
    assert db.usage(key)["held_requests"] == 1
    assert db.usage(key)["search_queries"] == 1
    with pytest.raises(ResearchStop, match="held"):
        db.mark_workbench_operation_complete(key, "uncertain")


def test_dollar_failure_retains_committed_operation_slot(state):
    db, key, _ = state
    assert db.reserve_workbench_operation(key, "too-expensive", "model", 1, "same")
    with pytest.raises(ResearchStop, match="Spending limit"):
        db.reserve(key, "too-expensive", "provider", 100001, 100000)
    assert db.usage(key)["model_requests"] == 1
    assert db.usage(key)["spent_micro"] == 0
    with pytest.raises(ResearchStop, match="held"):
        db.reserve_workbench_operation(key, "too-expensive", "model", 1, "same")


def identity_checkpoint(db, key):
    source = {
        "id": "leadership",
        "url": "https://cedar-works.example/leadership",
        "access_status": "read",
        "text": "Maya Rao is Finance Director at Cedar Works.",
    }
    other_source = {
        "id": "other-leadership",
        "url": "https://other-works.example/leadership",
        "access_status": "read",
        "text": "Maya Rao is Finance Director at Other Works.",
    }
    candidates = [
        {
            "name": "Maya Rao",
            "company": company,
            "role": "Finance Director",
            "domain": domain,
            "source_id": source_id,
            "quote": f"Maya Rao is Finance Director at {company}.",
            "status": "current",
        }
        for company, domain, source_id in [
            ("Cedar Works", "cedar-works.example", "leadership"),
            ("Other Works", "other-works.example", "other-leadership"),
        ]
    ]
    sources = [source, other_source]
    for item in sources:
        db.save_source(key, item)
    db.save_checkpoint(
        key, {"identity_candidates": candidates, "sources": sources, "identity_done": True}
    )
    identity = assess_identity(PROSPECT, sources, candidates)
    assert identity["status"] == "conflict"
    selected = next(c for c in identity["candidates"] if c["selectable"])
    db.finish_workbench_run(
        key,
        {
            "outcome": "needs_identity_confirmation",
            "identity": identity,
            "next_action": "Confirm prospect.",
        },
    )
    return source, selected, db.get_workbench_run(key)["evidence_version"]


def test_confirmation_binds_run_checkpoint_and_current_identity_then_reuses_deadline(state):
    db, key, _ = state
    _, candidate, version = identity_checkpoint(db, key)
    deadline = db.get_workbench_run(key)["deadline_at"]
    with pytest.raises(ValueError, match="evidence changed"):
        db.confirm_workbench_identity(key, candidate["id"], "stale")
    with pytest.raises(ValueError, match="supported current"):
        db.confirm_workbench_identity(key, "wrong-or-former-candidate", version)
    db.confirm_workbench_identity(key, candidate["id"], version)
    assert db.get_workbench_run(key)["execution_status"] == "queued"
    assert db.claim_workbench_run(key)
    run = db.get_workbench_run(key)
    assert run["deadline_at"] == deadline
    assert run["confirmation"]["candidate_id"] == candidate["id"]
    assert run["confirmation"]["proof_sources"]["leadership"]


def test_signal_progress_preserves_confirmation_but_changed_identity_evidence_invalidates(state):
    db, key, _ = state
    source, candidate, version = identity_checkpoint(db, key)
    db.confirm_workbench_identity(key, candidate["id"], version)
    db.claim_workbench_run(key)
    db.save_source(
        key,
        {
            "id": "news",
            "url": "https://cedar-works.example/news",
            "access_status": "read",
            "text": "Invoice review.",
        },
    )
    run = db.get_workbench_run(key)
    db.save_checkpoint(key, {**run["checkpoint"], "signal_done": True})
    assert db.get_workbench_run(key)["confirmation"]["candidate_id"] == candidate["id"]
    db.save_source(key, {**source, "text": "Changed leadership evidence."})
    changed = db.get_workbench_run(key)
    assert not changed["confirmation"]
    assert changed["evidence_version"] != version


def test_held_request_blocks_identity_confirmation_without_requeue(state):
    db, key, _ = state
    db.reserve(key, "possibly-charged", "same", 1000, 100000)
    _, candidate, version = identity_checkpoint(db, key)
    with pytest.raises(ResearchStop, match="held"):
        db.confirm_workbench_identity(key, candidate["id"], version)
    run = db.get_workbench_run(key)
    assert run["execution_status"] == "completed"
    assert not run["confirmation"]
    assert run["usage"]["held_requests"] == 1


def test_failure_and_restart_keep_sources_checkpoint_and_held_spending(state):
    db, key, _ = state
    db.save_source(
        key, {"id": "partial", "url": "https://cedar-works.example/", "text": "Saved page."}
    )
    db.save_checkpoint(key, {"identity_done": True, "sources": db.workbench_sources(key)})
    db.reserve_workbench_operation(key, "uncertain", "search", 1, "same")
    db.reserve(key, "uncertain", "provider", 1000, 100000)
    db.fail_workbench_run(key, "Provider unavailable; request held for review.")
    failed = db.get_workbench_run(key)
    assert failed["result"]["sources"][0]["id"] == "partial"
    assert failed["checkpoint"]["identity_done"]
    assert failed["usage"]["held_requests"] == 1
    # Startup recovery of another unfinished run does not disturb the finished failure.
    second, _ = db.submit(PROSPECT, "second", db.get_campaign_brief(), mode="live")
    db.claim_workbench_run(second)
    db.save_source(second, {"id": "second-page", "text": "Separate run."})
    assert db.recover_workbench_runs() == 1
    assert db.get_workbench_run(key) == failed
    recovered = db.get_workbench_run(second)
    assert recovered["execution_status"] == "interrupted"
    assert recovered["result"]["sources"][0]["id"] == "second-page"
