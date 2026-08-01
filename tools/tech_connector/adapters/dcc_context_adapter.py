"""Context adapter exposing Tech Connector project and DCC state."""

from __future__ import annotations

from typing import Any

from reasoning_runtime import ContextAdapter, InteractionSurface


class DccContextAdapter(ContextAdapter):
    """Expose Tech Connector's active app/project state to the runtime."""

    name = "tech_connector_context"

    def __init__(self, *, app_service: Any = None, window: Any = None, project_root: str = "") -> None:
        self.app_service = app_service
        self.window = window
        self.project_root = project_root

    def get_active_context(self) -> dict[str, Any]:
        roots: list[str] = []
        if self.app_service is not None and hasattr(self.app_service, "all_roots"):
            try:
                roots = [str(item) for item in self.app_service.all_roots()]
            except Exception:
                roots = []
        if self.project_root and self.project_root not in roots:
            roots.insert(0, self.project_root)
        return {
            "domain": "dcc_game_development",
            "project_root": self.project_root,
            "project_roots": roots,
            "has_window": self.window is not None,
            "has_app_service": self.app_service is not None,
        }

    def get_interaction_surface(self) -> InteractionSurface:
        return InteractionSurface(
            kind="tech_connector",
            supports_clarification=True,
            supports_approval=True,
            metadata={"ui": self.window is not None},
        )
