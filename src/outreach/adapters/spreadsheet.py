"""Reading a spreadsheet file into plain rows.

This is the only place that knows what a .csv or .xlsx actually is. Everything
above gets a list of dictionaries: column name to cell value, as text.

Values come back as text on purpose. A phone number that Excel decided was a
number, or a GST code it turned into scientific notation, would otherwise
arrive mangled. Text in, text out, no interpretation.
"""

from __future__ import annotations

import csv
from pathlib import Path

Row = dict[str, str]


class SpreadsheetError(RuntimeError):
    """The file could not be read at all."""


def read_rows(path: str | Path, sheet: str | None = None) -> list[Row]:
    """Read a .csv or .xlsx into rows. The first row is treated as headers.

    A workbook with several sheets will not be guessed at: it says which sheets
    exist and asks which one. Silently reading the wrong sheet — a summary tab
    rather than the leads — is worse than an error.
    """
    file = Path(path)
    if not file.exists():
        raise SpreadsheetError(f"No such file: {file}")

    suffix = file.suffix.lower()
    if suffix == ".csv":
        return _read_csv(file)
    if suffix in {".xlsx", ".xlsm"}:
        return _read_excel(file, sheet)
    readable = suffix or "a file with no extension"
    raise SpreadsheetError(f"Cannot read {readable}. Use .csv or .xlsx.")


def _read_csv(file: Path) -> list[Row]:
    # utf-8-sig strips the invisible marker Excel puts at the start of the file,
    # which otherwise becomes part of the first column's name.
    with file.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def _read_excel(file: Path, sheet_name: str | None) -> list[Row]:
    from openpyxl import load_workbook

    workbook = load_workbook(file, read_only=True, data_only=True)
    names = workbook.sheetnames

    if sheet_name is not None:
        if sheet_name not in names:
            workbook.close()
            available = "\n".join(f"  {n}" for n in names)
            raise SpreadsheetError(f"No sheet called '{sheet_name}'. This file has:\n{available}")
        sheet = workbook[sheet_name]
    elif len(names) == 1:
        sheet = workbook[names[0]]
    else:
        workbook.close()
        available = "\n".join(f"  {n}" for n in names)
        raise SpreadsheetError(
            f"This file has several sheets. Say which one with --sheet:\n{available}"
        )

    rows = sheet.iter_rows(values_only=True)
    try:
        header_cells = next(rows)
    except StopIteration:
        return []

    headers = [str(h).strip() if h is not None else "" for h in header_cells]
    result: list[Row] = []
    for cells in rows:
        row = {
            header: ("" if value is None else str(value).strip())
            for header, value in zip(headers, cells, strict=False)
            if header
        }
        if any(row.values()):  # skip entirely blank rows
            result.append(row)
    workbook.close()
    return result
