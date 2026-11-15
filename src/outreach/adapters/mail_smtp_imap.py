"""Gmail and Zoho mailboxes over SMTP and IMAP — the real implementation of `MailPort` (D-002).

This is the only file allowed to import `smtplib`, `imaplib` and `email`
(invariant I-1).

Sending is deliberately **not retried**. If a connection drops after the
server has accepted a message, a retry sends it twice, and there is no way to
tell from here which happened. A transport interruption retains the pending
send record until a person reconciles delivery. Explicit server refusals are recorded as failed.

Reading replies (IMAP, D-023) is strictly read-only: the inbox is opened
read-only and messages are fetched with BODY.PEEK, so nothing is marked read,
moved or deleted. What counts as a reply is decided in `core.replies`; this
file only turns raw mail into `InboundMessage`s.
"""

from __future__ import annotations

import contextlib
import hashlib
import imaplib
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parseaddr, parsedate_to_datetime

from outreach.config import Settings
from outreach.core.models import InboundMessage, OutboundMessage, SentMessage
from outreach.ports.mail import MailAuthError, MailError, MailUncertainError

_TIMEOUT_SECONDS = 30


class SmtpImapMailbox:
    """Implements `outreach.ports.mail.MailPort` against an SMTP mailbox."""

    def __init__(self, settings: Settings) -> None:
        settings.require(*Settings.SEND)
        self._s = settings

    # --- connecting ---------------------------------------------------------

    def _connect(self) -> smtplib.SMTP:
        s = self._s
        try:
            if s.mail_smtp_port == 465:
                server: smtplib.SMTP = smtplib.SMTP_SSL(
                    s.mail_smtp_host,
                    s.mail_smtp_port,
                    timeout=_TIMEOUT_SECONDS,
                    context=ssl.create_default_context(),
                )
            else:
                server = smtplib.SMTP(s.mail_smtp_host, s.mail_smtp_port, timeout=_TIMEOUT_SECONDS)
                server.starttls(context=ssl.create_default_context())
            server.login(s.mail_username, s.mail_password)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailAuthError(
                "The email provider refused the login. Use an app-specific password "
                "and check SMTP access in your account settings."
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise MailAuthError(
                f"Could not reach {s.mail_smtp_host}:{s.mail_smtp_port} — {exc}. "
                "Check the host and port in Zoho: Settings → Mail Accounts → IMAP/SMTP."
            ) from exc
        return server

    def verify_login(self) -> None:
        """Log in and out without sending anything. Used by `outreach check`."""
        self._connect().quit()

    # --- sending ------------------------------------------------------------

    def build(self, message: OutboundMessage) -> EmailMessage:
        """The exact email that would be sent. Separate so it can be inspected."""
        s = self._s
        email = EmailMessage()
        email["From"] = formataddr((s.sender_name, s.sender_email))
        email["To"] = message.to
        email["Subject"] = message.subject
        email["Message-ID"] = message.message_id
        email["Date"] = formatdate(localtime=True)
        # Deliberately no List-Unsubscribe header (D-018). It is what mailing
        # lists carry, Gmail reads it as a bulk-mail signal, and on the first
        # real test it put a one-to-one email into Promotions. Gmail requires
        # it only of senders of 5,000+ emails a day. The opt-out lives in the
        # signature instead, as a person would write it.
        if message.in_reply_to:
            email["In-Reply-To"] = message.in_reply_to
            email["References"] = message.in_reply_to
        email.set_content(message.body_text)
        for file in message.attachments:
            maintype, subtype = file.mime_type.split("/", 1)
            email.add_attachment(
                file.content, maintype=maintype, subtype=subtype, filename=file.filename
            )
        return email

    def send(self, message: OutboundMessage) -> SentMessage:
        server = self._connect()
        try:
            server.send_message(self.build(message))
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(f"The email provider refused the address {message.to}: {exc}") from exc
        except (smtplib.SMTPDataError, smtplib.SMTPSenderRefused) as exc:
            raise MailError("The email provider refused this message.") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise MailUncertainError(
                "Connection interrupted. Delivery is uncertain; inspect the Sent "
                "folder before retrying."
            ) from exc
        finally:
            # The message is already sent or already failed; a noisy goodbye
            # from the server changes neither.
            with contextlib.suppress(smtplib.SMTPException, OSError):
                server.quit()
        return SentMessage(
            message_id=message.message_id,
            to=message.to,
            sent_at=datetime.now(UTC),
        )

    # --- reading replies ----------------------------------------------------

    def _imap(self) -> imaplib.IMAP4_SSL:
        s = self._s
        if not s.mail_imap_host:
            raise MailAuthError(
                "OUTREACH_MAIL_IMAP_HOST is not set. For Zoho India it is imappro.zoho.in."
            )
        try:
            imap = imaplib.IMAP4_SSL(
                s.mail_imap_host,
                s.mail_imap_port,
                timeout=_TIMEOUT_SECONDS,
                ssl_context=ssl.create_default_context(),
            )
            imap.login(s.mail_username, s.mail_password)
        except imaplib.IMAP4.error as exc:
            raise MailAuthError(
                f"Zoho refused the inbox login ({exc}). Check that IMAP access is on "
                "(Zoho Mail: Settings → Mail Accounts → IMAP Access) and that the app "
                "password is right."
            ) from exc
        except OSError as exc:
            raise MailAuthError(
                f"Could not reach {s.mail_imap_host}:{s.mail_imap_port} — {exc}."
            ) from exc
        return imap

    def verify_inbox(self) -> None:
        """Log in to the inbox and out, reading nothing."""
        imap = self._imap()
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            imap.logout()

    def fetch_replies(self, since: datetime | None = None) -> list[InboundMessage]:
        """Every message in the inbox since `since` (a day's precision), parsed.

        Read-only: the folder is selected read-only and bodies fetched with
        BODY.PEEK, so the operator's unread mail stays unread."""
        imap = self._imap()
        try:
            status, _ = imap.select("INBOX", readonly=True)
            if status != "OK":
                raise MailError("Could not open the inbox.")
            criteria = f'(SINCE "{since:%d-%b-%Y}")' if since else "ALL"
            status, data = imap.search(None, criteria)
            if status != "OK":
                raise MailError("The inbox search failed.")
            messages: list[InboundMessage] = []
            for number in (data[0] or b"").split():
                status, parts = imap.fetch(number, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw and (parsed := parse_message(raw)):
                    messages.append(parsed)
            return messages
        except imaplib.IMAP4.error as exc:
            raise MailError(f"Reading the inbox failed: {exc}") from exc
        finally:
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                imap.logout()


_ID = re.compile(r"<[^<>\s]+>")
_TAGS = re.compile(r"<[^>]+>")


def _text_of(message) -> str:
    """The readable text. For a delivery report (a bounce), every text part —
    including the returned headers, which carry our Message-ID."""
    if message.get_content_type() == "multipart/report":
        chunks = []
        for part in message.walk():
            kind = part.get_content_type()
            if kind == "message/delivery-status":  # the status codes, e.g. 5.1.1
                chunks.extend(str(block) for block in part.get_payload())
            elif kind == "message/rfc822":  # the returned email: its headers
                inner = part.get_payload(0)
                chunks.append("".join(f"{k}: {v}\n" for k, v in inner.items()))
            elif not part.is_multipart():
                with contextlib.suppress(Exception):
                    chunks.append(str(part.get_content()))
        return "\n".join(chunks)
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    try:
        text = body.get_content()
    except Exception:  # an undecodable part must not stop the inbox check
        payload = body.get_payload(decode=True) or b""
        text = payload.decode("utf-8", errors="replace")
    if body.get_content_type() == "text/html":
        text = _TAGS.sub(" ", re.sub(r"(?i)<br\s*/?>|</p>", "\n", text))
    return str(text)


def parse_message(raw: bytes) -> InboundMessage | None:
    """Raw mail → `InboundMessage`, or None if it has no usable sender."""
    message = message_from_bytes(raw, policy=policy.default)
    address = parseaddr(str(message.get("From", "")))[1]
    if "@" not in address:
        return None
    try:
        received = parsedate_to_datetime(str(message.get("Date")))
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received = datetime.now(UTC)
    auto = str(message.get("Auto-Submitted", "no")).strip().lower()
    precedence = str(message.get("Precedence", "")).strip().lower()
    # A stable stand-in when a message has no Message-ID, so the same message
    # is recognised as already stored at the next check.
    message_id = (
        str(message.get("Message-ID", "")).strip()
        or f"<no-id-{hashlib.sha256(raw).hexdigest()[:32]}@local>"
    )
    try:
        return InboundMessage(
            message_id=message_id,
            from_address=address.lower(),
            subject=str(message.get("Subject", "")),
            body_text=_text_of(message),
            received_at=received,
            in_reply_to=(_ID.findall(str(message.get("In-Reply-To", ""))) or [None])[0],
            references=_ID.findall(str(message.get("References", ""))),
            auto_submitted=(auto not in ("", "no"))
            or precedence in ("auto_reply", "auto-reply")
            or message.get("X-Autoreply") is not None
            or message.get("X-Autorespond") is not None,
        )
    except ValueError:  # an address our validator rejects: not something we wrote to
        return None
