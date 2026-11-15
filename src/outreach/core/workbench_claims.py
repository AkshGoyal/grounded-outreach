"""Deterministic claim checks for a Workbench email draft.

Every sentence of the subject and body is bound to the passages it may rely on: the
selected hook passage, the identity passage, or an approved campaign claim. A sentence
then passes only if its *meaning*, not just its vocabulary, stays inside that support:

- names, numbers and dates must appear in the bound support;
- causal, intent, pain, presupposition, certainty and outcome wording must also appear
  there ("because", "struggling", "still", "clearly", "saves");
- tense must not turn an in-progress or planned development into a completed one, or
  a past event into an ongoing one;
- recency words need a recent dated hook, and relative dates are never computed;
- exactly one question, and it is the campaign's fixed call to action.

Shared vocabulary is reported as information only. A model's own verdict is never
consulted here; these rules are what block approval.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

from outreach.core.grounding import allowed_vocabulary, specifics_in
from outreach.core.workbench_evidence import normal

TARGET_WORDS = (70, 120)
HARD_WORDS = (50, 150)
# Caution words. "Often" and "usually" generalise about people in a role without claiming
# anything about this prospect, so they count as caution too (first Sonnet run: "a new
# finance chief often starts by…" was blocked and cost a repair).
HEDGES = re.compile(
    r"\b(may|might|could|perhaps|possibly|probably|likely|if|often|usually|typically|"
    r"sometimes|tends? to)\b"
)
# The sender explaining their own email ("That's why I'm writing", "I'm writing because…")
# says nothing about the prospect, so it needs no source, caution word or stated cause.
SENDER_META = re.compile(
    r"\b(?:why i ?(?:'|’)?(?:m| am) (?:writing|getting in touch|reaching out)|"
    r"i ?(?:'|’)?(?:m| am) writing (?:because|to|as)|the reason (?:for|i)\b[^.]{0,30}"
    r"(?:note|email|writing))"
)

# (category, pattern, message). Each pattern found in a sentence must also be found in
# the support that sentence relies on.
_RISKY = [
    (
        "causal",
        r"\b(because|since|due to|as a result|so that|which means|means that|resulting in|"
        r"led to|leads to|driven by|thanks to|in order to|to fix|to address|to solve|"
        r"to tackle|to avoid)\b",
        "states a cause or purpose",
    ),
    (
        "intent",
        r"\b(needs?|needed|looking (?:for|to)|interested in|evaluating|considering|budget|"
        r"priorit(?:y|ies)|wants? to|trying to|hoping to|in the market)\b",
        "attributes a need or buying intent",
    ),
    (
        "pain",
        r"\b(struggl\w*|pain\w*|problems?|challeng\w*|frustrat\w*|bottlenecks?|"
        r"falling behind|behind on|backlogs?|costly|expensive|broken|messy|chao\w*|"
        r"slow\w*|delay\w*|errors?|mistakes?|issues|overwhelm\w*|risks?)\b",
        "describes a problem the source does not state",
    ),
    (
        "presupposition",
        r"\b(now that|still|again|finally|already|continues? to|no longer|even|another)\b",
        "presupposes something the source does not state",
    ),
    (
        "certainty",
        r"\b(clearly|obviously|surely|must be|certainly|undoubtedly|i'?m sure|i am sure|"
        r"no doubt|definitely|proves?|shows that|suggests?|indicates?)\b",
        "claims certainty or an implication the source does not state",
    ),
    (
        "outcome",
        r"(\b(sav(?:e|es|ing|ings)|reduc\w*|cuts?|faster|fewer|eliminat\w*|guarantee\w*|"
        r"automatic\w*|automat(?:e|es|ed)|roi|customers?|clients?|trusted|"
        # "a leading provider" is a credential; "leading global IT" is just their job.
        r"(?:a|the|an?|industry|market|world)[ -]leading|"
        r"leading (?:provider|platform|company|solution|vendor|brand|firm|supplier)|"
        r"leading (?:\w+ )?(?:teams|companies|brands|firms|organi[sz]ations|businesses)|"
        r"proven|results?|increas\w*|improv\w*|accura\w*|ai|percent|hours?)\b|%)",
        "claims a result or credential not in the approved campaign",
    ),
]
_FUTURE = re.compile(
    r"\b(will|plans? to|planning|going to|upcoming|soon|intends? to|about to|expected to|set to)\b"
)
_ONGOING = re.compile(r"\b(?:is|are)\s+\w+ing\b|\b(currently|underway|in progress|ongoing)\b")
_PAST = re.compile(
    r"\b(introduced|launched|rolled out|completed|announced|hired|appointed|raised|acquired|"
    r"began|started|implemented|finished|opened|expanded|went live|deployed|adopted|built|"
    r"created)\b"
)
# "Just" means recency only before a verb ("just joined"), not in "just as much".
_RECENT = re.compile(
    r"\b(recent|recently|new|newly|latest|"
    r"just (?:\w+ed|\w+en|took|began|became|won|made|got|came|went))\b"
)
_RELATIVE = re.compile(
    r"\b(yesterday|today|this week|last week|this month|last month|this year|last year|"
    r"this quarter|last quarter|days ago|weeks ago|months ago)\b"
)
_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTH = r"(" + "|".join(_MONTHS + [m[:3] for m in _MONTHS]) + r")\.?"
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b"),
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+(\d{{4}}))?\b"),
    re.compile(rf"\b{_MONTH}(?:\s+(\d{{4}}))?\b"),
]
_SIGNOFFS = {
    "best,",
    "best regards,",
    "regards,",
    "kind regards,",
    "thanks,",
    "thank you,",
    "cheers,",
    "warm regards,",
}
_COMMON = set(
    """
    about also across against been being both from have here into just more most only other
    over same some such than that their them then there these they this those through very
    what when where which while with would your yours team teams noticed notice read reading
    saw seen wondered thought work works working help helps helping like want useful share
    sharing note given whether happy open quick short worth hear question each
    """.split()  # noqa: SIM905 - a readable word list
)


def _acronyms(text):
    """Initials of capitalised titles in the support: "Chief Financial Officer" -> "cfo"."""
    found = set()
    for phrase in re.findall(r"(?:\b[A-Z][a-z]+(?:\s+(?:of|and|&)\s+|\s+)){1,4}[A-Z][a-z]+", text):
        words = [w for w in re.split(r"\s+", phrase) if w[:1].isupper()]
        if 2 <= len(words) <= 5:
            found.add("".join(w[0] for w in words).lower())
    return found


def content_hash(subject, body):
    return hashlib.sha256((subject + "\n\n" + body).encode()).hexdigest()


def campaign_claims(campaign):
    """Stable IDs for the sender's approved claims; nothing else may describe the offer."""
    claims = {"offer": campaign.get("offer", "")}
    for number, text in enumerate(campaign.get("supported_capabilities", []), 1):
        claims[f"capability-{number}"] = text
    for number, text in enumerate(campaign.get("proof_points", []), 1):
        claims[f"proof-{number}"] = text
    return {key: value for key, value in claims.items() if value}


def sender_parts(campaign):
    sender = campaign.get("sender", "")
    name, _, company = sender.partition(",")
    return sender.strip(), name.strip(), company.strip()


def draft_context(run):
    """Everything the checker may rely on, taken only from this run's saved snapshot."""
    result = run.get("result") or {}
    hook = result.get("hook") or {}
    identity = result.get("identity") or {}
    selected = identity.get("selected") or {}
    supports = {}
    for source_id in hook.get("source_ids", [])[:1]:
        supports[source_id] = {"kind": "source", "role": "hook", "text": hook.get("summary", "")}
    if selected.get("source_id") and selected.get("quote"):
        supports.setdefault(
            selected["source_id"],
            {"kind": "source", "role": "identity", "text": selected["quote"]},
        )
    # Every other fact that passed the checks may be used too; the reviewer can leave any
    # of them out (run["exclude"]) and the email is rewritten without it.
    for signal in result.get("candidate_signals") or []:
        quote, source_id = signal.get("quote", ""), signal.get("source_id")
        if not quote or not source_id or quote == hook.get("summary"):
            continue
        if source_id in supports:
            if quote not in supports[source_id]["text"]:
                supports[source_id]["text"] += " " + quote
        elif len([s for s in supports.values() if s["role"] == "extra"]) < 3:
            supports[source_id] = {"kind": "source", "role": "extra", "text": quote}
    # Context and background facts are used only when the reviewer ticks them.
    for signal in result.get("context_signals") or []:
        source_id = signal.get("source_id")
        if source_id in (run.get("include") or []) and signal.get("quote"):
            if source_id in supports:
                if signal["quote"] not in supports[source_id]["text"]:
                    supports[source_id]["text"] += " " + signal["quote"]
            else:
                supports[source_id] = {"kind": "source", "role": "extra", "text": signal["quote"]}
    for source_id in [x for x in run.get("exclude") or [] if x != "__rewrite__"]:
        if source_id in supports and supports[source_id]["role"] != "hook":
            supports.pop(source_id)
    for claim_id, text in campaign_claims(run["campaign"]).items():
        if claim_id not in (run.get("exclude") or []):
            supports[claim_id] = {"kind": "campaign", "role": "offer", "text": text}
    sender, sender_name, sender_company = sender_parts(run["campaign"])
    return {
        "prospect": {k: run["prospect"].get(k, "") for k in ("name", "company", "role")},
        "identity_summary": identity.get("summary", ""),
        "hook": {
            "source_id": (hook.get("source_ids") or [None])[0],
            "summary": hook.get("summary", ""),
            "temporal_label": hook.get("temporal_label", ""),
            "basis": hook.get("basis", "read_source"),
            "event_date": hook.get("event_date"),
        },
        "supports": supports,
        "cta": run["campaign"].get("cta", ""),
        "sender": sender,
        "sender_name": sender_name,
        "sender_company": sender_company,
        "campaign_id": run["campaign"].get("id"),
        "campaign_version": run["campaign"].get("version"),
    }


def terms(value):
    return {
        word[:-1] if word.endswith("s") and not word.endswith("ss") else word
        for word in re.findall(r"[a-z][a-z'-]{3,}", normal(value))
        if word not in _COMMON
    }


def _segments(subject, body):
    found = [{"part": "subject", "text": subject.strip(), "role": "content"}]
    lines = [line.strip() for line in body.replace("\r\n", "\n").split("\n")]
    for line in lines:
        if not line:
            continue
        lowered = normal(line)
        if re.fullmatch(r"(hi|hello|dear)\s+[^,.!?]{1,80}[,!]?", lowered):
            found.append({"part": "body", "text": line, "role": "greeting"})
            continue
        if lowered in _SIGNOFFS:
            found.append({"part": "body", "text": line, "role": "signoff"})
            continue
        for sentence in re.split(r"(?<=[.!?])\s+(?=[\"“'A-Z0-9])", line):
            if sentence.strip():
                found.append({"part": "body", "text": sentence.strip(), "role": "content"})
    return found


def _dates(text):
    """(year, month, day) tuples with None for components the text does not state."""
    found, lowered = [], normal(text)
    consumed = lowered
    for number, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(consumed):
            groups = match.groups()
            if number == 0:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            elif number == 1:
                month = _month_number(groups[0])
                day, year = int(groups[1]), int(groups[2]) if groups[2] else None
            elif number == 2:
                day, month = int(groups[0]), _month_number(groups[1])
                year = int(groups[2]) if groups[2] else None
            else:
                if groups[0] == "may" and not groups[1]:
                    continue  # "may" is far more often a hedge than a month.
                month, day = _month_number(groups[0]), None
                year = int(groups[1]) if groups[1] else None
            found.append((year, month, day))
        consumed = pattern.sub(" ", consumed)
    return found


def _month_number(value):
    value = value.rstrip(".")
    for number, month in enumerate(_MONTHS, 1):
        if value in (month, month[:3]):
            return number
    return None


def _date_supported(mentioned, known):
    return any(
        all(m is None or m == k for m, k in zip(mentioned, candidate, strict=True))
        for candidate in known
    )


def _issue(code, message, segment=None, severity="error"):
    issue = {"code": code, "severity": severity, "message": message}
    if segment:
        issue.update(part=segment["part"], text=segment["text"])
    return issue


def validate_draft(draft, context):
    """Return per-sentence annotations and blocking issues for one subject/body pair."""
    subject = str(draft.get("subject") or "")
    body = str(draft.get("body") or "")
    claims = [c for c in draft.get("claims") or [] if isinstance(c, dict)]
    supports = context["supports"]
    hook = context["hook"]
    prospect = context["prospect"]
    first_name = prospect["name"].split()[0] if prospect["name"] else ""
    names = " ".join([prospect["name"], prospect["company"], context["sender"]])
    issues, segments = [], []
    full_text = normal(subject + "\n" + body)

    for claim in claims:
        support_id, kind = claim.get("support_id", ""), claim.get("kind", "")
        if normal(claim.get("text", "")) not in full_text:
            issues.append(
                _issue(
                    "claim_text_missing",
                    "A cited claim no longer appears in the draft; its citation was dropped.",
                    severity="notice",
                )
            )
            continue
        if support_id not in supports:
            issues.append(
                _issue(
                    "unknown_support",
                    f"Cites '{support_id}', which is not saved evidence or an approved claim.",
                    {"part": "body", "text": claim.get("text", "")},
                    severity="notice",
                )
            )
        elif (kind == "offer") != (supports[support_id]["kind"] == "campaign"):
            issues.append(
                _issue(
                    "claim_kind",
                    "Facts must cite read sources; offer claims must cite approved "
                    "campaign claims.",
                    {"part": "body", "text": claim.get("text", "")},
                    severity="notice",
                )
            )
        if (
            kind == "inference"
            and not HEDGES.search(normal(claim.get("text", "")))
            and not SENDER_META.search(normal(claim.get("text", "")))
        ):
            issues.append(
                _issue(
                    "unhedged_inference",
                    "An inference must be worded cautiously (may, might, could).",
                    {"part": "body", "text": claim.get("text", "")},
                )
            )

    if not subject.strip():
        issues.append(_issue("subject", "Add a subject line."))
    elif len(subject) > 90 or re.match(r"\s*(re|fwd?)\s*:", subject, re.I):
        issues.append(
            _issue(
                "subject",
                "Keep the subject under 90 characters, without Re: or Fwd:.",
                {"part": "subject", "text": subject},
            )
        )

    questions = 0
    hook_used = False
    hook_terms = terms(hook["summary"])
    goal_supports = {k: v["text"] for k, v in supports.items() if v["kind"] == "campaign"}
    goal_text = normal(" ".join(goal_supports.values()))
    goal_vocabulary = allowed_vocabulary(goal_supports, sender=names) | _acronyms(
        " ".join(goal_supports.values())
    )
    for segment in _segments(subject, body):
        segment.update(support_ids=[], kinds=[], issues=[])
        text = normal(segment["text"])
        if segment["role"] == "greeting":
            greeted = re.sub(r"^(hi|hello|dear)\s+|[,!]$", "", text).strip()
            if greeted not in (normal(first_name), normal(prospect["name"])):
                segment["issues"].append(
                    _issue("greeting_name", "The greeting does not use the prospect's name.")
                )
            segments.append(segment)
            continue
        if segment["role"] == "signoff":
            segments.append(segment)
            continue
        if "?" in segment["text"]:
            questions += 1
            if text == normal(context["cta"]):
                segment["role"] = "cta"
                segments.append(segment)
                continue
            segment["issues"].append(
                _issue(
                    "cta",
                    "This question is not your closing question; keep it only if you want it.",
                    severity="notice",
                )
            )
        if segment["part"] == "body" and text in {
            normal(context["sender"]),
            normal(context["sender_name"]),
            normal(context["sender_company"]),
        }:
            segment["role"] = "signoff"
            segments.append(segment)
            continue

        # Bind: the writer's own citations first, then supports with real shared content.
        cited = {
            c.get("support_id"): c.get("kind")
            for c in claims
            if normal(c.get("text", "")) and normal(c.get("text", "")) in text
            if c.get("support_id") in supports
        }
        rated = next(
            (
                c
                for c in claims
                if normal(c.get("text", ""))
                and normal(c.get("text", "")) in text
                and c.get("relevance")
            ),
            None,
        )
        if rated:
            segment["relevance"] = rated["relevance"]
            segment["why"] = str(rated.get("why", ""))[:160]
        sentence_terms = terms(segment["text"])
        bound = dict(cited)
        if not bound:
            # Uncited text (reviewer edits, subjects) binds only to its closest support(s).
            overlaps = {
                support_id: len(sentence_terms & terms(support["text"]))
                for support_id, support in supports.items()
            }
            best = max(overlaps.values(), default=0)
            for support_id, overlap in overlaps.items():
                if overlap >= 2 and overlap == best:
                    kind = "offer" if supports[support_id]["kind"] == "campaign" else "fact"
                    bound[support_id] = kind
        if not bound and segment["part"] == "subject":
            # A subject usually sums up a cited sentence in other words ("appointed as Chief
            # Financial Officer" -> "CFO appointment"); it inherits that sentence's citation.
            echoed = max(
                (
                    c
                    for c in claims
                    if c.get("support_id") in supports
                    and len(sentence_terms & terms(c.get("text", ""))) >= 2
                ),
                key=lambda c: len(sentence_terms & terms(c.get("text", ""))),
                default=None,
            )
            if echoed:
                support_id = echoed["support_id"]
                bound[support_id] = (
                    "offer" if supports[support_id]["kind"] == "campaign" else "fact"
                )
        if segment["part"] == "subject" and bound:
            # The subject is coloured like the sentence whose source it shares.
            sibling = next(
                (c for c in claims if c.get("support_id") in bound and c.get("relevance")), None
            )
            if sibling:
                segment["relevance"] = sibling["relevance"]
                segment["why"] = "sums up: " + str(sibling.get("why", ""))[:150]
        segment["support_ids"] = list(bound)
        segment["kinds"] = sorted(
            set(bound.values())
            | ({"inference"} if HEDGES.search(text) and segment["part"] == "body" else set())
        )
        if (
            segment["part"] == "body"
            and hook["source_id"] in bound
            and (
                # A long passage only needs its key words echoed, not half of all of them.
                len(sentence_terms & hook_terms) >= min(4, max(2, len(hook_terms) // 3))
                # What the rep typed is too short to share three words; citing it is enough.
                or hook.get("basis") == "as_entered"
            )
        ):
            hook_used = True
        support_text = " ".join(supports[s]["text"] for s in bound)
        source_text = normal(
            " ".join(supports[s]["text"] for s in bound if supports[s]["kind"] == "source")
        )
        support_norm = normal(support_text)
        sender_meta = bool(SENDER_META.search(text))
        if not bound:
            if segment["part"] == "subject" and not specifics_in(segment["text"]):
                segment["issues"].append(
                    _issue(
                        "generic_subject",
                        "Generic subject: it names nothing specific from the evidence.",
                        severity="notice",
                    )
                )
            else:
                segment["issues"].append(
                    _issue(
                        "unsupported_sentence",
                        "Not tied to a source or your offer. Fine as a linking sentence; "
                        "remove it if it says more than you can stand behind.",
                        severity="notice",
                    )
                )

        vocabulary = allowed_vocabulary(
            {s: supports[s]["text"] for s in bound}, company=prospect["company"], sender=names
        ) | _acronyms(" ".join(supports[s]["text"] for s in bound) + " " + prospect["role"])
        # The rep's goal is approved as a whole: a name or term from any line of it ("HR",
        # the product name) may appear in any sentence, whichever line that sentence cites.
        vocabulary |= goal_vocabulary
        # Dates are checked as whole dates below, so their day numbers are not names.
        undated = segment["text"]
        for pattern in _DATE_PATTERNS[:3]:
            undated = re.sub(pattern.pattern, " ", undated, flags=re.IGNORECASE)
        missing = [
            word
            for word in specifics_in(undated)
            if word not in vocabulary
            and (word[:-1] if word.endswith("s") else word) not in vocabulary
        ]
        if missing:
            segment["issues"].append(
                _issue(
                    "unsupported_specific",
                    "Not in the cited support: " + ", ".join(missing) + ".",
                )
            )
        for category, pattern, message in _RISKY:
            if sender_meta and category == "causal":
                continue  # the cause of the sender's own email, not of anything about them
            severity = "notice" if category == "presupposition" else "error"
            for match in re.finditer(pattern, text):
                phrase = match.group(0)
                if not re.search(pattern, support_norm) or not re.search(
                    r"(?<![a-z])" + re.escape(phrase.rstrip("s")), support_norm
                ):
                    segment["issues"].append(
                        _issue(
                            "unsupported_" + category,
                            f"'{phrase}' {message}.",
                            severity=severity,
                        )
                    )
                    break
        if source_text:
            if _FUTURE.search(text) and not _FUTURE.search(source_text):
                segment["issues"].append(
                    _issue("tense", "Describes a plan or future step the source does not state.")
                )
            if (
                _PAST.search(text)
                and not _PAST.search(source_text)
                and (_ONGOING.search(source_text) or _FUTURE.search(source_text))
            ):
                segment["issues"].append(
                    _issue(
                        "tense",
                        "Presents an in-progress or planned development as already completed.",
                    )
                )
            if (
                _ONGOING.search(text)
                and not _ONGOING.search(source_text)
                and _PAST.search(source_text)
            ):
                segment["issues"].append(_issue("tense", "Presents a past event as still ongoing."))
        if _RELATIVE.search(text):
            segment["issues"].append(
                _issue("relative_time", "Use the source's date instead of a relative time.")
            )
        recent_word = _RECENT.search(text)
        if (
            recent_word
            and hook["temporal_label"] != "Recent event"
            and not re.search(rf"\b{recent_word.group(0)}\b", support_norm)
            # "new hire", "new customer": the goal's own wording, not a claim of recency.
            and not re.search(rf"\b{recent_word.group(0)}\b", goal_text)
        ):
            segment["issues"].append(
                _issue("recency", "The selected evidence is not a recent dated event.")
            )
        known = _dates(support_text)
        event_date = hook.get("event_date")
        if event_date:
            try:
                parsed = date.fromisoformat(event_date)
                known.append((parsed.year, parsed.month, parsed.day))
            except ValueError:
                pass
        for mentioned in _dates(segment["text"]):
            if not _date_supported(mentioned, known):
                segment["issues"].append(
                    _issue("unsupported_date", "This date does not match the cited evidence.")
                )
                break
        for issue in segment["issues"]:
            issue.update(part=segment["part"], text=segment["text"])
        segments.append(segment)

    for segment in segments:
        if segment["role"] in ("greeting", "signoff"):
            for issue in segment["issues"]:
                issue.update(part=segment["part"], text=segment["text"])
        issues.extend(segment["issues"])
    if not any(s["role"] == "cta" for s in segments):
        issues.append(
            _issue(
                "cta",
                "Your closing question is missing: " + context["cta"],
                severity="notice",
            )
        )
    elif questions > 1 or sum(s["role"] == "cta" for s in segments) > 1:
        issues.append(
            _issue("cta", "More than one question; one is usually enough.", severity="notice")
        )
    if not hook_used:
        issues.append(
            _issue(
                "hook_missing",
                "The email does not mention the hook, so it may read as generic.",
                severity="notice",
            )
        )
    words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", body))
    if not HARD_WORDS[0] <= words <= HARD_WORDS[1]:
        issues.append(
            _issue(
                "length",
                f"The body has {words} words; most replies come to emails of "
                f"{TARGET_WORDS[0]}–{TARGET_WORDS[1]}.",
                severity="notice",
            )
        )
    elif not TARGET_WORDS[0] <= words <= TARGET_WORDS[1]:
        issues.append(
            _issue(
                "length",
                f"The body has {words} words; aim for {TARGET_WORDS[0]}–{TARGET_WORDS[1]}.",
                severity="notice",
            )
        )
    errors = [i for i in issues if i["severity"] == "error"]
    for segment in segments:
        severities = {i["severity"] for i in segment["issues"]}
        segment["status"] = (
            "error" if "error" in severities else "notice" if severities else "supported"
        )
    return {
        "ok": not errors,
        "errors": errors,
        "notices": [i for i in issues if i["severity"] != "error"],
        "segments": segments,
        "word_count": words,
        "content_hash": content_hash(subject, body),
    }
