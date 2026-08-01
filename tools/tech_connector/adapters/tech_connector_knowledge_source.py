"""Tech Connector knowledge source adapter."""

from __future__ import annotations

from reasoning_runtime import KnowledgeGap, KnowledgeSearchResult, KnowledgeSource


class TechConnectorProjectKnowledgeSource(KnowledgeSource):
    """Search project/index knowledge through current Tech Connector services."""

    name = "tech_connector_project_knowledge"

    def __init__(self, project_roots: list[str] | None = None) -> None:
        self.project_roots = list(project_roots or [])

    def search(self, gap: KnowledgeGap, context: dict) -> list[KnowledgeSearchResult]:
        roots = self.project_roots or list(
            ((context.get("tech_connector_context") or {}).get("project_roots") or [])
        )
        if not roots:
            return []
        try:
            from tech_connector.services.project_search_service import gather_project_search_context

            answer = gather_project_search_context(
                gap.question,
                active_path=str(roots[0]),
            )
        except Exception:
            return []
        answer = str(answer or "")
        if not answer:
            return []
        return [
            KnowledgeSearchResult(
                source=self.name,
                answer=answer,
                confidence=0.7,
                metadata={"gap": gap.key},
            )
        ]
