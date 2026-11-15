"""Many prospects in one go: one goal, one authorization, one run and one review each."""

import re
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from outreach.core.workbench import parse_prospects
from outreach.wiring import build_workbench_app
from tests.test_workbench_parallel import PublicSources
from tests.test_workbench_research_routes import config, live_app  # noqa: F401
from tests.test_workbench_review import approve
from tests.test_workbench_spine import workbench_settings  # noqa: F401

LIST = (
    "Name\tCompany\tTitle\n"
    "Maya Rao\tCedar Works\tFinance Director\n"
    "Hannah Brooks, Ridgeway Components, Finance Director\n"
    'Nobody Known, "Elsewhere, Inc.", https://elsewhere.example\n'
    "Maya Rao, Cedar Works\n"
)


def list_path(client, landing):
    """A list lands on its first prospect; the whole list is linked from that page."""
    assert landing.startswith("/runs/")
    return re.search(r"/batches/[0-9a-f-]+", client.get(landing).text).group(0)


def finished(client, batch_path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        runs = client.get(batch_path + "/status").json()["runs"]
        if all(run["execution_status"] not in ("queued", "running") for run in runs):
            return runs
        time.sleep(0.02)
    raise AssertionError("The batch did not finish.")


def test_pasted_rows_are_parsed_deduplicated_and_validated():
    prospects, errors = parse_prospects(LIST)
    assert not errors
    assert [p["name"] for p in prospects] == ["Maya Rao", "Hannah Brooks", "Nobody Known"]
    assert prospects[2]["company"] == "Elsewhere, Inc."
    assert (
        prospects[2]["website"].startswith("https://elsewhere.example") and not prospects[2]["role"]
    )
    _, errors = parse_prospects("Only A Name\nX, javascript:alert(1), Role, javascript:alert(1)")
    assert "Line 1" in errors[0]
    many, errors = parse_prospects("\n".join(f"Person {n}, Company {n}" for n in range(21)))
    assert len(many) == 21 and "up to 20" in errors[-1]


def test_example_batch_runs_each_prospect_and_reviews_stay_individual(workbench_settings):  # noqa: F811
    app = build_workbench_app(workbench_settings)
    with TestClient(app) as client:
        page = client.get("/batch/new").text
        assert "Many at once" in page and "Maya Rao, Cedar Works, Finance Director" in page
        request_id = str(uuid4())
        response = client.post(
            "/batch", data={"request_id": request_id, "prospects": LIST}, follow_redirects=False
        )
        assert response.status_code == 303
        landing = response.headers["location"]
        batch_path = list_path(client, landing)
        runs = finished(client, batch_path)
        assert len(runs) == 3 and landing == "/runs/" + runs[0]["id"]
        assert [r["business_outcome"] for r in runs] == [
            "ready_for_review",
            "needs_revision",
            "ready_for_review",
        ]
        # Submitting the same form again opens the same batch and starts nothing new.
        again = client.post(
            "/batch", data={"request_id": request_id, "prospects": LIST}, follow_redirects=False
        )
        assert again.headers["location"] == landing
        with app.state.open_workbench_store() as db:
            assert len(db.list_workbench_runs()) == 3
        page = client.get(batch_path).text
        assert "Research finished. 3 to go through." in page
        assert "Review the next draft" in page and "Not personalised" in page
        assert 'http-equiv="refresh"' not in page
        assert client.get(batch_path + "/export").status_code == 409
        first = "/runs/" + runs[0]["id"]
        run_page = client.get(first).text
        assert "data-batch-nav" in run_page and "1 of 3" in run_page
        # Every prospect in the list is one click away, each with its own state.
        assert all(f'href="/runs/{r["id"]}" class="batch-step' in run_page for r in runs)
        assert run_page.count('aria-current="page"') >= 1 and "is-attention" in run_page
        assert f'href="/runs/{runs[1]["id"]}" data-batch-next' in run_page
        draft = client.get(first + "/status").json()["draft"]
        assert approve(client, first, draft).status_code == 303
        exported = client.get(batch_path + "/export")
        assert exported.status_code == 200 and exported.text.count("Subject:") == 1
        assert "To: Maya Rao, Cedar Works" in exported.text
        assert "Download 1 approved email" in client.get(batch_path).text
        assert client.get("/batches/missing").status_code == 404
        assert "3 prospects" in client.get("/batch/new").text


def test_live_batch_needs_one_explicit_authorization_and_uses_the_goal(config):  # noqa: F811
    fake = PublicSources()
    app = live_app(config, fake)
    with TestClient(app) as client:
        page = client.get("/batch/new").text
        assert "can never cost more than $0.05 each" in page
        assert 'name="live_consent" required' in page
        data = {"request_id": str(uuid4()), "prospects": "Maya Rao, Cedar Works, Finance Director"}
        refused = client.post("/batch", data=data)
        assert refused.status_code == 422 and "authorize this batch" in refused.text
        assert "Maya Rao, Cedar Works, Finance Director" in refused.text and not fake.calls
        bad = client.post("/batch", data=data | {"prospects": "Just A Name", "live_consent": "on"})
        assert bad.status_code == 422 and "Line 1" in bad.text and not fake.calls
        response = client.post("/batch", data=data | {"live_consent": "on"}, follow_redirects=False)
        assert response.status_code == 303
        runs = finished(client, list_path(client, response.headers["location"]))
        assert [r["business_outcome"] for r in runs] == ["ready_for_review"]
        saved = client.get("/runs/" + runs[0]["id"] + "/status").json()
        assert saved["mode"] == "live" and saved["usage"]["spent_micro"] <= 50000
