import unittest
from unittest.mock import patch

from tech_connector.engine.request_context import RequestContext
from tech_connector.services.clarification_service import build_confirmation
from tech_connector.services.dcc.dcc_execution_service import build_dcc_execution_request, default_dcc_execution_adapters
from tech_connector.services.prompt_dispatch_service import CAP_DCC_CONNECTION, PassthroughRouteHandler, PromptDispatchService
from tech_connector.services.prompt_route_service import classify_prompt_route


class TestUnrealGraphPromptDispatch(unittest.TestCase):
    def test_direct_dcc_bridge_satisfies_connection_requirement_without_window(self):
        service = PromptDispatchService(
            handlers={
                "test.dcc": PassthroughRouteHandler(
                    handler_id="TestDccHandler",
                    reason="dispatched",
                    requires={CAP_DCC_CONNECTION},
                )
            }
        )
        decision = {
            "execution_route": "test.dcc",
            "requires_dcc_connection": True,
            "host": "maya",
            "route": "dcc_execute",
        }

        with patch("tech_connector.services.dcc.dcc_execution_service._maya_direct_bridge_available", return_value=True):
            result = service.dispatch(decision, RequestContext(text="prompt"), emit=lambda _event: None)

        self.assertEqual(result.action, "passthrough")
        self.assertNotEqual(result.result_type, "missing_capabilities")

    def test_missing_direct_dcc_bridge_still_requests_connection(self):
        service = PromptDispatchService(
            handlers={
                "test.dcc": PassthroughRouteHandler(
                    handler_id="TestDccHandler",
                    reason="dispatched",
                    requires={CAP_DCC_CONNECTION},
                )
            }
        )
        decision = {
            "execution_route": "test.dcc",
            "requires_dcc_connection": True,
            "host": "maya",
            "route": "dcc_execute",
        }

        with patch("tech_connector.services.dcc.dcc_execution_service._maya_direct_bridge_available", return_value=False):
            result = service.dispatch(decision, RequestContext(text="prompt"), emit=lambda _event: None)

        self.assertEqual(result.action, "clarify")
        self.assertEqual(result.result_type, "missing_capabilities")
        self.assertIn(CAP_DCC_CONNECTION, result.metadata["missing_capabilities"])

    def test_graph_prompt_request_does_not_treat_blueprint_as_callable(self):
        prompt = (
            "In Unreal, add a temporary BeginPlay debug print node to BP_LesterPhoenix "
            "EventGraph that says AIStudio BeginPlay Probe."
        )
        decision = classify_prompt_route(prompt).to_dict()
        context = RequestContext(text=prompt, extras={"window": object()})
        request = build_dcc_execution_request(decision, context)

        self.assertEqual(request.target_type, "unreal_capability")
        self.assertEqual(request.mutation_scope, "graph_asset")
        self.assertEqual(request.target_identifier, "BP_LesterPhoenix")
        self.assertEqual(request.callable_name, "unreal_tools.graph.semantic_edit_plan")
        self.assertNotEqual(request.callable_name, "BP_LesterPhoenix")
        self.assertNotIn("callable", request.missing_slots)

    def test_read_only_graph_operation_prompt_does_not_stop_at_asset_navigation(self):
        prompt = (
            "In Unreal open BP_LesterPhoenix and report what graph operations are available "
            "for adding a temporary Print String node. Do not edit anything."
        )

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.intent_category, "unreal_semantic_graph_planning")
        self.assertEqual(decision.callable_name, "unreal_tools.graph.semantic_edit_plan")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertFalse(decision.requires_confirmation)
        self.assertNotEqual(decision.target_identifier, "navigation.open_asset")
        self.assertIn("semantic_graph_understanding", decision.required_context)

    def test_read_only_preview_adding_prompt_routes_to_graph_planning(self):
        prompt = (
            "In Unreal inspect BP_LesterPhoenix EventGraph and preview adding a temporary "
            "Print String called TC_PreviewOnly_0715 with message Preview Only. Do not edit or save."
        )

        decision = classify_prompt_route(prompt)

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.intent_category, "unreal_semantic_graph_planning")
        self.assertEqual(decision.callable_name, "unreal_tools.graph.semantic_edit_plan")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertNotEqual(decision.target_identifier, "navigation.open_asset")

    def test_read_only_graph_preview_can_use_direct_unreal_bridge_without_window(self):
        prompt = (
            "In Unreal open BP_LesterPhoenix and report what graph operations are available "
            "for adding a temporary Print String node. Do not edit anything."
        )
        decision = classify_prompt_route(prompt).to_dict()
        request = build_dcc_execution_request(decision, RequestContext(text=prompt))

        with patch("tech_connector.services.dcc.dcc_execution_service._unreal_direct_bridge_available", return_value=True):
            check = default_dcc_execution_adapters()["unreal"].check_capabilities(
                request,
                RequestContext(text=prompt),
            )

        self.assertTrue(check.ok)

    def test_graph_patch_confirmation_names_asset_and_graph(self):
        context = RequestContext(text="prompt")
        rendered = build_confirmation(
            decision={"intent_category": "unreal_semantic_graph_modification"},
            context=context,
            execution_request={"mutation_scope": "graph_asset", "risk_level": "high"},
            dispatch_result={
                "confirmation_request": {
                    "operation": "unreal_graph_patch",
                    "target_asset": "/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix",
                    "target_graph": "EventGraph",
                    "preview": {"operation_count": 1},
                    "mutation_scope": "graph_asset",
                    "risk_level": "high",
                }
            },
        )

        self.assertIn("Unreal graph patch", rendered.text)
        self.assertIn("/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix", rendered.text)
        self.assertIn("EventGraph", rendered.text)
        self.assertNotIn("execute `BP_LesterPhoenix`", rendered.text)


if __name__ == "__main__":
    unittest.main()
