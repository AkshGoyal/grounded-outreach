"""Run the full offline suite away from .env and owner data, using fictional fixtures."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.startswith(("OUTREACH_", "WORKBENCH_"))
            or any(part in key for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
        )
    }
    destination = ROOT / ".local-cache/workbench-checks/offline-tests.log"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="workbench-offline-") as directory:
        # Some legacy tests resolve this relative path at collection time.
        shutil.copytree(ROOT / "tests/fixtures", Path(directory) / "tests/fixtures")
        with destination.open("w") as log:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-c",
                    str(ROOT / "pyproject.toml"),
                    str(ROOT / "tests"),
                ],
                cwd=directory,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
    print("\n".join(destination.read_text().splitlines()[-45:]))
    print(f"Full log: {destination}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
