"""Compatibility alias for the game-engine animation timeline."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.game_engine.animation_timeline"
)

