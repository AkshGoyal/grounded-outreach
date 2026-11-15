# Outreach improvement plan — 2026-10-09

## Objective and scope

Refine the existing research → contact selection → campaign → email → reply journey
using Explee's clear progression as inspiration, while preserving our identity,
human review and modest-volume architecture. The source of truth is implemented
code, not old phase placeholders or marketing claims.

Explee references: https://explee.com/ (public pipeline/FAQs),
https://explee.com/landing-search (natural-language entry/examples),
https://api.explee.com/public/api/docs (search, interpretation and enrichment).
Authenticated Explee workflows were not exercised. Vendor performance figures
were not independently verified; pricing/data counts are not our product targets.

## Current state

Already implemented: saved/revised audiences, bounded staged public-source research,
role/publication evidence, direct campaign handoff, lists/imports, additional batches,
structured briefs, attachments, grounded drafting, exact launch snapshots, sender
accounts, suppression, paced sends, replies and private backups.

Keep Python/FastAPI/Jinja, SQLite and ports/adapters. Existing fake-provider tests,
Ruff, lockfile and browser QA are valuable. Current live contact yield and inbox
arrival are not established by offline tests. Earlier tiny live samples found general
inboxes but zero confirmed requested-role contacts; newer code needs a measured trial.

## Prioritized backlog

Effort is approximate developer days including focused checks; risk describes change
risk. Implementation statuses distinguish this increment from future work.

| Priority | Change | Impact / expected benefit | Effort | Risk | Status |
| --- | --- | --- | --- | --- | --- |
| P0 | Prompt-first creation and protected single-editor text | Fewer inputs and steps; preserve user wording | 2–3 | Medium | Implemented; verification recorded below |
| P0 | Campaign-specific prompts and immutable generation provenance | Prevent cross-purpose sales context and stale results | 2–4 | Medium | Implemented; report and verification below |
| P0 | Concise instructions and focused verification workflow | Less repeated context and approval overhead | <1 | Low | Implemented |
| P0 | Selected-email/role badge consistency and visible exceptions | Prevent misleading contact acceptance | 1–2 | Low–medium | Implemented; verification below |
| P1 | Results-first research page; one next action | Reduce scanning, repeated summaries and phone scrolling | 2–3 | Low | Implemented; verification below |
| P1 | Measured requested-role research benchmark and targeted retrieval | More useful contacts at a known cost | 2–4 | Medium | Offline benchmark and targeted retrieval implemented; live pilot requires separate approval |
| P1 | Personalization facts carried into drafting | Better relevant openings with source traceability | 2–3 | Medium | Implemented |
| P2 | Simpler campaign navigation and full-email review preview | Easier preparation and review | 1–2 | Low | Implemented |
| P2 | Consistent wording, secondary actions and visual spacing | More credible, calm interface | 1–2 | Low | Scoped polish implemented; wider visual redesign unnecessary |
| P2 | Recovery and readiness clarity | Distinguish interruption, uncertain request and delivery | 1–2 | Low–medium | Implemented |
| P2 | Minimal offline CI and reproducible browser tooling | Repeatable verification outside this laptop | 1–2 | Low | CI definition and stdlib browser runner implemented; remote CI unexecuted |
| P3 | Optional delivery-verification adapter | Reduce bad addresses if measured as the bottleneck | TBD | Medium | Conditional; does not establish role/ownership |
| P3 | Broader AI-assisted arbitrary prompt interpretation | Fewer clarification fields for complex prose | TBD | Medium | Conditional; use existing provider and explicit budget |

## Historical prompt-first increment — superseded composer

This section records the earlier implementation. Its separate exact-lines input and
optional detailed campaign fields were replaced by the single-editor KEEP design
in the campaign isolation upgrade below. Audience interpretation remains unchanged.

Audience: one overall prompt describing companies, geography, roles and intent.
Common explicit English patterns and labelled clauses are interpreted locally for
free. The original prompt is retained and shown in the free plan. Missing essentials
are clarified; no geography or contact roles are silently invented. Detailed inputs
remain optional. Complete prompt/detail submissions save and prepare the free plan
in one action. Paid research still requires a separate reviewed approval.

Campaign: one overall message prompt plus optional exact lines. Name/purpose,
organisation, sender and older structured fields remain optional controls. An omitted
name is derived from the supplied message. No provider request is made by saving.
Exact lines reuse the existing fixed ending/signature path: appended as a block at
the end, not arbitrary placement inside AI sentences. Changing message/ending
invalidates unsent approvals. Existing structured briefs and campaign history survive.

Limit: the free audience interpreter is deliberately conservative, not a general NLP
model. Overall audience prompts are limited to 2,000 characters to avoid truncating
the reviewed plan; longer/ambiguous requests use detailed inputs. Company/location
and accepted roles must be checked in the plan. Exact lines are not generated or
rewritten. Saving a message does not infer missing sender facts or launch drafting.

## Next implementation sequence and acceptance

1. Completed trust fixes: shared selected-contact evidence across research, handoff
   and campaign picker; distinct contradicted and unknown criteria; exceptions require
   explicit selection. Missing selected addresses cannot silently fall back or enroll.
2. Completed results-first layout: contacts and useful counts precede request/version
   logs. Partial results stay usable, with next actions preserving uncertainty and
   access to contacts from earlier audience versions.
3. Research benchmark: use existing seed-company inputs and fixtures; measure identity,
   requested-role yield, failure reasons, spend and elapsed time. Rank pages/context
   by requested role before considering another provider. Clarify unsupported custom roles.
4. Personalization continuity: carry a few source-backed product/recent-work facts,
   separately from audience qualification, into enrollment and drafting. Do not treat
   review notes or semantic model summaries as recipient facts.
5. Polish/recovery/CI: reuse shared templates and status endpoints. Preserve launch
   snapshots, suppression and uncertain-request/send guards through all changes.

Premature complexity: new frontend framework/database, distributed jobs, permanent
specialist agents, speculative custom skills/MCPs, CRM migration, mailbox pools,
autonomous replies/follow-ups and model/provider changes without measurements.

## Verification and release status

Verified on 2026-10-09:

- Full offline suite: 608 passed, 1 skipped (Windows symlink privilege).
- Ruff lint and formatting: passed, 156 Python files already formatted.
- Isolated headless Chrome journey: PASS, 148 checks including mobile layouts,
  prompt clarification, revisions, campaign batches, handoff, exact-line persistence,
  attachments and explicit cost/consent boundaries.
- Existing Playwright campaign journey was adapted and syntax reviewed by the
  specialist; the Playwright journey itself was not run in this session.

Browser validation found and fixed Windows CRLF handling in saved copy/closing:
submitted line breaks now survive without extra blank lines. Additional campaign
research batches reuse the same audience form instead of a duplicate older form.
All checks used fictional providers and temporary workspaces. No owner's database,
paid research, real email, deployment or running owner process was changed. Restart
the local application normally to load the changes; live research yield, OAuth and
inbox delivery remain unverified.

## Contact trust and parallel development increment — 2026-10-09

Completed:
- Research, audience handoff and campaign picker display the same selected address
  and role evidence. Both mismatched and unconfirmed criteria are visible, including
  their names. Fit exceptions are not automatically preselected.
- Explicit selection can still accept an exception; original facts remain intact.
  Publication is not delivery verification, and unsupported facts stay out of drafting.
- If a selected address disappears from current evidence, the interface asks the
  user to choose again; direct and legacy campaign/list paths reject it. Suppression
  follows the selected address. Existing campaign members retain their saved addresses.
- Strengthened the persistent parallel-work protocol in AGENTS.md and DEVELOPMENT.md.
  Actual work used two specialist agents alongside the primary: an independent contact
  safety review, and separately owned workflow documentation. The primary integrated
  the review findings and ran combined verification. This uses host-supported Codex
  delegation, not a new application runtime or permanent specialist configuration.

Next product increment at the time: results-first research layout (completed below).
Then a measured role-yield benchmark and source-backed personalization continuity.
Paid trials remain separate from offline implementation.

Verification for this increment: 46 targeted tests passed; full offline suite
619 passed, 1 skipped (Windows symlink privilege); Ruff lint and formatting passed
(157 Python files); git diff --check passed. The isolated headless Chrome guided
journey passed 148 checks. Eleven new regression cases cover cross-page address/role
consistency, distinct fit warnings, manual exception selection, stale direct/legacy
handoff, and selected-address suppression. All provider/mail behavior was fictional;
no paid calls, real sends, deployment or owner-process restart occurred.

## Results-first research increment — 2026-10-09

Completed:
- Compact published-email/company/spending overview and contact selection now appear
  before history, research explanations, request diagnostics and conversation records.
  Repeated email/company statistics and the competing header handoff button are removed.
- Progress, errors and pause controls remain prominent. Draft clarification and explicit
  plan approval appear before diagnostic details. Routine request details are collapsed;
  uncertain outcomes and cached recovery open them for attention.
- Current-run contacts use a direct next-action link to inline selection (all filters).
  If any available contacts come from older versions, the combined audience handoff
  remains the next action, so earlier results are not hidden.
- Resume is not offered in research limits when a provider outcome needs checking.
  Spending/approval rules, source evidence and existing saved work remain intact.

One independent review agent checked state/continuity risks alongside implementation;
its mixed-version navigation finding was fixed and covered by regression tests.
Next: offline requested-role benchmark and targeted research improvements, followed
by source-backed personalization continuity. No paid pilot is part of this increment.

Verification: full offline suite 625 passed, 1 skipped (Windows symlink privilege);
151 isolated headless browser checks passed, including results-before-details and
mobile overflow checks. Ruff lint/format (158 Python files) and git diff --check
passed. Six new state regressions cover partial/live results, plan consent, uncertain
requests and earlier/mixed-version contact navigation. No live provider requests,
real mail, deployment or owner-process restart occurred.

## Throughput and remaining execution — 2026-10-10

Completed scoped implementation:
- New/revised audiences use strategy6: no two-dry-round pause, eight-round limit or
  three-times-target candidate limit. Discovery continues until the target or next
  request cannot fit the approved cap. Known-company-only searches finish when that
  supplied list is checked; manual pause/provider/uncertain/daily-limit guards remain.
- Target counts completed suitable company contacts with distinct unsuppressed addresses,
  excluding contradicted fit, rejected companies and unsupported roles. General fallback
  counts only when allowed. The UI now shows target progress separately from saved names.
- Role-prioritized official pages/context; an HR search continues beyond a generic inbox.
  Repeated identical discovery sources skip another selection-model request.
- Separate official literal company/product context is requested in existing assessment
  calls, validated, carried into enrollment and grounded drafting. Source URL/date
  snapshots remain auditable and are excluded from model facts. Review shows source links.
- Saved full-email preview includes the fixed ending and attachments. Sent drafts use
  durable history instead of today's changed settings. Missing live send-job state no
  longer claims no earlier sends. Message navigation and optional test-send are simplified.
- Locked-dependency offline CI definition, isolated stdlib Chrome verifier, guarded
  Playwright fixture preflight. No new application services or database migration.
- DEVELOPMENT.md now explicitly describes phased implementation, bottom-up verification,
  persistent instructions, independent agent ownership and context/token discipline.

Actual delegation: personalization, campaign review/recovery and CI/browser tasks ran in
parallel with main-agent throughput implementation. The main agent reviewed and integrated
outputs, fixed cross-task provenance display and updated the budget-stop regression.
A later agent follow-up hit account usage limits; its unfinished integration was completed
by the main agent. The browser runner itself completed successfully after the earlier
approval-service usage-limit interruption. No permanent agent configuration was created.

Remaining external or conditional work: controlled live role-yield/delivery/OAuth validation,
remote execution of CI after an authorized push, optional Playwright pinned packaging if
that separate journey is needed, and provider additions only if measurements justify them.
No live provider calls, real mail, deployment or owner-process restart were performed.
Earlier saved research strategies remain stable; save a revised audience to use strategy6.

Verification for final integrated implementation (2026-10-10): 644 offline tests
passed, 1 skipped (Windows symlink privilege); Ruff lint and formatting passed
(162 Python files); git diff --check passed. The self-contained Chrome verifier
completed the guided journey with 151 checks. Campaign full preview/sent history and
provenance rendering have route-level regressions; the separate Playwright journey
was not executed. CI definition is local and remote CI remains unexecuted. Offline
throughput fixture results and their limits are in RESEARCH_BENCHMARK.md.

## Campaign isolation and single-editor upgrade — 2026-10-10

Completed: replaced shared sales-specific prompts with campaign-driven templates,
implement one editor with positioned programmatic KEEP blocks, preserve legacy data,
record generation provenance and block stale results/approvals. Detailed verified
findings, compatibility and file responsibilities: [CAMPAIGN_COMPOSER_REPORT.md](CAMPAIGN_COMPOSER_REPORT.md).
Verification: full offline run 685 passed, 1 skipped (Windows symlink privilege);
final short-input, exact-format, error-feedback and compatibility checks: 15 passed.
Ruff lint/formatting and whitespace checks passed; isolated Chrome guided journey
passed, including single-editor protection, stale browser recovery and campaign switching.
The full run preceded the final short-input/partial-legacy compatibility refinement;
that refinement was checked in the targeted run. No real emails, paid calls, owner DB
changes, external publication or app restart occurred.

Remaining release actions: restart the owner application normally to load the code,
review the current campaign instructions and explicitly regenerate affected older drafts.
Live model quality is unverified; optional provider integrations remain outside this change.

## Calm UI and sanity review — 2026-10-11

Completed:
- Consolidated overlapping colour roots into one light palette: near-white surfaces,
  desaturated sage actions, soft status backgrounds, slate text and visible focus rings.
  Corrected secondary-button/navigation hover colours; retained distinct warning/error
  states and readable helper/suppressed-contact text. No application architecture changes.
- Removed raw research-source metadata from campaign contact facts while retaining
  ordinary personalization facts and research evidence links. Added a route regression.
- Updated obsolete draft-page instructions and the optional Playwright fixture to use
  the single editor and Contacts tab. Marked the earlier composer plan as superseded.
- Expanded isolated Chrome QA to fake generation/saved review and 20 pages at 320px,
  390px and 1440px, with overflow, control labels, representative text contrast and
  keyboard skip-link checks. Visually inspected home, composer and audience screenshots.

Verification: full offline suite passed (one Windows symlink privilege skip; harmless
pytest cache-write warning). Final changed-template/review/browser contracts: 29 tests
passed; new metadata regression and contact-flow suite: 5 passed. Ruff lint/format
(170 Python files), browser fixture syntax and git diff --check passed. Final headless
Chrome journey passed. The optional standalone Playwright journey remains unexecuted.
The full-suite collection preceded the final metadata regression; that regression was
verified separately. No owner DB, paid provider, real mail, deployment or app restart.
Actual delegation: one bounded UI/pipeline audit agent implemented metadata/fixture
fixes and the regression; primary integrated palette and expanded browser QA.

### Remaining pipeline status

Core scoped implementation is complete. Remaining release/validation actions:
1. Restart the owner app normally to load these changes; review current campaign
   instructions and explicitly regenerate older drafts affected by the former prompts.
   Save a revised legacy audience to opt into strategy6 throughput behavior.
2. Separately authorized live research-role yield/cost and model-quality benchmark.
   Offline fixtures verify safeguards, not real-world contact yield or model quality.
3. Live OAuth/mailbox/delivery checks and remote CI execution after authorized release.

Optional, not required to finish this scope: pinned Playwright packaging/execution;
additional research/deliverability providers only after a measured need. Friend-link
publication remains deferred by the user. No permanent agents, extra services or
major rebuild are needed.
