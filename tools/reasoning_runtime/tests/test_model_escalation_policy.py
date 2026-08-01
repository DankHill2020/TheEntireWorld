from __future__ import annotations

import unittest

from reasoning_runtime import ModelTier, ModelTierEscalationPolicy


class ModelEscalationPolicyTests(unittest.TestCase):
    def test_escalates_to_next_tier(self):
        policy = ModelTierEscalationPolicy(
            [
                ModelTier("small", "local", "small-model"),
                ModelTier("standard", "local", "standard-model"),
            ]
        )

        decision = policy.on_failure({"model_tier": "small", "reason": "validation failed"}, {})

        self.assertTrue(decision.escalate)
        self.assertEqual(decision.target_model_tier, "standard")
        self.assertEqual(decision.target_route["model"], "standard-model")

    def test_stops_at_top_tier(self):
        policy = ModelTierEscalationPolicy([ModelTier("standard", "local", "standard-model")])

        decision = policy.on_failure({"model_tier": "standard"}, {})

        self.assertFalse(decision.escalate)


if __name__ == "__main__":
    unittest.main()
