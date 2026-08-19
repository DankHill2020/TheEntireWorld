"""Plan dependency-closed conversion of engine projects into TC runtime graphs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


SEMANTIC_DOMAINS = (
    "scene",
    "geometry",
    "material",
    "animation",
    "animation_state_machine",
    "ik_rig",
    "motion_matching",
    "gameplay_graph",
    "input",
    "physics",
    "vfx",
    "audio",
    "navigation",
    "ui",
    "code",
)

CONVERSION_STATES = ("native", "translate", "bake", "source_proxy", "unsupported")


@dataclass(frozen=True)
class EngineProjectAdapter:
    provider: str
    extraction_mode: str
    domain_strategies: dict[str, str]
    limitations: tuple[str, ...] = ()

    def strategy_for(self, domain: str) -> str:
        return self.domain_strategies.get(domain, "source_proxy")


@dataclass(frozen=True)
class EngineSemanticNode:
    source_id: str
    domain: str
    native_type: str
    dependencies: tuple[str, ...] = ()
    display_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.domain not in SEMANTIC_DOMAINS:
            raise ValueError(f"Unknown engine semantic domain: {self.domain}")


@dataclass(frozen=True)
class EngineProjectManifest:
    provider: str
    project_id: str
    engine_version: str
    nodes: tuple[EngineSemanticNode, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


_COMMON_STRATEGIES = {
    "scene": "translate",
    "geometry": "translate",
    "material": "translate",
    "animation": "translate",
    "animation_state_machine": "translate",
    "ik_rig": "translate",
    "motion_matching": "translate",
    "gameplay_graph": "translate",
    "input": "translate",
    "physics": "translate",
    "vfx": "bake",
    "audio": "translate",
    "navigation": "bake",
    "ui": "source_proxy",
    "code": "source_proxy",
}

_ADAPTERS = {
    "unreal": EngineProjectAdapter(
        provider="unreal",
        extraction_mode="compatible_engine_editor_plugin",
        domain_strategies=dict(_COMMON_STRATEGIES),
        limitations=(
            "Blueprint and native-code behavior require node-by-node semantic translation.",
            "Custom engine plug-ins remain source proxies until a TC translator is registered.",
        ),
    ),
    "unity": EngineProjectAdapter(
        provider="unity",
        extraction_mode="compatible_engine_editor_package",
        domain_strategies=dict(_COMMON_STRATEGIES),
        limitations=(
            "MonoBehaviour and package behavior require serialized-field and code translation.",
            "Custom render-pipeline nodes remain source proxies until a TC translator is registered.",
        ),
    ),
}


def engine_project_adapters() -> dict[str, dict[str, Any]]:
    """Return the registered full-project extraction contracts."""
    return {name: asdict(adapter) for name, adapter in _ADAPTERS.items()}


def plan_engine_project_conversion(
    manifest: EngineProjectManifest,
    requested_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Plan a dependency-closed conversion without claiming execution succeeded."""
    provider = manifest.provider.strip().lower()
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ValueError(f"No engine-project adapter is registered for '{provider}'.")

    node_map = {node.source_id: node for node in manifest.nodes}
    roots = list(dict.fromkeys(requested_ids or node_map.keys()))
    missing_roots = [source_id for source_id in roots if source_id not in node_map]
    ordered_ids, missing_dependencies, cycles = _dependency_order(node_map, roots)

    operations = []
    for source_id in ordered_ids:
        node = node_map[source_id]
        strategy = adapter.strategy_for(node.domain)
        operations.append(
            {
                "source_id": source_id,
                "display_name": node.display_name or source_id,
                "domain": node.domain,
                "native_type": node.native_type,
                "strategy": strategy,
                "dependencies": list(node.dependencies),
                "preserve_source_payload": strategy in {"bake", "source_proxy", "unsupported"},
            }
        )

    counts = {state: 0 for state in CONVERSION_STATES}
    for operation in operations:
        counts[operation["strategy"]] += 1
    blockers = [
        f"Unsupported semantic node: {item['source_id']} ({item['native_type']})"
        for item in operations
        if item["strategy"] == "unsupported"
    ]
    runtime_dependencies = [
        f"Source proxy requires a translator: {item['source_id']} ({item['native_type']})"
        for item in operations
        if item["strategy"] == "source_proxy"
    ]
    blockers.extend(f"Missing requested node: {source_id}" for source_id in missing_roots)
    blockers.extend(
        f"Missing dependency: {owner_id} -> {dependency_id}"
        for owner_id, dependency_id in missing_dependencies
    )

    return {
        "schema": "tech_connector.engine_project_conversion_plan.v1",
        "provider": provider,
        "project_id": manifest.project_id,
        "engine_version": manifest.engine_version,
        "extraction_mode": adapter.extraction_mode,
        "requested_roots": roots,
        "dependency_closed": not missing_roots and not missing_dependencies,
        "standalone_runtime_ready": not blockers and not runtime_dependencies and not cycles,
        "executable_after_conversion": not blockers and not runtime_dependencies and not cycles,
        "operations": operations,
        "strategy_counts": counts,
        "missing_dependencies": [list(item) for item in missing_dependencies],
        "cycles": cycles,
        "blockers": blockers,
        "runtime_dependencies": runtime_dependencies,
        "limitations": list(adapter.limitations),
    }


def _dependency_order(
    node_map: dict[str, EngineSemanticNode], roots: list[str]
) -> tuple[list[str], list[tuple[str, str]], list[list[str]]]:
    ordered: list[str] = []
    visited: set[str] = set()
    active: list[str] = []
    missing: list[tuple[str, str]] = []
    cycles: list[list[str]] = []

    def visit(source_id: str) -> None:
        if source_id in visited:
            return
        if source_id in active:
            start = active.index(source_id)
            cycle = active[start:] + [source_id]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if source_id not in node_map:
            return
        active.append(source_id)
        for dependency_id in node_map[source_id].dependencies:
            if dependency_id not in node_map:
                pair = (source_id, dependency_id)
                if pair not in missing:
                    missing.append(pair)
            else:
                visit(dependency_id)
        active.pop()
        visited.add(source_id)
        ordered.append(source_id)

    for root in roots:
        visit(root)
    return ordered, missing, cycles
