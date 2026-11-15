"""Additive Workbench snapshots/events, sharing the existing research accounting parent."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from outreach.adapters.platform_store import PlatformStore, now
from outreach.core.workbench import DEMO_CAMPAIGN, NO_GOAL, Prospect
from outreach.core.research import ResearchStop

# Sized from provider list prices (Nov 2026): a "fast" search request $0.001 (returns ten
# results with excerpts), a page read $0.001, a research-model step about $0.001 with
# DeepSeek V4.1 Flash. Free search excerpts count as weaker evidence, so few pages are
# opened. Worst case here is about $0.02; typical runs about $0.01.
DEFAULT_LIMITS = {
    "max_search_queries": 12,
    "max_pages": 6,
    "max_followups": 2,  # one for identity, one for the hook
    "max_search_requests": 5,
    # identity, signal, two follow-ups, draft, one repair, and a second model if the
    # first returns an unusable answer
    "max_model_requests": 8,
    "wall_seconds": 180,
    "recent_days": 180,
    "budget_micro": 50000,
    "write_draft": 1,  # 0 = research only: no email, so no drafting model cost
    # 1 = thorough: cover four angles and keep going until 3 facts from 2 angles;
    # 0 = quick: one news search and two pages.
    "thorough": 1,
}

MAX_BATCH = 20

WORKBENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS workbench_campaign_versions (
 campaign_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(campaign_id,version)
);
CREATE TABLE IF NOT EXISTS workbench_runs (
 run_id TEXT PRIMARY KEY REFERENCES research_runs(id),
 request_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL,
 prospect_json TEXT NOT NULL, campaign_id TEXT NOT NULL, campaign_version INTEGER NOT NULL,
 campaign_json TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('fixture','live')),
 execution_status TEXT NOT NULL CHECK(execution_status IN
 ('queued','running','completed','failed','interrupted')),
 business_outcome TEXT, result_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(campaign_id,campaign_version) REFERENCES workbench_campaign_versions(campaign_id,version)
);
CREATE TABLE IF NOT EXISTS workbench_stage_events (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workbench_runs(run_id),
 name TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('started','completed','failed')),
 detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workbench_stage_run ON workbench_stage_events(run_id,id);
CREATE TABLE IF NOT EXISTS workbench_research_options (
 run_id TEXT PRIMARY KEY REFERENCES workbench_runs(run_id), limits_json TEXT NOT NULL,
 deadline_at TEXT
);
CREATE TABLE IF NOT EXISTS workbench_research_state (
 run_id TEXT PRIMARY KEY REFERENCES workbench_runs(run_id), checkpoint_json TEXT NOT NULL DEFAULT '{}',
 confirmation_json TEXT NOT NULL DEFAULT '{}', evidence_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_operations (
 run_id TEXT NOT NULL REFERENCES workbench_runs(run_id), call_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('search','extract','model','followup')),
 units INTEGER NOT NULL CHECK(units>0), fingerprint TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('reserved','complete')), created_at TEXT NOT NULL,
 PRIMARY KEY(run_id,call_key)
);
CREATE TABLE IF NOT EXISTS workbench_sources (
 run_id TEXT NOT NULL REFERENCES workbench_runs(run_id), source_id TEXT NOT NULL,
 source_json TEXT NOT NULL, PRIMARY KEY(run_id,source_id)
);
CREATE TABLE IF NOT EXISTS workbench_drafts (
 run_id TEXT NOT NULL REFERENCES workbench_runs(run_id), revision INTEGER NOT NULL CHECK(revision>0),
 origin TEXT NOT NULL CHECK(origin IN ('model','repair','fixture','reviewer','template')),
 subject TEXT NOT NULL, body TEXT NOT NULL, claims_json TEXT NOT NULL, check_json TEXT NOT NULL,
 supported INTEGER NOT NULL CHECK(supported IN (0,1)), content_hash TEXT NOT NULL,
 basis_json TEXT NOT NULL, basis_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(run_id,revision)
);
CREATE TABLE IF NOT EXISTS workbench_review_events (
 id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('approve','reject')), content_hash TEXT NOT NULL,
 basis_hash TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 FOREIGN KEY(run_id,revision) REFERENCES workbench_drafts(run_id,revision)
);
CREATE TABLE IF NOT EXISTS workbench_current_goal (
 mode TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, version INTEGER NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(campaign_id,version) REFERENCES workbench_campaign_versions(campaign_id,version)
);
CREATE TABLE IF NOT EXISTS workbench_batches (
 batch_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, mode TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbench_batch_runs (
 batch_id TEXT NOT NULL REFERENCES workbench_batches(batch_id), position INTEGER NOT NULL,
 run_id TEXT NOT NULL REFERENCES workbench_runs(run_id), PRIMARY KEY(batch_id,position)
);
CREATE INDEX IF NOT EXISTS idx_workbench_batch_run ON workbench_batch_runs(run_id);
CREATE TRIGGER IF NOT EXISTS workbench_draft_revision_immutable
BEFORE UPDATE ON workbench_drafts BEGIN
 SELECT RAISE(ABORT,'Workbench draft revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS workbench_review_event_immutable
BEFORE UPDATE ON workbench_review_events BEGIN
 SELECT RAISE(ABORT,'Workbench review events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS workbench_campaign_version_immutable
BEFORE UPDATE ON workbench_campaign_versions BEGIN
 SELECT RAISE(ABORT,'Workbench campaign versions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS workbench_run_snapshot_immutable
BEFORE UPDATE OF request_id,request_fingerprint,prospect_json,campaign_id,
 campaign_version,campaign_json,mode ON workbench_runs BEGIN
 SELECT RAISE(ABORT,'Workbench run snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS workbench_research_limits_immutable
BEFORE UPDATE OF limits_json ON workbench_research_options BEGIN
 SELECT RAISE(ABORT,'Workbench research limits are immutable');
END;
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class WorkbenchStore(PlatformStore):
    def __init__(self, store, *, clock=None):
        super().__init__(store)
        self.clock = clock or now
        self.conn.executescript(WORKBENCH_SCHEMA)
        self._migrate_live_mode()
        self._migrate_draft_origins()
        self.conn.execute(
            "INSERT OR IGNORE INTO workbench_campaign_versions VALUES (?,?,?,?)",
            (DEMO_CAMPAIGN["id"], DEMO_CAMPAIGN["version"], canonical(DEMO_CAMPAIGN), now()),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO workbench_campaign_versions VALUES (?,?,?,?)",
            (NO_GOAL["id"], NO_GOAL["version"], canonical(NO_GOAL), now()),
        )

    def _time(self):
        value = self.clock()
        value = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if value.tzinfo is None:
            raise ValueError("The Workbench clock must include a UTC offset.")
        return value.astimezone(UTC)

    def _migrate_live_mode(self):
        """Rebuild the Phase 1 CHECK constraint atomically without losing child rows."""
        schema = self.one("SELECT sql FROM sqlite_master WHERE type='table' AND name='workbench_runs'")[
            "sql"
        ]
        if "'live'" in schema:
            return
        foreign_keys = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.transaction():
                schema = self.one(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='workbench_runs'"
                )["sql"]
                if "'live'" in schema:
                    return
                replacement = schema.replace(
                    "CREATE TABLE workbench_runs", "CREATE TABLE workbench_runs_upgrade", 1
                )
                replacement = replacement.replace(
                    "CHECK(mode='fixture')", "CHECK(mode IN ('fixture','live'))"
                )
                if replacement == schema or "'live'" not in replacement:
                    raise ValueError("Unrecognized Workbench schema; original records were retained.")
                self.conn.execute(replacement)
                self.conn.execute("INSERT INTO workbench_runs_upgrade SELECT * FROM workbench_runs")
                self.conn.execute("DROP TABLE workbench_runs")
                self.conn.execute("ALTER TABLE workbench_runs_upgrade RENAME TO workbench_runs")
                trigger = WORKBENCH_SCHEMA.split(
                    "CREATE TRIGGER IF NOT EXISTS workbench_run_snapshot_immutable", 1
                )[1].split("END;", 1)[0]
                self.conn.execute(
                    "CREATE TRIGGER IF NOT EXISTS workbench_run_snapshot_immutable" + trigger + "END;"
                )
                if self.conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError(
                        "Workbench migration failed its foreign-key check; records retained."
                    )
        finally:
            self.conn.execute(f"PRAGMA foreign_keys={int(foreign_keys)}")

    def _migrate_draft_origins(self):
        """Allow template-written drafts in databases created before that origin existed."""
        schema = self.one("SELECT sql FROM sqlite_master WHERE type='table' AND name='workbench_drafts'")[
            "sql"
        ]
        if "'template'" in schema:
            return
        old = "CHECK(origin IN ('model','repair','fixture','reviewer'))"
        new = "CHECK(origin IN ('model','repair','fixture','reviewer','template'))"
        if old not in schema:
            raise ValueError("Unrecognized Workbench draft schema; original records were retained.")
        foreign_keys = self.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.transaction():
                self.conn.execute(
                    schema.replace(
                        "CREATE TABLE workbench_drafts", "CREATE TABLE workbench_drafts_upgrade", 1
                    ).replace(old, new)
                )
                self.conn.execute("INSERT INTO workbench_drafts_upgrade SELECT * FROM workbench_drafts")
                self.conn.execute("DROP TABLE workbench_drafts")
                self.conn.execute("ALTER TABLE workbench_drafts_upgrade RENAME TO workbench_drafts")
                self.conn.execute(
                    "CREATE TRIGGER IF NOT EXISTS workbench_draft_revision_immutable "
                    "BEFORE UPDATE ON workbench_drafts BEGIN "
                    "SELECT RAISE(ABORT,'Workbench draft revisions are immutable'); END;"
                )
                if self.conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError("Workbench draft migration failed its foreign-key check.")
        finally:
            self.conn.execute(f"PRAGMA foreign_keys={int(foreign_keys)}")

    def _limits(self, limits):
        limits = {} if limits is None else limits
        if not isinstance(limits, dict) or not limits.keys() <= DEFAULT_LIMITS.keys():
            raise ValueError("Choose supported Workbench research limits.")
        result = DEFAULT_LIMITS | limits
        for name, value in result.items():
            maximum = 3650 if name == "recent_days" else DEFAULT_LIMITS[name]
            minimum = 0 if name in ("max_followups", "write_draft", "thorough") else 1
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"Invalid Workbench limit: {name}.")
        return result

    def get_campaign_brief(self):
        row = self.one(
            "SELECT snapshot_json FROM workbench_campaign_versions WHERE campaign_id=? AND version=?",
            (DEMO_CAMPAIGN["id"], DEMO_CAMPAIGN["version"]),
        )
        return json.loads(row["snapshot_json"])

    def save_campaign(self, campaign):
        """Store a goal snapshot once; the same content always maps to the same ID."""
        if not campaign.get("id") or type(campaign.get("version")) is not int:
            raise ValueError("A goal snapshot needs an ID and a version.")
        with self.transaction():
            self.conn.execute(
                "INSERT OR IGNORE INTO workbench_campaign_versions VALUES (?,?,?,?)",
                (campaign["id"], campaign["version"], canonical(campaign), now()),
            )
            saved = self.one(
                "SELECT snapshot_json FROM workbench_campaign_versions WHERE campaign_id=? AND version=?",
                (campaign["id"], campaign["version"]),
            )
        if saved["snapshot_json"] != canonical(campaign):
            raise ValueError("A different goal is already saved under this ID.")
        return json.loads(saved["snapshot_json"])

    def set_current_goal(self, mode, campaign):
        """The goal every new run in this mode uses until it is changed."""
        campaign = self.save_campaign(campaign)
        with self.transaction():
            self.conn.execute(
                "INSERT INTO workbench_current_goal VALUES (?,?,?,?) ON CONFLICT(mode) DO UPDATE SET "
                "campaign_id=excluded.campaign_id,version=excluded.version,"
                "updated_at=excluded.updated_at",
                (mode, campaign["id"], campaign["version"], now()),
            )
        return campaign

    def latest_campaign(self, mode):
        """The goal chosen on the Goal page, else the last run's goal, else the demo goal."""
        current = self.one(
            "SELECT v.snapshot_json FROM workbench_current_goal g JOIN workbench_campaign_versions v "
            "ON v.campaign_id=g.campaign_id AND v.version=g.version WHERE g.mode=?",
            (mode,),
        )
        if current:
            return json.loads(current["snapshot_json"])
        row = self.one(
            "SELECT campaign_json FROM workbench_runs WHERE mode=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (mode,),
        )
        return json.loads(row["campaign_json"]) if row else self.get_campaign_brief()

    def submit(self, prospect, request_id, campaign, *, mode="fixture", limits=None):
        prospect = Prospect.model_validate(prospect).model_dump()
        if mode not in ("fixture", "live"):
            raise ValueError("Choose fixture or live research.")
        limits = self._limits(limits)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 120:
            raise ValueError("Use the request identifier from the research form.")
        saved = self.one(
            "SELECT snapshot_json FROM workbench_campaign_versions WHERE campaign_id=? AND version=?",
            (campaign.get("id"), campaign.get("version")),
        )
        if not saved or saved["snapshot_json"] != canonical(campaign):
            raise ValueError("The campaign brief changed. Reload the form before starting.")
        fingerprint = hashlib.sha256(
            canonical([prospect, campaign, mode, limits]).encode()
        ).hexdigest()
        with self.transaction():
            existing = self.one("SELECT * FROM workbench_runs WHERE request_id=?", (request_id,))
            if existing:
                legacy = hashlib.sha256(canonical([prospect, campaign]).encode()).hexdigest()
                compatible_legacy = (
                    mode == existing["mode"] == "fixture"
                    and limits == DEFAULT_LIMITS
                    and existing["request_fingerprint"] == legacy
                )
                if existing["request_fingerprint"] != fingerprint and not compatible_legacy:
                    raise ValueError("This submission was already used with different inputs.")
                return existing["run_id"], False
            key = self.new_run(
                title=f"{prospect['name']} at {prospect['company']}",
                brief=campaign["offer"],
                purpose="workbench",
                tags=mode,
                project_id=None,
                target=1,
                budget=0 if mode == "fixture" else limits["budget_micro"],
                engine_version=2,
                strategy_version=1,
            )
            stamp = now()
            self.conn.execute(
                "INSERT INTO workbench_runs "
                "(run_id,request_id,request_fingerprint,prospect_json,campaign_id,campaign_version,"
                "campaign_json,mode,execution_status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,'queued',?,?)",
                (
                    key,
                    request_id,
                    fingerprint,
                    canonical(prospect),
                    campaign["id"],
                    campaign["version"],
                    canonical(campaign),
                    mode,
                    stamp,
                    stamp,
                ),
            )
            self.conn.execute(
                "INSERT INTO workbench_research_options VALUES (?,?,NULL)", (key, canonical(limits))
            )
            self.conn.execute(
                "INSERT INTO workbench_research_state(run_id,evidence_version) VALUES (?,?)",
                (key, hashlib.sha256(b"{}").hexdigest()),
            )
            self.set_run(key, status="queued", progress=f"{mode.capitalize()} research is queued.")
            self._stage(key, "Save inputs", "completed", "Prospect and campaign snapshot saved.")
        return key, True

    def get_workbench_run(self, key):
        row = self.one("SELECT * FROM workbench_runs WHERE run_id=?", (key,))
        if not row:
            return None
        options = self.one("SELECT * FROM workbench_research_options WHERE run_id=?", (key,))
        state = self.one("SELECT * FROM workbench_research_state WHERE run_id=?", (key,)) or {}
        return {
            "id": row["run_id"],
            "prospect": json.loads(row["prospect_json"]),
            "campaign": json.loads(row["campaign_json"]),
            "mode": row["mode"],
            "execution_status": row["execution_status"],
            "business_outcome": row["business_outcome"],
            "result": json.loads(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "limits": json.loads(options["limits_json"]) if options else dict(DEFAULT_LIMITS),
            "deadline_at": options["deadline_at"] if options else None,
            "usage": self.usage(key),
            "source_records": self.workbench_sources(key),
            "checkpoint": json.loads(state.get("checkpoint_json", "{}")),
            "confirmation": json.loads(state.get("confirmation_json", "{}")),
            "evidence_version": state.get("evidence_version", hashlib.sha256(b"{}").hexdigest()),
            "stages": self.rows(
                "SELECT name,status,detail,created_at FROM workbench_stage_events "
                "WHERE run_id=? ORDER BY id",
                (key,),
            ),
        } | self._review(key, row, state)

    def list_workbench_runs(self):
        keys = self.rows("SELECT run_id FROM workbench_runs ORDER BY created_at DESC,run_id DESC")
        return [self.get_workbench_run(row["run_id"]) for row in keys]

    def showcase_ids(self):
        """Runs copied in from the evaluation, so History can label them as such."""
        if not self.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workbench_showcase'"):
            return set()
        return {row["run_id"] for row in self.rows("SELECT run_id FROM workbench_showcase")}

    def usage(self, key):
        # A model the provider refused outright did no work, so it uses no model quota.
        operations = self.rows(
            "SELECT o.kind,o.units,o.status FROM workbench_operations o LEFT JOIN research_calls c "
            "ON c.run_id=o.run_id AND c.call_key=o.call_key WHERE o.run_id=? AND "
            "COALESCE(c.cost_kind,'')!='rejected'",
            (key,),
        )
        counts = {
            "search_queries": 0,
            "search_requests": 0,
            "pages": 0,
            "extract_requests": 0,
            "model_requests": 0,
            "followups": 0,
        }
        for operation in operations:
            kind, units = operation["kind"], operation["units"]
            if kind == "search":
                counts["search_queries"] += units
                counts["search_requests"] += 1
            elif kind == "extract":
                counts["pages"] += units
                counts["extract_requests"] += 1
            else:
                counts["model_requests" if kind == "model" else "followups"] += units
        calls = self.rows(
            "SELECT status,reserved_micro,charged_micro FROM research_calls WHERE run_id=?", (key,)
        )
        counts["held_requests"] = sum(call["status"] != "complete" for call in calls)
        counts["held_operations"] = sum(
            operation["status"] != "complete" for operation in operations
        )
        counts["spent_micro"] = sum(call["charged_micro"] for call in calls)
        # What finished requests actually cost, without amounts still only reserved.
        counts["settled_micro"] = sum(
            call["charged_micro"] for call in calls if call["status"] == "complete"
        )
        return counts

    def reserve_workbench_operation(self, key, call_key, kind, units, fingerprint):
        """Reserve quotas before provider dispatch, separately from the dollar ledger."""
        if kind not in {"search", "extract", "model", "followup"}:
            raise ValueError("Unknown Workbench operation kind.")
        if type(units) is not int or units <= 0 or (kind in {"model", "followup"} and units != 1):
            raise ValueError("Choose positive bounded Workbench operation units.")
        if (
            not isinstance(call_key, str)
            or not call_key
            or not isinstance(fingerprint, str)
            or not fingerprint
        ):
            raise ValueError("Workbench operations require a key and input fingerprint.")
        with self.transaction():
            existing = self.one(
                "SELECT * FROM workbench_operations WHERE run_id=? AND call_key=?", (key, call_key)
            )
            if existing:
                if (existing["fingerprint"], existing["kind"], existing["units"]) != (
                    fingerprint,
                    kind,
                    units,
                ):
                    raise ResearchStop("Saved request inputs changed; keep this run for review.")
                call = self.call(key, call_key)
                if existing["status"] == "complete" or (call and call["status"] == "complete"):
                    self.conn.execute(
                        "UPDATE workbench_operations SET status='complete' WHERE run_id=? AND call_key=?",
                        (key, call_key),
                    )
                    return False
                raise ResearchStop(
                    "A previous request is held for review; it will not be replayed."
                )
            row = self.one("SELECT execution_status FROM workbench_runs WHERE run_id=?", (key,))
            options = self.one("SELECT * FROM workbench_research_options WHERE run_id=?", (key,))
            if (
                not row
                or row["execution_status"] != "running"
                or not options
                or not options["deadline_at"]
            ):
                raise ResearchStop("Research is not running; no new request was reserved.")
            if self._time() >= datetime.fromisoformat(options["deadline_at"]):
                raise ResearchStop("Research time limit reached. Saved evidence remains available.")
            if self.one(
                "SELECT 1 FROM research_calls WHERE run_id=? AND status!='complete' LIMIT 1",
                (key,),
            ):
                raise ResearchStop(
                    "A previous provider request is held. Review it before continuing."
                )
            limits = json.loads(options["limits_json"])
            counts = self.usage(key)
            needed = {
                "search": [
                    ("search_queries", "max_search_queries", units),
                    ("search_requests", "max_search_requests", 1),
                ],
                "extract": [("pages", "max_pages", units)],
                "model": [("model_requests", "max_model_requests", 1)],
                "followup": [("followups", "max_followups", 1)],
            }[kind]
            if any(
                counts[counter] + increment > limits[limit] for counter, limit, increment in needed
            ):
                raise ResearchStop(
                    "Research request limit reached. Saved evidence remains available."
                )
            self.conn.execute(
                "INSERT INTO workbench_operations VALUES (?,?,?,?,?,?,?)",
                (
                    key,
                    call_key,
                    kind,
                    units,
                    fingerprint,
                    "complete" if kind == "followup" else "reserved",
                    self._time().isoformat(),
                ),
            )
        return True

    def mark_workbench_operation_complete(self, key, call_key):
        with self.transaction():
            operation = self.one(
                "SELECT * FROM workbench_operations WHERE run_id=? AND call_key=?", (key, call_key)
            )
            if not operation:
                raise ValueError("Workbench operation was not reserved.")
            call = self.call(key, call_key)
            if operation["kind"] != "followup" and (not call or call["status"] != "complete"):
                raise ResearchStop(
                    "The provider request remains held; completion cannot be inferred."
                )
            self.conn.execute(
                "UPDATE workbench_operations SET status='complete' WHERE run_id=? AND call_key=?",
                (key, call_key),
            )

    def release_unsent_operation(self, key, call_key):
        """Free a reserved step whose request was never sent (the spending guard refused
        it first). Only possible when the ledger has no entry for it at all: a request
        that was sent, whatever its outcome, can never be released this way."""
        with self.transaction():
            if self.call(key, call_key):
                raise ResearchStop("This request was sent; it cannot be released as unsent.")
            self.conn.execute(
                "DELETE FROM workbench_operations WHERE run_id=? AND call_key=?", (key, call_key)
            )

    def workbench_sources(self, key):
        return [
            json.loads(row["source_json"])
            for row in self.rows(
                "SELECT source_json FROM workbench_sources WHERE run_id=? ORDER BY rowid", (key,)
            )
        ]

    def save_source(self, key, source):
        if not source.get("id") or not isinstance(source["id"], str):
            raise ValueError("A source needs a stable identifier.")
        with self.transaction():
            run = self.one("SELECT execution_status FROM workbench_runs WHERE run_id=?", (key,))
            if not run or run["execution_status"] != "running":
                raise ValueError("The research run is not active.")
            old = self.one(
                "SELECT source_json FROM workbench_sources WHERE run_id=? AND source_id=?",
                (key, source["id"]),
            )
            state = self.one(
                "SELECT confirmation_json FROM workbench_research_state WHERE run_id=?", (key,)
            )
            confirmation = json.loads(state["confirmation_json"]) if state else {}
            proof = confirmation.get("proof_sources", {})
            if old and source["id"] in proof and old["source_json"] != canonical(source):
                self.conn.execute(
                    "UPDATE workbench_research_state SET confirmation_json='{}' WHERE run_id=?", (key,)
                )
            self.conn.execute(
                "INSERT INTO workbench_sources VALUES (?,?,?) ON CONFLICT(run_id,source_id) "
                "DO UPDATE SET source_json=excluded.source_json",
                (key, source["id"], canonical(source)),
            )
            state = self.one("SELECT * FROM workbench_research_state WHERE run_id=?", (key,))
            checkpoint = json.loads(state["checkpoint_json"]) if state else {}
            checkpoint["sources"] = self.workbench_sources(key)
            encoded = canonical(checkpoint)
            self.conn.execute(
                "INSERT INTO workbench_research_state VALUES (?,?,?,?) ON CONFLICT(run_id) "
                "DO UPDATE SET checkpoint_json=excluded.checkpoint_json,"
                "evidence_version=excluded.evidence_version",
                (key, encoded, "{}", hashlib.sha256(encoded.encode()).hexdigest()),
            )

    def save_checkpoint(self, key, bundle):
        if not isinstance(bundle, dict):
            raise ValueError("A research checkpoint must be an object.")
        encoded = canonical(bundle)
        version = hashlib.sha256(encoded.encode()).hexdigest()
        with self.transaction():
            run = self.one("SELECT execution_status FROM workbench_runs WHERE run_id=?", (key,))
            if not run or run["execution_status"] != "running":
                raise ValueError("The research run is not active.")
            state = self.one("SELECT * FROM workbench_research_state WHERE run_id=?", (key,))
            confirmation = state["confirmation_json"] if state else "{}"
            if state:
                old = json.loads(state["checkpoint_json"])
                if old.get("identity_candidates") != bundle.get("identity_candidates"):
                    confirmation = "{}"
            self.conn.execute(
                "INSERT INTO workbench_research_state VALUES (?,?,?,?) ON CONFLICT(run_id) "
                "DO UPDATE SET checkpoint_json=excluded.checkpoint_json,"
                "confirmation_json=excluded.confirmation_json,evidence_version=excluded.evidence_version",
                (key, encoded, confirmation, version),
            )

    def confirm_workbench_identity(self, key, candidate_id, evidence_version):
        from outreach.core.workbench_evidence import assess_identity

        with self.transaction():
            run = self.get_workbench_run(key)
            if (
                not run
                or run["execution_status"] != "completed"
                or run["business_outcome"] != "needs_identity_confirmation"
            ):
                raise ValueError("This run is not waiting for identity confirmation.")
            if run["evidence_version"] != evidence_version:
                raise ValueError(
                    "The research evidence changed. Reload before confirming identity."
                )
            if self.one(
                "SELECT 1 FROM research_calls WHERE run_id=? AND status!='complete' LIMIT 1", (key,)
            ):
                raise ResearchStop(
                    "A previous provider request is held. Review it before continuing."
                )
            assessed = assess_identity(
                run["prospect"],
                run["source_records"],
                run["checkpoint"].get("identity_candidates", []),
            )
            candidate = next(
                (
                    item
                    for item in assessed.get("candidates", [])
                    if item.get("id") == candidate_id and item.get("selectable")
                ),
                None,
            )
            if not candidate:
                raise ValueError("Choose a supported current identity from this run.")
            selected = assess_identity(
                run["prospect"],
                run["source_records"],
                run["checkpoint"].get("identity_candidates", []),
                confirmed_id=candidate_id,
            )
            if selected.get("status") != "matched":
                raise ValueError("The selected identity still conflicts with this prospect.")
            proof_ids = [*candidate.get("source_ids", []), candidate.get("source_id")]
            confirmation = {
                "candidate_id": candidate_id,
                "evidence_version": evidence_version,
                "confirmed_at": self._time().isoformat(),
                "candidate": candidate,
                "proof_sources": {
                    source["id"]: source
                    for source in run["source_records"]
                    if source["id"] in proof_ids
                },
            }
            self.conn.execute(
                "UPDATE workbench_research_state SET confirmation_json=? WHERE run_id=?",
                (canonical(confirmation), key),
            )
            self.conn.execute(
                "UPDATE workbench_runs SET execution_status='queued',business_outcome=NULL,"
                "updated_at=? WHERE run_id=?",
                (self._time().isoformat(), key),
            )
            self._stage(
                key,
                "Confirm prospect",
                "completed",
                "A reviewer confirmed this source-supported identity.",
            )
            self.set_run(
                key, status="queued", progress="Identity confirmed; saved research can continue."
            )

    def claim_workbench_run(self, key):
        with self.transaction():
            changed = self.conn.execute(
                "UPDATE workbench_runs SET execution_status='running',updated_at=? "
                "WHERE run_id=? AND execution_status='queued'",
                (now(), key),
            ).rowcount
            if changed:
                options = self.one("SELECT * FROM workbench_research_options WHERE run_id=?", (key,))
                if not options:
                    self.conn.execute(
                        "INSERT INTO workbench_research_options VALUES (?,?,NULL)",
                        (key, canonical(DEFAULT_LIMITS)),
                    )
                    options = {"limits_json": canonical(DEFAULT_LIMITS)}
                deadline = (
                    self._time()
                    + timedelta(seconds=json.loads(options["limits_json"])["wall_seconds"])
                ).isoformat()
                self.conn.execute(
                    "UPDATE workbench_research_options SET deadline_at=COALESCE(deadline_at,?) "
                    "WHERE run_id=?",
                    (deadline, key),
                )
                self.set_run(key, status="running", progress="Checking the saved research inputs.")
        return bool(changed)

    def _stage(self, key, name, status, detail):
        self.conn.execute(
            "INSERT INTO workbench_stage_events(run_id,name,status,detail,created_at) VALUES (?,?,?,?,?)",
            (key, name, status, detail, now()),
        )

    def add_stage(self, key, name, status, detail=""):
        with self.transaction():
            row = self.one("SELECT execution_status FROM workbench_runs WHERE run_id=?", (key,))
            if not row or row["execution_status"] != "running":
                raise ValueError("The research run is not active.")
            self._stage(key, name, status, detail)
            stamp = now()
            self.conn.execute("UPDATE workbench_runs SET updated_at=? WHERE run_id=?", (stamp, key))
            self.set_run(key, progress=detail)

    def finish_workbench_run(self, key, result):
        result = dict(result)
        drafts = result.pop("drafts", None) or []
        with self.transaction():
            changed = self.conn.execute(
                "UPDATE workbench_runs SET execution_status='completed',business_outcome=?,"
                "result_json=?,updated_at=? WHERE run_id=? AND execution_status='running'",
                (result["outcome"], canonical(result), now(), key),
            ).rowcount
            if not changed:
                raise ValueError("The research run is no longer active.")
            for draft in drafts:
                self._insert_draft(key, draft, draft["origin"])
            self._stage(
                key, "Save research result", "completed", "Result and business outcome saved."
            )
            self.set_run(key, status="completed", progress=result["next_action"])

    def _partial_result(self, key, reason, next_action):
        run = self.get_workbench_run(key)
        previous = run["result"] if run else {}
        return {
            **previous,
            "outcome": "research_unavailable",
            "identity": previous.get("identity"),
            "sources": (run["source_records"] or run["checkpoint"].get("sources", []))
            if run
            else [],
            "hook": None,
            "reason": reason,
            "next_action": next_action,
        }

    def fail_workbench_run(self, key, reason=None):
        result = self._partial_result(
            key,
            reason or "Research stopped before a result could be saved.",
            "Inspect saved stages, sources and spending before starting new research.",
        )
        with self.transaction():
            changed = self.conn.execute(
                "UPDATE workbench_runs SET execution_status='failed',business_outcome=?,result_json=?,"
                "updated_at=? WHERE run_id=? AND execution_status='running'",
                (result["outcome"], canonical(result), now(), key),
            ).rowcount
            if changed:
                self._stage(key, "Research stopped", "failed", result["reason"])
                self.set_run(
                    key, status="failed", error=result["reason"], progress=result["next_action"]
                )

    def recover_workbench_runs(self):
        """Single-worker startup recovery: show interruption, never silently restart work."""
        with self.transaction():
            rows = self.rows(
                "SELECT run_id FROM workbench_runs WHERE execution_status IN ('queued','running')"
            )
            for row in rows:
                key = row["run_id"]
                saved = json.loads(
                    self.one("SELECT result_json FROM workbench_runs WHERE run_id=?", (key,))[
                        "result_json"
                    ]
                )
                if saved.get("drafting"):
                    # Only a "Write the draft" attempt was interrupted: research stays.
                    saved.pop("drafting")
                    saved["limitations"] = [
                        *saved.get("limitations", []),
                        "Drafting stopped: the process stopped while the draft was written.",
                    ]
                    self.conn.execute(
                        "UPDATE workbench_runs SET execution_status='completed',result_json=?,"
                        "updated_at=? WHERE run_id=?",
                        (canonical(saved), now(), key),
                    )
                    self._stage(key, "Draft email", "failed", "The process stopped.")
                    self.set_run(key, status="completed")
                    continue
                result = self._partial_result(
                    key,
                    "The process stopped before this research run finished.",
                    "Review saved progress. No request has been replayed automatically.",
                )
                self.conn.execute(
                    "UPDATE workbench_runs SET execution_status='interrupted',business_outcome=?,"
                    "result_json=?,updated_at=? WHERE run_id=?",
                    (result["outcome"], canonical(result), now(), key),
                )
                self._stage(key, "Research interrupted", "failed", result["reason"])
                self.set_run(
                    key, status="failed", error=result["reason"], progress=result["next_action"]
                )
        return len(rows)

    # ---- Batches: many prospects, one goal, one authorization ----------------------------

    def create_batch(self, request_id, prospects, campaign, *, mode, limits=None):
        """Queue one run per prospect. The same form submission returns the same batch."""
        existing = self.one("SELECT batch_id FROM workbench_batches WHERE request_id=?", (request_id,))
        if existing:
            return existing["batch_id"], False
        if not 1 <= len(prospects) <= MAX_BATCH:
            raise ValueError(f"A batch holds 1 to {MAX_BATCH} prospects.")
        batch_id = hashlib.sha256(("batch:" + request_id).encode()).hexdigest()[:16]
        keys = [
            self.submit(prospect, f"{request_id}:{number}", campaign, mode=mode, limits=limits)[0]
            for number, prospect in enumerate(prospects, 1)
        ]
        with self.transaction():
            self.conn.execute(
                "INSERT INTO workbench_batches VALUES (?,?,?,?)", (batch_id, request_id, mode, now())
            )
            self.conn.executemany(
                "INSERT INTO workbench_batch_runs VALUES (?,?,?)",
                [(batch_id, number, key) for number, key in enumerate(keys, 1)],
            )
        return batch_id, True

    def get_batch(self, batch_id):
        row = self.one("SELECT * FROM workbench_batches WHERE batch_id=?", (batch_id,))
        if not row:
            return None
        keys = self.rows(
            "SELECT run_id FROM workbench_batch_runs WHERE batch_id=? ORDER BY position", (batch_id,)
        )
        return {
            "id": batch_id,
            "mode": row["mode"],
            "created_at": row["created_at"],
            "runs": [self.get_workbench_run(k["run_id"]) for k in keys],
        }

    def list_batches(self):
        rows = self.rows("SELECT batch_id FROM workbench_batches ORDER BY created_at DESC")
        return [self.get_batch(row["batch_id"]) for row in rows]

    def batch_of(self, key):
        """Where a run sits in its batch, for "next draft" navigation."""
        row = self.one("SELECT batch_id,position FROM workbench_batch_runs WHERE run_id=?", (key,))
        if not row:
            return None
        keys = [
            r["run_id"]
            for r in self.rows(
                "SELECT run_id FROM workbench_batch_runs WHERE batch_id=? ORDER BY position",
                (row["batch_id"],),
            )
        ]
        return {
            "id": row["batch_id"],
            "position": row["position"],
            "total": len(keys),
            "next": keys[row["position"]] if row["position"] < len(keys) else None,
            "previous": keys[row["position"] - 2] if row["position"] > 1 else None,
        }

    def release_rejected_call(self, key, call_key):
        """Close a held request that the saved stage log shows the provider refused.

        Only for outright refusals (HTTP 400/401/402/403/404/422): nothing was processed,
        so nothing was charged. Uncertain outcomes (timeouts, 5xx) can never be released.
        """
        with self.transaction():
            call = self.call(key, call_key)
            if not call or call["status"] == "complete":
                raise ValueError("That request is not held.")
            refused = None
            for event in self.rows(
                "SELECT detail FROM workbench_stage_events WHERE run_id=? AND status='failed'", (key,)
            ):
                match = re.search(r"returned HTTP (400|401|402|403|404|422)\b", event["detail"])
                if match:
                    refused = int(match.group(1))
            if refused is None:
                raise ValueError("The saved log does not show an outright refusal.")
            self.conn.execute(
                "UPDATE research_calls SET status='complete',response_json=?,charged_micro=0,"
                "cost_kind='rejected' WHERE run_id=? AND call_key=?",
                (
                    json.dumps({"rejected_status": refused, "released_after_review": True}),
                    key,
                    call_key,
                ),
            )
            self.conn.execute(
                "UPDATE workbench_operations SET status='complete' WHERE run_id=? AND call_key=?",
                (key, call_key),
            )
            self.conn.execute(
                "INSERT INTO workbench_stage_events(run_id,name,status,detail,created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    key,
                    "Held request released",
                    "completed",
                    f"The provider had refused this request (HTTP {refused}); recorded as not "
                    "charged after review.",
                    now(),
                ),
            )
        return refused

    # ---- Writing a draft after research (a hook exists, no email yet) --------------------

    def open_draft_attempt(self, key, *, seconds=120, rewrite=False):
        """Reopen a finished run for one drafting attempt; returns the attempt number."""
        with self.transaction():
            row = self.one("SELECT * FROM workbench_runs WHERE run_id=?", (key,))
            if not row or row["execution_status"] != "completed":
                raise ValueError("Wait for research to finish before writing the draft.")
            result = json.loads(row["result_json"])
            latest = self.one(
                "SELECT origin FROM workbench_drafts WHERE run_id=? ORDER BY revision DESC LIMIT 1",
                (key,),
            )
            # A template draft may be replaced on request; any draft may be rewritten with a
            # chosen set of facts. Either way the new email is a new revision.
            if latest and latest["origin"] != "template" and not rewrite:
                raise ValueError("This run already has a draft; edit it below.")
            if not result.get("hook") or (
                not latest and row["business_outcome"] != "research_ready"
            ):
                raise ValueError("A draft needs a saved hook first.")
            result["drafting"] = True
            self.conn.execute(
                "UPDATE workbench_runs SET execution_status='running',result_json=?,updated_at=? "
                "WHERE run_id=?",
                (canonical(result), now(), key),
            )
            self.conn.execute(
                "UPDATE workbench_research_options SET deadline_at=? WHERE run_id=?",
                ((self._time() + timedelta(seconds=seconds)).isoformat(), key),
            )
            self.set_run(key, status="running", progress="Writing the draft.")
            attempts = self.one(
                "SELECT COUNT(*) AS n FROM research_calls WHERE run_id=? AND "
                "call_key LIKE 'workbench/draft%/model'",
                (key,),
            )["n"]
        return attempts + 1

    def finish_draft_attempt(self, key, drafts, stopped=None, notes=()):
        with self.transaction():
            row = self.one("SELECT * FROM workbench_runs WHERE run_id=?", (key,))
            result = json.loads(row["result_json"])
            result.pop("drafting", None)
            if drafts:
                ready = drafts[-1]["check"]["ok"]
                result.update(
                    outcome="ready_for_review" if ready else "needs_revision",
                    next_action="Review the draft against its sources, then approve the "
                    "exact version."
                    if ready
                    else "Edit the highlighted wording, then check the edits again.",
                )
            result["limitations"] = [
                # An earlier failed attempt is no longer the current state once a draft exists.
                *(
                    note
                    for note in result.get("limitations", [])
                    if not (drafts and str(note).startswith("Drafting stopped"))
                ),
                *notes,
                *(["Drafting stopped: " + stopped] if stopped else []),
            ]
            self.conn.execute(
                "UPDATE workbench_runs SET execution_status='completed',business_outcome=?,"
                "result_json=?,updated_at=? WHERE run_id=? AND execution_status='running'",
                (result["outcome"], canonical(result), now(), key),
            )
            for draft in drafts:
                self._insert_draft(key, draft, draft["origin"])
            self.set_run(key, status="completed", progress=result["next_action"])

    # ---- Draft revisions and review (Phase 3) -------------------------------------------

    def _basis(self, key, row=None, state=None):
        """What an approval is bound to besides the text: evidence, identity, hook, campaign."""
        row = row or self.one("SELECT * FROM workbench_runs WHERE run_id=?", (key,))
        state = state or self.one("SELECT * FROM workbench_research_state WHERE run_id=?", (key,)) or {}
        result = json.loads(row["result_json"])
        hook = result.get("hook") or {}
        selected = (result.get("identity") or {}).get("selected") or {}
        basis = {
            "evidence_version": state.get("evidence_version", ""),
            "campaign": [row["campaign_id"], row["campaign_version"]],
            "campaign_hash": hashlib.sha256(row["campaign_json"].encode()).hexdigest(),
            "identity": [selected.get("source_id"), selected.get("quote")],
            "hook": [hook.get("signal_id"), hook.get("source_ids"), hook.get("summary")],
        }
        return basis, hashlib.sha256(canonical(basis).encode()).hexdigest()

    def _insert_draft(self, key, draft, origin):
        from outreach.core.workbench_claims import content_hash

        basis, basis_hash = self._basis(key)
        revision = (
            self.one(
                "SELECT COALESCE(MAX(revision),0) AS n FROM workbench_drafts WHERE run_id=?", (key,)
            )["n"]
            + 1
        )
        self.conn.execute(
            "INSERT INTO workbench_drafts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                revision,
                origin,
                draft["subject"],
                draft["body"],
                canonical(draft.get("claims") or []),
                canonical(draft["check"]),
                int(bool(draft["check"]["ok"])),
                content_hash(draft["subject"], draft["body"]),
                canonical(basis),
                basis_hash,
                self._time().isoformat(),
            ),
        )
        return revision

    def _review(self, key, row, state):
        drafts = [
            {
                "revision": d["revision"],
                "origin": d["origin"],
                "subject": d["subject"],
                "body": d["body"],
                "claims": json.loads(d["claims_json"]),
                "check": json.loads(d["check_json"]),
                "supported": bool(d["supported"]),
                "content_hash": d["content_hash"],
                "basis_hash": d["basis_hash"],
                "created_at": d["created_at"],
            }
            for d in self.rows("SELECT * FROM workbench_drafts WHERE run_id=? ORDER BY revision", (key,))
        ]
        events = self.rows(
            "SELECT revision,action,content_hash,basis_hash,note,created_at "
            "FROM workbench_review_events WHERE run_id=? ORDER BY id",
            (key,),
        )
        if not drafts:
            return {"drafts": [], "draft": None, "review": {"state": None, "events": events}}
        current = drafts[-1]
        _, basis_hash = self._basis(key, row, state)
        last = next((e for e in reversed(events) if e["revision"] == current["revision"]), None)
        if current["basis_hash"] != basis_hash:
            review_state = "stale"
        elif (
            last
            and last["action"] == "approve"
            and last["content_hash"] == current["content_hash"]
            and last["basis_hash"] == current["basis_hash"]
        ):
            review_state = "approved"
        elif last and last["action"] == "reject":
            review_state = "rejected"
        else:
            review_state = "ready_for_review" if current["supported"] else "needs_revision"
        return {
            "drafts": drafts,
            "draft": current,
            "review": {
                "state": review_state,
                "events": events,
                "approval": last if review_state == "approved" else None,
                "basis_hash": basis_hash,
            },
        }

    def _reviewable(self, key):
        run = self.get_workbench_run(key)
        if not run or run["execution_status"] != "completed" or not run["draft"]:
            raise ValueError("This run has no saved draft to review.")
        return run

    def _set_outcome(self, key, outcome, stage, detail):
        self.conn.execute(
            "UPDATE workbench_runs SET business_outcome=?,updated_at=? WHERE run_id=?",
            (outcome, self._time().isoformat(), key),
        )
        self._stage(key, stage, "completed", detail)

    def save_reviewer_revision(self, key, base_revision, draft):
        """Save checked reviewer text as a new immutable revision; never edit in place."""
        with self.transaction():
            run = self._reviewable(key)
            if run["draft"]["revision"] != base_revision:
                raise ValueError(
                    "The draft changed since you opened it. Review the latest version."
                )
            revision = self._insert_draft(key, draft, "reviewer")
            ready = draft["check"]["ok"]
            self._set_outcome(
                key,
                "ready_for_review" if ready else "needs_revision",
                "Check edits",
                f"Revision {revision} saved. "
                + (
                    "Claim checks passed; approval is required again."
                    if ready
                    else f"{len(draft['check']['errors'])} claim problem(s) block approval."
                ),
            )
            return revision

    def approve_draft(self, key, revision, expected_hash, recheck):
        """Approve one exact revision. `recheck` re-runs the claim checks inside the lock."""
        with self.transaction():
            run = self._reviewable(key)
            draft, review = run["draft"], run["review"]
            if draft["revision"] != revision or draft["content_hash"] != expected_hash:
                raise ValueError("Only the latest checked version can be approved. Reload it.")
            if review["state"] == "approved":
                return
            if review["state"] == "stale":
                raise ValueError("Evidence or campaign changed. Check the draft again first.")
            if review["state"] == "rejected":
                raise ValueError("This version was rejected. Check edits to create a new version.")
            if not draft["supported"] or not recheck(run)["ok"]:
                raise ValueError("Claim problems remain. Edit and check the draft first.")
            self.conn.execute(
                "INSERT INTO workbench_review_events"
                "(run_id,revision,action,content_hash,basis_hash,note,created_at) "
                "VALUES (?,?,'approve',?,?,'',?)",
                (
                    key,
                    revision,
                    draft["content_hash"],
                    draft["basis_hash"],
                    self._time().isoformat(),
                ),
            )
            self._set_outcome(
                key, "approved", "Approve draft", f"A reviewer approved revision {revision}."
            )

    def reject_draft(self, key, revision, note=""):
        with self.transaction():
            run = self._reviewable(key)
            draft = run["draft"]
            if draft["revision"] != revision:
                raise ValueError("Only the latest version can be rejected. Reload it.")
            self.conn.execute(
                "INSERT INTO workbench_review_events"
                "(run_id,revision,action,content_hash,basis_hash,note,created_at) "
                "VALUES (?,?,'reject',?,?,?,?)",
                (
                    key,
                    revision,
                    draft["content_hash"],
                    draft["basis_hash"],
                    str(note or "")[:500],
                    self._time().isoformat(),
                ),
            )
            self._set_outcome(
                key, "draft_rejected", "Reject draft", f"A reviewer rejected revision {revision}."
            )

    def approved_export(self, key):
        """The only way out of Workbench: the exact approved subject and body, or a refusal."""
        run = self.get_workbench_run(key)
        if not run or not run["draft"] or run["review"]["state"] != "approved":
            raise ValueError("Approve the current checked draft before copying or exporting it.")
        return run["draft"]
