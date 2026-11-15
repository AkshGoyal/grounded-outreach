"""Private SQLite attachment bytes, also preserved by workspace backups."""

import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import PurePosixPath

from outreach.core.attachments import FILE_TYPES, EmailAttachment, upload_name, validate_bundle

ATTACHMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_attachments (
 id TEXT PRIMARY KEY,
 campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, mime_type TEXT NOT NULL,
 content BLOB NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_attachments (
 message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
 attachment_id TEXT NOT NULL REFERENCES campaign_attachments(id),
 PRIMARY KEY(message_id,attachment_id)
);
CREATE TABLE IF NOT EXISTS draft_test_attachments (
 test_id TEXT NOT NULL REFERENCES draft_test_runs(id) ON DELETE CASCADE,
 attachment_id TEXT NOT NULL REFERENCES campaign_attachments(id),
 PRIMARY KEY(test_id,attachment_id)
);
"""


def decode(row):
    file = EmailAttachment(
        id=row["id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        content=bytes(row["content"]),
    )
    if file.manifest()["sha256"] != row["sha256"] or len(file.content) != row["size"]:
        raise ValueError(
            "An attachment changed in storage. Remove it and upload the original again."
        )
    return file


def campaign_files(conn, cid):
    return validate_bundle(
        [
            decode(row)
            for row in conn.execute(
                "SELECT * FROM campaign_attachments WHERE campaign_id=? AND active=1 "
                "ORDER BY created_at,id",
                (cid,),
            )
        ]
    )


def manifests(files):
    return [file.manifest() for file in files]


def saved_files(conn, key, *, test=False):
    table, field = (
        ("draft_test_attachments", "test_id") if test else ("message_attachments", "message_id")
    )
    return [
        dict(row)
        for row in conn.execute(
            "SELECT a.id,a.filename,a.mime_type,a.size,a.sha256 FROM campaign_attachments a JOIN "
            + table
            + " m ON m.attachment_id=a.id WHERE m."
            + field
            + "=? ORDER BY a.created_at,a.id",
            (key,),
        )
    ]


def add_files(conn, cid, uploads):
    current = list(campaign_files(conn, cid))
    added = []
    for name, data in uploads:
        name = upload_name(name)
        file = EmailAttachment(
            id=secrets.token_hex(16),
            filename=name,
            mime_type=FILE_TYPES[PurePosixPath(name).suffix.casefold()],
            content=data,
        )
        digest = hashlib.sha256(data).hexdigest()
        if any(f.filename == name and f.manifest()["sha256"] == digest for f in current):
            continue
        current.append(file)
        added.append(file)
    validate_bundle(current)
    for file in added:
        info = file.manifest()
        conn.execute(
            "INSERT INTO campaign_attachments VALUES (?,?,?,?,?,?,?,1,?)",
            (
                file.id,
                cid,
                file.filename,
                file.mime_type,
                file.content,
                info["sha256"],
                info["size"],
                datetime.now(UTC).isoformat(),
            ),
        )
    return len(added)


def record_files(conn, message_id, files, contact_id):
    contact = conn.execute("SELECT campaign_id FROM contacts WHERE id=?", (contact_id,)).fetchone()
    for file in validate_bundle(files):
        row = conn.execute(
            "SELECT * FROM campaign_attachments WHERE id=? AND campaign_id=?",
            (file.id, contact["campaign_id"]),
        ).fetchone()
        if not row or decode(row) != file:
            raise ValueError(
                "The reviewed attachment is unavailable. Review the campaign files again."
            )
        conn.execute("INSERT INTO message_attachments VALUES (?,?)", (message_id, file.id))
