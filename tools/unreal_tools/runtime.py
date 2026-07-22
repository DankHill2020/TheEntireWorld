"""PIE lifecycle, public-input injection, and runtime observation helpers."""

from __future__ import annotations

import json

from unreal_tools.assets import load_asset, load_blueprint_class


def _level_editor(unreal):
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not subsystem:
        raise RuntimeError("LevelEditorSubsystem is unavailable")
    return subsystem


def _bridge_library(unreal):
    library = getattr(unreal, "AIStudioBridgeLibrary", None)
    if not library:
        raise RuntimeError("AIStudioBridgeLibrary is unavailable; install and compile AIStudioBridge")
    return library


def _blueprint_class(unreal, asset_path):
    value = load_blueprint_class(unreal, asset_path)
    if not value:
        raise ValueError(f"Blueprint class could not be loaded: {asset_path}")
    return value


def _key(unreal, key_name):
    value = unreal.Key()
    value.set_editor_property("key_name", str(key_name or "").strip())
    if not value.export_text():
        raise ValueError(f"Unreal did not recognize input key: {key_name}")
    return value


def _json_result(value):
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise RuntimeError("AIStudioBridge returned a non-object JSON result")
    return parsed


def _find_pie_actor(unreal, actor_class):
    try:
        worlds = unreal.EditorLevelLibrary.get_pie_worlds(False) or []
    except Exception:
        worlds = []
    for world in worlds:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, actor_class) or []
        if actors:
            return actors[0]
    return None


def begin_pie(simulate=False):
    import unreal

    subsystem = _level_editor(unreal)
    before = bool(subsystem.is_in_play_in_editor())
    if not before:
        if simulate:
            subsystem.editor_play_simulate()
        else:
            subsystem.editor_request_begin_play()
    return json.dumps(
        {
            "ok": True,
            "requested": not before,
            "already_active": before,
            "simulate": bool(simulate),
            "active_immediately_after_request": bool(subsystem.is_in_play_in_editor()),
            "postconditions": {"pie_start_requested_or_already_active": True},
        },
        indent=2,
    )


def pie_status():
    import unreal

    subsystem = _level_editor(unreal)
    active = bool(subsystem.is_in_play_in_editor())
    worlds = []
    try:
        worlds = [str(world.get_path_name()) for world in unreal.EditorLevelLibrary.get_pie_worlds(False) or []]
    except Exception:
        pass
    return json.dumps(
        {
            "ok": True,
            "active": active,
            "pie_worlds": worlds,
            "postconditions": {"pie_state_observed": True},
        },
        indent=2,
    )


def end_pie():
    import unreal

    subsystem = _level_editor(unreal)
    before = bool(subsystem.is_in_play_in_editor())
    if before:
        subsystem.editor_request_end_play()
    return json.dumps(
        {
            "ok": True,
            "requested": before,
            "was_active": before,
            "postconditions": {"pie_end_requested_or_already_stopped": True},
        },
        indent=2,
    )


def inject_key(key_name, pressed=True):
    import unreal

    library = _bridge_library(unreal)
    if not hasattr(library, "inject_key_in_pie"):
        raise RuntimeError("Installed AIStudioBridge does not expose inject_key_in_pie")
    result = _json_result(library.inject_key_in_pie(_key(unreal, key_name), bool(pressed)))
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "PIE key injection failed"))
    return json.dumps(result, indent=2)


def inspect_character(
    character_blueprint_path,
    expected_anim_class_contains="",
    property_names=None,
):
    import unreal

    library = _bridge_library(unreal)
    character_class = _blueprint_class(unreal, character_blueprint_path)
    result = _json_result(
        library.inspect_character_in_pie(
            character_class,
            str(expected_anim_class_contains or ""),
            [str(value) for value in property_names or []],
        )
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "PIE character inspection failed"))
    actor = _find_pie_actor(unreal, character_class)
    montage = actor.get_current_montage() if actor else None
    result["active_montage"] = montage.get_path_name() if montage else ""
    result["runtime_actor_resolved"] = bool(actor)
    return json.dumps(result, indent=2)


def validate_character_montages(
    character_blueprint_path,
    montage_paths,
    expected_anim_class_contains="",
):
    import unreal

    library = _bridge_library(unreal)
    montages = []
    for path in montage_paths or []:
        asset = load_asset(unreal, path)
        if not asset:
            raise ValueError(f"Montage could not be loaded: {path}")
        montages.append(asset)
    result = _json_result(
        library.validate_character_montages_in_pie(
            _blueprint_class(unreal, character_blueprint_path),
            montages,
            str(expected_anim_class_contains or ""),
        )
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "PIE montage validation failed"))
    return json.dumps(result, indent=2)


def pie_validate(target_assets=None, expected=None, start_pie=False):
    """Evaluate structured PIE preconditions without treating compile success as gameplay proof."""
    import unreal

    expected = dict(expected or {})
    target_assets = [str(value) for value in target_assets or []]
    subsystem = _level_editor(unreal)
    was_active = bool(subsystem.is_in_play_in_editor())
    if start_pie and not was_active:
        subsystem.editor_request_begin_play()
    active = bool(subsystem.is_in_play_in_editor())
    assets = {
        path: bool(unreal.EditorAssetLibrary.does_asset_exist(path))
        for path in target_assets
    }
    assertions = {
        "pie_active": active,
        "target_assets_exist": bool(assets) and all(assets.values()),
    }
    evidence = {"assets": assets, "expected": expected}

    character_path = str(expected.get("character_blueprint_path") or "")
    if character_path and active:
        character = json.loads(
            inspect_character(
                character_path,
                str(expected.get("anim_class_contains") or ""),
                list((expected.get("properties") or {}).keys()),
            )
        )
        evidence["character"] = character
        assertions["runtime_character_resolved"] = bool(character.get("runtime_actor_resolved"))
        if expected.get("anim_class_contains"):
            assertions["anim_class_matches"] = bool(character.get("anim_class_matches"))
        observed_properties = dict(character.get("properties") or {})
        for name, required_value in dict(expected.get("properties") or {}).items():
            assertions[f"property:{name}"] = observed_properties.get(name) == required_value
    elif character_path:
        assertions["runtime_character_resolved"] = False

    if expected.get("active_montage"):
        observed = str((evidence.get("character") or {}).get("active_montage") or "")
        assertions["active_montage_matches"] = observed == str(expected["active_montage"])

    ok = bool(assertions) and all(assertions.values())
    return json.dumps(
        {
            "ok": ok,
            "operation": "runtime.pie_validate",
            "requested_pie_start": bool(start_pie and not was_active),
            "assertions": assertions,
            "evidence": evidence,
            "errors": [] if ok else [key for key, passed in assertions.items() if not passed],
        },
        indent=2,
    )
