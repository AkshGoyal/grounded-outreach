"""Command line entry point.

Right now it does one thing: read a spreadsheet and show you what it found.

Importing is deliberately two steps. Running it without `--commit` changes
nothing — it reads the file, tells you which column it thinks is the email
address, and lists what it would accept and reject. You look, and only then
run it again with `--commit`.

The same code produces both, so what you previewed is what you get.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from outreach.adapters.backup import BackupError, backup_database, default_destination
from outreach.adapters.db import connect
from outreach.adapters.spreadsheet import SpreadsheetError, read_rows
from outreach.adapters.store_sqlite import SqliteStore
from outreach.campaigns import closing_path, copy_path, load_closing, load_copy
from outreach.config import ConfigError, load_settings
from outreach.core.dispatch import dispatch, email_tail, plan
from outreach.core.drafting import draft_email
from outreach.core.flow import repeated_lines
from outreach.core.grounding import Verdict
from outreach.core.importing import (
    DEFAULT_SKIP,
    RowStatus,
    build_report,
    grouped_problems,
    plan_columns,
)
from outreach.core.models import Campaign, Contact, DraftStatus
from outreach.core.review import checks_for_display, storable_body
from outreach.generation import generation_snapshot, recipient_generation
from outreach.ports.llm import LLMError
from outreach.ports.mail import MailError
from outreach.wiring import build_llm, campaign_settings


def _print_report(report, *, committed: bool) -> None:
    plan = report.plan
    print("\nColumns")
    print(f"  email       {plan.email_column or '— none found —'}")
    print(f"  company     {plan.company_column or '— none found —'}")
    print(f"  evidence    {', '.join(plan.evidence_columns) or '— none —'}")

    counts = report.counts
    print("\nRows")
    print(f"  accepted    {counts['accepted']}")
    print(f"  rejected    {counts['rejected']}")
    print(f"  duplicates  {counts['duplicate']}")

    noted = [o for o in report.outcomes if o.status is RowStatus.ACCEPTED and o.note]
    if noted:
        print("\nAccepted, but worth a look")
        for outcome in noted:
            print(f"  row {outcome.row_number:>4}  {outcome.note}")

    groups = grouped_problems(report)
    if groups:
        print("\nRows not imported")
        for status, reason, count, rows in groups:
            where = f"row {rows}" if count == 1 else f"{count} rows ({rows})"
            print(f"  {status:<10} {reason}\n             {where}")

    print(
        "\nNothing was written. Re-run with --commit to import."
        if not committed
        else f"\nImported {counts['accepted']} contacts."
    )


def cmd_import(args: argparse.Namespace) -> int:
    settings = load_settings()
    # Importing touches no mailbox and no model, so it asks for neither.
    settings.require("db_path")
    rows = read_rows(args.file, sheet=args.sheet)
    if not rows:
        print(f"{args.file} has no rows.")
        return 1

    store = SqliteStore(connect(settings.db_path))
    skip = list(DEFAULT_SKIP) + (args.skip_column or [])
    plan = plan_columns(rows, skip=skip)
    if args.email_column:
        plan.email_column = args.email_column
        plan.evidence_columns = [c for c in plan.evidence_columns if c != args.email_column]

    known = store.emails_in_campaign(args.campaign)
    report = build_report(rows, plan=plan, already_known=known)

    if args.commit:
        if store.get_campaign(args.campaign) is None:
            store.add_campaign(
                Campaign(id=args.campaign, name=args.campaign, created_at=datetime.now(UTC))
            )
        for email, company, evidence in report.accepted:
            store.add_contact(
                Contact(
                    campaign_id=args.campaign,
                    email=email,
                    company=company,
                    evidence=evidence,
                )
            )

    _print_report(report, committed=args.commit)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    settings = load_settings()
    settings.require("db_path")

    if not Path(settings.db_path).exists():
        print(f"There is no database at {settings.db_path} yet — nothing to back up.")
        return 1

    destination = Path(args.to) if args.to else default_destination(settings.db_path)
    conn = connect(settings.db_path)
    counts = backup_database(conn, destination)
    conn.close()

    print(f"\nSaved to {destination}")
    for table, count in counts.items():
        marker = "   <- the one you cannot rebuild" if table == "suppressions" else ""
        print(f"  {table:<14} {count:>5}{marker}")
    print("\nTo restore, copy this file back over your database.\n")
    return 0


_MARK = {
    Verdict.NEUTRAL: "    ",
    Verdict.GROUNDED: " ok ",
    Verdict.UNVERIFIABLE: " ?  ",
    Verdict.UNSUPPORTED: " XX ",
    Verdict.REPEATS: " -- ",
}


def cmd_check(args: argparse.Namespace) -> int:
    """Confirm the setup works, before you spend time on anything else.

    Reports what is configured, what is missing, and — unless you say
    --no-live — makes one tiny real call to prove the key and the model
    actually work. That call costs a fraction of a paisa.
    """
    settings = load_settings()
    ok = True

    print("\nSettings")
    print(f"  provider       {settings.llm_provider}")
    print(f"  model          {settings.llm_model}")
    print(f"  database       {settings.db_path}")
    print(
        f"  sends as       {settings.sender_name or '(not set)'} "
        f"<{settings.sender_email or 'not set'}>"
    )

    needed = (*settings.llm_credentials(), *settings.SEND)
    missing = [name for name in needed if getattr(settings, name, None) in (None, "")]
    print("\nSettings for drafting and sending")
    for name in needed:
        mark = "missing" if name in missing else "set"
        print(f"  {'OUTREACH_' + name.upper():<32} {mark}")

    if Path(settings.db_path).exists():
        store = SqliteStore(connect(settings.db_path))
        campaigns = store._conn.execute(
            "SELECT id, (SELECT COUNT(*) FROM contacts c WHERE c.campaign_id = campaigns.id) AS n "
            "FROM campaigns ORDER BY created_at"
        ).fetchall()
        print("\nCampaigns")
        for row in campaigns:
            note = "" if load_copy(row["id"]) else f"  (no {copy_path(row['id'])} yet)"
            note += "  + fixed closing" if load_closing(row["id"]) else ""
            print(f"  {row['id']:<24} {row['n']:>4} contacts{note}")
        if not campaigns:
            print("  none yet — run: outreach import <file> --campaign <name> --commit")
    else:
        print(f"\nNo database at {settings.db_path} yet. Import a list to create it.")

    if missing:
        print("\nSet the missing values in .env, then run this again.\n")
        return 1

    if args.no_live:
        print("\nSettings look complete. Skipping the live call.\n")
        return 0

    print(f"\nAsking {settings.llm_model} to reply, to prove the key works...")
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool

    try:
        answer = build_llm(settings).generate(
            prompt="Reply with ok set to true. Nothing else.", schema=Ping, max_tokens=64
        )
    except LLMError as exc:
        print(f"\n  FAILED: {exc}\n")
        return 1

    print(f"  worked — the model replied and it matched the expected shape ({answer.ok}).")

    host, user = settings.mail_smtp_host, settings.mail_username
    print(f"\nLogging in to {host} as {user} (nothing is sent)...")
    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox

    try:
        SmtpImapMailbox(settings).verify_login()
    except MailError as exc:
        print(f"\n  FAILED: {exc}\n")
        return 1
    print("  worked — the mailbox accepted the login.\n")
    return 0 if ok else 1


def cmd_draft(args: argparse.Namespace) -> int:
    """Write drafts and show what the grounding checker made of them.

    Writes nothing. This is for reading, and for comparing one model against
    another on your own contacts rather than on someone else's benchmark.
    """
    settings = campaign_settings(load_settings(), args.campaign)
    settings.require("db_path", *settings.llm_credentials())

    campaign_copy = load_copy(args.campaign)
    if campaign_copy is None:
        print(
            f"\nNo campaign copy at {copy_path(args.campaign)}.\n"
            f"Copy campaigns/example.md to {copy_path(args.campaign)} and describe what you "
            "are offering — a draft may not claim anything that is not in that file.\n",
            file=sys.stderr,
        )
        return 1

    generation = generation_snapshot(args.campaign)
    campaign_copy, closing = generation["campaign_copy"], generation["closing"]
    if closing:
        print(
            f"\nUsing the fixed closing in {closing_path(args.campaign)} — "
            "the model writes the opening only."
        )
    models = args.model or [settings.llm_model]
    if args.save and len(models) > 1:
        print("--save keeps one model's drafts. Pass a single --model.", file=sys.stderr)
        return 1

    store = SqliteStore(connect(settings.db_path))
    # Saving drafts only the contacts that have none yet, so running it again
    # after importing more contacts picks up exactly the new ones. A preview
    # without --save looks at the first few, whatever their state.
    if args.redraft and not args.save:
        print("--redraft replaces saved drafts, so it needs --save as well.", file=sys.stderr)
        return 1
    # --redraft: everyone not yet emailed gets a fresh draft, and their older
    # unsent drafts are set aside — so a draft written before the closing
    # existed can never be sent with the closing added under it.
    if args.redraft:
        only_new = (
            "AND id NOT IN (SELECT contact_id FROM messages WHERE status IN ('sent','pending'))"
        )
    else:
        only_new = "AND id NOT IN (SELECT contact_id FROM drafts)" if args.save else ""
    limit = args.limit if args.limit is not None else (-1 if args.save else 3)
    contacts = [
        store.get_contact(row["id"])
        for row in store._conn.execute(
            f"SELECT id FROM contacts WHERE campaign_id = ? {only_new} ORDER BY id LIMIT ?",
            (args.campaign, limit),
        )
    ]
    if not contacts:
        if args.save:
            print(f"Every contact in '{args.campaign}' already has a draft.")
            print("Review them in the web page: uv run outreach serve")
            return 0
        print(f"No contacts in campaign '{args.campaign}'. Import a list first.")
        return 1

    saved = 0
    shown_whole = False
    for model in models:
        print(f"\n{'=' * 72}\n  {model}\n{'=' * 72}")
        llm = build_llm(settings, model)
        tally = {v: 0 for v in Verdict}

        for contact in contacts:
            if store.is_suppressed(contact.email):
                print(f"\n-- {contact.company} -- skipped, on the do-not-contact list")
                continue
            try:
                result = draft_email(
                    llm,
                    company=contact.company,
                    evidence=contact.evidence,
                    campaign_copy=campaign_copy,
                    sender=settings.sender_name or "",
                    closing=closing,
                )
            except (LLMError, ValueError) as exc:
                # One bad contact or one refusal must not end the whole run.
                print(f"\n-- {contact.company} -- could not draft: {exc}")
                if "not a valid model ID" in str(exc):
                    break
                continue
            print(f"\n-- {contact.company} -- {result.verdict.value.upper()}")
            print(f"{_MARK[result.subject_check.verdict]} SUBJECT: {result.draft.subject}")
            if result.subject_check.reason:
                print(f"      -> {result.subject_check.reason}")
            for check in result.all_checks:
                tally[check.verdict] += 1
            for check in result.checks:
                print(f"{_MARK[check.verdict]} {check.text}")
                if check.reason:
                    print(f"      -> {check.reason}")
            if not args.save and not shown_whole:
                # One email in full, as it would arrive — the reference to judge
                # the flow by, before drafting everyone.
                tail = email_tail(
                    closing=closing,
                    name=settings.sender_name or "(your name)",
                    company=settings.sender_company or "(your company)",
                    address=settings.sender_address or "(your address)",
                )
                print(f"\n   The whole email, as {contact.company} would get it:\n   {'-' * 60}")
                print(f"   Subject: {result.draft.subject}\n")
                whole = f"{storable_body(result)}\n\n{tail}"
                print("\n".join(f"   {line}" if line else "" for line in whole.splitlines()))
                print(f"   {'-' * 60}")
                shown_whole = True
            if args.save:
                try:
                    new_id = store.save_draft(
                        contact_id=contact.id,
                        model=model,
                        subject=result.draft.subject,
                        body=storable_body(result),
                        verdict=result.verdict.value,
                        checks=checks_for_display(result),
                        generation=recipient_generation(generation, contact),
                    )
                except ValueError:
                    print(
                        "Campaign instructions changed; "
                        "generation stopped without saving stale text.",
                        file=sys.stderr,
                    )
                    return 1
                if args.redraft:
                    for old in store.drafts_in_campaign(args.campaign):
                        if (
                            old.id != new_id
                            and old.contact_id == contact.id
                            and old.status
                            in (
                                DraftStatus.REVIEW,
                                DraftStatus.APPROVED,
                            )
                        ):
                            store.set_draft_status(old.id, DraftStatus.REJECTED)
                saved += 1

        total = sum(tally.values())
        print(f"\n  {model}: ", end="")
        print("  ".join(f"{v.value} {tally[v]}" for v in Verdict), f"  (of {total} lines)")

    if args.save:
        print(f"\nSaved {saved} draft(s) for review. Open them with: uv run outreach serve\n")
    else:
        print("\nNothing was written. Add --save to keep these for review.\n")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    """Send approved drafts. A dry run unless --really is given."""
    settings = campaign_settings(load_settings(), args.campaign, require_verified=True)
    settings.require("db_path", *settings.SEND)
    store = SqliteStore(connect(settings.db_path))

    planned = plan(
        store,
        args.campaign,
        daily_cap=settings.daily_send_cap,
        closing=load_closing(args.campaign),
        campaign_copy=load_copy(args.campaign) or "",
    )
    if not planned:
        print(f"\nNo approved drafts in '{args.campaign}'. Approve some in the web pages first.\n")
        return 1

    foot = email_tail(
        closing=load_closing(args.campaign),
        name=settings.sender_name,
        company=settings.sender_company,
        address=settings.sender_address,
    )
    going = [p for p in planned if p.will_send]

    print(f"\n{len(going)} to send, {len(planned) - len(going)} held back.\n")
    for item in planned:
        status = "SEND" if item.will_send else f"hold — {item.skip}"
        print(f"  {status:<40} {item.draft.company}  <{item.draft.email}>")

    if going:
        first = going[0].draft
        print(f"\nThe first one, exactly as it will go out:\n{'-' * 72}")
        print(f"From:    {settings.sender_name} <{settings.sender_email}>")
        print(f"To:      {first.email}")
        print(f"Subject: {first.subject}\n")
        print(f"{first.body}\n\n{foot}")
        print("-" * 72)

    if not args.really:
        print("\nThis was a dry run. Nothing was sent. Add --really to send.\n")
        return 0
    if not going:
        return 0

    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox

    gap = settings.send_gap_seconds
    print(f"\nSending {len(going)}, {gap} seconds apart. Ctrl-C stops safely between emails.\n")
    outcomes = dispatch(
        store,
        SmtpImapMailbox(settings),
        planned,
        sender_email=settings.sender_email,
        daily_cap=settings.daily_send_cap,
        tail=foot,
        pause=lambda: time.sleep(gap),
    )
    for outcome in outcomes:
        mark = "sent  " if outcome.sent else "FAILED"
        print(f"  {mark}  {outcome.draft.company}  — {outcome.detail}")
    sent = sum(o.sent for o in outcomes)
    print(f"\n{sent} sent. Replies will arrive in the Zoho inbox.\n")
    return 0 if sent == len(going) else 1


_TEST_BODY = """Hello,

This is a test from the outreach tool, sent through your Zoho mailbox to check
that sending works and that it lands in the inbox rather than spam.

Nothing about it is real — no prospect received it.

Aksh"""


def _explain_missing_draft(store: SqliteStore, wanted: int) -> None:
    """Say which draft numbers do exist, rather than just that one does not."""
    rows = store._conn.execute(
        "SELECT d.id, d.status, c.company, c.campaign_id FROM drafts d "
        "JOIN contacts c ON c.id = d.contact_id ORDER BY d.id DESC LIMIT 25"
    ).fetchall()
    if not rows:
        print(
            f"\nThere is no draft {wanted} — there are no saved drafts at all yet.\n\n"
            "Write some first, then run this again:\n"
            "  uv run outreach draft --campaign <your-campaign> --save\n"
            "  (or the Write drafts button in the web page)\n\n"
            "To test the connection without a draft, leave --draft off:\n"
            "  uv run outreach send-test --to you@example.com\n",
            file=sys.stderr,
        )
        return
    print(f"\nThere is no draft {wanted}. These exist:\n", file=sys.stderr)
    for r in rows:
        print(
            f"  {r['id']:>4}  {r['status']:<9} {r['company'] or '—'}  ({r['campaign_id']})",
            file=sys.stderr,
        )
    print("", file=sys.stderr)


def cmd_send_test(args: argparse.Namespace) -> int:
    """Send one test email to yourself, through the real Zoho connection."""
    settings = load_settings()
    settings.require("db_path")
    store = SqliteStore(connect(settings.db_path))

    campaign = args.campaign
    if args.draft is not None:
        draft = store.get_draft(args.draft)
        if draft is None:
            _explain_missing_draft(store, args.draft)
            return 1
        subject, body = draft.subject, draft.body
        campaign = store.get_contact(draft.contact_id).campaign_id
        what = f"draft {args.draft} ({draft.company}) — exactly what they would receive"
    else:
        subject, body = "Checking the outreach tool can send", _TEST_BODY
        what = "a short test message"

    if campaign:
        settings = campaign_settings(settings, campaign, require_verified=True)
    settings.require(*settings.SEND)
    closing = load_closing(campaign) if campaign else None
    if args.draft is not None:
        repeats = repeated_lines(
            body, closing=closing, campaign_copy=(load_copy(campaign) or "") if campaign else ""
        )
        if repeats:
            print(
                f"\nNot sent: draft {args.draft} repeats itself or your closing.", file=sys.stderr
            )
            for line, reason in repeats:
                print(f"  -- {line}\n      -> {reason}", file=sys.stderr)
            print(
                "Delete those lines on the review page, or write it again with\n"
                f"  uv run outreach draft --campaign {campaign} --save --redraft\n",
                file=sys.stderr,
            )
            return 1

    foot = email_tail(
        closing=closing,
        name=settings.sender_name,
        company=settings.sender_company,
        address=settings.sender_address,
    )
    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox
    from outreach.core.dispatch import new_message_id
    from outreach.core.sending import NotATestAddressError, SuppressedRecipientError, send_test

    print(f"\nSending {what}")
    print(f"  from {settings.sender_name} <{settings.sender_email}>  to {args.to}")
    try:
        send_test(
            store=store,
            mailbox=SmtpImapMailbox(settings),
            to=args.to,
            subject=subject,
            body_text=f"{body}\n\n{foot}",
            message_id=new_message_id(settings.sender_email),
        )
    except (NotATestAddressError, SuppressedRecipientError) as exc:
        print(f"\n  Not sent: {exc}\n", file=sys.stderr)
        return 1

    print("  sent.\n")
    print("Now check, in this order:")
    print("  1. Did it arrive in the inbox, not spam or promotions?")
    print("  2. Open it. In Gmail: ⋮ menu → Show original. You want to see")
    print("     SPF: PASS   DKIM: PASS   DMARC: PASS")
    print("  3. Does the footer read correctly — your name, company, address?")
    print("  4. Promotions tab instead of Primary? See docs/FAILURE_MAP.md, 2.7 #9.\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Where every campaign stands. Useful when sending runs over several days."""
    settings = load_settings()
    settings.require("db_path")
    if not Path(settings.db_path).exists():
        print(f"\nNo database at {settings.db_path} yet. Import a list first.\n")
        return 1
    store = SqliteStore(connect(settings.db_path))
    q = store._conn.execute

    sent_today = store.sent_today()
    cap = settings.daily_send_cap
    print(
        f"\nSent today: {sent_today} of {cap}.   Do-not-contact list: "
        f"{q('SELECT COUNT(*) FROM suppressions').fetchone()[0]}."
    )

    campaigns = [r["id"] for r in q("SELECT id FROM campaigns ORDER BY created_at")]
    if not campaigns:
        print("No campaigns yet.\n")
        return 0

    print(
        f"\n  {'campaign':<22}{'contacts':>9}{'no draft':>10}{'review':>8}"
        f"{'approved':>10}{'sent':>6}"
    )
    for cid in campaigns:
        contacts = q("SELECT COUNT(*) FROM contacts WHERE campaign_id = ?", (cid,)).fetchone()[0]
        undrafted = q(
            "SELECT COUNT(*) FROM contacts WHERE campaign_id = ? "
            "AND id NOT IN (SELECT contact_id FROM drafts)",
            (cid,),
        ).fetchone()[0]
        latest = {}
        for d in store.drafts_in_campaign(cid):  # newest first
            latest.setdefault(d.contact_id, d.status.value)
        counts = {s: sum(1 for v in latest.values() if v == s) for s in ("review", "approved")}
        sent = q(
            "SELECT COUNT(*) FROM messages m JOIN contacts c ON c.id = m.contact_id "
            "WHERE c.campaign_id = ? AND m.status = 'sent'",
            (cid,),
        ).fetchone()[0]
        print(
            f"  {cid:<22}{contacts:>9}{undrafted:>10}{counts['review']:>8}"
            f"{counts['approved']:>10}{sent:>6}"
        )

    waiting = sum(
        1
        for cid in campaigns
        for p in plan(
            store,
            cid,
            daily_cap=10**6,
            closing=load_closing(cid),
            campaign_copy=load_copy(cid) or "",
        )
        if p.will_send
    )
    if waiting:
        days = -(-waiting // cap)
        print(
            f"\n{waiting} approved and waiting to send. At {cap} a day that is "
            f"{days} day{'s' if days != 1 else ''} of sending."
        )
    print()
    return 0


def cmd_replies(args: argparse.Namespace) -> int:
    """Check the inbox for replies, read them, and list what needs handling."""
    from outreach.adapters.mail_smtp_imap import SmtpImapMailbox
    from outreach.core.models import ReplyStatus
    from outreach.core.replies import LABELS, ReplyCategory, check_replies

    settings = load_settings()
    settings.require("db_path", *settings.SEND, "mail_imap_host")
    store = SqliteStore(connect(settings.db_path))
    credentials = settings.llm_credentials()
    llm = build_llm(settings) if all(getattr(settings, n, None) for n in credentials) else None
    try:
        result = check_replies(
            store,
            SmtpImapMailbox(settings),
            llm,
            own_address=settings.sender_email,
            offer_for=lambda cid: load_copy(cid) or "",
            sender=settings.sender_name,
            sender_company=settings.sender_company or "",
        )
    except MailError as exc:
        print(f"\nCould not read the inbox: {exc}\n", file=sys.stderr)
        return 1
    print(f"\n{result.new} new repl{'y' if result.new == 1 else 'ies'}.")
    for address in result.suppressed:
        print(f"  added to the do-not-contact list: {address}")
    waiting = [r for r in store.list_replies() if r.status is ReplyStatus.NEW]
    print(f"\n{len(waiting)} to handle:")
    for r in waiting:
        label = LABELS[ReplyCategory(r.category)] if r.category else "Not read yet"
        print(f"  #{r.id:<4} {label:<15} {r.company or r.from_address}  — {r.summary}")
    print("\nOpen them in the web page: uv run outreach serve → Inbox\n")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the local web interface."""
    import uvicorn

    from outreach.web.app import create_app

    if args.host not in ("127.0.0.1", "localhost", "::1") and not load_settings().app_password:
        raise ConfigError("Set OUTREACH_APP_PASSWORD before exposing the workspace to a network.")
    url = f"http://{args.host}:{args.port}"
    print(f"\n  {url}" + ("" if args.no_browser else "  — opening it in your browser."))
    print("  Ctrl-C to stop. Cloud access requires a workspace password and allowed host.\n")
    if not args.no_browser:
        import threading
        import webbrowser

        # A second after starting, so the page is there when the tab opens.
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(
        create_app(poll_minutes=10),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="outreach")
    sub = parser.add_subparsers(dest="command", required=True)

    importer = sub.add_parser("import", help="read a spreadsheet of contacts")
    importer.add_argument("file", help="path to a .csv or .xlsx")
    importer.add_argument("--campaign", required=True, help="campaign id, e.g. rfd-buyers-q4")
    importer.add_argument("--sheet", help="which sheet to read, for a workbook with several")
    importer.add_argument("--email-column", help="override which column holds the email address")
    importer.add_argument(
        "--skip-column",
        action="append",
        help="a column to leave out of evidence. Repeat for several.",
    )
    importer.add_argument(
        "--commit", action="store_true", help="actually write. Without this, nothing changes."
    )
    importer.set_defaults(func=cmd_import)

    backup = sub.add_parser("backup", help="make a verified copy of the database")
    backup.add_argument("--to", help="where to write it (default: backups/ beside the database)")
    backup.set_defaults(func=cmd_backup)

    checker = sub.add_parser("check", help="confirm your setup works")
    checker.add_argument("--no-live", action="store_true", help="skip the test call to the model")
    checker.set_defaults(func=cmd_check)

    drafter = sub.add_parser("draft", help="write drafts and check them (writes nothing)")
    drafter.add_argument("--campaign", required=True)
    drafter.add_argument(
        "--limit",
        type=int,
        default=None,
        help="how many contacts (default: 3 for a preview, all of them with --save)",
    )
    drafter.add_argument(
        "--model",
        action="append",
        help="override the configured model. Repeat to compare several.",
    )
    drafter.add_argument(
        "--save", action="store_true", help="keep the drafts for review in the web pages"
    )
    drafter.add_argument(
        "--redraft",
        action="store_true",
        help="draft everyone not yet emailed again, setting their older drafts aside",
    )
    drafter.set_defaults(func=cmd_draft)

    sender = sub.add_parser("send", help="send approved drafts (a dry run unless --really)")
    sender.add_argument("--campaign", required=True)
    sender.add_argument("--really", action="store_true", help="actually send")
    sender.set_defaults(func=cmd_send)

    tester = sub.add_parser("send-test", help="send one test email to yourself through Zoho")
    tester.add_argument("--to", required=True, help="your own address — never a prospect's")
    tester.add_argument(
        "--draft", type=int, help="send yourself this draft exactly as a prospect would get it"
    )
    tester.add_argument(
        "--campaign", help="include this campaign's closing, to see how it looks in an inbox"
    )
    tester.set_defaults(func=cmd_send_test)

    status = sub.add_parser("status", help="where every campaign stands")
    status.set_defaults(func=cmd_status)

    replies = sub.add_parser("replies", help="check the inbox for replies and sort them")
    replies.set_defaults(func=cmd_replies)

    serve = sub.add_parser("serve", help="open the web interface in your browser")
    serve.add_argument("--host", default="127.0.0.1", help="default: this machine only")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--no-browser", action="store_true", help="just print the address, don't open a tab"
    )
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, SpreadsheetError, BackupError, LLMError, MailError) as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
