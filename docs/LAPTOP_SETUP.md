# Run and test on your laptop

No Codespaces or phone testing is needed. The browser app runs on your laptop at
**http://127.0.0.1:8000**. Keep the terminal running during research, drafting,
sending and inbox checks. Closing it stops background jobs.

## Start the actual app

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/), then
open a terminal and run:

```sh
git clone https://github.com/AkshGoyal/Outreach-Agent.git
cd Outreach-Agent
git switch codex/research-pilot-v1
uv sync --locked --extra dev
```

If already cloned, use `git pull --ff-only` on this branch instead. GitHub may ask
you to authenticate to the private repository. Keep its current visibility.

Copy `.env.example` to `.env` using your file manager. Open `.env` in your editor:

- Add actual Parallel/OpenRouter keys for live research and drafting. Codex Cloud
  settings do not copy to your laptop; proxy placeholders are not portable API keys.
  Never paste keys into chat or commit `.env`.
- Set a private `OUTREACH_APP_PASSWORD` for workspace sign-in.
- Keep `OUTREACH_OAUTH_PUBLIC_URL` blank for local HTTP use.
- For initial testing, use small research caps and a low daily send cap. Research
  spending is separate from drafting and reply-classification charges. A new local
  database does not reset or extend the original $1 research pilot authorization.

Start:

```sh
uv run outreach serve
```

Your browser opens the app. If it doesn't, visit http://127.0.0.1:8000 yourself.
Save a goal, create a plan only when ready for a paid request, and approve that
plan before discovery. You can prepare campaigns and review drafts before choosing
a sending account. Setup's AI test is also a paid request; skip it if unnecessary.

An existing Cloud database is not downloaded by Git. Use a workspace backup if
you want saved private work, rather than starting an empty local workspace.

## Connect email

For OAuth, use the prepared HTTPS host and [OAuth setup](OAUTH_SETUP.md). Google
and Zoho need registered client applications, exact callback URLs and your consent.
The app currently requires HTTPS for OAuth; a localhost HTTP page will show setup
requirements. Research API keys cannot substitute for mailbox credentials.

For local use, Email accounts also supports Gmail/Zoho **app passwords**, provided
your provider plan/policy allows SMTP and IMAP. Enable the required provider settings,
enter the account and verify it. Assign the intended account in each campaign's
Settings. Verification sends no mail. The laptop needs outbound SMTP/IMAP access.

Neither option is automatically activated by cloning the repository.

## First real campaign check

1. Connect and verify your account, then use “Send a test to yourself.” Confirm
   one test to an inbox you control and check arrival, spam and authentication.
2. Create a small campaign using a different controlled recipient address. Use
   truthful test evidence and a complete message brief. Generate and read every draft.
3. Approve drafts, review the complete emails and sender on Launch, tick the
   confirmation and send. Look at History and the provider's Sent folder.
4. Reply from the receiving inbox. In the app, select the sending account and
   “Check for replies.” Verify the right campaign, edit the suggested answer and
   explicitly send it once.
5. Send an opt-out from the controlled recipient. Sync again and verify it appears
   on Do-not-contact. Keep that test address excluded from future outreach.
6. Back up the workspace and download the archive. Only then move to a small batch
   of manually reviewed real leads. No email address is guessed or guaranteed deliverable.

You explicitly approve the actual sends inside the app. Codex has not run these
real-mail steps. Read [campaign readiness](CAMPAIGN_READINESS.md) for the verified
features and remaining limits.

## Restore a workspace backup

Stop the app. Use a fresh checkout/folder for the restore so existing work stays
available. Extract your generated archive into a separate empty directory; its
`manifest.json` contains SHA-256 checksums for the saved files. Place:

- `outreach.db` at `data/outreach.db` in the fresh project;
- `mail-credentials.key`, if included, beside that database in `data/`;
- the archived `campaigns/` files into the fresh project's `campaigns/` directory.

Configure `.env` separately. A conflicting `OUTREACH_CREDENTIAL_KEY` overrides the
restored file, so remove that override or use the original matching key. Preserve
the original OAuth client configuration for refresh tokens, or reconnect through
provider sign-in. Revoked credentials cannot be restored by a backup.

Start the app and inspect campaign history, suppression and accounts before any
sends. Pending/uncertain messages remain blocked. The archive contains private
contacts, conversations and possibly a key that unlocks mailbox credentials; keep
it secure and never upload it to the repository. The CLI `outreach backup` still
creates a database-only backup; the browser button creates the full workspace bundle.

## Guided local setup and Windows handoff

See [GETTING_STARTED.md](GETTING_STARTED.md). This laptop's new folder is
Desktop/Aksh/Outreach-Agent-Local. Use START-OUTREACH.cmd normally; if a restricted
preview notice appears, use RESTART-OUTREACH.cmd for an authenticated graceful handoff.
Active work refuses restart. Automatic inbox polling stays off.

Settings & connections now accepts masked research keys. Browser-entered values are
encrypted in provider-credentials.enc and applied by the web app; empty fields keep
existing keys and .env is never rewritten. Keep the encrypted file with its original
encryption key; downloadable workspace backups exclude research keys.

On Windows, process-alive uses a read-only process query rather than os.kill(pid,0).
POSIX permission bits do not describe Windows ACLs. The symlink-specific assertion skips
when the account lacks that privilege. The launcher trusts only this checkout for child
Git checks, without changing global trust or Windows security settings.

### Desktop startup continuation

The installed workspace now starts with .venv\Scripts\python.exe directly. No uv invocation is needed when the environment already exists. The browser opens only after the server is listening. Keep the app window open.

When loading newly changed backend code, close the existing app window, then double-click START-OUTREACH.cmd. RESTART-OUTREACH.cmd hands off a restricted preview; an already-running desktop process is opened without reload.

Settings & connections has Check OpenRouter key: it requests key metadata, never a model completion or paid research. This is distinct from the legacy paid model diagnostic. Parallel's dashboard is the owner check for its credits/access. Key acceptance does not prove available account credits or model access.

Latest checks: 468 offline tests passed, one Windows symlink privilege skip; 35 real-Chrome assertions passed. Live desktop login/pages/assets/free save-to-database passed. Email remains saved but unverified.

### Latest UI update

Close the existing app terminal and double-click START-OUTREACH.cmd once to load removal and feedback routes. After that, refresh http://127.0.0.1:8000. Home, audiences and campaigns show Delete / archive; Archived work provides restore. The header shows background activity and progress pages update without replacing selections. See GETTING_STARTED.md for button meanings, deletion limits and connection interruption behavior.

Validation: 475 offline tests passed, one Windows privilege skip; 53 Chrome checks passed, plus 33 final targeted checks. Existing workspace files and provider settings were preserved.


### Audience edit and recovery update (2026-10-07)

The app is responding at http://127.0.0.1:8000. It still has the previous Python backend loaded: close its existing terminal and double-click START-OUTREACH.cmd once, keeping the new window open. An update notice appears until the new routes load.

The latest audience had five completed calls rather than a live queue. One supported company suggestion was recovered from saved results after correcting an exact-host homepage check. Research is paused; contact and fit checks are unfinished. No paid request was made and existing calls, approved inputs, spend and .env were preserved.

Edit audience saves unused drafts directly or creates a revised free draft for work already started. What happened explains companies, published emails, approvals and request outcomes. Two email accounts are now recorded as verified in the live workspace. Latest validation: 487 offline tests passed, one Windows privilege skip; 66 Chrome assertions passed and 28 final targeted checks passed.


### Campaign research continuation and visible controls

Refresh now shows Find more contacts, Edit and Delete / archive. The actual owner app is healthy but still has its older backend; close its terminal and reopen START-OUTREACH.cmd once to enable the new campaign Research and audience/removal routes. Unsupported actions point to explicit update instructions rather than disappearing.

Find more contacts creates a free next research batch with a separate cap and approval. Existing history remains intact; review and enroll approved results back into the same campaign. See GETTING_STARTED.md. Latest: 495 offline tests passed, one Windows skip; 80 Chrome assertions passed. Existing .env unchanged; no paid request or real mail operation was performed.


### Final flow, deletion and research update (2026-10-07)

The top-left name is Complete Outreach Tool. Home separates audiences (goal, plan, company/contact research) from campaigns (reviewed recipients, message, drafts and sending). Each audience shows its own name/reference and a saved-state next step: finish details, approve a ready plan, watch progress, continue paused checks, review contacts or inspect an uncertain request. Paid continuation never automatically replays an uncertain outcome.

Delete audience now also supports researched work after explicit confirmation: it moves to Deleted audiences while costs, evidence, existing campaign contacts and research links remain intact. Restore starts no research. Eligible unused drafts remain permanently deletable; active jobs must stop first. No real audience was deleted during this update. Before changes, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261007-032006.

Flexible search is offered for new/revised audiences. It accepts explicitly published general business inbox fallbacks, inspects up to ten discovery sources and prioritizes official contact pages. Evidence from official-site search results is retained when extraction omits an address. Explicit [at]/(dot) spellings can be decoded with the original quote retained. Unknown company-fit facts stay available for human review. Addresses and website identities are never guessed, and suppression remains enforced. Earlier approved runs keep their original request inputs; choose Edit audience and save a revised flexible draft to change the approved scope.

The normal owner app remains running at http://127.0.0.1:8000. Close its terminal and reopen START-OUTREACH.cmd once to load the new backend; keep the new terminal open. The app shows this update requirement. Earlier loaded processes retain their continuation fallback. No paid research or mail operation was performed.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Load the 2026-10-07 audience/research update

The normal owner app may still have earlier Python code loaded. Close its terminal and reopen START-OUTREACH.cmd, then refresh http://127.0.0.1:8000. Keep the window open. RESTART-OUTREACH.cmd only hands off a restricted preview; it does not terminate a normal desktop app.

Research flow: save audience → Prepare plan for free → review and approve paid research → review/approve published contacts → Use this audience → choose/create campaign → Message/attachments. Editing researched inputs saves a version inside the same audience. The history panel shows where previous runs stopped. Increase a paused run's total cap in Continue research / change target and budget, confirm the increase, save, then Continue research. An uncertain request must be resolved by checking provider usage; setup never automatically replays it.

## Strategy 4 local update (2026-10-08)
New audiences and edited versions use the wider-web evidence collector. Existing runs retain their original strategy and paid-request identities. If the app says restricted review mode, double-click RESTART-OUTREACH.cmd in this folder from the normal desktop session; it gracefully hands off the preview before opening the normal app. Merely opening START-OUTREACH.cmd while a preview occupies port 8000 will reopen that existing preview. No research starts automatically. Use a small known-company audience and a free plan first; explicitly approve any paid pilot yourself.
