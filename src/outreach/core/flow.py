"""Does the email read as one piece, without saying anything twice?

When a campaign has a fixed closing, the model writes only the opening, and
the closing follows it word for word. The commonest way that goes wrong is the
opening doing the closing's job: offering the sample, pointing at the
website, asking the question, thanking them, signing off. The result reads
like two emails stapled together.

So each sentence the model writes is checked, in plain code, for:

- **anything the closing owns** — the offer, the website, the request, thanks,
  a sign-off, or a question (the closing asks the question);
- **heavy overlap with a closing paragraph** — three or more of its
  distinctive words, not counting product words that the opening legitimately
  shares with it;
- **saying what an earlier sentence already said.**

A sentence the model wrote that is caught here is removed, with the reason
shown. A repeat still in the text — typed in review, or in a draft written
before the closing existed — blocks approval and sending (D-020).
"""

from __future__ import annotations

import re

from outreach.core.grounding import content_words

# Words the closing's job consists of. If the opening uses one, it is doing
# the closing's work.
_CLOSING_OWNS = frozenset(
    {
        "sample", "complimentary", "trial", "dispatch", "courier", "postal",
        "portal", "website", "regard", "sincerely", "thank", "thanks",
    }
)  # fmt: skip
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:co\.in|in|com|net|org)\b", re.IGNORECASE)
_SIGN_OFF = re.compile(
    r"^\s*(?:warm|best|kind|with)?\s*(?:regards|wishes)|^\s*(?:sincerely|yours|thank|thanks)"
    r"|look(?:ing)? forward",
    re.IGNORECASE,
)
_SOFT_OVERLAP = 3
_DUPLICATE = 0.6
# A sentence ends at . ! or ? followed by space, or at a line break.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip()]


def closing_vocabulary(closing: str, *, campaign_copy: str = "") -> set[str]:
    """The closing's distinctive words — minus product words the opening is
    allowed to share with it, which come from the campaign copy."""
    return content_words(closing) - content_words(campaign_copy)


def _similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= _DUPLICATE


def flow_problem(
    sentence: str,
    *,
    earlier: list[str],
    closing: str | None,
    closing_words: set[str],
) -> str | None:
    """Why this sentence should not be in the opening, or None if it belongs."""
    words = content_words(sentence)

    for previous in earlier:
        if _similar(words, content_words(previous)):
            return "Says the same as an earlier sentence."

    if not closing:
        return None

    if _URL.search(sentence):
        return "The closing already gives the website."
    if _SIGN_OFF.search(sentence):
        return "The closing already thanks them and signs off."
    if sentence.rstrip().endswith("?"):
        return "The closing already asks the question."
    owned = sorted(words & _CLOSING_OWNS)
    if owned:
        return f"The closing already covers this (“{owned[0]}”)."
    shared = words & closing_words
    if len(shared) >= _SOFT_OVERLAP:
        return f"Repeats the closing ({', '.join(sorted(shared)[:4])})."
    return None


def repeated_lines(body: str, *, closing: str | None, campaign_copy: str) -> list[tuple[str, str]]:
    """Every line of a stored body that repeats the closing or an earlier line,
    with the reason — checked against the closing as it is *now*.

    Drafting already removes these lines, but a draft can be written before
    the closing existed, or edited afterwards. This is the same check, run
    again on the exact text that would go out, wherever an email can leave:
    approval, a test send, and the real send (D-020).
    """
    closing_words = closing_vocabulary(closing, campaign_copy=campaign_copy) if closing else set()
    found: list[tuple[str, str]] = []
    kept: list[str] = []
    for sentence in split_sentences(body):
        problem = flow_problem(sentence, earlier=kept, closing=closing, closing_words=closing_words)
        if problem:
            found.append((sentence, problem))
        else:
            kept.append(sentence)
    return found
