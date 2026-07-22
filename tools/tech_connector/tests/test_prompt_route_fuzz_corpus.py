from __future__ import annotations

import json
from pathlib import Path
import unittest

from tech_connector.services.prompt_route_service import classify_prompt_route


FIXTURE = Path(__file__).parent / "fixtures" / "prompt_route_fuzz_cases.json"


class TestPromptRouteFuzzCorpus(unittest.TestCase):
    def test_prompt_mutation_fixture_is_reviewable_regression_data(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ids = [case.get("id") for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in cases:
            with self.subTest(case=case.get("id")):
                self.assertTrue(str(case.get("id") or "").strip())
                self.assertTrue(str(case.get("ground_truth") or "").strip())
                self.assertGreaterEqual(len(case.get("mutations") or []), 3)
                self.assertIn(case["ground_truth"], case["mutations"])
                self.assertTrue(case.get("expected_routes"))

    def test_checked_in_prompt_mutations_keep_expected_routes(self) -> None:
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in cases:
            expected = set(case["expected_routes"])
            for prompt in case["mutations"]:
                with self.subTest(case=case["id"], prompt=prompt):
                    decision = classify_prompt_route(prompt, project_roots=["C:/depot/tools"])
                    self.assertIn(decision.route, expected)


if __name__ == "__main__":
    unittest.main()
