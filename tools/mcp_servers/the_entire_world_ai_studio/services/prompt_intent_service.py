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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequestTask:
    task_id: str
    action: str
    objective: str
    target: str = ""
    capability: str = ""
    depends_on: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    host: str = ""
    mutation_requested: bool = False
    live_host_execution_requested: bool = False
    workflow_requested: bool = False
    read_only_requested: bool = False
    tasks: list[RequestTask] = field(default_factory=list)
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
        data["tasks"] = [task.to_dict() for task in self.tasks]
        return data


_CACHE: dict[tuple[str, str, bool], RequestUnderstanding] = {}
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
    understanding = understand_prompt_request(text, host=host, allow_model=False)
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


def understand_prompt_request(text: str, host: str = "", *, allow_model: bool = True) -> RequestUnderstanding:
    """Return one canonical semantic understanding of the request.

    Obvious requests remain deterministic. Mixed or grammatically ambiguous
    requests use a small local model, then pass through deterministic
    normalization and safety checks.
    """
    raw = re.sub(r"\s+", " ", text or "").strip()
    cache_key = (raw, host or "", bool(allow_model))
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        return RequestUnderstanding(**{**cached.to_dict(), "tasks": [RequestTask(**t) for t in cached.to_dict()["tasks"]]})

    baseline = _deterministic_understanding(raw, host=host)
    result = baseline
    if allow_model and _needs_semantic_model(raw, baseline):
        model_result = _model_understanding(raw, host=host, baseline=baseline)
        if model_result is not None:
            result = _merge_and_verify(baseline, model_result, raw)

    with _CACHE_LOCK:
        _CACHE[cache_key] = result
    return result


def _deterministic_understanding(text: str, host: str = "") -> RequestUnderstanding:
    lower = text.lower()
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

    if location_query:
        primary_route = "project_search"
        primary_intent = "project_search"
        primary_action = "locate"
        requested_artifact = "project_symbol_location"
        behavior = _read_only_behavior_phrase(lower)
        confidence = 0.95
        reasons = ["The request asks for the location of an existing project function and does not request mutation."]
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

    tasks = _build_default_tasks(
        route=primary_route,
        target_file=files[0] if files else "",
        requested_artifact=requested_artifact,
        behavior=behavior,
        host=host,
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
        host=host,
        mutation_requested=mutation_requested,
        live_host_execution_requested=execution_requested,
        workflow_requested=workflow_requested,
        read_only_requested=explicit_read_only or primary_route == "project_search",
        tasks=tasks,
        constraints=_extract_constraints(text),
        expected_outputs=_expected_outputs(primary_route, requested_artifact),
        stop_conditions=_extract_stop_conditions(text),
        confidence=confidence,
        reasons=reasons,
    )



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
    route_uncertain = baseline.confidence < 0.78
    return mixed_verbs or multiple_actions or ambiguous_find or route_uncertain


def _model_understanding(text: str, host: str, baseline: RequestUnderstanding) -> RequestUnderstanding | None:
    try:
        from services.ollama_service import OLLAMA_BASE_URL, FAST_CODE_MODEL
    except Exception:
        OLLAMA_BASE_URL = "http://127.0.0.1:11434"
        FAST_CODE_MODEL = "qwen2.5-coder:7b"

    system = """You interpret requests for a local coding and DCC execution system.
Return ONLY one JSON object. Determine the governing user action, not isolated keywords.
A search verb may describe the behavior of a new helper rather than mean project search.
Break the request into ordered tasks and dependencies.
Valid primary_route values: project_search, target_discovery, dcc_query, dcc_execute, pipeline_graph, action_graph, chat.
Do not invent files, symbols, or hosts.
JSON schema:
{
  "normalized_goal": "...",
  "primary_intent": "project_code_edit|project_search|dcc_execution|dcc_query|workflow_pipeline|general_chat",
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
  "tasks": [{"task_id":"task_1","action":"inspect|search|modify_code|execute|validate|report","objective":"...","target":"...","capability":"...","depends_on":[],"produces":[],"read_only":true}],
  "constraints": [], "expected_outputs": [], "stop_conditions": [],
  "ambiguity_reasons": [], "confidence": 0.0, "reasons": []
}"""
    prompt = (
        f"Known host hint: {host or '(none)'}\n"
        f"Deterministic baseline: {json.dumps(baseline.to_dict(), default=str)}\n"
        f"User request: {text}\n"
        "Interpret the request and return the JSON object."
    )
    payload = json.dumps({
        "model": FAST_CODE_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 700, "num_ctx": 4096},
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
        tasks = [RequestTask(**_clean_task(item, index)) for index, item in enumerate(parsed.get("tasks") or []) if isinstance(item, dict)]
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
            host=str(parsed.get("host") or host or baseline.host),
            mutation_requested=bool(parsed.get("mutation_requested", baseline.mutation_requested)),
            live_host_execution_requested=bool(parsed.get("live_host_execution_requested", baseline.live_host_execution_requested)),
            workflow_requested=bool(parsed.get("workflow_requested", baseline.workflow_requested)),
            read_only_requested=bool(parsed.get("read_only_requested", baseline.read_only_requested)),
            tasks=tasks or baseline.tasks,
            constraints=[str(x) for x in parsed.get("constraints") or baseline.constraints],
            expected_outputs=[str(x) for x in parsed.get("expected_outputs") or baseline.expected_outputs],
            stop_conditions=[str(x) for x in parsed.get("stop_conditions") or baseline.stop_conditions],
            ambiguity_reasons=[str(x) for x in parsed.get("ambiguity_reasons") or []],
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", baseline.confidence)))),
            source="model",
            model_name=str(FAST_CODE_MODEL),
            reasons=[str(x) for x in parsed.get("reasons") or []],
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
    model.source = "model_verified"
    return model


def _build_default_tasks(route: str, target_file: str, requested_artifact: str, behavior: str, host: str) -> list[RequestTask]:
    if route == "target_discovery":
        return [
            RequestTask("inspect_existing", "search", "Inspect the target and existing compatible implementations.", target_file, "project_index", [], ["existing_implementation_or_gap"], True),
            RequestTask("apply_code_change", "modify_code", f"Create or modify {requested_artifact or 'code'} to satisfy: {behavior or 'the requested behavior'}.", target_file, "project_edit", ["inspect_existing"], ["code_change"], False),
            RequestTask("validate_code_change", "validate", "Validate syntax and relevant behavior.", target_file, "validation", ["apply_code_change"], ["validation_result"], True),
        ]
    if route == "project_search":
        return [RequestTask("search_project", "search", "Find and report the requested project evidence.", target_file, "project_index", [], ["project_evidence"], True)]
    if route == "dcc_execute":
        return [
            RequestTask("resolve_dcc_operation", "inspect", "Resolve the registered DCC operation and arguments.", host, "dcc_registry", [], ["dcc_execution_request"], True),
            RequestTask("execute_dcc_operation", "execute", "Execute the resolved operation in the host.", host, "dcc_execution", ["resolve_dcc_operation"], ["dcc_result"], False),
            RequestTask("validate_dcc_result", "validate", "Read back host state and validate the result.", host, "dcc_validation", ["execute_dcc_operation"], ["validation_result"], True),
        ]
    if route in {"pipeline_graph", "action_graph"}:
        return [
            RequestTask("resolve_capabilities", "inspect", "Resolve capabilities required by each workflow step.", "", "capability_resolution", [], ["capability_bindings"], True),
            RequestTask("compose_workflow", "compose", "Build the ordered dependency graph.", "", "action_graph", ["resolve_capabilities"], ["workflow_graph"], True),
            RequestTask("validate_workflow", "validate", "Validate every action type, dependency, and input contract.", "", "action_contract_validation", ["compose_workflow"], ["validation_result"], True),
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
        "task_id": str(item.get("task_id") or f"task_{index + 1}"),
        "action": str(item.get("action") or "inspect"),
        "objective": str(item.get("objective") or "Complete the task."),
        "target": str(item.get("target") or ""),
        "capability": str(item.get("capability") or ""),
        "depends_on": [str(x) for x in item.get("depends_on") or []],
        "produces": [str(x) for x in item.get("produces") or []],
        "read_only": bool(item.get("read_only", True)),
    }
