"""Pose Search / Motion Matching helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def _load(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Pose Search asset not found: {asset_path}")
    return asset


def _bridge(unreal):
    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if not bridge:
        raise RuntimeError("AIStudioBridgeLibrary is unavailable; install/enable AIStudioBridge and restart Unreal.")
    return bridge


def _decode(payload):
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _channel_class_path(channel_name, channel_type):
    raw = str(channel_type or channel_name or "").strip()
    if raw.startswith("/Script/"):
        return raw
    key = raw.lower().replace(" ", "").replace("_", "")
    known = {
        "position": "/Script/PoseSearch.PoseSearchFeatureChannel_Position",
        "velocity": "/Script/PoseSearch.PoseSearchFeatureChannel_Velocity",
        "trajectory": "/Script/PoseSearch.PoseSearchFeatureChannel_Trajectory",
        "phase": "/Script/PoseSearch.PoseSearchFeatureChannel_Phase",
        "heading": "/Script/PoseSearch.PoseSearchFeatureChannel_Heading",
    }
    if key not in known:
        raise ValueError(f"Unknown Pose Search channel type: {channel_type}")
    return known[key]


def inspect_database(asset_path):
    import unreal

    asset = _load(unreal, asset_path)
    fields = {}
    for name in ("schema", "animation_assets", "sample_rate", "normalization_set"):
        try:
            value = asset.get_editor_property(name)
            fields[name] = value
        except Exception:
            pass
    return _result(ok=True, asset_path=asset_path, class_name=asset.get_class().get_name(), fields=fields)


def create_pose_search_database(
    skeleton_path: str,
    animation_paths: list[str],
    asset_path: str,
    schema_path: str = "",
    sample_rate: int = 30,
) -> str:
    import unreal

    schema_path = schema_path or asset_path + "_Schema"
    if not unreal.EditorAssetLibrary.does_asset_exist(schema_path):
        schema_result = _decode(_bridge(unreal).create_pose_search_schema(skeleton_path, schema_path, int(sample_rate)))
        if not schema_result.get("ok"):
            return _result(ok=False, status="schema_creation_failed", schema=schema_result)
    database_result = _decode(_bridge(unreal).create_pose_search_database(schema_path, asset_path))
    if not database_result.get("ok"):
        return _result(ok=False, status="database_creation_failed", database=database_result)
    additions = [_decode(_bridge(unreal).add_pose_search_animation(asset_path, path)) for path in animation_paths]
    ok = all(row.get("ok") for row in additions)
    return _result(
        ok=ok,
        status="created_and_populated" if ok else "created_with_animation_failures",
        asset_path=asset_path,
        schema_path=schema_path,
        database=database_result,
        animations=additions,
    )


def add_animation(database_path: str, animation_path: str) -> str:
    import unreal

    return _bridge(unreal).add_pose_search_animation(database_path, animation_path)


def remove_animation(database_path: str, animation_path: str) -> str:
    import unreal

    return _bridge(unreal).remove_pose_search_animation(database_path, animation_path)


def set_database_property(database_path: str, property_name: str, value) -> str:
    import unreal

    database = _load(unreal, database_path)
    database.set_editor_property(str(property_name), value)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(database, False))
    readback = database.get_editor_property(str(property_name))
    return _result(
        ok=saved,
        status="property_set_and_saved" if saved else "save_failed",
        database_path=database_path,
        property_name=property_name,
        readback=readback,
    )


def create_schema(
    skeleton_path: str,
    asset_path: str,
    channels: list[dict] | None = None,
    sample_rate: int = 30,
) -> str:
    import unreal

    created = _decode(_bridge(unreal).create_pose_search_schema(skeleton_path, asset_path, int(sample_rate)))
    if not created.get("ok"):
        return _result(ok=False, status="schema_creation_failed", create=created)
    channel_results = []
    for channel in channels or []:
        channel_results.append(
            _decode(
                _bridge(unreal).add_pose_search_schema_channel(
                    asset_path,
                    _channel_class_path(channel.get("name", ""), channel.get("type", "")),
                    json.dumps(channel.get("settings") or {}),
                )
            )
        )
    ok = all(row.get("ok") for row in channel_results)
    return _result(ok=ok, status="created_and_configured" if ok else "created_with_channel_failures", create=created, channels=channel_results)


def add_schema_channel(
    schema_path: str,
    channel_name: str,
    channel_type: str,
    settings: dict | None = None,
) -> str:
    import unreal

    return _bridge(unreal).add_pose_search_schema_channel(
        schema_path,
        _channel_class_path(channel_name, channel_type),
        json.dumps(settings or {}),
    )


def add_state_animations(database_path: str, animation_paths: list[str], state_tag: str) -> str:
    import unreal

    additions = [_decode(_bridge(unreal).add_pose_search_animation(database_path, path)) for path in animation_paths]
    database = _load(unreal, database_path)
    tags = list(database.get_editor_property("tags") or [])
    tag = unreal.Name(str(state_tag))
    if tag not in tags:
        tags.append(tag)
        database.set_editor_property("tags", tags)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(database, False))
    ok = saved and all(row.get("ok") for row in additions)
    return _result(
        ok=ok,
        status="animations_added_and_tagged" if ok else "animation_or_save_failure",
        database_path=database_path,
        state_tag=state_tag,
        animation_results=additions,
        tags=[str(value) for value in database.get_editor_property("tags") or []],
    )
