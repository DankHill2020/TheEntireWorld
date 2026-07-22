"""Synthesize detailed Unreal implementation plans from evidence and techniques."""

from __future__ import annotations

import re
from typing import Any, Iterable


def _feature_name(request: str) -> str:
    text = " ".join(str(request or "").split())
    for pattern in (
        r"\bspecifically\s+for\s+([A-Za-z][A-Za-z0-9_-]+)",
        r"\b(?:build|create|add|implement)\s+(?:an?\s+|the\s+)?([A-Za-z][A-Za-z0-9_-]+)(?:\s+(?:feature|system|ability|mechanic))?",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).replace("_", " ").strip().title()
    return "Prompt Feature"


def _operation_params(
    operation: str,
    context: dict[str, Any],
    request: str,
    step: dict[str, Any],
) -> dict[str, Any]:
    target = str(context.get("target_asset") or "")
    anim_bp = str(context.get("animation_blueprint") or "")
    skeleton = str(context.get("target_skeleton") or context.get("skeleton") or "")
    params: dict[str, Any] = {}
    animation_phase = str(step.get("domain") or "") in {"animation_system", "animation_metadata"}
    blueprint_target = anim_bp if animation_phase and anim_bp else target
    if operation in {"blueprint.scan", "blueprint.compile"}:
        params["asset_path"] = blueprint_target
    elif operation == "assets.inspect":
        params["asset_path"] = target
    elif operation == "semantic_index.query":
        params["query"] = request
    elif operation == "animation.find_compatible":
        params.update({"query": request, "skeleton_path": skeleton})
    elif operation == "animation.create_anim_bp":
        params.update({"skeleton_path": skeleton, "asset_path": "<resolve from project naming convention>"})
    elif operation == "blueprint.add_function":
        title = re.sub(r"[^A-Za-z0-9]+", " ", str(step.get("title") or "Feature Action"))
        params.update(
            {
                "blueprint_path": blueprint_target,
                "function_name": "Handle" + "".join(value.title() for value in title.split()),
            }
        )
    elif operation in {"blueprint.add_node", "blueprint.connect_node_pins"}:
        params.update(
            {
                "blueprint_path": blueprint_target,
                "graph_name": "<resolve from live graph topology>",
            }
        )
    elif operation == "runtime.inject_key":
        params.update({"key_name": "<resolve from prompt input contract>", "pressed": True})
    elif operation == "runtime.inspect_character":
        params.update(
            {
                "character_blueprint_path": target,
                "expected_anim_class_contains": anim_bp.rsplit("/", 1)[-1] if anim_bp else "",
                "property_names": ["CurrentState"],
            }
        )
    try:
        from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

        definition = UNREAL_OPERATIONS.get(operation)
        for required in definition.required if definition else ():
            params.setdefault(str(required), f"<resolve required parameter: {required}>")
    except Exception:
        pass
    return params


def _unresolved_params(params: dict[str, Any]) -> list[str]:
    return [key for key, value in params.items() if not value or str(value).startswith("<resolve")]


def _operation_realization(
    operation: str,
    status: dict[str, Any],
    graph_executor_status: dict[str, Any],
) -> dict[str, Any]:
    if status.get("callable_found"):
        return {
            "kind": "direct_callable",
            "status": "resolved",
            "execution_operation": operation,
            "function": status.get("function") or "",
            "required_evidence": ["operation-specific postcondition readback"],
        }
    namespace = str(operation or "").partition(".")[0]
    graph_namespaces = {
        "animation", "collision", "combat", "input", "movement", "physics", "state"
    }
    if namespace in graph_namespaces and graph_executor_status.get("callable_found"):
        return {
            "kind": "blueprint_graph_spec",
            "status": "pending_graph_spec",
            "execution_operation": "blueprint.apply_graph_spec",
            "function": graph_executor_status.get("function") or "",
            "required_spec": [
                "exact target graph from live topology",
                "exact palette action for every node from reflection or verified project precedent",
                "literal/default value for every authored input pin",
                "explicit execution and data links with unique node ids",
                "operation-specific runtime postconditions",
            ],
            "discovery": [
                "query the semantic project index for equivalent nodes and connected project examples",
                "search live context-filtered Blueprint palette actions when project precedent is absent",
                "probe selected actions on a disposable Blueprint copy to read exact pins and compile status",
                "compare current official Unreal technique guidance when local evidence is incomplete",
                "validate the graph spec on a disposable asset before approving target mutation",
            ],
            "required_evidence": [
                "palette action resolves",
                "all pin values are accepted",
                "all schema links are accepted and read back",
                "Blueprint compiles without errors",
                "the declared runtime outcome passes in PIE",
            ],
        }
    return {
        "kind": "capability_acquisition",
        "status": "missing_callable",
        "execution_operation": "",
        "function": "",
        "required_evidence": ["registered callable", "live postcondition test"],
    }


def _trigger_key(trigger: str) -> str:
    match = re.search(r"\b(SPACEBAR|SPACE|[A-Z0-9])\b\s+input\b|\binput\s+(SPACEBAR|SPACE|[A-Z0-9])\b", str(trigger or ""), re.I)
    return (next((value for value in match.groups() if value), "") if match else "").upper()


def _guard_priority(guards: list[str]) -> tuple[int, str]:
    text = " ".join(str(value) for value in guards).lower()
    if re.search(r"\b(?:climbing|hanging|falling|airborne|attached|active ability)\b", text):
        return 400, "authoritative active-state context"
    if re.search(r"\b(?:obstacles?|ledges?|walls?|surfaces?|targets?|hits?)\b", text):
        return 300, "measured world-context opportunity"
    if re.search(r"\b(?:sprinting|crouching|grounded|moving)\b", text):
        return 200, "locomotion-state context"
    if re.search(r"\b(?:does not exist|absent|no context|fallback|baseline|preserve jump)\b", text):
        return 0, "explicit baseline fallback"
    return 100 + min(len(guards), 9), "guard-specificity fallback"


def _input_arbitration(behaviors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for behavior in behaviors:
        if behavior.get("depends_on"):
            continue
        key = _trigger_key(str(behavior.get("trigger") or ""))
        if key:
            grouped.setdefault(key, []).append(behavior)
    rows = []
    for key, candidates in grouped.items():
        ordered = []
        for behavior in candidates:
            priority_evidence = (
                [str(value) for value in behavior.get("guards") or []]
                + [str(behavior.get("title") or "")]
                + [str(value) for value in behavior.get("outcomes") or []]
            )
            score, reason = _guard_priority(priority_evidence)
            ordered.append({
                "behavior_id": behavior.get("id"),
                "title": behavior.get("title"),
                "priority": score,
                "reason": reason,
                "guards": list(behavior.get("guards") or []),
            })
        ordered.sort(key=lambda value: (-int(value["priority"]), str(value.get("behavior_id") or "")))
        ties = [
            [left.get("behavior_id"), right.get("behavior_id")]
            for left, right in zip(ordered, ordered[1:])
            if left.get("priority") == right.get("priority")
        ]
        rows.append({
            "input": key,
            "policy": "Evaluate in descending priority and execute only the first passing candidate.",
            "ordered_candidates": ordered,
            "unresolved_ties": ties,
            "fallback_behavior_id": next(
                (value.get("behavior_id") for value in ordered if value.get("priority") == 0), ""
            ),
        })
    return rows


def _behavior_proof_fixtures(behaviors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixtures = []
    for behavior in behaviors:
        behavior_id = str(behavior.get("id") or "behavior")
        outcomes = list(behavior.get("outcomes") or [])
        guards = list(behavior.get("guards") or [])
        fixtures.extend([
            {
                "id": f"{behavior_id}_positive",
                "category": "positive",
                "setup": guards,
                "action": behavior.get("trigger"),
                "assertions": outcomes,
                "evidence": ["structured runtime observation", "before/after character snapshot"],
            },
            {
                "id": f"{behavior_id}_negative",
                "category": "negative",
                "setup": [f"force false: {value}" for value in guards],
                "action": behavior.get("trigger"),
                "assertions": ["activation is rejected", "authoritative baseline state is unchanged"],
                "evidence": ["structured runtime observation", "negative-path state snapshot"],
            },
            {
                "id": f"{behavior_id}_interruption",
                "category": "interruption",
                "setup": ["activate behavior and interrupt during its active state"],
                "action": "invoke declared cancellation or force guard loss",
                "assertions": ["owned settings are restored", "behavior returns to its ready state"],
                "evidence": ["pre-activation ownership snapshot", "post-cleanup snapshot", "runtime log window"],
            },
        ])
        source = " ".join(str(value) for value in behavior.get("source_clauses") or [])
        numbers = re.findall(r"\b\d+(?:\.\d+)?\s*(?:cm|m|seconds?|s|units?)?\b", source, re.I)
        if numbers:
            fixtures.append({
                "id": f"{behavior_id}_boundary",
                "category": "boundary",
                "setup": [f"test immediately below, at, and immediately above {value}" for value in numbers],
                "action": behavior.get("trigger"),
                "assertions": ["authored comparator behavior is exact at every boundary sample"],
                "evidence": ["measured setup values", "structured pass/fail result per sample"],
            })
    return fixtures


def _animation_role_bindings(
    behaviors: list[dict[str, Any]], candidates: list[dict[str, Any]], skeleton: str
) -> list[dict[str, Any]]:
    roles = list(dict.fromkeys(
        str(role) for behavior in behaviors for role in behavior.get("animation_roles") or [] if role
    ))
    candidate_paths = [
        value.get("asset_path") or value.get("path")
        for value in candidates
        if value.get("asset_path") or value.get("path")
    ]
    return [
        {
            "role": role,
            "target_skeleton": skeleton,
            "selected_asset": "",
            "candidate_assets": candidate_paths,
            "required_evidence": [
                "semantic role match",
                "skeleton compatibility or verified retarget",
                "root-motion and displacement metrics",
                "contextual preview acceptance",
                "consumed AnimGraph slot/layer path",
                "PIE playback on the possessed target mesh",
            ],
            "status": "blocked_until_asset_evidence_passes",
        }
        for role in roles
    ]


def synthesize_detailed_implementation_plan(
    request: str,
    *,
    requirement_contract: dict[str, Any],
    project_context: dict[str, Any],
    architecture_decision: dict[str, Any],
    techniques: Iterable[dict[str, Any]],
    implementation_steps: Iterable[dict[str, Any]],
    operation_status: Iterable[dict[str, Any]],
    gameplay_proof_contract: dict[str, Any],
    animation_candidates: Iterable[dict[str, Any]] | None = None,
    behavior_decomposition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a readable plan and machine-executable action graph without mechanic dispatch."""

    explicit = dict(requirement_contract.get("explicit") or {})
    proof_contract = dict(gameplay_proof_contract.get("gameplay_contract") or {})
    techniques = [dict(row) for row in techniques or []]
    statuses = {str(row.get("operation") or ""): dict(row) for row in operation_status or []}
    graph_executor_status = statuses.get("blueprint.apply_graph_spec", {})
    feature = str(proof_contract.get("feature_name") or _feature_name(request))
    inputs = list(explicit.get("inputs") or [])
    timing = list(explicit.get("timing") or [])
    continuous = bool(timing or re.search(r"\b(?:hold|holding|while|continuous|every tick)\b", request or "", re.I))
    state_flow = (
        ["Inactive", "Qualifying", "Entering", "Active", "Exiting", "Interrupted", "Inactive"]
        if continuous
        else ["Inactive", "Activating", "Active", "Completing", "Inactive"]
    )
    architecture_rows = [
        {"technique": row.get("key"), **dict(row.get("architecture") or {})}
        for row in techniques
        if row.get("architecture")
    ]

    actions = []
    phases = []
    action_index = 0
    for phase_index, raw_step in enumerate(implementation_steps or [], 1):
        step = dict(raw_step)
        phase_actions = []
        for operation in step.get("operations") or []:
            action_index += 1
            status = statuses.get(str(operation), {})
            params = _operation_params(str(operation), project_context, request, step)
            action = {
                "id": f"action_{action_index:02d}",
                "operation": operation,
                "params": params,
                "callable": bool(status.get("callable_found")),
                "unresolved_params": _unresolved_params(params),
                "preconditions": ["Prior phase postconditions passed", "Live target evidence is unchanged"],
                "postconditions": [step.get("detail") or step.get("success") or "Operation-specific readback passes"],
                "mutation_allowed": False,
            }
            actions.append(action)
            phase_actions.append(action["id"])
        phases.append(
            {
                "number": phase_index,
                "title": step.get("title"),
                "domain": step.get("domain"),
                "detail": step.get("detail"),
                "action_ids": phase_actions,
            }
        )

    candidates = [dict(row) for row in animation_candidates or []]
    behavior = dict(behavior_decomposition or {})
    behavior_rows = [dict(row) for row in behavior.get("selected_primitives") or []]
    arbitration = _input_arbitration(behavior_rows)
    proof_fixtures = _behavior_proof_fixtures(behavior_rows)
    role_bindings = _animation_role_bindings(
        behavior_rows,
        candidates,
        str(project_context.get("target_skeleton") or project_context.get("skeleton") or ""),
    )
    behavior_operation_bindings = []
    for row in behavior_rows:
        step = {"domain": "behavior", "title": row.get("title")}
        bindings = []
        for operation in row.get("operations") or []:
            status = statuses.get(str(operation), {})
            params = _operation_params(str(operation), project_context, request, step)
            realization = _operation_realization(str(operation), status, graph_executor_status)
            bindings.append({
                "operation": operation,
                "callable": bool(status.get("callable_found")),
                "function": status.get("function") or "",
                "params": params,
                "unresolved_params": _unresolved_params(params),
                "realization": realization,
                "postconditions": list(row.get("outcomes") or row.get("proof_scenarios") or []),
            })
        behavior_operation_bindings.append({
            "behavior_id": row.get("id") or row.get("key"),
            "title": row.get("title"),
            "depends_on": list(row.get("depends_on") or []),
            "trigger": row.get("trigger"),
            "observations": list(row.get("observations") or []),
            "guards": list(row.get("guards") or []),
            "outcomes": list(row.get("outcomes") or []),
            "operation_bindings": bindings,
        })
    proof_claims = [dict(row) for row in gameplay_proof_contract.get("proof_claims") or []]
    unresolved_actions = [row["id"] for row in actions if not row["callable"] or row["unresolved_params"]]
    unresolved_behavior_operations = [
        f"{row.get('behavior_id')}:{binding.get('operation')}"
        for row in behavior_operation_bindings
        for binding in row.get("operation_bindings") or []
        if not binding.get("callable") or binding.get("unresolved_params")
    ]
    readiness_errors = []
    if not project_context.get("target_asset"):
        readiness_errors.append("The exact target character Blueprint is unresolved.")
    if role_bindings and not project_context.get("animation_blueprint"):
        readiness_errors.append("Animation roles exist but the exact target AnimBlueprint is unresolved.")
    if any(row.get("unresolved_ties") for row in arbitration):
        readiness_errors.append("Input arbitration contains equal-priority candidates requiring an explicit ordering decision.")
    if role_bindings:
        readiness_errors.append("Animation role assets remain unselected or lack contextual acceptance evidence.")
    if unresolved_behavior_operations:
        readiness_errors.append("One or more behavior operations lack a callable with resolved parameters.")
    if unresolved_actions:
        readiness_errors.append("One or more implementation actions lack a callable with resolved parameters.")
    if behavior_rows and not proof_fixtures:
        readiness_errors.append("No executable PIE fixtures were generated for the behavior contract.")
    primitive_functions = [
        "Handle" + "".join(part.title() for part in re.split(r"[^A-Za-z0-9]+", str(key)) if part)
        for key in behavior.get("primitive_keys") or []
    ]
    return {
        "framework": "unreal_detailed_implementation_plan_v1",
        "feature": feature,
        "request": request,
        "project_context": {
            "target_character": project_context.get("target_asset"),
            "parent_class": project_context.get("target_parent_class"),
            "skeletal_mesh": project_context.get("skeletal_mesh"),
            "target_skeleton": project_context.get("target_skeleton") or project_context.get("skeleton"),
            "current_animation_blueprint": project_context.get("animation_blueprint"),
        },
        "behavior_contract": {
            "activation": explicit.get("activation") or proof_contract.get("trigger"),
            "inputs": inputs,
            "timing": timing,
            "scope": list(explicit.get("scope") or []),
            "preconditions": list(proof_contract.get("preconditions") or []),
            "runtime_behavior": list(proof_contract.get("runtime_behavior") or []),
            "state_changes": list(proof_contract.get("state_changes") or []),
            "player_visible_result": proof_contract.get("player_visible_result"),
            "completion_or_cancellation": proof_contract.get("completion_or_cancellation"),
            "invalid_conditions": list(proof_contract.get("invalid_conditions") or []),
        },
        "proposed_architecture": {
            **dict(architecture_decision or {}),
            "technique_guidance": architecture_rows,
            "state_flow": list(behavior.get("states") or state_flow),
            "state_transitions": list(behavior.get("transitions") or []),
            "observations": list(behavior.get("observations") or []),
            "guards": list(behavior.get("guards") or []),
            "state_owner_variables": [
                f"bIs{feature.replace(' ', '')}",
                "CurrentState",
                "ActivationElapsedSeconds" if timing else "ActivationRequest",
                "ObservedTarget",
                "PreviousMovementState",
            ],
            "function_boundaries": [
                f"Observe{feature.replace(' ', '')}Context",
                f"CanEnter{feature.replace(' ', '')}",
                f"Enter{feature.replace(' ', '')}",
                f"Update{feature.replace(' ', '')}",
                f"Exit{feature.replace(' ', '')}",
                f"Cancel{feature.replace(' ', '')}",
            ] + primitive_functions,
        },
        "animation_integration": {
            "policy": architecture_decision.get("animation_integration"),
            "current_animation_blueprint": project_context.get("animation_blueprint"),
            "requested_artifacts": list(explicit.get("requested_artifacts") or []),
            "required_roles": list(behavior.get("animation_roles") or []),
            "role_assessment": list(behavior.get("animation_role_assessment") or []),
            "candidate_assets": candidates,
            "role_bindings": role_bindings,
            "acceptance_rule": "No candidate is wired into the final path until semantic role, skeleton/retarget, motion metrics, contextual preview, graph consumption, and PIE playback pass.",
        },
        "phases": phases,
        "action_graph": actions,
        "behavior_implementation": behavior_operation_bindings,
        "input_arbitration": arbitration,
        "proof_plan": {
            "claims": proof_claims,
            "levels": sorted({int(row.get("evidence_level") or 0) for row in proof_claims}),
            "generated_scenarios": list(behavior.get("proof_scenarios") or []),
            "fixtures": proof_fixtures,
            "regression_fixture": {
                "id": "global_regression",
                "setup": ["record baseline movement, reserved inputs, locomotion, and combat behavior"],
                "action": "run the full feature fixture sequence, then repeat baseline actions",
                "assertions": ["reserved inputs remain unchanged", "baseline movement and animation still pass"],
                "evidence": ["before/after structured runtime snapshots", "bounded diagnostics log comparison"],
            },
            "completion_rule": "Every claim must pass from trusted observed evidence; compilation alone is Level 1 only.",
        },
        "behavior_decomposition": behavior,
        "knowledge_gaps": list(behavior.get("unmatched_behavior_clauses") or []),
        "rollback_manifest": {
            "modify_with_backup": [
                value for value in (
                    project_context.get("target_asset"),
                    project_context.get("animation_blueprint"),
                ) if value
            ],
            "create_isolated": [],
            "restore_order": ["animation blueprint", "character blueprint", "input assets", "created feature assets"],
            "verification": ["compile restored assets", "reload packages", "rerun baseline regression fixture"],
        },
        "readiness": {
            "action_count": len(actions),
            "unresolved_action_ids": unresolved_actions,
            "unresolved_behavior_operations": unresolved_behavior_operations,
            "errors": readiness_errors,
            "ready_for_approval": not readiness_errors,
            "ready_for_completion_claim": False,
        },
    }
