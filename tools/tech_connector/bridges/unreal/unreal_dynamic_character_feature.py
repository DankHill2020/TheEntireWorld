"""Spec-driven character Blueprint feature authoring for Unreal.

This module is intentionally importable inside Unreal's Python interpreter.  It
turns an approved feature plan into visual K2 EventGraph nodes, member
variables, execution wires, compile/save calls, and a validation report.
"""

from __future__ import annotations

from typing import Any

from tech_connector.services.unreal.animation_context_service import (
    animation_role_contracts,
    evaluate_animation_candidate,
)


DEFAULT_CHARACTER_PATH = "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix"
DEFAULT_ANIM_BLUEPRINT_PATH = "/Game/Variant_Combat/Anims/ABP_Manny_Combat"
REQUESTED_MANNY_SKELETON_PATH = "/Game/Characters/Mannequins/Meshes/SKM_Manny"
FALLBACK_MANNY_SKELETON_PATH = "/Game/Characters/Mannequins/Meshes/SK_Mannequin"
REFERENCE_ANIMATION_DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/fbx/Samba%20Dancing.fbx"
)


def build_master_traversal_combat_plan(prompt: str = "") -> dict[str, Any]:
    """Return a concrete plan for the Lester traversal/combat request."""

    return {
        "framework": "unreal_dynamic_character_feature_plan_v1",
        "status": "approval_ready",
        "feature": "dynamic_character_traversal_combat",
        "request": prompt,
        "target_asset": DEFAULT_CHARACTER_PATH,
        "anim_blueprint": DEFAULT_ANIM_BLUEPRINT_PATH,
        "requested_skeleton": REQUESTED_MANNY_SKELETON_PATH,
        "fallback_skeleton": FALLBACK_MANNY_SKELETON_PATH,
        "selected_target_skeleton": FALLBACK_MANNY_SKELETON_PATH,
        "reserved_keys": ["E", "F"],
        "cleanup_legacy_climbing_scaffold": True,
        "animation_slot_requirements": {
            "required_slots": ["DefaultSlot"],
            "role_slots": {
                "climb_loop": "DefaultSlot",
                "grapple_zip": "DefaultSlot",
                "vault_slide": "DefaultSlot",
                "dodge_roll": "DefaultSlot",
            },
            "validation": "Every required slot must exist as a Slot node in the AnimGraph pose chain and reach Output Pose.",
        },
        "motion_matching_requirements": {
            "enabled": "motion matching" in (prompt or "").lower() or "pose search" in (prompt or "").lower(),
            "required_assets": ["PoseSearchDatabase", "PoseSearchSchema"],
            "validation": "Prompt-built motion matching must verify PoseSearch plugin availability, database assets, compatible animation entries, and an AnimGraph Motion Matching node path to Output Pose.",
        },
        "features": [
            {
                "name": "Automatic Wall Climbing",
                "event": "Tick",
                "state_variable": "bIsClimbing",
                "graph_y": 0,
                "debug_text": "Auto Climb: wall contact drives climb/hang state variables for ABP",
                "actions": [
                    {
                        "type": "capsule_trace",
                        "channels": ["WorldStatic", "WorldDynamic", "PhysicsBody"],
                        "distance_cm": 95.0,
                        "radius": 34.0,
                        "half_height": 72.0,
                    },
                    {
                        "type": "branch_on_last_trace",
                        "true_do_once": True,
                        "false_set": [
                            {"variable": "bClimbWallDetected", "value": False},
                            {"variable": "bIsClimbing", "value": False},
                            {"variable": "bIsClimbHanging", "value": False},
                        ],
                        "false_float_set": [
                            {"variable": "ClimbVerticalInput", "value": 0.0},
                            {"variable": "ClimbSpeed", "value": 0.0},
                        ],
                    },
                    {"type": "set_bool", "variable": "bWantsToClimb", "value": True},
                    {"type": "set_bool", "variable": "bClimbWallDetected", "value": True},
                    {"type": "set_bool", "variable": "bIsClimbing", "value": True},
                    {"type": "set_bool", "variable": "bIsClimbHanging", "value": True},
                    {"type": "set_float", "variable": "ClimbVerticalInput", "value": 1.0},
                    {"type": "set_float", "variable": "ClimbSpeed", "value": 180.0},
                    {"type": "set_movement_mode", "mode": "MOVE_Flying"},
                    {"type": "play_montage", "role": "climb_loop", "play_rate": 1.0},
                    {"type": "print", "text": "Auto climb active: ABP climb/hang state"},
                ],
            },
            {
                "name": "Grappling Hook Zip",
                "key": "G",
                "state_variable": "bIsGrappling",
                "graph_y": 560,
                "debug_text": "G Grapple: 2500cm forward trace -> LaunchCharacter override",
                "actions": [
                    {"type": "set_bool", "variable": "bIsGrappling", "value": True},
                    {"type": "line_trace", "distance_cm": 2500.0},
                    {"type": "play_montage", "role": "grapple_zip", "play_rate": 1.0},
                    {
                        "type": "launch_character",
                        "velocity": {"x": 2500.0, "y": 0.0, "z": 450.0},
                        "xy_override": True,
                        "z_override": True,
                    },
                ],
            },
            {
                "name": "Parkour Vault & Slide",
                "key": "SpaceBar",
                "state_variable": "bIsVaulting",
                "graph_y": 1040,
                "debug_text": "Space Vault/Slide: waist-high obstacle vault or sprint slide impulse",
                "actions": [
                    {"type": "set_bool", "variable": "bIsClimbWallJumping", "value": True},
                    {"type": "set_bool", "variable": "bIsClimbing", "value": False},
                    {"type": "set_bool", "variable": "bIsClimbHanging", "value": False},
                    {"type": "set_bool", "variable": "bIsVaulting", "value": True},
                    {"type": "play_montage", "role": "vault_slide", "play_rate": 1.0},
                    {
                        "type": "launch_character",
                        "velocity": {"x": -850.0, "y": 0.0, "z": 720.0},
                        "xy_override": True,
                        "z_override": True,
                    },
                    {"type": "delay", "duration": 0.45},
                    {"type": "set_bool", "variable": "bIsClimbWallJumping", "value": False},
                ],
            },
            {
                "name": "Combat Dodge Roll",
                "key": "C",
                "state_variable": "bIsDodgeRolling",
                "graph_y": 1520,
                "debug_text": "C Dodge Roll: directional evade with invulnerability frames",
                "actions": [
                    {"type": "set_bool", "variable": "bTraversalInvulnerable", "value": True},
                    {"type": "set_bool", "variable": "bIsDodgeRolling", "value": True},
                    {"type": "play_montage", "role": "dodge_roll", "play_rate": 1.15},
                    {
                        "type": "launch_character",
                        "velocity": {"x": 1200.0, "y": 0.0, "z": 150.0},
                        "xy_override": True,
                        "z_override": False,
                    },
                    {"type": "delay", "duration": 0.35},
                    {"type": "set_bool", "variable": "bTraversalInvulnerable", "value": False},
                ],
            },
        ],
        "variables": [
            {"name": "bIsClimbing", "type": "bool", "default": "false"},
            {"name": "bWantsToClimb", "type": "bool", "default": "false"},
            {"name": "bClimbWallDetected", "type": "bool", "default": "false"},
            {"name": "bIsClimbHanging", "type": "bool", "default": "false"},
            {"name": "bIsClimbWallJumping", "type": "bool", "default": "false"},
            {"name": "bIsVaulting", "type": "bool", "default": "false"},
            {"name": "bIsGrappling", "type": "bool", "default": "false"},
            {"name": "bIsDodgeRolling", "type": "bool", "default": "false"},
            {"name": "bTraversalInvulnerable", "type": "bool", "default": "false"},
            {"name": "ClimbSpeed", "type": "real", "default": "0.0"},
            {"name": "ClimbVerticalInput", "type": "real", "default": "0.0"},
            {"name": "ClimbWallDistance", "type": "real", "default": "0.0"},
            {"name": "GrappleLaunchSpeed", "type": "real", "default": "2500.0"},
            {"name": "DodgeLaunchSpeed", "type": "real", "default": "1200.0"},
        ],
        "required_animation_roles": {
            "climb_loop": {
                "slot": "DefaultSlot",
                "semantic_contracts": animation_role_contracts("climb_loop"),
                "preferred_assets": [
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_WallJump",
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Jump",
                ],
                "generated_asset": "/Game/AIStudio/GeneratedAnims/Traversal/AI_ClimbLoop",
            },
            "grapple_zip": {
                "slot": "DefaultSlot",
                "semantic_contracts": animation_role_contracts("grapple_zip"),
                "preferred_assets": [
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Dash",
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Jump",
                ],
                "generated_asset": "/Game/AIStudio/GeneratedAnims/Traversal/AI_GrappleZip",
            },
            "vault_slide": {
                "slot": "DefaultSlot",
                "semantic_contracts": animation_role_contracts("vault_slide"),
                "preferred_assets": [
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_WallJump",
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Jump",
                ],
                "generated_asset": "/Game/AIStudio/GeneratedAnims/Traversal/AI_VaultSlide",
            },
            "dodge_roll": {
                "slot": "DefaultSlot",
                "semantic_contracts": animation_role_contracts("dodge_roll"),
                "preferred_assets": [
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Dash",
                    "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_Attack_01",
                ],
                "generated_asset": "/Game/AIStudio/GeneratedAnims/Combat/AI_DodgeRoll",
            },
        },
        "validation": [
            "Character Blueprint compiles and saves.",
            "AnimBlueprint compiles and saves after traversal state variables are added.",
            "N, G, SpaceBar, and C key nodes exist in the character EventGraph.",
            "G and C paths call LaunchCharacter with override pins wired/set.",
            "Required animation roles resolve to real AnimSequence assets or generated local duplicates.",
            "AnimGraph Output Pose has a connected upstream pose chain.",
            "E and F are preserved for Interact and editor viewport focus.",
        ],
        "affected_assets": [
            {"path": DEFAULT_CHARACTER_PATH, "change": "add variables and visual K2 EventGraph input/action wiring"},
            {"path": DEFAULT_ANIM_BLUEPRINT_PATH, "change": "add traversal/combat state variables and compile"},
        ],
    }


def build_character_ability_plan(
    prompt: str = "",
    *,
    ability_name: str = "PromptAbility",
    key: str = "Q",
    character_path: str = DEFAULT_CHARACTER_PATH,
    anim_blueprint_path: str = DEFAULT_ANIM_BLUEPRINT_PATH,
) -> dict[str, Any]:
    """Return a concrete character-Blueprint ability plan.

    This is a lightweight Blueprint ability path.  If a prompt explicitly needs
    GAS classes, the higher-level planner can still route to capability
    acquisition; this plan proves normal prompt-generated abilities without
    pretending a missing GAS stack exists.
    """

    clean_name = "".join(ch for ch in str(ability_name or "PromptAbility").title() if ch.isalnum())
    active_var = "bIs" + clean_name + "Active"
    cooldown_var = "bIs" + clean_name + "OnCooldown"
    resource_var = clean_name + "Resource"
    return {
        "framework": "unreal_dynamic_character_feature_plan_v1",
        "status": "approval_ready",
        "feature": "dynamic_character_ability",
        "ability_name": clean_name,
        "request": prompt,
        "target_asset": character_path,
        "anim_blueprint": anim_blueprint_path,
        "requested_skeleton": REQUESTED_MANNY_SKELETON_PATH,
        "fallback_skeleton": FALLBACK_MANNY_SKELETON_PATH,
        "selected_target_skeleton": FALLBACK_MANNY_SKELETON_PATH,
        "reserved_keys": ["E", "F"],
        "features": [
            {
                "name": clean_name + " Ability",
                "key": key,
                "state_variable": active_var,
                "graph_y": 2200,
                "debug_text": key + " " + clean_name + ": activate ability, spend resource, start cooldown",
                "actions": [
                    {"type": "set_bool", "variable": active_var, "value": True},
                    {"type": "set_bool", "variable": cooldown_var, "value": True},
                    {"type": "set_float", "variable": resource_var, "value": 75.0},
                    {"type": "print", "text": key + " " + clean_name + " ability activated"},
                    {
                        "type": "launch_character",
                        "velocity": {"x": 900.0, "y": 0.0, "z": 120.0},
                        "xy_override": True,
                        "z_override": False,
                    },
                    {"type": "delay", "duration": 1.0},
                    {"type": "set_bool", "variable": active_var, "value": False},
                    {"type": "set_bool", "variable": cooldown_var, "value": False},
                ],
            }
        ],
        "variables": [
            {"name": active_var, "type": "bool", "default": "false"},
            {"name": cooldown_var, "type": "bool", "default": "false"},
            {"name": resource_var, "type": "real", "default": "100.0"},
        ],
        "required_animation_roles": {
            clean_name.lower() + "_activation": {
                "preferred_assets": [
                    "/Game/Characters/Mannequins/Anims/Unarmed/Attack/MM_Attack_01",
                    "/Game/Characters/Mannequins/Anims/Unarmed/Jump/MM_Dash",
                ],
                "generated_asset": "/Game/AIStudio/GeneratedAnims/Abilities/AI_" + clean_name + "_Activation",
            }
        },
        "validation": [
            "Character Blueprint compiles and saves.",
            "Ability input key node exists and is not reserved.",
            "Ability active/cooldown/resource variables exist.",
            "Activation graph has executable state, debug, launch/effect, cooldown delay, and reset nodes.",
            "Required animation role resolves to a real AnimSequence asset or generated local duplicate.",
        ],
        "affected_assets": [
            {"path": character_path, "change": "add ability variables and visual K2 EventGraph activation wiring"},
            {"path": anim_blueprint_path, "change": "add ability state variables and compile"},
        ],
    }


def _pin(unreal, node: Any, *names: str) -> Any:
    wanted = {str(name).lower().replace(" ", "").replace("_", "") for name in names}
    for item in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        try:
            name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(item))
        except Exception:
            name = str(item.get_name()) if hasattr(item, "get_name") else ""
        if name.lower().replace(" ", "").replace("_", "") in wanted:
            return item
    return None


def _node_title(unreal, node: Any) -> str:
    try:
        return str(unreal.BlueprintEditorLibrary.get_node_title(node))
    except Exception:
        return str(node.get_name()) if node else ""


def _set_pos(unreal, node: Any, x: float, y: float) -> None:
    try:
        unreal.BlueprintEditorLibrary.set_node_pos(node, unreal.IntPoint(int(x), int(y)))
    except Exception:
        pass


def _pin_names(unreal, node: Any) -> list[str]:
    names = []
    for item in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        try:
            names.append(str(unreal.BlueprintGraphPinLibrary.get_pin_name(item)))
        except Exception:
            pass
    return names


def _pin_direction(unreal, pin: Any) -> str:
    for name in ("get_pin_direction", "get_direction"):
        try:
            value = getattr(unreal.BlueprintGraphPinLibrary, name)(pin)
            return str(value)
        except Exception:
            pass
    return ""


def _pin_category(unreal, pin: Any) -> str:
    for name in ("get_pin_category", "get_category"):
        try:
            value = getattr(unreal.BlueprintGraphPinLibrary, name)(pin)
            return str(value)
        except Exception:
            pass
    try:
        value = unreal.BlueprintGraphPinLibrary.get_pin_type(pin)
        return str(value)
    except Exception:
        return ""


def _is_output_pin(unreal, pin: Any) -> bool:
    direction = _pin_direction(unreal, pin).lower()
    return "output" in direction or direction.endswith("egpd_output")


def _is_exec_pin(unreal, pin: Any) -> bool:
    category = _pin_category(unreal, pin).lower()
    if "exec" in category:
        return True
    try:
        if bool(unreal.BlueprintGraphPinLibrary.is_execution_pin(pin)):
            return True
    except Exception:
        pass
    return str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin)).lower().replace(" ", "") in {
        "execute",
        "then",
        "completed",
        "pressed",
        "released",
        "true",
        "false",
        "reset",
    }


def _linked_pins(unreal, pin: Any) -> list[Any]:
    try:
        return list(unreal.BlueprintGraphPinLibrary.list_connected_pins(pin) or [])
    except Exception:
        return []


def _owning_node(unreal, pin: Any) -> Any:
    try:
        return unreal.BlueprintGraphPinLibrary.get_owning_node(pin)
    except Exception:
        return None


def _compile_blueprint_asset(unreal, asset: Any) -> dict[str, Any]:
    report = {"compiled": False, "error": ""}
    if asset is None:
        report["error"] = "Asset is None"
        return report
    try:
        result = unreal.BlueprintEditorLibrary.compile_blueprint(asset)
        report["compiled"] = result is not False
    except Exception as exc:
        report["compiled"] = False
        report["error"] = str(exc)
    return report


def _connect(unreal, src: Any, dst: Any, label: str, report: dict[str, Any]) -> bool:
    if src is None or dst is None:
        report.setdefault("warnings", []).append("Missing pin for link: " + label)
        return False
    ok = False
    try:
        ok = bool(unreal.BlueprintGraphPinLibrary.try_create_connection(src, dst))
        if not ok:
            src.make_link_to(dst)
            ok = True
    except Exception as exc:
        report.setdefault("warnings", []).append("Link failed " + label + ": " + str(exc))
    report.setdefault("links_created", []).append({"label": label, "ok": ok})
    return ok


def _set_pin_value(unreal, item: Any, value: Any, label: str, report: dict[str, Any]) -> bool:
    if item is None:
        report.setdefault("warnings", []).append("Missing pin for value: " + label)
        return False
    try:
        ok = bool(unreal.BlueprintGraphPinLibrary.set_pin_value(item, str(value)))
    except Exception as exc:
        ok = False
        report.setdefault("warnings", []).append("Set pin failed " + label + ": " + str(exc))
    report.setdefault("pins_set", []).append({"pin": label, "value": str(value), "ok": ok})
    return ok


def _create_node(unreal, editor: Any, palette: str, x: float, y: float, report: dict[str, Any], context_pin: Any = None) -> Any:
    node = None
    try:
        node = editor.create_node_from_name(
            palette,
            unreal.Vector2D(float(x), float(y)),
            [context_pin] if context_pin is not None else [],
            None,
        )
    except Exception as exc:
        report.setdefault("warnings", []).append("Create node failed " + palette + ": " + str(exc))
        return None
    if node is None:
        report.setdefault("warnings", []).append("Create node returned None: " + palette)
        return None
    _set_pos(unreal, node, x, y)
    report.setdefault("nodes_created", []).append(
        {
            "palette": palette,
            "name": str(node.get_name()),
            "title": _node_title(unreal, node),
            "pins": _pin_names(unreal, node),
        }
    )
    return node


def _add_variable(unreal, graph: Any, blueprint: Any, spec: dict[str, Any], report: dict[str, Any]) -> None:
    name = str(spec.get("name") or "")
    if not name:
        return
    existing = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint) or []}
    if name in existing:
        report.setdefault("variables_reused", []).append(name)
        return
    try:
        pin_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name(str(spec.get("type") or "bool"))
        ok = bool(graph.add_member_variable(name, pin_type, str(spec.get("default") or "")))
        if ok:
            report.setdefault("variables_added", []).append(name)
        else:
            report.setdefault("warnings", []).append("add_member_variable returned false: " + name)
    except Exception as exc:
        report.setdefault("warnings", []).append("Variable add failed " + name + ": " + str(exc))


def _download_https_file(url: str, destination_file: str) -> dict[str, Any]:
    import hashlib
    import os
    import urllib.request

    result = {
        "ok": False,
        "url": url,
        "file": destination_file,
        "bytes": 0,
        "sha256": "",
        "errors": [],
    }
    if not str(url or "").lower().startswith("https://"):
        result["errors"].append("Animation downloads require HTTPS.")
        return result
    os.makedirs(os.path.dirname(destination_file), exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AIStudio-Unreal-AnimationDownloader/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()
        with open(destination_file, "wb") as handle:
            handle.write(payload)
        result["bytes"] = len(payload)
        result["sha256"] = hashlib.sha256(payload).hexdigest()
        header = payload[:256]
        if not destination_file.lower().endswith(".fbx"):
            result["errors"].append("Downloaded animation is not an .fbx file.")
        if b"Kaydara FBX" not in header and b"FBX" not in header:
            result["errors"].append("Downloaded file does not look like an FBX asset.")
        result["ok"] = not result["errors"]
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


def _import_downloaded_fbx_animation(unreal, source_file: str, destination_path: str, save: bool = True) -> dict[str, Any]:
    result = {"ok": False, "source_file": source_file, "destination_path": destination_path, "assets": [], "errors": []}
    try:
        unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
        task = unreal.AssetImportTask()
        task.filename = source_file
        task.destination_path = destination_path
        task.automated = True
        task.replace_existing = True
        task.save = bool(save)
        try:
            options = unreal.FbxImportUI()
            options.original_import_type = unreal.FBXImportType.FBXIT_SKELETAL_MESH
            options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
            options.import_animations = True
            options.import_as_skeletal = True
            options.import_mesh = True
            options.create_physics_asset = False
            task.options = options
        except Exception as exc:
            result["errors"].append("FBX import options warning: " + str(exc))
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        for asset in list(task.get_objects() or []):
            try:
                path = asset.get_path_name().split(".")[0]
                cls = asset.get_class().get_name()
            except Exception:
                path = str(asset)
                cls = ""
            result["assets"].append({"path": path, "class": cls})
            if save:
                try:
                    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
                except Exception:
                    pass
        result["ok"] = bool(result["assets"])
        if not result["ok"] and not result["errors"]:
            result["errors"].append("Unreal imported zero assets from downloaded FBX.")
    except Exception as exc:
        result["errors"].append(str(exc))
    return result


def _asset_skeleton_path(unreal, asset_path: str) -> str:
    try:
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        skeleton = None
        for prop in ("skeleton", "target_skeleton"):
            try:
                skeleton = asset.get_editor_property(prop)
            except Exception:
                skeleton = getattr(asset, prop, None)
            if skeleton:
                break
        if skeleton:
            return str(skeleton.get_path_name()).split(".")[0]
    except Exception:
        pass
    return ""


def _is_target_skeleton(unreal, asset_path: str, target_skeletons: list[str]) -> bool:
    skeleton_path = _asset_skeleton_path(unreal, asset_path)
    return bool(skeleton_path and skeleton_path in {str(path) for path in target_skeletons if path})


def _asset_data_for_path(unreal, asset_path: str) -> Any:
    try:
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not asset:
            return None
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        object_path = asset.get_path_name()
        try:
            return registry.get_asset_by_object_path(object_path)
        except Exception:
            try:
                return registry.get_asset_by_object_path(unreal.SoftObjectPath(object_path))
            except Exception:
                return None
    except Exception:
        return None


def _discover_ik_retargeters(unreal) -> list[str]:
    paths: list[str] = []
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        class_path = unreal.TopLevelAssetPath("/Script/IKRig", "IKRetargeter")
        for row in registry.get_assets_by_class(class_path, True) or []:
            path = str(row.package_name)
            if path not in paths:
                paths.append(path)
    except Exception:
        pass
    return paths


def _discover_skeletal_meshes_for_skeleton(unreal, skeleton_path: str) -> list[str]:
    matches: list[str] = []
    if not skeleton_path:
        return matches
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        class_path = unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")
        for row in registry.get_assets_by_class(class_path, True) or []:
            path = str(row.package_name)
            try:
                mesh = unreal.EditorAssetLibrary.load_asset(path)
                mesh_skeleton = mesh.get_editor_property("skeleton") if mesh else None
                mesh_skeleton_path = str(mesh_skeleton.get_path_name()).split(".")[0] if mesh_skeleton else ""
                if mesh_skeleton_path == skeleton_path and path not in matches:
                    matches.append(path)
            except Exception:
                continue
    except Exception:
        pass
    return matches


def discover_retarget_target_options(
    preferred_skeleton: str = "",
    preferred_mesh: str = "",
) -> dict[str, Any]:
    """Return skeleton/mesh choices that a user can select for prompt retargeting."""

    import unreal

    skeleton_paths: list[str] = []
    mesh_preference = str(preferred_mesh or "")
    skeleton_preference = str(preferred_skeleton or "")
    out = {"ok": True, "default_target_skeleton": "", "options": [], "errors": []}
    try:
        if mesh_preference and unreal.EditorAssetLibrary.does_asset_exist(mesh_preference):
            mesh = unreal.EditorAssetLibrary.load_asset(mesh_preference)
            skeleton = mesh.get_editor_property("skeleton") if mesh else None
            if skeleton:
                skeleton_preference = str(skeleton.get_path_name()).split(".")[0]
        if skeleton_preference:
            skeleton_paths.append(skeleton_preference)
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        class_path = unreal.TopLevelAssetPath("/Script/Engine", "Skeleton")
        for row in registry.get_assets_by_class(class_path, True) or []:
            path = str(row.package_name)
            if path and path not in skeleton_paths:
                skeleton_paths.append(path)
        for skeleton_path in skeleton_paths:
            asset = unreal.EditorAssetLibrary.load_asset(skeleton_path) if unreal.EditorAssetLibrary.does_asset_exist(skeleton_path) else None
            meshes = _discover_skeletal_meshes_for_skeleton(unreal, skeleton_path)
            if mesh_preference in meshes:
                meshes.remove(mesh_preference)
                meshes.insert(0, mesh_preference)
            out["options"].append(
                {
                    "skeleton": skeleton_path,
                    "exists": bool(asset),
                    "class": asset.get_class().get_name() if asset else "",
                    "skeletal_meshes": meshes,
                }
            )
        available = [row for row in out["options"] if row.get("exists")]
        if available:
            out["default_target_skeleton"] = str(available[0].get("skeleton") or "")
    except Exception as exc:
        out["ok"] = False
        out["errors"].append(str(exc))
    return out


def _direct_duplicate_and_retarget_to_selected_mesh(
    unreal,
    asset_data: Any,
    source_mesh_path: str,
    target_meshes: list[str],
    retargeters: list[str],
    target_skeletons: list[str],
    target_path: str,
    save: bool = True,
) -> dict[str, Any]:
    report = {"ok": False, "attempts": [], "selected_asset": "", "selected_skeleton": "", "errors": []}
    source_mesh = unreal.EditorAssetLibrary.load_asset(source_mesh_path) if source_mesh_path else None
    if not source_mesh:
        report["errors"].append("No source SkeletalMesh was available from the downloaded FBX import.")
        return report
    for retargeter_path in retargeters:
        retargeter = unreal.EditorAssetLibrary.load_asset(retargeter_path) if retargeter_path else None
        if not retargeter:
            report["errors"].append("Retargeter could not be loaded for direct retarget: " + retargeter_path)
            continue
        for target_mesh_path in target_meshes:
            target_mesh = unreal.EditorAssetLibrary.load_asset(target_mesh_path) if target_mesh_path else None
            attempt = {"retargeter": retargeter_path, "source_mesh": source_mesh_path, "target_mesh": target_mesh_path, "created": [], "errors": []}
            if not target_mesh:
                attempt["errors"].append("Target SkeletalMesh could not be loaded.")
                report["attempts"].append(attempt)
                continue
            try:
                created_data = list(
                    unreal.IKRetargetBatchOperation.duplicate_and_retarget(
                        [asset_data],
                        source_mesh,
                        target_mesh,
                        retargeter,
                        "",
                        "",
                        "",
                        "_Target",
                        target_path,
                        False,
                        True,
                        True,
                    )
                    or []
                )
                for row in created_data:
                    try:
                        asset = row.get_asset()
                        path = asset.get_path_name().split(".")[0] if asset else str(row.package_name)
                        cls = asset.get_class().get_name() if asset else ""
                    except Exception:
                        path = str(getattr(row, "package_name", row))
                        cls = ""
                        asset = None
                    skeleton = _asset_skeleton_path(unreal, path)
                    attempt["created"].append({"path": path, "class": cls, "skeleton": skeleton})
                    if asset and save:
                        try:
                            unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
                        except Exception:
                            pass
                    if cls == "AnimSequence" and skeleton in set(target_skeletons):
                        report["ok"] = True
                        report["selected_asset"] = path
                        report["selected_skeleton"] = skeleton
                if not created_data:
                    attempt["errors"].append("Direct duplicate_and_retarget produced zero assets.")
            except Exception as exc:
                attempt["errors"].append(str(exc))
            report["attempts"].append(attempt)
            if report["ok"]:
                return report
    return report


def _retarget_animation_to_skeleton(
    unreal,
    asset_path: str,
    role: str,
    role_spec: dict[str, Any],
    plan: dict[str, Any],
    save: bool = True,
) -> dict[str, Any]:
    target_skeletons = [
        str(role_spec.get("target_skeleton") or ""),
        str(plan.get("selected_target_skeleton") or ""),
        str(plan.get("requested_skeleton") or ""),
        str(plan.get("fallback_skeleton") or ""),
    ]
    target_skeletons = [path for index, path in enumerate(target_skeletons) if path and path not in target_skeletons[:index]]
    target_meshes = [
        str(item)
        for item in (
            role_spec.get("target_skeletal_meshes")
            or role_spec.get("target_meshes")
            or plan.get("target_skeletal_meshes")
            or []
        )
        if item
    ]
    if not target_meshes:
        for skeleton_path in target_skeletons:
            target_meshes.extend(_discover_skeletal_meshes_for_skeleton(unreal, skeleton_path))
    target_meshes = [path for index, path in enumerate(target_meshes) if path and path not in target_meshes[:index]]
    retargeters = [
        str(role_spec.get("retargeter_path") or ""),
        str(plan.get("retargeter_path") or ""),
        *_discover_ik_retargeters(unreal),
    ]
    retargeters = [path for index, path in enumerate(retargeters) if path and path not in retargeters[:index]]
    target_path = str(role_spec.get("retarget_destination_path") or ("/Game/AIStudio/RetargetedAnimations/" + str(role)))
    report = {
        "ok": False,
        "fallback_required": False,
        "fallback_route": "",
        "source_asset": asset_path,
        "source_skeleton": _asset_skeleton_path(unreal, asset_path),
        "target_skeletons": target_skeletons,
        "target_skeletal_meshes": target_meshes,
        "target_path": target_path,
        "retargeters_considered": retargeters,
        "created_assets": [],
        "selected_asset": "",
        "selected_skeleton": "",
        "errors": [],
    }
    if not asset_path:
        report["errors"].append("No imported animation asset was available to retarget.")
        report["fallback_required"] = True
        report["fallback_route"] = "external_dcc_retarget"
        return report
    asset_data = _asset_data_for_path(unreal, asset_path)
    if not asset_data:
        report["errors"].append("Could not resolve AssetData for imported animation: " + asset_path)
        report["fallback_required"] = True
        report["fallback_route"] = "external_dcc_retarget"
        return report
    for retargeter_path in retargeters:
        try:
            retargeter = unreal.EditorAssetLibrary.load_asset(retargeter_path)
            if not retargeter:
                report["errors"].append("Retargeter could not be loaded: " + retargeter_path)
                continue
            inputs = unreal.IKRetargetBatchOperationInputs()
            inputs.assets_to_retarget = [asset_data]
            inputs.ik_retarget_asset = retargeter
            inputs.target_path = target_path
            inputs.use_source_path = False
            inputs.include_referenced_assets = True
            created_data = list(unreal.IKRetargetBatchOperation.run_batch_retarget(inputs) or [])
            for row in created_data:
                try:
                    asset = row.get_asset()
                    path = asset.get_path_name().split(".")[0] if asset else str(row.package_name)
                    cls = asset.get_class().get_name() if asset else ""
                except Exception:
                    path = str(getattr(row, "package_name", row))
                    cls = ""
                    asset = None
                skeleton = _asset_skeleton_path(unreal, path)
                report["created_assets"].append(
                    {"path": path, "class": cls, "skeleton": skeleton, "retargeter": retargeter_path}
                )
                if asset and save:
                    try:
                        unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
                    except Exception:
                        pass
                if cls == "AnimSequence" and skeleton in set(report["target_skeletons"]):
                    report["ok"] = True
                    report["selected_asset"] = path
                    report["selected_skeleton"] = skeleton
                    return report
            if not created_data:
                report["errors"].append("Retargeter produced zero assets: " + retargeter_path)
        except Exception as exc:
            report["errors"].append("Retarget failed with " + retargeter_path + ": " + str(exc))
    if not report["ok"]:
        source_mesh_path = str(role_spec.get("_source_skeletal_mesh") or role_spec.get("source_skeletal_mesh") or "")
        direct = _direct_duplicate_and_retarget_to_selected_mesh(
            unreal,
            asset_data,
            source_mesh_path,
            target_meshes,
            retargeters,
            target_skeletons,
            target_path,
            save=save,
        )
        report["direct_retarget"] = direct
        report["created_assets"].extend(
            [
                {
                    "path": created.get("path"),
                    "class": created.get("class"),
                    "skeleton": created.get("skeleton"),
                    "retargeter": attempt.get("retargeter"),
                    "target_mesh": attempt.get("target_mesh"),
                }
                for attempt in direct.get("attempts") or []
                for created in attempt.get("created") or []
            ]
        )
        if direct.get("ok"):
            report["ok"] = True
            report["selected_asset"] = str(direct.get("selected_asset") or "")
            report["selected_skeleton"] = str(direct.get("selected_skeleton") or "")
            return report
        report["errors"].extend(direct.get("errors") or [])
    if not retargeters:
        report["errors"].append("No IK Retargeter asset was specified or discovered.")
    if report["created_assets"] and not report["ok"]:
        report["errors"].append("Retarget produced assets, but none were AnimSequences on the target skeleton.")
    if not report["ok"]:
        report["fallback_required"] = True
        report["fallback_route"] = "external_dcc_retarget"
        report["fallback_manifest"] = {
            "source_anim_sequence": asset_path,
            "source_skeleton": report["source_skeleton"],
            "target_skeletons": report["target_skeletons"],
            "target_unreal_path": target_path,
            "preferred_output_class": "AnimSequence",
            "reason": "Unreal IK retarget did not create an AnimSequence on the required target skeleton.",
        }
    return report


def _download_and_import_animation_role(unreal, role: str, role_spec: dict[str, Any], save: bool = True) -> dict[str, Any]:
    import os
    import urllib.parse

    url = str(role_spec.get("download_url") or "")
    report = {
        "download": {"ok": False, "errors": []},
        "import": {"ok": False, "assets": [], "errors": []},
        "asset_path": "",
        "asset_class": "",
        "asset_skeleton": "",
        "source_skeletal_mesh": "",
        "resolved": False,
        "semantic_evaluation": {},
        "errors": [],
    }
    semantic_candidate = {
        "name": role_spec.get("download_name") or role_spec.get("source_name") or "",
        "description": role_spec.get("source_description") or "",
        "tags": role_spec.get("source_tags") or [],
        "download_url": url,
    }
    semantic = evaluate_animation_candidate(
        role,
        semantic_candidate,
        probe_only=bool(role_spec.get("probe_only", False)),
    )
    report["semantic_evaluation"] = semantic
    if not semantic.get("accepted"):
        report["errors"].append(
            "Online animation rejected before download: " + str(semantic.get("reason") or "semantic role mismatch")
        )
        return report
    destination_path = str(
        role_spec.get("download_destination_path")
        or role_spec.get("generated_asset")
        or ("/Game/AIStudio/DownloadedAnimations/" + str(role))
    )
    saved_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())
    download_dir = os.path.join(saved_dir, "AIStudio", "DownloadedAnimations")
    file_name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or (str(role) + ".fbx")
    if not file_name.lower().endswith(".fbx"):
        file_name += ".fbx"
    local_file = os.path.join(download_dir, file_name)
    download = _download_https_file(url, local_file)
    imported = {"ok": False, "assets": [], "errors": []}
    selected_asset = ""
    selected_class = ""
    source_mesh_asset = ""
    if download.get("ok"):
        imported = _import_downloaded_fbx_animation(unreal, local_file, destination_path, save=save)
        anim_asset = next((row for row in imported.get("assets") or [] if row.get("class") == "AnimSequence"), None)
        mesh_asset = next((row for row in imported.get("assets") or [] if row.get("class") == "SkeletalMesh"), None)
        selected = anim_asset or next(iter(imported.get("assets") or []), None)
        if selected:
            selected_asset = str(selected.get("path") or "")
            selected_class = str(selected.get("class") or "")
        if mesh_asset:
            source_mesh_asset = str(mesh_asset.get("path") or "")
    report.update({
        "download": download,
        "import": imported,
        "asset_path": selected_asset,
        "asset_class": selected_class,
        "asset_skeleton": _asset_skeleton_path(unreal, selected_asset) if selected_asset else "",
        "source_skeletal_mesh": source_mesh_asset,
        "resolved": bool(selected_asset),
    })
    return report


def _evaluate_role_asset_candidate(role: str, asset_path: str, role_spec: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(role_spec.get("semantic_provenance") or {})
    candidate = {
        "name": provenance.get("name") or asset_path.rsplit("/", 1)[-1],
        "description": provenance.get("description") or "",
        "tags": provenance.get("tags") or [],
        "url": provenance.get("source_url") or "",
    }
    result = evaluate_animation_candidate(
        role,
        candidate,
        probe_only=bool(role_spec.get("probe_only", False)),
    )
    result["asset_path"] = asset_path
    result["has_explicit_provenance"] = bool(provenance)
    return result


def _read_animation_asset_provenance(unreal, asset: Any) -> dict[str, Any]:
    """Read durable semantic evidence stored on an imported/generated asset."""

    if asset is None:
        return {}
    fields = {
        "role": "AIStudio.AnimationRole",
        "name": "AIStudio.SourceName",
        "description": "AIStudio.SourceDescription",
        "tags": "AIStudio.SourceTags",
        "source_url": "AIStudio.SourceUrl",
        "license": "AIStudio.SourceLicense",
        "semantic_score": "AIStudio.SemanticScore",
    }
    result: dict[str, Any] = {}
    for key, tag in fields.items():
        try:
            value = str(unreal.EditorAssetLibrary.get_metadata_tag(asset, tag) or "").strip()
        except Exception:
            value = ""
        if value:
            result[key] = value
    return result


def _write_animation_asset_provenance(
    unreal,
    asset: Any,
    role: str,
    role_spec: dict[str, Any],
    semantic: dict[str, Any],
) -> None:
    """Persist evidence so later audits do not trust an asset path or filename."""

    if asset is None:
        return
    best = dict(semantic.get("best_match") or {})
    values = {
        "AIStudio.AnimationRole": role,
        "AIStudio.SourceName": role_spec.get("download_name") or role_spec.get("source_name") or asset.get_name(),
        "AIStudio.SourceDescription": role_spec.get("source_description") or "",
        "AIStudio.SourceTags": ",".join(str(value) for value in role_spec.get("source_tags") or []),
        "AIStudio.SourceUrl": role_spec.get("download_url") or role_spec.get("source_url") or "",
        "AIStudio.SourceLicense": role_spec.get("source_license") or "",
        "AIStudio.SemanticScore": semantic.get("score", best.get("score", 0)),
    }
    for tag, value in values.items():
        unreal.EditorAssetLibrary.set_metadata_tag(asset, tag, str(value))


def _evaluate_persisted_role_asset(unreal, role: str, asset: Any, role_spec: dict[str, Any]) -> dict[str, Any]:
    provenance = _read_animation_asset_provenance(unreal, asset)
    declared_role = str(provenance.get("role") or "")
    candidate = {
        "name": provenance.get("name") or "",
        "description": provenance.get("description") or "",
        "tags": provenance.get("tags") or "",
        "url": provenance.get("source_url") or "",
    }
    semantic = evaluate_animation_candidate(
        role,
        candidate,
        probe_only=bool(role_spec.get("probe_only", False)),
    )
    semantic["provenance"] = provenance
    semantic["has_explicit_provenance"] = bool(provenance)
    semantic["declared_role_matches"] = declared_role == role
    semantic["license_declared"] = bool(provenance.get("license"))
    semantic["accepted"] = bool(
        semantic.get("accepted")
        and semantic["has_explicit_provenance"]
        and semantic["declared_role_matches"]
        and semantic["license_declared"]
    )
    return semantic


def _resolve_animation_roles(unreal, plan: dict[str, Any], report: dict[str, Any], save: bool = True) -> dict[str, Any]:
    """Resolve required animation roles to real project assets.

    If a generated target is absent but a preferred compatible source clip is
    present, duplicate the source into the generated location.  Missing roles
    remain explicit failures; no role is silently treated as done.
    """

    resolved: dict[str, Any] = {}
    for role, spec in dict(plan.get("required_animation_roles") or {}).items():
        role_spec = dict(spec or {})
        generated = str(role_spec.get("generated_asset") or "")
        preferred = [str(item) for item in role_spec.get("preferred_assets") or [] if item]
        row = {
            "role": str(role),
            "resolved": False,
            "asset_path": "",
            "asset_class": "",
            "asset_skeleton": "",
            "retarget_required": False,
            "retarget": {},
            "source_asset": "",
            "created": False,
            "downloaded": False,
            "imported_assets": [],
            "errors": [],
            "semantic_evaluation": {},
        }
        if generated and unreal.EditorAssetLibrary.does_asset_exist(generated):
            semantic = _evaluate_role_asset_candidate(str(role), generated, role_spec)
            row["semantic_evaluation"] = semantic
            if semantic.get("accepted") and semantic.get("has_explicit_provenance"):
                asset = unreal.EditorAssetLibrary.load_asset(generated)
                row["resolved"] = True
                row["asset_path"] = generated
                row["asset_class"] = asset.get_class().get_name() if asset else ""
                row["asset_skeleton"] = _asset_skeleton_path(unreal, generated)
                resolved[str(role)] = row
                continue
            row["errors"].append("Existing generated animation lacks accepted semantic provenance for role: " + str(role))
        source = ""
        rejected_sources = []
        for candidate_path in preferred:
            if not unreal.EditorAssetLibrary.does_asset_exist(candidate_path):
                continue
            semantic = _evaluate_role_asset_candidate(str(role), candidate_path, role_spec)
            if semantic.get("accepted"):
                source = candidate_path
                row["semantic_evaluation"] = semantic
                break
            rejected_sources.append({"asset_path": candidate_path, "semantic_evaluation": semantic})
        if rejected_sources:
            row["rejected_sources"] = rejected_sources
        if not source:
            if role_spec.get("download_url"):
                downloaded = _download_and_import_animation_role(unreal, str(role), role_spec, save=save)
                row["download"] = downloaded.get("download")
                row["import"] = downloaded.get("import")
                row["semantic_evaluation"] = downloaded.get("semantic_evaluation") or {}
                row["downloaded"] = bool(row.get("download", {}).get("ok"))
                row["imported_assets"] = list(row.get("import", {}).get("assets") or [])
                row["resolved"] = bool(downloaded.get("resolved"))
                row["asset_path"] = str(downloaded.get("asset_path") or "")
                row["asset_class"] = str(downloaded.get("asset_class") or "")
                row["asset_skeleton"] = str(downloaded.get("asset_skeleton") or "")
                if downloaded.get("source_skeletal_mesh"):
                    role_spec["_source_skeletal_mesh"] = str(downloaded.get("source_skeletal_mesh") or "")
                target_skeletons = [
                    str(role_spec.get("target_skeleton") or ""),
                    str(plan.get("selected_target_skeleton") or ""),
                    str(plan.get("requested_skeleton") or ""),
                    str(plan.get("fallback_skeleton") or ""),
                ]
                if row["asset_path"] and not _is_target_skeleton(unreal, row["asset_path"], target_skeletons):
                    row["retarget_required"] = True
                    retarget = _retarget_animation_to_skeleton(unreal, row["asset_path"], str(role), role_spec, plan, save=save)
                    row["retarget"] = retarget
                    if retarget.get("ok"):
                        row["resolved"] = True
                        row["asset_path"] = str(retarget.get("selected_asset") or "")
                        row["asset_class"] = "AnimSequence"
                        row["asset_skeleton"] = str(retarget.get("selected_skeleton") or "")
                    elif not bool(role_spec.get("allow_foreign_skeleton", False)):
                        row["resolved"] = False
                        row["errors"].extend(retarget.get("errors") or [])
                        row["errors"].append(
                            "Downloaded animation skeleton is not target compatible and retargeting did not create a valid target-skeleton AnimSequence."
                        )
                if row["asset_path"] and row["resolved"]:
                    resolved_asset = unreal.EditorAssetLibrary.load_asset(row["asset_path"])
                    _write_animation_asset_provenance(
                        unreal,
                        resolved_asset,
                        str(role),
                        role_spec,
                        row.get("semantic_evaluation") or {},
                    )
                    if resolved_asset and save:
                        unreal.EditorAssetLibrary.save_loaded_asset(resolved_asset, False)
                    try:
                        plan["required_animation_roles"][role]["resolved_asset"] = row["asset_path"]
                    except Exception:
                        pass
                row["errors"].extend(row.get("download", {}).get("errors") or [])
                row["errors"].extend(row.get("import", {}).get("errors") or [])
            else:
                row["errors"].append("No contextually valid AnimSequence asset exists for role: " + str(role))
            resolved[str(role)] = row
            continue
        if generated:
            try:
                asset = unreal.EditorAssetLibrary.duplicate_asset(source, generated)
                row["created"] = bool(asset)
                row["resolved"] = bool(asset)
                row["asset_path"] = generated if asset else ""
                row["asset_class"] = asset.get_class().get_name() if asset else ""
                row["asset_skeleton"] = _asset_skeleton_path(unreal, generated) if asset else ""
                row["source_asset"] = source
                try:
                    plan["required_animation_roles"][role]["semantic_provenance"] = {
                        "name": source.rsplit("/", 1)[-1],
                        "tags": row.get("semantic_evaluation", {}).get("best_match", {}).get("required_hits", []),
                        "source_asset": source,
                        "license": "project_internal",
                    }
                except Exception:
                    pass
                local_role_spec = dict(role_spec)
                local_role_spec.update(
                    {
                        "source_name": source.rsplit("/", 1)[-1],
                        "source_tags": row.get("semantic_evaluation", {}).get("best_match", {}).get("required_hits", []),
                        "source_url": source,
                        "source_license": "project_internal",
                    }
                )
                _write_animation_asset_provenance(
                    unreal,
                    asset,
                    str(role),
                    local_role_spec,
                    row.get("semantic_evaluation") or {},
                )
                if asset and save:
                    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
            except Exception as exc:
                row["errors"].append("Duplicate animation failed: " + str(exc))
        else:
            asset = unreal.EditorAssetLibrary.load_asset(source)
            row["resolved"] = True
            row["asset_path"] = source
            row["asset_class"] = asset.get_class().get_name() if asset else ""
            row["asset_skeleton"] = _asset_skeleton_path(unreal, source)
            row["source_asset"] = source
        resolved[str(role)] = row
    report["animation_roles"] = resolved
    return resolved


def _ensure_role_montages(unreal, plan: dict[str, Any], report: dict[str, Any], save: bool = True) -> dict[str, Any]:
    montages: dict[str, Any] = {}
    for role, row in dict(report.get("animation_roles") or {}).items():
        asset_path = str(dict(row).get("asset_path") or "")
        if not asset_path:
            continue
        montage_path = str(
            dict(plan.get("required_animation_roles") or {}).get(role, {}).get("montage_asset")
            or ("/Game/AIStudio/GeneratedAnims/Montages/AM_" + str(role).title().replace("_", ""))
        )
        montage_asset = unreal.EditorAssetLibrary.load_asset(montage_path) if unreal.EditorAssetLibrary.does_asset_exist(montage_path) else None
        created = False
        if not montage_asset:
            try:
                sequence = unreal.EditorAssetLibrary.load_asset(asset_path)
                factory = unreal.AnimMontageFactory()
                factory.source_animation = sequence
                package_path = montage_path.rsplit("/", 1)[0]
                asset_name = montage_path.rsplit("/", 1)[-1]
                montage_asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    asset_name,
                    package_path,
                    unreal.AnimMontage,
                    factory,
                )
                created = bool(montage_asset)
            except Exception as exc:
                montages[str(role)] = {"resolved": False, "asset_path": "", "source_animation": asset_path, "errors": [str(exc)]}
                continue
        if montage_asset and save:
            try:
                unreal.EditorAssetLibrary.save_loaded_asset(montage_asset, False)
            except Exception:
                pass
        montage_path_final = montage_asset.get_path_name().split(".")[0] if montage_asset else ""
        try:
            plan["required_animation_roles"][role]["montage_asset"] = montage_path_final
        except Exception:
            pass
        montages[str(role)] = {
            "resolved": bool(montage_asset),
            "asset_path": montage_path_final,
            "source_animation": asset_path,
            "slot": str(dict(plan.get("required_animation_roles") or {}).get(role, {}).get("slot") or "DefaultSlot"),
            "created": created,
            "class": montage_asset.get_class().get_name() if montage_asset else None,
            "errors": [],
        }
    report["animation_montages"] = montages
    return montages


def _role_montage_path(plan: dict[str, Any], role: str) -> str:
    role_spec = dict(dict(plan.get("required_animation_roles") or {}).get(role, {}) or {})
    return str(
        role_spec.get("montage_asset")
        or ("/Game/AIStudio/GeneratedAnims/Montages/AM_" + str(role).title().replace("_", ""))
    )


def _required_animation_slots(plan: dict[str, Any]) -> list[str]:
    slots: list[str] = []
    explicit = dict(plan.get("animation_slot_requirements") or {}).get("required_slots") or []
    for slot in explicit:
        slot_name = str(slot or "")
        if slot_name and slot_name not in slots:
            slots.append(slot_name)
    for spec in dict(plan.get("required_animation_roles") or {}).values():
        slot_name = str(dict(spec or {}).get("slot") or "")
        if slot_name and slot_name not in slots:
            slots.append(slot_name)
    return slots or ["DefaultSlot"]


def _inspect_anim_graph_output(unreal, anim_path: str, required_slots: list[str] | None = None) -> dict[str, Any]:
    required_slots = [str(slot) for slot in (required_slots or ["DefaultSlot"]) if str(slot)]
    report = {
        "anim_blueprint": anim_path,
        "asset_exists": False,
        "anim_graph_exists": False,
        "output_pose_found": False,
        "output_pose_connected": False,
        "upstream_nodes": [],
        "state_machine_pose_connected": False,
        "default_slot_found": False,
        "default_slot_pose_connected": False,
        "default_slot_reaches_output_pose": False,
        "required_slots": required_slots,
        "slots": {},
        "all_required_slots_reach_output_pose": False,
        "errors": [],
    }
    if not anim_path:
        return report
    try:
        anim_bp = unreal.EditorAssetLibrary.load_asset(anim_path) if unreal.EditorAssetLibrary.does_asset_exist(anim_path) else None
        report["asset_exists"] = bool(anim_bp)
        if not anim_bp:
            return report
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(anim_bp, "AnimGraph")
        report["anim_graph_exists"] = bool(editor)
        if not editor:
            return report
        links: dict[str, list[str]] = {}
        for node in editor.list_all_nodes() or []:
            title = _node_title(unreal, node)
            links.setdefault(title, [])
            for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
                try:
                    for linked in unreal.BlueprintGraphPinLibrary.list_connected_pins(pin) or []:
                        owner = unreal.BlueprintGraphPinLibrary.get_owning_node(linked)
                        if owner:
                            linked_title = _node_title(unreal, owner)
                            if linked_title not in links[title]:
                                links[title].append(linked_title)
                except Exception:
                    pass
            if title == "Output Pose":
                report["output_pose_found"] = True
                result_pin = _pin(unreal, node, "Result")
                try:
                    for linked in unreal.BlueprintGraphPinLibrary.list_connected_pins(result_pin) or []:
                        owner = unreal.BlueprintGraphPinLibrary.get_owning_node(linked)
                        if owner:
                            owner_title = _node_title(unreal, owner)
                            report["upstream_nodes"].append(owner_title)
                            report["output_pose_connected"] = True
                except Exception as exc:
                    report["errors"].append("Output Pose link inspection failed: " + str(exc))
            if "StateMachine" in str(node.get_class().get_name()):
                pose_pin = _pin(unreal, node, "Pose")
                try:
                    if pose_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(pose_pin):
                        report["state_machine_pose_connected"] = True
                except Exception:
                    pass
            for slot_name in required_slots:
                slot_title = "Slot '" + slot_name + "'"
                report["slots"].setdefault(
                    slot_name,
                    {"found": False, "pose_connected": False, "reaches_output_pose": False},
                )
                if title != slot_title:
                    continue
                report["slots"][slot_name]["found"] = True
                if slot_name == "DefaultSlot":
                    report["default_slot_found"] = True
                pose_pin = _pin(unreal, node, "Pose")
                try:
                    pose_connected = bool(
                        pose_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(pose_pin)
                    )
                    report["slots"][slot_name]["pose_connected"] = pose_connected
                    if slot_name == "DefaultSlot":
                        report["default_slot_pose_connected"] = pose_connected
                except Exception:
                    pass
        for slot_name in required_slots:
            slot_title = "Slot '" + slot_name + "'"
            frontier = [slot_title]
            seen = set()
            while frontier:
                current = frontier.pop(0)
                if current in seen:
                    continue
                seen.add(current)
                if current == "Output Pose":
                    report["slots"].setdefault(
                        slot_name,
                        {"found": False, "pose_connected": False, "reaches_output_pose": False},
                    )
                    report["slots"][slot_name]["reaches_output_pose"] = True
                    if slot_name == "DefaultSlot":
                        report["default_slot_reaches_output_pose"] = True
                    break
                frontier.extend([item for item in links.get(current, []) if item not in seen])
        report["all_required_slots_reach_output_pose"] = all(
            row.get("found") and row.get("pose_connected") and row.get("reaches_output_pose")
            for row in report["slots"].values()
        )
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def _inspect_abp_climbing_update(unreal, anim_path: str) -> dict[str, Any]:
    report = {
        "anim_blueprint": anim_path,
        "event_graph_exists": False,
        "has_cast_to_lester": False,
        "sets_climbing": False,
        "sets_climb_hanging": False,
        "sets_wall_jump": False,
        "sets_climb_speed": False,
        "data_pins_connected": {},
        "ok": False,
        "errors": [],
    }
    try:
        anim_bp = unreal.EditorAssetLibrary.load_asset(anim_path) if unreal.EditorAssetLibrary.does_asset_exist(anim_path) else None
        if not anim_bp:
            return report
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(anim_bp, "EventGraph")
        report["event_graph_exists"] = bool(editor)
        if not editor:
            return report
        titles = [_node_title(unreal, node) for node in editor.list_all_nodes() or []]
        report["has_cast_to_lester"] = "Cast To BP_LesterPhoenix" in titles
        report["sets_climbing"] = "Set bIsClimbing" in titles
        report["sets_climb_hanging"] = "Set bIsClimbHanging" in titles
        report["sets_wall_jump"] = "Set bIsClimbWallJumping" in titles
        report["sets_climb_speed"] = "Set ClimbSpeed" in titles
        for variable in (
            "bIsClimbing",
            "bIsClimbHanging",
            "bIsClimbWallJumping",
            "bClimbWallDetected",
            "ClimbSpeed",
            "ClimbVerticalInput",
        ):
            connected = False
            for node in editor.list_all_nodes() or []:
                if _node_title(unreal, node) != "Set " + variable:
                    continue
                value_pin = _pin(unreal, node, variable)
                try:
                    connected = bool(value_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(value_pin))
                except Exception:
                    connected = False
                break
            report["data_pins_connected"][variable] = connected
        report["ok"] = bool(
            report["event_graph_exists"]
            and report["has_cast_to_lester"]
            and report["sets_climbing"]
            and report["sets_climb_hanging"]
            and report["sets_wall_jump"]
            and report["sets_climb_speed"]
            and all(report["data_pins_connected"].values())
        )
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def _inspect_character_anim_binding(unreal, character: Any, anim_path: str) -> dict[str, Any]:
    report = {
        "expected_anim_blueprint": anim_path,
        "skeletal_mesh_components": [],
        "has_expected_anim_blueprint_on_mesh": False,
        "errors": [],
    }
    expected_markers = {
        anim_path,
        anim_path + "." + anim_path.rsplit("/", 1)[-1] + "_C",
    }
    try:
        subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        library = unreal.SubobjectDataBlueprintFunctionLibrary
        for handle in subsystem.k2_gather_subobject_data_for_blueprint(character) or []:
            data = library.get_data(handle)
            obj = None
            try:
                obj = library.get_object_for_blueprint(data, character)
            except Exception:
                try:
                    obj = library.get_object(data)
                except Exception:
                    obj = None
            if obj is None:
                continue
            class_path = str(obj.get_class().get_path_name())
            if "SkeletalMeshComponent" not in class_path:
                continue
            row = {
                "name": str(library.get_display_name(data)),
                "variable": str(library.get_variable_name(data)),
                "class": class_path,
                "animation_mode": "",
                "anim_class": "",
                "skeletal_mesh": "",
                "uses_expected_anim_blueprint": False,
            }
            for prop in ("animation_mode", "anim_class", "skeletal_mesh"):
                try:
                    row[prop] = str(obj.get_editor_property(prop))
                except Exception:
                    row[prop] = ""
            anim_class = str(row.get("anim_class") or "")
            row["uses_expected_anim_blueprint"] = any(marker in anim_class for marker in expected_markers)
            if row["uses_expected_anim_blueprint"]:
                report["has_expected_anim_blueprint_on_mesh"] = True
            report["skeletal_mesh_components"].append(row)
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def _exec_successors(unreal, node: Any) -> list[Any]:
    successors: list[Any] = []
    for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        if not (_is_output_pin(unreal, pin) and _is_exec_pin(unreal, pin)):
            continue
        for linked in _linked_pins(unreal, pin):
            owner = _owning_node(unreal, linked)
            if owner is not None:
                successors.append(owner)
    return successors


def _exec_reaches(unreal, starts: list[Any], predicate: Any, max_depth: int = 96) -> bool:
    queue = list(starts)
    seen: set[int] = set()
    depths = {id(node): 0 for node in queue}
    while queue:
        node = queue.pop(0)
        if id(node) in seen:
            continue
        seen.add(id(node))
        try:
            if predicate(node):
                return True
        except Exception:
            pass
        if depths.get(id(node), 0) >= max_depth:
            continue
        for next_node in _exec_successors(unreal, node):
            if id(next_node) not in seen:
                depths[id(next_node)] = depths.get(id(node), 0) + 1
                queue.append(next_node)
    return False


def _node_montage_pin_value(unreal, node: Any) -> str:
    pin = _pin(unreal, node, "AnimMontage")
    if pin is None:
        return ""
    try:
        return str(unreal.BlueprintGraphPinLibrary.get_pin_value(pin))
    except Exception:
        return ""


def _feature_start_nodes(unreal, nodes: list[Any], feature: dict[str, Any]) -> tuple[str, list[Any]]:
    if feature.get("event"):
        event = "Event Tick" if str(feature.get("event")).lower() in {"tick", "event tick"} else str(feature.get("event"))
        return event, [node for node in nodes if _node_title(unreal, node) == event]
    key = "Space Bar" if str(feature.get("key")) == "SpaceBar" else str(feature.get("key") or "")
    return key, [node for node in nodes if _node_title(unreal, node) == key]


def _inspect_feature_exec_paths(unreal, nodes: list[Any], plan: dict[str, Any]) -> dict[str, Any]:
    report = {"features": {}, "ok": True}
    for feature in plan.get("features") or []:
        feature = dict(feature or {})
        start_label, starts = _feature_start_nodes(unreal, nodes, feature)
        feature_row = {
            "start": start_label,
            "start_found": bool(starts),
            "required_montage_roles": [],
            "montage_paths_reached": {},
            "requires_launch": False,
            "launch_reached": True,
            "ok": bool(starts),
        }
        for action in feature.get("actions") or []:
            action = dict(action or {})
            action_type = str(action.get("type") or "")
            if action_type == "play_montage":
                role = str(action.get("role") or "")
                montage_path = _role_montage_path(plan, role)
                feature_row["required_montage_roles"].append(role)
                reached = _exec_reaches(
                    unreal,
                    starts,
                    lambda node, expected=montage_path: (
                        _node_title(unreal, node).replace(" ", "").lower() == "playanimmontage"
                        and expected in _node_montage_pin_value(unreal, node)
                    ),
                )
                feature_row["montage_paths_reached"][role] = reached
                feature_row["ok"] = bool(feature_row["ok"] and reached)
            if action_type == "launch_character":
                feature_row["requires_launch"] = True
                reached = _exec_reaches(
                    unreal,
                    starts,
                    lambda node: _node_title(unreal, node).replace(" ", "").lower() == "launchcharacter",
                )
                feature_row["launch_reached"] = reached
                feature_row["ok"] = bool(feature_row["ok"] and reached)
        report["features"][str(feature.get("name") or start_label)] = feature_row
        report["ok"] = bool(report["ok"] and feature_row["ok"])
    return report


def _ensure_abp_climbing_update_wiring(unreal, anim_bp: Any, report: dict[str, Any]) -> None:
    if anim_bp is None:
        return
    try:
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(anim_bp, "EventGraph")
        if editor is None:
            report.setdefault("warnings", []).append("AnimBlueprint EventGraph unavailable for climbing update wiring.")
            return
        existing_status = _inspect_abp_climbing_update(unreal, anim_bp.get_path_name().split(".")[0])
        if existing_status.get("ok"):
            report.setdefault("abp_update_wiring", {})["climbing_already_present"] = True
            return
        cleanup_titles = {
            "TryGetPawnOwner",
            "Cast To BP_LesterPhoenix",
            "Set bIsClimbing",
            "Set bIsClimbHanging",
            "Set bIsClimbWallJumping",
            "Set bClimbWallDetected",
            "Set ClimbSpeed",
            "Set ClimbVerticalInput",
            "Get bIsClimbing",
            "Get bIsClimbHanging",
            "Get bIsClimbWallJumping",
            "Get bClimbWallDetected",
            "Get ClimbSpeed",
            "Get ClimbVerticalInput",
        }
        stale = [node for node in editor.list_all_nodes() or [] if _node_title(unreal, node) in cleanup_titles]
        if stale:
            try:
                editor.remove_nodes(stale)
                report.setdefault("abp_update_wiring", {})["stale_nodes_removed"] = len(stale)
            except Exception as exc:
                report.setdefault("warnings", []).append("Could not remove stale ABP climbing nodes: " + str(exc))
        sequence = next((node for node in editor.list_all_nodes() or [] if _node_title(unreal, node) == "Sequence"), None)
        if sequence is None:
            report.setdefault("warnings", []).append("AnimBlueprint update Sequence node not found; climbing variables added but update chain not wired.")
            return
        before_outputs = list(sequence.list_output_pins() or [])
        try:
            editor.add_node_pin(sequence)
        except Exception:
            pass
        output_pins = list(sequence.list_output_pins() or [])
        start_pin = output_pins[-1] if len(output_pins) > len(before_outputs) else (output_pins[-1] if output_pins else None)
        owner = editor.add_call_function_node("/Script/Engine.AnimInstance:TryGetPawnOwner")
        _set_pos(unreal, owner, -1100.0, 1640.0)
        cast = editor.create_node_from_name(
            "Utilities|Casting|CastToBP_LesterPhoenix",
            unreal.Vector2D(-740.0, 1640.0),
            [_pin(unreal, owner, "ReturnValue")],
            None,
        )
        _set_pos(unreal, cast, -740.0, 1640.0)
        _connect(unreal, start_pin, _pin(unreal, cast, "execute"), "ABP Update Sequence -> Cast Lester", report)
        _connect(unreal, _pin(unreal, owner, "ReturnValue"), _pin(unreal, cast, "Object"), "TryGetPawnOwner -> Cast Object", report)
        source_self = _pin(unreal, cast, "AsBP Lester Phoenix", "As BP Lester Phoenix")
        previous_exec = _pin(unreal, cast, "then")
        class_path = "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix.BP_LesterPhoenix_C"
        variable_pairs = [
            ("bIsClimbing", "bIsClimbing"),
            ("bIsClimbHanging", "bIsClimbHanging"),
            ("bIsClimbWallJumping", "bIsClimbWallJumping"),
            ("bClimbWallDetected", "bClimbWallDetected"),
            ("ClimbSpeed", "ClimbSpeed"),
            ("ClimbVerticalInput", "ClimbVerticalInput"),
        ]
        for index, (source_var, target_var) in enumerate(variable_pairs):
            getter = editor.add_get_member_variable_node(source_var, class_path)
            setter = editor.add_set_member_variable_node(target_var)
            _set_pos(unreal, getter, -360.0, 1500.0 + index * 120.0)
            _set_pos(unreal, setter, 40.0 + index * 280.0, 1640.0)
            _connect(unreal, source_self, _pin(unreal, getter, "self", "target"), "Lester -> " + source_var, report)
            _connect(unreal, _pin(unreal, getter, source_var), _pin(unreal, setter, target_var), source_var + " -> ABP " + target_var, report)
            _connect(unreal, previous_exec, _pin(unreal, setter, "execute"), "ABP climbing update " + target_var, report)
            previous_exec = _pin(unreal, setter, "then")
        report.setdefault("abp_update_wiring", {})["climbing_added"] = True
    except Exception as exc:
        report.setdefault("warnings", []).append("AnimBlueprint climbing update wiring failed: " + str(exc))


def _key_palette(key_name: str) -> str:
    key = "SpaceBar" if str(key_name).lower() in {"space", "spacebar"} else str(key_name)
    return "Input|KeyboardEvents|" + key


def _event_palette(event_name: str) -> str:
    event = str(event_name or "").strip().lower()
    if event in {"tick", "event tick", "receive tick"}:
        return "AddEvent|EventTick"
    if event in {"beginplay", "begin play", "event beginplay"}:
        return "AddEvent|EventBeginPlay"
    return ""


def _vector_literal(value: dict[str, Any] | None) -> str:
    value = value or {}
    return "(X={:.6f},Y={:.6f},Z={:.6f})".format(
        float(value.get("x") or 0.0),
        float(value.get("y") or 0.0),
        float(value.get("z") or 0.0),
    )


def _author_action_chain(unreal, editor: Any, feature: dict[str, Any], report: dict[str, Any]) -> None:
    y = float(feature.get("graph_y") or 0.0)
    x = 0.0
    trigger = str(feature.get("event") or "")
    palette = _event_palette(trigger) if trigger else _key_palette(str(feature.get("key") or ""))
    key_node = _create_node(unreal, editor, palette, x, y, report)
    previous_exec = _pin(unreal, key_node, "Pressed", "then") if key_node else None
    movement_get = None
    last_trace_node = None

    for index, action in enumerate(feature.get("actions") or [], 1):
        action_type = str(action.get("type") or "")
        x = 360.0 * index
        node = None
        next_exec_override = None
        if action_type == "set_bool":
            node = editor.add_set_member_variable_node(str(action.get("variable") or ""))
            _set_pos(unreal, node, x, y)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "SetVar|" + str(action.get("variable") or ""),
                    "name": str(node.get_name()),
                    "title": _node_title(unreal, node),
                    "pins": _pin_names(unreal, node),
                }
            )
            _set_pin_value(unreal, _pin(unreal, node, str(action.get("variable") or "")), str(bool(action.get("value"))).lower(), action_type, report)
        elif action_type == "set_float":
            node = editor.add_set_member_variable_node(str(action.get("variable") or ""))
            _set_pos(unreal, node, x, y)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "SetVar|" + str(action.get("variable") or ""),
                    "name": str(node.get_name()),
                    "title": _node_title(unreal, node),
                    "pins": _pin_names(unreal, node),
                }
            )
            _set_pin_value(unreal, _pin(unreal, node, str(action.get("variable") or "")), action.get("value"), action_type, report)
        elif action_type == "print":
            node = _create_node(unreal, editor, "Development|PrintString", x, y, report)
            _set_pin_value(unreal, _pin(unreal, node, "InString"), action.get("text") or feature.get("debug_text") or feature.get("name"), "PrintString.InString", report)
            _set_pin_value(unreal, _pin(unreal, node, "bPrintToScreen"), "true", "PrintString.bPrintToScreen", report)
            _set_pin_value(unreal, _pin(unreal, node, "bPrintToLog"), "true", "PrintString.bPrintToLog", report)
        elif action_type == "set_movement_mode":
            if movement_get is None:
                movement_get = editor.add_get_member_variable_node("CharacterMovement")
                _set_pos(unreal, movement_get, x, y + 220)
                report.setdefault("nodes_created", []).append(
                    {
                        "palette": "GetVar|CharacterMovement",
                        "name": str(movement_get.get_name()),
                        "title": _node_title(unreal, movement_get),
                        "pins": _pin_names(unreal, movement_get),
                    }
                )
            node = _create_node(unreal, editor, "Pawn|Components|CharacterMovement|SetMovementMode", x, y, report, _pin(unreal, movement_get, "CharacterMovement"))
            _set_pin_value(unreal, _pin(unreal, node, "NewMovementMode", "MovementMode"), action.get("mode") or "MOVE_Flying", "SetMovementMode.NewMovementMode", report)
        elif action_type == "set_character_movement_float":
            if movement_get is None:
                movement_get = editor.add_get_member_variable_node("CharacterMovement")
                _set_pos(unreal, movement_get, x, y + 220)
            node = editor.add_set_member_variable_node(str(action.get("variable") or ""), "/Script/Engine.CharacterMovementComponent")
            _set_pos(unreal, node, x, y)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "SetCharacterMovement|" + str(action.get("variable") or ""),
                    "name": str(node.get_name()),
                    "title": _node_title(unreal, node),
                    "pins": _pin_names(unreal, node),
                }
            )
            _connect(unreal, _pin(unreal, movement_get, "CharacterMovement"), _pin(unreal, node, "self", "target"), "CharacterMovement target", report)
            _set_pin_value(unreal, _pin(unreal, node, str(action.get("variable") or "")), action.get("value"), str(action.get("variable") or ""), report)
        elif action_type == "launch_character":
            node = _create_node(unreal, editor, "Character|LaunchCharacter", x, y, report)
            _set_pin_value(unreal, _pin(unreal, node, "LaunchVelocity"), _vector_literal(action.get("velocity")), "LaunchCharacter.LaunchVelocity", report)
            _set_pin_value(unreal, _pin(unreal, node, "bXYOverride"), str(bool(action.get("xy_override"))).lower(), "LaunchCharacter.bXYOverride", report)
            _set_pin_value(unreal, _pin(unreal, node, "bZOverride"), str(bool(action.get("z_override"))).lower(), "LaunchCharacter.bZOverride", report)
        elif action_type == "play_montage":
            node = _create_node(unreal, editor, "Animation|PlayAnimMontage", x, y, report)
            role = str(action.get("role") or "")
            montage_path = str(dict(report.get("animation_montages") or {}).get(role, {}).get("asset_path") or "")
            if montage_path:
                _set_pin_value(unreal, _pin(unreal, node, "AnimMontage"), montage_path, "PlayAnimMontage.AnimMontage", report)
            _set_pin_value(unreal, _pin(unreal, node, "InPlayRate"), action.get("play_rate") or 1.0, "PlayAnimMontage.InPlayRate", report)
        elif action_type == "capsule_trace":
            node = _create_node(unreal, editor, "Collision|CapsuleTraceByChannel", x, y, report)
            _set_pin_value(unreal, _pin(unreal, node, "TraceChannel"), "WorldStatic", "CapsuleTrace.TraceChannel", report)
            _set_pin_value(unreal, _pin(unreal, node, "Radius"), action.get("radius") or 34.0, "CapsuleTrace.Radius", report)
            _set_pin_value(unreal, _pin(unreal, node, "HalfHeight"), action.get("half_height") or 72.0, "CapsuleTrace.HalfHeight", report)
            location_node = _create_node(unreal, editor, "Transformation|GetActorLocation", x - 260.0, y - 260.0, report)
            forward_node = _create_node(unreal, editor, "Transformation|GetActorForwardVector", x - 260.0, y - 60.0, report)
            scale_node = editor.add_call_function_node("/Script/Engine.KismetMathLibrary:Multiply_VectorFloat")
            _set_pos(unreal, scale_node, x + 20.0, y - 60.0)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "KismetMathLibrary|Multiply_VectorFloat",
                    "name": str(scale_node.get_name()),
                    "title": _node_title(unreal, scale_node),
                    "pins": _pin_names(unreal, scale_node),
                }
            )
            add_node = editor.add_call_function_node("/Script/Engine.KismetMathLibrary:Add_VectorVector")
            _set_pos(unreal, add_node, x + 280.0, y - 160.0)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "KismetMathLibrary|Add_VectorVector",
                    "name": str(add_node.get_name()),
                    "title": _node_title(unreal, add_node),
                    "pins": _pin_names(unreal, add_node),
                }
            )
            _set_pin_value(unreal, _pin(unreal, scale_node, "B"), action.get("distance_cm") or 95.0, "WallTrace.Distance", report)
            _connect(unreal, _pin(unreal, location_node, "ReturnValue"), _pin(unreal, node, "Start"), "ActorLocation -> CapsuleTrace.Start", report)
            _connect(unreal, _pin(unreal, forward_node, "ReturnValue"), _pin(unreal, scale_node, "A"), "ForwardVector -> TraceDistanceScale", report)
            _connect(unreal, _pin(unreal, location_node, "ReturnValue"), _pin(unreal, add_node, "A"), "ActorLocation -> TraceEndAdd", report)
            _connect(unreal, _pin(unreal, scale_node, "ReturnValue"), _pin(unreal, add_node, "B"), "ForwardOffset -> TraceEndAdd", report)
            _connect(unreal, _pin(unreal, add_node, "ReturnValue"), _pin(unreal, node, "End"), "ActorLocationPlusForward -> CapsuleTrace.End", report)
            report.setdefault("trace_channels", []).append(list(action.get("channels") or []))
            last_trace_node = node
        elif action_type == "branch_on_last_trace":
            node = _create_node(unreal, editor, "Utilities|FlowControl|Branch", x, y, report)
            if last_trace_node is not None:
                _connect(
                    unreal,
                    _pin(unreal, last_trace_node, "ReturnValue", "Return Value"),
                    _pin(unreal, node, "Condition"),
                    "Trace ReturnValue -> Branch Condition",
                    report,
                )
            false_print = str(action.get("false_print") or "")
            false_previous = _pin(unreal, node, "False", "else")
            if false_print:
                print_node = _create_node(unreal, editor, "Development|PrintString", x + 360.0, y + 220.0, report)
                _set_pin_value(unreal, _pin(unreal, print_node, "InString"), false_print, "ClimbMiss.PrintString", report)
                _connect(unreal, false_previous, _pin(unreal, print_node, "execute"), "Climb miss -> PrintString", report)
                false_previous = _pin(unreal, print_node, "then")
            false_index = 0
            for reset in list(action.get("false_set") or []):
                false_index += 1
                reset_node = editor.add_set_member_variable_node(str(reset.get("variable") or ""))
                _set_pos(unreal, reset_node, x + 360.0 * false_index, y + 360.0)
                report.setdefault("nodes_created", []).append(
                    {
                        "palette": "SetVar|" + str(reset.get("variable") or ""),
                        "name": str(reset_node.get_name()),
                        "title": _node_title(unreal, reset_node),
                        "pins": _pin_names(unreal, reset_node),
                    }
                )
                _set_pin_value(unreal, _pin(unreal, reset_node, str(reset.get("variable") or "")), str(bool(reset.get("value"))).lower(), "BranchFalse.SetBool", report)
                _connect(unreal, false_previous, _pin(unreal, reset_node, "execute"), "Branch false reset " + str(reset.get("variable") or ""), report)
                false_previous = _pin(unreal, reset_node, "then")
            for reset in list(action.get("false_float_set") or []):
                false_index += 1
                reset_node = editor.add_set_member_variable_node(str(reset.get("variable") or ""))
                _set_pos(unreal, reset_node, x + 360.0 * false_index, y + 360.0)
                report.setdefault("nodes_created", []).append(
                    {
                        "palette": "SetVar|" + str(reset.get("variable") or ""),
                        "name": str(reset_node.get_name()),
                        "title": _node_title(unreal, reset_node),
                        "pins": _pin_names(unreal, reset_node),
                    }
                )
                _set_pin_value(unreal, _pin(unreal, reset_node, str(reset.get("variable") or "")), reset.get("value"), "BranchFalse.SetFloat", report)
                _connect(unreal, false_previous, _pin(unreal, reset_node, "execute"), "Branch false reset " + str(reset.get("variable") or ""), report)
                false_previous = _pin(unreal, reset_node, "then")
            if bool(action.get("true_do_once")):
                gate = _create_node(unreal, editor, "Utilities|FlowControl|DoOnce", x + 360.0, y, report)
                _connect(unreal, _pin(unreal, node, "True", "then"), _pin(unreal, gate, "execute"), "Climb branch true -> DoOnce", report)
                _connect(unreal, false_previous, _pin(unreal, gate, "Reset"), "Climb branch false -> DoOnce Reset", report)
                next_exec_override = _pin(unreal, gate, "Completed")
        elif action_type == "line_trace":
            node = _create_node(unreal, editor, "Collision|LineTraceByChannel", x, y, report)
            distance = float(action.get("distance_cm") or 2500.0)
            location_node = _create_node(unreal, editor, "Transformation|GetActorLocation", x - 260.0, y - 260.0, report)
            forward_node = _create_node(unreal, editor, "Transformation|GetActorForwardVector", x - 260.0, y - 60.0, report)
            scale_node = editor.add_call_function_node("/Script/Engine.KismetMathLibrary:Multiply_VectorFloat")
            _set_pos(unreal, scale_node, x + 20.0, y - 60.0)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "KismetMathLibrary|Multiply_VectorFloat",
                    "name": str(scale_node.get_name()),
                    "title": _node_title(unreal, scale_node),
                    "pins": _pin_names(unreal, scale_node),
                }
            )
            add_node = editor.add_call_function_node("/Script/Engine.KismetMathLibrary:Add_VectorVector")
            _set_pos(unreal, add_node, x + 280.0, y - 160.0)
            report.setdefault("nodes_created", []).append(
                {
                    "palette": "KismetMathLibrary|Add_VectorVector",
                    "name": str(add_node.get_name()),
                    "title": _node_title(unreal, add_node),
                    "pins": _pin_names(unreal, add_node),
                }
            )
            _set_pin_value(unreal, _pin(unreal, scale_node, "B"), distance, "LineTrace.Distance", report)
            _connect(unreal, _pin(unreal, location_node, "ReturnValue"), _pin(unreal, node, "Start"), "ActorLocation -> LineTrace.Start", report)
            _connect(unreal, _pin(unreal, forward_node, "ReturnValue"), _pin(unreal, scale_node, "A"), "ForwardVector -> GrappleTraceDistanceScale", report)
            _connect(unreal, _pin(unreal, location_node, "ReturnValue"), _pin(unreal, add_node, "A"), "ActorLocation -> GrappleTraceEndAdd", report)
            _connect(unreal, _pin(unreal, scale_node, "ReturnValue"), _pin(unreal, add_node, "B"), "ForwardOffset -> GrappleTraceEndAdd", report)
            _connect(unreal, _pin(unreal, add_node, "ReturnValue"), _pin(unreal, node, "End"), "ActorLocationPlusForward -> LineTrace.End", report)
        elif action_type == "delay":
            node = _create_node(unreal, editor, "Utilities|FlowControl|Delay", x, y, report)
            _set_pin_value(unreal, _pin(unreal, node, "Duration"), action.get("duration") or 0.35, "Delay.Duration", report)
        else:
            report.setdefault("warnings", []).append("Unsupported feature action: " + action_type)
        if node is not None and previous_exec is not None:
            _connect(unreal, previous_exec, _pin(unreal, node, "execute"), feature.get("name", "Feature") + " step " + str(index), report)
        if node is not None:
            previous_exec = next_exec_override or (_pin(unreal, node, "True", "then") if action_type == "branch_on_last_trace" else _pin(unreal, node, "then"))


def _cleanup_legacy_climbing_scaffold(unreal, editor: Any, report: dict[str, Any]) -> None:
    legacy_titles = {
        "N",
        "G",
        "Space Bar",
        "C",
        "Set bIsClimbing",
        "Set bWantsToClimb",
        "Set bClimbWallDetected",
        "Set bIsClimbHanging",
        "Set bIsClimbWallJumping",
        "Set bIsGrappling",
        "Set bIsVaulting",
        "Set bIsDodgeRolling",
        "Set bTraversalInvulnerable",
        "Set ClimbVerticalInput",
        "Set ClimbSpeed",
        "Set ClimbWallDistance",
        "SetMovementMode",
        "Set Movement Mode",
        "Set Gravity Scale",
        "CapsuleTraceByChannel",
        "Capsule Trace By Channel",
        "LineTraceByChannel",
        "Line Trace By Channel",
        "LaunchCharacter",
        "Get Actor Location",
        "GetActorForwardVector",
        "vector * float",
        "vector + vector",
        "Branch",
        "Do Once",
        "PlayAnimMontage",
        "Delay",
    }
    remove = []
    for node in editor.list_all_nodes() or []:
        title = _node_title(unreal, node)
        if title in legacy_titles:
            remove.append(node)
            continue
        if "Gravity Scale" in title or "GravityScale" in title:
            remove.append(node)
    if not remove:
        return
    if bool(report.get("cleanup_dry_run")):
        report.setdefault("cleanup_candidates", []).extend([_node_title(unreal, node) for node in remove])
        return
    try:
        for start in range(0, len(remove), 24):
            batch = remove[start : start + 24]
            try:
                for node in batch:
                    try:
                        for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
                            try:
                                unreal.BlueprintGraphPinLibrary.break_pin_links(pin)
                            except Exception:
                                pass
                    except Exception:
                        pass
                editor.remove_nodes(batch)
            except Exception as batch_exc:
                report.setdefault("warnings", []).append(
                    "Generated traversal cleanup batch failed: " + str(batch_exc)
                )
        report.setdefault("nodes_removed", []).extend([_node_title(unreal, node) for node in remove])
    except Exception as exc:
        report.setdefault("warnings", []).append("Legacy climbing scaffold cleanup failed: " + str(exc))


def execute_character_feature_plan(plan: dict[str, Any] | None = None, save: bool = True) -> dict[str, Any]:
    """Execute an approved spec-driven character feature plan inside Unreal."""

    import unreal

    plan = dict(plan or build_master_traversal_combat_plan())
    character_path = str(plan.get("target_asset") or DEFAULT_CHARACTER_PATH)
    anim_path = str(plan.get("anim_blueprint") or DEFAULT_ANIM_BLUEPRINT_PATH)
    report: dict[str, Any] = {
        "ok": False,
        "operation": "gameplay.execute_character_feature_plan",
        "framework": plan.get("framework"),
        "feature": plan.get("feature"),
        "character_path": character_path,
        "anim_blueprint": anim_path,
        "assets": {},
        "variables_added": [],
        "variables_reused": [],
        "nodes_created": [],
        "links_created": [],
        "pins_set": [],
        "warnings": [],
        "errors": [],
        "compile": {},
        "saved": {},
        "verification": {},
    }

    try:
        character = unreal.EditorAssetLibrary.load_asset(character_path)
        anim_bp = unreal.EditorAssetLibrary.load_asset(anim_path) if anim_path else None
        for path in (
            character_path,
            anim_path,
            str(plan.get("requested_skeleton") or ""),
            str(plan.get("fallback_skeleton") or ""),
        ):
            if not path:
                continue
            asset = unreal.EditorAssetLibrary.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
            report["assets"][path] = {
                "exists": bool(asset),
                "class": asset.get_class().get_name() if asset else None,
            }
        if character is None:
            raise RuntimeError("Character Blueprint could not be loaded: " + character_path)
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(character, "EventGraph")
        if editor is None:
            raise RuntimeError("Character EventGraph editor unavailable")
        if plan.get("cleanup_legacy_climbing_scaffold"):
            _cleanup_legacy_climbing_scaffold(unreal, editor, report)
        _resolve_animation_roles(unreal, plan, report, save=save)
        _ensure_role_montages(unreal, plan, report, save=save)
        current_validation = validate_character_feature_plan(plan, _preloaded_character=character)
        if current_validation.get("ok"):
            if anim_bp is not None:
                report["compile"][anim_path] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(anim_bp))
                report["saved"][anim_path] = bool(unreal.EditorAssetLibrary.save_loaded_asset(anim_bp, False)) if save else False
            report["compile"][character_path] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(character))
            report["saved"][character_path] = bool(unreal.EditorAssetLibrary.save_loaded_asset(character, False)) if save else False
            report["verification"] = current_validation
            report["already_valid"] = True
            report["ok"] = bool(report["compile"].get(character_path)) and (
                not save or bool(report["saved"].get(character_path))
            )
            return report
        try:
            subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
            if subsystem:
                subsystem.open_editor_for_assets([asset for asset in (character, anim_bp) if asset is not None])
        except Exception as exc:
            report["warnings"].append("Open editor warning: " + str(exc))

        for target in (character, anim_bp):
            if target is None:
                continue
            target_editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(target, "EventGraph")
            if target_editor is None:
                continue
            for variable in plan.get("variables") or []:
                _add_variable(unreal, target_editor, target, dict(variable), report)
        report["compile"][character_path + "#pre_abp"] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(character))
        if save:
            report["saved"][character_path + "#pre_abp"] = bool(unreal.EditorAssetLibrary.save_loaded_asset(character, False))
        _ensure_abp_climbing_update_wiring(unreal, anim_bp, report)

        begin = _create_node(unreal, editor, "AddEvent|EventBeginPlay", 0.0, -720.0, report)
        begin_print = _create_node(unreal, editor, "Development|PrintString", 360.0, -720.0, report)
        _set_pin_value(
            unreal,
            _pin(unreal, begin_print, "InString"),
            "[AIStudio] Dynamic character feature system active",
            "BeginPlay.PrintString",
            report,
        )
        _connect(unreal, _pin(unreal, begin, "then"), _pin(unreal, begin_print, "execute"), "BeginPlay -> Dynamic Feature Print", report)

        for feature in plan.get("features") or []:
            key = str(dict(feature).get("key") or "")
            if key in set(plan.get("reserved_keys") or []):
                report["warnings"].append("Skipped reserved key binding: " + key)
                continue
            _author_action_chain(unreal, editor, dict(feature), report)

        if anim_bp is not None:
            report["compile"][anim_path] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(anim_bp))
            report["saved"][anim_path] = bool(unreal.EditorAssetLibrary.save_loaded_asset(anim_bp, False)) if save else False
        report["compile"][character_path] = bool(unreal.BlueprintEditorLibrary.compile_blueprint(character))
        report["saved"][character_path] = bool(unreal.EditorAssetLibrary.save_loaded_asset(character, False)) if save else False
        report["verification"] = validate_character_feature_plan(plan, _preloaded_character=character)
        report["ok"] = bool(report["compile"].get(character_path)) and (
            not save or bool(report["saved"].get(character_path))
        ) and bool(report["verification"].get("ok"))
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def preflight_character_feature_cleanup(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inspect generated traversal cleanup candidates without mutating assets."""

    import unreal

    plan = dict(plan or build_master_traversal_combat_plan())
    character_path = str(plan.get("target_asset") or DEFAULT_CHARACTER_PATH)
    report: dict[str, Any] = {
        "ok": False,
        "character_path": character_path,
        "cleanup_candidates": [],
        "errors": [],
        "warnings": [],
        "cleanup_dry_run": True,
    }
    try:
        character = unreal.EditorAssetLibrary.load_asset(character_path)
        if character is None:
            raise RuntimeError("Character Blueprint could not be loaded: " + character_path)
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(character, "EventGraph")
        if editor is None:
            raise RuntimeError("Character EventGraph editor unavailable")
        _cleanup_legacy_climbing_scaffold(unreal, editor, report)
        report["candidate_count"] = len(report.get("cleanup_candidates") or [])
        report["ok"] = True
    except Exception as exc:
        report["errors"].append(str(exc))
    return report


def validate_character_feature_plan(plan: dict[str, Any] | None = None, _preloaded_character: Any = None) -> dict[str, Any]:
    """Validate graph postconditions for a spec-driven character feature plan."""

    import json
    import unreal

    plan = dict(plan or build_master_traversal_combat_plan())
    character_path = str(plan.get("target_asset") or DEFAULT_CHARACTER_PATH)
    report = {
        "ok": False,
        "character_path": character_path,
        "required_keys": [],
        "required_events": [],
        "found_keys": {},
        "found_events": {},
        "launch_character_nodes": 0,
        "capsule_trace_nodes": 0,
        "capsule_trace_start_end_wired": False,
        "line_trace_nodes": 0,
        "line_trace_start_end_wired": False,
        "print_nodes": 0,
        "play_montage_nodes": 0,
        "play_montage_asset_pins": [],
        "do_once_nodes": 0,
        "branch_nodes": 0,
        "gravity_scale_nodes": 0,
        "state_variables": {},
        "asset_dependencies": {},
        "functional_requirements": {},
        "animation_roles": {},
        "animation_montages": {},
        "anim_graph": {},
        "abp_climbing_update": {},
        "character_anim_binding": {},
        "feature_exec_paths": {},
        "compile": {},
        "errors": [],
        "warnings": [],
    }
    try:
        character = _preloaded_character or unreal.EditorAssetLibrary.load_asset(character_path)
        if character is None:
            raise RuntimeError("Character Blueprint could not be loaded: " + character_path)
        anim_path = str(plan.get("anim_blueprint") or "")
        anim_bp_for_compile = (
            unreal.EditorAssetLibrary.load_asset(anim_path)
            if anim_path and unreal.EditorAssetLibrary.does_asset_exist(anim_path)
            else None
        )
        report["compile"][character_path] = _compile_blueprint_asset(unreal, character)
        if anim_path:
            report["compile"][anim_path] = _compile_blueprint_asset(unreal, anim_bp_for_compile)
        editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(character, "EventGraph")
        if editor is None:
            raise RuntimeError("EventGraph editor unavailable")
        titles = []
        for node in editor.list_all_nodes() or []:
            title = _node_title(unreal, node)
            titles.append(title)
            compact = title.lower().replace(" ", "")
            if compact == "launchcharacter":
                report["launch_character_nodes"] += 1
            if compact == "capsuletracebychannel":
                report["capsule_trace_nodes"] += 1
                try:
                    start_pin = _pin(unreal, node, "Start")
                    end_pin = _pin(unreal, node, "End")
                    start_wired = bool(start_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(start_pin))
                    end_wired = bool(end_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(end_pin))
                    report["capsule_trace_start_end_wired"] = bool(start_wired and end_wired)
                except Exception:
                    pass
            if compact == "linetracebychannel":
                report["line_trace_nodes"] += 1
                try:
                    start_pin = _pin(unreal, node, "Start")
                    end_pin = _pin(unreal, node, "End")
                    start_wired = bool(start_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(start_pin))
                    end_wired = bool(end_pin and unreal.BlueprintGraphPinLibrary.list_connected_pins(end_pin))
                    report["line_trace_start_end_wired"] = bool(start_wired and end_wired)
                except Exception:
                    pass
            if compact == "printstring":
                report["print_nodes"] += 1
            if compact == "playanimmontage":
                report["play_montage_nodes"] += 1
                asset_pin = _pin(unreal, node, "AnimMontage")
                value = ""
                try:
                    value = str(unreal.BlueprintGraphPinLibrary.get_pin_value(asset_pin)) if asset_pin else ""
                except Exception:
                    value = ""
                report["play_montage_asset_pins"].append(value)
            if compact == "branch":
                report["branch_nodes"] += 1
            if compact == "doonce":
                report["do_once_nodes"] += 1
            if "gravityscale" in compact or compact == "setgravityscale":
                report["gravity_scale_nodes"] += 1
        for feature in plan.get("features") or []:
            if feature.get("event"):
                event = "Event Tick" if str(feature.get("event")).lower() in {"tick", "event tick"} else str(feature.get("event"))
                report["required_events"].append(event)
                report["found_events"][event] = any(title == event for title in titles)
            else:
                key = "Space Bar" if str(feature.get("key")) == "SpaceBar" else str(feature.get("key") or "")
                report["required_keys"].append(key)
                report["found_keys"][key] = any(title == key for title in titles)
        report["feature_exec_paths"] = _inspect_feature_exec_paths(unreal, list(editor.list_all_nodes() or []), plan)
        existing = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(character) or []}
        for variable in plan.get("variables") or []:
            name = str(dict(variable).get("name") or "")
            if name:
                report["state_variables"][name] = name in existing
        requested_skeleton = str(plan.get("requested_skeleton") or "")
        fallback_skeleton = str(plan.get("fallback_skeleton") or "")
        for label, path in (
            ("character_blueprint", character_path),
            ("anim_blueprint", anim_path),
            ("requested_skeleton", requested_skeleton),
            ("fallback_skeleton", fallback_skeleton),
        ):
            if not path:
                continue
            asset = unreal.EditorAssetLibrary.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
            report["asset_dependencies"][label] = {
                "path": path,
                "exists": bool(asset),
                "class": asset.get_class().get_name() if asset else None,
            }
        action_types = {
            str(action.get("type") or "")
            for feature in plan.get("features") or []
            for action in dict(feature).get("actions") or []
        }
        min_launch_nodes = sum(
            1
            for feature in plan.get("features") or []
            for action in dict(feature).get("actions") or []
            if str(action.get("type") or "") == "launch_character"
        )
        min_montage_nodes = sum(
            1
            for feature in plan.get("features") or []
            for action in dict(feature).get("actions") or []
            if str(action.get("type") or "") == "play_montage"
        )
        required_slots = _required_animation_slots(plan)
        report["functional_requirements"] = {
            "character_blueprint_compiles": bool(report["compile"].get(character_path, {}).get("compiled")),
            "anim_blueprint_compiles": bool(
                not anim_path or report["compile"].get(anim_path, {}).get("compiled")
            ),
            "has_required_launch_nodes": report["launch_character_nodes"] >= min_launch_nodes,
            "has_required_montage_play_nodes": report["play_montage_nodes"] >= min_montage_nodes,
            "has_bound_montage_play_assets": (
                min_montage_nodes == 0
                or (
                    len([value for value in report["play_montage_asset_pins"] if value]) >= min_montage_nodes
                )
            ),
            "has_required_capsule_trace_nodes": (
                "capsule_trace" not in action_types or report["capsule_trace_nodes"] >= 1
            ),
            "has_wired_wall_probe_trace": (
                "capsule_trace" not in action_types or bool(report["capsule_trace_start_end_wired"])
            ),
            "has_required_line_trace_nodes": (
                "line_trace" not in action_types or report["line_trace_nodes"] >= 1
            ),
            "has_wired_grapple_trace": (
                "line_trace" not in action_types or bool(report["line_trace_start_end_wired"])
            ),
            "has_anim_blueprint": bool(report["asset_dependencies"].get("anim_blueprint", {}).get("exists")),
            "has_requested_or_fallback_skeleton": bool(
                report["asset_dependencies"].get("requested_skeleton", {}).get("exists")
                or report["asset_dependencies"].get("fallback_skeleton", {}).get("exists")
            ),
        }
        has_climbing = any(str(feature.get("state_variable") or "") == "bIsClimbing" for feature in plan.get("features") or [])
        if has_climbing:
            report["functional_requirements"]["climbing_is_trace_gated"] = report["branch_nodes"] >= 1
            report["functional_requirements"]["climbing_montage_is_entry_gated"] = report["do_once_nodes"] >= 1
            report["functional_requirements"]["climbing_does_not_use_gravity_toggle"] = report["gravity_scale_nodes"] == 0
            report["functional_requirements"]["climbing_has_single_wall_probe"] = report["capsule_trace_nodes"] == 1
        if plan.get("feature") == "dynamic_character_traversal_combat":
            report["functional_requirements"]["grapple_has_single_forward_trace"] = report["line_trace_nodes"] == 1
        for role, spec in dict(plan.get("required_animation_roles") or {}).items():
            role_spec = dict(spec or {})
            resolved_asset = str(role_spec.get("resolved_asset") or "")
            generated = str(role_spec.get("generated_asset") or "")
            download_destination = str(role_spec.get("download_destination_path") or "")
            preferred = [str(item) for item in role_spec.get("preferred_assets") or [] if item]
            candidates = (
                ([resolved_asset] if resolved_asset else [])
                + ([generated] if generated else [])
                + ([download_destination] if download_destination else [])
                + preferred
            )
            asset_path = next((path for path in candidates if path and unreal.EditorAssetLibrary.does_asset_exist(path)), "")
            asset = unreal.EditorAssetLibrary.load_asset(asset_path) if asset_path else None
            skeleton_path = _asset_skeleton_path(unreal, asset_path) if asset_path else ""
            semantic = _evaluate_persisted_role_asset(unreal, str(role), asset, role_spec)
            sequence_probe = {}
            bridge_library = getattr(unreal, "AIStudioBridgeLibrary", None)
            if asset and bridge_library and hasattr(bridge_library, "inspect_animation_sequence"):
                try:
                    sequence_probe = json.loads(bridge_library.inspect_animation_sequence(asset))
                except Exception as exc:
                    sequence_probe = {"ok": False, "error": str(exc)}
            target_skeletons = [
                str(role_spec.get("target_skeleton") or ""),
                str(plan.get("selected_target_skeleton") or ""),
                requested_skeleton,
                fallback_skeleton,
            ]
            skeleton_ok = (
                not asset
                or asset.get_class().get_name() != "AnimSequence"
                or bool(role_spec.get("allow_foreign_skeleton", False))
                or skeleton_path in {path for path in target_skeletons if path}
            )
            report["animation_roles"][str(role)] = {
                "resolved": bool(asset) and skeleton_ok and bool(semantic.get("accepted")),
                "asset_path": asset_path,
                "class": asset.get_class().get_name() if asset else None,
                "skeleton": skeleton_path,
                "target_skeleton_compatible": skeleton_ok,
                "download_url": str(role_spec.get("download_url") or ""),
                "semantic_evaluation": semantic,
                "sequence_probe": sequence_probe,
            }
            montage_path = _role_montage_path(plan, str(role))
            montage = unreal.EditorAssetLibrary.load_asset(montage_path) if montage_path and unreal.EditorAssetLibrary.does_asset_exist(montage_path) else None
            report["animation_montages"][str(role)] = {
                "resolved": bool(montage),
                "asset_path": montage_path,
                "class": montage.get_class().get_name() if montage else None,
                "slot": str(role_spec.get("slot") or "DefaultSlot"),
            }
        report["anim_graph"] = _inspect_anim_graph_output(unreal, anim_path, required_slots)
        report["abp_climbing_update"] = _inspect_abp_climbing_update(unreal, anim_path)
        report["character_anim_binding"] = _inspect_character_anim_binding(unreal, character, anim_path)
        if has_climbing:
            report["functional_requirements"]["abp_climbing_update_wired"] = bool(
                report["abp_climbing_update"].get("ok")
            )
        report["functional_requirements"]["character_mesh_uses_requested_anim_blueprint"] = bool(
            report["character_anim_binding"].get("has_expected_anim_blueprint_on_mesh")
        )
        report["functional_requirements"]["feature_inputs_reach_required_actions"] = bool(
            report["feature_exec_paths"].get("ok")
        )
        report["functional_requirements"]["has_required_animation_roles"] = (
            bool(report["animation_roles"])
            and all(row.get("resolved") for row in report["animation_roles"].values())
        )
        report["functional_requirements"]["has_required_animation_montages"] = (
            min_montage_nodes == 0
            or (
                bool(report["animation_montages"])
                and all(row.get("resolved") for row in report["animation_montages"].values())
            )
        )
        report["functional_requirements"]["has_anim_graph_output_pose_connection"] = bool(
            report["anim_graph"].get("output_pose_connected")
            and report["anim_graph"].get("state_machine_pose_connected")
        )
        report["functional_requirements"]["default_slot_feeds_final_pose"] = (
            min_montage_nodes == 0
            or bool(
                report["anim_graph"].get("default_slot_found")
                and report["anim_graph"].get("default_slot_pose_connected")
                and report["anim_graph"].get("default_slot_reaches_output_pose")
            )
        )
        report["functional_requirements"]["all_required_slots_feed_final_pose"] = (
            min_montage_nodes == 0
            or bool(report["anim_graph"].get("all_required_slots_reach_output_pose"))
        )
        report["ok"] = (
            all(report["found_keys"].values())
            and all(report["found_events"].values())
            and all(report["state_variables"].values())
            and report["launch_character_nodes"] >= min_launch_nodes
            and report["print_nodes"] >= 1
            and all(report["functional_requirements"].values())
        )
    except Exception as exc:
        report["errors"].append(str(exc))
    return report
