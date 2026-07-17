"""Build compact model-ready context packets from local DCC intelligence."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .store import IntelligenceStore, ProjectRef

STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "into", "make", "create", "update", "fix", "tool"}


def keywords(text: str, max_terms: int = 12) -> list[str]:
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
    terms: list[str] = []
    for term in raw:
        t = term.lower()
        if t not in STOPWORDS and t not in terms:
            terms.append(t)
    return terms[:max_terms]


@dataclass
class ContextPacket:
    project: dict[str, Any]
    request: str
    editor_state: dict[str, Any] | None
    selected_refs: list[str]
    relevant_assets: list[dict[str, Any]]
    relevant_symbols: list[dict[str, Any]]
    relevant_api: list[dict[str, Any]]
    relevant_functions: list[dict[str, Any]]
    relevant_capabilities: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    recent_history: list[dict[str, Any]]
    guidance: list[str]

    def to_prompt_text(self) -> str:
        payload = {
            "project": self.project,
            "request": self.request,
            "editor_state": self.editor_state,
            "selected_refs": self.selected_refs,
            "relevant_assets": self.relevant_assets[:10],
            "relevant_symbols": self.relevant_symbols[:15],
            "relevant_api": self.relevant_api[:15],
            "relevant_functions": self.relevant_functions[:10],
            "relevant_capabilities": self.relevant_capabilities[:10],
            "dependencies": self.dependencies[:25],
            "recent_history": self.recent_history[:10],
            "guidance": self.guidance,
        }
        return "DCC_LOCAL_INTELLIGENCE_CONTEXT\n" + json.dumps(payload, indent=2, ensure_ascii=False)


class ContextBuilder:
    def __init__(self, store: IntelligenceStore):
        self.store = store

    def build(self, project: ProjectRef, request: str, dcc: str | None = None) -> ContextPacket:
        dcc = dcc or project.dcc
        state = self.store.latest_snapshot(project.id, dcc)
        selected = []
        if state:
            selected = state.get("selected", []) or []
        terms = keywords(request)
        assets: list[dict[str, Any]] = []
        symbols: list[dict[str, Any]] = []
        api: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        capabilities: list[dict[str, Any]] = []
        for term in terms:
            assets.extend(self.store.search_assets(project.id, term, limit=8))
            symbols.extend(self.store.search_symbols(project.id, dcc, term, limit=8))
            api.extend(self.store.search_python_api(project.id, dcc, term, limit=8))
            functions.extend(self.store.search_functions(project.id, term, limit=8))
            capabilities.extend(self.store.search_capabilities(project.id, term, limit=8))
        assets = self._dedupe(assets, "id")[:20]
        symbols = self._dedupe(symbols, "id")[:30]
        api = self._dedupe(api, "id")[:30]
        functions = self._dedupe(functions, "id")[:20]
        capabilities = self._dedupe(capabilities, "id")[:20]
        refs = [str(x) for x in selected]
        refs += [a.get("asset_path", "") for a in assets[:10]]
        deps = self.store.related_dependencies(project.id, refs, limit=50)
        history = [self.store._row_to_dict(r) for r in self.store.conn.execute(
            "SELECT * FROM execution_history WHERE project_id=? AND dcc=? ORDER BY id DESC LIMIT 10",
            (project.id, dcc),
        ).fetchall()]
        return ContextPacket(
            project={"id": project.id, "dcc": project.dcc, "name": project.name, "root_path": project.root_path},
            request=request,
            editor_state=state,
            selected_refs=refs[:20],
            relevant_assets=assets,
            relevant_symbols=symbols,
            relevant_api=api,
            relevant_functions=functions,
            relevant_capabilities=capabilities,
            dependencies=deps,
            recent_history=history,
            guidance=[
                "Prefer existing capabilities before inventing new scripts.",
                "Use selected/open editor state as the highest-priority context.",
                "For destructive changes, produce a backup/preview plan before execution.",
                "When context is missing, ask the DCC adapter for a fresh snapshot instead of guessing.",
            ],
        )

    @staticmethod
    def _dedupe(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        seen = set()
        out = []
        for item in items:
            marker = item.get(key) or json.dumps(item, sort_keys=True, default=str)
            if marker in seen:
                continue
            seen.add(marker)
            out.append(item)
        return out
