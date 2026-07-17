# planner_interface.py
"""Planner-facing query helpers for project-analysis data."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .file_crawler import load_config
from .graph_rag import KnowledgeGraph
from .symbol_db import query_symbols


def _graph_path() -> Path:
    cfg = load_config()
    return Path(cfg.get("graph_pickle", Path(__file__).with_name("graph.pkl")))


def query_graph(prompt: str, limit: int = 20) -> dict[str, Any]:
    """Return symbols and graph nodes related to ``prompt``.

    This is intentionally structured and deterministic so the UI/model layer can
    use it as context without guessing which project assets or code symbols exist.
    """
    query = (prompt or "").strip()
    symbols = query_symbols(query) if query else []
    related_nodes: list[dict[str, Any]] = []
    graph_file = _graph_path()
    graph_available = graph_file.exists()
    if graph_available and query:
        try:
            related_nodes = KnowledgeGraph.load(graph_file).related_to(query, limit=limit)
        except Exception:
            graph_available = False

    return {
        "query": query,
        "symbols": symbols[:limit],
        "graph_nodes": related_nodes[:limit],
        "graph_available": graph_available,
    }


def plan_workflow(goal: str, context_nodes: list | None = None) -> dict[str, Any]:
    """Compatibility wrapper for the older project_analysis planner API."""
    context = context_nodes if context_nodes is not None else query_graph(goal).get("symbols", [])
    return {
        "goal": goal,
        "steps": [],
        "context": context,
        "note": "Use registered capabilities/workflows to turn this context into executable steps.",
    }

