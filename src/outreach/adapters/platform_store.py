"""Durable projects, research, review, account metadata and campaign enrollment."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from outreach.core.models import Campaign, Contact
from outreach.core.research import ResearchBudgetStop, ResearchStop, host, literal, same_site


def enrollment_evidence(lead):
    """Snapshot supported facts and provenance without promoting review notes."""
    evidence, provenance = {}, {}
    sources = {source["url"]: source for source in lead["sources"]}
    context_count = 0
    for fact in lead["facts"]:
        if fact["status"] != "supported":
            continue
        source_url = fact.get("source_url")
        source = sources.get(source_url, {})
        personal = fact.get("kind") == "personalization"
        if personal and not (
            source_url
            and same_site(source_url, lead["website"])
            and literal(fact["quote"], source.get("text", ""))
        ):
            continue
        field = fact["criterion"]
        if personal:
            context_count += 1
            field = f"Company context {context_count}"
        if field in {"research_sources", "research_run", "review_note", "source_website"}:
            continue
        while field in evidence:
            field += " (additional)"
        evidence[field] = fact["quote"]
        if source_url:
            provenance[field] = {
                "source_url": source_url,
                "retrieved_at": source.get("retrieved_at"),
                "kind": fact.get("kind", "qualification"),
            }
    evidence["source_website"] = lead["website"]
    if provenance:
        evidence["research_sources"] = json.dumps(provenance, ensure_ascii=False)
    return evidence


PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, purpose TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_accounts (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 sender_name TEXT NOT NULL, company TEXT NOT NULL, address TEXT NOT NULL,
 smtp_host TEXT NOT NULL, smtp_port INTEGER NOT NULL, imap_host TEXT NOT NULL,
 imap_port INTEGER NOT NULL, username TEXT NOT NULL, password_cipher TEXT NOT NULL,
 verified_at TEXT, last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_settings (
 campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
 project_id TEXT REFERENCES projects(id), purpose TEXT NOT NULL DEFAULT 'sales',
 tags TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
 sender_account_id TEXT REFERENCES mail_accounts(id)
);
CREATE TABLE IF NOT EXISTS campaign_briefs (
 campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id), preferences_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_oauth (
 account_id TEXT PRIMARY KEY REFERENCES mail_accounts(id), provider TEXT NOT NULL,
 region TEXT NOT NULL, remote_account_id TEXT NOT NULL, token_cipher TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_attempts (
 state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, payload_cipher TEXT NOT NULL,
 expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_api_ids (
 account_id TEXT NOT NULL REFERENCES mail_accounts(id), local_id TEXT NOT NULL,
 remote_id TEXT NOT NULL, mime_id TEXT, PRIMARY KEY(account_id,local_id)
);
CREATE TABLE IF NOT EXISTS mail_test_runs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES mail_accounts(id),
 recipient TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_runs (
 id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), title TEXT NOT NULL,
 brief TEXT NOT NULL, purpose TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
 target_count INTEGER NOT NULL, budget_micro INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft', plan_json TEXT, plan_version INTEGER NOT NULL DEFAULT 1,
 progress TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', worker_pid INTEGER,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, approved_at TEXT
);
CREATE TABLE IF NOT EXISTS research_execution (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, state_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS research_suggestions (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
 identity TEXT NOT NULL, company TEXT NOT NULL, evidence_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '', lead_id INTEGER,
 UNIQUE(run_id,identity)
);
CREATE TABLE IF NOT EXISTS research_intakes (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id), preferences_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_research_runs (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
 campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS research_trash (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE, deleted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_archives (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id), archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_messages (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_runs(id),
 role TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_calls (
 run_id TEXT NOT NULL REFERENCES research_runs(id), call_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, status TEXT NOT NULL, reserved_micro INTEGER NOT NULL,
 charged_micro INTEGER NOT NULL, cost_kind TEXT NOT NULL DEFAULT 'reserved',
 response_json TEXT, created_at TEXT NOT NULL, PRIMARY KEY(run_id, call_key)
);
CREATE TABLE IF NOT EXISTS lead_entities (
 id INTEGER PRIMARY KEY, company TEXT NOT NULL, domain TEXT NOT NULL,
 identity_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_leads (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_runs(id),
 entity_id INTEGER NOT NULL REFERENCES lead_entities(id), company TEXT NOT NULL,
 website TEXT NOT NULL, discovery_json TEXT NOT NULL,
 facts_json TEXT NOT NULL DEFAULT '[]', sources_json TEXT NOT NULL DEFAULT '[]',
 emails_json TEXT NOT NULL DEFAULT '[]', flags_json TEXT NOT NULL DEFAULT '[]',
 fit_summary TEXT NOT NULL DEFAULT '', processing_status TEXT NOT NULL DEFAULT 'pending',
 review_status TEXT NOT NULL DEFAULT 'pending', selected_email TEXT,
 review_note TEXT NOT NULL DEFAULT '', reviewed_at TEXT,
 UNIQUE(run_id, entity_id)
);
CREATE TABLE IF NOT EXISTS lead_lists (
 id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), name TEXT NOT NULL,
 tags TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lead_list_members (
 list_id TEXT NOT NULL REFERENCES lead_lists(id),
 lead_id INTEGER NOT NULL REFERENCES research_leads(id),
 PRIMARY KEY(list_id, lead_id)
);
CREATE TABLE IF NOT EXISTS contact_origins (
 contact_id INTEGER NOT NULL REFERENCES contacts(id),
 lead_id INTEGER NOT NULL REFERENCES research_leads(id),
 PRIMARY KEY(contact_id, lead_id)
);
CREATE TABLE IF NOT EXISTS reply_mailboxes (
 reply_id INTEGER PRIMARY KEY REFERENCES replies(id), account_id TEXT REFERENCES mail_accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_leads_run ON research_leads(run_id);
CREATE INDEX IF NOT EXISTS idx_research_calls_date ON research_calls(created_at);
"""


def now():
    return datetime.now(UTC).isoformat()


def ident():
    return uuid.uuid4().hex[:16]


class PlatformStore:
    def __init__(self, store):
        self.store = store
        self.conn = store._conn

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def rows(self, sql, values=()):
        return [dict(row) for row in self.conn.execute(sql, values)]

    def one(self, sql, values=()):
        row = self.conn.execute(sql, values).fetchone()
        return dict(row) if row else None

    def projects(self):
        return self.rows("SELECT * FROM projects ORDER BY created_at DESC")

    def add_project(self, name, purpose, tags=""):
        key = ident()
        self.conn.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?)", (key, name, purpose, tags, now())
        )
        return key

    def accounts(self):
        return self.rows(
            "SELECT a.id,label,email,sender_name,company,address,smtp_host,smtp_port,"
            "imap_host,imap_port,username,verified_at,last_error,created_at,"
            "o.provider AS oauth_provider "
            "FROM mail_accounts a LEFT JOIN mail_oauth o ON o.account_id=a.id ORDER BY created_at"
        )

    def account(self, key, *, secret=False):
        rows = (
            self.accounts()
            if not secret
            else self.rows(
                "SELECT a.*,o.provider AS oauth_provider FROM mail_accounts a "
                "LEFT JOIN mail_oauth o ON o.account_id=a.id"
            )
        )
        return next((r for r in rows if r["id"] == key), None)

    def save_account(self, values, encrypted, account_id=None):
        key = account_id or ident()
        with self.transaction():
            if account_id:
                old = self.account(key)
                if old is None:
                    raise ValueError("Account not found.")
                used = self.one(
                    "SELECT 1 FROM messages m JOIN contacts c ON c.id=m.contact_id "
                    "JOIN campaign_settings s ON s.campaign_id=c.campaign_id "
                    "WHERE s.sender_account_id=? LIMIT 1",
                    (key,),
                )
                if used and old["email"] != values["email"]:
                    raise ValueError("Create a new account to change a sender that has sent mail.")
                self.conn.execute(
                    "UPDATE mail_accounts SET label=?,email=?,sender_name=?,company=?,address=?,"
                    "smtp_host=?,smtp_port=?,imap_host=?,imap_port=?,username=?,password_cipher=?,"
                    "verified_at=NULL,last_error='' WHERE id=?",
                    tuple(
                        values[k]
                        for k in (
                            "label",
                            "email",
                            "sender_name",
                            "company",
                            "address",
                            "smtp_host",
                            "smtp_port",
                            "imap_host",
                            "imap_port",
                            "username",
                        )
                    )
                    + (encrypted, key),
                )
                self.conn.execute(
                    "UPDATE drafts SET status='review' WHERE status='approved' AND contact_id IN "
                    "(SELECT c.id FROM contacts c JOIN campaign_settings s ON "
                    "s.campaign_id=c.campaign_id "
                    "WHERE s.sender_account_id=?)",
                    (key,),
                )
            else:
                self.conn.execute(
                    "INSERT INTO mail_accounts (id,label,email,sender_name,company,address,"
                    "smtp_host,smtp_port,imap_host,imap_port,username,password_cipher,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key,)
                    + tuple(
                        values[k]
                        for k in (
                            "label",
                            "email",
                            "sender_name",
                            "company",
                            "address",
                            "smtp_host",
                            "smtp_port",
                            "imap_host",
                            "imap_port",
                            "username",
                        )
                    )
                    + (encrypted, now()),
                )
        return key

    def campaign(self, cid):
        row = self.one(
            "SELECT c.*,s.project_id,s.purpose,s.tags,COALESCE(s.status,'draft') AS status,"
            "s.sender_account_id,s.campaign_id AS workspace_campaign_id,"
            "a.email AS sender_email,a.label AS account_label,a.verified_at "
            "FROM campaigns c LEFT JOIN campaign_settings s ON s.campaign_id=c.id "
            "LEFT JOIN mail_accounts a ON a.id=s.sender_account_id WHERE c.id=?",
            (cid,),
        )
        if row:
            brief = self.one(
                "SELECT preferences_json FROM campaign_briefs WHERE campaign_id=?", (cid,)
            )
            row["message_brief"] = json.loads(brief["preferences_json"]) if brief else None
        return row

    def save_message_brief(self, cid, brief):
        if not self.campaign(cid):
            raise ValueError("Choose an existing campaign.")
        self.conn.execute(
            "INSERT INTO campaign_briefs VALUES (?,?) ON CONFLICT(campaign_id) "
            "DO UPDATE SET preferences_json=excluded.preferences_json",
            (cid, brief.model_dump_json()),
        )

    def save_campaign(self, cid, name, project_id, purpose, tags, account_id, status="draft"):
        account_id = account_id or None
        account = self.account(account_id) if account_id else None
        if account_id and not account:
            raise ValueError("Choose an existing sending account, or connect it later.")
        if status == "active" and (not account or not account["verified_at"]):
            raise ValueError("Verify a sending account before making this campaign active.")
        with self.transaction():
            old = self.campaign(cid)
            if old:
                if old["sender_account_id"] != account_id and self.one(
                    "SELECT 1 FROM messages m JOIN contacts c ON c.id=m.contact_id "
                    "WHERE c.campaign_id=? LIMIT 1",
                    (cid,),
                ):
                    raise ValueError(
                        "A campaign with send history keeps its original account. Create "
                        "another campaign for a different sender."
                    )
                self.conn.execute("UPDATE campaigns SET name=? WHERE id=?", (name, cid))
                if old["sender_account_id"] != account_id:
                    self.invalidate_approvals(cid)
            else:
                self.store.add_campaign(Campaign(id=cid, name=name, created_at=datetime.now(UTC)))
            self.conn.execute(
                "INSERT INTO campaign_settings VALUES (?,?,?,?,?,?) ON CONFLICT(campaign_id) "
                "DO UPDATE SET project_id=excluded.project_id,purpose=excluded.purpose,"
                "tags=excluded.tags,status=excluded.status,"
                "sender_account_id=excluded.sender_account_id",
                (cid, project_id or None, purpose, tags, status, account_id or None),
            )

    def attachment_files(self, cid):
        from outreach.adapters.attachments import campaign_files

        return campaign_files(self.conn, cid)

    def add_attachments(self, cid, uploads):
        from outreach.adapters.attachments import add_files

        return add_files(self.conn, cid, uploads)

    def attachment(self, cid, file_id):
        from outreach.adapters.attachments import decode

        row = self.conn.execute(
            "SELECT * FROM campaign_attachments WHERE id=? AND campaign_id=?", (file_id, cid)
        ).fetchone()
        return decode(row) if row else None

    def remove_attachment(self, cid, file_id):
        return self.conn.execute(
            "UPDATE campaign_attachments SET active=0 WHERE id=? AND campaign_id=? AND active=1",
            (file_id, cid),
        ).rowcount

    def invalidate_approvals(self, cid):
        self.conn.execute(
            "UPDATE drafts SET status='review' WHERE status='approved' AND contact_id IN "
            "(SELECT id FROM contacts WHERE campaign_id=?)",
            (cid,),
        )

    def research_campaign(self, run_id):
        row = self.one("SELECT campaign_id FROM campaign_research_runs WHERE run_id=?", (run_id,))
        return self.campaign(row["campaign_id"]) if row else None

    def link_research(self, campaign_id, run_id):
        campaign = self.campaign(campaign_id)
        if not campaign or campaign["status"] in ("archived", "completed"):
            raise ValueError("Reopen this campaign before researching more contacts.")
        self.conn.execute(
            "INSERT INTO campaign_research_runs (run_id,campaign_id) VALUES (?,?)",
            (run_id, campaign_id),
        )

    def campaign_runs(self, campaign_id):
        return [
            self.run(row["id"])
            for row in self.rows(
                "SELECT r.id FROM research_runs r WHERE r.id IN "
                "(SELECT run_id FROM campaign_research_runs WHERE campaign_id=? "
                "UNION SELECT l.run_id FROM research_leads l "
                "JOIN contact_origins o ON o.lead_id=l.id "
                "JOIN contacts c ON c.id=o.contact_id WHERE c.campaign_id=?) "
                "ORDER BY r.created_at DESC, r.id DESC",
                (campaign_id, campaign_id),
            )
        ]

    def runs(self, *, include_archived=False, include_deleted=False):
        return [
            self.run(r["id"])
            for r in self.rows(
                "SELECT id FROM research_runs "
                + (
                    "WHERE 1=1 "
                    if include_deleted
                    else "WHERE id NOT IN (SELECT run_id FROM research_trash) "
                )
                + (
                    ""
                    if include_archived
                    else "AND id NOT IN (SELECT run_id FROM research_archives) "
                )
                + "ORDER BY created_at DESC"
            )
        ]

    def run(self, key):
        row = self.one("SELECT * FROM research_runs WHERE id=?", (key,))
        if row:
            row["execution"] = self.execution(key)
            row["deleted"] = bool(
                self.one("SELECT run_id FROM research_trash WHERE run_id=?", (key,))
            )
            row["archived"] = bool(
                self.one("SELECT run_id FROM research_archives WHERE run_id=?", (key,))
            )
            row["plan"] = json.loads(row["plan_json"]) if row["plan_json"] else None
            intake = self.one(
                "SELECT preferences_json FROM research_intakes WHERE run_id=?", (key,)
            )
            row["intake"] = json.loads(intake["preferences_json"]) if intake else None
            row["spent_micro"] = self.conn.execute(
                "SELECT COALESCE(SUM(charged_micro),0) FROM research_calls WHERE run_id=?", (key,)
            ).fetchone()[0]
            row["spent"] = row["spent_micro"] / 1_000_000
            row["budget"] = row["budget_micro"] / 1_000_000
        return row

    def new_run(
        self,
        *,
        title,
        brief,
        purpose,
        tags,
        project_id,
        target,
        budget,
        engine_version=1,
        strategy_version=2,
    ):
        key = ident()
        self.conn.execute(
            (
                "INSERT INTO research_runs "
                "(id,title,brief,purpose,tags,project_id,target_count,budget_micro"
                ",created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)"
            ),
            (key, title, brief, purpose, tags, project_id or None, target, budget, now(), now()),
        )
        if engine_version == 2:
            self.conn.execute("INSERT INTO research_execution VALUES (?,2,'{}')", (key,))
        if engine_version == 2:
            self.save_execution(key, strategy_version=strategy_version)
        self.message(key, "user", brief)
        return key

    def audience_groups(self):
        """Group only explicit revisions; never merge unrelated goals or reset ledgers."""
        runs = self.runs(include_archived=True, include_deleted=True)
        by_id = {r["id"]: r for r in runs}
        parents = {r["id"]: r["execution"].get("parent_run") for r in runs}
        # Older revisions already recorded their parent in this fixed application message.
        for row in self.rows(
            "SELECT run_id,body FROM research_messages WHERE role='assistant' "
            "AND body LIKE 'Revised from /research/%'"
        ):
            candidate = row["body"].split("/research/", 1)[1].split(".", 1)[0]
            if candidate in by_id and not parents.get(row["run_id"]):
                parents[row["run_id"]] = candidate
        groups = {}
        for run in runs:
            key, seen = run["id"], set()
            while parents.get(key) in by_id and key not in seen:
                seen.add(key)
                key = parents[key]
            groups.setdefault(key, []).append(run)
        return groups

    def audience_history(self, key):
        return next(
            (runs for runs in self.audience_groups().values() if any(r["id"] == key for r in runs)),
            [],
        )

    def audiences(self, *, include_archived=False, include_deleted=False):
        cards = []
        for root, history in self.audience_groups().items():
            visible = [
                r
                for r in history
                if (include_deleted or not r["deleted"]) and (include_archived or not r["archived"])
            ]
            if visible:
                # New draft revisions win over older runs whose worker just finished.
                latest = max(visible, key=lambda r: (r["created_at"], r["id"]))
                cards.append(
                    {
                        **latest,
                        "audience_id": root,
                        "history": history,
                        "run_count": len(history),
                        "total_spent": sum(r["spent"] for r in history),
                    }
                )
        return sorted(cards, key=lambda r: r["updated_at"], reverse=True)

    def audience_leads(self, key):
        return [
            lead
            for run in self.audience_history(key)
            if not run["archived"] and not run["deleted"]
            for lead in self.leads(run["id"])
        ]

    def execution(self, key):
        row = self.one("SELECT * FROM research_execution WHERE run_id=?", (key,))
        return (
            {"version": row["version"], **json.loads(row["state_json"])} if row else {"version": 1}
        )

    def save_execution(self, key, **values):
        state = self.execution(key)
        state.update(values)
        version = state.pop("version")
        self.conn.execute(
            "INSERT INTO research_execution VALUES (?,?,?) ON CONFLICT(run_id) "
            "DO UPDATE SET state_json=excluded.state_json",
            (key, version, json.dumps(state)),
        )

    def suggestions(self, key):
        rows = self.rows("SELECT * FROM research_suggestions WHERE run_id=? ORDER BY id", (key,))
        for row in rows:
            row["evidence"] = json.loads(row["evidence_json"])
        return rows

    def add_suggestion(self, key, candidate):
        identity = " ".join(candidate["company"].casefold().split())
        self.conn.execute(
            "INSERT OR IGNORE INTO research_suggestions "
            "(run_id,identity,company,evidence_json) VALUES (?,?,?,?)",
            (key, identity, candidate["company"], json.dumps(candidate)),
        )

    def finish_suggestion(self, key, *, status, reason="", lead_id=None):
        self.conn.execute(
            "UPDATE research_suggestions SET status=?,reason=?,lead_id=? WHERE id=?",
            (status, reason, lead_id, key),
        )

    def save_intake(self, key, intake, *, title, purpose, target, budget):
        run = self.run(key)
        if (
            not run
            or run["archived"]
            or run["deleted"]
            or run["status"] != "draft"
            or run["plan"]
            or run["approved_at"]
            or run["spent_micro"]
        ):
            raise ValueError(
                "This research has already started. Keep it and create a new brief "
                "to change the audience."
            )
        self.conn.execute(
            "INSERT INTO research_intakes VALUES (?,?) ON CONFLICT(run_id) "
            "DO UPDATE SET preferences_json=excluded.preferences_json",
            (key, intake.model_dump_json()),
        )
        self.conn.execute(
            "UPDATE research_runs SET title=?,purpose=?,target_count=?,budget_micro=?,brief=?,"
            "updated_at=?,progress=? WHERE id=?",
            (
                title,
                purpose,
                target,
                budget,
                intake.research_brief(),
                now(),
                "Audience draft saved. No paid planning or research has started.",
                key,
            ),
        )

    def message(self, key, role, body):
        self.conn.execute(
            "INSERT INTO research_messages (run_id,role,body,created_at) VALUES (?,?,?,?)",
            (key, role, body, now()),
        )

    def messages(self, key):
        return self.rows("SELECT * FROM research_messages WHERE run_id=? ORDER BY id", (key,))

    def set_run(self, key, **values):
        allowed = {
            "status",
            "plan_json",
            "plan_version",
            "progress",
            "error",
            "approved_at",
            "worker_pid",
            "budget_micro",
            "target_count",
            "brief",
        }
        if not values.keys() <= allowed:
            raise ValueError("Unexpected research field.")
        values["updated_at"] = now()
        self.conn.execute(
            "UPDATE research_runs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
            (*values.values(), key),
        )

    def call(self, run_id, key):
        return self.one("SELECT * FROM research_calls WHERE run_id=? AND call_key=?", (run_id, key))

    def reserve(self, run_id, key, fingerprint, amount, daily_cap):
        with self.transaction():
            existing = self.call(run_id, key)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ResearchStop("Saved request inputs changed; keep this run for review.")
                if existing["status"] != "complete":
                    raise ResearchStop(
                        "A prior request has an uncertain outcome. Its budget is retained; "
                        "do not replay it."
                    )
                return json.loads(existing["response_json"])
            if self.one("SELECT 1 FROM research_calls WHERE charged_micro>reserved_micro LIMIT 1"):
                raise ResearchStop(
                    "Provider overcharge requires reconciliation before new paid requests."
                )
            run = self.run(run_id)
            if run["status"] not in ("planning", "running"):
                raise ResearchStop("Research paused before the next request.")
            # Runs copied in as a showcase were paid for elsewhere, on their own day.
            showcase = self.one(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workbench_showcase'"
            )
            spent_today = self.conn.execute(
                (
                    "SELECT COALESCE(SUM(charged_micro),0) FROM research_calls WHERE "
                    "substr(created_at,1,10)=?"
                    + (" AND run_id NOT IN (SELECT run_id FROM workbench_showcase)" if showcase else "")
                ),
                (now()[:10],),
            ).fetchone()[0]
            if (
                amount <= 0
                or run["spent_micro"] + amount > run["budget_micro"]
                or spent_today + amount > daily_cap
            ):
                raise ResearchBudgetStop(
                    "Spending limit reached before the next request. Saved results are "
                    "available for review."
                )
            self.conn.execute(
                (
                    "INSERT INTO research_calls "
                    "(run_id,call_key,fingerprint,status,reserved_micro,charged_micro,"
                    "created_at) VALUES (?,?,?,'reserved',?,?,?)"
                ),
                (run_id, key, fingerprint, amount, amount, now()),
            )
        return None

    def finish_call(self, run_id, key, response, charge, kind):
        entry = self.call(run_id, key)
        self.conn.execute(
            (
                "UPDATE research_calls SET "
                "status='complete',response_json=?,charged_micro=?,cost_kind=? "
                "WHERE run_id=? AND call_key=?"
            ),
            (json.dumps(response), charge, kind, run_id, key),
        )
        if charge > entry["reserved_micro"]:
            self.set_run(
                run_id, status="failed", error="Provider overcharge requires reconciliation."
            )
            raise ResearchStop(
                "Provider cost exceeded its reservation. Stop and reconcile this "
                "run before continuing."
            )

    def add_candidate(self, run_id, candidate):
        identity = (
            host(candidate["website"]) + "/" + " ".join(candidate["company"].casefold().split())
        )
        self.conn.execute(
            (
                "INSERT OR IGNORE INTO lead_entities "
                "(company,domain,identity_key,created_at) VALUES (?,?,?,?)"
            ),
            (candidate["company"], host(candidate["website"]), identity, now()),
        )
        entity = self.one("SELECT id FROM lead_entities WHERE identity_key=?", (identity,))["id"]
        self.conn.execute(
            (
                "INSERT OR IGNORE INTO research_leads "
                "(run_id,entity_id,company,website,discovery_json) VALUES "
                "(?,?,?,?,?)"
            ),
            (run_id, entity, candidate["company"], candidate["website"], json.dumps(candidate)),
        )
        return self.one(
            "SELECT id FROM research_leads WHERE run_id=? AND entity_id=?", (run_id, entity)
        )["id"]

    def decode_lead(self, row):
        for name in ("facts", "sources", "emails", "flags", "discovery"):
            row[name] = json.loads(row[name + "_json"])
        from outreach.core.campaign_selection import contact_summary

        row["contact"] = contact_summary(row)
        selected = row["contact"]["email"]
        email = selected["value"] if selected else ""
        row["suppressed"] = bool(email and self.store.is_suppressed(email))
        row["suppressed_emails"] = [
            e["value"] for e in row["emails"] if self.store.is_suppressed(e["value"])
        ]
        row["prior_campaigns"] = self.rows(
            "SELECT DISTINCT c.campaign_id,p.name FROM contacts c "
            "JOIN campaigns p ON p.id=c.campaign_id "
            "LEFT JOIN contact_origins o ON o.contact_id=c.id "
            "LEFT JOIN research_leads other ON other.id=o.lead_id "
            "WHERE c.email=? OR other.entity_id=?",
            (email, row["entity_id"]),
        )
        return row

    def lead(self, key):
        row = self.one("SELECT * FROM research_leads WHERE id=?", (key,))
        return self.decode_lead(row) if row else None

    def leads(self, run_id=None, list_id=None):
        sql = "SELECT r.* FROM research_leads r"
        args = ()
        if list_id:
            sql += " JOIN lead_list_members m ON m.lead_id=r.id WHERE m.list_id=?"
            args = (list_id,)
        elif run_id:
            sql += " WHERE r.run_id=?"
            args = (run_id,)
        return [self.decode_lead(r) for r in self.rows(sql + " ORDER BY r.id", args)]

    def save_evidence(self, key, *, facts, sources, emails, flags, summary, complete=True):
        self.conn.execute(
            (
                "UPDATE research_leads SET "
                "facts_json=?,sources_json=?,emails_json=?,flags_json=?,fit_summar"
                "y=?,processing_status=? WHERE id=?"
            ),
            (
                json.dumps(facts),
                json.dumps(sources),
                json.dumps(emails),
                json.dumps(flags),
                summary,
                "complete" if complete else "pending",
                key,
            ),
        )

    def review_leads(self, ids, *, action, confirmed=False, note="", email=None):
        if action not in ("approve", "reject", "pending"):
            raise ValueError("Choose approve, reject or pending.")
        with self.transaction():
            for key in ids:
                lead = self.lead(key)
                if lead is None:
                    raise ValueError("Lead not found.")
                chosen = (
                    email
                    if email and len(ids) == 1
                    else (
                        lead["selected_email"]
                        or (lead["emails"][0]["value"] if lead["emails"] else "")
                    )
                )
                if action == "approve":
                    if not confirmed:
                        raise ValueError(
                            "Confirm company identity, contact ownership and fit for the "
                            "selected leads."
                        )
                    if lead["processing_status"] != "complete" or chosen not in {
                        e["value"] for e in lead["emails"]
                    }:
                        raise ValueError(
                            "Only a completed lead with a published email can be approved."
                        )
                    if self.store.is_suppressed(chosen):
                        raise ValueError("An address is on the global do-not-contact list.")
                    if any(f["status"] != "supported" for f in lead["facts"]) and not note.strip():
                        raise ValueError(
                            "Add your review note when the research could not establish every "
                            "criterion."
                        )
                if action != "approve":
                    self.conn.execute(
                        (
                            "UPDATE drafts SET status='review' WHERE status='approved' AND "
                            "contact_id IN (SELECT contact_id FROM contact_origins WHERE "
                            "lead_id=?)"
                        ),
                        (key,),
                    )
                self.conn.execute(
                    (
                        "UPDATE research_leads SET "
                        "review_status=?,selected_email=?,review_note=?,reviewed_at=? "
                        "WHERE id=?"
                    ),
                    (
                        "approved"
                        if action == "approve"
                        else "rejected"
                        if action == "reject"
                        else "pending",
                        chosen or None,
                        note,
                        now(),
                        key,
                    ),
                )

    def lists(self):
        return self.rows(
            "SELECT l.*,COUNT(m.lead_id) AS lead_count FROM lead_lists l LEFT "
            "JOIN lead_list_members m ON m.list_id=l.id GROUP BY l.id ORDER BY "
            "l.created_at DESC"
        )

    def accept_campaign_selection(self, ids):
        """Called inside enrollment/list transaction; no separate review ceremony."""
        from outreach.core.campaign_selection import campaign_email

        for key in ids:
            lead = self.lead(key)
            email = campaign_email(lead)
            if not email or self.store.is_suppressed(email["value"]):
                raise ValueError("Select completed contacts with published, unsuppressed emails.")
            if lead["review_status"] == "approved":
                continue
            self.conn.execute(
                "UPDATE research_leads SET review_status='approved',selected_email=?,"
                "review_note=?,reviewed_at=? WHERE id=?",
                (
                    email["value"],
                    "Selected by user for campaign. Publication is not delivery verification; "
                    "unknown audience criteria remain unknown; "
                    "contradicted criteria remain audience fit mismatches.",
                    now(),
                    key,
                ),
            )

    def add_list(self, name, project_id, ids, tags="", *, accept_selected=False):
        key = ident()
        with self.transaction():
            if accept_selected:
                self.accept_campaign_selection(ids)
            self.conn.execute(
                "INSERT INTO lead_lists VALUES (?,?,?,?,?)",
                (key, project_id or None, name, tags, now()),
            )
            for lead_id in ids:
                lead = self.lead(lead_id)
                if (
                    not lead
                    or lead["review_status"] != "approved"
                    or not lead["selected_email"]
                    or not lead["contact"]["email"]
                    or lead["processing_status"] != "complete"
                    or lead["suppressed"]
                ):
                    raise ValueError(
                        "Only reviewed and approved leads can be saved to an outreach list."
                    )
                self.conn.execute(
                    "INSERT OR IGNORE INTO lead_list_members VALUES (?,?)", (key, lead_id)
                )
        return key

    def enroll(self, cid, ids, *, acknowledge_prior=False, accept_selected=False):
        added, skipped = 0, 0
        with self.transaction():
            campaign = self.campaign(cid)
            if not campaign or campaign["status"] in ("archived", "completed"):
                raise ValueError("Choose an open campaign, or reopen it before adding leads.")
            if accept_selected:
                self.accept_campaign_selection(ids)
            for key in ids:
                lead = self.lead(key)
                if not lead or lead["review_status"] != "approved" or not lead["selected_email"]:
                    raise ValueError("Approve every selected lead before adding it to a campaign.")
                if not lead["contact"]["email"] or lead["processing_status"] != "complete":
                    raise ValueError(
                        "Choose a published contact again before adding it to a campaign."
                    )
                email = lead["contact"]["email"]["value"]
                if self.store.is_suppressed(email):
                    raise ValueError("A selected contact is suppressed globally.")
                if email in self.store.emails_in_campaign(cid):
                    skipped += 1
                    continue
                if lead["prior_campaigns"] and not acknowledge_prior:
                    raise ValueError(
                        "Some addresses belong to other campaigns. Review their history "
                        "and acknowledge prior outreach."
                    )
                evidence = enrollment_evidence(lead)
                # Run IDs and operator review notes stay in contact_origins/research records,
                # not in the facts a draft is allowed to claim about a recipient.
                contact_id = self.store.add_contact(
                    Contact(
                        campaign_id=cid, email=email, company=lead["company"], evidence=evidence
                    )
                )
                self.conn.execute("INSERT INTO contact_origins VALUES (?,?)", (contact_id, key))
                added += 1
        return added, skipped
