"""Request providers for The Entire World Intelligence Engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .progress_events import ActivityEvent, EngineResult, ProgressEvent
from .request_context import RequestContext

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]


class RequestProvider(Protocol):
    name: str

    def can_handle(self, context: RequestContext) -> bool: ...
    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult: ...


def _emit(emit: ProgressCallback, stage: str, message: str, current: int = 0, total: int = 0, detail: str = "") -> None:
    emit(ProgressEvent(stage=stage, message=message, current=current, total=total, detail=detail))


def _activity(activity: ActivityCallback | None, kind: str, title: str, detail: str = "", **kwargs) -> None:
    if activity:
        activity(ActivityEvent(kind=kind, title=title, detail=detail, **kwargs))


def _route_decision(context: RequestContext) -> dict:
    return (context.extras or {}).get("prompt_route_decision") or {}


def _route_scope(context: RequestContext) -> str | None:
    decision = _route_decision(context)
    filters = decision.get("index_filters") or {}
    scope = filters.get("scope")
    return str(scope) if scope else None


def _augment_explicit_file_candidates(context: RequestContext, candidates: list[dict]) -> list[dict]:
    """Ensure explicitly named files reach evidence ranking even when symbol search is empty."""
    from pathlib import Path
    from services.target_entity_service import extract_target_entities

    augmented = [dict(item) for item in candidates if isinstance(item, dict)]
    known = {
        str(item.get("path") or "").replace("\\", "/").casefold()
        for item in augmented
        if item.get("path")
    }
    explicit_files = [
        entity for entity in extract_target_entities(context.text)
        if entity.kind in {"filename", "path"}
    ]
    if not explicit_files:
        return augmented

    available_paths = [context.current_file_path, *list(context.open_file_paths or ())]
    for entity in explicit_files:
        wanted_name = Path(entity.value).name.casefold()
        for available_path in available_paths:
            if not available_path or Path(available_path).name.casefold() != wanted_name:
                continue
            normalized = str(available_path).replace("\\", "/").casefold()
            if normalized not in known:
                augmented.insert(0, {
                    "path": str(available_path),
                    "score": 0,
                    "symbols": [],
                    "chunks": [],
                    "candidate_source": "explicit_open_file",
                })
                known.add(normalized)

        # Fall back to the canonical indexed-file matcher when the file is not open.
        try:
            from services.project_search_service import _matching_file_row
            row = _matching_file_row(context.current_file_path, entity.value)
        except Exception:
            row = None
        if row:
            path = str(row.get("path") or row.get("rel_path") or "")
            normalized = path.replace("\\", "/").casefold()
            if path and normalized not in known:
                augmented.insert(0, {
                    "path": path,
                    "score": 0,
                    "symbols": [],
                    "chunks": [],
                    "candidate_source": "explicit_index_file",
                })
                known.add(normalized)
    return augmented


@dataclass
class ActionGraphProvider:
    name: str = "action_graph"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        try:
            from services.action_planner_service import plan_prompt_to_action_graph, should_route_to_action_graph
            from services.project_service import is_target_discovery_edit_request
            if is_target_discovery_edit_request(context.text):
                return False
            plan = plan_prompt_to_action_graph(context.text, list(context.project_roots or []))
            return (
                plan.get("intent") not in {"needs_llm_planner", "project_search"}
                or should_route_to_action_graph(context.text, list(context.project_roots or []))
            )
        except Exception:
            return False

    def _plan_from_route_decision(self, context: RequestContext, route_decision: dict) -> dict | None:
        operations = list(route_decision.get("operations") or [])
        if not operations:
            return None
        actions = []
        previous_action_id = ""
        for index, operation in enumerate(operations, start=1):
            operation_key = str(operation.get("operation") or "")
            requires_confirmation = bool(operation.get("requires_confirmation"))
            is_verify = operation_key in {"scene.find_joint", "scene.object_exists"}
            action_type = "validate_dcc_call" if is_verify else "execute_dcc"
            action_id = str(operation.get("id") or f"action_{index}")
            action = {
                "id": action_id,
                "type": action_type,
                "title": str(operation.get("label") or operation_key or action_type),
                "description": str(operation.get("condition") or ""),
                "args": {
                    "host": str(operation.get("host") or route_decision.get("host") or ""),
                    "operation": operation_key,
                    "callable": str(operation.get("callable") or ""),
                    "params": dict(operation.get("args") or {}),
                    "produces": list(operation.get("produces") or []),
                    "requires": list(operation.get("requires") or []),
                    "evidence": list(operation.get("evidence") or []),
                },
                "depends_on": [previous_action_id] if previous_action_id else [],
                "requires_approval": requires_confirmation,
                "source": "prompt_route_prerequisite_graph",
            }
            actions.append(action)
            previous_action_id = action_id
        return {
            "goal": context.text,
            "intent": str(route_decision.get("intent_category") or "action_graph"),
            "planner": "deterministic_prompt_route",
            "confidence": float(route_decision.get("confidence") or 0.0),
            "diagnostics": list(route_decision.get("reasons") or []),
            "actions": actions,
        }

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from services.action_planner_service import plan_prompt_to_action_graph, should_route_to_action_graph
        from services.action_graph_service import format_action_graph
        from services.action_execution_engine import ActionExecutionEngine

        _emit(emit, "action_plan", "Compiling deterministic action graph")
        route_decision = _route_decision(context)
        plan = self._plan_from_route_decision(context, route_decision) if route_decision else None
        if not plan:
            plan = plan_prompt_to_action_graph(context.text, list(context.project_roots or []))
        if plan.get("intent") == "needs_llm_planner" and should_route_to_action_graph(context.text, list(context.project_roots or [])):
            from services.intent_clarification_service import build_action_graph_clarification

            _emit(emit, "action_plan", "Structured request needs clarification", 1, 1)
            _activity(
                activity,
                "clarification",
                "Action graph needs confirmation",
                "The prompt looked structured, so Unreal/DCC execution was blocked until the user confirms the intended graph.",
                status="warn",
            )
            clarification = build_action_graph_clarification(
                context.text,
                plan,
                project_roots=list(context.project_roots or []),
            )
            return EngineResult(
                action="answer",
                label="Clarification Needed",
                text=clarification["text"],
                metadata={"engine_path": self.name, "result_type": "action_graph_clarification", "plan": plan, "clarification": clarification},
            )
        engine = ActionExecutionEngine()
        validation = engine.validate_plan(plan)
        approval = engine.analyze_approval_requirements(plan)
        _activity(
            activity,
            "plan",
            "Action graph compiled",
            f"{len(plan.get('actions') or [])} action(s), approval required: {approval.get('approval_required')}",
            status="ok" if validation.get("valid") else "warn",
            metadata={"intent": plan.get("intent")},
        )
        _emit(emit, "action_plan", "Action graph ready", 1, 1)
        return EngineResult(
            action="action_plan",
            label="Action Graph",
            text=format_action_graph(plan),
            metadata={
                "engine_path": self.name,
                "result_type": "action_plan",
                "plan": plan,
                "validation": validation,
                "approval": approval,
            },
        )


@dataclass
class ConnectionStatusProvider:
    name: str = "connection_status"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        lower = (context.text or "").lower()
        return "connected" in lower or "connection" in lower

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        _emit(emit, "connection_status", "Reading cached connection status")
        rows = []
        extras = context.extras or {}
        for key in ("connected_application_status", "connected_application_rows", "status_rows"):
            value = extras.get(key)
            if isinstance(value, list):
                rows = value
                break
        if rows:
            lines = ["Cached connection status:"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                state = "LIVE" if row.get("connected") else "SETUP"
                name = row.get("name") or row.get("id") or "Unknown"
                mode = row.get("mode") or ""
                lines.append(f"- {name}: {state}" + (f" ({mode})" if mode else ""))
            text = "\n".join(lines)
        else:
            text = (
                "I do not have a cached connection snapshot in this request.\n\n"
                "This was treated as a status question, not an action graph. Use the status bar or "
                "`Tools > Connected Apps > Capability Status` to refresh live bridge/account details."
            )
        _emit(emit, "connection_status", "Connection status ready", 1, 1)
        _activity(activity, "result", "Connection status answered", "Returned cached/read-only status without compiling a workflow graph.", status="ok")
        return EngineResult(
            action="answer",
            label="Connection Status",
            text=text,
            metadata={"engine_path": self.name, "result_type": "connection_status"},
        )


@dataclass
class ProjectHealthProvider:
    name: str = "project_health"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        try:
            from services.project_service import is_project_health_request
            return is_project_health_request(context.text)
        except Exception:
            return False

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from services.project_service import answer_project_health_request
        _emit(emit, "project_health", "Checking project health cache")
        _activity(activity, "tool", "Project Health cache", "Checking cached dead-code/import/file analysis", status="info")
        answer = answer_project_health_request(context.text, active_path=context.current_file_path, use_cache=True)
        _emit(emit, "project_health", "Project health analysis ready", 1, 1)
        _activity(activity, "result", "Project health result ready", "Returned graph/static analysis without sending a giant scan to the LLM", status="ok")
        return EngineResult(
            action="answer",
            label="Project Health",
            text=answer,
            metadata={"engine_path": self.name, "result_type": "project_health"},
        )


@dataclass
class TargetDiscoveryEditProvider:
    name: str = "target_discovery"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        try:
            from services.project_service import is_target_discovery_edit_request
            return is_target_discovery_edit_request(context.text)
        except Exception:
            return False

    def _needs_clarification(self, discovery: dict) -> bool:
        confidence = discovery.get("confidence")
        candidates = discovery.get("candidates") or []
        if confidence in {"none", "low"}:
            return True
        if len(candidates) >= 2:
            first = int(candidates[0].get("score") or 0)
            second = int(candidates[1].get("score") or 0)
            if first and second and (first - second) <= 6:
                return True
        return False

    def _clarification_text(self, discovery: dict) -> str:
        candidates = discovery.get("candidates") or []
        if candidates:
            lines = [
                "I found more than one plausible edit target, so I should confirm before changing files.",
                "",
                "Best candidate files:",
            ]
        else:
            terms = ", ".join(str(term) for term in discovery.get("terms") or []) or "the requested concepts"
            return (
                "I could not find a confident edit target in the project index yet, so I should not guess.\n\n"
                f"Search terms: {terms}\n\n"
                "Reply with the file, symbol, or area you want me to modify, or ask me to broaden the search."
            )
        for i, item in enumerate(candidates[:5], 1):
            lines.append(f"{i}. `{item.get('path')}` — score {item.get('score')}")
            symbols = item.get("symbols") or []
            if symbols:
                considered = []
                for sym in symbols[:4]:
                    considered.append(f"{sym.get('kind')} `{sym.get('qualname') or sym.get('name')}` lines {sym.get('start_line')}-{sym.get('end_line')}")
                lines.append("   Considered: " + "; ".join(considered))
        lines.extend([
            "",
            "Which file should I modify? Reply with a number, a path, or say `create a new file`.",
        ])
        return "\n".join(lines)

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from services.project_service import (
            discover_edit_targets,
            format_edit_target_context,
            build_project_edit_target_prompt,
        )
        from services.target_resolution_service import resolve_target_candidates

        _emit(emit, "target_discovery", "Finding likely edit targets")
        _activity(activity, "intent", "Project edit request", context.text, status="info")
        _activity(activity, "tool", "Project index", "Searching symbols, usages, and chunks for target concepts", status="info")
        discovery = discover_edit_targets(
            context.text,
            active_path=context.current_file_path,
            limit=8,
            scope=_route_scope(context),
        )
        candidates = _augment_explicit_file_candidates(
            context,
            list(discovery.get("candidates") or []),
        )
        resolution = resolve_target_candidates(
            context.text,
            candidates,
            active_file=context.current_file_path,
            open_files=context.open_file_paths,
            operation_memory=(context.extras or {}).get("operation_memory")
            or (context.extras or {}).get("active_operation_memory"),
            allowed_roots=context.project_roots,
        )
        ranked_candidates = list(resolution.candidates or [])
        _emit(emit, "target_discovery", "Ranking target files", len(ranked_candidates), 8)

        # Preserve symbols/chunks from the original discovery records while using
        # evidence ranking as the authority for order and selection.
        original_by_path = {
            str(item.get("path") or "").replace("\\", "/").casefold(): item
            for item in candidates
            if isinstance(item, dict) and item.get("path")
        }
        ordered_candidates: list[dict] = []
        for idx, ranked in enumerate(ranked_candidates[:8], start=1):
            path = str(ranked.get("path") or "")
            original = dict(original_by_path.get(path.replace("\\", "/").casefold()) or {})
            merged = dict(original)
            merged.update({
                "path": path,
                "score": ranked.get("score", original.get("score", 0)),
                "evidence_confidence": ranked.get("confidence", 0),
                "evidence_signals": list(ranked.get("signals") or []),
                "excluded": bool(ranked.get("excluded", False)),
                "exclusion_reason": str(ranked.get("exclusion_reason") or ""),
            })
            ordered_candidates.append(merged)
            symbols = merged.get("symbols") or []
            symbol_items = [
                f"{sym.get('kind')} {sym.get('qualname') or sym.get('name')} lines {sym.get('start_line')}-{sym.get('end_line')}"
                for sym in symbols[:6]
            ]
            top_signals = [
                f"{float(signal.get('score') or 0):+.0f} {signal.get('reason') or signal.get('key') or ''}"
                for signal in list(ranked.get("signals") or [])[:5]
            ]
            _activity(
                activity,
                "candidate",
                f"Candidate target #{idx}",
                "Evidence-ranked project target",
                status="ok" if path == resolution.selected_path else "info",
                path=path,
                score=float(ranked.get("score") or 0),
                items=[*top_signals, *symbol_items],
                metadata={
                    "candidate_index": idx,
                    "confidence": ranked.get("confidence"),
                    "signals": ranked.get("signals") or [],
                    "selected": path == resolution.selected_path,
                },
            )

        discovery["candidates"] = ordered_candidates
        discovery["target_resolution"] = resolution.to_dict()
        discovery["evidence_ranking"] = ranked_candidates

        if resolution.status != "selected":
            _activity(
                activity,
                "clarification",
                "Clarification needed",
                "Evidence ranking could not safely select one edit target.",
                status="warn",
                metadata={"target_resolution": resolution.to_dict()},
            )
            return EngineResult(
                action="clarify",
                label="Clarification Needed",
                text=resolution.clarification_prompt or self._clarification_text(discovery),
                metadata={
                    "engine_path": self.name,
                    "result_type": "clarification",
                    "discovery": discovery,
                    "target_resolution": resolution.to_dict(),
                },
            )

        selected_path = resolution.selected_path
        selected_candidate = next(
            (item for item in ordered_candidates if str(item.get("path") or "") == selected_path),
            {"path": selected_path, "score": 0, "symbols": [], "chunks": []},
        )
        discovery["best_target"] = selected_candidate
        discovery["confidence"] = "high"
        discovery["selected_path"] = selected_path

        discovery_context = format_edit_target_context(discovery)
        _emit(emit, "prompt", "Building grounded edit prompt")
        prompt = build_project_edit_target_prompt(
            context.text,
            discovery_context,
            active_path=selected_path or context.current_file_path,
        )
        _emit(emit, "prompt", "Edit prompt ready", 1, 1)
        _activity(
            activity,
            "plan",
            "Planned edit target",
            "Preparing patch-style edit prompt from evidence-ranked target.",
            status="ok",
            path=selected_path,
            score=float(selected_candidate.get("score") or 0),
            metadata={
                "target_confidence": resolution.confidence,
                "target_reasons": resolution.reasons,
            },
        )
        return EngineResult(
            action="send_raw",
            label="Project Target Edit",
            prompt=prompt,
            text=(
                "Target discovery complete. Sending grounded edit prompt to the coding model.\n"
                f"Selected: {selected_path}\n"
                f"Target confidence: {resolution.confidence:.0%}\n"
                f"Candidates: {len(ordered_candidates)}"
            ),
            metadata={
                "engine_path": self.name,
                "result_type": "target_edit",
                "discovery": discovery,
                "target_resolution": resolution.to_dict(),
                "selected_target": selected_path,
            },
        )


@dataclass
class ProjectSearchProvider:
    name: str = "project_search"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        try:
            from services.project_search_service import is_project_scope_request
            return is_project_scope_request(context.text)
        except Exception:
            return False

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from services.project_search_service import (
            answer_project_dependency_question,
            answer_simple_project_index_question,
            build_deterministic_project_search_answer,
            gather_project_search_context,
            should_deepen_project_search,
        )
        _emit(emit, "project_search", "Searching project index")
        _activity(activity, "tool", "Project index", f"Query: {context.text}", status="info")

        direct_answer = answer_simple_project_index_question(
            context.text, active_path=context.current_file_path
        ) or answer_project_dependency_question(
            context.text, active_path=context.current_file_path
        )
        if direct_answer:
            _emit(emit, "project_search", "Project index answer ready", 1, 1)
            _activity(
                activity,
                "result",
                "Project index answered directly",
                "Returned deterministic indexed facts without LLM routing",
                status="ok",
            )
            return EngineResult(
                action="answer",
                label="Project Index",
                text=direct_answer,
                metadata={
                    "engine_path": self.name,
                    "result_type": "project_index_direct",
                    "deep_search_candidate": should_deepen_project_search(context.text, direct_answer),
                    "deep_search_query": context.text,
                    "deep_search_scope": _route_scope(context),
                },
            )

        project_context = gather_project_search_context(
            context.text,
            active_path=context.current_file_path,
            limit=120,
            scope=_route_scope(context),
        )
        _emit(emit, "project_search", "Project evidence gathered", 1, 1)
        _activity(activity, "result", "Project evidence gathered", "Returning indexed evidence directly without LLM routing", status="ok")
        answer = build_deterministic_project_search_answer(
            context.text,
            context.current_file_path,
            project_context,
        )
        return EngineResult(
            action="answer",
            label="Project Search",
            text=answer,
            metadata={
                "engine_path": self.name,
                "result_type": "project_search_direct",
                "deep_search_candidate": should_deepen_project_search(context.text, answer),
                "deep_search_query": context.text,
                "deep_search_scope": _route_scope(context),
            },
        )


def default_providers() -> list[RequestProvider]:
    return [
        ConnectionStatusProvider(),
        ProjectHealthProvider(),
        TargetDiscoveryEditProvider(),
        ActionGraphProvider(),
        ProjectSearchProvider(),
    ]
