"""Problem formulation and meaning-graph construction.

This stage runs before routing, retrieval, mutation, or DCC execution. Its job
is not to classify a prompt. It explains the problem another engineer would
need to solve, identifies what must become true before the request can be
completed, and constructs a meaning graph from which executable plans can be
derived.

The service is deterministic by default and accepts an optional semantic
interpreter/critic callback. Model output is advisory until it passes the
adequacy checks in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable, Iterable, Optional


@dataclass(frozen=True)
class MeaningNode:
    node_id: str
    kind: str
    label: str
    value: str = ""
    known: bool = False
    required: bool = True
    source: str = "formulation"
    confidence: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeaningEdge:
    source: str
    relation: str
    target: str
    required: bool = True
    confidence: float = 0.7
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProblemFormulation:
    original_prompt: str
    normalized_prompt: str
    literal_request: str
    interpreted_problem: str
    desired_outcome: str
    deliverables: list[str] = field(default_factory=list)
    subject: str = ""
    action_mode: str = "understand"
    scope: str = ""
    relationships: list[str] = field(default_factory=list)
    knowns: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    blocking_unknowns: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    success_conditions: list[str] = field(default_factory=list)
    failure_conditions: list[str] = field(default_factory=list)
    meaning_nodes: list[MeaningNode] = field(default_factory=list)
    meaning_edges: list[MeaningEdge] = field(default_factory=list)
    candidate_plan: list[dict[str, Any]] = field(default_factory=list)
    critique: list[str] = field(default_factory=list)
    revisions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    adequate: bool = False
    can_plan: bool = False
    requires_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["framework"] = "problem_formulation_v2"
        data["meaning_graph"] = {
            "framework": "meaning_graph_v1",
            "nodes": [node.to_dict() for node in self.meaning_nodes],
            "edges": [edge.to_dict() for edge in self.meaning_edges],
        }
        return data


SemanticCallback = Callable[[dict[str, Any]], Optional[dict[str, Any]]]


_QUESTION_START = re.compile(
    r"^\s*(what|which|where|who|why|how|show|find|list|identify|explain|tell me)\b",
    re.IGNORECASE,
)
_MUTATION = re.compile(
    r"\b(add|create|implement|write|patch|modify|update|fix|repair|refactor|rename|remove|delete|wire|connect|build)\b",
    re.IGNORECASE,
)
_EXECUTION = re.compile(r"\b(run|execute|launch|call|apply)\b", re.IGNORECASE)
_SOURCE_NOUNS = re.compile(
    r"\b(file|files|function|functions|method|methods|class|classes|code|source|module|script|implementation)\b",
    re.IGNORECASE,
)
_DCC_NOUNS = re.compile(
    r"\b(scene|selected|selection|object|objects|node|nodes|joint|joints|mesh|asset|graph|control|rig)\b",
    re.IGNORECASE,
)
_FILE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b")
_SYMBOL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b")
_UNREAL_ASSET_RE = re.compile(r"(?<![A-Za-z0-9_])(/Game/[A-Za-z0-9_./-]+)")
_PLAN_ONLY_RE = re.compile(
    r"\b(?:plan\s+only|implementation\s+plan|plan\s+for\s+approval|"
    r"first\s+produce.{0,40}\bplan|do\s+not\s+(?:mutate|edit|modify|save|execute)|"
    r"before\s+(?:any\s+)?mutation)\b",
    re.IGNORECASE,
)


def build_problem_formulation(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
    request_understanding: dict[str, Any] | Any | None = None,
    semantic_contract: dict[str, Any] | Any | None = None,
    semantic_interpreter: SemanticCallback | None = None,
    semantic_critic: SemanticCallback | None = None,
) -> ProblemFormulation:
    """Form the problem without taking ownership of intent or execution planning.

    ``request_understanding`` and ``semantic_contract`` are canonical upstream
    inputs.  ``decision`` remains a compatibility carrier for older callers.
    The formulation service may critique meaning, but it must not select a
    route or create an independent execution contract.
    """

    decision = dict(decision or {})
    context = dict(context or {})
    understanding_data = (
        request_understanding.to_dict()
        if hasattr(request_understanding, "to_dict")
        else dict(request_understanding or decision.get("request_understanding") or {})
    )
    contract_data = (
        semantic_contract.to_dict()
        if hasattr(semantic_contract, "to_dict")
        else dict(
            semantic_contract
            or decision.get("semantic_execution_contract")
            or understanding_data.get("semantic_execution_contract")
            or {}
        )
    )
    decision["request_understanding"] = understanding_data
    decision["semantic_execution_contract"] = contract_data
    raw = str(prompt or "")
    normalized = _normalize(raw)

    facts = _collect_facts(normalized, decision, context)
    formulation = _deterministic_formulation(normalized, facts, decision, context)

    if semantic_interpreter is not None:
        proposed = _safe_callback(
            semantic_interpreter,
            {
                "stage": "problem_formulation",
                "instruction": (
                    "Explain the problem to solve, not the route or search query. "
                    "Preserve grammatical roles, desired deliverables, relationships, "
                    "unknowns, prerequisites, exclusions, evidence, and success conditions. "
                    "Determine what must become true before any action can safely occur. "
                    "For helper or function design, first determine whether an equivalent "
                    "capability already exists. Then require target/input validation, host API "
                    "availability, type filtering, namespace and long-path handling where "
                    "relevant, stable ordering, duplicate handling, configurable matching "
                    "rules, clear return shape, non-mutation guarantees when requested, and "
                    "focused static plus host-runtime validation."
                ),
                "prompt": normalized,
                "facts": facts,
                "context": _compact_context(context),
                "current_formulation": formulation.to_dict(),
            },
        )
        if proposed:
            formulation = _merge_model_formulation(formulation, proposed)
            formulation.source = "semantic_interpreter"

    critique = _deterministic_critique(formulation)
    if semantic_critic is not None:
        model_critique = _safe_callback(
            semantic_critic,
            {
                "stage": "problem_formulation_critique",
                "instruction": (
                    "Criticize the formulation. Identify lost grammatical roles, "
                    "premature actions, missing prerequisites, missing exclusions, "
                    "and any reason the proposed plan could answer a related but "
                    "different question."
                ),
                "prompt": normalized,
                "formulation": formulation.to_dict(),
            },
        )
        if model_critique:
            critique.extend(_strings(model_critique.get("critique") or model_critique.get("issues") or []))

    formulation.critique = _uniq(critique)
    formulation = _revise_formulation(formulation)
    formulation.adequate, adequacy_issues = evaluate_formulation_adequacy(formulation)
    formulation.critique = _uniq([*formulation.critique, *adequacy_issues])
    formulation.requires_clarification = bool(formulation.blocking_unknowns)
    formulation.can_plan = formulation.adequate and not formulation.requires_clarification
    formulation.clarification_questions = _clarification_questions(formulation)
    formulation.confidence = _confidence(formulation)
    return formulation


def evaluate_formulation_adequacy(
    formulation: ProblemFormulation | dict[str, Any],
) -> tuple[bool, list[str]]:
    data = formulation.to_dict() if isinstance(formulation, ProblemFormulation) else dict(formulation or {})
    issues: list[str] = []

    if not str(data.get("desired_outcome") or "").strip():
        issues.append("Desired user-visible outcome is missing.")
    if not list(data.get("deliverables") or []):
        issues.append("Requested deliverable is not explicit.")
    if not list(data.get("success_conditions") or []):
        issues.append("No testable success condition was defined.")
    if not list(data.get("candidate_plan") or []):
        issues.append("No dependency-ordered path was formulated.")
    if data.get("action_mode") in {"mutate", "execute"}:
        plan_actions = [str(item.get("action") or "") for item in data.get("candidate_plan") or []]
        if not any(action in {"inspect", "resolve", "discover", "analyze", "preflight"} for action in plan_actions):
            issues.append("Mutation/execution plan acts before resolving target and context.")
        if not any(action == "validate" for action in plan_actions):
            issues.append("Mutation/execution plan lacks validation.")
    relationship_blob = " ".join(data.get("relationships") or []).lower()
    if data.get("deliverables") == ["files"] and not any(
        token in relationship_blob for token in ("contain", "member_of", "belongs")
    ):
        issues.append("File deliverable does not preserve the requested containment relationship.")
    interpreted = str(data.get("interpreted_problem") or "").lower()
    if interpreted in {"search project fact", "respond to request", "complete requested objective"}:
        issues.append("Interpretation is a generic route label rather than a problem statement.")
    return not issues, issues


def problem_formulation_context(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
    max_chars: int = 5000,
) -> str:
    formulation = build_problem_formulation(prompt, decision, context=context)
    data = formulation.to_dict()
    lines = [
        "PROBLEM FORMULATION — REQUIRED BEFORE ACTION:",
        f"Literal request: {data['literal_request']}",
        f"Problem to solve: {data['interpreted_problem']}",
        f"Desired outcome: {data['desired_outcome']}",
        f"Action mode: {data['action_mode']}",
        f"Deliverables: {', '.join(data['deliverables']) or '(unresolved)'}",
        f"Subject: {data['subject'] or '(unresolved)'}",
    ]
    if data["relationships"]:
        lines.append("Meaning relationships:")
        lines.extend(f"- {item}" for item in data["relationships"])
    if data["unknowns"]:
        lines.append("Unknowns to resolve:")
        lines.extend(f"- {item}" for item in data["unknowns"])
    if data["exclusions"]:
        lines.append("Do not confuse with:")
        lines.extend(f"- {item}" for item in data["exclusions"])
    if data["candidate_plan"]:
        lines.append("Dependency-ordered formulation plan:")
        for item in data["candidate_plan"]:
            deps = ", ".join(item.get("depends_on") or [])
            suffix = f" after [{deps}]" if deps else ""
            lines.append(f"- {item.get('step_id')}: {item.get('objective')}{suffix}")
    if data["success_conditions"]:
        lines.append("Success conditions:")
        lines.extend(f"- {item}" for item in data["success_conditions"])
    lines.append(f"Adequate={str(data['adequate']).lower()} can_plan={str(data['can_plan']).lower()} confidence={data['confidence']:.2f}")
    return "\n".join(lines)[:max_chars].rstrip()


def _collect_facts(
    prompt: str,
    decision: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    understanding = dict(decision.get("request_understanding") or {})
    semantic_contract = dict(
        decision.get("semantic_execution_contract")
        or understanding.get("semantic_execution_contract")
        or {}
    )
    if understanding:
        intent_frame = {
            "action": understanding.get("primary_action", ""),
            "object_type": understanding.get("requested_artifact", ""),
            "target_text": (
                understanding.get("target_symbol")
                or understanding.get("target_file")
                or understanding.get("behavior_description")
                or ""
            ),
            "requested_scope": (
                understanding.get("target_container_query")
                or understanding.get("target_file")
                or ""
            ),
            "negative_constraints": list(understanding.get("constraints") or []),
            "source": "canonical_request_understanding",
        }
    else:
        try:
            from tech_connector.services.prompt.prompt_intent_service import parse_intent_frame
            intent_frame = parse_intent_frame(prompt).to_dict()
        except Exception:
            intent_frame = {}
    files = _uniq(_FILE_RE.findall(prompt))
    symbols = _uniq(
        value for value in _SYMBOL_RE.findall(prompt)
        if not value.lower().endswith((".py", ".json", ".txt", ".md"))
    )
    assets = _uniq(value.rstrip(".,;:)") for value in _UNREAL_ASSET_RE.findall(prompt))
    momentum = context.get("context_momentum") or decision.get("context_momentum") or {}
    recent_targets = list(momentum.get("targets") or []) if isinstance(momentum, dict) else []
    return {
        "intent_frame": intent_frame,
        "semantic_contract": semantic_contract,
        "explicit_files": files,
        "explicit_symbols": symbols,
        "explicit_assets": assets,
        "question_form": bool(_QUESTION_START.search(prompt)),
        "mutation_language": _uniq(match.group(0).lower() for match in _MUTATION.finditer(prompt)),
        "execution_language": _uniq(match.group(0).lower() for match in _EXECUTION.finditer(prompt)),
        "source_language": bool(_SOURCE_NOUNS.search(prompt)),
        "dcc_language": bool(_DCC_NOUNS.search(prompt)),
        "host": str(decision.get("host") or context.get("host") or ""),
        "active_file": str(context.get("active_file") or decision.get("active_file") or ""),
        "recent_targets": recent_targets[:12],
        "conversation_entities": dict(context.get("conversation_entities") or {}),
    }


def _deterministic_formulation(
    prompt: str,
    facts: dict[str, Any],
    decision: dict[str, Any],
    context: dict[str, Any],
) -> ProblemFormulation:
    lower = prompt.lower()
    intent = dict(facts.get("intent_frame") or {})
    contract = dict(facts.get("semantic_contract") or {})

    action_mode = _action_mode(prompt, facts, intent, contract)
    deliverables = _deliverables(prompt, intent, contract)
    subject = _subject(prompt, deliverables, intent, contract)
    scope = _scope(prompt, facts, intent, contract)
    relationships = _relationships(prompt, deliverables, subject, contract)
    knowns = _knowns(prompt, facts, scope)
    unknowns, blocking = _unknowns(
        prompt,
        action_mode=action_mode,
        deliverables=deliverables,
        subject=subject,
        relationships=relationships,
        facts=facts,
    )
    constraints = _constraints(prompt, intent, contract)
    exclusions = _exclusions(
        prompt,
        action_mode=action_mode,
        deliverables=deliverables,
        relationships=relationships,
        subject=subject,
    )
    prerequisites = _prerequisites(
        action_mode=action_mode,
        deliverables=deliverables,
        relationships=relationships,
        unknowns=unknowns,
    )
    evidence = _evidence_required(
        action_mode=action_mode,
        deliverables=deliverables,
        relationships=relationships,
        subject=subject,
    )
    desired = _desired_outcome(deliverables, subject, relationships, action_mode)
    interpreted = _interpreted_problem(
        deliverables=deliverables,
        subject=subject,
        relationships=relationships,
        action_mode=action_mode,
        scope=scope,
    )
    success = _success_conditions(
        deliverables=deliverables,
        subject=subject,
        relationships=relationships,
        action_mode=action_mode,
        evidence=evidence,
    )
    failure = _failure_conditions(
        deliverables=deliverables,
        relationships=relationships,
        action_mode=action_mode,
    )
    nodes, edges = _meaning_graph(
        deliverables=deliverables,
        subject=subject,
        relationships=relationships,
        knowns=knowns,
        unknowns=unknowns,
        desired_outcome=desired,
        scope=scope,
    )
    plan = _candidate_plan(
        action_mode=action_mode,
        deliverables=deliverables,
        subject=subject,
        relationships=relationships,
        prerequisites=prerequisites,
        evidence=evidence,
        unknowns=unknowns,
        primary_route=str(
            decision.get("route")
            or intent.get("primary_route")
            or ""
        ),
        host=str(decision.get("host") or facts.get("host") or ""),
    )

    return ProblemFormulation(
        original_prompt=prompt,
        normalized_prompt=prompt,
        literal_request=prompt,
        interpreted_problem=interpreted,
        desired_outcome=desired,
        deliverables=deliverables,
        subject=subject,
        action_mode=action_mode,
        scope=scope,
        relationships=relationships,
        knowns=knowns,
        unknowns=unknowns,
        blocking_unknowns=blocking,
        assumptions=_assumptions(prompt, facts, action_mode, scope),
        constraints=constraints,
        exclusions=exclusions,
        prerequisites=prerequisites,
        evidence_required=evidence,
        success_conditions=success,
        failure_conditions=failure,
        meaning_nodes=nodes,
        meaning_edges=edges,
        candidate_plan=plan,
        confidence=0.5,
    )


def _action_mode(prompt: str, facts: dict[str, Any], intent: dict[str, Any], contract: dict[str, Any]) -> str:
    lower = prompt.lower()
    if _PLAN_ONLY_RE.search(prompt):
        return "design"
    action = str(intent.get("action") or "")
    if action == "execute" and (
        contract.get("execution_requested") or facts.get("execution_language")
    ):
        return "execute"
    contract_goal = str(contract.get("goal_type") or "")
    if contract_goal in {"locate", "explain", "inspect", "compare"}:
        return "read_only"
    if contract_goal in {"modify", "create", "repair", "refactor"}:
        return "mutate"
    if contract_goal == "execute":
        return "execute"

    question = bool(facts.get("question_form"))
    source_language = bool(facts.get("source_language"))
    if question and source_language:
        return "read_only"
    if action == "inspect":
        return "read_only"
    if action == "execute" and not question:
        return "execute"
    if action in {"add", "create", "modify", "repair", "refactor"}:
        # "what can I do to X to make..." is advisory/design, not automatic mutation.
        if re.search(r"^\s*(what|how)\s+(?:can|could|should|would)\b", lower):
            return "design"
        return "mutate"
    return "understand"


def _deliverables(prompt: str, intent: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    if _PLAN_ONLY_RE.search(prompt):
        return ["implementation_plan"]
    explicit = str(contract.get("deliverable_type") or "")
    if explicit:
        mapping = {
            "file": "files",
            "function": "functions",
            "method": "methods",
            "class": "classes",
            "code_change": "code_changes",
            "explanation": "explanation",
        }
        return [mapping.get(explicit, explicit)]
    lower = prompt.lower()
    for plural, pattern in (
        ("functions", r"\b(?:what|which|find|show|list).{0,30}\bfunctions?\b"),
        ("methods", r"\b(?:what|which|find|show|list).{0,30}\bmethods?\b"),
        ("classes", r"\b(?:what|which|find|show|list).{0,30}\bclasses?\b"),
        ("files", r"\b(?:what|which|find|show|list|where).{0,30}\bfiles?\b"),
    ):
        if re.search(pattern, lower):
            return [plural]
    if re.search(r"\b(make|create|add|implement|write)\s+(?:a|an|the)?\s*function\b", lower):
        return ["function_design"]
    object_type = str(intent.get("object_type") or "")
    if object_type:
        return [object_type]
    return ["answer"]


def _subject(prompt: str, deliverables: list[str], intent: dict[str, Any], contract: dict[str, Any]) -> str:
    behavior = str(contract.get("behavior") or contract.get("subject_text") or "").strip()
    if behavior:
        return behavior
    if deliverables == ["files"]:
        match = re.search(
            r"\b(?:what|which)\s+files?\s+(.+?)(?:\?|$)|\bfind\s+(?:the\s+)?files?\s+(?:that|which)?\s*(.+?)(?:\?|$)",
            prompt,
            re.IGNORECASE,
        )
        if match:
            return next((group for group in match.groups() if group), "").strip(" .?")
    if any(item in deliverables for item in ("functions", "methods", "classes")):
        behavior = re.search(
            r"\b(?:actually\s+)?(create|build|find|locate|return|handle|use|call)\s+(.+?)(?:\?|$)",
            prompt,
            re.IGNORECASE,
        )
        if behavior:
            return f"{behavior.group(1)} {behavior.group(2)}".strip()
        match = re.search(
            r"\b(?:functions?|methods?|classes?)\s+(?:in|from|inside|within)\s+(.+?)(?:\?|$)",
            prompt,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" .?")
        behavior = re.search(r"\b(?:actually\s+)?(create|build|find|locate|return|handle|use|call)\s+(.+?)(?:\?|$)", prompt, re.IGNORECASE)
        if behavior:
            return f"{behavior.group(1)} {behavior.group(2)}".strip()
    if "function_design" in deliverables:
        match = re.search(r"\bfunction\s+(?:that|to|for)\s+(.+?)(?:\?|$)", prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .?")
    target = str(intent.get("target_text") or "").strip()
    return target or prompt


def _scope(prompt: str, facts: dict[str, Any], intent: dict[str, Any], contract: dict[str, Any]) -> str:
    container = str(contract.get("container_query") or "").strip()
    if container:
        return container
    files = list(facts.get("explicit_files") or [])
    if files:
        return files[0]
    assets = list(facts.get("explicit_assets") or [])
    if assets:
        return ", ".join(assets)
    requested = str(intent.get("requested_scope") or "")
    if requested:
        return requested
    if re.search(r"\b(that|this)\s+file\b", prompt, re.IGNORECASE):
        recent = _recent_target(facts, "file")
        return recent or "conversation_reference:file"
    return "project"


def _relationships(prompt: str, deliverables: list[str], subject: str, contract: dict[str, Any]) -> list[str]:
    explicit = str(contract.get("relationship") or "")
    if explicit:
        return [explicit]
    lower = prompt.lower()
    if deliverables == ["files"]:
        return ["files contain implementations", f"implementations perform: {subject}"]
    if any(item in deliverables for item in ("functions", "methods", "classes")) and re.search(r"\b(in|from|inside|within)\b", lower):
        return ["members belong to requested container", f"members perform: {subject}"]
    if "function_design" in deliverables:
        return ["target file should contain new or reused helper", f"helper purpose: {subject}"]
    return [f"answer addresses: {subject}"]


def _knowns(prompt: str, facts: dict[str, Any], scope: str) -> list[str]:
    values = [f"Original request: {prompt}"]
    for path in facts.get("explicit_files") or []:
        values.append(f"Explicit file: {path}")
    for symbol in facts.get("explicit_symbols") or []:
        values.append(f"Explicit symbol: {symbol}")
    for asset in facts.get("explicit_assets") or []:
        values.append(f"Explicit Unreal asset: {asset}")
    if scope and not scope.startswith("conversation_reference"):
        values.append(f"Requested scope: {scope}")
    host = str(facts.get("host") or "")
    if host:
        values.append(f"Host/domain context: {host}")
    return _uniq(values)


def _unknowns(
    prompt: str,
    *,
    action_mode: str,
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    facts: dict[str, Any],
) -> tuple[list[str], list[str]]:
    unknowns: list[str] = []
    blocking: list[str] = []
    if not subject or subject == prompt:
        unknowns.append("Precise subject or behavior the result must satisfy.")
    if any("conversation_reference" in value for value in [str(_scope(prompt, facts, {}, {}))]):
        unknowns.append("The concrete file referred to by 'that/this file'.")
        blocking.append("Resolve the conversation file reference.")
    if deliverables == ["files"]:
        unknowns.extend([
            "Which symbols actually implement the requested behavior.",
            "Which files contain those symbols.",
            "Whether candidates implement the complete behavior or only a narrow subtask.",
        ])
    if "function_design" in deliverables:
        unknowns.extend([
            "Whether an equivalent helper already exists.",
            "Existing naming, traversal, filtering, and return-shape conventions.",
            "The safest insertion point and validation strategy.",
        ])
    if action_mode in {"mutate", "execute"}:
        explicit_callable = bool(
            re.search(
                r"\b(?:run|execute|call|launch)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                prompt,
                re.IGNORECASE,
            )
        )
        if (
            not facts.get("explicit_files")
            and not facts.get("explicit_symbols")
            and not facts.get("explicit_assets")
            and not explicit_callable
        ):
            unknowns.append("The exact target to modify or execute.")
            blocking.append("Resolve one concrete mutation/execution target.")
        unknowns.append("The observable validation that proves the operation succeeded.")
    return _uniq(unknowns), _uniq(blocking)


def _constraints(prompt: str, intent: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    values = [
        *_strings(intent.get("negative_constraints") or []),
        *_strings(contract.get("constraints") or []),
    ]
    for match in re.finditer(
        r"\b(?:do not|don't|dont|never|only|must|without|preserve|reuse|before|after)\b[^.;]*",
        prompt,
        re.IGNORECASE,
    ):
        values.append(match.group(0).strip())
    return _uniq(values)


def _exclusions(
    prompt: str,
    *,
    action_mode: str,
    deliverables: list[str],
    relationships: list[str],
    subject: str,
) -> list[str]:
    exclusions: list[str] = []
    if deliverables == ["files"]:
        exclusions.extend([
            "Files that merely contain the same words.",
            "Functions that mention the subject but do not implement it.",
            "Narrow helpers unless the user asked for that sub-behavior.",
        ])
    if "function_design" in deliverables:
        exclusions.extend([
            "Creating a duplicate helper before checking existing implementations.",
            "Listing related functions without answering whether or how to add the requested capability.",
        ])
    if action_mode == "read_only":
        exclusions.extend([
            "Executing a DCC operation merely because the prompt names an executable behavior.",
            "Mutating source files or scene state.",
        ])
    return _uniq(exclusions)


def _prerequisites(
    *,
    action_mode: str,
    deliverables: list[str],
    relationships: list[str],
    unknowns: list[str],
) -> list[str]:
    if deliverables == ["files"]:
        return [
            "Represent the requested behavior precisely.",
            "Find candidate implementing symbols.",
            "Inspect behavioral evidence for each candidate.",
            "Resolve each candidate's containing file.",
            "Rank complete implementations above incidental or narrow matches.",
        ]
    if "function_design" in deliverables:
        return [
            "Resolve the target file.",
            "Inventory existing helpers and related call sites.",
            "Determine whether the capability already exists.",
            "Define the helper contract and insertion point.",
            "Define validation before implementation.",
        ]
    if deliverables == ["implementation_plan"]:
        return [
            "Resolve every explicit project and Unreal asset target.",
            "Preserve each requested behavior, constraint, and failure observation.",
            "Inspect live project evidence before choosing architecture.",
            "Compare applicable current techniques and callable operations.",
            "Define mutation stages, rollback, and runtime proof without executing them.",
        ]
    if action_mode == "mutate":
        return [
            "Resolve exact target.",
            "Inspect current implementation and reusable patterns.",
            "Design smallest safe change.",
            "Validate after mutation.",
        ]
    if action_mode == "execute":
        return [
            "Resolve callable and inputs.",
            "Preflight host and safety constraints.",
            "Define observable success.",
            "Verify host state after execution.",
        ]
    return ["Resolve enough evidence to satisfy the requested deliverable."]


def _evidence_required(
    *,
    action_mode: str,
    deliverables: list[str],
    relationships: list[str],
    subject: str,
) -> list[str]:
    if deliverables == ["files"]:
        return [
            "Matching function/method/class name or signature.",
            "Docstring or source-body evidence for the requested behavior.",
            "Call relationships showing complete implementation responsibility.",
            "Containing source file path.",
            "Negative evidence demoting incidental matches.",
        ]
    if "function_design" in deliverables:
        return [
            "Existing related symbols in the target file/project.",
            "Current naming and return conventions.",
            "Call sites or consumers of the proposed result.",
            "Focused static/runtime validation path.",
        ]
    if deliverables == ["implementation_plan"]:
        return [
            "Live target assets, ownership, dependencies, and current graph topology.",
            "A clause-complete behavior/state/transition contract.",
            "Versioned technique evidence and callable operation availability.",
            "Positive, negative, boundary, regression, and rollback criteria.",
        ]
    if action_mode in {"mutate", "execute"}:
        return ["Resolved target", "pre-action state", "post-action result", "validation evidence"]
    return ["Evidence directly supporting the answer."]


def _desired_outcome(
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    action_mode: str,
) -> str:
    if deliverables == ["files"]:
        return f"The user knows which source files contain the primary implementation of '{subject}', and why."
    if "function_design" in deliverables:
        return f"The user has a justified design or implementation path for a helper that {subject}, without duplicating existing capability."
    if deliverables == ["implementation_plan"]:
        return f"The user receives an evidence-grounded, approval-ready implementation plan for '{subject}' and no project mutation occurs."
    if action_mode == "mutate":
        return (
            f"Success requires the requested change to '{subject}' to be implemented "
            "narrowly and to pass every required validation gate."
        )
    if action_mode == "execute":
        return (
            f"Success requires the resolved operation for '{subject}' to execute "
            "successfully and its resulting state to pass the required validation."
        )
    return f"The response directly resolves '{subject}'."


def _interpreted_problem(
    *,
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    action_mode: str,
    scope: str,
) -> str:
    if deliverables == ["files"]:
        return (
            f"Identify the implementation responsible for '{subject}', then resolve "
            f"and rank the source files that contain that implementation within {scope}."
        )
    if "function_design" in deliverables:
        return (
            f"Determine whether {scope} already contains a reusable capability for "
            f"'{subject}'; if not, design the smallest compatible helper and its validation."
        )
    if deliverables == ["implementation_plan"]:
        return f"Inspect and decompose '{subject}', then produce a complete approval-gated implementation and proof plan within {scope}."
    if action_mode == "mutate":
        return f"Resolve and safely modify the exact target for '{subject}', preserving unrelated behavior."
    if action_mode == "execute":
        return f"Resolve, preflight, execute, and verify the operation for '{subject}'."
    return f"Determine and deliver the evidence-backed answer for '{subject}'."


def _success_conditions(
    *,
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    action_mode: str,
    evidence: list[str],
) -> list[str]:
    if deliverables == ["files"]:
        return [
            "At least one source file is returned, or absence is explicitly established.",
            "Each returned file is justified by contained implementation symbols.",
            "The evidence explains why the symbol performs the requested behavior.",
            "Incidental word matches and narrow unrelated helpers are excluded.",
        ]
    if "function_design" in deliverables:
        return [
            "The system states whether equivalent functionality already exists.",
            "The proposed helper has a clear signature, behavior, placement, and return contract.",
            "The recommendation follows existing project conventions.",
            "A concrete validation path is defined before implementation.",
        ]
    if deliverables == ["implementation_plan"]:
        return [
            "Every explicit target and requested behavior clause appears in the plan.",
            "Architecture choices are tied to live project and versioned source evidence.",
            "Every action names a real callable or remains an explicit capability gap.",
            "Rollback and runtime proof scenarios are concrete and ordered.",
            "No project or DCC mutation occurs before approval.",
        ]
    if action_mode in {"mutate", "execute"}:
        return [
            "The target is uniquely resolved before action.",
            "Only the intended state is changed.",
            "Concrete validation confirms the requested outcome.",
            "Warnings and unverified assumptions are reported.",
        ]
    return ["The response delivers the requested artifact and directly satisfies the interpreted problem."]


def _failure_conditions(
    *,
    deliverables: list[str],
    relationships: list[str],
    action_mode: str,
) -> list[str]:
    failures = ["A handler returns output that does not satisfy the desired deliverable."]
    if deliverables == ["files"]:
        failures.extend([
            "The system returns files based only on token overlap.",
            "The result omits supporting implementation symbols.",
        ])
    if action_mode in {"mutate", "execute"}:
        failures.append("The system acts before target/context resolution or without validation.")
    return failures


def _meaning_graph(
    *,
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    knowns: list[str],
    unknowns: list[str],
    desired_outcome: str,
    scope: str,
) -> tuple[list[MeaningNode], list[MeaningEdge]]:
    nodes: list[MeaningNode] = [
        MeaningNode("user_outcome", "outcome", desired_outcome, desired_outcome, known=True, confidence=0.9),
        MeaningNode("subject", "subject", subject or "unresolved subject", subject, known=bool(subject), confidence=0.85 if subject else 0.3),
        MeaningNode("scope", "scope", scope or "unresolved scope", scope, known=bool(scope and not scope.startswith("conversation_reference")), confidence=0.8),
    ]
    edges: list[MeaningEdge] = []
    for index, deliverable in enumerate(deliverables):
        node_id = f"deliverable_{index+1}"
        nodes.append(MeaningNode(node_id, "deliverable", deliverable, deliverable, known=True, confidence=0.9))
        edges.append(MeaningEdge("user_outcome", "requires", node_id, reason="The requested output must be delivered."))
    for index, relation in enumerate(relationships):
        node_id = f"relationship_{index+1}"
        nodes.append(MeaningNode(node_id, "relationship", relation, relation, known=True, confidence=0.8))
        edges.append(MeaningEdge("subject", "participates_in", node_id, reason="Preserves grammatical/semantic relationship."))
    for index, unknown in enumerate(unknowns):
        node_id = f"unknown_{index+1}"
        nodes.append(MeaningNode(node_id, "unknown", unknown, unknown, known=False, confidence=0.7))
        edges.append(MeaningEdge(node_id, "must_be_resolved_before", "user_outcome", reason="Unknown affects answer adequacy."))
    return nodes, edges


def _candidate_plan(
    *,
    action_mode: str,
    deliverables: list[str],
    subject: str,
    relationships: list[str],
    prerequisites: list[str],
    evidence: list[str],
    unknowns: list[str],
    primary_route: str = "",
    host: str = "",
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(
        step_id: str,
        action: str,
        objective: str,
        depends_on: Iterable[str] = (),
        produces: Iterable[str] = (),
        success: str = "",
        *,
        capability: str = "",
        read_only: bool = True,
    ) -> None:
        steps.append({
            "step_id": step_id,
            "action": action,
            "objective": objective,
            "depends_on": list(depends_on),
            "produces": list(produces),
            "success_condition": success,
            "capability": capability,
            "read_only": read_only,
        })

    if primary_route == "dcc_query":
        host_label = host or "DCC"
        add(
            "understand_host_query",
            "analyze",
            f"Resolve the exact {host_label} state requested and its read-only result contract.",
            produces=["host_query_contract"],
            success="The host query, arguments, and expected result are unambiguous.",
            capability="semantic_reasoning",
        )
        add(
            "resolve_host_capability",
            "capability_gap",
            f"Determine the registered {host_label} capability that can answer the query.",
            ["understand_host_query"],
            ["host_query_capability"],
            "A deterministic read-only host capability is resolved or a concrete gap is reported.",
            capability="capability_resolution",
        )
        add(
            "query_host_state",
            "query",
            f"Query the requested live {host_label} state without mutation.",
            ["resolve_host_capability"],
            ["dcc_state_result"],
            "The host returns structured state for the requested query.",
            capability="dcc_query",
        )
        add(
            "report_host_state",
            "report",
            "Report the requested host state and any query limitations.",
            ["query_host_state"],
            ["final_answer"],
            "The response directly answers the host-state question.",
            capability="reporting",
        )
        return steps

    if deliverables == ["files"]:
        add("form_behavior", "analyze", f"Define what counts as implementing '{subject}'.", produces=["behavior_contract"], success="Complete behavior and exclusions are explicit.")
        add("find_implementations", "discover", "Find candidate symbols that satisfy the behavior contract.", ["form_behavior"], ["candidate_symbols"], "Candidate implementations are found or absence is established.")
        add("inspect_implementations", "inspect", "Inspect names, signatures, docstrings, bodies, and call relationships.", ["find_implementations"], ["symbol_evidence"], "Each candidate has positive and negative behavioral evidence.")
        add("resolve_files", "resolve", "Resolve containing source files for supported implementation symbols.", ["inspect_implementations"], ["candidate_files"], "Every supported symbol maps to an existing source file.")
        add("rank_files", "rank", "Rank complete implementations above incidental or narrow matches.", ["resolve_files"], ["ranked_files"], "Ranking is explainable from behavioral evidence.")
        add("report_files", "report", "Return file paths, supporting symbols, and rationale.", ["rank_files"], ["final_answer"], "The requested files and why are directly answered.")
        return steps

    if "function_design" in deliverables:
        add("resolve_target_file", "resolve", "Resolve the target file and conversation reference.", produces=["target_file"], success="One source file is resolved.")
        add("inventory_existing", "inspect", "Inventory existing related helpers, conventions, and call sites.", ["resolve_target_file"], ["existing_capabilities"], "Equivalent and adjacent capabilities are classified.")
        add("decide_gap", "analyze", "Decide whether a new helper is needed or an existing one should be reused/extended.", ["inventory_existing"], ["capability_gap_decision"], "The duplication question is answered with evidence.")
        add(
            "design_helper",
            "plan",
            (
                f"Define signature, input validation, host API requirements, type filtering, "
                f"namespace/long-path behavior, matching rules, stable ordering, duplicate "
                f"handling, return shape, placement, and non-mutating behavior for a helper "
                f"that {subject}."
            ),
            ["decide_gap"],
            ["helper_design"],
            "The design is robust, implementable, convention-compatible, and explicit about edge cases.",
        )
        add("define_validation", "validate", "Define focused static and host-runtime validation.", ["design_helper"], ["validation_plan"], "Success and regression checks are concrete.")
        add("report_or_implement", "report", "Return the design or hand it to the mutation planner if implementation was explicitly requested.", ["define_validation"], ["final_answer"], "The user receives the requested design/implementation path.")
        return steps

    if deliverables == ["implementation_plan"]:
        add("resolve_targets", "resolve", "Resolve explicit Unreal assets, runtime owners, and touched boundaries.", produces=["resolved_targets"], success="Every named target is uniquely resolved.")
        add("inspect_live_state", "inspect", "Inspect live graph, input, animation, asset, and runtime evidence.", ["resolve_targets"], ["live_evidence"], "The current failure and reusable project patterns are evidenced.")
        add("decompose_behavior", "analyze", "Preserve all requested stimuli, observations, guards, states, transitions, effects, and failure paths.", ["inspect_live_state"], ["behavior_contract"], "Every behavior clause is represented without selecting a canned mechanic.")
        add("compare_techniques", "discover", "Compare current applicable techniques and verify callable operations.", ["decompose_behavior"], ["technique_evidence", "capability_matrix"], "Choices are source-grounded and missing operations remain explicit.")
        add("synthesize_plan", "plan", "Produce exact staged actions, asset impacts, rollback, and acceptance criteria.", ["compare_techniques"], ["approval_plan"], "The plan is detailed, executable, and mutation remains gated.")
        add("define_runtime_proof", "validate", "Define positive, negative, boundary, regression, visual, and log proof scenarios.", ["synthesize_plan"], ["proof_contract"], "Completion cannot be claimed from compilation or asset existence alone.")
        add("report_plan", "report", "Present the approval-ready plan and unresolved choices.", ["define_runtime_proof"], ["final_answer"], "The user can approve, revise, add, or remove plan stages before mutation.")
        return steps

    if action_mode == "mutate":
        add("resolve_target", "resolve", "Resolve exact target and boundaries.", produces=["resolved_target"], success="Mutation target is unique.")
        add("inspect_context", "inspect", "Inspect current implementation, dependencies, and reusable patterns.", ["resolve_target"], ["target_context"], "Enough evidence exists for a safe change.")
        add("design_change", "plan", "Design the smallest behavior-preserving change.", ["inspect_context"], ["change_plan"], "Exact edits and rollback are defined.")
        add("apply_change", "modify", "Apply the scoped change.", ["design_change"], ["changed_state"], "Only intended targets changed.", read_only=False)
        add("validate", "validate", "Run focused validation and inspect resulting behavior.", ["apply_change"], ["validation_result"], "Validation proves success or identifies repair.")
        add("report", "report", "Report changes, evidence, warnings, and remaining risks.", ["validate"], ["final_answer"], "Accountable verified outcome is delivered.")
        return steps

    if action_mode == "execute":
        add("resolve_callable", "resolve", "Resolve callable, host, inputs, and target.", produces=["execution_contract"], success="Operation is unambiguous.")
        add("preflight", "preflight", "Check host connection, safety, and observable success.", ["resolve_callable"], ["preflight_result"], "Execution is safe and measurable.")
        add("execute", "execute", "Execute through the deterministic bridge.", ["preflight"], ["execution_result"], "Structured result is returned.", read_only=False)
        add("validate", "validate", "Verify resulting host/project state.", ["execute"], ["validation_result"], "State satisfies objective.")
        add("report", "report", "Report operation, outcome, and warnings.", ["validate"], ["final_answer"], "Verified result is delivered.")
        return steps

    add("understand", "analyze", "Resolve deliverable, subject, relationships, and success.", produces=["formulated_problem"], success="Problem formulation is adequate.")
    add("gather_evidence", "discover", "Gather evidence required by the formulated problem.", ["understand"], ["evidence"], "Evidence is sufficient.")
    add("report", "report", "Produce the requested deliverable.", ["gather_evidence"], ["final_answer"], "Desired outcome is satisfied.")
    return steps


def _deterministic_critique(formulation: ProblemFormulation) -> list[str]:
    issues: list[str] = []
    if formulation.deliverables == ["files"] and not any("contain" in item for item in formulation.relationships):
        issues.append("The formulation lost the file-to-implementation containment relationship.")
    if formulation.action_mode == "read_only" and any(step.get("action") in {"modify", "execute"} for step in formulation.candidate_plan):
        issues.append("The plan proposes action for a read-only request.")
    if formulation.action_mode in {"mutate", "execute"} and formulation.candidate_plan:
        first = formulation.candidate_plan[0].get("action")
        if first not in {"resolve", "inspect", "analyze", "discover", "preflight"}:
            issues.append("The plan acts before resolving what must be true.")
    if formulation.subject.lower() in {"rig", "code", "file", "function"}:
        issues.append("The subject may be too broad; preserve the full requested behavior.")
    return issues


def _revise_formulation(formulation: ProblemFormulation) -> ProblemFormulation:
    revisions: list[str] = []
    if formulation.deliverables == ["files"] and not any("contain" in item for item in formulation.relationships):
        formulation.relationships.insert(0, "files contain implementations")
        revisions.append("Restored containment relationship for file deliverable.")
    if formulation.action_mode == "read_only":
        before = len(formulation.candidate_plan)
        formulation.candidate_plan = [
            step for step in formulation.candidate_plan
            if step.get("action") not in {"modify", "execute"}
        ]
        if len(formulation.candidate_plan) != before:
            revisions.append("Removed premature mutation/execution from read-only plan.")
    formulation.revisions = _uniq([*formulation.revisions, *revisions])
    return formulation


def _merge_model_formulation(base: ProblemFormulation, proposed: dict[str, Any]) -> ProblemFormulation:
    allowed_lists = {
        "deliverables", "relationships", "knowns", "unknowns", "blocking_unknowns",
        "assumptions", "constraints", "exclusions", "prerequisites",
        "evidence_required", "success_conditions", "failure_conditions",
        "candidate_plan", "critique", "revisions",
    }
    allowed_scalars = {
        "literal_request", "interpreted_problem", "desired_outcome", "subject",
        "action_mode", "scope",
    }
    for key in allowed_scalars:
        value = proposed.get(key)
        if isinstance(value, str) and value.strip():
            setattr(base, key, value.strip())
    for key in allowed_lists:
        value = proposed.get(key)
        if isinstance(value, list) and value:
            if key == "candidate_plan":
                cleaned = [dict(item) for item in value if isinstance(item, dict)]
            else:
                cleaned = _strings(value)
            if cleaned:
                setattr(base, key, cleaned)
    return base


def _clarification_questions(formulation: ProblemFormulation) -> list[str]:
    questions: list[str] = []
    for item in formulation.blocking_unknowns:
        if "conversation file reference" in item.lower():
            questions.append("Which previously discussed file does 'that/this file' refer to?")
        elif "mutation/execution target" in item.lower():
            questions.append("Which exact file, symbol, asset, or scene object should be changed or executed?")
        else:
            questions.append(f"Please clarify: {item}")
    return _uniq(questions)


def _confidence(formulation: ProblemFormulation) -> float:
    score = 0.45
    if formulation.interpreted_problem:
        score += 0.1
    if formulation.deliverables and formulation.deliverables != ["answer"]:
        score += 0.1
    if formulation.subject:
        score += 0.08
    if formulation.relationships:
        score += 0.08
    if formulation.success_conditions:
        score += 0.08
    if formulation.candidate_plan:
        score += 0.08
    score -= 0.12 * len(formulation.blocking_unknowns)
    score -= 0.04 * min(3, len(formulation.critique))
    if formulation.adequate:
        score += 0.08
    return round(max(0.05, min(0.99, score)), 3)


def _assumptions(prompt: str, facts: dict[str, Any], action_mode: str, scope: str) -> list[str]:
    values: list[str] = []
    if action_mode == "read_only" and facts.get("host"):
        values.append("The named DCC host is domain context; a live host is not required unless scene state is explicitly requested.")
    if scope == "project":
        values.append("Search is limited to the active indexed project.")
    if facts.get("source_language"):
        values.append("References to files/functions/code indicate source-code evidence rather than scene execution.")
    return _uniq(values)


def _recent_target(facts: dict[str, Any], kind: str) -> str:
    entities = dict(facts.get("conversation_entities") or {})
    primary = entities.get(f"primary_{kind}")
    if isinstance(primary, str) and primary.strip():
        return primary
    for item in facts.get("recent_targets") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") == kind and str(item.get("value") or "").strip():
            return str(item["value"])
    active = str(facts.get("active_file") or "")
    if kind == "file" and active:
        return active
    return ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _safe_callback(callback: SemanticCallback, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = callback(payload)
        return dict(result or {}) if isinstance(result, dict) else {}
    except Exception:
        return {}


def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_file": context.get("active_file", ""),
        "open_files": list(context.get("open_files") or [])[:12],
        "host": context.get("host", ""),
        "conversation_entities": dict(context.get("conversation_entities") or {}),
        "context_momentum": dict(context.get("context_momentum") or {}),
    }


def _strings(values: Iterable[Any]) -> list[str]:
    return [str(value).strip() for value in values if str(value or "").strip()]


def _uniq(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
