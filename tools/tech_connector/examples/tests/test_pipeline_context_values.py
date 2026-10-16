import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.services.pipeline_context_value_service import (
    pipeline_symbol_host,
    read_pipeline_host_selection,
    selection_parameter_spec,
)
from tech_connector.services.pipeline_source_location_service import (
    resolve_pipeline_source_location,
)
from tech_connector.services.pipeline_usage_context_service import (
    infer_project_usage_context,
    infer_project_usage_links,
)
from tech_connector.services.action_planner_service import workflow_plan_from_action_graph
from tech_connector.ui.pipeline_attribute_editor import PipelineAttributeEditor


class _Bridge:
    def __init__(self, result="['Cube', 'Rig']", *, online=True) -> None:
        self.result = result
        self.online = online

    def find_port(self):
        return 1234 if self.online else None

    def get_selection_code(self):
        return "selection"

    def execute(self, _code, timeout=4.0):
        return True, self.result


class _UnrealBridge:
    def health_check(self, timeout=4.0):
        return {
            "connected": True,
            "selected_assets": ["/Game/Props/SM_Chair.SM_Chair"],
            "selected_actors": ["/Game/Maps/Test.Test:PersistentLevel.Chair"],
        }


class _Router:
    blender = _Bridge()
    unreal = _UnrealBridge()


class PipelineContextValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_parameter_is_host_aware(self) -> None:
        symbol = {"host": "blender", "name": "process_meshes"}
        spec = selection_parameter_spec(symbol, "objects", "list[str]")

        self.assertEqual("blender", pipeline_symbol_host(symbol))
        self.assertEqual("Use Blender Selection", spec["label"])
        self.assertTrue(spec["multiple"])
        self.assertIsNone(selection_parameter_spec(symbol, "lod_count", "int"))

    def test_bridge_selection_remains_a_typed_list(self) -> None:
        result = read_pipeline_host_selection(
            _Router(), host="blender", input_name="objects", multiple=True
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(["Cube", "Rig"], result["value"])

    def test_unreal_asset_and_actor_inputs_choose_relevant_selection(self) -> None:
        router = _Router()

        assets = read_pipeline_host_selection(
            router, host="unreal", input_name="selected_assets", multiple=True
        )
        actor = read_pipeline_host_selection(
            router, host="unreal", input_name="actor", multiple=False
        )

        self.assertEqual(["/Game/Props/SM_Chair.SM_Chair"], assets["value"])
        self.assertEqual("/Game/Maps/Test.Test:PersistentLevel.Chair", actor["value"])

    def test_attribute_editor_offers_and_applies_live_selection(self) -> None:
        editor = PipelineAttributeEditor()
        step = {
            "symbol": {"name": "process_meshes", "host": "blender", "kind": "function"},
            "params": [{"name": "objects", "annotation": "list[str]"}],
            "literal_values": {"objects": []},
        }
        emitted = []
        editor.contextValueRequested.connect(emitted.append)
        editor.set_node(step)

        button = editor.context_buttons["objects"]
        self.assertEqual("Use Blender Selection", button.text())
        button.click()
        self.assertEqual("objects", emitted[0]["input"])

        editor.apply_context_value("objects", ["Cube", "Rig"], source="blender_live_selection")
        self.assertEqual(["Cube", "Rig"], step["literal_values"]["objects"])
        self.assertEqual("blender_live_selection", step["literal_value_provenance"]["objects"])
        self.assertIn("BLENDER LIVE SELECTION", editor.param_status_labels["objects"].text())

    def test_attribute_editor_distinguishes_optional_empty_from_missing_required(self) -> None:
        editor = PipelineAttributeEditor()
        step = {
            "symbol": {"name": "export_fbx", "host": "maya", "kind": "function"},
            "params": [
                {"name": "nodes", "annotation": "list[str]", "required": False, "default": []},
                {"name": "export_path", "annotation": "str", "required": True},
            ],
            "literal_values": {"nodes": [], "export_path": ""},
            "literal_value_provenance": {
                "nodes": "operation_default",
                "export_path": "required_user_input",
            },
            "literal_value_details": {
                "nodes": {"source": "operation_default", "missing": False},
                "export_path": {
                    "source": "required_user_input",
                    "missing": True,
                    "question": "Where should the FBX be written?",
                },
            },
        }

        editor.set_node(step)

        self.assertEqual("Optional — automatic/default behavior", editor.param_widgets["nodes"].placeholderText())
        self.assertIn("FUNCTION DEFAULT", editor.param_status_labels["nodes"].text())
        self.assertIn("MISSING REQUIRED INPUT", editor.param_status_labels["export_path"].text())
        self.assertIn("#ff9f1c", editor.param_widgets["export_path"].styleSheet())

    def test_attribute_editor_preserves_typed_manual_values(self) -> None:
        editor = PipelineAttributeEditor()
        step = {
            "symbol": {"name": "typed", "host": "maya"},
            "params": [
                {"name": "start_frame", "annotation": "int", "required": True},
                {"name": "nodes", "annotation": "list[str]", "required": False},
            ],
            "literal_values": {"start_frame": 1, "nodes": []},
        }
        editor.set_node(step)

        editor.param_widgets["start_frame"].setText("24")
        editor.param_widgets["nodes"].setText('["Rig", "Root"]')

        self.assertEqual(24, step["literal_values"]["start_frame"])
        self.assertEqual(["Rig", "Root"], step["literal_values"]["nodes"])

    def test_source_location_resolves_callable_and_generated_operation(self) -> None:
        callable_source = resolve_pipeline_source_location(
            "blender_tools.pipeline_transfer.process_meshes_for_transfer",
            operation="pipeline.process_meshes_for_transfer",
            host="blender",
        )
        generated_source = resolve_pipeline_source_location(
            "ai_studio.blender.generated.blender_export_fbx",
            operation="blender.export_fbx",
            host="blender",
        )

        self.assertTrue(callable_source["file_path"].endswith("blender_tools\\pipeline_transfer.py"))
        self.assertEqual(8, callable_source["start_line"])
        self.assertTrue(generated_source["file_path"].endswith("dcc_operation_service.py"))
        self.assertGreater(generated_source["start_line"], 1)

    def test_real_call_site_binds_previous_output_only_when_argument_uses_it(self) -> None:
        steps = [
            {
                "symbol": {"name": "load_assets"},
                "outputs": [{"name": "assets", "annotation": "list[str]"}],
            },
            {
                "symbol": {"name": "publish_assets"},
                "params": [{"name": "assets", "annotation": "list[str]"}],
            },
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "production_pipeline.py"
            path.write_text(
                "def run():\n"
                "    loaded = load_assets()\n"
                "    publish_assets(assets=loaded['assets'])\n",
                encoding="utf-8",
            )
            links = infer_project_usage_links(steps, [folder])

        self.assertEqual(1, len(links))
        self.assertEqual("assets", links[0]["from_output"])
        self.assertEqual("assets", links[0]["to_input"])
        self.assertEqual("project_call_site", links[0]["evidence"]["kind"])

    def test_call_site_does_not_connect_unrelated_literal_argument(self) -> None:
        steps = [
            {"symbol": {"name": "load_assets"}, "outputs": [{"name": "assets"}]},
            {"symbol": {"name": "publish_assets"}, "params": [{"name": "assets"}]},
        ]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "pipeline.py").write_text(
                "def run():\n"
                "    loaded = load_assets()\n"
                "    publish_assets(assets=['manual'])\n",
                encoding="utf-8",
            )
            links = infer_project_usage_links(steps, [folder])

        self.assertEqual([], links)

    def test_call_site_values_do_not_leak_between_function_scopes(self) -> None:
        steps = [
            {"symbol": {"name": "load_assets"}, "outputs": [{"name": "assets"}]},
            {"symbol": {"name": "publish_assets"}, "params": [{"name": "assets"}]},
        ]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "separate_scopes.py").write_text(
                "def load_step():\n"
                "    loaded = load_assets()\n\n"
                "def publish_step(loaded):\n"
                "    publish_assets(assets=loaded['assets'])\n",
                encoding="utf-8",
            )
            links = infer_project_usage_links(steps, [folder])

        self.assertEqual([], links)

    def test_import_context_disambiguates_same_named_dcc_functions(self) -> None:
        steps = [
            {
                "symbol": {
                    "name": "maya_export",
                    "function_path": "maya_tools.io.export_fbx",
                },
                "outputs": [{"name": "export_path"}],
            },
            {
                "symbol": {
                    "name": "blender_export",
                    "function_path": "blender_tools.io.export_fbx",
                },
                "outputs": [{"name": "export_path"}],
            },
            {
                "symbol": {"name": "publish_file"},
                "params": [{"name": "source_file"}],
            },
        ]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "qualified_pipeline.py").write_text(
                "import blender_tools.io as blender_io\n\n"
                "def run():\n"
                "    exported = blender_io.export_fbx('C:/tmp/asset.fbx')\n"
                "    publish_file(source_file=exported['export_path'])\n",
                encoding="utf-8",
            )
            links = infer_project_usage_links(steps, [folder])

        self.assertEqual(1, len(links))
        self.assertEqual(2, links[0]["from_step"])

    def test_call_site_context_resolves_non_export_selection_argument(self) -> None:
        steps = [{
            "symbol": {"name": "bind_skin", "host": "maya"},
            "params": [{"name": "nodes", "annotation": "list[str]", "required": True}],
        }]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "rig_build.py").write_text(
                "import maya.cmds as cmds\n\n"
                "def run():\n"
                "    selected = cmds.ls(selection=True)\n"
                "    bind_skin(nodes=selected)\n",
                encoding="utf-8",
            )
            context = infer_project_usage_context(steps, [folder])

        self.assertEqual([], context["links"])
        self.assertEqual(1, len(context["values"]))
        value = context["values"][0]["value"]
        self.assertEqual("dcc_input_context_v1", value["$pipeline_context"])
        self.assertEqual("selection", value["context_kind"])
        self.assertEqual("nodes", value["input"])

    def test_call_site_context_uses_only_unambiguous_literal_values(self) -> None:
        steps = [{
            "symbol": {"name": "build_lods", "host": "blender"},
            "params": [{"name": "lod_count", "annotation": "int", "required": True}],
        }]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "asset_build.py")
            path.write_text(
                "def prop():\n"
                "    build_lods(lod_count=3)\n\n"
                "def vehicle():\n"
                "    build_lods(lod_count=3)\n",
                encoding="utf-8",
            )
            context = infer_project_usage_context(steps, [folder])
            self.assertEqual(3, context["values"][0]["value"])
            self.assertEqual(2, context["values"][0]["evidence_count"])

            path.write_text(
                "def prop():\n"
                "    build_lods(lod_count=2)\n\n"
                "def vehicle():\n"
                "    build_lods(lod_count=4)\n",
                encoding="utf-8",
            )
            ambiguous = infer_project_usage_context(steps, [folder])
        self.assertEqual([], ambiguous["values"])

    def test_action_graph_fills_missing_non_export_argument_from_observed_usage(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "rig_build.py").write_text(
                "import maya.cmds as cmds\n\n"
                "def run():\n"
                "    bind_skin(nodes=cmds.ls(selection=True), normalize=True)\n",
                encoding="utf-8",
            )
            graph = {
                "project_root": folder,
                "confidence": 0.9,
                "required_inputs": [{
                    "stage": "bind_step", "argument": "nodes", "host": "maya",
                    "question": "Which nodes should be bound?",
                }],
                "actions": [{
                    "id": "bind_step",
                    "type": "execute_dcc",
                    "args": {
                        "host": "maya",
                        "operation": "rig.bind_skin",
                        "callable": "rig_tools.bind_skin",
                        "params": {},
                        "produces": ["skin_cluster"],
                        "operation_contract": {
                            "required": ["nodes"],
                            "optional": {"normalize": True},
                        },
                    },
                }],
            }
            plan = workflow_plan_from_action_graph(graph)

        self.assertTrue(plan["success"], plan)
        step = plan["steps"][0]
        self.assertEqual(
            "dcc_input_context_v1",
            step["literal_values"]["nodes"]["$pipeline_context"],
        )
        self.assertEqual("project_call_site", step["literal_value_provenance"]["nodes"])
        self.assertEqual([], step["unresolved_inputs"])


if __name__ == "__main__":
    unittest.main()
