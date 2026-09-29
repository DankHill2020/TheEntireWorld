"""Production VFX asset authoring, validation, profiling, and deterministic cooking."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService
from tech_connector.game_engine.runtime.tc_effect_system_service import QUALITY_PROFILES, create_effect_preset, effect_preset_names


EFFECT_SYSTEM_SCHEMA = "tech_connector.asset.effect_system.v2"
EFFECT_RUNTIME_SCHEMA = "tech_connector.runtime.effect_system.v1"
EFFECT_PHASES = (
    "system_spawn", "system_update", "emitter_spawn", "emitter_update",
    "particle_spawn", "particle_update", "event_handler", "render",
)
SIMULATION_TARGETS = ("auto", "cpu", "gpu")
RENDERER_TYPES = ("sprite", "mesh", "ribbon", "beam", "light", "decal", "volume", "volume_sprite", "metaball", "point")

# phase(s), relative ALU, texture reads, GPU support, description
MODULE_LIBRARY: dict[str, tuple[tuple[str, ...], int, int, bool, str]] = {
    "initialize": (("particle_spawn",), 4, 0, True, "Lifetime, position, color, size, and initial attributes."),
    "spawn_rate": (("emitter_update",), 2, 0, True, "Continuous particles-per-second spawning."),
    "spawn_burst": (("emitter_spawn", "emitter_update"), 2, 0, True, "Timed or event-driven particle bursts."),
    "shape_location": (("particle_spawn",), 8, 0, True, "Point, sphere, box, cone, cylinder, mesh, or texture sampling."),
    "velocity": (("particle_spawn", "particle_update"), 3, 0, True, "Set or add particle velocity."),
    "add_velocity": (("particle_spawn", "particle_update"), 3, 0, True, "Add directional or randomized particle velocity."),
    "gravity": (("particle_update",), 3, 0, True, "Gravity acceleration."),
    "drag": (("particle_update",), 4, 0, True, "Velocity damping."),
    "curl_noise": (("particle_update",), 26, 3, True, "Divergence-free turbulent noise force."),
    "vortex": (("particle_update",), 12, 0, True, "Axis-aligned vortex force."),
    "point_attractor": (("particle_update",), 10, 0, True, "Attraction or repulsion around a point."),
    "vector_field": (("particle_update",), 12, 1, True, "Sample a vector-field texture or volume."),
    "collision": (("particle_update",), 24, 2, True, "Depth, distance-field, or analytic collision."),
    "surface_interaction": (("particle_update",), 24, 2, True, "Collide, slide, stick, or bounce against surfaces."),
    "kill_volume": (("particle_update",), 4, 0, True, "Kill particles inside or outside a volume."),
    "color_over_life": (("particle_update",), 4, 1, True, "Evaluate an HDR color gradient over normalized age."),
    "size_over_life": (("particle_update",), 3, 1, True, "Evaluate scale curves over normalized age."),
    "rotation_over_life": (("particle_update",), 3, 0, True, "Integrate angular velocity."),
    "rotation": (("particle_update",), 3, 0, True, "Integrate particle rotation."),
    "camera_offset": (("particle_update",), 4, 0, True, "Camera-facing depth offset."),
    "event_generator": (("event_handler",), 8, 0, False, "Publish spawn, death, collision, or custom events."),
    "event_receiver": (("event_handler",), 8, 0, False, "Consume events from another emitter."),
    "data_channel_read": (("particle_spawn", "particle_update"), 8, 1, True, "Read structured gameplay/VFX data."),
    "data_channel_write": (("emitter_update", "event_handler"), 8, 1, False, "Publish structured data for other systems."),
    "subgraph": (("particle_spawn", "particle_update", "event_handler"), 6, 0, True, "Reusable versioned module graph."),
}


@dataclass(frozen=True)
class EffectIssue:
    severity: str
    code: str
    message: str
    subject: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class EffectCostEstimate:
    emitter_count: int
    maximum_particles: int
    estimated_live_particles: int
    alu_operations_per_second: int
    texture_reads_per_second: int
    estimated_memory_bytes: int
    cpu_event_emitters: int
    status: str
    recommendations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EffectConversionReceipt:
    provider: str
    source_version: str
    asset_ids: tuple[str, ...]
    diagnostics: tuple[EffectIssue, ...]
    source_to_asset: dict[str, str]

    @property
    def succeeded(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "source_version": self.source_version, "asset_ids": list(self.asset_ids), "succeeded": self.succeeded, "diagnostics": [item.to_dict() for item in self.diagnostics], "source_to_asset": dict(self.source_to_asset)}


def effect_system_defaults(*, preset: str = "sparks", quality: str = "high", seed: int = 1) -> dict[str, Any]:
    system = create_effect_preset(preset, quality=quality, seed=seed).to_dict()
    values = {
        "effect_version": 2, "preset": str(preset), "duration": 5.0, "loop": False,
        "warmup": {"seconds": 0.0, "step_seconds": 1.0 / 30.0},
        "fixed_bounds": {"enabled": False, "minimum": [-5.0, -5.0, -5.0], "maximum": [5.0, 5.0, 5.0]},
        "parameters": deepcopy(system.get("parameters") or {}),
        "emitters": [_normalize_emitter(row, index) for index, row in enumerate(system.get("emitters") or [])],
        "event_bindings": deepcopy(system.get("event_bindings") or []),
        "data_channels": deepcopy(system.get("data_channels") or {}),
        "data_channel_bindings": deepcopy(system.get("data_channel_bindings") or []),
        "subgraphs": deepcopy(system.get("subgraphs") or {}),
        "scalability": str(quality), "quality_overrides": _default_quality_overrides(),
        "simulation": {"backend": str(system.get("backend_preference") or "auto"), "deterministic": True, "seed": int(seed), "fixed_time_step": 1.0 / 60.0, "maximum_substeps": 4},
        "pooling": {"enabled": True, "prewarm_instances": 0, "maximum_instances": 128, "reclaim_delay": 0.25},
        "source_extensions": [],
    }
    return normalize_effect_properties(values)


def normalize_effect_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    values = deepcopy(dict(properties or {}))
    defaults = {
        "effect_version": 2, "preset": "custom", "duration": 5.0, "loop": True,
        "warmup": {"seconds": 0.0, "step_seconds": 1.0 / 30.0},
        "fixed_bounds": {"enabled": False, "minimum": [-5.0, -5.0, -5.0], "maximum": [5.0, 5.0, 5.0]},
        "parameters": {}, "emitters": [], "event_bindings": [], "data_channels": {},
        "data_channel_bindings": [], "subgraphs": {}, "scalability": "auto",
        "quality_overrides": _default_quality_overrides(),
        "simulation": {"backend": "auto", "deterministic": True, "seed": 1, "fixed_time_step": 1.0 / 60.0, "maximum_substeps": 4},
        "pooling": {"enabled": True, "prewarm_instances": 0, "maximum_instances": 128, "reclaim_delay": 0.25},
        "source_extensions": [],
    }
    defaults.update(values)
    defaults["effect_version"] = 2
    defaults["emitters"] = [_normalize_emitter(row, index) for index, row in enumerate(values.get("emitters") or [])]
    return defaults


class EffectAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def presets(self) -> tuple[str, ...]:
        return tuple(effect_preset_names())

    def module_library(self) -> dict[str, dict[str, Any]]:
        return {name: {"phases": list(spec[0]), "alu_cost": spec[1], "texture_reads": spec[2], "gpu_supported": spec[3], "description": spec[4]} for name, spec in MODULE_LIBRARY.items()}

    def create(self, name: str, *, preset: str = "sparks", quality: str = "high", seed: int = 1,
               folder: str | Path = "Assets/Effects"):
        receipt = self.operations.create_asset("tc.effect_system", name, folder=folder)
        self._save(receipt.asset_id, effect_system_defaults(preset=preset, quality=quality, seed=seed))
        return receipt

    def apply_preset(self, asset_id: str, preset: str, *, preserve_parameters: bool = True) -> dict[str, Any]:
        _record, authored = self._load(asset_id)
        values = effect_system_defaults(preset=preset, quality=str(authored.get("scalability") or "high"), seed=int(dict(authored.get("simulation") or {}).get("seed", 1)))
        if preserve_parameters: values["parameters"] = deepcopy(dict(authored.get("parameters") or {}))
        self._save(asset_id, values)
        return self.properties(asset_id)

    def properties(self, asset_id: str) -> dict[str, Any]:
        return self._load(asset_id)[1]

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        _record, current = self._load(asset_id); authored = {} if replace else current
        authored.update(deepcopy(dict(values or {}))); self._save(asset_id, authored)
        return self.properties(asset_id)

    def validate(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> list[EffectIssue]:
        return validate_effect_properties(self.properties(asset_id), platform=platform, quality=quality)

    def estimate(self, asset_id: str, *, quality: str = "high") -> EffectCostEstimate:
        return estimate_effect_cost(self.properties(asset_id), quality=quality)

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        payload = compile_effect_payload(self.properties(asset_id), platform=platform, quality=quality)
        return self.database.store_derived(asset_id, f"effect_runtime:{platform}:{quality}", payload,
            metadata={"platform": platform, "quality": quality, "schema": EFFECT_RUNTIME_SCHEMA}, extension=".tcfxbin")

    def convert_unreal(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Effects/Converted/Unreal") -> EffectConversionReceipt:
        return self._convert("unreal", payload, folder)

    def convert_unity(self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Effects/Converted/Unity") -> EffectConversionReceipt:
        return self._convert("unity", payload, folder)

    def _convert(self, provider: str, payload: Mapping[str, Any], folder: str | Path) -> EffectConversionReceipt:
        provider = str(provider).casefold(); diagnostics: list[EffectIssue] = []
        if provider == "unreal": rows, version = _convert_unreal_effects(payload, diagnostics)
        elif provider == "unity": rows, version = _convert_unity_effects(payload, diagnostics)
        else: raise ValueError(f"Unsupported effect provider: {provider}")
        created: list[str] = []; mapping: dict[str, str] = {}
        target_folder = self.project_root / Path(folder)
        for row in rows:
            base = _safe_effect_name(str(row.get("name") or "ConvertedEffect")); name = base; suffix = 2
            while (target_folder / f"{name}.tcfx").exists(): name, suffix = f"{base}_{suffix}", suffix + 1
            receipt = self.operations.create_asset("tc.effect_system", name, folder=folder)
            values = normalize_effect_properties(dict(row.get("properties") or {})); values["source_extensions"] = deepcopy(list(row.get("source_extensions") or []))
            self._save(receipt.asset_id, values); created.append(receipt.asset_id)
            mapping[str(row.get("source_id") or name)] = receipt.asset_id
        return EffectConversionReceipt(provider, version, tuple(created), tuple(diagnostics), mapping)

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown effect asset: {asset_id}")
        if record.asset_type != "tc.effect_system": raise ValueError(f"Asset is not an Effect System: {asset_id}")
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Effect source is unreadable: {record.source_path}") from exc
        return record, normalize_effect_properties(dict(payload.get("properties") or {}))

    def _save(self, asset_id: str, properties: Mapping[str, Any]) -> None:
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown effect asset: {asset_id}")
        values = normalize_effect_properties(properties)
        payload = json.loads(record.source_path.read_text(encoding="utf-8")); payload["schema"] = EFFECT_SYSTEM_SCHEMA; payload["properties"] = values
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, record.source_path)
        references = _effect_references(values)
        edges = [(value, kind) for value, kind in references if self.database.asset(value) is not None and value != asset_id]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata, dependencies=edges)


def validate_effect_properties(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> list[EffectIssue]:
    values = normalize_effect_properties(properties); issues: list[EffectIssue] = []
    if float(values.get("duration", 0.0) or 0.0) <= 0: issues.append(EffectIssue("error", "invalid_duration", "Effect duration must be greater than zero.", "duration"))
    emitters = [dict(row) for row in values.get("emitters") or []]; ids = [str(row.get("id") or "") for row in emitters]
    if not emitters: issues.append(EffectIssue("warning", "no_emitters", "Effect System has no emitters.", "emitters", "Add an emitter or apply a preset."))
    if len(ids) != len(set(ids)): issues.append(EffectIssue("error", "duplicate_emitter_id", "Emitter IDs must be unique.", "emitters"))
    for index, emitter in enumerate(emitters):
        subject = str(emitter.get("name") or f"Emitter {index + 1}"); target = str(emitter.get("simulation_target") or "auto")
        if target not in SIMULATION_TARGETS: issues.append(EffectIssue("error", "invalid_simulation_target", f"{subject} has an invalid simulation target.", subject))
        if int(emitter.get("capacity", 0) or 0) <= 0: issues.append(EffectIssue("error", "invalid_capacity", f"{subject} capacity must be greater than zero.", subject))
        if float(emitter.get("spawn_rate", 0.0) or 0.0) < 0: issues.append(EffectIssue("error", "negative_spawn_rate", f"{subject} spawn rate cannot be negative.", subject))
        modules = [dict(row) for row in emitter.get("modules") or []]
        if not modules: issues.append(EffectIssue("error", "missing_modules", f"{subject} has no executable modules.", subject))
        for module_index, module in enumerate(modules):
            opcode = str(module.get("type") or ""); phase = str(module.get("phase") or "particle_update")
            if opcode not in MODULE_LIBRARY: issues.append(EffectIssue("warning", "unknown_module", f"{subject} module '{opcode}' is preserved but has no native compiler implementation.", f"{subject}.modules[{module_index}]")); continue
            allowed, _alu, _tex, gpu_supported, _description = MODULE_LIBRARY[opcode]
            if phase not in allowed: issues.append(EffectIssue("error", "invalid_module_phase", f"Module '{opcode}' cannot run in {phase}.", f"{subject}.modules[{module_index}]", f"Move it to {', '.join(allowed)}."))
            if target == "gpu" and not gpu_supported: issues.append(EffectIssue("error", "cpu_only_module", f"GPU emitter '{subject}' contains CPU-only module '{opcode}'.", f"{subject}.modules[{module_index}]", "Switch the emitter to CPU or replace the module."))
        renderers = [dict(row) for row in emitter.get("renderers") or []]
        if not renderers: issues.append(EffectIssue("warning", "no_renderer", f"{subject} simulates but has no renderer.", subject))
        for renderer in renderers:
            if str(renderer.get("type") or "") not in RENDERER_TYPES: issues.append(EffectIssue("error", "invalid_renderer", f"{subject} uses unsupported renderer '{renderer.get('type')}'.", subject))
    known = set(ids)
    for binding in values.get("event_bindings") or []:
        row = dict(binding); source = str(row.get("source_emitter") or ""); target = str(row.get("target_emitter") or "")
        if source not in known or target not in known: issues.append(EffectIssue("error", "invalid_event_binding", "Event binding references an unknown emitter.", f"{source} -> {target}"))
        source_row = next((item for item in emitters if str(item.get("id")) == source), {})
        if str(source_row.get("simulation_target") or "auto") == "gpu": issues.append(EffectIssue("error", "gpu_cpu_event", "CPU event bindings cannot originate from a GPU emitter.", source, "Use a GPU data channel/event path or switch the source emitter to CPU."))
    estimate = estimate_effect_cost(values, quality=quality)
    if estimate.status == "over_budget": issues.append(EffectIssue("warning", "over_budget", "Estimated effect cost exceeds the selected quality budget.", quality, "Reduce capacity/spawn rate, consolidate emitters, or add quality overrides."))
    if str(platform).casefold() in {"mobile", "android", "ios"} and any(str(row.get("simulation_target")) == "gpu" and any(str(item.get("type")) == "volume" for item in row.get("renderers") or []) for row in emitters):
        issues.append(EffectIssue("warning", "mobile_volume", "GPU volume rendering may be unavailable or expensive on the selected mobile target.", platform))
    return issues


def estimate_effect_cost(properties: Mapping[str, Any], *, quality: str = "high") -> EffectCostEstimate:
    values = normalize_effect_properties(properties); profile = QUALITY_PROFILES.get(str(quality).casefold(), QUALITY_PROFILES["high"])
    particles = 0; alu = 0; textures = 0; memory = 0; cpu_events = 0
    for emitter in values.get("emitters") or []:
        row = dict(emitter); capacity = max(0, int(row.get("capacity", 0) or 0)); lifetime = max(0.01, float(row.get("lifetime", row.get("duration", 1.0)) or 1.0))
        live = min(capacity, round(max(0.0, float(row.get("spawn_rate", 0.0))) * lifetime + sum(int(item.get("count", 0)) for item in row.get("bursts") or [])))
        particles += live; memory += capacity * 96
        for module in row.get("modules") or []:
            spec = MODULE_LIBRARY.get(str(dict(module).get("type") or ""))
            if spec: alu += live * spec[1] * 60; textures += live * spec[2] * 60
            if str(dict(module).get("type") or "") in {"event_generator", "event_receiver", "data_channel_write"}: cpu_events += 1
    maximum = int(profile.max_particles); utilization = particles / max(1, maximum)
    status = "within_target" if utilization <= 0.8 else "near_limit" if utilization <= 1.0 else "over_budget"
    recommendations = []
    if particles > maximum: recommendations.append("Lower emitter capacity/spawn rate or author a quality override.")
    if len(values.get("emitters") or []) > 8: recommendations.append("Consolidate compatible emitters to reduce per-instance overhead.")
    if cpu_events: recommendations.append("Keep event-heavy emitters on CPU or replace cross-emitter events with data channels.")
    return EffectCostEstimate(len(values.get("emitters") or []), maximum, particles, alu, textures, memory, cpu_events, status, tuple(recommendations))


def compile_effect_payload(properties: Mapping[str, Any], *, platform: str, quality: str) -> bytes:
    values = normalize_effect_properties(properties); issues = validate_effect_properties(values, platform=platform, quality=quality)
    errors = [item.message for item in issues if item.severity == "error"]
    if errors: raise ValueError("Effect System is not cookable: " + " ".join(errors))
    override = deepcopy(dict(dict(values.get("quality_overrides") or {}).get(str(quality).casefold()) or {}))
    spawn_scale = float(override.get("spawn_scale", 1.0)); capacity_scale = float(override.get("capacity_scale", 1.0)); disabled = set(override.get("disabled_emitters") or [])
    emitters = []
    for emitter in values.get("emitters") or []:
        row = deepcopy(dict(emitter)); row["enabled"] = bool(row.get("enabled", True)) and str(row.get("id")) not in disabled
        row["spawn_rate"] = float(row.get("spawn_rate", 0.0)) * spawn_scale; row["capacity"] = max(1, round(int(row.get("capacity", 1)) * capacity_scale))
        stacks = {phase: [] for phase in EFFECT_PHASES}
        for module_index, module in enumerate(row.pop("modules", [])):
            item = deepcopy(dict(module)); item["operation_index"] = module_index; stacks.setdefault(str(item.get("phase") or "particle_update"), []).append(item)
        row["module_stacks"] = stacks; emitters.append(row)
    parameters = [{"slot": index, "name": name, **dict(spec if isinstance(spec, Mapping) else {"type": "float", "default": spec})} for index, (name, spec) in enumerate(sorted(dict(values.get("parameters") or {}).items()))]
    runtime = {"schema": EFFECT_RUNTIME_SCHEMA, "platform": str(platform), "quality": str(quality), "duration": values["duration"], "loop": values["loop"], "warmup": values["warmup"], "fixed_bounds": values["fixed_bounds"], "parameters": parameters, "emitters": emitters, "event_bindings": values["event_bindings"], "data_channels": values["data_channels"], "data_channel_bindings": values["data_channel_bindings"], "simulation": values["simulation"], "pooling": values["pooling"], "cost": estimate_effect_cost(values, quality=quality).to_dict()}
    return json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _convert_unreal_effects(payload: Mapping[str, Any], diagnostics: list[EffectIssue]) -> tuple[list[dict[str, Any]], str]:
    data = deepcopy(dict(payload or {})); version = str(data.get("engine_version") or data.get("version") or "unknown")
    systems = data.get("niagara_systems") or data.get("systems") or ([data] if data.get("emitters") else [])
    rows = []
    for system in systems:
        source = dict(system); properties = normalize_effect_properties({
            "preset": "converted_unreal", "duration": source.get("duration", 5.0), "loop": source.get("loop", True),
            "parameters": source.get("parameters") or {}, "event_bindings": source.get("event_bindings") or [],
            "emitters": [_unreal_emitter(value, index, diagnostics) for index, value in enumerate(source.get("emitters") or [])],
            "scalability": source.get("scalability", "auto"),
        })
        rows.append({"source_id": str(source.get("object_path") or source.get("id") or source.get("name")), "name": str(source.get("name") or "NiagaraSystem"), "properties": properties, "source_extensions": deepcopy(list(source.get("source_extensions") or []))})
    return rows, version


def _unreal_emitter(value: Mapping[str, Any], index: int, diagnostics: list[EffectIssue]) -> dict[str, Any]:
    row = dict(value); modules = []
    group_aliases = {"emitter_spawn": "emitter_spawn", "emitter_update": "emitter_update", "particle_spawn": "particle_spawn", "particle_update": "particle_update", "event_handler": "event_handler", "render": "render"}
    for module_index, item in enumerate(row.get("modules") or row.get("stack") or []):
        source = dict(item); kind = str(source.get("type") or source.get("name") or "module"); normalized = kind.casefold().replace(" ", "_")
        aliases = {"initialize_particle": "initialize", "add_velocity": "add_velocity", "solve_forces_and_velocity": "velocity", "gravity_force": "gravity", "collision": "collision", "color": "color_over_life", "scale_sprite_size": "size_over_life", "generate_location_event": "event_generator"}
        opcode = aliases.get(normalized, normalized); phase = group_aliases.get(str(source.get("group") or source.get("phase") or "particle_update").casefold().replace(" ", "_"), "particle_update")
        extension = []
        if opcode not in MODULE_LIBRARY:
            extension.append(deepcopy(source)); diagnostics.append(EffectIssue("warning", "unsupported_niagara_module", f"Niagara module '{kind}' was preserved and needs a native replacement.", str(row.get("name") or f"Emitter {index + 1}")))
        modules.append({"id": str(source.get("id") or f"module_{module_index}"), "type": opcode, "phase": phase, "enabled": bool(source.get("enabled", True)), "parameters": deepcopy(dict(source.get("parameters") or {})), "version": int(source.get("version", 1)), "source_extensions": extension})
    renderers = []
    for renderer_index, item in enumerate(row.get("renderers") or []):
        source = dict(item); kind = str(source.get("type") or "sprite").casefold().replace("renderer", "").replace("_", "").strip()
        aliases = {"spriterenderer": "sprite", "meshrenderer": "mesh", "ribbonrenderer": "ribbon", "lightrenderer": "light", "componentrenderer": "mesh"}; kind = aliases.get(str(source.get("type") or "").casefold().replace(" ", ""), kind)
        renderers.append({"id": str(source.get("id") or f"renderer_{renderer_index}"), "type": kind if kind in RENDERER_TYPES else "sprite", **deepcopy(dict(source.get("properties") or {}))})
    return {"id": str(row.get("id") or row.get("name") or f"emitter_{index}"), "name": str(row.get("name") or f"Emitter {index + 1}"), "simulation_target": str(row.get("simulation_target") or row.get("sim_target") or "auto").casefold(), "capacity": int(row.get("capacity") or row.get("max_particles") or 1024), "spawn_rate": float(row.get("spawn_rate") or 0.0), "lifetime": float(row.get("lifetime") or row.get("duration") or 1.0), "modules": modules, "renderers": renderers}


def _convert_unity_effects(payload: Mapping[str, Any], diagnostics: list[EffectIssue]) -> tuple[list[dict[str, Any]], str]:
    data = deepcopy(dict(payload or {})); version = str(data.get("unity_version") or data.get("version") or "unknown")
    graphs = data.get("visual_effect_graphs") or data.get("graphs") or ([data] if data.get("systems") or data.get("contexts") else [])
    rows = []
    for graph in graphs:
        source = dict(graph); systems = source.get("systems") or [source]
        emitters = [_unity_system(value, index, diagnostics) for index, value in enumerate(systems)]
        properties = normalize_effect_properties({"preset": "converted_unity", "duration": source.get("duration", 5.0), "loop": source.get("loop", True), "parameters": source.get("parameters") or source.get("exposed_properties") or {}, "emitters": emitters, "scalability": source.get("scalability", "auto")})
        rows.append({"source_id": str(source.get("guid") or source.get("id") or source.get("name")), "name": str(source.get("name") or "VisualEffectGraph"), "properties": properties, "source_extensions": deepcopy(list(source.get("source_extensions") or []))})
    return rows, version


def _unity_system(value: Mapping[str, Any], index: int, diagnostics: list[EffectIssue]) -> dict[str, Any]:
    row = dict(value); modules = []; renderers = []; capacity = int(row.get("capacity") or 1024)
    context_phases = {"spawn": "emitter_update", "initialize": "particle_spawn", "update": "particle_update", "output": "render", "event": "event_handler", "gpu_event": "event_handler"}
    for context_index, context_value in enumerate(row.get("contexts") or []):
        context = dict(context_value); context_type = str(context.get("type") or context.get("context_type") or "update").casefold().replace(" ", "_")
        phase = context_phases.get(context_type, "particle_update"); capacity = int(context.get("capacity") or capacity)
        if context_type == "output":
            output = str(context.get("output_type") or context.get("name") or "sprite").casefold(); kind = next((name for name in RENDERER_TYPES if name in output), "sprite")
            renderers.append({"id": str(context.get("id") or f"output_{context_index}"), "type": kind, **deepcopy(dict(context.get("settings") or {}))})
        for block_index, block_value in enumerate(context.get("blocks") or []):
            block = dict(block_value); title = str(block.get("type") or block.get("name") or "block"); normalized = title.casefold().replace(" ", "_")
            aliases = {"set_lifetime": "initialize", "set_velocity": "velocity", "add_velocity": "add_velocity", "gravity": "gravity", "linear_drag": "drag", "turbulence": "curl_noise", "collision_depth_buffer": "collision", "color_over_life": "color_over_life", "size_over_life": "size_over_life", "trigger_event": "event_generator"}
            opcode = aliases.get(normalized, normalized); extension = []
            if opcode not in MODULE_LIBRARY:
                extension.append(deepcopy(block)); diagnostics.append(EffectIssue("warning", "unsupported_unity_vfx_block", f"Unity VFX block '{title}' was preserved and needs a native replacement.", str(row.get("name") or f"System {index + 1}")))
            if opcode in MODULE_LIBRARY and phase not in MODULE_LIBRARY[opcode][0]: phase_for_module = MODULE_LIBRARY[opcode][0][0]
            else: phase_for_module = phase
            modules.append({"id": str(block.get("id") or f"context_{context_index}_block_{block_index}"), "type": opcode, "phase": phase_for_module, "enabled": bool(block.get("enabled", True)), "parameters": deepcopy(dict(block.get("parameters") or block.get("settings") or {})), "version": int(block.get("version", 1)), "source_extensions": extension})
    return {"id": str(row.get("id") or row.get("name") or f"system_{index}"), "name": str(row.get("name") or f"System {index + 1}"), "simulation_target": str(row.get("simulation_target") or "gpu").casefold(), "capacity": capacity, "spawn_rate": float(row.get("spawn_rate") or 0.0), "lifetime": float(row.get("lifetime") or 1.0), "modules": modules, "renderers": renderers}


def _normalize_emitter(value: Mapping[str, Any], index: int) -> dict[str, Any]:
    row = deepcopy(dict(value or {})); identifier = str(row.get("id") or row.get("emitter_id") or f"emitter_{index}")
    target = str(row.get("simulation_target") or "auto").casefold(); target = target if target in SIMULATION_TARGETS else "auto"
    modules = []
    for item_index, item in enumerate(row.get("modules") or []):
        if isinstance(item, Mapping):
            module = deepcopy(dict(item)); module_type = str(module.get("type") or module.get("module_type") or "module")
            phase = str(module.get("phase") or "update"); parameters = deepcopy(dict(module.get("parameters") or {})); enabled = bool(module.get("enabled", True))
        else:
            module_type = str(item); phase = "update"; parameters = {}; enabled = True
        aliases = {"forces": "gravity", "render": "color_over_life"}; module_type = aliases.get(module_type, module_type)
        phase_aliases = {"spawn": "particle_spawn", "update": "particle_update", "render": "render"}; phase = phase_aliases.get(phase, phase)
        if module_type in MODULE_LIBRARY and phase not in MODULE_LIBRARY[module_type][0]: phase = MODULE_LIBRARY[module_type][0][0]
        modules.append({"id": str(module.get("id") if isinstance(item, Mapping) else "" or f"{identifier}_module_{item_index}"), "type": module_type, "phase": phase, "enabled": enabled, "parameters": parameters, "version": int(module.get("version", 1) if isinstance(item, Mapping) else 1), "source_extensions": deepcopy(list(module.get("source_extensions") or [])) if isinstance(item, Mapping) else []})
    renderer = deepcopy(dict(row.get("renderer") or {})); renderers = deepcopy(list(row.get("renderers") or ([renderer] if renderer else [])))
    if not renderers: renderers = [{"id": f"{identifier}_renderer", "type": "sprite", "material_asset_id": "", "blend_mode": "additive", "sort_mode": "view_depth", "motion_vectors": False}]
    for renderer_index, item in enumerate(renderers):
        item.setdefault("id", f"{identifier}_renderer_{renderer_index}"); item.setdefault("type", "sprite")
        if "blend" in item and "blend_mode" not in item: item["blend_mode"] = item.pop("blend")
    capacity = int(row.get("capacity") or row.get("max_particles") or max(128, math.ceil(float(row.get("spawn_rate", 0.0)) * max(1.0, float(row.get("duration", 1.0))))))
    return {"id": identifier, "name": str(row.get("name") or f"Emitter {index + 1}"), "enabled": bool(row.get("enabled", True)), "simulation_target": target, "local_space": bool(row.get("local_space", False)), "capacity": max(1, capacity), "spawn_rate": max(0.0, float(row.get("spawn_rate", 0.0))), "bursts": deepcopy(list(row.get("bursts") or ([{"time": 0.0, "count": int(row.get("burst_count", 0))}] if int(row.get("burst_count", 0)) else []))), "lifetime": float(row.get("lifetime") or row.get("duration") or 1.0), "loop": bool(row.get("loop", row.get("looping", False))), "event_only": bool(row.get("event_only", False)), "persistent_ids": bool(row.get("persistent_ids", False)), "spawn_shape": deepcopy(dict(row.get("spawn_shape") or {"type": "point"})), "modules": modules, "renderers": renderers, "bounds": deepcopy(dict(row.get("bounds") or {})), "scalability": deepcopy(dict(row.get("scalability") or {})), "source_extensions": deepcopy(list(row.get("source_extensions") or []))}


def _default_quality_overrides() -> dict[str, Any]:
    return {"low": {"spawn_scale": 0.3, "capacity_scale": 0.35, "disabled_emitters": []}, "medium": {"spawn_scale": 0.6, "capacity_scale": 0.65, "disabled_emitters": []}, "high": {"spawn_scale": 1.0, "capacity_scale": 1.0, "disabled_emitters": []}, "cinematic": {"spawn_scale": 1.5, "capacity_scale": 1.75, "disabled_emitters": []}, "mobile": {"spawn_scale": 0.3, "capacity_scale": 0.35, "disabled_emitters": []}}


def _effect_references(values: Mapping[str, Any]) -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()
    for emitter in values.get("emitters") or []:
        for renderer in dict(emitter).get("renderers") or []:
            for key, kind in (("material_asset_id", "effect_material"), ("mesh_asset_id", "effect_mesh"), ("texture_asset_id", "effect_texture")):
                reference = str(dict(renderer).get(key) or "")
                if reference: references.add((reference, kind))
        for module in dict(emitter).get("modules") or []:
            for key, item in dict(dict(module).get("parameters") or {}).items():
                if str(key).endswith("_asset_id") and item: references.add((str(item), "effect_module_resource"))
    return references


def _safe_effect_name(value: str) -> str:
    cleaned = "_".join(part for part in "".join(char if char.isalnum() or char in "_.-" else " " for char in value).split() if part).strip("._")
    return cleaned or "ConvertedEffect"


__all__ = ["EFFECT_SYSTEM_SCHEMA", "EFFECT_RUNTIME_SCHEMA", "EFFECT_PHASES", "SIMULATION_TARGETS", "RENDERER_TYPES", "MODULE_LIBRARY", "EffectIssue", "EffectCostEstimate", "EffectConversionReceipt", "EffectAssetService", "effect_system_defaults", "normalize_effect_properties", "validate_effect_properties", "estimate_effect_cost", "compile_effect_payload"]
