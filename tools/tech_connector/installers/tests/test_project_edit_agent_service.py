from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.change_history_service import load_change_session, undo_change_session
from services.project_edit_agent_service import (
    apply_project_edit_agent_response,
    build_code_agent_adaptive_plan,
    build_project_edit_agent_request,
    build_project_edit_model_stages,
    model_for_project_edit_stage,
    preview_project_edit_agent_response,
    render_code_agent_expert_context,
    render_code_agent_adaptive_plan,
    select_code_agent_experts,
    render_project_edit_agent_report,
    validate_project_edit_paths,
)
from services.project_service import discover_edit_targets, format_edit_target_context, build_project_edit_target_prompt


class TestProjectEditAgentService(unittest.TestCase):
    ACTIVE_UI_FILE = "C:/depot/tools/custom_qt/custom_widgets.py"

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
        self.assertIn("Do not emit XML patches.", stages[0].user_prompt)
        self.assertIn("<modify_file path=", stages[1].user_prompt)
        self.assertLessEqual(len(stages[0].user_prompt), 7000)
        self.assertLessEqual(len(stages[1].user_prompt), 12000)
        self.assertEqual("local_model_serial", stages[0].resource_lane)
        self.assertEqual(4096, stages[0].num_ctx)
        self.assertEqual("local_plan", stages[0].model_tier)
        self.assertFalse(stages[0].prefer_coder)
        self.assertEqual("local_code", stages[1].model_tier)
        self.assertTrue(stages[1].prefer_coder)

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
            "router_local_code": "qwen2.5-coder:14b",
            "model": "ollama:qwen3:14b",
        }

        self.assertEqual("qwen3:8b", model_for_project_edit_stage(stages[0], settings))
        self.assertEqual("qwen2.5-coder:14b", model_for_project_edit_stage(stages[1], settings))

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
            self.assertEqual("applied_with_validation_errors", result.status)
            self.assertIn("failed: py_compile broken.py", report)
            self.assertIn("Warnings / Errors:", report)

    def test_create_file_is_supported_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = """<create_file path="new_tool.py">
def created():
    return True
</create_file>"""

            result = apply_project_edit_agent_response(response, project_root=str(root))
            report = render_project_edit_agent_report(result)

            self.assertTrue(result.ok)
            self.assertTrue((root / "new_tool.py").exists())
            self.assertIn("create", report)
            self.assertIn("py_compile new_tool.py", report)

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
