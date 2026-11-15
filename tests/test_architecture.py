"""The folder rule, enforced by the test suite.

Until now this was a check someone had to remember to run by hand. Now a commit
that breaks the rule fails the tests instead.

The rule: only files inside `adapters/` may talk to an outside library. Every
other file deals in the project's own types. That is what keeps the choice of
Zoho or of Claude a setting we can change, rather than a decision baked
throughout the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "outreach"

# The one file allowed to know which adapters exist.
#
# Something has to decide that "the mailbox" means Zoho and "storage" means
# SQLite, and wire them together. That job belongs to the entry point and
# nowhere else — which is exactly why it is named here rather than the rule
# being quietly relaxed.
COMPOSITION_ROOT = {"cli.py", "web/app.py", "wiring.py"}

# Libraries belonging to an outside service or storage engine.
VENDOR_PACKAGES = {"smtplib", "imaplib", "email", "anthropic", "sqlite3", "openpyxl", "csv"}


def _top_level_imports(path: Path) -> set[str]:
    """Every package name imported by one file, ignoring relative imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _rel(path: Path) -> str:
    """A file's path inside the package, always written with forward slashes.

    On Windows `str(path)` gives `web\\app.py`, which never matches
    `web/app.py` in COMPOSITION_ROOT — so the web app was wrongly reported as
    breaking the rule. `as_posix()` writes it the same way on every machine.
    """
    return path.relative_to(SRC).as_posix()


def _files_outside_adapters() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "adapters" not in p.relative_to(SRC).parts]


def test_only_adapters_may_import_outside_libraries():
    offenders = {
        _rel(path): sorted(VENDOR_PACKAGES & _top_level_imports(path))
        for path in _files_outside_adapters()
        if VENDOR_PACKAGES & _top_level_imports(path)
    }
    assert not offenders, (
        "These files import an outside library but do not live in adapters/:\n"
        f"{offenders}\n"
        "Move the code into an adapter, or talk to it through a port instead."
    )


def test_nothing_depends_on_a_specific_adapter():
    """Dependencies point one way: adapters -> ports -> core, never back.

    The entry point is the single documented exception — see COMPOSITION_ROOT.
    """
    offenders = {
        _rel(path): sorted(n for n in _top_level_imports(path) if n == "outreach.adapters")
        for path in _files_outside_adapters()
        if "outreach.adapters" in {n for n in _top_level_imports(path)}
    }
    # ast gives us the top-level package only, so check the raw text as well.
    textual = [
        _rel(p)
        for p in _files_outside_adapters()
        if _rel(p) not in COMPOSITION_ROOT
        and (
            "from outreach.adapters" in p.read_text(encoding="utf-8")
            or "import outreach.adapters" in p.read_text(encoding="utf-8")
        )
    ]
    assert not offenders and not textual, (
        f"These files reach into adapters/: {textual or offenders}\n"
        "core/ and ports/ must not know which adapter is in use."
    )


def test_path_names_are_written_the_same_way_on_every_machine():
    """Found on a real Windows laptop: the web app was flagged as breaking the
    rule because Windows wrote its path with a backslash. This proves the
    composition-root check does not depend on the operating system."""
    from pathlib import PureWindowsPath

    assert PureWindowsPath("web", "app.py").as_posix() in COMPOSITION_ROOT
    assert _rel(SRC / "web" / "app.py") in COMPOSITION_ROOT
