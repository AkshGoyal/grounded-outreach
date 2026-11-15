"""Disposable local browser QA server. Fictional data; no real credentials or APIs."""

import argparse
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import uvicorn
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

from outreach.adapters.research_api import ResearchAPI
from outreach.config import Settings
from outreach.core.models import InboundMessage
from outreach.web.app import create_app
from tests.test_campaign_acceptance import CampaignLLM, ai_research
from tests.test_platform import VerifiedMailbox, db_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8779)
    parser.add_argument("--no-auth", action="store_true", help="Disposable visual QA only")
    args = parser.parse_args()
    for key in list(os.environ):
        if key.startswith("OUTREACH_") or key in (
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "PARALLEL_API_KEY",
        ):
            del os.environ[key]
    with tempfile.TemporaryDirectory(prefix="outreach-browser-qa-") as directory:
        os.chdir(directory)
        settings = Settings(
            _env_file=None,
            db_path=str(Path(directory) / "outreach.db"),
            app_password=None if args.no_auth else "offline-workspace-qa",
            parallel_api_key="fake",
            openrouter_api_key="fake",
            send_gap_seconds=0,
        )
        boxes = {"career@gmail.com": VerifiedMailbox(), "sales@example.com": VerifiedMailbox()}
        import outreach.web.app as app_module

        app_module.build_llm = lambda config: CampaignLLM()
        calls = []
        app = create_app(
            settings,
            mailbox=lambda identity: boxes[str(identity.sender_email)],
            research_api=lambda db, key: ResearchAPI(
                settings,
                db,
                key,
                client=httpx.Client(transport=httpx.MockTransport(ai_research(calls))),
            ),
        )

        if args.no_auth:

            @app.middleware("http")
            async def allow_disposable_qa_frame(request, call_next):
                response = await call_next(request)
                response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
                return response

        @app.get("/qa/guided", response_class=HTMLResponse)
        def guided_browser_test():
            return (
                Path(__file__).resolve().parents[1] / "browser/guided_workspace.html"
            ).read_text(encoding="utf-8")

        @app.get("/qa/state")
        def qa_state():
            with db_for(settings) as db:
                return {
                    "calls": len(calls),
                    "runs": [
                        {"id": r["id"], "status": r["status"], "spent": r["spent_micro"]}
                        for r in db.runs()
                    ],
                    "sent": sum(len(box.sent) for box in boxes.values()),
                }

        @app.post("/qa/progress")
        def simulate_progress(run_id: str = Form(...), status: str = Form(...)):
            if status not in ("running", "completed"):
                raise HTTPException(400, "Choose a fictional progress state.")
            with db_for(settings) as db:
                if not db.run(run_id):
                    raise HTTPException(404, "Fictional run not found.")
                db.set_run(
                    run_id,
                    status=status,
                    progress="Checking published evidence for a fictional company.",
                )
            if status == "running":
                app.state.research.active.add(run_id)
            else:
                app.state.research.active.discard(run_id)
            return {"simulated": True}

        @app.post("/qa/zero-result")
        def simulate_zero_result():
            from outreach.core.intake import AudienceIntake
            from tests.test_audience_intake import complete
            from tests.test_research_recovery import saved_zero_result

            values = complete()
            with db_for(settings) as db:
                key = db.new_run(
                    title="Fictional cached recovery",
                    brief=values["brief"],
                    purpose="sales",
                    tags="",
                    project_id=None,
                    target=1,
                    budget=100000,
                )
                db.save_intake(
                    key,
                    AudienceIntake(
                        goal=values["brief"],
                        company_type="Textile mills",
                        geography="Anywhere",
                        contact_roles=["general"],
                    ),
                    title="Fictional cached recovery",
                    purpose="sales",
                    target=1,
                    budget=100000,
                )
            saved_zero_result(settings, key)
            return {"id": key}

        @app.get("/qa/preview", response_class=HTMLResponse)
        def mobile_preview():
            return """<!doctype html><meta charset="utf-8"><title>Fictional mobile preview</title>
            <style>body{margin:0;background:#f5f8f6}iframe{width:390px;height:1000px;border:0}</style>
            <iframe src="/research/new" title="Fictional audience"></iframe><script>
            document.querySelector('iframe').onload = event => {
              const form=event.target.contentDocument.querySelector('.audience-form');
              form.querySelector('[name=brief]').value=
                'Find AI startups in Bangalore for job opportunities. Contact HR recruiters.';
              form.querySelector('[name=brief]').dispatchEvent(new Event('input',{bubbles:true}));
            };</script>"""

        @app.post("/qa/reply")
        def simulate_reply(body: str = Form("Happy to talk.")):
            box = boxes["career@gmail.com"]
            if not box.sent:
                raise HTTPException(400, "No simulated career outreach yet.")
            original = box.sent[0]
            box._replies.append(
                InboundMessage(
                    message_id=f"<qa-{len(box._replies)}@atlas-ai.example>",
                    from_address=original.to,
                    subject="Re: " + original.subject,
                    body_text=body,
                    received_at=datetime.now(UTC) + timedelta(minutes=1),
                    in_reply_to=original.message_id,
                )
            )
            return {"simulated": True}

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
