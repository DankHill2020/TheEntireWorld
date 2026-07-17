"""Knowledge index database reference."""

from tech_connector.bridges.knowledge_bridge import KnowledgeBridge, IndexWorker
from tech_connector.models.constants import project_index_db_path

__all__ = ["KnowledgeBridge", "IndexWorker", "project_index_db_path", "symbol_db_exists"]


def symbol_db_exists() -> bool:
    return KnowledgeBridge.db_exists()
