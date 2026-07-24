from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tech_connector.engine.request_context import RequestContext
from tech_connector.services.choice_provider_service import (
    ChoiceProviderRequest,
    UnrealAssetChoiceProvider,
)
from tech_connector.services.license_entitlement_service import make_license_token
from tech_connector.services.reasoning.clarification_service import (
    bind_clarification_response,
    build_confirmation,
    build_slot_clarification,
    choice_provider_for_slot,
    expected_type_for_slot,
    proposed_input_approval_policy,
)


class TestClarificationApprovalControls(unittest.TestCase):
    def test_proposed_project_context_requires_approval_by_default(self) -> None:
        context = RequestContext(
            text="Use the played character",
            extras={
                "target_blueprint": "/Game/Characters/BP_LesterPhoenix",
                "settings": {"execution_approval_mode": "always_ask"},
            },
        )
        policy = proposed_input_approval_policy(context)
        self.assertTrue(policy["requires_approval"])
        self.assertEqual(policy["mode"], "always_ask")

        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal"},
            context=context,
            missing_slots=["target_blueprint"],
            execution_request={"execution_environment": "unreal"},
        )
        self.assertEqual(result.request.slots[0].state, "confirm")
        self.assertTrue(result.request.slots[0].requires_confirmation)
        self.assertEqual(
            result.request.ui_controls[0]["inferred_value"],
            "/Game/Characters/BP_LesterPhoenix",
        )

    def test_full_automation_requires_explicit_mode_and_entitlement(self) -> None:
        secret = "approval-policy-test"
        token = make_license_token(
            {"tier": "commercial", "license_id": "lic_automation"},
            secret,
        )
        context = RequestContext(
            text="Use the played character",
            extras={
                "settings": {
                    "execution_approval_mode": "full_automation",
                    "tech_connector_license_token": token,
                }
            },
        )
        with patch.dict(
            "os.environ",
            {"TECH_CONNECTOR_LICENSE_VERIFY_SECRET": secret},
            clear=False,
        ):
            policy = proposed_input_approval_policy(context)
        self.assertFalse(policy["requires_approval"])
        self.assertEqual(policy["mode"], "full_automation")
        self.assertTrue(policy["entitled"])

    def test_mesh_choice_provider_is_selected_by_declared_slot_type(self) -> None:
        self.assertEqual(choice_provider_for_slot("mesh", "unreal"), "unreal.meshes")
        self.assertEqual(expected_type_for_slot("mesh", "unreal"), "unreal.Mesh")
        self.assertEqual(
            choice_provider_for_slot("skeletal_mesh", "unreal"),
            "unreal.skeletal_meshes",
        )
        self.assertEqual(
            expected_type_for_slot("skeletal_mesh", "unreal"),
            "unreal.SkeletalMesh",
        )
        self.assertEqual(
            choice_provider_for_slot("static_mesh", "unreal"),
            "unreal.static_meshes",
        )
        self.assertEqual(
            expected_type_for_slot("static_mesh", "unreal"),
            "unreal.StaticMesh",
        )

    def test_live_unreal_asset_provider_preserves_asset_classes_and_recommendation(self) -> None:
        calls = []

        class Bridge:
            def call(self, function, args=None, kwargs=None):
                calls.append((function, list(args or []), dict(kwargs or {})))
                asset_class = args[0]
                values = {
                    "SkeletalMesh": ["/Game/Characters/SKM_Manny.SKM_Manny"],
                    "StaticMesh": ["/Game/Props/SM_Crate.SM_Crate"],
                }
                return True, values.get(asset_class, [])

        provider = UnrealAssetChoiceProvider(
            "unreal.meshes",
            ("SkeletalMesh", "StaticMesh"),
            "Unreal meshes",
        )
        result = provider.choices(
            ChoiceProviderRequest(
                provider_id="unreal.meshes",
                slot_name="mesh",
                filters={
                    "recommended_value": "/Game/Props/SM_Crate.SM_Crate",
                    "limit": 20,
                },
                context_snapshot={
                    "window": SimpleNamespace(
                        command_router=SimpleNamespace(unreal=Bridge())
                    )
                },
            )
        )

        self.assertEqual(result.status, "loaded")
        self.assertEqual(
            [call[1][0] for call in calls],
            ["SkeletalMesh", "StaticMesh"],
        )
        self.assertEqual(result.choices[0].value, "/Game/Props/SM_Crate.SM_Crate")
        self.assertTrue(result.choices[0].is_recommended)
        self.assertEqual(
            {choice.metadata["asset_class"] for choice in result.choices},
            {"SkeletalMesh", "StaticMesh"},
        )

    def test_blueprint_resolution_control_is_editable_and_typed(self) -> None:
        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal"},
            context=RequestContext(text="Use BP_LesterPhoenix"),
            missing_slots=["target_blueprint"],
            execution_request={
                "execution_environment": "unreal",
                "original_prompt": "Use BP_LesterPhoenix",
                "keyword_args": {
                    "target_blueprint": "/Game/Characters/BP_LesterPhoenix"
                },
            },
        )
        control = result.request.ui_controls[0]
        self.assertEqual(control["choice_provider_id"], "unreal.blueprints")
        self.assertEqual(control["expected_type"], "unreal.AssetPath")
        self.assertTrue(control["editable"])
        self.assertEqual(
            control["provider_filters"]["recommended_value"],
            "/Game/Characters/BP_LesterPhoenix",
        )

    def test_confirmation_uses_approve_deny_buttons(self) -> None:
        result = build_confirmation(
            decision={"route": "dcc_execute", "host": "maya", "requires_confirmation": True},
            context=RequestContext(text="Maya create cube"),
            execution_request={
                "callable_name": "ai_studio.maya.generated.modeling_create_primitive",
                "execution_environment": "maya",
                "keyword_args": {"primitive_type": "cube"},
                "mutation_scope": "dcc_scene_mutation",
                "risk_level": "high",
                "requires_confirmation": True,
            },
            dispatch_result={
                "confirmation_request": {
                    "mutation_scope": "dcc_scene_mutation",
                    "risk_level": "high",
                }
            },
        )
        self.assertIn("Use Approve or Deny below", result.text)
        labels = [control["label"] for control in result.request.ui_controls]
        self.assertEqual(labels, ["Approve", "Deny"])

    def test_confirmation_binder_accepts_button_labels(self) -> None:
        result = build_confirmation(
            decision={"route": "dcc_execute", "requires_confirmation": True},
            context=RequestContext(text="Blender make a cube"),
            execution_request={"requires_confirmation": True},
        )
        approved = bind_clarification_response(result.pending_state, "Approve")
        denied = bind_clarification_response(result.pending_state, "Deny")
        self.assertTrue(approved["accepted"])
        self.assertEqual(approved["action"], "confirm")
        self.assertFalse(approved["route_decision"]["requires_confirmation"])
        self.assertTrue(denied["accepted"])
        self.assertEqual(denied["action"], "cancel")

    def test_unreal_graph_missing_slots_offer_context_choices(self) -> None:
        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal", "missing_info": ["target_asset", "target_graph", "graph_operations"]},
            context=RequestContext(text="In Unreal add stamina to BP_LesterPhoenix anim graph"),
            missing_slots=["target_asset", "target_graph", "graph_operations"],
            execution_request={
                "execution_environment": "unreal",
                "original_prompt": "In Unreal add stamina to BP_LesterPhoenix anim graph",
                "missing_slots": ["target_asset", "target_graph", "graph_operations"],
            },
        )
        controls = {control["slot"]: control for control in result.request.ui_controls}
        self.assertEqual(controls["target_asset"]["choice_provider_id"], "unreal.assets")
        self.assertEqual(controls["graph_operations"]["choice_provider_id"], "unreal.operations")
        self.assertEqual(controls["target_graph"]["type"], "choice")
        self.assertIn({"value": "AnimGraph", "label": "Anim Graph"}, controls["target_graph"]["choices"])
        self.assertIn("I inferred the needed context from your prompt", result.text)
        self.assertIn("BP_LesterPhoenix", result.text)
        self.assertIn("AnimGraph", result.text)

    def test_structured_slot_binder_accepts_approve_form_values(self) -> None:
        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal", "missing_info": ["target_asset", "target_graph", "graph_operations"]},
            context=RequestContext(text="In Unreal add stamina to BP_LesterPhoenix anim graph"),
            missing_slots=["target_asset", "target_graph", "graph_operations"],
            execution_request={
                "execution_environment": "unreal",
                "missing_slots": ["target_asset", "target_graph", "graph_operations"],
            },
        )
        binding = bind_clarification_response(
            result.pending_state,
            '{"slots":{"target_asset":"/Game/Characters/BP_LesterPhoenix","target_graph":{"value":"AnimGraph","label":"Anim Graph"},"graph_operations":"inspect_graph"}}',
        )
        self.assertTrue(binding["accepted"])
        self.assertEqual(binding["action"], "resume")
        keyword_args = binding["execution_request"]["keyword_args"]
        self.assertEqual(keyword_args["target_asset"], "/Game/Characters/BP_LesterPhoenix")
        self.assertEqual(keyword_args["target_graph"], "AnimGraph")
        self.assertEqual(keyword_args["graph_operations"], "inspect_graph")
        self.assertEqual(binding["execution_request"]["missing_slots"], [])

    def test_natural_chat_reply_can_fill_unreal_graph_slots(self) -> None:
        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal", "missing_info": ["target_asset", "target_graph", "graph_operations"]},
            context=RequestContext(text="In Unreal inspect the current project for sprint or stamina. Do not edit anything yet."),
            missing_slots=["target_asset", "target_graph", "graph_operations"],
            execution_request={
                "execution_environment": "unreal",
                "original_prompt": "In Unreal inspect BP_LesterPhoenix anim graph for sprint or stamina. Do not edit anything yet.",
                "missing_slots": ["target_asset", "target_graph", "graph_operations"],
            },
        )
        binding = bind_clarification_response(result.pending_state, "Use BP_LesterPhoenix anim graph and inspect only.")
        self.assertTrue(binding["accepted"])
        keyword_args = binding["execution_request"]["keyword_args"]
        self.assertEqual(keyword_args["target_asset"], "BP_LesterPhoenix")
        self.assertEqual(keyword_args["target_graph"], "AnimGraph")
        self.assertEqual(keyword_args["graph_operations"], "inspect_graph")
        self.assertEqual(binding["execution_request"]["missing_slots"], [])

    def test_chat_approval_accepts_inferred_context_slots(self) -> None:
        result = build_slot_clarification(
            decision={"route": "dcc_execute", "host": "unreal", "missing_info": ["target_asset", "target_graph", "graph_operations"]},
            context=RequestContext(text="In Unreal add stamina to BP_LesterPhoenix anim graph"),
            missing_slots=["target_asset", "target_graph", "graph_operations"],
            execution_request={
                "execution_environment": "unreal",
                "original_prompt": "In Unreal add stamina to BP_LesterPhoenix anim graph",
                "missing_slots": ["target_asset", "target_graph", "graph_operations"],
            },
        )
        self.assertIn("Reply approve/yes to continue", result.text)
        binding = bind_clarification_response(result.pending_state, "yee")
        self.assertTrue(binding["accepted"])
        keyword_args = binding["execution_request"]["keyword_args"]
        self.assertEqual(keyword_args["target_asset"], "BP_LesterPhoenix")
        self.assertEqual(keyword_args["target_graph"], "AnimGraph")
        self.assertEqual(keyword_args["graph_operations"], "semantic_graph_edit")
        self.assertEqual(binding["execution_request"]["missing_slots"], [])


if __name__ == "__main__":
    unittest.main()
