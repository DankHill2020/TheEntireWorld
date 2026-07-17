from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tech_connector.bridges.unreal.unreal_blueprint_inspection import _pin_type_summary
from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.router.command_router import CommandRouter
from tech_connector.services.unreal.development_eval_service import (
    read_unreal_development_eval,
    record_unreal_development_eval,
)
from tech_connector.services.unreal.feature_planning_service import (
    _stamina_sprint_plan,
    is_approved_unreal_feature_execution_request,
    is_direct_unreal_blueprint_inspection,
    is_unreal_feature_plan_request,
)
from tech_connector.services.unreal.unreal_operation_service import (
    UNREAL_OPERATIONS,
    unreal_operation_payload,
)


class _PinType:
    def export_text(self):
        return '(PinCategory="object",PinSubCategoryObject="/Script/Engine.AnimMontage\'/Script/Engine.AnimMontage\'")'


class TestUnrealBlueprintInspection(unittest.TestCase):
    def test_blueprint_scan_uses_current_first_party_inspector(self) -> None:
        operation = UNREAL_OPERATIONS["blueprint.scan"]

        self.assertEqual(
            operation.function,
            "tech_connector.bridges.unreal.unreal_blueprint_inspection.scan_blueprint",
        )
        self.assertFalse(operation.mutates_project)

    def test_pin_type_summary_returns_reflected_object_type(self) -> None:
        self.assertEqual("/Script/Engine.AnimMontage", _pin_type_summary(_PinType()))

    def test_router_rejects_insufficient_blueprint_scan_payload(self) -> None:
        router = CommandRouter()
        payload = json.dumps(
            {
                "sufficient": False,
                "missing_sections": ["variables", "graphs"],
                "errors": ["Blueprint inspection is insufficient"],
            }
        )

        with patch.object(router.unreal, "call", return_value=(True, payload)):
            _label, ok, result = router.execute_unreal_operation(
                "blueprint.scan",
                {"asset_path": "/Game/Test/BP_Test"},
            )

        self.assertFalse(ok)
        self.assertEqual(payload, result)

    def test_dynamic_inspector_accepts_full_package_paths(self) -> None:
        source = CommandRouter()._unreal_blueprint_dynamic_inspect_code(
            "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter"
        )

        self.assertIn('package_lower = path_lower.split(".", 1)[0]', source)
        self.assertIn("package_lower, short_lower", source)

    def test_blueprint_scan_payload_preserves_read_only_defaults(self) -> None:
        payload = unreal_operation_payload(
            "blueprint.scan",
            {"asset_path": "/Game/Test/BP_Test"},
        )

        self.assertEqual([], payload["args"])
        self.assertEqual(
            {
                "include_graphs": True,
                "include_defaults": True,
                "asset_path": "/Game/Test/BP_Test",
            },
            payload["kwargs"],
        )
        self.assertFalse(payload["mutates_project"])

    def test_feature_plan_detection_keeps_unreal_asset_work_out_of_source_search(self) -> None:
        prompt = (
            "In Unreal add a stamina and sprint system to BP_ThirdPersonCharacter. "
            "Give me the implementation plan for approval and do not edit yet."
        )

        self.assertTrue(is_unreal_feature_plan_request(prompt))
        self.assertFalse(is_direct_unreal_blueprint_inspection(prompt))

    def test_stamina_plan_uses_registered_input_operations_without_gaps(self) -> None:
        evidence = {
            "sufficient": True,
            "target_asset": "/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter",
            "blueprint": {
                "parent_class": "Character",
                "variables": [],
                "functions": [],
                "graphs": [{"name": "EventGraph"}],
                "components": [],
                "defaults": {"movement": {"max_walk_speed": 600.0}},
            },
            "animation_blueprints": [],
            "assets": {
                "input_actions": [],
                "input_mapping_contexts": [
                    {"name": "IMC_Default", "path": "/Game/Input/IMC_Default"}
                ],
            },
        }

        plan = _stamina_sprint_plan("stamina sprint", evidence)

        self.assertEqual([], plan["missing_capabilities"])
        self.assertIn("input.create_action", UNREAL_OPERATIONS)
        self.assertIn("input.add_mapping", UNREAL_OPERATIONS)
        self.assertFalse(plan["approval_gate"]["changes_applied"])
        self.assertFalse(plan["self_review"]["fabricated_operations"])

    def test_request_engine_feature_fast_path_skips_semantic_planning(self) -> None:
        prompt = (
            "In Unreal add a stamina and sprint system to BP_ThirdPersonCharacter. "
            "Give me the implementation plan for approval and do not edit yet."
        )
        fake_plan = {
            "status": "approval_ready",
            "target_asset": "/Game/Test/BP_Test",
            "bridge_seconds": 0.2,
            "evidence": {"movement_defaults": {}, "sprint_action_exists": False},
            "affected_assets": [],
            "implementation_steps": [],
            "missing_capabilities": [],
            "validation": [],
            "rollback": [],
        }

        with patch(
            "tech_connector.services.unreal.feature_planning_service.build_live_unreal_feature_plan",
            return_value=fake_plan,
        ), patch(
            "tech_connector.services.unreal.development_eval_service.record_unreal_development_eval",
        ), patch(
            "tech_connector.services.prompt_execution_context_service.build_prompt_execution_context",
            side_effect=AssertionError("fast Unreal plan must not invoke semantic planning"),
        ):
            result = RequestEngine().process(RequestContext(prompt))

        self.assertEqual("clarify", result.action)
        self.assertEqual("unreal_feature_plan_approval", result.metadata["result_type"])
        self.assertEqual("unreal_capability", result.metadata["route_decision"]["route"])

    def test_approval_is_bound_to_prior_unreal_feature_plan(self) -> None:
        prior = {
            "result_type": "unreal_feature_plan_approval",
            "plan": {"status": "approval_ready", "feature": "stamina_sprint"},
        }

        self.assertTrue(is_approved_unreal_feature_execution_request("Approved, execute it", prior))
        self.assertFalse(is_approved_unreal_feature_execution_request("Approved, execute it", {}))

    def test_request_engine_resumes_approved_unreal_plan_without_semantic_reroute(self) -> None:
        prior = {
            "result_type": "unreal_feature_plan_approval",
            "plan": {"status": "approval_ready", "feature": "stamina_sprint"},
        }
        completed = {
            "status": "completed",
            "feature": "stamina_sprint",
            "results": [],
            "validation": {"compile_ok": True, "layout_ok": True, "input_mappings_ok": True},
        }
        context = RequestContext(
            "Approved, execute the stamina sprint plan",
            extras={"prior_result_metadata": prior},
        )

        with patch(
            "tech_connector.services.unreal.feature_planning_service.execute_approved_unreal_feature_plan",
            return_value=completed,
        ), patch(
            "tech_connector.services.prompt_execution_context_service.build_prompt_execution_context",
            side_effect=AssertionError("approved Unreal continuation must not reroute semantically"),
        ):
            result = RequestEngine().process(context)

        self.assertEqual("answer", result.action)
        self.assertEqual("unreal_feature_execution_completed", result.metadata["result_type"])
        self.assertEqual("unreal_live_bridge_approved_execution", result.metadata["engine_path"])

    def test_unreal_development_eval_ledger_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unreal_eval.jsonl"
            record_unreal_development_eval(
                case="blueprint_scan",
                stage="inspection",
                status="failed",
                issue="false success",
                evidence={"engine": "5.8"},
                remediation="use supported reflection",
                log_path=path,
            )

            rows = read_unreal_development_eval(log_path=path)

        self.assertEqual(1, len(rows))
        self.assertEqual("false success", rows[0]["issue"])
        self.assertEqual("5.8", rows[0]["evidence"]["engine"])


if __name__ == "__main__":
    unittest.main()
