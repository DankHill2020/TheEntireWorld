"""Compatibility alias for the canonical connected-DCC driver widget."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("tech_connector.ui.dcc_viewer.driver_widget")
