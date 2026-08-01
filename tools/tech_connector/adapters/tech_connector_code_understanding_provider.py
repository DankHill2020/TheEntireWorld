"""Code understanding provider that delegates to current Tech Connector services."""

from __future__ import annotations

from reasoning_runtime import CodeContext, CodeUnderstandingProvider, CodeUnderstandingRequest


class TechConnectorCodeUnderstandingProvider(CodeUnderstandingProvider):
    """Expose current repo/file/symbol intelligence through a runtime contract."""

    name = "tech_connector_code_understanding"

    def understand(self, request: CodeUnderstandingRequest) -> CodeContext:
        roots = [str(root) for root in request.project_roots if root]
        active_path = request.active_file or (roots[0] if roots else "")
        if not active_path:
            return CodeContext(gaps=("No project roots were supplied.",))
        try:
            from tech_connector.services.project_search_service import gather_project_search_context

            context_text = gather_project_search_context(
                request.query,
                active_path=active_path,
            )
        except Exception as exc:
            return CodeContext(gaps=(str(exc),))
        return CodeContext(
            summary=str(context_text or ""),
            metadata={"source": "tech_connector.services.project_search_service"},
        )
