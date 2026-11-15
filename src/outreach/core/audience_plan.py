"""Free, predictable planning from the owner's structured audience preferences."""

from outreach.core.intake import CONTACT_ROLES, AudienceIntake
from outreach.core.research import ResearchPlan


def local_plan(intake: AudienceIntake):
    if intake.questions():
        raise ValueError("Complete company type, location and contact roles first.")
    scope = " ".join((intake.company_type, intake.geography)).strip()
    roles = " ".join(CONTACT_ROLES[r] for r in intake.contact_roles)
    criteria = [intake.company_type]
    if intake.geography.casefold() not in {"anywhere", "worldwide", "global"}:
        criteria.append("Located in " + intake.geography)
    if intake.must_haves:
        criteria.append(intake.must_haves)
    return ResearchPlan(
        summary=intake.goal
        if intake.prompt_input
        else (
            intake.goal
            + "\nCompany type: "
            + intake.company_type
            + "\nLocation: "
            + intake.geography
            + "\nPrefer: "
            + roles
            + (
                "; general inbox fallback allowed after checking preferred roles."
                if intake.research_mode == "flexible"
                else "; review requested roles."
            )
        )[:2000],
        criteria=criteria,
        queries=[
            (scope + " companies official websites")[:200],
            (scope + " " + " ".join(intake.contact_roles) + " contact email")[:200],
        ],
        alternate_queries=[
            (scope + " industry association members")[:200],
            (scope + " businesses contact")[:200],
        ],
        exclusions=[intake.exclusions] if intake.exclusions else [],
    )
