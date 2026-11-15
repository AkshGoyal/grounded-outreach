# Publish the real outreach app from your phone

The production build and persistent startup are prepared and tested in Cloud.
The app is **not published**: there is no hosting account/API access connected,
no live OAuth clients/consent, and no selected real test inbox. The root
`render.yaml` still describes the sample demo. Use `deployment/render.yaml` for
the real Python app; it is a proposed paid service and disk, not deployed resources.

## First: connect hosting

1. In Safari open [Render dashboard](https://dashboard.render.com/), sign in/create
   your account, and connect GitHub. Grant access to the existing Outreach-Agent
   repository without changing its visibility.
2. Create a **Blueprint** from that repository on `codex/research-pilot-v1`.
   Set the Blueprint path to `deployment/render.yaml` (not the root demo file).
   Review the Starter service and 1 GB persistent disk charges before creating
   resources. Render hosting charges are separate from the $1 research pilot.
3. Once deployed, Render provides an HTTPS service URL. In the service Environment
   settings, view the generated `OUTREACH_APP_PASSWORD` and use it to sign into the
   app. Do not paste passwords or client secrets into chat. Bookmark the URL on
   your iPhone, or use Safari Share → Add to Home Screen.
4. Add the actual Parallel/OpenRouter keys to the hosting environment if research
   and drafting are needed. Codex Cloud credentials do not automatically transfer
   to Render; a proxy-injected placeholder is not a portable provider credential.
   Add Google/Zoho client settings after registering those apps below. Restart the
   service after environment changes. Use each key's provider/host secret settings.

Render's web-service URL is read from `RENDER_EXTERNAL_URL`; startup automatically
sets the app's OAuth origin/allowed hostname. For a custom domain, explicitly set
`OUTREACH_OAUTH_PUBLIC_URL` to its HTTPS origin before registering callback URLs.
The Blueprint does not start inbox polling, research, drafting or campaign sends.
Research defaults are $1 per run and day admission limits, with explicit paid-action
approval. These defaults do not reset/extend the original pilot ledger or grant
permission to rerun exhausted pilot requests.

## Configure the HTTPS proxy correctly

The backend trusts only loopback proxy headers by default. If the hosting edge
connects from another address, configure `FORWARDED_ALLOW_IPS` with its specific
verified addresses or documented private proxy network. Do not trust arbitrary
forwarded headers. Only the hosting edge should reach the app backend.

Open Email accounts → provider sign-in → Administrator setup. If the backend isn't
recognizing HTTPS, it shows the observed peer. Confirm that address is the hosting
proxy through host documentation/support before adding it to the trust list. The
callback requires HTTPS and the canonical hostname; workspace cookies remain
Secure when an HTTPS app origin is configured. This setting needs verification on
the actual host; it cannot be inferred reliably from the Codex executor.

A proposed wildcard proxy setting was rejected by automatic approval review as
unsafe. The supplied configuration retains restricted trust; no wildcard was applied.

## Register and connect email

Follow [OAUTH_SETUP.md](OAUTH_SETUP.md) in the provider consoles. Register these
URLs using the actual app hostname:

- Google: `https://YOUR-APP/accounts/oauth/gmail/callback`
- Zoho: `https://YOUR-APP/accounts/oauth/zoho/callback`

Store client credentials in the host environment, then Continue with Google/Zoho
inside the app and approve consent on the provider's page. Only the account owner
can grant consent; the research API keys cannot grant mailbox permission. OAuth
connects a sending account; the workspace password is separate.

## Run real mail tests

Email accounts → Verify again → Send a test to yourself. Choose an inbox you own
and explicitly confirm one [TEST] message. The page retains recent accepted,
failed, pending and uncertain outcomes across restarts. Check the destination,
spam and sender authentication. For uncertainty, inspect Sent before another test.

Reply TEST REPLY and inspect the sending provider inbox. A test message is not a
campaign, so it doesn't create a campaign reply. A full campaign round-trip requires
an approved small campaign to controlled addresses, reviewed drafts and explicit
launch. No such test has run in Cloud. Inbox filters now use campaign/account names;
Check for replies can target the selected account, keeping the current filters.

Disconnect from tool clears stored OAuth tokens, removes verified status and
returns unsent approvals to review while retaining campaign history. Previously
constructed adapters check the stored connection before future HTTP requests.
Revoke provider consent separately in Google/Zoho connected-app settings. Refused
or expired API permissions clear verified status and display reconnection guidance.

## Persistent state and limits

The locked production build uses `uv sync --locked --no-dev --python 3.12`.
`outreach.hosted` changes the working directory to `/var/data/outreach`, keeps
SQLite and campaign files there, and stores the encryption key beside SQLite.
It requires an HTTPS origin, a workspace password of at least 16 characters and
an absolute database path inside the persistent directory. It runs one process
with access logging/inbox polling off. Back up the whole directory off-host.

The disk must remain attached. App restarts preserve data, but interrupt in-memory
workers. Campaign history/pending sends survive; workers do not automatically
repeat deliveries or silently resume paid research. Sending progress names the
campaign/account and points to its replies. Durable queues, multi-user operation,
provider policy approval and actual iPhone Safari/delivery verification remain
separate from the successful Cloud smoke tests.

Cloud verification: 430 offline tests, lint/format, locked production install and
live local startup/login/save paths pass. Desktop/390px Chromium checks pass with
fictional records/fake mailboxes, no browser errors, overflow or external requests.
Local ignored artifacts: `data/hosted-smoke-report.json`, `data/activation-preview/`.
No public deployment, real mail or new paid research/model call was made.
