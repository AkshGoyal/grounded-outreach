# Use Outreach on this laptop

Open **http://127.0.0.1:8000**. Work is saved on this laptop.

## Finish the local connections

1. In **Desktop → Aksh → Outreach-Agent-Local**, double-click **RESTART-OUTREACH.cmd**.
   It signs in privately, asks the restricted preview to stop gracefully, then starts
   the app as your normal Windows account. Keep its window open. It refuses active
   research, drafting or sending and makes no paid request.
2. Open **Settings & connections**. Parallel and OpenRouter already have keys.
   “Key saved” means configured, not authenticated. Blank key fields keep existing
   values; new keys are encrypted and .env is never rewritten. Only you can create
   provider keys and add credits.
3. Open **Review email connections**, then **Verify again** for the reused account.
   Verification checks sending and inbox login and sends no email. The earlier app
   had no inbox host; a matching provider/region host was filled in. Confirm it against
   your mailbox's server settings.
4. If refused, choose **Edit account**. Leave password blank to keep the reused login,
   or enter a replacement app password yourself if revoked. Provider security settings,
   MFA and consent require your account-owner access.

[Gmail app passwords](https://support.google.com/accounts/answer/185833):
enable 2-Step Verification, then generate an App Password. Some organizational or
protected accounts do not offer this option; use administrator-approved access or
this app's separate HTTPS OAuth setup.

[Zoho IMAP](https://www.zoho.com/mail/help/imap-access.html):
enable IMAP and confirm the region and organization server type.
[Zoho app passwords](https://help.zoho.com/portal/en/kb/accounts/manage-your-zoho-account/articles/mfa-application-specific-passwords):
with MFA, generate an application-specific password in Zoho Account → Security.
Your plan and administrator policy must allow the chosen access.

The old **outreach-agent** folder remains intact, including 10 sent-history records,
contacts and drafts. Those campaigns were not imported or relaunched.

## Save an audience for free

1. On Home, enter your goal and choose its purpose.
2. Continue and enter company type, location and acceptable contact roles.
3. Choose **Next: review & save**, then **Save audience**.

Saving makes no provider request and sends no email. Requirements and future limits
are optional. Back keeps your entries. Unsaved edits survive refresh of the same
saved version; validation errors retain submitted values. Paid consent is never
restored from browser storage.

## When you choose to start paid work

Your saved audience has a separate **Create plan for review** action. Choose a small
research cap and explicitly approve one AI planning request. Review its plan, then
independently approve company research. Review evidence and published email ownership
before approving contacts. Save a list or create a campaign.

Campaign creation needs a name and optional contact list. Its dashboard points to the
next step: audience, message, draft review, sender or launch. Connect email later.
Review every draft and the launch before sending.

Research, drafting and reply classification can incur separate provider charges.
No live research or real emails were run during setup.

## Recover your connection error

Your goal was saved; provider access failed during planning. The reservation is retained
and may differ from the provider invoice. The failed request is not automatically
replayed. Inspect provider usage before approving another paid attempt.

**Save a copy of this audience (free)** prepares a fresh draft without discarding the
original attempt or reservation. Copying starts no research.

## Private files

Do not share .env, data/outreach.db, mail-credentials.key or backups.
Browser-entered research keys live in data/provider-credentials.enc. Keep that
encrypted file and its original encryption key together; downloadable backups
exclude research keys. Restore both together if saved keys cannot be unlocked.

Before UI changes, source/tests/docs and an online SQLite snapshot were saved under
data/recovery/ui-20261006-140351. Existing .env files were preserved.
Local changes remain uncommitted on top of b54b637.

## Latest connection check and loading updates

The desktop app is now running at http://127.0.0.1:8000. Refresh if the browser still shows connection refused. To load the newest backend changes, close the app's existing terminal window, then double-click START-OUTREACH.cmd. Keep that window open; the browser opens once the server is listening.

In Settings & connections, choose Check OpenRouter key. It uses [OpenRouter key metadata](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key), not a model completion. An accepted key still needs sufficient account credits and access to the selected model. Confirm Parallel access and credits in its dashboard. Then Review email connections → Verify again checks the reused account without sending an email. If declined, enable the mailbox's required access or replace its app password yourself. Never paste keys/passwords into chat.

## Removing work and understanding progress

Home, Saved audiences, audience details, Campaigns and campaign settings now show **Delete / archive**. Opening that action changes nothing. A confirmation page explains what can be removed.

- Unused audiences without a plan, research requests or leads can be permanently deleted after checking the confirmation box.
- Empty draft campaigns without contacts or saved message files can be deleted.
- Work with research or campaign history can be archived. **Archived work** lets you restore it. Charges, uncertain reservations, contacts, message history and replies are retained. Restored campaigns stay paused and unsent approvals require review again.
- Work still running cannot be removed. Open progress and finish or stop it first.

Each main page has **On this page** guidance and optional **More guidance**. After a form submission, the button shows **Working…** and a status message explains the action. Repeated submissions are blocked while waiting; returning with Back resets this feedback. Passwords and input contents never appear in status messages.

The header shows background activity. Research shows its current operation, actual saved-company count and accounted spend. Drafting and sending show actual job counts. Updates arrive without replacing the page or losing selections. Completion offers **Open latest saved results** / draft review / final sending results. If live updates are interrupted, the app says so and reconnects with a slower retry interval. Status polling does not repeat paid requests or send email.

Keep the app window open. Status checks run while this browser tab is visible. Smaller draft batches and connection verification use request-level working feedback; they do not claim a made-up percentage. Backups retain the native browser download flow.

To load this backend update, close the existing app terminal and double-click **START-OUTREACH.cmd**. Current running processes retain their previously loaded Python code. Latest verification: 475 offline tests passed, one Windows privilege-related skip; 53 Chrome assertions passed, with desktop and 390px visual review. Two email accounts are now recorded as verified by the live workspace; no new verification or sends were initiated during this UI change.


## Editing your idea and understanding research results

Choose **Edit audience** from Home, Audiences, the audience page or a company's evidence page. All inputs are visible in the editor. **Save changes** updates an unused draft. Once planning or requests exist, **Save revised audience (free)** creates a new draft and keeps the original results, approvals and costs. Saving edits makes no provider request. Pause the original separately if it is still running; a revised paid plan needs fresh approval.

Campaign pages show **Edit campaign** and **Edit message**. Their existing state and approval restrictions still apply; review edited drafts before sending.

**What happened** appears near the top of research results. It shows saved companies, published emails, your approvals and whether requests finished, are waiting or have an uncertain outcome. Expand **Costs and request details** when needed. An uncertain outcome is not a queued call and will not be retried automatically.

A company marked **Contact checks not finished** is only a suggestion. **Recover saved suggestions (free)** uses already-saved discovery results after a website-check fix; it makes no request. **Continue approved research (paid checks)** can spend within the existing cap to check contacts and fit. The app does not start those checks automatically.

The repaired audience now has one saved suggestion, with checks unfinished and research paused. Its five earlier calls are finished. No new paid calls or emails were made. Close the old app terminal and reopen **START-OUTREACH.cmd** once to load the latest controls, then refresh http://127.0.0.1:8000.


## Finding more contacts for an existing campaign

Open the campaign and choose **Find more contacts**, or its **Research** tab. Reuse its latest audience or choose another saved audience. Set **Company target** and **Maximum research spend** for the next batch. Expand **Edit audience for this batch** to change your goal, location, accepted contact roles or exclusions.

Choose **Save next research batch (free)**. This makes no provider request. Create the paid plan only when ready, then review and approve the plan to start research. Open results, check the published addresses and evidence, approve suitable contacts and choose **Add selected to campaign**. Your campaign is preselected. Existing members are skipped and earlier emails/replies stay intact.

Research batch history offers **Open results / progress**. Use it to continue unfinished contact checks instead of creating another batch. A company target is not a promised email count. Broaden geography or exclusions when looking for different companies; repeated scope can return familiar results.

**Edit campaign**, **Edit message**, **Edit audience** and **Delete / archive** are visible buttons. Delete is offered only for eligible unused drafts; saved history uses archive. A campaign with linked research retains it through archive.

If a button leads to the update notice, the old server is still running. Close its terminal, double-click **START-OUTREACH.cmd** in Desktop/Aksh/Outreach-Agent-Local, keep the new terminal open and refresh http://127.0.0.1:8000. Opening RESTART-OUTREACH.cmd while a normal desktop app already runs does not reload its code.


### Final flow, deletion and research update (2026-10-07)

The top-left name is Complete Outreach Tool. Home separates audiences (goal, plan, company/contact research) from campaigns (reviewed recipients, message, drafts and sending). Each audience shows its own name/reference and a saved-state next step: finish details, approve a ready plan, watch progress, continue paused checks, review contacts or inspect an uncertain request. Paid continuation never automatically replays an uncertain outcome.

Delete audience now also supports researched work after explicit confirmation: it moves to Deleted audiences while costs, evidence, existing campaign contacts and research links remain intact. Restore starts no research. Eligible unused drafts remain permanently deletable; active jobs must stop first. No real audience was deleted during this update. Before changes, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261007-032006.

Flexible search is offered for new/revised audiences. It accepts explicitly published general business inbox fallbacks, inspects up to ten discovery sources and prioritizes official contact pages. Evidence from official-site search results is retained when extraction omits an address. Explicit [at]/(dot) spellings can be decoded with the original quote retained. Unknown company-fit facts stay available for human review. Addresses and website identities are never guessed, and suppression remains enforced. Earlier approved runs keep their original request inputs; choose Edit audience and save a revised flexible draft to change the approved scope.

The normal owner app remains running at http://127.0.0.1:8000. Close its terminal and reopen START-OUTREACH.cmd once to load the new backend; keep the new terminal open. The app shows this update requirement. Earlier loaded processes retain their continuation fallback. No paid research or mail operation was performed.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Use the updated research engine

Close the existing app terminal and double-click START-OUTREACH.cmd once to load the updated Python backend; keep the new terminal open. RESTART-OUTREACH.cmd opens an already running normal server without reloading it. Open an earlier audience, click Edit audience, and save a revised draft. Start with five companies, Flexible mode if general business inboxes are acceptable, and a reviewed spending cap. Saving is free. Create a paid plan, review it, then explicitly approve research. The screen now separates found names, verified sites, checked companies and email counts. Review source evidence before approving any contact. A cap or coverage stop keeps partial results. No named founder/HR/management role or inbox delivery is guaranteed.


## Add a saved audience to a campaign

Open the campaign, choose **Audience → Add a saved audience**, then choose the audience and its approved contacts. Alternatively, open an audience and click **Use this audience**. Choose the destination campaign and click **Add selected contacts to campaign**.

Saving an audience saves your goal and criteria. It does not automatically create recipients. If no contacts are ready, open the audience to continue research or review the evidence and approve contacts with published emails. You do not need to save a separate contact list before adding them. Existing members are skipped; reusing contacts from another campaign requires reviewing their prior outreach and acknowledging reuse.

## Add attachments to your emails

Open **Campaign → Message → Add or manage attachments**. Choose files and click **Upload attachments**. Use up to five files with a combined size of 10 MB: PDF, DOCX, XLSX, PPTX, TXT, CSV, PNG or JPG.

The same files accompany every initial email in this campaign and its optional draft tests. Review filenames and download files to check them on draft review and launch. Changing attachments returns approved unsent drafts to review and requires fresh launch confirmation. Replies do not automatically include them.

Removing a file stops it being attached to future emails; saved message/test history retains the original version. Workspace backups include the uploaded bytes. The database and backups grow with the files you upload, so keep them private.

After installing this update, restart the app once with START-OUTREACH.cmd and refresh [your local workspace](http://127.0.0.1:8000).


## Research without losing your place

Save your goal, company type and location. Select your preferred contact role first, for example Founder; selecting every role allows a general business inbox to count toward the target. Flexible search keeps published general inboxes as labelled fallbacks after checking preferred roles. Focused search keeps role evidence explicit.

Choose **Prepare plan for free**, review it and only then approve paid research. **Web searches / Pages fetched** show whether the run reached full-page extraction. A budget is a cap, not a promise of that many founders or deliverable addresses.

An audience keeps its versions and last saved run together. **Edit audience** creates a new version under the same card when the original has research history. **Continue research / change target and budget** changes a paused run's total cap without discarding spend; save limits and resume separately. Prior uncertain requests are never replayed.

You can use partial results: open the source evidence, approve suitable complete contacts, then **Use this audience** and choose an existing campaign or create one. Approved contacts from earlier active versions remain selectable. Add files from the campaign's **Message → Add attachments**.

## Try the improved email research
Create an audience or edit an older audience into a new version. Select the roles you need. Optionally expand Known companies and add `Company | https://website` (up to ten). Save, create the free plan, review the scope and budget, then separately approve research when ready to incur provider charges. Results distinguish requested-role addresses, general inbox fallbacks and identities needing review. Open each company to inspect role and email sources, approve suitable contacts, and choose Use this audience to add them to a campaign. A budget is a spending cap, not a guarantee of emails.

## Add found emails directly
In an audience, select the emails, choose a campaign, and click **Add selected to campaign**. You can also create a campaign from the selection. A separate approval checkbox, review note or saved list is no longer required. Source details and role/fit labels remain available. Adding contacts never sends email. Open a campaign’s **Attachments** tab to upload and manage files. For lower-cost research controls, create a new audience or an edited version; existing paid runs retain their original strategy.

In a campaign, open Contacts, expand an audience, select emails and click Add selected. No saved list is needed. Older list tools live under Other ways to add contacts. Create a campaign by naming it; add emails afterward, or retain the contacts already selected from research.
