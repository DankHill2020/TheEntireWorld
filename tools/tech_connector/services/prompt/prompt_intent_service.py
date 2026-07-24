"""Canonical semantic request understanding for prompt execution.

This service interprets grammatical intent once, extracts a structured intent
frame, and builds low-confidence clarification summaries. It does not own routing,
execution contracts, progress, or the canonical goal graph. Deterministic logic
verifies semantic facts and safety signals only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import threading
import urllib.request
from typing import Any


@dataclass
class PromptIntent:
    kind: str = "general"
    host: str = ""
    target: str = ""
    read_only: bool = False
    wants_execution: bool = False
    wants_mutation: bool = False
    confidence: float = 0.5
    reasons: list[str] = field(default_factory=list)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequestTask:
    """Advisory semantic goal hint retained for compatibility.

    PromptTaskSplitterService owns the canonical dependency graph. These rows
    are semantic hints only and must never be treated as the authoritative
    execution plan.

    Backward-compatible executable goal contract.

    Existing consumers may continue using task_id/action/objective. Newer
    consumers can use goal_type, success_condition, required_inputs, and the
    other planning fields to treat each task as an achievable goal.
    """

    task_id: str
    action: str
    objective: str
    target: str = ""
    capability: str = ""
    depends_on: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    read_only: bool = True
    title: str = ""
    goal_type: str = ""
    success_condition: str = ""
    required_inputs: list[str] = field(default_factory=list)
    conditional_on: str = ""
    requires_reasoning: bool = False
    requires_confirmation: bool = False
    estimated_complexity: int = 1
    terminal: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def goal_id(self) -> str:
        return self.task_id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["goal_id"] = self.task_id
        return data


@dataclass
class RequestUnderstanding:
    normalized_goal: str
    primary_intent: str = "general_chat"
    primary_route: str = "chat"
    secondary_intents: list[str] = field(default_factory=list)
    primary_action: str = ""
    requested_artifact: str = ""
    behavior_description: str = ""
    target_file: str = ""
    target_symbol: str = ""
    target_container_type: str = ""
    target_container_query: str = ""
    target_container_path: str = ""
    requested_member_type: str = ""
    member_behavior: str = ""
    reference_scope: str = ""
    host: str = ""
    mutation_requested: bool = False
    live_host_execution_requested: bool = False
    workflow_requested: bool = False
    read_only_requested: bool = False
    primary_goal: str = ""
    goal_type: str = "respond"
    tasks: list[RequestTask] = field(default_factory=list)
    estimated_steps: int = 0
    requires_project_search: bool = False
    requires_graph: bool = False
    requires_generation: bool = False
    requires_validation: bool = False
    requires_execution: bool = False
    requires_clarification: bool = False
    requires_examples: bool = False
    requires_reuse_search: bool = False
    constraints: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    ambiguity_reasons: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "deterministic"
    model_name: str = ""
    reasons: list[str] = field(default_factory=list)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        serialized_tasks = [task.to_dict() for task in self.tasks]
        data["tasks"] = serialized_tasks
        data["goals"] = serialized_tasks
        data["primary_goal"] = self.primary_goal or self.normalized_goal
        data["estimated_steps"] = self.estimated_steps or len(serialized_tasks)
        return data


_CACHE: dict[tuple[str, ...], RequestUnderstanding] = {}
_CACHE_LOCK = threading.Lock()


def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text or ""))


def _target_from_host_state_query(lower: str) -> str:
    try:
        from tech_connector.services.request_frame_service import analyze_request_frame

        frame = analyze_request_frame(lower)
        if frame.selection_role == "scope" and frame.object_kind == "properties":
            return "selection.properties"
    except Exception:
        pass
    if _has(lower, r"\b(project snapshot|snapshot)\b") or (
        _has(lower, r"\bproject\b") and _has(lower, r"\b(report|inspect|scan|snapshot)\b")
    ):
        return "project"
    if _has(lower, r"\b(selection|selected|selected actors|selected assets|what is selected|what's selected)\b"):
        return "selection"
    if _has(lower, r"\b(joint|joints|bone|bones|skeleton)\b"):
        return "scene.list_joints"
    if _has(lower, r"\b(current file|scene path|scene name|current scene|active scene)\b"):
        return "scene"
    if _has(lower, r"\b(current level|active level|loaded level|world)\b"):
        return "level"
    if _has(lower, r"\b(project|snapshot)\b"):
        return "project"
    return "state"


def _detect_prompt_host(lower: str) -> str:
    aliases = {
        "maya": r"\bmaya\b",
        "unreal": r"\b(?:unreal|ue[45](?:\.\d+)?)\b",
        "blender": r"\bblender\b",
        "houdini": r"\bhoudini\b",
        "unity": r"\bunity\b",
    }
    for name, pattern in aliases.items():
        if re.search(pattern, lower or ""):
            return name
    return ""


def _host_state_query_kind(lower: str, host: str) -> str:
    """Return the concrete read-only host-state shape, if one is requested."""
    if not host:
        return ""
    try:
        from tech_connector.services.request_frame_service import analyze_request_frame

        frame = analyze_request_frame(lower, host=host)
        if frame.wants_execution or frame.wants_mutation:
            return ""
        if frame.selection_role == "scope" and frame.object_kind == "properties":
            return "selection.properties"
        if frame.selection_role == "subject":
            return "selection"
    except Exception:
        pass
    affirmative_text = re.sub(
        r"\b(?:do\s+not|don't|dont|never|without)\s+"
        r"(?:run|execute|apply|create|add|modify|change|set|delete|remove)\b",
        "",
        lower,
    )
    if re.search(r"\b(run|execute|apply|create|add|modify|change|set|delete|remove)\b", affirmative_text):
        return ""
    if re.search(r"\b(function|method|class|source\s+code|docstrings?|filenames?)\b", lower):
        return ""
    if not re.search(
        r"\b(what|which|list|show|report|get|inspect|scan|open|focus|take|current|selected)\b",
        lower,
    ):
        return ""

    if host == "unreal":
        if re.search(r"\b(current\s+project|project\s+snapshot|snapshot)\b", lower):
            return "project"
        if re.search(r"\bwhat(?:'s|\s+is)\s+selected\b", lower):
            return "selection"
        if re.search(r"\bselected\s+(?:actors?|assets?)\b", lower) and re.search(
            r"\b(report|list|show|get|inspect|scan)\b", lower
        ):
            return "selection"
        if re.search(r"\b(open|focus)\b", lower) and re.search(
            r"\b(bp_[a-z0-9_]+|blueprint|asset|event\s*graph|node)\b",
            lower,
        ):
            return "graph" if re.search(r"\b(event\s*graph|graph|node)\b", lower) else "navigation"
        if re.search(r"\b(blueprint|bp_[a-z0-9_]+|graphs?|variables?|components?|compile\s+status)\b", lower):
            return "graph"
        if re.search(r"\b(current|active|loaded)\s+(?:level|world)\b", lower):
            return "level"
        if re.search(r"\b(actors?|assets?)\b", lower):
            return "assets"
        return ""

    if re.search(r"\bwhat(?:'s|\s+is)\s+(?:currently\s+)?selected\b|\bcurrent\s+selection\s*\??\s*$", lower):
        return "selection"
    if re.search(r"\b(joints?|bones?|skeleton)\b", lower):
        return "joints"
    if re.search(r"\b(current|active)\s+(?:file|scene)|scene\s+(?:path|name)\b", lower):
        return "scene"
    return ""


def _registered_host_operation_for_prompt(host: str, text: str) -> tuple[str, Any | None]:
    if host == "unreal":
        return "", None
    try:
        from tech_connector.services.dcc.dcc_operation_service import (
            dcc_prompt_to_operation,
            registered_dcc_operation,
        )

        operation = dcc_prompt_to_operation(
            host,
            text,
            problem_formulation={"action_mode": "execute", "deliverables": []},
        )
        return operation or "", registered_dcc_operation(host, operation or "")
    except Exception:
        return "", None


def classify_prompt_intent(text: str, host: str = "") -> PromptIntent:
    """Backward-compatible phrase-level intent classification."""
    understanding = understand_prompt_request(text, host=host)
    return prompt_intent_from_understanding(understanding, text, host=host)


def prompt_intent_from_understanding(
    understanding: RequestUnderstanding,
    text: str,
    *,
    host: str = "",
) -> PromptIntent:
    """Build the compatibility intent without re-running semantic analysis."""
    route = understanding.primary_route
    kind_map = {
        "project_search": "project_symbol_search",
        "target_discovery": "project_code_edit",
        "dcc_query": "host_state_query",
        "dcc_execute": "dcc_execution",
        "pipeline_graph": "workflow_pipeline",
        "action_graph": "workflow_pipeline",
    }
    specialized_kinds = {
        "asset_navigation",
        "graph_read_or_navigation",
        "read_only_ui_wrapper_planning",
        "read_only_code_planning",
    }
    kind = (
        understanding.primary_intent
        if understanding.primary_intent in specialized_kinds
        else kind_map.get(route, "general")
    )
    target = understanding.target_symbol or understanding.target_file
    if route == "dcc_query" and not target:
        target = _target_from_host_state_query((text or "").lower())
    return PromptIntent(
        kind=kind,
        host=host or understanding.host,
        target=target,
        read_only=understanding.read_only_requested,
        wants_execution=understanding.live_host_execution_requested,
        wants_mutation=understanding.mutation_requested,
        confidence=understanding.confidence,
        reasons=list(understanding.reasons),
    )


def understand_prompt_request(
    text: str,
    host: str = "",
    context: dict[str, Any] | None = None,
) -> RequestUnderstanding:
    """Return one canonical semantic understanding of the request.

    Deterministic extraction supplies facts and fallback behavior, while the
    semantic model normally interprets the complete request before routing.
    The result then passes through deterministic normalization and safety checks.
    """
    try:
        from tech_connector.services.prompt_task_splitter_service import normalize_prompt_text, split_prompt_clauses
        normalized_source = normalize_prompt_text(text)
        clause_plan = split_prompt_clauses(normalized_source)
        raw = re.sub(r"\s+", " ", normalized_source).strip()
    except Exception:
        clause_plan = None
        raw = re.sub(r"\s+", " ", text or "").strip()
    context = dict(context or {})
    context_key = json.dumps(
        {
            "active_path": context.get("active_path") or "",
            "primary_file": context.get("primary_file") or "",
            "selected_files": list(context.get("selected_files") or []),
        },
        sort_keys=True,
        default=str,
    )
    cache_key = (raw, host or "", context_key)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        return _copy_request_understanding(cached)

    # Deterministic extraction supplies factual observations and a resilient
    # fallback. It is not treated as the final semantic interpretation.
    deterministic_facts = _deterministic_understanding(raw, host=host)

    # Use the semantic model when grammar, sequencing, or route confidence
    # needs interpretation. Explicit high-confidence requests proceed directly
    # to the context-aware planning model instead of paying for a duplicate
    # interpretation pass.
    model_result = None
    if _needs_semantic_model(raw, deterministic_facts):
        model_result = _model_understanding(
            raw,
            host=host,
            baseline=deterministic_facts,
            context=context,
        )
    if model_result is not None:
        result = _merge_and_verify(
            deterministic_facts,
            model_result,
            raw,
        )
    else:
        result = deterministic_facts

    # Semantic execution contracts are owned by PromptExecutionContext.
    # Intent understanding must not create a second interpretation/planning
    # object.  Keep this field empty here for compatibility; the canonical
    # context builder attaches the one authoritative contract downstream.
    result.semantic_execution_contract = {}

    if clause_plan is not None:
        result = _apply_clause_plan_to_understanding(
            result,
            clause_plan.to_dict(),
            host=host,
        )

    with _CACHE_LOCK:
        _CACHE[cache_key] = result
    return _copy_request_understanding(result)


def understand_prompt_request_deterministic(
    text: str,
    host: str = "",
) -> RequestUnderstanding:
    """Return the bounded, model-free understanding used by cheap routing.

    The canonical request engine builds richer semantic context before routing.
    This compatibility API exists for callers that only need a route decision;
    it must never wait for a model or inspect project state.
    """
    try:
        from tech_connector.services.prompt_task_splitter_service import normalize_prompt_text, split_prompt_clauses

        normalized_source = normalize_prompt_text(text)
        clause_plan = split_prompt_clauses(normalized_source)
        raw = re.sub(r"\s+", " ", normalized_source).strip()
    except Exception:
        clause_plan = None
        raw = re.sub(r"\s+", " ", text or "").strip()

    result = _deterministic_understanding(raw, host=host)
    result.semantic_execution_contract = {}
    if clause_plan is not None:
        result = _apply_clause_plan_to_understanding(
            result,
            clause_plan.to_dict(),
            host=host,
        )
    return result


def _copy_request_understanding(value: RequestUnderstanding) -> RequestUnderstanding:
    """Return a request-scoped copy so downstream planning cannot mutate cache state."""
    data = value.to_dict()
    task_rows = list(data.pop("tasks", []) or data.pop("goals", []) or [])
    data.pop("goals", None)
    restored_tasks = []
    for row in task_rows:
        item = dict(row or {})
        item.pop("goal_id", None)
        restored_tasks.append(RequestTask(**item))
    return RequestUnderstanding(**{**data, "tasks": restored_tasks})



def _tasks_from_semantic_contract(
    contract: dict[str, Any] | None,
) -> list[RequestTask]:
    """Convert the semantic pre-action plan into canonical request goals."""
    data = dict(contract or {})
    rows = list(data.get("plan_steps") or [])
    tasks: list[RequestTask] = []
    for index, row in enumerate(rows):
        item = dict(row or {})
        step_id = str(
            item.get("step_id")
            or item.get("goal_id")
            or f"semantic_step_{index + 1}"
        )
        action = str(item.get("action") or "analyze")
        tasks.append(
            RequestTask(
                task_id=step_id,
                action=action,
                objective=str(item.get("objective") or ""),
                target=str(data.get("subject_text") or data.get("behavior") or ""),
                capability={
                    "analyze": "semantic_reasoning",
                    "search": "project_index",
                    "resolve": "target_resolution",
                    "rank": "evidence_ranking",
                    "plan": "implementation_planning",
                    "modify_code": "project_edit",
                    "execute": "dcc_execution",
                    "validate": "validation",
                    "report": "reporting",
                }.get(action, action),
                depends_on=[
                    str(value)
                    for value in (item.get("depends_on") or [])
                ],
                produces=[
                    str(value)
                    for value in (item.get("produces") or [])
                ],
                read_only=bool(item.get("read_only", True)),
                title=str(item.get("title") or item.get("objective") or step_id),
                goal_type=str(data.get("goal_type") or ""),
                success_condition=str(item.get("success_condition") or ""),
                required_inputs=[],
                requires_reasoning=bool(item.get("requires_reasoning")),
                requires_confirmation=bool(item.get("requires_confirmation")),
                estimated_complexity=2 if item.get("requires_reasoning") else 1,
                terminal=index == len(rows) - 1,
                metadata={
                    "semantic_contract_step": True,
                    "deliverable_type": data.get("deliverable_type", ""),
                    "relationship": data.get("relationship", ""),
                    "evidence_required": list(data.get("evidence_required") or []),
                },
            )
        )
    return tasks

def _deterministic_understanding(text: str, host: str = "") -> RequestUnderstanding:
    lower = text.lower()
    host = host or _detect_prompt_host(lower)
    try:
        from tech_connector.services.target_entity_service import (
            parse_scoped_member_query,
        )
        scoped_query = parse_scoped_member_query(text)
    except Exception:
        scoped_query = None
    files = re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui)\b", text, re.I)
    explicit_scope_match = re.search(
        r"(?P<path>(?:[A-Za-z]:[\\/]|[.]{1,2}[\\/]|/)[^\n\r:*?\"<>|]+?)"
        r"(?=\s*(?:$|[?.!,;]|\b(?:and|but|that|which|where|under|inside|within|"
        r"are|aren['’]?t|is|isn['’]?t|was|were|not|never)\b))",
        text,
        re.I,
    )
    explicit_scope_path = (explicit_scope_match.group("path").strip().rstrip(".?!,; ") if explicit_scope_match else "")
    unimported_files_query = bool(
        re.search(
            r"\b(?:what|which|list|show|find|check)?\s*(?:files?|modules?)\s+"
            r"(?:(?:are|is)\s+)?(?:not|never)\s+(?:being\s+)?imported\b|"
            r"\b(?:what|which|list|show|find|check)?\s*(?:files?|modules?)\s+"
            r"(?:aren['’]?t|isn['’]?t)\s+imported\b|"
            r"\bunimported\s+(?:files?|modules?)\b",
            lower,
        )
    )
    explicit_qualified_symbol = _explicit_qualified_symbol_reference(text)
    explicit_module_reference = _explicit_module_reference(text)
    symbol_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)", text)
    target_symbol = explicit_qualified_symbol or (symbol_match.group(1) if symbol_match else "")
    if not target_symbol:
        execution_symbol_match = re.search(
            r"\b(?:run|execute|call|launch|perform)\s+"
            r"(?:the\s+)?([A-Za-z_][A-Za-z0-9_.]*)\b",
            text,
            re.IGNORECASE,
        )
        if execution_symbol_match and execution_symbol_match.group(1).lower() not in {"a", "an", "the", "this", "that"}:
            target_symbol = execution_symbol_match.group(1)
    explicit_read_only = bool(
        re.search(r"\b(do not|don't|dont|never|without)\s+(edit|change|modify|write|save|apply|create|add|insert|execute|run|mutate)\b", lower)
        or re.search(r"\b(not an edit|no edit|no edits|not editing|don't mutate|dont mutate|do not mutate|no wait just explain|example only|explain the fix)\b", lower)
    )
    location_query = _is_project_symbol_location_query(lower)
    symbol_operations = _symbol_code_operations(lower)
    explicit_symbol_code_question = bool(explicit_qualified_symbol and symbol_operations)
    mutation_requested = bool(
        re.search(r"\b(add|insert|edit|modify|change|create|build|make|put|delete|remove|save|write|wire|connect|implement|patch|fix|refactor|rename|improve|document)\b", lower)
        or re.search(r"\btest\s+that\b", lower)
    ) and not explicit_read_only and not location_query
    execution_requested = bool(host and re.search(r"\b(run|execute|call|launch|perform|apply)\b", lower))
    workflow_requested = bool(re.search(r"\b(workflow|pipeline|action graph|node graph|multi[- ]step|sequence|compose)\b", lower))

    # Grammatical high-value pattern: the first verb creates an artifact while a
    # later search verb describes that artifact's behavior.
    helper_creation = re.search(
        r"\b(?:make|create|add|write|implement|build)\s+(?:a\s+|an\s+)?(?:new\s+)?(helper(?:\s+function)?|function|method|class|tool|ui|window)\b(?:\s+(?:that|to|which)\s+(.+))?",
        lower,
    )
    search_primary = bool(re.search(
        r"^(?:please\s+)?(?:find|locate|search|inspect|review|analy[sz]e|determine|show|list|where|which|what)\b",
        lower,
    ))
    explanation_or_example = bool(re.search(
        r"\b(how would i|how would you|how do i|how can i|how should i|"
        r"show me how|example of|write an example|what would .* look like|"
        r"if i wanted .* how|what would .* class look like|show .* example|example only|no wait just explain)\b",
        lower,
    ))
    code_learning_request = bool(
        (
            explanation_or_example
            or re.search(
                r"\bhelp\s+me\s+(?:write|create|build|design|implement)\b",
                lower,
            )
        )
        and re.search(r"\b(function|method|helper|class|widget|ui|code|script|implementation)\b", lower)
    )
    ui_wrapper_planning = bool(
        re.search(r"\b(find|locate|identify|choose|select)\b", lower)
        and re.search(r"\b(existing|project)\b", lower)
        and re.search(r"\b(function|functions|method|operation)\b", lower)
        and re.search(r"\b(propose|plan|design|outline)\b", lower)
        and re.search(r"\b(ui|wrapper|window|interface|panel|tool)\b", lower)
        and explicit_read_only
    )
    comparison_request = bool(
        re.search(r"^\s*(?:please\s+)?compare\b|\b(?:differences?|contrast)\s+(?:between|among)\b", lower)
    )
    host_state_query = _host_state_query_kind(lower, host)
    registered_host_operation = (
        _registered_host_operation_for_prompt(host, text)
        if host and not target_symbol
        else ("", None)
    )
    discover_then_change = bool(
        re.search(r"\b(find|locate|identify|inspect|review|analy[sz]e)\b", lower)
        and re.search(
            r"\b(fix|patch|improve|refactor|update|modify|change|document|"
            r"add(?:\s+missing)?\s+(?:docstrings?|params?)|"
            r"make\b.{0,80}\b(?:actionable|clearer?|useful|helpful|better))\b",
            lower,
        )
        and not explicit_read_only
    )
    issue_target_discovery = bool(
        re.search(
            r"\b(bugs?|errors?|issues?|problems?|failures?|wrong|slow|freezes?|"
            r"disappears?|missing|while\s+still|not\s+warning)\b",
            lower,
        )
        and re.search(r"\b(find|identify|inspect|review|analy[sz]e|determine|plan|propose|owning)\b", lower)
        and not mutation_requested
    )
    read_only_code_planning = bool(
        re.search(r"\b(plan|propose|outline|design|architect|implementation\s+plan)\b", lower)
        and re.search(r"\b(code|application|files?|function|method|class|module|service|ui|handler|system)\b", lower)
        and not mutation_requested
    )
    scoped_context_reference = bool(explicit_module_reference or files or re.search(r"\bcustom\s+widgets(?:\s+py)?\b|\bcustom_widgets(?:\.py)?\b|\bcustom_qt\b", lower))
    scoped_example_request = bool(
        scoped_context_reference
        and re.search(r"\b(slider|qslider|widget|class|helper)\b", lower)
        and re.search(r"\b(what would|how would|could .* use|show|example|look like|should i add|already have|is there already|do we already|pretend)\b", lower)
        and (explicit_read_only or not re.search(r"\b(?:add|create|implement|write|patch|put|make)\b", lower))
    )

    if unimported_files_query:
        primary_route = "project_health"
        primary_intent = "code_health"
        primary_action = "analyze"
        requested_artifact = "unimported_files"
        behavior = "identify source files in the explicit scope that are not reachable through the import graph"
        mutation_requested = False
        confidence = 0.97
        reasons = [
            "The request explicitly asks for files that are not imported.",
            "This requires deterministic import/dependency graph analysis, not behavior search.",
        ]
    elif scoped_example_request and scoped_query is None:
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "search"
        requested_artifact = "scoped_class_search"
        behavior = _read_only_behavior_phrase(lower) or lower
        mutation_requested = False
        confidence = 0.9
        reasons = [
            "The request asks for scoped project guidance or existence evidence, not a file mutation.",
        ]
    elif host_state_query:
        primary_route = "dcc_query"
        primary_intent = (
            "graph_read_or_navigation"
            if host == "unreal" and host_state_query == "graph"
            else "asset_navigation"
            if host == "unreal" and host_state_query == "navigation"
            else "dcc_query"
        )
        primary_action = "inspect"
        requested_artifact = "host_state"
        behavior = host_state_query
        mutation_requested = False
        confidence = 0.96
        reasons = [f"The request asks to inspect current {host or 'DCC'} host state without mutation."]
    elif registered_host_operation[0]:
        operation_key, operation_spec = registered_host_operation
        primary_route = (
            "dcc_query"
            if operation_key in {"scene.ls", "scene.list_joints", "project.snapshot", "blueprint.scan"}
            else "dcc_execute"
        )
        primary_intent = "dcc_query" if primary_route == "dcc_query" else "dcc_execution"
        primary_action = "inspect" if primary_route == "dcc_query" else "execute"
        requested_artifact = "host_state" if primary_route == "dcc_query" else "dcc_operation"
        behavior = operation_key
        mutation_requested = bool(getattr(operation_spec, "mutates_project", False))
        execution_requested = primary_route == "dcc_execute"
        confidence = 0.94
        reasons = [f"The request maps to registered {host} operation {operation_key!r}."]
    elif comparison_request:
        primary_route = "chat"
        primary_intent = "comparison"
        primary_action = "compare"
        requested_artifact = "comparison"
        behavior = "compare the selected files"
        mutation_requested = False
        confidence = 0.94
        reasons = ["The request asks for a read-only comparison of contextual targets."]
    elif ui_wrapper_planning:
        primary_route = "target_discovery"
        primary_intent = "read_only_ui_wrapper_planning"
        primary_action = "plan"
        requested_artifact = "ui_wrapper_plan"
        behavior = "wrap a discovered project operation in a Maya UI"
        mutation_requested = False
        confidence = 0.94
        reasons = [
            "The request asks to discover a real project operation and propose a UI wrapper without editing files.",
        ]
    elif read_only_code_planning or issue_target_discovery:
        primary_route = "target_discovery"
        primary_intent = "read_only_code_planning"
        primary_action = "plan"
        requested_artifact = "implementation_plan"
        behavior = _read_only_behavior_phrase(lower) or lower
        mutation_requested = False
        confidence = 0.92
        reasons = [
            "The request asks for evidence-backed code analysis or a plan without applying project edits.",
        ]
    elif discover_then_change:
        primary_route = "target_discovery"
        primary_intent = "project_code_edit"
        primary_action = "modify"
        requested_artifact = "code_change"
        behavior = _read_only_behavior_phrase(lower) or lower
        mutation_requested = True
        confidence = 0.93
        reasons = [
            "The request first discovers an implementation target and then asks to change it.",
        ]
    elif scoped_query is not None:
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "search"
        requested_artifact = f"scoped_{scoped_query.member_type}_search"
        behavior = scoped_query.behavior_description
        mutation_requested = False
        confidence = scoped_query.confidence
        reasons = [
            "The request scopes a member search to a described project container.",
            "The container must be resolved before members are ranked by behavior.",
        ]
    elif explicit_symbol_code_question:
        primary_route = "project_search"
        primary_intent = "code_understanding"
        primary_action = "inspect"
        requested_artifact = "symbol_inspection"
        behavior = ", ".join(symbol_operations)
        mutation_requested = False
        confidence = 0.97
        reasons = [
            "The request gives an explicit qualified project symbol target.",
            "The requested operation is source inspection, not generic symbol location.",
        ]
    elif location_query:
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "locate"
        requested_artifact = "project_symbol_location"
        behavior = _read_only_behavior_phrase(lower)
        confidence = 0.95
        reasons = ["The request asks for the location of an existing project function and does not request mutation."]
    elif code_learning_request:
        primary_route = "chat"
        primary_intent = "code_generation_guidance"
        primary_action = "explain"
        requested_artifact = "code_example"
        behavior = _read_only_behavior_phrase(lower) or lower
        mutation_requested = False
        confidence = 0.9
        reasons = [
            "The request asks how to design or write code, not to modify the project.",
            "Existing project patterns may be searched for reuse, but the terminal goal is explanation or example generation.",
        ]
    elif helper_creation:
        primary_route = "target_discovery"
        primary_intent = "project_code_edit"
        primary_action = "create"
        requested_artifact = helper_creation.group(1).replace(" ", "_")
        behavior = (helper_creation.group(2) or "").strip()
        if files:
            behavior_match = re.search(r"\b(?:that|which)\s+(.+?)(?:\?|$)", lower)
            if behavior_match:
                behavior = behavior_match.group(1).strip()
        confidence = 0.88
        reasons = ["The governing verb creates a code artifact; later search language describes the artifact's behavior."]
    elif execution_requested and not files:
        primary_route = "dcc_execute"
        primary_intent = "dcc_execution"
        primary_action = "execute"
        requested_artifact = "dcc_operation"
        behavior = ""
        confidence = 0.84
        reasons = [f"The request explicitly asks to execute an operation in {host}."]
    elif workflow_requested and mutation_requested:
        primary_route = "pipeline_graph"
        primary_intent = "workflow_pipeline"
        primary_action = "compose"
        requested_artifact = "workflow"
        behavior = ""
        confidence = 0.82
        reasons = ["The request explicitly asks to create or compose a workflow/pipeline."]
    elif mutation_requested and (
        files
        or re.search(
            r"\b(code|function|method|class|module|helper|ui|handler|service|test|"
            r"button|menu|view|filter|agent|indexing|thread|context)\b",
            lower,
        )
    ):
        primary_route = "target_discovery"
        primary_intent = "project_code_edit"
        primary_action = "modify"
        requested_artifact = "code"
        behavior = ""
        confidence = 0.8
        reasons = ["The request asks to change project code or create a code artifact."]
    elif _is_explicit_file_existence_query(lower, bool(files)):
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "inspect"
        requested_artifact = "existing_implementation"
        behavior = _read_only_behavior_phrase(lower)
        confidence = 0.94
        reasons = ["The request asks whether an implementation exists in an explicitly named source file."]
    elif search_primary or re.search(
        r"\b(list|show|where is|which function|find the|locate the|inspect the|review the|analy[sz]e the)\b",
        lower,
    ):
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "search"
        requested_artifact = "project_fact"
        behavior = ""
        mutation_requested = False
        confidence = 0.78
        reasons = ["The governing action requests read-only project information."]
    else:
        primary_route = "chat"
        primary_intent = "general_chat"
        primary_action = "discuss"
        requested_artifact = ""
        behavior = ""
        confidence = 0.5
        reasons = ["No high-confidence structured execution intent was detected."]

    goal_type = _goal_type_for_request(
        primary_action=primary_action,
        primary_intent=primary_intent,
        route=primary_route,
    )
    if scoped_query is not None:
        tasks = _build_scoped_member_tasks(scoped_query)
    else:
        tasks = _build_default_tasks(
            route=primary_route,
            target_file=files[0] if files else "",
            requested_artifact=requested_artifact,
            behavior=behavior,
            host=host,
            goal_type=goal_type,
        )
    return RequestUnderstanding(
        normalized_goal=_normalize_goal(text, primary_action, requested_artifact, files[0] if files else "", behavior),
        primary_intent=primary_intent,
        primary_route=primary_route,
        primary_action=primary_action,
        requested_artifact=requested_artifact,
        behavior_description=behavior,
        target_file=files[0] if files else explicit_module_reference,
        target_symbol=target_symbol,
        target_container_type=(
            scoped_query.container_type if scoped_query is not None else ("file" if explicit_module_reference else "directory" if explicit_scope_path else "")
        ),
        target_container_query=(
            scoped_query.container_query if scoped_query is not None else explicit_module_reference or explicit_scope_path
        ),
        target_container_path=(
            files[0] if files and scoped_query is not None else explicit_scope_path
        ),
        requested_member_type=(
            scoped_query.member_type
            if scoped_query is not None
            else "symbol"
            if explicit_symbol_code_question
            else _project_symbol_kind(lower)
            if location_query
            else ""
        ),
        member_behavior=(
            scoped_query.behavior_description if scoped_query is not None else ""
        ),
        reference_scope=(
            scoped_query.reference_kind if scoped_query is not None else ""
        ),
        host=host,
        mutation_requested=mutation_requested,
        live_host_execution_requested=execution_requested,
        workflow_requested=workflow_requested,
        read_only_requested=(
            explicit_read_only
            or primary_route in {"project_search", "dcc_query", "chat"}
            or primary_intent in {"read_only_ui_wrapper_planning", "read_only_code_planning"}
            or code_learning_request
        ),
        primary_goal=_normalize_goal(text, primary_action, requested_artifact, files[0] if files else "", behavior),
        goal_type=goal_type,
        tasks=tasks,
        estimated_steps=len(tasks),
        requires_project_search=any(task.capability == "project_index" for task in tasks),
        requires_graph=any(task.capability in {"action_graph", "workflow_graph"} for task in tasks),
        requires_generation=any(task.goal_type in {"generate", "design", "implement"} for task in tasks),
        requires_validation=any(task.action == "validate" for task in tasks),
        requires_execution=any(task.action == "execute" for task in tasks),
        requires_clarification=False,
        requires_examples=goal_type in {"learn", "explain", "generate"} or "explain_usage" in symbol_operations,
        requires_reuse_search=any(task.task_id == "inspect_existing" for task in tasks),
        constraints=_extract_constraints(text),
        expected_outputs=_expected_outputs(primary_route, requested_artifact),
        stop_conditions=_extract_stop_conditions(text),
        confidence=confidence,
        reasons=reasons,
    )




def _apply_clause_plan_to_understanding(
    understanding: RequestUnderstanding,
    clause_plan: dict[str, Any],
    *,
    host: str = "",
) -> RequestUnderstanding:
    """Use deterministic clause structure when a request has multiple actions."""
    if (
        understanding.read_only_requested
        and not understanding.mutation_requested
        and understanding.primary_intent in {
            "code_generation_guidance",
            "project_search",
            "code_understanding",
            "read_only_code_planning",
        }
    ):
        return understanding

    clauses = [
        dict(item)
        for item in (clause_plan.get("clauses") or [])
        if isinstance(item, dict)
    ]
    meaningful = [
        clause
        for clause in clauses
        if str(clause.get("action") or "") not in {"constraint", "respond"}
    ]
    if len(meaningful) <= 1:
        return understanding

    tasks: list[RequestTask] = []
    clause_to_task: dict[str, str] = {}
    latest_output = ""

    for index, clause in enumerate(meaningful, start=1):
        clause_id = str(clause.get("clause_id") or f"clause_{index}")
        action = str(clause.get("action") or "inspect")
        task_id = _safe_goal_id(
            clause.get("object_text")
            or clause.get("normalized_text")
            or f"goal_{index}",
            fallback=f"goal_{index}",
        )
        if task_id in clause_to_task.values():
            task_id = f"{task_id}_{index}"
        clause_to_task[clause_id] = task_id

        task_action, goal_type, capability, read_only = _task_semantics_for_clause(
            action,
            clause,
            host=host,
        )
        produces = [_output_name_for_goal(task_id, task_action)]
        required_inputs = [latest_output] if latest_output else []
        latest_output = produces[0]

        tasks.append(
            RequestTask(
                task_id=task_id,
                action=task_action,
                objective=str(
                    clause.get("normalized_text")
                    or clause.get("text")
                    or "Complete the requested goal."
                ),
                target=str(clause.get("object_text") or ""),
                capability=capability,
                depends_on=[],
                produces=produces,
                read_only=read_only,
                title=_goal_title_for_clause(action, clause),
                goal_type=goal_type,
                success_condition=_success_condition_for_clause(
                    action,
                    clause,
                ),
                required_inputs=required_inputs,
                conditional_on=str(
                    clause.get("conditional_on")
                    or clause.get("condition_kind")
                    or ""
                ),
                requires_reasoning=task_action in {
                    "design",
                    "generate",
                    "modify_code",
                    "report",
                },
                requires_confirmation=bool(
                    clause.get("requires_confirmation")
                )
                or task_action in {"modify_code", "execute"},
                estimated_complexity=(
                    3
                    if task_action in {"modify_code", "generate"}
                    else 2
                    if task_action in {"design", "validate", "execute"}
                    else 1
                ),
                terminal=False,
                metadata={
                    "source_clause_id": clause_id,
                    "condition_kind": clause.get("condition_kind") or "",
                    "branch_group": clause.get("branch_group") or "",
                    "constraints": list(clause.get("constraints") or []),
                    "clause_confidence": float(clause.get("confidence") or 0.0),
                },
            )
        )

    # Convert clause dependencies after all task ids are known.
    by_clause = {
        str(clause.get("clause_id") or ""): clause
        for clause in clauses
    }

    def resolved_task_dependencies(clause_id: str, seen: set[str] | None = None) -> list[str]:
        seen = set(seen or ())
        if not clause_id or clause_id in seen:
            return []
        seen.add(clause_id)
        clause_row = by_clause.get(clause_id, {})
        resolved: list[str] = []
        for dependency in clause_row.get("depends_on") or []:
            dependency_id = str(dependency)
            if dependency_id in clause_to_task:
                resolved.append(clause_to_task[dependency_id])
            else:
                resolved.extend(resolved_task_dependencies(dependency_id, seen))
        return list(dict.fromkeys(resolved))
    for task in tasks:
        source_clause_id = str(task.metadata.get("source_clause_id") or "")
        clause = by_clause.get(source_clause_id, {})
        task.depends_on = resolved_task_dependencies(source_clause_id)
        task.required_inputs = [
            _output_name_for_goal(dependency, "")
            for dependency in task.depends_on
        ]

    # Approval clauses are gates. Mutation after a gate must depend on it.
    approval_ids = [
        task.task_id
        for task in tasks
        if task.action == "approval"
    ]
    if approval_ids:
        latest_gate = approval_ids[-1]
        gate_index = next(
            i for i, task in enumerate(tasks)
            if task.task_id == latest_gate
        )
        for task in tasks[gate_index + 1:]:
            if not task.read_only and latest_gate not in task.depends_on:
                task.depends_on.append(latest_gate)

    terminal = _terminal_task(tasks)
    if terminal:
        terminal.terminal = True

    understanding.tasks = tasks
    understanding.estimated_steps = len(tasks)
    understanding.requires_project_search = any(
        task.capability == "project_index"
        for task in tasks
    )
    understanding.requires_graph = any(
        task.capability in {"action_graph", "workflow_graph"}
        for task in tasks
    )
    understanding.requires_generation = any(
        task.action in {"design", "generate", "modify_code"}
        for task in tasks
    )
    understanding.requires_validation = any(
        task.action == "validate"
        for task in tasks
    )
    understanding.requires_execution = any(
        task.action == "execute"
        for task in tasks
    )
    understanding.mutation_requested = any(
        not task.read_only
        for task in tasks
    )
    understanding.read_only_requested = (
        not understanding.mutation_requested
        or bool(clause_plan.get("has_approval_gate"))
    )
    understanding.workflow_requested = (
        understanding.workflow_requested
        or len(tasks) >= 4
        and any(task.action in {"modify_code", "execute"} for task in tasks)
    )
    understanding.requires_clarification = False
    understanding.requires_reuse_search = any(
        task.action in {"search", "inspect"}
        for task in tasks
    )
    understanding.constraints = list(dict.fromkeys([
        *understanding.constraints,
        *[
            str(value)
            for clause in meaningful
            for value in (clause.get("constraints") or [])
            if value
        ],
    ]))
    understanding.primary_goal = (
        terminal.objective
        if terminal
        else understanding.primary_goal
    )
    understanding.goal_type = (
        terminal.goal_type
        if terminal
        else understanding.goal_type
    )
    understanding.primary_route = _route_for_clause_tasks(
        tasks,
        fallback=understanding.primary_route,
    )
    understanding.primary_intent = {
        "project_search": "project_search",
        "target_discovery": "project_code_edit",
        "dcc_execute": "dcc_execution",
        "pipeline_graph": "workflow_pipeline",
        "action_graph": "workflow_pipeline",
        "chat": "code_generation_guidance"
        if understanding.goal_type in {"learn", "explain", "generate"}
        else "general_chat",
    }.get(understanding.primary_route, understanding.primary_intent)
    understanding.confidence = max(
        understanding.confidence,
        float(clause_plan.get("confidence") or 0.0),
    )
    understanding.reasons.append(
        f"Deterministic clause decomposition preserved {len(tasks)} ordered goals."
    )
    return understanding


def _safe_goal_id(value: Any, *, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").lower()).strip("_")
    text = re.sub(r"^(the|a|an)_", "", text)
    return (text[:48] or fallback).rstrip("_")


def _task_semantics_for_clause(
    action: str,
    clause: dict[str, Any],
    *,
    host: str,
) -> tuple[str, str, str, bool]:
    object_text = str(clause.get("object_text") or "").lower()
    if action == "search":
        return "search", "locate", "project_index", True
    if action == "explain":
        return "design", "explain", "code_design", True
    if action == "generate":
        read_only = bool(clause.get("read_only", True))
        return (
            "generate" if read_only else "modify_code",
            "generate" if read_only else "modify",
            "code_generation" if read_only else "project_edit",
            read_only,
        )
    if action == "modify_code":
        return "modify_code", "modify", "project_edit", False
    if action == "execute":
        return "execute", "execute", "dcc_execution" if host else "function_execution", False
    if action == "validate":
        capability = "dcc_validation" if host and "scene" in object_text else "validation"
        return "validate", "validate", capability, True
    if action == "report":
        return "report", "explain", "reporting", True
    if action == "plan":
        return "design", "plan", "code_design", True
    if action == "approval":
        return "approval", "plan", "approval_gate", True
    return "inspect", "respond", "context_resolution", True


def _goal_title_for_clause(
    action: str,
    clause: dict[str, Any],
) -> str:
    object_text = str(clause.get("object_text") or "").strip()
    labels = {
        "search": "Locate project evidence",
        "explain": "Explain the approach",
        "generate": "Generate the requested result",
        "modify_code": "Implement the requested change",
        "execute": "Execute the requested operation",
        "validate": "Validate the result",
        "report": "Report the outcome",
        "plan": "Plan the requested improvements",
        "approval": "Wait for approval",
    }
    label = labels.get(action, "Complete the next goal")
    return f"{label}: {object_text[:80]}" if object_text else label


def _success_condition_for_clause(
    action: str,
    clause: dict[str, Any],
) -> str:
    object_text = str(clause.get("object_text") or "the requested result")
    return {
        "search": f"Relevant evidence for {object_text} is found or its absence is confirmed.",
        "explain": f"The approach for {object_text} is clear, grounded, and actionable.",
        "generate": f"A complete {object_text} is produced without unintended mutation.",
        "modify_code": f"The requested change to {object_text} is implemented in the selected target.",
        "execute": f"The requested operation on {object_text} completes or returns a structured failure.",
        "validate": f"{object_text} passes the smallest relevant validation or remaining failures are explicit.",
        "report": "The user receives the outcome, evidence, changes, warnings, and next action.",
        "plan": f"A concrete, dependency-aware plan for {object_text} is complete.",
        "approval": "Explicit user approval is recorded before dependent mutation begins.",
    }.get(action, "The clause has a verifiable result.")


def _output_name_for_goal(task_id: str, action: str) -> str:
    suffix = {
        "search": "evidence",
        "inspect": "evidence",
        "design": "design",
        "generate": "generated_result",
        "modify_code": "code_change",
        "execute": "execution_result",
        "validate": "validation_result",
        "report": "user_report",
        "approval": "approval",
    }.get(action, "result")
    return f"{task_id}_{suffix}"


def _terminal_task(tasks: list[RequestTask]) -> RequestTask | None:
    for preferred in ("report", "validate", "generate", "modify_code", "execute"):
        for task in reversed(tasks):
            if task.action == preferred:
                return task
    return tasks[-1] if tasks else None


def _route_for_clause_tasks(
    tasks: list[RequestTask],
    *,
    fallback: str,
) -> str:
    terminal = _terminal_task(tasks)
    if not terminal:
        return fallback
    if terminal.action == "report":
        has_mutation = any(not task.read_only for task in tasks)
        if has_mutation:
            return "target_discovery"
        return "chat"
    if terminal.goal_type in {"explain", "learn", "generate"} and terminal.read_only:
        return "chat"
    if any(task.action == "modify_code" for task in tasks):
        return "target_discovery"
    if any(task.action == "execute" for task in tasks):
        return "dcc_execute"
    if any(task.capability in {"action_graph", "workflow_graph"} for task in tasks):
        return "pipeline_graph"
    if all(task.action in {"search", "inspect", "report"} for task in tasks):
        return "project_search" if terminal.action != "report" else "chat"
    return fallback

def _is_project_symbol_location_query(lower: str) -> bool:
    """Recognize cheap project symbol-location questions without a model call.

    Examples:
        Where is our function to create rig located?
        What function creates the rig?
        Locate the rig-building function.
    """
    existence_query = bool(re.search(
        r"^\s*(?:do\s+(?:we|i)\s+have|are\s+there|is\s+there|"
        r"what\s+(?:class|function|method|helper|file)|which\s+(?:class|function|method|helper|file))\b",
        lower,
    ))
    if not existence_query and re.search(
        r"^\s*(?:please\s+)?(?:add|create|make|write|implement|modify|edit|change|fix|patch|rename|remove|delete)\b",
        lower,
    ):
        return False
    location_language = bool(re.search(
        r"\b(where is|where are|located|locate|which functions?|what functions?|what files?|which files?|"
        r"which class(?:es)?|what class(?:es)?|do (?:we|i) have|is there|are there)\b",
        lower,
    ))
    code_artifact = bool(re.search(
        r"\b(files?|functions?|methods?|helpers?|classes?|widgets?|implementations?|code|tools?)\b",
        lower,
    ))
    behavior_or_concept = bool(re.search(
        r"\b(create|build|make|generate|browse|select|choose|rig|rigging|directory|folder)\b",
        lower,
    ))
    return location_language and code_artifact and behavior_or_concept


def _explicit_qualified_symbol_reference(text: str) -> str:
    match = re.search(
        r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,})(?![\w.])",
        text or "",
    )
    return match.group(1) if match else ""


def _explicit_module_reference(text: str) -> str:
    symbol = _explicit_qualified_symbol_reference(text)
    match = re.search(
        r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)(?![\w.])",
        text or "",
    )
    value = match.group(1) if match else ""
    if value and value != symbol:
        return value
    return ""


def _symbol_code_operations(lower: str) -> list[str]:
    operations: list[str] = []

    def add(kind: str) -> None:
        if kind not in operations:
            operations.append(kind)

    text = lower or ""
    if re.search(r"\b(what\s+does|what\s+do|how\s+does|explain|summari[sz]e|describe|run\s+through)\b", text):
        add("explain_behavior")
    if re.search(r"\b(how\s+(?:do|can|should|would)\s+i\s+use|how\s+to\s+use|usage|example|invoke|call\s+it|call\s+this|use\s+it)\b", text):
        add("explain_usage")
    if re.search(r"\b(who\s+calls|what\s+calls|find\s+callers?|called\s+by|callers?)\b", text):
        add("find_callers")
    if re.search(r"\b(show|read|inspect|open)\s+(?:the\s+)?(?:implementation|source|body|code)\b", text):
        add("show_implementation")
    return operations


def _project_symbol_kind(text: str) -> str:
    match = re.search(
        r"^\s*(?:do\s+(?:we|i)\s+have\s+(?:any\s+)?|are\s+there\s+(?:any\s+)?|"
        r"is\s+there\s+(?:a\s+)?|what\s+|which\s+)?"
        r"(class(?:es)?|functions?|methods?|helpers?|files?|widgets?)\b",
        str(text or "").lower(),
    )
    if not match:
        return ""
    value = match.group(1)
    return {
        "classes": "class",
        "functions": "function",
        "methods": "method",
        "helpers": "helper",
        "files": "file",
        "widgets": "widget",
    }.get(value, value)


def _is_explicit_file_existence_query(lower: str, has_source_file: bool) -> bool:
    """Recognize focused read-only questions without invoking the semantic model."""
    if not has_source_file:
        return False
    if re.search(r"\b(add|create|make|write|implement|modify|edit|change|fix|patch|rename|remove|delete)\b", lower):
        return False
    asks_existence = bool(re.search(
        r"\b(do we have|does .* have|is there|are there|any|what .* have|which .* have|show me|list)\b",
        lower,
    ))
    names_code_artifact = bool(re.search(r"\b(helper|helpers|function|functions|method|methods|class|classes|implementation|implementations)\b", lower))
    return asks_existence and names_code_artifact


def _read_only_behavior_phrase(lower: str) -> str:
    """Extract the behavior being sought, preserving words such as find/filter."""
    patterns = (
        r"\b(?:what|which)\s+files?\s+(?:has|have|contains?|implements?)\s+(.+?)(?:\?|$)",
        r"\b(?:for|that|which|to)\s+(.+?)(?:\?|$)",
        r"\b(?:helper|helpers|function|functions|method|methods)\s+(.+?)(?:\?|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""

def _needs_semantic_model(text: str, baseline: RequestUnderstanding) -> bool:
    lower = text.lower()
    # High-confidence deterministic interpretations must remain instant. The
    # model is for grammatical ambiguity, not ordinary explicit-file lookups.
    high_confidence_guidance = (
        baseline.primary_route == "chat"
        and baseline.primary_intent in {"code_generation_guidance", "comparison"}
        and bool(baseline.target_file)
        and bool(re.search(r"\b(how would i|how would you|how do i|how can i|how should i)\b", lower))
    )
    if baseline.confidence >= 0.90 and (
        baseline.primary_route in {
            "project_search", "target_discovery", "dcc_query", "dcc_execute", "pipeline_graph", "action_graph"
        }
        or high_confidence_guidance
    ):
        return False
    if len(text) > 1400:
        return True
    mixed_verbs = bool(re.search(r"\b(make|create|add|implement|build|modify|fix)\b", lower) and re.search(r"\b(find|search|inspect|identify|locate|check)\b", lower))
    multiple_actions = len(re.findall(r"\b(find|search|inspect|create|add|implement|modify|run|execute|validate|test|report|connect|import|export)\b", lower)) >= 3
    ambiguous_find = bool(re.search(r"\b(?:helper|function|method|tool)\s+(?:to|that|which)\s+find", lower))
    teaching_or_design = bool(re.search(
        r"\b(how would i|how would you|how do i|how can i|show me how|"
        r"what would .* look like|if i wanted .* how)\b",
        lower,
    ))
    sequencing_language = bool(re.search(r"\b(first|then|after that|before|after|finally|once)\b", lower))
    route_uncertain = baseline.confidence < 0.78
    return mixed_verbs or multiple_actions or ambiguous_find or teaching_or_design or sequencing_language or route_uncertain


def _model_understanding(
    text: str,
    host: str,
    baseline: RequestUnderstanding,
    context: dict[str, Any] | None = None,
) -> RequestUnderstanding | None:
    try:
        from tech_connector.services.ollama_service import (
            OLLAMA_BASE_URL,
            semantic_intent_model,
        )

        from tech_connector.services.ollama_resource_service import (
            build_semantic_understanding_options,
            choose_semantic_understanding_budget,
        )
    except Exception:
        OLLAMA_BASE_URL = "http://127.0.0.1:11434"

        def semantic_intent_model():
            return "qwen2.5:1.5b"

        def build_semantic_understanding_options(settings=None):
            return {
                "temperature": 0.0,
                "num_ctx": 2048,
                "num_predict": 384,
                "top_k": 1,
                "top_p": 0.1,
                "repeat_penalty": 1.0,
            }

        def choose_semantic_understanding_budget(settings=None):
            return type("Budget", (), {"timeout_seconds": 30})()

    system = """You are the first semantic understanding and planning stage for a local coding and DCC execution system.
Return ONLY one JSON object.
Interpret the ORIGINAL user request in context before routing or taking any action.
Determine the requested deliverable, subject, relationships, scope, constraints, assumptions, and success condition.
Then produce dependency-ordered achievable goals that gather or resolve required evidence before mutation, execution, or reporting.
The deterministic baseline contains observations and a fallback interpretation; it is not authoritative. Replace generic or incorrect baseline meanings.
Separate locate, learn, explain, generate, modify, execute, validate, compare, and plan.
A request asking how to write something is guidance/code generation, not a project edit.
For every request, including short single-sentence requests, create the smallest useful plan.
A file-location request about behavior should plan: interpret behavior -> find implementing symbols -> resolve containing files -> rank evidence -> report.
A scoped member request should plan: resolve container -> find members -> compare behavior -> report.
A mutation request should plan: resolve target -> inspect context/reuse -> design -> edit -> validate -> report.
An execution request should plan: resolve callable/inputs -> preflight -> execute -> verify -> report.
Break multi-step requests into bounded achievable goals with explicit dependencies and measurable success conditions.
Valid primary_route values: project_search, target_discovery, dcc_query, dcc_execute, pipeline_graph, action_graph, chat.
Do not invent files, symbols, or hosts.
JSON schema:
{
  "normalized_goal": "...",
  "primary_goal": "...",
  "goal_type": "locate|learn|explain|generate|modify|execute|validate|compare|plan|debug|respond",
  "primary_intent": "project_code_edit|project_search|code_generation_guidance|dcc_execution|dcc_query|workflow_pipeline|general_chat",
  "primary_route": "...",
  "secondary_intents": [],
  "primary_action": "...",
  "requested_artifact": "...",
  "behavior_description": "...",
  "target_file": "...",
  "target_symbol": "...",
  "host": "...",
  "mutation_requested": true,
  "live_host_execution_requested": false,
  "workflow_requested": false,
  "read_only_requested": false,
  "goals": [{
    "task_id":"goal_1",
    "title":"...",
    "action":"inspect|search|design|generate|modify_code|execute|validate|report",
    "goal_type":"locate|learn|explain|generate|modify|execute|validate|plan",
    "objective":"...",
    "target":"...",
    "capability":"...",
    "depends_on":[],
    "required_inputs":[],
    "produces":[],
    "success_condition":"...",
    "conditional_on":"",
    "requires_reasoning":true,
    "requires_confirmation":false,
    "estimated_complexity":1,
    "terminal":false,
    "read_only":true
  }],
  "constraints": [],
  "expected_outputs": [],
  "stop_conditions": [],
  "ambiguity_reasons": [],
  "confidence": 0.0,
  "reasons": []
}"""
    try:
        from tech_connector.services.prompt_task_splitter_service import clause_plan_for_model, split_prompt_clauses
        clause_packet = clause_plan_for_model(split_prompt_clauses(text))
    except Exception:
        clause_packet = "DETERMINISTIC CLAUSE PLAN unavailable"
    context = dict(context or {})
    conversation_context = {
        "active_path": context.get("active_path") or "",
        "primary_file": context.get("primary_file") or "",
        "selected_files": list(context.get("selected_files") or []),
        "prior_result_summary": context.get("prior_result_summary") or "",
    }
    prompt = (
        f"Known host hint: {host or '(none)'}\n"
        f"Conversation context: {json.dumps(conversation_context, default=str)}\n"
        f"Deterministic baseline: {json.dumps(baseline.to_dict(), default=str)}\n"
        f"{clause_packet}\n"
        f"User request: {text}\n"
        "Preserve every clause, dependency, condition, constraint, and approval gate. "
        "Interpret each clause, then select the terminal goal and return the JSON object."
    )
    model_name = semantic_intent_model()
    settings = dict(context.get("settings") or {})
    semantic_options = build_semantic_understanding_options(settings=settings)
    semantic_budget = choose_semantic_understanding_budget(settings=settings)
    try:
        from tech_connector.services.llm_router_service import generate_llm_response
        raw_text = generate_llm_response(
            model=model_name,
            prompt=prompt,
            system=system,
            response_format="json",
            options=semantic_options,
            timeout=max(5, int(semantic_budget.timeout_seconds))
        ).strip()
        parsed = _parse_json_object(raw_text)
        if not parsed:
            return None
        goal_rows = parsed.get("goals") or parsed.get("tasks") or []
        tasks = [RequestTask(**_clean_task(item, index)) for index, item in enumerate(goal_rows) if isinstance(item, dict)]
        return RequestUnderstanding(
            normalized_goal=str(parsed.get("normalized_goal") or baseline.normalized_goal),
            primary_intent=str(parsed.get("primary_intent") or baseline.primary_intent),
            primary_route=str(parsed.get("primary_route") or baseline.primary_route),
            secondary_intents=[str(x) for x in parsed.get("secondary_intents") or []],
            primary_action=str(parsed.get("primary_action") or baseline.primary_action),
            requested_artifact=str(parsed.get("requested_artifact") or baseline.requested_artifact),
            behavior_description=str(parsed.get("behavior_description") or baseline.behavior_description),
            target_file=str(parsed.get("target_file") or baseline.target_file),
            target_symbol=str(parsed.get("target_symbol") or baseline.target_symbol),
            target_container_type=str(
                parsed.get("target_container_type")
                or baseline.target_container_type
            ),
            target_container_query=str(
                parsed.get("target_container_query")
                or baseline.target_container_query
            ),
            target_container_path=str(
                parsed.get("target_container_path")
                or baseline.target_container_path
            ),
            requested_member_type=str(
                parsed.get("requested_member_type")
                or baseline.requested_member_type
            ),
            member_behavior=str(
                parsed.get("member_behavior")
                or baseline.member_behavior
            ),
            reference_scope=str(
                parsed.get("reference_scope")
                or baseline.reference_scope
            ),
            host=str(parsed.get("host") or host or baseline.host),
            mutation_requested=bool(parsed.get("mutation_requested", baseline.mutation_requested)),
            live_host_execution_requested=bool(parsed.get("live_host_execution_requested", baseline.live_host_execution_requested)),
            workflow_requested=bool(parsed.get("workflow_requested", baseline.workflow_requested)),
            read_only_requested=bool(parsed.get("read_only_requested", baseline.read_only_requested)),
            primary_goal=str(parsed.get("primary_goal") or parsed.get("normalized_goal") or baseline.primary_goal or baseline.normalized_goal),
            goal_type=str(parsed.get("goal_type") or baseline.goal_type),
            tasks=tasks or baseline.tasks,
            estimated_steps=len(tasks or baseline.tasks),
            requires_project_search=any(task.capability == "project_index" for task in (tasks or baseline.tasks)),
            requires_graph=any(task.capability in {"action_graph", "workflow_graph"} for task in (tasks or baseline.tasks)),
            requires_generation=any(task.goal_type in {"generate", "design", "implement"} for task in (tasks or baseline.tasks)),
            requires_validation=any(task.action == "validate" for task in (tasks or baseline.tasks)),
            requires_execution=any(task.action == "execute" for task in (tasks or baseline.tasks)),
            requires_clarification=bool(parsed.get("requires_clarification", False)),
            requires_examples=bool(parsed.get("requires_examples", baseline.requires_examples)),
            requires_reuse_search=bool(parsed.get("requires_reuse_search", baseline.requires_reuse_search)),
            constraints=[str(x) for x in parsed.get("constraints") or baseline.constraints],
            expected_outputs=[str(x) for x in parsed.get("expected_outputs") or baseline.expected_outputs],
            stop_conditions=[str(x) for x in parsed.get("stop_conditions") or baseline.stop_conditions],
            ambiguity_reasons=[str(x) for x in parsed.get("ambiguity_reasons") or []],
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", baseline.confidence)))),
            source="model",
            model_name=model_name,
            reasons=[str(x) for x in parsed.get("reasons") or []],
            semantic_execution_contract=dict(
                parsed.get("semantic_execution_contract")
                or baseline.semantic_execution_contract
                or {}
            ),
        )
    except Exception:
        return None


def _merge_and_verify(baseline: RequestUnderstanding, model: RequestUnderstanding, text: str) -> RequestUnderstanding:
    valid_routes = {"project_search", "target_discovery", "dcc_query", "dcc_execute", "pipeline_graph", "action_graph", "chat"}
    if model.primary_route not in valid_routes:
        model.primary_route = baseline.primary_route
    # Explicit source files are factual and must not be discarded by the model.
    if baseline.target_file and not model.target_file:
        model.target_file = baseline.target_file
    # A code mutation may not become read-only search solely because its behavior includes "find".
    if baseline.mutation_requested and model.primary_route in {"project_search", "chat"}:
        model.primary_route = "target_discovery"
        model.primary_intent = "project_code_edit"
        model.mutation_requested = True
        model.read_only_requested = False
        model.reasons.append("Deterministic verification preserved explicit source-code mutation over a read-only interpretation.")
    # Live execution requires a host hint or an explicit unresolved-environment plan.
    if model.primary_route == "dcc_execute" and not (model.host or baseline.host):
        model.primary_route = baseline.primary_route
        model.reasons.append("Rejected live DCC execution because no host was resolved.")
    if model.primary_route in {"pipeline_graph", "action_graph"} and not model.workflow_requested:
        # Require explicit workflow semantics rather than incidental words.
        if not re.search(r"\b(workflow|pipeline|action graph|node graph|compose|sequence|multi[- ]step)\b", text.lower()):
            model.primary_route = baseline.primary_route
            model.reasons.append("Rejected workflow routing because the user did not request reusable orchestration.")
    protected_intents = {
        "dcc_query",
        "graph_read_or_navigation",
        "asset_navigation",
        "read_only_ui_wrapper_planning",
        "read_only_code_planning",
    }
    if baseline.confidence >= 0.9 and baseline.primary_intent in protected_intents:
        model.primary_route = baseline.primary_route
        model.primary_intent = baseline.primary_intent
        model.primary_action = baseline.primary_action
        model.requested_artifact = baseline.requested_artifact
        model.behavior_description = baseline.behavior_description
        model.host = baseline.host
        model.mutation_requested = baseline.mutation_requested
        model.live_host_execution_requested = baseline.live_host_execution_requested
        model.read_only_requested = baseline.read_only_requested
        model.goal_type = baseline.goal_type
        model.tasks = baseline.tasks
        model.reasons.append("Deterministic verification preserved an unambiguous specialized intent.")
    if baseline.confidence >= 0.9 and str(baseline.requested_artifact or "").startswith("scoped_"):
        model.primary_route = baseline.primary_route
        model.primary_intent = baseline.primary_intent
        model.primary_action = baseline.primary_action
        model.requested_artifact = baseline.requested_artifact
        model.behavior_description = baseline.behavior_description
        model.target_file = baseline.target_file
        model.target_container_type = baseline.target_container_type
        model.target_container_query = baseline.target_container_query
        model.requested_member_type = baseline.requested_member_type
        model.member_behavior = baseline.member_behavior
        model.reference_scope = baseline.reference_scope
        model.mutation_requested = baseline.mutation_requested
        model.read_only_requested = baseline.read_only_requested
        model.tasks = baseline.tasks
        model.reasons.append("Deterministic verification preserved scoped member target and behavior fields.")
    model.confidence = max(model.confidence, baseline.confidence if model.primary_route == baseline.primary_route else 0.0)
    if not model.tasks:
        model.tasks = baseline.tasks
    model.primary_goal = model.primary_goal or model.normalized_goal
    model.estimated_steps = len(model.tasks)
    model.requires_project_search = any(task.capability == "project_index" for task in model.tasks)
    model.requires_graph = any(task.capability in {"action_graph", "workflow_graph"} for task in model.tasks)
    model.requires_generation = any(task.goal_type in {"generate", "design", "implement"} for task in model.tasks)
    model.requires_validation = any(task.action == "validate" for task in model.tasks)
    model.requires_execution = any(task.action == "execute" for task in model.tasks)
    model.requires_reuse_search = any(task.task_id == "inspect_existing" for task in model.tasks)
    if not model.semantic_execution_contract:
        model.semantic_execution_contract = dict(
            baseline.semantic_execution_contract or {}
        )
    if baseline.confidence >= 0.9 and baseline.normalized_goal:
        # Keep deterministic facts and polished wording when the prompt already
        # has an unambiguous grammar. The model still contributes semantic
        # interpretation, tasks, and uncertainty.
        model.normalized_goal = baseline.normalized_goal
        model.primary_goal = baseline.normalized_goal
    model.source = "model_verified"
    return model


def _goal_type_for_request(primary_action: str, primary_intent: str, route: str) -> str:
    action = (primary_action or "").lower()
    intent = (primary_intent or "").lower()
    if intent == "code_generation_guidance":
        return "learn"
    if intent in {"read_only_ui_wrapper_planning", "read_only_code_planning"}:
        return "plan"
    if intent == "comparison" or action == "compare":
        return "compare"
    if action in {"locate", "search", "inspect"} or route == "project_search":
        return "locate"
    if action in {"create", "generate"}:
        return "generate"
    if action in {"modify", "fix", "refactor"} or route == "target_discovery":
        return "modify"
    if action == "execute" or route == "dcc_execute":
        return "execute"
    if action == "compose" or route in {"pipeline_graph", "action_graph"}:
        return "plan"
    if action == "explain":
        return "explain"
    return "respond"



def _build_scoped_member_tasks(scoped_query: Any) -> list[RequestTask]:
    container_label = (
        scoped_query.container_query
        or f"the requested {scoped_query.container_type}"
    )
    member_label = scoped_query.member_type or "symbol"
    behavior = scoped_query.behavior_description or "the requested behavior"

    return [
        RequestTask(
            "resolve_target_container",
            "search",
            (
                f"Resolve the project {scoped_query.container_type} described as "
                f"{container_label!r}."
            ),
            container_label,
            "project_index",
            [],
            ["resolved_container_path"],
            True,
            title=f"Resolve {scoped_query.container_type}",
            goal_type="locate",
            success_condition=(
                "One project container is resolved with sufficient confidence, "
                "or ambiguity is explicitly reported."
            ),
            estimated_complexity=1,
            metadata={
                "container_type": scoped_query.container_type,
                "container_query": scoped_query.container_query,
                "reference_kind": scoped_query.reference_kind,
            },
        ),
        RequestTask(
            "find_matching_container_members",
            "search",
            (
                f"Find {member_label}s inside the resolved container that "
                f"{behavior}."
            ),
            container_label,
            "project_index",
            ["resolve_target_container"],
            ["matching_container_members"],
            True,
            title=f"Find matching {member_label}s",
            goal_type="locate",
            success_condition=(
                f"Relevant {member_label}s in the resolved container are ranked "
                "by behavioral evidence, or their absence is confirmed."
            ),
            required_inputs=["resolved_container_path"],
            estimated_complexity=2,
            metadata={
                "member_type": scoped_query.member_type,
                "behavior_verb": scoped_query.behavior_verb,
                "behavior_object": scoped_query.behavior_object,
                "behavior_description": scoped_query.behavior_description,
            },
        ),
        RequestTask(
            "report_scoped_member_matches",
            "report",
            (
                f"Report which {member_label}s in the resolved container "
                f"{behavior}, with evidence and exclusions."
            ),
            container_label,
            "reporting",
            ["find_matching_container_members"],
            ["scoped_member_answer"],
            True,
            title="Report scoped matches",
            goal_type="explain",
            success_condition=(
                "The answer identifies the best matching members, explains why "
                "they match, and distinguishes narrower or unrelated members."
            ),
            required_inputs=["matching_container_members"],
            requires_reasoning=True,
            estimated_complexity=1,
            terminal=True,
            metadata={
                "member_type": scoped_query.member_type,
                "behavior_description": scoped_query.behavior_description,
            },
        ),
    ]

def _build_default_tasks(
    route: str,
    target_file: str,
    requested_artifact: str,
    behavior: str,
    host: str,
    goal_type: str = "",
) -> list[RequestTask]:
    if route == "dcc_query":
        return [
            RequestTask(
                "query_dcc_state", "inspect",
                f"Read the requested {host or 'DCC'} host state.",
                host, "dcc_query", [], ["dcc_state_result"], True,
                title="Read host state", goal_type="locate",
                success_condition="The requested host state is returned without mutation.",
                estimated_complexity=1, terminal=True,
            )
        ]
    if goal_type == "compare":
        return [
            RequestTask(
                "resolve_comparison_targets", "inspect",
                "Resolve the contextual targets and gather equivalent evidence for each.",
                target_file, "project_index", [], ["comparison_evidence"], True,
                title="Resolve comparison targets", goal_type="locate",
                success_condition="Every selected target is resolved with comparable evidence.",
                estimated_complexity=1,
            ),
            RequestTask(
                "compare_targets", "report",
                "Compare the selected targets by behavior, structure, and relevant tradeoffs.",
                target_file, "reporting", ["resolve_comparison_targets"], ["comparison"], True,
                title="Compare the selected targets", goal_type="compare",
                success_condition="The response states meaningful similarities and differences with evidence.",
                required_inputs=["comparison_evidence"], requires_reasoning=True,
                estimated_complexity=2, terminal=True,
            ),
        ]
    if goal_type == "plan" and route == "target_discovery":
        return [
            RequestTask(
                "inspect_existing", "search",
                "Find a concrete project operation and relevant UI patterns.",
                target_file, "project_index", [], ["operation_and_ui_patterns"], True,
                title="Discover implementation targets", goal_type="locate",
                success_condition="A real operation and compatible UI patterns are identified.",
                estimated_complexity=1,
            ),
            RequestTask(
                "design_ui_wrapper", "design",
                f"Design a UI wrapper for {behavior or 'the selected operation'} without modifying files.",
                target_file, "code_design", ["inspect_existing"], ["ui_wrapper_plan"], True,
                title="Design the UI wrapper", goal_type="plan",
                success_condition="The plan names the operation, UI behavior, integration points, and validation.",
                required_inputs=["operation_and_ui_patterns"], requires_reasoning=True,
                estimated_complexity=2,
            ),
            RequestTask(
                "report_ui_wrapper_plan", "report",
                "Report the evidence-backed UI wrapper plan without applying edits.",
                target_file, "reporting", ["design_ui_wrapper"], ["planning_report"], True,
                title="Report the plan", goal_type="plan",
                success_condition="The user receives an actionable read-only implementation plan.",
                required_inputs=["ui_wrapper_plan"], requires_reasoning=True,
                estimated_complexity=1, terminal=True,
            ),
        ]
    if goal_type in {"learn", "explain"}:
        return [
            RequestTask(
                "inspect_existing",
                "search",
                "Search for existing project patterns relevant to the requested example.",
                target_file,
                "project_index",
                [],
                ["reusable_patterns_or_gap"],
                True,
                title="Find reusable examples",
                goal_type="locate",
                success_condition="Relevant existing helpers or a confirmed implementation gap are identified.",
                requires_reasoning=False,
                estimated_complexity=1,
            ),
            RequestTask(
                "design_example",
                "design",
                f"Design a clear implementation approach for {behavior or requested_artifact or 'the requested helper'}.",
                target_file,
                "code_design",
                ["inspect_existing"],
                ["implementation_design"],
                True,
                title="Design the example",
                goal_type="explain",
                success_condition="Inputs, outputs, assumptions, and the algorithm are explicit.",
                required_inputs=["reusable_patterns_or_gap"],
                requires_reasoning=True,
                estimated_complexity=2,
            ),
            RequestTask(
                "generate_example",
                "generate",
                f"Generate an example {requested_artifact or 'implementation'} grounded in the design.",
                target_file,
                "code_generation",
                ["design_example"],
                ["code_example"],
                True,
                title="Generate example code",
                goal_type="generate",
                success_condition="A coherent example is produced without modifying project files.",
                required_inputs=["implementation_design"],
                requires_reasoning=True,
                estimated_complexity=2,
            ),
            RequestTask(
                "explain_validation",
                "report",
                "Explain assumptions, edge cases, and how the example should be validated.",
                target_file,
                "reporting",
                ["generate_example"],
                ["usage_and_validation_guidance"],
                True,
                title="Explain usage and validation",
                goal_type="explain",
                success_condition="The user knows how to adapt and test the example.",
                required_inputs=["code_example"],
                requires_reasoning=True,
                estimated_complexity=1,
                terminal=True,
            ),
        ]
    if route == "target_discovery":
        return [
            RequestTask(
                "inspect_existing", "search",
                "Inspect the target and existing compatible implementations.",
                target_file, "project_index", [], ["existing_implementation_or_gap"], True,
                title="Inspect existing implementation", goal_type="locate",
                success_condition="A concrete edit target or confirmed gap is identified.",
                estimated_complexity=1,
            ),
            RequestTask(
                "apply_code_change", "modify_code",
                f"Create or modify {requested_artifact or 'code'} to satisfy: {behavior or 'the requested behavior'}.",
                target_file, "project_edit", ["inspect_existing"], ["code_change"], False,
                title="Implement the requested change", goal_type="modify",
                success_condition="The requested behavior is implemented in the selected target.",
                required_inputs=["existing_implementation_or_gap"],
                requires_reasoning=True, requires_confirmation=True,
                estimated_complexity=3,
            ),
            RequestTask(
                "validate_code_change", "validate",
                "Validate syntax and relevant behavior.",
                target_file, "validation", ["apply_code_change"], ["validation_result"], True,
                title="Validate the implementation", goal_type="validate",
                success_condition="Syntax passes and relevant behavior is verified or remaining risk is explicit.",
                required_inputs=["code_change"],
                estimated_complexity=2, terminal=True,
            ),
        ]
    if route == "project_search":
        return [
            RequestTask(
                "search_project", "search",
                "Find and report the requested project evidence.",
                target_file, "project_index", [], ["project_evidence"], True,
                title="Locate project evidence", goal_type="locate",
                success_condition="The requested file, symbol, relationship, or confirmed absence is reported.",
                estimated_complexity=1, terminal=True,
            )
        ]
    if route == "dcc_execute":
        return [
            RequestTask(
                "resolve_dcc_operation", "inspect",
                "Resolve the registered DCC operation and arguments.",
                host, "dcc_registry", [], ["dcc_execution_request"], True,
                title="Resolve the DCC operation", goal_type="locate",
                success_condition="A callable, host, arguments, and missing inputs are known.",
                estimated_complexity=1,
            ),
            RequestTask(
                "execute_dcc_operation", "execute",
                "Execute the resolved operation in the host.",
                host, "dcc_execution", ["resolve_dcc_operation"], ["dcc_result"], False,
                title="Execute the DCC operation", goal_type="execute",
                success_condition="The host reports a completed operation or a structured failure.",
                required_inputs=["dcc_execution_request"],
                requires_confirmation=True, estimated_complexity=2,
            ),
            RequestTask(
                "validate_dcc_result", "validate",
                "Read back host state and validate the result.",
                host, "dcc_validation", ["execute_dcc_operation"], ["validation_result"], True,
                title="Validate the host result", goal_type="validate",
                success_condition="The requested host state is confirmed or the discrepancy is reported.",
                required_inputs=["dcc_result"], estimated_complexity=1, terminal=True,
            ),
        ]
    if route in {"pipeline_graph", "action_graph"}:
        return [
            RequestTask(
                "resolve_capabilities", "inspect",
                "Resolve capabilities required by each workflow step.",
                "", "capability_resolution", [], ["capability_bindings"], True,
                title="Resolve workflow capabilities", goal_type="locate",
                success_condition="Each requested step has a callable capability or an explicit gap.",
                estimated_complexity=2,
            ),
            RequestTask(
                "compose_workflow", "compose",
                "Build the ordered dependency graph.",
                "", "action_graph", ["resolve_capabilities"], ["workflow_graph"], True,
                title="Compose the workflow", goal_type="plan",
                success_condition="All steps, dependencies, inputs, and outputs form a valid graph.",
                required_inputs=["capability_bindings"],
                requires_reasoning=True, estimated_complexity=3,
            ),
            RequestTask(
                "validate_workflow", "validate",
                "Validate every action type, dependency, and input contract.",
                "", "action_contract_validation", ["compose_workflow"], ["validation_result"], True,
                title="Validate the workflow", goal_type="validate",
                success_condition="The workflow graph is executable or all blockers are explicit.",
                required_inputs=["workflow_graph"], estimated_complexity=2, terminal=True,
            ),
        ]
    return []


def _normalize_goal(text: str, action: str, artifact: str, target_file: str, behavior: str) -> str:
    if action == "compare":
        return "Compare the selected files and report meaningful similarities and differences."
    if action == "locate" and artifact == "project_symbol_location":
        detail = _third_person_behavior(behavior)
        symbol_kind = _project_symbol_kind(text)
        if symbol_kind and symbol_kind != "file":
            purpose = f" that {detail}" if detail else ""
            return f"Find the project {symbol_kind}{purpose}."
        purpose = f" that {detail}" if detail else ""
        return f"Find the project file containing an implementation{purpose}."
    if action and artifact:
        target = f" in {target_file}" if target_file else ""
        purpose = f" that {behavior}" if behavior else ""
        return f"{action.capitalize()} {artifact.replace('_', ' ')}{target}{purpose}."
    return text


def _third_person_behavior(behavior: str) -> str:
    value = re.sub(r"\s+", " ", str(behavior or "")).strip(" .?")
    if not value:
        return ""
    match = re.match(r"^(create|build|make|generate|find|detect|resolve|handle|use|call|validate|return)\b(.*)$", value)
    if not match:
        return value
    verb = match.group(1)
    remainder = match.group(2).strip()
    inflected = {
        "create": "creates",
        "build": "builds",
        "make": "makes",
        "generate": "generates",
        "find": "finds",
        "detect": "detects",
        "resolve": "resolves",
        "handle": "handles",
        "use": "uses",
        "call": "calls",
        "validate": "validates",
        "return": "returns",
    }[verb]
    if remainder in {"rig", "function", "method", "class", "file", "module"}:
        remainder = f"a {remainder}"
    return " ".join(part for part in (inflected, remainder) if part)


def _extract_constraints(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip()
        for line in re.split(r"[\n;]+", text or "")
        if re.search(r"\b(only|do not|don't|dont|never|must|before|after|reuse|preserve|without)\b", line, re.I)
    ][:12]


def _extract_stop_conditions(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", match.group(0)).strip()
        for match in re.finditer(r"\b(?:stop|finish|end)\b[^.;\n]*", text or "", re.I)
    ][:6]


def _expected_outputs(route: str, artifact: str) -> list[str]:
    return {
        "target_discovery": [artifact or "code_change", "validation_result", "change_report"],
        "project_search": ["project_evidence"],
        "dcc_query": ["dcc_state_result"],
        "dcc_execute": ["dcc_execution_result", "host_validation_result"],
        "pipeline_graph": ["validated_workflow_graph"],
        "action_graph": ["validated_action_graph"],
    }.get(route, ["response"])


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _clean_task(item: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "task_id": str(item.get("task_id") or item.get("goal_id") or f"goal_{index + 1}"),
        "action": str(item.get("action") or "inspect"),
        "objective": str(item.get("objective") or "Complete the goal."),
        "target": str(item.get("target") or ""),
        "capability": str(item.get("capability") or ""),
        "depends_on": [str(x) for x in item.get("depends_on") or []],
        "produces": [str(x) for x in item.get("produces") or []],
        "read_only": bool(item.get("read_only", True)),
        "title": str(item.get("title") or item.get("objective") or f"Goal {index + 1}"),
        "goal_type": str(item.get("goal_type") or item.get("action") or "respond"),
        "success_condition": str(item.get("success_condition") or "The goal is completed with a verifiable result."),
        "required_inputs": [str(x) for x in item.get("required_inputs") or []],
        "conditional_on": str(item.get("conditional_on") or ""),
        "requires_reasoning": bool(item.get("requires_reasoning", False)),
        "requires_confirmation": bool(item.get("requires_confirmation", False)),
        "estimated_complexity": max(1, min(5, int(item.get("estimated_complexity") or 1))),
        "terminal": bool(item.get("terminal", False)),
        "metadata": dict(item.get("metadata") or {}),
    }


@dataclass
class IntentFrame:
    action: str = "unknown"
    object_type: str = ""
    target_text: str = ""
    qualifiers: list[str] = field(default_factory=list)
    negative_constraints: list[str] = field(default_factory=list)
    quantity: int | None = None
    ordering: str = ""
    requested_scope: str = ""
    success_criteria: list[str] = field(default_factory=list)
    ambiguity: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_intent_frame(prompt: str) -> IntentFrame:
    raw = prompt or ""
    lower = re.sub(r"\s+", " ", raw.lower()).strip()
    action = _action(lower)
    object_type = _object_type(lower)
    quantity = _quantity(lower)
    ordering = "first_match" if re.search(r"\b(first|next)\b", lower) else ""
    scope = _scope(lower)
    qualifiers: list[str] = []
    negatives: list[str] = []
    success: list[str] = []
    ambiguity: list[str] = []

    for label, pattern in (
        ("concise", r"\b(concise|brief|short)\b"),
        ("minimal", r"\b(minimal|smallest|narrow)\b"),
        ("existing_only", r"\b(existing|reuse|do not duplicate|don't duplicate)\b"),
        ("report_changes", r"\b(report back|tell me what|summarize what|report what)\b"),
        ("validate", r"\b(validate|verify|compile|test)\b"),
    ):
        if re.search(pattern, lower):
            qualifiers.append(label)

    for match in re.finditer(r"\b(do not|don't|never|without)\s+([^,.!?;]+)", lower):
        negatives.append(match.group(0).strip())

    if "report_changes" in qualifiers:
        success.append("Report the exact target changed and the precise modification.")
    if "validate" in qualifiers:
        success.append("Provide concrete validation evidence.")
    if action in {"add", "modify", "repair", "refactor", "create"}:
        success.append("Complete only the requested mutation and preserve unrelated behavior.")

    target_text = _target_phrase(raw)
    if action in {"modify", "repair", "refactor"} and not target_text and not ordering:
        ambiguity.append("The mutation target is not explicit.")
    if action == "unknown":
        ambiguity.append("The requested action is unclear.")
    confidence = 0.95 if action != "unknown" and (target_text or ordering or action == "inspect") else 0.65
    return IntentFrame(
        action=action,
        object_type=object_type,
        target_text=target_text,
        qualifiers=qualifiers,
        negative_constraints=negatives,
        quantity=quantity,
        ordering=ordering,
        requested_scope=scope,
        success_criteria=success,
        ambiguity=ambiguity,
        confidence=confidence,
    )


def render_intent_frame(frame: IntentFrame | dict[str, Any]) -> str:
    f = frame if isinstance(frame, IntentFrame) else IntentFrame(**dict(frame or {}))
    lines = [
        "Intent frame:",
        f"- Action: {f.action}",
        f"- Object: {f.object_type or '(unspecified)'}",
        f"- Target: {f.target_text or '(resolve deterministically)'}",
        f"- Quantity/order: {f.quantity if f.quantity is not None else '(unspecified)'} / {f.ordering or '(none)'}",
        f"- Requested scope: {f.requested_scope or '(infer conservatively)'}",
    ]
    if f.qualifiers:
        lines.append("- Qualifiers: " + ", ".join(f.qualifiers))
    if f.negative_constraints:
        lines.append("- Negative constraints: " + " | ".join(f.negative_constraints))
    if f.ambiguity:
        lines.append("- Ambiguity: " + " | ".join(f.ambiguity))
    return "\n".join(lines)


def _action(lower: str) -> str:
    patterns = (
        # Mutation verbs take precedence over incidental retrieval words such as
        # "find" inside "add X to the first function you find".
        ("repair", r"\b(fix|repair|debug|correct)\b"),
        ("refactor", r"\b(refactor|restructure|clean up)\b"),
        ("add", r"\b(add|insert|append)\b"),
        ("create", r"\b(create|build|generate|write|implement)\b"),
        ("modify", r"\b(modify|change|update|wire|connect|rename|remove|delete)\b"),
        ("execute", r"\b(run|execute|call|launch)\b"),
        ("inspect", r"\b(find|search|show|list|inspect|explain|identify|what|which|where)\b"),
    )
    for action, pattern in patterns:
        if re.search(pattern, lower):
            return action
    return "unknown"


def _object_type(lower: str) -> str:
    for kind, pattern in (
        ("docstring", r"\bdocstrings?\b"),
        ("function", r"\bfunctions?|methods?\b"),
        ("class", r"\bclasses?\b"),
        ("ui_handler", r"\bui\s+handler\b"),
        ("file", r"\bfiles?\b"),
        ("graph", r"\bgraphs?|nodes?|pins?\b"),
        ("asset", r"\bassets?\b"),
    ):
        if re.search(pattern, lower):
            return kind
    return ""


def _quantity(lower: str) -> int | None:
    match = re.search(r"\b(?:first|only|exactly)\s+(\d+)\b", lower)
    if match:
        return int(match.group(1))
    if re.search(r"\b(first|one|single)\b", lower):
        return 1
    return None


def _scope(lower: str) -> str:
    if re.search(r"\b(entire project|whole project|project-wide|all files|every file)\b", lower):
        return "project"
    if re.search(r"\b(module|package|folder|directory)\b", lower):
        return "module"
    if re.search(r"\b(this file|current file|active file)\b", lower):
        return "file"
    if re.search(r"\b(first|one|single|this function|selected function|this handler)\b", lower):
        return "exact_target"
    return ""


def _target_phrase(raw: str) -> str:
    # Preserve user wording after common action verbs; this is advisory metadata,
    # not a replacement for indexed target resolution.
    match = re.search(r"\b(?:add|create|write|implement|insert|modify|change|update|fix|repair|refactor|rename|find|show|inspect)\b\s+(.+)", raw, flags=re.I)
    return match.group(1).strip()[:300] if match else ""


CONFIDENCE_AUTO_PLAN_MIN = 0.60
CONFIDENCE_CLARIFY_MIN = 0.35


def _extract_files(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b", text or ""):
        value = match.group(1)
        if value not in found:
            found.append(value)
    return found


def _extract_symbolish_names(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\b", text or ""):
        value = match.group(1)
        lower = value.lower()
        if "_" not in value:
            continue
        if lower.endswith((".py", ".json", ".uasset")):
            continue
        if value not in found:
            found.append(value)
    return found


def build_action_graph_clarification(
    prompt: str,
    plan: dict[str, Any],
    *,
    project_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Build a concise approval-style clarification for a structured prompt."""
    roots = list(project_roots or [])
    files = _extract_files(prompt)
    symbols = _extract_symbolish_names(prompt)
    diagnostics = list(plan.get("diagnostics") or [])
    confidence = float(plan.get("confidence") or 0.0)

    guesses: list[str] = []
    if "pipeline" in (prompt or "").lower() or "workflow" in (prompt or "").lower():
        guesses.append("You want Tech Connector to create or update a Pipeline node graph, not run an Unreal/DCC prototype.")
    if files:
        guesses.append("Use these source files as grounding: " + ", ".join(f"`{item}`" for item in files[:4]) + ".")
    if symbols:
        guesses.append("Resolve these function/symbol names from the project index: " + ", ".join(f"`{item}`" for item in symbols[:6]) + ".")
    if "flow" in (prompt or "").lower():
        guesses.append("Connect execution flow in the order described by the prompt.")
    if any(term in (prompt or "").lower() for term in ("arg", "args", "return", "returns", "connected")):
        guesses.append("Connect return/output values into matching downstream arguments when the index confirms compatible ports.")
    if not roots:
        guesses.append("The missing piece is an active indexed project root, so symbol resolution cannot be trusted yet.")

    if not guesses:
        guesses.append("The request looks structured, but the deterministic planner could not identify a complete action graph.")

    lines = [
        "I think I know the shape of this, but I should confirm before continuing.",
        "",
        "**Closest Interpretation**",
    ]
    lines.extend(f"- {item}" for item in guesses)
    lines.extend(
        [
            "",
            "**Confidence Benchmark**",
            f"- Planner confidence: `{confidence:.2f}`",
            f"- Auto-plan threshold: `{CONFIDENCE_AUTO_PLAN_MIN:.2f}`",
            f"- Clarify threshold: `{CONFIDENCE_CLARIFY_MIN:.2f}`",
        ]
    )
    if diagnostics:
        lines.extend(["", "**Why I Paused**"])
        lines.extend(f"- {item}" for item in diagnostics[:5])
    lines.extend(
        [
            "",
            "**Reply With**",
            "- `yes` to use this interpretation",
            "- the corrected function/file names if any guess is wrong",
            "- `index project` if the project root/index is missing",
        ]
    )
    return {
        "needs_clarification": True,
        "confidence": confidence,
        "auto_plan_threshold": CONFIDENCE_AUTO_PLAN_MIN,
        "clarify_threshold": CONFIDENCE_CLARIFY_MIN,
        "guesses": guesses,
        "files": files,
        "symbols": symbols,
        "text": "\n".join(lines),
    }
