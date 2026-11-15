"""Browser-entered provider keys, encrypted locally; never rewrite .env."""

import json
import os
import tempfile
from pathlib import Path

from outreach.adapters.credential_vault import CredentialVault
from outreach.config import ConfigError

FIELDS = ("parallel_api_key", "openrouter_api_key")


class ProviderCredentials:
    def __init__(self, settings):
        self.settings = settings
        self.path = Path(settings.db_path).resolve().parent / "provider-credentials.enc"

    def read(self):
        if not self.path.exists():
            return {}
        try:
            values = json.loads(CredentialVault(self.settings).decrypt(self.path.read_text()))
            if not isinstance(values, dict) or any(
                key not in FIELDS or not isinstance(value, str) for key, value in values.items()
            ):
                raise ValueError()
            return values
        except (ConfigError, ValueError, OSError) as exc:
            raise ConfigError(
                "Saved research keys could not be opened. Restore the original encryption "
                "key and provider-credentials.enc together. Your .env has not been changed."
            ) from exc

    def apply(self):
        for name, value in self.read().items():
            setattr(self.settings, name, value)

    def save(self, updates):
        if any(name not in FIELDS for name in updates):
            raise ConfigError("Choose a supported research provider.")
        values = self.read() | updates
        if any(
            not isinstance(value, str) or not 1 <= len(value) <= 500 for value in values.values()
        ):
            raise ConfigError("Enter a provider key between 1 and 500 characters.")
        encrypted = CredentialVault(self.settings).encrypt(json.dumps(values))
        with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted.encode())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.apply()
