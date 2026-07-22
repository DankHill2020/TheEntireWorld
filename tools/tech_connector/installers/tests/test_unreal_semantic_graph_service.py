import unittest

from tech_connector.services.prompt_route_service import classify_prompt_route
from tech_connector.services.unreal.semantic_graph_service import (
    build_semantic_graph_analysis,
    graph_edit_progress_events,
    graph_edit_threading_contract,
    is_unreal_graph_modification_request,
)
from tech_connector.services.unreal.graph_patch_service import build_patch, build_preview, execute_patch
from tech_connector.services.unreal.rewrite_plan_service import build_rewrite_plan
from tech_connector.services.unreal.unreal_operation_service import (
    build_unreal_execution_plan,
    build_unreal_prototype_params,
)


class TestUnrealSemanticGraphService(unittest.TestCase):
    def test_detects_unreal_graph_modification_request(self):
        self.assertTrue(
            is_unreal_graph_modification_request(
                "In Unreal add wall running nodes into BP_Player Event Graph"
            )
        )
        self.assertFalse(is_unreal_graph_modification_request("In Unreal what actors are selected?"))
        self.assertFalse(
            is_unreal_graph_modification_request(
                "In Unreal, inspect the current project for an existing sprint or stamina system and report what you find. Do not edit anything yet."
            )
        )

    def test_builds_traversal_semantic_graph_analysis(self):
        analysis = build_semantic_graph_analysis(
            "In Unreal improve climbing in the character Blueprint graph",
            context={
                "graphs": [{"name": "EventGraph"}],
                "functions": [{"name": "UpdateClimbing"}],
                "variables": [{"name": "bIsClimbing"}],
            },
        )

        self.assertIn("traversal", analysis["intent_domains"])
        self.assertIn("Blueprint", analysis["graph_types"])
        self.assertIn("Collision", analysis["affected_systems"])
        self.assertTrue(any("existing gameplay behavior" in item for item in analysis["preservation_checks"]))
        self.assertIn("blueprint_architecture", analysis["best_practice_domains"])
        self.assertEqual(
            analysis["edit_intelligence"]["framework"],
            "unreal_graph_edit_intelligence_v1",
        )
        self.assertTrue(
            any("insertion point" in item.lower() for item in analysis["semantic_questions"])
        )

    def test_prototype_params_include_graph_comprehension_payload(self):
        params = build_unreal_prototype_params("Unreal add wall running to my character Blueprint graph")
        graph = params["parameters"]["semantic_graph_understanding"]

        self.assertIn("traversal", graph["intent_domains"])
        self.assertIn("graph_comprehension_pipeline", params["parameters"])
        self.assertIn("integration_point_justification", params["parameters"]["requested_outputs"])

    def test_execution_plan_requires_semantic_graph_for_blueprint_graph_edit(self):
        plan = build_unreal_execution_plan("Unreal add wall running nodes to BP_Player Blueprint graph")

        self.assertTrue(plan["semantic_graph_required"])
        self.assertIn("semantic_graph_understanding", plan)
        self.assertIn("semantic_graph_understanding", plan["params"])
        self.assertTrue(
            any("semantic graph understanding" in step.lower() for step in plan["steps"])
        )

    def test_route_requires_semantic_graph_context_for_unreal_graph_edits(self):
        decision = classify_prompt_route("Unreal connect nodes in BP_Player Blueprint graph")

        self.assertEqual(decision.route, "unreal_capability")
        self.assertIn("semantic_graph_understanding", decision.required_context)
        self.assertIn("existing_behavior_preservation", decision.required_context)

    def test_semantic_graph_includes_visible_lifecycle_and_layout_contract(self):
        analysis = build_semantic_graph_analysis("Unreal add traversal guard nodes to BP_Player Event Graph")

        self.assertEqual(analysis["lifecycle_states"][0], "REQUEST_RECEIVED")
        self.assertIn("ASSET_OPENED", analysis["lifecycle_states"])
        self.assertIn("TARGET_REVERIFIED", analysis["lifecycle_states"])
        self.assertIn("LAYOUT_CLEANUP", analysis["lifecycle_states"])
        self.assertIn("navigation.open_asset", analysis["open_focus_operations"])
        self.assertIn("blueprint.focus_graph_item", analysis["open_focus_operations"])
        self.assertTrue(any(target["state"] == "EDITING" for target in analysis["focus_targets"]))
        self.assertTrue(any("Preserve the dominant graph flow" in item for item in analysis["layout_contract"]))
        self.assertIn("structural_graph_diff", analysis["post_edit_report_fields"])

    def test_execution_plan_exposes_visible_graph_edit_workflow(self):
        plan = build_unreal_execution_plan("Unreal add wall running nodes to BP_Player Blueprint graph")

        self.assertIn("ASSET_OPENED", plan["graph_edit_state_machine"])
        self.assertTrue(any("Open and focus" in step for step in plan["steps"]))
        self.assertTrue(any("Reserve graph layout space" in step for step in plan["steps"]))
        self.assertIn("graph_layout_contract", plan)

    def test_rewrite_plan_requires_open_focus_layout_and_validation(self):
        plan = build_rewrite_plan("Unreal rewire BP_Player Blueprint graph for wall running")

        self.assertEqual(plan["process_detection"]["visible_state"], "CHANGE_PLANNED")
        self.assertEqual(plan["planned_open_asset_step"]["operation"], "navigation.open_asset")
        self.assertIn("blueprint.open_graph", plan["planned_open_asset_step"]["followups"])
        self.assertIn("blueprint.focus_graph_item", plan["planned_open_asset_step"]["followups"])
        self.assertTrue(any(target["state"] == "EDITING" for target in plan["focus_targets"]))
        self.assertTrue(plan["layout_plan"]["reserve_space_before_node_creation"])
        self.assertTrue(any("Compile modified asset" in item for item in plan["post_apply_validation"]))
        self.assertEqual(
            plan["graph_edit_intelligence"]["framework"],
            "unreal_graph_edit_intelligence_v1",
        )
        self.assertTrue(any("Snapshot" in item for item in plan["preflight_checks"]))
        self.assertTrue(any("insertion" in item.lower() or "insert" in item.lower() for item in plan["insertion_strategy"]))

    def test_rewrite_plan_infers_beginplay_print_probe(self):
        plan = build_rewrite_plan(
            "In Unreal, add a temporary BeginPlay debug print node to /Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix EventGraph that says AIStudio BeginPlay Probe."
        )
        ops = plan["graph_patch_candidate"]["operations"]

        self.assertEqual(plan["target_asset"], "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix")
        self.assertEqual(plan["target_graph"], "EventGraph")
        self.assertEqual(ops[0]["node_class"], "Development|PrintString")
        self.assertEqual(ops[0]["from_node"], "K2Node_Event_0")
        self.assertEqual(ops[0]["property_value"], "AIStudio BeginPlay Probe")

    def test_rewrite_plan_infers_named_print_string_without_beginplay(self):
        plan = build_rewrite_plan(
            "In Unreal open BP_LesterPhoenix, then in BP_LesterPhoenix EventGraph add a temporary Print String node named TC_PromptProbe_Print with message TC Prompt Probe. Apply it now."
        )
        ops = plan["graph_patch_candidate"]["operations"]

        self.assertEqual(plan["target_asset"], "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix")
        self.assertEqual(plan["target_graph"], "EventGraph")
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["node"], "TC_PromptProbe_Print")
        self.assertEqual(ops[0]["node_class"], "Development|PrintString")
        self.assertEqual(ops[0]["property_value"], "TC Prompt Probe")
        self.assertNotEqual(ops[0]["node_class"], "K2Node_Knot")

    def test_rewrite_plan_infers_called_print_string_name(self):
        plan = build_rewrite_plan(
            "In Unreal inspect BP_LesterPhoenix EventGraph and preview adding a temporary Print String called TC_PreviewOnly_0715 with message Preview Only. Do not edit or save."
        )
        ops = plan["graph_patch_candidate"]["operations"]

        self.assertEqual(ops[0]["node"], "TC_PreviewOnly_0715")
        self.assertEqual(ops[0]["node_class"], "Development|PrintString")
        self.assertEqual(ops[0]["property_value"], "Preview Only")

    def test_graph_patch_preview_exposes_visible_lifecycle_requirements(self):
        patch = build_patch(
            "/Game/Characters/BP_Player",
            "EventGraph",
            [{"op": "add_node", "graph": "EventGraph", "node": "Branch_IsClimbing", "node_class": "K2Node_IfThenElse"}],
        )
        preview = build_preview(patch)

        self.assertEqual(preview.visible_state, "CHANGE_PLANNED")
        self.assertIn("navigation.open_asset", preview.open_focus_operations)
        self.assertTrue(any("Compile modified asset" in item for item in preview.post_apply_validation))
        self.assertTrue(preview.threading_contract["background_worker_required"])
        self.assertFalse(preview.threading_contract["separate_os_thread_per_stage"])
        self.assertTrue(any(stage["stage"] == "COMPILING" for stage in preview.progress_stages))

    def test_graph_patch_preview_carries_unreal_edit_intelligence(self):
        analysis = build_semantic_graph_analysis(
            "Unreal add replicated traversal guard nodes to BP_Player Event Graph",
            params={"target_asset": "/Game/Characters/BP_Player", "target_graph": "EventGraph"},
        )
        patch = build_patch(
            "/Game/Characters/BP_Player",
            "EventGraph",
            [{"op": "add_node", "graph": "EventGraph", "node": "Branch_CanWallRun", "node_class": "K2Node_IfThenElse"}],
            metadata={
                "edit_intelligence": analysis["edit_intelligence"],
                "preflight_checks": analysis["edit_intelligence"]["preflight_checks"],
                "insertion_strategy": analysis["edit_intelligence"]["insertion_strategy"],
                "troubleshooting_path": analysis["edit_intelligence"]["troubleshooting_path"],
                "repair_strategies": analysis["edit_intelligence"]["repair_strategies"],
            },
        )
        preview = build_preview(patch)

        self.assertEqual(preview.edit_intelligence["framework"], "unreal_graph_edit_intelligence_v1")
        self.assertTrue(any("Open the target asset" in item for item in preview.preflight_checks))
        self.assertTrue(any("authority" in item.lower() for item in preview.insertion_strategy))
        self.assertTrue(any("compile fails" in item.lower() for item in preview.troubleshooting_path))
        self.assertTrue(any("rollback" in item.lower() for item in preview.repair_strategies))

    def test_graph_patch_apply_fails_when_added_node_not_verified(self):
        class FakeBridge:
            def backup_blueprint_asset(self, _asset):
                return {"ok": True, "data": {"backup_asset": "/Game/Backup/BP_Player_Backup"}}

            def apply_graph_patch(self, _patch):
                return {
                    "ok": True,
                    "data": {
                        "applied": True,
                        "compile_ok": True,
                        "graph_snapshot_after": {"graphs": [{"name": "EventGraph", "nodes": []}]},
                    },
                }

        patch = build_patch(
            "/Game/Characters/BP_Player",
            "EventGraph",
            [{"op": "add_node", "graph": "EventGraph", "node": "Probe_Print", "node_class": "Development|PrintString", "property_name": "InString", "property_value": "Probe"}],
        )
        result = execute_patch(
            patch,
            graph_snapshot={"graphs": [{"name": "EventGraph", "nodes": []}]},
            allow_apply=True,
            bridge=FakeBridge(),
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.applied)
        self.assertTrue(result.validation["validation_errors"])
        self.assertTrue(any("Post-apply graph snapshot" in item for item in result.validation["validation_errors"]))

    def test_graph_patch_apply_fails_when_nothing_applied(self):
        class FakeBridge:
            def backup_blueprint_asset(self, _asset):
                return {"ok": True, "data": {"backup_asset": "/Game/Backup/BP_Player_Backup"}}

            def apply_graph_patch(self, _patch):
                return {
                    "ok": True,
                    "data": {
                        "applied": False,
                        "compile_ok": True,
                        "warnings": ["Unsupported node class"],
                        "graph_snapshot_after": {"name": "EventGraph", "nodes": []},
                    },
                }

        patch = build_patch(
            "/Game/Characters/BP_Player",
            "EventGraph",
            [{"op": "add_node", "graph": "EventGraph", "node": "Reroute", "node_class": "K2Node_Knot"}],
        )
        result = execute_patch(
            patch,
            graph_snapshot={"graphs": [{"name": "EventGraph", "nodes": []}]},
            allow_apply=True,
            bridge=FakeBridge(),
        )

        self.assertFalse(result.ok)
        self.assertFalse(result.applied)
        self.assertIn("No requested graph operations were applied.", result.validation["validation_errors"])

    def test_graph_patch_apply_passes_when_added_print_node_is_verified(self):
        class FakeBridge:
            def backup_blueprint_asset(self, _asset):
                return {"ok": True, "data": {"backup_asset": "/Game/Backup/BP_Player_Backup"}}

            def apply_graph_patch(self, _patch):
                return {
                    "ok": True,
                    "data": {
                        "applied": True,
                        "compile_ok": True,
                        "graph_snapshot_after": {
                            "graphs": [
                                {
                                    "name": "EventGraph",
                                    "nodes": [
                                        {
                                            "name": "K2Node_CallFunction_9",
                                            "class": "K2Node_CallFunction PrintString",
                                            "pins": [{"name": "InString", "value": "Probe"}],
                                        }
                                    ],
                                }
                            ]
                        },
                    },
                }

        patch = build_patch(
            "/Game/Characters/BP_Player",
            "EventGraph",
            [{"op": "add_node", "graph": "EventGraph", "node": "Probe_Print", "node_class": "Development|PrintString", "property_name": "InString", "property_value": "Probe"}],
        )
        result = execute_patch(
            patch,
            graph_snapshot={"graphs": [{"name": "EventGraph", "nodes": []}]},
            allow_apply=True,
            bridge=FakeBridge(),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.validation["validation_errors"], [])

    def test_graph_edit_progress_contract_is_visible_and_ordered(self):
        contract = graph_edit_threading_contract()
        events = graph_edit_progress_events()

        self.assertTrue(contract["background_worker_required"])
        self.assertFalse(contract["separate_os_thread_per_stage"])
        self.assertEqual(events[0]["stage"], "REQUEST_RECEIVED")
        self.assertEqual(events[-1]["stage"], "COMPLETED")
        self.assertTrue(all(event["current"] for event in events))
        self.assertTrue(any(event["stage"] == "LAYOUT_CLEANUP" for event in events))

    def test_execution_plan_carries_progress_contract(self):
        plan = build_unreal_execution_plan("Unreal add wall running nodes to BP_Player Blueprint graph")

        self.assertTrue(plan["graph_edit_threading_contract"]["background_worker_required"])
        self.assertFalse(plan["graph_edit_threading_contract"]["separate_os_thread_per_stage"])
        self.assertTrue(any(stage["state"] == "VALIDATING" for stage in plan["graph_edit_progress_stages"]))


if __name__ == "__main__":
    unittest.main()
