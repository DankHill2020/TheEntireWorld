from __future__ import annotations

import unittest

from reasoning_runtime import EvidenceState, UnderstandingValidation


class PromptExecutionStateTests(unittest.TestCase):
    def test_evidence_state_escalates_once_per_tier(self):
        state = EvidenceState()

        self.assertTrue(state.escalate("missing source"))
        state.add({"source": "ast"}, confidence=1.2)

        data = state.to_dict()
        self.assertEqual(data["current_tier"], 1)
        self.assertEqual(data["attempted_tiers"], [0, 1])
        self.assertEqual(data["confidence"], 1.0)

    def test_understanding_validation_serializes(self):
        validation = UnderstandingValidation(
            valid=False,
            confidence=0.2,
            clarification_required=True,
        )

        self.assertTrue(validation.to_dict()["clarification_required"])


if __name__ == "__main__":
    unittest.main()
