"""Published contact evidence across official and corroborated professional pages."""

import re
from typing import Literal

from pydantic import BaseModel, Field

from outreach.core.research import (
    Assessment,
    email_matches,
    host,
    literal,
    public_url,
    same_site,
)

ROLE_LABELS = {
    "founder": "Founder / co-founder",
    "management": "Named senior management",
    "hr": "HR / recruiting department",
}
ROLE_WORDS = {
    "founder": r"\b(?:co[- ]?founder|founder|founded|co[- ]?founded)\b",
    "management": r"\b(?:CEO|CTO|CFO|COO|chief|director|president)\b",
    "hr": r"\b(?:HR|recruiting|recruitment|human resources)\b",
}


class PersonEvidence(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    role: Literal["founder", "management", "hr"]
    source_id: str
    quote: str = Field(min_length=12, max_length=600)


class AddressEvidence(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    email: str = Field(max_length=254)
    source_id: str
    quote: str = Field(min_length=12, max_length=600)


class ContactEvidenceAssessment(Assessment):
    people: list[PersonEvidence] = Field(default_factory=list, max_length=6)
    addresses: list[AddressEvidence] = Field(default_factory=list, max_length=12)


class PersonalizationEvidence(BaseModel):
    source_id: str
    quote: str = Field(min_length=12, max_length=400)


class PersonalizedContactAssessment(ContactEvidenceAssessment):
    personalization: list[PersonalizationEvidence] = Field(default_factory=list, max_length=3)


def contains_name(value, text):
    return bool(re.search(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", text, re.I))


def supported_people(answer, context, company, website):
    found = []
    for person in answer.people:
        source = context.get(person.source_id)
        if (
            not source
            or not public_url(source["url"])
            or not literal(person.quote, source["text"])
            or not contains_name(person.name, person.quote)
            or not re.search(ROLE_WORDS[person.role], person.quote, re.I)
        ):
            continue
        if not same_site(source["url"], website) and not contains_name(company, person.quote):
            continue
        found.append(
            person.model_dump()
            | {
                "source_url": source["url"],
                "retrieved_at": source.get("retrieved_at", ""),
            }
        )
    return found


def company_email(value, website):
    return value.rsplit("@", 1)[-1].casefold() == host(website)


def collect_addresses(sources, website, company, people=()):
    # Import here to preserve the old scheduler's behavior and avoid a module cycle.
    from outreach.core.research_scheduler import contact_emails

    found = {}
    for source in sources:
        if not public_url(source["url"]):
            continue
        official = same_site(source["url"], website)
        # This only extracts literal published addresses; it does not assign ownership.
        for address in contact_emails([source], source["url"]):
            if not official and not (
                company_email(address["value"], website)
                and contains_name(company, source["text"])
                or any(contains_name(p["name"], address["quote"]) for p in people)
            ):
                continue
            evidence = {
                "url": source["url"],
                "quote": address["quote"],
                "retrieved_at": source.get("retrieved_at", ""),
                "scope": "official" if official else "external",
            }
            value = address["value"]
            if value in found:
                if evidence not in found[value]["publication_sources"]:
                    found[value]["publication_sources"].append(evidence)
                continue
            found[value] = address | {
                "publication_sources": [evidence],
                "source_scope": "official" if official else "external",
                "match_kind": "unconfirmed",
            }
    return list(found.values())


def link_contact_evidence(addresses, people, claims, context, company, website, roles):
    """Roles and addresses may have separate quotes; name coincidence is insufficient."""
    for address in addresses:
        address["match_kind"] = "unconfirmed"
        if address["role_hint"] == "General business inbox":
            if any(
                s["scope"] == "official" or company_email(address["value"], website)
                for s in address["publication_sources"]
            ):
                address["match_kind"] = (
                    "requested_role" if "general" in roles else "general_fallback"
                )
            continue
        if address["role_hint"] == "HR / recruiting department":
            if any(s["scope"] == "official" for s in address["publication_sources"]):
                address["match_kind"] = "requested_role" if "hr" in roles else "unconfirmed"
            continue
        if address["role_hint"] == "Support inbox":
            continue
        accepted = []
        for claim in claims:
            if claim.email.casefold() != address["value"].casefold():
                continue
            source = context.get(claim.source_id)
            if (
                not source
                or not literal(claim.quote, source["text"])
                or not contains_name(claim.name, claim.quote)
                or claim.email.casefold()
                not in {value.casefold() for _, _, value in email_matches(claim.quote)}
            ):
                continue
            for person in people:
                if person["name"].casefold() != claim.name.casefold():
                    continue
                # Require an employer/domain or explicit official-profile link in addition
                # to the matching name. Never join two unrelated namesakes automatically.
                corroborated = (
                    same_site(source["url"], website)
                    or company_email(address["value"], website)
                    or contains_name(company, claim.quote)
                    or any(
                        same_site(s["url"], website) and source["url"] in s["text"]
                        for s in context.values()
                    )
                )
                if corroborated:
                    accepted.append((person, source, claim))
        names = {p["name"].casefold() for p, _, _ in accepted}
        if len(names) != 1:
            continue
        person, source, claim = next(
            (entry for entry in accepted if entry[0]["role"] in roles), accepted[0]
        )
        address.update(
            contact_name=person["name"],
            role_hint=ROLE_LABELS[person["role"]],
            role_quote=person["quote"],
            role_source_url=person["source_url"],
            ownership_quote=claim.quote,
            ownership_source_url=source["url"],
            match_kind="requested_role" if person["role"] in roles else "unconfirmed",
        )
    return sorted(
        addresses,
        key=lambda a: (
            {"requested_role": 0, "general_fallback": 1, "unconfirmed": 2}[a["match_kind"]],
            a["value"],
        ),
    )


def result_counts(addresses):
    return {
        "requested_role": sum(a.get("match_kind") == "requested_role" for a in addresses),
        "general_fallback": sum(a.get("match_kind") == "general_fallback" for a in addresses),
        "unconfirmed": sum(a.get("match_kind") == "unconfirmed" for a in addresses),
    }
