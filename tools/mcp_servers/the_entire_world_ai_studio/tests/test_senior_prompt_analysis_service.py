from __future__ import annotations

import unittest

from services.engineering_reasoning_service import (
    analyze_senior_prompt,
    render_senior_prompt_analysis,
)


class TestSeniorPromptAnalysisService(unittest.TestCase):

    def test_analyze_senior_prompt(self) -> None:
        """Verify prompt parsing identifies DCC targets and extracts sub-tasks."""
        prompt = "Create a climbing animation slot connection and test navigation"
        analysis = analyze_senior_prompt(prompt)
        self.assertIsInstance(analysis, dict)
        self.assertIn("primary_objective", analysis)

    def test_render_senior_prompt_analysis(self) -> None:
        """Verify rendering formats prompt analysis to markdown cleanly."""
        analysis = {
            "primary_objective": "Create a climbing animation slot connection and test navigation",
            "intent_category": "medium",
        }
        report = render_senior_prompt_analysis(analysis)
        self.assertIsInstance(report, str)
        self.assertIn("Objective:", report)
