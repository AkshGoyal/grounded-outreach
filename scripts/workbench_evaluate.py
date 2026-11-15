"""Run the evaluation set against a running live Outreach Workbench and save the results.

Each prospect is one paid run (about $0.02) started exactly as a rep would start it:
the goal, the prospect, Thorough research, with an email. Runs go one at a time and the
results file is rewritten after each, so a problem found early costs one run, not fifteen.
A prospect that already has a saved result is skipped unless --redo names it.

    python scripts/workbench_evaluate.py --base-url http://127.0.0.1:8795 --only finance:1

Nothing is sent to any prospect. The saved record holds the prospect's name, company and
title, the hook with its public source link, the drafted email and the run's numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evaluation" / "workbench_cases.json"
RESULTS = ROOT / "src" / "outreach" / "web" / "evaluation" / "workbench_results.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, data=data))
    except urllib.error.HTTPError as response:
        if response.code == 303:
            return response.headers["location"]
        raise SystemExit(f"{url} answered {response.code}: {response.read()[:400]!r}") from None
    raise SystemExit(f"{url} did not redirect; the form was not accepted.")


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def _seconds(run):
    stamps = [s["created_at"] for s in run.get("stages") or [] if s.get("created_at")]
    if not stamps:
        return 0
    first, last = (datetime.fromisoformat(x) for x in (run["created_at"], max(stamps)))
    return max(0, round((last - first).total_seconds()))


def record(goal, prospect, run):
    """The numbers and text the report needs from one saved run; nothing else is kept."""
    result = run.get("result") or {}
    hook = result.get("hook") or {}
    draft = run.get("draft") or {}
    check = draft.get("check") or {}
    sources = result.get("sources") or []
    by_id = {s.get("id"): s for s in sources}
    hook_source = by_id.get((hook.get("source_ids") or [None])[0]) or {}
    content = [
        s
        for s in check.get("segments", [])
        if s.get("part") == "body" and s.get("role") not in ("greeting", "signoff", "cta")
    ]
    drafts = run.get("drafts") or []
    asked = [
        s["detail"]
        for s in run.get("stages") or []
        if s.get("name") in ("Draft model request", "Repair model request")
        and s.get("detail", "").startswith("Asking ")
    ]
    signals = result.get("candidate_signals") or []
    return {
        "goal": goal["id"],
        "name": prospect["name"],
        "company": prospect["company"],
        "role": prospect["role"],
        "why_chosen": prospect.get("why", ""),
        "run_id": run["id"],
        "ran_at": run["created_at"],
        "execution_status": run["execution_status"],
        "outcome": run.get("business_outcome"),
        "identity": (result.get("identity") or {}).get("status"),
        "hook": {
            "strength": hook.get("strength"),
            "basis": hook.get("basis", "read_source"),
            "title": hook.get("title"),
            "summary": hook.get("summary"),
            "event_date": hook.get("event_date"),
            "verdict": (hook.get("judgement") or {}).get("verdict"),
            "source_title": hook_source.get("title") or hook_source.get("publisher"),
            "source_url": hook_source.get("url"),
        },
        "facts": {
            "usable": len(signals),
            "set_aside": len(result.get("rejected_signals") or []),
            "angles": sorted({s.get("angle") for s in signals if s.get("angle")}),
        },
        "sources": {
            "usable": sum(s.get("access_status") in ("read", "excerpt") for s in sources),
            "seen": len(sources),
        },
        "email": {
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "words": check.get("word_count"),
            "origin": draft.get("origin"),
            "writer": asked[-1].removeprefix("Asking ").rstrip(".") if asked else None,
            "versions": len(drafts),
            "first_pass": bool(drafts) and bool(drafts[0].get("supported")),
            "passed": bool(check.get("ok")),
            "sentences": len(content),
            "backed": sum(bool(s.get("support_ids")) for s in content),
            "blocked_before_review": len((drafts[0].get("check") or {}).get("errors", []))
            if drafts and "check" in drafts[0]
            else None,
        }
        if draft
        else None,
        "cost_micro": (run.get("usage") or {}).get("spent_micro", 0),
        "seconds": _seconds(run),
        "held_requests": (run.get("usage") or {}).get("held_requests", 0),
        "problems": [
            f"{s['name']}: {s.get('detail', '')[:160]}"
            for s in run.get("stages") or []
            if s.get("status") == "failed"
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8795")
    parser.add_argument("--only", action="append", default=[], help="goal or goal:N (1-based)")
    parser.add_argument("--redo", action="append", default=[], help="goal:N to run again")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / ".local-cache" / "workbench-eval-raw")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text())
    saved = json.loads(RESULTS.read_text()) if RESULTS.exists() else {"records": []}
    records = {(r["goal"], r["name"]): r for r in saved["records"]}
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    for goal in cases["goals"]:
        for number, prospect in enumerate(goal["prospects"], 1):
            tag = f"{goal['id']}:{number}"
            if args.only and goal["id"] not in args.only and tag not in args.only:
                continue
            key = (goal["id"], prospect["name"])
            if key in records and tag not in args.redo:
                print(f"{tag} {prospect['name']}: already saved, skipped")
                continue
            location = _post(
                args.base_url + "/research",
                {
                    "request_id": str(uuid4()),
                    "name": prospect["name"],
                    "company": prospect["company"],
                    "role": prospect["role"],
                    "options": "1",
                    "use_goal": "on",
                    "write_draft": "on",
                    "depth": "thorough",
                    "live_consent": "on",
                    **goal["goal"],
                },
            )
            run_id = re.search(r"/runs/([0-9a-f]+)", location).group(1)
            deadline = time.monotonic() + 400
            while True:
                run = _get(f"{args.base_url}/runs/{run_id}/status")
                if run["execution_status"] not in ("queued", "running"):
                    break
                if time.monotonic() > deadline:
                    raise SystemExit(f"{tag}: run {run_id} did not finish in time.")
                time.sleep(3)
            (args.raw_dir / f"{goal['id']}-{number}-{run_id}.json").write_text(json.dumps(run))
            entry = record(goal, prospect, run)
            if key in records:
                entry["rerun_of"] = records[key]["run_id"]
            records[key] = entry
            ordered = [
                records[(g["id"], p["name"])]
                for g in cases["goals"]
                for p in g["prospects"]
                if (g["id"], p["name"]) in records
            ]
            RESULTS.write_text(
                json.dumps(
                    {
                        "goals": [
                            {"id": g["id"], "label": g["label"], "goal": g["goal"]}
                            for g in cases["goals"]
                        ],
                        "manual_minutes_per_prospect": cases["manual_minutes_per_prospect"],
                        "records": ordered,
                    },
                    indent=1,
                    ensure_ascii=False,
                )
                + "\n"
            )
            email = entry["email"] or {}
            print(
                f"{tag} {prospect['name']}: {entry['outcome']}, hook {entry['hook']['strength']}, "
                f"identity {entry['identity']}, ${entry['cost_micro'] / 1e6:.3f}, "
                f"{entry['seconds']}s, writer {email.get('writer')}, "
                f"first pass {email.get('first_pass')}, problems {len(entry['problems'])}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
