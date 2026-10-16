"""Portable rigging contract loader for desktop and embedded DCC Pythons."""

from importlib import import_module as _import_module
from importlib.util import module_from_spec as _module_from_spec, spec_from_file_location as _spec_from_file_location
from pathlib import Path as _Path
import sys as _sys

try:
    _implementation = _import_module("tech_connector.game_engine.authoring.rigging_workspace_service")
except ModuleNotFoundError:
    # Embedded DCCs may not include optional desktop dependencies such as
    # Pillow or Qt. The rig contract is dependency-free, so load that source
    # directly instead of importing the complete game_engine package.
    _source = (
        _Path(__file__).resolve().parents[2]
        / "game_engine"
        / "authoring"
        / "rigging_workspace_service.py"
    )
    _name = "_tech_connector_portable_rigging_workspace_service"
    _spec = _spec_from_file_location(_name, _source)
    if _spec is None or _spec.loader is None:
        raise ImportError("Could not load the portable rigging workspace contract")
    _implementation = _module_from_spec(_spec)
    _sys.modules[_name] = _implementation
    _spec.loader.exec_module(_implementation)
_sys.modules[__name__] = _implementation



