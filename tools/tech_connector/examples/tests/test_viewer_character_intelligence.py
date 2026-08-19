import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtWidgets import QApplication

from tech_connector import viewer_cmds
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_viewer_chat_authors_explains_executes_persists_and_undoes_character_decisions() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        created = viewer_cmds.execute_active(
            "characters.create",
            character_id="mara",
            display_name="Mara",
            parameter_specs={"empathy": {"default": 0.8, "minimum": 0.0, "maximum": 1.0}},
            parameters={"empathy": 0.9},
            force_local=True,
        )
        viewer_cmds.execute_active(
            "narrative.set_world_fact", path="ceasefire", value=True, force_local=True
        )
        viewer_cmds.execute_active(
            "characters.add_rule",
            character_id="mara",
            rule_id="honor_ceasefire",
            conditions=[{"path": "world.ceasefire", "operator": "equals", "value": True}],
            action_tags=["violence"],
            outcome="deny",
            force_local=True,
        )
        viewer_cmds.execute_active(
            "characters.add_objective",
            character_id="mara",
            objective_id="protect",
            description="Protect the town",
            desired_facts={"town.safe": True},
            priority=1.0,
            force_local=True,
        )
        decision = viewer_cmds.execute_active(
            "characters.choose_action",
            character_id="mara",
            available_affordances=["gate"],
            model_proposal={"action_id": "attack", "rationale": "dramatic", "confidence": 1.0},
            actions=[
                {"action_id": "attack", "tags": ["violence"], "base_utility": 20.0},
                {
                    "action_id": "secure_gate",
                    "required_affordance": "gate",
                    "effects": {"town.safe": True},
                    "parameter_weights": {"empathy": 0.5},
                },
            ],
            execute=True,
            force_local=True,
        )

        assert created["executed"]
        assert decision["decision"]["chosen_action"] == "secure_gate"
        assert not decision["decision"]["model_proposal_accepted"]
        assert viewer.character_world.world_facts["town.safe"] is True
        assert viewer.build_federated_scene_document().metadata["character_world"]["characters"]["mara"]

        viewer.undo_viewer_action()
        assert "town.safe" not in viewer.character_world.world_facts
    finally:
        viewer.close()
        app.processEvents()
