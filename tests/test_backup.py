"""A backup nobody checked is a guess.

The do-not-contact list is the one thing in this database that cannot be
rebuilt from anywhere else, so these tests care most about whether it survives.
"""

import sqlite3

import pytest

from outreach.adapters.backup import BackupError, backup_database, default_destination
from outreach.adapters.db import connect
from outreach.core.models import SuppressionReason


def test_the_do_not_contact_list_survives(store, tmp_path):
    store.add_suppression("stop@example.com", SuppressionReason.UNSUBSCRIBE, note="asked twice")
    store.add_suppression("bounced@example.com", SuppressionReason.BOUNCE)

    counts = backup_database(store._conn, tmp_path / "copy.db")
    assert counts["suppressions"] == 2

    with sqlite3.connect(tmp_path / "copy.db") as copy:
        copy.row_factory = sqlite3.Row
        rows = {r["email"]: r["reason"] for r in copy.execute("SELECT * FROM suppressions")}
    assert rows == {"stop@example.com": "unsubscribe", "bounced@example.com": "bounce"}


def test_contacts_survive_too(store, contact_id, tmp_path):
    counts = backup_database(store._conn, tmp_path / "copy.db")
    assert counts["contacts"] == 1
    assert counts["campaigns"] == 1


def test_the_copy_is_a_working_database(store, contact_id, tmp_path):
    """Not just a file of the right size — something you can actually open."""
    backup_database(store._conn, tmp_path / "copy.db")
    conn = connect(tmp_path / "copy.db")
    assert conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 1
    conn.close()


def test_backing_up_while_the_database_is_in_use(store, contact_id, tmp_path):
    """A plain file copy can catch a half-written update. This must not."""
    store.add_suppression("stop@example.com", SuppressionReason.UNSUBSCRIBE)
    store.record_pending_send(
        contact_id=contact_id,
        message_id="<live@starthreads.in>",
        recipient_email="buyer@example.com",
        subject="s",
        body_text="b",
    )
    counts = backup_database(store._conn, tmp_path / "copy.db")
    assert counts["messages"] == 1
    assert counts["suppressions"] == 1


def test_the_destination_directory_is_created(store, tmp_path):
    target = tmp_path / "does" / "not" / "exist" / "copy.db"
    backup_database(store._conn, target)
    assert target.exists()


def test_an_unwritable_destination_fails_loudly(store, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory")
    with pytest.raises(BackupError):
        backup_database(store._conn, blocker / "copy.db")


def test_the_default_name_is_dated(tmp_path):
    from datetime import UTC, datetime

    when = datetime(2026, 9, 20, 14, 30, 12, tzinfo=UTC)
    path = default_destination(tmp_path / "data" / "outreach.db", now=when)
    assert path.name == "outreach-20260920-143012.db"
    assert path.parent.name == "backups"


def test_backups_do_not_overwrite_each_other(tmp_path):
    from datetime import UTC, datetime

    first = default_destination(tmp_path / "x.db", now=datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC))
    second = default_destination(tmp_path / "x.db", now=datetime(2026, 9, 20, 11, 0, 0, tzinfo=UTC))
    assert first != second


def test_the_backup_is_one_file_not_three(store, contact_id, tmp_path):
    """A live SQLite database in WAL mode is three files on disk. The copy
    must not be — a restore should be one file move, with nothing to forget.

    The backup goes in its own directory here, because tmp_path also holds the
    source database and its own -wal and -shm files.
    """
    folder = tmp_path / "backup-target"
    backup_database(store._conn, folder / "copy.db")
    written = sorted(p.name for p in folder.iterdir())
    assert written == ["copy.db"], f"backup left behind: {written}"
