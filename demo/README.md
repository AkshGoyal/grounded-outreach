# Interactive mobile workflow demo

`mobile-preview.html` is a self-contained, responsive browser demo of the outreach
workflow. It is separate from the Python application and uses fictional companies,
mailboxes, evidence, drafts and replies. It performs no AI requests, research,
provider authentication, inbox access or email delivery. Do not enter credentials.

Try brief → editable plan → approval → select/remove leads → approve selection →
save a list → create or reuse a campaign → select a sample sender → edit/approve
drafts → review and simulate sending → simulate handling a reply. Home, Research,
Lists, Campaigns, Inbox and Accounts remain available in the bottom navigation.
Editing a draft or campaign settings resets unsent approval. Sent sample records
remain visible when revisiting a campaign. Browser storage retains demo changes
when supported; Accounts includes a reset action. Changes never reach the real app.

Open the HTML file in a browser that permits local HTML and JavaScript, or serve
this directory on a normal HTTP/HTTPS host. Phone document viewers may show a static
preview and disable scripts; iPhone Files previews are not a verified interactive
launch path. A directly tappable browser experience needs a hosted HTTPS URL.
The Codex workspace's localhost address is not accessible from the phone.

## Open on an iPhone through Render

The root `render.yaml` deploys only this sample-data directory as a static site.
It does not deploy Python, upload the database or mailbox credentials, or configure
API keys. Static sites are advertised as free by Render; review the service's
current plan/usage terms when creating the account. Automatic deploys are disabled.

On the phone, open
[Deploy the demo](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FAkshGoyal%2FOutreach-Agent%2Ftree%2Fcodex%2Fresearch-pilot-v1),
sign in to Render, connect GitHub with access to the private Outreach-Agent
repository, and review/apply the blueprint. It should show one **Static Site**
named `outreach-mobile-demo`, not a paid Python web service. When deployment succeeds,
open the site's actual `onrender.com` URL in Safari. The URL is supplied by Render;
it cannot be known or verified before the operator connects their hosting account.
If the deploy button cannot locate the private repository, use Render's **New →
Blueprint**, select Outreach-Agent, and select branch `codex/research-pilot-v1`.

The demo URL is publicly accessible; it contains only fictional sample fixtures.
The GitHub repository remains private. Do not use this static deployment for real
campaigns. Changes made inside the demo stay in the phone browser's local storage.

The demo was checked in Chromium with a 390×844 mobile viewport and touch mode,
including the full workflow, navigation, persistence, approval resets and no
external network requests. Local file navigation is blocked by the managed
Chromium policy, so QA used a loopback HTTP server. Native iOS/Android file handling
has not been tested.

The Sites publishing helper is not installed in this Cloud executor. No Site was
created or published, and there is no hosted demo link yet. The existing GitHub
repository is private; it was not made public to serve this demo.
