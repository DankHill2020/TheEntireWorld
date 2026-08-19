"""Compatibility alias for tech_connector.game_engine.integration.transferability_matrix_service."""

from importlib import import_module as _import_module
import sys as _sys

_implementation = _import_module("tech_connector.game_engine.integration.transferability_matrix_service")
_sys.modules[__name__] = _implementation



