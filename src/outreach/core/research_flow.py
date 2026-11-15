"""Plan -> explicit approval -> discovery -> same-company sources -> review."""

import json

from outreach.core.discovery import checked_candidates, discovery_context, sources_of
from outreach.core.intake import CONTACT_ROLES
from outreach.core.research import (
    Assessment,
    Candidates,
    ResearchPlan,
    ResearchStop,
    checked_facts,
    host,
    published_emails,
    same_site,
    text_windows,
)


def build_plan(store, api, run_id):
    run = store.run(run_id)
    plan = api.generate(
        f"plan/{run['plan_version']}",
        "Turn this brief into a concrete lead-research plan for user approval. "
        "Return what you understood, 1-6 mandatory company-specific criteria, "
        "exclusions, and two groups of 1-3 search queries. Prefer company websites. "
        "Distinguish owned products from consulting, garment manufacturing from "
        "fabric supply, and company fit from current buying/hiring. Do not name "
        "invented companies.\nBRIEF: " + run["brief"],
        ResearchPlan,
    )
    store.set_run(
        run_id,
        plan_json=plan.model_dump_json(),
        status="awaiting_approval",
        progress="Review what we understood and edit the plan before research starts.",
        error="",
    )
    store.message(run_id, "assistant", plan.summary)


def run_research(store, api, run_id):
    run = store.run(run_id)
    if not run["approved_at"] or not run["plan"]:
        raise ResearchStop("Approve the research plan before discovering leads.")
    if run["execution"]["version"] == 2:
        from outreach.core.research_scheduler import run_staged_research

        return run_staged_research(store, api, run_id)
    plan = ResearchPlan.model_validate(run["plan"])
    target = run["target_count"]
    flexible = (run.get("intake") or {}).get("research_mode") == "flexible"
    for round_no, queries in enumerate((plan.queries, plan.alternate_queries), 1):
        if len(store.leads(run_id)) >= target:
            break
        store.set_run(run_id, progress=f"Finding companies · search round {round_no} of 2")
        sources = sources_of(api.search(f"discovery/{round_no}", plan.summary, queries))
        context = discovery_context(sources, 10 if flexible else 8)
        answer = api.generate(
            f"discovery-select/{round_no}",
            f"Select up to {target} distinct companies matching this plan. Each website MUST be "
            "an actual official company URL in its cited source text or source URL. Never return "
            "a directory, social profile or guessed domain as a company website. identity_quote "
            "must be copied literally from the supplied source and identify this company. "
            "Return fewer candidates if insufficient evidence.\nPLAN: "
            + plan.model_dump_json()
            + "\nSOURCES: "
            + json.dumps(context, ensure_ascii=False),
            Candidates,
        )
        candidates, rejected = checked_candidates(sources, answer, 10 if flexible else 8)
        if rejected:
            store.message(
                run_id,
                "assistant",
                f"Search round {round_no}: {sum(rejected.values())} suggestions were excluded "
                "because their company website or identity could not be verified.",
            )
        for candidate in candidates:
            store.add_candidate(run_id, candidate)
            if len(store.leads(run_id)) >= target:
                break
    leads = store.leads(run_id)
    for number, lead in enumerate(leads, 1):
        if store.run(run_id)["status"] != "running":
            raise ResearchStop("Research paused. Completed leads are saved.")
        if lead["processing_status"] == "complete":
            continue
        prefix = f"company/{lead['id']}"
        store.set_run(run_id, progress=f"Reading {lead['company']} · {number} of {len(leads)}")
        objective = (
            "Find official contact, about, products and careers pages for " + lead["company"]
        )
        query = lead["company"] + " official contact careers email"
        # Legacy runs keep their original inputs for durable checkpoint recovery.
        if run.get("intake"):
            roles = run["intake"]["contact_roles"]
            objective += (
                ". Official domain: "
                + lead["website"]
                + ". Accepted contacts: "
                + "; ".join(CONTACT_ROLES[role] for role in roles)
                + ". Find published professional addresses for any of these roles; "
                "do not guess addresses or relabel general inboxes as a named contact."
            )
            keywords = {
                "founder": "founder",
                "hr": "HR recruiting careers",
                "management": "leadership management",
                "general": "contact",
                "other": "contact",
            }
            query = lead["company"] + " " + " ".join(keywords[role] for role in roles) + " email"
        queries = [query]
        if flexible:
            objective += (
                ". Prefer these roles; include an explicitly published general business inbox "
                "as a fallback. Search contact footers and official careers pages."
            )
            queries += [
                "site:" + host(lead["website"]) + " contact email",
                lead["company"] + " official careers recruiting email",
            ]
        response = api.search(prefix + "/contact-search", objective, queries)
        candidates = sources_of(response)
        urls = list(
            dict.fromkeys(
                [
                    lead["website"],
                    *[s["url"] for s in candidates if same_site(s["url"], lead["website"])],
                ]
            )
        )[:4]
        if flexible:
            official_sources = [s for s in candidates if same_site(s["url"], lead["website"])]
            ranked = sorted(
                official_sources,
                key=lambda s: (
                    not bool(published_emails([s], lead["website"])),
                    not any(word in s["url"].lower() for word in ("contact", "career", "about")),
                ),
            )
            urls = list(dict.fromkeys([s["url"] for s in ranked] + urls))[:4]
        sources = sources_of(api.extract(prefix + "/pages", urls))
        sources = [s for s in sources if same_site(s["url"], lead["website"])]
        official_search = [s for s in candidates if same_site(s["url"], lead["website"])]
        evidence_sources = sources + [
            s
            for s in official_search
            if not any(s["url"] == item["url"] and s["text"] == item["text"] for item in sources)
        ]
        emails = published_emails(evidence_sources, lead["website"])
        # Preserve earlier request fingerprints. Flexible drafts can use search evidence
        # for assessment too; legacy runs keep the original extracted-page prompt.
        if flexible:
            sources = evidence_sources
        context = {
            f"s{i}": {**s, "text": text_windows(s["text"], 5000)}
            for i, s in enumerate(sources[:3], 1)
        }
        criteria = [
            {"criterion_index": i, "criterion": value} for i, value in enumerate(plan.criteria, 1)
        ]
        answer = api.generate(
            prefix + "/assessment",
            "Assess only this company. For each criterion_index return supported, contradicted "
            "or unknown with source_id and a short exact quote from ONE contiguous passage. "
            "Do not fix spelling, join headings, add punctuation or use directory-wide claims. "
            "Office address alone does not prove a manufacturing facility. Service delivery "
            "alone does not prove an owned software product. Do not infer hiring or buying "
            "intent. Explain uncertainties.\nCOMPANY: "
            + lead["company"]
            + "\nCRITERIA: "
            + json.dumps(criteria)
            + "\nSOURCES: "
            + json.dumps(context, ensure_ascii=False),
            Assessment,
        )
        facts = checked_facts(
            answer, plan.criteria, {f"s{i}": s for i, s in enumerate(sources[:3], 1)}
        )
        flags = list(answer.unknowns)
        if flexible and "general" not in run["intake"]["contact_roles"] and emails:
            flags.append(
                "Flexible search includes general business inbox fallbacks. "
                "Review the quoted role; a general inbox is not a named or HR contact."
            )
        if not emails:
            flags.append("No published email found on the retrieved company pages.")
        if any(f["status"] != "supported" for f in facts):
            flags.append(
                "Some criteria lack verified literal evidence; human fit review is required."
            )
        flags.append("Confirm that this website belongs to the intended company before approval.")
        store.save_evidence(
            lead["id"],
            facts=facts,
            sources=evidence_sources,
            emails=emails,
            flags=flags,
            summary=answer.fit_summary,
        )
    store.set_run(
        run_id, status="completed", progress=f"{len(leads)} companies saved for review.", error=""
    )
