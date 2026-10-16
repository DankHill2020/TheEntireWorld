"""Dependency graph analysis with package-cost and cycle diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .asset_database_service import AssetDatabase


@dataclass(frozen=True)
class AssetDependencyNode:
    asset_id: str
    name: str
    type_id: str
    path: str
    source_bytes: int
    derived_bytes: int
    package_bytes: int
    depth: int
    relationship: str
    missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetDependencyEdge:
    owner_asset_id: str
    dependency_asset_id: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetDependencyGraph:
    root_asset_id: str
    nodes: tuple[AssetDependencyNode, ...]
    edges: tuple[AssetDependencyEdge, ...]
    cycles: tuple[tuple[str, ...], ...]
    source_bytes: int
    derived_bytes: int
    package_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_asset_id": self.root_asset_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "cycles": [list(cycle) for cycle in self.cycles],
            "source_bytes": self.source_bytes,
            "derived_bytes": self.derived_bytes,
            "package_bytes": self.package_bytes,
        }


class AssetDependencyGraphService:
    """Build a connected asset graph without counting shared dependencies twice."""

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database

    def analyze(
        self, root_asset_id: str, *, include_referencers: bool = True, max_depth: int = 32,
    ) -> AssetDependencyGraph:
        root = str(root_asset_id)
        if self.database.asset(root) is None:
            raise KeyError(f"Unknown asset: {root}")
        depths = {root: 0}
        relationships = {root: "Selected"}
        pending = [root]
        edge_map: dict[tuple[str, str], str] = {}
        while pending:
            current = pending.pop(0)
            depth = depths[current]
            if depth >= max(0, int(max_depth)):
                continue
            neighbors = [(current, dependency, kind, "Dependency") for dependency, kind in self.database.dependency_edges(current)]
            if include_referencers:
                neighbors.extend((owner, current, kind, "Referencer") for owner, kind in self.database.referencer_edges(current))
            for owner, dependency, kind, relationship in neighbors:
                edge_map[(owner, dependency)] = kind
                other = dependency if owner == current else owner
                if other not in depths:
                    depths[other] = depth + 1
                    relationships[other] = relationship
                    pending.append(other)

        nodes = []
        for asset_id, depth in sorted(depths.items(), key=lambda item: (item[1], item[0])):
            record = self.database.asset(asset_id)
            if record is None:
                nodes.append(AssetDependencyNode(asset_id, asset_id, "missing", "", 0, 0, 0, depth, relationships[asset_id], True))
                continue
            derived_bytes = sum(
                artifact.path.stat().st_size for artifact in self.database.derived_artifacts(asset_id)
                if artifact.path.is_file()
            )
            try:
                path = record.source_path.relative_to(self.project_root).as_posix()
            except ValueError:
                path = str(record.source_path)
            nodes.append(AssetDependencyNode(
                asset_id, record.source_path.name, record.asset_type, path, int(record.size),
                int(derived_bytes), int(record.size) + int(derived_bytes), depth,
                relationships[asset_id], False,
            ))
        edges = tuple(
            AssetDependencyEdge(owner, dependency, kind)
            for (owner, dependency), kind in sorted(edge_map.items())
            if owner in depths and dependency in depths
        )
        cycles = self._cycles(tuple(depths), edges)
        source_bytes = sum(node.source_bytes for node in nodes)
        derived_bytes = sum(node.derived_bytes for node in nodes)
        return AssetDependencyGraph(root, tuple(nodes), edges, cycles, source_bytes, derived_bytes, source_bytes + derived_bytes)

    @staticmethod
    def _cycles(asset_ids: tuple[str, ...], edges: tuple[AssetDependencyEdge, ...]) -> tuple[tuple[str, ...], ...]:
        adjacency = {asset_id: [] for asset_id in asset_ids}
        for edge in edges:
            adjacency.setdefault(edge.owner_asset_id, []).append(edge.dependency_asset_id)
        index = 0
        indices: dict[str, int] = {}
        low: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[tuple[str, ...]] = []

        def visit(node: str) -> None:
            nonlocal index
            indices[node] = low[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for neighbor in adjacency.get(node, ()):
                if neighbor not in indices:
                    visit(neighbor)
                    low[node] = min(low[node], low[neighbor])
                elif neighbor in on_stack:
                    low[node] = min(low[node], indices[neighbor])
            if low[node] == indices[node]:
                component = []
                while stack:
                    value = stack.pop()
                    on_stack.remove(value)
                    component.append(value)
                    if value == node:
                        break
                if len(component) > 1 or node in adjacency.get(node, ()):
                    components.append(tuple(sorted(component)))

        for asset_id in sorted(adjacency):
            if asset_id not in indices:
                visit(asset_id)
        return tuple(sorted(components))


__all__ = ["AssetDependencyEdge", "AssetDependencyGraph", "AssetDependencyGraphService", "AssetDependencyNode"]
