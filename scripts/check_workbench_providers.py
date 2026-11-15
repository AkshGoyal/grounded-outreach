"""Explicit, bounded Workbench provider smoke check; no application or mail workers.

Without --live, only reports credential presence. Live calls use a separate saved
ledger so reruns reuse completed responses and never replay held requests.
"""

import argparse
import json
import time
from pathlib import Path

import httpx

from outreach.adapters.db import connect
from outreach.adapters.platform_store import PlatformStore
from outreach.adapters.provider_connection import check_openrouter
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import ConfigError, Settings
from outreach.core.research import ResearchStop

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".local-cache" / "workbench-provider-smoke.db"
BUDGET_MICRO = 20_000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow four bounded paid requests")
    parser.add_argument("--credential-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--model-attempt",
        type=int,
        choices=range(4),
        default=0,
        help="Explicit new model check after a key change; keeps earlier reservations",
    )
    args = parser.parse_args()
    try:
        config = Settings(_env_file=args.credential_file, db_path=str(LEDGER))
    except ValueError:
        print("Invalid configuration; no calls made. Check variable names and value types.")
        return 1
    missing = [
        "OUTREACH_" + name.upper()
        for name in ("parallel_api_key", "openrouter_api_key")
        if not getattr(config, name)
    ]
    if missing:
        print("Not configured: " + ", ".join(missing) + ". No calls made.")
        return 1
    print("Both provider keys configured; values are hidden.")
    if not args.live:
        print("No calls made. Use --live for the explicit provider smoke check.")
        return 0

    started = time.monotonic()
    results = []
    with PlatformStore(SqliteStore(connect(LEDGER))) as store:
        previous = store.one("SELECT id FROM research_runs ORDER BY created_at LIMIT 1")
        run = (
            previous["id"]
            if previous
            else store.new_run(
                title="Workbench provider smoke check",
                brief="One public-documentation search/read and two tiny model responses.",
                purpose="provider verification",
                tags="workbench-smoke",
                project_id=None,
                target=1,
                budget=BUDGET_MICRO,
            )
        )
        if not previous:
            store.set_run(run, status="running")
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            api = ResearchAPI(config, store, run, client=client)

            def check(label, function):
                if time.monotonic() - started >= 90:
                    results.append({"check": label, "result": "not started: deadline reached"})
                    return
                client.timeout = httpx.Timeout(min(20, 90 - (time.monotonic() - started)))
                before = time.monotonic()
                try:
                    detail = function()
                    results.append({"check": label, "result": "passed", "detail": detail})
                except Exception as exc:
                    # Never print provider bodies, credentials or configuration exceptions.
                    results.append(
                        {"check": label, "result": "failed", "error_type": type(exc).__name__}
                    )
                    if isinstance(exc, (ConfigError, ResearchStop)):
                        # These errors contain operator guidance, not response bodies.
                        results[-1]["reason"] = str(exc)
                results[-1]["seconds"] = round(time.monotonic() - before, 2)

            check("OpenRouter authentication", lambda: check_openrouter(config, client=client))

            def search():
                data = api.search(
                    "search",
                    "Find official Parallel Search API documentation.",
                    ["Parallel Search API documentation"],
                )
                count = len(data.get("results", []))
                if not count:
                    raise ValueError("Empty search result")
                return {"results": count}

            def read():
                data = api.paid(
                    "read",
                    "parallel",
                    "/v1/extract",
                    {
                        "urls": ["https://www.python.org/about/"],
                        "objective": "Read the public description of Python.",
                        "advanced_settings": {"full_content": True},
                    },
                    1000,
                )
                pages = data.get("results", [])
                text = " ".join(
                    p.get("full_content") or " ".join(p.get("excerpts") or []) for p in pages
                )
                if "python" not in text.casefold():
                    raise ValueError("No usable page text")
                return {"readable_pages": len(pages), "characters": len(text)}

            check("Parallel web search", search)
            check("Parallel public-page read", read)
            model_keys = []
            for role, model in [("research", config.research_model), ("draft", config.llm_model)]:
                call_key = f"{role}/attempt-{args.model_attempt}" if args.model_attempt else role
                model_keys.append(call_key)

                def model_check(model=model, call_key=call_key):
                    data = api.paid(
                        call_key,
                        "openrouter",
                        "/chat/completions",
                        {
                            "model": model,
                            "max_tokens": 96,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": 'Return exactly the JSON object {"ok":true}.',
                                }
                            ],
                            "response_format": {
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "smoke_check",
                                    "strict": True,
                                    "schema": {
                                        "type": "object",
                                        "properties": {"ok": {"type": "boolean"}},
                                        "required": ["ok"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "provider": {
                                "require_parameters": True,
                                "max_price": {"prompt": 1, "completion": 5, "request": 0},
                            },
                        },
                        2500 if args.model_attempt else 5000,
                    )
                    content = json.loads(data["choices"][0]["message"]["content"])
                    if content != {"ok": True}:
                        raise ValueError("Unexpected structured output")
                    return {"model": model, "structured_output": True}

                check(role + " model", model_check)
        held = store.one("SELECT COUNT(*) AS n FROM research_calls WHERE status!='complete'")["n"]
        current_keys = ["search", "read", *model_keys]
        current_held = sum(
            1
            for key in current_keys
            if (entry := store.call(run, key)) and entry["status"] != "complete"
        )
        report = {
            "results": results,
            "held_requests": held,
            "current_attempt": args.model_attempt,
            "current_attempt_held_requests": current_held,
            "ledger": str(LEDGER),
            "budget_usd": BUDGET_MICRO / 1_000_000,
            "accounted_usd": store.run(run)["spent_micro"] / 1_000_000,
        }
        destination = LEDGER.with_suffix(".json")
        destination.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 0 if all(r["result"] == "passed" for r in results) and not current_held else 1


if __name__ == "__main__":
    raise SystemExit(main())
