"""Generate an original TC starter mannequin with production-style character assets."""

from __future__ import annotations

import array
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
from typing import Any

from tech_connector.game_engine.authoring.tc_animation_take_service import create_take, set_keyframe
from tech_connector.game_engine.authoring.tc_rig_template_service import expanded_tc_rig_template_joints
from tech_connector.game_engine.deformation.blend_shape import (
    attach_blend_shape_deformer,
    blend_shape_target_from_dict,
)
from tech_connector.game_engine.scene.federated_scene_service import FederatedSceneDocument

from .asset_database_service import AssetDatabase
from .asset_operations_service import AssetOperationsService
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry
from .character_asset_service import generate_bone_lods, recommended_mesh_lods
from .physics_asset_service import automatic_physics_asset


STARTER_CHARACTER_SCHEMA = "tech_connector.starter_character.v3"
STARTER_PROVIDER_ID = "tc_starter"
STARTER_SKELETON_NATIVE_ID = "tc_starter_biped"
STARTER_MESH_NATIVE_ID = "tc_starter_mannequin"
STARTER_SKIN_RUNTIME_ID = f"{STARTER_PROVIDER_ID}::{STARTER_SKELETON_NATIVE_ID}::{STARTER_MESH_NATIVE_ID}"
STARTER_ALBEDO_SOURCE = Path(__file__).with_name("builtin") / "starter_character" / "tc_starter_mannequin_albedo_v1.png"


@dataclass(frozen=True)
class StarterCharacterReceipt:
    skeleton_asset_id: str
    skeletal_mesh_asset_id: str
    skin_binding_asset_id: str
    material_asset_id: str
    texture_asset_id: str
    ik_rig_asset_id: str
    control_rig_asset_id: str
    physics_asset_id: str
    mesh_source_path: str
    texture_source_path: str
    vertex_count: int
    triangle_count: int
    bone_count: int
    presentation_variant: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema": STARTER_CHARACTER_SCHEMA, **asdict(self)}


@dataclass(frozen=True)
class StarterCharacterGeometry:
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    normals: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    influences: tuple[tuple[tuple[int, float], ...], ...]
    joint_ids: tuple[str, ...]


class StarterCharacterService:
    def __init__(
        self,
        project_root: str | Path,
        database: AssetDatabase,
        registry: AssetTypeRegistry | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self.operations = AssetOperationsService(self.project_root, database, self.registry)

    def create(
        self,
        name: str = "TC_Starter_Mannequin",
        *,
        visual_style: str = "stylized_pbr",
        dimensionality: str = "3d",
        folder: str | Path = "Assets/Characters/Starter",
    ) -> StarterCharacterReceipt:
        safe_name = _safe_name(name)
        rows = expanded_tc_rig_template_joints()
        bones = _skeleton_bones(rows)
        geometry = generate_starter_mannequin_geometry()
        variant = _presentation_variant(visual_style, dimensionality)
        mesh_source = self.project_root / Path(folder) / "Source" / f"{safe_name}_{variant}.obj"
        if mesh_source.exists():
            raise FileExistsError(mesh_source)
        mesh_source.parent.mkdir(parents=True, exist_ok=True)
        _write_obj(mesh_source, geometry, variant)
        created: list[str] = []
        try:
            skeleton = self.operations.create_asset(
                "tc.skeleton", f"SK_{safe_name}", folder=Path(folder) / "Rig", properties={
                    "bones": bones,
                    "sockets": [
                        {"name": "weapon_r", "bone": "tc_r_hand", "transform": {"position": [0.08, 0.0, 0.0]}},
                        {"name": "weapon_l", "bone": "tc_l_hand", "transform": {"position": [-0.08, 0.0, 0.0]}},
                        {"name": "camera_head", "bone": "tc_head", "transform": {"position": [0.0, 0.08, 0.04]}},
                    ],
                    "retarget_pose": {"name": "TC_A_Pose", "forward_axis": "+Z", "up_axis": "+Y"},
                    "preserve_bones": [
                        "tc_root", "tc_hips", "tc_head", "tc_l_hand", "tc_r_hand", "tc_l_ankle", "tc_r_ankle",
                    ],
                    "template_id": "tc_biped_v1",
                },
            )
            created.append(skeleton.asset_id)
            texture = self.operations.import_asset(
                STARTER_ALBEDO_SOURCE, folder=Path(folder) / "Textures", type_id="tc.texture",
                importer_settings={
                    "color_space": "srgb", "generate_mips": True,
                    "compression": "color", "max_size": 2048,
                },
            )
            created.append(texture.asset_id)
            material = self.operations.create_asset(
                "tc.material", f"M_{safe_name}", folder=Path(folder) / "Materials", properties={
                    "shading_model": "toon" if variant == "pixel_8bit" else "pbr",
                    "base_color": "#287fc2", "roughness": 0.48, "metalness": 0.02,
                    "palette": ["#10283d", "#287fc2", "#7dc8f5", "#f0f5f7"] if variant == "pixel_8bit" else [],
                    "pixel_snap": variant == "pixel_8bit", "two_sided": False,
                    "base_color_texture": texture.asset_id,
                    "texture_mapping": {"mode": "triplanar", "scale": 2.6, "blend_sharpness": 5.0},
                },
            )
            created.append(material.asset_id)
            self.database.set_dependencies(material.asset_id, [(texture.asset_id, "base_color")])
            ik_chains = _starter_ik_chains()
            ik_rig = self.operations.create_asset(
                "tc.ik_rig", f"IK_{safe_name}", folder=Path(folder) / "Rig", properties={
                    "skeleton_id": skeleton.asset_id, "retarget_root": "tc_hips", "chains": ik_chains,
                    "skeleton_bones": bones,
                    "goals": [
                        {"name": str(chain["goal"]), "chain": str(chain["name"]), "space": "world"}
                        for chain in ik_chains
                    ],
                },
            )
            created.append(ik_rig.asset_id)
            self.database.set_dependencies(ik_rig.asset_id, [(skeleton.asset_id, "skeleton")])
            control_rig = self.operations.create_asset(
                "tc.control_rig", f"CR_{safe_name}", folder=Path(folder) / "Rig", properties={
                    "skeleton_id": skeleton.asset_id,
                    "controls": _starter_controls(),
                    "variables": {
                        "foot_ik_weight": {"type": "float", "default": 1.0},
                        "look_at_weight": {"type": "float", "default": 0.0},
                        "face_weight": {"type": "float", "default": 1.0},
                    },
                    "graph": {
                        "nodes": [
                            {"id": "BodyControls", "title": "Body and IK Controls", "opcode": "control"},
                            {"id": "FaceControls", "title": "Face Controls", "opcode": "control"},
                            {"id": "OutputPose", "title": "Output Pose", "opcode": "output_pose"},
                        ],
                        "connections": [
                            {"source": "BodyControls", "target": "OutputPose"},
                            {"source": "FaceControls", "target": "OutputPose"},
                        ],
                    },
                    "lod_policy": {
                        "minimum_lod": 0,
                        "disabled_nodes": {"2": ["FaceControls"], "3": ["FaceControls", "BodyControls"]},
                    },
                },
            )
            created.append(control_rig.asset_id)
            self.database.set_dependencies(control_rig.asset_id, [(skeleton.asset_id, "skeleton")])
            mesh = self.operations.create_asset(
                "tc.skeletal_mesh", f"SKM_{safe_name}", folder=Path(folder) / "Mesh", properties={
                    "skeleton_id": skeleton.asset_id, "skin_binding_id": "",
                    "source_geometry": str(mesh_source),
                    "sections": [{
                        "id": "body", "material_slot": "StarterBody", "material_id": material.asset_id,
                        "visible": True,
                    }],
                    "lods": recommended_mesh_lods(4 if variant == "standard" else 3),
                    "bone_lods": generate_bone_lods(
                        bones, count=4 if variant == "standard" else 3,
                        preserve_bones=["tc_root", "tc_hips", "tc_head", "tc_l_hand", "tc_r_hand"],
                    ),
                    "performance_profile": "mobile" if variant == "pixel_8bit" else "balanced",
                    "bounds": {"minimum": [-1.12, -0.02, -0.34], "maximum": [1.12, 1.94, 0.40]},
                    "presentation_variants": {
                        "standard": {"mesh": str(mesh_source), "material": "builtin:starter_mannequin"},
                        "pixel_8bit": {"mesh": str(mesh_source), "material": "builtin:starter_mannequin_pixel", "vertex_snap": 0.015625},
                        "side_2_5d": {"mesh": str(mesh_source), "material": "builtin:starter_mannequin", "plane_axis": "z"},
                    },
                    "active_presentation_variant": variant,
                    "geometry_channels": {"positions": True, "normals": True, "uv0": True, "tangents": "cook"},
                    "deformation_quality": "smooth_four_influence",
                    "morph_targets": _starter_face_morph_targets(geometry),
                },
            )
            created.append(mesh.asset_id)
            binding = self.operations.create_asset(
                "tc.skin_binding", f"SKIN_{safe_name}", folder=Path(folder) / "Mesh", properties={
                    "mesh_id": mesh.asset_id, "skeleton_id": skeleton.asset_id,
                    "influences": [
                        {"id": bone["id"], "name": bone["id"], "parent": bone["parent"]}
                        for bone in bones
                    ],
                    "vertex_weights": [
                        {
                            "vertex_index": index,
                            "weights": {geometry.joint_ids[joint_index]: weight for joint_index, weight in influences},
                        }
                        for index, influences in enumerate(geometry.influences)
                    ],
                    "max_influences": 4, "normalize": True,
                    "topology": {"vertex_count": len(geometry.vertices), "triangle_count": len(geometry.triangles), "source": str(mesh_source)},
                    "performance_profile": "mobile" if variant == "pixel_8bit" else "balanced",
                    "weight_profiles": {
                        "smooth_default": {"maximum_influences": 4, "source": "generated_v3"},
                        "mobile": {"maximum_influences": 2, "source": "derived_at_cook"},
                    },
                },
            )
            created.append(binding.asset_id)
            self.database.set_dependencies(binding.asset_id, [(skeleton.asset_id, "skeleton")])
            _update_properties(self.database, mesh.asset_id, {"skin_binding_id": binding.asset_id})
            self.database.set_dependencies(mesh.asset_id, [
                (skeleton.asset_id, "skeleton"), (binding.asset_id, "skin_binding"),
                (material.asset_id, "material"),
            ])
            physics_setup = automatic_physics_asset(
                _physics_joint_graph(rows), root_joint="tc_hips", preset="balanced", include_leaf_joints=False,
            )
            physics = self.operations.create_asset(
                "tc.physics_asset", f"PHYS_{safe_name}", folder=Path(folder) / "Physics", properties={
                    "skeleton_id": skeleton.asset_id, "skeletal_mesh_id": mesh.asset_id,
                    "preset": "balanced", "bodies": physics_setup.bodies,
                    "constraints": physics_setup.constraints,
                    "animation_binding": physics_setup.animation_binding,
                    "physical_animation": {"enabled": True, "blend": 0.0, "recovery_seconds": 0.35},
                    "solver": {"iterations": 8, "substeps": 2},
                },
            )
            created.append(physics.asset_id)
            self.database.set_dependencies(physics.asset_id, [
                (skeleton.asset_id, "skeleton"), (mesh.asset_id, "skeletal_mesh"),
            ])
            return StarterCharacterReceipt(
                skeleton.asset_id, mesh.asset_id, binding.asset_id,
                material.asset_id, texture.asset_id, ik_rig.asset_id, control_rig.asset_id,
                physics.asset_id, str(mesh_source), str(texture.destination_path),
                len(geometry.vertices), len(geometry.triangles), len(bones), variant,
            )
        except Exception:
            priority = {
                "tc.physics_asset": 0, "tc.skeletal_mesh": 1, "tc.skin_binding": 2,
                "tc.ik_rig": 3, "tc.control_rig": 3, "tc.material": 4, "tc.texture": 5, "tc.skeleton": 6,
            }
            ordered = sorted(
                created,
                key=lambda asset_id: priority.get(
                    self.database.asset(asset_id).asset_type if self.database.asset(asset_id) else "", 9
                ),
            )
            for asset_id in ordered:
                if self.database.asset(asset_id) is None:
                    continue
                try:
                    self.operations.delete_asset(asset_id, _record_undo=False)
                except Exception:
                    pass
            mesh_source.unlink(missing_ok=True)
            raise

    def attach_to_level(
        self,
        document: FederatedSceneDocument,
        receipt: StarterCharacterReceipt,
    ) -> dict[str, bytes]:
        rows = expanded_tc_rig_template_joints()
        geometry = generate_starter_mannequin_geometry()
        world_positions = _world_joint_positions(rows)
        inverse_matrices = array.array("f")
        for row in rows:
            x, y, z = world_positions[str(row["id"])]
            inverse_matrices.extend((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1))
        influence_offsets = array.array("I", [0])
        joint_indices = array.array("I")
        weights = array.array("f")
        for influences in geometry.influences:
            for joint_index, weight in influences:
                joint_indices.append(joint_index)
                weights.append(weight)
            influence_offsets.append(len(joint_indices))
        binding = {
            "provider_id": STARTER_PROVIDER_ID,
            "skeletons": [{
                "native_id": STARTER_SKELETON_NATIVE_ID,
                "joints": [
                    {
                        "native_id": str(row["id"]), "name": str(row["id"]),
                        "parent_native_id": str(row.get("parent") or ""),
                    }
                    for row in rows
                ],
                "inverse_bind_matrices_f32": inverse_matrices,
            }],
            "meshes": [{
                "native_id": STARTER_MESH_NATIVE_ID, "skeleton_id": STARTER_SKELETON_NATIVE_ID,
                "deformation_mode": "linear_blend_skinning", "runtime_mode": "skeletal",
                "vertex_count": len(geometry.vertices),
                "bind_vertices_f32": array.array("f", [value for vertex in geometry.vertices for value in vertex]),
                "influence_offsets_u32": influence_offsets,
                "joint_indices_u32": joint_indices,
                "weights_f32": weights,
                "sparse_influence_count": len(joint_indices), "max_influences_per_vertex": 4,
            }],
        }
        blobs = document.rig_graph.merge_deformation_binding(binding)
        face_targets = tuple(
            blend_shape_target_from_dict(value) for value in _starter_face_morph_targets(geometry)
        )
        attach_blend_shape_deformer(
            document.rig_graph, f"{STARTER_PROVIDER_ID}::{STARTER_MESH_NATIVE_ID}",
            len(geometry.vertices), face_targets, deformer_id="tc_starter_face_shapes",
        )
        _author_starter_locomotion_clips(document)
        return blobs


def generate_starter_mannequin_geometry(rows: list[dict[str, Any]] | None = None) -> StarterCharacterGeometry:
    if rows is None:
        return _cached_starter_geometry()
    return _generate_starter_geometry(list(rows))


@lru_cache(maxsize=1)
def _cached_starter_geometry() -> StarterCharacterGeometry:
    return _generate_starter_geometry(expanded_tc_rig_template_joints())


def _generate_starter_geometry(rows: list[dict[str, Any]]) -> StarterCharacterGeometry:
    joint_ids = tuple(str(row["id"]) for row in rows)
    joint_index = {value: index for index, value in enumerate(joint_ids)}
    # Overlapping anisotropic capsules form one connected, watertight implicit
    # surface. Each primitive also provides a semantic skinning influence.
    primitives = (
        ((0.0, 0.92, 0.0), (0.0, 1.10, 0.0), (0.22, 0.17, 0.15), "tc_hips"),
        ((0.0, 1.04, 0.0), (0.0, 1.31, 0.0), (0.205, 0.17, 0.145), "tc_spine_01"),
        ((0.0, 1.25, 0.0), (0.0, 1.47, 0.0), (0.285, 0.18, 0.16), "tc_spine_03"),
        ((0.0, 1.45, 0.0), (0.0, 1.58, 0.0), (0.09, 0.09, 0.085), "tc_neck"),
        ((0.0, 1.62, 0.01), (0.0, 1.79, 0.015), (0.145, 0.17, 0.135), "tc_head"),
        ((0.18, 1.44, 0.0), (0.48, 1.42, 0.0), (0.105, 0.105, 0.11), "tc_l_upperarm"),
        ((0.45, 1.42, 0.0), (0.73, 1.38, 0.0), (0.085, 0.085, 0.09), "tc_l_forearm"),
        ((0.70, 1.38, 0.0), (0.91, 1.36, 0.035), (0.075, 0.065, 0.105), "tc_l_hand"),
        ((-0.18, 1.44, 0.0), (-0.48, 1.42, 0.0), (0.105, 0.105, 0.11), "tc_r_upperarm"),
        ((-0.45, 1.42, 0.0), (-0.73, 1.38, 0.0), (0.085, 0.085, 0.09), "tc_r_forearm"),
        ((-0.70, 1.38, 0.0), (-0.91, 1.36, 0.035), (0.075, 0.065, 0.105), "tc_r_hand"),
        ((0.115, 0.93, 0.0), (0.115, 0.56, 0.0), (0.12, 0.13, 0.125), "tc_l_thigh"),
        ((0.115, 0.57, 0.0), (0.115, 0.19, -0.005), (0.095, 0.105, 0.10), "tc_l_knee"),
        ((0.115, 0.17, 0.0), (0.115, 0.07, 0.20), (0.11, 0.085, 0.13), "tc_l_ankle"),
        ((-0.115, 0.93, 0.0), (-0.115, 0.56, 0.0), (0.12, 0.13, 0.125), "tc_r_thigh"),
        ((-0.115, 0.57, 0.0), (-0.115, 0.19, -0.005), (0.095, 0.105, 0.10), "tc_r_knee"),
        ((-0.115, 0.17, 0.0), (-0.115, 0.07, 0.20), (0.11, 0.085, 0.13), "tc_r_ankle"),
        # Anatomical landmarks keep the neutral silhouette readable without
        # baking gender or costume assumptions into the starter asset.
        ((0.0, 1.30, 0.09), (0.0, 1.43, 0.10), (0.235, 0.12, 0.105), "tc_spine_03"),
        ((0.12, 0.76, -0.02), (0.12, 0.48, -0.035), (0.13, 0.16, 0.13), "tc_l_thigh"),
        ((-0.12, 0.76, -0.02), (-0.12, 0.48, -0.035), (0.13, 0.16, 0.13), "tc_r_thigh"),
        ((0.115, 0.46, -0.02), (0.115, 0.23, -0.035), (0.105, 0.135, 0.11), "tc_l_knee"),
        ((-0.115, 0.46, -0.02), (-0.115, 0.23, -0.035), (0.105, 0.135, 0.11), "tc_r_knee"),
        # Facial volumes provide dedicated deformable regions for the starter
        # expressions while remaining a neutral mannequin rather than a likeness.
        ((0.0, 1.70, 0.105), (0.0, 1.70, 0.205), (0.052, 0.055, 0.065), "tc_nose_root"),
        ((0.0, 1.57, 0.015), (0.0, 1.66, 0.075), (0.115, 0.085, 0.105), "tc_jaw"),
        ((0.145, 1.71, 0.0), (0.165, 1.71, 0.0), (0.035, 0.060, 0.040), "tc_head"),
        ((-0.145, 1.71, 0.0), (-0.165, 1.71, 0.0), (0.035, 0.060, 0.040), "tc_head"),
        # Separate palm/finger capsules create a readable hand silhouette and
        # carry the existing per-finger skeleton all the way to deformation.
        ((0.82, 1.37, 0.0), (0.94, 1.37, 0.0), (0.075, 0.060, 0.085), "tc_l_hand"),
        ((0.91, 1.392, -0.055), (1.065, 1.392, -0.055), (0.028, 0.026, 0.027), "tc_l_index_01"),
        ((0.91, 1.375, -0.018), (1.085, 1.375, -0.018), (0.029, 0.027, 0.028), "tc_l_middle_01"),
        ((0.91, 1.358, 0.020), (1.055, 1.358, 0.020), (0.027, 0.025, 0.027), "tc_l_ring_01"),
        ((0.90, 1.342, 0.055), (1.020, 1.342, 0.055), (0.024, 0.023, 0.024), "tc_l_pinky_01"),
        ((0.84, 1.325, 0.055), (0.955, 1.285, 0.090), (0.032, 0.030, 0.033), "tc_l_thumb_01"),
        ((-0.82, 1.37, 0.0), (-0.94, 1.37, 0.0), (0.075, 0.060, 0.085), "tc_r_hand"),
        ((-0.91, 1.392, -0.055), (-1.065, 1.392, -0.055), (0.028, 0.026, 0.027), "tc_r_index_01"),
        ((-0.91, 1.375, -0.018), (-1.085, 1.375, -0.018), (0.029, 0.027, 0.028), "tc_r_middle_01"),
        ((-0.91, 1.358, 0.020), (-1.055, 1.358, 0.020), (0.027, 0.025, 0.027), "tc_r_ring_01"),
        ((-0.90, 1.342, 0.055), (-1.020, 1.342, 0.055), (0.024, 0.023, 0.024), "tc_r_pinky_01"),
        ((-0.84, 1.325, 0.055), (-0.955, 1.285, 0.090), (0.032, 0.030, 0.033), "tc_r_thumb_01"),
    )
    vertices, triangles = _march_implicit_humanoid(primitives)
    normals = _vertex_normals(vertices, triangles)
    uvs = tuple(
        ((math.atan2(vertex[2], vertex[0]) / (2.0 * math.pi) + 0.5) % 1.0,
         max(0.0, min(1.0, vertex[1] / 1.92)))
        for vertex in vertices
    )
    influences = tuple(_smooth_influences(vertex, primitives, joint_index) for vertex in vertices)
    return StarterCharacterGeometry(vertices, triangles, normals, uvs, influences, joint_ids)


def _skeleton_bones(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row["id"]), "name": str(row["id"]), "parent": str(row.get("parent") or ""),
            "semantic_role": str(row.get("slot") or row.get("face_slot") or "helper"),
            "reference_translation": [float(value) * 0.01 for value in row.get("t") or (0, 0, 0)],
            "lod_importance": _bone_importance(str(row.get("slot") or row.get("face_slot") or row["id"])),
        }
        for row in rows
    ]


def _capsule_distance(
    point: tuple[float, float, float],
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    radii: tuple[float, float, float],
) -> float:
    scaled_point = tuple(point[index] / radii[index] for index in range(3))
    scaled_first = tuple(first[index] / radii[index] for index in range(3))
    scaled_second = tuple(second[index] / radii[index] for index in range(3))
    segment = tuple(scaled_second[index] - scaled_first[index] for index in range(3))
    relative = tuple(scaled_point[index] - scaled_first[index] for index in range(3))
    length_squared = sum(value * value for value in segment)
    amount = 0.0 if length_squared <= 1.0e-12 else max(
        0.0, min(1.0, sum(relative[index] * segment[index] for index in range(3)) / length_squared),
    )
    closest = tuple(scaled_first[index] + segment[index] * amount for index in range(3))
    return math.sqrt(sum((scaled_point[index] - closest[index]) ** 2 for index in range(3)))


def _implicit_field(point: tuple[float, float, float], primitives: tuple[Any, ...]) -> float:
    return min(_capsule_distance(point, first, second, radii) - 1.0 for first, second, radii, _bone in primitives)


def _implicit_gradient(point: tuple[float, float, float], primitives: tuple[Any, ...]) -> tuple[float, float, float]:
    first, second, radii, _bone = min(
        primitives, key=lambda primitive: _capsule_distance(point, primitive[0], primitive[1], primitive[2]),
    )
    epsilon = 0.002
    return tuple(
        (
            _capsule_distance(tuple(point[i] + (epsilon if i == axis else 0.0) for i in range(3)), first, second, radii)
            - _capsule_distance(tuple(point[i] - (epsilon if i == axis else 0.0) for i in range(3)), first, second, radii)
        ) / (2.0 * epsilon)
        for axis in range(3)
    )


def _march_implicit_humanoid(primitives: tuple[Any, ...]) -> tuple[
    tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int], ...],
]:
    minimum = (-1.12, -0.06, -0.34)
    maximum = (1.12, 1.96, 0.40)
    counts = (47, 45, 23)
    steps = tuple((maximum[axis] - minimum[axis]) / (counts[axis] - 1) for axis in range(3))
    points: list[tuple[float, float, float]] = []
    values: list[float] = []
    for y_index in range(counts[1]):
        for z_index in range(counts[2]):
            for x_index in range(counts[0]):
                point = (
                    minimum[0] + steps[0] * x_index,
                    minimum[1] + steps[1] * y_index,
                    minimum[2] + steps[2] * z_index,
                )
                points.append(point)
                values.append(_implicit_field(point, primitives))

    def grid_index(x_index: int, y_index: int, z_index: int) -> int:
        return (y_index * counts[2] + z_index) * counts[0] + x_index

    corners = ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1),
               (0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1))
    tetrahedra = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6),
                  (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    vertex_lookup: dict[tuple[int, int, int], int] = {}

    def intersect(first_index: int, second_index: int) -> tuple[float, float, float]:
        first, second = points[first_index], points[second_index]
        first_value, second_value = values[first_index], values[second_index]
        denominator = first_value - second_value
        amount = 0.5 if abs(denominator) <= 1.0e-12 else first_value / denominator
        return tuple(first[axis] + (second[axis] - first[axis]) * amount for axis in range(3))

    def vertex_id(point: tuple[float, float, float]) -> int:
        key = tuple(int(round(value * 1_000_000.0)) for value in point)
        found = vertex_lookup.get(key)
        if found is not None:
            return found
        found = len(vertices)
        vertex_lookup[key] = found
        vertices.append(point)
        return found

    def add_triangle(first: tuple[float, float, float], second: tuple[float, float, float], third: tuple[float, float, float]) -> None:
        edge_a = tuple(second[index] - first[index] for index in range(3))
        edge_b = tuple(third[index] - first[index] for index in range(3))
        normal = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        center = tuple((first[index] + second[index] + third[index]) / 3.0 for index in range(3))
        gradient = _implicit_gradient(center, primitives)
        if sum(normal[index] * gradient[index] for index in range(3)) < 0.0:
            second, third = third, second
        triangle = (vertex_id(first), vertex_id(second), vertex_id(third))
        if len(set(triangle)) == 3:
            triangles.append(triangle)

    for y_index in range(counts[1] - 1):
        for z_index in range(counts[2] - 1):
            for x_index in range(counts[0] - 1):
                cube = tuple(grid_index(x_index + x, y_index + y, z_index + z) for x, y, z in corners)
                if all(values[index] <= 0.0 for index in cube) or all(values[index] > 0.0 for index in cube):
                    continue
                for tetrahedron in tetrahedra:
                    indices = [cube[index] for index in tetrahedron]
                    inside = [index for index in indices if values[index] <= 0.0]
                    outside = [index for index in indices if values[index] > 0.0]
                    if len(inside) in {0, 4}:
                        continue
                    if len(inside) == 1:
                        samples = [intersect(inside[0], value) for value in outside]
                        add_triangle(samples[0], samples[1], samples[2])
                    elif len(inside) == 3:
                        samples = [intersect(outside[0], value) for value in inside]
                        add_triangle(samples[0], samples[2], samples[1])
                    else:
                        first, second = inside
                        third, fourth = outside
                        a = intersect(first, third)
                        b = intersect(first, fourth)
                        c = intersect(second, third)
                        d = intersect(second, fourth)
                        add_triangle(a, c, d)
                        add_triangle(a, d, b)
    return tuple(vertices), tuple(triangles)


def _vertex_normals(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[float, float, float], ...]:
    accumulated = [[0.0, 0.0, 0.0] for _value in vertices]
    for first, second, third in triangles:
        edge_a = tuple(vertices[second][index] - vertices[first][index] for index in range(3))
        edge_b = tuple(vertices[third][index] - vertices[first][index] for index in range(3))
        normal = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        for vertex_index in (first, second, third):
            for axis in range(3):
                accumulated[vertex_index][axis] += normal[axis]
    result = []
    for normal in accumulated:
        length = math.sqrt(sum(value * value for value in normal))
        result.append(tuple(value / max(1.0e-12, length) for value in normal))
    return tuple(result)


def _smooth_influences(
    vertex: tuple[float, float, float], primitives: tuple[Any, ...], joint_index: dict[str, int],
) -> tuple[tuple[int, float], ...]:
    scored: dict[str, float] = {}
    for first, second, radii, bone in primitives:
        distance = _capsule_distance(vertex, first, second, radii)
        score = math.exp(-3.25 * distance)
        scored[bone] = max(score, scored.get(bone, 0.0))
    selected = sorted(scored.items(), key=lambda item: item[1], reverse=True)[:4]
    total = sum(value for _bone, value in selected)
    normalized = [(joint_index[bone], value / total) for bone, value in selected]
    # Make the final sum exact enough for strict cook validation.
    if normalized:
        normalized[0] = (normalized[0][0], normalized[0][1] + 1.0 - sum(value for _index, value in normalized))
    return tuple(normalized)


def _physics_joint_graph(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected = {
        "tc_hips", "tc_spine_01", "tc_spine_03", "tc_head",
        "tc_l_upperarm", "tc_l_forearm", "tc_l_hand", "tc_r_upperarm", "tc_r_forearm", "tc_r_hand",
        "tc_l_thigh", "tc_l_knee", "tc_l_ankle", "tc_r_thigh", "tc_r_knee", "tc_r_ankle",
    }
    by_id = {str(row["id"]): row for row in rows}
    world = _world_joint_positions(rows)
    result: dict[str, dict[str, Any]] = {}
    for joint_id in selected:
        parent = str(by_id[joint_id].get("parent") or "")
        while parent and parent not in selected:
            parent = str(by_id.get(parent, {}).get("parent") or "")
        matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                  0.0, 0.0, 1.0, 0.0, *world[joint_id], 1.0]
        result[joint_id] = {
            "parent_id": parent, "bind_world_matrix": matrix,
            "attributes": {"joint_role": joint_id},
        }
    return result


def _starter_ik_chains() -> list[dict[str, Any]]:
    definitions = (
        ("Left Arm", "tc_l_upperarm", "tc_l_hand", "two_bone"),
        ("Right Arm", "tc_r_upperarm", "tc_r_hand", "two_bone"),
        ("Left Leg", "tc_l_thigh", "tc_l_ankle", "two_bone"),
        ("Right Leg", "tc_r_thigh", "tc_r_ankle", "two_bone"),
        ("Spine", "tc_hips", "tc_head", "fabrik"),
    )
    return [
        {
            "name": name, "start_bone": start, "end_bone": end, "solver": solver,
            "goal": name.replace(" ", "_") + "_Goal", "pole": name.replace(" ", "_") + "_Pole",
            "settings": {"iterations": 12, "precision": 0.001, "stretch": 0.0},
        }
        for name, start, end, solver in definitions
    ]


def _starter_controls() -> list[dict[str, Any]]:
    return [
        {"name": "root", "bone": "tc_root", "shape": "circle", "color": "yellow", "space": "world", "channels": ["translate", "rotate"]},
        {"name": "hips", "bone": "tc_hips", "shape": "box", "color": "yellow", "space": "root", "channels": ["translate", "rotate"]},
        {"name": "foot_ik_l", "bone": "tc_l_ankle", "shape": "foot", "color": "blue", "space": "world", "channels": ["translate", "rotate", "foot_roll"]},
        {"name": "foot_ik_r", "bone": "tc_r_ankle", "shape": "foot", "color": "red", "space": "world", "channels": ["translate", "rotate", "foot_roll"]},
        {"name": "hand_ik_l", "bone": "tc_l_hand", "shape": "cube", "color": "blue", "space": "world", "channels": ["translate", "rotate", "finger_curl"]},
        {"name": "hand_ik_r", "bone": "tc_r_hand", "shape": "cube", "color": "red", "space": "world", "channels": ["translate", "rotate", "finger_curl"]},
        {"name": "look_at", "bone": "tc_head", "shape": "sphere", "color": "cyan", "space": "world", "channels": ["translate", "weight"]},
        {"name": "face", "bone": "tc_head", "shape": "panel", "color": "cyan", "space": "head", "channels": [
            "jaw_open", "smile", "blink_l", "blink_r", "brow_raise_l", "brow_raise_r",
        ]},
    ]


def _starter_face_morph_targets(geometry: StarterCharacterGeometry) -> list[dict[str, Any]]:
    def target(identifier: str, name: str, selector: Any, delta: Any) -> dict[str, Any]:
        deltas = {
            str(index): list(delta(vertex))
            for index, vertex in enumerate(geometry.vertices)
            if selector(vertex)
        }
        return {
            "target_id": identifier, "name": name, "weight": 0.0, "minimum": 0.0, "maximum": 1.0,
            "frames": [{"weight": 1.0, "deltas": deltas}], "mask": None, "driver": None,
            "animation_keys": [],
        }

    front = lambda vertex: vertex[2] > 0.095 and vertex[1] > 1.56  # noqa: E731
    return [
        target(
            "jaw_open", "Jaw Open",
            lambda vertex: front(vertex) and vertex[1] < 1.665 and abs(vertex[0]) < 0.13,
            lambda vertex: (0.0, -0.045 * max(0.2, (1.67 - vertex[1]) / 0.11), 0.025),
        ),
        target(
            "smile", "Smile",
            lambda vertex: front(vertex) and 1.63 < vertex[1] < 1.70 and 0.045 < abs(vertex[0]) < 0.135,
            lambda vertex: (0.018 if vertex[0] > 0 else -0.018, 0.018, 0.004),
        ),
        target(
            "blink_l", "Blink Left",
            lambda vertex: front(vertex) and vertex[0] > 0.015 and 1.69 < vertex[1] < 1.765,
            lambda vertex: (0.0, -0.018, -0.006),
        ),
        target(
            "blink_r", "Blink Right",
            lambda vertex: front(vertex) and vertex[0] < -0.015 and 1.69 < vertex[1] < 1.765,
            lambda vertex: (0.0, -0.018, -0.006),
        ),
        target(
            "brow_raise_l", "Brow Raise Left",
            lambda vertex: front(vertex) and vertex[0] > 0.0 and 1.75 < vertex[1] < 1.82,
            lambda vertex: (0.0, 0.018, 0.004),
        ),
        target(
            "brow_raise_r", "Brow Raise Right",
            lambda vertex: front(vertex) and vertex[0] < 0.0 and 1.75 < vertex[1] < 1.82,
            lambda vertex: (0.0, 0.018, 0.004),
        ),
    ]


def _world_joint_positions(rows: list[dict[str, Any]]) -> dict[str, tuple[float, float, float]]:
    positions: dict[str, tuple[float, float, float]] = {}
    for row in rows:
        local = tuple(float(value) * 0.01 for value in row.get("t") or (0, 0, 0))
        parent = positions.get(str(row.get("parent") or ""), (0.0, 0.0, 0.0))
        positions[str(row["id"])] = tuple(parent[index] + local[index] for index in range(3))
    return positions


def _author_starter_locomotion_clips(document: FederatedSceneDocument) -> None:
    graph = document.rig_graph
    joint = lambda value: f"{STARTER_PROVIDER_ID}::{value}"  # noqa: E731
    clips = (
        ("tc_idle", "TC Idle", 1, 49, 24.0),
        ("tc_walk", "TC Walk Forward", 1, 25, 24.0),
        ("tc_walk_forward_right", "TC Walk Forward Right", 1, 25, 24.0),
        ("tc_walk_right", "TC Walk Right", 1, 25, 24.0),
        ("tc_walk_backward_right", "TC Walk Backward Right", 1, 25, 24.0),
        ("tc_walk_backward", "TC Walk Backward", 1, 25, 24.0),
        ("tc_walk_backward_left", "TC Walk Backward Left", 1, 25, 24.0),
        ("tc_walk_left", "TC Walk Left", 1, 25, 24.0),
        ("tc_walk_forward_left", "TC Walk Forward Left", 1, 25, 24.0),
        ("tc_run", "TC Run", 1, 17, 24.0),
        ("tc_jump", "TC Jump", 1, 25, 24.0),
        ("tc_land", "TC Land", 1, 13, 24.0),
        ("tc_start_forward", "TC Start Forward", 1, 15, 24.0),
        ("tc_stop_forward", "TC Stop Forward", 1, 17, 24.0),
        ("tc_pivot_left", "TC Pivot Left", 1, 19, 24.0),
        ("tc_pivot_right", "TC Pivot Right", 1, 19, 24.0),
        ("tc_crouch_idle", "TC Crouch Idle", 1, 49, 24.0),
        ("tc_crouch_walk", "TC Crouch Walk", 1, 25, 24.0),
        ("tc_fall", "TC Fall", 1, 25, 24.0),
    )
    non_looping = {"tc_jump", "tc_land", "tc_start_forward", "tc_stop_forward", "tc_pivot_left", "tc_pivot_right"}
    for clip_id, name, start, end, fps in clips:
        take_id = create_take(graph, name, start_frame=start, end_frame=end, frame_rate=fps)
        graph.animation[take_id]["id"] = clip_id
        graph.animation[clip_id] = graph.animation.pop(take_id)
        graph.animation[clip_id]["loop"] = clip_id not in non_looping
    for frame, value in ((1, 0.0), (13, 0.018), (25, 0.0), (37, 0.018), (49, 0.0)):
        set_keyframe(graph, "tc_idle", joint("tc_hips"), "translateY", frame, 1.0 + value)
    directional_walks = {
        "tc_walk": 0.0, "tc_walk_forward_right": 45.0, "tc_walk_right": 90.0,
        "tc_walk_backward_right": 135.0, "tc_walk_backward": 180.0,
        "tc_walk_backward_left": -135.0, "tc_walk_left": -90.0,
        "tc_walk_forward_left": -45.0,
    }
    walk_cycles = tuple((clip, 25, 28.0) for clip in directional_walks)
    for clip, end, amplitude in (*walk_cycles, ("tc_run", 17, 44.0)):
        middle = (end + 1) // 2
        quarter = max(2, (end + 1) // 4)
        three_quarter = min(end - 1, quarter * 3)
        for bone, sign in (("tc_l_thigh", 1.0), ("tc_r_thigh", -1.0)):
            set_keyframe(graph, clip, joint(bone), "rotateX", 1, amplitude * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", middle, -amplitude * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", end, amplitude * sign)
        for bone, sign in (("tc_l_upperarm", -1.0), ("tc_r_upperarm", 1.0)):
            set_keyframe(graph, clip, joint(bone), "rotateX", 1, amplitude * 0.65 * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", middle, -amplitude * 0.65 * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", end, amplitude * 0.65 * sign)
        for bone, sign in (("tc_l_knee", 1.0), ("tc_r_knee", -1.0)):
            set_keyframe(graph, clip, joint(bone), "rotateX", 1, 8.0 if sign > 0 else 42.0)
            set_keyframe(graph, clip, joint(bone), "rotateX", middle, 42.0 if sign > 0 else 8.0)
            set_keyframe(graph, clip, joint(bone), "rotateX", end, 8.0 if sign > 0 else 42.0)
        for bone, sign in (("tc_l_ankle", 1.0), ("tc_r_ankle", -1.0)):
            set_keyframe(graph, clip, joint(bone), "rotateX", 1, -12.0 * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", middle, 12.0 * sign)
            set_keyframe(graph, clip, joint(bone), "rotateX", end, -12.0 * sign)
        stride_bob = 0.045 if clip == "tc_run" else 0.025
        for frame, value in ((1, 1.0), (quarter, 1.0 + stride_bob), (middle, 1.0), (three_quarter, 1.0 + stride_bob), (end, 1.0)):
            set_keyframe(graph, clip, joint("tc_hips"), "translateY", frame, value)
        for frame, value in ((1, -3.0), (middle, 3.0), (end, -3.0)):
            set_keyframe(graph, clip, joint("tc_spine_03"), "rotateZ", frame, value)
        graph.animation[clip]["events"] = [
            {"frame": 1, "name": "foot_contact_l"}, {"frame": middle, "name": "foot_contact_r"},
        ]
        if clip in directional_walks:
            direction = directional_walks[clip]
            set_keyframe(graph, clip, joint("tc_hips"), "rotateY", 1, direction)
            set_keyframe(graph, clip, joint("tc_hips"), "rotateY", end, direction)
    for frame, value in ((1, 1.0), (8, 1.16), (16, 1.25), (25, 1.08)):
        set_keyframe(graph, "tc_jump", joint("tc_hips"), "translateY", frame, value)
    for bone in ("tc_l_knee", "tc_r_knee"):
        for frame, value in ((1, 22.0), (8, 42.0), (16, 12.0), (25, 28.0)):
            set_keyframe(graph, "tc_jump", joint(bone), "rotateX", frame, value)
    for frame, value in ((1, 1.08), (6, 0.94), (13, 1.0)):
        set_keyframe(graph, "tc_land", joint("tc_hips"), "translateY", frame, value)
    graph.animation["tc_land"]["events"] = [{"frame": 2, "name": "land_contact"}]
    for clip, yaw in (("tc_pivot_left", -90.0), ("tc_pivot_right", 90.0)):
        for frame, value in ((1, 0.0), (10, yaw * 0.55), (19, yaw)):
            set_keyframe(graph, clip, joint("tc_hips"), "rotateY", frame, value)
        set_keyframe(graph, clip, joint("tc_l_knee"), "rotateX", 10, 28.0)
        set_keyframe(graph, clip, joint("tc_r_knee"), "rotateX", 10, 28.0)
        graph.animation[clip]["events"] = [{"frame": 10, "name": "pivot_plant"}]
    for clip, values in (
        ("tc_start_forward", ((1, 0.0), (6, 18.0), (15, 34.0))),
        ("tc_stop_forward", ((1, 34.0), (10, 16.0), (17, 0.0))),
    ):
        for frame, value in values:
            set_keyframe(graph, clip, joint("tc_l_thigh"), "rotateX", frame, value)
            set_keyframe(graph, clip, joint("tc_r_thigh"), "rotateX", frame, -value)
        graph.animation[clip]["events"] = [{"frame": values[-1][0], "name": "transition_complete"}]
    for clip in ("tc_crouch_idle", "tc_crouch_walk"):
        end = int(graph.animation[clip]["end_frame"])
        for frame in (1, end):
            set_keyframe(graph, clip, joint("tc_hips"), "translateY", frame, 0.72)
            set_keyframe(graph, clip, joint("tc_l_knee"), "rotateX", frame, 58.0)
            set_keyframe(graph, clip, joint("tc_r_knee"), "rotateX", frame, 58.0)
            set_keyframe(graph, clip, joint("tc_spine_01"), "rotateX", frame, 12.0)
    for frame, value in ((1, 8.0), (13, 20.0), (25, 28.0)):
        set_keyframe(graph, "tc_fall", joint("tc_l_upperarm"), "rotateZ", frame, value)
        set_keyframe(graph, "tc_fall", joint("tc_r_upperarm"), "rotateZ", frame, -value)


def _write_obj(path: Path, geometry: StarterCharacterGeometry, variant: str) -> None:
    lines = [f"# TC Starter Mannequin ({variant})", "o TC_Starter_Mannequin"]
    lines.extend(f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in geometry.vertices)
    lines.extend(f"vt {u:.9g} {v:.9g}" for u, v in geometry.uvs)
    lines.extend(f"vn {x:.9g} {y:.9g} {z:.9g}" for x, y, z in geometry.normals)
    lines.extend(
        f"f {a + 1}/{a + 1}/{a + 1} {b + 1}/{b + 1}/{b + 1} {c + 1}/{c + 1}/{c + 1}"
        for a, b, c in geometry.triangles
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _update_properties(database: AssetDatabase, asset_id: str, values: dict[str, Any]) -> None:
    record = database.asset(asset_id)
    if record is None:
        raise KeyError(asset_id)
    payload = json.loads(record.source_path.read_text(encoding="utf-8"))
    payload.setdefault("properties", {}).update(values)
    temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, record.source_path)
    database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)


def _presentation_variant(visual_style: str, dimensionality: str) -> str:
    if str(visual_style).casefold() == "pixel_8bit":
        return "pixel_8bit"
    if str(dimensionality).casefold() == "2.5d":
        return "side_2_5d"
    return "standard"


def _bone_importance(value: str) -> int:
    key = value.casefold()
    if any(token in key for token in ("hips", "spine", "head", "arm", "leg", "foot", "hand")):
        return 100
    if any(token in key for token in ("finger", "thumb", "lip", "brow", "tongue")):
        return 25
    return 50


def _safe_name(value: str) -> str:
    safe = "_".join(part for part in "".join(character if character.isalnum() else "_" for character in str(value)).split("_") if part)
    if not safe:
        raise ValueError("Starter character name must contain a letter or number.")
    return safe[:80]


__all__ = [
    "STARTER_CHARACTER_SCHEMA", "STARTER_MESH_NATIVE_ID", "STARTER_PROVIDER_ID",
    "STARTER_SKIN_RUNTIME_ID", "STARTER_SKELETON_NATIVE_ID", "StarterCharacterGeometry",
    "StarterCharacterReceipt", "StarterCharacterService", "generate_starter_mannequin_geometry",
]
