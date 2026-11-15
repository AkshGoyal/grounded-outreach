"""Research results stay usable ahead of diagnostics without weakening consent."""

import pytest

from tests.test_audience_intake import complete
from tests.test_platform import db_for, saved_lead
from tests.test_research_continuity import revision
from tests.test_research_continuity import workspace as workspace


def add_result(config, key):
    with db_for(config) as db:
        lead = saved_lead(db)
        db.conn.execute("UPDATE research_leads SET run_id=? WHERE id=?", (key, lead))
    return lead


def test_partial_results_come_before_details_and_next_action_uses_inline_selection(workspace):
    config, app, client, key = workspace
    add_result(config, key)
    with db_for(config) as db:
        db.set_run(key, status="paused")
    page = client.get(f"/research/{key}").text
    assert page.index('id="contact-review"') < page.index('id="research-details"')
    assert page.index('id="contact-review"') < page.index("RESEARCH HISTORY")
    assert f'href="/research/{key}?stage=all#contact-review"' in page
    assert "Use this audience →" not in page
    assert page.count('data-summary="email_count"') == 1
    assert page.count('data-summary="with_email"') == 1
    assert 'id="research-details" >' in page
    assert not app.state.research.active


@pytest.mark.parametrize("current_results", [False, True])
def test_prior_version_results_keep_working_handoff_link(workspace, current_results):
    config, _, client, key = workspace
    add_result(config, key)
    latest = revision(client, key)
    if current_results:
        add_result(config, latest)
    page = client.get(f"/research/{latest}").text
    assert f'href="/research/{latest}/use"' in page
    assert "Add emails to a campaign" in page


def test_plan_approval_precedes_diagnostics_and_remains_explicit(workspace):
    config, app, client, key = workspace
    page = client.post(f"/research/{key}/intake", data=complete() | {"action": "plan_local"}).text
    assert page.index('id="plan-review"') < page.index('id="research-details"')
    assert 'name="confirm" required' in page
    with db_for(config) as db:
        assert not db.run(key)["approved_at"]
        assert not db.rows("SELECT * FROM research_calls")
    assert not app.state.research.active


def test_active_partial_results_keep_progress_pause_and_selection(workspace):
    config, app, client, key = workspace
    lead = add_result(config, key)
    with db_for(config) as db:
        db.set_run(key, status="running")
    app.state.research.active.add(key)
    try:
        page = client.get(f"/research/{key}").text
        assert page.index('id="live-progress"') < page.index('id="contact-review"')
        assert "data-research-pause" in page
        assert f'name="lead_ids" value="{lead}"' in page
        assert page.index('id="contact-review"') < page.index('id="research-details"')
    finally:
        app.state.research.active.discard(key)


def test_uncertain_request_stays_prominent_and_has_no_resume_action(workspace):
    config, _, client, key = workspace
    client.post(f"/research/{key}/intake", data=complete() | {"action": "plan_local"})
    add_result(config, key)
    with db_for(config) as db:
        db.set_run(key, status="running", approved_at="2026-10-09T00:00:00Z")
        db.reserve(key, "uncertain", "fixed-fingerprint", 1000, 5000000)
        db.set_run(key, status="paused")
    page = client.get(f"/research/{key}").text
    assert page.index("Check the previous request") < page.index('id="contact-review"')
    assert f'action="/research/{key}/resume"' not in page
    assert 'id="research-details" open' in page
    assert "sales@mills.example" in page
