from __future__ import annotations

import unittest

from services.prompt_route_service import classify_prompt_route


class TestPromptEvalRegressions(unittest.TestCase):
    def test_freeze_patch_prompt_routes_to_target_discovery(self) -> None:
        decision = classify_prompt_route(
            "Troubleshoot why the app freezes during long prompts and patch the likely main-thread issue.",
            project_roots=["C:/depot/tools"],
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("target_discovery", decision.provider)

    def test_find_parser_make_errors_actionable_routes_to_target_discovery(self) -> None:
        decision = classify_prompt_route(
            "Find the parser for XML patches and make errors more actionable.",
            project_roots=["C:/depot/tools"],
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("target_discovery", decision.provider)

    def test_docstring_mutation_routes_to_target_discovery(self) -> None:
        decision = classify_prompt_route(
            "Add missing docstrings and missing params to existing Maya rigging functions, but inspect the project first.",
            project_roots=["C:/depot/tools"],
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("target_discovery", decision.provider)

    def test_unreal_blueprint_inspect_uses_unreal_capability_even_with_compile_status(self) -> None:
        decision = classify_prompt_route(
            "In Unreal, inspect BP_LesterPhoenix and list graphs, variables, components, and compile status. Do not edit.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual("unreal_capability", decision.route)
        self.assertEqual("blueprint.scan", decision.target_identifier)
        self.assertEqual("read_only", decision.mutation_scope)

    def test_pipeline_code_fix_routes_to_target_discovery_not_pipeline_execution(self) -> None:
        prompts = [
            "The pipeline node graph compile button is not warning when required inputs are missing. Find where to fix it and propose the patch.",
            "When I right click in pipeline node view the tool filter is slow. Find the code path and improve the search/filter behavior.",
            "Improve Add and Connect context so it adds related functions and connects them, but uses existing context if related nodes already exist.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_prompt_route(
                    prompt,
                    project_roots=["C:/depot/tools"],
                    active_path="C:/depot/tools/custom_qt/custom_widgets.py",
                )
                self.assertEqual("target_discovery", decision.route)
                self.assertEqual("target_discovery", decision.provider)
                self.assertIn("pipeline_graph", decision.rejected_routes)

    def test_status_index_bug_routes_to_target_discovery_not_broad_search(self) -> None:
        decision = classify_prompt_route(
            "Indexing says Knowledge Ready while still running. Find the likely owning files.",
            project_roots=["C:/depot/tools"],
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("target_discovery", decision.provider)
        self.assertIn("project_search", decision.rejected_routes)

    def test_application_code_planning_routes_to_target_discovery(self) -> None:
        prompts = [
            "When I switch chat history files the old thread disappears. Use the likely owning files and propose a safe repair plan with tests.",
            "Plan how the mobile app should show Jobs and Output logs while reusing the existing desktop job/pipeline systems. Do not create code yet.",
            "Make the code agent behave more like an IDE agent: symbol lookup, repo map, references, usages, tests, structured patching, then validation. Propose the implementation path.",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_prompt_route(
                    prompt,
                    project_roots=["C:/depot/tools"],
                    active_path="C:/depot/tools/custom_qt/custom_widgets.py",
                )
                self.assertEqual("target_discovery", decision.route)
                self.assertEqual("target_discovery", decision.provider)
                self.assertIn("project_search", decision.rejected_routes)


if __name__ == "__main__":
    unittest.main()
