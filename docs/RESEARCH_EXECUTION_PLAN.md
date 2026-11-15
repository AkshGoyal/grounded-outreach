# Research execution plan — 2026-10-07

Status: implementation authorized and completed for the staged Parallel-first engine on 2026-10-07. Offline and browser checks pass; the owner desktop process needs a reload, and a live paid yield pilot remains pending. See RESEARCH_BENCHMARK.md. No paid research or mailbox operation was performed by the agent.

## Why the current runs returned nothing

Read-only inspection of the two latest completed runs found:

| Requested companies | Spending cap | Accounted cost | Requests | Saved companies |
| --- | --- | --- | --- | --- |
| 25 | $0.10 | $0.014270 | 5, all complete | 0 |
| 10 | $0.10 | $0.014036 | 5, all complete | 0 |

Both used Flexible mode and accepted founder, HR, management, general and other contacts. Each discovery round returned ten usable source records. The first rounds suggested four and three companies respectively, but every suggested website was a placeholder, rather than a usable URL. The second rounds suggested none. These runs have no uncertain requests.

The app rejected every suggestion before reaching contact search or page extraction. Its current discovery prompt requires a company's official website to already appear in the same supplied search excerpt. It has no separate step to resolve a company name to its website. The code always tries at most two discovery rounds, then labels the run completed even when the target is unmet. The budget is only a spending ceiling; increasing it does not currently create more search effort.

This is an orchestration failure demonstrated by the saved results. It does not prove that these companies have no public emails, nor that Parallel has no useful results. The source-host blocklist is also not a reliable classifier of source authority. Named contacts remain harder to find than general business inboxes, but contact filters did not cause these particular empty results.

Earlier offline/browser checks established UI and checkpoint behavior with simulated providers. They did not establish production research yield. Live yield needs its own benchmark.

## Tool choices

| Approach | Benefits | Costs and limitations | Recommendation |
| --- | --- | --- | --- |
| Rebuild the staged workflow using existing Parallel Search/Extract and OpenRouter | Existing accounts; explicit request costs; separates discovery, identity and email collection; easy to test and resume | We must implement domain resolution, adaptive work scheduling and evidence handling; some pages may be unreadable | First implementation |
| Add Tavily search or Firecrawl map/scrape as a measured fallback | Another retrieval route; Firecrawl can discover site links and interact with dynamic pages | Another account/key; separate credit accounting; fallback cannot repair our discarded-candidate bug by itself | Add only after benchmark identifies missing coverage or page-reading failures |
| Parallel FindAll for company discovery, followed by contact extraction | Purpose-built structured entity discovery; asynchronous status/events | Higher entry cost; matching companies does not guarantee public emails; requires additional job and cost integration | Optional higher-budget mode later |

These are capability comparisons, not a measured claim that one vendor returns more emails for this audience.

Current published Parallel rates: Fast Search $0.001 for ten results; Basic/Advanced $0.005 for ten results; Extract $0.001 per result. Additional search results have separate pricing. FindAll Base lists $0.25 fixed plus $0.03 per match: 25 matches would be $1.00 before contact extraction or enrichment. These rates were checked on 2026-10-07 and must be rechecked before changing billing logic.

Even a simple illustrative path of two Fast searches plus three extracted pages per company costs $0.005 per company, or $0.125 for 25, before discovery and model work. Some companies need fewer pages; others need more. A $0.10 cap cannot promise 25 contact-bearing companies.

Sources:
- [Parallel Search reference](https://docs.parallel.ai/api-reference/search/search): valid modes, excerpts and sessions.
- [Parallel search guidance](https://docs.parallel.ai/search/best-practices): short keyword queries, contextual objectives and supported source policies.
- [Parallel pricing](https://parallel.ai/pricing): search, extraction and FindAll rates.
- [Parallel FindAll](https://docs.parallel.ai/findall-api/findall-quickstart): structured discovery and results.
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search): result limits, depth, raw content and usage.
- [Firecrawl Map](https://docs.firecrawl.dev/features/map): sitemap/search-based link discovery; coverage is not exhaustive.
- [Firecrawl Scrape](https://docs.firecrawl.dev/features/scrape): page content, dynamic interactions, page status and option-dependent credits.

## Recommended execution

1. **Define a usable result.** Keep company target separate from email count. Default goal: the requested number of distinct matching companies with at least one published professional email each. Let the owner choose preferred roles and whether a general business inbox is acceptable. Show companies without emails separately. Named-person roles must have evidence; general inboxes never become founder/HR contacts by inference.

2. **Discover company names broadly.** Use industry/location synonyms, official sites, association lists and directories as discovery sources. Store every supported company suggestion with its discovery quote, URL and status, even when its website is unknown. Do not discard an entity just because a list excerpt lacks its official domain.

3. **Resolve each company's official website.** Search its name with location/product context and read likely official pages. Record evidence linking the name and domain; use additional context for same-name businesses. Keep unresolved or ambiguous identities visible for review. URL normalization may handle an explicitly supplied bare domain, but must never invent a domain.

4. **Find and read contact pages.** Search the verified domain, follow discovered contact/about/careers/team/footer links, and inspect relevant pages in a bounded sequence. Prefer promising pages and stop early once the contact goal is met. Use provider-supported domain policies rather than assuming search-engine operators behave identically everywhere. Begin with Parallel Search/Extract; introduce a crawler only where evidence shows it is needed. Preserve mailto links, original HTML/text and obfuscated published spellings where available.

5. **Extract actual published addresses.** Parse deterministically, normalize and deduplicate, and retain URL, original quote, retrieval time and observed role. OpenRouter organizes evidence and assesses company fit; it does not generate email addresses. Initially accept automatic email extraction only from verified company sites. Clearly separate any future third-party contact evidence for explicit review. “Published” does not mean deliverable or approved to send.

6. **Continue according to yield and remaining funds.** Persist a queue of discovery, domain-resolution and contact-reading work. Prioritize checking promising known companies before spending everything on new names. Choose the next bounded action only if its maximum reservation fits both run and daily caps. New query angles must add coverage rather than repeat cached searches. Pause after three consecutive rounds with no new entities/domains/contact-bearing companies and explain what failed. Cap rounds/pages/time to avoid endless work. Save good results progressively.

7. **Report the real outcome.** Show counts for suggestions, verified sites, checked companies, companies with emails and total distinct addresses. Show the current activity, recent result, request start time, cap, accounted charges and outstanding reservations. Finish with target reached, partial results, no usable results, budget limit, search exhausted, provider blocked or paused. Explain failed page reads and identity rejection reasons. Pause/Continue resumes saved work; Find more contacts creates an explicit new batch.

Directory discovery becomes less restrictive. Website ownership, literal email evidence, private-network protections and campaign suppression remain enforced. Optional company preferences should influence ranking; explicit mandatory criteria remain mandatory unless the owner changes them. Unknown fit evidence stays visible for review.

## Implementation sequence and file scope

**Increment 1: durable candidates and honest outcomes.** Add versioned engine metadata and an unresolved candidate queue without changing existing approved request inputs. Implement company-name discovery, independent domain resolution and reasoned completion states.

**Increment 2: adaptive contact collection and progress.** Add persisted per-company page work, published-address goal, bounded scheduling, stage counts, pause/recovery and the simplified research screen.

**Increment 3: benchmark, then optional fallback.** Test the production pipeline on representative fixed fixtures, measure real retrieval separately, and add a fallback provider only if results justify it.

Proposed files:
- src/outreach/core/discovery.py and core/research.py: candidate/evidence models and independent validation.
- New core/research_scheduler.py: bounded stage scheduling and stop reasons.
- src/outreach/core/research_flow.py: versioned discovery → resolve → contact → fit-review orchestration.
- src/outreach/adapters/platform_store.py: additive candidate/job/page checkpoints, outcomes and funnel counts.
- src/outreach/ports/research.py and adapters/research_api.py: supported query policies, modes/sessions, page errors and price-aware reservations.
- src/outreach/core/intake.py: company/contact goals and hard versus preferred criteria.
- src/outreach/web/research_jobs.py, research_view.py and platform.py: progress, continuation and new-version routing.
- Research intake/detail/live templates and their existing JavaScript: plain-language progress and result actions.
- Tests for research scheduling, domain identity, extraction, cost/recovery and browser integration; living documentation.

Existing completed and uncertain requests remain immutable. Legacy approved runs retain their current engine and fingerprints. Revised research uses a new explicit version and approval; useful cached public evidence can seed a new draft without pretending it was newly checked. No automatic paid replay, enrollment or sending.

## Acceptance and controlled execution

Offline acceptance must cover: directory-only names followed by official-site resolution; ambiguous names; public mailto/footer/careers addresses; role preference with general fallback; duplicate entities/emails; no-email/contact-form-only sites; bad page status; price changes; pause/restart; uncertain requests; zero-yield stops and deleted audiences. Replay the latest failure pattern with fictional fixtures rather than committing private responses.

Require zero invented addresses, source evidence for every address, accurate partial outcomes and no cap bypass or repeated charge after restart. Run browser tests through the actual backend to confirm that saved results and progress agree.

Build a manually reviewed benchmark of at least ten representative companies, including known published-email pages and sites that publish none. Compare returned companies/addresses against the dated source evidence; report contact-bearing-company yield, public-email recall on accessible known pages, source validity, cost and elapsed time. Target at least 80% recall of known accessible benchmark addresses and 100% source-backed identity/address precision before expansion; these are acceptance targets, not a promised production yield.

Then the owner may explicitly approve a five-company pilot with a suggested $0.25 maximum, after reviewing estimated search, extraction and model reservations. This pilot is proposed, not authorized or executed. Review every result and the provider ledger before scaling to 25. If it fails the benchmark, diagnose the failing stage before recommending more budget or another provider.

## Current laptop state

The app responds at http://127.0.0.1:8000 in normal desktop mode. Two saved mailbox accounts have verification timestamps and no saved connection errors; no new mailbox connection check was performed. The running server, .env, campaigns, credentials and research ledger were preserved. This step changes planning documentation only.


## Implemented 2026-10-07 follow-up

The free structured planner and strategy 3 collection are now implemented for new audience versions. Earlier approved/cached requests keep their strategy and fingerprints. Revisions stay under one audience with history and campaign handoff across approved active versions; paused runs can extend their total cap without resetting their ledger. Search and extraction counters distinguish a pre-fetch budget stop from a failed page read.

Read-only production audit: 35 existing ledger calls, successful searches, zero extraction calls. Recent engine-2 runs stopped at their budget guard during discovery/website resolution. No live research, provider-key test or mailbox action was performed to diagnose this.

Offline provider fixtures verify a $0.10 run reaches extraction with fewer model calls and founder research reads beyond general-inbox excerpts. This is an execution regression check, not a measured real-world recall result. The source benchmark and separately approved live pilot remain outstanding.

Primary references checked: [Parallel Search](https://docs.parallel.ai/api-reference/search/search), [Extract settings](https://docs.parallel.ai/extract/advanced-extract-settings), [Source policy](https://docs.parallel.ai/resources/source-policy). The same x-api-key is used for Search and Extract; a separate fetch key is not documented.
