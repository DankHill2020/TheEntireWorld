import unittest

from tech_connector.services.action_execution_engine import (
    ACTION_STATUS_AWAITING_CONFIRMATION,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_SUCCEEDED,
    FAILURE_CONFIRMATION,
    FAILURE_EXECUTION,
    FAILURE_OUTCOME,
    FAILURE_VALIDATION,
    ActionExecutionEngine,
    ActionHandler,
    ActionHandlerRegistry,
    ExecutionContext,
)


class TestActionExecutionSupervisor(unittest.TestCase):
    def _engine(self, handler: ActionHandler) -> ActionExecutionEngine:
        registry = ActionHandlerRegistry()
        registry.register(handler)
        return ActionExecutionEngine(registry)

    def test_successful_action_executes_once_and_does_not_repair(self):
        calls = {"execute": 0, "repair": 0}

        def execute(action, context):
            calls["execute"] += 1
            return {"ok": True, "stdout": "created target", "observed_outcome": {"created": True}}

        def repair(action, result, context):
            calls["repair"] += 1
            return {"ok": True}

        engine = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair))
        result = engine.execute_action(
            {"type": "validate", "id": "a1", "expected_outcomes": [{"path": "observed_outcome.created", "equals": True}]},
            ExecutionContext(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(ACTION_STATUS_SUCCEEDED, result["status"])
        self.assertEqual(1, calls["execute"])
        self.assertEqual(0, calls["repair"])

    def test_execution_failure_is_classified_repaired_retried_and_succeeds(self):
        calls = {"execute": 0}

        def execute(action, context):
            calls["execute"] += 1
            if not action["args"].get("fixed"):
                return {"ok": False, "stderr": "NameError: missing_symbol", "retryable": True}
            return {"ok": True, "stdout": "fixed"}

        def repair(action, result, context):
            self.assertEqual(FAILURE_EXECUTION, result.failure_category)
            return {"ok": True, "summary": "Use resolved symbol.", "args": {"fixed": True}}

        engine = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair))
        result = engine.execute_action(
            {"type": "validate", "id": "a1", "args": {}, "max_retries": 1},
            ExecutionContext(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["retry_count"])
        self.assertEqual(2, calls["execute"])

    def test_default_failure_path_produces_repair_plan_without_blind_retry(self):
        calls = {"execute": 0}

        def execute(action, context):
            calls["execute"] += 1
            return {"ok": False, "stderr": "NameError: missing_symbol", "retryable": True}

        engine = self._engine(ActionHandler("validate", "test", execute_fn=execute))
        result = engine.execute_action(
            {"type": "validate", "id": "a1", "max_retries": 2},
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(1, calls["execute"])
        self.assertEqual("repair_code_or_api_usage", result["repair_plan"]["kind"])
        self.assertTrue(result["repair_plan"]["requires_model_escalation"])
        self.assertGreaterEqual(len(result["repair_plan"]["steps"]), 3)

    def test_validation_failure_repairs_then_passes(self):
        calls = {"execute": 0}

        def execute(action, context):
            calls["execute"] += 1
            if calls["execute"] == 1:
                return {"ok": True, "validation_results": [{"name": "compile", "passed": False, "errors": ["SyntaxError"]}]}
            return {"ok": True, "validation_results": [{"name": "compile", "passed": True}]}

        def repair(action, result, context):
            self.assertEqual(FAILURE_VALIDATION, result.failure_category)
            return {"ok": True, "summary": "Repair syntax."}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_action(
            {"type": "validate", "id": "a1", "max_retries": 1},
            ExecutionContext(),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(2, calls["execute"])

    def test_outcome_failure_is_not_reported_complete(self):
        def execute(action, context):
            return {"ok": True, "stdout": "tests passed", "observed_outcome": {"registered": False}}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {
                "type": "validate",
                "id": "a1",
                "expected_outcomes": [{"name": "helper registered", "path": "observed_outcome.registered", "equals": True}],
                "max_retries": 0,
            },
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_OUTCOME, result["failure_category"])
        self.assertEqual(ACTION_STATUS_BLOCKED, result["status"])

    def test_retry_exhaustion_preserves_blocker(self):
        def execute(action, context):
            return {"ok": False, "stderr": "IndexError: chain member missing", "retryable": True}

        def repair(action, result, context):
            return {"ok": True, "summary": "Tried guard."}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_action(
            {"type": "validate", "id": "a1", "max_retries": 1},
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(1, result["retry_count"])
        self.assertIn("IndexError", result["error"])

    def test_non_retryable_failure_stops_immediately(self):
        calls = {"execute": 0, "repair": 0}

        def execute(action, context):
            calls["execute"] += 1
            return {"ok": False, "status": "capability_gap", "error": "No callable matched.", "retryable": False}

        def repair(action, result, context):
            calls["repair"] += 1
            return {"ok": True}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_action(
            {"type": "validate", "id": "a1", "max_retries": 3},
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(1, calls["execute"])
        self.assertEqual(0, calls["repair"])

    def test_confirmation_required_action_is_not_retried(self):
        def execute(action, context):
            return {"ok": True, "status": "confirmation_required", "requires_confirmation": True}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {"type": "validate", "id": "a1", "max_retries": 3, "requires_confirmation": True},
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_CONFIRMATION, result["failure_category"])
        self.assertEqual(ACTION_STATUS_AWAITING_CONFIRMATION, result["status"])

    def test_action_graph_recovery_does_not_rerun_valid_independent_nodes(self):
        calls = {"first": 0, "second": 0}

        def execute(action, context):
            if action["id"] == "first":
                calls["first"] += 1
                return {"ok": True}
            calls["second"] += 1
            return {"ok": False, "stderr": "temporary failure", "retryable": True}

        def repair(action, result, context):
            return {"ok": True}

        plan = {
            "goal": "exercise graph recovery",
            "intent": "test",
            "actions": [
                {"type": "validate", "id": "first"},
                {"type": "validate", "id": "second", "max_retries": 1},
            ],
        }
        report = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_plan(plan, ExecutionContext())

        self.assertEqual("partial_failure", report["status"])
        self.assertEqual(1, calls["first"])
        self.assertEqual(2, calls["second"])

    def test_maya_style_successful_command_missing_node_is_outcome_failure(self):
        def execute(action, context):
            return {"ok": True, "result": {"maya_command_executed": True, "nodes": []}}

        result = self._engine(ActionHandler("execute_dcc", "maya-test", mutability="dcc_mutation", execute_fn=execute)).execute_action(
            {
                "type": "execute_dcc",
                "id": "maya",
                "expected_outcomes": [{"name": "locator exists", "path": "result.nodes", "contains": "prompt_smoke_locator"}],
                "max_retries": 0,
            },
            ExecutionContext(approved=True),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_OUTCOME, result["failure_category"])

    def test_maya_script_editor_traceback_inside_raw_result_is_execution_failure(self):
        raw = (
            "STDOUT:\nbefore maya failure\n\n"
            "STDERR:\nTraceback (most recent call last):\n"
            "RuntimeError: AI_STUDIO_MAYA_SMOKE_ERROR"
        )

        def execute(action, context):
            return {
                "ok": True,
                "status": "completed",
                "result": {"raw_result": raw},
                "raw_result": raw,
            }

        result = self._engine(ActionHandler("execute_dcc", "maya-test", mutability="dcc_mutation", execute_fn=execute)).execute_action(
            {"type": "execute_dcc", "id": "maya_error", "max_retries": 0},
            ExecutionContext(approved=True),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_EXECUTION, result["failure_category"])
        self.assertIn("AI_STUDIO_MAYA_SMOKE_ERROR", result["stderr"])

    def test_unreal_style_compile_success_missing_graph_state_is_outcome_failure(self):
        def execute(action, context):
            return {"ok": True, "result": {"compiled": True, "nodes": ["EventGraph"]}}

        result = self._engine(ActionHandler("execute_unreal_python", "unreal-test", mutability="dcc_mutation", execute_fn=execute)).execute_action(
            {
                "type": "execute_unreal_python",
                "id": "unreal",
                "expected_outcomes": [{"name": "Print String node added", "path": "result.nodes", "contains": "PrintString"}],
                "max_retries": 0,
            },
            ExecutionContext(approved=True),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_OUTCOME, result["failure_category"])

    def test_repair_attempts_can_escalate_model_tiers_before_exhaustion(self):
        calls = {"execute": 0, "tiers": []}

        class Escalator:
            def escalate_action(self, action, result, next_tier, context):
                calls["tiers"].append(next_tier)
                return {
                    "ok": True,
                    "summary": f"Use {next_tier} repair planning.",
                    "model_tier": next_tier,
                    "args": {"fixed_by_strong_model": True},
                }

        def execute(action, context):
            calls["execute"] += 1
            if action["args"].get("fixed_by_strong_model"):
                return {"ok": True, "stdout": "strong repair passed"}
            return {"ok": False, "stderr": "ambiguous coding failure", "retryable": True}

        def repair(action, result, context):
            return {"ok": True, "summary": f"Repair on {result.model_tier or 'deterministic'} tier."}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_action(
            {
                "type": "validate",
                "id": "a1",
                "max_retries": 3,
                "model_tiers": ["small", "strong"],
                "repairs_per_model_tier": 1,
            },
            ExecutionContext(services={"model_escalation": Escalator()}),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["strong"], calls["tiers"])
        self.assertEqual("strong", result["model_tier"])
        self.assertGreaterEqual(calls["execute"], 2)

    def test_major_outcome_failure_escalates_without_minor_tier_repair(self):
        calls = {"repair": 0, "tiers": []}

        class Escalator:
            def escalate_action(self, action, result, next_tier, context):
                calls["tiers"].append(next_tier)
                return {"ok": True, "model_tier": next_tier, "args": {"strong": True}}

        def execute(action, context):
            if action["args"].get("strong"):
                return {"ok": True, "result": {"registered": True}}
            return {"ok": True, "result": {"registered": False}}

        def repair(action, result, context):
            calls["repair"] += 1
            return {"ok": True}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute, repair_fn=repair)).execute_action(
            {
                "type": "validate",
                "id": "a1",
                "max_retries": 2,
                "model_tiers": ["small", "strong"],
                "repairs_per_model_tier": 2,
                "expected_outcomes": [{"path": "result.registered", "equals": True}],
            },
            ExecutionContext(services={"model_escalation": Escalator()}),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["strong"], calls["tiers"])
        self.assertEqual(0, calls["repair"])

    def test_runtime_registry_accepts_custom_user_runnable_action_types(self):
        calls = {"execute": 0}

        def execute(action, context):
            calls["execute"] += 1
            return {"ok": True, "observed_outcome": {"compiled": True}}

        registry = ActionHandlerRegistry()
        registry.register(ActionHandler("coding_py_compile", "user-runnable coding smoke", execute_fn=execute))
        engine = ActionExecutionEngine(registry)
        plan = {
            "goal": "run a user-provided coding check",
            "intent": "validate",
            "actions": [
                {
                    "type": "coding_py_compile",
                    "id": "compile_check",
                    "expected_outcomes": [{"path": "observed_outcome.compiled", "equals": True}],
                }
            ],
        }

        validation = engine.validate_plan(plan)
        self.assertTrue(validation["valid"], validation["errors"])

        report = engine.execute_plan(plan, ExecutionContext())
        self.assertEqual("completed", report["status"])
        self.assertEqual(1, calls["execute"])


if __name__ == "__main__":
    unittest.main()
