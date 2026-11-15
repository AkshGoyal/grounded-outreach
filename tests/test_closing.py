"""A fixed closing, and an opening that leads into it without repeating it.

The closing below is the operator's wording with made-up contact details —
the real numbers and registration details never enter the repository.
"""

import subprocess
from pathlib import Path

import pytest

from outreach.campaigns import load_closing
from outreach.core.dispatch import OPT_OUT, email_tail
from outreach.core.drafting import (
    Draft,
    DraftSentence,
    DraftVerdict,
    build_prompt,
    check_draft,
)
from outreach.core.flow import closing_vocabulary, flow_problem
from outreach.core.grounding import Verdict
from outreach.core.review import storable_body

CLOSING = """We would be pleased to send a complimentary sample pack to your unit so your \
sampling and production teams can test the runnability and shade results directly on your line.

If you would like to explore our full product range and manufacturing standards before testing, \
please feel free to visit our portal at https://example.in.

Kindly let us know if we may dispatch these trial samples, along with the preferred postal \
address and contact person to mark the courier to.

Thank you for your consideration, and we look forward to the possibility of working together.

Warm regards,

Test Person
Mobile: +91 00000 00000"""

COPY = "Star Threads manufactures ready-for-dyeing (RFD) cotton sewing thread in Ludhiana."
EVIDENCE = {
    "City": "Tiruppur",
    "What they do (verified)": "Knitted cotton fabric and garment dyeing for export",
    "Contact person": "R. Subramanian",
}


def _problem(sentence, earlier=(), closing=CLOSING):
    return flow_problem(
        sentence,
        earlier=list(earlier),
        closing=closing,
        closing_words=closing_vocabulary(closing, campaign_copy=COPY) if closing else set(),
    )


# --- what the opening must not do, because the closing does it -------------


@pytest.mark.parametrize(
    "sentence",
    [
        "We would be happy to send you some samples.",
        "You can see our range at https://example.in.",
        "Please visit our website for details.",
        "Thank you for your time.",
        "We look forward to hearing from you.",
        "Warm regards, Aksh",
        "Would you be interested in trying our thread?",
        "Your production teams could check the runnability and shade on your line.",
    ],
)
def test_the_opening_does_not_do_the_closings_job(sentence):
    assert _problem(sentence) is not None, sentence


def test_a_specific_point_about_them_is_kept():
    sentence = (
        "Since you knit cotton fabric and dye garments for export in Tiruppur, thread that "
        "takes the same dye bath as the garment could keep your seams matching."
    )
    assert _problem(sentence) is None


def test_an_introduction_is_kept():
    sentence = (
        "My name is Aksh Goyal, and I write on behalf of Star Threads, which manufactures "
        "ready-for-dyeing cotton sewing thread in Ludhiana."
    )
    assert _problem(sentence) is None


def test_saying_the_same_thing_twice_is_caught_even_without_a_closing():
    first = "We manufacture ready-for-dyeing cotton sewing thread in Ludhiana."
    second = "In Ludhiana we manufacture cotton sewing thread that is ready for dyeing."
    assert _problem(second, earlier=[first], closing=None) is not None


def test_without_a_closing_the_opening_may_offer_samples():
    """Campaigns with no fixed closing still work as before."""
    assert _problem("We would be happy to send you a sample.", closing=None) is None


# --- how it plays out in a whole draft --------------------------------------


def _draft(*sentences):
    return Draft(
        subject="RFD cotton sewing thread from Ludhiana",
        sentences=[DraftSentence(text=t, cites=c) for t, c in sentences],
    )


def _check(draft, closing=CLOSING):
    return check_draft(
        draft, evidence=EVIDENCE, company="Kohinoor Knits", campaign_copy=COPY, closing=closing
    )


def test_repeated_lines_are_removed_but_do_not_block():
    result = _check(
        _draft(
            ("Dear Mr. Subramanian,", "Contact person"),
            (
                "You knit cotton fabric and dye garments for export in Tiruppur.",
                "What they do (verified)",
            ),
            ("We would be glad to send you samples to test.", None),
        )
    )
    assert result.verdict is DraftVerdict.CLEAN
    assert [c.verdict for c in result.checks][-1] is Verdict.REPEATS
    assert "samples" not in storable_body(result)
    assert "Tiruppur" in storable_body(result)


def test_an_invented_claim_is_still_blocked_before_flow_is_considered():
    result = _check(_draft(("Your Coimbatore unit would suit this.", "City")))
    assert result.verdict is DraftVerdict.BLOCKED
    assert result.checks[0].verdict is Verdict.UNSUPPORTED


# --- the prompt -------------------------------------------------------------


def test_with_a_closing_the_model_is_asked_for_the_opening_only():
    prompt = build_prompt(
        company="Kohinoor Knits",
        evidence=EVIDENCE,
        campaign_copy=COPY,
        sender="Aksh Goyal",
        closing=CLOSING,
    )
    assert "writing the opening" in prompt
    assert "complimentary sample pack" in prompt, "it is shown the closing, to lead into it"
    assert "Do not repeat, paraphrase or anticipate" in prompt
    assert "{" not in prompt and "}" not in prompt


def test_without_a_closing_the_full_email_prompt_is_used():
    prompt = build_prompt(company="X", evidence=EVIDENCE, campaign_copy=COPY, sender="A")
    assert "writing the opening" not in prompt
    assert "current campaign alone determines its purpose" in prompt


# --- what is actually sent -------------------------------------------------


def test_the_closing_is_sent_word_for_word_with_a_way_to_opt_out():
    tail = email_tail(closing=CLOSING, name="n", company="c", address="a")
    assert tail.startswith(CLOSING)
    assert tail.endswith(OPT_OUT)


def test_without_a_closing_the_standard_footer_is_used():
    tail = email_tail(closing=None, name="Aksh", company="Star Threads", address="Ludhiana")
    assert "Ludhiana" in tail and "reply and say so" in tail


def test_notes_in_the_closing_file_are_never_emailed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "rfd.closing.md").write_text(
        "<!-- remember to update the GST number -->\nWarm regards,\nAksh"
    )
    closing = load_closing("rfd")
    assert "remember" not in closing
    assert closing == "Warm regards,\nAksh"


def test_the_send_uses_the_closing_not_the_footer(store):
    from datetime import UTC, datetime

    from outreach.core.dispatch import dispatch, plan
    from outreach.core.models import Campaign, Contact, DraftStatus
    from tests.fakes.mail import FakeMailbox

    store.add_campaign(Campaign(id="c", name="c", created_at=datetime.now(UTC)))
    cid = store.add_contact(Contact(campaign_id="c", email="b@mill.example"))
    did = store.save_draft(
        contact_id=cid, model="m", subject="s", body="Dear Sir/Madam,", verdict="clean", checks=[]
    )
    store.set_draft_status(did, DraftStatus.APPROVED)
    mailbox = FakeMailbox()
    dispatch(
        store,
        mailbox,
        plan(store, "c", daily_cap=10, closing=CLOSING, campaign_copy=COPY),
        sender_email="a@example.in",
        tail=email_tail(closing=CLOSING, name="n", company="c", address="a"),
        pause=lambda: None,
    )
    body = mailbox.sent[0].body_text
    assert body.startswith("Dear Sir/Madam,")
    assert "complimentary sample pack" in body
    assert body.endswith(OPT_OUT)


# --- the real closing never reaches git -------------------------------------


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        ("campaigns/rfd-buyers-q4.closing.md", True),
        ("campaigns/rfd-buyers-q4.md", True),
        ("campaigns/example.closing.md", False),
        ("campaigns/example.md", False),
    ],
)
def test_real_campaign_files_cannot_be_committed(path, ignored):
    """A real closing holds mobile numbers and registration details."""
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=repo, check=False)
    assert (result.returncode == 0) is ignored


# --- drafts written before the closing existed -------------------------------


@pytest.fixture
def campaign_with_old_drafts(monkeypatch, tmp_path):
    """Three contacts: one already emailed, one with an approved draft and one
    with a draft in review — both written before the closing existed."""
    import os

    from outreach.adapters.db import connect
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.cli import main
    from outreach.core.models import DraftStatus, MessageStatus
    from tests.fakes.llm import FakeLLM

    for name in list(os.environ):
        if name.startswith("OUTREACH_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    for k, v in {
        "DB_PATH": str(tmp_path / "x.db"),
        "OPENROUTER_API_KEY": "k",
        "SENDER_NAME": "Aksh Goyal",
        "SENDER_EMAIL": "aksh@example.in",
    }.items():
        monkeypatch.setenv(f"OUTREACH_{k}", v)
    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "rfd.md").write_text(COPY)
    sheet = tmp_path / "s.csv"
    sheet.write_text(
        "Company,Email\nSent Mill,sent@m.example\nOld Mill,old@m.example\n"
        "Review Mill,review@m.example\n"
    )
    main(["import", str(sheet), "--campaign", "rfd", "--commit"])

    old = Draft(
        subject="Old draft",
        sentences=[
            DraftSentence(text="We would love to send you free samples."),
            DraftSentence(text="Best regards, Aksh"),
        ],
    )
    monkeypatch.setattr("outreach.cli.build_llm", lambda s, m=None: FakeLLM([old] * 10))
    main(["draft", "--campaign", "rfd", "--save"])

    store = SqliteStore(connect(tmp_path / "x.db"))
    drafts = {d.company: d for d in store.drafts_in_campaign("rfd")}
    store.set_draft_status(drafts["Old Mill"].id, DraftStatus.APPROVED)
    store.record_pending_send(
        contact_id=drafts["Sent Mill"].contact_id,
        message_id="<m@x>",
        recipient_email="sent@m.example",
        subject="s",
        body_text="b",
    )
    store.mark_send_outcome("<m@x>", MessageStatus.SENT)
    store.set_draft_status(drafts["Sent Mill"].id, DraftStatus.SENT)

    (tmp_path / "campaigns" / "rfd.closing.md").write_text(CLOSING)
    new = Draft(subject="New draft", sentences=[DraftSentence(text="Dear Sir/Madam,")])
    monkeypatch.setattr("outreach.cli.build_llm", lambda s, m=None: FakeLLM([new] * 10))
    return store, main


def test_redraft_replaces_every_unsent_draft(campaign_with_old_drafts):
    from outreach.core.dispatch import plan

    store, main = campaign_with_old_drafts
    assert main(["draft", "--campaign", "rfd", "--save", "--redraft"]) == 0

    live = [d for d in store.drafts_in_campaign("rfd") if d.status.value in ("review", "approved")]
    assert sorted(d.company for d in live) == ["Old Mill", "Review Mill"]
    assert all(d.subject == "New draft" for d in live)
    assert not any(
        p.will_send for p in plan(store, "rfd", daily_cap=10, closing=CLOSING, campaign_copy=COPY)
    ), "the old approved draft must not go out with the closing under it"


def test_redraft_leaves_anyone_already_emailed_alone(campaign_with_old_drafts):
    store, main = campaign_with_old_drafts
    main(["draft", "--campaign", "rfd", "--save", "--redraft"])
    sent_mill = [d for d in store.drafts_in_campaign("rfd") if d.company == "Sent Mill"]
    assert [d.subject for d in sent_mill] == ["Old draft"]


def test_redraft_needs_save(campaign_with_old_drafts):
    _, main = campaign_with_old_drafts
    assert main(["draft", "--campaign", "rfd", "--redraft"]) == 1


# --- a draft written before the closing existed (D-020) ----------------------
#
# The case that reached an inbox: an opening from the full-email prompt, with
# its own sample offer, question and sign-off, and the closing added under it.

OLD_BODY = """Hello Ravi,

I am Test Person from Example Threads, a maker of industrial sewing thread in Ludhiana.

I noticed that Sunrise Denims runs both denim production and garment washing.

We make unbleached cotton sewing thread that takes dye in the same bath, and we would like \
to send you sample cones at no cost.

Would you be open to evaluating a sample?

Best regards, Test Person, Example Threads."""


def test_every_repeated_line_in_an_old_draft_is_found():
    from outreach.core.flow import repeated_lines

    found = [line for line, _ in repeated_lines(OLD_BODY, closing=CLOSING, campaign_copy=COPY)]
    assert found == [
        "We make unbleached cotton sewing thread that takes dye in the same bath, and we would "
        "like to send you sample cones at no cost.",
        "Would you be open to evaluating a sample?",
        "Best regards, Test Person, Example Threads.",
    ]


def test_without_a_closing_an_old_draft_is_left_alone():
    from outreach.core.flow import repeated_lines

    assert repeated_lines(OLD_BODY, closing=None, campaign_copy=COPY) == []


def test_an_approved_old_draft_is_held_back_at_send_time(store):
    from datetime import UTC, datetime

    from outreach.core.dispatch import plan
    from outreach.core.models import Campaign, Contact, DraftStatus

    store.add_campaign(Campaign(id="c", name="c", created_at=datetime.now(UTC)))
    cid = store.add_contact(Contact(campaign_id="c", email="b@mill.example"))
    did = store.save_draft(
        contact_id=cid, model="m", subject="s", body=OLD_BODY, verdict="clean", checks=[]
    )
    store.set_draft_status(did, DraftStatus.APPROVED)

    [held] = plan(store, "c", daily_cap=10, closing=CLOSING, campaign_copy=COPY)
    assert not held.will_send
    assert "repeats" in held.skip and "+2 more" in held.skip

    [fine] = plan(store, "c", daily_cap=10, closing=None, campaign_copy=COPY)
    assert fine.will_send, "without a closing there is nothing for it to repeat"


def test_a_draft_that_repeats_the_closing_cannot_be_approved():
    from outreach.core.review import approval_blocker, recheck

    checked = recheck(
        "RFD cotton sewing thread from Ludhiana",
        OLD_BODY,
        evidence={"Company": "Sunrise Denims"},
        company="Sunrise Denims",
        campaign_copy=COPY,
        sender="Test Person",
        closing=CLOSING,
    )
    blocker = approval_blocker(checked)
    assert blocker and "repeat" in blocker and "Best regards" in blocker


def test_send_test_refuses_an_old_draft_before_connecting(campaign_with_old_drafts, monkeypatch):
    store, main = campaign_with_old_drafts
    for k, v in {
        "MAIL_SMTP_HOST": "smtp.example.in",
        "MAIL_USERNAME": "u",
        "MAIL_PASSWORD": "p",
        "SENDER_COMPANY": "Example Threads",
        "SENDER_ADDRESS": "Ludhiana",
    }.items():
        monkeypatch.setenv(f"OUTREACH_{k}", v)

    def no_connection(*a, **k):
        raise AssertionError("must refuse before connecting")

    monkeypatch.setattr("outreach.adapters.mail_smtp_imap.SmtpImapMailbox", no_connection)
    draft = next(d for d in store.drafts_in_campaign("rfd") if d.company == "Review Mill")
    assert main(["send-test", "--to", "me@example.com", "--draft", str(draft.id)]) == 1


def test_a_preview_prints_one_whole_email_with_the_closing(campaign_with_old_drafts, capsys):
    _, main = campaign_with_old_drafts
    capsys.readouterr()
    assert main(["draft", "--campaign", "rfd", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert out.count("The whole email") == 1
    assert "Thank you for your consideration" in out
    assert OPT_OUT in out
