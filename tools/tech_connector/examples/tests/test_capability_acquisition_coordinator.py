from __future__ import annotations

import threading
import time
from types import SimpleNamespace
import unittest

from tech_connector.services.capability_acquisition_coordinator import (
    CapabilityAcquisitionCoordinator,
)


def _plan() -> dict:
    return {
        "original_request": "Build the requested Unreal effect.",
        "steps": [
            {
                "step_id": "research",
                "action": "search",
                "objective": "Research the implementation.",
            },
            {
                "step_id": "implement",
                "action": "modify",
                "objective": "Implement the adapter.",
            },
            {
                "step_id": "validate",
                "action": "validate",
                "objective": "Validate the adapter.",
            },
        ],
    }


def _wait_for_status(coordinator: CapabilityAcquisitionCoordinator, status: str) -> dict:
    deadline = time.time() + 2.0
    while time.time() < deadline:
        snapshot = coordinator.snapshot()
        if snapshot["status"] == status:
            return snapshot
        time.sleep(0.005)
    raise AssertionError(f"Coordinator did not reach {status}: {coordinator.snapshot()}")


class CapabilityAcquisitionCoordinatorTests(unittest.TestCase):
    def test_pause_preserves_checkpoint_and_resume_uses_added_context(self) -> None:
        research_started = threading.Event()
        finish_research = threading.Event()
        calls: list[tuple[str, int]] = []

        def runner(step, job):
            calls.append((step["step_id"], len(job.context_addenda)))
            if step["step_id"] == "research":
                research_started.set()
                self.assertTrue(finish_research.wait(1.0))
            return {"ok": True, "evidence": [step["step_id"]]}

        coordinator = CapabilityAcquisitionCoordinator(_plan(), stage_runner=runner)
        coordinator.start()
        self.assertTrue(research_started.wait(1.0))
        coordinator.add_context("Use a GPU-safe implementation and retain the existing emitter.")
        self.assertEqual(coordinator.snapshot()["status"], "pausing")
        finish_research.set()

        paused = _wait_for_status(coordinator, "paused")
        self.assertEqual([row["step_id"] for row in paused["checkpoints"]], ["research"])
        self.assertEqual(paused["checkpoints"][0]["status"], "completed")
        coordinator.resume()
        completed = coordinator.wait(2.0)

        self.assertEqual(completed["status"], "completed")
        self.assertEqual([name for name, _ in calls], ["research", "implement", "validate"])
        self.assertEqual(calls[1][1], 1)
        remaining = completed["plan"]["steps"][1:]
        self.assertTrue(all(step["context_revision"] == 1 for step in remaining))
        self.assertTrue(all(step["added_context"] for step in remaining))

    def test_cancel_while_paused_never_runs_remaining_mutation(self) -> None:
        research_started = threading.Event()
        finish_research = threading.Event()
        calls: list[str] = []

        def runner(step, _job):
            calls.append(step["step_id"])
            if step["step_id"] == "research":
                research_started.set()
                self.assertTrue(finish_research.wait(1.0))
            return {"ok": True}

        coordinator = CapabilityAcquisitionCoordinator(_plan(), stage_runner=runner)
        coordinator.start()
        self.assertTrue(research_started.wait(1.0))
        coordinator.request_pause()
        finish_research.set()
        _wait_for_status(coordinator, "paused")
        coordinator.cancel()
        cancelled = coordinator.wait(2.0)

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(calls, ["research"])

    def test_default_runner_refuses_to_claim_unimplemented_codegen_succeeded(self) -> None:
        coordinator = CapabilityAcquisitionCoordinator(_plan())
        coordinator.start()
        result = coordinator.wait(2.0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checkpoints"][0]["status"], "completed")
        self.assertEqual(result["checkpoints"][1]["status"], "failed")
        self.assertIn("implementation provider", result["errors"][0])

    def test_external_requirement_pauses_and_retries_only_current_step(self) -> None:
        attempts = []

        def runner(step, _job):
            attempts.append(step["step_id"])
            if len(attempts) == 1:
                return {
                    "ok": False,
                    "pause_required": True,
                    "message": "Restart Unreal, then resume.",
                }
            return {"ok": True, "evidence": ["live callable loaded"]}

        plan = {
            "steps": [
                {"step_id": "validate_dcc_adapter", "action": "validate"},
            ]
        }
        coordinator = CapabilityAcquisitionCoordinator(plan, stage_runner=runner)
        coordinator.start()
        paused = _wait_for_status(coordinator, "paused")
        self.assertEqual(paused["current_step_label"], "Restart Unreal, then resume.")
        self.assertEqual(paused["checkpoints"][0]["status"], "waiting")

        coordinator.resume()
        completed = coordinator.wait(2.0)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(attempts, ["validate_dcc_adapter", "validate_dcc_adapter"])

    def test_ui_result_flow_hands_acquire_then_resume_to_coordinator(self) -> None:
        from tech_connector.app.main_window_chat_runtime import MainWindowChatRuntimeMixin

        class Harness(MainWindowChatRuntimeMixin):
            def __init__(self):
                self.started = None
                self.last_user_prompt = "fallback prompt"
                self._active_capability_coordinator = None

            def _stop_prompt_progress_observer(self, *_args):
                pass

            def _update_active_operation_memory_from_result(self, *_args):
                pass

            def _append_prompt_understanding(self, *_args):
                pass

            def _begin_route_capability_acquisition(self, text, decision):
                self.started = (text, decision)

        route = {
            "operation_mode": "acquire_then_resume",
            "capability_gap_plan": {"steps": []},
            "user_text": "route prompt",
        }
        result = SimpleNamespace(
            action="answer",
            label="Target Discovery",
            text="This answer must not bypass acquisition.",
            prompt="",
            metadata={
                "route_decision": route,
                "prompt_execution_context": {"prompt": "original full prompt"},
            },
        )
        harness = Harness()
        harness.on_intelligence_engine_result(result)

        self.assertIsNotNone(harness.started)
        self.assertEqual(harness.started[0], "original full prompt")
        self.assertEqual(harness.started[1]["operation_mode"], "acquire_then_resume")


if __name__ == "__main__":
    unittest.main()
