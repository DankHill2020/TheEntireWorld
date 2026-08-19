from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from tech_connector.app.main_window_chat_runtime import (
    MainWindowChatRuntimeMixin,
    PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS,
    PROMPT_PROGRESS_QUIET_SECONDS,
)
from reasoning_runtime.engine.progress_events import EngineResult
from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.prompt.prompt_execution_context_service import (
    PromptExecutionContext,
    UnderstandingValidation,
    _PLANNING_CACHE,
    _action_catalog,
    _should_pause_for_user_context,
    _validate_planning_result,
    build_prompt_execution_context,
    review_prompt_answer,
    validate_prompt_understanding,
)
from tech_connector.services.prompt.prompt_intent_service import classify_prompt_intent, understand_prompt_request
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


TOOLS_ROOT = "C:/depot/tools"
CREATE_RIG = "maya_tools/Rigging/create_rig.py"
CUSTOM_WIDGETS = "custom_qt/custom_widgets.py"


def _workspace(*files: str, primary: int = 0) -> dict:
    entities = {}
    ids = []
    for index, file_path in enumerate(files):
        entity_id = f"file-{index}"
        ids.append(entity_id)
        entities[entity_id] = {
            "entity_id": entity_id,
            "kind": "file",
            "ref": file_path,
            "name": Path(file_path).name,
            "source": "project_search",
            "confidence": 0.98,
        }
    return {
        "entities": entities,
        "primary_entities": {"file": ids[primary]} if ids else {},
        "selected_entity_sets": {"file": ids},
    }


def _plan_for(system: str, packet: dict, **_kwargs) -> dict:
    if "answer-quality reviewer" in system:
        return {}
    prompt = str(packet.get("raw_prompt") or "").lower()
    base = {
        "interpreted_request": prompt,
        "intent_category": "project_search",
        "primary_route": "project_search",
        "goal_type": "locate",
        "deliverable": "file",
        "behavior": "create rig",
        "scope": "project",
        "target": "",
        "resolved_references": dict(packet.get("resolved_references") or {}),
        "mutation_requested": False,
        "execution_requested": False,
        "steps": [
            {
                "step_id": "search",
                "action": "search",
                "objective": "Find supported project evidence.",
                "depends_on": [],
                "success_condition": "A supported result is returned.",
            }
        ],
        "function_calls": [
            {
                "action_type": "search_project",
                "arguments": {"query": "create rig", "scope": "project"},
                "reason": "Find the implementation.",
            }
        ],
        "answer_contract": {
            "must_answer": ["Return the requested evidence."],
            "must_not_include": [],
            "success_condition": "The requested evidence is supported.",
        },
        "unknowns": [],
        "context_requests": [],
        "clarification_question": "",
        "confidence": 0.94,
        "reasons": ["The request has a clear read-only deliverable."],
    }
    if "twist joints" in prompt and "are there" in prompt:
        base.update(
            {
                "interpreted_request": "Check the remembered file for functions that find twist joints.",
                "deliverable": "function",
                "behavior": "find twist joints",
                "scope": "exact_file",
                "target": CUSTOM_WIDGETS,
            }
        )
    elif prompt.startswith("file to"):
        base.update(
            {
                "intent_category": "general_chat",
                "primary_route": "chat",
                "goal_type": "respond",
                "deliverable": "answer",
                "behavior": "",
                "scope": "conversation",
                "confidence": 0.45,
                "function_calls": [],
            }
        )
    elif "compare those files" in prompt:
        base.update(
            {
                "interpreted_request": "Compare the selected files.",
                "intent_category": "comparison",
                "primary_route": "chat",
                "goal_type": "analyze",
                "deliverable": "comparison",
                "behavior": "compare implementations",
                "scope": "selected_files",
                "function_calls": [],
            }
        )
    elif "help me write" in prompt:
        base.update(
            {
                "interpreted_request": "Explain how to write a function that finds twist joints.",
                "intent_category": "code_generation_guidance",
                "primary_route": "chat",
                "goal_type": "learn",
                "deliverable": "code_example",
                "behavior": "find twist joints",
                "scope": "conversation",
                "function_calls": [],
            }
        )
    return base


class IntentPlanningPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        from tech_connector.services.prompt import prompt_intent_service

        prompt_intent_service._CACHE.clear()
        _PLANNING_CACHE.clear()
        self.model_patch = patch(
            "tech_connector.services.prompt.prompt_intent_service._model_understanding",
            return_value=None,
        )
        self.planner_patch = patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=_plan_for,
        )
        self.semantic_model = self.model_patch.start()
        self.planner_model = self.planner_patch.start()

    def tearDown(self) -> None:
        self.planner_patch.stop()
        self.model_patch.stop()

    def _build(self, prompt: str, **facts) -> PromptExecutionContext:
        return build_prompt_execution_context(
            prompt,
            decision_facts={
                "project_roots": [TOOLS_ROOT],
                "settings": {"ai_work_memory_enabled": False},
                **facts,
            },
        )

    def test_high_confidence_file_search_skips_semantic_model(self) -> None:
        understanding = understand_prompt_request("what file has creat rig?")

        self.semantic_model.assert_not_called()
        self.assertEqual("project_search", understanding.primary_route)

    def test_existence_question_uses_governing_semantics_not_create_keyword(self) -> None:
        prompt = "do we have any class to create a Browse to Directory widget?"
        understanding = understand_prompt_request(prompt)

        self.semantic_model.assert_not_called()
        self.assertEqual("project_search", understanding.primary_route)
        self.assertEqual("project_search", understanding.primary_intent)
        self.assertEqual("project_symbol_location", understanding.requested_artifact)
        self.assertFalse(understanding.mutation_requested)
        self.assertTrue(understanding.read_only_requested)
        self.assertGreaterEqual(understanding.confidence, 0.9)

    def test_elliptical_what_class_to_create_is_a_symbol_lookup(self) -> None:
        prompt = "what class to create a Browse to Directory widget?"
        understanding = understand_prompt_request(prompt)

        self.semantic_model.assert_not_called()
        self.assertEqual("project_search", understanding.primary_route)
        self.assertEqual("project_search", understanding.primary_intent)
        self.assertEqual("project_symbol_location", understanding.requested_artifact)
        self.assertEqual("class", understanding.requested_member_type)
        self.assertEqual("create a browse to directory widget", understanding.behavior_description)
        self.assertEqual(
            "Find the project class that creates a browse to directory widget.",
            understanding.normalized_goal,
        )
        self.assertFalse(understanding.mutation_requested)
        self.assertTrue(understanding.read_only_requested)
        self.assertGreaterEqual(understanding.confidence, 0.9)

    def test_explicit_qualified_symbol_preserves_explanation_and_usage_intent(self) -> None:
        prompt = (
            "@maya_tools.Rigging.create_rig.create_rig_from_mapping "
            "what does this function do and how i do use it?"
        )
        understanding = understand_prompt_request(prompt)

        self.semantic_model.assert_not_called()
        self.assertEqual("project_search", understanding.primary_route)
        self.assertEqual("code_understanding", understanding.primary_intent)
        self.assertEqual("symbol_inspection", understanding.requested_artifact)
        self.assertEqual(
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
            understanding.target_symbol,
        )
        self.assertIn("explain_behavior", understanding.behavior_description)
        self.assertIn("explain_usage", understanding.behavior_description)
        self.assertTrue(understanding.requires_examples)
        self.assertFalse(understanding.mutation_requested)

    def test_module_mention_guidance_is_scoped_read_only_class_help(self) -> None:
        prompt = "what would i do if i needed a class to make a QSlider in @custom_qt.custom_widgets"
        understanding = understand_prompt_request(prompt)

        self.semantic_model.assert_not_called()
        self.assertEqual("project_search", understanding.primary_route)
        self.assertEqual("project_search", understanding.primary_intent)
        self.assertEqual("scoped_class_search", understanding.requested_artifact)
        self.assertEqual("custom_qt.custom_widgets", understanding.target_file)
        self.assertEqual("custom_qt.custom_widgets", understanding.target_container_query)
        self.assertEqual("class", understanding.requested_member_type)
        self.assertEqual("make a QSlider", understanding.behavior_description)
        self.assertFalse(understanding.mutation_requested)

    def test_module_mention_add_class_is_scoped_project_edit(self) -> None:
        prompt = "add a QSlider class to @custom_qt.custom_widgets"
        understanding = understand_prompt_request(prompt)

        self.semantic_model.assert_not_called()
        self.assertEqual("target_discovery", understanding.primary_route)
        self.assertEqual("project_code_edit", understanding.primary_intent)
        self.assertTrue(understanding.mutation_requested)
        self.assertEqual("custom_qt.custom_widgets", understanding.target_file)
        self.assertEqual("file", understanding.target_container_type)
        self.assertEqual("custom_qt.custom_widgets", understanding.target_container_query)

    def test_composed_request_distinguishes_and_roles(self) -> None:
        from tech_connector.services.prompt.prompt_task_splitter_service import compose_request

        select_it = compose_request("Create a locator and select it.").to_dict()
        dont_select = compose_request("Create a locator and don't select it.").to_dict()
        call_it = compose_request("Create a locator and call it wrist_loc.").to_dict()
        context = compose_request("Create a locator and the wrist is selected.").to_dict()
        validate = compose_request("Create a locator and verify it exists.").to_dict()
        two_goals = compose_request("Create a locator and a control.").to_dict()

        self.assertEqual(["GOAL", "DEPENDENT_GOAL"], [c["role"] for c in select_it["clauses"]])
        self.assertEqual(["goal_1"], select_it["goals"][1]["depends_on"])
        self.assertEqual("$goal_1.output", select_it["goals"][1]["consumes"][0])

        self.assertEqual(["GOAL", "CONSTRAINT"], [c["role"] for c in dont_select["clauses"]])
        self.assertEqual(["don't select it"], dont_select["goals"][0]["constraints"])

        self.assertEqual(["GOAL", "ARGUMENT"], [c["role"] for c in call_it["clauses"]])
        self.assertEqual("wrist_loc", call_it["goals"][0]["arguments"]["name"])

        self.assertEqual(["GOAL", "CONTEXT"], [c["role"] for c in context["clauses"]])
        self.assertIn("context_hint", context["shared_context"])

        self.assertEqual(["GOAL", "VALIDATION"], [c["role"] for c in validate["clauses"]])
        self.assertEqual(["verify it exists"], validate["goals"][0]["validations"])

        self.assertEqual(["GOAL", "GOAL"], [c["role"] for c in two_goals["clauses"]])
        self.assertEqual(2, len(two_goals["goals"]))

    def test_composed_request_preserves_output_request_as_modifier_not_task(self) -> None:
        from tech_connector.services.prompt.prompt_task_splitter_service import compose_request

        composed = compose_request("Find the rig function and tell me what file it is in.").to_dict()

        self.assertEqual(["GOAL", "OUTPUT_REQUEST"], [c["role"] for c in composed["clauses"]])
        self.assertEqual(1, len(composed["goals"]))
        self.assertIn("output:tell me what file it is in", composed["goals"][0]["modifiers"])

    def test_execution_context_carries_composed_request_graph(self) -> None:
        context = self._build("Create a locator and call it wrist_loc.")
        composed = context.task_graph["composed_request"]

        self.assertEqual("compositional_request_v1", composed["framework"])
        self.assertEqual(["GOAL", "ARGUMENT"], [c["role"] for c in composed["clauses"]])
        self.assertEqual("wrist_loc", composed["goals"][0]["arguments"]["name"])

    def test_composed_request_tracks_shared_context_plural_args_and_both_reference(self) -> None:
        from tech_connector.services.prompt.prompt_task_splitter_service import compose_request

        composed = compose_request(
            "In Maya, create a locator and a control, name them wrist_loc and wrist_ctrl, "
            "move both to the wrist joint, but only select the control."
        ).to_dict()

        self.assertEqual("maya", composed["shared_context"]["host"])
        self.assertEqual(
            ["GOAL", "GOAL", "ARGUMENT", "DEPENDENT_GOAL", "CONSTRAINT"],
            [clause["role"] for clause in composed["clauses"]],
        )
        self.assertEqual("wrist_loc", composed["goals"][0]["arguments"]["name"])
        self.assertEqual("wrist_ctrl", composed["goals"][1]["arguments"]["name"])
        self.assertEqual(["goal_1", "goal_2"], composed["goals"][2]["depends_on"])
        self.assertEqual(["$goal_1.output", "$goal_2.output"], composed["goals"][2]["consumes"])
        self.assertEqual(["only select the control"], composed["goals"][2]["constraints"])

    def test_composed_request_recognizes_code_inspection_and_unpunctuated_chains(self) -> None:
        from tech_connector.services.prompt.prompt_task_splitter_service import compose_request

        inspect_prompt = compose_request(
            "Inspect prompt_route_service.py and tell me which function decides project search."
        ).to_dict()
        chain_prompt = compose_request(
            "create locator move it to wrist parent it under joint verify it exists"
        ).to_dict()

        self.assertEqual(["GOAL", "OUTPUT_REQUEST"], [clause["role"] for clause in inspect_prompt["clauses"]])
        self.assertEqual("find", inspect_prompt["goals"][0]["action"])
        self.assertEqual(
            ["GOAL", "DEPENDENT_GOAL", "DEPENDENT_GOAL", "VALIDATION"],
            [clause["role"] for clause in chain_prompt["clauses"]],
        )
        self.assertEqual(3, len(chain_prompt["goals"]))
        self.assertEqual(["goal_2"], chain_prompt["goals"][2]["depends_on"])

    def test_prompt_route_does_not_promote_project_ui_or_api_queries_to_unreal(self) -> None:
        project_details = classify_prompt_route("Open project details or refresh the tree if stale.")
        api_query = classify_prompt_route("are we importing the new api anywhere find that and dont load it")

        self.assertNotEqual("unreal_capability", project_details.route)
        self.assertEqual("target_discovery", project_details.route)
        self.assertNotEqual("unreal_capability", api_query.route)
        self.assertEqual("project_search", api_query.route)

    def test_high_confidence_symbol_lookup_skips_planning_model(self) -> None:
        context = self._build("do we have any class to create a Browse to Directory widget?")

        self.planner_model.assert_not_called()
        self.assertEqual("deterministic_project_lookup", context.planning_result["planning_mode"])
        self.assertEqual("project_search", context.planning_result["primary_route"])
        self.assertEqual("class", context.planning_result["deliverable"])
        self.assertFalse(context.planning_result["mutation_requested"])

    def test_elliptical_symbol_lookup_skips_planning_model(self) -> None:
        context = self._build("what class to create a Browse to Directory widget?")

        self.planner_model.assert_not_called()
        self.assertEqual("deterministic_project_lookup", context.planning_result["planning_mode"])
        self.assertEqual("project_search", context.planning_result["primary_route"])
        self.assertEqual("class", context.planning_result["deliverable"])
        self.assertFalse(context.planning_result["mutation_requested"])

    def test_instructional_request_uses_semantic_model(self) -> None:
        understanding = understand_prompt_request("help me write a function to find twist joints")

        self.semantic_model.assert_called_once()
        self.assertEqual("code_generation_guidance", understanding.primary_intent)

    def test_typo_repair_produces_natural_file_intent(self) -> None:
        context = self._build("what file has creat rig?")
        validation = validate_prompt_understanding(context)

        self.assertEqual("what file has create rig?", context.normalized_prompt)
        self.assertEqual("create rig", context.planning_result["behavior"])
        self.assertEqual("file", context.planning_result["deliverable"])
        self.assertIn(
            "implementation that creates a rig",
            context.request_understanding["normalized_goal"],
        )
        self.assertTrue(validation.valid)
        self.assertGreaterEqual(validation.confidence, 0.85)

    def test_singular_follow_up_locks_workspace_file_over_active_editor(self) -> None:
        context = self._build(
            "are there functions in that file to find twist joints?",
            active_path=f"{TOOLS_ROOT}/{CUSTOM_WIDGETS}",
            conversation_workspace=_workspace(CREATE_RIG),
        )
        validation = validate_prompt_understanding(context)

        self.assertEqual(CREATE_RIG, context.resolved_references["that_file"]["value"])
        self.assertEqual(CREATE_RIG, context.planning_result["target"])
        self.assertEqual("exact_file", context.planning_result["scope"])
        self.assertTrue(validation.valid)

    def test_malformed_fragment_requires_targeted_clarification(self) -> None:
        context = self._build("file to find twist joints")
        validation = validate_prompt_understanding(context)

        self.assertFalse(validation.valid)
        self.assertTrue(validation.clarification_required)
        self.assertLessEqual(validation.confidence, 0.64)
        question = validation.clarification_question.lower()
        self.assertIn("find an existing implementation", question)
        self.assertIn("help write", question)

    def test_internal_tool_connection_unknowns_do_not_ask_the_user(self) -> None:
        should_pause = _should_pause_for_user_context(
            "Find the parser, inspect its callers, update error reporting, and run focused tests.",
            {
                "primary_route": "target_discovery",
                "primary_intent": "project_code_edit",
                "goal_type": "modify",
                "requested_artifact": "code_change",
                "behavior_description": "improve parser error reporting",
                "confidence": 0.58,
            },
            {"behavior": "improve parser error reporting", "unresolved_fields": []},
            {
                "unknowns": [
                    "Which indexed parser owns the behavior.",
                    "How search, edit, and focused test tools should be sequenced.",
                ],
                "blocking_unknowns": [],
            },
            {},
        )

        self.assertFalse(should_pause)

    def test_unresolved_conversation_reference_still_asks_the_user(self) -> None:
        should_pause = _should_pause_for_user_context(
            "edit the function in that file",
            {
                "primary_route": "target_discovery",
                "primary_intent": "project_code_edit",
                "goal_type": "modify",
                "requested_artifact": "code_change",
                "behavior_description": "edit function",
                "confidence": 0.9,
            },
            {"behavior": "edit function", "unresolved_fields": []},
            {"unknowns": [], "blocking_unknowns": []},
            {},
        )

        self.assertTrue(should_pause)

    def test_plural_reference_resolves_selected_workspace_set(self) -> None:
        context = self._build(
            "compare those files",
            conversation_workspace=_workspace(CREATE_RIG, CUSTOM_WIDGETS),
        )
        validation = validate_prompt_understanding(context)

        self.assertEqual(
            [CREATE_RIG, CUSTOM_WIDGETS],
            context.resolved_references["those_files"]["value"],
        )
        self.assertTrue(validation.valid)

    def test_help_write_request_is_guidance_not_project_mutation(self) -> None:
        context = self._build("help me write a function that finds twist joints")
        validation = validate_prompt_understanding(context)

        self.assertEqual("chat", context.planning_result["primary_route"])
        self.assertEqual("code_generation_guidance", context.planning_result["intent_category"])
        self.assertFalse(context.planning_result["mutation_requested"])
        self.assertEqual("code_example", context.planning_result["deliverable"])
        self.assertTrue(validation.valid)

    def test_planning_model_receives_existing_ollama_budget_settings(self) -> None:
        packets = []

        def capture_plan(system: str, packet: dict, **kwargs) -> dict:
            packets.append(packet)
            return _plan_for(system, packet, **kwargs)

        self.planner_model.side_effect = capture_plan
        context = self._build(
            "help me write a function that finds twist joints",
            settings={
                "ai_work_memory_enabled": False,
                "ollama_max_timeout_seconds": 3,
                "ollama_max_num_ctx": 2048,
                "ollama_max_num_predict": 256,
            },
        )

        self.assertEqual("chat", context.planning_result["primary_route"])
        self.assertTrue(packets)
        self.assertEqual(3, packets[0]["settings"]["ollama_max_timeout_seconds"])
        self.assertEqual(2048, packets[0]["settings"]["ollama_max_num_ctx"])

    def test_how_would_widget_request_is_read_only_guidance_end_to_end(self) -> None:
        prompt = "in custom_widgets.py how would i make a new widget to create a color picker?"
        understanding = understand_prompt_request(prompt)
        context = self._build(prompt, active_path=f"{TOOLS_ROOT}/{CUSTOM_WIDGETS}")
        contract = context.semantic_execution_contract

        self.semantic_model.assert_not_called()
        self.assertEqual("chat", understanding.primary_route)
        self.assertEqual("code_generation_guidance", understanding.primary_intent)
        self.assertFalse(understanding.mutation_requested)
        self.assertTrue(understanding.read_only_requested)
        self.assertEqual("custom_widgets.py", understanding.target_file)
        self.assertFalse(contract["mutation_requested"])
        self.assertTrue(contract["read_only"])
        self.assertNotIn("apply_change", [step["step_id"] for step in contract["plan_steps"]])

    def test_maya_host_state_query_stays_on_dcc_query_path(self) -> None:
        prompt = "In Maya, list joints in the current scene. Do not modify anything."
        context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("dcc_query", context.request_understanding["primary_route"])
        self.assertEqual("maya", context.request_understanding["host"])
        self.assertEqual("host", context.planning_result["scope"])
        self.assertEqual(
            "query_dcc",
            context.planning_result["function_calls"][0]["action_type"],
        )
        query_args = context.planning_result["function_calls"][0]["arguments"]
        self.assertEqual("maya", query_args["host"])
        self.assertEqual("scene.list_joints", query_args["operation"])
        self.assertEqual("dcc_query", decision.route)
        self.assertEqual("scene.list_joints", decision.target_identifier)
        self.assertEqual("read_only", decision.mutation_scope)

    def test_unreal_blueprint_inspection_keeps_specialized_intent(self) -> None:
        prompt = (
            "In Unreal, inspect BP_LesterPhoenix and list graphs, variables, "
            "components, and compile status. Do not edit."
        )
        context = self._build(prompt)
        intent = classify_prompt_intent(prompt, host="unreal")
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("graph_read_or_navigation", intent.kind)
        self.assertEqual("unreal_capability", decision.route)
        self.assertEqual("blueprint.scan", decision.target_identifier)
        self.assertEqual("read_only", decision.mutation_scope)

    def test_question_form_create_behavior_remains_symbol_search(self) -> None:
        prompt = (
            "What Maya project functions create controls for a rig? "
            "Search symbols and docstrings, not filenames."
        )
        context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("project_search", context.request_understanding["primary_route"])
        self.assertFalse(context.request_understanding["mutation_requested"])
        self.assertEqual("project_search", decision.route)

    def test_find_then_improve_keeps_target_discovery_mutation(self) -> None:
        prompt = "Find the parser for XML patches and make errors more actionable."
        context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("target_discovery", context.request_understanding["primary_route"])
        self.assertTrue(context.request_understanding["mutation_requested"])
        self.assertEqual("target_discovery", decision.route)

    def test_read_only_application_plan_uses_target_discovery_without_mutation(self) -> None:
        prompt = (
            "Plan how the mobile app should show Jobs and Output logs while reusing "
            "the existing desktop job systems. Do not create code yet."
        )
        context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("read_only_code_planning", context.request_understanding["primary_intent"])
        self.assertFalse(context.request_understanding["mutation_requested"])
        self.assertEqual("target_discovery", decision.route)
        self.assertEqual("read_only", decision.mutation_scope)

    def test_unknown_dcc_operation_becomes_capability_acquisition_not_fake_execution(self) -> None:
        prompt = "In Maya, run a quantum retopology pass on the selected mesh."
        planner_result = _plan_for("planner", {"raw_prompt": prompt})
        planner_result.update(
            {
                "intent_category": "dcc_execution",
                "primary_route": "dcc_execute",
                "goal_type": "execute",
                "scope": "host",
                "target": "mesh.quantum_retopology",
                "host": "maya",
                "mutation_requested": True,
                "execution_requested": True,
                "function_calls": [
                    {
                        "action_type": "execute_dcc",
                        "arguments": {
                            "host": "maya",
                            "operation": "mesh.quantum_retopology",
                            "params": {},
                        },
                        "reason": "Attempt the requested operation.",
                    }
                ],
                "confidence": 0.94,
            }
        )
        _PLANNING_CACHE.clear()
        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            return_value=planner_result,
        ):
            context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertEqual("dcc_capability_acquisition", context.planning_result["intent_category"])
        self.assertEqual("target_discovery", context.planning_result["primary_route"])
        self.assertFalse(context.planning_result["execution_requested"])
        self.assertTrue(context.planning_result["capability_gap"]["execution_blocked"])
        self.assertNotIn("execute_dcc", json.dumps(context.planning_result["function_calls"]))
        step_ids = {step["step_id"] for step in context.planning_result["steps"]}
        self.assertIn("implement_dcc_adapter", step_ids)
        self.assertIn("validate_dcc_adapter", step_ids)
        self.assertIn("replan_original_request", step_ids)
        self.assertEqual("target_discovery", decision.route)

    def test_function_backed_artifact_uses_original_prompt_to_avoid_false_dcc_acquisition(self) -> None:
        prompt = (
            "Build a PySide/Qt tool panel that lets me search registered functions, "
            "pick one, edit JSON args, and run or queue it through the backend."
        )
        semantic_plan = {
            "interpreted_request": "search registered functions, pick one, edit JSON args, and run or queue it through the backend",
            "intent_category": "dcc_execution",
            "primary_route": "dcc_execute",
            "goal_type": "execute",
            "deliverable": "execution_result",
            "behavior": "search_registered_functions",
            "scope": "host",
            "target": "search_registered_functions",
            "host": "maya",
            "mutation_requested": True,
            "execution_requested": True,
            "function_calls": [
                {
                    "action_type": "execute_dcc",
                    "arguments": {"host": "maya", "operation": "search_registered_functions", "params": {}},
                    "reason": "Semantic layer mistakenly treated the generated UI's run button as immediate execution.",
                }
            ],
            "unknowns": [],
            "confidence": 0.91,
        }

        repaired = _validate_planning_result(
            semantic_plan,
            _action_catalog(),
            {},
            original_prompt=prompt,
        )

        self.assertEqual("target_discovery", repaired["primary_route"])
        self.assertEqual("function_backed_artifact_generation", repaired["intent_category"])
        self.assertEqual("working_generated_code", repaired["deliverable"])
        self.assertFalse(repaired["execution_requested"])
        self.assertEqual([], repaired["unknowns"])
        self.assertEqual("search_project", repaired["function_calls"][0]["action_type"])

    def test_indexed_project_callable_remains_available_for_dcc_execution(self) -> None:
        prompt = "run create_rig_from_mapping in Maya"
        planner_result = _plan_for("planner", {"raw_prompt": prompt})
        planner_result.update(
            {
                "intent_category": "dcc_execution",
                "primary_route": "dcc_execute",
                "goal_type": "execute",
                "scope": "host",
                "target": "create_rig_from_mapping",
                "host": "maya",
                "mutation_requested": True,
                "execution_requested": True,
                "function_calls": [
                    {
                        "action_type": "execute_dcc",
                        "arguments": {
                            "host": "maya",
                            "operation": "create_rig_from_mapping",
                            "params": {},
                        },
                        "reason": "Run the indexed project callable.",
                    }
                ],
                "confidence": 0.94,
            }
        )
        _PLANNING_CACHE.clear()
        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            return_value=planner_result,
        ):
            context = self._build(prompt)
        decision = classify_prompt_route(prompt, execution_context=context)

        self.assertNotIn("capability_gap", context.planning_result)
        call = context.planning_result["function_calls"][0]
        self.assertEqual("execute_dcc", call["action_type"])
        self.assertEqual("create_rig_from_mapping", call["arguments"]["operation"])
        self.assertTrue(any(
            candidate.get("source") in {"project_index", "project_source_ast"}
            and "create_rig_from_mapping" in str((candidate.get("metadata") or {}).get("symbol") or "")
            for candidate in context.context_candidates
        ))
        self.assertEqual("dcc_execute", decision.route)

    def test_executor_stops_before_adapter_for_unresolved_dcc_callable(self) -> None:
        from tech_connector.services.action_execution_engine import (
            ExecutionContext,
            default_action_handler_registry,
        )

        request = SimpleNamespace(
            original_prompt="In Maya run mesh.quantum_retopology",
            missing_slots=["callable"],
            callable_name="mesh.quantum_retopology",
            target_identifier="mesh.quantum_retopology",
            execution_environment="maya",
            to_dict=lambda: {
                "missing_slots": ["callable"],
                "target_identifier": "mesh.quantum_retopology",
            },
        )
        with (
            patch(
                "tech_connector.services.dcc.dcc_execution_service.build_dcc_execution_request",
                return_value=request,
            ),
            patch(
                "tech_connector.services.dcc.dcc_execution_service.default_dcc_execution_adapters"
            ) as adapters,
        ):
            result = default_action_handler_registry().require("execute_dcc").execute(
                {
                    "args": {
                        "host": "maya",
                        "operation": "mesh.quantum_retopology",
                    }
                },
                ExecutionContext(
                    current_dcc_host="maya",
                    policy={"original_prompt": request.original_prompt},
                ),
            )

        self.assertFalse(result["ok"])
        self.assertEqual("capability_gap", result["status"])
        self.assertTrue(result["requires_replan"])
        self.assertTrue(result["capability_gap"]["execution_blocked"])
        adapters.assert_not_called()

    def test_unsupported_planner_action_is_rejected(self) -> None:
        invalid_plan = _plan_for("planner", {"raw_prompt": "what file has create rig?"})
        invalid_plan["function_calls"] = [
            {"action_type": "invent_project_fact", "arguments": {}, "reason": "bad"}
        ]
        validated = _validate_planning_result(invalid_plan, _action_catalog(), {})

        calls = validated["function_calls"]
        self.assertEqual("search_project", calls[0]["action_type"])
        self.assertNotIn("invent_project_fact", json.dumps(calls))
        self.assertLessEqual(validated["confidence"], 0.84)

    def test_partial_planner_json_is_completed_from_semantic_contract(self) -> None:
        partial = {
            "scope": "exact_file",
            "target": CREATE_RIG,
            "confidence": 0.91,
            "unknowns": [],
        }
        _PLANNING_CACHE.clear()
        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            return_value=partial,
        ):
            context = self._build(
                "are there functions in that file to find twist joints?",
                conversation_workspace=_workspace(CREATE_RIG),
            )

        plan = context.planning_result
        self.assertEqual("project_search", plan["primary_route"])
        self.assertEqual("function", plan["deliverable"])
        self.assertEqual("find twist joints", plan["behavior"])
        self.assertEqual("search_project", plan["function_calls"][0]["action_type"])

    def test_identical_request_reuses_plan_without_mutating_semantic_cache(self) -> None:
        planner = MagicMock(side_effect=_plan_for)
        _PLANNING_CACHE.clear()
        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            planner,
        ):
            first = self._build(
                "are there functions in that file to find twist joints?",
                conversation_workspace=_workspace(CREATE_RIG),
            )
            second = self._build(
                "are there functions in that file to find twist joints?",
                conversation_workspace=_workspace(CREATE_RIG),
            )

        self.assertEqual(1, planner.call_count)
        self.assertEqual(first.planning_result, second.planning_result)
        from tech_connector.services.prompt.prompt_intent_service import understand_prompt_request

        cached_hypothesis = understand_prompt_request(
            "are there functions in that file to find twist joints?"
        )
        self.assertEqual("conversation_reference", cached_hypothesis.reference_scope)
        self.assertEqual("", cached_hypothesis.target_file)

    def test_exact_file_answer_uses_current_ast_line_numbers(self) -> None:
        from tech_connector.services.project_search_service import answer_scoped_member_behavior_question

        path = Path(TOOLS_ROOT) / CREATE_RIG
        source_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        expected_lines = [
            index
            for index, line in enumerate(source_lines, start=1)
            if line.lstrip().startswith("def get_twists(")
        ]
        answer = answer_scoped_member_behavior_question(
            "are there functions in that file to find twist joints?",
            active_path=str(path),
        )

        self.assertIsNotNone(answer)
        self.assertIn("Source: current file AST.", answer)
        for line in expected_lines:
            self.assertIn(f"on line `{line}`", answer)

    def test_answer_review_rejects_wrong_exact_file(self) -> None:
        context = PromptExecutionContext(
            prompt="are there functions in that file to find twist joints?",
            normalized_prompt="are there functions in that file to find twist joints?",
            planning_result={
                "deliverable": "function",
                "behavior": "find twist joints",
                "scope": "exact_file",
                "target": CREATE_RIG,
            },
            semantic_execution_contract={"deliverable_type": "function"},
        )
        result = EngineResult(
            "answer",
            "Project Index",
            "Yes. `find_twists()` finds twist joints.",
            metadata={"selected_file": CUSTOM_WIDGETS, "evidence_tier": 2},
        )

        review = review_prompt_answer(context, {"route": "project_search"}, result)

        self.assertFalse(review["adequate"])
        self.assertIn("exact-file scope", " ".join(review["failures"]))

    def test_answer_review_rejects_negative_answer_contradicted_by_context(self) -> None:
        context = PromptExecutionContext(
            prompt="are there functions in that file to find twist joints?",
            normalized_prompt="are there functions in that file to find twist joints?",
            context_candidates=[
                {"kind": "file_symbols", "value": {"symbols": ["get_twists finds twist joints"]}}
            ],
            planning_result={
                "deliverable": "function",
                "behavior": "find twist joints",
                "scope": "exact_file",
                "target": CREATE_RIG,
            },
            semantic_execution_contract={"deliverable_type": "function"},
        )
        result = EngineResult(
            "answer",
            "Project Index",
            "No functions find twist joints.",
            metadata={"selected_file": CREATE_RIG, "evidence_tier": 2},
        )

        review = review_prompt_answer(context, {"route": "project_search"}, result)

        self.assertFalse(review["adequate"])
        self.assertIn("source context", " ".join(review["failures"]))

    def test_contextual_knowledge_persists_only_reviewed_high_confidence_facts(self) -> None:
        from tech_connector.services import ai_work_memory_service as memory

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.multiple(
                memory,
                MEMORY_DIR=root,
                LOCKS_DIR=root / "locks",
                THIRD_PARTY_KNOWLEDGE_DIR=root / "third_party",
                CONTEXTUAL_KNOWLEDGE_PATH=root / "contextual_knowledge.jsonl",
            ):
                count = memory.record_contextual_knowledge(
                    {},
                    [
                        {
                            "kind": "function",
                            "subject": "find twist joints",
                            "relation": "confirmed_in_file",
                            "value": "get_twists",
                            "confidence": 0.96,
                            "validated": True,
                        },
                        {
                            "kind": "function",
                            "subject": "find twist joints",
                            "value": "maybe_twists",
                            "confidence": 0.6,
                            "validated": False,
                        },
                    ],
                    request="are there twist helpers?",
                )
                rows = memory.relevant_contextual_knowledge({}, "twist joints")
        self.assertEqual(1, count)
        self.assertEqual(["get_twists"], [row["value"] for row in rows])


class RequestEngineOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        from unittest.mock import patch
        self.fast_lookup_patcher1 = patch("tech_connector.engine.request_engine.RequestEngine._fast_simple_project_index_lookup", return_value=None)
        self.fast_lookup_patcher2 = patch("tech_connector.engine.request_engine.RequestEngine._fast_semantic_project_lookup", return_value=None)
        self.fast_lookup_patcher1.start()
        self.fast_lookup_patcher2.start()

    def tearDown(self) -> None:
        self.fast_lookup_patcher1.stop()
        self.fast_lookup_patcher2.stop()

    def _context(self) -> PromptExecutionContext:
        return PromptExecutionContext(
            prompt="what file has create rig?",
            normalized_prompt="what file has create rig?",
            request_understanding={"primary_route": "project_search"},
            planning_result={
                "primary_route": "project_search",
                "goal_type": "locate",
                "deliverable": "file",
                "behavior": "create rig",
                "scope": "project",
                "confidence": 0.95,
            },
            semantic_execution_contract={"deliverable_type": "file"},
        )

    def test_route_is_classified_once_after_gate(self) -> None:
        execution_context = self._context()
        decision = MagicMock()
        decision.to_dict.return_value = {
            "route": "project_search",
            "provider": "project_search",
            "execution_route": "engine.project_search",
        }
        validation = UnderstandingValidation(True, 0.95, reasons=["clear"])
        dispatch_result = EngineResult(
            "answer",
            "Project Index",
            "Best match: `maya_tools/Rigging/create_rig.py`",
            metadata={"selected_file": CREATE_RIG},
        )
        diagnostic = SimpleNamespace(to_dict=lambda: {"candidates": [], "selected_route": "project_search"})
        with (
            patch("tech_connector.services.prompt.prompt_execution_context_service.build_prompt_execution_context", return_value=execution_context),
            patch("tech_connector.services.prompt.prompt_execution_context_service.validate_prompt_understanding", return_value=validation),
            patch("tech_connector.services.prompt.prompt_route_service.classify_prompt_route", return_value=decision) as classify,
            patch("tech_connector.services.route_diagnostics_service.build_route_diagnostic_report", return_value=diagnostic),
            patch("tech_connector.services.prompt.prompt_progress_service.build_prompt_progress_plan", return_value={"stages": []}),
            patch("tech_connector.services.prompt.prompt_dispatch_service.PromptDispatchService.dispatch", return_value=dispatch_result),
            patch("tech_connector.services.prompt.prompt_execution_context_service.review_prompt_answer", return_value={"adequate": True, "score": 0.95, "validated_facts": []}),
        ):
            result = RequestEngine().process(RequestContext("show project dependencies"))

        self.assertEqual("answer", result.action)
        self.assertEqual(2, classify.call_count)
        self.assertIn("execution_context", classify.call_args_list[1][1])

    def test_low_confidence_gate_prevents_route_and_dispatch(self) -> None:
        execution_context = self._context()
        execution_context.planning_result["planning_mode"] = "clarification_fast_path"
        execution_context.planning_result["behavior"] = "find twist joints"
        execution_context.request_understanding.update(
            {"requested_artifact": "file", "behavior_description": "find twist joints"}
        )
        validation = UnderstandingValidation(
            False,
            0.5,
            missing_fields=["requested_action"],
            clarification_required=True,
            clarification_question="Should I search for a file or help write code?",
        )
        with (
            patch("tech_connector.services.prompt.prompt_execution_context_service.build_prompt_execution_context", return_value=execution_context),
            patch("tech_connector.services.prompt.prompt_execution_context_service.validate_prompt_understanding", return_value=validation),
            patch("tech_connector.services.prompt.prompt_route_service.classify_prompt_route") as classify,
            patch("tech_connector.services.prompt.prompt_dispatch_service.PromptDispatchService.dispatch") as dispatch,
        ):
            result = RequestEngine().process(RequestContext("file to find twist joints"))

        self.assertEqual("clarify", result.action)
        self.assertIn("What I understand:", result.text)
        self.assertIn("file related to find twist joints", result.text)
        self.assertIn("Should I search for a file or help write code?", result.text)
        self.assertEqual(1, classify.call_count)
        self.assertNotIn("execution_context", classify.call_args[1])
        dispatch.assert_not_called()

    def test_answer_review_failure_does_not_reinterpret_clear_request(self) -> None:
        execution_context = self._context()
        decision = MagicMock()
        decision.to_dict.return_value = {
            "route": "project_search",
            "provider": "project_search",
            "execution_route": "engine.project_search",
        }
        validation = UnderstandingValidation(True, 0.95, reasons=["clear"])
        dispatch_result = EngineResult("answer", "Project Index", "Initial answer")
        diagnostic = SimpleNamespace(to_dict=lambda: {"candidates": [], "selected_route": "project_search"})
        failed_review = {
            "adequate": False,
            "score": 0.5,
            "validated_facts": [],
            "context_requests": [],
        }
        with (
            patch("tech_connector.services.prompt.prompt_execution_context_service.build_prompt_execution_context", return_value=execution_context),
            patch("tech_connector.services.prompt.prompt_execution_context_service.validate_prompt_understanding", return_value=validation),
            patch("tech_connector.services.prompt.prompt_route_service.classify_prompt_route", return_value=decision),
            patch("tech_connector.services.route_diagnostics_service.build_route_diagnostic_report", return_value=diagnostic),
            patch("tech_connector.services.prompt.prompt_progress_service.build_prompt_progress_plan", return_value={"stages": []}),
            patch("tech_connector.services.prompt.prompt_dispatch_service.PromptDispatchService.dispatch", return_value=dispatch_result),
            patch("tech_connector.services.prompt.prompt_execution_context_service.review_prompt_answer", return_value=failed_review),
            patch(
                "tech_connector.services.prompt.prompt_execution_context_service.continue_answer_search",
                return_value=("Best supported answer", failed_review),
            ),
        ):
            result = RequestEngine().process(RequestContext("show project dependencies"))

        self.assertEqual("answer", result.action)
        self.assertEqual("Best supported answer", result.text)
        self.assertTrue(result.metadata["answer_review_incomplete"])

    def test_inadequate_trusted_result_does_not_read_unassigned_repair_text(self) -> None:
        execution_context = self._context()
        decision = MagicMock()
        decision.to_dict.return_value = {
            "route": "project_search",
            "provider": "project_search",
            "execution_route": "engine.project_search",
        }
        validation = UnderstandingValidation(True, 0.95, reasons=["clear"])
        dispatch_result = EngineResult(
            "answer",
            "Project Index",
            "Initial deterministic answer",
            metadata={"result_type": "project_index_direct"},
        )
        diagnostic = SimpleNamespace(to_dict=lambda: {"candidates": [], "selected_route": "project_search"})
        trusted_review = {
            "adequate": False,
            "score": 0.5,
            "reviewer": "trusted_deterministic_result",
            "validated_facts": [],
            "context_requests": [],
        }
        with (
            patch("tech_connector.services.prompt.prompt_execution_context_service.build_prompt_execution_context", return_value=execution_context),
            patch("tech_connector.services.prompt.prompt_execution_context_service.validate_prompt_understanding", return_value=validation),
            patch("tech_connector.services.prompt.prompt_route_service.classify_prompt_route", return_value=decision),
            patch("tech_connector.services.route_diagnostics_service.build_route_diagnostic_report", return_value=diagnostic),
            patch("tech_connector.services.prompt.prompt_progress_service.build_prompt_progress_plan", return_value={"stages": []}),
            patch("tech_connector.services.prompt.prompt_dispatch_service.PromptDispatchService.dispatch", return_value=dispatch_result),
            patch("tech_connector.services.prompt.prompt_execution_context_service.review_prompt_answer", return_value=trusted_review),
            patch("tech_connector.services.prompt.prompt_execution_context_service.continue_answer_search") as continue_search,
        ):
            result = RequestEngine().process(RequestContext("show project dependencies"))

        self.assertEqual("answer", result.action)
        self.assertEqual("Initial deterministic answer", result.text)
        self.assertTrue(result.metadata["answer_review_incomplete"])
        continue_search.assert_not_called()


class _ProgressObserverWindow(MainWindowChatRuntimeMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self.messages: list[str] = []
        self.live_process_label = SimpleNamespace(setText=lambda _text: None)

    def append(self, text):
        self.messages.append(str(text))


class PromptProgressObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_long_internal_step_reports_every_fifteen_seconds(self) -> None:
        window = _ProgressObserverWindow()
        now = time.time()
        window._prompt_progress_observers = {
            "main": {
                "active": True,
                "label": "implementation plan",
                "started_at": now - 30,
                "last_event_at": now - PROMPT_PROGRESS_QUIET_SECONDS - 1,
                "last_chat_update_at": now - PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS - 1,
                "last_message": "Inspecting indexed call relationships",
                "last_human_stage": "",
                "observer_notice_sent": False,
            }
        }

        window._tick_prompt_progress_observers()
        self.assertEqual(1, len(window.messages))
        self.assertIn("Inspecting indexed call relationships", window.messages[0])
        self.assertIn("Active step:", window.messages[0])

        window._tick_prompt_progress_observers()
        self.assertEqual(1, len(window.messages))

        state = window._prompt_progress_observers["main"]
        state["last_chat_update_at"] -= PROMPT_PROGRESS_CHAT_INTERVAL_SECONDS + 1
        window._tick_prompt_progress_observers()
        self.assertEqual(2, len(window.messages))
        window.deleteLater()


class _OfficialFlowWindow(MainWindowChatRuntimeMixin, QWidget):
    def __init__(self) -> None:
        QWidget.__init__(self)
        self.input = QLineEdit(self)
        self.attached_images = []
        self.attached_files = []
        self.settings = {"ai_work_memory_enabled": False}
        self.service = SimpleNamespace(last_assistant_output="")
        self.current_file_path = ""
        self.messages = []
        self.statuses = []
        self.finished = False

    def _active_response_roles(self):
        return []

    def _check_capability_gaps(self, _text):
        return False

    def _attachment_context_for_prompt(self):
        return ""

    def _visible_prompt_text(self, text):
        return text

    def _log_ui_diagnostic(self, *_args, **_kwargs):
        return None

    def _start_prompt_progress_observer(self, *_args, **_kwargs):
        return None

    def _stop_prompt_progress_observer(self, *_args, **_kwargs):
        return None

    def _note_prompt_progress_event(self, *_args, **_kwargs):
        return None

    def _append_prompt_understanding(self, _decision):
        return None

    def _append_structured_interaction_cards(self, _result):
        return None

    def _store_pending_chat_continuation(self, _result, _message=""):
        return None

    def handle_engine_activity(self, _event):
        return None

    def update_attachment_strip(self):
        return None

    def project_roots(self):
        return [TOOLS_ROOT]

    def selected_mcphost_model(self):
        return "ollama:qwen3:8b"

    def append(self, text):
        self.messages.append(str(text))

    def set_live_process(self, text):
        self.statuses.append(str(text))
        if str(text).endswith("ready"):
            self.finished = True


class OfficialUiFlowResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_send_message_keeps_qt_event_loop_responsive_during_official_worker(self) -> None:
        window = _OfficialFlowWindow()
        window.input.setText("what file has creat rig?")
        timer_fired = []

        def slow_engine(_engine, _context):
            time.sleep(0.2)
            return EngineResult("answer", "Test", "Worker answer")

        with patch("tech_connector.engine.request_engine.RequestEngine.process", slow_engine):
            QTimer.singleShot(25, lambda: timer_fired.append(True))
            started = time.perf_counter()
            window.send_message()
            returned_after = time.perf_counter() - started
            QTest.qWait(80)
            self.app.processEvents()
            responsive_before_finish = bool(timer_fired) and not window.finished
            deadline = time.perf_counter() + 2.0
            while not window.finished and time.perf_counter() < deadline:
                QTest.qWait(25)
                self.app.processEvents()

        self.assertLess(returned_after, 0.1)
        self.assertTrue(responsive_before_finish)
        self.assertTrue(window.finished)
        self.assertIn("Understanding your request...", window.statuses)
        self.assertIn("Worker answer", "\n".join(window.messages))
        window.request_preparation_worker.wait(1000)
        window.deleteLater()

    def test_elliptical_class_lookup_uses_official_send_message_worker(self) -> None:
        window = _OfficialFlowWindow()
        window.current_file_path = "C:/depot/tools/maya_tools/Rigging/create_rig.py"
        window.input.setText("what class to create a Browse to Directory widget?")

        with patch(
            "tech_connector.services.prompt.prompt_execution_context_service._model_json",
            side_effect=AssertionError("planning or repair model should not run"),
        ):
            window.send_message()
            deadline = time.perf_counter() + 10.0
            while not window.finished and time.perf_counter() < deadline:
                QTest.qWait(25)
                self.app.processEvents()

        response = "\n".join(window.messages)
        self.assertTrue(window.finished)
        self.assertIn("BrowseDirectory", response)
        self.assertIn("custom_widgets.py", response)
        self.assertIn("getExistingDirectory", response)
        self.assertNotIn("Prompt dispatch failed", response)
        window.request_preparation_worker.wait(1000)
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
