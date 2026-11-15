"""Production research flow, gated by the original pilot's durable $1 ledger."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from experiments.pilot_runtime import PilotStop, Runtime, atomic_json, session_lock
from outreach.adapters.db import connect
from outreach.adapters.platform_store import PlatformStore, now
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import load_settings
from outreach.core.research import ResearchStop, literal, same_site, text_windows
from outreach.core.research_flow import build_plan, run_research, sources_of

ARM = "founders-bangalore-v1"
BRIEF = (
    "Find up to three AI product startups based in Bangalore/Bengaluru for speculative "
    "founder job outreach. Look for founders' names and explicitly published direct "
    "professional email addresses. Do not guess email patterns. Do not count general "
    "info/sales/support emails as founder emails. Establish the correct company and "
    "official domain. Prefer companies building their own AI products over pure agencies. "
    "Save source-backed product details and founder/company facts useful for personalising "
    "an introduction in a later drafting step. Do not research vacancies extensively or "
    "require an open position. Do not infer the sender's skills or claim anyone is hiring. "
    "Unknown founder email is a valid unresolved result."
)


class ProfileFact(BaseModel):
    summary: str
    source_id: str
    quote: str


class FounderProfile(BaseModel):
    founder_name: str
    founder_source_id: str
    founder_quote: str
    email: str
    email_source_id: str
    email_quote: str
    email_association_quote: str
    personalisation: list[ProfileFact] = Field(max_length=3)
    unknowns: list[str]


def profile_context(text):
    """Keep founder/identity passages alongside ordinary product/contact excerpts."""
    chunks = [text_windows(text, 2500)]
    for match in list(re.finditer(r"founder|co-founder|Bangalore|Bengaluru", text, re.I))[:5]:
        chunks.append(text[max(0, match.start() - 220) : match.end() + 380])
    return "\n[separate excerpt]\n".join(dict.fromkeys(chunks))[:5000]


def validate_profile(profile, sources):
    from outreach.core.research import published_emails

    founder_source = sources.get(profile.founder_source_id, {})
    contact_source = sources.get(profile.email_source_id, {})
    founder_valid = bool(
        profile.founder_name.strip()
        and profile.founder_name.casefold() in profile.founder_quote.casefold()
        and "founder" in profile.founder_quote.casefold()
        and literal(profile.founder_quote, founder_source.get("text", ""))
    )
    published = published_emails([contact_source], contact_source["url"]) if contact_source else []
    email_valid = bool(
        founder_valid
        and any(e["value"] == profile.email.lower() for e in published)
        and profile.email.lower() in profile.email_quote.lower()
        and literal(profile.email_quote, contact_source.get("text", ""))
        and literal(profile.email_association_quote, contact_source.get("text", ""))
        and profile.founder_name.casefold() in profile.email_association_quote.casefold()
        and profile.email.casefold() in profile.email_association_quote.casefold()
        and profile.email.split("@")[0].casefold()
        not in {"info", "sales", "support", "hello", "connect", "contact", "careers", "jobs"}
    )
    facts = [
        f.model_dump() | {"source_url": sources[f.source_id]["url"]}
        for f in profile.personalisation
        if f.source_id in sources and literal(f.quote, sources[f.source_id]["text"])
    ]
    return {
        "founder_role_quote_valid": founder_valid,
        "direct_founder_email_evidence_valid": email_valid,
        "personalisation_facts": facts,
        "summary_review": "Literal quotes matched; summaries still require semantic review.",
        "review_status": "pending",
        "campaign_ready": False,
    }


def followup(db, api, folder):
    """Target the original three candidates; no replacement companies or guessed contacts."""
    blocked = (
        "rocketreach.co",
        "apollo.io",
        "signalhire.com",
        "contactout.com",
        "lusha.com",
        "zoominfo.com",
        "email-format.com",
        "leadiq.com",
        "lead411.com",
        "growjo.com",
    )
    profiles = []
    db.set_run(api.run_id, status="running")
    for lead in db.leads(api.run_id):
        prefix = f"founder-followup/{lead['id']}"
        result = api.search(
            prefix + "/search",
            "Find named founders and explicitly published direct professional founder emails "
            "for this exact company. Prefer official about/team pages and founders' own public "
            "professional websites. Exclude contact brokers, guessed email patterns, vacancies, "
            "and generic company inboxes. " + lead["company"] + " " + lead["website"],
            [lead["company"] + " founder cofounder email Bangalore Bengaluru"],
        )
        discovered = sources_of(result)
        safe = [s for s in discovered if not any(b in s["url"].lower() for b in blocked)]
        existing_urls = {s["url"] for s in lead["sources"]}
        about_links = []
        for source in lead["sources"]:
            for url in re.findall(r'https?://[^\s<>"\]]+', source["text"]):
                url = url.rstrip(").,]")
                if same_site(url, lead["website"]) and re.search("about|team|founder", url, re.I):
                    about_links.append(url)
        urls = list(
            dict.fromkeys(
                [u for u in about_links if u not in existing_urls]
                + [s["url"] for s in safe if s["url"] not in existing_urls]
            )
        )[:4]
        fetched = sources_of(api.extract(prefix + "/pages", urls)) if urls else []
        sources = {f"s{i}": s for i, s in enumerate(lead["sources"] + fetched + safe, 1)}
        atomic_json(folder / (prefix.replace("/", "-") + "-sources.json"), sources)
        context = {
            sid: s | {"text": profile_context(s["text"])} for sid, s in list(sources.items())[:8]
        }
        # Preserve the original input bound by reducing excerpts, not discarding footer contacts.
        while len(json.dumps(context, ensure_ascii=False).encode()) > 18500:
            for s in context.values():
                s["text"] = s["text"][: max(800, int(len(s["text"]) * 0.8))]
        profile = api.generate(
            prefix + "/profile",
            "Research this exact company's named founders and public professional email. "
            "Every quote must be ONE contiguous exact passage from its cited source. "
            "The email association quote MUST contain both the founder's name and email. "
            "Do not guess contacts or count general inboxes. When the founder/email cannot "
            "be established, use empty strings and list the uncertainty. Find up to three "
            "product/company facts useful for a later introduction, without inventing sender "
            "skills or implying a vacancy. A founder title requires an explicit founder quote. "
            "COMPANY: "
            + lead["company"]
            + " "
            + lead["website"]
            + "\nSOURCES: "
            + json.dumps(context, ensure_ascii=False),
            FounderProfile,
        )
        profiles.append(
            {
                "company": lead["company"],
                "website": lead["website"],
                "profile": profile.model_dump(),
                "checks": validate_profile(profile, sources),
                "baseline_lead_id": lead["id"],
            }
        )
        atomic_json(folder / "founder-profiles.json", profiles)
    db.set_run(api.run_id, status="completed")
    return profiles


class PilotBoundedAPI(ResearchAPI):
    """Reserve in both ledgers before HTTP; incomplete outcomes cannot be replayed."""

    def __init__(self, *args, runtime, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtime = runtime

    def paid(self, key, provider, path, body, reserve):
        if provider == "openrouter":
            body = body | {"max_tokens": 2000}
            if sum(len(m["content"].encode()) for m in body["messages"]) > 24000:
                raise ResearchStop("Benchmark prompt exceeds the original pilot input bound.")
        fingerprint = hashlib.sha256(
            json.dumps([provider, path, body], sort_keys=True).encode()
        ).hexdigest()
        ledger_key = ARM + "/" + key
        runtime = self.runtime
        prior = runtime.state["calls"].get(ledger_key)
        if prior:
            saved = self.store.call(self.run_id, key)
            if (
                prior.get("fingerprint") != fingerprint
                or prior["status"] != "complete"
                or not saved
                or saved["status"] != "complete"
            ):
                raise ResearchStop("Benchmark checkpoint needs review; no request replayed.")
            return super().paid(key, provider, path, body, reserve)
        if runtime.state["notes"]:
            raise ResearchStop("Pilot reconciliation is pending; no request sent.")
        calls = [c for c in runtime.state["calls"].values() if c["arm"] == ARM]
        urls = len(body.get("urls", [])) if path == "/v1/extract" else 0
        if path == "/v1/search" and sum(c.get("path") == path for c in calls) >= 8:
            raise ResearchStop("Benchmark search-request limit reached.")
        if sum(c.get("url_count", 0) for c in calls) + urls > 20:
            raise ResearchStop("Benchmark extraction limit reached.")
        run = self.store.run(self.run_id)
        if run["status"] not in ("planning", "running"):
            raise ResearchStop("Benchmark is not running.")
        if run["spent_micro"] + reserve > run["budget_micro"]:
            raise ResearchStop("Benchmark run budget reached before the next request.")
        try:
            runtime.reserve(ledger_key, ARM, Decimal(reserve) / 1_000_000)
        except PilotStop as exc:
            raise ResearchStop(str(exc)) from exc
        entry = runtime.state["calls"][ledger_key]
        entry.update(provider=provider, fingerprint=fingerprint, path=path, url_count=urls)
        runtime.save()
        try:
            return super().paid(key, provider, path, body, reserve)
        finally:
            saved = self.store.call(self.run_id, key)
            if saved and saved["status"] == "complete":
                entry.update(
                    status="complete",
                    charged=str(Decimal(saved["charged_micro"]) / 1_000_000),
                    cost_kind=saved["cost_kind"],
                    response=json.loads(saved["response_json"]),
                )
                if Decimal(entry["charged"]) > Decimal(entry["reserved"]):
                    runtime.state["notes"].append("Benchmark overcharge needs reconciliation.")
            runtime.save()
            print(
                f"{provider} {key}: {entry['status']} · "
                f"combined accounted USD {runtime.charged():.6f}",
                flush=True,
            )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--followup", action="store_true")
    args = parser.parse_args()
    root = Path("data/research-pilot-v1")
    if not (root / "ledger.json").exists():
        raise SystemExit("Original pilot ledger is required; no fresh budget created.")
    folder = root / ARM
    folder.mkdir(parents=True, exist_ok=True)
    settings = load_settings(
        _env_file=None,
        db_path=str(folder / "research.db"),
        research_model="anthropic/claude-haiku-4.5",
        research_max_budget_usd=0.20,
        research_daily_budget_usd=0.20,
    )
    settings.require("parallel_api_key", "openrouter_api_key")
    # The guard never uses Runtime.request; actual HTTP stays in ResearchAPI.
    runtime = db = api = None
    try:
        with session_lock(root):
            runtime = Runtime(root, {"parallel": "unused", "openrouter": "unused"})
            db = PlatformStore(SqliteStore(connect(settings.db_path)))
            manifest = folder / "run.json"
            if manifest.exists():
                saved = json.loads(manifest.read_text())
                if saved["brief"] != BRIEF:
                    raise ResearchStop("Saved benchmark brief changed; inspect before continuing.")
                key = saved["run_id"]
            else:
                key = db.new_run(
                    title="Bangalore AI startup founder outreach",
                    brief=BRIEF,
                    purpose="job search",
                    tags="AI, Bangalore, founders, speculative outreach",
                    project_id=None,
                    target=3,
                    budget=200000,
                )
                atomic_json(manifest, {"run_id": key, "brief": BRIEF, "cap_usd": "0.20"})
            api = PilotBoundedAPI(settings, db, key, runtime=runtime)
            run = db.run(key)
            if not run["plan"]:
                db.set_run(key, status="planning")
                build_plan(db, api, key)
                run = db.run(key)
                atomic_json(folder / "plan.json", run["plan"])
            if not run["approved_at"]:
                # The operator explicitly supplied and authorised this bounded test brief.
                db.message(key, "user", "Execute the supplied founder-contact test brief.")
                db.set_run(key, approved_at=now(), status="approved")
            if run["status"] != "completed":
                db.set_run(key, status="running")
                run_research(db, api, key)
            if args.followup:
                followup(db, api, folder)
            atomic_json(folder / "results.json", db.leads(key))
            atomic_json(folder / "accounting.json", runtime.summary())
            print(
                json.dumps(
                    {
                        "status": db.run(key)["status"],
                        "candidate_companies": len(db.leads(key)),
                        "benchmark_accounted_usd": str(runtime.charged(ARM)),
                        "combined_accounted_usd": str(runtime.charged()),
                        "approved_leads": 0,
                    }
                ),
                flush=True,
            )
    except (ResearchStop, PilotStop) as exc:
        if api:
            db.set_run(api.run_id, status="failed", error=str(exc))
            atomic_json(folder / "results.json", db.leads(api.run_id))
        if runtime:
            atomic_json(folder / "accounting.json", runtime.summary())
        print(f"Stopped: {exc}", flush=True)
        raise SystemExit(1) from None
    finally:
        if api:
            api.close()
        if db:
            db.close()
        if runtime:
            runtime.close()


if __name__ == "__main__":
    main()
