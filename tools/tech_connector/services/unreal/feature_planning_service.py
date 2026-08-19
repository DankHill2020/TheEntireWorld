"""Evidence-first planning for bounded Unreal Blueprint gameplay features."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
import re
import time
from typing import Any, Callable


ProgressCallback = Callable[[str], None]


@lru_cache(maxsize=1)
def _plugin_function_status_index() -> dict[str, dict[str, Any]]:
    """
    Builds the lightweight reflected plugin-function status index.

    :return: Python call paths mapped to implementation status
    """
    from tech_connector.services.unreal.unreal_capability_audit_service import (
        CPP_PATH,
        MANIFEST_PATH,
        _parse_cpp_bodies,
    )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    bodies = _parse_cpp_bodies(CPP_PATH)
    index: dict[str, dict[str, Any]] = {}
    for row in manifest.get("capabilities") or []:
        python_call = str(row.get("python_call") or "")
        function_path = python_call.partition("(")[0].strip()
        cpp_function = str(row.get("function") or "")
        body = dict(bodies.get(cpp_function) or {})
        if function_path:
            index[function_path] = {
                "callable_found": bool(body) and not body.get("cpp_body_required"),
                "cpp_status": (
                    "implemented"
                    if body and not body.get("cpp_body_required")
                    else "cpp_body_required" if body else "missing_cpp_body"
                ),
                "source_path": str(CPP_PATH),
            }
    return index


@lru_cache(maxsize=256)
def _python_source_definitions(
    path_text: str,
    modified_ns: int,
    size: int,
) -> frozenset[str]:
    """
    Reads top-level Python definitions once per source revision.

    :param path_text: Python source path
    :param modified_ns: source modification timestamp in nanoseconds
    :param size: source size in bytes
    :return: top-level callable and class names
    """
    del modified_ns, size
    origin = Path(path_text)
    tree = ast.parse(origin.read_text(encoding="utf-8"), filename=str(origin))
    return frozenset(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )


def is_approved_unreal_feature_execution_request(
    prompt: str,
    prior_result_metadata: dict[str, Any] | None,
) -> bool:
    """Recognize approval only when it is bound to a prior Unreal feature plan."""

    metadata = dict(prior_result_metadata or {})
    plan = dict(metadata.get("plan") or {})
    return bool(
        metadata.get("result_type") == "unreal_feature_plan_approval"
        and plan.get("status") == "approval_ready"
        and plan.get("feature")
        and re.search(r"\b(approve|approved|proceed|continue|execute|do it|go ahead|yes)\b", prompt or "", re.I)
    )


def _call_feature_function(function_path: str, *, timeout: float = 40.0) -> tuple[bool, Any]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    bridge = UnrealBridge()
    ok, raw = bridge.call(
        function_path,
        args=[],
        kwargs={},
        timeout=timeout,
        retries=0,
        retry_safe=False,
        operation="gameplay.stamina_sprint",
    )
    try:
        return ok, json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return ok, raw


def _rollback_stamina_feature() -> dict[str, Any]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    code = """
import unreal, json
out = {'ok': True, 'actions': [], 'errors': []}
for backup, target in (
    ('/Game/TimeFighters/AIStudioBackups/BP_ThirdPersonCharacter_PreStamina_20260716', '/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter'),
    ('/Game/TimeFighters/AIStudioBackups/IMC_Default_PreStamina_20260716', '/Game/Input/IMC_Default'),
):
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(backup):
            if unreal.EditorAssetLibrary.does_asset_exist(target):
                unreal.EditorAssetLibrary.delete_asset(target)
            restored = bool(unreal.EditorAssetLibrary.duplicate_asset(backup, target))
            out['actions'].append({'restore': target, 'ok': restored})
            out['ok'] = out['ok'] and restored
    except Exception as exc:
        out['ok'] = False
        out['errors'].append(str(exc))
for path in ('/Game/TimeFighters/Input/IA_Sprint', '/Game/TimeFighters/Blueprints/Components/BPC_StaminaSprint'):
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            deleted = bool(unreal.EditorAssetLibrary.delete_asset(path))
            out['actions'].append({'delete_created_asset': path, 'ok': deleted})
            out['ok'] = out['ok'] and deleted
    except Exception as exc:
        out['ok'] = False
        out['errors'].append(str(exc))
print(json.dumps(out))
"""
    response = UnrealBridge().execute_python(code, timeout=20, reset_globals=True)
    data = response.get("data") or {}
    return data if isinstance(data, dict) else {"ok": False, "error": str(data)}


def _feature_plan_seal_payload(plan: dict[str, Any]) -> dict[str, Any]:
    payload = dict(plan or {})
    payload.pop("plan_seal", None)
    payload.pop("authorization", None)
    return payload


def seal_feature_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Bind approval to the exact serialized plan that was shown to the user."""

    sealed = _feature_plan_seal_payload(plan)
    canonical = json.dumps(sealed, sort_keys=True, separators=(",", ":"), default=str)
    sealed["plan_seal"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return sealed


def authorize_feature_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Authorize only an intact sealed plan; later edits invalidate execution."""

    authorized = dict(plan or {})
    supplied = str(authorized.get("plan_seal") or "")
    expected = str(seal_feature_plan(authorized).get("plan_seal") or "")
    if not supplied or supplied != expected:
        raise ValueError("Feature plan is unsealed or changed after sealing")
    authorized["authorization"] = {"approved": True, "plan_seal": supplied}
    return authorized


def _decoded_operation_result(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return raw


def execute_approved_unreal_feature_plan(
    plan: dict[str, Any],
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Execute a sealed feature-independent operation list and require runtime proof."""

    from tech_connector.router.command_router import CommandRouter
    from tech_connector.services.unreal.unreal_operation_service import (
        UNREAL_OPERATIONS,
        unreal_operation_payload,
    )

    plan = dict(plan or {})
    errors: list[str] = []
    if plan.get("framework") != "unreal_generic_feature_plan_v2":
        errors.append("Unsupported or missing generic feature-plan framework.")
    authorization = dict(plan.get("authorization") or {})
    supplied_seal = str(plan.get("plan_seal") or "")
    expected_seal = str(seal_feature_plan(plan).get("plan_seal") or "")
    if not authorization.get("approved") or authorization.get("plan_seal") != supplied_seal:
        errors.append("The exact plan has not been approved.")
    if not supplied_seal or supplied_seal != expected_seal:
        errors.append("The approved plan changed after it was sealed.")
    if plan.get("missing_capabilities"):
        errors.append("Approved plan still has unresolved capabilities.")

    calls = list(plan.get("operation_calls") or [])
    if not calls:
        errors.append("Approved plan contains no concrete operation calls.")
    required_verification = [str(value) for value in plan.get("required_verification_operations") or []]
    if not required_verification:
        errors.append("Approved plan declares no required verification operations.")
    if errors:
        return {"status": "blocked", "errors": errors, "plan": plan}

    router = CommandRouter()
    results: list[dict[str, Any]] = []
    passed_verification: list[str] = []
    for index, call in enumerate(calls, 1):
        call = dict(call or {})
        operation = str(call.get("operation") or "")
        params = dict(call.get("params") or {})
        postconditions = list(call.get("postconditions") or [])
        if operation == "feature.execute_generic_plan":
            errors.append("A generic plan cannot recursively execute its own orchestrator.")
            break
        if operation not in UNREAL_OPERATIONS:
            errors.append(f"Operation {index} is not registered: {operation or '<missing>'}")
            break
        if not postconditions:
            errors.append(f"Operation {index} has no declared postconditions: {operation}")
            break
        try:
            unreal_operation_payload(operation, params)
        except Exception as exc:
            errors.append(f"Operation {index} parameters are invalid: {exc}")
            break
        if progress:
            progress(f"Executing {index}/{len(calls)}: {operation}")
        label, ok, raw = router.execute_unreal_operation(operation, params)
        decoded = _decoded_operation_result(raw)
        payload_ok = not isinstance(decoded, dict) or decoded.get("ok", True) is not False
        passed = bool(ok and payload_ok)
        results.append(
            {
                "index": index,
                "operation": operation,
                "label": label,
                "ok": passed,
                "declared_postconditions": postconditions,
                "result": decoded,
            }
        )
        if not passed:
            errors.append(f"Operation failed: {operation}")
            break
        if operation in required_verification and operation not in passed_verification:
            passed_verification.append(operation)

    missing_verification = [
        operation for operation in required_verification if operation not in passed_verification
    ]
    if missing_verification:
        errors.append("Required verification did not pass: " + ", ".join(missing_verification))
    return {
        "status": "failed" if errors else "completed",
        "feature": plan.get("feature"),
        "target_asset": plan.get("target_asset"),
        "results": results,
        "passed_verification_operations": passed_verification,
        "errors": errors,
        "rollback": plan.get("rollback") or [],
    }


def render_unreal_feature_execution(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "failed")
    lines = ["Unreal stamina/sprint feature: " + status]
    for row in result.get("results") or []:
        lines.append(f"- {row.get('stage')}: {'passed' if row.get('ok') else 'failed'}")
    validation = dict(result.get("validation") or {})
    if validation:
        lines.append(f"- Blueprint compile: {'passed' if validation.get('compile_ok') else 'failed'}")
        if "behavior_ok" in validation:
            lines.append(f"- Compiled behavior: {'passed' if validation.get('behavior_ok') else 'failed'}")
        lines.append(f"- Graph layout: {'passed' if validation.get('layout_ok') else 'failed'}")
        lines.append(f"- Input mappings: {'passed' if validation.get('input_mappings_ok') else 'failed'}")
    if result.get("errors"):
        lines.extend("- " + str(error) for error in result["errors"])
    return "\n".join(lines)


def _asset_token(prompt: str) -> str:
    path_match = re.search(r"(?<![A-Za-z0-9_])(/Game/[A-Za-z0-9_./-]+)", prompt or "")
    if path_match:
        return path_match.group(1).rstrip(".,;:)").split(".", 1)[0]
    match = re.search(r"\b(?:ABP|BP)_[A-Za-z0-9_]+\b", prompt or "")
    return match.group(0) if match else ""


def is_unreal_feature_plan_request(prompt: str) -> bool:
    lower = (prompt or "").lower()
    has_target = bool(
        _asset_token(prompt)
        or re.search(r"\bresolve\b.{0,50}\b(?:character\s+)?blueprint\b", lower)
        or re.search(r"\b(?:selected|played|active)\s+character\b", lower)
    )
    subsystem_hits = sum(
        bool(re.search(pattern, lower))
        for pattern in (
            r"\bniagara|vfx|particle",
            r"\banim|montage|notify",
            r"\bblueprint|component|interface",
            r"\binput|mapping",
            r"\bai|state\s*tree|behavior\s*tree|perception|patrol",
            r"\bwidget|ui|save\s*game",
            r"\breplicat|multiplayer|network",
            r"\bmaterial|metasound|audio",
        )
    )
    explicit_plan = bool(
        re.search(r"\b(plan|approval|approve|do not edit|don't edit|dont edit|do not save|yet)\b", lower)
    )
    complex_feature = bool(
        len(prompt or "") >= 600
        or subsystem_hits >= 3
        or "success criteria" in lower
        or "requirements:" in lower
    )
    return bool(
        "unreal" in lower
        and has_target
        and re.search(r"\b(add|create|build|implement|repair|fix|set up|setup)\b", lower)
        and (explicit_plan or complex_feature)
    )


def is_direct_unreal_blueprint_inspection(prompt: str) -> bool:
    lower = (prompt or "").lower()
    return bool(
        "unreal" in lower
        and _asset_token(prompt)
        and re.search(r"\b(inspect|scan|show|list|report)\b", lower)
        and not re.search(r"\b(add|create|build|implement|modify|change|delete|remove)\b", lower)
    )


def _call_live_context(prompt: str, target_asset: str) -> tuple[bool, dict[str, Any], float]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    started = time.perf_counter()
    bridge = UnrealBridge()
    function_path = "tech_connector.bridges.unreal.unreal_blueprint_inspection.inspect_feature_context"
    ok, raw = bridge.call(
        function_path,
        args=[target_asset, prompt],
        kwargs={},
        timeout=12,
        retries=0,
        retry_safe=True,
        operation="blueprint.feature_context",
    )
    if not ok and "has no attribute 'inspect_feature_context'" in str(raw):
        bridge.execute_python(
            "import importlib\n"
            "import tech_connector.bridges.unreal.unreal_blueprint_inspection as inspection\n"
            "importlib.reload(inspection)\n"
            "'reloaded'",
            timeout=5,
            reset_globals=True,
        )
        ok, raw = bridge.call(
            function_path,
            args=[target_asset, prompt],
            kwargs={},
            timeout=12,
            retries=0,
            retry_safe=True,
            operation="blueprint.feature_context",
        )
    elapsed = time.perf_counter() - started
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        data = {"errors": [str(raw)], "sufficient": False}
    return ok and bool(data.get("sufficient")), data, elapsed


def _stamina_sprint_plan(prompt: str, evidence: dict[str, Any]) -> dict[str, Any]:
    from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

    blueprint = dict(evidence.get("blueprint") or {})
    assets = dict(evidence.get("assets") or {})
    input_actions = list(assets.get("input_actions") or [])
    mapping_contexts = list(assets.get("input_mapping_contexts") or [])
    action_names = {str(row.get("name") or "").lower() for row in input_actions}
    mapping_by_name = {str(row.get("name") or ""): str(row.get("path") or "") for row in mapping_contexts}
    target_asset = str(evidence.get("target_asset") or "")
    movement = dict((blueprint.get("defaults") or {}).get("movement") or {})
    anim_blueprints = list(evidence.get("animation_blueprints") or [])
    current_anim = anim_blueprints[0] if anim_blueprints else {}
    component_path = "/Game/TimeFighters/Blueprints/Components/BPC_StaminaSprint"
    input_path = "/Game/TimeFighters/Input/IA_Sprint"
    mapping_path = mapping_by_name.get("IMC_Default") or "/Game/Input/IMC_Default"
    missing_capabilities = []
    required_input_operations = ["input.add_mapping"]
    if "ia_sprint" not in action_names:
        required_input_operations.insert(0, "input.create_action")
    for operation in required_input_operations:
        if operation not in UNREAL_OPERATIONS:
            missing_capabilities.append(
                {
                    "capability": operation,
                    "reason": f"The approved feature requires {operation}, but it is not registered yet.",
                }
            )

    return {
        "framework": "unreal_feature_approval_plan_v1",
        "status": "approval_ready",
        "request": prompt,
        "feature": "stamina_sprint",
        "target_asset": target_asset,
        "evidence": {
            "target_parent_class": blueprint.get("parent_class"),
            "authored_variables": [row.get("name") for row in blueprint.get("variables") or []],
            "functions": [row.get("name") for row in blueprint.get("functions") or []],
            "graphs": [row.get("name") for row in blueprint.get("graphs") or []],
            "movement_defaults": movement,
            "skeletal_mesh": next((row.get("skeletal_mesh_asset") for row in blueprint.get("components") or [] if row.get("skeletal_mesh_asset")), ""),
            "animation_blueprint": current_anim.get("asset_path") or "",
            "animation_variables": [row.get("name") for row in current_anim.get("variables") or []],
            "input_action_count": len(input_actions),
            "input_mapping_context": mapping_path,
            "sprint_action_exists": "ia_sprint" in action_names,
        },
        "affected_assets": [
            {"path": component_path, "change": "create reusable Actor Component Blueprint"},
            {"path": input_path, "change": "create Boolean Enhanced Input action" if "ia_sprint" not in action_names else "reuse existing action"},
            {"path": mapping_path, "change": "add IA_Sprint keyboard/gamepad mappings"},
            {"path": target_asset, "change": "add component and minimal input/movement glue"},
        ],
        "unchanged_assets": [
            {
                "path": current_anim.get("asset_path") or "current animation Blueprint",
                "reason": "It already derives locomotion from GroundSpeed; validate sprint playback before proposing an AnimGraph edit.",
            }
        ],
        "implementation_steps": [
            {
                "step": 1,
                "title": "Verify bridge capabilities",
                "operations": ["input.create_action", "input.add_mapping"],
                "detail": "Dry-run the registered typed bridge functions and require verified postconditions. Do not substitute arbitrary or fabricated calls.",
            },
            {
                "step": 2,
                "title": "Create reusable stamina component",
                "operations": ["blueprint.create_from_template", "blueprint.create_variable", "blueprint.add_function"],
                "detail": "Create BPC_StaminaSprint as an ActorComponent with MaxStamina=100, Stamina=100, DrainPerSecond=20, RecoveryPerSecond=15, RecoveryDelay=1.0, WalkSpeed=600, SprintSpeed=900, plus StartSprint, StopSprint, CanSprint, DrainStamina, and RecoverStamina behavior.",
            },
            {
                "step": 3,
                "title": "Create and map sprint input",
                "operations": ["input.create_action", "input.add_mapping"],
                "detail": "Create IA_Sprint only because the inventory proves it is absent; map Left Shift and a gamepad face/shoulder input in IMC_Default without disturbing existing mappings.",
            },
            {
                "step": 4,
                "title": "Integrate the character",
                "operations": ["blueprint.add_component", "blueprint.add_node", "blueprint.connect_node_pins"],
                "detail": "Add BPC_StaminaSprint to BP_ThirdPersonCharacter. Bind IA_Sprint Started/Completed to the component and let the component set CharacterMovement MaxWalkSpeed. Keep EventGraph glue limited to input forwarding.",
            },
            {
                "step": 5,
                "title": "Compile and validate",
                "operations": ["blueprint.compile", "blueprint.get_compile_errors", "blueprint.scan"],
                "detail": "Compile each touched Blueprint, require zero compile errors, rescan exact variables/components/graphs, then PIE-test drain, exhaustion fallback to 600 speed, delayed recovery, and repeated input transitions.",
            },
        ],
        "missing_capabilities": missing_capabilities,
        "validation": [
            "All touched Blueprints compile with zero errors and no orphan graph pins.",
            "Holding sprint raises MaxWalkSpeed from 600 to 900 only while movement input is active and Stamina is positive.",
            "Stamina drains at 20/s, stops sprint at zero, waits 1.0s, and recovers at 15/s without exceeding 100.",
            "ABP locomotion continues to receive GroundSpeed and reaches its run range without an AnimGraph mutation.",
            "Existing temporal ability, melee, lock-on, jump, move, and look inputs still work.",
        ],
        "rollback": [
            "Create backups or duplicate touched assets before mutation.",
            "Remove BPC_StaminaSprint from BP_ThirdPersonCharacter and its two input event bindings.",
            "Remove IA_Sprint mappings from IMC_Default, then delete IA_Sprint only if this plan created it and no referencers remain.",
            "Delete BPC_StaminaSprint only after a referencer query returns empty; restore backed-up assets if compile or PIE validation fails.",
        ],
        "approval_gate": {
            "required": True,
            "changes_applied": False,
            "message": "Approve this exact asset plan before capability creation or Unreal asset mutation begins.",
        },
        "self_review": {
            "request_covered": True,
            "live_evidence_sufficient": bool(evidence.get("sufficient")),
            "unknowns_are_explicit": True,
            "fabricated_operations": False,
            "animation_edit_avoided_without_evidence": True,
        },
    }


def _local_operation_status(operation_key: str) -> dict[str, Any]:
    """Verify that a registered operation resolves to a concrete local function."""

    from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

    operation = UNREAL_OPERATIONS.get(operation_key)
    if operation is None:
        return {
            "operation": operation_key,
            "registered": False,
            "callable_found": False,
            "function": "",
            "reason": "No operation is registered.",
        }
    function_path = str(operation.function or "")
    if function_path.startswith("ai_studio.synthetic."):
        return {
            "operation": operation_key,
            "registered": True,
            "callable_found": False,
            "function": function_path,
            "reason": "The registry entry is synthetic and has no importable implementation.",
        }
    if function_path.startswith("unreal.AIStudioBridgeLibrary."):
        try:
            plugin_row = _plugin_function_status_index().get(function_path)
        except Exception as exc:
            return {
                "operation": operation_key,
                "registered": True,
                "callable_found": False,
                "function": function_path,
                "reason": "AIStudioBridge plugin status could not be inspected: " + str(exc),
            }
        if not plugin_row:
            return {
                "operation": operation_key,
                "registered": True,
                "callable_found": False,
                "function": function_path,
                "reason": "AIStudioBridge function is not listed in the plugin manifest.",
            }
        cpp_status = str(plugin_row.get("cpp_status") or "")
        return {
            "operation": operation_key,
            "registered": True,
            "callable_found": bool(plugin_row.get("callable_found")),
            "function": function_path,
            "source_path": str(plugin_row.get("source_path") or ""),
            "reason": (
                "AIStudioBridge reflected C++ body is implemented."
                if cpp_status == "implemented"
                else f"AIStudioBridge reflected C++ body status is `{cpp_status}`."
            ),
        }
    module_name, separator, function_name = function_path.rpartition(".")
    if not separator:
        return {
            "operation": operation_key,
            "registered": True,
            "callable_found": False,
            "function": function_path,
            "reason": "The function path is not fully qualified.",
        }
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        spec = None
    origin = Path(spec.origin) if spec and spec.origin and spec.origin.endswith(".py") else None
    if origin is None or not origin.exists():
        return {
            "operation": operation_key,
            "registered": True,
            "callable_found": False,
            "function": function_path,
            "reason": f"Module `{module_name}` is not available as local Python source.",
        }
    try:
        source_stat = origin.stat()
        definitions = _python_source_definitions(
            str(origin),
            int(source_stat.st_mtime_ns),
            int(source_stat.st_size),
        )
    except Exception as exc:
        return {
            "operation": operation_key,
            "registered": True,
            "callable_found": False,
            "function": function_path,
            "source_path": str(origin),
            "reason": "The operation source could not be inspected: " + str(exc),
        }
    found = function_name in definitions
    return {
        "operation": operation_key,
        "registered": True,
        "callable_found": found,
        "function": function_path,
        "source_path": str(origin),
        "reason": "Local function definition found." if found else f"Function `{function_name}` is not defined in `{module_name}`.",
    }


def _generic_requirement_specs(
    prompt: str, behavior_decomposition: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    lower = prompt.lower()
    specs: list[dict[str, Any]] = [
        {
            "domain": "project_discovery",
            "title": "Inspect exact target assets and dependencies",
            "operations": ["blueprint.scan", "assets.inspect"],
            "success": "Target class, components, references, conventions, and reusable assets are supported by live evidence.",
        }
    ]
    enhanced_input_actions = [
        action
        for action in ("sprint", "crouch", "prone", "crawl", "mantle", "dodge")
        if re.search(rf"\b{action}\b", lower)
    ]
    if re.search(r"\b(?:enhanced\s+input|input\s+actions?|input\s+mappings?)\b", lower):
        for action in enhanced_input_actions or ["requested_action"]:
            action_token = "".join(part.title() for part in action.split("_"))
            specs.append(
                {
                    "domain": "enhanced_input",
                    "title": f"Create and map the {action} input action",
                    "operations": ["input.create_action", "input.add_mapping"],
                    "operation_arguments": {
                        "input.create_action": {
                            "asset_path": f"/Game/Input/IA_{action_token}",
                            "value_type": "boolean",
                            "description": f"Gameplay input for {action}",
                            "save": True,
                        },
                        "input.add_mapping": {
                            "mapping_context_path": "$resolved_input_mapping_context",
                            "action_path": f"/Game/Input/IA_{action_token}",
                            "key_name": f"$resolved_{action}_key",
                            "save": True,
                        },
                    },
                    "success": (
                        f"IA_{action_token} exists, is mapped once in the resolved active mapping "
                        "context, and its trigger reaches the owning character."
                    ),
                }
            )
    if "stamina" in lower:
        specs.extend(
            [
                {
                    "domain": "stamina",
                    "title": "Create authoritative reusable stamina behavior",
                    "operations": [
                        "rollback.record_asset_snapshot",
                        "gameplay.create_stamina_component",
                        "gameplay.integrate_stamina_character",
                        "gameplay.validate_stamina_feature",
                    ],
                    "operation_arguments": {
                        "rollback.record_asset_snapshot": {
                            "asset_path": "$target_asset",
                            "reason": "Before stamina and movement integration",
                            "operation": "gameplay.integrate_stamina_character",
                        },
                    },
                    "success": (
                        "Stamina ownership, drain, exhaustion, delayed recovery, movement gating, "
                        "and character integration are implemented and read back from compiled assets."
                    ),
                },
                {
                    "domain": "stamina_replication",
                    "title": "Replicate stamina and drive HUD updates",
                    "operations": [
                        "blueprint.configure_replication",
                        "network.inspect_authority_flow",
                        "blueprint.apply_graph_spec",
                    ],
                    "operation_arguments": {
                        "blueprint.configure_replication": {
                            "blueprint_path": "$target_asset",
                            "rep_notify_variables": ["Stamina"],
                            "server_rpc_functions": [
                                "Server_StartSprint",
                                "Server_StopSprint",
                                "Server_RequestDodge",
                            ],
                            "reliable": True,
                            "save": True,
                        },
                        "network.inspect_authority_flow": {
                            "blueprint_path": "$target_asset",
                            "required_variables": ["Stamina"],
                            "required_server_rpcs": [
                                "Server_StartSprint",
                                "Server_StopSprint",
                                "Server_RequestDodge",
                            ],
                            "required_onrep_functions": ["OnRep_Stamina"],
                        },
                        "blueprint.apply_graph_spec": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "graph_spec": {
                                "purpose": "Server-authoritative stamina with event-driven HUD update",
                                "required_flow": [
                                    "owning client sends bounded movement ability requests",
                                    "server validates and mutates Stamina",
                                    "OnRep_Stamina broadcasts a HUD update",
                                    "HUD consumes replicated state without polling",
                                ],
                            },
                        },
                    },
                    "success": (
                        "The server owns stamina mutations, Stamina uses RepNotify, OnRep_Stamina "
                        "updates the HUD, and authority/readback inspection proves the path."
                    ),
                },
            ]
        )
    if re.search(r"\b(?:motion\s+matching|pose\s+search)\b", lower):
        specs.extend(
            [
                {
                    "domain": "motion_matching",
                    "title": "Create and configure the Pose Search schema",
                    "operations": [
                        "motion_matching.create_schema",
                        "motion_matching.add_schema_channel",
                    ],
                    "operation_arguments": {
                        "motion_matching.create_schema": {
                            "schema_name": "PSchema_Traversal",
                            "save_path": "$project_convention_animation_folder",
                        },
                        "motion_matching.add_schema_channel": {
                            "schema_path": "$created_pose_search_schema",
                            "channel_type": "Position",
                            "bone_name": "$validated_motion_matching_bone",
                        },
                    },
                    "success": (
                        "A skeleton-compatible Pose Search schema exists with explicit trajectory "
                        "and pose channels proven by reflected readback."
                    ),
                },
                {
                    "domain": "motion_matching",
                    "title": "Build and validate the Motion Matching database",
                    "operations": [
                        "animation.find_compatible",
                        "motion_matching.create_database",
                        "motion_matching.add_animation",
                        "motion_matching.inspect_database",
                    ],
                    "operation_arguments": {
                        "animation.find_compatible": {
                            "skeleton_path": "$target_skeleton",
                            "directory": "$project_animation_folder",
                        },
                        "motion_matching.create_database": {
                            "skeleton_path": "$target_skeleton",
                            "animation_paths": "$contextually_accepted_animation_paths",
                            "asset_path": "$project_convention_motion_database_path",
                            "schema_path": "$created_pose_search_schema",
                            "sample_rate": 30,
                        },
                        "motion_matching.add_animation": {
                            "database_path": "$created_pose_search_database",
                            "animation_path": "$each_contextually_accepted_animation",
                        },
                        "motion_matching.inspect_database": {
                            "database_path": "$created_pose_search_database",
                        },
                    },
                    "success": (
                        "Only skeleton-compatible, contextually accepted animations are indexed, "
                        "and database readback proves schema, channels, assets, and sample settings."
                    ),
                },
            ]
        )
    if re.search(r"\b(?:ik\s+rig|ik\s+retargeter|retarget(?:er|ing)?)\b", lower):
        specs.extend(
            [
                {
                    "domain": "ik_retarget",
                    "title": "Create source and target IK Rigs with validated chains",
                    "operations": [
                        "skeletal.inspect_bones",
                        "retarget.create_ik_rig",
                        "retarget.add_ik_chain",
                    ],
                    "operation_arguments": {
                        "skeletal.inspect_bones": {
                            "skeletal_mesh_path": "$each_source_and_target_skeletal_mesh",
                            "include_hierarchy": True,
                        },
                        "retarget.create_ik_rig": {
                            "skeletal_mesh_path": "$each_source_and_target_skeletal_mesh",
                            "save_path": "$project_convention_ik_rig_path",
                        },
                        "retarget.add_ik_chain": {
                            "ik_rig_path": "$created_ik_rig",
                            "chain_name": "$derived_chain_name",
                            "start_bone": "$validated_chain_start_bone",
                            "end_bone": "$validated_chain_end_bone",
                        },
                    },
                    "success": (
                        "Source and target IK Rigs use bone-proven chain endpoints; no guessed bone "
                        "or chain name is accepted."
                    ),
                },
                {
                    "domain": "ik_retarget",
                    "title": "Create, map, and inspect the IK Retargeter",
                    "operations": [
                        "retarget.create_ik_retargeter",
                        "retarget.set_chain_mapping",
                        "retarget.set_root_settings",
                        "retarget.inspect",
                    ],
                    "operation_arguments": {
                        "retarget.create_ik_retargeter": {
                            "source_ik_rig_path": "$source_ik_rig_path",
                            "target_ik_rig_path": "$target_ik_rig_path",
                            "save_path": "$project_convention_retargeter_path",
                        },
                        "retarget.set_chain_mapping": {
                            "retargeter_path": "$created_ik_retargeter",
                            "source_chain": "$validated_source_chain",
                            "target_chain": "$validated_target_chain",
                        },
                        "retarget.set_root_settings": {
                            "retargeter_path": "$created_ik_retargeter",
                            "blend_height": 1.0,
                            "scale_factor": 1.0,
                        },
                        "retarget.inspect": {
                            "retargeter_path": "$created_ik_retargeter",
                        },
                    },
                    "success": (
                        "Retargeter readback proves both rigs, every requested chain mapping, root "
                        "settings, and skeleton compatibility before animation use."
                    ),
                },
            ]
        )
    requested_anim_states = [
        state
        for state in ("crouch", "prone", "crawl", "mantle", "dodge")
        if re.search(rf"\b{state}\b", lower)
    ]
    if (
        requested_anim_states
        and re.search(r"\b(?:anim(?:ation)?\s*blueprint|animblueprint|abp_[a-z0-9_]+)\b", lower)
        and re.search(r"\b(?:states?|state\s+machine|transition\s+rules?)\b", lower)
    ):
        specs.append(
            {
                "domain": "anim_graph_state_machine",
                "title": "Author concrete locomotion states and transition rules",
                "operations": [
                    "animation.get_state_machine_graph",
                    "anim_graph.add_state_machine",
                    *[
                        operation
                        for _state in requested_anim_states
                        for operation in (
                            "anim_graph.add_state",
                            "anim_graph.synthesize_transition_rule_expression",
                            "anim_graph.add_transition_rule",
                        )
                    ],
                    "anim_graph.wire_state_machine_to_output_pose",
                    "blueprint.compile_and_save",
                ],
                "operation_arguments": {
                    "animation.get_state_machine_graph": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "anim_graph.add_state_machine": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "anim_graph.add_state": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                        "state_name": "$each_requested_state",
                        "animation_asset_path": "$accepted_animation_for_state",
                    },
                    "anim_graph.synthesize_transition_rule_expression": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                        "from_state": "$resolved_source_state",
                        "to_state": "$each_requested_state",
                        "rule_expression": "$authoritative_state_guard_expression",
                    },
                    "anim_graph.add_transition_rule": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                        "from_state": "$resolved_source_state",
                        "to_state": "$each_requested_state",
                        "rule_expression": "$validated_transition_rule_expression",
                    },
                    "anim_graph.wire_state_machine_to_output_pose": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "blueprint.compile_and_save": {
                        "anim_bp_path": "$target_animation_blueprint",
                    },
                },
                "success": (
                    "Every requested state has an accepted animation, explicit entry/exit guards, "
                    "compiled transition graphs, and a proven path through the state machine to Output Pose."
                ),
            }
        )
    if re.search(r"\b(?:additive\s+slots?|root\s+motion|output\s+pose)\b", lower):
        specs.append(
            {
                "domain": "animation_pose_path",
                "title": "Preserve additive slots and root motion through Output Pose",
                "operations": [
                    "animation.inspect_imported_pipeline",
                    "animation.get_state_machine_graph",
                    "anim_graph.wire_state_machine_to_output_pose",
                    "blueprint.compile_and_save",
                    "runtime.validate_character_montages",
                ],
                "operation_arguments": {
                    "animation.inspect_imported_pipeline": {
                        "imported_paths": "$selected_animation_paths",
                        "target_skeleton_path": "$target_skeleton",
                        "target_skeletal_mesh_path": "$target_skeletal_mesh",
                    },
                    "animation.get_state_machine_graph": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "anim_graph.wire_state_machine_to_output_pose": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "blueprint.compile_and_save": {
                        "anim_bp_path": "$target_animation_blueprint",
                    },
                    "runtime.validate_character_montages": {
                        "character_blueprint_path": "$target_asset",
                        "montage_paths": "$accepted_additive_and_root_motion_assets",
                        "expected_anim_class_contains": "$target_animation_blueprint",
                    },
                },
                "success": (
                    "Readback proves root-motion policy, additive slot consumption, state-machine "
                    "connectivity, final Output Pose wiring, and possessed-character playback."
                ),
            }
        )
    if re.search(r"\b(?:physics\s*asset|physicsasset|constraint\s+profile|physical[- ]animation\s+profile)\b", lower):
        specs.append(
            {
                "domain": "physics_profiles",
                "title": "Create and validate PhysicsAsset profiles",
                "operations": [
                    "physics.list_bodies",
                    "physics.list_constraints",
                    "physics.add_profile",
                    "physics.set_profile_property",
                    "physics.list_profiles",
                ],
                "operation_arguments": {
                    "physics.list_bodies": {"asset_path": "$resolved_physics_asset"},
                    "physics.list_constraints": {"asset_path": "$resolved_physics_asset"},
                    "physics.add_profile": {
                        "asset_path": "$resolved_physics_asset",
                        "profile_name": "$each_requested_profile_name",
                        "profile_type": "$constraint_or_physical_animation",
                        "assign_all": True,
                    },
                    "physics.set_profile_property": {
                        "asset_path": "$resolved_physics_asset",
                        "profile_name": "$each_requested_profile_name",
                        "property_name": "$requested_profile_property",
                        "value": "$requested_profile_value",
                        "save": True,
                    },
                    "physics.list_profiles": {"asset_path": "$resolved_physics_asset"},
                },
                "success": (
                    "The target PhysicsAsset is resolved from the live mesh, body/constraint topology "
                    "is valid, and each constraint or physical-animation profile is assigned and read back."
                ),
            }
        )
    if any(term in lower for term in ("inventory", "pickup", "item stack", "item pickup")):
        specs.extend(
            [
                {
                    "domain": "inventory_state",
                    "title": "Define authoritative inventory state and item identity",
                    "operations": [
                        "rollback.record_asset_snapshot",
                        "blueprint.scan",
                        "blueprint.apply_graph_spec",
                        "blueprint.compile",
                        "blueprint.get_compile_errors",
                    ],
                    "operation_arguments": {
                        "rollback.record_asset_snapshot": {
                            "asset_path": "$target_asset",
                            "reason": "Before inventory graph and replication mutation",
                            "operation": "inventory.author_state",
                        },
                        "blueprint.apply_graph_spec": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "graph_spec": {
                                "purpose": "Create inventory entry schema and authoritative add/remove/query functions",
                                "required_state": [
                                    "InventoryEntries array keyed by stable ItemId",
                                    "quantity per entry",
                                    "schema version for persistence migration",
                                ],
                                "required_functions": [
                                    "FindInventoryEntry",
                                    "AddInventoryItem",
                                    "RemoveInventoryItem",
                                    "SerializeInventory",
                                    "RestoreInventory",
                                ],
                            },
                        },
                        "blueprint.get_compile_errors": {
                            "blueprint_path": "$target_asset",
                        },
                    },
                    "success": "The owning Blueprint has one authoritative inventory array keyed by stable ItemId, quantity-safe add/remove/query functions, and a rollback token before mutation.",
                },
                {
                    "domain": "inventory_pickup_flow",
                    "title": "Author server-owned pickup request and overlap flow",
                    "operations": [
                        "blueprint.search_node_actions",
                        "blueprint.describe_node_action",
                        "blueprint.probe_node_action",
                        "blueprint.apply_graph_spec",
                        "blueprint.configure_replication",
                        "network.inspect_authority_flow",
                    ],
                    "operation_arguments": {
                        "blueprint.search_node_actions": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "query": "authority overlap valid pickup add inventory destroy actor",
                        },
                        "blueprint.describe_node_action": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "palette_action": "$selected_blueprint_action",
                        },
                        "blueprint.probe_node_action": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "palette_action": "$selected_blueprint_action",
                        },
                        "blueprint.apply_graph_spec": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "graph_spec": {
                                "purpose": "Client request to server-authoritative pickup transaction",
                                "required_flow": [
                                    "overlap validates pickup actor and item definition",
                                    "non-authority owner invokes Server_RequestPickup",
                                    "server revalidates distance, ownership, item validity, and capacity",
                                    "server mutates InventoryEntries exactly once",
                                    "successful pickup destroys or disables the world pickup",
                                    "OnRep_InventoryEntries emits one UI update event",
                                ],
                                "negative_paths": [
                                    "duplicate request",
                                    "full inventory",
                                    "invalid item id",
                                    "out-of-range pickup",
                                    "non-owning client",
                                ],
                            },
                        },
                        "blueprint.configure_replication": {
                            "blueprint_path": "$target_asset",
                            "rep_notify_variables": ["InventoryEntries"],
                            "server_rpc_functions": ["Server_RequestPickup"],
                            "reliable": True,
                            "save": True,
                        },
                        "network.inspect_authority_flow": {
                            "blueprint_path": "$target_asset",
                            "required_variables": ["InventoryEntries"],
                            "required_server_rpcs": ["Server_RequestPickup"],
                            "required_onrep_functions": ["OnRep_InventoryEntries"],
                        },
                    },
                    "success": "Overlap only proposes a pickup; the owning client RPC reaches server authority, the server revalidates and mutates once, InventoryEntries replicates with OnRep, and invalid or duplicate requests fail without state change.",
                },
            ]
        )
    if any(term in lower for term in ("niagara", "particle", "vfx", "effect")):
        specs.extend(
            [
                {
                    "domain": "niagara",
                    "title": "Create and inspect the requested Niagara emitters",
                    "operations": [
                        "niagara.create_emitter",
                        "niagara.list_module_inputs",
                        "niagara.inspect_system",
                    ],
                    "operation_arguments": {
                        "niagara.create_emitter": {
                            "asset_path": "$each_requested_emitter_path",
                            "template": "$resolved_project_niagara_template",
                            "parameters": "$requested_emitter_parameters",
                        },
                        "niagara.list_module_inputs": {
                            "asset_path": "$resolved_niagara_system",
                            "emitter_name": "$each_requested_emitter_name",
                            "include_topology": False,
                        },
                        "niagara.inspect_system": {
                            "asset_path": "$resolved_niagara_system",
                        },
                    },
                    "success": (
                        "Each requested emitter is created from a proven project or engine template, "
                        "has a visible renderer, and exposes concrete stack/module readback."
                    ),
                },
                {
                    "domain": "niagara",
                    "title": "Author and bind Niagara user parameters",
                    "operations": [
                        "niagara.set_user_parameter",
                        "niagara.set_module_input",
                        "niagara.set_renderer_property",
                        "niagara.inspect_system",
                    ],
                    "operation_arguments": {
                        "niagara.set_user_parameter": {
                            "asset_path": "$resolved_niagara_system",
                            "parameter_name": "$each_requested_user_parameter",
                            "value": "$requested_default_value",
                            "value_type": "auto",
                        },
                        "niagara.set_module_input": {
                            "asset_path": "$resolved_niagara_system",
                            "emitter_name": "$resolved_emitter_name",
                            "script_usage": "$resolved_stack_usage",
                            "module_name": "$resolved_module_name",
                            "input_name": "$resolved_module_input",
                            "value": "$user_parameter_binding_or_value",
                            "value_type": "auto",
                        },
                        "niagara.set_renderer_property": {
                            "asset_path": "$resolved_niagara_system",
                            "emitter_name": "$resolved_emitter_name",
                            "renderer_index": 0,
                            "property_name": "$resolved_renderer_property",
                            "value": "$requested_renderer_value",
                            "value_type": "auto",
                        },
                        "niagara.inspect_system": {
                            "asset_path": "$resolved_niagara_system",
                        },
                    },
                    "success": (
                        "Every requested User parameter exists, is wired into a concrete spawn/update/"
                        "renderer input, and survives system readback."
                    ),
                },
            ]
        )
    attachment_requested = bool(
        re.search(r"\b(?:attach|attachment|socket)\b", lower)
        or re.search(r"\b(?:bone|hand)\b.{0,40}\b(?:attach|spawn|parent|socket)\b", lower)
    )
    if attachment_requested:
        specs.extend(
            [
                {
                    "domain": "skeletal_attachment",
                    "title": "Resolve the real skeleton bone or socket",
                    "operations": ["skeletal.inspect_bones", "skeletal.inspect_sockets"],
                    "success": "The chosen attachment name is proven on the target skeletal mesh/skeleton.",
                },
                {
                    "domain": "blueprint_integration",
                    "title": "Attach and configure the component",
                    "operations": ["blueprint.add_component", "blueprint.attach_to_socket"],
                    "success": "The component is attached to the verified mesh and bone/socket and is inactive by default.",
                },
            ]
        )
    graph_mutation_requested = bool(
        re.search(r"\b(?:blueprint|event\s*graph|construction\s*script|graph)\b", lower)
        and re.search(r"\b(?:add|insert|wire|connect|rewire|mutate|modify|branch|node|pins?)\b", lower)
    )
    if graph_mutation_requested:
        specs.append(
            {
                "domain": "blueprint_graph_mutation",
                "title": "Plan a reversible Blueprint graph mutation transaction",
                "operations": [
                    "blueprint.scan",
                    "blueprint.search_node_actions",
                    "blueprint.describe_node_action",
                    "blueprint.probe_node_action",
                    "blueprint.apply_graph_spec",
                    "blueprint.compile",
                    "blueprint.get_compile_errors",
                    "blueprint.scan",
                ],
                "success": (
                    "Pre-scan, action discovery, pin-proofed graph spec, apply, compile, and post-scan verify "
                    "the intended nodes/pins changed while unrelated nodes, variables, and links are preserved."
                ),
            }
        )
    data_driven_requested = bool(
        re.search(r"\b(?:data\s*asset|dataasset|data\s*table|datatable|schema|row\s*struct)\b", lower)
        or (
            re.search(r"\b(?:rarity|stack\s*size|item\s*definition|pickup\s*definition)\b", lower)
            and re.search(r"\b(?:item|inventory|pickup)\b", lower)
        )
    )
    if data_driven_requested:
        specs.append(
            {
                "domain": "data_driven_gameplay",
                "title": "Define data-driven item schema and runtime lookup path",
                "operations": [
                    "dataasset.inspect_schema",
                    "dataasset.create_or_update",
                    "datatable.inspect_schema",
                    "datatable.create_or_update",
                    "blueprint.bind_data_lookup",
                    "runtime.validate_data_lookup",
                ],
                "success": (
                    "Item definitions expose the requested fields, runtime pickup logic reads data by stable key, "
                    "save/load stores identifiers rather than duplicated display data, and missing rows fail safely."
                ),
            }
        )
    animation_notify_requested = bool(
        re.search(r"\b(?:anim(?:ation)?\s+notify|notify\s*state|notifystate)\b", lower)
    )
    if animation_notify_requested:
        specs.append(
            {
                "domain": "animation_notify",
                "title": "Create reusable notify-state control",
                "operations": [
                    "animation.create_notify_state",
                    "animation.add_notify_state_range",
                    "blueprint.create_interface",
                ],
                "success": "Notify begin/tick/end communicate through a safe interface and expose the requested controls.",
            }
        )
    if "duplicate" in lower and any(term in lower for term in ("anim", "animation", "montage")):
        specs.append(
            {
                "domain": "animation_asset",
                "title": "Choose and duplicate a compatible animation",
                "operations": ["animation.find_compatible", "assets.duplicate", "animation.inspect_notifies"],
                "success": "Only a proven compatible animation duplicate is modified, with source and destination reported.",
            }
        )
    if any(term in lower for term in ("preview", "play the", "plays the")):
        specs.append(
            {
                "domain": "preview_path",
                "title": "Create an isolated removable preview path",
                "operations": ["input.create_action", "input.add_mapping", "animation.play_asset"],
                "success": "The test animation can be triggered without replacing normal locomotion.",
            }
        )
    if any(term in lower for term in ("interface", "avoid coupling", "unsafe hard cast")):
        specs.append(
            {
                "domain": "blueprint_contract",
                "title": "Create a decoupled Blueprint communication contract",
                "operations": ["blueprint.create_interface", "blueprint.add_function", "blueprint.implement_interface"],
                "success": "The notify does not depend on an unsafe hard cast to one character class.",
            }
        )
    if any(term in lower for term in ("state tree", "statetree", "behavior tree", "perception", "patrol", " ai ")):
        specs.extend(
            [
                {
                    "domain": "ai_behavior",
                    "title": "Inspect the existing AI controller and decision system",
                    "operations": ["ai.inspect_controller", "ai.inspect_state_tree", "ai.inspect_behavior_tree"],
                    "success": "The plan reuses the project's actual AI framework and blackboard/state data rather than creating a parallel behavior path.",
                },
                {
                    "domain": "ai_behavior",
                    "title": "Author and validate the requested AI behavior",
                    "operations": ["ai.author_behavior", "navigation.validate_path", "runtime.ai_validate"],
                    "success": "The behavior transitions, navigation, target loss, and recovery paths are proven in a runtime test.",
                },
            ]
        )
    if any(term in lower for term in ("combo", "damage", "attack", "melee")):
        specs.append(
            {
                "domain": "combat_animation",
                "title": "Integrate animation timing with reusable combat contracts",
                "operations": [
                    "animation.find_compatible",
                    "animation.add_anim_notify",
                    "blueprint.create_interface",
                    "gameplay.validate_damage",
                ],
                "success": "Montage/notify timing drives damage through a reusable contract with duplicate-hit and interruption tests.",
            }
        )
    ui_requested = bool(re.search(r"\b(?:widget|user\s+interface|hud)\b", lower))
    persistence_requested = bool(re.search(r"\b(?:save\s*game|savegame|persist(?:ence|ent)?)\b", lower))
    inventory_requested = bool(re.search(r"\b(?:inventory|pickup|item\s+stack)\b", lower))
    if inventory_requested:
        replicated_variables = ["InventoryEntries"]
        server_rpcs = ["Server_RequestPickup"]
        onrep_functions = ["OnRep_InventoryEntries"]
        hud_flow = [
            "OnRep_InventoryEntries invokes InventoryChanged dispatcher",
            "HUD or view model subscribes once",
            "widget rows are rebuilt from authoritative replicated entries",
            "empty, removed, and stack-updated states are represented",
        ]
        hud_scenario = "Inventory OnRep produces one HUD refresh per accepted server mutation"
        network_assertions = [
            "owning client request changes server inventory once",
            "second client observes replicated InventoryEntries",
            "OnRep updates HUD on both relevant clients",
            "duplicate and non-owner requests do not mutate inventory",
        ]
    elif "stamina" in lower:
        replicated_variables = ["Stamina"]
        server_rpcs = ["Server_StartSprint", "Server_StopSprint", "Server_RequestDodge"]
        onrep_functions = ["OnRep_Stamina"]
        hud_flow = [
            "OnRep_Stamina broadcasts StaminaChanged with current and maximum values",
            "HUD or view model subscribes once",
            "stamina bar updates from replicated values without polling",
            "exhaustion and recovery states remain player-visible",
        ]
        hud_scenario = "Stamina RepNotify produces one HUD refresh per authoritative mutation"
        network_assertions = [
            "owning client ability request is validated by the server",
            "second client observes replicated stamina and movement state",
            "OnRep_Stamina updates the owning HUD",
            "duplicate, invalid, and non-owner requests do not mutate stamina",
        ]
    else:
        replicated_variables = ["$requested_replicated_variables"]
        server_rpcs = ["$requested_server_rpc_functions"]
        onrep_functions = ["$required_onrep_functions"]
        hud_flow = [
            "authoritative replicated state invokes its resolved RepNotify or dispatcher",
            "HUD or view model subscribes once",
            "presentation updates from event payloads without polling",
            "empty, invalid, interrupted, and recovery states are represented",
        ]
        hud_scenario = "Requested replicated state produces one UI refresh per accepted server mutation"
        network_assertions = [
            "owning client request reaches and is revalidated by the server",
            "all relevant clients observe the requested replicated state",
            "RepNotify presentation executes exactly once per accepted mutation",
            "invalid, duplicate, and non-owner requests do not mutate state",
        ]
    if ui_requested:
        specs.extend(
            [
                {
                    "domain": "ui",
                    "title": "Create or extend the project UI using existing widget conventions",
                    "operations": [
                        "assets.inspect",
                        "assets.dependencies",
                        "blueprint.scan",
                        "blueprint.apply_graph_spec",
                        "blueprint.compile",
                        "runtime.pie_validate",
                    ],
                    "operation_arguments": {
                        "assets.inspect": {"asset_path": "$target_asset"},
                        "assets.dependencies": {
                            "asset_path": "$target_asset",
                            "recursive": True,
                        },
                        "blueprint.apply_graph_spec": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "graph_spec": {
                                "purpose": "Event-driven HUD notification for authoritative gameplay state",
                                "required_flow": hud_flow,
                            },
                        },
                        "runtime.pie_validate": {
                            "target_assets": ["$target_asset"],
                            "expected": {"scenario": hud_scenario},
                            "start_pie": True,
                        },
                    },
                    "success": "The UI reflects authoritative gameplay state without polling or duplicating ownership.",
                },
            ]
        )
    if persistence_requested:
        specs.extend(
            [
                {
                    "domain": "persistence",
                    "title": "Persist and restore the requested state",
                    "operations": [
                        "assets.inspect",
                        "assets.dependencies",
                        "blueprint.scan",
                        "blueprint.apply_graph_spec",
                        "blueprint.compile",
                        "runtime.pie_validate",
                    ],
                    "operation_arguments": {
                        "assets.inspect": {"asset_path": "$target_asset"},
                        "assets.dependencies": {
                            "asset_path": "$target_asset",
                            "recursive": True,
                        },
                        "blueprint.apply_graph_spec": {
                            "blueprint_path": "$target_asset",
                            "graph_name": "EventGraph",
                            "graph_spec": {
                                "purpose": "Versioned inventory SaveGame round trip",
                                "required_flow": [
                                    "serialize stable ItemId, quantity, and schema version",
                                    "save only on authority or owning local persistence boundary",
                                    "load validates item definitions and clamps invalid quantities",
                                    "older schema migrates or reports an explicit incompatibility",
                                    "restored authoritative state triggers the normal replicated UI path",
                                ],
                            },
                        },
                        "runtime.pie_validate": {
                            "target_assets": ["$target_asset"],
                            "expected": {
                                "scenario": "save inventory, clear runtime state, load, and compare ItemId/quantity/version"
                            },
                            "start_pie": True,
                        },
                    },
                    "success": "A save/load graph and PIE round-trip fixture preserve stable item identifiers, quantities, and version data while handling missing or old data safely.",
                }
            ]
        )
    if any(term in lower for term in ("replicate", "replicated", "replication", "multiplayer", "networked", "server authoritative")):
        specs.append(
            {
                "domain": "networking",
                "title": "Define and validate server-authoritative replication",
                "operations": [
                    "blueprint.configure_replication",
                    "network.inspect_authority_flow",
                    "runtime.multiplayer_pie_validate",
                ],
                "operation_arguments": {
                    "blueprint.configure_replication": {
                        "blueprint_path": "$target_asset",
                        "rep_notify_variables": replicated_variables,
                        "server_rpc_functions": server_rpcs,
                        "reliable": True,
                        "save": True,
                    },
                    "network.inspect_authority_flow": {
                        "blueprint_path": "$target_asset",
                        "required_variables": replicated_variables,
                        "required_server_rpcs": server_rpcs,
                        "required_onrep_functions": onrep_functions,
                    },
                    "runtime.multiplayer_pie_validate": {
                        "target_assets": ["$target_asset"],
                        "client_count": 2,
                        "start_pie": True,
                        "expected": {
                            "minimum_pie_worlds": 2,
                            "assertions": network_assertions,
                        },
                    },
                },
                "success": "Authority, ownership, prediction, and replicated state are verified with at least two PIE clients.",
            }
        )
    if any(term in lower for term in ("material", "dissolve", "metasound", "audio", "sound")):
        specs.append(
            {
                "domain": "presentation",
                "title": "Coordinate material, audio, and effect presentation",
                "operations": [
                    "material.inspect",
                    "material.set_parameter",
                    "audio.inspect",
                    "audio.set_parameter",
                ],
                "success": "Visual/audio parameters are driven from one gameplay state and return to stable defaults.",
            }
        )
    if re.search(r"\b(?:rollback|restore|revert|snapshot)\b", lower):
        specs.append(
            {
                "domain": "rollback",
                "title": "Journal every mutation and prove rollback",
                "operations": [
                    "rollback.record_asset_snapshot",
                    "rollback.latest",
                    "rollback.restore_asset_snapshot",
                ],
                "operation_arguments": {
                    "rollback.record_asset_snapshot": {
                        "asset_path": "$each_existing_asset_before_mutation",
                        "reason": "$planned_mutation_reason",
                        "operation": "$planned_operation",
                        "metadata": {
                            "request_id": "$request_id",
                            "dependency_stage": "$current_dependency_stage",
                        },
                    },
                    "rollback.restore_asset_snapshot": {
                        "token": "$recorded_snapshot_token",
                    },
                },
                "success": (
                    "Every existing asset mutation has a pre-change snapshot token, created assets "
                    "are journaled separately, and a disposable restore/readback fixture passes."
                ),
            }
        )
    behavior = dict(behavior_decomposition or {})
    for row in behavior.get("selected_primitives") or []:
        row = dict(row)
        if row.get("always") and not row.get("match_evidence"):
            continue
        specs.append(
            {
                "domain": "behavior_" + str(row.get("key") or "generated").replace(".", "_"),
                "title": "Implement behavior: " + str(row.get("title") or row.get("key") or "prompt behavior"),
                "operations": [
                    "rollback.record_asset_snapshot",
                    "blueprint.scan",
                    "blueprint.search_node_actions",
                    "blueprint.describe_node_action",
                    "blueprint.probe_node_action",
                    "blueprint.apply_graph_spec",
                    "blueprint.compile",
                    "blueprint.get_compile_errors",
                ],
                "operation_arguments": {
                    "rollback.record_asset_snapshot": {
                        "asset_path": "$target_asset",
                        "reason": "Before behavior graph synthesis",
                        "operation": "blueprint.apply_graph_spec",
                    },
                    "blueprint.scan": {
                        "asset_path": "$target_asset",
                        "include_graphs": True,
                        "include_defaults": True,
                    },
                    "blueprint.search_node_actions": {
                        "blueprint_path": "$target_asset",
                        "graph_name": "EventGraph",
                        "query": " ".join(
                            [
                                str(row.get("title") or ""),
                                str(row.get("trigger") or ""),
                                *[str(value) for value in row.get("observations") or []],
                                *[str(value) for value in row.get("guards") or []],
                                *[str(value) for value in row.get("outcomes") or []],
                            ]
                        ),
                    },
                    "blueprint.describe_node_action": {
                        "blueprint_path": "$target_asset",
                        "graph_name": "EventGraph",
                        "palette_action": "$selected_blueprint_action",
                    },
                    "blueprint.probe_node_action": {
                        "blueprint_path": "$target_asset",
                        "graph_name": "EventGraph",
                        "palette_action": "$selected_blueprint_action",
                    },
                    "blueprint.apply_graph_spec": {
                        "blueprint_path": "$target_asset",
                        "graph_name": "EventGraph",
                        "graph_spec": {
                            "behavior_id": row.get("id") or row.get("key"),
                            "title": row.get("title"),
                            "trigger": row.get("trigger"),
                            "observations": list(row.get("observations") or []),
                            "guards": list(row.get("guards") or []),
                            "states": list(row.get("states") or []),
                            "transitions": list(row.get("transitions") or []),
                            "outcomes": list(row.get("outcomes") or []),
                            "failure_paths": list(row.get("failure_paths") or []),
                        },
                    },
                    "blueprint.compile": {"asset_path": "$target_asset"},
                    "blueprint.get_compile_errors": {
                        "blueprint_path": "$target_asset"
                    },
                },
                "success": "; ".join(str(value) for value in row.get("proof_scenarios") or [])
                or (
                    "The behavior's declared trigger, observations, guards, states, outcomes, "
                    "and failure paths compile and pass runtime proof."
                ),
            }
        )
    if re.search(r"\bstate\w*\b", lower) and re.search(
        r"\b(?:anim(?:ation)?\s*blueprint|anim\s*instance|abp_[a-z0-9_]+)\b", lower
    ):
        specs.append(
            {
                "domain": "animation_state_integration",
                "title": "Propagate authoritative character state into the AnimBlueprint",
                "operations": [
                    "blueprint.scan",
                    "blueprint.apply_graph_spec",
                    "blueprint.compile_and_save",
                ],
                "operation_arguments": {
                    "blueprint.scan": {
                        "asset_path": "$target_animation_blueprint",
                        "include_graphs": True,
                        "include_defaults": True,
                    },
                    "blueprint.apply_graph_spec": {
                        "blueprint_path": "$target_animation_blueprint",
                        "graph_name": "BlueprintUpdateAnimation",
                        "graph_spec": {
                            "purpose": "Read authoritative traversal state from owning character",
                            "source_blueprint": "$target_asset",
                            "state_variables": requested_anim_states,
                            "required_flow": [
                                "Try Get Pawn Owner",
                                "validated character/interface access",
                                "copy authoritative state into AnimInstance variables",
                            ],
                        },
                    },
                    "blueprint.compile_and_save": {
                        "anim_bp_path": "$target_animation_blueprint"
                    },
                },
                "success": "Every requested animation state is copied from the owning character on each animation update and read back from the compiled graph.",
            }
        )
    if any(term in lower for term in ("animation", "montage", "animblueprint", "anim blueprint")):
        specs.append(
            {
                "domain": "animation_graph_integration",
                "title": "Bind contextually accepted animation roles through the final pose path",
                "operations": [
                    "animation.find_compatible",
                    "animation.get_state_machine_graph",
                    "anim_graph.wire_state_machine_to_output_pose",
                    "blueprint.compile_and_save",
                ],
                "operation_arguments": {
                    "animation.find_compatible": {
                        "skeleton_path": "$target_skeleton",
                        "directory": "$project_animation_folder",
                    },
                    "animation.get_state_machine_graph": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "anim_graph.wire_state_machine_to_output_pose": {
                        "anim_bp_path": "$target_animation_blueprint",
                        "state_machine_name": "$resolved_locomotion_state_machine",
                    },
                    "blueprint.compile_and_save": {
                        "anim_bp_path": "$target_animation_blueprint"
                    },
                },
                "success": "Each behavior has a skeleton-compatible, contextually accepted animation and its required slot or state reaches Output Pose.",
            }
        )
    specs.append(
        {
            "domain": "orchestration",
            "title": "Execute the approved dependency graph transactionally",
            "operations": ["feature.execute_generic_plan"],
            "success": "The approved plan can resume after each acquired capability, back up touched assets, and roll back failed stages.",
        }
    )
    specs.append(
        {
            "domain": "validation",
            "title": "Compile, inspect, run, and review diagnostics",
            "operations": [
                "blueprint.compile",
                "asset.save",
                "blueprint.scan",
                "niagara.inspect_system" if "niagara" in lower else "assets.inspect",
                "animation.inspect_notifies" if animation_notify_requested else "assets.inspect",
                "runtime.pie_validate",
                "diagnostics.read_log_errors",
            ],
            "operation_arguments": {
                "blueprint.compile": {"asset_path": "$each_touched_blueprint"},
                "asset.save": {"asset_path": "$each_touched_asset"},
                "blueprint.scan": {"asset_path": "$each_touched_blueprint"},
                "runtime.pie_validate": {
                    "target_assets": "$all_touched_runtime_assets",
                    "start_pie": True,
                    "expected": "$prompt_derived_runtime_postconditions",
                },
            },
            "success": "All touched assets compile and runtime evidence proves behavior without new warnings or errors.",
        }
    )
    if re.search(r"\b(?:report|full\s+results?|asset\s+paths?|readback)\b", lower):
        specs.append(
            {
                "domain": "reporting",
                "title": "Report exact execution contracts and readback evidence",
                "operations": [
                    "animation.report_pipeline_assets",
                    "diagnostics.read_log_errors",
                    "rollback.latest",
                ],
                "success": (
                    "The result names every planned operation, resolved callable, argument, dependency, "
                    "affected asset path, rollback token, elapsed stage time, and postcondition readback."
                ),
            }
        )
    return specs


_COVERAGE_STOP_WORDS = {
    "a", "all", "and", "any", "asset", "assets", "build", "create", "current",
    "every", "for", "from", "implement", "in", "into", "of", "on", "only",
    "please", "requested", "stack", "the", "to", "unreal", "use", "using", "with",
}


def _coverage_terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", str(text or "").lower().replace("_", " ")))
    aliases = {
        "animblueprint": {"animation", "blueprint", "animgraph"},
        "abp": {"animation", "blueprint", "animgraph"},
        "physicsasset": {"physics", "profile", "constraint"},
        "repnotify": {"replication", "network", "onrep"},
        "retargeter": {"retarget", "ik"},
        "retargeting": {"retarget", "ik"},
        "diagnostics": {"log", "errors"},
        "readback": {"report", "evidence", "inspect"},
    }
    expanded = set(words)
    for word in words:
        expanded.update(aliases.get(word, set()))
        if len(word) > 4 and word.endswith("ing"):
            expanded.add(word[:-3])
        elif len(word) > 4 and word.endswith("ed"):
            expanded.add(word[:-2])
        elif len(word) > 4 and word.endswith("s"):
            expanded.add(word[:-1])
    return {word for word in expanded if len(word) > 1 and word not in _COVERAGE_STOP_WORDS}


def _prompt_clause_operation_coverage(
    prompt: str,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prove that each source clause reaches one or more concrete operation chains."""

    from tech_connector.services.unreal.behavior_capability_decomposition_service import _clauses

    rows = []
    for clause_index, clause in enumerate(_clauses(prompt), 1):
        clause_terms = _coverage_terms(clause)
        matches = []
        represented_terms: set[str] = set()
        for requirement_index, requirement in enumerate(requirements, 1):
            operations = [str(value) for value in requirement.get("operations") or [] if value]
            requirement_text = " ".join(
                [
                    str(requirement.get("domain") or ""),
                    str(requirement.get("title") or ""),
                    str(requirement.get("success") or ""),
                    *operations,
                ]
            )
            requirement_terms = _coverage_terms(requirement_text)
            overlap = clause_terms.intersection(requirement_terms)
            overlap_ratio = len(overlap) / max(1, len(clause_terms))
            if not overlap or (
                len(overlap) < 3
                and overlap_ratio < 0.2
                and len(clause_terms) > 3
            ):
                continue
            matches.append(
                {
                    "requirement_id": f"requirement_{requirement_index:02d}",
                    "domain": requirement.get("domain"),
                    "title": requirement.get("title"),
                    "operations": operations,
                    "matched_terms": sorted(overlap),
                    "_coverage_score": round(overlap_ratio, 4),
                }
            )
        matches.sort(
            key=lambda row: (
                float(row.get("_coverage_score") or 0.0),
                len(row.get("matched_terms") or []),
            ),
            reverse=True,
        )
        matches = matches[:8]
        for match in matches:
            represented_terms.update(
                _coverage_terms(
                    " ".join(
                        [
                            str(match.get("domain") or ""),
                            str(match.get("title") or ""),
                            *list(match.get("operations") or []),
                        ]
                    )
                )
            )
            match.pop("_coverage_score", None)
        covered = bool(matches)
        rows.append(
            {
                "clause_id": f"clause_{clause_index:02d}",
                "source_clause": clause,
                "classification": "operation_chain" if covered else "unresolved",
                "covered": covered,
                "covered_by": [row["requirement_id"] for row in matches],
                "operation_count": sum(len(row["operations"]) for row in matches),
                "requirements": matches,
                "unrepresented_terms": sorted(clause_terms - represented_terms),
            }
        )
    uncovered = [row["source_clause"] for row in rows if not row["covered"]]
    return {
        "framework": "unreal_prompt_clause_operation_coverage_v1",
        "source_prompt": prompt,
        "clauses": rows,
        "clause_count": len(rows),
        "covered_clause_count": len(rows) - len(uncovered),
        "coverage_ratio": (
            round((len(rows) - len(uncovered)) / len(rows), 4) if rows else 1.0
        ),
        "uncovered_clauses": uncovered,
        "complete": not uncovered,
    }


def _is_narrow_stamina_sprint_request(prompt: str) -> bool:
    """Keep the legacy specialization only for a compact stamina/sprint-only ask."""

    from tech_connector.services.unreal.behavior_capability_decomposition_service import _clauses

    lower = str(prompt or "").lower()
    if "stamina" not in lower or "sprint" not in lower:
        return False
    unrelated_domains = re.compile(
        r"\b(?:niagara|pose\s+search|motion\s+matching|retarget|ik\s+rig|"
        r"physics\s*asset|physicsasset|state\s+machine|transition\s+rule|"
        r"root\s+motion|additive|multiplayer|two-client|prone|crawl|mantle)\b"
    )
    return (
        len(prompt or "") < 500
        and len(_clauses(prompt)) <= 2
        and not unrelated_domains.search(lower)
    )


def build_unreal_requirement_preview(prompt: str) -> dict[str, Any]:
    """Expose the deterministic feature stages before target discovery completes."""
    requirements = _generic_requirement_specs(prompt)
    clause_coverage = _prompt_clause_operation_coverage(prompt, requirements)
    operations = []
    for requirement_index, requirement in enumerate(requirements, 1):
        for operation_index, operation in enumerate(requirement["operations"], 1):
            status = _local_operation_status(operation)
            definition = None
            try:
                from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

                definition = UNREAL_OPERATIONS.get(operation)
            except Exception:
                pass
            operations.append(
                {
                    "id": f"requirement_{requirement_index:02d}_operation_{operation_index:02d}",
                    "phase": requirement["title"],
                    "domain": requirement["domain"],
                    "operation": operation,
                    "function": status.get("function") or "",
                    "required_arguments": list(definition.required) if definition else [],
                    "optional_arguments": dict(definition.optional) if definition else {},
                    "planned_arguments": dict(
                        (requirement.get("operation_arguments") or {}).get(operation) or {}
                    ),
                    "callable": bool(status.get("callable_found")),
                    "mutates_project": bool(definition.mutates_project) if definition else False,
                    "postcondition": requirement["success"],
                }
            )
    return {
        "framework": "unreal_requirement_preview_v1",
        "requirements": requirements,
        "operations": operations,
        "clause_coverage": clause_coverage,
        "missing_operations": [
            row["operation"] for row in operations if not row["callable"]
        ],
    }


def _generic_unreal_feature_plan(
    prompt: str,
    evidence: dict[str, Any],
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Build an evidence-backed plan that turns unknown operations into acquisition work."""

    from tech_connector.services.task_playbook_service import matching_playbooks
    from tech_connector.services.gameplay_proof_contract_service import build_gameplay_proof_contract
    from tech_connector.services.unreal.behavior_capability_decomposition_service import (
        decompose_prompt_behaviors,
        synthesize_novel_behavior_contract,
    )
    from tech_connector.services.unreal.evidence_driven_feature_synthesis_service import (
        build_feature_research_plan,
        derive_prompt_requirement_contract,
    )
    from tech_connector.services.unreal.expert_technique_registry import select_expert_techniques
    from tech_connector.services.unreal.implementation_plan_synthesis_service import (
        synthesize_detailed_implementation_plan,
    )
    from tech_connector.services.unreal.unreal_task_sequence_service import (
        build_unreal_task_sequence,
        verify_unreal_task_sequence,
    )

    task_observer_events: list[dict[str, Any]] = []

    def emit_task_event(event: dict[str, Any]) -> None:
        row = dict(event or {})
        task_observer_events.append(row)
        if progress:
            progress(
                "TASK_EVENT:"
                + json.dumps(row, separators=(",", ":"), default=str)
            )
    playbooks = matching_playbooks(prompt, host="unreal", limit=4)
    blueprint = dict(evidence.get("blueprint") or {})
    assets = dict(evidence.get("assets") or {})
    skeletal_mesh = next(
        (
            str(row.get("skeletal_mesh_asset") or "")
            for row in blueprint.get("components") or []
            if row.get("skeletal_mesh_asset")
        ),
        "",
    )
    animation_blueprints = list(evidence.get("animation_blueprints") or [])
    related_animations = list(assets.get("related_animations") or [])
    unknowns = []
    lower = prompt.lower()
    if re.search(r"\b(?:attach|attachment|socket)\b", lower) or re.search(
        r"\b(?:bone|hand)\b.{0,40}\b(?:attach|spawn|parent|socket)\b", lower
    ):
        unknowns.append("Exact target bone/socket is not yet present in the live evidence and must be queried from the skeleton.")
    if "duplicate" in lower and not related_animations:
        unknowns.append("No compatible source animation has been selected yet.")
    elif "duplicate" in lower:
        unknowns.append("A compatible source animation must be selected from the live candidates before duplication.")
    if "niagara" in lower:
        unknowns.append("Existing Niagara systems/materials/modules have not yet been inventoried for reuse.")
    target = str(evidence.get("target_asset") or "")
    project_context = {
        "target_asset": target,
        "target_parent_class": blueprint.get("parent_class"),
        "skeletal_mesh": skeletal_mesh,
        "animation_blueprint": (animation_blueprints[0].get("asset_path") if animation_blueprints else ""),
        "target_skeleton": assets.get("target_skeleton") or assets.get("skeleton") or "",
    }
    requirement_contract = derive_prompt_requirement_contract(prompt)
    initial_behavior = decompose_prompt_behaviors(prompt)
    initial_requirements = _generic_requirement_specs(prompt, initial_behavior)
    initial_clause_coverage = _prompt_clause_operation_coverage(
        prompt, initial_requirements
    )
    emit_task_event(
        {
            "type": "decomposition_completed",
            "clause_count": initial_clause_coverage["clause_count"],
            "requirement_count": len(initial_requirements),
        }
    )
    model_synthesis = {}
    if (
        not initial_clause_coverage["complete"]
        and evidence.get("allow_model_behavior_synthesis")
    ):
        model_synthesis = synthesize_novel_behavior_contract(
            prompt,
            project_context=project_context,
        )
    behavior = decompose_prompt_behaviors(prompt, model_synthesis=model_synthesis)
    requirements = _generic_requirement_specs(prompt, behavior)
    clause_coverage = _prompt_clause_operation_coverage(prompt, requirements)
    operation_status: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        for operation in requirement["operations"]:
            operation_status.setdefault(operation, _local_operation_status(operation))
    for operation in (
        "blueprint.apply_graph_spec",
        "blueprint.get_compile_errors",
        "runtime.pie_begin",
        "runtime.pie_status",
        "runtime.pie_end",
        "runtime.inject_key",
        "runtime.inspect_character",
        "runtime.validate_character_montages",
    ):
        operation_status.setdefault(operation, _local_operation_status(operation))
    task_sequence = build_unreal_task_sequence(
        requirements,
        clause_coverage,
        operation_status,
    )
    emit_task_event(
        {
            "type": "task_sequence_created",
            "task_count": task_sequence["task_count"],
        }
    )
    task_verification = {
        "framework": "unreal_task_sequence_verification_v1",
        "status": "not_requested",
        "verified": clause_coverage["complete"],
        "failed_clause_ids": [],
        "verdicts": [],
        "batches": [],
        "elapsed_ms": 0.0,
    }
    if clause_coverage["complete"] and evidence.get("allow_model_behavior_synthesis"):
        task_verification = verify_unreal_task_sequence(
            task_sequence,
            event=emit_task_event,
        )
    emit_task_event(
        {
            "type": "task_verification_finished",
            "verified": bool(task_verification.get("verified")),
            "failed_clause_ids": list(
                task_verification.get("failed_clause_ids") or []
            ),
        }
    )
    missing = [status for status in operation_status.values() if not status["callable_found"]]
    graph_namespaces = {"animation", "collision", "combat", "input", "movement", "physics", "state"}
    graph_executor_ready = operation_status["blueprint.apply_graph_spec"]["callable_found"]
    acquisition_missing = [
        status for status in missing
        if not (
            graph_executor_ready
            and str(status.get("operation") or "").partition(".")[0] in graph_namespaces
        )
    ]
    detected_domains = list(dict.fromkeys(row["domain"] for row in requirements))
    implementation_steps = []
    for index, requirement in enumerate(requirements, 1):
        statuses = [operation_status[operation] for operation in requirement["operations"]]
        implementation_steps.append(
            {
                "step": index,
                "title": requirement["title"],
                "domain": requirement["domain"],
                "operations": list(requirement["operations"]),
                "operation_arguments": dict(requirement.get("operation_arguments") or {}),
                "available_operations": [row["operation"] for row in statuses if row["callable_found"]],
                "missing_operations": [row["operation"] for row in statuses if not row["callable_found"]],
                "detail": requirement["success"],
            }
        )
    acquisition_steps = []
    for index, status in enumerate(acquisition_missing, 1):
        operation = status["operation"]
        acquisition_steps.append(
            {
                "step": index,
                "capability": operation,
                "current_evidence": status,
                "actions": [
                    "Search the maintained project index and local tool packages for an equivalent callable.",
                    "Probe live UE 5.8 Python reflection for the exact supported API and asset type.",
                    "Implement a bounded first-party bridge adapter when no reusable callable exists.",
                    "Register the concrete function in UNREAL_OPERATIONS with accurate mutability and parameters.",
                    "Run syntax/unit tests, then a live dry-run or disposable-asset test with postcondition readback.",
                    "Resume the original feature plan at the blocked operation; do not substitute a fabricated call.",
                ],
                "done_when": f"`{operation}` resolves to a real callable and passes its live postcondition test.",
            }
        )
    technique_selection = select_expert_techniques(
        prompt,
        required_domains=detected_domains,
        project_context=project_context,
    )
    gameplay_proof = build_gameplay_proof_contract(prompt).to_dict()
    architecture_decision = {
        "state_owner": "Reusable ActorComponent generated from the behavior contract",
        "character_integration": "Thin Enhanced Input and lifecycle calls on the resolved played character",
        "animation_integration": "Extend the current AnimBlueprint through explicit state data and verified slot/layer paths",
        "selection_basis": "Live project ownership, composed behavior count, existing project conventions, and selected versioned techniques",
        "network_policy": "Preserve CharacterMovement authority; require explicit replication/prediction proof before multiplayer completion",
    }
    detailed_plan = synthesize_detailed_implementation_plan(
        prompt,
        requirement_contract=requirement_contract,
        project_context=project_context,
        architecture_decision=architecture_decision,
        techniques=technique_selection.get("techniques") or [],
        implementation_steps=implementation_steps,
        operation_status=operation_status.values(),
        gameplay_proof_contract=gameplay_proof,
        animation_candidates=related_animations,
        behavior_decomposition=behavior,
    )
    research_plan = build_feature_research_plan(
        prompt,
        engine_version="5.8",
        project_evidence=evidence,
    )
    detailed_readiness = dict(detailed_plan.get("readiness") or {})
    plan_status = (
        "semantic_task_repair_required"
        if not task_verification.get("verified")
        else "capability_acquisition_required"
        if acquisition_missing
        else "approval_ready"
        if detailed_readiness.get("ready_for_approval")
        else "implementation_spec_incomplete"
    )
    result = {
        "framework": "unreal_generic_feature_plan_v2",
        "status": plan_status,
        "request": prompt,
        "feature": "generic_unreal_feature",
        "target_asset": target,
        "detected_domains": detected_domains,
        "matched_playbooks": [
            {"key": playbook.key, "title": playbook.title, "summary": playbook.summary}
            for playbook in playbooks
        ],
        "requirement_contract": requirement_contract,
        "prompt_clause_coverage": clause_coverage,
        "task_sequence": task_sequence,
        "task_sequence_verification": task_verification,
        "task_observer_events": task_observer_events,
        "behavior_decomposition": behavior,
        "novel_behavior_synthesis": model_synthesis,
        "expert_technique_selection": technique_selection,
        "architecture_decision": architecture_decision,
        "detailed_implementation_plan": detailed_plan,
        "gameplay_proof_contract": gameplay_proof,
        "research_plan": research_plan,
        "evidence": {
            "target_parent_class": blueprint.get("parent_class"),
            "skeletal_mesh": skeletal_mesh,
            "animation_blueprint": (animation_blueprints[0].get("asset_path") if animation_blueprints else ""),
            "related_animation_candidates": related_animations[:20],
            "related_blueprints": list(assets.get("related_blueprints") or [])[:20],
            "live_evidence_sufficient": bool(evidence.get("sufficient")),
        },
        "affected_assets": [
            {"path": target, "change": "modify only after exact graph/component targets are reconfirmed"},
            {"path": "proposed feature assets", "change": "names and folders resolved from project conventions before creation"},
            {"path": "duplicated test assets", "change": "source assets remain unchanged"},
        ],
        "implementation_steps": implementation_steps,
        "operation_status": list(operation_status.values()),
        "missing_capabilities": [
            {
                "capability": row["operation"],
                "reason": row["reason"],
                "registered": row["registered"],
                "function": row["function"],
            }
            for row in acquisition_missing
        ],
        "build_readiness": {
            "ready": not acquisition_missing and bool(detailed_readiness.get("ready_for_approval")),
            "blocked_by": [row["operation"] for row in acquisition_missing],
            "errors": list(detailed_readiness.get("errors") or []),
        },
        "capability_acquisition": acquisition_steps,
        "unknowns": unknowns,
        "validation": [
            requirement["success"] for requirement in requirements if requirement["domain"] == "validation"
        ] + [
            "No source animation or unrelated Blueprint is modified.",
            "Every created/modified asset and exact runtime diagnostic is reported.",
        ],
        "rollback": [
            "Duplicate or back up every existing asset before mutation.",
            "Create new feature assets in an isolated project-convention folder so they can be removed independently.",
            "On failed compile or postcondition, restore modified assets and remove only assets created by this plan.",
            "Never bypass unrelated project compile/runtime errors; report them separately from feature failures.",
        ],
        "approval_gate": {
            "required": True,
            "changes_applied": False,
            "scope": "capability adapters, then exact Unreal assets",
            "message": (
                "Approve this plan before mutating Unreal assets."
                if plan_status == "approval_ready"
                else "Approval is disabled until every detailed-readiness error and callable gap is resolved."
            ),
        },
        "self_review": {
            "request_covered": bool(detected_domains) and clause_coverage["complete"],
            "prompt_clause_coverage_complete": clause_coverage["complete"],
            "prompt_clause_coverage_ratio": clause_coverage["coverage_ratio"],
            "task_sequence_verified": bool(task_verification.get("verified")),
            "live_evidence_sufficient": bool(evidence.get("sufficient")),
            "unknowns_are_explicit": True,
            "fabricated_operations": False,
            "all_operations_verified": not missing,
            "implementation_spec_ready": bool(detailed_readiness.get("ready_for_approval")),
            "original_goal_preserved_after_acquisition": True,
        },
    }
    if behavior.get("knowledge_required") and not clause_coverage["complete"]:
        result["unknowns"] = list(dict.fromkeys([
            *result.get("unknowns", []),
            *behavior.get("unmatched_behavior_clauses", []),
        ]))
        result["status"] = "capability_acquisition_required"
    if not task_verification.get("verified"):
        failed_ids = set(task_verification.get("failed_clause_ids") or [])
        failed_clauses = [
            str(row.get("source_clause") or "")
            for row in clause_coverage.get("clauses") or []
            if str(row.get("clause_id") or "") in failed_ids
        ]
        result["unknowns"] = list(dict.fromkeys([
            *result.get("unknowns", []),
            *failed_clauses,
        ]))
        result["status"] = "semantic_task_repair_required"
        result["approval_gate"]["message"] = (
            "Approval is disabled until the failed focused task checks are repaired "
            "and reverified."
        )
    if not clause_coverage["complete"]:
        result["unknowns"] = list(dict.fromkeys([
            *result.get("unknowns", []),
            *clause_coverage["uncovered_clauses"],
        ]))
        result["status"] = "implementation_spec_incomplete"
        result["approval_gate"]["message"] = (
            "Approval is disabled because one or more source prompt clauses have no "
            "concrete operation chain."
        )
    return result


def build_live_unreal_feature_plan(
    prompt: str,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    target = _asset_token(prompt)
    if progress:
        progress("Calling live Unreal Blueprint inspection")
    ok, evidence, bridge_seconds = _call_live_context(prompt, target)
    if not ok:
        return {
            "framework": "unreal_feature_approval_plan_v1",
            "status": "evidence_failed",
            "request": prompt,
            "target_asset": target,
            "evidence": evidence,
            "bridge_seconds": bridge_seconds,
            "approval_gate": {"required": True, "changes_applied": False},
        }
    if progress:
        progress("Live Unreal evidence ready; building approval plan")
    if _is_narrow_stamina_sprint_request(prompt):
        plan = _stamina_sprint_plan(prompt, evidence)
    else:
        evidence["allow_model_behavior_synthesis"] = True
        plan = _generic_unreal_feature_plan(prompt, evidence, progress=progress)
    plan["bridge_seconds"] = bridge_seconds
    plan["live_evidence"] = evidence
    return plan


def render_unreal_feature_plan(plan: dict[str, Any]) -> str:
    status = str(plan.get("status") or "")
    if status not in {
        "approval_ready",
        "capability_acquisition_required",
        "implementation_spec_incomplete",
        "knowledge_choice_required",
        "semantic_task_repair_required",
    }:
        errors = list((plan.get("evidence") or {}).get("errors") or [])
        return "Unreal feature planning stopped because live evidence was insufficient.\n\n" + (
            "Errors: " + "; ".join(str(item) for item in errors)
            if errors else "No assets were changed."
        )
    evidence = dict(plan.get("evidence") or {})
    if plan.get("framework") == "unreal_generic_feature_plan_v2":
        detailed = dict(plan.get("detailed_implementation_plan") or {})
        behavior = dict(plan.get("behavior_decomposition") or {})
        proof = dict(plan.get("gameplay_proof_contract") or {})
        lines = [
            (
                "Unreal implementation plan ready for approval"
                if status == "approval_ready"
                else "Unreal implementation plan is not ready for approval"
            ),
            "",
            "Project Context:",
            f"Target: `{plan.get('target_asset')}`",
            f"Live bridge evidence: `{plan.get('bridge_seconds', 0):.2f}s`",
            "Domains: " + ", ".join(f"`{item}`" for item in plan.get("detected_domains") or []),
            f"Skeletal mesh: `{evidence.get('skeletal_mesh') or 'not resolved'}`",
            f"Animation Blueprint: `{evidence.get('animation_blueprint') or 'not resolved'}`",
            "",
            "What I'll Build:",
            f"- Feature: `{detailed.get('feature') or 'unresolved feature'}`",
            "State owner: " + str(dict(detailed.get("proposed_architecture") or {}).get("state_owner") or "not resolved"),
            "- Animation roles: " + ", ".join(
                f"`{role}`" for role in dict(detailed.get("animation_integration") or {}).get("required_roles") or []
            ),
            "- Animation candidates remain `candidate_only` until compatibility, contextual preview, graph consumption, and PIE evidence pass.",
            "",
            "Generated State Flow:",
            " -> ".join(
                f"`{state}`" for state in dict(detailed.get("proposed_architecture") or {}).get("state_flow") or []
            ),
            "",
            "Behavior contract:",
        ]
        lines.extend(f"- Observation: {item}" for item in behavior.get("observations") or [])
        lines.extend(f"- Guard: {item}" for item in behavior.get("guards") or [])
        lines.extend(f"- State: `{item}`" for item in behavior.get("states") or [])
        for transition in behavior.get("transitions") or []:
            transition = dict(transition)
            lines.append(
                "- Transition: `{} -> {}` on `{}`; guards: {}".format(
                    transition.get("from"),
                    transition.get("to"),
                    transition.get("event"),
                    ", ".join(str(value) for value in transition.get("guards") or []) or "none",
                )
            )
        task_verification = dict(plan.get("task_sequence_verification") or {})
        if (
            behavior.get("unmatched_behavior_clauses")
            and not task_verification.get("verified")
        ):
            lines.append(
                "- Unresolved clauses: "
                + "; ".join(str(item) for item in behavior["unmatched_behavior_clauses"])
            )
        coverage = dict(plan.get("prompt_clause_coverage") or {})
        lines.extend(
            [
                "",
                "Request coverage:",
                f"- Clauses: `{coverage.get('covered_clause_count', 0)}/{coverage.get('clause_count', 0)}`",
                f"- Focused verifier: `{task_verification.get('status') or 'not run'}`",
                f"- Verification time: `{float(task_verification.get('elapsed_ms') or 0.0) / 1000.0:.2f}s`",
            ]
        )
        lines.extend([
            "",
            "Matched local playbooks:",
        ])
        lines.extend(
            f"- `{row.get('key')}`: {row.get('title')}"
            for row in plan.get("matched_playbooks") or []
        )
        lines.extend(["", "Implementation:"])
        for row in plan.get("implementation_steps") or []:
            lines.append(f"{row.get('step')}. {row.get('title')}: {row.get('detail')}")
            lines.append("   Operations: " + ", ".join(f"`{item}`" for item in row.get("operations") or []))
            if row.get("missing_operations"):
                lines.append("   Needs acquisition: " + ", ".join(f"`{item}`" for item in row["missing_operations"]))
        task_sequence = dict(plan.get("task_sequence") or {})
        if task_sequence.get("tasks"):
            lines.extend(
                [
                    "",
                    f"Dependency-ordered task sequence ({task_sequence.get('task_count', 0)} tasks):",
                ]
            )
            for task in task_sequence.get("tasks") or []:
                dependencies = ", ".join(
                    f"`{value}`" for value in task.get("depends_on") or []
                ) or "none"
                lines.append(
                    f"- `{task.get('task_id')}` {task.get('title')} "
                    f"[depends on: {dependencies}]"
                )
                for operation in task.get("operations") or []:
                    lines.append(
                        "  - `{}` -> `{}` args={} postcondition={}".format(
                            operation.get("operation"),
                            operation.get("function") or "unresolved",
                            json.dumps(
                                operation.get("arguments") or {},
                                separators=(",", ":"),
                                default=str,
                            ),
                            operation.get("postcondition") or "",
                        )
                    )
        if detailed.get("action_graph"):
            lines.extend(["", "Executable action graph:"])
            for action in detailed.get("action_graph") or []:
                unresolved = list(action.get("unresolved_params") or [])
                blocked = bool(unresolved or not action.get("callable"))
                suffix = "BLOCKED: " + ", ".join(unresolved) if blocked else "ready"
                lines.append(f"- `{action.get('id')}` `{action.get('operation')}`: {suffix}")
        if detailed.get("input_arbitration"):
            lines.extend(["", "Input arbitration:"])
            for arbitration in detailed.get("input_arbitration") or []:
                order = " > ".join(
                    str(value.get("title") or value.get("behavior_id"))
                    for value in arbitration.get("ordered_candidates") or []
                )
                lines.append(f"- `{arbitration.get('input')}`: {order}")
                for tie in arbitration.get("unresolved_ties") or []:
                    lines.append("  BLOCKED tie: " + " vs ".join(str(value) for value in tie))
        role_bindings = list(dict(detailed.get("animation_integration") or {}).get("role_bindings") or [])
        if role_bindings:
            lines.extend(["", "Animation role evidence:"])
            for binding in role_bindings:
                lines.append(
                    f"- `{binding.get('role')}`: {binding.get('status')}; selected asset: "
                    f"`{binding.get('selected_asset') or 'none'}`"
                )
        fixtures = list(dict(detailed.get("proof_plan") or {}).get("fixtures") or [])
        if fixtures:
            lines.extend(["", f"Executable PIE fixtures: {len(fixtures)}"])
            lines.extend(
                f"- `{fixture.get('id')}` ({fixture.get('category')}): {fixture.get('action')}"
                for fixture in fixtures
            )
        readiness = dict(detailed.get("readiness") or {})
        if readiness.get("errors"):
            lines.extend(["", "Approval blockers:"])
            lines.extend(f"- {item}" for item in readiness.get("errors") or [])
        claims = list(proof.get("proof_claims") or [])
        if claims:
            lines.extend(["", "Runtime proof contract:"])
            for claim in claims:
                lines.append(
                    f"- L{claim.get('evidence_level')} `{claim.get('claim_id')}`: "
                    f"{claim.get('then_assertion') or claim.get('description')}"
                )
        if plan.get("unknowns"):
            lines.extend(["", "Evidence still to resolve:"])
            lines.extend(f"- {item}" for item in plan.get("unknowns") or [])
        if plan.get("capability_acquisition"):
            lines.extend(["", "Capability acquisition loop:"])
            for row in plan.get("capability_acquisition") or []:
                lines.append(f"{row.get('step')}. `{row.get('capability')}`: {row.get('done_when')}")
                reason = (row.get("current_evidence") or {}).get("reason")
                if reason:
                    lines.append("   Current evidence: " + str(reason))
        lines.extend(["", "Validation:"])
        lines.extend(f"- {item}" for item in plan.get("validation") or [])
        lines.extend(["", "Rollback:"])
        lines.extend(f"- {item}" for item in plan.get("rollback") or [])
        lines.extend(
            [
                "",
                "No Unreal assets or capability adapters were changed. Approval is required before acquisition or execution.",
            ]
        )
        return "\n".join(lines)
    lines = [
        "Unreal implementation plan ready for approval",
        "",
        f"Target: `{plan.get('target_asset')}`",
        f"Live bridge evidence: `{plan.get('bridge_seconds', 0):.2f}s`",
        f"Current movement: walk speed `{(evidence.get('movement_defaults') or {}).get('max_walk_speed')}`",
        f"Current AnimBP: `{evidence.get('animation_blueprint') or 'unknown'}`",
        f"Sprint input exists: `{'yes' if evidence.get('sprint_action_exists') else 'no'}`",
        "",
        "Affected assets:",
    ]
    for row in plan.get("affected_assets") or []:
        lines.append(f"- `{row.get('path')}`: {row.get('change')}")
    lines.extend(["", "Implementation:"])
    for row in plan.get("implementation_steps") or []:
        lines.append(f"{row.get('step')}. {row.get('title')}: {row.get('detail')}")
        lines.append("   Operations: " + ", ".join(f"`{item}`" for item in row.get("operations") or []))
    gaps = list(plan.get("missing_capabilities") or [])
    if gaps:
        lines.extend(["", "Capability gaps to bridge first:"])
        for row in gaps:
            lines.append(f"- `{row.get('capability')}`: {row.get('reason')}")
    lines.extend(["", "Validation:"])
    lines.extend(f"- {item}" for item in plan.get("validation") or [])
    lines.extend(["", "Rollback:"])
    lines.extend(f"- {item}" for item in plan.get("rollback") or [])
    lines.extend(["", "No Unreal assets were changed. Approval is required before execution."])
    return "\n".join(lines)


def render_unreal_blueprint_inspection(evidence: dict[str, Any], elapsed: float) -> str:
    blueprint = dict(evidence.get("blueprint") or {})
    lines = [
        f"Live Unreal Blueprint inspection: `{evidence.get('target_asset')}`",
        f"Bridge time: `{elapsed:.2f}s`",
        f"Parent: `{blueprint.get('parent_class') or 'unknown'}`",
        f"Variables: `{len(blueprint.get('variables') or [])}`",
        f"Functions: `{len(blueprint.get('functions') or [])}`",
        f"Graphs: `{len(blueprint.get('graphs') or [])}`",
        f"Components: `{len(blueprint.get('components') or [])}`",
    ]
    if blueprint.get("warnings"):
        lines.append("Warnings: " + "; ".join(str(item) for item in blueprint.get("warnings") or []))
    return "\n".join(lines)


def inspect_live_unreal_blueprint(prompt: str) -> dict[str, Any]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    bridge = UnrealBridge()
    function_path = "tech_connector.bridges.unreal.unreal_blueprint_inspection.scan_blueprint_by_query"
    started = time.perf_counter()
    ok, raw = bridge.call(
        function_path,
        args=[_asset_token(prompt)],
        kwargs={"include_graphs": True, "include_defaults": True},
        timeout=8,
        retries=0,
        retry_safe=True,
        operation="blueprint.scan",
    )
    if not ok and "has no attribute 'scan_blueprint_by_query'" in str(raw):
        bridge.execute_python(
            "import importlib\n"
            "import tech_connector.bridges.unreal.unreal_blueprint_inspection as inspection\n"
            "importlib.reload(inspection)\n"
            "'reloaded'",
            timeout=5,
            reset_globals=True,
        )
        ok, raw = bridge.call(
            function_path,
            args=[_asset_token(prompt)],
            kwargs={"include_graphs": True, "include_defaults": True},
            timeout=8,
            retries=0,
            retry_safe=True,
            operation="blueprint.scan",
        )
    try:
        blueprint = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        blueprint = {"sufficient": False, "errors": [str(raw)]}
    evidence = {
        "target_asset": blueprint.get("asset_path") or _asset_token(prompt),
        "blueprint": blueprint,
        "sufficient": bool(blueprint.get("sufficient")),
    }
    return {
        "ok": bool(ok) and bool(blueprint.get("sufficient")),
        "evidence": evidence,
        "bridge_seconds": time.perf_counter() - started,
    }
