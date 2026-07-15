import unittest

from services.studio_profile_service import (
    matching_studio_rules,
    studio_decision_profile_context,
    studio_profile_summary,
)


class TestStudioProfileService(unittest.TestCase):
    def test_profile_context_includes_decision_order(self):
        context = studio_decision_profile_context(
            "Build and connect a Maya rigging pipeline",
            host="maya",
        )
        self.assertIn("STUDIO DECISION PROFILE", context)
        self.assertIn("inspect context", context.lower())
        self.assertIn("Validate pipeline data flow", context)
        self.assertIn("registered", context.lower())

    def test_vcs_prompt_matches_vcs_rules(self):
        rules = matching_studio_rules("create a branch commit and open a GitHub PR")
        self.assertTrue(rules)
        self.assertTrue(any("source-control" in " ".join(rule.pause_when) or "source" in rule.key for rule in rules))

    def test_summary_is_structured(self):
        summary = studio_profile_summary()
        self.assertGreater(summary["rule_count"], 0)
        self.assertIn("rules", summary)


if __name__ == "__main__":
    unittest.main()
