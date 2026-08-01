"""Modular feature discovery and invocation for Tech Connector's public API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class APIFeatureDescriptor:
    feature_id: str
    category: str
    version: str
    description: str
    operations: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    available: bool = True
    source: str = ""
    operation_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    access: str = "direct"
    owner_feature_id: str = ""
    lifecycle_stage: str = ""
    stability: str = "stable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class APIFeatureRegistry:
    """Stores independently discoverable API modules and approved operations."""

    def __init__(self) -> None:
        self._descriptors: dict[str, APIFeatureDescriptor] = {}
        self._handlers: dict[str, dict[str, Callable[..., Any]]] = {}

    def register(
        self,
        descriptor: APIFeatureDescriptor,
        handlers: dict[str, Callable[..., Any]] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        feature_id = str(descriptor.feature_id or "").strip()
        if not feature_id:
            raise ValueError("API feature_id is required.")
        if feature_id in self._descriptors and not replace:
            raise ValueError(f"API feature is already registered: {feature_id}")
        if descriptor.access not in {"direct", "owned", "internal"}:
            raise ValueError(
                f"API feature '{feature_id}' has unsupported access level: "
                f"{descriptor.access}"
            )
        if descriptor.access == "owned" and not descriptor.owner_feature_id:
            raise ValueError(
                f"Owned API feature '{feature_id}' must declare owner_feature_id."
            )

        operation_handlers = dict(handlers or {})
        undeclared = sorted(set(operation_handlers) - set(descriptor.operations))
        if undeclared:
            raise ValueError(
                f"Handlers are not declared by feature '{feature_id}': {', '.join(undeclared)}"
            )
        self._descriptors[feature_id] = descriptor
        self._handlers[feature_id] = operation_handlers

    def list(
        self,
        *,
        category: str = "",
        available_only: bool = True,
        access: str = "",
        lifecycle_stage: str = "",
        owner_feature_id: str = "",
    ) -> list[APIFeatureDescriptor]:
        category = str(category or "").strip()
        access = str(access or "").strip()
        lifecycle_stage = str(lifecycle_stage or "").strip()
        owner_feature_id = str(owner_feature_id or "").strip()
        features = []
        for descriptor in self._descriptors.values():
            if available_only and not descriptor.available:
                continue
            if category and not (
                descriptor.category == category
                or descriptor.category.startswith(category + ".")
            ):
                continue
            if access and descriptor.access != access:
                continue
            if lifecycle_stage and descriptor.lifecycle_stage != lifecycle_stage:
                continue
            if owner_feature_id and descriptor.owner_feature_id != owner_feature_id:
                continue
            features.append(descriptor)
        return sorted(features, key=lambda item: (item.category, item.feature_id))

    def get(self, feature_id: str) -> APIFeatureDescriptor | None:
        return self._descriptors.get(str(feature_id or "").strip())

    def invoke(self, feature_id: str, operation: str, **kwargs: Any) -> Any:
        descriptor = self.get(feature_id)
        if descriptor is None:
            raise KeyError(f"Unknown API feature: {feature_id}")
        if not descriptor.available:
            raise RuntimeError(f"API feature is unavailable: {feature_id}")
        operation = str(operation or "").strip()
        if operation not in descriptor.operations:
            raise KeyError(
                f"Feature '{feature_id}' does not declare operation '{operation}'."
            )
        handler = self._handlers.get(descriptor.feature_id, {}).get(operation)
        if handler is None:
            ownership = ""
            if descriptor.owner_feature_id:
                ownership = (
                    f" Use owner feature '{descriptor.owner_feature_id}' to run this stage."
                )
            raise RuntimeError(
                f"Feature '{feature_id}' operation '{operation}' is discoverable "
                f"but has no direct invocation handler.{ownership}"
            )
        return handler(**kwargs)

    def manifest(self) -> dict[str, Any]:
        features = [descriptor.to_dict() for descriptor in self.list(available_only=False)]
        return {
            "schema": "tech_connector.api_features.v2",
            "feature_count": len(features),
            "features": features,
        }
