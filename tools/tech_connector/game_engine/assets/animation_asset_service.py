"""Editable animation assets, deterministic runtime cooking, and engine interchange."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


ANIMATION_CLIP_SCHEMA = "tech_connector.asset.animation_clip.v2"
BLEND_SPACE_SCHEMA = "tech_connector.asset.blend_space.v1"
ANIMATION_MASK_SCHEMA = "tech_connector.asset.animation_mask.v1"
ANIMATION_CONTROLLER_SCHEMA = "tech_connector.asset.animation_controller.v2"
ANIMATION_INTERCHANGE_SCHEMA = "tech_connector.animation_interchange.v1"
ANIMATION_RUNTIME_SCHEMA = "tech_connector.runtime.animation.v1"


@dataclass(frozen=True)
class AnimationIssue:
    severity: str
    code: str
    message: str
    subject: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AnimationConversionReceipt:
    provider: str
    source_version: str
    asset_ids: tuple[str, ...]
    diagnostics: tuple[AnimationIssue, ...]
    source_to_asset: dict[str, str]

    @property
    def succeeded(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "source_version": self.source_version,
            "asset_ids": list(self.asset_ids), "succeeded": self.succeeded,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "source_to_asset": dict(self.source_to_asset),
        }


def animation_clip_defaults(
    *, skeleton_id: str = "", duration_seconds: float = 1.0,
    sample_rate: float = 30.0, loop: bool = True,
) -> dict[str, Any]:
    return {
        "animation_version": 2, "skeleton_id": str(skeleton_id),
        "duration_seconds": max(0.0, float(duration_seconds)),
        "sample_rate": max(1.0, float(sample_rate)), "loop": bool(loop),
        "additive": {"enabled": False, "base_pose": "reference_pose", "base_clip_id": "", "space": "local"},
        "root_motion": {"mode": "preserve", "root_bone": "root", "lock_height": False, "normalize_scale": True},
        "tracks": [], "curves": [], "events": [], "sync_markers": [],
        "compression": {"preset": "balanced", "error_threshold": 0.001, "rotation_format": "variable", "translation_format": "variable"},
        "retargeting": {"translation_mode": "skeleton", "rotation_mode": "animation"},
        "source": {},
    }


def blend_space_defaults(
    *, skeleton_id: str = "", dimensions: int = 2,
    axes: Sequence[Mapping[str, Any]] = (), samples: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    count = 1 if int(dimensions) == 1 else 2
    default_axes = [
        {"name": "Speed", "parameter": "speed", "minimum": 0.0, "maximum": 6.0, "grid_divisions": 6, "smoothing_seconds": 0.1},
        {"name": "Direction", "parameter": "direction", "minimum": -180.0, "maximum": 180.0, "grid_divisions": 8, "smoothing_seconds": 0.1, "wrap": True},
    ]
    return {
        "blend_space_version": 1, "skeleton_id": str(skeleton_id), "dimensions": count,
        "axes": [deepcopy(dict(value)) for value in axes][:count] or default_axes[:count],
        "samples": [_normalize_sample(value, count) for value in samples],
        "interpolation": {"method": "linear" if count == 1 else "triangulated", "weight_speed": 5.0, "target_weight_epsilon": 0.0001},
        "sync": {"mode": "marker", "group": "Locomotion", "leader": "highest_weight"},
        "preview": {"x": 0.0, "y": 0.0}, "source": {},
    }


def animation_mask_defaults(*, skeleton_id: str = "", weights: Mapping[str, float] | None = None) -> dict[str, Any]:
    return {
        "mask_version": 1, "skeleton_id": str(skeleton_id),
        "weights": {str(key): min(1.0, max(0.0, float(value))) for key, value in dict(weights or {}).items()},
        "include_children": True, "feather_depth": 0, "source": {},
    }


def animation_controller_defaults(*, skeleton_id: str = "") -> dict[str, Any]:
    return {
        "animation_controller_version": 2, "skeleton_id": str(skeleton_id),
        "parameters": {},
        "layers": [{
            "id": "base", "name": "Base Layer", "weight": 1.0, "blend_mode": "override", "mask_asset_id": "",
            "state_machine": {"entry_state": "entry", "states": [{"id": "entry", "name": "Entry", "motion": None, "speed": 1.0, "loop": True}], "transitions": []},
        }],
        "pose_graph": {"nodes": [], "connections": []}, "slots": [], "sync_groups": [],
        "root_motion": {"mode": "in_place", "consume_translation": False, "consume_rotation": False},
        "performance": {"update_rate": 1, "maximum_active_poses": 8, "cache_poses": True, "multithreaded": True, "lod_thresholds": []},
        "source_extensions": [], "source": {},
    }


class AnimationAssetService:
    """One source of truth for editor UI, Python automation, conversion, and cook."""

    _TYPES = {"tc.animation_clip", "tc.blend_space", "tc.animation_mask", "tc.animation_controller"}

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create_clip(self, name: str, *, skeleton_id: str = "", duration_seconds: float = 1.0,
                    sample_rate: float = 30.0, loop: bool = True, folder: str | Path = "Assets/Animation/Clips"):
        receipt = self.operations.create_asset("tc.animation_clip", name, folder=folder)
        self._save(receipt.asset_id, animation_clip_defaults(skeleton_id=skeleton_id, duration_seconds=duration_seconds, sample_rate=sample_rate, loop=loop))
        return receipt

    def create_blend_space(self, name: str, *, skeleton_id: str = "", dimensions: int = 2,
                           axes: Sequence[Mapping[str, Any]] = (), samples: Sequence[Mapping[str, Any]] = (),
                           folder: str | Path = "Assets/Animation/BlendSpaces"):
        receipt = self.operations.create_asset("tc.blend_space", name, folder=folder)
        self._save(receipt.asset_id, blend_space_defaults(skeleton_id=skeleton_id, dimensions=dimensions, axes=axes, samples=samples))
        return receipt

    def create_mask(self, name: str, *, skeleton_id: str = "", weights: Mapping[str, float] | None = None,
                    folder: str | Path = "Assets/Animation/Masks"):
        receipt = self.operations.create_asset("tc.animation_mask", name, folder=folder)
        self._save(receipt.asset_id, animation_mask_defaults(skeleton_id=skeleton_id, weights=weights))
        return receipt

    def create_controller(self, name: str, *, skeleton_id: str = "", properties: Mapping[str, Any] | None = None,
                          folder: str | Path = "Assets/Animation/Controllers"):
        receipt = self.operations.create_asset("tc.animation_controller", name, folder=folder)
        values = animation_controller_defaults(skeleton_id=skeleton_id)
        values.update(deepcopy(dict(properties or {})))
        self._save(receipt.asset_id, values)
        return receipt

    def properties(self, asset_id: str) -> dict[str, Any]:
        _record, values = self._load(asset_id)
        return values

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        _record, current = self._load(asset_id)
        authored = {} if replace else current
        authored.update(deepcopy(dict(values or {})))
        self._save(asset_id, authored)
        return self.properties(asset_id)

    def validate(self, asset_id: str) -> list[AnimationIssue]:
        record, values = self._load(asset_id)
        if record.asset_type == "tc.animation_clip": return validate_animation_clip(values)
        if record.asset_type == "tc.blend_space": return validate_blend_space(values)
        if record.asset_type == "tc.animation_mask": return validate_animation_mask(values)
        return validate_animation_controller(values)

    def evaluate_blend_space(self, asset_id: str, x: float, y: float = 0.0) -> dict[str, float]:
        record, values = self._load(asset_id)
        if record.asset_type != "tc.blend_space":
            raise ValueError(f"Asset is not a Blend Space: {asset_id}")
        return evaluate_blend_space(values, x=x, y=y)

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record, values = self._load(asset_id)
        compiled = compile_animation_payload(record.asset_type, values, platform=platform, quality=quality)
        kind = record.asset_type.removeprefix("tc.") + "_runtime"
        return self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}", compiled,
            metadata={"platform": platform, "quality": quality, "schema": ANIMATION_RUNTIME_SCHEMA}, extension=".tcanim",
        )

    def convert_unreal(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted/Unreal") -> AnimationConversionReceipt:
        return self._convert("unreal", payload, folder)

    def convert_unity(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted/Unity") -> AnimationConversionReceipt:
        return self._convert("unity", payload, folder)

    def convert_file(self, source_path: str | Path, *, provider: str,
                     folder: str | Path = "Assets/Animation/Converted") -> AnimationConversionReceipt:
        """Convert an Unreal/Unity editor export file into native editable assets."""
        path = Path(source_path).expanduser().resolve()
        if path.suffix.casefold() in {".uasset", ".controller", ".anim"}:
            raise ValueError(
                f"'{path.suffix}' is an engine-private format. Export it with the Tech Connector "
                f"{str(provider).title()} editor adapter, then import the resulting .json file."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Animation export is not readable JSON: {path}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Animation export root must be a JSON object.")
        return self._convert(provider, payload, folder)

    def import_interchange(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted") -> AnimationConversionReceipt:
        data = dict(payload or {})
        if data.get("schema") != ANIMATION_INTERCHANGE_SCHEMA:
            raise ValueError(f"Unsupported animation interchange schema: {data.get('schema')!r}")
        provider = str(data.get("provider") or "portable").casefold()
        return self._convert(provider, data, folder)

    def export_interchange(self, asset_ids: Iterable[str], *, provider: str = "tech_connector") -> dict[str, Any]:
        assets = []
        for asset_id in dict.fromkeys(str(value) for value in asset_ids):
            record, properties = self._load(asset_id)
            assets.append({"source_id": asset_id, "name": record.source_path.stem.split(".")[0], "type_id": record.asset_type, "properties": properties})
        return {"schema": ANIMATION_INTERCHANGE_SCHEMA, "provider": str(provider), "provider_version": "1", "assets": assets}

    def _convert(self, provider: str, payload: Mapping[str, Any], folder: str | Path) -> AnimationConversionReceipt:
        provider = str(provider).casefold()
        if provider not in {"unreal", "unity", "portable", "tech_connector"}:
            raise ValueError(f"Unsupported animation provider: {provider}")
        document, diagnostics = _normalize_interchange(provider, payload)
        created: list[str] = []
        mapping: dict[str, str] = {}
        # Motions are created before controllers so references can be resolved.
        priority = {"tc.animation_clip": 0, "tc.blend_space": 1, "tc.animation_mask": 2, "tc.animation_controller": 3}
        for row in sorted(document.get("assets") or [], key=lambda value: priority.get(str(value.get("type_id")), 9)):
            type_id = str(row.get("type_id") or "")
            if type_id not in self._TYPES:
                diagnostics.append(AnimationIssue("warning", "unsupported_asset_type", f"Preserved unsupported {provider} asset type '{type_id}'.", str(row.get("source_id") or ""), "Export it as an animation clip, blend space, mask, or controller."))
                continue
            properties = _replace_source_refs(deepcopy(dict(row.get("properties") or {})), mapping)
            name = _safe_name(str(row.get("name") or type_id.removeprefix("tc.")))
            receipt = self.operations.create_asset(type_id, _available_name(self.project_root / Path(folder), name, self.operations, type_id), folder=folder)
            properties.setdefault("source", {"provider": provider, "version": str(document.get("provider_version") or ""), "source_id": str(row.get("source_id") or "")})
            self._save(receipt.asset_id, properties)
            created.append(receipt.asset_id)
            source_id = str(row.get("source_id") or name)
            mapping[source_id] = receipt.asset_id
        # Resolve forward references after every source object has an ID.
        for asset_id in created:
            self._save(asset_id, _replace_source_refs(self.properties(asset_id), mapping))
        return AnimationConversionReceipt(provider, str(document.get("provider_version") or ""), tuple(created), tuple(diagnostics), mapping)

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown animation asset: {asset_id}")
        if record.asset_type not in self._TYPES: raise ValueError(f"Asset is not an animation asset: {asset_id}")
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Animation source is unreadable: {record.source_path}") from exc
        return record, _normalize_properties(record.asset_type, deepcopy(dict(payload.get("properties") or {})))

    def _save(self, asset_id: str, properties: Mapping[str, Any]) -> None:
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown animation asset: {asset_id}")
        values = _normalize_properties(record.asset_type, properties)
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        payload["schema"] = _schema_for(record.asset_type)
        payload["properties"] = values
        _atomic_json_write(record.source_path, payload)
        edges = [(reference, kind) for reference, kind in _asset_references(record.asset_type, values) if self.database.asset(reference) is not None and reference != asset_id]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata, dependencies=edges)


def validate_animation_clip(values: Mapping[str, Any]) -> list[AnimationIssue]:
    issues: list[AnimationIssue] = []
    if float(values.get("duration_seconds", 0.0) or 0.0) <= 0: issues.append(AnimationIssue("error", "invalid_duration", "Duration must be greater than zero.", "duration_seconds"))
    if float(values.get("sample_rate", 0.0) or 0.0) <= 0: issues.append(AnimationIssue("error", "invalid_sample_rate", "Sample rate must be greater than zero.", "sample_rate"))
    duration = float(values.get("duration_seconds", 0.0) or 0.0)
    for event in values.get("events") or []:
        time = float(dict(event).get("time", -1.0) or 0.0)
        if time < 0 or time > duration: issues.append(AnimationIssue("error", "event_out_of_range", "Animation event lies outside the clip duration.", str(dict(event).get("name") or "event")))
    additive = dict(values.get("additive") or {})
    if additive.get("enabled") and additive.get("base_pose") == "clip" and not additive.get("base_clip_id"):
        issues.append(AnimationIssue("error", "missing_additive_base", "Additive clip mode requires a base clip.", "additive.base_clip_id"))
    return issues


def validate_blend_space(values: Mapping[str, Any]) -> list[AnimationIssue]:
    issues: list[AnimationIssue] = []
    dimensions = int(values.get("dimensions", 2) or 2)
    axes = list(values.get("axes") or [])
    if dimensions not in {1, 2}: issues.append(AnimationIssue("error", "invalid_dimensions", "Blend Spaces support one or two dimensions.", "dimensions"))
    if len(axes) != dimensions: issues.append(AnimationIssue("error", "axis_count", "Axis count must match Blend Space dimensions.", "axes"))
    for index, axis in enumerate(axes):
        row = dict(axis)
        if float(row.get("minimum", 0.0)) >= float(row.get("maximum", 0.0)): issues.append(AnimationIssue("error", "invalid_axis_range", "Axis minimum must be below maximum.", f"axes[{index}]"))
    seen: set[tuple[float, ...]] = set()
    for index, sample in enumerate(values.get("samples") or []):
        row = dict(sample); position = tuple(float(v) for v in row.get("position") or ())
        if len(position) != dimensions: issues.append(AnimationIssue("error", "sample_dimensions", "Sample position does not match Blend Space dimensions.", f"samples[{index}]")); continue
        if position in seen: issues.append(AnimationIssue("warning", "duplicate_sample", "Multiple samples occupy the same position.", f"samples[{index}]", "Move or remove one of the samples."))
        seen.add(position)
        for axis_index, value in enumerate(position):
            if axis_index < len(axes) and not float(axes[axis_index].get("minimum", 0.0)) <= value <= float(axes[axis_index].get("maximum", 0.0)):
                issues.append(AnimationIssue("error", "sample_out_of_range", "Sample lies outside an axis range.", f"samples[{index}].position[{axis_index}]"))
    if not values.get("samples"): issues.append(AnimationIssue("warning", "no_samples", "Blend Space has no animation samples.", "samples", "Add at least one clip sample."))
    return issues


def validate_animation_mask(values: Mapping[str, Any]) -> list[AnimationIssue]:
    return [AnimationIssue("error", "invalid_weight", "Bone mask weights must be between zero and one.", str(bone)) for bone, weight in dict(values.get("weights") or {}).items() if not 0.0 <= float(weight) <= 1.0]


def validate_animation_controller(values: Mapping[str, Any]) -> list[AnimationIssue]:
    issues: list[AnimationIssue] = []
    parameters = dict(values.get("parameters") or {})
    for name, spec in parameters.items():
        if str(dict(spec).get("type") or "float").casefold() not in {"float", "int", "bool", "trigger"}: issues.append(AnimationIssue("error", "invalid_parameter_type", f"Parameter '{name}' has an unsupported type.", str(name)))
    layers = list(values.get("layers") or [])
    if not layers: issues.append(AnimationIssue("error", "no_layers", "Animation Controller needs at least one layer.", "layers"))
    for layer_index, layer in enumerate(layers):
        machine = dict(dict(layer).get("state_machine") or {}); rows = [dict(row) for row in machine.get("states") or []]
        state_ids = [str(row.get("id") or "") for row in rows]
        if len(state_ids) != len(set(state_ids)): issues.append(AnimationIssue("error", "duplicate_state", "State IDs must be unique within a layer.", f"layers[{layer_index}]"))
        if str(machine.get("entry_state") or "") not in state_ids: issues.append(AnimationIssue("error", "invalid_entry_state", "Layer entry state does not exist.", f"layers[{layer_index}].state_machine.entry_state"))
        for index, transition in enumerate(machine.get("transitions") or []):
            row = dict(transition); source = str(row.get("from") or ""); target = str(row.get("to") or "")
            if source not in state_ids and source not in {"any", "*"}: issues.append(AnimationIssue("error", "invalid_transition_source", "Transition source state does not exist.", f"layers[{layer_index}].transitions[{index}]"))
            if target not in state_ids: issues.append(AnimationIssue("error", "invalid_transition_target", "Transition target state does not exist.", f"layers[{layer_index}].transitions[{index}]"))
            for condition in row.get("conditions") or []:
                parameter = str(dict(condition).get("parameter") or "")
                if parameter and parameter not in parameters and parameter not in {"state_time", "normalized_time", "remaining_time"}: issues.append(AnimationIssue("error", "unknown_parameter", f"Transition references unknown parameter '{parameter}'.", f"layers[{layer_index}].transitions[{index}]"))
    return issues


def evaluate_blend_space(values: Mapping[str, Any], *, x: float, y: float = 0.0) -> dict[str, float]:
    dimensions = int(values.get("dimensions", 2) or 2)
    samples = [dict(row) for row in values.get("samples") or []]
    if not samples: return {}
    query = (float(x),) if dimensions == 1 else (float(x), float(y))
    distances = []
    for index, sample in enumerate(samples):
        position = tuple(float(v) for v in sample.get("position") or ())[:dimensions]
        if len(position) != dimensions: continue
        distance = math.sqrt(sum((position[i] - query[i]) ** 2 for i in range(dimensions)))
        key = str(sample.get("id") or sample.get("clip_asset_id") or f"sample_{index}")
        if distance <= 1e-8: return {key: 1.0}
        distances.append((key, distance))
    # Restrict to the local simplex-sized neighbourhood; inverse distance is stable for collinear/degenerate samples.
    distances.sort(key=lambda item: (item[1], item[0])); selected = distances[:2 if dimensions == 1 else 3]
    raw = [(key, 1.0 / max(distance, 1e-8)) for key, distance in selected]; total = sum(value for _key, value in raw)
    return {key: value / total for key, value in raw} if total else {}


def compile_animation_payload(type_id: str, values: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    """Validate and compile any first-class animation asset into portable runtime data."""
    if type_id not in AnimationAssetService._TYPES:
        raise ValueError(f"Unsupported animation asset type: {type_id}")
    normalized = _normalize_properties(type_id, values)
    validator = {
        "tc.animation_clip": validate_animation_clip,
        "tc.blend_space": validate_blend_space,
        "tc.animation_mask": validate_animation_mask,
        "tc.animation_controller": validate_animation_controller,
    }[type_id]
    errors = [item.message for item in validator(normalized) if item.severity == "error"]
    if errors:
        raise ValueError(f"{type_id} is not cookable: " + " ".join(errors))
    return _compile_asset(type_id, normalized, platform=platform, quality=quality)


def _normalize_interchange(provider: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[AnimationIssue]]:
    data = deepcopy(dict(payload or {})); diagnostics: list[AnimationIssue] = []
    if data.get("schema") == ANIMATION_INTERCHANGE_SCHEMA:
        return data, diagnostics
    if provider == "unreal": return _normalize_unreal(data, diagnostics), diagnostics
    if provider == "unity": return _normalize_unity(data, diagnostics), diagnostics
    raise ValueError("Portable conversion requires a versioned animation interchange document.")


def _normalize_unreal(data: dict[str, Any], diagnostics: list[AnimationIssue]) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    version = str(data.get("engine_version") or data.get("version") or "unknown")
    for clip in data.get("animation_sequences") or data.get("clips") or []:
        row = dict(clip); props = animation_clip_defaults(skeleton_id=str(row.get("skeleton") or ""), duration_seconds=float(row.get("duration") or row.get("length") or 1.0), sample_rate=float(row.get("sample_rate") or 30.0), loop=bool(row.get("loop", True)))
        props.update({key: deepcopy(row[key]) for key in ("curves", "events", "sync_markers", "tracks") if key in row})
        props["root_motion"]["mode"] = "extract" if row.get("enable_root_motion") else "preserve"
        assets.append({"source_id": str(row.get("object_path") or row.get("id") or row.get("name")), "name": str(row.get("name") or "AnimationClip"), "type_id": "tc.animation_clip", "properties": props})
    for space in data.get("blend_spaces") or []:
        row = dict(space); dimensions = 1 if "1d" in str(row.get("type") or "").casefold() else int(row.get("dimensions") or 2)
        axes = [_axis_from_unreal(value) for value in row.get("axes") or []]
        samples = [{"id": str(value.get("id") or f"sample_{i}"), "clip_asset_id": str(value.get("animation") or value.get("clip") or ""), "position": list(value.get("position") or [value.get("x", 0.0), value.get("y", 0.0)])[:dimensions], "rate_scale": float(value.get("rate_scale") or 1.0), "mirror": bool(value.get("mirror", False))} for i, value in enumerate(row.get("samples") or [])]
        props = blend_space_defaults(skeleton_id=str(row.get("skeleton") or ""), dimensions=dimensions, axes=axes, samples=samples)
        assets.append({"source_id": str(row.get("object_path") or row.get("id") or row.get("name")), "name": str(row.get("name") or "BlendSpace"), "type_id": "tc.blend_space", "properties": props})
    for controller in data.get("animation_blueprints") or data.get("controllers") or ([data] if data.get("state_machines") else []):
        row = dict(controller); props = animation_controller_defaults(skeleton_id=str(row.get("skeleton") or ""))
        props["parameters"] = {str(key): _parameter_spec(value) for key, value in dict(row.get("parameters") or row.get("variables") or {}).items()}
        props["layers"] = [_unreal_machine(value, index) for index, value in enumerate(row.get("state_machines") or [])] or props["layers"]
        props["slots"] = deepcopy(list(row.get("slots") or [])); props["source_extensions"] = _unsupported_nodes(row, "unreal", diagnostics)
        assets.append({"source_id": str(row.get("object_path") or row.get("id") or row.get("name")), "name": str(row.get("name") or "AnimationController"), "type_id": "tc.animation_controller", "properties": props})
    return {"schema": ANIMATION_INTERCHANGE_SCHEMA, "provider": "unreal", "provider_version": version, "assets": assets}


def _normalize_unity(data: dict[str, Any], diagnostics: list[AnimationIssue]) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    version = str(data.get("unity_version") or data.get("version") or "unknown")
    for clip in data.get("animation_clips") or data.get("clips") or []:
        row = dict(clip)
        props = animation_clip_defaults(
            skeleton_id=str(row.get("skeleton") or row.get("avatar") or ""),
            duration_seconds=float(row.get("duration") or row.get("length") or 1.0),
            sample_rate=float(row.get("sample_rate") or row.get("frame_rate") or row.get("frameRate") or 60.0),
            loop=bool(row.get("loop", row.get("is_looping", row.get("isLooping", True)))),
        )
        props["events"] = deepcopy(list(row.get("events") or []))
        props["curves"] = deepcopy(list(row.get("curves") or []))
        assets.append({
            "source_id": str(row.get("guid") or row.get("id") or row.get("asset_path") or row.get("name")),
            "name": str(row.get("name") or "AnimationClip"), "type_id": "tc.animation_clip", "properties": props,
        })
    for mask in data.get("animation_masks") or data.get("avatar_masks") or []:
        row = dict(mask); weights = dict(row.get("weights") or {})
        if not weights:
            weights = {str(item.get("path") or item.get("bone") or ""): 1.0 if item.get("active", True) else 0.0 for item in row.get("transforms") or [] if item.get("path") or item.get("bone")}
        props = animation_mask_defaults(skeleton_id=str(row.get("skeleton") or ""), weights=weights)
        assets.append({
            "source_id": str(row.get("guid") or row.get("id") or row.get("name")),
            "name": str(row.get("name") or "AnimationMask"), "type_id": "tc.animation_mask", "properties": props,
        })
    controllers = data.get("animator_controllers") or data.get("controllers") or ([data] if data.get("layers") else [])
    for controller in controllers:
        row = dict(controller); generated_spaces: list[dict[str, Any]] = []
        props = animation_controller_defaults(skeleton_id=str(row.get("skeleton") or row.get("avatar") or ""))
        parameters = row.get("parameters") or {}
        props["parameters"] = ({str(key): _parameter_spec(value) for key, value in parameters.items()} if isinstance(parameters, Mapping) else {str(value.get("name")): _parameter_spec(value) for value in parameters})
        props["layers"] = []
        for layer_index, layer_value in enumerate(row.get("layers") or []):
            layer = dict(layer_value); machine = dict(layer.get("state_machine") or layer.get("stateMachine") or layer)
            states = []
            for state_index, state_value in enumerate(machine.get("states") or []):
                state = dict(state_value); motion = state.get("motion")
                if isinstance(motion, Mapping) and str(motion.get("type") or "").casefold() in {"blendtree", "blend_tree"}:
                    source_id = str(motion.get("id") or f"{row.get('name', 'Controller')}:{layer_index}:{state_index}:blend_tree")
                    generated_spaces.append(_unity_blend_tree(dict(motion), source_id, str(row.get("skeleton") or "")))
                    motion_ref = {"type": "blend_space", "asset_id": source_id}
                else:
                    motion_ref = {"type": "clip", "asset_id": str(dict(motion).get("clip") or dict(motion).get("id") or "")} if isinstance(motion, Mapping) else ({"type": "clip", "asset_id": str(motion)} if motion else None)
                states.append({"id": str(state.get("id") or state.get("name") or f"state_{state_index}"), "name": str(state.get("name") or f"State {state_index}"), "motion": motion_ref, "speed": float(state.get("speed") or 1.0), "loop": bool(state.get("loop", True)), "write_defaults": bool(state.get("write_defaults", state.get("writeDefaultValues", True))), "source_extensions": deepcopy(list(state.get("behaviours") or []))})
                if state.get("behaviours"): diagnostics.append(AnimationIssue("warning", "unity_behaviour_preserved", "Unity StateMachineBehaviour was preserved as source metadata and needs a Tech Connector gameplay callback.", str(state.get("name") or "state")))
            transitions = [_unity_transition(value, index) for index, value in enumerate(machine.get("transitions") or [])]
            entry = str(machine.get("default_state") or machine.get("defaultState") or (states[0]["id"] if states else ""))
            props["layers"].append({"id": str(layer.get("id") or f"layer_{layer_index}"), "name": str(layer.get("name") or f"Layer {layer_index}"), "weight": float(layer.get("weight", layer.get("defaultWeight", 1.0))), "blend_mode": "additive" if str(layer.get("blending_mode") or layer.get("blendingMode") or "").casefold() == "additive" else "override", "mask_asset_id": str(layer.get("mask") or ""), "synced_layer_index": int(layer.get("synced_layer_index", layer.get("syncedLayerIndex", -1))), "state_machine": {"entry_state": entry, "states": states, "transitions": transitions}})
        props["source_extensions"] = _unsupported_nodes(row, "unity", diagnostics)
        assets.extend(generated_spaces)
        assets.append({"source_id": str(row.get("guid") or row.get("id") or row.get("name")), "name": str(row.get("name") or "AnimationController"), "type_id": "tc.animation_controller", "properties": props})
    return {"schema": ANIMATION_INTERCHANGE_SCHEMA, "provider": "unity", "provider_version": version, "assets": assets}


def _unreal_machine(value: Mapping[str, Any], index: int) -> dict[str, Any]:
    row = dict(value); states = []
    for state_index, item in enumerate(row.get("states") or []):
        state = dict(item); source_motion = state.get("motion") or state.get("animation") or state.get("blend_space")
        kind = "blend_space" if state.get("blend_space") or str(dict(source_motion).get("type") if isinstance(source_motion, Mapping) else "").casefold() in {"blendspace", "blend_space"} else "clip"
        reference = str(dict(source_motion).get("asset_id") or dict(source_motion).get("asset") or "") if isinstance(source_motion, Mapping) else str(source_motion or "")
        states.append({"id": str(state.get("id") or state.get("name") or f"state_{state_index}"), "name": str(state.get("name") or f"State {state_index}"), "motion": {"type": kind, "asset_id": reference} if reference else None, "speed": float(state.get("speed") or 1.0), "loop": bool(state.get("loop", True))})
    return {"id": str(row.get("id") or f"layer_{index}"), "name": str(row.get("name") or f"State Machine {index}"), "weight": 1.0, "blend_mode": "override", "mask_asset_id": "", "state_machine": {"entry_state": str(row.get("entry_state") or row.get("initial_state") or (states[0]["id"] if states else "")), "states": states, "transitions": [_unreal_transition(item, i) for i, item in enumerate(row.get("transitions") or [])]}}


def _unreal_transition(value: Mapping[str, Any], index: int) -> dict[str, Any]:
    row = dict(value); conditions = row.get("conditions") or _parse_condition(str(row.get("condition") or ""))
    return {"id": str(row.get("id") or f"transition_{index}"), "from": str(row.get("from") or row.get("source") or ""), "to": str(row.get("to") or row.get("target") or ""), "conditions": deepcopy(list(conditions)), "duration": float(row.get("duration", row.get("blend_seconds", 0.2))), "exit_time": row.get("exit_time"), "blend_mode": str(row.get("blend_mode") or "crossfade"), "interruption": str(row.get("interruption") or "source_then_target")}


def _unity_transition(value: Mapping[str, Any], index: int) -> dict[str, Any]:
    row = dict(value); conditions = []
    operator_map = {"if": "is_true", "ifnot": "is_false", "greater": ">", "less": "<", "equals": "==", "notequal": "!="}
    for item in row.get("conditions") or []:
        condition = dict(item); mode = str(condition.get("mode") or condition.get("operator") or "if").replace("_", "").casefold()
        conditions.append({"parameter": str(condition.get("parameter") or condition.get("name") or ""), "operator": operator_map.get(mode, str(condition.get("operator") or "==")), "threshold": condition.get("threshold", condition.get("value", True))})
    return {"id": str(row.get("id") or f"transition_{index}"), "from": str(row.get("from") or row.get("source") or "any" if row.get("any_state") else ""), "to": str(row.get("to") or row.get("destination") or ""), "conditions": conditions, "duration": float(row.get("duration") or 0.0), "offset": float(row.get("offset") or 0.0), "exit_time": float(row.get("exit_time", row.get("exitTime", 0.0))) if row.get("has_exit_time", row.get("hasExitTime", False)) else None, "interruption": str(row.get("interruption_source") or row.get("interruptionSource") or "none"), "ordered": bool(row.get("ordered_interruption", row.get("orderedInterruption", True))), "blend_mode": "crossfade"}


def _unity_blend_tree(tree: dict[str, Any], source_id: str, skeleton: str) -> dict[str, Any]:
    blend_type = str(tree.get("blend_type") or tree.get("blendType") or "Simple1D"); dimensions = 1 if "1d" in blend_type.casefold() else 2
    parameters = [str(tree.get("blend_parameter") or tree.get("blendParameter") or "speed"), str(tree.get("blend_parameter_y") or tree.get("blendParameterY") or "direction")]
    axes = [{"name": value.title(), "parameter": value, "minimum": float(tree.get("minimum", -1.0 if index else 0.0)), "maximum": float(tree.get("maximum", 1.0)), "grid_divisions": 5, "smoothing_seconds": 0.1} for index, value in enumerate(parameters[:dimensions])]
    samples = []
    for index, child_value in enumerate(tree.get("children") or []):
        child = dict(child_value); position = [float(child.get("threshold", 0.0))] if dimensions == 1 else list(child.get("position") or [child.get("position_x", 0.0), child.get("position_y", 0.0)])[:2]
        samples.append({"id": str(child.get("id") or f"sample_{index}"), "clip_asset_id": str(child.get("motion") or child.get("clip") or ""), "position": position, "rate_scale": float(child.get("time_scale", child.get("timeScale", 1.0))), "mirror": bool(child.get("mirror", False))})
    props = blend_space_defaults(skeleton_id=skeleton, dimensions=dimensions, axes=axes, samples=samples); props["source_extensions"] = {"unity_blend_type": blend_type, "use_automatic_thresholds": bool(tree.get("use_automatic_thresholds", tree.get("useAutomaticThresholds", False)))}
    return {"source_id": source_id, "name": str(tree.get("name") or "BlendTree"), "type_id": "tc.blend_space", "properties": props}


def _unsupported_nodes(row: Mapping[str, Any], provider: str, diagnostics: list[AnimationIssue]) -> list[dict[str, Any]]:
    supported = {"sequenceplayer", "blendspaceplayer", "statemachine", "slot", "layeredboneblend", "applyadditive", "inertialization", "deadblending", "outputpose", "blendtree", "clip"}
    preserved = []
    for node in list(row.get("nodes") or row.get("graph_nodes") or []):
        item = dict(node); kind = str(item.get("type") or item.get("opcode") or "unknown"); key = re.sub(r"[^a-z0-9]", "", kind.casefold())
        if key not in supported:
            preserved.append({"provider": provider, "kind": kind, "payload": deepcopy(item)})
            diagnostics.append(AnimationIssue("warning", "unsupported_node_preserved", f"{provider.title()} node '{kind}' was preserved but requires a native replacement.", str(item.get("name") or item.get("id") or kind), "Replace it in the Animation Controller graph before shipping."))
    return preserved


def _parse_condition(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, expression in enumerate(re.split(r"\s+(and|or)\s+", text.strip(), flags=re.IGNORECASE)):
        if index % 2:
            continue
        match = re.fullmatch(r"\s*(not\s+)?([A-Za-z_][\w.]*)\s*(<=|>=|==|!=|<|>)?\s*(.*?)\s*", expression)
        if not match:
            continue
        negated, parameter, operator, raw = match.groups(); value: Any = True
        if raw:
            if raw.casefold() in {"true", "false"}: value = raw.casefold() == "true"
            else:
                try: value = float(raw)
                except ValueError: value = raw
        result.append({"parameter": parameter, "operator": operator or ("is_false" if negated else "is_true"), "threshold": value, "join": "or" if index >= 2 and re.split(r"\s+(and|or)\s+", text.strip(), flags=re.IGNORECASE)[index - 1].casefold() == "or" else "and"})
    return result


def _compile_asset(type_id: str, values: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    authored = deepcopy(dict(values)); runtime: dict[str, Any] = {"schema": ANIMATION_RUNTIME_SCHEMA, "asset_type": type_id, "platform": str(platform), "quality": str(quality)}
    if type_id == "tc.animation_controller":
        parameters = dict(authored.get("parameters") or {}); runtime["parameter_slots"] = [{"index": index, "name": name, **dict(spec)} for index, (name, spec) in enumerate(sorted(parameters.items()))]
        runtime["layers"] = []
        for layer in authored.get("layers") or []:
            row = deepcopy(dict(layer)); machine = dict(row.get("state_machine") or {}); states = [dict(value) for value in machine.get("states") or []]; indices = {str(value.get("id")): index for index, value in enumerate(states)}
            machine["state_indices"] = indices; machine["transition_table"] = [{**dict(value), "source_index": indices.get(str(dict(value).get("from")), -1), "target_index": indices.get(str(dict(value).get("to")), -1)} for value in machine.get("transitions") or []]
            machine.pop("transitions", None); row["state_machine"] = machine; runtime["layers"].append(row)
        runtime["pose_graph"] = authored.get("pose_graph") or authored.get("graph") or {"nodes": [], "connections": []}; runtime["performance"] = authored.get("performance") or {}
    elif type_id == "tc.blend_space":
        runtime.update({key: authored.get(key) for key in ("dimensions", "axes", "samples", "interpolation", "sync")})
        runtime["sample_count"] = len(authored.get("samples") or [])
    elif type_id == "tc.animation_clip":
        runtime.update({key: authored.get(key) for key in ("skeleton_id", "duration_seconds", "sample_rate", "loop", "additive", "root_motion", "tracks", "curves", "events", "sync_markers", "compression")})
        runtime["sample_count"] = int(math.ceil(float(authored.get("duration_seconds", 0.0)) * float(authored.get("sample_rate", 0.0)))) + 1
    else: runtime.update({"skeleton_id": authored.get("skeleton_id"), "weights": authored.get("weights"), "include_children": authored.get("include_children"), "feather_depth": authored.get("feather_depth")})
    return json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_properties(type_id: str, properties: Mapping[str, Any]) -> dict[str, Any]:
    values = deepcopy(dict(properties or {}))
    if type_id == "tc.animation_clip": defaults = animation_clip_defaults(skeleton_id=str(values.get("skeleton_id") or ""), duration_seconds=float(values.get("duration_seconds") or 1.0), sample_rate=float(values.get("sample_rate") or 30.0), loop=bool(values.get("loop", True)))
    elif type_id == "tc.blend_space": defaults = blend_space_defaults(skeleton_id=str(values.get("skeleton_id") or ""), dimensions=int(values.get("dimensions") or 2), axes=values.get("axes") or (), samples=values.get("samples") or ())
    elif type_id == "tc.animation_mask": defaults = animation_mask_defaults(skeleton_id=str(values.get("skeleton_id") or ""), weights=values.get("weights") or {})
    else:
        # Keep legacy locomotion fields; expose them as one modern layer when absent.
        defaults = animation_controller_defaults(skeleton_id=str(values.get("skeleton_id") or ""))
        if not values.get("layers") and values.get("state_machine"):
            states = []
            for state in values.get("state_machine", {}).get("states") or []:
                row = dict(state); reference = row.get("clip_asset_id") or row.get("clip_slot") or row.get("blend_space") or ""; kind = "blend_space" if row.get("blend_space") else "clip"
                states.append({"id": str(row.get("id") or "state"), "name": str(row.get("name") or row.get("id") or "State"), "motion": {"type": kind, "asset_id": str(reference)} if reference else None, "speed": float(row.get("speed") or 1.0), "loop": bool(row.get("loop", True))})
            transitions = [_unreal_transition(item, index) for index, item in enumerate(values.get("state_machine", {}).get("transitions") or [])]
            values["layers"] = [{"id": "base", "name": "Base Layer", "weight": 1.0, "blend_mode": "override", "mask_asset_id": "", "state_machine": {"entry_state": str(values.get("state_machine", {}).get("entry_state") or ""), "states": states, "transitions": transitions}}]
        values.setdefault("pose_graph", deepcopy(values.get("graph") or {"nodes": [], "connections": []}))
    defaults.update(values)
    return defaults


def _asset_references(type_id: str, values: Mapping[str, Any]) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set(); skeleton = str(values.get("skeleton_id") or "")
    if skeleton: references.add((skeleton, "skeleton"))
    if type_id == "tc.animation_clip":
        base = str(dict(values.get("additive") or {}).get("base_clip_id") or "")
        if base: references.add((base, "additive_base"))
    elif type_id == "tc.blend_space":
        references.update((str(row.get("clip_asset_id")), "animation_sample") for row in values.get("samples") or [] if row.get("clip_asset_id"))
    elif type_id == "tc.animation_controller":
        for layer in values.get("layers") or []:
            mask = str(dict(layer).get("mask_asset_id") or "")
            if mask: references.add((mask, "animation_mask"))
            for state in dict(dict(layer).get("state_machine") or {}).get("states") or []:
                motion = dict(dict(state).get("motion") or {}); reference = str(motion.get("asset_id") or "")
                if reference: references.add((reference, str(motion.get("type") or "motion")))
    return references


def _replace_source_refs(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: (mapping.get(str(item), item) if key in {"asset_id", "clip_asset_id", "mask_asset_id", "skeleton_id", "base_clip_id"} else _replace_source_refs(item, mapping)) for key, item in value.items()}
    if isinstance(value, list): return [_replace_source_refs(item, mapping) for item in value]
    return value


def _normalize_sample(value: Mapping[str, Any], dimensions: int) -> dict[str, Any]:
    row = dict(value); position = list(row.get("position") or [row.get("x", row.get("speed", 0.0)), row.get("y", row.get("direction", 0.0))])[:dimensions]
    return {"id": str(row.get("id") or row.get("clip_asset_id") or row.get("clip") or f"sample_{abs(hash(tuple(position))) & 0xffff:x}"), "clip_asset_id": str(row.get("clip_asset_id") or row.get("clip") or row.get("animation") or row.get("slot") or ""), "position": [float(item) for item in position], "rate_scale": float(row.get("rate_scale") or 1.0), "mirror": bool(row.get("mirror", False)), "sync_marker": str(row.get("sync_marker") or "")}


def _parameter_spec(value: Any) -> dict[str, Any]:
    row = dict(value) if isinstance(value, Mapping) else {"default": value}; kind = str(row.get("type") or "float").casefold()
    aliases = {"boolean": "bool", "integer": "int"}; kind = aliases.get(kind, kind)
    if "default" in row:
        default = row["default"]
    elif kind == "float":
        default = row.get("default_float", row.get("defaultFloat", 0.0))
    elif kind == "int":
        default = row.get("default_int", row.get("defaultInt", 0))
    else:
        default = row.get("default_bool", row.get("defaultBool", False))
    return {"type": kind, "default": default, **({"minimum": row["minimum"]} if "minimum" in row else {}), **({"maximum": row["maximum"]} if "maximum" in row else {})}


def _axis_from_unreal(value: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(value); return {"name": str(row.get("name") or row.get("parameter") or "Axis"), "parameter": str(row.get("parameter") or row.get("name") or "axis").casefold(), "minimum": float(row.get("minimum", row.get("min", 0.0))), "maximum": float(row.get("maximum", row.get("max", 1.0))), "grid_divisions": int(row.get("grid_divisions", row.get("grid_num", 4))), "smoothing_seconds": float(row.get("smoothing_seconds", 0.1)), "wrap": bool(row.get("wrap", False))}


def _schema_for(type_id: str) -> str:
    return {"tc.animation_clip": ANIMATION_CLIP_SCHEMA, "tc.blend_space": BLEND_SPACE_SCHEMA, "tc.animation_mask": ANIMATION_MASK_SCHEMA, "tc.animation_controller": ANIMATION_CONTROLLER_SCHEMA}[type_id]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return cleaned or "AnimationAsset"


def _available_name(folder: Path, name: str, _operations: AssetOperationsService, type_id: str) -> str:
    extensions = {"tc.animation_clip": ".anim.tcasset", "tc.blend_space": ".blendspace.tcasset", "tc.animation_mask": ".animmask.tcasset", "tc.animation_controller": ".animgraph.tcasset"}
    candidate = name; index = 2
    while (folder / f"{candidate}{extensions[type_id]}").exists(): candidate, index = f"{name}_{index}", index + 1
    return candidate


def _atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


__all__ = [
    "ANIMATION_CLIP_SCHEMA", "BLEND_SPACE_SCHEMA", "ANIMATION_MASK_SCHEMA", "ANIMATION_CONTROLLER_SCHEMA",
    "ANIMATION_INTERCHANGE_SCHEMA", "ANIMATION_RUNTIME_SCHEMA", "AnimationIssue", "AnimationConversionReceipt",
    "AnimationAssetService", "animation_clip_defaults", "blend_space_defaults", "animation_mask_defaults",
    "animation_controller_defaults", "validate_animation_clip", "validate_blend_space", "validate_animation_mask",
    "validate_animation_controller", "evaluate_blend_space",
    "compile_animation_payload",
]
