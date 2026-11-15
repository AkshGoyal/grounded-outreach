"""Authentication metadata checks must never make a paid request or expose keys."""

import httpx
import pytest
from fastapi.testclient import TestClient

from outreach.adapters.provider_connection import check_openrouter
from outreach.config import ConfigError
from outreach.web.app import create_app


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, {"data": {"label": "private-provider-label", "limit_remaining": 2}}, "accepted"),
        (200, {"data": {"limit_remaining": 0}}, "limit is exhausted"),
        (200, {"data": {"is_management_key": True}}, "management key"),
        (401, {"error": "private-provider-message"}, "refused this key"),
        (500, {"error": "private-provider-message"}, "Could not check"),
        (200, {"data": None}, "Could not check"),
        (302, {}, "Could not check"),
    ],
)
def test_check_only_gets_metadata_and_sanitizes_results(settings, status, body, expected):
    config = settings.model_copy(update={"openrouter_api_key": "fictional-private-key"})
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        try:
            result = check_openrouter(config, client=client)
        except ConfigError as exc:
            result = str(exc)
    assert expected in result
    assert not any(value in result for value in ("private-provider", "fictional-private-key"))
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert str(calls[0].url) == "https://openrouter.ai/api/v1/key"
    assert calls[0].headers["authorization"] == "Bearer fictional-private-key"
    assert not calls[0].content


def test_restricted_or_missing_key_never_contacts_provider(settings):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network request"))
    ) as client:
        for values in (
            {"local_network_restricted": True, "openrouter_api_key": "fake"},
            {"openrouter_api_key": None},
        ):
            with pytest.raises(ConfigError):
                check_openrouter(settings.model_copy(update=values), client=client)


def test_connection_check_requires_login_and_same_origin(settings):
    config = settings.model_copy(update={"app_password": "fictional"})
    calls = []
    app = create_app(
        config, provider_check=lambda value: calls.append(value) or "Accepted fake key."
    )
    client = TestClient(app)
    route = "/setup/providers/check-openrouter"
    assert client.post(route, follow_redirects=False).status_code == 303
    assert not calls
    client.post("/login", data={"password": "fictional"})
    assert client.post(route, headers={"Origin": "https://elsewhere.invalid"}).status_code == 403
    assert not calls
    assert "Accepted fake key." in client.post(route).text
    assert calls == [config]
