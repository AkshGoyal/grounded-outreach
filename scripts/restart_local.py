"""Owner-run handoff; authenticated, no process killing, no paid requests."""

import socket
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values


def occupied():
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", 8000)) == 0


def main():
    if not occupied():
        return
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    password = values.get("OUTREACH_APP_PASSWORD")
    if not password:
        raise SystemExit("Workspace password is not configured. Existing server was left running.")
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
            login = client.post("/login", data={"password": password})
            if login.status_code != 303:
                raise ValueError()
            status = client.get("/setup/local-status")
            if status.status_code != 200:
                raise ValueError()
            mode = status.json()
            if not mode.get("restricted"):
                print("The desktop app is already running. Opening it.")
                return
            if not mode.get("restart_available"):
                raise ValueError()
            response = client.post("/setup/restart-local")
            if response.status_code == 409:
                raise SystemExit("Current work is still active. Finish or pause it, then restart.")
            if response.status_code != 200:
                raise ValueError()
    except (httpx.HTTPError, ValueError):
        raise SystemExit(
            "Could not restart this workspace safely. Existing files and server were left intact."
        ) from None
    for _ in range(100):
        if not occupied():
            print("Preview stopped safely. Starting the desktop app.")
            return
        time.sleep(0.15)
    raise SystemExit("Server is still closing. Wait a moment and try the launcher again.")


if __name__ == "__main__":
    main()
