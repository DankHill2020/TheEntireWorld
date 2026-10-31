"""Cleanup helpers for construction-only Maya joints."""

from __future__ import annotations

from functools import wraps
import re

import maya.cmds as cmds


_TEMP_BONE_TOKEN = re.compile(r"(?:^|_)temp(?:_|$)", re.IGNORECASE)


def _is_temp_bone(node):
    short_name = node.rsplit("|", 1)[-1].split(":")[-1]
    return bool(_TEMP_BONE_TOKEN.search(short_name))


def delete_temp_bones(exclude=()):
    """Delete newly created construction joints with a distinct ``temp`` token.

    Non-temporary children are first reparented beside the temporary joint so
    cleanup cannot accidentally remove a persistent skeleton branch. Referenced
    and explicitly excluded joints are left untouched because they predate the
    current operation and may be valid rig data despite their name.
    """
    excluded = set(exclude or ())
    candidates = [
        node for node in (cmds.ls(type="joint", long=True) or [])
        if _is_temp_bone(node) and node not in excluded
    ]
    candidate_set = set(candidates)
    roots = []
    for node in candidates:
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        if not any(parent in candidate_set for parent in parents):
            roots.append(node)

    deleted = []
    skipped = []
    for node in sorted(roots, key=lambda value: value.count("|"), reverse=True):
        if not cmds.objExists(node):
            continue
        try:
            if cmds.referenceQuery(node, isNodeReferenced=True):
                skipped.append(node)
                continue
        except Exception:
            pass

        parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [None])[0]
        children = cmds.listRelatives(node, children=True, type="transform", fullPath=True) or []
        for child in children:
            if _is_temp_bone(child):
                continue
            if parent and cmds.objExists(parent):
                cmds.parent(child, parent, absolute=True)
            else:
                cmds.parent(child, world=True, absolute=True)
        try:
            cmds.delete(node)
            deleted.append(node)
        except Exception as exc:
            skipped.append("{} ({})".format(node, exc))

    if deleted:
        print("[cleanup] Deleted temporary bones: {}".format(deleted))
    if skipped:
        cmds.warning("Could not delete temporary bones: {}".format(skipped))
    return deleted


def cleanup_temp_bones(function):
    """Clean up only temporary joints created by this operation.

    Existing scene joints are treated as user data, even when their names
    contain ``temp``. Sweeping the entire scene before a fit could otherwise
    delete authored helpers such as hair, eyelid, or twist joints.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        existing = set(cmds.ls(type="joint", long=True) or [])
        try:
            return function(*args, **kwargs)
        finally:
            delete_temp_bones(exclude=existing)

    return wrapped
