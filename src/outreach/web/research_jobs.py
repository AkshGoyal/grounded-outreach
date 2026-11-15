"""Background research with durable state and explicit restart/recovery."""

import os
import threading

from outreach.core.research import ResearchStop
from outreach.core.research_flow import build_plan, run_research


class ResearchRunner:
    def __init__(self, open_store, open_api):
        self.open_store, self.open_api = open_store, open_api
        self._lock = threading.Lock()
        self.active = set()

    def start(self, key, *, planning=False):
        with self._lock:
            if key in self.active:
                return False
            db = self.open_store()
            try:
                with db.transaction():
                    run = db.run(key)
                    allowed = (
                        ("draft", "awaiting_approval")
                        if planning
                        else ("approved", "paused", "failed")
                    )
                    if not run or run["archived"] or run["deleted"] or run["status"] not in allowed:
                        return False
                    db.set_run(
                        key,
                        status="planning" if planning else "running",
                        error="",
                        worker_pid=os.getpid(),
                    )
            finally:
                db.close()
            self.active.add(key)

        def work():
            db = self.open_store()
            api = None
            try:
                api = self.open_api(db, key)
                (build_plan if planning else run_research)(db, api, key)
            except ResearchStop as exc:
                if db.execution(key)["version"] == 2:
                    db.save_execution(
                        key,
                        outcome="paused"
                        if db.run(key)["status"] == "pause_requested"
                        else "provider_blocked",
                    )
                status = "paused" if db.run(key)["status"] == "pause_requested" else "failed"
                db.set_run(
                    key,
                    status=status,
                    error=str(exc),
                    progress="Stopped; completed results and spending are saved.",
                )
            except Exception:
                db.set_run(
                    key,
                    status="failed",
                    error=(
                        "Research stopped unexpectedly. Saved requests and spending are "
                        "retained for review."
                    ),
                )
            finally:
                if api:
                    api.close()
                db.close()
                with self._lock:
                    self.active.discard(key)

        threading.Thread(target=work, name="research-" + key, daemon=True).start()
        return True
