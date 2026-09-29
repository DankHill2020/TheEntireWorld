"""Production material, instance, shader, and texture integration services."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


MATERIAL_SCHEMA = "tech_connector.asset.material.v2"
MATERIAL_RUNTIME_SCHEMA = "tech_connector.runtime.material.v1"
MATERIAL_DOMAINS = ("surface", "decal", "post_process", "ui", "volume")
MATERIAL_BLEND_MODES = ("opaque", "masked", "translucent", "additive", "modulate")
MATERIAL_SHADING_MODELS = ("pbr", "unlit", "subsurface", "clear_coat", "cloth", "hair", "thin_translucent")
COLOR_TEXTURE_SLOTS = frozenset({"base_color", "emissive", "subsurface_color"})
DATA_TEXTURE_SLOTS = frozenset({"normal", "roughness", "metalness", "ambient_occlusion", "opacity", "height", "mask"})

NODE_COSTS: dict[str, tuple[int, int]] = {
    "constant": (0, 0), "parameter": (0, 0), "uv": (0, 0), "vertex_color": (0, 0),
    "sample_texture": (4, 1), "sample_normal": (5, 1), "virtual_texture": (6, 1),
    "add": (1, 0), "subtract": (1, 0), "multiply": (1, 0), "divide": (4, 0),
    "lerp": (2, 0), "clamp": (1, 0), "saturate": (1, 0), "one_minus": (1, 0),
    "dot": (2, 0), "cross": (3, 0), "normalize": (4, 0), "fresnel": (5, 0),
    "power": (6, 0), "sine": (5, 0), "noise": (18, 0), "parallax": (24, 2),
    "static_switch": (0, 0), "material_function": (4, 0), "surface_output": (0, 0),
}


def shader_backend_capabilities() -> dict[str, Any]:
    """Report native shader tools honestly; portable IR remains available everywhere."""
    tools = {
        "directx_dxc": shutil.which("dxc") or "",
        "vulkan_glslang": shutil.which("glslangValidator") or "",
        "spirv_cross": shutil.which("spirv-cross") or "",
        "metal_xcrun": shutil.which("xcrun") or "",
    }
    return {
        "portable_ir": True,
        "native_compilers": tools,
        "native_compilation_available": any(tools.values()),
        "fallback": "portable_runtime_ir",
    }


@dataclass(frozen=True)
class MaterialIssue:
    severity: str
    code: str
    message: str
    subject: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MaterialResolution:
    asset_id: str
    source_type: str
    root_material_id: str
    inheritance_chain: tuple[str, ...]
    properties: dict[str, Any]
    overrides: dict[str, Any]
    dependencies: tuple[str, ...]
    permutation_key: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id, "source_type": self.source_type,
            "root_material_id": self.root_material_id,
            "inheritance_chain": list(self.inheritance_chain),
            "properties": deepcopy(self.properties), "overrides": deepcopy(self.overrides),
            "dependencies": list(self.dependencies), "permutation_key": self.permutation_key,
            "fingerprint": self.fingerprint,
        }


class MaterialService:
    """Shared source of truth for material UI, automation, validation, and cooking."""

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create_material(
        self, name: str, *, domain: str = "", shading_model: str = "",
        blend_mode: str = "", preset: str = "default_lit",
        folder: str | Path = "Assets/Materials",
    ):
        receipt = self.operations.create_asset("tc.material", name, folder=folder)
        properties = material_preset(preset)
        if domain: properties["domain"] = str(domain)
        if shading_model: properties["shading_model"] = str(shading_model)
        if blend_mode: properties["blend_mode"] = str(blend_mode)
        self._save(receipt.asset_id, properties)
        return receipt

    def create_instance(
        self, name: str, parent_material_id: str, *, overrides: Mapping[str, Any] | None = None,
        static_switch_overrides: Mapping[str, bool] | None = None,
        folder: str | Path = "Assets/Materials/Instances",
    ):
        self.resolve(parent_material_id)
        receipt = self.operations.create_asset("tc.material_instance", name, folder=folder)
        self._save(receipt.asset_id, {
            "material_version": 2, "parent_material_id": str(parent_material_id),
            "overrides": deepcopy(dict(overrides or {})),
            "static_switch_overrides": {str(key): bool(value) for key, value in dict(static_switch_overrides or {}).items()},
            "parameter_groups": {}, "platform_overrides": {},
        })
        return receipt

    def update_properties(
        self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False,
    ) -> dict[str, Any]:
        _record, authored = self._load(asset_id)
        properties = {} if replace else authored
        properties.update(deepcopy(dict(values or {})))
        self._save(asset_id, properties)
        _record, saved = self._load(asset_id)
        return saved

    def apply_preset(self, asset_id: str, preset: str) -> MaterialResolution:
        record, authored = self._load(asset_id)
        if record.asset_type != "tc.material":
            raise ValueError(f"Asset is not a Material: {asset_id}")
        preview = {
            key: authored[key]
            for key in ("preview_mesh", "preview_environment", "preview_exposure")
            if key in authored
        }
        properties = material_preset(preset)
        properties.update(preview)
        self._save(asset_id, properties)
        return self.resolve(asset_id)

    def resolve(self, asset_id: str) -> MaterialResolution:
        return self._resolve(str(asset_id), ())

    def set_instance_overrides(
        self, asset_id: str, overrides: Mapping[str, Any], *, replace: bool = False,
        static_switches: Mapping[str, bool] | None = None,
    ) -> MaterialResolution:
        record, properties = self._load(asset_id)
        if record.asset_type != "tc.material_instance":
            raise ValueError(f"Asset is not a Material Instance: {asset_id}")
        values = {} if replace else dict(properties.get("overrides") or {})
        values.update(deepcopy(dict(overrides or {})))
        properties["overrides"] = values
        if static_switches is not None:
            switches = {} if replace else dict(properties.get("static_switch_overrides") or {})
            switches.update({str(key): bool(value) for key, value in static_switches.items()})
            properties["static_switch_overrides"] = switches
        self._save(asset_id, properties)
        return self.resolve(asset_id)

    def revert_instance_overrides(self, asset_id: str, names: Iterable[str] = ()) -> MaterialResolution:
        _record, properties = self._load(asset_id)
        selected = {str(value) for value in names}
        properties["overrides"] = {
            key: value for key, value in dict(properties.get("overrides") or {}).items()
            if selected and key not in selected
        }
        properties["static_switch_overrides"] = {
            key: value for key, value in dict(properties.get("static_switch_overrides") or {}).items()
            if selected and key not in selected
        }
        self._save(asset_id, properties)
        return self.resolve(asset_id)

    def assign_texture(
        self, material_asset_id: str, slot: str, texture_asset_id: str, *,
        channel: str = "rgba", color_space: str = "auto", sampler: str = "linear_wrap", uv_set: int = 0,
    ) -> MaterialResolution:
        texture = self.database.asset(texture_asset_id)
        if texture is None or texture.asset_type not in {"tc.texture", "tc.image_project", "tc.video"}:
            raise ValueError(f"Texture binding requires a Texture, Image Project, or Video asset: {texture_asset_id}")
        record, properties = self._load(material_asset_id)
        key = "overrides" if record.asset_type == "tc.material_instance" else "texture_bindings"
        bindings = dict(properties.get(key) or {})
        binding = {
            "asset_id": str(texture_asset_id), "channel": str(channel),
            "color_space": _expected_color_space(slot) if color_space == "auto" else str(color_space),
            "sampler": str(sampler), "uv_set": max(0, int(uv_set)),
        }
        if key == "overrides":
            bindings[f"texture_bindings.{slot}"] = binding
        else:
            bindings[str(slot)] = binding
        properties[key] = bindings
        self._save(material_asset_id, properties)
        return self.resolve(material_asset_id)

    def validate(self, asset_id: str, *, platform: str = "desktop") -> tuple[MaterialIssue, ...]:
        try:
            resolution = self.resolve(asset_id)
        except (KeyError, ValueError) as exc:
            return (MaterialIssue("error", "invalid_material", str(exc), fix="Repair the parent chain or recreate the asset."),)
        properties = resolution.properties
        issues: list[MaterialIssue] = []
        domain = str(properties.get("domain") or "surface")
        shading = str(properties.get("shading_model") or "pbr")
        blend = str(properties.get("blend_mode") or "opaque")
        if domain not in MATERIAL_DOMAINS:
            issues.append(MaterialIssue("error", "invalid_domain", f"Unsupported material domain: {domain}", "domain", f"Choose one of: {', '.join(MATERIAL_DOMAINS)}."))
        if shading not in MATERIAL_SHADING_MODELS:
            issues.append(MaterialIssue("error", "invalid_shading_model", f"Unsupported shading model: {shading}", "shading_model", f"Choose one of: {', '.join(MATERIAL_SHADING_MODELS)}."))
        if blend not in MATERIAL_BLEND_MODES:
            issues.append(MaterialIssue("error", "invalid_blend_mode", f"Unsupported blend mode: {blend}", "blend_mode", f"Choose one of: {', '.join(MATERIAL_BLEND_MODES)}."))
        if domain == "post_process" and shading != "unlit":
            issues.append(MaterialIssue("error", "post_process_lit", "Post-process materials must use the Unlit shading model.", "shading_model", "Set Shading Model to unlit."))
        if blend == "masked" and not 0.0 <= float(properties.get("opacity_mask_clip", 0.333)) <= 1.0:
            issues.append(MaterialIssue("error", "invalid_mask_clip", "Opacity Mask Clip must be between 0 and 1.", "opacity_mask_clip", "Clamp the value to the 0–1 range."))
        for slot, binding in dict(properties.get("texture_bindings") or {}).items():
            if not isinstance(binding, Mapping):
                issues.append(MaterialIssue("error", "invalid_texture_binding", f"Texture binding {slot} must be an object.", str(slot)))
                continue
            texture_id = str(binding.get("asset_id") or "")
            texture = self.database.asset(texture_id)
            if texture is None:
                issues.append(MaterialIssue("error", "missing_texture", f"Texture is unavailable: {texture_id}", str(slot), "Choose a registered texture asset."))
            expected = _expected_color_space(str(slot))
            actual = str(binding.get("color_space") or expected)
            if actual != expected:
                issues.append(MaterialIssue("warning", "texture_color_space", f"{slot} expects {expected}, not {actual}.", str(slot), f"Set Color Space to {expected}."))
        graph = dict(properties.get("graph") or {})
        graph_issues, stats = analyze_material_graph(graph, platform=platform)
        issues.extend(graph_issues)
        if stats["estimated_alu"] > (96 if platform in {"mobile", "android", "ios"} else 256):
            issues.append(MaterialIssue("warning", "shader_cost", f"Estimated shader ALU cost is {stats['estimated_alu']} instructions.", "graph", "Use static switches, bake procedural branches, or simplify expensive nodes."))
        if stats["texture_samples"] > (8 if platform in {"mobile", "android", "ios"} else 16):
            issues.append(MaterialIssue("warning", "texture_sample_cost", f"Shader uses {stats['texture_samples']} texture samples.", "graph", "Pack compatible data maps or reuse texture samples."))
        return tuple(issues)

    def compile(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        resolution = self.resolve(asset_id)
        errors = [item.message for item in self.validate(asset_id, platform=platform) if item.severity == "error"]
        if errors:
            raise ValueError("; ".join(errors))
        payload = compile_material_payload(resolution, platform=platform, quality=quality)
        return self.database.store_derived(
            asset_id, f"material_runtime:{platform}:{quality}", payload,
            metadata={"platform": platform, "quality": quality, "permutation_key": resolution.permutation_key,
                      "fingerprint": resolution.fingerprint}, extension=".tcmaterialbin",
        )

    def rebuild_dependencies(self, asset_id: str) -> tuple[tuple[str, str], ...]:
        _record, properties = self._load(asset_id)
        self._save(asset_id, properties)
        return self.database.dependency_edges(asset_id)

    def _resolve(self, asset_id: str, stack: tuple[str, ...]) -> MaterialResolution:
        if asset_id in stack:
            raise ValueError(f"Material inheritance cycle detected: {' -> '.join((*stack, asset_id))}")
        record, authored = self._load(asset_id)
        if record.asset_type == "tc.material":
            properties = _normalize_material(authored)
            chain, root, overrides = (asset_id,), asset_id, {}
        elif record.asset_type == "tc.material_instance":
            parent_id = str(authored.get("parent_material_id") or authored.get("parent") or "")
            if not parent_id:
                raise ValueError(f"Material Instance has no parent: {asset_id}")
            parent = self._resolve(parent_id, (*stack, asset_id))
            properties = deepcopy(parent.properties)
            overrides = deepcopy(dict(authored.get("overrides") or {}))
            for path, value in overrides.items():
                _set_dotted(properties, str(path), deepcopy(value))
            switches = dict(properties.get("static_switches") or {})
            switches.update({str(key): bool(value) for key, value in dict(authored.get("static_switch_overrides") or {}).items()})
            properties["static_switches"] = switches
            platform_values = dict(properties.get("platform_overrides") or {})
            platform_values.update(deepcopy(dict(authored.get("platform_overrides") or {})))
            properties["platform_overrides"] = platform_values
            chain, root = (*parent.inheritance_chain, asset_id), parent.root_material_id
        else:
            raise ValueError(f"Asset is not a Material or Material Instance: {asset_id}")
        dependencies = tuple(sorted(set(self.database.dependencies(asset_id)) | set(chain[:-1]) | _material_references(properties)))
        permutation_key = _fingerprint({"static_switches": properties.get("static_switches", {}), "platform_overrides": properties.get("platform_overrides", {})})[:20]
        fingerprint = _fingerprint({"properties": properties, "chain": chain, "permutation_key": permutation_key})
        return MaterialResolution(asset_id, record.asset_type, root, chain, properties, overrides, dependencies, permutation_key, fingerprint)

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown material asset: {asset_id}")
        if record.asset_type not in {"tc.material", "tc.material_instance"}:
            raise ValueError(f"Asset is not a Material or Material Instance: {asset_id}")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Material source is unreadable: {record.source_path}") from exc
        return record, deepcopy(dict(payload.get("properties") or {}))

    def _save(self, asset_id: str, properties: Mapping[str, Any]) -> None:
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown material asset: {asset_id}")
        clean = _normalize_material(properties) if record.asset_type == "tc.material" else deepcopy(dict(properties))
        clean["material_version"] = 2
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        payload["schema"], payload["properties"] = MATERIAL_SCHEMA, clean
        _atomic_json_write(record.source_path, payload)
        refs = _material_references(clean)
        parent = str(clean.get("parent_material_id") or clean.get("parent") or "")
        edges = [(value, "parent_material" if value == parent else "material_resource") for value in sorted(refs | ({parent} if parent else set())) if self.database.asset(value) is not None]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id,
                                     metadata=record.metadata, dependencies=edges)


def material_preset(name: str) -> dict[str, Any]:
    key = str(name or "default_lit").strip().casefold()
    presets = {
        "default_lit": {},
        "unlit": {"shading_model": "unlit", "base_color": "#ffffff"},
        "glass": {"shading_model": "thin_translucent", "blend_mode": "translucent", "roughness": 0.08, "opacity": 0.18, "transmission": 1.0, "two_sided": True},
        "clear_coat": {"shading_model": "clear_coat", "clear_coat": 1.0, "clear_coat_roughness": 0.08},
        "skin": {"shading_model": "subsurface", "roughness": 0.42, "subsurface_color": "#ff9b88"},
        "cloth": {"shading_model": "cloth", "roughness": 0.72, "sheen": 0.35, "two_sided": True},
        "decal": {"domain": "decal", "blend_mode": "translucent", "shading_model": "unlit"},
        "post_process": {"domain": "post_process", "shading_model": "unlit"},
    }
    if key not in presets:
        raise KeyError(f"Unknown material preset: {name}")
    result = _normalize_material({})
    result.update(deepcopy(presets[key]))
    result["preset"] = key
    return result


def analyze_material_graph(graph: Mapping[str, Any], *, platform: str = "desktop") -> tuple[list[MaterialIssue], dict[str, Any]]:
    nodes = [dict(item) for item in graph.get("nodes") or () if isinstance(item, Mapping)]
    connections = [dict(item) for item in graph.get("connections") or () if isinstance(item, Mapping)]
    issues: list[MaterialIssue] = []
    ids = [str(item.get("id") or "") for item in nodes]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        issues.append(MaterialIssue("error", "node_identity", "Every material node requires a unique stable ID.", "graph", "Regenerate duplicate or blank node IDs."))
    known = set(ids)
    for edge in connections:
        if str(edge.get("source") or "") not in known or str(edge.get("target") or "") not in known:
            issues.append(MaterialIssue("error", "dangling_connection", "A graph connection targets a missing node.", "graph", "Reconnect or remove the dangling edge."))
    if _graph_cycle(known, connections):
        issues.append(MaterialIssue("error", "dependency_cycle", "Material graph contains a dependency cycle.", "graph", "Break the feedback connection or move temporal behavior to a supported runtime node."))
    outputs = [item for item in nodes if _material_node_opcode(item) in {"surface", "surface_output", "shader_output"}]
    if nodes and len(outputs) != 1:
        issues.append(MaterialIssue("error", "output_count", "Material graphs require exactly one output node.", "graph", "Add one Surface Output and remove extras."))
    alu = texture_samples = branches = 0
    expensive: list[str] = []
    for node in nodes:
        opcode = _material_node_opcode(node)
        cost = NODE_COSTS.get(opcode, (2, 0))
        alu += cost[0]
        texture_samples += cost[1]
        if opcode == "static_switch": branches += 1
        if cost[0] >= 12: expensive.append(str(node.get("title") or opcode))
    permutations = min(4096, 2 ** branches)
    stats = {
        "node_count": len(nodes), "connection_count": len(connections),
        "estimated_alu": alu, "texture_samples": texture_samples,
        "static_switches": branches, "permutations": permutations,
        "expensive_nodes": expensive, "platform": str(platform),
    }
    if permutations > 64:
        issues.append(MaterialIssue("warning", "permutation_count", f"Static switches can produce {permutations} shader permutations.", "graph", "Prefer runtime parameters for non-structural choices."))
    return issues, stats


def _material_node_opcode(node: Mapping[str, Any]) -> str:
    """Accept both current opcode-authored nodes and legacy title-authored graphs."""
    explicit = str(node.get("opcode") or "").strip()
    if explicit:
        return explicit
    return "_".join(
        part for part in "".join(
            character if character.isalnum() else " " for character in str(node.get("title") or "")
        ).casefold().split() if part
    )


def compile_material_payload(
    resolution: MaterialResolution, *, platform: str = "desktop", quality: str = "high",
) -> bytes:
    properties = deepcopy(resolution.properties)
    graph = dict(properties.get("graph") or {})
    _issues, stats = analyze_material_graph(graph, platform=platform)
    operations = []
    for index, node in enumerate(_ordered_nodes(graph)):
        operations.append({
            "index": index, "id": str(node.get("id") or f"node_{index}"),
            "opcode": str(node.get("opcode") or "constant"),
            "parameters": deepcopy(dict(node.get("parameters") or {})),
        })
    shader_source = _generated_shader_source(properties, operations, platform)
    payload = {
        "schema": MATERIAL_RUNTIME_SCHEMA, "asset_id": resolution.asset_id,
        "root_material_id": resolution.root_material_id,
        "inheritance_chain": list(resolution.inheritance_chain),
        "platform": str(platform), "quality": str(quality),
        "domain": properties.get("domain"), "shading_model": properties.get("shading_model"),
        "blend_mode": properties.get("blend_mode"), "two_sided": bool(properties.get("two_sided")),
        "parameters": {key: deepcopy(properties.get(key)) for key in (
            "base_color", "roughness", "metalness", "specular", "normal_strength", "emissive_color",
            "emissive_intensity", "opacity", "opacity_mask_clip", "clear_coat", "clear_coat_roughness",
            "subsurface_color", "transmission", "ior", "sheen",
        )},
        "texture_bindings": deepcopy(dict(properties.get("texture_bindings") or {})),
        "static_switches": deepcopy(dict(properties.get("static_switches") or {})),
        "permutation_key": resolution.permutation_key, "graph_operations": operations,
        "connections": deepcopy(list(graph.get("connections") or ())),
        "statistics": stats, "generated_source": shader_source,
        "dependencies": list(resolution.dependencies), "fingerprint": resolution.fingerprint,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _normalize_material(values: Mapping[str, Any]) -> dict[str, Any]:
    defaults = {
        "material_version": 2, "preset": "default_lit", "domain": "surface",
        "shading_model": "pbr", "blend_mode": "opaque", "two_sided": False,
        "base_color": "#ffffff", "roughness": 0.5, "metalness": 0.0, "specular": 0.5,
        "normal_strength": 1.0, "emissive_color": "#000000", "emissive_intensity": 0.0,
        "opacity": 1.0, "opacity_mask_clip": 0.333, "clear_coat": 0.0,
        "clear_coat_roughness": 0.1, "subsurface_color": "#ffffff", "transmission": 0.0,
        "ior": 1.5, "sheen": 0.0, "parameters": {}, "parameter_groups": {},
        "texture_bindings": {}, "static_switches": {}, "graph": {"nodes": [], "connections": []},
        "platform_overrides": {}, "preview_mesh": "Sphere", "preview_environment": "Studio",
        "preview_exposure": 0.0,
    }
    defaults.update(deepcopy(dict(values or {})))
    return defaults


def _graph_cycle(node_ids: set[str], connections: Iterable[Mapping[str, Any]]) -> bool:
    outgoing = {node_id: [] for node_id in node_ids}
    for edge in connections:
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source in outgoing and target in node_ids:
            outgoing[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting: return True
        if node_id in visited: return False
        visiting.add(node_id)
        if any(visit(target) for target in outgoing[node_id]): return True
        visiting.remove(node_id); visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in sorted(node_ids))


def _ordered_nodes(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = [dict(item) for item in graph.get("nodes") or () if isinstance(item, Mapping)]
    by_id = {str(item.get("id") or ""): item for item in nodes}
    incoming = {node_id: 0 for node_id in by_id}
    outgoing = {node_id: [] for node_id in by_id}
    for edge in graph.get("connections") or ():
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source in by_id and target in by_id:
            outgoing[source].append(target); incoming[target] += 1
    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0); ordered.append(current)
        for target in sorted(outgoing[current]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target); ready.sort()
    ordered.extend(sorted(set(by_id) - set(ordered)))
    return [by_id[node_id] for node_id in ordered]


def _expected_color_space(slot: str) -> str:
    return "srgb" if str(slot) in COLOR_TEXTURE_SLOTS else "linear"


def _material_references(value: Any, key: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            name = str(child_key)
            if (name.endswith("_id") or name == "asset_id") and isinstance(child, str) and child.startswith("tc.asset."):
                found.add(child)
            else:
                found.update(_material_references(child, name))
    elif isinstance(value, (list, tuple)):
        for child in value: found.update(_material_references(child, key))
    return found


def _set_dotted(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts: raise ValueError("Material override path cannot be blank.")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _generated_shader_source(properties: Mapping[str, Any], operations: list[dict[str, Any]], platform: str) -> str:
    lines = [
        "// Generated by Tech Connector Material Compiler",
        f"// target={platform} domain={properties.get('domain')} shading={properties.get('shading_model')}",
        "struct TC_Surface { float3 baseColor; float roughness; float metalness; float opacity; };",
        "TC_Surface EvaluateMaterial(float2 uv0) {",
        f"  TC_Surface s = {{float3(1.0, 1.0, 1.0), {float(properties.get('roughness', 0.5)):.6f}, {float(properties.get('metalness', 0.0)):.6f}, {float(properties.get('opacity', 1.0)):.6f}}};",
    ]
    for operation in operations:
        lines.append(f"  // [{operation['index']}] {operation['opcode']} ({operation['id']})")
    lines.extend(["  return s;", "}"])
    return "\n".join(lines) + "\n"


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
