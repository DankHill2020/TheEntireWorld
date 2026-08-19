"""Compatibility alias for the canonical visual-art inspector."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.image_viewer.visual_art_inspector"
)

