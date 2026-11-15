"""Write docs/WORKBENCH_EVALUATION.md from the saved evaluation, using the app's own numbers.

python scripts/workbench_report.py
"""

from pathlib import Path

from outreach.web.workbench_eval import evaluation

OUT = Path(__file__).resolve().parents[1] / "docs" / "WORKBENCH_EVALUATION.md"


def main():
    r = evaluation()
    lines = [
        "# Outreach Workbench: evaluation on real prospects",
        "",
        f"{r['n']} real executives, {r['goals_count']} different products to pitch, run live "
        f"on {r['dates'][0]}. The same report is in the app under **Evaluation**, with every "
        "email and the public page its hook came from.",
        "",
        "## Headline",
        "",
        "| Result | Value | Detail |",
        "| --- | --- | --- |",
        *(
            f"| {h['label'].capitalize()} | **{h['value']}** | {h['detail']} |"
            for h in r["headline"]
        ),
        "",
        "## Metrics, and why each matters",
        "",
        "| Metric | Value | Detail | Why it matters |",
        "| --- | --- | --- | --- |",
        *(f"| {m['name']} | **{m['value']}** | {m['detail']} | {m['why']} |" for m in r["metrics"]),
        "",
        "Hook strength: " + ", ".join(f"{s['count']} {s['label']}" for s in r["strengths"]) + ".",
        "",
        "## Three different pitches",
        "",
        "The products and senders are fictional; the prospects are real public executives.",
        "",
        "| Pitch | Prospects | Strong hooks | Ready to send | Cost each | Time each |",
        "| --- | --- | --- | --- | --- | --- |",
        *(
            f"| {g['label']} ({g['sender']}) | {g['prospects']} | {g['strong']} | {g['ready']} "
            f"| ${g['cost']:.3f} | {g['seconds']} s |"
            for g in r["goals"]
        ),
        "",
        "## Every prospect",
        "",
        "| Prospect | Pitch | Hook | Verdict | Cost | Time | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *(
            f"| {p['name']}, {p['role']}, {p['company']} | {p['goal_label']} | "
            f"{p['strength_label']} | {p['verdict_label']} | ${p['cost_micro'] / 1e6:.3f} | "
            f"{p['seconds']} s | {p['review']['note']} |"
            for p in r["prospects"]
        ),
        "",
        "## Two example emails",
        "",
    ]
    for name in ("John Vandemore", "Christina Schelling"):
        p = next(x for x in r["prospects"] if x["name"] == name)
        lines += [
            f"**{p['name']}, {p['role']}, {p['company']}** ({p['goal_label']}). Hook from "
            f"[{p['hook']['source_title'] or 'the source'}]({p['hook']['source_url']}).",
            "",
            f"> **Subject:** {p['email']['subject']}",
            ">",
            *("> " + line if line else ">" for line in p["email"]["body"].splitlines()),
            "",
        ]
    lines += [
        "## What testing found, and what was fixed",
        "",
        f"Before the fixes: {r['first_attempt']['reached_review']} of {r['n']} reached a draft, "
        f"{r['first_attempt']['strong_hooks']} had a Strong hook, "
        f"{r['first_attempt']['first_pass']} passed the checks on the first draft. Each problem "
        "was fixed, covered by a test, and the affected prospects were run again.",
        "",
        *(
            f"{n}. **{f['problem']}** {f['fix']} *(Found on {f['found_on']}.)*"
            for n, f in enumerate(r["fixes"], 1)
        ),
        "",
        "## How this was measured",
        "",
        "- Each prospect was run once as a rep would: name, company and title, Thorough "
        "research, with an email, using that goal. Runner: `scripts/workbench_evaluate.py`; "
        "prospects and goals: `evaluation/workbench_cases.json`.",
        f"- {r['method']}",
        f'- "About {r["manual_minutes"]} minutes by hand" is the research time per prospect '
        "given in the brief; review time is not counted on either side.",
        f"- Costs are what the providers charged: ${r['final_spend']:.2f} for the {r['n']} "
        f"final runs, ${r['total_spend']:.2f} for all {r['runs']} runs including re-runs.",
        "- Fifteen prospects is a small sample. It shows the process works across roles, "
        "companies and pitches; it does not measure reply rates.",
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"Wrote {OUT.relative_to(OUT.parents[1])}")


if __name__ == "__main__":
    main()
