import inspect
import unittest

from bridges.unreal.unreal_bridge import UnrealBridge
from services.action_execution_engine import (
    ExecutionContext,
    _handle_execute_unreal_python,
)


class TestUnrealBridgeGraphFocus(unittest.TestCase):
    def test_bridge_uses_ue58_blueprint_graph_editor_for_inspection(self):
        source = inspect.getsource(UnrealBridge.inspect_blueprint_graph)

        self.assertIn("BlueprintEditorLibrary.list_graphs", source)
        self.assertIn("BlueprintGraphEditor.get_graph_editor_by_name", source)
        self.assertIn("BlueprintGraphEditor.list_all_nodes", source)
        self.assertNotIn("KismetEditorUtilities.get_all_graphs", source)

    def test_bridge_focus_helper_reports_resolved_node_position_mode(self):
        source = inspect.getsource(UnrealBridge.focus_blueprint_graph_item)

        self.assertIn("AssetEditorSubsystem", source)
        self.assertIn("BlueprintGraphEditor.get_graph_editor_by_name", source)
        self.assertIn("opened_graph_and_resolved_node_position", source)
        self.assertIn("visual selection is not exposed", source)

    def test_graph_patch_compile_uses_available_blueprint_editor_library(self):
        source = inspect.getsource(UnrealBridge.apply_graph_patch)

        self.assertIn("BlueprintEditorLibrary.compile_blueprint", source)
        self.assertNotIn("KismetEditorUtilities.compile_blueprint", source)

    def test_action_execution_accepts_current_unreal_bridge_dict_response(self):
        class FakeBridge:
            def __init__(self):
                self.calls = []

            def execute_python(self, code, timeout=30.0):
                self.calls.append((code, timeout))
                return {"ok": True, "data": {"selected": []}, "error": ""}

        bridge = FakeBridge()
        result = _handle_execute_unreal_python(
            {"args": {"code": "print('ok')", "timeout": 12.0}},
            ExecutionContext(services={"unreal_bridge": bridge}),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["output"], {"selected": []})
        self.assertEqual(bridge.calls, [("print('ok')", 12.0)])

    def test_action_execution_reports_current_unreal_bridge_dict_error(self):
        class FakeBridge:
            def execute_python(self, code, timeout=30.0):
                return {"ok": False, "data": None, "error": "compile failed"}

        result = _handle_execute_unreal_python(
            {"args": {"code": "bad()"}},
            ExecutionContext(services={"unreal_bridge": FakeBridge()}),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["output"], "compile failed")


if __name__ == "__main__":
    unittest.main()
