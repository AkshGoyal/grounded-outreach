"""Dated public excerpts test extraction, not live web recall or deliverability."""

import json
from pathlib import Path

import pytest

from outreach.core.research import email_matches

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "public_email_excerpts.json").read_text(encoding="utf8")
)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_public_email_excerpt(case):
    actual = {value.lower() for _, _, value in email_matches(case["text"])}
    assert actual == set(case["emails"])
