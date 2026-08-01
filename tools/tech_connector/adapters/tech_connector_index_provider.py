"""Tech Connector index provider adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reasoning_runtime import (
    IndexBuildResult,
    IndexProvider,
    IndexQuery,
    IndexRecord,
    IndexSearchResult,
)


class TechConnectorProjectIndexProvider(IndexProvider):
    """Expose Tech Connector's local project index through a runtime contract."""

    name = "tech_connector_project_index"

    def __init__(self, project_roots: list[str] | None = None, app_service: Any = None) -> None:
        self.project_roots = [str(root) for root in (project_roots or []) if root]
        self.app_service = app_service

    def search(self, query: IndexQuery) -> list[IndexSearchResult]:
        active_path = str(query.metadata.get("active_path") or "")
        if not active_path and self.project_roots:
            active_path = self.project_roots[0]
        symbol_results = self._search_symbols(query, active_path)
        if symbol_results:
            return symbol_results
        try:
            from tech_connector.services.project_search_service import gather_project_search_context

            text = gather_project_search_context(
                query.query,
                active_path=active_path or None,
                limit=query.limit,
                scope=query.scope or None,
            )
        except Exception:
            return []
        text = str(text or "").strip()
        if not text:
            return []
        record = IndexRecord(
            record_id=f"{self.name}:{abs(hash((query.query, active_path, query.scope)))}",
            title="Tech Connector project index result",
            text=text,
            source=self.name,
            kind="project_index_result",
            locator=active_path,
            metadata={"scope": query.scope},
        )
        return [IndexSearchResult(record=record, score=0.75, metadata={"provider": self.name})]

    def _search_symbols(self, query: IndexQuery, active_path: str) -> list[IndexSearchResult]:
        kind = str(query.filters.get("kind") or query.metadata.get("kind") or "")
        try:
            from tech_connector.services.symbol_lookup_service import TechConnectorSymbolLookupProvider
            from reasoning_runtime import SymbolQuery

            root = self.project_roots[0] if self.project_roots else None
            provider = TechConnectorSymbolLookupProvider(project_root=root)
            hits = provider.find_symbols(
                SymbolQuery(
                    query=query.query,
                    kind=kind,
                    scope=query.scope or "project",
                    limit=query.limit,
                    active_path=active_path,
                )
            )
        except Exception:
            return []
        results: list[IndexSearchResult] = []
        for hit in hits:
            title = f"{hit.kind} {hit.qualname or hit.name}".strip()
            text = (
                f"{title}\n"
                f"Path: {hit.path}\n"
                f"Lines: {hit.start_line}-{hit.end_line}\n"
                f"Scope: {hit.source_scope}"
            )
            record = IndexRecord(
                record_id=f"symbol:{hit.symbol_id}",
                title=title,
                text=text,
                source=self.name,
                kind="symbol",
                locator=hit.path,
                metadata={
                    "symbol_id": hit.symbol_id,
                    "name": hit.name,
                    "qualname": hit.qualname,
                    "symbol_kind": hit.kind,
                    "start_line": hit.start_line,
                    "end_line": hit.end_line,
                    "source_scope": hit.source_scope,
                    **hit.metadata,
                },
            )
            results.append(
                IndexSearchResult(
                    record=record,
                    score=hit.score,
                    metadata={"provider": self.name, "lane": "symbol_lookup"},
                )
            )
        return results

    def build_or_update(
        self,
        roots: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> IndexBuildResult:
        metadata = dict(metadata or {})
        build_fn = getattr(self.app_service, "build_project_index", None)
        if callable(build_fn):
            try:
                result = build_fn(roots)
            except Exception as exc:
                return IndexBuildResult(ok=False, errors=(str(exc),), metadata=metadata)
            indexed_count = int(getattr(result, "indexed_count", 0) or 0)
            return IndexBuildResult(ok=True, indexed_count=indexed_count, metadata=metadata)
        return IndexBuildResult(
            ok=False,
            errors=("Tech Connector project index build is not available from this adapter.",),
            metadata=metadata,
        )

    def status(self) -> dict[str, Any]:
        roots = list(self.project_roots)
        db_path = ""
        exists = False
        try:
            from tech_connector.models.constants import project_index_db_path

            db = project_index_db_path(Path(roots[0]) if roots else None)
            db_path = str(db)
            exists = db.exists()
        except Exception:
            pass
        return {
            "ok": exists,
            "provider": self.name,
            "project_roots": roots,
            "db_path": db_path,
        }
