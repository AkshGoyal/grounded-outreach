# Bangalore AI startup founder benchmark — 2026-10-04

The operator requested a small real test of mostly Bangalore AI startups, published
founder email addresses, and source-backed details for later job-outreach drafts.
Vacancies, sender qualifications and email delivery were outside this test.

## Execution and accounting

Parallel and OpenRouter were called successfully from Cloud using configured
credentials, without printing them. The production planning/research path produced
three candidate companies. A separate founder-focused diagnostic then revisited
the same companies; it did not replace or silently approve the baseline records.

The test appended `founders-bangalore-v1` to the original durable pilot ledger.
Its $0.20 allowance remained inside the original combined $1 ceiling. All previous
comparison entries and retained reservations were preserved.

| Measure | Result |
|---|---:|
| Candidate companies | 3 |
| Verified direct founder emails | 0 |
| General company inboxes, not founder contacts | 2 |
| Manually reviewed personalisation facts | 6 |
| Source-backed draft opening hooks | 3 |
| Search requests | 8 |
| Extracted URLs | 20 |
| Model requests | 9 |
| Additional test accounting | $0.083969 |
| Combined pilot accounting | $0.491129 |

Combined accounting includes $0.157993 reported model usage, $0.293 Parallel tariff
estimates, and $0.040136 retained reservations. These are conservative ledger
figures, not a provider invoice. Search and extraction limits are exhausted for
this arm; do not reset the budget or make additional paid calls to fill its sample.

## Quality findings

This test has not demonstrated a usable founder-contact list. Two founders were
identified on official company pages; another founder candidate appeared on a
public professional profile and still needs official corroboration. One company's
Bangalore location was not established. Startup-stage qualification also remains
incomplete. General inboxes must not be relabelled as direct founder addresses.

The sources do support product-specific personalisation. Manual review retained
six facts and three opening hooks, but removed model embellishments: a product
mission presented as a measured result, an unsupported financing description,
and recognition not independently verified. A wrong-company contact-broker result
was excluded. A quote existing verbatim is necessary but does not establish that
the model's summary faithfully states its meaning.

During diagnosis, source-context selection was found to favour repeated terminal
examples containing `@` and omit founder passages. The production selector now
prioritises founder roles, real email patterns and the requested location, skipping
covered windows. Regression checks passed offline. No paid rerun measured the
quality effect of this code change.

The founder profile schema and contact-ownership checks remain an experiment;
they are not yet integrated into production lead storage or the frontend. The
next product increment should distinguish company fit, founder identity, direct
contact ownership and draft evidence, with editable clarification before research.
Canonical URL deduplication and targeted official founder/profile retrieval should
precede any expansion of paid search. Changing providers alone has no established
benefit from this sample. HubSpot was not called in this benchmark.

## Artifacts and validation

Private artifacts remain ignored under `data/research-pilot-v1/founders-bangalore-v1/`:
`results.json`, `founder-profiles.json`, cached sources, `accounting.json`,
`drafting-evidence.json`, and the readable `founder-review.md`. All leads remain
pending; no contacts were enrolled, no sender skills inferred, and no emails sent.
The original four-way comparison remains unchanged.

The full offline suite passed with 361 tests after the context fix. Focused budget,
replay, source and contact-ownership checks cover the new benchmark. See
[frontend product plan](FRONTEND_PRODUCT_PLAN.md) for the proposed user flow;
that document does not claim the redesigned frontend has been implemented.

## Broadened contact review after operator feedback

The operator subsequently accepted HR/recruiting and senior-management addresses
as alternatives to founder email, and approved the frontend product plan. The
original founder-only benchmark and its zero-direct-founder-email result remain
unchanged. Its request limits were not reset, and no additional paid provider
requests were made.

A separate assistant-directed public-site review inspected the original companies
and six additional AI companies. Twenty-seven HTTPS page requests, including two
source rechecks, found two official-site HR/recruiting addresses with relevant
product facts and Bangalore/Bengaluru presence. This is manual discovery evidence,
not proof that the automatic AI pipeline now has equivalent contact yield. One
company's displayed HR address links to its support inbox; the mismatch is flagged
for review. The other address is explicitly labelled Careers. Department inboxes
are recorded as such, not as named founders or executives. Support/sales/general
inboxes and a text-concatenation email artifact were excluded from this shortlist.

Private artifacts in the same ignored folder: `broadened-contact-review.json`,
`broadened-contact-review.md`, `job-outreach-review.csv`, cached public-page text
and `broadened-import-preview.json`. Two source-backed product facts and two
opening hooks accompany the shortlist. Both CSV rows pass the production import
preview's structural checks; that does not verify mailbox existence, resolve the
link mismatch or approve contacts. No production campaign was modified, enrolled
or sent. Combined pilot accounting remains **$0.491129**.


## Live production workflow test — 2026-10-05

The agreed broader contact-role brief was tested through actual saved-intake,
planning and research-approval routes using the production research adapter. An
isolated SQLite run and the original pilot ledger both reserved before every paid
request. The run cap was $0.12; the original combined ceiling stayed $1.

Eight paid requests completed, accounting $0.022986. Total pilot accounting is now
**$0.514115**. The two-company target returned one candidate, **Spike AI**, on
`getspike.ai`. Evidence included the product heading “Spike — autonomous marketing
for B2B” and the careers statement “Work from anywhere in India with main office
in Bangalore.” The saved ownership/product uncertainties still need human review.

Only a general hello inbox was extracted, from the site's Contact footer. It is
not a confirmed founder, HR/recruiting or senior-management address. Requested-role
usable yield for this tiny run is therefore **zero confirmed**, despite one company
with a published email. All results remain pending. No list/campaign was created,
no real draft was generated and no mail was sent.

Private results, complete retrieved pages, source quotes, timestamps, call costs
and the isolated DB are in `data/research-pilot-v1/workspace-careers-v1/`. They are
not committed. Do not import the general inbox as meeting the requested role.
The automated pipeline worked; this one-company sample does not establish adequate
contact coverage. The earlier manually reviewed HR shortlist remains a separate
manual result, not automated yield.

Next research improvement: separate company discovery from requested-contact
resolution, prioritize explicit contact/role context and relevant careers/team
pages, and measure confirmed founder/HR/management yield before considering paid
verification/enrichment. Verification cannot establish the person's role or fix
wrong company identity. A CRM such as HubSpot can store approved leads; it is not
part of the current discovery pipeline and would not fix this contact gap alone.
