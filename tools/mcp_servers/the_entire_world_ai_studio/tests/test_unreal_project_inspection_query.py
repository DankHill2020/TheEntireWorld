from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from engine.request_context import RequestContext
from services.dcc_execution_service import DccExecutionRequest, UnrealExecutionAdapter
from services.prompt_route_service import classify_prompt_route


class _Router:
    def __init__(self) -> None:
        self.calls = []

    def execute_unreal_operation(self, operation_key, params=None):
        self.calls.append((operation_key, dict(params or {})))
        return (
            "Unreal Project Snapshot",
            True,
            json.dumps(
                {
                    "ok": True,
                    "connected": True,
                    "mode": "standard",
                    "data": {
                        "open_project": {"project_name": "Time_Fighters.uproject"},
                        "loaded_level": "Lvl_ThirdPerson",
                        "selected_assets": [],
                        "selected_actors": [],
                        "asset_counts": {"Blueprint": 12, "SkeletalMesh": 4, "AnimSequence": 20},
                        "blueprints": ["/Game/Characters/BP_LesterPhoenix.BP_LesterPhoenix"],
                        "skeletal_meshes": ["/Game/Characters/SK_Lester.SK_Lester"],
                        "animations": ["/Game/Animations/A_Sprint.A_Sprint"],
                    },
                    "stages": [{"name": "blueprints", "ok": True, "count": 1}],
                }
            ),
        )


class TestUnrealProjectInspectionQuery(unittest.TestCase):
    def test_unreal_snapshot_prompt_routes_to_project_snapshot_capability(self) -> None:
        decision = classify_prompt_route("In Unreal take a project snapshot and report the active level and selected actors.")

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.target_identifier, "project.snapshot")
        self.assertFalse(decision.missing_info)

    def test_unreal_blueprint_name_inspection_fills_asset_path_slot(self) -> None:
        decision = classify_prompt_route("In Unreal inspect BP_LesterPhoenix and list its graphs, variables, and components.")

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.target_identifier, "blueprint.scan")
        self.assertEqual(decision.keyword_args["asset_path"], "BP_LesterPhoenix")
        self.assertFalse(decision.missing_info)

    def test_unreal_graph_modification_retains_named_target_asset(self) -> None:
        decision = classify_prompt_route(
            "In Unreal add a temporary BeginPlay debug print node to BP_LesterPhoenix EventGraph that says AIStudio BeginPlay Probe."
        )

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.intent_category, "unreal_semantic_graph_modification")
        self.assertEqual(decision.target_identifier, "BP_LesterPhoenix")
        self.assertEqual(decision.keyword_args["target_asset"], "BP_LesterPhoenix")

    def test_unreal_open_and_focus_asset_routes_to_bridge_navigation_not_pipeline_graph(self) -> None:
        decision = classify_prompt_route("In Unreal open BP_LesterPhoenix and focus the Event Graph node named BeginPlay.")

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.target_identifier, "navigation.open_asset")
        self.assertEqual(decision.callable_name, "unreal_tools.navigation.open_asset")
        self.assertEqual(decision.keyword_args["asset_path"], "BP_LesterPhoenix")
        self.assertIn("pipeline_graph", decision.rejected_routes)

    def test_read_only_project_inspection_uses_standard_asset_snapshot(self) -> None:
        router = _Router()
        context = RequestContext(
            text="In Unreal, inspect the current project for an existing sprint or stamina system and report what you find. Do not edit anything yet.",
            extras={"window": SimpleNamespace(command_router=router)},
        )
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="query",
            target_type="dcc_callable",
            target_identifier="unreal_tools.navigation.open_asset",
            callable_name="unreal_tools.navigation.open_asset",
            mutation_scope="read_only",
            original_prompt=context.text,
        )

        result = UnrealExecutionAdapter("unreal").query(request, context)

        self.assertEqual(result.status, "completed")
        self.assertEqual(router.calls[0], ("project.snapshot", {"mode": "standard", "directory": "/Game/"}))
        self.assertIn("Unreal project inspection report", result.rendered_output)
        self.assertIn("Blueprint: 12", result.rendered_output)
        self.assertIn("Recommended next plan before editing", result.rendered_output)
        self.assertNotIn('"stages"', result.rendered_output)

    def test_generic_project_snapshot_does_not_emit_gameplay_plan(self) -> None:
        adapter = UnrealExecutionAdapter("unreal")
        request = DccExecutionRequest(
            execution_environment="unreal",
            operation_mode="query",
            target_type="unreal_capability",
            target_identifier="project.snapshot",
            mutation_scope="read_only",
            original_prompt="In Unreal, take a project snapshot and report loaded level and selected actors.",
        )

        with unittest.mock.patch.object(
            adapter,
            "_run_unreal_python",
            return_value=(True, {"current_level": "/Game/Maps/TestMap", "selected_actors": ["Hero"], "selected_assets": [], "asset_counts": {"Blueprint": 3}}),
        ):
            result = adapter.query(request, RequestContext(text=request.original_prompt))

        self.assertEqual("completed", result.status)
        self.assertIn("Loaded level: `/Game/Maps/TestMap`", result.rendered_output)
        self.assertNotIn("Gameplay-system findings", result.rendered_output)
        self.assertNotIn("Recommended next plan before editing", result.rendered_output)


if __name__ == "__main__":
    unittest.main()
