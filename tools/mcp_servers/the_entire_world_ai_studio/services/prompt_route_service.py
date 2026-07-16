"""Deterministic prompt route classification for chat requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


ENGINE_PROVIDERS = {"action_graph", "connection_status", "project_health", "target_discovery", "project_search"}

HOST_ALIASES = {
    "maya": ("maya",),
    "unreal": ("unreal", "ue5", "ue4"),
    "blender": ("blender",),
    "substance_painter": ("substance painter", "substance", "painter"),
    "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
    "unity": ("unity",),
    "houdini": ("houdini", "hou", "hip"),
}


@dataclass
class PromptRouteDecision:
    route: str
    confidence: float
    provider: str
    intent_category: str = ""
    host: str = ""
    execution_route: str = ""
    handler_id: str = ""
    operation_mode: str = ""
    target_type: str = ""
    target_identifier: str = ""
    callable_name: str = ""
    positional_args: list[Any] = field(default_factory=list)
    keyword_args: dict[str, Any] = field(default_factory=dict)
    execution_environment: str = ""
    mutation_scope: str = ""
    analysis_depth: str = ""
    context_resolvers: list[str] = field(default_factory=list)
    deterministic_steps: list[str] = field(default_factory=list)
    search_scopes: list[str] = field(default_factory=list)
    index_filters: dict[str, Any] = field(default_factory=dict)
    model_capability: str = ""
    risk_level: str = ""
    requires_fresh_index: bool = False
    requires_dcc_connection: bool = False
    requires_plan: bool = False
    can_execute_directly: bool = False
    compound_kind: str = "atomic"
    operations: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    required_context: list[str] = field(default_factory=list)
    model_tier: str = "local_fast"
    missing_info: list[str] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    rejected_routes: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    route_candidates: list[dict[str, Any]] = field(default_factory=list)
    selected_route_reason: str = ""
    senior_prompt_analysis: dict[str, Any] = field(default_factory=dict)
    reasoning_pipeline: dict[str, Any] = field(default_factory=dict)
    visible_progress: dict[str, Any] = field(default_factory=dict)
    domain_experts: list[dict[str, Any]] = field(default_factory=list)
    capability_gap_plan: dict[str, Any] = field(default_factory=dict)
    request_understanding: dict[str, Any] = field(default_factory=dict)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)
    primary_goal: str = ""
    goal_type: str = ""
    estimated_steps: int = 0
    requires_generation: bool = False
    requires_project_search: bool = False
    requires_validation: bool = False
    requires_execution: bool = False
    # Capability Acquisition & Gap Analysis
    capability_plan_id: str = ""
    capability_gaps: list[str] = field(default_factory=list)


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _word_in(text: str, value: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text))


def _detect_host(text: str) -> str:
    lower = (text or "").lower()
    for host, aliases in HOST_ALIASES.items():
        if any(_word_in(lower, alias) for alias in aliases):
            return host
    return ""


def _detect_hosts(text: str) -> list[str]:
    lower = (text or "").lower()
    hosts = []
    for host, aliases in HOST_ALIASES.items():
        if any(_word_in(lower, alias) for alias in aliases):
            hosts.append(host)
    return hosts


def _has_file_ref(text: str) -> bool:
    return bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", text or ""))


def _callable_after_execution_verb(text: str) -> str:
    match = re.search(r"\b(?:run|execute|call|launch|test)\s+([A-Za-z_][A-Za-z0-9_]*)\b", text or "", re.IGNORECASE)
    if match and match.group(1).lower() not in {"the", "a", "an", "this", "that"}:
        return match.group(1)
    match = re.search(r"\b(unreal_tools(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b", text or "")
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*)\b", text or "")
    return match.group(1) if match else ""


def _explicit_source_file_references(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui)\b", text or "", re.IGNORECASE)


def _is_explicit_source_code_mutation(text: str, lower: str) -> bool:
    """Hard precedence guard: an explicitly named source file plus code mutation is a project edit.

    Live execution verbs intentionally disqualify this guard so prompts such as
    `run create_rig_from_mapping in Maya` still reach DCC execution.
    """
    source_files = _explicit_source_file_references(text)
    if not source_files:
        return False
    if re.search(r"\b(run|execute|call|launch|perform)\b", lower or ""):
        return False
    mutation = re.search(
        r"\b(add|edit|modify|change|update|refactor|improve|fix|patch|implement|write|insert|rename|remove|delete|document|wire)\b",
        lower or "",
    )
    code_object = re.search(
        r"\b(code|helper|function|method|class|module|docstring|variable|handler|ui|button|test|tests|import|logic|line|symbol|name)\b",
        lower or "",
    )
    # An explicit source filename already supplies the code target. Commands such
    # as "rename _get_joint in create_rig.py" should not require the user to also
    # say function/symbol.
    return bool(mutation and (code_object or source_files))


def _route_candidate_diagnostics(text: str, lower: str, *, host: str, hosts: list[str]) -> list[dict[str, Any]]:
    """Cheap explainable route scores used for diagnostics and future ranker migration."""
    candidates = {
        "target_discovery": {"score": 0.0, "reasons": []},
        "dcc_execute": {"score": 0.0, "reasons": []},
        "pipeline_graph": {"score": 0.0, "reasons": []},
        "project_search": {"score": 0.0, "reasons": []},
        "chat": {"score": 0.1, "reasons": ["fallback route"]},
    }
    if _is_explicit_source_code_mutation(text, lower):
        candidates["target_discovery"]["score"] += 1.0
        candidates["target_discovery"]["reasons"].append("explicit source file plus code mutation")
    if _explicit_source_file_references(text):
        candidates["target_discovery"]["score"] += 0.45
        candidates["project_search"]["score"] += 0.25
    if host and re.search(r"\b(run|execute|call|launch|select|move|rotate|scale|create|delete|set)\b", lower):
        candidates["dcc_execute"]["score"] += 0.72
        candidates["dcc_execute"]["reasons"].append(f"host operation language for {host}")
    if len(hosts) >= 2 or re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|compose|sequence)\b", lower):
        candidates["pipeline_graph"]["score"] += 0.8
        candidates["pipeline_graph"]["reasons"].append("explicit workflow or pipeline language")
    if _looks_like_read_only_project_question(lower):
        candidates["project_search"]["score"] += 0.7
        candidates["project_search"]["reasons"].append("read-only project fact language")
    return [
        {"route": route, "score": round(float(data["score"]), 3), "reasons": list(data["reasons"])}
        for route, data in sorted(candidates.items(), key=lambda item: item[1]["score"], reverse=True)
    ]


def _looks_like_read_only_project_question(lower: str) -> bool:
    if not re.search(
        r"\b(what|which|where|list|show|find|file|path|how many|arguments|args|required|dependencies|classes|functions|methods)\b",
        lower or "",
    ):
        return False
    if re.search(r"\b(run|execute|call|launch|do it|perform|apply|modify scene|in the scene)\b", lower or ""):
        return False
    if re.search(r"\b(add|create|write|generate|implement|insert|modify|update|fix|patch|wire|connect|build)\b", lower or "") and not re.search(
        r"\b(what|which|where|list|show|find|how many|arguments|args|required|dependencies|classes|functions|methods)\b",
        lower or "",
    ):
        return False
    return bool(
        re.search(r"\b(file|files|path|python|py|function|functions|method|methods|class|classes|symbol|symbols|project|code|script|tool|tools|argument|arguments|args|caller|callers|callee|callees)\b", lower or "")
        or re.search(r"\b(can|could|would)\s+i\s+(?:use\s+)?(?:create|make|build)\b", lower or "")
    )


def _is_connection_status_question(lower: str) -> bool:
    text = lower or ""
    if re.search(r"\b(connect|connection|connected|status|health)\b", text) is None:
        return False
    if re.search(r"\b(testing connection|test connection|connection status|am i connected|are we connected|what am i connected to|what is connected)\b", text):
        return True
    if re.fullmatch(r"\s*(?:am i )?connected\s*\??\s*", text):
        return True
    if re.fullmatch(r"\s*(?:status|health)\s*\??\s*", text):
        return True
    return False


def _is_simple_project_fact_question(lower: str) -> bool:
    """Small deterministic lookups should not trigger expert planning scaffolds."""
    text = lower or ""
    if not re.search(
        r"\b(what|which|where|list|show|find|how many|arguments?|args?|required|functions?|methods?|classes?|symbols?|callers?|usages?|references?)\b",
        text,
    ):
        return False
    if re.search(
        r"\b(add|write|implement|insert|modify|update|fix|patch|wire|connect|refactor|delete|remove|execute|run|apply)\b",
        text,
    ):
        return False
    if re.search(r"\b(create|build|generate|make)\b", text) and not re.search(
        r"\b(what|which|where|list|show|find)\b.*\b(functions?|methods?|classes?|symbols?|files?|paths?)\b",
        text,
    ):
        return False
    return bool(
        re.search(r"\b(functions?|methods?|classes?|symbols?|files?|path|arguments?|args?|required|callers?|callees|usages?|references?|imports?|dependencies)\b", text)
        or re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", text)
    )


def _has_explicit_dcc_mutation(lower: str) -> bool:
    return bool(re.search(
        r"\b(move|translate|rotate|scale|select|frame|create|make|build|spawn|delete|remove|set|modify|change|connect|disconnect|assign|bind|skin|constrain|parent\s+constrain|orient\s+constrain|point\s+constrain)\b",
        lower or "",
    ))


def _simple_project_fact_progress() -> dict[str, Any]:
    return {
        "framework": "visible_prompt_progress_v1",
        "enabled": True,
        "progress_mode": "terse",
        "stages": [
            {
                "index": 1,
                "total": 2,
                "state": "working",
                "label": "Searching project facts",
                "message": "Checking the active file and local index.",
                "stop_when": "A direct symbol or file answer is available.",
            },
            {
                "index": 2,
                "total": 2,
                "state": "done",
                "label": "Answer ready",
                "message": "Returning the direct project answer.",
                "stop_when": "Answer is rendered in chat.",
            },
        ],
    }


def _is_unreal_live_query(lower: str) -> bool:
    if "unreal" not in lower and "ue5" not in lower and "ue4" not in lower and "unreal_tools" not in lower:
        return False
    if re.search(r"\b(create|make|build|spawn|duplicate|delete|remove|set|modify|change|compile|save|write)\b", lower):
        return False
    query_words = re.search(r"\b(what|which|show|list|get|inspect|scan|find|current|loaded|active|selected|where)\b", lower)
    unreal_terms = re.search(
        r"\b(selection|selected|actor|actors|asset|assets|level|world|blueprint|blueprints|skeleton|skeletons|mesh|meshes|static mesh|"
        r"animation|animations|plugin|plugins|component|components|project|snapshot|reference|references|dependency|dependencies|"
        r"control rig|anim blueprint|niagara|physics|material|materials)\b",
        lower,
    )
    return bool(query_words and unreal_terms)


def _known_unreal_operation_from_text(text: str) -> dict[str, Any]:
    lower = (text or "").lower()
    try:
        from services.unreal.unreal_operation_service import (
            UNREAL_OPERATIONS,
            extract_unreal_asset_name,
            extract_unreal_package_like_path,
            unreal_navigation_operation_from_text,
            unreal_prompt_to_operation,
        )
    except Exception:
        UNREAL_OPERATIONS = {}
        extract_unreal_asset_name = None
        extract_unreal_package_like_path = None
        unreal_navigation_operation_from_text = None
        unreal_prompt_to_operation = None
    navigation_context = bool(
        re.search(r"\b(unreal|ue5|ue4|blueprint|anim blueprint|control rig|asset|assets)\b", lower)
        or re.search(r"/game/", lower)
        or re.search(r"\b(?:bp|abp|sk|sm|mi|m|cr|pa|ne)_[A-Za-z0-9_]+\b", text or "")
    )
    if navigation_context and callable(unreal_navigation_operation_from_text):
        navigation_key, navigation_params = unreal_navigation_operation_from_text(text)
        if navigation_key and navigation_key in UNREAL_OPERATIONS:
            op = UNREAL_OPERATIONS[navigation_key]
            return {
                "operation_key": navigation_key,
                "function": str(getattr(op, "function", "") or ""),
                "mutates_project": bool(getattr(op, "mutates_project", False)),
                "required": [
                    name for name in list(getattr(op, "required", ()) or ())
                    if not dict(navigation_params or {}).get(name)
                ],
                "keyword_args": dict(navigation_params or {}),
            }
    inspect_blueprint_context = bool(
        re.search(r"\b(inspect|scan|list|show|get)\b", lower)
        and re.search(r"\b(blueprint|graphs?|variables?|components?|bp_[A-Za-z0-9_]+)\b", lower)
    )
    inferred_key = unreal_prompt_to_operation(text) if callable(unreal_prompt_to_operation) else ""
    if inspect_blueprint_context and "blueprint.scan" in UNREAL_OPERATIONS:
        inferred_key = "blueprint.scan"
    if inferred_key and inferred_key in UNREAL_OPERATIONS:
        op = UNREAL_OPERATIONS[inferred_key]
        keyword_args: dict[str, Any] = {}
        if inferred_key in {"assets.inspect", "blueprint.scan", "navigation.open_asset"}:
            asset_ref = ""
            if callable(extract_unreal_package_like_path):
                asset_ref = str(extract_unreal_package_like_path(text) or "")
            if not asset_ref and callable(extract_unreal_asset_name):
                asset_ref = str(extract_unreal_asset_name(text) or "")
            if asset_ref:
                keyword_args["asset_path"] = asset_ref
        return {
            "operation_key": inferred_key,
            "function": str(getattr(op, "function", "") or ""),
            "mutates_project": bool(getattr(op, "mutates_project", False)),
            "required": [
                name for name in list(getattr(op, "required", ()) or ())
                if not keyword_args.get(name)
            ],
            "keyword_args": keyword_args,
        }
    for key, op in UNREAL_OPERATIONS.items():
        function = str(getattr(op, "function", "") or "")
        label = str(getattr(op, "label", "") or "")
        if key.lower() in lower or (function and function.lower() in lower) or (label and label.lower() in lower):
            return {
                "operation_key": key,
                "function": function,
                "mutates_project": bool(getattr(op, "mutates_project", False)),
                "required": list(getattr(op, "required", ()) or ()),
                "keyword_args": {},
            }
    callable_name = _callable_after_execution_verb(text)
    if callable_name.startswith("unreal_tools."):
        return {
            "operation_key": "",
            "function": callable_name,
            "mutates_project": bool(re.search(r"\b(create|spawn|duplicate|delete|remove|set|modify|compile|save)\b", lower)),
            "required": [],
            "keyword_args": {},
        }
    return {}


def _has_no_execute_guard(lower: str) -> bool:
    return bool(
        re.search(
            r"\b(do not|don't|dont|never)\s+(run|execute|call|launch|apply|change|modify|edit|write|save)\b",
            lower,
        )
        or re.search(r"\b(just|only)\s+(show|explain|preview|plan)\b", lower)
    )


def _detect_compound_kind(lower: str) -> str:
    if re.search(r"\b(first|then|and then|before|after)\b", lower):
        if re.search(r"\b(find|check|analyze|inspect|diagnose|review)\b", lower) and re.search(r"\b(fix|fixing|change|edit|update|clean up|cleanup|refactor)\b", lower):
            return "analysis_then_mutation"
        return "sequence"
    if re.search(r"\b(and|plus)\b", lower) and re.search(r"\b(open|find|run|execute|edit|fix|create|connect|validate)\b", lower):
        return "sequence"
    return "atomic"


def _compound_operations(lower: str, route: str, mode: str) -> list[dict[str, Any]]:
    kind = _detect_compound_kind(lower)
    if kind == "analysis_then_mutation":
        return [
            {"route": "project_search", "operation_mode": "analyze", "requires_confirmation": False},
            {"route": route, "operation_mode": mode or "edit", "requires_confirmation": True},
        ]
    if kind == "sequence":
        return [{"route": route, "operation_mode": mode or "plan", "requires_confirmation": False}]
    return []


def _is_generated_maya_rig_control_post_action(host: str, operation_key: str, text: str, params: dict[str, Any]) -> bool:
    if host != "maya" or operation_key not in {"scene.move", "scene.select", "navigation.frame_selection"}:
        return False
    lower = (text or "").lower()
    objects = [str(obj) for obj in params.get("objects") or []]
    if not objects:
        direct = re.search(r"\b([A-Za-z_][A-Za-z0-9_:|.-]*(?:_ctrl|Ctrl|CTRL))\b", text or "")
        if direct:
            objects = [direct.group(1)]
    generated_control_targets = [
        obj for obj in objects
        if obj.lower().endswith("_ctrl") or obj.lower() in {"pelvis_ctrl", "hip_ctrl", "root_ctrl"}
    ]
    if not generated_control_targets:
        return False
    if re.search(r"\b(select only|just select|only select)\b", lower):
        return False
    return True


def _is_unreal_graph_operation_planning_request(lower: str) -> bool:
    text = lower or ""
    if "unreal" not in text and not re.search(r"\b(?:bp|abp|bpc|niagara|control rig|metasound|pcg)\b", text):
        return False
    if not re.search(r"\b(graph|event\s*graph|eventgraph|anim\s*graph|animgraph|blueprint|node|nodes|pin|pins|operation|operations)\b", text):
        return False
    if not re.search(r"\b(report|show|list|what|which|available|possible|plan|preview|inspect|explain)\b", text):
        return False
    return bool(re.search(r"\b(add|adding|insert|connect|rewire|modify|edit|create|print string|reroute)\b", text))


def _maya_rigging_prerequisite_decision(
    *,
    host: str,
    operation_key: str,
    op_function: str,
    text: str,
    params: dict[str, Any],
    no_execute: bool,
) -> PromptRouteDecision | None:
    if not _is_generated_maya_rig_control_post_action(host, operation_key, text, params):
        return None
    objects = list(params.get("objects") or [])
    target_control = str(objects[0]) if objects else "requested control"
    return PromptRouteDecision(
        route="action_graph",
        confidence=0.93,
        provider="action_graph",
        intent_category="maya_rigging_prerequisite_plan",
        host="maya",
        callable_name=op_function,
        target_identifier=operation_key,
        keyword_args=dict(params),
        operation_mode="approve_prerequisites_then_execute",
        target_type="maya_rig_control",
        execution_environment="maya_scene",
        mutation_scope="dcc_scene_mutation",
        analysis_depth="prerequisite_graph",
        required_context=[
            "dcc_connection",
            "maya_scene_context",
            "skeleton_exists",
            "root_joint_origin",
            "hik_mapping_state",
            "rig_build_state",
            "target_control_exists",
        ],
        deterministic_steps=[
            "check_maya_connection",
            "verify_target_control_exists",
            "verify_skeleton_root_origin",
            "check_hik_mapping_from_origin",
            "check_rig_or_control_rig_exists",
            "verify_target_control_after_prerequisites",
            "execute_requested_control_action",
        ],
        compound_kind="prerequisite_chain",
        requires_plan=True,
        requires_confirmation=not no_execute,
        can_execute_directly=False,
        model_tier="none_deterministic",
        operations=[
            {
                "id": "verify_target_control",
                "label": f"Check whether {target_control} already exists",
                "operation": "scene.object_exists",
                "host": "maya",
                "args": {"name": target_control},
                "requires_confirmation": False,
                "produces": ["target_control_exists", "target_control_missing"],
            },
            {
                "id": "requested_post_requisite_action",
                "label": f"Run requested action on existing {target_control}",
                "operation": operation_key,
                "host": "maya",
                "args": dict(params),
                "requires_confirmation": True,
                "condition": "target_control_exists",
                "requires": ["target_control_exists"],
            },
            {
                "id": "verify_skeleton_origin",
                "label": "Verify skeleton root joint",
                "operation": "scene.find_joint",
                "host": "maya",
                "args": {"name": "origin"},
                "requires_confirmation": False,
                "condition": "target_control_missing",
                "produces": ["skeleton_exists", "root_joint_origin"],
            },
            {
                "id": "create_hik_mapping_if_missing",
                "label": "Create HIK mapping from origin if missing",
                "operation": "python.call",
                "host": "maya",
                "callable": "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
                "args": {"root_joint": "origin"},
                "requires_confirmation": True,
                "condition": "skeleton_exists and hik_mapping_missing",
                "produces": ["body_joint_map", "face_joint_map"],
                "evidence": [
                    "maya_tools/Rigging/mocap/setup_hik.py:create_rig_mapping(root_joint=None) returns (body_joint_map, face_joint_map)",
                ],
            },
            {
                "id": "create_rig_if_missing",
                "label": "Create rig/control rig if missing",
                "operation": "python.call",
                "host": "maya",
                "callable": "maya_tools.Rigging.create_rig.create_rig_from_mapping",
                "args": {"body_joint_map": "$body_joint_map", "face_joint_map": "$face_joint_map"},
                "requires_confirmation": True,
                "condition": "skeleton_exists and target_control_missing",
                "requires": ["body_joint_map", "face_joint_map"],
                "produces": ["rig_build_state", "generated_controls"],
                "execution_notes": [
                    "Run through Maya commandPort/Python so mobile/remote execution does not depend on blocking UI popups.",
                    "After this callable returns, verify the requested control exists before running the post-requisite action.",
                ],
                "evidence": [
                    "maya_tools/Rigging/create_rig.py:create_rig_from_mapping(body_joint_map, face_joint_map)",
                ],
            },
            {
                "id": "verify_target_control_after_prerequisites",
                "label": f"Verify {target_control} exists after prerequisite setup",
                "operation": "scene.object_exists",
                "host": "maya",
                "args": {"name": target_control},
                "requires_confirmation": False,
                "requires": ["rig_build_state"],
            },
            {
                "id": "requested_post_requisite_action_after_prerequisites",
                "label": f"Run requested action on generated {target_control}",
                "operation": operation_key,
                "host": "maya",
                "args": dict(params),
                "requires_confirmation": True,
                "condition": "target_control_missing and target_control_exists_after_prerequisites",
                "requires": ["target_control_exists_after_prerequisites"],
            },
        ],
        missing_info=["approval_to_create_hik_mapping_and_rig_if_missing"],
        reasons=[
            "Prompt targets a likely generated Maya rig control, so the requested action depends on skeleton/HIK/rig prerequisites.",
            "If the skeleton exists but the rig/control does not, prerequisite automation must be approved before the final post-requisite action.",
        ],
        rejected_routes=["dcc_execute", "project_search"],
    )



def decision_requires_live_dcc(decision: PromptRouteDecision | dict[str, Any] | None) -> bool:
    """Return True only when the current request genuinely needs a live DCC.

    A DCC host hint narrows project search and expert context. It does not by
    itself justify launching a DCC/MCPHost session.
    """
    if decision is None:
        return False
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})

    if not bool(data.get("requires_dcc_connection")):
        return False

    operation_mode = str(data.get("operation_mode") or "").lower()
    route = str(data.get("route") or "").lower()
    execution_route = str(data.get("execution_route") or "").lower()

    if operation_mode in {"execute", "prototype", "navigate", "query"}:
        return route in {"dcc_execute", "dcc_prototype", "dcc_query", "unreal_capability"}

    return execution_route in {
        "dcc.execution_pipeline",
        "dcc.prototype_pipeline",
        "dcc.scene_query",
        "unreal.capability_pipeline",
    }


def decision_is_project_only(decision: PromptRouteDecision | dict[str, Any] | None) -> bool:
    """Return True when all current goals can be satisfied without a live host."""
    if decision is None:
        return False
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    if bool(data.get("requires_execution")):
        return False

    route = str(data.get("route") or "").lower()
    provider = str(data.get("provider") or "").lower()
    goal_type = str(data.get("goal_type") or "").lower()
    mutation_scope = str(data.get("mutation_scope") or "").lower()
    graph = dict(data.get("task_graph") or data.get("goal_graph") or {})
    goals = list(graph.get("goals") or graph.get("tasks") or [])

    project_routes = {
        "project_search",
        "quality_audit",
        "project_health",
        "target_discovery",
        "chat",
    }
    project_providers = {
        "project_search",
        "project_health",
        "target_discovery",
        "llm",
    }
    non_live_actions = {
        "search",
        "inspect",
        "design",
        "generate",
        "report",
        "validate",
        "approval",
        "respond",
    }

    if goals:
        actions = {
            str(goal.get("action") or "").lower()
            for goal in goals
            if isinstance(goal, dict)
        }
        if actions and actions.issubset(non_live_actions):
            return True

    if route in project_routes or provider in project_providers:
        return mutation_scope != "dcc_scene_mutation"

    return goal_type in {"locate", "learn", "explain", "compare", "generate", "respond", "plan"}

def _finalize_decision(decision: PromptRouteDecision, lower: str) -> PromptRouteDecision:
    if not decision.route_candidates:
        decision.route_candidates = []
    if not decision.selected_route_reason and decision.reasons:
        decision.selected_route_reason = str(decision.reasons[0])
    route_defaults: dict[str, dict[str, Any]] = {
        "project_health": {
            "execution_route": "engine.project_health",
            "handler_id": "ProjectHealthProvider",
            "operation_mode": "analyze",
            "target_type": "project",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "graph",
            "context_resolvers": ["dependency_graph", "call_graph", "symbol_index"],
            "deterministic_steps": ["load_project_index", "query_dependency_graph", "format_health_result"],
            "model_capability": "none",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "quality_audit": {
            "execution_route": "engine.project_search",
            "handler_id": "ProjectSearchProvider",
            "operation_mode": "audit",
            "target_type": "code",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "semantic",
            "context_resolvers": ["symbol_index", "call_graph", "code_chunks"],
            "deterministic_steps": ["gather_indexed_evidence", "rank_relevant_symbols", "summarize_evidence"],
            "model_capability": "local_code",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "target_discovery": {
            "execution_route": "engine.target_discovery",
            "handler_id": "TargetDiscoveryEditProvider",
            "operation_mode": "edit",
            "target_type": "code",
            "execution_environment": "project_source",
            "mutation_scope": "file_modification",
            "analysis_depth": "semantic",
            "context_resolvers": ["target_discovery", "symbol_index", "code_chunks"],
            "deterministic_steps": ["discover_targets", "rank_candidates", "build_grounded_edit_prompt"],
            "model_capability": "local_code",
            "risk_level": "medium",
            "requires_plan": True,
            "requires_fresh_index": True,
        },
        "pipeline_graph": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "compose_pipeline",
            "target_type": "pipeline_graph",
            "execution_environment": "ui_pipeline_graph",
            "mutation_scope": "local_reversible_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["project_index", "symbol_index", "workflow_graph"],
            "deterministic_steps": ["resolve_symbols", "create_nodes", "bind_literals", "connect_data", "connect_flow", "validate_graph"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
            "can_execute_directly": True,
        },
        "action_graph": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "plan_actions",
            "target_type": "action_graph",
            "execution_environment": "ai_studio",
            "mutation_scope": "local_reversible_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["project_index", "symbol_index"],
            "deterministic_steps": ["compile_action_graph", "validate_actions"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
            "can_execute_directly": True,
        },
        "project_search": {
            "execution_route": "engine.project_search",
            "handler_id": "ProjectSearchProvider",
            "operation_mode": "search",
            "target_type": "project",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "index",
            "context_resolvers": ["project_index", "symbol_index"],
            "deterministic_steps": ["query_project_index", "answer_from_indexed_facts"],
            "model_capability": "none_or_local_fast",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "connection_status": {
            "execution_route": "engine.connection_status",
            "handler_id": "ConnectionStatusProvider",
            "operation_mode": "status",
            "target_type": "connected_applications",
            "execution_environment": "ui_context",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": ["cached_status_cards", "connected_account_settings"],
            "deterministic_steps": ["read_cached_connection_status", "format_status_result"],
            "model_capability": "none",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "dcc_execute": {
            "execution_route": "dcc.execution_pipeline",
            "handler_id": "CommandRouter.execute_dcc_editor_operation",
            "operation_mode": "execute",
            "target_type": "dcc_callable",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["dcc_connection", "resolved_callable", "argument_validation"],
            "deterministic_steps": ["resolve_callable", "validate_arguments", "confirm_execution", "execute_dcc"],
            "model_capability": "none",
            "risk_level": "high",
            "requires_dcc_connection": True,
        },
        "dcc_query": {
            # Live host-state queries are distinct from scene mutation. Keeping
            # them off dcc.execution_pipeline prevents read-only DCC queries
            # from being treated as generic execution requests by the chat UI.
            "execution_route": "dcc.scene_query",
            "handler_id": "DCCExecutionHandler",
            "operation_mode": "query",
            "target_type": "dcc_scene_query",
            "execution_environment": "dcc_host",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": ["dcc_connection", "scene_context"],
            "deterministic_steps": [
                "check_connection",
                "execute_read_only_query_adapter",
                "format_query_result",
            ],
            "model_capability": "none",
            "risk_level": "low",
            "requires_dcc_connection": True,
            "can_execute_directly": True,
        },
        "unreal_capability": {
            "execution_route": "unreal.capability_pipeline",
            "handler_id": "CommandRouter.plan_unreal_request",
            "operation_mode": "execute_or_inspect",
            "target_type": "unreal_capability",
            "execution_environment": "unreal",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["unreal_reflection_index", "capability_graph", "argument_validation"],
            "deterministic_steps": ["search_capabilities", "resolve_function", "validate_arguments", "confirm_if_mutating", "execute_unreal"],
            "model_capability": "none",
            "risk_level": "high",
            "requires_dcc_connection": True,
            "requires_fresh_index": True,
        },
        "dcc_prototype": {
            "execution_route": "dcc.prototype_pipeline",
            "handler_id": "CommandRouter.execute_dcc_editor_operation",
            "operation_mode": "prototype",
            "target_type": "dcc_scene_or_tool",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "semantic",
            "context_resolvers": ["dcc_connection", "scene_context", "capability_graph"],
            "deterministic_steps": ["gather_scene_context", "plan_prototype", "confirm_execution"],
            "model_capability": "local_code",
            "risk_level": "high",
            "requires_dcc_connection": True,
            "requires_plan": True,
        },
        "function_execution": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "execute",
            "target_type": "function",
            "execution_environment": "unknown",
            "mutation_scope": "unknown",
            "analysis_depth": "graph",
            "context_resolvers": ["symbol_index", "callable_metadata"],
            "deterministic_steps": ["resolve_function", "ask_for_execution_environment", "validate_arguments"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
        },
        "github_ingest": {
            "execution_route": "ui.github_import",
            "handler_id": "MainWindow.trigger_web_import",
            "operation_mode": "ingest",
            "target_type": "repository",
            "execution_environment": "external_repository",
            "mutation_scope": "persistent_local_mutation",
            "analysis_depth": "index",
            "context_resolvers": ["github_search", "index_repository"],
            "deterministic_steps": ["open_import_ui", "select_repository", "ingest_repository", "index_repository"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
        },
        "chat": {
            "execution_route": "llm.chat",
            "handler_id": "ai_router.route_prompt",
            "operation_mode": "chat",
            "target_type": "conversation",
            "execution_environment": "model",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": [],
            "deterministic_steps": ["route_model"],
            "model_capability": "local_fast",
            "risk_level": "low",
            "can_execute_directly": True,
        },
    }
    defaults = route_defaults.get(decision.route, {})
    list_defaults_that_may_overwrite_when_empty = {"context_resolvers", "deterministic_steps"}
    protected_defaults = {"operations", "required_context", "missing_info", "reasons", "rejected_routes", "alternatives"}
    for key, value in defaults.items():
        if key in protected_defaults:
            continue
        current = getattr(decision, key, None)
        empty_list_allowed = key in list_defaults_that_may_overwrite_when_empty and current == []
        if (current in ("", None, False) or empty_list_allowed) and key not in {"requires_plan", "requires_fresh_index", "requires_dcc_connection", "can_execute_directly"}:
            setattr(decision, key, value)
        elif key in {"requires_plan", "requires_fresh_index", "requires_dcc_connection", "can_execute_directly"} and not getattr(decision, key):
            setattr(decision, key, bool(value))
    if decision.host and not decision.execution_environment:
        decision.execution_environment = decision.host
    if decision.host and not decision.search_scopes:
        if decision.host == "unreal":
            decision.search_scopes = ["project", "external_tools", "unreal_engine"]
            decision.index_filters = {
                "scope": "unreal_project",
                "host": "unreal",
                "source_scopes": ["project", "external_tools", "unreal_engine"],
            }
            if "host_scoped_index" not in decision.context_resolvers:
                decision.context_resolvers.append("host_scoped_index")
            decision.reasons.append("Host hint `unreal` narrows index searches to project/general Python plus Unreal-related code.")
        elif decision.host == "maya":
            decision.search_scopes = ["project", "external_tools", "maya"]
            decision.index_filters = {
                "scope": "maya_project",
                "host": "maya",
                "source_scopes": ["project", "external_tools", "maya"],
            }
            if "host_scoped_index" not in decision.context_resolvers:
                decision.context_resolvers.append("host_scoped_index")
            decision.reasons.append("Host hint `maya` narrows index searches to project/general Python plus Maya-related code.")
        else:
            decision.search_scopes = ["project", "external_tools"]
            decision.index_filters = {
                "scope": f"{decision.host}_project",
                "host": decision.host,
                "source_scopes": ["project", "external_tools"],
            }
    if _has_no_execute_guard(lower):
        read_only_navigation = (
            decision.route == "unreal_capability"
            and decision.target_type == "dcc_navigation"
            and str(decision.target_identifier or "").startswith("navigation.")
            and decision.mutation_scope == "read_only"
        )
        read_only_query = (
            decision.route in {"dcc_query", "unreal_capability"}
            and decision.operation_mode == "query"
            and decision.mutation_scope == "read_only"
            and str(decision.target_identifier or "") in {"project.snapshot", "selection", "scene.list_joints", "scene.ls", "scene"}
        )
        if read_only_navigation:
            decision.operation_mode = decision.operation_mode or "navigate"
            decision.can_execute_directly = True
        elif read_only_query:
            decision.can_execute_directly = True
        elif decision.route in {"dcc_execute", "dcc_prototype", "unreal_capability", "function_execution"}:
            decision.operation_mode = "preview"
        elif not decision.operation_mode:
            decision.operation_mode = "preview"
        decision.mutation_scope = "read_only"
        decision.requires_dcc_connection = False
        decision.requires_confirmation = False
        if not (read_only_navigation or read_only_query):
            decision.can_execute_directly = False
        decision.risk_level = "low"
        decision.disqualifiers.append("Prompt explicitly blocked execution or mutation.")
    if decision.compound_kind == "atomic":
        decision.compound_kind = _detect_compound_kind(lower)
    if not decision.operations:
        decision.operations = _compound_operations(lower, decision.route, decision.operation_mode)
    if (
        decision.route == "project_search"
        and decision.model_tier == "none_deterministic"
        and _is_simple_project_fact_question(lower)
    ):
        decision.visible_progress = _simple_project_fact_progress()
        decision.senior_prompt_analysis = {}
        decision.reasoning_pipeline = {}
        decision.domain_experts = []
        decision.capability_gap_plan = {}
        return decision
    rich_context_allowed = len(lower or "") <= 1200
    if not rich_context_allowed:
        decision.reasons.append("Deferred rich route analysis during foreground classification for a medium/long prompt.")
        try:
            from services.goal_gap_planning_service import build_goal_gap_plan, compact_goal_gap_plan

            decision.capability_gap_plan = compact_goal_gap_plan(
                build_goal_gap_plan(lower[:1000], decision.to_dict()),
                max_links=2,
                max_options=1,
                max_learning=1,
                max_actions=0,
                max_tests=0,
            )
        except Exception:
            decision.capability_gap_plan = {}
        try:
            from services.prompt_progress_service import build_prompt_progress_plan, compact_prompt_progress_plan

            decision.visible_progress = compact_prompt_progress_plan(
                build_prompt_progress_plan(lower[:800], decision.to_dict()),
                max_stages=4,
            )
        except Exception:
            decision.visible_progress = {}
        return decision

    try:
        from services.engineering_reasoning_service import analyze_senior_prompt

        decision.senior_prompt_analysis = analyze_senior_prompt(
            lower,
            route=decision.route,
            intent_category=decision.intent_category,
            host=decision.host,
            provider=decision.provider,
            existing=decision.to_dict(),
        )
    except Exception:
        decision.senior_prompt_analysis = {}
    try:
        from services.domain_expert_service import select_domain_experts

        decision.domain_experts = select_domain_experts(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.domain_experts = []
    try:
        from services.goal_gap_planning_service import build_goal_gap_plan

        decision.capability_gap_plan = build_goal_gap_plan(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.capability_gap_plan = {}
    try:
        from services.multi_stage_reasoning_service import build_reasoning_pipeline

        decision.reasoning_pipeline = build_reasoning_pipeline(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.reasoning_pipeline = {}
    try:
        from services.prompt_progress_service import build_prompt_progress_plan

        decision.visible_progress = build_prompt_progress_plan(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.visible_progress = {}
    return decision


def _is_vague_senior_improvement(lower: str) -> bool:
    if not re.search(r"\b(make|improve|clean up|cleanup|production ready|scalable|maintainable|fragile|better)\b", lower or ""):
        return False
    if re.search(
        r"\b(latency|ranking|recall|memory leak|startup|specific|line|file|files|function|class|method|traceback|exception|error code|compile error|efficient|efficiency|duplicate|duplicates|refactor|change multiple)\b",
        lower or "",
    ):
        return False
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", lower or ""):
        return False
    return bool(
        re.search(r"\b(system|architecture|feature|subsystem|project search|search|operation|code|project|this|that|it)\b", lower or "")
    )


def _looks_like_staged_long_contract(text: str, lower: str) -> bool:
    """Return True for long checklist prompts that should be staged through LLM planning."""
    if len(text or "") < 900:
        return False
    numbered_count = len(re.findall(r"(?:^|\s)\d+[.)]\s+", text or ""))
    if numbered_count < 4 and not re.search(r"\b(before making any changes|implementation requirements|after implementation)\b", lower or ""):
        return False
    if not re.search(r"\b(inspect|identify|determine|propose|plan|before editing|validate|report)\b", lower or ""):
        return False
    return bool(
        re.search(r"\b(do not skip|preserve|rollback|compile|syntax-check|ask only|before making any changes)\b", lower or "")
        or numbered_count >= 8
    )


def classify_prompt_route(
    prompt: str,
    *,
    project_roots: list[str] | None = None,
    active_path: str | None = None,
) -> PromptRouteDecision:
    """Return the intended route without performing model, filesystem, DCC, or broad index work."""
    text = re.sub(r"\s+", " ", prompt or "").strip()
    lower = text.lower()
    roots = project_roots or []
    host = _detect_host(text)
    hosts = _detect_hosts(text)
    no_execute = _has_no_execute_guard(lower)
    try:
        from services.prompt_intent_service import classify_prompt_intent, understand_prompt_request
        from services.prompt_task_splitter_service import build_request_task_graph, task_graph_route

        request_understanding = understand_prompt_request(text, host=host)
        phrase_intent = classify_prompt_intent(text, host=host)
        task_graph = build_request_task_graph(text, host=host)
        semantic_route = task_graph_route(task_graph)

        goal_graph = task_graph
        primary_goal = str(
            goal_graph.get("primary_goal")
            or request_understanding.primary_goal
            or request_understanding.normalized_goal
            or ""
        )
        goal_type = str(
            goal_graph.get("goal_type")
            or request_understanding.goal_type
            or ""
        ).lower()
        goal_count = len(goal_graph.get("goals") or goal_graph.get("tasks") or [])
        estimated_steps = int(
            goal_graph.get("estimated_steps")
            or request_understanding.estimated_steps
            or goal_count
            or 0
        )
        requires_project_search = bool(
            goal_graph.get("requires_project_search")
            or request_understanding.requires_project_search
        )
        requires_generation = bool(
            goal_graph.get("requires_generation")
            or request_understanding.requires_generation
        )
        requires_execution = bool(
            goal_graph.get("requires_execution")
            or request_understanding.requires_execution
        )
        requires_validation = bool(
            goal_graph.get("requires_validation")
            or request_understanding.requires_validation
        )
        semantic_execution_contract = dict(
            goal_graph.get("semantic_execution_contract")
            or request_understanding.semantic_execution_contract
            or {}
        )
    except Exception:
        phrase_intent = None
        request_understanding = None
        task_graph = {}
        goal_graph = {}
        semantic_route = ""
        primary_goal = ""
        goal_type = ""
        goal_count = 0
        estimated_steps = 0
        requires_project_search = False
        requires_generation = False
        requires_execution = False
        requires_validation = False
        semantic_execution_contract = {}

    route_candidates = _route_candidate_diagnostics(text, lower, host=host, hosts=hosts)
    # ------------------------------------------------------------------
    # Goal-first routing
    #
    # The goal graph owns the user's terminal objective. Supporting search
    # goals do not turn teaching/example requests into project-search results.
    # Explicit mutations and host execution remain protected by later guards.
    # ------------------------------------------------------------------
    semantic_confidence = float(
        request_understanding.confidence if request_understanding else 0.0
    )

    if (
        request_understanding
        and semantic_confidence >= 0.78
        and goal_type in {"learn", "explain", "compare", "respond"}
        and not request_understanding.mutation_requested
        and not requires_execution
    ):
        return _finalize_decision(
            PromptRouteDecision(
                route="chat",
                provider="llm",
                confidence=semantic_confidence,
                intent_category=request_understanding.primary_intent or "code_generation_guidance",
                host=host,
                operation_mode="respond",
                mutation_scope="read_only",
                required_context=(
                    ["project_index", "symbol_index", "request_goal_graph"]
                    if requires_project_search
                    else ["request_goal_graph"]
                ),
                model_tier="local_fast",
                primary_goal=primary_goal,
                goal_type=goal_type,
                estimated_steps=estimated_steps,
                requires_generation=requires_generation,
                requires_project_search=requires_project_search,
                requires_validation=requires_validation,
                requires_execution=requires_execution,
                request_understanding=request_understanding.to_dict(),
                task_graph=goal_graph,
                route_candidates=route_candidates,
                selected_route_reason="The terminal goal is explanation or teaching; project search is supporting evidence only.",
                reasons=[
                    "The request asks for guidance, explanation, comparison, or an example rather than a project mutation.",
                    "Any project search goal supports the final explanation instead of becoming the terminal response.",
                ],
                rejected_routes=["target_discovery", "dcc_execute"],
            ),
            lower,
        )

    if (
        request_understanding
        and semantic_confidence >= 0.78
        and goal_type == "generate"
        and not request_understanding.mutation_requested
        and not requires_execution
    ):
        return _finalize_decision(
            PromptRouteDecision(
                route="chat",
                provider="llm",
                confidence=semantic_confidence,
                intent_category=request_understanding.primary_intent or "code_generation",
                host=host,
                operation_mode="generate",
                mutation_scope="read_only",
                required_context=(
                    ["project_index", "symbol_index", "request_goal_graph"]
                    if requires_project_search
                    else ["request_goal_graph"]
                ),
                model_tier="local_code",
                primary_goal=primary_goal,
                goal_type=goal_type,
                estimated_steps=estimated_steps,
                requires_generation=True,
                requires_project_search=requires_project_search,
                requires_validation=requires_validation,
                requires_execution=False,
                request_understanding=request_understanding.to_dict(),
                task_graph=goal_graph,
                route_candidates=route_candidates,
                selected_route_reason="The terminal goal is code generation without modifying project files.",
                reasons=[
                    "Generation is the terminal goal.",
                    "Project search may supply reusable patterns before the model produces the requested example.",
                ],
                rejected_routes=["target_discovery", "dcc_execute"],
            ),
            lower,
        )

    # Semantic understanding owns the primary intent for mixed-language requests.
    # Deterministic routing still verifies facts, contracts, and safety.
    if (
        request_understanding
        and semantic_confidence >= 0.78
        and semantic_route in {"target_discovery", "project_search", "pipeline_graph", "action_graph"}
    ):
        common_goal_metadata = {
            "primary_goal": primary_goal,
            "goal_type": goal_type,
            "estimated_steps": estimated_steps,
            "requires_generation": requires_generation,
            "requires_project_search": requires_project_search,
            "requires_validation": requires_validation,
            "requires_execution": requires_execution,
            "request_understanding": request_understanding.to_dict(),
            "task_graph": goal_graph,
            "semantic_execution_contract": semantic_execution_contract,
        }

        if semantic_route == "target_discovery" and (
            request_understanding.mutation_requested
            or goal_type == "modify"
            or bool(goal_graph.get("mutation_goal_ids"))
        ):
            source_files = _explicit_source_file_references(text)
            return _finalize_decision(
                PromptRouteDecision(
                    route="target_discovery",
                    provider="target_discovery",
                    intent_category=request_understanding.primary_intent or "project_code_edit",
                    host=host,
                    confidence=semantic_confidence,
                    target_type="code",
                    target_identifier=request_understanding.target_file or (source_files[0] if source_files else ""),
                    requires_confirmation=bool(goal_graph.get("approval_goal_ids")) or True,
                    required_context=["target_discovery", "symbol_index", "code_chunks", "request_goal_graph"],
                    model_tier="local_code",
                    route_candidates=route_candidates,
                    selected_route_reason="The goal graph contains a project-code mutation.",
                    reasons=list(
                        request_understanding.reasons
                        or ["The terminal goal modifies project code."]
                    ),
                    rejected_routes=["project_search", "action_graph", "pipeline_graph", "dcc_execute"],
                    **common_goal_metadata,
                ),
                lower,
            )

        if (
            semantic_route == "project_search"
            and goal_type not in {"learn", "explain", "compare", "generate", "modify", "execute"}
            and not request_understanding.mutation_requested
        ):
            return _finalize_decision(
                PromptRouteDecision(
                    route="project_search",
                    provider="project_search",
                    intent_category=request_understanding.primary_intent or "project_exploration",
                    host=host,
                    confidence=semantic_confidence,
                    operation_mode="query",
                    mutation_scope="read_only",
                    required_context=["project_index", "symbol_index", "request_goal_graph"],
                    model_tier="none_deterministic",
                    route_candidates=route_candidates,
                    selected_route_reason="The terminal goal is a read-only project lookup.",
                    reasons=list(request_understanding.reasons),
                    rejected_routes=["target_discovery", "dcc_execute", "action_graph"],
                    **common_goal_metadata,
                ),
                lower,
            )

        if (
            semantic_route in {"pipeline_graph", "action_graph"}
            and (
                request_understanding.workflow_requested
                or goal_type == "plan"
                or bool(goal_graph.get("requires_graph"))
            )
        ):
            route_name = "pipeline_graph" if semantic_route == "pipeline_graph" else "action_graph"
            return _finalize_decision(
                PromptRouteDecision(
                    route=route_name,
                    provider="action_graph",
                    intent_category=request_understanding.primary_intent or "workflow_pipeline",
                    host=host,
                    confidence=semantic_confidence,
                    required_context=["project_index", "symbol_index", "workflow_graph", "request_goal_graph"],
                    route_candidates=route_candidates,
                    selected_route_reason="The goal graph requires explicit workflow orchestration.",
                    reasons=list(request_understanding.reasons),
                    **common_goal_metadata,
                ),
                lower,
            )

    # Version 1.0 Recovery precedence law: explicit source-code mutation wins
    # before DCC operation inference and workflow/pipeline classification.
    if _is_explicit_source_code_mutation(text, lower):
        source_files = _explicit_source_file_references(text)
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="explicit_source_code_edit",
            host=host,
            confidence=0.97,
            target_type="code",
            target_identifier=source_files[0] if source_files else "",
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            route_candidates=route_candidates,
            selected_route_reason="Explicit source filename plus code-mutation intent has highest precedence.",
            request_understanding=request_understanding.to_dict() if request_understanding else {},
            task_graph=goal_graph,
            semantic_execution_contract=semantic_execution_contract,
            primary_goal=primary_goal,
            goal_type=goal_type,
            estimated_steps=estimated_steps,
            requires_generation=requires_generation,
            requires_project_search=requires_project_search,
            requires_validation=requires_validation,
            requires_execution=requires_execution,
            reasons=[
                "Prompt explicitly names a source file and requests a code mutation.",
                "Project code edits must be resolved by target discovery before any DCC or workflow inference.",
            ],
            rejected_routes=["action_graph", "pipeline_graph", "dcc_execute", "dcc_prototype"],
        ), lower)

    if _is_connection_status_question(lower):
        return _finalize_decision(PromptRouteDecision(
            route="connection_status",
            provider="connection_status",
            intent_category="connection_status",
            host=host,
            confidence=0.9,
            mutation_scope="read_only",
            model_tier="none_deterministic",
            reasons=["Prompt asks for connection/status information; do not compile an action graph."],
            rejected_routes=["action_graph", "pipeline_graph", "dcc_execute"],
        ), lower)

    if phrase_intent and phrase_intent.kind == "host_state_query" and not _has_explicit_dcc_mutation(lower):
        target = phrase_intent.target or "selection"
        if host == "unreal" and target == "project":
            return _finalize_decision(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name="ai_studio.synthetic.project_snapshot",
                target_identifier="project.snapshot",
                operation_mode="query",
                mutation_scope="read_only",
                risk_level="low",
                confidence=phrase_intent.confidence,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                model_tier="none_deterministic",
                reasons=list(phrase_intent.reasons or ["Prompt asks for a read-only Unreal project snapshot."]),
                rejected_routes=["navigation.open_asset", "dcc_execute", "action_graph"],
            ), lower)
        keyword_args: dict[str, Any] = {}
        if host == "maya" and target == "scene.list_joints":
            try:
                from services.dcc_operation_service import build_dcc_operation_params

                keyword_args = dict(build_dcc_operation_params("maya", "scene.list_joints", text) or {})
            except Exception:
                keyword_args = {}
        elif host == "maya" and target == "selection":
            target = "scene.ls"
            keyword_args = {"selection": True}
        return _finalize_decision(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host=host,
            target_identifier=target,
            keyword_args=keyword_args,
            operation_mode="query",
            mutation_scope="read_only",
            confidence=phrase_intent.confidence,
            requires_confirmation=False,
            required_context=["dcc_connection"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or [f"Prompt asks for read-only {host} state."]),
            rejected_routes=["navigation.open_asset", "unreal_capability", "dcc_execute", "action_graph"],
        ), lower)

    if not host and no_execute and re.search(r"\b(inspect|check|analyze|analyse|find|review|determine|identify)\b", lower) and re.search(
        r"\b(project|code|codebase|files|classes|functions|systems?|implementation|architecture)\b",
        lower,
    ):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="read_only_project_investigation",
            confidence=0.82,
            operation_mode="investigate",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "code_chunks"],
            model_tier="local_fast",
            reasons=["Prompt asks for read-only project investigation and explicitly avoids editing."],
            rejected_routes=["unreal_capability", "action_graph", "target_discovery"],
        ), lower)

    if _looks_like_staged_long_contract(text, lower):
        return _finalize_decision(PromptRouteDecision(
            route="chat",
            provider="llm",
            intent_category="staged_long_contract",
            host=host,
            confidence=0.82,
            operation_mode="staged_plan",
            mutation_scope="read_only",
            analysis_depth="staged",
            required_context=[
                "project_context",
                "connected_application_context",
                "task_chunks",
                "global_constraints",
                "deferred_stages",
            ],
            model_tier="local_code",
            requires_plan=True,
            requires_confirmation=False,
            reasons=[
                "Prompt is a long staged contract; route to staged LLM planning before any deterministic pipeline/action graph execution.",
                "Foreground routing should not reinterpret checklist wording like pipeline nodes as a Tech Connector pipeline graph request.",
            ],
            rejected_routes=["pipeline_graph", "action_graph", "dcc_execute"],
        ), lower)

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ), lower)

    if phrase_intent and phrase_intent.kind == "project_symbol_search":
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=phrase_intent.confidence,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "docstrings"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or ["Prompt asks for read-only symbol/function search."]),
            rejected_routes=["target_discovery", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ), lower)

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from services.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "", [])
                ]
                rig_prereq_decision = _maya_rigging_prerequisite_decision(
                    host=host,
                    operation_key=op_key,
                    op_function=op.function,
                    text=text,
                    params=params,
                    no_execute=no_execute,
                )
                if rig_prereq_decision:
                    return _finalize_decision(rig_prereq_decision, lower)
                if op_key in {"scene.list_joints", "scene.ls"}:
                    return _finalize_decision(PromptRouteDecision(
                        route="dcc_query",
                        confidence=0.96,
                        provider="dcc",
                        intent_category="dcc_query",
                        host=host,
                        callable_name=op.function,
                        target_identifier=op_key,
                        keyword_args=params,
                        requires_confirmation=False,
                        mutation_scope="read_only",
                        required_context=["dcc_connection", "scene_context"],
                        missing_info=missing_info,
                        model_tier="none_deterministic",
                        reasons=[f"Prompt asks for a read-only {host} scene inventory query."],
                        rejected_routes=["llm.chat", "dcc_execute", "project_search"],
                    ), lower)
                return _finalize_decision(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                    rejected_routes=["action_graph", "project_search", "target_discovery"],
                ), lower)
        except Exception:
            pass

    if host and re.search(r"\b(where should|where would|how should|how would)\b", lower) and re.search(
        r"\b(add|create|implement|put|place|wire)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_understanding",
            host=host,
            confidence=0.82,
            required_context=["project_index", "symbol_index", "project_architecture"],
            model_tier="local_fast",
            reasons=["Prompt asks where/how to add something; answer from indexed project architecture before host execution."],
            rejected_routes=["dcc_execute", "dcc_prototype", "unreal_capability"],
        ), lower)

    if host == "unreal" and _is_unreal_graph_operation_planning_request(lower):
        target_asset = ""
        try:
            from services.unreal.unreal_operation_service import extract_unreal_asset_name, extract_unreal_package_like_path

            target_asset = str(extract_unreal_package_like_path(text) or extract_unreal_asset_name(text) or "")
        except Exception:
            target_asset = ""
        return _finalize_decision(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="unreal_semantic_graph_planning",
            host="unreal",
            confidence=0.9,
            callable_name="unreal_tools.graph.semantic_edit_plan",
            target_identifier=target_asset,
            keyword_args={"target_asset": target_asset} if target_asset else {},
            operation_mode="plan",
            target_type="unreal_graph",
            mutation_scope="read_only",
            risk_level="low",
            requires_confirmation=False,
            required_context=[
                "unreal_reflection_index",
                "capability_graph",
                "semantic_graph_understanding",
                "graph_node_pin_link_index",
                "argument_validation",
            ],
            model_tier="none_deterministic",
            reasons=[
                "Prompt asks to inspect or report available Unreal graph operations; keep this in graph planning instead of plain asset navigation.",
            ],
            rejected_routes=["navigation.open_asset", "pipeline_graph", "action_graph"],
        ), lower)

    if host == "unreal":
        try:
            from services.unreal.semantic_graph_service import is_unreal_graph_modification_request

            if is_unreal_graph_modification_request(text):
                target_asset = ""
                try:
                    from services.unreal.unreal_operation_service import extract_unreal_asset_name, extract_unreal_package_like_path

                    target_asset = str(extract_unreal_package_like_path(text) or extract_unreal_asset_name(text) or "")
                except Exception:
                    target_asset = ""
                return _finalize_decision(PromptRouteDecision(
                    route="unreal_capability",
                    provider="unreal",
                    intent_category="unreal_semantic_graph_modification",
                    host="unreal",
                    confidence=0.91,
                    callable_name="unreal_tools.graph.semantic_edit_plan",
                    target_identifier=target_asset,
                    keyword_args={"target_asset": target_asset} if target_asset else {},
                    requires_confirmation=not no_execute,
                    required_context=[
                        "unreal_reflection_index",
                        "capability_graph",
                        "semantic_graph_understanding",
                        "graph_node_pin_link_index",
                        "existing_behavior_preservation",
                        "similar_project_patterns",
                        "argument_validation",
                    ],
                    mutation_scope="graph_asset",
                    risk_level="high",
                    model_tier="local_code",
                    reasons=[
                        "Prompt asks to modify an Unreal graph; route before generic pipeline graph handling.",
                        "Semantic graph understanding and preservation checks are required before graph mutation.",
                    ],
                    rejected_routes=["pipeline_graph", "action_graph"],
                ), lower)
        except Exception:
            pass

    pipeline_code_target = bool(
        re.search(r"\b(pipeline|node graph|node view|add and connect|right click|right-click|compile button|required inputs|tool filter)\b", lower)
        and re.search(r"\b(find|where|code path|fix|improve|patch|repair|update|slow|warning|propose)\b", lower)
    )
    if pipeline_code_target:
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="pipeline_code_edit",
            host=host,
            confidence=0.86,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "pipeline_graph_code", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to find or improve Tech Connector pipeline/node-graph code, not to compose or execute a pipeline graph."],
            rejected_routes=["pipeline_graph", "action_graph", "dcc_execute"],
        ), lower)

    status_code_target = bool(
        re.search(r"\b(index|indexing|knowledge|status|status bar|status panel|progress|ready|stale|connection|connected|theme|color|ui)\b", lower)
        and re.search(r"\b(find|where|code path|owning files?|likely owning|fix|improve|patch|repair|update|wrong|bug|says|still|running|slow|freeze|frozen)\b", lower)
        and not (
            host
            and re.search(r"\b(function|functions|method|operation)\b", lower)
            and re.search(r"\b(ui|wrapper|window|interface|panel|tool)\b", lower)
        )
    )
    if status_code_target:
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="status_ui_code_edit",
            host=host,
            confidence=0.84,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "status_ui_code", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to find or fix Tech Connector status/index/UI code, not to perform a broad project fact search."],
            rejected_routes=["project_search", "action_graph", "dcc_execute"],
        ), lower)

    application_code_target = bool(
        re.search(
            r"\b(chat history|old thread|thread disappears|switch chat|switching chat|mobile app|jobs?|output logs?|job logs?|ide agent|repo map|symbol lookup|structured patching|error reporting|reporting quality|rollback status)\b",
            lower,
        )
        and re.search(r"\b(plan|propose|find|where|code path|owning files?|fix|improve|patch|repair|update|reuse|tests?)\b", lower)
    )
    if application_code_target:
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="application_code_architecture",
            host=host,
            confidence=0.83,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "project_architecture", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for Tech Connector application-code planning or repair; discover owning files before synthesis."],
            rejected_routes=["project_search", "pipeline_graph", "action_graph", "dcc_execute"],
        ), lower)
    
    # Check if this is a pipeline or multi-DCC request
    is_pipeline = False
    if len(hosts) >= 2:
        is_pipeline = True
    elif len(hosts) == 1 and re.search(r"\b(pipeline|workflow|bridge|connect|transfer|export|import)\b", lower):
        is_pipeline = True
    elif re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|multi-step|multi step|sequence|compose)\b", lower):
        is_pipeline = True
        
    if is_pipeline:
        route = "pipeline_graph" if re.search(r"\b(create|make|setup|build|design|scaffold|graph|ui|nodes?|nodes? view|compose|sequence)\b", lower) else "action_graph"
        return _finalize_decision(PromptRouteDecision(
            route=route,
            provider="action_graph",
            intent_category="workflow_pipeline",
            host=host or (hosts[0] if hosts else ""),
            confidence=0.88,
            required_context=["project_index", "symbol_index", "workflow_graph"],
            reasons=["Prompt is classified as a multi-DCC or pipeline request."],
        ), lower)

    file_ref = _has_file_ref(text) or bool(active_path and re.search(r"\b(this|current|active|selected)\s+(?:file|script)\b", lower))
    symbol_ref = bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b", text or ""))
    execution_callable = _callable_after_execution_verb(text)
    known_unreal_operation = _known_unreal_operation_from_text(text)

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ), lower)

    if phrase_intent and phrase_intent.kind == "project_symbol_search":
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=phrase_intent.confidence,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "docstrings"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or ["Prompt asks for read-only symbol/function search."]),
            rejected_routes=["target_discovery", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ), lower)

    if phrase_intent and phrase_intent.kind in {"asset_navigation", "graph_read_or_navigation"} and host == "unreal" and known_unreal_operation:
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        if operation_key.startswith("navigation.") or operation_key in {"blueprint.scan", "assets.inspect"}:
            return _finalize_decision(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=operation_key,
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                operation_mode="navigate" if operation_key.startswith("navigation.") else "query",
                target_type="dcc_navigation" if operation_key.startswith("navigation.") else "dcc_callable",
                mutation_scope="read_only",
                risk_level="low",
                can_execute_directly=operation_key.startswith("navigation."),
                confidence=max(0.9, phrase_intent.confidence),
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=list(phrase_intent.reasons or ["Prompt asks for read-only Unreal asset or graph navigation."]),
                rejected_routes=["unreal_semantic_graph_modification", "pipeline_graph", "action_graph"],
            ), lower)

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ), lower)

    if host == "unreal" and known_unreal_operation:
        early_unreal_operation_key = str(known_unreal_operation.get("operation_key") or "")
        if early_unreal_operation_key in {"project.snapshot", "blueprint.scan", "assets.inspect"}:
            return _finalize_decision(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=early_unreal_operation_key,
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                mutation_scope="read_only",
                risk_level="low",
                confidence=0.92,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=["Prompt maps to a registered read-only Unreal operation; do not fall back to generic project source search."],
                rejected_routes=["project_search", "dcc_query"],
            ), lower)

    if re.search(r"\b(docstring|docstrings|function docs|function documentation|param docs|parameter docs|missing params?|missing parameters?)\b", lower) and re.search(
        r"\b(add|create|write|generate|fill|fix|update|patch|improve)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="documentation_code_edit",
            host=host,
            confidence=0.82,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "docstrings", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to modify code documentation; discover real target symbols before editing."],
        ), lower)

    if re.search(r"\b(find|locate|identify|inspect|diagnose|troubleshoot)\b", lower) and re.search(
        r"\b(make|improve|fix|patch|repair|update|change|refactor|more actionable|clearer|better)\b", lower
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="discover_then_edit",
            host=host,
            confidence=0.80,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt combines target discovery with a requested code improvement."],
        ), lower)

    early_project_fact_query = (
        (
            re.search(r"\b(what|which|where|list|show|find|first|how many|arguments|args|required|dependencies|classes|functions|methods)\b", lower)
            or re.search(r"\b(callers|callees|called by|uses|usages|references)\b", lower)
            or re.search(r"\bis\s+there\s+(?:a\s+)?(?:function|method|class|symbol)\b", lower)
        )
        and (
            file_ref
            or symbol_ref
            or _looks_like_read_only_project_question(lower)
            or re.search(r"\b(project|file|files|function|functions|class|classes|method|methods|symbol|symbols|import|imports|dependency|dependencies|python|py|argument|arguments|args|caller|callers|callee|callees)\b", lower)
        )
        and not re.search(r"\b(then|after that|and then|go ahead|do it|apply|execute|run|actually add|actually create|make the change)\b", lower)
    )
    if early_project_fact_query and not re.search(r"\b(create|build|add|implement|write|modify|update|fix|patch|wire|connect)\b.*\b(ui|tool|feature|code|file|class|function|method)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.86,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for indexed project/code facts before any action-graph or host execution."],
            rejected_routes=["action_graph", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ), lower)

    if _is_vague_senior_improvement(lower):
        return _finalize_decision(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="senior_investigation",
            host=host,
            confidence=0.78,
            operation_mode="investigate",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "current_behavior", "failure_modes"],
            model_tier="local_code",
            reasons=["Prompt is a broad senior-level improvement request; investigate the failing dimension before editing."],
            alternatives=[
                {"route": "target_discovery", "reason": "Use after the failing dimension and edit target are identified."},
            ],
        ), lower)
    if not host and str(known_unreal_operation.get("operation_key") or "").startswith("navigation."):
        host = "unreal"
    if not known_unreal_operation and host == "unreal":
        try:
            from services.unreal.unreal_operation_service import unreal_prompt_to_operation, UNREAL_OPERATIONS
            op_key = unreal_prompt_to_operation(text)
            if op_key and op_key in UNREAL_OPERATIONS:
                op = UNREAL_OPERATIONS[op_key]
                if op.mutates_project or op_key in {"project.debug", "blueprint.compile"}:
                    known_unreal_operation = {
                        "operation_key": op_key,
                        "function": op.function,
                        "mutates_project": bool(op.mutates_project),
                        "required": list(op.required),
                    }
        except Exception:
            pass

    if (
        re.search(r"\b(dead|unused|unresolved|missing|broken)\b", lower)
        and re.search(r"\b(import|imports|code|files|functions|classes|dependencies)\b", lower)
        and not re.search(r"\b(docstring|docstrings|function docs|function documentation|param docs|parameter docs)\b", lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="project_health",
            provider="project_health",
            intent_category="code_health",
            host=host,
            confidence=0.86,
            required_context=["dependency_graph", "call_graph", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for deterministic code health/dependency facts."],
        ), lower)

    if re.search(r"\b(circular import|circular imports|circular dependency|circular dependencies|import cycle|dependency cycle)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="project_health",
            provider="project_health",
            intent_category="code_health",
            host=host,
            confidence=0.88,
            required_context=["dependency_graph", "import_graph"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for cycle detection, which should come from the dependency/import graph."],
        ), lower)

    if re.search(r"\b(find|check|diagnose|inspect|review)\b", lower) and re.search(r"\b(problem|issue|bug|broken|error|failure)\b", lower) and re.search(r"\b(then|before|after|ask before|fix|fixing)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="guided_code_fix",
            host=host,
            confidence=0.77,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for a staged diagnose-then-fix flow with confirmation before mutation."],
        ), lower)

    if re.search(r"\b(memory leak|memory leaks|resource leak|resource leaks|race condition|race conditions|thread safety|security issue|security issues|exception handling|error recovery)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="quality_audit",
            host=host,
            confidence=0.76,
            required_context=["symbol_index", "call_graph", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for semantic quality risks; use indexed evidence first, then bounded code reasoning if needed."],
            alternatives=[{"route": "target_discovery", "reason": "Use if the user asks to apply fixes after the audit."}],
        ), lower)

    if re.search(r"\b(unclear|bad|poor|confusing|ambiguous|inconsistent)\b", lower) and re.search(r"\b(name|names|naming|variable|variables|function|functions|api|apis)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="naming_quality",
            host=host,
            confidence=0.74,
            required_context=["symbol_index", "code_chunks"],
            model_tier="local_fast",
            reasons=["Prompt asks for naming clarity analysis grounded in indexed symbols."],
            alternatives=[{"route": "target_discovery", "reason": "Use if the user asks to rename or change the code."}],
        ), lower)

    if re.search(r"\b(optimize|profile|performance|faster|efficient|efficiency|startup|allocations|memory usage|disk io|database queries|rendering|caching|background work|hang|freeze|freezing|ui hang|ui hangs|responsive|responsiveness)\b", lower):
        wants_change = bool(re.search(r"\b(make|improve|reduce|change|fix|update|refactor|speed up|harden|patch|repair)\b", lower))
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery" if wants_change else "quality_audit",
            provider="target_discovery" if wants_change else "project_search",
            intent_category="performance",
            host=host,
            confidence=0.78,
            requires_confirmation=wants_change,
            required_context=["symbol_index", "call_graph", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for performance work; route to audit unless it explicitly asks for code changes."],
        ), lower)

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from services.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "", [])
                ]
                return _finalize_decision(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                    rejected_routes=["action_graph", "project_search", "target_discovery"],
                ), lower)
        except Exception:
            pass

    if host == "unreal" and known_unreal_operation:
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        is_navigation = operation_key.startswith("navigation.")
        if is_navigation:
            return _finalize_decision(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=str(operation_key or known_unreal_operation.get("function") or execution_callable),
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                operation_mode="navigate",
                target_type="dcc_navigation",
                mutation_scope="read_only",
                risk_level="low",
                can_execute_directly=True,
                confidence=0.92,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=[
                    "Prompt references a registered Unreal navigation operation; route before generic action-graph grammar.",
                ],
                rejected_routes=["pipeline_graph", "action_graph"],
            ), lower)

    try:
        from services.action_planner_service import should_route_to_action_graph
        action_graph = should_route_to_action_graph(text, roots)
    except Exception:
        action_graph = False

    if action_graph:
        return _finalize_decision(PromptRouteDecision(
            route="pipeline_graph" if re.search(r"\b(pipeline|workflow|node|graph)\b", lower) else "action_graph",
            provider="action_graph",
            intent_category="workflow_pipeline",
            host=host,
            confidence=0.86 if file_ref else 0.74,
            required_context=["project_index", "symbol_index", "workflow_graph"],
            reasons=["Prompt matches deterministic action-graph grammar."],
            rejected_routes=["dcc_execute", "dcc_prototype", "unreal_capability"],
        ), lower)

    if host == "unreal" and _is_unreal_live_query(lower):
        target = "unreal_query"
        if re.search(r"\b(selection|selected|selected actors|selected assets|what is selected|what's selected)\b", lower):
            target = "selection"
        elif re.search(r"\b(level|world|current|loaded|active)\b", lower):
            target = "level"
        elif re.search(r"\b(skeleton|skeletons)\b", lower):
            target = "skeletons"
        elif re.search(r"\b(mesh|meshes|static mesh)\b", lower):
            target = "meshes"
        elif re.search(r"\b(blueprint|blueprints|control rig|anim blueprint)\b", lower):
            target = "blueprint"
        elif re.search(r"\b(asset|assets)\b", lower):
            target = "assets"
        return _finalize_decision(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host="unreal",
            target_identifier=target,
            callable_name=str(known_unreal_operation.get("function") or ""),
            confidence=0.88,
            requires_confirmation=False,
            required_context=["dcc_connection", "unreal_capability_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for read-only Unreal context from registered/base Unreal Python capabilities."],
            rejected_routes=["dcc_execute", "target_discovery"],
        ), lower)

    if host == "unreal" and known_unreal_operation:
        mutates = bool(known_unreal_operation.get("mutates_project"))
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        is_navigation = operation_key.startswith("navigation.")
        semantic_graph_required = False
        try:
            from services.unreal.semantic_graph_service import is_unreal_graph_modification_request

            semantic_graph_required = is_unreal_graph_modification_request(text)
        except Exception:
            semantic_graph_required = bool(re.search(r"\b(graph|blueprint|node|pin|state machine|anim graph|control rig)\b", lower))
        required_context = ["unreal_reflection_index", "capability_graph", "argument_validation"]
        if semantic_graph_required:
            required_context.extend([
                "semantic_graph_understanding",
                "graph_node_pin_link_index",
                "existing_behavior_preservation",
                "similar_project_patterns",
            ])
        return _finalize_decision(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            callable_name=str(known_unreal_operation.get("function") or execution_callable),
            target_identifier=str(operation_key or known_unreal_operation.get("function") or execution_callable),
            keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
            operation_mode="navigate" if is_navigation else "",
            target_type="dcc_navigation" if is_navigation else "",
            mutation_scope="read_only" if is_navigation else "",
            risk_level="low" if is_navigation else "",
            can_execute_directly=is_navigation,
            confidence=0.92,
            requires_confirmation=mutates and not no_execute,
            required_context=required_context,
            missing_info=list(known_unreal_operation.get("required") or []),
            model_tier="none_deterministic",
            reasons=[
                "Prompt references a registered/base Unreal Python callable; route directly to deterministic Unreal execution preparation.",
                "Unreal graph modification requests must build semantic graph understanding before mutation.",
            ] if semantic_graph_required else ["Prompt references a registered/base Unreal Python callable; route directly to deterministic Unreal execution preparation."],
        ), lower)

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from services.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "")
                ]
                rig_prereq_decision = _maya_rigging_prerequisite_decision(
                    host=host,
                    operation_key=op_key,
                    op_function=op.function,
                    text=text,
                    params=params,
                    no_execute=no_execute,
                )
                if rig_prereq_decision:
                    return _finalize_decision(rig_prereq_decision, lower)
                return _finalize_decision(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                ), lower)
        except Exception:
            pass

    if host and re.search(r"\b(run|execute|call|test|launch)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="dcc_execute",
            provider="dcc",
            intent_category="dcc_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.90,
            requires_confirmation=not no_execute,
            required_context=["dcc_connection", "resolved_callable", "argument_validation"],
            model_tier="none_deterministic",
            reasons=[f"Prompt explicitly asks to run/execute in {host}."],
            rejected_routes=["project_search", "target_discovery"],
        ), lower)

    if host and re.search(r"\b(selection|selected|current file|scene path|scene name|current scene|current level|active level|selected actors|selected assets|what is selected|what's selected)\b", lower):
        target = "selection" if re.search(r"\b(selection|selected|selected actors|selected assets|what is selected|what's selected)\b", lower) else "scene"
        return _finalize_decision(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host=host,
            target_identifier=target,
            confidence=0.84,
            requires_confirmation=False,
            required_context=["dcc_connection"],
            model_tier="none_deterministic",
            reasons=[f"Prompt asks for a read-only {host} host query."],
            rejected_routes=["dcc_execute", "target_discovery"],
        ), lower)

    if (
        not host
        and not re.search(r"\brun\s+through\b", lower)
        and re.search(r"\b(run|execute|call|launch)\s+[A-Za-z_][A-Za-z0-9_]*\b", lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="function_execution",
            provider="action_graph",
            intent_category="function_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.66,
            requires_confirmation=True,
            required_context=["symbol_index", "callable_metadata", "execution_environment"],
            missing_info=["execution_environment"],
            model_tier="none_deterministic",
            reasons=["Prompt asks to execute a function but does not specify where it should run."],
            alternatives=[
                {"route": "dcc_execute", "reason": "Use if the user names Maya, Unreal, Blender, or another host."},
                {"route": "project_search", "reason": "Use if the user meant explain rather than execute."},
            ],
        ), lower)

    if host == "unreal" and re.search(r"\b(compile|spawn|duplicate|blueprint|asset|actor|refresh|inspect)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            confidence=0.84,
            requires_confirmation=bool(re.search(r"\b(compile|spawn|duplicate|create|modify|delete)\b", lower)) and not no_execute,
            required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
            model_tier="none_deterministic",
            reasons=["Prompt contains Unreal host plus Unreal capability terms."],
        ), lower)

    if host and _looks_like_read_only_project_question(lower) and re.search(
        r"\b(find|identify|locate|use|reuse)\b.*\b(function|method|class|tool)\b.*\b(create|build|add|implement|write)\b.*\b(ui|tool|window|panel|interface|code)\b",
        lower,
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="code_edit",
            host=host,
            confidence=0.84,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks", "ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to discover an existing host-related function, then create project UI/code around it."],
            rejected_routes=["dcc_execute", "dcc_prototype", "project_search"],
        ), lower)

    if host and _looks_like_read_only_project_question(lower):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.86,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt names a DCC host but asks for indexed project/code facts, not host execution."],
            rejected_routes=["dcc_execute", "dcc_prototype"],
        ), lower)

    if host and _has_explicit_dcc_mutation(lower) and not no_execute:
        return _finalize_decision(PromptRouteDecision(
            route="dcc_execute",
            provider="dcc",
            intent_category="dcc_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.78,
            requires_confirmation=True,
            required_context=["dcc_connection", "resolved_callable", "argument_validation"],
            model_tier="none_deterministic",
            reasons=[f"Prompt explicitly requests a live {host} scene mutation."],
            rejected_routes=["project_search", "target_discovery", "action_graph"],
            route_candidates=route_candidates,
            selected_route_reason=f"Explicit live {host} mutation language selected DCC execution.",
        ), lower)

    is_explanation = bool(re.search(r"\b(how to|how do|how can|how would|what would i|explain how|how should|can you tell me|can you show me|is there a way to)\b", lower))
    if host and re.search(r"\b(make|create|build|prototype|set up|setup|add)\b", lower) and not re.search(r"\b(pipeline|workflow)\b", lower) and not is_explanation:
        return _finalize_decision(PromptRouteDecision(
            route="dcc_prototype",
            provider="dcc",
            intent_category="dcc_prototype",
            host=host,
            confidence=0.68,
            requires_confirmation=not no_execute,
            required_context=["dcc_connection", "scene_context", "capability_graph"],
            model_tier="local_code",
            reasons=[f"Prompt asks to create/prototype inside {host}."],
            alternatives=[{"route": "target_discovery", "reason": "Use if this is a code edit rather than an in-host operation."}],
        ), lower)

    if re.search(r"\b(prototype|replacement)\b", lower) and re.search(r"\b(do not change|don't change|dont change|without changing|current code)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="feature_work",
            host=host,
            confidence=0.73,
            operation_mode="prototype",
            mutation_scope="read_only",
            requires_confirmation=False,
            required_context=["target_discovery", "symbol_index", "similar_implementations"],
            model_tier="local_code",
            risk_level="low",
            reasons=["Prompt asks for a prototype or replacement without changing current code."],
        ), lower)

    if re.search(r"\b(edit|modify|change|update|refactor|improve|fix|add|implement|clean up|cleanup)\b", lower) and (
        file_ref or symbol_ref or re.search(r"\b(file|files|function|functions|class|classes|method|methods|module|modules|tool|tools|existing|current|code)\b", lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="code_edit",
            host=host,
            confidence=0.80,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for a code change and identifies a code target or target category."],
        ), lower)

    if re.search(r"\b(prototype|implement|build|create|add support|add ui|add command|add tool|scaffold|new subsystem|new feature)\b", lower) and (
        re.search(r"\b(feature|tool|subsystem|integration|support|ui|command|workflow|pipeline node|tests?|replacement)\b", lower)
        or symbol_ref
    ):
        broad = bool(re.search(r"\b(subsystem|architecture|redesign|integration)\b", lower))
        decision = PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="feature_work",
            host=host,
            confidence=0.76,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "similar_implementations", "project_architecture"],
            model_tier="enterprise_optional" if broad else "local_code",
            reasons=["Prompt asks to add or prototype project code; first discover targets and existing patterns."],
            alternatives=[{"route": "dcc_prototype", "reason": "Use only if the user explicitly asks to create inside a connected DCC host."}],
        )
        if re.search(r"\b(do not change|don't change|dont change|without changing|replacement)\b", lower):
            decision.operation_mode = "prototype"
            decision.mutation_scope = "read_only"
            decision.requires_confirmation = False
            decision.can_execute_directly = False
            decision.risk_level = "low"
            decision.reasons.append("Prompt requested prototype/planning without changing current code.")
        return _finalize_decision(decision, lower)

    if re.search(r"\b(explain|summarize|run through|how does|how do|how .+ works|why does|startup order|initialization|execution flow|architecture|what would i|how can|how would|how to|is there a way)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_understanding",
            host=host,
            confidence=0.72,
            required_context=["symbol_index", "code_chunks", "dependency_graph"],
            model_tier="local_fast",
            reasons=["Prompt asks for code understanding; gather indexed evidence before model explanation."],
        ), lower)

    if (
        re.search(r"\b(what|which|where|list|show|find|first|how many|arguments|args|required|dependencies|classes|functions|methods)\b", lower)
        or re.search(r"\b(callers|callees|called by|uses|usages|references)\b", lower)
        or re.search(r"\bis\s+there\s+(?:a\s+)?(?:function|method|class|symbol)\b", lower)
    ) and (
        file_ref
        or symbol_ref
        or re.search(r"\b(project|file|files|function|functions|class|classes|method|methods|symbol|symbols|import|imports|dependency|dependencies|python|py|argument|arguments|args|caller|callers|callee|callees)\b", lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.82,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for indexed project/code facts."],
            rejected_routes=["dcc_execute"],
        ), lower)

    if re.search(r"\b(github|repo|repository|ingest|import)\b", lower) and re.search(r"\b(search|find|ingest|import|use|bring in)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="github_ingest",
            provider="ui",
            intent_category="repository_ingestion",
            host=host,
            confidence=0.70,
            requires_confirmation=True,
            required_context=["github_search", "repository_selection"],
            model_tier="local_fast",
            reasons=["Prompt asks for repository search/import/ingestion as part of a workflow."],
        ), lower)

    return _finalize_decision(PromptRouteDecision(
        route="chat",
        provider="llm",
        intent_category="general_chat",
        host=host,
        confidence=0.35,
        model_tier="local_fast",
        reasons=["No deterministic route exceeded the confidence threshold."],
        semantic_execution_contract=semantic_execution_contract,
        alternatives=[
            {"route": "project_search", "reason": "Use for indexed project facts."},
            {"route": "target_discovery", "reason": "Use for code edits/refactors."},
            {"route": "dcc_execute", "reason": "Use for running a function inside a DCC."},
        ],
    ), lower)


def should_prepare_with_engine(prompt: str, *, project_roots: list[str] | None = None, active_path: str | None = None) -> bool:
    return classify_prompt_route(prompt, project_roots=project_roots, active_path=active_path).provider in ENGINE_PROVIDERS
