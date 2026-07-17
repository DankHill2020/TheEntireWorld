"""Capability/workflow analysis helpers inside the Tech Connector server.

This package is not the canonical project-search index. Structural project
search, unused-file analysis, imports, call sites, and dependency facts are
owned by ``knowledge/build_knowledge_index_v2.py`` and queried through
``services/project_search_service.py`` / ``services/project_service.py``.
Keep this package focused on workflow composition, capability registration, and
legacy planner compatibility unless it is explicitly wired into that v2 index.

Public API:
- ``run_indexer()``: crawl, parse, store symbols, embed, and build the legacy
  planner graph.
- ``query_graph(prompt)``: query the legacy planner graph.
"""

from .run_indexer import run_indexer
from .planner_interface import plan_workflow, query_graph

__all__ = ["run_indexer", "query_graph", "plan_workflow"]
