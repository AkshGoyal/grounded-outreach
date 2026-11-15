"""Small provider boundaries for the named-prospect workbench."""

from typing import Protocol


class ProspectResearchProvider(Protocol):
    def research(self, prospect: dict) -> dict:
        """Return source data; the core decides identity and useful evidence."""
        ...


class DraftWriter(Protocol):
    origin: str  # "model" or "fixture"; saved with each draft revision

    def generate(self, stage: str, prompt: str, context: dict) -> dict:
        """Return {subject, body, claims}. The core checks it; the writer proves nothing."""
        ...
