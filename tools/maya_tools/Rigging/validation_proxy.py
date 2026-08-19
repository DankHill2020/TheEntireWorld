"""Disposable Maya skeletal proxy used for transfer and parity validation."""

from __future__ import annotations

from typing import Any


def create_rigged_proxy(
    name_prefix: str = "AIStudio_Proxy",
    start_frame: int = 1,
    end_frame: int = 24,
    travel_distance: float = 100.0,
) -> dict[str, Any]:
    import maya.cmds as cmds

    prefix = str(name_prefix or "AIStudio_Proxy")
    mesh = cmds.polyCube(name=f"{prefix}_Mesh", width=10.0, height=20.0, depth=10.0)[0]
    cmds.select(clear=True)
    root = cmds.joint(name=f"{prefix}_Root", position=(0.0, -10.0, 0.0))
    tip = cmds.joint(name=f"{prefix}_Tip", position=(0.0, 10.0, 0.0))
    cmds.select(clear=True)
    skin = cmds.skinCluster(
        [root, tip], mesh, name=f"{prefix}_Skin", toSelectedBones=True,
        maximumInfluences=8, obeyMaxInfluences=True,
    )[0]
    material = cmds.shadingNode("lambert", asShader=True, name=f"{prefix}_Material")
    shading_group = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=f"{prefix}_MaterialSG",
    )
    cmds.connectAttr(material + ".outColor", shading_group + ".surfaceShader", force=True)
    cmds.setAttr(material + ".color", 0.2, 0.5, 0.8, type="double3")
    cmds.sets(mesh, edit=True, forceElement=shading_group)
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    cmds.setKeyframe(root, attribute="translateX", time=start, value=0.0)
    cmds.setKeyframe(root, attribute="translateX", time=end, value=float(travel_distance))
    cmds.setKeyframe(tip, attribute="rotateZ", time=start, value=-20.0)
    cmds.setKeyframe(tip, attribute="rotateZ", time=end, value=20.0)
    cmds.playbackOptions(minTime=start, maxTime=end, animationStartTime=start, animationEndTime=end)
    return {
        "ok": True,
        "mesh": mesh,
        "joints": [root, tip],
        "skin_cluster": skin,
        "start_frame": start,
        "end_frame": end,
        "maximum_influences": 8,
        "material": material,
        "shading_group": shading_group,
    }


def inspect_rigged_proxy(
    name_prefix: str = "AIStudio_Proxy",
    start_frame: int = 1,
    end_frame: int = 24,
) -> dict[str, Any]:
    import maya.cmds as cmds

    prefix = str(name_prefix or "AIStudio_Proxy")
    mesh = f"{prefix}_Mesh"
    root = f"{prefix}_Root"
    tip = f"{prefix}_Tip"
    required = [mesh, root, tip]
    existing = {name: bool(cmds.objExists(name)) for name in required}
    parents = cmds.listRelatives(tip, parent=True, fullPath=False) or [] if existing[tip] else []
    hierarchy_ok = all(existing.values()) and root in parents
    history = cmds.listHistory(mesh) or [] if existing[mesh] else []
    clusters = cmds.ls(history, type="skinCluster") or []
    cluster = clusters[0] if clusters else ""
    influences = cmds.skinCluster(cluster, query=True, influence=True) or [] if cluster else []
    maximum = int(cmds.getAttr(cluster + ".maxInfluences")) if cluster else 0
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True)) if existing[mesh] else 0
    normalized = bool(cluster and vertex_count > 0)
    for index in range(vertex_count):
        values = cmds.skinPercent(cluster, f"{mesh}.vtx[{index}]", query=True, value=True) or []
        if not values or abs(sum(float(value) for value in values) - 1.0) > 1e-4:
            normalized = False
            break
    skin_ok = bool(cluster and 0 < len(influences) <= 8 and maximum <= 8 and normalized)
    keys = sorted(set(float(value) for value in (cmds.keyframe([root, tip], query=True, timeChange=True) or [])))
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    animation_ok = bool(keys and keys[0] <= start and keys[-1] >= end)
    shapes = cmds.listRelatives(mesh, shapes=True, fullPath=True) or [] if existing[mesh] else []
    shading_groups = []
    for shape in shapes:
        for value in cmds.listConnections(shape, type="shadingEngine") or []:
            if value not in shading_groups:
                shading_groups.append(value)
    material_ok = any(value not in {"initialShadingGroup", "initialParticleSE"} for value in shading_groups)
    return {
        "ok": True,
        "mesh": mesh,
        "joints": [root, tip],
        "skin_cluster": cluster,
        "influences": [str(value) for value in influences],
        "maximum_influences": maximum,
        "normalized_vertex_count": vertex_count if normalized else 0,
        "key_times": keys,
        "shading_groups": shading_groups,
        "parity_checks": {
            "joint hierarchy": hierarchy_ok,
            "skin influence count and normalization": skin_ok,
            "animation frame range": animation_ok,
            "material assignments": material_ok,
        },
    }


__all__ = ["create_rigged_proxy", "inspect_rigged_proxy"]
