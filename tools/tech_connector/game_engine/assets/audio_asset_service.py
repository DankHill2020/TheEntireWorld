"""Game-audio assets, validation, engine interchange, and deterministic cooking."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
from typing import Any, Iterable, Mapping, Sequence

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_metadata_service import read_asset_metadata, write_asset_metadata
from .asset_operations_service import AssetOperationsService


AUDIO_RUNTIME_SCHEMA = "tech_connector.runtime.audio.v1"
SOUND_CUE_SCHEMA = "tech_connector.asset.sound_cue.v1"
AUDIO_MIXER_SCHEMA = "tech_connector.asset.audio_mixer.v1"
ATTENUATION_SCHEMA = "tech_connector.asset.audio_attenuation.v1"
REVERB_SCHEMA = "tech_connector.asset.audio_reverb.v1"
AUDIO_ASSET_TYPES = {"tc.audio_clip", "tc.sound_cue", "tc.audio_mixer", "tc.audio_attenuation", "tc.audio_reverb"}

CUE_NODE_TYPES = {
    "wave_player", "random", "sequence", "mixer", "modulator", "switch", "branch",
    "delay", "loop", "attenuation", "sub_cue", "parameter", "envelope", "filter",
    "oscillator", "noise", "crossfade", "output",
}
DSP_EFFECTS = {
    "gain", "eq", "compressor", "limiter", "gate", "delay", "chorus", "flanger",
    "distortion", "convolution_reverb", "algorithmic_reverb", "high_pass", "low_pass",
    "band_pass", "pitch_shift", "stereo_width", "loudness_meter", "spectrum_analyzer",
}
VOICE_RESOLUTIONS = {"prevent_new", "stop_oldest", "stop_quietest", "stop_farthest", "stop_lowest_priority", "virtualize_quietest"}


@dataclass(frozen=True)
class AudioIssue:
    severity: str
    code: str
    message: str
    subject: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AudioConversionReceipt:
    provider: str
    source_version: str
    asset_ids: tuple[str, ...]
    diagnostics: tuple[AudioIssue, ...]
    source_to_asset: dict[str, str]

    @property
    def succeeded(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "source_version": self.source_version, "asset_ids": list(self.asset_ids), "succeeded": self.succeeded, "diagnostics": [item.to_dict() for item in self.diagnostics], "source_to_asset": dict(self.source_to_asset)}


def audio_clip_defaults() -> dict[str, Any]:
    return {
        "audio_version": 1, "load_mode": "decompress_on_load", "compression": "auto",
        "quality": 0.8, "sample_rate_policy": "preserve", "sample_rate": 0,
        "channel_policy": "preserve", "normalize": False, "loudness_target_lufs": -16.0,
        "stream_chunk_kb": 256, "seekable": True, "loop": False,
        "loop_start_seconds": 0.0, "loop_end_seconds": 0.0,
        "trim_start_seconds": 0.0, "trim_end_seconds": 0.0,
        "analysis": {"envelope": False, "spectrum": False, "tempo": False},
        "platform_overrides": {},
    }


def sound_cue_defaults() -> dict[str, Any]:
    return {
        "audio_version": 1, "volume": 1.0, "pitch": 1.0, "priority": 1.0,
        "parameters": {}, "graph": {"nodes": [{"id": "output", "type": "output", "parameters": {}}], "connections": []},
        "attenuation_asset_id": "", "mixer_group_id": "master", "submix_sends": [],
        "concurrency": {"group": "default", "maximum_voices": 16, "resolution": "stop_oldest", "retrigger_seconds": 0.0, "virtualize": True},
        "spatialization": {"enabled": False, "plugin": "builtin", "binaural": False},
        "source_effects": [], "loop": False, "duration_limit_seconds": 0.0,
        "source_extensions": [],
    }


def audio_mixer_defaults() -> dict[str, Any]:
    return {
        "audio_version": 1,
        "groups": [
            {"id": "master", "name": "Master", "parent_id": "", "volume_db": 0.0, "mute": False, "solo": False, "effects": [{"id": "master_limiter", "type": "limiter", "enabled": True, "parameters": {"ceiling_db": -0.3}}], "sends": []},
            {"id": "music", "name": "Music", "parent_id": "master", "volume_db": 0.0, "mute": False, "solo": False, "effects": [], "sends": []},
            {"id": "sfx", "name": "SFX", "parent_id": "master", "volume_db": 0.0, "mute": False, "solo": False, "effects": [], "sends": []},
            {"id": "dialogue", "name": "Dialogue", "parent_id": "master", "volume_db": 0.0, "mute": False, "solo": False, "effects": [], "sends": []},
            {"id": "ui", "name": "UI", "parent_id": "master", "volume_db": 0.0, "mute": False, "solo": False, "effects": [], "sends": []},
        ],
        "snapshots": [{"id": "default", "name": "Default", "transition_seconds": 0.25, "group_overrides": {}}],
        "parameters": {}, "output": {"channels": "device", "headroom_db": 3.0}, "source_extensions": [],
    }


def attenuation_defaults() -> dict[str, Any]:
    return {
        "audio_version": 1, "spatial_blend": 1.0, "distance_model": "inverse",
        "minimum_distance": 1.0, "maximum_distance": 50.0,
        "volume_curve": [{"distance": 0.0, "value": 1.0}, {"distance": 1.0, "value": 1.0}, {"distance": 50.0, "value": 0.0}],
        "spread_curve": [], "priority_curve": [], "low_pass_curve": [], "high_pass_curve": [],
        "doppler_scale": 1.0, "spread_degrees": 0.0, "focus": {"enabled": False, "focus_azimuth": 30.0, "non_focus_azimuth": 60.0, "volume_scale": 1.0, "priority_scale": 1.0},
        "occlusion": {"enabled": False, "trace_channel": "visibility", "volume_db": -6.0, "low_pass_hz": 1200.0, "attack_seconds": 0.1, "release_seconds": 0.5},
        "reverb_send": {"enabled": True, "minimum": 0.0, "maximum": 1.0, "minimum_distance": 1.0, "maximum_distance": 50.0},
        "shape": {"type": "sphere", "extent": [1.0, 1.0, 1.0], "cone_inner_degrees": 45.0, "cone_outer_degrees": 90.0},
        "source_extensions": [],
    }


def reverb_defaults(*, preset: str = "room") -> dict[str, Any]:
    presets = {
        "room": {"decay_seconds": 1.1, "wet_db": -8.0, "pre_delay_ms": 8.0, "diffusion": 0.8, "density": 0.85},
        "hall": {"decay_seconds": 2.8, "wet_db": -6.0, "pre_delay_ms": 22.0, "diffusion": 0.9, "density": 0.95},
        "cave": {"decay_seconds": 4.5, "wet_db": -4.0, "pre_delay_ms": 35.0, "diffusion": 0.95, "density": 1.0},
        "outdoors": {"decay_seconds": 0.45, "wet_db": -14.0, "pre_delay_ms": 5.0, "diffusion": 0.35, "density": 0.25},
        "underwater": {"decay_seconds": 1.8, "wet_db": -3.0, "pre_delay_ms": 12.0, "diffusion": 0.9, "density": 1.0, "high_cut_hz": 900.0},
    }
    if preset not in presets: raise KeyError(f"Unknown reverb preset: {preset}")
    return {"audio_version": 1, "preset": preset, "algorithm": "algorithmic", "impulse_response_asset_id": "", "dry_db": 0.0, "early_reflections_db": -8.0, "high_cut_hz": 12000.0, "low_cut_hz": 40.0, "modulation": 0.0, **presets[preset], "source_extensions": []}


class AudioAssetService:
    _AUTHORED_TYPES = {"tc.sound_cue", "tc.audio_mixer", "tc.audio_attenuation", "tc.audio_reverb"}

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def clip_settings(self, asset_id: str) -> dict[str, Any]:
        record = self._require(asset_id, {"tc.audio_clip"}); metadata = read_asset_metadata(record.source_path)
        values = audio_clip_defaults(); values.update(deepcopy(dict(metadata.get("audio_settings") or metadata.get("importer_settings") or {}))); return values

    def set_clip_settings(self, asset_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        record = self._require(asset_id, {"tc.audio_clip"}); settings = self.clip_settings(asset_id); settings.update(deepcopy(dict(values or {})))
        metadata = read_asset_metadata(record.source_path)
        write_asset_metadata(record.source_path, asset_id=record.asset_id, type_id=record.asset_type, importer=str(metadata.get("importer") or "builtin:audio"), importer_settings=settings, previous_paths=list(metadata.get("previous_paths") or ()))
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata={**record.metadata, "audio_settings": settings})
        return settings

    def create_sound_cue(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Cues"):
        return self._create("tc.sound_cue", name, sound_cue_defaults(), properties, folder)

    def create_mixer(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Mixers"):
        return self._create("tc.audio_mixer", name, audio_mixer_defaults(), properties, folder)

    def create_attenuation(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Attenuation"):
        return self._create("tc.audio_attenuation", name, attenuation_defaults(), properties, folder)

    def create_reverb(self, name: str, *, preset: str = "room", properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Reverb"):
        return self._create("tc.audio_reverb", name, reverb_defaults(preset=preset), properties, folder)

    def properties(self, asset_id: str) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record and record.asset_type == "tc.audio_clip": return self.clip_settings(asset_id)
        return self._load(asset_id)[1]

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record and record.asset_type == "tc.audio_clip": return self.set_clip_settings(asset_id, values)
        _record, current = self._load(asset_id); authored = {} if replace else current; authored.update(deepcopy(dict(values or {}))); self._save(asset_id, authored); return self.properties(asset_id)

    def validate(self, asset_id: str) -> list[AudioIssue]:
        record = self._require(asset_id, AUDIO_ASSET_TYPES); return validate_audio_asset(record.asset_type, self.properties(asset_id))

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self._require(asset_id, AUDIO_ASSET_TYPES); values = self.properties(asset_id)
        errors = [item.message for item in validate_audio_asset(record.asset_type, values) if item.severity == "error"]
        if errors: raise ValueError("Audio asset is not cookable: " + " ".join(errors))
        if record.asset_type == "tc.audio_clip": payload = compile_audio_clip_payload(record.source_path, values, platform=platform, quality=quality)
        else: payload = compile_audio_payload(record.asset_type, values, platform=platform, quality=quality)
        return self.database.store_derived(asset_id, f"audio_runtime:{platform}:{quality}", payload, metadata={"platform": platform, "quality": quality, "asset_type": record.asset_type}, extension=".tcaudio")

    def convert_unreal(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Audio/Converted/Unreal") -> AudioConversionReceipt:
        return self._convert("unreal", payload, folder)

    def convert_unity(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Audio/Converted/Unity") -> AudioConversionReceipt:
        return self._convert("unity", payload, folder)

    def _convert(self, provider: str, payload: Mapping[str, Any], folder: str | Path) -> AudioConversionReceipt:
        diagnostics: list[AudioIssue] = []
        rows, version = _convert_unreal_audio(payload, diagnostics) if provider == "unreal" else _convert_unity_audio(payload, diagnostics)
        created = []; mapping = {}
        priority = {"tc.audio_mixer": 0, "tc.audio_attenuation": 1, "tc.audio_reverb": 2, "tc.sound_cue": 3}
        for row in sorted(rows, key=lambda value: priority.get(str(value.get("type_id")), 9)):
            type_id = str(row["type_id"]); name = _safe_name(str(row.get("name") or "AudioAsset")); target = self.project_root / Path(folder); suffix = 2; base = name
            extension = {"tc.sound_cue": ".soundcue.tcasset", "tc.audio_mixer": ".audiomixer.tcasset", "tc.audio_attenuation": ".attenuation.tcasset", "tc.audio_reverb": ".reverb.tcasset"}[type_id]
            while (target / f"{name}{extension}").exists(): name, suffix = f"{base}_{suffix}", suffix + 1
            receipt = self.operations.create_asset(type_id, name, folder=folder); self._save(receipt.asset_id, _replace_refs(dict(row.get("properties") or {}), mapping)); created.append(receipt.asset_id); mapping[str(row.get("source_id") or name)] = receipt.asset_id
        for asset_id in created: self._save(asset_id, _replace_refs(self.properties(asset_id), mapping))
        return AudioConversionReceipt(provider, version, tuple(created), tuple(diagnostics), mapping)

    def _create(self, type_id: str, name: str, defaults: dict[str, Any], properties: Mapping[str, Any] | None, folder: str | Path):
        receipt = self.operations.create_asset(type_id, name, folder=folder); defaults.update(deepcopy(dict(properties or {}))); self._save(receipt.asset_id, defaults); return receipt

    def _require(self, asset_id: str, types: Iterable[str]):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown audio asset: {asset_id}")
        if record.asset_type not in set(types): raise ValueError(f"Asset is not a supported audio asset: {asset_id}")
        return record

    def _load(self, asset_id: str):
        record = self._require(asset_id, self._AUTHORED_TYPES)
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Audio source is unreadable: {record.source_path}") from exc
        return record, _normalize_audio(record.asset_type, dict(payload.get("properties") or {}))

    def _save(self, asset_id: str, properties: Mapping[str, Any]) -> None:
        record = self._require(asset_id, self._AUTHORED_TYPES); values = _normalize_audio(record.asset_type, properties)
        payload = json.loads(record.source_path.read_text(encoding="utf-8")); payload["schema"] = _schema(record.asset_type); payload["properties"] = values
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp"); temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, record.source_path)
        edges = [(value, kind) for value, kind in _audio_references(record.asset_type, values) if self.database.asset(value) is not None and value != asset_id]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata, dependencies=edges)


def validate_audio_asset(type_id: str, values: Mapping[str, Any]) -> list[AudioIssue]:
    issues: list[AudioIssue] = []
    if type_id == "tc.audio_clip":
        if str(values.get("load_mode")) not in {"decompress_on_load", "compressed_in_memory", "stream"}: issues.append(AudioIssue("error", "invalid_load_mode", "Audio Clip load mode is invalid.", "load_mode"))
        if not 0.0 <= float(values.get("quality", 0.8)) <= 1.0: issues.append(AudioIssue("error", "invalid_quality", "Audio compression quality must be between zero and one.", "quality"))
        if bool(values.get("loop")) and float(values.get("loop_end_seconds", 0.0)) and float(values.get("loop_end_seconds", 0.0)) <= float(values.get("loop_start_seconds", 0.0)): issues.append(AudioIssue("error", "invalid_loop_region", "Loop end must occur after loop start.", "loop"))
    elif type_id == "tc.sound_cue":
        graph = dict(values.get("graph") or {}); nodes = [dict(row) for row in graph.get("nodes") or []]; ids = [str(row.get("id") or "") for row in nodes]
        if len(ids) != len(set(ids)): issues.append(AudioIssue("error", "duplicate_node", "Sound Cue node IDs must be unique.", "graph"))
        outputs = [row for row in nodes if str(row.get("type")) == "output"]
        if len(outputs) != 1: issues.append(AudioIssue("error", "output_count", "Sound Cue requires exactly one Output node.", "graph"))
        for node in nodes:
            if str(node.get("type") or "") not in CUE_NODE_TYPES: issues.append(AudioIssue("warning", "unknown_cue_node", f"Unknown Sound Cue node '{node.get('type')}' is preserved.", str(node.get("id") or "")))
        concurrency = dict(values.get("concurrency") or {})
        if int(concurrency.get("maximum_voices", 0)) <= 0: issues.append(AudioIssue("error", "invalid_voice_limit", "Concurrency maximum voices must be greater than zero.", "concurrency"))
        if str(concurrency.get("resolution")) not in VOICE_RESOLUTIONS: issues.append(AudioIssue("error", "invalid_voice_resolution", "Concurrency resolution policy is invalid.", "concurrency"))
    elif type_id == "tc.audio_mixer":
        groups = [dict(row) for row in values.get("groups") or []]; ids = [str(row.get("id") or "") for row in groups]
        if "master" not in ids: issues.append(AudioIssue("error", "missing_master", "Audio Mixer requires a master group.", "groups"))
        if len(ids) != len(set(ids)): issues.append(AudioIssue("error", "duplicate_group", "Audio Mixer group IDs must be unique.", "groups"))
        parents = {str(row.get("id")): str(row.get("parent_id") or "") for row in groups}
        for group in groups:
            subject = str(group.get("name") or group.get("id")); parent = str(group.get("parent_id") or "")
            if parent and parent not in ids: issues.append(AudioIssue("error", "unknown_parent", f"Mixer group '{subject}' references an unknown parent.", subject))
            for effect in group.get("effects") or []:
                if str(dict(effect).get("type") or "") not in DSP_EFFECTS: issues.append(AudioIssue("warning", "unknown_dsp", f"Mixer effect '{dict(effect).get('type')}' is preserved but unsupported.", subject))
        for group_id in ids:
            seen = set(); cursor = group_id
            while cursor:
                if cursor in seen: issues.append(AudioIssue("error", "mixer_cycle", "Audio Mixer routing hierarchy contains a cycle.", group_id)); break
                seen.add(cursor); cursor = parents.get(cursor, "")
    elif type_id == "tc.audio_attenuation":
        minimum = float(values.get("minimum_distance", 0.0)); maximum = float(values.get("maximum_distance", 0.0))
        if minimum < 0 or maximum <= minimum: issues.append(AudioIssue("error", "invalid_distance", "Maximum attenuation distance must be greater than minimum distance.", "distance"))
        if not 0.0 <= float(values.get("spatial_blend", 1.0)) <= 1.0: issues.append(AudioIssue("error", "invalid_spatial_blend", "Spatial blend must be between zero and one.", "spatial_blend"))
    elif type_id == "tc.audio_reverb":
        if float(values.get("decay_seconds", 0.0)) <= 0: issues.append(AudioIssue("error", "invalid_decay", "Reverb decay time must be greater than zero.", "decay_seconds"))
        if str(values.get("algorithm")) == "convolution" and not str(values.get("impulse_response_asset_id") or ""): issues.append(AudioIssue("error", "missing_impulse", "Convolution reverb requires an impulse-response Audio Clip.", "impulse_response_asset_id"))
    return issues


def compile_audio_clip_payload(source_path: Path, settings: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    source = source_path.read_bytes(); header = json.dumps({"schema": AUDIO_RUNTIME_SCHEMA, "asset_type": "tc.audio_clip", "platform": platform, "quality": quality, "source_extension": source_path.suffix.casefold(), "source_hash": hashlib.sha256(source).hexdigest(), "settings": dict(settings)}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return b"TCAUDIO1" + struct.pack("<I", len(header)) + header + source


def compile_audio_payload(type_id: str, values: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    normalized = _normalize_audio(type_id, values); runtime = {"schema": AUDIO_RUNTIME_SCHEMA, "asset_type": type_id, "platform": platform, "quality": quality}
    if type_id == "tc.sound_cue":
        graph = dict(normalized.get("graph") or {}); nodes = [dict(row) for row in graph.get("nodes") or []]; runtime["operations"] = [{"index": index, "id": str(row.get("id")), "opcode": str(row.get("type")), "parameters": dict(row.get("parameters") or {})} for index, row in enumerate(nodes)]; runtime["connections"] = graph.get("connections") or []
        runtime.update({key: normalized.get(key) for key in ("volume", "pitch", "priority", "parameters", "attenuation_asset_id", "mixer_group_id", "submix_sends", "concurrency", "spatialization", "source_effects", "loop")})
    elif type_id == "tc.audio_mixer":
        runtime["groups"] = normalized.get("groups"); runtime["snapshots"] = normalized.get("snapshots"); runtime["parameters"] = normalized.get("parameters"); runtime["output"] = normalized.get("output")
    else: runtime.update(deepcopy(normalized))
    return json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_audio(type_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    authored = deepcopy(dict(values or {})); defaults = {"tc.sound_cue": sound_cue_defaults, "tc.audio_mixer": audio_mixer_defaults, "tc.audio_attenuation": attenuation_defaults, "tc.audio_reverb": reverb_defaults}[type_id](); defaults.update(authored); defaults["audio_version"] = 1; return defaults


def _audio_references(type_id: str, values: Mapping[str, Any]) -> set[tuple[str, str]]:
    refs = set()
    if type_id == "tc.sound_cue":
        attenuation = str(values.get("attenuation_asset_id") or "")
        if attenuation: refs.add((attenuation, "audio_attenuation"))
        for node in dict(values.get("graph") or {}).get("nodes") or []:
            for key in ("clip_asset_id", "cue_asset_id"):
                value = str(dict(dict(node).get("parameters") or {}).get(key) or "")
                if value: refs.add((value, "audio_source"))
        for send in values.get("submix_sends") or []:
            value = str(dict(send).get("reverb_asset_id") or "")
            if value: refs.add((value, "audio_reverb"))
    elif type_id == "tc.audio_reverb":
        value = str(values.get("impulse_response_asset_id") or "")
        if value: refs.add((value, "impulse_response"))
    return refs


def _convert_unreal_audio(payload: Mapping[str, Any], diagnostics: list[AudioIssue]) -> tuple[list[dict[str, Any]], str]:
    data = dict(payload or {}); rows = []; version = str(data.get("engine_version") or "unknown")
    for item in data.get("submixes") or []:
        source = dict(item); mixer = audio_mixer_defaults(); mixer["groups"] = deepcopy(list(source.get("groups") or mixer["groups"])); rows.append({"source_id": str(source.get("object_path") or source.get("name")), "name": str(source.get("name") or "AudioMixer"), "type_id": "tc.audio_mixer", "properties": mixer})
    for item in data.get("attenuation_settings") or []:
        source = dict(item); values = attenuation_defaults(); values.update({"spatial_blend": 1.0 if source.get("spatialize", True) else 0.0, "distance_model": str(source.get("distance_model") or "inverse").casefold(), "minimum_distance": float(source.get("minimum_distance") or source.get("inner_radius") or 1.0), "maximum_distance": float(source.get("maximum_distance") or source.get("falloff_distance") or 50.0), "occlusion": deepcopy(dict(source.get("occlusion") or values["occlusion"])), "reverb_send": deepcopy(dict(source.get("reverb_send") or values["reverb_send"]))}); rows.append({"source_id": str(source.get("object_path") or source.get("name")), "name": str(source.get("name") or "Attenuation"), "type_id": "tc.audio_attenuation", "properties": values})
    for item in data.get("sound_cues") or data.get("metasounds") or []:
        source = dict(item); cue = sound_cue_defaults(); nodes = []
        for index, node_value in enumerate(source.get("nodes") or []):
            node = dict(node_value); kind = str(node.get("type") or node.get("class") or "node").casefold().replace("soundnode", "").replace("metasound", "").replace(" ", "_"); aliases = {"waveplayer": "wave_player", "random": "random", "concatenator": "sequence", "mixer": "mixer", "modulator": "modulator", "switch": "switch", "delay": "delay", "looping": "loop", "attenuation": "attenuation", "output": "output"}; kind = aliases.get(kind, kind)
            if kind not in CUE_NODE_TYPES: diagnostics.append(AudioIssue("warning", "unsupported_unreal_audio_node", f"Unreal audio node '{node.get('type')}' was preserved.", str(node.get("name") or index)))
            nodes.append({"id": str(node.get("id") or f"node_{index}"), "type": kind, "parameters": deepcopy(dict(node.get("parameters") or {})), "source_extension": deepcopy(node) if kind not in CUE_NODE_TYPES else {}})
        cue["graph"] = {"nodes": nodes or cue["graph"]["nodes"], "connections": deepcopy(list(source.get("connections") or []))}; cue["attenuation_asset_id"] = str(source.get("attenuation") or ""); cue["concurrency"].update(deepcopy(dict(source.get("concurrency") or {}))); cue["source_extensions"] = deepcopy(list(source.get("source_extensions") or [])); rows.append({"source_id": str(source.get("object_path") or source.get("name")), "name": str(source.get("name") or "SoundCue"), "type_id": "tc.sound_cue", "properties": cue})
    return rows, version


def _convert_unity_audio(payload: Mapping[str, Any], diagnostics: list[AudioIssue]) -> tuple[list[dict[str, Any]], str]:
    data = dict(payload or {}); rows = []; version = str(data.get("unity_version") or "unknown")
    for item in data.get("audio_mixers") or []:
        source = dict(item); mixer = audio_mixer_defaults(); mixer["groups"] = deepcopy(list(source.get("groups") or mixer["groups"])); mixer["snapshots"] = deepcopy(list(source.get("snapshots") or mixer["snapshots"])); rows.append({"source_id": str(source.get("guid") or source.get("name")), "name": str(source.get("name") or "AudioMixer"), "type_id": "tc.audio_mixer", "properties": mixer})
    for item in data.get("audio_sources") or data.get("random_containers") or []:
        source = dict(item); cue = sound_cue_defaults(); clips = list(source.get("clips") or ([source.get("clip")] if source.get("clip") else [])); nodes = [{"id": f"clip_{index}", "type": "wave_player", "parameters": {"clip_asset_id": str(value.get("guid") if isinstance(value, Mapping) else value)}} for index, value in enumerate(clips)]
        root = "random" if len(nodes) > 1 else "mixer"; nodes.extend([{"id": root, "type": "random" if len(nodes) > 1 else "mixer", "parameters": {}}, {"id": "output", "type": "output", "parameters": {}}]); connections = [{"source": node["id"], "target": root} for node in nodes if node["type"] == "wave_player"] + [{"source": root, "target": "output"}]
        cue["graph"] = {"nodes": nodes, "connections": connections}; cue["volume"] = float(source.get("volume", 1.0)); cue["pitch"] = float(source.get("pitch", 1.0)); cue["priority"] = 1.0 - min(255, max(0, int(source.get("priority", 128)))) / 255.0; cue["spatialization"] = {"enabled": float(source.get("spatial_blend", source.get("spatialBlend", 0.0))) > 0, "plugin": "builtin", "binaural": False}; cue["submix_sends"] = [{"mixer_group_id": str(source.get("output_group") or "master"), "level": 1.0}]; cue["source_extensions"] = deepcopy(list(source.get("filters") or [])); rows.append({"source_id": str(source.get("guid") or source.get("id") or source.get("name")), "name": str(source.get("name") or "AudioSource"), "type_id": "tc.sound_cue", "properties": cue})
        if source.get("spatial_blend", source.get("spatialBlend", 0.0)):
            attenuation = attenuation_defaults(); attenuation.update({"spatial_blend": float(source.get("spatial_blend", source.get("spatialBlend", 1.0))), "minimum_distance": float(source.get("minimum_distance", source.get("minDistance", 1.0))), "maximum_distance": float(source.get("maximum_distance", source.get("maxDistance", 50.0))), "doppler_scale": float(source.get("doppler_level", source.get("dopplerLevel", 1.0))), "spread_degrees": float(source.get("spread", 0.0))}); attenuation_id = str(source.get("guid") or source.get("id") or source.get("name")) + ":attenuation"; cue["attenuation_asset_id"] = attenuation_id; rows.append({"source_id": attenuation_id, "name": str(source.get("name") or "AudioSource") + "_Attenuation", "type_id": "tc.audio_attenuation", "properties": attenuation})
    return rows, version


def _replace_refs(value: Any, mapping: Mapping[str, str]) -> Any:
    if isinstance(value, dict): return {key: (mapping.get(str(item), item) if key.endswith("_asset_id") else _replace_refs(item, mapping)) for key, item in value.items()}
    if isinstance(value, list): return [_replace_refs(item, mapping) for item in value]
    return value


def _schema(type_id: str) -> str:
    return {"tc.sound_cue": SOUND_CUE_SCHEMA, "tc.audio_mixer": AUDIO_MIXER_SCHEMA, "tc.audio_attenuation": ATTENUATION_SCHEMA, "tc.audio_reverb": REVERB_SCHEMA}[type_id]


def _safe_name(value: str) -> str:
    cleaned = "_".join(part for part in "".join(char if char.isalnum() or char in "_.-" else " " for char in value).split() if part).strip("._"); return cleaned or "AudioAsset"


__all__ = ["AUDIO_RUNTIME_SCHEMA", "SOUND_CUE_SCHEMA", "AUDIO_MIXER_SCHEMA", "ATTENUATION_SCHEMA", "REVERB_SCHEMA", "AUDIO_ASSET_TYPES", "CUE_NODE_TYPES", "DSP_EFFECTS", "VOICE_RESOLUTIONS", "AudioIssue", "AudioConversionReceipt", "AudioAssetService", "audio_clip_defaults", "sound_cue_defaults", "audio_mixer_defaults", "attenuation_defaults", "reverb_defaults", "validate_audio_asset", "compile_audio_clip_payload", "compile_audio_payload"]
