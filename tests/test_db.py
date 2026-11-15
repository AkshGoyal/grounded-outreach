"""The database bootstrap must be idempotent and set its pragmas."""

from outreach.adapters.db import SCHEMA_VERSION, connect, schema_version


def test_connect_creates_file_and_parent_directory(tmp_path):
    db = tmp_path / "nested" / "outreach.db"
    conn = connect(db)
    assert db.exists()
    conn.close()


def test_pragmas_are_set(tmp_path):
    conn = connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    # SQLite defaults foreign keys OFF per connection; forgetting this lets
    # orphaned rows through silently.
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_bootstrap_is_idempotent(tmp_path):
    db = tmp_path / "x.db"
    connect(db).close()
    conn = connect(db)
    assert schema_version(conn) == SCHEMA_VERSION
    rows = conn.execute("SELECT COUNT(*) AS n FROM schema_meta").fetchone()["n"]
    assert rows == 1, "reconnecting must not duplicate metadata rows"
    conn.close()


def test_expected_tables_exist(tmp_path):
    conn = connect(tmp_path / "x.db")
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {
        "schema_meta",
        "campaigns",
        "contacts",
        "suppressions",
        "messages",
        "replies",
        "reply_triage",
        "drafts",
        "projects",
        "mail_accounts",
        "campaign_settings",
        "campaign_briefs",
        "draft_generations",
        "campaign_research_runs",
        "mail_oauth",
        "oauth_attempts",
        "mail_api_ids",
        "mail_test_runs",
        "research_runs",
        "research_execution",
        "research_suggestions",
        "research_intakes",
        "research_archives",
        "research_trash",
        "research_messages",
        "research_calls",
        "lead_entities",
        "research_leads",
        "lead_lists",
        "lead_list_members",
        "contact_origins",
        "reply_mailboxes",
        "reply_sends",
        "draft_test_runs",
        "campaign_attachments",
        "message_attachments",
        "draft_test_attachments",
    }
    conn.close()


def test_suppression_guard_exists_in_the_database(tmp_path):
    """The table that records sends must not exist without the guard on it."""
    conn = connect(tmp_path / "x.db")
    triggers = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    assert "refuse_insert_to_suppressed" in triggers
    assert "refuse_update_to_suppressed" in triggers
    conn.close()


def test_an_older_database_gains_the_drafts_table_on_connect(tmp_path):
    """The operator's real database was created at schema version 2, before
    drafts existed. Connecting with newer code must upgrade it in place,
    keeping every contact — not fail, and not start over."""
    import sqlite3

    path = tmp_path / "old.db"
    conn = connect(path)
    conn.execute("INSERT INTO campaigns (id, name, created_at) VALUES ('c', 'c', 'now')")
    conn.execute(
        "INSERT INTO contacts (campaign_id, email, evidence, created_at) "
        "VALUES ('c', 'a@example.com', '{}', 'now')"
    )
    conn.execute("DROP TABLE drafts")
    conn.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
    conn.close()

    upgraded = connect(path)
    tables = {r[0] for r in upgraded.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "drafts" in tables
    assert schema_version(upgraded) == SCHEMA_VERSION
    assert upgraded.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1
    upgraded.close()
    del sqlite3
