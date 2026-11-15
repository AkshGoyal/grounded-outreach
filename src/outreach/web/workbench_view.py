"""What the results page shows: a highlighted email with numbered sources, or, without an
email, the findings ranked one by one. Pure functions over a saved run."""

# The email is coloured by what each sentence does for the pitch, as the writer rated it
# while drafting. Source numbers stay on every sentence either way.
#   core     (deep green)  about them: the personal detail, from research
#   support  (light green) the bridge from their situation to your pitch
#   goal     (grey)        your pitch, from your goal
#   optional (amber)       pleasant but could be cut; one click removes these
#   block    (red)         blocks approval: says something the sources do not
KIND_BY_STATUS = {"error": "block", "notice": "optional"}
KIND_BY_RELEVANCE = {
    "core": "core",
    "supporting": "support",
    "offer": "goal",
    "optional": "optional",
}

STRENGTH_LABELS = {
    "strong": "Strong hook",
    "moderate": "Good hook",
    "weak": "Weaker hook",
    "none": "Not personalised",
}


def _source_title(source):
    return source.get("title") or source.get("publisher") or "Source"


def references(run):
    """Numbered sources in the order the reader meets them; your goal is "G"."""
    result = run.get("result") or {}
    sources = {s.get("id"): s for s in result.get("sources") or run.get("source_records") or []}
    order = []

    def add(source_id):
        if source_id and source_id in sources and source_id not in order:
            order.append(source_id)

    draft = run.get("draft") or {}
    for segment in (draft.get("check") or {}).get("segments", []):
        for support in segment.get("support_ids", []):
            add(support)
    hook = result.get("hook") or {}
    for source_id in hook.get("source_ids", []):
        add(source_id)
    for signal in result.get("candidate_signals") or []:
        add(signal.get("source_id"))
    add(((result.get("identity") or {}).get("selected") or {}).get("source_id"))
    for signal in result.get("rejected_signals") or []:
        add(signal.get("source_id"))  # "Not used" findings still show where they came from
    numbered = {source_id: str(number) for number, source_id in enumerate(order, 1)}
    listing = [
        {
            "n": numbered[source_id],
            "id": source_id,
            "title": _source_title(sources[source_id]),
            "url": sources[source_id].get("url", ""),
            "excerpt": sources[source_id].get("access_status") == "excerpt",
            "fixture": bool(sources[source_id].get("fixture")),
        }
        for source_id in order
    ]
    return numbered, listing


def _piece(segment, numbered):
    kinds = segment.get("kinds") or []
    supports = segment.get("support_ids") or []
    refs = [numbered[s] for s in supports if s in numbered]
    if any(s not in numbered and s != "as-entered" for s in supports):
        refs.append("G")
    relevance = segment.get("relevance")
    if segment.get("status") == "error":
        kind = "block"
    elif segment.get("role") == "cta":
        kind = "plain"
    elif relevance in KIND_BY_RELEVANCE:
        kind = KIND_BY_RELEVANCE[relevance]
    elif segment.get("status") in KIND_BY_STATUS:
        kind = KIND_BY_STATUS[segment["status"]]
    elif "inference" in kinds:
        kind = "optional"  # a cautious "may" or "might": a judgement, not a sourced fact
    elif "fact" in kinds or any(s in numbered for s in supports):
        kind = "support"
    elif supports:
        kind = "goal"
    else:
        kind = "plain"
    if kind == "optional" and not segment.get("issues"):
        return {
            "text": segment["text"],
            "kind": kind,
            "refs": list(dict.fromkeys(refs)),
            "note": segment.get("why") or "Could be cut without losing anything.",
        }
    if kind in ("core", "support", "goal") and segment.get("why") and not segment.get("issues"):
        return {
            "text": segment["text"],
            "kind": kind,
            "refs": list(dict.fromkeys(refs)),
            "note": segment["why"],
        }
    messages = [i["message"] for i in segment.get("issues", []) if i.get("severity") == "error"]
    if not messages:
        messages = [i["message"] for i in segment.get("issues", [])]
    return {
        "text": segment["text"],
        "kind": kind,
        "refs": list(dict.fromkeys(refs)),
        "note": messages[0] if messages else "",
    }


def annotate(run):
    """Subject and body split into plain text and highlighted sentences, in order."""
    draft = run.get("draft") or {}
    numbered, _ = references(run)
    segments = (draft.get("check") or {}).get("segments", [])
    subject = next((s for s in segments if s.get("part") == "subject"), None)
    body, text, cursor = [], draft.get("body", ""), 0
    for segment in segments:
        if segment.get("part") != "body":
            continue
        at = text.find(segment["text"], cursor)
        if at < 0:
            continue
        if at > cursor:
            body.append({"text": text[cursor:at], "kind": "gap", "refs": [], "note": ""})
        if segment.get("role") in ("greeting", "signoff"):
            body.append({"text": segment["text"], "kind": "plain", "refs": [], "note": ""})
        else:
            piece = _piece(segment, numbered)
            # Content sentences can be edited or removed where they stand; the fixed
            # closing question cannot.
            piece["edit"] = segment.get("role") != "cta"
            body.append(piece)
        cursor = at + len(segment["text"])
    if cursor < len(text):
        body.append({"text": text[cursor:], "kind": "gap", "refs": [], "note": ""})
    return {
        "subject": _piece(subject, numbered) if subject else None,
        "body": body,
    }


ANGLE_LABELS = {
    "person": "About them",
    "company": "Company news",
    "growth": "Growth signal",
    "goal": "Fits your goal",
}


def _used_sources(run):
    """Sources the current email actually relies on, sentence by sentence."""
    draft = run.get("draft") or {}
    used = set()
    for segment in (draft.get("check") or {}).get("segments", []):
        used.update(segment.get("support_ids") or [])
    return used


def facts(run):
    """Everything found, in three groups the reviewer can act on.

    chosen    the hook and other checked facts: ticked, used for the email
    extra     true facts kept aside (context, earlier roles): unticked, yours to add
    set_aside not usable, each with the reason (old, unsupported, someone else…)
    """
    result = run.get("result") or {}
    numbered, _ = references(run)
    used = _used_sources(run)
    seen = set()

    def item(text, source_id, label, tone, why="", tickable=True, locked=False):
        key = " ".join(str(text).split()).lower()[:160]
        if not text or key in seen:
            return None
        seen.add(key)
        return {
            "text": text,
            "source_id": source_id or "",
            "ref": numbered.get(source_id, ""),
            "label": label,
            "tone": tone,
            "why": why,
            "tickable": tickable and bool(source_id),
            "locked": locked,
            "in_email": bool(source_id) and source_id in used,
        }

    chosen, extra, set_aside = [], [], []
    hook = result.get("hook") or {}
    if hook:
        strength = hook.get("strength", "moderate")
        tone = {"strong": "fact", "moderate": "fact", "weak": "call", "none": "block"}[strength]
        entry = item(
            hook.get("summary"),
            (hook.get("source_ids") or [""])[0],
            STRENGTH_LABELS.get(strength, "Hook"),
            tone,
            (hook.get("judgement") or {}).get("verdict", ""),
            locked=True,
        )
        if entry:
            chosen.append(entry)
    for signal in result.get("candidate_signals") or []:
        entry = item(
            signal.get("quote"),
            signal.get("source_id"),
            ANGLE_LABELS.get(signal.get("angle"), "Also found"),
            "fact",
        )
        if entry:
            chosen.append(entry)
    selected = (result.get("identity") or {}).get("selected") or {}
    entry = item(
        selected.get("quote"), selected.get("source_id"), "Who they are", "fact", tickable=False
    )
    if entry:
        chosen.append(entry)
    for signal in result.get("context_signals") or []:
        background = signal.get("category") == "background"
        entry = item(
            signal.get("quote"),
            signal.get("source_id"),
            "Earlier role" if background else "Context",
            "goal",
            "About their past, not their current job."
            if background
            else "True and sourced, but not linked to what you offer.",
        )
        if entry:
            extra.append(entry)
    for signal in result.get("rejected_signals") or []:
        reason = str(signal.get("reason", ""))
        if any(word in reason for word in ("Another account", "Duplicate", "syndicated")):
            continue
        entry = item(
            signal.get("quote"),
            signal.get("source_id"),
            "Set aside",
            "call",
            reason,
            tickable=False,
        )
        if entry:
            set_aside.append(entry)
    return {"chosen": chosen, "extra": extra, "set_aside": set_aside[:6]}


def findings(run):
    """Flat list, most useful first (kept for callers that want one list)."""
    groups = facts(run)
    flat = []
    for entry in groups["chosen"] + groups["extra"]:
        flat.append({**entry, "why": entry["why"]})
    for entry in groups["set_aside"]:
        flat.append({**entry, "label": "Not used"})
    return flat[:8]


# ---- Live run view: saved stage events as five plain-language phases -----------------

PHASES = [
    ("person", "Find the person"),
    ("news", "Find news about them"),
    ("hook", "Choose the hook"),
    ("email", "Write the email"),
    ("check", "Check every sentence"),
]


def _step(name, first, detail=""):
    """(phase, plain label) for a saved stage name; (None, None) for wrapper events."""
    low = name.lower()
    if low == "research sources" and "stopped early" not in detail.lower():
        return None, None  # spans the whole research; its parts are shown instead
    if low in ("save inputs", "check prospect", "research sources", "research stopped"):
        return "person", "Getting started" if low in ("save inputs", "check prospect") else (
            "Research stopped early"
        )
    if low.startswith("identity evidence") and "no model step" in detail.lower():
        return "person", "Confirmed from the search results"
    if low.startswith("identity search"):
        return "person", f"Searching the web for {first}"
    if low.startswith("identity extract") or low.startswith("followup extract"):
        return "person", "Reading pages that mention them"
    if low.startswith("identity evidence") or low.startswith("followup evidence"):
        return "person", "Reading what those pages say about them"
    if low.startswith("followup search"):
        return "person", "Searching again with different words"
    if low == "match identity":
        return "person", "Confirming it is the right person"
    if low.startswith("signal-followup") or low.startswith("signal followup"):
        return "news", "Searching again for news"
    if low.startswith("signal search"):
        return "news", "Searching for recent news"
    if low.startswith("signal extract"):
        return "news", "Reading news pages"
    if low.startswith("signal evidence"):
        return "news", "Picking out dated facts"
    if low == "choose a hook":
        return "hook", "Choosing the strongest hook"
    if low in ("draft email", "draft model request", "template draft"):
        return (
            "email",
            "Writing a plain version" if low == "template draft" else "Writing the email",
        )
    if low in ("repair draft", "repair model request"):
        return "check", "Fixing a flagged sentence"
    if low in ("prepare result", "save research result"):
        return "check", "Saving the result"
    return None, name


def timeline(run):
    """Phases with their steps, for the live run view and the finished summary."""
    first = (run.get("prospect", {}).get("name") or "them").split()[0]
    running = run.get("execution_status") in ("queued", "running")
    drafting = bool(run.get("limits", {}).get("write_draft", 1)) and not (
        run.get("campaign") or {}
    ).get("no_goal")
    steps = {key: [] for key, _ in PHASES}
    last_phase = "person"
    for event in run.get("stages") or []:
        phase, label = _step(event.get("name", ""), first, event.get("detail", ""))
        if label is None:
            continue
        phase = phase or last_phase
        last_phase = phase
        bucket = steps[phase]
        if bucket and bucket[-1]["label"] == label:
            step = bucket[-1]
        else:
            step = {"label": label, "count": 0, "status": "started", "detail": ""}
            bucket.append(step)
        if event.get("status") == "started":
            step["count"] += 1
        step["status"] = event.get("status", "started")
        if event.get("status") == "failed" or not step["detail"]:
            step["detail"] = event.get("detail", "")
    draft = run.get("draft") or {}
    if draft and not any("sentence" in s["label"] for s in steps["check"]):
        ok = (draft.get("check") or {}).get("ok")
        steps["check"].insert(
            0,
            {
                "label": "Every sentence passed" if ok else "Some sentences need a fix",
                "count": 1,
                "status": "completed" if ok else "failed",
                "detail": "",
            },
        )
    order = [key for key, _ in PHASES]
    reached = max((order.index(k) for k in order if steps[k]), default=0)
    phases = []
    for index, (key, title) in enumerate(PHASES):
        has = bool(steps[key])
        if key in ("email", "check") and not drafting and not draft:
            state = "skipped"
        elif running and index == reached:
            state = "current"
        elif has or index < reached:
            state = "done"
        else:
            state = "todo"
        if any(s["status"] == "failed" for s in steps[key]) and state == "done":
            state = "warn"
        for step in steps[key]:
            if step["label"].startswith("Reading") and step["count"] > 1:
                step["label"] = f"{step['label']} ({step['count']})"
        phases.append({"key": key, "title": title, "state": state, "steps": steps[key]})
    return phases


# ---- Dashboard: what all runs add up to ------------------------------------------------


def _first_output(run):
    draft = run.get("draft") or {}
    if draft.get("subject"):
        return "Email: " + draft["subject"]
    hook = (run.get("result") or {}).get("hook") or {}
    if hook.get("summary"):
        return hook["summary"]
    return ""


def dashboard(runs):
    """Counts, hook strength mix and cost across the given runs."""
    counts = {"total": len(runs), "running": 0, "review": 0, "approved": 0, "attention": 0}
    strengths = {"strong": 0, "moderate": 0, "weak": 0, "none": 0}
    spent = 0
    live_runs = 0
    for run in runs:
        state = (run.get("review") or {}).get("state") if run.get("draft") else None
        if run.get("execution_status") in ("queued", "running"):
            counts["running"] += 1
        elif state == "approved":
            counts["approved"] += 1
        elif state == "ready_for_review" or run.get("business_outcome") == "research_ready":
            counts["review"] += 1
        else:
            counts["attention"] += 1
        strength = ((run.get("result") or {}).get("hook") or {}).get("strength")
        if strength in strengths:
            strengths[strength] += 1
        if run.get("mode") == "live":
            live_runs += 1
            spent += (run.get("usage") or {}).get("settled_micro", 0)
        run["first_output"] = _first_output(run)
    with_hook = sum(strengths.values())
    return {
        "counts": counts,
        "strengths": strengths,
        "with_hook": with_hook,
        "spent": spent / 1_000_000,
        "average": (spent / live_runs / 1_000_000) if live_runs else 0,
        "live_runs": live_runs,
    }


def duration(run):
    """Elapsed time as m:ss from start to the last saved change."""
    from datetime import datetime

    try:
        start = datetime.fromisoformat(str(run.get("created_at")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(run.get("updated_at")).replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60}:{seconds % 60:02d}"
