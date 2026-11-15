# Campaign readiness — 2026-10-05

The application is ready for a **controlled campaign trial after connecting and
testing a real mailbox**. The implemented journey works end to end with simulated
providers. This is not yet proof of live OAuth, inbox delivery, lead yield or
hands-off operation. All execution and verification for this increment took place
in Codex Cloud. Phone testing was postponed at the operator's request.

## What was verified

| Feature | Evidence | Practical limit |
| --- | --- | --- |
| Saved audience and clarification | Browser goal → audience form; offline missing-answer/paid-action gates | Voice depends on browser speech service; no live voice test |
| Research plan and discovery | Browser separate planning/research approvals; actual production pipeline with mocked HTTP | One bounded live production run completed; requested contact quality remains unresolved |
| Source evidence and published emails | Literal-source regression suite; fictional AI/Bengaluru/HR scenario | Human ownership/fit review remains required; deliverability is unknown |
| Lead approval, removal and saved audiences | Browser removes a support-only contact and approves an HR contact; list-to-campaign handoff | Approval never verifies an inbox |
| Multiple campaigns and senders | Career Gmail and partnership Zoho campaigns, import, drafting and sending through separate fake mailboxes | Real provider accounts need connection and consent |
| Personalization and draft review | Generated source-backed product sentence; edit/recheck/approval and sender-change regressions | Automated grounding does not prove all claims semantically true |
| Exact launch review | Signed, expiring review of recipients, subject/body, sender, footer and pace; worker keeps that selection | Reopen launch after changes, expiry or server restart |
| Caps, stop and uncertain sends | Regression suite; uncertainty stops batch, remains pending and reserves daily capacity | Run one app process; do not run a CLI sender concurrently |
| Replies and opt-outs | Account-scoped matching, explicit answer, concurrent/repeated-answer guards, global suppression | Provider consent and a real reply round-trip remain untested |
| Revisit, extend, pause and archive | Existing campaign-state/enrollment/rewrite tests; import to the selected campaign | Completed/paused campaigns need reopening before more sends |
| Restart and recovery | Saved messages/replies/test outcomes; pending sends/answers stay blocked | Running jobs stop on restart; there is no durable queue |
| Full workspace backup | Private downloadable archive; restore/decrypt saved credentials and recover suppression | API keys and OAuth client secrets must be reconfigured separately |
| Desktop frontend | Chromium at 1440px; full form journey and management pages; visual inspection | Browser QA is not an independent user study or complete accessibility audit |
| Provider credentials | Live read-only OpenRouter key check and GET of an existing Parallel run: both HTTP 200 | Authentication does not establish future quota or lead quality |

All **449 offline tests passed**, and lint/format checks passed. Tests use fictional
data and fake model/mail providers. The original $1 research pilot
ledger now accounts **$0.514115**. The additional production-flow run accounted
**$0.022986**, with both SQLite and the original ledger gating every request. It
saved one company and a general inbox, with zero confirmed founder/HR/management
contacts. All results remain pending; no campaign was created and no real email
was sent.

## Changes made during this review

- Home separates first use from returning work and surfaces completed research
  with unreviewed leads. Campaign cards link to the structured message brief,
  sender selection, replies or uncertain-message history as appropriate.
- History shows the exact saved outbound text, recipient, time, message ID and
  accepted/failed/uncertain status, even after restart. It has no resend button.
- Launch requires explicit consent tied to the reviewed selection. Approving more
  drafts or changing content/sender/ending requires a fresh review. A new campaign
  becomes active on launch; completion/pausing remain explicit operator choices.
- Reply answers reserve their request in SQLite before sending. A successful or
  uncertain answer cannot be repeated by refresh, a second concurrent request,
  restart or moving the reply back to “to handle.” A known refused attempt can be
  retried explicitly. Answers respect the global daily cap.
- Tests of a saved draft now require confirmation and a signed single-use request,
  retain outcomes and reject campaign/suppressed recipients. Unsaved edits are not
  part of that test. Account connection tests retain their existing guarded flow.
- Workspace backups include SQLite, campaign text and the mailbox key together.
  They wait for active research/draft/send jobs to finish, verify database integrity
  and archive checksums, and provide a protected download.
- Imports preserve campaign context and reject invalid campaign IDs. Setup explains
  per-campaign accounts, optional legacy defaults and separate AI charges. Fields
  have visible labels; secondary and reject actions have readable contrast.

## What still needs real validation

1. Register Google/Zoho clients against the app's stable HTTPS URL, configure their
   client credentials and grant account-owner consent. Those settings are absent
   in this Cloud environment. See [OAuth setup](OAUTH_SETUP.md).
2. Send one confirmed test to an inbox you control. Check Sent, arrival, spam and
   authentication headers. Provider acceptance is not inbox delivery.
3. Run a tiny campaign to controlled addresses: source-backed drafts → approvals →
   launch → reply → inbox sync → one answer → opt-out. Stop if an outcome is uncertain.
4. Improve and review another real audience sample before relying on automated lead volume.
   The earlier founder-only Bangalore benchmark returned **zero direct founder
   emails**. The two manually reviewed HR contacts are not evidence of improved
   automated yield. The latest production test saved Spike AI with a general
   hello inbox; it does not meet the requested contact-role requirement. See
   [research findings](FOUNDER_RESEARCH_RESULTS.md).
5. Keep and verify a downloaded backup outside the running workspace. Use one
   process with persistent storage. Scheduling, durable workers, automatic follow-ups
   and automatic reply sending are not implemented.

## Reproduce the desktop QA

Install development dependencies, start the disposable server in one terminal:

```sh
uv sync --locked --extra dev
uv run python -m tests.fakes.workspace_server --port 8779
```

In another terminal, with Playwright and Chromium available:

```sh
node tests/browser/campaign_journey.cjs
```

This server uses a temporary directory, fictional contacts and fake providers;
it strips inherited application credentials and never uses the real workspace.
Restart it before each browser run. On systems where Chromium is elsewhere, set
`QA_CHROMIUM_PATH`; use `QA_BASE_URL` for another local port. Reports and screenshots
go to ignored `data/campaign-acceptance/`. They do not contain real recipient data.

For the actual application, use [laptop setup](LAPTOP_SETUP.md).

## Laptop guided workflow verification — 2026-10-06

458 offline tests pass; one Windows symlink test skips. Lint/format pass.
Real headless Chrome executes guided free saving, separate fake planning consent,
independent fake research approval and lead review. All 35 assertions pass, including
390px overflow/labels on Home, audience/save, leads, campaign, settings and email forms.
Refresh preserves matching-version edits, ignores stale cache and never restores
consent. Unsaved scope edits block planning.

Start the disposable server with --no-auth and open /qa/guided for the additional
harness. --no-auth removes only fictional QA authentication and allows same-origin
framing; production protection is unchanged. The longer Playwright journey is updated
but was not executed on this laptop because that runtime is unavailable. Python
acceptance still covers two fake senders, approval/launch guards, simulated sends/replies,
backups and restart.

Actual app integration passed: health/private login, 12 pages/assets, same-origin
protection, and a fictional free draft persisted then removed. Earlier email credentials
were reused, encrypted and unverified. The user's failed reservation remains intact.
No live paid requests or real mail operations were made. See GETTING_STARTED.md.

Latest continuation validation (2026-10-06): 468 offline tests pass, one Windows symlink-privilege skip; 35 Chrome guided checks pass. The normal desktop app responds on port 8000 and live free form persistence passes. New OpenRouter diagnostics only GET key metadata; provider and real mail verification are still pending owner action. No paid research or real email was performed.

Latest UI feedback/removal validation: 475 offline tests passed (one Windows symlink privilege skip), 53 Chrome assertions passed, and 33 targeted checks passed after final template adjustments. Confirmed draft deletion uses fictional QA data only. Live status preserves lead selections; interruptions reconnect without replaying operations. Desktop/390px visuals reviewed. Two email accounts are now recorded as verified in the real workspace. This UI increment ran no live paid research or real emails. Restart the existing desktop backend once to load the new routes.

Final research-status consistency adjustments passed 44 targeted tests and the same 53 Chrome checks. Status badges, saved counts, spend and pause controls update together; earlier desktop processes retain their refresh fallback until restarted.


### Editable research and request clarity (2026-10-07)

Latest validation: 487 offline tests passed, one Windows symlink privilege skip; 66 Chrome guided assertions passed, plus 28 targeted checks after final template placement. Edit audience is available throughout audience views. It saves unused drafts directly and creates free revisions after planning/requests; old approvals and ledgers stay intact.

Saved-result recovery is offline and idempotent, retaining literal evidence and exact website-host restrictions. One suggestion was recovered in the actual workspace; contact/fit checks have not run and the run is paused. A recovered suggestion is not an approved contact. Continuing checks can incur provider costs and requires an explicit owner action. Uncertain calls are not replayed.

The normal owner server is responding but still has its earlier backend loaded. Close its app terminal and reopen START-OUTREACH.cmd to load updated routes. Actual HTML shows the update notice and recovered state. No paid request or real email was made for this increment.


### Additional research batches and visible actions

495 offline tests pass (one Windows privilege skip); 80 real-Chrome assertions pass, plus eight targeted checks after final layout changes. A campaign now offers Find more contacts and a Research tab. Additional batches save free, retain a separate cap/approval, preserve original calls/results, and keep campaign context through revisions and approved-result enrollment. Duplicate members remain skipped. Linked research makes campaign removal an archive action.

Actual owner HTML confirms Edit/removal buttons and explicit update guidance. Backend reload is still an owner close/reopen of START-OUTREACH.cmd. All research providers and email operations in acceptance/Chrome QA were fake; no paid research, real email or real deletion was initiated.


### Final flow, deletion and research update (2026-10-07)

The top-left name is Complete Outreach Tool. Home separates audiences (goal, plan, company/contact research) from campaigns (reviewed recipients, message, drafts and sending). Each audience shows its own name/reference and a saved-state next step: finish details, approve a ready plan, watch progress, continue paused checks, review contacts or inspect an uncertain request. Paid continuation never automatically replays an uncertain outcome.

Delete audience now also supports researched work after explicit confirmation: it moves to Deleted audiences while costs, evidence, existing campaign contacts and research links remain intact. Restore starts no research. Eligible unused drafts remain permanently deletable; active jobs must stop first. No real audience was deleted during this update. Before changes, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261007-032006.

Flexible search is offered for new/revised audiences. It accepts explicitly published general business inbox fallbacks, inspects up to ten discovery sources and prioritizes official contact pages. Evidence from official-site search results is retained when extraction omits an address. Explicit [at]/(dot) spellings can be decoded with the original quote retained. Unknown company-fit facts stay available for human review. Addresses and website identities are never guessed, and suppression remains enforced. Earlier approved runs keep their original request inputs; choose Edit audience and save a revised flexible draft to change the approved scope.

The normal owner app remains running at http://127.0.0.1:8000. Close its terminal and reopen START-OUTREACH.cmd once to load the new backend; keep the new terminal open. The app shows this update requirement. Earlier loaded processes retain their continuation fallback. No paid research or mail operation was performed.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Research continuity update (2026-10-07)

An audience picker now shows one card per explicitly linked audience family. Use this audience includes reviewed, complete, nonsuppressed contacts from all active versions; each contact retains its own research origin. A new audience version does not automatically enroll anyone or alter existing campaign members. Search/fetch counters explain whether research reached contact pages. Free plans still require a separate paid-research approval. Same-run cap changes retain spending and require separate continuation; uncertain calls block both editing limits and replay.

Validation: 560 offline tests passed with one Windows symlink-privilege skip; the real Chrome guided journey passed 138 assertions using fictional research/mail only. Live founder-email yield and provider authorization remain untested; no setup run spends credits or sends real emails.
