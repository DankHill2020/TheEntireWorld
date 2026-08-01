"""Composable reasoning layers independent of any UI or DCC domain."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReasoningFrame:
    """State passed through the layered reasoning pipeline."""

    request: str
    context: dict[str, Any] = field(default_factory=dict)
    understanding: dict[str, Any] = field(default_factory=dict)
    gaps: tuple[dict[str, Any], ...] = ()
    evidence: tuple[Any, ...] = ()
    plan: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "ReasoningFrame":
        data = {
            "request": self.request,
            "context": self.context,
            "understanding": self.understanding,
            "gaps": self.gaps,
            "evidence": self.evidence,
            "plan": self.plan,
            "metadata": self.metadata,
        }
        data.update(updates)
        return ReasoningFrame(**data)


@dataclass(frozen=True)
class ReasoningLayerResult:
    frame: ReasoningFrame
    ok: bool = True
    diagnostics: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class ReasoningLayer(ABC):
    """One replaceable layer in the reasoning pipeline."""

    name: str = "reasoning_layer"

    @abstractmethod
    def run(self, frame: ReasoningFrame) -> ReasoningLayerResult:
        """Process and return the updated frame."""


class LayeredReasoningPipeline:
    """Runs request understanding, gap handling, planning, and repair layers."""

    def __init__(self, layers: list[ReasoningLayer] | None = None) -> None:
        self.layers = list(layers or [])

    def register(self, layer: ReasoningLayer) -> None:
        self.layers.append(layer)

    def run(self, request: str, context: dict[str, Any] | None = None) -> ReasoningLayerResult:
        frame = ReasoningFrame(request=request, context=dict(context or {}))
        diagnostics: list[str] = []
        for layer in self.layers:
            result = layer.run(frame)
            diagnostics.extend(result.diagnostics)
            frame = result.frame
            if not result.ok:
                return ReasoningLayerResult(
                    frame=frame,
                    ok=False,
                    diagnostics=tuple(diagnostics),
                    metadata={"failed_layer": layer.name},
                )
        return ReasoningLayerResult(frame=frame, ok=True, diagnostics=tuple(diagnostics))
