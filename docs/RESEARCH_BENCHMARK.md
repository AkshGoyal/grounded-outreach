# Research benchmark and throughput — 2026-10-10

## Current executable offline benchmark

Run: uv run pytest tests/test_research_throughput.py -rP. Uses fictional companies,
temporary databases, the production scheduler, HTTP adapter, evidence validation and
spending ledger. No live accounts or owner workspace are used.

| Scenario | Requested / obtained suitable company contacts | Requests | Fictional accounted cost |
| --- | --- | --- | --- |
| Ten empty discovery rounds before a useful company | 1 / 1 | 15 | $0.015 |
| Four companies without email before a useful fifth company | 1 / 1 | 25 | $0.025 |
| Two companies with requested HR contacts | 2 / 2 | 10 | $0.010 |
| Empty discovery with a $0.009 fixture cap | 1 / 0 | 9 searches; zero model calls | $0.009 |

These are deterministic fixture results, not production price estimates, live recall
or delivery rates. Other regressions verify duplicate-source model skips, manual pause,
uncertain request non-replay, duplicate/suppressed-address counting and literal official
personalization. Existing cross-page founder and public-excerpt tests remain in use.

Strategy 6 applies to new/revised audiences. Discovery continues until the target or
remaining budget cannot fund the next request, with no two-dry-round pause, eight-round
ceiling or three-times-target candidate ceiling. Completed requests are reused.
Known-company-only input remains limited to those companies and finishes when checked.
Manual pause, provider problems, daily caps and uncertain outcomes still stop safely.
Earlier saved strategies keep their request semantics; revise the audience to use the
new strategy. Budget exhaustion can leave unspent funds when the next call reservation
is larger than the remainder.

The target remains companies with suitable contacts, one distinct unsuppressed address
per counted company. A discovered name, generic fallback in focused mode, rejected
company or contradicted audience fit does not count. Publication does not verify delivery.
Official pages are prioritized by requested role; an HR search no longer stops on the
first general inbox. Identical discovery results avoid repeated model-selection calls.

Live requested-role yield, elapsed time, provider prices and inbox delivery still need
a separately approved pilot. Do not infer those from this benchmark. No new email
verification provider or broad AI prompt parser is required by these results.

## Historical research notes

The following dated observations and test totals describe earlier versions, not current
verification. Known-company input is implemented now; older notes about its absence are
historical.

### Public-source research benchmark seed — 2026-10-07

These ten companies/pages were inspected through ordinary web search, without calling the laptop's Parallel/OpenRouter accounts or creating production research runs. This is a manually reviewed starting set, not a measured production-provider benchmark. The rows test address discovery and role handling; they do not establish that every company fits a Bengaluru-only startup audience.

| Company | Official page inspected | Observation | Expected research behavior |
| --- | --- | --- | --- |
| Sarvam AI | [Contact](https://www.sarvam.ai/contact-us), [Help](https://docs.sarvam.ai/api/getting-started/help) | Contact page publishes press email; documentation publishes support email | Preserve publication and actual role; neither proves HR/founder identity |
| CoRover | [About](https://corover.ai/company/about-us) | Footer publishes a chat/business address | Retrieve footer and verify original address, especially when rendered labels run into the email text |
| Niramai | [Contact](https://niramai.com/contact/) | Explicit general contact address | Save literal email evidence; do not relabel as a named executive |
| Karya | [Contact](https://www.karya.in/contact/) | Explicit business, partnership, recruiting and support addresses | Collect/deduplicate them and prefer recruiting when requested |
| Yellow.ai | [Demo](https://info.yellow.ai/request-demo) | General regional address in footer | Include subdomain evidence and preserve actual contact type |
| LimeChat | [Privacy](https://www.limechat.ai/legal/privacy-policy) | Support and legal addresses appear | Exclude legal address; support is not a recruiting contact |
| Observe.AI | [Contact](https://www.observe.ai/contact-us) | No literal email visible in the retrieved contact-page text | Keep company and report this page's result; do not claim no email exists anywhere |
| Gnani | https://www.gnani.ai/contact-us/ | Direct page retrieval unavailable during this inspection | Record unreadable page, not no-email or invented contact |
| Staqu | [Contact](https://www.staqu.com/connect-with-us/) | Footer publishes general info address | Read footer; geography still needs independent fit checking |
| Fractal | [Contact form](https://fractal.ai/contact-us-submitted/), [Privacy](https://fractal.ai/privacy-policy/) | Contact page provides a form; privacy page publishes DPO address | A form or privacy email does not fulfill an outreach-email goal |

The dated observations above refer only to the retrieved pages, not exhaustive website searches. Search indexing and page contents can change. No address was approved, enrolled, sent to, or checked for deliverability.

## Executable offline coverage

tests/test_research_staged.py exercises the production HTTP adapter and actual staged pipeline with fictional companies: directory-only identity → official-domain search → literal contact-link reading → published email → fit review. It also covers search-result email reuse without extra page requests, page failures, ambiguity, administrative inbox exclusion, requested-role mismatch, alias/domain deduplication, budget stops before a request or before fit, pause/restart, uncertain requests and actual page/status counts.

The full current suite passes 526 tests, with one Windows symlink privilege skip. Chrome verifies the backend/UI journey using a disposable fake-provider workspace; 89 assertions pass. These results establish implementation behavior, not public-web recall or inbox deliverability.

## Live pilot, still pending owner execution

After reloading the normal desktop app, save a revised audience using five companies and a separately reviewed maximum (suggested starting cap $0.25). Keep general business fallback enabled if it is acceptable. Review the paid plan and approve that individual run. Include known companies from this set only when they fit the approved audience; a focused seed-company input is not implemented.

Record discovered names, verified domains, companies with relevant emails, distinct addresses, unresolved reasons, actual/reserved costs and elapsed time. Open each source to confirm address and role. Compare against the dated pages and inspect misses. Expand the target only after that measured trial. No pilot was run by the agent.

## Strategy 4 validation — 2026-10-08

`tests/fixtures/public_email_excerpts.json` records ten short excerpts observed on public pages on 2026-10-07. `tests/test_public_email_excerpts.py` exercises production parsing against ten published addresses and five negative controls. It covers explicit obfuscation, business inboxes, absent addresses, and a federated social handle that must not become an email.

This is an excerpt extraction benchmark, **not** a live search benchmark, founder-match recall score, or deliverability check. Source URLs and dates accompany each case. The current Niramai contact-page excerpt has no address; earlier observations above should not be assumed current.

Separate fictional-provider tests exercise cross-page founder attribution, invented-address rejection, unrelated namesakes, deduplication with multiple publication sources, partial budget stops, unchanged cached request bodies, and refusal to replay uncertain requests. Real-provider yield remains unmeasured until an explicitly approved small pilot.

Final local validation: 585 offline tests passed, one Windows symlink privilege skip; Ruff passed; 138 real-Chrome assertions passed using disposable fake providers. The production workspace was checked through authenticated read-only routes and remains in restricted review mode until owner desktop handoff.

## 2026-10-08 simplified workflow validation
594 offline tests passed, one Windows symlink privilege skip; final guidance changes also passed 35 focused tests. Ruff and diff checks passed. 139 real Chrome checks passed including direct enrollment without a separate approval/note and campaign attachment upload/download. Empty known-company fixture uses three search/fetch calls and zero model calls; empty discovery stops after two searches and zero model calls. These are deterministic fictional-provider savings, not a measured live yield improvement. The owner desktop server remains running with an update notice; restart is needed to load the new backend.
