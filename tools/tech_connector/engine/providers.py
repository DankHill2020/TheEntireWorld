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
        r"^\s*\d+\.\s+`?[^`\n]+`?\s+-\s+`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))(?:\:\d+)?`?\s*$",
        r"^\s*`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))`?\s*$",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return str(fallback or "")


def _extract_selected_symbol(answer: str) -> str:
    """Return the first ranked callable name from a deterministic index answer."""
    import re

    text = str(answer or "")
    for pattern in (
        r"^\s*\d+\.\s+`?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"^\s*-\s+`?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1)
    return ""


def _extract_ranked_symbol_rows(answer: str) -> list[dict[str, str]]:
    """Extract ordered callable/file rows from a ranked index response."""
    import re

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^\s*\d+\.\s+`?([A-Za-z_][A-Za-z0-9_]*)\s*\([^`\n]*\)`?"
        r"\s+-\s+`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))"
        r"(?:\:\d+)?`?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in pattern.finditer(str(answer or "")):
        key = (match.group(1), match.group(2).strip())
        if key not in seen:
            rows.append({"symbol": key[0], "file": key[1]})
            seen.add(key)

    current_file = ""
    file_header = re.compile(
        r"^\s*\d+\.\s+`?([^`\n]+?\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui))`?\s*$",
        re.IGNORECASE,
    )
    nested_callable = re.compile(
        r"^\s*-\s+`?([A-Za-z_][A-Za-z0-9_]*)\s*\([^`\n]*\)`?"
        r"(?:\s+on\s+line\s+`?\d+`?)?\s*$",
        re.IGNORECASE,
    )
    for line in str(answer or "").splitlines():
        file_match = file_header.match(line)
        if file_match:
            current_file = file_match.group(1).strip()
            continue
        callable_match = nested_callable.match(line)
        if not callable_match or not current_file:
            continue
        key = (callable_match.group(1), current_file)
        if key not in seen:
            rows.append({"symbol": key[0], "file": key[1]})
            seen.add(key)
    return rows


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
    from tech_connector.services.reasoning.target_entity_service import extract_target_entities

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


def _expected_file_candidates_from_route(context: RequestContext) -> list[dict]:
    """Promote planned generated-code targets into target discovery evidence."""
    from pathlib import Path

    decision = _route_decision(context)
    plan = decision.get("capability_gap_plan") or {}
    if not isinstance(plan, dict):
        return []

    expected: list[dict] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            files = value.get("expected_files")
            if isinstance(files, list):
                for item in files:
                    if isinstance(item, dict) and item.get("path"):
                        expected.append(dict(item))
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(plan)
    if not expected:
        return []

    roots = [Path(root) for root in context.project_roots or () if str(root or "").strip()]
    candidates: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(expected):
        raw_path = str(item.get("path") or "").strip()
        if not raw_path or " or " in raw_path:
            continue
        path = Path(raw_path)
        if path.suffix.lower() not in {
            ".c", ".cc", ".cpp", ".cs", ".h", ".hpp", ".js", ".json",
            ".py", ".qml", ".ts", ".tsx", ".ui",
        }:
            continue
        resolved = ""
        if path.is_absolute():
            resolved = str(path)
        else:
            resolved = str((roots[0] / path) if roots else path)
        key = resolved.replace("\\", "/").casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append({
            "path": resolved,
            "score": 120 - index * 5,
            "symbols": [],
            "chunks": [],
            "candidate_source": "capability_gap_expected_file",
            "expected_file_rank": index,
            "purpose": str(item.get("purpose") or ""),
        })
    return candidates


def _candidate_identity_keys(context: RequestContext, path_text: str) -> set[str]:
    from pathlib import Path

    raw = str(path_text or "").strip()
    if not raw:
        return set()
    path = Path(raw)
    keys = {raw.replace("\\", "/").casefold()}
    if not path.is_absolute():
        for root in context.project_roots or ():
            if str(root or "").strip():
                keys.add(str(Path(root) / path).replace("\\", "/").casefold())
    else:
        for root in context.project_roots or ():
            root_path = Path(root)
            try:
                rel = path.relative_to(root_path)
                keys.add(str(rel).replace("\\", "/").casefold())
            except Exception:
                pass
    return keys


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
        from tech_connector.services.prompt.prompt_dispatch_service import PromptDispatchService

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
        operations = [
            dict(operation)
            for operation in (route_decision.get("operations") or [])
            if any(
                dict(operation).get(key)
                for key in ("operation", "callable", "args", "produces", "requires")
            )
        ]
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
            from tech_connector.services.prompt.prompt_intent_service import build_action_graph_clarification

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
            from tech_connector.services.prompt.artifact_contract_service import (
                requests_generated_code_artifact,
            )

            understanding = dict(route_decision.get("request_understanding") or {})
            operation_mode = str(route_decision.get("operation_mode") or "").lower()
            if understanding and not requests_generated_code_artifact(route_decision):
                if operation_mode == "plan":
                    return route_decision.get("provider") == self.name
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
    def _synthesize_dynamic_sketch_and_plan(self, prompt: str, target_file: str) -> tuple[list[str], list[str]]:
        import re
        from pathlib import Path

        raw_text = prompt or ""
        lower_text = raw_text.lower()
        target_name = Path(target_file).name if target_file else ""
        target_stem = Path(target_file).stem if target_file else ""

        id_matches = re.findall(r"\b([A-Z][a-zA-Z0-9]+|[a-z][a-z0-9_]{3,})\b", raw_text)
        stopwords = {
            "class", "function", "method", "strategy", "first", "adding", "create",
            "make", "build", "file", "target", "edits", "prompt", "please", "with",
            "from", "into", "that", "this", "have", "need", "want", "should", "could",
            "before", "after", "about", "which", "where", "custom", "widgets", "tools",
            "module", "package", "python", "script", "project", "code", "implementation",
        }
        candidates = [w for w in id_matches if w.lower() not in stopwords]

        qt_match = re.search(r"\b(Q[A-Z][a-zA-Z0-9]+)\b", raw_text)
        qt_class = qt_match.group(1) if qt_match else ""

        entity_name = ""
        if qt_class:
            if qt_class in {"QTableWidget", "QTreeWidget", "QListWidget", "QComboBox", "QSpinBox", "QSlider", "QDialog"}:
                entity_name = f"Custom{qt_class[1:]}"
            else:
                entity_name = qt_class
        elif candidates:
            entity_name = candidates[0]
            if entity_name.islower():
                entity_name = "".join(part.capitalize() for part in entity_name.split("_"))
        else:
            entity_name = "CustomComponent"

        is_func = bool(re.search(r"\b(?:function|def|helper\s+function|utility\s+function)\b", lower_text))
        is_enum = bool(re.search(r"\b(?:enum|enumeration)\b", lower_text))
        is_dataclass = bool(re.search(r"\b(?:dataclass|struct|schema|record)\b", lower_text))

        base_class = ""
        if qt_class:
            base_class = f"QtWidgets.{qt_class}"
        elif "dialog" in lower_text:
            base_class = "QtWidgets.QDialog"
        elif "widget" in lower_text:
            base_class = "QtWidgets.QWidget"
        elif "thread" in lower_text:
            base_class = "QtCore.QThread"
        elif "exception" in lower_text or "error" in lower_text:
            base_class = "Exception"
        elif "dict" in lower_text:
            base_class = "dict"

        if is_enum:
            sketch_lines = [
                f"class {entity_name}(enum.Enum):",
                f'    """Enum defining options for {entity_name.lower()} handling."""',
                "    DEFAULT = 'default'",
                "    ACTIVE = 'active'",
                "    DISABLED = 'disabled'",
            ]
            plan_steps = [
                f"1. Import standard `enum` module in `{target_name}` if not present.",
                f"2. Define `{entity_name}` with type-safe enumeration variants.",
                f"3. Integrate `{entity_name}` with surrounding functions and validation rules.",
                f"4. Add unit test coverage for `{entity_name}` serialization and comparisons.",
            ]
        elif is_dataclass:
            sketch_lines = [
                "@dataclass",
                f"class {entity_name}:",
                f'    """Structured data container for {entity_name.lower()} payload."""',
                "    id: str",
                "    name: str",
                "    enabled: bool = True",
                "    metadata: dict = field(default_factory=dict)",
            ]
            plan_steps = [
                f"1. Ensure `@dataclass` and `field` are imported from `dataclasses` in `{target_name}`.",
                f"2. Define schema fields and default initializers for `{entity_name}`.",
                f"3. Provide serialization / deserialization methods (`to_dict` / `from_dict`) if required.",
                f"4. Add smoke tests for `{entity_name}` construction and field validation.",
            ]
        elif is_func:
            func_name = candidates[0] if candidates else "process_data"
            if not func_name.islower():
                func_name = re.sub(r"(?<!^)(?=[A-Z])", "_", func_name).lower()
            sketch_lines = [
                f"def {func_name}(data: dict, options: dict | None = None) -> dict:",
                f'    """Process and transform {func_name.replace("_", " ")} payload."""',
                "    options = options or {}",
                "    result = dict(data)",
                "    # Perform requested operations and validations",
                "    return result",
            ]
            plan_steps = [
                f"1. Inspect `{target_name}` to confirm function placement and parameter naming standards.",
                f"2. Implement `def {func_name}(...)` with clear type hints and docstring.",
                "3. Implement core processing logic and error handling for edge cases.",
                f"4. Execute local tests calling `{func_name}` to verify behavior.",
            ]
        elif qt_class == "QTableWidget" or ("table" in lower_text and "widget" in lower_text):
            sketch_lines = [
                f"class {entity_name}(QtWidgets.QTableWidget):",
                f'    """Custom table widget providing structured item handling and column headers."""',
                "",
                "    def __init__(self, rows: int = 0, columns: int = 0, parent=None):",
                "        super().__init__(rows, columns, parent)",
                "        self.setAlternatingRowColors(True)",
                "        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)",
                "        self.horizontalHeader().setStretchLastSection(True)",
                "",
                "    def populate(self, headers: list[str], row_data: list[list[str]]) -> None:",
                "        self.setColumnCount(len(headers))",
                "        self.setHorizontalHeaderLabels(headers)",
                "        self.setRowCount(len(row_data))",
                "        for r, row in enumerate(row_data):",
                "            for c, val in enumerate(row):",
                "                self.setItem(r, c, QtWidgets.QTableWidgetItem(str(val)))",
            ]
            plan_steps = [
                f"1. Confirm `QtWidgets.QTableWidget` and `QtWidgets.QTableWidgetItem` imports in `{target_name}`.",
                f"2. Implement `{entity_name}` extending `QtWidgets.QTableWidget` with custom initialization and selection behavior.",
                "3. Add helper methods (`populate`, item selection listeners) for managing table rows and headers.",
                "4. Verify runtime construction, signal connections, and widget rendering.",
            ]
        elif qt_class or "widget" in lower_text or "dialog" in lower_text:
            base = base_class or "QtWidgets.QWidget"
            sketch_lines = [
                f"class {entity_name}({base}):",
                f'    """Custom UI component extending {base} for {entity_name.lower()}."""',
                "",
                "    def __init__(self, parent=None):",
                "        super().__init__(parent)",
                "        self._setup_ui()",
                "",
                "    def _setup_ui(self) -> None:",
                "        layout = QtWidgets.QVBoxLayout(self)",
                "        layout.setContentsMargins(8, 8, 8, 8)",
                "        # Construct layout components and connect signals",
            ]
            plan_steps = [
                f"1. Check PySide imports and layout conventions in `{target_name}`.",
                f"2. Implement `{entity_name}` inheriting from `{base}` with layout initialization.",
                "3. Wire internal child widgets, events, and signal connections.",
                f"4. Add smoke test constructing `{entity_name}` in non-modal / application context.",
            ]
        else:
            base_suffix = f"({base_class})" if base_class else ""
            sketch_lines = [
                f"class {entity_name}{base_suffix}:",
                f'    """Implementation for {entity_name.lower()} in {target_stem or "target module"}."""',
                "",
                "    def __init__(self, config: dict | None = None):",
                "        self.config = config or {}",
                "        self.is_active = True",
                "",
                "    def execute(self, payload: dict) -> dict:",
                "        # Process payload and return result state",
                "        return {'status': 'success', 'data': payload}",
            ]
            plan_steps = [
                f"1. Review existing module structure and patterns in `{target_name}`.",
                f"2. Define `{entity_name}` class with initializers and configurable fields.",
                "3. Implement core operational methods, parameter checking, and error handling.",
                f"4. Add unit test suite verifying `{entity_name}` instantiation and method execution.",
            ]

        return sketch_lines, plan_steps

    def _plan_text(self, context: RequestContext, discovery: dict, selected_candidate: dict, ordered_candidates: list[dict], resolution: dict) -> str:
        selected = str(selected_candidate.get("path") or "")
        reasons = list(resolution.get("reasons") or [])
        symbols = selected_candidate.get("symbols") or []
        symbol_names = []
        for symbol in symbols[:6]:
            if not isinstance(symbol, dict):
                continue
            name = symbol.get("qualname") or symbol.get("name")
            if not name:
                continue
            symbol_names.append(f"{symbol.get('kind', 'symbol')} `{name}`")

        sketch_lines, plan_steps = self._synthesize_dynamic_sketch_and_plan(context.text, selected)

        clean_reasons = []
        for r in reasons:
            r_str = str(r or "").strip()
            if not r_str or "provider score" in r_str.lower():
                continue
            if r_str == "Candidate is open in the editor.":
                clean_reasons.append("Selected file is active in the workspace editor.")
            elif r_str == "Candidate is editable source (.py).":
                clean_reasons.append("Target is editable Python source file.")
            elif "expected generated-code target" in r_str.lower():
                clean_reasons.append("Target matches expected implementation module.")
            else:
                clean_reasons.append(r_str)

        lines = [
            "I mapped your request to the likely owning code target and can provide a concrete implementation plan before any edits.",
            "",
            "Requested scope:",
            f"- Prompt: {str(context.text or '').strip().splitlines()[0][:220] or '(not provided)'}",
            f"- Primary target: `{selected}`",
        ]
        if clean_reasons:
            lines.extend([
                "",
                "Why this file is top candidate:",
                *[f"- {reason}" for reason in clean_reasons[:3]],
            ])
        if symbol_names:
            lines.extend([
                "",
                "Relevant symbols found:",
                *[f"- {name}" for name in symbol_names],
            ])

        lines.extend([
            "",
            "Concrete sketch (adapt to existing patterns in this module):",
            "```python",
            *sketch_lines,
            "```",
            "",
            "Plan (no edits yet):",
            *plan_steps,
            "",
            "Top ranked targets:",
        ])
        for idx, candidate in enumerate(ordered_candidates[:5], 1):
            path = str(candidate.get("path") or "")
            if not path:
                continue
            tag = " (Primary target)" if idx == 1 else ""
            lines.append(f"- #{idx}: `{path}`{tag}")
        if not ordered_candidates:
            lines.append("- No ranked candidates were found beyond file-level matches.")

        lines.extend([
            "",
            "Reply with `approve` and I will proceed to generate the exact patch, or ask for a different target before I draft it.",
        ])
        return "\n".join(lines)

    def handle(self, context: RequestContext, emit: ProgressCallback, activity: ActivityCallback | None = None) -> EngineResult:
        from tech_connector.services.project_service import (
            discover_edit_targets,
            format_edit_target_context,
            build_project_edit_target_prompt,
        )
        from tech_connector.services.reasoning.target_resolution_service import resolve_target_candidates

        route_decision = _route_decision(context)
        understanding = dict(route_decision.get("request_understanding") or {})
        read_only_requested = bool(understanding.get("read_only_requested"))
        mutation_requested = bool(understanding.get("mutation_requested"))
        operation_mode = str(route_decision.get("operation_mode") or "").lower()
        from tech_connector.services.prompt.artifact_contract_service import (
            requests_generated_code_artifact,
        )
        generated_code_artifact = requests_generated_code_artifact(route_decision)

        if (
            understanding
            and not generated_code_artifact
            and (read_only_requested or not mutation_requested)
            and operation_mode != "plan"
        ):
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
        planned_candidates = _expected_file_candidates_from_route(context)
        if generated_code_artifact and not planned_candidates and context.project_roots:
            candidates.insert(0, {
                "path": str(context.project_roots[0]),
                "score": 0,
                "symbols": [],
                "chunks": [],
                "candidate_source": "generated_artifact_scope",
                "purpose": (
                    "Project scope for a new generated artifact; discovered files "
                    "are grounding patterns, not assumed edit owners."
                ),
            })
        if planned_candidates:
            merged_planned: list[dict] = []
            planned_keys: set[str] = set()
            for item in planned_candidates:
                keys = _candidate_identity_keys(context, str(item.get("path") or ""))
                if keys and not (keys & planned_keys):
                    merged_planned.append(item)
                    planned_keys.update(keys)
            remaining_candidates: list[dict] = []
            seen = set(planned_keys)
            for item in candidates:
                keys = _candidate_identity_keys(context, str(item.get("path") or ""))
                if keys and keys & seen:
                    continue
                remaining_candidates.append(item)
                seen.update(keys)
            candidates = [*merged_planned, *remaining_candidates]
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
        resolution_state = resolution.to_dict()

        route_requires_confirmation = route_decision.get("requires_confirmation")
        requires_confirmation = not (
            route_requires_confirmation is False
            or str(route_requires_confirmation).strip().lower() in {"0", "false", "no", "off"}
        )
        plan_binding = dict((context.extras or {}).get("clarification_binding") or {})
        plan_approved = bool(
            (
                context.text
                and (
                    (route_decision.get("approved") and not requires_confirmation)
                    or str(route_decision.get("approval_state") or "").strip().lower() == "approved"
                    or str(route_decision.get("approval") or "").strip().lower() == "approved"
                )
            )
            or str(plan_binding.get("action") or "").strip().lower() == "confirm"
            or bool(plan_binding.get("route_decision", {}).get("approved"))
            or str(plan_binding.get("route_decision", {}).get("approval_state") or "").strip().lower() == "approved"
        )

        if operation_mode == "plan" and not plan_approved:
            _emit(emit, "prompt", "Read-only plan generated", 1, 1)
            _activity(
                activity,
                "plan",
                "Implementation plan prepared",
                f"Providing ranked target evidence for {selected_path or selected_candidate.get('path') or ''} before any edit prompt generation.",
                status="ok",
                path=selected_path,
                score=float(selected_candidate.get("score") or 0),
                metadata={
                    "target_confidence": resolution.confidence,
                    "target_reasons": resolution.reasons,
                    "generated_code_artifact": generated_code_artifact,
                    "live_tree_mutation_allowed": False,
                },
            )
            pending_route = dict(route_decision)
            if selected_path:
                selected_target = str(selected_path)
                pending_route["resolved_target_file"] = selected_target
                pending_route["target_file"] = selected_target
                pending_route["target"] = selected_target
                index_filters = dict(pending_route.get("index_filters") or {})
                index_filters["target_file"] = selected_target
                index_filters["scope"] = "active"
                pending_route["index_filters"] = index_filters
            return EngineResult(
                action="clarify",
                label="Project Edit Plan",
                text=self._plan_text(
                    context,
                    discovery,
                    selected_candidate,
                    ordered_candidates,
                    resolution_state,
                ),
                metadata={
                    "engine_path": self.name,
                "result_type": "target_discovery_plan",
                "discovery": discovery,
                "target_resolution": resolution_state,
                "selected_target": selected_path,
                "generated_code_artifact": generated_code_artifact,
                "live_tree_mutation_allowed": False,
                "pending_clarification": {
                    "kind": "confirmation",
                    "resumable": True,
                    "target": str(selected_path or ""),
                    "execution_environment": str(
                        route_decision.get("execution_environment")
                        or route_decision.get("host")
                        or ""
                    ),
                        "route_decision": pending_route,
                        "execution_request": {
                            "operation_mode": "plan",
                            "original_prompt": context.text,
                            "target_file": str(selected_path or ""),
                            "target_path": str(selected_path or ""),
                            "resolved_target_file": str(selected_path or ""),
                        },
                    "unresolved_slots": [],
                    "allow_text_approval": True,
                },
                "ui_controls": [
                    {"type": "button", "value": "approve", "label": "Approve"},
                    {"type": "button", "value": "cancel", "label": "Deny"},
                ],
            },
            )

        discovery_context = format_edit_target_context(
            discovery,
            max_source_lines=8 if generated_code_artifact else 45,
            max_candidates=4 if generated_code_artifact else 8,
        )
        _emit(emit, "prompt", "Building grounded edit prompt")
        prompt = build_project_edit_target_prompt(
            context.text,
            discovery_context,
            active_path=(
                context.current_file_path
                if generated_code_artifact and not bool(mutation_requested and not read_only_requested)
                else selected_path or context.current_file_path
            ),
            generated_artifact=generated_code_artifact,
            live_tree_mutation_allowed=bool(mutation_requested and not read_only_requested),
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
                "generated_code_artifact": generated_code_artifact,
                "live_tree_mutation_allowed": bool(mutation_requested and not read_only_requested),
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
                "generated_code_artifact": generated_code_artifact,
                "live_tree_mutation_allowed": bool(mutation_requested and not read_only_requested),
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
            answer_explicit_symbol_inspection_question,
            answer_simple_project_index_question,
            build_deterministic_project_search_answer,
            gather_project_search_context,
            should_deepen_project_search,
        )
        _emit(emit, "project_search", "Searching project index")
        try:
            from tech_connector.services.prompt.prompt_task_splitter_service import normalize_prompt_text
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
        explicit_symbol_answer = answer_explicit_symbol_inspection_question(
            query_text,
            project_roots=list(context.project_roots or []),
            active_path=effective_active_path,
        )
        if explicit_symbol_answer:
            _emit(emit, "project_search", "Exact symbol inspected", 1, 1)
            _activity(
                activity,
                "result",
                "Exact symbol inspected",
                "Resolved the explicit @symbol before broad project search",
                status="ok",
            )
            return EngineResult(
                action="answer",
                label="Symbol Inspection",
                text=explicit_symbol_answer,
                metadata={
                    "engine_path": self.name,
                    "result_type": "symbol_inspection_direct",
                    "deep_search_candidate": False,
                    "deep_search_query": query_text,
                    "original_query": context.text,
                    "deep_search_scope": _route_scope(context),
                    "selected_file": "",
                    "resolved_target_file": "",
                    "reference_scope_locked": True,
                    "evidence_tier": 2,
                    "workspace_update": {},
                    "conversation_entities": {},
                },
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
