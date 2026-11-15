"""Disposable Workbench browser harness server with fictional providers only.

``--profile fixture`` uses the fixture provider. ``--profile live`` exercises the real
live adapter, ledger and routes over a fictional in-process HTTP transport: no secrets,
network requests or paid calls are possible.
"""

import argparse
import threading
from pathlib import Path

import httpx
import uvicorn
from fastapi.responses import HTMLResponse

from outreach.adapters.workbench_fixture import FixtureDraftWriter, FixtureResearchProvider
from outreach.adapters.workbench_research import SourcePolicy
from outreach.config import Settings
from outreach.wiring import build_workbench_app
from tests.test_workbench_parallel import PublicSources, public_resolver
from tests.test_workbench_research_routes import AmbiguousFixture

PAGES = {"fixture": "workbench_workspace.html", "live": "workbench_live_workspace.html"}


def fixture_app(settings):
    released = threading.Event()
    released.set()
    ambiguous = threading.Event()

    class GatedFixture(FixtureResearchProvider):
        def research(self, prospect):
            if not released.wait(10):
                raise RuntimeError("QA provider was not released")
            if ambiguous.is_set():
                return AmbiguousFixture().research(prospect)
            return super().research(prospect)

    writer = FixtureDraftWriter()
    app = build_workbench_app(settings, provider=GatedFixture(), writer=writer)

    @app.post("/qa/draft/{variant}")
    def draft_variant(variant: str):
        # supported | false_inference | persistent_false_inference (labelled fixtures)
        writer.variant = variant
        return {"draft_variant": variant}

    @app.post("/qa/hold")
    def hold_provider():
        released.clear()
        return {"fixture_provider_held": True}

    @app.post("/qa/release")
    def release_provider():
        released.set()
        return {"fixture_provider_held": False}

    @app.post("/qa/ambiguous/{state}")
    def ambiguous_identity(state: str):
        ambiguous.set() if state == "on" else ambiguous.clear()
        return {"ambiguous_identity": ambiguous.is_set()}

    return app


def live_app(settings):
    fake = PublicSources(restricted=True)
    settings = settings.model_copy(
        update={"parallel_api_key": "fictional", "openrouter_api_key": "fictional"}
    )
    app = build_workbench_app(
        settings,
        mode="live",
        source_policy=SourcePolicy(public_resolver),
        research_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake)),
    )

    @app.get("/qa/calls")
    def provider_calls():
        return {"calls": len(fake.calls)}

    @app.post("/qa/scenario/{name}")
    def scenario(name: str):
        # With the restricted profile a run makes search, two extracts, then the identity
        # model call. "uncertain" times out that model call after one page was read.
        # "sparse": no page can be read at all, so not even a company-only hook exists.
        fake.sparse = fake.unreadable = name == "sparse"
        fake.timeout_at = len(fake.calls) + 4 if name == "uncertain" else None
        return {"scenario": name}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", choices=tuple(PAGES), default="fixture")
    args = parser.parse_args()
    settings = Settings(
        _env_file=None,
        _env_prefix="WORKBENCH_QA_",
        db_path=str(args.data_dir / "workbench.db"),
        app_password=None,
    )
    app = (fixture_app if args.profile == "fixture" else live_app)(settings)

    @app.middleware("http")
    async def allow_local_qa_frame(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response

    @app.get("/qa/workbench", response_class=HTMLResponse)
    def guided():
        return (Path(__file__).resolve().parents[1] / "browser" / PAGES[args.profile]).read_text()

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
