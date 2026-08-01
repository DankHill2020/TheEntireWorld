from __future__ import annotations

import unittest

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QWidget

from tech_connector.app.main_window_workflows import MainWindowWorkflowsMixin
from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph
from tech_connector.services.workflow_python_graph_sync_service import parse_pipeline_python_to_graph
from tech_connector.ui.pipeline_node_view import PipelineNodeView


class _ManifestView:
    def __init__(self, steps, data_links, flow_links):
        self._steps = steps
        self._data_links = data_links
        self._flow_links = flow_links

    def ordered_step_data(self):
        return self._steps

    def manifest_data_links(self):
        return self._data_links

    def manifest_flow_links(self):
        return self._flow_links


class WorkflowPythonGraphSyncServiceTest(unittest.TestCase):
    def test_real_codegen_output_round_trips_nodes_plugs_and_links(self):
        steps = [
            {
                "symbol": {
                    "name": "create_rig_mapping",
                    "kind": "function",
                    "file_path": "C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py",
                    "params": [{"name": "root_joint", "annotation": "str"}],
                    "outputs": [
                        {"name": "body_joint_map", "annotation": "dict"},
                        {"name": "face_joint_map", "annotation": "dict"},
                    ],
                },
                "literal_values": {},
            },
            {
                "symbol": {
                    "name": "create_rig_from_mapping",
                    "kind": "function",
                    "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                    "params": [
                        {"name": "body_joint_map", "annotation": "dict"},
                        {"name": "face_joint_map", "annotation": "dict"},
                        {"name": "namespace", "annotation": "str"},
                    ],
                    "outputs": [{"name": "result", "annotation": "Any"}],
                },
                "literal_values": {"namespace": "AIStudio_MocapCharacter"},
            },
        ]
        data_links = [
            {"from": "step1.body_joint_map", "to": "step2.body_joint_map", "type": "data"},
            {"from": "step1.face_joint_map", "to": "step2.face_joint_map", "type": "data"},
        ]
        flow_links = [{"from": "step1", "to": "step2", "type": "flow"}]

        code = generate_pipeline_code_from_graph(
            "Maya HIK Mocap To Rig",
            "Create a mocap HIK rig mapping in Maya, then create a project rig from that mapping.",
            steps,
            view=_ManifestView(steps, data_links, flow_links),
        )

        self.assertIn("spec_from_file_location('step1_mod'", code)
        self.assertIn("flow_links = [{'from': 'step1', 'to': 'step2', 'type': 'flow'}]", code)

        parsed = parse_pipeline_python_to_graph(code)

        self.assertTrue(parsed.ok, parsed.diagnostics)
        self.assertEqual("maya_hik_mocap_to_rig", parsed.function_name)
        self.assertEqual(["create_rig_mapping", "create_rig_from_mapping"], [s["symbol"]["name"] for s in parsed.steps])
        self.assertEqual(
            ["body_joint_map", "face_joint_map"],
            [o["name"] for o in parsed.steps[0]["outputs"]],
        )
        self.assertEqual(
            {"namespace": "AIStudio_MocapCharacter"},
            parsed.steps[1]["literal_values"],
        )
        self.assertEqual(
            [
                {"from_step": 1, "from_output": "body_joint_map", "to_step": 2, "to_input": "body_joint_map", "type": "data"},
                {"from_step": 1, "from_output": "face_joint_map", "to_step": 2, "to_input": "face_joint_map", "type": "data"},
            ],
            parsed.data_links,
        )
        self.assertEqual([{"from_step": 1, "to_step": 2, "type": "flow"}], parsed.flow_links)

    def test_dispatcher_codegen_round_trips_real_operation_identity_and_data_links(self):
        steps = [
            {
                "symbol": {
                    "name": "stage_01_motionbuilder_export",
                    "kind": "function",
                    "pipeline_operation": "dcc_operation",
                    "provider_id": "motionbuilder",
                    "operation": "io.export_fbx",
                    "function_path": "motionbuilder_tools.io.export_fbx",
                    "params": [
                        {"name": "filepath", "annotation": "str"},
                        {"name": "settings", "annotation": "dict"},
                    ],
                    "outputs": [{"name": "fbx_path", "annotation": "str"}],
                },
                "literal_values": {
                    "filepath": "C:/tmp/source.fbx",
                    "settings": {"frame_range": [1, 90]},
                },
            },
            {
                "symbol": {
                    "name": "stage_02_blender_import",
                    "kind": "function",
                    "pipeline_operation": "dcc_operation",
                    "provider_id": "blender",
                    "operation": "io.import_fbx",
                    "function_path": "blender_tools.io.import_fbx",
                    "params": [{"name": "filepath", "annotation": "str"}],
                    "outputs": [{"name": "animations", "annotation": "list"}],
                },
                "literal_values": {},
            },
        ]
        code = generate_pipeline_code_from_graph(
            "Dispatcher Round Trip",
            "Export from MotionBuilder and import into Blender.",
            steps,
            view=_ManifestView(
                steps,
                [{"from": "step1.fbx_path", "to": "step2.filepath", "type": "data"}],
                [{"from": "step1", "to": "step2", "type": "flow"}],
            ),
        )

        parsed = parse_pipeline_python_to_graph(code)

        self.assertTrue(parsed.ok, parsed.diagnostics)
        self.assertEqual(
            ["io.export_fbx", "io.import_fbx"],
            [step["symbol"]["name"] for step in parsed.steps],
        )
        self.assertEqual(
            [
                "motionbuilder_tools.io.export_fbx",
                "blender_tools.io.import_fbx",
            ],
            [step["symbol"]["function_path"] for step in parsed.steps],
        )
        self.assertEqual(
            [
                {
                    "from_step": 1,
                    "from_output": "fbx_path",
                    "to_step": 2,
                    "to_input": "filepath",
                    "type": "data",
                }
            ],
            parsed.data_links,
        )

    def test_markdown_fenced_codegen_output_is_still_parseable(self):
        code = """```python
def generated_pipeline(step1_value=None):
    results = {}
    outputs = {}
    return results
```"""

        parsed = parse_pipeline_python_to_graph(code)

        self.assertFalse(parsed.ok)
        self.assertIn("no step calls found", parsed.diagnostics)


class _WorkflowPythonUiHarness(MainWindowWorkflowsMixin, QWidget):
    def __init__(self, symbols):
        super().__init__()
        self.wf_builder_code_edit = QPlainTextEdit(self)
        self.wf_node_view = PipelineNodeView(self)
        self.wf_test_status = QLabel(self)
        self.wf_builder_steps = []
        self.all_discovered_symbols = symbols
        self._cached_discovered_symbols = symbols
        self.events = []

    def _report_workflow_builder_event(self, message: str):
        self.events.append(str(message or ""))
        super()._report_workflow_builder_event(message)

    def append(self, text: str):
        self.events.append(str(text or ""))


class WorkflowPythonGraphSyncUiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_python_tab_sync_rebuilds_pipeline_node_view_from_real_codegen_output(self):
        symbols = [
            {
                "name": "create_rig_mapping",
                "kind": "function",
                "file_path": "C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py",
                "params": [{"name": "root_joint", "annotation": "str"}],
                "outputs": [
                    {"name": "body_joint_map", "annotation": "dict"},
                    {"name": "face_joint_map", "annotation": "dict"},
                ],
            },
            {
                "name": "create_rig_from_mapping",
                "kind": "function",
                "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                "params": [
                    {"name": "body_joint_map", "annotation": "dict"},
                    {"name": "face_joint_map", "annotation": "dict"},
                    {"name": "namespace", "annotation": "str"},
                ],
                "outputs": [{"name": "result", "annotation": "Any"}],
            },
        ]
        steps = [{"symbol": symbols[0], "literal_values": {}}, {"symbol": symbols[1], "literal_values": {"namespace": "AIStudio_MocapCharacter"}}]
        data_links = [
            {"from": "step1.body_joint_map", "to": "step2.body_joint_map", "type": "data"},
            {"from": "step1.face_joint_map", "to": "step2.face_joint_map", "type": "data"},
        ]
        flow_links = [{"from": "step1", "to": "step2", "type": "flow"}]
        code = generate_pipeline_code_from_graph(
            "Maya HIK Mocap To Rig",
            "Create a mocap HIK rig mapping in Maya, then create a project rig from that mapping.",
            steps,
            view=_ManifestView(steps, data_links, flow_links),
        )

        harness = _WorkflowPythonUiHarness(symbols)
        try:
            harness.wf_builder_code_edit.setPlainText(f"```python\n{code}\n```")
            harness.sync_workflow_graph_from_python()

            self.assertEqual(["create_rig_mapping", "create_rig_from_mapping"], [s["symbol"]["name"] for s in harness.wf_builder_steps])
            self.assertEqual({"namespace": "AIStudio_MocapCharacter"}, harness.wf_builder_steps[1]["literal_values"])
            self.assertEqual(2, len(harness.wf_node_view.manifest_data_links()))
            self.assertEqual(1, len(harness.wf_node_view.manifest_flow_links()))
            self.assertNotIn("```", harness.wf_builder_code_edit.toPlainText())
            self.assertTrue(any("Synced Pipeline Python into graph" in event for event in harness.events))
        finally:
            harness.close()

    def test_python_tab_sync_renders_dispatcher_operations_and_connected_plugs(self):
        steps = [
            {
                "symbol": {
                    "name": "stage_01_motionbuilder_export",
                    "kind": "function",
                    "pipeline_operation": "dcc_operation",
                    "provider_id": "motionbuilder",
                    "operation": "io.export_fbx",
                    "function_path": "motionbuilder_tools.io.export_fbx",
                    "params": [
                        {"name": "filepath", "annotation": "str"},
                        {"name": "settings", "annotation": "dict"},
                    ],
                    "outputs": [{"name": "fbx_path", "annotation": "str"}],
                },
                "literal_values": {
                    "filepath": "C:/tmp/source.fbx",
                    "settings": {"frame_range": [1, 90]},
                },
            },
            {
                "symbol": {
                    "name": "stage_02_blender_import",
                    "kind": "function",
                    "pipeline_operation": "dcc_operation",
                    "provider_id": "blender",
                    "operation": "io.import_fbx",
                    "function_path": "blender_tools.io.import_fbx",
                    "params": [{"name": "filepath", "annotation": "str"}],
                    "outputs": [{"name": "animations", "annotation": "list"}],
                },
                "literal_values": {},
            },
        ]
        code = generate_pipeline_code_from_graph(
            "Dispatcher UI Round Trip",
            "Export from MotionBuilder and import into Blender.",
            steps,
            view=_ManifestView(
                steps,
                [{"from": "step1.fbx_path", "to": "step2.filepath", "type": "data"}],
                [{"from": "step1", "to": "step2", "type": "flow"}],
            ),
        )
        harness = _WorkflowPythonUiHarness([])
        try:
            harness.wf_builder_code_edit.setPlainText(code)
            harness.sync_workflow_graph_from_python()

            self.assertEqual(
                ["io.export_fbx", "io.import_fbx"],
                [step["symbol"]["name"] for step in harness.wf_builder_steps],
            )
            self.assertEqual(
                ["motionbuilder_tools.io.export_fbx", "blender_tools.io.import_fbx"],
                [
                    step["symbol"].get("function_path")
                    for step in harness.wf_builder_steps
                ],
            )
            self.assertEqual(1, len(harness.wf_node_view.manifest_data_links()))
            self.assertEqual(1, len(harness.wf_node_view.manifest_flow_links()))
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
