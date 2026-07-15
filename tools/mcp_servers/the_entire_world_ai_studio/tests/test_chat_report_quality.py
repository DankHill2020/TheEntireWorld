from __future__ import annotations

import unittest

from services.chat_report_service import (
    documentation_quality_checklist,
    format_documentation_report,
    format_error_report,
)
from services.multi_stage_reasoning_service import build_reasoning_pipeline


class TestChatReportQuality(unittest.TestCase):
    def test_error_report_leads_with_user_quality_sections(self) -> None:
        try:
            raise RuntimeError("graph connection is missing required input")
        except RuntimeError as exc:
            report = format_error_report(
                title="Pipeline Error",
                summary="Save / Compile failed.",
                operation="pipeline compile",
                exception=exc,
                context={"node": "load_rig_mapping"},
                recovery=["Connect the required input and compile again."],
                validation=["Graph compile was blocked before execution."],
            )

        self.assertIn("**What happened**", report)
        self.assertIn("**User impact**", report)
        self.assertIn("**Evidence**", report)
        self.assertIn("**Recovery / next action**", report)
        self.assertIn("**Validation**", report)
        self.assertIn("RuntimeError", report)
        self.assertLess(report.index("**What happened**"), report.index("**Traceback**"))

    def test_documentation_report_uses_shared_quality_bar(self) -> None:
        report = format_documentation_report(
            topic="Mobile pairing",
            summary="Pairing documentation should explain QR scan, token privacy, and recovery.",
            evidence=["Desktop exposes pair and download QR routes."],
            gaps=["Store installation steps still need platform-specific screenshots."],
            validation=["Checked current mobile server routes."],
        )

        self.assertIn("**Quality Standard**", report)
        self.assertIn("verified facts", report)
        self.assertIn("**Gaps / Unknowns**", report)

    def test_reasoning_pipeline_requires_report_quality_in_validation(self) -> None:
        plan = build_reasoning_pipeline(
            "Fix the pipeline compile error and report what changed",
            {
                "route": "pipeline_graph",
                "provider": "action_graph",
                "confidence": 0.8,
                "requires_plan": True,
                "mutation_scope": "local_reversible_mutation",
                "senior_prompt_analysis": {},
            },
        )
        stages = {stage["key"]: stage for stage in plan["stages"]}
        validation_evidence = "\n".join(stages["validation"]["evidence"])
        post_gates = "\n".join(stages["post_execution_validation"]["verification_gate"])
        self.assertIn("report quality", validation_evidence)
        self.assertIn("evidence, validation, and recovery", post_gates)

    def test_quality_checklist_mentions_recovery(self) -> None:
        checklist = "\n".join(documentation_quality_checklist())
        self.assertIn("recovery", checklist.lower())


if __name__ == "__main__":
    unittest.main()
