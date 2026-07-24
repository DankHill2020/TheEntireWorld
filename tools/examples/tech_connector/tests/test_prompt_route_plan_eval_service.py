from __future__ import annotations

from pathlib import Path
import unittest

from tech_connector.services.prompt.prompt_route_eval_service import (
    evaluate_prompt_route_cases,
    format_prompt_route_eval_detail,
    load_prompt_route_eval_cases,
)


FIXTURE = Path(__file__).parent / "fixtures" / "prompt_route_plan_eval_cases.json"


class TestPromptRoutePlanEvalService(unittest.TestCase):
    def test_plan_eval_reports_accuracy_and_timing_by_category(self) -> None:
        cases = load_prompt_route_eval_cases(FIXTURE)
        report = evaluate_prompt_route_cases(cases, project_roots=["C:/depot/tools"])

        self.assertEqual(len(cases), report.total)
        self.assertEqual(0, report.failed, report.to_dict())
        self.assertGreaterEqual(report.accuracy, 0.99)
        self.assertLess(report.average_ms, 250.0)
        self.assertIn("typo", report.by_category)
        self.assertIn("plan_only", report.by_category)

    def test_detailed_eval_report_includes_plan_contract_and_goal_trace(self) -> None:
        cases = load_prompt_route_eval_cases(FIXTURE)[:2]
        report = evaluate_prompt_route_cases(
            cases,
            project_roots=["C:/depot/tools"],
            include_details=True,
        )
        text = format_prompt_route_eval_detail(report)

        self.assertIn("Semantic contract:", text)
        self.assertIn("Planning result:", text)
        self.assertIn("Ordered goals:", text)
        self.assertIn("Execution rehearsal:", text)
        self.assertIn("actual_steps:", text)
        self.assertIn("cpp_wrapper_plans:", text)
        self.assertTrue(all(row.details for row in report.rows))
        self.assertIn("planning_result", report.rows[0].details)
        self.assertIn("execution_rehearsal", report.rows[0].details)

    def test_abp_rehearsal_has_atomic_graph_steps_and_gap_plans(self) -> None:
        cases = [
            case
            for case in load_prompt_route_eval_cases(FIXTURE)
            if case.id == "brief_unreal_abp_crawl"
        ]
        report = evaluate_prompt_route_cases(
            cases,
            project_roots=["C:/depot/tools"],
            include_details=True,
        )
        outputs = report.rows[0].details["execution_rehearsal"]["generated_outputs"]
        abp = next(item for item in outputs if item["kind"] == "unreal_abp_capability_plan")

        self.assertIn("create_or_update_states", [step["id"] for step in abp["actual_steps"]])
        self.assertEqual([], abp["capability_gaps"])
        self.assertNotIn("blueprint.scan", [gap["operation"] for gap in abp["capability_gaps"]])
        self.assertIn("blueprint.scan", [cap["operation"] for cap in abp["available_capabilities"]])
        self.assertIn("blueprint.compile_and_save", [cap["operation"] for cap in abp["available_capabilities"]])
        self.assertEqual([], abp["capability_acquisition_plans"])
        self.assertTrue(abp["cpp_wrapper_plans"])
        self.assertTrue(all(not plan.get("is_execution_blocker") for plan in abp["cpp_wrapper_plans"]))
        self.assertTrue(abp["cpp_wrapper_plans"][0]["progress_phases"])


if __name__ == "__main__":
    unittest.main()
