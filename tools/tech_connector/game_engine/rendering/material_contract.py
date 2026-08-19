"""Portable look-development contracts shared by scene importers and renderers."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
import hashlib
import importlib.util
from pathlib import Path
from typing import Any


PORTABLE_MATERIAL_SCHEMA = "tech_connector.portable_material.v1"
PORTABLE_LOOKDEV_SCHEMA = "tech_connector.portable_lookdev.v1"
COLOR_TEXTURE_CHANNELS = frozenset({"base_color", "emission_color", "coat_color"})
DATA_TEXTURE_CHANNELS = frozenset({
    "metalness", "specular_roughness", "normal", "displacement", "opacity",
    "transmission_weight", "coat_weight", "coat_roughness", "ambient_occlusion",
})
TEXTURE_CHANNEL_ALIASES = {
    "albedo": "base_color",
    "base color": "base_color",
    "base_color_texture": "base_color",
    "color": "base_color",
    "diffuse": "base_color",
    "diffuse_color": "base_color",
    "emission": "emission_color",
    "emission_color": "emission_color",
    "emissive": "emission_color",
    "metallic": "metalness",
    "metallic_texture": "metalness",
    "roughness": "specular_roughness",
    "roughness_texture": "specular_roughness",
    "normal map": "normal",
    "normal_texture": "normal",
    "height": "displacement",
    "alpha": "opacity",
}

PROVIDER_LOOKDEV_CAPTURE_PROFILES: dict[str, dict[str, Any]] = {
    "maya": {
        "capture_status": "native",
        "geometry_level": "mesh",
        "assignment_level": "face",
        "uv_level": "named_set",
        "texture_evidence": "filesystem",
        "material_cost_gated": True,
    },
    "blender": {
        "capture_status": "native",
        "geometry_level": "mesh",
        "assignment_level": "face",
        "uv_level": "named_set",
        "texture_evidence": "filesystem",
        "material_cost_gated": True,
    },
    "3dsmax": {
        "capture_status": "native",
        "geometry_level": "mesh",
        "assignment_level": "face",
        "uv_level": "map_channel_1",
        "texture_evidence": "filesystem",
        "material_cost_gated": True,
    },
    "houdini": {
        "capture_status": "native",
        "geometry_level": "mesh",
        "assignment_level": "primitive",
        "uv_level": "vertex_or_point",
        "texture_evidence": "filesystem",
        "material_cost_gated": True,
    },
    "unreal": {
        "capture_status": "partial",
        "geometry_level": "bounds",
        "assignment_level": "component_slot",
        "uv_level": "not_exposed",
        "texture_evidence": "import_source_or_package",
        "material_cost_gated": True,
        "limitations": ["Material-instance parameters are portable; compiled shader graphs remain host-owned."],
    },
    "unity": {
        "capture_status": "partial",
        "geometry_level": "bounds",
        "assignment_level": "renderer_slot",
        "uv_level": "uv0_convention",
        "texture_evidence": "asset_source",
        "material_cost_gated": True,
        "limitations": ["ShaderGraph topology remains host-owned; common Lit/Standard parameters are portable."],
    },
    "substance_painter": {
        "capture_status": "lookdev_only",
        "geometry_level": "source_mesh_reference",
        "assignment_level": "texture_set",
        "uv_level": "stack_inventory",
        "texture_evidence": "export_required",
        "material_cost_gated": True,
        "limitations": ["Layer stacks are preserved as host evidence and require Painter for full editing."],
    },
    "motionbuilder": {
        "capture_status": "not_role_required",
        "geometry_level": "bounds",
        "assignment_level": "not_captured",
        "uv_level": "not_captured",
        "texture_evidence": "fbx_interchange",
        "material_cost_gated": True,
        "limitations": ["MotionBuilder qualification targets animation and FBX interchange, not lookdev authoring."],
    },
    "photoshop": {
        "capture_status": "image_document_native",
        "geometry_level": "not_applicable",
        "assignment_level": "layer",
        "uv_level": "not_applicable",
        "texture_evidence": "layered_document",
        "material_cost_gated": True,
        "limitations": ["Image layers feed portable texture channels rather than 3D material assignments."],
    },
    "gimp": {
        "capture_status": "image_document_native",
        "geometry_level": "not_applicable",
        "assignment_level": "layer",
        "uv_level": "not_applicable",
        "texture_evidence": "layered_document",
        "material_cost_gated": True,
        "limitations": ["Image layers feed portable texture channels rather than 3D material assignments."],
    },
}


@dataclass(frozen=True)
class PortableTextureBinding:
    channel: str
    path: str
    color_space: str
    uv_set: str = "st"
    wrap_u: str = "periodic"
    wrap_v: str = "periodic"
    source_channel: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortableMaterial:
    material_id: str
    name: str
    source_provider: str
    source_shader: str
    parameters: dict[str, Any]
    textures: dict[str, PortableTextureBinding]
    source_graph: dict[str, Any] = field(default_factory=dict)
    unsupported_nodes: tuple[str, ...] = ()
    approximation: str = "openpbr"
    schema: str = PORTABLE_MATERIAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["textures"] = {key: value.to_dict() for key, value in self.textures.items()}
        data["unsupported_nodes"] = list(self.unsupported_nodes)
        return data


@dataclass(frozen=True)
class PortableLookdevState:
    source_provider: str
    materials: dict[str, dict[str, Any]]
    assignments: tuple[dict[str, Any], ...]
    texture_assets: dict[str, dict[str, Any]]
    host_extensions: dict[str, Any]
    parity: dict[str, Any]
    schema: str = PORTABLE_LOOKDEV_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_provider": self.source_provider,
            "materials": copy.deepcopy(self.materials),
            "assignments": copy.deepcopy(list(self.assignments)),
            "texture_assets": copy.deepcopy(self.texture_assets),
            "host_extensions": copy.deepcopy(self.host_extensions),
            "parity": copy.deepcopy(self.parity),
        }


def portable_material_runtime_capabilities() -> dict[str, Any]:
    modules = {
        "materialx": "MaterialX",
        "opencolorio": "PyOpenColorIO",
        "openusd": "pxr",
    }
    available = {
        capability: importlib.util.find_spec(module) is not None
        for capability, module in modules.items()
    }
    return {
        "schema": "tech_connector.lookdev_runtime_capabilities.v1",
        "available": available,
        "portable_contract": True,
        "materialx_document_io": available["materialx"],
        "ocio_processor": available["opencolorio"],
        "usd_shade_io": available["openusd"],
        "fallback": "portable_contract_and_source_graph",
    }


def provider_lookdev_capture_profile(provider: str) -> dict[str, Any]:
    key = str(provider or "").strip().lower().split(":", 1)[0]
    if key == "max":
        key = "3dsmax"
    profile = PROVIDER_LOOKDEV_CAPTURE_PROFILES.get(key)
    if profile is None:
        return {
            "provider": key,
            "capture_status": "unsupported",
            "geometry_level": "unknown",
            "assignment_level": "unknown",
            "uv_level": "unknown",
            "texture_evidence": "unknown",
            "material_cost_gated": False,
            "limitations": ["No lookdev capture profile is registered."],
        }
    return {"provider": key, **copy.deepcopy(profile), "limitations": list(profile.get("limitations") or [])}


def normalize_portable_material(
    payload: dict[str, Any] | None,
    *,
    source_provider: str = "",
    source_path: str = "",
    material_id: str = "",
) -> PortableMaterial:
    source = dict(payload or {})
    saved_parameters = source.get("parameters") if isinstance(source.get("parameters"), dict) else {}
    name = str(source.get("name") or material_id or "Material")
    identifier = str(
        material_id
        or source.get("source_material_id")
        or source.get("native_id")
        or source.get("id")
        or name
    )
    base_color = _vector(
        saved_parameters.get("base_color", source.get("base_color", source.get("color"))),
        4,
        (0.75, 0.78, 0.82, 1.0),
    )
    emission = _vector(
        saved_parameters.get("emission_color", source.get("emission_color", source.get("emission"))),
        3,
        (0.0, 0.0, 0.0),
    )
    parameters = {
        "base_weight": _unit(saved_parameters.get("base_weight", source.get("base_weight", 1.0)), 1.0),
        "base_color": base_color,
        "metalness": _unit(saved_parameters.get("metalness", source.get("metalness", source.get("metallic", 0.0))), 0.0),
        "specular_weight": _unit(saved_parameters.get("specular_weight", source.get("specular_weight", source.get("specular", 0.5))), 0.5),
        "specular_roughness": _unit(saved_parameters.get("specular_roughness", source.get("specular_roughness", source.get("roughness", 0.5))), 0.5),
        "specular_ior": max(1.0, _number(saved_parameters.get("specular_ior", source.get("specular_ior", source.get("ior", 1.5))), 1.5)),
        "transmission_weight": _unit(saved_parameters.get("transmission_weight", source.get("transmission_weight", source.get("transmission", 0.0))), 0.0),
        "coat_weight": _unit(saved_parameters.get("coat_weight", source.get("coat_weight", source.get("clearcoat", 0.0))), 0.0),
        "coat_roughness": _unit(saved_parameters.get("coat_roughness", source.get("coat_roughness", 0.1)), 0.1),
        "emission_color": emission,
        "emission_luminance": max(0.0, _number(saved_parameters.get("emission_luminance", source.get("emission_luminance", source.get("emission_strength", 0.0))), 0.0)),
        "opacity": _unit(saved_parameters.get("opacity", source.get("opacity", base_color[3])), base_color[3]),
        "thin_walled": bool(saved_parameters.get("thin_walled", source.get("thin_walled", False))),
    }
    texture_payload = source.get("textures") or source.get("texture_paths") or {}
    textures: dict[str, PortableTextureBinding] = {}
    if isinstance(texture_payload, dict):
        for source_channel, raw_binding in texture_payload.items():
            channel = canonical_texture_channel(str(source_channel))
            binding = _texture_binding(
                channel,
                str(source_channel),
                raw_binding,
                source_path=source_path,
            )
            if binding is not None:
                textures[channel] = binding
    elif isinstance(texture_payload, list):
        for raw_binding in texture_payload:
            if not isinstance(raw_binding, dict):
                continue
            source_channel = str(raw_binding.get("channel") or raw_binding.get("source_channel") or "")
            channel = canonical_texture_channel(source_channel)
            binding = _texture_binding(
                channel,
                str(raw_binding.get("source_channel") or source_channel),
                raw_binding,
                source_path=source_path,
            )
            if binding is not None:
                textures[channel] = binding
    source_graph = dict(source.get("source_graph") or {})
    unsupported = tuple(sorted({str(item) for item in source.get("unsupported_nodes") or [] if str(item)}))
    approximation = "openpbr" if not unsupported else "openpbr_with_source_fallback"
    return PortableMaterial(
        identifier,
        name,
        str(source_provider or source.get("source_provider") or ""),
        str(source.get("source_shader") or source.get("shader") or source.get("shader_type") or "unknown"),
        parameters,
        textures,
        source_graph,
        unsupported,
        approximation,
    )


def lookdev_state_from_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    source_provider: str = "",
    source_path: str = "",
) -> PortableLookdevState:
    """Extract scene-level materials, assignments, and dependency evidence."""

    source = dict(snapshot or {})
    provider = str(source_provider or source.get("provider_id") or "").strip().lower().split(":", 1)[0]
    scene_path = str(source_path or source.get("scene") or source.get("file") or "")
    materials: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []
    texture_assets: dict[str, dict[str, Any]] = {}
    raw_materials: dict[str, dict[str, Any]] = {}
    candidate_objects: set[str] = set()
    assigned_objects: set[str] = set()
    explicit_face_assignments = 0
    explicit_uv_assignments = 0
    graph_materials = 0

    def register_material(raw: dict[str, Any], fallback_id: str = "") -> str:
        nonlocal graph_materials
        payload = copy.deepcopy(raw)
        material_id = str(
            payload.get("source_material_id")
            or payload.get("native_id")
            or payload.get("id")
            or payload.get("name")
            or fallback_id
            or f"Material{len(materials) + 1}"
        )
        had_source_graph = isinstance(payload.get("source_graph"), dict) and bool(payload.get("source_graph"))
        if had_source_graph:
            graph_materials += 1
        else:
            payload["source_graph"] = {
                "schema": "tech_connector.host_material_payload.v1",
                "provider": provider,
                "payload": copy.deepcopy(raw),
            }
        portable = normalize_portable_material(
            payload,
            source_provider=provider,
            source_path=scene_path,
            material_id=material_id,
        ).to_dict()
        materials.setdefault(material_id, portable)
        raw_materials.setdefault(material_id, copy.deepcopy(raw))
        return material_id

    top_level = source.get("materials")
    if isinstance(top_level, list):
        for index, raw in enumerate(top_level):
            if isinstance(raw, dict):
                register_material(raw, f"Material{index + 1}")
    elif isinstance(top_level, dict):
        for material_id, raw in top_level.items():
            if isinstance(raw, dict):
                register_material(raw, str(material_id))

    objects = source.get("objects") or source.get("meshes") or []
    for object_index, obj in enumerate(objects if isinstance(objects, list) else []):
        if not isinstance(obj, dict) or str(obj.get("type") or "").lower() == "error":
            continue
        object_id = str(obj.get("native_id") or obj.get("id") or obj.get("name") or f"Object{object_index + 1}")
        geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
        object_type = str(obj.get("type") or "").lower()
        if geometry or "mesh" in object_type or isinstance(obj.get("materials"), list) or isinstance(obj.get("material"), dict):
            candidate_objects.add(object_id)
        object_materials = obj.get("materials") if isinstance(obj.get("materials"), list) else []
        if isinstance(obj.get("material"), dict):
            object_materials = [obj["material"], *object_materials]
        material_ids = [
            register_material(raw, f"{object_id}:slot{slot_index}")
            for slot_index, raw in enumerate(object_materials)
            if isinstance(raw, dict)
        ]
        explicit = obj.get("material_assignments") if isinstance(obj.get("material_assignments"), list) else []
        has_explicit_assignments = bool(explicit)
        rows = explicit or [
            {"material_id": material_id, "slot_index": slot_index}
            for slot_index, material_id in enumerate(material_ids)
        ]
        for row_index, raw_assignment in enumerate(rows):
            if not isinstance(raw_assignment, dict):
                continue
            inline_material = raw_assignment.get("material")
            material_id = str(raw_assignment.get("material_id") or raw_assignment.get("source_material_id") or "")
            if isinstance(inline_material, dict):
                material_id = register_material(inline_material, material_id)
            if not material_id and row_index < len(material_ids):
                material_id = material_ids[row_index]
            if not material_id or material_id not in materials:
                continue
            faces = raw_assignment.get("face_indices") or raw_assignment.get("faces") or []
            face_ranges = _compact_index_ranges(faces if isinstance(faces, (list, tuple)) else [])
            if face_ranges:
                explicit_face_assignments += 1
            uv_set = str(
                raw_assignment.get("uv_set")
                or geometry.get("active_uv_set")
                or geometry.get("uv_set")
                or "st"
            )
            uv_source = "explicit" if (
                raw_assignment.get("uv_set") or geometry.get("active_uv_set") or geometry.get("uv_set")
            ) else "inferred_default"
            if uv_source == "explicit":
                explicit_uv_assignments += 1
            slot_index = _nonnegative_int(raw_assignment.get("slot_index"), row_index)
            assignment = {
                "assignment_id": _stable_id(provider, object_id, material_id, str(slot_index), str(face_ranges)),
                "object_native_id": object_id,
                "material_id": material_id,
                "slot_index": slot_index,
                "assignment_level": "face" if face_ranges else (
                    "slot" if has_explicit_assignments or len(rows) > 1 else "object"
                ),
                "face_ranges": face_ranges,
                "uv_set": uv_set,
                "uv_set_source": uv_source,
            }
            assignments.append(assignment)
            assigned_objects.add(object_id)

    for material_id, material in materials.items():
        textures = material.get("textures") if isinstance(material.get("textures"), dict) else {}
        for channel, binding in textures.items():
            if not isinstance(binding, dict):
                continue
            path = str(binding.get("path") or "")
            if not path:
                continue
            asset_id = _stable_id("texture", str(Path(path).expanduser()).lower())
            asset = texture_assets.setdefault(asset_id, _texture_asset_record(path, scene_path))
            asset["asset_id"] = asset_id
            asset.setdefault("channels", [])
            asset.setdefault("material_ids", [])
            asset.setdefault("color_spaces", [])
            asset.setdefault("uv_sets", [])
            _append_unique(asset["channels"], str(channel))
            _append_unique(asset["material_ids"], material_id)
            _append_unique(asset["color_spaces"], str(binding.get("color_space") or ""))
            _append_unique(asset["uv_sets"], str(binding.get("uv_set") or "st"))
            binding.setdefault("metadata", {})["texture_asset_id"] = asset_id

    include_materials = bool((source.get("isolation") or {}).get("include_materials", True))
    missing_textures = sum(1 for asset in texture_assets.values() if not asset.get("exists"))
    assignment_status = _coverage_status(len(assigned_objects), len(candidate_objects), enabled=include_materials)
    face_status = "complete" if assignments and explicit_face_assignments == len(assignments) else (
        "partial" if explicit_face_assignments else "unavailable"
    )
    uv_status = "complete" if assignments and explicit_uv_assignments == len(assignments) else (
        "partial" if explicit_uv_assignments else "inferred"
    )
    texture_status = "not_applicable" if not texture_assets else ("complete" if not missing_textures else "partial")
    graph_status = "complete" if materials and graph_materials == len(materials) else (
        "partial" if graph_materials else ("payload_only" if materials else "unavailable")
    )
    limitations: list[str] = []
    if not include_materials:
        limitations.append("Material capture was disabled for this snapshot.")
    if candidate_objects and not assigned_objects:
        limitations.append("The provider did not expose material assignments for visible mesh objects.")
    if assignments and not explicit_face_assignments:
        limitations.append("Assignments are object or slot level; per-face assignments were not exposed.")
    if assignments and not explicit_uv_assignments:
        limitations.append("UV set names were not exposed; the portable default was inferred.")
    if missing_textures:
        limitations.append(f"{missing_textures} referenced texture asset(s) were unavailable at capture time.")
    if materials and not graph_materials:
        limitations.append("Raw host material payloads were preserved, but complete shader graphs were not exposed.")
    statuses = [assignment_status, face_status, uv_status, texture_status, graph_status]
    overall = "complete" if statuses and all(status in {"complete", "not_applicable"} for status in statuses) else (
        "partial" if materials or assignments else "unavailable"
    )
    parity = {
        "overall": overall,
        "material_definitions": {"status": "complete" if materials else "unavailable", "count": len(materials)},
        "object_assignments": {
            "status": assignment_status,
            "assigned_object_count": len(assigned_objects),
            "candidate_object_count": len(candidate_objects),
        },
        "face_assignments": {
            "status": face_status,
            "explicit_assignment_count": explicit_face_assignments,
            "assignment_count": len(assignments),
        },
        "uv_bindings": {
            "status": uv_status,
            "explicit_assignment_count": explicit_uv_assignments,
            "assignment_count": len(assignments),
        },
        "texture_assets": {
            "status": texture_status,
            "available_count": len(texture_assets) - missing_textures,
            "missing_count": missing_textures,
            "embedded_count": 0,
            "asset_count": len(texture_assets),
        },
        "source_graphs": {"status": graph_status, "graph_count": graph_materials, "material_count": len(materials)},
        "limitations": limitations,
    }
    return PortableLookdevState(
        provider,
        materials,
        tuple(assignments),
        texture_assets,
        {provider or "unknown": {"material_payloads": raw_materials}},
        parity,
    )


def normalize_portable_lookdev_state(
    payload: dict[str, Any] | None,
    *,
    source_provider: str = "",
    source_path: str = "",
) -> PortableLookdevState:
    """Normalize a saved lookdev state while retaining archive storage metadata."""

    source = copy.deepcopy(payload or {})
    if str(source.get("schema") or "") != PORTABLE_LOOKDEV_SCHEMA:
        return lookdev_state_from_snapshot(
            source,
            source_provider=source_provider,
            source_path=source_path,
        )
    provider = str(source_provider or source.get("source_provider") or "").strip().lower().split(":", 1)[0]
    materials: dict[str, dict[str, Any]] = {}
    for material_id, raw in (source.get("materials") or {}).items():
        if isinstance(raw, dict):
            materials[str(material_id)] = normalize_portable_material(
                raw,
                source_provider=provider,
                source_path=source_path,
                material_id=str(material_id),
            ).to_dict()
    assignments = tuple(dict(row) for row in source.get("assignments") or [] if isinstance(row, dict))
    assets = {
        str(asset_id): dict(asset)
        for asset_id, asset in (source.get("texture_assets") or {}).items()
        if isinstance(asset, dict)
    }
    return PortableLookdevState(
        provider,
        materials,
        assignments,
        assets,
        dict(source.get("host_extensions") or {}),
        dict(source.get("parity") or {}),
    )


def embed_portable_lookdev_textures(
    state: PortableLookdevState | dict[str, Any],
    *,
    source_id: str,
    max_file_bytes: int = 64 * 1024 * 1024,
    max_total_bytes: int = 256 * 1024 * 1024,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Embed bounded texture dependencies and keep oversized assets explicit."""

    result = state.to_dict() if isinstance(state, PortableLookdevState) else copy.deepcopy(state)
    blobs: dict[str, bytes] = {}
    total = 0
    safe_source = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(source_id))
    for asset_id, asset in sorted((result.get("texture_assets") or {}).items()):
        path = Path(str(asset.get("path") or "")).expanduser()
        size = _nonnegative_int(asset.get("size"), 0)
        asset["storage"] = "missing" if not asset.get("exists") else "external"
        if not asset.get("exists") or not path.is_file():
            continue
        if size > int(max_file_bytes) or total + size > int(max_total_bytes):
            asset["portable"] = False
            asset["embed_reason"] = "size_limit"
            continue
        try:
            payload = path.read_bytes()
        except OSError as exc:
            asset["portable"] = False
            asset["embed_reason"] = f"read_failed: {exc}"
            continue
        suffix = "".join(path.suffixes[-2:]) or ".bin"
        blob_name = f"scene_sources/{safe_source or 'source'}/textures/{asset_id}{suffix}"
        blobs[blob_name] = payload
        total += len(payload)
        asset.update({"storage": "embedded", "blob": blob_name, "portable": True, "embedded_size": len(payload)})
    embedded = sum(1 for asset in (result.get("texture_assets") or {}).values() if asset.get("storage") == "embedded")
    texture_parity = result.setdefault("parity", {}).setdefault("texture_assets", {})
    texture_parity["embedded_count"] = embedded
    texture_parity["external_count"] = sum(
        1 for asset in (result.get("texture_assets") or {}).values() if asset.get("storage") == "external"
    )
    texture_parity["portable_count"] = embedded
    blob_by_asset = {
        asset_id: str(asset.get("blob") or "")
        for asset_id, asset in (result.get("texture_assets") or {}).items()
        if asset.get("blob")
    }
    for material in (result.get("materials") or {}).values():
        for binding in (material.get("textures") or {}).values():
            metadata = binding.setdefault("metadata", {})
            blob_name = blob_by_asset.get(str(metadata.get("texture_asset_id") or ""))
            if blob_name:
                metadata["archive_blob"] = blob_name
    return result, blobs


def resolve_embedded_lookdev_textures(
    snapshot: dict[str, Any],
    state: PortableLookdevState | dict[str, Any],
    blobs: dict[str, bytes],
    *,
    cache_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Materialize verified archive textures and redirect cached host payloads."""

    result = copy.deepcopy(snapshot)
    lookdev = state.to_dict() if isinstance(state, PortableLookdevState) else copy.deepcopy(state)
    destination = Path(cache_root).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    resolved_assets: dict[str, str] = {}
    failures: list[str] = []
    for asset_id, asset in sorted((lookdev.get("texture_assets") or {}).items()):
        blob_name = str(asset.get("blob") or "")
        payload = blobs.get(blob_name) if blob_name else None
        if payload is None:
            continue
        expected_head = str(asset.get("head_sha256") or "")
        actual_head = hashlib.sha256(payload[:1024 * 1024]).hexdigest()
        if expected_head and actual_head != expected_head:
            failures.append(f"{asset_id}: checksum mismatch")
            continue
        source_suffixes = Path(str(asset.get("path") or "texture.bin")).suffixes[-2:]
        suffix = "".join(source_suffixes) or ".bin"
        output = destination / f"{asset_id}{suffix}"
        try:
            if not output.is_file() or output.stat().st_size != len(payload):
                temporary = destination / f".{asset_id}.tmp"
                temporary.write_bytes(payload)
                temporary.replace(output)
            resolved_assets[str(asset_id)] = str(output)
        except OSError as exc:
            failures.append(f"{asset_id}: {exc}")

    texture_paths_by_material: dict[str, dict[str, str]] = {}
    for material_id, material in (lookdev.get("materials") or {}).items():
        for channel, binding in (material.get("textures") or {}).items():
            metadata = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
            resolved = resolved_assets.get(str(metadata.get("texture_asset_id") or ""))
            if resolved:
                texture_paths_by_material.setdefault(str(material_id), {})[str(channel)] = resolved

    for obj in result.get("objects") or result.get("meshes") or []:
        if not isinstance(obj, dict):
            continue
        payloads = [material for material in (obj.get("materials") or []) if isinstance(material, dict)]
        if isinstance(obj.get("material"), dict):
            payloads.insert(0, obj["material"])
        for material in payloads:
            material_id = str(
                material.get("source_material_id")
                or material.get("native_id")
                or material.get("id")
                or material.get("name")
                or ""
            )
            replacements = texture_paths_by_material.get(material_id) or {}
            if not replacements:
                continue
            raw_paths = material.setdefault("texture_paths", {})
            for raw_channel, raw_binding in list(raw_paths.items()):
                resolved = replacements.get(canonical_texture_channel(str(raw_channel)))
                if not resolved:
                    continue
                if isinstance(raw_binding, dict):
                    raw_binding["path"] = resolved
                else:
                    raw_paths[raw_channel] = resolved
            for channel, resolved in replacements.items():
                raw_paths.setdefault(channel, resolved)
    return result, {
        "resolved_count": len(resolved_assets),
        "failure_count": len(failures),
        "failures": failures,
        "resolved_assets": resolved_assets,
    }


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8", errors="replace")).hexdigest()
    return digest[:24]


def _nonnegative_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(default))


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _compact_index_ranges(values: list[Any] | tuple[Any, ...]) -> list[list[int]]:
    parsed: set[int] = set()
    for value in values:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            parsed.add(index)
    indices = sorted(parsed)
    if not indices:
        return []
    ranges: list[list[int]] = []
    start = previous = indices[0]
    for value in indices[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append([start, previous])
        start = previous = value
    ranges.append([start, previous])
    return ranges


def _coverage_status(observed: int, expected: int, *, enabled: bool) -> str:
    if not enabled:
        return "disabled"
    if expected <= 0:
        return "not_applicable"
    if observed <= 0:
        return "unavailable"
    return "complete" if observed >= expected else "partial"


def _texture_asset_record(path: str, source_path: str) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    source_parent = Path(source_path).expanduser().parent if source_path else None
    if not candidate.is_absolute() and source_parent is not None:
        candidate = source_parent / candidate
    resolved = candidate.resolve(strict=False)
    record: dict[str, Any] = {
        "path": str(resolved),
        "source_relative_path": "",
        "exists": False,
        "size": 0,
        "mtime_ns": 0,
        "head_sha256": "",
        "storage": "missing",
        "portable": False,
    }
    if source_parent is not None:
        try:
            record["source_relative_path"] = str(resolved.relative_to(source_parent.resolve(strict=False)))
        except ValueError:
            pass
    if not resolved.is_file():
        return record
    try:
        stat = resolved.stat()
        with resolved.open("rb") as handle:
            head = handle.read(1024 * 1024)
        record.update({
            "exists": True,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "head_sha256": hashlib.sha256(head).hexdigest(),
            "storage": "external",
        })
    except OSError:
        pass
    return record


def canonical_texture_channel(channel: str) -> str:
    raw = str(channel or "").strip().lower()
    key = raw.replace("_", " ")
    return TEXTURE_CHANNEL_ALIASES.get(raw, TEXTURE_CHANNEL_ALIASES.get(key, key.replace(" ", "_")))


def viewer_material_approximation(material: PortableMaterial) -> dict[str, Any]:
    parameters = material.parameters
    return {
        "name": material.name,
        "source_material_id": material.material_id,
        "base_color": list(parameters["base_color"]),
        "roughness": float(parameters["specular_roughness"]),
        "metallic": float(parameters["metalness"]),
        "specular": float(parameters["specular_weight"]),
        "emission_color": list(parameters["emission_color"]),
        "opacity": float(parameters["opacity"]),
        "transmission": float(parameters["transmission_weight"]),
        "ior": float(parameters["specular_ior"]),
        "clearcoat": float(parameters["coat_weight"]),
        "textures": {key: binding.path for key, binding in material.textures.items()},
        "texture_color_spaces": {key: binding.color_space for key, binding in material.textures.items()},
        "approximation": material.approximation,
        "portable_material": material.to_dict(),
    }


def _texture_binding(
    channel: str,
    source_channel: str,
    raw_binding: Any,
    *,
    source_path: str,
) -> PortableTextureBinding | None:
    metadata: dict[str, Any] = {}
    if isinstance(raw_binding, dict):
        path = str(raw_binding.get("path") or raw_binding.get("file") or "")
        color_space = str(raw_binding.get("color_space") or raw_binding.get("colorspace") or "")
        uv_set = str(raw_binding.get("uv_set") or "st")
        wrap_u = str(raw_binding.get("wrap_u") or "periodic")
        wrap_v = str(raw_binding.get("wrap_v") or "periodic")
        metadata = {key: value for key, value in raw_binding.items() if key not in {
            "path", "file", "color_space", "colorspace", "uv_set", "wrap_u", "wrap_v"
        }}
    else:
        path = str(raw_binding or "")
        color_space = ""
        uv_set = "st"
        wrap_u = "periodic"
        wrap_v = "periodic"
    if not path:
        return None
    candidate = Path(path).expanduser()
    source_was_absolute = candidate.is_absolute()
    if not source_was_absolute and source_path:
        candidate = Path(source_path).expanduser().resolve().parent / candidate
    if candidate.exists():
        normalized_path = str(candidate.resolve())
    elif source_was_absolute:
        normalized_path = path
    else:
        normalized_path = str(candidate)
    if not color_space:
        color_space = "sRGB - Texture" if channel in COLOR_TEXTURE_CHANNELS else "Raw"
    return PortableTextureBinding(
        channel,
        normalized_path,
        color_space,
        uv_set,
        wrap_u,
        wrap_v,
        source_channel,
        metadata,
    )


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if result == result and abs(result) != float("inf") else float(default)


def _unit(value: Any, default: float) -> float:
    return max(0.0, min(1.0, _number(value, default)))


def _vector(value: Any, size: int, default: tuple[float, ...]) -> tuple[float, ...]:
    values = list(value) if isinstance(value, (list, tuple)) else list(default)
    values.extend(default[len(values):size])
    return tuple(_number(values[index], default[index]) for index in range(size))


__all__ = [
    "PORTABLE_LOOKDEV_SCHEMA",
    "PORTABLE_MATERIAL_SCHEMA",
    "PROVIDER_LOOKDEV_CAPTURE_PROFILES",
    "PortableLookdevState",
    "PortableMaterial",
    "PortableTextureBinding",
    "canonical_texture_channel",
    "embed_portable_lookdev_textures",
    "lookdev_state_from_snapshot",
    "normalize_portable_lookdev_state",
    "normalize_portable_material",
    "portable_material_runtime_capabilities",
    "provider_lookdev_capture_profile",
    "resolve_embedded_lookdev_textures",
    "viewer_material_approximation",
]
