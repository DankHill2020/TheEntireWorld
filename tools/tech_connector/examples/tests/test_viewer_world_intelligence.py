from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtWidgets import QApplication

from tech_connector import viewer_cmds
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_viewer_chat_world_intelligence_and_game_profile_persist_and_undo() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        viewer_cmds.execute_active("characters.create", character_id="teacher", display_name="Teacher", force_local=True)
        viewer_cmds.execute_active(
            "world_ai.add_sensor", character_id="teacher", sensor_id="hearing", modality="audio", range=30.0, force_local=True
        )
        viewer_cmds.execute_active(
            "world_ai.add_behavior_graph",
            graph_id="teach",
            root_node="explain",
            nodes={"explain": {"kind": "action", "action_id": "offer_scaffold"}},
            force_local=True,
        )
        configured = viewer_cmds.execute_active(
            "gameplay.configure_experience",
            profile_id="physics_class",
            game_types=["realistic_simulation", "educational", "sandbox"],
            learning_objectives=[{"id": "forces", "description": "Explain net force", "evidence": ["prediction", "reflection"]}],
            force_local=True,
        )
        decision = viewer_cmds.execute_active(
            "world_ai.evaluate_behavior", character_id="teacher", graph_id="teach", force_local=True
        )
        visuals = viewer_cmds.execute_active(
            "gameplay.set_visual_style",
            style="8-bit",
            world_layout="2.5d",
            pixel_perfect=True,
            force_local=True,
        )
        visual_plan = viewer_cmds.execute_active(
            "gameplay.preview_visual_plan", target="web", viewport_size=[1280, 720], force_local=True
        )
        document = viewer.build_federated_scene_document()

        assert configured["executed"]
        assert decision["behavior"]["selected_action"] == "offer_scaffold"
        assert document.metadata["character_world"]["intelligence"]["sensors"]["teacher"]
        assert document.metadata["game_experience"]["profile_id"] == "physics_class"
        assert visuals["visual_settings"]["title"] == "8-Bit Pixel Art in 2.5D"
        assert visual_plan["visual_plan"]["gameplay_contract"] == "unchanged"
        assert document.metadata["game_experience"]["presentation"]["visual_style"] == "pixel_8bit"

        viewer.undo_viewer_action()
        assert viewer.game_experience_profile is not None
        assert viewer.game_experience_profile.presentation is None
        viewer.undo_viewer_action()
        assert viewer.game_experience_profile is None
    finally:
        viewer.close()
        app.processEvents()


def test_viewer_look_menu_uses_friendly_controls_without_changing_simulation() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        viewer.set_viewer_visual_style("pixel_8bit")
        viewer.set_viewer_world_layout("2.5d")
        viewer.update_viewer_visual_setting("pixel_canvas", [384, 216])
        plan = viewer.preview_viewer_visual_plan()
        presentation = viewer.game_experience_profile.presentation

        assert presentation.visual_style == "pixel_8bit"
        assert presentation.dimensionality == "2.5d"
        assert presentation.resolution.base_width == 384
        assert "8-Bit Pixel Art / 2.5D" in viewer.look_btn.toolTip()
        assert plan["visual_plan"]["simulation_contract"] == "unchanged"
    finally:
        viewer.close()
        app.processEvents()
