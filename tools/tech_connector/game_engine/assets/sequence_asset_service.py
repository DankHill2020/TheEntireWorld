"""First-class cinematic sequence authoring, evaluation, interchange, and cooking."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
import uuid

from .asset_database_service import AssetDatabase, AssetRecord
from .asset_operations_service import AssetOperationsService


SEQUENCE_SCHEMA = "tech_connector.level_sequence.v1"
SEQUENCE_RUNTIME_SCHEMA = "tech_connector.level_sequence.runtime.v1"
TRACK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "camera_cut": {"label": "Camera Cut", "category": "Cameras", "asset_types": (), "binding": False},
    "camera": {"label": "Camera", "category": "Cameras", "asset_types": (), "binding": True},
    "animation": {"label": "Animation", "category": "Character", "asset_types": ("tc.animation_clip",), "binding": True},
    "control_rig": {"label": "Control Rig", "category": "Character", "asset_types": ("tc.control_rig",), "binding": True},
    "transform": {"label": "Transform", "category": "Transforms", "asset_types": (), "binding": True},
    "translation": {"label": "Translation", "category": "Transforms", "asset_types": (), "binding": True},
    "rotation": {"label": "Rotation", "category": "Transforms", "asset_types": (), "binding": True},
    "scale": {"label": "Scale", "category": "Transforms", "asset_types": (), "binding": True},
    "bone_transform": {"label": "Bone Transform", "category": "Character", "asset_types": (), "binding": True},
    "attachment": {"label": "Attach", "category": "Constraints", "asset_types": (), "binding": True},
    "constraint": {"label": "Constraint", "category": "Constraints", "asset_types": ("tc.physics_constraint",), "binding": True},
    "audio": {"label": "Audio", "category": "Media", "asset_types": ("tc.audio_clip", "tc.sound_cue"), "binding": False},
    "media": {"label": "Media", "category": "Media", "asset_types": ("tc.video", "tc.media_source"), "binding": False},
    "event": {"label": "Event", "category": "Gameplay", "asset_types": (), "binding": False},
    "property": {"label": "Property", "category": "Properties", "asset_types": (), "binding": True},
    "component_property": {"label": "Component Property", "category": "Properties", "asset_types": (), "binding": True},
    "visibility": {"label": "Visibility", "category": "Properties", "asset_types": (), "binding": True},
    "material": {"label": "Material Parameter", "category": "Rendering", "asset_types": ("tc.material", "tc.material_instance"), "binding": True},
    "effect": {"label": "Effect", "category": "FX", "asset_types": ("tc.effect_system",), "binding": True},
    "geometry_cache": {"label": "Geometry Cache", "category": "Geometry", "asset_types": ("tc.geometry_cache",), "binding": True},
    "spawn": {"label": "Spawn", "category": "Gameplay", "asset_types": ("tc.prefab",), "binding": False},
    "sub_sequence": {"label": "Sub-Sequence", "category": "Cinematics", "asset_types": ("tc.level_sequence",), "binding": False},
    "fade": {"label": "Fade", "category": "Cinematics", "asset_types": (), "binding": False},
    "level_visibility": {"label": "Level Visibility", "category": "World", "asset_types": ("tc.level",), "binding": False},
    "level_blend": {"label": "Level Blend", "category": "World", "asset_types": ("tc.level",), "binding": False},
    "time_dilation": {"label": "Time Dilation", "category": "Cinematics", "asset_types": (), "binding": False},
}
TRACK_TYPES = tuple(TRACK_DEFINITIONS)
RENDER_FORMATS = ("png", "exr", "jpg", "mp4", "prores")


@dataclass(frozen=True)
class SequenceIssue:
    severity: str
    code: str
    message: str
    path: str = ""


def sequence_defaults(*, duration_frames: int = 300, fps: int = 30) -> dict[str, Any]:
    end = max(1, int(duration_frames))
    rate = max(1, int(fps))
    return {
        "sequence_version": 1,
        "display_rate": {"numerator": rate, "denominator": 1},
        "tick_resolution": 24_000,
        "playback_range": {"start": 0, "end": end},
        "view_range": {"start": 0, "end": end},
        "working_range": {"start": 0, "end": end},
        "evaluation": "frame_locked",
        "playback_mode": "loop",
        "bindings": [],
        "tracks": [],
        "folders": [],
        "markers": [],
        "render_settings": {
            "resolution": [1920, 1080], "format": "png", "output_directory": "Renders",
            "use_camera_cuts": True, "frame_handles": 0, "temporal_samples": 1,
            "spatial_samples": 1, "motion_blur": True, "include_audio": True,
            "burn_in": False, "overwrite_existing": False,
        },
        "source_extensions": [],
    }


def new_binding(
    name: str, *, object_id: str = "", binding_type: str = "possessable",
    parent_binding_id: str = "", component_path: str = "", bone_name: str = "",
    socket_name: str = "", skeleton_asset_id: str = "",
) -> dict[str, Any]:
    return {
        "id": f"binding_{uuid.uuid4().hex[:12]}", "name": str(name or "Binding"),
        "type": str(binding_type or "possessable"), "object_id": str(object_id), "tags": [],
        "parent_binding_id": str(parent_binding_id), "component_path": str(component_path),
        "bone_name": str(bone_name), "socket_name": str(socket_name),
        "skeleton_asset_id": str(skeleton_asset_id),
    }


def new_track(
    track_type: str, name: str = "", *, binding_id: str = "", parent_id: str = "",
) -> dict[str, Any]:
    kind = str(track_type).strip().casefold()
    if kind not in TRACK_TYPES:
        raise ValueError(f"Unsupported sequence track type: {track_type}")
    label = str(name or kind.replace("_", " ").title())
    return {
        "id": f"track_{uuid.uuid4().hex[:12]}", "name": label, "type": kind,
        "binding_id": str(binding_id), "parent_id": str(parent_id),
        "target_path": "", "evaluation_priority": 0,
        "muted": False, "locked": False, "solo": False, "sections": [],
    }


def new_section(
    name: str, start_frame: int, end_frame: int, *, asset_id: str = "", row: int = 0,
) -> dict[str, Any]:
    start, end = int(start_frame), int(end_frame)
    if end <= start:
        raise ValueError("Sequence section end must be after its start.")
    return {
        "id": f"section_{uuid.uuid4().hex[:12]}", "name": str(name or "Section"),
        "start_frame": start, "end_frame": end, "row": max(0, int(row)),
        "asset_id": str(asset_id), "source_offset": 0.0, "time_scale": 1.0,
        "blend_type": "absolute", "ease_in": 0, "ease_out": 0, "pre_roll": 0,
        "post_roll": 0, "completion_mode": "restore_state", "channels": [],
    }


def new_level_blend_section(
    name: str, level_asset_id: str, start_frame: int, end_frame: int, *,
    ease_in: int = 30, ease_out: int = 30, blend_mode: str = "crossfade",
) -> dict[str, Any]:
    section = new_section(name, start_frame, end_frame, asset_id=level_asset_id)
    section.update({
        "blend_type": str(blend_mode), "ease_in": max(0, int(ease_in)),
        "ease_out": max(0, int(ease_out)), "pre_roll": max(1, int(ease_in)),
        "level_transition": {
            "streaming": "async", "world_partition": True, "data_layers": [],
            "blend_lighting": True, "blend_post_process": True, "blend_audio": True,
            "blend_gameplay": False, "preserve_player_state": True,
            "preserve_persistent_actors": True, "unload_when_inactive": True,
        },
    })
    return section


def track_preset(track_type: str, name: str = "", *, binding_id: str = "") -> dict[str, Any]:
    """Create a ready-to-key track with familiar default channels."""
    track = new_track(track_type, name, binding_id=binding_id)
    channel_names: tuple[str, ...] = ()
    kind = track["type"]
    if kind == "translation": channel_names = ("translation.x", "translation.y", "translation.z")
    elif kind == "rotation": channel_names = ("rotation.x", "rotation.y", "rotation.z")
    elif kind == "scale": channel_names = ("scale.x", "scale.y", "scale.z")
    elif kind in {"transform", "bone_transform"}: channel_names = (
        "translation.x", "translation.y", "translation.z", "rotation.x", "rotation.y",
        "rotation.z", "scale.x", "scale.y", "scale.z",
    )
    elif kind == "camera": channel_names = ("focal_length", "aperture", "focus_distance")
    elif kind in {"visibility", "fade", "time_dilation", "property", "component_property", "material"}: channel_names = ("value",)
    track["default_channels"] = [{"id": value, "name": value, "value_type": "float", "keys": []} for value in channel_names]
    return track


def add_channel_key(
    section: dict[str, Any], channel_name: str, frame: float, value: Any,
    *, interpolation: str = "linear", in_tangent: float = 0.0, out_tangent: float = 0.0,
) -> dict[str, Any]:
    channels = section.setdefault("channels", [])
    channel = next((item for item in channels if item.get("id") == channel_name or item.get("name") == channel_name), None)
    if channel is None:
        channel = {"id": str(channel_name), "name": str(channel_name), "value_type": _value_type(value), "keys": []}
        channels.append(channel)
    key = {"frame": float(frame), "value": deepcopy(value), "interpolation": str(interpolation),
           "in_tangent": float(in_tangent), "out_tangent": float(out_tangent)}
    channel.setdefault("keys", []).append(key)
    channel["keys"].sort(key=lambda item: float(item.get("frame") or 0.0))
    return key


def validate_sequence(values: Mapping[str, Any] | None) -> tuple[SequenceIssue, ...]:
    data = dict(values or {})
    issues: list[SequenceIssue] = []
    rate = dict(data.get("display_rate") or {})
    if int(rate.get("numerator") or 0) <= 0 or int(rate.get("denominator") or 0) <= 0:
        issues.append(SequenceIssue("error", "invalid_display_rate", "Display rate must be positive.", "display_rate"))
    playback = dict(data.get("playback_range") or {})
    start, end = int(playback.get("start") or 0), int(playback.get("end") or 0)
    if end <= start:
        issues.append(SequenceIssue("error", "invalid_playback_range", "Playback end must be after its start.", "playback_range"))
    bindings = [dict(item) for item in data.get("bindings") or () if isinstance(item, Mapping)]
    binding_ids = {str(item.get("id") or "") for item in bindings}
    if "" in binding_ids or len(binding_ids) != len(bindings):
        issues.append(SequenceIssue("error", "invalid_bindings", "Binding IDs must be present and unique.", "bindings"))
    for binding_index, binding in enumerate(bindings):
        path = f"bindings[{binding_index}]"
        parent_id = str(binding.get("parent_binding_id") or "")
        if parent_id and parent_id not in binding_ids:
            issues.append(SequenceIssue("error", "missing_parent_binding", f"Binding references missing parent '{parent_id}'.", path))
        if parent_id == str(binding.get("id") or ""):
            issues.append(SequenceIssue("error", "recursive_binding", "A binding cannot parent itself.", path))
        if (binding.get("bone_name") or binding.get("socket_name")) and not (binding.get("skeleton_asset_id") or parent_id or binding.get("object_id")):
            issues.append(SequenceIssue("error", "unresolved_skeletal_attachment", "Bone or socket bindings require a skeleton, parent binding, or bound object.", path))
        if binding.get("component_path") and not (parent_id or binding.get("object_id")):
            issues.append(SequenceIssue("error", "unresolved_component", "Component bindings require a parent binding or bound object.", path))
    tracks = [dict(item) for item in data.get("tracks") or () if isinstance(item, Mapping)]
    track_ids = {str(item.get("id") or "") for item in tracks}
    if "" in track_ids or len(track_ids) != len(tracks):
        issues.append(SequenceIssue("error", "invalid_tracks", "Track IDs must be present and unique.", "tracks"))
    section_ids: set[str] = set()
    for track_index, track in enumerate(tracks):
        path = f"tracks[{track_index}]"
        kind = str(track.get("type") or "").casefold()
        if kind not in TRACK_TYPES:
            issues.append(SequenceIssue("error", "unknown_track_type", f"Unknown track type '{kind}'.", path))
        binding_id = str(track.get("binding_id") or "")
        if binding_id and binding_id not in binding_ids:
            issues.append(SequenceIssue("error", "missing_binding", f"Track references missing binding '{binding_id}'.", path))
        definition = TRACK_DEFINITIONS.get(kind, {})
        if definition.get("binding") and not binding_id:
            issues.append(SequenceIssue("warning", "unbound_track", f"{definition.get('label', kind)} track is not bound to an object, component, or bone.", path))
        parent_id = str(track.get("parent_id") or "")
        if parent_id and parent_id not in track_ids:
            issues.append(SequenceIssue("error", "missing_parent_track", f"Track references missing parent '{parent_id}'.", path))
        rows: dict[int, list[tuple[int, int, str]]] = {}
        for section_index, raw_section in enumerate(track.get("sections") or ()):
            section = dict(raw_section) if isinstance(raw_section, Mapping) else {}
            section_path = f"{path}.sections[{section_index}]"
            section_id = str(section.get("id") or "")
            if not section_id or section_id in section_ids:
                issues.append(SequenceIssue("error", "invalid_section_id", "Section IDs must be present and unique.", section_path))
            section_ids.add(section_id)
            section_start = int(section.get("start_frame") or 0)
            section_end = int(section.get("end_frame") or 0)
            if section_end <= section_start:
                issues.append(SequenceIssue("error", "invalid_section_range", "Section end must be after its start.", section_path))
            if float(section.get("time_scale", 1.0)) <= 0.0:
                issues.append(SequenceIssue("error", "invalid_time_scale", "Section time scale must be positive.", section_path))
            asset_types = tuple(definition.get("asset_types") or ())
            if asset_types and kind in {"animation", "control_rig", "audio", "media", "effect", "geometry_cache", "spawn", "sub_sequence", "level_visibility", "level_blend"} and not section.get("asset_id"):
                issues.append(SequenceIssue("warning", "missing_section_asset", f"{definition.get('label', kind)} section has no assigned asset.", section_path))
            if kind == "level_blend":
                transition = dict(section.get("level_transition") or {})
                if str(section.get("blend_type") or "crossfade") not in {"crossfade", "additive", "replace", "portal", "match_cut"}:
                    issues.append(SequenceIssue("error", "invalid_level_blend_mode", "Level blend mode must be crossfade, additive, replace, portal, or match_cut.", section_path))
                if str(transition.get("streaming") or "async") not in {"async", "blocking", "preloaded"}:
                    issues.append(SequenceIssue("error", "invalid_level_streaming_mode", "Level streaming must be async, blocking, or preloaded.", section_path))
            for channel_index, raw_channel in enumerate(section.get("channels") or ()):
                channel = dict(raw_channel) if isinstance(raw_channel, Mapping) else {}
                channel_path = f"{section_path}.channels[{channel_index}]"
                frames: list[float] = []
                for key in channel.get("keys") or ():
                    try: frames.append(float(dict(key).get("frame")))
                    except (TypeError, ValueError): issues.append(SequenceIssue("error", "invalid_key_frame", "Channel key frame must be numeric.", channel_path))
                if len(frames) != len(set(frames)):
                    issues.append(SequenceIssue("error", "duplicate_channel_keys", "A channel cannot contain multiple keys at the same frame.", channel_path))
            row = max(0, int(section.get("row") or 0))
            for other_start, other_end, other_name in rows.setdefault(row, []):
                if section_start < other_end and other_start < section_end and kind in {"camera_cut", "sub_sequence"}:
                    issues.append(SequenceIssue("warning", "overlapping_sections", f"'{section.get('name')}' overlaps '{other_name}' on row {row}.", section_path))
            rows[row].append((section_start, section_end, str(section.get("name") or section_id)))
    render = dict(data.get("render_settings") or {})
    resolution = list(render.get("resolution") or ())
    if len(resolution) != 2 or any(int(value) <= 0 for value in resolution):
        issues.append(SequenceIssue("error", "invalid_render_resolution", "Render resolution must contain two positive dimensions.", "render_settings.resolution"))
    if str(render.get("format") or "png").casefold() not in RENDER_FORMATS:
        issues.append(SequenceIssue("error", "invalid_render_format", f"Unsupported render format '{render.get('format')}'.", "render_settings.format"))
    if int(render.get("temporal_samples") or 1) < 1 or int(render.get("spatial_samples") or 1) < 1:
        issues.append(SequenceIssue("error", "invalid_render_samples", "Render sample counts must be at least one.", "render_settings"))
    return tuple(issues)


def evaluate_sequence(values: Mapping[str, Any], frame: int) -> dict[str, Any]:
    target = int(frame)
    bindings = {str(item.get("id") or ""): dict(item) for item in values.get("bindings") or () if isinstance(item, Mapping)}
    tracks = [dict(item) for item in values.get("tracks") or () if isinstance(item, Mapping)]
    solo = any(bool(track.get("solo")) for track in tracks)
    active: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    camera_cut: dict[str, Any] | None = None
    for track in tracks:
        if bool(track.get("muted")) or (solo and not bool(track.get("solo"))):
            continue
        for raw in track.get("sections") or ():
            section = dict(raw) if isinstance(raw, Mapping) else {}
            start, end = int(section.get("start_frame") or 0), int(section.get("end_frame") or 0)
            if start <= target < end:
                channels = {str(channel.get("name") or channel.get("id") or "value"): evaluate_channel(channel, target) for channel in section.get("channels") or () if isinstance(channel, Mapping)}
                result = {"track_id": track.get("id"), "track_type": track.get("type"),
                          "binding": deepcopy(bindings.get(str(track.get("binding_id") or ""))),
                          "evaluated_channels": channels, **section}
                active.append(result)
                if track.get("type") == "camera_cut":
                    camera_cut = result
            for channel in section.get("channels") or ():
                channel_data = dict(channel) if isinstance(channel, Mapping) else {}
                for key in channel_data.get("keys") or ():
                    key_data = dict(key) if isinstance(key, Mapping) else {}
                    if track.get("type") == "event" and int(key_data.get("frame") or 0) == target:
                        events.append({"track_id": track.get("id"), **key_data})
    level_blends = []
    for section in active:
        if section.get("track_type") != "level_blend": continue
        start, end = int(section.get("start_frame") or 0), int(section.get("end_frame") or 0)
        ease_in, ease_out = max(0, int(section.get("ease_in") or 0)), max(0, int(section.get("ease_out") or 0))
        weight = 1.0
        if ease_in and target < start + ease_in: weight = min(weight, max(0.0, (target - start) / ease_in))
        if ease_out and target >= end - ease_out: weight = min(weight, max(0.0, (end - target) / ease_out))
        level_blends.append({"level_asset_id": str(section.get("asset_id") or ""), "weight": weight,
                             "blend_mode": str(section.get("blend_type") or "crossfade"),
                             "transition": deepcopy(dict(section.get("level_transition") or {})),
                             "section_id": str(section.get("id") or "")})
    return {"frame": target, "active_sections": active, "camera_cut": camera_cut, "events": events, "level_blends": level_blends}


def evaluate_channel(channel: Mapping[str, Any], frame: float) -> Any:
    keys = sorted((dict(item) for item in channel.get("keys") or () if isinstance(item, Mapping)), key=lambda item: float(item.get("frame") or 0.0))
    if not keys: return None
    target = float(frame)
    if target <= float(keys[0].get("frame") or 0.0): return deepcopy(keys[0].get("value"))
    if target >= float(keys[-1].get("frame") or 0.0): return deepcopy(keys[-1].get("value"))
    for first, second in zip(keys, keys[1:]):
        start, end = float(first.get("frame") or 0.0), float(second.get("frame") or 0.0)
        if start <= target <= end:
            if str(first.get("interpolation") or "linear").casefold() in {"constant", "step"}: return deepcopy(first.get("value"))
            a, b = first.get("value"), second.get("value")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                alpha = (target - start) / max(1.0e-9, end - start)
                return float(a) + (float(b) - float(a)) * alpha
            return deepcopy(first.get("value"))
    return deepcopy(keys[-1].get("value"))


def compile_sequence_payload(values: Mapping[str, Any], *, platform: str = "windows", quality: str = "high") -> bytes:
    issues = validate_sequence(values)
    errors = [issue.message for issue in issues if issue.severity == "error"]
    if errors:
        raise ValueError("; ".join(errors))
    payload = {
        "schema": SEQUENCE_RUNTIME_SCHEMA, "platform": str(platform), "quality": str(quality),
        "sequence": deepcopy(dict(values)),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_render_jobs(values: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Build deterministic camera-cut render jobs or one full-range fallback job."""
    playback = dict(values.get("playback_range") or {})
    settings = deepcopy(dict(values.get("render_settings") or {}))
    handles = max(0, int(settings.get("frame_handles") or 0))
    cuts = []
    for track in values.get("tracks") or ():
        if isinstance(track, Mapping) and track.get("type") == "camera_cut" and not track.get("muted"):
            cuts.extend(dict(section) for section in track.get("sections") or () if isinstance(section, Mapping))
    ranges = cuts if settings.get("use_camera_cuts", True) and cuts else [{
        "id": "full_sequence", "name": "Full Sequence", "start_frame": int(playback.get("start") or 0),
        "end_frame": int(playback.get("end") or 0), "asset_id": "",
    }]
    jobs = []
    for index, section in enumerate(sorted(ranges, key=lambda item: int(item.get("start_frame") or 0))):
        start = int(section.get("start_frame") or 0)
        end = int(section.get("end_frame") or 0)
        jobs.append({
            "id": f"render_{index + 1:03d}_{section.get('id') or 'range'}",
            "name": str(section.get("name") or f"Shot {index + 1:03d}"),
            "start_frame": start - handles, "end_frame": end + handles,
            "camera_binding_id": str(section.get("asset_id") or ""), "settings": deepcopy(settings),
        })
    return tuple(jobs)


def unreal_level_sequence_to_native(source: Mapping[str, Any]) -> dict[str, Any]:
    result = sequence_defaults(duration_frames=int(source.get("playback_end") or 300), fps=int(source.get("display_rate") or 30))
    result["playback_range"]["start"] = int(source.get("playback_start") or 0)
    result["bindings"] = [new_binding(str(item.get("name") or "Binding"), object_id=str(item.get("object_path") or "")) for item in source.get("bindings") or ()]
    result["tracks"] = []
    for raw in source.get("tracks") or ():
        item = deepcopy(dict(raw)); item["type"] = _canonical_track_type(str(item.get("type") or item.get("class") or "property"))
        item.setdefault("id", f"track_{uuid.uuid4().hex[:12]}"); item.setdefault("name", TRACK_DEFINITIONS[item["type"]]["label"]); item.setdefault("sections", [])
        result["tracks"].append(item)
    result["source_extensions"] = [{"engine": "unreal", "payload": deepcopy(dict(source))}]
    return result


def unity_timeline_to_native(source: Mapping[str, Any]) -> dict[str, Any]:
    fps = int(source.get("frame_rate") or 30)
    duration = max(1, round(float(source.get("duration") or 10.0) * fps))
    result = sequence_defaults(duration_frames=duration, fps=fps)
    for raw in source.get("tracks") or ():
        item = dict(raw)
        type_name = str(item.get("type") or "").casefold()
        kind = _canonical_track_type(type_name)
        track = new_track(kind, str(item.get("name") or "Track"))
        for clip in item.get("clips") or ():
            clip_data = dict(clip)
            start = round(float(clip_data.get("start") or 0.0) * fps)
            end = round((float(clip_data.get("start") or 0.0) + float(clip_data.get("duration") or 0.0)) * fps)
            track["sections"].append(new_section(str(clip_data.get("name") or "Clip"), start, max(start + 1, end), asset_id=str(clip_data.get("asset_id") or "")))
        result["tracks"].append(track)
    result["source_extensions"] = [{"engine": "unity", "payload": deepcopy(dict(source))}]
    return result


def native_to_unreal_level_sequence(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return an Unreal-oriented lossless interchange document."""
    playback = dict(values.get("playback_range") or {})
    rate = dict(values.get("display_rate") or {})
    return {
        "schema": "tech_connector.interchange.unreal_level_sequence.v1",
        "display_rate": int(rate.get("numerator") or 30) / max(1, int(rate.get("denominator") or 1)),
        "tick_resolution": int(values.get("tick_resolution") or 24_000),
        "playback_start": int(playback.get("start") or 0),
        "playback_end": int(playback.get("end") or 0),
        "bindings": deepcopy(list(values.get("bindings") or ())),
        "tracks": deepcopy(list(values.get("tracks") or ())),
        "markers": deepcopy(list(values.get("markers") or ())),
        "source_extensions": deepcopy(list(values.get("source_extensions") or ())),
    }


def native_to_unity_timeline(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a Unity Timeline-oriented interchange document."""
    playback = dict(values.get("playback_range") or {})
    rate = dict(values.get("display_rate") or {})
    fps = int(rate.get("numerator") or 30) / max(1, int(rate.get("denominator") or 1))
    track_types = {"animation": "AnimationTrack", "audio": "AudioTrack", "event": "SignalTrack", "sub_sequence": "ControlTrack"}
    tracks = []
    for raw in values.get("tracks") or ():
        track = dict(raw)
        clips = []
        for raw_section in track.get("sections") or ():
            section = dict(raw_section)
            start = int(section.get("start_frame") or 0)
            end = int(section.get("end_frame") or start + 1)
            clips.append({
                "name": str(section.get("name") or "Clip"), "start": start / fps,
                "duration": max(1, end - start) / fps, "asset_id": str(section.get("asset_id") or ""),
                "source_offset": float(section.get("source_offset") or 0.0),
                "time_scale": float(section.get("time_scale") or 1.0),
            })
        tracks.append({
            "id": str(track.get("id") or ""), "name": str(track.get("name") or "Track"),
            "type": track_types.get(str(track.get("type") or ""), "PlayableTrack"),
            "binding_id": str(track.get("binding_id") or ""), "clips": clips,
            "native_track_type": str(track.get("type") or ""),
        })
    return {
        "schema": "tech_connector.interchange.unity_timeline.v1", "frame_rate": fps,
        "duration": max(0, int(playback.get("end") or 0) - int(playback.get("start") or 0)) / fps,
        "tracks": tracks, "bindings": deepcopy(list(values.get("bindings") or ())),
        "markers": deepcopy(list(values.get("markers") or ())),
        "source_extensions": deepcopy(list(values.get("source_extensions") or ())),
    }


class SequenceAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(self, name: str, *, folder: str | Path = "Assets/Cinematics", duration_frames: int = 300, fps: int = 30):
        return self.operations.create_asset("tc.level_sequence", name, folder=folder, properties=sequence_defaults(duration_frames=duration_frames, fps=fps))

    def properties(self, asset_id: str) -> dict[str, Any]:
        record = self._require(asset_id)
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        return deepcopy(dict(payload.get("properties") or {}))

    def update(self, asset_id: str, values: Mapping[str, Any]) -> AssetRecord:
        record = self._require(asset_id)
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        payload["properties"] = deepcopy(dict(values))
        record.source_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        dependencies = [(value, "sequence_reference") for value in _asset_references(values)]
        return self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata, dependencies=dependencies)

    def validate(self, asset_id: str) -> tuple[SequenceIssue, ...]:
        values = self.properties(asset_id); issues = list(validate_sequence(values))
        for binding_index, binding in enumerate(values.get("bindings") or ()):
            skeleton_id = str(binding.get("skeleton_asset_id") or "")
            if skeleton_id:
                record = self.database.asset(skeleton_id)
                if record is None: issues.append(SequenceIssue("error", "missing_skeleton_asset", f"Skeleton binding references unavailable asset '{skeleton_id}'.", f"bindings[{binding_index}]"))
                elif record.asset_type != "tc.skeleton": issues.append(SequenceIssue("error", "wrong_skeleton_asset_type", f"Bone binding requires tc.skeleton, not {record.asset_type}.", f"bindings[{binding_index}]"))
        for track_index, track in enumerate(values.get("tracks") or ()):
            allowed = tuple(TRACK_DEFINITIONS.get(str(track.get("type") or ""), {}).get("asset_types") or ())
            for section_index, section in enumerate(track.get("sections") or ()):
                reference = str(section.get("asset_id") or "")
                if not reference: continue
                path = f"tracks[{track_index}].sections[{section_index}]"
                if reference == asset_id and track.get("type") == "sub_sequence":
                    issues.append(SequenceIssue("error", "recursive_sub_sequence", "A sequence cannot contain itself as a sub-sequence.", path)); continue
                record = self.database.asset(reference)
                if record is None: issues.append(SequenceIssue("error", "missing_section_asset", f"Section references unavailable asset '{reference}'.", path))
                elif allowed and record.asset_type not in allowed: issues.append(SequenceIssue("error", "incompatible_section_asset", f"{track.get('type')} track expects {', '.join(allowed)}, not {record.asset_type}.", path))
        return tuple(issues)

    def add_binding(self, asset_id: str, name: str, **target: Any) -> dict[str, Any]:
        values = self.properties(asset_id); binding = new_binding(name, **target)
        values.setdefault("bindings", []).append(binding); self.update(asset_id, values); return deepcopy(binding)

    def add_track(
        self, asset_id: str, track_type: str, name: str = "", *, binding_id: str = "", parent_id: str = "",
    ) -> dict[str, Any]:
        values = self.properties(asset_id); track = track_preset(track_type, name, binding_id=binding_id); track["parent_id"] = str(parent_id)
        values.setdefault("tracks", []).append(track); self.update(asset_id, values); return deepcopy(track)

    def add_section(
        self, asset_id: str, track_id: str, name: str, start_frame: int, end_frame: int,
        *, referenced_asset_id: str = "", row: int = 0,
    ) -> dict[str, Any]:
        values = self.properties(asset_id); track = _find_track(values, track_id)
        section = (new_level_blend_section(name, referenced_asset_id, start_frame, end_frame)
                   if track.get("type") == "level_blend" else
                   new_section(name, start_frame, end_frame, asset_id=referenced_asset_id, row=row))
        section["channels"] = deepcopy(list(track.get("default_channels") or ()))
        track.setdefault("sections", []).append(section); self.update(asset_id, values); return deepcopy(section)

    def add_key(
        self, asset_id: str, track_id: str, section_id: str, channel_name: str,
        frame: float, value: Any, *, interpolation: str = "linear",
    ) -> dict[str, Any]:
        values = self.properties(asset_id); track = _find_track(values, track_id)
        section = next((item for item in track.get("sections") or () if str(item.get("id") or "") == str(section_id)), None)
        if section is None: raise KeyError(f"Sequence section is unavailable: {section_id}")
        key = add_channel_key(section, channel_name, frame, value, interpolation=interpolation)
        self.update(asset_id, values); return deepcopy(key)

    def remove_track(self, asset_id: str, track_id: str) -> bool:
        values = self.properties(asset_id); before = len(values.get("tracks") or ())
        values["tracks"] = [item for item in values.get("tracks") or () if str(item.get("id") or "") != str(track_id)]
        if len(values["tracks"]) == before: return False
        self.update(asset_id, values); return True

    def remove_section(self, asset_id: str, track_id: str, section_id: str) -> bool:
        values = self.properties(asset_id); track = _find_track(values, track_id); before = len(track.get("sections") or ())
        track["sections"] = [item for item in track.get("sections") or () if str(item.get("id") or "") != str(section_id)]
        if len(track["sections"]) == before: return False
        self.update(asset_id, values); return True

    def cook(self, asset_id: str, *, platform: str = "windows", quality: str = "high"):
        errors = [issue.message for issue in self.validate(asset_id) if issue.severity == "error"]
        if errors: raise ValueError("; ".join(errors))
        payload = compile_sequence_payload(self.properties(asset_id), platform=platform, quality=quality)
        return self.database.store_derived(asset_id, f"level_sequence_runtime:{platform}:{quality}", payload, metadata={"platform": platform, "quality": quality}, extension=".tcseqbin")

    def _require(self, asset_id: str) -> AssetRecord:
        record = self.database.asset(str(asset_id))
        if record is None or record.asset_type != "tc.level_sequence":
            raise KeyError(f"Level Sequence asset is unavailable: {asset_id}")
        return record


def _asset_references(values: Mapping[str, Any]) -> tuple[str, ...]:
    references: set[str] = set()
    for binding in values.get("bindings") or ():
        if isinstance(binding, Mapping) and binding.get("skeleton_asset_id"):
            references.add(str(binding["skeleton_asset_id"]))
    for track in values.get("tracks") or ():
        if not isinstance(track, Mapping):
            continue
        for section in track.get("sections") or ():
            if isinstance(section, Mapping) and section.get("asset_id"):
                references.add(str(section["asset_id"]))
    return tuple(sorted(references))


def _find_track(values: Mapping[str, Any], track_id: str) -> dict[str, Any]:
    track = next((item for item in values.get("tracks") or () if str(item.get("id") or "") == str(track_id)), None)
    if track is None: raise KeyError(f"Sequence track is unavailable: {track_id}")
    return track


def _value_type(value: Any) -> str:
    if isinstance(value, bool): return "bool"
    if isinstance(value, int): return "int"
    if isinstance(value, float): return "float"
    if isinstance(value, (list, tuple)): return f"vector{len(value)}"
    return "string"


def _canonical_track_type(value: str) -> str:
    text = str(value or "").casefold().replace(" ", "_")
    aliases = (
        (("camera_cut", "cameracut"), "camera_cut"), (("cinecamera", "camera"), "camera"),
        (("subscene", "controltrack", "sub_sequence"), "sub_sequence"),
        (("animation", "animationtrack", "skeletal"), "animation"),
        (("transform", "3dtransform"), "transform"), (("translation",), "translation"),
        (("audio",), "audio"), (("signal", "event"), "event"),
        (("activation", "visibility"), "visibility"), (("controlrig", "control_rig"), "control_rig"),
        (("levelvisibility", "level_visibility"), "level_visibility"), (("levelblend", "level_blend"), "level_blend"),
    )
    for needles, result in aliases:
        if any(needle in text for needle in needles): return result
    return text if text in TRACK_DEFINITIONS else "property"
