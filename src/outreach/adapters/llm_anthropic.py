"""Claude, behind the LLM port (D-007).

This is the only module allowed to import the `anthropic` package — see
invariant I-6 and `tests/test_architecture.py`, which enforces it.

It returns a validated instance of the caller's schema or raises. There is no
path here that hands back unchecked text, which is what makes "parse the
model's prose and hope" impossible further up.
"""

from __future__ import annotations

import time

from outreach.config import Settings
from outreach.ports.llm import LLMError, SchemaT

# Retry only on failures that a retry can actually fix. A refusal or a bad
# request will fail identically every time, and retrying it just spends money.
_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 4.0)


class AnthropicLLM:
    """Implements `outreach.ports.llm.LLMPort` against the Anthropic API."""

    def __init__(self, settings: Settings, *, client: object | None = None) -> None:
        settings.require("anthropic_api_key")
        self._model = settings.anthropic_model
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings):
        import anthropic

        return anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def generate(
        self,
        *,
        prompt: str,
        schema: type[SchemaT],
        max_tokens: int = 4096,
    ) -> SchemaT:
        """Return a validated `schema` instance, or raise `LLMError`."""
        import anthropic

        last_error: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            try:
                message = self._client.messages.parse(
                    model=self._model,
                    max_tokens=max_tokens,
                    # Adaptive thinking, at medium effort: drafting a short
                    # email is a judgement call, but not a hard reasoning
                    # problem, and effort is the first thing that costs money.
                    thinking={"type": "adaptive"},
                    output_config={"effort": "medium", "format": schema},
                    # If a safety classifier declines the request, fall back
                    # rather than failing the whole run.
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    messages=[{"role": "user", "content": prompt}],
                )
            except anthropic.APIStatusError as exc:
                last_error = exc
                if exc.status_code not in _RETRYABLE_STATUS:
                    raise LLMError(
                        f"Claude refused the request ({exc.status_code}): {exc}"
                    ) from exc
            except anthropic.APIConnectionError as exc:
                last_error = exc
            else:
                return self._parsed(message, schema)

            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])

        raise LLMError(f"Claude was unreachable after {_MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _parsed(message, schema: type[SchemaT]) -> SchemaT:
        if getattr(message, "stop_reason", None) == "refusal":
            details = getattr(message, "stop_details", None)
            raise LLMError(f"Claude declined to answer: {details}")

        parsed = getattr(message, "parsed_output", None)
        if parsed is None:
            raise LLMError("Claude returned nothing that matched the requested shape.")
        if not isinstance(parsed, schema):
            raise LLMError(f"Expected {schema.__name__}, got {type(parsed).__name__}.")
        return parsed
