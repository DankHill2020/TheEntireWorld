"""Deterministic deformation transfer planning and point-cache qualification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Sequence


DESTINATIONS = {"maya", "houdini", "blender", "unreal", "unity", "usd", "fbx", "gltf"}
_EDITABLE_PATHS = {
    "blend_shape": {"maya": "blendShape", "houdini": "blendshapes_sop",
                    "blender": "shape_keys", "unreal": "skeletal_mesh_morph_targets",
                    "unity": "skinned_mesh_blend_shapes", "usd": "usdskel_blend_shapes",
                    "fbx": "fbx_blend_shape_channels", "gltf": "morph_targets"},
    "muscle": {"maya": "cMuscle_pose_interpolator", "houdini": "muscles_and_tissue",
               "blender": "geometry_nodes_shape_keys", "unreal": "deformer_graph_ml_deformer",
               "unity": "compute_deformer_blend_shapes", "usd": "usdskel_blend_shapes",
               "fbx": "blend_shapes", "gltf": "morph_targets"},
    "flesh": {"maya": "skin_cluster_ncloth_proxy", "houdini": "vellum_softbody",
              "blender": "soft_body_mesh_deform", "unreal": "deformer_graph",
              "unity": "compute_deformer", "usd": "usdskel_blend_shapes",
              "fbx": "blend_shapes", "gltf": "morph_targets"},
    "jiggle": {"maya": "nhair_dynamic_joints", "houdini": "vellum_constraints",
               "blender": "geometry_nodes_soft_body", "unreal": "anim_dynamics_control_rig",
               "unity": "dynamic_bones_compute", "usd": "usdskel_animation",
               "fbx": "joint_animation", "gltf": "joint_animation"},
}


@dataclass(frozen=True)
class DeformationTransferArtifact:
    deformer_id: str
    deformer_type: str
    selected_path: str
    editable: bool
    fallback_chain: tuple[str, ...]
    preserves_canonical_skin: bool = True


def build_deformation_transfer_plan(rig_graph: Any, mesh_id: str, destination: str, *,
                                    prefer_editable: bool = True, frame_rate: float = 24.0,
                                    frame_count: int = 0) -> dict[str, Any]:
    """Choose a target path without claiming live-host qualification."""
    target = str(destination or "").strip().lower()
    if target not in DESTINATIONS:
        raise ValueError(f"Unsupported deformation transfer destination: {destination}")
    if frame_rate <= 0.0 or frame_count < 0:
        raise ValueError("Frame rate must be positive and frame count cannot be negative.")
    mesh_key = str(mesh_id)
    skins = sorted(str(identifier) for identifier, skin in (getattr(rig_graph, "skins", {}) or {}).items()
                   if str(skin.get("mesh_id") or "") == mesh_key)
    deformers = sorted(((str(identifier), item) for identifier, item in
                        (getattr(rig_graph, "deformers", {}) or {}).items()
                        if str(item.get("mesh_id") or "") == mesh_key
                        and str(item.get("type") or "") in _EDITABLE_PATHS
                        and bool(item.get("enabled", True))),
                       key=lambda pair: (int(pair[1].get("order", 0) or 0), pair[0]))
    artifacts = []
    for identifier, deformer in deformers:
        kind = str(deformer.get("type") or "")
        editable_path = _EDITABLE_PATHS[kind][target]
        cache_path = ("usd_time_sampled_points" if target == "usd" else
                      "geometry_cache" if target in {"unreal", "unity"} else "alembic_point_cache")
        artifacts.append(DeformationTransferArtifact(
            identifier, kind, editable_path if prefer_editable else cache_path, bool(prefer_editable),
            tuple(dict.fromkeys((editable_path, "corrective_or_morph_bake", cache_path))),
        ))
    gates = ["live_target_import", "target_playback_hash", "target_performance_budget"]
    if not frame_count and any(not artifact.editable for artifact in artifacts):
        gates.insert(0, "baked_frame_range")
    payload = {
        "schema": "tech_connector.deformation_transfer_plan.v1", "mesh_id": mesh_key,
        "destination": target,
        "canonical_skin": {"authoritative": True, "skin_ids": skins, "required": bool(artifacts)},
        "artifacts": [asdict(item) for item in artifacts],
        "cache": {"frame_rate": float(frame_rate), "frame_count": int(frame_count),
                  "topology_must_remain_constant": True, "space": "object"},
        "qualification": {"status": "contract_validated", "remaining_gates": gates,
                          "live_host_claimed": False},
    }
    payload["receipt_sha256"] = _sha(payload)
    return payload


def qualify_deformation_point_cache(frames: Sequence[Sequence[Sequence[float]]], *,
                                    expected_vertex_count: int | None = None) -> dict[str, Any]:
    """Validate constant topology, finite samples, and deterministic cache identity."""
    normalized: list[list[list[float]]] = []
    count = expected_vertex_count
    errors: list[str] = []
    for frame_index, frame in enumerate(frames):
        if count is None:
            count = len(frame)
        if len(frame) != count:
            errors.append(f"frame_{frame_index}:vertex_count_{len(frame)}_expected_{count}")
        output_frame = []
        for vertex_index, value in enumerate(frame):
            point = [float(item) for item in value]
            if len(point) != 3:
                errors.append(f"frame_{frame_index}:vertex_{vertex_index}:not_vec3")
                point = (point + [0.0, 0.0, 0.0])[:3]
            if not all(math.isfinite(item) for item in point):
                errors.append(f"frame_{frame_index}:vertex_{vertex_index}:non_finite")
                point = [item if math.isfinite(item) else 0.0 for item in point]
            output_frame.append(point)
        normalized.append(output_frame)
    payload = {
        "schema": "tech_connector.deformation_cache_qualification.v1",
        "qualified": bool(normalized) and not errors, "frame_count": len(normalized),
        "vertex_count": int(count or 0),
        "constant_topology": not any("vertex_count" in item for item in errors),
        "finite_samples": not any("non_finite" in item for item in errors), "errors": errors,
    }
    payload["sample_sha256"] = _sha(normalized)
    return payload


def _sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["DESTINATIONS", "DeformationTransferArtifact", "build_deformation_transfer_plan",
           "qualify_deformation_point_cache"]
