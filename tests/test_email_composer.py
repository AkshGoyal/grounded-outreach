"""One-call composing protects exact blocks and separates campaign instructions."""

import pytest

from outreach.core.drafting import build_prompt, draft_email
from outreach.core.email_composer import parse_editor, resolve_fixed
from outreach.core.review import approval_blocker, recheck, storable_body
from outreach.ports.llm import LLMError


class SectionsLLM:
    def __init__(self, sections):
        self.sections = sections
        self.prompts = []

    def generate(self, *, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        return schema.model_validate({"subject": "A brief introduction", "sections": self.sections})


def section(index, text):
    return {"index": index, "sentences": [{"text": text, "cites": None}]}


SOURCE = """Write a short job-search introduction.
[KEEP]
I have already applied through the careers portal.
[/KEEP]
Ask for a brief conversation.
[KEEP]
Best regards,
Keshav
[/KEEP]"""


def compose(source=SOURCE, llm=None, evidence=None):
    llm = llm or SectionsLLM([section(0, "Hello."), section(2, "Could we speak briefly?")])
    return draft_email(llm, company="Example", evidence=evidence or {}, campaign_copy=source)


def test_parser_preserves_lines_spaces_punctuation_and_relative_positions():
    parts = parse_editor("[KEEP]\n  Hello,\n\nfriend!  \n[/KEEP]\nWrite a sentence.")
    assert [(p.kind, p.index) for p in parts] == [("keep", 0), ("generate", 1)]
    assert parts[0].text == "  Hello,\n\nfriend!  "


@pytest.mark.parametrize(
    "source", ["[KEEP]unclosed", "[/KEEP]", "[KEEP][KEEP]x[/KEEP][/KEEP]", "[KEEP] [/KEEP]"]
)
def test_invalid_markers_are_clear_errors(source):
    with pytest.raises(ValueError):
        parse_editor(source)


def test_exact_middle_and_end_are_programmatically_assembled_one_call():
    llm = SectionsLLM([section(0, "Hello."), section(2, "Could we speak briefly?")])
    result = compose(llm=llm)
    assert storable_body(result) == (
        "Hello.\n\nI have already applied through the careers portal.\n\n"
        "Could we speak briefly?\n\nBest regards,\nKeshav"
    )
    assert len(llm.prompts) == 1
    assert "job-search" in llm.prompts[0]
    assert "Star Threads" not in llm.prompts[0]
    assert "Write a short" not in storable_body(result)


def test_fixed_only_email_still_has_subject_without_generated_sections():
    result = compose("[KEEP]\nHello.\n[/KEEP]", SectionsLLM([]))
    assert storable_body(result) == "Hello."


@pytest.mark.parametrize(
    "sections",
    [
        [section(2, "Hello."), section(0, "Hi.")],
        [section(0, "Hello.")],
        [section(0, "Hello."), section(0, "Hi.")],
    ],
)
def test_bad_section_identity_is_rejected(sections):
    with pytest.raises(LLMError):
        compose(llm=SectionsLLM(sections))


def test_model_cannot_duplicate_fixed_block():
    with pytest.raises(LLMError):
        compose(
            llm=SectionsLLM(
                [
                    section(0, "I have already applied through the careers portal."),
                    section(2, "Hi."),
                ]
            )
        )


def test_variables_are_explicit_deterministic_and_missing_fails_before_model():
    assert (
        resolve_fixed(
            "Hi {{name}} at {{company}}, {{designation}}.",
            evidence={"Name": "Sam", "Designation": "Director"},
            company="Example",
        )
        == "Hi Sam at Example, Director."
    )
    for text in ["{{unknown}}", "{{name}}"]:
        llm = SectionsLLM([])
        with pytest.raises(ValueError):
            compose("[KEEP]" + text + "[/KEEP]", llm)
        assert not llm.prompts


@pytest.mark.parametrize("change", ["remove", "rewrite", "reverse", "spacing"])
def test_edited_fixed_blocks_cannot_be_approved(change):
    body = storable_body(compose())
    if change == "remove":
        body = body.replace("I have already applied through the careers portal.", "")
    elif change == "rewrite":
        body = body.replace("already applied", "previously applied")
    elif change == "reverse":
        body = "Best regards,\nKeshav\n\nI have already applied through the careers portal."
    else:
        body = body.replace("Best regards,\nKeshav", "Best regards, Keshav")
    result = recheck(
        "A brief introduction",
        body,
        evidence={},
        company="Example",
        campaign_copy=SOURCE,
        sender="",
    )
    assert "fixed KEEP" in approval_blocker(result)


def test_unchanged_blocks_pass_preservation_check_and_survive_storable_body():
    body = storable_body(compose())
    result = recheck(
        "A brief introduction",
        body,
        evidence={},
        company="Example",
        campaign_copy=SOURCE,
        sender="",
    )
    assert not approval_blocker(result)
    assert storable_body(result) == body


def test_global_prompt_is_neutral_for_new_campaigns_with_or_without_legacy_closing():
    for closing in [None, "Best regards, Keshav"]:
        prompt = build_prompt(
            company="Example",
            evidence={},
            campaign_copy="Write job-search outreach about my analytics background.",
            closing=closing,
        )
        assert "job-search" in prompt
        for contaminant in ["Star Threads", "cotton", "Ludhiana", "sample"]:
            assert contaminant not in prompt


def test_generated_repetitions_are_checked_across_instruction_gaps():
    llm = SectionsLLM(
        [section(0, "Could we speak briefly?"), section(2, "Could we speak briefly?")]
    )
    result = compose(llm=llm)
    assert storable_body(result).count("Could we speak briefly?") == 1
    assert any(check.verdict.value == "repeats" for check in result.checks)


def test_unknown_or_incomplete_fixed_variables_rejected_when_saving():
    for text in ["{{unknown}}", "{{name", "company}}"]:
        with pytest.raises(ValueError):
            parse_editor("[KEEP]" + text + "[/KEEP]")
