"""Free, conservative interpretation of common audience prompts.

Keep the complete original request. Missing or ambiguous essentials are clarified,
never filled by a paid model call or silently broadened.
"""

import re

from outreach.core.intake import AudienceIntake


def labelled(prompt, label):
    match = re.search(rf"(?:^|\n){label}\s*:\s*([^\n]+)", prompt, re.I)
    return match.group(1).strip().rstrip(".") if match else ""


def prompt_purpose(prompt):
    if re.search(r"\b(jobs?|careers?|employment|internships?)\b", prompt, re.I):
        return "job search"
    if re.search(r"\b(partner|partners|partnership|partnerships|collaboration)\b", prompt, re.I):
        return "partnerships"
    return "sales"


def audience_from_prompt(prompt, *, research_mode="focused", seed_websites=""):
    if len(prompt) > 2000:
        raise ValueError(
            "Keep the overall audience prompt below 2,000 characters, or use detailed inputs."
        )
    company = labelled(prompt, r"(?:companies|company type|audience)")
    geography = labelled(prompt, r"(?:location|geography)")
    # Recognise a common explicit company + location sentence, not arbitrary prose.
    match = re.search(
        r"\b(?:find|reach|target|research|looking for)\s+(.+?)\s+in\s+"
        r"([^\n.!?;]+?)(?=\s+(?:for|to|with|and contact|and reach)\b|[\n.!?;]|$)",
        prompt,
        re.I,
    )
    if match:
        company = company or match.group(1).strip()
        geography = geography or match.group(2).strip()
    if not geography and re.search(r"\b(anywhere|worldwide|globally)\b", prompt, re.I):
        geography = "Anywhere"
        match = re.search(
            r"\b(?:find|reach|target|research)\s+(.+?)\s+(?:anywhere|worldwide|globally)\b",
            prompt,
            re.I,
        )
        company = company or (match.group(1).strip() if match else "")
    # Exclusion clauses must not become acceptable roles.
    positive = re.sub(
        r"\b(?:exclude|avoid|do not contact|don't contact|not)\b[^\n.!?;]*", "", prompt, flags=re.I
    )
    patterns = {
        "founder": r"\b(?:co[- ]?founders?|founders?)\b",
        "hr": r"\b(?:HR|recruiters?|recruiting|recruitment|human resources)\b",
        "management": r"\b(?:management|CEOs?|CTOs?|CFOs?|COOs?|directors?|executives?)\b",
        "general": r"\b(?:general (?:business )?inbox(?:es)?|business inbox(?:es)?)\b",
    }
    roles = [key for key, pattern in patterns.items() if re.search(pattern, positive, re.I)]
    return AudienceIntake(
        prompt_input=True,
        goal=prompt,
        company_type=company,
        geography=geography,
        contact_roles=roles,
        must_haves=labelled(prompt, r"(?:must-haves|requirements)"),
        exclusions=labelled(prompt, r"(?:exclude|exclusions)")
        or (
            match.group(1).strip()
            if (match := re.search(r"\b(?:exclude|avoid)\s+([^\n.!?;]+)", prompt, re.I))
            else ""
        ),
        personalisation=labelled(prompt, r"(?:personalisation|personalization|learn)"),
        research_mode=research_mode,
        seed_websites=seed_websites,
    )
