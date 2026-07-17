"""File-aware agent context helpers backed by the local project index."""

from __future__ import annotations

from typing import List

from tech_connector.services.file_index_service import file_index_service


class FileAwareAgent:
    """Small retrieval helper for prompt context assembly."""

    def __init__(self):
        self.index_service = file_index_service

    def get_context_for_file(self, file_path: str, max_chars: int = 20000) -> str:
        content = self.index_service.get_file_content(file_path)
        if content:
            clipped = content[:max_chars]
            suffix = "\n\n...[truncated]..." if len(content) > max_chars else ""
            return f"File: {file_path}\nSource: local_index\n\n{clipped}{suffix}"
        schema = self.index_service.describe_schema()
        return (
            f"Could not retrieve indexed content for file: {file_path}\n"
            f"Index schema/debug info: {schema}"
        )

    def search_and_get_context(self, query: str, limit: int = 5, preview_chars: int = 1200) -> str:
        results = self.index_service.search_files(query, limit)
        if not results:
            return f"No indexed files found matching query: {query}"
        parts: List[str] = []
        for result in results:
            content = result.get("content") or ""
            preview = content[:preview_chars]
            suffix = "\n...[truncated]..." if len(content) > preview_chars else ""
            parts.append(f"File: {result.get('path')}\nPreview:\n{preview}{suffix}")
        return "\n\n---\n\n".join(parts)

    def get_project_structure(self, limit: int = 100) -> str:
        files = self.index_service.list_all_indexed_files(limit)
        return f"Indexed files ({len(files)} shown):\n" + "\n".join(files)


file_aware_agent = FileAwareAgent()
