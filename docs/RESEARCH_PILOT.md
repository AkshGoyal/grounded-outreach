# Research pilot: measure before integration

This experiment compares our own Parallel Search/Extract loop with Parallel
FindAll preview discovery. Both use the same contact retrieval and OpenRouter
assessment. It never opens the campaign database or connects to email.

## Keys and running

Use the existing ignored `.env` in your original checkout. Keep its configured
`OUTREACH_OPENROUTER_API_KEY` and add `OUTREACH_PARALLEL_API_KEY`.
Never paste keys into a command or commit them. The pilot also accepts the
generic `OPENROUTER_API_KEY` and `PARALLEL_API_KEY` names. Environment variables
override the same names in the file.

Codex Cloud variables are available only inside that Cloud environment, not in
a local Windows Work Mode session. For Cloud, configure `OUTREACH_PARALLEL_API_KEY`
and `OUTREACH_OPENROUTER_API_KEY` (the generic key names above also work), then
start a new task/session on the pilot branch. Set `OUTREACH_LLM_MODEL` to
`anthropic/claude-haiku-4.5`. If using Cloud secrets, confirm the execution phase
can access them; a setup-only secret is insufficient for research commands.
Run `uv sync --extra dev` and `uv run python -m experiments.research_pilot check`
before paid work. Do not print secret values. For a local run, add the keys to
the local ignored `.env` instead.

Run from this worktree, using the existing virtual environment's Python or
`uv run python`. Replace PATH_TO_ENV with the original checkout's `.env`:

```powershell
python -m experiments.research_pilot check --env-file PATH_TO_ENV
python -m experiments.research_pilot plan --env-file PATH_TO_ENV --brief textiles
python -m experiments.research_pilot plan --env-file PATH_TO_ENV --brief jobs
python -m experiments.research_pilot run --env-file PATH_TO_ENV --brief textiles --mode custom
python -m experiments.research_pilot run --env-file PATH_TO_ENV --brief textiles --mode findall
python -m experiments.research_pilot run --env-file PATH_TO_ENV --brief jobs --mode custom
python -m experiments.research_pilot run --env-file PATH_TO_ENV --brief jobs --mode findall
python -m experiments.research_pilot report
```

`check` and `report` make no API calls. `plan` uses OpenRouter only. `run` requires
both keys. The current inexpensive model is `anthropic/claude-haiku-4.5`;
the pilot reads `OUTREACH_LLM_MODEL` and restricts eligible providers to prices
of at most $1/million input and $5/million output tokens, no request fee.
An incompatible model stops instead of selecting a more expensive provider.

## Limits and accounting

One fixed session lives in ignored `data/research-pilot-v1/`. Do not delete or
move the ledger to get around limits. These are local request-admission limits,
not provider account spending caps. Provider pricing changes, billing overhead
or unexpected metering can differ; reconcile with provider dashboards. Other
apps using these keys are outside this budget.

| Limit | Value |
| --- | --- |
| Entire pilot | $1 maximum local accounted/reserved spend |
| Each brief/method combination | $0.20 |
| Both planning calls together | $0.10 |
| Companies per combination | Up to 5 |
| Custom discovery | At most 2 search rounds |
| Search requests per combination | 8 including contact retrieval |
| Extracted URLs per combination | 20 |
| Model output per call | 2,000 tokens |
| Model prompt per call | 24,000 UTF-8 bytes |
| HTTP timeout | 90 seconds |
| FindAll polling per invocation | 180 seconds, then resume same run |

The four combinations plus planning allocate at most $0.90 of the $1 ceiling.
Stop on budget, quota, authentication/network error, malformed output, or
completed sample. Missing contact text gets at most one extra search per
company when capacity remains. The pilot may stop with fewer than five results.

Cost is reserved to disk **before** each paid request. Completed responses are
cached; interrupted POST requests are never automatically replayed. An uncertain
request retains its full reservation. Check its provider outcome before recovery.
FindAll's saved ID allows polling the same run without buying another preview.
Only remove a stale `pilot.lock` after confirming no pilot process is running.

Prices checked 2026-10-03 from [Parallel pricing](https://docs.parallel.ai/getting-started/pricing):
fast search $0.001/request; extraction $0.001/URL; FindAll preview $0.10/run.
Preview evaluates roughly 5-10 candidates and does not promise five matches.
It is a cheap feasibility check, not a representative benchmark of paid FindAll
tiers. No additional FindAll enrichment is requested.

For illustration, eight searches plus twenty pages cost $0.028 before models;
FindAll preview adds $0.10. A Haiku call with 4,000 input and 1,000 output tokens
is $0.009 at the price ceilings. Actual call sizes vary. OpenRouter `usage.cost`
is recorded when available; Parallel totals are tariff estimates, not measured
invoice charges. Missing usage keeps the conservative reservation. Costs that
exceed a reservation stop all new paid work for reconciliation.

## Quality and reviewing results

Two fixed briefs cover manufacturers in Tiruppur/Ludhiana for potential RFD
cotton sewing-thread samples, and AI product companies with an India presence
for early-career job outreach. These are hypotheses: neither purchasing intent
nor active hiring is inferred as fact.

Each company gets criterion-level supported/contradicted/unknown labels,
source URLs, retrieval times, exact quotes, contacts, unknowns and tentative fit.
The code checks JSON shape, literal quote presence, email syntax and contact
presence in its cited quote. It never guesses email patterns or phone country
codes. A matching quote proves presence in a source, not truth or ownership.

Review each saved `results.json` against its `sources-N.json`:

1. Confirm this is the intended company, not a similarly named business or duplicate.
2. Check each mandatory criterion is actually established by the cited source.
3. Confirm contacts belong to that company, not a directory's support team.
4. Prefer official pages; corroborate directory contacts and assess freshness.
5. Separate general business contacts from relevant purchasing/recruiting contacts.

All records remain `review_status=pending` and `campaign_ready=false`. Published
does not mean deliverable, reachable, hiring, or interested. Missing email is
not an email-ready lead. Human-verified lead count and cost per usable lead stay
null until reviewed; zero usable leads must not produce a fake cost-per-lead.

Compare reviewed unique companies, valid published emails/phones, fit, missing
data, duplicates, sources and total costs. Count overlaps only once in combined
yield. Five candidates per combination is directional evidence, not statistical
proof of a winner. The next implementation decision follows this measurement;
the onboarding UI and campaign import remain outside this experiment.

## Code and tests

`experiments/pilot_runtime.py` owns credentials, HTTP, reservations and replay.
`experiments/research_pilot.py` owns briefs, discovery, evidence and reports.
`tests/test_research_pilot.py` checks budgets, ambiguous failures, cache reuse
and evidence rejection without external requests. Run `python -m pytest`.

## Initial Cloud attempt, 2026-10-03

The Cloud checkout initially contained main at `224265a`. The saved pilot was
recovered from `origin/codex/research-pilot-v1` at `50b2d55`; execution continued
on that branch. The multi-campaign navigation section in PLATFORM_PLAN.md was
preserved. No campaign database or mailbox was opened by the experiment.

Cloud runtime observations reported both keys ready, and the pilot's offline
`check` confirmed both were configured without printing their values. Dependencies
were synced from `uv.lock` using the Cloud cache. All 322 tests passed, along with
lint and formatting checks; three pilot files needed formatting only.

For offline tests in Cloud, remove inherited application credentials from the
test process so fixtures cannot select a real provider through environment
settings. The browser tests need permission to create local sockets, even though
their providers are fakes and they make no external API requests:

```bash
.venv/bin/python - <<'PY'
import os
import pytest
for name in list(os.environ):
    if name.startswith('OUTREACH_') or name in (
        'OPENROUTER_API_KEY', 'PARALLEL_API_KEY', 'ANTHROPIC_API_KEY'
    ):
        del os.environ[name]
raise SystemExit(pytest.main(['-q']))
PY
```

The first live request, `plan/textiles`, used `anthropic/claude-haiku-4.5` and
stopped with OpenRouter HTTP 401. A subsequent read-only `/auth/key` check also
returned 401 and classified the credential as expired. No secret values or
provider response bodies were printed. Parallel authentication has not been
tested remotely: no Parallel requests were made after the OpenRouter failure.

The Cloud ledger retains **$0.020068 reserved**, zero reported usage and zero
Parallel tariff charges. This is a conservative reservation, not a confirmed
invoice charge. No plans or leads were completed, so none of the four methods
has measured yield. The earlier handoff also recorded a $0.020068 reservation;
reconcile that original request separately if its ledger exists elsewhere.

Replace `OUTREACH_OPENROUTER_API_KEY` in the Cloud environment configuration
and start a new Cloud session on this branch. Preserve the Cloud ledger and
check the provider outcome before recovering `plan/textiles`; rerunning it as-is
will stop on the uncertain entry. Do not delete the ledger or start a replacement
session directory to bypass it. All four comparisons remain pending, with the
same $1 ceiling and $0.20 per-combination limits. The pilot has not selected a
winning discovery method.

## Cloud comparison completed, 2026-10-03

After the operator replaced the OpenRouter environment variable, Cloud runtime
observations were current/ready and a read-only authentication check returned
HTTP 200. The existing checkout and ledger were retained; no fresh session
directory or budget reset was used. Parallel authenticated during the comparison.

The confirmed HTTP 401 entry was explicitly reconciled with `status=rejected`,
`http_status=401` and `recovery_key=plan/textiles/recovery-1`. Runtime recovery
preserves the original charged reservation and reserves the new request
separately. Without that explicit marker, rejected/uncertain outcomes still stop.
The earlier handoff's $0.020068 was also carried forward conservatively. Neither
reservation was treated as a confirmed invoice charge or discarded.

Both plans and all four comparisons completed: **15 candidate records assessed
for $0.407160 accounted**, including $0.040136 retained reservations, $0.102024
OpenRouter-reported usage and $0.265 Parallel tariff estimates. Every comparison
stayed below $0.20, 8 searches, 20 extracted URLs and 5 companies. FindAll preview
returned five textile matches and one job-search match; no extra preview was
purchased to fill the job sample. All records remain pending and not campaign-ready.

During execution, the checker was corrected to recognize the declared criterion
description as well as its short key, allowing case/whitespace/final-period
formatting only. Duplicate or unrelated labels remain unknown. All cached
assessments were revalidated offline against their original supplied source maps,
with earlier outputs retained under `validation-audit`. No extra model calls
were used for this correction. Recovery, budget and criterion tests were added;
all **325 offline tests**, lint and formatting checks pass.

The measurement reveals both missed contact text and wrong-company associations;
the two automated textile FindAll email candidates require rejection or identity
resolution, not approval. A separate source review found 16 literal email texts
on apparent company pages for nine records. These are review suggestions, not
verified usable leads. Human-verified yield and cost per usable lead remain null.

See [RESEARCH_PILOT_RESULTS.md](RESEARCH_PILOT_RESULTS.md) for the comparison and
source-review findings. Ignored artifacts in `data/research-pilot-v1/` include
the original cached responses, ledger, per-run results and sources,
`comparison.json`, `comparison.md`, `review-queue.csv`, `source-email-review.csv`
and `cloud-handoff.zip`. Keep the ledger and cached responses on any handoff.
The multi-campaign navigation plan in PLATFORM_PLAN.md is unchanged. The next
increment should fix identity resolution and faithful evidence extraction before
UI integration; the pilot has not established a verified discovery-method winner.

## Additional founder benchmark, 2026-10-04

The operator authorised a small Bangalore AI startup founder-contact test, without
vacancy research. The production baseline and a founder-focused diagnostic used
the existing ledger: $0.083969 additional accounting, $0.491129 combined. Eight
searches and 20 extracted URLs exhausted this arm's request limits. Three candidate
companies yielded zero verified direct founder emails and two general inboxes.
Six manually checked facts and three opening hooks were saved privately for later
drafting. No leads were approved or enrolled, and no mail was sent.

See [founder benchmark findings](FOUNDER_RESEARCH_RESULTS.md). The original
four-way comparison and multi-campaign navigation plan are preserved.

The operator broadened the subsequent contact-review scope to founder, HR/recruiting
or senior management. A separate unpaid public-site review found two published
HR/recruiting department addresses; one has a displayed-address/mailto mismatch
requiring review. This does not revise the founder-only comparison, reset request
limits or establish automated yield. No paid API calls were added; the combined
ledger remains $0.491129. See FOUNDER_RESEARCH_RESULTS.md for the distinction.


## Production-flow acceptance run — 2026-10-05

`experiments/workspace_pilot.py --confirm-live` exercised actual saved-intake,
planning and approved production discovery for the accepted Bangalore AI contact
brief (founder, HR/recruiting or senior management; no guessed addresses/vacancy
hunt). It used an isolated SQLite DB with a $0.12 run/day gate and the original
shared $1 Runtime ledger; no ledger reset or unrelated production budget was used.
The bridge's offline tests prove reservation-before-I/O, shared-cap refusal and
cached-call reuse. Interrupted/error requests retain reservations and never replay.

Eight paid calls completed; $0.022986 accounted, bringing the original combined
ledger to **$0.514115 / $1**. One company and a general inbox were saved, all pending;
zero requested-role contacts were confirmed. No campaigns, live drafting or mail.
See FOUNDER_RESEARCH_RESULTS.md and CAMPAIGN_READINESS.md. Both configured keys also
returned HTTP 200 on separate read-only authentication/status checks. Credential
values and arbitrary response bodies were never printed.
