from __future__ import annotations

import unittest

from tech_connector.services.unreal.unreal_capability_audit_service import (
    audit_unreal_capability_catalogs,
)
from tech_connector.services.unreal.unreal_cpp_wrapper_service import (
    create_unreal_cpp_wrapper_plan,
)
from tech_connector.services.unreal.cpp_domain_wrapper_requirements_service import (
    audit_cpp_domain_wrapper_requirements,
)
from tech_connector.services.unreal.domain_operation_coverage_service import (
    audit_domain_operation_coverage,
)
from tech_connector.services.unreal.unreal_capability_inventory_service import (
    build_unreal_capability_inventory,
    resolve_unreal_inventory_item,
)
from tech_connector.services.unreal.capability_graph_service import (
    search_unreal_capability_graph,
)
from tech_connector.services.unreal.feature_planning_service import _local_operation_status
from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS


class TestUnrealCapabilityAuditService(unittest.TestCase):
    def test_plugin_manifest_aliases_resolve_to_operations_or_capabilities(self) -> None:
        audit = audit_unreal_capability_catalogs()

        self.assertEqual([], audit["manifest_function_gaps"])
        self.assertEqual([], audit["manifest_alias_gaps"])
        self.assertEqual([], audit["enabled_stubbed_capabilities"])
        self.assertEqual([], audit["plugin_safety_gaps"])
        self.assertIn("anim_graph.add_state", UNREAL_OPERATIONS)
        self.assertIn("anim_graph.add_transition_rule", UNREAL_OPERATIONS)
        self.assertIn("anim_graph.wire_state_machine_to_output_pose", UNREAL_OPERATIONS)
        self.assertIn("blueprint.compile_and_save", UNREAL_OPERATIONS)
        self.assertIn("animation.delete_state", UNREAL_OPERATIONS)
        self.assertIn("animation.delete_transition", UNREAL_OPERATIONS)
        self.assertIn("animation.rename_state", UNREAL_OPERATIONS)
        self.assertIn("animation.set_state_transition_rule", UNREAL_OPERATIONS)
        self.assertIn("anim_graph.synthesize_transition_rule_expression", UNREAL_OPERATIONS)

    def test_plugin_body_gaps_are_cleared_for_anim_graph_wrappers(self) -> None:
        audit = audit_unreal_capability_catalogs()

        self.assertEqual([], audit["plugin_body_gaps"])
        manifest_count = audit["counts"]["plugin_manifest_capabilities"]
        self.assertGreaterEqual(manifest_count, 48)
        self.assertEqual(manifest_count, audit["counts"]["header_functions"])
        self.assertEqual(manifest_count, audit["counts"]["cpp_functions"])
        self.assertEqual(19, audit["counts"]["cpp_domain_wrapper_requirements"])

    def test_wrapper_plan_recognizes_existing_functional_reflected_body(self) -> None:
        plan = create_unreal_cpp_wrapper_plan(
            ".",
            "add anim graph state to anim blueprint",
            apply=False,
        ).to_dict()

        self.assertEqual("add_anim_graph_state", plan["capability"])
        self.assertTrue(
            any("already implemented" in warning for warning in plan["warnings"]),
            plan["warnings"],
        )
        self.assertTrue(plan["functional_body_contract"]["ok"])

    def test_cpp_wrapper_plan_prefers_python_when_domain_api_exists(self) -> None:
        plan = create_unreal_cpp_wrapper_plan(
            ".",
            "create a Niagara emitter",
            apply=False,
        ).to_dict()

        self.assertTrue(
            any("already covered by a functional Python implementation" in warning for warning in plan["warnings"]),
            plan["warnings"],
        )

    def test_feature_planner_understands_plugin_backed_operation_status(self) -> None:
        compile_status = _local_operation_status("blueprint.compile_and_save")
        state_status = _local_operation_status("anim_graph.add_state")

        self.assertTrue(compile_status["callable_found"], compile_status)
        self.assertTrue(state_status["callable_found"], state_status)
        self.assertTrue(state_status["reason"], state_status)

    def test_remaining_domain_wrapper_requirements_are_explicit(self) -> None:
        audit = audit_cpp_domain_wrapper_requirements()
        coverage = audit_domain_operation_coverage()

        self.assertTrue(audit["ok"], audit)
        self.assertEqual([], audit["retired_without_requirement"])
        self.assertIn("niagara", audit["domains"])
        self.assertIn("pose_search", audit["domains"])
        self.assertIn("ik_retarget", audit["domains"])
        self.assertIn("physics", audit["domains"])
        for row in audit["requirements"]:
            self.assertTrue(row["wrapper_function"], row)
            self.assertTrue(row["required_modules"], row)
            self.assertTrue(row["minimum_contract"], row)
            self.assertTrue(row["validation_fixture"], row)
        self.assertEqual(20, coverage["counts"]["operations"])
        self.assertEqual(20, coverage["counts"]["python_functional"])
        self.assertEqual(0, coverage["counts"]["python_stubbed"])
        self.assertEqual(0, coverage["counts"]["implement_python_first"])
        self.assertEqual(0, coverage["counts"]["cpp_required"])
        create_emitter = next(row for row in coverage["coverage"] if row["operation"] == "niagara.create_emitter")
        self.assertEqual("python_native", create_emitter["decision"])
        for row in coverage["coverage"]:
            self.assertTrue(row["python_implementation"], row)
            self.assertTrue(row["context_builder_exists"], row)
            self.assertTrue(row["reflected_api_evidence"], row)

    def test_canonical_inventory_is_single_unreal_callable_surface(self) -> None:
        inventory = build_unreal_capability_inventory()

        self.assertTrue(inventory["ok"], inventory["gaps"])
        self.assertEqual([], inventory["gaps"]["plugin_functions_missing_from_manifest"])
        self.assertEqual([], inventory["gaps"]["manifest_functions_missing_cpp_body"])
        self.assertIn("CreateKnownAssetByClassPath", inventory["plugin_functions"])
        self.assertEqual(
            "plugin",
            inventory["plugin_aliases"]["asset.create_by_class_path"]["location"],
        )
        self.assertIn("niagara.create_emitter", inventory["operations"])
        self.assertNotIn("niagara.create_emitter", inventory["cpp_domain_wrapper_requirements"])
        self.assertEqual(
            "implemented_python",
            inventory["cpp_domain_wrapper_requirements"]["niagara.set_module_input"]["implementation_state"],
        )
        self.assertEqual(0, inventory["counts"]["unreal_tools_placeholder_functions"])
        self.assertEqual(0, inventory["counts"]["retired_operations"])

        self.assertGreater(
            inventory["counts"]["total_callable_surface"],
            inventory["counts"]["operations"],
        )
        self.assertGreater(inventory["counts"]["unreal_tools_functions"], 0)
        self.assertGreater(inventory["counts"]["total_inventory_rows"], inventory["counts"]["operations"])
        self.assertLessEqual(
            inventory["counts"]["base_unreal_python_api_materialized"],
            inventory["counts"]["base_unreal_python_api"],
        )
        self.assertIn("asset.set_reflected_property", inventory["lookup"])
        self.assertIn("unreal_tools.assets.set_reflected_property", inventory["lookup"])
        self.assertIn("unreal.AIStudioBridgeLibrary.set_reflected_asset_property", inventory["lookup"])

        resolved = resolve_unreal_inventory_item("asset.set_reflected_property")
        self.assertTrue(resolved["ok"], resolved)
        self.assertEqual("operations", resolved["section"])

        tools_resolved = resolve_unreal_inventory_item("unreal_tools.assets.set_reflected_property")
        self.assertTrue(tools_resolved["ok"], tools_resolved)
        self.assertEqual("unreal_tools_functions", tools_resolved["section"])

    def test_every_registered_operation_has_a_complete_callable_chain(self) -> None:
        audit = audit_unreal_capability_catalogs()
        incomplete = [
            row
            for row in audit["operation_callable_chains"]
            if not row["execution_chain_complete"]
        ]

        self.assertEqual([], incomplete)

    def test_reflected_unreal_python_api_is_searchable_when_index_exists(self) -> None:
        inventory = build_unreal_capability_inventory()
        if inventory["counts"]["base_unreal_python_api"] == 0:
            self.skipTest("No local reflected Unreal Python API index is available.")

        resolved = resolve_unreal_inventory_item("unreal.EditorAssetLibrary")
        self.assertTrue(resolved["ok"], resolved)
        self.assertEqual("base_unreal_python_api", resolved["section"])

        search = search_unreal_capability_graph("EditorAssetLibrary", sync=False, limit=5)
        self.assertTrue(search["success"], search)
        self.assertTrue(
            any(row.get("qualified_name") == "unreal.EditorAssetLibrary" for row in search["python_api"]),
            search["python_api"],
        )

    def test_natural_api_search_handles_context_and_typos(self) -> None:
        inventory = build_unreal_capability_inventory()
        if inventory["counts"]["base_unreal_python_api"] == 0:
            self.skipTest("No local reflected Unreal Python API index is available.")

        behavior = search_unreal_capability_graph(
            "create behavior tree blackbord key",
            sync=False,
            limit=5,
        )
        geometry = search_unreal_capability_graph(
            "geometry script boolian subtract dynamic meshes",
            sync=False,
            limit=5,
        )

        self.assertTrue(
            any("BehaviorTree" in str(row.get("qualified_name")) for row in behavior["python_api"]),
            behavior["python_api"],
        )
        self.assertEqual(
            "unreal.DynamicMesh.apply_mesh_boolean",
            geometry["python_api"][0]["qualified_name"],
        )


if __name__ == "__main__":
    unittest.main()
