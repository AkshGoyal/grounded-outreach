"""Real named-prospect adapter and accounting with fictional HTTP responses only."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from outreach.adapters.db import connect
from outreach.adapters.workbench_fixture import FixtureDraftWriter
from outreach.adapters.workbench_research import ParallelProspectProvider, SourcePolicy
from outreach.adapters.workbench_store import WorkbenchStore
from outreach.adapters.research_api import ResearchAPI
from outreach.adapters.store_sqlite import SqliteStore
from outreach.config import Settings
from outreach.core.workbench import DEMO_CAMPAIGN
from outreach.core.workbench_evidence import assess_identity, select_hook
from outreach.core.research import ResearchStop

LEADERSHIP = "https://cedar-works.example/leadership"
NEWS = "https://cedar-works.example/news/invoice-review"
PERSON = "Maya Rao is Finance Director at Cedar Works and oversees invoice review."
EVENT = "On 2026-10-15, Cedar Works introduced a weekly invoice exception review led by Maya Rao."
PROSPECT = {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director", "email": ""}


def writer_context(payload):
    """Rebuild the writer's view from the prompt payload, as a real model would see it."""
    sender = payload["sender_signature"]
    return {
        "prospect": payload["prospect"],
        "hook": {
            "source_id": payload["selected_hook"]["support_id"],
            "summary": payload["selected_hook"]["passage"],
        },
        "supports": payload["supports"],
        "cta": payload["call_to_action"],
        "sender": sender,
        "sender_company": sender.partition(",")[2].strip(),
    }


def public_resolver(host, port):
    return ["8.8.8.8"]


class PublicSources:
    def __init__(
        self,
        *,
        timeout_at=None,
        sparse=False,
        restricted=False,
        draft_variant="supported",
        junk_candidate=False,
        unreadable=False,
    ):
        self.calls = []
        self.junk_candidate = junk_candidate
        self.unreadable = unreadable
        self.timeout_at, self.sparse, self.restricted = timeout_at, sparse, restricted
        self.draft_variant = draft_variant

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if len(self.calls) == self.timeout_at:
            raise httpx.ReadTimeout("Explicitly fictional uncertain request")
        if request.url.path.endswith("/search"):
            urls = [LEADERSHIP] if "leadership" in body["search_queries"][0] else [NEWS]
            if self.restricted and urls == [LEADERSHIP]:
                urls.insert(0, "https://www.linkedin.com/in/fictional-maya")
                urls.insert(1, "https://cedar-works.example/restricted")
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": u,
                            "title": "Fictional public source",
                            "full_content": "PREVIEW IS NOT PROOF",
                        }
                        for u in urls
                    ]
                },
            )
        if request.url.path.endswith("/extract"):
            url = body["urls"][0]
            if self.unreadable:
                return httpx.Response(200, json={"errors": [{"url": url, "status_code": 403}]})
            if url.endswith("restricted"):
                return httpx.Response(200, json={"errors": [{"url": url, "status_code": 403}]})
            text = PERSON if url == LEADERSHIP else EVENT
            if self.sparse and url == LEADERSHIP:
                text = "Cedar Works leadership: our finance team supports suppliers."
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": url,
                            "title": "Fictional business source",
                            "publisher": "Cedar Works",
                            "full_content": text,
                            "event_date": "2026-10-15" if url == NEWS else None,
                            "publication_date": "2026-10-15" if url == NEWS else None,
                        }
                    ]
                },
            )
        prompt = body["messages"][-1]["content"]
        assert "PREVIEW IS NOT PROOF" not in prompt
        assert "@" not in prompt
        context = json.loads(prompt[prompt.index('{"prospect"') :])
        schema = body["response_format"]["json_schema"]["name"]
        if schema == "draftoutput":
            stage = "repair" if prompt.startswith("Revise") else "draft"
            result = FixtureDraftWriter(self.draft_variant).generate(
                stage, prompt, writer_context(context)
            )
        elif schema == "identityfindings":
            source = next(s for s in context["sources"] if s["url"] == LEADERSHIP)
            result = {
                "identity_candidates": []
                if self.sparse
                else [
                    {
                        "name": "Maya Rao",
                        "company": "Cedar Works",
                        "role": "Finance Director",
                        "domain": "cedar-works.example",
                        "source_id": source["id"],
                        "quote": PERSON,
                        "status": "current",
                    }
                ]
            }
            if self.junk_candidate:
                # Seen in a real live run: an uncertain candidate with "Unknown" as quote.
                result["identity_candidates"].append(
                    {
                        "id": "",
                        "name": "Maya Rao",
                        "company": "Cedar Works Holdings",
                        "role": "Head of Finance",
                        "domain": "cedar-works.example",
                        "source_id": source["id"],
                        "quote": "Unknown",
                        "status": "uncertain",
                        "effective_date": None,
                    }
                )
        else:
            source = next(s for s in context["sources"] if s["url"] == NEWS)
            result = {
                "signals": [
                    {
                        "title": "Invoice exception review",
                        "company": "Cedar Works",
                        "person": "Maya Rao",
                        "source_id": source["id"],
                        "quote": EVENT,
                        "kind": "event",
                        "event_date": "2026-10-15",
                        "role_tags": ["finance", "invoice"],
                        "specificity": 3,
                        "event_key": "invoice-review-2026-10-15",
                    }
                ]
            }
        return httpx.Response(
            200,
            json={
                "usage": {"cost": 0.001},
                "choices": [
                    {
                        "message": {"content": json.dumps(result)},
                    }
                ],
            },
        )


@pytest.fixture
def rig(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "test.db"),
        parallel_api_key="fictional",
        openrouter_api_key="fictional",
    )
    db = WorkbenchStore(SqliteStore(connect(settings.db_path)))
    yield settings, db
    db.close()


def setup(rig, fake, *, limits=None, prospect=None):
    settings, db = rig
    prospect = PROSPECT | (prospect or {})
    key, _ = db.submit(prospect, "fictional-request", DEMO_CAMPAIGN, mode="live", limits=limits)
    assert db.claim_workbench_run(key)
    api = ResearchAPI(settings, db, key, client=httpx.Client(transport=httpx.MockTransport(fake)))
    return ParallelProspectProvider(api, policy=SourcePolicy(public_resolver)), key, prospect


def test_no_email_reaches_supported_hook_and_checkpoint_without_replaying(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake)
    bundle = provider.research(prospect)
    identity = assess_identity(prospect, bundle["sources"], bundle["identity_candidates"])
    assert identity["status"] == "matched"
    result = select_hook(
        prospect,
        DEMO_CAMPAIGN,
        bundle["sources"],
        bundle["signals"],
        identity,
        now=datetime(2026, 11, 10, tzinfo=UTC),
    )
    assert result["outcome"] == "research_ready"
    _, db = rig
    assert db.get_workbench_run(key)["checkpoint"]["signal_done"]
    before = len(fake.calls)
    assert provider.research(prospect) == bundle
    assert len(fake.calls) == before
    usage = db.usage(key)
    # Thorough: identity (2), news (3), growth (2), and one more news search (2) because
    # the fake sources hold only one fact.
    assert usage["search_queries"] == 9 and usage["pages"] == 2
    assert usage["model_requests"] == 3 and usage["held_requests"] == 0
    assert any(s["access_status"] == "preview" and not s["text"] for s in bundle["sources"])
    signal_search = [body for path, body in fake.calls if path.endswith("/search")][1]
    assert DEMO_CAMPAIGN["offer"] in signal_search["objective"]
    assert DEMO_CAMPAIGN["supported_capabilities"][0] in signal_search["objective"]
    # The goal angle searches for the offer itself.
    assert any(DEMO_CAMPAIGN["offer"][:40] in q for q in signal_search["search_queries"])


def test_linkedin_hint_and_restricted_page_use_accessible_alternative(rig):
    fake = PublicSources(restricted=True)
    provider, _, prospect = setup(
        rig, fake, prospect={"profile_url": "https://linkedin.com/in/maya"}
    )
    bundle = provider.research(prospect)
    assert bundle["signals"] and bundle["limitations"]
    assert any(s["access_status"] == "blocked" for s in bundle["sources"])
    assert not any("linkedin" in u for _, b in fake.calls for u in b.get("urls", []))


def test_timeout_holds_reservation_and_is_never_replayed(rig):
    fake = PublicSources(timeout_at=1)
    provider, key, prospect = setup(rig, fake)
    with pytest.raises(ResearchStop, match="retained"):
        provider.research(prospect)
    with pytest.raises(ResearchStop, match="uncertain"):
        provider.research(prospect)
    _, db = rig
    assert len(fake.calls) == 1
    assert db.usage(key)["held_requests"] == 1
    assert db.get_workbench_run(key)["checkpoint"]["sources"] == []


def test_whole_http_deadline_holds_late_response_without_completing_it(rig):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_response(request):
        calls.append(request.url.path)
        entered.set()
        release.wait(2)
        return httpx.Response(200, json={"results": []})

    provider, key, prospect = setup(rig, slow_response)
    deadline = datetime.fromisoformat(rig[1].get_workbench_run(key)["deadline_at"])
    provider.clock = lambda: deadline - timedelta(seconds=0.02)
    before = time.monotonic()
    try:
        with pytest.raises(ResearchStop, match="retained"):
            provider.research(prospect)
        assert entered.is_set() and time.monotonic() - before < 0.5
        with pytest.raises(ResearchStop, match="uncertain"):
            provider.research(prospect)
        assert len(calls) == 1
    finally:
        release.set()
    # Late HTTP completion has no access to the store and cannot clear its reservation.
    assert rig[1].call(key, "workbench/identity/search")["status"] == "reserved"
    assert rig[1].usage(key)["held_requests"] == 1


def test_query_cap_stops_before_dispatch(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake, limits={"max_search_queries": 1})
    with pytest.raises(ResearchStop, match="request limit"):
        provider.research(prospect)
    assert fake.calls == []
    assert rig[1].usage(key)["spent_micro"] == 0


def test_deadline_blocks_first_dispatch(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake)
    rig[1].clock = lambda: datetime.now(UTC) + timedelta(seconds=181)
    with pytest.raises(ResearchStop, match="time limit"):
        provider.research(prospect)
    assert fake.calls == []
    assert rig[1].usage(key)["search_queries"] == 0


def test_sparse_identity_uses_only_one_bounded_followup_then_holds(rig):
    fake = PublicSources(sparse=True)
    provider, key, prospect = setup(rig, fake)
    bundle = provider.research(prospect)
    assert not bundle["identity_candidates"]
    assert rig[1].usage(key)["followups"] == 2
    # The person is not confirmed, so the company is still researched for a company-only
    # email: identity (2) + identity follow-up (2) + news (3) + growth (2) + news
    # follow-up (2) queries.
    assert rig[1].usage(key)["search_queries"] == 11
    assert bundle.get("signal_done") and bundle["signals"]


def test_disabled_followup_returns_missing_evidence_without_provider_failure(rig):
    fake = PublicSources(sparse=True)
    provider, key, prospect = setup(rig, fake, limits={"max_followups": 0})
    bundle = provider.research(prospect)
    assert not bundle["identity_candidates"] and not bundle["provider_failed"]
    assert rig[1].usage(key)["followups"] == 0
    assert rig[1].usage(key)["search_requests"] == 3  # identity, news, growth


@pytest.mark.parametrize("status", ["blocked", "empty"])
def test_no_read_evidence_skips_all_model_calls_and_returns_missing_evidence(rig, status):
    fake = PublicSources()

    def unreadable(request):
        response = fake(request)
        if request.url.path.endswith("/extract"):
            return httpx.Response(
                200,
                json={
                    "errors": [{"status_code": 403}] if status == "blocked" else [],
                    "results": [],
                },
            )
        return response

    provider, key, prospect = setup(rig, unreadable)
    bundle = provider.research(prospect)
    assert not bundle["identity_candidates"] and not bundle["signals"]
    assert bundle["provider_failed"] is False
    assert not any(source["access_status"] == "read" for source in bundle["sources"])
    usage = rig[1].usage(key)
    # Nothing readable anywhere: no model step is ever paid for.
    # Nothing readable anywhere: no model step is ever paid for.
    assert usage["model_requests"] == 0 and usage["followups"] == 2
    assert all(path.endswith(("/search", "/extract")) for path, _ in fake.calls)


def test_partial_reads_survive_later_held_request_and_are_not_replayed(rig):
    fake = PublicSources(timeout_at=4, restricted=True)
    provider, key, prospect = setup(rig, fake)
    # Search, restricted page, readable leadership page, then the model times out.
    with pytest.raises(ResearchStop, match="retained"):
        provider.research(prospect)
    saved = rig[1].get_workbench_run(key)["checkpoint"]
    assert any(s["access_status"] == "read" and s["text"] == PERSON for s in saved["sources"])
    # Whatever step comes next, the held request blocks it and nothing is replayed.
    with pytest.raises(ResearchStop, match="uncertain|held"):
        provider.research(prospect)
    assert len(fake.calls) == 4


def test_contact_address_in_identity_is_rejected_before_any_provider_request(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake)
    with pytest.raises(ResearchStop, match="private details"):
        provider.research(prospect | {"role": "Finance; contact owner@example.com"})
    assert not fake.calls and rig[1].usage(key)["spent_micro"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://[::1]/",
        "https://localhost/",
        "https://public.example:8443/",
        "https://user:password@public.example/",
        "http://169.254.169.254/",
    ],
)
def test_source_policy_rejects_private_unsafe_and_encoded_urls(url):
    assert SourcePolicy(public_resolver).check(url)[0] is None


def test_resolved_private_target_and_unsafe_redirect_are_not_admitted(rig):
    assert not SourcePolicy(lambda h, p: ["8.8.8.8", "10.0.0.1"]).check(LEADERSHIP)[0]
    provider, key, _ = setup(rig, PublicSources())
    provider.prospect = PROSPECT
    provider.bundle = {"sources": [], "limitations": []}
    source = provider._source(
        LEADERSHIP,
        "read",
        {
            "full_content": PERSON,
            "redirect_chain": ["http://127.0.0.1/private"],
        },
    )
    assert source["access_status"] == "blocked" and not source["text"]
    assert rig[1].workbench_sources(key)[0]["access_status"] == "blocked"


def test_successful_redirect_records_actual_safe_source_url_and_requested_url(rig):
    provider, _, _ = setup(rig, PublicSources())
    provider.prospect = PROSPECT
    provider.bundle = {"sources": [], "limitations": []}
    final = "https://cedar-works.example/current-leadership"
    source = provider._source(LEADERSHIP, "read", {"full_content": PERSON, "final_url": final})
    assert source["url"] == final and source["requested_url"] == LEADERSHIP


def test_unsafe_official_hint_stops_before_spending(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake)
    bundle = provider.research(prospect | {"website": "http://127.0.0.1/"})
    assert not fake.calls and bundle["limitations"]
    assert rig[1].usage(key)["spent_micro"] == 0


def test_dns_lookup_timeout_does_not_wait_for_blocked_resolver():
    release = threading.Event()

    def stalled(host, port):
        release.wait(5)
        return ["8.8.8.8"]

    started = time.monotonic()
    try:
        result, reason = SourcePolicy(stalled, dns_timeout=0.02).check(LEADERSHIP)
        assert result is None and "timed out" in reason
        assert time.monotonic() - started < 0.5
    finally:
        release.set()


def test_dns_is_cached_per_policy_but_each_check_accepts_smaller_deadline():
    calls = []

    def resolve(host, port):
        calls.append(host)
        return ["8.8.8.8"]

    policy = SourcePolicy(resolve)
    assert policy.check(LEADERSHIP)[0]
    assert policy.check(NEWS)[0]
    assert len(calls) == 1
    assert policy.check(NEWS, timeout=0)[0] is None


def test_remaining_wall_limit_applies_to_dns_and_prevents_paid_dispatch(rig):
    fake = PublicSources()
    provider, key, prospect = setup(rig, fake)
    deadline = datetime.fromisoformat(rig[1].get_workbench_run(key)["deadline_at"])
    provider.clock = lambda: deadline - timedelta(seconds=0.01)
    release = threading.Event()

    def stalled(host, port):
        release.wait(5)
        return ["8.8.8.8"]

    provider.policy = SourcePolicy(stalled)
    started = time.monotonic()
    try:
        bundle = provider.research(prospect | {"website": LEADERSHIP})
        assert bundle["limitations"] and not fake.calls
        assert time.monotonic() - started < 0.5
    finally:
        release.set()


def test_unrequested_extra_extraction_result_is_not_admitted(rig):
    fake = PublicSources()

    def extra(request):
        response = fake(request)
        if request.url.path.endswith("/extract"):
            body = response.json()
            body["results"].insert(
                0,
                {
                    "url": "https://unrelated.example/unasked",
                    "full_content": (
                        "A fictional unrelated page falsely claims a recent acquisition."
                    ),
                },
            )
            return httpx.Response(200, json=body)
        return response

    provider, _, prospect = setup(rig, extra)
    bundle = provider.research(prospect)
    assert bundle["signals"]
    assert not any("unrelated.example" in s["url"] for s in bundle["sources"])
    assert any("unrequested extra" in reason for reason in bundle["limitations"])


@pytest.mark.parametrize("tie", ["requested_url", "original_url", "redirect_chain"])
def test_extraction_redirect_requires_explicit_request_tie(rig, tie):
    provider, key, _ = setup(rig, PublicSources())
    final = "https://cedar-works.example/new-leadership"
    item = {"url": final, "full_content": PERSON}
    item[tie] = [LEADERSHIP, final] if tie == "redirect_chain" else LEADERSHIP
    assert provider._requested_result(item, LEADERSHIP)
    assert not provider._requested_result({"url": final}, LEADERSHIP)


def test_page_scan_finds_identity_the_model_missed(rig):
    # Seen live: the model returned only a weak quote; the company page itself named the
    # person with first name only ("Eric is Chief Financial Officer of ...").
    fake = PublicSources(sparse=True)
    fake_text = (
        "# Maya Rao\n## Finance Director\n"
        "Maya is Finance Director of Cedar Works, overseeing invoices and suppliers."
    )
    original = fake.__call__

    def call(request):
        response = original(request)
        if (
            request.url.path.endswith("/extract")
            and json.loads(request.content)["urls"][0] == LEADERSHIP
        ):
            data = response.json()
            data["results"][0]["full_content"] = fake_text
            return httpx.Response(200, json=data)
        return response

    provider, key, prospect = setup(rig, call)
    bundle = provider.research(prospect)
    identity = assess_identity(prospect, bundle["sources"], bundle["identity_candidates"])
    assert identity["status"] == "matched", identity
    assert identity["selected"]["quote"].startswith("Maya is Finance Director of Cedar Works")
