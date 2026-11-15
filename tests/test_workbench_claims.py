"""Claim checks on drafts: meaning, not vocabulary overlap, decides support. Fictional data."""

from copy import deepcopy

import pytest

from outreach.adapters.workbench_fixture import FixtureDraftWriter, FixtureResearchProvider
from outreach.core.workbench import DEMO_CAMPAIGN, run_pipeline
from outreach.core.workbench_claims import draft_context, validate_draft

PROSPECT = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"}
OPENER = (
    "I read that Cedar Works is introducing a weekly invoice exception review led by "
    "you, with a named owner for each unresolved exception."
)


@pytest.fixture
def context():
    result = run_pipeline(PROSPECT, DEMO_CAMPAIGN, FixtureResearchProvider(), lambda *a: None)
    return draft_context({"result": result, "campaign": DEMO_CAMPAIGN, "prospect": PROSPECT})


@pytest.fixture
def good(context):
    return FixtureDraftWriter().generate("draft", "", context)


def replace(draft, old, new):
    changed = deepcopy(draft)
    assert old in changed["body"] or old in changed["subject"]
    changed["body"] = changed["body"].replace(old, new)
    changed["subject"] = changed["subject"].replace(old, new)
    return changed


def codes(check):
    return {issue["code"] for issue in check["errors"]}


def warnings(check):
    """Shown to the reviewer, but they do not block approval."""
    return {issue["code"] for issue in check["notices"]}


def test_supported_draft_binds_every_sentence_and_meets_length(context, good):
    check = validate_draft(good, context)
    assert check["ok"], check["errors"]
    assert 70 <= check["word_count"] <= 120
    content = [s for s in check["segments"] if s["role"] == "content"]
    assert all(s["support_ids"] for s in content)
    assert "fixture-invoice-review" in content[1]["support_ids"]
    assert any("offer" in s["kinds"] for s in content)
    assert any(s["role"] == "cta" for s in check["segments"])


def test_unsupported_causal_claim_with_matching_vocabulary_is_blocked(context, good):
    # Every content word comes from the source; the causal link and outcome do not.
    bad = replace(
        good,
        OPENER,
        "Because Cedar Works is introducing a weekly invoice exception review, each "
        "unresolved exception led by Maya Rao has a named owner.",
    )
    check = validate_draft(bad, context)
    assert not check["ok"] and "unsupported_causal" in codes(check)
    assert not [
        i for i in check["notices"] if i["code"] == "new_wording" and "because" in i["text"]
    ]


def test_tense_change_with_identical_vocabulary_is_blocked(context, good):
    completed = replace(good, "is introducing", "introduced")
    assert "tense" in codes(validate_draft(completed, context))
    planned = replace(good, "is introducing", "will introduce")
    assert "tense" in codes(validate_draft(planned, context))


def test_false_dates_and_relative_dates_are_blocked(context, good):
    wrong_day = replace(good, "I read that Cedar Works", "On October 3, Cedar Works")
    assert "unsupported_date" in codes(validate_draft(wrong_day, context))
    wrong_year = replace(good, "I read that Cedar Works", "In 2025, Cedar Works")
    assert codes(validate_draft(wrong_year, context)) & {"unsupported_date", "unsupported_specific"}
    right_day = replace(good, "I read that Cedar Works", "On October 15, Cedar Works")
    assert validate_draft(right_day, context)["ok"]
    relative = replace(good, "I read that Cedar Works", "Last week, Cedar Works")
    assert "relative_time" in codes(validate_draft(relative, context))


def test_fabricated_offer_claims_and_credentials_are_blocked(context, good):
    metric = replace(
        good,
        "It can also show exceptions and route them for human resolution.",
        "It cuts invoice exceptions by 40% for finance teams like yours.",
    )
    check = validate_draft(metric, context)
    assert {"unsupported_outcome", "unsupported_specific"} & codes(check)
    customers = replace(
        good,
        "It can also show exceptions and route them for human resolution.",
        "Leading finance teams already trust it to route exceptions.",
    )
    assert not validate_draft(customers, context)["ok"]


def test_citation_must_exist_and_match_the_claim_kind(context, good):
    fake = deepcopy(good)
    fake["claims"][1]["support_id"] = "capability-9"  # not in this campaign
    # Wrong citations are bookkeeping, not claims: warned about, and each sentence is still
    # checked against whatever actually supports it.
    assert "unknown_support" in warnings(validate_draft(fake, context))
    swapped = deepcopy(good)
    swapped["claims"][0]["support_id"] = "capability-1"  # a fact citing the offer
    assert "claim_kind" in warnings(validate_draft(swapped, context))
    unhedged = deepcopy(good)
    unhedged["claims"][-1]["text"] = "your team handles each unresolved exception"
    unhedged["claims"][-1]["kind"] = "inference"
    assert "unhedged_inference" in codes(validate_draft(unhedged, context))


def test_other_person_or_company_cannot_enter_the_draft(context, good):
    other = replace(good, "led by you", "led by Priya Shah")
    assert "unsupported_specific" in codes(validate_draft(other, context))
    other_company = replace(good, "I read that Cedar Works", "I read that Other Works")
    assert not validate_draft(other_company, context)["ok"]
    greeting = replace(good, "Hi Maya,", "Hi Priya,")
    assert "greeting_name" in codes(validate_draft(greeting, context))


def test_presupposition_certainty_and_pain_need_support(context, good):
    still = replace(
        good,
        "That may be relevant",
        "Cedar Works still has unresolved exceptions. That may be relevant",
    )
    assert "unsupported_presupposition" in warnings(validate_draft(still, context))
    for sentence in (
        "Clearly the weekly invoice exception review shows that exceptions matter.",
        "Your team is struggling with each unresolved exception.",
        "Your team needs a weekly invoice exception review.",
    ):
        bad = replace(good, "That may be relevant", sentence + " That may be relevant")
        assert not validate_draft(bad, context)["ok"], sentence


def test_one_exact_call_to_action(context, good):
    # Your closing question is a style choice, so changes to it are flagged, not blocked.
    missing = replace(good, DEMO_CAMPAIGN["cta"], "Let me know what you think.")
    assert "cta" in warnings(validate_draft(missing, context))
    extra = replace(
        good, "That may be relevant", "Is invoice review on your list? That may be relevant"
    )
    assert "cta" in warnings(validate_draft(extra, context))


def test_recency_words_need_a_recent_dated_hook(context, good):
    recent = replace(good, "I read that Cedar Works", "I recently read that Cedar Works")
    assert validate_draft(recent, context)["ok"]
    evergreen = deepcopy(context)
    evergreen["hook"]["temporal_label"] = "Evergreen evidence"
    assert "recency" in codes(validate_draft(recent, evergreen))


def test_generic_draft_is_flagged_but_left_to_the_reviewer(context, good):
    generic = deepcopy(good)
    generic["body"] = generic["body"].replace(OPENER, "I hope this finds you well.")
    check = validate_draft(generic, context)
    assert {"hook_missing", "unsupported_sentence"} <= warnings(check)
    # A specific claim with nothing behind it is still blocked.
    invented = deepcopy(good)
    invented["body"] = invented["body"].replace(OPENER, "I saw Cedar Works opened a Berlin office.")
    assert "unsupported_specific" in codes(validate_draft(invented, context))


def test_campaign_snapshot_isolates_offer_claims_and_cta(context, good):
    other = deepcopy(DEMO_CAMPAIGN) | {
        "id": "other-campaign",
        "cta": "Could we compare notes next week?",
        "supported_capabilities": ["Summarize supplier statements."],
    }
    result = run_pipeline(PROSPECT, DEMO_CAMPAIGN, FixtureResearchProvider(), lambda *a: None)
    other_context = draft_context({"result": result, "campaign": other, "prospect": PROSPECT})
    check = validate_draft(good, other_context)
    assert {"cta", "unknown_support"} <= warnings(check)


def test_pipeline_repairs_once_then_holds_persistent_false_inference():
    repaired = run_pipeline(
        PROSPECT,
        DEMO_CAMPAIGN,
        FixtureResearchProvider(),
        lambda *a: None,
        FixtureDraftWriter("false_inference"),
    )
    assert repaired["outcome"] == "ready_for_review"
    assert [d["check"]["ok"] for d in repaired["drafts"]] == [False, True]
    held = run_pipeline(
        PROSPECT,
        DEMO_CAMPAIGN,
        FixtureResearchProvider(),
        lambda *a: None,
        FixtureDraftWriter("persistent_false_inference"),
    )
    assert held["outcome"] == "needs_revision" and len(held["drafts"]) == 2
    assert {"unsupported_pain", "unsupported_certainty"} <= codes(held["drafts"][-1]["check"])


def test_unknown_prospect_gets_a_draft_marked_not_personalised():
    calls = []

    class Writer(FixtureDraftWriter):
        def generate(self, *args):
            calls.append(args)
            return super().generate(*args)

    result = run_pipeline(
        {"name": "Unknown Person", "company": "Another Company"},
        DEMO_CAMPAIGN,
        FixtureResearchProvider(),
        lambda *a: None,
        Writer(),
    )
    hook = result["hook"]
    assert hook["basis"] == "as_entered" and hook["strength"] == "none"
    assert hook["judgement"]["verdict"].startswith("Not personalised")
    assert not result["sources"] and len(calls) == 1 and result["drafts"]
    body = result["drafts"][-1]["body"]
    assert "I read" not in body and "Unknown Person" not in body.split("\n", 1)[1]
