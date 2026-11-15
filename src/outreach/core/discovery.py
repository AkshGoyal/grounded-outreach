"""Validate cached discovery evidence and explain rejected company suggestions."""

import json
import re
from collections import Counter
from urllib.parse import urlsplit

from outreach.core.research import (
    Candidates,
    ResearchStop,
    company_site,
    host,
    literal,
    public_url,
    text_windows,
)


def sources_of(response):
    sources = []
    for result in response.get("results", []):
        url = public_url(result.get("url", ""))
        text = result.get("full_content") or "\n".join(result.get("excerpts") or [])
        if url and isinstance(text, str) and text.strip():
            sources.append(
                {
                    "url": url,
                    "title": result.get("title", ""),
                    "text": text[:100000],
                    "retrieved_at": response.get("_retrieved_at", ""),
                }
            )
    return sources


def discovery_context(sources, source_limit=8):
    return {
        f"s{i}": {**s, "text": text_windows(s["text"], 1800)}
        for i, s in enumerate(sources[:source_limit], 1)
    }


def checked_candidates(sources, answer, source_limit=8):
    context = discovery_context(sources, source_limit)
    accepted, rejected = [], Counter()
    for candidate in answer.candidates:
        source = context.get(candidate.source_id, {})
        original = next((s for s in sources if s["url"] == source.get("url")), {})
        website = public_url(candidate.website)
        text = source.get("text", "")
        urls = {source.get("url")} | {
            public_url(u.rstrip(").,]")) for u in re.findall(r'https?://[^\s<>"\]]+', text)
        }
        # A cited article on the same exact host also substantiates its homepage.
        # Never infer a different domain, directory or unpublished deeper path.
        homepage = bool(
            website
            and urlsplit(website).path == "/"
            and not urlsplit(website).query
            and host(website) == host(source.get("url", ""))
        )
        reason = (
            "missing_source"
            if not source
            else "unverified_website"
            if not website or not company_site(website) or (website not in urls and not homepage)
            else "unsupported_identity"
            if not (
                literal(candidate.identity_quote, original.get("text", ""))
                or (
                    candidate.identity_quote.strip().casefold() == candidate.company.casefold()
                    and re.search(
                        r"(?<!\w)" + re.escape(candidate.company) + r"(?!\w)",
                        original.get("text", ""),
                        re.I,
                    )
                )
            )
            else ""
        )
        if reason:
            rejected[reason] += 1
            continue
        accepted.append(
            candidate.model_dump()
            | {
                "website": website,
                "source_url": source["url"],
                "retrieved_at": source.get("retrieved_at", ""),
            }
        )
    return accepted, dict(rejected)


def saved_discovery(store, run_id):
    accepted, rejected, suggested = [], Counter(), 0
    for number in (1, 2):
        search = store.call(run_id, f"discovery/{number}")
        selection = store.call(run_id, f"discovery-select/{number}")
        if (
            not search
            or not selection
            or search["status"] != "complete"
            or selection["status"] != "complete"
        ):
            continue
        try:
            sources = sources_of(json.loads(search["response_json"]))
            response = json.loads(selection["response_json"])
            answer = Candidates.model_validate_json(response["choices"][0]["message"]["content"])
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            continue
        source_limit = (
            10 if (store.run(run_id)["intake"] or {}).get("research_mode") == "flexible" else 8
        )
        values, reasons = checked_candidates(sources, answer, source_limit)
        suggested += len(answer.candidates)
        accepted.extend(values)
        rejected.update(reasons)
    known = {
        (host(lead["website"]), " ".join(lead["company"].casefold().split()))
        for lead in store.leads(run_id)
    }
    recoverable = []
    for candidate in accepted:
        identity = (host(candidate["website"]), " ".join(candidate["company"].casefold().split()))
        if identity not in known:
            known.add(identity)
            recoverable.append(candidate)
    remaining = max(0, store.run(run_id)["target_count"] - len(store.leads(run_id)))
    return {
        "suggested": suggested,
        "rejected": sum(rejected.values()),
        "reasons": dict(rejected),
        "recoverable": recoverable[:remaining],
    }


def recover_saved_discovery(store, run_id):
    """Caller owns the write transaction/worker lock. No provider is used."""
    run = store.run(run_id)
    if (
        not run
        or run["archived"]
        or run["deleted"]
        or run["status"] not in ("completed", "failed", "paused")
    ):
        raise ResearchStop("Finish or pause this research before recovering saved suggestions.")
    candidates = saved_discovery(store, run_id)["recoverable"]
    for candidate in candidates:
        store.add_candidate(run_id, candidate)
    if candidates:
        values = {
            "progress": f"{len(candidates)} company suggestions recovered locally. "
            "Contact and audience-fit checks have not run. No new request was made."
        }
        if run["status"] == "completed":
            values.update(status="paused", error="")
        store.set_run(run_id, **values)
        store.message(run_id, "assistant", values["progress"])
    return len(candidates)
