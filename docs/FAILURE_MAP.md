# Failure map

## Campaign acceptance and recovery — 2026-10-05

| Symptom | First check | Recovery |
| --- | --- | --- |
| Launch review changed/expired | Added approvals, draft/footer/sender change, age or restart | Reopen Launch, inspect current emails and confirm again |
| Sending stops on uncertainty | History pending entry and provider Sent | Keep blocked; don't retry merely because arrival isn't visible |
| Fewer daily slots than accepted count | Pending messages created today | Uncertainty consumes capacity; don't clear records |
| Reply cannot repeat | Saved reply claim and message | Expected after acceptance/uncertainty, including reopening triage or restart |
| Answer reaches daily limit | Accepted + pending sends across campaigns | Wait until the next UTC day |
| Saved draft test did nothing | Consent, saved version, signed request and previous outcome | Inspect results before a fresh explicit request |
| Backup refuses active work | Research/draft/send progress | Finish/stop work before bundling |
| Backup refuses missing key | Original key or configured matching key | Restore it first; a generated replacement is not a restore |
| Restored account cannot decrypt | Key beside DB and environment override | Use original key; configure provider clients/reconnect revoked consent |
| General inbox for founder/HR research | Contact quote/ownership on original source | Keep pending/remove; don't relabel it as a requested role |
| Live pilot bridge stops | Original ledger and isolated SQLite reservation | Keep both; known completed calls are reused, uncertainty stays blocked |

History is read-only; there is no button for clearing uncertainty. Full restoration
is in LAPTOP_SETUP.md. Older answers lack schema-9 claims: inspect pre-upgrade
conversation history before attempting another answer.

## Research pilot (2026-10-03)

| Symptom | First place to check | Recovery |
| --- | --- | --- |
| Missing Parallel key | `research_pilot check`, key names only | Add `OUTREACH_PARALLEL_API_KEY` to the chosen ignored `.env` |
| OpenRouter HTTP 401 | Correct `.env` path and key in provider dashboard | Replace the rejected key; reconcile the existing reserved call before rerunning; do not delete the ledger |
| Budget stop | `research_pilot report` and `ledger.json` | Review partial results; no automatic increase |
| Uncertain POST outcome | Reserved ledger entry and provider request history | Reconcile before retry; normal resume never duplicates the charge |
| FindAll polling timeout | Saved FindAll run ID | Resume the same command to poll that run |
| No email or failed quote check | `sources-N.json` and rejected contact reasons | Keep unknown/pending; never synthesize an address |
| Pilot locked | Running processes and `pilot.lock` | Remove the lock only after confirming the process ended |

Initial live probe: OpenRouter returned 401. Reported spend is $0; the local
ledger conservatively retains $0.020068, which is a reservation, not a bill.

> **Status: current to the end of v1** — import, drafting, review and sending.

**How to use this file:** something is wrong → find the symptom in §1 → follow
it to the component section → look where it says to look first.

---

## 1. Symptom index

*The fastest path in. One line per observable symptom.*

| Symptom | Likely component | Go to |
| --- | --- | --- |
| `recipient is suppressed: refusing to record this send` | the database guard doing its job | §2.4 — this is correct behaviour, not a bug |
| A `pending` message row that never became `sent` | a crash or a failure mid-send | §2.4 |
| The wrong column was treated as the email address | `core/importing.py` guessed | Preview showed it; re-run with `--email-column` |
| Rows missing after an import | rejected or duplicate | The preview lists every one with its spreadsheet row number |
| A draft is blocked and you think it should not be | the specifics check | §2.6 — the reason names the exact word |
| A draft goes out with an invented detail | the known first-word gap | §2.6 |
| App refuses to start, "Configuration is invalid or incomplete" | `config.py` | §2.1 |
| `database is locked` | `adapters/db.py` | §2.2 |
| Tests pass locally, fail on another machine | dependencies | §2.3 |
| `NotImplementedError: ... lands in Phase N` | an adapter stub | Expected. That phase is not built yet. |

## 2. Per-component failure modes

*One subsection per component in `ARCHITECTURE.md` §2, using this shape:*

### 2.1 — `config.py`

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | A setting a command needs is missing | `ConfigError` listing the exact `OUTREACH_*` variables | The error names them; commands check before doing any work | Add them to `.env` |
| 2 | A value is present but blank | Treated as missing, not as a value | `require()` in `config.py` | Supply a real value |
| 5 | A value is present but malformed | Fails at load, before any command runs | `config.py` field types | Fix the value |
| 3 | `.env` exists but is not being read | Settings load with unexpected values | Working directory — `env_file=".env"` is relative | Run from the repo root |

**Blast radius:** total. Nothing runs without settings — which is the intent.

**Safe to retry?** Yes. Loading settings has no side effects.

### 2.2 — `adapters/db.py`

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | Two writers at once | `database is locked` after ~5s | `busy_timeout` in `connect()`; D-006 notes SQLite is single-writer | Serialise the writers; do not raise the timeout to mask it |
| 2 | `data/` not writable | `sqlite3.OperationalError: unable to open database file` | Permissions on `data/` | Fix permissions |
| 3 | Database file lost or corrupted | Everything empty, or `database disk image is malformed` | Whether a backup exists at all | §4 — and note there is no backup procedure yet |
| 4 | Foreign keys silently off | Orphaned rows appear | SQLite disables FKs *per connection*; `connect()` sets the pragma | Use `connect()`, never raw `sqlite3.connect` |

**Blast radius:** all stored state — recipients, suppression, drafts, threads.

**Safe to retry?** Connecting, yes (bootstrap is idempotent). Writes, not
necessarily — that question becomes real in Phase 2.

### 2.4 — Suppression and sending

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | A suppressed address is written to | `SuppressedRecipientError`, or `sqlite3.IntegrityError` from the trigger | Neither is a bug — both are the guards working | Nothing to fix |
| 2 | Addresses normalised inconsistently | Someone who opted out gets another email | `core/normalize.py` — it must be the *only* place addresses are lowercased | Route every path through it |
| 3 | Crash between writing the row and sending | A `messages` row stuck at `pending` | Query `WHERE status = 'pending'` | Decide per row whether it actually went out; the row exists precisely so this is answerable |
| 4 | Send fails | Row marked `failed`, exception raised | `core/sending.py` | Retry, or leave it — nothing is hidden |

**Blast radius:** the do-not-contact list is the one piece of state where an
error has a real-world cost — emailing someone who explicitly asked you not to.

**Safe to retry?** Refusing is. A failed send is, but only because the row
records the attempt; retrying without that record risks a duplicate.

### 2.5 — Importing a list

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | The email column is guessed wrong | Preview names a column that is not the address | The `Columns` block printed before anything is written | Re-run with `--email-column "Exact Header"` |
| 2 | Excel mangles a value (GST code, phone) | Odd text in evidence | `adapters/spreadsheet.py` reads everything as text on purpose | Check the source cell's formatting |
| 3 | A whole file is rejected | "No column looks like an email address" | Headers — the guess needs either a recognisable header or values that look like addresses | Pass `--email-column` |
| 4 | Re-importing seems to do nothing | 0 accepted, many duplicates | Correct behaviour — the campaign already has them | Nothing to fix |

**Blast radius:** contacts only. Import writes nothing else and cannot send.

**Safe to retry?** Yes, always. Without `--commit` nothing is written at all,
and with it, addresses already in the campaign are skipped.

### 2.6 — Drafting and grounding

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | A true sentence is blocked | "Nothing we hold mentions 'x'" | The word is genuinely not in the evidence — add it to the spreadsheet, or accept the block | Either is fine; over-flagging is the intended bias |
| 2 | A fabrication gets through | Recipient mentions something you never said | Was the invented word the **first word** of its sentence? That is the known gap, recorded in `test_a_lie_as_the_very_first_word_slips_through` | Tighten `specifics_in`, and accept more false alarms |
| 3 | Everything lands in the maybe pile | Long flag list, nothing grounded | The prompt is producing waffle, or the contact has little evidence | Check the evidence first — a contact with only a company name cannot produce a grounded email |
| 4 | Claude is unreachable | `LLMError: unreachable after 3 attempts` | Network, or the API status page | Retried automatically for 429/5xx; a 400 is not retried because it would fail identically |
| 6 | `TypeError: ... unexpected keyword argument` | A function signature and its caller drifted apart | Whether a test actually calls the function *the CLI calls*, not just the one underneath it | Happened once: `draft_email` gained an argument in the caller but not the callee, and no test called `draft_email` at all. `tests/test_cli_draft.py` now drives the command end to end |
| 7 | A subject line blocked for a word that is clearly true | Title Case subject — every word counts as a specific | The reason line under SUBJECT, which is now printed | Prompt v2 asks for sentence case; plurals now match singulars |
| 8 | Drafts read as machine-written despite passing | Raw cell text pasted in ("(12 t)", slashes, brackets) | The prompt — the checker rewards restating evidence, which can pull a model toward copying it verbatim | Prompt v2 tells it to rephrase, and to drop any figure whose unit is unclear |
| 5 | Claude declines the request | `LLMError: declined to answer` | The prompt content | Server-side fallback is enabled, so this means the fallback declined too |

**Blast radius:** drafting only. Nothing here can send; a blocked draft simply
does not proceed.

**Safe to retry?** Yes. Drafting has no side effects — it writes nothing until
a draft is accepted.

### 2.7 — Review and sending

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | Approve is refused | Red message naming a line and a word | That word is not in the recipient's evidence or your campaign copy | Reword the line, or add the fact to the spreadsheet and re-import |
| 2 | `check` fails to log in | "Zoho refused the login" | Two-factor sign-in needs an app-specific password | Zoho: My Account → Security → App Passwords; put that in `OUTREACH_MAIL_PASSWORD` |
| 3 | `check` cannot reach the server | "Could not reach smtppro.zoho.in:465" | Network, or a wrong host for your Zoho data centre | Zoho: Settings → Mail Accounts → IMAP/SMTP shows the exact host |
| 4 | A send run stops after the first email | "stopped — ..." | A login failure: every other email would fail the same way, so it stops | Fix the login, re-run — already-sent contacts are skipped |
| 5 | One contact failed, others sent | "FAILED ... refused the address" | The address is wrong or the mailbox does not exist | Correct it in the spreadsheet; the failed one can be re-sent |
| 6 | A contact shows "already written to" but you are not sure it arrived | A `pending` message row | A crash mid-send — it may or may not have gone | Check Zoho's Sent folder. The tool will never resend a pending one on its own |
| 7 | Everything held back as "today's limit" | `OUTREACH_DAILY_SEND_CAP` reached | Deliberate, for a domain that had never sent mail | Wait until tomorrow, or raise the cap once replies show mail is landing |
| 9 | Emails land in Gmail's **Promotions** tab | Arrives, but not in Primary | Not an authentication problem — that would be spam. It is content | Remove mailing-list signals (D-018, done); test with a real `--draft`, not the test message; avoid links, images and words like "free" and "offer" in early emails; change one thing at a time and `send-test` again. Replies are what moves a new domain into Primary over time |
| 10 | A good sentence was taken out as "repeats the closing" | It used a word the closing owns ("sample", "dispatch") or shared three distinctive words with it | The reason under the struck-out line in review | Put it back reworded without the closing's word — a line that still repeats cannot be approved (D-020) |
| 11 | The opening offers samples or signs off | No closing file for that campaign, so the full-email prompt was used | `uv run outreach check` shows "+ fixed closing" per campaign | Create `campaigns/<id>.closing.md`, then `draft --campaign <id> --save --redraft` |
| 12 | A draft is held back as "repeats — …", or the review page says to delete lines | It was written before the closing existed, or an edit added an offer or sign-off | The line and the reason are shown | Delete those lines in review, or `draft --campaign <id> --save --redraft` |
| 8 | Emails land in spam | No replies at all; recipients say they found it in spam | SPF, DKIM and DMARC for starthreads.in — Zoho shows each as verified or not | Finish Zoho's domain setup; lower the cap; send to people likely to reply first |

**Blast radius:** this is the only part of the system that reaches a real
person. Every guard in it errs towards not sending.

**Safe to retry?** `send` without `--really`, always. With it, yes —
already-sent and interrupted contacts are skipped, so a re-run only sends
what has not gone.

### 2.8 — Replies (D-023)

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | The inbox can't be read | Inbox page: "The last check failed: Zoho refused the inbox login" | IMAP access is off, or `OUTREACH_MAIL_IMAP_HOST` is missing | Zoho Mail → Settings → Mail Accounts → IMAP Access → on; `OUTREACH_MAIL_IMAP_HOST=imappro.zoho.in`; Setup → "Test the Zoho login" |
| 2 | A reply you can see in Zoho isn't in the Inbox | Not listed, even under "All" | It didn't match any email we sent — e.g. sent from another address with a new subject | Handle it in Zoho. Only replies are stored, by design |
| 3 | A reply shows "Not read yet" | Grey label | The AI key is missing or the model call failed | It is read again at the next check; Setup → "Test the AI key" |
| 4 | A "yes" was read as "not interested" | The company is on the do-not-contact list | Inbox → All → the reply's summary and text | The tool has no undo for the do-not-contact list, on purpose. If they clearly asked to hear more, answer them from Zoho |
| 5 | A detail they gave isn't shown | Address in the reply, but not under "Details they gave" | The model's copy didn't match the reply word for word, so code dropped it | Copy it from the reply text shown on the same page |

**Blast radius:** reading is read-only, and nothing is sent without a person.
The only automatic action adds addresses to the do-not-contact list.

### 2.3 — Dependencies

| # | What can fail | Likely symptom | Where to look first | Fix / recover |
| --- | --- | --- | --- | --- |
| 1 | Versions drift between machines | Passes here, fails there | `uv.lock` — is it committed and current? | `make install`, which installs from the lock |

---

## 3. Incidents that must never happen silently

*The short list of failures that are unacceptable to discover late — e.g. a
send to a suppressed address, an ungrounded claim reaching a recipient, a
follow-up to someone who already replied. For each: the guard that prevents it,
and the alarm that fires if the guard is bypassed.*

| Must-never-happen | Guard | Alarm / detection |
| --- | --- | --- |
| A send to a suppressed address | **Two guards.** `core/sending.py` refuses first; the database trigger rejects the row even if that code is bypassed | 12 tests in `tests/test_suppression.py`, one of which writes straight to the table to prove the second guard fires |
| An ungrounded claim reaching a recipient | Not built yet — Phase 4 (I-3) | — |
| A follow-up to someone who already replied | Not built yet — Phase 8 (I-5) | — |
| A real credential committed to git | `.gitignore` excludes `.env`; `.env.example` holds only placeholders | Verified against real paths before the first commit |
| Recipient PII committed to git | `.gitignore` excludes `data/`, `*.csv`, `*.xlsx`, `*.db` | Verified against real paths; fixtures re-admitted explicitly |

## 4. Recovery runbooks

**Research pilot in Cloud (2026-10-03):** configured/ready credentials can still
be expired. The initial HTTP 401 was confirmed as expiry; after the operator
updated Cloud configuration, the read-only authentication check returned 200.
Recovery uses an explicit marker for the confirmed HTTP 401, preserving the
original reservation and charging a separate recovery entry. Network timeouts
and unreviewed outcomes remain blocked. Never clear the ledger to replay it.
Recheck Cloud observations and authentication after credential updates; a new
checkout must retain the ledger and cached responses. Details and test isolation:
[RESEARCH_PILOT.md](RESEARCH_PILOT.md#cloud-comparison-completed-2026-10-03).

**Pilot source-review failures:** company names can collide (DGM Textiles versus
a Nigerian business), directory headings can masquerade as company-specific
facts, and a model can alter literal quotes or miss contact footers. Compare
`results.json`, `sources-N.json`, `raw-sources-N.json` and cached assessments;
use `review-queue.csv` and `source-email-review.csv` as review aids, never import
them automatically. Full findings: [RESEARCH_PILOT_RESULTS.md](RESEARCH_PILOT_RESULTS.md).

*Step-by-step procedures for the messy cases: a partially-sent campaign, a
revoked API key mid-run, a bounce spike, a domain reputation drop.*

**Historical backup gap (now closed for browser workspaces) — database backup.** The SQLite file will hold every recipient,
suppression record and reply. There is currently **no backup procedure**, and
the file is git-ignored precisely because it must not go to GitHub. A
destination and a cadence are needed before the first real campaign, not after.
Tracked as a Phase 2 exit requirement.

## Integrated workspace (2026-10-04)

| Symptom | First place to look | Recovery |
| --- | --- | --- |
| Gmail/Zoho verification fails in Codex Cloud | Cloud TCP policy; no public SMTP/IMAP route exists here | Use a Cloud application host with public mail connectivity; do not bypass the sidecar |
| Gmail or Zoho login rejected on a capable host | Email accounts, MFA/app password, Zoho region/plan/IMAP access | Correct account settings and verify both protocols; no message is sent during verification |
| An account cannot be unlocked | Original encryption key beside DB or configured credential key | Restore that key or reconnect the account; never expose the key in logs |
| Campaign launch refuses account | Account verified status | Save the draft freely; verify sending and inbox access before launch |
| Research stopped after timeout/HTTP error | Run error and request-spending panel | Retain reservation; reconcile provider outcome; Resume will not replay an uncertain call |
| Research stopped at spending limit | Run/daily budget totals | Review saved results, or explicitly authorize a new bounded run; never clear history |
| Research shows wrong company or unsupported fit | Source evidence and criterion quotes | Remove lead or verify fit with an explicit note; no automatic enrollment |
| Lead enrollment rejected | Approval, suppression, prior campaign/company history | Review leads or acknowledge prior outreach; suppressed contacts remain blocked |
| Changed campaign no longer sends | Unsent drafts reset to review | Rewrite or recheck and approve again |
| Background work stopped after restart | Saved research state or pending send records | Explicitly resume known research; inspect pending SMTP sends before retrying |
| Inbox message associated with wrong campaign | Receiving account, thread IDs and campaign identity | Matching is account-scoped; retain original account after send history |
| Cloud browser sign-in/host rejected | App password, allowed-host settings and HTTPS proxy | Configure the actual host and sign in; do not disable same-origin protection |

The database backup also needs separately preserved campaign text and encryption key.
Run one application process and avoid concurrent CLI senders; queued workers and
cross-process send leases remain a future scaling increment.

For Codespaces previews, use `bash .devcontainer/preview.sh`, keep port 8000
Private, and select Open in Browser rather than an embedded preview. If the app
stops, inspect the terminal or restart the stopped Codespace. Missing research keys
must be added to GitHub Codespaces secrets separately from Codex Cloud. Restart the
Codespace after adding them. This preview is not a permanent campaign host.

The separate phone HTML demo may display without working controls in iPhone Files.
Use an HTTPS static host and Safari instead. `render.yaml` prepares this sample-only
host but requires the operator's Render/GitHub connection. If the deploy button
cannot resolve the private repository, select New → Blueprint and the pilot branch.
No Render URL exists until that deployment succeeds. Demo edits never update the
Python application; its research and sending are explicitly simulated.

Founder research can return a general inbox without identifying a founder's
address. Keep contact ownership separate from company fit; never guess an address
or promote a general inbox as direct contact. Quote-presence checks do not prove
summary fidelity: distinguish goals from results, and do not invent financing or
recognition. Broker results can refer to another company with a similar name.
Repeated terminal examples containing `@` previously displaced founder passages;
source-window prioritisation now has a regression check. Its live quality effect
is unmeasured. The founder benchmark exhausted its 8-search/20-URL limits with
zero direct contacts; do not bypass those limits by resetting the ledger.

A public page can display an HR email while its mailto points to support. Review
the HTML association, keep the mismatch beside the recipient and do not treat
format/import acceptance as mailbox verification. Public text parsing can also
concatenate labels into fake addresses; compare candidates with the original
visible text/link before accepting them. The broader shortlist is manual research
and must not be used to claim the automated founder experiment improved.

## Saved intake and mobile review

- Missing company/location/contact roles: the draft is saved but planning stays
  blocked. Open the run and answer the displayed questions; no mailbox is needed.
- Missing planning authorisation or provider settings: no planning worker starts.
  Saved preferences remain available; confirm the paid action or configure providers.
- Invalid values: the form returns HTTP 400 with the entered text/choices retained.
- Started audience edit: rejected by storage and routes. Keep history and create
  a new audience; do not clear checkpoints to edit the original scope.
- Browser storage blocked: refresh restoration may be unavailable, but Save draft
  persists in SQLite. Paid checkboxes are never restored from browser storage.
- Published generic contact with requested HR/founder role: Needs review remains
  pending. Check source context; preferences do not automatically validate ownership.
- Filtered bulk review: selection is limited to displayed records. The return URL
  retains filters; zero selection disables actions.
- Phone page access: Chromium checks do not establish iPhone Safari compatibility
  or provide a public app URL. A real HTTPS deployment is still needed.

## Campaign preparation, message and selected draft review

| Symptom | First place to check | Recovery |
| --- | --- | --- |
| Saved campaign cannot draft | Message tab: topic, introduction, desired reply | Complete and save the brief; partial save makes no model call |
| Verified account still cannot launch | Message copy and campaign status | Complete message, resume if paused and reapprove affected drafts |
| New campaign ignores environment mailbox | Campaign sender selection | Choose and verify its account; this prevents cross-campaign sender mistakes |
| Selected bulk approval does nothing | Selection, confirmation, current IDs and campaign membership | Review/select current drafts and confirm; foreign/stale IDs cannot approve |
| Some selected drafts remain in review | Grounding, ambiguity, suppression | Inspect checks and edit; selection never overrides them |
| Old draft version cannot approve | Current version in Draft queue | Review the latest version; old versions remain history |
| Internal reviewer note no longer supports a claim | Recipient facts and original sources | Use source-backed evidence; audit notes/internal IDs are excluded from drafting |
| Message or account change removes approvals | Changed text/ending/identity | Review unsent drafts again; sent history stays preserved |
| Account change rejected after outreach | Pending/sent message history | Keep that campaign's account; create a separate campaign for the new sender |
| Structured fields empty after raw editor save | Advanced raw copy was saved | Raw copy is now authoritative; save a structured brief only when replacing it |
| Invalid campaign/message form | Displayed field error | Correct retained input and save again; validation errors do not echo credentials |
| Approval checkbox not restored after refresh | Browser restoration consent exclusions | Read and confirm the action again; saved facts survive separately |

Migration from schema 6 adds `campaign_briefs`; existing contacts/settings/copy remain.
Back up SQLite, campaign files and credential key together before host updates.
Chromium layout checks use fake providers; real iPhone access still needs HTTPS hosting.

## OAuth and test mail

| Symptom | First check | Recovery |
| --- | --- | --- |
| Sign-in disabled | HTTPS origin, allowed hostname, workspace password and provider client settings | Complete OAUTH_SETUP.md and restart; configured status is not live authentication |
| Callback mismatch/expired sign-in | Browser cookie, ten-minute state, canonical host and exact registered callback | Open the canonical HTTPS app and start again; never paste codes/tokens into chat |
| Google refuses consent | Enabled Gmail API, test user and requested scopes | Add the exact user; grant read/send scopes; public distribution may need verification |
| Zoho refuses access | OAuth client region, plan and scopes | Register/connect in correct data center and check API access |
| Google works then expires | Testing app refresh-token lifetime or revoked consent | Reconnect; inspect provider configuration before broader deployment |
| Verification fails | Provider permissions/identity or refresh token | Reconnect OAuth or correct the existing app-password connection |
| Test won't start | Verified account, controlled recipient, confirmation, request nonce | Choose own inbox; campaign/suppressed addresses and reused requests remain blocked |
| Accepted test absent from inbox | Sent folder, spam, authentication headers | Acceptance is not delivery; inspect provider status without automatically repeating |
| Test/campaign send uncertain | Pending/test outcome, provider Sent receipt | Reconcile manually before any retry; HTTP send is never retried automatically |
| Zoho reply cannot find thread | Account-scoped mail_api_ids and original MIME | Sync source inbox; missing sent receipt requires reconciliation, not another send |
| All normal browser forms rejected | Referrer-Policy and Origin | Use same-origin for normal pages; no-referrer only on OAuth callback responses |
| Cloud legacy mail inaccessible | TCP network grants; configured IMAP | No grants here. Activate HTTPS OAuth on a hosted app or use an explicitly configured mail-capable host |

Encrypted tokens require the same backed-up key as mailbox passwords. Schema 8
preserves existing data; it does not turn password accounts into OAuth automatically.
Run one process. Provider consent and actual inbox delivery remain untested here.

## Hosted startup and recovery refinements

| Symptom | First check | Recovery |
| --- | --- | --- |
| Can't publish from Codex | Connected hosting account/API credentials | Connect Render/GitHub externally; a prepared blueprint does not create hosting access |
| Render opens only sample demo | Blueprint path | Use deployment/render.yaml for Python; root render.yaml is the sample demo |
| Hosted startup refuses configuration | Workspace password, HTTPS origin and absolute data paths | Follow HOSTED_APP.md; don't weaken the startup guard |
| Campaign text/key disappears after update | Persistent volume and working directory | Keep the disk and all three data types together; restore full backup |
| Provider button returns HTTPS setup error | Actual edge peer and trusted proxy configuration | Verify the host's proxy addresses; do not use wildcard trust |
| Account disconnected but campaign history still visible | Retained account/provider identity | Expected; reconnect the same confirmed email to reuse the account |
| Refreshed permissions refused | Account verification/last_error | Verify/reconnect; a green badge is removed on auth refusal |
| Test result lost from last URL | Saved Recent test requests | Inspect accepted/pending/uncertain history before another send |
| Inbox check opens another mailbox | Selected account_id and verified list | Targeted checks only open that account; filters are preserved |
| Sending page empty after restart | In-memory job vs persisted messages | Open campaign history/pending sends; never infer that delivery didn't happen |

Production dependency install and local startup passed; host proxy behavior, live
OAuth/mail and actual Safari access remain untested. Automatic approval review
rejected wildcard forwarded-header trust; the supplied defaults stay restricted.

## Guided laptop recovery

| Symptom | First check | Recovery |
| --- | --- | --- |
| Provider connection failed after entering a goal | Saved audience and request ledger | Goal is already saved; inspect retained reservation/provider usage, then use RESTART-OUTREACH.cmd; no automatic replay |
| Preview saves but cannot use live services | Settings restart notice | Owner launches RESTART-OUTREACH.cmd; restricted session blocks paid work before reserving |
| Restart refuses active work | Research, draft or sending job | Finish or pause the job first; files and history remain intact |
| Invalid field prevents saving | Named error and focused field | Correct that field; submitted entries are retained |
| Old browser values appear | Saved-version stamp | Stale cache is ignored; matching-version unsaved edits are restored, consent is never restored |
| Planning disabled after audience edits | Unsaved editor changes | Save edits first; planning uses saved preferences |
| Saved provider keys cannot be opened | provider-credentials.enc and original mail-credentials.key | Restore both together; startup refuses unreadable secrets and never rewrites .env |
| Reused account needs verification | Owner-run app and inbox/server settings | Verify sending/inbox login without an email; enable IMAP or MFA app-password access yourself if needed |
| Gmail App Password option absent | Organization or protection policy | Use administrator-approved access or HTTPS OAuth; do not weaken provider policy |

### Startup and provider diagnostics (2026-10-06)

If 127.0.0.1 refuses connection, keep the desktop app window open and run START-OUTREACH.cmd. The browser now opens after the listener starts. For backend updates, close the existing app window first; RESTART-OUTREACH.cmd hands off a restricted preview but does not reload a desktop process already running.

Settings & connections → Check OpenRouter key checks metadata only. Refused keys require a regular API key; exhausted limits require owner credit/limit review. Connection failures show no raw response or key. Key acceptance does not guarantee credits or selected-model availability. Confirm Parallel access in platform.parallel.ai. Restricted email verification preserves the account and explains restart without attempting access.

### Removal and feedback

If Delete / archive is absent, restart the desktop backend with START-OUTREACH.cmd after closing its existing app terminal. Opening the review link does not delete anything. If Delete is not offered, the item has saved work/history or is not an unused draft; archive preserves those records. Active work must finish or stop first. Restore archived audiences from /research?view=archived and campaigns from /campaigns?status=archived; restored campaigns are paused.

If progress says Updates interrupted, local status requests are failing, not proof that the provider operation stopped. The app retries status with backoff and never replays a paid or sending request. Keep the server window open. Open saved results/history before retrying operations after a server restart. Terminal work shows an explicit result-review link. Returning with Back clears stale Working feedback. Current selections remain intact while status polls.

Before this change, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261006-232849. No real user item was removed in validation.


### Completed requests but no contacts (2026-10-07)

The diagnosed audience had five finished requests and no pending calls. A website check rejected a homepage whose evidence was a cited article on the same company host. That check now accepts only an exact-host homepage with literal identity evidence; unrelated or unverified sites remain excluded. One company suggestion was recovered locally and the audience is paused. Its contact and fit checks have not run; no contact or deliverability claim is made.

Use What happened to distinguish saved companies, published emails, approvals, waiting requests and uncertain outcomes. Checks not finished means an unprocessed suggestion, not proof that no public email exists. Continue approved research (paid checks) is a separate owner action; no paid request was made during repair.

Edit audience changes an unused draft directly. A run with plans or requests saves revised inputs to a new free draft. Pause original work separately if it is still running. If new controls are missing, close the app terminal and double-click START-OUTREACH.cmd; RESTART-OUTREACH.cmd does not reload an already-running normal desktop server.

Before this increment, source/tests/docs and an online SQLite snapshot were preserved in data/recovery/ui-20261007-004359. The repair verified unchanged .env, research-call rows, approved inputs and spend; the earlier uncertain reservation remains intact.


### More contacts and missing buttons (2026-10-07)

Open the campaign's Find more contacts button or Research tab. Choose a saved audience when needed, edit batch size/spending cap and save the next batch free. Create and approve its paid plan separately. Open unfinished earlier batches to continue existing checks instead. Review discovered emails, approve the intended contacts, then add the selected results to the preselected campaign. Existing members are skipped; research may still return familiar companies unless the scope/exclusions change.

If Edit or Delete / archive seems absent, refresh the page: buttons now remain visible in older template contexts. On this laptop the actual backend still needs one close/reopen of START-OUTREACH.cmd. Until then unavailable audience edit/removal actions lead to a clear update notice; campaign edits and the ordinary new-audience workflow remain available. RESTART-OUTREACH.cmd opens an already-running normal app without reloading it.

A linked research batch prevents permanent deletion of an otherwise empty campaign; archive keeps the research association and ledger. Delete an eligible unused audience only after confirmation. Before this increment, source/tests/docs and SQLite were backed up under data/recovery/ui-20261007-010654.


### Final flow, deletion and research update (2026-10-07)

The top-left name is Complete Outreach Tool. Home separates audiences (goal, plan, company/contact research) from campaigns (reviewed recipients, message, drafts and sending). Each audience shows its own name/reference and a saved-state next step: finish details, approve a ready plan, watch progress, continue paused checks, review contacts or inspect an uncertain request. Paid continuation never automatically replays an uncertain outcome.

Delete audience now also supports researched work after explicit confirmation: it moves to Deleted audiences while costs, evidence, existing campaign contacts and research links remain intact. Restore starts no research. Eligible unused drafts remain permanently deletable; active jobs must stop first. No real audience was deleted during this update. Before changes, source/tests/docs and SQLite were privately backed up to data/recovery/ui-20261007-032006.

Flexible search is offered for new/revised audiences. It accepts explicitly published general business inbox fallbacks, inspects up to ten discovery sources and prioritizes official contact pages. Evidence from official-site search results is retained when extraction omits an address. Explicit [at]/(dot) spellings can be decoded with the original quote retained. Unknown company-fit facts stay available for human review. Addresses and website identities are never guessed, and suppression remains enforced. Earlier approved runs keep their original request inputs; choose Edit audience and save a revised flexible draft to change the approved scope.

The normal owner app remains running at http://127.0.0.1:8000. Close its terminal and reopen START-OUTREACH.cmd once to load the new backend; keep the new terminal open. The app shows this update requirement. Earlier loaded processes retain their continuation fallback. No paid research or mail operation was performed.

Final validation: 510 offline tests passed, one Windows symlink privilege test skipped; 86 Chrome assertions passed. Lint and formatting passed. The owner process closed during final verification. The updated app is now running as a restricted local preview; use RESTART-OUTREACH.cmd from the laptop to hand off to the normal desktop app for live providers. No paid research, email operation or deletion of real user data was performed.


### Completed research with zero companies despite available budget (2026-10-07)

Confirmed in two owner runs: all five requests complete, no uncertain calls, no saved companies. First-round model suggestions had placeholder website values; the second discovery round produced no candidates. No contact-search/extract stage ran. Both were already Flexible mode, so contact-role loosening is not the remedy for this case.

Look first at discovery-select results, checked_candidates rejection counts and research_flow's fixed two-round loop. Do not replay completed paid requests or conclude that no public emails exist. The proposed repair retains unresolved names, independently resolves official domains and schedules further bounded work with honest partial outcomes. Read [RESEARCH_EXECUTION_PLAN.md](RESEARCH_EXECUTION_PLAN.md). Implementation is pending; raising the cap alone does not alter the current loop.



### Implemented staged research — 2026-10-07

The user authorized implementation of the proposed Parallel-first flow. New web-created audiences and revised/copied batches use engine version 2; existing approved runs retain version 1 and their request fingerprints. Additive research_execution/research_suggestions tables preserve unresolved names and per-company work.

The new pipeline separately resolves official sites, reads up to four literal same-site contact links/pages, reuses completed requests, retains partial emails before fit checks, deduplicates aliases by official domain, and stops after at most eight discovery rounds or three rounds with no new names. Each request still reserves against run/daily caps before network I/O. Fast Search is explicitly limited to ten results with the documented source policy for official-domain contact searches. No extra provider account was introduced.

Target progress counts contacts compatible with the chosen mode. Focused HR does not count support as HR; founder/management roles remain unconfirmed until human review. Privacy/legal/DPO/no-reply/abuse/security administrative addresses are excluded from outreach contact results. Company facts can remain unknown and must be reviewed. Completion reports target reached, partial/no usable results or a budget stop, with visible website-check evidence and separate company/email counts.

Validation: 526 offline tests passed, one Windows symlink privilege test skipped; 89 real Chrome assertions passed against fake providers. Lint/format checks passed. Public-source benchmark seed documented in RESEARCH_BENCHMARK.md; actual Parallel/OpenRouter yield is still unmeasured for this engine.

No paid research, email send, mailbox operation, credential change or production-audience deletion was performed. Pre-change source/tests/docs/SQLite snapshot: data/recovery/ui-20261007-152905. The normal owner server remains running; its loaded Python needs one close/reopen through START-OUTREACH.cmd to activate the new backend. A visible research-page notice explains this.

Recovery: use Edit audience to save a new draft for the staged engine. Old approved/uncertain calls remain unchanged. A budget stop can retain emails with pending fit checks, so review/approval is blocked until checks finish. Unresolved sites remain visible and cannot become approved contacts. Provider/page errors are distinct from absence of emails.


## Audience handoff and attachments

| Symptom | Look first | Recovery |
| --- | --- | --- |
| Saved audience has no recipients available | Use this audience → ready count and Open audience | Criteria alone are not contacts. Continue research, finish checks and approve published contacts. Suppressed contacts remain blocked. |
| Contact is already in another campaign | Prior campaigns shown in selection | Inspect that campaign's history, then explicitly acknowledge reuse if appropriate. Existing members of the destination are skipped. |
| Attachment upload is refused | Campaign → Message → Add or manage attachments | Use supported formats, non-empty files, at most five and 10 MB total. Wait for sending/drafting to finish or reopen an archived/completed campaign. |
| Launch or test says review changed | Current draft and attachment list | Reopen review, inspect files and approve again. Old consent does not apply to changed files. |
| Zoho attachment upload fails | Email account verification and provider plan | No message is submitted when upload fails. Check account access/limits; inspect saved attempt before deciding on a fresh send. No automatic retry. |
| Provider submission is uncertain | Campaign → History and provider Sent folder | Original attachment names and bytes remain in history. Reconcile the attempt before any retry. |
| Removed file still appears in history | History attachment links | Expected: removal changes future sends and retains the historical file. |
| New links are unavailable after updating | Restart notice at top of app | Close the existing app terminal, reopen START-OUTREACH.cmd, keep it open and refresh. Saved work is kept. |


## Research has searches but zero page reads

Symptoms: budget stop, saved search calls, no completed /page/ or /pages call. This is not evidence that the Parallel key lacks fetch access. Inspect the displayed search/fetch counters and current stage: planning, company identification and website selection may consume the remaining reservation allowance before extraction.

For a saved approved paused run, adjust its TOTAL cap (including existing spend) and continue separately. For improved collection, edit the same audience, prepare the new version's free plan and approve it. Old runs retain immutable request bodies; do not rewrite fingerprints or automatically replay an uncertain call. A cap increase alone cannot fix exhausted coverage or websites with no published email.

Named role without ownership evidence remains unconfirmed. An info/sales/support inbox cannot be labelled Founder merely because founder text appears elsewhere. Extraction errors keep source evidence and partial emails; they do not prove that the site contains no address.

Audience delete now applies to all explicitly linked versions. Any active older version blocks removal. Restore brings all versions back without starting work; campaign origins and paid ledgers survive soft deletion.


## Founder address exists on a different public page
Current contact collection discards non-official-domain sources and attribution requires name, role and email in one quote. An official role page plus a separate corroborated professional address page may therefore be missed. Proposed fix: bounded cross-web expansion and separate relation-level evidence with ambiguity checks; do not weaken identity checks to name equality alone. See EMAIL_RESEARCH_IMPLEMENTATION.md.

## Strategy 4 contact yield
Search snippets alone can omit addresses: fetch official pages and useful wider-web results. Separate role and address evidence prevents same-page-only false negatives. Namesakes and Mastodon handles must not become inferred email matches. Budget exhaustion preserves partial contacts; frozen assessment contexts prevent replay fingerprint drift. Live yield is still unverified.

## Direct handoff and low email yield
If adding fails, check finished contact status, publication, suppression, destination campaign and prior campaign acknowledgment. No separate review note is needed. If research pauses after two rounds with no new email, narrow the audience or supply known websites before choosing whether to continue spending. Existing runs keep their old strategy; edit into a new version to use the new controls. Attachments are in the campaign navigation; failed uploads do not send mail.

If the inline campaign picker is missing, restart the desktop server to load campaign_contacts_enabled and the new rendering context. Empty audience groups link to research; existing campaign members and unusable contacts are omitted. Legacy saved-list tools remain in Other ways to add contacts.

## Prompt-first creation — 2026-10-09

If a prompt does not establish company type, location or roles, it stays a free draft
and asks for those details. Reword it (for example: Find textile manufacturers in
India. Contact founders.) or use optional detailed inputs. Inspect core/prompt_intake.py
and tests/test_prompt_creation.py. Do not treat missing roles as permission for general
inboxes. Overall audience prompts longer than 2,000 characters are rejected rather
than truncated.

Current campaigns use one message editor. A supplied message prompt takes precedence
over legacy API fields. KEEP blocks can appear before, between or after generated sections;
the primary editor no longer requires separate message/closing fields. Legacy external
closings stay compatible until saved as KEEP in the editor.

Browser textarea submissions use CRLF. campaigns.save_texts normalizes copy and
closing before platform newline translation; regression tests protect exact lines
from extra blank lines on Windows.

If a contact says Choose contact, its saved selected address is no longer in current
published evidence. Open its source/review page and choose a supported address; do not
substitute another address silently. Audience fit mismatch and unconfirmed criteria
are separate warnings; either requires an explicit selection in the handoff.

Strategy6 is target-or-budget: low-yield rounds no longer pause automatically. A budget
stop can occur before the next reservation fits, leaving money unspent; do not shrink
reservations or replay uncertain calls to spend the remainder. A fixed known-company
list may finish below target because expanding it would change the approved scope.
Older strategy5 runs retain their low-yield pause; revise into a new audience version
to use strategy6. Custom roles need manual review and are not automatic role matches.

After app restart, /sending may have no live job object while durable messages still
exist. Inspect campaign history before retrying; acceptance does not establish inbox
delivery. Sent drafts link their saved history rather than current message settings.

## Campaign drafting diagnostics — 2026-10-10

If an unrelated sales offer appears in an older draft, do not assume another campaign
record was fetched. Earlier shared prompts hard-coded Star Threads/thread outreach.
Restart the app to load neutral templates, verify the selected campaign source in Message,
and explicitly regenerate; existing drafts/history are preserved. New drafts display
the campaign/contact and instruction fingerprint in review.

Changed instructions or recipient context during generation discard the stale result.
Changed instructions after generation require regeneration before approval/launch.
Missing/changed/reordered KEEP blocks prevent approval and even test-to-self delivery.
Unknown/malformed variables are rejected; missing name/title/company values fail clearly
before a provider call. Use only available reviewed details or remove that placeholder.
Browser recovery cannot replace saved campaign instructions. See
[CAMPAIGN_COMPOSER_REPORT.md](CAMPAIGN_COMPOSER_REPORT.md) for evidence and limits.
