"""Friendly research and spending summaries, without provider response content."""

from outreach.core.campaign_selection import campaign_email
from outreach.core.discovery import saved_discovery
from outreach.core.research_scheduler import ready_count


def request_summary(store, run, *, active):
    calls = store.rows(
        "SELECT call_key,status,charged_micro,cost_kind,created_at FROM research_calls "
        "WHERE run_id=? ORDER BY created_at",
        (run["id"],),
    )
    completed = sum(c["status"] == "complete" for c in calls)
    uncertain = len(calls) - completed
    discovery = saved_discovery(store, run["id"])
    leads = store.leads(run["id"])
    suggestions = store.suggestions(run["id"]) if run["execution"]["version"] == 2 else []
    current = next((c for c in calls if c["status"] != "complete"), None)
    matches = [email for lead in leads for email in lead["emails"]]
    return {
        "target_ready": ready_count(store, run["id"]),
        "role_matches": sum(e.get("match_kind") == "requested_role" for e in matches),
        "fallbacks": sum(e.get("match_kind") == "general_fallback" for e in matches),
        "unconfirmed_contacts": sum(e.get("match_kind") == "unconfirmed" for e in matches),
        "unresolved": sum(s["status"] == "unresolved" for s in suggestions),
        "resolving": sum(s["status"] == "pending" for s in suggestions),
        "checked": sum(lead["processing_status"] == "complete" for lead in leads),
        "email_count": len({e["value"] for lead in leads for e in lead["emails"]}),
        "outcome": run["execution"].get("outcome", ""),
        "request_started": current["created_at"] if active and current else None,
        "searches": sum(
            c["status"] == "complete"
            and (
                "/discovery/" in c["call_key"]
                or c["call_key"].startswith("discovery/")
                or c["call_key"].endswith("/search")
                or c["call_key"].endswith("/contact-search")
            )
            for c in calls
        ),
        "fetches": sum(
            c["status"] == "complete"
            and ("/page/" in c["call_key"] or c["call_key"].endswith("/pages"))
            for c in calls
        ),
        "total": len(calls),
        "completed": completed,
        "waiting": uncertain if active else 0,
        "needs_check": 0 if active else uncertain,
        "reported": sum(c["charged_micro"] for c in calls if c["cost_kind"] == "reported")
        / 1000000,
        "estimated": sum(c["charged_micro"] for c in calls if c["cost_kind"] == "tariff") / 1000000,
        "unconfirmed": sum(c["charged_micro"] for c in calls if c["cost_kind"] == "reserved")
        / 1000000,
        "suggested": len(suggestions)
        if run["execution"]["version"] == 2
        else discovery["suggested"],
        "rejected": run["execution"].get("rejected", 0)
        if run["execution"]["version"] == 2
        else discovery["rejected"],
        "recoverable": 0 if run["execution"]["version"] == 2 else len(discovery["recoverable"]),
        "companies": len(leads),
        "unchecked": sum(lead["processing_status"] != "complete" for lead in leads),
        "with_email": sum(bool(lead["emails"]) for lead in leads),
        "approved": sum(lead["review_status"] == "approved" for lead in leads),
    }


def continuation(store, run, active):
    """A saved-state next action. Merely viewing it never starts work."""
    key = run["id"]
    base = "/research/" + key

    def step(label, detail, href, action="link"):
        return {"label": label, "detail": detail, "href": href, "action": action}

    if run["deleted"] or run["archived"]:
        return step(
            "Restore this audience",
            "Restore saved work before continuing research.",
            "/workspace/audience/" + key + "/remove",
        )
    if active:
        return step(
            "Research is working",
            "Leave the app running. Results save as requests finish. "
            "You can pause company research after the current request.",
            base + "#live-progress",
        )
    uncertain = store.one(
        "SELECT call_key FROM research_calls WHERE run_id=? AND status!='complete'", (key,)
    )
    if uncertain:
        return step(
            "Check the previous request",
            "One request has an uncertain outcome. Check "
            "provider usage before deciding what to do next; it will not be replayed.",
            "/setup#research-connections",
        )
    ready = [lead for lead in store.audience_leads(key) if campaign_email(lead)]
    if ready:
        return step(
            "Add emails to a campaign",
            f"{len(ready)} published contacts are available. "
            "You can use partial results now and return to research later.",
            base + "?stage=all#contact-review"
            if all(lead["run_id"] == key for lead in ready)
            else base + "/use",
        )
    if run["execution"].get("outcome") == "budget_limit":
        return step(
            "Adjust the cap and continue this research",
            "The next request does not fit the remaining cap. Saved results and spending are kept. "
            "Increase this run’s total cap with confirmation, then continue; "
            "no request starts automatically.",
            base + "#research-limits",
        )
    if run["status"] == "awaiting_approval" and run["plan"]:
        return step(
            "Review and approve your plan",
            "Planning is finished. Company and email "
            "research has not started; review the plan and approve its spending cap.",
            base + "#plan-review",
        )
    if run["status"] == "draft":
        return step(
            "Finish audience details" if not run["intake"] else "Continue to planning",
            "Saving details and preparing the basic plan are free. "
            "Approve paid research separately.",
            base + "#audience-planning",
        )
    leads = store.leads(key)
    unchecked = sum(lead["processing_status"] != "complete" for lead in leads)
    if run["approved_at"] and (run["status"] in ("paused", "failed", "approved") or unchecked):
        if run["spent_micro"] >= run["budget_micro"]:
            return step(
                "Adjust the research cap",
                "Increase the total cap, then continue from saved results. "
                "Existing spending stays accounted.",
                base + "#research-limits",
            )
        return step(
            "Continue approved research (paid checks)",
            f"{unchecked} company suggestions "
            "still need checks. Continue from saved results within the remaining cap. "
            "Completed calls stay saved; no request starts until you click.",
            base,
            "resume",
        )
    if run["status"] == "failed":
        return step(
            "Save a revised audience",
            "Saved work is kept. Update the inputs in a new "
            "free draft before choosing another paid plan.",
            base + "/edit",
        )
    if not leads:
        return step(
            "Broaden the audience",
            "Research finished without saved companies. Try "
            "flexible search, broader geography or fewer must-haves in a revised draft.",
            base + "/edit",
        )
    ready = sum(bool(lead["emails"]) for lead in leads)
    return step(
        "Add emails to a campaign" if ready else "Review results or broaden the audience",
        f"{ready} companies have published emails. Select "
        "contacts to add to a campaign. Sources are optional to inspect.",
        base + "#contact-review",
    )
