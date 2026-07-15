from __future__ import annotations

import unittest

from services.rag_sufficiency_service import (
    build_rag_evidence_packet,
    evaluate_project_rag_sufficiency,
    render_rag_sufficiency_summary,
)


class TestRagSufficiencyService(unittest.TestCase):
    def test_direct_fact_query_with_exact_evidence_stops_before_model(self) -> None:
        result = evaluate_project_rag_sufficiency(
            "What functions do I have to create a rig?",
            "\n".join(
                [
                    "Project retrieval plan:",
                    "Mode: symbol",
                    "Exact symbol/source matches:",
                    "[1] function create_full_rig lines 10-40",
                    "File: C:/depot/tools/maya_tools/Rigging/create_rig.py",
                    "Source: local project knowledge index.",
                ]
            ),
        )

        self.assertTrue(result.answerable)
        self.assertEqual("none_deterministic", result.model_tier)
        self.assertEqual("deterministic_answer", result.recommended_next_stage)

    def test_edit_request_escalates_to_planning_and_code_tiers(self) -> None:
        result = evaluate_project_rag_sufficiency(
            "Create a Maya UI around create_full_rig",
            "\n".join(
                [
                    "Project retrieval plan:",
                    "Exact symbol/source matches:",
                    "[1] function create_full_rig lines 10-40",
                    "File: C:/depot/tools/maya_tools/Rigging/create_rig.py",
                ]
            ),
            intent="project_edit",
        )

        self.assertFalse(result.answerable)
        self.assertEqual("project_edit", result.route)
        self.assertEqual("local_plan_then_local_code", result.model_tier)

    def test_missing_evidence_broadens_retrieval_or_asks(self) -> None:
        result = evaluate_project_rag_sufficiency(
            "Where is the stamina system?",
            "No matching symbols found in the project index.",
        )

        self.assertFalse(result.answerable)
        self.assertIn("matching indexed project symbols or chunks", result.missing_requirements)

    def test_evidence_packet_is_compact_and_structured(self) -> None:
        result = evaluate_project_rag_sufficiency(
            "Summarize rig functions",
            "Exact symbol/source matches:\n" + ("x" * 5000),
        )
        packet = build_rag_evidence_packet(
            "Summarize rig functions",
            "Exact symbol/source matches:\n" + ("x" * 5000),
            result,
            max_chars=700,
        )

        self.assertEqual("adaptive_project_rag_v1", packet["framework"])
        self.assertLessEqual(len(packet["evidence_excerpt"]), 700)
        self.assertIn("sufficiency", packet)
        self.assertIn("RAG sufficiency:", render_rag_sufficiency_summary(result))


if __name__ == "__main__":
    unittest.main()
