"""OpenRouter, behind the LLM port (D-012).

One key, many models. The model name is a setting, so comparing two of them is
a config change rather than a code change — which is the whole reason the port
exists (invariant I-6).

Two things about OpenRouter that will bite if they are not handled here:

1. **Schema enforcement is per *provider*, not per model.** The same model can
   be served by several providers, and some of them treat a JSON schema as a
   polite suggestion. `require_parameters` forces routing to providers that
   actually enforce it. Without it you occasionally get prose back, and the
   failure looks like a model problem when it is a routing problem.

2. **Strict schemas need every field marked required, and no extra keys.**
   Pydantic marks optional fields as not-required, which strict mode rejects.
   `_strict_schema` below rewrites the schema so optional means "may be null",
   not "may be absent".
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import ValidationError

from outreach.config import Settings
from outreach.ports.llm import LLMError, SchemaT

BASE_URL = "https://openrouter.ai/api/v1"

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 4.0)


def _strict_schema(model: type[SchemaT]) -> dict[str, Any]:
    """Pydantic's JSON schema, rewritten for strict mode.

    Strict mode wants every property listed as required and no unexpected keys.
    A field that is genuinely optional stays optional by being nullable, which
    the schema already expresses.
    """

    def tighten(node: Any) -> Any:
        if isinstance(node, dict):
            node = {key: tighten(value) for key, value in node.items()}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [tighten(item) for item in node]
        return node

    return tighten(model.model_json_schema())


class OpenRouterLLM:
    """Implements `outreach.ports.llm.LLMPort` against OpenRouter."""

    def __init__(self, settings: Settings, *, client: object | None = None) -> None:
        settings.require("openrouter_api_key")
        self._model = settings.llm_model
        self._client = client or self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings):
        from openai import OpenAI

        return OpenAI(api_key=settings.openrouter_api_key, base_url=BASE_URL)

    def generate(
        self,
        *,
        prompt: str,
        schema: type[SchemaT],
        max_tokens: int = 4096,
    ) -> SchemaT:
        """Return a validated `schema` instance, or raise `LLMError`."""
        import openai

        request = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "strict": True,
                    "schema": _strict_schema(schema),
                },
            },
            # Route only to providers that genuinely enforce the schema.
            "extra_body": {"provider": {"require_parameters": True}},
        }

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                completion = self._client.chat.completions.create(**request)
            except openai.APIStatusError as exc:
                last_error = exc
                if exc.status_code not in _RETRYABLE_STATUS:
                    raise LLMError(
                        f"OpenRouter refused the request ({exc.status_code}): {exc}"
                    ) from exc
            except openai.APIConnectionError as exc:
                last_error = exc
            else:
                return self._parsed(completion, schema)

            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_BACKOFF_SECONDS[attempt])

        raise LLMError(f"OpenRouter was unreachable after {_MAX_ATTEMPTS} attempts: {last_error}")

    def _parsed(self, completion, schema: type[SchemaT]) -> SchemaT:
        try:
            content = completion.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise LLMError("OpenRouter returned a response with no message in it.") from exc

        if not content:
            raise LLMError(
                f"{self._model} returned nothing. If this repeats, the provider serving "
                "it may not enforce JSON schemas — check the model's providers on "
                "openrouter.ai."
            )

        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise LLMError(
                f"{self._model} returned something that is not a valid {schema.__name__}. "
                f"First 200 characters: {content[:200]!r}\n\n{exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self._model} did not return JSON at all: {content[:200]!r}") from exc
