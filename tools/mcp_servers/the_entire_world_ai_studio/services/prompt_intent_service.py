"""Semantic request understanding for prompt routing.

The model interprets grammatical intent and task relationships. Deterministic
logic then verifies facts, route contracts, and execution safety. The public
``classify_prompt_intent`` API is preserved for existing callers.
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
    """Backward-compatible executable goal contract.

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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        serialized_tasks = [task.to_dict() for task in self.tasks]
        data["tasks"] = serialized_tasks
        data["goals"] = serialized_tasks
        data["primary_goal"] = self.primary_goal or self.normalized_goal
        data["estimated_steps"] = self.estimated_steps or len(serialized_tasks)
        return data


_CACHE: dict[tuple[str, str], RequestUnderstanding] = {}
_CACHE_LOCK = threading.Lock()


def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text or ""))


def _target_from_host_state_query(lower: str) -> str:
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


def classify_prompt_intent(text: str, host: str = "") -> PromptIntent:
    """Backward-compatible phrase-level intent classification."""
    understanding = understand_prompt_request(text, host=host)
    route = understanding.primary_route
    kind_map = {
        "project_search": "project_symbol_search",
        "target_discovery": "project_code_edit",
        "dcc_query": "host_state_query",
        "dcc_execute": "dcc_execution",
        "pipeline_graph": "workflow_pipeline",
        "action_graph": "workflow_pipeline",
    }
    target = understanding.target_symbol or understanding.target_file
    if route == "dcc_query" and not target:
        target = _target_from_host_state_query((text or "").lower())
    return PromptIntent(
        kind=kind_map.get(route, "general"),
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
) -> RequestUnderstanding:
    """Return one canonical semantic understanding of the request.

    Obvious requests remain deterministic. Mixed or grammatically ambiguous
    requests use a small local model, then pass through deterministic
    normalization and safety checks.
    """
    try:
        from services.prompt_clause_service import normalize_prompt_text, split_prompt_clauses
        normalized_source = normalize_prompt_text(text)
        clause_plan = split_prompt_clauses(normalized_source)
        raw = re.sub(r"\s+", " ", normalized_source).strip()
    except Exception:
        clause_plan = None
        raw = re.sub(r"\s+", " ", text or "").strip()
    cache_key = (
        raw,
        host or "",
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        cached_data = cached.to_dict()
        task_rows = list(cached_data.pop("tasks", []) or cached_data.pop("goals", []) or [])
        cached_data.pop("goals", None)
        restored_tasks = []
        for row in task_rows:
            item = dict(row or {})
            item.pop("goal_id", None)
            restored_tasks.append(RequestTask(**item))
        return RequestUnderstanding(**{**cached_data, "tasks": restored_tasks})

    # Deterministic extraction supplies factual observations and a resilient
    # fallback. It is not treated as the final semantic interpretation.
    deterministic_facts = _deterministic_understanding(raw, host=host)

    # The semantic model is the normal early path. It interprets the original
    # normalized request and proposes dependency-ordered goals before routing,
    # retrieval, mutation, or execution.
    model_result = _model_understanding(
        raw,
        host=host,
        baseline=deterministic_facts,
    )
    if model_result is not None:
        result = _merge_and_verify(
            deterministic_facts,
            model_result,
            raw,
        )
    else:
        result = deterministic_facts

    try:
        from services.semantic_execution_contract_service import (
            build_semantic_execution_contract,
        )
        contract = build_semantic_execution_contract(
            raw,
            host=host,
            baseline_understanding=result,
        )
        result.semantic_execution_contract = contract.to_dict()
        result.normalized_goal = contract.goal or result.normalized_goal
        result.primary_goal = contract.goal or result.primary_goal
        result.goal_type = contract.goal_type or result.goal_type
        result.expected_outputs = list(
            contract.expected_outputs or result.expected_outputs
        )
        result.constraints = list(dict.fromkeys([
            *result.constraints,
            *contract.constraints,
        ]))
        result.confidence = max(
            result.confidence,
            contract.confidence,
        )

        # Contract planning is the deterministic fallback and consistency layer
        # for model-generated goals. Generic one-step goals are replaced with a
        # concrete semantic plan; specific model goals are preserved.
        contract_tasks = _tasks_from_semantic_contract(contract.to_dict())
        existing_specific = (
            len(result.tasks) > 1
            and not all(
                str(task.objective or "").lower() in {
                    "find and report the requested project evidence.",
                    "search project fact.",
                    "complete the requested task.",
                }
                for task in result.tasks
            )
        )
        if contract_tasks and not existing_specific:
            result.tasks = contract_tasks
            result.estimated_steps = len(contract_tasks)
    except Exception:
        contract = None

    if clause_plan is not None:
        result = _apply_clause_plan_to_understanding(
            result,
            clause_plan.to_dict(),
            host=host,
        )

    with _CACHE_LOCK:
        _CACHE[cache_key] = result
    return result



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
    try:
        from services.prompt_reference_resolution_service import (
            parse_scoped_member_query,
        )
        scoped_query = parse_scoped_member_query(text)
    except Exception:
        scoped_query = None
    files = re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui)\b", text, re.I)
    symbol_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)", text)
    target_symbol = symbol_match.group(1) if symbol_match else ""
    explicit_read_only = bool(re.search(r"\b(do not|don't|dont|never|without)\s+(edit|change|modify|write|save|apply|create|add|insert|execute|run)\b", lower))
    location_query = _is_project_symbol_location_query(lower)
    mutation_requested = bool(re.search(r"\b(add|insert|edit|modify|change|create|build|make|delete|remove|save|write|wire|connect|implement|patch|fix|refactor|rename)\b", lower)) and not explicit_read_only and not location_query
    execution_requested = bool(host and re.search(r"\b(run|execute|call|launch|perform|apply)\b", lower))
    workflow_requested = bool(re.search(r"\b(workflow|pipeline|action graph|node graph|multi[- ]step|sequence|compose)\b", lower))

    # Grammatical high-value pattern: the first verb creates an artifact while a
    # later search verb describes that artifact's behavior.
    helper_creation = re.search(
        r"\b(?:make|create|add|write|implement|build)\s+(?:a\s+|an\s+)?(?:new\s+)?(helper(?:\s+function)?|function|method|class|tool|ui|window)\b(?:\s+(?:that|to|which)\s+(.+))?",
        lower,
    )
    search_primary = bool(re.search(r"^(?:please\s+)?(?:find|locate|search|show|list|where|which|what)\b", lower))
    explanation_or_example = bool(re.search(
        r"\b(how would i|how would you|how do i|how can i|how should i|"
        r"show me how|example of|write an example|what would .* look like|"
        r"if i wanted .* how)\b",
        lower,
    ))
    code_learning_request = bool(
        explanation_or_example
        and re.search(r"\b(function|method|helper|class|code|script|implementation)\b", lower)
    )

    if scoped_query is not None:
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
    elif mutation_requested and (files or re.search(r"\b(code|function|method|class|module|helper|ui|handler|service|test)\b", lower)):
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
    elif search_primary or re.search(r"\b(list|show|where is|which function|find the|locate the)\b", lower):
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "search"
        requested_artifact = "project_fact"
        behavior = ""
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
        target_file=files[0] if files else "",
        target_symbol=target_symbol,
        target_container_type=(
            scoped_query.container_type if scoped_query is not None else ""
        ),
        target_container_query=(
            scoped_query.container_query if scoped_query is not None else ""
        ),
        target_container_path=(
            files[0] if files and scoped_query is not None else ""
        ),
        requested_member_type=(
            scoped_query.member_type if scoped_query is not None else ""
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
        read_only_requested=explicit_read_only or primary_route in {"project_search", "chat"} or code_learning_request,
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
        requires_examples=goal_type in {"learn", "explain", "generate"},
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
    if re.search(r"\b(add|create a|make a|write|implement|modify|edit|change|fix|patch|rename|remove|delete)\b", lower):
        return False
    location_language = bool(re.search(
        r"\b(where is|where are|located|locate|which function|what function|do we have|is there)\b",
        lower,
    ))
    code_artifact = bool(re.search(r"\b(function|method|helper|implementation|code|tool)\b", lower))
    behavior_or_concept = bool(re.search(r"\b(create|build|make|generate|rig|rigging)\b", lower))
    return location_language and code_artifact and behavior_or_concept


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
    if baseline.confidence >= 0.90 and baseline.primary_route in {
        "project_search", "target_discovery", "dcc_query", "dcc_execute", "pipeline_graph", "action_graph"
    }:
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


def _model_understanding(text: str, host: str, baseline: RequestUnderstanding) -> RequestUnderstanding | None:
    try:
        from services.ollama_service import (
            OLLAMA_BASE_URL,
            semantic_intent_model,
        )

        from services.ollama_resource_service import (
            build_semantic_understanding_options,
        )
    except Exception:
        OLLAMA_BASE_URL = "http://127.0.0.1:11434"

        def semantic_intent_model():
            return "qwen2.5:1.5b"

        def build_semantic_understanding_options():
            return {
                "temperature": 0.0,
                "num_ctx": 2048,
                "num_predict": 384,
                "top_k": 1,
                "top_p": 0.1,
                "repeat_penalty": 1.0,
            }

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
        from services.prompt_clause_service import clause_plan_for_model, split_prompt_clauses
        clause_packet = clause_plan_for_model(split_prompt_clauses(text))
    except Exception:
        clause_packet = "DETERMINISTIC CLAUSE PLAN unavailable"
    prompt = (
        f"Known host hint: {host or '(none)'}\n"
        f"Deterministic baseline: {json.dumps(baseline.to_dict(), default=str)}\n"
        f"{clause_packet}\n"
        f"User request: {text}\n"
        "Preserve every clause, dependency, condition, constraint, and approval gate. "
        "Interpret each clause, then select the terminal goal and return the JSON object."
    )
    model_name = semantic_intent_model()
    semantic_options = build_semantic_understanding_options()
    payload = json.dumps({
        "model": model_name,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "format": "json",
        "options": semantic_options,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=18) as response:
            raw_response = json.loads(response.read().decode("utf-8", errors="replace"))
        parsed = _parse_json_object(str(raw_response.get("response") or ""))
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
    if baseline.mutation_requested and baseline.target_file and model.primary_route == "project_search":
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
    model.source = "model_verified"
    return model


def _goal_type_for_request(primary_action: str, primary_intent: str, route: str) -> str:
    action = (primary_action or "").lower()
    intent = (primary_intent or "").lower()
    if intent == "code_generation_guidance":
        return "learn"
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
    if action and artifact:
        target = f" in {target_file}" if target_file else ""
        purpose = f" that {behavior}" if behavior else ""
        return f"{action.capitalize()} {artifact.replace('_', ' ')}{target}{purpose}."
    return text


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
