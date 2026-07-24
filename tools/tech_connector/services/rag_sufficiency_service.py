"""Compatibility shim for the canonical reasoning service module.

The implementation lives in ``tech_connector.services.reasoning.rag_sufficiency_service``.
Keep this root import path for older callers while avoiding duplicate logic.
"""

from tech_connector.services.reasoning.rag_sufficiency_service import *  # noqa: F401,F403
