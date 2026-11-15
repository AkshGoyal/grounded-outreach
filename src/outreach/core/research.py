"""Research vocabulary and evidence checks, independent of any API or database."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError, field_validator

DIRECTORIES = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "wikipedia.org",
    "tracxn.com",
    "revenuebase.ai",
    "indiamart.com",
    "justdial.com",
    "tradeindia.com",
    "youtube.com",
)


class ResearchStop(RuntimeError):
    pass


class ResearchBudgetStop(ResearchStop):
    pass


class ModelUnusable(ResearchStop):
    """A completed, paid model answer that cannot be used (empty or malformed)."""


class ProviderRejected(ResearchStop):
    """The provider refused the request outright; nothing was processed or charged."""


class ResearchPlan(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    criteria: list[str] = Field(min_length=1, max_length=6)
    queries: list[str] = Field(min_length=1, max_length=3)
    alternate_queries: list[str] = Field(min_length=1, max_length=3)
    exclusions: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("criteria", "queries", "alternate_queries", "exclusions")
    @classmethod
    def meaningful_items(cls, values):
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("Each plan item must contain 1–500 characters.")
        return [value.strip() for value in values]


class Candidate(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    website: str
    source_id: str
    identity_quote: str


class Candidates(BaseModel):
    candidates: list[Candidate] = Field(max_length=25)


class Fact(BaseModel):
    criterion_index: int
    status: str
    source_id: str
    quote: str


class Assessment(BaseModel):
    facts: list[Fact]
    fit_summary: str
    unknowns: list[str]


def public_url(value: str) -> str | None:
    try:
        p = urlsplit(value.strip())
        host = p.hostname or ""
        if p.scheme not in ("http", "https") or not host or "." not in host:
            return None
        if p.username or p.password or p.port not in (None, 80, 443):
            return None
        if host.endswith((".local", ".internal", ".localhost", ".invalid")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))
    except (ValueError, AttributeError):
        return None


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def company_site(url: str) -> bool:
    domain = host(url)
    return bool(public_url(url)) and not any(
        domain == d or domain.endswith("." + d) for d in DIRECTORIES
    )


def same_site(url: str, website: str) -> bool:
    domain, official = host(url), host(website)
    return bool(domain and official) and (domain == official or domain.endswith("." + official))


def literal(quote: str, text: str) -> bool:
    return len(quote.strip()) >= 12 and " ".join(quote.split()) in " ".join(text.split())


def text_windows(text: str, limit: int = 5500) -> str:
    """Keep a beginning, contact-bearing windows, and footer rather than only the top."""
    if len(text) <= limit:
        return text
    head_size = min(1400, int(limit * 0.35))
    tail_size = min(1000, int(limit * 0.25))
    remaining = max(0, limit - head_size - tail_size - 100)
    chunks = [text[:head_size]]
    roles = list(re.finditer(r"\b(?:co-?founders?|founders?|CEO)\b", text, re.I))
    emails = list(re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
    places = list(re.finditer(r"\b(?:Bangalore|Bengaluru)\b", text, re.I))
    contacts = list(re.finditer(r"contact|address|career|office", text, re.I))
    covered = []
    for match in roles + emails + places + contacts:
        if remaining <= 0 or len(covered) >= 8:
            break
        if any(start <= match.start() < end for start, end in covered):
            continue
        start = max(head_size, match.start() - 120)
        end = min(len(text) - tail_size, match.end() + 200)
        chunk = text[start:end]
        if chunk and remaining > 0:
            chunks.append(chunk[:remaining])
            remaining -= len(chunk) + 26
            covered.append((start, end))
    chunks.append(text[-tail_size:])
    return "\n\n[separate excerpt]\n\n".join(dict.fromkeys(chunks))[:limit]


def email_matches(text):
    """Read literal addresses and explicit [at]/(dot) spellings, never infer names."""
    pattern = (
        r"(?<![@A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}"
        r"(?:@|\s*(?:\[at\]|\(at\)|&#64;|&commat;)\s*)"
        r"[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}|"
        r"\s*(?:\[dot\]|\(dot\))\s*[A-Za-z0-9-]{1,63})+"
    )
    for match in re.finditer(pattern, text, re.I):
        published = match.group().rstrip(".")
        value = re.sub(r"\s*(?:\[at\]|\(at\)|&#64;|&commat;)\s*", "@", published, flags=re.I)
        value = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", value, flags=re.I)
        value = re.sub(r"\s+", "", value)
        yield match, published, value


def published_emails(sources: list[dict], website: str) -> list[dict]:
    """Deterministic extraction from same-site pages. Ownership still requires review."""
    found, seen = [], set()
    validator = TypeAdapter(EmailStr)
    for source in sources:
        if not same_site(source["url"], website):
            continue
        for match, published, value in email_matches(source["text"]):
            try:
                normalized = str(validator.validate_python(value)).lower()
            except ValidationError:
                continue
            if normalized in seen or normalized.endswith(("@example.com", "@yourbusiness.com")):
                continue
            seen.add(normalized)
            found.append(
                {
                    "value": normalized,
                    "published_value": published,
                    "source_url": source["url"],
                    "quote": source["text"][max(0, match.start() - 100) : match.end() + 120],
                    "retrieved_at": source["retrieved_at"],
                }
            )
    return found


def checked_facts(answer: Assessment, criteria: list[str], sources: dict) -> list[dict]:
    result = []
    for index, criterion in enumerate(criteria, 1):
        proposals = [f for f in answer.facts if f.criterion_index == index]
        fact = proposals[0] if len(proposals) == 1 else None
        source = sources.get(fact.source_id, {}) if fact else {}
        valid = fact and literal(fact.quote, source.get("text", ""))
        result.append(
            {
                "criterion": criterion,
                "status": fact.status
                if valid and fact.status in ("supported", "contradicted")
                else "unknown",
                "quote": fact.quote if valid else "",
                "source_url": source.get("url") if valid else None,
            }
        )
    return result
