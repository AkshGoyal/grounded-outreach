"""A language model that returns what you told it to.

Stands in for the *port*, so tests never touch the network, never need an API
key, and never cost money. Swapping provider changes none of them.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from outreach.ports.llm import LLMError, SchemaT


class FakeLLM:
    """Implements `LLMPort`. Returns queued responses in order."""

    def __init__(self, responses: list[BaseModel] | None = None) -> None:
        self._responses = list(responses or [])
        self.prompts: list[str] = []

    def generate(
        self,
        *,
        prompt: str,
        schema: type[SchemaT],
        max_tokens: int = 4096,
    ) -> SchemaT:
        self.prompts.append(prompt)
        if not self._responses:
            raise LLMError("FakeLLM has no queued responses left.")
        response = self._responses.pop(0)
        # Validate against the schema actually requested, as the real API does
        # — so a queued answer that the schema forbids fails here too.
        try:
            return schema.model_validate(response.model_dump())
        except ValidationError as exc:
            raise LLMError(
                f"FakeLLM was queued a {type(response).__name__} that does not "
                f"fit the requested {schema.__name__}: {exc}"
            ) from exc
