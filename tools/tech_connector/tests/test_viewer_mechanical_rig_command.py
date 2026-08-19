from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    def __init__(self) -> None:
        self.editable_rig_graph = EditableRigGraph()
        self.editable_rig_graph.add_node("Driver", "dag.control", node_id="Driver", attributes={"rotateY": 20.0})
        self.editable_rig_graph.add_node("Driven", "dag.control", node_id="Driven", attributes={"rotateY": 0.0})
        self._viewer_undo_stack = []
        self.refresh_count = 0

    def push_rig_undo_state(self, label: str) -> None:
        self._viewer_undo_stack.append(label)

    def refresh_scene_outliner(self) -> None:
        self.refresh_count += 1


def test_viewer_creates_live_mechanical_relationship() -> None:
    viewer = _ViewerHarness()

    result = ThreeDMeshPainterViewport._execute_tc_mechanical_rig_command(
        viewer,
        {"mode": "gear", "driver": "Driver", "driven": "Driven", "ratio": -2.0},
    )
    evaluated = evaluate_rig_graph(viewer.editable_rig_graph)

    assert result["mechanical_rig"]["mode"] == "gear"
    assert evaluated.attributes["Driven"]["rotateY"] == -40.0
    assert viewer._viewer_undo_stack == ["Create Mechanical Rig"]
    assert viewer.refresh_count == 1
