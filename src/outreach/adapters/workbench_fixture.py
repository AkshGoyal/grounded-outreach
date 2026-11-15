"""Deterministic fictional provider data, evaluated by the live evidence gates."""

import re
from copy import deepcopy

from outreach.core.workbench_draft import tidy_passage

IDENTITY_QUOTE = "Maya Rao is Finance Director at Cedar Works and oversees invoice review."
SIGNAL_QUOTE = (
    "Cedar Works is introducing a weekly invoice exception review led by "
    "Maya Rao, with a named owner for each unresolved exception."
)
FIXTURE_RESPONSE = {
    "identity_candidates": [
        {
            "name": "Maya Rao",
            "company": "Cedar Works",
            "role": "Finance Director",
            "domain": "cedar-works.example",
            "source_id": "fixture-leadership",
            "quote": IDENTITY_QUOTE,
            "status": "current",
        }
    ],
    "signals": [
        {
            "source_id": "fixture-invoice-review",
            "title": "Invoice exception review",
            "quote": SIGNAL_QUOTE,
            "company": "Cedar Works",
            "person": "Maya Rao",
            "kind": "event",
            "event_date": "2026-10-15",
            "event_key": "cedar-invoice-review",
            "role_tags": ["finance"],
            "specificity": 3,
        }
    ],
    "sources": [
        {
            "id": "fixture-leadership",
            "kind": "identity",
            "url": "https://cedar-works.example/leadership",
            "publisher": "Cedar Works (fictional)",
            "title": "Finance leadership",
            "text": IDENTITY_QUOTE,
            "passage": IDENTITY_QUOTE,
            "fixture": True,
            "access_status": "read",
            "quality": "official",
            "publication_date": None,
            "event_date": None,
            "retrieved_at": "2026-11-10T00:00:00+00:00",
        },
        {
            "id": "fixture-invoice-review",
            "kind": "signal",
            "url": "https://cedar-works.example/news/invoice-review",
            "publisher": "Cedar Works (fictional)",
            "title": "Invoice exception review",
            "text": SIGNAL_QUOTE,
            "passage": SIGNAL_QUOTE,
            "fixture": True,
            "access_status": "read",
            "quality": "official",
            "publication_date": "2026-10-15",
            "event_date": "2026-10-15",
            "retrieved_at": "2026-11-10T00:00:00+00:00",
        },
    ],
    "limitations": [],
    "reference_time": "2026-11-10T00:00:00+00:00",
    "identity_done": True,
    "signal_done": True,
}


RETRIEVED = "2026-11-10T00:00:00+00:00"


def _source(
    source_id,
    url,
    publisher,
    title,
    text,
    *,
    kind="signal",
    quality="official",
    published=None,
    event=None,
    access="read",
    reason="",
):
    readable = access == "read"
    return {
        "id": source_id,
        "kind": kind,
        "url": url,
        "publisher": publisher + " (fictional)",
        "title": title,
        "text": text if readable else "",
        "passage": text if readable else "",
        "fixture": True,
        "access_status": access,
        "quality": quality,
        "publication_date": published,
        "event_date": event,
        "retrieved_at": RETRIEVED,
        **({"limitation": reason} if reason else {}),
    }


def _bundle(candidates, signals, sources, limitations=()):
    return {
        "identity_candidates": candidates,
        "signals": signals,
        "sources": sources,
        "limitations": list(limitations),
        "reference_time": RETRIEVED,
        "identity_done": True,
        "signal_done": True,
    }


# (a) Same name, changed employer: two current identities need a reviewer's choice, and
# the other company's news must never become a claim about this prospect.
_JORDAN_TEAM = "Jordan Ellis, Controller at Northwind Supply, leads accounts payable."
_JORDAN_OTHER = (
    "Jordan Ellis is Head of Finance at Harbor Line Logistics after joining from a "
    "distributor this autumn."
)
_JORDAN_SIGNAL = (
    "Northwind Supply is moving supplier invoice approvals into one shared exception "
    "queue owned by its accounts payable team."
)
_HARBOR_SIGNAL = (
    "Harbor Line Logistics is replacing purchase-order matching across its finance team, "
    "led by Jordan Ellis."
)
SAME_NAME = _bundle(
    [
        {
            "name": "Jordan Ellis",
            "company": "Northwind Supply",
            "role": "Controller",
            "domain": "northwind-supply.example",
            "source_id": "northwind-team",
            "quote": "Jordan Ellis, Controller at Northwind Supply",
            "status": "current",
        },
        {
            "name": "Jordan Ellis",
            "company": "Harbor Line Logistics",
            "role": "Head of Finance",
            "domain": "harborline-logistics.example",
            "source_id": "harbor-line-people",
            "quote": "Jordan Ellis is Head of Finance at Harbor Line Logistics",
            "status": "current",
        },
    ],
    [
        {
            "source_id": "northwind-approvals",
            "title": "Supplier invoice approvals",
            "quote": _JORDAN_SIGNAL,
            "company": "Northwind Supply",
            "person": "",
            "kind": "event",
            "event_date": "2026-10-02",
            "event_key": "northwind-invoice-approval-queue",
            "role_tags": ["finance", "controller"],
            "specificity": 3,
        },
        {
            "source_id": "harbor-line-matching",
            "title": "Purchase-order matching",
            "quote": _HARBOR_SIGNAL,
            "company": "Harbor Line Logistics",
            "person": "Jordan Ellis",
            "kind": "event",
            "event_date": "2026-10-20",
            "event_key": "harbor-po-matching",
            "role_tags": ["finance"],
            "specificity": 3,
        },
    ],
    [
        _source(
            "northwind-team",
            "https://northwind-supply.example/team",
            "Northwind Supply",
            "Finance team",
            _JORDAN_TEAM,
            kind="identity",
        ),
        _source(
            "harbor-line-people",
            "https://harborline-logistics.example/people",
            "Harbor Line Logistics",
            "New finance leadership",
            _JORDAN_OTHER,
            kind="identity",
            published="2026-09-30",
        ),
        _source(
            "northwind-approvals",
            "https://northwind-supply.example/news/approvals",
            "Northwind Supply",
            "Supplier invoice approvals",
            _JORDAN_SIGNAL,
            published="2026-10-02",
            event="2026-10-02",
        ),
        _source(
            "harbor-line-matching",
            "https://harborline-logistics.example/news/po-matching",
            "Harbor Line Logistics",
            "Purchase-order matching",
            _HARBOR_SIGNAL,
            published="2026-10-20",
            event="2026-10-20",
        ),
    ],
)

# (b) Blocked sources and sparse evidence: identity comes from a permitted alternative,
# but nothing readable supports a news hook. The confirmed role becomes a weaker hook.
_PRIYA_BIO = "Priya Nair, Finance Director at Fernhill Foods, spoke about supplier onboarding."
SPARSE = _bundle(
    [
        {
            "name": "Priya Nair",
            "company": "Fernhill Foods",
            "role": "Finance Director",
            "domain": "fernhill-foods.example",
            "source_id": "fernhill-speakers",
            "quote": "Priya Nair, Finance Director at Fernhill Foods",
            "status": "current",
        },
    ],
    [
        {
            "source_id": "fernhill-press-preview",
            "title": "Invoice automation project",
            "quote": "Fernhill Foods is reviewing how supplier invoices are approved.",
            "company": "Fernhill Foods",
            "person": "",
            "kind": "event",
            "event_date": "2026-10-12",
            "event_key": "fernhill-invoice-approval",
            "role_tags": ["finance"],
            "specificity": 2,
        },
    ],
    [
        _source(
            "fernhill-leadership",
            "https://fernhill-foods.example/leadership",
            "Fernhill Foods",
            "Leadership",
            "",
            kind="identity",
            access="blocked",
            reason="The site refused automated reading (HTTP 403).",
        ),
        _source(
            "fernhill-linkedin",
            "https://www.linkedin.com/in/fictional-priya-nair",
            "LinkedIn",
            "Profile",
            "",
            kind="identity",
            access="blocked",
            reason="LinkedIn is an identity hint only and is never extracted.",
        ),
        _source(
            "fernhill-speakers",
            "https://fernhill-foods.example/events/speakers",
            "Fernhill Foods",
            "Supplier day speakers",
            _PRIYA_BIO,
            kind="identity",
        ),
        _source(
            "fernhill-press-preview",
            "https://trade-news.example/fernhill-invoices",
            "Trade News",
            "Invoice automation project",
            "",
            access="preview",
            quality="reporting",
            published="2026-10-12",
            reason="Search preview only; the article is behind a sign-in wall.",
        ),
    ],
    [
        "The Fernhill Foods leadership page refused automated reading; a permitted "
        "speaker page established identity instead.",
        "The only possible signal is a search preview behind a sign-in wall, which cannot "
        "support a claim.",
    ],
)

# (c) Republished old news and a conflicting detail: both events are dropped and a
# supported, evergreen responsibility is used without calling anything recent.
_DANIEL_BIO = (
    "Daniel Okafor is Controller at Larkspur Health and is responsible for supplier "
    "invoice exceptions across its clinics."
)
_DANIEL_OLD = (
    "Larkspur Health completed its move to a new purchase-order system in March 2023, "
    "according to Daniel Okafor."
)
_DANIEL_A = "Larkspur Health is consolidating 4 regional invoice review teams into one."
_DANIEL_B = "Larkspur Health is consolidating 3 regional invoice review teams into one."
REPUBLISHED = _bundle(
    [
        {
            "name": "Daniel Okafor",
            "company": "Larkspur Health",
            "role": "Controller",
            "domain": "larkspur-health.example",
            "source_id": "larkspur-finance",
            "quote": "Daniel Okafor is Controller at Larkspur Health",
            "status": "current",
        },
    ],
    [
        {
            "source_id": "larkspur-republished",
            "title": "Purchase-order system move",
            "quote": _DANIEL_OLD,
            "company": "Larkspur Health",
            "person": "Daniel Okafor",
            "kind": "event",
            "event_date": "2023-03-15",
            "event_key": "larkspur-po-system",
            "role_tags": ["finance"],
            "specificity": 3,
        },
        {
            "source_id": "larkspur-consolidation",
            "title": "Invoice review teams",
            "quote": _DANIEL_A,
            "company": "Larkspur Health",
            "person": "",
            "kind": "event",
            "event_date": "2026-10-06",
            "event_key": "larkspur-invoice-team-consolidation",
            "role_tags": ["finance"],
            "specificity": 3,
        },
        {
            "source_id": "larkspur-trade-report",
            "title": "Invoice review teams",
            "quote": _DANIEL_B,
            "company": "Larkspur Health",
            "person": "",
            "kind": "event",
            "event_date": "2026-10-06",
            "event_key": "larkspur-invoice-team-consolidation",
            "role_tags": ["finance"],
            "specificity": 3,
        },
        {
            "source_id": "larkspur-finance",
            "title": "Finance responsibilities",
            "quote": _DANIEL_BIO,
            "company": "Larkspur Health",
            "person": "Daniel Okafor",
            "kind": "evergreen",
            "event_date": None,
            "event_key": "controller-responsibility",
            "role_tags": ["finance", "controller"],
            "specificity": 2,
        },
    ],
    [
        _source(
            "larkspur-finance",
            "https://larkspur-health.example/finance",
            "Larkspur Health",
            "Finance team",
            _DANIEL_BIO,
            kind="identity",
        ),
        _source(
            "larkspur-republished",
            "https://health-ops.example/larkspur-po-system",
            "Health Ops Weekly",
            "Purchase-order system move",
            _DANIEL_OLD,
            quality="reporting",
            published="2026-11-02",
            event="2023-03-15",
        ),
        _source(
            "larkspur-consolidation",
            "https://larkspur-health.example/news/review-teams",
            "Larkspur Health",
            "Invoice review teams",
            _DANIEL_A,
            published="2026-10-06",
            event="2026-10-06",
        ),
        _source(
            "larkspur-trade-report",
            "https://health-ops.example/larkspur-review-teams",
            "Health Ops Weekly",
            "Invoice review teams",
            _DANIEL_B,
            quality="reporting",
            published="2026-10-07",
            event="2026-10-06",
        ),
    ],
)

# (d) True signal, false commercial inference: research is clean, but the fixture writer
# adds unsupported wording that survives the single repair, so approval stays blocked.
_HANNAH_BIO = "Hannah Brooks is Finance Director at Ridgeway Components."
_HANNAH_SIGNAL = (
    "Ridgeway Components is introducing a shared review queue for supplier invoice "
    "exceptions, with each exception routed to a named approver."
)
FALSE_INFERENCE = _bundle(
    [
        {
            "name": "Hannah Brooks",
            "company": "Ridgeway Components",
            "role": "Finance Director",
            "domain": "ridgeway-components.example",
            "source_id": "ridgeway-leadership",
            "quote": _HANNAH_BIO.rstrip("."),
            "status": "current",
        },
    ],
    [
        {
            "source_id": "ridgeway-review-queue",
            "title": "Supplier invoice exceptions",
            "quote": _HANNAH_SIGNAL,
            "company": "Ridgeway Components",
            "person": "",
            "kind": "event",
            "event_date": "2026-10-21",
            "event_key": "ridgeway-exception-queue",
            "role_tags": ["finance"],
            "specificity": 3,
        },
    ],
    [
        _source(
            "ridgeway-leadership",
            "https://ridgeway-components.example/leadership",
            "Ridgeway Components",
            "Leadership",
            _HANNAH_BIO,
            kind="identity",
        ),
        _source(
            "ridgeway-review-queue",
            "https://ridgeway-components.example/news/queue",
            "Ridgeway Components",
            "Supplier invoice exceptions",
            _HANNAH_SIGNAL,
            published="2026-10-21",
            event="2026-10-21",
        ),
    ],
)

# Labelled demo scenarios, shown on the fixture New research page. Every one runs
# through the same identity, hook, draft and review logic as live research.
SCENARIOS = [
    {
        "key": "happy-path",
        "label": "Everything checks out",
        "prospect": {"name": "Maya Rao", "company": "Cedar Works", "role": "Finance Director"},
        "expect": "A recent, attributed event becomes the hook and the draft passes every "
        "claim check.",
        "bundle": FIXTURE_RESPONSE,
        "handles": "each unresolved exception",
        "topic": "invoice exception review",
    },
    {
        "key": "same-name",
        "label": "Two people, same name",
        "prospect": {"name": "Jordan Ellis", "company": "Northwind Supply", "role": "Controller"},
        "expect": "Two current people share the name. You confirm the right one, and the "
        "other company's news is never used.",
        "bundle": SAME_NAME,
        "handles": "each exception in that shared queue",
        "topic": "shared exception queue",
    },
    {
        "key": "sparse",
        "label": "Too little public information",
        "prospect": {"name": "Priya Nair", "company": "Fernhill Foods", "role": "Finance Director"},
        "expect": "Blocked pages and a sign-in-walled article are never used. Identity "
        "comes from a permitted page, so the email opens with their role, marked as a "
        "weaker hook.",
        "bundle": SPARSE,
    },
    {
        "key": "republished",
        "label": "Old news, republished",
        "prospect": {"name": "Daniel Okafor", "company": "Larkspur Health", "role": "Controller"},
        "expect": "A 2023 event in a recent article and two reports that disagree are held "
        "back. A supported responsibility is used without calling it recent.",
        "bundle": REPUBLISHED,
        "handles": "supplier invoice exceptions across the clinics",
        "topic": "supplier invoice exceptions",
    },
    {
        "key": "false-inference",
        "label": "Draft overclaims",
        "prospect": {
            "name": "Hannah Brooks",
            "company": "Ridgeway Components",
            "role": "Finance Director",
        },
        "expect": "The signal is real, but the draft adds an unsupported claim about their "
        "problems. One repair fails, so approval stays blocked until you fix it.",
        "bundle": FALSE_INFERENCE,
        "handles": "each routed exception",
        "topic": "supplier invoice exceptions",
        "draft_variant": "persistent_false_inference",
    },
]
_BY_NAME = {s["prospect"]["name"].casefold(): s for s in SCENARIOS}


def scenario_for(prospect):
    return _BY_NAME.get(" ".join(str(prospect.get("name", "")).split()).casefold())


class FixtureResearchProvider:
    def research(self, prospect):
        scenario = scenario_for(prospect)
        if scenario:
            return deepcopy(scenario["bundle"])
        return {"identity_candidates": [], "signals": [], "sources": [], "limitations": []}


def _sentence_start(text):
    """Join a passage after 'I read that' without lowercasing a proper noun."""
    first = text.split(" ", 1)[0]
    if first.lower() in {"on", "in", "the", "a", "an", "this", "last", "during", "at"}:
        return text[0].lower() + text[1:]
    return text


def _lower_first(text):
    return text[0].lower() + text[1:] if text else text


def _topic(quote, offer_text):
    """Shortest run of the passage that names the offer-related topic, for the subject."""
    words = quote.rstrip(".").split()
    offer = {w.lower().strip(".,").rstrip("s") for w in offer_text.split() if len(w) > 3}
    marked = [i for i, w in enumerate(words) if w.lower().strip(".,").rstrip("s") in offer]
    if not marked:
        return " ".join(words[:5])
    start = marked[0]
    end = max(i for i in marked if i - start < 5)
    return " ".join(words[start : end + 1]).strip(",.")


class FixtureDraftWriter:
    """Deterministic, explicitly fictional drafts that still pass through the real checks.

    Variants exercise the review path without a model:
    ``supported`` writes a grounded draft; ``false_inference`` first adds an unsupported
    commercial inference and repairs it; ``persistent_false_inference`` keeps one after
    the single repair, so the run is held for the reviewer.
    """

    origin = "fixture"

    def __init__(self, variant=None):
        # None follows the labelled scenario for the prospect, else a supported draft.
        self.variant = variant

    def _variant(self, context):
        scenario = scenario_for(context["prospect"]) or {}
        return self.variant or scenario.get("draft_variant") or "supported"

    def _draft(self, context, bad=None):
        prospect, hook = context["prospect"], context["hook"]
        claims = {k: v["text"] for k, v in context["supports"].items()}
        capabilities = [claims[k] for k in sorted(claims) if k.startswith("capability-")]
        first = prospect["name"].split()[0]
        # Address the prospect directly rather than naming them to themselves.
        name = re.escape(prospect["name"])
        passage = re.sub(
            r"\b(led|run|owned|managed) by " + name + r"\b",
            r"\1 by you",
            hook["summary"].rstrip("."),
        )
        if re.match(name + r" is ", passage):
            passage = re.sub(r"^" + name + r" is ", "you are ", passage)
            passage = passage.replace(" and is ", " and are ")
        entered = hook.get("basis") == "as_entered"
        if entered:
            passage = tidy_passage(hook["summary"], prospect["name"], recent=False)
        lead = "I understand that " if entered else "I read that "
        opener = lead + _sentence_start(passage) + "."
        bridge = [
            f"{context['sender_company']} can {_lower_first(capabilities[0])}",
            *(f"It can also {_lower_first(c)}" for c in capabilities[1:2]),
        ]
        scenario = scenario_for(prospect) or {}
        handles = scenario.get("handles", "this work")
        inference = f"That may be relevant to how your team handles {handles}."
        sentences = [opener, *(bad or []), *bridge, inference]
        body = "\n\n".join(
            [f"Hi {first},", " ".join(sentences), context["cta"], "Best,\n" + context["sender"]]
        )
        topic = scenario.get("topic") or _topic(hook["summary"], " ".join(capabilities))
        subject = claims["offer"].rstrip(".") if entered else f"{prospect['company']} {topic}"
        cited = [
            {
                "text": opener,
                "kind": "fact",
                "support_id": hook["source_id"],
                "relevance": "core",
                "why": "The hook, said to them.",
            },
            *(
                {
                    "text": text,
                    "kind": "offer",
                    "support_id": f"capability-{number}",
                    "relevance": "offer",
                    "why": "What you offer.",
                }
                for number, text in enumerate(bridge, 1)
            ),
            {
                "text": inference,
                "kind": "inference",
                "support_id": hook["source_id"],
                "relevance": "optional",
                "why": "A link between the two; could be cut.",
            },
        ]
        return {"subject": subject, "body": body, "claims": cited}

    def generate(self, stage, prompt, context):
        company = context["prospect"]["company"]
        variant = self._variant(context)
        if variant == "false_inference" and stage == "draft":
            return self._draft(
                context,
                [
                    f"Because {company} is clearly struggling with invoice errors, "
                    "your team needs a faster review."
                ],
            )
        if variant == "persistent_false_inference":
            wording = {
                "draft": f"Because {company} is clearly struggling with invoice errors, "
                "your team needs a faster review.",
                "repair": "The new review suggests unresolved exceptions are slowing "
                "your team down.",
            }[stage]
            return self._draft(context, [wording])
        return self._draft(context)
