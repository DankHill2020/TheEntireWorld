from __future__ import annotations

import unittest
from unittest.mock import patch

from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine


class ProjectIndexEngineFastPathTests(unittest.TestCase):
    def test_function_file_lookup_bypasses_semantic_planning_but_reports_understanding(self) -> None:
        prompt = "what file has a function to find joints?"
        context = RequestContext(
            text=prompt,
            current_file_path="C:/depot/tools/custom_qt/custom_widgets.py",
            project_roots=["C:/depot/tools"],
        )

        with patch(
            "tech_connector.services.prompt_execution_context_service._model_json",
            side_effect=AssertionError("semantic planning model should not run"),
        ), patch(
            "tech_connector.services.semantic_execution_contract_service.build_semantic_execution_contract",
            side_effect=AssertionError("semantic contract should not run"),
        ):
            result = RequestEngine(progress=lambda _event: None).process(context)

        self.assertEqual("answer", result.action)
        self.assertEqual("Project Index", result.label)
        self.assertEqual("project_index_direct", result.metadata.get("result_type"))
        self.assertEqual(
            "simple_project_index_fast_path",
            result.metadata["prompt_execution_context"]["planning_result"]["planning_mode"],
        )
        self.assertIn("What I understood", result.text)
        self.assertIn("Find the source file", result.text)
        self.assertIn("setup_hik.py", result.text.replace("\\", "/"))
        self.assertIn("find_face_joints", result.text)

    def test_asset_search_clause_cannot_hide_live_unreal_mutation(self) -> None:
        prompt = (
            "In the live Unreal project, build a playable ledge traversal animation system. "
            "Search existing project and ArtSource animation assets first; when the required "
            "contextual clips are absent, download them, retarget them to the resolved target, "
            "import them, integrate the animations, compile, and run PIE verification."
        )
        context = RequestContext(
            text=prompt,
            project_roots=["C:/depot/tools", "C:/depot/ArtSource"],
            extras={"host_hint": "unreal"},
        )

        engine = RequestEngine(progress=lambda _event: None)
        with patch.object(engine, "_fast_live_unreal_request", return_value=None), patch(
            "tech_connector.services.project_search_service.answer_simple_project_index_question",
            return_value="A misleading search-only answer.",
        ):
            result = engine._fast_simple_project_index_lookup(context)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
