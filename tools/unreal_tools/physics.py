"""PhysicsAsset helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def _asset(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Physics asset not found: {asset_path}")
    return asset


def _bridge(unreal):
    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if not bridge:
        raise RuntimeError("AIStudioBridgeLibrary is unavailable; install/enable AIStudioBridge and restart Unreal.")
    return bridge


def list_bodies(asset_path):
    import unreal

    inspected = _decode(_bridge(unreal).inspect_physics_asset(asset_path))
    return _result(
        ok=bool(inspected.get("ok")),
        status=inspected.get("status"),
        asset_path=asset_path,
        bodies=list(inspected.get("bodies") or []),
        count=int(inspected.get("body_count") or 0),
    )


def list_constraints(asset_path):
    import unreal

    inspected = _decode(_bridge(unreal).inspect_physics_asset(asset_path))
    return _result(
        ok=bool(inspected.get("ok")),
        status=inspected.get("status"),
        asset_path=asset_path,
        constraints=list(inspected.get("constraints") or []),
        count=int(inspected.get("constraint_count") or 0),
    )


def set_body_property(asset_path, body_name, property_name, value, save=True, value_type="auto"):
    import unreal

    return _bridge(unreal).set_physics_body_property(
        asset_path,
        unreal.Name(str(body_name)),
        unreal.Name(str(property_name)),
        json.dumps(value),
    )


def set_constraint_property(asset_path, constraint_name, property_name, value, save=True, value_type="auto"):
    import unreal

    return _bridge(unreal).set_physics_constraint_property(
        asset_path,
        unreal.Name(str(constraint_name)),
        unreal.Name(str(property_name)),
        json.dumps(value),
    )


def set_profile_property(
    asset_path: str,
    profile_name: str,
    property_name: str,
    value,
    save: bool = True,
    value_type: str = "auto",
) -> str:
    import unreal

    return _bridge(unreal).set_physics_profile_property(
        asset_path,
        unreal.Name(str(profile_name)),
        unreal.Name(str(property_name)),
        json.dumps(value),
    )


def list_profiles(asset_path: str) -> str:
    import unreal

    return _bridge(unreal).list_physics_profiles(asset_path)


def add_profile(
    asset_path: str,
    profile_name: str,
    profile_type: str = "constraint",
    assign_all: bool = True,
) -> str:
    import unreal

    return _bridge(unreal).add_physics_profile(
        asset_path,
        unreal.Name(str(profile_name)),
        str(profile_type),
        bool(assign_all),
    )


def remove_profile(asset_path: str, profile_name: str, profile_type: str = "constraint") -> str:
    import unreal

    return _bridge(unreal).remove_physics_profile(
        asset_path,
        unreal.Name(str(profile_name)),
        str(profile_type),
    )


def create_physics_asset(skeletal_mesh_path: str, save_path: str = "", assign_to_mesh: bool = True) -> str:
    import unreal

    if not save_path:
        package_path = skeletal_mesh_path.rsplit(".", 1)[0]
        directory, _, asset_name = package_path.rpartition("/")
        save_path = f"{directory}/PHYS_{asset_name}"
    return _bridge(unreal).create_physics_asset(skeletal_mesh_path, save_path, bool(assign_to_mesh))


def add_body(physics_asset_path: str, bone_name: str, shape_type: str = "capsule") -> str:
    import unreal

    return _bridge(unreal).add_physics_body(physics_asset_path, unreal.Name(str(bone_name)), str(shape_type))


def add_constraint(physics_asset_path: str, bone_name_a: str, bone_name_b: str) -> str:
    import unreal

    return _bridge(unreal).add_physics_constraint(
        physics_asset_path,
        unreal.Name(str(bone_name_a)),
        unreal.Name(str(bone_name_b)),
    )


def set_collision_profile(actor_query: str, profile_name: str, component_name: str = "") -> str:
    import unreal

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    query = str(actor_query or "").strip().lower()
    actors = subsystem.get_selected_level_actors() if query in {"", "selected", "selection"} else subsystem.get_all_level_actors()
    matches = []
    for actor in actors:
        labels = {actor.get_name().lower(), actor.get_actor_label().lower(), actor.get_path_name().lower()}
        if query not in {"", "selected", "selection"} and not any(query in label for label in labels):
            continue
        components = actor.get_components_by_class(unreal.PrimitiveComponent)
        for component in components:
            if component_name and component.get_name().lower() != str(component_name).lower():
                continue
            component.set_collision_profile_name(unreal.Name(str(profile_name)))
            matches.append(
                {
                    "actor": actor.get_path_name(),
                    "component": component.get_path_name(),
                    "profile": str(component.get_collision_profile_name()),
                }
            )
    if not matches:
        return _result(ok=False, status="actor_or_component_not_found", actor_query=actor_query, component_name=component_name)
    return _result(ok=True, status="collision_profile_set", profile_name=profile_name, changed=matches, count=len(matches))
