Current desktop validation and live prerequisites: [CAMPAIGN_READINESS.md](CAMPAIGN_READINESS.md).
Laptop instructions: [LAPTOP_SETUP.md](LAPTOP_SETUP.md). Phone testing is postponed.

# Research and campaign workspace

Implemented on `codex/research-pilot-v1`, 2026-10-04. The existing FastAPI app now
connects research, lead approval, reusable lists, campaign-specific sending accounts,
draft review, paced sending and reply management. No real campaign emails were sent
while implementing or testing this increment.

## Run it in Cloud

### Mobile workflow demo

For an interactive sample-data walkthrough, use `demo/mobile-preview.html`.
It includes editable planning, lead selection, campaign assignment, draft approval
and simulated sending/replies. It is a separate browser demo, not the Python
backend. It makes no paid API calls or real deliveries. Phone file viewers may
disable JavaScript; a hosted HTTPS URL is needed for reliable direct phone access.
See [demo limitations and verification](../demo/README.md). This Cloud session has
no phone-facing preview URL, and its Sites publishing helper is not installed.
No hosted demo was published and no repository access policy was changed.
For iPhone Safari, the root `render.yaml` prepares a sample-only static deployment;
the operator must connect their Render/GitHub account and apply the blueprint.
That deployment would provide a public sample-demo URL, not a running Python app.

### Open the current app in GitHub Codespaces

Select `codex/research-pilot-v1` on the GitHub repository, then use **Code →
Codespaces → Create codespace**. After setup completes, run
`bash .devcontainer/preview.sh` in its terminal. The launcher asks for a workspace
login password, allows the Codespace's exact forwarded hostname, and starts port
8000 with automatic inbox polling disabled. In **Ports**, keep port 8000 **Private**
and choose **Open in Browser**. The app blocks embedding in an editor preview pane.
Leave the terminal running; Ctrl-C stops it. Browsing alone makes no paid API calls.
Explicit research, drafting, inbox checks and sends retain their normal behavior.

The launcher works on loopback outside Codespaces. It uses the configured database
and campaign files, not the fictional demonstration data shown in Cloud screenshots.
Back up an existing workspace before launching an updated version. New Codespaces
start with an empty workspace; do not commit the private database or mailbox key.

Codex Cloud and GitHub Codespaces are separate environments. To run real research
there, grant this repository the Codespaces secrets `OUTREACH_PARALLEL_API_KEY` and
`OUTREACH_OPENROUTER_API_KEY`, then stop and restart the Codespace. The preview
screens work without them. GitHub may charge for Codespaces usage separately from
the API pilot budget. A Codespace is a development preview; stopped Codespaces do
not send campaigns or poll inboxes. Use a permanent host for ongoing campaigns.

### Permanent Cloud application host

Install with `uv sync --locked --extra dev`. Configure the existing Cloud environment
variables `OUTREACH_PARALLEL_API_KEY` and `OUTREACH_OPENROUTER_API_KEY`. The Setup
screen reports whether keys are configured without displaying them.

Start the browser app with `uv run outreach serve --no-browser`. This binds to
loopback by default. For access through your Cloud host, set a strong
`OUTREACH_APP_PASSWORD` and `OUTREACH_ALLOWED_HOSTS` to a comma-separated list of
actual hostnames, place the app behind HTTPS, and run:

```sh
uv run outreach serve --host 0.0.0.0 --port 8000 --no-browser
```

Use one server process and one worker. Sending and drafting jobs run in that
process; do not run a second worker or a concurrent CLI sender against the same
database. The server must remain running for background work. After a restart,
research results and budget reservations remain saved; a stopped job is surfaced
for explicit recovery. Sending never automatically restarts. Campaign pause is a
setting; stopping an active send uses its Stop button.

Persist the database directory **and** the `campaigns/` directory across host
restarts. Keep the mailbox encryption key with your private recovery material.
Existing campaigns and contacts are preserved; the new database tables are additive.
Back up an existing database before first starting the updated app.

### This Codex Cloud execution environment

The checked runtime has HTTPS access and ready Parallel/OpenRouter variables.
Its TCP configuration has no domain/IP grants, no VPN, and no general public
Internet route. The supported raw TCP forwarding path is for granted private
VPN endpoints, not public Gmail/Zoho servers. SMTP/IMAP cannot be demonstrated
against real providers in this executor. Do not bypass the sidecar or turn off TLS.

The browser and research workflow run here. Live mail needs a Cloud application
host that supports outbound SMTP on 465 (or 587) and IMAP on 993. Adding an HTTP
allowlist entry for Gmail/Zoho does not enable these protocols. The implemented alternative
is provider OAuth and HTTPS mail APIs; those require separately registered provider
applications and the real app URL. OAuth sign-in and HTTPS mail are now implemented
(see OAUTH_SETUP.md); live consent is not completed. App-password accounts still use
SMTP/IMAP. OAuth accounts use the HTTPS adapters.

## Use the workflow

1. **Email accounts (optional until launch):** connect Gmail or Zoho. Give each account a label, sender
   name, company/organization and postal address. Gmail requires 2-Step Verification
   and an app password; some organization policies disable app passwords. Zoho
   requires a plan with SMTP/IMAP access, IMAP enabled, the correct server region,
   and an application-specific password when MFA is enabled. Both sending login
   and inbox login must verify before launch; draft campaigns can select an
   unverified account or leave the sender blank.
   Verification logs in and out; it sends no mail and reads no messages. Passwords
   are encrypted in SQLite and are never displayed back in the account form.
2. **Research:** describe audience, geography and purpose; optionally choose a
   project and tags. Choose 1–25 companies and a run budget. Creating a plan uses
   an OpenRouter request within that cap. Edit the summary, required criteria,
   exclusions and search queries, or add a conversational clarification. Searches
   start only when you explicitly approve the plan and remaining budget.
3. **Review leads:** open each company's evidence and published email. Addresses
   come from deterministic extraction of retrieved company pages; a matching
   source quote alone does not prove ownership or fit. Approve individually or
   select several, confirm identity/contact ownership/fit, and remove unsuitable
   results. An unknown or contradicted criterion needs your written review note.
   Missing email and global suppression block approval for email outreach.
4. **Lead lists:** save an approved selection to a named reusable list, or add
   selected leads directly to an existing campaign. Same-campaign duplicates are
   skipped. Prior company/address membership is shown; reuse in another campaign
   requires an explicit acknowledgement. Suppression is checked again at enrollment.
5. **Campaigns:** create a campaign with a name, purpose, approved audience and
   message brief. Project/tags and sender connection are optional while saving.
   Complete the message before drafting; choose and verify a sender before launch.
   Each campaign keeps its own sending identity. Once a send record exists, changing identity requires a
   different campaign so reply routing remains stable. You can revisit campaigns,
   add approved leads, pause, reopen, complete or archive them.
6. **Drafts:** write the next batch or all remaining emails. A progress screen
   saves each completed draft and supports Stop. Rewrite unsent emails when the
   offer changes; previous unsent drafts become rejected, and the replacements
   wait for review. Filter the queue, review individually with previous/next, or
   confirm approval of selected drafts that pass every check.
   Editing copy, closing, sending identity or an approved draft requires fresh
   approval. Updating an account also resets its unsent approvals.
7. **Send:** inspect the full email and sender on the send preview, then explicitly
   confirm sending. The app sends approved emails automatically at the configured
   pace, within the global daily cap, with an opt-out. Stop works between emails.
   Approval and text are checked again just before sending. Suppressed contacts
   and already-sent/pending recipients stay blocked. A connection interrupted
   during SMTP delivery remains pending: reconcile it with the Sent folder before
   considering any retry.
8. **Inbox:** check all verified accounts, or use automatic polling while the
   server runs. Matching is scoped to the receiving account. The campaign dashboard
   links to its filtered inbox; category filters help triage. Suggested answers
   require your explicit send, which uses the receiving account. Opt-outs and
   bounces update the global do-not-contact list. IMAP leaves messages unread and
   does not move or delete them.

The persistent sidebar keeps Research, Lead lists, Campaigns and Inbox available.
Projects, purpose, tags, search and status organize separate sales and job-search
work. Filters stay in the URL; browser back restores the review position. Archived
campaigns disappear from the default campaign view, but remain in history.

Voice input is optional browser speech recognition. Browser/service support and
microphone permission determine availability; transcription may use the browser's
external speech service. Text entry always works. No server voice API is configured.

## Spending and recovery

Production research has a per-run budget and a daily aggregate research cap.
`OUTREACH_RESEARCH_MAX_BUDGET_USD` and `OUTREACH_RESEARCH_DAILY_BUDGET_USD` default to
$5 each; the browser's initial run budget is $0.50. Two discovery rounds and up to
four same-site pages per company bound a run. Research may finish with fewer
companies than requested, or stop at the cap with partial results available.
Drafting and inbox-classification model calls use the existing model configuration;
**they are separate from the research cap**. Browser controls state when an AI
request will be made. SMTP/IMAP authentication does not use either research API.

Paid research requests reserve microdollar amounts in SQLite before network I/O.
Successful responses are cached with their original retrieval time. OpenRouter
reported cost is used when available; Parallel uses a tariff estimate. Missing
usage retains the conservative reservation. Timeouts, HTTP errors and interrupted
requests retain their reservation and block replay. Resume reuses completed calls;
it cannot retry uncertain ones. Costs above reservation stop all further paid
research until reconciled. The request-spending panel exposes the accounting basis.
These are admission controls, not a guarantee of the provider's eventual invoice.

The comparison pilot remains in `data/research-pilot-v1/` with its original $1
ceiling and **$0.407160 accounted spend**. Production does not import or modify that
ledger. Its 15 candidates remain pending in the pilot artifacts; no pilot result
was silently enrolled or sent. See [pilot results](RESEARCH_PILOT_RESULTS.md).

The Back up workspace button now creates a verified, downloadable archive of
SQLite, campaign text and the mailbox encryption key. Keep it private and outside
the running workspace. Provider API keys and OAuth client secrets are excluded.
The CLI backup remains database-only. See LAPTOP_SETUP.md for restoration. Never
commit or share the key or workspace archive. Losing it does not expose
passwords, but encrypted accounts must be reconnected. Account pages remain readable;
actual sending is blocked when credentials cannot be decrypted.

## Verification and next improvements

Offline tests use fake mailboxes and a mocked HTTP transport through the actual
production reservation/evidence pipeline. They cover approval gates, literal
source checks, retained uncertain spending, restart recovery, encryption, account
verification, enrollment, suppression, draft rewrites, account-scoped send/reply
routing, changed approvals, TLS verification, sign-in and cross-origin writes.
Chromium checks cover the brief → editable plan → approval → lead evidence flow,
workspace pages, desktop/mobile layout and JavaScript errors. Browser screenshots
are in ignored `data/platform-preview/`. No additional paid research calls were
made during the integration.

Recommended next increments: activate OAuth/HTTPS mail after host/provider setup; sender delivery/bounce reporting and a mailbox reconciliation screen;
operator-reviewed follow-up sequences; email deliverability checks; durable queued
workers before multi-user operation. Automatic follow-ups, automatic reply sending,
hosted deployment and deliverability verification remain incomplete. OAuth code
is now implemented but needs provider registration and live activation; see below.

## Founder test and proposed frontend refinement

The Cloud founder benchmark appended to the original pilot ledger, bringing
combined accounting from $0.407160 to $0.491129. It produced three company
candidates, zero verified direct founder emails and two general inboxes. Private
source-reviewed facts and draft hooks are in
`data/research-pilot-v1/founders-bangalore-v1/founder-review.md`; none are approved
for sending. See [quality findings](FOUNDER_RESEARCH_RESULTS.md) and the
[proposed frontend plan](FRONTEND_PRODUCT_PLAN.md). Campaign clarification belongs
in the app's intake/edit flow; the saved intake and campaign/message/draft refinements below are now implemented.

The broader job-outreach review now has two published HR/recruiting department
contacts in `data/research-pilot-v1/founders-bangalore-v1/job-outreach-review.csv`.
Inspect `broadened-contact-review.md` first: one displayed HR address has a support
mailto link mismatch. Both CSV rows pass format/import preview only. Keep source
review, lead approval, draft approval and launch separate; these files have not
been imported into a production campaign or used to send mail. This additional
manual public-site review used no paid provider calls.

## New guided audience flow

Home → enter a goal/purpose → Continue to audience details saves a free research
draft. Or open Research → New audience. Enter company type, location (or Anywhere),
and all acceptable contact roles; select HR for a published recruiting department
inbox. Set the count and cap, optionally add requirements, exclusions and desired
personalisation. Save draft anytime. No email account is required here.

To plan, complete the audience fields, check the paid-planning authorisation and
choose Create plan for review. Provider settings are required for that action.
Review the summary/criteria/exclusions, optionally open Advanced search controls,
then explicitly approve research. Preferences feed both planning and company
contact-search inputs, but the operator still verifies contact role and ownership.

Filter discovered companies by review stage, inspect source evidence and approve
a selection. Then open Save or use approved contacts to save a list or enroll in
an existing campaign, or choose Create campaign from the approved selection.
Campaign creation saves without a connected sending account; verification is
required at launch.

SQLite drafts survive restarts; unsubmitted changes are optionally kept in the
current browser tab. Paid authorisation is never restored. Started audiences remain
immutable; use a new brief to change scope. Mobile has Home/Research/Leads/Campaigns/
Inbox bottom tabs and a Manage menu. Static phone demo and deployment status are
unchanged. Screenshots from fictional-data browser QA are ignored under
`data/intake-preview/`. No additional live research or mail was run for this work.

## Campaign preparation and review

From approved leads choose Create campaign, or open a saved list and choose a new
campaign. Fill the name and purpose, confirm the audience, and enter the Message
fields. A partial brief is a free saved draft. Supply your actual introduction and
background, the topic and desired reply; the tool does not invent skills or vacancies.
Sender connection can wait. Save opens the campaign's readiness overview.

Use Audience to inspect sources or add another approved list. Suppressed contacts
stay blocked; previous outreach requires acknowledgement. Use Message to complete
or revise your brief and optional fixed ending. Drafts shows paid AI actions separately
from research spending. Write remaining emails, filter the queue and open Review.
Previous/next moves through current drafts. Check each full email and recipient
facts, then approve individually or select reviewed drafts and confirm the selection.
Automatic checks still hold unsupported and ambiguous claims.

Launch shows the chosen sender, limits, held recipients and every outgoing email
including its ending/footer. It stays blocked without a verified account or complete
message. Editing the message or sender requires fresh approval of unsent drafts;
sent history remains. Campaigns with mail history cannot switch sender accounts.
The advanced raw-copy editor remains supported and clears the structured brief
when saved. Legacy CLI campaigns retain their existing configuration behavior.

The campaign increment passed 388 offline tests and desktop/390px Chromium workflow
checks using fictional data and a fake model. Screenshots are local ignored files in
`data/campaign-preview/`. No paid calls or mail were made, and pilot accounting
remains $0.491129. These checks provide neither a public URL nor an actual iPhone
Safari test. OAuth host/provider activation and inbox/send-progress refinement
remain work before claiming the complete hosted product is ready.

## OAuth and real-mail test increment

Email accounts now offers Google/Zoho sign-in and a separate confirmed test-to-self
page. Campaign sending and reply handling use HTTPS for OAuth accounts, while existing
app-password accounts retain SMTP/IMAP. The workspace login remains independent.
Token storage is encrypted; Google uses PKCE; both callbacks require single-use,
expiring, browser-bound state. No provider password is requested by OAuth.

[OAuth setup and real test steps](OAUTH_SETUP.md) explain the HTTPS address, provider
registration, environment names, permission scopes, provider constraints and recovery.
No client credentials/public callback URL/workspace password are currently configured
in this Cloud environment; TCP policy permits no SMTP/IMAP hosts. Therefore no live
provider consent, login, inbox reading or real delivery was completed. The test inbox
also needs explicit user selection. Connecting an account only checks identity/list
access; a confirmed test is needed for actual send/delivery evidence.

Offline HTTP fakes test the real adapters and campaign/account routing; Chromium checks
cover account/setup/test screens at desktop and 390px without external requests,
overflow or browser errors. Screenshots stay ignored in `data/oauth-preview/`.
No research/model requests, real mail or deployment were made; pilot spending is unchanged.

Latest verification: 413 offline tests, lint/format and desktop/390px browser checks
passed. Live mail remains untested; see OAUTH_SETUP.md for prerequisites.

## Hosted startup and activation

[HOSTED_APP.md](HOSTED_APP.md) gives the phone-accessible deployment steps for the
real backend. A separate `deployment/render.yaml` prepares a paid service/persistent
disk, secure generated workspace password and locked production build; the sample
root blueprint is preserved. No host is connected/deployed. Startup derives the
callback origin/allowed hostname, places database/campaign text/key on the private
volume, and rejects missing protection or an ephemeral database path. Proxy trust
remains restricted and needs the actual host's specific configuration.

Email account recovery now includes local OAuth disconnect, cleared verification
on permission refusal and saved test outcomes. Disconnect preserves sent/account
history and requires future draft review; revoke provider consent separately.
Inbox uses readable campaign/account selectors, retains filters and supports a
selected-account check. Sending progress identifies the campaign/sender, keeps
mobile cards and explains server restart/uncertain-delivery recovery.

430 offline tests, a locked production install/local hosted startup and desktop/390px
fictional-provider browser checks pass. Research pilot accounting is unchanged;
no real mail or public deployment occurred. Host connection, provider registration,
owner consent and a controlled test recipient still need external setup.


## Desktop acceptance and current pilot accounting — 2026-10-05

Phone testing is postponed. Returning Home prioritizes existing work; launch uses
an expiring review bound to exact emails/sender, campaign History survives restart,
reply answers cannot repeat after acceptance/uncertainty, and browser backup exports
the full private workspace. See LAPTOP_SETUP.md and CAMPAIGN_READINESS.md.

The historical $0.407160/$0.491129 figures above describe earlier runs. After the
bounded production test the original $1 ledger accounts **$0.514115**, including
$0.022986 for eight new paid calls. This returned one general-only contact, not a
verified requested-role lead. All real results remain pending and no mail was sent.
