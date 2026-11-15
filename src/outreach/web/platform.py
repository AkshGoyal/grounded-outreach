"""Browser workflow. Concrete storage and provider factories are injected by app.py."""

import os
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import EmailStr, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from outreach.campaigns import is_valid_id, load_closing, load_copy, save_texts
from outreach.config import ConfigError
from outreach.core.attachments import manifests
from outreach.core.audience_plan import local_plan
from outreach.core.discovery import recover_saved_discovery
from outreach.core.intake import CONTACT_ROLES, LEAD_STAGES, AudienceIntake, lead_stage
from outreach.core.message_brief import MessageBrief
from outreach.core.prompt_intake import audience_from_prompt, prompt_purpose
from outreach.core.research import ResearchPlan
from outreach.ports.mail import MailError
from outreach.web.processes import process_alive
from outreach.web.research_view import continuation, request_summary

PURPOSES = ("sales", "job search", "partnerships", "other")
STATES = ("draft", "active", "paused", "completed", "archived")


def redirect(path, message=""):
    separator = "&" if "?" in path else "?"
    return RedirectResponse(
        path + (separator + "message=" + quote(message) if message else ""), 303
    )


def install_platform(
    app, settings, templates, open_store, vault, mailbox, profile, research, sender, drafter
):
    def render(request, page, **context):
        context["filter_statuses"] = (
            STATES
            if request.url.path.startswith("/campaigns")
            else (
                "draft",
                "planning",
                "awaiting_approval",
                "running",
                "paused",
                "completed",
                "failed",
            )
            if request.url.path.startswith("/research")
            else ()
        )
        return templates.TemplateResponse(request, page, context)

    def options(db):
        return {
            "projects": db.projects(),
            "purposes": PURPOSES,
            "accounts": db.accounts(),
            "campaigns": db.rows(
                "SELECT c.*,s.purpose,s.tags,COALESCE(s.status,'draft') AS status,"
                "s.project_id,a.email AS sender_email FROM campaigns c "
                "LEFT JOIN campaign_settings s ON s.campaign_id=c.id "
                "LEFT JOIN mail_accounts a ON a.id=s.sender_account_id ORDER BY c.created_at DESC"
            ),
        }

    def project(db, value):
        if value and not db.one("SELECT id FROM projects WHERE id=?", (value,)):
            raise ValueError("Choose an existing project.")
        return value or None

    def purpose(value):
        if value not in PURPOSES:
            raise ValueError("Choose a campaign purpose.")
        return value

    def ids(form):
        values = list(dict.fromkeys(int(v) for v in form.getlist("lead_ids")))
        if not values or len(values) > 250:
            raise ValueError("Select between 1 and 250 leads.")
        return values

    def return_path(form):
        path = form.get("return_to", "/lists")
        return (
            path
            if path.startswith(("/research/", "/lists/", "/leads/")) and not path.startswith("//")
            else "/lists"
        )

    def paid_unavailable(destination):
        if destination.startswith("/research/"):
            with open_store() as db:
                run = db.run(destination.split("?")[0].split("/")[-1])
                if run and (run["archived"] or run["deleted"]):
                    return redirect(
                        destination, "Restore this audience before editing or starting research."
                    )
        if settings.local_network_restricted:
            return redirect(
                destination,
                "Your audience is saved. Live research needs a restart from "
                "START-OUTREACH.cmd in your laptop folder. No new paid request was made.",
            )
        return None

    @app.get("/research")
    def research_home(
        request: Request,
        q: str = "",
        project_id: str = "",
        purpose_filter: str = "",
        status: str = "",
        view: str = "",
    ):
        with open_store() as db:
            runs = [
                r
                for r in db.audiences(include_archived=True, include_deleted=True)
                if r["deleted"] == (view == "deleted")
                and (view == "deleted" or r["archived"] == (view == "archived"))
                and (not project_id or r["project_id"] == project_id)
                and (not purpose_filter or r["purpose"] == purpose_filter)
                and (not status or r["status"] == status)
                and q.casefold() in (r["title"] + " " + r["brief"] + " " + r["tags"]).casefold()
            ]
            for run in runs:
                run["next_step"] = continuation(db, run, run["id"] in research.active)
            return render(
                request,
                "research.html",
                runs=runs,
                **options(db),
                max_budget=settings.research_max_budget_usd,
                keys_ready=bool(settings.parallel_api_key and settings.openrouter_api_key),
            )

    @app.get("/research/new")
    def research_intake(request: Request):
        with open_store() as db:
            return render(
                request,
                "research_intake.html",
                intake={},
                run=None,
                contact_roles=CONTACT_ROLES,
                max_budget=settings.research_max_budget_usd,
                default_budget=min(0.5, settings.research_max_budget_usd),
                **options(db),
            )

    @app.get("/campaigns/{campaign_id}/research")
    def campaign_research(request: Request, campaign_id: str, source: str = ""):
        with open_store() as db:
            campaign = db.campaign(campaign_id)
            if not campaign:
                raise HTTPException(404, "Campaign not found.")
            related = db.campaign_runs(campaign_id)
            original = (
                db.run(source) if source else next((run for run in related if run["intake"]), None)
            )
            if source and not original:
                raise HTTPException(404, "Audience not found.")
            for batch in related:
                batch["lead_count"] = db.one(
                    "SELECT COUNT(*) AS n FROM research_leads WHERE run_id=?", (batch["id"],)
                )["n"]
            count = db.one(
                "SELECT COUNT(*) AS n FROM contacts WHERE campaign_id=?", (campaign_id,)
            )["n"]
            return render(
                request,
                "campaign_research.html",
                campaign_id=campaign_id,
                metadata=campaign,
                campaign_context=campaign,
                tab="research",
                run=None,
                intake=original["intake"] or {"goal": original["brief"]} if original else {},
                editing_full=True,
                intake_action=f"/campaigns/{campaign_id}/research",
                save_label="Save next research batch (free)",
                form_values={
                    "title": (campaign["name"][:90] + " — more contacts"),
                    "purpose": original["purpose"] if original else campaign["purpose"] or "sales",
                    "target": original["target_count"] if original else 5,
                    "budget": min(original["budget"], settings.research_max_budget_usd)
                    if original
                    else min(0.5, settings.research_max_budget_usd),
                },
                source_run=original,
                related_runs=related,
                saved_audiences=[run for run in db.audiences() if run["intake"]],
                contact_count=count,
                campaign_open=campaign["status"] not in ("archived", "completed"),
                contact_roles=CONTACT_ROLES,
                max_budget=settings.research_max_budget_usd,
                default_budget=min(0.5, settings.research_max_budget_usd),
                **options(db),
            )

    @app.post("/campaigns/{campaign_id}/research")
    @app.post("/research/intake")
    @app.post("/research/{run_id}/intake")
    @app.post("/research/{run_id}/revise")
    async def save_audience(request: Request, run_id: str = "", campaign_id: str = ""):
        form = await request.form()
        campaign_context = None
        if campaign_id:
            with open_store() as db:
                campaign_context = db.campaign(campaign_id)
                if not campaign_context:
                    raise HTTPException(404, "Campaign not found.")
                if campaign_context["status"] in ("archived", "completed"):
                    raise HTTPException(
                        409, "Reopen this campaign before researching more contacts."
                    )
        revision_of = run_id if request.url.path.endswith("/revise") else ""
        if revision_of:
            with open_store() as db:
                campaign_context = db.research_campaign(revision_of)
                if not db.run(revision_of):
                    raise HTTPException(404, "Original audience not found.")
            campaign_id = campaign_context["id"] if campaign_context else ""
            run_id = ""
        destination = "/research/" + run_id if run_id else "/research/new"
        try:
            intake = AudienceIntake(
                goal=form.get("brief", "").strip(),
                company_type=form.get("company_type", "").strip(),
                geography=form.get("geography", "").strip(),
                contact_roles=form.getlist("contact_roles"),
                must_haves=form.get("must_haves", "").strip(),
                exclusions=form.get("audience_exclusions", "").strip(),
                personalisation=form.get("personalisation", "").strip(),
                research_mode=form.get("research_mode", "flexible"),
                seed_websites=form.get("seed_websites", "").strip(),
            )
            prompt_input = (
                form.get("input_mode") == "prompt" and form.get("action") != "save_details"
            )
            if prompt_input:
                intake = audience_from_prompt(
                    form.get("brief", "").strip(),
                    research_mode=form.get("research_mode", "focused"),
                    seed_websites=form.get("seed_websites", "").strip(),
                )
            if len(intake.research_brief()) > 8000:
                raise ValueError("Keep the combined audience brief below 8,000 characters.")
            target = int(form.get("target", "5"))
            budget = Decimal(form.get("budget", str(min(0.5, settings.research_max_budget_usd))))
            if (
                not 1 <= target <= 25
                or not budget.is_finite()
                or not Decimal(".10") <= budget <= Decimal(str(settings.research_max_budget_usd))
            ):
                raise ValueError("Choose 1–25 companies and a budget within the displayed limit.")
            title = (form.get("title", "").strip() or intake.goal[:80])[:120]
            intent = purpose(form.get("purpose") or prompt_purpose(intake.goal))
            with open_store() as db, db.transaction():
                if not run_id:
                    run_id = db.new_run(
                        engine_version=2,
                        strategy_version=6,
                        title=title,
                        brief=intake.goal,
                        purpose=intent,
                        tags="",
                        project_id=None,
                        target=target,
                        budget=int(budget * 1_000_000),
                    )
                db.save_intake(
                    run_id,
                    intake,
                    title=title,
                    purpose=intent,
                    target=target,
                    budget=int(budget * 1_000_000),
                )
                if campaign_id:
                    parent = form.get("parent_run", "")
                    if parent:
                        source = db.run(parent)
                        if not source or source["deleted"] or source["archived"]:
                            raise ValueError("Choose an active saved audience for this batch.")
                        db.save_execution(run_id, parent_run=parent)
                    db.link_research(campaign_id, run_id)
                    db.message(
                        run_id,
                        "assistant",
                        f"Research batch for /campaigns/{campaign_id}. "
                        "Review and approve contacts before adding them. "
                        "Nothing is sent automatically.",
                    )
                if revision_of:
                    db.save_execution(run_id, parent_run=revision_of)
                    db.message(
                        run_id,
                        "assistant",
                        f"Revised from /research/{revision_of}. "
                        "Original research and spending remain unchanged.",
                    )
            destination = "/research/" + run_id
            if form.get("action") == "plan_local" or (
                form.get("action") in ("save_prompt", "save_details") and not intake.questions()
            ):
                plan = local_plan(intake)
                with open_store() as db, db.transaction():
                    db.set_run(
                        run_id,
                        plan_json=plan.model_dump_json(),
                        status="awaiting_approval",
                        progress="Free plan ready. Review it before approving paid research.",
                    )
                    db.save_execution(run_id, plan_source="local")
                return redirect(
                    destination, "Plan prepared for free. No provider request was made."
                )
            if form.get("action") == "plan" and not revision_of and not campaign_id:
                blocked = paid_unavailable(destination)
                if blocked:
                    return blocked
                if intake.questions():
                    return redirect(
                        destination,
                        "Answer the audience questions below before creating a paid plan.",
                    )
                if not form.get("planning_confirm"):
                    return redirect(
                        destination, "Confirm the paid planning request before continuing."
                    )
                if not settings.parallel_api_key or not settings.openrouter_api_key:
                    return redirect(
                        destination,
                        "Your brief is saved. Configure the research providers before planning.",
                    )
                research.start(run_id, planning=True)
                return redirect(destination)
            return redirect(
                destination,
                "Next version saved under this audience for free. Original research is unchanged. "
                "Prepare the free plan, then approve paid research when ready."
                if revision_of
                else "Research batch saved for free. Approve a plan, review the results, "
                "then add approved contacts to your campaign."
                if campaign_id
                else "Audience saved. No API spend. Complete it whenever you are ready.",
            )
        except (ValueError, InvalidOperation) as exc:
            problem = (
                str(exc)
                if isinstance(exc, ValueError) and not isinstance(exc, ValidationError)
                else "Check the company target (1–25) and the displayed spending limit."
            )
            if isinstance(exc, ValidationError):
                labels = {
                    "goal": "Goal: use 20–6,500 characters.",
                    "seed_websites": "Use Company name | https://company-website, up to 10 lines.",
                    "company_type": "Company type: keep it under 300 characters.",
                    "geography": "Location: keep it under 300 characters.",
                    "contact_roles": "Contacts: choose one of the displayed roles.",
                    "must_haves": "Must-haves: keep it under 300 characters.",
                    "exclusions": "Exclusions: keep them under 300 characters.",
                    "personalisation": "Email details: keep them under 300 characters.",
                }
                problem = " ".join(
                    dict.fromkeys(
                        labels.get(error["loc"][0], "Check your audience details.")
                        for error in exc.errors(include_input=False)
                    )
                )
            with open_store() as db:
                saved = db.run(run_id) if run_id else None
                if saved and (saved["status"] != "draft" or saved["plan"] or saved["spent_micro"]):
                    return redirect(
                        destination,
                        "Started research keeps its audience. Create a new brief to change it.",
                    )
                response = render(
                    request,
                    "research_intake.html",
                    run=saved,
                    intake={
                        "goal": form.get("brief", ""),
                        "company_type": form.get("company_type", ""),
                        "geography": form.get("geography", ""),
                        "contact_roles": form.getlist("contact_roles"),
                        "must_haves": form.get("must_haves", ""),
                        "exclusions": form.get("audience_exclusions", ""),
                        "personalisation": form.get("personalisation", ""),
                        "research_mode": form.get("research_mode", "flexible"),
                    },
                    form_values=dict(form),
                    editing_full=bool(campaign_id or revision_of or form.get("edit_view")),
                    campaign_context=campaign_context,
                    intake_action=f"/research/{revision_of}/revise"
                    if revision_of
                    else f"/campaigns/{campaign_id}/research"
                    if campaign_id
                    else None,
                    save_label="Save next version of this audience"
                    if revision_of
                    else "Save next research batch (free)"
                    if campaign_id
                    else None,
                    form_error=problem + " Your entries are kept below.",
                    contact_roles=CONTACT_ROLES,
                    max_budget=settings.research_max_budget_usd,
                    default_budget=min(0.5, settings.research_max_budget_usd),
                    **options(db),
                )
                response.status_code = 400
                return response

    @app.post("/projects")
    async def create_project(request: Request):
        form = await request.form()
        try:
            name = form.get("name", "").strip()
            if not 1 <= len(name) <= 100:
                raise ValueError("Give the project a name up to 100 characters.")
            with open_store() as db:
                db.add_project(
                    name, purpose(form.get("purpose", "sales")), form.get("tags", "")[:200]
                )
            return redirect("/research", "Project created.")
        except ValueError as exc:
            return redirect("/research", str(exc))

    @app.post("/research")
    async def create_research(request: Request):
        form = await request.form()
        try:
            brief = form.get("brief", "").strip()
            title = form.get("title", "").strip() or brief[:80]
            target = int(form.get("target", "5"))
            budget = Decimal(form.get("budget", ".50"))
            if not 20 <= len(brief) <= 8000 or not 1 <= target <= 25:
                raise ValueError(
                    "Describe your audience in 20–8,000 characters and choose 1–25 companies."
                )
            if not budget.is_finite() or not Decimal(".10") <= budget <= Decimal(
                str(settings.research_max_budget_usd)
            ):
                raise ValueError("Choose a budget within the displayed spending limit.")
            with open_store() as db:
                key = db.new_run(
                    engine_version=2,
                    strategy_version=6,
                    title=title[:120],
                    brief=brief,
                    purpose=purpose(form.get("purpose", "sales")),
                    tags=form.get("tags", "")[:200],
                    project_id=project(db, form.get("project_id")),
                    target=target,
                    budget=int(budget * 1_000_000),
                )
            blocked = paid_unavailable("/research/" + key)
            if blocked:
                return blocked
            research.start(key, planning=True)
            return redirect("/research/" + key)
        except (ValueError, InvalidOperation) as exc:
            return redirect("/research", str(exc))

    def recover_run(db, run_id):
        run = db.run(run_id)
        if not run:
            raise HTTPException(404, "Research run not found.")
        if (
            run["status"] in ("planning", "running", "pause_requested")
            and run_id not in research.active
        ):
            alive = bool(
                run["worker_pid"]
                and run["worker_pid"] != os.getpid()
                and process_alive(run["worker_pid"])
            )
            if not alive:
                db.set_run(
                    run_id,
                    status="failed",
                    error=(
                        "The worker stopped. Saved results and reserved spending remain "
                        "available; uncertain requests will not be replayed."
                    ),
                )
                run = db.run(run_id)
        return run

    @app.get("/research/{run_id}/status")
    def research_status(run_id: str):
        from fastapi.responses import JSONResponse

        with open_store() as db:
            run = recover_run(db, run_id)
            count = len(db.leads(run_id))
            detail = {
                "draft": "Audience saved. No research has started.",
                "planning": "Creating your plan. No company discovery starts until you approve it.",
                "awaiting_approval": "Your plan is ready. Review and approve it before research.",
                "running": "Finding companies and checking evidence. Results save as they finish.",
                "pause_requested": "Pausing after the current request. Saved results are kept.",
                "paused": "Paused. Your results and spending records are saved.",
                "completed": "Research finished. Review saved companies before using their emails.",
                "failed": "Research stopped. Open saved results to review the error and spending.",
            }.get(run["status"], "Your saved work remains available.")
            return JSONResponse(
                {
                    "status": run["status"],
                    "label": templates.env.filters["friendly_status"](run["status"]),
                    "detail": run["progress"]
                    if run["status"] in ("planning", "running", "pause_requested")
                    and run["progress"]
                    else run["progress"]
                    if run["execution"]["version"] == 2
                    else detail,
                    "active": run["status"] in ("planning", "running", "pause_requested"),
                    "companies": count,
                    "target": run["target_count"],
                    "spent": run["spent"],
                    "budget": run["budget"],
                    "updated_at": run["updated_at"],
                    "requests": request_summary(db, run, active=run_id in research.active),
                },
                headers={"Cache-Control": "no-store"},
            )

    @app.get("/research/{run_id}")
    def research_detail(request: Request, run_id: str, stage: str = "all"):
        with open_store() as db:
            run = recover_run(db, run_id)
            all_leads = db.leads(run_id)
            stage = stage if stage in LEAD_STAGES else "all"
            intake = AudienceIntake(**run["intake"]) if run["intake"] else None
            counts = {
                key: sum(lead_stage(lead) == key for lead in all_leads) for key in LEAD_STAGES
            }
            counts["all"] = len(all_leads)
            return render(
                request,
                "research_run.html",
                run=run,
                audience_history=db.audience_history(run_id),
                leads=[lead for lead in all_leads if stage == "all" or lead_stage(lead) == stage],
                total_leads=len(all_leads),
                stage=stage,
                stage_counts=counts,
                lead_stages=LEAD_STAGES,
                intake=run["intake"] or {"goal": run["brief"]},
                questions=intake.questions() if intake else [],
                contact_roles=CONTACT_ROLES,
                max_budget=settings.research_max_budget_usd,
                default_budget=min(0.5, settings.research_max_budget_usd),
                messages=db.messages(run_id),
                calls=db.rows(
                    "SELECT call_key,status,charged_micro,cost_kind FROM research_calls "
                    "WHERE run_id=? ORDER BY created_at",
                    (run_id,),
                ),
                campaign_context=db.research_campaign(run_id),
                suggestions=db.suggestions(run_id) if run["execution"]["version"] == 2 else [],
                work_summary=request_summary(db, run, active=run_id in research.active),
                continuation=continuation(db, run, run_id in research.active),
                active=run_id in research.active,
                providers_ready=bool(settings.parallel_api_key and settings.openrouter_api_key),
                **options(db),
            )

    @app.get("/research/{run_id}/edit")
    def edit_audience(request: Request, run_id: str):
        with open_store() as db:
            run = db.run(run_id)
            if not run:
                raise HTTPException(404, "Audience not found.")
            in_place = (
                run["status"] == "draft"
                and not run["archived"]
                and not run["deleted"]
                and not run["plan"]
                and not run["approved_at"]
                and not db.one("SELECT call_key FROM research_calls WHERE run_id=?", (run_id,))
            )
            return render(
                request,
                "research_edit.html",
                run=run,
                editing_full=True,
                in_place=in_place,
                campaign_context=db.research_campaign(run_id),
                original_active=run["status"] in ("planning", "running", "pause_requested"),
                intake=run["intake"] or {"goal": run["brief"]},
                intake_action=f"/research/{run_id}/" + ("intake" if in_place else "revise"),
                save_label="Save changes" if in_place else "Save next version of this audience",
                form_values={
                    "title": run["title"],
                    "budget": min(run["budget"], settings.research_max_budget_usd),
                },
                contact_roles=CONTACT_ROLES,
                max_budget=settings.research_max_budget_usd,
                default_budget=min(0.5, settings.research_max_budget_usd),
                **options(db),
            )

    @app.post("/research/{run_id}/recover-discovery")
    def recover_discovery(run_id: str):
        from outreach.core.research import ResearchStop

        try:
            with research._lock, open_store() as db, db.transaction():
                if run_id in research.active:
                    raise ResearchStop(
                        "Wait for current research to stop before recovering saved results."
                    )
                count = recover_saved_discovery(db, run_id)
            return redirect(
                "/research/" + run_id,
                f"{count} company suggestions recovered from saved results. "
                "No new API request was made. Contact and fit checks still need your approval.",
            )
        except ResearchStop as exc:
            return redirect("/research/" + run_id, str(exc))

    @app.post("/research/{run_id}/refine")
    async def refine(request: Request, run_id: str):
        blocked = paid_unavailable("/research/" + run_id)
        if blocked:
            return blocked
        form = await request.form()
        with open_store() as db:
            run = db.run(run_id)
            if not run or run["approved_at"] or run_id in research.active:
                return redirect(
                    "/research/" + run_id,
                    "A running or approved plan cannot be changed. Start a new research brief.",
                )
            if run["intake"] and not run["plan"]:
                return redirect(
                    "/research/" + run_id,
                    "Complete your audience and authorise planning in the saved intake form first.",
                )
            text = form.get("instruction", "").strip()
            if not 3 <= len(text) <= 2000 or len(run["brief"]) + len(text) > 8000:
                return redirect(
                    "/research/" + run_id,
                    "Use a short clarification between 3 and 2,000 characters.",
                )
            db.message(run_id, "user", text)
            db.set_run(
                run_id,
                brief=run["brief"] + "\nClarification: " + text,
                status="draft",
                plan_version=run["plan_version"] + 1,
                plan_json=None,
                error="",
            )
        research.start(run_id, planning=True)
        return redirect("/research/" + run_id)

    @app.post("/research/{run_id}/copy")
    def copy_audience(run_id: str):
        with open_store() as db, db.transaction():
            original = db.run(run_id)
            if not original or not original["intake"]:
                raise HTTPException(404, "Saved audience details were not found.")
            intake = AudienceIntake(**original["intake"])
            budget = min(
                original["budget_micro"], int(settings.research_max_budget_usd * 1_000_000)
            )
            key = db.new_run(
                engine_version=2,
                strategy_version=6,
                title=(original["title"][:112] + " (copy)"),
                brief=intake.goal,
                purpose=original["purpose"],
                tags="",
                project_id=None,
                target=original["target_count"],
                budget=budget,
            )
            db.save_intake(
                key,
                intake,
                title=original["title"][:112] + " (copy)",
                purpose=original["purpose"],
                target=original["target_count"],
                budget=budget,
            )
        return redirect(
            "/research/" + key,
            "Audience copied for free. The earlier attempt and reservation are kept. "
            "No research was retried; any new paid plan needs your approval.",
        )

    @app.post("/research/{run_id}/approve")
    async def approve_plan(request: Request, run_id: str):
        blocked = paid_unavailable("/research/" + run_id)
        if blocked:
            return blocked
        form = await request.form()
        try:
            plan = ResearchPlan(
                summary=form.get("summary", ""),
                criteria=form.get("criteria", "").splitlines(),
                queries=form.get("queries", "").splitlines(),
                alternate_queries=form.get("alternate_queries", "").splitlines(),
                exclusions=[x for x in form.get("exclusions", "").splitlines() if x.strip()],
            )
            if not form.get("confirm"):
                raise ValueError("Confirm the plan and its spending cap before research starts.")
            with open_store() as db, db.transaction():
                run = db.run(run_id)
                if (
                    not run
                    or run["archived"]
                    or run["deleted"]
                    or run["status"] != "awaiting_approval"
                    or run["approved_at"]
                ):
                    raise ValueError("This plan is not awaiting approval.")
                from datetime import UTC, datetime

                db.set_run(
                    run_id,
                    plan_json=plan.model_dump_json(),
                    status="approved",
                    approved_at=datetime.now(UTC).isoformat(),
                )
                db.message(run_id, "user", "Approved research plan and run budget.")
            research.start(run_id)
            return redirect("/research/" + run_id)
        except ValueError:
            return redirect(
                "/research/" + run_id,
                (
                    "Check the plan: summary, 1–6 criteria, and 1–3 queries in each "
                    "search round are required. Confirm the budget."
                ),
            )

    @app.post("/research/{run_id}/pause")
    def pause_research(run_id: str):
        with open_store() as db:
            run = db.run(run_id)
            if run and run["status"] == "running":
                db.set_run(
                    run_id, status="pause_requested", progress="Pausing after the current request."
                )
        return redirect("/research/" + run_id)

    @app.post("/research/{run_id}/limits")
    async def change_research_limits(request: Request, run_id: str):
        form = await request.form()
        destination = "/research/" + run_id
        try:
            target = int(form.get("target", ""))
            cap = Decimal(form.get("budget", ""))
            if (
                not 1 <= target <= 25
                or not cap.is_finite()
                or not Decimal(".10") <= cap <= Decimal(str(settings.research_max_budget_usd))
            ):
                raise ValueError("Choose 1–25 companies and a cap within the displayed limit.")
            with research._lock, open_store() as db, db.transaction():
                run = db.run(run_id)
                if (
                    not run
                    or run["deleted"]
                    or run["archived"]
                    or run_id in research.active
                    or run["status"] in ("running", "planning", "pause_requested")
                ):
                    raise ValueError(
                        "Pause research and restore the audience before changing its limits."
                    )
                if db.one(
                    "SELECT call_key FROM research_calls WHERE run_id=? AND status!='complete'",
                    (run_id,),
                ):
                    raise ValueError(
                        "Check the uncertain provider request first. Its reservation is retained."
                    )
                amount = int(cap * 1_000_000)
                if amount < run["spent_micro"]:
                    raise ValueError("The total cap cannot be below already accounted spending.")
                if amount > run["budget_micro"] and not form.get("confirm"):
                    raise ValueError(
                        "Confirm the larger total cap. No request starts automatically."
                    )
                if run["status"] == "completed" and target > run["target_count"]:
                    state = run["execution"]
                    if state.get("no_yield", 0) >= 3 or state.get("round", 0) >= 8:
                        raise ValueError(
                            "Search coverage is exhausted. "
                            "Edit the audience to broaden the next version."
                        )
                    db.set_run(run_id, status="paused")
                db.set_run(run_id, target_count=target, budget_micro=amount)
                db.message(
                    run_id,
                    "assistant",
                    f"Research limits updated: {target} companies; total cap ${cap:.2f}. "
                    "Existing spending and saved requests are retained.",
                )
            return redirect(
                destination,
                "Limits saved. Click Continue research when ready; nothing started automatically.",
            )
        except (ValueError, InvalidOperation) as exc:
            return redirect(destination, str(exc))

    @app.post("/research/{run_id}/resume")
    def resume(run_id: str):
        blocked = paid_unavailable("/research/" + run_id)
        if blocked:
            return blocked
        with research._lock, open_store() as db, db.transaction():
            run = db.run(run_id)
            if not run or not run["approved_at"]:
                return redirect(
                    "/research/" + run_id, "Review and approve a plan before research can resume."
                )
            if run_id in research.active:
                return redirect("/research/" + run_id, "This research is already running.")
            if db.one(
                "SELECT call_key FROM research_calls WHERE run_id=? AND status!='complete'",
                (run_id,),
            ):
                return redirect(
                    "/research/" + run_id,
                    "A previous request has an uncertain outcome. Check provider usage; "
                    "it will not be repeated. Saved results remain available.",
                )
            if run["spent_micro"] >= run["budget_micro"]:
                return redirect(
                    "/research/" + run_id,
                    "This batch reached its cap. Save a revised audience with a new cap "
                    "and approve its plan separately.",
                )
            if run["status"] == "completed" and db.one(
                "SELECT id FROM research_leads WHERE run_id=? AND processing_status!='complete'",
                (run_id,),
            ):
                db.set_run(run_id, status="paused")
        research.start(run_id)
        return redirect("/research/" + run_id)

    @app.get("/leads/{lead_id}")
    def lead_detail(request: Request, lead_id: int):
        with open_store() as db:
            lead = db.lead(lead_id)
            if not lead:
                raise HTTPException(404, "Lead not found.")
            return render(
                request,
                "lead.html",
                lead=lead,
                audience=db.run(lead["run_id"])["intake"],
                contact_roles=CONTACT_ROLES,
            )

    @app.post("/leads/review")
    async def review_leads(request: Request):
        form = await request.form()
        try:
            with open_store() as db:
                db.review_leads(
                    ids(form),
                    action=form.get("action"),
                    confirmed=bool(form.get("confirmed")),
                    note=form.get("note", "")[:2000],
                    email=form.get("email"),
                )
            return redirect(return_path(form), "Lead review saved.")
        except ValueError as exc:
            return redirect(return_path(form), str(exc))

    @app.get("/lists")
    def lists(request: Request, q: str = "", project_id: str = ""):
        with open_store() as db:
            lists = [
                item
                for item in db.lists()
                if q.casefold() in (item["name"] + " " + item["tags"]).casefold()
                and (not project_id or item["project_id"] == project_id)
            ]
            return render(request, "lists.html", lists=lists, **options(db))

    @app.post("/lists")
    async def save_list(request: Request):
        form = await request.form()
        try:
            name = form.get("name", "").strip()
            if not 1 <= len(name) <= 120:
                raise ValueError("Name the lead list.")
            with open_store() as db:
                key = db.add_list(
                    name, project(db, form.get("project_id")), ids(form), form.get("tags", "")[:200]
                )
            return redirect("/lists/" + key)
        except ValueError as exc:
            return redirect(return_path(form), str(exc))

    @app.get("/lists/{list_id}")
    def list_detail(request: Request, list_id: str):
        with open_store() as db:
            item = db.one("SELECT * FROM lead_lists WHERE id=?", (list_id,))
            if not item:
                raise HTTPException(404, "List not found.")
            return render(
                request, "list.html", item=item, leads=db.leads(list_id=list_id), **options(db)
            )

    @app.get("/accounts")
    def accounts(request: Request, edit: str = ""):
        with open_store() as db:
            return render(
                request,
                "accounts.html",
                accounts=db.accounts(),
                edit=db.account(edit) if edit else None,
            )

    def verify(account_id):
        if settings.local_network_restricted:
            return (
                "Your email login is saved. Restart using RESTART-OUTREACH.cmd before "
                "verifying sending and inbox access. No network check or email was sent."
            )
        error = ""
        try:
            account = profile(account_id)
            box = mailbox(account)
            if not callable(getattr(box, "verify_login", None)) or not callable(
                getattr(box, "verify_inbox", None)
            ):
                raise ConfigError(
                    "This mailbox adapter cannot verify both sending and inbox access."
                )
            box.verify_login()
            box.verify_inbox()
        except (ConfigError, MailError, OSError):
            error = (
                "Verification failed. Reconnect OAuth or check your app password, "
                "server region, permissions and network connection."
            )
        with open_store() as db:
            from datetime import UTC, datetime

            db.conn.execute(
                "UPDATE mail_accounts SET verified_at=?,last_error=? WHERE id=?",
                (None if error else datetime.now(UTC).isoformat(), error, account_id),
            )
        return error or "Sending and inbox access verified. No email was sent."

    @app.post("/accounts")
    async def save_account(request: Request):
        form = await request.form()
        try:
            email = str(TypeAdapter(EmailStr).validate_python(form.get("email", ""))).casefold()
            provider = form.get("provider", "gmail")
            if provider not in ("gmail", "zoho"):
                raise ValueError("Choose Gmail or Zoho.")
            region = form.get("region", "com")
            if region not in ("com", "in", "eu", "com.au", "jp", "ca"):
                raise ValueError("Choose your Zoho server region.")
            paid = form.get("zoho_paid") == "1"
            smtp = (
                "smtp.gmail.com"
                if provider == "gmail"
                else ("smtppro.zoho." if paid else "smtp.zoho.") + region
            )
            imap = (
                "imap.gmail.com"
                if provider == "gmail"
                else ("imappro.zoho." if paid else "imap.zoho.") + region
            )
            values = {
                "email": email,
                "username": email,
                "smtp_host": smtp,
                "smtp_port": 465,
                "imap_host": imap,
                "imap_port": 993,
            }
            for field in ("label", "sender_name", "company", "address"):
                values[field] = form.get(field, "").strip()
                if not 1 <= len(values[field]) <= 300:
                    raise ValueError(
                        "Fill in the account label, sender name, company and postal address."
                    )
            password = form.get("password", "")
            with open_store() as db:
                key = form.get("account_id") or None
                old = db.account(key, secret=True) if key else None
                if old and old.get("oauth_provider"):
                    raise ValueError("Reconnect this account through OAuth instead.")
                if not password and not old:
                    raise ValueError("Enter an app password from your email provider.")
                cipher = vault().encrypt(password) if password else old["password_cipher"]
                key = db.save_account(values, cipher, key)
            message = await run_in_threadpool(verify, key)
            return redirect("/accounts", message)
        except (ValueError, ConfigError):
            return redirect(
                "/accounts",
                (
                    "Account could not be saved. Check the required fields and use a "
                    "unique email address."
                ),
            )
        except Exception:
            return redirect(
                "/accounts",
                (
                    "Account could not be saved. Check for an existing account with "
                    "this email address."
                ),
            )

    @app.post("/accounts/{account_id}/verify")
    async def verify_account(account_id: str):
        return redirect("/accounts", await run_in_threadpool(verify, account_id))

    @app.get("/campaigns")
    def campaigns(
        request: Request,
        q: str = "",
        purpose_filter: str = "",
        project_id: str = "",
        status: str = "",
    ):
        with open_store() as db:
            opts = options(db)
            rows = [
                c
                for c in opts.pop("campaigns")
                if q.casefold() in (c["name"] + " " + (c["tags"] or "")).casefold()
                and (not purpose_filter or c["purpose"] == purpose_filter)
                and (not project_id or c["project_id"] == project_id)
                and (c["status"] == status if status else c["status"] != "archived")
            ]
            for c in rows:
                c["contacts"] = db.one(
                    "SELECT COUNT(*) AS n FROM contacts WHERE campaign_id=?", (c["id"],)
                )["n"]
                c["sent"] = db.one(
                    (
                        "SELECT COUNT(DISTINCT m.contact_id) AS n FROM messages m JOIN "
                        "contacts c ON c.id=m.contact_id WHERE c.campaign_id=? AND "
                        "m.status='sent'"
                    ),
                    (c["id"],),
                )["n"]
                c["replies"] = db.one(
                    (
                        "SELECT COUNT(*) AS n FROM replies r JOIN reply_triage t ON "
                        "t.reply_id=r.id JOIN contacts c ON c.id=t.contact_id WHERE "
                        "c.campaign_id=?"
                    ),
                    (c["id"],),
                )["n"]
            return render(request, "campaigns.html", campaigns=rows, **opts)

    @app.get("/campaigns/new")
    def new_campaign(request: Request, list_id: str = ""):
        with open_store() as db:
            chosen = db.leads(list_id=list_id) if list_id else []
            purposes = {db.run(lead["run_id"])["purpose"] for lead in chosen}
            initial_purpose = next(iter(purposes)) if len(purposes) == 1 else "sales"
            return render(
                request,
                "campaign_form.html",
                campaign=None,
                initial_purpose=initial_purpose,
                selected_has_prior=any(lead["prior_campaigns"] for lead in chosen),
                lists=db.lists(),
                list_id=list_id,
                states=STATES,
                message_brief={},
                **options(db),
            )

    @app.get("/campaigns/{campaign_id}/settings")
    def campaign_form(request: Request, campaign_id: str):
        with open_store() as db:
            item = db.campaign(campaign_id)
            if not item:
                raise HTTPException(404, "Campaign not found.")
            return render(
                request,
                "campaign_form.html",
                campaign=item,
                offer=load_copy(campaign_id) or "",
                closing=load_closing(campaign_id) or "",
                states=STATES,
                lists=[],
                **options(db),
            )

    def form_problem(exc):
        if callable(getattr(exc, "errors", None)):
            first = exc.errors()[0]
            return str(first["loc"][0]) + ": " + first["msg"]
        return str(exc)[:500]

    def editor_values(item, cid):
        saved = item.get("message_brief") or {}
        brief = MessageBrief(**saved) if saved else None
        # Show the exact source used by generation, including external legacy edits.
        source = load_copy(cid) or (submitted_editor(saved)["message_prompt"] if brief else "")
        closing = load_closing(cid)
        if closing:
            source = source.rstrip() + "\n\n[KEEP]\n" + closing + "\n[/KEEP]"
        return {"message_prompt": source}

    def submitted_editor(form):
        source = form.get("message_prompt", "")
        if not source:
            source = "\n".join(
                f"{key.replace('_', ' ')}: {form[key]}"
                for key in (
                    "topic",
                    "introduction",
                    "background",
                    "desired_response",
                    "tone",
                    "sender_name",
                )
                if form.get(key)
            )
        if form.get("closing"):
            source += "\n\n[KEEP]\n" + form["closing"] + "\n[/KEEP]"
        return {"message_prompt": source}

    def message_from(form):
        return MessageBrief(
            message_prompt=form.get("message_prompt", "").strip(),
            **{
                key: form.get(key, "").strip()
                for key in (
                    "topic",
                    "introduction",
                    "background",
                    "desired_response",
                    "sender_name",
                )
            },
            tone=form.get("tone", "professional"),
        )

    @app.get("/campaigns/{campaign_id}/message")
    def campaign_message(request: Request, campaign_id: str):
        with open_store() as db:
            item = db.campaign(campaign_id)
            if not item:
                raise HTTPException(404, "Campaign not found.")
            return render(
                request,
                "campaign_message.html",
                campaign_id=campaign_id,
                metadata=item,
                tab="message",
                attachments=manifests(db.attachment_files(campaign_id)),
                message_brief=editor_values(item, campaign_id),
                closing=load_closing(campaign_id) or "",
                legacy_copy=load_copy(campaign_id) if not item["message_brief"] else None,
            )

    @app.post("/campaigns/{campaign_id}/message")
    async def save_message(request: Request, campaign_id: str):
        form = await request.form()
        try:
            if sender.busy or drafter.busy:
                raise ValueError("Stop sending or drafting before changing the message brief.")
            brief = message_from(form)
            from outreach.core.email_composer import parse_editor

            parse_editor(brief.message_prompt or brief.campaign_copy())
            closing = form.get("closing", "").strip()
            if len(closing) > 4000:
                raise ValueError("Keep the shared closing below 4,000 characters.")
            with open_store() as db:
                if not db.campaign(campaign_id):
                    raise HTTPException(404, "Campaign not found.")
                old_copy, old_closing = (
                    load_copy(campaign_id) or "",
                    load_closing(campaign_id) or "",
                )
                if brief.campaign_copy() != old_copy or closing != old_closing:
                    db.invalidate_approvals(campaign_id)
                save_texts(campaign_id, copy=brief.campaign_copy(), closing=closing)
                db.save_message_brief(campaign_id, brief)
            note = "Message brief saved. " + (
                "Complete: " + ", ".join(brief.missing())
                if brief.missing()
                else "New or changed drafts need review."
            )
            return redirect("/campaigns/" + campaign_id + "/message", note)
        except ValueError as exc:
            with open_store() as db:
                item = db.campaign(campaign_id)
                if not item:
                    raise HTTPException(404, "Campaign not found.") from None
                response = render(
                    request,
                    "campaign_message.html",
                    campaign_id=campaign_id,
                    metadata=item,
                    tab="message",
                    attachments=manifests(db.attachment_files(campaign_id)),
                    message_brief=submitted_editor(form),
                    closing=form.get("closing", ""),
                    form_error=form_problem(exc) + " Your entries are kept below.",
                )
                response.status_code = 400
                return response

    async def save_campaign(request, campaign_id=None):
        form = await request.form()
        try:
            if sender.busy or drafter.busy:
                raise ValueError("Stop sending or drafting before changing campaign settings.")
            name = form.get("name", "").strip()
            if not name and not campaign_id and form.get("message_prompt", "").strip():
                name = form["message_prompt"].strip().split("\n")[0][:80]
            cid = campaign_id or re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:45]
            if not name or len(name) > 120 or not is_valid_id(cid):
                raise ValueError("Choose a campaign name that contains letters or digits.")
            brief = message_from(form) if form.get("brief_mode") == "structured" else None
            offer = brief.campaign_copy() if brief else form.get("offer", "").strip()
            from outreach.core.email_composer import parse_editor

            parse_editor(brief.message_prompt if brief and brief.message_prompt else offer)
            closing = form.get("closing", "").strip()
            content_submitted = not campaign_id or bool(brief) or "offer" in form
            if len(offer) > 12000 or len(closing) > 4000:
                raise ValueError("Describe the offer or campaign topic (up to 12,000 characters).")
            status = form.get("status", "draft")
            if status not in STATES:
                raise ValueError("Choose a campaign status.")
            with open_store() as db:
                list_id = form.get("list_id")
                if list_id:
                    if not db.one("SELECT id FROM lead_lists WHERE id=?", (list_id,)):
                        raise ValueError("Choose an existing lead list.")
                    for lead in db.leads(list_id=list_id):
                        if lead["review_status"] != "approved" or not lead["selected_email"]:
                            raise ValueError(
                                "Review and approve this list before campaign creation."
                            )
                        if lead["suppressed"]:
                            raise ValueError("A lead in this list is globally suppressed.")
                        if lead["prior_campaigns"] and not form.get("acknowledge_prior"):
                            raise ValueError(
                                "Review and acknowledge prior outreach before reusing this list."
                            )
                if not campaign_id and db.campaign(cid):
                    raise ValueError(
                        "A campaign with this name already exists. Use a different name."
                    )
                db.save_campaign(
                    cid,
                    name,
                    project(db, form.get("project_id")),
                    purpose(form.get("purpose") or prompt_purpose(form.get("message_prompt", ""))),
                    form.get("tags", "")[:200],
                    form.get("account_id"),
                    status,
                )
                if content_submitted:
                    if offer != (load_copy(cid) or "") or closing != (load_closing(cid) or ""):
                        db.invalidate_approvals(cid)
                    save_texts(cid, copy=offer, closing=closing)
                    if brief:
                        db.save_message_brief(cid, brief)
                    else:
                        db.conn.execute("DELETE FROM campaign_briefs WHERE campaign_id=?", (cid,))
                list_id = form.get("list_id")
                if list_id:
                    db.enroll(
                        cid,
                        [lead["id"] for lead in db.leads(list_id=list_id)],
                        acknowledge_prior=bool(form.get("acknowledge_prior")),
                    )
            return redirect("/campaigns/" + cid)
        except ValueError as exc:
            with open_store() as db:
                response = render(
                    request,
                    "campaign_form.html",
                    campaign=db.campaign(campaign_id) if campaign_id else None,
                    states=STATES,
                    lists=db.lists(),
                    list_id=form.get("list_id", ""),
                    form_values=dict(form),
                    message_brief=submitted_editor(form),
                    closing=form.get("closing", ""),
                    form_error=form_problem(exc) + " Your entries are kept below.",
                    **options(db),
                )
                response.status_code = 400
                return response

    @app.post("/campaigns/new")
    async def create_campaign(request: Request):
        return await save_campaign(request)

    @app.post("/campaigns/{campaign_id}/settings")
    async def update_campaign(request: Request, campaign_id: str):
        return await save_campaign(request, campaign_id)

    def usable_contacts(db, run_id):
        run = db.run(run_id)
        if not run or run.get("deleted") or run.get("archived"):
            raise HTTPException(404, "Audience not found. Restore it from Trash or Archived first.")
        leads = db.audience_leads(run_id)
        from outreach.core.campaign_selection import campaign_email

        ready = [
            {**lead, "campaign_email": campaign_email(lead)}
            for lead in leads
            if campaign_email(lead)
        ]
        return run, leads, ready

    @app.get("/campaigns/{campaign_id}/audience")
    def choose_saved_audience(request: Request, campaign_id: str):
        with open_store() as db:
            item = db.campaign(campaign_id)
            if not item:
                raise HTTPException(404, "Campaign not found.")
            audiences = []
            for run in db.audiences():
                _, leads, ready = usable_contacts(db, run["id"])
                audiences.append({**run, "lead_count": len(leads), "ready_count": len(ready)})
            return render(
                request,
                "campaign_audiences.html",
                campaign_id=campaign_id,
                metadata=item,
                tab="audience",
                audiences=audiences,
            )

    @app.get("/research/{run_id}/use")
    def use_saved_audience(request: Request, run_id: str, campaign_id: str = ""):
        with open_store() as db:
            run, leads, ready = usable_contacts(db, run_id)
            campaign = db.campaign(campaign_id) if campaign_id else None
            return render(
                request,
                "audience_use.html",
                run=run,
                leads=ready,
                lead_count=len(leads),
                blocked_count=len(leads) - len(ready),
                campaign_context=campaign,
                **options(db),
            )

    @app.post("/research/{run_id}/use")
    async def enroll_saved_audience(request: Request, run_id: str):
        form = await request.form()
        try:
            if sender.busy or drafter.busy:
                raise ValueError("Wait for sending or drafting to finish before adding contacts.")
            chosen = ids(form)
            with open_store() as db:
                run, _, ready = usable_contacts(db, run_id)
                if not set(chosen).issubset({lead["id"] for lead in ready}):
                    raise ValueError(
                        "Some contacts changed. Review this audience "
                        "and select available contacts again."
                    )
                if form.get("action") == "new":
                    key = db.add_list(
                        run["title"][:120], run.get("project_id"), chosen, accept_selected=True
                    )
                    return redirect(
                        "/campaigns/new?list_id=" + key,
                        "Approved audience selected. Name your campaign and choose its sender.",
                    )
                cid = form.get("campaign_id", "")
                count, skipped = db.enroll(
                    cid,
                    chosen,
                    acknowledge_prior=bool(form.get("acknowledge_prior")),
                    accept_selected=True,
                )
            return redirect(
                "/campaigns/" + cid + "?tab=audience",
                f"{count} contacts added from {run['title']}; {skipped} already in this campaign. "
                "Next: write your message.",
            )
        except ValueError as exc:
            return redirect("/research/" + run_id + "/use", str(exc))

    @app.post("/campaigns/{campaign_id}/enroll")
    async def enroll(request: Request, campaign_id: str):
        form = await request.form()
        try:
            with open_store() as db:
                count, skipped = db.enroll(
                    campaign_id, ids(form), acknowledge_prior=bool(form.get("acknowledge_prior"))
                )
            return redirect(
                "/campaigns/" + campaign_id,
                f"{count} leads added; {skipped} already in this campaign.",
            )
        except ValueError as exc:
            return redirect(return_path(form), str(exc))

    @app.post("/campaigns/from-selection")
    async def campaign_from_selection(request: Request):
        form = await request.form()
        try:
            with open_store() as db:
                key = db.add_list(
                    form.get("name", "").strip()[:120] or "Selected outreach audience",
                    project(db, form.get("project_id")),
                    ids(form),
                )
            return redirect("/campaigns/new?list_id=" + key)
        except ValueError as exc:
            return redirect(return_path(form), str(exc))

    @app.post("/campaigns/{campaign_id}/enroll-list")
    async def enroll_list(request: Request, campaign_id: str):
        form = await request.form()
        try:
            with open_store() as db:
                key = form.get("list_id", "")
                if not db.one("SELECT id FROM lead_lists WHERE id=?", (key,)):
                    raise ValueError("Choose an existing approved audience list.")
                count, skipped = db.enroll(
                    campaign_id,
                    [lead["id"] for lead in db.leads(list_id=key)],
                    acknowledge_prior=bool(form.get("acknowledge_prior")),
                )
            return redirect(
                "/campaigns/" + campaign_id + "?tab=audience",
                f"{count} added; {skipped} already in this campaign.",
            )
        except ValueError as exc:
            return redirect("/campaigns/" + campaign_id + "?tab=audience", str(exc))

    @app.post("/enroll")
    async def enroll_selection(request: Request):
        form = await request.form()
        return await enroll(request, form.get("campaign_id", ""))
