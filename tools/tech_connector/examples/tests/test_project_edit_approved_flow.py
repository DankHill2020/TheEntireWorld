from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tech_connector.app.main_window_editor import answer_project_index_request


class TestProjectEditApprovedFlow(unittest.TestCase):
    def test_approved_handoff_uses_shared_workflow_and_returns_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            target = root / "service.py"
            test_path = tests_dir / "test_service.py"
            target.write_text(
                "def render_errors(results: list[dict[str, object]]) -> list[str]:\n"
                "    \"\"\"\n"
                "    Render validation errors.\n"
                "    :param results: validation result dictionaries\n"
                "    :return: concise failure lines\n"
                "    \"\"\"\n"
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
            approval_id = "a" * 64
            approved = {
                "plan": "Approved implementation plan",
                "fingerprint": approval_id,
            }
            workflow = SimpleNamespace(
                status="ready",
                approval_id=approval_id,
                preview=SimpleNamespace(
                    changes=[
                        {
                            "action": "modify",
                            "path": str(target.resolve()),
                            "before": target.read_text(encoding="utf-8"),
                            "after": target.read_text(encoding="utf-8") + "\n# integrated\n",
                        },
                        {
                            "action": "modify",
                            "path": str(test_path.resolve()),
                            "before": test_path.read_text(encoding="utf-8"),
                            "after": test_path.read_text(encoding="utf-8") + "\n# focused coverage\n",
                        },
                    ]
                ),
                errors=[],
                implementation_plan={"objective": objective},
                candidate="",
                readiness_snapshot=lambda: {
                    "ready": True,
                    "status": "ready",
                    "summary": "Validated preview is ready.",
                },
            )

            with patch(
                "tech_connector.services.settings_service.load_settings",
                return_value={"code_model": "coder"},
            ), patch(
                "tech_connector.services.project_edit_workflow_service."
                "run_multi_file_project_edit_workflow",
                return_value=workflow,
            ) as run_workflow:
                _answer, payload = answer_project_index_request(
                    str(target),
                    objective,
                    "project_edit",
                    approved_plan=approved,
                )

            run_workflow.assert_called_once()
            workflow_kwargs = run_workflow.call_args.kwargs
            self.assertEqual(approval_id, workflow_kwargs["approved_plan_id"])
            self.assertTrue(workflow_kwargs["dry_run"])
            self.assertEqual(str(target.resolve()), workflow_kwargs["active_path"])
            self.assertEqual("project_changes", payload["type"])
            self.assertEqual(2, len(payload["changes"]))
            self.assertEqual(approval_id, payload["approval_id"])


if __name__ == "__main__":
    unittest.main()
