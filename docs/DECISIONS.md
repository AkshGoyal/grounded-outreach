# Decision log

## Campaign safety, desktop acceptance and live research validation — 2026-10-05

**Decision:** Bind launch consent, reserve reply answers, retain test outcomes,
expose message history, bundle full backups, and prioritize returning work on Home.
Verify the desktop journey and bounded live research through the original ledger.

**Context:** The operator authorized remaining fixes and end-to-end testing, with
phone testing postponed. Hosting/OAuth credentials are absent. The original $1 cap
remains authoritative; real research must not escape into a fresh budget.

**Alternatives considered:** A visual-only demo cannot exercise sending/storage.
A frontend rewrite or durable queue expands scope without fixing immediate gaps.
Authentication or fake research alone cannot establish contact quality. Resetting
the pilot ledger or using an unrelated production budget loses the shared ceiling.

**Why this one:** Preserve records/navigation while adding recovery and consent
guarantees. Browser QA exercises real forms; live research uses the production
pipeline and both budget gates. The $0.022986 run brings accounting to $0.514115
and exposes a general-only inbox instead of claiming a requested contact role.

**Risks / failure modes:** Acceptance is not arrival. General contact is not
confirmed HR/founder/management. Grounding cannot prove all semantic claims. Backup
archives contain a sensitive credential key. Jobs stop at restart; use one process.
New reply claims cannot reconstruct relationships of historical answers sent before
schema 9; inspect old conversations manually.

**How we'd detect it:** Route/storage acceptance, concurrent reply/uncertain-send
tests, backup restore/decryption, shared-budget bridge tests and desktop form/label/
layout checks. Live artifacts remain in ignored `data/research-pilot-v1/workspace-careers-v1/`;
no private contact data is committed.

**When to revisit:** After provider consent and a controlled email round-trip, or
when yield/scaling requires contact-focused discovery, separately budgeted
verification/enrichment, durable workers or multi-user controls.

**Date:** 2026-10-05.

### D-025 - Bound and measure research before production integration

- **Decision:** isolate a CLI pilot in `experiments/`, with a fixed $1 ledger,
  four $0.20 brief/method allocations and $0.10 shared planning allowance.
- **Context:** the operator asked to test cost, limits and lead quality first.
- **Alternatives considered:** building onboarding immediately would hide
  retrieval economics; a large research report would not measure usable contacts.
- **Why this one:** compare Search/Extract and FindAll preview using the same
  assessment and evidence gates, with resumable requests and no campaign writes.
- **Risks / failure modes:** preview has low recall; quotations can be true to
  a page but irrelevant; pricing can change; a failed request can have unknown cost.
- **How we'd detect it:** durable ledger, source quotes, pending manual review,
  offline fault tests and actual provider usage separated from tariff estimates.
- **When to revisit:** after a small live comparison and human review; before
  moving provider access into production ports/adapters or increasing volume.
- **Date:** 2026-10-03.

One entry per decision, newest last. Every entry uses the template below. A
decision is not "done" until it is written here.

Statuses: `active` · `superseded by D-nn` · `reversed`

---

## Template (copy for each new entry)

### D-000 — <short title>

- **Status:** active
- **Date:** YYYY-MM-DD
- **Decision:** what we chose, stated in one sentence.
- **Context:** the problem and the constraints in force at the time.
- **Alternatives considered:**
  - *Option A* — rejected because …
  - *Option B* — rejected because …
- **Why this one:** the deciding factors.
- **Risks / failure modes:** what can go wrong as a result of this choice.
- **How we'd detect it:** symptoms, logs, metrics, tests that would catch it.
- **When to revisit:** the change in circumstances that would reopen this.

---

### D-001 — Dedicated private repository

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** the project lives in `AkshGoyal/Outreach-Agent`, private for now,
  to be made public at Phase 9 when it is portfolio-ready.
- **Context:** work began in `AkshGoyal/AkshGoyal`, which is GitHub's special
  profile repository — its `README.md` renders on the GitHub profile page.
- **Alternatives considered:**
  - *Build in the profile repo* — rejected: an application there crowds out the
    profile README, and it is an unnatural place for a reviewer to find a
    project. The initial commit was reverted and the branch abandoned.
  - *Public from day one* — rejected for now: a single real recipient row
    committed by mistake would be public and cached before it was noticed. The
    commit history is still preserved and becomes visible when the repo flips.
- **Why this one:** separates the artefact from the profile, and keeps the
  blast radius of an accidental PII commit inside a private repo.
- **Risks / failure modes:** the repo is forgotten in private and never
  published; PII is committed anyway and is merely less exposed, not safe.
- **How we'd detect it:** Phase 9 has "flip to public" as an explicit exit
  criterion; `.gitignore` is the primary PII guard and is in place from the
  first commit.
- **When to revisit:** at Phase 9, or sooner if collaboration is needed.

### D-002 — Email via Zoho Mail on SMTP/IMAP, behind a provider-agnostic mail port

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** send and receive through a paid Zoho Mail mailbox on
  `starthreads.in`, using **SMTP for sending and IMAP for reading**, with all
  mail access confined behind a single internal interface (the "mail port") so
  that the provider is a configuration value rather than an architectural
  commitment.
- **Context:** ~20–30 sends/day, quality over volume, India-centric recipients,
  cost-sensitive but not at the expense of quality. The domain
  `starthreads.in` is owned and carries a live website, but has never sent
  email, so it has no sending reputation in either direction. One mailbox is
  needed, separate from personal mail.
- **Alternatives considered:**
  - *Google Workspace via the Gmail API* — rejected on cost and lock-in.
    ~₹318/user/month incl. GST versus ~₹59–75 for Zoho Mail Lite, roughly 5×.
    Its genuine technical advantage is native `threadId`, which removes the
    need to reconstruct threads from message headers; its push notifications
    are worth little at this volume, where polling every few minutes is ample.
    The advantage was judged not to justify 5× cost plus a proprietary API.
    **Note:** Workspace also speaks SMTP/IMAP, so this rejection is of the
    *Gmail API*, not of Google as a provider.
  - *Transactional ESP (Amazon SES / Resend / Brevo)* — rejected: most
    transactional providers' acceptable-use policies prohibit cold outreach, and
    termination mid-campaign would cost both the channel and the accumulated
    sending reputation. It also splits sending and receiving across two systems,
    making threading harder, while saving none of the DNS work.
  - *Keep the existing personal Gmail address* — rejected: mixes with personal
    mail, cannot align SPF/DKIM to `starthreads.in`, and a `@gmail.com` sender
    undercuts the credibility of B2B manufacturing outreach. Retained only as a
    free way to smoke-test draft quality before spending anything.
- **Why this one:** SMTP and IMAP are open protocols, so the mail port can be
  implemented once and pointed at any provider. Choosing Zoho therefore does not
  foreclose Google — if inbox placement disappoints, the mailbox moves and the
  credentials change, with no code above the port affected. Cheapest real option
  that meets the requirement, and Zoho being India-based is a minor plus for
  DPDP data residency.
- **Risks / failure modes:**
  - **Thread reconstruction is ours to do.** Without a provider thread ID we
    match replies via `Message-ID` / `In-Reply-To` / `References`. Clients that
    strip or mangle these headers, and forwards, can break the chain — the
    result is a reply attributed to the wrong recipient or to none.
  - App password revoked or rotated → every send and fetch fails at once.
  - Bounces arrive as ordinary email to be parsed, not as webhooks, so a
    mis-parsed bounce means a dead address is never suppressed.
  - Zoho throttles or flags the account for outbound volume.
- **How we'd detect it:** an explicit *unmatched replies* queue that a human
  sees — a reply that cannot be attributed is never silently dropped; a
  send-failure alarm on authentication errors; a test suite of recorded raw
  RFC822 replies, including header-stripped and forwarded ones, asserted against
  expected attribution.
- **When to revisit:** if unmatched replies exceed a small fraction of inbound,
  if inbox placement to Gmail recipients proves poor, or if volume rises to the
  point where bounce webhooks and dedicated-IP reputation start to matter.

### D-003 — Send from the root domain, single mailbox

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** outreach sends from a mailbox on the root domain
  `@starthreads.in`, not from an isolated sending subdomain.
- **Context:** one mailbox is wanted for now, and no other business email exists
  on the domain. The domain already serves a live website at the matching
  address.
- **Alternatives considered:**
  - *Isolated subdomain (`outreach.starthreads.in`)* — rejected for now: its
    purpose is to keep a reputation problem away from ordinary business
    correspondence, and there is no ordinary business correspondence on this
    domain to protect. It also costs credibility, because the sending address
    would no longer match the website a buyer checks.
  - *A separate lookalike domain* — rejected: full isolation, but zero domain
    age, a longer warm-up, and a sender address that does not match the website
    is a trust cost with no offsetting benefit at this volume.
- **Why this one:** at 20–30/day with every draft human-reviewed, the chance of
  burning the domain is low, and address–website alignment is worth real money
  in B2B credibility.
- **Risks / failure modes:** if reputation is damaged, it is the root domain's,
  and any business email later put on `starthreads.in` inherits it. The website
  itself is unaffected — web and mail reputation are separate systems.
- **How we'd detect it:** DMARC aggregate reports (start at `p=none` to
  monitor), bounce and complaint rates, and periodic seed-address inbox
  placement checks.
- **When to revisit:** before putting the business's day-to-day email on this
  domain, or at the first sign of reputation damage. Moving to a subdomain later
  means new DNS records and a fresh warm-up, not a code change.

### D-004 — Emails are sent as Aman Goyal, from `aman@starthreads.in`

- **Status:** superseded by D-008
- **Date:** 2026-09-19
- **Decision:** the single mailbox is `aman@starthreads.in`, and outreach is
  written and signed in the voice of Aman Goyal, the director of the business —
  not in the voice of the person operating the tool.
- **Context:** Aksh builds and runs the tool; Aman is the director. In B2B
  manufacturing outreach the reply is usually a sample request, a price
  enquiry, or a request for a call — all things the director answers. One
  mailbox only (D-003 established it sits on the root domain).
- **Alternatives considered:**
  - *`aman.goyal@starthreads.in`* — perfectly viable, and worth switching to if
    a second Aman ever joins. Rejected for now as marginally more formal;
    first-name-only at a small manufacturer reads as the person who has been
    there longest, which is the intended signal.
  - *`aksh@starthreads.in`* — rejected: the operator has less authority to
    negotiate, and a buyer's reply would need forwarding to the person who can
    actually answer it, adding a hop and a delay to the most valuable moment in
    the whole funnel.
  - *Role address (`sales@`, `info@`, `hello@`)* — rejected: role addresses read
    as blast mail, are filtered more aggressively, and get materially lower
    reply rates than a named human.
- **Why this one:** the sender is the person who can act on the reply, and a
  named director on a domain that matches the company website is the strongest
  credibility signal available at zero cost.
- **Risks / failure modes:**
  - **The operator and the sender are different people.** Drafts written in
    Aman's voice need approval from someone with authority to speak as him.
    This is the main risk this decision introduces.
  - Replies land in Aman's mailbox. If nobody triages them promptly, an
    interested buyer goes unanswered — **worse than never having sent at all**,
    because it spends the first impression and the domain's reputation for
    nothing.
  - Aman's name and identity are attached to every send, so a bad draft is his
    reputational cost, not the tool's.
- **How we'd detect it:** the review step records who approved each draft; the
  age of the oldest unanswered reply is a visible metric; Phase 7 routes
  anything needing a human into an explicit queue rather than leaving it in a
  mailbox nobody is watching.
- **When to revisit:** if Aman is not in practice available to review or
  respond; if a second sender is added; or if the job-search use case (which
  sends as Aksh) is brought into the same system.

### D-005 — Python as the language and runtime

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** the whole tool is written in Python.
- **Context:** one operator, ~30 sends/day, a mail layer that must speak SMTP
  and IMAP (D-002), and schema-validated LLM output as a stated principle.
- **Alternatives considered:**
  - *TypeScript / Node* — rejected: email is the riskiest part of this system
    (D-002), and Node has no standard-library IMAP or MIME parsing, so the
    riskiest layer would rest on third-party packages. Its main advantage — one
    language if the review UI grows — is largely neutralised because a
    server-rendered Python UI can serve the review screen.
  - *Go* — rejected: excellent deployment story, but the weakest LLM ecosystem
    of the three, third-party mail libraries, and not a stack the operator
    maintains.
- **Why this one:** `smtplib`, `imaplib` and `email` are standard library, so
  the mail port costs almost nothing to build and nothing to maintain. Pydantic
  gives enum-constrained, schema-validated model output directly. It is also the
  stack already in use elsewhere, and the one a reviewer expects for this work.
- **Risks / failure modes:** packaging for a VPS is fiddlier than a single
  binary; dependency drift without a lockfile.
- **How we'd detect it:** a lockfile (`uv`) pins versions; the test suite runs
  from a clean checkout with no keys, which catches environment drift.
- **When to revisit:** if the review interface becomes a rich client
  application rather than a server-rendered page.

### D-006 — SQLite for storage

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** all state lives in a single SQLite database file.
- **Context:** one user, ~30 sends/day, run locally for now. Invariant I-2
  requires that a suppression check and the send it guards cannot come apart.
- **Alternatives considered:**
  - *PostgreSQL* — rejected for now: real concurrency and the obvious
    destination if this is ever hosted for several users, but it needs a
    container or a paid instance today for a problem that does not exist yet.
  - *JSON / CSV files* — rejected outright: no transactions, so a crash between
    "check suppression" and "record the send" leaves inconsistent state and
    **I-2 becomes unenforceable**. That alone disqualifies it.
- **Why this one:** real transactions make I-2 enforceable rather than
  aspirational; zero ops, zero cost, and backup is a file copy. At this volume
  it will never be the bottleneck.
- **Access method:** explicit SQL behind a thin repository layer, rather than an
  ORM — so that what is read is what runs. *(Recommended; pending confirmation.)*
- **Risks / failure modes:** single-writer, so a web UI and a send job running
  at once need WAL mode and care. The file contains recipient PII, drafts and
  reply bodies — it is git-ignored, and it needs a backup destination that is
  not a public cloud folder.
- **How we'd detect it:** `database is locked` errors under concurrent access;
  a backup procedure recorded in FAILURE_MAP before the first real campaign.
- **When to revisit:** a second user, hosting, or genuine write concurrency.

### D-007 — Claude (`claude-opus-5`) for drafting, behind an LLM port

- **Status:** active
- **Date:** 2026-09-19
- **Decision:** drafting uses Anthropic's `claude-opus-5`, and every LLM call
  goes through a single wrapper module (invariant I-6), so the provider and
  model are configuration rather than architecture.
- **Context:** ~900 drafts/month at roughly 2,000 input and 600 output tokens
  each. Writing quality is the stated priority. Measured monthly drafting cost:
  Opus 5 ≈ $22.50, Sonnet 5 ≈ $9.00, Haiku 4.5 ≈ $4.50, Gemini 3.7 Flash ≈
  $3.38, GPT-5.6 Terra ≈ $10.08.
- **Alternatives considered:**
  - *Google Gemini* — cheapest and already familiar, but the saving is ~$19/month
    on the single decision where quality is the entire product, and the current
    Flash rate is introductory and doubles on 1 Jan 2027.
  - *OpenAI* — mid-range on both cost and familiarity, with nothing decisive in
    its favour here.
- **Why this one:** the product *is* writing quality, so this is the one place
  not to economise; the total spread between best and cheapest is about $19/month,
  less than the value of one good reply from a buyer. Structured outputs with
  strict schemas give the enforced-at-schema-level validation the brief requires.
  Secondary: the operator's other public projects run on Gemini, so this
  diversifies rather than repeats.
- **Risks / failure modes:** provider outage stops drafting (approved drafts
  still send); price changes; a prompt tuned for one model degrading on another.
- **How we'd detect it:** explicit timeouts and retries on every call; cost
  tracked per run; drafts reviewed by a human before sending, so quality
  regressions are caught before a recipient sees them.
- **When to revisit:** if cost rises materially with volume, or if measured
  draft quality does not justify the tier. Prompt caching is the first lever to
  pull before changing model — roughly 1,500 of the 2,000 input tokens per draft
  are identical across a batch.
- **Deferred:** the model used for *reply classification* is not decided. See
  Q16 — it costs between $0.27 and $1.35/month either way, and the decision is
  better made in Phase 7 against real replies.


### D-008 — Emails are sent as Aksh Goyal, from `aksh@starthreads.in`

- **Status:** active (supersedes D-004)
- **Date:** 2026-09-20
- **Decision:** the mailbox is `aksh@starthreads.in`, and outreach is written
  and signed by Aksh Goyal — the person who also builds and runs the tool.
- **Context:** the mailbox was purchased as `aksh@`, not `aman@`. D-004 had
  recommended the director's name for authority; the operator chose their own.
- **Alternatives considered:**
  - *`aman@starthreads.in` (D-004)* — the director's name carries more weight in
    a price or sample negotiation. Not chosen: it splits the person who sends
    from the person who operates, and everything below follows from closing
    that split.
- **Why this one:** it collapses the biggest open question in the project.
  Under D-004 the drafts went out in one person's name while another approved
  them, which raised who signs off on each draft, who watches the inbox, and
  what the review screen has to look like for a non-technical approver. With
  one person doing all of it, those questions disappear rather than being
  answered. Q15 is closed by this decision, not resolved by it.
- **What it costs:** less positional authority. A buyer's reply asking for a
  price or a sample may still need the director's decision, so the fast path
  from reply to answer is a conversation, not a forward. At 20-30 sends/day
  with every draft reviewed, that is a small and manageable cost.
- **Risks / failure modes:** an enquiry that needs the director stalls waiting
  for him; recipients who check the website may not recognise the sender's name
  against the business.
- **How we'd detect it:** the age of the oldest unanswered reply, once Phase 7
  routes replies into a queue.
- **When to revisit:** if reply rates are poor and the sender's standing looks
  like the reason, or if a second mailbox is added. Changing it is one line in
  `.env` plus a new mailbox — no code change.

### D-009 — MCP belongs on our own data, not in the send path

- **Status:** active
- **Date:** 2026-09-20
- **Decision:** MCP (the protocol that lets an AI assistant call tools) stays in
  the plan, but on the *reading* side: a server that exposes this tool's own
  database and drafts, so the operator can ask an assistant "what replies came
  in today, and which need me?" Sending stays in ordinary code.
- **Context:** Zoho ships a first-party MCP offering and several community Zoho
  Mail servers exist, so routing sends through MCP is genuinely possible.
- **Alternatives considered:**
  - *Send through a Zoho Mail MCP server* — rejected for the send path.
    Sending is not a judgment call; it is "this exact text, to this exact
    address, now". Putting it behind an assistant moves a mechanical step into
    the unpredictable layer, against the project's own principle that the model
    is called only where judgment is needed.
    More seriously, it breaks I-2. Both suppression guards work because the
    send goes through our code: our function refuses, and our database refuses.
    A send that happens inside someone else's server cannot be vetoed by our
    trigger — we would be trusting a report that an email went out rather than
    controlling whether it does.
    It also saves the cheap part. Sending is ~20 lines of standard library; the
    expensive parts are suppression, pacing, thread matching, bounce handling
    and crash-safety, and MCP supplies none of them.
  - *No MCP at all* — rejected: the reading side is a real convenience, and the
    data is ours, so none of the objections above apply to it.
- **Why this one:** it takes the useful half of the idea and leaves the half
  that would cost control of the send path.
- **Risks / failure modes:** an MCP server over our database is a read path
  into recipient PII — it needs to be local and read-only, not exposed.
- **How we'd detect it:** it does not exist yet; when built, it is
  read-only by construction and has no send capability to misuse.
- **When to revisit:** if the reading server proves useful and a genuinely
  read-only, auditable send path ever becomes available. The send-path
  objection is about control, not about MCP as a technology.


### D-010 — A local web interface, alongside the command line

- **Status:** active
- **Date:** 2026-09-20
- **Decision:** a small web application served on `127.0.0.1`, calling exactly
  the same functions as the command line. Both entry points stay.
- **Context:** the operator asked for something friendlier than a terminal. The
  main job the interface has to support is reading and editing prose — draft
  emails — and judging whether each one is worth sending.
- **Alternatives considered:**
  - *Command line only* — rejected: reviewing and editing written English in a
    terminal is unpleasant enough that the review step would get skipped, and a
    review step that gets skipped is worse than none, because it creates false
    confidence.
  - *A terminal interface (curses)* — rejected for the same reason, with the
    extra cost of building widgets a browser gives for free.
  - *A hosted web application* — rejected: recipient data is PII, and hosting it
    means it leaves the operator's machine and needs authentication, transport
    security and a privacy posture, for one user on one laptop.
- **Why this one:** a browser is the right tool for reading and editing prose;
  running locally means no PII leaves the machine and there is nothing to
  secure; server-rendered HTML means no separate frontend to build or deploy.
  Critically, the web app calls the same code as the command line, so the two
  are two faces on one system rather than two implementations that can drift.
- **Risks / failure modes:** the web app is a second composition root, so the
  dependency rule needs a second named exception — done, by path, in
  `tests/test_architecture.py`. Binding to `0.0.0.0` instead of `127.0.0.1`
  would expose recipient data to the local network; the default is the loopback
  address and changing it takes a deliberate flag.
- **How we'd detect it:** the architecture test fails if any other file starts
  naming adapters; route tests cover every page.
- **When to revisit:** if a second person ever needs access, at which point
  hosting, authentication and D-006's storage choice all need reconsidering
  together.

### D-011 — Grounding by citation plus a deterministic specifics check

- **Status:** active
- **Date:** 2026-09-20
- **Decision:** the model returns a subject and a list of sentences, each naming
  the evidence field it drew on. Ordinary code then checks that **every
  specific detail — every name, place, number and product term — appears in
  that recipient's evidence, their company name, our own approved copy, or the
  sender's name.** Anything else blocks the draft. Sentences that are about the
  recipient but contain nothing checkable are flagged for the operator to keep
  or cut, rather than passed or blocked.
- **Context:** an email that invents a fact about a recipient is worse than a
  generic one — generic gets deleted, wrong gets remembered. The brief requires
  this to be enforced structurally, not by asking the prompt nicely.
- **Alternatives considered:**
  - *Write freely, then have a second model check it* — rejected: it uses a
    model to check a model on a judgement call, and the failure that matters
    (missing a fabrication) is silent. You would never know it happened.
  - *Slot-filling — the model never types the facts, code assembles them* —
    rejected: completely reliable, but the emails read stiffly, and stiffness
    is the thing the whole project exists to avoid.
- **Why this one:** the damaging errors are invented *specifics*. A specificity
  check is plain code — no second model call, no paraphrase problem, no silent
  misses — and it catches exactly that class, the same way every time.
- **The operator's addition, and it closed a real hole:** a third outcome for
  claims that are about the recipient but unverifiable. My original design
  passed those silently, which was the weakness I had acknowledged. They are
  now surfaced as a decision rather than a guess.
- **Risks / failure modes:**
  - **The known gap:** a word is read as a specific if it is capitalised *and
    not the first word of the sentence*, or contains a digit anywhere. So an
    invented place name used as the opening word of a sentence is not caught by
    the capitalisation test. Checking first words instead needs a dictionary we
    do not have; the alternative is a hand-kept list of every common English
    opener, which produces false alarms forever — and a checker that cries wolf
    stops being read. Recorded as a test, `test_a_lie_as_the_very_first_word_slips_through`.
  - Vague fabrications ("your business seems well established") are not caught,
    by design — they go to the operator as a maybe.
  - False alarms erode trust, so three were fixed on sight: the subject leaking
    into the body, greetings landing in the maybe pile, and the sender's own
    name being flagged as an invented fact.
- **How we'd detect it:** an adversarial test set of drafts containing
  deliberate lies — invented cities, invented people, invented certifications,
  invented founding years, and a fabricated citation — every one of which must
  be rejected.
- **When to revisit:** if the maybe pile is consistently large (the prompt is
  producing waffle), or if a fabrication ever reaches a recipient — in which
  case the first question is whether it was sentence-initial.

### D-012 — OpenRouter as the model provider, model chosen by measurement

- **Status:** active (supersedes the provider half of D-007; the grounding
  design in D-011 is unaffected)
- **Date:** 2026-09-20
- **Decision:** drafting goes through OpenRouter, with the model as a setting.
  **Which** model is deliberately not fixed here — it is to be chosen by
  running the same contacts through several and reading the results.
- **Context:** the operator has an OpenRouter account and asked for a cheap,
  good model, explicitly requesting an unbiased answer.
- **Why not name a model in this entry:** because at the current volume the
  cost argument does not exist. Seven contactable leads is 7 drafts; every
  candidate model costs between ₹1 and ₹15 to run the whole list. Choosing on
  price would be optimising a rounding error. And the quality question has a
  *measurable* answer specific to this project — the grounding checker already
  counts grounded, unverifiable and unsupported lines per draft, so two models
  can be compared on this campaign's real contacts rather than on a benchmark
  written by someone else.
- **Alternatives considered:**
  - *Direct Anthropic only (D-007)* — not rejected, just narrowed: the adapter
    still exists and works, and `OUTREACH_LLM_PROVIDER=anthropic` switches back.
    OpenRouter wins on being able to compare models at all.
  - *Picking the cheapest model outright* — rejected: the saving is a few
    hundred rupees a month at full volume and under ₹15 today, against a
    product whose entire value is whether the writing is good.
  - *Picking the most capable model outright* — rejected for the same reason in
    reverse: it assumes the answer instead of measuring it, and a cheaper model
    may well be indistinguishable on emails this short and this constrained.
- **Risks / failure modes:**
  - **Schema enforcement on OpenRouter is per provider, not per model.** The
    same model served by a different provider may treat the JSON schema as a
    suggestion and return prose. `require_parameters: true` forces routing to
    providers that enforce it; without that the failure looks like a model
    problem when it is a routing problem.
  - Strict mode rejects optional properties, which Pydantic emits by default —
    handled by `_strict_schema`, tested directly.
  - OpenRouter adds ~5.5% on card credit top-ups.
  - A model swapped for cost may quietly produce more unsupported lines. The
    checker makes that visible rather than silent.
- **How we'd detect it:** `outreach draft --model a --model b` prints a verdict
  tally per model on the same contacts. A model that waffles shows up as a
  large unverifiable count; one that invents shows up as unsupported.
- **When to revisit:** once there is real volume (Phase 3.5), when the cost
  difference stops being a rounding error, and after the first real replies
  show which drafts actually got answered.

### D-013 — GPT-5.6 Luna as the default drafting model, by measurement

- **Status:** active (fills in the model D-012 deliberately left open)
- **Date:** 2026-09-23
- **Decision:** `openai/gpt-5.6-luna` is the default model.
- **Context:** the first real run, on three real contacts from the leads list,
  compared models with the grounding checker as the scorer.
- **Measured result (21 lines each):**

  | Model | grounded | maybe | unsupported | cost at 900 drafts/month |
  | --- | --- | --- | --- | --- |
  | GPT-5.6 Luna | 13 | 1 | **0** | ~₹90 |
  | Claude Haiku 4.5 | 11 | 7 | 2 | ~₹400 |
  | Gemini 3.1 Pro | — | — | — | model ID rejected by OpenRouter |

- **Why this one:** it was both the cheapest and the best on the only measure
  that matters here — zero invented claims, almost no vague filler, and short.
  That confirms the hypothesis in D-012 that this is an easy task: facts are
  handed over, the schema constrains the shape, and a checker catches
  mistakes, so a cheap model is not at a disadvantage.
- **Alternatives considered:** *Claude Haiku 4.5* — more persuasive prose, but
  ran past the length asked for, produced seven maybes, and merged two field
  names into one citation. Not rejected permanently; easy to re-test.
- **Honest caveat:** reading the drafts, not the scores, Luna's weaknesses were
  real: it pasted raw cell text ("(12 t)", "washing/processing"), used stiff
  wording lifted from the prompt, and signed off as the company. All three
  were prompt faults, fixed in prompt version 2. **The comparison should be
  re-run on v2** before treating this as settled.
- **Risks / failure modes:** a cheap model may degrade faster on unusual
  evidence; OpenRouter model IDs change.
- **How we'd detect it:** the per-model tally in `outreach draft`.
- **When to revisit:** after re-running on prompt v2, and after the first
  real replies show which drafts actually got answered.

### D-014 — At this volume, replies and follow-ups stay manual

- **Status:** replies superseded by D-023; follow-ups still manual
- **Date:** 2026-09-23
- **Decision:** v1 ends at sending. Replies are read in the Zoho inbox, and
  follow-ups are written by hand. Reply ingestion, classification and
  automated follow-ups (Phases 7 and 8) are not built.
- **Context:** the operator asked to wind the project up. The real list has
  seven contactable addresses. The unsolved constraint is finding addresses
  (Phase 3.5), not handling replies.
- **Alternatives considered:**
  - *Build Phases 7 and 8 anyway* — rejected: automating the triage of seven
    replies takes longer to build than a person takes to read them for a
    year, and IMAP thread matching is the riskiest code in the plan (D-002).
    Building it before there is volume would be building it against
    imagined replies rather than real ones.
- **What keeps this safe without the automation:** the do-not-contact list is
  a web page with a form. A reply saying "unsubscribe" is added there by hand,
  and both suppression guards then apply to every future send.
- **Risks / failure modes:** an unsubscribe reply is read and not added to the
  list, and a later campaign writes to that person again.
- **How we'd detect it:** it would arrive as a complaint. Before any second
  campaign, read every reply to the first.
- **When to revisit:** as soon as Phase 3.5 produces enough addresses that
  reading replies by hand stops being quick — the point at which this
  decision becomes the bottleneck.

### D-015 — Nothing is approved while any line is unsupported, including edits

- **Status:** active
- **Date:** 2026-09-23
- **Decision:** a draft cannot be approved while any line in it — including
  a line a person typed during review — contains a specific that is not in
  the recipient's evidence or the campaign copy.
- **Alternatives considered:**
  - *Trust the operator's edits* — rejected: the operator is the authority on
    the truth, but a typo, a half-remembered name or a confusion between two
    buyers is exactly how a wrong fact reaches a recipient. The rule is only
    worth anything if it holds all the way to the send.
  - *Warn but allow* — rejected: a warning that can be clicked past becomes a
    warning that is clicked past.
- **Why this one:** if the operator knows something true that is missing, the
  fix is to add it to the spreadsheet, where it then becomes evidence for
  every future draft rather than a one-off edit.
- **Cost:** occasional friction when a true fact is not in the data yet.

### D-016 — Compliance footer, reply-to-unsubscribe, and no send button

- **Status:** active, except the header and footer wording — superseded by D-018 — and
  "no send button" — superseded by D-022
- **Date:** 2026-09-23
- **Decision:** every email carries the sender's name, company and physical
  address and an instruction to reply "unsubscribe", plus a
  `List-Unsubscribe: mailto:` header. The footer is added at send time, not
  stored in the draft. Sending runs only from the terminal, is a dry run
  unless `--really` is given, and refuses to start without a physical address.
- **Context:** the brief lists sender identification, a physical address, a
  working opt-out and honoured opt-outs as the baseline for outreach, with
  recipients mostly in India under the DPDP Act.
- **Alternatives considered:**
  - *An unsubscribe link* — rejected for now: it needs a public web endpoint,
    which means hosting something on the internet that can write to the
    suppression list. A reply is a working opt-out with nothing exposed.
  - *Footer written by the model* — rejected: it could be edited, forgotten or
    worded differently each time.
  - *A send button in the web page* — rejected: a single click would send, a
    run of emails a minute apart would hang the request for minutes, and
    there is no safe way to stop part-way. The web page shows the plan and
    the command instead.
- **Risks / failure modes:** the reply-based opt-out depends on someone
  reading replies (see D-014).
- **When to revisit:** if volume grows enough that manual unsubscribe handling
  is unreliable — at which point a hosted unsubscribe endpoint, with its own
  security review, becomes worth building.

### D-017 — A second way to send, fenced so it cannot reach a prospect

- **Status:** active
- **Date:** 2026-09-24
- **Decision:** `outreach send-test --to <address>` sends one email through the
  real Zoho connection, bypassing import, drafting and review. It refuses any
  address on the do-not-contact list and any address belonging to a contact
  in any campaign, marks the subject [TEST], and writes nothing.
- **Context:** the operator had not yet connected Zoho at all. Testing the
  connection the only existing way meant importing a fake contact, drafting
  it with a model call, approving it and sending — and that fake contact then
  stayed in the real campaign.
- **Why this does not weaken I-2 or the one-email rule:** the fence is by
  address, not by trust. A prospect's address is refused, so this cannot be
  used to send an unreviewed email to anyone the campaign is aimed at, or a
  second email to someone already written to.
- **Alternatives considered:**
  - *A hidden test campaign* — rejected: the one-email-per-contact rule would
    block a second test to the same address, and DNS problems usually take
    several tests to fix.
  - *No test path* — rejected: the first real email a prospect receives would
    also be the first email the system had ever sent.
- **Risks / failure modes:** an operator types a prospect's address that was
  never imported. It would send a [TEST] email to them. The subject marking
  limits the damage; the fix is not to do that.
- **`--draft N`:** sends a real draft to yourself exactly as the prospect
  would get it, so a specific email can be read in a real inbox before
  approving it.


### D-018 — Read like a person, not a mailing list

- **Status:** active (supersedes the header and footer wording in D-016)
- **Date:** 2026-09-24
- **Decision:** no `List-Unsubscribe` header, and the footer is a plain
  signature — name, company, address — ending "If this isn't relevant to you,
  just reply and say so, and I won't write again."
- **Context:** the first real test send reached Gmail but landed in the
  Promotions tab rather than Primary. Arriving at all means authentication
  worked; Promotions is a content classification. Two things in the email
  were mailing-list signals, and both were my choices in D-016: the
  List-Unsubscribe header, and the newsletter wording "if you would rather not
  hear from us, reply 'unsubscribe'".
- **Why this is still compliant:** the sender is identified by name, company
  and physical address, and the recipient is told plainly how to opt out. Any
  reply that says no — in whatever words — goes on the do-not-contact list.
- **What is given up:** Gmail's own unsubscribe button. Gmail requires the
  header only of senders of more than 5,000 emails a day; this sends ten.
- **Honest limit:** Gmail's classifier is not public. This removes the signals
  we control; it cannot guarantee Primary. A brand-new domain's first email to
  someone it has never written to can land in Promotions regardless, and the
  thing that fixes that over time is replies.
- **How we'd detect it:** `send-test` to a personal Gmail after each change,
  one change at a time; mail-tester.com for a score.
- **When to revisit:** well before volume approaches thousands a day, when the
  header becomes a requirement rather than a cost.

### D-019 — The operator's own closing, word for word; the model writes the opening

- **Status:** active
- **Date:** 2026-09-24
- **Decision:** a campaign may have a fixed closing in
  `campaigns/<id>.closing.md`, added word for word under every email. When it
  exists the model writes only the opening — greeting, a one-line
  introduction, and one checked point about the recipient that leads into the
  closing — using a separate prompt (`prompts/draft_opening.md`, v3).
- **Context:** the operator supplied a specific ending — sample offer, website,
  request for the courier address, thanks, and a two-person signature with
  company registration details — and asked that emails be more thoroughly
  checked and not repeat themselves.
- **The new check (`core/flow.py`):** any sentence the model writes that does
  the closing's job — offers samples, gives the website, asks a question,
  thanks them, signs off — or shares three or more distinctive words with a
  closing paragraph, or says what an earlier sentence said, is removed and the
  reason shown. It does not block approval: nothing in it is false, it is
  redundant. *(Superseded by D-020: a repeat left in the text now does block
  approval and sending.)*
- **One line added that the operator did not write:** "If this is not
  relevant to your unit, simply reply and let us know, and we will not write
  again." The closing identifies the sender thoroughly, but had no way to opt
  out, which the brief lists as a baseline requirement. Added by code under
  the closing, so it cannot be dropped by editing the file.
- **Noted once, not overridden:** the closing contains a link. Links nudge
  mail toward Promotions; a single link to the sender's own domain is the
  mildest kind. Kept, as the operator's call.
- **Where the files live:** on the operator's machine only. Campaign files
  other than the two examples are git-ignored — a real closing holds mobile
  numbers and registration details — and a test pins that.
- **Risks / failure modes:** the flow check can remove a legitimate sentence
  that happens to use a closing word ("dispatch", "sample") in another sense.
  It is shown with its reason, and can be restored by editing in review.

### D-020 — A repeat is checked where the email leaves, not only where it is written

- **Status:** active
- **Date:** 2026-09-24
- **Decision:** the flow check from D-019 runs again, against the closing as
  it is *now*, on the exact text that would go out — at every exit:
  - **review page:** opening a draft that repeats says which lines to delete;
  - **approval:** refused while any line repeats the closing or itself;
  - **`send` / send page:** an approved draft that repeats is held back, with
    the line and the reason;
  - **`send-test --draft`:** refused before connecting to Zoho.
  `plan()` takes the closing and campaign copy as required arguments, so a
  caller cannot forget them and let a repeat through unseen.
- **Context:** the first real test email carried its own sample offer, a
  question and "Best regards", then the closing said all three again. The
  draft had been written before the closing file existed. D-019's check ran
  only at drafting time, so it never saw the combination.
- **Also:** `draft --save --redraft` rewrites everyone not yet emailed and sets
  their older drafts aside; a preview (`draft` without `--save`) now prints
  one whole email exactly as it would arrive, closing and opt-out included —
  a reference to judge the flow by before drafting everyone.
- **Alternatives considered:** remove repeated lines silently at send time —
  rejected: it would send text nobody approved. Stamp each draft with the
  closing it was written against and refuse any mismatch — rejected for now:
  it would also stop drafts whose text is fine, and the content check catches
  the actual failure.
- **Risks / failure modes:** a false positive now blocks rather than being
  restorable. The reason is always shown, and rewording the line clears it.

### D-021 — "Approve all", only for drafts that pass every check; `serve` opens the browser

- **Status:** active
- **Date:** 2026-09-24
- **Decision:** the drafts page has an "Approve all that pass every check"
  button. It re-checks each draft in review against the campaign copy and
  closing as they are now, saves the fresh result, and approves only the clean
  ones. A draft with a "maybe" line, an unsupported line or a repeat stays in
  review, and the page says how many of each were left. It asks for
  confirmation, and sends nothing.
- **Context:** the operator asked for a way to approve a batch without
  opening each draft.
- **Why not everything:** a "maybe" line is the operator's call by design
  (D-011); a bulk click is not a decision about it. Unsupported lines and
  repeats cannot be approved one at a time either (D-015, D-020), so bulk
  approval must not be a way around that.
- **What does not change:** nothing is ever sent without an approved draft
  *and* `outreach send --really` typed by hand. There is no schedule and no
  automatic send (D-016).
- **Also:** `outreach serve` opens the page in the default browser a second
  after starting; `--no-browser` only prints the address, for Codespaces or a
  machine with no screen.

### D-022 — Everything from the browser, including sending

- **Status:** active (supersedes the "no send button" part of D-016)
- **Date:** 2026-09-25
- **Decision:** the whole daily loop runs from the web pages, with no
  terminal: set up and test the connections, write the offer and ending,
  import, draft, review, send a test to yourself, and send. Sending starts
  from a button, runs in the background, shows live progress, and can be
  stopped between emails.
- **Context:** the operator asked for a platform anyone can use, "not me
  writing commands in the terminal".
- **How D-016's three objections are met:**
  - *one click would send* → the button names the count and asks for
    confirmation, under a preview of the exact first email;
  - *a request would hang for minutes* → a background thread does the
    sending; the page refreshes itself and can be left;
  - *no safe way to stop* → Stop is checked before every email, and ends the
    wait between emails at once. It never cuts an email off halfway.
- **Unchanged guards:** the same `plan` and `dispatch` as the terminal: only
  approved drafts that pass every check, today's cap, nobody written to twice,
  the do-not-contact list checked at the moment of sending. One run at a time,
  so two runs can never both see someone as "not yet written to".
- **Risks / failure modes:** closing the tool mid-run stops sending. An email
  that was being handed to Zoho at that instant is left `pending` and, as
  before, never sent again automatically.
- **Also:** the offer and the ending are edited in the browser (still saved
  only in `campaigns/` on this computer); campaign ids used as file names are
  restricted to lower-case letters, digits, `-` and `_`, so a form cannot
  write outside that folder.

### D-023 — Replies are read, matched, sorted and acted on — safely

- **Status:** active (supersedes the replies half of D-014)
- **Date:** 2026-09-26
- **Decision:** the tool reads the Zoho inbox over IMAP — on a button, and
  every 10 minutes while `serve` is running — and for each reply to an email
  we sent: matches it to the company, sorts it (wants samples, interested,
  question, not interested, out of office, bounced, other), pulls out the
  postal address, contact person and phone if the reply gives them, and
  suggests an answer. The Inbox page shows them; an answer is sent from there,
  in the same thread, only when a person presses Send.
- **Context:** 10 real emails went out; replies are arriving, and an opt-out
  must be honoured quickly. The operator chose replies before research.
- **Rules:**
  - **Read-only inbox.** Opened read-only, bodies fetched with BODY.PEEK:
    nothing is marked read, moved or deleted.
  - **Only replies are stored.** A message is kept only if it matches an email
    we sent — by thread headers, by the Message-ID quoted in a bounce, by the
    sender's address, or (kept unattributed, for a person — I-4) by subject.
    The operator's ordinary mail is never stored or sent to a model.
  - **Code, not the model, decides the risky cases.** Bounces are recognised
    from the sender and delivery-status text; permanent (5.x.x) ones suppress
    the address, temporary (4.x.x, "delayed") ones don't. Out-of-office is
    recognised from the Auto-Submitted / X-Autoreply headers.
  - **Details are grounded.** A postal address, contact person or phone the
    model pulls out is kept only if it appears word for word in the reply.
  - **Act only in the safe direction.** "Not interested" and hard bounces go
    on the do-not-contact list at once. Nothing is ever sent automatically.
    Answers go through `send_message`, so both suppression guards apply.
  - **A failed reading isn't lost:** the reply is kept as "not read yet" and
    read again at the next check.
- **Schema v4:** a `reply_triage` table holds the interpretation, separate
  from `replies`, which holds what arrived, unchanged.
- **Risks / failure modes:** a real "yes" misread as "not interested" would
  suppress a lead. The summary and the full reply are on the Inbox page under
  "All", and the do-not-contact page shows the reason; there is no undo in the
  tool, so such a lead is answered from Zoho. A misreading in the other
  direction only costs a person's attention.
- **Needs:** `OUTREACH_MAIL_IMAP_HOST=imappro.zoho.in` in `.env`, and IMAP
  access switched on in Zoho Mail (Settings → Mail Accounts → IMAP Access).

### D-024 — Research: our own agent, Parallel for search and page reading, any published contact

- **Status:** active — to be built next
- **Date:** 2026-09-26
- **Decision:** the research layer (docs/PLATFORM_PLAN.md §1–3) is our own
  agent loop — plan searches, find companies, read their pages, pull out facts
  with quotes, check every contact in code — using **Parallel's Search API**
  ($1 per 1,000 fast searches, with a free monthly allowance) and **Extract
  API** ($1 per 1,000 pages, JavaScript and PDFs included), behind a search
  port so another engine can be added.
- **Contacts:** any contact published on the web — general addresses and
  named people's work addresses — each kept with the page it was found on.
  Never guessed from a pattern such as firstname@company: guessed addresses
  bounce, and bounces damage the domain's standing with Gmail and Zoho.
- **Context:** the operator chose option A, asked for "any contacts we can
  find", and pointed to Parallel as cheaper than Tavily — which checks out.
- **Alternatives considered:** Tavily (~$8 per 1,000 after 1,000 free a month),
  Serper (cheapest, Google results, but snippets only — a candidate second
  engine), Brave ($5 per 1,000, no free tier), Exa ($7 per 1,000), Parallel
  FindAll (a finished list, $0.03–1 per match — kept as a later option).
- **Legal:** named work addresses are personal data under India's DPDP Act.
  Mitigations: published sources only, source recorded, a working opt-out in
  every email, opt-outs honoured at once and permanently. Worth a lawyer's
  look before volume grows.

**Pilot measurement update, 2026-10-03:** the saved pilot branch was recovered
and checked in Cloud. After the expired OpenRouter key was replaced, explicit
recovery preserved the original reservation, with the earlier handoff also
carried conservatively. Four bounded comparisons assessed 15 candidate records
for $0.407160 accounted. All 325 offline tests and lint/format checks pass.
Custom discovery cost less on both briefs; FindAll retrieved more textile
contact text, but identity/ownership errors prevent a verified yield comparison.
Fix source identity and faithful evidence extraction on the saved corpus before
integration or another paid run. D-024 and the multi-campaign navigation plan
remain in place; no verified discovery-method winner or cost per usable lead
has been established. [Comparison](RESEARCH_PILOT_RESULTS.md) and
[recovery record](RESEARCH_PILOT.md#cloud-comparison-completed-2026-10-03).

## D-026 — Integrated research and campaign workspace

**Decision:** Extend the existing FastAPI/Jinja/SQLite tool with durable production
research, reusable reviewed lead lists, encrypted Gmail/Zoho app-password accounts,
and campaign-specific outbound/inbox routing. Use the custom Parallel Search/Extract
loop; retain the completed FindAll comparison as a separate experiment.

**Context:** The operator authorized completing the frontend workflow, preserving
multi-campaign navigation, and selected Gmail plus Zoho. The pilot demonstrated
weak ownership/fit evidence and missed contact footers, requiring source inspection
and explicit lead approval before enrollment.

**Alternatives considered:** A new frontend/backend stack would duplicate existing
review/suppression controls. Promoting FindAll candidates automatically would carry
pilot identity errors into real outreach. Provider OAuth/HTTPS mail APIs would work
on more restricted hosts, but require separately registered provider applications;
this increment keeps the existing portable SMTP/IMAP adapter with app-password setup.

**Why this one:** Reuses existing grounded drafting and paced sending, adds durable
spending admission and cached results, checks literal emails in full company page
text, preserves source provenance, and links approvals through the browser.

**Risks / failure modes:** Public SMTP/IMAP is unavailable in this Codex executor;
provider plans/policies can reject app passwords; loss of the encryption key needs
account reconnection; workers stop when the app stops; ambiguous paid calls or mail
sends require reconciliation. Research caps exclude drafting and inbox AI costs.

**How we'd detect it:** Account verification, request-spending panels, pending send
records, restart warnings, offline workflow/isolation tests and Chromium UI checks.

**When to revisit:** Use OAuth/HTTPS transports for hosts without mail ports; use
queued durable workers and stronger leases before multiple users/server processes.

**Date:** 2026-10-04.

## Cloud browser preview (2026-10-04)

**Decision:** Provide a password-protected GitHub Codespaces launcher for the
existing app, with its exact forwarded hostname and no automatic inbox polling.

**Context:** The operator wants to view progress and understand hosting before
taking the OAuth/deployment step. Codex Cloud has no user-facing preview URL here.

**Alternatives considered:** A localhost URL in Codex is inaccessible from the
operator's browser. Immediate permanent deployment would precede the requested
explanation. An embedded editor preview conflicts with the app's frame protection.

**Why this one:** Reuses the existing Codespaces configuration and app without
provider registration or automatically starting paid inbox classification.

**Risks / failure modes:** Codespaces stop; secrets do not transfer from Codex
Cloud; preview usage may incur GitHub hosting charges. Real actions still need
configuration and their existing explicit approvals.

**How we'd detect it:** Launcher startup, forwarded-host/password/cross-origin
checks, offline web tests and desktop/mobile Chromium checks.

**When to revisit:** Choose a permanent HTTPS host before ongoing campaigns and
provider OAuth activation. The operator requested an explanation before that step.

**Date:** 2026-10-04.

## Interactive phone demonstration (2026-10-04)

**Decision:** Provide a separate browser-local sample-data workflow and a Render
static-site blueprint for iPhone access. Do not expose the real backend or secrets.

**Context:** The operator has an iPhone, does not want Codespaces, and accepted an
interactive demo. Codex has no phone-facing URL and Sites helpers are not installed.

**Alternatives considered:** Screenshots do not let the operator test controls.
iPhone document previews do not reliably execute HTML scripts. Serving the real
Python tool requires a separately connected application host and account setup.

**Why this one:** One HTML file exercises the approval flow with no API spending
or email delivery. The optional static host serves it in Safari without a laptop.

**Risks / failure modes:** This is simulated behavior, not backend integration.
Hosting needs the operator's account connection. The static URL is public sample
content; browser storage is local to the device. No hosting deployment is claimed.

**How we'd detect it:** Explicit demo notices, mobile Chromium workflow checks,
no external network requests, and hosting status supplied by Render after setup.

**When to revisit:** Deploy and test the Python application once a proper host and
provider authentication are configured. Replace demo testing with real integration.

**Date:** 2026-10-04.

## Founder benchmark and in-tool clarification — 2026-10-04

**Decision:** Test publicly listed AI startup founder contacts in Bangalore with
source-backed personalisation; collect campaign preferences in creation/editing
and clarify only missing research-critical details before the search.

**Why:** This matches the operator's immediate test brief without requiring a CV
or extensive vacancy research. The saved frontend plan preserves multi-campaign
navigation. The bounded production baseline plus diagnostic shares the original
$1 ledger and $0.20 arm allowance; no new budget was created.

**Risks and detection:** Public founder contacts may be absent; general inboxes
and wrong-company results must not count as direct contacts. Literal quotes can
still support an embellished summary, so draft facts need semantic review. This
test found zero direct contacts; six facts and three hooks were manually reviewed.

**Revisit:** Integrate explicit contact-role/ownership evidence and campaign intake
into production after this benchmark. See FOUNDER_RESEARCH_RESULTS.md.

## Job-outreach contact fallback — 2026-10-04

**Decision:** Accept published HR/recruiting or named senior-management emails
when a founder address is absent. Label department inboxes explicitly.

**Context:** The operator needs usable campaign recipients and approved the
frontend plan, while the founder-only live test returned no direct contacts.

**Alternatives considered:** Founder-only would miss suitable recruiting channels.
Accepting any company inbox would mix support/sales contacts into job outreach.
Guessing addresses would remove the required source evidence.

**Why this one:** Recruiting inboxes fit job outreach without requiring a named
founder. A manual official-site review can inspect the broadened scope without
resetting the paid pilot's exhausted request limits.

**Risks / failure modes:** Displayed addresses and mailto links can disagree;
publication does not establish delivery. Manual discovery is not automated yield.

**How we'd detect it:** Retain page quotes, compare displayed address/link, flag
mismatches, and require recipient/draft review before launch.

**When to revisit:** Integrate selectable contact roles into approved research
plans and production lead evidence, then measure the automated path separately.

**Date:** 2026-10-04.

## Saved audience before paid research — 2026-10-04

**Decision:** Implement the approved plan's first journey increment in the existing
FastAPI/Jinja app: saved intake, explicit paid planning, editable plan approval,
lead-review stages and mobile navigation.

**Context:** Home previously made a paid request immediately and led with mailbox
setup. The operator approved the frontend design and HR/management alternatives.

**Alternatives considered:** Keeping a single brief form hid contact choices and
cost timing. Replacing the framework or extending the static demo would duplicate
working backend behavior and approval gates.

**Why this one:** Additive SQLite `research_intakes` records retain preferences
without replacing research/campaign identities. A shared intake form reuses real
provider workers; roles feed planning and company searches. Existing runs retain
original search fingerprints.

**Risks / failure modes:** Role preferences do not prove address ownership. A paid
request can remain uncertain. Browser-tab storage may be unavailable or disappear.

**How we'd detect it:** Route tests exercise cost gates, incomplete forms, immutable
started scopes and legacy migration; browser checks cover refresh, mobile controls
and filters. SQLite Save draft works independently of optional browser storage.

**When to revisit:** Continue campaign/list handoff, message/draft/launch/inbox UX
and explicit contact-role evidence, then measure quality on authorised live runs.

**Date:** 2026-10-04.

## Campaign preparation before mailbox setup — 2026-10-04

**Decision:** Implement the approved frontend's campaign/message/draft increment in
the existing app. Save campaign and partial message before account connection;
require an explicit verified identity and complete message before launch. Share
campaign tabs, audience handoff, queue filtering and selected/current-version review.

**Context:** The operator authorised continuing the approved product plan. The old
campaign form required mailbox setup before preparing the audience or message and
hid the next task across unrelated pages. Job-outreach sender skills are not supplied.

**Alternatives considered:** Keeping mailbox-first creation blocks preparation.
Allowing environment fallback for new campaigns risks the wrong sender. A new UI
framework or duplicate campaign model adds integration work without improving gates.
Keeping raw copy as the only editor obscures which sender facts were supplied.

**Why this one:** Additive structured briefs compile into the existing copy/checks;
legacy campaigns remain usable. Approved lists retain provenance, previous outreach
and suppression. Readiness and shared tabs keep context. Selected approval validates
current campaign IDs and retains all evidence checks. Every outgoing email is previewed.

**Risks / failure modes:** Editing identity/content can stale approvals; internal notes
can be mistaken for recipient facts; JSON and files are not one atomic transaction;
queued work still stops with the process. Source-backed text can remain semantically
misleading. OAuth and hosted mail transport are not implemented by this UI work.

**How we'd detect it:** 388 offline tests cover migration, missing-message/account
launch gates, changed approvals, sent identity, scoped approval, stale versions and
note exclusion. Desktop/390px Chromium checks exercise fictional preparation through
launch blocking with no browser errors, overflow or external requests. Human source
review and separately authorised live quality/mail tests remain necessary.

**When to revisit:** Before multiple server processes, implement durable workers
and consistent content persistence; after HTTPS hosting decisions, implement provider
OAuth/transport. Measure role/ownership and lead yield before claiming research quality.

**Date:** 2026-10-04.

## OAuth account connection with HTTPS transport — 2026-10-04

**Decision:** Implement Google and Zoho provider consent plus HTTPS mail adapters in
the existing FastAPI app, retaining app-password SMTP/IMAP. Add an explicit test-to-self
screen with persisted replay/outcome tracking. Keep provider sign-in separate from
workspace login and campaign launch approval.

**Context:** The operator requested real mail testing and OAuth. Cloud has no TCP
mail grants, no IMAP host and no registered OAuth clients/public callback URL. Provider
consent and a controlled test recipient cannot be inferred from environment sender fields.

**Alternatives considered:** OAuth over SMTP would still fail on this restricted host.
Replacing the mail core would risk suppression/pending-send/reply behavior. Treating
configured credentials as verified or sending to a presumed recipient would invent
test evidence and outreach authorization. A static demo cannot receive backend tokens.

**Why this one:** Reuses mail/sending ports, encryption and campaign-specific identities.
Gmail raw MIME and Zoho plaintext/thread APIs support HTTPS-only hosting. Browser-bound
single-use state, Google PKCE, fixed regional endpoints and private token storage protect
consent. Explicit test acceptance is separated from actual inbox delivery.

**Risks / failure modes:** Missing hosting/registration/consent; Google Testing expiry
and restricted-scope verification; Zoho region/plan constraints; mail POST uncertainty;
provider-assigned IDs and lost receipt storage; worker/process persistence limits.
Revocation requires reconnection. OAuth code in access logs would be sensitive, so
launchers disable them; callback no-referrer must not break normal form Origin checks.

**How we'd detect it:** Offline HTTP tests cover state/PKCE, encryption, refresh, missing
scopes, replay, migration, routing, threads and uncertain pending sends; Chromium checks
cover account/setup/test forms at 390px and desktop. Setup readiness and explicit real
mail steps expose missing prerequisites. No real authentication/delivery is claimed.

**When to revisit:** Activate after selecting HTTPS hosting and registering provider
clients; test actual consent/delivery and a controlled reply campaign. Add explicit
provider revocation UI, multiple-primary-mailbox selection and durable queues before
broader/multi-process use. Consider send-only scopes if inbox access is not required.

**Date:** 2026-10-04.

## Persistent hosted preparation and operational recovery — 2026-10-04

**Decision:** Prepare a separate native-Python Render blueprint and a protected hosted
launcher, then finish account/test-history and inbox/send context controls. Keep the
sample blueprint and legacy local startup intact. Do not claim external activation.

**Context:** The operator asked to finish remaining work without a laptop or Codespaces.
Cloud has no hosting/provider credentials; OAuth needs a real HTTPS app and owner consent.
SQLite, campaign files and token encryption key must survive host restarts together.

**Alternatives considered:** A static demo can't run mail/OAuth. Hosting SQLite on an
ephemeral free filesystem loses state. Replatforming to a different frontend/DB/host
would duplicate approval/routing controls. Wildcard proxy trust was rejected by automatic
approval review because spoofed forwarded headers are unsafe; retain restricted trust
and require the host's verified proxy configuration instead.

**Why this one:** Native locked install preserves absolute prompt/template paths;
hosted chdir puts all private state on one proposed persistent disk. Secure protection,
automatic URL metadata and explicit activation steps reduce phone setup work. Saved test
outcomes and local disconnect prevent lost/ambiguous state without deleting history;
readable scoped inbox controls preserve multiple campaigns/accounts.

**Risks / failure modes:** Hosting requires separate account connection and paid charges;
proxy addresses can't be inferred before deploying; worker progress isn't durable;
Google/Zoho restrictions and consent remain external. Local disconnect isn't provider
revocation. Source-backed lead quality and delivery are not established by fakes.

**How we'd detect it:** 430 offline tests, successful isolated locked production install,
local hosted health/login/save paths, restart persistence tests, and desktop/390px
fictional-provider checks. Startup rejects unsafe paths/protection; proxy setup is
visible to the administrator. No live delivery or publication is claimed.

**When to revisit:** Activate when hosting access is connected and costs reviewed;
verify actual proxy/consent/mail/Safari. Add durable queues and comprehensive backups
before multi-process operation. Measure research role/ownership separately under budget.

**Date:** 2026-10-04.

## Guided laptop workflow and private provider entry

**Decision:** Keep the real FastAPI routes and approval gates; guide free audience saving
through three steps, then show paid planning as a separate action on saved preferences.
Encrypt browser-entered provider keys without modifying .env. Reuse the earlier mailbox
login as an unverified account while preserving both workspaces.

**Context:** The first planning request failed to reach a provider from the restricted
session. The audience was saved, but the combined form made the failure look like a
save error. The user explicitly requested extensive simplification.

**Alternatives considered:** Cosmetic changes leave saving and spending mixed.
A new frontend adds dependency/migration costs. Copying the old .env/database risks
overwriting new keys and current history.

**Why this one:** Progressive HTML works without JavaScript. Existing scope, spending,
history and approval guards remain. The credential vault encrypts local key overrides.
The owner launcher authenticates a graceful restart rather than killing a guessed PID.

**Risks / failure modes:** Browser drafts may become stale; restore only matching saved
versions, never consent, and block planning until edits are saved. Keys are configured,
not verified. The earlier mailbox lacked an inbox host. Provider policy, quota,
consent and real delivery remain external.

**How we'd detect it:** Offline secret-storage/auth/recovery tests, 35 real-Chrome
assertions through a fake-provider server, and actual loopback HTTP checks. No real
provider research or mail operation was used for setup.

**When to revisit:** After owner-run account verification and usability feedback.
The longer Playwright journey is updated but its runtime is unavailable on this laptop.

**Date:** 2026-10-06.

## Non-paid connection diagnostics and startup readiness

**Decision:** Check OpenRouter with GET /api/v1/key metadata, never a model completion. Keep Parallel as configured until its owner confirms dashboard access/credits. Start using the installed venv directly and open the browser only after Uvicorn is listening.

**Context:** Connection refusals during startup and generic provider errors were confusing. Setup must make no paid research or real mail request.

**Alternatives considered:** A completion ping could spend credits. A Parallel search could start paid work. Guessing an undocumented validation API would give unreliable results. Opening the browser before binding can show ERR_CONNECTION_REFUSED.

**Why this one:** The documented OpenRouter metadata endpoint checks credentials without generating text. Provider response labels, keys and raw errors are never displayed. Missing/restricted keys stop before any network request.

**Risks / failure modes:** Key acceptance does not prove available account credits or model access. Exhausted key limits are reported. The running desktop process must reload backend changes; close its app window and launch START-OUTREACH.cmd once.

**How we'd detect it:** Offline mock tests assert one GET, the exact metadata URL, no completion, no secret leakage, authentication and origin protection. Latest validation: 468 passed, one Windows symlink privilege skip; 35 Chrome assertions pass; live local free persistence passes.

**When to revisit:** After owner-run connection checks and feedback.

**Date:** 2026-10-06.

## Discoverable removal and honest progress feedback

**Decision:** Put Delete / archive on Home, audience/campaign lists and details, plus campaign settings. Permanently delete only unused drafts after explicit confirmation and a server-side recheck; archive work that has history. Use request feedback and read-only local status polling for actual background job progress.

**Context:** The user could not find deletion and wanted guidance, visible loading, current operations and completion feedback. Preserve existing data and approval controls.

**Alternatives considered:** Unrestricted cascading deletion can erase charges, uncertain sends and evidence. CSS-only loading cannot show actual job state. Automatic full-page refresh loses selected leads and edits. Fixed completion estimates would misrepresent provider latency.

**Why this one:** Review separates opening removal from changing data. Removal holds runner locks, rechecks state in a transaction and refuses active jobs. Archived audiences retain their original status and spending ledger; runner and paid entry points block them until restored. Archive views are reversible. Completed progress offers saved results without replacing the user's page.

**Risks / failure modes:** Only unused drafts can be deleted; archive is the option for other saved work. Poll failures do not prove work stopped. Status is process-local for drafting/sending; after a restart, inspect durable saved results. The desktop backend requires a restart to load updates. Foreground operations show working feedback without fabricated counts.

**How we'd detect it:** Confirmation/history-race/auth/origin/active-job tests; actual-count API checks; 53 Chrome assertions cover completion, retained selections, connection interruption/recovery, loading reset, double submission and confirmed deletion. 475 offline tests pass (one Windows symlink privilege skip), plus 33 targeted tests after final template adjustments.

**When to revisit:** User feedback about other item types, stronger cross-process job visibility, or an explicitly requested export-and-purge policy.

**Date:** 2026-10-06.


## Editable audiences and recovery from saved discovery

**Decision:** Allow unused audience drafts to be edited directly; changes after planning or requests create a free revised draft. Validate a company homepage against a cited page on the same exact normalized host, keeping public-URL, company-site and literal identity-evidence checks. Recover only completed cached discovery results, without a provider request.

**Context:** The latest audience had five completed requests, zero saved companies and no pending request. The URL check rejected a supported homepage because the cited source was an article on that same host. Other suggestions lacked verified company sites or evidence.

**Alternatives considered:** Repeating research spends again; accepting unrelated domains or guessed URLs weakens evidence. Mutating an approved run would mismatch its inputs, results and spending record.

**Why this one:** Existing calls and approval records remain unchanged. Recovery adds unprocessed suggestions and pauses completed work. Contact and fit checks require an explicit continuation. The summary separates waiting requests from uncertain outcomes and completed calls.

**Risks / failure modes:** A source-supported company suggestion is not a qualified contact. Revised inputs apply to a new draft; active original work must be paused separately. Uncertain reservations remain blocked and are never replayed automatically.

**How we'd detect it:** 487 offline tests passed, one Windows symlink privilege skip; 66 real-Chrome assertions passed. Recovery tests verify unchanged request ledgers, idempotence, evidence restrictions and no API use. Live owner-app HTML confirms the repaired audience and update notice.

**When to revisit:** After owner feedback on research quality and explicit use of the contact/fit checks.

**Date:** 2026-10-07.


## Additional research batches within a campaign

**Decision:** Add a campaign Research page and prominent Find more contacts, Edit campaign, Edit message and Delete / archive controls. Save each additional research batch as a free independent audience linked to the campaign. Keep earlier calls, caps and approvals intact.

**Context:** The user could not find a way to research more emails or see edit/removal actions. The owner's server still had the older backend, so feature guards hid the buttons.

**Alternatives considered:** Increasing an approved run's target would change its approved scope and collide with saved request inputs. Automatically running another batch would incur unapproved costs. Sending newly discovered addresses directly would bypass contact and draft review.

**Why this one:** A new batch has editable inputs, a separate spending cap and explicit paid planning/research approval. Related research remains reachable from the campaign, including earlier enrolled evidence. The campaign is preselected when adding approved results; existing members are skipped by the existing enrollment guard. Detailed history and audience edits are optional sections.

**Risks / failure modes:** Company targets do not guarantee published email counts or different search results. Broaden the audience or exclusions to reach different companies. Closed campaigns must reopen before another batch. A campaign with linked research uses archive rather than draft deletion. Older processes show visible controls with clear update guidance; audience editing and removal require a backend reload.

**How we'd detect it:** 495 offline tests pass with one Windows symlink privilege skip; 80 Chrome assertions pass, including 390px campaign controls and another free batch. Tests cover no provider/mail use on saves, retained original history/caps, preserved error inputs, campaign revision links, duplicate enrollment, removal/FK cleanup, authentication and origin checks. Actual owner HTML confirms visible buttons and update instructions.

**When to revisit:** After owner feedback on contact yield, search diversity or explicit requests for further checks within an existing company.

**Date:** 2026-10-07.

## Audience deletion, explicit continuation and flexible research

**Decision:** Permit confirmed removal of researched audiences into a restorable Deleted audiences view; retain unused-draft permanent deletion. Separate audience and campaign work, with next actions derived from saved state. Add an explicit flexible option and retain public email evidence from official search results.

**Context:** Users could not delete researched audiences or understand how to resume, and strict discovery/contact handling missed usable published addresses.

**Alternatives considered:** Cascading deletion would erase spending and campaign evidence; silently modifying an approved run would change cached request inputs. Guessing addresses or treating general inboxes as named contacts would introduce false claims.

**Why this one:** Deletion clears active work without destroying durable history. State guidance explains the exact next operation and its cost. New flexible drafts broaden discovery and accept general inbox fallbacks with human review, while legacy request fingerprints remain stable.

**Risks / failure modes:** Deleted audiences retain data until a separate purge policy is explicitly implemented. Email yield and delivery are not guaranteed. Uncertain requests stay blocked. Backend changes need a desktop reload.

**How we'd detect it:** Offline tests cover deletion/restoration with preserved calls/leads/campaign links, stale confirmation races, all research states, uncertain-resume blocking, same-site provenance, explicit email spellings, short literal identity evidence and long-page extraction. Chrome covers researched-audience delete/restore and mobile layouts. Real account operations were not run.

**When to revisit:** Owner feedback about research yield, pause/resume clarity or an explicitly requested full export-and-purge policy.

**Date:** 2026-10-07.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Research redesign proposal (2026-10-07)

- **Decision:** Diagnose empty research before further production changes; propose the staged Parallel-first pipeline in [RESEARCH_EXECUTION_PLAN.md](RESEARCH_EXECUTION_PLAN.md). Implementation choice remains pending review.
- **Context:** Two owner runs reached completed with zero companies after five successful requests each; all first-round candidate websites were placeholders. Both runs used Flexible mode and had unused budget. Contact extraction never started.
- **Alternatives considered:** Tavily/Firecrawl fallback for measured retrieval gaps; FindAll for higher-budget entity discovery. Neither substitutes for independent domain resolution and adaptive scheduling.
- **Why this one:** Reuse existing accounts while addressing the demonstrated pipeline failure. Compare real yield before adding providers or spending more.
- **Risks / failure modes:** Ambiguous company identity, unavailable published addresses, unreadable pages and insufficient budget for the requested target.
- **How we'd detect it:** Stage-level outcome counts, dated public-evidence benchmark, spending ledger and explicit partial outcomes.
- **When to revisit:** Benchmark shows search coverage or page-reading gaps after the core redesign.
- **Date:** 2026-10-07. No new paid call, mailbox operation or production-data mutation in this diagnosis/planning step.

### Staged research implementation (2026-10-07)

- **Decision:** Implement the user's approved Parallel-first plan for new/revised audiences, preserving earlier approved runs.
- **Context:** Existing completed runs rejected all unknown website suggestions and never reached email extraction.
- **Alternatives considered:** Switching retrieval vendor or FindAll immediately would add cost/setup without fixing discarded names. Keep these options conditional on measured benchmark misses.
- **Why this one:** Existing accounts suffice for explicit domain resolution, staged reading, checkpoint recovery and price-aware reservations.
- **Risks / failure modes:** Domain ambiguity; blocked or unindexed pages; unavailable preferred-role emails; budgets insufficient for the requested target; old desktop process still loading earlier code.
- **How we'd detect it:** Persisted suggestions and reasons; separate name/site/check/email counts; explicit outcomes; public-source benchmark; offline HTTP and Chrome integration checks.
- **When to revisit:** Controlled owner pilot shows missing retrieval coverage or page-reading failures after proper domain resolution.
- **Date:** 2026-10-07. Implementation authorized in this conversation; live paid pilot remains pending.


## 2026-10-07 — Direct audience handoff and campaign attachments

**Decision:** Add a visible saved-audience picker and a dedicated contact-selection page. Store immutable campaign attachment bytes in SQLite and attach the same selected files to every initial campaign email and optional draft test. Replies do not inherit files.

**Context:** A saved audience contains search criteria; recipients are researched contacts that require evidence review and approval. The previous list-first interface hid this connection. The user also requested email attachments.

**Alternatives considered:** Expanding only the existing list menu would leave the criteria-versus-contacts distinction unclear. File paths on disk would break if originals were moved and require a second backup mechanism. Per-recipient files would add selection complexity beyond the requested campaign feature.

**Why this one:** Direct selection reuses existing enrollment guards and contact origins without another provider request. SQLite BLOBs keep exact bytes in the existing private database backup. Draft, test and launch screens show names; attachment changes reset approved unsent drafts and invalidate signed launch/test consent.

**Risks / failure modes:** Larger databases and backups; provider upload limits or rejected files; stale consent; interrupted delivery. App limit is five files and 10 MB combined. Multipart input is bounded before parser spool files can grow beyond the request limit. Filenames, MIME types and stored hashes are validated.

**How we'd detect it:** Offline tests cover stale consent, exact MIME bytes, Gmail encoding, Zoho upload-before-send, failed upload without message submission, suppression, history retention, private downloads, size/count limits and database backup. Browser tests use fictional contacts and files only.

**When to revisit:** A need for per-recipient files, reply-specific attachments, large files or shared hosted storage.

**Date:** 2026-10-07.


## 2026-10-07: free plans, explicit audience lineage and contact-first research

**Decision:** Keep immutable research runs and their ledgers, but group explicit revisions and campaign batches selected from an audience under one audience card. The latest version opens by default; history links preserve earlier plans/results. Campaign handoff accepts approved, complete, nonsuppressed contacts across active versions. Only explicit parent links or older application-generated revision messages establish lineage; unrelated audiences are never merged by similar names.

Basic structured planning is deterministic and free. Optional AI planning remains separately paid. A stopped run can change target/total cap with confirmation for an increase, then resume separately. Existing spending/reservations/checkpoints remain intact; active or uncertain requests block limit changes. Deleting/archiving/restoring an audience applies to its entire explicit family and preserves history; permanent deletion is limited to a solitary unused draft.

New runs opt into strategy 3: smaller discovery batches/output reservations, exact literal brand-site resolution when unambiguous, and actual contact page extraction before accepting search-only general inboxes. Founder/management requests continue through the bounded page queue rather than stopping at a general inbox. The existing fit assessment also collects literal named-role evidence; invented addresses, unquoted ownership and relabelled generic inboxes are rejected. Earlier strategies retain their original API bodies and fingerprints.

**Evidence:** Read-only laptop ledger audit found successful searches and zero extraction requests; recent budget stops occurred before email collection. It does not demonstrate a key-level Extract failure. Fictional provider tests cover a $0.10 run reaching extraction, named-role evidence, immutable ledgers and uncertain stops. Production yield and key authorization have not been tested with paid requests.

**Risks:** A public email may not exist; a site may block extraction; evidence may be outdated; a cheap model may fail strict output. No deliverability or founder-email availability is promised. Inspect source evidence and provider-reported costs before scaling.


## Email research effectiveness proposal
Decision status: proposed, not implemented. Recommend bounded public-web contact retrieval with relation-level evidence and an optional separately enabled enrichment adapter. Current domain-only collection and same-quote attribution limit recall. Alternatives are a free-form model agent (harder to control/reproduce) or enrichment-only lookup (coverage, pricing and publication evidence differ). Validate the public-web path with a seeded, dated founder-email benchmark before choosing more providers. See EMAIL_RESEARCH_IMPLEMENTATION.md.

## 2026-10-08 — Evidence-backed wider-web contacts
Use versioned strategy 4 for new audiences. Role and ownership may come from different literal sources. External addresses are reviewable, never guessed. Frozen per-stage context preserves request identity on resume. Keep earlier research strategies unchanged.

## 2026-10-08 — Direct campaign selection and email-yield cost controls
- **Decision:** Selecting published contacts and clicking Add to campaign also records their acceptance, atomically with enrollment. Detailed evidence review remains optional. Add an Attachments campaign tab.
- **Context:** Separate approval, notes, lists and enrollment made a simple handoff hard to understand. The owner explicitly requested fewer review steps.
- **Alternatives considered:** Retaining mandatory notes leaves the reported friction; automatically enrolling all research results would remove the user's choice.
- **Why this one:** One explicit selection action, existing deduplication and suppression protections, and no automatic sending. Unconfirmed roles and audience criteria remain labelled, never rewritten as supported evidence.
- **Risks / failure modes:** A published address can be stale or belong to the wrong role. Selection is recorded as user acceptance, not an assertion of manual verification.
- **How we'd detect it:** Source details remain accessible; tests cover missing/suppressed/unfinished contacts, invalid destinations and transaction rollback.
- **When to revisit:** Add delivery verification if bounce measurements justify its cost.

New research uses strategy 5: empty discovery results skip the model; empty company evidence skips assessments unless named-role evidence can guide retrieval; two discovery rounds with no new published addresses pause for the owner to decide. Existing strategies and paid request identities remain unchanged.

## 2026-10-08 — Campaign contacts without a list detour
Decision: show usable audience emails directly on the campaign Contacts page. Selection posts to existing atomic handoff with the campaign already set; existing members are omitted. New campaigns require a name, with older saved-list selection collapsed. Preselected contacts show a count and carry their group identifier privately. Alternatives: a separate picker preserves extra clicks; automatic addition removes explicit selection. Risks: broad audiences may contain uncertain roles, so labels and source links remain. Tests cover direct addition, duplicate omission and selected-contact creation. Revisit pagination when audience sizes justify it.

## Prompt-first creation and focused development — 2026-10-09

- **Decision:** Use one overall audience prompt, one overall message prompt and an
  optional exact-lines block; reuse existing intake, plan, campaign-copy and fixed-ending
  paths. Add concise AGENTS.md and align CLAUDE.md with authorized autonomous increments.
- **Context:** The owner requested fewer inputs and more efficient development without
  disrupting existing workflows. Many local changes already exist and must be preserved.
- **Alternatives considered:** Paid AI parsing at every save introduces cost and new
  consent/recovery steps; removing structured controls prevents precise correction.
  A frontend rewrite adds unnecessary scope.
- **Why this one:** Common audience patterns can be interpreted for free, ambiguity
  clarified, and message prose passed unchanged into existing drafting. Optional detailed
  controls retain precision; paid research and sending approvals remain separate.
- **Risks / failure modes:** Conservative English parsing may require clarification;
  a supplied prompt overrides detailed message fields; fixed lines appear at the end.
- **How we detect it:** Prompt creation/revision/validation regressions, fake-provider
  tests and browser harness. Original audience wording and interpreted scope are reviewed.
- **When to revisit:** A measured sample shows clarification overhead warrants a bounded
  AI interpretation step, or users require arbitrary placement of exact text.
- **Date:** 2026-10-09

## Target-or-budget research and scoped completion — 2026-10-10

The owner requested continuous research throughput under the approved cap. New strategy6
runs remove dry-round, eight-round and candidate ceilings; existing strategies stay
stable. Fixed seeds, explicit pause, daily caps and uncertain/provider failures remain
valid stops. Role priority and duplicate-source model skips improve useful work without
changing providers or adding parallel paid calls. Company-context extraction shares the
existing assessment, stays literal/official and retains provenance through enrollment.
Review/recovery polish and offline CI/browser tooling finish the scoped backlog. Live
yield and optional integrations remain conditional. Revisit based on measured live yield,
not fictional benchmark cost or a claimed token-savings percentage.

## Single-editor protected composition and campaign isolation — 2026-10-10

Replace hard-coded shared sales context with neutral current-campaign prompts. Use
ordered KEEP blocks and one structured generation call per recipient; programmatic
insertion preserves wording/placement without another paid interpretation step. Keep
legacy campaign IDs, files, drafts and closings compatible; add immutable generation
provenance and reject stale results instead of a large campaign-storage rewrite.

The exact owner incident remains unverified; fictional prompts reproduce the shared
template problem. Tests protect three distinct campaign purposes, state restoration,
retry/isolation, protected formatting, approval and send checks. Historical drafts cannot
retroactively gain reliable provenance. Bump COMPOSER_VERSION when shared generation
semantics change; revisiting storage consolidation requires a demonstrated need.

## Workbench: grounded draft and exact-version review — 2026-11-10

Workbench drafts run automatically after a supported hook, inside the same run: identity,
signal, one follow-up, draft and one repair share the run's model-request cap (raised
4 → 5), dollar budget, deadline and durable ledger. A held draft request keeps the
research result (`research_ready`) and is never replayed. the Workbench uses its own prompt
(`core/workbench_draft.py`); the original campaign composer and COMPOSER_VERSION are unchanged.
`ResearchAPI.generate` gained optional `model`/`system` arguments (defaults unchanged)
so drafts use the configured draft model (`llm_model`) through the same ledger.

Support is decided by deterministic rules in `core/workbench_claims.py`, never by a model
verdict. Each sentence binds to the writer's citations, or else its closest saved
support (hook passage, identity passage, campaign claim IDs derived from the snapshot).
Names, numbers and dates must appear in the bound support; causal, intent, pain,
presupposition, certainty and outcome wording must also appear there; tense may not
turn in-progress/planned into completed (or past into ongoing); recency needs a recent
dated hook; relative dates are rejected; one exact campaign CTA. Shared vocabulary is a
notice only. This is conservative and will over-flag some fluent model output; the
single repair plus reviewer edits are the intended path, not relaxing the rules.

Draft revisions and review events are immutable rows. Approval binds run, revision,
content hash and a basis hash (evidence version, campaign snapshot, selected identity,
hook). Any edit creates a new revision; any basis change marks the draft stale; a
rejected version must be rechecked first. Copy/export is a server route that returns only
the currently approved revision; there is no bulk approval route. Revisit if live drafts
are routinely held by false positives, measured in an authorised live run.

## Workbench: demo scenarios and workbench layout — 2026-11-10

- The four edge cases are fictional provider responses keyed by prospect name in
  `adapters/workbench_fixture.SCENARIOS`, not special code paths: identity, hook, claim and
  review decisions are the same functions used for live responses. The list reaches the
  web layer through `wiring.build_workbench_app` (fixture mode only), so web never imports an
  adapter and live mode shows no scenarios.
- The run page puts hook and evidence beside the editable draft because the reviewer's
  job is comparison; each sentence's citation links to and highlights its source.
- Fixture drafts address the prospect as "you" instead of naming them to themselves; the
  claim checker still binds that sentence to the cited passage.

## Workbench: hosted launcher — 2026-11-10

- the Workbench gets its own `--hosted` mode instead of reusing `outreach.hosted`, because the
  original hosted app wires mail, OAuth and inbox features that the Workbench must not expose.
  Rules mirror it: environment-only settings, a password of at least 16 characters, one
  HTTPS origin host, an absolute persistent data directory, one worker.
- The Render blueprint is a separate proposal file (`deployment/workbench-render.yaml`);
  existing blueprints are untouched until Aksh reviews pricing and applies it.

## Workbench: workbench redesign around one three-step flow — 2026-11-11

- **Context:** Aksh found the Phase 4 workbench hard to read: demo cards dominated the
  first screen, the email sat below a long claim list, and headings were phrased as
  abstract questions.
- **Decision:** organise every screen around one flow (enter a prospect → research and
  draft → review, approve, copy). The run page leads with a progress bar, a status card
  with one primary action, and the draft email as a composer; hook and sources sit
  beside it; diagnostics go under "Behind the scenes". Guidance came from the MIT
  `ui-ux-pro-max` skill's UX rules (read, scripts not run).
- **Kept:** routes, data contract, claim checks, exact-version approval, export rules
  and every data attribute the tests and scripts depend on.
- **Trade-off:** desktop now puts the email first (left) instead of the source; the
  source-to-draft link is preserved by citation tags that highlight the source.

## Workbench: editable outreach goal (branch `workbench/editable-goal`) — 2026-11-11

- **Context:** Aksh asked what the research is looking for and why. The fixed demo
  campaign already steered queries, hook ranking and allowed claims, but was hidden and
  could not be changed.
- **Decision:** "Your goal" is step 1 of the New prospect form in live mode: sender,
  offer, who it is for, what it does (1–4 claims), provable results (0–3), good reasons
  to reach out, and one closing question. It is pre-filled with the last goal used (the
  demo goal by default) and can be reset. Each distinct goal is saved once as an
  immutable, content-addressed snapshot (`goal-<hash>`, version 1) and every run binds
  to it. "Good reasons to reach out" feeds the signal search query, the research
  objective, the model's signal prompt and hook ranking. Example mode keeps the fixed
  demo goal because its saved sources and drafts were written for it.
- **Trade-off:** capabilities and results the rep types become approved claims; the
  checker enforces wording against them but cannot know whether they are true.
  Validation keeps them short statements and the closing question a single question, so
  the checker's CTA rule still works.

## Workbench: looser evidence rules and larger research budget (branch `workbench/looser-evidence`) — 2026-11-11

- **Context:** a live run for a well-documented CFO ended "needs more evidence" although
  the company team page and SEC filings were read. The model quoted an offer letter that
  never names him, and the identity rule accepted only "Full Name, Role at Company" in a
  fixed pattern; "Eric is Chief Financial Officer of Innventure" failed. The hook stage
  never ran. Spend was $0.016 of $0.10: breadth, not dollars, was the constraint.
- **Budget (per run):** 10 search queries in up to 5 requests, 14 page reads, 2
  follow-up rounds (identity and hook), 6 model steps, 180 s, $0.15 cap. Prices used:
  search request ~$0.005 (ledger tariff raised from $0.001 to stay conservative), page
  read ~$0.001, research-model step ~$0.005. Worst case ≈ $0.08; typical $0.02–0.05.
- **Identity:** literal quotes match ignoring punctuation; the person may be referenced
  by first or last name when the page names them in full; join/appointment phrasing is
  accepted; the employer may be implied by the company's own site or a filing/wire page
  that names it. A page scan proposes candidates the model missed. Company site, filings
  (SEC, exchanges, Companies House) and major wires confirm automatically; any other
  readable page only offers the identity for one-click human confirmation.
- **Hook:** news about the prospect themselves no longer has to mention offer keywords.
  If no development passes, the identity source's stated responsibility ("overseeing
  finance, accounting…") becomes a hook labelled "Weaker hook"; a bare title is not
  enough. Hooks show Strong (recent dated event), Good (stated responsibility) or
  Weaker (role fallback).
- **Unchanged:** previews are never proof; dates, recency, contradictions, syndication
  and the draft claim checker are as strict as before; nothing is auto-approved.
- **Evidence:** replaying the saved Eric Stober run offline now confirms identity from
  innventure.com/team and yields a sourced role hook without any new paid call.

## Workbench: never-empty hooks (branch `workbench/looser-evidence`, second pass) — 2026-11-11

- **Context:** the re-run confirmed Eric Stober from 7 pages but still ended "needs more
  evidence": the model trimmed a bracket from the press-release sentence (no longer
  literal), the 8-K said "the Company" instead of the name, both appointment items
  disagreed on the date, and the role fallback skipped sentences containing "joined".
  Aksh: use whatever was found; do not leave the result empty.
- **Decision — fallback chain:** (1) a hook that passes every check (Strong/Good);
  (2) the best relevant item held back only for a soft reason (no offer keyword, older
  than 180 days but within 3 years, undated, or a date-only conflict) — used without
  any date or recency; (3) the sentence that confirmed who they are and their role;
  (4) if the person is not confirmed, company news only, with a visible warning that
  the person was not confirmed. Only "nothing readable at all" or "which person?" stay
  empty. Steps 2–4 are labelled "Weaker hook".
- **Also:** a model quote that omits words is replaced by the page's own sentence (adding
  words is not allowed: ≥95% of quoted words must be on the page); wire datelines are
  trimmed; signals naming the person or coming from the company's site or a filing count
  as attributed even when the sentence says "the Company".
- **Example scenario (b)** "Too little public information" now ends Ready for review
  with a Weaker role hook instead of no draft.
- **Still strict:** previews are never proof, recency words need a dated recent event,
  quantity/status conflicts and invented additions are rejected, the claim checker and
  human approval are unchanged.

## Workbench: draft model, "Write the draft" and clickable history — 2026-11-11

- **Context:** a live run selected a hook but wrote no email: OpenRouter answered HTTP
  404 for `openai/gpt-5.6-luna` (the original app's `llm_model`), the call stayed "held",
  and the page offered no way forward.
- **Decision:** Workbench drafts use `OUTREACH_WORKBENCH_DRAFT_MODEL`, else the research model
  (`anthropic/claude-haiku-4.5`, proven on this account). Outright provider rejections
  (HTTP 400/401/402/403/404/422) are recorded as complete at $0 with a plain reason, not
  held, because nothing was processed. A run with a hook and no draft shows "Write the
  draft": one model request inside the run's limits, new ledger keys per attempt
  (`draft-2`, `repair-2`), a fresh 120 s window, and interrupted attempts restore the
  saved research. History rows open the run anywhere on the row and say what is next.
- **Not changed:** responses with an uncertain outcome (timeouts, 5xx) stay held and are
  never replayed.

## Workbench: resilient pipeline: always a usable email, with an honest judgement (branch `workbench/resilient-pipeline`) — 2026-11-11

- **Context:** live runs kept dead-ending (refused model, held request, strict gates).
  Aksh: the tool must be useful in every case, use whatever it found, and say how
  strong it is.
- **Models per job (OpenRouter list prices per million tokens, Nov 2026):** research
  findings use `anthropic/claude-haiku-5.5` ($0.10/$0.50) then `claude-haiku-4.5`
  ($1/$5); drafts use `anthropic/claude-sonnet-5.5` ($2/$10, about one cent per email)
  then the Haiku models. Settings: `OUTREACH_WORKBENCH_RESEARCH_MODELS`,
  `OUTREACH_WORKBENCH_DRAFT_MODELS`. Price cap per call $3/$15.
- **Failure treatment:**
  | Failure | Treatment |
  |---|---|
  | Provider refuses a request (HTTP 400/401/402/403/404/422) | Recorded at $0 with the provider's message; next model in the list is tried; uses no model quota |
  | Model returns malformed findings | Bad items dropped and counted; valid ones kept |
  | Uncertain outcome (timeout, 5xx), limit, budget or time reached | Held and never replayed; paid research stops; the run continues with what was saved |
  | No model can write the email | Free built-in template writes it; "Write it with the model" retries later |
  | Nothing confirms the person | Company news, else how the company describes itself |
  | Nothing readable at all | Email from what the rep typed, labelled "Not personalised" |
  Only "which person did you mean?" stops for input.
- **Judgement:** every hook carries a verdict (Strong / Good / Weaker / Not personalised)
  plus plain lists of what it has and what it lacks, built from facts (source type,
  identity confirmed, dated and recent, link to the offer), not from a model's opinion.
- **UI:** prospect email removed (never used; nothing is sent); judgement lists in the
  hook panel; email and hook set in a serif "letter" face; sentence-case labels;
  design guidance from Anthropic's `frontend-design` skill.
- **Trade-off:** the bottom rungs produce generic or thin emails. They are labelled and
  still need human approval; the alternative was an empty result.
- **Reviewed release:** run 8cbb7016d08b4378's draft request, which the saved log shows
  OpenRouter refused with HTTP 404 before the refusal handling existed, was released at
  $0 through `release_rejected_call` on Aksh's instruction.

## Workbench: batch research (branch `workbench/batch`) — 2026-11-11

- **Context:** Aksh wants to research many prospects in one go instead of one at a time.
- **Decision:** "Many at once" takes a pasted list (name, company, optional title and
  website; tabs or commas, header row skipped, duplicates dropped, up to 20), one goal
  and, in live mode, one authorization that states the per-prospect limit and the batch
  maximum (20 × $0.15 = $3.00). Each row becomes an ordinary run with the same limits,
  ledger and checks; three run at a time. The batch page shows progress, each hook's
  strength and the next step, opens "Review the next draft", and downloads all approved
  emails as one text file. Run pages gain previous/next navigation within the batch.
- **Kept:** no bulk approval. Each email is still read and approved on its own; the
  download contains only individually approved versions.
- **Limits:** runs still waiting when the server restarts are marked interrupted, not
  restarted. Pasted text only (no file upload), which needs no new dependency.
- **Alternative kept:** `workbench/resilient-pipeline` has everything except batches.

## Workbench: default models switched to DeepSeek V4.1 Flash — 2026-11-11

- **Context:** Aksh asked for cheaper open-source models; Claude Haiku 4.5 model steps
  were about $0.023 of a $0.042 run.
- **Decision:** `deepseek/deepseek-v4.1-flash` ($0.05/$0.57 per million tokens, supports
  strict JSON output) for research findings and for drafting, then
  `anthropic/claude-haiku-5.5`, then `anthropic/claude-haiku-4.5` (proven) as fallbacks.
  Override with `OUTREACH_WORKBENCH_RESEARCH_MODELS` / `OUTREACH_WORKBENCH_DRAFT_MODELS`.
- **Trade-off:** a smaller model may quote less exactly or write blander prose. The
  pipeline, not the model, enforces correctness (malformed findings dropped, quotes
  snapped to the page, every sentence checked, one repair, template fallback), so the
  expected cost is more "weaker hook" or "needs a fix" results, not unsupported claims.
  Prompts contain public page text, the prospect's name and the offer; routing follows
  the account's OpenRouter privacy settings.

## Workbench: easier claims, reviewer choices, better hook choice — 2026-11-11

- **Context:** the cheap-model run chose a cost-cut sentence over Eric Stober's CFO
  appointment, and the email read stiffly. Aksh: make it easy for the email to use what
  was found, and let the person decide afterwards what not to use.
- **Hook choice:** dates, years and legal references ("Section 13", "Act of 1934") no
  longer count as conflicting quantities; when only one account states the event date
  in its own words, that account wins; a first-name reference counts as being about the
  person. Replayed run 8da5995922fd438b now picks the 19 Oct 2026 appointment as a
  Strong hook.
- **Easier claims:** the email may use up to three other checked facts besides the hook.
  Only real overclaims block approval: invented names, numbers or dates; claims of
  problems, needs, intent, certainty or results; tense and date errors; unhedged
  inferences. Missing hook, generic or linking sentences, changed closing question,
  length, citation slips and presuppositions are now warnings ("Your call"). Title
  acronyms (CFO for Chief Financial Officer) are accepted.
- **Reviewer choices:** every body sentence has "Remove this sentence" (a free, checked
  new revision), and "Choose which facts the email uses" lists the hook, other facts and
  the offer lines with tick boxes; "Rewrite with the ticked facts" is one model request.
- **Prompt:** the writer is told to sound like a person, open with the hook in the
  second person in its own words, paraphrase the offer, and is given the hard limits.

## Workbench: cost cut: excerpts as evidence, fewer reads, smaller model context — 2026-11-11

- **Context:** Aksh found runs too expensive. Real costs of run 8da5995922fd438b at list
  prices: page reads $0.010 (10 pages), models $0.0075 (of which $0.003 was a DeepSeek
  draft that returned nothing), searches $0.002. The ledger had recorded searches at
  $0.005 each; Parallel's "fast" mode is $0.001 per request (docs.parallel.ai pricing).
- **Decisions:**
  - Search excerpts (about 1,100 characters per result, ten results, free with the
    search) are stored as "excerpt" sources and count as weaker, labelled evidence:
    "Seen in a search excerpt; the full page was not opened". LinkedIn excerpts never
    count. This revises the brief's "previews are not evidence" rule at Aksh's request.
  - Pages are opened only when needed: none for identity if the excerpts already confirm
    the person, otherwise two; two for the hook; one per follow-up.
  - The identity model step is skipped when the page scan confirms the person.
  - The model reads only passages around the person or company (up to 1,400 characters
    each, eight most relevant sources), not whole pages.
  - Claude 5 and open reasoning models are asked for low reasoning effort.
  - Limits: 8 queries in 4 requests, 6 pages, 2 follow-ups, 8 model steps, $0.05 cap
    (was 10/5/14/2/10, $0.15). Search tariff recorded at $0.001.
- **Expected:** about $0.005–0.012 per run (2–3 searches, 0–4 pages, 2–3 model steps).

## Workbench: professional UI pass: app shell, Goal page, email-first run page — 2026-11-11

- **Context:** Aksh asked for a more intuitive, professional UI.
- **Decisions:**
  - App shell with a side bar (New prospect, Many at once, History, Goal) and the mode
    and safety note at its foot; it becomes a top bar on phones.
  - The goal is a setting, chosen once on its own Goal page (saved as the current goal per
    mode), not a block repeated on every form. Forms show one line: "Writing for …,
    Change". Each run still keeps a copy of the goal it used.
  - Run page: the email is the workspace on the left; the side panel explains it (the
    hook with its verdict, the facts the email may use, the sources). The sentence check
    is collapsed behind counts (backed by a source / your call / blocking) and opens
    by itself when something blocks approval.
  - Quieter visual system: 15px base, one accent, flat cards, sentence-case labels.

## Workbench: results page, start options and colour meaning — 2026-11-12

- **Context:** Aksh asked for a simpler results page (claims highlighted with their
  sources; without an email, findings one by one in priority order), an option to skip
  drafting to save cost, an optional goal, and colours that each carry one meaning.
- **Start options** (both forms): "Use my goal" and "Draft an email". Unticking the
  goal runs plain research with the built-in `no-goal` campaign (research looks for any
  sourced news; no offer gate; no offer judgements) and switches drafting off, because
  there is nothing to offer. Unticking drafting stores `write_draft: 0` in the run's
  limits: no drafting model call; "Write the draft" stays available later.
- **Results page:** with an email, a read view marks every sentence and numbers its
  sources (1, 2… for pages, G for your goal); the editor sits behind "Edit the email".
  Without an email, "What we found" lists findings most useful first (hook, other
  facts, who they are, then what was not used and why), each with its source number.
  Sources are numbered in the order the reader meets them; search excerpts are listed.
- **Colour meaning:** green = backed by a source / strong or good hook / approved;
  grey = from your goal or neutral; amber = your call / weaker; red = blocks approval /
  failed / not personalised; blue = only clickable things and work in progress.
  Cautious "may/might" inferences are amber.
- **Evidence:** live research-only run f8c03d28576942fc cost $0.005 and picked the
  19 Oct 2026 appointment as a Strong hook.
- **Not built (Aksh's idea for the write-up):** choosing rule strictness at the start.

## Workbench: live run view and History dashboard — 2026-11-12

- **Context:** the case study grades "a live run view (showing each stage as it executes)
  and a dashboard (showing history, status, and outputs across runs)". The run view was
  a technical log ("Identity extract 1"); History was a plain list.
- **Run view:** saved stage events are shown as five plain phases (Find the person, Find
  news about them, Choose the hook, Write the email, Check every sentence) with plain
  step names ("Searching the web for Eric", "Reading news pages (2)"), a running clock and
  the settled cost against the run's limit. Phases are done, working (blue), not yet,
  skipped on purpose (research only) or done with a note (amber). Finished runs keep the
  same summary under "How this run went" ("Took 0:12, Cost $0.005 of $0.05").
- **Dashboard:** History opens with counts (researched, working now, ready for you,
  approved, need a closer look), average and total live cost, and a hook-strength bar;
  each row shows its cost and its output (email subject or hook).
- **Cost shown** is settled cost: completed requests only, not amounts still reserved.

## Workbench: minimum research standard and found / chosen / set aside — 2026-11-12

- **Context:** a live run used one usable fact: it searched once for news, read two
  pages, and only searched again when nothing at all was usable. Aksh: set a minimum
  standard, then clearly show what was found and what was chosen.
- **Minimum standard ("Thorough", the default):** news covers the person (appointments,
  interviews, talks), the company (press releases, launches, partnerships) and the goal;
  a growth search (hiring, funding, acquisitions, expansion, results) always runs; up to
  4 pages are read across them; if there are fewer than 3 different facts or fewer than
  2 angles, one more search targets the missing angles. "Quick" keeps the old single
  news search and two pages. Facts carry an angle label. Limits: 12 queries in 5
  requests. Expected cost about $0.010–0.013 (Quick about $0.006).
- **True facts are kept, not discarded:** facts with no link to the offer become
  "Context" and earlier roles elsewhere "Earlier role"; both unticked, the reviewer can
  tick them into the email. "He served…" on a page about the person now counts as them.
- **Page:** "What we found" shows Chosen (ticked; the hook is always used; "In the
  email" marks facts the current email relies on), Also found, not chosen (unticked),
  From your goal (offer lines, ticked) and Set aside (folded, each with its reason).
  "Write the email from the ticked facts" / "Rewrite with the ticked facts".

## Workbench: relevant, natural drafting with per-sentence relevance — 2026-11-12

- **Context:** live emails used facts in a bolted-on way ("Nine years as CFO at Astrotech
  might be a useful base…", naming predecessors). Aksh: use facts only where relevant
  and natural, keep everything, and make removal easy by colouring sentences by
  relevance while drafting.
- **Drafting:** the writer first decides privately what the hook means for this person
  in their role and why the offer might matter, then writes around that one thread. An
  extra fact is used only if it makes the email more specific to their current
  situation or the offer; career history, past employers, colleagues and company trivia
  are left out by default. One bridge, the offer in one or two plain sentences, 50–100
  words.
- **Relevance per sentence:** the writer rates each sentence core (the reason for
  writing), supporting (more specific to them), offer, or optional (could be cut), with
  a few words why. The checker carries the rating onto each sentence.
- **Email colours now mean relevance:** deep green = reason for writing; light green =
  adds relevance; grey = your offer; amber = optional, easy to cut; red = blocks
  approval. Source numbers stay on every sentence. "Remove them" drops all optional
  sentences in one click, as a new checked version.
- **Subject lines inherit the sentence they sum up (live rewrite, run f09ee6ca58744c0d):**
  Haiku 5.5 rewrote Eric Stober's email at about $0.001 in four sentences: the CFO
  appointment (core), his new remit tied to invoice review (supporting), and two offer
  lines; no career history and nothing marked optional. Its subject, "Congratulations on
  your Innventure CFO appointment", was flagged as unsourced because it paraphrases the
  source ("appointed … Chief Financial Officer") and shared only one word with it. A
  subject that shares at least two words with a cited sentence now takes that
  sentence's source and colour.

## Workbench: daily paid cap separate from the run cap — 2026-11-12

- **Context:** the day cap equalled the run cap ($0.05), so a data folder allowed about
  four live runs a day. That would stop a recording or an evaluator's second session.
- **Decision:** `--daily-usd` sets the total paid spend per UTC day across all runs in a
  data folder, default $0.50 and at most $2.00, never below the run budget. The hosted
  blueprint uses $0.05 per run and $0.50 per day. The environment setting
  `OUTREACH_RESEARCH_DAILY_BUDGET_USD` can still lower it.

## Workbench: the pitch is the point; research personalises it — 2026-11-13

- **Context:** Aksh's hosted test produced an email whose subject and "reason for
  writing" were the prospect's news, with the offer as a flat afterthought. His point:
  the goal is to pitch the product; research exists to make the pitch relatable and
  more likely to get a reply.
- **Decision:** the drafting brief is pitch-first (personal opener → bridge → pitch →
  closing question; subject names the offer, made specific to them). Sentence roles
  shown to the reviewer are About them / Bridge / Your pitch / Optional. Stored values
  are unchanged (core / supporting / offer / optional), so older drafts still render.
- **Goal content matters:** risky wording (problems, outcomes) is allowed only when the
  goal states it. The demo goal now has one "why it matters" line; a rep's own goal
  should have one too.
- **Model:** kept Claude Haiku 5.5 until the new brief is tested live; a stronger
  drafting model is a cost decision for Aksh if quality is still short.

## Workbench: one job per screen — 2026-11-13

- **Result page:** the email and its approve button are the page. A sentence is edited
  or removed where it stands (its source and rating follow the new wording, which is
  checked again). Hook reasons, facts, sources, run details, whole-email editing,
  the sentence check and versions are folded.
- **Start page:** one page with a mode (One prospect / Many at once). A list is
  reviewed one prospect at a time on the same result page; the old list table is
  still reachable as "Whole list".

## Workbench: stronger model for writing only — 2026-11-13

- **Context:** with a pitch-first brief, Haiku 5.5's email was structurally right but
  stiff. Aksh accepted a higher cost for a better email.
- **Decision:** `workbench_draft_models` = Sonnet 5.5, then Haiku 5.5, then Haiku 4.5. Research
  models are unchanged. About $0.013 more per email; about $0.02 per prospect.
- **Guard:** the writer's token allowance is 1,500 so the worst-case reservation fits a
  $0.05 run. If a model's worst case still does not fit, the unsent step is released
  and the next model is tried; a sent request can never be released this way.
