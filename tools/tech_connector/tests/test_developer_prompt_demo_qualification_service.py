from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tech_connector.game_engine.integration.developer_prompt_demo_qualification_service import (
    DEVELOPER_PROMPT_CASES,
    DEVELOPER_PROMPT_DEMO_SCHEMA,
    qualify_developer_demo_prompts,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.action_planner_service import should_route_to_action_graph


class TestDeveloperPromptDemoQualificationService(unittest.TestCase):
    def test_code_execution_flow_question_is_not_treated_as_a_pipeline(self) -> None:
        self.assertFalse(
            should_route_to_action_graph(
                "Find all callers of build_project_edit_agent_request and explain the execution flow.",
                ["C:/depot/tools"],
            )
        )

    def test_explicit_cross_host_function_contract_routes_to_pipeline(self) -> None:
        decision = classify_prompt_route(
            "Transfer animation from Maya through Blender to Unreal. Functions: "
            "maya.animation.export, blender.io.import_fbx, "
            "unreal_tools.asset_transfer_adapter.import_fbx_verified.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(decision.route, "pipeline_graph")
        self.assertEqual(decision.provider, "action_graph")
        self.assertEqual(decision.operation_mode, "compose_pipeline")

    def test_official_answers_are_content_qualified_not_route_only(self) -> None:
        report = qualify_developer_demo_prompts(
            "C:/depot/tools",
            cases=DEVELOPER_PROMPT_CASES[:2],
        )

        self.assertTrue(report["ready_for_end_to_end_demo"])
        self.assertEqual(report["summary"]["end_to_end_proven"], 2)
        rows = {row["case_id"]: row for row in report["cases"]}
        self.assertEqual(
            rows["explain_qualified_maya_function"]["evidence_level"],
            "official_answer_content",
        )
        self.assertIn(
            "Signature: `rig_arm_module(side, body_joint_map, parent_ctrl=None)`",
            rows["explain_qualified_maya_function"]["result_text"],
        )
        self.assertIn(
            "project_edit_workflow_runner_planning.py:68",
            rows["find_callers"]["result_text"],
        )
        self.assertNotIn("detect_editor_intent", rows["find_callers"]["result_text"])

    def test_pipeline_demo_gate_qualifies_generation_and_safe_failures(self) -> None:
        pipeline_cases = tuple(case for case in DEVELOPER_PROMPT_CASES if case.pipeline)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "developer_prompt_report.json"
            report = qualify_developer_demo_prompts(
                "C:/depot/tools",
                output_path=output_path,
                cases=pipeline_cases,
            )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], DEVELOPER_PROMPT_DEMO_SCHEMA)
        self.assertTrue(report["ready_for_demo"])
        self.assertEqual(report["summary"]["case_count"], 10)
        self.assertEqual(report["summary"]["passed"], 10)
        self.assertEqual(report["summary"]["safe_failure_cases"], 2)
        self.assertEqual(report["summary"]["end_to_end_proven"], 2)
        self.assertFalse(report["ready_for_end_to_end_demo"])
        self.assertEqual(report["failed_case_ids"], [])
        self.assertEqual(persisted["schema"], DEVELOPER_PROMPT_DEMO_SCHEMA)
        self.assertTrue(persisted["ready_for_demo"])

        cases_by_id = {row["case_id"]: row for row in report["cases"]}
        self.assertEqual(
            cases_by_id["blender_to_tc_engine"]["hosts"],
            ["blender", "tech_connector"],
        )
        self.assertEqual(
            cases_by_id["max_to_unreal"]["hosts"],
            ["3dsmax", "unreal"],
        )
        self.assertEqual(cases_by_id["unknown_explicit_function"]["operations"], [])
        self.assertEqual(cases_by_id["unsupported_houdini_usd_edge"]["operations"], [])
        self.assertTrue(
            all(
                check["passed"]
                for row in report["cases"]
                for check in row["checks"]
            )
        )

    def test_live_runtime_report_upgrades_matching_pipeline_evidence(self) -> None:
        case = next(row for row in DEVELOPER_PROMPT_CASES if row.case_id == "blender_to_tc_engine")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            blender_fbx = root / "handoff.fbx"
            engine_asset = root / "Project" / "Assets" / "Imported" / "handoff.fbx"
            engine_asset.parent.mkdir(parents=True)
            blender_fbx.write_bytes(b"fbx")
            engine_asset.write_bytes(b"fbx")
            evidence_path = root / "live.json"
            evidence_path.write_text(json.dumps({
                "schema": "tech_connector.live_maya_blender_e2e.v1",
                "passed": True,
                "blender_fbx": {"path": str(blender_fbx), "bytes": 3},
                "maya_parity_checks": {"animation frame range": True},
                "blender_parity_checks": {"animation range": True},
                "tech_connector_asset": {
                    "asset_id": "tc.asset.demo",
                    "asset_path": str(engine_asset),
                    "asset_type": "tc.static_mesh",
                    "valid": True,
                    "issues": [],
                },
            }), encoding="utf-8")

            report = qualify_developer_demo_prompts(
                "C:/depot/tools",
                cases=(case,),
                runtime_evidence_paths=(evidence_path,),
            )

        row = report["cases"][0]
        self.assertTrue(row["end_to_end_qualified"])
        self.assertEqual(row["evidence_level"], "live_runtime_artifact_readback")
        self.assertEqual(row["runtime_evidence"]["asset_id"], "tc.asset.demo")


if __name__ == "__main__":
    unittest.main()
