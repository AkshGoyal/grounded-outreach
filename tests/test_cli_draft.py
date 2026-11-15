"""`outreach draft`, end to end, with a fake model.

A unit test on `draft_email` would not have caught the bug this file guards
against — the CLI called it with an argument it did not accept, and only
running the command revealed that. So this drives the command itself.
"""

import pytest

from outreach.cli import main
from outreach.core.drafting import Draft, DraftSentence
from tests.fakes.llm import FakeLLM


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    """A campaign with contacts, campaign copy, and a fake model."""
    for name in list(__import__("os").environ):
        if name.startswith("OUTREACH_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setenv("OUTREACH_OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OUTREACH_SENDER_NAME", "Aksh Goyal")
    monkeypatch.setenv("OUTREACH_SENDER_EMAIL", "aksh@example.com")

    (tmp_path / "campaigns").mkdir()
    (tmp_path / "campaigns" / "rfd.md").write_text(
        "Star Threads makes RFD cotton sewing thread in Ludhiana. We send samples."
    )

    fixture = __import__("pathlib").Path(__file__).parent / "fixtures" / "sample_contacts.csv"
    assert main(["import", str(fixture), "--campaign", "rfd", "--commit"]) == 0
    return tmp_path


def _fake_model(monkeypatch, *sentences, subject="RFD cotton thread"):
    """Replace the real adapter. Nothing here touches the network."""
    draft = Draft(subject=subject, sentences=[DraftSentence(text=t, cites=c) for t, c in sentences])

    def build(settings, model=None):
        return FakeLLM(responses=[draft] * 20)

    monkeypatch.setattr("outreach.cli.build_llm", build)


def test_the_draft_command_runs(workspace, monkeypatch, capsys):
    """The regression: the CLI called draft_email with an argument it did not
    take, and only a real run revealed it."""
    _fake_model(monkeypatch, ("Hello.", None), ("We make RFD cotton thread.", None))
    assert main(["draft", "--campaign", "rfd", "--limit", "2"]) == 0
    assert "Nothing was written" in capsys.readouterr().out


def test_it_shows_the_verdict_for_each_line(workspace, monkeypatch, capsys):
    _fake_model(
        monkeypatch,
        ("You are in Tiruppur.", "City"),
        ("I saw your Coimbatore unit.", "City"),
    )
    main(["draft", "--campaign", "rfd", "--limit", "1"])
    out = capsys.readouterr().out
    assert "BLOCKED" in out
    assert "coimbatore" in out.lower()


def test_it_runs_every_model_it_is_given(workspace, monkeypatch, capsys):
    _fake_model(monkeypatch, ("Hello.", None))
    main(["draft", "--campaign", "rfd", "--limit", "1", "--model", "a/one", "--model", "b/two"])
    out = capsys.readouterr().out
    assert "a/one" in out and "b/two" in out


def test_it_skips_anyone_on_the_do_not_contact_list(workspace, monkeypatch, capsys):
    from outreach.adapters.db import connect
    from outreach.adapters.store_sqlite import SqliteStore
    from outreach.core.models import SuppressionReason

    SqliteStore(connect(workspace / "x.db")).add_suppression(
        "purchase@kohinoorknits.example", SuppressionReason.UNSUBSCRIBE
    )
    _fake_model(monkeypatch, ("Hello.", None))
    main(["draft", "--campaign", "rfd", "--limit", "4"])
    assert "on the do-not-contact list" in capsys.readouterr().out


def test_a_missing_campaign_copy_file_is_explained(workspace, monkeypatch, capsys):
    _fake_model(monkeypatch, ("Hello.", None))
    assert main(["draft", "--campaign", "nosuch"]) == 1
    assert "No campaign copy" in capsys.readouterr().err


def test_a_blocked_subject_shows_why(workspace, monkeypatch, capsys):
    """On the first real run a subject was marked XX with no reason printed."""
    _fake_model(monkeypatch, ("Hello.", None), subject="About your Coimbatore unit")
    main(["draft", "--campaign", "rfd", "--limit", "1"])
    out = capsys.readouterr().out
    assert "SUBJECT" in out and "coimbatore" in out.lower()


def test_one_failing_contact_does_not_end_the_run(workspace, monkeypatch, capsys):
    from outreach.ports.llm import LLMError

    calls = {"n": 0}

    class Flaky:
        def generate(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMError("the model declined")
            return kwargs["schema"].model_validate(
                {"subject": "RFD thread", "sentences": [{"text": "Hello.", "cites": None}]}
            )

    monkeypatch.setattr("outreach.cli.build_llm", lambda s, m=None: Flaky())
    assert main(["draft", "--campaign", "rfd", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "could not draft" in out
    assert calls["n"] == 2, "the second contact was still drafted"
