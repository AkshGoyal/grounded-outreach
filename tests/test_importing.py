"""Reading a spreadsheet: what gets in, what gets rejected, and why.

The fixture is deliberately messy — capitals, stray spaces, a broken address, a
missing address, a blank cell and a duplicate — because a real list is.
"""

from pathlib import Path

import pytest

from outreach.adapters.spreadsheet import SpreadsheetError, read_rows
from outreach.core.importing import (
    ColumnPlan,
    RowStatus,
    build_report,
    plan_columns,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_contacts.csv"


@pytest.fixture
def rows():
    return read_rows(FIXTURE)


@pytest.fixture
def report(rows):
    return build_report(rows, plan=plan_columns(rows))


# --- working out which column is which --------------------------------------


def test_finds_the_email_column_from_its_header(rows):
    assert plan_columns(rows).email_column == "Email ID"


def test_finds_the_company_column(rows):
    assert plan_columns(rows).company_column == "Company Name"


def test_everything_else_becomes_evidence(rows):
    plan = plan_columns(rows)
    assert set(plan.evidence_columns) == {"City", "What they make", "Notes", "Contact Person"}


def test_finds_the_email_column_even_with_a_useless_header():
    """Headers like 'Column 3' are common in scraped lists. Fall back to
    reading the values."""
    rows = [
        {"A": "Alpha Mills", "Column 3": "a@alpha.example"},
        {"A": "Beta Mills", "Column 3": "b@beta.example"},
    ]
    assert plan_columns(rows).email_column == "Column 3"


def test_reports_clearly_when_no_column_looks_like_an_email():
    rows = [{"Company": "Alpha Mills", "City": "Ludhiana"}]
    report = build_report(rows, plan=plan_columns(rows))
    assert report.counts["accepted"] == 0
    assert "looks like an email" in report.outcomes[0].reason


# --- checking the rows ------------------------------------------------------


def test_good_rows_are_accepted(report):
    assert report.counts["accepted"] == 4


def test_a_broken_address_is_rejected_with_its_reason(report):
    bad = [o for o in report.outcomes if o.status is RowStatus.REJECTED and o.email]
    assert len(bad) == 1
    assert "anand.fabrics.example" in bad[0].reason


def test_a_missing_address_is_rejected(report):
    missing = [o for o in report.outcomes if o.status is RowStatus.REJECTED and not o.email]
    assert len(missing) == 1
    assert "No email address" in missing[0].reason


def test_every_row_is_accounted_for(rows, report):
    """Nothing is silently dropped — the report has one entry per data row."""
    assert len(report.outcomes) == len(rows)


def test_rejected_rows_keep_their_spreadsheet_row_number(report):
    """So you can open the file and go straight to the row."""
    problems = [o for o in report.outcomes if o.status is not RowStatus.ACCEPTED]
    assert all(o.row_number >= 2 for o in problems)


# --- duplicates -------------------------------------------------------------


def test_the_same_address_twice_keeps_the_first(report):
    dupes = [o for o in report.outcomes if o.status is RowStatus.DUPLICATE]
    assert len(dupes) == 1
    assert dupes[0].email == "purchase@kohinoorknits.example"


def test_capitals_and_spaces_do_not_hide_a_duplicate(report):
    """The file has PURCHASE@... and ' purchase@... ' as separate rows."""
    accepted = [e for e, _, _ in report.accepted]
    assert accepted.count("purchase@kohinoorknits.example") == 1


def test_addresses_already_in_the_campaign_are_not_re_added(rows):
    report = build_report(
        rows, plan=plan_columns(rows), already_known={"ORDERS@deccanweaves.example"}
    )
    assert "orders@deccanweaves.example" not in [e for e, _, _ in report.accepted]


# --- evidence ---------------------------------------------------------------


def test_evidence_is_the_cell_text_and_nothing_else(report):
    evidence = dict(
        next(ev for email, _, ev in report.accepted if email == "orders@deccanweaves.example")
    )
    assert evidence["City"] == "Hyderabad"
    assert evidence["Notes"] == "Asked for samples last year"


def test_blank_cells_are_left_out_entirely(report):
    """An empty string invites a model to fill the gap. Absence does not."""
    evidence = next(ev for email, _, ev in report.accepted if "shaktimills" in email)
    assert "What they make" not in evidence
    assert "" not in evidence.values()


def test_the_company_is_kept_separately_from_evidence(report):
    _, company, evidence = next(
        row for row in report.accepted if row[0] == "orders@deccanweaves.example"
    )
    assert company == "Deccan Weaves"
    assert "Company Name" not in evidence


# --- reading the file itself ------------------------------------------------


def test_surrounding_spaces_are_stripped(rows):
    emails = [r["Email ID"] for r in rows]
    assert " buying@meridiantex.example " not in emails
    assert "buying@meridiantex.example" in emails


def test_an_unsupported_file_type_says_so(tmp_path):
    bad = tmp_path / "contacts.pdf"
    bad.write_text("nope")
    with pytest.raises(SpreadsheetError, match="Use .csv or .xlsx"):
        read_rows(bad)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(SpreadsheetError, match="No such file"):
        read_rows(tmp_path / "nowhere.csv")


def test_an_overridden_email_column_is_respected(rows):
    """--email-column must win over the guess."""
    plan = ColumnPlan(email_column="Email ID", company_column="Company Name", evidence_columns=[])
    report = build_report(rows, plan=plan)
    assert report.counts["accepted"] == 4
    assert all(ev == {} for _, _, ev in report.accepted)


# --- workbooks with several sheets ------------------------------------------


def test_a_multi_sheet_workbook_is_not_guessed_at(tmp_path):
    """Silently reading a summary tab instead of the leads would be worse than
    an error, so it asks."""
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Summary"
    book.create_sheet("Buyer Leads").append(["Company", "Email"])
    path = tmp_path / "leads.xlsx"
    book.save(path)

    with pytest.raises(SpreadsheetError) as exc:
        read_rows(path)
    assert "Buyer Leads" in str(exc.value) and "--sheet" in str(exc.value)


def test_a_named_sheet_is_read(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Summary"
    leads = book.create_sheet("Buyer Leads")
    leads.append(["Company", "Email"])
    leads.append(["Alpha Mills", "a@alpha.example"])
    path = tmp_path / "leads.xlsx"
    book.save(path)

    rows = read_rows(path, sheet="Buyer Leads")
    assert rows == [{"Company": "Alpha Mills", "Email": "a@alpha.example"}]


def test_an_unknown_sheet_name_lists_the_real_ones(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Summary"
    book.create_sheet("Buyer Leads")
    path = tmp_path / "leads.xlsx"
    book.save(path)

    with pytest.raises(SpreadsheetError, match="Buyer Leads"):
        read_rows(path, sheet="Typo")


# --- keeping bookkeeping out of the evidence --------------------------------


def test_bookkeeping_columns_are_left_out_by_default():
    """'Change vs v1: New lead' handed to a model as a fact about a business
    produces 'I see you are a new lead'. Your own tracking columns are not
    facts about them."""
    rows = [
        {
            "Company": "Alpha Mills",
            "Email": "a@alpha.example",
            "City": "Ludhiana",
            "Status": "Not contacted",
            "Change vs v1": "New lead",
            "Your notes": "",
            "#": "1",
        }
    ]
    plan = plan_columns(rows)
    assert plan.evidence_columns == ["City"]


def test_you_can_skip_more_columns():
    rows = [{"Company": "A", "Email": "a@a.example", "City": "X", "Phone": "123"}]
    plan = plan_columns(rows, skip=["Phone"])
    assert "Phone" not in plan.evidence_columns
    assert "City" in plan.evidence_columns


def test_skipping_is_case_and_space_insensitive():
    rows = [{"Company": "A", "Email": "a@a.example", "  STATUS  ": "x", "City": "Y"}]
    assert plan_columns(rows).evidence_columns == ["City"]


# --- messy cells, as real research lists have them --------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("info@billoomi.example (management only)", "info@billoomi.example"),
        ("Email: sales@alpha.example", "sales@alpha.example"),
        ("sales@alpha.example, info@alpha.example", "sales@alpha.example"),
        ("sales@alpha.example / info@alpha.example", "sales@alpha.example"),
        ("  SALES@Alpha.example  ", "sales@alpha.example"),
    ],
)
def test_an_address_is_pulled_out_of_a_cell_with_other_text(cell, expected):
    """Found in the real leads file: 'info@... (management only)' was being
    rejected outright, throwing away a real published address."""
    rows = [{"Company": "Alpha", "Email": cell}]
    report = build_report(rows, plan=plan_columns(rows))
    assert [email for email, _, _ in report.accepted] == [expected]


def test_the_leftover_text_is_shown_not_silently_dropped():
    rows = [{"Company": "Alpha", "Email": "info@alpha.example (management only)"}]
    [outcome] = build_report(rows, plan=plan_columns(rows)).outcomes
    assert outcome.status is RowStatus.ACCEPTED
    assert "management only" in outcome.note


def test_two_addresses_in_one_cell_are_reported():
    rows = [{"Company": "Alpha", "Email": "a@alpha.example, b@alpha.example"}]
    [outcome] = build_report(rows, plan=plan_columns(rows)).outcomes
    assert "2 addresses" in outcome.note


def test_a_clean_cell_carries_no_note():
    rows = [{"Company": "Alpha", "Email": "a@alpha.example"}]
    [outcome] = build_report(rows, plan=plan_columns(rows)).outcomes
    assert outcome.note is None


def test_not_published_is_still_rejected():
    rows = [{"Company": "Alpha", "Email": "Not published"}]
    [outcome] = build_report(rows, plan=plan_columns(rows)).outcomes
    assert outcome.status is RowStatus.REJECTED
