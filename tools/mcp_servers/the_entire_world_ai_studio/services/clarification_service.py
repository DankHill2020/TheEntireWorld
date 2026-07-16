"""Structured clarification policy and deterministic rendering.

Clarification is not the same problem as model reasoning. When routing already
knows the intent, target, missing slots, choices, and validation constraints, a
template can ask the user for the missing value without invoking a large model.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from engine.request_context import RequestContext


SLOT_CLARIFICATION = "slot"
SEMANTIC_CLARIFICATION = "semantic"
CONFIRMATION = "confirmation"

APPROVAL_WORDS = {"yes", "y", "yeah", "yep", "yea", "yee", "ok", "okay", "approve", "approved", "confirm", "proceed", "go", "go ahead", "continue", "do it"}
CANCEL_WORDS = {"no", "n", "cancel", "deny", "denied", "reject", "stop", "never mind", "nevermind", "do not", "don't", "dont"}


@dataclass
class ClarificationSlot:
    name: str
    label: str = ""
    expected_type: str = ""
    multiple: bool = False
    choices: list[Any] = field(default_factory=list)
    recommended_choice: Any = None
    default_value: Any = None
    inferred_value: Any = None
    inferred_source: str = ""
    required_reason: str = ""
    confidence: float = 0.0
    why_default: str = ""
    auto_accept_threshold: float = 1.0
    control_type: str = ""
    choice_provider_id: str = ""
    provider_filters: dict[str, Any] = field(default_factory=dict)
    refresh_policy: str = "manual"
    cache_seconds: float = 0.0
    context_dependencies: list[str] = field(default_factory=list)
    stale_values_may_execute: bool = False
    can_resolve_automatically: bool = False
    context_source: str = ""
    validation_constraints: dict[str, Any] = field(default_factory=dict)
    examples: list[Any] = field(default_factory=list)
    free_text_allowed: bool = True
    can_use_default: bool = False
    requires_confirmation: bool = False
    resolved_value: Any = None
    state: str = "unresolved"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClarificationRequest:
    kind: str
    intent: str = ""
    target: str = ""
    execution_environment: str = ""
    slots: list[ClarificationSlot] = field(default_factory=list)
    route_decision: dict[str, Any] = field(default_factory=dict)
    execution_request: dict[str, Any] = field(default_factory=dict)
    dispatch_result: dict[str, Any] = field(default_factory=dict)
    confirmation: dict[str, Any] = field(default_factory=dict)
    alternatives: list[Any] = field(default_factory=list)
    reason: str = ""
    model_tier_policy: str = "deterministic"
    rendering_mechanism: str = "deterministic"
    ui_controls: list[dict[str, Any]] = field(default_factory=list)
    resumable: bool = True

    def unresolved_slots(self) -> list[ClarificationSlot]:
        return [slot for slot in self.slots if slot.state in {"unresolved", "confirm"}]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["slots"] = [slot.to_dict() for slot in self.slots]
        payload["unresolved_slot_names"] = [slot.name for slot in self.unresolved_slots()]
        return payload


@dataclass
class ClarificationRenderResult:
    text: str
    request: ClarificationRequest
    model_tier_policy: str
    rendering_mechanism: str
    pending_state: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "clarification": self.request.to_dict(),
            "clarification_type": self.request.kind,
            "clarification_model_tier": self.model_tier_policy,
            "clarification_rendering": self.rendering_mechanism,
            "pending_clarification": self.pending_state,
            "ui_controls": list(self.request.ui_controls),
        }


def slot_label(name: str) -> str:
    labels = {
        "execution_environment": "execution environment",
        "active_project": "project",
        "project_index": "project index",
        "dcc_connection": "DCC connection",
        "callable": "function",
        "callable_disambiguation": "function",
        "asset_path": "asset path",
        "target_asset": "target asset",
        "target_graph": "graph",
        "graph_operations": "graph operation",
        "skeleton_path": "skeleton",
        "world": "Unreal world",
        "selected_actor": "selected actor",
        "selected_object": "selected object",
        "workflow_graph": "workflow graph",
        "mutation_scope": "mutation scope",
    }
    return labels.get(name, name.replace("_", " "))


def expected_type_for_slot(name: str, environment: str = "") -> str:
    if name in {"execution_environment"}:
        return "execution_host"
    if name in {"asset_path", "target_asset"}:
        return "unreal.AssetPath" if environment == "unreal" else "file_or_asset_path"
    if name == "target_graph":
        return "unreal.GraphName" if environment == "unreal" else "graph_name"
    if name == "graph_operations":
        return "unreal.GraphOperation"
    if name in {"skeleton_path"}:
        return "unreal.Skeleton"
    if name in {"world"}:
        return "unreal.World"
    if name in {"selected_actor"}:
        return "unreal.Actor"
    if name in {"selected_object"}:
        return "dcc.Object"
    if name in {"callable", "callable_disambiguation"}:
        return "callable"
    if name.endswith("_path"):
        return "path"
    return "value"


def choice_provider_for_slot(name: str, environment: str = "", *, decision: dict[str, Any] | None = None, request: dict[str, Any] | None = None) -> str:
    if name == "execution_environment":
        return "operation.memory"
    if name in {"callable", "callable_disambiguation"}:
        return "project.callables"
    if name in {"target_symbol", "symbol"}:
        return "project.symbol_search"
    if name in {"target_file", "file", "output_path"}:
        return "project.files"
    if environment == "unreal":
        if name in {"asset_path", "target_asset"}:
            return "unreal.assets"
        if name == "graph_operations":
            return "unreal.operations"
        if name in {"skeleton", "skeleton_path"}:
            return "unreal.skeletons"
        if name in {"mesh", "mesh_path"}:
            return "unreal.meshes"
        if name in {"operation", "callable"}:
            return "unreal.operations"
    return ""


def control_type_for_slot(name: str, environment: str = "", *, has_choices: bool = False, provider_id: str = "") -> str:
    if name == "execution_environment":
        return "choice"
    if provider_id and provider_id != "operation.memory":
        return "searchable_select"
    if environment == "unreal" and name == "target_graph":
        return "choice"
    if environment == "unreal" and name == "graph_operations":
        return "searchable_select"
    if has_choices:
        return "choice"
    if name.startswith("include_") or name in {"overwrite", "recursive", "save_after_execution"}:
        return "toggle"
    if name in {"frame", "count", "timeout", "threshold", "index"}:
        return "numeric"
    if environment == "unreal" and name.endswith("_path"):
        return "asset_picker"
    return "text"


def provider_filters_for_slot(name: str, *, decision: dict[str, Any] | None = None, request: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = decision or {}
    request = request or {}
    if name in {"callable", "callable_disambiguation"}:
        return {"symbol_kinds": ["function", "method"], "query": request.get("callable_name") or decision.get("callable_name") or decision.get("target_identifier") or ""}
    if name in {"target_symbol", "symbol"}:
        return {"query": decision.get("target_identifier") or "", "scope": "project"}
    if name in {"target_file", "file"}:
        return {"query": decision.get("target_identifier") or "", "limit": 80}
    if name == "target_asset":
        prompt = str(request.get("original_prompt") or decision.get("target_identifier") or "")
        return {"query": prompt, "limit": 80}
    if name == "graph_operations":
        prompt = str(request.get("original_prompt") or decision.get("target_identifier") or "")
        return {"query": prompt, "limit": 40}
    return {}


def refresh_policy_for_provider(provider_id: str) -> str:
    if provider_id.startswith("unreal.") or provider_id.startswith("maya.") or provider_id.startswith("blender."):
        return "host_reconnect_or_manual"
    if provider_id.startswith("project."):
        return "index_or_project_change"
    if provider_id == "operation.memory":
        return "manual"
    return "manual"


def cache_seconds_for_provider(provider_id: str) -> float:
    if provider_id.startswith("unreal.") or provider_id.startswith("maya."):
        return 5.0
    if provider_id.startswith("project."):
        return 30.0
    return 0.0


def context_dependencies_for_provider(provider_id: str) -> list[str]:
    if provider_id.startswith("unreal."):
        return ["unreal_connection", "host_selection"]
    if provider_id.startswith("maya."):
        return ["maya_connection", "host_selection"]
    if provider_id.startswith("project."):
        return ["project_root", "project_index"]
    if provider_id == "operation.memory":
        return ["operation_memory"]
    return []


def clarify_kind_for_route(decision: dict[str, Any], missing_slots: list[str]) -> str:
    if not missing_slots:
        return SEMANTIC_CLARIFICATION
    intent = str(decision.get("intent_category") or decision.get("route") or "").lower()
    if intent in {"chat", "general"}:
        return SEMANTIC_CLARIFICATION
    if any(slot in {"feature_behavior", "improvement_goal", "optimization_target"} for slot in missing_slots):
        return SEMANTIC_CLARIFICATION
    return SLOT_CLARIFICATION


def model_tier_for_clarification(request: ClarificationRequest) -> str:
    if request.kind == CONFIRMATION:
        return "deterministic"
    if request.kind == SLOT_CLARIFICATION:
        unresolved = request.unresolved_slots()
        if all(slot.choices or slot.expected_type or slot.free_text_allowed for slot in unresolved):
            return "deterministic"
        return "small_local"
    # Semantic ambiguity can still start local; enterprise is not inherited from
    # the eventual task and should only be chosen by a later explicit policy.
    return "larger_local"


def build_slots(
    names: list[str],
    *,
    decision: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    context: RequestContext | None = None,
) -> list[ClarificationSlot]:
    decision = decision or {}
    request = request or {}
    environment = str(request.get("execution_environment") or decision.get("execution_environment") or decision.get("host") or "")
    slots: list[ClarificationSlot] = []
    for name in names:
        choices = _choices_for_slot(name, decision=decision, request=request, context=context)
        provider_id = choice_provider_for_slot(name, environment, decision=decision, request=request)
        default_value = None
        optional = request.get("argument_schema", {}).get("optional") if isinstance(request.get("argument_schema"), dict) else {}
        if isinstance(optional, dict):
            default_value = optional.get(name)
        slots.append(
            ClarificationSlot(
                name=name,
                label=slot_label(name),
                expected_type=expected_type_for_slot(name, environment),
                choices=choices,
                default_value=default_value,
                required_reason=_reason_for_slot(name, request or decision),
                control_type=control_type_for_slot(name, environment, has_choices=bool(choices), provider_id=provider_id),
                choice_provider_id=provider_id,
                provider_filters=provider_filters_for_slot(name, decision=decision, request=request),
                refresh_policy=refresh_policy_for_provider(provider_id),
                cache_seconds=cache_seconds_for_provider(provider_id),
                context_dependencies=context_dependencies_for_provider(provider_id),
                free_text_allowed=not bool(choices),
                can_use_default=default_value is not None,
                context_source=_context_source_for_slot(name, environment),
            )
        )
    return slots


def build_slot_clarification(
    *,
    decision: dict[str, Any],
    context: RequestContext,
    missing_slots: list[str],
    execution_request: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    reason: str = "",
) -> ClarificationRenderResult:
    slots = build_slots(missing_slots, decision=decision, request=execution_request or {}, context=context)
    resolved, unresolved = resolve_slots_from_context(slots, context=context, decision=decision, request=execution_request or {})
    inferred_values = _infer_slot_values_from_chat_text(
        {
            "execution_request": execution_request or {},
            "accepted_value_schemas": {
                slot.name: {
                    "expected_type": slot.expected_type,
                    "choices": list(slot.choices),
                    "free_text_allowed": slot.free_text_allowed,
                    "multiple": slot.multiple,
                }
                for slot in unresolved
            },
        },
        [slot.to_dict() for slot in unresolved],
        context.text,
    )
    if inferred_values:
        for slot in unresolved:
            if slot.name in inferred_values:
                slot.inferred_value = inferred_values[slot.name]
                slot.default_value = inferred_values[slot.name]
                slot.inferred_source = "prompt"
                slot.confidence = 0.72
                slot.why_default = "Inferred from the chat prompt. Review before proceeding."
                slot.state = "confirm"
    target = str((execution_request or {}).get("callable_name") or decision.get("callable_name") or decision.get("target_identifier") or "")
    request = ClarificationRequest(
        kind=clarify_kind_for_route(decision, [slot.name for slot in unresolved] or list(missing_slots or [])),
        intent=str(decision.get("intent_category") or decision.get("route") or ""),
        target=target,
        execution_environment=str((execution_request or {}).get("execution_environment") or decision.get("host") or ""),
        slots=resolved + unresolved,
        route_decision=decision,
        execution_request=execution_request or {},
        dispatch_result=dispatch_result or {},
        reason=reason,
    )
    request.model_tier_policy = model_tier_for_clarification(request)
    request.rendering_mechanism = "deterministic" if request.model_tier_policy == "deterministic" else request.model_tier_policy
    request.ui_controls = ui_controls_for_request(request)
    text = render_clarification(request)
    return ClarificationRenderResult(
        text=text,
        request=request,
        model_tier_policy=request.model_tier_policy,
        rendering_mechanism=request.rendering_mechanism,
        pending_state=pending_state_for_request(request),
    )


def build_confirmation(
    *,
    decision: dict[str, Any],
    context: RequestContext,
    execution_request: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> ClarificationRenderResult:
    confirmation = (dispatch_result or {}).get("confirmation_request") or {}
    target = str((execution_request or {}).get("callable_name") or decision.get("callable_name") or decision.get("target_identifier") or "")
    request = ClarificationRequest(
        kind=CONFIRMATION,
        intent=str(decision.get("intent_category") or decision.get("route") or ""),
        target=target,
        execution_environment=str((execution_request or {}).get("execution_environment") or decision.get("host") or ""),
        slots=[],
        route_decision=decision,
        execution_request=execution_request or {},
        dispatch_result=dispatch_result or {},
        confirmation=confirmation,
        reason="Permission is required before performing the resolved operation.",
        model_tier_policy="deterministic",
        rendering_mechanism="deterministic",
    )
    request.ui_controls = [
        {"type": "button", "value": "confirm", "label": "Approve"},
        {"type": "button", "value": "cancel", "label": "Deny"},
    ]
    text = render_confirmation(request, context)
    return ClarificationRenderResult(
        text=text,
        request=request,
        model_tier_policy="deterministic",
        rendering_mechanism="deterministic",
        pending_state=pending_state_for_request(request),
    )


def resolve_slots_from_context(
    slots: list[ClarificationSlot],
    *,
    context: RequestContext,
    decision: dict[str, Any],
    request: dict[str, Any],
) -> tuple[list[ClarificationSlot], list[ClarificationSlot]]:
    resolved: list[ClarificationSlot] = []
    unresolved: list[ClarificationSlot] = []
    extras = context.extras or {}
    operation_memory = extras.get("operation_memory") or extras.get("active_operation_memory") or {}
    remembered_slots = operation_memory.get("resolved_slots") if isinstance(operation_memory, dict) else {}
    remembered_slots = remembered_slots if isinstance(remembered_slots, dict) else {}
    for slot in slots:
        value = None
        source = ""
        if slot.name == "execution_environment":
            remembered_host = operation_memory.get("selected_host") if isinstance(operation_memory, dict) else ""
            value = decision.get("host") or request.get("execution_environment")
            source = "route"
            if not _has_resolved_value(value) and remembered_host:
                value = remembered_host
                source = "operation_memory"
        elif slot.name in {"target_file", "file"} and context.current_file_path:
            value = context.current_file_path
            source = "active_file"
        elif slot.name in {"selected_object", "selected_actor"}:
            selection = extras.get("selected_objects") or extras.get("selected_actors")
            if selection:
                value = selection
                source = "active_selection"
        elif slot.name in extras:
            value = extras.get(slot.name)
            source = "request_context"
        elif slot.name in remembered_slots:
            value = remembered_slots.get(slot.name)
            source = "operation_memory"
        if _has_resolved_value(value):
            slot.resolved_value = value
            slot.inferred_value = value
            slot.inferred_source = source
            slot.confidence = 0.95 if source == "operation_memory" else 0.9
            slot.why_default = f"Resolved from {source.replace('_', ' ')}."
            slot.can_resolve_automatically = True
            slot.state = "resolved"
            resolved.append(slot)
        else:
            if slot.name == "template":
                try:
                    from services.unreal.unreal_operation_service import infer_unreal_prototype_template
                    inferred = infer_unreal_prototype_template(context.text)
                    slot.recommended_choice = inferred
                    slot.default_value = inferred
                    slot.inferred_value = inferred
                except Exception:
                    pass
            elif slot.name == "asset_path":
                folders = extras.get("selected_folders")
                if folders and isinstance(folders, list):
                    folder = folders[0].rstrip('/')
                    slot.default_value = f"{folder}/"
                    slot.inferred_value = slot.default_value
                    slot.why_default = "Inferred from active Content Browser folder."
            elif slot.name == "asset_name":
                target = str(decision.get("target_identifier") or decision.get("callable_name") or "")
                target_name = "NewAsset"
                if "niagara" in target.lower() or "emitter" in context.text.lower():
                    target_name = "NE_NewEmitter"
                elif "blueprint" in target.lower() or "character" in context.text.lower():
                    target_name = "BP_NewCharacter"
                slot.default_value = target_name
                slot.inferred_value = target_name
                slot.why_default = "Default asset name for this type."
            unresolved.append(slot)
    return resolved, unresolved


def _has_resolved_value(value: Any) -> bool:
    if value in (None, "", []):
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "missing", "none", "null"}:
        return False
    return True


def render_clarification(request: ClarificationRequest) -> str:
    unresolved = request.unresolved_slots()
    if request.kind == SEMANTIC_CLARIFICATION:
        target = f" for `{request.target}`" if request.target else ""
        return f"Could you clarify what kind of improvement we are aiming for here{target}? Specifically, should we focus on behavior, performance, readability, usability, or architectural changes?"
    if not unresolved:
        return "I've successfully gathered the missing details from your current workspace. Shall we go ahead and proceed?"
    inferred = [slot for slot in unresolved if _has_resolved_value(slot.inferred_value)]
    if inferred and len(inferred) == len(unresolved):
        lines = ["I inferred the needed context from your prompt. Please review this draft before I continue:"]
        for slot in inferred:
            lines.append(f"- {slot.label}: `{choice_label(slot.inferred_value)}`")
        lines.append("Reply approve/yes to continue, deny/cancel to stop, or type a correction in Ask Anything.")
        return "\n".join(lines)
    if len(unresolved) == 1:
        return render_slot_question(request, unresolved[0])
    labels = ", ".join(slot.label for slot in unresolved)
    target = f" for `{request.target}`" if request.target else ""
    if request.execution_environment == "unreal" and any(slot.name in {"target_asset", "target_graph", "graph_operations"} for slot in unresolved):
        return (
            "I need to confirm the Unreal graph target before editing. "
            "Pick the target asset, graph, and graph operation below. "
            "Use the Ask Anything line only if you want to add context before approving."
        )
    return f"To get this started, I'll need a couple of details first: {labels}{target}. Could you fill me in on those?"


def render_slot_question(request: ClarificationRequest, slot: ClarificationSlot) -> str:
    target = request.target or "this"
    if slot.name == "execution_environment":
        choices = slot.choices or ["Maya", "Unreal", "Blender"]
        return f"Which host application would you like me to run `{target}` in? I can target {format_choices(choices)}."
    if slot.name in {"callable", "callable_disambiguation"}:
        if slot.choices:
            return f"Which function should we target for `{target}`? Here are the matches I found: {format_choices(slot.choices)}."
        return f"Which function would you like to target for `{target}`?"
    if request.execution_environment == "unreal" and slot.name in {"target_asset", "target_graph", "graph_operations"}:
        if slot.choices:
            return f"Which {slot.label} should I use for the Unreal graph edit?"
        return f"Which {slot.label} should I use for the Unreal graph edit?"
    if slot.choices:
        return f"Which {slot.label} would you prefer to use: {format_choices(slot.choices)}?"
    if slot.can_use_default:
        return f"Would you like to proceed with the default {slot.label} (`{slot.default_value}`) for `{target}`, or specify a custom one?"
    if slot.expected_type == "description":
        return f"Could you let me know what the {slot.label} should be?"
    return f"Could you specify the {slot.label} you'd like to use for `{target}`?"


def render_confirmation(request: ClarificationRequest, context: RequestContext) -> str:
    target = request.target or request.intent or "this operation"
    scope = request.confirmation.get("mutation_scope") or request.execution_request.get("mutation_scope") or "the current context"
    risk = request.confirmation.get("risk_level") or request.execution_request.get("risk_level") or "unknown"
    if request.confirmation.get("operation") == "unreal_graph_patch":
        asset = request.confirmation.get("target_asset") or "target asset"
        graph = request.confirmation.get("target_graph") or "target graph"
        preview = request.confirmation.get("preview") or {}
        count = preview.get("operation_count") or "planned"
        return (
            f"I'm ready to apply an Unreal graph patch to `{asset}` / `{graph}`.\n\n"
            f"Planned operations: `{count}`\n"
            f"This will modify {scope} (Risk level: {risk}). Use Approve or Deny below."
        )
    
    args_lines = []
    exec_req = request.execution_request or {}
    keyword_args = exec_req.get("keyword_args") or request.route_decision.get("keyword_args") or {}
    positional_args = exec_req.get("positional_args") or request.route_decision.get("positional_args") or []
    
    if positional_args:
        args_lines.append("Positional Arguments:")
        for arg in positional_args:
            args_lines.append(f"  - `{repr(arg)}`")
    if keyword_args:
        args_lines.append("Arguments:")
        for key, val in keyword_args.items():
            args_lines.append(f"  - `{key}`: `{repr(val)}`")
            
    args_block = "\n" + "\n".join(args_lines) if args_lines else ""
    return f"I'm ready to execute `{target}`.{args_block}\n\nThis will modify {scope} (Risk level: {risk}). Use Approve or Deny below."


def ui_controls_for_request(request: ClarificationRequest) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for slot in request.unresolved_slots():
        if slot.choices:
            controls.append(
                {
                    "type": slot.control_type or "choice",
                    "slot": slot.name,
                    "label": slot.label,
                    "choices": list(slot.choices),
                    "multiple": slot.multiple,
                    "free_text_allowed": slot.free_text_allowed,
                    "choice_provider_id": slot.choice_provider_id,
                    "provider_filters": dict(slot.provider_filters),
                    "refresh_policy": slot.refresh_policy,
                    "cache_seconds": slot.cache_seconds,
                    "context_dependencies": list(slot.context_dependencies),
                    "state": "loaded",
                    "recommended_choice": slot.recommended_choice,
                    "default_value": slot.default_value,
                    "inferred_value": slot.inferred_value,
                }
            )
        elif slot.expected_type in {"path", "file_or_asset_path", "unreal.AssetPath"}:
            controls.append({
                "type": slot.control_type or ("asset_picker" if slot.expected_type == "unreal.AssetPath" else "file_picker"),
                "slot": slot.name,
                "label": slot.label,
                "choice_provider_id": slot.choice_provider_id,
                "provider_filters": dict(slot.provider_filters),
                "refresh_policy": slot.refresh_policy,
                "cache_seconds": slot.cache_seconds,
                "context_dependencies": list(slot.context_dependencies),
                "state": "idle" if slot.choice_provider_id else "manual",
                "recommended_choice": slot.recommended_choice,
                "default_value": slot.default_value,
                "inferred_value": slot.inferred_value,
            })
        elif slot.expected_type in {"execution_host"}:
            controls.append({
                "type": slot.control_type or "dropdown",
                "slot": slot.name,
                "label": slot.label,
                "choices": ["maya", "unreal", "blender", "motionbuilder"],
                "choice_provider_id": slot.choice_provider_id,
                "provider_filters": dict(slot.provider_filters),
                "refresh_policy": slot.refresh_policy,
                "cache_seconds": slot.cache_seconds,
                "context_dependencies": list(slot.context_dependencies),
                "state": "loaded",
                "recommended_choice": slot.recommended_choice,
                "default_value": slot.default_value,
                "inferred_value": slot.inferred_value,
            })
        else:
            controls.append({
                "type": slot.control_type or "text",
                "slot": slot.name,
                "label": slot.label,
                "choice_provider_id": slot.choice_provider_id,
                "provider_filters": dict(slot.provider_filters),
                "refresh_policy": slot.refresh_policy,
                "cache_seconds": slot.cache_seconds,
                "context_dependencies": list(slot.context_dependencies),
                "state": "idle" if slot.choice_provider_id else "manual",
                "recommended_choice": slot.recommended_choice,
                "default_value": slot.default_value,
                "inferred_value": slot.inferred_value,
            })
    return controls


def pending_state_for_request(request: ClarificationRequest) -> dict[str, Any]:
    return {
        "kind": request.kind,
        "resumable": request.resumable,
        "target": request.target,
        "execution_environment": request.execution_environment,
        "route_decision": request.route_decision,
        "execution_request": request.execution_request,
        "unresolved_slots": [slot.to_dict() for slot in request.unresolved_slots()],
        "accepted_value_schemas": {
            slot.name: {
                "expected_type": slot.expected_type,
                "choices": list(slot.choices),
                "free_text_allowed": slot.free_text_allowed,
                "multiple": slot.multiple,
            }
            for slot in request.unresolved_slots()
        },
        "confirmation": request.confirmation,
    }


def bind_clarification_response(pending_state: dict[str, Any], answer: str) -> dict[str, Any]:
    """Bind a short user reply to the pending clarification contract.

    This is intentionally conservative: it only accepts answers that match the
    stored slot schema, confirmation words, or allowed free text. A caller can
    re-route only when this returns ``accepted=False`` with ``reason='reroute'``.
    """
    text = str(answer or "").strip()
    lower = text.lower()
    if lower in CANCEL_WORDS:
        return {"accepted": True, "action": "cancel", "clear_pending": True}
    if not pending_state or not pending_state.get("resumable", True):
        return {"accepted": False, "reason": "stale_or_not_resumable", "reroute": True}
    if pending_state.get("kind") == CONFIRMATION:
        if lower in APPROVAL_WORDS or lower in {"run", "execute"}:
            route_decision = dict(pending_state.get("route_decision") or {})
            execution_request = dict(pending_state.get("execution_request") or {})
            route_decision["approved"] = True
            route_decision["requires_confirmation"] = False
            execution_request["approved"] = True
            execution_request["requires_confirmation"] = False
            return {
                "accepted": True,
                "action": "confirm",
                "clear_pending": True,
                "route_decision": route_decision,
                "execution_request": execution_request,
            }
        if lower in CANCEL_WORDS:
            return {"accepted": True, "action": "cancel", "clear_pending": True}
        return {"accepted": False, "reason": "confirmation_expected", "message": "Reply Approve/Yes to continue, or Deny/Cancel to stop."}
    slots = list(pending_state.get("unresolved_slots") or [])
    if lower in APPROVAL_WORDS and slots:
        approved_values = _approval_values_from_inferred_slots(slots)
        if approved_values:
            return _bind_slot_values(pending_state, slots, approved_values)
        return {
            "accepted": False,
            "reason": "approval_without_inferred_values",
            "message": "I do not have enough inferred context yet. Type the missing context in chat, ideally using @ to choose known assets or symbols.",
        }
    structured_values = _parse_structured_slot_values(text)
    if structured_values and slots:
        return _bind_slot_values(pending_state, slots, structured_values)
    if len(slots) != 1:
        inferred_values = _infer_slot_values_from_chat_text(pending_state, slots, text)
        if inferred_values:
            return _bind_slot_values(pending_state, slots, inferred_values)
        return {"accepted": False, "reason": "multiple_slots_require_structured_ui", "message": "Please answer the requested fields."}
    slot = slots[0]
    return _bind_slot_values(pending_state, [slot], {str(slot.get("name") or ""): text})


def _approval_values_from_inferred_slots(slots: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for slot in slots:
        slot_name = str(slot.get("name") or "")
        value = slot.get("inferred_value")
        if value in (None, "", []):
            value = slot.get("default_value")
        if value in (None, "", []):
            value = slot.get("resolved_value")
        if value in (None, "", []):
            return {}
        values[slot_name] = value
    return values


def _parse_structured_slot_values(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    values = parsed.get("slots") if isinstance(parsed.get("slots"), dict) else parsed
    return dict(values) if isinstance(values, dict) else {}


def _bind_slot_values(pending_state: dict[str, Any], slots: list[dict[str, Any]], values_by_slot: dict[str, Any]) -> dict[str, Any]:
    execution_request = dict(pending_state.get("execution_request") or {})
    route_decision = dict(pending_state.get("route_decision") or {})
    keyword_args = dict(execution_request.get("keyword_args") or route_decision.get("keyword_args") or {})
    accepted: dict[str, Any] = {}
    remaining: list[str] = []
    for slot in slots:
        slot_name = str(slot.get("name") or "")
        if slot_name not in values_by_slot:
            existing_value = keyword_args.get(slot_name)
            if existing_value not in (None, "", []):
                accepted[slot_name] = existing_value
            else:
                remaining.append(slot_name)
            continue
        schema = (pending_state.get("accepted_value_schemas") or {}).get(slot_name, {})
        choices = list(schema.get("choices") or slot.get("choices") or [])
        raw_value = values_by_slot.get(slot_name)
        value = _match_choice_value(raw_value, choices)
        if value is None and not choices and schema.get("free_text_allowed", True):
            value = raw_value
        if value is None:
            return {
                "accepted": False,
                "reason": "invalid_slot_value",
                "slot": slot_name,
                "message": f"Please choose one of: {format_choices(choices)}.",
            }
        if slot_name == "execution_environment":
            host_value = str(value).strip().lower()
            route_decision["host"] = host_value
            route_decision["execution_environment"] = host_value
            execution_request["execution_environment"] = host_value
        else:
            keyword_args[slot_name] = value
        accepted[slot_name] = value
    if remaining:
        return {
            "accepted": False,
            "reason": "missing_structured_slot_values",
            "message": "Choose values for every requested field, then press Approve.",
            "missing_slots": remaining,
        }
    execution_request["keyword_args"] = keyword_args
    route_decision["keyword_args"] = keyword_args
    accepted_names = set(accepted)
    route_decision["missing_info"] = [name for name in route_decision.get("missing_info") or [] if name not in accepted_names]
    execution_request["missing_slots"] = [name for name in execution_request.get("missing_slots") or [] if name not in accepted_names]
    return {
        "accepted": True,
        "action": "resume",
        "values": accepted,
        "route_decision": route_decision,
        "execution_request": execution_request,
        "clear_pending": True,
    }


def _infer_slot_values_from_chat_text(pending_state: dict[str, Any], slots: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """Infer missing slot values from a natural chat clarification.

    This keeps clarification prompt-first: users can say "BP_LesterPhoenix anim
    graph" in chat instead of typing into per-slot widgets.
    """
    source_text = " ".join(
        part
        for part in (
            str(((pending_state.get("execution_request") or {}).get("original_prompt") or "")),
            str(text or ""),
        )
        if part
    )
    lower = source_text.lower()
    values: dict[str, Any] = {}
    schemas = pending_state.get("accepted_value_schemas") or {}
    for slot in slots:
        slot_name = str(slot.get("name") or "")
        schema = schemas.get(slot_name, {})
        choices = list(schema.get("choices") or slot.get("choices") or [])
        matched = _match_choice(source_text, choices) if choices else None
        if matched is not None:
            values[slot_name] = matched
            continue
        if slot_name == "target_graph":
            if re.search(r"\banim(?:ation)?\s*graph\b|\banimgraph\b", lower):
                values[slot_name] = "AnimGraph"
            elif re.search(r"\bevent\s*graph\b|\beventgraph\b", lower):
                values[slot_name] = "EventGraph"
            elif re.search(r"\bconstruction\s*script\b|\bconstructionscript\b", lower):
                values[slot_name] = "ConstructionScript"
        elif slot_name == "target_asset":
            path_match = re.search(r"(/Game/[A-Za-z0-9_./-]+)", source_text)
            if path_match:
                values[slot_name] = path_match.group(1).rstrip(".,;:)")
            else:
                bp_match = re.search(r"\b((?:BP|ABP|BPC)_[A-Za-z0-9_]+)\b", source_text)
                if bp_match:
                    values[slot_name] = bp_match.group(1)
        elif slot_name == "graph_operations":
            if re.search(r"\b(inspect|find|identify|report|analy[sz]e|review)\b", lower):
                values[slot_name] = "inspect_graph"
            elif re.search(r"\b(add|create|implement|insert|connect|wire|modify|edit|fix)\b", lower):
                values[slot_name] = "semantic_graph_edit"
    return values


def _match_choice_value(answer: Any, choices: list[Any]) -> Any:
    if not choices:
        return None
    for choice in choices:
        if answer == choice:
            return choice.get("value") if isinstance(choice, dict) and "value" in choice else choice
    if isinstance(answer, (dict, list)):
        answer_text = json.dumps(answer, sort_keys=True, default=str)
    else:
        answer_text = str(answer)
    return _match_choice(answer_text, choices)


def format_choices(choices: list[Any]) -> str:
    labels = [choice_label(choice) for choice in choices]
    if len(labels) <= 2:
        return " or ".join(labels)
    return ", ".join(labels[:-1]) + ", or " + labels[-1]


def choice_label(value: Any) -> str:
    if isinstance(value, dict):
        raw = value.get("label") or value.get("name") or value.get("path") or value.get("value") or str(value)
    else:
        raw = str(value)
    raw = raw.strip()
    if "/" in raw:
        raw = raw.rstrip("/").split("/")[-1]
    return raw or "value"


def _match_choice(answer: str, choices: list[Any]) -> Any:
    if not choices:
        return None
    answer_lower = answer.strip().lower()
    for choice in choices:
        label = choice_label(choice)
        raw_values = {label.lower(), str(choice).lower()}
        if isinstance(choice, dict):
            for key in ("value", "name", "path", "operation", "id", "key"):
                if choice.get(key) not in (None, ""):
                    raw_values.add(str(choice.get(key)).lower())
            try:
                raw_values.add(json.dumps(choice, sort_keys=True, default=str).lower())
            except Exception:
                pass
        if answer_lower in raw_values:
            return choice.get("value") if isinstance(choice, dict) and "value" in choice else choice
    for choice in choices:
        label = choice_label(choice)
        raw = str(choice)
        if answer_lower and (
            answer_lower in label.lower()
            or answer_lower in raw.lower()
            or label.lower() in answer_lower
            or raw.lower() in answer_lower
        ):
            return choice.get("value") if isinstance(choice, dict) and "value" in choice else choice
    return None


def _choices_for_slot(
    name: str,
    *,
    decision: dict[str, Any],
    request: dict[str, Any],
    context: RequestContext | None,
) -> list[Any]:
    choices = []
    candidates = decision.get("alternatives") or decision.get("choices") or request.get("choices") or []
    if name == "execution_environment":
        return ["Maya", "Unreal", "Blender"]
    if name in {"callable_disambiguation", "callable"}:
        schema = request.get("argument_schema") or {}
        matches = schema.get("matches") if isinstance(schema, dict) else []
        choices = [item.get("qualname") or item.get("name") or item for item in matches or candidates]
    elif name == "template":
        try:
            from services.unreal.unreal_operation_service import UNREAL_PROTOTYPE_FEATURE_ALIASES
            choices = list(UNREAL_PROTOTYPE_FEATURE_ALIASES.keys())
        except Exception:
            choices = []
    elif name == "target_graph":
        choices = [
            {"value": "EventGraph", "label": "Event Graph"},
            {"value": "AnimGraph", "label": "Anim Graph"},
            {"value": "ConstructionScript", "label": "Construction Script"},
            {"value": "FunctionGraph", "label": "Function Graph"},
        ]
    elif name in {"world"}:
        extras = (context.extras if context else {}) or {}
        choices = list(extras.get("loaded_worlds") or extras.get("unreal_worlds") or [])
    elif name in {"asset_path", "skeleton_path"}:
        extras = (context.extras if context else {}) or {}
        choices = list(extras.get("asset_paths") or extras.get("unreal_assets") or [])
    else:
        choices = list(candidates or [])
    return [choice for choice in choices if choice not in (None, "")]


def _reason_for_slot(name: str, source: dict[str, Any]) -> str:
    if name == "execution_environment":
        return "The callable cannot run until a host application is selected."
    if name in {"callable", "callable_disambiguation"}:
        return "The dispatcher needs one concrete callable before execution."
    if name.endswith("_path"):
        return "The operation requires a concrete path."
    return "The operation requires this value before execution."


def _context_source_for_slot(name: str, environment: str) -> str:
    if environment == "unreal" and name in {"world", "asset_path", "skeleton_path", "selected_actor"}:
        return "unreal_live_context"
    if environment == "maya" and name in {"selected_object"}:
        return "maya_live_context"
    if name in {"callable", "callable_disambiguation"}:
        return "project_symbol_index"
    return "route_context"


def build_problem_formulation_clarification(
    *,
    prompt: str,
    decision: dict[str, Any] | None = None,
    context: RequestContext,
) -> ClarificationRenderResult | None:
    """Ask only for unknowns that block an adequate problem formulation."""
    decision = dict(decision or {})
    try:
        from services.problem_formulation_service import build_problem_formulation
        formulation = build_problem_formulation(
            prompt,
            decision,
            context={
                "active_file": context.current_file_path,
                "host": decision.get("host") or "",
                "conversation_entities": (context.extras or {}).get("conversation_entities") or {},
                "context_momentum": (context.extras or {}).get("context_momentum") or {},
            },
        )
    except Exception:
        return None

    if not formulation.requires_clarification:
        return None

    slots: list[ClarificationSlot] = []
    for index, unknown in enumerate(formulation.blocking_unknowns):
        name = f"problem_unknown_{index + 1}"
        if "file reference" in unknown.lower():
            name = "target_file"
        elif "target" in unknown.lower():
            name = "target_symbol"
        slots.append(
            ClarificationSlot(
                name=name,
                label=slot_label(name),
                expected_type=expected_type_for_slot(name, formulation.scope),
                required_reason=unknown,
                control_type=control_type_for_slot(name, formulation.scope),
                choice_provider_id=choice_provider_for_slot(
                    name,
                    formulation.scope,
                    decision=decision,
                    request={"original_prompt": prompt},
                ),
                provider_filters=provider_filters_for_slot(
                    name,
                    decision=decision,
                    request={"original_prompt": prompt},
                ),
                free_text_allowed=True,
                context_source="problem_formulation",
            )
        )

    request = ClarificationRequest(
        kind=SEMANTIC_CLARIFICATION,
        intent="problem_formulation",
        target=formulation.subject,
        execution_environment=str(decision.get("host") or ""),
        slots=slots,
        route_decision={
            **decision,
            "problem_formulation": formulation.to_dict(),
        },
        reason=(
            "The system formed the problem before acting, but one or more "
            "unknowns would materially change the plan."
        ),
        model_tier_policy="larger_local",
        rendering_mechanism="deterministic",
    )
    request.ui_controls = ui_controls_for_request(request)

    lines = [
        "I need one detail before I can form the problem correctly:",
        "",
        f"Current interpretation: {formulation.interpreted_problem}",
    ]
    for question in formulation.clarification_questions:
        lines.append(f"- {question}")
    lines.extend([
        "",
        "I have not routed, searched, edited, or executed anything yet.",
    ])
    return ClarificationRenderResult(
        text="\\n".join(lines),
        request=request,
        model_tier_policy=request.model_tier_policy,
        rendering_mechanism=request.rendering_mechanism,
        pending_state=pending_state_for_request(request),
    )
