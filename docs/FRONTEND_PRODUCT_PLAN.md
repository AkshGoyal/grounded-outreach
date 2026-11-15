# Frontend product plan

Status: product design approved by the operator. The first intake/research/review
increment and the campaign/message/draft increment are implemented. Sending
progress, inbox/account refinements and desktop end-to-end acceptance are also
implemented. OAuth host/provider activation and real delivery remain. Phone testing
is postponed; see CAMPAIGN_READINESS.md and LAPTOP_SETUP.md.
Latest user direction: 2026-10-04. Execute improvements in the real FastAPI app;
the separate phone HTML demo is not backend or research verification.

## Product goal and main journey

Turn a person's outreach goal into an approved audience, personalised messages,
controlled sending and manageable conversations. Support multiple campaigns,
different Gmail/Zoho sending accounts, returning to older work, and adding leads.

Describe goal → clarify essentials → approve research plan → research → review
leads → save audience/choose campaign → review message brief → generate drafts →
approve drafts → review launch → explicitly send → manage replies.

The person should understand what is happening, what is uncertain, what they are
authorising, how much it costs and what to do next. Each screen has one principal
action. Save incomplete work and preserve context, filters and review position.

## Campaign preferences and clarification

Collect audience and message preferences during campaign creation and editing,
not by repeatedly questioning the operator in developer chat. Allow a research-
first start too: keep the intake as a saved draft until a campaign is chosen.

Audience fields: company type, geography, contact role, must-haves, exclusions,
target count, research budget, and desired personalisation evidence. Message fields:
outreach purpose, introduction/offer, relevant sender background, desired response,
tone and signature. Projects, tags and search queries belong under optional settings.
Email connection can be completed later; it must be verified before launch.

Ask conditional clarifications only when a missing or ambiguous answer changes
research. Show existing answers and ask the person to resolve the ambiguity. Do
not require a CV or vacancies when the request is speculative founder outreach.
Review the resulting plain-language plan before paid discovery. Creating/refining
the AI plan itself is a paid action within the run cap and must be labelled.

Editing audience preferences does not silently change an already approved run.
Explain the effect and create/reapprove a revised plan; retain earlier evidence.
Changing the message or sending identity returns unsent drafts to review. Existing
sent history and replies keep their original sender and campaign association.

### Current real test brief

Find AI product startups mainly in Bangalore/Bengaluru. Seek explicitly published
founder, HR/recruiting or senior-management professional emails and source-backed
company/product details for later personalised drafting. Prefer founders, but accept
published HR/recruiting department inboxes or named senior-management contacts as
fallbacks. Show the actual contact role and source; an HR inbox does not need a named
person. General/support/sales inboxes are separate and do not satisfy this brief.
Do not guess email patterns or extensively investigate vacancies. Missing contact
is an unresolved result, not permission to invent one. Sender skills are not supplied;
collect them at the message-brief step if needed for truthful drafting.

## Navigation and page inventory

Desktop: Home, Research, Lead lists, Campaigns and Inbox remain persistent. Accounts,
Settings, Do-not-contact and Archives are accessible under management. Mobile: five
bottom tabs for Home, Research, Leads, Campaigns and Inbox; a visible menu opens
management. Project selection filters work; it is never mandatory onboarding.

| Page | Purpose and principal action |
| --- | --- |
| Workspace sign-in | Protected access to the tool. Mail-provider connection is a separate action. |
| First-use Home | Goal input and a simple start; existing list/import are alternatives. |
| Returning Home | Tasks awaiting review, active sends, replies, interrupted work and next actions. |
| New outreach intake | Start from research, a saved audience or an import; save as draft. |
| Campaign/audience preferences | Edit audience and message intent; ask conditional clarification before discovery. |
| Research library | Search/filter runs; see target, spend, status and reviewed yield; resume correct work. |
| Research brief | Text input plus optional voice transcript that remains editable. |
| Research plan review | Editable audience, mandatory criteria, exclusions, contact role and budget; approve discovery. |
| Research progress | Actual stages/counts, accounted spending, partial results and stop/recovery status. |
| Lead review | Matches, needs review, no requested contact and unsuitable results; approve/remove a selection. |
| Lead detail | Identity, criteria, contact purpose/ownership, quotes, sources, dates and prior outreach. |
| Lead-list library | Reusable approved audiences grouped by purpose/project; open or create a list. |
| Lead-list detail | Inspect/add/remove members; choose a new or existing campaign. |
| Campaign creation | Audience → message → sender; save without a verified sender, block launch until connected. |
| Campaign overview | Readiness checklist, sender, counts, replies and next task. |
| Campaign audience tab | Members, origins, exclusions and previous outreach; add more approved leads. |
| Campaign message tab | Goal, introduction/offer, background, tone, desired response and closing; save revisions. |
| Campaign drafts tab | Generate remaining/rewrite unsent drafts; filter by review and checks. |
| Individual draft review | Full email plus recipient evidence; edit/approve/reject and move to next. |
| Launch review | Exact sender, eligible/held-back recipients, pace, daily limit and complete email previews. |
| Sending progress | Sent/remaining/stopped/uncertain attempts; stop between deliveries and explain recovery. |
| Inbox | Campaign/account selectors by readable name, reply categories, last sync and connection errors. |
| Conversation detail | Original outreach, thread, source account and editable suggested reply; explicit send. |
| Email accounts | Gmail/Zoho connection, last verified state, reconnect errors and campaigns using each identity. |
| Settings/spending/recovery | Provider readiness vs authenticated status, spending controls, backups and failed tasks. |
| Do-not-contact and archives | Global suppression, preserved old campaigns and search/history. |

Campaign tabs share one header and retain sender/context. Avoid introducing new
top-level destinations for every workflow step. Keep current URLs working and
reuse the existing records rather than making a duplicate workspace.

## Decisions and states users need to see

Separate company identity, audience fit, requested contact availability, contact
ownership, mail checks and user approval. Never collapse them into an unexplained
confidence percentage. A named founder email is different from a general inbox.
Published contact text is different from verified deliverability.

Research states: draft, clarification needed, planning, awaiting approval, running,
paused, partial/completed and failed. Show discovered candidates separately from
reviewed eligible leads. Do not imply the requested count is guaranteed. Stop
takes effect after the current request; already-incurred spending remains recorded.

Lead states: unreviewed, unresolved identity, missing requested contact, missing
mandatory evidence, user-approved, removed and suppressed. Approval keeps its
scope and provenance. Removing a lead from an audience does not erase history.
Unknown/contradicted facts do not become supported merely because a note is added.

Draft states: generating, needs review, edited/recheck, approved, rejected, sent
and uncertain. Changes invalidate relevant unsent approvals. Suppressed recipients
remain blocked. A successful SMTP submission is not proof of inbox delivery.

Campaign states: draft, ready, active, paused, completed and archived. Show whether
the server is running; do not promise durable background operation before the host
and worker support it. No automatic replies or follow-ups in the initial scope.

## Key interactions

Lead review must separate approving a selection from saving/enrolling it. After
approval offer Save as list, Create campaign and Add to existing campaign. Show
prior outreach and require acknowledgement when appropriate. Reuse must not alter
an existing campaign's saved recipient address.

The campaign checklist is Audience ready → Message ready → Sender connected →
Drafts approved → Launch reviewed. Research and planning work before email setup.
Changing the sender after sent history exists requires a separate campaign.

Draft review needs previous/next navigation, selection-aware bulk approval,
grounding failures beside the relevant claim, complete closing/footer previews,
and clear AI cost information separate from research spending. No recipient fact
or sender qualification may be invented to make an email sound personalised.

Accounts distinguish app-password connection from OAuth (both implemented,
OAuth awaiting host/provider activation). Never show a successful OAuth state until a provider actually connects.
Real research testing and real mail testing are separate from the static demo.

## Mobile and accessibility acceptance

Design at 390px first, with cards replacing dense tables, 44px touch targets,
keyboard-safe forms, visible focus, semantic headings and labelled controls. Sticky
actions must not cover content or the iPhone safe area. Save form drafts; avoid
full-page refreshes while a person is editing. Do not rely on colour alone.

Voice input is optional and browser-dependent; always provide text. Test Safari
on an actual iPhone through HTTPS when a real application host exists. Chromium
touch emulation is useful QA but is not an iPhone/Safari integration test.

## Quality and product acceptance

For the current job-outreach test, inspect every candidate's correct company, AI
product, Bangalore association, requested contact role, published email ownership
and personalisation facts. Track founders, HR/recruiting, named senior management,
unresolved and generic-only results separately. The approved plan must show allowed
fallback roles; do not silently broaden an existing founder-only research run.
Keep results pending user review and retain exact quotes/URLs/retrieval dates.

Regression examples: similarly named companies, directory-wide geography claims,
consulting described as an owned product, third-party footer contacts, guessed
emails, missing page footers, unsupported quoted claims and cross-campaign duplicates.

Product scenarios: complete the journey without a connected mailbox until launch;
manage sales and job campaigns simultaneously; revisit/add audience safely; change
message and reapprove; resume known research without paying twice; retain uncertain
requests/deliveries; receive replies through the correct account; respect suppression.

## Implementation order and files

1. Establish the real research baseline and save the current contact-role brief.
2. Implement intake/Home, plain-language plan, progress and staged lead review.
3. Implement list-to-campaign handoff and campaign workspace tabs/checklist.
4. Improve draft queue/review, launch and sending/recovery screens.
5. Complete account/inbox UX, activate the implemented OAuth/HTTPS mail transport, and
   test the actual hosted app and authorised mail round-trip on iPhone.

Reuse `web/app.py`, `web/templates/` and `web/static/` for the actual interface.
Add intake/preferences and role/identity evidence in the existing core/store with
additive migrations where needed. Update route acceptance tests and browser QA.
The first UI increment touches `home.html`, `research.html`, `research_run.html`,
`_leads.html`, `lead.html`, `campaign_form.html`, `base.html`, `workspace.js`,
`style.css`, their route handlers and preference storage. Follow later increments
with campaign/draft/send/inbox/account templates and corresponding route tests.

No new frontend framework is required to deliver these interactions. Hosting,
provider OAuth and durable workers remain separately visible implementation work.

## Implemented first increment — 2026-10-04

The real application now starts with a free saved goal/audience draft, not an
immediate paid planning request. Research is a library with a New audience entry.
Saved intake captures company type, geography, accepted contact roles, purpose,
count, budget and optional requirements/exclusions/personalisation. Incomplete
intake asks the missing company/location/contact questions inside the tool. Paid
planning requires complete answers and explicit authorisation; research still
requires separate approval of the editable plan. Mail setup is deferred in the
journey. Drafts persist in SQLite; optional unsubmitted changes survive refresh
in browser-tab storage, without restoring paid authorisation. Validation errors
retain submitted values. Started audiences cannot be edited in place.

Accepted roles are alternatives, not simultaneous requirements. They reach both
the AI planning brief and company contact-search objective/query. Old runs keep
their original contact-search inputs for checkpoint recovery. Role classification
and address ownership are still source-review tasks, not automatically verified
fields. No live quality improvement is claimed from these prompt changes.

Home shows unfinished research, the plan view keeps search-query controls under
Advanced, results separate Needs review / No published email / Approved / Do not
contact / Removed, and bulk actions show selection counts. Review and subsequent
list/campaign handoff are visually separate. Filters survive review redirects.
Phone navigation has five bottom tabs and a Manage menu; lead tables become cards.
This is the production app, not a change to the standalone static phone demo.

Offline tests and desktop/390px mobile Chromium checks exercise saved drafts,
refresh restoration, plan approval, filters, bulk selection, navigation and
overflow. Actual iPhone Safari/HTTPS hosting, OAuth, live delivery and the remaining
campaign/draft/inbox redesign are not completed by this increment.

Final verification for this increment: **373 offline tests passed**, repository
lint/format checks passed, and desktop/390px mobile Chromium workflow checks
reported no browser errors, external requests or horizontal overflow across Home,
research library/intake/results, campaigns, lists and accounts. Browser fixtures
and mail/providers were fake; no additional live calls or sending were performed.

## Implemented campaign and draft increment — 2026-10-04

Approved contacts now hand off directly to a new campaign through a reusable list.
Creation follows Audience → Message → optional Sender and saves incomplete work.
Existing campaigns can add an approved list from their Audience tab; duplicate,
suppression and prior-outreach checks remain. Campaign tabs share the name, sender
and context: Overview, Audience, Message, Drafts, Launch and Replies. Overview
shows readiness and the next actions. Sent campaigns retain their original account.

The structured message brief captures topic, introduction, supplied background,
request, tone, name and optional ending. No qualifications are inferred. Partial
messages save freely but cannot generate drafts or launch. Changing message text,
ending or account returns unsent approved drafts to review. Legacy raw text remains
supported; editing it clears the structured representation to avoid conflicting copy.

Draft queues have search/status filters, selection-aware approval and previous/next
review. Only current drafts from this campaign can be approved by the new selection
form; unsupported, ambiguous and suppressed drafts remain held. Launch shows every
eligible email in full. New campaigns cannot silently use environment mail settings:
a chosen verified sender is required before launch or a test delivery.

Internal research IDs and reviewer notes are audit metadata, not recipient facts;
they are excluded from model prompts and grounding, including older stored contacts.
Browser restoration never restores approval, launch or prior-outreach consent.
The actual app was checked at desktop and 390px mobile widths with fake providers;
no external requests or mail were made. Public hosting and actual iPhone Safari,
OAuth activation, durable workers and measured live research quality remain separate.

## OAuth connection and test-mail UI — 2026-10-04

Email accounts separates app-password transport from OAuth/HTTPS. Connect with
Google/Zoho opens a dedicated sender-details/provider-consent flow. Missing HTTPS,
workspace protection or provider credentials disables the button and exposes admin
setup. Reconnect keeps the same confirmed email's account/history and resets unsent
approvals. A confirmed test-to-self action rejects campaign/suppressed addresses and
replayed forms, reports acceptance separately from delivery, and retains uncertainty.
The app's login remains independent of provider connection. Source/account routing
and campaign approval gates remain. No hosted phone URL, actual consent or delivery
is established by offline/browser checks. See OAUTH_SETUP.md for activation.

## Account recovery, inbox and sending refinement — 2026-10-04

Inbox has readable campaign/account selectors, scoped checks and retained review
filters. Inbox/send tables adapt to mobile cards. Send progress shows campaign and
sender identity and makes server/restart/uncertain-delivery limits explicit. Account
screens expose local disconnect without deleting campaign history; mail tests show
saved outcomes across restarts. Permission refusal clears verified state. The
administrator OAuth details show an unrecognized HTTPS proxy rather than silently
trusting it. Remaining live activation is covered by HOSTED_APP.md: connect hosting,
register providers, consent, controlled delivery and actual iPhone testing.


## Desktop acceptance and recovery implemented — 2026-10-05

First-use Home keeps the goal form; returning Home collapses it and surfaces campaign
next actions and completed research awaiting lead review. Campaign tabs now include
persistent History; reply detail retains campaign and receiving-account context.
Launch consent expires and binds exact content, sender, audience and pacing. Repeat
or interrupted reply/test sends remain fenced; uncertainty is visible, stops the
batch and reserves daily room. Full workspace backups are downloadable and tested
for restoration. Imports retain campaign context. Form labels and secondary-action
contrast were corrected during desktop browser QA.

The complete Chromium journey at 1440px passed with zero JavaScript errors, external
browser requests, horizontal overflow or missing labels in checked screens. It uses
fictional providers and is not independent user research or real delivery proof.
A separate bounded live research test worked but produced only a general inbox;
it remains pending and does not satisfy the requested role. Phone testing is
postponed. OAuth provider activation, real delivery and contact quality remain
explicit gates before broader use. See CAMPAIGN_READINESS.md.
