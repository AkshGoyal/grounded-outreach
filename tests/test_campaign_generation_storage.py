"""Campaign-scoped generation, stale result refusal and safe legacy upgrades."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from outreach.adapters.db import SCHEMA_VERSION, connect, schema_version
from outreach.adapters.store_sqlite import SqliteStore
from outreach.campaigns import save_texts
from outreach.core.models import Campaign, Contact
from outreach.generation import (
    current_generation_matches,
    generation_snapshot,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = connect(tmp_path / "fixture.db")
    store = SqliteStore(db)
    contacts = {}
    instructions = {
        "job-search": "Write job-search outreach about AI and analytics.",
        "sales": "Introduce an automation product and offer a trial.",
        "networking": "Write a short professional networking introduction.",
    }
    for cid, copy in instructions.items():
        store.add_campaign(Campaign(id=cid, name=cid, created_at=datetime.now(UTC)))
        contacts[cid] = store.add_contact(
            Contact(campaign_id=cid, email="shared@example.com", company="Fictional Labs")
        )
        save_texts(cid, copy=copy, closing="Fixed text for " + cid)
    yield store, contacts
    db.close()


def save(store, contact_id, generation=None):
    return store.save_draft(
        contact_id=contact_id,
        model="fake",
        subject="Hello",
        body="A fictional draft.",
        verdict="ready",
        checks=[],
        generation=generation,
    )


def test_three_campaigns_keep_independent_snapshots_and_same_address(workspace):
    store, contacts = workspace
    hashes = set()
    for cid, contact_id in contacts.items():
        snapshot = generation_snapshot(cid)
        hashes.add(snapshot["instruction_hash"])
        draft = store.get_draft(save(store, contact_id, snapshot))
        assert draft.campaign_id == cid
        assert draft.generation == {**snapshot, "contact_id": contact_id}
        assert [item.id for item in store.drafts_in_campaign(cid)] == [draft.id]
    assert len(hashes) == 3


def test_cross_campaign_snapshot_is_rejected_without_partial_draft(workspace):
    store, contacts = workspace
    with pytest.raises(ValueError, match="does not belong"):
        save(store, contacts["job-search"], generation_snapshot("sales"))
    assert store._conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_stale_result_refused_but_other_campaign_snapshot_stays_current(workspace):
    store, contacts = workspace
    job = generation_snapshot("job-search")
    sales = generation_snapshot("sales")
    save_texts("job-search", copy="Write new job-search instructions.", closing="New closing")
    assert not current_generation_matches(job)
    assert current_generation_matches(sales)
    with pytest.raises(ValueError, match="instructions changed"):
        save(store, contacts["job-search"], job)
    assert store.drafts_in_campaign("job-search") == []
    assert store.get_draft(save(store, contacts["sales"], sales)).campaign_id == "sales"


def test_tampered_snapshot_and_wrong_recipient_are_rejected(workspace):
    store, contacts = workspace
    source = generation_snapshot("job-search")
    with pytest.raises(ValueError, match="instructions changed"):
        save(store, contacts["job-search"], {**source, "campaign_copy": "Other copy"})
    with pytest.raises(ValueError, match="does not belong"):
        save(store, contacts["job-search"], {**source, "contact_id": contacts["sales"]})


def test_database_refuses_cross_campaign_provenance_and_history_moves(workspace):
    store, contacts = workspace
    draft_id = save(store, contacts["job-search"])
    with pytest.raises(sqlite3.IntegrityError, match="mismatch"):
        store._conn.execute(
            "INSERT INTO draft_generations VALUES (?,?,?,?,?)",
            (draft_id, "sales", contacts["sales"], "hash", "{}"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(
            "UPDATE contacts SET campaign_id='sales' WHERE id=?", (contacts["job-search"],)
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(
            "UPDATE drafts SET contact_id=? WHERE id=?", (contacts["sales"], draft_id)
        )


def test_provenance_insert_failure_rolls_back_new_draft(workspace):
    store, contacts = workspace
    store._conn.execute(
        "CREATE TRIGGER fixture_refuse BEFORE INSERT ON draft_generations "
        "BEGIN SELECT RAISE(ABORT, 'fixture refusal'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="fixture refusal"):
        save(store, contacts["job-search"], generation_snapshot("job-search"))
    assert store.drafts_in_campaign("job-search") == []


def test_reopen_preserves_snapshot_and_legacy_draft_without_invented_provenance(workspace):
    store, contacts = workspace
    new_id = save(store, contacts["sales"], generation_snapshot("sales"))
    old_id = save(store, contacts["job-search"])
    conn = connect("fixture.db")
    try:
        recovered = SqliteStore(conn)
        assert recovered.get_draft(new_id).generation["campaign_id"] == "sales"
        assert recovered.get_draft(old_id).generation is None
        assert recovered.get_draft(old_id).campaign_id == "job-search"
    finally:
        conn.close()


def test_provenance_cannot_be_rewritten(workspace):
    store, contacts = workspace
    draft_id = save(store, contacts["sales"], generation_snapshot("sales"))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._conn.execute(
            "UPDATE draft_generations SET snapshot_json=? WHERE draft_id=?",
            (json.dumps({"campaign_id": "networking"}), draft_id),
        )


def test_schema_upgrade_preserves_existing_drafts(workspace):
    store, contacts = workspace
    draft_id = save(store, contacts["job-search"])
    store._conn.execute("DROP TABLE draft_generations")
    store._conn.execute("UPDATE schema_meta SET value='10' WHERE key='schema_version'")
    upgraded = connect("fixture.db")
    try:
        assert schema_version(upgraded) == SCHEMA_VERSION == 11
        old = SqliteStore(upgraded).get_draft(draft_id)
        assert old.campaign_id == "job-search" and old.generation is None
    finally:
        upgraded.close()


def test_missing_campaign_configuration_never_borrows_other_copy(workspace):
    with pytest.raises(ValueError, match="instructions"):
        generation_snapshot("missing")
    assert not current_generation_matches({"campaign_id": "missing"})
