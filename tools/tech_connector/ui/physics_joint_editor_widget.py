"""Compatibility alias for the game-engine physics-joint editor."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.game_engine.physics_joint_editor"
)

