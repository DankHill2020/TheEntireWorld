from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.app.main_window_editor import answer_project_index_request
from tech_connector.services.project_edit_agent_service import (
    ProjectEditLeafWorkUnits,
    build_project_edit_plan_from_leaf_work_units,
    project_edit_leaf_work_units_handoff,
    project_edit_plan_fingerprint,
)


class TestProjectEditApprovedFlow(unittest.TestCase):
    def test_approved_handoff_skips_whole_patch_and_runs_three_leaf_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            target = root / "service.py"
            test_path = tests_dir / "test_service.py"
            target.write_text(
                "def render_errors(results):\n"
                "    \"\"\"Render errors.\"\"\"\n"
                "    return [str(item.get('message', '')) for item in results if not item.get('ok')]\n",
                encoding="utf-8",
            )
            test_path.write_text(
                "import unittest\n\n"
                "from service import render_errors\n\n"
                "class TestService(unittest.TestCase):\n"
                "    def test_render_errors(self):\n"
                "        self.assertEqual([], render_errors([]))\n",
                encoding="utf-8",
            )
            objective = (
                "In service.py, add a reusable function named summarize_validation_failures that accepts "
                "validation result dictionaries and returns concise failure lines. Reuse it in render_errors "
                "and add focused unittest coverage."
            )
            work_units = ProjectEditLeafWorkUnits(
                helper_name="summarize_validation_failures",
                target_path=str(target.resolve()),
                integration_symbol="render_errors",
                integration_source=target.read_text(encoding="utf-8"),
                test_path=str(test_path.resolve()),
                test_anchor_symbol="TestService.test_render_errors",
                test_anchor_source=(
                    "def test_render_errors(self):\n"
                    "    self.assertEqual([], render_errors([]))"
                ),
                owner_module="service",
                target_revision=hashlib.sha1(target.read_bytes()).hexdigest(),
                test_revision=hashlib.sha1(test_path.read_bytes()).hexdigest(),
            )
            grounded_plan = build_project_edit_plan_from_leaf_work_units(objective, work_units)
            plan_text = (
                f"Implementation Plan\nObjective: {objective}\nBest target: {target}\n"
                "Reuse render_errors and TestService.test_render_errors.\n"
                "Proposed changes: define summarize_validation_failures, integrate it into render_errors, "
                f"and add focused unittest coverage in {test_path}.\n"
                "Verify imports, parse, compile, and focused unittest.\n"
                "Plan self-check: target, integration, test scope, and verification match the request.\n"
                "Approval produces a preview only and does not write files."
            )
            approved = {
                "plan": plan_text,
                "fingerprint": project_edit_plan_fingerprint(grounded_plan),
                "leaf_work_units": project_edit_leaf_work_units_handoff(work_units),
            }
            calls: list[dict] = []

            def query_model(**kwargs):
                calls.append(kwargs)
                prompt = kwargs["user_prompt"]
                if "Return only one complete top-level function" in prompt:
                    return (
                        "def summarize_validation_failures(results: list[dict[str, object]]) -> list[str]:\n"
                        "    \"\"\"Return messages for failed validation results.\"\"\"\n"
                        "    return [str(item.get('message', 'Validation failed.')) for item in results "
                        "if not item.get('ok')]"
                    )
                if "complete replacement for render_errors" in prompt:
                    return (
                        "def render_errors(results):\n"
                        "    \"\"\"Render errors.\"\"\"\n"
                        "    return summarize_validation_failures(results)"
                    )
                if "Return one complete unittest method" in prompt:
                    return (
                        "import unittest\n"
                        "from service import summarize_validation_failures\n\n"
                        "class TestGenerated(unittest.TestCase):\n"
                        "    def test_summarize_validation_failures(self):\n"
                        "        self.assertEqual([], summarize_validation_failures([]))"
                    )
                self.fail("Unexpected whole-patch or repair model call")

            with patch(
                "tech_connector.services.settings_service.load_settings",
                return_value={"code_model": "coder"},
            ), patch(
                "tech_connector.knowledge.search.query_ollama_text",
                side_effect=query_model,
            ):
                _answer, payload = answer_project_index_request(
                    str(target),
                    objective,
                    "project_edit",
                    approved_plan=approved,
                )

            self.assertEqual(3, len(calls))
            self.assertEqual(["micro", "small", "micro"], [call["coder_preference"] for call in calls])
            self.assertTrue(all(not isinstance(call.get("response_format"), dict) for call in calls))
            self.assertEqual("project_changes", payload["type"])
            self.assertEqual(2, len(payload["changes"]))
            self.assertEqual(target.read_text(encoding="utf-8"), work_units.integration_source)


if __name__ == "__main__":
    unittest.main()
