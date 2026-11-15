"""Immutable campaign instruction snapshots for generated draft provenance.

Version 1 hashes the campaign identity and exact loaded copy/closing. Bump the
composer version when shared generation semantics change so drafts require review.
"""

from __future__ import annotations

from outreach.campaigns import is_valid_id, load_closing, load_copy
from outreach.core.generation import COMPOSER_VERSION, instruction_fingerprint


def instruction_hash(generation: dict) -> str:
    return instruction_fingerprint(
        generation["campaign_id"],
        generation["campaign_copy"],
        generation["closing"],
        composer_version=generation["composer_version"],
    )


def generation_snapshot(campaign_id: str) -> dict:
    """Read only this campaign's current configuration; never borrow another."""
    if not is_valid_id(campaign_id):
        raise ValueError("Choose a valid campaign.")
    copy = load_copy(campaign_id)
    if not copy:
        raise ValueError("Save this campaign's email instructions before generating drafts.")
    snapshot = {
        "campaign_id": campaign_id,
        "campaign_copy": copy,
        "closing": load_closing(campaign_id),
        "composer_version": COMPOSER_VERSION,
    }
    snapshot["instruction_hash"] = instruction_hash(snapshot)
    return snapshot


def current_generation_matches(generation: dict | None) -> bool:
    """False for stale or malformed snapshots; legacy drafts have no snapshot."""
    if not generation:
        return False
    try:
        return (
            generation["instruction_hash"] == instruction_hash(generation)
            and generation["instruction_hash"]
            == generation_snapshot(generation["campaign_id"])["instruction_hash"]
        )
    except (KeyError, TypeError, ValueError, OSError):
        return False


def recipient_generation(generation: dict, contact) -> dict:
    """Retain the exact recipient context used for this model request."""
    return {
        **generation,
        "contact_id": contact.id,
        "recipient_company": contact.company,
        "recipient_evidence": dict(contact.evidence),
    }
