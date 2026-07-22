from __future__ import annotations

from pathlib import Path
import unittest

from tech_connector.services.prompt_route_eval_service import (
    evaluate_prompt_route_cases,
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


if __name__ == "__main__":
    unittest.main()
