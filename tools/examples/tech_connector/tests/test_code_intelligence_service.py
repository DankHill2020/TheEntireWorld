from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tech_connector.services.code_intelligence_service import (
    build_code_intelligence_packet,
    deterministic_code_answer,
    render_code_intelligence_packet,
)
from tech_connector.services.repo_map_service import render_repo_map
from tech_connector.services.validation_planner_service import plan_validation_for_paths, render_validation_plan


class TestCodeIntelligenceService(unittest.TestCase):
    def test_validation_planner_prefers_compile_for_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tool.py"
            source.write_text("def run():\n    return True\n", encoding="utf-8")

            steps = plan_validation_for_paths([str(source)], project_root=tmp)
            text = render_validation_plan(steps)

            self.assertEqual(1, len(steps))
            self.assertIn("py_compile tool.py", steps[0]["command"])
            self.assertIn("Python syntax", text)

    def test_render_code_intelligence_packet_surfaces_ide_agent_fields(self) -> None:
        packet = {
            "mode": "symbol",
            "scope": "project",
            "can_answer_without_model": True,
            "terms": ["create", "rig"],
            "sufficiency": {
                "answerable": True,
                "confidence": 0.92,
                "recommended_next_stage": "deterministic_answer",
            },
            "repo_map": {
                "file_count": 2,
                "symbol_count": 7,
                "directories": [{"path": "maya_tools", "files": 1, "symbols": 5}],
            },
            "symbols": [
                {
                    "kind": "function",
                    "qualname": "create_full_rig",
                    "path": "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                    "start_line": 10,
                }
            ],
            "validation_plan": [
                {
                    "command": "py_compile create_rig.py",
                    "reason": "Python syntax must pass.",
                    "paths": ["C:/depot/tools/maya_tools/Rigging/create_rig.py"],
                }
            ],
            "project_context": "Exact symbol/source matches:\n[1] create_full_rig",
            "deterministic_answer": "create_full_rig",
        }

        text = render_code_intelligence_packet(packet)

        self.assertIn("Code intelligence packet:", text)
        self.assertIn("Can answer without model: True", text)
        self.assertIn("Repo map: 2 files, 7 symbols", text)
        self.assertIn("create_full_rig", text)
        self.assertEqual("create_full_rig", deterministic_code_answer(packet))

    def test_repo_map_renderer_handles_empty_map(self) -> None:
        text = render_repo_map({"root": "C:/depot/tools", "file_count": 0, "symbol_count": 0})

        self.assertIn("Repo map:", text)
        self.assertIn("Indexed files: 0", text)

    def test_build_packet_is_safe_when_index_is_missing_or_stale(self) -> None:
        packet = build_code_intelligence_packet(
            "What functions create a rig in Maya?",
            active_path="C:/depot/tools/maya_tools/Rigging/create_rig.py",
            limit=5,
            include_repo_map=False,
        )

        self.assertIn(packet["scope"], {"project", "maya_project"})
        self.assertIn("terms", packet)
        self.assertIn("sufficiency", packet)
        self.assertIn("validation_plan", packet)


if __name__ == "__main__":
    unittest.main()
