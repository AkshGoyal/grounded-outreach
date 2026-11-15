"""Start options: research only (no email, no drafting cost) and research without a goal."""

from fastapi.testclient import TestClient

from outreach.core.workbench import NO_GOAL
from tests.test_workbench_parallel import PublicSources
from tests.test_workbench_research_routes import config, live_app  # noqa: F401
from tests.test_workbench_spine import payload, settled, start


def drafting_calls(fake):
    return [
        body
        for path, body in fake.calls
        if path.endswith("/chat/completions")
        and body["response_format"]["json_schema"]["name"] == "draftoutput"
    ]


def test_research_only_makes_no_drafting_call_and_can_draft_later(config):  # noqa: F811
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        path = start(
            client, payload(live_consent="on", options="1", use_goal="on")
        )  # write_draft left unticked
        run = settled(client, path)
        assert run["limits"]["write_draft"] == 0
        assert run["business_outcome"] == "research_ready" and run["result"]["hook"]
        assert not run["drafts"] and not drafting_calls(fake)
        page = client.get(path).text
        assert "What we found" in page and "Write the draft" in page
        assert client.post(path + "/draft/write", follow_redirects=False).status_code == 303
        assert client.get(path + "/status").json()["draft"]
        assert len(drafting_calls(fake)) == 1


def test_no_goal_researches_any_news_and_never_drafts(config):  # noqa: F811
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        path = start(
            client, payload(live_consent="on", options="1", write_draft="on")
        )  # use_goal left unticked: drafting is switched off with it
        run = settled(client, path)
        assert run["campaign"] == NO_GOAL and run["limits"]["write_draft"] == 0
        assert run["result"]["hook"] and not run["drafts"] and not drafting_calls(fake)
        judgement = run["result"]["hook"]["judgement"]
        assert not any("offer" in item for item in judgement["has"] + judgement["lacks"])
        signal = [body for p, body in fake.calls if p.endswith("/search")][1]
        assert "invoice" not in signal["search_queries"][0].lower()
        page = client.get(path).text
        assert "What we found" in page and "Write the draft" not in page
        refused = client.post(path + "/draft/write")
        assert refused.status_code == 409 and "without a goal" in refused.text


def test_default_form_still_drafts_with_the_goal(config):  # noqa: F811
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        run = settled(
            client,
            start(client, payload(live_consent="on", options="1", use_goal="on", write_draft="on")),
        )
        assert run["limits"]["write_draft"] == 1 and run["draft"]


def test_thorough_covers_four_angles_and_quick_stays_small(config):  # noqa: F811
    thorough_fake, quick_fake = PublicSources(), PublicSources()
    with TestClient(live_app(config, thorough_fake)) as client:
        thorough = settled(
            client,
            start(client, payload(live_consent="on", options="1", use_goal="on", depth="thorough")),
        )
    with TestClient(live_app(config, quick_fake)) as client:
        quick = settled(
            client,
            start(client, payload(live_consent="on", options="1", use_goal="on", depth="quick")),
        )
    assert thorough["limits"]["thorough"] == 1 and quick["limits"]["thorough"] == 0

    def searches(fake):
        return [q for p, b in fake.calls if p.endswith("/search") for q in b["search_queries"]]

    t, q = searches(thorough_fake), searches(quick_fake)
    assert any("hiring" in x for x in t) and any("funding" in x for x in t)
    assert not any("hiring" in x for x in q)
    # The fake sources hold one fact, so thorough looks once more; quick does not.
    assert thorough["usage"]["followups"] > quick["usage"]["followups"]
    assert thorough["usage"]["search_requests"] > quick["usage"]["search_requests"]
    assert quick["result"]["hook"] and thorough["result"]["hook"]


def test_one_visible_choice_sets_goal_and_email(config):  # noqa: F811
    """The start page sends one choice; each maps to the goal and email settings."""
    fake = PublicSources()
    with TestClient(live_app(config, fake)) as client:
        page = client.get("/research/new").text
        assert 'name="purpose" value="email" checked' in page and "data-cost-line" in page
        assert "About $0.020" in page and "can never cost more than $0.05" in page
        expected = {"email": (False, 1), "goal": (False, 0), "none": (True, 0)}
        for purpose, (no_goal, write_draft) in expected.items():
            run = settled(
                client, start(client, payload(live_consent="on", options="1", purpose=purpose))
            )
            assert (run["campaign"] == NO_GOAL) is no_goal
            assert run["limits"]["write_draft"] == write_draft
