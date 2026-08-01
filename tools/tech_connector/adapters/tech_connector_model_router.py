"""Model routing adapter for Tech Connector's existing provider settings."""

from __future__ import annotations

from reasoning_runtime.models import ModelRequest, ModelRoute, ModelRouter


class TechConnectorModelRouter(ModelRouter):
    """Resolve model routes through Tech Connector settings when available."""

    name = "tech_connector_model_router"

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = dict(settings) if settings is not None else None

    def choose_route(self, request: ModelRequest) -> ModelRoute:
        try:
            from tech_connector.services.llm_router_service import resolve_llm_provider_route
            from tech_connector.services.settings_service import load_settings

            settings = dict(self.settings) if self.settings is not None else load_settings()
            selected = str(settings.get("model") or settings.get("general_model") or "")
            route = resolve_llm_provider_route(selected, settings)
            return ModelRoute(
                provider=route.provider,
                model=route.model,
                transport=route.transport,
                tier="tech_connector_configured",
                fallback_allowed=not route.cloud_active,
                metadata={"cloud_active": route.cloud_active},
            )
        except Exception as exc:
            return ModelRoute(
                provider="none",
                model="none",
                tier="unavailable",
                metadata={"error": str(exc)},
            )
