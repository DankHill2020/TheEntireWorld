import unittest
from unittest.mock import patch

from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.application_command_service import ApplicationCommandService
from tech_connector.services.desktop_window_service import render_desktop_window_inspection


WINDOW_RESULT = {
    "ok": True,
    "supported": True,
    "filters": {"process_name": "UnrealEditor", "title_query": ""},
    "foreground_handle": 10,
    "window_count": 2,
    "modal_candidate_count": 1,
    "windows": [
        {
            "handle": 10,
            "pid": 55,
            "process_name": "UnrealEditor",
            "title": "IA_Sprint",
            "bounds": {"left": 100, "top": 50, "width": 1200, "height": 700},
            "foreground": True,
            "enabled": True,
            "owner_handle": 0,
            "owned_window": False,
            "owner_in_result": False,
            "modal_candidate": False,
        },
        {
            "handle": 11,
            "pid": 55,
            "process_name": "UnrealEditor",
            "title": "Blueprint Asset Compilation Errors",
            "bounds": {"left": 300, "top": 200, "width": 700, "height": 300},
            "foreground": False,
            "enabled": True,
            "owner_handle": 10,
            "owned_window": True,
            "owner_in_result": True,
            "modal_candidate": True,
        },
    ],
    "errors": [],
    "mutated_desktop": False,
}


class TestDesktopWindowService(unittest.TestCase):
    def test_renderer_reports_window_state_and_modal_candidates(self):
        text = render_desktop_window_inspection(WINDOW_RESULT)

        self.assertIn("IA_Sprint", text)
        self.assertIn("Blueprint Asset Compilation Errors", text)
        self.assertIn("modal candidate", text)

    def test_application_command_exposes_typed_read_only_inspection(self):
        with patch(
            "tech_connector.services.desktop_window_service.inspect_desktop_windows",
            return_value=WINDOW_RESULT,
        ) as inspect:
            result = ApplicationCommandService().execute(
                "inspect_windows", {"process_name": "UnrealEditor"}
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["mutated_desktop"])
        inspect.assert_called_once_with(
            process_name="UnrealEditor",
            title_query="",
            include_untitled=False,
            limit=100,
        )

    def test_prompt_fast_path_inspects_unreal_windows_without_a_model(self):
        with patch(
            "tech_connector.services.desktop_window_service.inspect_desktop_windows",
            return_value=WINDOW_RESULT,
        ) as inspect, patch(
            "tech_connector.services.prompt.prompt_execution_context_service.build_prompt_execution_context",
            side_effect=AssertionError("window inspection must not invoke semantic planning"),
        ):
            result = RequestEngine().process(
                RequestContext("Inspect the open Unreal windows and show any modal dialogs")
            )

        self.assertEqual("answer", result.action)
        self.assertEqual("desktop_window_inspection", result.metadata["result_type"])
        self.assertEqual("read_only", result.metadata["route_decision"]["mutation_scope"])
        inspect.assert_called_once_with(
            process_name="UnrealEditor",
            title_query="",
            include_untitled=False,
            limit=100,
        )


if __name__ == "__main__":
    unittest.main()
