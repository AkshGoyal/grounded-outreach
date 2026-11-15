# Campaign isolation and single-editor composer — 2026-10-10

## Verified findings

Both globally loaded drafting templates previously instructed every campaign to write
Star Threads cotton-thread sales emails (sample offers, Ludhiana and sales-specific
structure), including job-search campaigns. build_prompt selected these shared files
for every campaign. A fictional job-search brief reproduced the contradictory sales
context with and without a fixed closing. This is a verified prompt-contamination
cause, not proof that another campaign's database rows were fetched.

The inspected campaign, brief, recipient and draft queries filter by campaign ID or
follow the draft's own contact. LLM adapters make stateless requests: no shared
conversation history or drafting cache was found. Browser recovery keys include the
campaign path, but the message form allowed stale unsaved values to override saved
server text. Foreground drafting previously lacked the background worker's busy guard
and neither path recorded or checked generation provenance before storing results.

The owner's database and running process were not accessed. The exact historical
incident, old generated emails and which application version produced them remain
unverified. New regression tests reproduce the prompt issue and the stale-result risk
using fictional campaigns and temporary databases.

## Changes and responsibilities

- prompts/draft_email.md and draft_opening.md are neutral and derive purpose, sender
  facts, tone, length and response from the current campaign. Shared rules preserve
  grounding and uncertainty; they contain no old campaign's product or business.
- core/message_brief.py returns the natural-language editor source directly, without
  inserting a second configuration wrapper or requiring separate drafting fields.
- core/email_composer.py parses an ordered specification of generated instruction gaps
  and protected KEEP blocks. It normalizes CRLF transport to LF, removes one framing
  newline beside each marker, and preserves all remaining block text.
- core/drafting.py uses one structured model call per recipient. For marked editors,
  the model returns only indexed generated sections. Code validates those section IDs,
  checks generated claims, and inserts protected blocks in their original order.
- core/review.py preserves protected blocks in stored previews, including blocks that
  require a grounding decision; missing/altered/reordered blocks prevent approval.
  Protected wording never establishes an unsupported recipient fact by itself.
- Campaign creation/message templates provide one editor and a selection toolbar that
  wraps selected text in KEEP markers. Saved server instructions beat browser caches.
  Legacy copy and closing appear together in the editor, with the closing as KEEP.
  Saving that combined editor clears the external closing so it is not appended twice.
- campaigns.py validates file identifiers and preserves literal content inside marked
  editors, including HTML-like comments. Existing campaign files remain the generation
  source; the editor shows that same source. Structured legacy/API submissions remain
  compatible. Legacy text routes remain accessible and validate KEEP syntax.
- generation.py and core/generation.py create immutable campaign/source fingerprints.
  The web batch, background worker and CLI carry the same snapshot through generation
  and storage; new snapshots also retain the recipient evidence used for the request.
- SqliteStore validates campaign/contact identity, unchanged instructions and recipient
  context, then saves the draft and provenance atomically. Schema 11 adds
  draft_generations and identity guards. Existing campaigns, recipients, drafts and
  send history are preserved; older drafts retain an explicit unknown provenance.
- web/app.py and draft_jobs.py share one busy guard for foreground/background drafting.
  Overlapping work cannot replace the active campaign. Configuration editing remains
  free and cannot silently launch drafting. Failed/paused jobs retain saved progress.
- Review exposes the campaign, recipient and instruction version. Outdated generation
  prevents approval and launch until explicitly regenerated; old versions stay available.
  dispatch.py also checks campaign identity and protected blocks during send planning.
  Existing suppression, daily caps, durable claims and launch snapshots remain in use.

## How to use the editor

Describe the whole objective naturally. Optional KEEP blocks divide the generated
sections without extra form fields:

    Write a short job-search introduction using the reviewed company facts.
    [KEEP]
    I have already applied through the company's careers portal.
    [/KEEP]
    Explain my supplied AI/analytics experience and request a short conversation.
    [KEEP]
    Best regards,
    Keshav
    [/KEEP]

The model interprets the prose during the existing generation call; saving performs
no paid interpretation call. Objective/tone/length are model instructions, not brittle
keyword fields or mandatory configuration screens. The ordered KEEP specification is
parsed deterministically, and the model cannot supply or alter its protected sections.

Explicit {{name}}, {{company}} and {{designation}} variables inside KEEP text use
reviewed saved recipient fields. Unknown, malformed or unavailable values produce a
clear failure rather than invented information. Many published-inbox contacts have
no named person/title; company substitution is available when company is saved.

Generated text remains editable. Protected blocks must remain exact and in order to
approve. Fixed user assertions still undergo existing grounding checks. Sender identity
and opt-out footer remain part of the final preview and launch protections.

## Isolation and compatibility limits

The application is a single authenticated workspace, not a multi-tenant SaaS. Login
protects the workspace; all campaigns within it belong to that workspace. This change
does not invent a new user/tenant permission model.

Background generation is intentionally serialized, not a new distributed queue.
Instruction hashes include campaign identity, source copy/closing and composer version.
Bump COMPOSER_VERSION when shared generation semantics change. Historical drafts without
snapshots cannot retroactively establish which prompt produced them; no history is
rewritten or automatically regenerated. Saving a changed message invalidates unsent
approvals; regeneration is a separate explicit model action.

Campaign files and brief metadata still use the existing separate persistence stores.
The editor reads the actual generation source and snapshots make that source auditable;
this is not a database-only storage redesign. Direct external file edits are detected
when saving generated results and checking approval/launch. Ordinary application edits
are guarded while drafting/sending. This does not guarantee arbitrary concurrent manual
filesystem edits are atomic with an SMTP operation.

## Verification

Full offline run: 685 passed, 1 skipped (Windows symlink privilege). Final short-input
and partial-legacy compatibility refinements were subsequently verified in a 15-test
targeted run. Ruff lint/formatting and whitespace checks passed. The isolated Chrome
guided journey passed with the single editor, toolbar, stale cache and switching checks.
The separately maintained Playwright journey was adapted and syntax checked; it was
not executed. An elevated full run hit two Git ownership checks and one five-second
fake-worker timeout; the normal local-identity full run passed without global Git
configuration changes or relaxed test deadlines. Details are in IMPROVEMENT_PLAN.md.

Actual delegated work used three bounded specialists for isolation/storage, composition,
and UI/browser fixtures. Main-agent integration and an independent final review caught
the stale-source read and test-to-self guard gaps. No permanent agents were configured.
Tests use three deliberately different campaigns and fictional provider responses.
They verify context isolation, fixed wording/order, preview/persistence, regeneration,
stale response refusal, failed-job retries, worker overlap and preserved legacy data.
Browser QA verifies the toolbar, one editor, saved text and repeated switching/refresh.
Offline tests establish control/data integrity, not live model writing quality or delivery.
No real email, paid request, owner-data migration, deployment or publication was performed.
