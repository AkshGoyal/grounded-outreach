# Roadmap

## Current acceptance status — 2026-10-05

The campaign journey passes desktop browser QA and all 449 offline tests,
including the shared-ledger bridge checks for the live production pilot. Returning Home,
exact launch consent, persistent message history, reply duplication/uncertainty
guards, daily pending reservations and downloadable full backups are implemented.
Campaigns become active on launch; pause/completion remain explicit choices.

Parallel/OpenRouter read-only authentication returned HTTP 200. A subsequent live
production research run, bounded to $0.12 with the original ledger also gating every
request, completed with one company and a general inbox. It accounted $0.022986,
bringing total pilot accounting to **$0.514115 / $1**. Zero founder/HR/management
contacts are confirmed; no lead was approved/enrolled and no real mail was sent.

Next external steps: configure hosting/provider OAuth, grant owner consent and run
a controlled real-email round-trip. Research contact yield still needs improvement
and manual source review. Phone testing is postponed. Durable workers, automatic
follow-ups and automatic reply sending remain deferred. See
[CAMPAIGN_READINESS.md](CAMPAIGN_READINESS.md) and [LAPTOP_SETUP.md](LAPTOP_SETUP.md).

Earlier roadmap sections retain the project history; this status supersedes their
older implementation/test counts and open prerequisites.

## Current research increment (2026-10-03)

The bounded experiment in [RESEARCH_PILOT.md](RESEARCH_PILOT.md) implements
custom Search/Extract and FindAll preview comparison with shared assessment.
Both keys now authenticate in Cloud. All four bounded comparisons completed:
15 candidate records assessed; $0.407160 accounted against the $1 cap, including
$0.040136 conservatively retained from the rejected Cloud request and earlier
handoff. All 325 offline tests, lint and formatting checks pass. See
[the comparison and source review](RESEARCH_PILOT_RESULTS.md) and
[the recovery record](RESEARCH_PILOT.md#cloud-comparison-completed-2026-10-03).

Next: resolve company identity, retain literal contact/evidence text and reject
directory-wide or service-only fit claims. Test improvements on the saved corpus
before another paid run or UI integration. Human-verified yield and cost per
usable lead remain unmeasured; all records are pending and not campaign-ready.

**User requirement added 2026-10-03:** managing multiple concurrent research
runs and campaigns must be easy. The UI increment must include purpose/category,
tags, status filters, persistent navigation and links between research, lists
and campaigns. See [PLATFORM_PLAN.md](PLATFORM_PLAN.md#managing-multiple-research-runs-and-campaigns).

**Project:** personalized B2B outreach — a grounded, individually personalized
email per recipient, sent at a controlled rate, with threads tracked, replies
classified, and follow-ups that stop when someone answers.

**Last updated:** 2026-09-26

---

## Current position — v1 in use; becoming a platform

**Next: [PLATFORM_PLAN.md](PLATFORM_PLAN.md)** — the research layer, the replies
layer, and the rest of the browser front end, with the options and costs.

| | |
| --- | --- |
| **State** | **v1 is complete.** A contact list goes in; grounded drafts come out; a person reviews, edits and approves them; approved drafts are sent from Zoho with a compliance footer, at a capped and paced rate, never twice to the same person, never to anyone on the do-not-contact list. |
| **Done** | Phases 1–6. Plus: backup, a local web interface, two model adapters (OpenRouter and Anthropic), and a first real run against live models on real contacts. |
| **Deferred** | Automatic follow-ups and durable background workers. Reply ingestion and explicit answers are implemented. |
| **The real bottleneck** | Phase 3.5 — **7 of 44 leads have an email address.** The evidence on all 44 is excellent; the addresses are what is missing. |
| **In use** | The first 10 real emails were sent on 2026-09-24. Since D-022 the whole loop — setup checks, offer and ending, import, draft, review, test email, send with progress and Stop — runs from the browser. |
| **Tests** | See current acceptance report; offline suite is green, with fake providers and no external API requests. Cloud browser tests need local socket permission; inherited application credentials are removed from the test process. Nothing in the suite has ever sent a real email. |

| Phase | Status |
| --- | --- |
| 1 · Stack and skeleton | done |
| 2 · Data model and suppression | done — two independent guards |
| 3 · Import | done — tested on the real leads file |
| 3.5 · Finding addresses | **pilot measured** — four Cloud comparisons completed; improve source identity and evidence extraction before production integration (D-024, RESEARCH_PILOT_RESULTS.md) |
| 4 · Grounded drafting | done — prompt v2, tuned on a real run |
| 5 · Review | done — web screen |
| 6 · Sending | done — from the terminal or the browser (D-022); used for real |
| 7 · Replies | done (D-023) — Inbox page: read, matched, sorted, opt-outs and bounces suppressed, answers sent by a person |
| 8 · Follow-ups | deferred (D-014) — written by hand |
| 9 · Docs and portfolio | docs done; **the leads file must be purged from git history before the repo goes public** |

---

## Connecting Zoho and sending your first real emails

**Part 1 — in Zoho, once.**

1. **Check the domain is set up.** Zoho Mail Admin Console → Domains →
   starthreads.in → Email Configuration. MX, SPF, DKIM and DMARC should each
   show as verified. Any that do not: Zoho shows a record to copy — add it in
   GoDaddy's DNS page for starthreads.in, wait an hour, press Verify.
2. **Allow IMAP/SMTP access.** Log in to mail.zoho.in → Settings → Mail
   Accounts → IMAP Access → on.
3. **Make an app password.** accounts.zoho.in → Security → App Passwords →
   Generate, named "outreach tool". Copy it — Zoho shows it once. This, not
   your normal password, is what the tool logs in with.

**Part 2 — in `.env` on your laptop.**

```
OUTREACH_MAIL_SMTP_HOST=smtppro.zoho.in
OUTREACH_MAIL_SMTP_PORT=465
OUTREACH_MAIL_USERNAME=aksh@starthreads.in
OUTREACH_MAIL_PASSWORD=the app password from step 3
OUTREACH_MAIL_IMAP_HOST=imappro.zoho.in
OUTREACH_SENDER_COMPANY=Star Threads Private Limited
OUTREACH_SENDER_ADDRESS=your full registered business address
```

**Part 3 — test, in this order.**

4. `uv run outreach check` — must end with the mailbox saying "worked".
   That is a login only; nothing is sent.
5. `uv run outreach send-test --to your-personal-gmail` — one email to you.
   Check it is in the inbox, not spam, and that Gmail's "Show original" says
   SPF, DKIM and DMARC all PASS.
6. Optional but worth it: send a test to the address mail-tester.com gives
   you, for a score out of 10 and a list of anything wrong.
7. `uv run outreach send-test --to your-personal-gmail --draft N` — one real
   draft, exactly as the prospect would receive it.
8. Only then: `uv run outreach backup`, and send the real ones.

## Picking this up again

**The next piece of work is Phase 3.5** — addresses for the other 37 leads.
Its first decision is not technical: where addresses may come from. A
business's own website, publishing a contact address for enquiries, is the
strongest footing under the DPDP Act; brokered or scraped personal addresses
are not. That needs deciding before anything is built.

**Also carried forward:**

1. **Purge the leads file from git history before going public.** It was
   uploaded through GitHub's web interface, which bypasses `.gitignore`, so it
   sits in the history even if deleted. Use `git filter-repo`, or GitHub's own
   guide to removing sensitive data. The file holds no credentials, so nothing
   needs rotating — but check that no fork keeps a copy.
2. **Re-run the model comparison on prompt v2.** GPT-5.6 Luna won on v1
   (D-013); v2 changed enough that it is worth confirming.
3. **Backups need a habit and a second location.** `outreach backup` works;
   it is only useful if it is run, and kept somewhere other than this laptop.

---

## Established facts

Answers given 2026-09-18/19. These are facts, not assumptions — anything not
listed here is still unknown and must be asked, never invented.

| | |
| --- | --- |
| **Primary use case** | B2B outreach for a family RFD (ready-for-dyeing) cotton thread manufacturer in Ludhiana. Introduce the product, offer samples, start a conversation. |
| **Secondary use case** | Job-search outreach — lower volume, a variation of the same engine. Not in v1 scope. |
| **Volume** | 20–30 sends/day. Less is acceptable. **Quality matters more than volume** — this is a design input, not a preference. |
| **Recipients** | Mostly India → DPDP Act 2023 is the governing regime. Some international exposure possible; to be confirmed before any non-India send. |
| **Domain** | `starthreads.in` (**.in, not .com**) — registered at GoDaddy, live website on Vercel, full login access. DNS is authoritative at **GoDaddy** (`ns13`/`ns14.domaincontrol.com`), pointing at Vercel via A/CNAME — so mail records are added in the GoDaddy console, not Vercel's. Has **never sent email**, so it has no sending reputation. |
| **Mailbox** | `aksh@starthreads.in` — Zoho Mail on the root domain, live (D-002, D-003, D-008). |
| **Recipient data** | Supplied by hand at first, partly from research already collected in a spreadsheet. Structure deliberately not yet pinned down. Automated research/collection is a wanted future feature, not v1. |
| **Cost posture** | As low as possible without trading off quality. Every cost decision discussed individually. |
| **Hosting** | Runs locally for now, one user. VPS or cloud later. Scale up only when needed. |

### What the volume figure settles on its own

20–30/day is not a smaller bulk system, it is a different class of system:

- **No ESP needed.** One ordinary mailbox covers it many times over.
- **Warm-up is not throwaway work.** The ramp *is* the campaign.
- **No queues, workers or concurrency.** A process run once a day suffices.
- **Reviewing every draft is feasible** — ~30 drafts is minutes of reading. This
  effectively settles the old open question on review posture: review
  everything, at least until the output earns trust.
- **Cost is dominated by the mailbox subscription,** not by sending or tokens.

---

## Two tracks

- **Track B (build)** — Phases 1–9, strictly sequential.
- **Track D (deliverability clock)** — domain, DNS, mailbox, warm-up ramp. Runs
  in the background because it is bound by wall-clock time, not by engineering
  speed. It produces *reputation*, not features.

Track D is now the long pole. Nothing in Track B is blocked by it, and it is
blocked by nothing in Track B.

### Track D — next actions

1. ~~Confirm which nameservers are authoritative.~~ **Done:** GoDaddy
   (`ns13.domaincontrol.com`, `ns14.domaincontrol.com`). All mail records go in
   the GoDaddy DNS console. *(Caveat: the lookup was run against the `.com`
   spelling; re-confirm against `starthreads.in` before relying on it.)*
2. ~~Buy the mailbox.~~ **Done:** `aksh@starthreads.in` (D-008). IMAP/POP
   requires a paid plan; the free tier is web-access only and cannot be
   automated. **Select the India data centre at signup:** it determines the MX
   hostnames (`*.zoho.in` rather than `*.zoho.com`), is awkward to change
   afterwards, and keeps mail data in India, which suits DPDP.
3. Publish MX, SPF, DKIM and DMARC at GoDaddy. Before adding them, remove any
   default GoDaddy parked MX records and disable GoDaddy Email Forwarding — if
   either survives, inbound mail is misrouted. Adding MX and TXT records cannot
   affect the website, which is served via A/CNAME.
4. Verify SPF, DKIM and DMARC all pass before any real send.
5. Begin the warm-up ramp — genuine, human-written, low volume, rising toward
   20–30/day.

---

## Phase 1 — Stack selection and repo skeleton  *(done)*

- **Goal:** choose language, storage, LLM provider and layout; a skeleton that
  runs, lints and tests with no API keys present.
- **Main decisions:** language and runtime · storage engine · LLM provider and
  the single module wrapping it · config and secrets handling · test strategy
  and the LLM mock boundary.
- **Key risks:** over-building for a volume that does not exist; an LLM
  abstraction so thin it leaks provider details, or so thick it hides failures.
- **Done when:** clone → install → test suite passes green with no API keys, and
  `ARCHITECTURE.md` §5 is filled in.

## Phase 2 — Data model, suppression and the send-path invariant  *(done)*

- **Goal:** define campaign, recipient, message, thread, event and suppression;
  build the suppression ledger **before** anything can send.
- **Main decisions:** entity shapes and keys · whether the job-search use case is
  a campaign config or a fork (hypothesis: config) · how suppression is keyed
  (address, domain, or both) · where the check is enforced so it cannot be
  bypassed.
- **Key risks:** a suppression check in the caller rather than in the send
  primitive, so a future code path skips it silently.
- **Done when:** a test proves the only path capable of sending refuses a
  suppressed address, and no alternative path to sending exists.

## Phase 3 — Recipient import and data quality  *(done)*

- **Goal:** messy spreadsheet → validated, deduplicated rows, with every field
  personalization may cite marked as *evidence*.
- **Main decisions:** input format and column mapping · validation and
  normalization · dedupe key · how bad rows are reported · the evidence
  representation Phase 4 checks against.
- **Key risks:** silently dropping rows; normalizing an address into a different
  valid address; treating an inferred field as evidence.
- **Done when:** a seeded fictional list imports with a per-row accept/reject
  report.

## Phase 3.5 — Finding contactable leads  *(new, and now the bottleneck)*

Measured on the real list: **7 of 44 leads have a usable email address.** Thirty-six
say "Not published" — most came from IndiaMART profiles, which publish a phone
number and hide the email behind a contact form. The evidence on those leads is
excellent (segment, city, what they do, credibility, fit are filled for all 44);
only the address is missing. So the constraint on this whole tool is currently
addresses, not drafting.

- **Goal:** turn a lead with rich evidence but no address into a lead with a
  verified address, without inventing anything.
- **Main decisions:**
  - **Where addresses come from.** A business's own website, publishing a
    contact address for business enquiries, is the most defensible source.
    Brokers and scraped personal addresses are not, and carry a bounce and
    reputation cost as well as a legal one.
  - **Verification.** An address that does not exist becomes a hard bounce, and
    bounces damage the domain's standing. Verifying before sending matters more
    here than finding more addresses.
  - **How researched evidence is marked.** This is the sharp one — see below.
  - **How much runs unattended** versus produces a list for a human to confirm.
- **The risk that matters most:** *researched evidence is model output.*
  Invariant I-3 says a claim about a recipient must trace to evidence. If a
  research agent writes the evidence, and the agent invents a detail, the
  grounding check is faithfully tracing a claim back to a fabrication and
  declaring it sound. Researched facts must therefore be stored **with their
  source URL and marked as machine-gathered**, kept distinct from facts that
  came out of a human-checked spreadsheet — and probably held to a higher bar
  before a draft may cite them.
- **Legal note:** recipients are mostly in India, so the DPDP Act applies.
  Business contact details published by a business for business contact is the
  strongest footing. This needs a deliberate decision before the phase runs,
  not after.
- **Done when:** a lead with no address comes out the other side with a
  verified address and sourced, marked evidence — or is honestly reported as
  not contactable by email.

## Phase 4 — Grounded personalization  *(done)*

- **Goal:** every recipient-specific claim traces to an evidence field, enforced
  by code, not by prompt wording.
- **Main decisions:** prompt file format and versioning · output schema and
  constrained enums · **the grounding mechanism** (the central decision here) ·
  context cap per call · retry and timeout policy.
- **Key risks:** a check that catches verbatim mismatches but misses paraphrase;
  drafts that pass the check and still read like a template; prompt growth as
  evidence columns multiply.
- **Note:** personalization quality is capped by the richness of the input data.
  This phase will surface exactly how much evidence each recipient actually has.
- **Done when:** an adversarial set of drafts containing fabricated claims is
  rejected with no false negatives, with the LLM mocked.
- **Status:** the checker, the draft schema, the versioned prompt and the
  Anthropic adapter are built and tested (D-011). **Untested:** the live API
  call — that needs a key and costs money, so the adapter is exercised against
  a fake client only. Not yet wired into the command line or the web pages.

## Phase 5 — Human review and approval  *(done)*

- **Goal:** a human gate between draft and send.
- **Main decisions:** what makes a draft *flagged* (given that all are reviewed,
  flagging becomes a prioritization aid rather than a filter) · the review
  surface · whether edits feed back into prompts or evidence.
- **Key risks:** a review step heavy enough that it gets skipped, which is worse
  than no gate because it manufactures false confidence.
- **Done when:** a batch can be approved, edited or rejected, and an unapproved
  draft cannot reach the send path.

## Phase 6 — Sending  *(done)*

*Substantially smaller than originally scoped: at 20–30/day most bulk-sending
concerns do not apply, and the domain/DNS/warm-up work happens on Track D.*

- **Goal:** send approved drafts at a controlled rate through the mail port, and
  handle what comes back at the transport level.
- **Main decisions:** per-recipient-domain throttling · bounce parsing (bounces
  arrive as email, not webhooks — see D-002) · unsubscribe mechanism · the
  sender-identification and physical-address footer required by DPDP.
- **Key risks:** a crash mid-campaign that double-sends on restart; a mis-parsed
  bounce leaving a dead address unsuppressed.
- **Done when:** a campaign to a seeded test list sends at the configured rate,
  every send is idempotent under restart, and hard bounces and complaints feed
  suppression automatically.

## Phase 7 — Reply ingestion, threading and classification  *(deferred — D-014)*

*The most interesting phase, and the one carrying D-002's main risk.*

- **Goal:** fetch replies, attach each to the right thread, classify, route.
- **Main decisions:** thread identity via `Message-ID` / `In-Reply-To` /
  `References` and the fallbacks when clients mangle them · the classification
  label set and its enum constraint · routing rules per class · the confidence
  threshold below which a human decides.
- **Key risks:** mis-threading a reply onto the wrong recipient; an unsubscribe
  classified as "other" and never suppressed; auto-responders read as interest.
- **Done when:** a fixture mailbox of realistic replies — including
  header-stripped and forwarded ones — is attributed and classified correctly,
  unsubscribes reliably reach suppression, and anything unmatched lands in a
  human queue rather than being dropped.

## Phase 8 — Follow-ups  *(deferred — D-014)*

- **Goal:** follow up without ever contacting someone who already replied or
  opted out.
- **Main decisions:** cadence and cap · what a follow-up says relative to the
  original · stop conditions and where they are enforced.
- **Key risks:** a race between an inbound reply and a queued follow-up.
- **Done when:** a test proves no follow-up is sent after a reply, after an
  opt-out, or past the cap — including when the reply arrives while the
  follow-up is already queued.

## Phase 9 — Docs, demo and portfolio polish

- **Goal:** legible to someone who has never seen it; demonstrable without real
  recipient data.
- **Main decisions:** what the demo shows · README structure · which internals
  are worth explaining to a reviewer.
- **Key risks:** PII in fixtures, demos or git history.
- **Done when:** a seeded fictional campaign runs end to end from a clean clone,
  the four docs are current, history contains no real recipient data, and the
  repo is flipped to public.

---

## Why this order

1. **Suppression and the data model precede anything that can send.** A guard
   retrofitted onto an existing send path means every existing call site is a
   place it might be missing. The send primitive must be born with it.
2. **Import precedes personalization** because grounding is defined against
   evidence, and evidence is whatever import decided to keep.
3. **Personalization precedes sending** because "is this email worth receiving?"
   is the question most likely to invalidate the concept, and the cheapest to
   answer — drafts can be read without sending anything.
4. **Review precedes sending,** so the first real send is already gated.
5. **Replies follow sending; follow-ups follow replies,** because "have they
   already answered?" is a precondition for a follow-up, not a feature of it.
6. **Deliverability runs in parallel throughout** — see Track D.

## Alternative orderings considered

- **Thin vertical slice first** (one row → draft → send to yourself → read the
  reply). *Pro:* integration pain surfaces immediately. *Con:* the slice's send
  path is written before suppression exists — the exact retrofit guarded against
  above. Mitigable by hard-failing on every address except your own. Still open
  for discussion.
- **Deliverability first, end to end.** *Pro:* most runway for the hardest
  problem. *Con:* builds sending infrastructure for a message nobody would reply
  to. Track D captures most of the benefit at a fraction of the cost.
- **Reply layer first.** *Pro:* the most differentiated part. *Con:* nothing to
  reply to; would be built entirely against fixtures and rebuilt once real
  threading behaviour is observed.

---

## Open questions

### Answered

Q1 domain · Q2 geography · Q3 volume · Q4 data source · Q5 reply mailbox ·
Q6 stack constraints · Q10 repo location (→ D-001) · Q13 DNS authority (GoDaddy) ·
Q14 mailbox local part (→ D-004, then D-008) · Q15 who approves and who
answers — **closed by D-008** · Q8 interface (→ D-010: both, sharing one
implementation).

**Q7 review posture** — effectively settled by volume: every draft is reviewed.
The remaining detail (what gets flagged for extra attention) moves into Phase 5.

### Open

| # | Question | Blocks |
| --- | --- | --- |
| Q16 | Which model classifies replies — `claude-opus-5` or `claude-haiku-4-5`? **Deliberately deferred.** Costs $1.35 vs $0.27/month, so the decision is about accuracy, not price, and is better made in Phase 7 against real replies than guessed now. Changing it is a config value (I-6). | Phase 7 only. Blocks nothing before then. |

| Q9 | Is the job-search use case in scope for v1, or a later variation? | Phase 2 (campaign vs. fork). Working assumption: later. |
| Q11 | What does a *good* reply look like — a sample request, a call, a price enquiry? | Phase 7 label set; defines the success metric. |
| Q12 | Any international recipients in the first campaigns? | Phase 6 footer and consent requirements (GDPR vs. DPDP only). |

## Completed browser workflow (2026-10-04)

Implemented research brief/clarification → editable plan approval → bounded research
→ evidence/lead review → reusable lists/new or existing campaigns → verified Gmail/
Zoho sender assignment → draft-all/rewrite/review → paced sending → account-scoped
inbox and replies. Added project/purpose/tag/status navigation, campaign archives,
prior-outreach acknowledgements, credential encryption and protected Cloud access.
The $1 comparison pilot and multi-campaign plan remain preserved.

Offline provider tests and Chromium checks verify this increment. Real Gmail/Zoho
verification/sending cannot run in this Codex executor because public SMTP/IMAP is
unavailable. Deployment and authenticating the operator's accounts remain setup work.
See [workspace guide](WORKSPACE_GUIDE.md). Next recommended: OAuth/HTTPS mail
transports, delivery/reconciliation views, reviewed follow-up sequences and durable
workers for multi-user scale.

The app was run again in Cloud with fictional demonstration data, including the
research approval flow. Added a verified Codespaces launcher and corrected the
setup instructions; fixed overview campaign progress labels on desktop/mobile.
OAuth implementation remains paused at the operator's request for a clear hosting
explanation. Next: choose a permanent HTTPS address, register Google/Zoho OAuth
applications, implement and verify the account connection and HTTPS mail adapters.

Added a separate interactive phone demo with sample planning, lead selection,
campaigns, draft review, simulated sending and replies. Mobile Chromium checks
passed without external network requests. Prepared a Render static-site blueprint
for iPhone Safari; the operator must connect hosting/GitHub before a URL exists.
No Site or Render deployment was created, and this is not the Python backend.

Saved the complete frontend product plan, including campaign creation/editing
preferences, conditional clarification, lead evidence review and mobile navigation.
The Cloud founder-contact benchmark called Parallel/OpenRouter and saved six
reviewed facts plus three opening hooks, but found zero verified founder emails.
Combined pilot accounting is $0.491129. Fixed source-context selection offline;
founder role/ownership integration and the planned frontend redesign remain next
increments. The existing workspace, static demo and OAuth/hosting status above
are unchanged. See FRONTEND_PRODUCT_PLAN.md and FOUNDER_RESEARCH_RESULTS.md.

The operator approved the frontend product plan and broadened test contacts to
founders, HR/recruiting or senior management. Manual official-site review saved
two pending HR/recruiting contacts, product facts and opening hooks; one address
has a mailto mismatch flagged for review. Import preview accepted both rows, with
no enrollment or sending and no additional research API spend. Next production
work remains the approved intake/plan/review frontend, including explicit allowed
contact-role fallbacks; the live automatic founder result remains zero contacts.

## Approved frontend plan: first increment implemented

Implemented the real saved-intake → explicit paid planning → editable plan approval
→ staged lead-review journey. Added company/location/contact-role clarification
inside the tool, optional requirements and draft persistence, unfinished research
on Home, mobile five-tab navigation and lead cards. Contact preferences reach
planning and company-level search; legacy requests retain their original inputs.
Schema 6 adds `research_intakes` without replacing earlier run/campaign records.

The campaign/list handoff, tabs/checklist, message brief, selected draft review
and complete launch previews are now implemented below. Sending-progress/inbox
refinement, OAuth and permanent HTTPS hosting remain unfinished items from the
approved product plan. Automatic role ownership/deliverability checks
and a measured live research-quality improvement are not claimed.

## Approved frontend plan: campaign and draft increment implemented

Implemented Audience → Message → optional Sender creation, approved-selection
handoff and adding approved lists to existing campaigns. Added shared campaign tabs,
readiness overview, saved structured message briefs, draft filters, selected approval,
previous/next review and all-email launch previews. Schema 7 adds campaign briefs
without replacing records or legacy copy. New campaigns cannot inherit environment
mail credentials; incomplete messages and unverified accounts block launch. Message
or identity changes require unsent reapproval; sent history keeps its account.
Internal review notes/IDs cannot ground recipient claims. Validation retains inputs.

388 offline tests pass, including migration and sending gates. Fictional-provider
Chromium checks cover the preparation/review journey at 390px and desktop with no
horizontal overflow, JavaScript errors or external requests. No live research/mail
was run and the original pilot ledger remains intact.

Next: sending-progress/recovery and account/inbox UX; explain and choose permanent
HTTPS hosting before OAuth registration/activation. Then test authorised real mail
round-trip and actual iPhone Safari. Explicit source-backed contact role/ownership
and semantic fact review still need production work and a separately bounded quality
measurement; this UI increment does not establish improved live research yield.

## OAuth implementation and live test prerequisites

Implemented Gmail/Zoho authorization-code sign-in, encrypted refresh tokens, HTTPS
send/read adapters, provider identity and inbox-list checks, campaign/account routing,
Zoho thread-ID mapping, and an explicit test-to-self page with replay prevention.
Schema 8 adds tokens, expiring attempts, API IDs and test outcomes while preserving
schema 7 accounts/campaigns. Existing SMTP/IMAP and old CLI behavior stay supported.
Workspace login stays separate; a provider callback cannot sign into the workspace.

Offline and browser checks pass, but live OAuth/mail work is blocked by missing
HTTPS URL/client credentials and consent. Current Cloud TCP policy has no mail grants
and IMAP is missing. No deployment, live login/read/send or improved research quality
is claimed. Next action is host/provider activation per OAUTH_SETUP.md, then one
confirmed test to a user-controlled address, inspection of delivery, and a separately
approved tiny controlled-recipient campaign for reply routing. Sending-progress and
inbox refinement remain separate product work. The original pilot ledger is untouched.

Verification of this increment: 413 offline tests and lint/format checks pass;
desktop/390px browser checks pass with fake mail only.

## Deployment preparation and operational UI implemented

Prepared the real-app Render blueprint and protected persistent startup, preserving
the sample demo. Added saved test history, local OAuth disconnect, cleared verification
on refused permissions, readable/scoped inbox filters and mobile sending context.
430 offline tests, locked production build/local startup and desktop/390px browser
checks pass. Proxy trust remains restricted after automatic approval rejected the
wildcard proposal. No host account is connected and no deployment or live mail ran.

The concrete external next steps are in HOSTED_APP.md: connect hosting/review its
paid service/disk, verify proxy settings, register provider clients, grant consent,
and select/confirm a test inbox. Then run a controlled approved campaign for reply
routing and actual Safari QA. Durable queues, source-backed contact-role/semantic
verification and measured lead yield remain longer-term product work. The original
pilot ledger and navigation/history are preserved; no research spending was added.

## Laptop setup and guided UI completed — 2026-10-06

Windows process recovery and offline portability fixed. Simplified Home, three-step
free audience saving, separate paid planning, campaign creation/next actions and
connection settings. Private key entry preserves .env. Earlier email login reused
in encrypted storage with verification pending; old campaigns/history remain intact.
Authenticated graceful restart enables owner handoff from the restricted preview.

Validation: 458 offline tests pass, one symlink-privilege case skips; 35 real-Chrome
fake-provider assertions pass, including mobile layout and save-to-lead-review
integration. Actual loopback login, 12 pages/assets and free form persistence pass.
No paid research, real sends, mailbox reads or live authorization checks were performed.

Next owner steps: launch RESTART-OUTREACH.cmd, verify the reused account, and enable
IMAP/MFA/provider access if needed. Follow GETTING_STARTED.md. Real research and delivery
remain separately authorized use beyond setup.

### Desktop continuation verification (2026-10-06)

The owner desktop server is running on loopback in normal mode. Actual private login, twelve pages/assets, origin protection and a free form-to-database save passed. Added non-paid OpenRouter key metadata diagnostics, a restricted email-verification guard and browser opening only after the server listens. All 468 offline tests pass, one privilege-only symlink case skips; all 35 real-Chrome guided assertions pass. Backend updates need one close/reopen of the existing desktop app window. Email remains saved/unverified; owner verification, provider permissions and credits remain external steps. No research request, mailbox read or real send was made.

### Visible removal and guided live feedback completed — 2026-10-06

Added confirmation-based unused-draft deletion, reversible archive/restore views, visible controls on Home/lists/details/settings, per-page guidance, immediate action feedback and duplicate-submit protection. Research/current background job snapshots update actual counts and operations without full-page reloads. Completion and interrupted-update recovery are explicit. Mobile status remains visible.

Validation: 475 offline tests passed, one Windows symlink privilege skip; 53 Chrome assertions passed; desktop/390px screenshots reviewed; 33 targeted tests passed after final template changes. Real app remains running in normal mode; its previously loaded backend needs one close/reopen to expose these routes. Two mailbox accounts are recorded as verified. No paid research, live email or real deletion was initiated in this increment. Other deletion item types await user preference; existing history remains intact.


### Audience editing and zero-result recovery (2026-10-07)

Completed visible Edit audience from Home, audiences, details and lead evidence, plus campaign/message edit links. Unused drafts save in place; started work creates a revised free draft with original history preserved. Replaced the pending-request table with an early What happened summary, separate costs/details and honest unchecked-contact labels.

Fixed exact-host homepage validation and recovered one suggestion from the owner's saved results with no provider request. The audience remains paused pending contact/fit checks. All five original requests were already finished; the earlier failed run's uncertain reservation remains unchanged.

Validation: 487 offline tests passed, one Windows privilege skip; 66 real-Chrome assertions passed, plus 28 targeted checks after final template placement. Fake-provider desktop/mobile checks and actual owner-app HTML passed. Two email accounts are recorded as verified. No paid research, mail operations or real user deletion occurred. Owner must close/reopen START-OUTREACH.cmd once to load new backend routes; actual app remains available on port 8000.


### Research more contacts from a campaign (2026-10-07)

Completed prominent campaign Find more contacts and Research tab, free additional batches with audience reuse and separate caps, durable campaign/run links, related progress/results, and campaign preselection when enrolling approved results. Existing members are skipped; research and sending stay separate approvals. Limits appear first; optional audience edits and history stay collapsed.

Edit/removal buttons remain visible on older backend pages and route unsupported actions to update guidance. Actual owner HTML verified audience and campaign buttons; owner backend reload remains required for the new routes. Existing .env/history preserved and no paid research or mail operation used.

Validation: 495 offline tests passed, one Windows privilege skip; 80 real-Chrome assertions passed, plus eight targeted checks after final layout changes. Lint/format and desktop/mobile visuals pass. Next: owner reloads START-OUTREACH.cmd and uses the separately approved research/contact-review flow.


### Final flow, deletion and research update (2026-10-07)

The top-left name is Complete Outreach Tool. Home separates audiences (goal, plan, company/contact research) from campaigns (reviewed recipients, message, drafts and sending). Each audience shows its own name/reference and a saved-state next step: finish details, approve a ready plan, watch progress, continue paused checks, review contacts or inspect an uncertain request. Paid continuation never automatically replays an uncertain outcome.

Delete audience now also supports researched work after explicit confirmation: it moves to Deleted audiences while costs, evidence, existing campaign contacts and research links remain intact. Restore starts no research. Eligible unused drafts remain permanently deletable; active jobs must stop first. No real audience was deleted during this update. Before changes, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261007-032006.

Flexible search is offered for new/revised audiences. It accepts explicitly published general business inbox fallbacks, inspects up to ten discovery sources and prioritizes official contact pages. Evidence from official-site search results is retained when extraction omits an address. Explicit [at]/(dot) spellings can be decoded with the original quote retained. Unknown company-fit facts stay available for human review. Addresses and website identities are never guessed, and suppression remains enforced. Earlier approved runs keep their original request inputs; choose Edit audience and save a revised flexible draft to change the approved scope.

The normal owner app remains running at http://127.0.0.1:8000. Close its terminal and reopen START-OUTREACH.cmd once to load the new backend; keep the new terminal open. The app shows this update requirement. Earlier loaded processes retain their continuation fallback. No paid research or mail operation was performed.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Current research priority — 2026-10-07

Read-only diagnosis and [research execution plan](RESEARCH_EXECUTION_PLAN.md) completed. The latest 25- and 10-company owner runs saved zero companies because every first-round website was unknown and discovery stopped after two rounds. These runs spent $0.014270 and $0.014036 of their respective $0.10 caps; contact extraction was never reached. Flexible mode was already enabled.

Next proposed increments: persist suggestions and resolve official domains; adaptive contact collection with honest progress/outcomes; offline and dated public-source benchmark; separately owner-approved small paid pilot; optional fallback only if measured gaps justify it. No implementation or paid pilot occurred during this planning step. Current server is reachable in normal desktop mode at http://127.0.0.1:8000; no restart required for documentation changes.

### Implemented staged research — 2026-10-07

The user authorized implementation of the proposed Parallel-first flow. New web-created audiences and revised/copied batches use engine version 2; existing approved runs retain version 1 and their request fingerprints. Additive research_execution/research_suggestions tables preserve unresolved names and per-company work.

The new pipeline separately resolves official sites, reads up to four literal same-site contact links/pages, reuses completed requests, retains partial emails before fit checks, deduplicates aliases by official domain, and stops after at most eight discovery rounds or three rounds with no new names. Each request still reserves against run/daily caps before network I/O. Fast Search is explicitly limited to ten results with the documented source policy for official-domain contact searches. No extra provider account was introduced.

Target progress counts contacts compatible with the chosen mode. Focused HR does not count support as HR; founder/management roles remain unconfirmed until human review. Privacy/legal/DPO/no-reply/abuse/security administrative addresses are excluded from outreach contact results. Company facts can remain unknown and must be reviewed. Completion reports target reached, partial/no usable results or a budget stop, with visible website-check evidence and separate company/email counts.

Validation: 526 offline tests passed, one Windows symlink privilege test skipped; 89 real Chrome assertions passed against fake providers. Lint/format checks passed. Public-source benchmark seed documented in RESEARCH_BENCHMARK.md; actual Parallel/OpenRouter yield is still unmeasured for this engine.

No paid research, email send, mailbox operation, credential change or production-audience deletion was performed. Pre-change source/tests/docs/SQLite snapshot: data/recovery/ui-20261007-152905. The normal owner server remains running; its loaded Python needs one close/reopen through START-OUTREACH.cmd to activate the new backend. A visible research-page notice explains this.


### 2026-10-07 — Saved audience handoff and email attachments
Implemented direct saved-audience selection into campaigns; readiness guidance; selection origin and reuse checks; campaign attachment upload/download/remove; immutable delivery bytes for SMTP/Gmail/Zoho; visible draft/test/launch file review; stale-consent invalidation; exact file references retained with pending/sent/test history and database backups. Validation uses offline providers and fictional browser data. Account-owner live delivery remains an explicit user action.

Verification: full offline regression and real Chrome acceptance cover the new flow. Browser checks use a disposable workspace and fake providers; the account-owner app at port 8000 stays running until the owner restarts it once to load new Python routes. No live provider or mailbox operation was performed.

Final evidence: **542 offline tests passed; 1 Windows symlink privilege skip; 119 real Chrome assertions passed**. Ruff check/format and Git diff whitespace checks passed. Original workspace research ledger remains at 34 entries; no real emails, paid research or existing .env edits during this increment.


## 2026-10-07 research continuity implementation

Implemented: free structured plans, grouped explicit audience versions, last-run/history links, cross-version approved-contact handoff, same-run target/total-cap edits, separate continuation, search/fetch counters, lower new-run model reservation overhead, exact-evidence site resolution, preferred-role page collection and literal founder-role evidence in the fit call.

Validation uses fictional providers and real browser forms. Next quality gate remains the dated representative public-email benchmark described in RESEARCH_BENCHMARK.md, followed only by an owner-approved live pilot. Offline passes do not establish live provider authorization, public-email recall or inbox deliverability.


## Next effectiveness gate
Before further claims that research works: implement explicit seeded retrieval/diagnostics and measure a dated founder-email benchmark, then bounded cross-web expansion and relation-level evidence. EMAIL_RESEARCH_IMPLEMENTATION.md records the proposed sequence. No live provider pilot was performed for this proposal.

## Implemented locally — 2026-10-08

New audiences use strategy 4. Existing runs keep their original strategy and request fingerprints; create an edited version to use the new collector.

- Read company websites directly, follow published contact/team links, then use bounded wider-web search and extraction when the requested role is missing.
- Connect separately quoted role and email-ownership evidence; never manufacture an address from a name or domain.
- Keep general inboxes separate from requested-role matches and unconfirmed identities. External publications retain their source URLs and need human review. Publication does not prove deliverability.
- Optional **Known companies** accepts up to ten `Company | https://website` lines. It researches those companies only, reducing discovery costs.
- Save partial results and frozen assessment contexts. Completed requests are reused on resume; uncertain paid requests are not automatically replayed.
- Caps per company: three official-page reads, one official-domain search if needed, one wider-web search, up to two additional page reads, and up to two structured assessments. The approved monetary cap still takes precedence.
- Targets remain companies with suitable contacts, not a promise of that many founder addresses. Unconfirmed identities do not satisfy the target automatically.

Still pending: an owner-approved live Parallel/OpenRouter pilot to measure end-to-end yield and actual cost. Offline fixtures do not establish live recall or deliverability. Optional enrichment-provider integration and a shared cross-run page cache are not implemented.

## 2026-10-08: Simplified email workflow
Implemented one-step selection to campaign, optional detailed review, visible attachment navigation, cost-per-email reporting and strategy 5 empty-result/low-yield spending controls. Pending: owner-run live yield measurement; no paid research or real email is part of implementation checks.

Completed: inline campaign Contacts picker, no repeated destination selection, duplicate omission, optional legacy lists and selected-contact count on campaign creation.

Campaign contact-flow validation: 51 affected offline tests passed, 142 real Chrome assertions passed, Ruff and git diff checks passed. No paid research or real mail was used. Existing desktop server remains running; restart once to load inline audience contacts.

## Current improvement pipeline — 2026-10-09

See [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) for the prioritized living backlog,
effort/risk and implementation status. Prompt-first audience/campaign creation and
concise development instructions are implemented in the current increment. Selected
contact trust, results-first research layout, measured role yield and personalization
continuity are next. Broader autonomous outreach and architecture replacement remain
outside scope. See DEVELOPMENT.md for focused task and verification commands.
