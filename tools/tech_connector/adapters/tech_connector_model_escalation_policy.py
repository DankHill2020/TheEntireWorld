"""Tech Connector model-tier escalation adapter."""

from __future__ import annotations

from reasoning_runtime.models import ModelTier, ModelTierEscalationPolicy


class TechConnectorLocalModelEscalationPolicy(ModelTierEscalationPolicy):
    """Map Tech Connector's local model profiles into runtime tiers."""

    name = "tech_connector_local_model_escalation"

    def __init__(self) -> None:
        try:
            from tech_connector.services.ollama_service import code_model_for_profile

            tiers = [
                ModelTier(tier, "ollama", code_model_for_profile(tier), "local")
                for tier in ("micro", "small", "standard", "quality", "deep")
            ]
        except Exception:
            tiers = [
                ModelTier("micro", "ollama", "qwen2.5-coder:3b", "local"),
                ModelTier("small", "ollama", "qwen2.5-coder:3b", "local"),
                ModelTier("standard", "ollama", "qwen2.5-coder:7b", "local"),
                ModelTier("quality", "ollama", "qwen2.5-coder:7b", "local"),
                ModelTier("deep", "ollama", "qwen2.5-coder:7b", "local"),
            ]
        super().__init__(tiers)
