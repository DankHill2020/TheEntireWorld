from __future__ import annotations

"""Rig template loading helpers for Maya rigging workflows."""

import json
from pathlib import Path

import maya.cmds as cmds


DEFAULT_BIPED_RIG_TEMPLATE = "C:/depot/ArtSource/Rigs/rig_template.ma"


def _short_name(node: str) -> str:
    return str(node or "").split("|")[-1].split(":")[-1]


def _is_rfl_joint(node: str) -> bool:
    return _short_name(node).endswith("_RFL")


def load_biped_rig_template(
    template_path: str = DEFAULT_BIPED_RIG_TEMPLATE,
    namespace: str = "",
    reference: bool = False,
    merge_namespaces_on_clash: bool = False,
) -> dict:
    """Import or reference the biped rig template and report skeleton/RFL joints."""
    path = Path(template_path).expanduser()
    if not path.exists():
        raise RuntimeError("Rig template does not exist: {0}".format(path))

    before = set(cmds.ls(long=True) or [])
    kwargs = {
        "ignoreVersion": True,
        "returnNewNodes": True,
        "preserveReferences": True,
    }
    if namespace:
        kwargs["namespace"] = namespace
    if reference:
        new_nodes = cmds.file(str(path), reference=True, **kwargs) or []
    else:
        kwargs["mergeNamespacesOnClash"] = bool(merge_namespaces_on_clash)
        new_nodes = cmds.file(str(path), i=True, **kwargs) or []

    if not new_nodes:
        after = set(cmds.ls(long=True) or [])
        new_nodes = sorted(after - before)

    joints = [node for node in new_nodes if cmds.objExists(node) and cmds.nodeType(node) == "joint"]
    if not joints:
        joints = cmds.ls(type="joint", long=True) or []
    rfl_joints = [node for node in joints if _is_rfl_joint(node)]
    child_joints = set(cmds.listRelatives(joints, children=True, type="joint", fullPath=True) or [])
    root_joints = [node for node in joints if node not in child_joints]

    report = {
        "ok": True,
        "template_path": str(path).replace("\\", "/"),
        "reference": bool(reference),
        "namespace": namespace,
        "new_node_count": len(new_nodes),
        "joint_count": len(joints),
        "root_joints": root_joints,
        "rfl_joints": rfl_joints,
        "rfl_joint_count": len(rfl_joints),
        "sample_joints": joints[:40],
    }
    print(json.dumps(report, indent=2))
    return report


def load_default_biped_rig_template(reference: bool = False, namespace: str = "") -> dict:
    return load_biped_rig_template(
        DEFAULT_BIPED_RIG_TEMPLATE,
        namespace=namespace,
        reference=reference,
    )
