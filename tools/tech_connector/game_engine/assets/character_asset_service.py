"""Character LOD planning and compact runtime skin-binding compilation."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
import struct
from typing import Any, Iterable, Mapping


CHARACTER_PERFORMANCE_PROFILES: dict[str, dict[str, Any]] = {
    "mobile": {"max_influences": 2, "min_weight": 0.01, "mesh_lod_bias": 1, "bone_lod_bias": 1, "motion_vectors": False, "update_when_offscreen": False},
    "balanced": {"max_influences": 4, "min_weight": 0.001, "mesh_lod_bias": 0, "bone_lod_bias": 0, "motion_vectors": True, "update_when_offscreen": False},
    "high": {"max_influences": 4, "min_weight": 0.0005, "mesh_lod_bias": 0, "bone_lod_bias": 0, "motion_vectors": True, "update_when_offscreen": False},
    "hero": {"max_influences": 8, "min_weight": 0.0001, "mesh_lod_bias": 0, "bone_lod_bias": 0, "motion_vectors": True, "update_when_offscreen": False},
    "cinematic": {"max_influences": 8, "min_weight": 0.0, "mesh_lod_bias": 0, "bone_lod_bias": 0, "motion_vectors": True, "update_when_offscreen": True},
}


@dataclass(frozen=True)
class CharacterAssetIssue:
    severity: str
    code: str
    message: str
    fix: str = ""


def character_performance_profile(name: str) -> dict[str, Any]:
    key = str(name or "balanced").strip().casefold()
    if key not in CHARACTER_PERFORMANCE_PROFILES:
        raise KeyError(f"Unknown character performance profile: {name}")
    return {"name": key, **CHARACTER_PERFORMANCE_PROFILES[key]}


def recommended_mesh_lods(count: int = 4) -> list[dict[str, Any]]:
    targets = (
        (1.0, 100.0, 0.0, 8, 0),
        (0.5, 50.0, 0.5, 4, 1),
        (0.2, 25.0, 1.5, 4, 2),
        (0.08, 12.5, 4.0, 2, 3),
        (0.03, 6.25, 8.0, 2, 4),
    )
    return [
        {"level": level, "screen_size": screen, "triangle_percent": triangles,
         "max_deviation": deviation, "max_influences": influences,
         "bone_lod": bone_lod, "hysteresis": 0.02 if level else 0.0}
        for level, (screen, triangles, deviation, influences, bone_lod) in enumerate(targets[:max(1, min(5, int(count)))])
    ]


def generate_bone_lods(
    bones: Iterable[Mapping[str, Any] | str],
    *,
    count: int = 4,
    preserve_bones: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Build deterministic bone evaluation sets and parent remaps for mesh LODs."""

    normalized: list[dict[str, str]] = []
    for value in bones:
        if isinstance(value, Mapping):
            name = str(value.get("name") or value.get("id") or "").strip()
            parent = str(value.get("parent") or value.get("parent_id") or "").strip()
        else:
            name, parent = str(value).strip(), ""
        if name:
            normalized.append({"name": name, "parent": parent})
    by_name = {item["name"]: item for item in normalized}
    required = {str(value) for value in preserve_bones}
    roots = {item["name"] for item in normalized if not item["parent"] or item["parent"] not in by_name}
    required.update(roots)

    def detail_level(name: str) -> int:
        key = name.casefold()
        if any(token in key for token in ("root", "pelvis", "hips", "spine", "chest", "neck", "head", "clav", "upperarm", "lowerarm", "thigh", "calf")):
            return 4
        if any(token in key for token in ("hand", "foot", "jaw", "eye")):
            return 3
        if any(token in key for token in ("twist", "roll", "helper", "corrective")):
            return 2
        if any(token in key for token in ("finger", "thumb", "toe", "face", "brow", "lip", "cheek")):
            return 1
        return 3

    results: list[dict[str, Any]] = []
    thresholds = (0, 1, 2, 3, 4)
    for level in range(max(1, min(5, int(count)))):
        threshold = thresholds[level]
        retained = {item["name"] for item in normalized if detail_level(item["name"]) >= threshold} | required
        # Every retained bone requires its ancestor chain for stable local transforms.
        for name in tuple(retained):
            parent = by_name.get(name, {}).get("parent", "")
            while parent in by_name and parent not in retained:
                retained.add(parent)
                parent = by_name[parent]["parent"]
        remap: dict[str, str] = {}
        for item in normalized:
            if item["name"] in retained:
                continue
            parent = item["parent"]
            while parent and parent not in retained:
                parent = by_name.get(parent, {}).get("parent", "")
            remap[item["name"]] = parent or next(iter(sorted(roots)), "")
        results.append({
            "level": level, "retained_bones": sorted(retained), "removed_bones": sorted(set(by_name) - retained),
            "parent_remap": dict(sorted(remap.items())), "evaluation_rate_divisor": 1 if level < 2 else 2 if level == 2 else 4,
        })
    return results


def validate_character_lods(properties: Mapping[str, Any]) -> tuple[CharacterAssetIssue, ...]:
    values = dict(properties or {})
    lods = list(values.get("lods") or ())
    bone_lods = list(values.get("bone_lods") or ())
    issues: list[CharacterAssetIssue] = []
    if not lods:
        issues.append(CharacterAssetIssue("warning", "missing_mesh_lods", "No Mesh LODs are authored.", "Generate Recommended LODs."))
    for index, lod in enumerate(lods):
        screen = float(lod.get("screen_size", 0.0))
        triangles = float(lod.get("triangle_percent", 0.0))
        influences = int(lod.get("max_influences", 4) or 4)
        if index == 0 and (screen != 1.0 or triangles != 100.0):
            issues.append(CharacterAssetIssue("error", "invalid_lod0", "LOD 0 must preserve screen size 1.0 and 100% geometry."))
        if index and (screen >= float(lods[index - 1].get("screen_size", 0.0)) or triangles >= float(lods[index - 1].get("triangle_percent", 0.0))):
            issues.append(CharacterAssetIssue("error", "unordered_lods", f"LOD {index} must reduce screen size and triangle percentage."))
        if influences not in {1, 2, 4, 8, 12, 16, 32}:
            issues.append(CharacterAssetIssue("error", "invalid_influence_budget", f"LOD {index} has unsupported influence budget {influences}."))
    for index, bone_lod in enumerate(bone_lods):
        retained = set(bone_lod.get("retained_bones") or ())
        removed = set(bone_lod.get("removed_bones") or ())
        if retained & removed:
            issues.append(CharacterAssetIssue("error", "bone_lod_overlap", f"Bone LOD {index} retains and removes the same bone."))
        if any(target and target not in retained for target in dict(bone_lod.get("parent_remap") or {}).values()):
            issues.append(CharacterAssetIssue("error", "invalid_bone_remap", f"Bone LOD {index} remaps to a bone that is not retained."))
    return tuple(issues)


def validate_skin_binding_properties(properties: Mapping[str, Any]) -> tuple[CharacterAssetIssue, ...]:
    values = dict(properties or {})
    issues: list[CharacterAssetIssue] = []
    authored_rows = list(values.get("vertex_weights") or ())
    if not authored_rows:
        return (CharacterAssetIssue("warning", "empty_skin_binding", "Skin Binding has no materialized DCC weights yet.", "Import or attach a .tcskin payload."),)
    if not values.get("mesh_id"):
        issues.append(CharacterAssetIssue("error", "missing_mesh", "Assign the Skeletal Mesh receiving these weights."))
    if not values.get("skeleton_id"):
        issues.append(CharacterAssetIssue("error", "missing_skeleton", "Assign the Skeleton providing influences."))
    influence_names = {str(item.get("name") or item.get("id") or "") for item in values.get("influences") or () if isinstance(item, Mapping)}
    seen: set[int] = set()
    for row in authored_rows:
        index = int(row.get("vertex_index", -1))
        weights = dict(row.get("weights") or {})
        if index < 0 or index in seen:
            issues.append(CharacterAssetIssue("error", "invalid_vertex", f"Skin Binding has duplicate or invalid vertex index {index}."))
        seen.add(index)
        if set(weights) - influence_names:
            issues.append(CharacterAssetIssue("error", "missing_influence", f"Vertex {index} references an influence absent from the Skeleton."))
        total = sum(float(value) for value in weights.values())
        if not math.isfinite(total) or abs(total - 1.0) > 1.0e-4:
            issues.append(CharacterAssetIssue("error", "unnormalized_weights", f"Vertex {index} weights total {total:.6g}, not 1.0."))
    return tuple(issues)


def compile_skin_binding_payload(
    properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high",
) -> bytes:
    """Compile compact fixed-width GPU weights without altering source DCC weights."""

    values = dict(properties or {})
    errors = [item.message for item in validate_skin_binding_properties(values) if item.severity == "error"]
    if errors:
        raise ValueError("Skin Binding cannot be cooked: " + "; ".join(errors))
    profile_name = str(dict(values.get("platform_overrides") or {}).get(str(platform)) or values.get("performance_profile") or quality or "balanced")
    if profile_name not in CHARACTER_PERFORMANCE_PROFILES:
        profile_name = "high" if str(quality).casefold() in {"high", "hero", "cinematic"} else "balanced"
    profile = character_performance_profile(profile_name)
    width = max(1, min(32, int(profile["max_influences"])))
    threshold = max(0.0, float(profile["min_weight"]))
    influences = [dict(item) for item in values.get("influences") or ()]
    joint_index = {str(item.get("name") or item.get("id") or ""): index for index, item in enumerate(influences)}
    index_bits = 8 if len(influences) <= 256 else 16
    rows = {int(item.get("vertex_index", 0)): dict(item.get("weights") or {}) for item in values.get("vertex_weights") or ()}
    topology = dict(values.get("topology") or {})
    vertex_count = int(topology.get("vertex_count", max(rows, default=-1) + 1) or 0)
    indices: list[int] = []
    weights_u16: list[int] = []
    reduced_vertices = 0
    max_discarded = 0.0
    for vertex in range(vertex_count):
        source = sorted(((name, float(weight)) for name, weight in rows.get(vertex, {}).items() if float(weight) > 0.0), key=lambda item: item[1], reverse=True)
        kept = [item for item in source if item[1] >= threshold] or source[:1]
        kept = kept[:width]
        discarded = max(0.0, sum(weight for _name, weight in source) - sum(weight for _name, weight in kept))
        if discarded > 1.0e-12:
            reduced_vertices += 1
            max_discarded = max(max_discarded, discarded)
        total = sum(weight for _name, weight in kept)
        normalized = [(name, weight / total) for name, weight in kept] if total > 0.0 else []
        quantized = [int(round(weight * 65535.0)) for _name, weight in normalized]
        if quantized:
            quantized[0] += 65535 - sum(quantized)
        for slot in range(width):
            if slot < len(normalized):
                indices.append(joint_index[normalized[slot][0]])
                weights_u16.append(quantized[slot])
            else:
                indices.append(0); weights_u16.append(0)
    index_format = "B" if index_bits == 8 else "H"
    index_bytes = struct.pack("<" + index_format * len(indices), *indices) if indices else b""
    weight_bytes = struct.pack("<" + "H" * len(weights_u16), *weights_u16) if weights_u16 else b""
    payload = {
        "schema": "tech_connector.cooked_skin_binding.v1",
        "platform": str(platform), "quality": str(quality), "profile": profile,
        "mesh_id": str(values.get("mesh_id") or ""), "skeleton_id": str(values.get("skeleton_id") or ""),
        "topology": topology, "vertex_count": vertex_count, "joint_count": len(influences),
        "layout": {"fixed_influence_width": width, "joint_index_bits": index_bits, "weight_format": "unorm16", "little_endian": True},
        "buffers": {"joint_indices": base64.b64encode(index_bytes).decode("ascii"), "weights": base64.b64encode(weight_bytes).decode("ascii")},
        "performance": {"buffer_bytes": len(index_bytes) + len(weight_bytes), "bytes_per_vertex": width * (index_bits // 8 + 2),
                        "vertices_reduced": reduced_vertices, "max_discarded_weight": max_discarded,
                        "source_weights_preserved": True, "vertex_order_optimization": "cook_stage", "index_order_optimization": "cook_stage"},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compile_skeletal_mesh_plan(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    values = dict(properties or {})
    errors = [item.message for item in validate_character_lods(values) if item.severity == "error"]
    if errors:
        raise ValueError("Skeletal Mesh cannot be cooked: " + "; ".join(errors))
    profile_name = str(dict(values.get("platform_overrides") or {}).get(str(platform)) or values.get("performance_profile") or "balanced")
    profile = character_performance_profile(profile_name)
    payload = {
        "schema": "tech_connector.cooked_skeletal_mesh_plan.v1", "platform": str(platform), "quality": str(quality),
        "skeleton_id": str(values.get("skeleton_id") or ""), "skin_binding_id": str(values.get("skin_binding_id") or ""),
        "lods": list(values.get("lods") or ()), "bone_lods": list(values.get("bone_lods") or ()),
        "lod_artifacts": list(values.get("lod_artifacts") or ()),
        "lod_generation_receipt": dict(values.get("lod_generation_receipt") or {}),
        "performance_profile": profile, "bounds": dict(values.get("bounds") or {}),
        "runtime_policy": {"visibility_culling": True, "update_when_offscreen": bool(profile["update_when_offscreen"]),
                           "motion_vectors": bool(profile["motion_vectors"]), "flatten_transform_hierarchy": True},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "CHARACTER_PERFORMANCE_PROFILES", "CharacterAssetIssue", "character_performance_profile",
    "compile_skeletal_mesh_plan", "compile_skin_binding_payload", "generate_bone_lods",
    "recommended_mesh_lods", "validate_character_lods", "validate_skin_binding_properties",
]
