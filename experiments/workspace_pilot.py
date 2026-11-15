"""Exercise production research while retaining the original $1 pilot ledger.

No mailbox, enrollment or sending. Published contacts stay pending human review.
Both the production SQLite budget and the original pilot ledger gate every POST.
"""

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from experiments.pilot_runtime import PilotStop, Runtime, atomic_json, session_lock
from outreach.adapters.db import connect
from outreach.adapters.platform_store import PlatformStore
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import Settings
from outreach.core.research import ResearchStop
from outreach.web.app import create_app

ARM = "workspace-careers-v1"
BRIEF = {
    "brief": "Find AI product startups in Bangalore for speculative job outreach. "
    "Prefer founder emails, but published HR/recruiting or senior-management professional "
    "emails are accepted. Do not guess addresses or extensively search vacancies. "
    "Save company/product facts and exact sources for personalized emails later.",
    "company_type": "Startups building their own AI software products",
    "geography": "Bangalore / Bengaluru, India",
    "contact_roles": ["founder", "hr", "management"],
    "purpose": "job search",
    "title": "Bangalore AI contact-role pilot",
    "target": "2",
    "budget": ".12",
}
PLAN = {
    "summary": BRIEF["brief"],
    "criteria": "Builds its own AI software product, not just consulting or courses.\n"
    "Has an explicitly sourced office or team in Bangalore/Bengaluru, India.",
    "queries": "Bengaluru AI product startup official careers HR recruiting email\n"
    "Bangalore AI startup founder official website email",
    "alternate_queries": "Bengaluru AI software startup contact recruiting leadership email",
    "exclusions": "Consulting-only agencies\nCourses/training providers\n"
    "Guessed email patterns and unrelated support-only contacts",
    "confirm": "on",
}


def bridge(runtime, db, run_id):
    def handle(request):
        if request.method != "POST":
            raise PilotStop("Only production research POSTs are allowed in this bridge.")
        if request.url.host == "api.parallel.ai":
            provider, api_path = "parallel", request.url.path
        elif request.url.host == "openrouter.ai" and request.url.path.startswith("/api/v1/"):
            provider, api_path = "openrouter", request.url.path.removeprefix("/api/v1")
        else:
            raise PilotStop("Unexpected production research destination.")
        if api_path not in ("/v1/search", "/v1/extract", "/chat/completions"):
            raise PilotStop("Unexpected production research operation.")
        row = db.one(
            "SELECT * FROM research_calls WHERE run_id=? AND status='reserved' "
            "ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        )
        if not row:
            raise PilotStop("Production spending must be reserved before network I/O.")
        try:
            result = runtime.paid(
                ARM + "/" + row["call_key"],
                ARM,
                provider,
                api_path,
                json.loads(request.content),
                Decimal(row["reserved_micro"]) / 1_000_000,
                tariff=provider == "parallel",
            )
        except PilotStop as exc:
            raise ResearchStop(str(exc)) from exc
        return httpx.Response(200, json=result)

    return httpx.Client(transport=httpx.MockTransport(handle))


def wait(app, run_id):
    while run_id in app.state.research.active:
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=Path("data/research-pilot-v1"))
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live:
        print("Live test requires --confirm-live; no network request was made.")
        return 1
    folder = args.session / ARM
    folder.mkdir(parents=True, exist_ok=True)
    config = Settings(
        _env_file=None,
        db_path=str(folder / "workspace.db"),
        app_password=None,
        oauth_public_url=None,
        allowed_hosts="testserver",
        research_max_budget_usd=0.12,
        research_daily_budget_usd=0.12,
    )
    config.require("parallel_api_key", "openrouter_api_key")
    if not (args.session / "ledger.json").exists():
        raise PilotStop("The original pilot ledger must exist; do not start a fresh ledger.")
    with session_lock(args.session):
        runtime = Runtime(
            args.session,
            {
                "parallel": config.parallel_api_key,
                "openrouter": config.openrouter_api_key,
                "model": config.research_model,
            },
        )
        try:
            app = create_app(
                config,
                research_api=lambda db, key: ResearchAPI(
                    config, db, key, client=bridge(runtime, db, key)
                ),
            )
            client = TestClient(app)
            with PlatformStore(SqliteStore(connect(config.db_path))) as db:
                runs = db.runs()
            if runs:
                run_id = runs[0]["id"]
            else:
                response = client.post("/research/intake", data=BRIEF, follow_redirects=False)
                run_id = response.headers["location"].split("?")[0].split("/")[-1]
            with PlatformStore(SqliteStore(connect(config.db_path))) as db:
                state = db.run(run_id)["status"]
            if state == "draft":
                client.post(
                    f"/research/{run_id}/intake",
                    data=BRIEF | {"action": "plan", "planning_confirm": "on"},
                )
                wait(app, run_id)
            with PlatformStore(SqliteStore(connect(config.db_path))) as db:
                state = db.run(run_id)["status"]
            if state == "awaiting_approval":
                # The operator approved this exact brief and allowed fallback roles.
                client.post(f"/research/{run_id}/approve", data=PLAN)
                wait(app, run_id)
            with PlatformStore(SqliteStore(connect(config.db_path))) as db:
                run, leads = db.run(run_id), db.leads(run_id)
                report = {
                    "status": run["status"],
                    "companies": len(leads),
                    "companies_with_published_email": sum(bool(lead["emails"]) for lead in leads),
                    "all_contacts_pending_review": all(
                        lead["review_status"] == "pending" for lead in leads
                    ),
                    "run_accounted_usd": run["spent"],
                    "combined_pilot_usd": str(runtime.charged()),
                    "real_mail_sent": False,
                    "campaigns_created": 0,
                    "error": run["error"],
                }
                atomic_json(folder / "results.json", {"run": run, "leads": leads})
                atomic_json(folder / "summary.json", report)
            print(json.dumps(report))
            return 0 if run["status"] == "completed" else 1
        finally:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
