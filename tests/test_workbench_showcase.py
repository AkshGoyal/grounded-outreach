"""The hosted app starts from the evaluation's real runs instead of an empty History."""

import re

from fastapi.testclient import TestClient

from outreach.config import Settings
from outreach.workbench import SHOWCASE, seed_showcase
from outreach.wiring import build_workbench_app


def hosted_app(tmp_path):
    assert seed_showcase(tmp_path)
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "workbench.db"),
        parallel_api_key="fictional",
        openrouter_api_key="fictional",
    )
    return build_workbench_app(settings, mode="live", daily_budget_usd=0.5)


def test_empty_hosted_folder_starts_with_fifteen_reviewable_runs(tmp_path):
    with TestClient(hosted_app(tmp_path)) as client:
        history = client.get("/history").text
        assert history.count('class="showcase-tag"') == 15
        ids = re.findall(r'href="/runs/([0-9a-f]+)"', history)
        assert len(set(ids)) == 15
        for run_id in set(ids):
            saved = client.get(f"/runs/{run_id}/status").json()
            assert saved["execution_status"] == "completed" and saved["draft"]
            # Saved evidence still matches the email: nothing reads as stale.
            assert saved["review"]["state"] == "ready_for_review", (run_id, saved["review"])
            assert client.get(f"/runs/{run_id}").status_code == 200


def test_seed_never_overwrites_and_carries_no_contact_details(tmp_path):
    (tmp_path / "workbench.db").write_bytes(b"existing")
    assert not seed_showcase(tmp_path)
    assert (tmp_path / "workbench.db").read_bytes() == b"existing"
    text = SHOWCASE.read_bytes().decode("utf-8", "ignore")
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    assert not re.search(r"sk-or-v1-|x-api-key|Bearer [A-Za-z0-9]{20,}", text)


def test_showcase_spend_does_not_use_up_todays_cap(tmp_path):
    app = hosted_app(tmp_path)
    with app.state.open_workbench_store() as db:
        assert db.showcase_ids() and len(db.showcase_ids()) == 15
        total = db.conn.execute("SELECT SUM(charged_micro) FROM research_calls").fetchone()[0]
        assert total > 300000  # about $0.31 of evaluation spend is in the copy
        db.conn.execute("UPDATE research_calls SET created_at=datetime('now')")
        counted = db.conn.execute(
            "SELECT COALESCE(SUM(charged_micro),0) FROM research_calls WHERE "
            "substr(created_at,1,10)=substr(datetime('now'),1,10) "
            "AND run_id NOT IN (SELECT run_id FROM workbench_showcase)"
        ).fetchone()[0]
        assert counted == 0


def test_contact_block_titles_are_replaced_by_a_plain_name():
    from outreach.adapters.workbench_research import clean_title

    pdf = "https://www.example.com/press/release.pdf"
    assert clean_title("Media Contact: Jane Roe (415) 555-0100", pdf) == "example.com PDF document"
    assert clean_title("Investor contacts: ir@example.com", "https://example.com/news") == (
        "example.com page"
    )
    assert clean_title("Example names a new CFO", pdf) == "Example names a new CFO"


def test_saved_results_carry_no_phone_numbers_or_emails():
    from outreach.web.workbench_eval import HERE

    raw = (HERE / "workbench_results.json").read_text()
    assert not re.search(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", raw)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw)


def test_wrong_password_is_shown_on_the_field_with_tries_left(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "workbench.db"),
        app_password="right-password-for-tests",
    )
    with TestClient(build_workbench_app(settings)) as client:
        first = client.post("/login", data={"password": "nope"})
        assert first.status_code == 401
        assert 'aria-invalid="true"' in first.text and "isn't right" in first.text
        assert "tries left" not in first.text  # no countdown until it matters
        for _ in range(2):
            later = client.post("/login", data={"password": "nope"})
        assert "2 tries left before a one-minute pause" in later.text
        client.post("/login", data={"password": "nope"})
        last = client.post("/login", data={"password": "nope"})
        assert "0 tries left" in last.text
        locked = client.post("/login", data={"password": "right-password-for-tests"})
        assert locked.status_code == 429 and "Too many wrong tries" in locked.text


def test_sign_in_survives_a_restart_and_ends_when_the_password_changes(tmp_path):
    def app(password):
        return build_workbench_app(
            Settings(_env_file=None, db_path=str(tmp_path / "workbench.db"), app_password=password)
        )

    with TestClient(app("first-password-1")) as client:
        assert client.post("/login", data={"password": "first-password-1"}).status_code == 200
        cookie = client.cookies.get("outreach_session")
    with TestClient(app("first-password-1"), cookies={"outreach_session": cookie}) as client:
        assert client.get("/history", follow_redirects=False).status_code == 200
    with TestClient(app("second-password-2"), cookies={"outreach_session": cookie}) as client:
        assert client.get("/history", follow_redirects=False).status_code == 303
