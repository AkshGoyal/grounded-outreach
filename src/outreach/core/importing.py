"""Turning a spreadsheet into contacts we can safely write to.

Three jobs, in order:

1. Work out which column holds the email address, and which columns hold
   things we know about the business.
2. Check each row. A row without a usable email cannot be contacted, so it is
   rejected — reported, never silently dropped.
3. Notice duplicates, both within the file and against what is already stored.

Nothing here writes to the database. It produces a report, and the caller
decides whether to commit it. That is what makes a preview possible: the same
code runs either way, so what you previewed is exactly what you get.

On evidence
-----------
`evidence` is the set of facts we are allowed to say about a business later.
The rule is deliberately strict: **a cell's literal text, and nothing else.**
Nothing inferred, nothing computed, nothing a model suggested.

Blank cells are dropped rather than stored as empty text. A model handed
`{"what they make": ""}` will happily invent what they make; a model handed
nothing at all has nothing to invent from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, EmailStr, ValidationError

from outreach.core.normalize import normalize_email

Row = dict[str, str]

# Header names that mean "this is the email address", in the spellings that
# actually turn up in Indian B2B lists.
_EMAIL_HEADER = re.compile(r"\b(e[-\s]?mail|mail[\s_-]?id|email[\s_-]?address)\b", re.IGNORECASE)
_COMPANY_HEADER = re.compile(
    r"\b(company|firm|business|organisation|organization)\b", re.IGNORECASE
)
_LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# An address somewhere inside a cell that also holds other text:
# "info@x.com (management only)", "a@x.com, b@x.com", "Email: a@x.com".
_ADDRESS_IN_TEXT = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


class RowStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class RowOutcome:
    """What happened to one row, and why. Every row gets one of these."""

    row_number: int  # 1-based, counting the header as row 1, as a spreadsheet does
    status: RowStatus
    email: str | None
    reason: str | None = None
    # Accepted, but worth a look: the cell held more than one address, or an
    # address with a note beside it. Shown in the preview so nothing is
    # silently interpreted.
    note: str | None = None


@dataclass
class ColumnPlan:
    """Which column is which. Guessed, then shown to you before anything runs."""

    email_column: str | None
    company_column: str | None
    evidence_columns: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    """The result of reading a file. Nothing has been written yet."""

    plan: ColumnPlan
    outcomes: list[RowOutcome]
    accepted: list[tuple[str, str | None, dict[str, str]]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        tally = {status.value: 0 for status in RowStatus}
        for outcome in self.outcomes:
            tally[outcome.status.value] += 1
        return tally


class _EmailCheck(BaseModel):
    email: EmailStr


# Columns that are your own bookkeeping rather than facts about the business.
# Left in, they become material a draft may cite — "I see you are a new lead"
# is a real sentence a model will write if "Change vs v1: New lead" is handed
# to it as evidence.
DEFAULT_SKIP = (
    "#",
    "s.no",
    "sr no",
    "serial",
    "status",
    "last contacted",
    "your notes",
    "change vs v1",
    "priority",
    "source url",
)


def plan_columns(
    rows: list[Row], *, skip: tuple[str, ...] | list[str] = DEFAULT_SKIP
) -> ColumnPlan:
    """Guess which column is which.

    Header names first, because they are what a person meant. If no header
    looks like an email, fall back to reading the values: the column where most
    cells look like addresses is almost certainly the one.

    `skip` names columns that are your own bookkeeping rather than facts about
    the business. They are left out of evidence entirely, because evidence is
    what a draft is allowed to cite.
    """
    if not rows:
        return ColumnPlan(email_column=None, company_column=None)

    headers = list(rows[0].keys())

    email_column = next((h for h in headers if _EMAIL_HEADER.search(h)), None)
    if email_column is None:
        email_column = _sniff_email_column(rows, headers)

    company_column = next((h for h in headers if _COMPANY_HEADER.search(h)), None)

    skipped = {s.strip().lower() for s in skip}
    evidence_columns = [
        h
        for h in headers
        if h not in {email_column, company_column} and h.strip().lower() not in skipped
    ]
    return ColumnPlan(
        email_column=email_column,
        company_column=company_column,
        evidence_columns=evidence_columns,
    )


def _sniff_email_column(rows: list[Row], headers: list[str]) -> str | None:
    """The column whose values look most like email addresses, if any does."""
    best, best_score = None, 0.0
    for header in headers:
        values = [r.get(header, "").strip() for r in rows]
        filled = [v for v in values if v]
        if not filled:
            continue
        score = sum(bool(_LOOKS_LIKE_EMAIL.match(v)) for v in filled) / len(filled)
        if score > best_score:
            best, best_score = header, score
    # Half is a deliberately low bar: a list with several broken addresses is
    # normal, and a wrong guess is shown to you before anything is written.
    return best if best_score >= 0.5 else None


def build_report(
    rows: list[Row],
    *,
    plan: ColumnPlan,
    already_known: set[str] | None = None,
) -> ImportReport:
    """Check every row against the plan. Writes nothing.

    `already_known` is the set of addresses already stored for this campaign,
    so re-importing an updated file does not create duplicates.
    """
    seen = {normalize_email(e) for e in (already_known or set())}
    report = ImportReport(plan=plan, outcomes=[])

    if plan.email_column is None:
        report.outcomes.append(
            RowOutcome(
                row_number=1,
                status=RowStatus.REJECTED,
                email=None,
                reason="No column in this file looks like an email address.",
            )
        )
        return report

    for index, row in enumerate(rows, start=2):  # row 1 is the header
        raw = row.get(plan.email_column, "").strip()

        if not raw:
            report.outcomes.append(
                RowOutcome(index, RowStatus.REJECTED, None, "No email address in this row.")
            )
            continue

        found = _ADDRESS_IN_TEXT.findall(raw)
        candidate = found[0] if found else raw
        try:
            _EmailCheck(email=candidate)
        except ValidationError:
            report.outcomes.append(
                RowOutcome(index, RowStatus.REJECTED, raw, f"'{raw}' is not a valid email address.")
            )
            continue

        note = None
        leftover = raw.replace(candidate, "", 1).strip(" ,;/|:-\t")
        if len(found) > 1:
            note = f"{len(found)} addresses in this cell — used the first, {candidate}."
        elif leftover:
            note = f"The cell also says “{leftover}” — used {candidate}."

        email = normalize_email(candidate)
        if email in seen:
            report.outcomes.append(
                RowOutcome(index, RowStatus.DUPLICATE, email, "Already seen — keeping the first.")
            )
            continue

        seen.add(email)
        company = row.get(plan.company_column, "").strip() if plan.company_column else None
        report.outcomes.append(RowOutcome(index, RowStatus.ACCEPTED, email, note=note))
        report.accepted.append((email, company or None, _evidence(row, plan)))

    return report


def _evidence(row: Row, plan: ColumnPlan) -> dict[str, str]:
    """A cell's literal text, and nothing else. Blanks are left out entirely."""
    return {
        column: row[column].strip()
        for column in plan.evidence_columns
        if row.get(column, "").strip()
    }


def _ranges(numbers: list[int]) -> str:
    """[2, 3, 4, 7, 9, 10] -> '2–4, 7, 9–10'."""
    parts, start, prev = [], None, None
    for n in sorted(numbers):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            parts.append(f"{start}–{prev}" if prev != start else str(start))
            start = prev = n
    if start is not None:
        parts.append(f"{start}–{prev}" if prev != start else str(start))
    return ", ".join(parts)


def grouped_problems(report: ImportReport) -> list[tuple[str, str, int, str]]:
    """Rejections and duplicates, grouped by identical reason.

    A real list had 36 rows saying "Not published". Listing each one buries
    the three rows that actually need a look; grouping shows both at a glance.
    Returns (status, reason, count, row ranges), largest group first.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for o in report.outcomes:
        if o.status is RowStatus.ACCEPTED:
            continue
        groups.setdefault((o.status.value, o.reason or ""), []).append(o.row_number)
    return sorted(
        ((status, reason, len(rows), _ranges(rows)) for (status, reason), rows in groups.items()),
        key=lambda g: -g[2],
    )
