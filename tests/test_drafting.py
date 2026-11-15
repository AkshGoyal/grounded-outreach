"""`draft_email` — the function the command line actually calls.

This file exists because it did not. Every other test exercised `check_draft`,
so `draft_email` shipped with a signature the CLI could not call, and the
failure only appeared when a real person ran it.
"""

import pytest

from outreach.core.drafting import Draft, DraftSentence, DraftVerdict, build_prompt, draft_email
from tests.fakes.llm import FakeLLM

EVIDENCE = {"City": "Hyderabad", "What they make": "Handloom and powerloom"}
COPY = "Star Threads makes RFD cotton sewing thread in Ludhiana. We send free samples."


def _llm(*sentences, subject="RFD cotton thread"):
    draft = Draft(
        subject=subject,
        sentences=[DraftSentence(text=t, cites=c) for t, c in sentences],
    )
    return FakeLLM(responses=[draft])


def _draft(llm, **kwargs):
    return draft_email(
        llm,
        company="Deccan Weaves",
        evidence=EVIDENCE,
        campaign_copy=COPY,
        **kwargs,
    )


# --- the call the CLI makes -------------------------------------------------


def test_it_accepts_every_argument_the_cli_passes():
    """The regression this file was written for."""
    result = _draft(_llm(("Hello.", None)), sender="Aksh Goyal")
    assert result.verdict is not None


def test_the_senders_name_is_not_flagged_as_invented():
    result = _draft(_llm(("Best regards, Aksh", None)), sender="Aksh Goyal")
    assert result.verdict is not DraftVerdict.BLOCKED


def test_without_a_sender_the_name_is_flagged():
    """Proves the sender argument is actually doing something, rather than
    being accepted and ignored."""
    result = _draft(_llm(("Best regards, Aksh", None)))
    assert result.verdict is DraftVerdict.BLOCKED


# --- the whole path, end to end ---------------------------------------------


def test_a_clean_draft_comes_back_clean():
    result = _draft(
        _llm(("You do handloom and powerloom work in Hyderabad.", "What they make")),
        sender="Aksh Goyal",
    )
    assert result.verdict is DraftVerdict.CLEAN


def test_a_fabrication_from_the_model_is_blocked():
    result = _draft(_llm(("I saw your new Coimbatore unit.", "City")), sender="Aksh Goyal")
    assert result.verdict is DraftVerdict.BLOCKED
    assert "Coimbatore" not in result.sendable_body()


def test_the_prompt_reaches_the_model_with_the_evidence_in_it():
    llm = _llm(("Hello.", None))
    _draft(llm, sender="Aksh Goyal")
    prompt = llm.prompts[0]
    assert "Hyderabad" in prompt
    assert "Handloom and powerloom" in prompt
    assert "Deccan Weaves" in prompt
    assert "Star Threads" in prompt


def test_the_model_is_told_which_field_names_it_may_cite():
    llm = _llm(("Hello.", None))
    _draft(llm, sender="Aksh Goyal")
    assert "City, What they make" in llm.prompts[0]


# --- the prompt template ----------------------------------------------------


def test_a_contact_with_no_evidence_says_so_rather_than_leaving_a_gap():
    """An empty facts list invites the model to fill it. Say 'nothing'."""
    prompt = build_prompt(company="Alpha Mills", evidence={}, campaign_copy=COPY)
    assert "(nothing)" in prompt


def test_an_llm_failure_is_not_swallowed():
    from outreach.ports.llm import LLMError

    with pytest.raises(LLMError):
        _draft(FakeLLM(responses=[]), sender="Aksh Goyal")
