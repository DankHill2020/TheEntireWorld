import unittest
from unittest.mock import patch

from tech_connector.services.prompt.prompt_execution_context_service import _PLANNING_CACHE
from tech_connector.services.prompt.prompt_intent_service import _CACHE
from tech_connector.services.prompt.prompt_stage_quality_service import audit_prompt_stage_quality


TOOLS_ROOT = r"C:\depot\tools"


def _no_model(*_args, **_kwargs):
    return None


class TestPromptStageQualityService(unittest.TestCase):
    def assertAuditOk(self, report) -> None:
        if report.ok:
            return
        failures = [
            f"{item.stage}.{item.check}: {item.detail or item.actual}"
            for item in report.checks
            if not item.ok
        ]
        self.fail("\n".join(failures[:12]))

    def test_qt_generated_tool_quality_survives_full_ui_route(self) -> None:
        with patch("tech_connector.services.prompt.prompt_intent_service._model_understanding", side_effect=_no_model), patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_no_model,
        ):
            _CACHE.clear()
            _PLANNING_CACHE.clear()
            report = audit_prompt_stage_quality(
                "Build a PySide/Qt tool panel in Tech Connector that lets me search the registered Unreal/DCC operation catalog, pick an operation, edit its arguments as JSON, run/queue the function through our existing execution services, and show result/progress/errors without blocking the UI.",
                project_roots=[TOOLS_ROOT],
                expected_routes=["target_discovery"],
                expected_patterns=["code.qt_operation_runner_ui"],
                required_actions=[
                    "code.search_project",
                    "code.inspect_symbols",
                    "code.plan_patch",
                    "code.plan_expected_code",
                    "code.validate_expected_code",
                    "code.validate_patch_in_temp_workspace",
                    "code.apply_patch",
                    "code.update_tests",
                    "code.run_tests",
                ],
                required_callables=[
                    "tech_connector.services.code_operation_service.plan_expected_code",
                    "tech_connector.services.code_operation_service.validate_expected_code",
                    "tech_connector.services.code_operation_service.validate_patch_in_temp_workspace",
                ],
                require_quality_bar=True,
                require_temp_workspace_validation=True,
                include_engine_dispatch=True,
                expected_engine_actions=["send_raw"],
                expected_selected_target_suffix="tech_connector/ui/operation_runner_panel.py",
            )

        self.assertAuditOk(report)
        self.assertEqual("function_backed_artifact_generation", report.planning_mode)
        self.assertGreaterEqual(report.score, 0.99)

    def test_unreal_and_cross_dcc_plans_preserve_actual_operation_chains(self) -> None:
        cases = [
            {
                "prompt": "Make a crawling anim system in ABP_Combat with a crawl state, enter and exit transition rules, output pose wiring, compile/save, and validation.",
                "routes": ["unreal_capability"],
                "patterns": ["unreal.anim_blueprint_locomotion_crawl"],
                "actions": [
                    "blueprint.scan",
                    "anim_graph.add_state",
                    "anim_graph.add_transition_rule",
                    "anim_graph.wire_state_machine_to_output_pose",
                    "blueprint.compile_and_save",
                    "unreal.create_validation_map",
                ],
            },
            {
                "prompt": "Create Niagara muzzle flash and bullet impact FX for BP_Rifle and BP_Enemy, attach them to sockets, add replication-safe gameplay cue events, compile save and validate in a test map.",
                "routes": ["target_discovery", "unreal_capability"],
                "patterns": ["unreal.niagara_gameplay_fx"],
                "actions": [
                    "blueprint.scan",
                    "niagara.create_emitter",
                    "blueprint.attach_to_socket",
                    "blueprint.add_event",
                    "blueprint.compile_and_save",
                    "unreal.create_validation_map",
                ],
            },
            {
                "prompt": "In Blender clean up this mocap crawl animation, export it as FBX, import it into Unreal, retarget it to Manny, create a crawl blendspace, wire it into ABP_Locomotion, and validate gameplay.",
                "routes": ["unreal_capability", "pipeline_graph", "action_graph"],
                "patterns": ["cross_app.blender_to_unreal_animation"],
                "actions": [
                    "blender.scan_animation",
                    "blender.clean_animation",
                    "blender.export_fbx",
                    "import_unreal_asset",
                    "unreal.retarget_animation",
                    "unreal.create_blendspace",
                    "blueprint.scan",
                    "anim_graph.add_state",
                    "anim_graph.add_transition_rule",
                    "blueprint.compile_and_save",
                    "unreal.create_validation_map",
                ],
            },
            {
                "prompt": "In Maya adjust the MetaHuman facial control rig for a sneer, propagate DNA if available, import into Unreal, hook the facial AnimBP slot, and validate playback in Sequencer.",
                "routes": ["action_graph", "pipeline_graph", "unreal_capability"],
                "patterns": ["cross_app.maya_metahuman_facial"],
                "actions": [
                    "maya.scan_facial_rig",
                    "maya.adjust_facial_control_rig",
                    "metahuman.propagate_dna",
                    "import_unreal_asset",
                    "blueprint.scan",
                    "unreal.hook_facial_animbp_slot",
                    "blueprint.compile_and_save",
                    "sequencer.validate_playback",
                ],
            },
        ]

        with patch("tech_connector.services.prompt.prompt_intent_service._model_understanding", side_effect=_no_model), patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_no_model,
        ):
            _CACHE.clear()
            _PLANNING_CACHE.clear()
            for case in cases:
                with self.subTest(prompt=case["prompt"]):
                    report = audit_prompt_stage_quality(
                        case["prompt"],
                        project_roots=[TOOLS_ROOT],
                        expected_routes=case["routes"],
                        expected_patterns=case["patterns"],
                        required_actions=case["actions"],
                    )
                    self.assertAuditOk(report)
                    self.assertGreaterEqual(report.score, 0.99)


if __name__ == "__main__":
    unittest.main()
