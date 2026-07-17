import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.services.domain_expert_service import DOMAIN_EXPERTS
from tech_connector.services.unreal.blueprint_graph_knowledge_service import (
    blueprint_graph_expert_context,
    persist_blueprint_graph_expert_knowledge,
)


class TestBlueprintGraphExpertKnowledge(unittest.TestCase):
    def test_context_contains_supported_removed_and_layout_paths(self):
        context = blueprint_graph_expert_context()

        self.assertIn("BlueprintGraphEditor", context)
        self.assertIn("default_key_mappings.mappings", context)
        self.assertIn("get_blueprint_variables", context)
        self.assertIn("left-to-right", context)
        self.assertIn("overlapping nodes", context)
        self.assertIn("setter Output_Get", context)
        self.assertIn("new_object", context)
        self.assertIn("get_game_world", context)
        self.assertIn("ObjectIterator(World)", context)
        self.assertIn("editor_request_end_play", context)
        self.assertIn("diagnostics.read_log_errors", context)

    def test_blueprint_expert_references_verified_knowledge_service(self):
        expert = next(item for item in DOMAIN_EXPERTS if item.domain == "unreal.blueprint_graph")

        self.assertIn("blueprint_graph_knowledge_service", expert.required_services)
        self.assertTrue(any("default_key_mappings" in item for item in expert.avoid))
        self.assertTrue(any("overlap" in item for item in expert.validation_steps))

    def test_live_facts_persist_as_validated_contextual_knowledge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "knowledge.jsonl"
            with patch("tech_connector.services.ai_work_memory_service.CONTEXTUAL_KNOWLEDGE_PATH", path):
                count = persist_blueprint_graph_expert_knowledge({})

            self.assertEqual(13, count)
            self.assertEqual(13, len(path.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
