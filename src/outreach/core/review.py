"""Turning a checked draft into something a person approves, edits or rejects.

Three rules, and they are the whole of this file:

1. **Lines the checker could not back up are removed before you see the
   draft.** They were promised never to reach a recipient, so they do not
   reach the review screen as sendable text either. You are shown what was
   removed and why.
2. **The "maybe" lines stay in, marked.** They are about the recipient but not
   checkable — your call, as agreed.
3. **An edit is checked again, and a draft cannot be approved while any line
   in it is unsupported** — including lines you typed. If you know something
   true that is not in the spreadsheet, put it in the spreadsheet. That keeps
   the rule "every claim traces to evidence" true all the way to the send.
"""

from __future__ import annotations

from pydantic import ValidationError

from outreach.core.drafting import CheckedDraft, Draft, DraftSentence, DraftVerdict, check_draft
from outreach.core.email_composer import fixed_content, fixed_content_problem, has_fixed_content
from outreach.core.flow import split_sentences
from outreach.core.grounding import SentenceCheck, Verdict

__all__ = ["split_sentences"]  # re-exported: callers split text the same way the checks do


def storable_body(result: CheckedDraft) -> str:
    """The body as it goes to review: unsupported lines already removed,
    maybes kept, one sentence per paragraph so it reads like an email."""
    if result.assembled_body is not None:
        return result.assembled_body
    keep = {Verdict.GROUNDED, Verdict.NEUTRAL, Verdict.UNVERIFIABLE}
    return "\n\n".join(c.text.strip() for c in result.checks if c.verdict in keep)


def checks_for_display(result: CheckedDraft) -> list[dict]:
    """Every line with its verdict, for the review screen. Removed lines are
    included and flagged, so it is visible what the checker took out."""
    return [
        {
            "text": c.text,
            "verdict": c.verdict.value,
            "reason": c.reason,
            "removed": c.verdict in (Verdict.UNSUPPORTED, Verdict.REPEATS)
            and c.text not in result.fixed_blocks,
            "is_subject": c is result.subject_check,
        }
        for c in result.all_checks
    ]


def recheck(
    subject: str,
    body: str,
    *,
    evidence: dict[str, str],
    company: str | None,
    campaign_copy: str,
    sender: str,
    closing: str | None = None,
) -> CheckedDraft | None:
    """Check edited text again. Returns None if there is nothing to check.

    Repeats in text you typed are flagged, not removed — it is your text —
    and approval waits until you delete them."""
    sentences = split_sentences(body)
    try:
        draft = Draft(
            subject=subject.strip(),
            sentences=[DraftSentence(text=s) for s in sentences],
        )
    except ValidationError:
        return None
    result = check_draft(
        draft,
        evidence=evidence,
        company=company,
        campaign_copy=campaign_copy,
        sender=sender,
        closing=closing,
    )

    if has_fixed_content(campaign_copy):
        try:
            blocks = fixed_content(campaign_copy, evidence=evidence, company=company)
            problem = fixed_content_problem(body, blocks)
        except ValueError as exc:
            blocks, problem = [], str(exc)
        result.fixed_blocks = tuple(blocks)
        result.assembled_body = body
        if problem:
            result.checks.append(
                SentenceCheck(
                    text="Protected fixed content",
                    verdict=Verdict.UNSUPPORTED,
                    reason=problem,
                )
            )
            result.verdict = DraftVerdict.BLOCKED
    return result


def approval_blocker(result: CheckedDraft | None) -> str | None:
    """Why this draft cannot be approved, or None if it can."""
    if result is None:
        return "The draft needs a subject and at least one sentence."
    problems = []
    blocked = result.blocked
    if blocked:
        lines = "; ".join(f"“{c.text}” — {c.reason}" for c in blocked)
        problems.append(
            f"{len(blocked)} line(s) say something we cannot back up: {lines} "
            "Remove or reword them, or add the fact to the spreadsheet."
        )
    # A repeat never reaches a recipient: the closing would say it again
    # right underneath (D-020).
    repeats = [c for c in result.checks if c.verdict is Verdict.REPEATS]
    if repeats:
        lines = "; ".join(f"“{c.text}” — {c.reason}" for c in repeats)
        problems.append(f"{len(repeats)} line(s) repeat something: {lines} Delete them.")
    return " ".join(problems) or None
