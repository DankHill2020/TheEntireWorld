"""Prepare a Maya deformation rig and export it as an Unreal skeletal FBX."""

from __future__ import annotations

import os
import re
from typing import Any

import maya.cmds as cmds
import maya.mel as mel

from maya_tools.Rigging import create_rig


def sanitize_rig_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_")
    for prefix in ("SKM_", "SK_", "PHYS_"):
        if name.upper().startswith(prefix):
            name = name[len(prefix):]
            break
    if not name:
        raise ValueError("Rig name is required.")
    if name[0].isdigit():
        name = "Rig_" + name
    return name


def _mesh_transforms(values: list[str] | tuple[str, ...] | None = None) -> list[str]:
    requested = list(values or cmds.ls(selection=True, long=True) or [])
    meshes = []
    for value in requested:
        if not cmds.objExists(value):
            continue
        node_type = cmds.nodeType(value)
        transform = value
        if node_type == "mesh":
            parents = cmds.listRelatives(value, parent=True, fullPath=True) or []
            transform = parents[0] if parents else value
        elif node_type == "transform":
            shapes = cmds.listRelatives(value, shapes=True, noIntermediate=True, fullPath=True) or []
            if not any(cmds.nodeType(shape) == "mesh" for shape in shapes):
                continue
        else:
            continue
        if transform not in meshes:
            meshes.append(transform)
    if not meshes:
        raise ValueError("Select at least one skinned mesh before exporting to Unreal.")
    return meshes


def list_skinned_meshes() -> list[str]:
    """Return exportable, non-intermediate skinned mesh transforms in the scene."""
    meshes = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        transform = parents[0]
        if transform in meshes:
            continue
        history = cmds.listHistory(transform, pruneDagObjects=True) or []
        if any(cmds.nodeType(node) == "skinCluster" for node in history):
            meshes.append(transform)
    return meshes


def _skin_clusters(meshes: list[str]) -> list[str]:
    clusters = []
    for mesh in meshes:
        for node in cmds.listHistory(mesh, pruneDagObjects=True) or []:
            if cmds.nodeType(node) == "skinCluster" and node not in clusters:
                clusters.append(node)
    if not clusters:
        raise ValueError("The selected mesh has no skinCluster and cannot be exported as a Skeletal Mesh.")
    return clusters


def _influences(clusters: list[str]) -> list[str]:
    joints = []
    for cluster in clusters:
        for joint in cmds.skinCluster(cluster, query=True, influence=True) or []:
            matches = cmds.ls(joint, long=True) or []
            resolved = matches[0] if len(matches) == 1 else joint
            if resolved not in joints:
                joints.append(resolved)
    return joints


def _root_joints(joints: list[str]) -> list[str]:
    joint_set = set(joints)
    roots = []
    for joint in joints:
        cursor = joint
        while True:
            parent = cmds.listRelatives(cursor, parent=True, type="joint", fullPath=True) or []
            if not parent or parent[0] not in joint_set:
                break
            cursor = parent[0]
        if cursor not in roots:
            roots.append(cursor)
    return roots


def restore_skin_bind_pose(meshes: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    mesh_nodes = _mesh_transforms(meshes)
    clusters = _skin_clusters(mesh_nodes)
    joints = _influences(clusters)
    bind_poses = []
    for cluster in clusters:
        bind_poses.extend(cmds.listConnections(cluster + ".bindPose", source=True, destination=False, type="dagPose") or [])
    bind_poses = list(dict.fromkeys(bind_poses))
    restored = []
    for pose in bind_poses:
        try:
            cmds.dagPose(pose, restore=True, **{"global": True})
            restored.append(pose)
        except (RuntimeError, TypeError):
            cmds.dagPose(pose, restore=True)
            restored.append(pose)
    if not restored:
        raise RuntimeError(
            "No connected bindPose node was found for the selected skinCluster. "
            "The export was stopped instead of guessing a pose."
        )
    return {"meshes": mesh_nodes, "skin_clusters": clusters, "joints": joints, "bind_poses": restored}


def export_skeletal_fbx(
    rig_name: str,
    output_directory: str,
    *,
    meshes: list[str] | tuple[str, ...] | None = None,
    skeletal_mesh_name: str = "",
) -> dict[str, Any]:
    name = sanitize_rig_name(rig_name)
    mesh_asset_name = re.sub(r"[^A-Za-z0-9_]+", "_", str(skeletal_mesh_name or "").strip()).strip("_")
    if not mesh_asset_name:
        mesh_asset_name = f"SKM_{name}"
    pose = restore_skin_bind_pose(meshes)
    roots = _root_joints(pose["joints"])
    requested_directory = os.path.expandvars(str(output_directory or "").strip())
    if not requested_directory:
        raise ValueError("An FBX output directory is required.")
    output_directory = os.path.abspath(requested_directory)
    os.makedirs(output_directory, exist_ok=True)
    fbx_path = os.path.join(output_directory, f"{mesh_asset_name}.fbx").replace("\\", "/")

    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        cmds.select(clear=True)
        cmds.select(pose["meshes"] + roots, replace=True, noExpand=True)
        mel.eval("FBXResetExport;")
        mel.eval("FBXExportSmoothingGroups -v true;")
        mel.eval("FBXExportSkins -v true;")
        mel.eval("FBXExportShapes -v true;")
        mel.eval("FBXExportConstraints -v false;")
        mel.eval("FBXExportInputConnections -v false;")
        mel.eval("FBXExportAnimationOnly -v false;")
        mel.eval('FBXExportUpAxis "y";')
        mel.eval('FBXExport -f "{}" -s;'.format(fbx_path.replace('"', '\\"')))
    finally:
        cmds.select(clear=True)
        if previous_selection:
            cmds.select(previous_selection, replace=True, noExpand=True)
    if not os.path.isfile(fbx_path):
        raise RuntimeError(f"Maya reported FBX export success but no file exists: {fbx_path}")
    return {
        **pose,
        "rig_name": name,
        "fbx_path": fbx_path,
        "skeletal_mesh_name": mesh_asset_name,
        "skeleton_name": f"SK_{name}",
        "physics_asset_name": f"PHYS_{name}",
        "root_joints": roots,
    }


def remove_rig_restore_bind_pose_and_export(
    body_joint_map: dict[str, Any],
    face_joint_map: dict[str, Any] | None,
    rig_name: str,
    output_directory: str,
    *,
    meshes: list[str] | tuple[str, ...] | None = None,
    skeletal_mesh_name: str = "",
) -> dict[str, Any]:
    """Remove generated controls, restore skin bind pose, and export Unreal FBX."""
    create_rig.store_all_control_cv_positions()
    create_rig.remove_full_rig(body_joint_map, face_joint_map or {})
    result = export_skeletal_fbx(
        rig_name,
        output_directory,
        meshes=meshes,
        skeletal_mesh_name=skeletal_mesh_name,
    )
    result["rig_removed"] = True
    return result


__all__ = [
    "export_skeletal_fbx",
    "list_skinned_meshes",
    "remove_rig_restore_bind_pose_and_export",
    "restore_skin_bind_pose",
    "sanitize_rig_name",
]
