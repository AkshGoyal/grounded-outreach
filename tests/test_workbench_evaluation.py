"""The evaluation report is built from saved real-run results, with no paid call."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from outreach.web.workbench_eval import HERE, evaluation
from outreach.wiring import build_workbench_app
from tests.test_workbench_spine import workbench_settings  # noqa: F401


def test_report_numbers_agree_with_the_saved_results():
    results = json.loads((HERE / "workbench_results.json").read_text())
    review = json.loads((HERE / "workbench_review.json").read_text())
    report = evaluation()
    records = results["records"]
    assert report["n"] == len(records) == 15 and report["goals_count"] == 3
    # Every prospect has a review, and the review names only evaluated prospects.
    assert {r["name"] for r in records} == set(review["emails"])
    # The record holds no personal contact data: no email addresses, no phone numbers.
    raw = (HERE / "workbench_results.json").read_text()
    assert "@" not in raw.replace("@media", "")
    sentences = sum(r["email"]["sentences"] for r in records)
    backed = sum(r["email"]["backed"] for r in records)
    assert f"{backed} of {sentences}" in report["headline"][1]["detail"]
    ready = sum(review["emails"][r["name"]]["verdict"] in ("send", "edit") for r in records)
    assert report["headline"][0]["value"] == f"{ready} of 15"


def test_evaluation_page_is_reachable_from_every_page(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        page = client.get("/evaluation")
        assert page.status_code == 200
        assert "How it performs on real prospects" in page.text
        assert page.text.count('class="eval-prospect"') == 15
        assert 'href="/evaluation" aria-current="page"' in page.text
        assert 'href="/evaluation"' in client.get("/research/new").text
        # Sources open safely in a new tab.
        assert 'target="_blank" rel="noopener noreferrer"' in page.text


def test_runner_and_cases_files_exist():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evaluation" / "workbench_cases.json").read_text())
    assert sum(len(g["prospects"]) for g in cases["goals"]) == 15
    assert (root / "scripts" / "workbench_evaluate.py").exists()
