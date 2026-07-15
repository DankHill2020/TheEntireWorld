from __future__ import annotations

import unittest

from app.main_window_chat_runtime import MainWindowChatRuntimeMixin
from engine.request_context import RequestContext
from engine.request_engine import RequestEngine
from services.capability_service import expand_terms
from services.prompt_route_service import classify_prompt_route
from services.project_search_service import _function_location_terms, _should_clarify_function_location


class TestChatProjectSearchFastPath(unittest.TestCase):
    def test_chat_runtime_exposes_engine_start_method(self) -> None:
        self.assertTrue(hasattr(MainWindowChatRuntimeMixin, "start_intelligence_engine_request"))

    def test_maya_rig_function_question_uses_project_search_provider(self) -> None:
        prompt = "what function do i have for creating a rig in maya"
        decision = classify_prompt_route(prompt)
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        progress: list[str] = []
        result = RequestEngine(progress=lambda event: progress.append(event.display_text())).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("engine.project_search", decision.execution_route)
        self.assertEqual("answer", result.action)
        self.assertEqual("Project Index", result.label)
        self.assertIn("create_rig_from_mapping", result.text)
        self.assertLess(result.text.find("create_rig_from_mapping"), result.text.find("create_full_rig") if "create_full_rig" in result.text else len(result.text))
        self.assertIn("Project index answer ready", "\n".join(progress))

    def test_project_wide_maya_rig_search_does_not_get_stuck_on_active_file(self) -> None:
        prompt = "What functions create a rig in maya?"
        decision = classify_prompt_route(prompt, active_path="C:/depot/tools/custom_qt/custom_widgets.py")
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/custom_qt/custom_widgets.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("create_rig_from_mapping", result.text)
        self.assertIn("maya_tools", result.text.replace("\\", "/"))

    def test_project_wide_rig_file_search_does_not_get_stuck_on_active_file(self) -> None:
        prompt = "what files have functions to create rig"
        decision = classify_prompt_route(prompt, active_path="C:/depot/tools/custom_qt/custom_widgets.py")
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/custom_qt/custom_widgets.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("create_full_rig", result.text)
        self.assertIn("maya_tools", result.text.replace("\\", "/"))

    def test_broad_project_search_answers_fast_and_marks_background_deepening(self) -> None:
        prompt = "Find every class that opens a QFileDialog."
        decision = classify_prompt_route(prompt, active_path="C:/depot/tools/custom_qt/custom_widgets.py")
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/custom_qt/custom_widgets.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("QFileDialog call matches", result.text)
        self.assertTrue(result.metadata.get("deep_search_candidate"))
        self.assertEqual(prompt, result.metadata.get("deep_search_query"))

    def test_connection_status_prompts_do_not_compile_action_graphs(self) -> None:
        prompts = [
            "Testing connection",
            "am i connected ?",
            "connection status",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_prompt_route(prompt)
                self.assertNotEqual("action_graph", decision.route)
                self.assertNotEqual("pipeline_graph", decision.route)
                self.assertNotEqual("engine.action_graph", decision.execution_route)

    def test_connection_status_prompt_answers_from_cached_rows(self) -> None:
        prompt = "am i connected ?"
        decision = classify_prompt_route(prompt)
        context = RequestContext(
            text=prompt,
            project_roots=["C:/depot/tools"],
            extras={
                "prompt_route_decision": decision.to_dict(),
                "connected_application_status": [
                    {"name": "Maya", "connected": True, "mode": "bridge:7001"},
                    {"name": "Unreal Engine", "connected": False, "mode": "bridge not detected"},
                ],
            },
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("connection_status", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("Maya: LIVE", result.text)
        self.assertIn("Unreal Engine: SETUP", result.text)

    def test_read_only_project_investigation_does_not_route_to_unreal_execution(self) -> None:
        prompt = "inspect the project for sprint and stamina systems; do not edit anything"
        decision = classify_prompt_route(prompt, active_path="C:/depot/tools/custom_qt/custom_widgets.py")

        self.assertEqual("project_search", decision.route)
        self.assertEqual("engine.project_search", decision.execution_route)
        self.assertNotEqual("unreal_capability", decision.route)
        self.assertNotEqual("unreal.capability_pipeline", decision.execution_route)

    def test_file_function_question_lists_active_file_functions_without_raw_index_evidence(self) -> None:
        prompt = "in create_rig.py what functions do i have?"
        decision = classify_prompt_route(prompt)
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("Functions in", result.text)
        self.assertIn("create_full_rig", result.text)
        self.assertNotIn("Indexed Evidence", result.text)
        self.assertNotIn("Exact import matches", result.text)
        self.assertNotIn("Project retrieval plan", result.text)
        self.assertNotIn(".venv", result.text)

    def test_this_file_function_question_uses_active_file_ast(self) -> None:
        prompt = "what functions are in this file?"
        decision = classify_prompt_route(prompt, active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py")
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
            project_roots=["C:/depot/tools"],
            extras={"prompt_route_decision": decision.to_dict()},
        )
        result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("project_search", decision.route)
        self.assertEqual("answer", result.action)
        self.assertIn("Functions in", result.text)
        self.assertIn("create_full_rig", result.text)
        self.assertNotIn("Indexed Evidence", result.text)

    def test_simple_project_fact_route_uses_terse_progress(self) -> None:
        decision = classify_prompt_route(
            "what functions are in this file?",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )
        progress = decision.visible_progress
        self.assertEqual("project_search", decision.route)
        self.assertEqual("none_deterministic", decision.model_tier)
        self.assertLessEqual(len(progress.get("stages") or []), 2)
        self.assertFalse(decision.reasoning_pipeline)

    def test_function_fact_prompts_route_to_project_search(self) -> None:
        prompts = [
            "what functions create a control",
            "what functions do i have to create a rig",
            "what arguments does create_full_rig take?",
            "find callers of query_ollama_text",
            "show functions in maya_tools Rigging create_rig.py",
        ]

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_prompt_route(prompt)
                self.assertEqual("project_search", decision.route)
                self.assertEqual("engine.project_search", decision.execution_route)

    def test_control_synonyms_expand_only_in_matching_context(self) -> None:
        rig_terms = _function_location_terms(
            "what functions create a control",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )
        self.assertIn("ctrl", rig_terms)

        vcs_terms = expand_terms(["source", "control"], context="git source control status")
        self.assertIn("vcs", vcs_terms)
        self.assertNotIn("ctrl", vcs_terms)

        ui_terms = expand_terms(["control"], context="Qt widget control in a dialog")
        self.assertIn("widget", ui_terms)
        self.assertNotIn("ctrl", ui_terms)

    def test_function_search_ignores_output_format_instructions(self) -> None:
        terms = _function_location_terms(
            "What functions do I have for creating a rig in Maya? Return function names and file paths only; do not edit anything.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        self.assertIn("create", terms)
        self.assertIn("rig", terms)
        self.assertNotIn("names", terms)
        self.assertNotIn("paths", terms)
        self.assertNotIn("only", terms)

    def test_maya_rig_function_search_returns_real_rig_builders(self) -> None:
        from services.project_search_service import build_deterministic_project_search_answer

        answer = build_deterministic_project_search_answer(
            "What functions do I have for creating a rig in Maya? Return function names and file paths only; do not edit anything.",
            "C:/depot/tools/maya_tools/Rigging/create_rig.py",
            "",
        )

        self.assertIn("create_rig_from_mapping", answer)
        self.assertLess(answer.find("create_rig_from_mapping"), answer.find("create_full_rig") if "create_full_rig" in answer else len(answer))
        self.assertNotIn("find_references_from_namespace", answer)

    def test_maya_hik_mapping_rig_build_question_prefers_mapping_builder(self) -> None:
        from services.project_search_service import _function_location_rows

        prompt = "Find the function I should use to build a Maya rig from an existing HIK mapping. Give me function names and full file paths only; don't edit."
        terms = _function_location_terms(prompt, active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py")
        rows = _function_location_rows(
            terms,
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
            question=prompt,
            limit=5,
        )

        self.assertEqual(rows[0]["name"], "create_rig_from_mapping")
        self.assertNotEqual(rows[0]["name"], "_build_rigging_tab")
        self.assertNotIn("should_build_rig_from", terms)

    def test_function_search_clarifies_only_when_ranked_matches_are_close(self) -> None:
        close_rows = [{"match_score": 100, "name": "a"}, {"match_score": 92, "name": "b"}]
        self.assertTrue(_should_clarify_function_location("what function handles this", close_rows))

        clear_rows = [{"match_score": 455, "name": "create_full_rig"}, {"match_score": 420, "name": "remove_full_rig"}]
        self.assertFalse(_should_clarify_function_location("what function creates a rig", clear_rows))

        explicit_rows = [{"match_score": 100, "name": "a"}, {"match_score": 92, "name": "b"}]
        self.assertFalse(_should_clarify_function_location("what does create_full_rig do", explicit_rows))

    def test_edit_and_planning_prompts_do_not_fall_into_heavy_project_health(self) -> None:
        docstring_decision = classify_prompt_route("Add missing docstrings to functions in the current file")
        self.assertNotEqual("project_health", docstring_decision.route)
        self.assertNotEqual("engine.project_health", docstring_decision.execution_route)

        planning_decision = classify_prompt_route("where should I add a new Unreal graph rollback validator?")
        self.assertEqual("project_search", planning_decision.route)
        self.assertEqual("engine.project_search", planning_decision.execution_route)

        ui_decision = classify_prompt_route("Find an existing Maya function and create a UI for it")
        self.assertEqual("target_discovery", ui_decision.route)
        self.assertTrue(ui_decision.requires_confirmation)

        ui_plan_decision = classify_prompt_route(
            "Find an existing project function that performs a meaningful Maya operation and propose a Maya UI wrapper around it. Do not edit anything yet.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )
        self.assertEqual("target_discovery", ui_plan_decision.route)
        self.assertEqual("read_only_ui_wrapper_planning", ui_plan_decision.intent_category)
        self.assertEqual("read_only", ui_plan_decision.mutation_scope)
        self.assertFalse(ui_plan_decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
