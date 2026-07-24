import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel

from tech_connector.ui.detachable_tabs import DetachableTabWidget


class DetachableTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rejects_incompatible_tab_type(self):
        feature_tabs = DetachableTabWidget(tab_type="feature")
        editor_tabs = DetachableTabWidget(tab_type="editor_file")
        widget = QLabel("Chat")
        feature_tabs.addTab(widget, "Chat")

        payload = feature_tabs.drag_payload_for_index(0)

        self.assertFalse(editor_tabs.accept_tab_drop(payload))
        self.assertEqual(feature_tabs.count(), 1)
        self.assertEqual(editor_tabs.count(), 0)

    def test_moves_widget_between_compatible_containers(self):
        first = DetachableTabWidget(tab_type="feature")
        second = DetachableTabWidget(tab_type="feature")
        widget = QLabel("Chat")
        first.addTab(widget, "Chat")

        payload = first.drag_payload_for_index(0)
        self.assertTrue(second.accept_tab_drop(payload))

        self.assertEqual(first.count(), 0)
        self.assertEqual(second.count(), 1)
        self.assertIs(second.widget(0), widget)

    def test_detached_window_closes_when_final_tab_moves_away(self):
        root = DetachableTabWidget(tab_type="pipeline")
        graph = QLabel("Graph")
        root.addTab(graph, "Node Graph")

        root.detach_tab_by_index(0)
        self.assertEqual(root.count(), 0)
        self.assertEqual(len(root._detached_windows), 1)

        detached = root._detached_windows[0]
        payload = detached.tabs.drag_payload_for_index(0)
        self.assertTrue(root.accept_tab_drop(payload))

        self.assertEqual(root.count(), 1)
        self.assertIs(root.widget(0), graph)
        self.assertEqual(detached.tabs.count(), 0)

    def test_dragged_outside_helper_detaches_tab(self):
        root = DetachableTabWidget(tab_type="feature")
        chat = QLabel("Chat")
        root.addTab(chat, "Chat")
        root.resize(300, 120)
        root.show()
        self.app.processEvents()

        outside = root.mapToGlobal(QPoint(root.width() + 120, root.height() + 120))
        self.assertTrue(root.detach_index_if_dragged_outside(0, outside))

        self.assertEqual(root.count(), 0)
        self.assertEqual(len(root._detached_windows), 1)
        self.assertIs(root._detached_windows[0].tabs.widget(0), chat)


if __name__ == "__main__":
    unittest.main()
