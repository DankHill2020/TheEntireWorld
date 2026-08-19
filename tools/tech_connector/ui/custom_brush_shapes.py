"""Compatibility alias for image-viewer brush shapes."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("tech_connector.ui.image_viewer.brush_shapes")

