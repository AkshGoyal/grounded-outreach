"""Run the guided browser checks against a fresh fictional server and browser profile."""

import argparse
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def find_browser(explicit: str | None) -> str:
    if explicit:
        candidate = shutil.which(explicit) or explicit
        if Path(candidate).is_file():
            return candidate
        raise RuntimeError("The --browser path does not exist.")
    for command in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        if candidate := shutil.which(command):
            return candidate
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
        if base:
            candidate = Path(base) / "Google/Chrome/Application/chrome.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("Chrome/Chromium was not found. Supply --browser with an installed path.")


def run(browser: str, timeout: int) -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # The server itself creates a temporary DB and replaces providers with fakes.
    with tempfile.TemporaryDirectory(prefix="outreach-guided-qa-") as directory:
        folder = Path(directory)
        with (folder / "server.log").open("w", encoding="utf-8") as server_log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "tests.fakes.workspace_server",
                    "--port",
                    str(port),
                    "--no-auth",
                ],
                cwd=ROOT,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            try:
                deadline = time.monotonic() + 20
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("The fictional QA server exited before readiness.")
                    try:
                        with urllib.request.urlopen(origin + "/qa/state", timeout=1) as response:
                            state = json.load(response)
                        if state != {"calls": 0, "runs": [], "sent": 0}:
                            raise RuntimeError("The QA server is not a fresh fictional workspace.")
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "The fictional QA server did not become ready."
                            ) from None
                        time.sleep(0.1)
                result = subprocess.run(
                    [
                        browser,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                        f"--user-data-dir={folder / 'profile'}",
                        "--dump-dom",
                        "--virtual-time-budget=65000",
                        origin + "/qa/guided",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    creationflags=creationflags,
                )
                match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.DOTALL)
                report = html.unescape(match.group(1)).strip() if match else ""
                if result.returncode == 0 and report.startswith("PASS"):
                    print(report)
                    return 0
                print(report or "Browser returned no completed guided QA report.", file=sys.stderr)
                if result.stderr:
                    print(result.stderr[-3000:], file=sys.stderr)
                return 1
            finally:
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Existing Chrome/Chromium executable (never downloaded)")
    parser.add_argument(
        "--timeout", type=int, default=120, help="Browser timeout in seconds (1-120)"
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")
    try:
        return run(find_browser(args.browser), args.timeout)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Browser QA could not complete: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
