# Platform plan - research, replies, and the web front end

## Managing multiple research runs and campaigns

Requirement added by the operator on 2026-10-03: several research efforts and
campaigns must remain clearly classified and easy to navigate. This is in the
pipeline for the production UI increment, after the cost/quality pilot.

Use a persistent sidebar: Overview, Research, Lead lists, Campaigns, Inbox.
Every screen keeps its active project/context visible and supports search,
purpose, tags and status filters. Save filters and return position when navigating
back so reviewing one company does not lose the operator's place.

| Object | Classification and lifecycle | Links |
| --- | --- | --- |
| Project | Purpose such as sales, job search, partnerships, other; user name and tags | Groups related research, lists and campaigns |
| Research run | Brief, geography, industry, target roles; queued/running/paused/completed/failed; budget, spend, reviewed yield | Source runs remain linked to their resulting leads and lists |
| Lead list | Reusable named selection; contacts need review/approved/rejected | Can combine research runs and supply multiple campaigns |
| Campaign | Purpose, offer, audience, sending identity; draft/active/paused/completed/archived | Shows originating lists and research, replies and campaign-specific progress |

Keep a shared company/contact identity with campaign-specific membership and
status. A person can belong to multiple lists without duplicating their contact
record. Preserve source provenance per observation; never overwrite it with
an unrelated research run. Show prior outreach and cross-campaign duplicates
before enrollment. Suppression remains global, with sending limits enforced
across campaigns as well as any per-campaign allocation.

The overview should answer: what is running, what needs review, what has stopped,
what each effort costs, and what action is next. Opening a research run shows its
brief, live progress, budget, evidence and leads; selecting approved leads offers
Add to list or Create campaign with the origin already linked. Opening a campaign
shows audience, drafts, review, sends and replies with links back to source evidence.
Archive old work without losing history. Do not silently enroll or send results.

UI acceptance: manage a textile-sales project and a job-search project at once;
find either in one filter/search; resume its correct research run; trace a contact
to evidence and prior campaigns; return from review without losing filters.
This section is a planned design, not functionality implemented by the pilot.

*Written 2026-09-25, after the first 10 real emails went out. Prices were
checked on that date and are converted at roughly ₹85 to the dollar.*

The goal: type one description of who you want to reach, and the platform
does the rest in the browser — finds the companies, finds their published
contact details, checks them, writes the emails, sends them, and sorts the
replies. A person still approves before anything is sent.

```
  1 Research        2 Draft        3 Review       4 Send        5 Replies
  "prompt" ──► companies + ──► emails ──► approve ──► Zoho, ──► read, sort,
               checked         grounded   (all or     slowly     suggest an
               contacts        in (1)     one by one)            answer
     NEW          built          built       built       built       NEW
```

---

## 1. How AI research actually works

**What I (Claude, in this tool) do when asked to research:** I have two tools —
*web search* (a search engine returns titles, links and snippets) and *web
fetch* (read one page). I loop: search, read the most promising pages, decide
what's missing, search again, and stop when I have enough. There is no hidden
database of contacts behind it. Any email address I give you came from a page
where a company published it — and can be out of date or wrong.

**Claude's "Research" mode** is the same idea at a larger scale: a lead agent
plans the work and starts several sub-agents that search in parallel, then
combines what they found, with citations. Anthropic reports it beat a single
agent by about 90% on their research tests, but uses about 15× the tokens of
a normal chat ([Anthropic engineering](https://www.anthropic.com/engineering/multi-agent-research-system)).

**"Deep research" APIs** (OpenAI's o4-mini-deep-research, Perplexity's Sonar
Deep Research) package that loop behind one call. They write a *report*. A
report is the wrong shape for us: we need a list of companies, one row each,
with every fact traceable to a page.

**The lesson for us:** the state of the art isn't a model, it's the loop —
plan, search, read the source, verify, repeat — plus good search results and
a check on every claim. We already have the check (the grounding checker).
The research layer extends the same rule to contacts: **an email address is
kept only if our own code finds it, character for character, on a page we
fetched — never because a model said so.**

---

## 2. The options

| Option | What it is | Cost for ~100 checked leads | Fit for Indian textile units |
| --- | --- | --- | --- |
| **A. Our own research agent** *(recommended)* | Our loop: AI plans searches → search API finds companies → we read each company's own website → AI extracts facts with quotes → code confirms each email is on the page → domain mail check | **≈ ₹200–400 / month** (search on a free tier, cheap model for reading) | Good: reads the sources that actually list these units — their own sites, trade directories, exporter lists |
| B. Parallel FindAll | A paid API: describe the companies, get back a list with cited fields | Base ≈ $3 (₹280), Core ≈ $17 (₹1,450) per 100 matches, contact enrichment extra | Unknown for small Indian units; still needs our email check |
| C. Contact databases (Apollo, Hunter) | Buy access to a database of people | $49+/month subscription | Weak: aimed at larger companies, and full of named personal contacts |
| D. Deep-research APIs | One call writes a research report | $0.40–1.30+ per query, and up to ~$30 on the biggest models | Poor: a report, not a list; hard to check line by line |
| E. Exa Websets | Prompt → table of companies with enrichment | $49/month minimum plan | Plausible, but a second subscription |

Prices: [Parallel FindAll](https://github.com/parallel-web/parallel-llms-txt/blob/main/public/docs/findall-api/core-concepts/findall-generator-pricing.md),
[Exa Websets](https://exa.ai/pricing),
[Tavily](https://docs.tavily.com/documentation/api-credits),
[OpenRouter web search](https://openrouter.ai/docs/guides/features/plugins/web-search),
[Claude web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool),
[Perplexity Sonar Deep Research](https://openrouter.ai/perplexity/sonar-deep-research),
[OpenAI deep research cost](https://x.com/ArtificialAnlys/status/1940896348364210647),
[email verification prices](https://myemailverifier.com/blog/email-verification-api-pricing/),
[Google Places](https://developers.google.com/maps/billing-and-pricing/pricing).

### Why A

- **Cheapest by far** at our volume, and the cost is per use, not a subscription.
- **Every fact is checkable.** The agent saves the quote and the page it came
  from; those become the contact's evidence, which the email is then written
  from. Research and drafting share one rule.
- **Nothing is locked in.** The search engine sits behind a port, like the
  mail and the model, so Tavily, Exa, Parallel or Google Places can be swapped
  or combined later without touching the rest. B can be added as a second
  engine if A's discovery turns out too narrow.
- **It's the portfolio piece:** an agent loop with verification, not a wrapper
  around someone else's API.

### The pieces of A, and what each costs

| Step | Tool | Cost |
| --- | --- | --- |
| Plan the searches from your prompt | our model (GPT-5.6 Luna via OpenRouter) | paise |
| Find candidate companies | **Parallel Search** — a free monthly allowance, then $1 per 1,000 (fast) or $5 per 1,000 (advanced) | ₹0 at our volume |
| Read each company's website (home, about, contact) | **Parallel Extract** — $1 per 1,000 pages, handles JavaScript-heavy sites and PDFs; our own fetcher as a free fallback | ≈ ₹20–50 / month |
| Pull out what they do, where, fit, contacts — with quotes | our model | ≈ ₹1 per company |
| Confirm each email is literally on the page | our code | ₹0 |
| Confirm the domain accepts mail (MX record) | our code (DNS lookup) | ₹0 |
| Optional: check the mailbox exists | Reoon, ~$1 per 1,000 | ≈ ₹10 / month |

---

## 3. The research layer — how it will work in the browser

1. **Describe who you want.** One box: *"Garment exporters and knitwear units
   with in-house dyeing in Tiruppur and Ludhiana, 50–500 employees."* Plus how
   many companies you want and a spending cap for the run.
2. **Check the plan.** The AI turns it into search queries and a short list of
   "what makes a company a fit". You can edit both before it runs.
3. **It runs, visibly.** A progress page like the sending one: searches made,
   companies found, websites read, cost so far. It stops at the cap.
4. **Review the results.** A table: company, website, city, what they do,
   fit reason (with the quote), email(s) found (with the page), phone, and a
   check mark for each check passed. Companies already in any campaign, or on
   the do-not-contact list, are dropped automatically.
5. **Add to a campaign.** Tick the ones you want → they become contacts, with
   everything found as their evidence and the source links kept. From there
   it's the flow you already use.

**Rules it follows:**
- Only **published addresses** — on the company's own site or a business
  directory listing. By default the general ones (info@, sales@,
  purchase@); named people's work addresses only if you say so (question 4
  below). Nothing guessed from patterns like firstname@company.
- Every email and fact carries the **page it came from**.
- **Unknown stays unknown.** A company with no published email is still
  shown — with its website and phone — but can't be added to a send.

**Legal note (not legal advice):** India's DPDP Act treats a work email that
identifies a person as personal data; the DPDP Rules were notified on 14
November 2025 with an 18-month phase-in to about May 2027
([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190655)). Our
approach keeps to the defensible end: published business contacts only, the
source recorded, a working opt-out in every email, and opt-outs honoured
immediately and permanently. Worth a short check with a lawyer before volume
grows.

---

## 4. The replies layer — built (D-023)

1. **Read the inbox** — a "Check replies" button, and automatically every
   few minutes while the tool is open. Read-only; nothing is deleted or moved.
2. **Match each reply to the email it answers**, using the email's
   Message-ID, which we already store for every send. Replies we can't match
   are kept and shown, never dropped (invariant I-4).
3. **Sort them** with the model: *wants samples* (and did they give an
   address?), *interested / has questions*, *not interested*,
   *out of office*, *bounced*, *other*.
4. **Act safely:**
   - *not interested* and *bounced* → added to the do-not-contact list at
     once;
   - *wants samples* → the postal address and contact person are pulled out
     for you to copy to the courier;
   - everything else → shown with a **suggested answer** you edit and send.
     The platform never replies on its own.
5. **An Inbox page** listing replies by type, with the original email beside
   each one, and per-campaign counts (sent → replied → samples requested) on
   the dashboard.

Follow-ups (a second email to those who didn't reply) come after this, and
stay manual until reply rates say otherwise.

---

## 5. The front end

**Done (D-022):** dashboard with each campaign's next step · Setup page with
"Test the Zoho login" and "Test the AI key" · offer & ending editor ·
import · write drafts · review · approve all that pass · send yourself a test ·
**send from the browser with live progress and Stop** · do-not-contact list ·
backup. `outreach serve` opens it in the browser.

**Still in the terminal:** starting the tool, `--redraft`, and editing `.env`.

**Next front-end steps:**
- A **"Rewrite unsent drafts"** button (the `--redraft` of the browser).
- **Settings in the browser** — enter the keys and Zoho password in a form
  instead of editing `.env`. Stored on this computer only, never shown back.
- A **double-click launcher** (Windows `.bat`) so starting it needs no
  terminal either.
- The **Research** and **Inbox** pages above.

---

## 6. Build order

| Step | What | Why this order |
| --- | --- | --- |
| 1 | Replies: read, match, sort, auto-suppress, Inbox page | You've sent 10 emails; replies are arriving *now*, and an opt-out must be honoured quickly |
| 2 | Research layer, version 1: prompt → plan → search → read sites → checked contacts → add to campaign | The real bottleneck: 7 of 44 leads had an address |
| 3 | Settings in the browser, redraft button, launcher | Finishes "no terminal" |
| 4 | Research v2: a second search engine (Parallel or Google Places), parallel sub-agents, cost dashboard | Only once v1's hit rate is measured |
| 5 | Follow-ups | Once reply rates are known |

Each step goes in as a small, tested increment, with the decision recorded.

---

## 7. Decided (2026-09-26)

1. **Research engine: option A**, our own agent — D-024.
2. **Replies first** — built, D-023.
3. **Contacts:** any contact **published** on the web — general addresses and
   named people's work addresses alike. Still never guessed from a pattern:
   a guessed address that bounces costs the domain's reputation (D-024).
4. **Search: Parallel** instead of Tavily. At $1 per 1,000 fast searches
   against Tavily's ~$8 per 1,000 after its free tier, it is cheaper, and its
   Extract API reads JavaScript-heavy sites and PDFs, which many Indian
   manufacturers' sites are. Others checked: Serper (~$0.30–1 per 1,000,
   Google results but links and snippets only), Brave ($5 per 1,000, no free
   tier since February 2026), Exa ($7 per 1,000). The search engine stays
   behind a port, so Serper can be added later for Google's coverage.
   Sources: [Parallel pricing](https://parallel.ai/pricing),
   [search API prices compared](https://www.buildmvpfast.com/api-costs/ai-search),
   [Brave's change](https://www.implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing/).

**Needed before research starts:** a Parallel account — parallel.ai → sign up →
API key → add `OUTREACH_PARALLEL_API_KEY=...` to `.env`.

## Implemented workspace increment (2026-10-04)

The multi-campaign navigation plan above is preserved. Its first usable increment
is now implemented in the existing browser app: persistent navigation, projects,
purpose/tags/status/search filters, URL-preserved filters and browser-back position,
research planning and approval, source evidence, bulk lead review, reusable lists,
new/existing campaign enrollment, Gmail/Zoho account selection, draft-all/rewrite,
paced sending, campaign dashboards and an account-scoped inbox. Campaign archives
preserve history. Shared research company identities and contact-origin links retain
provenance; prior company/address membership is shown before reuse.

The app uses SMTP/IMAP app passwords; provider OAuth remains a future transport
option. Live public mail connectivity is unavailable in this Codex executor, so
production sending requires a Cloud host with those protocols. Search, evidence,
spending, browser flow and mail routing were verified using offline providers.
See [workspace operation](WORKSPACE_GUIDE.md) for exact behavior and limitations.

## Proposed frontend refinement, 2026-10-04

[FRONTEND_PRODUCT_PLAN.md](FRONTEND_PRODUCT_PLAN.md) expands the existing
multi-campaign plan with the complete page map, mobile navigation, approval states
and implementation order. Campaign preferences belong in creation/editing forms;
research asks only clarifications that affect the approved search. This is the saved
product plan; implemented portions and remaining work are tracked below. The live founder benchmark's
contact and evidence limitations are recorded separately in
[FOUNDER_RESEARCH_RESULTS.md](FOUNDER_RESEARCH_RESULTS.md).

The approved product plan's first frontend increment is now implemented in the
real app: free saved intake, in-tool audience clarification, contact-role choices,
explicit paid planning, plan approval, staged lead review and five mobile tabs.
The existing multi-campaign navigation/history remains. Campaign handoff, tabs,
message brief, draft review and full launch previews are now implemented. Sending
progress, inbox and OAuth/hosting refinements remain subsequent increments. See
FRONTEND_PRODUCT_PLAN.md and WORKSPACE_GUIDE.md for exact behavior and limitations.

Campaign preparation now saves before mailbox connection. Approved selection → list
→ campaign retains source origins, prior-outreach checks and suppression. Shared
campaign tabs and readiness show the next task; message editing collects supplied
sender facts before paid drafting. Queue filters, selected checked approval and
previous/next review precede complete launch previews. New campaigns require an
explicit verified identity at launch, and sent history cannot move to another account.
See WORKSPACE_GUIDE.md for usage and FRONTEND_PRODUCT_PLAN.md for remaining scope.
