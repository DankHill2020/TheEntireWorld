from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.services.change_history_service import load_change_session, undo_change_session
from tech_connector.services.project_edit_agent_service import (
    apply_project_edit_agent_response,
    apply_project_edit_syntax_repair,
    build_code_agent_adaptive_plan,
    build_project_edit_agent_request,
    build_project_edit_leaf_candidate,
    build_project_edit_leaf_stage,
    build_project_edit_plan_from_leaf_work_units,
    build_project_edit_model_stages,
    build_project_edit_repair_stage,
    build_project_edit_syntax_repair_stage,
    compile_project_edit_leaf_work_units,
    inspect_project_edit_structured_syntax,
    model_for_project_edit_stage,
    parse_project_edit_leaf_source,
    ProjectEditPlan,
    preview_project_edit_agent_response,
    project_edit_plan_fingerprint,
    project_edit_leaf_work_units_handoff,
    project_edit_has_core_contract_failure,
    project_edit_preview_error_score,
    render_code_agent_expert_context,
    render_code_agent_adaptive_plan,
    render_grounded_project_edit_handoff,
    restore_project_edit_leaf_work_units,
    select_code_agent_experts,
    render_project_edit_agent_report,
    validate_project_edit_plan_output,
    validate_project_edit_paths,
)
from tech_connector.services.project_service import discover_edit_targets, format_edit_target_context, build_project_edit_target_prompt


class TestProjectEditAgentService(unittest.TestCase):
    ACTIVE_UI_FILE = "C:/depot/tools/custom_qt/custom_widgets.py"

    def test_explicit_active_edit_reuses_index_snapshot_without_deep_intelligence(self) -> None:
        active = str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py")
        snapshot = {
            "path": active,
            "root": str(Path(active).parents[1]),
            "sha1": "a" * 40,
            "symbols": [{
                "kind": "function",
                "name": "preview_project_edit_agent_response",
                "qualname": "preview_project_edit_agent_response",
                "start_line": 100,
                "end_line": 120,
                "source": "def preview_project_edit_agent_response():\n    return None",
            }],
        }
        with patch(
            "tech_connector.services.file_index_service.file_index_service.get_file_snapshot",
            return_value=snapshot,
        ), patch(
            "tech_connector.services.project_edit_agent_service._build_project_edit_intelligence_packet"
        ) as deep_intelligence:
            plan = build_project_edit_agent_request(
                "In project_edit_agent_service.py, update the preview function and add focused tests.",
                active_path=active,
            )

        deep_intelligence.assert_not_called()
        self.assertEqual("explicit_index_snapshot", plan.discovery["evidence_mode"])
        self.assertEqual("reuse_target_discovery", plan.intelligence_packet["mode"])
        self.assertEqual("a" * 40, plan.discovery["index_revision"])

    def test_build_project_edit_agent_request_includes_adaptive_success_contract(self) -> None:
        plan = build_project_edit_agent_request(
            "Add missing docstrings to rig helper functions",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        self.assertIn("adaptive_planning", [stage["key"] for stage in plan.stages])
        self.assertIn("code_intelligence", [stage["key"] for stage in plan.stages])
        self.assertIn("expert_selection", [stage["key"] for stage in plan.stages])
        self.assertEqual("adaptive_code_agent_v1", plan.adaptive_plan["framework"])
        self.assertTrue(plan.intelligence_packet)
        self.assertTrue(plan.domain_experts)
        self.assertTrue(plan.success_contract)
        self.assertIn("Adaptive code agent execution plan:", plan.model_prompt)
        self.assertIn("Code intelligence packet:", plan.model_prompt)
        self.assertIn("Deterministic IDE-agent steps before model synthesis:", plan.model_prompt)
        self.assertIn("Code/domain expert advisory context:", plan.model_prompt)
        self.assertIn("Reuse existing project functions, classes, services, and helpers", plan.model_prompt)
        self.assertIn("validate, repair, and report", plan.model_prompt)

    def test_project_edit_model_stages_split_plan_and_patch_generation(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and build a UI around it.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        stages = build_project_edit_model_stages(plan)

        self.assertEqual(["target_selection_plan", "patch_generation"], [stage.key for stage in stages])
        self.assertIn("Do not emit XML patches", stages[0].user_prompt)
        self.assertIn("approval-ready implementation plan", stages[0].user_prompt)
        self.assertIn('"changes": [', stages[1].user_prompt)
        self.assertEqual("object", stages[1].response_format["type"])
        self.assertIn("new_content", stages[1].response_format["properties"]["changes"]["items"]["required"])
        self.assertIn("replace_symbol", stages[1].response_format["properties"]["changes"]["items"]["properties"]["action"]["enum"])
        self.assertIn("insert_after_symbol", stages[1].response_format["properties"]["changes"]["items"]["properties"]["action"]["enum"])
        self.assertLessEqual(len(stages[0].user_prompt), 7000)
        self.assertLessEqual(len(stages[1].user_prompt), 12000)
        self.assertEqual("local_model_serial", stages[0].resource_lane)
        self.assertEqual(4096, stages[0].num_ctx)
        self.assertEqual("local_plan", stages[0].model_tier)
        self.assertFalse(stages[0].prefer_coder)
        self.assertEqual("local_code", stages[1].model_tier)
        self.assertTrue(stages[1].prefer_coder)
        self.assertEqual("micro", stages[1].coder_preference)

    def test_project_edit_model_stages_skip_patch_for_plan_only_request(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and explain how you would build a UI around it. Do not edit anything.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )

        stages = build_project_edit_model_stages(plan)

        self.assertEqual(["target_selection_plan"], [stage.key for stage in stages])
        self.assertNotIn("<modify_file path=", stages[0].user_prompt)

    def test_project_edit_stage_models_reuse_existing_router_settings(self) -> None:
        plan = build_project_edit_agent_request(
            "Find a Maya rigging function and build a UI around it.",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
        )
        stages = build_project_edit_model_stages(plan)
        settings = {
            "router_local_plan": "qwen3:8b",
            "router_local_code_micro": "qwen2.5-coder:1.5b",
            "model": "ollama:qwen3:14b",
        }

        self.assertEqual("qwen3:8b", model_for_project_edit_stage(stages[0], settings))
        self.assertEqual("qwen2.5-coder:1.5b", model_for_project_edit_stage(stages[1], settings))

    def test_project_edit_plan_output_requires_target_and_verification_evidence(self) -> None:
        plan = build_project_edit_agent_request(
            "Add a helper and focused tests in the project edit service.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        valid = """Intent: implement the requested helper.
Best target: project_edit_agent_service.py based on the active file and indexed service symbols.
Reuse preview_project_edit_agent_response and the existing validation helpers rather than duplicating them.
Generate a focused patch, then compile the module, verify imports, and run focused unittest tests.
Block if the target signature or required call site cannot be established from project evidence.
Plan self-check: target, test scope, and verification all match the objective.
"""

        self.assertEqual([], validate_project_edit_plan_output(plan, valid))

    def test_project_edit_plan_output_rejects_detached_code_and_renders_grounded_fallback(self) -> None:
        plan = build_project_edit_agent_request(
            "Add a helper and focused tests in the project edit service.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        detached = """Here is the implementation:
```python
class ReplacementEditor:
    def run(self):
        return True
```
This should solve the request without any other changes or tests.
"""

        errors = validate_project_edit_plan_output(plan, detached)
        fallback = render_grounded_project_edit_handoff(plan, rejected_plan_errors=errors)

        self.assertTrue(any("implementation code" in error for error in errors))
        self.assertTrue(any("target file" in error for error in errors))
        self.assertTrue(any("indexed existing symbol" in error for error in errors))
        self.assertIn("project_edit_agent_service.py", fallback)
        self.assertIn("Completion gates:", fallback)

    def test_project_edit_patch_stage_includes_exact_source_and_preview_contract(self) -> None:
        plan = build_project_edit_agent_request(
            "Add summarize_validation_failures and reuse it for validation errors. Preview only; do not apply changes.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )

        patch_stage = build_project_edit_model_stages(plan)[1]

        self.assertIn("Focused exact source excerpts:", patch_stage.user_prompt)
        self.assertIn("def render_project_edit_agent_report", patch_stage.user_prompt)
        self.assertIn("A preview still requires a complete structured change payload", patch_stage.user_prompt)
        self.assertLessEqual(len(patch_stage.user_prompt), 13000)

    def test_project_edit_repairs_refine_context_and_escalate_one_tier_at_a_time(self) -> None:
        plan = build_project_edit_agent_request(
            "Add summarize_validation_failures and focused tests.",
            active_path=str(Path(__file__).parents[1] / "services" / "project_edit_agent_service.py"),
        )
        candidate = "<modify_file path=\"service.py\">\ninvalid candidate\n</modify_file>"
        stages = [
            build_project_edit_repair_stage(
                plan,
                candidate,
                ["Generated Python did not parse."],
                attempt=attempt,
                approved_plan="Approved plan: update the service and focused tests.",
            )
            for attempt in (1, 2, 3, 4, 5)
        ]

        self.assertEqual(["small", "standard", "standard", "standard", "standard"], [stage.coder_preference for stage in stages])
        self.assertEqual([105, 135, 135, 135, 135], [stage.timeout for stage in stages])
        self.assertTrue(all("Focus only on the listed failures" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Current exact source excerpts:" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Approved plan: update the service" in stage.user_prompt for stage in stages))
        self.assertTrue(all("Syntax reset:" in stage.user_prompt for stage in stages))
        self.assertTrue(all(stage.timeout < 300 for stage in stages))

        implementation_reset = build_project_edit_repair_stage(
            plan,
            candidate,
            ["Candidate did not implement requested public symbols: summarize_validation_failures"],
            attempt=1,
            approved_plan="Approved plan: define and reuse the helper with tests.",
        )
        self.assertIn("Implementation reset:", implementation_reset.user_prompt)
        self.assertIn("Never import", implementation_reset.user_prompt)
        self.assertNotIn("invalid candidate", implementation_reset.user_prompt)

        completion_focus = build_project_edit_repair_stage(
            plan,
            candidate,
            ["New public callables need useful docstrings: summarize_validation_failures"],
            attempt=3,
            approved_plan="Approved plan: define and reuse the helper with tests.",
        )
        self.assertIn("Completion focus:", completion_focus.user_prompt)

    def test_project_edit_candidate_scoring_prefers_missing_docs_and_tests_over_invalid_code(self) -> None:
        nearly_complete = project_edit_preview_error_score(
            [
                "New public callables need useful docstrings: summarize_validation_failures",
                "Behavior-changing tool work must add or update a focused test file before preview approval.",
            ]
        )
        malformed = project_edit_preview_error_score(
            ["Structured change JSON did not parse: Unterminated string starting at line 8."]
        )

        self.assertLess(nearly_complete, malformed)

    def test_project_edit_core_failure_recognizes_new_symbol_used_as_replace_target(self) -> None:
        prompt = "Add a function named summarize_validation_failures with focused tests."

        self.assertTrue(project_edit_has_core_contract_failure(
            ["Indexed Python symbol was not found: summarize_validation_failures in service.py"],
            prompt,
        ))
        self.assertFalse(project_edit_has_core_contract_failure(
            ["Indexed Python symbol was not found: unrelated_existing_helper in service.py"],
            prompt,
        ))

    def test_project_edit_preview_accepts_structured_json_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "values.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": str(source),
                            "original_content": "VALUE = 1\n",
                            "new_content": "VALUE = 2\n",
                        }
                    ],
                    "report": {"changed": ["VALUE"], "verification": ["compile"]},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok)
            self.assertEqual("VALUE = 2\n", preview.changes[0]["after"])
            self.assertEqual("VALUE = 1\n", source.read_text(encoding="utf-8"))

    def test_project_edit_preview_resolves_nested_symbol_replacement_with_ast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                "class Example:\n"
                "    def value(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "replace_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def value(self):\n    return 2",
                        }
                    ],
                    "report": {"changed": ["Example.value"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok)
            self.assertIn("    def value(self):\n        return 2", preview.changes[0]["after"])

    def test_project_edit_preview_composes_symbol_operations_on_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                "def value():\n"
                "    return 1\n",
                encoding="utf-8",
            )
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "insert_before_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def helper():\n    \"\"\"Return the replacement value.\"\"\"\n    return 2",
                        },
                        {
                            "action": "replace_symbol",
                            "path": str(source),
                            "target_symbol": "value",
                            "original_content": "",
                            "new_content": "def value():\n    return helper()",
                        },
                    ],
                    "report": {"changed": ["helper", "value"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(1, len(preview.changes))
            self.assertIn("def helper():\n    \"\"\"Return the replacement value.\"\"\"\n    return 2", preview.changes[0]["after"])
            self.assertIn("def value():\n    return helper()", preview.changes[0]["after"])

    def test_project_edit_leaf_workers_compile_evidence_and_compose_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "service.py"
            tests_dir = root / "tests"
            tests_dir.mkdir()
            test_path = tests_dir / "test_service.py"
            target_before = (
                "def render_errors(results):\n"
                "    \"\"\"Render validation errors.\"\"\"\n"
                "    return [str(item.get('message', '')) for item in results if not item.get('ok')]\n"
            )
            test_before = (
                "import unittest\n\n"
                "from service import render_errors\n\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_render_errors(self):\n"
                "        self.assertEqual(['bad'], render_errors([{'ok': False, 'message': 'bad'}]))\n"
            )
            target.write_text(target_before, encoding="utf-8")
            test_path.write_text(test_before, encoding="utf-8")
            objective = (
                "In service.py, add a reusable function named summarize_validation_failures that accepts "
                "validation result dictionaries and returns concise failure lines. Reuse it in render_errors "
                "and add focused unittest coverage."
            )
            plan = ProjectEditPlan(
                prompt=objective,
                discovery={
                    "best_target": {"path": str(target)},
                    "project_roots": [str(root)],
                },
                discovery_context="",
                model_prompt="",
                active_path=str(target),
            )
            approved = (
                "Implement summarize_validation_failures in service.py and integrate it into the selected renderer. "
                "Extend TestService.test_render_errors in tests/test_service.py. Verify imports and unittest."
            )

            snapshots = {
                str(target.resolve()).lower(): {
                    "path": str(target.resolve()),
                    "root": str(root.resolve()),
                    "sha1": hashlib.sha1(target.read_bytes()).hexdigest(),
                    "symbols": [{
                        "kind": "function",
                        "name": "render_errors",
                        "qualname": "render_errors",
                        "source": target_before,
                    }],
                },
                str(test_path.resolve()).lower(): {
                    "path": str(test_path.resolve()),
                    "root": str(root.resolve()),
                    "sha1": hashlib.sha1(test_path.read_bytes()).hexdigest(),
                    "symbols": [{
                        "kind": "method",
                        "name": "test_render_errors",
                        "qualname": "TestService.test_render_errors",
                        "source": (
                            "def test_render_errors(self):\n"
                            "    self.assertEqual(['bad'], render_errors([{'ok': False, 'message': 'bad'}]))"
                        ),
                    }],
                },
            }
            with patch(
                "tech_connector.services.file_index_service.file_index_service.get_file_snapshot",
                side_effect=lambda value, **_kwargs: snapshots.get(str(Path(value).resolve()).lower()),
            ):
                work_units = compile_project_edit_leaf_work_units(plan, approved)

            self.assertIsNotNone(work_units)
            assert work_units is not None
            self.assertEqual("render_errors", work_units.integration_symbol)
            self.assertEqual("TestService.test_render_errors", work_units.test_anchor_symbol)
            self.assertEqual("service", work_units.owner_module)
            self.assertEqual("micro", build_project_edit_leaf_stage(
                work_units,
                kind="define",
                attempt=1,
                objective=objective,
                approved_plan=approved,
            ).coder_preference)
            self.assertEqual("small", build_project_edit_leaf_stage(
                work_units,
                kind="integrate",
                attempt=1,
                objective=objective,
                approved_plan=approved,
            ).coder_preference)

            helper_source, helper_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def summarize_validation_failures(results: list[dict]) -> list[str]:\n"
                        "    \"\"\"Return messages from failed validation results.\"\"\"\n"
                        "    return [str(item.get('message', 'Validation failed.')) for item in results "
                        "if not item.get('ok')]"
                    )
                }),
                kind="define",
                expected_symbol="summarize_validation_failures",
                objective=objective,
            )
            integration_source, integration_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def render_errors(results):\n"
                        "    \"\"\"Render validation errors.\"\"\"\n"
                        "    return summarize_validation_failures(results)"
                    )
                }),
                kind="integrate",
                expected_symbol="render_errors",
                required_reference="summarize_validation_failures",
                objective=objective,
            )
            test_source, test_errors = parse_project_edit_leaf_source(
                json.dumps({
                    "source": (
                        "def test_summarize_validation_failures(self):\n"
                        "    results = [{'ok': True, 'message': 'skip'}, {'ok': False, 'message': 'bad'}]\n"
                        "    self.assertEqual(['bad'], summarize_validation_failures(results))"
                    )
                }),
                kind="test",
                expected_symbol="test_summarize_validation_failures",
                required_reference="summarize_validation_failures",
                objective=objective,
            )
            self.assertEqual([], helper_errors + integration_errors + test_errors)
            candidate = build_project_edit_leaf_candidate(
                work_units,
                helper_source=helper_source,
                integration_source=integration_source,
                test_source=test_source,
            )

            preview = preview_project_edit_agent_response(
                candidate,
                project_root=str(root),
                request_prompt=objective,
            )

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(2, len(preview.changes))
            target_after = next(item["after"] for item in preview.changes if item["path"] == str(target.resolve()))
            test_after = next(item["after"] for item in preview.changes if item["path"] == str(test_path.resolve()))
            self.assertIn("def summarize_validation_failures", target_after)
            self.assertIn("from service import summarize_validation_failures", test_after)
            self.assertEqual(target_before, target.read_text(encoding="utf-8"))
            self.assertEqual(test_before, test_path.read_text(encoding="utf-8"))

            handoff = project_edit_leaf_work_units_handoff(work_units)
            restored, restore_errors = restore_project_edit_leaf_work_units(handoff, objective)
            self.assertEqual([], restore_errors)
            self.assertEqual(work_units.integration_symbol, restored.integration_symbol)
            restored_plan = build_project_edit_plan_from_leaf_work_units(objective, restored)
            self.assertEqual("approved_index_handoff", restored_plan.discovery["evidence_mode"])

            test_path.write_text(test_before + "\n# changed\n", encoding="utf-8")
            stale_units, stale_errors = restore_project_edit_leaf_work_units(handoff, objective)
            self.assertIsNone(stale_units)
            self.assertTrue(any("test file changed" in error for error in stale_errors))

    def test_project_edit_leaf_validation_rejects_unbounded_or_detached_source(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            json.dumps({"source": "import os\n\ndef helper():\n    return 1"}),
            kind="define",
            expected_symbol="helper",
        )
        detached, detached_errors = parse_project_edit_leaf_source(
            json.dumps({"source": "def render(values):\n    return list(values)"}),
            kind="integrate",
            expected_symbol="render",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual("", source)
        self.assertTrue(any("exactly one function" in error for error in errors))
        self.assertEqual("", detached)
        self.assertTrue(any("required symbol" in error for error in detached_errors))

        wrong_contract, contract_errors = parse_project_edit_leaf_source(
            (
                "def summarize_validation_failures(result: ProjectEditApplyResult) -> str:\n"
                "    \"\"\"Return one joined validation report.\"\"\"\n"
                "    return '\\n'.join(item['message'] for item in result.validation)"
            ),
            kind="define",
            expected_symbol="summarize_validation_failures",
            objective=(
                "Add a helper that accepts validation result dictionaries and returns human-readable failure lines."
            ),
        )
        self.assertEqual("", wrong_contract)
        self.assertTrue(any("dictionaries" in error or "individual failure lines" in error for error in contract_errors))

        unfiltered, unfiltered_errors = parse_project_edit_leaf_source(
            (
                "def summarize_validation_failures(results: list[dict[str, object]]) -> list[str]:\n"
                "    \"\"\"Return a line for every validation result.\"\"\"\n"
                "    return [str(item.get('message')) for item in results]"
            ),
            kind="define",
            expected_symbol="summarize_validation_failures",
            objective=(
                "Add a helper that accepts validation result dictionaries and returns human-readable failure lines."
            ),
        )
        self.assertEqual("", unfiltered)
        self.assertTrue(any("ok value is true" in error for error in unfiltered_errors))

    def test_project_edit_leaf_test_normalizes_single_class_wrapper(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            (
                "import unittest\n"
                "from service import summarize_validation_failures\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_summarize_validation_failures(self):\n"
                "        self.assertEqual([], summarize_validation_failures([]))\n"
            ),
            kind="test",
            expected_symbol="test_generated_behavior",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual([], errors)
        self.assertTrue(source.startswith("def test_summarize_validation_failures"))
        self.assertNotIn("class TestService", source)
        self.assertNotIn("import unittest", source)

    def test_project_edit_leaf_test_extracts_only_method_using_required_helper(self) -> None:
        source, errors = parse_project_edit_leaf_source(
            (
                "import unittest\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_existing_behavior(self):\n"
                "        self.assertTrue(True)\n\n"
                "    def test_summarize_validation_failures(self):\n"
                "        self.assertEqual([], summarize_validation_failures([]))\n"
            ),
            kind="test",
            expected_symbol="test_generated_behavior",
            required_reference="summarize_validation_failures",
        )

        self.assertEqual([], errors)
        self.assertTrue(source.startswith("def test_summarize_validation_failures"))
        self.assertNotIn("test_existing_behavior", source)

    def test_project_edit_preview_resolves_unique_bare_filename_within_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_dir = Path(tmp) / "services"
            service_dir.mkdir()
            source = service_dir / "sample.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": "sample.py",
                            "target_symbol": "",
                            "original_content": "VALUE = 1\n",
                            "new_content": "VALUE = 2\n",
                        }
                    ],
                    "report": {"changed": ["VALUE"], "reused": [], "verification": ["compile"], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertTrue(preview.ok, preview.errors)
            self.assertEqual(str(source.resolve()), preview.changes[0]["path"])

    def test_project_edit_syntax_subagent_repairs_one_structured_change(self) -> None:
        candidate = json.dumps(
            {
                "changes": [
                    {
                        "action": "modify",
                        "path": "service.py",
                        "target_symbol": "render_report",
                        "original_content": "old source",
                        "new_content": "def summarize(item):\n    return f'{item.get('message')}'",
                    }
                ],
                "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                "blocked_reason": "",
            }
        )

        issues = inspect_project_edit_structured_syntax(candidate)
        small_stage = build_project_edit_syntax_repair_stage(issues[0], attempt=1)
        standard_stage = build_project_edit_syntax_repair_stage(issues[0], attempt=2)
        repaired = apply_project_edit_syntax_repair(
            candidate,
            change_index=0,
            repair_response=json.dumps(
                {"corrected_source": "def summarize(item):\n    return str(item.get('message'))"}
            ),
        )

        self.assertEqual(1, len(issues))
        self.assertEqual("small", small_stage.coder_preference)
        self.assertEqual("standard", standard_stage.coder_preference)
        self.assertEqual([], inspect_project_edit_structured_syntax(repaired))

    def test_project_edit_preview_rejects_self_import_missing_symbol_and_missing_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "service.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            response = json.dumps(
                {
                    "changes": [
                        {
                            "action": "modify",
                            "path": str(source),
                            "target_symbol": "",
                            "original_content": "VALUE = 1\n",
                            "new_content": "from service import requested_helper\n\nVALUE = 1\n",
                        }
                    ],
                    "report": {"changed": [], "reused": [], "verification": [], "remaining_gaps": []},
                    "blocked_reason": "",
                }
            )

            preview = preview_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Add a function named requested_helper and focused unittest coverage.",
            )

            self.assertFalse(preview.ok)
            self.assertTrue(any("cannot import" in error.lower() for error in preview.errors))
            self.assertTrue(any("requested_helper" in error for error in preview.errors))
            self.assertTrue(any("focused test file" in error for error in preview.errors))

    def test_project_edit_plan_fingerprint_detects_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            plan = ProjectEditPlan(
                prompt="Update VALUE.",
                discovery={"best_target": {"path": str(target)}},
                discovery_context="",
                model_prompt="",
                active_path=str(target),
            )

            before = project_edit_plan_fingerprint(plan)
            target.write_text("VALUE = 2\n", encoding="utf-8")

            self.assertNotEqual(before, project_edit_plan_fingerprint(plan))

    def test_code_agent_selects_existing_domain_experts(self) -> None:
        maya_experts = select_code_agent_experts(
            "Create a Maya UI for an existing rigging function.",
            discovery={
                "best_target": {"path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
                "project_roots": ["C:/depot/tools"],
            },
        )
        maya_domains = {expert["domain"] for expert in maya_experts}
        self.assertIn("maya.rigging", maya_domains)
        self.assertIn("python.code", maya_domains)
        self.assertIn("Code/domain expert advisory context:", render_code_agent_expert_context(maya_experts))

    def test_code_agent_selects_ui_and_validation_experts_for_maya_ui_work(self) -> None:
        experts = select_code_agent_experts(
            "Create a Maya Qt UI for an existing rigging function, validate inputs, add tests, and compile modified files.",
            discovery={
                "best_target": {"path": "C:/depot/tools/maya_tools/Rigging/create_rig.py"},
                "project_roots": ["C:/depot/tools"],
            },
            limit=8,
        )

        domains = {expert["domain"] for expert in experts}
        self.assertIn("maya.rigging", domains)
        self.assertIn("python.ui_integration", domains)
        self.assertIn("python.testing_validation", domains)

    def test_code_agent_selects_unreal_graph_expert_for_graph_code_request(self) -> None:
        experts = select_code_agent_experts(
            "Improve Unreal Blueprint graph planning code and validation.",
            discovery={
                "best_target": {
                    "path": "C:/depot/tools/tech_connector/services/unreal/semantic_graph_service.py"
                },
                "project_roots": ["C:/depot/tools/tech_connector"],
            },
        )
        domains = {expert["domain"] for expert in experts}
        self.assertIn("unreal.blueprint_graph", domains)
        self.assertIn("python.code", domains)

    def test_code_agent_selects_responsiveness_and_index_experts_for_freeze_work(self) -> None:
        experts = select_code_agent_experts(
            "Fix the UI freeze while project indexing and long prompts stream; keep chat updates responsive.",
            discovery={
                "best_target": {
                    "path": "C:/depot/tools/tech_connector/app/main_window_editor.py"
                },
                "project_roots": ["C:/depot/tools/tech_connector"],
            },
            limit=8,
        )

        domains = {expert["domain"] for expert in experts}
        self.assertIn("python.async_responsiveness", domains)
        self.assertIn("python.index_search", domains)
        self.assertIn("python.ui_integration", domains)

    def test_adaptive_plan_requires_successful_output_and_fallbacks(self) -> None:
        plan = build_code_agent_adaptive_plan(
            "Implement a reusable stamina system and connect it to sprinting",
            discovery={
                "confidence": "low",
                "best_target": {},
            },
        )
        text = render_code_agent_adaptive_plan(plan)

        self.assertTrue(plan["requires_confirmation"])
        self.assertIn("successful output", text)
        self.assertIn("repo map, symbol lookup, references, usages", text)
        self.assertIn("build_code_intelligence_packet", text)
        self.assertIn("Do not fabricate missing APIs or paths.", text)
        self.assertIn("Capability gaps", text)

    def test_preview_resolves_modify_file_with_existing_resilient_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tool.py"
            source.write_text("def run():\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run():
    return 'old'
====
def run():
    return 'new'
>>>>
</modify_file>"""

            result = preview_project_edit_agent_response(response, project_root=str(root))

            self.assertTrue(result.ok)
            self.assertEqual("preview_ready", result.status)
            self.assertEqual(1, len(result.changes))
            self.assertIn("return 'new'", result.changes[0]["after"])
            self.assertEqual("def run():\n    return 'old'\n", source.read_text(encoding="utf-8"))

    def test_apply_writes_change_validates_python_and_creates_undo_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tool.py"
            source.write_text("def run():\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run():
    return 'old'
====
def run():
    return 'new'
>>>>
</modify_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))

            self.assertTrue(result.ok)
            self.assertEqual("applied", result.status)
            self.assertIn("return 'new'", source.read_text(encoding="utf-8"))
            self.assertTrue(result.change_session_path)
            self.assertTrue(any(item.get("ok") for item in result.validation))

            session = load_change_session(result.change_session_path)
            ok, _message, changed = undo_change_session(session)
            self.assertTrue(ok)
            self.assertIn(str(source.resolve()), changed)
            self.assertIn("return 'old'", source.read_text(encoding="utf-8"))

    def test_apply_reports_validation_failure_for_invalid_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.py"
            source.write_text("def run():\n    return 'old'\n", encoding="utf-8")
            response = f"""<modify_file path="{source}">
<<<< ORIGINAL
def run():
    return 'old'
====
def run(
    return 'new'
>>>>
</modify_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))
            report = render_project_edit_agent_report(result)

            self.assertFalse(result.ok)
            self.assertEqual("preview_failed", result.status)
            self.assertIn("failed: candidate:syntax", report)
            self.assertIn("Warnings / Errors:", report)
            self.assertIn("return 'old'", source.read_text(encoding="utf-8"))

    def test_create_file_is_supported_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = """<create_file path="new_tool.py">
def created():
    \"\"\"Return whether the generated tool was created successfully.\"\"\"
    return True
</create_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))
            report = render_project_edit_agent_report(result)

            self.assertTrue(result.ok)
            self.assertTrue((root / "new_tool.py").exists())
            self.assertIn("create", report)
            self.assertIn("py_compile new_tool.py", report)

    def test_preview_rejects_unresolved_new_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="broken_import_tool.py">
import package_that_does_not_exist_tech_connector

def build_report():
    \"\"\"Build the report.\"\"\"
    return package_that_does_not_exist_tech_connector.report()
</create_file>"""

            result = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertFalse(result.ok)
            self.assertTrue(any("could not be resolved" in error for error in result.errors))

    def test_preview_rejects_new_public_callable_without_docstring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="undocumented_tool.py">
def normalize_records(records):
    return list(records)
</create_file>"""

            result = preview_project_edit_agent_response(response, project_root=tmp)

            self.assertFalse(result.ok)
            self.assertTrue(any("docstrings" in error for error in result.errors))

    def test_whole_tool_preview_requires_and_accepts_focused_behavior_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response_without_test = """<create_file path="record_tool.py">
def normalize_records(records: list[str]) -> list[str]:
    \"\"\"Normalize records by trimming whitespace and removing empty values.\"\"\"
    return [value.strip() for value in records if value.strip()]
</create_file>"""
            prompt = "Create a reusable record normalization tool with working behavior."

            rejected = preview_project_edit_agent_response(
                response_without_test,
                project_root=tmp,
                request_prompt=prompt,
            )

            self.assertFalse(rejected.ok)
            self.assertTrue(any("focused test file" in error for error in rejected.errors))

            response_with_test = response_without_test + """
<create_file path="test_record_tool.py">
import unittest

from record_tool import normalize_records


class RecordToolTests(unittest.TestCase):
    def test_normalize_records_trims_and_drops_empty_values(self):
        self.assertEqual(["alpha", "beta"], normalize_records([" alpha ", "", "beta"]))


if __name__ == "__main__":
    unittest.main()
</create_file>"""
            accepted = preview_project_edit_agent_response(
                response_with_test,
                project_root=tmp,
                request_prompt=prompt,
            )

            self.assertTrue(accepted.ok, accepted.errors)
            self.assertTrue(all(item.get("ok") for item in accepted.validation))

            applied = apply_project_edit_agent_response(
                response_with_test,
                project_root=tmp,
                request_prompt=prompt,
            )
            self.assertTrue(applied.ok, applied.errors)
            self.assertTrue(any("Focused behavior tests passed" in item.get("message", "") for item in applied.validation))

    def test_apply_withholds_completion_when_generated_behavior_test_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = """<create_file path="calculator_tool.py">
def add_values(left: int, right: int) -> int:
    \"\"\"Return the sum of two integer values.\"\"\"
    return left - right
</create_file>
<create_file path="test_calculator_tool.py">
import unittest

from calculator_tool import add_values


class CalculatorToolTests(unittest.TestCase):
    def test_add_values_returns_sum(self):
        self.assertEqual(5, add_values(2, 3))


if __name__ == "__main__":
    unittest.main()
</create_file>"""

            result = apply_project_edit_agent_response(
                response,
                project_root=tmp,
                request_prompt="Create a reusable calculator tool with working behavior.",
            )

            self.assertFalse(result.ok)
            self.assertEqual("applied_with_validation_errors", result.status)
            self.assertTrue(any("FAILED" in error or "failed" in error.lower() for error in result.errors))

    def test_validate_project_edit_paths_reuses_python_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "checked.py"
            source.write_text("def checked():\n    return True\n", encoding="utf-8")

            result = validate_project_edit_paths([str(source)])

            self.assertEqual(1, len(result))
            self.assertTrue(result[0]["ok"])
            self.assertIn("py_compile checked.py", result[0]["command"])

    def test_target_discovery_uses_subsystem_paths_over_active_file_for_indexing(self) -> None:
        discovery = discover_edit_targets(
            "Indexing says ready while still running; find that progress bug and fix it.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("knowledge_background_service.py" in path or "main_window_core.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_prompt_thread_paths_for_freeze_work(self) -> None:
        discovery = discover_edit_targets(
            "Troubleshoot why the app freezes during long prompts and patch the likely main-thread issue.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(
            any(
                marker in path
                for path in paths
                for marker in (
                    "main_window_chat_runtime.py",
                    "prompt_dispatch_service.py",
                    "prompt_progress_service.py",
                )
            )
        )
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_parser_paths_for_xml_patch_work(self) -> None:
        discovery = discover_edit_targets(
            "Find the parser for XML patches and make errors more actionable.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("project_edit_agent_service.py" in path or "knowledge/search.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").replace("\\", "/").startswith("tests/"))

    def test_target_discovery_uses_pipeline_paths_for_node_graph_work(self) -> None:
        discovery = discover_edit_targets(
            "When I right click in pipeline node view the filter is slow. Find the code path and improve it.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("pipeline_node_view.py" in path or "node_search_dialog.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_target_discovery_uses_code_agent_paths_for_adaptive_planning(self) -> None:
        discovery = discover_edit_targets(
            "Which service should own adaptive code-agent planning?",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("project_edit_agent_service.py" in path or "code_intelligence_service.py" in path for path in paths))

    def test_target_discovery_uses_maya_rigging_paths_for_docstring_work(self) -> None:
        discovery = discover_edit_targets(
            "Add missing docstrings and missing param entries to existing Maya rigging functions, but inspect the project first.",
            active_path=self.ACTIVE_UI_FILE,
            limit=5,
        )

        paths = [str(item.get("path") or "").replace("\\", "/") for item in discovery["candidates"]]
        self.assertTrue(any("maya_tools/Rigging/create_rig.py" in path for path in paths))
        self.assertFalse(str((discovery["best_target"] or {}).get("path") or "").endswith("custom_widgets.py"))

    def test_project_edit_contract_requires_create_plan_for_missing_targets(self) -> None:
        context = format_edit_target_context(
            {
                "question": "Create missing function launch_rig_mapping_wizard in the Maya UI layer.",
                "project_roots": ["C:/depot/tools"],
                "active_path": self.ACTIVE_UI_FILE,
                "terms": ["launch", "rig", "mapping", "wizard"],
                "scope": None,
                "confidence": "none",
                "best_target": None,
                "candidates": [],
            }
        )
        prompt = build_project_edit_target_prompt(
            "Create missing function launch_rig_mapping_wizard in the Maya UI layer.",
            context,
            active_path=self.ACTIVE_UI_FILE,
        )

        self.assertIn("verify that the target exists", prompt)
        self.assertIn("how to create it", prompt)
        self.assertIn("how it would be implemented", prompt)
        self.assertIn("ask for approval before emitting a create-file or create-symbol patch", prompt)
        self.assertIn("creation plan and implementation plan", prompt)


if __name__ == "__main__":
    unittest.main()
