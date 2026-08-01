from __future__ import annotations

import unittest

from reasoning_runtime import extract_plan_verification


class PlanVerificationHelperTests(unittest.TestCase):
    def test_extracts_nested_verification_payload(self):
        payload = {
            "capability_gap_plan": {
                "request_plan_verification": {
                    "matches_request": False,
                    "missing": [{"text": "target"}],
                }
            }
        }

        result = extract_plan_verification(payload)

        self.assertFalse(result["matches_request"])
        self.assertEqual(result["missing"][0]["text"], "target")


if __name__ == "__main__":
    unittest.main()
