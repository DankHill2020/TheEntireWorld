"""Compatibility alias for the shared FX workflow service."""

from importlib import import_module as _import_module
import sys as _sys

_implementation = _import_module("tech_connector.game_engine.runtime.tc_fx_workflow_service")
_sys.modules[__name__] = _implementation
