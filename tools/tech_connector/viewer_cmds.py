"""Compatibility alias for the public game-engine viewer command facade."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.game_engine.integration.viewer_commands"
)
