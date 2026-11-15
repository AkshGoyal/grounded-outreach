"""SQLite connection and bootstrap (D-006).

Explicit SQL, no ORM: what you read here is what runs.

This module owns the connection settings and the schema.

The schema includes the second of the two suppression guards: a rule the
database itself applies. Even if application code is wrong, or someone types
SQL by hand, the database refuses to record an email addressed to someone on
the do-not-contact list (invariant I-2).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 11


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the database, creating the file and its parent directory if needed.

    Pragmas, and why each one is set:

    - ``journal_mode=WAL``   readers don't block the writer. D-006 notes SQLite
                             is single-writer; WAL is the mitigation.
    - ``foreign_keys=ON``    SQLite disables these per connection by default,
                             which silently lets orphaned rows through.
    - ``busy_timeout``       wait rather than raise immediately when the write
                             lock is briefly held.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    _bootstrap(conn)
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One outreach push, with its own message and rules.
CREATE TABLE IF NOT EXISTS campaigns (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One business we may write to, inside one campaign.
-- `evidence` is JSON: whatever we know about them, as given.
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    company     TEXT,
    evidence    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    UNIQUE (campaign_id, email)
);

-- The do-not-contact list. Keyed by address alone: suppression is global,
-- never per-campaign. Someone who opts out of one campaign is out of all.
CREATE TABLE IF NOT EXISTS suppressions (
    email      TEXT PRIMARY KEY,
    reason     TEXT NOT NULL
                 CHECK (reason IN ('unsubscribe', 'bounce', 'complaint', 'manual')),
    created_at TEXT NOT NULL,
    note       TEXT
);

-- Emails we send. The row is written BEFORE the email goes out, as 'pending',
-- so a crash mid-send leaves visible evidence instead of a silent re-send.
--
-- `recipient_email` is stored here as well as on the contact, on purpose: it
-- is the address actually written to, and it lets the guard below check a row
-- without following a join.
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    message_id      TEXT NOT NULL UNIQUE,
    recipient_email TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body_text       TEXT NOT NULL,
    status          TEXT NOT NULL
                      CHECK (status IN ('pending', 'sent', 'failed')),
    created_at      TEXT NOT NULL,
    sent_at         TEXT
);

-- Replies. `message_id` is nullable on purpose: a reply we cannot attribute is
-- still recorded, and surfaced to a human, never dropped (invariant I-4).
CREATE TABLE IF NOT EXISTS replies (
    id                  INTEGER PRIMARY KEY,
    message_id          TEXT REFERENCES messages(message_id),
    provider_message_id TEXT NOT NULL UNIQUE,
    from_address        TEXT NOT NULL,
    subject             TEXT NOT NULL,
    body_text           TEXT NOT NULL,
    received_at         TEXT NOT NULL
);

-- Reserve an answer before network I/O. No message FK: a crash can happen
-- between the reservation and writing the pending message. Such a claim is
-- uncertain and must remain blocked, even after a restart.
CREATE TABLE IF NOT EXISTS reply_sends (
    reply_id   INTEGER PRIMARY KEY REFERENCES replies(id),
    message_id TEXT NOT NULL UNIQUE
);

-- How each reply was read (schema v4). Kept apart from `replies` on purpose:
-- `replies` is what arrived, unchanged; this is our interpretation of it,
-- which can be redone. `contact_id` is null when a reply can't be matched.
CREATE TABLE IF NOT EXISTS reply_triage (
    reply_id        INTEGER PRIMARY KEY REFERENCES replies(id) ON DELETE CASCADE,
    contact_id      INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    matched_by      TEXT NOT NULL
                      CHECK (matched_by IN ('thread', 'bounce', 'address', 'subject')),
    category        TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    details         TEXT NOT NULL DEFAULT '{}',
    suggested_reply TEXT NOT NULL DEFAULT '',
    action          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'done')),
    created_at      TEXT NOT NULL
);

-- Drafts waiting for a human. Nothing here can be sent until a person has
-- approved it, and a draft cannot be approved while any line in it is one
-- the grounding checker could not back up (see core/review.py).
CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    checks      TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL
                  CHECK (status IN ('review', 'approved', 'rejected', 'sent')),
    created_at  TEXT NOT NULL,
    reviewed_at TEXT
);


-- Optional provenance for new drafts. Historical drafts remain untouched.
CREATE TABLE IF NOT EXISTS draft_generations (
    draft_id INTEGER PRIMARY KEY REFERENCES drafts(id) ON DELETE CASCADE,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    instruction_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS draft_generation_identity_insert
BEFORE INSERT ON draft_generations
WHEN NOT EXISTS (
    SELECT 1 FROM drafts d JOIN contacts c ON c.id=d.contact_id
    WHERE d.id=NEW.draft_id AND d.contact_id=NEW.contact_id
      AND c.campaign_id=NEW.campaign_id
)
BEGIN
    SELECT RAISE(ABORT, 'draft generation campaign/contact mismatch');
END;

CREATE TRIGGER IF NOT EXISTS draft_generation_immutable
BEFORE UPDATE ON draft_generations
BEGIN
    SELECT RAISE(ABORT, 'draft generation provenance is immutable');
END;

CREATE TRIGGER IF NOT EXISTS draft_contact_immutable
BEFORE UPDATE OF contact_id ON drafts
WHEN NEW.contact_id != OLD.contact_id
BEGIN
    SELECT RAISE(ABORT, 'draft contact identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS contact_campaign_history_immutable
BEFORE UPDATE OF campaign_id ON contacts
WHEN NEW.campaign_id != OLD.campaign_id AND (
    EXISTS (SELECT 1 FROM drafts WHERE contact_id=OLD.id)
    OR EXISTS (SELECT 1 FROM messages WHERE contact_id=OLD.id)
)
BEGIN
    SELECT RAISE(ABORT, 'contact campaign with history is immutable');
END;

CREATE TABLE IF NOT EXISTS draft_test_runs (
    id TEXT PRIMARY KEY,
    draft_id INTEGER NOT NULL REFERENCES drafts(id),
    recipient TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drafts_contact ON drafts(contact_id);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_email);
CREATE INDEX IF NOT EXISTS idx_contacts_email     ON contacts(email);

-- ---------------------------------------------------------------------------
-- Guard two of two (invariant I-2).
--
-- Guard one lives in core/sending.py and refuses before anything is written.
-- This one is the backstop: the database itself rejects the row. It fires on
-- INSERT, which happens before the email is sent, and on any UPDATE that would
-- point an existing row at a suppressed address.
-- ---------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS refuse_insert_to_suppressed
BEFORE INSERT ON messages
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM suppressions WHERE email = NEW.recipient_email)
BEGIN
    SELECT RAISE(ABORT, 'recipient is suppressed: refusing to record this send');
END;

CREATE TRIGGER IF NOT EXISTS refuse_update_to_suppressed
BEFORE UPDATE OF recipient_email ON messages
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM suppressions WHERE email = NEW.recipient_email)
BEGIN
    SELECT RAISE(ABORT, 'recipient is suppressed: refusing to record this send');
END;
"""


def _bootstrap(conn: sqlite3.Connection) -> None:
    """Create the schema and record its version. Safe to call on every connect."""
    conn.executescript(SCHEMA_SQL)
    from outreach.adapters.platform_store import PLATFORM_SCHEMA

    conn.executescript(PLATFORM_SCHEMA)
    from outreach.adapters.attachments import ATTACHMENT_SCHEMA

    conn.executescript(ATTACHMENT_SCHEMA)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    return int(row["value"]) if row else 0
