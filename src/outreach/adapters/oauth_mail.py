"""OAuth authorization and HTTPS mail, with encrypted refresh tokens and no send retries."""

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit

import httpx

from outreach.adapters.credential_vault import CredentialVault
from outreach.adapters.db import connect
from outreach.adapters.mail_smtp_imap import SmtpImapMailbox, parse_message
from outreach.adapters.platform_store import PlatformStore, now
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import ConfigError
from outreach.core.models import SentMessage
from outreach.core.normalize import normalize_email
from outreach.ports.mail import MailAuthError, MailError, MailUncertainError

REGIONS = ("com", "in", "eu", "com.au", "jp", "ca")
SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
    "zoho": "ZohoMail.accounts.READ,ZohoMail.messages.READ,ZohoMail.messages.CREATE",
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OAuthMail:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=30)

    def store(self):
        return PlatformStore(SqliteStore(connect(self.settings.db_path)))

    def configuration(self, provider, region="com"):
        if provider not in SCOPES or region not in REGIONS:
            raise ConfigError("Choose Gmail or Zoho and a supported region.")
        s = self.settings
        prefix = "google" if provider == "gmail" else "zoho"
        s.require(
            "app_password", "oauth_public_url", prefix + "_client_id", prefix + "_client_secret"
        )
        url = urlsplit(s.oauth_public_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ConfigError("OAuth needs the app's HTTPS origin, without a path or query.")
        if url.hostname.casefold() not in {
            h.strip().casefold() for h in s.allowed_hosts.split(",")
        }:
            raise ConfigError("Add the OAuth app hostname to OUTREACH_ALLOWED_HOSTS.")
        return {
            "client_id": getattr(s, prefix + "_client_id"),
            "client_secret": getattr(s, prefix + "_client_secret"),
            "redirect_uri": s.oauth_public_url.rstrip("/")
            + "/accounts/oauth/"
            + provider
            + "/callback",
        }

    def readiness(self):
        result = {}
        for provider in SCOPES:
            try:
                self.configuration(provider)
                result[provider] = {"ready": True, "reason": "Ready for provider consent."}
            except ConfigError:
                result[provider] = {
                    "ready": False,
                    "reason": "Sign-in needs an HTTPS app address, workspace protection "
                    "and provider credentials. See Administrator setup below.",
                }
        return result

    def begin(self, provider, region, values, browser):
        config = self.configuration(provider, region)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        payload = {"provider": provider, "region": region, "values": values, "verifier": verifier}
        cipher = CredentialVault(self.settings).encrypt(json.dumps(payload))
        with self.store() as db:
            db.conn.execute("DELETE FROM oauth_attempts WHERE expires_at<?", (int(time.time()),))
            db.conn.execute(
                "INSERT INTO oauth_attempts VALUES (?,?,?,?)",
                (digest(state), digest(browser), cipher, int(time.time()) + 600),
            )
        params = {k: v for k, v in config.items() if k != "client_secret"}
        params.update(
            response_type="code",
            scope=SCOPES[provider],
            state=state,
            access_type="offline",
            prompt="consent",
        )
        if provider == "gmail":
            params.update(
                code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("="),
                code_challenge_method="S256",
            )
        base = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            if provider == "gmail"
            else ("https://accounts.zoho." + region + "/oauth/v2/auth")
        )
        return base + "?" + urlencode(params)

    def consume(self, provider, state, browser):
        with self.store() as db, db.transaction():
            row = db.one("SELECT * FROM oauth_attempts WHERE state_hash=?", (digest(state),))
            if (
                not row
                or row["expires_at"] <= time.time()
                or not browser
                or not secrets.compare_digest(row["browser_hash"], digest(browser))
            ):
                raise ConfigError(
                    "This sign-in expired or belongs to another browser. Start again."
                )
            payload = json.loads(CredentialVault(self.settings).decrypt(row["payload_cipher"]))
            if payload["provider"] != provider:
                raise ConfigError("The sign-in provider does not match. Start again.")
            db.conn.execute("DELETE FROM oauth_attempts WHERE state_hash=?", (digest(state),))
            return payload

    def token(self, provider, region, **grant):
        config = self.configuration(provider, region)
        endpoint = (
            "https://oauth2.googleapis.com/token"
            if provider == "gmail"
            else ("https://accounts.zoho." + region + "/oauth/v2/token")
        )
        try:
            response = self.client.post(endpoint, data=config | grant)
            data = response.json()
            if response.is_error or data.get("error") or not data.get("access_token"):
                raise MailAuthError(
                    "Provider sign-in failed. Reconnect and check OAuth configuration."
                )
            data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
            return data
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise MailAuthError("Could not complete provider sign-in. Start again.") from exc

    def complete(self, provider, payload, code):
        region = payload["region"]
        grant = {"grant_type": "authorization_code", "code": code}
        if provider == "gmail":
            grant["code_verifier"] = payload["verifier"]
        tokens = self.token(provider, region, **grant)
        if not tokens.get("refresh_token"):
            raise MailAuthError("Offline access was not granted. Reconnect with provider consent.")
        if tokens.get("scope"):
            granted = set(tokens["scope"].replace(",", " ").split())
            required = set(SCOPES[provider].replace(",", " ").split())
            if not required <= granted:
                raise MailAuthError("Required read/send permissions were not granted. Reconnect.")
        box = ApiMailbox(self.settings, self, provider, region, "", tokens, "")
        email, remote = box.identity()
        email = normalize_email(email)
        box.email, box.remote = email, remote
        box.verify_inbox()
        values = payload["values"] | {
            "email": email,
            "username": email,
            "smtp_host": "",
            "smtp_port": 465,
            "imap_host": "",
            "imap_port": 993,
        }
        with self.store() as db:
            old = db.one("SELECT id FROM mail_accounts WHERE lower(email)=lower(?)", (email,))
            key = db.save_account(values, "", old["id"] if old else None)
            db.conn.execute(
                "INSERT INTO mail_oauth VALUES (?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                "provider=excluded.provider,region=excluded.region,"
                "remote_account_id=excluded.remote_account_id,token_cipher=excluded.token_cipher",
                (
                    key,
                    provider,
                    region,
                    remote,
                    CredentialVault(self.settings).encrypt(json.dumps(tokens)),
                ),
            )
            db.conn.execute(
                "UPDATE mail_accounts SET verified_at=?,last_error='' WHERE id=?", (now(), key)
            )
        return key

    def mailbox(self, identity):
        with self.store() as db:
            row = db.one(
                "SELECT o.*,a.email FROM mail_oauth o JOIN mail_accounts a "
                "ON a.id=o.account_id WHERE o.account_id=?",
                (identity.mail_account_id,),
            )
        if not row:
            raise MailAuthError("OAuth account disconnected. Reconnect it before sending.")
        if not row["token_cipher"]:
            raise MailAuthError("OAuth account disconnected. Reconnect before using it.")
        tokens = json.loads(CredentialVault(self.settings).decrypt(row["token_cipher"]))
        return ApiMailbox(
            identity,
            self,
            row["provider"],
            row["region"],
            row["remote_account_id"],
            tokens,
            row["account_id"],
            row["email"],
        )


class ApiMailbox:
    def __init__(self, settings, oauth, provider, region, remote, tokens, account_id, email=""):
        self._s, self.oauth, self.provider, self.region = settings, oauth, provider, region
        self.remote, self.tokens, self.account_id, self.email = remote, tokens, account_id, email

    @property
    def base(self):
        return (
            "https://gmail.googleapis.com/gmail/v1/users/me"
            if self.provider == "gmail"
            else ("https://mail.zoho." + self.region + "/api/accounts")
        )

    def auth_failed(self):
        if self.account_id:
            with self.oauth.store() as db:
                db.conn.execute(
                    "UPDATE mail_accounts SET verified_at=NULL,last_error=? WHERE id=?",
                    (
                        "Mail permissions expired or were refused. Verify or reconnect OAuth.",
                        self.account_id,
                    ),
                )

    def request(self, method, path, *, sending=False, **kwargs):
        if self.account_id:
            with self.oauth.store() as db:
                connection = db.one(
                    "SELECT token_cipher FROM mail_oauth WHERE account_id=?", (self.account_id,)
                )
            if not connection or not connection["token_cipher"]:
                raise MailAuthError("OAuth account disconnected. Reconnect before using it.")
        if self.tokens["expires_at"] < time.time() + 60:
            try:
                fresh = self.oauth.token(
                    self.provider,
                    self.region,
                    grant_type="refresh_token",
                    refresh_token=self.tokens["refresh_token"],
                )
            except MailAuthError:
                self.auth_failed()
                raise
            self.tokens.update(fresh)
            with self.oauth.store() as db:
                refreshed = db.conn.execute(
                    "UPDATE mail_oauth SET token_cipher=? WHERE account_id=? AND token_cipher!=''",
                    (CredentialVault(self._s).encrypt(json.dumps(self.tokens)), self.account_id),
                )
                if self.account_id and refreshed.rowcount != 1:
                    raise MailAuthError("Account disconnected during refresh. Reconnect first.")
        header = "Bearer " if self.provider == "gmail" else "Zoho-oauthtoken "
        try:
            response = self.oauth.client.request(
                method,
                self.base + path,
                headers={
                    **kwargs.pop("headers", {}),
                    "Authorization": header + self.tokens["access_token"],
                },
                **kwargs,
            )
            if response.status_code in (401, 403):
                self.auth_failed()
                raise MailAuthError(
                    "Mail access refused. Reconnect this account and check permissions."
                )
            if response.status_code >= 500:
                raise (
                    MailUncertainError("Provider error: delivery may have occurred. Do not resend.")
                    if sending
                    else MailError("Mail provider temporarily unavailable.")
                )
            if response.is_error:
                raise MailError("The mail provider refused this request.")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a provider response object.")
            if self.provider == "zoho":
                status = int(data.get("status", {}).get("code", 200))
                if status >= 500 and sending:
                    raise MailUncertainError(
                        "Provider error: delivery may have occurred. Do not resend."
                    )
                if status >= 400:
                    raise MailError(
                        "Zoho refused this request. Check account permissions and plan."
                    )
            return data
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if sending:
                raise MailUncertainError(
                    "Delivery uncertain. Inspect Sent before retrying."
                ) from exc
            raise MailError("Could not read from the mail provider. Try again later.") from exc

    def identity(self):
        if self.provider == "gmail":
            data = self.request("GET", "/profile")
            return data["emailAddress"].casefold(), "me"
        accounts = self.request("GET", "").get("data", [])
        accounts = [a for a in accounts if a.get("type") == "ZOHO_ACCOUNT" and a.get("enabled")]
        if len(accounts) != 1:
            raise MailAuthError(
                "Expected one primary Zoho mailbox. Check your account configuration."
            )
        return accounts[0]["primaryEmailAddress"].casefold(), str(accounts[0]["accountId"])

    def verify_login(self):
        email, remote = self.identity()
        if email != self.email or remote != self.remote:
            raise MailAuthError("Provider mailbox identity changed. Reconnect this account.")

    def verify_inbox(self):
        if self.provider == "gmail":
            self.request("GET", "/messages", params={"maxResults": 1, "labelIds": "INBOX"})
        else:
            self.request(
                "GET",
                "/" + self.remote + "/messages/search",
                params={"searchKey": "in:inbox", "limit": 1},
            )

    def remember(self, local, remote, mime=None):
        with self.oauth.store() as db:
            db.conn.execute(
                "INSERT INTO mail_api_ids VALUES (?,?,?,?) "
                "ON CONFLICT(account_id,local_id) DO UPDATE SET remote_id=excluded.remote_id,"
                "mime_id=excluded.mime_id",
                (self.account_id, local, str(remote), mime),
            )

    def send(self, message):
        if self.email != self._s.sender_email:
            raise MailAuthError("The chosen sending identity does not match its OAuth account.")
        if self.provider == "gmail":
            # Reuse exact MIME headers, signature and threading from the existing adapter.
            raw = SmtpImapMailbox.build(self, message).as_bytes()
            data = self.request(
                "POST",
                "/messages/send",
                sending=True,
                json={"raw": base64.urlsafe_b64encode(raw).decode()},
            )
            if not data.get("id"):
                raise MailUncertainError("Missing provider receipt. Inspect Sent before retrying.")
            try:
                self.remember(message.message_id, data["id"], message.message_id)
            except Exception as exc:
                raise MailUncertainError(
                    "Sent, but receipt storage failed. Inspect Sent; do not resend."
                ) from exc
        else:
            path = "/" + self.remote + "/messages"
            content = {
                "fromAddress": self.email,
                "toAddress": message.to,
                "subject": message.subject,
                "content": message.body_text,
                "mailFormat": "plaintext",
                "encoding": "UTF-8",
                "isSchedule": False,
            }
            if message.in_reply_to:
                with self.oauth.store() as db:
                    row = db.one(
                        "SELECT remote_id FROM mail_api_ids WHERE account_id=? AND mime_id=?",
                        (self.account_id, message.in_reply_to),
                    )
                if not row:
                    raise MailError(
                        "This reply has no Zoho thread reference. Sync the inbox first."
                    )
                path += "/" + row["remote_id"]
                content["action"] = "reply"
            if message.attachments:
                uploaded = []
                for file in message.attachments:
                    receipt = self.request(
                        "POST",
                        "/" + self.remote + "/messages/attachments",
                        params={"fileName": file.filename, "isInline": "false"},
                        content=file.content,
                        headers={"Content-Type": "application/octet-stream"},
                    ).get("data")
                    if not isinstance(receipt, list) or len(receipt) != 1:
                        raise MailError("Attachment upload receipt missing. No email was sent.")
                    item = receipt[0]
                    fields = ("attachmentName", "attachmentPath", "storeName")
                    if not isinstance(item, dict) or any(
                        not isinstance(item.get(k), str) or not item[k] for k in fields
                    ):
                        raise MailError("Attachment upload receipt incomplete. No email was sent.")
                    uploaded.append({k: item[k] for k in fields})
                content["attachments"] = uploaded
            data = self.request("POST", path, sending=True, json=content).get("data", {})
            remote = data.get("messageId") if isinstance(data, dict) else None
            if not remote:
                raise MailUncertainError("Missing Zoho receipt. Inspect Sent before retrying.")
            try:
                self.remember(message.message_id, remote)
                parsed = parse_message(
                    self.request(
                        "GET", "/" + self.remote + "/messages/" + str(remote) + "/originalmessage"
                    )["data"]["content"].encode()
                )
                if not parsed:
                    raise MailError("Cannot read sent headers.")
                self.remember(message.message_id, remote, parsed.message_id)
            except Exception as exc:
                raise MailUncertainError(
                    "Sent, but thread receipt is unresolved. Inspect Sent; do not resend."
                ) from exc
        return SentMessage(message_id=message.message_id, to=message.to, sent_at=datetime.now(UTC))

    def fetch_replies(self, since=None):
        messages = []
        token, start = None, 1
        while True:
            if self.provider == "gmail":
                params = {"maxResults": 100, "labelIds": "INBOX"}
                if since:
                    params["q"] = "after:" + str(int(since.timestamp()) - 86400)
                if token:
                    params["pageToken"] = token
                page = self.request("GET", "/messages", params=params)
                for item in page.get("messages", []):
                    raw = self.request("GET", "/messages/" + item["id"], params={"format": "raw"})[
                        "raw"
                    ]
                    parsed = parse_message(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
                    if parsed:
                        messages.append(parsed)
                token = page.get("nextPageToken")
                if not token:
                    return messages
            else:
                query = "in:inbox" + (" after:" + since.strftime("%d-%b-%Y") if since else "")
                page = self.request(
                    "GET",
                    "/" + self.remote + "/messages/search",
                    params={"searchKey": query, "limit": 200, "start": start},
                )
                items = page.get("data", [])
                for item in items:
                    raw = self.request(
                        "GET",
                        "/"
                        + self.remote
                        + "/messages/"
                        + str(item["messageId"])
                        + "/originalmessage",
                    )["data"]["content"]
                    parsed = parse_message(raw.encode())
                    if parsed:
                        self.remember(
                            "inbound:" + parsed.message_id, item["messageId"], parsed.message_id
                        )
                        messages.append(parsed)
                if len(items) < 200:
                    return messages
                start += len(items)
