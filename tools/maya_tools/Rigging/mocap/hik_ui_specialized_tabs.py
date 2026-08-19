"""Specialized FACS, corrective, ribbon, and QA tabs for the HIK UI."""

from __future__ import annotations

import json

try:
    import maya.cmds as cmds
    from maya_tools.Rigging import create_rig
except ImportError:
    from tech_connector.services.dcc.tc_hik_ui_host import cmds, create_rig

try:
    if hasattr(cmds, "about") and int(cmds.about(version=True)) < 2025:
        from PySide2 import QtCore, QtWidgets
    else:
        from PySide6 import QtCore, QtWidgets
except (ImportError, RuntimeError):
    from PySide6 import QtCore, QtWidgets

try:
    from tech_connector.game_engine.authoring import facs_facial_rig_service
    from tech_connector.game_engine.authoring import pose_space_deformer_service
    from tech_connector.game_engine.authoring import ribbon_rig_service
except ImportError:
    facs_facial_rig_service = None
    pose_space_deformer_service = None
    ribbon_rig_service = None


class HIKSpecializedTabsMixin:
    """Provide specialized authoring and QA tabs for ``HIKDefinitionUI``."""
