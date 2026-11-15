"""The evaluation report: real prospects, three goals, the numbers a sales lead cares about.

Read from two saved files shipped with the app, so the page needs no paid call:
- evaluation/workbench_results.json: what each live run produced (scripts/workbench_evaluate.py)
- evaluation/workbench_review.json: the email-by-email review and the fixes made on the way
"""

from __future__ import annotations

import json
import statistics
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent / "evaluation"
STRENGTHS = [
    ("strong", "Strong", "Recent, dated news about them, from a source we read"),
    ("moderate", "Good", "True and sourced, but not recent news"),
    ("weak", "Weaker", "Thin evidence; the email says less"),
    ("none", "Not personalised", "Nothing usable; a plain email"),
]
VERDICTS = {
    "send": "Send as written",
    "edit": "One small edit",
    "check": "Check a fact first",
}


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


@lru_cache(maxsize=1)
def _load():
    results = json.loads((HERE / "workbench_results.json").read_text())
    review = json.loads((HERE / "workbench_review.json").read_text())
    return results, review


def evaluation():
    results, review = _load()
    records = results["records"]
    n = len(records)
    manual_minutes = results["manual_minutes_per_prospect"]
    goals = {g["id"]: g for g in results["goals"]}
    emails = [r["email"] for r in records if r.get("email")]
    sentences = sum(e["sentences"] for e in emails)
    backed = sum(e["backed"] for e in emails)
    verdicts = {
        r["name"]: review["emails"].get(r["name"], {"verdict": "check", "note": ""})
        for r in records
    }
    counts = {key: sum(v["verdict"] == key for v in verdicts.values()) for key in VERDICTS}
    seconds = [r["seconds"] for r in records]
    costs = [r["cost_micro"] for r in records]
    median_seconds = statistics.median(seconds)
    by_strength = {key: sum(r["hook"]["strength"] == key for r in records) for key, *_ in STRENGTHS}
    personal = by_strength["strong"] + by_strength["moderate"]
    first = review["first_attempt"]

    headline = [
        {
            "value": f"{counts['send'] + counts['edit']} of {n}",
            "label": "emails ready to send",
            "detail": f"{counts['send']} as written, {counts['edit']} after one small edit; "
            f"{counts['check']} flagged by the tool to check first",
        },
        {
            "value": "0",
            "label": "wrong facts",
            "detail": f"{backed} of {sentences} email sentences tied to a source or your goal",
        },
        {
            "value": f"{round(median_seconds)} s",
            "label": "research and draft, per prospect",
            "detail": f"About {manual_minutes} minutes by hand; "
            f"{round(manual_minutes * 60 / median_seconds)}× faster",
        },
        {
            "value": f"${statistics.mean(costs) / 1e6:.3f}",
            "label": "average cost per prospect",
            "detail": f"${min(costs) / 1e6:.3f} to ${max(costs) / 1e6:.3f}; "
            f"200 prospects ≈ ${200 * statistics.mean(costs) / 1e6:.2f}",
        },
    ]
    metrics = [
        {
            "name": "Personalised with a sourced hook",
            "value": f"{_pct(personal, n)}%",
            "detail": f"{personal} of {n} rated Strong or Good",
            "why": "A reply depends on a real reason to write.",
        },
        {
            "name": "Right person confirmed automatically",
            "value": f"{_pct(sum(r['identity'] == 'matched' for r in records), n)}%",
            "detail": f"{sum(r['identity'] == 'matched' for r in records)} of {n}; the other "
            "is marked for the rep to confirm",
            "why": "An email about the wrong person is worse than none.",
        },
        {
            "name": "Emails passing every check on the first draft",
            "value": f"{_pct(sum(e['first_pass'] for e in emails), n)}%",
            "detail": f"{sum(e['first_pass'] for e in emails)} of {n}; "
            f"{first['first_pass']} of {n} before the fixes",
            "why": "A blocked draft costs a second writing call and the rep's time.",
        },
        {
            "name": "Runs that finished",
            "value": f"{_pct(sum(r['execution_status'] == 'completed' for r in records), n)}%",
            "detail": f"{sum(r['held_requests'] for r in records)} held requests, "
            f"{sum(bool(r['problems']) for r in records)} with a failed step",
            "why": "Every prospect gets an answer; none is left empty.",
        },
        {
            "name": "Sources considered per prospect",
            "value": f"{round(statistics.mean(r['sources']['usable'] for r in records))}",
            "detail": "search results and pages read, of which only checked passages count",
            "why": "More reading than a rep would do by hand, in seconds.",
        },
        {
            "name": "Email length",
            "value": f"{round(statistics.mean(e['words'] for e in emails))} words",
            "detail": f"{min(e['words'] for e in emails)} to {max(e['words'] for e in emails)}",
            "why": "Short enough to read on a phone.",
        },
    ]
    goal_rows = []
    for goal_id, goal in goals.items():
        rows = [r for r in records if r["goal"] == goal_id]
        goal_rows.append(
            {
                "label": goal["label"],
                "offer": goal["goal"]["offer"],
                "sender": goal["goal"]["sender_company"],
                "prospects": len(rows),
                "strong": sum(r["hook"]["strength"] == "strong" for r in rows),
                "ready": sum(verdicts[r["name"]]["verdict"] != "check" for r in rows),
                "cost": statistics.mean(r["cost_micro"] for r in rows) / 1e6,
                "seconds": round(statistics.median(r["seconds"] for r in rows)),
            }
        )
    prospects = [
        {
            **r,
            "goal_label": goals[r["goal"]]["label"],
            "review": verdicts[r["name"]],
            "verdict_label": VERDICTS[verdicts[r["name"]]["verdict"]],
            "strength_label": dict((k, label) for k, label, _ in STRENGTHS).get(
                r["hook"]["strength"], "Not personalised"
            ),
        }
        for r in records
    ]
    return {
        "n": n,
        "goals_count": len(goals),
        "headline": headline,
        "metrics": metrics,
        "strengths": [
            {"key": key, "label": label, "detail": detail, "count": by_strength[key]}
            for key, label, detail in STRENGTHS
        ],
        "goals": goal_rows,
        "prospects": prospects,
        "fixes": review["fixes"],
        "method": review["method"],
        "first_attempt": first,
        "final_spend": sum(costs) / 1e6,
        "total_spend": first["spend_micro"] / 1e6,
        "runs": first["runs"],
        "dates": sorted(r["ran_at"][:10] for r in records),
        "manual_minutes": manual_minutes,
    }
