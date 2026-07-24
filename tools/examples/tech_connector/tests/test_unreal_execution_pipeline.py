from __future__ import annotations

import json
import sys
import unittest

from tech_connector.services.unreal.capability_registry import validate_unreal_capability_registry
from tech_connector.services.prompt.prompt_intent_service import (
    RequestTask,
    RequestUnderstanding,
    _needs_semantic_model,
    understand_prompt_request_deterministic,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.prompt.prompt_plan_verification_service import verify_prompt_plan_alignment
from tech_connector.services.prompt.prompt_task_splitter_service import build_request_task_graph
from tech_connector.services.unreal.unreal_operation_service import (
    build_unreal_editable_character_fx_params,
    build_unreal_execution_plan,
    unreal_prompt_to_operation,
)
from tech_connector.services.unreal.unreal_resolvers import _extract_query_string


class TestUnrealExecutionPipeline(unittest.TestCase):

    def test_capability_registry_health(self) -> None:
        """Verify the capability registry is 100% healthy and matches operations."""
        report = validate_unreal_capability_registry()
        self.assertTrue(report["ok"], f"Capability registry invalid: {report}")
        self.assertEqual(report["registered_count"], 139)

    def test_extract_query_string_resolver(self) -> None:
        """Verify extraction from nested resolver results handles types gracefully."""
        self.assertEqual(_extract_query_string("direct_str"), "direct_str")
        self.assertEqual(_extract_query_string({"ref": "val_ref"}), "val_ref")
        self.assertEqual(_extract_query_string({"path": "val_path"}), "val_path")
        self.assertEqual(_extract_query_string({"name": "val_name"}), "val_name")
        self.assertEqual(_extract_query_string(["list_item"]), "list_item")
        self.assertEqual(_extract_query_string([]), "")
        self.assertEqual(_extract_query_string(None), "")

    def test_editable_character_niagara_fx_prompt_has_dependency_rich_plan(self) -> None:
        prompt = (
            "In Unreal add a really cool editable Niagara aura FX component to "
            "BP_ThirdPersonCharacter, attached to spine_03, with tunable color, "
            "intensity, spawn rate, radius, lifetime, pulse speed, auto activate, "
            "socket, and offset parameters."
        )

        self.assertEqual(unreal_prompt_to_operation(prompt), "niagara.attach_editable_character_fx")
        params = build_unreal_editable_character_fx_params(prompt)
        self.assertEqual(params["blueprint_path"], "BP_ThirdPersonCharacter")
        self.assertEqual(params["component_name"], "AIStudio_AuraFX")
        self.assertEqual(params["socket_name"], "spine_03")
        self.assertIn("FX_SpawnRate", params["parameters"])

        plan = build_unreal_execution_plan(prompt)
        self.assertEqual(plan["operation"], "niagara.attach_editable_character_fx")
        self.assertIn("BP_ThirdPersonCharacter", plan["affected_assets"])
        self.assertTrue(any("Duplicate or reuse Niagara System" in step for step in plan["steps"]))
        self.assertTrue(any("Create editable Blueprint variables" in step for step in plan["steps"]))

        decision = classify_prompt_route(prompt)
        self.assertEqual(decision.route, "dcc_execute")
        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.target_identifier, "niagara.attach_editable_character_fx")
        self.assertIn("FX_Intensity", decision.keyword_args["parameters"])

    def test_camera_outline_niagara_prompt_preserves_source_strategy(self) -> None:
        prompt = (
            "In Unreal create a Niagara effect on BP_ThirdPersonCharacter where "
            "the camera-facing outline/silhouette of the character is the emitter "
            "source, with editable cyan color, edge thickness, spawn rate, camera "
            "fade, noise, and intensity parameters."
        )

        self.assertEqual(unreal_prompt_to_operation(prompt), "niagara.attach_editable_character_fx")
        params = build_unreal_editable_character_fx_params(prompt)
        self.assertEqual(params["blueprint_path"], "BP_ThirdPersonCharacter")
        self.assertEqual(params["component_name"], "AIStudio_CameraSilhouetteOutlineFX")
        self.assertEqual(params["system_path"], "/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CameraSilhouetteOutline")
        self.assertEqual(params["parameters"]["FX_Profile"], "camera_silhouette_outline")
        self.assertEqual(params["parameters"]["FX_SourceMode"], "camera_facing_character_outline")
        self.assertEqual(params["parameters"]["FX_Color"], [0.0, 0.85, 1.0, 1.0])
        self.assertIn("FX_EdgeThickness", params["parameters"])
        self.assertIn("FX_CameraFade", params["parameters"])

        plan = build_unreal_execution_plan(prompt)
        self.assertEqual(plan["operation"], "niagara.attach_editable_character_fx")
        self.assertFalse(plan["complete"])
        self.assertEqual(
            plan["capability_gaps"][0]["required_capability"],
            "niagara.synthesize_source_strategy_stack",
        )
        self.assertTrue(any("camera-facing silhouette/outline source" in step for step in plan["steps"]))
        self.assertTrue(any("Bind supported Blueprint variables" in step for step in plan["steps"]))

        decision = classify_prompt_route(prompt)
        self.assertEqual(decision.route, "target_discovery")
        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.operation_mode, "acquire_then_resume")
        self.assertEqual(decision.target_identifier, "niagara.synthesize_source_strategy_stack")
        self.assertEqual(
            decision.capability_gap_plan["resume_operation"],
            "niagara.attach_editable_character_fx",
        )
        contract = decision.capability_gap_plan["requested_behavior_contract"]
        self.assertEqual(contract["source_strategy"], "camera_facing_character_outline")
        self.assertIn("FX_EdgeThickness", contract["required_parameter_names"])
        self.assertTrue(any("not merely generic Niagara asset creation" in item for item in contract["acceptance"]))
        self.assertEqual(decision.keyword_args["parameters"]["FX_SourceMode"], "camera_facing_character_outline")

        understanding = understand_prompt_request_deterministic(prompt)
        self.assertEqual(understanding.host, "unreal")
        self.assertTrue(understanding.mutation_requested)
        self.assertFalse(understanding.read_only_requested)

    def test_implicit_unreal_niagara_compound_prompt_reaches_capability_acquisition(self) -> None:
        prompt = (
            "Create a cinematic Niagara effect whose emitter source follows the visible camera-facing "
            "outline of the player character mesh, with editable color, intensity, width, spawn rate, "
            "lifetime, velocity, noise, and fade parameters. Attach it to a valid character component "
            "or bone, wire Blueprint variables into Niagara user parameters, compile, save, and validate "
            "it in play mode."
        )

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.host, "unreal")
        self.assertEqual(decision.route, "target_discovery")
        self.assertEqual(decision.operation_mode, "acquire_then_resume")
        self.assertEqual(decision.target_identifier, "niagara.synthesize_source_strategy_stack")
        self.assertEqual(
            decision.capability_gap_plan["resume_operation"],
            "niagara.attach_editable_character_fx",
        )
        contract = decision.capability_gap_plan["requested_behavior_contract"]
        self.assertIn("FX_Velocity", contract["required_parameter_names"])
        self.assertTrue(any("Play In Editor" in step for step in contract["planned_steps"]))

    def test_compositional_dcc_request_defers_model_to_plan_verifier(self) -> None:
        prompt = (
            "In Unreal create a Niagara effect on BP_ThirdPersonCharacter where "
            "the camera-facing outline of the character is the emitter source, "
            "with editable color, edge thickness, camera fade, and noise controls."
        )
        baseline = RequestUnderstanding(
            normalized_goal=prompt,
            primary_intent="dcc_execution",
            primary_route="dcc_execute",
            host="unreal",
            mutation_requested=True,
            live_host_execution_requested=True,
            confidence=0.98,
        )

        self.assertFalse(_needs_semantic_model(prompt, baseline))

        atomic_prompt = "In Unreal compile BP_ThirdPersonCharacter."
        atomic_baseline = RequestUnderstanding(
            normalized_goal=atomic_prompt,
            primary_intent="dcc_execution",
            primary_route="dcc_execute",
            host="unreal",
            mutation_requested=True,
            live_host_execution_requested=True,
            confidence=0.98,
        )
        self.assertFalse(_needs_semantic_model(atomic_prompt, atomic_baseline))

    def test_lightweight_plan_verifier_rejects_missing_specific_behavior(self) -> None:
        prompt = (
            "Create a Niagara effect where the camera-visible character outline "
            "is the emitter source and validate the contour as the camera moves."
        )
        candidate = {
            "route": "dcc_execute",
            "operation_plan": {
                "operation": "niagara.attach_editable_character_fx",
                "steps": [
                    "Create or reuse a Niagara System.",
                    "Attach a NiagaraComponent to the character Blueprint.",
                    "Compile and save the Blueprint.",
                ],
            },
        }
        model_response = {
            "matches_request": False,
            "covered": [
                {
                    "request_fragment": "Create a Niagara effect",
                    "plan_evidence": "Create or reuse a Niagara System.",
                }
            ],
            "missing": [
                {
                    "request_fragment": "camera-visible character outline is the emitter source",
                    "reason": "No step derives source positions from the camera-visible contour.",
                    "required_capability": "niagara.sample_camera_visible_silhouette",
                }
            ],
            "distorted": [],
            "unsupported_claims": [],
            "confidence": 0.97,
        }

        verdict = verify_prompt_plan_alignment(
            prompt,
            candidate,
            model_query=lambda _system, _user: __import__("json").dumps(model_response),
        )

        self.assertEqual(verdict["status"], "mismatch")
        self.assertFalse(verdict["matches_request"])
        self.assertEqual(
            verdict["missing"][0]["required_capability"],
            "niagara.sample_camera_visible_silhouette",
        )

    def test_plan_verifier_escalates_low_confidence_1_5b_verdict_to_3b(self) -> None:
        calls = []
        low_confidence = {
            "match": True,
            "missing": [],
            "wrong": [],
            "unsupported": [],
            "confidence": 0.4,
        }
        confident = {
            "match": False,
            "missing": [{
                "text": "camera outline source mutation",
                "reason": "No concrete stack mutation step exists.",
                "capability": "niagara.synthesize_source_strategy_stack",
            }],
            "wrong": [],
            "unsupported": [],
            "confidence": 0.94,
        }

        verdict = verify_prompt_plan_alignment(
            "Create camera-outline Niagara FX.",
            {"operation_plan": {"operation": "niagara.attach_editable_character_fx", "steps": ["Attach FX."]}},
            model_query=lambda _system, _user: json.dumps(low_confidence),
            fallback_model_query=lambda _system, _user: calls.append("3b") or json.dumps(confident),
        )

        self.assertEqual(calls, ["3b"])
        self.assertEqual(verdict["verifier_tier"], "semantic_code_3b_fallback")
        self.assertFalse(verdict["matches_request"])

    def test_plan_verifier_dismisses_missing_claim_contradicted_by_plan_text(self) -> None:
        response = {
            "match": False,
            "missing": [{
                "text": "Blueprint variables into Niagara user parameters",
                "reason": "The plan does not bind the variables.",
                "capability": "",
            }],
            "wrong": [],
            "unsupported": [],
            "confidence": 0.8,
        }
        candidate = {"operation_plan": {
            "operation": "niagara.attach_editable_character_fx",
            "steps": ["Bind Blueprint variables into matching Niagara user parameters."],
        }}

        verdict = verify_prompt_plan_alignment(
            "Wire Blueprint variables into Niagara user parameters.",
            candidate,
            model_query=lambda _system, _user: json.dumps(response),
        )

        self.assertTrue(verdict["matches_request"])
        self.assertEqual(verdict["missing"], [])
        self.assertEqual(len(verdict["dismissed_missing"]), 1)

    def test_semantic_atomic_operation_gap_survives_composite_routing(self) -> None:
        prompt = (
            "In Unreal create a Niagara effect on BP_ThirdPersonCharacter where "
            "the camera-facing outline of the character is the emitter source, "
            "with editable color, edge thickness, camera fade, and noise controls."
        )
        understanding = RequestUnderstanding(
            normalized_goal=prompt,
            primary_goal="Emit particles from the camera-visible character outline",
            primary_intent="dcc_execution",
            primary_route="dcc_execute",
            primary_action="create",
            requested_artifact="Niagara character effect",
            behavior_description="Use the camera-visible character silhouette as the emitter source.",
            host="unreal",
            mutation_requested=True,
            live_host_execution_requested=True,
            requires_execution=True,
            requires_validation=True,
            goal_type="execute",
            confidence=0.96,
            source="model",
            model_name="test-small-semantic-model",
            tasks=[
                RequestTask(
                    task_id="goal_1",
                    action="execute",
                    objective="Attach the editable Niagara component.",
                    capability="niagara.attach_editable_character_fx",
                    produces=["attached_fx"],
                    read_only=False,
                ),
                RequestTask(
                    task_id="goal_2",
                    action="execute",
                    objective="Sample the camera-visible character silhouette as particle source positions.",
                    capability="niagara.sample_camera_visible_silhouette",
                    depends_on=["goal_1"],
                    produces=["silhouette_particle_source"],
                    read_only=False,
                ),
                RequestTask(
                    task_id="goal_3",
                    action="validate",
                    objective="Prove emitted particles originate on the visible outline in PIE.",
                    capability="runtime.validate_niagara_source",
                    depends_on=["goal_2"],
                    read_only=True,
                    terminal=True,
                ),
            ],
        )
        graph = build_request_task_graph(prompt, host="unreal", understanding=understanding)
        decision = classify_prompt_route(
            prompt,
            execution_context={
                "request_understanding": understanding.to_dict(),
                "task_graph": graph,
            },
        )

        self.assertEqual(decision.route, "target_discovery")
        self.assertEqual(decision.target_identifier, "niagara.synthesize_source_strategy_stack")
        self.assertEqual(
            decision.capability_gap_plan["resume_operation"],
            "niagara.attach_editable_character_fx",
        )
        semantic_graph = decision.task_graph["semantic_request_graph"]
        self.assertEqual(semantic_graph["source"], "model")
        evaluations = {
            row["capability"]: row
            for row in decision.task_graph["semantic_capability_evaluation"]
        }
        self.assertEqual(
            evaluations["niagara.attach_editable_character_fx"]["status"],
            "registered_callable",
        )
        self.assertEqual(
            evaluations["niagara.sample_camera_visible_silhouette"]["status"],
            "missing_unregistered_callable",
        )
        self.assertIn("niagara.sample_camera_visible_silhouette", decision.capability_gaps)
        self.assertIn("runtime.validate_niagara_source", decision.capability_gaps)
