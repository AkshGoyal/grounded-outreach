"""Named-prospect validation and the first, fixture-backed research decision path."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from outreach.core.workbench_claims import draft_context
from outreach.core.workbench_draft import compose_draft
from outreach.core.workbench_evidence import assess_identity, select_hook
from outreach.core.research import public_url
from outreach.ports.workbench import DraftWriter, ProspectResearchProvider

DEMO_CAMPAIGN = {
    "id": "invoice-review-demo",
    # 2: added the "why it matters" line. A saved snapshot is never changed in place, so
    # databases that hold version 1 keep it for their older runs.
    "version": 2,
    "name": "Invoice review for finance teams",
    "sender": "Alex Morgan, ClearLedger Demo",
    "offer": "Invoice review and exception routing for finance teams.",
    "intended_role": "Finance leaders responsible for invoice operations",
    "supported_capabilities": [
        "Review invoice information against supplied purchase-order records.",
        "Show exceptions and route them for human resolution.",
    ],
    # Why it matters: the sender's own claim about teams in general, never about a prospect.
    "proof_points": [
        "Finance teams often find invoice exceptions late, at month-end close.",
    ],
    "tone": "Concise, specific and professional",
    "cta": "Would a short walkthrough of invoice exception review be useful?",
    "fixture": True,
    "label": "Fictional demo offer; no customer results or measured savings claimed.",
}


# Research without a goal: nothing is offered, so nothing can be drafted. Research looks for
# any recent, sourced news about the person or company instead of offer-related news.
NO_GOAL = {
    "id": "no-goal",
    "version": 1,
    "name": "No goal",
    "sender": "",
    "offer": "",
    "intended_role": "",
    "supported_capabilities": [],
    "proof_points": [],
    "looking_for": "",
    "tone": "",
    "cta": "",
    "no_goal": True,
    "label": "Research only, without a goal.",
}

GOAL_FIELDS = (
    "sender_name",
    "sender_company",
    "offer",
    "intended_role",
    "capabilities",
    "proof_points",
    "looking_for",
    "cta",
)


def _lines(value):
    items = value if isinstance(value, list) else str(value or "").splitlines()
    return [
        " ".join(str(item).split()).lstrip("-•* ").strip() for item in items if str(item).strip()
    ]


class CampaignGoal(BaseModel):
    """The rep's goal for outreach: what is offered, to whom, and what the email may claim.

    Everything entered here becomes an approved claim the draft checker accepts, so each
    field is short, plain and bounded. A saved goal is immutable; editing makes a new one.
    """

    model_config = ConfigDict(extra="forbid")

    sender_name: str = Field(min_length=2, max_length=80)
    sender_company: str = Field(min_length=2, max_length=80)
    offer: str = Field(min_length=10, max_length=160)
    intended_role: str = Field(min_length=3, max_length=120)
    capabilities: list[str] = Field(min_length=1, max_length=4)
    proof_points: list[str] = Field(default_factory=list, max_length=3)
    looking_for: str = Field(default="", max_length=200)
    cta: str = Field(min_length=10, max_length=160)

    @field_validator("capabilities", "proof_points", mode="before")
    @classmethod
    def split_lines(cls, value):
        return _lines(value)

    @field_validator("capabilities", "proof_points")
    @classmethod
    def short_lines(cls, value):
        for item in value:
            if not 5 <= len(item) <= 200:
                raise ValueError("Keep each line between 5 and 200 characters.")
            if "?" in item:
                raise ValueError("Write claims as statements, not questions.")
        return value

    @field_validator(
        "sender_name",
        "sender_company",
        "offer",
        "intended_role",
        "looking_for",
        "cta",
        mode="before",
    )
    @classmethod
    def trim(cls, value):
        return " ".join(str(value or "").split())

    @field_validator("sender_name", "sender_company")
    @classmethod
    def no_comma(cls, value):
        if "," in value:
            raise ValueError("Leave out commas.")
        return value

    @field_validator("offer")
    @classmethod
    def offer_statement(cls, value):
        if "?" in value:
            raise ValueError("Describe the offer as a statement, not a question.")
        return value

    @field_validator("cta")
    @classmethod
    def one_question(cls, value):
        if not value.endswith("?") or value.count("?") != 1:
            raise ValueError("Write one question that ends with a question mark.")
        if any(mark in value[:-1] for mark in (". ", "! ")):
            raise ValueError("Keep the closing question to one sentence.")
        return value

    def campaign(self) -> dict:
        """The immutable snapshot a run is bound to; its ID is derived from its content."""
        body = {
            "sender": f"{self.sender_name}, {self.sender_company}",
            "offer": self.offer.rstrip(".") + ".",
            "intended_role": self.intended_role,
            "supported_capabilities": list(self.capabilities),
            "proof_points": list(self.proof_points),
            "looking_for": self.looking_for,
            "tone": DEMO_CAMPAIGN["tone"],
            "cta": self.cta,
        }
        if goal_values(DEMO_CAMPAIGN) == goal_values(body):
            return dict(DEMO_CAMPAIGN)
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
        return {
            "id": f"goal-{digest}",
            "version": 1,
            "name": self.offer.rstrip("."),
            **body,
            "fixture": False,
            "label": "Your goal. Every capability and result listed here is treated as true.",
        }


def goal_values(campaign: dict) -> dict:
    """Form values for a saved campaign snapshot (used to prefill the goal form)."""
    sender = campaign.get("sender", "")
    name, _, company = sender.partition(",")
    return {
        "sender_name": name.strip(),
        "sender_company": company.strip(),
        "offer": campaign.get("offer", "").rstrip("."),
        "intended_role": campaign.get("intended_role", ""),
        "capabilities": "\n".join(campaign.get("supported_capabilities", [])),
        "proof_points": "\n".join(campaign.get("proof_points", [])),
        "looking_for": campaign.get("looking_for", ""),
        "cta": campaign.get("cta", ""),
    }


class Prospect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=200)
    role: str = Field(default="", max_length=120)
    website: str = Field(default="", max_length=2000)
    profile_url: str = Field(default="", max_length=2000)
    email: str = Field(default="", max_length=254)

    @field_validator("*", mode="before")
    @classmethod
    def trim(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("name", "company")
    @classmethod
    def useful_identity(cls, value):
        if value.casefold() in {"unknown", "none", "n/a", "na"} or not any(
            letter.isalpha() for letter in value
        ):
            raise ValueError("Enter the prospect's name and company or domain.")
        return value

    @field_validator("website", "profile_url")
    @classmethod
    def public_hint(cls, value):
        if not value:
            return ""
        url = public_url(value)
        if not url:
            raise ValueError("Use a public HTTP or HTTPS URL without credentials.")
        return url

    @field_validator("email")
    @classmethod
    def optional_email(cls, value):
        return str(TypeAdapter(EmailStr).validate_python(value)) if value else ""


def parse_prospects(text: str, limit: int = 20):
    """Rows pasted from a spreadsheet: name, company, job title, website (last two optional).

    Returns (prospects, errors). Tabs or commas separate cells; a header row is skipped.
    """
    prospects, errors, seen = [], [], set()
    rows = [line for line in str(text or "").splitlines() if line.strip()]
    for number, line in enumerate(rows, 1):
        delimiter = "\t" if "\t" in line else ","
        # Quoted cells keep their commas ("Acme, Inc."); quotes themselves are dropped.
        cells = [
            cell.strip().strip('"').strip()
            for cell in re.split(delimiter + r'(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
        ]
        if number == 1 and cells[0].casefold() in {"name", "full name", "prospect", "person"}:
            continue
        if len(cells) < 2 or not cells[1]:
            errors.append(f"Line {number}: add the company after the name, separated by a comma.")
            continue
        values = {"name": cells[0], "company": cells[1]}
        for cell in cells[2:4]:
            if cell.casefold().startswith(("http://", "https://")):
                values["website"] = cell
            elif cell and "role" not in values:
                values["role"] = cell
        try:
            prospect = Prospect.model_validate(values).model_dump()
        except ValidationError as exc:
            problem = exc.errors(include_input=False)[0]
            errors.append(f"Line {number} ({cells[0] or 'no name'}): {problem['msg']}")
            continue
        key = (prospect["name"].casefold(), prospect["company"].casefold())
        if key in seen:
            continue
        seen.add(key)
        prospects.append(prospect)
    if not prospects and not errors:
        errors.append("Paste at least one prospect: name, company.")
    if len(prospects) > limit:
        errors.append(f"That is {len(prospects)} prospects; a batch holds up to {limit}.")
    return prospects, errors


def run_pipeline(
    prospect: dict,
    campaign: dict,
    provider: ProspectResearchProvider,
    emit: Callable[[str, str, str], None],
    writer: DraftWriter | None = None,
    fallback: DraftWriter | None = None,
) -> dict:
    """Use the same evidence gates for fixture and live provider responses.

    ``fallback`` is a free writer used when ``writer`` cannot produce a draft.
    """
    prospect = Prospect.model_validate(prospect).model_dump()
    emit("Check prospect", "started", "Checking the saved prospect and campaign snapshot.")
    if not campaign.get("id") or not campaign.get("version"):
        raise ValueError("A versioned campaign brief is required.")
    emit("Check prospect", "completed", "Name and company are present.")
    emit("Research sources", "started", "Resolving identity before selecting a relevant signal.")
    data = provider.research(prospect)
    stopped_early = data.get("stopped_reason")
    emit(
        "Research sources",
        "failed" if stopped_early else "completed",
        "Research stopped early; continuing with what was saved. " + stopped_early
        if stopped_early
        else "Provider evidence and access limitations saved.",
    )
    sources = data.get("sources", [])
    emit("Match identity", "started", "Checking source-bound person, employer and role evidence.")
    identity = assess_identity(
        prospect, sources, data.get("identity_candidates", []), data.get("confirmed_id")
    )
    emit("Match identity", "completed", identity["summary"])
    emit(
        "Choose a hook",
        "started",
        "Gating source support, entity, dates and contradictions before ranking.",
    )
    result = select_hook(
        prospect,
        campaign,
        sources,
        data.get("signals", []),
        identity,
        now=data.get("reference_time"),
        recent_days=data.get("recent_days", 180),
    )
    result["limitations"] = list(
        dict.fromkeys([*result.get("limitations", []), *data.get("limitations", [])])
    )
    if stopped_early:
        result["limitations"].insert(
            0, "Research stopped early, so this uses only what was saved: " + stopped_early
        )
    if data.get("provider_failed") and result["outcome"] == "needs_more_evidence":
        result.update(
            outcome="research_unavailable",
            reason="The provider could not complete the required research.",
            next_action="Review the saved request state before starting any new paid request.",
        )
    emit("Choose a hook", "completed", result["reason"])
    if result["outcome"] == "research_ready" and writer is not None:
        context = draft_context({"result": result, "campaign": campaign, "prospect": prospect})
        drafts, stopped, notes = compose_draft(writer, context, emit, fallback)
        result["drafts"] = drafts
        result["limitations"].extend(notes)
        if stopped:
            result["limitations"].append("Drafting stopped: " + stopped)
            result["next_action"] = (
                "Research is saved. Review the held or limited request before any new paid draft."
            )
        elif drafts:
            ready = drafts[-1]["check"]["ok"]
            result.update(
                outcome="ready_for_review" if ready else "needs_revision",
                next_action="Review the draft against its sources, then approve the exact version."
                if ready
                else "Edit the highlighted wording, then check the edits again.",
            )
    emit(
        "Prepare result",
        "completed",
        "Evidence, decision and next action prepared; nothing is approved until a reviewer does.",
    )
    return result
