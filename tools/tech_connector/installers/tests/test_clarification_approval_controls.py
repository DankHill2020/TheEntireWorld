from __future__ import annotations

import unittest

from tech_connector.engine.request_context import RequestContext
from tech_connector.services.clarification_service import bind_clarification_response, build_confirmation, build_slot_clarification


class TestClarificationApprovalControls(unittest.TestCase):
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
