"""IDE-style code intelligence facade for project prompts.

This service is the deterministic front door before model synthesis. It gathers
symbol facts, usages, repo-map context, validation candidates, and sufficiency
signals from existing Tech Connector services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CodeIntelligencePacket:
    objective: str
    mode: str
    scope: str
    active_path: str = ""
    terms: tuple[str, ...] = field(default_factory=tuple)
    repo_map: dict[str, Any] = field(default_factory=dict)
    symbols: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    usages: dict[str, Any] = field(default_factory=dict)
    project_context: str = ""
    sufficiency: dict[str, Any] = field(default_factory=dict)
    validation_plan: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    deterministic_answer: str = ""

    @property
    def can_answer_without_model(self) -> bool:
        return bool(self.sufficiency.get("answerable")) and bool(self.deterministic_answer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "mode": self.mode,
            "scope": self.scope,
            "active_path": self.active_path,
            "terms": list(self.terms),
            "repo_map": self.repo_map,
            "symbols": list(self.symbols),
            "usages": self.usages,
            "project_context": self.project_context,
            "sufficiency": self.sufficiency,
            "validation_plan": list(self.validation_plan),
            "deterministic_answer": self.deterministic_answer,
            "can_answer_without_model": self.can_answer_without_model,
        }


def build_code_intelligence_packet(
    objective: str,
    *,
    active_path: str | None = None,
    limit: int = 20,
    include_repo_map: bool = True,
) -> dict[str, Any]:
    """Gather deterministic IDE-agent context for code/search/edit prompts."""

    from knowledge.search import extract_code_search_terms, search_index_symbols, search_index_usages
    from services.project_search_service import (
        build_deterministic_project_search_answer,
        detect_project_search_mode,
        detect_search_scope,
        gather_project_search_context,
    )
    from services.rag_sufficiency_service import evaluate_project_rag_sufficiency
    from services.validation_planner_service import plan_validation_for_paths

    text = objective or ""
    scope = detect_search_scope(text)
    mode = detect_project_search_mode(text)
    terms = tuple(extract_code_search_terms(text)[:12])
    project_context = gather_project_search_context(text, active_path=active_path, limit=limit, scope=scope)
    sufficiency = evaluate_project_rag_sufficiency(
        text,
        project_context,
        intent="project_edit" if mode == "target_edit" else "project_search",
    )
    deterministic_answer = ""
    if sufficiency.answerable:
        deterministic_answer = build_deterministic_project_search_answer(text, active_path, project_context)
    project_roots = _project_roots_from_context(project_context)
    symbols = tuple(
        search_index_symbols(
            list(terms),
            limit=min(limit, 20),
            active_path=active_path,
            scope=scope,
            project_roots=project_roots,
        )
        if terms
        else []
    )
    usages = search_index_usages(
        text,
        limit=min(max(limit, 10), 50),
        active_path=active_path,
        scope=scope,
        project_roots=project_roots,
    )
    repo_map = {}
    if include_repo_map:
        from services.repo_map_service import build_repo_map

        repo_map = build_repo_map(
            project_root=project_roots[0] if project_roots else None,
            scope=scope,
            max_dirs=12,
            max_files=16,
        )
    validation_paths = _candidate_paths(symbols, usages, active_path=active_path)
    validation_plan = tuple(
        plan_validation_for_paths(
            validation_paths,
            project_root=project_roots[0] if project_roots else None,
        )
    )
    return CodeIntelligencePacket(
        objective=text.strip(),
        mode=str(mode),
        scope=scope,
        active_path=str(active_path or ""),
        terms=terms,
        repo_map=repo_map,
        symbols=symbols,
        usages=usages,
        project_context=project_context,
        sufficiency=sufficiency.to_dict(),
        validation_plan=validation_plan,
        deterministic_answer=deterministic_answer,
    ).to_dict()


def render_code_intelligence_packet(packet: dict[str, Any] | None, *, max_context_chars: int = 5000) -> str:
    packet = dict(packet or {})
    if not packet:
        return ""
    lines = [
        "Code intelligence packet:",
        f"Mode: {packet.get('mode') or 'unknown'}",
        f"Scope: {packet.get('scope') or 'project'}",
        f"Can answer without model: {bool(packet.get('can_answer_without_model'))}",
    ]
    terms = packet.get("terms") or []
    if terms:
        lines.append("Terms: " + ", ".join(str(term) for term in terms[:12]))
    suff = dict(packet.get("sufficiency") or {})
    if suff:
        lines.append(
            "RAG sufficiency: "
            f"{'answerable' if suff.get('answerable') else 'needs synthesis'} "
            f"(confidence {suff.get('confidence')})"
        )
        if suff.get("recommended_next_stage"):
            lines.append(f"Next stage: {suff.get('recommended_next_stage')}")
    repo = dict(packet.get("repo_map") or {})
    if repo:
        lines.extend(
            [
                f"Repo map: {repo.get('file_count', 0)} files, {repo.get('symbol_count', 0)} symbols",
                "Top areas: "
                + ", ".join(str(item.get("path")) for item in list(repo.get("directories") or [])[:6]),
            ]
        )
    symbols = list(packet.get("symbols") or [])
    if symbols:
        lines.append("Top symbol evidence:")
        for item in symbols[:8]:
            lines.append(
                f"- {item.get('kind')} {item.get('qualname') or item.get('name')} "
                f"at {item.get('path')}:{item.get('start_line')}"
            )
    validation = list(packet.get("validation_plan") or [])
    if validation:
        lines.append("Validation candidates:")
        for item in validation[:8]:
            lines.append(f"- {item.get('command')}: {item.get('reason')}")
    context = str(packet.get("project_context") or "").strip()
    if context:
        lines.extend(["", "Indexed project evidence excerpt:", context[:max_context_chars]])
    return "\n".join(lines)


def deterministic_code_answer(packet: dict[str, Any] | None) -> str | None:
    packet = dict(packet or {})
    answer = str(packet.get("deterministic_answer") or "").strip()
    return answer if packet.get("can_answer_without_model") and answer else None


def _project_roots_from_context(context: str) -> list[str]:
    for line in (context or "").splitlines():
        if line.startswith("Project roots:"):
            raw = line.split(":", 1)[1].strip()
            if not raw or raw == "(none)":
                return []
            return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def _candidate_paths(
    symbols: tuple[dict[str, Any], ...],
    usages: dict[str, Any],
    *,
    active_path: str | None = None,
) -> list[str]:
    paths: list[str] = []
    if active_path:
        paths.append(str(active_path))
    for item in symbols:
        path = item.get("path")
        if path:
            paths.append(str(path))
    for key in ("exact_symbols", "exact_calls", "exact_chunks", "related_symbols"):
        for item in usages.get(key) or []:
            path = item.get("path")
            if path:
                paths.append(str(path))
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            normalized = str(Path(path).expanduser().resolve())
        except Exception:
            normalized = path
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out[:12]
