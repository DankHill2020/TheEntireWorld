"""The Entire World Intelligence Engine."""

from __future__ import annotations

from typing import Callable, Iterable

from .progress_events import ActivityEvent, EngineResult, ProgressEvent
from .request_context import RequestContext
from .providers import RequestProvider, default_providers

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]


class RequestEngine:
    """Route a request through deterministic, non-UI-thread preparation."""

    def __init__(
        self,
        progress: ProgressCallback | None = None,
        activity: ActivityCallback | None = None,
        providers: Iterable[RequestProvider] | None = None,
    ):
        self.progress = progress or (lambda _event: None)
        self.activity = activity or (lambda _event: None)
        self.providers = list(providers or default_providers())

    def emit(self, stage: str, message: str, current: int = 0, total: int = 0, detail: str = "") -> None:
        self.progress(ProgressEvent(stage=stage, message=message, current=current, total=total, detail=detail))

    def process(self, context: RequestContext) -> EngineResult:
        self.emit("intent", "Understanding request")
        self.activity(ActivityEvent("intent", "Request received", context.text, status="info"))
        route_decision = (context.extras or {}).get("prompt_route_decision") or {}
        if not route_decision:
            try:
                from services.prompt_route_service import classify_prompt_route

                route_decision = classify_prompt_route(
                    context.text,
                    project_roots=list(context.project_roots or []),
                    active_path=context.current_file_path,
                ).to_dict()
            except Exception as exc:
                self.activity(ActivityEvent("error", "Route classification failed", str(exc), status="error"))
                route_decision = {}
        if route_decision:
            try:
                from services.prompt_dispatch_service import PromptDispatchService
                from services.prompt_progress_service import build_prompt_progress_plan
                from services.route_diagnostics_service import build_route_diagnostic_report

                route_diagnostics = build_route_diagnostic_report(route_decision).to_dict()
                route_decision["route_diagnostics"] = route_diagnostics
                for candidate in list(route_diagnostics.get("candidates") or [])[:5]:
                    self.activity(
                        ActivityEvent(
                            "route_candidate",
                            str(candidate.get("route") or "route"),
                            "; ".join(candidate.get("reasons") or []),
                            status="ok" if candidate.get("selected") else "info",
                            score=float(candidate.get("score") or 0.0),
                            metadata={"candidate": candidate, "selected_route": route_diagnostics.get("selected_route")},
                        )
                    )

                visible_plan = route_decision.get("visible_progress") or build_prompt_progress_plan(
                    context.text,
                    route_decision,
                )
                route_decision["visible_progress"] = visible_plan
                for stage in list(visible_plan.get("stages") or [])[:3]:
                    self.emit(
                        str(stage.get("state") or "progress").lower(),
                        str(stage.get("label") or stage.get("message") or "Working"),
                        int(stage.get("index") or 0),
                        int(stage.get("total") or 0),
                        str(stage.get("message") or ""),
                    )
                    self.activity(
                        ActivityEvent(
                            "visible_progress",
                            str(stage.get("label") or "Working"),
                            f"{stage.get('message') or ''} Stop: {stage.get('stop_when') or ''}",
                            status="info",
                            metadata={"stage": stage, "route": route_decision.get("route")},
                        )
                    )
                self.emit("route", f"Routing through {route_decision.get('execution_route') or route_decision.get('route')}")
                self.activity(
                    ActivityEvent(
                        "route",
                        "Selected prompt route",
                        str(route_decision.get("execution_route") or route_decision.get("route") or ""),
                        status="ok",
                        metadata=route_decision,
                    )
                )
                return PromptDispatchService().dispatch(route_decision, context, self.progress, self.activity)
            except Exception as exc:
                self.activity(ActivityEvent("error", "Prompt dispatcher failed", str(exc), status="error"))
                return EngineResult(
                    action="error",
                    label="Prompt Dispatcher",
                    text=f"Prompt dispatch failed: {exc}",
                    metadata={"engine_path": "prompt_dispatch", "error": str(exc), "result_type": "error", "route_decision": route_decision},
                )
        for provider in self.providers:
            try:
                if not provider.can_handle(context):
                    continue
                self.emit("route", f"Routing through {provider.name}")
                self.activity(ActivityEvent("route", "Selected engine provider", provider.name, status="ok"))
                return provider.handle(context, self.progress, self.activity)
            except Exception as exc:
                self.activity(ActivityEvent("error", "Provider failed", f"{provider.name}: {exc}", status="error"))
                return EngineResult(
                    action="error",
                    label="Intelligence Engine",
                    text=f"{provider.name} failed: {exc}",
                    metadata={"engine_path": provider.name, "error": str(exc), "result_type": "error"},
                )
        self.activity(ActivityEvent("route", "No special engine route matched", "Using default chat path", status="info"))
        return EngineResult(
            action="passthrough",
            label="Default",
            text="No special engine route matched.",
            metadata={"engine_path": "passthrough", "result_type": "passthrough"},
        )
