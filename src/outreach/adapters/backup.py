"""Making a safe copy of the database.

Why this exists at all: everything the tool knows lives in one file. Contacts
can be re-imported from a spreadsheet if it is lost. **The do-not-contact list
cannot.** There is no other record of who asked you to stop, and the cost of
losing it is writing again to people who explicitly opted out.

Why not just copy the file: a database being written to is briefly in a state
where a plain file copy captures half an update. SQLite's own backup routine
takes a consistent snapshot even while the database is in use, so the copy is
always openable. `cp` is not a substitute.

The copy is deliberately left as a single file — see the journal-mode note
below — so restoring is one file move, with nothing to forget.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Tables whose contents we count afterwards, as proof the copy is not empty.
_CHECKED_TABLES = (
    "campaigns",
    "contacts",
    "suppressions",
    "messages",
    "replies",
    "reply_triage",
)


class BackupError(RuntimeError):
    """The backup could not be made, or the copy did not verify."""


def default_destination(db_path: str | Path, *, now: datetime | None = None) -> Path:
    """`backups/outreach-20260920-143012.db`, beside the database."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return Path(db_path).parent / "backups" / f"outreach-{stamp}.db"


def backup_database(conn: sqlite3.Connection, destination: str | Path) -> dict[str, int]:
    """Copy the live database to `destination`, then verify the copy.

    Returns the row count of each table in the *copy* — not in the original —
    because the point is to know what was actually saved.
    """
    target = Path(destination)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"Cannot create the folder for {target}: {exc}") from exc

    # Explicit close, not a `with` block: sqlite3's context manager commits but
    # does NOT close, which leaves -wal and -shm files beside the copy. A
    # restore is then three files instead of one, and the extra two look like
    # debris nobody will think to copy.
    copy = None
    try:
        copy = sqlite3.connect(target)
        conn.backup(copy)
        # The copy inherits WAL mode from the live database, which means it is
        # three files on disk, not one. Switching the copy to DELETE mode folds
        # the -wal and -shm files back in, so a restore is a single file you
        # can email to yourself or drop on a USB stick.
        copy.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.Error as exc:
        raise BackupError(f"Could not write the backup to {target}: {exc}") from exc
    finally:
        if copy is not None:
            copy.close()

    counts = _verify(target)
    return counts


def _verify(target: Path) -> dict[str, int]:
    """Open the copy and count it. A backup nobody checked is a guess."""
    copy = None
    try:
        copy = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"The backup at {target} failed its integrity check.")
        return {
            table: copy.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in _CHECKED_TABLES
        }
    except sqlite3.Error as exc:
        raise BackupError(f"The backup at {target} could not be read back: {exc}") from exc
    finally:
        if copy is not None:
            copy.close()
