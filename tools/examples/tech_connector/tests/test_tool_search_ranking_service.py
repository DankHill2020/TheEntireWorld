from __future__ import annotations

import unittest

from tech_connector.services.tool_search_ranking_service import tool_query_rank
from tech_connector.ui.pipeline_node_view import pipeline_tool_query_rank


class ToolSearchRankingServiceTest(unittest.TestCase):
    def test_exact_function_token_match_beats_broad_context_match(self):
        terms = ["create", "rig", "mapping"]
        rows = [
            {
                "name": "create_rig_arm_space_switches",
                "label_lower": "function: create_rig_arm_space_switches [setup_hik.py]",
                "path_lower": "c:/depot/tools/maya_tools/rigging/mocap/setup_hik.py",
                "detail_lower": "creates rig controls from a mapping",
                "priority": 10,
            },
            {
                "name": "create_rig_mapping",
                "label_lower": "function: create_rig_mapping [setup_hik.py]",
                "path_lower": "c:/depot/tools/maya_tools/rigging/mocap/setup_hik.py",
                "priority": 10,
            },
        ]

        ranked = sorted(rows, key=lambda row: tool_query_rank(row, terms))

        self.assertEqual("create_rig_mapping", ranked[0]["name"])

    def test_pipeline_tool_rank_uses_same_name_first_order(self):
        terms = ["create", "rig", "mapping"]
        mapping = {
            "name": "create_rig_mapping",
            "label_lower": "function: create_rig_mapping",
            "path_lower": "",
            "priority": 10,
        }
        arm_switches = {
            "name": "create_rig_arm_space_switches",
            "label_lower": "function: create_rig_arm_space_switches",
            "path_lower": "mapping helpers",
            "priority": 10,
        }

        self.assertLess(pipeline_tool_query_rank(mapping, terms), pipeline_tool_query_rank(arm_switches, terms))


if __name__ == "__main__":
    unittest.main()
