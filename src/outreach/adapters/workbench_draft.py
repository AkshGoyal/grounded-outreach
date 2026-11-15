"""Configured draft model behind the same per-run quotas, deadline and paid-request ledger."""

from outreach.core.workbench_draft import DRAFT_SYSTEM, DraftOutput


class ModelDraftWriter:
    """Calls the Workbench draft model once per stage, never replaying.

    Models come from OUTREACH_WORKBENCH_DRAFT_MODELS, tried in order when one is refused. A
    later "Write the draft" attempt uses new request keys (draft-2, repair-2…) so earlier
    ledger entries are never reused or replayed.
    """

    origin = "model"

    def __init__(self, provider, attempt=1):
        self.attempt = attempt
        # Reuses the live research provider's guard: operation quota, held-request refusal,
        # wall-clock deadline and the durable research_calls ledger.
        self.provider = provider
        self.api, self.store, self.run_id = provider.api, provider.store, provider.run_id

    def generate(self, stage, prompt, context):
        from outreach.adapters.workbench_research import _models

        suffix = "" if self.attempt == 1 else f"-{self.attempt}"
        label = "Draft model request" if stage == "draft" else "Repair model request"
        result = self.provider.generate_structured(
            f"workbench/{stage}{suffix}/model",
            prompt,
            DraftOutput,
            _models(self.api.settings.workbench_draft_models),
            label=label,
            system=DRAFT_SYSTEM,
            # An email and its sentence list fit well inside this; a larger allowance only
            # makes the spending guard reserve more than the step can cost.
            max_tokens=1500,
        )
        self.store.add_stage(
            self.run_id, label, "completed", "Structured draft saved for claim checks."
        )
        return result.model_dump()
