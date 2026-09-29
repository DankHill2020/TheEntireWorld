from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.game_engine.authoring.tc_mesh_modeling_service import MeshTopology
from tech_connector.game_engine.deformation import DeformationWeightMap
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    def __init__(self) -> None:
        self.mesh = SimpleNamespace(name="HeroMesh")
        self.editable_rig_graph = EditableRigGraph()
        self.selected_mesh_vertex_indices = set()
        self.undo_labels: list[str] = []
        self.refresh_count = 0

    def _canonical_mesh_topology(self):
        return MeshTopology.from_data(
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)],
            [(0, 1, 2)],
        ), [], []

    def push_rig_undo_state(self, label: str) -> None:
        self.undo_labels.append(label)

    def refresh_scene_outliner(self) -> None:
        self.refresh_count += 1

    def update_viewport_status(self) -> None:
        pass


def _add_joint(graph: EditableRigGraph, name: str, x: float) -> str:
    matrix = IDENTITY_MATRIX[:]
    matrix[12] = x
    return graph.add_joint(name, joint_id=name, local_matrix=matrix)


def test_viewer_native_bind_and_weight_commands_mutate_rig_graph() -> None:
    viewer = _ViewerHarness()
    joints = [_add_joint(viewer.editable_rig_graph, f"Joint_{index}", float(index)) for index in range(8)]

    bound = ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.bind_skin",
        {"influences": joints, "max_influences": 8, "bind_method": "distance"},
    )
    skin_id = bound["skin_id"]
    painted = ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.paint_weights",
        {"skin_id": skin_id, "vertex_indices": [1], "influence": "Joint_7", "weight": 0.8},
    )
    pruned = ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.prune_weights",
        {"skin_id": skin_id, "threshold": 0.01, "max_influences": 4},
    )

    assert bound["summary"]["max_influences"] == 8
    assert painted["summary"]["weighted_vertices"] == 3
    assert pruned["summary"]["max_influences"] == 4
    assert viewer.editable_rig_graph.skins[skin_id]["max_influences_per_vertex"] == 4
    assert len(viewer.undo_labels) == 3
    assert viewer.refresh_count == 3


def test_viewer_remove_influence_requires_fallback_for_sole_weight() -> None:
    viewer = _ViewerHarness()
    root = _add_joint(viewer.editable_rig_graph, "Root", 0.0)
    spare = _add_joint(viewer.editable_rig_graph, "Spare", 5.0)
    bound = ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.bind_skin",
        {"influences": [root], "max_influences": 8},
    )
    skin_id = bound["skin_id"]
    ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.add_influence",
        {"skin_id": skin_id, "influence": spare},
    )
    removed = ThreeDMeshPainterViewport._execute_tc_skinning_command(
        viewer,
        "skinning.remove_influence",
        {"skin_id": skin_id, "influence": root, "fallback_influence": spare},
    )

    assert removed["summary"]["influences"] == ["Spare"]
    assert viewer.editable_rig_graph.skins[skin_id]["joint_ids"] == ["Spare"]


def test_viewer_fleshy_option_adds_paintable_deformer_without_mutating_skin_weights() -> None:
    viewer = _ViewerHarness()
    root = _add_joint(viewer.editable_rig_graph, "Root", 0.0)
    skin_id = viewer.editable_rig_graph.add_skin("HeroMesh", [root], skin_id="hero_skin")
    viewer.editable_rig_graph.skins[skin_id]["weight_overrides"] = {"0": {root: 1.0}}
    original_weights = dict(viewer.editable_rig_graph.skins[skin_id]["weight_overrides"])
    viewer._selected_skin_or_deformer = lambda: (skin_id, "skin", "HeroMesh")
    viewer.deformation_weight_map = lambda _key: DeformationWeightMap("flesh", [1.0, 0.5, 0.0])
    paint_targets = []
    viewer._select_deformation_paint_target = lambda key, label: paint_targets.append((key, label))

    ThreeDMeshPainterViewport.enable_fleshy_selected_skin(viewer)

    flesh = next(item for item in viewer.editable_rig_graph.deformers.values() if item["type"] == "flesh")
    assert flesh["settings"]["source_id"] == skin_id
    assert viewer.editable_rig_graph.skins[skin_id]["weight_overrides"] == original_weights
    assert viewer.editable_rig_graph.skins[skin_id]["fleshy"]["canonical_skin_preserved"]
    assert paint_targets[-1][0] == f"flesh:{skin_id}"


def test_viewer_secondary_motion_preset_uses_one_paintable_map_and_portable_skin() -> None:
    viewer = _ViewerHarness()
    root = _add_joint(viewer.editable_rig_graph, "Root", 0.0)
    skin_id = viewer.editable_rig_graph.add_skin("HeroMesh", [root], skin_id="hero_skin")
    viewer.editable_rig_graph.skins[skin_id]["weight_overrides"] = {"0": {root: 1.0}}
    original_weights = dict(viewer.editable_rig_graph.skins[skin_id]["weight_overrides"])
    viewer._selected_skin_or_deformer = lambda: (skin_id, "skin", "HeroMesh")
    shared_map = DeformationWeightMap("muscle", [1.0, 0.5, 0.0])
    viewer.deformation_weight_map = lambda _key: shared_map
    paint_targets = []
    viewer._select_deformation_paint_target = lambda key, label: paint_targets.append((key, label))

    ThreeDMeshPainterViewport.add_secondary_motion_preset_to_selected_skin(viewer, "muscle_follow")

    preset = viewer.editable_rig_graph.skins[skin_id]["secondary_motion_presets"][0]
    assert preset["preset_id"] == "muscle_follow"
    assert preset["canonical_skin_preserved"]
    assert len(preset["deformer_ids"]) == 2
    assert viewer.editable_rig_graph.skins[skin_id]["weight_overrides"] == original_weights
    assert paint_targets[-1][0] == f"secondary:{skin_id}:muscle_follow"


def test_viewer_muscle_commands_add_paintable_tissue_and_drive_it_live() -> None:
    viewer = _ViewerHarness()
    root = _add_joint(viewer.editable_rig_graph, "Root", 0.0)
    skin_id = viewer.editable_rig_graph.add_skin("HeroMesh", [root], skin_id="hero_skin")
    viewer.editable_rig_graph.skins[skin_id]["weight_overrides"] = {"0": {root: 1.0}}
    viewer.deformation_weight_map = lambda _key: DeformationWeightMap("muscle", [1.0, 0.5, 0.0])
    viewer._select_deformation_paint_target = lambda _key, _label: None

    added = ThreeDMeshPainterViewport._execute_tc_deformation_command(
        viewer, "deformation.add_muscle",
        {"skin_id": skin_id, "mesh_id": "HeroMesh", "contraction": 0.12, "bulge": 0.06},
    )
    activated = ThreeDMeshPainterViewport._execute_tc_deformation_command(
        viewer, "deformation.set_muscle_activation",
        {"deformer_id": added["deformer_id"], "activation": 0.35, "pose_values": {"elbow": 0.8}},
    )

    muscle = viewer.editable_rig_graph.deformers[added["deformer_id"]]
    assert muscle["type"] == "muscle"
    assert muscle["settings"]["muscle"]["contraction"] == 0.12
    assert muscle["settings"]["activation"] == 0.35
    assert muscle["settings"]["pose_values"] == {"elbow": 0.8}
    assert activated["activation"] == 0.35
    assert viewer.editable_rig_graph.skins[skin_id]["muscles"][0]["canonical_skin_preserved"]


def test_viewer_blend_shape_commands_create_targets_and_update_channels() -> None:
    viewer = _ViewerHarness()
    target = {
        "target_id": "smile", "name": "Smile", "weight": 0.0,
        "minimum": -1.0, "maximum": 1.0,
        "frames": [{"weight": 1.0, "deltas": {"1": [0.0, 0.25, 0.0]}}],
        "mask": None, "driver": None, "animation_keys": [[1.0, 0.0], [10.0, 1.0]],
    }
    added = ThreeDMeshPainterViewport._execute_tc_deformation_command(
        viewer, "deformation.add_blend_shape",
        {"mesh_id": "HeroMesh", "vertex_count": 3, "targets": [target]},
    )
    updated = ThreeDMeshPainterViewport._execute_tc_deformation_command(
        viewer, "deformation.set_blend_shape_weights",
        {"deformer_id": added["deformer_id"], "weights": {"smile": 0.75}, "frame": 6.0},
    )

    deformer = viewer.editable_rig_graph.deformers[added["deformer_id"]]
    assert deformer["type"] == "blend_shape"
    assert added["target_ids"] == ["smile"]
    assert updated["weights"] == {"smile": 0.75}
    assert deformer["settings"]["targets"][0]["frames"][0]["deltas"] == {"1": [0.0, 0.25, 0.0]}
