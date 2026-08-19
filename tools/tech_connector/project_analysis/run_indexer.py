# run_indexer.py
"""Indexer entrypoint for the Tech Connector project-analysis package."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .ast_parser import parse_file
from .embed_store import embed_text
from .file_crawler import crawl_files, get_included_extensions
from .graph_rag import KnowledgeGraph
from .symbol_db import insert_symbols

try:
    from .capability_registry import register_from_symbol
except Exception:  # pragma: no cover - import guard for standalone use
    def register_from_symbol(_symbol):
        return None


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the local project-analysis YAML config."""
    path = Path(config_path) if config_path else Path(__file__).with_name("config.yaml")
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    for key in ("project_root", "sqlite_db", "graph_file", "graph_pickle"):
        value = config.get(key)
        if value and not Path(value).is_absolute():
            config[key] = str((path.parent / value).resolve())
    return config


def run_indexer(
    project_root: str | None = None,
    *,
    store_embeddings: bool | None = None,
    register_capabilities: bool = True,
) -> dict[str, Any]:
    """Crawl, parse, store symbols, optionally embed files, and build graph data.

    Returns a small summary dict so callers can show progress/results in the UI.
    """
    cfg = load_config()
    root = project_root or cfg.get("project_root")
    if not root:
        raise ValueError("project_root is required in config.yaml or as an argument")

    extensions = get_included_extensions(cfg)
    graph_path = Path(
        cfg.get("graph_file")
        or cfg.get("graph_pickle")
        or Path(__file__).with_name("graph.json")
    )
    embed_model = cfg.get("embed_model", "nomic-embed-text")
    should_embed = bool(cfg.get("enable_embeddings", False)) if store_embeddings is None else bool(store_embeddings)

    graph = KnowledgeGraph()
    files_seen = 0
    symbols_seen = 0
    capabilities_seen = 0
    embeddings_seen = 0
    errors: list[str] = []

    for file_path in crawl_files(root, extensions):
        files_seen += 1
        path = Path(file_path)
        try:
            symbols = parse_file(str(path))
        except Exception as exc:
            errors.append(f"{path}: parse failed: {exc}")
            continue

        if symbols:
            insert_symbols(symbols)
            graph.add_symbols(symbols)
            symbols_seen += len(symbols)
            if register_capabilities:
                for symbol in symbols:
                    try:
                        if register_from_symbol(symbol):
                            capabilities_seen += 1
                    except Exception as exc:
                        errors.append(f"{path}: capability registration failed: {exc}")

        if should_embed:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                embed_text(text, model=embed_model)
                embeddings_seen += 1
            except Exception as exc:
                errors.append(f"{path}: embedding failed: {exc}")

    unreal_summary = {}
    try:
        from tech_connector.services.ai_project_intelligence import ingest_unreal_if_connected

        unreal_summary = ingest_unreal_if_connected(root, mode="quick")
    except Exception as exc:
        unreal_summary = {"ok": False, "error": str(exc)}

    graph.save(graph_path)
    summary = {
        "project_root": str(Path(root).resolve()),
        "files": files_seen,
        "symbols": symbols_seen,
        "capabilities": capabilities_seen,
        "embeddings": embeddings_seen,
        "graph": str(graph_path),
        "errors": errors,
        "unreal": unreal_summary,
    }
    print(
        "Indexed {files} files, {symbols} symbols, {capabilities} capabilities. Graph: {graph}".format(
            **summary
        )
    )
    return summary


if __name__ == "__main__":
    run_indexer()
