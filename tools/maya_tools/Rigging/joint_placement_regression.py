"""Golden-baseline regression tools for automatic skeleton placement.

Baseline files store approved core joint locations and bone proportions in
mesh-height-normalized coordinates. This makes comparisons invariant to scene
translation and uniform character scale while keeping failures understandable
to rigging artists.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import maya.cmds as cmds

from maya_tools.Rigging import joint_placer


SCHEMA_VERSION = 1
DEFAULT_THRESHOLDS = {
    "mean_anchor_error": 0.0125,
    "max_anchor_error": 0.035,
    "mean_bone_length_error": 0.04,
    "max_bone_length_error": 0.10,
    "mean_mapped_joint_error": 0.02,
    "max_mapped_joint_error": 0.05,
    "max_plane_deviation": 1.0e-5,
    "require_inside": True,
    "require_anatomy_valid": True,
    "required_template_joint_count": 280,
    "required_reverse_foot_joint_count": 12,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _distance(a, b) -> float:
    return math.sqrt(sum((float(a[index]) - float(b[index])) ** 2 for index in range(3)))


def _mesh_frame(mesh: str) -> Dict[str, object]:
    mesh = joint_placer._as_mesh_transform(mesh)
    bounds = joint_placer.get_mesh_bounds(mesh)
    height = max(float(bounds["height"]), 1.0e-8)
    return {
        "mesh": mesh,
        "height": height,
        "origin": (
            float(bounds["center"].x),
            float(bounds["min"].y),
            float(bounds["center"].z),
        ),
        "width_over_height": float(bounds["width"]) / height,
        "depth_over_height": float(bounds["depth"]) / height,
    }


def _normalize_point(point, frame: Dict[str, object]):
    origin = frame["origin"]
    height = frame["height"]
    return [
        (float(point[0]) - origin[0]) / height,
        (float(point[1]) - origin[1]) / height,
        (float(point[2]) - origin[2]) / height,
    ]


def _normalized_points(points: Dict[str, Tuple[float, float, float]], frame):
    return {name: _normalize_point(point, frame) for name, point in points.items()}


def _normalized_bone_lengths(points: Dict[str, object]) -> Dict[str, float]:
    lengths = {}
    for child, parent in joint_placer.PARENT_MAP.items():
        if child in points and parent in points:
            lengths["{0}->{1}".format(parent, child)] = _distance(points[parent], points[child])
    return lengths


def _studio_root(namespace: str = "") -> Optional[str]:
    prefix = joint_placer._template_namespace_prefix(namespace)
    candidates = cmds.ls(prefix + "origin", type="joint", long=True) or []
    required = set(joint_placer.TEMPLATE_CORE_JOINTS.values()) | set(
        joint_placer.HIGH_RES_TEMPLATE_SIGNATURE
    )
    for candidate in candidates:
        descendants = [candidate] + (
            cmds.listRelatives(candidate, ad=True, type="joint", fullPath=True) or []
        )
        short_names = {joint.split("|")[-1].split(":")[-1] for joint in descendants}
        if required.issubset(short_names):
            return candidate
    return None


def _template_anchor_points(
    namespace: str = "",
    root: Optional[str] = None,
) -> Dict[str, Tuple[float, float, float]]:
    root = root or _studio_root(namespace)
    descendants = [root] + (
        cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or []
    ) if root else []
    by_short_name = {}
    for joint in descendants:
        by_short_name.setdefault(joint.split("|")[-1].split(":")[-1], []).append(joint)
    points = {}
    for canonical_name, template_name in joint_placer.TEMPLATE_CORE_JOINTS.items():
        matches = by_short_name.get(template_name, [])
        if len(matches) == 1:
            joint = matches[0]
            position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
            points[canonical_name] = tuple(float(value) for value in position)
    return points


def capture_baseline(
    mesh: str,
    path: str,
    case_id: str = "",
    namespace: str = "",
    notes: str = "",
    thresholds: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Capture the currently approved fitted skeleton as a golden baseline."""
    mesh = joint_placer._as_mesh_transform(mesh)
    root = _studio_root(namespace)
    if not root:
        cmds.error("Fit and approve the high-resolution studio skeleton before capturing a baseline.")

    frame = _mesh_frame(mesh)
    points = _normalized_points(_template_anchor_points(namespace, root=root), frame)
    missing = sorted(set(joint_placer.BUILD_ORDER) - set(points))
    if missing:
        cmds.error("Cannot capture baseline; missing core joints: {0}".format(", ".join(missing)))

    mesh_report = joint_placer.analyze_mesh_for_joint_placement(mesh).as_dict()
    all_joints = [root] + (cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or [])
    rfl_joints = []
    for side in ("l", "r"):
        heel = joint_placer._find_template_joint("{0}_heel_RFL".format(side), namespace)
        if heel:
            rfl_joints.extend([heel] + (cmds.listRelatives(heel, ad=True, type="joint", fullPath=True) or []))

    merged_thresholds = dict(DEFAULT_THRESHOLDS)
    merged_thresholds.update(thresholds or {})
    destination = Path(path).expanduser().resolve()
    data = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id or destination.stem,
        "captured_utc": _utc_now(),
        "notes": notes,
        "source_scene": str(cmds.file(query=True, sceneName=True) or "").replace("\\", "/"),
        "mesh": {
            "node": mesh,
            "vertex_count": mesh_report["vertex_count"],
            "face_count": mesh_report["face_count"],
            "shell_count": mesh_report["shell_count"],
            "width_over_height": frame["width_over_height"],
            "depth_over_height": frame["depth_over_height"],
        },
        "skeleton": {
            "template_joint_count": len(all_joints),
            "reverse_foot_joint_count": len(rfl_joints),
            "anchors": points,
            "bone_lengths": _normalized_bone_lengths(points),
        },
        "thresholds": merged_thresholds,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def capture_mapped_baseline(
    mesh: str,
    path: str,
    target_to_source_joint: Dict[str, str],
    case_id: str = "",
    notes: str = "",
    thresholds: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Capture joints from an external approved rig under studio target names."""
    mesh = joint_placer._as_mesh_transform(mesh)
    frame = _mesh_frame(mesh)
    mapped_points = {}
    missing = []
    for target_name, source_joint in target_to_source_joint.items():
        matches = cmds.ls(source_joint, type="joint", long=True) or []
        if len(matches) != 1:
            missing.append(source_joint)
            continue
        position = cmds.xform(matches[0], query=True, worldSpace=True, translation=True)
        mapped_points[target_name] = _normalize_point(position, frame)
    if missing:
        cmds.error("Cannot capture mapped baseline; unresolved source joints: {0}".format(", ".join(missing)))

    mesh_report = joint_placer.analyze_mesh_for_joint_placement(mesh).as_dict()
    merged_thresholds = dict(DEFAULT_THRESHOLDS)
    merged_thresholds.update(thresholds or {})
    destination = Path(path).expanduser().resolve()
    data = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id or destination.stem,
        "captured_utc": _utc_now(),
        "notes": notes,
        "source_scene": str(cmds.file(query=True, sceneName=True) or "").replace("\\", "/"),
        "mesh": {
            "node": mesh,
            "vertex_count": mesh_report["vertex_count"],
            "face_count": mesh_report["face_count"],
            "shell_count": mesh_report["shell_count"],
            "width_over_height": frame["width_over_height"],
            "depth_over_height": frame["depth_over_height"],
        },
        "skeleton": {
            "template_joint_count": 280,
            "reverse_foot_joint_count": 12,
            "anchors": {},
            "bone_lengths": {},
            "mapped_joints": mapped_points,
        },
        "thresholds": merged_thresholds,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def capture_anchor_baseline(
    mesh: str,
    path: str,
    canonical_to_source_joint: Dict[str, str],
    case_id: str = "",
    notes: str = "",
    thresholds: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Capture approved core anchors from an older or differently named rig."""
    unknown = sorted(set(canonical_to_source_joint) - set(joint_placer.BUILD_ORDER))
    if unknown:
        cmds.error("Unknown canonical anchors: {0}".format(", ".join(unknown)))
    mesh = joint_placer._as_mesh_transform(mesh)
    frame = _mesh_frame(mesh)
    anchors = {}
    missing = []
    for canonical_name, source_joint in canonical_to_source_joint.items():
        matches = cmds.ls(source_joint, type="joint", long=True) or []
        if len(matches) != 1:
            missing.append(source_joint)
            continue
        position = cmds.xform(matches[0], query=True, worldSpace=True, translation=True)
        anchors[canonical_name] = _normalize_point(position, frame)
    if missing:
        cmds.error("Cannot capture anchor baseline; unresolved source joints: {0}".format(", ".join(missing)))

    mesh_report = joint_placer.analyze_mesh_for_joint_placement(mesh).as_dict()
    merged_thresholds = dict(DEFAULT_THRESHOLDS)
    merged_thresholds.update(thresholds or {})
    destination = Path(path).expanduser().resolve()
    data = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id or destination.stem,
        "captured_utc": _utc_now(),
        "notes": notes,
        "source_scene": str(cmds.file(query=True, sceneName=True) or "").replace("\\", "/"),
        "mesh": {
            "node": mesh,
            "vertex_count": mesh_report["vertex_count"],
            "face_count": mesh_report["face_count"],
            "shell_count": mesh_report["shell_count"],
            "width_over_height": frame["width_over_height"],
            "depth_over_height": frame["depth_over_height"],
        },
        "skeleton": {
            "template_joint_count": 280,
            "reverse_foot_joint_count": 12,
            "anchors": anchors,
            "bone_lengths": _normalized_bone_lengths(anchors),
        },
        "thresholds": merged_thresholds,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def load_baseline(path: str) -> Dict[str, object]:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            "Unsupported placement baseline schema {0}: {1}".format(
                data.get("schema_version"), source
            )
        )
    return data


def evaluate_points(
    mesh: str,
    points: Dict[str, Tuple[float, float, float]],
    baseline: Dict[str, object],
    preview: Optional[joint_placer.PlacementPreview] = None,
    template_joint_count: int = 0,
    reverse_foot_joint_count: int = 0,
    fitted_points: Optional[Dict[str, Tuple[float, float, float]]] = None,
) -> Dict[str, object]:
    """Compare a placement result with one approved normalized baseline."""
    frame = _mesh_frame(mesh)
    actual = _normalized_points(points, frame)
    expected = baseline["skeleton"].get("anchors", {})
    common = sorted(set(expected) & set(actual))
    anchor_errors = {name: _distance(expected[name], actual[name]) for name in common}
    actual_lengths = _normalized_bone_lengths(actual)
    expected_lengths = baseline["skeleton"].get("bone_lengths", {})
    length_errors = {}
    for name in sorted(set(expected_lengths) & set(actual_lengths)):
        reference = float(expected_lengths[name])
        # Ratios against effectively singular helper/template segments are
        # numerically meaningless (a safe one-percent repair can otherwise
        # look like a many-thousand-percent regression).  Anatomical validity
        # separately rejects zero-length solved bones.
        if reference < 0.005:
            continue
        length_errors[name] = abs(float(actual_lengths[name]) - reference) / reference

    plane_deviation = joint_placer.measure_planar_deviation(points)
    height = frame["height"]
    plane_deviation = {name: float(value) / height for name, value in plane_deviation.items()}
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(baseline.get("thresholds", {}))
    mean_anchor = sum(anchor_errors.values()) / float(len(anchor_errors) or 1)
    max_anchor = max(anchor_errors.values(), default=0.0)
    mean_length = sum(length_errors.values()) / float(len(length_errors) or 1)
    max_length = max(length_errors.values(), default=0.0)
    max_plane = max(plane_deviation.values(), default=float("inf"))
    outside = list(preview.outside_joints) if preview else []
    anatomy = list(preview.anatomical_issues) if preview else []
    failures = []
    if set(expected) - set(actual):
        failures.append("missing anchors: {0}".format(", ".join(sorted(set(expected) - set(actual)))))
    if anchor_errors and mean_anchor > float(thresholds["mean_anchor_error"]):
        failures.append("mean anchor error {0:.5f}".format(mean_anchor))
    if anchor_errors and max_anchor > float(thresholds["max_anchor_error"]):
        failures.append("max anchor error {0:.5f}".format(max_anchor))
    if length_errors and mean_length > float(thresholds["mean_bone_length_error"]):
        failures.append("mean bone-length error {0:.5f}".format(mean_length))
    if length_errors and max_length > float(thresholds["max_bone_length_error"]):
        failures.append("max bone-length error {0:.5f}".format(max_length))
    if max_plane > float(thresholds["max_plane_deviation"]):
        failures.append("max plane deviation {0:.8f}".format(max_plane))
    if thresholds.get("require_inside") and outside:
        failures.append("outside joints: {0}".format(", ".join(outside)))
    if thresholds.get("require_anatomy_valid") and anatomy:
        failures.append("anatomy: {0}".format("; ".join(anatomy)))
    if template_joint_count and template_joint_count != int(thresholds["required_template_joint_count"]):
        failures.append("template joint count {0}".format(template_joint_count))
    if reverse_foot_joint_count and reverse_foot_joint_count != int(thresholds["required_reverse_foot_joint_count"]):
        failures.append("reverse-foot joint count {0}".format(reverse_foot_joint_count))

    expected_mapped = baseline["skeleton"].get("mapped_joints", {})
    normalized_fitted = _normalized_points(fitted_points or {}, frame)
    mapped_common = sorted(set(expected_mapped) & set(normalized_fitted))
    mapped_errors = {
        name: _distance(expected_mapped[name], normalized_fitted[name])
        for name in mapped_common
    }
    missing_mapped = sorted(set(expected_mapped) - set(normalized_fitted))
    mean_mapped = sum(mapped_errors.values()) / float(len(mapped_errors) or 1)
    max_mapped = max(mapped_errors.values(), default=0.0)
    if missing_mapped:
        failures.append("missing mapped joints: {0}".format(", ".join(missing_mapped)))
    if mapped_errors and mean_mapped > float(thresholds["mean_mapped_joint_error"]):
        failures.append("mean mapped-joint error {0:.5f}".format(mean_mapped))
    if mapped_errors and max_mapped > float(thresholds["max_mapped_joint_error"]):
        failures.append("max mapped-joint error {0:.5f}".format(max_mapped))

    return {
        "case_id": baseline.get("case_id", ""),
        "passed": not failures,
        "failures": failures,
        "metrics": {
            "mean_anchor_error": mean_anchor,
            "max_anchor_error": max_anchor,
            "mean_bone_length_error": mean_length,
            "max_bone_length_error": max_length,
            "max_plane_deviation": max_plane,
            "outside_joint_count": len(outside),
            "anatomy_issue_count": len(anatomy),
            "template_joint_count": template_joint_count,
            "reverse_foot_joint_count": reverse_foot_joint_count,
            "mean_mapped_joint_error": mean_mapped,
            "max_mapped_joint_error": max_mapped,
        },
        "anchor_errors": anchor_errors,
        "actual_anchors": {name: actual[name] for name in common},
        "expected_anchors": {name: expected[name] for name in common},
        "bone_length_errors": length_errors,
        "mapped_joint_errors": mapped_errors,
        "plane_deviation": plane_deviation,
        "thresholds": thresholds,
    }


def evaluate_mesh_against_baseline(
    mesh: str,
    baseline_path: str,
    template_path: str = joint_placer.DEFAULT_PLACEMENT_TEMPLATE,
    build_skeleton: bool = False,
) -> Dict[str, object]:
    baseline = load_baseline(baseline_path)
    if build_skeleton:
        result = joint_placer.build_basic_biped_skeleton(
            mesh,
            solver="production",
            template_path=template_path,
            replace_existing=True,
            create_guides=False,
            require_interior=False,
        )
        preview = joint_placer.PlacementPreview(
            mesh=mesh,
            points=result.points,
            confidence=result.confidence,
            clearance=result.clearance,
            geometry_report=result.geometry_report,
            outside_joints=result.outside_joints,
            anatomical_issues=result.anatomical_issues,
            pose_type=result.pose_type,
            pose_angle_degrees=result.pose_angle_degrees,
            planar_deviation=result.planar_deviation,
            method=result.method,
            template_path=result.template_path,
            requires_review=result.requires_review,
        )
        fitted_points = {}
        for joint_name in baseline["skeleton"].get("mapped_joints", {}):
            joint = joint_placer._find_template_joint(joint_name)
            if joint:
                fitted_points[joint_name] = tuple(
                    cmds.xform(joint, query=True, worldSpace=True, translation=True)
                )
        return evaluate_points(
            mesh,
            result.points,
            baseline,
            preview=preview,
            template_joint_count=result.template_joint_count,
            reverse_foot_joint_count=result.reverse_foot_joint_count,
            fitted_points=fitted_points,
        )
    preview = joint_placer.preview_biped_joint_placement(
        mesh,
        solver="production",
        template_path=template_path,
        create_guides=False,
    )
    return evaluate_points(mesh, preview.points, baseline, preview=preview)


def evaluate_studio_foot_contract(
    namespace: str = "",
    mesh: str = "",
) -> Dict[str, object]:
    """Validate the animator-facing foot result on a fitted studio skeleton."""
    failures = []
    sides = {}
    start_time = float(cmds.currentTime(query=True))
    ground_y = (
        joint_placer.get_mesh_bounds(mesh)["min"].y
        if mesh else 0.0
    )
    for side in ("l", "r"):
        ankle = joint_placer._find_template_joint(side + "_ankle", namespace)
        toe = joint_placer._find_template_joint(side + "_toe", namespace)
        tip = joint_placer._find_template_joint(side + "_toeTip", namespace)
        if not ankle or not toe or not tip:
            failures.append(side + ":missing_foot_chain")
            continue

        points = {
            "ankle": tuple(cmds.xform(ankle, query=True, worldSpace=True, translation=True)),
            "toe": tuple(cmds.xform(toe, query=True, worldSpace=True, translation=True)),
            "tip": tuple(cmds.xform(tip, query=True, worldSpace=True, translation=True)),
        }
        toe_translate = tuple(float(cmds.getAttr(toe + ".translate" + axis)) for axis in "XYZ")
        tip_translate = tuple(float(cmds.getAttr(tip + ".translate" + axis)) for axis in "XYZ")
        toe_rotate = tuple(float(cmds.getAttr(toe + ".rotate" + axis)) for axis in "XYZ")
        tip_rotate = tuple(float(cmds.getAttr(tip + ".rotate" + axis)) for axis in "XYZ")
        toe_orient = tuple(float(cmds.getAttr(toe + ".jointOrient" + axis)) for axis in "XYZ")
        tip_orient = tuple(float(cmds.getAttr(tip + ".jointOrient" + axis)) for axis in "XYZ")
        toe_axis = tuple(float(cmds.getAttr(toe + ".rotateAxis" + axis)) for axis in "XYZ")
        tip_axis = tuple(float(cmds.getAttr(tip + ".rotateAxis" + axis)) for axis in "XYZ")
        axes = joint_placer._joint_world_axes(ankle)
        scale = max(abs(toe_translate[0]), abs(tip_translate[0]), 1.0)
        tolerance = scale * 1.0e-6
        foot_depth = points["toe"][2] - points["ankle"][2]
        toe_depth = points["tip"][2] - points["toe"][2]
        slope_delta = float("inf")
        if abs(foot_depth) > 1.0e-8 and abs(toe_depth) > 1.0e-8:
            slope_delta = abs(
                ((points["toe"][0] - points["ankle"][0]) / foot_depth)
                - ((points["tip"][0] - points["toe"][0]) / toe_depth)
            )
        channels = (
            "translateX", "translateY", "translateZ",
            "rotateX", "rotateY", "rotateZ",
            "scaleX", "scaleY", "scaleZ", "visibility",
        )
        checks = {
            "tip_grounded": abs(points["tip"][1] - ground_y) <= tolerance,
            "toe_translate_x_only": max(abs(toe_translate[1]), abs(toe_translate[2])) <= tolerance,
            "tip_translate_x_only": max(abs(tip_translate[1]), abs(tip_translate[2])) <= tolerance,
            "toe_rotate_z_only": max(abs(toe_rotate[0]), abs(toe_rotate[1])) <= tolerance,
            "tip_rotate_zero": max(map(abs, tip_rotate)) <= tolerance,
            "toe_joint_orient_zero": max(map(abs, toe_orient)) <= tolerance,
            "tip_joint_orient_zero": max(map(abs, tip_orient)) <= tolerance,
            "rotate_axis_zero": max(map(abs, toe_axis + tip_axis)) <= tolerance,
            "stable_ankle_roll": abs(float(axes["z"].y)) <= 1.0e-6 and float(axes["y"].y) > 0.5,
            "continuous_front_line": slope_delta <= 1.0e-6,
            "channels_unlocked": not any(
                cmds.getAttr(node + "." + channel, lock=True)
                for node in (ankle, toe, tip)
                for channel in channels
            ),
        }
        failures.extend(
            side + ":" + name for name, passed in checks.items() if not passed
        )
        sides[side] = {
            "points": points,
            "toe_translate": toe_translate,
            "tip_translate": tip_translate,
            "toe_rotate": toe_rotate,
            "tip_rotate": tip_rotate,
            "ankle_y_world_up": float(axes["y"].y),
            "ankle_z_vertical": float(axes["z"].y),
            "front_slope_delta": slope_delta,
            "checks": checks,
        }

    mirror_error = float("inf")
    if "l" in sides and "r" in sides:
        mirror_error = max(
            max(
                abs(sides["l"]["points"][name][0] + sides["r"]["points"][name][0]),
                abs(sides["l"]["points"][name][1] - sides["r"]["points"][name][1]),
                abs(sides["l"]["points"][name][2] - sides["r"]["points"][name][2]),
            )
            for name in ("ankle", "toe", "tip")
        )
        mirror_scale = max(
            abs(value)
            for side in sides.values()
            for point in side["points"].values()
            for value in point
        )
        if mirror_error > max(mirror_scale, 1.0) * 1.0e-6:
            failures.append("left_right_mirror")

    before = {side: dict(data["points"]) for side, data in sides.items()}
    joint_placer.fit_studio_toe_tips_to_ground(
        namespace=namespace,
        ground_y=ground_y,
    )
    joint_placer.orient_studio_leg_chains(namespace=namespace)
    repeat_drift = 0.0
    for side in ("l", "r"):
        if side not in before:
            continue
        for label, suffix in (("ankle", "ankle"), ("toe", "toe"), ("tip", "toeTip")):
            joint = joint_placer._find_template_joint(side + "_" + suffix, namespace)
            current = tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
            repeat_drift = max(
                repeat_drift,
                max(abs(before[side][label][index] - current[index]) for index in range(3)),
            )
    if repeat_drift > 1.0e-6:
        failures.append("repeat_run_drift")
    if abs(float(cmds.currentTime(query=True)) - start_time) > 1.0e-8:
        failures.append("timeline_changed")

    return {
        "passed": not failures,
        "failures": failures,
        "mirror_error": mirror_error,
        "repeat_run_drift": repeat_drift,
        "sides": sides,
    }


def evaluate_studio_pelvis_contract(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Validate the shared pelvis-ridge lift on a fitted studio skeleton."""
    failures = []
    names = ("origin", "pelvis", "hipswing", "l_thigh", "r_thigh", "l_knee", "r_knee")
    joints = {
        name: joint_placer._find_template_joint(name, namespace)
        for name in names
    }
    missing = [name for name, joint in joints.items() if not joint]
    if missing:
        return {
            "passed": False,
            "failures": ["missing joints: " + ", ".join(missing)],
        }
    points = {
        name: tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        for name, joint in joints.items()
    }
    bounds = joint_placer.get_mesh_bounds(mesh)
    query = joint_placer.MeshInteriorQuery(mesh)
    height = max(float(bounds["height"]), 1.0e-8)
    tolerance = height * 1.0e-6
    pelvis_ratio = (points["pelvis"][1] - float(bounds["min"].y)) / height
    root = joints["origin"]
    stage = (
        cmds.getAttr(root + "." + joint_placer.PELVIS_RIDGE_STAGE_ATTR)
        if cmds.attributeQuery(
            joint_placer.PELVIS_RIDGE_STAGE_ATTR,
            node=root,
            exists=True,
        )
        else ""
    )
    applied_lift = (
        float(cmds.getAttr(root + "." + joint_placer.PELVIS_RIDGE_LIFT_ATTR))
        if cmds.attributeQuery(
            joint_placer.PELVIS_RIDGE_LIFT_ATTR,
            node=root,
            exists=True,
        )
        else 0.0
    )
    channels = (
        "translateX", "translateY", "translateZ",
        "rotateX", "rotateY", "rotateZ",
        "scaleX", "scaleY", "scaleZ", "visibility",
    )
    checks = {
        "stage_recorded": stage == "fitted",
        "origin_zero": max(map(abs, points["origin"])) <= tolerance,
        "shared_lift_recorded": (
            applied_lift > 0.0
            and applied_lift
            <= height * joint_placer.STUDIO_PELVIS_RIDGE_LIFT_HEIGHT_RATIO
        ),
        "thigh_height_mirrored": abs(
            points["l_thigh"][1] - points["r_thigh"][1]
        ) <= tolerance,
        "thighs_near_pelvis_ridge": max(
            abs(points["l_thigh"][1] - points["pelvis"][1]),
            abs(points["r_thigh"][1] - points["pelvis"][1]),
        ) <= height * 0.02,
        "pelvis_height_anatomical": 0.48 <= pelvis_ratio <= 0.60,
        "ridge_joints_inside": all(
            query.point_inside(points[name])
            for name in ("pelvis", "hipswing", "l_thigh", "r_thigh")
        ),
        "channels_unlocked": not any(
            cmds.getAttr(node + "." + channel, lock=True)
            for node in joints.values()
            for channel in channels
        ),
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    before = dict(points)
    joint_placer.fit_studio_pelvis_ridge(mesh, namespace=namespace)
    repeat_drift = 0.0
    for name, joint in joints.items():
        current = tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        repeat_drift = max(
            repeat_drift,
            max(abs(before[name][index] - current[index]) for index in range(3)),
        )
    if repeat_drift > tolerance:
        failures.append("repeat_run_drift")
    return {
        "passed": not failures,
        "failures": failures,
        "pelvis_height_ratio": pelvis_ratio,
        "applied_lift": applied_lift,
        "repeat_run_drift": repeat_drift,
        "checks": checks,
        "points": points,
    }


def write_report(report: Dict[str, object], path: str) -> str:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return str(destination).replace("\\", "/")


def capture_selected_baseline(path: str, case_id: str = "", namespace: str = ""):
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select the approved character mesh first.")
    return capture_baseline(selection[0], path, case_id=case_id, namespace=namespace)


def evaluate_selected_mesh(baseline_path: str, template_path: str = joint_placer.DEFAULT_PLACEMENT_TEMPLATE):
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select the character mesh to validate first.")
    return evaluate_mesh_against_baseline(selection[0], baseline_path, template_path=template_path)

