"""Compatibility alias for Unreal-facing game-engine editor dialogs."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.game_engine.unreal_editor_dialogs"
)

