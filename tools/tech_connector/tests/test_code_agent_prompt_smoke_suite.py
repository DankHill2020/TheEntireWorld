from __future__ import annotations

import unittest

from tech_connector.app.main_window_editor import detect_editor_intent
from tech_connector.services.project_edit_agent_service import (
    build_project_edit_agent_request,
    preview_project_edit_agent_response,
    render_code_agent_adaptive_plan,
)


MAYA_UI_PROMPT = """Find an existing project function that performs a meaningful Maya operation with multiple arguments.
Create a Maya UI that exposes that function to the user.
Before editing, search for callers, related utilities, Maya window patterns, shared UI framework, argument names, types, defaults, required values, return data, and Maya context.
Reuse existing UI classes, styling, logging, validation, path controls, selection helpers, and Maya integration functions where available.
The UI must open directly inside Maya, prevent duplicate windows, use typed controls, validate required fields, call the original function, show results/errors, and include Run and Reset or Refresh.
Add it in the appropriate Maya UI/tools folder and add it to the existing Maya tools menu if one exists.
Verify imports, compile files, add tests where possible, and clearly separate static verification from Maya runtime verification."""


DOCSTRING_PROMPT = """Add missing docstrings and missing param entries to existing Maya rigging functions.
Inspect the project first, choose the real target functions from the index, preserve signatures, and compile the modified file."""


QT_UI_PROMPT = """Find the existing Tech Connector chat controls and improve the send button status reporting.
Reuse existing chat/report/status helpers, avoid adding a new UI framework, patch exact files, and verify with focused tests."""


UNREAL_PLAN_PROMPT = """Inspect existing Unreal graph editing support and add a safer planning report for graph mutation prompts.
Reuse the existing semantic graph and capability graph services, avoid changing graph execution, and add tests for the planning output."""


PROJECT_EDIT_ROUTING_CASES = [
    MAYA_UI_PROMPT,
    DOCSTRING_PROMPT,
    QT_UI_PROMPT,
    UNREAL_PLAN_PROMPT,
    "Find where rig creation lives and add a small Maya launcher UI for the best existing function.",
    "I need a button in Maya for the rig builder. Find the function and wire it up properly.",
    "Can you inspect the existing Maya tools and make a window for exporting animation?",
    "Add a testable wrapper around the current skeleton mapping operation, using the project UI patterns.",
    "Find the function that validates a character and expose it in a Maya-safe dialog.",
    "Make it easier for beginners to run the selected-rig validation tool from Maya.",
    "Where should a UI for create_full_rig go, and then add it using existing conventions?",
    "Please improve the current chat response copy buttons by finding the right existing widget first.",
    "Inspect existing status reporting and add better progress messages for long code-agent operations.",
    "Find the current prompt router code and add a safer fallback for missing model names.",
    "Audit existing indexing startup code and fix the UI freeze risk without changing unrelated behavior.",
    "Find our project tree widget and make its arrows more readable against the Tech Connector theme.",
    "Add missing unit tests around duplicate Maya window handling after finding the UI helper code.",
    "Create a reusable helper for argument-to-widget mapping if one does not already exist.",
    "Find any existing argument schema utilities and use them to build typed controls for a Maya tool.",
    "Make a docstring tool that fills missing params, but first inspect existing docstring code.",
    "I want the tool to infer the right file and add validation before running generated code.",
    "Please locate the menu registration system and add this new Maya window to it.",
    "Find existing logging/report UI and use it for a new Maya operation panel.",
    "Update existing bridge status lights to report Maya connection failures more clearly.",
    "Inspect the current Unreal graph planner and add a visible rollback note section.",
    "Find the Blueprint graph operation planning code and improve the validation report.",
    "I want a safer way to create pipeline nodes from prompts; find existing graph code and patch it.",
    "Make the node search menu faster by inspecting existing filtering/cache code before editing.",
    "Improve persistent memory expertise selection by finding the domain expert service first.",
    "Find the mobile pairing server code and add clearer job-progress reporting.",
    "Add tests for app startup window visibility after finding the startup/show code path.",
    "Find the code that opens chat history and fix switching chats so previous messages return.",
    "Refactor the project sidebar setup area to be collapsible using current UI classes.",
    "Find the existing Help About dialog and add the website plus ownership text.",
    "Add a smoke test for @ asset mention resolution after finding the mention parser.",
    "Make index progress less noisy by locating the background index service and patching output filtering.",
    "Find the existing code change report formatter and make multi-file reports clearer.",
    "Create a Maya UI for current selection processing, but reuse an existing selected-node helper if present.",
    "Find a real function with boolean and numeric args and build the right controls for it.",
    "I don't know where this belongs, but add a clean UI for a Maya rigging operation and test it.",
]


CODE_AGENT_INTENT_CASES = [
    ("Add a helper function to this file that normalizes Maya node names.", "generate"),
    ("In this file, replace the current timeout message with a clearer one.", "edit"),
    ("Fix the bug in this open file where the status label never updates.", "edit"),
    ("Explain what this class does and where it is used.", "project_search"),
    ("What functions do I have for creating a rig?", "project_search"),
    ("What functions do I have to create a rig?", "project_search"),
    ("Which files mention QApplication?", "project_search"),
    ("Where is the Maya bridge status light implemented?", "project_search"),
    ("List callers of build_project_edit_agent_request.", "project_search"),
    ("Find every class that opens a QFileDialog.", "project_search"),
    ("Show me unused-looking files related to old workflow UI.", "project_search"),
    ("Troubleshoot why the app freezes during long prompts and patch the likely main-thread issue.", "project_edit"),
    ("The send button appears to do nothing on long messages; inspect the routing path and fix it.", "project_edit"),
    ("When I switch chat history files the old thread disappears; find the state bug and repair it.", "project_edit"),
    ("The Maya status light is wrong; inspect connected-app status code and fix the display.", "project_edit"),
    ("Indexing says ready while still running; find that progress bug and fix it.", "project_edit"),
    ("Make a new reusable code-generation validation helper if the project does not already have one.", "project_edit"),
    ("Create tests for prompt chunking after finding the long prompt service.", "project_edit"),
    ("Add a small current-file utility below the selected function.", "generate"),
    ("Refactor this file's duplicate button setup code into a helper.", "edit"),
    ("Why does this function return None sometimes?", "lookup"),
    ("Summarize the active file and explain the main classes.", "lookup"),
    ("Find the right place for a new mobile job log endpoint and implement it.", "project_edit"),
    ("I need a pipeline job troubleshooting report; locate the job service and add one.", "project_edit"),
    ("Search for the function that registers Maya menus and add a new item.", "project_edit"),
    ("Can you build a UI from an existing Maya function but do not duplicate the function?", "project_edit"),
    ("Diagnose the failed code-edit preview and add a fallback message.", "project_edit"),
    ("Find the parser for XML patches and make errors more actionable.", "project_edit"),
    ("Update the current function to include an optional verbose flag.", "edit"),
    ("Write a new class in this file for a collapsible sidebar section.", "generate"),
    ("Where should I add a new Unreal graph rollback validator?", "project_search"),
    ("Where should I add a new Unreal graph rollback validator? Then add it.", "project_edit"),
    ("Find the existing docstring utilities, then create missing-param support.", "project_edit"),
    ("Improve this exact selected code block without touching other files.", "edit"),
    ("Create a new pytest for this open helper.", "generate"),
    ("Find all places that call query_ollama_text and update code-edit calls to prefer coder models.", "project_edit"),
    ("The model tag 404s when qwen3:14b is selected; inspect resolver code and fix fallback.", "project_edit"),
    ("I want a fresh function in the current module that formats validation output.", "generate"),
    ("What does detect_editor_intent consider a project edit?", "project_search"),
    ("Which service should own adaptive code-agent planning?", "project_search"),
    ("Pick the best existing service for adaptive code-agent planning and wire it into project edits.", "project_edit"),
]


class TestCodeAgentPromptSmokeSuite(unittest.TestCase):
    def _assert_project_edit_prompt_is_adaptive(self, prompt: str, active_path: str) -> None:
        self.assertEqual("project_edit", detect_editor_intent(prompt))

        plan = build_project_edit_agent_request(prompt, active_path=active_path, limit=8)
        adaptive = render_code_agent_adaptive_plan(plan.adaptive_plan)

        self.assertTrue(plan.discovery_context)
        self.assertIn("adaptive_planning", [stage["key"] for stage in plan.stages])
        self.assertIn("Adaptive code agent execution plan:", plan.model_prompt)
        self.assertIn("Success contract:", plan.model_prompt)
        self.assertIn("Required output sections:", plan.model_prompt)
        self.assertIn("Fallback policy:", plan.model_prompt)
        self.assertIn("Reuse existing project functions, classes, services, and helpers", plan.model_prompt)
        self.assertIn("<modify_file path=", plan.model_prompt)
        self.assertIn("Adaptive stages to follow:", adaptive)

    def test_project_edit_routing_handles_40_goal_phrasings(self) -> None:
        self.assertEqual(40, len(PROJECT_EDIT_ROUTING_CASES))
        for prompt in PROJECT_EDIT_ROUTING_CASES:
            with self.subTest(prompt=prompt[:90]):
                self.assertEqual("project_edit", detect_editor_intent(prompt))

    def test_code_agent_intent_matrix_covers_create_search_edit_and_troubleshooting(self) -> None:
        self.assertEqual(41, len(CODE_AGENT_INTENT_CASES))
        for prompt, expected in CODE_AGENT_INTENT_CASES:
            with self.subTest(expected=expected, prompt=prompt[:90]):
                self.assertEqual(expected, detect_editor_intent(prompt))

    def test_maya_ui_objective_routes_to_adaptive_project_edit(self) -> None:
        self._assert_project_edit_prompt_is_adaptive(
            MAYA_UI_PROMPT,
            "C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

    def test_docstring_objective_routes_to_adaptive_project_edit(self) -> None:
        self._assert_project_edit_prompt_is_adaptive(
            DOCSTRING_PROMPT,
            "C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

    def test_qt_ui_objective_routes_to_adaptive_project_edit(self) -> None:
        self._assert_project_edit_prompt_is_adaptive(
            QT_UI_PROMPT,
            "C:/depot/tools/tech_connector/app/main_window_chat_runtime.py",
        )

    def test_unreal_planning_objective_routes_to_adaptive_project_edit(self) -> None:
        self._assert_project_edit_prompt_is_adaptive(
            UNREAL_PLAN_PROMPT,
            "C:/depot/tools/tech_connector/services/unreal/semantic_graph_service.py",
        )

    def test_preview_rejects_unpatchable_model_response(self) -> None:
        result = preview_project_edit_agent_response(
            "I would create a UI, but here is only prose and no patch.",
            project_root="C:/depot/tools",
        )

        self.assertFalse(result.ok)
        self.assertEqual("preview_failed", result.status)
        self.assertIn("No <modify_file> or <create_file> changes found.", result.errors)


if __name__ == "__main__":
    unittest.main()
