import inspect
import unittest
from pathlib import Path

from tech_connector.app.main_window_core import MainWindowCoreMixin
from tech_connector.app.main_window_history_assets import MainWindowHistoryAssetsMixin
from tech_connector.services.project_edit_agent_service import _focused_project_edit_source_context


APP_ROOT = Path(__file__).resolve().parent.parent


class TestMainThreadRiskGuards(unittest.TestCase):
    def test_startup_does_not_poll_project_index_sync(self):
        source = inspect.getsource(MainWindowCoreMixin.run_after_first_paint_startup)

        self.assertNotIn("index_sync_timer", source)
        self.assertNotIn("refresh_index_sync_status", source)
        self.assertIn("start_project_index_change_watcher", source)

    def test_project_edit_stage_context_does_not_parse_source_files_live(self):
        source = inspect.getsource(_focused_project_edit_source_context)

        self.assertNotIn("read_text(", source)
        self.assertNotIn("ast.parse", source)
        self.assertNotIn("get_source_segment", source)
        self.assertIn("get_file_snapshot", source)

    def test_index_worker_stdout_is_not_connected_to_chat_append(self):
        source = inspect.getsource(MainWindowHistoryAssetsMixin)

        self.assertNotIn("index_worker.output.connect(lambda s: self.append(s))", source)

    def test_missing_index_startup_notice_is_not_appended_to_chat(self):
        source = inspect.getsource(MainWindowCoreMixin.run_after_first_paint_startup)

        self.assertNotIn("Index v2 not found", source)

    def test_startup_work_is_staggered_after_first_paint(self):
        source = inspect.getsource(MainWindowCoreMixin.run_after_first_paint_startup)

        for direct_call in (
            "self.refresh_history()",
            "self.refresh_snippets_list()",
            "self.load_project_tree_lazy()",
            "self.restore_editor_state()",
            "self.start_async_symbol_indexing()",
        ):
            self.assertNotIn(direct_call, source)
        self.assertIn("_schedule_startup_step", source)

    def test_initial_status_cards_defer_expensive_integration_scan(self):
        source = inspect.getsource(MainWindowCoreMixin.update_initial_status_cards)

        self.assertIn("_startup_defer_expensive_status", source)
        self.assertIn("Checking later", source)

    def test_new_graph_does_not_spin_wait_for_symbol_indexing(self):
        source = (APP_ROOT / "app" / "main_window_workflows.py").read_text(encoding="utf-8")
        start = source.index("    def start_new_workflow_builder")
        end = source.index("    def ensure_pipeline_graph_interaction_ready", start)
        block = source[start:end]

        self.assertNotIn("while self._indexing_thread.is_alive()", block)
        self.assertNotIn("QApplication.processEvents()", block)
        self.assertIn("_ensure_pipeline_symbols_available_nonblocking", block)

    def test_python_to_graph_sync_does_not_scan_symbols_on_ui_path(self):
        source = (APP_ROOT / "app" / "main_window_workflows.py").read_text(encoding="utf-8")
        start = source.index("    def sync_workflow_graph_from_python")
        end = source.index("    def _rebuild_pipeline_graph_from_steps", start)
        block = source[start:end]

        self.assertNotIn("or self.get_all_available_symbols()", block)
        self.assertIn("_ensure_pipeline_symbols_available_nonblocking", block)

    def test_hot_ui_modules_do_not_force_nested_event_processing(self):
        relative_paths = [
            "app/main_window_chat_runtime.py",
            "app/main_window_dcc.py",
            "ui/terminal_dialog.py",
        ]
        for relative_path in relative_paths:
            source = (APP_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(relative_path=relative_path):
                self.assertNotIn("QApplication.processEvents()", source)


if __name__ == "__main__":
    unittest.main()
