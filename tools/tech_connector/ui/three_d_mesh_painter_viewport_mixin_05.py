"""Compatibility alias for mesh-painter viewport mixin 05."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_05"
)

