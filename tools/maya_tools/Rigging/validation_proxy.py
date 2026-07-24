"""Disposable Maya rigged-proxy fixture for transfer validation."""

from __future__ import annotations

from typing import Any


def create_rigged_proxy(
    name_prefix: str = "AIStudio_Proxy",
    *,
    start_frame: int = 1,
    end_frame: int = 24,
    travel_distance: float = 100.0,
) -> dict[str, Any]:
    """Create, skin, animate, and select a small biped-like transfer fixture."""
    import maya.cmds as cmds

    prefix = str(name_prefix or "AIStudio_Proxy").replace(" ", "_")
    if cmds.objExists(f"{prefix}_GRP"):
        raise RuntimeError(
            f"{prefix}_GRP already exists; choose a unique name_prefix for a disposable fixture"
        )
    group = cmds.group(empty=True, name=f"{prefix}_GRP")
    cmds.select(clear=True)
    root = cmds.joint(name=f"{prefix}_root_JNT", position=(0, 0, 0))
    spine = cmds.joint(name=f"{prefix}_spine_JNT", position=(0, 5, 0))
    chest = cmds.joint(name=f"{prefix}_chest_JNT", position=(0, 10, 0))
    cmds.select(chest)
    left_arm = cmds.joint(name=f"{prefix}_L_arm_JNT", position=(4, 10, 0))
    cmds.select(chest)
    right_arm = cmds.joint(name=f"{prefix}_R_arm_JNT", position=(-4, 10, 0))
    cmds.select(root)
    left_leg = cmds.joint(name=f"{prefix}_L_leg_JNT", position=(2, -6, 0))
    cmds.select(root)
    right_leg = cmds.joint(name=f"{prefix}_R_leg_JNT", position=(-2, -6, 0))
    joints = [root, spine, chest, left_arm, right_arm, left_leg, right_leg]
    cmds.parent(root, group)

    mesh = cmds.polyCube(
        name=f"{prefix}_Body_GEO",
        width=6,
        height=12,
        depth=3,
        subdivisions_height=6,
    )[0]
    cmds.move(0, 4, 0, mesh, absolute=True)
    cmds.parent(mesh, group)
    skin = cmds.skinCluster(
        joints,
        mesh,
        toSelectedBones=True,
        bindMethod=0,
        normalizeWeights=1,
        name=f"{prefix}_SKIN",
    )[0]
    cmds.setKeyframe(root, attribute="translateX", time=int(start_frame), value=0.0)
    cmds.setKeyframe(
        root,
        attribute="translateX",
        time=int(end_frame),
        value=float(travel_distance),
    )
    cmds.playbackOptions(minTime=int(start_frame), maxTime=int(end_frame))
    cmds.select([mesh, root], replace=True)
    return {
        "maya_scene": True,
        "group": group,
        "mesh": mesh,
        "root_joint": root,
        "joints": joints,
        "skin_cluster": skin,
        "frame_range": [int(start_frame), int(end_frame)],
        "selection": [mesh, root],
    }
