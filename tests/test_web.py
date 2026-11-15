"""The web interface must show the same truth as the command line.

Both call the same import code, so these tests mostly check that the pages
render, that a preview writes nothing, and that the do-not-contact list is
visible where it matters.
"""

import pytest
from fastapi.testclient import TestClient

from outreach.core.models import SuppressionReason
from outreach.web.app import create_app

FIXTURE = "tests/fixtures/sample_contacts.csv"


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def _upload(client, *, campaign="test", commit=False, email_column=""):
    with open(FIXTURE, "rb") as handle:
        data = {"campaign": campaign, "sheet": "", "email_column": email_column}
        if commit:
            data["commit"] = "1"
        return client.post(
            "/import", files={"file": ("contacts.csv", handle, "text/csv")}, data=data
        )


def test_the_home_page_loads_with_nothing_in_it(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Who would you like to reach?" in response.text


def test_preview_shows_the_numbers_without_writing(client):
    response = _upload(client)
    assert response.status_code == 200
    assert "This is what would happen" in response.text
    assert "Nothing was written" in response.text
    # and the campaign still does not exist
    assert "Who would you like to reach?" in client.get("/").text


def test_preview_names_the_column_it_chose(client):
    assert "Email ID" in _upload(client).text


def test_preview_lists_every_rejected_row_with_its_reason(client):
    text = _upload(client).text
    assert "not a valid email address" in text
    assert "No email address in this row" in text


def test_importing_writes_the_contacts(client):
    response = _upload(client, campaign="rfd", commit=True)
    assert "Imported" in response.text

    page = client.get("/campaigns/rfd?tab=audience")
    assert "Kohinoor Knits" in page.text
    assert "Deccan Weaves" in page.text


def test_the_campaign_page_shows_the_evidence(client):
    _upload(client, campaign="rfd", commit=True)
    page = client.get("/campaigns/rfd?tab=audience").text
    assert "Tiruppur" in page
    assert "Asked for samples last year" in page


def test_a_suppressed_contact_is_marked_on_the_campaign_page(client, settings):
    from outreach.adapters.db import connect
    from outreach.adapters.store_sqlite import SqliteStore

    _upload(client, campaign="rfd", commit=True)
    SqliteStore(connect(settings.db_path)).add_suppression(
        "orders@deccanweaves.example", SuppressionReason.UNSUBSCRIBE
    )
    assert "do not contact" in client.get("/campaigns/rfd?tab=audience").text


def test_an_address_can_be_added_to_the_list_from_the_page(client):
    client.post(
        "/suppressions",
        data={"email": "STOP@example.com", "reason": "unsubscribe", "note": "asked by phone"},
        follow_redirects=True,
    )
    page = client.get("/suppressions").text
    # stored lowercased, through the same one function the rest of the code uses
    assert "stop@example.com" in page
    assert "asked by phone" in page


def test_an_unreadable_file_reports_why_instead_of_crashing(client):
    response = client.post(
        "/import",
        files={"file": ("notes.pdf", b"not a spreadsheet", "application/pdf")},
        data={"campaign": "x", "sheet": "", "email_column": ""},
    )
    assert response.status_code == 200
    assert "Use .csv or .xlsx" in response.text


def test_backup_runs_from_the_page(client):
    _upload(client, campaign="rfd", commit=True)
    response = client.post("/backup")
    assert response.status_code == 200
    assert "cannot be rebuilt" in response.text


def test_serve_opens_the_page_in_the_browser(monkeypatch):
    import threading

    from outreach.cli import main

    opened, started, built = [], [], []
    # Never the real app here: on a machine with a real .env it would read
    # the real inbox and database.
    monkeypatch.setattr("outreach.web.app.create_app", lambda **k: built.append(k) or object())
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(k["port"]))
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr(
        threading, "Timer", lambda delay, fn, args: type("T", (), {"start": lambda s: fn(*args)})()
    )
    assert main(["serve", "--port", "8123"]) == 0
    assert opened == ["http://127.0.0.1:8123"] and started == [8123]
    assert built == [{"poll_minutes": 10}], "the tool checks for replies while open"

    opened.clear()
    main(["serve", "--no-browser"])
    assert opened == []
