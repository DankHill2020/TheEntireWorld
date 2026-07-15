from __future__ import annotations

import unittest

from services.project_service import (
    build_project_edit_target_prompt,
    build_project_understanding_contract,
    format_edit_target_context,
)


class TestProjectCodeGenerationGrounding(unittest.TestCase):
    def _discovery(self) -> dict:
        return {
            "scope": "strict_project",
            "project_roots": ["C:/depot/tools"],
            "active_path": "C:/depot/tools/custom_qt/custom_widgets.py",
            "terms": ["rig", "docstring", "function"],
            "confidence": "high",
            "best_target": {
                "path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                "score": 42,
            },
            "candidates": [
                {
                    "path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                    "score": 42,
                    "symbols": [
                        {
                            "kind": "function",
                            "qualname": "create_full_rig",
                            "name": "create_full_rig",
                            "start_line": 12,
                            "end_line": 20,
                            "source": "def create_full_rig(arm_joints=None):\n    return {}\n",
                        }
                    ],
                    "chunks": [],
                }
            ],
        }

    def test_target_context_names_project_roots_best_target_and_symbols(self) -> None:
        context = format_edit_target_context(self._discovery())

        self.assertIn("Project roots: C:/depot/tools", context)
        self.assertIn("Best target: C:/depot/tools/maya_tools/Rigging/create_rig.py", context)
        self.assertIn("function create_full_rig lines 12-20", context)
        self.assertIn("def create_full_rig", context)

    def test_target_context_excludes_virtualenv_candidates(self) -> None:
        discovery = self._discovery()
        discovery["candidates"].append(
            {
                "path": "C:/depot/tools/.venv/Lib/site-packages/pip/_internal/cache.py",
                "score": 999,
                "symbols": [],
                "chunks": [{"text": "dependency code should not be offered as an edit target"}],
            }
        )

        context = format_edit_target_context(discovery)

        self.assertIn("create_rig.py", context)
        self.assertNotIn("site-packages", context)
        self.assertNotIn("dependency code should not be offered", context)

    def test_understanding_contract_requires_index_grounding_and_verification(self) -> None:
        context = format_edit_target_context(self._discovery())
        contract = build_project_understanding_contract(
            "Add missing docstrings to rig functions",
            context,
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertIn("Project understanding contract:", contract)
        self.assertIn("Assigned project roots: C:/depot/tools", contract)
        self.assertIn("Target confidence: high", contract)
        self.assertIn("Best indexed target: C:/depot/tools/maya_tools/Rigging/create_rig.py", contract)
        self.assertIn("Do not invent files, classes, functions, imports, arguments, call sites, or APIs", contract)
        self.assertIn("py_compile", contract)
        self.assertIn("focused unit tests", contract)

    def test_project_edit_prompt_matches_codex_like_grounded_patch_flow(self) -> None:
        context = format_edit_target_context(self._discovery())
        prompt = build_project_edit_target_prompt(
            "Add missing docstrings to rig functions",
            context,
            active_path="C:/depot/tools/custom_qt/custom_widgets.py",
        )

        self.assertIn("Project understanding contract:", prompt)
        self.assertIn("Project facts used.", prompt)
        self.assertIn("Target file/symbol decision with confidence.", prompt)
        self.assertIn("Implementation plan.", prompt)
        self.assertIn("Patch or exact code change.", prompt)
        self.assertIn("Verification command or manual validation.", prompt)
        self.assertIn("<modify_file path=", prompt)
        self.assertIn("Match the style and architecture of the indexed target file.", prompt)
        self.assertIn("Use existing project helpers before writing new abstractions.", prompt)


if __name__ == "__main__":
    unittest.main()
