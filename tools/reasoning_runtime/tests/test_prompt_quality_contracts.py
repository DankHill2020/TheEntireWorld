from __future__ import annotations

import unittest

from reasoning_runtime import PromptStageQualityReport, StageQualityCheck


class PromptQualityContractTests(unittest.TestCase):
    def test_quality_report_serializes_checks(self):
        report = PromptStageQualityReport(
            prompt="hello",
            ok=True,
            score=1.0,
            elapsed_ms=1.23456,
            checks=[StageQualityCheck("route", "selected", True)],
        )

        data = report.to_dict()

        self.assertEqual(data["elapsed_ms"], 1.235)
        self.assertEqual(data["checks"][0]["stage"], "route")


if __name__ == "__main__":
    unittest.main()
