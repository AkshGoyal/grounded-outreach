"""One-process Workbench worker with durable claims and real persisted stage events."""

import threading
import time

from outreach.core.workbench import run_pipeline
from outreach.core.workbench_claims import draft_context
from outreach.core.workbench_draft import TemplateDraftWriter, compose_draft
from outreach.core.research import ResearchStop


class WorkbenchRunner:
    def __init__(
        self, open_store, provider=None, *, provider_factory=None, writer=None, writer_factory=None
    ):
        self.open_store = open_store
        self.provider = provider
        self.provider_factory = provider_factory
        self.writer = writer
        self.writer_factory = writer_factory
        self.active = set()
        self._lock = threading.Lock()

    def start(self, key):
        with self._lock:
            if key in self.active:
                return False
            with self.open_store() as store:
                if not store.claim_workbench_run(key):
                    return False
            self.active.add(key)

        def work():
            try:
                with self.open_store() as store:
                    provider = None
                    try:
                        run = store.get_workbench_run(key)
                        provider = (
                            self.provider_factory(store, key)
                            if self.provider_factory
                            else self.provider
                        )

                        class SavedProvider:
                            def research(self, prospect):
                                try:
                                    bundle = provider.research(prospect)
                                except ResearchStop as exc:
                                    # A limit, refusal or held request ends paid research,
                                    # but everything already saved is still used.
                                    bundle = getattr(provider, "bundle", None)
                                    if not isinstance(bundle, dict):
                                        raise
                                    bundle["stopped_reason"] = str(exc)
                                bundle["reference_time"] = run["created_at"]
                                bundle["recent_days"] = run.get("limits", {}).get(
                                    "recent_days", 180
                                )
                                for source in bundle.get("sources", []):
                                    store.save_source(key, source)
                                store.save_checkpoint(key, bundle)
                                # Saving changed proof can invalidate the prior confirmation.
                                confirmation = store.get_workbench_run(key).get("confirmation") or {}
                                bundle["confirmed_id"] = confirmation.get("candidate_id")
                                store.save_checkpoint(key, bundle)
                                return bundle

                        drafting = bool(run.get("limits", {}).get("write_draft", 1)) and not run[
                            "campaign"
                        ].get("no_goal")
                        writer = (
                            (self.writer_factory(provider) if self.writer_factory else self.writer)
                            if drafting
                            else None
                        )
                        result = run_pipeline(
                            run["prospect"],
                            run["campaign"],
                            SavedProvider(),
                            lambda name, status, detail: store.add_stage(key, name, status, detail),
                            writer,
                            TemplateDraftWriter() if self.writer_factory and drafting else None,
                        )
                        store.finish_workbench_run(key, result)
                    except ResearchStop as exc:
                        store.fail_workbench_run(key, reason=str(exc))
                    except Exception:
                        store.fail_workbench_run(key)
                    finally:
                        if (
                            provider is not None
                            and self.provider_factory
                            and hasattr(provider, "close")
                        ):
                            provider.close()
            finally:
                with self._lock:
                    self.active.discard(key)

        thread = threading.Thread(target=work, name="workbench-research-" + key, daemon=True)
        try:
            thread.start()
        except RuntimeError:
            with self.open_store() as store:
                store.fail_workbench_run(key)
            with self._lock:
                self.active.discard(key)
            raise
        return True

    def start_batch(self, keys, *, concurrency=3):
        """Work through queued runs a few at a time, in order."""

        def work():
            pending = list(keys)
            while pending:
                with self._lock:
                    busy = len(self.active & set(keys))
                if busy < concurrency:
                    try:
                        self.start(pending.pop(0))
                    except Exception:  # noqa: S112 - one bad run must not stop the batch
                        continue
                else:
                    time.sleep(0.05)

        threading.Thread(target=work, name="workbench-batch", daemon=True).start()

    def write_draft(self, key, exclude=(), include=()):
        """Write the email for a run whose research saved a hook but no draft.

        Runs in the request (about 10–30 seconds). Uses new ledger keys per attempt, so
        nothing earlier is replayed. Returns None, or the reason drafting stopped.
        """
        with self._lock:
            if key in self.active:
                raise ValueError("This run is already working.")
            self.active.add(key)
        try:
            with self.open_store() as store:
                attempt = store.open_draft_attempt(
                    key, rewrite=bool(exclude) or bool(include) or None
                )
                provider = None
                stopped = None
                drafts, notes = [], []
                try:
                    provider = (
                        self.provider_factory(store, key)
                        if self.provider_factory
                        else self.provider
                    )
                    writer = (
                        self.writer_factory(provider, attempt)
                        if self.writer_factory
                        else self.writer
                    )
                    if writer is None:
                        stopped = "No draft writer is configured on this server."
                    else:
                        run = store.get_workbench_run(key)
                        context = draft_context(
                            {
                                "result": run["result"],
                                "campaign": run["campaign"],
                                "prospect": run["prospect"],
                                "exclude": list(exclude),
                                "include": list(include),
                            }
                        )
                        drafts, stopped, notes = compose_draft(
                            writer,
                            context,
                            lambda name, status, detail: store.add_stage(key, name, status, detail),
                            TemplateDraftWriter() if self.writer_factory else None,
                        )
                except ResearchStop as exc:
                    stopped = str(exc)
                except Exception:
                    stopped = "The draft could not be written."
                finally:
                    if (
                        provider is not None
                        and self.provider_factory
                        and hasattr(provider, "close")
                    ):
                        provider.close()
                store.finish_draft_attempt(key, drafts, stopped, notes)
                return stopped
        finally:
            with self._lock:
                self.active.discard(key)
