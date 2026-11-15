# Development workflow — updated 2026-10-10

## Verified repository and environment

Python 3.11+, FastAPI/Jinja, lightweight JavaScript, Pydantic, SQLite; provider ports
and adapters with enforced import boundaries. The lockfile, pytest, Ruff, fake
research/mail adapters and disposable browser server already exist. No new permanent
agents, custom skills or MCP services are required for the current work.

This session runs locally on Windows. The checkout is codex/research-pilot-v1 with
extensive pre-existing uncommitted changes. Cached upstream comparison was 0/0;
no fetch occurred, so current remote synchronization is unverified. There is one
worktree. This audit used one actual specialist agent for an independent read-only audit,
then bounded browser-fixture updates; main-agent code and test integration remained
separate.

Native exec_command failed during helper setup. Node REPL filesystem access and
child_process.execFile/spawn provided an operational local fallback; this is a
session limitation, not a required project dependency. Browser UI tooling reported
no available browsers. The isolated stdlib headless Chrome verifier passed the guided journey (151 checks)
on 2026-10-10; sandboxed Chrome could not start. Never treat
a fallback as permission to bypass restrictions.

## Focused task procedure

1. Read AGENTS.md, git status and relevant implementation/tests.
2. State the intended behavior and make a small plan for substantial changes.
3. Delegate only valuable independent work, with explicit ownership and bounded output.
4. Implement through existing components; do not run paid providers or owner mail in tests.
5. Run targeted tests, then appropriate broader checks. Inspect the diff.
6. Update affected docs and report verified outcomes and remaining gaps.

Do not repeat the complete repository audit for ordinary future features. Reassess
infrastructure when deployment, scale, dependencies or permissions actually change.

## What we are building and how Codex works

Product: improve the existing prospect research → published-email selection → campaign
brief → grounded draft → reviewed send → reply workflow. Keep the current stack and
product identity. Codex agents are development collaborators; application research and
mail jobs remain the existing in-process workers. No agent scheduler, Agents API service,
permanent specialists, model routing or global account settings were added.

Persistent knowledge has separate purposes:
- AGENTS.md: short operating rules, architecture boundaries, authorization and verification.
- DEVELOPMENT.md: how to perform a task and run checks; session/tool limitations.
- IMPROVEMENT_PLAN.md: completed increments, prioritized remaining work and acceptance.
- ARCHITECTURE.md / DECISIONS.md / FAILURE_MAP.md: consult when the task touches those topics.
Repository code and tests verify behavior; old conversation or old test totals do not.

## Build in small phases

1. Define the user-visible outcome, acceptance checks and relevant risks.
2. Inspect the smallest relevant code/test surface and preserve unrelated dirty work.
3. Divide independent work only when beneficial; assign one owner per writable file.
4. Implement one useful increment through existing components. Avoid mixing unrelated
   infrastructure work into a feature. A phase ends with usable, integrated behavior,
   rather than scaffolding or an unverified agent report.
5. Verify from the changed behavior outward, resolve findings, then update the plan and
   report outcomes and limits. Continue authorized work without approval between routine
   reversible phases. Ask only at the existing destructive/paid/architecture boundaries.

Recent completed sequence: prompt-first creation → selected-contact trust → results-first
research → target-or-budget throughput and benchmark → personalization and campaign
review/recovery → repeatable offline CI/browser checks. Current verification is in the plan.

## Verify from the core upward

Use the layers relevant to the change; this is a testing strategy, not a mandate to add
new infrastructure or force test-first code for every edit.

| Layer | What it proves in this project |
| --- | --- |
| Pure core rules | Parsing, role attribution, evidence validation, target counting and grounding |
| Storage and state | Transactions, suppression, checkpoints, budgets, snapshots and approval invalidation |
| Fake-provider integration | Actual HTTP adapter/scheduler, costs, partial results, pause/resume and uncertain-request refusal |
| Routes and templates | Input validation, consent, selection and the same facts/address appearing across flows |
| Browser journey | Labels, mobile overflow, interaction, live updates and saved text persistence |
| Release checks | Ruff, formatting, required full offline suite, diff review and affected documentation |

Run focused tests after each meaningful batch. Run combined/full checks when a change
crosses workflows, after integration. Do not repeat a passing full suite without new
changes or unresolved concerns. Only separately approved live trials can establish current
web recall, OAuth operation or delivery; fictional tests do not prove those outcomes.

## Context, tokens and cost

Read instructions once, then only task-relevant code and references. Use rg and bounded
reads; retain decisions and current state in concise documents rather than copying chats.
Delegate distilled context and ask for concise findings, changed files and actual checks.
Keep raw logs in ignored local artifacts; surface their outcomes and relevant failures.
After compaction or interruption, recover the active task from code, the plan and concise
state, without restarting completed audits or overwriting existing work.

Parallel agents can improve elapsed time and review quality but consume additional model
work. They are not a guaranteed token-saving feature. This repository does not measure
Codex token consumption or configure automatic model selection; no percentage savings are
claimed. Prefer one agent for small tasks and independent specialists for substantial work.
Application cost is separate: existing reservations/caching enforce research caps; strategy6
skips duplicate-source selection calls and empty-source model calls. Preserve reliability.

These conventions agree with official guidance on [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md), and
[focused instructions](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).

## Parallel work protocol

This is a development workflow using the host's agent tools when available. It does
not add an application multi-agent runtime, a background scheduler or permanent agent
configuration. Check capabilities each session; the current session exposes four total
concurrency slots including the main agent. That capacity is not a repository guarantee.

For substantial work with independent tasks:

1. The main agent inspects relevant code, chooses the next increment and identifies
   useful parallel tasks. Keep tightly coupled changes with one owner.
2. Each delegation states its outcome, relevant files, exact files it may edit (or
   read-only scope), constraints, required checks and expected return format. Give
   only the context needed; avoid repeated full-repository audits.
3. Assign each writable file to one agent. Shared worktree changes are immediately
   visible: coordinate ownership before editing, and report new dependencies instead
   of changing another agent's files. Reserve integration files for the main agent.
4. Agents return findings or changed files, checks actually run, and unresolved risks.
   Independent review can run alongside implementation; checks that require the final
   combined changes run after integration.
5. The main agent reviews every result and diff, resolves findings, runs the required
   integrated checks and updates the plan. A delegated success report alone is not
   final verification. Do not spawn further agents without a useful bounded task.
6. Report which tasks actually ran in parallel and which results were integrated.
   When tools or slots are unavailable, proceed sequentially and state the limit.

Useful pairings include implementation plus a read-only safety review, or code changes
plus documentation in separately owned files. Use one agent for small fixes; more
agents are not a success criterion. Existing permission, cost and data boundaries
apply equally to every agent.

## Commands

Install exact dependencies: uv sync --locked --extra dev
Targeted tests: uv run pytest tests/test_prompt_creation.py -q
Full offline tests: uv run pytest
Lint: uv run ruff check .
Formatting: uv run ruff format --check .
Local app: uv run outreach serve --no-browser
Self-contained guided browser QA: uv run python scripts/check_browser.py
(or .venv/Scripts/python.exe scripts/check_browser.py on Windows). It uses an installed
Chrome/Chromium; pass --browser with an explicit executable if detection fails.
The stdlib runner starts its own fresh fake server on an available loopback port,
uses a temporary browser profile, reports the guided PASS/check count and stops only
its own server. No packages, browser downloads, real provider calls or owner DB are
needed. Browser execution may require approved unsandboxed execution on Windows;
permission failure is a verification limit, never a reason to bypass restrictions.
The runner timeout is 120 seconds maximum. This checks the guided harness, not the
separate Playwright campaign journey below.

Manual disposable browser server: uv run python -m tests.fakes.workspace_server --port 8779
Browser harness: tests/browser/guided_workspace.html at /qa/guided on that fake server;
Playwright journey requires Node 18+ and a separately available Playwright runtime.
Start a fresh fake server with --no-auth, then set QA_BASE_URL explicitly to its
loopback origin (for example, http://127.0.0.1:8779) before running
node tests/browser/campaign_journey.cjs. The script checks /qa/state is fresh before
any workflow writes; an authenticated, non-QA or reused server is rejected. Restart
the fixture for each run. Playwright uses its installed Chromium by default;
QA_CHROMIUM_PATH can explicitly select an existing compatible browser. No automatic
browser downloads occur. See docs/CAMPAIGN_READINESS.md for the broader journey.

On Windows the existing .venv/Scripts/python.exe -m pytest and
.venv/Scripts/ruff.exe are equivalent local checks when uv is unavailable. If the
existing pytest cache is unwritable, use -o cache_dir=.local-cache/pytest-cache.

## Boundaries and pending capabilities

- Research reserves cost before requests and caches completed calls. Uncertain calls
  remain held; no automatic retry or budget reset. Publication is not delivery verification.
- Jobs run in-process; one app worker and persistent storage are required. A restart
  does not mean a paid request or mail operation may be replayed.
- Root render.yaml deploys the static demo. deployment/render.yaml describes the
  backend with persistent storage; live deployment was not verified.
- .github/workflows/offline-checks.yml now runs Python 3.11, locked development
  dependencies, Ruff and the offline pytest suite on pushes and pull requests, with
  read-only repository permissions and no credentials or deployment steps. The workflow
  has not been executed remotely in this session. Its dependency installation requires
  network access; application tests use offline fixtures.
- No type checker is configured. Browser dependencies remain separately supplied, not
  reproducibly declared in a package manifest; a pinned browser package/lockfile and
  clean installation verification remain queued. Do not claim Playwright reproducibility
  from syntax checks or the separate headless guided harness.
- A root buyer-leads .xlsx is tracked despite spreadsheet ignore rules. Its contents
  were not inspected in this audit. Owner review is needed before publication or
  synchronization; no deletion or history rewrite was performed.
- Do not claim live OAuth, inbox delivery or current research yield from fake-provider
  tests. Use a separately approved controlled live trial when needed.

## Context and cost discipline

Keep AGENTS.md short, use one living improvement plan, and read only relevant files.
Use existing fixtures and request accounting before adding services or model calls.
Free prompt saving uses local interpretation and direct message storage; broader AI
prompt interpretation must be separately approved and measured if introduced later.
