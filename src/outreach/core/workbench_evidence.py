"""Source-bound identity, date and hook decisions for the named-prospect workflow.

Model findings are candidates. A readable source and literal support are required;
the ranker never turns model confidence into evidence or buying intent.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from outreach.core.research import host, public_url


class IdentityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=200)
    role: str = Field(default="", max_length=120)
    domain: str = Field(min_length=3, max_length=253)
    source_id: str
    quote: str = Field(min_length=12, max_length=1800)
    status: Literal["current", "former", "uncertain"]
    effective_date: str | None = None


class _Salvageable(BaseModel):
    """Findings whose list items are judged one by one.

    Models sometimes return one malformed candidate (for example "Unknown" as a quote)
    among valid ones. Such an item could never pass the source checks anyway, so it is
    dropped and counted instead of failing the whole paid run.
    """

    model_config = ConfigDict(extra="forbid")
    _dropped: int = PrivateAttr(default=0)

    @classmethod
    def salvage(cls, content):
        data = json.loads(content)
        (field,) = cls.model_fields
        if not isinstance(data, dict) or set(data) != {field} or not isinstance(data[field], list):
            raise ValueError("The response does not have the expected shape.")
        item_type = cls.model_fields[field].annotation.__args__[0]
        limit = next(
            m.max_length for m in cls.model_fields[field].metadata if hasattr(m, "max_length")
        )
        kept = []
        for item in data[field]:
            try:
                kept.append(item_type.model_validate(item))
            except ValidationError:
                continue
        result = cls.model_validate({field: kept[:limit]})
        result._dropped = len(data[field]) - len(result.model_dump()[field])
        return result

    @property
    def dropped(self):
        return self._dropped


class IdentityFindings(_Salvageable):
    identity_candidates: list[IdentityCandidate] = Field(default_factory=list, max_length=8)


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    source_id: str
    title: str = Field(default="", max_length=300)
    quote: str = Field(min_length=20, max_length=1800)
    company: str
    person: str = ""
    kind: Literal["event", "evergreen"]
    event_date: str | None = None
    event_key: str = Field(default="", max_length=200)
    role_tags: list[str] = Field(default_factory=list, max_length=8)
    specificity: int = Field(default=1, ge=0, le=3)
    # Which kind of research found it: about the person, the company, growth signals
    # (hiring, funding, acquisitions), or the rep's own reasons to reach out.
    angle: Literal["person", "company", "growth", "goal", "other"] = "other"


class SignalFindings(_Salvageable):
    signals: list[Signal] = Field(default_factory=list, max_length=12)


def normal(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def stable_id(kind, value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return kind + "-" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def source_is_read(source):
    url = public_url(source.get("url", ""))
    return bool(
        url
        # "excerpt": text the search engine returned for the page, without opening it.
        and source.get("access_status") in ("read", "excerpt")
        and source.get("text", "").strip()
        and not (host(url) == "linkedin.com" or host(url).endswith(".linkedin.com"))
    )


def admit_sources(sources):
    """Keep access limitations visible without making previews/unsafe URLs proof."""
    admitted = []
    for source in sources:
        item = dict(source)
        if item.get("access_status") in ("read", "excerpt") and not source_is_read(item):
            item["access_status"] = (
                "blocked"
                if not public_url(item.get("url", ""))
                or "linkedin.com" in host(item.get("url", ""))
                else "empty"
            )
            item["limitation"] = "No permitted readable evidence was admitted from this source."
        if item.get("access_status") not in ("read", "excerpt"):
            item["passage"] = ""
            item["text"] = ""
        admitted.append(item)
    return admitted


def loose(value):
    """Matching form that ignores punctuation, quote styles and markdown spacing."""
    return " ".join(re.findall(r"[0-9a-z]+", normal(value)))


def supported_quote(source, quote):
    if not source_is_read(source):
        return False
    text = source.get("text", "")
    if normal(quote) in normal(text):
        return True
    words = loose(quote)
    # Punctuation-insensitive match still needs a real passage, not a few words.
    return len(words.split()) >= 4 and words in loose(text)


_DATELINE = re.compile(
    r"^.{0,90}?\((?:globe newswire|business wire|pr newswire|accesswire|newswire)\)\s*[-—–]+\s*",
    re.IGNORECASE,
)


def snap_quote(source, quote):
    """Return the source's own sentence when the model trimmed or tidied a passage.

    Models often drop a bracket or a ticker from a sentence. Leaving words out is
    allowed; adding them is not: at most one quoted word in twenty may be missing from
    the page sentence. That literal sentence is then used, so evidence is always the
    page's own words, never the model's.
    """
    if supported_quote(source, quote):
        return quote
    if not source_is_read(source):
        return None
    wanted = loose(quote).split()
    if len(wanted) < 6:
        return None
    best, best_score = None, 0.0
    for sentence in _sentences(source.get("text", "")):
        words = set(loose(sentence).split())
        score = sum(word in words for word in wanted) / len(wanted)
        if score > best_score:
            best, best_score = sentence, score
    if best and best_score >= 0.95 and len(loose(best).split()) <= 2 * len(wanted) + 12:
        # A wire dateline ("CITY, Date (GLOBE NEWSWIRE) --") is not part of the news.
        return _DATELINE.sub("", best) or best
    return None


def _company_key(value):
    words = re.findall(r"[a-z0-9]+", normal(value))
    return "".join(
        w
        for w in words
        if w not in {"private", "limited", "ltd", "pvt", "inc", "llc", "corporation", "corp", "plc"}
    )


def role_key(value):
    role = normal(value)
    aliases = {
        "cfo": "chief financial officer",
        "ceo": "chief executive officer",
        "coo": "chief operating officer",
        "cto": "chief technology officer",
    }
    return aliases.get(role, role)


_ROLE_SHORT = {
    "cfo": "chief financial officer",
    "ceo": "chief executive officer",
    "coo": "chief operating officer",
    "cto": "chief technology officer",
    "cio": "chief information officer",
    "ciso": "chief information security officer",
    "chro": "chief human resources officer",
    "cpo": "chief people officer",
    "cmo": "chief marketing officer",
    "cro": "chief revenue officer",
    "evp": "executive vice president",
    "svp": "senior vice president",
    "vp": "vice president",
}
_ROLE_FILLER = {"and", "the", "of", "global", "group"}
# Rank that pages put in front of the job itself.
_ROLE_RANK = re.compile(r"\b(?:senior executive|executive|senior|group)\s+vice\s+president\b")


def _role_words(value):
    text = normal(value).replace("&", " and ")
    words = []
    for word in re.findall(r"[a-z]+", text):
        words.extend(_ROLE_SHORT.get(word, word).split())
    ranked = " ".join(words)
    core = [w for w in re.findall(r"[a-z]+", _ROLE_RANK.sub(" ", ranked)) if w not in _ROLE_FILLER]
    # A title that is only a rank ("Senior Vice President") is compared as it stands.
    return set(core or [w for w in words if w not in _ROLE_FILLER])


def same_role(supplied, found):
    """The title the rep typed and the title on a page name the same job.

    Pages add rank ("Executive Vice President, Chief People Officer"), abbreviate ("CFO")
    or give the fuller form ("Chief People and Culture Officer"); a rep types the short
    one. One title's words inside the other's is the same job. Different jobs at the same
    company ("Chief Talent Officer") still differ.
    """
    a, b = _role_words(supplied), _role_words(found)
    return bool(a and b) and (a <= b or b <= a)


FILING_AND_WIRE_HOSTS = {
    "sec.gov",
    "globenewswire.com",
    "prnewswire.com",
    "businesswire.com",
    "accessnewswire.com",
    "newswire.ca",
    "nseindia.com",
    "bseindia.com",
    "londonstockexchange.com",
    "find-and-update.company-information.service.gov.uk",
}
REPORTING_HOSTS = {"reuters.com", "apnews.com", "ft.com", "bloomberg.com", "bbc.com", "bbc.co.uk"}


def _host_in(url, hosts):
    actual = host(url)
    return any(actual == h or actual.endswith("." + h) for h in hosts)


def _role_pattern(role):
    key = role_key(role)
    short = {
        v: k
        for k, v in {
            "cfo": "chief financial officer",
            "ceo": "chief executive officer",
            "coo": "chief operating officer",
            "cto": "chief technology officer",
        }.items()
    }.get(key)
    options = [re.escape(normal(role)), re.escape(key)] + ([short] if short else [])
    return "(?:" + "|".join(dict.fromkeys(o for o in options if o)) + ")"


def _name_refs(name, page_text):
    """Full name always; first or last name alone only when the page names the person."""
    full = normal(name)
    refs = [re.escape(full)]
    parts = full.split()
    if len(parts) >= 2 and full in normal(page_text):
        refs += [rf"(?:mr|ms|mrs|dr)\.?\s+{re.escape(parts[-1])}", re.escape(parts[0])]
        refs.append(re.escape(parts[-1]))
    return "(?:" + "|".join(refs) + ")"


_LINK = (
    r"\s*(?:,|—|–|:|\||-)?\s*(?:is|was|serves as|works as|currently serves as|became|"
    r"(?:has |had )?(?:been )?(?:appointed|named|promoted)(?: as| to)?|"
    r"(?:has |had )?joined(?:\s+\S+){0,4}?\s+as|as)?\s*(?:the\s+|our\s+|its\s+)?(?:new\s+)?"
)


def _relation_flexible(candidate, source):
    """The person is named, the role follows directly, and the employer is clear.

    The employer is clear when it is named in the passage, when the page is the
    company's own site, or when the page is a filing or wire release about it.
    """
    quote = normal(candidate["quote"])
    text = source.get("text", "")
    if not candidate.get("role"):
        return False
    pattern = rf"\b{_name_refs(candidate['name'], text)}{_LINK}{_role_pattern(candidate['role'])}\b"
    if not re.search(pattern, quote):
        return False
    company = normal(candidate["company"])
    if company and company in quote:
        return True
    domain = normal(candidate.get("domain", "")).removeprefix("www.")
    on_company_site = bool(domain) and (
        host(source.get("url", "")) == domain or host(source.get("url", "")).endswith("." + domain)
    )
    filing = _host_in(source.get("url", ""), FILING_AND_WIRE_HOSTS)
    return on_company_site or (filing and bool(company) and company in normal(text))


def _relation_supported(candidate):
    """Require one relation, not a page containing unrelated names and job words."""
    quote = normal(candidate["quote"])
    name, company, role = (re.escape(normal(candidate[k])) for k in ("name", "company", "role"))
    if role:
        # Written biographies and compact leadership-list entries are both supported.
        patterns = [
            rf"{name}\s*(?:,|—|–|:|is|serves as|works as|currently serves as)"
            rf"\s*(?:the\s+)?{role}\s+(?:at|of|for|with)\s+{company}",
            rf"{name}\s*[,—–:|\-]?\s*{role}\s*(?:at|of|for|[,—–:|\-])\s*{company}",
            rf"{company}\s*[,—–:|\-]\s*{name}\s*[,—–:|\-]\s*{role}",
        ]
    else:
        patterns = [rf"{name}\s+(?:works at|works for|is at|serves at)\s+{company}"]
    return any(re.search(pattern, quote) for pattern in patterns)


_PAST_ROLE = re.compile(
    r"\b(served|previously|formerly|earlier in (?:his|her|their) career|"
    r"(?:prior to|before) (?:joining|that|this)|most recently)\b"
)


def _obvious_domain(company, domain):
    """The web address plainly belongs to the company named.

    True when the company's name is in the address ("cedarworks.com"), when the address
    is the start of the name ("yum.com" for Yum! Brands, "levistrauss.com" for Levi
    Strauss & Co.) or its initials ("ge.com").
    """
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", normal(company))
        if w not in {"private", "limited", "ltd", "pvt", "inc", "llc", "corporation", "corp", "plc"}
    ]
    key = "".join(words)
    labels = normal(domain).removeprefix("www.").split(".")
    # The name part of the address: "yum" in investors.yum.com, "bbc" in bbc.co.uk.
    two_part_ending = len(labels) > 2 and labels[-2] in {"co", "com", "org", "ac"}
    label = labels[-3] if two_part_ending else labels[-2] if len(labels) > 1 else labels[0]
    label = re.sub(r"[^a-z0-9]", "", label)
    if not key or not label:
        return False
    return (
        key in re.sub(r"[^a-z0-9]", "", normal(domain))
        or (len(label) >= 3 and key.startswith(label))
        or (len(words) > 1 and len(label) >= 2 and label == "".join(w[0] for w in words))
    )


def _domain_supported(prospect, source, candidate):
    domain = normal(candidate["domain"]).removeprefix("www.")
    if not public_url("https://" + domain + "/"):
        return False
    source_host = host(source.get("url", ""))
    source_is_company = source_host == domain or source_host.endswith("." + domain)
    supplied_domain = host(prospect.get("website", "")) or (
        normal(prospect["company"]) if "." in prospect["company"] else ""
    )
    obvious_domain = _obvious_domain(candidate["company"], domain)
    if source_is_company:
        return supplied_domain == domain if supplied_domain else obvious_domain
    trusted = _host_in(source.get("url", ""), REPORTING_HOSTS | FILING_AND_WIRE_HOSTS)
    return trusted and (
        supplied_domain == domain or domain in normal(source.get("text", "")) or obvious_domain
    )


def _weak_domain_supported(prospect, source, candidate):
    """Any other readable page: allowed only for a human to confirm, never automatically."""
    domain = normal(candidate["domain"]).removeprefix("www.")
    if not public_url("https://" + domain + "/"):
        return False
    supplied = host(prospect.get("website", ""))
    if supplied:
        return supplied == domain
    return _obvious_domain(candidate["company"], domain)


_TITLE = re.compile(
    r"\b(?:chief [a-z]+ officer|c[efot]o|(?:senior |executive )?vice president(?: of [a-z ]+)?|"
    r"(?:group |global )?(?:finance|financial) (?:director|controller)|financial controller|"
    r"controller|treasurer|head of [a-z&]+(?: [a-z&]+)?|(?:managing )?director(?: of [a-z]+)?|"
    r"president|founder|co-founder|partner)\b"
)


def _sentences(text):
    for line in str(text or "").splitlines():
        line = line.strip(" #*-|>\t")
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
            if 20 <= len(part) <= 600:
                yield part


def _company_domain(prospect, sources):
    """The supplied website, else a read page's host that plainly carries the company name."""
    supplied = host(prospect.get("website", ""))
    if supplied:
        return supplied
    words = re.findall(r"[a-z0-9]+", normal(prospect.get("company", "")))
    key = "".join(
        w
        for w in words
        if w not in {"private", "limited", "ltd", "pvt", "inc", "llc", "corporation"}
    )
    for source in sources:
        site = host(source.get("url", "")).removeprefix("www.")
        if (
            key
            and source.get("access_status") in ("read", "excerpt")
            and key in re.sub(r"[^a-z0-9]", "", site)
        ):
            return site
    return ""


def find_identity_candidates(prospect, sources):
    """Read pages directly for a sentence naming the person with a role.

    This does not trust the research model to pick the best quote; every candidate is
    still checked by the same rules as model candidates.
    """
    name = normal(prospect.get("name", ""))
    company = prospect.get("company", "")
    parts = name.split()
    if len(parts) < 2:
        return []
    found = []
    company_domain = _company_domain(prospect, sources)
    for source in admit_sources(sources):
        text = source.get("text", "")
        if source.get("access_status") not in ("read", "excerpt") or name not in normal(text):
            continue
        domain = company_domain or host(source.get("url", ""))
        for sentence in _sentences(text):
            low = normal(sentence)
            if not any(p in low.split() or p in re.findall(r"[a-z]+", low) for p in parts):
                continue
            if prospect.get("role"):
                found_role = re.search(rf"\b{_role_pattern(prospect['role'])}\b", low)
                role = prospect["role"] if found_role else ""
            else:
                match = _TITLE.search(low)
                role = match.group(0) if match else ""
            if not role:
                continue
            candidate = {
                "name": prospect["name"],
                "company": company,
                "role": role,
                "domain": domain,
                "source_id": source["id"],
                "quote": sentence,
                "status": "current",
            }
            if _relation_flexible(candidate, source) and not re.search(
                r"\b(formerly|former|previously|left|departed|used to|no longer)\b", low
            ):
                found.append(candidate)
                break
        else:
            # A leadership or bio page: the name on its own line, the title on the next.
            lines = [line.strip(" #*-|>\t") for line in text.splitlines() if line.strip()]
            for line, title in zip(lines, lines[1:], strict=False):
                if normal(line) != name or not 5 <= len(title) <= 160:
                    continue
                titled = (
                    same_role(prospect["role"], title)
                    if prospect.get("role")
                    else bool(_TITLE.search(normal(title)))
                )
                candidate = {
                    "name": prospect["name"],
                    "company": company,
                    "role": title,
                    "domain": domain,
                    "source_id": source["id"],
                    "quote": f"{line}, {title}",
                    "status": "current",
                }
                if titled and _relation_flexible(candidate, source):
                    found.append(candidate)
                    break
    return found


def assess_identity(prospect, sources, candidates, confirmed_id=None):
    by_id = {s["id"]: s for s in admit_sources(sources) if s.get("id")}
    checked = []
    seen_quotes = set()

    # The model's candidates are judged first. The page scan then covers every page that
    # gave no supported identity: pages the model did not cite, and pages where its quote
    # did not hold up (live case: it quoted only a title from the company's own bio page).
    def judge(raw):
        key = (normal(raw.get("quote", "")), raw.get("source_id"))
        if key in seen_quotes:
            return
        seen_quotes.add(key)
        try:
            item = IdentityCandidate.model_validate(raw).model_dump()
        except ValidationError:
            return
        source = by_id.get(item["source_id"], {})
        item["quote"] = snap_quote(source, item["quote"]) or item["quote"]
        item["id"] = stable_id("identity", {k: v for k, v in item.items() if k != "id"})
        reason = ""
        weak = False
        related = _relation_supported(item) or _relation_flexible(item, source)
        evidenced = supported_quote(source, item["quote"]) and related
        if not supported_quote(source, item["quote"]):
            reason = "Identity has no literal support in a permitted page read."
        elif not related:
            reason = "The passage does not bind this name, role and employer together."
        elif not _domain_supported(prospect, source, item):
            if _weak_domain_supported(prospect, source, item):
                weak = True
            else:
                reason = "The source does not establish the claimed company domain."
                evidenced = False
        elif item["status"] != "current" or re.search(
            r"\b(formerly|former|previously|left|departed|used to|no longer)\b",
            normal(item["quote"]),
        ):
            reason = "Former or uncertain employment does not establish current identity."
        matches_company = normal(prospect["company"]) in {
            normal(item["company"]),
            normal(item["domain"]),
        }
        matches_role = not prospect.get("role") or same_role(prospect["role"], item["role"])
        matches_website = not prospect.get("website") or host(prospect["website"]) == normal(
            item["domain"]
        )
        matches_person = normal(item["name"]) == normal(prospect["name"])
        item["supported"] = not reason
        item["evidenced"] = evidenced
        item["weak"] = weak
        item["selectable"] = bool(
            not reason and matches_person and matches_company and matches_role and matches_website
        )
        item["reason"] = reason or (
            "Found on a third-party page, not the company's own site or a filing. "
            "Confirm this is the right person."
            if item["selectable"] and weak
            else "Matches the supplied person and company."
            if item["selectable"]
            else "This identity differs from the supplied company, role or website."
        )
        checked.append(item)

    for raw in list(candidates):
        judge(raw)
    held_up = {c["source_id"] for c in checked if c["supported"]}
    for raw in find_identity_candidates(prospect, sources):
        if raw["source_id"] not in held_up:
            judge(raw)
    supported = [
        c for c in checked if c["supported"] and normal(c["name"]) == normal(prospect["name"])
    ]
    eligible = [c for c in supported if c["selectable"]]
    chosen = next((c for c in eligible if c["id"] == confirmed_id), None) if confirmed_id else None
    distinct = {(normal(c["company"]), role_key(c["role"]), normal(c["domain"])) for c in supported}
    strong = [c for c in eligible if not c["weak"]]
    # Several sentences about the same job are one identity, not a conflict.
    same_job = len({(normal(c["company"]), normal(c["domain"])) for c in supported}) == 1
    if chosen is None and not confirmed_id and strong and (len(distinct) == 1 or same_job):
        chosen = strong[0]
    if chosen:
        return {
            **{k: chosen[k] for k in ("name", "company", "role", "domain")},
            "status": "matched",
            "summary": "The supplied person and company match a read source.",
            "candidates": checked,
            "selected": chosen,
        }
    conflict = bool(supported) or any(
        c["evidenced"] and normal(c["name"]) == normal(prospect["name"]) for c in checked
    )
    return {
        "status": "conflict" if conflict else "unconfirmed",
        "summary": "Confirm which supported current identity is intended."
        if conflict
        else "No supported identity was established.",
        "candidates": checked,
        "selected": None,
    }


def _date(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


_ANNOUNCES = (
    r"\b(?:announce[sd]?|announcing|has been (?:appointed|named|promoted)|appoints|"
    r"welcomes|has joined|(?:names|promotes|hires)\s+(?:\S+\s+){1,4}?(?:as|to)\b)"
)


def _date_supported(value, source, quote, own_site=False):
    parsed = _date(value)
    if not parsed:
        return False
    if _date_in_quote(value, quote):
        return True  # the quoted words themselves state this date
    text = str(source.get("text", ""))
    position = normal(text).find(normal(quote)[:60])
    if position >= 0 and _date_in_quote(value, normal(text)[max(0, position - 300) : position]):
        return True  # a dateline just before the quote ("Oct. 19, 2026 (GLOBE NEWSWIRE) --")
    if re.search(r"\btoday\b", normal(quote)) and _date(source.get("publication_date")) == parsed:
        return True  # "today announced" on a page published that same day
    years = set(re.findall(r"(?<![$\d])\b(?:19|20)\d{2}\b", quote))
    if years and str(parsed.year) not in years:
        return False
    explicit = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", quote)
    if explicit and parsed.isoformat() not in explicit:
        return False
    if (
        _date(source.get("publication_date")) == parsed
        and re.search(_ANNOUNCES, normal(quote))
        and (
            own_site
            or source.get("quality") == "official"
            or _host_in(source.get("url", ""), FILING_AND_WIRE_HOSTS)
        )
    ):
        # The company's own announcement, or a filing or wire copy of it: the day it was
        # published is the day it was announced. News sites and aggregators re-date old
        # stories, so they do not get this benefit.
        return True
    dated_event = re.findall(
        r"(?:originally|event|announced|launched)\b.{0,40}?(\d{4}-\d{2}-\d{2})",
        normal(source.get("text", "")),
    )
    if dated_event and parsed.isoformat() not in dated_event:
        return False
    recorded_date = _date(source.get("event_date"))
    if recorded_date:
        return recorded_date == parsed
    variations = [
        parsed.isoformat(),
        parsed.strftime("%B %d, %Y"),
        parsed.strftime("%d %B %Y"),
        parsed.strftime("%b %d, %Y"),
        parsed.strftime("%d %b %Y"),
    ]
    passage = normal(quote)
    return any(normal(v).replace(" 0", " ") in passage.replace(" 0", " ") for v in variations)


def _terms(value):
    ignored = {
        "about",
        "after",
        "their",
        "which",
        "through",
        "would",
        "teams",
        "company",
        "finance",
        "director",
    }
    return {
        word.rstrip("s") for word in re.findall(r"[a-z]{4,}", normal(value)) if word not in ignored
    }


_MONTH_WORD = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_NOT_QUANTITIES = [
    r"\b\d{4}-\d{2}-\d{2}\b",  # ISO dates
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b",  # 4.30.2026
    rf"\b{_MONTH_WORD}\s+\d{{1,2}}(?:st|nd|rd|th)?\b,?",  # Oct. 19
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_WORD}",  # 19 October
    r"\bq[1-4]\b",
    r"\b(?:section|rule|item|form|act of|exhibit|no\.?|number)\s+[\d.()a-z-]+",  # legal refs
    r"\b(?:19|20)\d{2}\b",  # years
]


def _numeric_detail(quote):
    """Amounts and counts a reader would compare; dates, years and legal references are
    not quantities (an SEC header once made two accounts of one appointment "conflict")."""
    text = normal(quote)
    for pattern in _NOT_QUANTITIES:
        text = re.sub(pattern, " ", text)
    return tuple(
        sorted(
            m.strip(" ,.")
            for m in re.findall(
                r"(?:[$£€]\s*)?\d[\d,.]*(?:\s*(?:million|billion|thousand|%))?", text
            )
        )
    )


def _date_in_quote(value, quote):
    """True when the quote itself states this date (not only the page around it)."""
    parsed = _date(value)
    if not parsed:
        return False
    low = normal(quote)
    month, short = parsed.strftime("%B").lower(), parsed.strftime("%b").lower()
    day, year = parsed.day, parsed.year
    patterns = [
        parsed.isoformat(),
        rf"\b(?:{month}|{short}\.?|sept\.?)\s+{day}(?:st|nd|rd|th)?,?\s+{year}\b",
        rf"\b{day}(?:st|nd|rd|th)?\s+(?:{month}|{short}\.?)\s+{year}\b",
    ]
    return any(re.search(p, low) for p in patterns)


def _event_status(quote):
    return bool(
        re.search(r"\b(cancelled|canceled|denied|withdrawn|postponed|abandoned)\b", normal(quote))
    )


def _role_terms(value):
    words = set(re.findall(r"[a-z]{3,}", role_key(value)))
    words -= {"chief", "officer", "director", "leader", "leaders", "responsible", "for"}
    if words & {"financial", "finance", "accounting", "accounts"}:
        words.add("finance")
    return words


def event_family(value):
    """Normalize date/amount decorations, not the meaning of unrelated events."""
    text = re.sub(r"\d[\d,.]*(?:million|billion|thousand|bn|m|k)?", " ", normal(value))
    tokens = re.findall(r"[a-z]+", text)
    decorations = {
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
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "million",
        "billion",
        "thousand",
    }
    return " ".join(token for token in tokens if token not in decorations)


_DUTY = re.compile(
    r"\b(oversee|oversees|overseeing|responsible for|leads|leading|manages|managing|heads|"
    r"runs|in charge of|focus(?:es)? on|owns)\b"
)
_EVENTISH = re.compile(
    r"\b(raised|funding round|appointed|launched|acquired|announced|introduced|joined|"
    r"implemented|recently|last week|last month|no longer|formerly|previously)\b"
)


# Reasons that make a signal a poor first choice but still true, sourced and about them.
_SOFT_REASONS = (
    "no specific connection",
    "older than the recent-event window",
    "Event date is unknown",
    "lacks a stable topic identifier",
    "conflict about this event's date.",
)


def _soft_signal_hook(parsed, by_id, identity, offer_terms, today):
    """Best signal held back only for a soft reason, used without any recency claim."""
    pool = []
    for item in parsed:
        if item["eligible"] or not any(r in item["reason"] for r in _SOFT_REASONS):
            continue
        # Off-topic company news (a cafeteria opening) is worse than their own role.
        if not item.get("relevant"):
            continue
        event_date = _date(item["event_date"])
        if event_date and (event_date > today or (today - event_date).days > 3 * 365):
            continue
        pool.append(item)
    if not pool:
        return None
    pool.sort(
        key=lambda i: (
            bool(i["person"]),
            sum(i["score"].values()),
            i["score"]["quality"],
            i["id"],
        ),
        reverse=True,
    )
    chosen = pool[0]
    by_id[chosen["source_id"]]["passage"] = chosen["quote"]
    matches = sorted(_terms(chosen["quote"]) & offer_terms)
    return {
        "title": "Something sourced about them",
        "summary": chosen["quote"],
        "source_ids": [chosen["source_id"]],
        "signal_id": chosen["id"],
        "temporal_label": "Evergreen evidence",
        "strength": "weak",
        "event_date": None,
        "score": chosen["score"],
        "selection_reasons": [
            "Held back as a strong hook because: " + chosen["reason"],
            "Used without calling it recent; the email may not say when it happened.",
            "Offer connection: "
            + (", ".join(matches) if matches else "none named; the email bridges to your offer")
            + ".",
            "Confirmed role: " + (identity.get("role") or "Unknown") + ".",
        ],
    }


def _role_hook(identity, offer_terms):
    """The last fallback: the sentence that confirmed who they are and what they do."""
    selected = identity.get("selected") or {}

    def readable(candidate):
        # Prefer a real sentence that says what they do over a heading or a bare title.
        low = normal(candidate.get("quote", ""))
        words = len(low.split())
        return (
            2 * bool(_DUTY.search(low))
            + bool(re.search(r"\b(is|are|has|have|was|serves|joined|leads)\b", low))
            + (8 <= words <= 45)
            + (candidate.get("id") == selected.get("id")) * 0.5
        )

    same_person = [
        c
        for c in identity.get("candidates", [])
        if c.get("supported") and c.get("selectable") and not c.get("weak")
    ]
    selected = max(same_person, key=readable, default=selected)
    quote = selected.get("quote", "")
    low = normal(quote)
    if not selected.get("source_id") or len(low.split()) < 5:
        return None
    matches = sorted(_terms(quote) & offer_terms)
    return {
        "title": "Their current role",
        "summary": quote,
        "source_ids": [selected["source_id"]],
        "signal_id": None,
        "temporal_label": "Evergreen evidence",
        "strength": "weak",
        "event_date": None,
        "score": {
            "offer_fit": min(len(matches), 4),
            "role_fit": 1,
            "specificity": 1,
            "freshness": 0,
            "quality": 0,
        },
        "selection_reasons": [
            "No development about them passed the checks.",
            "Fallback: the sentence that confirmed who they are and their role.",
            "Offer connection: "
            + (
                ", ".join(matches)
                if matches
                else "none named; the email bridges from their role to your offer."
            )
            + ".",
            "Confirmed role: " + (identity.get("role") or "Unknown") + ".",
        ],
    }


_ABOUT = re.compile(
    r"\b(is|are|provides?|offers?|builds?|makes?|helps?|serves?|operates?|develops?|"
    r"delivers?|speciali[sz]es?|manufactures?|supplies|designs?)\b"
)


def _company_fact_hook(prospect, sources):
    """A small sourced thing: how the company describes itself on its own site."""
    domain = _company_domain(prospect, sources)
    company = normal(prospect["company"])
    if not domain or not company:
        return None
    for source in admit_sources(sources):
        site = host(source.get("url", "")).removeprefix("www.")
        if source.get("access_status") != "read" or not (
            site == domain or site.endswith("." + domain)
        ):
            continue
        for sentence in _sentences(source.get("text", "")):
            low = normal(sentence)
            words = low.split()
            if (
                company in low
                and 8 <= len(words) <= 45
                and _ABOUT.search(low)
                and not _EVENTISH.search(low)
                and "cookie" not in low
                and "©" not in sentence
            ):
                return {
                    "title": "About their company",
                    "summary": sentence,
                    "source_ids": [source["id"]],
                    "signal_id": None,
                    "temporal_label": "Evergreen evidence",
                    "strength": "weak",
                    "basis": "company_page",
                    "event_date": None,
                    "score": {},
                    "selection_reasons": [
                        "No news and no confirmed detail about the person was found.",
                        "Fallback: how the company describes itself on its own website.",
                    ],
                }
    return None


def _as_entered_hook(prospect):
    role, company = prospect.get("role", ""), prospect["company"]
    summary = (
        f"{prospect['name']} is {role} at {company}"
        if role
        else f"{prospect['name']} works at {company}"
    )
    return {
        "title": "Only what you entered",
        "summary": summary,
        "source_ids": ["as-entered"],
        "signal_id": None,
        "temporal_label": "Not verified",
        "strength": "none",
        "basis": "as_entered",
        "event_date": None,
        "score": {},
        "selection_reasons": [
            "Nothing usable could be read about this person or company.",
            "The email uses only the name, role and company you typed. Nothing was looked up "
            "to support it, so it is not personalised.",
        ],
    }


def _judgement(hook, identity, sources, offer_terms, prospect):
    """Plain-language verdict shown to the reviewer: what the hook has and what it lacks."""
    source = next((s for s in sources if s.get("id") in hook.get("source_ids", [])), {})
    basis = hook.get("basis", "read_source")
    has, lacks = [], []
    if basis == "as_entered":
        lacks += [
            "No public page could be read to support anything",
            "Not personalised: it uses only what you typed",
        ]
    else:
        site = host(source.get("url", ""))
        domain = normal(identity.get("domain") or _company_domain(prospect, sources))
        own = bool(domain) and site.removeprefix("www.") == domain.removeprefix("www.")
        if own or source.get("quality") == "official":
            has.append("Comes from the company's own website")
        elif _host_in(source.get("url", ""), FILING_AND_WIRE_HOSTS):
            has.append("Comes from an official filing or press release")
        elif _host_in(source.get("url", ""), REPORTING_HOSTS):
            has.append("Comes from a major news outlet")
        else:
            has.append("Comes from a public page that was read in full")
            lacks.append("The page is not the company's own site or an official filing")
        if source.get("access_status") == "excerpt":
            has.append("The quoted words appear in the search result for that page")
            lacks.append("Seen in a search excerpt; the full page was not opened")
        else:
            has.append("The quoted words appear on that page")
    if identity.get("status") == "matched":
        has.append("The person and their role were confirmed on a readable page")
    else:
        lacks.append("The person could not be confirmed at this company")
    if hook.get("temporal_label") == "Recent event":
        has.append("A dated event from the last six months")
    elif basis != "as_entered":
        lacks.append('No recent dated news, so the email may not say "recently"')
    if basis not in ("as_entered", "company_page") and offer_terms:
        if _terms(hook.get("summary", "")) & offer_terms:
            has.append("Mentions something close to what you offer")
        else:
            lacks.append("No direct link to what you offer; the email has to bridge to it")
    strength = hook.get("strength", "moderate")
    verdict = {
        "strong": "Strong: recent, dated and sourced.",
        "moderate": "Good: sourced and relevant, but not recent news.",
        "weak": "Weaker: true and sourced, but not a strong reason to write now.",
        "none": "Not personalised: nothing could be verified.",
    }[strength]
    return {"verdict": verdict, "has": has, "lacks": lacks}


def select_hook(prospect, campaign, sources, signals, identity, *, now=None, recent_days=180):
    """Choose the best available hook and say honestly how strong it is.

    Ladder: checked news → softer sourced detail → their confirmed role → company news →
    how the company describes itself → only what the rep typed. Only an unresolved
    "which person?" question stops without a hook.
    """
    result = _select_checked_hook(
        prospect, campaign, sources, signals, identity, now=now, recent_days=recent_days
    )
    if result["outcome"] == "needs_more_evidence":
        fact = _company_fact_hook(prospect, sources)
        hook = fact or _as_entered_hook(prospect)
        result.update(
            outcome="research_ready",
            hook=hook,
            reason=(
                "No news and nothing about the person passed the checks, so the email "
                "opens with how the company describes itself. This is a weaker hook."
                if fact
                else "Nothing usable could be read, so the email uses only what you typed. "
                "It is not personalised; add a public page about them for a real hook."
            ),
            next_action="Research saved. No outreach draft has been created or approved.",
        )
    if result.get("hook"):
        hook = result["hook"]
        hook.setdefault("basis", "read_source")
        # "CITY, Date (GLOBE NEWSWIRE) --" is not part of the news; the date stays in event_date.
        hook["summary"] = _DATELINE.sub("", hook.get("summary", "")) or hook.get("summary", "")
        offer_terms = _terms(
            " ".join(campaign.get("supported_capabilities", []))
            + " "
            + campaign.get("offer", "")
            + " "
            + campaign.get("looking_for", "")
        )
        hook["judgement"] = _judgement(
            hook, result["identity"], result["sources"], offer_terms, prospect
        )
    return result


def _select_checked_hook(
    prospect, campaign, sources, signals, identity, *, now=None, recent_days=180
):
    reference = now or datetime.now(UTC)
    if isinstance(reference, str):
        reference = datetime.fromisoformat(reference.replace("Z", "+00:00"))
    today = reference.date() if isinstance(reference, datetime) else reference
    displayed = admit_sources(sources)
    by_id = {s["id"]: s for s in displayed if s.get("id")}
    base = {
        "identity": identity,
        "sources": displayed,
        "hook": None,
        "candidate_signals": [],
        "rejected_signals": [],
        "context_signals": [],
        "limitations": [],
    }
    company_only = identity["status"] == "unconfirmed" and bool(signals)
    if company_only:
        # The person is as entered but not confirmed: only company news may be used.
        identity = {
            **identity,
            "name": prospect["name"],
            "company": prospect["company"],
            "role": "",
            "domain": _company_domain(prospect, sources),
        }
    if identity["status"] != "matched" and not company_only:
        conflict = identity["status"] == "conflict"
        return {
            **base,
            "outcome": "needs_identity_confirmation" if conflict else "needs_more_evidence",
            "reason": identity["summary"],
            "next_action": "Confirm a supported prospect, or correct the company and start again."
            if conflict
            else "Add an accessible official source or try another source.",
        }
    selected_identity = identity.get("selected") or {}
    if selected_identity.get("source_id") in by_id:
        by_id[selected_identity["source_id"]]["passage"] = selected_identity["quote"]
    offer_terms = _terms(
        " ".join(campaign.get("supported_capabilities", []))
        + " "
        + campaign.get("offer", "")
        + " "
        + campaign.get("looking_for", "")
    )
    parsed = []
    for raw in signals:
        try:
            item = Signal.model_validate(raw).model_dump()
        except ValidationError:
            base["rejected_signals"].append({"reason": "Signal data was incomplete or invalid."})
            continue
        source = by_id.get(item["source_id"], {})
        item["quote"] = snap_quote(source, item["quote"]) or item["quote"]
        item["id"] = stable_id("signal", {k: v for k, v in item.items() if k != "id"})
        reason = ""
        quote_low = normal(item["quote"])
        name_parts = normal(identity["name"]).split()
        person_named = normal(identity["name"]) in quote_low or (
            len(name_parts) > 1
            and normal(identity["name"]) in normal(source.get("text", ""))
            and re.search(
                rf"\b(?:{re.escape(name_parts[-1])}|{re.escape(name_parts[0])})\b", quote_low
            )
            is not None
        )
        # "He served nine years as CFO of…" on a page about them is about them too.
        if (
            not person_named
            and item["person"]
            and normal(item["person"]) == normal(identity["name"])
            and normal(identity["name"]) in normal(source.get("text", ""))
            # "He…", "Previously, he…", "Most recently, he…": a short lead-in, then the pronoun.
            # Also "A champion of emerging technology, she has…": an opening phrase, a
            # comma, then the pronoun.
            and re.match(
                r"\s*(?:(?:[a-z]+(?:\s+[a-z]+)?,?\s+)|(?:[^.;:]{0,70},\s+))?(?:he|she|they)\b",
                quote_low,
            )
        ):
            person_named = True
        same_company = _company_key(item["company"]) == _company_key(identity["company"])
        source_about_company = (
            identity.get("domain")
            and (
                host(source.get("url", "")) == normal(identity["domain"]).removeprefix("www.")
                or host(source.get("url", "")).endswith(
                    "." + normal(identity["domain"]).removeprefix("www.")
                )
            )
        ) or (
            _host_in(source.get("url", ""), FILING_AND_WIRE_HOSTS)
            and _company_key(identity["company"]) in loose(source.get("text", "")).replace(" ", "")
        )
        attributed = same_company and (
            _company_key(identity["company"]) in loose(item["quote"]).replace(" ", "")
            or person_named
            or source_about_company
        )
        if not supported_quote(source, item["quote"]):
            reason = "Signal lacks literal support in a permitted page read."
        elif not attributed:
            reason = "The signal is not attributed to the confirmed company."
        elif item["person"] and (
            normal(item["person"]) != normal(identity["name"]) or not person_named
        ):
            reason = "The signal is attributed to another person."
        event_date = _date(item["event_date"])
        if not reason and item["kind"] == "event":
            if not event_family(item["event_key"]):
                reason = "The event lacks a stable topic identifier for contradiction checks."
            elif not _date_supported(
                item["event_date"], source, item["quote"], own_site=bool(source_about_company)
            ):
                reason = "Event date is unknown or unsupported; publication date is not event date."
            elif event_date > today:
                reason = "The event date is in the future."
            elif (today - event_date).days > recent_days:
                reason = (
                    "The event is older than the recent-event window, even if recently republished."
                )
        if (
            not reason
            and item["kind"] == "evergreen"
            and re.search(
                r"\b(raised|funding round|appointed|launched|acquired|announced|introduced|"
                r"implemented|recently|last week|last month|was|were|no longer)\b",
                normal(item["quote"]),
            )
        ):
            reason = "An event or recency claim cannot be relabelled as evergreen evidence."
        fit = len(_terms(item["quote"]) & offer_terms)
        generic = {
            "review",
            "information",
            "against",
            "supplied",
            "record",
            "show",
            "route",
            "routing",
            "them",
            "human",
            "resolution",
            "support",
            "business",
            "operation",
        }
        meaningful_fit = (_terms(item["quote"]) & offer_terms) - generic
        role_fit = bool(
            _role_terms(" ".join(item["role_tags"])) & _role_terms(identity.get("role", ""))
        )
        # News about the prospect themselves (an appointment, an interview) is relevant
        # on its own; company news still has to connect to the offer.
        about_person = bool(item["person"]) and normal(item["person"]) == normal(identity["name"])
        item["relevant"] = bool(meaningful_fit or about_person)
        # Without a goal there is no offer to connect to; any sourced news can be the hook.
        if not reason and not meaningful_fit and not about_person and offer_terms:
            reason = "The read passage has no specific connection to the approved offer."
        item.update(
            {
                "eligible": not reason,
                "reason": reason,
                "score": {
                    "offer_fit": min(fit, 4),
                    "role_fit": int(role_fit),
                    "specificity": item["specificity"],
                    "freshness": 2 if item["kind"] == "event" else 0,
                    "quality": 2
                    if source.get("quality") == "official"
                    else 1
                    if source.get("quality") == "reporting"
                    else 0,
                },
            }
        )
        parsed.append(item)
    # Conflicting details of the same event cannot be resolved by ranking one higher.
    groups = {}
    ranked = sorted(
        parsed,
        key=lambda item: (sum(item["score"].values()), item["score"]["quality"], item["id"]),
        reverse=True,
    )
    for item in ranked:
        source = by_id.get(item["source_id"], {})
        if item["event_key"] and supported_quote(source, item["quote"]):
            family = (
                event_family(item["event_key"])
                if item["kind"] == "event"
                else normal(item["event_key"])
            )
            # Accounts about different named people are different events, even when the
            # model files them under one label (a new CFO and a departing officer).
            person = normal(item.get("person") or "")
            groups.setdefault((normal(item["company"]), family, person), []).append(item)
    for group in groups.values():
        dates = {s["event_date"] for s in group if s["event_date"]}
        stated = {
            s["event_date"]
            for s in group
            if s["event_date"] and _date_in_quote(s["event_date"], s["quote"])
        }
        if len(dates) > 1 and len(stated) == 1:
            # One account states the date in its own words (a dated press release); the
            # others carry a date the model took from elsewhere, often the announcement
            # rather than the start date. The stated one is kept; the rest step aside.
            (kept,) = stated
            for item in group:
                if item["event_date"] != kept and not _date_in_quote(
                    item["event_date"], item["quote"]
                ):
                    item.update(
                        eligible=False,
                        reason="Another account of this event states its date directly; "
                        "that one is used.",
                    )
            group = [item for item in group if item["eligible"] or item["event_date"] == kept]
            dates = {kept}
        quantities = {_numeric_detail(s["quote"]) for s in group if _numeric_detail(s["quote"])}
        statuses = {_event_status(s["quote"]) for s in group}
        if len(quantities) > 1 or len(statuses) > 1:
            for item in group:
                item.update(
                    eligible=False,
                    reason="Read sources conflict about this event's date, quantity or status.",
                )
        elif len(dates) > 1:
            # Only the date is disputed: never claim a date, but the event itself may be used.
            for item in group:
                item.update(
                    eligible=False,
                    reason="Read sources conflict about this event's date.",
                )
    eligible, seen = [], set()
    for item in ranked:
        if not item["eligible"]:
            base["rejected_signals"].append(item)
            continue
        signature = (
            (event_family(item["event_key"]), item["event_date"], _numeric_detail(item["quote"]))
            if item["kind"] == "event" and item["event_key"]
            else (normal(item["event_key"]), normal(item["quote"]))
        )
        if signature in seen:
            base["rejected_signals"].append(
                {
                    **item,
                    "eligible": False,
                    "reason": "Duplicate or syndicated account of the same signal.",
                }
            )
            continue
        seen.add(signature)
        eligible.append(item)
    # What they do now is a better reason to write than where they worked before, so
    # earlier-career facts rank after everything else (live case: "Prior to joining…" was
    # chosen over the person's current remit).
    eligible.sort(
        key=lambda item: (
            not (item["kind"] != "event" and _PAST_ROLE.search(normal(item["quote"]))),
            sum(item["score"].values()),
            item["score"]["quality"],
            item["id"],
        ),
        reverse=True,
    )
    base["candidate_signals"] = eligible
    # True facts that are not hook material are kept for the reviewer to choose from:
    # "context" has no link to the offer; "background" is their earlier role elsewhere.
    for item in base["rejected_signals"]:
        reason = str(item.get("reason", ""))
        source = by_id.get(item.get("source_id"), {})
        if not item.get("quote") or not supported_quote(source, item["quote"]):
            continue
        about_them = bool(item.get("person")) and normal(item["person"]) == normal(identity["name"])
        past_role = bool(_PAST_ROLE.search(normal(item["quote"])))
        if "no specific connection" in reason:
            category = "context"
        elif about_them and (
            "not attributed to the confirmed company" in reason
            or ("relabelled as evergreen" in reason and past_role)
        ):
            category = "background"
        else:
            continue
        base["context_signals"].append({**item, "category": category})
    base["context_signals"] = base["context_signals"][:4]
    fallback = None
    if not eligible:
        fallback = _soft_signal_hook(parsed, by_id, identity, offer_terms, today) or (
            None if company_only else _role_hook(identity, offer_terms)
        )
    if company_only:
        chosen = eligible[0] if eligible else None
        hook = fallback
        if chosen:
            by_id[chosen["source_id"]]["passage"] = chosen["quote"]
            hook = {
                "title": "About their company",
                "summary": chosen["quote"],
                "source_ids": [chosen["source_id"]],
                "signal_id": chosen["id"],
                "temporal_label": "Recent event"
                if chosen["kind"] == "event"
                else "Evergreen evidence",
                "strength": "weak",
                "event_date": chosen["event_date"],
                "score": chosen["score"],
                "selection_reasons": [],
            }
        if not hook:
            return {
                **base,
                "outcome": "needs_more_evidence",
                "reason": identity["summary"],
                "next_action": "Add an accessible official source or try another source.",
            }
        hook["title"] = "About their company"
        hook["selection_reasons"] = [
            f"{prospect['name']} could not be confirmed at {prospect['company']} from a "
            "readable page, so the email talks only about the company.",
            *hook.get("selection_reasons", []),
        ]
        return {
            **base,
            "outcome": "research_ready",
            "hook": hook,
            "reason": f"We could not confirm from a readable page that {prospect['name']} "
            f"works at {prospect['company']}. The email mentions only the company. Check "
            "the person yourself before sending.",
            "next_action": "Research saved. No outreach draft has been created or approved.",
        }
    if fallback:
        return {
            **base,
            "outcome": "research_ready",
            "hook": fallback,
            "reason": "Nothing passed every check for a strong hook, so the email uses the "
            "best sourced detail that was found. This is a weaker hook: read it before "
            "approving, and add a better source if you have one.",
            "next_action": "Research saved. No outreach draft has been created or approved.",
        }
    if not eligible:
        return {
            **base,
            "outcome": "needs_more_evidence",
            "reason": "No supported, relevant and temporally safe hook remains.",
            "next_action": "Try another accessible source before generating a draft.",
        }
    selected = eligible[0]
    by_id[selected["source_id"]]["passage"] = selected["quote"]
    selected_source = by_id[selected["source_id"]]
    if selected["kind"] == "event" and not selected_source.get("event_date"):
        selected_source["event_date"] = selected["event_date"]
    matches = sorted(_terms(selected["quote"]) & offer_terms)
    factors = [
        "Offer connection: " + ", ".join(matches) + ".",
        "Confirmed role: " + (identity.get("role") or "Unknown") + ".",
        f"Specificity score: {selected['score']['specificity']} of 3, after support checks.",
        (
            f"Freshness: event date {selected['event_date']}, within {recent_days} days of {today}."
            if selected["kind"] == "event"
            else "Freshness: evergreen evidence; no recent-event claim."
        ),
        "Source quality: " + selected_source.get("quality", "other") + ".",
    ]
    hook = {
        "title": "A supported development"
        if selected["kind"] == "event"
        else "An established responsibility",
        "summary": selected["quote"],
        "source_ids": [selected["source_id"]],
        "signal_id": selected["id"],
        "temporal_label": "Recent event" if selected["kind"] == "event" else "Evergreen evidence",
        "strength": "strong" if selected["kind"] == "event" else "moderate",
        "event_date": selected["event_date"],
        "score": selected["score"],
        "selection_reasons": factors,
    }
    reason = (
        (
            "This passage connects to the approved offer through " + ", ".join(matches) + ". "
            if matches
            else "This passage is about the person in their current role; the email bridges "
            "to the offer. "
        )
        + "It ranked first among "
        + str(len(eligible))
        + " eligible signal(s), considering "
        "confirmed role, specificity, event freshness and source quality. "
        "This is a relevance judgment, not evidence of buying intent."
    )
    return {
        **base,
        "outcome": "research_ready",
        "hook": hook,
        "reason": reason,
        "next_action": "Research saved. No outreach draft has been created or approved.",
    }
