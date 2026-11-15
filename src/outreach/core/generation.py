"""Pure instruction identity shared by generation, review and send checks.

Bump COMPOSER_VERSION when shared prompt/composition semantics change.
"""

from __future__ import annotations

import hashlib
import json

COMPOSER_VERSION = 1


def instruction_fingerprint(
    campaign_id: str,
    campaign_copy: str,
    closing: str | None,
    *,
    composer_version: int = COMPOSER_VERSION,
) -> str:
    source = {
        "campaign_id": campaign_id,
        "campaign_copy": campaign_copy,
        "closing": closing,
        "composer_version": composer_version,
    }
    return hashlib.sha256(
        json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
