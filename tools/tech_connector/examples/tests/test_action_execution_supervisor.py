import unittest

from tech_connector.services.action_execution_engine import (
    ACTION_STATUS_AWAITING_CONFIRMATION,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_SUCCEEDED,
    FAILURE_CONFIRMATION,
    FAILURE_DEPENDENCY,
    FAILURE_ENVIRONMENT,
    FAILURE_EXECUTION,
    FAILURE_OUTCOME,
    FAILURE_PERMISSION,
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

    def test_falsey_bare_handler_results_are_successful_outputs(self):
        for index, value in enumerate((False, 0, "", [])):
            with self.subTest(value=value):
                result = self._engine(
                    ActionHandler(
                        "validate",
                        "falsey-test",
                        execute_fn=lambda action, context, output=value: output,
                    )
                ).execute_action(
                    {
                        "type": "validate",
                        "id": f"falsey_{index}",
                        "expected_outcomes": [
                            {"path": "output", "equals": value},
                        ],
                    },
                    ExecutionContext(),
                )

                self.assertTrue(result["ok"], result)

    def test_implicit_result_contract_detects_failure_evidence(self):
        failures = (
            {"error": "boom"},
            {"status": "failed"},
            {"exit_code": 7, "output": "command stopped"},
            {"exception_type": "RuntimeError"},
        )
        for index, raw in enumerate(failures):
            with self.subTest(raw=raw):
                result = self._engine(
                    ActionHandler(
                        "validate",
                        "implicit-contract-test",
                        execute_fn=lambda action, context, value=raw: dict(value),
                    )
                ).execute_action(
                    {
                        "type": "validate",
                        "id": f"implicit_failure_{index}",
                        "max_retries": 0,
                    },
                    ExecutionContext(),
                )

                self.assertFalse(result["ok"], result)
                self.assertEqual(FAILURE_EXECUTION, result["failure_category"])

    def test_explicit_success_cannot_hide_nonempty_error(self):
        def execute(action, context):
            return {"ok": True, "error": "boom"}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {"type": "validate", "id": "contradictory", "max_retries": 0},
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_EXECUTION, result["failure_category"])
        self.assertEqual("boom", result["diagnosis"])

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

    def test_falsey_outcomes_can_exist_without_being_truthy(self):
        def execute(action, context):
            return {
                "ok": True,
                "result": {"disabled": False, "count": 0, "value": None},
            }

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {
                "type": "validate",
                "id": "falsey_exists",
                "expected_outcomes": [
                    {"path": "result.disabled", "exists": True},
                    {"path": "result.count", "exists": True},
                    {"path": "result.value", "exists": True},
                    {"path": "result.missing", "exists": False},
                ],
            },
            ExecutionContext(),
        )

        self.assertTrue(result["ok"], result)

    def test_missing_list_index_is_outcome_failure_instead_of_crashing(self):
        def execute(action, context):
            return {"ok": True, "result": {"items": []}}

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {
                "type": "validate",
                "id": "missing_index",
                "max_retries": 0,
                "expected_outcomes": [
                    {"name": "first item", "path": "result.items.0", "exists": True},
                ],
            },
            ExecutionContext(),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(FAILURE_OUTCOME, result["failure_category"])
        self.assertIn("first item", result["diagnosis"])
        self.assertIn("observed None", result["diagnosis"])

    def test_hostname_attribute_error_is_not_misclassified_as_environment(self):
        def execute(action, context):
            return {
                "ok": False,
                "error": "AttributeError: Config object has no attribute 'hostname'",
                "retryable": True,
            }

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {"type": "validate", "id": "hostname", "max_retries": 0},
            ExecutionContext(),
        )

        self.assertEqual(FAILURE_EXECUTION, result["failure_category"])
        self.assertEqual("repair_code_or_api_usage", result["repair_plan"]["kind"])

    def test_exception_type_alone_drives_dependency_and_syntax_diagnosis(self):
        dependency = self._engine(
            ActionHandler(
                "validate",
                "dependency-test",
                execute_fn=lambda action, context: {
                    "ok": False,
                    "exception_type": "ModuleNotFoundError",
                    "retryable": True,
                },
            )
        ).execute_action(
            {"type": "validate", "id": "dependency", "max_retries": 0},
            ExecutionContext(),
        )
        syntax = self._engine(
            ActionHandler(
                "validate",
                "syntax-test",
                execute_fn=lambda action, context: {
                    "ok": False,
                    "exception_type": "SyntaxError",
                    "retryable": True,
                },
            )
        ).execute_action(
            {"type": "validate", "id": "syntax", "max_retries": 0},
            ExecutionContext(),
        )

        self.assertEqual(FAILURE_DEPENDENCY, dependency["failure_category"])
        self.assertIn("ModuleNotFoundError", dependency["diagnosis"])
        self.assertEqual("repair_code_syntax", syntax["repair_plan"]["kind"])

    def test_environment_diagnosis_preserves_concrete_connection_error(self):
        def execute(action, context):
            return {
                "ok": False,
                "error": "Maya bridge unavailable at 127.0.0.1:7001",
                "retryable": True,
            }

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {"type": "validate", "id": "bridge", "max_retries": 0},
            ExecutionContext(),
        )

        self.assertEqual(FAILURE_ENVIRONMENT, result["failure_category"])
        self.assertIn("127.0.0.1:7001", result["diagnosis"])

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
        self.assertEqual("report_non_retryable_gap", result["repair_plan"]["kind"])
        self.assertFalse(result["repair_plan"]["requires_model_escalation"])

    def test_permission_failure_does_not_propose_automatic_code_repair(self):
        def execute(action, context):
            return {
                "ok": False,
                "exception_type": "PermissionError",
                "exception_message": "Access denied: C:/protected/config.json",
            }

        result = self._engine(ActionHandler("validate", "test", execute_fn=execute)).execute_action(
            {"type": "validate", "id": "permission", "max_retries": 3},
            ExecutionContext(),
        )

        self.assertEqual(FAILURE_PERMISSION, result["failure_category"])
        self.assertEqual("resolve_permission_boundary", result["repair_plan"]["kind"])
        self.assertFalse(result["repair_plan"]["requires_model_escalation"])
        self.assertFalse(result["retryable"])
        self.assertIn("C:/protected/config.json", result["diagnosis"])

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
