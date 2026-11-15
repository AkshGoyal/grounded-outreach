"""The adversarial set: drafts containing deliberate lies, which must be caught.

Every fabrication here is the kind a model actually produces — plausible,
well-written, and wrong. If any of these ever passes, the guard is decorative.
"""

import pytest

from outreach.core.drafting import Draft, DraftSentence, DraftVerdict, check_draft
from outreach.core.grounding import Verdict

EVIDENCE = {
    "City": "Hyderabad",
    "What they make": "Handloom and powerloom",
    "Notes": "Asked for samples last year",
    "Contact Person": "M. Reddy",
}
COMPANY = "Deccan Weaves"
COPY = "Star Threads makes RFD cotton sewing thread in Ludhiana. We send free samples."


def _draft(*sentences, subject="About RFD cotton thread"):
    return Draft(
        subject=subject,
        sentences=[DraftSentence(text=t, cites=c) for t, c in sentences],
    )


def _check(draft):
    return check_draft(draft, evidence=EVIDENCE, company=COMPANY, campaign_copy=COPY)


# --- the lies that must never get through -----------------------------------


@pytest.mark.parametrize(
    "lie",
    [
        "I saw you have just expanded into Coimbatore.",
        "Your Bengaluru unit would be a good fit for this.",
        "We spoke with Mr Sharma at your office last month.",
        "You run 40 looms, which is exactly our range.",
        "Congratulations on the ISO 9001 certification.",
        "Since 1987 you have been a leader in this segment.",
    ],
)
def test_an_invented_specific_is_caught(lie):
    result = _check(_draft((lie, "Notes")))
    assert result.verdict is DraftVerdict.BLOCKED
    assert result.blocked, f"this got through: {lie}"


def test_a_lie_in_the_subject_line_is_caught_too():
    """The subject is the first thing read and the easiest place to forget."""
    result = _check(_draft(("A short note.", None), subject="Following up on Coimbatore"))
    assert result.verdict is DraftVerdict.BLOCKED


def test_citing_a_field_that_does_not_exist_is_caught():
    """A model that invents its own source is more dangerous than one that
    invents a fact, because the citation makes it look verified."""
    result = _check(_draft(("You work with cotton.", "Annual Turnover")))
    assert result.verdict is DraftVerdict.BLOCKED
    assert "Annual Turnover" in result.blocked[0].reason


def test_the_reason_names_the_offending_word():
    result = _check(_draft(("Your Coimbatore plant is impressive.", "City")))
    assert "coimbatore" in result.blocked[0].reason.lower()


def test_a_blocked_sentence_never_reaches_the_email():
    result = _check(
        _draft(
            ("You do handloom and powerloom work in Hyderabad.", "What they make"),
            ("I saw your new Coimbatore unit.", "City"),
        )
    )
    assert "Coimbatore" not in result.sendable_body()
    assert "Hyderabad" in result.sendable_body()


# --- what should pass -------------------------------------------------------


def test_a_true_specific_claim_is_grounded():
    result = _check(_draft(("You do handloom and powerloom work in Hyderabad.", "What they make")))
    assert result.verdict is DraftVerdict.CLEAN


def test_our_own_product_words_are_allowed():
    """Saying what *we* make is not a claim about the recipient."""
    result = _check(_draft(("We make RFD cotton sewing thread in Ludhiana.", None)))
    assert result.verdict is DraftVerdict.CLEAN


def test_referring_to_the_company_by_name_is_fine():
    result = _check(_draft(("I am writing to Deccan Weaves about thread.", None)))
    assert result.verdict is DraftVerdict.CLEAN


def test_ordinary_sentence_openers_are_not_treated_as_claims():
    result = _check(
        _draft(
            ("Hello,", None),
            ("Would a sample be useful?", None),
            ("Best regards", None),
        )
    )
    assert not result.blocked


# --- the "maybe" bucket -----------------------------------------------------


def test_a_vague_claim_is_flagged_for_you_rather_than_blocked():
    """It is not provably false, so blocking it would be wrong. It is not
    provably true either, so passing it silently would be worse."""
    result = _check(_draft(("Your business seems well established.", None)))
    assert result.verdict is DraftVerdict.NEEDS_YOUR_CALL
    assert len(result.unverifiable) == 1


def test_you_can_drop_the_maybes():
    result = _check(
        _draft(
            ("You do handloom and powerloom work in Hyderabad.", "What they make"),
            ("Your business seems well established.", None),
        )
    )
    kept = result.sendable_body(keep_unverifiable=True)
    cut = result.sendable_body(keep_unverifiable=False)
    assert "well established" in kept
    assert "well established" not in cut
    assert "Hyderabad" in cut


def test_a_draft_with_one_lie_and_one_maybe_is_blocked_not_merely_flagged():
    result = _check(
        _draft(
            ("Your business seems well established.", None),
            ("I saw your Coimbatore unit.", "City"),
        )
    )
    assert result.verdict is DraftVerdict.BLOCKED


# --- the shape of what the model may return ---------------------------------


def test_an_empty_draft_is_not_expressible():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Draft(subject="Hello", sentences=[])


def test_an_empty_subject_is_not_expressible():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Draft(subject="", sentences=[DraftSentence(text="Hi.")])


def test_every_sentence_gets_a_verdict():
    result = _check(_draft(("One.", None), ("Two.", None), ("Three.", None)))
    assert len(result.checks) == 3, "the body"
    assert len(result.all_checks) == 4, "the body plus the subject line"
    assert all(c.verdict in set(Verdict) for c in result.all_checks)


def test_the_subject_is_not_part_of_the_body():
    """It was, briefly. The subject would have been pasted onto the front of
    every email."""
    result = _check(_draft(("Hello there.", None), subject="RFD cotton thread — sample offer"))
    assert "sample offer" not in result.sendable_body()
    assert result.sendable_subject() == "RFD cotton thread — sample offer"


def test_a_greeting_is_not_a_maybe():
    """Only sentences that are *about the recipient* land in the maybe pile.
    A flag list long enough to skim past is a flag list nobody reads."""
    result = _check(
        _draft(
            ("Hello,", None),
            ("We make RFD cotton sewing thread in Ludhiana.", None),
            ("Best regards", None),
        )
    )
    assert result.verdict is DraftVerdict.CLEAN
    assert result.unverifiable == []


def test_a_vague_claim_about_them_is_still_a_maybe():
    result = _check(_draft(("Your operation looks impressive.", None)))
    assert result.verdict is DraftVerdict.NEEDS_YOUR_CALL


def test_a_blocked_subject_means_there_is_no_subject_to_send():
    result = _check(_draft(("Hello.", None), subject="About your Coimbatore plant"))
    assert result.verdict is DraftVerdict.BLOCKED
    assert result.sendable_subject() is None


# --- the known gap, written down rather than hidden -------------------------


def test_a_lie_as_the_very_first_word_slips_through():
    """This documents a real limitation, it does not endorse it.

    Every sentence starts with a capital, so the first word is exempt from the
    capitalisation test — otherwise "About" and "Congratulations" get flagged
    forever and the checker stops being trusted. The cost is that an invented
    place name used as the opening word is not caught this way.

    If this test ever starts failing, someone improved the checker. Delete it
    and celebrate.
    """
    result = _check(_draft(("Coimbatore is a strong market for you.", None)))
    assert result.verdict is not DraftVerdict.BLOCKED


def test_but_a_lie_with_a_number_is_caught_even_first():
    """Digits are checked wherever they appear, including the opening word."""
    result = _check(_draft(("1987 was a good year for your firm.", None)))
    assert result.verdict is DraftVerdict.BLOCKED


# --- false alarms that would make you stop trusting the flags ---------------


def test_signing_your_own_name_is_not_a_claim_about_them():
    result = check_draft(
        _draft(("Best regards, Aksh", None)),
        evidence=EVIDENCE,
        company=COMPANY,
        campaign_copy=COPY,
        sender="Aksh Goyal",
    )
    assert result.verdict is not DraftVerdict.BLOCKED


def test_a_sentence_restating_the_evidence_it_cites_is_grounded_not_a_maybe():
    """'You asked about samples last year' has nothing capitalised in it, but
    it plainly restates the Notes field. Calling that a maybe is noise."""
    result = _check(_draft(("You asked about samples last year, so I am following up.", "Notes")))
    assert result.verdict is DraftVerdict.CLEAN


def test_but_a_sentence_citing_evidence_it_does_not_restate_is_still_a_maybe():
    result = _check(_draft(("You seem like a good fit for us.", "Notes")))
    assert result.verdict is DraftVerdict.NEEDS_YOUR_CALL


def test_a_plain_question_is_not_a_maybe():
    """'Would you like a sample?' closes every email. Flagging it would bury
    the flags that matter."""
    result = _check(_draft(("Would you like a sample?", None)))
    assert result.verdict is DraftVerdict.CLEAN


def test_a_question_carrying_an_invented_detail_is_still_caught():
    result = _check(_draft(("Is your Coimbatore unit still running?", None)))
    assert result.verdict is DraftVerdict.BLOCKED
