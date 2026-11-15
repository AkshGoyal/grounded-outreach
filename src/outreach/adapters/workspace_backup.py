"""Private, verified restore bundle: SQLite, campaign text, and mailbox key."""

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from outreach.adapters.backup import BackupError, backup_database
from outreach.campaigns import closing_path, copy_path, is_valid_id


def backup_workspace(conn, settings):
    directory = Path(settings.db_path).resolve().parent / "backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = "workspace-" + uuid.uuid4().hex + ".zip"
    target = directory / name
    try:
        with tempfile.TemporaryDirectory(dir=directory) as staging:
            snapshot = Path(staging) / "outreach.db"
            counts = backup_database(conn, snapshot)
            content = {"outreach.db": snapshot.read_bytes()}
            for row in conn.execute("SELECT id FROM campaigns"):
                cid = row["id"]
                if not is_valid_id(cid):
                    raise BackupError(
                        "A campaign has an invalid file name. Fix it before backing up."
                    )
                for path in (copy_path(cid), closing_path(cid)):
                    if path.is_symlink():
                        raise BackupError("Campaign text must be a regular file for this backup.")
                    if path.exists():
                        content["campaigns/" + path.name] = path.read_bytes()
            has_accounts = conn.execute(
                "SELECT 1 FROM mail_accounts WHERE password_cipher!='' UNION ALL "
                "SELECT 1 FROM mail_oauth WHERE token_cipher!='' LIMIT 1"
            ).fetchone()
            key_path = Path(settings.db_path).resolve().parent / "mail-credentials.key"
            if settings.credential_key:
                content["mail-credentials.key"] = settings.credential_key.encode()
            elif key_path.exists():
                content["mail-credentials.key"] = key_path.read_bytes()
            elif has_accounts:
                raise BackupError(
                    "Mailbox encryption key is missing. Restore it before making a full backup."
                )
            manifest = {
                "format": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "counts": counts,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in content.items()},
                "contains_mailbox_key": "mail-credentials.key" in content,
                "excluded": ["provider API keys", "OAuth client secrets", ".env"],
            }
            content["manifest.json"] = json.dumps(manifest, indent=2).encode()
            with target.open("xb") as stream:
                os.chmod(target, 0o600)
                with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for name, data in content.items():
                        archive.writestr(name, data)
            with zipfile.ZipFile(target) as archive:
                if archive.testzip() or any(
                    hashlib.sha256(archive.read(name)).hexdigest() != digest
                    for name, digest in manifest["files"].items()
                ):
                    raise BackupError("Workspace backup did not pass verification.")
        return target, manifest
    except (OSError, zipfile.BadZipFile, BackupError) as exc:
        target.unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(
            "The workspace backup could not be saved. Check disk access and space."
        ) from exc
