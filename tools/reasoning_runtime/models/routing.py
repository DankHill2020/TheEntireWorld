"""Replaceable model routing contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelRequest:
    task: str
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()
    max_cost_tier: str = ""
    privacy_tier: str = ""


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    tier: str = "default"
    transport: str = "local"
    fallback_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelProviderRoute:
    """Resolved provider contract that can be reused for an entire request."""

    provider: str
    model: str
    api_key: str = ""
    cloud_active: bool = False
    transport: str = "local"


class ModelProviderLockError(RuntimeError):
    """A locked provider failed and fallback was intentionally blocked."""


_ACTIVE_PROVIDER_ROUTE: ContextVar[ModelProviderRoute | None] = ContextVar(
    "reasoning_runtime_model_provider_route",
    default=None,
)
_ACTIVE_MODEL_CALLS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "reasoning_runtime_model_calls",
    default=None,
)
_ACTIVE_PROVIDER_FAILURE: ContextVar[str | None] = ContextVar(
    "reasoning_runtime_model_provider_failure",
    default=None,
)


def public_provider_route(route: ModelProviderRoute) -> dict[str, Any]:
    return {
        "provider": route.provider,
        "model": route.model,
        "transport": route.transport,
        "cloud_active": route.cloud_active,
        "fallback_allowed": False,
    }


def current_model_provider_route() -> ModelProviderRoute | None:
    return _ACTIVE_PROVIDER_ROUTE.get()


def current_model_calls() -> list[dict[str, Any]] | None:
    return _ACTIVE_MODEL_CALLS.get()


def assert_model_provider_healthy() -> None:
    failure = _ACTIVE_PROVIDER_FAILURE.get()
    if failure:
        raise ModelProviderLockError(failure)


def mark_model_provider_failed(message: str) -> None:
    if _ACTIVE_PROVIDER_ROUTE.get() is not None:
        _ACTIVE_PROVIDER_FAILURE.set(message)


def model_provider_integrity(
    route: ModelProviderRoute,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    unexpected = [
        call
        for call in calls
        if call.get("provider") != route.provider
        or (route.cloud_active and call.get("model") != route.model)
    ]
    return {
        "valid": not unexpected,
        "call_count": len(calls),
        "unexpected_routes": unexpected,
    }


@contextmanager
def locked_model_provider_route(route: ModelProviderRoute):
    """Freeze a provider route and collect model-call telemetry."""

    route_token = _ACTIVE_PROVIDER_ROUTE.set(route)
    calls: list[dict[str, Any]] = []
    calls_token = _ACTIVE_MODEL_CALLS.set(calls)
    failure_token = _ACTIVE_PROVIDER_FAILURE.set(None)
    try:
        yield calls
    finally:
        _ACTIVE_PROVIDER_FAILURE.reset(failure_token)
        _ACTIVE_MODEL_CALLS.reset(calls_token)
        _ACTIVE_PROVIDER_ROUTE.reset(route_token)


@dataclass(frozen=True)
class ModelResponse:
    ok: bool
    text: str = ""
    route: ModelRoute | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelRouter(ABC):
    """Chooses and executes models for runtime reasoning steps."""

    name: str = "model_router"

    @abstractmethod
    def choose_route(self, request: ModelRequest) -> ModelRoute:
        """Select the model route for a reasoning task."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        route = self.choose_route(request)
        return ModelResponse(
            ok=False,
            route=route,
            error=f"Model generation is not implemented by {self.name}.",
        )


class StaticModelRouter(ModelRouter):
    """Simple router useful for tests and local-only integrations."""

    name = "static_model_router"

    def __init__(self, route: ModelRoute | None = None) -> None:
        self.route = route or ModelRoute(provider="none", model="none")

    def choose_route(self, request: ModelRequest) -> ModelRoute:
        return self.route
