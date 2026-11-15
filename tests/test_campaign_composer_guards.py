"""Route-level fixed text and generation guards; every external service is fake."""

import re

from outreach.campaigns import load_copy
from tests.test_campaign_isolation_composer import composed_workspace as composed_workspace
from tests.test_platform import db_for, verified_account


def test_fixed_outer_whitespace_comments_and_crlf_survive_review_save(composed_workspace):
    settings, _, client, _, box, _ = composed_workspace
    source = "[KEEP]\n  Hello {{name}},\n<!-- literal -->\n\n  Best regards,\nKeshav  \n[/KEEP]"
    assert (
        client.post("/campaigns/job-search/message", data={"message_prompt": source}).status_code
        == 200
    )
    assert load_copy("job-search") == source
    client.post("/campaigns/job-search/draft")
    with db_for(settings) as db:
        draft = db.store.drafts_in_campaign("job-search")[0]
    expected = "  Hello Alex Job Search,\n<!-- literal -->\n\n  Best regards,\nKeshav  "
    assert draft.body == expected
    client.post(
        f"/drafts/{draft.id}",
        data={"subject": draft.subject, "body": expected.replace("\n", "\r\n"), "action": "save"},
    )
    with db_for(settings) as db:
        saved = db.store.get_draft(draft.id)
        assert saved.body == expected
        assert not any("fixed KEEP block" in (c.get("reason") or "") for c in saved.checks)
    assert not box.sent


def test_foreground_generation_blocks_configuration_changes(composed_workspace):
    _, app, client, llm, box, _ = composed_workspace
    original = load_copy("job-search")
    responses = []

    def edit_while_model_is_working():
        assert app.state.drafter.busy
        responses.append(
            client.post(
                "/campaigns/job-search/message",
                data={"message_prompt": "Write different sales outreach."},
            )
        )

    llm.callback = edit_while_model_is_working
    client.post("/campaigns/job-search/draft")
    assert responses[0].status_code == 400
    assert load_copy("job-search") == original and not app.state.drafter.busy
    assert not box.sent


def test_test_to_self_refuses_altered_fixed_content(composed_workspace):
    settings, _, client, _, box, _ = composed_workspace
    with db_for(settings) as db:
        account = verified_account(db, settings)
    client.post(
        "/campaigns/job-search/settings", data={"name": "Job Search", "account_id": account}
    )
    client.post("/campaigns/job-search/draft")
    with db_for(settings) as db:
        draft = db.store.drafts_in_campaign("job-search")[0]
        db.store.update_draft(
            draft.id,
            subject=draft.subject,
            body=draft.body.replace(
                "I have already applied through the careers portal.", "Changed wording."
            ),
            verdict="clean",
            checks=[],
        )
    page = client.get(f"/drafts/{draft.id}").text
    token = {
        key: re.search(r'name="' + key + r'" value="([^\"]+)"', page).group(1)
        for key in ("test_nonce", "test_token")
    }
    response = client.post(
        f"/drafts/{draft.id}/test-send",
        data={
            **token,
            "to": "sender@gmail.com",
            "confirmed": "on",
        },
    )
    assert "fixed KEEP block" in response.text
    with db_for(settings) as db:
        assert not db.rows("SELECT * FROM draft_test_runs")
    assert not box.sent


def test_unavailable_fixed_variable_is_clear_and_free(composed_workspace):
    settings, _, client, llm, box, _ = composed_workspace
    with db_for(settings) as db:
        db.conn.execute("UPDATE contacts SET evidence='{}' WHERE campaign_id='job-search'")
    response = client.post("/campaigns/job-search/draft")
    assert "No reviewed recipient value is available for {{name}}" in response.text
    assert not llm.prompts and not box.sent
    with db_for(settings) as db:
        assert not db.store.drafts_in_campaign("job-search")


def test_short_fixed_only_editor_needs_no_hidden_fields(composed_workspace):
    settings, _, client, llm, box, _ = composed_workspace
    source = "[KEEP]\nHi.\n[/KEEP]"
    response = client.post("/campaigns/job-search/message", data={"message_prompt": source})
    assert response.status_code == 200
    client.post("/campaigns/job-search/draft")
    with db_for(settings) as db:
        assert db.store.drafts_in_campaign("job-search")[0].body == "Hi."
    assert len(llm.prompts) == 1 and not box.sent
