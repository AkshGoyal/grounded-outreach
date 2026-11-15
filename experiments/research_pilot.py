"""Small, resumable research comparison. Run with --help before any paid work."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import EmailStr, TypeAdapter, ValidationError

from experiments.pilot_runtime import (
    STRING,
    PilotStop,
    Runtime,
    array_schema,
    atomic_json,
    configured,
    object_schema,
    poll_findall,
    session_lock,
    settings,
    stamp,
)

BRIEFS = {
    "textiles": {
        "objective": "Find garment manufacturers in Tiruppur or Ludhiana that may be "
        "relevant prospects for ready-for-dyeing cotton sewing thread. We offer samples. "
        "Potential product fit is an inference, not evidence they currently buy this thread.",
        "conditions": {
            "manufacturer": "Manufactures garments, knitwear or apparel; not only a trader.",
            "location": "Has a manufacturing operation in Tiruppur or Ludhiana, India.",
        },
        "preferences": "Cotton garments, garment dyeing or washing; published purchasing contacts.",
    },
    "jobs": {
        "objective": "Find AI product companies in India potentially relevant for early-career "
        "AI product, AI generalist or analytics job outreach. Discover company suitability "
        "separately from current hiring; do not invent vacancies or employee contact details.",
        "conditions": {
            "ai_product": "Builds and offers an AI software product, not only training courses.",
            "india": "Has an office or team presence in India.",
        },
        "preferences": "Early-career roles, product or generalist work, Bengaluru/Pune/Gurugram; "
        "published recruiting contacts. Record active roles only with a current source.",
    },
}
PLAN_SCHEMA = object_schema(
    {
        "search_queries": array_schema(STRING),
        "alternate_queries": array_schema(STRING),
        "source_types": array_schema(STRING),
        "quality_checks": array_schema(STRING),
    }
)
CANDIDATE_SCHEMA = object_schema(
    {
        "candidates": array_schema(
            object_schema(
                {
                    "company": STRING,
                    "website": STRING,
                    "source_id": STRING,
                }
            )
        )
    }
)
FACT_SCHEMA = object_schema(
    {
        "criterion": STRING,
        "status": {"type": "string", "enum": ["supported", "contradicted", "unknown"]},
        "source_id": STRING,
        "quote": STRING,
    }
)
ASSESS_SCHEMA = object_schema(
    {
        "criteria": array_schema(FACT_SCHEMA),
        "contacts": array_schema(
            object_schema(
                {
                    "kind": {"type": "string", "enum": ["email", "phone", "form"]},
                    "value": STRING,
                    "source_id": STRING,
                    "quote": STRING,
                    "association_quote": STRING,
                }
            )
        ),
        "fit_inference": STRING,
        "unknowns": array_schema(STRING),
    }
)
EMAIL = TypeAdapter(EmailStr)


def public_url(value: str) -> str | None:
    try:
        p = urlsplit(value.strip())
        host = (p.hostname or "").lower()
        if p.scheme not in ("https", "http") or not host or p.username or p.password:
            return None
        if p.port not in (None, 80, 443) or "." not in host:
            return None
        if host.endswith((".local", ".internal", ".localhost", ".invalid", ".example")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))
    except (ValueError, AttributeError):
        return None


def squash(value: str) -> str:
    return " ".join(value.casefold().split())


def source_supported(quote: str, text: str) -> bool:
    return len(quote.strip()) >= 12 and squash(quote) in squash(text)


def sources_from(response: dict, *, full=False) -> list[dict]:
    sources = []
    for item in response.get("results", []):
        url = public_url(item.get("url", ""))
        if not url:
            continue
        content = item.get("full_content") if full else None
        content = content or "\n".join(item.get("excerpts") or [])
        if content:
            sources.append({"url": url, "text": content[:12000], "retrieved_at": stamp()})
    return sources


def named_sources(sources: list[dict], chars=2800) -> dict[str, dict]:
    return {f"s{i}": {**s, "text": s["text"][:chars]} for i, s in enumerate(sources, 1)}


def dedupe(candidates: list[dict]) -> list[dict]:
    seen, result = set(), []
    for c in candidates:
        website = public_url(c.get("website", ""))
        if not website or not c.get("company", "").strip():
            continue
        # Keep different businesses on shared domains; don't collapse by host alone.
        key = (squash(c["company"]), urlsplit(website).hostname.removeprefix("www."))
        if key not in seen:
            seen.add(key)
            result.append({**c, "website": website})
    return result


def validate_assessment(company: dict, answer: dict, sources: dict, criteria: dict) -> dict:
    checked, contacts, rejected = [], [], []
    for criterion in criteria:
        labels = {squash(label).rstrip(".") for label in (criterion, criteria[criterion])}
        proposed = [
            x
            for x in answer.get("criteria", [])
            if squash(x.get("criterion", "")).rstrip(".") in labels
        ]
        fact = proposed[0] if len(proposed) == 1 else {}
        source = sources.get(fact.get("source_id"), {})
        valid = source_supported(fact.get("quote", ""), source.get("text", ""))
        status = fact.get("status", "unknown") if valid else "unknown"
        if status not in ("supported", "contradicted", "unknown"):
            status = "unknown"
        checked.append(
            {
                "criterion": criterion,
                "status": status,
                "quote": fact.get("quote", "") if valid else "",
                "source_url": source.get("url") if valid else None,
                "retrieved_at": source.get("retrieved_at") if valid else None,
            }
        )
    seen = set()
    for item in answer.get("contacts", []):
        source = sources.get(item.get("source_id"), {})
        quote, value = item.get("quote", ""), item.get("value", "").strip()
        kind = item.get("kind")
        associated = source_supported(item.get("association_quote", ""), source.get("text", ""))
        valid = source_supported(quote, source.get("text", "")) and associated
        normalized = value
        if kind == "email":
            try:
                normalized = str(EMAIL.validate_python(value)).lower()
            except ValidationError:
                valid = False
            valid = valid and bool(
                re.search(
                    r"(?<![\w.+-])" + re.escape(value) + r"(?![\w.-])",
                    quote,
                    re.I,
                )
            )
        elif kind == "phone":
            digits = re.sub(r"\D", "", value)
            valid = valid and 7 <= len(digits) <= 15 and value in quote
            normalized = ("+" if value.startswith("+") else "") + digits
        elif kind == "form":
            normalized = public_url(value)
            valid = valid and normalized is not None and value in quote
        else:
            valid = False
        if not valid:
            rejected.append({"kind": kind, "reason": "Unsupported value, quote or association."})
            continue
        if (kind, normalized) in seen:
            continue
        seen.add((kind, normalized))
        contacts.append(
            {
                "kind": kind,
                "value": value,
                "normalized": normalized,
                "source_url": source["url"],
                "quote": quote,
                "association_quote": item["association_quote"],
                "retrieved_at": source["retrieved_at"],
                "status": "published; ownership and freshness require review",
            }
        )
    supported = bool(checked) and all(x["status"] == "supported" for x in checked)
    return {
        **company,
        "criteria": checked,
        "contacts": contacts,
        "fit_inference": answer.get("fit_inference", ""),
        "unknowns": answer.get("unknowns", []),
        "rejected_contacts": rejected,
        "all_criteria_have_quotes": supported,
        "email_candidate": supported and any(c["kind"] == "email" for c in contacts),
        "review_status": "pending",
        "campaign_ready": False,
        "verification_note": "Quote matching checks source presence, not semantic truth. "
        "Human review must confirm company identity, criterion meaning and contact ownership. "
        "No mailbox deliverability or phone reachability verification has been performed.",
    }


class Research:
    def __init__(self, runtime, brief, mode):
        self.r, self.brief, self.mode = runtime, brief, mode
        self.arm = brief + "-" + mode
        self.folder = runtime.folder / self.arm
        self.folder.mkdir(exist_ok=True)
        self.spec = BRIEFS[brief]

    def save(self, name, data):
        atomic_json(self.folder / (name + ".json"), data)

    def load(self, name):
        file = self.folder / (name + ".json")
        return json.loads(file.read_text(encoding="utf-8")) if file.exists() else None

    def search(self, name, objective, queries):
        key = self.arm + "/search/" + name
        used = sum(k.startswith(self.arm + "/search/") for k in self.r.state["calls"])
        if key not in self.r.state["calls"] and used >= 8:
            raise PilotStop("Search limit reached (8 requests per arm).")
        return self.r.paid(
            key,
            self.arm,
            "parallel",
            "/v1/search",
            {
                "objective": objective[:2000],
                "search_queries": queries[:3],
                "mode": "fast",
                "max_chars_total": 10000,
            },
            Decimal("0.001"),
            tariff=True,
        )

    def extract(self, name, urls):
        urls = list(dict.fromkeys(u for x in urls if (u := public_url(x))))[:4]
        if not urls:
            return []
        key = self.arm + "/extract/" + name
        used = sum(
            int(Decimal(v["reserved"]) / Decimal("0.001"))
            for k, v in self.r.state["calls"].items()
            if k.startswith(self.arm + "/extract/")
        )
        if key not in self.r.state["calls"] and used + len(urls) > 20:
            raise PilotStop("Page limit reached (20 URLs per arm).")
        result = self.r.paid(
            key,
            self.arm,
            "parallel",
            "/v1/extract",
            {
                "urls": urls,
                "objective": "Find company identity, business activity, location and published "
                "email addresses and phone numbers. Preserve the text around every contact.",
                "advanced_settings": {"full_content": True},
            },
            Decimal("0.001") * len(urls),
            tariff=True,
        )
        return sources_from(result, full=True)

    def discover(self, plan):
        cached = self.load("candidates")
        if cached is not None:
            return cached
        if self.mode == "findall":
            response = self.r.paid(
                self.arm + "/findall",
                self.arm,
                "parallel",
                "/v1beta/findall/runs",
                {
                    "objective": self.spec["objective"],
                    "entity_type": "companies",
                    "match_conditions": [
                        {"name": k, "description": v} for k, v in self.spec["conditions"].items()
                    ],
                    "generator": "preview",
                    "match_limit": 5,
                },
                Decimal("0.10"),
                tariff=True,
            )
            result = poll_findall(self.r, response["findall_id"])
            self.save("findall-result", result)
            candidates = dedupe(
                [
                    {
                        "company": c.get("name", ""),
                        "website": c.get("url", ""),
                        "discovery_status": c.get("match_status", "unknown"),
                        "discovery_basis": c.get("basis", []),
                    }
                    for c in result.get("candidates", [])
                    if c.get("match_status") == "matched"
                ]
            )[:5]
        else:
            candidates, all_sources = [], []
            for round_no, queries in enumerate(
                (plan["search_queries"], plan["alternate_queries"]),
                1,
            ):
                response = self.search(
                    "discovery-" + str(round_no),
                    self.spec["objective"],
                    queries,
                )
                all_sources.extend(sources_from(response))
                context = named_sources(all_sources[:10], chars=1500)
                self.save("discovery-sources", context)
                answer = self.r.llm(
                    self.arm + "/discover-" + str(round_no),
                    self.arm,
                    "Select at most five DISTINCT relevant companies from these sources. "
                    "Use a source_id from the supplied map. The website must be an actual "
                    "URL present in the source text or a supplied source URL, never guessed. "
                    "Prefer an official website. Return no candidate if no company URL "
                    "can be established. Brief: "
                    + json.dumps(self.spec)
                    + "\nSOURCES: "
                    + json.dumps(context, ensure_ascii=False),
                    CANDIDATE_SCHEMA,
                )
                for c in answer.get("candidates", [])[:5]:
                    source = context.get(c.get("source_id"), {})
                    website = public_url(c.get("website", ""))
                    urls = {s["url"] for s in context.values()}
                    if (
                        source
                        and website
                        and (website in urls or c["website"] in source.get("text", ""))
                    ):
                        candidates.append(
                            {
                                "company": c["company"],
                                "website": website,
                                "discovery_source": source.get("url"),
                            }
                        )
                candidates = dedupe(candidates)[:5]
                if len(candidates) >= 5:
                    break
        self.save("candidates", candidates)
        return candidates

    def assess(self, number, company, sources):
        context = named_sources(sources[:5], chars=3000)
        self.save("sources-" + str(number), context)
        answer = self.r.llm(
            self.arm + "/assess-" + str(number),
            self.arm,
            "Assess this company against every criterion. For supported/contradicted "
            "return an exact source quote and its source_id. If missing, use unknown. "
            "For contacts return exact published values and an exact quote containing "
            "each value, plus an association_quote showing the contact belongs to this "
            "company (company heading, footer, or nearby company-specific text). "
            "Exclude directory/platform support contacts. Do not infer personal details, "
            "hiring, WhatsApp availability, buyer intent or deliverability. Only use "
            "these sources. Fit inference must be explicitly tentative.\nCOMPANY: "
            + json.dumps({k: company[k] for k in ("company", "website")})
            + "\nBRIEF: "
            + json.dumps(self.spec)
            + "\nSOURCES: "
            + json.dumps(context, ensure_ascii=False),
            ASSESS_SCHEMA,
        )
        return validate_assessment(company, answer, context, self.spec["conditions"])

    def run(self, plan):
        candidates = self.discover(plan)
        leads, stop_reason = [], "sample_complete"
        for number, company in enumerate(candidates, 1):
            cached = self.load("lead-" + str(number))
            if cached is not None:
                leads.append(cached)
                continue
            try:
                source_cache = self.load("raw-sources-" + str(number))
                if source_cache is None:
                    # One targeted search per company, plus a second only when capacity
                    # remains and no contact-looking text was retrieved. Both arms use
                    # this same contact retrieval and assessment path.
                    query = company["company"] + " official contact email phone"
                    response = self.search(str(number), query, [query])
                    found = sources_from(response)
                    urls = [company["website"], *[s["url"] for s in found[:2]]]
                    source_cache = self.extract(str(number), urls)
                    if not any("@" in s["text"] for s in source_cache):
                        used = sum(
                            k.startswith(self.arm + "/search/") for k in self.r.state["calls"]
                        )
                        pages = sum(
                            int(Decimal(v["reserved"]) / Decimal("0.001"))
                            for k, v in self.r.state["calls"].items()
                            if k.startswith(self.arm + "/extract/")
                        )
                        if used < 8 and pages < 20:
                            fallback = self.search(
                                str(number) + "-missing",
                                "Find a published company email in contact "
                                "pages or brochures; never guess.",
                                [company["company"] + " email brochure contact"],
                            )
                            extra = sources_from(fallback)
                            if extra:
                                source_cache.extend(
                                    self.extract(
                                        str(number) + "-missing",
                                        [extra[0]["url"]],
                                    )
                                )
                    self.save("raw-sources-" + str(number), source_cache)
                lead = self.assess(number, company, source_cache)
                self.save("lead-" + str(number), lead)
                leads.append(lead)
                print(f"{self.arm}: assessed {number}/{len(candidates)}", flush=True)
            except PilotStop as exc:
                stop_reason = str(exc)
                break
        result = {
            "brief": self.spec,
            "method": self.mode,
            "discovered": len(candidates),
            "assessed": len(leads),
            "leads": leads,
            "stop_reason": stop_reason,
            "email_candidates_pending_review": sum(x["email_candidate"] for x in leads),
            "human_verified_usable_leads": None,
            "cost_per_verified_usable_lead": None,
            "arm_accounted_usd": str(self.r.charged(self.arm)),
        }
        self.save("results", result)
        return result


def make_plan(runtime, brief):
    path = runtime.folder / (brief + "-plan.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    plan = runtime.llm(
        "plan/" + brief,
        "plans",
        "Plan a tiny lead research experiment for this fixed brief. Do not change the "
        "mandatory conditions or invent company names. Return 2-3 initial search queries "
        "and 2-3 alternate queries pursuing different source types, useful source types, "
        "and concrete quality checks. Prefer company websites and relevant directories. "
        "No need to find actual leads in this planning call.\n" + json.dumps(BRIEFS[brief]),
        PLAN_SCHEMA,
    )
    for field in ("search_queries", "alternate_queries"):
        if not isinstance(plan.get(field), list) or not 1 <= len(plan[field]) <= 3:
            raise PilotStop("Planner returned an invalid query count.")
        if any(not isinstance(q, str) or not q.strip() or len(q) > 300 for q in plan[field]):
            raise PilotStop("Planner returned an invalid query.")
    atomic_json(path, plan)
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "plan", "run", "report"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--brief", choices=tuple(BRIEFS), default="textiles")
    parser.add_argument("--mode", choices=("custom", "findall"), default="custom")
    # Fixed session path: repeating commands cannot silently reset the $1 cap.
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    folder = root / "data" / "research-pilot-v1"
    config = settings(args.env_file)
    if args.command == "check":
        print(
            json.dumps(
                {
                    "env_file": str(args.env_file.resolve()),
                    "openrouter_configured": configured(config["openrouter"]),
                    "parallel_configured": configured(config["parallel"]),
                    "model": config["model"],
                    "session": str(folder),
                    "max_total_usd": "1.00",
                    "limits_per_arm": {
                        "budget_usd": "0.20",
                        "companies": 5,
                        "search_requests": 8,
                        "extracted_urls": 20,
                    },
                },
                indent=2,
            )
        )
        return 0
    with session_lock(folder):
        runtime = Runtime(folder, config)
        try:
            if args.command == "report":
                print(json.dumps(runtime.summary(), indent=2))
            elif args.command == "plan":
                print(json.dumps(make_plan(runtime, args.brief), indent=2))
                print(json.dumps(runtime.summary(), indent=2))
            else:
                if not configured(config["parallel"]) or not configured(config["openrouter"]):
                    raise PilotStop("Both API keys are required for a live research comparison.")
                plan = make_plan(runtime, args.brief)
                result = Research(runtime, args.brief, args.mode).run(plan)
                print(
                    json.dumps(
                        {k: v for k, v in result.items() if k not in ("leads", "brief")}, indent=2
                    )
                )
                print(json.dumps(runtime.summary(), indent=2))
        except (PilotStop, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PilotStop):
                print(str(exc), file=sys.stderr)
            else:
                print(
                    "Unexpected provider response; checkpoints retained for inspection.",
                    file=sys.stderr,
                )
            print(json.dumps(runtime.summary(), indent=2))
            return 1
        finally:
            runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
