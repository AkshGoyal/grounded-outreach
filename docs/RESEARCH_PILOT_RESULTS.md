# Research pilot comparison — 3 October 2026

All four bounded runs completed in Cloud. **15 candidate records assessed; $0.407160 accounted against the $1 ceiling.** All records remain pending review and none is campaign-ready.

| Brief | Discovery method | Assessed / discovered | Cost, USD | Literal email addresses retained | Automated email candidates, pending review |
| --- | --- | --- | --- | --- | --- |
| textiles | custom | 5 / 5 | 0.055438 | 0 | 0 |
| textiles | findall | 5 / 5 | 0.150933 | 4 | 2 |
| jobs | custom | 4 / 4 | 0.047644 | 2 | 0 |
| jobs | findall | 1 / 1 | 0.10956 | 0 | 0 |

These contact/candidate counts are automated source-presence checks, **not verified leads**. The two automated textile FindAll email candidates contain a wrong-company contact (DGM Textiles) and an unresolved generic-profile identity (Garment Manufacturer Tirupur). Both need rejection or identity resolution before use.

## Costs and limits

OpenRouter reported usage: **$0.102024**. Parallel tariff estimates: **$0.265**, including two $0.10 previews, 19 search requests and 46 extracted URLs. Retained reservations: **$0.040136** (the rejected Cloud request plus the earlier handoff reservation). These are conservative accounted costs, not confirmed invoice charges.

Each comparison stayed below $0.20, 8 searches, 20 extracted URLs and 5 companies. Both planning calls used $0.003449 in reported usage; planning plus carried reservations totals $0.043585, below $0.10. No paid requests were added after the four samples completed.

## What the measurement shows

Custom discovery was cheaper for both briefs and found four job candidates versus one FindAll preview match. FindAll returned more textile contact text, but ownership errors and weak location evidence prevent treating that yield as verified. This small sample does not establish a winner or a cost per usable lead. Keep D-024 unchanged while improving source verification.

The shared pipeline loses real published contact text when the model alters quotes or the assessment context omits a footer. The supplementary source-email-review.csv contains **16 literal email texts across 9 company records** from inspected apparent company pages already cached by these runs. This is a separate review queue, not approved contacts or corrected automatic yield. A company may still fail the garment/product/location brief.

## Source-review findings

| Run | Company | Finding |
| --- | --- | --- |
| textiles-custom | Tirupurhub | Model changed Tirupur to Tiruppur in quotes and combined separate headings. Official page contains a business email; the checker rejected its association quote. |
| textiles-custom | S.A Clothing | Cited evidence establishes fabric manufacturing, not garment manufacturing. Contact retrieval also includes Sana Clothing, which is a different name/domain. Do not treat the two supported labels as confirmed fit. |
| textiles-custom | SSM Weaving Mills | Model stitched separate passages together with ellipses and generated nonliteral address/association quotes. Saved official pages contain two email addresses for review. |
| textiles-custom | Saini Knitwears | Location quote matches a retrieved contact page; manufacturer quote and phone association do not match. Confirm company identity across sainiredfort.com and sainiknitwears.com and whether any telephone is a marketplace relay. |
| textiles-custom | Tiruppur Apparel Exports | Manufacturer heading is literal, but proposed location quote combines text. Official page contains an email outside the short assessment context; product fit and actual facility still need review. |
| textiles-findall | Santex Inc India | Manufacturer evidence and one official-site phone match; location quote fails. Saved official page contains two emails not retained by the model assessment. |
| textiles-findall | KG GARMENTS | Two emails and two phones are literally published on kggarments.com. Location assessment quote fails despite an address on the site. Confirm identity, manufacturing operation, contact purpose and freshness. |
| textiles-findall | DGM Textiles | Reject the proposed contact association: itsdgm.com lists Lagos Island, Nigeria, while the company profile is for an Indian textile exporter. A second retrieved dgm.world page belongs to a different business too. Literal quote presence did not establish ownership. |
| textiles-findall | Garment Manufacturer Tirupur | Hold for identity review: generic LinkedIn profile name is not evidence of a manufacturing facility or a demonstrated link to tirupurclothing.com. Published contact text exists but cannot establish this association. |
| textiles-findall | Triton Garments | No retained contacts or literal location quote. Contact search included thetritonco.com; association with the intended garment manufacturer is unproven. |
| jobs-custom | De-X AI | Reject/hold the contact association: directory candidate De-X AI was paired with DexaAI Automation. Retrieved contact page states United States, and India presence remains unknown. |
| jobs-custom | Incubxperts | Official site contains careers and general business emails. Autonomous-agent/service language does not establish a named proprietary AI software product; assess product-versus-consultancy fit. |
| jobs-custom | Fractal Analytics | Official contact page contains hiring support and HR helpdesk emails, but proposed criterion/address/association quotes combine or alter source text. Confirm recruiting purpose and own-product suitability; no active early-career role was established. |
| jobs-custom | Bytesview Analytics | General email and careers portal are literally published on bytesview.com. The cited India statement is a directory-wide Noida heading, which does not establish this company location; own-product and current-role evidence is incomplete. |
| jobs-findall | Fuel4Media Technologies Pvt. Ltd: Digital,Mobile & Emerging Technologies, Development, AI | FindAll matched custom AI development services, which does not prove an owned AI product. The official page publishes job/sales emails; model used obfuscated values and a nonliteral combined association quote. No current role established. |

## Implementation and validation

Confirmed HTTP 401 recovery uses an explicit recovery key while preserving the original charged reservation. A separate conservative entry carries the earlier handoff reservation. Network failures and unreviewed outcomes still cannot replay automatically.

Criterion checking now accepts the declared short key or its declared description, allowing case, whitespace and final-period formatting. It rejects unrelated labels and duplicate claims; quote and contact checks remain unchanged. All 15 records were revalidated offline from the original cached responses/source maps, preserving earlier outputs under validation-audit. No extra model calls were used to fix parsing.

325 offline tests, lint and formatting checks passed. The multi-campaign navigation plan in docs/PLATFORM_PLAN.md is unchanged. Human-verified counts and cost per usable lead remain null.

## Next increment

Resolve company identity and official domains before contact retrieval. Extract literal contact text and company-specific evidence without model paraphrasing; keep contact sections available rather than taking only the beginning of each page. Distinguish garment production from fabric supply, proprietary products from services, and company-specific facts from directory-wide headings. Test these failures on the saved corpus before another paid run or UI integration.

The planned UI still groups projects, research runs, reusable lead lists and campaigns with persistent navigation, purpose/tags/status filters, provenance, shared identity, cross-campaign outreach checks and global suppression. This pilot does not implement that UI.
