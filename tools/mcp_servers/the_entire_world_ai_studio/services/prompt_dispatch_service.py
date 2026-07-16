"""Canonical execution dispatch for routed prompts.

PromptRouteService decides what the user wants. This dispatcher validates the
canonical goal graph, identifies the next achievable goals, and selects the
registered handler for the current execution route. Handlers may use the
original prompt as payload/query text, but they must not reinterpret intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import time
from typing import Any, Callable, Protocol

from engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from engine.request_context import RequestContext
from services.context_providers import ContextItem, ContextProviderRegistry

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]


CAP_ACTIVE_PROJECT = "active_project"
CAP_PROJECT_INDEX = "project_index"
CAP_PYTHON_SYMBOLS = "python_symbols"
CAP_WORKFLOW_GRAPH = "workflow_graph"
CAP_DCC_CONNECTION = "dcc_connection"
CAP_LLM = "llm"


class PromptRouteHandler(Protocol):
    handler_id: str
    requires: set[str]

    def execute(
        self,
        decision: dict,
        context: RequestContext,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None,
    ) -> EngineResult: ...


@dataclass
class ProviderRouteHandler:
    """Adapter that lets existing engine providers be used as dispatch handlers."""

    handler_id: str
    provider: object
    requires: set[str] = field(default_factory=set)

    def execute(
        self,
        decision: dict,
        context: RequestContext,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None,
    ) -> EngineResult:
        if activity:
            activity(
                ActivityEvent(
                    "route",
                    "Dispatch handler selected",
                    self.handler_id,
                    status="ok",
                    metadata={"execution_route": decision.get("execution_route")},
                )
            )
        extras = dict(context.extras or {})
        extras["prompt_route_decision"] = dict(decision or {})
        extras["request_goal_graph"] = dict(
            decision.get("goal_graph")
            or decision.get("task_graph")
            or {}
        )
        extras["current_request_goal"] = dict(decision.get("current_goal") or {})
        extras["ready_request_goals"] = list(decision.get("ready_goals") or [])
        routed_context = replace(context, extras=extras)
        return self.provider.handle(routed_context, emit, activity)


@dataclass
class PassthroughRouteHandler:
    handler_id: str
    reason: str
    requires: set[str] = field(default_factory=set)

    def execute(
        self,
        decision: dict,
        context: RequestContext,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None,
    ) -> EngineResult:
        if activity:
            activity(
                ActivityEvent(
                    "route",
                    "Dispatcher passthrough",
                    self.reason,
                    status="info",
                    metadata={"route": decision.get("route"), "execution_route": decision.get("execution_route")},
                )
            )
        return EngineResult(
            action="passthrough",
            label="Dispatcher",
            text=self.reason,
            metadata={
                "engine_path": "prompt_dispatch",
                "result_type": "passthrough",
                "route_decision": decision,
                "handler_id": self.handler_id,
            },
        )


@dataclass
class DccExecutionRouteHandler:
    handler_id: str = "DCCExecutionHandler"
    requires: set[str] = field(default_factory=lambda: {CAP_DCC_CONNECTION})

    def execute(
        self,
        decision: dict,
        context: RequestContext,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None,
    ) -> EngineResult:
        from services.dcc_execution_service import (
            build_dcc_execution_request,
            default_dcc_execution_adapters,
        )
        from services.interaction_quality_service import (
            build_execution_plan,
            build_result_card,
            recovery_options,
            update_execution_plan,
        )

        request = build_dcc_execution_request(decision, context)
        execution_plan = build_execution_plan(decision, request.to_dict())
        emit(ProgressEvent("execution_plan", "Resolved execution plan", 1, len(execution_plan)))
        adapters = default_dcc_execution_adapters()
        adapter = adapters.get(request.execution_environment)
        if not adapter:
            from services.clarification_service import build_slot_clarification

            clarification = build_slot_clarification(
                decision=decision,
                context=context,
                missing_slots=["execution_environment"],
                execution_request=request.to_dict(),
                reason="No registered execution adapter matched the resolved host.",
            )
            return EngineResult(
                action="clarify",
                label="DCC Execution",
                text=clarification.text,
                metadata={
                    "engine_path": "prompt_dispatch",
                    "result_type": "missing_adapter",
                    "dcc_request": request.to_dict(),
                    "missing_capabilities": [{"capability": "execution_adapter", "current_state": "missing"}],
                    "execution_plan": execution_plan,
                    "result_card": build_result_card(decision=decision, request=request.to_dict()),
                    "recovery_options": recovery_options(result_type="missing_adapter"),
                    **clarification.to_metadata(),
                },
            )

        check = adapter.check_capabilities(request, context)
        if not check.ok:
            from services.clarification_service import build_slot_clarification

            failures = check.to_dict()["failures"]
            missing_slots = list(request.missing_slots)
            capability_slots = [
                str(failure.get("capability") or "")
                for failure in failures
                if failure.get("capability") and failure.get("current_state") in {"missing", "missing_slots"}
            ]
            clarification = build_slot_clarification(
                decision=decision,
                context=context,
                missing_slots=missing_slots or capability_slots,
                execution_request=request.to_dict(),
                reason="Required capabilities or arguments are not ready.",
            )
            text = clarification.text
            if any(failure.get("required_user_action") for failure in failures):
                text = self._format_capability_failures(request, failures)
            return EngineResult(
                action="clarify",
                label="DCC Execution",
                text=text,
                metadata={
                    "engine_path": "prompt_dispatch",
                    "result_type": "capability_failure",
                    "dcc_request": request.to_dict(),
                    "missing_capabilities": failures,
                    "missing_slots": missing_slots,
                    "selected_adapter": request.execution_environment,
                    "execution_plan": execution_plan,
                    "result_card": build_result_card(decision=decision, request=request.to_dict()),
                    "recovery_options": recovery_options(result_type="missing_capabilities"),
                    **clarification.to_metadata(),
                },
            )

        emit(ProgressEvent("argument_validation", "Arguments validated" if not request.missing_slots else "Arguments need input", 3, len(execution_plan)))
        if request.preview_only or request.operation_mode == "preview":
            result = adapter.preview(request, context)
        elif request.operation_mode == "query":
            result = adapter.query(request, context)
        else:
            result = adapter.execute(request, context)
        execution_plan = update_execution_plan(execution_plan, status=result.status, result_type=f"dcc_{result.status}")

        action = "answer"
        if result.status in {"confirmation_required", "missing_slots"}:
            action = "clarify"
        elif result.status in {"failed", "terminal_failure"}:
            action = "error"
        clarification_metadata = {}
        text = result.rendered_output or result.user_message
        if result.status == "missing_slots":
            from services.clarification_service import build_slot_clarification

            clarification = build_slot_clarification(
                decision=decision,
                context=context,
                missing_slots=list(result.missing_slots or request.missing_slots),
                execution_request=request.to_dict(),
                dispatch_result=result.to_dict(),
                reason="Known operation needs missing argument values before execution.",
            )
            text = clarification.text
            clarification_metadata = clarification.to_metadata()
        elif result.status == "confirmation_required":
            if (result.confirmation_request or {}).get("operation") == "scene.object_exists" and result.user_message:
                text = result.user_message
            else:
                from services.clarification_service import build_confirmation

                clarification = build_confirmation(
                    decision=decision,
                    context=context,
                    execution_request=request.to_dict(),
                    dispatch_result=result.to_dict(),
                )
                text = clarification.text
                clarification_metadata = clarification.to_metadata()
        return EngineResult(
            action=action,
            label="DCC Execution",
            text=text,
            metadata={
                "engine_path": "prompt_dispatch",
                "result_type": f"dcc_{result.status}",
                "dispatch_result": result.to_dict(),
                "dcc_request": request.to_dict(),
                "selected_adapter": request.execution_environment,
                "execution_plan": execution_plan,
                "result_card": build_result_card(
                    decision=decision,
                    request=request.to_dict(),
                    dispatch_result=result.to_dict(),
                ),
                "recovery_options": recovery_options(result_type=f"dcc_{result.status}", dispatch_result=result.to_dict()),
                **clarification_metadata,
            },
        )

    def _format_capability_failures(self, request, failures: list[dict]) -> str:
        lines = [
            "I resolved this as a DCC execution request, but it is not ready to run.",
            "",
            f"Host: `{request.execution_environment or 'missing'}`",
            f"Mode: `{request.operation_mode}`",
            f"Target: `{request.callable_name or request.target_identifier or 'missing'}`",
        ]
        if request.argument_schema.get("signature"):
            lines.append(f"Signature: `{request.argument_schema.get('signature')}`")
        if request.missing_slots:
            lines.append("Missing slots: " + ", ".join(f"`{slot}`" for slot in request.missing_slots))
        if failures:
            lines.append("")
            lines.append("Capability failures:")
            for failure in failures:
                lines.append(
                    f"- `{failure.get('capability')}`: {failure.get('current_state')}"
                    + (f" - {failure.get('required_user_action')}" if failure.get("required_user_action") else "")
                )
        return "\n".join(lines)


def default_route_handlers() -> dict[str, PromptRouteHandler]:
    from engine.providers import (
        ActionGraphProvider,
        ConnectionStatusProvider,
        ProjectHealthProvider,
        ProjectSearchProvider,
        TargetDiscoveryEditProvider,
    )

    return {
        "engine.project_health": ProviderRouteHandler(
            "ProjectHealthHandler",
            ProjectHealthProvider(),
            {CAP_ACTIVE_PROJECT, CAP_PROJECT_INDEX, CAP_PYTHON_SYMBOLS},
        ),
        "engine.project_search": ProviderRouteHandler(
            "ProjectSearchHandler",
            ProjectSearchProvider(),
            {CAP_ACTIVE_PROJECT, CAP_PROJECT_INDEX},
        ),
        "engine.connection_status": ProviderRouteHandler(
            "ConnectionStatusHandler",
            ConnectionStatusProvider(),
            set(),
        ),
        "engine.target_discovery": ProviderRouteHandler(
            "TargetDiscoveryHandler",
            TargetDiscoveryEditProvider(),
            {CAP_ACTIVE_PROJECT, CAP_PROJECT_INDEX, CAP_PYTHON_SYMBOLS},
        ),
        "engine.action_graph": ProviderRouteHandler(
            "WorkflowHandler",
            ActionGraphProvider(),
            {CAP_ACTIVE_PROJECT, CAP_PROJECT_INDEX, CAP_PYTHON_SYMBOLS, CAP_WORKFLOW_GRAPH},
        ),
        "ui.github_import": PassthroughRouteHandler(
            "GitHubHandler",
            "GitHub/repository ingestion is handled by the UI import flow.",
        ),
        "llm.chat": PassthroughRouteHandler(
            "LocalLLMHandler",
            "General chat should continue through the model router.",
            {CAP_LLM},
        ),
        "dcc.execution_pipeline": DccExecutionRouteHandler(),
        "dcc.prototype_pipeline": DccExecutionRouteHandler("DCCPrototypeHandler"),
        "unreal.capability_pipeline": DccExecutionRouteHandler("UnrealExecutionHandler"),
    }


class PromptDispatchService:
    """Single route-decision-to-handler orchestrator."""

    def __init__(self, handlers: dict[str, PromptRouteHandler] | None = None):
        self.handlers = handlers or default_route_handlers()

    def dispatch(
        self,
        decision: dict,
        context: RequestContext,
        emit: ProgressCallback,
        activity: ActivityCallback | None = None,
    ) -> EngineResult:
        started = time.perf_counter()
        try:
            from services.operation_memory_service import apply_operation_memory_to_decision

            memory = (context.extras or {}).get("operation_memory") or (context.extras or {}).get("active_operation_memory")
            if memory:
                decision = apply_operation_memory_to_decision(decision, memory)
        except Exception:
            pass
        try:
            from services.route_diagnostics_service import build_route_diagnostic_report

            decision["route_diagnostics"] = build_route_diagnostic_report(decision).to_dict()
        except Exception:
            pass
        goal_graph = dict(decision.get("task_graph") or {})
        goals = list(goal_graph.get("goals") or goal_graph.get("tasks") or [])
        goal_type = str(
            decision.get("goal_type")
            or goal_graph.get("goal_type")
            or ""
        ).lower()
        primary_goal = str(
            decision.get("primary_goal")
            or goal_graph.get("primary_goal")
            or goal_graph.get("goal")
            or ""
        )
        request_understanding = dict(decision.get("request_understanding") or {})

        if goal_graph and not bool(goal_graph.get("valid", True)):
            result = EngineResult(
                action="error",
                label="Request Understanding",
                text="The request goal graph is invalid and cannot be executed safely.",
                metadata={
                    "engine_path": "prompt_dispatch",
                    "result_type": "invalid_goal_graph",
                    "route_decision": decision,
                    "goal_graph": goal_graph,
                    "invalid_dependencies": list(goal_graph.get("invalid_dependencies") or []),
                    "duplicate_goal_ids": list(goal_graph.get("duplicate_goal_ids") or []),
                    "dependency_cycles": list(goal_graph.get("dependency_cycles") or []),
                },
            )
            self._record_metric(decision, result, started)
            return result

        completed_goal_ids = {
            str(value)
            for value in (
                (context.extras or {}).get("completed_goal_ids")
                or decision.get("completed_goal_ids")
                or []
            )
        }

        try:
            from services.prompt_task_splitter_service import next_achievable_goals

            ready_goals = next_achievable_goals(goal_graph, completed_goal_ids)
        except Exception:
            ready_goals = []
            for goal in list(goal_graph.get("ordered_goals") or goals):
                goal_id = str(goal.get("task_id") or goal.get("goal_id") or "")
                if not goal_id or goal_id in completed_goal_ids:
                    continue
                dependencies = {
                    str(value)
                    for value in (goal.get("depends_on") or [])
                }
                if dependencies.issubset(completed_goal_ids):
                    ready_goals.append(goal)

        decision = dict(decision)
        decision["task_graph"] = goal_graph
        decision["goal_graph"] = goal_graph
        decision["primary_goal"] = primary_goal
        decision["goal_type"] = goal_type
        decision["ready_goals"] = ready_goals
        decision["completed_goal_ids"] = sorted(completed_goal_ids)

        if ready_goals:
            decision["current_goal"] = dict(ready_goals[0])
            decision["current_goal_id"] = str(
                ready_goals[0].get("task_id")
                or ready_goals[0].get("goal_id")
                or ""
            )
        else:
            decision["current_goal"] = {}
            decision["current_goal_id"] = ""

        if activity and goal_graph:
            activity(
                ActivityEvent(
                    "request_goal_graph",
                    primary_goal or "Request goal graph",
                    (
                        f"{len(goals)} goal(s), "
                        f"{len(ready_goals)} currently achievable, "
                        f"{len(completed_goal_ids)} completed"
                    ),
                    status="ok",
                    metadata={
                        "framework": goal_graph.get("framework"),
                        "goal_type": goal_type,
                        "primary_route": goal_graph.get("primary_route"),
                        "terminal_goal_ids": list(goal_graph.get("terminal_goal_ids") or []),
                        "approval_goal_ids": list(goal_graph.get("approval_goal_ids") or []),
                    },
                )
            )
            for goal in goals[:12]:
                goal_id = str(goal.get("task_id") or goal.get("goal_id") or "")
                if goal_id in completed_goal_ids:
                    status = "done"
                elif any(
                    str(item.get("task_id") or item.get("goal_id") or "") == goal_id
                    for item in ready_goals
                ):
                    status = "ready"
                else:
                    status = "pending"
                activity(
                    ActivityEvent(
                        "request_goal",
                        str(goal.get("title") or goal_id or goal.get("action") or "Goal"),
                        str(goal.get("objective") or ""),
                        status=status,
                        metadata={
                            "goal": goal,
                            "primary_goal": primary_goal,
                            "goal_type": goal_type,
                        },
                    )
                )

        read_only_requested = bool(request_understanding.get("read_only_requested"))
        mutation_requested = bool(request_understanding.get("mutation_requested"))
        mutation_goal_ids = {
            str(value)
            for value in (goal_graph.get("mutation_goal_ids") or [])
        }
        current_goal = dict(decision.get("current_goal") or {})
        current_goal_id = str(decision.get("current_goal_id") or "")
        current_goal_mutates = bool(
            current_goal
            and (
                not bool(current_goal.get("read_only", True))
                or current_goal_id in mutation_goal_ids
                or str(current_goal.get("goal_type") or "").lower() == "modify"
                or str(current_goal.get("action") or "").lower() == "modify_code"
            )
        )
        graph_has_mutation = bool(mutation_goal_ids) or any(
            not bool(goal.get("read_only", True))
            for goal in goals
        )

        # Validate handler ownership against the canonical goal graph.
        # Target discovery may only own a real mutation goal.
        if (
            str(decision.get("route") or "") == "target_discovery"
            and (
                read_only_requested
                or not mutation_requested
                or not graph_has_mutation
                or (current_goal and not current_goal_mutates)
            )
        ):
            previous_route = str(decision.get("route") or "")
            previous_execution_route = str(decision.get("execution_route") or "")
            decision["route"] = "project_search"
            decision["provider"] = "project_search"
            decision["execution_route"] = "engine.project_search"
            decision["handler_id"] = "ProjectSearchProvider"
            decision["operation_mode"] = "query"
            decision["mutation_scope"] = "read_only"
            decision["requires_confirmation"] = False
            decision["can_execute_directly"] = True
            decision.setdefault("rejected_routes", [])
            if "target_discovery" not in decision["rejected_routes"]:
                decision["rejected_routes"].append("target_discovery")
            decision.setdefault("reasons", [])
            decision["reasons"].append(
                "Dispatcher corrected TargetDiscovery because the canonical "
                "goal graph does not expose an achievable mutation goal."
            )
            if activity:
                activity(
                    ActivityEvent(
                        "route_guard",
                        "Corrected handler ownership",
                        "Target discovery declined a non-mutating current goal.",
                        status="warn",
                        metadata={
                            "previous_route": previous_route,
                            "previous_execution_route": previous_execution_route,
                            "new_route": decision["route"],
                            "new_execution_route": decision["execution_route"],
                            "goal_type": goal_type,
                            "current_goal_id": current_goal_id,
                            "read_only_requested": read_only_requested,
                            "mutation_requested": mutation_requested,
                            "graph_has_mutation": graph_has_mutation,
                            "current_goal_mutates": current_goal_mutates,
                        },
                    )
                )

        # Teaching, explanation, comparison, and read-only generation must stay
        # on the LLM route even when project search is a supporting goal.
        if (
            goal_type in {"learn", "explain", "compare", "respond", "generate"}
            and not mutation_requested
            and str(decision.get("route") or "") == "project_search"
        ):
            previous_route = str(decision.get("route") or "")
            decision["route"] = "chat"
            decision["provider"] = "llm"
            decision["execution_route"] = "llm.chat"
            decision["handler_id"] = "LocalLLMHandler"
            decision["operation_mode"] = (
                "generate" if goal_type == "generate" else "respond"
            )
            decision["mutation_scope"] = "read_only"
            decision["requires_confirmation"] = False
            decision["can_execute_directly"] = True
            decision.setdefault("reasons", [])
            decision["reasons"].append(
                "Dispatcher preserved the terminal learning/generation goal; "
                "project search remains supporting context."
            )
            if activity:
                activity(
                    ActivityEvent(
                        "route_guard",
                        "Preserved terminal goal",
                        f"{previous_route} -> chat for goal type {goal_type}",
                        status="info",
                        metadata={
                            "goal_type": goal_type,
                            "primary_goal": primary_goal,
                            "ready_goal_ids": [
                                str(goal.get("task_id") or goal.get("goal_id") or "")
                                for goal in ready_goals
                            ],
                        },
                    )
                )

        execution_route = str(decision.get("execution_route") or "")
        handler = self.handlers.get(execution_route)
        if not handler:
            result = EngineResult(
                action="error",
                label="Prompt Dispatcher",
                text=f"No handler registered for execution route: {execution_route or '<missing>'}",
                metadata={
                    "engine_path": "prompt_dispatch",
                    "result_type": "dispatch_error",
                    "route_decision": decision,
                },
            )
            self._record_metric(decision, result, started)
            return result

        missing = self._missing_capabilities(handler.requires, decision, context)
        if missing:
            from services.clarification_service import build_slot_clarification

            clarification = build_slot_clarification(
                decision=decision,
                context=context,
                missing_slots=sorted(missing),
                reason="The route is known, but required application context is missing.",
            )
            result = EngineResult(
                action="clarify",
                label="Clarification Needed",
                text=clarification.text,
                metadata={
                    "engine_path": "prompt_dispatch",
                    "result_type": "missing_capabilities",
                    "route_decision": decision,
                    "missing_capabilities": sorted(missing),
                    "handler_id": handler.handler_id,
                    **clarification.to_metadata(),
                },
            )
            if activity:
                activity(
                    ActivityEvent(
                        "clarification",
                        "Missing execution capabilities",
                        ", ".join(sorted(missing)),
                        status="warn",
                        metadata={"handler_id": handler.handler_id},
                    )
                )
            self._record_metric(decision, result, started)
            return result

        emit(ProgressEvent("dispatch", f"Dispatching via {handler.handler_id}"))
        result = handler.execute(decision, context, emit, activity)
        metadata = dict(result.metadata or {})
        metadata.setdefault("route_decision", decision)
        metadata.setdefault("route_diagnostics", decision.get("route_diagnostics") or {})
        metadata.setdefault("handler_id", handler.handler_id)
        metadata.setdefault("goal_graph", decision.get("goal_graph") or decision.get("task_graph") or {})
        metadata.setdefault("current_goal", decision.get("current_goal") or {})
        metadata.setdefault("current_goal_id", decision.get("current_goal_id") or "")
        metadata.setdefault("ready_goals", decision.get("ready_goals") or [])
        try:
            from services.operation_memory_service import update_operation_memory

            metadata["operation_memory"] = update_operation_memory(
                (context.extras or {}).get("operation_memory") or (context.extras or {}).get("active_operation_memory"),
                route_decision=decision,
                execution_request=metadata.get("dcc_request") or {},
                binding=(context.extras or {}).get("clarification_binding") or {},
                result=metadata.get("dispatch_result") or {"result_type": metadata.get("result_type")},
            )
        except Exception:
            pass
        result = EngineResult(
            action=result.action,
            label=result.label,
            text=result.text,
            prompt=result.prompt,
            metadata=metadata,
        )
        self._record_metric(decision, result, started)
        return result

    def _missing_capabilities(self, requires: set[str], decision: dict, context: RequestContext) -> set[str]:
        missing: set[str] = set()
        if CAP_ACTIVE_PROJECT in requires and not context.project_roots:
            missing.add(CAP_ACTIVE_PROJECT)
        if CAP_PROJECT_INDEX in requires and "missing" in (context.index_state or "").lower():
            missing.add(CAP_PROJECT_INDEX)
        if (
            CAP_DCC_CONNECTION in requires
            and decision.get("requires_confirmation")
            and not (decision.get("approved") or decision.get("confirmation_accepted"))
        ):
            return missing
        if (
            CAP_DCC_CONNECTION in requires
            and decision.get("requires_dcc_connection")
            and not (context.extras or {}).get("window")
            and not self._has_direct_dcc_connection(decision)
        ):
            missing.add(CAP_DCC_CONNECTION)
        return missing

    def _has_direct_dcc_connection(self, decision: dict) -> bool:
        host = str(decision.get("execution_environment") or decision.get("host") or "").strip().lower()
        try:
            from services.dcc_execution_service import _maya_direct_bridge_available, _unreal_direct_bridge_available
        except Exception:
            return False
        if host == "maya":
            return bool(_maya_direct_bridge_available())
        if host == "unreal":
            return bool(_unreal_direct_bridge_available())
        return False

    def _missing_capability_text(self, decision: dict, missing: set[str]) -> str:
        lines = [
            "I know which route this prompt belongs to, but I need one more piece before executing it.",
            "",
            f"Route: `{decision.get('route')}`",
            f"Mode: `{decision.get('operation_mode')}`",
            "Missing: " + ", ".join(f"`{item}`" for item in sorted(missing)),
        ]
        if decision.get("missing_info"):
            lines.append("Missing slots: " + ", ".join(f"`{item}`" for item in decision.get("missing_info") or []))
        return "\n".join(lines)

    def _record_metric(self, decision: dict, result: EngineResult, started: float) -> None:
        try:
            from services.routing_metrics_service import record_route_metric

            record_route_metric(
                {
                    "route": decision.get("route"),
                    "execution_route": decision.get("execution_route"),
                    "handler_id": (result.metadata or {}).get("handler_id"),
                    "selected_adapter": (result.metadata or {}).get("selected_adapter"),
                    "confidence": decision.get("confidence"),
                    "operation_mode": decision.get("operation_mode"),
                    "risk_level": decision.get("risk_level"),
                    "goal_type": decision.get("goal_type"),
                    "primary_goal": decision.get("primary_goal"),
                    "current_goal_id": decision.get("current_goal_id"),
                    "goal_count": len(
                        (
                            decision.get("goal_graph")
                            or decision.get("task_graph")
                            or {}
                        ).get("goals")
                        or []
                    ),
                    "ready_goal_count": len(decision.get("ready_goals") or []),
                    "result_type": result.result_type,
                    "action": result.action,
                    "capability_failure": result.result_type in {"capability_failure", "missing_capabilities"},
                    "missing_argument_resolution": bool((result.metadata or {}).get("missing_slots")),
                    "confirmation_requested": result.result_type in {"dcc_confirmation_required"},
                    "clarification_type": (result.metadata or {}).get("clarification_type"),
                    "clarification_rendering": (result.metadata or {}).get("clarification_rendering"),
                    "clarification_model_tier": (result.metadata or {}).get("clarification_model_tier"),
                    "clarification_slot_count": len(((result.metadata or {}).get("clarification") or {}).get("unresolved_slot_names") or []),
                    "deterministic_clarification": (result.metadata or {}).get("clarification_rendering") == "deterministic",
                    "enterprise_clarification": (result.metadata or {}).get("clarification_model_tier") == "enterprise",
                    "automatic_slot_resolution": len([slot for slot in (((result.metadata or {}).get("clarification") or {}).get("slots") or []) if slot.get("state") == "resolved"]),
                    "clarification_avoidance": bool((result.metadata or {}).get("operation_memory") and not (result.metadata or {}).get("pending_clarification")),
                    "resume_success": bool((result.metadata or {}).get("operation_memory") and result.action in {"answer", "action_plan"}),
                    "recovery_option_count": len((result.metadata or {}).get("recovery_options") or []),
                    "follow_up_suggestion_count": len(((result.metadata or {}).get("result_card") or {}).get("follow_up_suggestions") or []),
                    "preview": str(decision.get("operation_mode") or "") == "preview",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "used_llm": bool(result.action == "send_raw" or decision.get("model_capability") not in {"none", "none_deterministic"}),
                }
            )
        except Exception:
            pass


# --- Prompt Staging Support (merged from prompt_staging_service.py) ---

@dataclass
class PromptDraft:
    user_text: str = ""
    context_items: list[ContextItem] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.user_text) // 4) + sum(item.estimate_tokens() for item in self.context_items)

    def context_badge(self) -> str:
        if not self.context_items:
            return "Staged context: none"
        by_kind: dict[str, int] = {}
        for item in self.context_items:
            by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        parts = [f"{kind}×{count}" for kind, count in sorted(by_kind.items())]
        return f"Staged context: {', '.join(parts)} | ~{self.token_estimate:,} tokens"

    def render_for_composer(self) -> str:
        """Return reviewable text inserted into the prompt composer."""
        lines = []
        if self.user_text.strip():
            lines.append(self.user_text.strip())
            lines.append("")
        if self.context_items:
            lines.append("----- STAGED CONTEXT: review before sending -----")
            for index, item in enumerate(self.context_items, start=1):
                lines.append(f"\n[{index}] {item.title}")
                lines.append(item.to_prompt_text())
            lines.append("----- END STAGED CONTEXT -----")
        return "\n".join(lines).strip()

    def render_for_model(self) -> str:
        """Return the final prompt after user presses Send."""
        return self.render_for_composer()

    def to_json(self) -> str:
        return json.dumps({
            "user_text": self.user_text,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "token_estimate": self.token_estimate,
            "context_items": [
                {
                    "source": item.source,
                    "title": item.title,
                    "body": item.body,
                    "kind": item.kind,
                    "priority": item.priority,
                    "metadata": item.metadata,
                }
                for item in self.context_items
            ],
        }, indent=2, default=str)


class PromptStagingService:
    def __init__(self, registry: ContextProviderRegistry | None = None):
        self.registry = registry or ContextProviderRegistry()

    def build_draft(
        self,
        user_text: str,
        *,
        project_root: str | None = None,
        include_unreal: bool = True,
        include_code: bool = True,
        include_cpp_wrappers: bool = True,
        max_items: int = 8,
    ) -> PromptDraft:
        items = self.registry.collect(user_text, project_root=project_root)
        if not include_unreal:
            items = [item for item in items if not item.source.startswith("unreal")]
        if not include_code:
            items = [item for item in items if item.source != "code_index"]
        if not include_cpp_wrappers:
            items = [item for item in items if item.source != "cpp_wrapper"]

        return PromptDraft(
            user_text=user_text,
            context_items=items[:max_items],
        )
