"""Compatibility alias for tech_connector.game_engine.integration.tc_hik_ui_host."""

from importlib import import_module as _import_module
import sys as _sys

_implementation = _import_module("tech_connector.game_engine.integration.tc_hik_ui_host")
_sys.modules[__name__] = _implementation



