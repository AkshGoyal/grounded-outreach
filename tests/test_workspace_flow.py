"""Audience deletion, saved-state guidance and broader evidence-backed research."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from outreach.core.discovery import checked_candidates
from outreach.core.research import Assessment, Candidates, published_emails
from outreach.core.research_flow import run_research
from outreach.web.app import create_app
from tests.test_audience_intake import complete
from tests.test_platform import PLAN, SOURCE, db_for
from tests.test_research_recovery import saved_zero_result


@pytest.fixture
def flow_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(
        settings,
        research_api=lambda *args: pytest.fail("No provider request authorized"),
        mailbox=lambda *args: pytest.fail("No mail operation authorized"),
    )
    client = TestClient(app)
    response = client.post("/research/intake", data=complete(), follow_redirects=False)
    key = response.headers["location"].split("?")[0].rsplit("/", 1)[-1]
    return settings, app, client, key


def test_delete_researched_audience_hides_and_restores_without_erasing_history(flow_workspace):
    config, app, client, key = flow_workspace
    saved_zero_result(config, key)
    client.post(f"/research/{key}/recover-discovery")
    with db_for(config) as db:
        calls = db.rows("SELECT * FROM research_calls")
        leads = db.leads(key)
        original = db.run(key)
        db.save_campaign("keep", "Keep", None, "sales", "", None)
        db.link_research("keep", key)
    route = f"/workspace/audience/{key}/remove"
    page = client.get(route).text
    assert "Delete audience" in page and "Deleted audiences" in page
    assert (
        client.post(route, data={"action": "delete", "deletion_version": "trash-v1"}).status_code
        == 409
    )
    response = client.post(
        route,
        data={
            "action": "delete",
            "deletion_version": "trash-v1",
            "confirm_delete": "yes",
        },
    )
    assert "Audience deleted from active work" in response.text
    with db_for(config) as db:
        assert db.run(key)["deleted"] and not db.runs()
        assert db.rows("SELECT * FROM research_calls") == calls and db.leads(key) == leads
        assert db.research_campaign(key)["id"] == "keep"
        assert db.run(key)["plan_json"] == original["plan_json"]
    assert not app.state.research.start(key)
    assert "Restore this audience" in client.post(f"/research/{key}/resume").text
    assert f'href="/research/{key}"' not in client.get("/research").text
    assert f'href="/research/{key}"' in client.get("/research?view=deleted").text
    client.post(route, data={"action": "restore"})
    with db_for(config) as db:
        assert not db.run(key)["deleted"] and db.run(key)["status"] == "paused"
        assert db.rows("SELECT * FROM research_calls") == calls
    assert not app.state.research.active


def test_deleted_work_cannot_be_edited_in_place_or_recovered(flow_workspace):
    config, app, client, key = flow_workspace
    saved_zero_result(config, key)
    client.post(
        f"/workspace/audience/{key}/remove",
        data={
            "action": "delete",
            "deletion_version": "trash-v1",
            "confirm_delete": "yes",
        },
    )
    client.post(f"/research/{key}/recover-discovery")
    with db_for(config) as db:
        assert not db.leads(key)
    page = client.get(f"/research/{key}").text
    assert "Restore this audience" in page
    assert 'action="/research/' + key + '/resume"' not in page


@pytest.mark.parametrize(
    "status,expected",
    [
        ("draft", "Continue to planning"),
        ("awaiting_approval", "Review and approve your plan"),
        ("paused", "Continue approved research"),
        ("completed", "Broaden the audience"),
    ],
)
def test_saved_state_gives_a_specific_next_action(flow_workspace, status, expected):
    config, app, client, key = flow_workspace
    with db_for(config) as db:
        values = {"status": status}
        if status in ("awaiting_approval", "paused"):
            values["plan_json"] = json.dumps(PLAN)
        if status == "paused":
            values["approved_at"] = "2026-10-07"
        db.set_run(key, **values)
    page = client.get(f"/research/{key}").text
    assert expected in page and "WHERE YOU ARE" in page
    assert "Complete Outreach Tool" in page
    assert "AUDIENCE " + key[:6] in page


def test_uncertain_resume_does_not_start_worker_or_repeat_requests(flow_workspace):
    config, app, client, key = flow_workspace
    with db_for(config) as db:
        db.conn.execute("DELETE FROM research_execution WHERE run_id=?", (key,))
        db.set_run(key, status="running", approved_at="2026-10-07", plan_json=json.dumps(PLAN))
        db.reserve(key, "uncertain", "fingerprint", 1000, 5000000)
        db.set_run(key, status="failed")
        calls = db.rows("SELECT * FROM research_calls")
    assert "Check the previous request" in client.get(f"/research/{key}").text
    assert "uncertain outcome" in client.post(f"/research/{key}/resume").text
    assert not app.state.research.active
    with db_for(config) as db:
        assert db.rows("SELECT * FROM research_calls") == calls


@pytest.mark.parametrize(
    "published",
    [
        "hello@mills.example",
        "hello [at] mills [dot] example",
        "hello (at) mills (dot) example",
        "hello&#64;mills.example",
    ],
)
def test_explicit_email_formats_keep_original_source_quote(published):
    text = "Contact the company at " + published + " for business enquiries."
    emails = published_emails(
        [
            {
                "url": "https://mills.example/contact",
                "text": text,
                "retrieved_at": "2026-10-07",
            }
        ],
        "https://mills.example/",
    )
    assert len(emails) == 1 and emails[0]["value"] == "hello@mills.example"
    assert emails[0]["published_value"] == published and published in emails[0]["quote"]
    assert not published_emails(
        [
            {
                "url": "https://other.example/contact",
                "text": text,
                "retrieved_at": "",
            }
        ],
        "https://mills.example/",
    )


def test_long_page_without_email_finishes_promptly():
    start = time.monotonic()
    assert not published_emails(
        [
            {
                "url": "https://mills.example/",
                "text": "a" * 100000,
                "retrieved_at": "",
            }
        ],
        "https://mills.example/",
    )
    assert time.monotonic() - start < 2


def test_short_exact_company_name_is_supported_but_substring_is_not():
    def answer(name):
        return Candidates(
            candidates=[
                {
                    "company": name,
                    "website": "https://mills.example/",
                    "source_id": "s1",
                    "identity_quote": name,
                }
            ]
        )

    source = [
        {
            "url": "https://mills.example/",
            "text": "Acme builds software.",
            "title": "",
            "retrieved_at": "",
        }
    ]
    assert checked_candidates(source, answer("Acme"))[0]
    assert not checked_candidates(source, answer("cme"))[0]


@pytest.mark.parametrize("mode", ["focused", "flexible"])
def test_official_search_email_is_kept_when_extract_omits_it(flow_workspace, mode):
    config, app, client, key = flow_workspace
    client.post(f"/research/{key}/intake", data=complete() | {"research_mode": mode, "target": "1"})

    class LocalAPI:
        def __init__(self):
            self.contact_queries = []
            self.urls = []

        def search(self, call, objective, queries):
            if "contact-search" in call:
                self.contact_queries = queries
                return {"results": [SOURCE]}
            return {"results": [SOURCE]}

        def extract(self, call, urls):
            self.urls = urls
            return {
                "results": [SOURCE | {"full_content": "Example Mills makes textiles in Tiruppur."}]
            }

        def generate(self, call, prompt, schema):
            if schema is Candidates:
                return Candidates(
                    candidates=[
                        {
                            "company": "Example Mills",
                            "website": SOURCE["url"],
                            "source_id": "s1",
                            "identity_quote": "Example Mills makes textiles",
                        }
                    ]
                )
            return Assessment(
                facts=[
                    {
                        "criterion_index": 1,
                        "status": "supported",
                        "source_id": "s1",
                        "quote": "Example Mills makes textiles in Tiruppur.",
                    }
                ],
                fit_summary="Textile manufacturer",
                unknowns=[],
            )

    api = LocalAPI()
    with db_for(config) as db:
        # Preserve regression coverage for the original approved engine.
        db.conn.execute("DELETE FROM research_execution WHERE run_id=?", (key,))
        db.set_run(key, status="running", approved_at="2026-10-07", plan_json=json.dumps(PLAN))
        run_research(db, api, key)
        lead = db.leads(key)[0]
        assert lead["emails"][0]["value"] == "sales@mills.example"
        assert "Contact sales@mills.example" in lead["emails"][0]["quote"]
        assert any("Contact sales@mills.example" in source["text"] for source in lead["sources"])
        assert len(api.contact_queries) == (3 if mode == "flexible" else 1)
        assert db.run(key)["status"] == "completed" and not db.rows("SELECT * FROM research_calls")
