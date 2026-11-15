"""Scope reply matching to the mailbox that received the message."""

from datetime import datetime

from outreach.adapters.store_sqlite import SqliteStore
from outreach.core.normalize import normalize_email


class MailboxStore(SqliteStore):
    def __init__(self, conn, account_id):
        super().__init__(conn)
        self.account_id = account_id

    def _messages(self, condition, args=(), order=""):
        return self._conn.execute(
            "SELECT m.* FROM messages m JOIN contacts c ON c.id=m.contact_id "
            "LEFT JOIN campaign_settings s ON s.campaign_id=c.campaign_id "
            "WHERE m.status='sent' AND s.sender_account_id IS ? AND " + condition + " " + order,
            (self.account_id, *args),
        )

    def find_message(self, message_id):
        key = message_id.strip()
        row = self._conn.execute(
            "SELECT local_id FROM mail_api_ids WHERE account_id IS ? AND mime_id=?",
            (self.account_id, key),
        ).fetchone()
        return self._sent(self._messages("m.message_id=?", (row[0] if row else key,)).fetchone())

    def last_message_to(self, email):
        return self._sent(
            self._messages(
                "m.recipient_email=?", (normalize_email(email),), "ORDER BY m.sent_at DESC LIMIT 1"
            ).fetchone()
        )

    def sent_subjects(self):
        return {r["subject"] for r in self._messages("1=1")}

    def first_send_at(self):
        row = self._messages("1=1", order="ORDER BY m.sent_at LIMIT 1").fetchone()
        return datetime.fromisoformat(row["sent_at"]) if row else None

    def save_reply(self, message, *, message_id):
        key = super().save_reply(message, message_id=message_id)
        self._conn.execute("INSERT INTO reply_mailboxes VALUES (?,?)", (key, self.account_id))
        return key

    def replies_needing_triage(self):
        return [
            r[0]
            for r in self._conn.execute(
                "SELECT r.id FROM replies r LEFT JOIN reply_triage t ON t.reply_id=r.id "
                "LEFT JOIN reply_mailboxes b ON b.reply_id=r.id WHERE b.account_id IS ? "
                "AND (t.reply_id IS NULL OR t.category='unread') ORDER BY r.id",
                (self.account_id,),
            )
        ]
