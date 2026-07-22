"""Evidence-first planning for bounded Unreal Blueprint gameplay features."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
from typing import Any, Callable


ProgressCallback = Callable[[str], None]


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
        tree = ast.parse(origin.read_text(encoding="utf-8"), filename=str(origin))
        definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
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
    if any(term in lower for term in ("niagara", "particle", "vfx", "effect")):
        specs.extend(
            [
                {
                    "domain": "niagara",
                    "title": "Inspect or create the Niagara System",
                    "operations": ["niagara.inspect_system", "niagara.create_system"],
                    "success": "A Niagara System exists with a compiled emitter and a visible renderer.",
                },
                {
                    "domain": "niagara",
                    "title": "Author and bind Niagara user parameters",
                    "operations": [
                        "niagara.set_user_parameter",
                        "niagara.set_module_input",
                        "niagara.set_renderer_property",
                        "niagara.compile",
                    ],
                    "success": "Every requested User parameter exists and drives a concrete spawn/update/renderer input.",
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
                    "operations": ["blueprint.add_component", "blueprint.attach_component"],
                    "success": "The component is attached to the verified mesh and bone/socket and is inactive by default.",
                },
            ]
        )
    if any(term in lower for term in ("notify", "anim notify", "notifystate")):
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
    if any(term in lower for term in ("widget", " ui ", "hud", "save game", "savegame", "persist")):
        specs.extend(
            [
                {
                    "domain": "ui",
                    "title": "Create or extend the project UI using existing widget conventions",
                    "operations": ["ui.inspect_widgets", "ui.create_widget", "ui.bind_view_model"],
                    "success": "The UI reflects authoritative gameplay state without polling or duplicating ownership.",
                },
                {
                    "domain": "persistence",
                    "title": "Persist and restore the requested state",
                    "operations": ["savegame.inspect_schema", "savegame.create_schema", "savegame.validate_round_trip"],
                    "success": "A save/load round trip preserves the requested state and handles missing or old data safely.",
                },
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
    behavior = dict(behavior_decomposition or {})
    for row in behavior.get("selected_primitives") or []:
        row = dict(row)
        operations = list(dict.fromkeys(str(value) for value in row.get("operations") or [] if value))
        if not operations:
            continue
        specs.append(
            {
                "domain": "behavior_" + str(row.get("key") or "generated").replace(".", "_"),
                "title": "Implement behavior: " + str(row.get("title") or row.get("key") or "prompt behavior"),
                "operations": operations,
                "success": "; ".join(str(value) for value in row.get("proof_scenarios") or [])
                or "The behavior's declared states, guards, outcomes, and failure paths pass runtime proof.",
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
                    "state.read_owning_character_variables",
                    "state.write_anim_instance_variables",
                ],
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
                    "animation.bind_contextual_roles",
                    "animation.verify_slot_output_pose",
                ],
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
                "blueprint.scan",
                "niagara.inspect_system" if "niagara" in lower else "assets.inspect",
                "animation.inspect_notifies" if "notify" in lower else "assets.inspect",
                "runtime.pie_validate",
                "diagnostics.read_log_errors",
            ],
            "success": "All touched assets compile and runtime evidence proves behavior without new warnings or errors.",
        }
    )
    return specs


def _generic_unreal_feature_plan(prompt: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Build an evidence-backed plan that turns unknown operations into acquisition work."""

    from tech_connector.services.task_playbook_service import matching_playbooks
    from tech_connector.services.gameplay_proof_contract_service import build_gameplay_proof_contract
    from tech_connector.services.unreal.behavior_capability_decomposition_service import (
        decompose_prompt_behaviors,
        requires_prompt_specific_behavior_synthesis,
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
    model_synthesis = {}
    if (
        requires_prompt_specific_behavior_synthesis(prompt, initial_behavior)
        and evidence.get("allow_model_behavior_synthesis")
    ):
        model_synthesis = synthesize_novel_behavior_contract(
            prompt,
            project_context=project_context,
        )
    behavior = decompose_prompt_behaviors(prompt, model_synthesis=model_synthesis)
    requirements = _generic_requirement_specs(prompt, behavior)
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
        "capability_acquisition_required"
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
            "request_covered": bool(detected_domains),
            "live_evidence_sufficient": bool(evidence.get("sufficient")),
            "unknowns_are_explicit": True,
            "fabricated_operations": False,
            "all_operations_verified": not missing,
            "implementation_spec_ready": bool(detailed_readiness.get("ready_for_approval")),
            "original_goal_preserved_after_acquisition": True,
        },
    }
    if behavior.get("knowledge_required"):
        result["unknowns"] = list(dict.fromkeys([
            *result.get("unknowns", []),
            *behavior.get("unmatched_behavior_clauses", []),
        ]))
        result["status"] = "capability_acquisition_required"
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
    lower = prompt.lower()
    if "stamina" in lower and "sprint" in lower:
        plan = _stamina_sprint_plan(prompt, evidence)
    else:
        evidence["allow_model_behavior_synthesis"] = True
        plan = _generic_unreal_feature_plan(prompt, evidence)
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
            f"Target: `{plan.get('target_asset')}`",
            f"Live bridge evidence: `{plan.get('bridge_seconds', 0):.2f}s`",
            "Domains: " + ", ".join(f"`{item}`" for item in plan.get("detected_domains") or []),
            f"Skeletal mesh: `{evidence.get('skeletal_mesh') or 'not resolved'}`",
            f"Animation Blueprint: `{evidence.get('animation_blueprint') or 'not resolved'}`",
            "State owner: " + str(dict(detailed.get("proposed_architecture") or {}).get("state_owner") or "not resolved"),
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
        if behavior.get("unmatched_behavior_clauses"):
            lines.append(
                "- Unresolved clauses: "
                + "; ".join(str(item) for item in behavior["unmatched_behavior_clauses"])
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
