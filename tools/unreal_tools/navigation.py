"""Editor navigation helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def open_content_browser(folder_path="/Game/", new_browser=False):
    import unreal

    try:
        unreal.EditorAssetLibrary.sync_browser_to_objects([str(folder_path)])
        return _result(ok=True, folder_path=folder_path, new_browser=bool(new_browser))
    except Exception as exc:
        return _result(ok=False, error=str(exc), folder_path=folder_path)


def open_asset(asset_path):
    import unreal

    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        return _result(ok=False, error="asset_not_found", asset_path=asset_path)
    subsystem = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
    opened = bool(subsystem.open_editor_for_assets([asset])) if subsystem else False
    return _result(ok=opened, asset_path=asset_path, opened=opened)


def open_window(window_name):
    import unreal

    subsystem = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
    if subsystem and hasattr(subsystem, "spawn_and_register_tab"):
        return _result(ok=False, status="requires_editor_utility_widget", window_name=window_name)
    return _result(ok=False, status="api_unavailable", window_name=window_name)


def load_level(level_path):
    import unreal

    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not subsystem:
        return _result(ok=False, status="api_unavailable", api="LevelEditorSubsystem")
    loaded = bool(subsystem.load_level(str(level_path)))
    return _result(ok=loaded, level_path=level_path, loaded=loaded)


def add_nav_mesh_bounds(location=None, extent=None, save=True):
    import unreal

    location = location or [0.0, 0.0, 0.0]
    extent = extent or [1000.0, 1000.0, 500.0]
    cls = getattr(unreal, "NavMeshBoundsVolume", None)
    if not cls:
        return _result(ok=False, status="api_unavailable", api="NavMeshBoundsVolume")
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        cls,
        unreal.Vector(float(location[0]), float(location[1]), float(location[2])),
    )
    if not actor:
        return _result(ok=False, error="spawn_failed")
    try:
        actor.set_actor_scale3d(unreal.Vector(float(extent[0]) / 100.0, float(extent[1]) / 100.0, float(extent[2]) / 100.0))
    except Exception:
        pass
    if save:
        unreal.EditorLevelLibrary.save_current_level()
    return _result(ok=True, actor_path=actor.get_path_name(), location=location, extent=extent, saved=bool(save))
