import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tech_connector.ui.pipeline_node_view import PipelineGraphLink, PipelineNodeView


def _step(name: str):
    symbol = {
        "name": name,
        "kind": "function",
        "params": [{"name": "value", "annotation": "str", "required": False}],
        "outputs": [{"name": "result", "annotation": "str"}],
    }
    return {
        "symbol": symbol,
        "params": list(symbol["params"]),
        "outputs": list(symbol["outputs"]),
        "literal_values": {},
    }


class PipelineUiPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bulk_node_load_does_not_emit_per_node_or_fill_undo(self):
        view = PipelineNodeView()
        graph_events = []
        order_events = []
        view.graphChanged.connect(lambda: graph_events.append(True))
        view.orderChanged.connect(order_events.append)

        for index in range(60):
            step = _step(f"tool_{index}")
            view.add_pipeline_step(
                step,
                step["params"],
                step["outputs"],
                emit_signals=False,
                push_undo=False,
            )

        self.assertEqual([], graph_events)
        self.assertEqual([], order_events)
        self.assertEqual([], view._undo_stack)
        self.assertEqual(60, len(view.nodes))

    def test_node_drag_coalesces_geometry_and_graph_notifications(self):
        view = PipelineNodeView()
        first = _step("first")
        second = _step("second")
        view.add_pipeline_step(first, first["params"], first["outputs"])
        view.add_pipeline_step(second, second["params"], second["outputs"])
        view.links.append(
            PipelineGraphLink(
                first["graph_step_id"],
                "result",
                second["graph_step_id"],
                "value",
                "data",
            )
        )
        view.refresh_links(rebuild=True)
        graph_events = []
        view.graphChanged.connect(lambda: graph_events.append(True))

        item = view.node_items[first["graph_step_id"]]
        for offset in range(40):
            item.setPos(900 + offset, 90)

        self.assertLessEqual(len(graph_events), 1)
        self.assertTrue(view._geometry_refresh_timer.isActive())
        QTest.qWait(180)
        self.assertLessEqual(len(graph_events), 1)

    def test_large_tool_index_builds_in_event_loop_chunks(self):
        view = PipelineNodeView()
        symbols = [
            {
                "name": f"tool_{index}",
                "kind": "function",
                "provider_id": "project",
                "public_tool": True,
            }
            for index in range(1200)
        ]
        view.set_tool_symbols(symbols)

        self.assertTrue(view._tool_symbol_search_cache_build_scheduled)
        self.assertEqual([], view._tool_symbol_search_cache)
        QTest.qWait(80)
        self.assertFalse(view._tool_symbol_search_cache_build_scheduled)
        # Public utility nodes are intentionally included alongside project tools.
        self.assertGreaterEqual(len(view._tool_symbol_search_cache), 1200)
        indexed_names = {
            row["symbol"].get("name") for row in view._tool_symbol_search_cache
        }
        self.assertIn("tool_1199", indexed_names)

    def test_incomplete_node_outline_is_orange_and_updates_when_ready(self):
        view = PipelineNodeView()
        step = _step("requires_context")
        step["params"][0]["required"] = True
        step["symbol"]["params"][0]["required"] = True
        view.add_pipeline_step(step, step["params"], step["outputs"])
        view.refresh_links(rebuild=True)

        item = view.node_items[step["graph_step_id"]]
        self.assertEqual("#ff9f1c", item.pen().color().name())
        self.assertIn("needs a value", item.toolTip())

        step.setdefault("literal_values", {})["value"] = "ready"
        view.refresh_node_literals(step, emit_signal=False)
        self.assertEqual("#5bd000", item.pen().color().name())
        self.assertEqual("Pipeline data flow satisfied.", item.toolTip())


if __name__ == "__main__":
    unittest.main()
