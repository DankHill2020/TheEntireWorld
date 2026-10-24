"""Honest, inspectable coverage report for the project editor surface."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .asset_type_registry import AssetTypeRegistry


def build_engine_capability_report(
    registry: AssetTypeRegistry,
    contract: Mapping[str, Any],
    editor: Any,
) -> dict[str, Any]:
    """Summarize declared capabilities without treating registration as qualification."""

    descriptors = registry.all()
    maturity_counts = Counter(item.maturity for item in descriptors)
    families = []
    for family in registry.families():
        members = registry.all(family=family)
        families.append({
            "name": family,
            "asset_type_count": len(members),
            "maturity_counts": dict(sorted(Counter(item.maturity for item in members).items())),
        })

    operation_groups = []
    declared_operations: set[str] = set()
    for name, operations in sorted(contract.items()):
        if not name.endswith("_operations") or not isinstance(operations, (list, tuple)):
            continue
        names = {str(operation) for operation in operations}
        declared_operations.update(names)
        operation_groups.append({"name": name, "operation_count": len(names)})

    unavailable_operations = sorted(
        name for name in declared_operations if not callable(getattr(editor, name, None))
    )
    asset_types = [{
        "type_id": item.type_id,
        "name": item.display_name,
        "family": item.family,
        "maturity": item.maturity,
        "creatable": item.creatable,
        "importable": item.importable,
        "editor": item.standard_editor_name,
        "api_namespace": item.python_api_namespace,
        "runtime_loader_id": item.runtime_loader_id,
        "cooker_id": item.cooker_id,
        "production_qualified": item.maturity == "production_ready",
    } for item in descriptors]

    return {
        "schema": "tech_connector.engine_capability_report.v1",
        "asset_type_count": len(asset_types),
        "maturity_counts": {
            level: maturity_counts[level]
            for level in ("experimental", "authoring_preview", "runtime_ready", "production_ready")
        },
        "production_qualified_asset_type_count": maturity_counts["production_ready"],
        "families": families,
        "asset_types": asset_types,
        "editor_operation_count": len(declared_operations),
        "operation_groups": operation_groups,
        "unavailable_declared_operations": unavailable_operations,
        "interpretation": (
            "Registry entries and callable editor methods describe available surfaces. "
            "Only production_ready is a production qualification claim; runtime_ready "
            "does not imply platform, performance, recovery, or shipping qualification."
        ),
    }


__all__ = ["build_engine_capability_report"]
