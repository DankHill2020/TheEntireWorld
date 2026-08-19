"""Compatibility alias for the game-engine simulation-runtime setup UI."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.game_engine.simulation_runtime_setup"
)

