"""Live run view phases and the History dashboard."""

from fastapi.testclient import TestClient

from outreach.web.workbench_view import dashboard, timeline
from outreach.wiring import build_workbench_app
from tests.test_workbench_spine import payload, workbench_settings, settled, start  # noqa: F401


def test_finished_run_has_five_done_phases_in_plain_words(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = settled(client, start(client, payload()))
        phases = timeline(run)
        assert [p["key"] for p in phases] == ["person", "news", "hook", "email", "check"]
        assert all(p["state"] == "done" for p in phases), phases
        labels = [s["label"] for p in phases for s in p["steps"]]
        assert "Confirming it is the right person" in labels
        assert "Choosing the strongest hook" in labels
        assert not any("extract" in label.lower() for label in labels)
        page = client.get("/runs/" + run["id"]).text
        assert "How this run went" in page and "Example mode, no cost" in page


def test_research_only_skips_writing_and_checking(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        run = settled(client, start(client, payload(options="1", use_goal="on")))
        states = {p["key"]: p["state"] for p in timeline(run)}
        assert states["email"] == states["check"] == "skipped"
        assert states["hook"] == "done"


def test_running_run_marks_the_reached_phase_as_current():
    run = {
        "execution_status": "running",
        "prospect": {"name": "Maya Rao"},
        "limits": {"write_draft": 1},
        "campaign": {},
        "stages": [
            {"name": "Save inputs", "status": "completed", "detail": ""},
            {"name": "Identity search", "status": "completed", "detail": ""},
            {"name": "Signal search", "status": "started", "detail": ""},
        ],
    }
    states = {p["key"]: p["state"] for p in timeline(run)}
    assert states == {
        "person": "done",
        "news": "current",
        "hook": "todo",
        "email": "todo",
        "check": "todo",
    }
    steps = timeline(run)[0]["steps"]
    assert steps[-1]["label"] == "Searching the web for Maya"


def test_dashboard_counts_strengths_and_outputs(workbench_settings):  # noqa: F811
    with TestClient(build_workbench_app(workbench_settings)) as client:
        settled(client, start(client, payload()))
        settled(client, start(client, payload(name="Hannah Brooks", company="Ridgeway Components")))
        settled(client, start(client, payload(name="Nobody Known", company="Elsewhere")))
        with client.app.state.open_workbench_store() as db:
            runs = db.list_workbench_runs()
        board = dashboard(runs)
        assert board["counts"]["total"] == 3
        assert board["counts"]["review"] + board["counts"]["attention"] == 3
        assert board["strengths"]["strong"] >= 2 and board["strengths"]["none"] == 1
        assert all(run["first_output"] for run in runs)
        page = client.get("/history").text
        assert "Prospects researched" in page and "How strong the hooks are" in page
        assert "Email: " in page
