"""Canonical semantic execution contract for Tech Connector.

This service is the single source of truth for what the user is trying to
accomplish. It consolidates clause structure, intent framing, target entities,
semantic relationships, deliverables, evidence requirements, assumptions, and
success criteria before routing, retrieval, prediction, or progress rendering.

Downstream services should consume this contract instead of independently
reinterpreting the raw prompt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass
class SemanticExecutionContract:
    original_prompt: str
    normalized_request: str

    goal: str
    goal_type: str
    deliverable_type: str

    subject_type: str = ""
    subject_text: str = ""
    relationship: str = ""
    container_type: str = ""
    container_query: str = ""

    action: str = ""
    behavior: str = ""
    host_domain: str = ""
    context_source: str = ""

    read_only: bool = True
    mutation_requested: bool = False
    execution_requested: bool = False

    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)

    expected_outputs: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    success_definition: str = ""
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    planning_rationale: str = ""
    formulation_source: str = ""
    canonical_owner: str = "PromptExecutionContext"

    clause_plan: dict[str, Any] = field(default_factory=dict)
    intent_frame: dict[str, Any] = field(default_factory=dict)
    target_entities: list[dict[str, Any]] = field(default_factory=list)
    scoped_member_query: dict[str, Any] = field(default_factory=dict)

    confidence: float = 0.5
    confidence_signals: list[str] = field(default_factory=list)
    uncertainty_signals: list[str] = field(default_factory=list)
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["framework"] = "semantic_execution_contract_v2"
        return data


_LOCATION_PREFIX_RE = re.compile(
    r"^\s*(?:what|which|where|find|locate|show|list)\b",
    re.IGNORECASE,
)

_FILE_DELIVERABLE_RE = re.compile(
    r"\b(?:what|which|where|find|locate|show)\s+(?:the\s+)?(?:project\s+)?file\b"
    r"|\bwhat\s+file\b|\bwhich\s+file\b|\bwhere\s+is\b.*\bfile\b",
    re.IGNORECASE,
)

_SYMBOL_DELIVERABLE_RE = re.compile(
    r"\b(?:what|which|find|locate|show|list)\s+(?:the\s+)?"
    r"(function|method|class|helper|symbol)s?\b",
    re.IGNORECASE,
)

_BEHAVIOR_VERBS = {
    "create": ("create", "creates", "creating", "build", "builds", "building", "make", "makes", "making", "generate", "generates", "setup"),
    "find": ("find", "finds", "finding", "locate", "resolve", "detect", "identify", "collect", "filter", "list", "get"),
    "validate": ("validate", "verify", "check", "compile", "test"),
    "use": ("use", "uses", "using", "call", "calls", "calling"),
    "modify": ("modify", "edit", "change", "update", "patch", "fix", "refactor", "rename", "remove", "delete", "wire", "connect", "implement"),
    "execute": ("run", "execute", "call", "launch", "perform", "apply"),
}


def build_semantic_execution_contract(
    prompt: str,
    *,
    host: str = "",
    baseline_understanding: dict[str, Any] | Any | None = None,
    problem_formulation: dict[str, Any] | Any | None = None,
) -> SemanticExecutionContract:
    """Build one canonical representation of the user's intended outcome."""

    raw = str(prompt or "")
    normalized = _normalize_prompt(raw)

    baseline = (
        baseline_understanding.to_dict()
        if hasattr(baseline_understanding, "to_dict")
        else dict(baseline_understanding or {})
    )
    formulation = (
        problem_formulation.to_dict()
        if hasattr(problem_formulation, "to_dict")
        else dict(problem_formulation or {})
    )

    clause_plan = _safe_clause_plan(normalized)
    intent_frame = _safe_intent_frame(normalized)
    target_entities = _safe_target_entities(normalized)
    scoped_query = _safe_scoped_query(normalized)

    lower = normalized.lower()
    host_domain = host or str(baseline.get("host") or "") or _detect_host(lower)

    deliverable_type = _deliverable_type(
        lower,
        baseline=baseline,
        scoped_query=scoped_query,
        intent_frame=intent_frame,
    )
    goal_type = _goal_type(
        lower,
        deliverable_type=deliverable_type,
        baseline=baseline,
        intent_frame=intent_frame,
    )
    action = _canonical_action(
        lower,
        baseline=baseline,
        intent_frame=intent_frame,
        goal_type=goal_type,
    )

    subject_type, subject_text = _subject(
        normalized,
        deliverable_type=deliverable_type,
        baseline=baseline,
        scoped_query=scoped_query,
        intent_frame=intent_frame,
    )
    relationship = _relationship(
        lower,
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        scoped_query=scoped_query,
    )
    container_type, container_query = _container(
        normalized,
        deliverable_type=deliverable_type,
        scoped_query=scoped_query,
        baseline=baseline,
    )
    behavior = _behavior(
        normalized,
        action=action,
        subject_text=subject_text,
        baseline=baseline,
        scoped_query=scoped_query,
    )

    explicit_read_only = bool(
        re.search(
            r"\b(do not|don't|dont|never|without)\s+"
            r"(edit|change|modify|write|save|apply|create|add|insert|execute|run)\b",
            lower,
        )
    )
    if "mutation_requested" in baseline:
        mutation_requested = bool(baseline.get("mutation_requested"))
    else:
        mutation_requested = bool(
            intent_frame.get("action") in {"add", "create", "modify", "repair", "refactor"}
            or _contains_action(lower, "modify")
        )
    if baseline.get("read_only_requested"):
        mutation_requested = False
    if goal_type == "locate" or explicit_read_only:
        mutation_requested = False

    execution_requested = bool(
        baseline.get("live_host_execution_requested")
        or _contains_action(lower, "execute")
    )
    if not host_domain and execution_requested:
        execution_requested = False

    read_only = not mutation_requested and not execution_requested

    constraints = _ordered_unique(
        [
            *[str(item) for item in baseline.get("constraints") or []],
            *[str(item) for item in clause_plan.get("clauses") or [] if False],
            *[str(item) for item in intent_frame.get("negative_constraints") or []],
            *_extract_constraints(normalized),
        ]
    )

    assumptions = _assumptions(
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        host_domain=host_domain,
        relationship=relationship,
        read_only=read_only,
    )
    unresolved = _unresolved_fields(
        deliverable_type=deliverable_type,
        subject_text=subject_text,
        container_query=container_query,
        host_domain=host_domain,
        execution_requested=execution_requested,
    )
    expected_outputs = _expected_outputs(
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        goal_type=goal_type,
    )
    evidence_required = _evidence_required(
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        relationship=relationship,
        behavior=behavior,
    )
    success_definition = _success_definition(
        goal_type=goal_type,
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        relationship=relationship,
        behavior=behavior,
    )
    plan_steps = _build_plan_steps(
        goal_type=goal_type,
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        relationship=relationship,
        container_type=container_type,
        container_query=container_query,
        behavior=behavior,
        mutation_requested=mutation_requested,
        execution_requested=execution_requested,
        evidence_required=evidence_required,
    )
    planning_rationale = _planning_rationale(
        goal_type=goal_type,
        deliverable_type=deliverable_type,
        relationship=relationship,
        plan_steps=plan_steps,
    )

    goal = _canonical_goal(
        goal_type=goal_type,
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        subject_text=subject_text,
        relationship=relationship,
        container_type=container_type,
        container_query=container_query,
        behavior=behavior,
        host_domain=host_domain,
    )

    # Problem formulation can refine unresolved semantic fields, but cannot
    # create a second contract.  Only fill gaps; explicit understanding wins.
    if formulation:
        formulated_subject = str(formulation.get("subject") or "").strip()
        formulated_scope = str(formulation.get("scope") or "").strip()
        formulated_goal = str(formulation.get("desired_outcome") or "").strip()
        if not subject_text and formulated_subject:
            subject_text = formulated_subject
            behavior = behavior or formulated_subject
        if not container_query and formulated_scope not in {"", "project"}:
            container_query = formulated_scope
            container_type = container_type or "scope"
        if (not goal or goal == "Respond to the request.") and formulated_goal:
            goal = formulated_goal
        constraints = _ordered_unique([
            *constraints,
            *[str(value) for value in formulation.get("constraints") or []],
        ])
        assumptions = _ordered_unique([
            *assumptions,
            *[str(value) for value in formulation.get("assumptions") or []],
        ])
        evidence_required = _ordered_unique([
            *evidence_required,
            *[str(value) for value in formulation.get("evidence_required") or []],
        ])
        unresolved = [
            value for value in unresolved
            if not (value == "subject_behavior" and subject_text)
            and not (value == "conversation_reference" and container_query and container_query not in {"that", "this"})
        ]

    confidence, confidence_signals, uncertainty_signals = _confidence(
        deliverable_type=deliverable_type,
        goal_type=goal_type,
        subject_text=subject_text,
        relationship=relationship,
        container_query=container_query,
        unresolved_fields=unresolved,
        baseline=baseline,
        scoped_query=scoped_query,
    )

    context_source = _context_source(
        deliverable_type=deliverable_type,
        host_domain=host_domain,
        execution_requested=execution_requested,
        baseline=baseline,
    )

    return SemanticExecutionContract(
        original_prompt=raw,
        normalized_request=normalized,
        goal=goal,
        goal_type=goal_type,
        deliverable_type=deliverable_type,
        subject_type=subject_type,
        subject_text=subject_text,
        relationship=relationship,
        container_type=container_type,
        container_query=container_query,
        action=action,
        behavior=behavior,
        host_domain=host_domain,
        context_source=context_source,
        read_only=read_only,
        mutation_requested=mutation_requested,
        execution_requested=execution_requested,
        constraints=constraints,
        assumptions=assumptions,
        unresolved_fields=unresolved,
        expected_outputs=expected_outputs,
        evidence_required=evidence_required,
        success_definition=success_definition,
        plan_steps=plan_steps,
        planning_rationale=planning_rationale,
        formulation_source=str(formulation.get("framework") or formulation.get("source") or ""),
        canonical_owner="PromptExecutionContext",
        clause_plan=clause_plan,
        intent_frame=intent_frame,
        target_entities=target_entities,
        scoped_member_query=scoped_query,
        confidence=confidence,
        confidence_signals=confidence_signals,
        uncertainty_signals=uncertainty_signals,
    )


def contract_from_decision(decision: dict[str, Any] | Any | None) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    return dict(
        data.get("semantic_execution_contract")
        or data.get("semantic_contract")
        or (data.get("request_understanding") or data.get("understanding") or {}).get("semantic_execution_contract")
        or {}
    )


def render_semantic_execution_contract(
    contract: SemanticExecutionContract | dict[str, Any],
) -> str:
    data = contract.to_dict() if isinstance(contract, SemanticExecutionContract) else dict(contract or {})
    lines = [
        "Understanding:",
        f"- Goal: {data.get('goal') or '(unknown)'}",
        f"- Deliverable: {data.get('deliverable_type') or '(unknown)'}",
        f"- Subject: {data.get('subject_type') or '(unknown)'}"
        + (f" — {data.get('subject_text')}" if data.get("subject_text") else ""),
        f"- Relationship: {data.get('relationship') or '(none)'}",
        f"- Scope: {data.get('context_source') or '(unknown)'}",
        f"- Confidence: {float(data.get('confidence') or 0.0):.0%}",
    ]
    if data.get("evidence_required"):
        lines.append("- Evidence needed: " + ", ".join(data["evidence_required"][:4]))
    if data.get("uncertainty_signals"):
        lines.append("- Uncertain: " + " | ".join(data["uncertainty_signals"][:4]))
    return "\n".join(lines)


def _normalize_prompt(text: str) -> str:
    try:
        from tech_connector.services.prompt_task_splitter_service import normalize_prompt_text
        return re.sub(r"\s+", " ", normalize_prompt_text(text)).strip()
    except Exception:
        return re.sub(r"\s+", " ", text or "").strip()


def _safe_clause_plan(text: str) -> dict[str, Any]:
    try:
        from tech_connector.services.prompt_task_splitter_service import split_prompt_clauses
        return split_prompt_clauses(text).to_dict()
    except Exception:
        return {}


def _safe_intent_frame(text: str) -> dict[str, Any]:
    try:
        from tech_connector.services.prompt_intent_service import parse_intent_frame
        return parse_intent_frame(text).to_dict()
    except Exception:
        return {}


def _safe_target_entities(text: str) -> list[dict[str, Any]]:
    try:
        from tech_connector.services.target_entity_service import extract_target_entities
        return [item.to_dict() for item in extract_target_entities(text)]
    except Exception:
        return []


def _safe_scoped_query(text: str) -> dict[str, Any]:
    try:
        from tech_connector.services.target_entity_service import parse_scoped_member_query
        parsed = parse_scoped_member_query(text)
        return parsed.to_dict() if parsed else {}
    except Exception:
        return {}


def _deliverable_type(
    lower: str,
    *,
    baseline: dict[str, Any],
    scoped_query: dict[str, Any],
    intent_frame: dict[str, Any],
) -> str:
    if scoped_query:
        return str(scoped_query.get("member_type") or "symbol")
    if str(baseline.get("primary_intent") or "") == "comparison":
        return "comparison"
    if _FILE_DELIVERABLE_RE.search(lower):
        return "file"
    if _SYMBOL_DELIVERABLE_RE.search(lower):
        match = _SYMBOL_DELIVERABLE_RE.search(lower)
        if match:
            token = match.group(1).lower()
            return {
                "function": "function",
                "method": "method",
                "class": "class",
                "helper": "helper",
                "symbol": "symbol",
            }.get(token, "symbol")
    requested_member_type = str(baseline.get("requested_member_type") or "")
    if requested_member_type in {"file", "function", "method", "class", "helper", "symbol", "widget"}:
        return requested_member_type
    requested = str(baseline.get("requested_artifact") or "")
    if "file" in requested:
        return "file"
    if requested.startswith("scoped_"):
        return requested.replace("scoped_", "").replace("_search", "")
    object_type = str(intent_frame.get("object_type") or "")
    if object_type:
        return object_type
    goal_type = str(baseline.get("goal_type") or "")
    if goal_type == "modify":
        return "code_change"
    if goal_type in {"explain", "learn"}:
        return "explanation"
    return "answer"


def _goal_type(
    lower: str,
    *,
    deliverable_type: str,
    baseline: dict[str, Any],
    intent_frame: dict[str, Any],
) -> str:
    baseline_goal = str(baseline.get("goal_type") or "")
    if baseline_goal and baseline_goal != "respond":
        return baseline_goal
    if _LOCATION_PREFIX_RE.search(lower):
        return "locate"
    action = str(intent_frame.get("action") or "")
    return {
        "inspect": "locate",
        "create": "modify",
        "add": "modify",
        "modify": "modify",
        "repair": "modify",
        "refactor": "modify",
        "execute": "execute",
    }.get(action, "respond")


def _canonical_action(
    lower: str,
    *,
    baseline: dict[str, Any],
    intent_frame: dict[str, Any],
    goal_type: str,
) -> str:
    if goal_type == "locate":
        return "locate"
    baseline_action = str(baseline.get("primary_action") or "")
    if baseline_action:
        return baseline_action
    frame_action = str(intent_frame.get("action") or "")
    if frame_action:
        return frame_action
    for canonical in ("execute", "modify", "validate", "create", "find"):
        if _contains_action(lower, canonical):
            return canonical
    return "respond"


def _subject(
    text: str,
    *,
    deliverable_type: str,
    baseline: dict[str, Any],
    scoped_query: dict[str, Any],
    intent_frame: dict[str, Any],
) -> tuple[str, str]:
    if scoped_query:
        return (
            str(scoped_query.get("member_type") or "symbol"),
            str(scoped_query.get("behavior_description") or ""),
        )

    baseline_subject = (
        str(baseline.get("requested_member_type") or "")
        or str(baseline.get("requested_artifact") or "")
    )
    target_symbol = str(baseline.get("target_symbol") or "")
    if target_symbol:
        return "symbol", target_symbol

    if deliverable_type == "file":
        object_phrase = _extract_after_file_question(text)
        return "implementation", object_phrase or "requested behavior"
    execution_match = re.search(
        r"\b(?:run|execute|call|launch|perform|apply)\s+"
        r"([A-Za-z_][A-Za-z0-9_.]*)\b",
        text,
        re.IGNORECASE,
    )
    if execution_match:
        return "callable", execution_match.group(1)
    if deliverable_type in {"function", "method", "class", "helper", "symbol"}:
        return deliverable_type, _extract_behavior_phrase(text)
    if baseline_subject:
        return baseline_subject, str(baseline.get("behavior_description") or "")
    return str(intent_frame.get("object_type") or ""), str(intent_frame.get("target_text") or "")


def _relationship(
    lower: str,
    *,
    deliverable_type: str,
    subject_type: str,
    scoped_query: dict[str, Any],
) -> str:
    if scoped_query:
        return "member_of_container"
    if deliverable_type == "file" and subject_type in {"implementation", "function", "method", "class", "symbol"}:
        return "contains"
    if re.search(r"\b(calls?|uses?|references?)\b", lower):
        return "calls_or_uses"
    if re.search(r"\b(returns?|produces?)\b", lower):
        return "returns"
    if re.search(r"\b(creates?|builds?|generates?|makes?)\b", lower):
        return "implements_behavior"
    return "matches"


def _container(
    text: str,
    *,
    deliverable_type: str,
    scoped_query: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[str, str]:
    if scoped_query:
        return (
            str(scoped_query.get("container_type") or "file"),
            str(scoped_query.get("container_query") or ""),
        )
    container_type = str(baseline.get("target_container_type") or "")
    container_query = str(baseline.get("target_container_query") or "")
    if container_type or container_query:
        return container_type or "file", container_query
    if deliverable_type == "file":
        return "project", ""
    return "", ""


def _behavior(
    text: str,
    *,
    action: str,
    subject_text: str,
    baseline: dict[str, Any],
    scoped_query: dict[str, Any],
) -> str:
    if scoped_query:
        return str(scoped_query.get("behavior_description") or "")
    baseline_behavior = str(
        baseline.get("member_behavior")
        or baseline.get("behavior_description")
        or ""
    ).strip()
    if baseline_behavior:
        return baseline_behavior
    phrase = _extract_behavior_phrase(text)
    if phrase:
        return phrase
    if action == "execute" and subject_text:
        return subject_text
    return " ".join(part for part in (action, subject_text) if part).strip()


def _extract_after_file_question(text: str) -> str:
    patterns = (
        r"\bwhat\s+file\s+(.+?)(?:\?|$)",
        r"\bwhich\s+file\s+(.+?)(?:\?|$)",
        r"\bfind\s+(?:the\s+)?file\s+(?:that|which|to|for)?\s*(.+?)(?:\?|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(1).strip(" .?")
            phrase = re.sub(r"^(?:does|do|is|has|have)\s+", "", phrase, flags=re.IGNORECASE)
            return phrase
    return ""


def _extract_behavior_phrase(text: str) -> str:
    patterns = (
        r"\b(?:that|which|to|for)\s+(.+?)(?:\?|$)",
        r"\b(?:function|method|helper|implementation)\s+(.+?)(?:\?|$)",
        r"\b(?:file)\s+(.+?)(?:\?|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .?")
            value = re.sub(
                r"^(?:does|do|is|has|have)\s+",
                "",
                value,
                flags=re.IGNORECASE,
            )
            if value:
                return value
    return ""


def _contains_action(lower: str, canonical: str) -> bool:
    terms = _BEHAVIOR_VERBS.get(canonical, (canonical,))
    return any(re.search(rf"\b{re.escape(term)}\b", lower) for term in terms)


def _detect_host(lower: str) -> str:
    aliases = {
        "maya": ("maya",),
        "unreal": ("unreal", "ue5", "ue4"),
        "blender": ("blender",),
        "houdini": ("houdini",),
        "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
        "unity": ("unity",),
    }
    for host, values in aliases.items():
        if any(re.search(rf"\b{re.escape(value)}\b", lower) for value in values):
            return host
    return ""


def _context_source(
    *,
    deliverable_type: str,
    host_domain: str,
    execution_requested: bool,
    baseline: dict[str, Any],
) -> str:
    if execution_requested and host_domain:
        return "live_dcc"
    if deliverable_type in {"file", "function", "method", "class", "helper", "symbol", "implementation"}:
        return "project_index"
    if str(baseline.get("reference_scope") or "") == "conversation_reference":
        return "conversation"
    return "conversation_or_project_context"


def _assumptions(
    *,
    deliverable_type: str,
    subject_type: str,
    host_domain: str,
    relationship: str,
    read_only: bool,
) -> list[str]:
    assumptions: list[str] = []
    if deliverable_type == "file":
        assumptions.append("The user wants source-code location, not a scene asset.")
    if host_domain and read_only:
        assumptions.append(f"{host_domain.title()} narrows domain context but does not require a live host.")
    if relationship == "contains":
        assumptions.append("The file should be justified by supporting symbols, not filename text alone.")
    if subject_type == "implementation":
        assumptions.append("Equivalent verbs such as create, build, generate, make, and setup may express the behavior.")
    return assumptions


def _unresolved_fields(
    *,
    deliverable_type: str,
    subject_text: str,
    container_query: str,
    host_domain: str,
    execution_requested: bool,
) -> list[str]:
    unresolved: list[str] = []
    if deliverable_type in {"file", "function", "method", "class", "helper", "symbol"} and not subject_text:
        unresolved.append("subject_behavior")
    if container_query == "that" or container_query == "this":
        unresolved.append("conversation_reference")
    if execution_requested and not host_domain:
        unresolved.append("execution_environment")
    return unresolved


def _expected_outputs(
    *,
    deliverable_type: str,
    subject_type: str,
    goal_type: str,
) -> list[str]:
    if goal_type == "locate" and deliverable_type == "file":
        return ["file_path", "supporting_symbol_names", "evidence_summary"]
    if goal_type == "locate":
        return [f"{deliverable_type}_matches", "locations", "evidence_summary"]
    if goal_type == "modify":
        return ["changed_files", "change_summary", "validation_result"]
    if goal_type == "execute":
        return ["execution_result", "validation_result"]
    return ["response"]


def _evidence_required(
    *,
    deliverable_type: str,
    subject_type: str,
    relationship: str,
    behavior: str,
) -> list[str]:
    evidence: list[str] = []
    if deliverable_type == "file":
        evidence.extend(["matching symbol name", "containing file path"])
    if relationship == "contains":
        evidence.append("symbol belongs to returned file")
    if behavior:
        evidence.extend(["behavior match in symbol name, signature, docstring, or source"])
    if subject_type in {"implementation", "function", "method", "helper"}:
        evidence.append("narrow unrelated helpers are demoted")
    return _ordered_unique(evidence)


def _success_definition(
    *,
    goal_type: str,
    deliverable_type: str,
    subject_type: str,
    relationship: str,
    behavior: str,
) -> str:
    if goal_type == "locate" and deliverable_type == "file":
        return (
            "Return the strongest matching project file, the supporting functions "
            f"or methods that {behavior or 'implement the requested behavior'}, "
            "and enough evidence to explain why that file is the answer."
        )
    if goal_type == "locate":
        return (
            f"Return the relevant {deliverable_type} matches with locations and "
            "evidence, or explicitly confirm that no reliable match exists."
        )
    if goal_type == "modify":
        return "Apply only the requested change, preserve unrelated behavior, and provide validation evidence."
    if goal_type == "execute":
        return "Run the resolved operation and verify the resulting host state."
    return "Produce a complete response that satisfies the requested deliverable."



def _build_plan_steps(
    *,
    goal_type: str,
    deliverable_type: str,
    subject_type: str,
    relationship: str,
    container_type: str,
    container_query: str,
    behavior: str,
    mutation_requested: bool,
    execution_requested: bool,
    evidence_required: list[str],
) -> list[dict[str, Any]]:
    """Create a bounded semantic plan before routing or taking action."""

    steps: list[dict[str, Any]] = []

    def add(
        step_id: str,
        action: str,
        objective: str,
        *,
        depends_on: list[str] | None = None,
        produces: list[str] | None = None,
        read_only: bool = True,
        success_condition: str = "",
        requires_reasoning: bool = False,
        requires_confirmation: bool = False,
    ) -> None:
        steps.append(
            {
                "step_id": step_id,
                "goal_id": step_id,
                "action": action,
                "objective": objective,
                "depends_on": list(depends_on or []),
                "produces": list(produces or []),
                "read_only": bool(read_only),
                "success_condition": success_condition,
                "requires_reasoning": bool(requires_reasoning),
                "requires_confirmation": bool(requires_confirmation),
            }
        )

    if goal_type == "locate" and deliverable_type == "file" and relationship == "contains":
        add(
            "interpret_behavior",
            "analyze",
            f"Translate the requested behavior into searchable implementation concepts: {behavior or 'requested behavior'}.",
            produces=["behavior_search_terms", "behavior_synonyms"],
            success_condition="The behavior is represented by precise domain terms and controlled synonyms.",
            requires_reasoning=True,
        )
        add(
            "find_candidate_symbols",
            "search",
            "Find functions, methods, or classes that implement the requested behavior.",
            depends_on=["interpret_behavior"],
            produces=["candidate_symbols"],
            success_condition="Candidate symbols are found or their absence is confirmed.",
        )
        add(
            "resolve_containing_files",
            "resolve",
            "Resolve the project files containing the candidate symbols.",
            depends_on=["find_candidate_symbols"],
            produces=["candidate_files"],
            success_condition="Every candidate symbol is associated with its containing source file.",
        )
        add(
            "rank_file_evidence",
            "rank",
            "Rank files using contained-symbol evidence and demote narrow or unrelated helpers.",
            depends_on=["resolve_containing_files"],
            produces=["ranked_files"],
            success_condition="The strongest file is separated from weaker alternatives by explicit evidence.",
            requires_reasoning=True,
        )
        add(
            "report_location",
            "report",
            "Return the best file path, supporting symbols, and why they answer the request.",
            depends_on=["rank_file_evidence"],
            produces=["final_answer"],
            success_condition="The answer includes the requested file and supporting implementation evidence.",
            requires_reasoning=True,
        )
        return steps

    if goal_type == "locate" and container_query:
        add(
            "resolve_container",
            "search",
            f"Resolve the {container_type or 'container'} described as '{container_query}'.",
            produces=["resolved_container"],
            success_condition="One container is resolved or ambiguity is explicitly reported.",
        )
        add(
            "find_members",
            "search",
            f"Find {deliverable_type}s in the resolved container that {behavior or 'match the requested behavior'}.",
            depends_on=["resolve_container"],
            produces=["candidate_members"],
            success_condition="Relevant members are identified within the resolved container only.",
        )
        add(
            "rank_members",
            "rank",
            "Compare candidate members against the requested behavior and evidence requirements.",
            depends_on=["find_members"],
            produces=["ranked_members"],
            success_condition="Behaviorally strong matches are separated from incidental text matches.",
            requires_reasoning=True,
        )
        add(
            "report_members",
            "report",
            "Return the best matching members with locations and evidence.",
            depends_on=["rank_members"],
            produces=["final_answer"],
            success_condition="The answer directly identifies which members satisfy the request.",
            requires_reasoning=True,
        )
        return steps

    if goal_type == "modify" or mutation_requested:
        add(
            "resolve_target",
            "search",
            "Resolve the exact file, symbol, asset, or graph target before editing.",
            produces=["resolved_target"],
            success_condition="The edit target is uniquely resolved or clarification is requested.",
        )
        add(
            "inspect_context",
            "inspect",
            "Inspect the target, callers, dependencies, nearby patterns, and applicable constraints.",
            depends_on=["resolve_target"],
            produces=["target_context", "reuse_candidates"],
            success_condition="Enough project evidence exists to design a safe minimal change.",
        )
        add(
            "design_change",
            "plan",
            "Design the smallest change that satisfies the request while preserving unrelated behavior.",
            depends_on=["inspect_context"],
            produces=["change_plan"],
            success_condition="The plan names exact edits, validation, and rollback considerations.",
            requires_reasoning=True,
        )
        add(
            "apply_change",
            "modify_code",
            "Apply the approved or safe scoped change.",
            depends_on=["design_change"],
            produces=["changed_artifacts"],
            read_only=False,
            success_condition="Only the resolved target and required supporting code are changed.",
            requires_confirmation=False,
        )
        add(
            "validate_change",
            "validate",
            "Compile, syntax-check, test, or inspect the resulting behavior.",
            depends_on=["apply_change"],
            produces=["validation_result"],
            success_condition="Concrete validation evidence confirms success or identifies a repair need.",
        )
        add(
            "report_change",
            "report",
            "Report changed files, behavior, validation evidence, warnings, and unresolved risks.",
            depends_on=["validate_change"],
            produces=["final_answer"],
            success_condition="The user receives an accountable verified outcome.",
            requires_reasoning=True,
        )
        return steps

    if goal_type == "execute" or execution_requested:
        add(
            "resolve_callable",
            "search",
            "Resolve the exact callable or host operation and its required inputs.",
            produces=["resolved_callable", "validated_inputs"],
            success_condition="The operation and inputs are unambiguous.",
        )
        add(
            "preflight_execution",
            "validate",
            "Confirm host connection, safety requirements, and expected observable result.",
            depends_on=["resolve_callable"],
            produces=["preflight_result"],
            success_condition="Execution is safe and the success signal is defined.",
        )
        add(
            "execute_operation",
            "execute",
            "Run the resolved operation through the deterministic host bridge.",
            depends_on=["preflight_execution"],
            produces=["execution_result"],
            read_only=False,
            success_condition="The host returns a structured execution result.",
        )
        add(
            "verify_host_result",
            "validate",
            "Verify the resulting host state against the requested objective.",
            depends_on=["execute_operation"],
            produces=["validation_result"],
            success_condition="The resulting state satisfies the objective or a repair path is identified.",
        )
        add(
            "report_execution",
            "report",
            "Report the executed operation, result, validation, and warnings.",
            depends_on=["verify_host_result"],
            produces=["final_answer"],
            success_condition="The user receives a clear verified execution outcome.",
        )
        return steps

    add(
        "understand_request",
        "analyze",
        "Resolve the requested deliverable, subject, relationships, constraints, and success criteria.",
        produces=["semantic_request"],
        success_condition="The request has a concrete outcome and no critical semantic ambiguity.",
        requires_reasoning=True,
    )
    add(
        "gather_evidence",
        "search",
        "Gather only the evidence needed to answer the interpreted request.",
        depends_on=["understand_request"],
        produces=["relevant_evidence"],
        success_condition="The evidence is sufficient for the requested deliverable.",
    )
    add(
        "synthesize_answer",
        "report",
        "Produce the requested answer from the interpreted request and gathered evidence.",
        depends_on=["gather_evidence"],
        produces=["final_answer"],
        success_condition="The response directly satisfies the requested deliverable.",
        requires_reasoning=True,
    )
    return steps


def _planning_rationale(
    *,
    goal_type: str,
    deliverable_type: str,
    relationship: str,
    plan_steps: list[dict[str, Any]],
) -> str:
    if goal_type == "locate" and deliverable_type == "file" and relationship == "contains":
        return (
            "A file-location question about behavior must first find the implementing "
            "symbols, then resolve and rank their containing files; searching raw prompt "
            "words against file text is insufficient."
        )
    if goal_type == "modify":
        return (
            "Mutation requires target resolution and context inspection before any edit, "
            "followed by deterministic validation and accountable reporting."
        )
    if goal_type == "execute":
        return (
            "Host execution requires callable resolution and preflight validation before "
            "the operation, then verification of the resulting host state."
        )
    return (
        f"The request is decomposed into {len(plan_steps)} dependency-ordered step(s) "
        "so interpretation and evidence gathering occur before the terminal action."
    )

def _canonical_goal(
    *,
    goal_type: str,
    deliverable_type: str,
    subject_type: str,
    subject_text: str,
    relationship: str,
    container_type: str,
    container_query: str,
    behavior: str,
    host_domain: str,
) -> str:
    if goal_type == "locate" and deliverable_type == "file":
        detail = behavior or subject_text or "the requested behavior"
        return (
            "Find the project file containing an implementation that "
            f"{_third_person_behavior(detail)}."
        )
    if goal_type == "locate" and container_query:
        detail = behavior or subject_text or "match the requested behavior"
        return (
            f"Find {deliverable_type}s in the {container_type} described as "
            f"'{container_query}' that {detail}."
        )
    if goal_type == "locate":
        detail = subject_text or behavior or "the requested target"
        return f"Locate the {deliverable_type} for {detail}."
    if goal_type == "modify":
        return f"Modify {subject_text or subject_type or 'the requested target'} as requested."
    if goal_type == "execute":
        host_label = f" in {host_domain.title()}" if host_domain else ""
        return f"Execute {subject_text or behavior or 'the requested operation'}{host_label}."
    return subject_text or behavior or "Respond to the request."


def _third_person_behavior(behavior: str) -> str:
    value = re.sub(r"\s+", " ", str(behavior or "")).strip(" .?")
    value = re.sub(r"^(?:does|do|is|has|have)\s+", "", value, flags=re.IGNORECASE)
    match = re.match(
        r"^(create|creating|build|building|make|making|generate|generating|find|finding|detect|detecting|resolve|resolving|handle|handling|use|using|call|calling|validate|validating|return|returning)\b(.*)$",
        value,
        re.IGNORECASE,
    )
    if not match:
        return value or "matches the requested behavior"
    verb = {
        "creating": "create",
        "building": "build",
        "making": "make",
        "generating": "generate",
        "finding": "find",
        "detecting": "detect",
        "resolving": "resolve",
        "handling": "handle",
        "using": "use",
        "calling": "call",
        "validating": "validate",
        "returning": "return",
    }.get(match.group(1).lower(), match.group(1).lower())
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


def _confidence(
    *,
    deliverable_type: str,
    goal_type: str,
    subject_text: str,
    relationship: str,
    container_query: str,
    unresolved_fields: list[str],
    baseline: dict[str, Any],
    scoped_query: dict[str, Any],
) -> tuple[float, list[str], list[str]]:
    score = 0.45
    signals: list[str] = []
    uncertainty: list[str] = []

    if deliverable_type and deliverable_type != "answer":
        score += 0.16
        signals.append(f"Deliverable resolved as {deliverable_type}.")
    if goal_type and goal_type != "respond":
        score += 0.12
        signals.append(f"Goal type resolved as {goal_type}.")
    if subject_text:
        score += 0.12
        signals.append("Requested subject or behavior was preserved.")
    if relationship:
        score += 0.08
        signals.append(f"Relationship resolved as {relationship}.")
    if container_query:
        score += 0.08
        signals.append("Container scope was preserved.")
    if scoped_query:
        score = max(score, float(scoped_query.get("confidence") or 0.0))
        signals.append("Scoped member grammar matched deterministically.")

    baseline_confidence = float(baseline.get("confidence") or 0.0)
    if baseline_confidence:
        score = max(score, min(0.98, baseline_confidence))

    for field_name in unresolved_fields:
        score -= 0.12
        uncertainty.append(f"Unresolved {field_name.replace('_', ' ')}.")
    if deliverable_type == "file" and relationship == "contains":
        signals.append("Answer requires both file and contained-symbol evidence.")

    return (
        round(max(0.05, min(0.99, score)), 3),
        _ordered_unique(signals),
        _ordered_unique(uncertainty),
    )


def _extract_constraints(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(
        r"\b(?:do not|don't|dont|never|only|must|without|preserve|reuse|before|after|until)\b[^.;]*",
        text,
        re.IGNORECASE,
    ):
        value = re.sub(r"\s+", " ", match.group(0)).strip()
        if value:
            values.append(value)
    return _ordered_unique(values)


def _ordered_unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
