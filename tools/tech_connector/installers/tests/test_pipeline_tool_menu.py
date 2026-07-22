import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QMenu

from tech_connector.ui.pipeline_node_view import PipelineNodeView
from tech_connector.ui.pipeline_attribute_editor import PipelineAttributeEditor


class PipelineToolMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_add_tool_menu_has_global_and_provider_all(self):
        view = PipelineNodeView()
        menu = QMenu(view)
        actions = {}
        view._populate_add_tool_menu(
            menu,
            [
                {"name": "create_rig", "file_path": "C:/tools/maya/rigging.py", "kind": "function"},
                {"name": "get_changed_files", "provider_id": "github", "kind": "function", "public_tool": True},
            ],
            actions,
        )

        top_menus = [action.text() for action in menu.actions() if action.menu()]
        self.assertGreaterEqual(len(top_menus), 3)
        self.assertEqual(top_menus[0], "All")
        self.assertIn("Maya", top_menus)
        self.assertIn("GitHub", top_menus)

        github_menu = next(action.menu() for action in menu.actions() if action.text() == "GitHub")
        github_children = [action.text() for action in github_menu.actions()]
        self.assertEqual(github_children[0], "All")
        self.assertIn("Changes", github_children)
        self.assertNotIn("Rigging", github_children)

    def test_add_tool_menu_caps_large_all_menus(self):
        view = PipelineNodeView()
        menu = QMenu(view)
        actions = {}
        symbols = [
            {"name": f"maya_tool_{idx:03d}", "provider_id": "maya", "kind": "function", "public_tool": True}
            for idx in range(120)
        ]
        view._populate_add_tool_menu(menu, symbols, actions)

        global_all = next(action.menu() for action in menu.actions() if action.text() == "All")
        global_children = [action.text() for action in global_all.actions()]
        self.assertEqual(len([text for text in global_children if "maya_tool_" in text]), 80)
        self.assertTrue(any("Type in the filter" in text for text in global_children))

        maya_menu = next(action.menu() for action in menu.actions() if action.text() == "Maya")
        maya_all = next(action.menu() for action in maya_menu.actions() if action.text() == "All")
        maya_children = [action.text() for action in maya_all.actions()]
        self.assertEqual(len([text for text in maya_children if text.startswith("maya_tool_")]), 50)
        self.assertTrue(any("Type in the filter" in text for text in maya_children))

    def test_context_tool_picker_starts_empty_and_limits_results(self):
        view = PipelineNodeView()
        symbols = [
            {
                "name": f"create_rig_part_{idx:02d}",
                "provider_id": "maya",
                "kind": "function",
                "public_tool": True,
            }
            for idx in range(18)
        ]
        view.set_tool_symbols(symbols)
        root_menu = QMenu(view)
        add_menu = root_menu.addMenu("Add Tool Node")

        filter_edit, result_list = view._build_context_tool_picker(root_menu, add_menu)

        self.assertIsInstance(filter_edit, QLineEdit)
        self.assertIsInstance(result_list, QListWidget)
        self.assertEqual(result_list.count(), 0)

        filter_edit.setText("rig")
        QApplication.processEvents()

        self.assertEqual(result_list.count(), 10)
        self.assertTrue(all("create_rig_part_" in result_list.item(i).text() for i in range(result_list.count())))

    def test_context_tool_picker_down_focuses_first_result(self):
        view = PipelineNodeView()
        view.set_tool_symbols([
            {"name": "create_rig", "provider_id": "maya", "kind": "function", "public_tool": True},
            {"name": "create_rig_mapping", "provider_id": "maya", "kind": "function", "public_tool": True},
        ])
        root_menu = QMenu(view)
        add_menu = root_menu.addMenu("Add Tool Node")
        filter_edit, result_list = view._build_context_tool_picker(root_menu, add_menu)
        filter_edit.setText("create rig")
        picker = filter_edit.parentWidget()
        add_menu.show()
        filter_edit.setFocus()
        QApplication.processEvents()

        QTest.keyClick(filter_edit, Qt.Key_Down)
        QApplication.processEvents()

        self.assertTrue(result_list.hasFocus())
        self.assertEqual(result_list.currentRow(), 0)
        self.assertEqual(picker._inactivity_timer.interval(), 3000)
        picker._inactivity_timer.timeout.emit()
        QApplication.processEvents()
        self.assertTrue(add_menu.isVisible())
        add_menu.close()

    def test_context_tool_filter_prefers_exact_word_combo_function_name(self):
        view = PipelineNodeView()
        view.set_tool_symbols([
            {"name": "create_arm_space_switches", "provider_id": "maya", "kind": "function", "public_tool": True, "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
            {"name": "create_full_rig", "provider_id": "maya", "kind": "function", "public_tool": True, "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
            {"name": "create_rig_from_mapping", "provider_id": "maya", "kind": "function", "public_tool": True, "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
            {"name": "create_rig_mapping", "provider_id": "maya", "kind": "function", "public_tool": True, "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
            {"name": "rig_arm_module", "provider_id": "maya", "kind": "function", "public_tool": True, "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
        ])

        matches = view._filtered_tool_symbols_for_context_menu("create rig mapping", require_query=True, limit=5)

        self.assertGreaterEqual(len(matches), 2)
        self.assertEqual(matches[0]["name"], "create_rig_mapping")
        self.assertEqual(matches[1]["name"], "create_rig_from_mapping")

    def test_graph_interaction_ready_signal_is_available(self):
        view = PipelineNodeView()
        calls = []
        view.graphInteractionRequested.connect(lambda: calls.append("ready"))

        view._request_graph_interaction_ready()

        self.assertEqual(calls, ["ready"])

    def test_context_suggestions_reuse_existing_compatible_nodes(self):
        view = PipelineNodeView()
        mapping_symbol = {
            "name": "create_rig_mapping",
            "provider_id": "maya",
            "kind": "function",
            "params": [],
            "outputs": [
                {"name": "body", "python_type": "dict", "semantic_type": "maya.rig.body_map"},
                {"name": "face", "python_type": "dict", "semantic_type": "maya.rig.face_map"},
            ],
            "public_tool": True,
        }
        view.add_pipeline_step({"symbol": mapping_symbol}, [], mapping_symbol["outputs"])

        target_symbol = {
            "name": "create_rig",
            "provider_id": "maya",
            "kind": "function",
            "params": [
                {"name": "body", "python_type": "dict", "semantic_type": "maya.rig.body_map"},
                {"name": "face", "python_type": "dict", "semantic_type": "maya.rig.face_map"},
            ],
            "outputs": [{"name": "rig", "python_type": "str"}],
            "public_tool": True,
        }

        suggestions = view.context_connection_suggestions(target_symbol)

        self.assertEqual({item["to_input"] for item in suggestions}, {"body", "face"})

        view.add_tool_node_with_existing_context(target_symbol, suggestions)

        self.assertEqual(len([link for link in view.links if link.link_type == "data"]), 2)

    def test_add_and_connect_context_adds_missing_related_functions(self):
        view = PipelineNodeView()
        mapping_symbol = {
            "name": "create_rig_mapping",
            "provider_id": "maya",
            "kind": "function",
            "params": [],
            "outputs": [
                {"name": "body", "python_type": "dict", "semantic_type": "maya.rig.body_map"},
                {"name": "face", "python_type": "dict", "semantic_type": "maya.rig.face_map"},
            ],
            "public_tool": True,
        }
        target_symbol = {
            "name": "create_rig",
            "provider_id": "maya",
            "kind": "function",
            "params": [
                {"name": "body", "python_type": "dict", "semantic_type": "maya.rig.body_map"},
                {"name": "face", "python_type": "dict", "semantic_type": "maya.rig.face_map"},
            ],
            "outputs": [{"name": "rig", "python_type": "str"}],
            "public_tool": True,
            "common_predecessors": ["create_rig_mapping"],
        }
        view.set_tool_symbols([mapping_symbol, target_symbol])

        plan = view.context_addition_plan(target_symbol)
        self.assertEqual([item["name"] for item in plan["available"]], ["create_rig_mapping"])

        view.add_tool_node_with_context(target_symbol, plan)

        names = {node.symbol.get("name") for node in view.nodes.values()}
        self.assertIn("create_rig_mapping", names)
        self.assertIn("create_rig", names)
        self.assertEqual(len([link for link in view.links if link.link_type == "data"]), 2)
        target_node = next(node for node in view.nodes.values() if node.symbol.get("name") == "create_rig")
        self.assertEqual(target_node.step_data["context_addition_details"]["mode"], "Add and Connect Context")
        self.assertIn("create_rig_mapping", target_node.step_data["context_addition_details"]["added"])

    def test_context_addition_exposes_top_usage_patterns_for_selection(self):
        view = PipelineNodeView()
        view.set_tool_symbols([
            {"name": "create_rig_mapping", "provider_id": "maya", "kind": "function", "outputs": [{"name": "body", "python_type": "dict"}], "public_tool": True},
            {"name": "load_rig_mapping", "provider_id": "maya", "kind": "function", "outputs": [{"name": "body", "python_type": "dict"}], "public_tool": True},
            {"name": "parse_rig_mapping_file", "provider_id": "maya", "kind": "function", "outputs": [{"name": "body", "python_type": "dict"}], "public_tool": True},
            {"name": "experimental_mapping", "provider_id": "maya", "kind": "function", "outputs": [{"name": "body", "python_type": "dict"}], "public_tool": True},
        ])
        target = {
            "name": "create_rig",
            "provider_id": "maya",
            "kind": "function",
            "params": [{"name": "body", "python_type": "dict"}],
            "public_tool": True,
            "usage_patterns": [
                {"title": "Generated mapping", "rank": 1, "common_predecessors": ["create_rig_mapping"], "evidence": ["rig_build_workflow.py"]},
                {"title": "Loaded mapping", "rank": 2, "common_predecessors": ["load_rig_mapping"], "evidence": ["mapping_loader_test.py"]},
                {"title": "Parsed mapping file", "rank": 3, "common_predecessors": ["parse_rig_mapping_file"]},
                {"title": "Experimental mapping", "rank": 4, "common_predecessors": ["experimental_mapping"]},
            ],
        }

        patterns = view.usage_patterns_for_symbol(target)
        self.assertEqual([pattern["title"] for pattern in patterns], ["Generated mapping", "Loaded mapping", "Parsed mapping file"])

        loaded_plan = view.context_addition_plan(target, patterns[1])
        self.assertEqual([item["name"] for item in loaded_plan["available"]], ["load_rig_mapping"])

    def test_attribute_editor_renders_context_details_only_when_present(self):
        editor = PipelineAttributeEditor()
        editor.set_node({
            "symbol": {"name": "plain_node", "kind": "function"},
            "params": [],
        })
        plain_rows = editor.form.rowCount()

        editor.set_node({
            "symbol": {"name": "create_rig", "kind": "function"},
            "params": [],
            "context_addition_details": {
                "mode": "Add and Connect Context",
                "pattern": "Generated mapping",
                "added": ["create_rig_mapping"],
                "connections": ["create_rig_mapping.body -> body"],
                "evidence": ["rig_build_workflow.py"],
            },
        })

        self.assertGreater(editor.form.rowCount(), plain_rows)


if __name__ == "__main__":
    unittest.main()
