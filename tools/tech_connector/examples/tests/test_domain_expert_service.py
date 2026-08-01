from __future__ import annotations

import unittest

from tech_connector.services.domain_expert_service import (
    BROAD_DOMAIN_CATALOG,
    expert_advisory_context,
    expert_registry_summary,
    select_domain_experts,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


class TestDomainExpertService(unittest.TestCase):
    def test_registry_covers_initial_maya_and_unreal_tool_areas(self) -> None:
        summary = expert_registry_summary()
        self.assertEqual(summary["framework"], "modular_domain_experts_v1")
        self.assertIn("layered senior judgment", summary["expert_definition"])
        self.assertIn("architecture_and_boundaries", summary["knowledge_pyramid"])
        maya_domains = set(summary["applications"]["maya"])
        unreal_domains = set(summary["applications"]["unreal"])
        python_domains = set(summary["applications"]["python"])
        self.assertIn("maya.node_editor", maya_domains)
        self.assertIn("maya.hypershade", maya_domains)
        self.assertIn("maya.rigging", maya_domains)
        self.assertIn("unreal.blueprint_graph", unreal_domains)
        self.assertIn("unreal.control_rig", unreal_domains)
        self.assertIn("python.ui_integration", python_domains)
        self.assertIn("python.testing_validation", python_domains)
        self.assertIn("python.async_responsiveness", python_domains)
        self.assertIn("python.index_search", python_domains)
        self.assertIn("python.patch_application", python_domains)

    def test_expert_profiles_include_senior_level_dimensions(self) -> None:
        matches = select_domain_experts(
            "In Unreal refactor this Blueprint-heavy prototype into components and subsystems",
            {"host": "unreal", "route": "unreal_capability", "mutation_scope": "dcc_asset_mutation"},
            limit=8,
        )
        by_domain = {match["domain"]: match for match in matches}
        self.assertIn("unreal.blueprint_graph", by_domain)
        blueprint = by_domain["unreal.blueprint_graph"]
        self.assertIn("Actor Components", blueprint["architecture_topics"])
        self.assertTrue(any("Blueprint" in item for item in blueprint["tradeoffs"]))
        self.assertTrue(any("unresolved pins" in item for item in blueprint["debugging_strategies"]))
        self.assertTrue(any("redirector" in item for item in blueprint["production_concerns"]))
        self.assertTrue(any("refactor" in item.lower() for item in blueprint["expert_brief"]))

    def test_registry_has_broad_coverage_for_every_supported_app_family(self) -> None:
        summary = expert_registry_summary()
        for app in (
            "maya",
            "unreal",
            "blender",
            "houdini",
            "substance_painter",
            "motionbuilder",
            "unity",
            "github",
            "perforce",
            "slack",
            "discord",
            "atlassian",
            "mobile",
            "pipeline",
        ):
            self.assertIn(app, summary["applications"])
            self.assertGreaterEqual(len(summary["applications"][app]), 1, app)

        for app, entries in BROAD_DOMAIN_CATALOG.items():
            domains = set(summary["applications"].get(app, []))
            for key, _label, _terms in entries:
                self.assertIn(f"{app}.{key}", domains)

    def test_catalog_experts_are_observe_mode_and_do_not_own_execution(self) -> None:
        matches = select_domain_experts(
            "In Blender Geometry Nodes add a procedural bevel setup",
            {"host": "blender", "route": "dcc_execute", "mutation_scope": "dcc_scene_mutation"},
        )
        by_domain = {match["domain"]: match for match in matches}
        self.assertIn("blender.geometry_nodes", by_domain)
        self.assertEqual(by_domain["blender.geometry_nodes"]["mode"], "observe")
        self.assertIn("Expert is advisory", by_domain["blender.geometry_nodes"]["assumptions"][0])
        self.assertTrue(any("existing" in risk.lower() for risk in by_domain["blender.geometry_nodes"]["risks"]))

    def test_houdini_is_recognized_as_supported_dcc_host(self) -> None:
        decision = classify_prompt_route("Houdini create a SOP node and connect it")
        data = decision.to_dict()
        self.assertEqual(data["host"], "houdini")
        domains = {expert["domain"] for expert in data["domain_experts"]}
        self.assertIn("houdini.sops", domains)
        labels = {expert["id"] for expert in data["visible_progress"]["expert_lenses"]}
        self.assertIn("dcc_technical_director", labels)

    def test_production_system_prompt_selects_senior_system_expert(self) -> None:
        matches = select_domain_experts(
            "Build me a procedural traversal system with mantling, ledge grab, Motion Matching, GAS, and replication",
            {"host": "unreal", "route": "unreal_capability", "mutation_scope": "dcc_asset_mutation"},
            limit=8,
        )
        by_domain = {match["domain"]: match for match in matches}
        self.assertIn("production.traversal", by_domain)
        traversal = by_domain["production.traversal"]
        self.assertIn("prediction and replication", traversal["architecture_topics"])
        self.assertIn("GAS_ability_per_traversal_action", traversal["implementation_approaches"])
        self.assertTrue(any("Do not reduce a production-system request" in item for item in traversal["risks"]))
        self.assertTrue(any("architecture:" in item for item in traversal["expert_brief"]))

    def test_soulslike_prompt_selects_combat_expert_and_review_expert(self) -> None:
        matches = select_domain_experts(
            "Build me a Souls-like combat system and review the architecture for long term maintainability",
            {"host": "unreal", "route": "unreal_capability", "mutation_scope": "dcc_asset_mutation"},
            limit=10,
        )
        domains = {match["domain"] for match in matches}
        self.assertIn("production.combat", domains)
        self.assertIn("review.principal_engineer", domains)

    def test_code_edit_prompt_selects_specialist_code_experts(self) -> None:
        matches = select_domain_experts(
            "Fix the Qt chat UI freeze during indexing, add progress status, patch safely, and add regression tests",
            {"route": "code_edit", "intent_category": "project_edit", "mutation_scope": "code_change"},
            limit=10,
        )
        domains = {match["domain"] for match in matches}
        self.assertIn("python.ui_integration", domains)
        self.assertIn("python.async_responsiveness", domains)
        self.assertIn("python.index_search", domains)
        self.assertIn("python.testing_validation", domains)
        self.assertIn("python.patch_application", domains)

    def test_maya_node_editor_prompt_selects_node_editor_expert(self) -> None:
        matches = select_domain_experts(
            "In Maya Node Editor connect ctrl.tx to joint.rx and keep the graph clean",
            {"host": "maya", "route": "dcc_execute", "mutation_scope": "dcc_scene_mutation"},
        )
        by_domain = {match["domain"]: match for match in matches}
        self.assertIn("maya.node_editor", by_domain)
        self.assertEqual(by_domain["maya.node_editor"]["mode"], "advise")
        self.assertIn("validate_data_flow", by_domain["maya.node_editor"]["recommended_operations"])
        self.assertIn("Expert is advisory", by_domain["maya.node_editor"]["assumptions"][0])

    def test_maya_hypershade_prompt_selects_hypershade_without_execution(self) -> None:
        matches = select_domain_experts(
            "Maya Hypershade add a color correction between the file texture and material",
            {"host": "maya", "route": "dcc_execute", "mutation_scope": "dcc_scene_mutation"},
        )
        by_domain = {match["domain"]: match for match in matches}
        self.assertIn("maya.hypershade", by_domain)
        self.assertEqual(by_domain["maya.hypershade"]["mode"], "observe")
        self.assertIn("Preserve existing material appearance", " ".join(by_domain["maya.hypershade"]["responsibilities"]))

    def test_unreal_blueprint_prompt_selects_graph_expert(self) -> None:
        decision = classify_prompt_route("In Unreal edit this Blueprint graph and connect the new node safely")
        data = decision.to_dict()
        domains = {expert["domain"] for expert in data["domain_experts"]}
        self.assertIn("unreal.blueprint_graph", domains)
        labels = {expert["id"] for expert in data["visible_progress"]["expert_lenses"]}
        self.assertIn("unreal_engineer", labels)
        self.assertIn("unreal.blueprint_graph", labels)

    def test_advisory_context_is_compact_and_execution_safe(self) -> None:
        text = expert_advisory_context(
            "Maya rigging add control with constraint",
            {"host": "maya", "route": "dcc_execute"},
            limit=2,
        )
        self.assertIn("Domain expert advisory context:", text)
        self.assertIn("Stable existing services still own execution", text)


if __name__ == "__main__":
    unittest.main()
