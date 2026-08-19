"""Native editable FBX import through a production Blender conversion backend."""

from __future__ import annotations

import array
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX

try:
    import numpy as np
except Exception:  # pragma: no cover - native FBX conversion already requires the desktop runtime.
    np = None


NATIVE_FBX_SCHEMA = "tech_connector.native_fbx_asset.v1"
NATIVE_SCENE_SCHEMA = "tech_connector.native_scene_asset.v1"
NATIVE_SCENE_EXTENSIONS = frozenset({
    ".abc", ".fbx", ".glb", ".gltf", ".obj", ".stl",
    ".usd", ".usda", ".usdc", ".usdz",
})


@dataclass
class NativeFbxAsset:
    source_path: str
    manifest: dict[str, Any]
    floats: array.array
    integers: array.array

    @property
    def source_format(self) -> str:
        return str(
            self.manifest.get("source_format")
            or Path(self.source_path).suffix.lower().lstrip(".")
        )

    def to_editable_rig_graph(self) -> tuple[EditableRigGraph, dict[str, bytes]]:
        graph = EditableRigGraph()
        blobs = {
            "native_fbx/buffers.f32": self.floats.tobytes(),
            "native_fbx/buffers.u32": self.integers.tobytes(),
        }
        centimeters_per_unit = max(
            1.0e-12,
            float(self.manifest.get("unit_scale", 1.0) or 1.0) * 100.0,
        )
        for armature in self.manifest.get("armatures") or []:
            armature_id = str(armature.get("native_id") or "Armature")
            bones = list(armature.get("bones") or [])
            ids = {str(bone.get("name") or ""): f"native_fbx::{armature_id}::{bone.get('name') or ''}" for bone in bones}
            bind_world = _armature_bind_world_matrices(
                armature,
                centimeters_per_unit=centimeters_per_unit,
            )
            for bone in bones:
                name = str(bone.get("name") or "Joint")
                joint_id = ids[name]
                parent_id = ids.get(str(bone.get("parent") or ""), "")
                world_matrix = bind_world.get(name, IDENTITY_MATRIX)
                parent_world = bind_world.get(str(bone.get("parent") or ""))
                matrix = _relative_row_matrix(world_matrix, parent_world)
                graph.add_joint(
                    name,
                    parent_id=parent_id if parent_id in graph.joints else "",
                    local_matrix=matrix,
                    joint_id=joint_id,
                    source_ref={"provider_id": "native_fbx", "native_id": f"{armature_id}:{name}"},
                )
                graph.joints[joint_id]["bind_world_matrix"] = list(world_matrix)
            for bone in bones:
                joint_id = ids.get(str(bone.get("name") or ""), "")
                parent_id = ids.get(str(bone.get("parent") or ""), "")
                if joint_id in graph.joints:
                    graph.joints[joint_id]["parent_id"] = parent_id
            for constraint in armature.get("constraints") or []:
                kind = _constraint_kind(str(constraint.get("type") or ""))
                if not kind:
                    continue
                target_id = ids.get(str(constraint.get("bone") or ""), "")
                if target_id:
                    source_id = ids.get(str(constraint.get("subtarget") or ""), "")
                    constraint_id = graph.add_constraint(
                        kind,
                        [source_id] if source_id else [],
                        target_id,
                        settings=dict(constraint),
                    )
                    if not source_id or kind in {"ik", "aim"}:
                        graph.constraints[constraint_id].update({
                            "ownership": "baked",
                            "edit_policy": "baked_only",
                            "evaluation_note": (
                                "The FBX contains a constraint whose complete solver state is not portable; "
                                "its imported bind/animation result remains authoritative."
                            ),
                        })
        for mesh in self.manifest.get("meshes") or []:
            armature_id = str(mesh.get("armature_id") or "")
            armature = next(
                (item for item in self.manifest.get("armatures") or [] if str(item.get("native_id") or "") == armature_id),
                None,
            )
            if armature is None or int(mesh.get("influence_count", 0) or 0) <= 0:
                continue
            joint_ids = [f"native_fbx::{armature_id}::{bone.get('name') or ''}" for bone in armature.get("bones") or []]
            skin_id = f"native_fbx::{mesh.get('native_id') or mesh.get('name') or 'mesh'}::skin"
            graph.add_skin(
                f"native_fbx::{mesh.get('native_id') or mesh.get('name') or 'mesh'}",
                joint_ids,
                skin_id=skin_id,
                weights_blob="native_fbx/buffers.f32",
                source_ref={"provider_id": "native_fbx", "native_id": str(mesh.get("native_id") or "")},
            )
            graph.skins[skin_id].update({
                "vertex_count": int(mesh.get("vertex_count", 0) or 0),
                "influence_count": int(mesh.get("influence_count", 0) or 0),
                "influence_offset_offset": int(mesh.get("influence_offset_offset", 0) or 0),
                "joint_index_offset": int(mesh.get("joint_index_offset", 0) or 0),
                "weight_float_offset": int(mesh.get("weight_float_offset", 0) or 0),
                "max_influences_per_vertex": int(mesh.get("max_influences_per_vertex", 0) or 0),
                "buffer_encoding": "shared_f32_u32",
            })
        graph.animation = {}
        for index, action in enumerate(self.manifest.get("actions") or []):
            action_id = f"native_fbx::action::{index}"
            graph.animation[action_id] = {"id": action_id, **dict(action)}
        return graph, blobs

    def build_deformation_binding(
        self,
        graph: EditableRigGraph | None = None,
    ) -> dict[str, Any]:
        """Compile immutable FBX skin data into the viewport's exact sparse GPU contract."""
        if np is None:
            raise RuntimeError("NumPy is required for native FBX skinning.")
        editable_graph = graph or self.to_editable_rig_graph()[0]
        centimeters_per_unit = max(
            1.0e-12,
            float(self.manifest.get("unit_scale", 1.0) or 1.0) * 100.0,
        )
        skeletons: list[dict[str, Any]] = []
        meshes: list[dict[str, Any]] = []
        armature_joint_ids: dict[str, list[str]] = {}
        for armature in self.manifest.get("armatures") or []:
            armature_id = str(armature.get("native_id") or "Armature")
            bones = list(armature.get("bones") or [])
            joint_ids = [
                f"native_fbx::{armature_id}::{str(bone.get('name') or '')}"
                for bone in bones
            ]
            armature_joint_ids[armature_id] = joint_ids
            bind_world = _armature_bind_world_matrices(
                armature,
                centimeters_per_unit=centimeters_per_unit,
            )
            matrices = np.asarray(
                [bind_world.get(str(bone.get("name") or ""), IDENTITY_MATRIX) for bone in bones],
                dtype=np.float32,
            ).reshape((-1, 4, 4))
            inverse_bind = np.linalg.inv(matrices).astype(np.float32, copy=False)
            skeletons.append({
                "native_id": armature_id,
                "joints": [
                    {
                        "native_id": joint_id,
                        "name": str(bone.get("name") or "Joint"),
                        "parent_native_id": (
                            f"native_fbx::{armature_id}::{str(bone.get('parent') or '')}"
                            if bone.get("parent")
                            else ""
                        ),
                    }
                    for joint_id, bone in zip(joint_ids, bones)
                ],
                "inverse_bind_matrices_f32": inverse_bind.tobytes(order="C"),
                "inverse_bind_float_offset": 0,
            })

        float_values = np.frombuffer(self.floats, dtype=np.float32)
        integer_values = np.frombuffer(self.integers, dtype=np.uint32)
        for mesh in self.manifest.get("meshes") or []:
            armature_id = str(mesh.get("armature_id") or "")
            joint_ids = armature_joint_ids.get(armature_id, [])
            vertex_count = int(mesh.get("vertex_count", 0) or 0)
            influence_count = int(mesh.get("influence_count", 0) or 0)
            if not joint_ids or vertex_count <= 0 or influence_count <= 0:
                continue
            position_start = int(mesh.get("position_float_offset", 0) or 0)
            offset_start = int(mesh.get("influence_offset_offset", 0) or 0)
            index_start = int(mesh.get("joint_index_offset", 0) or 0)
            weight_start = int(mesh.get("weight_float_offset", 0) or 0)
            positions = (
                float_values[position_start : position_start + vertex_count * 3]
                .reshape((-1, 3))
                .astype(np.float32, copy=True)
            )
            positions *= float(centimeters_per_unit)
            offsets = integer_values[offset_start : offset_start + vertex_count + 1].astype(np.uint32, copy=True)
            indices = integer_values[index_start : index_start + influence_count].astype(np.uint32, copy=True)
            weights = float_values[weight_start : weight_start + influence_count].astype(np.float32, copy=True)
            valid_offsets = (
                len(offsets) == vertex_count + 1
                and int(offsets[0]) == 0
                and int(offsets[-1]) == influence_count
                and bool(np.all(offsets[1:] >= offsets[:-1]))
            )
            all_vertices_weighted = bool(valid_offsets and np.all(np.diff(offsets.astype(np.int64)) > 0))
            indices_valid = bool(len(indices) == influence_count and int(indices.max(initial=0)) < len(joint_ids))
            weights_valid = bool(
                len(weights) == influence_count
                and np.all(np.isfinite(weights))
                and np.all(weights >= 0.0)
            )
            maximum = int(mesh.get("max_influences_per_vertex", 0) or 0)
            gpu_exact = bool(
                all_vertices_weighted
                and indices_valid
                and weights_valid
                and 0 < maximum <= 32
            )
            mesh_world = _scaled_row_matrix(
                mesh.get("world_matrix") or IDENTITY_MATRIX,
                centimeters_per_unit,
            )
            authored = dict(mesh.get("tech_connector_transform") or {})
            points_h = np.ones((vertex_count, 4), dtype=np.float64)
            points_h[:, :3] = positions
            base_world_points = points_h @ np.asarray(mesh_world, dtype=np.float64).reshape((4, 4))
            pivot = (base_world_points[:, :3].min(axis=0) + base_world_points[:, :3].max(axis=0)) * 0.5
            mesh_world = _apply_authored_mesh_transform(mesh_world, authored, pivot=pivot)
            meshes.append({
                "native_id": str(mesh.get("native_id") or mesh.get("name") or "Mesh"),
                "skeleton_id": armature_id,
                "vertex_count": vertex_count,
                "bind_vertices_f32": positions.tobytes(order="C"),
                "bind_vertex_float_offset": 0,
                "influence_offsets_u32": offsets,
                "influence_offset_offset": 0,
                "joint_indices_u32": indices,
                "joint_index_offset": 0,
                "weights_f32": weights.tobytes(order="C"),
                "weight_float_offset": 0,
                "sparse_influence_count": influence_count,
                "max_influences_per_vertex": maximum,
                "bind_geometry_matrix": mesh_world,
                "deformation_mode": "linear_blend_skinning",
                "runtime_mode": "skeletal" if gpu_exact else "point_cache",
                "gpu_runtime_mode": "skeletal" if gpu_exact else "point_cache",
                "gpu_influence_mode": "sparse" if gpu_exact else "point_cache",
                "gpu_influence_width": 0,
                "exact_parity_accepted": gpu_exact,
                "contract_errors": [] if gpu_exact else [
                    "Native FBX skin requires valid nonzero weights and at most 32 influences per vertex for exact GPU playback."
                ],
            })
        binding = {
            "provider_id": "native_fbx",
            "unit_linear": "centimeters",
            "up_axis": "y",
            "skeletons": skeletons,
            "meshes": meshes,
            "contract_errors": [],
        }
        binding["initial_pose"] = self.deformation_pose_at_frame(
            binding,
            int(self.manifest.get("frame_start", 1) or 1),
            graph=editable_graph,
        )
        return binding

    def deformation_pose_at_frame(
        self,
        binding: dict[str, Any],
        frame: int,
        *,
        graph: EditableRigGraph | None = None,
    ) -> dict[str, Any]:
        """Read a baked exact FBX pose, falling back to the editable local graph for static rigs."""
        if np is None:
            raise RuntimeError("NumPy is required for native FBX animation playback.")
        armatures = {
            str(item.get("native_id") or ""): item
            for item in self.manifest.get("armatures") or []
        }
        float_values = np.frombuffer(self.floats, dtype=np.float32)
        centimeters_per_unit = max(
            1.0e-12,
            float(self.manifest.get("unit_scale", 1.0) or 1.0) * 100.0,
        )
        evaluated_pose: dict[str, Any] | None = None
        evaluated_by_skeleton: dict[str, dict[str, Any]] = {}
        skeleton_poses = []
        sampled_frame = int(frame)
        used_baked_cache = False
        for skeleton in binding.get("skeletons") or []:
            skeleton_id = str(skeleton.get("native_id") or "")
            armature = armatures.get(skeleton_id, {})
            cache = dict(armature.get("pose_cache") or {})
            joint_count = len(skeleton.get("joints") or [])
            if bool(cache.get("available")) and int(cache.get("joint_count", 0) or 0) == joint_count:
                frame_start = int(cache.get("frame_start", 1) or 1)
                frame_end = int(cache.get("frame_end", frame_start) or frame_start)
                cache_frame = max(frame_start, min(frame_end, sampled_frame))
                frame_offset = cache_frame - frame_start
                matrix_start = int(cache.get("matrix_float_offset", 0) or 0) + frame_offset * joint_count * 16
                matrix_end = matrix_start + joint_count * 16
                if matrix_start < 0 or matrix_end > len(float_values):
                    raise ValueError(f"Native FBX pose cache is truncated for armature {skeleton_id}.")
                column_matrices = float_values[matrix_start:matrix_end].reshape((joint_count, 4, 4))
                row_matrices = column_matrices.transpose((0, 2, 1)).astype(np.float32, copy=True)
                row_matrices[:, 3, :3] *= float(centimeters_per_unit)
                used_baked_cache = True
            else:
                if evaluated_pose is None:
                    if graph is None:
                        graph = self.to_editable_rig_graph()[0]
                    evaluated_pose = build_native_fbx_deformation_pose(graph, binding)
                    evaluated_by_skeleton = {
                        str(item.get("native_id") or ""): item
                        for item in evaluated_pose.get("skeletons") or []
                    }
                source = evaluated_by_skeleton.get(skeleton_id)
                if source is None:
                    raise KeyError(f"No editable pose exists for armature {skeleton_id}.")
                packed = source.get("joint_matrices_f32")
                row_matrices = np.frombuffer(packed, dtype=np.float32).reshape((joint_count, 4, 4)).copy()
            skeleton_poses.append({
                "native_id": skeleton_id,
                "joint_matrices_f32": row_matrices.tobytes(order="C"),
                "joint_matrix_float_offset": 0,
            })
        return {
            "provider_id": "native_fbx",
            "frame": sampled_frame,
            "pose_source": "baked_exact" if used_baked_cache else "local_graph",
            "skeletons": skeleton_poses,
            "objects": [],
        }


def build_native_fbx_deformation_pose(
    graph: EditableRigGraph,
    binding: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate a native rig graph and return only the joint matrices needed by the GPU."""
    if np is None:
        raise RuntimeError("NumPy is required for native FBX skinning.")
    evaluated = graph.evaluate_local()
    if not evaluated.ok:
        detail = "; ".join(evaluated.errors[:4]) or ", ".join(evaluated.unsupported_local_node_ids[:4])
        raise ValueError("Native rig evaluation failed: " + detail)
    skeletons = []
    for skeleton in binding.get("skeletons") or []:
        joint_ids = [str(item.get("native_id") or "") for item in skeleton.get("joints") or []]
        matrices = np.asarray(
            [evaluated.world_matrices[joint_id] for joint_id in joint_ids],
            dtype=np.float32,
        ).reshape((-1, 4, 4))
        skeletons.append({
            "native_id": str(skeleton.get("native_id") or ""),
            "joint_matrices_f32": matrices.tobytes(order="C"),
            "joint_matrix_float_offset": 0,
        })
    return {
        "provider_id": "native_fbx",
        "skeletons": skeletons,
        "objects": [],
    }


def apply_native_joint_matrix_override(
    graph: EditableRigGraph,
    joint_id: str,
    *,
    translation_delta: tuple[float, float, float] | None = None,
    rotation_degrees: tuple[float, float, float] | None = None,
    scale: tuple[float, float, float] | None = None,
) -> list[float]:
    """Apply a viewer-authored local joint delta while preserving imported joint orientation."""
    if np is None:
        raise RuntimeError("NumPy is required for native rig editing.")
    joint = graph.joints.get(str(joint_id))
    node = graph.nodes.get(str(joint_id))
    if joint is None or node is None:
        raise KeyError(f"Unknown native joint: {joint_id}")
    if graph.joint_edit_policy(joint_id) != "full":
        raise PermissionError("Linked DCC joints must be edited in their source session.")
    matrix = np.asarray(joint.get("local_matrix") or IDENTITY_MATRIX, dtype=np.float64).reshape((4, 4)).copy()
    if translation_delta is not None:
        matrix[3, :3] += np.asarray(translation_delta[:3], dtype=np.float64)
    if rotation_degrees is not None:
        rotation = _row_euler_matrix(rotation_degrees)
        matrix[:3, :3] = matrix[:3, :3] @ rotation
    if scale is not None:
        factors = np.asarray(scale[:3], dtype=np.float64)
        if np.any(factors <= 0.0):
            raise ValueError("Joint scale values must be greater than zero.")
        matrix[:3, :3] = factors[:, None] * matrix[:3, :3]
    values = matrix.reshape(-1).tolist()
    joint["local_matrix"] = values
    node.setdefault("attributes", {})["matrix"] = values
    return values


def _armature_bind_world_matrices(
    armature: dict[str, Any],
    *,
    centimeters_per_unit: float,
) -> dict[str, list[float]]:
    if np is None:
        raise RuntimeError("NumPy is required for native FBX rig conversion.")
    armature_world = np.asarray(
        armature.get("world_matrix") or IDENTITY_MATRIX,
        dtype=np.float64,
    ).reshape((4, 4))
    result = {}
    for bone in armature.get("bones") or []:
        bone_armature = np.asarray(
            bone.get("matrix_local") or IDENTITY_MATRIX,
            dtype=np.float64,
        ).reshape((4, 4))
        column_world = armature_world @ bone_armature
        row_world = column_world.T
        row_world[3, :3] *= float(centimeters_per_unit)
        result[str(bone.get("name") or "")] = row_world.reshape(-1).tolist()
    return result


def _relative_row_matrix(world_matrix: Any, parent_world_matrix: Any | None) -> list[float]:
    if np is None:
        raise RuntimeError("NumPy is required for native FBX rig conversion.")
    world = np.asarray(world_matrix, dtype=np.float64).reshape((4, 4))
    if parent_world_matrix is None:
        return world.reshape(-1).tolist()
    parent = np.asarray(parent_world_matrix, dtype=np.float64).reshape((4, 4))
    return (world @ np.linalg.inv(parent)).reshape(-1).tolist()


def _scaled_row_matrix(matrix: Any, centimeters_per_unit: float) -> list[float]:
    if np is None:
        raise RuntimeError("NumPy is required for native FBX rig conversion.")
    row = np.asarray(matrix, dtype=np.float64).reshape((4, 4)).T.copy()
    row[3, :3] *= float(centimeters_per_unit)
    return row.reshape(-1).tolist()


def _apply_authored_mesh_transform(
    matrix: Any,
    authored: dict[str, Any],
    *,
    pivot: Any = (0.0, 0.0, 0.0),
) -> list[float]:
    if np is None:
        raise RuntimeError("NumPy is required for native FBX rig conversion.")
    result = np.asarray(matrix, dtype=np.float64).reshape((4, 4)).copy()
    translation = np.asarray(list(authored.get("translation_shared_cm") or (0.0, 0.0, 0.0))[:3], dtype=np.float64)
    rotation = _row_euler_matrix(list(authored.get("rotation_degrees") or (0.0, 0.0, 0.0))[:3])
    scale = np.asarray(list(authored.get("scale") or (1.0, 1.0, 1.0))[:3], dtype=np.float64)
    pivot = np.asarray(pivot, dtype=np.float64).reshape(3)
    authored_matrix = np.eye(4, dtype=np.float64)
    authored_matrix[:3, :3] = scale[:, None] * rotation
    authored_matrix[3, :3] = (
        -pivot @ authored_matrix[:3, :3]
        + pivot
        + translation
    )
    return (result @ authored_matrix).reshape(-1).tolist()


def _row_euler_matrix(rotation_degrees: Any):
    if np is None:
        raise RuntimeError("NumPy is required for native FBX rig conversion.")
    values = list(rotation_degrees or (0.0, 0.0, 0.0))
    values = (values + [0.0, 0.0, 0.0])[:3]
    rx, ry, rz = [float(value) * np.pi / 180.0 for value in values]
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    column = np.asarray(
        [
            [cy * cz, cz * sx * sy - cx * sz, sx * sz + cx * cz * sy],
            [cy * sz, cx * cz + sx * sy * sz, cx * sy * sz - cz * sx],
            [-sy, cy * sx, cx * cy],
        ],
        dtype=np.float64,
    )
    return column.T


def find_blender_executable() -> Path | None:
    configured = os.environ.get("TECH_CONNECTOR_BLENDER") or os.environ.get("BLENDER_EXECUTABLE")
    candidates = [configured, shutil.which("blender")]
    program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation"
    if program_files.is_dir():
        candidates.extend(str(path) for path in sorted(program_files.glob("Blender */blender.exe"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def find_blender_fbx_extractor() -> Path | None:
    """Resolve the converter worker in both canonical and compatibility package layouts."""
    configured = os.environ.get("TECH_CONNECTOR_BLENDER_FBX_EXTRACTOR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(__file__).with_name("blender_fbx_extract.py"),
        Path(__file__).resolve().parents[1] / "integration" / "blender_fbx_extract.py",
        Path(__file__).resolve().parents[2] / "services" / "dcc" / "blender_fbx_extract.py",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    return None


def native_scene_import_capabilities() -> dict[str, Any]:
    """Report import support without launching a DCC or mutating scene state."""
    blender = find_blender_executable()
    worker = find_blender_fbx_extractor()
    backend_ready = bool(blender and worker)
    formats: dict[str, dict[str, Any]] = {}
    for extension in sorted(NATIVE_SCENE_EXTENSIONS):
        formats[extension] = {
            "available": backend_ready,
            "backend": "blender_background",
            "implementation": "external_converter",
            "in_process": False,
            "requires": ["Blender", "Tech Connector Blender extraction worker"],
            "geometry": True,
            "uvs": True,
            "materials": True,
            "hierarchy": True,
            "skinning": extension in {".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz"},
            "animation": extension in {".abc", ".fbx", ".glb", ".gltf", ".usd", ".usda", ".usdc", ".usdz"},
        }
    return {
        "schema": "tech_connector.scene_import_capabilities.v1",
        "available": backend_ready,
        "backend": "blender_background",
        "implementation": "external_converter",
        "in_process": False,
        "dependency": {
            "name": "Blender",
            "required": True,
            "found": bool(blender),
            "executable": str(blender or ""),
        },
        "backend_executable": str(blender or ""),
        "worker": str(worker or ""),
        "formats": formats,
        "limitations": [
            "Import runs out-of-process through Blender; it is not an in-process native parser.",
            *([] if backend_ready else ["A Blender installation and the packaged extraction worker are required."]),
        ],
    }


def import_native_scene(
    source_path: str | os.PathLike[str],
    *,
    blender_executable: str | os.PathLike[str] | None = None,
    timeout: float = 180.0,
    cancel_event: threading.Event | None = None,
) -> NativeFbxAsset:
    """Import a supported scene file through an isolated Blender process."""
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Native scene import canceled.")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in NATIVE_SCENE_EXTENSIONS:
        supported = ", ".join(sorted(NATIVE_SCENE_EXTENSIONS))
        raise ValueError(f"A readable supported scene file is required ({supported}): {source}")
    blender = Path(blender_executable).resolve() if blender_executable else find_blender_executable()
    if blender is None or not blender.is_file():
        raise RuntimeError("No Blender scene conversion backend was found.")
    worker = find_blender_fbx_extractor()
    if worker is None:
        raise RuntimeError(
            "The Blender scene extraction worker is missing from the Tech Connector installation."
        )
    prefix = source.suffix.lower().lstrip(".") or "scene"
    with tempfile.TemporaryDirectory(prefix=f"tech_connector_{prefix}_") as directory:
        output = Path(directory)
        manifest_path = output / "manifest.json"
        float_path = output / "buffers.f32"
        uint_path = output / "buffers.u32"
        startup = getattr(subprocess, "STARTUPINFO", None)
        startup_info = startup() if startup is not None else None
        if startup_info is not None:
            startup_info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        command = [
            str(blender),
            "--background",
            "--factory-startup",
            "--python",
            str(worker),
            "--",
            "--input",
            str(source),
            "--manifest",
            str(manifest_path),
            "--floats",
            str(float_path),
            "--uints",
            str(uint_path),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startup_info,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + max(0.1, float(timeout))
        stdout = ""
        stderr = ""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _stop_subprocess(process)
                raise RuntimeError("Native scene import canceled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _stop_subprocess(process)
                raise TimeoutError(f"Native scene import exceeded {float(timeout):g} seconds.")
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or not manifest_path.is_file():
            detail = (stderr or stdout or "Blender returned no diagnostic output.")[-4000:]
            raise RuntimeError(f"Blender could not import {source.suffix.lower()} scene:\n" + detail)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("schema") or "") not in {NATIVE_FBX_SCHEMA, NATIVE_SCENE_SCHEMA}:
            raise ValueError("The scene converter returned an unsupported asset schema.")
        manifest.setdefault("source_format", source.suffix.lower().lstrip("."))
        _attach_portable_materials(manifest, source)
        floats = array.array("f")
        with float_path.open("rb") as stream:
            floats.fromfile(stream, float_path.stat().st_size // floats.itemsize)
        integers = array.array("I")
        with uint_path.open("rb") as stream:
            integers.fromfile(stream, uint_path.stat().st_size // integers.itemsize)
    return NativeFbxAsset(str(source), manifest, floats, integers)


def import_native_fbx(
    source_path: str | os.PathLike[str],
    *,
    blender_executable: str | os.PathLike[str] | None = None,
    timeout: float = 180.0,
    cancel_event: threading.Event | None = None,
) -> NativeFbxAsset:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Native FBX import canceled.")
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".fbx":
        raise ValueError(f"A readable FBX file is required: {source}")
    return import_native_scene(
        source,
        blender_executable=blender_executable,
        timeout=timeout,
        cancel_event=cancel_event,
    )


NativeSceneAsset = NativeFbxAsset


def _attach_portable_materials(manifest: dict[str, Any], source: Path) -> None:
    """Persist normalized lookdev while retaining the complete source payload."""
    from tech_connector.game_engine.rendering.material_contract import normalize_portable_material

    provider = f"native_{str(manifest.get('source_format') or source.suffix.lstrip('.')).lower()}"
    for mesh in manifest.get("meshes") or []:
        if not isinstance(mesh, dict):
            continue
        for material in mesh.get("materials") or []:
            if not isinstance(material, dict):
                continue
            material["portable_material"] = normalize_portable_material(
                material,
                source_provider=provider,
                source_path=str(source),
            ).to_dict()


def _stop_subprocess(process: subprocess.Popen[Any]) -> None:
    """Bounded child cleanup used by cancellation and timeout paths."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2.0)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=2.0)
        except Exception:
            pass


def _constraint_kind(blender_type: str) -> str:
    return {
        "COPY_TRANSFORMS": "parent",
        "COPY_LOCATION": "point",
        "COPY_ROTATION": "orient",
        "COPY_SCALE": "scale",
        "TRACK_TO": "aim",
        "DAMPED_TRACK": "aim",
        "IK": "ik",
    }.get(str(blender_type or "").upper(), "")

