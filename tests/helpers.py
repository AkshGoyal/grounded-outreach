"""Submit the real launch form after reviewing it, as the browser does."""

import re


def confirm_launch(client, path, **kwargs):
    page = client.get(path)
    token = re.search(r'name="launch_token" value="([^"]+)"', page.text)
    return client.post(
        path, data={"confirm_send": "on", "launch_token": token[1] if token else ""}, **kwargs
    )


def confirm_draft_test(client, draft_id, to):
    page = client.get(f"/drafts/{draft_id}").text
    values = {
        name: re.search(r'name="' + name + r'" value="([^"]+)"', page)[1]
        for name in ("test_nonce", "test_token")
    }
    return client.post(f"/drafts/{draft_id}/test-send", data=values | {"to": to, "confirmed": "on"})
