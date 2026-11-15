"""Encrypt mailbox passwords at rest, with a private key outside the database."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from outreach.config import ConfigError, Settings


class CredentialVault:
    def __init__(self, settings: Settings):
        path = Path(settings.db_path).resolve().parent / "mail-credentials.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if settings.credential_key:
            key = settings.credential_key.encode()
        else:
            if path.exists():
                key = path.read_bytes()
            else:
                key = Fernet.generate_key()
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temp_path = Path(stream.name)
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    try:
                        # Publish only a completely written key, without replacing an existing one.
                        os.link(temp_path, path)
                    except FileExistsError:
                        key = path.read_bytes()
                finally:
                    temp_path.unlink(missing_ok=True)
        try:
            self.cipher = Fernet(key)
        except ValueError as exc:
            raise ConfigError("The mailbox encryption key is invalid.") from exc

    def encrypt(self, password: str) -> str:
        return self.cipher.encrypt(password.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        try:
            return self.cipher.decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise ConfigError(
                "Mailbox credentials cannot be unlocked. Restore the original encryption key "
                "or reconnect the account."
            ) from exc
