"""Structured Unreal Blueprint/AnimGraph rewrite planning.

This is a planning layer, not a direct mutation engine. It builds explicit,
previewable graph rewrite plans so the UI can show what the system intends to
change before any Unreal-side apply step runs.
"""

from __future__ import annotations

from typing import Any

GRAPH_MUTATION_HINTS = (
    "add node",
    "remove node",
    "delete node",
    "replace node",
    "replace nodes",
    "rewire",
    "connect pin",
    "disconnect pin",
    "set property",
    "change property",
)


def _extract_asset_name_candidates(text: str) -> list[str]:
    import re

    paths = re.findall(r"(/Game/[A-Za-z0-9_./-]+)", text or "")
    names = re.findall(r"\b(?:BP|ABP|BPI|WBP|CR)_[A-Za-z0-9_]+\b", text or "")
    return paths + [name for name in names if name not in paths]


def _resolve_unreal_asset_candidate(candidate: str) -> str:
    candidate = str(candidate or "").strip().rstrip(".,;:)")
    if not candidate or candidate.startswith("/Game/"):
        return candidate
    try:
        from bridges.unreal.unreal_bridge import UnrealBridge

        source = f"""
import unreal, json
candidate = {candidate!r}
out = {{'match': ''}}
try:
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = reg.get_assets_by_paths(['/Game'], True, True)
    except TypeError:
        assets = reg.get_assets_by_path('/Game', True, True)
    exact = []
    partial = []
    for asset in assets:
        name = str(getattr(asset, 'asset_name', '') or '')
        package_name = str(getattr(asset, 'package_name', '') or '')
        if name.lower() == candidate.lower():
            exact.append(package_name)
        elif candidate.lower() in name.lower():
            partial.append(package_name)
    out['match'] = (exact or partial or [''])[0]
except Exception as exc:
    out['error'] = str(exc)
print(json.dumps(out))
"""
        response = UnrealBridge().execute_python(source, timeout=12, reset_globals=True)
        data = response.get("data") if isinstance(response, dict) else {}
        if isinstance(data, dict) and data.get("match"):
            return str(data.get("match"))
    except Exception:
        pass
    return candidate


def _extract_quoted_or_said_message(text: str) -> str:
    import re

    for pattern in (
        r"['\"]([^'\"]{1,160})['\"]",
        r"\bsays?\s+(.+?)(?:,|\.\s|$)",
        r"\bmessage\s+(.+?)(?:,|\.\s|$)",
    ):
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(".")
            if value:
                return value
    return "AIStudio BeginPlay Probe"


def _extract_named_graph_node(text: str, fallback: str) -> str:
    import re

    match = re.search(
        r"\b(?:named|called|call\s+it)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        text or "",
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return fallback


def _infer_graph_patch_operations(request_text: str) -> list[dict[str, Any]]:
    text = (request_text or "").lower()
    ops: list[dict[str, Any]] = []
    if ("print" in text or "log" in text or "debug" in text) and "beginplay" in text:
        message = _extract_quoted_or_said_message(request_text)
        ops.append(
            {
                "op": "add_node",
                "graph": "EventGraph",
                "node": "AIStudio_BeginPlayProbe_PrintString",
                "node_class": "Development|PrintString",
                "from_node": "K2Node_Event_0",
                "from_pin": "then",
                "to_pin": "execute",
                "property_name": "InString",
                "property_value": message,
                "reason": "Prompt requested a temporary BeginPlay debug print probe.",
            }
        )
        return ops
    if (
        ("print string" in text or "printstring" in text or "debug print" in text)
        and ("add" in text or "insert" in text or "create" in text)
    ):
        message = _extract_quoted_or_said_message(request_text)
        ops.append(
            {
                "op": "add_node",
                "graph": "EventGraph",
                "node": _extract_named_graph_node(request_text, "AIStudio_PrintString"),
                "node_class": "Development|PrintString",
                "property_name": "InString",
                "property_value": message,
                "reason": "Prompt requested a temporary Print String/debug output node.",
            }
        )
        return ops
    if "rewire" in text or "connect" in text:
        ops.append(
            {
                "op": "connect_pins",
                "graph": "AnimGraph" if "anim" in text else "EventGraph",
                "from_node": "SourceNode",
                "from_pin": "Output",
                "to_node": "TargetNode",
                "to_pin": "Input",
                "reason": "Inferred placeholder pin reconnect from natural-language rewrite request",
            }
        )
    if "remove" in text or "delete" in text:
        ops.append(
            {
                "op": "remove_node",
                "graph": "AnimGraph" if "anim" in text else "EventGraph",
                "node": "NodeToRemove",
                "reason": "Inferred placeholder node removal from natural-language rewrite request",
            }
        )
    if (
        "add" in text
        or "insert" in text
        or "replace node" in text
        or "replace nodes" in text
    ):
        ops.append(
            {
                "op": "add_node",
                "graph": "AnimGraph" if "anim" in text else "EventGraph",
                "node": "NewNode",
                "node_class": "K2Node_Knot",
                "reason": "Conservative placeholder node-add suggestion inferred from natural-language rewrite request",
            }
        )
    return ops


HIGH_RISK_GRAPH_KEYWORDS = (
    "blueprint graph",
    "anim graph",
    "animation blueprint",
    "control rig",
    "motion matching",
    "pose search",
    "rewire",
    "graph rewrite",
    "replace nodes",
    "reconnect pins",
)


def detect_high_risk_graph_request(text: str) -> bool:
    q = (text or "").lower()
    return any(term in q for term in HIGH_RISK_GRAPH_KEYWORDS)


def build_rewrite_plan(
    request_text: str,
    context: dict[str, Any] | None = None,
    graph_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.unreal.semantic_graph_service import build_semantic_graph_analysis

    context = context or {}
    graph_snapshot = graph_snapshot or {}
    selected_assets = list(context.get("selected_assets") or [])
    explicit_assets = _extract_asset_name_candidates(request_text)
    target_asset = (
        explicit_assets[0]
        if explicit_assets
        else (selected_assets[0] if selected_assets else "")
    )
    target_asset = _resolve_unreal_asset_candidate(target_asset)
    target_graph = (
        "AnimGraph" if "anim" in (request_text or "").lower() else "EventGraph"
    )
    graph_names = [
        str(g.get("name"))
        for g in graph_snapshot.get("graphs") or []
        if isinstance(g, dict)
    ]
    graph_exists = target_graph in graph_names if graph_names else "unknown"
    inferred_operations = _infer_graph_patch_operations(request_text)
    semantic_graph = build_semantic_graph_analysis(
        request_text,
        context=context,
        params={"target_asset": target_asset, "target_graph": target_graph},
    )
    edit_intelligence = semantic_graph.get("edit_intelligence") or {}
    process_detection = {
        "request_kind": "unreal_graph_rewrite",
        "graph_mutation_keywords_detected": [
            hint
            for hint in GRAPH_MUTATION_HINTS
            if hint in (request_text or "").lower()
        ],
        "explicit_asset_candidates": explicit_assets,
        "selected_assets_available": selected_assets,
        "target_asset_reason": (
            "explicit_asset_in_prompt"
            if explicit_assets
            else ("selected_asset_context" if selected_assets else "unresolved")
        ),
        "target_graph_reason": "anim_request"
        if "anim" in (request_text or "").lower()
        else "default_event_graph",
        "will_require_confirmation": True,
        "will_require_preflight": True,
        "will_prefer_plan_preview": True,
        "visible_state": "CHANGE_PLANNED",
        "next_state": "AWAITING_APPROVAL",
    }
    return {
        "ok": True,
        "plan_kind": "unreal_graph_rewrite",
        "request_text": request_text,
        "target_asset": target_asset,
        "target_graph": target_graph,
        "graph_exists": graph_exists,
        "available_graphs": graph_names,
        "semantic_graph_understanding": semantic_graph,
        "graph_edit_intelligence": edit_intelligence,
        "visible_edit_lifecycle": semantic_graph.get("visible_edit_lifecycle") or [],
        "graph_edit_state_machine": semantic_graph.get("lifecycle_states") or [],
        "graph_edit_failure_states": semantic_graph.get("failure_states") or [],
        "graph_edit_progress_stages": semantic_graph.get("progress_stages") or [],
        "graph_edit_threading_contract": semantic_graph.get("threading_contract") or {},
        "pre_edit_proposal_required_fields": semantic_graph.get("pre_edit_proposal_required_fields") or [],
        "open_focus_operations": semantic_graph.get("open_focus_operations") or [],
        "focus_targets": semantic_graph.get("focus_targets") or [],
        "graph_layout_contract": semantic_graph.get("layout_contract") or [],
        "post_edit_report_fields": semantic_graph.get("post_edit_report_fields") or [],
        "planned_open_asset_step": {
            "operation": "navigation.open_asset",
            "asset_path": target_asset,
            "graph": target_graph,
            "followups": [
                "blueprint.open_graph",
                "blueprint.focus_graph_item",
                "focus_or_select_planned_insertion_area_when_supported",
                "bring_unreal_editor_forward",
            ],
        },
        "layout_plan": {
            "flow_direction": "infer_from_local_graph_or_default_left_to_right",
            "reserve_space_before_node_creation": True,
            "avoid_overlaps_crossings_and_excessive_wire_length": True,
            "group_new_logic_by_intent": True,
            "preserve_or_expand_related_comment_regions": True,
            "prefer_function_macro_component_if_inline_logic_is_too_large": True,
            "expert_layout_guidance": edit_intelligence.get("layout_plan") or [],
        },
        "compile_expectations": [
            "Blueprint compiles with no fatal errors",
            "All referenced nodes/classes/assets resolve",
            "No disconnected required execution chain",
            "Graph layout remains readable and native to the existing graph style",
        ],
        "node_changes": [
            {
                "action": "review",
                "node": "existing graph state",
                "reason": "Baseline inspection required before surgical edits",
            }
        ],
        "pin_link_changes": [],
        "graph_patch_candidate": {
            "target_asset": target_asset,
            "target_graph": target_graph,
            "operations": inferred_operations,
            "notes": [
                "These operations are inferred placeholders from natural language and must be reviewed against the live graph snapshot.",
                "The system should block apply if placeholder nodes/pins cannot be resolved during preflight.",
            ],
        },
        "process_detection": process_detection,
        "preflight_checks": [
            "Verify target asset exists",
            "Verify target graph exists",
            "Open and focus target asset/graph before mutation",
            "Focus the planned graph item or insertion region before editing it",
            "Verify referenced nodes/pins exist before applying edits",
            "Verify graph state has not changed since plan generation",
            "Verify insertion point and local layout space are still valid",
            "Capture backup/prototype target before mutation",
            "Block placeholders that do not map to live nodes/pins",
        ]
        + list(edit_intelligence.get("preflight_checks") or []),
        "insertion_strategy": edit_intelligence.get("insertion_strategy") or [],
        "communication_strategy": edit_intelligence.get("communication_strategy") or [],
        "troubleshooting_path": edit_intelligence.get("troubleshooting_path") or [],
        "repair_strategies": edit_intelligence.get("repair_strategies") or [],
        "post_apply_validation": [
            "Compile modified asset and capture warnings/errors",
            "Verify required execution pins and data pins are connected or have valid defaults",
            "Verify no orphaned nodes, invalid references, accidental loops, or unrelated node modifications",
            "Verify new paths are reachable and existing paths remain connected",
            "Verify layout readability and changed comment regions",
            "Reopen asset/graph if possible to confirm changes persist",
        ]
        + list(edit_intelligence.get("validation_matrix") or []),
        "rollback": {
            "strategy": "prototype_or_backup_before_apply",
            "rollback_token": "",
        },
        "preview_ready": True,
        "warnings": [
            "This is a structured rewrite plan preview, not a completed graph mutation.",
            "Direct graph rewrites should only run after target graph verification and explicit confirmation.",
        ],
        "graph_snapshot": graph_snapshot,
    }
