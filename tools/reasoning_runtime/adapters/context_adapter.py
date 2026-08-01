"""Context and interaction ingress contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InteractionSurface:
    """Describes where a user request entered the reasoning runtime."""

    kind: str = "api"
    user_id: str = ""
    session_id: str = ""
    supports_clarification: bool = True
    supports_approval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextAdapter(ABC):
    """Supplies active environment state to the reasoning kernel."""

    name: str = "context"

    @abstractmethod
    def get_active_context(self) -> dict[str, Any]:
        """Return domain-specific context available before reasoning starts."""

    def get_interaction_surface(self) -> InteractionSurface:
        """Return how the current request entered the system."""

        return InteractionSurface()

    def get_permission_context(self) -> dict[str, Any]:
        """Return permission and approval constraints for this request."""

        return {}
