"""Evidence-gap retrieval for Unreal feature planning and bounded repair."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from tech_connector.services.unreal.evidence_driven_feature_synthesis_service import (
    build_feature_research_plan,
)
from tech_connector.services.unreal.semantic_project_index_service import (
    infer_required_index_domains,
    query_semantic_project_index,
)


class AutonomousKnowledgeRetrievalEngine:
    """Retrieve evidence without fabricating a mechanic-specific solution."""

    def __init__(self, index_db_path: str | None = None, project_root: str | None = None):
        default_index = Path(__file__).resolve().parents[1] / "knowledge" / "index" / "knowledge_index_v2.sqlite"
        self.index_db_path = Path(index_db_path) if index_db_path else default_index
        self.project_root = project_root

    @staticmethod
    def _terms(text: str, limit: int = 12) -> list[str]:
        stop = {"build", "create", "system", "feature", "failed", "failure", "unreal", "engine"}
        values = []
        for value in re.findall(r"[A-Za-z_][A-Za-z0-9_.:]{2,}", text or ""):
            normalized = value.lower()
            if normalized not in stop and normalized not in values:
                values.append(normalized)
        return values[:limit]

    def search_knowledge_index(self, query_terms: Iterable[str], limit: int = 30) -> list[dict[str, Any]]:
        if not self.index_db_path.exists():
            return []
        results: list[dict[str, Any]] = []
        try:
            with closing(sqlite3.connect(str(self.index_db_path), timeout=3.0)) as connection:
                for term in list(query_terms)[:12]:
                    safe_term = re.sub(r"[^A-Za-z0-9_]", " ", str(term)).strip()
                    if not safe_term:
                        continue
                    rows = connection.execute(
                        "SELECT path, rel_path, text FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 8",
                        ('"' + safe_term.replace('"', '') + '"',),
                    ).fetchall()
                    for path, relative_path, text in rows:
                        results.append(
                            {
                                "file_path": path,
                                "relative_path": relative_path,
                                "snippet": str(text or "")[:500],
                                "matched_term": term,
                                "source_kind": "local_index",
                            }
                        )
                        if len(results) >= limit:
                            break
                    if len(results) >= limit:
                        break
        except (sqlite3.Error, OSError):
            return []
        return results

    def build_acquisition_plan(
        self,
        request: str,
        *,
        gaps: Iterable[dict[str, Any]] | None = None,
        failed_assertions: Iterable[dict[str, Any]] | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        gaps = [dict(row) for row in gaps or []]
        failed_assertions = [dict(row) for row in failed_assertions or []]
        terms = self._terms(" ".join([request, *[str(row) for row in gaps], *[str(row) for row in failed_assertions]]))
        project_context = query_semantic_project_index(
            " ".join(terms), project_root=self.project_root, limit=30
        )
        local_records = self.search_knowledge_index(terms)
        research = build_feature_research_plan(request, project_evidence=project_context)
        capability_gap = any(
            any(token in str(row).lower() for token in ("not exposed", "python unavailable", "reflection missing"))
            for row in [*gaps, *failed_assertions]
        )
        return {
            "framework": "unreal_evidence_gap_acquisition_v1",
            "request": request,
            "attempt": attempt,
            "max_attempts": 3,
            "continue_allowed": attempt <= 3,
            "required_domains": infer_required_index_domains(request),
            "gaps": gaps,
            "failed_assertions": failed_assertions,
            "project_context": project_context,
            "local_records": local_records,
            "research_queries": research.get("research_queries") or [],
            "source_acceptance": research.get("source_acceptance") or {},
            "cpp_wrapper": {
                "recommended": capability_gap,
                "reason": (
                    "A live reflection/capability failure indicates the required fact or action is unavailable to Python."
                    if capability_gap
                    else "No evidence currently justifies adding C++ surface area."
                ),
                "required_proof": [
                    "live reflection lookup failed",
                    "no registered first-party operation satisfies the contract",
                    "wrapper self-test returns structured live evidence",
                ],
            },
            "decision": {
                "recommended": "add_knowledge_first",
                "alternatives": ["add_knowledge_first", "run_with_current_knowledge"],
                "mutation_allowed": False,
                "reason": "Resolve evidence gaps and revalidate the feature contract before project mutation.",
            },
        }

    def escalate_and_retrieve_expert_solution(self, failed_feature: str, failure_reason: str) -> dict[str, Any]:
        """Compatibility entrypoint; returns evidence work, never an invented fix."""
        return self.build_acquisition_plan(
            failed_feature,
            failed_assertions=[{"assertion": failed_feature, "failure": failure_reason}],
        )
