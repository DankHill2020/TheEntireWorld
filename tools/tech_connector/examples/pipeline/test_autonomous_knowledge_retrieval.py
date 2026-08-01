# coding=utf-8
"""
    Unit Test Suite for Autonomous Knowledge Retrieval & C++ Graph Expert Engine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.autonomous_knowledge_retrieval_engine import (
    AutonomousKnowledgeRetrievalEngine,
)


class TestAutonomousKnowledgeRetrieval(unittest.TestCase):
    """
        Test case suite for AutonomousKnowledgeRetrievalEngine.
    """

    def setUp(self):
        """
            Sets up knowledge retrieval engine instance.
        """
        self.engine = AutonomousKnowledgeRetrievalEngine()

    def test_search_knowledge_index(self):
        """
            Tests querying SQLite knowledge index for C++ and Graph symbols.
        """
        records = self.engine.search_knowledge_index(["Blueprint", "Character", "APIResult"])
        self.assertIsInstance(records, list)

    def test_escalation_returns_evidence_plan_without_inventing_cpp_fix(self):
        solution = self.engine.escalate_and_retrieve_expert_solution(
            failed_feature="AnimGraphPoseWiring",
            failure_reason="Basic instructions added variables but Output Pose pin remained unwired."
        )

        self.assertEqual(solution["request"], "AnimGraphPoseWiring")
        self.assertEqual("add_knowledge_first", solution["decision"]["recommended"])
        self.assertFalse(solution["decision"]["mutation_allowed"])
        self.assertFalse(solution["cpp_wrapper"]["recommended"])
        self.assertNotIn("advanced_cpp_strategy", solution)


if __name__ == "__main__":
    unittest.main()
