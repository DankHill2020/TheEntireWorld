from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.services.action_planner_service import plan_prompt_to_action_graph
from tech_connector.ui.pipeline_node_view import PipelineNodeView


class PipelinePromptMaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_unknown_pipeline_callable_routes_to_acquisition_without_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = plan_prompt_to_action_graph(
                "Create a node pipeline that runs quantum_retopology, then validates the result.",
                [tmp],
            )

        self.assertEqual("pipeline_capability_acquisition", graph["intent"])
        self.assertTrue(graph["capability_gaps"])
        self.assertFalse(any(action["type"] == "create_node" for action in graph["actions"]))
        self.assertTrue(all(action["type"] == "search_project" for action in graph["actions"]))

    def test_prompt_materializes_three_real_connected_functions_in_node_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "record_pipeline.py"
            source.write_text(
                """def load_records(path: str, encoding: str = "utf-8") -> list[str]:
    \"\"\"Load records from the requested path.\"\"\"
    records = [path]
    return records


def normalize_records(records: list[str]) -> list[str]:
    \"\"\"Normalize loaded records.\"\"\"
    normalized = [value.strip() for value in records]
    return normalized


def summarize_records(records: list[str]) -> dict[str, int]:
    \"\"\"Summarize normalized records.\"\"\"
    summary = {"count": len(records)}
    return summary
""",
                encoding="utf-8",
            )
            prompt = (
                'Create a node pipeline that runs load_records, then normalize_records, '
                'then summarize_records, using path = "records.txt".'
            )
            graph = plan_prompt_to_action_graph(prompt, [tmp])

            create_actions = [action for action in graph["actions"] if action["type"] == "create_node"]
            self.assertEqual(3, len(create_actions))
            self.assertTrue(all(Path(action["args"]["symbol"]["file_path"]).is_file() for action in create_actions))
            load_params = create_actions[0]["args"]["params"]
            encoding_default = next(item["default"] for item in load_params if item["name"] == "encoding")
            self.assertEqual("utf-8", encoding_default.strip("'\""))
            self.assertTrue(graph["validation"]["valid"])

            view = PipelineNodeView()
            result = view.materialize_action_graph(graph)

            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(3, result["node_count"])
            self.assertEqual(4, result["link_count"])
            self.assertEqual([], view.validate_data_flow())
            self.assertEqual(
                ["load_records", "normalize_records", "summarize_records"],
                [view.nodes[step_id].symbol["name"] for step_id in view.execution_order()],
            )


if __name__ == "__main__":
    unittest.main()
