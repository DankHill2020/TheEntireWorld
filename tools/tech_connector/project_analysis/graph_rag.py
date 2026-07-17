# graph_rag.py
"""Small knowledge graph layer for the project-analysis package.

The original project_analysis package used NetworkX directly. This version keeps
that behavior when NetworkX is installed, and falls back to a tiny in-memory
directed graph so importing the package does not require an extra dependency.
"""
from __future__ import annotations

import pickle
from collections import deque
from pathlib import Path
from typing import Any, Iterable, List, Tuple

try:
    import networkx as nx
except Exception:  # pragma: no cover - exercised only without networkx
    nx = None


class _FallbackDiGraph:
    def __init__(self):
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def add_node(self, node: str, **attrs):
        self.nodes.setdefault(node, {}).update(attrs)

    def add_edge(self, src: str, dst: str, **attrs):
        self.add_node(src)
        self.add_node(dst)
        self.edges.setdefault(src, []).append((dst, attrs))

    def number_of_nodes(self) -> int:
        return len(self.nodes)

    def number_of_edges(self) -> int:
        return sum(len(v) for v in self.edges.values())


class KnowledgeGraph:
    """Directed graph of files, symbols, imports, and capability relationships."""

    def __init__(self):
        self.g = nx.DiGraph() if nx else _FallbackDiGraph()

    def add_node(self, node: str, **attrs):
        self.g.add_node(node, **attrs)

    def add_edge(self, src: str, rel: str, dst: str, **attrs):
        attrs = {"relation": rel, **attrs}
        if nx:
            self.g.add_edge(src, dst, **attrs)
        else:
            self.g.add_edge(src, dst, **attrs)

    def add_symbol(self, symbol: dict[str, Any]):
        file_path = str(symbol.get("file", ""))
        name = str(symbol.get("name", ""))
        kind = str(symbol.get("type", symbol.get("kind", "symbol")))
        if not file_path or not name:
            return
        file_node = f"file:{file_path}"
        symbol_node = f"{kind}:{file_path}:{name}"
        self.add_node(file_node, type="file", path=file_path)
        self.add_node(
            symbol_node,
            type=kind,
            name=name,
            file=file_path,
            lineno=symbol.get("lineno", symbol.get("start_line")),
        )
        self.add_edge(file_node, "defines", symbol_node)
        if kind == "import":
            import_node = f"import:{name}"
            self.add_node(import_node, type="import", name=name)
            self.add_edge(file_node, "imports", import_node)

    def add_symbols(self, symbols: Iterable[dict[str, Any]]):
        for symbol in symbols:
            self.add_symbol(symbol)

    def query_path(self, start: str, goal: str) -> List[Tuple[str, str, str]]:
        """Return ``(source, relation, destination)`` triples for a shortest path."""
        if nx:
            try:
                nodes = nx.shortest_path(self.g, start, goal)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return []
            return [
                (a, self.g.edges[a, b].get("relation", ""), b)
                for a, b in zip(nodes, nodes[1:])
            ]

        if start not in self.g.nodes or goal not in self.g.nodes:
            return []
        queue = deque([(start, [])])
        seen = {start}
        while queue:
            node, path = queue.popleft()
            if node == goal:
                return path
            for dest, attrs in self.g.edges.get(node, []):
                if dest in seen:
                    continue
                seen.add(dest)
                queue.append((dest, path + [(node, attrs.get("relation", ""), dest)]))
        return []

    def related_to(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Return graph nodes whose name/path contains ``query``."""
        q = (query or "").lower()
        results = []
        if nx:
            iterator = self.g.nodes(data=True)
        else:
            iterator = self.g.nodes.items()
        for node, attrs in iterator:
            haystack = " ".join([node, str(attrs.get("name", "")), str(attrs.get("path", ""))]).lower()
            if q in haystack:
                results.append({"node": node, **dict(attrs)})
            if len(results) >= limit:
                break
        return results

    def save(self, path: str | Path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            pickle.dump(self.g, f)

    @classmethod
    def load(cls, path: str | Path) -> "KnowledgeGraph":
        graph = cls()
        with Path(path).open("rb") as f:
            graph.g = pickle.load(f)
        return graph

