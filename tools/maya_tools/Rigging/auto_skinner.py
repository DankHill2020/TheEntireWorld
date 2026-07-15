"""
auto_skinner.py

First-pass automatic skin weighting for Maya.

Design goal:
    mesh + skeleton -> skinCluster -> distance-to-bone initial weights -> optional smooth

This is a practical starting point, not a final deformation solver. It gives a
repeatable base bind that can be improved later with region masks, pose tests,
and joint-specific polish rules.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import maya.cmds as cmds
import maya.api.OpenMaya as om


DEFAULT_MAX_INFLUENCES = 4
DEFAULT_BIND_METHOD = 0
GEODESIC_VOXEL_BIND_METHOD = 3


BindSegment = Tuple[str, str, om.MVector, om.MVector]
WeightList = List[Tuple[str, float]]


IGNORE_WEIGHT_JOINT_TERMS = (
    "_tip",
    "end",
    "ikh",
    "ik_",
    "fk_",
    "driver",
    "ctrl",
    "fol",
)


def _as_mesh_transform(node: str) -> str:
    if not node or not cmds.objExists(node):
        cmds.error("Mesh does not exist: {0}".format(node))

    if cmds.nodeType(node) == "mesh":
        parent = cmds.listRelatives(node, parent=True, fullPath=False) or []
        if not parent:
            cmds.error("Mesh shape has no transform parent: {0}".format(node))
        return parent[0]

    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=False) or []
    mesh_shapes = [s for s in shapes if cmds.nodeType(s) == "mesh"]
    if not mesh_shapes:
        cmds.error("Selected object is not a mesh transform: {0}".format(node))
    return node


def find_skin_cluster(mesh: str) -> Optional[str]:
    mesh = _as_mesh_transform(mesh)
    history = cmds.listHistory(mesh) or []
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def get_joint_position(joint: str) -> om.MVector:
    return om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))


def _short_name(node: str) -> str:
    return node.split("|")[-1].split(":")[-1]


def _find_joint_by_terms(joints: Sequence[str], terms: Sequence[str]) -> Optional[str]:
    for joint in joints:
        name = _short_name(joint).lower()
        if all(term in name for term in terms):
            return joint
    return None


def _find_first_existing_joint(joints: Sequence[str], term_sets: Sequence[Sequence[str]]) -> Optional[str]:
    for terms in term_sets:
        joint = _find_joint_by_terms(joints, terms)
        if joint:
            return joint
    return None


def get_skin_joints(root_joint: str, include_ignored: bool = False) -> List[str]:
    if not root_joint or not cmds.objExists(root_joint):
        cmds.error("Root joint does not exist: {0}".format(root_joint))

    descendants = cmds.listRelatives(root_joint, allDescendents=True, type="joint", fullPath=False) or []
    descendants.reverse()
    joints = [root_joint] + descendants

    if include_ignored:
        return joints

    filtered = []
    for joint in joints:
        low = joint.lower()
        if any(term in low for term in IGNORE_WEIGHT_JOINT_TERMS):
            continue
        filtered.append(joint)

    return filtered


def build_bone_segments(joints: Sequence[str]) -> List[Tuple[str, str]]:
    joint_set = set(joints)
    segments = []

    for parent in joints:
        children = cmds.listRelatives(parent, children=True, type="joint", fullPath=False) or []
        for child in children:
            if child in joint_set:
                segments.append((parent, child))

    return segments


def build_cached_bone_segments(joints: Sequence[str]) -> List[BindSegment]:
    position_cache = {joint: get_joint_position(joint) for joint in joints}
    return [
        (parent, child, position_cache[parent], position_cache[child])
        for parent, child in build_bone_segments(joints)
    ]


def closest_point_on_segment(point: om.MVector, a: om.MVector, b: om.MVector) -> Tuple[om.MVector, float]:
    ab = b - a
    length_sq = ab * ab

    if length_sq <= 0.000001:
        return a, 0.0

    t = ((point - a) * ab) / length_sq
    t = max(0.0, min(1.0, t))
    return a + (ab * t), t


def get_mesh_vertices(mesh: str) -> List[str]:
    mesh = _as_mesh_transform(mesh)
    return cmds.ls("{0}.vtx[*]".format(mesh), flatten=True) or []


def normalize_and_limit_weights(weights: WeightList, max_influences: int = DEFAULT_MAX_INFLUENCES) -> WeightList:
    merged: Dict[str, float] = {}
    for joint, value in weights:
        if not joint or value <= 0.0:
            continue
        merged[joint] = merged.get(joint, 0.0) + float(value)

    top = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:max_influences]
    total = sum(value for _, value in top) or 1.0
    return [(joint, value / total) for joint, value in top]


def build_default_shoulder_profile(joints: Sequence[str]) -> dict:
    profile = {"sides": {}}
    spine = _find_first_existing_joint(
        joints,
        [
            ("spine_04",),
            ("spine4",),
            ("spine_03",),
            ("spine3",),
            ("spine",),
        ],
    )

    for side in ("l", "r"):
        clavicle = _find_first_existing_joint(joints, [(side, "clavicle"), (side, "shoulder")])
        upperarm = _find_first_existing_joint(joints, [(side, "upperarm"), (side, "upper", "arm")])
        lowerarm = _find_first_existing_joint(joints, [(side, "lowerarm"), (side, "forearm"), (side, "lower", "arm")])
        if not upperarm:
            continue

        weights = []
        weights.append((upperarm, 0.65))
        if clavicle:
            weights.append((clavicle, 0.25))
        if spine:
            weights.append((spine, 0.10))

        radius = 1.0
        if lowerarm and cmds.objExists(lowerarm):
            radius = max((get_joint_position(lowerarm) - get_joint_position(upperarm)).length() * 0.45, 0.001)

        profile["sides"][side] = {
            "center_joint": upperarm,
            "radius": radius,
            "weights": dict(normalize_and_limit_weights(weights)),
        }

    return profile


def save_shoulder_profile(profile: dict, path: str) -> str:
    folder = os.path.dirname(os.path.normpath(path))
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    with open(path, "w") as handle:
        json.dump(profile, handle, indent=2, sort_keys=True)
    return path


def load_shoulder_profile(path: str) -> dict:
    with open(path, "r") as handle:
        return json.load(handle)


def _vertex_weight_for_joint(skin: str, vertex: str, joint: str) -> float:
    try:
        value = cmds.skinPercent(skin, vertex, query=True, transform=joint)
        if isinstance(value, (list, tuple)):
            return float(value[0]) if value else 0.0
        return float(value or 0.0)
    except Exception:
        return 0.0


def learn_shoulder_profile_from_skin(
    mesh: str,
    root_joint: str = "origin",
    radius_scale: float = 0.45,
    min_vertices: int = 6,
) -> dict:
    mesh = _as_mesh_transform(mesh)
    skin = find_skin_cluster(mesh)
    if not skin:
        cmds.error("No skinCluster found on {0}".format(mesh))

    joints = get_skin_joints(root_joint)
    vertices = get_mesh_vertices(mesh)
    profile = build_default_shoulder_profile(joints)
    learned = {"sides": {}}

    for side, side_profile in profile.get("sides", {}).items():
        center_joint = side_profile.get("center_joint")
        if not center_joint or not cmds.objExists(center_joint):
            continue
        center = get_joint_position(center_joint)
        radius = max(float(side_profile.get("radius", 1.0)) * float(radius_scale), 0.001)
        influence_names = list(side_profile.get("weights", {}).keys())
        sums = {joint: 0.0 for joint in influence_names}
        count = 0

        for vertex in vertices:
            pos = om.MVector(*cmds.pointPosition(vertex, world=True))
            if (pos - center).length() > radius:
                continue
            count += 1
            for joint in influence_names:
                sums[joint] += _vertex_weight_for_joint(skin, vertex, joint)

        if count < min_vertices:
            learned["sides"][side] = side_profile
            continue

        averaged = [(joint, value / float(count)) for joint, value in sums.items()]
        learned["sides"][side] = {
            "center_joint": center_joint,
            "radius": radius,
            "weights": dict(normalize_and_limit_weights(averaged)),
            "sample_count": count,
        }

    return learned


def learn_shoulder_profile_from_selected(
    root_joint: str = "origin",
    output_path: Optional[str] = None,
    radius_scale: float = 0.45,
) -> dict:
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select a corrected skinned mesh first.")

    profile = learn_shoulder_profile_from_skin(
        _as_mesh_transform(selection[0]),
        root_joint=root_joint,
        radius_scale=radius_scale,
    )
    if output_path:
        save_shoulder_profile(profile, output_path)
    return profile


def apply_shoulder_profile_to_weights(
    pos: om.MVector,
    weights: WeightList,
    shoulder_profile: Optional[dict],
    blend_strength: float,
    max_influences: int,
) -> WeightList:
    if not shoulder_profile or blend_strength <= 0.0:
        return weights

    current = dict(weights)
    blended = dict(current)

    for side_profile in (shoulder_profile.get("sides") or {}).values():
        center_joint = side_profile.get("center_joint")
        if not center_joint or not cmds.objExists(center_joint):
            continue
        radius = max(float(side_profile.get("radius", 0.0)), 0.001)
        distance = (pos - get_joint_position(center_joint)).length()
        if distance > radius:
            continue

        falloff = 1.0 - (distance / radius)
        influence = max(0.0, min(1.0, blend_strength * falloff * falloff))
        target_weights = side_profile.get("weights") or {}
        for joint, target in target_weights.items():
            if not cmds.objExists(joint):
                continue
            blended[joint] = (blended.get(joint, 0.0) * (1.0 - influence)) + (float(target) * influence)

    return normalize_and_limit_weights(list(blended.items()), max_influences=max_influences)


def apply_shoulder_profile_to_skin(
    mesh: str,
    skin: str,
    shoulder_profile: Optional[dict],
    blend_strength: float = 0.35,
    max_influences: int = DEFAULT_MAX_INFLUENCES,
) -> None:
    if not shoulder_profile or blend_strength <= 0.0:
        return

    influence_joints = cmds.skinCluster(skin, query=True, influence=True) or []
    vertices = get_mesh_vertices(mesh)
    zero_weights = [(joint, 0.0) for joint in influence_joints]

    for vertex in vertices:
        pos = om.MVector(*cmds.pointPosition(vertex, world=True))
        current = [(joint, _vertex_weight_for_joint(skin, vertex, joint)) for joint in influence_joints]
        weights = apply_shoulder_profile_to_weights(
            pos,
            normalize_and_limit_weights(current, max_influences=max_influences),
            shoulder_profile,
            blend_strength,
            max_influences,
        )
        if not weights:
            continue
        cmds.skinPercent(skin, vertex, transformValue=zero_weights, normalize=False)
        cmds.skinPercent(skin, vertex, transformValue=weights, normalize=True)


def resolve_shoulder_profile(
    shoulder_profile: Optional[object],
    joints: Sequence[str],
) -> Optional[dict]:
    if shoulder_profile is None:
        return None
    if isinstance(shoulder_profile, str):
        if shoulder_profile.lower() == "default":
            return build_default_shoulder_profile(joints)
        return load_shoulder_profile(shoulder_profile)
    if isinstance(shoulder_profile, dict):
        return shoulder_profile
    cmds.warning("Unsupported shoulder profile type: {0}".format(type(shoulder_profile)))
    return None


def bind_mesh(
    mesh: str,
    joints: Sequence[str],
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    replace_existing: bool = False,
    bind_method: int = DEFAULT_BIND_METHOD,
) -> str:
    mesh = _as_mesh_transform(mesh)
    existing = find_skin_cluster(mesh)

    if existing and not replace_existing:
        return existing

    if existing and replace_existing:
        cmds.delete(existing)

    if not joints:
        cmds.error("No skin joints were provided.")

    skin = cmds.skinCluster(
        list(joints),
        mesh,
        toSelectedBones=True,
        bindMethod=bind_method,
        skinMethod=0,
        normalizeWeights=1,
        maximumInfluences=max_influences,
        obeyMaxInfluences=True,
        name="{0}_skinCluster".format(mesh.split("|")[-1]),
    )[0]

    return skin


def run_geodesic_voxel_bind(
    skin_cluster: str,
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    falloff: float = 0.0,
    voxel_resolution: int = 256,
    validate_voxels: bool = True,
) -> bool:
    if not skin_cluster or not cmds.objExists(skin_cluster):
        return False

    try:
        cmds.geomBind(
            skin_cluster,
            bindMethod=GEODESIC_VOXEL_BIND_METHOD,
            falloff=falloff,
            maxInfluences=max_influences,
            geodesicVoxelParams=[voxel_resolution, validate_voxels],
        )
        return True
    except Exception as exc:
        cmds.warning("Geodesic voxel bind failed for {0}: {1}".format(skin_cluster, exc))
        return False


def solve_vertex_weights(
    vertex: str,
    segments: Sequence[Tuple[str, str]],
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    falloff_power: float = 2.0,
) -> List[Tuple[str, float]]:
    cached_segments = [
        (parent, child, get_joint_position(parent), get_joint_position(child))
        for parent, child in segments
    ]
    return solve_vertex_weights_from_position(
        om.MVector(*cmds.pointPosition(vertex, world=True)),
        cached_segments,
        max_influences=max_influences,
        falloff_power=falloff_power,
    )


def solve_vertex_weights_from_position(
    pos: om.MVector,
    segments: Sequence[BindSegment],
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    falloff_power: float = 2.0,
) -> List[Tuple[str, float]]:
    weighted: Dict[str, float] = {}

    for parent, child, a, b in segments:
        closest, t = closest_point_on_segment(pos, a, b)
        distance = max((pos - closest).length(), 0.0001)

        score = 1.0 / (distance ** falloff_power)
        weighted[parent] = weighted.get(parent, 0.0) + score * (1.0 - t)
        weighted[child] = weighted.get(child, 0.0) + score * t

    if not weighted:
        return []

    top = sorted(weighted.items(), key=lambda item: item[1], reverse=True)[:max_influences]
    total = sum(value for _, value in top) or 1.0
    return [(joint, value / total) for joint, value in top]


def apply_auto_weights(
    mesh: str,
    root_joint: str,
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    replace_existing_skin: bool = False,
    falloff_power: float = 2.0,
    bind_method: int = DEFAULT_BIND_METHOD,
    custom_distance_weights: bool = True,
    geodesic_voxel_falloff: float = 0.0,
    geodesic_voxel_resolution: int = 256,
    shoulder_profile: Optional[object] = None,
    shoulder_blend_strength: float = 0.0,
) -> str:
    mesh = _as_mesh_transform(mesh)
    joints = get_skin_joints(root_joint)
    segments = build_cached_bone_segments(joints)
    resolved_shoulder_profile = resolve_shoulder_profile(shoulder_profile, joints)

    if custom_distance_weights and not segments:
        cmds.error("No valid bone segments found under: {0}".format(root_joint))

    skin = bind_mesh(
        mesh,
        joints,
        max_influences=max_influences,
        replace_existing=replace_existing_skin,
        bind_method=bind_method,
    )

    if not custom_distance_weights:
        if bind_method == GEODESIC_VOXEL_BIND_METHOD:
            run_geodesic_voxel_bind(
                skin,
                max_influences=max_influences,
                falloff=geodesic_voxel_falloff,
                voxel_resolution=geodesic_voxel_resolution,
            )
        apply_shoulder_profile_to_skin(
            mesh,
            skin,
            resolved_shoulder_profile,
            blend_strength=shoulder_blend_strength,
            max_influences=max_influences,
        )
        cmds.skinCluster(skin, edit=True, forceNormalizeWeights=True)
        return skin

    vertices = get_mesh_vertices(mesh)

    cmds.progressWindow(
        title="Auto Skinning",
        progress=0,
        maxValue=max(len(vertices), 1),
        status="Solving skin weights...",
        isInterruptable=True,
    )

    try:
        zero_weights = [(joint, 0.0) for joint in joints]

        for index, vertex in enumerate(vertices):
            if cmds.progressWindow(query=True, isCancelled=True):
                break

            pos = om.MVector(*cmds.pointPosition(vertex, world=True))
            weights = solve_vertex_weights_from_position(
                pos,
                segments,
                max_influences=max_influences,
                falloff_power=falloff_power,
            )
            weights = apply_shoulder_profile_to_weights(
                pos,
                weights,
                resolved_shoulder_profile,
                shoulder_blend_strength,
                max_influences,
            )

            if not weights:
                continue

            cmds.skinPercent(skin, vertex, transformValue=zero_weights, normalize=False)
            cmds.skinPercent(skin, vertex, transformValue=weights, normalize=True)

            if index % 25 == 0:
                cmds.progressWindow(edit=True, progress=index)

    finally:
        cmds.progressWindow(endProgress=True)

    cmds.skinCluster(skin, edit=True, forceNormalizeWeights=True)
    return skin


def smooth_skin_weights(mesh: str, iterations: int = 2) -> Optional[str]:
    mesh = _as_mesh_transform(mesh)
    skin = find_skin_cluster(mesh)
    if not skin:
        cmds.warning("No skinCluster found on {0}".format(mesh))
        return None

    cmds.select(mesh, replace=True)
    for _ in range(max(0, int(iterations))):
        try:
            cmds.SmoothSkinWeights()
        except Exception:
            # Available as a runtime command in many Maya installs, but not all.
            break

    return skin


def auto_skin_mesh(
    mesh: str,
    root_joint: str = "origin",
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    smooth_iterations: int = 2,
    replace_existing_skin: bool = False,
    falloff_power: float = 2.0,
    bind_method: int = DEFAULT_BIND_METHOD,
    custom_distance_weights: bool = True,
    geodesic_voxel_falloff: float = 0.0,
    geodesic_voxel_resolution: int = 256,
    shoulder_profile: Optional[object] = None,
    shoulder_blend_strength: float = 0.0,
) -> str:
    skin = apply_auto_weights(
        mesh=mesh,
        root_joint=root_joint,
        max_influences=max_influences,
        replace_existing_skin=replace_existing_skin,
        falloff_power=falloff_power,
        bind_method=bind_method,
        custom_distance_weights=custom_distance_weights,
        geodesic_voxel_falloff=geodesic_voxel_falloff,
        geodesic_voxel_resolution=geodesic_voxel_resolution,
        shoulder_profile=shoulder_profile,
        shoulder_blend_strength=shoulder_blend_strength,
    )

    if smooth_iterations:
        smooth_skin_weights(mesh, iterations=smooth_iterations)

    return skin


def auto_skin_selected(
    root_joint: str = "origin",
    max_influences: int = DEFAULT_MAX_INFLUENCES,
    smooth_iterations: int = 2,
    replace_existing_skin: bool = False,
    falloff_power: float = 2.0,
    bind_method: int = DEFAULT_BIND_METHOD,
    custom_distance_weights: bool = True,
    geodesic_voxel_falloff: float = 0.0,
    geodesic_voxel_resolution: int = 256,
    shoulder_profile: Optional[object] = None,
    shoulder_blend_strength: float = 0.0,
) -> str:
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select a mesh first, or pass a mesh explicitly to auto_skin_mesh().")

    mesh = _as_mesh_transform(selection[0])
    return auto_skin_mesh(
        mesh=mesh,
        root_joint=root_joint,
        max_influences=max_influences,
        smooth_iterations=smooth_iterations,
        replace_existing_skin=replace_existing_skin,
        falloff_power=falloff_power,
        bind_method=bind_method,
        custom_distance_weights=custom_distance_weights,
        geodesic_voxel_falloff=geodesic_voxel_falloff,
        geodesic_voxel_resolution=geodesic_voxel_resolution,
        shoulder_profile=shoulder_profile,
        shoulder_blend_strength=shoulder_blend_strength,
    )
