"""One published contact and its evidence across review and campaign handoff."""


def selected_contact(lead):
    if not lead:
        return None
    emails = lead.get("emails", [])
    chosen = lead.get("selected_email")
    if chosen:
        # Never replace an explicit choice with another person's address.
        return next((email for email in emails if email["value"] == chosen), None)
    return emails[0] if emails else None


def contact_summary(lead):
    email = selected_contact(lead)
    contradicted = [f["criterion"] for f in lead.get("facts", []) if f["status"] == "contradicted"]
    unknown = [f["criterion"] for f in lead.get("facts", []) if f["status"] == "unknown"]
    kind = email.get("match_kind") if email else None
    return {
        "email": email,
        "role_label": {
            "requested_role": "Role matched",
            "general_fallback": "General inbox",
        }.get(kind, "Role unconfirmed"),
        "contradicted": contradicted,
        "unknown": unknown,
        "stale_selection": bool(lead.get("selected_email") and not email),
        "preselect": bool(
            email
            and not contradicted
            and not unknown
            and (lead["review_status"] == "approved" or kind == "requested_role")
        ),
    }


def campaign_email(lead):
    if (
        not lead
        or lead["processing_status"] != "complete"
        or lead["review_status"] == "rejected"
        or lead.get("suppressed")
    ):
        return None
    return selected_contact(lead)
