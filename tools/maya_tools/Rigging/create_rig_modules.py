"""Modular rig builders and persistence helpers for :mod:`create_rig`."""

from __future__ import annotations

import json
import math
import os
import re

import maya.api.OpenMaya as om
import maya.cmds as cmds

from custom_qt import custom_widgets
from maya_tools.Rigging import enum_attrs
from maya_tools.Rigging.mocap import setup_hik


def bind_runtime(namespace):
    """
    Binds facade helpers used by the modular rig implementations.

    :param namespace: globals from the public ``create_rig`` facade.
    :return: None.
    """
    globals().update(namespace)


_EXPORT_START = set(globals())

__all__ = sorted(
    name
    for name in globals()
    if name not in _EXPORT_START and name != "_EXPORT_START"
)
