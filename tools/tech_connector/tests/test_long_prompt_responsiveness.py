import os
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout, QWidget

from tech_connector.app.main_window_chat_runtime import MainWindowChatRuntimeMixin
from tech_connector.app.main_window_core import MainWindowCoreMixin
from tech_connector.services.prompt_route_service import classify_prompt_route
from tech_connector.services.prompt_task_splitter_service import build_staged_prompt_contract, staged_prompt_for_llm
from tech_connector.ui.growing_prompt_edit import GrowingPromptEdit


LONG_STAMINA_PROMPT = (
    "I want to add a reusable character stamina system to the current project and connect it to sprinting.\n\n"
    + "\n".join(
        f"{idx}. Inspect, preserve, validate, rollback, and report reusable stamina sprint graph behavior."
        for idx in range(1, 140)
    )
)


class _NoRegistryWindow(MainWindowChatRuntimeMixin):
    def __init__(self):
        self.settings = {"capability_gate_max_sync_chars": 240}
        self.logged = []

    @property
    def _capability_registry(self):
        raise AssertionError("long prompts must not touch the synchronous capability registry")

    def _log_ui_diagnostic(self, event, **details):
        self.logged.append((event, details))


class _NoSyncCapabilityGateWindow(_NoRegistryWindow):
    def __init__(self):
        super().__init__()
        self.settings = {"capability_gate_max_sync_chars": 240}


class _MetadataWindow(MainWindowCoreMixin):
    def __init__(self, decision):
        self.settings = {"show_reasoning_summary": False, "show_activity_details": False}
        self._last_prompt_route_decision = decision.to_dict()

    def selected_mcphost_model(self):
        return "ollama:llama3:latest"

    def model_display_parts(self, model):
        return ("Ollama Local", str(model).replace("ollama:", ""), model)

    def source_mode_label(self):
        return "Always local"

    def dcc_connection_label(self, _task_role):
        return "none"


class _TerminalQueueWindow(MainWindowChatRuntimeMixin):
    def __init__(self):
        self.settings = {"terminal_output_process_chunk_chars": 10}
        self._raw_terminal_buffer_by_role = {"main": "abcdefghijklmnopqrstuvwxyz"}
        self._raw_terminal_flush_pending = {"main"}
        self.processed = []
        self.logged = []

    def _process_main_terminal_output(self, raw):
        self.processed.append(raw)

    def _process_role_terminal_output(self, role, raw):
        self.processed.append((role, raw))

    def _ui_diagnostic_enabled(self):
        return True

    def _log_ui_diagnostic(self, event, **details):
        self.logged.append((event, details))


class LongPromptResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_growing_prompt_eventually_sizes_to_long_contents(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        tabs = QTabWidget(host)
        page = QWidget()
        page.resize(900, 600)
        tabs.addTab(page, "Chat")
        layout.addWidget(tabs)
        host.workspace_tabs = tabs

        edit = GrowingPromptEdit(host)
        layout.addWidget(edit)
        host.show()
        edit.setText(LONG_STAMINA_PROMPT)
        self.app.processEvents()
        QTest.qWait(70)
        self.app.processEvents()

        self.assertGreater(edit.height(), 36)
        self.assertLessEqual(edit.height(), 200)

    def test_capability_gate_skips_long_prompts_without_registry_lookup(self):
        window = _NoRegistryWindow()
        window.settings["capability_gate_sync_enabled"] = True

        self.assertFalse(window._check_capability_gaps(LONG_STAMINA_PROMPT))
        self.assertEqual(window.logged[0][0], "capability_gate_skipped_long_prompt")

    def test_capability_gate_skips_medium_prompts_without_registry_lookup(self):
        window = _NoRegistryWindow()
        window.settings["capability_gate_sync_enabled"] = True
        prompt = (
            "In Unreal, inspect the current project for an existing sprint or stamina system and report what you find. "
            "Do not edit anything yet. Identify relevant Blueprint, C++, component, Gameplay Ability, or input assets. "
            "Use cached or quick project context if Project Intelligence is slow."
        )

        self.assertFalse(window._check_capability_gaps(prompt))
        self.assertEqual(window.logged[0][0], "capability_gate_skipped_long_prompt")

    def test_capability_gate_disabled_by_default_before_registry_lookup(self):
        window = _NoSyncCapabilityGateWindow()

        self.assertFalse(window._check_capability_gaps("what functions do i have to create rig"))

        self.assertEqual(window.logged[0][0], "capability_gate_skipped_disabled")

    def test_route_metadata_is_compacted_for_long_prompts(self):
        decision = classify_prompt_route(LONG_STAMINA_PROMPT, project_roots=["C:/depot/tools"])
        raw_size = len(str(decision.to_dict()))
        self.assertLess(raw_size, 10000)
        self.assertFalse(decision.senior_prompt_analysis)
        self.assertIn("Deferred rich route analysis", " ".join(decision.reasons))
        self.assertEqual(decision.route, "chat")
        self.assertEqual(decision.provider, "llm")
        self.assertEqual(decision.intent_category, "staged_long_contract")
        self.assertIn("pipeline_graph", decision.rejected_routes)

        window = _MetadataWindow(decision)
        metadata = window.build_request_metadata(
            LONG_STAMINA_PROMPT,
            LONG_STAMINA_PROMPT,
            SimpleNamespace(task_role="unreal", reason="test"),
            "main",
            "ollama:llama3:latest",
        )

        self.assertLess(len(str(metadata)), 5000)
        self.assertNotIn("domain_experts", str(metadata))
        self.assertLessEqual(len(metadata["prompt_route_decision"]["required_context"]), 8)

    def test_terminal_output_flush_processes_bounded_chunks(self):
        window = _TerminalQueueWindow()

        window._flush_terminal_output("main")

        self.assertEqual(window.processed, ["abcdefghij"])
        self.assertEqual(window._raw_terminal_buffer_by_role["main"], "klmnopqrstuvwxyz")
        self.assertEqual(window.logged[0][0], "terminal_output_processed")
        self.assertEqual(window.logged[0][1]["chunk_chars"], 10)

    def test_long_prompt_staging_preserves_compact_chunk_map(self):
        staged_text, contract = staged_prompt_for_llm(LONG_STAMINA_PROMPT, threshold=600)

        self.assertIsNotNone(contract)
        self.assertIn("Synthesis rule:", staged_text)
        self.assertIn("Compact source chunks:", staged_text)
        self.assertIn("Do not treat chunks as separate unrelated requests.", staged_text)
        self.assertGreaterEqual(len(contract.chunks), 2)
        self.assertLess(len(staged_text), len(LONG_STAMINA_PROMPT))

    def test_staged_contract_retains_user_goal(self):
        contract = build_staged_prompt_contract(LONG_STAMINA_PROMPT)

        self.assertIn("reusable character stamina system", contract.user_goal)
        self.assertTrue(contract.active_stage.instructions)


if __name__ == "__main__":
    unittest.main()
