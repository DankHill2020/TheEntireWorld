from __future__ import annotations

"""Host-neutral skinning utilities for TC-native and bridged DCC workflows."""

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from math import dist, isfinite
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from tech_connector.game_engine.deformation.spatial_skin_smoothing_service import spatial_smooth_weight_rows


SKIN_BIND_METHODS: dict[str, dict[str, Any]] = {
    "distance": {
        "label": "Closest Distance",
        "solver_status": "implemented",
        "maya_bind_method": 0,
        "notes": "Fast fallback bind based on joint-to-vertex distance.",
    },
    "heat": {
        "label": "Heat Map",
        "solver_status": "compatibility_preset",
        "maya_bind_method": 2,
        "notes": "Routes to host heat-map bind where available; TC native currently uses distance initialization plus metadata.",
    },
    "geodesic_voxel": {
        "label": "Geodesic Voxel",
        "solver_status": "compatibility_preset",
        "maya_bind_method": 3,
        "notes": "Routes to host geodesic voxel bind where available; TC native voxel/geodesic solver is planned.",
    },
    "current": {
        "label": "Current / Existing Weights",
        "solver_status": "metadata_only",
        "maya_bind_method": 4,
        "notes": "Preserve or rebind from existing host weights when available.",
    },
    "auto": {
        "label": "TC Auto Skinner",
        "solver_status": "implemented",
        "maya_bind_method": 2,
        "notes": "TC auto preset picks an engine-safe bind method and post-processes normalize/prune/smooth.",
    },
}


@dataclass(frozen=True)
class SkinInfluence:
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    locked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkinVertexWeights:
    vertex_index: int
    weights: dict[str, float] = field(default_factory=dict)

    def normalized(self, *, max_influences: int = 4, threshold: float = 0.0) -> SkinVertexWeights:
        return replace(
            self,
            weights=normalize_skin_weights(self.weights, max_influences=max_influences, threshold=threshold),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkinClusterState:
    mesh_id: str
    influences: tuple[SkinInfluence, ...]
    vertex_weights: tuple[SkinVertexWeights, ...]
    max_influences: int = 4
    normalize: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def influence_names(self) -> tuple[str, ...]:
        return tuple(influence.name for influence in self.influences)

    @property
    def vertex_count(self) -> int:
        return len(self.vertex_weights)

    def with_vertex_weights(self, vertex_weights: Iterable[SkinVertexWeights]) -> SkinClusterState:
        rows = tuple(
            row.normalized(max_influences=self.max_influences) if self.normalize else row
            for row in vertex_weights
        )
        return replace(self, vertex_weights=rows)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkinningOperationResult:
    ok: bool
    operation: str
    cluster: SkinClusterState | None = None
    changed_vertices: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkinWeightImportResult:
    cluster: SkinClusterState
    warnings: tuple[str, ...] = ()
    source_summary: dict[str, Any] = field(default_factory=dict)
    topology_matched: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_weight(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(number):
        return 0.0
    return max(0.0, number)


def normalize_skin_weights(
    weights: Mapping[str, Any],
    *,
    max_influences: int = 4,
    threshold: float = 0.0,
) -> dict[str, float]:
    max_count = max(1, int(max_influences or 1))
    threshold_value = max(0.0, float(threshold or 0.0))
    cleaned = {
        str(name): _clean_weight(value)
        for name, value in dict(weights or {}).items()
        if str(name) and _clean_weight(value) > threshold_value
    }
    if not cleaned:
        return {}
    top_items = sorted(cleaned.items(), key=lambda item: (-item[1], item[0]))[:max_count]
    total = sum(value for _, value in top_items)
    if total <= 0.0:
        return {}
    return {name: value / total for name, value in top_items}


def prune_skin_weights(
    weights: Mapping[str, Any],
    *,
    threshold: float = 0.001,
    max_influences: int = 4,
) -> dict[str, float]:
    return normalize_skin_weights(weights, max_influences=max_influences, threshold=threshold)


def mirror_influence_name(name: str) -> str:
    source = str(name or "")
    replacements = (
        ("Left", "Right"),
        ("right", "left"),
        ("left", "right"),
        ("_L_", "_R_"),
        ("_R_", "_L_"),
        (".L", ".R"),
        (".R", ".L"),
        ("_L", "_R"),
        ("_R", "_L"),
        ("L_", "R_"),
        ("R_", "L_"),
    )
    for left, right in replacements:
        if left in source:
            return source.replace(left, right, 1)
    return source


def bind_skin_from_distance(
    *,
    mesh_id: str,
    vertices: Sequence[Sequence[float]],
    influences: Sequence[SkinInfluence | Mapping[str, Any] | str],
    max_influences: int = 4,
    falloff: float = 2.0,
) -> SkinClusterState:
    influence_rows = tuple(_coerce_influence(influence) for influence in influences)
    exponent = max(0.001, float(falloff or 2.0))
    rows: list[SkinVertexWeights] = []
    for index, vertex in enumerate(vertices):
        position = _coerce_position(vertex)
        raw_weights: dict[str, float] = {}
        for influence in influence_rows:
            distance = max(0.0001, dist(position, influence.position))
            raw_weights[influence.name] = 1.0 / (distance**exponent)
        rows.append(
            SkinVertexWeights(
                vertex_index=index,
                weights=normalize_skin_weights(raw_weights, max_influences=max_influences),
            )
        )
    return SkinClusterState(
        mesh_id=str(mesh_id or ""),
        influences=influence_rows,
        vertex_weights=tuple(rows),
        max_influences=max(1, int(max_influences or 1)),
        normalize=True,
        metadata={"bind_method": "distance", "falloff": exponent},
    )


def available_skin_bind_methods() -> list[dict[str, Any]]:
    return [{"key": key, **dict(value)} for key, value in SKIN_BIND_METHODS.items()]


def bind_skin(
    *,
    mesh_id: str,
    vertices: Sequence[Sequence[float]],
    influences: Sequence[SkinInfluence | Mapping[str, Any] | str],
    bind_method: str = "heat",
    max_influences: int = 4,
    falloff: float = 2.0,
) -> SkinningOperationResult:
    method_key = normalize_bind_method(bind_method)
    cluster = bind_skin_from_distance(
        mesh_id=mesh_id,
        vertices=vertices,
        influences=influences,
        max_influences=max_influences,
        falloff=falloff,
    )
    metadata = {
        **cluster.metadata,
        "bind_method": method_key,
        "bind_label": SKIN_BIND_METHODS[method_key]["label"],
        "solver_status": SKIN_BIND_METHODS[method_key]["solver_status"],
        "bind_notes": SKIN_BIND_METHODS[method_key]["notes"],
    }
    warnings = ()
    if SKIN_BIND_METHODS[method_key]["solver_status"] == "compatibility_preset":
        warnings = (f"TC-native {SKIN_BIND_METHODS[method_key]['label']} solver is planned; initialized with distance weights for now.",)
    return SkinningOperationResult(
        True,
        "bind_skin",
        replace(cluster, metadata=metadata),
        changed_vertices=tuple(range(cluster.vertex_count)),
        warnings=warnings,
    )


def auto_skin_cluster(
    *,
    mesh_id: str,
    vertices: Sequence[Sequence[float]],
    influences: Sequence[SkinInfluence | Mapping[str, Any] | str],
    bind_method: str = "auto",
    max_influences: int = 4,
    falloff: float = 2.0,
    prune_threshold: float = 0.001,
    smooth_iterations: int = 1,
) -> SkinningOperationResult:
    result = bind_skin(
        mesh_id=mesh_id,
        vertices=vertices,
        influences=influences,
        bind_method=bind_method,
        max_influences=max_influences,
        falloff=falloff,
    )
    cluster = result.cluster
    rows = [
        SkinVertexWeights(row.vertex_index, prune_skin_weights(row.weights, threshold=prune_threshold, max_influences=max_influences))
        for row in cluster.vertex_weights
    ]
    cluster = cluster.with_vertex_weights(rows)
    if smooth_iterations:
        cluster = smooth_skin_weights(cluster, iterations=smooth_iterations, strength=0.35).cluster
    return SkinningOperationResult(
        True,
        "auto_skin_cluster",
        replace(cluster, metadata={**cluster.metadata, "auto_skinner": True, "prune_threshold": prune_threshold}),
        changed_vertices=tuple(range(cluster.vertex_count)),
        warnings=result.warnings,
    )


def influences_from_rig_graph(
    rig_graph: Any,
    *,
    joint_ids: Sequence[str] | None = None,
) -> tuple[SkinInfluence, ...]:
    joints = dict(getattr(rig_graph, "joints", {}) or {})
    selected_ids = [str(joint_id) for joint_id in (joint_ids or joints.keys()) if str(joint_id) in joints]
    influences: list[SkinInfluence] = []
    for joint_id in selected_ids:
        joint = dict(joints.get(joint_id) or {})
        matrix = joint.get("bind_world_matrix") or joint.get("world_matrix") or joint.get("local_matrix") or ()
        influences.append(
            SkinInfluence(
                name=joint_id,
                position=_matrix_translation(matrix),
                locked=bool(joint.get("locked", False)),
                metadata={
                    "display_name": str(joint.get("name") or joint_id),
                    "parent_id": str(joint.get("parent_id") or ""),
                    "source_ref": dict(joint.get("source_ref") or {}),
                },
            )
        )
    return tuple(influences)


def apply_skin_cluster_to_rig_graph(
    rig_graph: Any,
    cluster: SkinClusterState,
    *,
    skin_id: str | None = None,
    replace_existing: bool = True,
) -> str:
    joint_ids = list(cluster.influence_names)
    missing = [joint_id for joint_id in joint_ids if joint_id not in getattr(rig_graph, "joints", {})]
    if missing:
        raise KeyError("Skin cluster references joints that are not in the TC rig graph: " + ", ".join(missing[:8]))
    native_skin_id = str(skin_id or f"tc::{cluster.mesh_id}::skin")
    if native_skin_id in getattr(rig_graph, "skins", {}) and replace_existing:
        rig_graph.skins.pop(native_skin_id, None)
    if native_skin_id not in getattr(rig_graph, "skins", {}):
        rig_graph.add_skin(
            cluster.mesh_id,
            joint_ids,
            skin_id=native_skin_id,
            source_ref={},
        )
    skin = rig_graph.skins[native_skin_id]
    skin.update(
        {
            "vertex_count": cluster.vertex_count,
            "deformation_mode": "linear_blend_skinning",
            "runtime_mode": "tc_native",
            "max_influences_per_vertex": cluster.max_influences,
            "weight_encoding": "tc_weight_overrides",
            "metadata": dict(cluster.metadata),
        }
    )
    for row in cluster.vertex_weights:
        if row.weights:
            rig_graph.set_vertex_weights(native_skin_id, row.vertex_index, row.weights)
    return native_skin_id


def auto_skin_rig_graph(
    rig_graph: Any,
    *,
    mesh_id: str,
    vertices: Sequence[Sequence[float]],
    joint_ids: Sequence[str] | None = None,
    bind_method: str = "auto",
    max_influences: int = 4,
    falloff: float = 2.0,
    prune_threshold: float = 0.001,
    smooth_iterations: int = 1,
    skin_id: str | None = None,
) -> SkinningOperationResult:
    influences = influences_from_rig_graph(rig_graph, joint_ids=joint_ids)
    if not influences:
        return SkinningOperationResult(False, "auto_skin_rig_graph", warnings=("The TC rig graph has no joints to use as skin influences.",))
    result = auto_skin_cluster(
        mesh_id=mesh_id,
        vertices=vertices,
        influences=influences,
        bind_method=bind_method,
        max_influences=max_influences,
        falloff=falloff,
        prune_threshold=prune_threshold,
        smooth_iterations=smooth_iterations,
    )
    if result.cluster is None:
        return result
    native_skin_id = apply_skin_cluster_to_rig_graph(rig_graph, result.cluster, skin_id=skin_id)
    return SkinningOperationResult(
        result.ok,
        "auto_skin_rig_graph",
        replace(result.cluster, metadata={**result.cluster.metadata, "rig_graph_skin_id": native_skin_id}),
        changed_vertices=result.changed_vertices,
        warnings=result.warnings,
        metadata={"skin_id": native_skin_id, "joint_count": len(influences)},
    )


def paint_skin_weight(
    cluster: SkinClusterState,
    *,
    vertex_indices: Iterable[int],
    influence: str,
    value: float,
    mode: str = "replace",
    strength: float = 1.0,
) -> SkinningOperationResult:
    target_indices = {int(index) for index in vertex_indices}
    influence_name = str(influence or "")
    if not influence_name:
        return SkinningOperationResult(False, "paint_skin_weight", cluster, warnings=("Influence is required.",))
    amount = max(0.0, min(1.0, float(value)))
    blend = max(0.0, min(1.0, float(strength)))
    rows: list[SkinVertexWeights] = []
    changed: list[int] = []
    for row in cluster.vertex_weights:
        if row.vertex_index not in target_indices:
            rows.append(row)
            continue
        weights = dict(row.weights)
        current = _clean_weight(weights.get(influence_name, 0.0))
        if mode == "add":
            weights[influence_name] = current + amount * blend
        elif mode == "scale":
            weights[influence_name] = current * amount
        elif mode == "smooth":
            neighbor_average = sum(weights.values()) / max(1, len(weights))
            weights[influence_name] = current + (neighbor_average - current) * blend
        else:
            weights[influence_name] = current + (amount - current) * blend
        rows.append(
            SkinVertexWeights(
                row.vertex_index,
                normalize_skin_weights(weights, max_influences=cluster.max_influences),
            )
        )
        changed.append(row.vertex_index)
    return SkinningOperationResult(
        True,
        "paint_skin_weight",
        cluster.with_vertex_weights(rows),
        changed_vertices=tuple(changed),
    )


def smooth_skin_weights(
    cluster: SkinClusterState,
    *,
    vertex_indices: Iterable[int] | None = None,
    iterations: int = 1,
    strength: float = 0.5,
) -> SkinningOperationResult:
    selected = {int(index) for index in vertex_indices} if vertex_indices is not None else None
    rows = list(cluster.vertex_weights)
    influence_names = cluster.influence_names
    blend = max(0.0, min(1.0, float(strength)))
    for _ in range(max(1, int(iterations or 1))):
        next_rows: list[SkinVertexWeights] = []
        for offset, row in enumerate(rows):
            if selected is not None and row.vertex_index not in selected:
                next_rows.append(row)
                continue
            neighbors = [rows[i] for i in (offset - 1, offset, offset + 1) if 0 <= i < len(rows)]
            averaged = {
                name: sum(neighbor.weights.get(name, 0.0) for neighbor in neighbors) / len(neighbors)
                for name in influence_names
            }
            blended = {
                name: row.weights.get(name, 0.0) + (averaged.get(name, 0.0) - row.weights.get(name, 0.0)) * blend
                for name in influence_names
            }
            next_rows.append(
                SkinVertexWeights(
                    row.vertex_index,
                    normalize_skin_weights(blended, max_influences=cluster.max_influences),
                )
            )
        rows = next_rows
    changed = tuple(row.vertex_index for row in rows if selected is None or row.vertex_index in selected)
    return SkinningOperationResult(True, "smooth_skin_weights", cluster.with_vertex_weights(rows), changed)


def spatial_smooth_skin_weights(
    cluster: SkinClusterState,
    *,
    positions: Sequence[Sequence[float]],
    normals: Sequence[Sequence[float]] | None = None,
    center: Sequence[float] | None = None,
    radius: float = 1.0,
    strength: float = 0.5,
    iterations: int = 1,
    target_indices: Iterable[int] | None = None,
    normal_angle: float = 120.0,
    max_neighbors: int = 96,
    hardness: float = 0.5,
) -> SkinningOperationResult:
    """Apply the shared topology-independent smoothing kernel to a skin."""
    rows, changed = spatial_smooth_weight_rows(
        positions,
        [row.weights for row in cluster.vertex_weights],
        radius=radius,
        strength=strength,
        iterations=iterations,
        target_indices=target_indices,
        center=center,
        normals=normals,
        normal_angle=normal_angle,
        max_neighbors=max_neighbors,
        max_influences=cluster.max_influences,
        locked_influences=(item.name for item in cluster.influences if item.locked),
        hardness=hardness,
    )
    output = tuple(SkinVertexWeights(index, row) for index, row in enumerate(rows))
    return SkinningOperationResult(
        True,
        "spatial_smooth_skin_weights",
        replace(cluster, vertex_weights=output),
        changed_vertices=changed,
        metadata={"surface_spatial": True, "radius": float(radius), "center": tuple(center) if center else None},
    )


def normalize_skin_cluster(cluster: SkinClusterState) -> SkinningOperationResult:
    rows = tuple(
        SkinVertexWeights(
            row.vertex_index,
            normalize_skin_weights(row.weights, max_influences=cluster.max_influences),
        )
        for row in cluster.vertex_weights
    )
    return SkinningOperationResult(
        True,
        "normalize_skin_weights",
        replace(cluster, vertex_weights=rows),
        changed_vertices=tuple(row.vertex_index for row in rows),
    )


def prune_skin_cluster(
    cluster: SkinClusterState,
    *,
    threshold: float = 0.001,
    max_influences: int | None = None,
) -> SkinningOperationResult:
    maximum = max(1, min(32, int(max_influences or cluster.max_influences)))
    rows = tuple(
        SkinVertexWeights(
            row.vertex_index,
            prune_skin_weights(row.weights, threshold=threshold, max_influences=maximum),
        )
        for row in cluster.vertex_weights
    )
    return SkinningOperationResult(
        True,
        "prune_skin_weights",
        replace(cluster, vertex_weights=rows, max_influences=maximum),
        changed_vertices=tuple(row.vertex_index for row in rows),
    )


def add_skin_influence(cluster: SkinClusterState, influence: SkinInfluence) -> SkinningOperationResult:
    if not influence.name:
        return SkinningOperationResult(False, "add_skin_influence", cluster, warnings=("Influence name is required.",))
    if influence.name in cluster.influence_names:
        return SkinningOperationResult(True, "add_skin_influence", cluster, warnings=("Influence already exists.",))
    return SkinningOperationResult(True, "add_skin_influence", replace(cluster, influences=cluster.influences + (influence,)))


def remove_skin_influence(
    cluster: SkinClusterState,
    influence_name: str,
    *,
    fallback_influence: str = "",
) -> SkinningOperationResult:
    name = str(influence_name or "")
    if name not in cluster.influence_names:
        return SkinningOperationResult(False, "remove_skin_influence", cluster, warnings=(f"Unknown influence: {name}",))
    fallback = str(fallback_influence or "")
    if fallback and (fallback == name or fallback not in cluster.influence_names):
        return SkinningOperationResult(False, "remove_skin_influence", cluster, warnings=("Fallback influence must be a different influence in the cluster.",))
    rows: list[SkinVertexWeights] = []
    for row in cluster.vertex_weights:
        weights = dict(row.weights)
        removed = weights.pop(name, 0.0)
        if removed and fallback:
            weights[fallback] = weights.get(fallback, 0.0) + removed
        normalized = normalize_skin_weights(weights, max_influences=cluster.max_influences)
        if row.weights and not normalized:
            return SkinningOperationResult(
                False,
                "remove_skin_influence",
                cluster,
                warnings=(f"Vertex {row.vertex_index} would become unweighted; provide fallback_influence.",),
            )
        rows.append(SkinVertexWeights(row.vertex_index, normalized))
    influences = tuple(item for item in cluster.influences if item.name != name)
    return SkinningOperationResult(
        True,
        "remove_skin_influence",
        replace(cluster, influences=influences, vertex_weights=tuple(rows)),
        changed_vertices=tuple(row.vertex_index for row in rows if name in row.weights),
    )


def mirror_skin_weights(cluster: SkinClusterState) -> SkinningOperationResult:
    mirrored_influences: list[SkinInfluence] = []
    seen_names: set[str] = set()
    for influence in cluster.influences:
        mirrored_name = mirror_influence_name(influence.name)
        if mirrored_name not in seen_names:
            mirrored_influences.append(replace(influence, name=mirrored_name))
            seen_names.add(mirrored_name)
    mirrored_rows = []
    for row in cluster.vertex_weights:
        mirrored = {mirror_influence_name(name): value for name, value in row.weights.items()}
        mirrored_rows.append(
            SkinVertexWeights(
                row.vertex_index,
                normalize_skin_weights(mirrored, max_influences=cluster.max_influences),
            )
        )
    return SkinningOperationResult(
        True,
        "mirror_skin_weights",
        replace(cluster.with_vertex_weights(mirrored_rows), influences=tuple(mirrored_influences)),
        changed_vertices=tuple(row.vertex_index for row in mirrored_rows),
    )


def copy_skin_weights(
    source: SkinClusterState,
    *,
    target_mesh_id: str,
    target_vertex_count: int | None = None,
) -> SkinClusterState:
    count = int(target_vertex_count if target_vertex_count is not None else source.vertex_count)
    rows = []
    for index in range(max(0, count)):
        source_row = source.vertex_weights[min(index, max(0, source.vertex_count - 1))] if source.vertex_weights else SkinVertexWeights(index)
        rows.append(SkinVertexWeights(index, dict(source_row.weights)))
    return SkinClusterState(
        mesh_id=str(target_mesh_id or source.mesh_id),
        influences=source.influences,
        vertex_weights=tuple(rows),
        max_influences=source.max_influences,
        normalize=source.normalize,
        metadata={**source.metadata, "copy_strategy": "index"},
    )


def transfer_skin_weights(
    source: SkinClusterState,
    *,
    target_mesh_id: str,
    target_vertex_count: int | None = None,
    strategy: str = "index",
) -> SkinningOperationResult:
    cluster = copy_skin_weights(source, target_mesh_id=target_mesh_id, target_vertex_count=target_vertex_count)
    cluster = replace(cluster, metadata={**cluster.metadata, "transfer_strategy": str(strategy or "index")})
    return SkinningOperationResult(
        True,
        "transfer_skin_weights",
        cluster,
        changed_vertices=tuple(range(cluster.vertex_count)),
        warnings=() if strategy == "index" else (f"Transfer strategy '{strategy}' is recorded; TC-native remap solver is planned.",),
    )


def export_skin_weights_payload(
    cluster: SkinClusterState,
    *,
    vertex_positions: Sequence[Sequence[float]] | None = None,
    faces: Sequence[Sequence[int]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema": "tech_connector.skin_weights.v1",
        "cluster": cluster.to_dict(),
        "summary": skin_cluster_summary(cluster),
    }
    if vertex_positions is not None:
        payload["topology"] = skin_topology_identity(vertex_positions, faces or ())
    flesh = dict(cluster.metadata.get("flesh") or {})
    muscles = list(cluster.metadata.get("muscles") or [])
    secondary_motion = list(cluster.metadata.get("secondary_motion") or [])
    secondary_presets = list(cluster.metadata.get("secondary_motion_presets") or [])
    if flesh or muscles or secondary_motion or secondary_presets:
        payload["extensions"] = {}
        if flesh:
            payload["extensions"]["tech_connector.flesh.v1"] = flesh
        if muscles:
            payload["extensions"]["tech_connector.muscle.v1"] = {
                "deformers": muscles, "canonical_skin_preserved": True,
            }
        if secondary_motion or secondary_presets:
            payload["extensions"]["tech_connector.secondary_motion.v1"] = {
                "deformers": secondary_motion,
                "presets": secondary_presets,
                "canonical_skin_preserved": True,
            }
        payload["interchange"] = {
            "canonical_skin_weights": "authoritative",
            "secondary_flesh": "optional_extension_or_bake" if flesh else "none",
            "muscle_tissue": "optional_extension_or_bake" if muscles else "none",
            "secondary_motion": "optional_extension_or_bake" if secondary_motion or secondary_presets else "none",
            "safe_without_extension": True,
        }
    payload["receipt"] = {
        "algorithm": "sha256",
        "cluster_sha256": _stable_sha256(payload["cluster"]),
    }
    if payload.get("extensions"):
        payload["receipt"]["extensions_sha256"] = _stable_sha256(payload["extensions"])
    return payload


def export_skin_weights_json(
    cluster: SkinClusterState,
    *,
    vertex_positions: Sequence[Sequence[float]] | None = None,
    faces: Sequence[Sequence[int]] | None = None,
    indent: int = 2,
) -> str:
    return json.dumps(
        export_skin_weights_payload(cluster, vertex_positions=vertex_positions, faces=faces),
        indent=indent,
        sort_keys=True,
    )


def import_skin_weights_payload(payload: Mapping[str, Any]) -> SkinClusterState:
    data = dict(payload or {})
    cluster_data = dict(data.get("cluster") or data)
    influences = tuple(_coerce_influence(item) for item in cluster_data.get("influences") or ())
    rows = tuple(
        SkinVertexWeights(
            int(row.get("vertex_index", index)),
            normalize_skin_weights(row.get("weights") or {}, max_influences=int(cluster_data.get("max_influences", 4) or 4)),
        )
        for index, row in enumerate(cluster_data.get("vertex_weights") or ())
        if isinstance(row, Mapping)
    )
    return SkinClusterState(
        mesh_id=str(cluster_data.get("mesh_id") or ""),
        influences=influences,
        vertex_weights=rows,
        max_influences=int(cluster_data.get("max_influences", 4) or 4),
        normalize=bool(cluster_data.get("normalize", True)),
        metadata=dict(cluster_data.get("metadata") or {}),
    )


def skin_topology_identity(
    vertex_positions: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]] = (),
) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(f"v={len(vertex_positions)};f={len(faces)};".encode("ascii"))
    for vertex in vertex_positions:
        values = _coerce_position(vertex)
        digest.update((",".join(format(value, ".9g") for value in values) + ";").encode("ascii"))
    for face in faces:
        digest.update((",".join(str(int(index)) for index in face) + ";").encode("ascii"))
    return {
        "vertex_count": len(vertex_positions),
        "face_count": len(faces),
        "fingerprint": digest.hexdigest(),
    }


def save_skin_weights_file(
    path: str | os.PathLike[str],
    cluster: SkinClusterState,
    *,
    vertex_positions: Sequence[Sequence[float]] | None = None,
    faces: Sequence[Sequence[int]] | None = None,
) -> dict[str, Any]:
    output = Path(path).expanduser().resolve()
    if output.suffix.lower() not in {".tcskin", ".json"}:
        raise ValueError("Skin weights must be saved as .tcskin or .json.")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = export_skin_weights_payload(cluster, vertex_positions=vertex_positions, faces=faces)
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=output.suffix,
            prefix=output.stem + ".",
            dir=str(output.parent),
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = temporary.name
        os.replace(temporary_path, output)
    finally:
        if temporary_path and Path(temporary_path).exists():
            Path(temporary_path).unlink()
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "summary": dict(payload["summary"]),
        "topology": dict(payload.get("topology") or {}),
        "receipt": dict(payload["receipt"]),
    }


def load_skin_weights_file(
    path: str | os.PathLike[str],
    *,
    target_mesh_id: str = "",
    expected_vertex_count: int | None = None,
    expected_topology_fingerprint: str = "",
    available_influences: Iterable[str] | None = None,
    influence_map: Mapping[str, str] | None = None,
    allow_partial: bool = False,
) -> SkinWeightImportResult:
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() not in {".tcskin", ".json"}:
        raise ValueError("Skin weights must be loaded from .tcskin or .json.")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or str(data.get("schema") or "") != "tech_connector.skin_weights.v1":
        raise ValueError("Unsupported or missing Tech Connector skin-weight schema.")
    cluster_data = dict(data.get("cluster") or {})
    expected_checksum = str((data.get("receipt") or {}).get("cluster_sha256") or "")
    if expected_checksum and _stable_sha256(cluster_data) != expected_checksum:
        raise ValueError("Skin-weight payload checksum does not match its receipt.")
    cluster = import_skin_weights_payload(data)
    if cluster.max_influences < 1 or cluster.max_influences > 32:
        raise ValueError("Skin weights must declare between 1 and 32 influences per vertex.")
    indices = [row.vertex_index for row in cluster.vertex_weights]
    if len(indices) != len(set(indices)) or any(index < 0 for index in indices):
        raise ValueError("Skin-weight payload contains duplicate or negative vertex indices.")
    if any(set(row.weights) - set(cluster.influence_names) for row in cluster.vertex_weights):
        raise ValueError("Skin-weight rows reference influences missing from the cluster declaration.")

    warnings: list[str] = []
    topology = dict(data.get("topology") or {})
    file_vertex_count = int(topology.get("vertex_count", cluster.vertex_count) or 0)
    topology_matched = True
    if expected_vertex_count is not None and file_vertex_count != int(expected_vertex_count):
        topology_matched = False
        detail = f"Skin weights contain {file_vertex_count} vertices, but the target mesh has {int(expected_vertex_count)}."
        if not allow_partial:
            raise ValueError(detail)
        warnings.append(detail)
    source_fingerprint = str(topology.get("fingerprint") or "")
    if expected_topology_fingerprint and source_fingerprint and source_fingerprint != expected_topology_fingerprint:
        topology_matched = False
        detail = "Skin-weight topology fingerprint does not match the target mesh."
        if not allow_partial:
            raise ValueError(detail)
        warnings.append(detail)

    remap = {str(key): str(value) for key, value in dict(influence_map or {}).items()}
    available = {str(value) for value in available_influences} if available_influences is not None else None
    mapped_influences: list[SkinInfluence] = []
    mapped_names: set[str] = set()
    missing: list[str] = []
    for influence in cluster.influences:
        target_name = remap.get(influence.name, influence.name)
        if available is not None and target_name not in available:
            missing.append(influence.name)
            continue
        if target_name not in mapped_names:
            mapped_influences.append(replace(influence, name=target_name))
            mapped_names.add(target_name)
    if missing and not allow_partial:
        raise ValueError("Target rig is missing skin influences: " + ", ".join(missing[:12]))
    if missing:
        warnings.append("Dropped missing influences: " + ", ".join(missing[:12]))

    mapped_rows = []
    vertex_limit = int(expected_vertex_count) if expected_vertex_count is not None else None
    for row in cluster.vertex_weights:
        if vertex_limit is not None and row.vertex_index >= vertex_limit:
            continue
        weights: dict[str, float] = {}
        for name, value in row.weights.items():
            mapped_name = remap.get(name, name)
            if mapped_name in mapped_names:
                weights[mapped_name] = weights.get(mapped_name, 0.0) + float(value)
        normalized = normalize_skin_weights(weights, max_influences=cluster.max_influences)
        if normalized:
            mapped_rows.append(SkinVertexWeights(row.vertex_index, normalized))
        elif not allow_partial:
            raise ValueError(f"Vertex {row.vertex_index} has no weights after influence remapping.")
    imported = replace(
        cluster,
        mesh_id=str(target_mesh_id or cluster.mesh_id),
        influences=tuple(mapped_influences),
        vertex_weights=tuple(mapped_rows),
        metadata={**cluster.metadata, "import_source": str(source)},
    )
    return SkinWeightImportResult(
        imported,
        warnings=tuple(warnings),
        source_summary=dict(data.get("summary") or {}),
        topology_matched=topology_matched,
    )


def skin_cluster_from_rig_graph(rig_graph: Any, skin_id: str) -> SkinClusterState:
    skin = dict((getattr(rig_graph, "skins", {}) or {}).get(str(skin_id)) or {})
    if not skin:
        raise KeyError(f"Unknown TC skin: {skin_id}")
    overrides = dict(skin.get("weight_overrides") or {})
    if not overrides and skin.get("weights_blob"):
        raise ValueError("This skin still uses an unresolved binary weight blob; materialize its weights before export.")
    vertex_count = int(skin.get("vertex_count", 0) or 0)
    if vertex_count <= 0 and overrides:
        vertex_count = max(int(index) for index in overrides) + 1
    joint_ids = [str(value) for value in skin.get("joint_ids") or []]
    influences = influences_from_rig_graph(rig_graph, joint_ids=joint_ids)
    max_influences = max(1, min(32, int(skin.get("max_influences_per_vertex", 4) or 4)))
    rows = tuple(
        SkinVertexWeights(
            index,
            normalize_skin_weights(overrides.get(str(index)) or {}, max_influences=max_influences),
        )
        for index in range(vertex_count)
    )
    return SkinClusterState(
        mesh_id=str(skin.get("mesh_id") or ""),
        influences=influences,
        vertex_weights=rows,
        max_influences=max_influences,
        normalize=True,
        metadata={
            **dict(skin.get("metadata") or {}),
            "rig_graph_skin_id": str(skin_id),
            **({"flesh": dict(skin.get("fleshy") or {})} if skin.get("fleshy") else {}),
            **({"muscles": list(skin.get("muscles") or [])} if skin.get("muscles") else {}),
            **({"secondary_motion": list(skin.get("secondary_motion") or [])} if skin.get("secondary_motion") else {}),
            **({"secondary_motion_presets": list(skin.get("secondary_motion_presets") or [])}
               if skin.get("secondary_motion_presets") else {}),
            "interchange_contract": {
                "canonical_skin_weights_preserved": True,
                "secondary_deformers_are_extensions": True,
            },
        },
    )


def _stable_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_bind_method(bind_method: str) -> str:
    key = str(bind_method or "heat").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "heat_map": "heat",
        "heatmap": "heat",
        "geo": "geodesic_voxel",
        "geodesic": "geodesic_voxel",
        "voxel": "geodesic_voxel",
        "geodesicvoxel": "geodesic_voxel",
        "closest_distance": "distance",
        "distance_bind": "distance",
        "auto_skinner": "auto",
    }
    return aliases.get(key, key) if aliases.get(key, key) in SKIN_BIND_METHODS else "heat"


def skin_cluster_summary(cluster: SkinClusterState) -> dict[str, Any]:
    weighted_vertices = sum(1 for row in cluster.vertex_weights if row.weights)
    return {
        "mesh_id": cluster.mesh_id,
        "vertex_count": cluster.vertex_count,
        "weighted_vertices": weighted_vertices,
        "influences": list(cluster.influence_names),
        "max_influences": cluster.max_influences,
        "engine_ready": all(len(row.weights) <= cluster.max_influences for row in cluster.vertex_weights),
    }


def _coerce_influence(value: SkinInfluence | Mapping[str, Any] | str) -> SkinInfluence:
    if isinstance(value, SkinInfluence):
        return value
    if isinstance(value, Mapping):
        return SkinInfluence(
            name=str(value.get("name") or value.get("id") or ""),
            position=_coerce_position(value.get("position") or (0.0, 0.0, 0.0)),
            locked=bool(value.get("locked", False)),
            metadata=dict(value.get("metadata") or {}),
        )
    return SkinInfluence(name=str(value or ""))


def _coerce_position(value: Any) -> tuple[float, float, float]:
    parts = list(value or ())
    while len(parts) < 3:
        parts.append(0.0)
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def _matrix_translation(value: Any) -> tuple[float, float, float]:
    try:
        parts = [float(item) for item in list(value or ())]
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)
    if len(parts) >= 16:
        return (parts[12], parts[13], parts[14])
    return _coerce_position(parts)
