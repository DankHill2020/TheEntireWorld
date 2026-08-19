"""Create a minimal character proving TC-native animation and sparse skinning."""

from __future__ import annotations

import array
from pathlib import Path

from tech_connector.game_engine.authoring.tc_animation_take_service import create_take, set_keyframe
from tech_connector.game_engine.scene.federated_scene_service import FederatedSceneDocument, save_federated_scene


def create_skinned_character_sample(path: str | Path) -> Path:
    mesh = Path(__file__).with_name("assets") / "skinned_strip.obj"
    skin_id = "native_fbx::character_rig::character_mesh"
    document = FederatedSceneDocument(
        name="TC Native Skinned Character",
        metadata={"runtime_world": {
            "hud_text": "TC Native Skeleton + Sparse Skin",
            "rendering": {"lighting_profile": "studio_neutral", "upscaler": "tc_temporal"},
            "entities": [
                {"name": "Character", "render": {"mesh": str(mesh), "skin_binding": skin_id, "base_color": [0.08, 0.62, 0.92], "roughness": 0.32}},
                {"name": "RuntimeCamera", "transform": {"position": [0, 1.1, -6]}, "camera": {"active": True, "field_of_view": 45, "look_at": [0, 1, 0]}},
                {"name": "Sun", "light": {}},
            ],
            "begin_play": [{"node_id": "play", "operation": "animation.play", "arguments": ["wave", "restart"]}],
        }},
    )
    identity = array.array("f", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    binding = {
        "provider_id": "native_fbx",
        "skeletons": [{
            "native_id": "character_rig",
            "joints": [{"native_id": "root", "name": "Root"}, {"native_id": "tip", "name": "Tip", "parent_native_id": "root"}],
            "inverse_bind_matrices_f32": array.array("f", list(identity) + list(identity)),
        }],
        "meshes": [{
            "native_id": "character_mesh", "skeleton_id": "character_rig", "deformation_mode": "linear_blend_skinning",
            "runtime_mode": "skeletal", "vertex_count": 4,
            "bind_vertices_f32": array.array("f", [-0.5, 0, 0, 0.5, 0, 0, -0.5, 2, 0, 0.5, 2, 0]),
            "influence_offsets_u32": array.array("I", [0, 1, 2, 3, 4]),
            "joint_indices_u32": array.array("I", [0, 0, 1, 1]),
            "weights_f32": array.array("f", [1, 1, 1, 1]), "sparse_influence_count": 4,
            "max_influences_per_vertex": 1,
        }],
    }
    blobs = document.rig_graph.merge_deformation_binding(binding)
    take = create_take(document.rig_graph, "Wave", start_frame=1, end_frame=49, frame_rate=24)
    document.rig_graph.animation[take]["id"] = "wave"
    document.rig_graph.animation["wave"] = document.rig_graph.animation.pop(take)
    set_keyframe(document.rig_graph, "wave", "native_fbx::tip", "translateX", 1, 0)
    set_keyframe(document.rig_graph, "wave", "native_fbx::tip", "translateX", 25, 1.25)
    set_keyframe(document.rig_graph, "wave", "native_fbx::tip", "translateX", 49, 0)
    return save_federated_scene(path, document, blobs=blobs)


__all__ = ["create_skinned_character_sample"]
