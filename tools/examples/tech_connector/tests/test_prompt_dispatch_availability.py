from __future__ import annotations

import unittest

from tech_connector.engine.progress_events import EngineResult
from tech_connector.engine.request_context import RequestContext
from tech_connector.services.prompt.prompt_dispatch_service import (
    CAP_DCC_CONNECTION,
    PromptDispatchService,
)
from tech_connector.services.prompt.artifact_contract_service import restricts_live_mutation


class _NeverCalledDccHandler:
    handler_id = "NeverCalledDccHandler"
    requires = {CAP_DCC_CONNECTION}

    def execute(self, decision, context, emit, activity=None):
        return EngineResult(action="answer", label="DCC", text="executed")


class _NeverCalledProjectSearchHandler:
    handler_id = "NeverCalledProjectSearchHandler"
    requires = set()

    def execute(self, decision, context, emit, activity=None):
        raise AssertionError("Broad project search should not own a mutating target-discovery graph")


class _RecordingTargetDiscoveryHandler:
    handler_id = "RecordingTargetDiscoveryHandler"
    requires = set()

    def __init__(self) -> None:
        self.seen_decision = None

    def execute(self, decision, context, emit, activity=None):
        self.seen_decision = dict(decision)
        return EngineResult(
            action="send_raw",
            label="Target Discovery",
            text="target discovery owned the mutating graph",
            metadata={"result_type": "target_edit"},
        )


class TestPromptDispatchAvailability(unittest.TestCase):
    def test_disposable_workspace_prohibits_live_mutation(self) -> None:
        self.assertTrue(
            restricts_live_mutation(
                "Generate the implementation, do not modify live files; "
                "materialize only in a disposable workspace."
            )
        )
        self.assertFalse(
            restricts_live_mutation(
                "Generate the implementation and apply it to the selected project files."
            )
        )

    def test_disconnected_unreal_status_blocks_direct_execution_with_warning(self) -> None:
        service = PromptDispatchService(handlers={"test.dcc": _NeverCalledDccHandler()})
        context = RequestContext(
            text="In Unreal compile BP_PlayerCharacter",
            extras={
                "capability_availability": {
                    "hosts": {
                        "unreal": {
                            "connected": False,
                            "status": "off",
                            "light": "red",
                            "detail": "Bridge not detected",
                        }
                    }
                }
            },
        )

        result = service.dispatch(
            {
                "route": "dcc_execute",
                "execution_route": "test.dcc",
                "host": "unreal",
                "execution_environment": "unreal",
                "requires_dcc_connection": True,
                "requires_confirmation": False,
                "reasons": [],
            },
            context,
            lambda event: None,
        )

        self.assertEqual("clarify", result.action)
        self.assertIn("Warning: Unreal is currently disconnected", result.text)
        self.assertIn("dcc_connection", result.metadata["missing_capabilities"])

    def test_target_discovery_keeps_mutating_multistage_graph_even_when_first_goal_is_read_only(self) -> None:
        target_handler = _RecordingTargetDiscoveryHandler()
        service = PromptDispatchService(
            handlers={
                "engine.target_discovery": target_handler,
                "engine.project_search": _NeverCalledProjectSearchHandler(),
            }
        )
        context = RequestContext(text="In Unreal build a replicated inventory system with UI and save/load")

        result = service.dispatch(
            {
                "route": "target_discovery",
                "provider": "target_discovery",
                "execution_route": "engine.target_discovery",
                "request_understanding": {
                    "read_only_requested": False,
                    "mutation_requested": True,
                },
                "task_graph": {
                    "goals": [
                        {
                            "task_id": "inspect_gameplay_architecture",
                            "goal_type": "inspect",
                            "read_only": True,
                        },
                        {
                            "task_id": "implement_feature_changes",
                            "goal_type": "modify",
                            "read_only": False,
                            "depends_on": ["inspect_gameplay_architecture"],
                        },
                    ],
                    "mutation_goal_ids": ["implement_feature_changes"],
                },
                "reasons": [],
            },
            context,
            lambda event: None,
        )

        self.assertEqual("send_raw", result.action)
        self.assertEqual("target_discovery", target_handler.seen_decision["route"])
        self.assertEqual("engine.target_discovery", target_handler.seen_decision["execution_route"])

    def test_target_discovery_keeps_disposable_generated_code_artifact(self) -> None:
        target_handler = _RecordingTargetDiscoveryHandler()
        service = PromptDispatchService(
            handlers={
                "engine.target_discovery": target_handler,
                "engine.project_search": _NeverCalledProjectSearchHandler(),
            }
        )
        context = RequestContext(text="Generate a complete subsystem, but only validate it in a temp workspace")

        result = service.dispatch(
            {
                "route": "target_discovery",
                "provider": "target_discovery",
                "execution_route": "engine.target_discovery",
                "intent_category": "function_backed_artifact_generation",
                "request_understanding": {
                    "primary_intent": "function_backed_artifact_generation",
                    "requested_artifact": "working_generated_code",
                    "read_only_requested": True,
                    "mutation_requested": False,
                },
                "planning_result": {
                    "intent_category": "function_backed_artifact_generation",
                    "deliverable": "working_generated_code",
                    "planning_mode": "function_backed_artifact_generation",
                },
                "task_graph": {
                    "goals": [
                        {
                            "task_id": "discover_existing_patterns",
                            "goal_type": "inspect",
                            "read_only": True,
                        }
                    ],
                    "mutation_goal_ids": [],
                },
                "reasons": [],
            },
            context,
            lambda event: None,
        )

        self.assertEqual("send_raw", result.action)
        self.assertEqual("target_discovery", target_handler.seen_decision["route"])
        self.assertEqual("engine.target_discovery", target_handler.seen_decision["execution_route"])


if __name__ == "__main__":
    unittest.main()
