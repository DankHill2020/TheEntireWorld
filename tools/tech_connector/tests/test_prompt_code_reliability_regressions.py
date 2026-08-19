"""Regression tests for prompt-generated code and disposable proof reliability."""

from __future__ import annotations

import ast
from pathlib import Path

from tech_connector.services.project_edit_agent_service import (
    build_project_edit_multi_file_candidate,
    preview_project_edit_agent_response,
)

from tech_connector.services.project_edit_workflow_part_06 import (
    _expanded_ephemeral_behavior_rows,
    _ephemeral_harness_behavior_contract_errors,
    _parse_ephemeral_behavior_harness,
    _repair_unapproved_ephemeral_rejections,
)


def test_behavior_capsule_infers_exact_callable_from_ordered_steps() -> None:
    """Bind class-owned behavior to its single verified executable callable."""

    plan = {
        "behavior_contracts": [
            {
                "behavior_id": "R5_B01",
                "requirement_id": "R5",
                "production_owners": [
                    {
                        "path": "connector/image_viewer/cache.py",
                        "symbol": "ImageCache",
                        "callable_name": "",
                    }
                ],
                "polarity": "success",
                "operation": "refresh recency without changing insertion time",
                "expected_observations": ["the recently read value remains live"],
                "execution_steps": [
                    {
                        "step_id": "S1",
                        "phase": "act",
                        "callable_name": "get",
                        "instruction": "Call get for the existing key.",
                    }
                ],
            }
        ]
    }

    rows = _expanded_ephemeral_behavior_rows(plan)

    assert len(rows) == 1
    assert rows[0]["owner_execution"]["callable_name"] == "get"
    assert rows[0]["owner_execution"]["must_invoke_exact_callable"] is True
    assert rows[0]["test_name"].startswith("test_imagecache_get_")
from tech_connector.services.project_edit_workflow_part_07 import (
    _ephemeral_harness_call_graph_errors,
    _repair_ephemeral_harness_call_graph,
)


def test_removing_only_unapproved_rejection_keeps_harness_parseable() -> None:
    """Keep an empty repaired test syntactically valid for focused regeneration."""

    source = """\
__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {"test_cache": ["R1_B01"]}
import unittest


class TestCache(unittest.TestCase):
    def test_cache(self):
        with self.assertRaises(ValueError):
            object()
"""
    behavior_rows = [
        {
            "behavior_id": "R1_B01",
            "operation": "cache stores a valid value",
            "polarity": "success",
            "expected_observations": ["the value can be retrieved"],
            "production_owners": [],
        }
    ]

    repaired, repairs = _repair_unapproved_ephemeral_rejections(
        source,
        behavior_rows,
    )

    tree = ast.parse(repaired)
    test = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "test_cache"
    )
    assert repairs == ["test_cache: removed unapproved assertRaises proof"]
    assert len(test.body) == 1
    assert isinstance(test.body[0], ast.Pass)


def test_empty_repaired_proof_is_reported_as_harness_owned() -> None:
    """Expose a removed oracle as missing proof instead of production failure."""

    source = """\
__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {"test_cache": ["R1_B01"]}
import unittest


class TestCache(unittest.TestCase):
    def test_cache(self):
        pass
"""
    behavior_rows = [
        {
            "behavior_id": "R1_B01",
            "operation": "cache stores a valid value",
            "polarity": "success",
            "expected_observations": ["the value can be retrieved"],
            "production_owners": [],
        }
    ]

    errors = _ephemeral_harness_behavior_contract_errors(
        source,
        behavior_rows,
        generated_files=[],
    )

    assert any("executes no observable assertion" in error for error in errors)


def test_bare_assert_is_an_observable_disposable_proof() -> None:
    """Accept ordinary Python asserts as executable harness observations."""

    source = '''__TECH_CONNECTOR_BEHAVIOR_BINDINGS__ = {"test_value": ["R1_B01"]}

def test_value():
    result = normalize_value("x")
    assert result == "x"
'''
    behavior_rows = [{
        "behavior_id": "R1_B01",
        "operation": "normalize a value",
        "polarity": "success",
        "expected_observations": ["the normalized value is returned"],
        "production_owners": [{
            "path": "connector/value.py",
            "symbol": "normalize_value",
            "callable_name": "normalize_value",
        }],
    }]

    errors = _ephemeral_harness_behavior_contract_errors(
        source,
        behavior_rows,
        generated_files=[(
            "connector/value.py",
            "",
            "def normalize_value(value):\n    return value\n",
        )],
    )

    assert not any("executes no observable assertion" in error for error in errors)


def test_behavior_sidecar_is_multiline_and_preserves_runtime_proof() -> None:
    """Keep orchestrator metadata within source limits without changing tests."""

    behavior_ids = [f"R{index}_B01" for index in range(1, 10)]
    source = """\
import unittest
from data.merge_patch import merge_patch


class TestMergePatch(unittest.TestCase):
    def test_merge_patch(self):
        result = merge_patch({"a": 1}, {"b": 2})
        self.assertEqual(result, {"a": 1, "b": 2})
"""

    normalized, parse_errors = _parse_ephemeral_behavior_harness(
        source,
        behavior_ids,
        ["test_merge_patch"] * len(behavior_ids),
    )

    assert parse_errors == []
    assert max(len(line) for line in normalized.splitlines()) <= 100
    assert "result = merge_patch" in normalized
    assert "self.assertEqual" in normalized
    ast.parse(normalized)

    rows = [
        {
            "behavior_id": behavior_id,
            "operation": "merge a mapping patch",
            "polarity": "success",
            "expected_observations": ["the merged mapping is returned"],
            "production_owners": [
                {
                    "path": "data/merge_patch.py",
                    "symbol": "merge_patch",
                    "callable_name": "merge_patch",
                }
            ],
        }
        for behavior_id in behavior_ids
    ]
    errors = _ephemeral_harness_behavior_contract_errors(
        normalized,
        rows,
        generated_files=[
            (
                "data/merge_patch.py",
                "",
                "def merge_patch(document, patch):\n    return document | patch\n",
            )
        ],
    )

    assert errors == []


def test_authorized_disposable_harness_ignores_presentation_only_defects(
    tmp_path: Path,
) -> None:
    """Keep internal proof formatting from rejecting valid production code."""

    production_path = tmp_path / "value.py"
    production_path.write_text(
        "def value():\n    return 1\n",
        encoding="utf-8",
    )
    harness_path = tmp_path.parent / "test_disposable_long_line.py"
    harness = (
        "from value import value\n\n"
        "def test_value():\n"
        "    expected = " + repr("x" * 140) + "\n"
        "    assert value() == 1 and expected\n"
    )
    candidate = build_project_edit_multi_file_candidate([
        (str(production_path), "", production_path.read_text(encoding="utf-8")),
        (str(harness_path), "", harness),
    ])

    preview = preview_project_edit_agent_response(
        candidate,
        project_root=str(tmp_path),
        allowed_external_paths={str(harness_path)},
        request_prompt=(
            "Run the supplied disposable unittest module as an authoritative "
            "validation harness. It is not an output artifact."
        ),
    )

    assert not any(
        "Generated Python presentation defects" in error
        for error in preview.errors
    )


def test_external_host_patch_may_share_public_callable_leaf_name() -> None:
    """Distinguish a native dependency from its same-named wrapper."""

    production = '''def configure_asset(asset_path, value):
    import host_api
    return host_api.NativeLibrary.configure_asset(asset_path, value)
'''
    harness = '''from unittest.mock import patch
from connector.game_engine.wrappers import configure_asset

def test_configure_asset():
    with patch("host_api.NativeLibrary.configure_asset"):
        configure_asset("asset", {})
'''

    errors = _ephemeral_harness_call_graph_errors(
        harness,
        [("connector/game_engine/wrappers.py", "", production)],
        request_prompt="Configure an asset through the native host wrapper.",
    )

    assert not any("never patch the public callable" in error for error in errors)


def test_function_local_host_import_uses_importable_patch_target() -> None:
    """Patch a function-local host module directly instead of through its owner."""

    production = '''def configure_asset(asset_path, value):
    import host_api
    return host_api.NativeLibrary.configure_asset(asset_path, value)
'''
    harness = '''from unittest.mock import patch

@patch("connector.game_engine.wrappers.host_api.NativeLibrary.configure_asset")
def test_configure_asset(mock_configure_asset):
    assert configure_asset("asset", {}) is not None
'''

    initial_errors = _ephemeral_harness_call_graph_errors(
        harness,
        [("connector/game_engine/wrappers.py", "", production)],
        request_prompt="Configure an asset through the host wrapper.",
    )

    repaired, notes = _repair_ephemeral_harness_call_graph(
        harness,
        [("connector/game_engine/wrappers.py", "", production)],
        request_prompt="Configure an asset through the host wrapper.",
        project_root=".",
    )

    assert any("function-local host imports" in error for error in initial_errors)
    assert notes
    assert "host_api.NativeLibrary.configure_asset" in repaired
    assert "wrappers.host_api.NativeLibrary.configure_asset" not in repaired
