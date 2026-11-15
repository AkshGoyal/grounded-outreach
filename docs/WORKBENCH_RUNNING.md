# Outreach Workbench: run, test, deploy

Everything Aksh needs to run, test, deploy and record the Outreach Workbench. Nothing in
this file has been deployed, published, recorded or sent by an agent. Steps marked
**Aksh** are his to do; agents never push, deploy, email or submit.

## 1. What it is, in one minute

An SDR enters a known prospect (name + company; role optional; email not needed). The
workbench answers four questions on one page:

1. **Is this the right person?** Identity is resolved from pages actually read. Same
   name at another employer stops the run for a human choice.
2. **What did we find?** Each source shows publisher, access status and dates. Search
   previews, blocked pages and LinkedIn are listed but never used as proof.
3. **Why this hook?** Signals are gated (support, company, person, date, contradiction)
   before ranking. Old news republished recently, conflicting reports and other
   people's news are held back with a reason.
4. **What can we say with support?** One email is drafted from the hook and approved
   campaign claims, then checked sentence by sentence by deterministic rules. One
   repair is allowed; anything still unsupported blocks approval. The reviewer
   approves an exact revision; copy/export is server-enforced and only returns that
   approved text.

Data flow: form → saved run (prospect + campaign snapshot) → one worker → research
provider (fixture or Parallel + OpenRouter under per-run caps and a paid-request
ledger) → identity → hook → draft → claim check → saved revision → human review →
approved export. Execution status (queued/running/completed/failed/interrupted) is
separate from the business outcome (ready for review, needs more evidence, …).

## 2. Run it locally

Prerequisites: Python 3.11, [uv](https://docs.astral.sh/uv/). From the repo root:

```sh
uv sync --locked
uv run --offline --locked python -m outreach.workbench --port 8780 --data-dir .local-cache/workbench-demo
```

Open <http://127.0.0.1:8780>. Fixture mode is the default: fictional data, no keys,
no network calls. Use a fresh `--data-dir` if a database is from an older phase.

### Fixture replay: the five labelled scenarios

On **New prospect**, pick an example under "Or try an example" to fill the form, then **Start research**.

| Scenario | Prospect (fictional) | Expected outcome | What to show |
| --- | --- | --- | --- |
| Happy path | Maya Rao, Cedar Works | Ready for review | Point at a citation → its source highlights. Approve → Copy approved draft. |
| (a) Two people, same name | Jordan Ellis, Northwind Supply | Needs identity confirmation | Harbor Line Logistics card is "Not selectable". Confirm Northwind → draft never mentions Harbor Line. |
| (b) Too little public information | Priya Nair, Fernhill Foods | Ready for review (Weaker hook) | HTTP 403 page, LinkedIn and sign-in preview listed as not used as proof; identity from a permitted page; the email opens with her role, marked "Weaker hook". |
| (c) Old news, republished | Daniel Okafor, Larkspur Health | Ready for review (evergreen) | 2023 event in a Nov 2026 article and 4-vs-3 reports held back with reasons; hook labelled "Evergreen evidence". Typing "recently" into the draft and **Check edits** → blocked. |
| (d) Draft overclaims | Hannah Brooks, Ridgeway Components | Needs revision | Repair still says "slowing your team down"; Approve disabled and refused by the server. Delete the sentence → Check edits → Approve. |

Any other name in fixture mode gets **Needs more evidence**; the fixture never invents
facts about a real person.

### Live mode (paid; Aksh authorises each run)

Keys are read from `.env` (never printed or committed): `OUTREACH_PARALLEL_API_KEY`,
`OUTREACH_OPENROUTER_API_KEY`.

```sh
.venv/bin/python -m outreach.workbench --mode live --budget-usd 0.05 --daily-usd 0.50 \
  --data-dir .local-cache/workbench-live-L1 --port 8790
```

The form shows the run limits (12 search queries, 6 page reads, 2 follow-ups, 180 s,
$0.05) and requires ticking the consent box. `--daily-usd` caps total spend per UTC day
across all runs in that data folder (default $0.50). A typical Thorough run with an
email costs about $0.01 and takes about 40 seconds. A request whose outcome is
uncertain is **held**, counted, and never replayed.


## 3. Verification (all offline, no paid calls)

```sh
uv run --offline --locked pytest tests/test_workbench_*.py tests/test_architecture.py
uv run --offline --locked python scripts/check_workbench_offline.py
uv run --offline --locked ruff check . && uv run --offline --locked ruff format --check .
uv run --offline --locked python scripts/check_workbench_browser.py \
  --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

Restart/recovery is
covered by tests: a restarted server marks unfinished runs **interrupted**, keeps
completed output, drafts and approvals, and never replays held requests
(`test_workbench_spine.py`, `test_workbench_review.py::test_restart_keeps_drafts_and_approval`,
`test_workbench_review.py::test_held_draft_request_keeps_research_and_is_never_replayed`).

## 4. Live testing so far

Every paid run was approved by Aksh in the session.
Twelve live runs, all for Eric Stober (Innventure CFO), while the research and drafting
were tuned. The latest: Thorough research found 6 facts across person, company and
growth, chose his 19 Oct 2026 appointment as a Strong hook, and Haiku 5.5 wrote an email
that passed every check ($0.011 research + $0.001 rewrite).

Not yet run live: same-name, thin-footprint and old-news prospects, and a live batch.
These edge cases are covered by the fictional examples and the test suite; a short
paid rehearsal with real prospects is recommended before recording.

## 5. Deployment (Aksh applies)

Live at **https://outreach-workbench-workbench.onrender.com** (deployed 12 Nov 2026; the
password is `WORKBENCH_APP_PASSWORD` in the Render dashboard's Environment tab).

Free hosting blueprint: [`deployment/workbench-render-free.yaml`](../deployment/workbench-render-free.yaml)
(Render free plan: sleeps after 15 minutes idle, about a minute to wake; saved runs
reset on restart or redeploy). Build rehearsed from a clean checkout with
`uv sync --locked --no-dev --python 3.11`.

Paid alternative with saved history: [`deployment/workbench-render.yaml`](../deployment/workbench-render.yaml). It deploys
branch `workbench/batch` as one `starter` web service with a 1 GB disk (saved history),
live mode, $0.05 per run and $0.50 per day. Hosted mode was smoke-tested locally with
fictional data: `/health` answers, every other page needs the password, and other
host names are refused.

**Aksh's steps**
1. Push `workbench/batch` (done 12 Nov 2026, at Aksh's request).
2. Render → New → Blueprint → this repo, branch `workbench/batch`, path
   `deployment/workbench-render-free.yaml` (or the paid `workbench-render.yaml`).
3. Enter `OUTREACH_PARALLEL_API_KEY` and `OUTREACH_OPENROUTER_API_KEY` in the dashboard.
   Set `WORKBENCH_APP_PASSWORD` to the password you want evaluators to type (8 characters
   or more; it is never stored in the repo) and share it privately.
5. A fresh hosted data folder starts from the 15 evaluation runs
   (`src/outreach/web/evaluation/showcase.db`, contact details stripped), so History
   is never empty. Their spend does not count toward the hosted daily cap.
4. Deploy manually (auto-deploy is off). Check `/health`, the login, then one live run.

The fictional examples only appear in fixture mode. To give evaluators those too, add a
second free service with `--mode fixture` and no keys (history is not kept there).

## 6. Evaluation table (requirement → where → evidence)

| Requirement (brief) | Where | Evidence |
| --- | --- | --- |
| Prospect in → personalised draft out, human review | `core/workbench.py` `run_pipeline`; run page | `test_workbench_review.py::test_fixture_run_drafts_with_citations_and_export_requires_exact_approval` |
| Grounded in something real about the person | identity gates + hook gates `core/workbench_evidence.py` | `test_workbench_evidence.py` (identity, dates, contradictions, syndication) |
| Claims bound to evidence, meaning not word overlap | `core/workbench_claims.py` `validate_draft` | `test_workbench_claims.py` (causal, tense, dates, fabricated offer, wrong person) |
| Previews/LinkedIn/blocked never proof; URL safety | `admit_sources`, `adapters/workbench_research.SourcePolicy` | `test_workbench_evidence.py`, `test_workbench_parallel.py` |
| Budgets, caps, held requests never replayed | `adapters/workbench_store.py`, `ResearchAPI.paid` | `test_workbench_research_store.py`, `test_workbench_review.py::test_held_draft_request_…` |
| Exact-version approval, server-enforced export, no bulk approval | `workbench_store.approve_draft/approved_export`, `web/workbench.py` | `test_workbench_review.py` (stale edit, evidence change, rejection, run isolation) |
| UI: live stage view, history with statuses and outputs | `templates/workbench/*`, `static/workbench.*` | browser checks: 122 workbench / 120 live-adapter |
| 2–4 realistic edge cases | `adapters/workbench_fixture.SCENARIOS` | `test_workbench_scenarios.py`; browser scenario checks |
| No mail sending/accounts/inbox in Workbench runtime | `wiring.build_workbench_app` | `test_workbench_spine.py` (legacy routes 404), browser legacy-route checks |

## 7. Known limits and next steps

See [WORKBENCH_OVERVIEW.md](WORKBENCH_OVERVIEW.md), sections 5 and 6.
