"""Local server with a graceful handoff from preview to the owner's launcher."""

import argparse
import threading
import time
import webbrowser

import uvicorn

from outreach.config import load_settings
from outreach.web.app import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restricted", action="store_true")
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    if args.restricted:
        settings.local_network_restricted = True
    server = None

    def shutdown():
        if server:
            server.should_exit = True

    app = create_app(settings, local_shutdown=shutdown)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, access_log=False))
    if args.open_browser:

        def open_when_ready():
            for _ in range(120):
                if server.started:
                    webbrowser.open("http://127.0.0.1:8000")
                    return
                if server.should_exit:
                    return
                time.sleep(0.25)

        threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
