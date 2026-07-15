from __future__ import annotations

import sys
import unittest

from services.unreal.capability_registry import validate_unreal_capability_registry
from services.unreal.unreal_resolvers import _extract_query_string


class TestUnrealExecutionPipeline(unittest.TestCase):

    def test_capability_registry_health(self) -> None:
        """Verify the capability registry is 100% healthy and matches operations."""
        report = validate_unreal_capability_registry()
        self.assertTrue(report["ok"], f"Capability registry invalid: {report}")
        self.assertEqual(report["registered_count"], 134)

    def test_extract_query_string_resolver(self) -> None:
        """Verify extraction from nested resolver results handles types gracefully."""
        self.assertEqual(_extract_query_string("direct_str"), "direct_str")
        self.assertEqual(_extract_query_string({"ref": "val_ref"}), "val_ref")
        self.assertEqual(_extract_query_string({"path": "val_path"}), "val_path")
        self.assertEqual(_extract_query_string({"name": "val_name"}), "val_name")
        self.assertEqual(_extract_query_string(["list_item"]), "list_item")
        self.assertEqual(_extract_query_string([]), "")
        self.assertEqual(_extract_query_string(None), "")
