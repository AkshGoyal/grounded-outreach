"""Storage, in SQLite. Explicit SQL: what you read here is what runs.

Implements `outreach.ports.store.StorePort`. Every address is normalised on the
way in and on the way out, through the one function in `core.normalize`, so the
two suppression guards can never disagree about what an address looks like.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from outreach.core.models import (
    Campaign,
    Contact,
    DraftRecord,
    DraftStatus,
    InboundMessage,
    MessageStatus,
    ReplyRecord,
    ReplyStatus,
    SentRecord,
    SuppressionReason,
)
from outreach.core.normalize import normalize_email


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteStore:
    """Implements `StorePort` against an open SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- the do-not-contact list -------------------------------------------

    def is_suppressed(self, email: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM suppressions WHERE email = ?", (normalize_email(email),)
        ).fetchone()
        return row is not None

    def add_suppression(
        self, email: str, reason: SuppressionReason, note: str | None = None
    ) -> None:
        """Add an address, or leave the original entry alone if already present.

        The first reason is kept: how someone *first* opted out is the useful
        fact, and a later bounce should not overwrite an explicit unsubscribe.
        """
        self._conn.execute(
            "INSERT INTO suppressions (email, reason, created_at, note) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(email) DO NOTHING",
            (normalize_email(email), str(reason), _now(), note),
        )

    # --- campaigns and contacts --------------------------------------------

    def add_campaign(self, campaign: Campaign) -> None:
        self._conn.execute(
            "INSERT INTO campaigns (id, name, created_at) VALUES (?, ?, ?)",
            (campaign.id, campaign.name, campaign.created_at.isoformat()),
        )

    def get_campaign(self, campaign_id: str) -> Campaign | None:
        row = self._conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            return None
        return Campaign(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def emails_in_campaign(self, campaign_id: str) -> set[str]:
        """Addresses already stored for this campaign, so a re-import of an
        updated file does not create duplicates."""
        return {
            row["email"]
            for row in self._conn.execute(
                "SELECT email FROM contacts WHERE campaign_id = ?", (campaign_id,)
            )
        }

    def is_contact(self, email: str) -> bool:
        """True if this address belongs to a contact in any campaign."""
        row = self._conn.execute(
            "SELECT 1 FROM contacts WHERE email = ?", (normalize_email(email),)
        ).fetchone()
        return row is not None

    def add_contact(self, contact: Contact) -> int:
        cursor = self._conn.execute(
            "INSERT INTO contacts (campaign_id, email, company, evidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                contact.campaign_id,
                normalize_email(contact.email),
                contact.company,
                json.dumps(contact.evidence),
                (contact.created_at or datetime.now(UTC)).isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def get_contact(self, contact_id: int) -> Contact | None:
        row = self._conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        if row is None:
            return None
        return Contact(
            id=row["id"],
            campaign_id=row["campaign_id"],
            email=row["email"],
            company=row["company"],
            evidence=json.loads(row["evidence"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def campaign_attachments(self, campaign_id):
        from outreach.adapters.attachments import campaign_files

        return campaign_files(self._conn, campaign_id)

    # --- sends --------------------------------------------------------------

    def record_pending_send(
        self,
        *,
        contact_id: int,
        message_id: str,
        recipient_email: str,
        subject: str,
        body_text: str,
        attachments: tuple = (),
    ) -> int:
        """Write the row that the database's own suppression guard inspects.

        Raises `sqlite3.IntegrityError` if the address is suppressed — that is
        the trigger firing, and it is the intended behaviour.
        """
        self._conn.execute("SAVEPOINT pending_with_files")
        try:
            cursor = self._conn.execute(
                "INSERT INTO messages "
                "(contact_id, message_id, recipient_email, subject, body_text, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    contact_id,
                    message_id,
                    normalize_email(recipient_email),
                    subject,
                    body_text,
                    str(MessageStatus.PENDING),
                    _now(),
                ),
            )
            from outreach.adapters.attachments import record_files

            record_files(self._conn, message_id, attachments, contact_id)
            self._conn.execute("RELEASE pending_with_files")
            return int(cursor.lastrowid)
        except Exception:
            self._conn.execute("ROLLBACK TO pending_with_files")
            self._conn.execute("RELEASE pending_with_files")
            raise

    def mark_send_outcome(
        self, message_id: str, status: MessageStatus, sent_at: datetime | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE messages SET status = ?, sent_at = ? WHERE message_id = ?",
            (str(status), sent_at.isoformat() if sent_at else None, message_id),
        )

    # --- drafts and review --------------------------------------------------

    def save_draft(
        self,
        *,
        contact_id: int,
        model: str,
        subject: str,
        body: str,
        verdict: str,
        checks: list[dict],
        generation: dict | None = None,
    ) -> int:
        """Save atomically with provenance; legacy callers retain their existing API."""
        self._conn.execute("SAVEPOINT save_generated_draft")
        try:
            if generation is not None:
                from outreach.generation import current_generation_matches

                contact = self.get_contact(contact_id)
                if (
                    not contact
                    or contact.campaign_id != generation.get("campaign_id")
                    or generation.get("contact_id", contact_id) != contact_id
                ):
                    raise ValueError("Draft generation does not belong to this campaign contact.")
                if "recipient_evidence" in generation and (
                    generation["recipient_evidence"] != contact.evidence
                    or generation.get("recipient_company") != contact.company
                ):
                    raise ValueError("Recipient research changed. Generate a new draft.")
                if not current_generation_matches(generation):
                    raise ValueError("Campaign instructions changed. Generate a new draft.")
            cursor = self._conn.execute(
                "INSERT INTO drafts "
                "(contact_id, model, subject, body, verdict, checks, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    contact_id,
                    model,
                    subject,
                    body,
                    verdict,
                    json.dumps(checks),
                    str(DraftStatus.REVIEW),
                    _now(),
                ),
            )
            draft_id = int(cursor.lastrowid)
            if generation is not None:
                snapshot = {**generation, "contact_id": contact_id}
                self._conn.execute(
                    "INSERT INTO draft_generations "
                    "(draft_id,campaign_id,contact_id,instruction_hash,snapshot_json) "
                    "VALUES (?,?,?,?,?)",
                    (
                        draft_id,
                        snapshot["campaign_id"],
                        contact_id,
                        snapshot["instruction_hash"],
                        json.dumps(snapshot, ensure_ascii=False),
                    ),
                )
            self._conn.execute("RELEASE save_generated_draft")
            return draft_id
        except Exception:
            self._conn.execute("ROLLBACK TO save_generated_draft")
            self._conn.execute("RELEASE save_generated_draft")
            raise

    def _draft(self, row: sqlite3.Row) -> DraftRecord:
        keys = row.keys()
        return DraftRecord(
            id=row["id"],
            contact_id=row["contact_id"],
            model=row["model"],
            subject=row["subject"],
            body=row["body"],
            verdict=row["verdict"],
            checks=json.loads(row["checks"]),
            status=DraftStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            reviewed_at=(
                datetime.fromisoformat(row["reviewed_at"]) if row["reviewed_at"] else None
            ),
            company=row["company"] if "company" in keys else None,
            email=row["email"] if "email" in keys else None,
            campaign_id=row["campaign_id"] if "campaign_id" in keys else None,
            generation=(
                json.loads(row["snapshot_json"])
                if "snapshot_json" in keys and row["snapshot_json"]
                else None
            ),
        )

    def get_draft(self, draft_id: int) -> DraftRecord | None:
        row = self._conn.execute(
            "SELECT d.*, c.company, c.email, c.campaign_id, g.snapshot_json FROM drafts d "
            "JOIN contacts c ON c.id = d.contact_id "
            "LEFT JOIN draft_generations g ON g.draft_id=d.id WHERE d.id = ?",
            (draft_id,),
        ).fetchone()
        return self._draft(row) if row else None

    def drafts_in_campaign(self, campaign_id: str) -> list[DraftRecord]:
        """Every draft in a campaign, newest first, with its contact."""
        rows = self._conn.execute(
            "SELECT d.*, c.company, c.email, c.campaign_id, g.snapshot_json FROM drafts d "
            "JOIN contacts c ON c.id = d.contact_id "
            "LEFT JOIN draft_generations g ON g.draft_id=d.id "
            "WHERE c.campaign_id = ? ORDER BY d.id DESC",
            (campaign_id,),
        )
        return [self._draft(r) for r in rows]

    def update_draft(
        self, draft_id: int, *, subject: str, body: str, verdict: str, checks: list[dict]
    ) -> None:
        self._conn.execute(
            "UPDATE drafts SET subject = ?, body = ?, verdict = ?, checks = ? WHERE id = ?",
            (subject, body, verdict, json.dumps(checks), draft_id),
        )

    def set_draft_status(self, draft_id: int, status: DraftStatus) -> None:
        self._conn.execute(
            "UPDATE drafts SET status = ?, reviewed_at = ? WHERE id = ?",
            (str(status), _now(), draft_id),
        )

    # --- what the sender needs to stay safe --------------------------------

    def already_written_to(self, contact_id: int) -> bool:
        """True if this contact has a message that was sent — or that was
        being sent when something crashed. A 'pending' row is treated as sent:
        re-sending after a crash is the failure this table exists to prevent."""
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE contact_id = ? AND status IN ('sent', 'pending')",
            (contact_id,),
        ).fetchone()
        return row is not None

    def sent_today(self) -> int:
        """Emails sent since midnight UTC, across every campaign."""
        today = datetime.now(UTC).date().isoformat()
        return self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'sent' AND substr(sent_at, 1, 10) = ?",
            (today,),
        ).fetchone()[0]

    # --- replies ------------------------------------------------------------

    def sending_slots_today(self) -> int:
        """Reserve room for uncertain sends too, without calling them delivered."""
        today = datetime.now(UTC).date().isoformat()
        return self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE "
            "(status='sent' AND substr(sent_at,1,10)=?) OR "
            "(status='pending' AND substr(created_at,1,10)=?)",
            (today, today),
        ).fetchone()[0]

    def claim_reply_send(self, reply_id: int, message_id: str) -> bool:
        """Only a known failed answer may be replaced; pending/sent stays fenced."""
        row = self._conn.execute(
            "INSERT INTO reply_sends (reply_id,message_id) VALUES (?,?) "
            "ON CONFLICT(reply_id) DO UPDATE SET message_id=excluded.message_id "
            "WHERE EXISTS (SELECT 1 FROM messages m WHERE "
            "m.message_id=reply_sends.message_id AND m.status='failed')",
            (reply_id, message_id),
        )
        return row.rowcount == 1

    def _sent(self, row) -> SentRecord | None:
        if row is None:
            return None
        return SentRecord(
            message_id=row["message_id"],
            contact_id=row["contact_id"],
            recipient_email=row["recipient_email"],
            subject=row["subject"],
            body_text=row["body_text"],
            sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        )

    def find_message(self, message_id: str) -> SentRecord | None:
        """One of our sent emails, by its Message-ID."""
        return self._sent(
            self._conn.execute(
                "SELECT * FROM messages WHERE message_id = ? AND status = 'sent'",
                (message_id.strip(),),
            ).fetchone()
        )

    def last_message_to(self, email: str) -> SentRecord | None:
        """The most recent email we sent to this address."""
        return self._sent(
            self._conn.execute(
                "SELECT * FROM messages WHERE recipient_email = ? AND status = 'sent' "
                "ORDER BY sent_at DESC LIMIT 1",
                (normalize_email(email),),
            ).fetchone()
        )

    def sent_subjects(self) -> set[str]:
        return {
            r[0] for r in self._conn.execute("SELECT subject FROM messages WHERE status='sent'")
        }

    def first_send_at(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT MIN(sent_at) FROM messages WHERE status = 'sent'"
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def has_reply(self, provider_message_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM replies WHERE provider_message_id = ?", (provider_message_id,)
            ).fetchone()
            is not None
        )

    def save_reply(self, message: InboundMessage, *, message_id: str | None) -> int:
        """Record a reply exactly as it arrived. Returns its id."""
        cursor = self._conn.execute(
            "INSERT INTO replies (message_id, provider_message_id, from_address, subject, "
            "body_text, received_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                message_id,
                message.message_id,
                normalize_email(message.from_address),
                message.subject,
                message.body_text,
                message.received_at.isoformat(),
            ),
        )
        return int(cursor.lastrowid)

    def save_triage(
        self,
        reply_id: int,
        *,
        contact_id: int | None,
        matched_by: str,
        category: str,
        summary: str = "",
        details: dict[str, str] | None = None,
        suggested_reply: str = "",
        action: str = "",
    ) -> None:
        """How a reply was read. Reading it again replaces this, but keeps
        whether you had already marked it done."""
        self._conn.execute(
            "INSERT INTO reply_triage (reply_id, contact_id, matched_by, category, summary, "
            "details, suggested_reply, action, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(reply_id) DO UPDATE SET contact_id = excluded.contact_id, "
            "matched_by = excluded.matched_by, category = excluded.category, "
            "summary = excluded.summary, details = excluded.details, "
            "suggested_reply = excluded.suggested_reply, action = excluded.action",
            (
                reply_id,
                contact_id,
                matched_by,
                category,
                summary,
                json.dumps(details or {}),
                suggested_reply,
                action,
                _now(),
            ),
        )

    def replies_needing_triage(self) -> list[int]:
        """Replies not yet read, or whose reading failed last time."""
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT r.id FROM replies r LEFT JOIN reply_triage t ON t.reply_id = r.id "
                "WHERE t.reply_id IS NULL OR t.category = 'unread' ORDER BY r.id"
            )
        ]

    _REPLY_SELECT = (
        "SELECT r.*, t.contact_id, t.matched_by, t.category, t.summary, t.details, "
        "t.suggested_reply, t.action, t.status, c.company, c.campaign_id, "
        "m.recipient_email FROM replies r "
        "LEFT JOIN reply_triage t ON t.reply_id = r.id "
        "LEFT JOIN contacts c ON c.id = t.contact_id "
        "LEFT JOIN messages m ON m.message_id = r.message_id "
    )

    def _reply(self, row) -> ReplyRecord:
        return ReplyRecord(
            id=row["id"],
            from_address=row["from_address"],
            subject=row["subject"],
            body_text=row["body_text"],
            received_at=datetime.fromisoformat(row["received_at"]),
            provider_message_id=row["provider_message_id"],
            message_id=row["message_id"],
            contact_id=row["contact_id"],
            matched_by=row["matched_by"],
            category=row["category"],
            summary=row["summary"] or "",
            details=json.loads(row["details"] or "{}"),
            suggested_reply=row["suggested_reply"] or "",
            action=row["action"] or "",
            status=ReplyStatus(row["status"] or "new"),
            company=row["company"],
            campaign_id=row["campaign_id"],
            recipient_email=row["recipient_email"],
        )

    def get_reply(self, reply_id: int) -> ReplyRecord | None:
        row = self._conn.execute(self._REPLY_SELECT + "WHERE r.id = ?", (reply_id,)).fetchone()
        return self._reply(row) if row else None

    def list_replies(self) -> list[ReplyRecord]:
        """Newest first."""
        return [
            self._reply(r)
            for r in self._conn.execute(self._REPLY_SELECT + "ORDER BY r.received_at DESC")
        ]

    def set_reply_status(self, reply_id: int, status: ReplyStatus) -> None:
        self._conn.execute(
            "UPDATE reply_triage SET status = ? WHERE reply_id = ?", (str(status), reply_id)
        )
