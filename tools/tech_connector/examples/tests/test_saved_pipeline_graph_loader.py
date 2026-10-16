import os
import json
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QVBoxLayout

from tech_connector.app.main_window_workflows import MainWindowWorkflowsMixin
from tech_connector.ui.pipeline_node_view import PipelineNodeView


class _SelectedItem:
    def __init__(self, path: str) -> None:
        self.path = path

    def data(self, _role):
        return self.path


class _WorkflowList:
    def __init__(self, path: str) -> None:
        self.item = _SelectedItem(path)

    def selectedItems(self):
        return [self.item]


class _Stack:
    def __init__(self) -> None:
        self.index = -1

    def setCurrentIndex(self, index: int) -> None:
        self.index = index


class _GraphLoaderHarness:
    _apply_workflow_intent_links = MainWindowWorkflowsMixin._apply_workflow_intent_links
    _persist_pipeline_graph_manifest = MainWindowWorkflowsMixin._persist_pipeline_graph_manifest

    def __init__(self, manifest_path: str, manifest: dict) -> None:
        self.workflows_list = _WorkflowList(manifest_path)
        self.loaded_workflows = {manifest_path: manifest}
        self.wf_build_name = QLineEdit()
        self.wf_build_goal = QLineEdit()
        self.wf_build_host = QComboBox()
        self.wf_build_host.addItems(["maya", "cross_dcc"])
        self.wf_steps_layout = QVBoxLayout()
        self.wf_stack = _Stack()
        self.wf_node_view = PipelineNodeView()
        self.wf_builder_steps = []
        self.preview_forced = False

    def set_pipeline_composer_enabled(self, _enabled: bool) -> None:
        pass

    def _rebuild_pipeline_graph_from_steps(self) -> None:
        self.wf_node_view.clear_pipeline(push_undo=False)

    def _ensure_pipeline_symbols_available_nonblocking(self) -> None:
        pass

    def add_builder_step(self, custom_sym=None):
        symbol = dict(custom_sym or {})
        step = {
            "symbol": symbol,
            "params": list(symbol.get("params") or []),
            "outputs": list(symbol.get("outputs") or []),
            "literal_values": {},
            "table": None,
        }
        self.wf_builder_steps.append(step)
        self.wf_node_view.add_pipeline_step(step, step["params"], step["outputs"])
        return step

    def update_builder_code_preview(self, force: bool = False) -> None:
        self.preview_forced = force

    def _refresh_builder_output_consumers(self, _step_index: int) -> None:
        pass


class SavedPipelineGraphLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_saved_graph_restores_typed_literals_and_connections(self) -> None:
        manifest_path = "C:/project/workflows/cross_dcc/review.workflow.json"
        manifest = {
            "host": "cross_dcc",
            "goal": "Export from Blender and import into Unreal.",
            "function": "review_pipeline",
            "naming": {"original_function": "review_pipeline"},
            "steps": [
                {
                    "symbol": {
                        "name": "export_fbx",
                        "host": "blender",
                        "params": [{"name": "selection", "annotation": "list[str]"}],
                        "outputs": [{"name": "source_file", "annotation": "str"}],
                    },
                    "literal_values": {"selection": ""},
                },
                {
                    "symbol": {
                        "name": "import_fbx",
                        "host": "unreal",
                        "params": [{"name": "source_file", "annotation": "str"}],
                        "outputs": [{"name": "imported_paths", "annotation": "list[str]"}],
                    },
                    "literal_values": {},
                },
            ],
            "data_links": [
                {
                    "from_step": 1,
                    "from_output": "source_file",
                    "to_step": 2,
                    "to_input": "source_file",
                }
            ],
            "flow_links": [{"from_step": 1, "to_step": 2}],
        }
        harness = _GraphLoaderHarness(manifest_path, manifest)

        MainWindowWorkflowsMixin.load_selected_workflow_to_builder(harness)

        self.assertEqual("review_pipeline", harness.wf_build_name.text())
        self.assertEqual(2, len(harness.wf_node_view.nodes))
        self.assertEqual("", harness.wf_builder_steps[0]["literal_values"]["selection"])
        self.assertEqual([], harness.wf_node_view.validate_data_flow())
        self.assertEqual(2, len(harness.wf_node_view.links))
        self.assertTrue(harness.preview_forced)
        self.assertEqual(1, harness.wf_stack.index)

    def test_graph_manifest_persistence_preserves_typed_context_values(self) -> None:
        harness = _GraphLoaderHarness("unused", {})
        first = harness.add_builder_step({
            "name": "export_fbx",
            "host": "blender",
            "file_path": "C:/tools/blender_tools/io.py",
            "start_line": 9,
            "params": [{"name": "selection", "annotation": "list[str]"}],
            "outputs": [{"name": "source_file", "annotation": "str"}],
        })
        first["literal_values"] = {"selection": ["Cube", "Rig"]}
        first["literal_value_provenance"] = {"selection": "blender_live_selection"}

        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "pipeline.workflow.json"
            manifest_path.write_text('{"function": "pipeline"}', encoding="utf-8")

            harness._persist_pipeline_graph_manifest(manifest_path)

            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(["Cube", "Rig"], saved["steps"][0]["literal_values"]["selection"])
        self.assertEqual(
            "blender_live_selection",
            saved["steps"][0]["literal_value_provenance"]["selection"],
        )
        self.assertEqual(9, saved["steps"][0]["symbol"]["start_line"])


if __name__ == "__main__":
    unittest.main()
