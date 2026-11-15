# Email research implementation proposal

Status: core strategy 4 implemented locally; live provider yield remains unverified.
Prepared after inspecting the current scheduler and existing benchmark.

## User-visible outcome

Given an audience, desired contact role, target contact count and budget, produce relevant published business email addresses with evidence. Report exact requested-role matches separately from general business inbox fallbacks. Save results as they arrive under one audience. Reviewed contacts can be added to a campaign even if research is incomplete.

## Confirmed gaps

The prior production audit found successful searches and zero extraction requests because runs stopped before contact collection. Current strategy 3 improves that path but live usefulness is still unproven. The current collect_company function restricts its contact search to the official domain and filters all other domains out. NamedContact attribution requires name, role and email in the same quote. This excludes useful cross-page evidence. The current benchmark is mostly general inboxes and cannot validate founder-email quality. Passing fictional-provider tests is not a substitute for a dated public-web benchmark.

## Recommended design

Keep Parallel Search and Extract, OpenRouter for bounded structured interpretation, and the existing FastAPI/SQLite workspace. Use a deterministic resumable queue; the model may propose sources and identities, but code enforces budget, request idempotency, URL safety and evidence checks.

1. Normalize the audience into company criteria, geography, desired role, explicit fallback preference and CONTACT target. Do not add inferred must-haves. Distinguish candidate companies from matched contacts.
2. Search broadly for companies and people. Prefer official sources for identity, but retain directory, association, event and professional biography sources as evidence to inspect. Do not reject a discovered public email merely because official-domain resolution is unfinished; store it as unreviewed.
3. Read likely official team/about/contact pages, relevant PDFs and linked professional profiles. For missing named-role emails, run a bounded second search for the identified person plus company, role and contact details across public professional sources. Extract promising result URLs. External sources carry lower confidence and require identity corroboration.
4. Parse literal addresses, mailto links and explicit obfuscations in code. Deduplicate while retaining every source, retrieval time and quoted context. Never generate an address from a guessed naming pattern. Optionally parse safe ordinary HTML locally first; use a maintained public-URL/redirect/DNS/size/timeout policy before enabling local fetching. Parallel Extract remains the first implementation path so retrieval does not depend on an untested new crawler.
5. Link role, person, employer and address evidence across pages. Store evidence separately for each relation. A shared name alone is insufficient; require corroborating employer/domain/profile identity. Distinguish supported, ambiguous and missing relations. A generic mailbox remains generic even when a founder is mentioned nearby.
6. Assess company fit and contact role in a bounded structured model call. Reuse cached evidence and avoid one model call per page. Unknown optional company facts should not discard valid contacts; explicit required criteria and exclusions remain enforced.
7. Validate address syntax and domain mail routing locally where feasible. These checks are not proof of a working mailbox. An optional specialist enrichment/verification adapter may be enabled separately after public-web results are measured. Keep enriched results, verification outcomes and publication evidence distinct; catch-all and unknown statuses are not guarantees.
8. Persist each checkpoint and show results before the entire run ends. Resume the same queue; skip completed requests and previously evaluated identities. Uncertain paid calls require reconciliation, not automatic replay.

## Cost controls

Begin with a small discovery batch and finish contact retrieval for it before another discovery round. Preserve budget headroom for page reads and final evidence assessment using measured reservation estimates. Cache by normalized URL and retrieval freshness, and by company/person identity across audience versions while retaining source dates. Stop each candidate when its required evidence is sufficient; use bounded expansion only for promising missing contacts. Enforce both global and per-company spending limits. Measure cost per source-supported requested-role contact, not cost per API request. Do not recommend increasing budgets until stage metrics identify the bottleneck.

## User flow

Audience -> Find emails -> Live results -> Review contacts -> Add to campaign.
Place the editable search plan in an optional detail view, with a clear spending confirmation before paid execution. Show companies found, pages successfully read, exact-role emails, general inbox fallbacks, ambiguous matches, spend and a plain-language stop reason. Offer Pause, Continue, Edit audience and Use selected contacts. Preserve all existing ledgers, campaigns, credentials and attachment behavior.

## Implementation sequence

A. Add a diagnostic/benchmark mode accepting explicit seed companies/domains so discovery and extraction can be evaluated independently. Store stage counts, failures and costs without raw secrets.
B. Add contact/evidence records and candidate states; retain partial and external-source discoveries for review. Keep existing approved runs on their original request fingerprints.
C. Implement bounded cross-web person search and relation-level evidence matching, then evaluate against dated real pages.
D. Introduce the contact-target UI and incremental queue progress on the existing audience pages.
E. Enable optional paid enrichment only if the benchmark shows missing-public-email coverage is the actual limit.

Likely module boundaries: core contact/evidence models and scheduler; research API adapter; additive SQLite contact/evidence storage; web research status and review views; benchmark fixtures and runner. Any schema migration needs a backup and round-trip preservation checks before production use.

## Definition of working

Use at least ten dated examples including named founders whose addresses are publicly published, general-only inboxes, split-page identity evidence, same-name ambiguity, PDFs/obfuscation and pages with no usable email. Review exact ground truth before scoring. Start with seeded retrieval, then test discovery separately, then an end-to-end audience.

Report requested-role precision, recall of known accessible public addresses, fallback count, unsupported claims, pages read, costs, elapsed time and stop reasons. Proposed initial gates: zero invented addresses or unsupported role promotions and at least 80% recall of known accessible benchmark addresses. These are acceptance targets, not production claims. Missing unpublished emails must be reported honestly, not counted as a retrieval regression.

No paid research, verification service or real email was authorized or executed for this proposal. A live provider pilot remains separate from free public-page inspection and offline regression tests.

## Primary references

- Parallel Search and Extract together: https://docs.parallel.ai/extract/best-practices
- Source policy tradeoffs: https://docs.parallel.ai/resources/source-policy
- Optional email finder/verifier interface: https://hunter.io/api-documentation/v2

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
