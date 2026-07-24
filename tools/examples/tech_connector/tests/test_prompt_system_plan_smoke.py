from __future__ import annotations

import unittest

from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan
from tech_connector.services.prompt.prompt_progress_service import build_prompt_progress_plan
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.prompt.prompt_task_splitter_service import staged_prompt_for_llm


LONG_STAMINA_PROMPT = """In Unreal, I want to add a reusable character stamina system to the current project and connect it to sprinting.

Before making any changes:

1. Inspect the current project and determine whether a stamina, energy, sprint, movement-state, or character-stat system already exists.
2. Identify the most relevant files, classes, functions, Blueprint graphs, pipeline nodes, and project conventions.
3. Explain what you found and distinguish between functionality that can be reused, extended, or created.
4. Determine whether sprint is Python, C++, Blueprint, component, Gameplay Ability, or another system.
5. Identify missing information that would materially affect the implementation.
6. Propose a staged implementation plan before editing anything.

Implementation requirements:

7. Create or extend a reusable stamina system with configurable maximum stamina, sprint drain rate, recovery rate, recovery delay, threshold, depleted cancellation, moving-only drain, UI read access, and events.
8. Integrate the system with the current sprint implementation rather than creating a duplicate sprint path.
9. Preserve existing input, movement, animation, camera, and replication behavior unless explicitly required.
10. If networked, keep authoritative stamina state on the server and replicate only the state needed by clients and UI.
11. If the project already uses Gameplay Ability System, Gameplay Tags, attributes, or a stat component, prefer that architecture.
12. If several valid approaches exist, compare them and choose the one that best matches the current project.

Before editing each asset:

13. Open the exact asset, file, function, or graph for review.
14. State the specific changes about to be made and why that location was selected.
15. Reconfirm that the project state still matches the proposed plan.

During implementation:

16. Make changes in small, undoable stages.
17. Keep graphs and code organized according to existing project conventions.
18. For graph edits, preserve direction, avoid crossed wires, group logic, add comments, and avoid expanding the Event Graph when a function or component is more maintainable.
19. Reuse existing functions, variables, nodes, and project utilities wherever practical.
20. Do not fabricate APIs, functions, assets, or project information.

After implementation:

21. Compile or syntax-check every modified asset or file.
22. Validate sprint threshold, drain, recovery, cancellation, and normal movement.
23. Check that no unrelated files or graph paths were changed.
24. Roll back if validation fails and a valid result cannot be produced.
25. Report what was found, the architecture selected, changes, reuse, compilation, tests, warnings, and final outcome.
"""


def _decision(prompt: str, **overrides: object) -> dict[str, object]:
    decision = classify_prompt_route(prompt).to_dict()
    decision.update(overrides)
    return decision


def _actions(plan: dict[str, object]) -> set[str]:
    actions: set[str] = set()
    for item in plan.get("mixed_operation_sequence") or []:
        if not isinstance(item, dict):
            continue
        actions.update(str(action) for action in item.get("action_keys") or [])
        if item.get("action_type"):
            actions.add(str(item["action_type"]))
    return actions


class TestPromptSystemPlanSmoke(unittest.TestCase):
    def test_quick_maya_readonly_routes_to_dcc_without_approval(self) -> None:
        prompt = "In Maya, list joints in the current scene. Do not modify anything."
        decision = _decision(prompt)
        plan = build_goal_gap_plan(prompt, decision)
        progress = build_prompt_progress_plan(prompt, decision)

        self.assertEqual("maya", decision.get("host"))
        self.assertEqual("dcc_query", decision.get("route"))
        self.assertIn("run_dcc_operation", _actions(plan))
        self.assertFalse(plan.get("approval_gates"))
        self.assertIn("GAP_DISCOVERY", {stage["state"] for stage in progress["stages"]})

    def test_research_only_unreal_prompt_reports_sources_without_ingestion(self) -> None:
        prompt = (
            "In Unreal, research current best practices for motion matching driven climbing "
            "before recommending graph edits. Do not ingest or download anything."
        )
        plan = build_goal_gap_plan(
            prompt,
            _decision(prompt, allow_external_research=True, allow_ingestion=False),
        )
        actions = _actions(plan)

        self.assertIn("web_knowledge_search", actions)
        self.assertNotIn("download_or_ingest_asset", actions)
        self.assertNotIn("github_candidate_review", actions)
        self.assertTrue(plan.get("source_report_requirements"))

    def test_mixed_operation_ingest_allowed_has_approval_gates_and_materialization(self) -> None:
        prompt = (
            "In Blender inspect the character rig, find an online climb animation, "
            "import it into Unreal, retarget it, and validate the result."
        )
        plan = build_goal_gap_plan(
            prompt,
            _decision(prompt, allow_external_research=True, allow_ingestion=True),
        )
        actions = _actions(plan)
        generated = plan.get("generated_callable_candidates") or (
            plan.get("pipeline_materialization_plan") or {}
        ).get("generated_callable_candidates") or []

        self.assertIn("run_dcc_operation", actions)
        self.assertIn("run_python_function", actions)
        self.assertIn("import_unreal_asset", actions)
        self.assertIn("download_or_ingest_asset", actions)
        self.assertIn("github_candidate_review", actions)
        self.assertTrue(plan.get("approval_gates"))
        self.assertTrue(generated)

    def test_mixed_operation_research_only_blocks_download_and_github_ingest(self) -> None:
        prompt = (
            "In Blender inspect the character rig, find an online climb animation, "
            "import it into Unreal, retarget it, and validate the result."
        )
        plan = build_goal_gap_plan(
            prompt,
            _decision(prompt, allow_external_research=True, allow_ingestion=False),
        )
        actions = _actions(plan)

        self.assertIn("web_knowledge_search", actions)
        self.assertNotIn("download_or_ingest_asset", actions)
        self.assertNotIn("github_candidate_review", actions)
        self.assertTrue(plan.get("source_report_requirements"))

    def test_long_unreal_stamina_prompt_is_staged_before_execution(self) -> None:
        staged_prompt, contract = staged_prompt_for_llm(LONG_STAMINA_PROMPT)
        decision = _decision(LONG_STAMINA_PROMPT, allow_external_research=False, allow_ingestion=False)
        plan = build_goal_gap_plan(LONG_STAMINA_PROMPT, decision)
        progress = build_prompt_progress_plan(LONG_STAMINA_PROMPT, decision)

        self.assertIsNotNone(contract)
        self.assertLess(len(staged_prompt), len(LONG_STAMINA_PROMPT))
        self.assertIn("unreal.character_stamina", plan["matched_patterns"])
        self.assertIn("stamina_contract", {node["key"] for node in plan["capability_nodes"]})
        self.assertIn("Unreal Blueprint Graph Expert", {expert["label"] for expert in progress["expert_lenses"]})

    def test_known_external_sounding_capability_reuses_context_instead_of_reingesting(self) -> None:
        prompt = "Use our existing online animation source to import a climb animation into Unreal and validate the import."
        plan = build_goal_gap_plan(
            prompt,
            _decision(
                prompt,
                allow_external_research=True,
                allow_ingestion=True,
                context_resolvers=["online animation source candidate", "animation asset ingest"],
                deterministic_steps=["unreal animation import", "asset validation"],
            ),
        )
        actions = _actions(plan)

        self.assertNotIn("download_or_ingest_asset", actions)
        self.assertNotIn("github_candidate_review", actions)
        self.assertIn("import_unreal_asset", actions)


if __name__ == "__main__":
    unittest.main()
