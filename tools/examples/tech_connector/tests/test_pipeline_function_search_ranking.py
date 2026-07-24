from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from tech_connector.app.main_window_workflows import MainWindowWorkflowsMixin


class _PipelineSearchHarness(MainWindowWorkflowsMixin, QWidget):
    def __init__(self, symbols):
        super().__init__()
        self.all_discovered_symbols = symbols
        self.wf_build_func_box = QComboBox(self)
        self._pipeline_symbol_filter_cache = {}

    def _current_pipeline_dcc_filter(self) -> str:
        return "all"


class PipelineFunctionSearchRankingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_create_rig_mapping_is_top_and_search_is_capped_to_five(self):
        symbols = [
            {
                "name": "create_rig_arm_space_switches",
                "kind": "function",
                "file_path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                "description": "Create rig controls from a mapping.",
            },
            {
                "name": "create_rig_mapping",
                "kind": "function",
                "file_path": "C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py",
            },
            *[
                {
                    "name": f"create_rig_mapping_variant_{index}",
                    "kind": "function",
                    "file_path": f"C:/depot/tools/maya_tools/Rigging/test_{index}.py",
                }
                for index in range(8)
            ],
        ]
        harness = _PipelineSearchHarness(symbols)
        try:
            harness.filter_discovered_symbols("create rig mapping")

            self.assertLessEqual(harness.wf_build_func_box.count(), 5)
            self.assertEqual("create_rig_mapping", harness.wf_build_func_box.itemData(0)["name"])
        finally:
            harness.close()


if __name__ == "__main__":
    unittest.main()
