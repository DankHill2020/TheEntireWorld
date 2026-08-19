"""Regression tests for portable capability registry storage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tech_connector.services.capability_registry import CapabilityRegistry
from tech_connector.services.capability_registry_storage import (
    capability_registry_payload_exists,
    load_capability_registry_payload,
)


def test_registry_loads_sibling_shards_for_json_path(tmp_path: Path) -> None:
    """
    Verifies that a JSON registry path discovers its sibling shard directory.

    :param tmp_path: Temporary test directory.
    :return: None.
    """

    registry_path = tmp_path / "capability_registry.json"
    shard_dir = tmp_path / "capability_registry"
    shard_dir.mkdir()
    (shard_dir / "entries_0000.json").write_text(
        json.dumps({"entries": [{"id": "custom", "name": "Custom Tool"}]}),
        encoding="utf-8",
    )
    (shard_dir / "manifest.json").write_text(
        json.dumps({"schema": "1.0", "shards": [{"path": "entries_0000.json"}]}),
        encoding="utf-8",
    )

    assert capability_registry_payload_exists(registry_path)
    registry = CapabilityRegistry(registry_path)
    assert registry.get("custom") is not None
    assert registry.get("bridge_maya") is not None


def test_registry_supplies_builtin_bridges_without_generated_data(tmp_path: Path) -> None:
    """
    Verifies that portable bridge capabilities do not require generated files.

    :param tmp_path: Temporary test directory.
    :return: None.
    """

    registry = CapabilityRegistry(tmp_path / "missing.json")

    assert registry.stats()["total"] == 10
    assert registry.get("bridge_blender") is not None
    assert registry.get("bridge_unreal") is not None


def test_registry_rejects_shards_outside_registry_directory(tmp_path: Path) -> None:
    """
    Verifies that an untrusted manifest cannot read a parent-directory file.

    :param tmp_path: Temporary test directory.
    :return: None.
    """

    shard_dir = tmp_path / "capability_registry"
    shard_dir.mkdir()
    (shard_dir / "manifest.json").write_text(
        json.dumps({"schema": "1.0", "shards": [{"path": "../outside.json"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes its directory"):
        load_capability_registry_payload(shard_dir)
