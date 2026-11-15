"""The LLM port (invariant I-6).

No code outside `outreach.adapters` may import a model provider's SDK. Provider
and model are configuration, which is what keeps D-007 reversible.

The schema is part of the interface, not an afterthought: `generate` returns a
validated instance of the model you ask for, or raises. There is no code path
that hands back unvalidated free text, so "parse the model's prose and hope"
is not expressible.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when generation fails, including when output fails validation."""


@runtime_checkable
class LLMPort(Protocol):
    """What the rest of the system is allowed to ask of a language model."""

    def generate(
        self,
        *,
        prompt: str,
        schema: type[SchemaT],
        max_tokens: int = 4096,
    ) -> SchemaT:
        """Return an instance of `schema`, or raise `LLMError`.

        Implementations must validate before returning. Enumerated fields are
        constrained by the schema itself, so an invalid value cannot be
        returned — it raises instead.
        """
        ...
