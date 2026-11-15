"""Regressions from the first real run against live models, 2026-09-23.

Each test here is a specific thing that went wrong on real contacts with real
models. They are kept together so the history is readable in one place.
"""

import pytest
from pydantic import ValidationError

from outreach.core.drafting import (
    Draft,
    DraftSentence,
    DraftVerdict,
    build_prompt,
    check_draft,
    draft_email,
    schema_for,
)
from outreach.ports.llm import LLMError
from tests.fakes.llm import FakeLLM

EVIDENCE = {
    "Segment": "Garment dyeing",
    "City": "Tiruppur",
    "What they do (verified)": "Plain garment-dyed T-shirts and blanks",
}
COPY = "Star Threads makes 100% cotton RFD thread in Ludhiana. We offer trial sample cones."


# --- 1. "Samples" in a subject was blocked because the copy said "sample" ----


def test_a_plural_matches_its_singular():
    draft = Draft(
        subject="RFD Cotton Thread Samples for Garment Dyeing",
        sentences=[DraftSentence(text="Hello.")],
    )
    result = check_draft(draft, evidence=EVIDENCE, company="Tirupur Brands", campaign_copy=COPY)
    assert result.subject_check.verdict.value != "unsupported"


def test_plural_folding_does_not_let_an_invented_place_through():
    """The fold only makes two spellings of one word agree. It must not make
    an unrelated word pass."""
    draft = Draft(subject="About your Coimbatores units", sentences=[DraftSentence(text="Hi.")])
    result = check_draft(draft, evidence=EVIDENCE, company="Tirupur Brands", campaign_copy=COPY)
    assert result.verdict is DraftVerdict.BLOCKED


# --- 2. A model cited two fields as one: "What they do (verified), City" -----


def test_a_merged_citation_cannot_be_expressed():
    schema = schema_for(list(EVIDENCE))
    with pytest.raises(ValidationError):
        schema.model_validate(
            {
                "subject": "x",
                "sentences": [{"text": "y", "cites": "What they do (verified), City"}],
            }
        )


def test_an_invented_field_name_cannot_be_expressed():
    with pytest.raises(ValidationError):
        schema_for(list(EVIDENCE)).model_validate(
            {"subject": "x", "sentences": [{"text": "y", "cites": "Annual Turnover"}]}
        )


def test_a_real_field_name_is_accepted():
    ok = schema_for(list(EVIDENCE)).model_validate(
        {"subject": "x", "sentences": [{"text": "You are in Tiruppur.", "cites": "City"}]}
    )
    assert ok.sentences[0].cites == "City"


def test_with_no_evidence_the_only_citation_allowed_is_none():
    schema = schema_for([])
    schema.model_validate({"subject": "x", "sentences": [{"text": "y", "cites": None}]})
    with pytest.raises(ValidationError):
        schema.model_validate({"subject": "x", "sentences": [{"text": "y", "cites": "City"}]})


def test_the_constraint_reaches_the_api_as_an_enum():
    """Strict mode can only enforce what the schema says. The allowed field
    names must be in the schema OpenRouter receives, not just checked after."""
    from outreach.adapters.llm_openrouter import _strict_schema

    text = str(_strict_schema(schema_for(list(EVIDENCE))))
    assert "enum" in text
    assert "What they do (verified)" in text


def test_draft_email_rejects_a_merged_citation_from_the_model():
    bad = Draft(
        subject="x",
        sentences=[DraftSentence(text="y", cites="What they do (verified), City")],
    )
    with pytest.raises(LLMError):
        draft_email(
            FakeLLM(responses=[bad]),
            company="Tirupur Brands",
            evidence=EVIDENCE,
            campaign_copy=COPY,
            sender="Aksh Goyal",
        )


# --- 3. Every email signed off as the company, because the prompt never said
#        who was writing ---------------------------------------------------


def test_the_prompt_says_who_is_writing():
    prompt = build_prompt(
        company="CR Garments", evidence=EVIDENCE, campaign_copy=COPY, sender="Aksh Goyal"
    )
    assert "You are Aksh Goyal" in prompt
    assert prompt.count("Aksh Goyal") >= 2, "named as writer and in the sign-off instruction"


def test_the_prompt_forbids_pasting_raw_cell_text():
    prompt = build_prompt(company="X", evidence=EVIDENCE, campaign_copy=COPY, sender="A")
    assert "Rephrase facts in ordinary English" in prompt
    assert "leave the figure out" in prompt


def test_the_prompt_no_longer_asks_for_permission_wording():
    """'Please reply to give permission for us to send a sample' was lifted
    straight from the old prompt."""
    prompt = build_prompt(company="X", evidence=EVIDENCE, campaign_copy=COPY, sender="A")
    assert "permission" not in prompt.lower()


def test_the_prompt_has_no_unfilled_placeholders():
    prompt = build_prompt(company="X", evidence=EVIDENCE, campaign_copy=COPY, sender="A")
    assert "{" not in prompt and "}" not in prompt


# --- 4. The default model is the one that won ------------------------------


def test_the_default_model_is_the_measured_winner():
    from outreach.config import load_settings

    assert load_settings(_env_file=None).llm_model == "openai/gpt-5.6-luna"


def test_the_prompt_changelog_never_reaches_the_model():
    """The version history quotes past bad output on purpose. Sending it to the
    model would show it exactly the phrasing we are trying to stop."""
    prompt = build_prompt(company="X", evidence=EVIDENCE, campaign_copy=COPY, sender="A")
    assert "version:" not in prompt
    assert "<!--" not in prompt
    assert "was being copied verbatim" not in prompt
