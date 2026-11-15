"""Run Workbench browser journeys with existing Chrome and disposable fictional-provider servers.

The fixture journey uses fixture research; the live journey drives the real live adapter
over a fictional in-process transport. Neither can reach the network or a paid provider.
"""

import argparse
import html
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from check_browser import find_browser

ROOT = Path(__file__).resolve().parents[1]


PROFILES = ("fixture", "live")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser")
    parser.add_argument("--profile", choices=PROFILES, action="append")
    args = parser.parse_args()
    browser = find_browser(args.browser)
    failures = 0
    for profile in args.profile or PROFILES:
        print(f"== {profile} journey ==")
        failures += journey(browser, profile)
    return 1 if failures else 0


def journey(browser, profile):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="workbench-browser-") as directory:
        folder = Path(directory)
        with (folder / "server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "tests.fakes.workbench_server",
                    "--data-dir",
                    str(folder),
                    "--port",
                    str(port),
                    "--profile",
                    profile,
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 15
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"{profile} QA server failed to start")
                    try:
                        urllib.request.urlopen(origin + "/health", timeout=1).close()
                        break
                    except urllib.error.URLError:
                        if time.monotonic() >= deadline:
                            message = f"{profile} QA server did not become ready"
                            raise RuntimeError(message) from None
                        time.sleep(0.1)
                completed = subprocess.run(
                    [
                        browser,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-default-browser-check",
                        f"--user-data-dir={folder / 'chrome'}",
                        "--dump-dom",
                        "--virtual-time-budget=30000",
                        origin + "/qa/workbench",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                match = re.search(r'<pre id="result">(.*?)</pre>', completed.stdout, re.DOTALL)
                report = html.unescape(match.group(1)) if match else "No completed browser report"
                print(report)
                return 0 if completed.returncode == 0 and report.startswith("PASS") else 1
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
