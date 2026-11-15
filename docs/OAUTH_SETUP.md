# Gmail and Zoho OAuth setup and real mail testing

The application implements provider sign-in and HTTPS sending/inbox adapters.
Live consent and delivery have **not** been completed. In Cloud on 2026-10-04,
client IDs/secrets, an OAuth public URL and a workspace password were absent.
Existing SMTP settings are configured, but Cloud's TCP policy grants no mail
hosts; IMAP is also not configured. No SMTP login, inbox reading, real send or
provider consent is claimed. No research/model calls are needed for these tests.

## What sign-in does

The tool has its own workspace password. Google/Zoho sign-in connects an email
account to that workspace. It is not a replacement for workspace login.

You choose Connect with Google or Zoho, enter the sender details, and continue to
the provider's page. You sign in there and approve sending/inbox permissions.
The provider redirects back to this app; the server exchanges the temporary code
for encrypted access/refresh tokens and confirms the provider's mailbox address.
The app checks inbox-list access without reading bodies or sending a message.
A connected account becomes available to campaigns. A later explicit test delivery
establishes whether sending works; connected status does not prove deliverability.

Permissions: Google `gmail.send` and `gmail.readonly`; Zoho `accounts.READ`,
`messages.READ`, `messages.CREATE`. No delete or mark-read scopes are requested.
Inbox checking reads messages to find campaign replies, just as the existing IMAP
adapter does; unmatched personal mail is not persisted or passed to a model.
Do not enable automatic polling until you want inbox checking. Provider API fees,
quota and plan limits are separate from the research pilot budget.

## 1. Give the real app an HTTPS address

Use the prepared [real-app hosting setup](HOSTED_APP.md), or choose a host capable
of running the existing Python/FastAPI app and preserving
SQLite, `campaigns/`, and the encryption key. The static phone demo cannot run
this OAuth flow. No host was selected or deployed during this increment.

Set in the host environment:

- `OUTREACH_OAUTH_PUBLIC_URL=https://YOUR-APP` (origin only, no path).
- `OUTREACH_ALLOWED_HOSTS=YOUR-APP` (hostname, no scheme; keep any needed local hosts).
- `OUTREACH_APP_PASSWORD` (a strong workspace password).
- A stable `OUTREACH_CREDENTIAL_KEY`, or retain the generated private
  `mail-credentials.key` beside the persistent database.

Run one app process. Start with automatic inbox polling off:
`uv run uvicorn outreach.web.app:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log`.
Configure the host's HTTPS reverse proxy. Avoid access logs containing callback
query strings, because OAuth codes travel in them. The CLI/preview launchers now
disable access logging. Trust forwarded headers only from the host's actual proxy.

## 2. Register Google

1. Open [Google Cloud Console](https://console.cloud.google.com/), create/select
   your project, and enable the **Gmail API**.
2. In Google Auth Platform, configure branding and audience. For personal testing,
   keep Testing and add the exact Gmail/Workspace accounts as test users. Choose
   Internal only if your Workspace organization allows it.
3. Add scopes `https://www.googleapis.com/auth/gmail.send` and
   `https://www.googleapis.com/auth/gmail.readonly` in Data Access.
4. Create an OAuth client with application type **Web application**. Register
   this exact authorized redirect URI:
   `https://YOUR-APP/accounts/oauth/gmail/callback`.
5. Store the client ID and secret as `OUTREACH_GOOGLE_CLIENT_ID` and
   `OUTREACH_GOOGLE_CLIENT_SECRET` in the host environment; restart the app.
6. On the real app, open Email accounts → Connect with Google or Zoho sign-in,
   fill sender details and Continue with Google. Approve both permissions.

Google can expire refresh tokens for an external Testing app after seven days.
Reconnect when required. `gmail.readonly` is a restricted scope: broader public
use can require Google's verification and, depending on data use, a security
assessment. This implementation does not certify approval by Google.
See [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
and [OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server).

## 3. Register Zoho

1. Open [Zoho API Console](https://api-console.zoho.com/) for your account's data
   center (for India, `https://api-console.zoho.in/`). Create a **Server-based
   application** with homepage `https://YOUR-APP`.
2. Register `https://YOUR-APP/accounts/oauth/zoho/callback` as its redirect URI.
3. Store `OUTREACH_ZOHO_CLIENT_ID` and `OUTREACH_ZOHO_CLIENT_SECRET` in the host
   environment and restart. Select the matching region when connecting.
4. Continue with Zoho and consent to `ZohoMail.accounts.READ`,
   `ZohoMail.messages.READ`, and `ZohoMail.messages.CREATE`.

Regions supported: com, in, eu, com.au, jp, ca. URLs are constructed from those
fixed choices, never from a callback-supplied server URL. One enabled primary
Zoho mailbox per consent is supported; multiple primary mailboxes need a future
account-selection screen. A Zoho plan or organization policy can restrict API
access. Sender display name in Zoho's API delivery follows provider account
settings; the app-supplied name is still included in the email footer.
See [Zoho OAuth](https://www.zoho.com/mail/help/api/using-oauth-2.html),
[send](https://www.zoho.com/mail/help/api/post-send-an-email.html),
[reply](https://www.zoho.com/mail/help/api/post-reply-to-an-email.html) and
[original MIME](https://www.zoho.com/mail/help/api/get-original-message.html).

## 4. Run the first real test

Use Email accounts → Verify again, then **Send a test to yourself**. Enter an
address you control and confirm one test delivery. The app marks the subject
`[TEST]`, blocks campaign contacts/suppressed addresses, and records the outcome
before allowing a replay of the same form. No AI is involved and no campaign is
launched. Provider acceptance is displayed separately from inbox delivery.

Check the destination inbox/spam and the exact sender. In Gmail Show original,
check SPF, DKIM and DMARC; Zoho exposes source headers too. Reply `TEST REPLY`,
then confirm receipt in the sending provider's normal inbox. Test messages are
not campaign records, so this reply intentionally does not appear in the campaign
inbox. Testing campaign matching requires a separately approved tiny campaign to
controlled addresses, reviewed drafts and an explicit launch; do not use prospects
as connectivity probes. No such campaign was launched in this increment.

Uncertain test/delivery: inspect Sent and destination before retrying. Campaign
sends retain pending records. The app never automatically repeats an uncertain
HTTPS POST. Zoho provider IDs and internet Message-IDs are mapped within the
account for campaign reply/thread routing. Missing receipt storage after a successful
send is uncertain, not a reason to send again.

## Recovery and privacy

Reconnecting the same provider-confirmed email retains its account ID/history and
returns unsent approved drafts to review. A different email creates another
account. Sent campaign history retains its original account. Revoke consent in
Google account Third-party apps or Zoho Connected Apps; subsequent access failures
require reconnection. Tokens never appear in rendered account metadata or URLs.

Restore the database, campaign files and encryption key together. Losing the key
requires reconnection. Start a new sign-in after denial, expiry, restart during
consent or browser-cookie loss. Sign-ins expire in ten minutes, are single-use
and tied to a Secure HttpOnly browser cookie; Google also uses PKCE.

Offline HTTP fakes validate protocol/security behavior; they do not establish
provider approval, Zoho plan compatibility, actual mail delivery or Safari access.

## Prepared hosting and recovery controls

`deployment/render.yaml` prepares the real backend; the root render.yaml remains a
sample-only demo. `outreach.hosted` derives the HTTPS origin from Render, preserves
all private state on the persistent volume and keeps proxy trust restricted. Review
paid hosting charges and complete host access/proxy verification before publishing.
See HOSTED_APP.md for phone steps. No deployment is claimed.

The test page now shows saved outcomes after restart. Disconnect from tool destroys
local reusable tokens while retaining account/campaign history; revoked/refused API
permissions clear verified status. Inbox filters use readable campaign/account names
and can check one selected account. Automatic approval review rejected wildcard proxy
trust; the supplied configuration preserves restricted trust instead.
