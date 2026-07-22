from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tech_connector.bridges.unreal.unreal_intelligence import ensure_project, open_store
from tech_connector.services.unreal.evidence_driven_feature_synthesis_service import (
    build_feature_research_plan,
    promote_verified_feature_recipe,
    validate_synthesized_feature_spec,
)
from tech_connector.services.unreal.semantic_project_index_service import (
    _scan_project_art_sources,
    assess_project_visibility,
    exclude_unreal_semantic_paths,
    open_semantic_store,
    query_semantic_project_index,
    record_unreal_runtime_observation,
)


class UnrealSemanticProjectIndexTests(unittest.TestCase):
    def test_project_art_sources_are_searchable_with_probe_evidence(self) -> None:
        with TemporaryDirectory() as root:
            root_path = Path(root)
            rig = root_path / "ArtSource" / "Rigs" / "mocap_rigs" / "MannyRig_v01.fbx"
            rig.parent.mkdir(parents=True)
            rig.write_bytes(b"fbx probe")
            manifest = root_path / ".ai_studio" / "intelligence" / "artsource_asset_evidence.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                '{"assets":{"' + rig.as_posix() + '":{"role":"maya_hik_manny_retarget_target","confidence":1.0}}}',
                encoding="utf-8",
            )
            store = open_semantic_store(root)
            project = ensure_project(store, root)
            coverage = _scan_project_art_sources(
                store, project.id, project_root=root, live_project_dir=root
            )
            store.close()

            result = query_semantic_project_index("Manny HIK retarget", project_root=root)
            self.assertTrue(coverage["complete"])
            self.assertEqual(1, coverage["indexed"])
            self.assertEqual("maya_hik_manny_retarget_target", result["entities"][0]["metadata"]["role"])

    def test_partial_sight_recommends_adding_knowledge(self) -> None:
        with TemporaryDirectory() as root:
            store = open_semantic_store(root)
            project = ensure_project(store, root)
            store.add_semantic_index_run(
                project.id,
                "Unreal",
                status="partial",
                coverage={
                    "asset_catalog": {"complete": True},
                    "blueprint_topology": {"complete": False, "indexed": 1, "total": 12},
                },
                completed_at="2026-07-19T00:00:00+00:00",
            )
            store.close()

            visibility = assess_project_visibility(
                ["asset_catalog", "blueprint_topology"], project_root=root
            )
            self.assertEqual("partial", visibility["sight"])
            self.assertTrue(visibility["knowledge_choice"]["required"])
            self.assertEqual("add_knowledge_first", visibility["knowledge_choice"]["recommended"])

    def test_runtime_visibility_requires_matching_passed_scenario(self) -> None:
        with TemporaryDirectory() as root:
            store = open_semantic_store(root)
            project = ensure_project(store, root)
            store.add_semantic_index_run(
                project.id,
                "Unreal",
                status="complete",
                coverage={"runtime_world": {"complete": False}},
                completed_at="2026-07-19T00:00:00+00:00",
            )
            store.close()
            record_unreal_runtime_observation(
                "wall_contact_climb",
                status="passed",
                assertions={"entered_climb": True},
                evidence={"frame_samples": 20},
                project_root=root,
            )

            matching = assess_project_visibility(
                ["runtime_world"], project_root=root, scenario_key="wall_contact_climb"
            )
            missing = assess_project_visibility(
                ["runtime_world"], project_root=root, scenario_key="different_scenario"
            )
            self.assertEqual("complete", matching["sight"])
            self.assertEqual("partial", missing["sight"])

    def test_semantic_query_returns_entities_and_relations(self) -> None:
        with TemporaryDirectory() as root:
            store = open_semantic_store(root)
            project = ensure_project(store, root)
            store.upsert_semantic_entity(
                project.id,
                "Unreal",
                entity_key="asset:/Game/BP_Player",
                entity_kind="blueprint",
                display_name="BP_Player",
                path="/Game/BP_Player",
                source="test",
            )
            store.upsert_semantic_relation(
                project.id,
                "Unreal",
                source_key="asset:/Game/BP_Player",
                relation="owns_graph",
                target_key="asset:/Game/BP_Player::graph:EventGraph",
                source="test",
            )
            store.close()

            result = query_semantic_project_index("BP Player", project_root=root)
            self.assertTrue(result["ok"])
            self.assertTrue(result["entities"])
            self.assertEqual("owns_graph", result["relations"][0]["relation"])

    def test_explicit_exclusion_removes_asset_from_retrieval(self) -> None:
        with TemporaryDirectory() as root:
            store = open_semantic_store(root)
            project = ensure_project(store, root)
            store.upsert_semantic_entity(
                project.id,
                "Unreal",
                entity_key="asset:/Game/BadClimb",
                entity_kind="animation",
                display_name="BadClimb",
                path="/Game/BadClimb",
                source="test",
            )
            store.close()

            excluded = exclude_unreal_semantic_paths(
                ["/Game/BadClimb"], reason="context-invalid motion", project_root=root
            )
            self.assertTrue(excluded["ok"])
            self.assertEqual([], query_semantic_project_index("BadClimb", project_root=root)["entities"])

    def test_unknown_system_builds_generic_research_contract(self) -> None:
        plan = build_feature_research_plan(
            "Build a gravity inversion puzzle mechanic",
            research_mode={"official_docs": True, "web_techniques": True},
        )
        dimensions = {row["id"] for row in plan["contract_dimensions"]}
        self.assertIn("stimulus", dimensions)
        self.assertIn("verification", dimensions)
        self.assertEqual("add_knowledge_first", plan["knowledge_choice"]["default"])

    def test_unproven_spec_cannot_be_learned(self) -> None:
        with TemporaryDirectory() as root:
            recipe_path = Path(root) / "recipes.jsonl"
            result = promote_verified_feature_recipe(
                {"request": "Build anything"},
                {"blueprints_compiled": True},
                path=recipe_path,
            )
            self.assertFalse(result["ok"])
            self.assertFalse(result["learned"])
            self.assertFalse(recipe_path.exists())

    def test_complete_spec_requires_callable_postconditions_and_asset_checks(self) -> None:
        spec = {
            "stimuli": ["input"],
            "observations": ["trace"],
            "guards": ["valid hit"],
            "states": ["idle", "active"],
            "effects": ["movement"],
            "presentation": ["animation"],
            "assets": [{"role": "motion", "compatibility_checks": ["skeleton"]}],
            "failure_paths": ["cancel"],
            "runtime_scenarios": ["activate and recover"],
            "operations": [{"operation": "test", "callable": "module.fn", "postconditions": ["state active"]}],
            "evidence": [
                {
                    "source_url": "https://dev.epicgames.com/",
                    "source_kind": "official_docs",
                    "claim": "API contract",
                    "applies_to_version": "5.8",
                }
            ],
        }
        self.assertTrue(validate_synthesized_feature_spec(spec)["ok"])


if __name__ == "__main__":
    unittest.main()
