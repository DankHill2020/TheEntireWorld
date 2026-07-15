import inspect
import unittest
from pathlib import Path

from app.main_window_core import MainWindowCoreMixin
from app.main_window_history_assets import MainWindowHistoryAssetsMixin


APP_ROOT = Path(__file__).resolve().parent.parent


class _RunningWorker:
    def isRunning(self):
        return True


class _IndexStatusWindow(MainWindowCoreMixin):
    def __init__(self):
        self.index_worker = _RunningWorker()
        self.card_updates = []
        self.context_updates = 0

    def set_card(self, *args):
        self.card_updates.append(args)

    def update_unified_prompt_context_label(self):
        self.context_updates += 1


class TestMainThreadRiskGuards(unittest.TestCase):
    def test_index_sync_does_not_mark_ready_while_index_worker_runs(self):
        window = _IndexStatusWindow()

        window.on_index_sync_status_ready({"stale": False})

        self.assertEqual([], window.card_updates)
        self.assertEqual(1, window.context_updates)

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
