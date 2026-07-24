from __future__ import annotations

import unittest
from unittest.mock import Mock
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from tech_connector.services.gameplay_proof_contract_service import (
    ProofClaim,
    build_gameplay_proof_contract,
)
from tech_connector.services.gameplay_proof_execution_service import (
    FeatureCompletionStatus,
    GameplayProofExecutionService,
)
from tech_connector.services.unreal.evidence_driven_feature_synthesis_service import (
    derive_prompt_requirement_contract,
)
from tech_connector.services.unreal.feature_planning_service import (
    _generic_unreal_feature_plan,
    _local_operation_status,
    render_unreal_feature_plan,
)
from tech_connector.services.unreal.behavior_capability_decomposition_service import (
    decompose_prompt_behaviors,
    synthesize_novel_behavior_contract,
    validate_model_behavior_synthesis,
)
from tech_connector.services.unreal.prompt_reasoning_benchmark_service import (
    evaluate_unreal_prompt_plan,
)
from tech_connector.bridges.unreal.unreal_blueprint_inspection import (
    _asset_search_tokens,
    _focus_search_terms,
    _normalized_search_terms,
    _one_edit_apart,
)
from tech_connector.services.unreal.technique_currency_service import (
    build_technique_currency_review,
    compare_technique_candidates,
)
from tech_connector.services.unreal.evidence_driven_feature_synthesis_service import (
    REQUIRED_VERIFICATION_GATES,
    load_verified_feature_recipes,
    promote_verified_feature_recipe,
)


CLIMB_PROMPT = (
    "i would like you to create an ABP specifically for climbing, we should make it work "
    "on any wall simply by walking up to it and holding up or W for more than 1 second"
)


class TestGameplayProofEnforcement(unittest.TestCase):
    def test_novel_behavior_is_semantically_synthesized_not_name_matched(self) -> None:
        prompt = "Build a gravity-folding puzzle where rotating a glyph makes loose objects fall toward the matching wall."
        response = {
            "summary": "The glyph changes the room's active gravity frame.",
            "clause_coverage": [{
                "source_clause": prompt,
                "classification": "behavior",
                "covered_by": ["glyph_gravity_selection", "directional_object_fall"],
            }],
            "behaviors": [
                {
                    "id": "glyph_gravity_selection",
                    "title": "Select gravity direction from glyph rotation",
                    "source_clauses": [prompt],
                    "trigger": "the player rotates the glyph",
                    "observations": ["glyph orientation", "matching wall normal"],
                    "guards": ["glyph orientation maps to one valid room wall"],
                    "states": ["AwaitingGlyph", "GravityTransition", "GravityStable"],
                    "transitions": [
                        {"from": "AwaitingGlyph", "event": "glyph rotates", "guards": ["mapping valid"], "to": "GravityTransition"},
                        {"from": "GravityTransition", "event": "gravity vector applied", "guards": ["world updated"], "to": "GravityStable"},
                    ],
                    "outcomes": ["active gravity points toward the matching wall"],
                    "cancellation": ["invalid mapping retains previous gravity"],
                    "failure_paths": ["missing wall mapping does not change gravity"],
                    "animation_roles": [],
                    "proof_scenarios": ["loose physics objects accelerate toward the selected wall"],
                    "operations": ["puzzle.resolve_glyph_orientation", "physics.set_directional_gravity"],
                }
            ],
            "proposed_atomic_operations": ["puzzle.resolve_glyph_orientation", "physics.set_directional_gravity"],
            "ambiguities": [],
            "assumptions": [],
        }
        packet = synthesize_novel_behavior_contract(
            prompt,
            model_query=lambda _system, _user: json.dumps(response),
        )
        decomposition = decompose_prompt_behaviors(prompt, model_synthesis=packet)

        self.assertEqual("validated", packet["status"])
        self.assertIn("generated.glyph_gravity_selection", decomposition["primitive_keys"])
        self.assertIn("physics.set_directional_gravity", decomposition["operations"])
        self.assertIn("GravityTransition", decomposition["states"])
        self.assertFalse(decomposition["knowledge_required"])

    def test_model_behavior_synthesis_rejects_missing_prompt_coverage(self) -> None:
        result = validate_model_behavior_synthesis(
            "Build a puzzle where mirrors redirect sound and doors open only on the correct rhythm.",
            {
                "clause_coverage": [],
                "behaviors": [{"id": "mirror", "title": "Mirror", "states": ["Idle"], "transitions": [], "outcomes": [], "failure_paths": []}],
            },
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["uncovered_clauses"])

    def test_behavior_composition_changes_with_requested_wall_transfer(self) -> None:
        basic = decompose_prompt_behaviors(CLIMB_PROMPT)
        transfer = decompose_prompt_behaviors(
            CLIMB_PROMPT + " and let the player jump from wall to wall"
        )

        self.assertNotIn("movement.surface_to_surface_transfer", basic["primitive_keys"])
        self.assertIn("movement.surface_to_surface_transfer", transfer["primitive_keys"])
        self.assertEqual(["climb_loop"], basic["animation_roles"])
        self.assertIn("climb_wall_jump", transfer["animation_roles"])
        self.assertIn("TransferAirborne", transfer["states"])
        self.assertTrue(
            any(
                row["from"] == "TransferReacquiring" and row["to"] == "EnteringSurface"
                for row in transfer["transitions"]
            )
        )

    def test_detailed_plan_is_composed_from_prompt_and_live_context(self) -> None:
        plan = _generic_unreal_feature_plan(
            CLIMB_PROMPT + " and let the player jump from wall to wall",
            {
                "sufficient": True,
                "engine_version": "5.8",
                "target_asset": "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix",
                "target_skeleton": "/Game/Characters/Mannequins/Meshes/SK_Mannequin",
                "blueprint": {
                    "parent_class": "/Game/ThirdPerson/BP_ThirdPersonCharacter",
                    "components": [{"skeletal_mesh_asset": "/Game/Characters/Mannequins/Meshes/SKM_Manny_NoGeo"}],
                },
                "animation_blueprints": [{"asset_path": "/Game/Variant_Combat/Anims/ABP_Manny_Combat"}],
                "assets": {
                    "related_animations": [{"path": "/Game/Test/A_Climb", "class": "AnimSequence"}],
                },
                "semantic_visibility": {"sight": "complete", "gaps": []},
            },
        )
        detailed = plan["detailed_implementation_plan"]

        self.assertEqual("Wall Climbing", detailed["feature"])
        self.assertEqual(
            "/Game/Variant_Combat/Anims/ABP_Manny_Combat",
            detailed["project_context"]["current_animation_blueprint"],
        )
        self.assertIn("climb_wall_jump", detailed["animation_integration"]["required_roles"])
        self.assertIn("TransferReacquiring", detailed["proposed_architecture"]["state_flow"])
        self.assertTrue(any(row["unresolved_params"] for row in detailed["action_graph"]))
        self.assertFalse(detailed["readiness"]["ready_for_completion_claim"])
        rendered = render_unreal_feature_plan(plan)
        self.assertIn("Project Context:", rendered)
        self.assertIn("What I'll Build:", rendered)
        self.assertIn("Generated State Flow:", rendered)
        self.assertIn("climb_wall_jump", rendered)
        self.assertIn("candidate_only", rendered)

    def test_prompt_contract_preserves_trigger_inputs_timing_and_scope(self) -> None:
        contract = derive_prompt_requirement_contract(CLIMB_PROMPT)
        explicit = contract["explicit"]

        self.assertIn("walking up", explicit["activation"])
        self.assertEqual(["UP", "W"], explicit["inputs"])
        self.assertEqual("greater_than", explicit["timing"][0]["operator"])
        self.assertEqual(1.0, explicit["timing"][0]["seconds"])
        self.assertEqual(["any wall"], explicit["scope"])

    def test_gameplay_contract_covers_every_validation_level(self) -> None:
        contract = build_gameplay_proof_contract(CLIMB_PROMPT)
        levels = {claim.evidence_level for claim in contract.proof_claims}

        self.assertEqual(set(range(1, 7)), levels)
        self.assertIn("UP or W", contract.gameplay_contract.runtime_behavior[0])
        self.assertNotIn("stamina", contract.gameplay_contract.completion_or_cancellation.lower())
        self.assertTrue(any("contextually invalid" in value for value in contract.gameplay_contract.invalid_conditions))

    def test_unbound_runtime_observations_block_before_execution(self) -> None:
        contract = build_gameplay_proof_contract(CLIMB_PROMPT)
        bridge = Mock()
        bridge.find_port.return_value = 12347
        bridge.execute_python.return_value = {"ok": True}

        status = GameplayProofExecutionService(bridge=bridge).run_proof_pipeline(contract)

        self.assertEqual(FeatureCompletionStatus.RUNTIME_BLOCKED, status)
        self.assertEqual(1, bridge.execute_python.call_count)
        self.assertTrue(any("observation bindings" in value for value in contract.self_repair_notes))

    def test_runtime_comparison_requires_explicit_comparator(self) -> None:
        service = GameplayProofExecutionService()
        claim = ProofClaim(
            claim_id="exact_state",
            when_trigger="public trigger",
            then_assertion="state equals Active",
        )
        observation = {
            "claim_id": "exact_state",
            "property": "State",
            "expected": "Active",
            "observed": "Inactive",
            "timestamp": 0.5,
        }

        passed, _detail = service._evaluate_claim(claim, "run", [observation], [], [])
        self.assertFalse(passed)
        observation["comparator"] = "equals"
        passed, _detail = service._evaluate_claim(claim, "run", [observation], [], [])
        self.assertFalse(passed)
        observation["observed"] = "Active"
        passed, _detail = service._evaluate_claim(claim, "run", [observation], [], [])
        self.assertTrue(passed)

    def test_registered_graph_operations_resolve_to_real_functions(self) -> None:
        self.assertTrue(_local_operation_status("blueprint.add_node")["callable_found"])
        self.assertTrue(_local_operation_status("blueprint.connect_node_pins")["callable_found"])
        self.assertTrue(_local_operation_status("knowledge.compare_approaches")["callable_found"])

    def test_benchmark_does_not_award_runtime_proof_for_pending_claims(self) -> None:
        proof = build_gameplay_proof_contract(CLIMB_PROMPT).to_dict()
        plan = {
            "status": "knowledge_choice_required",
            "target_asset": "/Game/BP_Test",
            "requirement_contract": derive_prompt_requirement_contract(CLIMB_PROMPT),
            "gameplay_proof_contract": proof,
            "evidence": {
                "skeletal_mesh": "/Game/SK_Test",
                "animation_blueprint": "/Game/ABP_Test",
                "related_animation_candidates": [
                    {
                        "acceptance": "candidate_only",
                        "required_evidence": ["contextual preview"],
                    }
                ],
            },
            "architecture_decision": {
                "current_animation_blueprint": "/Game/ABP_Test",
                "animation_integration": "Extend current",
                "rejected_shortcut": "Do not replace the current AnimBP",
            },
            "expert_technique_selection": {"techniques": [{"sources": [{"url": "official"}]}]},
            "build_readiness": {"blocked_by": []},
            "self_review": {"all_operations_verified": True},
        }

        result = evaluate_unreal_prompt_plan(plan)
        scores = {row["key"]: row["score"] for row in result["categories"]}

        self.assertEqual(1, scores["runtime_and_gameplay_evidence"])
        self.assertFalse(result["verified_complete"])
        self.assertEqual(2, scores["completion_honesty"])

    def test_animation_search_focus_excludes_activation_noise(self) -> None:
        terms = _normalized_search_terms(CLIMB_PROMPT)
        focus = _focus_search_terms(CLIMB_PROMPT, terms)
        tokens = _asset_search_tokens("A_ClimbHang_Manny", "/Game/Anims/A_ClimbHang_Manny")

        self.assertIn("climb", focus)
        self.assertNotIn("walk", terms)
        self.assertIn("climb", tokens)

    def test_animation_search_can_resolve_one_edit_prompt_typo(self) -> None:
        typo_terms = _normalized_search_terms("create an ABP specifically for climing")
        focus = _focus_search_terms("create an ABP specifically for climing", typo_terms)

        self.assertIn("clim", focus)
        self.assertTrue(_one_edit_apart("clim", "climb"))

    def test_known_win_still_requests_current_technique_comparison(self) -> None:
        review = build_technique_currency_review(
            "compare this known climbing approach against newer techniques",
            engine_version="5.8",
            techniques=[
                {
                    "key": "movement.surface_constrained_traversal",
                    "registry_engine_version": "5.8",
                    "sources": [{"url": "https://dev.epicgames.com/example"}],
                }
            ],
            verified_episodes=[{"reusable": True}],
            research_mode={"enable_live_sources": True, "research_official_docs": True},
        )

        self.assertTrue(review["comparison"]["required"])
        self.assertEqual("ready_to_research", review["comparison"]["status"])
        self.assertIn("run_with_known_baseline", review["next_choices"])

    def test_newer_candidate_cannot_replace_baseline_without_runtime_proof(self) -> None:
        comparison = compare_technique_candidates(
            {"key": "known_win"},
            [
                {
                    "key": "newer_candidate",
                    "source": {
                        "url": "https://dev.epicgames.com/example",
                        "claim": "New engine pattern",
                        "source_kind": "official_docs",
                        "applies_to_version": "5.8",
                    },
                    "runtime_proof": {"all_gates_passed": False},
                }
            ],
        )

        self.assertEqual("retain_baseline_pending_proof", comparison["decision"])
        self.assertFalse(comparison["candidates"][0]["eligible_to_replace_baseline"])
        self.assertFalse(comparison["completion_allowed"])

    def test_private_or_paid_candidate_cannot_replace_shared_baseline(self) -> None:
        comparison = compare_technique_candidates(
            {"key": "known_win"},
            [{
                "key": "paid_candidate",
                "source": {
                    "url": "https://example.com/private-course",
                    "claim": "Alternative architecture",
                    "source_kind": "tutorial",
                    "applies_to_version": "5.8",
                    "paid": True,
                    "auth_required": True,
                    "entitlement_verified": True,
                    "use_for_current_task": True,
                },
                "runtime_proof": {"all_gates_passed": True},
            }],
        )

        candidate = comparison["candidates"][0]
        self.assertFalse(candidate["eligible_to_replace_baseline"])
        self.assertFalse(candidate["source_policy"]["community_share_allowed"])

    def test_system_recipe_requires_complete_trusted_level_one_through_six_proof(self) -> None:
        proof = build_gameplay_proof_contract(CLIMB_PROMPT).to_dict()
        for claim in proof["proof_claims"]:
            claim["status"] = "passed"
            claim["evidence_origin"] = (
                "unreal_editor" if claim["evidence_level"] == 1 else "unreal_automation"
            )
            claim["evidence_observed"] = "Observed assertion passed in isolated Unreal fixture."
        spec = {
            "request": CLIMB_PROMPT,
            "stimuli": ["W input and wall contact"],
            "observations": ["surface trace and hold duration"],
            "guards": ["valid traversable surface"],
            "states": ["idle", "enter", "active", "exit", "cancel"],
            "effects": ["surface-constrained character movement"],
            "presentation": ["contextually accepted climbing animation"],
            "assets": [{"role": "climb", "compatibility_checks": ["skeleton", "context preview"]}],
            "failure_paths": ["early release", "contact loss"],
            "runtime_scenarios": ["activate, climb, cancel, recover"],
            "operations": [{"operation": "test", "callable": "module.fn", "postconditions": ["observed"]}],
            "evidence": [{
                "source_url": "https://dev.epicgames.com/",
                "source_kind": "official_docs",
                "claim": "Engine contract",
                "applies_to_version": "5.8",
            }],
        }
        verification = {
            **{gate: True for gate in REQUIRED_VERIFICATION_GATES},
            "gameplay_proof_contract": proof,
        }

        with TemporaryDirectory() as root:
            accepted = promote_verified_feature_recipe(
                spec,
                verification,
                path=Path(root) / "recipes.jsonl",
            )
            self.assertTrue(accepted["learned"])

            proof["proof_claims"][-1]["status"] = "pending"
            rejected = promote_verified_feature_recipe(
                spec,
                verification,
                path=Path(root) / "rejected.jsonl",
            )
            self.assertFalse(rejected["learned"])
            self.assertIn(proof["proof_claims"][-1]["claim_id"], rejected["verification"]["system_proof"]["invalid_claims"])

    def test_newer_technique_request_routes_to_open_research_comparison(self) -> None:
        plan = _generic_unreal_feature_plan(
            "In Unreal compare our climbing approach against newer techniques",
            {
                "sufficient": True,
                "target_asset": "/Game/BP_Test",
                "blueprint": {"components": []},
                "animation_blueprints": [],
                "assets": {"related_animations": []},
            },
        )
        selected = {
            row["key"] for row in plan["expert_technique_selection"]["techniques"]
        }
        blocked = set(plan["build_readiness"]["blocked_by"])
        research_steps = [
            row for row in plan["capability_acquisition"]
            if str(row.get("capability") or "").startswith("knowledge.")
        ]

        self.assertIn("knowledge.source_comparison", selected)
        self.assertNotIn("knowledge.compare_approaches", blocked)
        self.assertNotIn("knowledge.search_sources", blocked)
        self.assertNotIn("knowledge.extract_claims", blocked)
        self.assertEqual([], research_steps)
        self.assertTrue(_local_operation_status("knowledge.search_sources")["callable_found"])
        self.assertTrue(_local_operation_status("knowledge.extract_claims")["callable_found"])

    def test_legacy_compile_only_system_recipe_is_quarantined_on_read(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "recipes.jsonl"
            path.write_text(
                json.dumps({
                    "request": "climbing system",
                    "verification": {
                        "all_gates_passed": True,
                        "blueprints_compiled": True,
                    },
                }) + "\n",
                encoding="utf-8",
            )

            self.assertEqual([], load_verified_feature_recipes(path=path))


if __name__ == "__main__":
    unittest.main()
