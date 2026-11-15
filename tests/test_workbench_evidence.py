"""Fictional source cases run through the same identity and hook gates as live research."""

from copy import deepcopy

import pytest

from outreach.adapters.workbench_fixture import FIXTURE_RESPONSE, FixtureResearchProvider
from outreach.core.workbench import DEMO_CAMPAIGN, run_pipeline
from outreach.core.workbench_evidence import assess_identity, select_hook

PROSPECT = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"}
NOW = "2026-11-10T00:00:00+00:00"


def evaluate(bundle, prospect=None, confirmed_id=None):
    prospect = prospect or PROSPECT
    identity = assess_identity(
        prospect, bundle["sources"], bundle["identity_candidates"], confirmed_id
    )
    return select_hook(
        prospect, DEMO_CAMPAIGN, bundle["sources"], bundle["signals"], identity, now=NOW
    )


def assert_no_signal_hook(result):
    """A rejected signal never becomes a strong, dated or "recent" hook.

    The result is either no hook, or a hook marked weaker that carries no date and no
    recency label (the draft checker then forbids "recently", "new" and similar).
    """
    if result["outcome"] == "research_ready":
        hook = result["hook"]
        assert hook["strength"] == "weak", hook
        assert hook["temporal_label"] != "Recent event" and hook["event_date"] is None
    else:
        assert result["outcome"] == "needs_more_evidence"


def assert_person_not_confirmed(result):
    """An unconfirmed person never gets a person hook; at most a company-only one."""
    assert result["identity"]["status"] != "matched"
    if result["outcome"] == "research_ready":
        assert result["hook"]["title"] == "About their company"
        assert result["hook"]["strength"] == "weak"
        assert "could not confirm" in result["reason"]
    else:
        assert result["outcome"] in ("needs_more_evidence", "needs_identity_confirmation")


def test_official_source_supports_hook_for_prospect_without_email():
    result = evaluate(deepcopy(FIXTURE_RESPONSE))
    assert result["outcome"] == "research_ready"
    assert result["hook"]["summary"] == FIXTURE_RESPONSE["signals"][0]["quote"]
    assert result["hook"]["source_ids"] == ["fixture-invoice-review"]
    assert result["hook"]["temporal_label"] == "Recent event"
    assert result["hook"]["score"]["role_fit"] == 1
    assert "not evidence of buying intent" in result["reason"]


@pytest.mark.parametrize("status", ["preview", "blocked", "unavailable", "empty"])
def test_unread_identity_source_never_establishes_identity(status):
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][0]["access_status"] = status
    assert_person_not_confirmed(evaluate(bundle))


@pytest.mark.parametrize(
    "url", ["https://www.linkedin.com/in/maya", "http://127.0.0.1/private", "javascript:alert(1)"]
)
def test_restricted_or_unsafe_read_cannot_enter_evidence(url):
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][0]["url"] = url
    result = evaluate(bundle)
    assert_person_not_confirmed(result)
    assert result["sources"][0]["access_status"] == "blocked"
    assert not result["sources"][0]["passage"]


def test_same_name_other_employer_requires_confirmation_before_hooks():
    bundle = deepcopy(FIXTURE_RESPONSE)
    other = deepcopy(bundle["identity_candidates"][0])
    other.update(
        company="Maple Works",
        domain="maple-works.example",
        source_id="other",
        quote="Maya Rao is Finance Director at Maple Works and oversees invoice review.",
    )
    bundle["identity_candidates"].append(other)
    bundle["sources"].append(
        {
            **bundle["sources"][0],
            "id": "other",
            "url": "https://maple-works.example/leadership",
            "text": other["quote"],
        }
    )
    first = evaluate(bundle)
    assert first["outcome"] == "needs_identity_confirmation" and first["hook"] is None
    choices = first["identity"]["candidates"]
    eligible = next(c for c in choices if c["company"] == "Cedar Works")
    wrong = next(c for c in choices if c["company"] == "Maple Works")
    assert eligible["selectable"] and not wrong["selectable"]
    assert evaluate(bundle, confirmed_id=eligible["id"])["outcome"] == "research_ready"
    assert evaluate(bundle, confirmed_id=wrong["id"])["outcome"] == "needs_identity_confirmation"


def test_changed_employer_and_old_identity_cannot_be_confirmed():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["identity_candidates"][0]["status"] = "former"
    result = evaluate(bundle)
    assert result["outcome"] == "needs_identity_confirmation"
    candidate = result["identity"]["candidates"][0]
    assert not candidate["selectable"]
    assert evaluate(bundle, confirmed_id=candidate["id"])["hook"] is None


def test_words_about_two_people_do_not_establish_one_identity():
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "Maya Rao met Arun Patel, Finance Director at Cedar Works, to discuss invoice review."
    bundle["sources"][0]["text"] = quote
    bundle["identity_candidates"][0]["quote"] = quote
    result = evaluate(bundle)
    assert_person_not_confirmed(result)
    assert not result["identity"]["candidates"][0]["selectable"]


def test_model_cannot_invent_company_domain_from_unrelated_page():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["identity_candidates"][0]["domain"] = "different-company.example"
    result = evaluate(bundle)
    assert_person_not_confirmed(result)
    assert not result["identity"]["candidates"][0]["selectable"]


def test_unrelated_blog_cannot_label_itself_an_official_identity_source():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][0].update(url="https://random-blog.example/profile", quality="official")
    result = evaluate(bundle)
    # A third-party page may only be confirmed by a person, never selected automatically.
    assert result["outcome"] == "needs_identity_confirmation" and result["hook"] is None
    assert all(c["weak"] for c in result["identity"]["candidates"] if c["supported"])


def test_recently_republished_old_event_is_not_a_recent_hook():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][1].update(event_date="2020-10-15", publication_date="2026-11-01")
    bundle["signals"][0]["event_date"] = "2020-10-15"
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert "older" in result["rejected_signals"][0]["reason"]


def test_unsupported_event_date_is_not_replaced_by_publication_date():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][1].update(event_date=None, publication_date="2026-10-15")
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert "Event date" in result["rejected_signals"][0]["reason"]


def test_recent_metadata_cannot_override_explicit_old_event_year_in_passage():
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "Cedar Works announced the invoice exception review in 2020."
    bundle["sources"][1]["text"] = quote
    bundle["signals"][0].update(quote=quote, person="")
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert "Event date" in result["rejected_signals"][0]["reason"]


def test_unknown_date_can_support_an_accurate_evergreen_responsibility():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"] = [
        {
            **bundle["signals"][0],
            "kind": "evergreen",
            "event_date": None,
            "source_id": "fixture-leadership",
            "quote": bundle["sources"][0]["text"],
            "event_key": "responsibility",
        }
    ]
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready"
    assert result["hook"]["temporal_label"] == "Evergreen evidence"
    assert result["hook"]["event_date"] is None


def test_event_cannot_be_disguised_as_evergreen():
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "Cedar Works announced a new invoice exception review in 2020."
    bundle["sources"][1]["text"] = quote
    bundle["signals"][0].update(kind="evergreen", event_date=None, quote=quote, person="")
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert "relabelled" in result["rejected_signals"][0]["reason"]


def test_conflicting_event_quantity_is_dropped_and_evergreen_alternative_wins():
    bundle = deepcopy(FIXTURE_RESPONSE)
    first = "Cedar Works is assigning 10 reviewers to invoice exceptions."
    second = "Cedar Works is assigning 20 reviewers to invoice exceptions."
    bundle["sources"][1]["text"] = first
    bundle["signals"][0]["quote"] = first
    bundle["sources"].append({**bundle["sources"][1], "id": "other-event", "text": second})
    bundle["signals"].append({**bundle["signals"][0], "source_id": "other-event", "quote": second})
    bundle["signals"].append(
        {
            **bundle["signals"][0],
            "source_id": "fixture-leadership",
            "quote": bundle["sources"][0]["text"],
            "kind": "evergreen",
            "event_date": None,
            "event_key": "role-responsibility",
        }
    )
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready"
    assert result["hook"]["source_ids"] == ["fixture-leadership"]
    assert sum("conflict" in s["reason"] for s in result["rejected_signals"]) == 2


def test_conflicting_event_dates_are_not_resolved_by_picking_higher_score():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"].append(
        {**bundle["sources"][1], "id": "other-event", "event_date": "2026-10-16"}
    )
    bundle["signals"].append(
        {
            **bundle["signals"][0],
            "source_id": "other-event",
            "event_date": "2026-10-16",
            "specificity": 0,
        }
    )
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert all("conflict" in signal["reason"] for signal in result["rejected_signals"])


def test_syndicated_signal_is_not_counted_twice_and_official_source_is_preferred():
    bundle = deepcopy(FIXTURE_RESPONSE)
    copy = {
        **bundle["sources"][1],
        "id": "syndicated",
        "url": "https://news.example/story",
        "quality": "reporting",
    }
    bundle["sources"].insert(1, copy)
    bundle["signals"].insert(0, {**bundle["signals"][0], "source_id": "syndicated"})
    result = evaluate(bundle)
    assert len(result["candidate_signals"]) == 1
    assert result["hook"]["source_ids"] == ["fixture-invoice-review"]
    assert "syndicated" in result["rejected_signals"][0]["reason"]


def test_unsupported_quote_or_wrong_person_cannot_be_ranked():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"][0]["quote"] += " Their invoices are always late."
    assert_no_signal_hook(evaluate(bundle))


def test_paraphrased_syndication_does_not_add_an_independent_signal():
    bundle = deepcopy(FIXTURE_RESPONSE)
    paraphrase = (
        "Cedar Works starts a weekly invoice exception review led by Maya Rao, "
        "assigning an owner to unresolved exceptions."
    )
    bundle["sources"].append(
        {**bundle["sources"][1], "id": "news-copy", "quality": "reporting", "text": paraphrase}
    )
    bundle["signals"].append(
        {**bundle["signals"][0], "source_id": "news-copy", "quote": paraphrase}
    )
    result = evaluate(bundle)
    assert len(result["candidate_signals"]) == 1
    assert result["hook"]["source_ids"] == ["fixture-invoice-review"]


def test_contradictory_event_status_cannot_be_selected_by_rank():
    bundle = deepcopy(FIXTURE_RESPONSE)
    denial = "Cedar Works cancelled the weekly invoice exception review led by Maya Rao."
    bundle["sources"].append({**bundle["sources"][1], "id": "cancellation", "text": denial})
    bundle["signals"].append({**bundle["signals"][0], "source_id": "cancellation", "quote": denial})
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert all("conflict" in s["reason"] for s in result["rejected_signals"])


def test_model_role_tag_cannot_make_an_unrelated_signal_relevant():
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "Cedar Works opened a cafeteria for employees on 2026-10-15."
    bundle["sources"][1]["text"] = quote
    bundle["signals"][0].update(quote=quote, person="", role_tags=["finance"])
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert "no specific connection" in result["rejected_signals"][0]["reason"]


def test_generic_review_word_does_not_establish_invoice_offer_connection():
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "Cedar Works completed a review of cafeteria menus on 2026-10-15."
    bundle["sources"][1]["text"] = quote
    bundle["signals"][0].update(quote=quote, person="", role_tags=["finance"])
    assert_no_signal_hook(evaluate(bundle))


def test_date_decorated_event_keys_cannot_evade_contradiction_grouping():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"][0]["event_key"] = "invoice-review-2026-10-15"
    bundle["sources"].append({**bundle["sources"][1], "id": "other", "event_date": "2026-10-16"})
    bundle["signals"].append(
        {
            **bundle["signals"][0],
            "event_key": "invoice-review-2026-10-16",
            "event_date": "2026-10-16",
            "source_id": "other",
        }
    )
    result = evaluate(bundle)
    assert_no_signal_hook(result)
    assert all("conflict" in s["reason"] for s in result["rejected_signals"])


def test_amount_decorated_event_keys_cannot_evade_contradiction_grouping():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"][0].update(
        event_key="invoice-review-10-reviewers",
        person="",
        quote="Cedar Works assigned 10 reviewers to invoice exceptions.",
    )
    bundle["sources"][1]["text"] = bundle["signals"][0]["quote"]
    bundle["sources"].append(
        {
            **bundle["sources"][1],
            "id": "other",
            "text": "Cedar Works assigned 20 reviewers to invoice exceptions.",
        }
    )
    bundle["signals"].append(
        {
            **bundle["signals"][0],
            "event_key": "invoice-review-20-reviewers",
            "source_id": "other",
            "quote": bundle["sources"][-1]["text"],
        }
    )
    assert_no_signal_hook(evaluate(bundle))


def test_event_without_topic_key_is_held_for_missing_conflict_check():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"][0]["event_key"] = ""
    assert_no_signal_hook(evaluate(bundle))


def test_literal_verified_event_date_is_shown_on_selected_source():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"][1]["event_date"] = None
    quote = "On 2026-10-15 Cedar Works introduced an invoice exception review led by Maya Rao."
    bundle["sources"][1]["text"] = quote
    bundle["signals"][0]["quote"] = quote
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready"
    assert result["sources"][1]["event_date"] == "2026-10-15"
    assert any("Source quality: official" in r for r in result["hook"]["selection_reasons"])
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"][0]["person"] = "Arun Patel"
    assert_no_signal_hook(evaluate(bundle))


def test_fixture_provider_uses_common_pipeline_and_real_events():
    events = []
    result = run_pipeline(
        PROSPECT, DEMO_CAMPAIGN, FixtureResearchProvider(), lambda *event: events.append(event)
    )
    assert result["outcome"] == "research_ready"
    assert any(name == "Match identity" and status == "completed" for name, status, _ in events)
    assert not any("Phase 3" in detail for _, _, detail in events)


def test_no_signals_falls_back_to_a_sourced_role_hook_marked_weaker():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"] = []
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready"
    assert result["hook"]["strength"] == "weak" and result["hook"]["signal_id"] is None
    assert result["hook"]["summary"] == result["identity"]["selected"]["quote"]
    assert "weaker hook" in result["reason"]


def test_a_bare_title_still_gives_a_weaker_role_hook():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["signals"] = []
    quote = "Maya Rao, Finance Director at Cedar Works"
    bundle["sources"][0]["text"] = quote
    bundle["identity_candidates"][0]["quote"] = quote
    result = evaluate(bundle)
    assert result["identity"]["status"] == "matched"
    assert result["outcome"] == "research_ready"
    assert result["hook"]["strength"] == "weak" and result["hook"]["summary"] == quote


def test_trimmed_quote_snaps_to_the_page_sentence_but_added_words_do_not():
    bundle = deepcopy(FIXTURE_RESPONSE)
    page = bundle["sources"][1]["text"]
    trimmed = page.replace("weekly ", "")
    assert trimmed != page
    bundle["signals"][0]["quote"] = trimmed
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready" and result["hook"]["summary"] == page.strip()
    bundle["signals"][0]["quote"] = page + " Their invoices are always late."
    assert_no_signal_hook(evaluate(bundle))


def test_date_only_conflict_is_used_without_a_date():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"].append(
        {**bundle["sources"][1], "id": "other-event", "event_date": "2026-10-16"}
    )
    bundle["signals"].append(
        {**bundle["signals"][0], "source_id": "other-event", "event_date": "2026-10-16"}
    )
    result = evaluate(bundle)
    assert result["outcome"] == "research_ready"
    assert result["hook"]["strength"] == "weak" and result["hook"]["event_date"] is None
    assert "date" in result["hook"]["selection_reasons"][0]


def test_unconfirmed_person_gets_a_company_only_hook_with_a_warning():
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["identity_candidates"] = []
    bundle["sources"][0]["text"] = "Cedar Works leadership: our finance team supports suppliers."
    result = evaluate(bundle)
    assert result["identity"]["status"] == "unconfirmed"
    assert result["outcome"] == "research_ready"
    assert result["hook"]["title"] == "About their company"
    assert "Maya Rao could not be confirmed" in result["hook"]["selection_reasons"][0]


def test_wire_dateline_is_trimmed_from_a_snapped_passage():
    from outreach.core.workbench_evidence import snap_quote

    text = (
        "ORLANDO, Fla., Oct. 19, 2026 (GLOBE NEWSWIRE) -- Cedar Works, Inc. (NASDAQ: CW) "
        "today announced that Maya Rao has joined the Company as Finance Director."
    )
    source = {"id": "read-x", "access_status": "read", "url": "https://x.example/a", "text": text}
    snapped = snap_quote(
        source, "Cedar Works today announced that Maya Rao has joined as Finance Director."
    )
    assert snapped.startswith("Cedar Works, Inc.") and snapped in text


def test_dateline_before_the_quote_or_same_day_today_supports_the_date():
    from outreach.core.workbench_evidence import _date_supported

    text = (
        "ORLANDO, Fla., Oct. 19, 2026 (GLOBE NEWSWIRE) -- Cedar Works, Inc. today announced "
        "that Maya Rao has joined the Company as Finance Director."
    )
    quote = "Cedar Works, Inc. today announced that Maya Rao has joined the Company"
    source = {"text": text, "publication_date": None}
    assert _date_supported("2026-10-19", source, quote)
    assert not _date_supported("2026-09-21", source, quote)
    page = {
        "text": "Cedar Works today announced a new finance lead.",
        "publication_date": "2026-10-19",
    }
    assert _date_supported("2026-10-19", page, "Cedar Works today announced a new finance lead")
    assert not _date_supported(
        "2026-10-19",
        page | {"publication_date": "2026-11-01"},
        "Cedar Works today announced a new finance lead",
    )


def test_pronoun_after_a_short_lead_in_still_refers_to_the_prospect():
    bundle = deepcopy(FIXTURE_RESPONSE)
    page = bundle["sources"][0]["text"] + " Most recently, he served as Controller of Birch Co."
    bundle["sources"][0]["text"] = page
    bundle["signals"].append(
        {
            "source_id": bundle["sources"][0]["id"],
            "quote": "Most recently, he served as Controller of Birch Co.",
            "company": "Birch Co",
            "person": "Maya Rao",
            "kind": "evergreen",
            "event_key": "",
        }
    )
    result = evaluate(bundle)
    earlier = [s for s in result["context_signals"] if "Birch" in s["quote"]]
    assert earlier and earlier[0]["category"] == "background"


def test_another_persons_event_under_the_same_label_is_not_a_date_conflict():
    """Live case: a departing officer's news filed under the new CFO's event label."""
    bundle = deepcopy(FIXTURE_RESPONSE)
    bundle["sources"].append(
        {**bundle["sources"][1], "id": "other-person", "event_date": "2026-10-16"}
    )
    bundle["signals"].append(
        {
            **bundle["signals"][0],
            "source_id": "other-person",
            "event_date": "2026-10-16",
            "person": "Sam Other",
            "specificity": 0,
        }
    )
    result = evaluate(bundle)
    hook = result["hook"]
    assert hook["strength"] == "strong" and hook["event_date"] == bundle["signals"][0]["event_date"]
    assert not any("conflict" in s["reason"] for s in result["rejected_signals"])


@pytest.mark.parametrize(
    ("supplied", "found", "same"),
    [
        ("Chief People Officer", "Executive Vice President, Chief People Officer", True),
        ("Chief People Officer", "Chief People and Culture Officer", True),
        ("CFO", "EVP, Chief Financial Officer and Treasurer", True),
        ("Chief Information Officer", "SVP & CIO", True),
        ("Finance Director", "Director of Finance", True),
        ("Chief People Officer", "Chief Talent Officer", False),
        ("Chief Financial Officer", "Chief Executive Officer", False),
        ("Controller", "Chief Financial Officer", False),
        ("Chief Data Officer", "Chief Information Officer", False),
    ],
)
def test_titles_match_across_rank_abbreviation_and_fuller_forms(supplied, found, same):
    """Live case: "Chief People Officer" typed, "Executive Vice President, Chief People
    Officer" on the page, treated as a different identity."""
    from outreach.core.workbench_evidence import same_role

    assert same_role(supplied, found) is same
    assert same_role(found, supplied) is same


def _announcement(quality):
    bundle = deepcopy(FIXTURE_RESPONSE)
    quote = "I am pleased to announce that Maya Rao has been appointed to lead invoice review."
    day = bundle["signals"][0]["event_date"]
    bundle["sources"][1].update(text=quote, event_date=None, publication_date=day, quality=quality)
    if quality != "official":
        bundle["sources"][1]["url"] = "https://trade-news.example/cedar-works-appointment"
    bundle["signals"][0].update(quote=quote)
    return evaluate(bundle), day


def test_official_announcement_is_dated_by_the_day_it_was_published():
    """Live case: a company's own "pleased to announce" memo, set aside as undated."""
    result, day = _announcement("official")
    assert result["hook"]["strength"] == "strong" and result["hook"]["event_date"] == day


def test_a_news_site_copy_of_an_announcement_is_not_dated_by_its_publication():
    result, _ = _announcement("reporting")
    assert_no_signal_hook(result)
    assert "Event date" in result["rejected_signals"][0]["reason"]


def test_profile_page_with_name_and_title_on_separate_lines_confirms_identity():
    """Live case: a company bio page; the model quoted only the title line."""
    bundle = deepcopy(FIXTURE_RESPONSE)
    page = bundle["sources"][0]
    page["text"] = (
        "Leadership\n\nMaya Rao\n\nSenior Vice President and Finance Director\n\n"
        "Maya leads supplier payments and the monthly close."
    )
    bundle["identity_candidates"] = [
        {
            **bundle["identity_candidates"][0],
            "source_id": page["id"],
            "role": "Senior Vice President and Finance Director",
            "quote": "Senior Vice President and Finance Director",
        }
    ]
    identity = evaluate(bundle)["identity"]
    assert identity["status"] == "matched"
    assert identity["selected"]["quote"] == "Maya Rao, Senior Vice President and Finance Director"


@pytest.mark.parametrize(
    ("company", "domain", "belongs"),
    [
        ("Yum! Brands", "yum.com", True),
        ("Yum! Brands", "investors.yum.com", True),
        ("Levi Strauss & Co.", "levistrauss.com", True),
        ("General Electric", "ge.com", True),
        ("Cedar Works", "cedar-works.example", True),
        ("BBC", "bbc.co.uk", True),
        ("Yum! Brands", "yummyfoods.com", False),
        ("Acumatica", "peoplematters.in", False),
        ("Northwind Supply", "harborline.example", False),
    ],
)
def test_company_site_is_recognised_when_the_address_is_shorter_than_the_name(
    company, domain, belongs
):
    """Live case: Yum! Brands' own release on yum.com was not accepted as its site."""
    from outreach.core.workbench_evidence import _obvious_domain

    assert _obvious_domain(company, domain) is belongs
