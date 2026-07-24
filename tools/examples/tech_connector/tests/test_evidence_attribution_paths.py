from __future__ import annotations

import unittest

from tech_connector.services.reasoning.evidence_ranking_service import rank_target_candidates


class TestEvidenceAttributionPaths(unittest.TestCase):
    def test_ranked_targets_include_structured_attributions(self) -> None:
        ranked = rank_target_candidates(
            "Fix BP_LesterPhoenix using the active editor context",
            [{"path": "C:/project/Content/BP_LesterPhoenix.uasset", "score": 2.0, "summary": "Phoenix actor blueprint"}],
            active_file="C:/project/Content/BP_LesterPhoenix.uasset",
            active_line=42,
            open_files=["C:/project/Content/BP_LesterPhoenix.uasset"],
        )

        self.assertTrue(ranked)
        payload = ranked[0].to_dict()
        self.assertIn("attributions", payload)
        self.assertTrue(payload["attributions"])
        self.assertTrue(any(item["source"] == "active_editor_context" for item in payload["attributions"]))
        cursor_paths = [
            item for item in payload["attributions"]
            if item["type"] == "active_cursor_line"
        ]
        self.assertEqual(42, cursor_paths[0]["metadata"]["line"])


if __name__ == "__main__":
    unittest.main()
