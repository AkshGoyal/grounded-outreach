"""Saved audience preferences, independent of paid planning and mail setup."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

CONTACT_ROLES = {
    "founder": "Founder / co-founder",
    "hr": "HR / recruiting (department inbox accepted)",
    "management": "Named senior management",
    "general": "General business inbox",
    "other": "Another role described in my goal",
}


def seed_companies(value):
    """Explicit owner-supplied companies; these are inputs, not verified web evidence."""
    from outreach.core.research import company_site, public_url

    result, seen = [], set()
    for line in value.splitlines():
        if not line.strip():
            continue
        name, separator, url = line.partition("|")
        website = public_url(url.strip())
        if (
            not separator
            or not 2 <= len(name.strip()) <= 120
            or not website
            or not company_site(website)
        ):
            raise ValueError("Use Company name | https://company-website on each line.")
        if website in seen:
            continue
        seen.add(website)
        result.append({"company": name.strip(), "website": website})
    if len(result) > 10:
        raise ValueError("Start with at most 10 known company websites.")
    return result


class AudienceIntake(BaseModel):
    prompt_input: bool = False
    goal: str = Field(min_length=20, max_length=6500)
    company_type: str = Field(default="", max_length=300)
    geography: str = Field(default="", max_length=300)
    contact_roles: list[str] = Field(default_factory=list, max_length=5)
    must_haves: str = Field(default="", max_length=300)
    exclusions: str = Field(default="", max_length=300)
    personalisation: str = Field(default="", max_length=300)
    research_mode: Literal["flexible", "focused"] = "focused"
    seed_websites: str = Field(default="", max_length=2500)

    @field_validator("seed_websites")
    @classmethod
    def valid_seeds(cls, value):
        seed_companies(value)
        return value.strip()

    @field_validator("contact_roles")
    @classmethod
    def known_roles(cls, roles):
        if any(role not in CONTACT_ROLES for role in roles):
            raise ValueError("Choose the displayed contact roles.")
        return list(dict.fromkeys(roles))

    def questions(self):
        questions = []
        if not self.company_type.strip():
            questions.append("What kind of companies should we research?")
        if not self.geography.strip():
            questions.append("Where should we look? You can enter ‘Anywhere’.")
        if not self.contact_roles:
            questions.append("Which contact roles are acceptable for this campaign?")
        return questions

    def research_brief(self):
        roles = "; ".join(CONTACT_ROLES[r] for r in self.contact_roles)
        facts = self.personalisation or "Source-backed company/product facts"
        fallback = (
            "Flexible search: prefer the selected roles, but accept an explicitly published "
            "general business inbox when no preferred-role address is found. Label the fallback "
            "as a general inbox; never claim it is a founder or HR address. Company type and "
            "geography guide discovery; do not invent extra must-haves or require vacancies. "
            "Keep plausible companies with unknown facts for human review. "
            if self.research_mode == "flexible"
            else ""
        )
        role_rule = (
            "General business inboxes are acceptable fallbacks for review. "
            if self.research_mode == "flexible"
            else "General/support/sales inboxes do not satisfy a founder, HR "
            "or management request. "
        )
        return (
            f"{self.goal}\n\nAudience preferences confirmed by the user:\n"
            f"Company type: {self.company_type}\nGeography: {self.geography}\n"
            f"Acceptable contact roles: {roles}\n"
            f"Must-haves: {self.must_haves or 'None added'}\n"
            f"Exclusions: {self.exclusions or 'None added'}\n"
            f"Personalisation evidence: {facts}\n"
            "Accepted contact roles are alternatives: one matching role is enough; "
            "do not require every role. Do not add company must-haves beyond those requested. "
            "Look for explicitly published professional email addresses for the accepted roles. "
            "Do not guess addresses or infer contact ownership. HR/recruiting department "
            "inboxes are acceptable when HR is selected. "
            + role_rule
            + "Keep unknowns unresolved. "
            + fallback
            + "Do not infer sender skills or require vacancies unless the user asks for them."
        )


def lead_stage(lead):
    if lead["review_status"] == "rejected":
        return "removed"
    if lead.get("suppressed"):
        return "held"
    if lead.get("processing_status", "complete") != "complete":
        return "checking"
    if lead["review_status"] == "approved":
        return "approved"
    if not lead["emails"]:
        return "missing"
    return "review"


LEAD_STAGES = {
    "all": "All companies",
    "checking": "Checks not finished",
    "review": "Needs review",
    "missing": "No published email",
    "approved": "Approved",
    "held": "Do not contact",
    "removed": "Removed",
}
