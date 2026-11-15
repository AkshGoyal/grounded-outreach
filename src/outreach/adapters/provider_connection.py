"""Read-only OpenRouter authentication check; never requests a model completion."""

import httpx

from outreach.config import ConfigError


def check_openrouter(settings, *, client=None):
    if settings.local_network_restricted:
        raise ConfigError("Restart using RESTART-OUTREACH.cmd before checking live connections.")
    if not settings.openrouter_api_key:
        raise ConfigError("Save your OpenRouter API key first.")
    owned = client is None
    client = client or httpx.Client(timeout=12, follow_redirects=False)
    try:
        response = client.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        if response.status_code in (401, 403):
            raise ConfigError(
                "OpenRouter refused this key. Create a regular API key and save it here."
            )
        response.raise_for_status()
        data = response.json().get("data")
        if not isinstance(data, dict):
            raise ValueError()
        if data.get("is_management_key") or data.get("is_provisioning_key"):
            raise ConfigError(
                "This is a management key. Save a regular OpenRouter API key for research."
            )
        remaining = data.get("limit_remaining")
        if isinstance(remaining, (int, float)) and remaining <= 0:
            return (
                "OpenRouter accepted the key, but its spending limit is exhausted. "
                "Review credits and limits in OpenRouter. No model request was made."
            )
        return (
            "OpenRouter accepted the key. No model request was made. "
            "Check account credits before approving paid research."
        )
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise ConfigError(
            "Could not check OpenRouter. Check your internet connection and provider status, "
            "then try again. No model request was made."
        ) from None
    finally:
        if owned:
            client.close()
