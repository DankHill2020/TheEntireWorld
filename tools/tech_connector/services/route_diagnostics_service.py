from __future__ import annotations

"""Explainable route diagnostics for logs, tests, and the future Developer Console.

This module does not classify or dispatch requests. It normalizes, renders,
and records the evidence already produced by PromptRouteService.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from tech_connector.models.constants import temp_output_path


@dataclass(frozen=True)
class RouteCandidateDiagnostic:
    route: str
    score: float
    reasons: tuple[str, ...] = ()
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDiagnosticReport:
    selected_route: str
    execution_route: str
    handler_id: str
    confidence: float
    selected_reason: str
    candidates: tuple[RouteCandidateDiagnostic, ...] = ()
    rejected_routes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_route": self.selected_route,
            "execution_route": self.execution_route,
            "handler_id": self.handler_id,
            "confidence": self.confidence,
            "selected_reason": self.selected_reason,
            "candidates": [item.to_dict() for item in self.candidates],
            "rejected_routes": list(self.rejected_routes),
            "warnings": list(self.warnings),
        }


def build_route_diagnostic_report(decision: dict[str, Any] | Any) -> RouteDiagnosticReport:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    selected_route = str(data.get("route") or "")
    raw_candidates = list(data.get("route_candidates") or [])
    candidates: list[RouteCandidateDiagnostic] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        route = str(raw.get("route") or "")
        if not route or route in seen:
            continue
        seen.add(route)
        try:
            score = float(raw.get("score") or 0.0)
        except Exception:
            score = 0.0
        candidates.append(
            RouteCandidateDiagnostic(
                route=route,
                score=score,
                reasons=tuple(str(item) for item in raw.get("reasons") or [] if item),
                selected=route == selected_route,
            )
        )
    if selected_route and selected_route not in seen:
        candidates.append(
            RouteCandidateDiagnostic(
                route=selected_route,
                score=float(data.get("confidence") or 0.0),
                reasons=tuple(str(item) for item in data.get("reasons") or [] if item)[:3],
                selected=True,
            )
        )
    candidates.sort(key=lambda item: (not item.selected, -item.score, item.route))
    warnings: list[str] = []
    if not selected_route:
        warnings.append("No selected route was recorded.")
    if not data.get("execution_route"):
        warnings.append("No execution route was recorded.")
    if candidates and not any(item.selected for item in candidates):
        warnings.append("Selected route was absent from route candidates.")
    return RouteDiagnosticReport(
        selected_route=selected_route,
        execution_route=str(data.get("execution_route") or ""),
        handler_id=str(data.get("handler_id") or ""),
        confidence=float(data.get("confidence") or 0.0),
        selected_reason=str(data.get("selected_route_reason") or ""),
        candidates=tuple(candidates),
        rejected_routes=tuple(str(item) for item in data.get("rejected_routes") or [] if item),
        warnings=tuple(warnings),
    )


def render_route_diagnostics(report: RouteDiagnosticReport | dict[str, Any], *, max_candidates: int = 5) -> str:
    data = report.to_dict() if isinstance(report, RouteDiagnosticReport) else dict(report or {})
    lines = [
        "Route diagnostics:",
        f"Selected: {data.get('selected_route') or '<none>'}",
        f"Execution route: {data.get('execution_route') or '<none>'}",
        f"Handler: {data.get('handler_id') or '<none>'}",
        f"Confidence: {float(data.get('confidence') or 0.0):.3f}",
    ]
    if data.get("selected_reason"):
        lines.append(f"Reason: {data['selected_reason']}")
    candidates = list(data.get("candidates") or [])
    if candidates:
        lines.append("Candidates:")
        for item in candidates[:max_candidates]:
            marker = "*" if item.get("selected") else "-"
            reasons = "; ".join(str(reason) for reason in item.get("reasons") or [])
            suffix = f" — {reasons}" if reasons else ""
            lines.append(f"{marker} {item.get('route')}: {float(item.get('score') or 0.0):.3f}{suffix}")
    for warning in data.get("warnings") or []:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def _metrics_path(project_root: str | None = None) -> Path:
    if project_root:
        return Path(project_root).resolve() / ".ai_studio" / "routing_metrics.jsonl"
    return temp_output_path("routing_metrics.jsonl", subdir="routing_metrics")


def record_route_metric(metric: dict[str, Any], *, project_root: str | None = None) -> None:
    """Append one route metric event.

    This deliberately avoids prompt text and file contents. It records behavior
    signals only: route, handler, confidence, result type, timing, and LLM use.
    """
    path = _metrics_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metric or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
