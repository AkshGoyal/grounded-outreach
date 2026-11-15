"""Actual campaign routes and workers with fictional model output and mail."""

import json
import threading
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from outreach.campaigns import save_texts
from outreach.core.models import Campaign, Contact, DraftStatus
from outreach.ports.llm import LLMError
from outreach.web.app import create_app
from tests.test_platform import VerifiedMailbox, db_for

CASES = {
    "job-search": (
        "Job Search",
        "job-search",
        "I have already applied through the careers portal.",
    ),
    "b2b-sales": ("B2B Sales", "B2B-sales", "We offer a 14-day trial."),
    "networking": (
        "Networking",
        "networking",
        "I would appreciate the opportunity to learn from your experience.",
    ),
}


def editor(cid):
    _, objective, fixed = CASES[cid]
    return (
        "Write a concise " + objective + " outreach introduction.\n"
        "[KEEP]\nHello {{name}},\n[/KEEP]\n"
        "Write a natural professional transition.\n"
        "[KEEP]\n" + fixed + "\n[/KEEP]\n"
        "Ask politely for a brief conversation.\n"
        "[KEEP]\nBest regards,\nKeshav\n[/KEEP]"
    )


class LayoutLLM:
    """Inspect the real structured prompt; never imitate a live model's accuracy."""

    def __init__(self):
        self.prompts = []
        self.callback = None
        self.failures = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def generate(self, *, prompt, schema, max_tokens=4096):
        self.prompts.append(prompt)
        self.entered.set()
        if self.block:
            assert self.release.wait(5), "Fictional generation was not released"
        if self.callback:
            self.callback()
        if self.failures:
            self.failures -= 1
            raise LLMError("Fictional provider failure")
        if schema.__name__ != "ComposedEmail":
            return schema.model_validate({"subject": "Hello", "sentences": [{"text": "Hello."}]})
        spec = json.loads(prompt.split("\n", 1)[1])
        texts = ["Hello.", "Could we arrange a conversation?", "Thank you."]
        sections = []
        for part in spec["editor_layout"]:
            if part["kind"] == "generate":
                sections.append(
                    {"index": part["index"], "sentences": [{"text": texts[len(sections)]}]}
                )
        return schema.model_validate({"subject": "An introduction", "sections": sections})


@pytest.fixture
def composed_workspace(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = settings.model_copy(update={"openrouter_api_key": "fake", "send_gap_seconds": 0})
    llm = LayoutLLM()
    monkeypatch.setattr("outreach.web.app.build_llm", lambda settings: llm)
    box = VerifiedMailbox()
    app = create_app(settings, mailbox=lambda identity: box)
    client = TestClient(app)
    recipients = {}
    for cid, (name, _, _) in CASES.items():
        response = client.post(
            "/campaigns/new",
            data={"name": name, "brief_mode": "structured", "message_prompt": editor(cid)},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        assert response.headers["location"].split("?")[0] == "/campaigns/" + cid
        with db_for(settings) as db:
            recipients[cid] = db.store.add_contact(
                Contact(
                    campaign_id=cid,
                    email=cid + "@fictional.example",
                    company="Fictional " + name,
                    evidence={"name": "Alex " + name, "designation": "Team lead"},
                )
            )
    return settings, app, client, llm, box, recipients


def finish(app):
    deadline = time.monotonic() + 5
    while app.state.drafter.busy and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not app.state.drafter.busy
    return app.state.drafter.job


def test_three_campaigns_generate_distinct_scoped_prompts_and_exact_previews(composed_workspace):
    settings, _, client, llm, box, recipients = composed_workspace
    for cid, (name, objective, fixed) in CASES.items():
        result = client.post("/campaigns/" + cid + "/draft", follow_redirects=False)
        assert result.status_code == 303
        prompt = llm.prompts[-1]
        assert objective in prompt and "Fictional " + name in prompt
        assert "Star Threads" not in prompt and "cotton sewing thread" not in prompt
        for other, (_, other_goal, other_fixed) in CASES.items():
            if other != cid:
                assert other_goal not in prompt and other_fixed not in prompt
        with db_for(settings) as db:
            drafts = db.store.drafts_in_campaign(cid)
            assert len(drafts) == 1
            draft = drafts[0]
            assert draft.contact_id == recipients[cid] and draft.campaign_id == cid
            assert draft.generation["campaign_copy"] == editor(cid)
            assert draft.generation["contact_id"] == recipients[cid]
            assert "Hello Alex " + name + "," in draft.body
            assert fixed in draft.body and "Best regards,\nKeshav" in draft.body
            assert (
                draft.body.index("Hello Alex")
                < draft.body.index(fixed)
                < draft.body.index("Best regards")
            )
            assert draft.body.count(fixed) == 1 and "[KEEP]" not in draft.body
            assert "Write a concise" not in draft.body and "Ask politely" not in draft.body
        preview = client.get("/drafts/" + str(draft.id))
        assert preview.status_code == 200 and fixed in preview.text
        assert "Keshav" in preview.text and "Hello Alex " + name in preview.text
    assert not box.sent


def test_editing_one_campaign_and_repeated_navigation_preserves_others(composed_workspace):
    settings, _, client, _, _, _ = composed_workspace
    with db_for(settings) as db:
        original = {cid: db.campaign(cid)["message_brief"] for cid in CASES}
    revised = editor("job-search") + "\nAvoid overly formal language."
    response = client.post("/campaigns/job-search/message", data={"message_prompt": revised})
    assert response.status_code == 200
    for _ in range(3):
        for cid in ("networking", "job-search", "b2b-sales"):
            page = client.get("/campaigns/" + cid + "/message")
            assert page.status_code == 200
            assert CASES[cid][2] in page.text
            assert 'data-server-values="true"' in page.text
    reopened = TestClient(create_app(settings))
    assert "Avoid overly formal language." in reopened.get("/campaigns/job-search/message").text
    with db_for(settings) as db:
        assert db.campaign("job-search")["message_brief"]["message_prompt"] == revised
        for cid in ("networking", "b2b-sales"):
            assert db.campaign(cid)["message_brief"] == original[cid]


def test_rewrite_uses_current_campaign_config_and_retains_old_generation(composed_workspace):
    settings, app, client, llm, box, _ = composed_workspace
    client.post("/campaigns/job-search/draft")
    with db_for(settings) as db:
        old = db.store.drafts_in_campaign("job-search")[0]
        db.store.set_draft_status(old.id, DraftStatus.APPROVED)
    revised = editor("job-search").replace("concise job-search", "friendly revised job-search")
    client.post("/campaigns/job-search/message", data={"message_prompt": revised})
    client.post("/campaigns/job-search/draft-all", data={"rewrite": "1"})
    job = finish(app)
    assert not job.error and job.completed == 1
    assert "friendly revised job-search" in llm.prompts[-1]
    with db_for(settings) as db:
        drafts = db.store.drafts_in_campaign("job-search")
        assert len(drafts) == 2 and drafts[0].generation["campaign_copy"] == revised
        assert drafts[1].generation == old.generation
        assert drafts[0].generation["instruction_hash"] != old.generation["instruction_hash"]
        assert not db.store.drafts_in_campaign("networking")
    assert not box.sent


def test_stale_foreground_result_is_discarded_without_destroying_existing_approval(
    composed_workspace,
):
    settings, _, client, llm, _, recipients = composed_workspace
    with db_for(settings) as db:
        approved = db.store.save_draft(
            contact_id=recipients["job-search"],
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(approved, DraftStatus.APPROVED)
        new_contact = db.store.add_contact(
            Contact(
                campaign_id="job-search",
                email="second@fictional.example",
                evidence={"name": "Jamie"},
            )
        )
    llm.callback = lambda: save_texts(
        "job-search", copy=editor("job-search") + "\nChanged now.", closing=""
    )
    response = client.post("/campaigns/job-search/draft", follow_redirects=False)
    assert "failed-1" in response.headers["location"]
    with db_for(settings) as db:
        assert db.store.get_draft(approved).status is DraftStatus.APPROVED
        assert not db.one("SELECT id FROM drafts WHERE contact_id=?", (new_contact,))
        assert len(db.store.drafts_in_campaign("job-search")) == 1


def test_failed_job_retry_keeps_campaign_identity(composed_workspace):
    settings, app, client, llm, box, recipients = composed_workspace
    llm.failures = 1
    client.post("/campaigns/b2b-sales/draft-all")
    failed = finish(app)
    assert failed.campaign_id == "b2b-sales" and failed.failed == 1 and failed.completed == 0
    client.post("/campaigns/networking/draft-all")
    assert finish(app).completed == 1
    client.post("/campaigns/b2b-sales/draft-all")
    retried = finish(app)
    assert retried.campaign_id == "b2b-sales" and retried.completed == 1
    with db_for(settings) as db:
        for cid in ("b2b-sales", "networking"):
            rows = db.store.drafts_in_campaign(cid)
            assert len(rows) == 1 and rows[0].contact_id == recipients[cid]
            assert rows[0].generation["campaign_id"] == cid
        assert not db.store.drafts_in_campaign("job-search")
    assert not box.sent


def test_overlapping_job_is_blocked_and_does_not_replace_active_identity(composed_workspace):
    settings, app, client, llm, _, _ = composed_workspace
    llm.block = True
    client.post("/campaigns/job-search/draft-all")
    assert llm.entered.wait(3)
    try:
        client.post("/campaigns/b2b-sales/draft-all")
        assert app.state.drafter.job.campaign_id == "job-search"
        assert len(llm.prompts) == 1
        assert "job-search" in llm.prompts[0] and "B2B-sales" not in llm.prompts[0]
    finally:
        llm.release.set()
    assert finish(app).completed == 1
    client.post("/campaigns/b2b-sales/draft-all")
    assert finish(app).completed == 1
    with db_for(settings) as db:
        assert len(db.store.drafts_in_campaign("job-search")) == 1
        assert len(db.store.drafts_in_campaign("b2b-sales")) == 1


def test_stale_background_rewrite_preserves_old_approval(composed_workspace):
    settings, app, client, llm, _, recipients = composed_workspace
    with db_for(settings) as db:
        old = db.store.save_draft(
            contact_id=recipients["job-search"],
            model="fake",
            subject="Hello",
            body="Hello.",
            verdict="clean",
            checks=[],
        )
        db.store.set_draft_status(old, DraftStatus.APPROVED)
    llm.callback = lambda: save_texts(
        "job-search", copy=editor("job-search") + "\nChanged now.", closing=""
    )
    client.post("/campaigns/job-search/draft-all", data={"rewrite": "1"})
    job = finish(app)
    assert job.error and job.completed == 0
    with db_for(settings) as db:
        assert db.store.get_draft(old).status is DraftStatus.APPROVED
        assert len(db.store.drafts_in_campaign("job-search")) == 1


def test_legacy_campaign_remains_accessible_without_foreign_fallback(composed_workspace):
    settings, _, client, llm, _, _ = composed_workspace
    with db_for(settings) as db:
        db.store.add_campaign(Campaign(id="legacy", name="Legacy", created_at=datetime.now(UTC)))
        db.store.add_contact(
            Contact(campaign_id="legacy", email="legacy@fictional.example", evidence={})
        )
    save_texts(
        "legacy", copy="Write a short hello about the legacy networking purpose.", closing=""
    )
    assert client.get("/campaigns/legacy/message").status_code == 200
    assert client.get("/campaigns/legacy").status_code == 200
    client.post("/campaigns/legacy/draft")
    assert "legacy networking purpose" in llm.prompts[-1] and "B2B-sales" not in llm.prompts[-1]
    with db_for(settings) as db:
        legacy = db.store.drafts_in_campaign("legacy")
        assert len(legacy) == 1 and legacy[0].generation["campaign_id"] == "legacy"
