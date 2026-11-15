"""Generate a whole campaign's unsent drafts with progress and a stop control."""

import threading
from dataclasses import dataclass

from outreach.core.drafting import draft_email
from outreach.core.review import checks_for_display, storable_body
from outreach.generation import generation_snapshot, recipient_generation
from outreach.ports.llm import LLMError


@dataclass
class DraftJob:
    campaign_id: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    finished: bool = False
    stopped: bool = False
    error: str = ""


class DraftRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.job = None
        self.inline_busy = False

    @property
    def busy(self):
        return self.inline_busy or (self.job is not None and not self.job.finished)

    def start(self, cid, open_store, open_llm, profile, *, rewrite=False):
        with self.lock:
            if self.busy:
                return False
            try:
                generation = generation_snapshot(cid)
            except ValueError as exc:
                self.job = DraftJob(cid, finished=True, error=str(exc))
                return False
            job = DraftJob(cid)
            self.job = job

        def work():
            db = open_store()
            try:
                copy, closing = generation["campaign_copy"], generation["closing"]
                if db.get_campaign(cid) is None:
                    raise ValueError("Campaign not found.")
                if not copy:
                    raise ValueError("Add the campaign topic and offer first.")
                account = profile(cid)
                llm = open_llm()
                rows = db._conn.execute(
                    "SELECT id FROM contacts WHERE campaign_id=? ORDER BY id", (cid,)
                ).fetchall()
                eligible = [
                    r["id"]
                    for r in rows
                    if not db.already_written_to(r["id"])
                    and (
                        rewrite
                        or not db._conn.execute(
                            "SELECT 1 FROM drafts WHERE contact_id=?", (r["id"],)
                        ).fetchone()
                    )
                ]
                job.total = len(eligible)
                for contact_id in eligible:
                    if job.stopped:
                        break
                    contact = db.get_contact(contact_id)
                    if contact is None or contact.campaign_id != cid:
                        raise ValueError("Campaign recipient changed during generation.")
                    if db.is_suppressed(contact.email):
                        continue
                    try:
                        result = draft_email(
                            llm,
                            company=contact.company,
                            evidence=contact.evidence,
                            campaign_copy=copy,
                            sender=account.sender_name or "",
                            closing=closing,
                        )
                    except ValueError as exc:
                        job.failed += 1
                        job.error = str(exc)[:300]
                        continue
                    except LLMError:
                        job.failed += 1
                        continue
                    # Save validates identity and unchanged instructions before retiring approvals.
                    db.save_draft(
                        contact_id=contact_id,
                        model=account.llm_model,
                        subject=result.draft.subject,
                        body=storable_body(result),
                        verdict=result.verdict.value,
                        checks=checks_for_display(result),
                        generation=recipient_generation(generation, contact),
                    )
                    db._conn.execute(
                        "UPDATE drafts SET status='rejected' WHERE contact_id=? "
                        "AND status='approved'",
                        (contact_id,),
                    )
                    job.completed += 1
            except Exception:
                job.error = (
                    "Drafting stopped. Check campaign copy, sending account and AI "
                    "configuration. Saved drafts are available for review."
                )
            finally:
                db._conn.close()
                job.finished = True

        threading.Thread(target=work, name="draft-" + cid, daemon=True).start()
        return True
