"""Workbench-only routes: research input, persisted result, and history."""

import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from jinja2 import ChoiceLoader, DictLoader
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.templating import Jinja2Templates

from outreach.core.workbench import (
    GOAL_FIELDS,
    NO_GOAL,
    CampaignGoal,
    Prospect,
    goal_values,
    parse_prospects,
)
from outreach.core.workbench_claims import draft_context, validate_draft
from outreach.core.research import ResearchStop
from outreach.web.workbench_jobs import WorkbenchRunner
from outreach.web.workbench_view import (
    annotate,
    dashboard,
    duration,
    facts,
    findings,
    references,
    timeline,
)
from outreach.web.security import install_security

HERE = Path(__file__).resolve().parent
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def readable_day(value):
    """'2026-10-15' -> '15 Oct 2026'; unknown values stay honest."""
    text = str(value or "")
    try:
        year, month, day = int(text[:4]), int(text[5:7]), int(text[8:10])
        return f"{day} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return text or "Unknown"


def readable_time(value):
    """ISO timestamp -> '10 Nov 2026, 14:05 UTC' (stored values are UTC)."""
    text = str(value or "")
    if len(text) < 16:
        return readable_day(text)
    return f"{readable_day(text)}, {text[11:16]} UTC"


# The prospect's email is not collected: research never uses it and nothing is sent.
FIELDS = ("name", "company", "role", "website", "profile_url")
GOAL_LABELS = {
    "sender_name": "Your name",
    "sender_company": "Your company",
    "offer": "What you offer",
    "intended_role": "Who it is for",
    "capabilities": "What it does",
    "proof_points": "Results you can prove",
    "looking_for": "Good reasons to reach out",
    "cta": "Closing question",
}


def _eval_headline():
    """The evaluation's headline numbers, for the sign-in page; empty if unavailable."""
    try:
        from outreach.web.workbench_eval import evaluation

        return evaluation()["headline"]
    except (OSError, ValueError, KeyError):
        return []


def create_workbench_app(
    settings,
    open_store,
    provider,
    *,
    mode="fixture",
    limits=None,
    provider_factory=None,
    writer=None,
    writer_factory=None,
    scenarios=(),
):
    # Labelled fictional demo cases; wiring passes them only in fixture mode.
    scenarios = list(scenarios) if mode == "fixture" else []
    runner = WorkbenchRunner(
        open_store,
        provider,
        provider_factory=provider_factory,
        writer=writer,
        writer_factory=writer_factory,
    )

    @asynccontextmanager
    async def lifespan(app):
        with open_store() as db:
            db.recover_workbench_runs()
        yield

    app = FastAPI(title="Outreach Workbench", lifespan=lifespan)
    app.state.workbench_runner = runner
    app.state.workbench_mode = mode
    app.state.open_workbench_store = open_store
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals["mode"] = mode
    templates.env.filters["when"] = readable_time
    templates.env.filters["day"] = readable_day
    templates.env.globals.update(
        # Typical paid cost of each part of a run, measured on the live runs of 12-13 Nov
        # 2026 (research ledger, median): shown before a run so the rep knows the price.
        costs={"thorough": 0.008, "quick": 0.005, "email": 0.012},
        eval_headline=_eval_headline,
        annotate=annotate,
        findings=findings,
        facts=facts,
        references=references,
        timeline=timeline,
        dashboard=dashboard,
        duration=duration,
    )
    templates.env.loader = ChoiceLoader(
        [DictLoader({"login.html": "{% extends 'workbench/login.html' %}"}), templates.env.loader]
    )
    install_security(app, settings, templates)

    # The address changes when the file does, so a deploy never shows a stale page.
    import hashlib

    templates.env.globals["asset_version"] = {
        name: hashlib.sha256((HERE / "static" / name).read_bytes()).hexdigest()[:10]
        for name in ("workbench.css", "workbench.js")
    }

    @app.get("/static/{asset}")
    def asset_file(asset: str):
        if asset not in ("workbench.css", "workbench.js"):
            raise HTTPException(404, "Asset not found.")
        return FileResponse(HERE / "static" / asset)

    def goal_context(goal=None, goal_open=False, has_errors=False):
        """What the shared "Your goal" block needs, on the single and the batch form."""
        with open_store() as db:
            # Example mode keeps the demo goal: its saved sources and drafts were written for it.
            campaign = db.get_campaign_brief() if mode == "fixture" else db.latest_campaign(mode)
            default = db.get_campaign_brief()
        shown = goal if goal is not None else goal_values(campaign)
        return {
            "campaign": campaign,
            "goal": shown,
            "goal_editable": mode != "fixture",
            "goal_is_default": shown == goal_values(default),
            "goal_open": goal_open or bool(has_errors and goal is not None),
            "limits": limits or {},
            "providers_ready": bool(settings.parallel_api_key and settings.openrouter_api_key),
            "options": {"use_goal": True, "write_draft": True, "purpose": "email"},
        }

    def read_goal(submitted):
        """(campaign, goal values, errors) from a submitted form; all None/[] if absent."""
        # A form without goal fields (older clients, scripts) keeps the last saved goal.
        if mode == "fixture" or not any(name in submitted for name in GOAL_FIELDS):
            return None, None, []
        goal = {name: str(submitted.get(name, "")) for name in GOAL_FIELDS}
        try:
            return CampaignGoal.model_validate(goal).campaign(), goal, []
        except ValidationError as exc:
            return (
                None,
                goal,
                [
                    f"{GOAL_LABELS.get(error['loc'][0], 'Goal')}: {error['msg']}"
                    for error in exc.errors(include_input=False)
                ],
            )

    def run_options(submitted):
        """(use the goal?, write an email?). The form sends one choice ("purpose"); older
        clients send the two boxes; with neither, both are on."""
        purpose = submitted.get("purpose")
        if purpose in ("email", "goal", "none"):
            return purpose != "none", purpose == "email"
        if not submitted.get("options"):
            return True, True
        use_goal = submitted.get("use_goal") == "on"
        return use_goal, use_goal and submitted.get("write_draft") == "on"

    def run_limits(write_draft, submitted=None):
        thorough = (submitted or {}).get("depth", "thorough") != "quick"
        return dict(limits or {}) | {"write_draft": int(write_draft), "thorough": int(thorough)}

    def live_problem(submitted):
        if mode != "live":
            return None
        if not (settings.parallel_api_key and settings.openrouter_api_key):
            return (
                "Configure OUTREACH_PARALLEL_API_KEY and OUTREACH_OPENROUTER_API_KEY "
                "before live research."
            )
        if submitted.get("live_consent") != "on":
            return "Review the live research limit and explicitly authorize this run."
        return None

    def batch_form(
        request,
        *,
        text="",
        errors=None,
        status_code=200,
        request_id=None,
        goal=None,
        goal_open=False,
    ):
        with open_store() as db:
            batches = db.list_batches()
        return templates.TemplateResponse(
            request,
            "workbench/batch_new.html",
            {
                **goal_context(goal, goal_open, has_errors=bool(errors)),
                "text": text
                if text or mode != "fixture"
                else "\n".join(
                    f"{s['prospect']['name']}, {s['prospect']['company']}, {s['prospect']['role']}"
                    for s in scenarios
                ),
                "errors": errors or [],
                "request_id": request_id or str(uuid4()),
                "active_page": "batch",
                "batches": batches,
                "max_batch": 20,
            },
            status_code=status_code,
        )

    def goal_page(request, *, goal=None, errors=None, saved=False, status_code=200):
        return templates.TemplateResponse(
            request,
            "workbench/goal.html",
            {
                **goal_context(goal, goal_open=True, has_errors=bool(errors)),
                "errors": errors or [],
                "saved": saved,
                "active_page": "goal",
            },
            status_code=status_code,
        )

    @app.get("/goal")
    def show_goal(request: Request):
        default_asked = "default" in (
            request.query_params.get("reset"),
            request.query_params.get("goal"),
        )
        if default_asked and mode != "fixture":
            with open_store() as db:
                default = goal_values(db.get_campaign_brief())
            return goal_page(request, goal=default)
        return goal_page(request, saved=request.query_params.get("saved") == "1")

    @app.post("/goal")
    async def save_goal(request: Request):
        if mode == "fixture":
            raise HTTPException(409, "Example mode uses the fixed demo goal.")
        submitted = await request.form()
        campaign, goal, errors = read_goal(submitted)
        if errors or campaign is None:
            return goal_page(
                request, goal=goal, errors=errors or ["Fill in the goal."], status_code=422
            )
        with open_store() as db:
            db.set_current_goal(mode, campaign)
        return RedirectResponse("/goal?saved=1", status_code=303)

    @app.get("/batch/new")
    def new_batch(request: Request):
        if request.query_params.get("goal") == "default" and mode != "fixture":
            with open_store() as db:
                default = goal_values(db.get_campaign_brief())
            return batch_form(request, goal=default, goal_open=True)
        return batch_form(request)

    @app.post("/batch")
    async def start_batch(request: Request):
        submitted = await request.form()
        text = str(submitted.get("prospects", ""))
        try:
            request_id = str(UUID(str(submitted.get("request_id", ""))))
        except ValueError:
            return batch_form(
                request,
                text=text,
                errors=["This form has expired. Submit it again."],
                status_code=422,
            )
        prospects, errors = parse_prospects(text)
        campaign, goal, goal_errors = read_goal(submitted)
        errors = [*errors, *goal_errors]
        if not errors and (problem := live_problem(submitted)):
            errors = [problem.replace("this run", "this batch")]
        if errors:
            return batch_form(
                request, text=text, errors=errors, status_code=422, request_id=request_id, goal=goal
            )
        use_goal, write_draft = run_options(submitted)
        with open_store() as db:
            if not use_goal:
                campaign = NO_GOAL
            elif goal is not None:
                campaign = db.set_current_goal(mode, campaign)
            elif mode == "fixture":
                campaign = db.get_campaign_brief()
            else:
                campaign = db.latest_campaign(mode)
            batch_id, created = db.create_batch(
                request_id,
                prospects,
                campaign,
                mode=mode,
                limits=run_limits(write_draft, submitted),
            )
            keys = [run["id"] for run in db.get_batch(batch_id)["runs"]]
        if created:
            runner.start_batch(keys)
        # A list is reviewed one prospect at a time, on the same page as a single run.
        return RedirectResponse(f"/runs/{keys[0]}", status_code=303)

    def saved_batch(batch_id):
        with open_store() as db:
            batch = db.get_batch(batch_id)
        if batch is None:
            raise HTTPException(404, "Batch not found.")
        return batch

    @app.get("/batches/{batch_id}")
    def batch_detail(request: Request, batch_id: str):
        return templates.TemplateResponse(
            request, "workbench/batch.html", {"batch": saved_batch(batch_id), "active_page": "batch"}
        )

    @app.get("/batches/{batch_id}/status")
    def batch_status(batch_id: str):
        batch = saved_batch(batch_id)
        return {
            "id": batch["id"],
            "runs": [
                {
                    "id": run["id"],
                    "execution_status": run["execution_status"],
                    "business_outcome": run["business_outcome"],
                    "review": (run.get("review") or {}).get("state"),
                }
                for run in batch["runs"]
            ],
        }

    @app.get("/batches/{batch_id}/export")
    def batch_export(batch_id: str):
        """Every individually approved email in the batch, as one text file."""
        parts = []
        with open_store() as db:
            batch = db.get_batch(batch_id)
            if batch is None:
                raise HTTPException(404, "Batch not found.")
            for run in batch["runs"]:
                try:
                    draft = db.approved_export(run["id"])
                except ValueError:
                    continue
                parts.append(
                    f"To: {run['prospect']['name']}, {run['prospect']['company']}\n"
                    f"Subject: {draft['subject']}\n\n{draft['body']}\n"
                )
        if not parts:
            return PlainTextResponse("No email in this batch is approved yet.", status_code=409)
        return PlainTextResponse(
            ("\n" + "-" * 60 + "\n\n").join(parts),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="outreach-batch-{batch_id}.txt"',
            },
        )

    def form(
        request,
        *,
        values=None,
        errors=None,
        status_code=200,
        request_id=None,
        chosen=None,
        goal=None,
        goal_open=False,
    ):
        shared = goal_context(goal, goal_open, bool(errors))
        return templates.TemplateResponse(
            request,
            "workbench/new.html",
            {
                "values": values
                if values is not None
                else (
                    {
                        "name": "Maya Rao",
                        "company": "Cedar Works",
                        "role": "Finance Director",
                    }
                    if mode == "fixture"
                    else {}
                ),
                "errors": errors or [],
                "request_id": request_id or str(uuid4()),
                **shared,
                "active_page": "new",
                "live_consent": False,
                "scenarios": scenarios,
                "chosen_scenario": chosen,
            },
            status_code=status_code,
        )

    @app.get("/")
    def home():
        return RedirectResponse("/research/new", status_code=303)

    @app.get("/research/new")
    def new_research(request: Request):
        previous = request.query_params.get("from_run")
        if previous:
            run = saved_run(previous)
            goal = goal_values(run["campaign"]) if mode != "fixture" else None
            return form(request, values=run["prospect"], goal=goal)
        if request.query_params.get("goal") == "default" and mode != "fixture":
            with open_store() as db:
                default = goal_values(db.get_campaign_brief())
            return form(request, goal=default, goal_open=True)
        key = request.query_params.get("scenario", "")
        scenario = next((s for s in scenarios if s["key"] == key), None)
        if mode == "fixture" and scenario:
            return form(request, values=dict(scenario["prospect"]), chosen=key)
        return form(request)

    @app.post("/research")
    async def start_research(request: Request):
        submitted = await request.form()
        values = {name: str(submitted.get(name, "")) for name in FIELDS}
        try:
            request_id = str(UUID(str(submitted.get("request_id", ""))))
        except ValueError:
            return form(
                request,
                values=values,
                errors=["This form has expired. Check your input and submit again."],
                status_code=422,
            )
        try:
            prospect = Prospect.model_validate(values)
        except ValidationError as exc:
            errors = [
                f"{error['loc'][0].replace('_', ' ').capitalize()}: {error['msg']}"
                for error in exc.errors(include_input=False)
            ]
            return form(
                request, values=values, errors=errors, request_id=request_id, status_code=422
            )
        goal = None
        # A form without goal fields (older clients, scripts) keeps the last saved goal.
        if mode != "fixture" and any(name in submitted for name in GOAL_FIELDS):
            goal = {name: str(submitted.get(name, "")) for name in GOAL_FIELDS}
            try:
                campaign = CampaignGoal.model_validate(goal).campaign()
            except ValidationError as exc:
                errors = [
                    f"{GOAL_LABELS.get(error['loc'][0], 'Goal')}: {error['msg']}"
                    for error in exc.errors(include_input=False)
                ]
                return form(
                    request,
                    values=values,
                    errors=errors,
                    request_id=request_id,
                    status_code=422,
                    goal=goal,
                )
        if mode == "live":
            if not (settings.parallel_api_key and settings.openrouter_api_key):
                return form(
                    request,
                    values=values,
                    request_id=request_id,
                    status_code=422,
                    goal=goal,
                    errors=[
                        "Configure OUTREACH_PARALLEL_API_KEY and "
                        "OUTREACH_OPENROUTER_API_KEY before live research."
                    ],
                )
            if submitted.get("live_consent") != "on":
                return form(
                    request,
                    values=values,
                    request_id=request_id,
                    status_code=422,
                    goal=goal,
                    errors=["Review the live research limit and explicitly authorize this run."],
                )
        use_goal, write_draft = run_options(submitted)
        try:
            with open_store() as db:
                if not use_goal:
                    campaign = NO_GOAL
                elif goal is not None:
                    campaign = db.set_current_goal(mode, campaign)
                elif mode == "fixture":
                    campaign = db.get_campaign_brief()
                else:
                    campaign = db.latest_campaign(mode)
                key, created = db.submit(
                    prospect.model_dump(mode="json"),
                    request_id,
                    campaign,
                    mode=mode,
                    limits=run_limits(write_draft, submitted),
                )
        except ValueError:
            return form(
                request,
                values=values,
                errors=[
                    "That submission was already used with different input. "
                    "Check this form and start a new run."
                ],
                status_code=409,
            )
        if created:
            runner.start(key)
        return RedirectResponse(f"/runs/{key}", status_code=303)

    def saved_run(key):
        with open_store() as db:
            run = db.get_workbench_run(key)
        if run is None:
            raise HTTPException(404, "Research run not found.")
        return run

    def batch_position(run_id):
        """Where this prospect sits in its list, and how every other one is doing."""
        with open_store() as db:
            place = db.batch_of(run_id)
            if not place:
                return None
            batch = db.get_batch(place["id"])
        steps = []
        for run in batch["runs"]:
            review = (run.get("review") or {}).get("state") if run.get("draft") else None
            if run["execution_status"] in ("queued", "running"):
                state = "working"
            elif review == "approved":
                state = "approved"
            elif review == "ready_for_review" or run.get("business_outcome") == "research_ready":
                state = "ready"
            else:
                state = "attention"
            steps.append({"id": run["id"], "name": run["prospect"]["name"], "state": state})
        return {**place, "runs": steps}

    def run_page(
        request,
        run_id,
        *,
        error=None,
        error_title="Confirmation not accepted",
        edited=None,
        status_code=200,
    ):
        return templates.TemplateResponse(
            request,
            "workbench/run.html",
            {
                "run": saved_run(run_id),
                "batch": batch_position(run_id),
                "active_page": "run",
                "error": error,
                "error_title": error_title,
                "edited": edited,
            },
            status_code=status_code,
        )

    def revision_number(value):
        try:
            return int(str(value))
        except ValueError:
            return 0

    @app.get("/runs/{run_id}")
    def run_detail(request: Request, run_id: str):
        return run_page(request, run_id)

    @app.get("/runs/{run_id}/status")
    def run_status(run_id: str):
        return saved_run(run_id)

    @app.post("/runs/{run_id}/confirm-prospect")
    async def confirm_prospect(request: Request, run_id: str):
        run = saved_run(run_id)
        if run["mode"] != mode:
            return run_page(
                request,
                run_id,
                error="Open this run in its original research mode before confirming.",
                status_code=409,
            )
        fields = await request.form()
        try:
            with open_store() as db:
                db.confirm_workbench_identity(
                    run_id,
                    str(fields.get("candidate_id", "")),
                    str(fields.get("evidence_version", "")),
                )
        except (ValueError, ResearchStop) as exc:
            # Re-render the saved run so a stale or refused choice is explained in place.
            return run_page(request, run_id, error=str(exc), status_code=409)
        runner.start(run_id)
        return RedirectResponse(f"/runs/{run_id}", status_code=303)

    @app.post("/runs/{run_id}/draft/check")
    async def check_edits(request: Request, run_id: str):
        """Recheck reviewer text on the server and save it as a new revision."""
        run = saved_run(run_id)
        fields = await request.form()
        edited = {
            "subject": " ".join(str(fields.get("subject", "")).split())[:200],
            "body": str(fields.get("body", "")).replace("\r\n", "\n").strip()[:4000],
        }
        remove = " ".join(str(fields.get("remove", "")).split())
        claims = None
        replace = " ".join(str(fields.get("replace", "")).split())
        if replace and fields.get("remove_it"):
            remove, replace = replace, ""
        if replace and run.get("draft"):
            # "Edit this sentence": swap one sentence where it stands. Its source and
            # rating follow the new wording, which is then checked against that source.
            current_draft = run["draft"]
            replacement = " ".join(str(fields.get("replacement", "")).split())[:600]
            edited = {"subject": current_draft["subject"], "body": current_draft["body"]}
            if replace == current_draft["subject"]:
                edited["subject"] = replacement[:200]
            elif replacement:
                edited["body"] = current_draft["body"].replace(replace, replacement, 1)
            else:
                remove = replace
            claims = [
                {**claim, "text": replacement} if claim.get("text") == replace else claim
                for claim in current_draft["claims"]
            ]
        if fields.get("remove_optional") and run.get("draft"):
            # "Remove them": drop every sentence the writer rated optional, then check.
            current_draft = run["draft"]
            body = current_draft["body"]
            for segment in current_draft["check"].get("segments", []):
                if segment.get("relevance") == "optional" and segment.get("part") == "body":
                    body = re.sub(
                        r"[ \t]*" + re.escape(segment["text"]) + r"[ \t]*", " ", body, count=1
                    )
            edited = {
                "subject": current_draft["subject"],
                "body": re.sub(r" *\n *", "\n", body).strip(),
            }
        if remove and run.get("draft") and not fields.get("remove_optional"):
            # "Remove this sentence": drop it from the saved email and check the rest.
            current_draft = run["draft"]
            edited = {"subject": current_draft["subject"], "body": current_draft["body"]}
            if remove == current_draft["subject"]:
                edited["subject"] = ""
            else:
                edited["body"] = re.sub(
                    r"[ \t]*" + re.escape(remove) + r"[ \t]*", " ", current_draft["body"], count=1
                )
                edited["body"] = re.sub(r" *\n *", "\n", edited["body"]).strip()
        current = run.get("draft")
        if not current:
            return run_page(
                request,
                run_id,
                error="This run has no draft to check.",
                error_title="Edits not checked",
                status_code=409,
            )
        unchanged = (edited["subject"], edited["body"]) == (current["subject"], current["body"])
        if unchanged and run["review"]["state"] in ("ready_for_review", "needs_revision"):
            return RedirectResponse(f"/runs/{run_id}#draft", status_code=303)
        # Citations carry forward only where their exact text survived the edit.
        draft = {**edited, "claims": claims or current["claims"]}
        draft["check"] = validate_draft(draft, draft_context(run))
        try:
            with open_store() as db:
                db.save_reviewer_revision(
                    run_id, revision_number(fields.get("base_revision", "")), draft
                )
        except ValueError as exc:
            return run_page(
                request,
                run_id,
                error=str(exc),
                error_title="Edits not saved",
                edited=edited,
                status_code=409,
            )
        return RedirectResponse(f"/runs/{run_id}#draft", status_code=303)

    @app.post("/runs/{run_id}/draft/approve")
    async def approve_draft(request: Request, run_id: str):
        saved_run(run_id)
        fields = await request.form()
        try:
            with open_store() as db:
                db.approve_draft(
                    run_id,
                    revision_number(fields.get("revision", "")),
                    str(fields.get("content_hash", "")),
                    lambda run: validate_draft(run["draft"], draft_context(run)),
                )
        except ValueError as exc:
            return run_page(
                request,
                run_id,
                error=str(exc),
                error_title="Draft not approved",
                status_code=409,
            )
        return RedirectResponse(f"/runs/{run_id}#draft", status_code=303)

    @app.post("/runs/{run_id}/draft/write")
    async def write_draft(request: Request, run_id: str):
        """Write the email for a saved hook (one model request in live mode).

        With a fact selection, rewrites the email using only the ticked facts."""
        run = saved_run(run_id)
        fields = await request.form()
        if run["campaign"].get("no_goal"):
            return run_page(
                request,
                run_id,
                error="This run was research only, without a goal. Start it again with your "
                "goal to get an email.",
                error_title="Draft not written",
                status_code=409,
            )
        exclude, include = [], []
        if fields.get("choose_facts"):
            offered = {str(v) for v in fields.getlist("offered")}
            keep = {str(v) for v in fields.getlist("use")}
            exclude = sorted(offered - keep)
            context_ids = {
                s.get("source_id") for s in (run["result"] or {}).get("context_signals") or []
            }
            include = sorted(keep & context_ids)
            if not keep & offered:
                return run_page(
                    request,
                    run_id,
                    error="Tick at least one fact to write the email from.",
                    error_title="Draft not rewritten",
                    status_code=422,
                )
        if run["mode"] != mode:
            return run_page(
                request,
                run_id,
                error="Open this run in its original research mode to write its draft.",
                error_title="Draft not written",
                status_code=409,
            )
        try:
            stopped = await run_in_threadpool(
                runner.write_draft,
                run_id,
                exclude or ("__rewrite__",) if fields.get("choose_facts") else (),
                include,
            )
        except ValueError as exc:
            return run_page(
                request, run_id, error=str(exc), error_title="Draft not written", status_code=409
            )
        if stopped:
            return run_page(
                request,
                run_id,
                error=stopped,
                error_title="The draft could not be written",
                status_code=502,
            )
        return RedirectResponse(f"/runs/{run_id}#draft", status_code=303)

    @app.post("/runs/{run_id}/draft/reject")
    async def reject_draft(request: Request, run_id: str):
        saved_run(run_id)
        fields = await request.form()
        try:
            with open_store() as db:
                db.reject_draft(
                    run_id,
                    revision_number(fields.get("revision", "")),
                    str(fields.get("note", "")),
                )
        except ValueError as exc:
            return run_page(
                request,
                run_id,
                error=str(exc),
                error_title="Draft not rejected",
                status_code=409,
            )
        return RedirectResponse(f"/runs/{run_id}#draft", status_code=303)

    @app.get("/runs/{run_id}/export")
    def export_draft(run_id: str, download: bool = False):
        """Copy/export is server-enforced: only the exact approved revision leaves Workbench."""
        saved_run(run_id)
        try:
            with open_store() as db:
                draft = db.approved_export(run_id)
        except ValueError as exc:
            return PlainTextResponse(str(exc), status_code=409)
        headers = {"Cache-Control": "no-store"}
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="outreach-draft-{run_id}-r{draft["revision"]}.txt"'
            )
        return PlainTextResponse(
            f"Subject: {draft['subject']}\n\n{draft['body']}\n", headers=headers
        )

    @app.get("/evaluation")
    def evaluation_page(request: Request):
        """How the workbench did on real prospects: saved results, no paid call."""
        from outreach.web.workbench_eval import evaluation

        return templates.TemplateResponse(
            request, "workbench/evaluation.html", {"report": evaluation(), "active_page": "evaluation"}
        )

    @app.get("/history")
    def history(request: Request):
        with open_store() as db:
            runs = db.list_workbench_runs()
            showcase = db.showcase_ids()
        return templates.TemplateResponse(
            request,
            "workbench/history.html",
            {"runs": runs, "showcase": showcase, "active_page": "history"},
        )

    return app
