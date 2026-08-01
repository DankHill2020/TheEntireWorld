from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.services.pipeline_graph_intelligence_service import (
    analyze_pipeline_graph,
    compact_pipeline_graph_report,
)
from tech_connector.ui.pipeline_node_view import PipelineNodeView


class PipelineGraphIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_required_input_gets_troubleshooting_path(self):
        snapshot = {
            "nodes": [
                {
                    "step_id": "step_1",
                    "name": "create_rig",
                    "params": [{"name": "body"}],
                    "outputs": [],
                }
            ],
            "links": [],
        }
        issues = [
            {
                "step_id": "step_1",
                "node": "create_rig",
                "input": "body",
                "message": "create_rig.body needs a value or data connection.",
            }
        ]

        analysis = analyze_pipeline_graph(snapshot, issues)

        self.assertEqual(analysis["framework"], "pipeline_graph_intelligence_v1")
        self.assertEqual(analysis["status"], "blocked")
        self.assertEqual(analysis["issues"][0]["category"], "unfilled_required_input")
        self.assertTrue(any("Add and Connect Context" in action for action in analysis["issues"][0]["suggested_actions"]))
        self.assertTrue(any("Resolve required inputs" in action for action in analysis["next_actions"]))
        self.assertTrue(any("Prefer Add and Connect" in step for step in analysis["troubleshooting_path"]))

    def test_repair_candidates_match_existing_outputs(self):
        snapshot = {
            "nodes": [
                {
                    "step_id": "step_1",
                    "name": "create_rig_mapping",
                    "params": [],
                    "outputs": [{"name": "body", "python_type": "dict"}],
                },
                {
                    "step_id": "step_2",
                    "name": "create_rig",
                    "params": [{"name": "body"}],
                    "outputs": [],
                },
            ],
            "links": [],
        }
        issues = [
            {
                "step_id": "step_2",
                "node": "create_rig",
                "input": "body",
                "message": "create_rig.body needs a value or data connection.",
            }
        ]

        analysis = analyze_pipeline_graph(snapshot, issues)

        candidates = analysis["repair_candidates"]
        self.assertTrue(any(candidate["action"] == "connect_existing_output" for candidate in candidates))
        self.assertTrue(any(candidate.get("from") == "create_rig_mapping.body" for candidate in candidates))

    def test_pipeline_node_view_exposes_graph_intelligence_report(self):
        view = PipelineNodeView()
        producer = {
            "name": "create_rig_mapping",
            "provider_id": "maya",
            "kind": "function",
            "params": [],
            "outputs": [{"name": "body", "python_type": "dict"}],
            "public_tool": True,
        }
        consumer = {
            "name": "create_rig",
            "provider_id": "maya",
            "kind": "function",
            "params": [{"name": "body", "python_type": "dict"}],
            "outputs": [{"name": "rig", "python_type": "str"}],
            "public_tool": True,
        }
        view.add_pipeline_step({"symbol": producer}, [], producer["outputs"])
        view.add_pipeline_step({"symbol": consumer}, consumer["params"], consumer["outputs"])

        report = view.graph_intelligence_report()

        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(candidate.get("from") == "create_rig_mapping.body" for candidate in report["repair_candidates"]))
        compact = compact_pipeline_graph_report(report)
        self.assertIn("Pipeline graph", compact)

    def test_pipeline_node_view_reports_ready_after_context_connection(self):
        view = PipelineNodeView()
        producer = {
            "name": "create_rig_mapping",
            "provider_id": "maya",
            "kind": "function",
            "params": [],
            "outputs": [{"name": "body", "python_type": "dict"}],
            "public_tool": True,
        }
        consumer = {
            "name": "create_rig",
            "provider_id": "maya",
            "kind": "function",
            "params": [{"name": "body", "python_type": "dict"}],
            "outputs": [{"name": "rig", "python_type": "str"}],
            "public_tool": True,
        }
        view.add_pipeline_step({"symbol": producer}, [], producer["outputs"])
        suggestions = view.context_connection_suggestions(consumer)
        view.add_tool_node_with_existing_context(consumer, suggestions)

        report = view.graph_intelligence_report()

        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["issues"])
        self.assertTrue(any("Compile/save" in action for action in report["next_actions"]))


if __name__ == "__main__":
    unittest.main()
