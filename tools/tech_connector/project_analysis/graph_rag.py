# graph_rag.py
"""Small knowledge graph layer for the project-analysis package.

The original project_analysis package used NetworkX directly. This version keeps
that behavior when NetworkX is installed, and falls back to a tiny in-memory
directed graph so importing the package does not require an extra dependency.
"""
from __future__ import annotations

import pickle
import re
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
        imports = list(symbol.get("imports", []) or [])
        if kind == "import":
            imports.append(name)
        for imported_name in dict.fromkeys(str(value) for value in imports if value):
            import_node = f"import:{imported_name}"
            self.add_node(import_node, type="import", name=imported_name)
            self.add_edge(symbol_node, "imports", import_node)
        calls = [
            *list(symbol.get("calls", []) or []),
            *list(symbol.get("unreal_refs", []) or []),
        ]
        for called_name in dict.fromkeys(str(value) for value in calls if value):
            call_node = f"call:{called_name}"
            self.add_node(call_node, type="call", name=called_name)
            self.add_edge(symbol_node, "calls", call_node)
        for operation_key in dict.fromkeys(
            str(value) for value in symbol.get("operation_keys", []) or [] if value
        ):
            capability_node = f"capability:{operation_key}"
            self.add_node(capability_node, type="capability", name=operation_key)
            self.add_edge(symbol_node, "provides", capability_node)
        app = str(symbol.get("app") or "")
        if app:
            app_node = f"host:{app}"
            self.add_node(app_node, type="host", name=app)
            self.add_edge(symbol_node, "targets", app_node)

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
        query_terms = {
            token for token in re.findall(r"[a-z][a-z0-9_]{1,}", q)
            if token not in {"a", "an", "and", "for", "of", "the", "to", "with"}
        }
        scored = []
        if nx:
            iterator = self.g.nodes(data=True)
        else:
            iterator = self.g.nodes.items()
        for node, attrs in iterator:
            haystack = " ".join([node, str(attrs.get("name", "")), str(attrs.get("path", ""))]).lower()
            score = sum(1 for token in query_terms if token in haystack)
            if q and q in haystack:
                score += 10
            if score:
                scored.append((score, {"node": node, **dict(attrs)}))
        scored.sort(key=lambda item: (
            -item[0],
            str(item[1].get("name") or item[1].get("node") or "").casefold(),
        ))
        return [item for _score, item in scored[:limit]]

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
