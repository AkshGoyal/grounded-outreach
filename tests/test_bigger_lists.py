"""What changes when the list gets bigger than seven.

Every test here is something that works fine on a handful of contacts and
breaks, or becomes unreadable, on a few dozen.
"""

import re

import pytest

from outreach.cli import main
from outreach.core.drafting import Draft, DraftSentence
from outreach.core.importing import build_report, grouped_problems, plan_columns
from tests.fakes.llm import FakeLLM

# --- the import preview stays readable --------------------------------------


def test_identical_rejections_are_grouped_into_one_line():
    rows = [{"Company": f"C{i}", "Email": "Not published"} for i in range(36)]
    rows.append({"Company": "Odd", "Email": "broken.example"})
    groups = grouped_problems(build_report(rows, plan=plan_columns(rows)))
    assert len(groups) == 2, "36 identical rejections become one line, plus the odd one"
    status, reason, count, where = groups[0]
    assert count == 36 and "Not published" in reason
    assert where == "2–37", "consecutive rows shown as a range"


def test_scattered_rows_are_listed_compactly():
    rows = [
        {"Company": "a", "Email": "Not published"},
        {"Company": "b", "Email": "b@b.example"},
        {"Company": "c", "Email": "Not published"},
        {"Company": "d", "Email": "Not published"},
    ]
    [(_, _, count, where)] = grouped_problems(build_report(rows, plan=plan_columns(rows)))
    assert count == 3 and where == "2, 4–5"


# --- drafting a bigger list -------------------------------------------------


@pytest.fixture
def forty(monkeypatch, tmp_path):
    """A campaign of forty contacts, with campaign copy and a fake model."""
    import os

    for name in list(os.environ):
        if name.startswith("OUTREACH_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    for name, value in {
        "DB_PATH": str(tmp_path / "x.db"),
        "OPENROUTER_API_KEY": "sk-or-test",
        "SENDER_NAME": "Aksh Goyal",
        "SENDER_EMAIL": "aksh@example.com",
    }.items():
        monkeypatch.setenv(f"OUTREACH_{name}", value)

    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "big.md").write_text("Star Threads makes RFD cotton thread.")
    sheet = tmp_path / "forty.csv"
    sheet.write_text(
        "Company,Email,City\n"
        + "".join(f"Mill {i},buyer{i}@mill{i}.example,Ludhiana\n" for i in range(40))
    )
    assert main(["import", str(sheet), "--campaign", "big", "--commit"]) == 0

    draft = Draft(subject="RFD thread", sentences=[DraftSentence(text="Hello.")])
    monkeypatch.setattr("outreach.cli.build_llm", lambda s, m=None: FakeLLM([draft] * 200))
    monkeypatch.setattr("outreach.web.app.build_llm", lambda s, m=None: FakeLLM([draft] * 200))
    return tmp_path


def _drafts(tmp_path):
    from outreach.adapters.db import connect

    return connect(tmp_path / "x.db").execute("SELECT COUNT(*) FROM drafts").fetchone()[0]


def test_saving_drafts_every_contact_not_just_three(forty):
    assert main(["draft", "--campaign", "big", "--save"]) == 0
    assert _drafts(forty) == 40


def test_running_it_again_does_not_create_duplicates(forty, capsys):
    main(["draft", "--campaign", "big", "--save"])
    main(["draft", "--campaign", "big", "--save"])
    assert _drafts(forty) == 40
    assert "already has a draft" in capsys.readouterr().out


def test_new_contacts_imported_later_are_the_only_ones_drafted(forty):
    main(["draft", "--campaign", "big", "--save"])
    more = forty / "more.csv"
    more.write_text("Company,Email\nLate Mill,late@late.example\n")
    main(["import", str(more), "--campaign", "big", "--commit"])
    main(["draft", "--campaign", "big", "--save"])
    assert _drafts(forty) == 41


def test_a_preview_without_save_still_shows_just_a_few(forty, capsys):
    main(["draft", "--campaign", "big"])
    assert capsys.readouterr().out.count("-- Mill") == 3


def test_the_web_page_drafts_ten_at_a_time(forty):
    """A request that runs for minutes looks exactly like one that has hung."""
    from fastapi.testclient import TestClient

    from outreach.config import load_settings
    from outreach.web.app import create_app

    client = TestClient(create_app(load_settings()))
    client.post("/campaigns/big/draft")
    assert _drafts(forty) == 10
    page = client.get("/campaigns/big/drafts").text
    assert "30 contacts still without a draft" in page
    assert re.search(r"Write the next 10 drafts", page)


# --- status -----------------------------------------------------------------


def test_status_shows_where_each_campaign_stands(forty, capsys):
    main(["draft", "--campaign", "big", "--save"])
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    line = next(row for row in out.splitlines() if row.strip().startswith("big"))
    assert line.split()[1:] == ["40", "0", "40", "0", "0"]
