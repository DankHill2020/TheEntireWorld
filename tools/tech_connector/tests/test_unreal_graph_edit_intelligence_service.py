import unittest

from tech_connector.services.unreal.graph_edit_intelligence_service import (
    build_unreal_graph_edit_intelligence,
)


class TestUnrealGraphEditIntelligenceService(unittest.TestCase):
    def test_blueprint_traversal_guidance_includes_insertion_and_recovery(self):
        guidance = build_unreal_graph_edit_intelligence(
            "Unreal add wall running to BP_Player Event Graph",
            intent_domains=["traversal", "movement"],
            graph_types=["Blueprint"],
            params={"target_asset": "/Game/Characters/BP_Player", "target_graph": "EventGraph"},
        )

        self.assertEqual(guidance["framework"], "unreal_graph_edit_intelligence_v1")
        self.assertIn("State guards and validation", guidance["graph_roles"])
        self.assertTrue(any("traversal" in item.lower() for item in guidance["insertion_strategy"]))
        self.assertTrue(any("snapshot" in item.lower() for item in guidance["preflight_checks"]))
        self.assertTrue(any("rollback" in item.lower() for item in guidance["repair_strategies"]))
        self.assertTrue(any("smoke test" in item.lower() for item in guidance["validation_matrix"]))

    def test_networking_guidance_separates_authority_and_feedback(self):
        guidance = build_unreal_graph_edit_intelligence(
            "Unreal make this replicated with server RPC and client feedback",
            intent_domains=["networking"],
            graph_types=["Blueprint"],
        )

        self.assertTrue(any("authority" in item.lower() for item in guidance["insertion_strategy"]))
        self.assertTrue(any("server rpc" in item.lower() for item in guidance["communication_strategy"]))
        self.assertTrue(any("onrep" in item.lower() for item in guidance["troubleshooting_path"]))
        self.assertTrue(any("server/client" in item.lower() for item in guidance["validation_matrix"]))

    def test_material_guidance_prefers_parameters_and_material_validation(self):
        guidance = build_unreal_graph_edit_intelligence(
            "Unreal edit material graph to add a wetness effect",
            intent_domains=["materials"],
            graph_types=["Material"],
        )

        self.assertTrue(any("material instances" in item.lower() for item in guidance["graph_type_guidance"]))
        self.assertTrue(any("parameter" in item.lower() for item in guidance["repair_strategies"]))
        self.assertTrue(any("compile material" in item.lower() for item in guidance["validation_matrix"]))
        self.assertTrue(any("material math" in item.lower() for item in guidance["layout_plan"]))


if __name__ == "__main__":
    unittest.main()
