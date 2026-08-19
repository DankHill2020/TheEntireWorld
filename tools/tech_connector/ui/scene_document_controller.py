"""Compatibility alias for the canonical DCC viewer scene controller."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module(
    "tech_connector.ui.dcc_viewer.scene_document_controller"
)

