from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.authoring.tc_mesh_modeling_service import MeshTopology
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    def __init__(self) -> None:
        self.mesh = SimpleNamespace(name="BodyMesh")
        self.editable_rig_graph = EditableRigGraph()
        self._selected_rig_node_id = "Surface_CTRL"
        self.selected_mesh_face_indices = {0}
        self.undo_labels = []
        self.refresh_count = 0
        self.editable_rig_graph.add_node(
            "Surface Control",
            "dag.control",
            node_id=self._selected_rig_node_id,
            attributes={"matrix": list(IDENTITY_MATRIX)},
        )

    def _canonical_mesh_topology(self):
        return MeshTopology.from_data(
            [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (0.0, 3.0, 0.0)],
            [(0, 1, 2)],
        ), [], []

    def push_rig_undo_state(self, label: str) -> None:
        self.undo_labels.append(label)

    def refresh_scene_outliner(self) -> None:
        self.refresh_count += 1


def test_viewer_authors_and_evaluates_normal_constraint() -> None:
    viewer = _ViewerHarness()

    result = ThreeDMeshPainterViewport._execute_tc_surface_constraint_command(
        viewer,
        "rigging.constrain_to_normal",
        {"barycentric": (0.5, 0.25, 0.25)},
    )

    assert result["world_matrix"][12:15] == pytest.approx((0.75, 0.75, 0.0))
    assert viewer.editable_rig_graph.constraints[result["constraint_id"]]["type"] == "normal"
    assert viewer.undo_labels == ["Constrain To Surface Normal"]
    assert viewer.refresh_count == 1
