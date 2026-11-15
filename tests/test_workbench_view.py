"""The results page data: every claim marked and numbered; findings ranked."""

from fastapi.testclient import TestClient

from outreach.web.workbench_view import annotate, findings, references
from outreach.wiring import build_workbench_app
from tests.test_workbench_spine import payload, workbench_settings, settled, start  # noqa: F401


def finished(client, **changes):
    return settled(client, start(client, payload(**changes)))


def test_email_pieces_rebuild_the_body_and_carry_meaning(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client)
        view = annotate(run)
        assert "".join(p["text"] for p in view["body"]) == run["draft"]["body"]
        kinds = {p["kind"] for p in view["body"]}
        # Coloured by the relevance the writer gave each sentence while drafting.
        assert {"core", "goal", "optional"} <= kinds and "block" not in kinds
        numbered, listing = references(run)
        hook_source = run["result"]["hook"]["source_ids"][0]
        assert numbered[hook_source] == "1" and listing[0]["id"] == hook_source
        facts = [p for p in view["body"] if p["kind"] == "core"]
        assert all(p["refs"] for p in facts) and "G" in {r for p in view["body"] for r in p["refs"]}


def test_overclaim_is_marked_as_blocking_with_its_reason(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client, name="Hannah Brooks", company="Ridgeway Components")
        blocked = [p for p in annotate(run)["body"] if p["kind"] == "block"]
        assert blocked and all(p["note"] for p in blocked)


def test_findings_rank_the_hook_first_and_explain_what_was_not_used(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(
            client,
            name="Daniel Okafor",
            company="Larkspur Health",
            role="Controller",
            options="1",
            use_goal="on",
        )
        items = findings(run)
        assert items[0]["label"] in ("Strong hook", "Good hook") and items[0]["ref"] == "1"
        assert any(i["label"] == "Not used" and i["why"] for i in items)
        assert len({i["text"] for i in items}) == len(items)


def test_facts_group_into_chosen_extra_and_set_aside(workbench_settings):  # noqa: F811
    from outreach.web.workbench_view import facts

    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client, name="Daniel Okafor", company="Larkspur Health", role="Controller")
        groups = facts(run)
        assert groups["chosen"][0]["locked"] and groups["chosen"][0]["in_email"]
        assert groups["set_aside"] and all(f["why"] for f in groups["set_aside"])
        page = client.get("/runs/" + run["id"]).text
        assert "Chosen" in page and "Set aside" in page and "In the email" in page
        assert "Rewrite with the ticked facts" in page


def test_ticked_context_fact_reaches_the_draft_context():
    from outreach.adapters.workbench_fixture import FixtureResearchProvider
    from outreach.core.workbench import DEMO_CAMPAIGN, run_pipeline
    from outreach.core.workbench_claims import draft_context

    prospect = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"}
    result = run_pipeline(prospect, DEMO_CAMPAIGN, FixtureResearchProvider(), lambda *a: None)
    result["context_signals"] = [
        {
            "source_id": "extra-page",
            "quote": "Cedar Works opened a new office in Leeds.",
            "category": "context",
        }
    ]
    base = {"result": result, "campaign": DEMO_CAMPAIGN, "prospect": prospect}
    assert "extra-page" not in draft_context(base)["supports"]
    assert "extra-page" in draft_context(base | {"include": ["extra-page"]})["supports"]


def test_remove_optional_sentences_in_one_click(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client)
        path = "/runs/" + run["id"]
        optional = [
            s for s in run["draft"]["check"]["segments"] if s.get("relevance") == "optional"
        ]
        assert optional and "Remove it" in client.get(path).text
        response = client.post(
            path + "/draft/check",
            data={"base_revision": run["draft"]["revision"], "remove_optional": "1"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        after = client.get(path + "/status").json()["draft"]
        assert after["revision"] == run["draft"]["revision"] + 1
        assert all(s["text"] not in after["body"] for s in optional)
        assert after["check"]["ok"]
        relevances = {s.get("relevance") for s in after["check"]["segments"]}
        assert "core" in relevances and "optional" not in relevances


def test_subject_that_sums_up_the_hook_inherits_its_source(workbench_settings):  # noqa: F811
    from outreach.core.workbench_claims import draft_context, terms, validate_draft

    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client)
        core = next(c for c in run["draft"]["claims"] if c.get("relevance") == "core")
        # Two of the opener's words, none of the source's exact phrasing beyond them.
        words = [w for w in core["text"].split() if w.strip(",.").lower() in terms(core["text"])]
        subject = "A note on " + " ".join(w.strip(",.") for w in words[:2])
        check = validate_draft({**run["draft"], "subject": subject}, draft_context(run))
        head = check["segments"][0]
        assert head["part"] == "subject" and head["support_ids"] == [core["support_id"]]
        assert head["relevance"] == "core" and not head["issues"]


def test_blocking_sentence_can_be_removed_from_the_problem_box(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client, name="Hannah Brooks", company="Ridgeway Components")
        page = client.get("/runs/" + run["id"]).text
        box = page.split('aria-label="Sentences to fix"', 1)[1].split("</ul>", 1)[0]
        assert "data-remove-blocking" in box and "Remove this sentence" in box


def test_a_sentence_is_edited_or_removed_where_it_stands(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client)
        path = "/runs/" + run["id"]
        page = client.get(path).text
        assert "data-sentence-editor" in page and page.count("data-sentence ") >= 3
        pitch = next(c for c in run["draft"]["claims"] if c.get("relevance") == "offer")
        new_text = pitch["text"].replace("can review", "reviews")
        assert new_text != pitch["text"]
        saved = client.post(
            path + "/draft/check",
            data={
                "base_revision": run["draft"]["revision"],
                "replace": pitch["text"],
                "replacement": new_text,
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303
        after = client.get(path + "/status").json()["draft"]
        assert new_text in after["body"] and pitch["text"] not in after["body"]
        # The edited sentence keeps its source and its rating; only the wording changed.
        edited = next(s for s in after["check"]["segments"] if s["text"] == new_text)
        assert edited["relevance"] == "offer" and pitch["support_id"] in edited["support_ids"]
        assert after["check"]["ok"]
        gone = client.post(
            path + "/draft/check",
            data={"base_revision": after["revision"], "replace": new_text, "remove_it": "1"},
            follow_redirects=False,
        )
        assert gone.status_code == 303
        final = client.get(path + "/status").json()["draft"]
        assert new_text not in final["body"] and final["revision"] == after["revision"] + 1


def test_one_start_page_with_a_mode_and_versioned_assets(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        one, many = client.get("/research/new").text, client.get("/batch/new").text
        for page in (one, many):
            assert 'class="mode-tabs"' in page and "One prospect" in page
            assert "Many at once" in page and "<h1>New prospect</h1>" in page
            assert "/static/workbench.css?v=" in page and "/static/workbench.js?v=" in page
        assert 'href="/research/new" aria-current="page"' in one
        assert 'href="/batch/new" aria-current="page"' in many
        # The side bar has one entry for starting research, not two.
        side = one.split('class="side-nav"', 1)[1].split("</nav>", 1)[0]
        assert "/batch/new" not in side


def test_model_email_gets_blank_lines_between_paragraphs():
    from outreach.core.workbench_draft import DraftOutput

    body = (
        "Hi John,\nFirst paragraph here.\nSecond paragraph here.\nA question?\nBest,\nAlex Morgan"
    )
    tidy = DraftOutput(subject="A subject", body=body).body
    assert tidy == (
        "Hi John,\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nA question?\n\n"
        "Best,\nAlex Morgan"
    )
    assert DraftOutput(subject="A subject", body=tidy).body == tidy


def test_often_counts_as_caution_for_a_general_observation():
    from outreach.core.workbench_claims import HEDGES

    assert HEDGES.search("a new finance chief often starts by looking at how the close runs")
    assert not HEDGES.search("your team is behind on the close")


def test_sender_meta_goal_terms_and_probably_do_not_block(workbench_settings):  # noqa: F811
    """From the evaluation: a good email was blocked by four false alarms."""
    from outreach.core.workbench_claims import draft_context, validate_draft

    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = finished(client)
        context, draft = draft_context(run), run["draft"]

        def check(extra):
            body = draft["body"].replace("\n\nWould a short", f"\n\n{extra}\n\nWould a short")
            assert extra in body
            return validate_draft({**draft, "body": body}, context)

        for fine in (
            "That's why I'm writing.",
            "I'm writing because ClearLedger Demo could help.",
            "Each exception is probably something your team sees.",
        ):
            assert check(fine)["ok"], (fine, check(fine)["errors"])
        for bad in (
            "Your invoices are late because of errors.",
            "Your team is clearly behind.",
        ):
            assert not check(bad)["ok"], bad


def test_just_as_much_is_not_a_recency_claim():
    from outreach.core.workbench_claims import _RECENT

    assert not _RECENT.search("the first morning could matter just as much to your team")
    assert _RECENT.search("you just joined the company") and _RECENT.search("a recent move")


def test_leading_a_team_is_not_a_boast_but_a_leading_provider_is():
    import re

    from outreach.core.workbench_claims import _RISKY

    outcome = next(pattern for category, pattern, _ in _RISKY if category == "outcome")
    assert not re.search(outcome, "leading global it and cloud operations may mean a lot")
    assert re.search(outcome, "we are a leading provider of invoice review")
    assert re.search(outcome, "the market-leading tool")
