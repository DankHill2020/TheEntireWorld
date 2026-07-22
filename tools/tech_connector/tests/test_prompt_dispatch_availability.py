from __future__ import annotations

import unittest

from tech_connector.engine.progress_events import EngineResult
from tech_connector.engine.request_context import RequestContext
from tech_connector.services.prompt_dispatch_service import (
    CAP_DCC_CONNECTION,
    PromptDispatchService,
)


class _NeverCalledDccHandler:
    handler_id = "NeverCalledDccHandler"
    requires = {CAP_DCC_CONNECTION}

    def execute(self, decision, context, emit, activity=None):
        return EngineResult(action="answer", label="DCC", text="executed")


class TestPromptDispatchAvailability(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
