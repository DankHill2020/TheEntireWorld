from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.scene.federated_scene_service import IDENTITY_MATRIX, save_federated_scene
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_viewer_adaptive_authoring_commands_mutate_one_native_session() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        original_topology, _colors, _proxies = viewer._canonical_mesh_topology()
        original_faces = len(original_topology.faces)
        modeled = viewer.execute_adaptive_scene_command(
            "modeling.extrude_faces",
            {"face_indices": [0], "distance": 0.1, "force_local": True},
        )
        node_id = viewer.editable_rig_graph.add_node(
            "Animated",
            "dag.control",
            node_id="Animated_CTRL",
            attributes={"matrix": list(IDENTITY_MATRIX)},
        )
        take = viewer.execute_adaptive_scene_command(
            "animation.create_take",
            {"name": "Shot", "start_frame": 1, "end_frame": 24, "force_local": True},
        )
        layer = viewer.execute_adaptive_scene_command(
            "animation.add_layer",
            {"take_id": take["take_id"], "name": "Secondary", "force_local": True},
        )
        keyed = viewer.execute_adaptive_scene_command(
            "animation.set_keyframe",
            {
                "take_id": take["take_id"],
                "node_id": node_id,
                "attribute": "translate_x",
                "value": 2.0,
                "frame": 12,
                "force_local": True,
            },
        )
        painted = viewer.execute_adaptive_scene_command(
            "deformation.paint_influence",
            {"map_key": "simulation_drive", "center": [0, 0, 0], "radius": 10.0, "force_local": True},
        )
        geometry_plan = viewer.execute_adaptive_scene_command(
            "engine.build_runtime_geometry_plan",
            {"target_platforms": ["desktop"], "force_local": True},
        )
        playtest = viewer.execute_adaptive_scene_command(
            "engine.plan_playtest",
            {"target": "desktop", "force_local": True},
        )

        assert modeled["executed"] and modeled["face_count"] > original_faces
        assert layer["layer"] == "Secondary"
        assert keyed["keyed_attributes"] == ["Animated_CTRL.translate_x"]
        assert painted["changed_vertices"]
        assert geometry_plan["runtime_geometry_plan"]["inputs"]["triangle_count"] > 0
        assert playtest["playtest_plan"]["strategy"]
    finally:
        viewer.close()
        app.processEvents()


def test_viewer_default_pose_commands_are_chat_routable_and_undoable() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        original_x = viewer.mesh.vertices[0].x
        viewer.mesh.vertices[0].x = original_x + 2.0

        restored = viewer.execute_adaptive_scene_command(
            "modeling.restore_default_pose",
            {"force_local": True},
        )
        assert restored["executed"] is True
        assert viewer.mesh.vertices[0].x == original_x

        viewer.undo_viewer_action()
        assert viewer.mesh.vertices[0].x == original_x + 2.0

        updated = viewer.execute_adaptive_scene_command(
            "modeling.update_default_pose",
            {"force_local": True},
        )
        assert updated["executed"] is True
        viewer.mesh.vertices[0].x = -99.0
        viewer.mesh.restore_default_pose()
        assert viewer.mesh.vertices[0].x == original_x + 2.0
    finally:
        viewer.close()
        app.processEvents()


def test_tcscene_round_trips_mesh_default_pose(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    source = ThreeDMeshPainterViewport()
    restored = ThreeDMeshPainterViewport()
    try:
        source.mesh.vertices[0].z = 7.75
        source.mesh.update_default_pose()
        document = source.build_federated_scene_document()
        scene_path = save_federated_scene(tmp_path / "mesh_pose.tcscene", document)

        ok, message = restored.load_federated_scene_file(str(scene_path), interactive=False)

        assert ok, message
        assert restored.mesh.default_pose.positions[0][2] == 7.75
        restored.mesh.vertices[0].z = -3.0
        restored.mesh.restore_default_pose()
        assert restored.mesh.vertices[0].z == 7.75
    finally:
        source.close()
        restored.close()
        app.processEvents()
