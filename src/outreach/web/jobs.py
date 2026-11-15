"""Sending from the web page, in the background, one campaign at a time.

A send run takes minutes on purpose (a gap between emails), which is far too
long for one web request. So the button starts a background thread and the
browser is taken to a progress page that refreshes itself.

The rules are the same as `outreach send --really`, because it calls the same
`plan` and `dispatch`:

- only approved drafts that pass every check go, up to today's cap;
- nobody is written to twice, and the do-not-contact list is checked at the
  moment of sending;
- Stop takes effect between emails, never halfway through one.

Only one run at a time: two runs in parallel could both read the same
"not yet written to" state before either had recorded its send.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from outreach.core.dispatch import Outcome, dispatch, plan
from outreach.ports.mail import MailPort
from outreach.ports.store import StorePort


@dataclass
class SendJob:
    campaign_id: str
    total: int
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    outcomes: list[Outcome] = field(default_factory=list)
    stop_requested: bool = False
    finished: bool = False
    crashed: str | None = None
    next_email_at: float | None = None  # epoch seconds, while waiting between emails

    @property
    def sent(self) -> int:
        return sum(1 for o in self.outcomes if o.sent)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if not o.sent)

    @property
    def seconds_to_next(self) -> int | None:
        if self.next_email_at is None:
            return None
        return max(int(self.next_email_at - time.time()), 0)


class SendRunner:
    """Holds the one current (or most recent) send run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.job: SendJob | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None and not self.job.finished

    def start(
        self,
        *,
        campaign_id: str,
        open_store: Callable[[], StorePort],
        open_mailbox: Callable[[], MailPort],
        daily_cap: int,
        closing: str | None,
        campaign_copy: str,
        sender_email: str,
        tail: str,
        gap_seconds: float,
        reviewed: list | None = None,
        attachments: tuple | None = None,
    ) -> SendJob | None:
        """Start a run, or return None if one is already going or nothing
        would be sent."""
        with self._lock:
            if self.busy:
                return None
            store = open_store()
            planned = (
                reviewed
                if reviewed is not None
                else plan(
                    store,
                    campaign_id,
                    daily_cap=daily_cap,
                    closing=closing,
                    campaign_copy=campaign_copy,
                )
            )
            if hasattr(store, "_conn"):
                store._conn.close()
            going = [p for p in planned if p.will_send]
            if any(p.draft.campaign_id and p.draft.campaign_id != campaign_id for p in going):
                raise ValueError("Send selection does not belong to this campaign.")
            if not going:
                return None
            job = SendJob(campaign_id=campaign_id, total=len(going))
            self.job = job

        def pause() -> None:
            job.next_email_at = time.time() + gap_seconds
            while time.time() < job.next_email_at and not job.stop_requested:
                time.sleep(0.2)
            job.next_email_at = None

        def run() -> None:
            thread_store = None
            try:
                # A fresh connection in this thread. Browser launches keep
                # their reviewed selection; dispatch rechecks each approval,
                # suppression and daily capacity just before network I/O.
                thread_store = open_store()
                dispatch(
                    thread_store,
                    open_mailbox(),
                    planned
                    if reviewed is not None
                    else plan(
                        thread_store,
                        campaign_id,
                        daily_cap=daily_cap,
                        closing=closing,
                        campaign_copy=campaign_copy,
                    ),
                    daily_cap=daily_cap,
                    attachments=attachments,
                    sender_email=sender_email,
                    tail=tail,
                    pause=pause,
                    stop=lambda: job.stop_requested,
                    report=job.outcomes.append,
                )
            except Exception:  # shown on the page, never lost silently
                job.crashed = (
                    "Sending stopped unexpectedly. "
                    "Inspect the campaign and pending sends before restarting."
                )
            finally:
                if thread_store is not None and hasattr(thread_store, "_conn"):
                    thread_store._conn.close()
                job.finished = True

        threading.Thread(target=run, name=f"send-{campaign_id}", daemon=True).start()
        return job

    def stop(self) -> None:
        if self.job is not None:
            self.job.stop_requested = True


class InboxChecker:
    """Checks the inbox for replies — on a button, and every few minutes
    while the tool is open. One check at a time: two at once could both see
    the same new message as not yet stored."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_checked: datetime | None = None
        self.last_error: str | None = None
        self.last_result = None

    def check(self, run: Callable[[], object]) -> None:
        """Run one check now, unless one is already running."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            self.last_result = run()
            self.last_error = None
        except Exception as exc:  # shown on the Inbox page, never lost silently
            self.last_error = f"{exc}"
        finally:
            self.last_checked = datetime.now(UTC)
            self._lock.release()

    def poll_every(self, minutes: float, run: Callable[[], object]) -> None:
        def loop() -> None:
            while True:
                self.check(run)
                time.sleep(minutes * 60)

        threading.Thread(target=loop, name="inbox-poll", daemon=True).start()
