"""Compatibility exports for Ollama model helpers.

The implementation lives in services.ollama_service. This module remains so
older imports from models.symbols keep working without duplicating logic.
"""

from services.ollama_service import (
    AI_MODELS,
    ModelInstallWorker,
    as_mcphost_model,
    installed_ollama_models,
    missing_required_models,
    normalize_ollama_model_name,
    warm_ollama_model,
    warm_required_models_async,
)

__all__ = [
    "AI_MODELS",
    "ModelInstallWorker",
    "as_mcphost_model",
    "installed_ollama_models",
    "missing_required_models",
    "normalize_ollama_model_name",
    "warm_ollama_model",
    "warm_required_models_async",
]
