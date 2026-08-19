from __future__ import annotations

import unittest
from unittest.mock import patch

from tech_connector.services.action_planner_service import plan_prompt_to_action_graph
from tech_connector.services.dcc.dynamic_pipeline_compiler_service import (
    _apply_prompt_parameters,
    compile_dynamic_pipeline,
)
from tech_connector.services.dcc.operation_contract_service import (
    build_operation_contract_inventory,
    operation_contracts,
    resolve_operation_contract,
)
from tech_connector.services.dcc.pipeline_requirement_coverage_service import (
    build_pipeline_requirement_ledger,
)
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph
from tech_connector.services.action_planner_service import workflow_plan_from_action_graph


class TestDynamicPipelineCompilerService(unittest.TestCase):
    def test_inventory_includes_full_unreal_surface_lazily(self) -> None:
        inventory = build_operation_contract_inventory("C:/depot/tools")
        unreal = inventory["unreal_counts"]
        self.assertGreaterEqual(unreal["operations"], 100)
        self.assertGreaterEqual(unreal["plugin_functions"], 20)
        self.assertGreaterEqual(unreal["unreal_tools_functions"], 200)
        self.assertGreater(unreal["base_unreal_python_api"], 100_000)
        self.assertEqual(
            unreal["base_unreal_python_api"],
            inventory["lazy_providers"]["unreal_python_api"],
        )
        self.assertLess(inventory["materialized_count"], 2_000)
        self.assertGreater(inventory["total_callable_surface"], 100_000)

    def test_requirement_ledger_does_not_truncate_thirty_part_requests(self) -> None:
        requirements = [f"validate requirement {index}" for index in range(1, 31)]
        ledger = build_pipeline_requirement_ledger(
            "; then ".join(requirements),
            [
                {
                    "id": "validation_stage",
                    "host": "unreal",
                    "operation": "validate.requirements",
                    "params": {},
                    "validation": requirements,
                }
            ],
        )
        self.assertEqual(30, ledger["requirement_count"])
        self.assertEqual(30, ledger["evidence_found"])

    def test_unreal_tools_adapter_is_resolvable_from_unified_inventory(self) -> None:
        result = resolve_operation_contract(
            "unreal_tools.asset_transfer_adapter.import_fbx_verified",
            host="unreal",
            project_root="C:/depot/tools",
        )
        self.assertTrue(result["ok"], result)
        contract = result["contract"]
        self.assertEqual("import", contract["role"])
        self.assertIn("fbx", contract["formats"])
        self.assertTrue(contract["executable"])

    def test_maya_motionbuilder_unreal_is_composed_without_pair_recipe(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export mocap animation from Maya, open it in MotionBuilder, then export it to Unreal."
        )
        self.assertEqual(["maya", "motionbuilder", "unreal"], plan["hosts"])
        self.assertFalse(plan.get("gaps"), plan)
        self.assertEqual(
            [
                ("maya", "export"),
                ("motionbuilder", "import"),
                ("motionbuilder", "export"),
                ("unreal", "import"),
                ("unreal", "validate"),
            ],
            [(row["host"], row["role"]) for row in plan["stages"]],
        )
        self.assertEqual("skeleton_path", plan["required_inputs"][0]["argument"])

    def test_requested_source_preparation_is_not_dropped(self) -> None:
        plan = compile_dynamic_pipeline(
            "In Maya build a rigged proxy, export FBX to Blender, clean it, "
            "then export and import it into Unreal."
        )
        self.assertEqual(
            "pipeline.create_rigged_proxy",
            plan["stages"][0]["operation"],
        )
        self.assertEqual("prepare", plan["stages"][0]["role"])
        self.assertEqual("animation.export", plan["stages"][1]["operation"])

    def test_requested_unreal_post_import_work_is_dependency_expanded(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export mocap animation from Maya to Unreal using skeleton "
            "/Game/Characters/SK_Target, inspect root motion and compatibility, "
            "retarget incompatible animation, then report final pipeline assets."
        )
        operations = [row["operation"] for row in plan["stages"]]
        self.assertIn("animation.inspect_imported_pipeline", operations)
        self.assertIn("animation.retarget_imported_if_needed", operations)
        self.assertIn("animation.report_pipeline_assets", operations)
        self.assertLess(
            operations.index("animation.inspect_imported_pipeline"),
            operations.index("animation.retarget_imported_if_needed"),
        )
        self.assertLess(
            operations.index("animation.retarget_imported_if_needed"),
            operations.index("animation.report_pipeline_assets"),
        )
        self.assertGreater(
            plan["requirement_ledger"]["requirement_count"],
            1,
        )

    def test_unproven_requested_operation_becomes_acquisition_gap(self) -> None:
        build_operation_contract_inventory.cache_clear()
        with patch(
            "tech_connector.services.dcc.operation_evidence_service.operation_validation_receipt",
            return_value={},
        ):
            plan = compile_dynamic_pipeline(
                "Export animation from MotionBuilder to Blender, bake frames 1-90, "
                "then import it into Unreal using skeleton /Game/Characters/SK_Target "
                "inspect skeleton compatibility, retarget incompatible clips, and create "
                "BlendSpace /Game/Characters/Animations/BS_Sprint."
            )
        build_operation_contract_inventory.cache_clear()
        self.assertFalse(plan["success"])
        gap = next(
            row
            for row in plan["capability_gaps"]
            if row.get("operation") == "unreal.create_blendspace"
        )
        self.assertEqual("operation_evidence_gap", gap["kind"])
        self.assertTrue(gap["execution_blocked"])
        self.assertTrue(gap["acquisition"]["resume_original_request"])
        self.assertIn(
            "disposable host validation and structured readback",
            gap["acquisition"]["required_proof"],
        )
        acquisition = gap["acquisition_plan"]
        self.assertEqual(
            ["confirm_capability_gap", "validate_dcc_adapter", "replan_original_request"],
            [row["step_id"] for row in acquisition["steps"]],
        )
        self.assertEqual(
            "unreal.AIStudioBridgeLibrary.configure_blend_space",
            acquisition["requested_behavior_contract"][
                "required_python_bridge_call"
            ],
        )
        self.assertEqual(
            "/Game/Characters/SK_Target",
            acquisition["resume_arguments"]["skeleton_path"],
        )

    def test_explicit_frame_range_and_blendspace_path_bind_without_guessing(self) -> None:
        prompt = (
            "In Blender clean and bake frames 1-90, then in Unreal create "
            "BlendSpace /Game/Characters/Animations/BS_Sprint."
        )
        contracts = operation_contracts(host="unreal", role="post_import")
        blendspace = next(
            row for row in contracts if row.operation == "unreal.create_blendspace"
        )
        blendspace_params = dict(blendspace.optional)
        _apply_prompt_parameters(blendspace, blendspace_params, prompt)
        self.assertEqual(
            "/Game/Characters/Animations/BS_Sprint",
            blendspace_params["asset_path"],
        )

        blender = next(
            row
            for row in operation_contracts(host="blender", role="process")
            if row.operation == "blender.clean_animation"
        )
        blender_params = dict(blender.optional)
        _apply_prompt_parameters(blender, blender_params, prompt)
        self.assertEqual([1, 90], blender_params["frame_range"])

    def test_pipeline_distinguishes_registered_from_live_validated_stages(self) -> None:
        def receipt(operation):
            if operation == "unreal.create_blendspace":
                return {
                    "ok": True,
                    "fixture_id": "blendspace_fixture",
                    "validated_at": "2026-07-23T00:00:00+00:00",
                }
            return {}

        build_operation_contract_inventory.cache_clear()
        with patch(
            "tech_connector.services.dcc.operation_evidence_service.operation_validation_receipt",
            side_effect=receipt,
        ):
            plan = compile_dynamic_pipeline(
                "Export animation from MotionBuilder to Blender, bake frames 1-90, "
                "then import it into Unreal using skeleton /Game/Characters/SK_Target "
                "inspect skeleton compatibility, retarget incompatible clips, and create "
                "BlendSpace /Game/Characters/Animations/BS_Sprint."
            )
        build_operation_contract_inventory.cache_clear()

        evidence = plan["evidence_summary"]
        blendspace = next(
            row
            for row in plan["stages"]
            if row["operation"] == "unreal.create_blendspace"
        )
        self.assertTrue(blendspace["evidence"]["live_validated"])
        self.assertEqual("live_validated", blendspace["evidence"]["level"])
        self.assertGreater(evidence["not_live_validated_count"], 0)
        self.assertIn("Only stages marked live_validated", evidence["claim"])

    def test_motionbuilder_blender_unreal_compiles_typed_data_edges(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export animation from MotionBuilder to Blender, clean it, export FBX, "
            "then import it into Unreal using skeleton /Game/Characters/SK_Mannequin."
        )
        self.assertEqual(["motionbuilder", "blender", "unreal"], plan["hosts"])
        self.assertFalse(plan.get("gaps"), plan)
        self.assertTrue(plan["data_edges"])
        self.assertTrue(
            any(edge["input"] == "source_file" for edge in plan["data_edges"])
        )
        unreal_import = next(
            row
            for row in plan["stages"]
            if row["host"] == "unreal" and row["role"] == "import"
        )
        self.assertEqual(
            "/Game/Characters/SK_Mannequin",
            unreal_import["params"]["skeleton_path"],
        )

    def test_explicit_paths_survive_into_stage_parameters(self) -> None:
        plan = compile_dynamic_pipeline(
            "In Maya export animation to C:/tmp/maya_take.fbx, in Blender import it "
            "and export to C:/tmp/blender_take.fbx, then import into Unreal folder "
            "/Game/AIStudio/Take using skeleton /Game/Characters/SK_Target."
        )
        exporters = [row for row in plan["stages"] if row["role"] == "export"]
        self.assertEqual("C:/tmp/maya_take.fbx", exporters[0]["params"]["export_path"])
        self.assertEqual("C:/tmp/blender_take.fbx", exporters[1]["params"]["output_path"])
        unreal_import = next(
            row
            for row in plan["stages"]
            if row["host"] == "unreal" and row["role"] == "import"
        )
        self.assertEqual(
            "/Game/AIStudio/Take",
            unreal_import["params"]["destination_path"],
        )
        self.assertEqual(
            "/Game/Characters/SK_Target",
            unreal_import["params"]["skeleton_path"],
        )

    def test_unsupported_usd_edge_is_a_precise_gap(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export a static mesh from Houdini as USD and import it into Unreal."
        )
        self.assertFalse(plan["success"])
        self.assertEqual("missing_transfer_edge", plan["gaps"][0]["kind"])
        self.assertEqual("unreal", plan["gaps"][0]["host"])
        self.assertEqual("import", plan["gaps"][0]["role"])
        self.assertEqual("usd", plan["gaps"][0]["format"])

    def test_action_planner_uses_dynamic_compiler_and_code_is_complete(self) -> None:
        graph = plan_prompt_to_action_graph(
            "Export a static mesh from Blender to Unreal and validate registry readback."
        )
        self.assertEqual("dynamic_typed_pipeline_v1", graph["framework"])
        workflow = workflow_plan_from_action_graph(graph)
        self.assertTrue(workflow and workflow["success"], workflow)
        code = generate_pipeline_code_from_graph(
            "dynamic_pipeline",
            graph["goal"],
            workflow["steps"],
        )
        compile(code, "<generated_pipeline>", "exec")
        self.assertIn("execute_pipeline_operation", code)
        self.assertIn("asset_transfer_adapter.import_fbx_verified", code)

    def test_default_destination_is_explicitly_deferred_to_content_browser(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export a static mesh from Blender to Unreal."
        )
        unreal_import = next(
            row
            for row in plan["stages"]
            if row["host"] == "unreal" and row["role"] == "import"
        )
        self.assertEqual(
            "__CURRENT_CONTENT_BROWSER__",
            unreal_import["params"]["destination_path"],
        )
        provenance = next(
            row
            for row in plan["parameter_provenance"]
            if row["stage"] == unreal_import["id"]
            and row["parameter"] == "destination_path"
        )
        self.assertEqual("current_content_browser_at_execution", provenance["source"])
        self.assertIn("/Game/AIStudio/Imports", provenance["resolution"])

    def test_defaults_off_requires_contextual_values_instead_of_guessing(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export a static mesh from Blender to Unreal.",
            use_default_settings=False,
        )
        arguments = {row["argument"] for row in plan["required_inputs"]}
        self.assertIn("output_path", arguments)
        self.assertIn("destination_path", arguments)
        self.assertNotIn("selection", arguments)
        self.assertFalse(plan["execution_ready"])

    def test_defaults_off_accepts_explicit_custom_destination(self) -> None:
        plan = compile_dynamic_pipeline(
            "Export a static mesh from Blender to C:/tmp/prop.fbx and import it into Unreal.",
            use_default_settings=False,
            custom_settings={
                "unreal_destination_path": "/Game/Custom/Props",
                "blender.blender.export_fbx.selection": "selected",
            },
        )
        unreal_import = next(
            row
            for row in plan["stages"]
            if row["host"] == "unreal" and row["role"] == "import"
        )
        self.assertEqual(
            "/Game/Custom/Props",
            unreal_import["params"]["destination_path"],
        )
        self.assertNotIn(
            "destination_path",
            {row["argument"] for row in plan["required_inputs"]},
        )


if __name__ == "__main__":
    unittest.main()
