"""Knowledge index database reference."""

from bridges.knowledge_bridge import KnowledgeBridge, IndexWorker
from models.constants import V2_DB

__all__ = ["KnowledgeBridge", "IndexWorker", "V2_DB", "symbol_db_exists"]


def symbol_db_exists() -> bool:
    return KnowledgeBridge.db_exists()
