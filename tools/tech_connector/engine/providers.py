"""Request providers for The Entire World Intelligence Engine."""

from __future__ import annotations

from dataclasses import dataclass
import time
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


def _is_conversational_file_reference(text: str) -> bool:
    import re
    return bool(re.search(
        r"\b(?:in|inside|within|from)\s+(?:that|this|the previous|the selected|the found)\s+file\b|"
        r"\b(?:that|this|the previous|the selected|the found)\s+file\b",
        str(text or ""), re.IGNORECASE,
    ))


def _selected_file_from_context(context: RequestContext) -> str:
    extras = context.extras or {}
    workspace = extras.get("conversation_workspace") or {}
    if workspace:
        try:
            from tech_connector.services.conversation_workspace_service import resolve_reference, workspace_from_dict

            resolution = resolve_reference(workspace, context.text, kind="file")
            if resolution.status == "resolved":
                current = workspace_from_dict(workspace)
                entity = current.entities.get(resolution.entity_id)
                if entity and entity.ref:
                    return entity.ref
        except Exception:
            pass
    decision = _route_decision(context)
    reference = decision.get("reference_resolution") or {}
    values = [
        decision.get("resolved_target_file"), decision.get("target_file"), decision.get("file"),
        reference.get("resolved_value") if isinstance(reference, dict) else "",
    ]
    memory = extras.get("operation_memory") or extras.get("active_operation_memory") or {}
    if isinstance(memory, dict):
        values.extend([memory.get("selected_file"), memory.get("recent_file"), memory.get("active_file")])
        slots = memory.get("resolved_slots") or {}
        if isinstance(slots, dict):
            values.extend([slots.get("target_file"), slots.get("file"), slots.get("selected_file")])
    for value in values:
        if str(value or "").strip():
            return str(value)
    return ""


def _resolved_context_file_path(context: RequestContext, value: str) -> str:
    """Resolve a remembered relative file against the request project roots."""
    from pathlib import Path

    raw = str(value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return str(path)
    for root in context.project_roots or ():
        candidate = Path(root) / path
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return raw


def _extract_selected_file(answer: str, fallback: str = "") -> str:
    import re
    text = str(answer or "")
    for pattern in (
        r"Best match:\s*`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))`?(?:\s|$)",
        r"^\s*`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))`?\s*$",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return str(fallback or "")


def _extract_project_answer_files(answer: str, fallback: str = "") -> list[str]:
    import re

    text = str(answer or "")
    found: list[str] = []
    patterns = (
        r"`([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))`",
        r"(?<![\w./\\-])([A-Za-z]:[\\/][^\s`]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))",
        r"(?<![\w./\\-])([A-Za-z0-9_./\\-]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = match.group(1).strip("` ,.;:")
            if value and value not in found:
                found.append(value)
    if fallback and fallback not in found:
        found.insert(0, fallback)
    return found[:12]


def _project_search_workspace_update(answer: str, *, primary_file: str = "", source: str = "project_search") -> dict:
    try:
        from tech_connector.services.conversation_workspace_service import file_entity_payload, normalize_entity

        files = _extract_project_answer_files(answer, primary_file)
        entities = []
        selected_ids = []
        primary_id = ""
        for index, path in enumerate(files):
            payload = file_entity_payload(path, source=source, confidence=0.98 if index == 0 else 0.9)
            entity = normalize_entity(payload)
            entities.append(entity.to_dict())
            selected_ids.append(entity.entity_id)
            if not primary_id:
                primary_id = entity.entity_id
        return {
            "entities": entities,
            "primary_entity_ids": [primary_id] if primary_id else [],
            "selected_entity_ids": selected_ids,
            "result_summary": "Project search result files",
            "source": source,
        }
    except Exception:
        return {}


def _augment_explicit_file_candidates(context: RequestContext, candidates: list[dict]) -> list[dict]:
    """Ensure explicitly named files reach evidence ranking even when symbol search is empty."""
    from pathlib import Path
    from tech_connector.services.target_entity_service import extract_target_entities

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
            from tech_connector.services.project_search_service import _matching_file_row
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


def _is_import_coverage_request(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        __import__("re").search(
            r"\b(?:files?|modules?)\s+(?:(?:are|is)\s+)?(?:not|never)\s+(?:being\s+)?imported\b|"
            r"\b(?:files?|modules?)\s+(?:aren['’]?t|isn['’]?t)\s+imported\b|"
            r"\bunimported\s+(?:files?|modules?)\b",
            lower,
        )
    )


@dataclass
class ImportCoverageProvider:
    """First-class deterministic provider for inbound-import coverage."""

    name: str = "import_coverage"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision and str(route_decision.get("execution_route") or "") == "engine.import_coverage":
            return True
        if route_decision and str(route_decision.get("provider") or "") == self.name:
            return True
        return _is_import_coverage_request(context.text)

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from tech_connector.services.prompt_dispatch_service import PromptDispatchService

        decision = dict(_route_decision(context) or {})
        decision.update({
            "route": "import_coverage",
            "provider": "import_coverage",
            "execution_route": "engine.import_coverage",
            "handler_id": "ImportCoverageHandler",
            "intent_category": "code_health",
            "operation_mode": "analyze_import_coverage",
            "target_type": "directory",
            "mutation_scope": "read_only",
            "requires_confirmation": False,
            "can_execute_directly": True,
        })
        return PromptDispatchService().dispatch(decision, context, emit, activity)


@dataclass
class ActionGraphProvider:
    name: str = "action_graph"

    def can_handle(self, context: RequestContext) -> bool:
        route_decision = _route_decision(context)
        if route_decision:
            return route_decision.get("provider") == self.name
        try:
            from tech_connector.services.action_planner_service import plan_prompt_to_action_graph, should_route_to_action_graph
            from tech_connector.services.project_service import is_target_discovery_edit_request
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
        from tech_connector.services.action_planner_service import plan_prompt_to_action_graph, should_route_to_action_graph
        from tech_connector.services.action_graph_service import format_action_graph
        from tech_connector.services.action_execution_engine import ActionExecutionEngine

        _emit(emit, "action_plan", "Compiling deterministic action graph")
        route_decision = _route_decision(context)
        plan = self._plan_from_route_decision(context, route_decision) if route_decision else None
        if not plan:
            plan = plan_prompt_to_action_graph(context.text, list(context.project_roots or []))
        if plan.get("intent") == "needs_llm_planner" and should_route_to_action_graph(context.text, list(context.project_roots or [])):
            from tech_connector.services.prompt_intent_service import build_action_graph_clarification

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
            from tech_connector.services.project_service import is_project_health_request
            return is_project_health_request(context.text)
        except Exception:
            return False

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from tech_connector.services.project_service import answer_project_health_request
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
            understanding = dict(route_decision.get("request_understanding") or {})
            if understanding:
                if bool(understanding.get("read_only_requested")):
                    return False
                if not bool(understanding.get("mutation_requested")):
                    return False
            return route_decision.get("provider") == self.name
        try:
            from tech_connector.services.project_service import is_target_discovery_edit_request
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
        from tech_connector.services.project_service import (
            discover_edit_targets,
            format_edit_target_context,
            build_project_edit_target_prompt,
        )
        from tech_connector.services.target_resolution_service import resolve_target_candidates

        route_decision = _route_decision(context)
        understanding = dict(route_decision.get("request_understanding") or {})
        read_only_requested = bool(understanding.get("read_only_requested"))
        mutation_requested = bool(understanding.get("mutation_requested"))

        if understanding and (read_only_requested or not mutation_requested):
            _activity(
                activity,
                "route_guard",
                "Target discovery rejected request",
                "The canonical request understanding is read-only or contains no mutation.",
                status="warn",
                metadata={
                    "read_only_requested": read_only_requested,
                    "mutation_requested": mutation_requested,
                    "preferred_route": "project_search",
                },
            )
            return EngineResult(
                action="error",
                label="Target Discovery",
                text=(
                    "TargetDiscoveryHandler refused this request because it is read-only. "
                    "The dispatcher should route it through ProjectSearchHandler."
                ),
                metadata={
                    "engine_path": self.name,
                    "result_type": "route_contract_rejected",
                    "reroute": True,
                    "preferred_route": "project_search",
                    "request_understanding": understanding,
                },
            )

        _emit(emit, "target_discovery", "Finding likely edit targets")
        _activity(activity, "intent", "Project edit request", context.text, status="info")
        _activity(activity, "tool", "Project index", "Searching symbols, usages, and chunks for target concepts", status="info")
        discovery_started = time.perf_counter()
        _emit(emit, "target_discovery", "Starting indexed target discovery")
        discovery = discover_edit_targets(
            context.text,
            active_path=context.current_file_path,
            limit=8,
            scope=_route_scope(context),
        )
        discovery_elapsed = time.perf_counter() - discovery_started
        _emit(
            emit,
            "target_discovery",
            f"Indexed target discovery finished in {discovery_elapsed:.2f}s",
        )
        _activity(
            activity,
            "performance",
            "Target discovery completed",
            f"discover_edit_targets finished in {discovery_elapsed:.2f}s",
            status="ok" if discovery_elapsed < 5.0 else "warn",
            metadata={"duration_seconds": round(discovery_elapsed, 3)},
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
            from tech_connector.services.project_search_service import is_project_scope_request
            return is_project_scope_request(context.text)
        except Exception:
            return False

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from tech_connector.services.project_search_service import (
            answer_project_dependency_question,
            answer_simple_project_index_question,
            build_deterministic_project_search_answer,
            gather_project_search_context,
            should_deepen_project_search,
        )
        _emit(emit, "project_search", "Searching project index")
        try:
            from tech_connector.services.prompt_task_splitter_service import normalize_prompt_text
            query_text = normalize_prompt_text(context.text)
        except Exception:
            query_text = context.text
        _activity(activity, "tool", "Project index", f"Query: {query_text}", status="info")

        referenced_file = _selected_file_from_context(context) if _is_conversational_file_reference(query_text) else ""
        resolved_referenced_file = _resolved_context_file_path(context, referenced_file)
        effective_active_path = resolved_referenced_file or context.current_file_path
        execution_context = dict((context.extras or {}).get("prompt_execution_context") or {})
        semantic_contract = dict(
            execution_context.get("semantic_execution_contract")
            or (context.extras or {}).get("semantic_execution_contract")
            or {}
        )
        direct_answer = answer_simple_project_index_question(
            query_text,
            active_path=effective_active_path,
            semantic_contract=semantic_contract,
        ) or answer_project_dependency_question(
            query_text, active_path=effective_active_path
        )
        if direct_answer:
            selected_file = _extract_selected_file(direct_answer, resolved_referenced_file or referenced_file)
            workspace_update = _project_search_workspace_update(
                direct_answer,
                primary_file=selected_file or resolved_referenced_file or referenced_file,
            )
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
                    "deep_search_candidate": should_deepen_project_search(query_text, direct_answer),
                    "deep_search_query": query_text,
                    "original_query": context.text,
                    "deep_search_scope": _route_scope(context),
                    "selected_file": selected_file,
                    "resolved_target_file": resolved_referenced_file or referenced_file,
                    "reference_scope_locked": bool(referenced_file),
                    "evidence_tier": 2 if resolved_referenced_file else 0,
                    "workspace_update": workspace_update,
                    "conversation_entities": {
                        "selected_file": selected_file,
                        "source": "project_search_result",
                        "confidence": 0.98 if selected_file else 0.0,
                    },
                },
            )

        project_context = gather_project_search_context(
            query_text,
            active_path=effective_active_path,
            limit=120,
            scope=_route_scope(context),
        )
        _emit(emit, "project_search", "Project evidence gathered", 1, 1)
        _activity(activity, "result", "Project evidence gathered", "Returning indexed evidence directly without LLM routing", status="ok")
        answer = build_deterministic_project_search_answer(
            query_text,
            effective_active_path,
            project_context,
        )
        selected_file = _extract_selected_file(answer, resolved_referenced_file or referenced_file)
        workspace_update = _project_search_workspace_update(
            answer,
            primary_file=selected_file or resolved_referenced_file or referenced_file,
        )
        return EngineResult(
            action="answer",
            label="Project Search",
            text=answer,
            metadata={
                "engine_path": self.name,
                "result_type": "project_search_direct",
                "deep_search_candidate": should_deepen_project_search(query_text, answer),
                "deep_search_query": query_text,
                "original_query": context.text,
                "deep_search_scope": _route_scope(context),
                "selected_file": selected_file,
                "resolved_target_file": resolved_referenced_file or referenced_file,
                "reference_scope_locked": bool(referenced_file),
                "evidence_tier": 2 if resolved_referenced_file else 0,
                "workspace_update": workspace_update,
                "conversation_entities": {
                    "selected_file": selected_file,
                    "source": "project_search_result",
                    "confidence": 0.98 if selected_file else 0.0,
                },
            },
        )


def default_providers() -> list[RequestProvider]:
    return [
        ImportCoverageProvider(),
        ConnectionStatusProvider(),
        ProjectHealthProvider(),
        TargetDiscoveryEditProvider(),
        ActionGraphProvider(),
        ProjectSearchProvider(),
    ]
