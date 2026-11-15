"""Checking that an email only says things we can actually back up.

The rule, in one sentence: **every specific detail in a draft must appear
either in that recipient's evidence or in our own approved copy.**

A specific is a name, a place, a number, a product term — the things that are
either right or wrong. "Handloom and powerloom in Hyderabad" is checkable. "Your
business seems well established" is not.

So each sentence gets one of four verdicts:

- **neutral** — it says nothing about the recipient at all. A greeting, a line
  about what we sell, a sign-off. There is nothing here that could be wrong
  about them, so it is not flagged.
- **grounded** — it says something specific about them, and every specific
  traces back.
- **unverifiable** — it *is* about them, but says nothing checkable. Not wrong,
  not provable. You decide whether to keep it. (This is the "maybe" bucket.)
- **unsupported** — it contains a specific that is nowhere in the evidence, or
  it cites an evidence field that does not exist. This never reaches a
  recipient.

The split between neutral and unverifiable matters more than it looks. Without
it, every "Hello," and "Best regards" lands in the maybe pile, and a flag list
long enough to skim past is a flag list nobody reads.

The checker is deliberately tuned to **over-flag rather than under-flag**. A
false alarm costs you a moment; a miss costs a relationship with a buyer who
notices you made something up about them.

One honest limitation
---------------------
A word is read as a specific if it is capitalised *and not the first word of
the sentence*, or if it contains a digit anywhere. The first word is skipped
because every sentence starts with a capital, and trying to tell "About" and
"Congratulations" apart from "Coimbatore" needs a dictionary we do not have.

So an invented place name used as the very first word of a sentence would slip
through the capitalisation test. In practice fabrications appear mid-sentence
("your Coimbatore unit", "we spoke with Mr Sharma"), and the alternative — a
hand-maintained list of every common English opener — produces false alarms
forever, which is worse: a checker that cries wolf stops being read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9''\-\.]*")
_HAS_DIGIT = re.compile(r"\d")

# Capitalised words that carry no factual claim: sentence openers, courtesies,
# months, and the first person. Anything here is never treated as a specific.
_NOT_A_CLAIM = frozenset(
    """
    a an and as at be been but by can could dear do does for from had has have
    hello hi how i i'm i've if in is it its may me might most much my of on or
    our ours please regards should since so thank thanks that the their them
    then there these they this those to us was we we're were what when where
    which who will with would you you're your yours best kind sincerely warm
    mr mrs ms dr shri sir madam
    january february march april june july august september october november
    december monday tuesday wednesday thursday friday saturday sunday
    """.split()  # noqa: SIM905 - a readable word list beats one 900-character line
)


class Verdict(StrEnum):
    NEUTRAL = "neutral"
    GROUNDED = "grounded"
    UNVERIFIABLE = "unverifiable"
    UNSUPPORTED = "unsupported"
    # Not about truth: the sentence repeats the fixed closing, or an earlier
    # sentence. Removed like an unsupported line, but it does not block.
    REPEATS = "repeats"


# Words that make a sentence be *about* the recipient. A sentence with none of
# these, no citation and no specifics is not a claim at all.
_ADDRESSES_RECIPIENT = frozenset({"you", "your", "yours", "you're", "yourself"})


@dataclass(frozen=True)
class SentenceCheck:
    text: str
    verdict: Verdict
    specifics: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    reason: str | None = None


def _words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def _normalise(word: str) -> str:
    """Lowercase, and strip possessives and trailing punctuation."""
    word = word.strip(".-'’")
    for suffix in ("'s", "’s"):
        if word.lower().endswith(suffix):
            word = word[: -len(suffix)]
    return word.lower()


def _stem(word: str) -> str:
    """Fold a simple plural onto its singular: samples -> sample.

    Found on the first real run: a subject line saying "Samples" was blocked
    because the campaign copy said "sample". The same fold is applied to both
    sides of every comparison, so it can only ever make two spellings of one
    word agree — it cannot make an unrelated word pass. Words ending in -ss
    (process, glass) are left alone.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def allowed_vocabulary(
    evidence: dict[str, str],
    *,
    company: str | None = None,
    campaign_copy: str = "",
    sender: str = "",
) -> set[str]:
    """Every word we are allowed to be specific about.

    Four sources, and only four: the facts held on this recipient, their
    company name, our own approved copy about what we sell, and the sender's
    own name — signing your own email is not a claim about anybody else.

    Each word is stored both as written and folded to its singular.
    """
    text = " ".join([*evidence.values(), company or "", campaign_copy, sender])
    words = {_normalise(w) for w in _words(text)} - {""}
    return words | {_stem(w) for w in words}


def _echoes(text: str, source: str) -> bool:
    """Does this sentence visibly restate the evidence it cites?

    Two shared content words is a low bar on purpose. The question here is only
    whether the sentence is *about* the cited fact — whether it is true has
    already been settled by the specifics check.
    """

    def content(s: str) -> set[str]:
        return {
            w for w in (_normalise(x) for x in _words(s)) if len(w) >= 3 and w not in _NOT_A_CLAIM
        }

    return len(content(text) & content(source)) >= 2


def specifics_in(sentence: str) -> list[str]:
    """The checkable details in one sentence: names, places and numbers.

    The first word is exempt from the capitalisation test — see the limitation
    noted at the top of this file. Digits are checked wherever they appear, so
    "40 looms" and "since 1987" are caught even at the start.
    """
    found: list[str] = []
    for position, word in enumerate(_words(sentence)):
        clean = _normalise(word)
        if not clean or clean in _NOT_A_CLAIM:
            continue
        has_digit = bool(_HAS_DIGIT.search(word))
        capitalised_mid_sentence = position > 0 and word[0].isupper()
        if (has_digit or capitalised_mid_sentence) and clean not in found:
            found.append(clean)
    return found


def check_sentence(
    text: str,
    *,
    cites: str | None,
    evidence: dict[str, str],
    vocabulary: set[str],
) -> SentenceCheck:
    """Judge one sentence. See the four verdicts at the top of this file."""
    if cites is not None and cites not in evidence:
        return SentenceCheck(
            text=text,
            verdict=Verdict.UNSUPPORTED,
            reason=(
                f"Cites '{cites}', which is not something we hold on this "
                f"recipient. Known: {', '.join(sorted(evidence)) or 'nothing'}."
            ),
        )

    found = specifics_in(text)
    unsupported = tuple(w for w in found if w not in vocabulary and _stem(w) not in vocabulary)

    if unsupported:
        return SentenceCheck(
            text=text,
            verdict=Verdict.UNSUPPORTED,
            specifics=tuple(found),
            unsupported=unsupported,
            reason=(f"Nothing we hold mentions {', '.join(repr(w) for w in unsupported)}."),
        )

    if not found and cites is not None and _echoes(text, evidence[cites]):
        # It cites a real fact and plainly restates it. There is nothing
        # capitalised to check, but this is not a vague claim either.
        return SentenceCheck(text=text, verdict=Verdict.GROUNDED)

    if not found and text.rstrip().endswith("?") and cites is None:
        # A question asserts nothing. "Would you like a sample?" is on every
        # email, and flagging it would bury the flags that matter. A question
        # with an invented detail in it is still caught above, by the
        # specifics check, before it can reach this line.
        return SentenceCheck(text=text, verdict=Verdict.NEUTRAL)

    if not found:
        about_them = cites is not None or any(
            _normalise(w) in _ADDRESSES_RECIPIENT for w in _words(text)
        )
        if not about_them:
            return SentenceCheck(
                text=text,
                verdict=Verdict.NEUTRAL,
                reason=None,
            )
        return SentenceCheck(
            text=text,
            verdict=Verdict.UNVERIFIABLE,
            reason="About them, but says nothing checkable. Keep it or cut it — your call.",
        )

    return SentenceCheck(text=text, verdict=Verdict.GROUNDED, specifics=tuple(found))


def content_words(text: str) -> set[str]:
    """The words that carry meaning: no stop-words, no short words, plurals
    folded. Used to tell whether two sentences say the same thing."""
    return {
        _stem(w)
        for w in (_normalise(x) for x in _words(text))
        if len(w) >= 3 and w not in _NOT_A_CLAIM
    }
