"""Build the checked-in joint-placement atlas from approved studio Maya rigs.

Run this module with Maya's ``mayapy``.  Source scenes are opened read-only and
the resulting normalized joint coordinates are written beneath
``joint_placement_reference_atlas`` next to this file.
"""

from __future__ import annotations

import json
import heapq
from pathlib import Path
from typing import Dict, Iterable, Tuple

import maya.cmds as cmds
import maya.api.OpenMaya as om


SCHEMA_VERSION = 1
CORE_NAMES = (
    "origin", "pelvis", "spine1", "spine3", "spine5", "spine5_Tip",
    "neck1", "head1", "head1_Tip",
    "l_clavicle", "l_upperarm", "l_lowerarm", "l_hand", "l_handTip",
    "r_clavicle", "r_upperarm", "r_lowerarm", "r_hand", "r_handTip",
    "l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip",
    "r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip",
)
SIGNATURE = (
    "l_upperarm1_twist", "r_thigh_twist1", "l_pinky_01",
    "r_thumb_04", "jaw", "l_eye", "r_eye",
)


def _short_name(node: str) -> str:
    return node.split("|")[-1].split(":")[-1]


def _studio_root() -> str:
    required = set(CORE_NAMES) | set(SIGNATURE)
    for candidate in cmds.ls("*:origin", "origin", type="joint", long=True) or []:
        descendants = [candidate] + (
            cmds.listRelatives(candidate, allDescendents=True, type="joint", fullPath=True)
            or []
        )
        names = {_short_name(joint) for joint in descendants}
        if required.issubset(names):
            return candidate
    raise RuntimeError("The scene does not contain an unambiguous studio origin hierarchy.")


def _largest_body_mesh() -> str:
    candidates = []
    for shape in cmds.ls(type="mesh", long=True) or []:
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        if not transform:
            continue
        bounds = cmds.exactWorldBoundingBox(transform)
        height = float(bounds[4] - bounds[1])
        width = float(bounds[3] - bounds[0])
        vertices = int(cmds.polyEvaluate(shape, vertex=True) or 0)
        # The approved bodies share the 29,094-vertex production topology.
        # Height wins first; vertex count and T-pose span break close ties.
        candidates.append(((height, vertices, width), transform))
    if not candidates:
        raise RuntimeError("The scene does not contain a renderable polygon mesh.")
    return max(candidates, key=lambda item: item[0])[1]


def _normalized_point(point, origin, height):
    return [
        (float(point[0]) - origin[0]) / height,
        (float(point[1]) - origin[1]) / height,
        (float(point[2]) - origin[2]) / height,
    ]


def _mesh_points(mesh: str):
    selection = om.MSelectionList()
    selection.add(mesh)
    dag_path = selection.getDagPath(0)
    if dag_path.node().hasFn(om.MFn.kTransform):
        dag_path.extendToShape()
    return om.MFnMesh(dag_path).getPoints(om.MSpace.kWorld)


def capture_scene(scene: str, case_id: str, output_directory: str) -> Dict[str, object]:
    """Open one approved rig and capture every uniquely named deform joint."""
    cmds.file(new=True, force=True)
    cmds.file(scene, open=True, force=True, ignoreVersion=True, prompt=False)
    mesh = _largest_body_mesh()
    root = _studio_root()
    bounds = cmds.exactWorldBoundingBox(mesh)
    height = max(float(bounds[4] - bounds[1]), 1.0e-8)
    origin = (
        (float(bounds[0]) + float(bounds[3])) * 0.5,
        float(bounds[1]),
        (float(bounds[2]) + float(bounds[5])) * 0.5,
    )
    width = float(bounds[3] - bounds[0])
    depth = float(bounds[5] - bounds[2])

    hierarchy = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    )
    by_name: Dict[str, list] = {}
    for joint in hierarchy:
        by_name.setdefault(_short_name(joint), []).append(joint)
    duplicate_names = sorted(name for name, joints in by_name.items() if len(joints) != 1)
    if duplicate_names:
        raise RuntimeError(
            "Studio hierarchy contains duplicate joint names: {}".format(
                ", ".join(duplicate_names[:12])
            )
        )

    points = {}
    axes = {}
    world_joint_points = {}
    for name, joints in sorted(by_name.items()):
        position = cmds.xform(joints[0], query=True, worldSpace=True, translation=True)
        matrix = cmds.xform(joints[0], query=True, worldSpace=True, matrix=True)
        world_joint_points[name] = tuple(float(value) for value in position)
        points[name] = _normalized_point(position, origin, height)
        axes[name] = {
            "x": [float(value) for value in matrix[0:3]],
            "y": [float(value) for value in matrix[4:7]],
            "z": [float(value) for value in matrix[8:11]],
        }

    missing = sorted(set(CORE_NAMES) - set(points))
    if missing:
        raise RuntimeError("Missing core joints: {}".format(", ".join(missing)))

    mesh_points = _mesh_points(mesh)
    joint_vertices = {}
    referenced_vertex_ids = set()
    neighbor_count = 32
    for name, joint_point in world_joint_points.items():
        nearest = heapq.nsmallest(
            neighbor_count,
            range(len(mesh_points)),
            key=lambda index: (
                (mesh_points[index].x - joint_point[0]) ** 2
                + (mesh_points[index].y - joint_point[1]) ** 2
                + (mesh_points[index].z - joint_point[2]) ** 2
            ),
        )
        joint_vertices[name] = nearest
        referenced_vertex_ids.update(nearest)
    topology_vertices = {
        str(index): _normalized_point(mesh_points[index], origin, height)
        for index in sorted(referenced_vertex_ids)
    }

    data = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "source_scene": str(Path(scene)).replace("\\", "/"),
        "mesh": {
            "node": mesh,
            "height": height,
            "width_over_height": width / height,
            "depth_over_height": depth / height,
            "vertex_count": int(cmds.polyEvaluate(mesh, vertex=True) or 0),
        },
        "skeleton": {
            "joint_count": len(points),
            "points": points,
            "axes": axes,
        },
        "topology": {
            "vertex_count": int(cmds.polyEvaluate(mesh, vertex=True) or 0),
            "face_count": int(cmds.polyEvaluate(mesh, face=True) or 0),
            "neighbor_count": neighbor_count,
            "vertices": topology_vertices,
            "joint_vertices": joint_vertices,
        },
    }
    destination = Path(output_directory) / (case_id + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def build_atlas(
    cases: Iterable[Tuple[str, str]],
    output_directory: str = "",
) -> Dict[str, object]:
    destination = Path(output_directory) if output_directory else (
        Path(__file__).resolve().parent / "joint_placement_reference_atlas"
    )
    captured = []
    failures = []
    for case_id, scene in cases:
        try:
            data = capture_scene(scene, case_id, str(destination))
            captured.append({
                "case_id": case_id,
                "joint_count": data["skeleton"]["joint_count"],
                "source_scene": data["source_scene"],
            })
        except Exception as exc:
            failures.append({
                "case_id": case_id,
                "source_scene": scene,
                "error": "{}: {}".format(type(exc).__name__, exc),
            })
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured": captured,
        "failures": failures,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest

