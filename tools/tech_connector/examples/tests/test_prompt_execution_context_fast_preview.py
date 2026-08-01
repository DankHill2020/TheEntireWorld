from __future__ import annotations

from pathlib import Path
from time import perf_counter
import unittest
from unittest.mock import patch

from tech_connector.services.prompt.prompt_execution_context_service import (
    _model_json,
    build_prompt_execution_context,
    plan_prompt_with_context,
)
from tech_connector.services.llm_router_service import LLMCloudProviderError
from tech_connector.services.prompt.prompt_intent_service import understand_prompt_request_deterministic
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


TOOLS_ROOT = str(Path(__file__).resolve().parents[3])


REAL_GAME_DEV_PROMPTS = [
    (
        "unreal",
        "In Unreal add a reusable stamina system for sprinting, dodging, and melee combos. "
        "It should drain while sprinting, block dodge when empty, regenerate after a delay, "
        "update the HUD, and compile the touched Blueprints.",
    ),
    (
        "unreal",
        "Make a crawling locomotion system in ABP Combat for Manny: prone idle, crawl forward/back/strafe, "
        "transitions from crouch, input gating, and no direct execution if Unreal is disconnected.",
    ),
    (
        "",
        "Plan a mantle and ledge climb feature across Character BP, AnimBP, and input mapping. "
        "Inspect existing movement code first, list dependencies, propose functions/assets to touch, and do not edit yet.",
    ),
    (
        "maya",
        "In Maya export selected Manny joints and animation to C:/tmp/manny_climb.fbx, then in Unreal "
        "import it into /Game/Characters/Manny/Animations and validate skeleton compatibility.",
    ),
    (
        "unreal",
        "Implement a networked pickup and inventory flow in Unreal: overlap detection, authority check, "
        "replicated inventory array, UI notification, save/load hook, tests or validation plan.",
    ),
    (
        "unreal",
        "Add enemy AI patrol and perception behavior: patrol spline, sight/hearing stimulus, chase state, "
        "lose target timeout, blackboard keys, behavior tree tasks, and debug draw validation.",
    ),
    (
        "maya",
        "Find existing Maya rigging functions and create a PySide tool to bind a mesh to selected joints, "
        "add/remove influences, validate selection, and add focused tests.",
    ),
    (
        "unreal",
        "Review the Unreal graph mutation planner for performance risks, explain dependencies and likely hotspots, "
        "include line numbers, but do not edit files.",
    ),
]


class TestPromptExecutionContextFastPreview(unittest.TestCase):
    def test_real_game_dev_fast_preview_batch_does_not_timeout(self) -> None:
        started = perf_counter()
        rows = []
        for host, prompt in REAL_GAME_DEV_PROMPTS:
            context = build_prompt_execution_context(
                prompt,
                host_hint=host,
                decision_facts={"project_roots": [TOOLS_ROOT]},
                fast_preview=True,
            )
            decision = classify_prompt_route(
                prompt,
                project_roots=[TOOLS_ROOT],
                execution_context=context.to_dict(),
            )
            goals = (
                (decision.task_graph or {}).get("ordered_goals")
                or (decision.task_graph or {}).get("goals")
                or []
            )
            audit = context.planning_result.get("deterministic_authority") or {}
            rows.append(
                (
                    decision.route,
                    len(goals),
                    context.planning_result.get("planning_mode"),
                    audit,
                )
            )

        elapsed_ms = (perf_counter() - started) * 1000.0
        self.assertLess(elapsed_ms, 5000.0)
        self.assertTrue(all(mode == "fast_preview" for _, _, mode, _ in rows))
        self.assertTrue(all(goal_count > 0 for _, goal_count, _, _ in rows))
        self.assertTrue(all(audit.get("authoritative") for _, _, _, audit in rows), rows)
        self.assertTrue(all(not audit.get("requires_deeper_planning") for _, _, _, audit in rows), rows)
        self.assertTrue(all((audit.get("confidence") or 0.0) >= 0.86 for _, _, _, audit in rows), rows)
        self.assertTrue(all(audit.get("checks") for _, _, _, audit in rows), rows)

    def test_fast_preview_marks_vague_mutation_as_not_authoritative(self) -> None:
        context = build_prompt_execution_context(
            "fix it",
            decision_facts={"project_roots": [TOOLS_ROOT]},
            fast_preview=True,
        )
        audit = context.planning_result.get("deterministic_authority") or {}

        self.assertFalse(audit.get("authoritative"), audit)
        self.assertTrue(audit.get("requires_deeper_planning"), audit)
        self.assertIn("mutation_scope_gated", audit.get("failed_checks") or [])

    def test_unreal_slash_phrases_do_not_become_exact_file_scope(self) -> None:
        prompts = [
            "In Unreal implement sprint stamina, dodge block, pickup overlap, HUD updates, and save/load persists inventory.",
            "In ABP Combat add Manny crawl states for prone idle and crawl forward/back/strafe states.",
        ]
        for prompt in prompts:
            understanding = understand_prompt_request_deterministic(prompt, host="unreal")
            self.assertEqual("", understanding.target_container_path, understanding.to_dict())
            self.assertEqual("", understanding.target_container_query, understanding.to_dict())

    def test_function_backed_tool_prompt_preserves_full_request_not_primitive_dcc_query(self) -> None:
        prompt = (
            "In Maya, build a production rigging utility: find existing skinning and HIK functions, "
            "create a PySide tool that binds the selected mesh to selected joints, adds/removes influences, "
            "validates selection and namespaces, logs every operation, and includes focused tests."
        )

        context = build_prompt_execution_context(
            prompt,
            host_hint="maya",
            decision_facts={"project_roots": [TOOLS_ROOT]},
            fast_preview=True,
        )

        self.assertEqual(prompt, context.planning_result.get("interpreted_request"))
        self.assertIn("PySide tool", context.planning_result.get("behavior") or "")
        self.assertNotEqual("scene.ls", context.planning_result.get("behavior"))

    def test_complex_unreal_implementation_skips_planning_model_before_indexed_search(self) -> None:
        prompt = (
            "In Unreal implement a networked pickup and inventory flow: overlap detection, "
            "server authority, client request RPC, replicated inventory array, OnRep HUD notification, "
            "save/load hook, rollback journal, and two-client PIE validation."
        )

        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=AssertionError("planning model should not be required"),
        ):
            context = build_prompt_execution_context(
                prompt,
                host_hint="unreal",
                decision_facts={"project_roots": [TOOLS_ROOT]},
            )

        self.assertEqual(
            "deterministic_complex_implementation",
            context.planning_result.get("planning_mode"),
        )
        self.assertEqual("target_discovery", context.planning_result.get("primary_route"))
        self.assertTrue(context.planning_result.get("mutation_requested"))

    def test_failed_context_replan_preserves_last_usable_model_plan(self) -> None:
        first_plan = {
            "interpreted_request": "Build a rig UI around create_full_rig.",
            "primary_route": "target_discovery",
            "intent_category": "project_code_edit",
            "goal_type": "generate",
            "deliverable": "code",
            "behavior": "Create and validate a working rig UI.",
            "scope": "project",
            "target": "rig_ui.py",
            "mutation_requested": True,
            "execution_requested": False,
            "steps": [
                {
                    "step_id": "inspect",
                    "action": "inspect",
                    "objective": "Inspect create_full_rig and its arguments.",
                    "depends_on": [],
                    "success_condition": "The callable contract is known.",
                }
            ],
            "function_calls": [],
            "unknowns": [],
            "context_requests": [
                {
                    "kind": "file_source",
                    "query": "create_full_rig",
                    "target": "maya_tools/Rigging/create_rig.py",
                    "reason": "Inspect the backend callable.",
                }
            ],
            "clarification_question": "",
            "confidence": 0.9,
            "reasons": [],
        }
        with (
            patch(
                "tech_connector.services.prompt.prompt_execution_context_service._cached_planning_model_json",
                side_effect=[first_plan, {}],
            ),
            patch(
                "tech_connector.services.prompt.prompt_execution_context_service.expand_prompt_context_candidates",
                return_value=[{"kind": "file_source", "value": "source"}],
            ),
            patch(
                "tech_connector.services.prompt.prompt_execution_context_service._action_catalog",
                return_value=[],
            ),
        ):
            result, _candidates = plan_prompt_with_context(
                "Build a rig UI around create_full_rig.",
                {
                    "primary_intent": "project_code_edit",
                    "primary_route": "target_discovery",
                    "goal_type": "generate",
                    "mutation_requested": True,
                    "confidence": 0.9,
                },
                {"goal": "Build a rig UI", "mutation_requested": True},
                {"interpreted_problem": "Build a rig UI"},
                [],
                {},
                {},
            )

        self.assertEqual("plan", result.get("model_role"))
        self.assertEqual("accepted", result.get("planning_candidate_status"))
        self.assertEqual("Inspect create_full_rig and its arguments.", result["steps"][0]["objective"])

    def test_locked_cloud_planning_failure_is_not_normalized_to_fallback(self) -> None:
        with patch(
            "tech_connector.services.llm_router_service.generate_llm_response",
            side_effect=LLMCloudProviderError("gemini quota exhausted"),
        ):
            with self.assertRaises(LLMCloudProviderError):
                _model_json(
                    "Return a plan.",
                    {
                        "raw_prompt": "Plan a rig UI.",
                        "settings": {},
                        "semantic_hypothesis": {"primary_route": "target_discovery"},
                        "context_candidates": [],
                    },
                )


if __name__ == "__main__":
    unittest.main()
