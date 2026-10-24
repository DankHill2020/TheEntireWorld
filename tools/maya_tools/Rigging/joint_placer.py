"""
joint_placer.py

Production-oriented automatic biped joint placement for Maya.

Design goal:
    mesh -> generated skeleton -> setup_hik-owned body/face maps

This module intentionally does NOT define its own HIK map. It creates joints with
names that setup_hik.guess_joint_map_from_root() already understands, then asks
setup_hik to build the mapping used by create_rig.py.

The placement pipeline is deliberately hybrid. A proportional template or an
optional learned-landmark provider proposes anatomical locations; mesh
cross-sections then recenter those proposals, and an independent inside-volume
query validates every result. This follows the production pattern of treating
ML as a proposal source rather than allowing an unverified prediction to become
a rig joint.
"""

from __future__ import annotations

import json
import hashlib
import heapq
import math
from pathlib import Path
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import maya.cmds as cmds
import maya.api.OpenMaya as om

from maya_tools.Rigging.mocap import setup_hik
from maya_tools.Rigging import rig_template
from maya_tools.Rigging.create_rig_core import normalize_rfl_joint_suffixes
from maya_tools.Rigging.undo_utils import undoable
from maya_tools.Rigging.temp_cleanup import cleanup_temp_bones


Vector3 = Tuple[float, float, float]
GENERATED_ATTR = "autoJointPlacerGenerated"
POSE_ATTR = "autoJointPlacerPose"
POSE_ANGLE_ATTR = "autoJointPlacerPoseAngle"
TEMPLATE_SCALE_ATTR = "autoJointPlacerTemplateScale"
RFL_SCALE_ATTR = "autoJointPlacerReverseFootScale"
RFL_SNAP_STAGE_ATTR = "autoJointPlacerReverseFootSnapStage"
PELVIS_RIDGE_STAGE_ATTR = "autoJointPlacerPelvisRidgeStage"
PELVIS_RIDGE_LIFT_ATTR = "autoJointPlacerPelvisRidgeLift"
PELVIS_RIDGE_THIGH_INSET_ATTR = "autoJointPlacerThighInset"
TEMPLATE_SOURCE_ATTR = "autoJointPlacerTemplateSource"
PLACEMENT_MESH_ATTR = "autoJointPlacerSourceMesh"
PLACEMENT_MESH_MESSAGE_ATTR = "autoJointPlacerSourceMeshMessage"
PLACEMENT_MESH_SIGNATURE_ATTR = "autoJointPlacerSourceMeshSignature"
BEND_AXIS_ATTR = "autoJointPlacerBendAxis"
BEND_PLANE_ATTR = "autoJointPlacerBendPlane"
TEMPLATE_KNEE_BEND_AXIS_ATTR = "autoJointPlacerTemplateKneeBendAxis"
STUDIO_TEMPLATE_KNEE_BEND_AXIS = "y"
BEND_POLICY_ATTR = "autoJointPlacerBendPolicy"
DETAIL_REPORT_ATTR = "autoJointPlacerDetailReport"
HAND_FIT_REPORT_ATTR = "autoJointPlacerHandFitReport"
STUDIO_VOLUME_REPORT_ATTR = "autoJointPlacerStudioVolumeReport"
REFERENCE_ATLAS_ATTR = "autoJointPlacerReferenceAtlas"
PLANAR_TOLERANCE = 0.001
STUDIO_CLAVICLE_LIFT_HEIGHT_RATIO = 0.006
STUDIO_KNEE_DROP_HEIGHT_RATIO = 0.009
STUDIO_FOOT_OUTWARD_HEIGHT_RATIO = 0.008
STUDIO_PELVIS_RIDGE_LIFT_HEIGHT_RATIO = 0.015
STUDIO_WRIST_DORSAL_FRACTION = 0.60
# Reference/volume fitting already places the femoral heads at the hip
# sockets. A second medial inset put them inside the pelvis.
STUDIO_THIGH_INSET_HEIGHT_RATIO = 0.0
DEFAULT_PLACEMENT_TEMPLATE = rig_template.DEFAULT_BIPED_RIG_TEMPLATE
DEFAULT_SKIN_WEIGHT_DIR = "C:/temp/weights"
_TEMPLATE_POINT_CACHE: Dict[Tuple[str, float], Dict[str, Vector3]] = {}
_TEMPLATE_AXIS_CACHE: Dict[Tuple[str, float], Dict[str, Dict[str, Vector3]]] = {}
_REFERENCE_CORPUS_CACHE: Dict[str, object] = {}


@dataclass(frozen=True)
class PlacementFrame:
    """Permutation/sign frame mapping a character into logical X/Y/Z space."""
    side_axis: int = 0
    up_axis: int = 1
    depth_axis: int = 2
    side_sign: float = 1.0
    up_sign: float = 1.0
    depth_sign: float = 1.0

    def world_to_logical(self, point: Vector3) -> Vector3:
        return (
            float(point[self.side_axis]) * self.side_sign,
            float(point[self.up_axis]) * self.up_sign,
            float(point[self.depth_axis]) * self.depth_sign,
        )

    def logical_to_world(self, point: Vector3) -> Vector3:
        result = [0.0, 0.0, 0.0]
        result[self.side_axis] = float(point[0]) * self.side_sign
        result[self.up_axis] = float(point[1]) * self.up_sign
        result[self.depth_axis] = float(point[2]) * self.depth_sign
        return tuple(result)

    def world_axis(self, logical_axis: str) -> str:
        index = {"x": self.side_axis, "y": self.up_axis, "z": self.depth_axis}[logical_axis]
        return "xyz"[index]

    def world_index(self, logical_axis: str) -> int:
        return {"x": self.side_axis, "y": self.up_axis, "z": self.depth_axis}[logical_axis]

    def world_normal(self, logical_axis: str) -> Vector3:
        result = [0.0, 0.0, 0.0]
        index = self.world_index(logical_axis)
        sign = {"x": self.side_sign, "y": self.up_sign, "z": self.depth_sign}[logical_axis]
        result[index] = sign
        return tuple(result)


@dataclass
class PlacementResult:
    root_joint: str
    body_joint_map: dict
    face_joint_map: dict
    points: Dict[str, Vector3]
    confidence: Dict[str, float]
    pose_type: str = "unknown"
    pose_angle_degrees: float = 0.0
    planar_deviation: Dict[str, float] = field(default_factory=dict)
    method: str = "production_hybrid"
    template_path: str = ""
    geometry_report: Dict[str, object] = field(default_factory=dict)
    outside_joints: List[str] = field(default_factory=list)
    anatomical_issues: List[str] = field(default_factory=list)
    clearance: Dict[str, float] = field(default_factory=dict)
    template_joint_count: int = 0
    reverse_foot_joint_count: int = 0
    requires_review: bool = False
    detail_placement_report: Dict[str, object] = field(default_factory=dict)


@dataclass
class PlacementPreview:
    mesh: str
    points: Dict[str, Vector3]
    confidence: Dict[str, float]
    clearance: Dict[str, float]
    geometry_report: Dict[str, object]
    outside_joints: List[str]
    anatomical_issues: List[str]
    pose_type: str
    pose_angle_degrees: float
    planar_deviation: Dict[str, float]
    method: str
    template_path: str
    requires_review: bool
    guides: List[str] = field(default_factory=list)


@dataclass
class MeshPlacementReport:
    mesh: str
    vertex_count: int
    face_count: int
    shell_count: int
    boundary_edge_count: int
    non_manifold_edge_count: int
    lamina_face_count: int

    @property
    def is_closed_manifold(self) -> bool:
        return (
            self.shell_count == 1
            and self.boundary_edge_count == 0
            and self.non_manifold_edge_count == 0
            and self.lamina_face_count == 0
        )

    def as_dict(self) -> Dict[str, object]:
        return {
            "mesh": self.mesh,
            "vertex_count": self.vertex_count,
            "face_count": self.face_count,
            "shell_count": self.shell_count,
            "boundary_edge_count": self.boundary_edge_count,
            "non_manifold_edge_count": self.non_manifold_edge_count,
            "lamina_face_count": self.lamina_face_count,
            "is_closed_manifold": self.is_closed_manifold,
        }


# Proportional fallback template.
# Values are normalized against the mesh bounding box:
#   x: -0.5 left side of bbox to +0.5 right side of bbox
#   y:  0.0 bottom to 1.0 top
#   z: -0.5 back to +0.5 front
# This is deliberately simple and predictable. Later solvers can override
# individual entries with cross-section or landmark results.
BIPED_PROPORTIONS: Dict[str, Vector3] = {
    "origin": (0.0, 0.50, 0.0),
    "pelvis": (0.0, 0.48, 0.0),

    "spine_01": (0.0, 0.56, 0.0),
    "spine_02": (0.0, 0.64, 0.0),
    "spine_03": (0.0, 0.72, 0.0),
    "spine_04": (0.0, 0.78, 0.0),

    "neck": (0.0, 0.86, 0.0),
    "head": (0.0, 0.93, 0.0),
    "head_tip": (0.0, 0.99, 0.0),

    "l_clavicle": (0.13, 0.80, 0.0),
    "l_upperarm": (0.25, 0.78, 0.0),
    "l_lowerarm": (0.42, 0.69, 0.0),
    "l_hand": (0.56, 0.61, 0.0),
    "l_hand_tip": (0.63, 0.59, 0.0),

    "r_clavicle": (-0.13, 0.80, 0.0),
    "r_upperarm": (-0.25, 0.78, 0.0),
    "r_lowerarm": (-0.42, 0.69, 0.0),
    "r_hand": (-0.56, 0.61, 0.0),
    "r_hand_tip": (-0.63, 0.59, 0.0),

    "l_thigh": (0.13, 0.46, 0.0),
    "l_knee": (0.13, 0.27, 0.02),
    "l_ankle": (0.13, 0.08, 0.0),
    "l_toe": (0.13, 0.035, 0.18),
    "l_toeTip": (0.13, 0.03, 0.28),

    "r_thigh": (-0.13, 0.46, 0.0),
    "r_knee": (-0.13, 0.27, 0.02),
    "r_ankle": (-0.13, 0.08, 0.0),
    "r_toe": (-0.13, 0.035, 0.18),
    "r_toeTip": (-0.13, 0.03, 0.28),
}


PARENT_MAP = {
    "pelvis": "origin",
    "spine_01": "pelvis",
    "spine_02": "spine_01",
    "spine_03": "spine_02",
    "spine_04": "spine_03",
    "neck": "spine_04",
    "head": "neck",
    "head_tip": "head",

    "l_clavicle": "spine_04",
    "l_upperarm": "l_clavicle",
    "l_lowerarm": "l_upperarm",
    "l_hand": "l_lowerarm",
    "l_hand_tip": "l_hand",

    "r_clavicle": "spine_04",
    "r_upperarm": "r_clavicle",
    "r_lowerarm": "r_upperarm",
    "r_hand": "r_lowerarm",
    "r_hand_tip": "r_hand",

    "l_thigh": "pelvis",
    "l_knee": "l_thigh",
    "l_ankle": "l_knee",
    "l_toe": "l_ankle",
    "l_toeTip": "l_toe",

    "r_thigh": "pelvis",
    "r_knee": "r_thigh",
    "r_ankle": "r_knee",
    "r_toe": "r_ankle",
    "r_toeTip": "r_toe",
}


BUILD_ORDER = [
    "origin",
    "pelvis",
    "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head", "head_tip",
    "l_clavicle", "l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip",
    "r_clavicle", "r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip",
    "l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip",
    "r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip",
]


TEMPLATE_CORE_JOINTS = {
    "origin": "origin",
    "pelvis": "pelvis",
    "spine_01": "spine1",
    "spine_02": "spine3",
    "spine_03": "spine5",
    "spine_04": "spine5_Tip",
    "neck": "neck1",
    "head": "head1",
    "head_tip": "head1_Tip",
    "l_clavicle": "l_clavicle",
    "l_upperarm": "l_upperarm",
    "l_lowerarm": "l_lowerarm",
    "l_hand": "l_hand",
    "l_hand_tip": "l_handTip",
    "r_clavicle": "r_clavicle",
    "r_upperarm": "r_upperarm",
    "r_lowerarm": "r_lowerarm",
    "r_hand": "r_hand",
    "r_hand_tip": "r_handTip",
    "l_thigh": "l_thigh",
    "l_knee": "l_knee",
    "l_ankle": "l_ankle",
    "l_toe": "l_toe",
    "l_toeTip": "l_toeTip",
    "r_thigh": "r_thigh",
    "r_knee": "r_knee",
    "r_ankle": "r_ankle",
    "r_toe": "r_toe",
    "r_toeTip": "r_toeTip",
}

HIGH_RES_TEMPLATE_SIGNATURE = (
    "l_upperarm1_twist",
    "r_thigh_twist1",
    "l_pinky_01",
    "r_thumb_04",
    "jaw",
    "l_eye",
    "r_eye",
)

# Internal head pivots are too far from the skin for a local surface-affine
# solve.  The same production topology is used by the approved references, so
# these joints are fitted from a robust proportional consensus instead.  This
# also covers tongue and teeth geometry that is welded into the single body
# mesh rather than exposed as separately named mesh transforms.
INTERNAL_HEAD_REFERENCE_JOINTS = (
    "neck2",
    "head1",
    "head1_Tip",
    "jaw",
    "jaw_Tip",
    "upper_teeth",
    "lower_teeth",
    "tongue1",
    "tongue2",
    "tongue3",
    "tongue4",
)
REFERENCE_TOE_JOINTS = (
    "l_toe",
    "l_toeTip",
    "r_toe",
    "r_toeTip",
)

STUDIO_LEG_MIRROR_SUFFIXES = (
    "thigh",
    "thigh_twist1", "thigh_twist2", "thigh_twist3", "thigh_twist4",
    "knee",
    "knee_twist1", "knee_twist2", "knee_twist3",
    "ankle", "toe", "toeTip",
    "heel_RFL", "toeTip_RFL", "toe_RFL", "ankle_RFL",
)

# ``origin`` is a rig-space reference pivot, not a deform joint.  Industry
# biped rigs keep it on the floor beneath the pelvis, which intentionally puts
# it between the feet and therefore outside the character volume.
NON_DEFORM_PLACEMENT_ROLES = frozenset(("origin",))

HIK_CORE_PLACEMENT_SLOTS = {
    "Reference": "origin",
    "Hips": "pelvis",
    "Neck": "neck",
    "Head": "head",
    "LeftShoulder": "l_clavicle",
    "LeftArm": "l_upperarm",
    "LeftForeArm": "l_lowerarm",
    "LeftHand": "l_hand",
    "RightShoulder": "r_clavicle",
    "RightArm": "r_upperarm",
    "RightForeArm": "r_lowerarm",
    "RightHand": "r_hand",
    "LeftUpLeg": "l_thigh",
    "LeftLeg": "l_knee",
    "LeftFoot": "l_ankle",
    "LeftToeBase": "l_toe",
    "RightUpLeg": "r_thigh",
    "RightLeg": "r_knee",
    "RightFoot": "r_ankle",
    "RightToeBase": "r_toe",
}

REQUIRED_MAPPED_PLACEMENT_SLOTS = (
    "Hips", "Spine", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
    "RightUpLeg", "RightLeg", "RightFoot",
)


# Cross-sections are taken perpendicular to the expected local bone direction.
# This preserves the longitudinal position of a proposal while moving its pivot
# toward the local medial region of the mesh.
PLACEMENT_SECTION_AXES = {
    "origin": ("x", "z"),
    "pelvis": ("x", "z"),
    "spine_01": ("x", "z"),
    "spine_02": ("x", "z"),
    "spine_03": ("x", "z"),
    "spine_04": ("x", "z"),
    "neck": ("x", "z"),
    "head": ("x", "z"),
    "head_tip": ("x", "z"),
    "l_clavicle": ("z",),
    # At the humeral head, a world-up ray crosses the deltoid and torso as one
    # broad interval; its midpoint is the armpit, not the shoulder pivot. Keep
    # the anatomically fitted height and solve only mesh depth here.
    "l_upperarm": ("z",),
    "l_lowerarm": ("y", "z"),
    "l_hand": ("y", "z"),
    "l_hand_tip": ("y", "z"),
    "r_clavicle": ("z",),
    "r_upperarm": ("z",),
    "r_lowerarm": ("y", "z"),
    "r_hand": ("y", "z"),
    "r_hand_tip": ("y", "z"),
    "l_thigh": ("x", "z"),
    "l_knee": ("x", "z"),
    "l_ankle": ("x", "z"),
    "r_thigh": ("x", "z"),
    "r_knee": ("x", "z"),
    "r_ankle": ("x", "z"),
    # Preserve authored foot height and forward position. A world-up ray at a
    # toe proposal can intersect the shin or torso and incorrectly choose that
    # remote volume; lateral centering is local and safe here.
    "l_toe": ("x",),
    "l_toeTip": ("x",),
    "r_toe": ("x",),
    "r_toeTip": ("x",),
}


def _short_name(node: str) -> str:
    return node.split("|")[-1]


def _point_vector(points: Dict[str, Vector3], name: str) -> Optional[om.MVector]:
    value = points.get(name)
    if not value:
        return None
    return om.MVector(value[0], value[1], value[2])


def classify_arm_pose(
    points: Dict[str, Vector3],
    frame: Optional[PlacementFrame] = None,
) -> Tuple[str, float]:
    """
    Classify generated arm placement as T-pose or A-pose from shoulder-to-hand slope.

    Returns:
        tuple[str, float]: pose label and absolute arm-down angle from horizontal.
    """
    frame = frame or PlacementFrame()
    if frame != PlacementFrame():
        logical_points = {name: frame.world_to_logical(point) for name, point in points.items()}
        return classify_arm_pose(logical_points)
    samples = []
    for side in ("l", "r"):
        shoulder = _point_vector(points, "{0}_upperarm".format(side))
        hand = _point_vector(points, "{0}_hand".format(side))
        if not shoulder or not hand:
            continue
        delta = hand - shoulder
        horizontal = abs(delta.x)
        vertical_drop = max(0.0, shoulder.y - hand.y)
        if horizontal <= 0.0001:
            continue
        samples.append(math.degrees(math.atan2(vertical_drop, horizontal)))

    if not samples:
        return "unknown", 0.0

    angle = sum(samples) / float(len(samples))
    if angle <= 12.0:
        return "t_pose", angle
    if angle >= 22.0:
        return "a_pose", angle
    return "relaxed_t_pose", angle


def _line_value_at(
    start: Vector3,
    end: Vector3,
    sample: Vector3,
    parameter_axis: int,
    value_axis: int,
) -> float:
    denominator = end[parameter_axis] - start[parameter_axis]
    if abs(denominator) <= 1.0e-8:
        return (start[value_axis] + end[value_axis]) * 0.5
    ratio = (sample[parameter_axis] - start[parameter_axis]) / denominator
    return start[value_axis] + ((end[value_axis] - start[value_axis]) * ratio)


def enforce_limb_planarity(
    points: Dict[str, Vector3],
    minimum_bend: float = 0.0,
    inside_query: Optional["MeshInteriorQuery"] = None,
    frame: Optional[PlacementFrame] = None,
) -> Dict[str, Vector3]:
    """
    Put the primary IK chains on explicit anatomical planes.

    Arms use the template's side/up bend plane: depth is the outward hinge
    axis (local Y), so the elbow prebend must be vertical rather than drifting
    toward character-front/back. Legs and the spine use YZ planes (constant
    X). A small elbow/knee prebend is retained or introduced inside the
    corresponding plane so a rotate-plane IK solver never receives a singular
    straight chain.
    """
    result = dict(points)
    frame = frame or PlacementFrame()
    chains = [
        (["l_thigh", "l_knee", "l_ankle"], frame.side_axis),
        (["r_thigh", "r_knee", "r_ankle"], frame.side_axis),
        (["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"], frame.side_axis),
    ]

    for chain, fixed_axis in chains:
        values = [result[name][fixed_axis] for name in chain if name in result]
        if not values:
            continue
        plane_value = sum(values) / float(len(values))
        if inside_query is not None:
            # A numerical mean can put a perfectly planar chain just outside a
            # curved or asymmetrical limb. Evaluate the authored section values
            # as candidate planes and retain the plane containing the greatest
            # number of joints. Distance from the mean is the deterministic
            # tie-breaker, preserving the least possible shape change.
            candidates = sorted(set(values + [plane_value]))

            axis_name = next(
                axis_name
                for axis_name, (_direction, component) in inside_query._AXES.items()
                if component == fixed_axis
            )
            local_intervals = []
            expected_count = 0
            for joint_name in chain:
                if joint_name not in result:
                    continue
                expected_count += 1
                point = result[joint_name]
                interval = _choose_interval(
                    inside_query.axis_intervals(point, axis_name),
                    point[fixed_axis],
                )
                if interval is not None:
                    local_intervals.append(interval)

            # Prefer the center of the volume shared by every joint section.
            # This guarantees that an exact IK plane is genuinely supported by
            # the mesh instead of merely winning a vote from wider sections.
            shared_low = max((interval[0] for interval in local_intervals), default=0.0)
            shared_high = min((interval[1] for interval in local_intervals), default=-1.0)
            has_shared_volume = (
                len(local_intervals) == expected_count
                and shared_high - shared_low > inside_query.tolerance * 2.0
            )

            def _plane_score(candidate_value):
                inside_count = 0
                normalized_clearances = []
                for joint_name in chain:
                    if joint_name not in result:
                        continue
                    candidate_point = list(result[joint_name])
                    candidate_point[fixed_axis] = candidate_value
                    candidate_point = tuple(candidate_point)
                    is_inside = inside_query.point_inside(candidate_point)
                    inside_count += int(is_inside)
                    if not is_inside:
                        normalized_clearances.append(-1.0)
                        continue
                    interval = _choose_interval(
                        inside_query.axis_intervals(candidate_point, axis_name),
                        candidate_value,
                    )
                    if interval is None:
                        normalized_clearances.append(0.0)
                        continue
                    half_width = max((interval[1] - interval[0]) * 0.5, 1.0e-8)
                    interval_center = (interval[0] + interval[1]) * 0.5
                    normalized_clearances.append(
                        1.0 - min(abs(candidate_value - interval_center) / half_width, 1.0)
                    )
                minimum_clearance = min(normalized_clearances) if normalized_clearances else -1.0
                mean_clearance = (
                    sum(normalized_clearances) / float(len(normalized_clearances))
                    if normalized_clearances else -1.0
                )
                return (
                    inside_count,
                    minimum_clearance,
                    mean_clearance,
                    -abs(candidate_value - plane_value),
                )

            if has_shared_volume:
                if chain and chain[0].endswith("upperarm"):
                    # Shoulder height is an anatomical landmark, whereas the
                    # shared vertical-volume midpoint trends toward the lower
                    # forearm/hand mass. Preserve that landmark and clamp only
                    # if a narrower downstream section cannot contain it.
                    plane_value = max(shared_low, min(values[0], shared_high))
                else:
                    plane_value = (shared_low + shared_high) * 0.5
            else:
                plane_value = max(candidates, key=_plane_score)
        for name in chain:
            if name in result:
                point = list(result[name])
                point[fixed_axis] = plane_value
                result[name] = tuple(point)

    # Feet follow the solved hip-knee-ankle plane but must not participate in
    # choosing it. On characters with tapered or offset feet, including toe
    # samples in the vote can select a lateral foot plane that misses the thigh
    # entirely. If a toe is not contained at the ankle plane, repair it within
    # that exact plane by changing only its height/depth coordinates.
    if inside_query is not None:
        side_axis_name = next(
            axis_name
            for axis_name, (_direction, component) in inside_query._AXES.items()
            if component == frame.side_axis
        )
        for side in ("l", "r"):
            ankle_name = "{0}_ankle".format(side)
            if ankle_name not in result:
                continue
            plane_value = result[ankle_name][frame.side_axis]
            for foot_name in ("{0}_toe".format(side), "{0}_toeTip".format(side)):
                if foot_name not in result:
                    continue
                candidate = list(result[foot_name])
                candidate[frame.side_axis] = plane_value
                candidate = tuple(candidate)
                if inside_query.point_inside(candidate):
                    result[foot_name] = candidate
                    continue
                repaired, success = inside_query.move_inside_preserving_plane(
                    candidate,
                    fixed_axis=side_axis_name,
                )
                move_distance = (
                    om.MVector(*repaired) - om.MVector(*candidate)
                ).length() if success else float("inf")
                if success and move_distance <= inside_query.diagonal * 0.08:
                    result[foot_name] = repaired

    # The shoulder and hand can sit at slightly different depths. Keep those
    # anatomical anchors and interpolate elbow/hand-tip depth between them.
    # Height remains free for the rotate-Y elbow prebend required by the
    # template basis (X along the arm, Y outward, Z vertical).
    for side in ("l", "r"):
        upper_name = "{0}_upperarm".format(side)
        lower_name = "{0}_lowerarm".format(side)
        hand_name = "{0}_hand".format(side)
        tip_name = "{0}_hand_tip".format(side)
        if not all(name in result for name in (upper_name, lower_name, hand_name)):
            continue
        logical_upper = frame.world_to_logical(result[upper_name])
        logical_hand = frame.world_to_logical(result[hand_name])
        side_delta = logical_hand[0] - logical_upper[0]
        if abs(side_delta) <= 1.0e-8:
            continue

        for name in (lower_name, tip_name):
            if name not in result:
                continue
            logical_point = list(frame.world_to_logical(result[name]))
            ratio = (logical_point[0] - logical_upper[0]) / side_delta
            logical_point[2] = logical_upper[2] + (
                (logical_hand[2] - logical_upper[2]) * ratio
            )
            candidate = frame.logical_to_world(tuple(logical_point))
            if inside_query is None or inside_query.point_inside(candidate):
                result[name] = candidate
                continue
            depth_axis_name = frame.world_axis("y")
            repaired, _clearance, success = inside_query.recenter_axis(
                candidate,
                depth_axis_name,
            )
            if success and inside_query.point_inside(repaired):
                result[name] = repaired

    for start_name, bend_name, end_name, parameter_axis, bend_axis, default_direction in (
        # Template arms use local Y as the outward hinge axis, so their
        # prebend belongs on logical up/down (local Z), never depth.
        ("l_upperarm", "l_lowerarm", "l_hand", frame.side_axis, frame.up_axis, -frame.up_sign),
        ("r_upperarm", "r_lowerarm", "r_hand", frame.side_axis, frame.up_axis, -frame.up_sign),
        ("l_thigh", "l_knee", "l_ankle", frame.up_axis, frame.depth_axis, frame.depth_sign),
        ("r_thigh", "r_knee", "r_ankle", frame.up_axis, frame.depth_axis, frame.depth_sign),
    ):
        if not all(name in result for name in (start_name, bend_name, end_name)):
            continue
        start = result[start_name]
        bend = list(result[bend_name])
        end = result[end_name]
        straight_value = _line_value_at(start, end, tuple(bend), parameter_axis, bend_axis)
        residual = bend[bend_axis] - straight_value
        if abs(residual) < minimum_bend:
            # A near-straight reference often carries floating-point residuals
            # whose sign is not an authored bend direction. Once the residual
            # is below the usable IK threshold, apply the anatomical policy
            # rather than amplifying that numerical noise into a full prebend.
            bend[bend_axis] = straight_value + (default_direction * minimum_bend)
            result[bend_name] = tuple(bend)

    return result


def refine_shoulder_landmarks(
    points: Dict[str, Vector3],
    query: "MeshInteriorQuery",
    frame: Optional[PlacementFrame] = None,
) -> Dict[str, Vector3]:
    """Move each arm root from the torso seed to the humeral-head section.

    A globally scaled template commonly leaves the upper-arm pivot inside the
    chest.  In a T/A pose, the torso-to-arm transition is measurable: the very
    tall torso section collapses into a compact, nearly round deltoid/humeral
    section.  Search only the proximal third of the upper arm and take the
    first local section matching that morphology.  This is a 3D volume test,
    not a front-view silhouette estimate.
    """
    result = dict(points)
    frame = frame or PlacementFrame()
    up_axis = frame.world_axis("y")
    depth_axis = frame.world_axis("z")
    up_component = query._AXES[up_axis][1]
    maximum_span = query.diagonal * 0.085

    for side in ("l", "r"):
        upper_name = "{0}_upperarm".format(side)
        elbow_name = "{0}_lowerarm".format(side)
        if upper_name not in result or elbow_name not in result:
            continue
        start = om.MVector(*result[upper_name])
        end = om.MVector(*result[elbow_name])
        segment = end - start
        if segment.length() <= 1.0e-8:
            continue

        chosen = None
        fallback_sections = []
        for step in range(36):
            amount = step * 0.01
            sample = start + (segment * amount)
            candidate = (sample.x, sample.y, sample.z)
            for _pass in range(2):
                candidate, _clearance, up_ok = query.recenter_axis(candidate, up_axis)
                candidate, _clearance, depth_ok = query.recenter_axis(candidate, depth_axis)
            if not (up_ok and depth_ok and query.point_inside(candidate)):
                continue
            up_interval = _choose_interval(
                query.axis_intervals(candidate, up_axis),
                candidate[query._AXES[up_axis][1]],
            )
            depth_interval = _choose_interval(
                query.axis_intervals(candidate, depth_axis),
                candidate[query._AXES[depth_axis][1]],
            )
            if not up_interval or not depth_interval:
                continue
            up_span = up_interval[1] - up_interval[0]
            depth_span = depth_interval[1] - depth_interval[0]
            largest = max(up_span, depth_span)
            smallest = min(up_span, depth_span)
            roundness = smallest / max(largest, 1.0e-8)
            chosen_values = list(candidate)
            chosen_values[up_component] = start[up_component]
            chosen_candidate = tuple(chosen_values)
            if amount >= 0.06 and query.point_inside(chosen_candidate):
                compactness = largest / max(roundness, 0.20)
                fallback_sections.append((compactness, amount, chosen_candidate))
            if largest <= maximum_span and roundness >= 0.82:
                # Section centroids drift down into the armpit because the
                # torso and deltoid are still connected here.  The authored
                # shoulder height is a better humeral-head landmark; use the
                # volume scan only for lateral/depth placement.
                if query.point_inside(chosen_candidate):
                    chosen = chosen_candidate
                break
        if chosen is None and fallback_sections:
            # Some stylized deltoids never satisfy the strict absolute-size
            # gate. Still move out of the torso: choose the most compact,
            # round proximal section rather than retaining the armpit seed.
            chosen = min(
                fallback_sections,
                key=lambda item: (item[0] * (1.0 + item[1]), item[1]),
            )[2]
        if chosen is not None:
            result[upper_name] = chosen
    return result


def refine_leg_landmarks(
    points: Dict[str, Vector3],
    query: "MeshInteriorQuery",
    frame: Optional[PlacementFrame] = None,
) -> Dict[str, Vector3]:
    """Solve hip height, knee line, and ankle line from limb morphology.

    Template ratios put the sample character's knees too high and its ankles
    down in the foot.  The knee is the compact section between the thigh and
    calf, while the ankle is the narrow section above the foot flare.  Search
    bounded height bands so a ray cannot jump into the pelvis or foot.
    """
    result = dict(points)
    frame = frame or PlacementFrame()
    logical_bounds = _logical_mesh_bounds(query.mesh, frame)
    minimum_y = logical_bounds["min"].y
    height = logical_bounds["height"]
    side_axis = frame.world_axis("x")
    depth_axis = frame.world_axis("z")

    def _smallest_section(seed: Vector3, low_ratio: float, high_ratio: float):
        logical_seed = frame.world_to_logical(seed)
        best = None
        for step in range(33):
            ratio = low_ratio + ((high_ratio - low_ratio) * (step / 32.0))
            logical_sample = (logical_seed[0], minimum_y + (height * ratio), logical_seed[2])
            candidate = frame.logical_to_world(logical_sample)
            for _pass in range(2):
                candidate, _clearance, side_ok = query.recenter_axis(candidate, side_axis)
                candidate, _clearance, depth_ok = query.recenter_axis(candidate, depth_axis)
            if not (side_ok and depth_ok and query.point_inside(candidate)):
                continue
            side_component = query._AXES[side_axis][1]
            depth_component = query._AXES[depth_axis][1]
            side_interval = _choose_interval(
                query.axis_intervals(candidate, side_axis), candidate[side_component]
            )
            depth_interval = _choose_interval(
                query.axis_intervals(candidate, depth_axis), candidate[depth_component]
            )
            if not side_interval or not depth_interval:
                continue
            area = (
                (side_interval[1] - side_interval[0])
                * (depth_interval[1] - depth_interval[0])
            )
            if best is None or area < best[0]:
                best = (area, candidate)
        return best[1] if best else None

    for side in ("l", "r"):
        thigh_name = "{0}_thigh".format(side)
        knee_name = "{0}_knee".format(side)
        ankle_name = "{0}_ankle".format(side)
        if not all(name in result for name in (thigh_name, knee_name, ankle_name)):
            continue

        # The studio template expects both femoral roots to branch from the
        # pelvis line. Keep their anatomical height identical even for an
        # A-stance; lateral/depth placement still comes from each leg volume.
        if "pelvis" in result:
            logical_thigh = list(frame.world_to_logical(result[thigh_name]))
            logical_pelvis = frame.world_to_logical(result["pelvis"])
            logical_thigh[1] = logical_pelvis[1]
            thigh_candidate = frame.logical_to_world(tuple(logical_thigh))
            result[thigh_name] = thigh_candidate

        knee = _smallest_section(result[knee_name], 0.24, 0.36)
        ankle = _smallest_section(result[ankle_name], 0.055, 0.13)
        if knee is not None:
            result[knee_name] = knee
        if ankle is not None:
            result[ankle_name] = ankle
    return result


def refine_foot_landmarks(
    points: Dict[str, Vector3],
    query: "MeshInteriorQuery",
    frame: Optional[PlacementFrame] = None,
) -> Dict[str, Vector3]:
    """Place toe base and tip in the local foot volume after ankle solving."""
    result = dict(points)
    frame = frame or PlacementFrame()
    logical_bounds = _logical_mesh_bounds(query.mesh, frame)
    height = logical_bounds["height"]
    up_axis = frame.world_axis("y")
    depth_axis = frame.world_axis("z")
    up_component = query._AXES[up_axis][1]
    depth_component = query._AXES[depth_axis][1]
    inset = max(query.diagonal * 0.0015, query.tolerance * 20.0)

    for side in ("l", "r"):
        ankle_name = "{0}_ankle".format(side)
        toe_name = "{0}_toe".format(side)
        tip_name = "{0}_toeTip".format(side)
        if not all(name in result for name in (ankle_name, toe_name, tip_name)):
            continue
        logical_ankle = frame.world_to_logical(result[ankle_name])
        logical_toe = frame.world_to_logical(result[toe_name])
        probe_y = logical_bounds["min"].y + (
            (logical_ankle[1] - logical_bounds["min"].y) * 0.18
        )
        probe = frame.logical_to_world(
            (logical_ankle[0], probe_y, logical_ankle[2])
        )
        intervals = query.axis_intervals(probe, depth_axis)
        ankle_world_depth = result[ankle_name][depth_component]
        interval = _choose_interval(intervals, ankle_world_depth)
        if not interval:
            continue
        # The authored corpus may use the opposite forward axis. The toe side
        # is the end of the local foot interval extending furthest from the
        # ankle, independent of source convention.
        low_distance = abs(interval[0] - ankle_world_depth)
        high_distance = abs(interval[1] - ankle_world_depth)
        forward_sign = 1.0 if high_distance >= low_distance else -1.0
        back = interval[0] if forward_sign > 0.0 else interval[1]
        front = interval[1] if forward_sign > 0.0 else interval[0]
        toe_depth = back + ((front - back) * 0.72)
        tip_depth = front - (forward_sign * inset)

        for name, depth_value in ((toe_name, toe_depth), (tip_name, tip_depth)):
            proposal = list(probe)
            proposal[depth_component] = depth_value
            up_intervals = query.axis_intervals(tuple(proposal), up_axis)
            local_intervals = [
                interval for interval in up_intervals
                if interval[0] - query.tolerance <= proposal[up_component] <= interval[1] + query.tolerance
                and (interval[1] - interval[0]) <= height * 0.14
            ]
            if not local_intervals:
                continue
            local_interval = min(
                local_intervals, key=lambda value: value[1] - value[0]
            )
            target_values = list(proposal)
            target_values[up_component] = (local_interval[0] + local_interval[1]) * 0.5
            target = tuple(target_values)
            if query.point_inside(target):
                result[name] = target
    return result


def _sanitize_studio_template_core_points(
    points: Dict[str, Vector3],
) -> Dict[str, Vector3]:
    """Repair known-invalid bind-pose landmarks without editing the source rig.

    The current studio template contains a right-hand-tip bind matrix copied
    from the left side and an effectively coincident chest-tip/neck pair. These
    values corrupt the normalization frame and create a singular spine segment.
    Use bilateral symmetry only when a point is demonstrably on the wrong side,
    then enforce a small scale-relative neck gap.
    """
    result = dict(points)
    center_names = (
        "origin", "pelvis", "spine_01", "spine_02", "spine_03",
        "spine_04", "neck", "head", "head_tip",
    )
    center_values = [result[name][0] for name in center_names if name in result]
    center_x = sum(center_values) / float(len(center_values) or 1)
    bilateral_suffixes = ("clavicle", "upperarm", "lowerarm", "hand", "hand_tip")
    for suffix in bilateral_suffixes:
        left_name = "l_{0}".format(suffix)
        right_name = "r_{0}".format(suffix)
        left = result.get(left_name)
        right = result.get(right_name)
        if left and left[0] <= center_x and right and right[0] < center_x:
            result[left_name] = (center_x + abs(right[0] - center_x), right[1], right[2])
        if right and right[0] >= center_x and left and left[0] > center_x:
            result[right_name] = (center_x - abs(left[0] - center_x), left[1], left[2])

    if "spine_04" in result and "neck" in result:
        y_values = [point[1] for point in result.values()]
        authored_height = max(y_values) - min(y_values)
        minimum_gap = max(authored_height * 0.01, 1.0e-4)
        spine = list(result["spine_04"])
        neck = result["neck"]
        if neck[1] - spine[1] < minimum_gap:
            spine[1] = neck[1] - minimum_gap
            result["spine_04"] = tuple(spine)
    return result


def measure_planar_deviation(
    points: Dict[str, Vector3],
    frame: Optional[PlacementFrame] = None,
) -> Dict[str, float]:
    frame = frame or PlacementFrame()
    if frame != PlacementFrame():
        logical_points = {name: frame.world_to_logical(point) for name, point in points.items()}
        return measure_planar_deviation(logical_points)
    deviations = {}
    chains = {
        "l_arm": ["l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip"],
        "r_arm": ["r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip"],
        "l_leg": ["l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip"],
        "r_leg": ["r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip"],
        "spine": ["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"],
    }
    for label, chain in chains.items():
        if label.endswith("arm"):
            chain_points = [points[name] for name in chain if name in points]
            if len(chain_points) < 2:
                deviations[label] = 0.0
                continue
            start = chain_points[0]
            end = chain_points[-1]
            side_delta = end[0] - start[0]
            if abs(side_delta) <= 1.0e-8:
                deviations[label] = 0.0
                continue
            deviations[label] = max(
                abs(
                    point[1]
                    - (
                        start[1]
                        + ((end[1] - start[1]) * ((point[0] - start[0]) / side_delta))
                    )
                )
                for point in chain_points
            )
            continue
        fixed_axis = 0
        values = [points[name][fixed_axis] for name in chain if name in points]
        if not values:
            deviations[label] = 0.0
            continue
        plane_value = sum(values) / float(len(values))
        deviations[label] = max(abs(value - plane_value) for value in values)
    return deviations


def _as_mesh_transform(node: str) -> str:
    """Return a mesh transform from a selected transform or mesh shape."""
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


def get_mesh_bounds(mesh: str) -> Dict[str, object]:
    mesh = _as_mesh_transform(mesh)
    bbox = cmds.exactWorldBoundingBox(mesh)
    min_v = om.MVector(bbox[0], bbox[1], bbox[2])
    max_v = om.MVector(bbox[3], bbox[4], bbox[5])
    center = (min_v + max_v) * 0.5

    return {
        "mesh": mesh,
        "min": min_v,
        "max": max_v,
        "center": center,
        "width": max_v.x - min_v.x,
        "height": max_v.y - min_v.y,
        "depth": max_v.z - min_v.z,
    }


def _mesh_dag_path(mesh: str) -> om.MDagPath:
    mesh = _as_mesh_transform(mesh)
    selection = om.MSelectionList()
    selection.add(mesh)
    dag_path = selection.getDagPath(0)
    if dag_path.apiType() != om.MFn.kMesh:
        dag_path.extendToShape()
    return dag_path


def analyze_mesh_for_joint_placement(mesh: str) -> MeshPlacementReport:
    """Return topology facts that determine how trustworthy volume tests are."""
    mesh = _as_mesh_transform(mesh)
    dag_path = _mesh_dag_path(mesh)
    mesh_fn = om.MFnMesh(dag_path)
    boundary_edges = 0
    edge_it = om.MItMeshEdge(dag_path)
    while not edge_it.isDone():
        if edge_it.onBoundary():
            boundary_edges += 1
        edge_it.next()

    non_manifold = cmds.polyInfo(mesh, nonManifoldEdges=True) or []
    lamina = cmds.polyInfo(mesh, laminaFaces=True) or []
    try:
        shell_count = int(cmds.polyEvaluate(mesh, shell=True) or 0)
    except Exception:
        shell_count = 0

    return MeshPlacementReport(
        mesh=mesh,
        vertex_count=int(mesh_fn.numVertices),
        face_count=int(mesh_fn.numPolygons),
        shell_count=shell_count,
        boundary_edge_count=boundary_edges,
        non_manifold_edge_count=len(non_manifold),
        lamina_face_count=len(lamina),
    )


def _deduplicate_sorted(values: Iterable[float], tolerance: float) -> List[float]:
    result = []
    for value in sorted(float(item) for item in values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def _pair_intersection_intervals(values: Iterable[float], tolerance: float) -> List[Tuple[float, float]]:
    """Pair ordered surface crossings into solid intervals for a closed mesh."""
    crossings = _deduplicate_sorted(values, tolerance)
    return [
        (crossings[index], crossings[index + 1])
        for index in range(0, len(crossings) - 1, 2)
        if crossings[index + 1] - crossings[index] > tolerance
    ]


def _choose_interval(
    intervals: Iterable[Tuple[float, float]],
    preferred_value: float,
) -> Optional[Tuple[float, float]]:
    intervals = list(intervals)
    if not intervals:
        return None
    containing = [item for item in intervals if item[0] <= preferred_value <= item[1]]
    choices = containing or intervals
    return min(choices, key=lambda item: abs(((item[0] + item[1]) * 0.5) - preferred_value))


def _recenter_along_direction(
    query: "MeshInteriorQuery",
    point: Vector3,
    direction: om.MVector,
) -> Tuple[Vector3, float, bool]:
    """Center a point through the mesh along an arbitrary world direction."""
    axis = om.MVector(direction)
    if axis.length() <= 1.0e-8:
        return point, 0.0, False
    axis.normalize()
    center = om.MVector(*point)
    source = center - (axis * query.diagonal)
    hits = query._ray_hits(
        (source.x, source.y, source.z),
        om.MFloatVector(axis.x, axis.y, axis.z),
        query.diagonal * 2.0,
    )
    distances = [
        (om.MVector(hit.x, hit.y, hit.z) - source) * axis
        for hit in hits
    ]
    interval = _choose_interval(
        _pair_intersection_intervals(distances, query.tolerance),
        query.diagonal,
    )
    if interval is None:
        return point, 0.0, False
    midpoint = (interval[0] + interval[1]) * 0.5
    target = source + (axis * midpoint)
    return (
        (target.x, target.y, target.z),
        (interval[1] - interval[0]) * 0.5,
        True,
    )


def _place_along_direction_fraction(
    query: "MeshInteriorQuery",
    point: Vector3,
    direction: om.MVector,
    fraction: float,
) -> Tuple[Vector3, float, bool]:
    """Place a point at a chosen fraction through an arbitrary mesh section."""
    axis = om.MVector(direction)
    if axis.length() <= 1.0e-8:
        return point, 0.0, False
    axis.normalize()
    center = om.MVector(*point)
    source = center - (axis * query.diagonal)
    hits = query._ray_hits(
        (source.x, source.y, source.z),
        om.MFloatVector(axis.x, axis.y, axis.z),
        query.diagonal * 2.0,
    )
    distances = [
        (om.MVector(hit.x, hit.y, hit.z) - source) * axis
        for hit in hits
    ]
    interval = _choose_interval(
        _pair_intersection_intervals(distances, query.tolerance),
        query.diagonal,
    )
    if interval is None:
        return point, 0.0, False
    fraction = max(0.0, min(float(fraction), 1.0))
    distance = interval[0] + ((interval[1] - interval[0]) * fraction)
    target = source + (axis * distance)
    clearance = min(distance - interval[0], interval[1] - distance)
    return (target.x, target.y, target.z), clearance, True


class MeshInteriorQuery:
    """Accelerated world-space cross-section and inside-volume queries."""

    _AXES = {
        "x": (om.MFloatVector(1.0, 0.0, 0.0), 0),
        "y": (om.MFloatVector(0.0, 1.0, 0.0), 1),
        "z": (om.MFloatVector(0.0, 0.0, 1.0), 2),
    }

    def __init__(self, mesh: str):
        self.mesh = _as_mesh_transform(mesh)
        self.bounds = get_mesh_bounds(self.mesh)
        self.dag_path = _mesh_dag_path(self.mesh)
        self.mesh_fn = om.MFnMesh(self.dag_path)
        self.acceleration = self.mesh_fn.autoUniformGridParams()
        self.diagonal = max(
            om.MVector(
                self.bounds["width"], self.bounds["height"], self.bounds["depth"]
            ).length(),
            0.001,
        )
        self.tolerance = max(self.diagonal * 1.0e-5, 1.0e-6)

    @staticmethod
    def _components(point: Vector3) -> List[float]:
        return [float(point[0]), float(point[1]), float(point[2])]

    def _ray_hits(
        self,
        source: Vector3,
        direction: om.MFloatVector,
        max_distance: float,
    ) -> List[om.MFloatPoint]:
        try:
            result = self.mesh_fn.allIntersections(
                om.MFloatPoint(*source),
                direction,
                om.MSpace.kWorld,
                float(max_distance),
                False,
                accelParams=self.acceleration,
                tolerance=1.0e-6,
                sortHits=True,
            )
            return list(result[0]) if result else []
        except RuntimeError:
            return []

    def axis_intervals(self, point: Vector3, axis: str) -> List[Tuple[float, float]]:
        direction, component = self._AXES[axis]
        minimum = self.bounds["min"][component]
        maximum = self.bounds["max"][component]
        margin = max((maximum - minimum) * 0.05, self.tolerance * 10.0)
        source = self._components(point)
        source[component] = minimum - margin
        hits = self._ray_hits(tuple(source), direction, (maximum - minimum) + (margin * 2.0))
        values = [float(hit[component]) for hit in hits]
        return _pair_intersection_intervals(values, self.tolerance)

    def point_inside(self, point: Vector3) -> bool:
        # Voting across three axes avoids a single ray grazing a vertex or edge.
        inside_votes = 0
        components = self._components(point)
        for axis, (direction, component) in self._AXES.items():
            maximum = self.bounds["max"][component]
            max_distance = max((maximum - components[component]) + self.diagonal * 0.05, self.tolerance)
            hits = self._ray_hits(point, direction, max_distance)
            distances = []
            for hit in hits:
                delta = om.MVector(
                    float(hit.x) - point[0],
                    float(hit.y) - point[1],
                    float(hit.z) - point[2],
                )
                distances.append(delta * om.MVector(direction))
            crossings = _deduplicate_sorted(
                [distance for distance in distances if distance > self.tolerance],
                self.tolerance,
            )
            if len(crossings) % 2 == 1:
                inside_votes += 1
        return inside_votes >= 2

    def recenter_axis(self, point: Vector3, axis: str) -> Tuple[Vector3, float, bool]:
        _direction, component = self._AXES[axis]
        values = self._components(point)
        interval = _choose_interval(self.axis_intervals(point, axis), values[component])
        if interval is None:
            return point, 0.0, False
        values[component] = (interval[0] + interval[1]) * 0.5
        clearance = (interval[1] - interval[0]) * 0.5
        return tuple(values), clearance, True

    def move_inside(self, point: Vector3) -> Tuple[Vector3, bool]:
        """Move an outside proposal just inside its closest local surface."""
        if self.point_inside(point):
            return point, True
        closest_result = self.mesh_fn.getClosestPointAndNormal(
            om.MPoint(*point), om.MSpace.kWorld
        )
        closest, normal = closest_result[0], closest_result[1]
        epsilon = max(self.diagonal * 0.002, self.tolerance * 20.0)
        closest_vector = om.MVector(closest.x, closest.y, closest.z)
        center = self.bounds["center"]
        directions = [
            -om.MVector(normal),
            om.MVector(normal),
            (center - closest_vector).normal(),
        ]
        for direction in directions:
            for multiplier in (1.0, 2.0, 4.0, 8.0):
                candidate = closest_vector + direction * epsilon * multiplier
                result = (candidate.x, candidate.y, candidate.z)
                if self.point_inside(result):
                    return result, True
        return point, False

    def move_inside_preserving_plane(
        self,
        point: Vector3,
        fixed_axis: str,
    ) -> Tuple[Vector3, bool]:
        """Move a point into the mesh without leaving its solved IK plane."""
        if self.point_inside(point):
            return point, True
        mutable_axes = [axis for axis in ("x", "y", "z") if axis != fixed_axis]
        inset = max(self.diagonal * 0.0005, self.tolerance * 10.0)
        for axis_order in (mutable_axes, list(reversed(mutable_axes))):
            candidate = tuple(point)
            for axis in axis_order:
                _direction, component = self._AXES[axis]
                values = self._components(candidate)
                interval = _choose_interval(
                    self.axis_intervals(candidate, axis),
                    values[component],
                )
                if interval is None:
                    continue
                lower = interval[0] + inset
                upper = interval[1] - inset
                if lower > upper:
                    lower, upper = interval
                values[component] = min(max(values[component], lower), upper)
                candidate = tuple(values)
                if self.point_inside(candidate):
                    return candidate, True
        return point, False


_MESH_INTERIOR_QUERY_CACHE: Dict[str, MeshInteriorQuery] = {}


def _cached_mesh_interior_query(mesh: str) -> MeshInteriorQuery:
    """Reuse acceleration structures throughout one placement run."""
    resolved = _as_mesh_transform(mesh)
    key = (cmds.ls(resolved, long=True) or [resolved])[0]
    query = _MESH_INTERIOR_QUERY_CACHE.get(key)
    if query is None:
        query = MeshInteriorQuery(resolved)
        _MESH_INTERIOR_QUERY_CACHE[key] = query
    return query


def clear_mesh_query_cache() -> None:
    """Release placement acceleration structures before a new mesh solve."""
    _MESH_INTERIOR_QUERY_CACHE.clear()

def point_from_normalized_bounds(bounds: Dict[str, object], xyz: Vector3) -> Vector3:
    x_norm, y_norm, z_norm = xyz
    min_v = bounds["min"]
    center = bounds["center"]

    x = center.x + (bounds["width"] * x_norm)
    y = min_v.y + (bounds["height"] * y_norm)
    z = center.z + (bounds["depth"] * z_norm)
    return (x, y, z)


def extract_studio_template_core_points(
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Dict[str, Vector3]:
    """Read authored bind-pose world positions directly from a Maya ASCII template."""
    source = Path(template_path).expanduser().resolve()
    if not source.exists():
        raise RuntimeError("Rig template does not exist: {0}".format(source))
    if source.suffix.lower() != ".ma":
        raise RuntimeError(
            "Placement extraction requires a Maya ASCII template with bind-pose matrices: {0}".format(source)
        )
    cache_key = (str(source).lower(), float(source.stat().st_mtime))
    cached = _TEMPLATE_POINT_CACHE.get(cache_key)
    if cached:
        return dict(cached)

    contents = source.read_text(encoding="utf-8", errors="replace")
    joint_blocks = {}
    block_pattern = re.compile(
        r'createNode\s+joint\s+-n\s+"([^"]+)"[^;]*;(.*?)(?=\ncreateNode\s|\Z)',
        re.DOTALL,
    )
    matrix_pattern = re.compile(
        r'setAttr\s+"\.bps"\s+-type\s+"matrix"\s+(.*?);',
        re.DOTALL,
    )
    translation_pattern = re.compile(
        r'setAttr\s+"\.t"\s+-type\s+"double3"\s+(.*?);',
        re.DOTALL,
    )
    number_pattern = re.compile(
        r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
    )
    for match in block_pattern.finditer(contents):
        joint_blocks[match.group(1)] = match.group(2)

    points = {}
    missing = []
    for canonical_name, template_name in TEMPLATE_CORE_JOINTS.items():
        block = joint_blocks.get(template_name, "")
        matrix_match = matrix_pattern.search(block)
        if not matrix_match:
            missing.append(template_name)
            continue
        values = [float(value) for value in number_pattern.findall(matrix_match.group(1))]
        if len(values) != 16:
            missing.append(template_name)
            continue
        points[canonical_name] = (values[12], values[13], values[14])
    if missing:
        raise RuntimeError(
            "Studio rig template is missing usable bind-pose matrices for: {0}".format(
                ", ".join(missing)
            )
        )
    points = _sanitize_studio_template_core_points(points)
    _TEMPLATE_POINT_CACHE.clear()
    _TEMPLATE_POINT_CACHE[cache_key] = dict(points)
    return points


def extract_studio_template_joint_axes(
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Dict[str, Dict[str, Vector3]]:
    """Read each joint's authored world-space XYZ basis from its bind matrix."""
    source = Path(template_path).expanduser().resolve()
    if not source.exists() or source.suffix.lower() != ".ma":
        raise RuntimeError(
            "Joint-axis extraction requires the Maya ASCII rig template: {0}".format(
                source
            )
        )
    cache_key = (str(source).lower(), float(source.stat().st_mtime))
    cached = _TEMPLATE_AXIS_CACHE.get(cache_key)
    if cached is not None:
        return {name: dict(axes) for name, axes in cached.items()}

    contents = source.read_text(encoding="utf-8", errors="replace")
    block_pattern = re.compile(
        r'createNode\s+joint\s+-n\s+"([^"]+)"[^;]*;(.*?)(?=\ncreateNode\s|\Z)',
        re.DOTALL,
    )
    matrix_pattern = re.compile(
        r'setAttr\s+"\.bps"\s+-type\s+"matrix"\s+(.*?);',
        re.DOTALL,
    )
    translation_pattern = re.compile(
        r'setAttr\s+"\.t"\s+-type\s+"double3"\s+(.*?);',
        re.DOTALL,
    )
    number_pattern = re.compile(
        r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
    )
    axes_by_name = {}
    for match in block_pattern.finditer(contents):
        matrix_match = matrix_pattern.search(match.group(2))
        if not matrix_match:
            continue
        values = [
            float(value) for value in number_pattern.findall(matrix_match.group(1))
        ]
        if len(values) != 16:
            continue
        axes = {
            "x": tuple(values[0:3]),
            "y": tuple(values[4:7]),
            "z": tuple(values[8:11]),
        }
        translation_match = translation_pattern.search(match.group(2))
        if translation_match:
            translation = [
                float(value)
                for value in number_pattern.findall(translation_match.group(1))
            ]
            if len(translation) == 3:
                axes["translate"] = tuple(translation)
        axes_by_name[match.group(1)] = axes
    if not axes_by_name:
        raise RuntimeError(
            "Rig template contains no usable bind-pose joint axes: {0}".format(
                source
            )
        )
    _TEMPLATE_AXIS_CACHE.clear()
    _TEMPLATE_AXIS_CACHE[cache_key] = axes_by_name
    return {name: dict(axes) for name, axes in axes_by_name.items()}


def solve_studio_template_points(
    mesh: str,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Tuple[Dict[str, Vector3], Dict[str, float]]:
    """Scale the authored studio skeleton into the target mesh as the proposal."""
    source_points = extract_studio_template_core_points(template_path)
    bounds = get_mesh_bounds(mesh)
    source_values = list(source_points.values())
    source_min_x = min(point[0] for point in source_values)
    source_max_x = max(point[0] for point in source_values)
    source_min_y = min(point[1] for point in source_values)
    source_max_y = max(point[1] for point in source_values)
    source_center_x = (source_min_x + source_max_x) * 0.5
    source_width = max(source_max_x - source_min_x, 1.0e-6)
    source_height = max(source_max_y - source_min_y, 1.0e-6)
    source_center_z_values = [
        source_points[name][2]
        for name in ("origin", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head")
        if name in source_points
    ]
    source_center_z = sum(source_center_z_values) / float(len(source_center_z_values))
    target_center = bounds["center"]
    target_min = bounds["min"]

    points = {}
    for name, point in source_points.items():
        x_normalized = (point[0] - source_center_x) / source_width
        y_normalized = (point[1] - source_min_y) / source_height
        points[name] = (
            target_center.x + x_normalized * bounds["width"],
            target_min.y + y_normalized * bounds["height"],
            target_center.z + ((point[2] - source_center_z) / source_height) * bounds["height"],
        )
    return points, {name: 0.72 for name in points}


def _load_reference_placement_corpus() -> List[Dict[str, object]]:
    module_root = Path(__file__).resolve().parent
    corpus_roots = (
        module_root / "joint_placement_regression_cases" / "baselines",
        module_root / "joint_placement_reference_atlas",
    )
    cache_key = "|".join(str(root) for root in corpus_roots)
    cached = _REFERENCE_CORPUS_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    inverse_template_names = {value: key for key, value in TEMPLATE_CORE_JOINTS.items()}
    entries = []
    for corpus_root in corpus_roots:
        if not corpus_root.exists():
            continue
        for source in sorted(corpus_root.glob("*.json")):
            if source.name == "manifest.json":
                continue
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
            except Exception:
                continue
            skeleton = data.get("skeleton") or {}
            detail_points = {
                name: tuple(float(value) for value in point)
                for name, point in (skeleton.get("points") or {}).items()
                if isinstance(point, (list, tuple)) and len(point) == 3
            }
            joint_axes = {}
            for name, axis_data in (skeleton.get("axes") or {}).items():
                if not isinstance(axis_data, dict):
                    continue
                parsed = {
                    axis: tuple(float(value) for value in vector)
                    for axis, vector in axis_data.items()
                    if axis in {"x", "y", "z"}
                    and isinstance(vector, (list, tuple))
                    and len(vector) == 3
                }
                if parsed:
                    joint_axes[name] = parsed
            normalized = dict(skeleton.get("anchors") or {})
            for template_name, canonical_name in inverse_template_names.items():
                if template_name in detail_points and canonical_name not in normalized:
                    normalized[canonical_name] = detail_points[template_name]
            for target_name, point in (skeleton.get("mapped_joints") or {}).items():
                canonical_name = inverse_template_names.get(target_name)
                if canonical_name and canonical_name not in normalized:
                    normalized[canonical_name] = point
            normalized = {
                name: tuple(float(value) for value in point)
                for name, point in normalized.items()
                if name in BUILD_ORDER and isinstance(point, (list, tuple)) and len(point) == 3
            }
            # Approved files can predate template-data repairs.  Apply the
            # same deterministic sanitation used by the live template so a
            # malformed zero-length landmark is never reintroduced as a
            # corpus seed.
            normalized = _sanitize_studio_template_core_points(normalized)
            if len(normalized) < 15:
                continue
            mesh_data = data.get("mesh") or {}
            topology = data.get("topology") or {}
            entries.append({
                "case_id": data.get("case_id") or source.stem,
                "width_over_height": float(mesh_data.get("width_over_height") or 0.0),
                "depth_over_height": float(mesh_data.get("depth_over_height") or 0.0),
                "vertex_count": int(mesh_data.get("vertex_count") or 0),
                "points": normalized,
                "detail_points": detail_points,
                "joint_axes": joint_axes,
                "topology": topology,
            })
    _REFERENCE_CORPUS_CACHE[cache_key] = list(entries)
    return entries


def _reference_shape_distance(
    entry: Dict[str, object],
    width_ratio: float,
    depth_ratio: float,
    vertex_count: int,
) -> float:
    shape_distance = abs(float(entry["width_over_height"]) - width_ratio)
    shape_distance += abs(float(entry["depth_over_height"]) - depth_ratio) * 1.5
    if vertex_count and entry["vertex_count"]:
        shape_distance += abs(
            math.log(float(vertex_count) / float(entry["vertex_count"]))
        ) * 0.01
    return shape_distance


def _rank_reference_entries(
    mesh: str,
    require_detail: bool = False,
) -> List[Tuple[float, Dict[str, object]]]:
    bounds = get_mesh_bounds(mesh)
    height = max(bounds["height"], 1.0e-6)
    width_ratio = bounds["width"] / height
    depth_ratio = bounds["depth"] / height
    vertex_count = int(cmds.polyEvaluate(_as_mesh_transform(mesh), vertex=True) or 0)
    entries = [
        entry for entry in _load_reference_placement_corpus()
        if not require_detail or entry.get("detail_points")
    ]
    return sorted(
        (
            (
                _reference_shape_distance(
                    entry, width_ratio, depth_ratio, vertex_count
                ),
                entry,
            )
            for entry in entries
        ),
        key=lambda item: (item[0], str(item[1].get("case_id") or "")),
    )


def _solve_linear_system_4x4(matrix, vector) -> Optional[List[float]]:
    augmented = [
        [float(value) for value in row] + [float(vector[index])]
        for index, row in enumerate(matrix)
    ]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1.0e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(4):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(5)
            ]
    return [augmented[index][4] for index in range(4)]


def _affine_transfer_point(
    source_points: List[Vector3],
    target_points: List[Vector3],
    source_point: Vector3,
) -> Optional[Vector3]:
    if len(source_points) != len(target_points) or len(source_points) < 4:
        return None
    normal = [[0.0] * 4 for _index in range(4)]
    right = [[0.0] * 4 for _axis in range(3)]
    for source, target in zip(source_points, target_points):
        row = (source[0], source[1], source[2], 1.0)
        for i in range(4):
            for j in range(4):
                normal[i][j] += row[i] * row[j]
            for axis in range(3):
                right[axis][i] += row[i] * target[axis]
    for index in range(3):
        normal[index][index] += 1.0e-9
    coefficients = [
        _solve_linear_system_4x4(normal, right[axis]) for axis in range(3)
    ]
    if any(values is None for values in coefficients):
        return None
    row = (source_point[0], source_point[1], source_point[2], 1.0)
    return tuple(
        sum(coefficients[axis][index] * row[index] for index in range(4))
        for axis in range(3)
    )


def solve_topology_reference_points(
    mesh: str,
) -> Tuple[Dict[str, Vector3], List[str]]:
    """Transfer an approved skeleton through identical production topology."""
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    ranked = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
    ]
    if not ranked:
        return {}, []
    # Whole-body anchors use the closest proportional reference. Hand roots,
    # metacarpals, MCPs, and thumb joints use a robust consensus of the five
    # closest approved rigs because small authoring differences are highly
    # visible in these compact chains.
    selected = ranked[:5]
    required_ids = sorted({
        int(index)
        for _distance, reference in selected
        for indices in ((reference.get("topology") or {}).get("joint_vertices") or {}).values()
        for index in indices
        if str(index) in ((reference.get("topology") or {}).get("vertices") or {})
    })
    if not required_ids:
        return {}, []
    shape = (
        cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True)
        or [None]
    )[0]
    if not shape:
        return {}, []
    selection = om.MSelectionList()
    selection.add(shape)
    dag_path = selection.getDagPath(0)
    target_mesh_points = om.MFnMesh(dag_path).getPoints(om.MSpace.kWorld)
    bounds = get_mesh_bounds(mesh)
    mesh_height = max(float(bounds["height"]), 1.0e-8)
    normalized_origin = (
        float(bounds["center"].x),
        float(bounds["min"].y),
        float(bounds["center"].z),
    )
    interior_query = None
    target_vertices = {
        index: (
            float(target_mesh_points[index].x),
            float(target_mesh_points[index].y),
            float(target_mesh_points[index].z),
        )
        for index in required_ids
    }
    transferred_sets = []
    for _distance, reference in selected:
        topology = reference.get("topology") or {}
        source_vertices = topology.get("vertices") or {}
        joint_vertices = topology.get("joint_vertices") or {}
        transferred_points = {}
        for name, source_joint in reference.get("detail_points", {}).items():
            # Older approved captures called the first cervical joint "neck";
            # newer templates call the same anatomical pivot "neck1". Keep
            # that reference usable instead of letting the generic fit snap
            # neck1 down onto spine5_Tip.
            target_name = "neck1" if name == "neck" else name
            if name in INTERNAL_HEAD_REFERENCE_JOINTS:
                # These pivots live inside the skull/oral cavity. A local
                # surface-affine extrapolation is ill-conditioned there and
                # can move a jaw hinge by several units even for identical
                # topology. For these internal anchors, transfer the approved
                # height-normalized placement into this mesh's bounds; this is
                # exact for the reference mesh and scales cleanly for matching
                # production topology. Keep the local affine result as a
                # fallback when the normalized candidate is outside the body.
                normalized_target = tuple(
                    normalized_origin[axis]
                    + (float(source_joint[axis]) * mesh_height)
                    for axis in range(3)
                )
                if interior_query is None:
                    interior_query = _cached_mesh_interior_query(mesh)
                if interior_query.point_inside(normalized_target):
                    transferred_points[target_name] = normalized_target
                    continue
            indices = [
                int(index) for index in joint_vertices.get(name, [])
                if str(index) in source_vertices and int(index) in target_vertices
            ]
            source_samples = [
                tuple(float(value) for value in source_vertices[str(index)])
                for index in indices
            ]
            target_samples = [target_vertices[index] for index in indices]
            transferred = _affine_transfer_point(
                source_samples,
                target_samples,
                tuple(float(value) for value in source_joint),
            )
            if transferred is not None:
                transferred_points[target_name] = transferred
        transferred_sets.append(transferred_points)

    result = dict(transferred_sets[0])
    consensus_pattern = re.compile(
        r"^(?:l|r)_(?:thumb_\d+|(?:index|middle|ring|pinky)_(?:01|02))$",
        re.IGNORECASE,
    )

    def _median(values):
        ordered = sorted(float(value) for value in values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) * 0.5

    consensus_names = sorted({
        name
        for points in transferred_sets
        for name in points
        if consensus_pattern.match(name)
    })
    for name in consensus_names:
        samples = [points[name] for points in transferred_sets if name in points]
        if len(samples) >= 3:
            result[name] = tuple(
                _median(sample[axis] for sample in samples)
                for axis in range(3)
            )
    return result, [str(reference["case_id"]) for _distance, reference in selected]


def solve_reference_thumb_dorsal_vectors(mesh: str) -> Dict[str, Vector3]:
    """Transfer approved thumb roll vectors through matching mesh topology."""
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    selected = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
        and entry.get("joint_axes")
    ][:5]
    if not selected:
        return {}

    names = (
        "l_thumb_01", "l_thumb_02", "l_thumb_03",
        "r_thumb_01", "r_thumb_02", "r_thumb_03",
    )
    required_ids = sorted({
        int(index)
        for _distance, reference in selected
        for name in names
        for index in ((reference.get("topology") or {}).get("joint_vertices") or {}).get(name, [])
        if str(index) in ((reference.get("topology") or {}).get("vertices") or {})
    })
    if not required_ids:
        return {}
    shape = (
        cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True)
        or [None]
    )[0]
    if not shape:
        return {}
    selection = om.MSelectionList()
    selection.add(shape)
    target_points = om.MFnMesh(selection.getDagPath(0)).getPoints(om.MSpace.kWorld)
    target_vertices = {
        index: (
            float(target_points[index].x),
            float(target_points[index].y),
            float(target_points[index].z),
        )
        for index in required_ids
    }

    samples_by_name = {name: [] for name in names}
    for _distance, reference in selected:
        topology = reference.get("topology") or {}
        source_vertices = topology.get("vertices") or {}
        joint_vertices = topology.get("joint_vertices") or {}
        joint_axes = reference.get("joint_axes") or {}
        joint_points = reference.get("detail_points") or {}
        for name in names:
            source_joint = joint_points.get(name)
            source_up = (joint_axes.get(name) or {}).get("y")
            if source_joint is None or source_up is None:
                continue
            indices = [
                int(index) for index in joint_vertices.get(name, [])
                if str(index) in source_vertices and int(index) in target_vertices
            ]
            source_samples = [
                tuple(float(value) for value in source_vertices[str(index)])
                for index in indices
            ]
            target_samples = [target_vertices[index] for index in indices]
            source_origin = tuple(float(value) for value in source_joint)
            source_tip = tuple(
                source_origin[axis] + float(source_up[axis]) * 0.02
                for axis in range(3)
            )
            target_origin = _affine_transfer_point(
                source_samples, target_samples, source_origin
            )
            target_tip = _affine_transfer_point(
                source_samples, target_samples, source_tip
            )
            if target_origin is None or target_tip is None:
                continue
            vector = om.MVector(*target_tip) - om.MVector(*target_origin)
            if vector.length() <= 1.0e-8:
                continue
            vector.normalize()
            if vector * om.MVector(0.0, 1.0, 0.0) < 0.0:
                vector *= -1.0
            samples_by_name[name].append(vector)

    result = {}
    for name, samples in samples_by_name.items():
        if not samples:
            continue
        vector = om.MVector()
        for sample in samples:
            vector += sample
        if vector.length() <= 1.0e-8:
            continue
        vector.normalize()
        result[name] = (vector.x, vector.y, vector.z)
    return result


def solve_reference_thumb_knuckle_z_vectors(mesh: str) -> Dict[str, Vector3]:
    """Transfer the approved local-Z thumb direction through mesh topology.

    A shortest-arc bone aim preserves the reference roll approximately, but it
    cannot account for character-specific deformation around the thumb mound.
    Exact-topology affine transfer makes local Z follow the visible knuckle
    surface while leaving the joint positions and local-X aims authoritative.
    """
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    selected = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0)
        == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0)
        == face_count
        and entry.get("joint_axes")
    ][:5]
    if not selected:
        return {}

    names = (
        "l_thumb_01", "l_thumb_02", "l_thumb_03",
        "r_thumb_01", "r_thumb_02", "r_thumb_03",
    )
    required_ids = sorted({
        int(index)
        for _distance, reference in selected
        for name in names
        for index in (
            (reference.get("topology") or {}).get("joint_vertices") or {}
        ).get(name, [])
        if str(index) in (
            (reference.get("topology") or {}).get("vertices") or {}
        )
    })
    if not required_ids:
        return {}
    target_mesh_points = om.MFnMesh(_mesh_dag_path(mesh)).getPoints(
        om.MSpace.kWorld
    )
    target_vertices = {
        index: (
            float(target_mesh_points[index].x),
            float(target_mesh_points[index].y),
            float(target_mesh_points[index].z),
        )
        for index in required_ids
    }

    samples_by_name = {name: [] for name in names}
    for _distance, reference in selected:
        topology = reference.get("topology") or {}
        source_vertices = topology.get("vertices") or {}
        joint_vertices = topology.get("joint_vertices") or {}
        joint_axes = reference.get("joint_axes") or {}
        joint_points = reference.get("detail_points") or {}
        for name in names:
            source_joint = joint_points.get(name)
            source_z = (joint_axes.get(name) or {}).get("z")
            if source_joint is None or source_z is None:
                continue
            indices = [
                int(index) for index in joint_vertices.get(name, [])
                if str(index) in source_vertices
                and int(index) in target_vertices
            ]
            source_samples = [
                tuple(float(value) for value in source_vertices[str(index)])
                for index in indices
            ]
            target_samples = [target_vertices[index] for index in indices]
            source_origin = tuple(float(value) for value in source_joint)
            source_tip = tuple(
                source_origin[axis] + float(source_z[axis]) * 0.02
                for axis in range(3)
            )
            target_origin = _affine_transfer_point(
                source_samples, target_samples, source_origin
            )
            target_tip = _affine_transfer_point(
                source_samples, target_samples, source_tip
            )
            if target_origin is None or target_tip is None:
                continue
            vector = om.MVector(*target_tip) - om.MVector(*target_origin)
            if vector.length() <= 1.0e-8:
                continue
            vector.normalize()
            samples_by_name[name].append(vector)

    result = {}
    for name, samples in samples_by_name.items():
        if not samples:
            continue
        canonical = om.MVector(samples[0])
        vector = om.MVector()
        for sample in samples:
            sample = om.MVector(sample)
            if sample * canonical < 0.0:
                sample *= -1.0
            vector += sample
        if vector.length() <= 1.0e-8:
            continue
        vector.normalize()
        result[name] = (vector.x, vector.y, vector.z)
    return result


def solve_reference_eyelid_tip_points(mesh: str) -> Dict[str, Vector3]:
    """Transfer eyelid tips by weighted exact-topology vertex correspondence.

    Eyelid surface patches are nearly planar, so a free affine fit can produce
    a valid mathematical transform with a wildly incorrect ray direction.
    Inverse-distance interpolation of the authored neighboring vertices keeps
    every result on the corresponding eyelid loop.
    """
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    selected = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
    ][:5]
    if not selected:
        return {}
    pattern = re.compile(
        r"^(?:l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$",
        re.IGNORECASE,
    )
    names = sorted({
        name
        for _distance, entry in selected
        for name in (entry.get("detail_points") or {})
        if pattern.match(name)
    })
    required_ids = sorted({
        int(index)
        for _distance, entry in selected
        for name in names
        for index in ((entry.get("topology") or {}).get("joint_vertices") or {}).get(name, [])
        if str(index) in ((entry.get("topology") or {}).get("vertices") or {})
    })
    if not required_ids:
        return {}
    target_mesh_points = om.MFnMesh(_mesh_dag_path(mesh)).getPoints(om.MSpace.kWorld)
    target_vertices = {
        index: om.MVector(target_mesh_points[index])
        for index in required_ids
    }
    samples_by_name = {name: [] for name in names}
    for _distance, entry in selected:
        topology = entry.get("topology") or {}
        source_vertices = topology.get("vertices") or {}
        joint_vertices = topology.get("joint_vertices") or {}
        detail_points = entry.get("detail_points") or {}
        for name in names:
            source_joint = detail_points.get(name)
            if source_joint is None:
                continue
            source_joint_vector = om.MVector(*source_joint)
            candidates = []
            for raw_index in joint_vertices.get(name, []):
                index = int(raw_index)
                source_vertex = source_vertices.get(str(index))
                if source_vertex is None or index not in target_vertices:
                    continue
                distance = (om.MVector(*source_vertex) - source_joint_vector).length()
                candidates.append((distance, index))
            candidates.sort(key=lambda item: item[0])
            nearest = candidates[:8]
            if not nearest:
                continue
            weights = [1.0 / max(distance, 1.0e-6) ** 4 for distance, _index in nearest]
            total_weight = sum(weights)
            point = om.MVector()
            for weight, (_distance_value, index) in zip(weights, nearest):
                point += target_vertices[index] * (weight / total_weight)
            samples_by_name[name].append((point.x, point.y, point.z))

    def _median(values):
        ordered = sorted(float(value) for value in values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) * 0.5

    return {
        name: tuple(_median(sample[axis] for sample in samples) for axis in range(3))
        for name, samples in samples_by_name.items()
        if samples
    }


def solve_reference_eye_centers(
    mesh: str,
    eyelid_tip_points: Optional[Dict[str, Vector3]] = None,
) -> Dict[str, Vector3]:
    """Infer eye pivots from the eyelid ring when no eyeball mesh exists.

    The approved rigs encode a stable relationship between each eye pivot and
    its visible eyelid loop. Reconstructing that relationship in lid-local
    units is more reliable than transferring an invisible interior landmark
    directly, especially on characters whose scene has no separate eye mesh.
    """
    mesh = _as_mesh_transform(mesh)
    mapped_tips = eyelid_tip_points or solve_reference_eyelid_tip_points(mesh)
    if not mapped_tips:
        return {}
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    selected = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
    ][:5]
    if not selected:
        return {}

    def _ring_feature(points: List[Vector3]) -> Tuple[om.MVector, float]:
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        zs = sorted(float(point[2]) for point in points)
        middle = len(zs) // 2
        median_z = zs[middle] if len(zs) % 2 else (zs[middle - 1] + zs[middle]) * 0.5
        center = om.MVector(
            (min(xs) + max(xs)) * 0.5,
            (min(ys) + max(ys)) * 0.5,
            median_z,
        )
        # Use the mean visible diameter so an unusually wide or tall stylized
        # lid cannot dominate the inferred depth offset.
        span = max(((max(xs) - min(xs)) + (max(ys) - min(ys))) * 0.5, 1.0e-8)
        return center, span

    result = {}
    for side in ("l", "r"):
        pattern = re.compile(
            r"^%s_(?:inner|outer|upper|lower)_eyelidTip\d*$" % side,
            re.IGNORECASE,
        )
        names = sorted(name for name in mapped_tips if pattern.match(name))
        if len(names) < 4:
            continue
        target_center, target_span = _ring_feature([mapped_tips[name] for name in names])
        relation_sum = om.MVector()
        total_weight = 0.0
        eye_name = side + "_eye"
        for distance, entry in selected:
            detail_points = entry.get("detail_points") or {}
            source_eye = detail_points.get(eye_name)
            source_ring = [detail_points[name] for name in names if name in detail_points]
            if source_eye is None or len(source_ring) < 4:
                continue
            source_center, source_span = _ring_feature(source_ring)
            relation = (om.MVector(*source_eye) - source_center) / source_span
            weight = 1.0 / max(float(distance), 0.002) ** 2
            relation_sum += relation * weight
            total_weight += weight
        if total_weight <= 0.0:
            continue
        relation = relation_sum / total_weight
        result[eye_name] = (
            target_center.x,
            target_center.y,
            target_center.z + (relation.z * target_span),
        )
    if "l_eye" in result and "r_eye" in result:
        body_center_x = get_mesh_bounds(mesh)["center"].x
        left = result["l_eye"]
        right = result["r_eye"]
        half_span = (
            abs(left[0] - body_center_x) + abs(right[0] - body_center_x)
        ) * 0.5
        shared_y = (left[1] + right[1]) * 0.5
        shared_z = (left[2] + right[2]) * 0.5
        result["l_eye"] = (body_center_x + half_span, shared_y, shared_z)
        result["r_eye"] = (body_center_x - half_span, shared_y, shared_z)
    return result


def _scene_mesh_vertices(meshes: Iterable[str]) -> List[om.MPoint]:
    """Return world-space vertices for non-intermediate scene meshes."""
    result = []
    for mesh in meshes:
        try:
            dag_path = _mesh_dag_path(mesh)
        except (RuntimeError, ValueError):
            continue
        result.extend(
            om.MPoint(point)
            for point in om.MFnMesh(dag_path).getPoints(om.MSpace.kWorld)
        )
    return result


def _scene_feature_meshes(
    include_tokens: Iterable[str],
    exclude_tokens: Iterable[str] = (),
    anchor_mesh: str = "",
) -> List[str]:
    """Find mesh transforms by semantic name tokens, regardless of hierarchy."""
    include = {str(token).lower() for token in include_tokens}
    exclude = {str(token).lower() for token in exclude_tokens}
    result = []
    for shape in cmds.ls(type="mesh", long=True) or []:
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        if not transform:
            continue
        short_name = _short_name(transform).split(":")[-1].lower()
        tokens = set(re.findall(r"[a-z0-9]+", short_name))
        if tokens.intersection(include) and not tokens.intersection(exclude):
            result.append(transform)
    result = list(dict.fromkeys(result))
    if anchor_mesh:
        anchor_path = (cmds.ls(anchor_mesh, long=True) or [anchor_mesh])[0]
        anchor_leaf = anchor_path.split("|")[-1]
        anchor_namespace = (
            anchor_leaf.rsplit(":", 1)[0] if ":" in anchor_leaf else ""
        )
        anchor_root = anchor_path.strip("|").split("|")[0]
        scoped = []
        for candidate in result:
            candidate_leaf = candidate.split("|")[-1]
            candidate_namespace = (
                candidate_leaf.rsplit(":", 1)[0]
                if ":" in candidate_leaf else ""
            )
            if anchor_namespace:
                if candidate_namespace == anchor_namespace:
                    scoped.append(candidate)
            elif (
                not candidate_namespace
                and candidate.strip("|").split("|")[0] == anchor_root
            ):
                scoped.append(candidate)
        return scoped
    return result


def _point_cloud_bounds_center(points: Iterable[om.MPoint]) -> Optional[Vector3]:
    points = list(points)
    if not points:
        return None
    return (
        (min(point.x for point in points) + max(point.x for point in points)) * 0.5,
        (min(point.y for point in points) + max(point.y for point in points)) * 0.5,
        (min(point.z for point in points) + max(point.z for point in points)) * 0.5,
    )


def solve_scene_eye_mesh_centers(body_mesh: str) -> Dict[str, Vector3]:
    """Use actual eyeball geometry, including a single combined two-eye mesh."""
    eye_meshes = _scene_feature_meshes(
        ("eye", "eyes", "eyeball", "eyeballs", "ocular"),
        ("eyelid", "lid", "lash", "lashes", "brow", "brows"),
        anchor_mesh=body_mesh,
    )
    points = _scene_mesh_vertices(eye_meshes)
    if not points:
        return {}
    center_x = get_mesh_bounds(body_mesh)["center"].x
    left = [point for point in points if point.x > center_x]
    right = [point for point in points if point.x < center_x]
    result = {}
    if left:
        result["l_eye"] = _point_cloud_bounds_center(left)
    if right:
        result["r_eye"] = _point_cloud_bounds_center(right)
    return {name: point for name, point in result.items() if point is not None}


def solve_scene_oral_mesh_points(body_mesh: str) -> Dict[str, Vector3]:
    """Place teeth and tongue joints from separate feature meshes when present."""
    result = {}
    for joint_name, vertical_token in (
        ("upper_teeth", "upper"),
        ("lower_teeth", "lower"),
    ):
        meshes = [
            mesh for mesh in _scene_feature_meshes(
                ("tooth", "teeth"), anchor_mesh=body_mesh
            )
            if vertical_token in set(re.findall(
                r"[a-z0-9]+", _short_name(mesh).split(":")[-1].lower()
            ))
        ]
        center = _point_cloud_bounds_center(_scene_mesh_vertices(meshes))
        if center is not None:
            result[joint_name] = center

    tongue_points = _scene_mesh_vertices(_scene_feature_meshes(
        ("tongue",), anchor_mesh=body_mesh
    ))
    if not tongue_points:
        return result
    min_z = min(point.z for point in tongue_points)
    max_z = max(point.z for point in tongue_points)
    span = max(max_z - min_z, 1.0e-8)
    center_z = sum(point.z for point in tongue_points) / float(len(tongue_points))
    body_center_z = get_mesh_bounds(body_mesh)["center"].z
    front_sign = 1.0 if center_z >= body_center_z else -1.0
    start_z, end_z = (min_z, max_z) if front_sign > 0.0 else (max_z, min_z)
    for index, fraction in enumerate((0.12, 0.38, 0.64, 0.88), start=1):
        target_z = start_z + ((end_z - start_z) * fraction)
        window = span * 0.08
        section = [
            point for point in tongue_points
            if abs(point.z - target_z) <= window
        ] or sorted(tongue_points, key=lambda point: abs(point.z - target_z))[:32]
        center = _point_cloud_bounds_center(section)
        if center is not None:
            result["tongue{0}".format(index)] = center
    return result

def solve_scene_brow_mesh_points(body_mesh: str) -> Dict[str, Vector3]:
    """Sample separate eyebrow meshes into smooth medial-to-lateral joint arcs."""
    bounds = get_mesh_bounds(body_mesh)
    center_x = bounds["center"].x
    meshes = _scene_feature_meshes(
        ("brow", "brows", "eyebrow", "eyebrows"),
        ("eyelid", "lid", "lash", "lashes"),
        anchor_mesh=body_mesh,
    )
    all_points = _scene_mesh_vertices(meshes)
    result = {}
    for side, direction in (("l", 1.0), ("r", -1.0)):
        points = [
            point for point in all_points
            if (point.x - center_x) * direction > 0.0
        ]
        if len(points) < 12:
            continue
        minimum_x = min(point.x for point in points)
        maximum_x = max(point.x for point in points)
        span = max(maximum_x - minimum_x, 1.0e-8)
        fractions = (0.06, 0.23, 0.40, 0.58, 0.77, 0.94)
        if side == "r":
            fractions = tuple(1.0 - fraction for fraction in fractions)
        samples = []
        sample_count = max(16, min(64, len(points) // 12))
        for fraction in fractions:
            target_x = minimum_x + (span * fraction)
            nearest = sorted(
                points, key=lambda point: abs(point.x - target_x)
            )[:sample_count]
            samples.append(om.MVector(
                sum(point.x for point in nearest) / len(nearest),
                sum(point.y for point in nearest) / len(nearest),
                sum(point.z for point in nearest) / len(nearest),
            ))
        for _iteration in range(2):
            updated = list(samples)
            for index in range(1, len(samples) - 1):
                midpoint = (samples[index - 1] + samples[index + 1]) * 0.5
                updated[index] = (samples[index] * 0.65) + (midpoint * 0.35)
            samples = updated
        names = [
            "{0}_brow{1}".format(side, index) for index in range(1, 6)
        ] + [side + "_brow_end"]
        for name, point in zip(names, samples):
            result[name] = (point.x, point.y, point.z)
    return result


def fit_studio_scene_feature_joints(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Reapply authoritative eye, teeth, and tongue mesh centers after volume fitting."""
    targets = solve_scene_oral_mesh_points(mesh)
    targets.update(solve_scene_eye_mesh_centers(mesh))
    placed = {}
    for name, point in targets.items():
        joint = _find_template_joint(name, namespace)
        if not joint:
            continue
        _set_joint_world_translation(joint, point)
        placed[name] = point
    return {"placed": placed, "placed_count": len(placed)}


def smooth_reference_eyelid_tip_points(
    points: Dict[str, Vector3],
    iterations: int = 4,
    strength: float = 0.4,
) -> Tuple[Dict[str, Vector3], Dict[str, object]]:
    """Regularize each authored eyelid arc while preserving both corners.

    Upper and lower lids are smoothed independently so the inner and outer
    canthi remain exact.  The caller projects the resulting proposals back to
    the mesh, making this a curve-quality pass rather than a free-space edit.
    """
    result = dict(points)
    strength = max(0.0, min(float(strength), 1.0))
    iterations = max(0, int(iterations))
    report = {"smoothed_tip_count": 0, "iterations": iterations, "strength": strength}

    def _suffix(name: str) -> int:
        match = re.search(r"(\d+)$", name)
        return int(match.group(1)) if match else 0

    def _roughness(names: List[str], values: Dict[str, Vector3]) -> float:
        if len(names) < 3:
            return 0.0
        vectors = [om.MVector(*values[name]) for name in names]
        length = sum((vectors[index] - vectors[index - 1]).length() for index in range(1, len(vectors)))
        if length <= 1.0e-8:
            return 0.0
        second_difference = sum(
            (vectors[index - 1] - (vectors[index] * 2.0) + vectors[index + 1]).length()
            for index in range(1, len(vectors) - 1)
        )
        return float(second_difference / length)

    before_values = dict(points)
    arc_names = []
    for side in ("l", "r"):
        inner = side + "_inner_eyelidTip"
        outer = side + "_outer_eyelidTip"
        upper = sorted(
            (name for name in points if re.match(r"^%s_upper_eyelidTip\d+$" % side, name, re.I)),
            key=_suffix,
            reverse=True,
        )
        lower = sorted(
            (name for name in points if re.match(r"^%s_lower_eyelidTip\d+$" % side, name, re.I)),
            key=_suffix,
        )
        arcs = []
        if inner in points and outer in points and upper:
            arcs.append([inner] + upper + [outer])
        if inner in points and outer in points and lower:
            arcs.append([outer] + lower + [inner])
        for names in arcs:
            arc_names.append(names)
            working = {name: om.MVector(*result[name]) for name in names}
            for _iteration in range(iterations):
                updated = dict(working)
                for index in range(1, len(names) - 1):
                    name = names[index]
                    neighbor_midpoint = (working[names[index - 1]] + working[names[index + 1]]) * 0.5
                    updated[name] = (working[name] * (1.0 - strength)) + (neighbor_midpoint * strength)
                working = updated
            for name, vector in working.items():
                result[name] = (vector.x, vector.y, vector.z)

    affected = {name for names in arc_names for name in names[1:-1]}
    report["smoothed_tip_count"] = len(affected)
    report["roughness_before"] = sum(_roughness(names, before_values) for names in arc_names)
    report["roughness_after"] = sum(_roughness(names, result) for names in arc_names)
    return result, report


def solve_reference_detail_points(
    mesh: str,
    reference_count: int = 3,
) -> Tuple[Dict[str, Vector3], List[str]]:
    """Blend the closest approved full skeletons into target mesh space.

    The atlas supplies anatomical proportions for fingers, thumbs, feet,
    correctives, and facial branches.  Mesh-volume fitting is intentionally a
    secondary local correction so it cannot rebuild those branches from an
    ambiguous front-view section.
    """
    topology_points, topology_references = solve_topology_reference_points(mesh)
    if topology_points:
        return topology_points, topology_references
    ranked = _rank_reference_entries(mesh, require_detail=True)
    if not ranked:
        return {}, []
    selected = ranked[:max(1, int(reference_count))]
    bounds = get_mesh_bounds(mesh)
    origin = (bounds["center"].x, bounds["min"].y, bounds["center"].z)
    height = bounds["height"]
    names = sorted({
        name
        for _distance, entry in selected
        for name in entry.get("detail_points", {})
    })
    points = {}
    for name in names:
        samples = []
        for distance, entry in selected:
            point = entry.get("detail_points", {}).get(name)
            if point is None:
                continue
            weight = 1.0 / max(distance, 0.002) ** 2
            samples.append((weight, point))
        if not samples:
            continue
        total_weight = sum(weight for weight, _point in samples)
        normalized = tuple(
            sum(weight * point[axis] for weight, point in samples) / total_weight
            for axis in range(3)
        )
        points[name] = (
            origin[0] + normalized[0] * height,
            origin[1] + normalized[1] * height,
            origin[2] + normalized[2] * height,
        )
    return points, [str(entry["case_id"]) for _distance, entry in selected]


def _solve_reference_proportional_joint_points(
    mesh: str,
    joint_names: Iterable[str],
    reference_count: int = 5,
    excluded_case_ids: Iterable[str] = (),
) -> Tuple[Dict[str, Vector3], List[str]]:
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    excluded = {str(case_id) for case_id in excluded_case_ids}
    ranked = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
        and str(entry.get("case_id") or "") not in excluded
    ]
    if not ranked:
        return {}, []
    selected = ranked[:max(1, int(reference_count))]
    bounds = get_mesh_bounds(mesh)
    origin = (bounds["center"].x, bounds["min"].y, bounds["center"].z)
    height = bounds["height"]
    result = {}
    for name in joint_names:
        samples = []
        for distance, entry in selected:
            point = (entry.get("detail_points") or {}).get(name)
            if point is None:
                continue
            weight = 1.0 / max(float(distance), 0.002) ** 2
            samples.append((weight, point))
        if not samples:
            continue
        total_weight = sum(weight for weight, _point in samples)
        normalized = tuple(
            sum(weight * float(point[axis]) for weight, point in samples)
            / total_weight
            for axis in range(3)
        )
        result[name] = (
            origin[0] + normalized[0] * height,
            origin[1] + normalized[1] * height,
            origin[2] + normalized[2] * height,
        )
    return result, [str(entry["case_id"]) for _distance, entry in selected]


def solve_reference_internal_head_points(
    mesh: str,
    reference_count: int = 5,
    excluded_case_ids: Iterable[str] = (),
) -> Tuple[Dict[str, Vector3], List[str]]:
    """Fit neck, skull, jaw, teeth, and tongue without surface extrapolation.

    These pivots sit inside the skull or oral cavity, where nearest-surface
    patches are frequently close to planar.  A local affine solve can then
    become ill-conditioned and throw the joint toward the face.  Blend the
    normalized authored pivots from the closest topology-compatible rigs
    instead; this keeps the centerline stable while retaining age/proportion
    differences from the reference corpus.
    """
    return _solve_reference_proportional_joint_points(
        mesh,
        INTERNAL_HEAD_REFERENCE_JOINTS,
        reference_count=reference_count,
        excluded_case_ids=excluded_case_ids,
    )


def solve_reference_toe_points(
    mesh: str,
    reference_count: int = 5,
    excluded_case_ids: Iterable[str] = (),
) -> Tuple[Dict[str, Vector3], List[str]]:
    """Fit toe bases at the authored ball pivots and tips inside the mesh end."""
    return _solve_reference_proportional_joint_points(
        mesh,
        REFERENCE_TOE_JOINTS,
        reference_count=reference_count,
        excluded_case_ids=excluded_case_ids,
    )


def solve_reference_corpus_points(
    mesh: str,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Tuple[Dict[str, Vector3], Dict[str, float], List[str], str]:
    """Seed placement from the closest approved normalized character."""
    fallback, confidence = solve_studio_template_points(mesh, template_path=template_path)
    corpus = _load_reference_placement_corpus()
    if not corpus:
        return fallback, confidence, [], ""
    topology_points, topology_references = solve_topology_reference_points(mesh)
    if topology_points:
        seeded_names = []
        for canonical_name, template_name in TEMPLATE_CORE_JOINTS.items():
            if template_name not in topology_points:
                continue
            fallback[canonical_name] = topology_points[template_name]
            confidence[canonical_name] = 0.99
            seeded_names.append(canonical_name)
        if len(seeded_names) >= 15:
            return (
                fallback,
                confidence,
                seeded_names,
                topology_references[0] if topology_references else "",
            )
    bounds = get_mesh_bounds(mesh)
    width_ratio = bounds["width"] / max(bounds["height"], 1.0e-6)
    depth_ratio = bounds["depth"] / max(bounds["height"], 1.0e-6)
    vertex_count = int(cmds.polyEvaluate(_as_mesh_transform(mesh), vertex=True) or 0)

    def _distance(entry):
        return _reference_shape_distance(
            entry, width_ratio, depth_ratio, vertex_count
        )

    reference = min(corpus, key=_distance)
    origin = (bounds["center"].x, bounds["min"].y, bounds["center"].z)
    height = bounds["height"]
    seeded_names = []
    for name, normalized in reference["points"].items():
        fallback[name] = (
            origin[0] + normalized[0] * height,
            origin[1] + normalized[1] * height,
            origin[2] + normalized[2] * height,
        )
        confidence[name] = max(0.72, 0.94 - min(_distance(reference), 0.22))
        seeded_names.append(name)
    return fallback, confidence, seeded_names, str(reference["case_id"])


def solve_mapped_hierarchy_points(
    mesh: str,
    joint_map: dict,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Tuple[Dict[str, Vector3], Dict[str, float]]:
    """Use the active rig mapping as the proportion and hierarchy proposal."""
    missing = mapped_hierarchy_missing_slots(joint_map)
    if missing:
        raise RuntimeError(
            "Mapped placement is incomplete: {0}".format(", ".join(missing))
        )
    canonical_joints = mapped_anatomical_joints(joint_map)
    source_points = {
        name: tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        for name, joint in canonical_joints.items()
    }
    frame = placement_frame_from_mapping(joint_map)
    logical_source_points = {
        name: frame.world_to_logical(point) for name, point in source_points.items()
    }
    fallback, confidence = solve_studio_template_points(mesh, template_path=template_path)
    # The default-template fallback is Y-up. Convert it through normalized mesh
    # coordinates when the mapped character uses another physical axis.
    if frame != PlacementFrame():
        default_bounds = get_mesh_bounds(mesh)
        logical_bounds = _logical_mesh_bounds(mesh, frame)
        converted_fallback = {}
        for name, point in fallback.items():
            normalized = (
                (point[0] - default_bounds["center"].x) / max(default_bounds["width"], 1.0e-6),
                (point[1] - default_bounds["min"].y) / max(default_bounds["height"], 1.0e-6),
                (point[2] - default_bounds["center"].z) / max(default_bounds["depth"], 1.0e-6),
            )
            logical_point = (
                logical_bounds["center"].x + normalized[0] * logical_bounds["width"],
                logical_bounds["min"].y + normalized[1] * logical_bounds["height"],
                logical_bounds["center"].z + normalized[2] * logical_bounds["depth"],
            )
            converted_fallback[name] = frame.logical_to_world(logical_point)
        fallback = converted_fallback
    bounds = _logical_mesh_bounds(mesh, frame)
    values = list(logical_source_points.values())
    source_min_y = min(point[1] for point in values)
    source_max_y = max(point[1] for point in values)
    if "head" in logical_source_points and "neck" in logical_source_points:
        head_y = logical_source_points["head"][1]
        neck_y = logical_source_points["neck"][1]
        source_max_y = max(source_max_y, head_y + max(head_y - neck_y, 0.0) * 0.35)
    source_height = max(source_max_y - source_min_y, 1.0e-6)
    source_min_x = min(point[0] for point in values)
    source_max_x = max(point[0] for point in values)
    source_width = max(source_max_x - source_min_x, 1.0e-6)
    center_names = (
        "origin", "pelvis", "spine_01", "spine_02", "spine_03",
        "spine_04", "neck", "head",
    )
    center_points = [logical_source_points[name] for name in center_names if name in logical_source_points]
    source_center_x = sum(point[0] for point in center_points) / float(len(center_points))
    source_center_z = sum(point[2] for point in center_points) / float(len(center_points))
    target_center = bounds["center"]
    target_min = bounds["min"]
    mapped_points = {}
    for name, point in logical_source_points.items():
        logical_point = (
            target_center.x + ((point[0] - source_center_x) / source_width) * bounds["width"],
            target_min.y + ((point[1] - source_min_y) / source_height) * bounds["height"],
            target_center.z + ((point[2] - source_center_z) / source_height) * bounds["height"],
        )
        mapped_points[name] = frame.logical_to_world(logical_point)
        confidence[name] = 0.82
    fallback.update(mapped_points)

    # Fill anatomical roles that HIK does not expose from neighboring mapped
    # joints, not from an unrelated hierarchy. This keeps variable spine counts
    # ordered and makes terminal helpers inherit the user's proportions.
    spine_chain = ("pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck")
    known_indices = [index for index, name in enumerate(spine_chain) if name in mapped_points]
    for index, name in enumerate(spine_chain):
        if name in mapped_points:
            continue
        lower = max((item for item in known_indices if item < index), default=None)
        upper = min((item for item in known_indices if item > index), default=None)
        if lower is None or upper is None:
            continue
        amount = (index - lower) / float(upper - lower)
        lower_point = fallback[spine_chain[lower]]
        upper_point = fallback[spine_chain[upper]]
        fallback[name] = tuple(
            lower_point[axis] + ((upper_point[axis] - lower_point[axis]) * amount)
            for axis in range(3)
        )
        confidence[name] = 0.76

    for tip_name, end_name, parent_name, extension in (
        ("head_tip", "head", "neck", 0.35),
        ("l_hand_tip", "l_hand", "l_lowerarm", 0.25),
        ("r_hand_tip", "r_hand", "r_lowerarm", 0.25),
        ("l_toeTip", "l_toe", "l_ankle", 0.45),
        ("r_toeTip", "r_toe", "r_ankle", 0.45),
    ):
        if end_name not in fallback or parent_name not in fallback:
            continue
        end_point = fallback[end_name]
        parent_point = fallback[parent_name]
        fallback[tip_name] = tuple(
            end_point[axis] + ((end_point[axis] - parent_point[axis]) * extension)
            for axis in range(3)
        )
        confidence[tip_name] = 0.70
    return fallback, confidence


def solve_basic_biped_points(mesh: str) -> Tuple[Dict[str, Vector3], Dict[str, float]]:
    """
    Return first-pass biped joint positions.

    The current implementation is proportional, with confidence set low/medium.
    This gives a stable baseline that can later be refined by landmark or mesh
    cross-section solvers without changing the downstream rigging code.
    """
    bounds = get_mesh_bounds(mesh)
    points = {
        name: point_from_normalized_bounds(bounds, normalized)
        for name, normalized in BIPED_PROPORTIONS.items()
    }
    diagonal = om.MVector(bounds["width"], bounds["height"], bounds["depth"]).length()
    points = enforce_limb_planarity(points, minimum_bend=diagonal * 0.005)
    confidence = {name: 0.50 for name in points}

    # Spine/head centerline tends to be more reliable from bbox proportions.
    for name in ["origin", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"]:
        confidence[name] = 0.65

    return points, confidence


def validate_points_inside_mesh(
    mesh: str,
    points: Dict[str, Vector3],
    query: Optional[MeshInteriorQuery] = None,
) -> List[str]:
    """Return deform landmarks whose positions cannot be verified in the mesh."""
    query = query or _cached_mesh_interior_query(mesh)
    terminal_roles = {
        "head_tip",
        "l_hand_tip", "r_hand_tip",
        "l_toeTip", "r_toeTip",
    }
    surface_tolerance = max(query.diagonal * 0.005, query.tolerance * 20.0)
    outside = []
    for name, point in points.items():
        if name in NON_DEFORM_PLACEMENT_ROLES or query.point_inside(point):
            continue
        if name in terminal_roles:
            closest = query.mesh_fn.getClosestPoint(
                om.MPoint(*point), om.MSpace.kWorld
            )[0]
            distance = om.MVector(
                closest.x - point[0],
                closest.y - point[1],
                closest.z - point[2],
            ).length()
            if distance <= surface_tolerance:
                continue
        outside.append(name)
    return outside


def validate_anatomical_layout(
    points: Dict[str, Vector3],
    bounds: Dict[str, object],
    frame: Optional[PlacementFrame] = None,
) -> List[str]:
    """Return actionable hierarchy/order problems in an otherwise valid volume solution."""
    frame = frame or PlacementFrame()
    if frame != PlacementFrame():
        logical_points = {name: frame.world_to_logical(point) for name, point in points.items()}
        logical_bounds = _logical_mesh_bounds(bounds["mesh"], frame)
        logical_bounds["mesh"] = bounds["mesh"]
        return validate_anatomical_layout(logical_points, logical_bounds)
    issues = []
    diagonal = max(
        om.MVector(bounds["width"], bounds["height"], bounds["depth"]).length(),
        0.001,
    )
    minimum_bone_length = diagonal * 0.003

    if "origin" in points and "pelvis" in points:
        origin = points["origin"]
        pelvis = points["pelvis"]
        if abs(origin[0] - pelvis[0]) > max(bounds["width"] * 0.02, 1.0e-5):
            issues.append("origin must be centered beneath the pelvis")
        origin_depth_tolerance = max(
            bounds["depth"] * 0.08,
            bounds["height"] * 0.04,
            1.0e-5,
        )
        if abs(origin[2] - pelvis[2]) > origin_depth_tolerance:
            issues.append("origin depth must align beneath the pelvis")
        if abs(origin[1] - bounds["min"].y) > max(bounds["height"] * 0.015, 1.0e-5):
            issues.append("origin must remain on the character ground plane")

    # In the authored studio hierarchy, spine5_Tip is a short connector at
    # the base of the neck. Approved rigs intentionally place neck1 at or
    # very near that pivot (0.0-0.14 cm across the reference corpus), so a
    # generic minimum-bone-length check incorrectly rejects known-good fits.
    short_template_links = {("spine_04", "neck")}
    for child, parent in PARENT_MAP.items():
        if child not in points or parent not in points:
            continue
        child_v = om.MVector(*points[child])
        parent_v = om.MVector(*points[parent])
        if (
            (parent, child) not in short_template_links
            and (child_v - parent_v).length() < minimum_bone_length
        ):
            issues.append("{0}->{1} has near-zero length".format(parent, child))

    ascending_chains = (
        ("pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head", "head_tip"),
    )
    descending_chains = (
        ("l_thigh", "l_knee", "l_ankle"),
        ("r_thigh", "r_knee", "r_ankle"),
    )
    for chain in ascending_chains:
        for lower, upper in zip(chain, chain[1:]):
            if lower not in points or upper not in points:
                continue
            if (lower, upper) in short_template_links:
                # Permit the intentional coincident/near-coincident helper
                # pivot, but still reject a clearly inverted neck joint.
                if points[upper][1] < points[lower][1] - minimum_bone_length:
                    issues.append("{0} must be above {1}".format(upper, lower))
            elif points[upper][1] <= points[lower][1]:
                issues.append("{0} must be above {1}".format(upper, lower))
    for chain in descending_chains:
        for upper, lower in zip(chain, chain[1:]):
            if upper in points and lower in points and points[lower][1] >= points[upper][1]:
                issues.append("{0} must be below {1}".format(lower, upper))

    centerline_values = [
        points[name][0]
        for name in ("pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head")
        if name in points
    ]
    center_x = sum(centerline_values) / float(len(centerline_values)) if centerline_values else bounds["center"].x
    side_tolerance = max(bounds["width"] * 0.002, 1.0e-5)
    for name, point in points.items():
        if name.startswith("l_") and point[0] <= center_x + side_tolerance:
            issues.append("{0} crossed the character centerline".format(name))
        elif name.startswith("r_") and point[0] >= center_x - side_tolerance:
            issues.append("{0} crossed the character centerline".format(name))

    lateral_chains = (
        ("l_clavicle", "l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip", 1.0),
        ("r_clavicle", "r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip", -1.0),
    )
    for *chain, direction in lateral_chains:
        for inner, outer in zip(chain, chain[1:]):
            if inner in points and outer in points:
                if (points[outer][0] - points[inner][0]) * direction <= 0.0:
                    issues.append("{0} must remain lateral to {1}".format(outer, inner))

    # Plane membership alone does not prevent a chain from folding back across
    # itself. Require successive core segments to continue generally forward
    # through elbows, knees, and the spine.
    continuity_chains = (
        ("l_clavicle", "l_upperarm", "l_lowerarm", "l_hand"),
        ("r_clavicle", "r_upperarm", "r_lowerarm", "r_hand"),
        ("l_thigh", "l_knee", "l_ankle"),
        ("r_thigh", "r_knee", "r_ankle"),
        ("pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"),
    )
    for chain in continuity_chains:
        for start_name, bend_name, end_name in zip(chain, chain[1:], chain[2:]):
            if not all(name in points for name in (start_name, bend_name, end_name)):
                continue
            incoming = om.MVector(*points[bend_name]) - om.MVector(*points[start_name])
            outgoing = om.MVector(*points[end_name]) - om.MVector(*points[bend_name])
            if incoming.length() <= minimum_bone_length or outgoing.length() <= minimum_bone_length:
                continue
            # Allow ordinary anatomical curvature (especially at the base of the
            # neck), but reject a substantial reversal such as an arm segment
            # snapping back across the torso to find an unrelated volume.
            if (incoming.normal() * outgoing.normal()) <= -0.25:
                issues.append(
                    "{0}->{1}->{2} folds back on itself".format(
                        start_name, bend_name, end_name
                    )
                )

    for side in ("l", "r"):
        ankle_name = "{0}_ankle".format(side)
        toe_name = "{0}_toe".format(side)
        tip_name = "{0}_toeTip".format(side)
        if all(name in points for name in (ankle_name, toe_name, tip_name)):
            ankle_to_toe = om.MVector(*points[toe_name]) - om.MVector(*points[ankle_name])
            toe_to_tip = om.MVector(*points[tip_name]) - om.MVector(*points[toe_name])
            if (
                ankle_to_toe.length() > minimum_bone_length
                and toe_to_tip.length() > minimum_bone_length
                and (ankle_to_toe.normal() * toe_to_tip.normal()) <= 0.0
            ):
                issues.append("{0}->{1}->{2} reverses through the forefoot".format(
                    ankle_name, toe_name, tip_name
                ))

    foot_height_tolerance = bounds["height"] * 0.04
    for side in ("l", "r"):
        ankle_name = "{0}_ankle".format(side)
        for toe_name in ("{0}_toe".format(side), "{0}_toeTip".format(side)):
            if ankle_name in points and toe_name in points:
                if points[toe_name][1] > points[ankle_name][1] + foot_height_tolerance:
                    issues.append(
                        "{0} is implausibly above {1}".format(toe_name, ankle_name)
                    )
    return issues


def solve_production_biped_points(
    mesh: str,
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    joint_map: Optional[dict] = None,
) -> Tuple[
    Dict[str, Vector3],
    Dict[str, float],
    MeshPlacementReport,
    List[str],
    Dict[str, float],
]:
    """
    Place a biped template using proposals plus mesh-volume verification.

    ``landmark_points`` is the integration seam for an ML or vision provider.
    Known joint names override the proportional proposal, but every override is
    still recentered and validated against the Maya mesh. Unknown landmarks are
    ignored so a provider cannot accidentally alter the output contract.
    """
    mesh = _as_mesh_transform(mesh)
    report = analyze_mesh_for_joint_placement(mesh)
    query = _cached_mesh_interior_query(mesh)
    using_mapped_hierarchy = mapped_hierarchy_requested(joint_map)
    placement_frame = placement_frame_from_mapping(joint_map) if using_mapped_hierarchy else PlacementFrame()

    # When the target has a matching approved topology reference with the full
    # core hierarchy, transfer those authored core landmarks directly. The
    # generic volume refinements below are valuable for new topology, but can
    # move known-good anchors (especially shoulders and toes) away from the
    # approved fit on a topology-matched character.
    if not using_mapped_hierarchy:
        topology_points, _topology_cases = solve_topology_reference_points(mesh)
        topology_core = {}
        for canonical_name, template_name in TEMPLATE_CORE_JOINTS.items():
            candidates = [template_name]
            if canonical_name == "neck":
                # Older approved scenes use ``neck`` where the current studio
                # template calls the same anatomical pivot ``neck1``.
                candidates.append("neck")
            source_name = next(
                (candidate for candidate in candidates if candidate in topology_points),
                None,
            )
            if source_name:
                topology_core[canonical_name] = topology_points[source_name]
        if len(topology_core) == len(TEMPLATE_CORE_JOINTS):
            confidence = {name: 0.99 for name in topology_core}
            for name, point in (landmark_points or {}).items():
                if name in topology_core and len(point) == 3:
                    topology_core[name] = tuple(float(value) for value in point)
                    confidence[name] = 0.72
            outside = validate_points_inside_mesh(mesh, topology_core, query=query)
            return (
                topology_core,
                confidence,
                report,
                outside,
                {name: 0.0 for name in topology_core},
            )

    reference_seeded = set()
    topology_seeded = set()
    try:
        if using_mapped_hierarchy:
            proposals, confidence = solve_mapped_hierarchy_points(
                mesh,
                joint_map,
                template_path=template_path,
            )
        else:
            proposals, confidence, seeded_names, _reference_case = solve_reference_corpus_points(
                mesh, template_path=template_path
            )
            reference_seeded.update(seeded_names)
            topology_seeded.update(
                name for name in seeded_names if confidence.get(name, 0.0) >= 0.98
            )
    except Exception as exc:
        if using_mapped_hierarchy:
            raise
        cmds.warning(
            "[joint_placer] Studio template proposal failed; using proportional fallback: {0}".format(exc)
        )
        proposals, confidence = solve_basic_biped_points(mesh)
    supplied_landmarks = {
        name: tuple(float(value) for value in point)
        for name, point in (landmark_points or {}).items()
        if name in proposals and len(point) == 3
    }
    proposals.update(supplied_landmarks)
    topology_seeded.difference_update(supplied_landmarks)

    # The rig reference belongs on the ground directly below the pelvis. It is
    # intentionally between the feet, not embedded in whichever foot happens
    # to be closest to the character centerline.
    if "pelvis" in proposals:
        logical_bounds = _logical_mesh_bounds(mesh, placement_frame)
        logical_pelvis = placement_frame.world_to_logical(proposals["pelvis"])
        proposals["origin"] = placement_frame.logical_to_world(
            (logical_pelvis[0], logical_bounds["min"].y, logical_pelvis[2])
        )

    resolved = {}
    clearance = {}
    for name in BUILD_ORDER:
        if name not in proposals:
            continue
        candidate = proposals[name]
        if name in NON_DEFORM_PLACEMENT_ROLES:
            resolved[name] = candidate
            clearance[name] = 0.0
            confidence[name] = max(confidence.get(name, 0.0), 0.95)
            continue
        if name in topology_seeded:
            is_inside = query.point_inside(candidate)
            if not is_inside:
                candidate, is_inside = _bounded_move_inside(
                    query, candidate, query.diagonal * 0.025
                )
            resolved[name] = candidate
            clearance[name] = 0.0
            confidence[name] = 0.99 if is_inside else 0.82
            continue
        successful_sections = 0
        section_clearances = []
        logical_axes = PLACEMENT_SECTION_AXES.get(name, ("x", "z"))
        axes = tuple(placement_frame.world_axis(axis) for axis in logical_axes)
        if name in reference_seeded and not query.point_inside(candidate):
            # Corpus anchors already encode anatomical proportions. If one is
            # just outside a new character, first inset it through the nearest
            # local surface. Running a full-axis recenter first can jump from a
            # shoulder/ankle to an unrelated torso or leg interval on complex
            # watertight characters.
            candidate, _locally_inset = query.move_inside(candidate)
        # Once an exterior proposal has been locally inset, axis intervals are
        # safe to resolve around that limb. Recenter every proposal—including
        # corpus seeds already inside the body—so depth comes from the actual
        # mesh volume instead of retaining the source character's front-view
        # projection.
        for _pass in range(2):
            for axis in axes:
                candidate, axis_clearance, success = query.recenter_axis(candidate, axis)
                successful_sections += int(success)
                if success:
                    section_clearances.append(axis_clearance)

        candidate, is_inside = query.move_inside(candidate)
        resolved[name] = candidate
        clearance[name] = min(section_clearances) if section_clearances else 0.0

        score = 0.72 if name in supplied_landmarks else confidence.get(name, 0.5)
        score += min(successful_sections, 4) * 0.04
        if is_inside:
            score += 0.12
        if not report.is_closed_manifold:
            score -= 0.15
        confidence[name] = max(0.05, min(score, 0.99))

    # Cross-section refinement operates per joint and can introduce tiny
    # out-of-plane offsets. Make the IK planes exact as the final deterministic
    # placement step, then re-run containment so a projection can never pass
    # silently when the source mesh cannot accommodate it.
    if len(topology_seeded) < 15:
        resolved = refine_leg_landmarks(
            resolved,
            query,
            frame=placement_frame,
        )
        resolved = refine_foot_landmarks(
            resolved,
            query,
            frame=placement_frame,
        )
    # Shoulder topology varies too much for an atlas seed to be authoritative.
    # Always search the target deltoid/humeral section, including dense studio
    # templates whose other body landmarks remain topology-seeded.
    resolved = refine_shoulder_landmarks(
        resolved,
        query,
        frame=placement_frame,
    )
    resolved = enforce_limb_planarity(
        resolved,
        minimum_bend=query.diagonal * 0.005,
        inside_query=query,
        frame=placement_frame,
    )
    planar_targets = dict(resolved)
    lateral_epsilon = query.diagonal * 0.0005
    for chain_names, direction in (
        (("l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip"), 1.0),
        (("r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip"), -1.0),
    ):
        logical_plane_start = placement_frame.world_to_logical(resolved[chain_names[0]])
        logical_plane_end = placement_frame.world_to_logical(resolved[chain_names[2]])
        plane_side_delta = logical_plane_end[0] - logical_plane_start[0]
        for parent_name, child_name in zip(chain_names, chain_names[1:]):
            if parent_name not in resolved or child_name not in resolved:
                continue
            parent_point = resolved[parent_name]
            target_point = planar_targets[child_name]
            logical_parent = placement_frame.world_to_logical(parent_point)
            logical_target = placement_frame.world_to_logical(target_point)
            is_lateral = (
                (logical_target[0] - logical_parent[0]) * direction
            ) > lateral_epsilon
            if query.point_inside(target_point) and is_lateral:
                continue
            # Search a narrow fan on the exact oblique arm plane, longest candidates
            # first. This handles wrists/fingers whose local volume curves away
            # from the straight authored segment without allowing an interval
            # query to jump across to the torso.
            delta_x = logical_target[0] - logical_parent[0]
            delta_up = logical_target[1] - logical_parent[1]
            planar_length = math.sqrt((delta_x * delta_x) + (delta_up * delta_up))
            base_angle = math.atan2(delta_up, delta_x)
            angle_offsets = [0.0]
            for degrees in range(5, 91, 5):
                angle_offsets.extend((math.radians(degrees), math.radians(-degrees)))
            repaired = None
            for step in range(100, 0, -1):
                amount = step / 100.0
                for angle_offset in angle_offsets:
                    angle = base_angle + angle_offset
                    candidate_side = (
                        logical_parent[0] + math.cos(angle) * planar_length * amount
                    )
                    plane_ratio = (
                        (candidate_side - logical_plane_start[0]) / plane_side_delta
                        if abs(plane_side_delta) > 1.0e-8 else 0.0
                    )
                    logical_candidate = (
                        candidate_side,
                        logical_parent[1] + math.sin(angle) * planar_length * amount,
                        logical_plane_start[2] + (
                            (logical_plane_end[2] - logical_plane_start[2]) * plane_ratio
                        ),
                    )
                    candidate = placement_frame.logical_to_world(logical_candidate)
                    if (
                        (logical_candidate[0] - logical_parent[0]) * direction > lateral_epsilon
                        and query.point_inside(candidate)
                    ):
                        repaired = candidate
                        break
                if repaired:
                    break
            if repaired:
                resolved[child_name] = repaired
    repair_axes = {}
    for chain_names, repair_axis in (
        (("l_thigh", "l_knee", "l_ankle"), placement_frame.world_axis("z")),
        (("r_thigh", "r_knee", "r_ankle"), placement_frame.world_axis("z")),
        (("l_toe", "l_toeTip", "r_toe", "r_toeTip"), placement_frame.world_axis("y")),
        (("pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"), placement_frame.world_axis("z")),
    ):
        repair_axes.update({name: repair_axis for name in chain_names})
    for name, repair_axis in repair_axes.items():
        if name in resolved and not query.point_inside(resolved[name]):
            repaired, _clearance, success = query.recenter_axis(
                resolved[name], repair_axis
            )
            if success and query.point_inside(repaired):
                resolved[name] = repaired

    # Pelvis depth can change during its final cross-section/plane solve. Align
    # the non-deforming root only after those refinements so it remains exactly
    # below the finished pelvis instead of below the initial template seed.
    if "origin" in resolved and "pelvis" in resolved:
        logical_bounds = _logical_mesh_bounds(mesh, placement_frame)
        logical_pelvis = placement_frame.world_to_logical(resolved["pelvis"])
        resolved["origin"] = placement_frame.logical_to_world(
            (logical_pelvis[0], logical_bounds["min"].y, logical_pelvis[2])
        )
    outside = validate_points_inside_mesh(mesh, resolved, query=query)
    for name in outside:
        confidence[name] = min(confidence.get(name, 0.0), 0.25)
    return resolved, confidence, report, outside, clearance


def _is_generated_joint(joint: str) -> bool:
    if not joint or not cmds.objExists(joint):
        return False
    if not cmds.attributeQuery(GENERATED_ATTR, node=joint, exists=True):
        return False
    try:
        return bool(cmds.getAttr("{0}.{1}".format(joint, GENERATED_ATTR)))
    except Exception:
        return False


def _tag_generated_joint(joint: str) -> None:
    if not joint or not cmds.objExists(joint):
        return
    if not cmds.attributeQuery(GENERATED_ATTR, node=joint, exists=True):
        cmds.addAttr(joint, longName=GENERATED_ATTR, attributeType="bool")
    cmds.setAttr("{0}.{1}".format(joint, GENERATED_ATTR), True)


def _set_string_attr(node: str, attr: str, value: str) -> None:
    if not node or not cmds.objExists(node):
        return
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, longName=attr, dataType="string")
    cmds.setAttr("{0}.{1}".format(node, attr), value, type="string")


def _set_float_attr(node: str, attr: str, value: float) -> None:
    if not node or not cmds.objExists(node):
        return
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, longName=attr, attributeType="double")
    cmds.setAttr("{0}.{1}".format(node, attr), float(value))


def _connect_placement_mesh(root: str, mesh: str) -> None:
    """Keep a rename-safe mesh link, readable path, and geometry signature."""
    if not root or not mesh or not cmds.objExists(root) or not cmds.objExists(mesh):
        return
    mesh = _as_mesh_transform(mesh)
    _set_string_attr(
        root,
        PLACEMENT_MESH_ATTR,
        (cmds.ls(mesh, long=True) or [mesh])[0],
    )
    if not cmds.attributeQuery(PLACEMENT_MESH_MESSAGE_ATTR, node=root, exists=True):
        cmds.addAttr(root, longName=PLACEMENT_MESH_MESSAGE_ATTR, attributeType="message")
    cmds.connectAttr(
        mesh + ".message",
        "{0}.{1}".format(root, PLACEMENT_MESH_MESSAGE_ATTR),
        force=True,
    )
    _set_string_attr(
        root,
        PLACEMENT_MESH_SIGNATURE_ATTR,
        _placement_mesh_signature(mesh),
    )


def _placement_mesh_signature(mesh: str) -> str:
    """Hash a mesh's world-space topology and points for safe approved reruns."""
    mesh = _as_mesh_transform(mesh)
    shape = (
        cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True)
        or [None]
    )[0]
    if not shape:
        raise RuntimeError("Cannot signature a mesh without a renderable shape: {0}".format(mesh))
    selection = om.MSelectionList()
    selection.add(shape)
    points = om.MFnMesh(selection.getDagPath(0)).getPoints(om.MSpace.kWorld)
    digest = hashlib.sha256()
    digest.update(struct.pack("!II", len(points), int(cmds.polyEvaluate(mesh, face=True) or 0)))
    for point in points:
        digest.update(struct.pack("!3d", float(point.x), float(point.y), float(point.z)))
    return digest.hexdigest()


def _approved_placement_matches_mesh(root: str, mesh: str) -> bool:
    """Return whether the existing approved pose belongs to this mesh."""
    if not root or not cmds.objExists(root) or not mesh or not cmds.objExists(mesh):
        return False
    mesh = _as_mesh_transform(mesh)
    if cmds.attributeQuery(PLACEMENT_MESH_SIGNATURE_ATTR, node=root, exists=True):
        stored_signature = cmds.getAttr(
            "{0}.{1}".format(root, PLACEMENT_MESH_SIGNATURE_ATTR)
        ) or ""
        if stored_signature:
            return stored_signature == _placement_mesh_signature(mesh)

    # Legacy skeletons predate signatures. Preserve their approved positions
    # only when their recorded source path (or live message connection) is the
    # same mesh; a different selected mesh must be solved from its own shape.
    current_path = (cmds.ls(mesh, long=True) or [mesh])[0]
    connected = []
    if cmds.attributeQuery(PLACEMENT_MESH_MESSAGE_ATTR, node=root, exists=True):
        connected = cmds.listConnections(
            "{0}.{1}".format(root, PLACEMENT_MESH_MESSAGE_ATTR),
            source=True,
            destination=False,
            shapes=False,
        ) or []
    if connected:
        try:
            connected_path = (cmds.ls(_as_mesh_transform(connected[0]), long=True) or [])[0]
            if connected_path:
                return connected_path == current_path
        except RuntimeError:
            pass
    stored_path = ""
    if cmds.attributeQuery(PLACEMENT_MESH_ATTR, node=root, exists=True):
        stored_path = cmds.getAttr(
            "{0}.{1}".format(root, PLACEMENT_MESH_ATTR)
        ) or ""
    if stored_path and cmds.objExists(stored_path):
        try:
            stored_path = (cmds.ls(_as_mesh_transform(stored_path), long=True) or [stored_path])[0]
        except RuntimeError:
            pass
    return stored_path == current_path


def _legacy_studio_pose_matches_mesh(
    root: str,
    mesh: str,
    anchor_names: Optional[Iterable[str]] = None,
    allow_mapped_hierarchy: bool = False,
) -> bool:
    """Recognize an untagged, already-fitted studio pose on its body mesh.

    Older joint-placer scenes have no geometry signature. Preserve their
    scene-authored placement on first use only when the mapped/core anchors
    already occupy the selected mesh bounds and span nearly its full height.
    The fit then stamps a content signature so future runs can distinguish a
    different target mesh without repeating this heuristic.
    """
    is_supported_root = is_studio_template_skeleton(root)
    if allow_mapped_hierarchy and root and cmds.objExists(root):
        is_supported_root = is_supported_root or cmds.nodeType(root) == "joint"
    if (
        not root or not mesh or not cmds.objExists(root)
        or not cmds.objExists(mesh)
        or not is_supported_root
        or cmds.attributeQuery(PLACEMENT_MESH_SIGNATURE_ATTR, node=root, exists=True)
    ):
        return False
    bounds = get_mesh_bounds(mesh)
    height = max(float(bounds["height"]), 1.0e-8)
    tolerance = height * 0.01
    current = _capture_studio_joint_positions(root)
    names = list(anchor_names or current.keys())
    positions = [
        current[name] for name in names
        if name in current and name != "origin"
    ]
    if len(positions) < 16:
        return False
    inside = 0
    ys = []
    for position in positions:
        point = om.MVector(*position)
        ys.append(float(point.y))
        if (
            bounds["min"].x - tolerance <= point.x <= bounds["max"].x + tolerance
            and bounds["min"].y - tolerance <= point.y <= bounds["max"].y + tolerance
            and bounds["min"].z - tolerance <= point.z <= bounds["max"].z + tolerance
        ):
            inside += 1
    pose_height = max(ys) - min(ys) if ys else 0.0
    return (
        inside / float(len(positions)) >= 0.95
        # Mapped HIK rigs often omit the auxiliary head-tip/root anchors used
        # by the full studio skeleton, so their verified body anchors can span
        # slightly less than 80% of the mesh while still covering pelvis-to-ankle.
        and 0.75 <= pose_height / height <= 1.15
    )


def tag_pose_metadata(root_joint: str, pose_type: str, pose_angle_degrees: float) -> None:
    _set_string_attr(root_joint, POSE_ATTR, pose_type)
    _set_float_attr(root_joint, POSE_ANGLE_ATTR, pose_angle_degrees)


def delete_existing_generated_skeleton(root_name: str = "origin") -> None:
    if not cmds.objExists(root_name):
        return
    if not _is_generated_joint(root_name):
        cmds.error(
            "Refusing to delete existing joint '{0}' because it was not created by joint_placer.".format(root_name)
        )
    cmds.delete(root_name)


def create_joint(name: str, position: Vector3, parent: Optional[str] = None, radius: float = 1.0) -> str:
    if cmds.objExists(name):
        if _is_generated_joint(name):
            cmds.delete(name)
        else:
            cmds.error(
                "Refusing to replace existing node '{0}' because it was not created by joint_placer.".format(name)
            )

    cmds.select(clear=True)
    joint = cmds.joint(name=name, position=position, radius=radius)
    _tag_generated_joint(joint)

    if parent and cmds.objExists(parent):
        cmds.parent(joint, parent)

    return joint


def orient_skeleton(root_joint: str) -> None:
    if not root_joint or not cmds.objExists(root_joint):
        return

    cmds.select(root_joint, hierarchy=True)
    try:
        cmds.joint(
            edit=True,
            orientJoint="xyz",
            secondaryAxisOrient="yup",
            children=True,
            zeroScaleOrient=True,
        )
    except Exception as exc:
        cmds.warning("[joint_placer] Joint orient failed: {0}".format(exc))


def _world_align_joint_preserving_children(joint: str) -> None:
    if not joint or not cmds.objExists(joint):
        return

    children = cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []
    detached_children = []
    for child in children:
        world_matrix = cmds.xform(child, query=True, worldSpace=True, matrix=True)
        # Reparenting changes a long DAG path immediately. Keep Maya's returned
        # path rather than attempting to reuse the now-invalid original path.
        detached = cmds.parent(child, world=True)[0]
        detached_children.append((detached, world_matrix))

    for attr in ("jointOrient", "rotate"):
        for axis in ("X", "Y", "Z"):
            plug = "{0}.{1}{2}".format(joint, attr, axis)
            if cmds.objExists(plug):
                try:
                    cmds.setAttr(plug, 0.0)
                except Exception:
                    pass

    for child, world_matrix in detached_children:
        if cmds.objExists(child):
            reparented = cmds.parent(child, joint)[0]
            cmds.xform(reparented, worldSpace=True, matrix=world_matrix)


def world_align_origin_and_pelvis(root_joint: str) -> None:
    _world_align_joint_preserving_children(root_joint)
    pelvis_children = cmds.listRelatives(root_joint, children=True, type="joint", fullPath=False) or []
    for child in pelvis_children:
        if _short_name(child) == "pelvis":
            _world_align_joint_preserving_children(child)
            return


def zero_origin_translation_preserving_children(root_joint: str) -> None:
    """Put the rig-space origin at world zero without moving the skeleton."""
    root_joint = (cmds.ls(root_joint, long=True) or [root_joint])[0]
    children = cmds.listRelatives(root_joint, children=True, fullPath=True) or []
    child_world_matrices = [
        (child, cmds.xform(child, query=True, worldSpace=True, matrix=True))
        for child in children
    ]
    cmds.xform(root_joint, worldSpace=True, translation=(0.0, 0.0, 0.0))
    for child, world_matrix in child_world_matrices:
        if cmds.objExists(child):
            cmds.xform(child, worldSpace=True, matrix=world_matrix)


def build_skeleton_from_points(
    points: Dict[str, Vector3],
    root_name: str = "origin",
    orient: bool = True,
    replace_existing: bool = True,
    pose_type: str = "unknown",
    pose_angle_degrees: float = 0.0,
) -> str:
    if replace_existing:
        delete_existing_generated_skeleton(root_name)

    created = {}

    for name in BUILD_ORDER:
        if name not in points:
            continue
        parent = PARENT_MAP.get(name)
        created_parent = created.get(parent) if parent else None
        created[name] = create_joint(name, points[name], parent=created_parent)

    root_joint = created.get(root_name, root_name)

    if orient:
        orient_skeleton(root_joint)

    world_align_origin_and_pelvis(root_joint)
    zero_origin_translation_preserving_children(root_joint)
    tag_pose_metadata(root_joint, pose_type, pose_angle_degrees)

    return root_joint


def make_hik_maps_from_root(root_joint: str) -> Tuple[dict, dict]:
    body_joint_map = setup_hik.guess_joint_map_from_root(root_joint)
    face_joint_map = setup_hik.populate_default_face_map_from_scene()
    return body_joint_map, face_joint_map


CORE_HIK_SLOTS = (
    "Reference",
    "Hips",
    "Spine",
    "Spine1",
    "Spine2",
    "Spine3",
    "Neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
)


def validate_body_joint_map(body_joint_map: dict, required_slots: Iterable[str] = CORE_HIK_SLOTS) -> List[str]:
    missing = []
    for slot in required_slots:
        joint = (body_joint_map.get(slot) or {}).get("joint")
        if not joint or not cmds.objExists(joint):
            missing.append(slot)
    return missing


def create_guides_from_points(
    points: Dict[str, Vector3],
    group_name: str = "auto_joint_guides_grp",
    confidence: Optional[Dict[str, float]] = None,
    outside_joints: Optional[Iterable[str]] = None,
) -> List[str]:
    """Create or update color-coded guides without rebuilding the DAG."""
    group_matches = cmds.ls(group_name, long=True, type="transform") or []
    group = group_matches[0] if group_matches else cmds.group(
        empty=True, name=group_name
    )
    confidence = confidence or {}
    outside = set(outside_joints or [])

    existing = {}
    for child in cmds.listRelatives(
        group, children=True, type="transform", fullPath=True
    ) or []:
        shapes = cmds.listRelatives(child, shapes=True, type="locator") or []
        if shapes:
            existing[_short_name(child)] = child

    locators = []
    desired_names = {
        "{0}_guide".format(name) for name in BUILD_ORDER if name in points
    }
    try:
        viewport_was_suspended = bool(cmds.refresh(query=True, suspend=True))
    except Exception:
        viewport_was_suspended = False
    if not viewport_was_suspended:
        try:
            cmds.refresh(suspend=True)
        except Exception:
            pass
    try:
        for name in BUILD_ORDER:
            if name not in points:
                continue
            guide_name = "{0}_guide".format(name)
            loc = existing.get(guide_name)
            if not loc:
                loc = cmds.spaceLocator(name=guide_name)[0]
                loc = cmds.parent(loc, group)[0]
            cmds.xform(loc, worldSpace=True, translation=points[name])
            score = float(confidence.get(name, 0.0))
            verified = name not in outside
            if not cmds.objExists(loc + ".placementConfidence"):
                cmds.addAttr(
                    loc,
                    longName="placementConfidence",
                    attributeType="double",
                    minValue=0.0,
                    maxValue=1.0,
                )
            if not cmds.objExists(loc + ".placementVerifiedInside"):
                cmds.addAttr(
                    loc,
                    longName="placementVerifiedInside",
                    attributeType="bool",
                )
            cmds.setAttr("{0}.placementConfidence".format(loc), score)
            cmds.setAttr("{0}.placementVerifiedInside".format(loc), verified)
            shapes = cmds.listRelatives(loc, shapes=True, fullPath=True) or []
            color = 13 if not verified else (17 if score < 0.65 else 14)
            for shape in shapes:
                cmds.setAttr("{0}.overrideEnabled".format(shape), True)
                cmds.setAttr("{0}.overrideColor".format(shape), color)
            locators.append(loc)

        stale = [
            child for short_name, child in existing.items()
            if short_name not in desired_names
        ]
        if stale:
            cmds.delete(stale)
    finally:
        if not viewport_was_suspended:
            try:
                cmds.refresh(suspend=False)
            except Exception:
                pass

    return locators


def delete_auto_joint_guides() -> List[str]:
    """Delete only the temporary guide hierarchy owned by joint placement."""
    groups = cmds.ls("auto_joint_guides_grp", long=True, type="transform") or []
    removed = list(groups)
    if groups:
        cmds.delete(groups)
    return removed


def _template_namespace_prefix(namespace: str) -> str:
    value = str(namespace or "").strip().strip(":")
    return "{0}:".format(value) if value else ""


def _find_template_joint(template_name: str, namespace: str = "") -> Optional[str]:
    matches = cmds.ls(
        "{0}{1}".format(_template_namespace_prefix(namespace), template_name),
        type="joint",
        long=True,
    ) or []
    return matches[0] if len(matches) == 1 else None


def is_studio_template_skeleton(root_joint: str, namespace: str = "") -> bool:
    if not root_joint or not cmds.objExists(root_joint):
        return False
    descendants = set(cmds.listRelatives(root_joint, ad=True, type="joint", fullPath=True) or [])
    descendants.add((cmds.ls(root_joint, long=True) or [root_joint])[0])
    for template_name in TEMPLATE_CORE_JOINTS.values():
        joint = _find_template_joint(template_name, namespace=namespace)
        if not joint or joint not in descendants:
            return False
    for template_name in HIGH_RES_TEMPLATE_SIGNATURE:
        joint = _find_template_joint(template_name, namespace=namespace)
        if not joint or joint not in descendants:
            return False
    return True


def _mapped_joint(joint_map: Optional[dict], slot: str) -> Optional[str]:
    value = (joint_map or {}).get(slot)
    if isinstance(value, dict):
        value = value.get("joint")
    elif isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    value = str(value or "").strip()
    matches = cmds.ls(value, type="joint", long=True) or []
    return matches[0] if len(matches) == 1 else None


def placement_frame_from_mapping(joint_map: Optional[dict]) -> PlacementFrame:
    """Infer character axes from mapped hips/head and left/right limbs."""
    hips = _mapped_joint(joint_map, "Hips")
    head = _mapped_joint(joint_map, "Head")
    left = _mapped_joint(joint_map, "LeftHand") or _mapped_joint(joint_map, "LeftArm")
    right = _mapped_joint(joint_map, "RightHand") or _mapped_joint(joint_map, "RightArm")
    if not hips or not head or not left or not right:
        return PlacementFrame()
    hips_point = cmds.xform(hips, query=True, worldSpace=True, translation=True)
    head_point = cmds.xform(head, query=True, worldSpace=True, translation=True)
    left_point = cmds.xform(left, query=True, worldSpace=True, translation=True)
    right_point = cmds.xform(right, query=True, worldSpace=True, translation=True)
    up_delta = [head_point[index] - hips_point[index] for index in range(3)]
    up_axis = max(range(3), key=lambda index: abs(up_delta[index]))
    remaining = [index for index in range(3) if index != up_axis]
    side_delta = [left_point[index] - right_point[index] for index in range(3)]
    side_axis = max(remaining, key=lambda index: abs(side_delta[index]))
    depth_axis = next(index for index in range(3) if index not in (up_axis, side_axis))
    return PlacementFrame(
        side_axis=side_axis,
        up_axis=up_axis,
        depth_axis=depth_axis,
        side_sign=1.0 if side_delta[side_axis] >= 0.0 else -1.0,
        up_sign=1.0 if up_delta[up_axis] >= 0.0 else -1.0,
        depth_sign=1.0,
    )


def _logical_mesh_bounds(mesh: str, frame: PlacementFrame) -> Dict[str, object]:
    bbox = cmds.exactWorldBoundingBox(_as_mesh_transform(mesh))
    world_min = (bbox[0], bbox[1], bbox[2])
    world_max = (bbox[3], bbox[4], bbox[5])
    logical_corners = [
        frame.world_to_logical((x, y, z))
        for x in (world_min[0], world_max[0])
        for y in (world_min[1], world_max[1])
        for z in (world_min[2], world_max[2])
    ]
    minimum = om.MVector(*(min(point[index] for point in logical_corners) for index in range(3)))
    maximum = om.MVector(*(max(point[index] for point in logical_corners) for index in range(3)))
    center = (minimum + maximum) * 0.5
    return {
        "min": minimum,
        "max": maximum,
        "center": center,
        "width": maximum.x - minimum.x,
        "height": maximum.y - minimum.y,
        "depth": maximum.z - minimum.z,
    }


def mapped_anatomical_joints(joint_map: Optional[dict]) -> Dict[str, str]:
    """Resolve the active HIK mapping into placement roles.

    Spine roles are distributed across the available HIK spine slots, allowing
    a user hierarchy to contain one through four mapped spine joints.
    """
    mapped = {}
    for slot, canonical_name in HIK_CORE_PLACEMENT_SLOTS.items():
        joint = _mapped_joint(joint_map, slot)
        if joint:
            mapped[canonical_name] = joint

    spine_joints = [
        _mapped_joint(joint_map, slot)
        for slot in ("Spine", "Spine1", "Spine2", "Spine3")
    ]
    spine_joints = [joint for joint in spine_joints if joint]
    spine_targets = {
        1: ("spine_02",),
        2: ("spine_01", "spine_03"),
        3: ("spine_01", "spine_02", "spine_04"),
        4: ("spine_01", "spine_02", "spine_03", "spine_04"),
    }.get(len(spine_joints), ())
    for canonical_name, joint in zip(spine_targets, spine_joints):
        mapped[canonical_name] = joint
    return mapped


def mapped_hierarchy_missing_slots(joint_map: Optional[dict]) -> List[str]:
    return [slot for slot in REQUIRED_MAPPED_PLACEMENT_SLOTS if not _mapped_joint(joint_map, slot)]


def mapped_hierarchy_requested(joint_map: Optional[dict]) -> bool:
    return any(_mapped_joint(joint_map, slot) for slot in REQUIRED_MAPPED_PLACEMENT_SLOTS)


def _common_mapped_root(joints: Iterable[str]) -> Optional[str]:
    paths = [
        (cmds.ls(joint, long=True) or [joint])[0].split("|")[1:]
        for joint in joints
        if joint and cmds.objExists(joint)
    ]
    if not paths:
        return None
    common = []
    for components in zip(*paths):
        if len(set(components)) != 1:
            break
        common.append(components[0])
    while common:
        candidate = "|" + "|".join(common)
        if cmds.objExists(candidate) and cmds.nodeType(candidate) == "joint":
            return candidate
        common.pop()
    # Fall back to the highest joint ancestor of the first mapped joint.
    candidate = (cmds.ls(next(iter(joints)), long=True) or [None])[0]
    highest = candidate
    while candidate:
        parent = cmds.listRelatives(candidate, parent=True, type="joint", fullPath=True) or []
        if not parent:
            break
        highest = candidate = parent[0]
    return highest


def mapped_studio_template_namespace(joint_map: Optional[dict]) -> Optional[str]:
    """Return the namespace when a mapping points at the studio template.

    The UI auto-populates its HIK mapping from any skeleton in the scene. A
    loaded studio template must still use the specialized studio fitting pass;
    treating it as an arbitrary mapped hierarchy skips its digit, twist, foot,
    and orientation contracts.
    """
    mapped = mapped_anatomical_joints(joint_map)
    root = _common_mapped_root(mapped.values()) if mapped else None
    if not root:
        return None
    short_name = _short_name(root)
    namespace = short_name.rsplit(":", 1)[0] if ":" in short_name else ""
    return namespace if is_studio_template_skeleton(root, namespace) else None


def _mapped_finger_chains(joint_map: Optional[dict]) -> List[List[str]]:
    chains = []
    for side in ("Left", "Right"):
        for digit in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
            chain = [
                _mapped_joint(joint_map, "{0}Hand{1}{2}".format(side, digit, index))
                for index in range(1, 5)
            ]
            chain = [joint for joint in chain if joint]
            if len(chain) >= 3:
                chains.append(chain)
    return chains


def _multiply_joint_local_translations(joints: Iterable[str], multiplier: float) -> None:
    if abs(multiplier - 1.0) <= 1.0e-8:
        return
    for joint in joints:
        if not joint or not cmds.objExists(joint):
            continue
        for axis in "XYZ":
            plug = "{0}.translate{1}".format(joint, axis)
            if not cmds.objExists(plug):
                continue
            try:
                if cmds.getAttr(plug, lock=True) or cmds.listConnections(
                    plug, source=True, destination=False
                ):
                    continue
                cmds.setAttr(plug, cmds.getAttr(plug) * multiplier)
            except RuntimeError:
                continue


def _orient_reverse_foot_ik_chain(side: str, namespace: str) -> Dict[str, Vector3]:
    """Make the distal RFL IK offsets signed local-X only and coplanar."""
    toe_tip = _find_template_joint("{0}_toeTip_RFL".format(side), namespace)
    toe = _find_template_joint("{0}_toe_RFL".format(side), namespace)
    if not toe:
        # Older studio templates use ``ball`` for the same reverse-foot role.
        # The rig builder deliberately supports both names, so the post-pose
        # snap must do the same or those pivots are positioned but never aimed.
        toe = _find_template_joint("{0}_ball_RFL".format(side), namespace)
    ankle = _find_template_joint("{0}_ankle_RFL".format(side), namespace)
    chain = (toe_tip, toe, ankle)
    if not all(chain):
        return {}
    aim_sign = 1.0 if side == "l" else -1.0
    offsets = {}
    for parent, child in zip(chain[:-1], chain[1:]):
        parent_position = om.MVector(*cmds.xform(
            parent, query=True, worldSpace=True, translation=True
        ))
        child_position = om.MVector(*cmds.xform(
            child, query=True, worldSpace=True, translation=True
        ))
        length = (child_position - parent_position).length()
        _orient_joint_x_to_child(
            parent,
            child,
            world_up=(0.0, aim_sign, 0.0),
            aim_sign=aim_sign,
        )
        cmds.setAttr(child + ".translate", length * aim_sign, 0.0, 0.0)
        offsets[_short_name(child)] = tuple(
            float(cmds.getAttr("{0}.translate{1}".format(child, axis)))
            for axis in "XYZ"
        )
    return offsets


def _fit_reverse_foot_chain(
    side: str,
    namespace: str,
    points: Dict[str, Vector3],
    desired_scale: float,
    ground_pivots: Optional[Dict[str, Vector3]] = None,
) -> bool:
    """Snap one reverse-foot helper chain after the deformation T-pose is final."""
    heel = _find_template_joint("{0}_heel_RFL".format(side), namespace)
    ankle_rfl = _find_template_joint("{0}_ankle_RFL".format(side), namespace)
    if not heel or not ankle_rfl:
        return False
    required = ("ankle", "toe", "toeTip")
    if not all(points.get("{0}_{1}".format(side, name)) for name in required):
        return False
    current_scale = 1.0
    if cmds.attributeQuery(RFL_SCALE_ATTR, node=heel, exists=True):
        current_scale = float(
            cmds.getAttr("{0}.{1}".format(heel, RFL_SCALE_ATTR)) or 1.0
        )
    chain = [heel] + (
        cmds.listRelatives(heel, ad=True, type="joint", fullPath=True) or []
    )
    _multiply_joint_local_translations(
        chain[1:], float(desired_scale) / max(current_scale, 1.0e-6)
    )
    _set_float_attr(heel, RFL_SCALE_ATTR, float(desired_scale))
    target_ankle = points["{0}_ankle".format(side)]
    current_ankle = cmds.xform(
        ankle_rfl, query=True, worldSpace=True, translation=True
    )
    heel_position = cmds.xform(
        heel, query=True, worldSpace=True, translation=True
    )
    delta = [target_ankle[index] - current_ankle[index] for index in range(3)]
    cmds.xform(
        heel,
        worldSpace=True,
        translation=[heel_position[index] + delta[index] for index in range(3)],
    )
    ground_y = float(points["{0}_toeTip".format(side)][1])
    for ground_suffix in ("heel_RFL", "outerBank_RFL", "innerBank_RFL"):
        ground_joint = _find_template_joint(
            "{0}_{1}".format(side, ground_suffix), namespace
        )
        if not ground_joint:
            continue
        ground_position = cmds.xform(
            ground_joint, query=True, worldSpace=True, translation=True
        )
        pivot_name = ground_suffix.rsplit("_RFL", 1)[0]
        fitted_position = (ground_pivots or {}).get(pivot_name)
        if fitted_position:
            ground_position = list(fitted_position)
        else:
            ground_position[1] = ground_y
        cmds.xform(
            ground_joint, worldSpace=True, translation=ground_position
        )
    for suffixes, point_name in (
        (("toeTip_RFL",), "toeTip"),
        (("toe_RFL", "ball_RFL"), "toe"),
        (("ankle_RFL",), "ankle"),
    ):
        joint = None
        for suffix in suffixes:
            joint = _find_template_joint(
                "{0}_{1}".format(side, suffix), namespace
            )
            if joint:
                break
        target = points["{0}_{1}".format(side, point_name)]
        if joint:
            cmds.xform(joint, worldSpace=True, translation=target)
    _orient_reverse_foot_ik_chain(side, namespace)
    return True


def _reverse_foot_source_mesh(root: str, points: Dict[str, Vector3]) -> str:
    """Resolve the mesh used by Joint Placer, with a scene fallback for old rigs."""
    if cmds.attributeQuery(PLACEMENT_MESH_MESSAGE_ATTR, node=root, exists=True):
        connected = cmds.listConnections(
            "{0}.{1}".format(root, PLACEMENT_MESH_MESSAGE_ATTR),
            source=True,
            destination=False,
            shapes=False,
        ) or []
        if connected:
            return _as_mesh_transform(connected[0])
    if cmds.attributeQuery(PLACEMENT_MESH_ATTR, node=root, exists=True):
        stored_mesh = cmds.getAttr("{0}.{1}".format(root, PLACEMENT_MESH_ATTR)) or ""
        if stored_mesh and cmds.objExists(stored_mesh):
            try:
                return _as_mesh_transform(stored_mesh)
            except RuntimeError:
                pass

    # Skeletons made before the source-mesh attribute was introduced still need
    # a useful T-pose. Prefer the densest mesh whose current bounds contain the
    # deformation foot points; this normally selects the placed body over props.
    foot_points = list(points.values())
    candidates = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        mesh = parents[0]
        try:
            bbox = cmds.exactWorldBoundingBox(mesh)
            diagonal = om.MVector(
                bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]
            ).length()
            margin = max(diagonal * 0.01, 1.0e-4)
            if not all(
                bbox[0] - margin <= point[0] <= bbox[3] + margin
                and bbox[1] - margin <= point[1] <= bbox[4] + margin
                and bbox[2] - margin <= point[2] <= bbox[5] + margin
                for point in foot_points
            ):
                continue
            vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
            candidates.append((vertex_count, diagonal, mesh))
        except (RuntimeError, TypeError, ValueError):
            continue
    return max(candidates, default=(0, 0.0, ""))[2]


def _solve_reverse_foot_ground_pivots(
    query: "MeshInteriorQuery",
    side: str,
    ankle: Vector3,
    toe: Vector3,
    toe_tip: Vector3,
    ground_y: float = 0.0,
) -> Dict[str, Vector3]:
    """Fit heel and bank pivots to the actual local sole footprint.

    The solve uses a horizontal foot basis rather than template offsets or
    channel values. It therefore remains stable after T-pose rotations and on
    characters with different foot sizes.
    """
    ankle_vector = om.MVector(*ankle)
    toe_vector = om.MVector(*toe)
    tip_vector = om.MVector(*toe_tip)
    forward = tip_vector - ankle_vector
    forward.y = 0.0
    if forward.length() <= 1.0e-8:
        forward = toe_vector - ankle_vector
        forward.y = 0.0
    if forward.length() <= 1.0e-8:
        return {}
    forward.normalize()

    lateral = om.MVector(0.0, 1.0, 0.0) ^ forward
    center_to_ankle = ankle_vector - query.bounds["center"]
    center_to_ankle.y = 0.0
    if lateral * center_to_ankle < 0.0:
        lateral *= -1.0
    lateral.normalize()

    foot_length = max(
        abs((tip_vector - ankle_vector) * forward),
        abs((toe_vector - ankle_vector) * forward),
        query.diagonal * 0.025,
    )
    points = query.mesh_fn.getPoints(om.MSpace.kWorld)
    samples = []
    for point in points:
        delta = om.MVector(point) - ankle_vector
        longitudinal = delta * forward
        sideways = delta * lateral
        if (
            -foot_length * 0.65 <= longitudinal <= foot_length * 1.18
            and abs(sideways) <= foot_length * 0.55
            and point.y <= ankle[1] + foot_length * 0.20
        ):
            samples.append((float(point.y), longitudinal, sideways))
    if len(samples) < 8:
        return {}

    sole_y = min(sample[0] for sample in samples)
    contact_height = max(foot_length * 0.025, query.diagonal * 0.001)
    contacts = [sample for sample in samples if sample[0] <= sole_y + contact_height]
    if len(contacts) < 4:
        contacts = sorted(samples, key=lambda sample: sample[0])[:max(4, len(samples) // 20)]

    rear = min(sample[1] for sample in contacts)
    heel_band = [
        sample for sample in contacts
        if sample[1] <= rear + foot_length * 0.055
    ] or contacts
    heel_forward = sum(sample[1] for sample in heel_band) / len(heel_band)
    # Reverse-foot roll needs a little clearance behind the visible heel rather
    # than sitting directly under its curved underside.
    heel_forward -= max(foot_length * 0.025, query.diagonal * 0.0005)
    heel_side = sum(sample[2] for sample in heel_band) / len(heel_band)

    toe_forward = (toe_vector - ankle_vector) * forward
    # Bank at the ball of the foot, where the low-foot silhouette is widest,
    # rather than blindly using the toe-joint depth.  The latter sits too far
    # forward on broad stylized feet and puts both pivots inside the sidewalls.
    low_foot_samples = [
        sample for sample in samples
        if sample[0] <= sole_y + foot_length * 0.16
    ]
    search_start = foot_length * 0.35
    search_end = min(toe_forward, foot_length * 0.78)
    width_candidates = []
    if search_end > search_start:
        for index in range(21):
            amount = index / 20.0
            candidate_forward = search_start + (
                (search_end - search_start) * amount
            )
            candidate_band = [
                sample for sample in low_foot_samples
                if abs(sample[1] - candidate_forward) <= foot_length * 0.045
            ]
            if len(candidate_band) < 4:
                continue
            candidate_width = (
                max(sample[2] for sample in candidate_band)
                - min(sample[2] for sample in candidate_band)
            )
            width_candidates.append((candidate_width, candidate_forward))
    bank_forward = toe_forward
    if width_candidates:
        widest = max(item[0] for item in width_candidates)
        widest_plateau = [
            item[1] for item in width_candidates
            if item[0] >= widest * 0.99
        ]
        bank_forward = sum(widest_plateau) / len(widest_plateau)
    bank_band = [
        sample for sample in low_foot_samples
        if abs(sample[1] - bank_forward) <= foot_length * 0.045
    ]
    if len(bank_band) < 4:
        bank_band = [
            sample for sample in samples
            if abs(sample[1] - toe_forward) <= foot_length * 0.16
            and sample[0] <= sole_y + foot_length * 0.22
        ]
    if len(bank_band) < 2:
        return {}

    inner_edge = min(sample[2] for sample in bank_band)
    outer_edge = max(sample[2] for sample in bank_band)
    bank_width = max(outer_edge - inner_edge, query.tolerance * 20.0)
    # The two banks serve different practical roles. The inner pivot can sit
    # slightly under the sole, avoiding an over-wide hierarchy near the arch.
    # The outer roll fulcrum must clear the lateral silhouette or the foot will
    # visibly collapse into itself when banking outward.
    edge_inset = max(bank_width * 0.10, query.diagonal * 0.0002)
    edge_clearance = max(bank_width * 0.0125, query.diagonal * 0.0002)
    inner_side = inner_edge + edge_inset
    outer_side = outer_edge + edge_clearance

    def _world_position(longitudinal: float, sideways: float) -> Vector3:
        position = ankle_vector + (forward * longitudinal) + (lateral * sideways)
        return (float(position.x), float(ground_y), float(position.z))

    return {
        "heel": _world_position(heel_forward, heel_side),
        "innerBank": _world_position(bank_forward, inner_side),
        "outerBank": _world_position(bank_forward, outer_side),
    }


def _mirror_reverse_foot_ground_pivots_if_symmetric(
    ground_pivots: Dict[str, Dict[str, Vector3]],
    center_x: float,
) -> bool:
    """Mirror the left footprint unless the measured right mesh differs materially."""
    left = ground_pivots.get("l") or {}
    right = ground_pivots.get("r") or {}
    labels = ("heel", "innerBank", "outerBank")
    if not all(label in left and label in right for label in labels):
        return False
    mirrored = {
        label: (
            (2.0 * float(center_x)) - left[label][0],
            left[label][1],
            left[label][2],
        )
        for label in labels
    }
    deviations = [
        (om.MVector(*right[label]) - om.MVector(*mirrored[label])).length()
        for label in labels
    ]
    # Judge symmetry against the local bank span, not total foot length. A
    # modest-looking whole-foot error can be a clearly visible lateral offset
    # at the contact pivots. Preserve independent mesh fits once that local
    # footprint differs materially.
    reference_width = max(
        (
            om.MVector(*left["innerBank"])
            - om.MVector(*left["outerBank"])
        ).length(),
        1.0e-6,
    )
    if max(deviations) > reference_width * 0.05:
        return False
    ground_pivots["r"] = mirrored
    return True


def snap_reverse_foot_helpers_to_deformation_skeleton(
    namespace: str = "",
    sides: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """Snap RFL helpers to the finalized deformation-leg T-pose.

    Initial anatomical placement and skin import deliberately leave the detached
    reverse-foot helpers untouched. The T-pose pass first straightens the legs in
    front view and grounds the toe tips, then calls this function.
    """
    normalize_rfl_joint_suffixes(namespace=namespace)
    root = _find_template_joint("origin", namespace)
    if not root:
        return {"namespace": namespace, "snapped_sides": [], "missing": ["origin"]}
    studio_template = is_studio_template_skeleton(root, namespace=namespace)
    desired_scale = 1.0
    if cmds.attributeQuery(TEMPLATE_SCALE_ATTR, node=root, exists=True):
        desired_scale = float(
            cmds.getAttr("{0}.{1}".format(root, TEMPLATE_SCALE_ATTR)) or 1.0
        )
    requested_sides = tuple(dict.fromkeys(
        str(side).lower() for side in (sides or ("l", "r"))
        if str(side).lower() in ("l", "r")
    ))
    if not requested_sides:
        return {"namespace": namespace, "snapped_sides": [], "missing": []}
    # Mapped/non-studio skeletons can use the same complete RFL hierarchy. The
    # old studio-only guard caused helpers on rigs such as Coolaid to remain at
    # their template positions even after the deformation foot was corrected.
    available_sides = tuple(
        side for side in requested_sides
        if _find_template_joint("{0}_heel_RFL".format(side), namespace)
        and _find_template_joint("{0}_toeTip_RFL".format(side), namespace)
        and (
            _find_template_joint("{0}_toe_RFL".format(side), namespace)
            or _find_template_joint("{0}_ball_RFL".format(side), namespace)
        )
        and _find_template_joint("{0}_ankle_RFL".format(side), namespace)
    )
    if not available_sides:
        return {
            "namespace": namespace,
            "snapped_sides": [],
            "missing": ["complete_reverse_foot_hierarchy"],
            "skeleton_type": "studio" if studio_template else "mapped",
        }
    requested_sides = available_sides
    points = {}
    missing = []
    for side in requested_sides:
        for name in ("ankle", "toe", "toeTip"):
            joint = _find_template_joint("{0}_{1}".format(side, name), namespace)
            if not joint:
                missing.append("{0}_{1}".format(side, name))
                continue
            points["{0}_{1}".format(side, name)] = tuple(
                cmds.xform(joint, query=True, worldSpace=True, translation=True)
            )
    source_mesh = _reverse_foot_source_mesh(root, points)
    query = None
    if source_mesh:
        clear_mesh_query_cache()
        query = _cached_mesh_interior_query(source_mesh)
    ground_pivots = {}
    for side in requested_sides:
        if query and all(
            points.get("{0}_{1}".format(side, name))
            for name in ("ankle", "toe", "toeTip")
        ):
            ground_pivots[side] = _solve_reverse_foot_ground_pivots(
                query,
                side,
                points["{0}_ankle".format(side)],
                points["{0}_toe".format(side)],
                points["{0}_toeTip".format(side)],
            )
    mirrored_ground_pivots = bool(
        query
        and set(requested_sides) == {"l", "r"}
        and _mirror_reverse_foot_ground_pivots_if_symmetric(
            ground_pivots,
            cmds.xform(root, query=True, worldSpace=True, translation=True)[0],
        )
    )
    snapped = [
        side for side in requested_sides
        if _fit_reverse_foot_chain(
            side,
            namespace,
            points,
            desired_scale,
            ground_pivots=ground_pivots.get(side),
        )
    ]
    if snapped:
        _set_string_attr(root, RFL_SNAP_STAGE_ATTR, "post_t_pose")
    return {
        "namespace": namespace,
        "skeleton_type": "studio" if studio_template else "mapped",
        "snapped_sides": snapped,
        "missing": missing,
        "desired_scale": desired_scale,
        "source_mesh": source_mesh,
        "ground_pivots": ground_pivots,
        "mirrored_ground_pivots": mirrored_ground_pivots,
    }


def snap_all_reverse_foot_helpers_after_t_pose() -> Dict[str, object]:
    """Run the post-T-pose RFL stage for every studio skeleton in the scene."""
    reports = []
    seen_namespaces = set()
    for joint in cmds.ls(type="joint", long=True) or []:
        short_name = _short_name(joint)
        if short_name.split(":")[-1] != "origin":
            continue
        namespace = short_name.rsplit(":", 1)[0] if ":" in short_name else ""
        if namespace in seen_namespaces:
            continue
        seen_namespaces.add(namespace)
        report = snap_reverse_foot_helpers_to_deformation_skeleton(namespace)
        if report.get("snapped_sides"):
            reports.append(report)
    return {
        "stage": "post_t_pose",
        "skeleton_count": len(reports),
        "reports": reports,
    }


def _joint_world_axes(joint: str) -> Dict[str, om.MVector]:
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    return {
        "x": om.MVector(matrix[0], matrix[1], matrix[2]).normal(),
        "y": om.MVector(matrix[4], matrix[5], matrix[6]).normal(),
        "z": om.MVector(matrix[8], matrix[9], matrix[10]).normal(),
    }


def _rotate_vector_between_directions(
    vector: om.MVector,
    source_direction: om.MVector,
    target_direction: om.MVector,
) -> om.MVector:
    """Shortest-arc transport of a vector from one aim direction to another."""
    source = om.MVector(source_direction)
    target = om.MVector(target_direction)
    if source.length() <= 1.0e-8 or target.length() <= 1.0e-8:
        return om.MVector(vector)
    source.normalize()
    target.normalize()
    cosine = max(-1.0, min(1.0, float(source * target)))
    if cosine > 1.0 - 1.0e-10:
        return om.MVector(vector)
    axis = source ^ target
    if axis.length() <= 1.0e-8:
        axis = source ^ om.MVector(0.0, 1.0, 0.0)
        if axis.length() <= 1.0e-8:
            axis = source ^ om.MVector(0.0, 0.0, 1.0)
    axis.normalize()
    sine = math.sqrt(max(0.0, 1.0 - (cosine * cosine)))
    value = om.MVector(vector)
    return (
        value * cosine
        + (axis ^ value) * sine
        + axis * ((axis * value) * (1.0 - cosine))
    )


def solve_reference_joint_roll_vectors(
    mesh: str,
    desired_x_by_name: Dict[str, om.MVector],
) -> Tuple[Dict[str, om.MVector], List[str]]:
    """Transfer approved local-Y roll while retaining target positions/X aims.

    The production rigs agree on a relative arm and digit frame.  Positions may
    differ substantially between characters, so copying Euler values is not a
    valid comparison.  Instead, rotate each approved reference frame by the
    shortest arc from its signed local X to the target bone's signed local X,
    then average the transported local-Y vectors.  This changes roll only;
    target pivots and the target bone direction remain authoritative.
    """
    if not mesh or not desired_x_by_name:
        return {}, []
    mesh = _as_mesh_transform(mesh)
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    ranked = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if entry.get("joint_axes")
    ]
    topology_matches = [
        item for item in ranked
        if int((item[1].get("topology") or {}).get("vertex_count") or 0)
        == vertex_count
        and int((item[1].get("topology") or {}).get("face_count") or 0)
        == face_count
    ]
    selected = (topology_matches or ranked)[:5]
    samples_by_name = {name: [] for name in desired_x_by_name}
    for distance, reference in selected:
        joint_axes = reference.get("joint_axes") or {}
        weight = 1.0 / max(0.01 + float(distance), 1.0e-6)
        for name, desired_x in desired_x_by_name.items():
            # Approved character rigs use a signed-X mirror convention: the
            # right frame is the left frame transformed as (x, -y, -z).  Some
            # historical atlas captures contain posed or rolled right fingers,
            # so consuming their right-side axes directly reproduces exactly
            # the mismatch this pass is meant to prevent.  The left side is the
            # canonical authored frame and the right is derived deterministically.
            mirrored_right = name.startswith("r_")
            reference_name = "l_" + name[2:] if mirrored_right else name
            axes = joint_axes.get(reference_name) or {}
            source_x = axes.get("x")
            source_y = axes.get("y")
            if source_x is None or source_y is None:
                continue
            if mirrored_right:
                source_x = (source_x[0], -source_x[1], -source_x[2])
                source_y = (source_y[0], -source_y[1], -source_y[2])
            transported = _rotate_vector_between_directions(
                om.MVector(*source_y),
                om.MVector(*source_x),
                desired_x,
            )
            target_x = om.MVector(desired_x).normal()
            transported -= target_x * (transported * target_x)
            if transported.length() <= 1.0e-8:
                continue
            transported.normalize()
            samples_by_name[name].append((transported, weight))

    result = {}
    for name, samples in samples_by_name.items():
        if not samples:
            continue
        # Roll is a rig standard, not a body-proportion measurement.  Select
        # the spherical medoid and reject distant captures so one malformed or
        # posed atlas (even the closest-shaped character) cannot dominate the
        # result.  Do not sign-flip samples: a 180-degree roll is a real error.
        medoid, _medoid_weight = max(
            samples,
            key=lambda candidate: sum(
                float(candidate[0] * other[0]) for other in samples
            ),
        )
        inliers = [
            (sample, weight) for sample, weight in samples
            if float(sample * medoid) >= 0.75
        ] or [(medoid, 1.0)]
        blended = om.MVector()
        for sample, _weight in inliers:
            blended += sample
        target_x = om.MVector(desired_x_by_name[name]).normal()
        blended -= target_x * (blended * target_x)
        if blended.length() <= 1.0e-8:
            continue
        blended.normalize()
        result[name] = blended
    return result, [str(entry.get("case_id") or "") for _distance, entry in selected]


def solve_template_joint_roll_vectors(
    desired_x_by_name: Dict[str, om.MVector],
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
) -> Dict[str, om.MVector]:
    """Transport each named joint's authored rig-template roll to its fitted X."""
    template_axes = extract_studio_template_joint_axes(template_path)
    result = {}
    for name, desired_x in desired_x_by_name.items():
        authored = template_axes.get(name) or {}
        source_x = authored.get("x")
        source_y = authored.get("y")
        if not source_x or not source_y:
            continue
        target_x = om.MVector(desired_x)
        if target_x.length() <= 1.0e-8:
            continue
        target_x.normalize()
        transported = _rotate_vector_between_directions(
            om.MVector(*source_y), om.MVector(*source_x), target_x
        )
        transported -= target_x * (transported * target_x)
        if transported.length() > 1.0e-8:
            result[name] = transported.normal()
    return result


def _reference_roll_basis(
    x_axis: om.MVector,
    reference_y: om.MVector,
) -> Tuple[om.MVector, om.MVector, om.MVector]:
    """Build a right-handed Maya basis from an exact aim and approved roll."""
    x_axis = om.MVector(x_axis).normal()
    y_axis = om.MVector(reference_y)
    y_axis -= x_axis * (y_axis * x_axis)
    if y_axis.length() <= 1.0e-8:
        raise RuntimeError("Approved joint roll is parallel to its bone aim.")
    y_axis.normalize()
    z_axis = x_axis ^ y_axis
    z_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()
    return x_axis, y_axis, z_axis


def _reference_z_basis(
    x_axis: om.MVector,
    reference_z: om.MVector,
) -> Tuple[om.MVector, om.MVector, om.MVector]:
    """Build a right-handed Maya basis from an exact aim and approved Z."""
    x_axis = om.MVector(x_axis).normal()
    z_axis = om.MVector(reference_z)
    z_axis -= x_axis * (z_axis * x_axis)
    if z_axis.length() <= 1.0e-8:
        raise RuntimeError("Approved joint Z is parallel to its bone aim.")
    z_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()
    z_axis = x_axis ^ y_axis
    z_axis.normalize()
    return x_axis, y_axis, z_axis


def _configure_preferred_bend_axis(
    joint: str,
    world_plane_normal: Vector3,
    plane_label: str,
) -> Optional[str]:
    """Record hinge metadata without inventing a preferred-angle pose."""
    if not joint or not cmds.objExists(joint):
        return None
    normal = om.MVector(*world_plane_normal)
    if normal.length() <= 1.0e-8:
        return None
    normal.normalize()
    axes = _joint_world_axes(joint)
    axis, _alignment = max(
        ((name, vector * normal) for name, vector in axes.items()),
        key=lambda item: abs(item[1]),
    )
    _set_string_attr(joint, BEND_AXIS_ATTR, axis)
    _set_string_attr(joint, BEND_PLANE_ATTR, plane_label)
    return axis


def capture_current_pose_as_preferred_angles(root: str) -> Dict[str, Tuple[float, float, float]]:
    """Store the completed placed pose as every joint's preferred angles.

    This must run after all placement and orientation cleanup.  Preferred
    angles are pose data, so deriving them from nominal prebend constants can
    disagree with the skeleton the artist is actually looking at (and can
    make an IK solve jump as soon as it is enabled).
    """
    captured = {}
    if not root or not cmds.objExists(root):
        return captured
    joints = [root] + (
        cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or []
    )
    for joint in joints:
        values = []
        for axis in "XYZ":
            rotate_plug = "{0}.rotate{1}".format(joint, axis)
            preferred_plug = "{0}.preferredAngle{1}".format(joint, axis)
            value = float(cmds.getAttr(rotate_plug))
            values.append(value)
            if not cmds.objExists(preferred_plug):
                continue
            try:
                cmds.setAttr(preferred_plug, value)
            except Exception:
                # A user-mapped skeleton may expose a driven or locked joint;
                # preserve placement rather than failing the whole operation.
                pass
        captured[_short_name(joint)] = tuple(values)
    return captured


def import_matching_skin_weights(
    mesh: str,
    export_dir: str = DEFAULT_SKIN_WEIGHT_DIR,
) -> Dict[str, object]:
    """Import exported weights when both files exactly match the mesh name."""
    mesh_name = _short_name(mesh)
    weight_dir = Path(export_dir).expanduser()
    xml_path = weight_dir / "{0}_weights.xml".format(mesh_name)
    json_path = weight_dir / "{0}_weights_influences.json".format(mesh_name)
    report = {
        "mesh": mesh_name,
        "directory": str(weight_dir).replace("\\", "/"),
        "matched": bool(xml_path.is_file() and json_path.is_file()),
        "imported": False,
    }
    if not report["matched"]:
        return report

    matches = cmds.ls(mesh_name, long=True, type="transform") or []
    if len(matches) != 1:
        report["error"] = "mesh name is not unique in the scene"
        cmds.warning(
            "[joint_placer] Matching skin weights were not imported for {0}: {1}.".format(
                mesh_name, report["error"]
            )
        )
        return report

    try:
        # Lazy import avoids loading the skinning UI stack when no matching
        # exported map exists, which keeps ordinary placement startup snappy.
        from maya_tools.Rigging import skinning_utils

        result = skinning_utils.import_skin_weights([mesh_name], str(weight_dir))
        report["result"] = result
        report["imported"] = mesh_name in (result.get("imported_meshes") or [])
        if not report["imported"]:
            report["error"] = "matching files were found but the importer skipped the mesh"
            cmds.warning(
                "[joint_placer] Matching skin weights were found for {0}, but import did not complete.".format(
                    mesh_name
                )
            )
    except Exception as exc:
        report["error"] = str(exc)
        cmds.warning(
            "[joint_placer] Could not import matching skin weights for {0}: {1}".format(
                mesh_name, exc
            )
        )
    return report


def _finger_plane_normal(joint: str, fallback: Vector3) -> Vector3:
    child_joints = cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []
    if not child_joints:
        return fallback
    child = child_joints[0]
    grandchild_joints = cmds.listRelatives(child, children=True, type="joint", fullPath=True) or []
    if not grandchild_joints:
        return fallback
    parent_position = om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
    child_position = om.MVector(*cmds.xform(child, query=True, worldSpace=True, translation=True))
    end_position = om.MVector(*cmds.xform(grandchild_joints[0], query=True, worldSpace=True, translation=True))
    normal = (child_position - parent_position) ^ (end_position - child_position)
    if normal.length() <= 1.0e-8:
        return fallback
    normal.normalize()
    return (normal.x, normal.y, normal.z)


def _finger_chain(root_joint: str) -> List[str]:
    chain = [root_joint]
    prefix = _short_name(root_joint).split(":")[-1].rsplit("_", 1)[0] + "_"
    current = root_joint
    while True:
        children = cmds.listRelatives(current, children=True, type="joint", fullPath=True) or []
        matching = [
            child for child in children
            if _short_name(child).split(":")[-1].startswith(prefix)
        ]
        if not matching:
            return chain
        current = matching[0]
        chain.append(current)


def _project_joint_chain_to_plane(chain: List[str]) -> float:
    """Project a chain onto its strongest authored plane and return prior deviation."""
    if len(chain) < 3:
        return 0.0
    positions = [
        om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
        for joint in chain
    ]
    chord = positions[-1] - positions[0]
    if chord.length() <= 1.0e-8:
        return 0.0
    normal_candidates = [chord ^ (point - positions[0]) for point in positions[1:-1]]
    normal = max(normal_candidates, key=lambda vector: vector.length(), default=om.MVector())
    if normal.length() <= 1.0e-8:
        return 0.0
    normal.normalize()
    offsets = [(point - positions[0]) * normal for point in positions]
    maximum_deviation = max(abs(offset) for offset in offsets)
    targets = [point - (normal * offset) for point, offset in zip(positions, offsets)]
    # Work from root to tip: moving a parent changes descendants, and each
    # descendant is then restored to its independently computed planar target.
    for joint, target in zip(chain[1:], targets[1:]):
        _set_joint_world_translation(joint, (target.x, target.y, target.z))
    return maximum_deviation


def _projected_chain_plane_deviation(chain: List[str]) -> float:
    """Return maximum deviation from a chain's strongest plane, without edits."""
    if len(chain) < 3:
        return 0.0
    positions = [
        om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in chain
    ]
    chord = positions[-1] - positions[0]
    if chord.length() <= 1.0e-8:
        return 0.0
    normal_candidates = [
        chord ^ (point - positions[0]) for point in positions[1:-1]
    ]
    normal = max(
        normal_candidates, key=lambda vector: vector.length(), default=om.MVector()
    )
    if normal.length() <= 1.0e-8:
        return 0.0
    normal.normalize()
    return max(abs((point - positions[0]) * normal) for point in positions)


def _project_finger_chain_to_tip_plane(
    chain: List[str],
    query: Optional["MeshInteriorQuery"] = None,
) -> Dict[str, float]:
    """Keep a centered terminal fixed while flattening its 02-to-tip chain.

    A generic best-fit plane can pull a fingertip away from the actual mesh
    cap. Instead, the plane is constrained to pass through joints 02 and the
    already-centered terminal; only intermediate pivots are projected.
    """
    if len(chain) < 4:
        return {"before": 0.0, "after": 0.0, "max_intermediate_move": 0.0}
    points = [
        om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in chain
    ]
    start = points[1]
    terminal = points[-1]
    chord = terminal - start
    if chord.length() <= 1.0e-8:
        return {"before": 0.0, "after": 0.0, "max_intermediate_move": 0.0}
    normal_candidates = [
        chord ^ (point - start) for point in points[2:-1]
    ]
    normal = max(
        normal_candidates,
        key=lambda vector: vector.length(),
        default=om.MVector(),
    )
    if normal.length() <= 1.0e-8:
        return {"before": 0.0, "after": 0.0, "max_intermediate_move": 0.0}
    normal.normalize()
    before = max(
        abs((point - start) * normal) for point in points[1:]
    )
    maximum_move = 0.0
    for joint, point in zip(chain[2:-1], points[2:-1]):
        target = point - (normal * ((point - start) * normal))
        target_tuple = (target.x, target.y, target.z)
        if query is not None and not query.point_inside(target_tuple):
            continue
        maximum_move = max(maximum_move, (point - target).length())
        _set_joint_world_translation_preserving_children(joint, target_tuple)
    final_points = [
        om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in chain[1:]
    ]
    after = max(abs((point - start) * normal) for point in final_points)
    return {
        "before": float(before),
        "after": float(after),
        "max_intermediate_move": float(maximum_move),
    }


def _studio_fingertip_center_offsets(
    mesh: str,
    namespace: str = "",
) -> Dict[str, Tuple[float, float]]:
    """Measure terminal offsets from their local mesh-section centers."""
    query = _cached_mesh_interior_query(mesh)
    result = {}
    for name, chain in _studio_finger_chains(namespace).items():
        if len(chain) < 2:
            continue
        tip = om.MVector(*cmds.xform(
            chain[-1], query=True, worldSpace=True, translation=True
        ))
        parent = om.MVector(*cmds.xform(
            chain[-2], query=True, worldSpace=True, translation=True
        ))
        direction = tip - parent
        hand = _find_template_joint(
            "{0}_hand".format(name.split("_", 1)[0]), namespace
        )
        if direction.length() <= 1.0e-8 or not hand:
            continue
        direction.normalize()
        up_axis = om.MVector(_joint_world_axes(hand)["y"])
        up_axis -= direction * (up_axis * direction)
        if up_axis.length() <= 1.0e-8:
            continue
        up_axis.normalize()
        side_axis = direction ^ up_axis
        if side_axis.length() <= 1.0e-8:
            continue
        side_axis.normalize()
        expected = om.MVector(tip)
        for _pass in range(2):
            value, _clearance, up_ok = _recenter_along_direction(
                query, (expected.x, expected.y, expected.z), up_axis
            )
            expected = om.MVector(*value)
            value, _clearance, side_ok = _recenter_along_direction(
                query, (expected.x, expected.y, expected.z), side_axis
            )
            expected = om.MVector(*value)
        offset = tip - expected
        result[name] = (
            float(abs(offset * up_axis)),
            float(abs(offset * side_axis)),
        )
    return result


def _enforce_no_reverse_finger_bend(
    chain: List[str],
    query: Optional["MeshInteriorQuery"] = None,
    dorsal_hint: Vector3 = (0.0, 1.0, 0.0),
) -> float:
    """Remove distal hyperextension without erasing a mesh-authored curl.

    ``chain`` is the articulated 02-terminal chain.  Heights along the dorsal
    axis are expressed as slopes along the finger, then projected onto a
    monotonically decreasing sequence with weighted isotonic regression.  A
    straight mesh therefore stays straight; a relaxed palmar curl survives;
    only a slope reversal at joints 03/04 is corrected.
    """
    if len(chain) < 4:
        return 0.0
    positions = [
        om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in chain
    ]
    dorsal = om.MVector(*dorsal_hint)
    travel = positions[-1] - positions[0]
    if dorsal.length() <= 1.0e-8 or travel.length() <= 1.0e-8:
        return 0.0
    dorsal.normalize()
    plane_candidates = [
        travel ^ (point - positions[0]) for point in positions[1:-1]
    ]
    plane_normal = max(
        plane_candidates,
        key=lambda vector: vector.length(),
        default=om.MVector(),
    )
    if plane_normal.length() > 1.0e-8:
        plane_normal.normalize()
        dorsal -= plane_normal * (dorsal * plane_normal)
        if dorsal.length() <= 1.0e-8:
            return 0.0
        dorsal.normalize()
    forward = travel - (dorsal * (travel * dorsal))
    if forward.length() <= 1.0e-8:
        return 0.0
    forward.normalize()
    parameters = [(point - positions[0]) * forward for point in positions]
    if any(
        upper - lower <= 1.0e-8
        for lower, upper in zip(parameters, parameters[1:])
    ):
        return 0.0
    heights = [(point - positions[0]) * dorsal for point in positions]
    spans = [
        upper - lower for lower, upper in zip(parameters, parameters[1:])
    ]
    slopes = [
        (upper - lower) / span
        for lower, upper, span in zip(heights, heights[1:], spans)
    ]

    # Pool adjacent violators for a non-increasing slope sequence.  Weighting
    # by longitudinal span preserves the fixed 02 and terminal endpoints.
    blocks = []
    for index, (slope, weight) in enumerate(zip(slopes, spans)):
        blocks.append([index, index, float(weight), float(slope * weight)])
        while len(blocks) >= 2:
            previous = blocks[-2][3] / blocks[-2][2]
            current = blocks[-1][3] / blocks[-1][2]
            if previous >= current - 1.0e-10:
                break
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([
                left[0], right[1], left[2] + right[2], left[3] + right[3]
            ])
    fitted_slopes = [0.0] * len(slopes)
    for start, end, weight, weighted_sum in blocks:
        fitted_slopes[start:end + 1] = [weighted_sum / weight] * (
            end - start + 1
        )
    fitted_heights = [heights[0]]
    for slope, span in zip(fitted_slopes, spans):
        fitted_heights.append(fitted_heights[-1] + (slope * span))

    maximum_correction = 0.0
    for joint, point, height, fitted_height in zip(
        chain[1:-1], positions[1:-1], heights[1:-1], fitted_heights[1:-1]
    ):
        correction = fitted_height - height
        maximum_correction = max(maximum_correction, abs(correction))
        if abs(correction) <= 1.0e-8:
            continue
        target = point + (dorsal * correction)
        target_tuple = (target.x, target.y, target.z)
        if query is not None and not query.point_inside(target_tuple):
            # The current joint is already valid.  Retain as much correction
            # as the actual finger volume permits rather than leaving the mesh.
            low, high = 0.0, 1.0
            for _iteration in range(12):
                blend = (low + high) * 0.5
                candidate = point + (dorsal * correction * blend)
                if query.point_inside((candidate.x, candidate.y, candidate.z)):
                    low = blend
                else:
                    high = blend
            target = point + (dorsal * correction * low)
            target_tuple = (target.x, target.y, target.z)
        _set_joint_world_translation_preserving_children(joint, target_tuple)
    return maximum_correction


def enforce_studio_finger_planarity(
    root: str,
    namespace: str = "",
    mesh: str = "",
) -> Dict[str, float]:
    """Make joints 02 through the terminal of each digit one bend plane.

    Joint 01 is the metacarpal fan/root and may approach joint 02 from outside
    that plane. The articulated finger starts at 02; projecting only that
    subchain preserves the approved palm spread while guaranteeing that
    joints 03-05 can use one local curl axis.
    """
    deviations = {}
    query = _cached_mesh_interior_query(mesh) if mesh else None
    for side in ("l", "r"):
        for digit in ("thumb", "index", "middle", "ring", "pinky"):
            name = "{0}_{1}_01".format(side, digit)
            finger_root = _find_template_joint(name, namespace)
            if not finger_root:
                continue
            chain = _finger_chain(finger_root)
            articulated_chain = chain[1:]
            deviations[name] = _project_joint_chain_to_plane(articulated_chain)
            deviations[name + "_reverse_bend_correction"] = (
                _enforce_no_reverse_finger_bend(
                    articulated_chain,
                    query=query,
                )
            )
            if digit != "thumb" or len(chain) < 4:
                continue

            # Thumb 02-04 is the strict one-axis curl chain. Thumb 01 is the
            # opposable base and may sit slightly outside that plane, but a
            # large inherited atlas offset makes the whole thumb look broken.
            # Clamp only the excess, preserve the distal chain in world space,
            # and reject a proposal that leaves the target mesh volume.
            positions = [
                om.MVector(*cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                ))
                for joint in chain[:4]
            ]
            plane_normal = (
                positions[2] - positions[1]
            ) ^ (
                positions[3] - positions[1]
            )
            first_length = (positions[1] - positions[0]).length()
            if plane_normal.length() <= 1.0e-8 or first_length <= 1.0e-8:
                continue
            plane_normal.normalize()
            signed_offset = (positions[0] - positions[1]) * plane_normal
            maximum_offset = first_length * 0.15
            if abs(signed_offset) > maximum_offset:
                retained_offset = math.copysign(maximum_offset, signed_offset)
                target = positions[0] - (
                    plane_normal * (signed_offset - retained_offset)
                )
                target_tuple = (target.x, target.y, target.z)
                if query is None or query.point_inside(target_tuple):
                    _set_joint_world_translation_preserving_children(
                        chain[0], target_tuple
                    )
                    signed_offset = retained_offset
            deviations[name + "_01_plane_offset_ratio"] = (
                abs(float(signed_offset)) / first_length
            )
    return deviations


def _align_mild_studio_digit_bend(
    chain: List[str],
    query: Optional["MeshInteriorQuery"] = None,
    obvious_bend_ratio: float = 0.08,
) -> Dict[str, object]:
    """Put 03/04 on the 02-to-tip line unless the mesh shows a clear bend."""
    articulated = chain[1:]
    if len(articulated) < 3:
        return {"aligned": False, "reason": "short_chain"}
    positions = [
        om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in articulated
    ]
    chord = positions[-1] - positions[0]
    chord_length = chord.length()
    if chord_length <= 1.0e-8:
        return {"aligned": False, "reason": "zero_length"}
    direction = chord.normal()
    deviations = []
    for point in positions[1:-1]:
        projected = positions[0] + (
            direction * ((point - positions[0]) * direction)
        )
        deviations.append((point - projected).length())
    maximum_ratio = max(deviations, default=0.0) / chord_length
    if maximum_ratio > float(obvious_bend_ratio):
        return {
            "aligned": False,
            "reason": "obvious_mesh_bend",
            "maximum_deviation_ratio": float(maximum_ratio),
        }

    cumulative = [0.0]
    for start, end in zip(positions, positions[1:]):
        cumulative.append(cumulative[-1] + (end - start).length())
    total = max(cumulative[-1], 1.0e-8)
    targets = [
        positions[0] + (chord * (distance / total))
        for distance in cumulative
    ]
    for joint, target in zip(articulated[1:-1], targets[1:-1]):
        target_tuple = (target.x, target.y, target.z)
        if query is not None and not query.point_inside(target_tuple):
            return {
                "aligned": False,
                "reason": "line_exits_mesh",
                "maximum_deviation_ratio": float(maximum_ratio),
            }
        _set_joint_world_translation_preserving_children(joint, target_tuple)
    return {
        "aligned": True,
        "reason": "minor_bend_projected_to_02_tip_line",
        "maximum_deviation_ratio": float(maximum_ratio),
    }


def _studio_finger_chains(namespace: str = "") -> Dict[str, List[str]]:
    """Return the authored high-resolution digit chains by stable template name."""
    result = {}
    for side in ("l", "r"):
        for digit in ("thumb", "index", "middle", "ring", "pinky"):
            count = 4 if digit == "thumb" else 5
            chain = [
                _find_template_joint(
                    "{0}_{1}_{2:02d}".format(side, digit, index), namespace
                )
                for index in range(1, count + 1)
            ]
            chain = [joint for joint in chain if joint]
            if len(chain) >= 2:
                result["{0}_{1}".format(side, digit)] = chain
    return result


def _depth_centered_inside_point(
    query: MeshInteriorQuery,
    point: Vector3,
) -> Tuple[Vector3, bool]:
    """Center a hand proposal through palm/finger thickness.

    In the studio T/A pose the hand spreads across XZ and its thickness is Y.
    Recentring Z can silently jump between adjacent fingers, producing crossed
    chains that are technically inside the mesh but anatomically invalid.
    """
    centered, _clearance, section_found = query.recenter_axis(point, "y")
    if section_found and query.point_inside(centered):
        return centered, True
    if query.point_inside(point):
        return point, True
    return point, False


def _bounded_move_inside(
    query: MeshInteriorQuery,
    point: Vector3,
    maximum_distance: float,
) -> Tuple[Vector3, bool]:
    """Accept a closest-surface repair only when it remains anatomically local.

    Hands and facial features contain several nearby disconnected volumes. An
    unconstrained closest-point repair can therefore move a thumb tip into the
    index finger, or an eyelid into the nose, while still passing an inside-
    mesh test. Distance gating turns that case into an explicit fit failure.
    """
    target, success = query.move_inside(point)
    if not success:
        return point, False
    distance = (om.MVector(*target) - om.MVector(*point)).length()
    if distance > max(float(maximum_distance), query.tolerance * 20.0):
        return point, False
    return target, True


def _fit_studio_wrist(
    query: MeshInteriorQuery,
    side: str,
    namespace: str,
) -> Optional[Vector3]:
    """Place a wrist at the narrow arm-to-palm section and center it in 3D."""
    lowerarm = _find_template_joint("{0}_lowerarm".format(side), namespace)
    hand = _find_template_joint("{0}_hand".format(side), namespace)
    if not lowerarm or not hand:
        return None
    elbow = om.MVector(*cmds.xform(lowerarm, query=True, worldSpace=True, translation=True))
    direction = 1.0 if side == "l" else -1.0
    tips = []
    for digit in ("index", "middle", "ring", "pinky"):
        tip = _find_template_joint("{0}_{1}_05".format(side, digit), namespace)
        if tip:
            tips.append(
                om.MVector(*cmds.xform(tip, query=True, worldSpace=True, translation=True))
            )
    if len(tips) != 4:
        return None
    shortest = min(tips, key=lambda point: (point.x - elbow.x) * direction)
    segment = shortest - elbow
    if segment.length() <= 1.0e-8:
        return None

    best = None
    best_score = float("inf")
    # Search an absolute elbow-to-shortest-fingertip band. Unlike searching
    # around the current hand joint, this cannot drift inward on repeated runs.
    for step in range(28):
        ratio = 0.45 + (step * 0.01)
        sample_vector = elbow + (segment * ratio)
        candidate = (sample_vector.x, sample_vector.y, sample_vector.z)
        for _pass in range(2):
            candidate, _y_clearance, y_ok = query.recenter_axis(candidate, "y")
            candidate, _z_clearance, z_ok = query.recenter_axis(candidate, "z")
        if not (y_ok and z_ok and query.point_inside(candidate)):
            continue
        y_interval = _choose_interval(query.axis_intervals(candidate, "y"), candidate[1])
        z_interval = _choose_interval(query.axis_intervals(candidate, "z"), candidate[2])
        if not y_interval or not z_interval:
            continue
        area = (y_interval[1] - y_interval[0]) * (z_interval[1] - z_interval[0])
        # A weak center prior prevents noisy topology from moving the wrist to
        # the edge of the search band when section areas are nearly identical.
        score = area * (1.0 + abs(ratio - 0.58) * 0.20)
        if score < best_score:
            best_score = score
            best = candidate
    if best is not None:
        _set_joint_world_translation(hand, best)
    return best


def _studio_digit_surface_rows(
    query: MeshInteriorQuery,
    side: str,
    chains: Dict[str, List[str]],
    namespace: str,
) -> Dict[str, float]:
    """Detect the four separate non-thumb finger rows from mesh sections."""
    wrist_joint = _find_template_joint("{0}_hand".format(side), namespace)
    thumb_chain = chains.get("{0}_thumb".format(side)) or []
    digit_names = ("index", "middle", "ring", "pinky")
    digit_chains = [chains.get("{0}_{1}".format(side, digit)) or [] for digit in digit_names]
    if not wrist_joint or not thumb_chain or any(not chain for chain in digit_chains):
        return {}

    wrist = cmds.xform(wrist_joint, query=True, worldSpace=True, translation=True)
    tips = [cmds.xform(chain[-1], query=True, worldSpace=True, translation=True) for chain in digit_chains]
    direction = 1.0 if side == "l" else -1.0
    shortest = min(tips, key=lambda point: (point[0] - wrist[0]) * direction)
    # Sample distally enough that palm webbing no longer merges neighboring
    # fingers into one interval.
    average_y = sum(point[1] for point in tips) / float(len(tips))
    sample_step = query.diagonal * 0.003
    best_intervals = []
    best_score = -1.0
    # The authored template can sit several finger-thicknesses above or below
    # the target mesh before fitting. Search a small distal X/Y grid instead of
    # assuming that one template-derived horizontal slice crosses all digits.
    for x_ratio in (0.70, 0.75, 0.80, 0.85, 0.90):
        common_x = wrist[0] + ((shortest[0] - wrist[0]) * x_ratio)
        for offset in (
            0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0, -4.0, 4.0,
            -5.0, 5.0, -6.0, 6.0, -7.0, 7.0, -8.0, 8.0,
        ):
            sample_y = average_y + (offset * sample_step)
            intervals = [
                interval for interval in query.axis_intervals((common_x, sample_y, wrist[2]), "z")
                if (interval[1] - interval[0]) <= query.diagonal * 0.03
                and abs(((interval[0] + interval[1]) * 0.5) - wrist[2]) <= query.diagonal * 0.07
            ]
            if len(intervals) != 4:
                continue
            score = min(interval[1] - interval[0] for interval in intervals)
            if score > best_score:
                best_score = score
                best_intervals = intervals
    if len(best_intervals) != 4:
        return {}

    centers = [(interval[0] + interval[1]) * 0.5 for interval in best_intervals]
    thumb_z = cmds.xform(thumb_chain[-1], query=True, worldSpace=True, translation=True)[2]
    centers.sort(reverse=thumb_z > (sum(centers) / float(len(centers))))
    return dict(zip(digit_names, centers))


def _studio_thumb_tip_from_sections(
    query: MeshInteriorQuery,
    side: str,
    wrist: om.MVector,
    source: List[om.MVector],
) -> Optional[Vector3]:
    """Find the distal thumb volume independently of the neighboring fingers."""
    if len(source) < 2:
        return None
    lateral_sign = 1.0 if side == "l" else -1.0
    authored_delta = source[-1].z - wrist.z
    thumb_side_sign = 1.0 if authored_delta >= 0.0 else -1.0
    minimum_thumb_offset = max(
        abs(authored_delta) * 0.55,
        query.diagonal * 0.02,
    )
    authored_reach = abs(source[-1].x - wrist.x)
    maximum_reach = max(authored_reach * 1.35, query.diagonal * 0.065)
    base_y = sum(point.y for point in source) / float(len(source))
    y_step = query.diagonal * 0.004
    best = None
    best_lateral = -1.0
    for step in range(16, 101):
        ratio = step / 100.0
        x_value = wrist.x + (lateral_sign * maximum_reach * ratio)
        section_candidates = []
        for y_offset in (0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0):
            y_value = base_y + (y_offset * y_step)
            for interval in query.axis_intervals((x_value, y_value, wrist.z), "z"):
                width = interval[1] - interval[0]
                z_value = (interval[0] + interval[1]) * 0.5
                signed_offset = (z_value - wrist.z) * thumb_side_sign
                if signed_offset <= minimum_thumb_offset:
                    continue
                if width > query.diagonal * 0.035:
                    continue
                proposal = (x_value, y_value, z_value)
                centered, inside = _depth_centered_inside_point(query, proposal)
                if inside:
                    section_candidates.append((signed_offset, centered))
        if not section_candidates:
            continue
        # The thumb is the component furthest from the four main digit rows.
        _offset, candidate = max(section_candidates, key=lambda item: item[0])
        lateral = (candidate[0] - wrist.x) * lateral_sign
        if lateral > best_lateral:
            best_lateral = lateral
            best = candidate
    return best


def _studio_digit_tip_from_row(
    query: MeshInteriorQuery,
    side: str,
    wrist: om.MVector,
    row_z: float,
    preferred_y: float,
) -> Optional[Vector3]:
    """Resolve one fingertip from its isolated top-view digit row."""
    lateral_sign = 1.0 if side == "l" else -1.0
    y_step = query.diagonal * 0.0025
    inset = max(query.diagonal * 0.0015, query.tolerance * 20.0)
    best = None
    best_lateral = -1.0
    for offset in (
        0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0, -4.0, 4.0,
        -5.0, 5.0, -6.0, 6.0, -7.0, 7.0, -8.0, 8.0,
    ):
        y_value = preferred_y + (offset * y_step)
        intervals = query.axis_intervals((wrist.x, y_value, row_z), "x")
        for interval in intervals:
            distal_x = interval[1] - inset if lateral_sign > 0.0 else interval[0] + inset
            lateral = (distal_x - wrist.x) * lateral_sign
            if lateral <= query.diagonal * 0.02 or lateral > query.diagonal * 0.20:
                continue
            proposal = (distal_x, y_value, row_z)
            centered, inside = _depth_centered_inside_point(query, proposal)
            if inside and lateral > best_lateral:
                best_lateral = lateral
                best = centered
    return best


def _fit_studio_hand_from_reference(
    query: MeshInteriorQuery,
    root: str,
    chains: Dict[str, List[str]],
    namespace: str = "",
) -> Dict[str, object]:
    """Locally conform an atlas-seeded hand without rebuilding its anatomy."""
    targets = {}
    locally_centered = []
    moved_inside = []
    for chain in chains.values():
        for joint in chain:
            if joint in targets:
                continue
            source = tuple(
                cmds.xform(joint, query=True, worldSpace=True, translation=True)
            )
            target = source
            success = query.point_inside(source)
            if not success:
                centered, centered_ok = _depth_centered_inside_point(query, source)
                if centered_ok:
                    move_distance = (
                        om.MVector(*centered) - om.MVector(*source)
                    ).length()
                    if move_distance <= query.diagonal * 0.018:
                        target = centered
                        success = True
                        locally_centered.append(_short_name(joint))
            if not success:
                repaired, repaired_ok = _bounded_move_inside(
                    query, source, query.diagonal * 0.025
                )
                if repaired_ok:
                    target = repaired
                    success = True
                    moved_inside.append(_short_name(joint))
            targets[joint] = target

    # Preserve the atlas X/Z landmarks, but derive the articulated finger's
    # side-view pose from the target mesh.  A former pass put joints 02-04 at a
    # fixed 40% dorsal bias and only centered the terminal.  That manufactured
    # a downward kink in a straight finger and erased useful curvature in a
    # relaxed finger.  Centering every joint from 02 through the terminal in
    # its own local Y section makes the chain follow the actual mesh centerline:
    # straight geometry stays straight, while a posed/curled digit stays posed.
    # Joint 01 remains a dorsal knuckle/palm landmark and the thumb keeps the
    # atlas layout because its cross-sections are not world-Y aligned.
    mesh_centerline_fitted = []
    for chain in chains.values():
        for joint in chain:
            source = targets.get(joint)
            if source is None:
                continue
            interval = _choose_interval(query.axis_intervals(source, "y"), source[1])
            if not interval:
                continue
            center = (interval[0] + interval[1]) * 0.5
            half_width = (interval[1] - interval[0]) * 0.5
            short_name = _short_name(joint)
            if "_thumb_" in short_name:
                # Keep the thumb centered through its section. Its in-plane
                # curvature still comes from the transferred atlas landmarks.
                depth_bias = 0.0
            elif short_name.endswith("_01"):
                depth_bias = 0.55
            else:
                depth_bias = 0.0
            candidate = (source[0], center + (half_width * depth_bias), source[2])
            if query.point_inside(candidate):
                targets[joint] = candidate
                if short_name.endswith("_01"):
                    continue
                mesh_centerline_fitted.append(_short_name(joint))

    hand_tips = []
    for side in ("l", "r"):
        hand_tip = _find_template_joint("{0}_handTip".format(side), namespace)
        if hand_tip:
            hand_tips.append(hand_tip)
            source = tuple(
                cmds.xform(hand_tip, query=True, worldSpace=True, translation=True)
            )
            centered, success = _depth_centered_inside_point(query, source)
            if success:
                targets[hand_tip] = centered
            else:
                targets[hand_tip] = source

    for joint in sorted(targets, key=lambda node: node.count("|")):
        _set_joint_world_translation(joint, targets[joint])
    for chain in chains.values():
        for parent, child in zip(chain, chain[1:]):
            _orient_joint_x_to_child(parent, child)

    checked = list(dict.fromkeys(list(targets) + hand_tips))
    outside = [
        _short_name(joint)
        for joint in checked
        if not query.point_inside(
            tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        )
    ]
    report = {
        "method": "approved_reference_atlas_local_volume_conform",
        "joint_count": len(checked),
        "inside_count": len(checked) - len(outside),
        "outside_joints": outside,
        "locally_centered": locally_centered,
        "moved_inside": moved_inside,
        "reference_layout_preserved": True,
        "mesh_centerline_fitted": mesh_centerline_fitted,
    }
    _set_string_attr(root, HAND_FIT_REPORT_ATTR, json.dumps(report, sort_keys=True))
    return report


def fit_studio_hand_joints(
    mesh: str,
    root: str,
    namespace: str = "",
    preserve_reference_layout: bool = False,
) -> Dict[str, object]:
    """Fit detailed studio fingers to the actual hand volume.

    The template supplies digit spread, proportions, and bend planes.  Each
    chain is kept as long as the mesh allows and is centered through the local
    mesh thickness, so placement is not merely a front-view projection.
    """
    query = _cached_mesh_interior_query(mesh)
    chains = _studio_finger_chains(namespace)
    if preserve_reference_layout:
        return _fit_studio_hand_from_reference(
            query, root, chains, namespace=namespace
        )
    report = {
        "method": "anatomical_palm_fan_volume_centered",
        "chain_scales": {},
        "fallback_joints": [],
        "outside_joints": [],
        "hand_tips": {},
        "joint_count": 0,
        "inside_count": 0,
        "wrists": {},
    }

    # Capture independent anatomical targets before moving the wrist. Moving a
    # parent carries all descendants in Maya; using those carried positions as
    # the next pass's source caused the entire hand to drift on every rebuild.
    source_positions = {
        joint: om.MVector(
            *cmds.xform(joint, query=True, worldSpace=True, translation=True)
        )
        for chain in chains.values()
        for joint in chain
    }
    report["source_thumb_positions"] = {
        chain_name: [
            [round(float(value), 6) for value in source_positions[joint]]
            for joint in chain
        ]
        for chain_name, chain in chains.items()
        if chain_name.endswith("_thumb")
    }
    surface_rows = {}
    for side in ("l", "r"):
        rows = _studio_digit_surface_rows(query, side, chains, namespace)
        surface_rows.update(
            {"{0}_{1}".format(side, digit): value for digit, value in rows.items()}
        )
    report["surface_rows"] = {
        name: round(float(value), 6) for name, value in surface_rows.items()
    }

    for side in ("l", "r"):
        wrist = _fit_studio_wrist(query, side, namespace)
        if wrist is not None:
            report["wrists"][side] = [round(float(value), 6) for value in wrist]

    for chain_name, chain in chains.items():
        source = [source_positions[joint] for joint in chain]
        side, digit = chain_name.split("_", 1)
        wrist_joint = _find_template_joint("{0}_hand".format(side), namespace)
        wrist = (
            om.MVector(*cmds.xform(wrist_joint, query=True, worldSpace=True, translation=True))
            if wrist_joint else source[0]
        )
        anchor = source[0]
        if digit == "thumb":
            local_anchor, local_anchor_ok = _bounded_move_inside(
                query,
                (anchor.x, anchor.y, anchor.z),
                query.diagonal * 0.025,
            )
            if local_anchor_ok:
                local_anchor, centered_ok = _depth_centered_inside_point(
                    query, local_anchor
                )
                if centered_ok:
                    anchor = om.MVector(*local_anchor)
        chosen_scale = None
        chosen_targets = None
        thumb_surface_factor = 1.0
        thumb_tip = None
        digit_tip = None
        if digit == "thumb":
            thumb_tip = _studio_thumb_tip_from_sections(
                query, side, wrist, source
            )
            if thumb_tip:
                report.setdefault("thumb_section_tips", {})[chain_name] = [
                    round(float(value), 6) for value in thumb_tip
                ]
            chord = source[-1] - anchor
            if chord.length() > 1.0e-8:
                ray_direction = chord.normal()
                hits = query._ray_hits(
                    (anchor.x, anchor.y, anchor.z),
                    om.MFloatVector(ray_direction.x, ray_direction.y, ray_direction.z),
                    query.diagonal,
                )
                distances = [
                    (om.MVector(hit.x, hit.y, hit.z) - anchor) * ray_direction
                    for hit in hits
                ]
                # A thumb root often sits close to the webbing surface. Ignore
                # that immediate exit and take the first genuinely distal hit.
                minimum_distal_hit = chord.length() * 0.75
                distances = [
                    distance for distance in distances
                    if distance > max(query.tolerance, minimum_distal_hit)
                ]
                if distances:
                    inset = max(query.diagonal * 0.002, query.tolerance * 20.0)
                    thumb_surface_factor = min(
                        2.5,
                        max(0.75, (min(distances) - inset) / chord.length()),
                    )
            report.setdefault("thumb_surface_factors", {})[chain_name] = round(
                float(thumb_surface_factor), 4
            )
        elif chain_name in surface_rows:
            digit_tip = _studio_digit_tip_from_row(
                query,
                side,
                wrist,
                surface_rows[chain_name],
                source[-1].y,
            )
            if digit_tip:
                report.setdefault("digit_section_tips", {})[chain_name] = [
                    round(float(value), 6) for value in digit_tip
                ]
        for step in range(101):
            scale = 1.0 - (step * 0.01)
            if scale < 0.20:
                break
            targets = []
            valid = True
            if digit == "thumb":
                if thumb_tip:
                    distal = om.MVector(*thumb_tip)
                    authored_lengths = [0.0]
                    for start, end in zip(source, source[1:]):
                        authored_lengths.append(authored_lengths[-1] + (end - start).length())
                    total_length = max(authored_lengths[-1], 1.0e-8)
                    proposals = [
                        anchor + ((distal - anchor) * (distance / total_length) * scale)
                        for distance in authored_lengths
                    ]
                else:
                    proposals = [
                        anchor + ((position - anchor) * thumb_surface_factor * scale)
                        for position in source
                    ]
            else:
                # Build a clean, non-crossing palm fan from this digit's own
                # fingertip direction.  Five-joint chains represent MCP,
                # proximal, middle, distal, and tip landmarks.
                surface_tip = om.MVector(*(digit_tip or source[-1]))
                if chain_name in surface_rows:
                    surface_tip.z = surface_rows[chain_name]
                distal = wrist + ((surface_tip - wrist) * scale)
                root_fraction = {
                    "index": 0.40,
                    "middle": 0.38,
                    "ring": 0.40,
                    "pinky": 0.44,
                }.get(digit, 0.40)
                digit_root = wrist + ((distal - wrist) * root_fraction)
                fractions = (0.0, 0.32, 0.61, 0.83, 1.0)
                proposals = [
                    digit_root + ((distal - digit_root) * fraction)
                    for fraction in fractions[:len(chain)]
                ]
            for proposal_vector in proposals:
                proposal = (proposal_vector.x, proposal_vector.y, proposal_vector.z)
                centered, inside = _depth_centered_inside_point(query, proposal)
                if not inside and digit == "thumb":
                    centered, inside = _bounded_move_inside(
                        query,
                        proposal,
                        query.diagonal * 0.0125,
                    )
                    if inside:
                        centered_candidate, centered_ok = _depth_centered_inside_point(
                            query, centered
                        )
                        if centered_ok:
                            centered = centered_candidate
                if not inside:
                    valid = False
                    break
                targets.append(centered)
            if valid:
                chosen_scale = scale
                chosen_targets = targets
                break

        if chosen_targets is None:
            chosen_scale = 1.0
            chosen_targets = []
            for joint, position in zip(chain, source):
                proposal = (position.x, position.y, position.z)
                centered, inside = _depth_centered_inside_point(query, proposal)
                if not inside:
                    centered, inside = _bounded_move_inside(
                        query,
                        proposal,
                        query.diagonal * 0.0125,
                    )
                    if inside:
                        report["fallback_joints"].append(_short_name(joint))
                chosen_targets.append(centered)

        for joint, target in zip(chain, chosen_targets):
            _set_joint_world_translation(joint, target)
        report["chain_scales"][chain_name] = round(float(chosen_scale), 4)

    # The palm endpoint belongs at the knuckle row, not at a template-space
    # offset.  Rebuilding it also prevents the prior left/right asymmetry.
    for side in ("l", "r"):
        knuckles = []
        for digit in ("index", "middle", "ring", "pinky"):
            chain = chains.get("{0}_{1}".format(side, digit)) or []
            if chain:
                knuckles.append(
                    cmds.xform(chain[0], query=True, worldSpace=True, translation=True)
                )
        hand_tip = _find_template_joint("{0}_handTip".format(side), namespace)
        if hand_tip and knuckles:
            centroid = tuple(
                sum(point[axis] for point in knuckles) / float(len(knuckles))
                for axis in range(3)
            )
            target, inside = _depth_centered_inside_point(query, centroid)
            if not inside:
                target, inside = query.move_inside(centroid)
            if inside:
                _set_joint_world_translation(hand_tip, target)
            report["hand_tips"][side] = [round(float(value), 6) for value in target]

    for chain in chains.values():
        for parent, child in zip(chain, chain[1:]):
            _orient_joint_x_to_child(parent, child)

    checked = []
    for chain in chains.values():
        checked.extend(chain)
    checked.extend(
        joint
        for joint in (
            _find_template_joint("l_hand", namespace),
            _find_template_joint("l_handTip", namespace),
            _find_template_joint("r_hand", namespace),
            _find_template_joint("r_handTip", namespace),
        )
        if joint
    )
    checked = list(dict.fromkeys(checked))
    outside = []
    for joint in checked:
        position = tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        if not query.point_inside(position):
            outside.append(_short_name(joint))
    report["joint_count"] = len(checked)
    report["outside_joints"] = outside
    report["inside_count"] = len(checked) - len(outside)
    _set_string_attr(root, HAND_FIT_REPORT_ATTR, json.dumps(report, sort_keys=True))
    return report


def fit_studio_distal_thumb_joints(
    mesh: str,
    namespace: str = "",
    smoothing: float = 0.0,
    minimum_bend_degrees: float = 4.0,
) -> Dict[str, object]:
    """Restore the topology-authored distal thumb pivots and rest bend.

    The topology/reference solve already owns the longitudinal knuckle
    and fingertip locations. ``smoothing`` is retained as an explicit opt-in
    for legacy data, but defaults to zero so a generic chord fraction cannot
    replace those anatomical landmarks.
    """
    query = _cached_mesh_interior_query(mesh)
    smoothing = max(0.0, min(float(smoothing), 1.0))
    dorsal_vectors = solve_reference_thumb_dorsal_vectors(mesh)
    reference_points, reference_cases = solve_reference_detail_points(mesh)
    placed = {}
    bend_degrees = {}
    for side in ("l", "r"):
        previous_joint = _find_template_joint(
            "{0}_thumb_02".format(side), namespace
        )
        knuckle_joint = _find_template_joint(
            "{0}_thumb_03".format(side), namespace
        )
        tip_joint = _find_template_joint(
            "{0}_thumb_04".format(side), namespace
        )
        if not previous_joint or not knuckle_joint or not tip_joint:
            continue
        previous_name = "{0}_thumb_02".format(side)
        approved_previous = reference_points.get(previous_name)
        if approved_previous is not None and query.point_inside(approved_previous):
            _set_joint_world_translation_preserving_children(
                previous_joint, approved_previous
            )
            placed[previous_name] = approved_previous
        tip_name = "{0}_thumb_04".format(side)
        approved_tip = reference_points.get(tip_name)
        if approved_tip is not None and query.point_inside(approved_tip):
            # The approved topology point is already centered just inside the
            # actual fingertip cap. Keeping the inherited template tip left it
            # near the distal pad on non-reference proportions.
            _set_joint_world_translation_preserving_children(
                tip_joint, approved_tip
            )
            placed[tip_name] = approved_tip
        previous = om.MVector(*cmds.xform(
            previous_joint, query=True, worldSpace=True, translation=True
        ))
        knuckle = om.MVector(*cmds.xform(
            knuckle_joint, query=True, worldSpace=True, translation=True
        ))
        tip = om.MVector(*cmds.xform(
            tip_joint, query=True, worldSpace=True, translation=True
        ))
        chord = tip - previous
        if chord.length() <= 1.0e-8:
            continue
        # Keep the topology-transferred IP hinge on the visible crease. The
        # chord target exists only for an explicit legacy smoothing request;
        # using it by default moved thumb03 along the digit and off its knuckle.
        knuckle_name = "{0}_thumb_03".format(side)
        approved_knuckle = reference_points.get(knuckle_name)
        chord_target = (
            om.MVector(*approved_knuckle)
            if approved_knuckle is not None
            else previous + (chord * 0.52)
        )
        proposal = (
            (knuckle * (1.0 - smoothing))
            + (chord_target * smoothing)
        )
        dorsal = om.MVector(*dorsal_vectors.get(
            "{0}_thumb_03".format(side),
            (0.0, 1.0, 0.0),
        ))
        dorsal -= chord.normal() * (dorsal * chord.normal())
        if dorsal.length() <= 1.0e-8:
            dorsal = om.MVector(0.0, 1.0, 0.0)
            dorsal -= chord.normal() * (dorsal * chord.normal())
        if dorsal.length() <= 1.0e-8:
            continue
        dorsal.normalize()
        target = (proposal.x, proposal.y, proposal.z)
        inside = bool(
            approved_knuckle is not None and query.point_inside(target)
        )
        if not inside:
            target, _clearance, section_found = _place_along_direction_fraction(
                query,
                target,
                dorsal,
                0.5,
            )
            inside = bool(section_found and query.point_inside(target))
        if not inside:
            target, inside = _bounded_move_inside(
                query,
                (proposal.x, proposal.y, proposal.z),
                query.diagonal * 0.008,
            )
        if not inside:
            continue
        target_vector = om.MVector(*target)
        chord_direction = chord.normal()
        line_point = previous + chord_direction * (
            (target_vector - previous) * chord_direction
        )
        bend_offset = target_vector - line_point
        if bend_offset.length() <= 1.0e-8:
            bend_offset = om.MVector(dorsal)
        bend_offset.normalize()

        def _joint_angle(offset_distance: float) -> float:
            candidate = line_point + bend_offset * offset_distance
            first = candidate - previous
            second = tip - candidate
            if first.length() <= 1.0e-8 or second.length() <= 1.0e-8:
                return 0.0
            cosine = max(-1.0, min(1.0, float(
                first.normal() * second.normal()
            )))
            return math.degrees(math.acos(cosine))

        target_offset = (target_vector - line_point).length()
        target_angle = _joint_angle(target_offset)
        required_angle = max(0.0, float(minimum_bend_degrees))
        if target_angle < required_angle:
            low = target_offset
            high = max(low, chord.length() * 0.01)
            maximum_offset = chord.length() * 0.15
            while high < maximum_offset and _joint_angle(high) < required_angle:
                high = min(maximum_offset, high * 1.75)
            if _joint_angle(high) >= required_angle:
                for _iteration in range(24):
                    midpoint = (low + high) * 0.5
                    if _joint_angle(midpoint) < required_angle:
                        low = midpoint
                    else:
                        high = midpoint
                candidate = line_point + bend_offset * high
                candidate_tuple = (candidate.x, candidate.y, candidate.z)
                if query.point_inside(candidate_tuple):
                    target = candidate_tuple
                    target_angle = _joint_angle(high)
        _set_joint_world_translation_preserving_children(
            knuckle_joint, target
        )
        placed[knuckle_name] = target
        bend_degrees[knuckle_name] = float(target_angle)
    return {
        "placed": placed,
        "placed_count": len(placed),
        "bend_degrees": bend_degrees,
        "minimum_bend_degrees": float(minimum_bend_degrees),
        "reference_cases": reference_cases,
    }


def fit_studio_thumb_root_depth(
    mesh: str,
    namespace: str = "",
    dorsal_fraction: float = 0.45,
) -> Dict[str, object]:
    """Seat thumb_01 slightly palmar of center without moving its children.

    A world-axis hand-depth solve is unreliable where the thumb mound turns
    away from the palm. Use the topology-transferred thumb dorsal vector (or
    the joint's local Y fallback), then place the CMC pivot at a modest 45%
    through that local section. The distal knuckle chain stays fixed in world
    space while only thumb_01 moves inward from the dorsal shell.
    """
    query = _cached_mesh_interior_query(mesh)
    dorsal_vectors = solve_reference_thumb_dorsal_vectors(mesh)
    fraction = max(0.0, min(float(dorsal_fraction), 1.0))
    placed = {}
    for side in ("l", "r"):
        name = "{0}_thumb_01".format(side)
        joint = _find_template_joint(name, namespace)
        if not joint:
            continue
        original = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        dorsal_value = dorsal_vectors.get(name)
        if dorsal_value is not None:
            dorsal = om.MVector(*dorsal_value)
        else:
            dorsal = om.MVector(_joint_world_axes(joint)["y"])
        target, clearance, found = _place_along_direction_fraction(
            query, original, dorsal, fraction
        )
        if not found or not query.point_inside(target):
            continue
        _set_joint_world_translation_preserving_children(joint, target)
        placed[name] = {
            "position": target,
            "offset": tuple(
                float(target[index]) - float(original[index])
                for index in range(3)
            ),
            "clearance": float(clearance),
        }
    return {
        "placed": placed,
        "placed_count": len(placed),
        "dorsal_fraction": fraction,
        "distal_children_preserved": True,
    }


def fit_studio_finger_knuckle_height(
    mesh: str,
    namespace: str = "",
    upper_fraction: float = 2.0 / 3.0,
) -> Dict[str, object]:
    """Seat each finger joint 02 two thirds toward the dorsal surface.

    Joints 03-04 retain their mesh-derived pose and joint 05 remains centered
    in the fingertip. The later planar pass makes that 02-05 chain a stable
    single-axis curl plane without flattening every pivot to one shell height.
    """
    query = _cached_mesh_interior_query(mesh)
    fraction = max(0.0, min(float(upper_fraction), 1.0))
    placed = {}
    for chain_name, chain in _studio_finger_chains(namespace).items():
        if chain_name.endswith("_thumb") or len(chain) < 5:
            continue
        start = om.MVector(*cmds.xform(chain[0], query=True, worldSpace=True, translation=True))
        end = om.MVector(*cmds.xform(chain[-1], query=True, worldSpace=True, translation=True))
        longitudinal = end - start
        if longitudinal.length() <= 1.0e-8:
            continue
        longitudinal.normalize()
        dorsal = om.MVector(0.0, 1.0, 0.0)
        dorsal -= longitudinal * (dorsal * longitudinal)
        if dorsal.length() <= 1.0e-8:
            dorsal = om.MVector(0.0, 0.0, 1.0)
            dorsal -= longitudinal * (dorsal * longitudinal)
        if dorsal.length() <= 1.0e-8:
            continue
        dorsal.normalize()
        if dorsal.y < 0.0:
            dorsal *= -1.0
        joint = chain[1]
        current = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        target, clearance, found = _place_along_direction_fraction(
            query, current, dorsal, fraction
        )
        if not found or not query.point_inside(target):
            continue
        _set_joint_world_translation_preserving_children(joint, target)
        placed[_short_name(joint)] = {
            "position": target,
            "section_fraction": fraction,
            "clearance": clearance,
        }
    return {"placed": placed, "placed_count": len(placed)}


def fit_studio_arm_red_dot_refinement(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Audit the topology-fitted shoulder, elbow, and wrist landmarks.

    The approved topology transfer already places these pivots from the source
    rigs.  A former post-pass recentered the chain independently and then
    projected the wrist onto a synthetic plane.  That destroyed the fitted
    shoulder/wrist landmarks and translated the complete finger hierarchy.
    Arm orientation is now solved from this immutable triangle instead.
    """
    query = _cached_mesh_interior_query(mesh)
    placed = {}
    for side in ("l", "r"):
        joints = [
            _find_template_joint("{0}_upperarm".format(side), namespace),
            _find_template_joint("{0}_lowerarm".format(side), namespace),
            _find_template_joint("{0}_hand".format(side), namespace),
        ]
        if not all(joints):
            continue
        for joint in joints:
            target = tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            placed[_short_name(joint)] = {
                "position": target,
                "inside": bool(query.point_inside(target)),
            }
    return {
        "placed": placed,
        "placed_count": 0,
        "method": "preserve_topology_reference_landmarks",
    }


def fit_studio_arm_hand_from_reference(
    mesh: str,
    namespace: str = "",
    reference_targets: Optional[Dict[str, Vector3]] = None,
) -> Dict[str, object]:
    """Restore approved mesh-relative arm and hand landmarks exactly.

    Topology transfer from the approved rig corpus owns elbow, wrist, and
    digit anatomy. No independent per-joint section-centering is allowed here:
    that post-process bent otherwise correct arms and pushed fingertips onto a
    shell edge. A later hand-volume pass may adjust only the through-volume
    coordinate before digit planarity and orientation are finalized.
    """
    query = _cached_mesh_interior_query(mesh)
    targets = reference_targets or {}
    restored = {}
    ordered_names = []
    for side in ("l", "r"):
        ordered_names.extend((
            "{0}_lowerarm".format(side),
            "{0}_hand".format(side),
            "{0}_handTip".format(side),
        ))
        for digit in ("thumb", "index", "middle", "ring", "pinky"):
            count = 4 if digit == "thumb" else 5
            ordered_names.extend(
                "{0}_{1}_{2:02d}".format(side, digit, index)
                for index in range(1, count + 1)
            )

    for name in ordered_names:
        target = targets.get(name)
        joint = _find_template_joint(name, namespace)
        if target is None or not joint:
            continue
        target = tuple(float(value) for value in target)
        _set_joint_world_translation(joint, target)
        restored[name] = {
            "position": target,
            "inside": bool(query.point_inside(target)),
        }

    return {
        "method": "approved_topology_reference_landmarks",
        "placed": restored,
        "placed_count": len(restored),
        "independent_section_centering": False,
    }


def _find_studio_elbow_section(
    query: "MeshInteriorQuery",
    shoulder: Vector3,
    wrist: Vector3,
) -> Optional[Vector3]:
    """Find the compact elbow section along a posed shoulder-to-wrist span."""
    start = om.MVector(*shoulder)
    end = om.MVector(*wrist)
    aim = end - start
    if aim.length() <= 1.0e-8:
        return None
    aim.normalize()

    # Build the cross-section in the arm's own frame. This remains valid for
    # both T- and A-poses, unlike world-Y/world-Z section measurements.
    depth_axis = om.MVector(0.0, 0.0, 1.0)
    depth_axis -= aim * (depth_axis * aim)
    if depth_axis.length() <= 1.0e-8:
        depth_axis = om.MVector(0.0, 1.0, 0.0)
        depth_axis -= aim * (depth_axis * aim)
    if depth_axis.length() <= 1.0e-8:
        return None
    depth_axis.normalize()
    section_axis = depth_axis ^ aim
    section_axis.normalize()

    candidates = []
    for step in range(45):
        fraction = 0.40 + (step * (0.22 / 44.0))
        sample = start + ((end - start) * fraction)
        point = (sample.x, sample.y, sample.z)
        depth_clearance = section_clearance = 0.0
        depth_ok = section_ok = False
        for _pass in range(2):
            point, depth_clearance, depth_ok = _recenter_along_direction(
                query, point, depth_axis
            )
            point, section_clearance, section_ok = _recenter_along_direction(
                query, point, section_axis
            )
        if not (depth_ok and section_ok and query.point_inside(point)):
            continue
        area = max(depth_clearance, query.tolerance) * max(
            section_clearance, query.tolerance
        )
        candidates.append((area, abs(fraction - 0.52), point))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def fit_studio_arm_hinge_plane_to_mesh(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Conform arm pivots without flattening an authored A-pose into a T-pose.

    Atlas transfer supplies stable longitudinal landmarks, while the target
    mesh owns each pivot's through-volume depth. Shoulder, elbow, and wrist
    must *not* share one world-Y value: doing that drags an A-pose shoulder down
    into the armpit. Preserve the fitted shoulder and the atlas elbow height,
    center their depth independently, and apply the 60-percent dorsal rule only
    inside the wrist's own section. The later hinge-orientation pass derives
    local Z from this final shoulder/elbow/wrist triangle.
    """
    query = _cached_mesh_interior_query(mesh)
    report = {}
    # This function runs after approved matrices may have been restored on an
    # existing skeleton. Refit the shoulder here—not only in the initial point
    # solve—so an obsolete chest/armpit pivot cannot overwrite the deltoid fit.
    arm_points = {}
    for side in ("l", "r"):
        for role in ("upperarm", "lowerarm"):
            name = "{0}_{1}".format(side, role)
            joint = _find_template_joint(name, namespace)
            if joint:
                arm_points[name] = tuple(cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                ))
    refined_arm_points = refine_shoulder_landmarks(arm_points, query)
    for side in ("l", "r"):
        name = "{0}_upperarm".format(side)
        joint = _find_template_joint(name, namespace)
        target = refined_arm_points.get(name)
        if joint and target and target != arm_points.get(name):
            _set_joint_world_translation_preserving_children(joint, target)

    for side in ("l", "r"):
        names = [
            "{0}_upperarm".format(side),
            "{0}_lowerarm".format(side),
            "{0}_hand".format(side),
        ]
        joints = [_find_template_joint(name, namespace) for name in names]
        if not all(joints):
            continue

        shoulder_position = tuple(cmds.xform(
            joints[0], query=True, worldSpace=True, translation=True
        ))
        wrist_position = tuple(cmds.xform(
            joints[2], query=True, worldSpace=True, translation=True
        ))
        elbow_section = _find_studio_elbow_section(
            query, shoulder_position, wrist_position
        )
        if elbow_section is not None:
            _set_joint_world_translation_preserving_children(
                joints[1], elbow_section
            )

        original = []
        depth_centered = []
        for index, joint in enumerate(joints):
            point = tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            original.append(tuple(float(value) for value in point))
            # The shoulder refinement already found the compact humeral section
            # in 3D. A new axis ray here can see the connected torso and pull it
            # back into the chest, so preserve that result exactly.
            if index > 0:
                for _pass in range(3):
                    point, _clearance, _found_z = query.recenter_axis(point, "z")
            depth_centered.append(tuple(float(value) for value in point))

        wrist_y_interval = _choose_interval(
            query.axis_intervals(depth_centered[2], "y"),
            depth_centered[2][1],
        )
        wrist_y = (
            wrist_y_interval[0]
            + (
                (wrist_y_interval[1] - wrist_y_interval[0])
                * STUDIO_WRIST_DORSAL_FRACTION
            )
            if wrist_y_interval else depth_centered[2][1]
        )
        shoulder_to_wrist_x = depth_centered[2][0] - depth_centered[0][0]
        elbow_ratio = (
            (depth_centered[1][0] - depth_centered[0][0]) / shoulder_to_wrist_x
            if abs(shoulder_to_wrist_x) > 1.0e-8 else 0.5
        )
        chord_z = depth_centered[0][2] + (
            (depth_centered[2][2] - depth_centered[0][2]) * elbow_ratio
        )
        # The elbow section's volume centroid is biased toward the outer elbow
        # mass. The anatomical flexion/inner side is across the section from
        # that offset, so the hinge pivot must travel in the opposite direction.
        mesh_bend_sign = -1.0 if depth_centered[1][2] >= chord_z else 1.0
        targets = []
        for index, center in enumerate(depth_centered):
            # Preserve each longitudinal landmark. Only the wrist gets the
            # explicit dorsal-height rule; shoulder and elbow retain their own
            # fitted/atlas Y values so an A-pose remains an A-pose.
            target_y = wrist_y if index == 2 else original[index][1]
            target = (center[0], target_y, center[2])
            if index == 1:
                elbow_interval = _choose_interval(
                    query.axis_intervals(target, "z"),
                    target[2],
                )
                if elbow_interval:
                    inner_z = (
                        elbow_interval[0]
                        if mesh_bend_sign > 0.0 else elbow_interval[1]
                    )
                    outer_z = (
                        elbow_interval[1]
                        if mesh_bend_sign > 0.0 else elbow_interval[0]
                    )
                    target = (
                        target[0],
                        target[1],
                        inner_z + ((outer_z - inner_z) * (2.0 / 3.0)),
                    )
                    found_z = True
                else:
                    found_z = False
            elif index == 2:
                for _pass in range(3):
                    target, _clearance, found_z = query.recenter_axis(target, "z")
            else:
                found_z = True
            if not found_z or not query.point_inside(target):
                target = center
            targets.append(tuple(float(value) for value in target))

        for name, joint, target in zip(names, joints, targets):
            _set_joint_world_translation_preserving_children(joint, target)
            report[name] = {
                "position": target,
                "inside": bool(query.point_inside(target)),
            }
    return {
        "method": "pose_preserving_mesh_depth_local_z_hinge_plane",
        "wrist_section_fraction_from_bottom": STUDIO_WRIST_DORSAL_FRACTION,
        "elbow_section_fraction_from_inner": 2.0 / 3.0,
        "placed": report,
        "placed_count": len(report),
    }


def _fit_studio_twist_segments(namespace: str = "") -> List[str]:
    """Place studio twist joints at deterministic fractions of their segment."""
    moved = []
    specs = (
        ("l_upperarm", "l_lowerarm", "l_upperarm{0}_twist", 4),
        ("r_upperarm", "r_lowerarm", "r_upperarm{0}_twist", 4),
        ("l_lowerarm", "l_hand", "l_lowerarm{0}_twist", 4),
        ("r_lowerarm", "r_hand", "r_lowerarm{0}_twist", 4),
        ("l_thigh", "l_knee", "l_thigh_twist{0}", 4),
        ("r_thigh", "r_knee", "r_thigh_twist{0}", 4),
        ("l_knee", "l_ankle", "l_knee_twist{0}", 3),
        ("r_knee", "r_ankle", "r_knee_twist{0}", 3),
    )
    for start_name, end_name, pattern, count in specs:
        start_joint = _find_template_joint(start_name, namespace)
        end_joint = _find_template_joint(end_name, namespace)
        if not start_joint or not end_joint:
            continue
        start = om.MVector(*cmds.xform(start_joint, query=True, worldSpace=True, translation=True))
        end = om.MVector(*cmds.xform(end_joint, query=True, worldSpace=True, translation=True))
        for index in range(1, count + 1):
            joint = _find_template_joint(pattern.format(index), namespace)
            if not joint:
                continue
            fraction = index / float(count + 1)
            target = start + ((end - start) * fraction)
            _set_joint_world_translation(joint, (target.x, target.y, target.z))
            moved.append(_short_name(joint))
    return moved


def mirror_studio_right_leg_from_left(
    namespace: str = "",
) -> Dict[str, Vector3]:
    """Make the right leg an exact world-X reflection of the authored left leg."""
    targets = []
    for suffix in STUDIO_LEG_MIRROR_SUFFIXES:
        left = _find_template_joint("l_{0}".format(suffix), namespace)
        right = _find_template_joint("r_{0}".format(suffix), namespace)
        if not left or not right:
            continue
        left_position = cmds.xform(
            left, query=True, worldSpace=True, translation=True
        )
        targets.append((right, (
            -float(left_position[0]),
            float(left_position[1]),
            float(left_position[2]),
        )))
    targets.sort(key=lambda item: item[0].count("|"))
    result = {}
    for right, target in targets:
        _set_joint_world_translation(right, target)
        result[_short_name(right).split(":")[-1]] = target
    return result


def _same_side_interval(
    intervals: Iterable[Tuple[float, float]],
    side: str,
    center_x: float,
    seed_x: float,
) -> Optional[Tuple[float, float]]:
    """Choose the local shell interval belonging to one anatomical side."""
    direction = 1.0 if side == "l" else -1.0
    intervals = list(intervals)
    containing = [
        interval for interval in intervals
        if interval[0] <= seed_x <= interval[1]
        and ((seed_x - center_x) * direction) > 0.0
    ]
    if containing:
        return min(
            containing,
            key=lambda interval: abs(((interval[0] + interval[1]) * 0.5) - seed_x),
        )
    candidates = [
        interval for interval in intervals
        if ((((interval[0] + interval[1]) * 0.5) - center_x) * direction) > 0.0
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda interval: abs(((interval[0] + interval[1]) * 0.5) - seed_x),
    )


def refine_studio_core_targets_for_mesh(
    targets: Dict[str, Vector3],
    mesh: str,
) -> Dict[str, object]:
    """Refine torso, A-stance legs, feet, and neck from local mesh sections.

    Unlike a whole-mesh inside test, every leg point must use the interval on
    its own side. This prevents the opposite leg or pelvis shell from falsely
    validating a joint in empty space.
    """
    query = _cached_mesh_interior_query(mesh)
    bounds = get_mesh_bounds(mesh)
    center_x = bounds["center"].x
    result = dict(targets)
    report = {
        "spine": {},
        "neck": {},
        "arms": {},
        "legs": {},
        "feet": {},
        "leg_pose": {},
    }

    # The cervical column is posterior to the geometric neck center, but avoid
    # pinning it against the rear surface. Forty-two percent forward from the
    # back keeps the pivot anatomical while correcting the overly posterior
    # result visible on deep-chested A-pose characters.
    for name in ("neck1", "neck2"):
        point = result.get(name)
        if not point:
            continue
        interval = _choose_interval(query.axis_intervals(point, "z"), point[2])
        if interval is None:
            continue
        back, front = interval
        target = (point[0], point[1], back + ((front - back) / 3.0))
        result[name] = target
        report["neck"][name] = target

    # Build one truly vertical spine column. Choose a single depth that remains
    # inside every sampled torso section and is as close as possible to the
    # neck-base depth, so spine1 aligns directly beneath neck1 in top view.
    spine_names = ("spine1", "spine3", "spine5")
    spine_points = [result.get(name) for name in spine_names]
    neck_base = result.get("neck1")
    if all(spine_points) and neck_base:
        center_line_x = neck_base[0]
        depth_intervals = []
        for point in spine_points + [neck_base]:
            interval = _choose_interval(
                query.axis_intervals(
                    (center_line_x, point[1], neck_base[2]), "z"
                ),
                neck_base[2],
            )
            if interval is not None:
                depth_intervals.append(interval)
        common_z = neck_base[2]
        if depth_intervals:
            common_back = max(interval[0] for interval in depth_intervals)
            common_front = min(interval[1] for interval in depth_intervals)
            if common_back <= common_front:
                clearance = max(
                    query.diagonal * 0.0005,
                    query.tolerance * 8.0,
                )
                common_z = max(
                    common_back + clearance,
                    min(common_front - clearance, common_z),
                )
        neck_base = (center_line_x, neck_base[1], common_z)
        result["neck1"] = neck_base
        report["neck"]["neck1"] = neck_base
        for name, point in zip(spine_names, spine_points):
            target = (center_line_x, point[1], common_z)
            result[name] = target
            report["spine"][name] = target
        if "spine5_Tip" in result:
            # The tip marks the neck base; neck1 owns the different rotational
            # frame, so both pivots intentionally occupy the same location.
            result["spine5_Tip"] = tuple(neck_base)
            report["spine"]["spine5_Tip"] = tuple(neck_base)

        # Keep the entire cervical/skull chain on the same centerline. Recenter
        # head pivots through their local skull sections so facial projection
        # cannot pull the head joint toward the nose or jaw.
        neck2 = result.get("neck2")
        if neck2:
            result["neck2"] = (center_line_x, neck2[1], neck2[2])
            report["neck"]["neck2"] = result["neck2"]
        for name in ("head1", "head1_Tip"):
            point = result.get(name)
            if not point:
                continue
            interval = _choose_interval(
                query.axis_intervals(
                    (center_line_x, point[1], point[2]), "z"
                ),
                point[2],
            )
            if interval is None:
                continue
            target = (
                center_line_x,
                point[1],
                (interval[0] + interval[1]) * 0.5,
            )
            result[name] = target
            report["neck"][name] = target

    # Locate the red-dot anatomical landmarks along the arm itself: shoulder
    # emergence and elbow constriction. The hand root remains at the distal
    # atlas endpoint, recentered through the wrist volume; selecting the
    # narrowest forearm section puts it visibly proximal to the wrist crease.
    for side in ("l", "r"):
        arm_names = [
            "{0}_upperarm".format(side),
            "{0}_lowerarm".format(side),
            "{0}_hand".format(side),
        ]
        upper = result.get(arm_names[0])
        wrist = result.get(arm_names[2])
        if not upper or not wrist:
            continue
        samples = []
        for step in range(49):
            fraction = step / 48.0
            candidate = tuple(
                upper[axis] + ((wrist[axis] - upper[axis]) * fraction)
                for axis in range(3)
            )
            y_ok = z_ok = False
            for _pass in range(3):
                candidate, _clearance, y_ok = query.recenter_axis(
                    candidate, "y"
                )
                candidate, _clearance, z_ok = query.recenter_axis(
                    candidate, "z"
                )
            if not (y_ok and z_ok and query.point_inside(candidate)):
                continue
            y_interval = _choose_interval(
                query.axis_intervals(candidate, "y"), candidate[1]
            )
            z_interval = _choose_interval(
                query.axis_intervals(candidate, "z"), candidate[2]
            )
            if not y_interval or not z_interval:
                continue
            area = (
                (y_interval[1] - y_interval[0])
                * (z_interval[1] - z_interval[0])
            )
            samples.append((fraction, area, candidate))

        shoulder_samples = [
            item for item in samples if 0.025 <= item[0] <= 0.075
        ]
        elbow_samples = [
            item for item in samples if 0.42 <= item[0] <= 0.62
        ]
        selected = {
            arm_names[0]: min(
                shoulder_samples, key=lambda item: abs(item[0] - 0.05)
            ) if shoulder_samples else None,
            arm_names[1]: min(
                elbow_samples, key=lambda item: item[1]
            ) if elbow_samples else None,
            arm_names[2]: min(
                samples, key=lambda item: abs(item[0] - 1.0)
            ) if samples else None,
        }
        arm_direction = om.MVector(
            wrist[0] - upper[0],
            wrist[1] - upper[1],
            0.0,
        )
        arm_normal = om.MVector(
            -arm_direction.y,
            arm_direction.x,
            0.0,
        )
        if arm_normal.y < 0.0:
            arm_normal *= -1.0
        for name, sample in selected.items():
            if sample is not None:
                target = sample[2]
                if name in (arm_names[1], arm_names[2]):
                    for _pass in range(3):
                        if name == arm_names[2]:
                            target, _clearance, normal_ok = (
                                _place_along_direction_fraction(
                                    query,
                                    target,
                                    arm_normal,
                                    STUDIO_WRIST_DORSAL_FRACTION,
                                )
                            )
                        else:
                            target, _clearance, normal_ok = (
                                _recenter_along_direction(
                                    query,
                                    target,
                                    arm_normal,
                                )
                            )
                        target, _clearance, depth_ok = query.recenter_axis(
                            target, "z"
                        )
                        if not (normal_ok and depth_ok):
                            break
                result[name] = target
                report["arms"][name] = target

    inset = max(query.diagonal * 0.0004, query.tolerance * 8.0)
    sole_y = bounds["min"].y
    sole_probe_y = sole_y + (bounds["height"] * 0.0035)
    for side in ("l", "r"):
        thigh = result.get(side + "_thigh")
        ankle = result.get(side + "_ankle")
        if not thigh or not ankle:
            continue
        section_targets = {}
        for suffix in ("thigh", "knee", "ankle"):
            name = side + "_" + suffix
            point = result.get(name)
            if not point:
                continue
            target_x = point[0]
            # At pelvis height both leg roots share the torso interval, so the
            # authored/inset X location is the meaningful hip socket. Below
            # the pelvis, use the isolated same-side limb interval.
            if suffix != "thigh":
                interval = _same_side_interval(
                    query.axis_intervals(point, "x"), side, center_x, point[0]
                )
                if interval is not None:
                    target_x = (interval[0] + interval[1]) * 0.5

            depth_probe = (target_x, point[1], point[2])
            depth_interval = _choose_interval(
                query.axis_intervals(depth_probe, "z"), point[2]
            )
            target_z = (
                (depth_interval[0] + depth_interval[1]) * 0.5
                if depth_interval is not None else point[2]
            )
            target = (target_x, point[1], target_z)
            if query.point_inside(target):
                section_targets[name] = target

        measured_ankle = section_targets.get(side + "_ankle", ankle)
        vertical_span = max(abs(thigh[1] - ankle[1]), 1.0e-8)
        stance_ratio = (
            abs(
                abs(measured_ankle[0] - center_x)
                - abs(thigh[0] - center_x)
            )
            / vertical_span
        )
        pose_type = "a_pose" if stance_ratio >= 0.025 else "t_pose"
        report["leg_pose"][side] = {
            "type": pose_type,
            "stance_ratio": stance_ratio,
            "classification_source": "same_side_mesh_sections",
            "front_projection": "mesh_centered_leg_plane",
        }
        # Section centering is valid for both leg stances. The pose
        # classification remains useful to downstream orientation/reporting,
        # but must not disable depth fitting on a nominal T-pose character.
        for name, target in section_targets.items():
            result[name] = target
            report["legs"][name] = target

        toe_name = side + "_toe"
        tip_name = side + "_toeTip"
        toe = result.get(toe_name)
        tip = result.get(tip_name)
        if not toe or not tip:
            continue
        toe_interval = _same_side_interval(
            query.axis_intervals(toe, "x"), side, center_x, toe[0]
        )
        if toe_interval is None:
            continue
        toe_x = (toe_interval[0] + toe_interval[1]) * 0.5
        depth_intervals = query.axis_intervals((toe_x, toe[1], toe[2]), "z")
        depth_interval = _choose_interval(depth_intervals, toe[2])
        toe_z = toe[2]
        if depth_interval is not None:
            toe_z = depth_interval[0] + (
                (depth_interval[1] - depth_interval[0]) * 0.88
            )
        toe_target = (toe_x, toe[1], toe_z)
        result[toe_name] = toe_target

        tip_depths = query.axis_intervals((toe_x, sole_probe_y, toe_z), "z")
        tip_z = max(
            (interval[1] for interval in tip_depths),
            default=min(bounds["max"].z, tip[2]),
        ) - inset
        tip_intervals = _same_side_interval(
            query.axis_intervals((toe_x, sole_probe_y, tip_z), "x"),
            side,
            center_x,
            toe_x,
        )
        tip_x = (
            (tip_intervals[0] + tip_intervals[1]) * 0.5
            if tip_intervals is not None else toe_x
        )
        tip_target = (tip_x, sole_y, tip_z)
        result[tip_name] = tip_target
        report["feet"][toe_name] = toe_target
        report["feet"][tip_name] = tip_target

    targets.clear()
    targets.update(result)
    return report


def _fit_studio_feet_to_volume(
    query: MeshInteriorQuery,
    namespace: str = "",
) -> Dict[str, Dict[str, Vector3]]:
    """Derive toe base and tip from each foot's longitudinal mesh interval."""
    result = {}
    inset = max(query.diagonal * 0.0015, query.tolerance * 20.0)
    for side in ("l", "r"):
        ankle_joint = _find_template_joint("{0}_ankle".format(side), namespace)
        toe_joint = _find_template_joint("{0}_toe".format(side), namespace)
        tip_joint = _find_template_joint("{0}_toeTip".format(side), namespace)
        if not ankle_joint or not toe_joint or not tip_joint:
            continue
        ankle = cmds.xform(ankle_joint, query=True, worldSpace=True, translation=True)
        old_toe = cmds.xform(toe_joint, query=True, worldSpace=True, translation=True)
        sole_y = query.bounds["min"][1]
        probe_y = sole_y + ((ankle[1] - sole_y) * 0.18)
        intervals = query.axis_intervals((old_toe[0], probe_y, ankle[2]), "z")
        interval = _choose_interval(intervals, ankle[2])
        if not interval:
            continue
        back, front = interval
        toe_z = back + ((front - back) * 0.72)
        tip_z = front - inset
        targets = {}
        for label, joint, z_value in (
            ("toe", toe_joint, toe_z),
            ("toeTip", tip_joint, tip_z),
        ):
            proposal = (old_toe[0], probe_y, z_value)
            target, _clearance, success = query.recenter_axis(proposal, "y")
            if not success or not query.point_inside(target):
                target, success = query.move_inside(proposal)
            if success:
                _set_joint_world_translation(joint, target)
                targets[label] = target
        if targets:
            result[side] = targets
    return result


def fit_studio_foot_front_flare(
    mesh: str,
    namespace: str = "",
) -> Dict[str, Dict[str, Vector3]]:
    """Recenter each foot joint in its own same-side mesh section.

    Reference toe tips can initially sit beyond the mesh end. Applying this
    correction after containment lets the final foot use the actual local
    footprint instead of a fixed character-height flare.
    """
    query = _cached_mesh_interior_query(mesh)
    bounds = get_mesh_bounds(mesh)
    center_x = bounds["center"].x
    sole_probe_y = bounds["min"].y + (bounds["height"] * 0.0035)
    result = {}
    for side in ("l", "r"):
        targets = {}
        for label in ("toe", "toeTip"):
            joint = _find_template_joint("{0}_{1}".format(side, label), namespace)
            if not joint:
                continue
            point = tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            probe = point
            if label == "toeTip":
                probe = (point[0], sole_probe_y, point[2])
            interval = _same_side_interval(
                query.axis_intervals(probe, "x"),
                side,
                center_x,
                point[0],
            )
            if interval is None:
                continue
            target = (
                (interval[0] + interval[1]) * 0.5,
                point[1],
                point[2],
            )
            _set_joint_world_translation(joint, target)
            targets[label] = target
        if targets:
            result[side] = targets
    return result


def fit_studio_toe_pivots_to_volume(
    mesh: str,
    namespace: str = "",
) -> Dict[str, Dict[str, Vector3]]:
    """Center toe pivots on the full forefoot and toe-end centerline.

    The toe base uses the center of the complete same-side forefoot width, not
    one digit's interval. The terminal helper sits at the center of the toe-end
    line, just inside the longest toe, and barely above the sole
    contact surface.
    """
    query = _cached_mesh_interior_query(mesh)
    center_x = query.bounds["center"].x
    sole_probe_y = query.bounds["min"].y + (query.bounds["height"] * 0.0035)
    vertices = query.mesh_fn.getPoints(om.MSpace.kWorld)
    result = {}

    def _same_side_span(intervals, side):
        direction = 1.0 if side == "l" else -1.0
        same_side = [
            interval for interval in intervals
            if ((((interval[0] + interval[1]) * 0.5) - center_x) * direction) > 0.0
        ]
        if not same_side:
            return None
        return (
            min(interval[0] for interval in same_side),
            max(interval[1] for interval in same_side),
        )

    def _lowest_local_interval(intervals, reference_y):
        local = [
            interval for interval in intervals
            if (interval[1] - interval[0]) <= query.bounds["height"] * 0.06
        ]
        choices = local or list(intervals)
        if not choices:
            return None
        return min(
            choices,
            key=lambda interval: (
                0.0 if interval[0] <= reference_y <= interval[1]
                else min(abs(reference_y - interval[0]), abs(reference_y - interval[1])),
                interval[0],
            ),
        )

    for side in ("l", "r"):
        ankle_joint = _find_template_joint("{0}_ankle".format(side), namespace)
        toe_joint = _find_template_joint("{0}_toe".format(side), namespace)
        tip_joint = _find_template_joint("{0}_toeTip".format(side), namespace)
        if not ankle_joint or not toe_joint or not tip_joint:
            continue
        ankle = tuple(cmds.xform(
            ankle_joint, query=True, worldSpace=True, translation=True
        ))
        toe = tuple(cmds.xform(
            toe_joint, query=True, worldSpace=True, translation=True
        ))
        forward_sign = 1.0 if toe[2] >= ankle[2] else -1.0
        side_direction = 1.0 if side == "l" else -1.0

        foot_vertices = [
            point for point in vertices
            if point.y <= ankle[1]
            and (point.x - center_x) * side_direction > 0.0
        ]
        if foot_vertices:
            terminal_depth = (
                max(point.z for point in foot_vertices)
                if forward_sign > 0.0
                else min(point.z for point in foot_vertices)
            )
        else:
            terminal_depth = tuple(cmds.xform(
                tip_joint, query=True, worldSpace=True, translation=True
            ))[2]

        # Ratios measured from the approved left foot. They preserve the same
        # anatomical placement across meshes while scaling with foot length.
        toe_depth = ankle[2] + ((terminal_depth - ankle[2]) * 0.6386)
        toe_span = _same_side_span(
            query.axis_intervals((toe[0], sole_probe_y, toe_depth), "x"), side
        )
        if toe_span is not None:
            medial_x = toe_span[0] if side == "l" else toe_span[1]
            outward_x = toe_span[1] if side == "l" else toe_span[0]
            toe_x = medial_x + ((outward_x - medial_x) * 0.4124)
        else:
            toe_x = toe[0]
        toe_y_interval = _lowest_local_interval(
            query.axis_intervals((toe_x, toe[1], toe_depth), "y"), toe[1]
        )
        toe_y = (
            toe_y_interval[0] + (
                (toe_y_interval[1] - toe_y_interval[0]) * 0.5093
            )
            if toe_y_interval is not None else toe[1]
        )
        toe_target = (toe_x, toe_y, toe_depth)

        # The approved tip sits near, but not on, the distal mesh boundary.
        tip_depth = toe_depth + (
            (terminal_depth - toe_depth) * 0.9423
        )
        tip_span = _same_side_span(
            query.axis_intervals(
                (toe_target[0], sole_probe_y, tip_depth), "x"
            ),
            side,
        )
        tip_x = (
            (tip_span[0] + tip_span[1]) * 0.5
            if tip_span is not None else toe_target[0]
        )
        # Preserve the artist-approved contact height as a scale-relative sole
        # inset, barely inside the mesh rather than at its volume center.
        sole_inset = max(query.diagonal * 0.0006025, query.tolerance * 5.0)
        tip_y = query.bounds["min"].y + sole_inset
        tip_target = (tip_x, tip_y, tip_depth)

        # The joint placer must retain the visible toe targets after the axis
        # pass. Put toeTip on the anatomical knee-ankle-toe plane so ankle X can
        # aim at toe, toe can bend only around Z, and both offsets stay local-X
        # without silently moving either pivot later.
        knee_joint = _find_template_joint("{0}_knee".format(side), namespace)
        if knee_joint:
            knee = om.MVector(*cmds.xform(
                knee_joint, query=True, worldSpace=True, translation=True
            ))
            ankle_vector = om.MVector(*ankle)
            toe_vector = om.MVector(*toe_target)
            plane_normal = (ankle_vector - knee) ^ (toe_vector - ankle_vector)
            if plane_normal.length() > 1.0e-8:
                plane_normal.normalize()
                tip_vector = om.MVector(*tip_target) - ankle_vector
                # Preserve the fitted sole height while constraining the
                # target to the leg plane; only a horizontal component changes.
                plane_error = tip_vector * plane_normal
                if (
                    abs(plane_normal.x) >= abs(plane_normal.z)
                    and abs(plane_normal.x) > 1.0e-8
                ):
                    tip_vector.x -= plane_error / plane_normal.x
                elif abs(plane_normal.z) > 1.0e-8:
                    tip_vector.z -= plane_error / plane_normal.z
                planar_tip = ankle_vector + tip_vector
                # Retain the small artist-authored lateral offset from the
                # anatomical plane, scaled by ankle-to-toe segment length.
                planar_tip.x += (
                    side_direction * (toe_vector - ankle_vector).length() * 0.006862
                )
                tip_target = (planar_tip.x, planar_tip.y, planar_tip.z)

        _set_joint_world_translation(toe_joint, toe_target)
        _set_joint_world_translation(tip_joint, tip_target)
        result[side] = {"toe": toe_target, "toeTip": tip_target}
    return result


def align_studio_thigh_roots_to_pelvis_depth(
    namespace: str = "",
) -> Dict[str, Vector3]:
    """Align both femoral roots with the pelvis in side view."""
    pelvis = _find_template_joint("pelvis", namespace)
    if not pelvis:
        return {}
    pelvis_position = tuple(cmds.xform(
        pelvis, query=True, worldSpace=True, translation=True
    ))
    result = {}
    for side in ("l", "r"):
        thigh = _find_template_joint("{0}_thigh".format(side), namespace)
        if not thigh:
            continue
        position = tuple(cmds.xform(
            thigh, query=True, worldSpace=True, translation=True
        ))
        target = (position[0], position[1], pelvis_position[2])
        _set_joint_world_translation_preserving_children(thigh, target)
        result[side] = target
    return result


def fit_studio_toe_tips_to_ground(
    namespace: str = "",
    ground_y: float = 0.0,
) -> Dict[str, Vector3]:
    """Put terminal toe pivots on the supplied mesh ground without lateral drift.

    The old extrapolation * (toe_depth / foot_depth) amplified any ankle to toe
    X mismatch and pulled tips across the character centerline. The local foot
    section pass now owns X/Z; this pass changes Y only.
    """
    result = {}
    for side in ("l", "r"):
        ankle = _find_template_joint("{0}_ankle".format(side), namespace)
        toe = _find_template_joint("{0}_toe".format(side), namespace)
        tip = _find_template_joint("{0}_toeTip".format(side), namespace)
        if not ankle or not toe or not tip:
            continue
        ankle_point = tuple(cmds.xform(
            ankle, query=True, worldSpace=True, translation=True
        ))
        toe_point = tuple(cmds.xform(
            toe, query=True, worldSpace=True, translation=True
        ))
        point = tuple(cmds.xform(
            tip, query=True, worldSpace=True, translation=True
        ))
        foot_depth = toe_point[2] - ankle_point[2]
        toe_depth = point[2] - toe_point[2]
        target_x = point[0]
        if abs(foot_depth) > 1.0e-8:
            target_x = toe_point[0] + (
                (toe_point[0] - ankle_point[0])
                * (toe_depth / foot_depth)
            )
        target = (target_x, float(ground_y), point[2])
        _set_joint_world_translation(tip, target)
        result[side] = target
    return result

def fit_studio_pelvis_ridge(
    mesh: str,
    namespace: str = "",
) -> Dict[str, Vector3]:
    """Raise the pelvis branch toward the visible pelvic ridge.

    Pelvis, hipswing, and both femoral roots move by one shared scale-relative
    amount. Every other joint is restored to its original world position so
    the correction does not translate the spine, knees, or detailed branches.
    """
    root = _find_template_joint("origin", namespace)
    names = ("pelvis", "hipswing", "l_thigh", "r_thigh")
    targets = {
        name: _find_template_joint(name, namespace)
        for name in names
    }
    if not root or not all(targets.values()):
        return {}
    if (
        cmds.attributeQuery(PELVIS_RIDGE_STAGE_ATTR, node=root, exists=True)
        and cmds.getAttr(root + "." + PELVIS_RIDGE_STAGE_ATTR) == "fitted"
    ):
        if not cmds.attributeQuery(PELVIS_RIDGE_LIFT_ATTR, node=root, exists=True):
            _set_float_attr(
                root,
                PELVIS_RIDGE_LIFT_ATTR,
                get_mesh_bounds(mesh)["height"]
                * STUDIO_PELVIS_RIDGE_LIFT_HEIGHT_RATIO,
            )
        return {
            name: tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            for name, joint in targets.items()
        }
    query = _cached_mesh_interior_query(mesh)
    bounds = get_mesh_bounds(mesh)
    lift = bounds["height"] * STUDIO_PELVIS_RIDGE_LIFT_HEIGHT_RATIO
    thigh_inset = bounds["height"] * STUDIO_THIGH_INSET_HEIGHT_RATIO
    center_x = bounds["center"].x
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    originals = {
        joint: tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in joints
    }
    chosen_lift = 0.0
    for multiplier in (1.0, 0.75, 0.5, 0.25):
        candidate_lift = lift * multiplier
        pelvis_y = originals[targets["pelvis"]][1] + candidate_lift
        candidates = {}
        for name, joint in targets.items():
            point = originals[joint]
            target_x = point[0]
            if name in ("l_thigh", "r_thigh"):
                offset = point[0] - center_x
                target_x = center_x + math.copysign(
                    max(0.0, abs(offset) - thigh_inset), offset
                )
            candidates[name] = (
                target_x,
                pelvis_y,
                point[2],
            )
        if all(query.point_inside(point) for point in candidates.values()):
            chosen_lift = candidate_lift
            break
    target_nodes = set(targets.values())
    pelvis_y = originals[targets["pelvis"]][1] + chosen_lift
    for joint in sorted(originals, key=lambda node: node.count("|")):
        point = originals[joint]
        if joint in target_nodes:
            name = next(key for key, value in targets.items() if value == joint)
            target_x = point[0]
            if name in ("l_thigh", "r_thigh"):
                offset = point[0] - center_x
                target_x = center_x + math.copysign(
                    max(0.0, abs(offset) - thigh_inset), offset
                )
            point = (target_x, pelvis_y, point[2])
        _set_joint_world_translation(joint, point)
    _fit_studio_twist_segments(namespace)
    _set_string_attr(root, PELVIS_RIDGE_STAGE_ATTR, "fitted")
    _set_float_attr(root, PELVIS_RIDGE_LIFT_ATTR, chosen_lift)
    _set_float_attr(root, PELVIS_RIDGE_THIGH_INSET_ATTR, thigh_inset)
    return {
        name: tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for name, joint in targets.items()
    }


def fit_studio_detail_joints_to_volume(
    mesh: str,
    root: str,
    namespace: str = "",
    preserve_reference_layout: bool = False,
) -> Dict[str, object]:
    """Conform every non-root studio joint to the character volume."""
    query = _cached_mesh_interior_query(mesh)
    twist_joints = _fit_studio_twist_segments(namespace)
    foot_targets = (
        {}
        if preserve_reference_layout
        else _fit_studio_feet_to_volume(query, namespace)
    )
    joints = cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    joints.sort(key=lambda joint: joint.count("|"))
    original_positions = {
        joint: tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        for joint in joints
    }
    targets = {}
    moved_inside = []
    depth_projected = []
    failed = []
    surface_tokens = (
        "eyelidtip", "brow", "lip", "cheek", "nose", "nostril",
        "chin", "mandible", "adams_apple",
    )
    surface_inset = max(query.diagonal * 0.001, query.tolerance * 20.0)
    for joint in joints:
        point = original_positions[joint]
        if query.point_inside(point):
            targets[joint] = point
            continue
        short_name = _short_name(joint).split(":")[-1].lower()
        target = point
        success = False
        if any(token in short_name for token in surface_tokens):
            intervals = query.axis_intervals(point, "z")
            if intervals:
                front_interval = max(intervals, key=lambda interval: interval[1])
                proposal = (point[0], point[1], front_interval[1] - surface_inset)
                if query.point_inside(proposal):
                    target = proposal
                    success = True
                    depth_projected.append(_short_name(joint))
        if not success:
            target, success = _bounded_move_inside(
                query,
                point,
                query.diagonal * 0.035,
            )
        move_distance = (om.MVector(*target) - om.MVector(*point)).length() if success else 0.0
        if success and move_distance <= query.diagonal * 0.12:
            targets[joint] = target
            moved_inside.append(_short_name(joint))
        else:
            targets[joint] = point
            failed.append(_short_name(joint))

    # Parents first, then restore every child to its independent world target.
    # A corrected parent pivot therefore cannot drag an already fitted branch.
    for joint in joints:
        _set_joint_world_translation(joint, targets[joint])

    remaining = []
    for joint in joints:
        point = tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        if not query.point_inside(point):
            remaining.append(_short_name(joint))
    report = {
        "joint_count": len(joints),
        "twist_joints_placed": twist_joints,
        "foot_targets": foot_targets,
        "moved_inside": moved_inside,
        "depth_projected_surface_joints": depth_projected,
        "failed_projection": failed,
        "outside_joints": remaining,
        "inside_count": len(joints) - len(remaining),
    }
    _set_string_attr(root, STUDIO_VOLUME_REPORT_ATTR, json.dumps(report, sort_keys=True))
    return report


def fit_studio_brow_end_joints_to_surface(
    mesh: str,
    root: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Continue each outer brow arc using the approved rig proportions.

    Brow landmarks are independent children of the head, so a generic local
    surface transfer can accidentally fold ``brow_end`` back toward the eye.
    Approved rigs consistently continue outward from brow4 through brow5.
    Preserve that component-wise continuation, then solve only its depth from
    the target face surface.
    """
    del namespace
    mesh = _as_mesh_transform(mesh)
    query = _cached_mesh_interior_query(mesh)
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    by_name = {
        _short_name(joint).split(":")[-1]: joint
        for joint in joints
    }
    vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
    face_count = int(cmds.polyEvaluate(mesh, face=True) or 0)
    selected = [
        (distance, entry)
        for distance, entry in _rank_reference_entries(mesh, require_detail=True)
        if int((entry.get("topology") or {}).get("vertex_count") or 0) == vertex_count
        and int((entry.get("topology") or {}).get("face_count") or 0) == face_count
    ][:5]

    def _median(values: List[float]) -> float:
        values = sorted(float(value) for value in values)
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) * 0.5

    report = {"placed": {}, "reference_cases": []}
    inset = max(query.diagonal * 0.0002, query.tolerance * 8.0)
    for side in ("l", "r"):
        names = [side + "_brow4", side + "_brow5", side + "_brow_end"]
        if not all(name in by_name for name in names):
            continue
        ratio_samples = [[], [], []]
        used_cases = []
        for _distance, entry in selected:
            detail = entry.get("detail_points") or {}
            if not all(name in detail for name in names):
                continue
            p4 = om.MVector(*detail[names[0]])
            p5 = om.MVector(*detail[names[1]])
            end = om.MVector(*detail[names[2]])
            incoming = p5 - p4
            outgoing = end - p5
            valid = True
            for axis in range(3):
                denominator = incoming[axis]
                if abs(denominator) <= 1.0e-8:
                    valid = False
                    break
                ratio_samples[axis].append(outgoing[axis] / denominator)
            if valid:
                used_cases.append(str(entry.get("case_id") or ""))
        if not used_cases or not all(ratio_samples):
            continue
        ratios = [_median(samples) for samples in ratio_samples]
        # Ignore isolated stylized outliers while retaining the direction and
        # relative taper shared by the reference brows.
        ratios[0] = max(0.25, min(ratios[0], 1.0))
        ratios[1] = max(0.5, min(ratios[1], 2.0))
        ratios[2] = max(0.5, min(ratios[2], 2.0))
        p4 = om.MVector(*cmds.xform(by_name[names[0]], query=True, worldSpace=True, translation=True))
        p5 = om.MVector(*cmds.xform(by_name[names[1]], query=True, worldSpace=True, translation=True))
        incoming = p5 - p4
        proposal = om.MVector(*(
            p5[axis] + (incoming[axis] * ratios[axis])
            for axis in range(3)
        ))
        target = (proposal.x, proposal.y, proposal.z)
        intervals = query.axis_intervals(target, "z")
        if intervals:
            front = max(intervals, key=lambda interval: interval[1])[1]
            candidate = (proposal.x, proposal.y, front - inset)
            if query.point_inside(candidate):
                target = candidate
        if not query.point_inside(target):
            target, success = _bounded_move_inside(
                query,
                target,
                query.diagonal * 0.02,
            )
            if not success:
                continue
        old = tuple(cmds.xform(by_name[names[2]], query=True, worldSpace=True, translation=True))
        _set_joint_world_translation(by_name[names[2]], target)
        report["placed"][names[2]] = {
            "before": old,
            "after": target,
            "continuation_ratios": ratios,
        }
        report["reference_cases"].extend(used_cases)
    report["reference_cases"] = list(dict.fromkeys(report["reference_cases"]))
    return report


def fit_studio_brows_from_left_profile(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Transfer the approved left-brow spacing and surface proximity."""
    query = _cached_mesh_interior_query(mesh)
    left_eye = _find_template_joint("l_eye", namespace)
    right_eye = _find_template_joint("r_eye", namespace)
    if not left_eye or not right_eye:
        return {"placed": {}, "placed_count": 0}
    eyes = {
        "l": om.MVector(*cmds.xform(left_eye, query=True, worldSpace=True, translation=True)),
        "r": om.MVector(*cmds.xform(right_eye, query=True, worldSpace=True, translation=True)),
    }
    eye_span = (eyes["l"] - eyes["r"]).length()
    if eye_span <= 1.0e-8:
        return {"placed": {}, "placed_count": 0}
    profile = (
        ("brow1", -0.304294744834, 0.276867506805, -0.000453623706),
        ("brow2", -0.097424419455, 0.308744368946, 0.004099913373),
        ("brow3", 0.079938038254, 0.328820046340, 0.0),
        ("brow4", 0.241085466832, 0.325855463827, 0.0),
        ("brow5", 0.377534105021, 0.274415058573, 0.015164163791),
        ("brow_end", 0.460920972200, 0.126093263325, 0.0),
    )
    placed = {}
    for side, mirror_sign in (("l", 1.0), ("r", -1.0)):
        eye = eyes[side]
        for suffix, lateral, vertical, surface_offset in profile:
            name = "{0}_{1}".format(side, suffix)
            joint = _find_template_joint(name, namespace)
            if not joint:
                continue
            x_value = eye.x + (mirror_sign * lateral * eye_span)
            y_value = eye.y + (vertical * eye_span)
            intervals = query.axis_intervals((x_value, y_value, eye.z), "z")
            if not intervals:
                continue
            front = max(intervals, key=lambda interval: interval[1])[1]
            target = (
                x_value,
                y_value,
                front + (surface_offset * eye_span),
            )
            _set_joint_world_translation_preserving_children(joint, target)
            placed[name] = target
    return {
        "source": "approved_left_brow_profile",
        "placed": placed,
        "placed_count": len(placed),
    }


def fit_studio_brow_arcs_to_surface(
    mesh: str,
    root: str,
    namespace: str = "",
    iterations: int = 4,
    strength: float = 0.35,
) -> Dict[str, object]:
    """Fair each complete brow row into one smooth surface-following arc."""
    mesh = _as_mesh_transform(mesh)
    query = _cached_mesh_interior_query(mesh)
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    by_name = {
        _short_name(joint).split(":")[-1]: joint
        for joint in joints
    }
    scene_brow_targets = solve_scene_brow_mesh_points(mesh)
    if scene_brow_targets:
        placed = {}
        for name, target in scene_brow_targets.items():
            joint = by_name.get(name)
            if not joint:
                continue
            _set_joint_world_translation(joint, target)
            placed[name] = target
        return {
            "source": "scene_brow_meshes",
            "placed": placed,
            "placed_count": len(placed),
        }
    reference_seed_points, reference_cases = solve_reference_detail_points(mesh)
    for side in ("l", "r"):
        seed_names = [
            "{0}_brow{1}".format(side, index) for index in range(1, 6)
        ] + [side + "_brow_end"]
        for name in seed_names:
            if name in by_name and name in reference_seed_points:
                _set_joint_world_translation(by_name[name], reference_seed_points[name])
    endpoint_report = fit_studio_brow_end_joints_to_surface(
        mesh,
        root,
        namespace=namespace,
    )
    iterations = max(0, int(iterations))
    strength = max(0.0, min(float(strength), 1.0))
    inset = max(query.diagonal * 0.0002, query.tolerance * 8.0)

    mesh_points = [
        om.MVector(point)
        for point in query.mesh_fn.getPoints(om.MSpace.kWorld)
    ]
    polygon_counts, polygon_vertices = query.mesh_fn.getVertices()
    adjacency = [set() for _point in mesh_points]
    cursor = 0
    for count in polygon_counts:
        vertices = polygon_vertices[cursor:cursor + count]
        cursor += count
        for index, vertex in enumerate(vertices):
            neighbor = vertices[(index + 1) % count]
            adjacency[vertex].add(neighbor)
            adjacency[neighbor].add(vertex)
    edge_pairs = {}
    edge_iterator = om.MItMeshEdge(_mesh_dag_path(mesh))
    while not edge_iterator.isDone():
        edge_pairs[edge_iterator.index()] = (
            edge_iterator.vertexId(0),
            edge_iterator.vertexId(1),
        )
        edge_iterator.next()

    def _nearest_vertex(point: om.MVector) -> int:
        return min(
            range(len(mesh_points)),
            key=lambda index: (mesh_points[index] - point).length(),
        )

    def _shortest_edge_path(
        start: int,
        end: int,
        graph: Optional[List[set]] = None,
    ) -> List[int]:
        if start == end:
            return [start]
        graph = graph or adjacency
        queue = [(0.0, start)]
        distances = {start: 0.0}
        previous = {}
        while queue:
            distance, vertex = heapq.heappop(queue)
            if distance != distances.get(vertex):
                continue
            if vertex == end:
                break
            for neighbor in graph[vertex]:
                candidate = distance + (
                    mesh_points[neighbor] - mesh_points[vertex]
                ).length()
                if candidate >= distances.get(neighbor, float("inf")):
                    continue
                distances[neighbor] = candidate
                previous[neighbor] = vertex
                heapq.heappush(queue, (candidate, neighbor))
        if end not in previous:
            return [start, end]
        path = [end]
        while path[-1] != start:
            path.append(previous[path[-1]])
        path.reverse()
        return path

    def _closest_polyline_point(
        point: om.MVector,
        polyline: List[om.MVector],
    ) -> Tuple[om.MVector, float]:
        best_point = polyline[0]
        best_distance = (point - best_point).length()
        for start, end in zip(polyline, polyline[1:]):
            segment = end - start
            denominator = segment * segment
            fraction = 0.0 if denominator <= 1.0e-12 else (
                ((point - start) * segment) / denominator
            )
            fraction = max(0.0, min(1.0, fraction))
            candidate = start + (segment * fraction)
            distance = (point - candidate).length()
            if distance < best_distance:
                best_point = candidate
                best_distance = distance
        return best_point, float(best_distance)

    def _roughness(points: List[om.MVector]) -> float:
        length = sum(
            (points[index] - points[index - 1]).length()
            for index in range(1, len(points))
        )
        if length <= 1.0e-8:
            return 0.0
        return float(sum(
            (points[index - 1] - (points[index] * 2.0) + points[index + 1]).length()
            for index in range(1, len(points) - 1)
        ) / length)

    report = {
        "endpoint_fit": endpoint_report,
        "seed_reference_cases": reference_cases,
        "iterations": iterations,
        "strength": strength,
        "sides": {},
    }
    for side in ("l", "r"):
        names = ["{0}_brow{1}".format(side, index) for index in range(1, 6)]
        names.append(side + "_brow_end")
        if not all(name in by_name for name in names):
            continue
        before = [
            om.MVector(*cmds.xform(by_name[name], query=True, worldSpace=True, translation=True))
            for name in names
        ]
        working = list(before)
        for _iteration in range(iterations):
            updated = list(working)
            for index in range(1, len(working) - 1):
                midpoint = (working[index - 1] + working[index + 1]) * 0.5
                updated[index] = (working[index] * (1.0 - strength)) + (midpoint * strength)
            working = updated

        local_tangents = []
        for index, point in enumerate(working):
            if index == 0:
                tangent = working[1] - point
            elif index == len(working) - 1:
                tangent = point - working[index - 1]
            else:
                tangent = working[index + 1] - working[index - 1]
            tangent.normalize()
            local_tangents.append(tangent)

        # A single midpoint seed is ambiguous on the dense facial topology:
        # the immediately lower forehead row can be closer at that one sample.
        # Gather aligned seeds around every brow landmark, expand each into a
        # Maya edge loop, then choose the loop which fits the *whole* arc.
        candidate_seeds = set()
        for point, tangent in zip(working, local_tangents):
            ranked_edges = sorted(
                edge_pairs,
                key=lambda edge_id: (
                    (
                        (
                            mesh_points[edge_pairs[edge_id][0]]
                            + mesh_points[edge_pairs[edge_id][1]]
                        ) * 0.5
                        - point
                    ).length()
                    + (
                        1.0
                        - abs(
                            (
                                mesh_points[edge_pairs[edge_id][1]]
                                - mesh_points[edge_pairs[edge_id][0]]
                            ).normal()
                            * tangent
                        )
                    ) * query.diagonal * 0.01
                ),
            )
            candidate_seeds.update(ranked_edges[:8])

        loop_candidates = {}
        for candidate_seed in candidate_seeds:
            candidate_edges = cmds.polySelect(
                mesh,
                edgeLoop=int(candidate_seed),
                noSelection=True,
            ) or [candidate_seed]
            key = tuple(sorted(int(edge_id) for edge_id in candidate_edges))
            if key in loop_candidates:
                continue
            candidate_vertices = set()
            for edge_id in key:
                pair = edge_pairs.get(edge_id)
                if pair:
                    candidate_vertices.update(pair)
            candidate_points = [mesh_points[index] for index in candidate_vertices]
            if len(candidate_points) < 2:
                continue
            distances = [
                min((point - candidate).length() for candidate in candidate_points)
                for point in working
            ]
            # Worst-landmark error dominates so a loop that is excellent only
            # at the outer brow cannot pull brow1/brow2 onto a lower row.
            score = (max(distances) * 3.0) + sum(distances) / len(distances)
            loop_candidates[key] = (score, int(candidate_seed))

        if loop_candidates:
            loop_key, (_loop_score, seed_edge) = min(
                loop_candidates.items(),
                key=lambda item: (item[1][0], item[1][1]),
            )
            loop_edges = list(loop_key)
        else:
            seed_edge = min(candidate_seeds)
            loop_edges = [seed_edge]
        loop_graph = [set() for _point in mesh_points]
        loop_vertices = set()
        for edge_id in loop_edges:
            pair = edge_pairs.get(int(edge_id))
            if not pair:
                continue
            first, second = pair
            loop_graph[first].add(second)
            loop_graph[second].add(first)
            loop_vertices.update(pair)
        if len(loop_vertices) >= 2:
            start_vertex = min(
                loop_vertices,
                key=lambda index: (mesh_points[index] - working[0]).length(),
            )
            end_vertex = min(
                loop_vertices,
                key=lambda index: (mesh_points[index] - working[-1]).length(),
            )
            edge_vertices = _shortest_edge_path(
                start_vertex,
                end_vertex,
                graph=loop_graph,
            )
        else:
            edge_vertices = [_nearest_vertex(point) for point in working]
        edge_polyline = [mesh_points[index] for index in edge_vertices]
        if len(edge_polyline) < 2:
            edge_polyline = list(working)
        edge_targets = []
        edge_distances_before = []
        for point in working:
            edge_point, edge_distance = _closest_polyline_point(point, edge_polyline)
            edge_targets.append(edge_point)
            edge_distances_before.append(edge_distance)

        targets = []
        failed = []
        for name, proposal in zip(names, edge_targets):
            closest, normal = query.mesh_fn.getClosestPointAndNormal(
                om.MPoint(proposal), om.MSpace.kWorld
            )[:2]
            surface = om.MVector(closest.x, closest.y, closest.z)
            normal = om.MVector(normal)
            target = (surface.x, surface.y, surface.z)
            for direction in (-normal, normal):
                candidate = surface + (direction * inset)
                candidate_tuple = (candidate.x, candidate.y, candidate.z)
                if query.point_inside(candidate_tuple):
                    target = candidate_tuple
                    break
            if not query.point_inside(target):
                target, success = _bounded_move_inside(
                    query,
                    target,
                    query.diagonal * 0.02,
                )
                if not success:
                    failed.append(name)
                    target = tuple(cmds.xform(
                        by_name[name], query=True, worldSpace=True, translation=True
                    ))
            targets.append(target)
        for name, target in zip(names, targets):
            _set_joint_world_translation(by_name[name], target)
        after = [om.MVector(*target) for target in targets]
        report["sides"][side] = {
            "joint_count": len(names),
            "roughness_before": _roughness(before),
            "roughness_after": _roughness(after),
            "edge_path_vertex_count": len(edge_vertices),
            "edge_loop_seed": int(seed_edge),
            "edge_loop_edge_count": len(loop_edges),
            "edge_loop_candidate_count": len(loop_candidates),
            "max_edge_distance_before": max(edge_distances_before or [0.0]),
            "max_edge_distance_after": max(
                _closest_polyline_point(point, edge_polyline)[1]
                for point in after
            ),
            "failed_projection": failed,
            "positions": {
                name: target for name, target in zip(names, targets)
            },
        }
    return report

def fit_studio_lip_joints_to_surface(
    mesh: str,
    namespace: str = "",
    iterations: int = 8,
    strength: float = 1.0,
) -> Dict[str, object]:
    """Author two clean, symmetric lip arcs from mesh-fitted face anchors.

    The approved center and commissure pivots are anchors. Only the four
    intermediate pivots on each half are faired; this prevents the upper and
    lower passes from fighting over their shared corners. The front-view curve
    is an elliptical half-arc. Depth comes from the frontmost facial-shell
    intersection at each clean X/Y sample, rather than a nearest hit that can
    jump to the oral cavity. This keeps the arc smooth in front view and
    registered to the actual lip surface in profile.
    """
    del iterations
    query = _cached_mesh_interior_query(mesh)
    inset = max(query.diagonal * 0.00015, query.tolerance * 6.0)
    strength = max(0.0, min(float(strength), 1.0))
    placed = {}
    roughness = {}
    row_joint_names = {}
    projected = []
    failed_projection = []
    missing_required = []
    max_surface_distance = 0.0

    def _position(name):
        joint = _find_template_joint(name, namespace)
        if not joint:
            return None
        return tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))

    for row in ("upper", "lower"):
        center_name = "c_{0}_lip".format(row)
        center = _position(center_name)
        left_corner = _position("l_lip_corner1")
        right_corner = _position("r_lip_corner1")
        if center is None or left_corner is None or right_corner is None:
            missing_required.extend([
                name for name, point in (
                    (center_name, center),
                    ("l_lip_corner1", left_corner),
                    ("r_lip_corner1", right_corner),
                ) if point is None
            ])
            continue
        final_names = (
            ["r_lip_corner1"]
            + ["r_{0}_lip{1}".format(row, index) for index in (1, 2, 3, 4)]
            + [center_name]
            + ["l_{0}_lip{1}".format(row, index) for index in (4, 3, 2, 1)]
            + ["l_lip_corner1"]
        )
        before = []
        for name in final_names:
            point = _position(name)
            if point is None:
                missing_required.append(name)
                before = []
                break
            before.append(om.MVector(*point))
        if not before:
            continue

        # Author one elliptical half-arc from the center to each approved
        # corner. Equal angular steps give stable spacing and let asymmetric
        # characters retain their own left/right commissure anchors.
        # This is flat at the center and steepens naturally into the commissure,
        # matching the visible vermilion border without dropping the upper row
        # through the mouth opening. Apply the same curve to depth: independent
        # per-joint surface rays reproduce polygon noise in side view, while
        # interpolation between two approved inset anchors stays within the
        # facial volume and produces one coherent three-dimensional arc.
        def _normalized_roughness(points):
            length = sum(
                (points[index] - points[index - 1]).length()
                for index in range(1, len(points))
            )
            if length <= 1.0e-8:
                return 0.0
            return float(sum(
                (points[index - 1] - (points[index] * 2.0) + points[index + 1]).length()
                for index in range(1, len(points) - 1)
            ) / length)

        def _front_roughness(points):
            return _normalized_roughness([
                om.MVector(point.x, point.y, 0.0) for point in points
            ])

        row_joint_names[row] = []
        # Center and corner positions are intentionally not written. They are
        # stable anatomical anchors and the corner is shared by both rows.
        center_value = om.MVector(*center)
        for side, corner in (("l", left_corner), ("r", right_corner)):
            corner_value = om.MVector(*corner)
            for step, index in enumerate((4, 3, 2, 1), 1):
                joint_name = "{0}_{1}_lip{2}".format(side, row, index)
                joint = _find_template_joint(joint_name, namespace)
                if not joint:
                    missing_required.append(joint_name)
                    continue
                current = om.MVector(*_position(joint_name))
                angle = (float(step) / 5.0) * (math.pi * 0.5)
                lateral_fraction = math.sin(angle)
                center_weight = math.cos(angle)
                proposal = om.MVector(
                    center_value.x + (
                        (corner_value.x - center_value.x) * lateral_fraction
                    ),
                    corner_value.y + (
                        (center_value.y - corner_value.y) * center_weight
                    ),
                    corner_value.z + (
                        (center_value.z - corner_value.z) * center_weight
                    ),
                )
                target_vector = (
                    current * (1.0 - strength)
                ) + (proposal * strength)
                # Always use the outermost +Z shell. Around an open mouth,
                # choosing the interval nearest the proposal can select teeth,
                # tongue, or the inner oral wall and pull the joint off the lip.
                intervals = query.axis_intervals(
                    (target_vector.x, target_vector.y, target_vector.z),
                    "z",
                )
                if intervals:
                    target_vector.z = max(
                        interval[1] for interval in intervals
                    ) - inset
                    projected.append(joint_name)
                else:
                    failed_projection.append(joint_name)
                target = (target_vector.x, target_vector.y, target_vector.z)
                _set_joint_world_translation_preserving_children(joint, target)
                placed[joint_name] = target
                row_joint_names[row].append(joint_name)
                closest = query.mesh_fn.getClosestPoint(
                    om.MPoint(target_vector), om.MSpace.kWorld
                )[0]
                max_surface_distance = max(
                    max_surface_distance,
                    float((
                        om.MVector(closest.x, closest.y, closest.z)
                        - target_vector
                    ).length()),
                )

        final_points = []
        for final_name in final_names:
            point = _position(final_name)
            if point is not None:
                final_points.append(om.MVector(*point))
        roughness[row] = {
            "before": _normalized_roughness(before),
            "after": _normalized_roughness(final_points),
            "front_before": _front_roughness(before),
            "front_after": _front_roughness(final_points),
        }
    missing_required = sorted(set(missing_required))
    surface_tolerance = max(inset * 1.5, query.tolerance * 20.0)
    if missing_required:
        cmds.error(
            "Studio lip arc fit is missing required joints: {0}".format(
                ", ".join(missing_required)
            )
        )
    if failed_projection:
        cmds.error(
            "Studio lip arc could not reach the outer facial shell for: {0}".format(
                ", ".join(sorted(set(failed_projection)))
            )
        )
    if len(placed) != 16:
        cmds.error(
            "Studio lip arc placed {0} intermediate joints; expected 16.".format(
                len(placed)
            )
        )
    if max_surface_distance > surface_tolerance:
        cmds.error(
            "Studio lip arc surface distance {0:.6f} exceeded {1:.6f}.".format(
                max_surface_distance, surface_tolerance
            )
        )
    return {
        "placed": placed,
        "placed_count": len(placed),
        "anchors_preserved": [
            "c_upper_lip", "c_lower_lip", "l_lip_corner1", "r_lip_corner1",
        ],
        "row_joint_names": row_joint_names,
        "projected": projected,
        "failed_projection": failed_projection,
        "max_surface_distance": max_surface_distance,
        "surface_tolerance": surface_tolerance,
        "roughness": roughness,
    }


def fit_studio_eyelid_joints_to_surface(
    mesh: str,
    root: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Collapse eyelid roots to each eye and ray their tips onto the lid skin."""
    del namespace
    query = _cached_mesh_interior_query(mesh)
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    by_name = {
        _short_name(joint).split(":")[-1]: joint
        for joint in joints
    }
    base_pattern = re.compile(
        r"^(l|r)_(?:inner|outer|upper|lower)_eyelid\d*$",
        re.IGNORECASE,
    )
    tip_pattern = re.compile(
        r"^(l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$",
        re.IGNORECASE,
    )
    mapped_tips = solve_reference_eyelid_tip_points(mesh)
    mapped_eye_centers = solve_reference_eye_centers(mesh, mapped_tips)
    scene_eye_centers = solve_scene_eye_mesh_centers(mesh)
    mapped_eye_centers.update(scene_eye_centers)
    mapped_tips, smoothing_report = smooth_reference_eyelid_tip_points(mapped_tips)
    inset = max(query.diagonal * 0.0002, query.tolerance * 8.0)
    collapsed = []
    projected = []
    failed = []
    max_surface_distance = 0.0
    for side in ("l", "r"):
        eye = by_name.get(side + "_eye")
        if not eye:
            continue
        eye_name = side + "_eye"
        if eye_name in mapped_eye_centers:
            _set_joint_world_translation(eye, mapped_eye_centers[eye_name])
        center = om.MVector(
            *cmds.xform(eye, query=True, worldSpace=True, translation=True)
        )
        side_bases = [
            (name, joint)
            for name, joint in by_name.items()
            if base_pattern.match(name) and name.lower().startswith(side + "_")
        ]
        for name, joint in side_bases:
            _set_joint_world_translation(joint, (center.x, center.y, center.z))
            collapsed.append(name)

        side_tips = [
            (name, joint)
            for name, joint in by_name.items()
            if tip_pattern.match(name) and name.lower().startswith(side + "_")
        ]
        for name, joint in side_tips:
            proposal = om.MVector(*mapped_tips[name]) if name in mapped_tips else om.MVector(
                *cmds.xform(joint, query=True, worldSpace=True, translation=True)
            )
            direction = proposal - center
            if direction.length() <= 1.0e-8:
                failed.append(name)
                continue
            direction.normalize()
            if name in mapped_tips:
                hits = query._ray_hits(
                    (center.x, center.y, center.z),
                    om.MFloatVector(direction.x, direction.y, direction.z),
                    query.diagonal,
                )
            else:
                hits = query._ray_hits(
                    (center.x, center.y, center.z),
                    om.MFloatVector(direction.x, direction.y, direction.z),
                    query.diagonal,
                )
            if hits:
                hit = min(
                    hits,
                    key=lambda point: (
                        om.MVector(point.x, point.y, point.z) - center
                    ).length(),
                )
                surface = om.MVector(hit.x, hit.y, hit.z)
            else:
                # Extreme infant/elder proportions can make an approved tip
                # direction graze the eyelid mesh.  The transferred proposal
                # is still local, so its closest surface point is a stable
                # fallback and avoids leaving a lid segment unplaced.
                closest = query.mesh_fn.getClosestPoint(
                    om.MPoint(proposal), om.MSpace.kWorld
                )[0]
                surface = om.MVector(closest.x, closest.y, closest.z)
                inward = center - surface
                if inward.length() <= 1.0e-8:
                    failed.append(name)
                    continue
                inward.normalize()
                direction = -inward
            target = surface - (direction * inset)
            _set_joint_world_translation(joint, (target.x, target.y, target.z))
            closest = query.mesh_fn.getClosestPoint(
                om.MPoint(target), om.MSpace.kWorld
            )[0]
            distance = (
                om.MVector(closest.x, closest.y, closest.z) - target
            ).length()
            max_surface_distance = max(max_surface_distance, float(distance))
            projected.append(name)
    return {
        "eye_center_source": (
            "scene_eye_mesh_center"
            if scene_eye_centers
            else "approved_lid_ring_relationship"
        ),
        "eye_centers": mapped_eye_centers,
        "smoothing": smoothing_report,
        "collapsed_root_count": len(collapsed),
        "projected_tip_count": len(projected),
        "failed_projection": failed,
        "max_surface_distance": max_surface_distance,
    }


def orient_studio_single_child_chains(
    root: str,
    namespace: str = "",
) -> Dict[str, float]:
    """Aim local X down every unambiguous one-child studio bone.

    Branch joints retain their authored basis because no single child defines
    a unique aim direction. The origin is also preserved as a world-space
    reference. Every oriented joint is measured after freezing so callers can
    audit the actual evaluated result rather than trusting the command.
    """
    del namespace
    joints = cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    joints.sort(key=lambda node: node.count("|"))
    result = {}
    for joint in joints:
        name = _short_name(joint).split(":")[-1]
        if re.search(r"(?:eyelid|lid)", name, re.IGNORECASE):
            # Their tip positions are mesh-fitted later, so defer their X aim
            # until that final eyelid arc has been placed.
            continue
        children = cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []
        if len(children) != 1:
            continue
        child = children[0]
        origin = om.MVector(
            *cmds.xform(joint, query=True, worldSpace=True, translation=True)
        )
        target = om.MVector(
            *cmds.xform(child, query=True, worldSpace=True, translation=True)
        )
        direction = target - origin
        if direction.length() <= 1.0e-8:
            continue
        _orient_joint_x_to_child(joint, child)
        matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        x_axis = om.MVector(matrix[0], matrix[1], matrix[2]).normal()
        result[_short_name(joint)] = abs(x_axis * direction.normal())
    return result


def orient_studio_eyelid_chains_to_tips(
    root: str,
) -> Dict[str, Dict[str, float]]:
    """Aim each eyelid segment's local +X toward its mesh-fitted tip child.

    The saved Lost Soul Kid rig authors every eyelid tip at positive local X.
    Preserve that convention for both template and mapped fits, after their
    mesh-dependent tip locations are final. Reorientation preserves each tip's
    evaluated world matrix and restores the joint's existing DoF policy.
    """
    if not root or not cmds.objExists(root):
        return {}
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    result = {}
    base_pattern = re.compile(
        r"^[lr]_(?:inner|outer|upper|lower)_eyelid\d*$",
        re.IGNORECASE,
    )
    for joint in joints:
        name = _short_name(joint).split(":")[-1]
        if not base_pattern.match(name):
            continue
        children = cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []
        tips = [
            child for child in children
            if re.search(r"eyelidTip\d*$", _short_name(child), re.IGNORECASE)
        ]
        if len(tips) != 1:
            result[name] = {"skipped": 1.0, "reason_missing_unique_tip": 1.0}
            continue
        tip = tips[0]
        _orient_joint_x_to_child(joint, tip, aim_sign=1.0)
        # Keep the aimed frame animator-facing and compatible with the studio
        # validator; moving JO to rotate preserves the evaluated world frame.
        _move_joint_orientation_to_rotate(joint)
        _move_joint_orientation_to_rotate(tip)
        origin = om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        target = om.MVector(*cmds.xform(
            tip, query=True, worldSpace=True, translation=True
        ))
        direction = target - origin
        matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        x_axis = om.MVector(matrix[0], matrix[1], matrix[2]).normal()
        alignment = (
            float(x_axis * direction.normal())
            if direction.length() > 1.0e-8 else 0.0
        )
        result[name] = {
            "x_toward_tip_alignment": alignment,
            "tip_distance": float(direction.length()),
        }
    return result


def orient_studio_digit_chains(
    mesh: str = "",
    namespace: str = "",
    preserve_positions: bool = False,
    preserve_knuckle_positions: bool = False,
) -> Dict[str, Dict[str, float]]:
    """Center fingertips and author straight, animator-facing digit channels.

    Joint 01 aims at joint 02. Every joint from 02 onward uses signed Translate
    X only (+X left, -X right), and the articulated chain shares one bend
    plane. From joint 02 onward, every digit uses signed local Translate X and
    local Z as its curl axis. The non-thumb local Y basis points toward the
    dorsal side, so positive/negative Z flexes the digit into the dorsal plane.
    Channels remain editable and unlocked.
    """
    query = _cached_mesh_interior_query(mesh) if mesh else None
    result = {}

    def _apply_world_basis_preserving_children(
        joint: str,
        x_axis: om.MVector,
        y_axis: om.MVector,
        z_axis: om.MVector,
    ) -> None:
        origin = om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        detached = []
        for child in cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []:
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            detached.append((
                cmds.parent(child, world=True, absolute=True)[0],
                child_matrix,
            ))
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        for attribute in ("jointOrient", "rotateAxis"):
            if cmds.objExists("{0}.{1}".format(joint, attribute)):
                cmds.setAttr(
                    "{0}.{1}".format(joint, attribute), 0.0, 0.0, 0.0
                )
        rotate_order = int(cmds.getAttr(joint + ".rotateOrder"))
        # Joints with skin weights cannot be frozen with makeIdentity. Keep
        # this operation safe on production rigs by writing the resulting
        # XYZ orientation directly into jointOrient instead.
        cmds.setAttr(joint + ".rotateOrder", 0)
        cmds.xform(joint, worldSpace=True, matrix=[
            x_axis.x, x_axis.y, x_axis.z, 0.0,
            y_axis.x, y_axis.y, y_axis.z, 0.0,
            z_axis.x, z_axis.y, z_axis.z, 0.0,
            origin.x, origin.y, origin.z, 1.0,
        ])
        xyz_rotation = cmds.getAttr(joint + ".rotate")[0]
        cmds.setAttr(joint + ".jointOrient", *xyz_rotation, type="double3")
        cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0, type="double3")
        cmds.setAttr(joint + ".rotateOrder", rotate_order)
        for child, child_matrix in detached:
            if not cmds.objExists(child):
                continue
            child = cmds.parent(child, joint, absolute=True)[0]
            cmds.xform(child, worldSpace=True, matrix=child_matrix)

    def _basis_from_x(
        x_axis: om.MVector,
        hand_axes: Dict[str, om.MVector],
        y_reference: Optional[om.MVector] = None,
        z_reference: Optional[om.MVector] = None,
    ) -> Tuple[om.MVector, om.MVector, om.MVector]:
        x_axis = om.MVector(x_axis).normal()
        if y_reference is not None:
            return _reference_roll_basis(x_axis, y_reference)
        if z_reference is not None:
            # Finger roll is authored from the anatomical palm plane. Project
            # its dorsal normal off the aim axis so local Z exits through the
            # top of every knuckle while X remains exactly down the bone.
            z_axis = om.MVector(z_reference)
            z_axis -= x_axis * (z_axis * x_axis)
            if z_axis.length() > 1.0e-8:
                z_axis.normalize()
                y_axis = z_axis ^ x_axis
                y_axis.normalize()
                z_axis = x_axis ^ y_axis
                z_axis.normalize()
                return x_axis, y_axis, z_axis
        y_axis = om.MVector(hand_axes["y"])
        y_axis -= x_axis * (y_axis * x_axis)
        if y_axis.length() <= 1.0e-8:
            y_axis = om.MVector(hand_axes["z"])
            y_axis -= x_axis * (y_axis * x_axis)
        y_axis.normalize()
        z_axis = x_axis ^ y_axis
        z_axis.normalize()
        y_axis = z_axis ^ x_axis
        y_axis.normalize()
        if z_axis * hand_axes["z"] < 0.0:
            y_axis *= -1.0
            z_axis *= -1.0
        return x_axis, y_axis, z_axis

    def _mesh_centered_tip(
        chain: List[str],
        hand_axes: Dict[str, om.MVector],
    ) -> Tuple[om.MVector, bool]:
        base = om.MVector(*cmds.xform(
            chain[1], query=True, worldSpace=True, translation=True
        ))
        tip = om.MVector(*cmds.xform(
            chain[-1], query=True, worldSpace=True, translation=True
        ))
        if query is None:
            return tip, False
        reach_direction = tip - base
        if reach_direction.length() <= 1.0e-8:
            return tip, False
        reach_direction.normalize()

        # Keep the authored reach unless it crosses the actual fingertip cap.
        hits = query._ray_hits(
            (base.x, base.y, base.z),
            om.MFloatVector(
                reach_direction.x, reach_direction.y, reach_direction.z
            ),
            query.diagonal,
        )
        distances = sorted(
            (om.MVector(hit.x, hit.y, hit.z) - base) * reach_direction
            for hit in hits
            if (om.MVector(hit.x, hit.y, hit.z) - base) * reach_direction
            > query.tolerance
        )
        authored_distance = (tip - base) * reach_direction
        if distances:
            inset = max(query.diagonal * 0.0015, query.tolerance * 20.0)
            authored_distance = min(
                authored_distance,
                max(0.0, distances[0] - inset),
            )
        centered = base + (reach_direction * authored_distance)

        # Center the terminal inside the real local fingertip cross-section,
        # using directions perpendicular to this particular terminal segment.
        # The base-to-tip reach can differ from the final phalanx on a curved
        # finger, so it is not a valid cross-section normal by itself.
        parent = om.MVector(*cmds.xform(
            chain[-2], query=True, worldSpace=True, translation=True
        ))
        section_direction = tip - parent
        if section_direction.length() <= 1.0e-8:
            section_direction = om.MVector(reach_direction)
        section_direction.normalize()
        up_axis = om.MVector(hand_axes["y"])
        up_axis -= section_direction * (up_axis * section_direction)
        if up_axis.length() <= 1.0e-8:
            return centered, False
        up_axis.normalize()
        side_axis = section_direction ^ up_axis
        side_axis.normalize()
        success = True
        # A finger cap is often slightly asymmetric, so two alternating
        # section-centering passes can leave a visible residual. Iterate to a
        # stable center before finalizing the terminal joint.
        for _pass in range(8):
            value, _clearance, up_ok = _recenter_along_direction(
                query,
                (centered.x, centered.y, centered.z),
                up_axis,
            )
            centered = om.MVector(*value)
            value, _clearance, side_ok = _recenter_along_direction(
                query,
                (centered.x, centered.y, centered.z),
                side_axis,
            )
            centered = om.MVector(*value)
            success = success and up_ok and side_ok
        return centered, bool(success and query.point_inside(centered))

    finger_chains = _studio_finger_chains(namespace)
    dorsal_by_side = {}
    for dorsal_side in ("l", "r"):
        hand = _find_template_joint(
            "{0}_hand".format(dorsal_side), namespace
        )
        if hand and cmds.objExists(hand):
            # Use the fitted hand frame's palm-normal axis as the anatomical
            # dorsal reference. A cross product of averaged finger reach and
            # knuckle spread drifts on splayed or individually curved digits,
            # and can put the curl axis on the back-of-hand instead.
            dorsal = _joint_world_axes(hand)["z"]
            if dorsal.length() > 1.0e-8:
                dorsal.normalize()
                # The studio hand frame's local Z points palmward; dorsal is
                # the opposite side of that normal.
                dorsal *= -1.0
                dorsal_by_side[dorsal_side] = dorsal

    # Solve all reference rolls before editing any parent basis.  This makes
    # the result independent of traversal order and keeps the comparison about
    # the approved local frame rather than the current hand transform.
    template_axes = extract_studio_template_joint_axes()
    desired_x_by_name = {}
    desired_x_sign_by_name = {}
    for chain_name, chain in finger_chains.items():
        side = chain_name.split("_", 1)[0]
        fallback_sign = 1.0 if side == "l" else -1.0
        positions = [
            om.MVector(*cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            for joint in chain
        ]
        for index, joint in enumerate(chain[:-1]):
            child_name = _short_name(chain[index + 1])
            # In Maya's joint hierarchy, the child link's authored local
            # Translate X determines which way the parent's local X points.
            # Use that exact sign per link: the template intentionally has
            # some distal links oriented opposite to their neighbors.
            authored_offset = template_axes.get(child_name, {}).get("translate")
            axis_sign = fallback_sign
            if authored_offset and abs(float(authored_offset[0])) > 1.0e-8:
                axis_sign = 1.0 if float(authored_offset[0]) > 0.0 else -1.0
            segment = (positions[index + 1] - positions[index]) * axis_sign
            if segment.length() > 1.0e-8:
                joint_name = _short_name(joint)
                desired_x_by_name[joint_name] = segment.normal()
                desired_x_sign_by_name[joint_name] = axis_sign
        if len(chain) >= 2:
            terminal_name = _short_name(chain[-1])
            parent_name = _short_name(chain[-2])
            if parent_name in desired_x_by_name:
                desired_x_by_name[terminal_name] = om.MVector(
                    desired_x_by_name[parent_name]
                )
    template_z_by_name = {}
    template_y_by_name = {}
    for joint_name, desired_x in desired_x_by_name.items():
        authored_axes = template_axes.get(joint_name) or {}
        authored_x = authored_axes.get("x")
        if not authored_x:
            continue
        source_x = om.MVector(*authored_x)
        target_x = om.MVector(desired_x).normal()
        for axis_name, axis_result in (
            ("y", template_y_by_name),
            ("z", template_z_by_name),
        ):
            source_axis = authored_axes.get(axis_name)
            if not source_axis:
                continue
            transported = _rotate_vector_between_directions(
                om.MVector(*source_axis), source_x, target_x
            )
            transported -= target_x * (transported * target_x)
            if transported.length() > 1.0e-8:
                transported.normalize()
                axis_result[joint_name] = transported
    # The official rig_template.ma is the authority for local frames. Atlas
    # roll is retained only as a fallback for joints absent from that template.
    reference_roll, reference_ids = solve_reference_joint_roll_vectors(
        mesh,
        desired_x_by_name,
    ) if mesh and not template_axes else ({}, [])
    thumb_knuckle_z = (
        solve_reference_thumb_knuckle_z_vectors(mesh)
        if mesh and not template_axes else {}
    )
    if template_axes:
        reference_ids = [Path(DEFAULT_PLACEMENT_TEMPLATE).stem]

    for chain_name, chain in finger_chains.items():
        if len(chain) < 3:
            continue
        side = chain_name.split("_", 1)[0]
        aim_sign = 1.0 if side == "l" else -1.0
        hand = _find_template_joint("{0}_hand".format(side), namespace)
        if not hand:
            continue
        hand_axes = _joint_world_axes(hand)
        previous_tip = om.MVector(*cmds.xform(
            chain[-1], query=True, worldSpace=True, translation=True
        ))
        centered_tip, centered_ok = _mesh_centered_tip(chain, hand_axes)
        # The selected mesh owns the fingertip cross-section even when the
        # legacy mapped anchors are retained. Preserve all other approved
        # pivots, but let the terminal land at the actual mesh-section center.
        if centered_ok:
            _set_joint_world_translation_preserving_children(
                chain[-1],
                (centered_tip.x, centered_tip.y, centered_tip.z),
            )
        tip_moved = bool(
            centered_ok
            and (centered_tip - previous_tip).length() > 1.0e-8
        )
        digit = chain_name.split("_", 1)[1]
        distal_kink_report = {"applied": False, "reason": "not_needed"}
        if (
            query is not None
            and (preserve_positions or preserve_knuckle_positions)
            and digit in ("index", "middle", "ring", "pinky")
            and len(chain) >= 5
        ):
            # Re-centering a mesh-dependent fingertip can make the final
            # phalanx kink against an otherwise straight authored chain. Ease
            # only a pronounced distal bend, and only when the mesh contains
            # the proposed pivot. Preserve both neighboring pivots and the
            # total length of the last two phalanges.
            before_pivot = om.MVector(*cmds.xform(
                chain[-3], query=True, worldSpace=True, translation=True
            ))
            distal_pivot = om.MVector(*cmds.xform(
                chain[-2], query=True, worldSpace=True, translation=True
            ))
            terminal = om.MVector(*cmds.xform(
                chain[-1], query=True, worldSpace=True, translation=True
            ))
            incoming = before_pivot - distal_pivot
            outgoing = terminal - distal_pivot
            span = terminal - before_pivot
            if (
                incoming.length() > 1.0e-8
                and outgoing.length() > 1.0e-8
                and span.length() > 1.0e-8
            ):
                turn_degrees = math.degrees(math.acos(max(
                    -1.0,
                    min(1.0, float(incoming.normal() * outgoing.normal())),
                )))
                kink_degrees = 180.0 - turn_degrees
                from_length = (distal_pivot - before_pivot).length()
                to_length = (terminal - distal_pivot).length()
                total_length = from_length + to_length
                straight_target = before_pivot + (
                    span * (from_length / max(total_length, 1.0e-8))
                )
                displacement = (straight_target - distal_pivot).length()
                articulated_positions = [om.MVector(*cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                )) for joint in chain[1:]]
                articulated_chord = (
                    articulated_positions[-1] - articulated_positions[0]
                )
                articulated_direction = articulated_chord.normal()
                chord_deviation = max((
                    (
                        point - articulated_positions[0]
                        - articulated_direction * (
                            (point - articulated_positions[0])
                            * articulated_direction
                        )
                    ).length()
                    for point in articulated_positions[1:-1]
                ), default=0.0) / max(articulated_chord.length(), 1.0e-8)
                target_tuple = (
                    straight_target.x, straight_target.y, straight_target.z
                )
                if kink_degrees < 12.0:
                    distal_kink_report = {
                        "applied": False,
                        "reason": "below_kink_threshold",
                        "kink_degrees_before": float(kink_degrees),
                    }
                elif chord_deviation > 0.08:
                    distal_kink_report = {
                        "applied": False,
                        "reason": "authored_curve_preserved",
                        "kink_degrees_before": float(kink_degrees),
                        "chord_deviation_ratio": float(chord_deviation),
                    }
                elif displacement > span.length() * 0.12:
                    distal_kink_report = {
                        "applied": False,
                        "reason": "correction_exceeds_limit",
                        "kink_degrees_before": float(kink_degrees),
                        "displacement": float(displacement),
                    }
                elif not query.point_inside(target_tuple):
                    distal_kink_report = {
                        "applied": False,
                        "reason": "candidate_outside_mesh",
                        "kink_degrees_before": float(kink_degrees),
                    }
                else:
                    _set_joint_world_translation_preserving_children(
                        chain[-2], target_tuple
                    )
                    distal_kink_report = {
                        "applied": True,
                        "reason": "mesh_contained_distal_smoothing",
                        "kink_degrees_before": float(kink_degrees),
                        "displacement": float(displacement),
                    }
        alignment_report = (
            {"applied": False, "reason": "approved_positions_preserved"}
            if preserve_positions or preserve_knuckle_positions
            else (
                {"applied": False, "reason": "authored_thumb_rest_bend_preserved"}
                if digit == "thumb"
                else _align_mild_studio_digit_bend(chain, query=query)
            )
        )
        original_positions = [
            om.MVector(*cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            for joint in chain
        ]

        # The approved template's local Z exits through the thumb knuckle.
        # Do not derive that roll from the 02-04 positions: those pivots are
        # intentionally collinear, so their cross product is numerical noise.
        # Transfer approved Z through the matching surface topology so 01 and
        # 02 follow this character's thumb mound, then share 02's Z through
        # the distal curl chain.
        thumb_shared_z = (
            template_z_by_name.get(_short_name(chain[1]))
            or thumb_knuckle_z.get(_short_name(chain[1]))
            if digit == "thumb" and len(chain) > 1
            else None
        )
        if digit == "thumb" and len(original_positions) >= 4:
            bend_plane_z = (
                original_positions[2] - original_positions[1]
            ) ^ (
                original_positions[3] - original_positions[1]
            )
            if bend_plane_z.length() > 1.0e-8:
                bend_plane_z.normalize()
                if (
                    thumb_shared_z is not None
                    and bend_plane_z * om.MVector(*thumb_shared_z) < 0.0
                ):
                    bend_plane_z *= -1.0
                if thumb_shared_z is None:
                    thumb_shared_z = (
                        bend_plane_z.x, bend_plane_z.y, bend_plane_z.z
                    )
        dorsal = (
            dorsal_by_side.get(side)
            if digit in ("index", "middle", "ring", "pinky")
            else None
        )
        last_basis = None
        for index, joint in enumerate(chain[:-1]):
            segment = original_positions[index + 1] - original_positions[index]
            if segment.length() <= 1.0e-8:
                continue
            joint_name = _short_name(joint)
            aim_sign = desired_x_sign_by_name.get(
                joint_name, 1.0 if side == "l" else -1.0
            )
            z_reference = template_z_by_name.get(joint_name)
            y_reference = template_y_by_name.get(joint_name)
            if y_reference is None:
                y_reference = reference_roll.get(joint_name)
            # Use the template's local Z for dorsal/knuckle-up, with local Y
            # across the digit. Generic anatomical roll is fallback-only.
            if z_reference is None and y_reference is None and digit != "thumb":
                y_reference = dorsal
            if digit == "thumb":
                z_reference = (
                    template_z_by_name.get(joint_name)
                    if index == 1
                    else thumb_shared_z
                )
                if z_reference is None:
                    z_reference = (
                        template_z_by_name.get(joint_name)
                        or thumb_knuckle_z.get(joint_name)
                    )
                if z_reference is not None:
                    y_reference = None
                elif index > 0:
                    y_reference = (
                        template_y_by_name.get(_short_name(chain[1]))
                        or reference_roll.get(_short_name(chain[1]))
                    )
            basis = _basis_from_x(
                segment * aim_sign,
                hand_axes,
                y_reference=y_reference,
                z_reference=z_reference,
            )
            _apply_world_basis_preserving_children(joint, *basis)
            last_basis = basis
        if last_basis is not None:
            terminal_x = om.MVector(last_basis[0])
            terminal_name = _short_name(chain[-1])
            terminal_y = (
                template_y_by_name.get(_short_name(chain[1]))
                or reference_roll.get(_short_name(chain[1]))
                if digit == "thumb"
                else template_y_by_name.get(terminal_name)
                or reference_roll.get(terminal_name)
            )
            terminal_z = template_z_by_name.get(terminal_name)
            terminal_basis = (
                _reference_z_basis(
                    terminal_x,
                    thumb_shared_z or terminal_z,
                )
                if digit == "thumb" and (terminal_z or thumb_shared_z) is not None
                else (
                    _reference_z_basis(terminal_x, terminal_z)
                    if terminal_z is not None
                    else (
                        _reference_roll_basis(terminal_x, terminal_y)
                        if terminal_y is not None else last_basis
                    )
                )
            )
            _apply_world_basis_preserving_children(chain[-1], *terminal_basis)

        # The aim solve above makes these off-axis values numerical noise. Set
        # the authored contract explicitly so thumb 02-04 and finger 02-tip use
        # signed local X translations only.
        for child in chain[1:]:
            for channel in ("translate", "rotate"):
                for axis in "XYZ":
                    plug = "{0}.{1}{2}".format(child, channel, axis)
                    if cmds.objExists(plug) and cmds.getAttr(plug, lock=True):
                        cmds.setAttr(plug, lock=False)
            cmds.setAttr(child + ".translateY", 0.0)
            cmds.setAttr(child + ".translateZ", 0.0)
            cmds.joint(child, edit=True, degreeOfFreedom="xyz")
            _set_string_attr(child, BEND_AXIS_ATTR, "z")
            _set_string_attr(child, BEND_PLANE_ATTR, "finger_local_z_curl")

        if query is None:
            centered_ok = True

        result[chain_name] = {
            "tip_mesh_centered": centered_ok,
            "tip_cross_section_adjusted": tip_moved,
            "minor_bend_alignment": alignment_report,
            "distal_kink_correction": distal_kink_report,
            "shared_thumb_curl_plane": bool(
                digit != "thumb" or thumb_shared_z is not None
            ),
            "topology_longitudinal_reach_preserved": True,
            "approved_positions_preserved": bool(preserve_positions),
            "each_joint_aims_at_child": True,
            "zero_rotation_from_01": True,
            "terminal_rotation_zero": True,
            "translate_x_only_from_02": True,
            "translate_x_sign": aim_sign,
            "translate_x_signs": {
                _short_name(joint): desired_x_sign_by_name.get(
                    _short_name(joint), aim_sign
                )
                for joint in chain[:-1]
            },
            "reference_roll_transferred": bool(
                template_z_by_name or reference_roll
            ),
            "reference_atlases": reference_ids,
        }
    return result


def configure_studio_bend_axes(root: str, namespace: str = "") -> Dict[str, str]:
    """Author one preferred bend axis while leaving all channels editable."""
    configured = {}
    joint_specs = (
        ("spine1", (1.0, 0.0, 0.0), "spine_yz"),
        ("spine3", (1.0, 0.0, 0.0), "spine_yz"),
        ("spine5", (1.0, 0.0, 0.0), "spine_yz"),
    )
    for name, normal, plane_label in joint_specs:
        joint = _find_template_joint(name, namespace)
        axis = _configure_preferred_bend_axis(
            joint,
            normal,
            plane_label,
        ) if joint else None
        if axis:
            configured[name] = axis

    for side in ("l", "r"):
        name = "{0}_knee".format(side)
        joint = _find_template_joint(name, namespace)
        if joint and cmds.objExists(joint):
            _set_string_attr(joint, BEND_AXIS_ATTR, "y")
            _set_string_attr(joint, BEND_PLANE_ATTR, "leg_local_y_hinge")
            configured[name] = "y"

    all_joints = [root] + (cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or [])
    finger_pattern = re.compile(r"^(?:l|r)_(?:thumb|index|middle|ring|pinky)_\d+$", re.IGNORECASE)
    for joint in all_joints:
        short_name = _short_name(joint).split(":")[-1]
        if not finger_pattern.match(short_name):
            continue
        index = int(short_name.rsplit("_", 1)[-1])
        digit = short_name.split("_")[1].lower()
        minimum_hinge_index = 2 if digit == "thumb" else 3
        if index < minimum_hinge_index:
            continue
        # Thumb 02-terminal and finger 03-terminal expose the common local-Z
        # curl axis. The final DoF pass authors that hinge while separately
        # unlocking transform channels for direct animation/editing.
        _set_string_attr(joint, BEND_AXIS_ATTR, "z")
        _set_string_attr(joint, BEND_PLANE_ATTR, "finger_local_z_curl")
        configured[short_name] = "z"

    _set_string_attr(
        root,
        BEND_POLICY_ATTR,
        "elbow_reference_axis_knee_y_digit02_terminal_z",
    )
    return configured


def configure_studio_elbow_bend_axes_from_channels(
    namespace: str = "",
) -> Dict[str, str]:
    """Record the project-standard local-Z elbow hinge without locking channels."""
    configured = {}
    for side in ("l", "r"):
        name = "{0}_lowerarm".format(side)
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        axis = "z"
        _set_string_attr(joint, BEND_AXIS_ATTR, axis)
        _set_string_attr(
            joint, BEND_PLANE_ATTR,
            "arm_reference_frame_local_{0}_hinge".format(axis),
        )
        configured[name] = axis
    return configured


def enforce_studio_joint_dof_policy(
    namespace: str = "",
) -> Dict[str, str]:
    """Set animator-facing hinge axes without locking transform channels."""
    configured = {}
    for chain_name, chain in _studio_finger_chains(namespace).items():
        start = 1  # Finger joint 02 onward; thumb joint 02 onward.
        for joint in chain[start:]:
            if not joint or not cmds.objExists(joint):
                continue
            # Record the intended curl axis without leaving transform channels
            # locked; the placer must remain fully editable after every fit.
            _set_string_attr(joint, BEND_AXIS_ATTR, "z")
            _set_string_attr(joint, BEND_PLANE_ATTR, "finger_local_z_curl")
            for channel in ("translate", "rotate"):
                for axis in "XYZ":
                    plug = "{0}.{1}{2}".format(joint, channel, axis)
                    if cmds.objExists(plug) and cmds.getAttr(plug, lock=True):
                        cmds.setAttr(plug, lock=False)
            configured[_short_name(joint)] = "z"
    for side in ("l", "r"):
        knee = _find_template_joint("{0}_knee".format(side), namespace)
        if knee and cmds.objExists(knee):
            _set_string_attr(knee, BEND_AXIS_ATTR, "y")
            _set_string_attr(knee, BEND_PLANE_ATTR, "leg_local_y_hinge")
            for channel in ("translate", "rotate"):
                for axis in "XYZ":
                    plug = "{0}.{1}{2}".format(knee, channel, axis)
                    if cmds.objExists(plug) and cmds.getAttr(plug, lock=True):
                        cmds.setAttr(plug, lock=False)
            configured[_short_name(knee)] = "y"
    return configured


def zero_studio_digit_non_curl_rotations(
    namespace: str = "",
) -> Dict[str, int]:
    """Bake digit rest frames into jointOrient so only curl is in rotateZ."""
    result = {}
    for chain_name, chain in _studio_finger_chains(namespace).items():
        for joint in chain[1:]:
            if not joint or not cmds.objExists(joint):
                continue
            children = []
            for child in cmds.listRelatives(
                joint, children=True, type="joint", fullPath=True
            ) or []:
                matrix = cmds.xform(
                    child, query=True, worldSpace=True, matrix=True
                )
                detached = cmds.parent(child, world=True, absolute=True)[0]
                children.append((detached, matrix))
            cmds.makeIdentity(
                joint, apply=True, translate=False, rotate=True, scale=False
            )
            for child, matrix in children:
                if cmds.objExists(child):
                    child = cmds.parent(child, joint, absolute=True)[0]
                    cmds.xform(child, worldSpace=True, matrix=matrix)
            rotate = tuple(float(value) for value in cmds.getAttr(
                joint + ".rotate"
            )[0])
            result[_short_name(joint)] = int(
                max(abs(value) for value in rotate) <= 1.0e-5
            )
    return result


def enforce_studio_thumb_z_only_rotates(
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Keep thumb 02-terminal animator rotations on the curl channel only.

    Approved thumb pivots can require a multi-axis rest frame under a lowered,
    scaled hand. Store that fitted rest frame in jointOrient, leaving rotate
    channels neutral and local Z available as the sole authored curl channel.
    Child matrices are detached and restored so the operation cannot move any
    descendant pivot.
    """
    result = {}
    for side in ("l", "r"):
        chain = _studio_finger_chains(namespace).get(
            "{0}_thumb".format(side), []
        )
        for joint in chain[1:]:
            child_matrices = [
                (child, cmds.xform(
                    child, query=True, worldSpace=True, matrix=True
                ))
                for child in (
                    cmds.listRelatives(
                        joint, children=True, type="joint", fullPath=True
                    ) or []
                )
            ]
            detached = [
                (cmds.parent(child, world=True, absolute=True)[0], matrix)
                for child, matrix in child_matrices
            ]
            cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
            cmds.makeIdentity(
                joint,
                apply=True,
                translate=False,
                rotate=True,
                scale=False,
            )
            for child, world_matrix in detached:
                if not cmds.objExists(child):
                    continue
                reparented = cmds.parent(child, joint, absolute=True)[0]
                cmds.xform(reparented, worldSpace=True, matrix=world_matrix)
            result[_short_name(joint)] = tuple(float(value) for value in cmds.getAttr(
                joint + ".rotate"
            )[0])
    return result


def capture_studio_template_knee_bend_axes(
    namespace: str = "",
) -> Dict[str, str]:
    """Tag knees with the studio template's authored local-Y hinge."""
    result = {}
    for side in ("l", "r"):
        joint = _find_template_joint("{0}_knee".format(side), namespace)
        if not joint:
            continue
        axis = STUDIO_TEMPLATE_KNEE_BEND_AXIS
        _set_string_attr(joint, TEMPLATE_KNEE_BEND_AXIS_ATTR, axis)
        result[side] = axis
    return result


def _studio_knee_hinge_direction(
    side: str,
    namespace: str = "",
) -> om.MVector:
    """Return the normal of one fitted hip-knee-ankle plane."""
    thigh = _find_template_joint("{0}_thigh".format(side), namespace)
    knee = _find_template_joint("{0}_knee".format(side), namespace)
    ankle = _find_template_joint("{0}_ankle".format(side), namespace)
    if thigh and knee and ankle:
        hip_position = om.MVector(*cmds.xform(
            thigh, query=True, worldSpace=True, translation=True
        ))
        knee_position = om.MVector(*cmds.xform(
            knee, query=True, worldSpace=True, translation=True
        ))
        ankle_position = om.MVector(*cmds.xform(
            ankle, query=True, worldSpace=True, translation=True
        ))
        direction = (
            knee_position - hip_position
        ) ^ (
            ankle_position - knee_position
        )
        if direction.length() > 1.0e-8:
            direction.normalize()
            left = _find_template_joint("l_knee", namespace)
            right = _find_template_joint("r_knee", namespace)
            if left and right:
                lateral = om.MVector(*cmds.xform(
                    left, query=True, worldSpace=True, translation=True
                )) - om.MVector(*cmds.xform(
                    right, query=True, worldSpace=True, translation=True
                ))
                if lateral.length() > 1.0e-8 and direction * lateral < 0.0:
                    direction *= -1.0
            return direction
    left = _find_template_joint("l_knee", namespace)
    right = _find_template_joint("r_knee", namespace)
    if left and right:
        direction = om.MVector(*cmds.xform(
            left, query=True, worldSpace=True, translation=True
        )) - om.MVector(*cmds.xform(
            right, query=True, worldSpace=True, translation=True
        ))
        if direction.length() > 1.0e-8:
            direction.normalize()
            return direction
    return om.MVector(1.0, 0.0, 0.0)


def align_studio_leg_front_projection(
    mesh: str = "",
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Place each knee on its hip-to-ankle line in front view only.

    Knee Y (height) and Z (sagittal depth) remain mesh-fitted. Only lateral X
    is corrected. Front-plane continuity is authoritative even when imperfect
    or asymmetric geometry means the pivot is not the exact kneecap center.
    """
    del mesh
    placed = {}
    for side in ("l", "r"):
        thigh = _find_template_joint("{0}_thigh".format(side), namespace)
        knee = _find_template_joint("{0}_knee".format(side), namespace)
        ankle = _find_template_joint("{0}_ankle".format(side), namespace)
        if not thigh or not knee or not ankle:
            continue
        hip_position = om.MVector(*cmds.xform(
            thigh, query=True, worldSpace=True, translation=True
        ))
        knee_position = om.MVector(*cmds.xform(
            knee, query=True, worldSpace=True, translation=True
        ))
        ankle_position = om.MVector(*cmds.xform(
            ankle, query=True, worldSpace=True, translation=True
        ))
        denominator = ankle_position.y - hip_position.y
        if abs(denominator) <= 1.0e-8:
            continue
        fraction = (knee_position.y - hip_position.y) / denominator
        ideal_x = hip_position.x + (
            (ankle_position.x - hip_position.x) * fraction
        )
        target = (ideal_x, knee_position.y, knee_position.z)
        _set_joint_world_translation_preserving_children(knee, target)
        placed[side] = target
    return placed


def finalize_studio_spine_neck_head(
    mesh: str,
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Reassert the central torso/head line after all detail volume fitting."""
    query = _cached_mesh_interior_query(mesh)
    neck1 = _find_template_joint("neck1", namespace)
    spine_tip = _find_template_joint("spine5_Tip", namespace)
    if not neck1 or not spine_tip:
        return {}
    base = tuple(cmds.xform(
        spine_tip, query=True, worldSpace=True, translation=True
    ))
    placed = {}
    _set_joint_world_translation_preserving_children(neck1, base)
    placed["neck1"] = base
    center_x = base[0]
    for name in ("neck2", "head1", "head1_Tip"):
        joint = _find_template_joint(name, namespace)
        if not joint:
            continue
        point = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        target = (center_x, point[1], point[2])
        if name.startswith("head1"):
            interval = _choose_interval(
                query.axis_intervals(target, "z"), target[2]
            )
            if interval is not None:
                target = (
                    center_x,
                    point[1],
                    (interval[0] + interval[1]) * 0.5,
                )
        _set_joint_world_translation_preserving_children(joint, target)
        placed[name] = target
    return placed


def enforce_studio_neck2_midpoint(
    namespace: str = "",
) -> Optional[Vector3]:
    """Keep neck2 exactly halfway between the final neck1 and head1 pivots."""
    neck1 = _find_template_joint("neck1", namespace)
    neck2 = _find_template_joint("neck2", namespace)
    head1 = _find_template_joint("head1", namespace)
    if not all((neck1, neck2, head1)):
        return None
    neck1_position = cmds.xform(
        neck1, query=True, worldSpace=True, translation=True
    )
    head1_position = cmds.xform(
        head1, query=True, worldSpace=True, translation=True
    )
    target = tuple(
        (float(neck1_position[index]) + float(head1_position[index])) * 0.5
        for index in range(3)
    )
    _set_joint_world_translation_preserving_children(neck2, target)
    return target


def align_studio_center_face_positions(
    mesh: str,
    namespace: str = "",
) -> Dict[str, object]:
    """Place non-lateral facial anchors on the anatomical center plane.

    Capture every target before moving a parent so hierarchy propagation can
    never introduce an X offset into a child such as ``nose_upper``.
    """
    bounds = get_mesh_bounds(mesh)
    spine_tip = _find_template_joint("spine5_Tip", namespace)
    center_x = (
        float(cmds.xform(
            spine_tip, query=True, worldSpace=True, translation=True
        )[0])
        if spine_tip and cmds.objExists(spine_tip)
        else float(bounds["center"].x)
    )
    names = (
        "nose_root", "nose_upper", "nose_tip", "nose_base",
        "c_upper_lip", "c_lower_lip", "upper_teeth", "lower_teeth",
    )
    targets = {}
    joints = {}
    for name in names:
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        point = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        joints[name] = joint
        targets[name] = (center_x, point[1], point[2])
    for name in names:
        joint = joints.get(name)
        if joint:
            _set_joint_world_translation(joint, targets[name])
    return {
        "center_x": center_x,
        "positions": targets,
        "local_translate_x": {
            name: float(cmds.getAttr(joint + ".translateX"))
            for name, joint in joints.items()
        },
    }


def enforce_studio_center_face_local_zeroes(
    namespace: str = "",
    preserve_nose_root_depth: bool = False,
) -> Dict[str, object]:
    """Enforce studio nose local-channel zeroes without moving child branches."""
    result = {}
    for name, axis in (
        ("nose_root", "Z"),
        ("nose_upper", "X"),
        ("nose_tip", "X"),
        ("nose_base", "X"),
    ):
        if name == "nose_root" and preserve_nose_root_depth:
            continue
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        joint = (cmds.ls(joint, long=True) or [joint])[0]
        child_matrices = [
            (child, cmds.xform(child, query=True, worldSpace=True, matrix=True))
            for child in (
                cmds.listRelatives(
                    joint, children=True, type="joint", fullPath=True
                ) or []
            )
        ]
        plug = "{0}.translate{1}".format(joint, axis)
        before = float(cmds.getAttr(plug))
        cmds.setAttr(plug, 0.0)
        for child, world_matrix in child_matrices:
            if cmds.objExists(child):
                cmds.xform(child, worldSpace=True, matrix=world_matrix)
        result[name] = {
            "axis": axis.lower(),
            "before": before,
            "after": float(cmds.getAttr(plug)),
            "preserved_child_count": len(child_matrices),
        }
    return result


def configure_mapped_bend_axes(root: str, joint_map: dict) -> Dict[str, str]:
    """Apply the same hinge policy through user-defined HIK joint mappings."""
    configured = {}
    frame = placement_frame_from_mapping(joint_map)
    hinge_specs = (
        ("LeftForeArm", "LeftHand", "y", (0.0, 0.0, -1.0), "arm_final_pose_plane"),
        ("RightForeArm", "RightHand", "y", (0.0, 0.0, -1.0), "arm_final_pose_plane"),
        ("LeftLeg", "LeftFoot", "x", (0.0, 0.0, 1.0), "leg_final_pose_plane"),
        ("RightLeg", "RightFoot", "x", (0.0, 0.0, 1.0), "leg_final_pose_plane"),
    )
    for slot, child_slot, logical_normal, bend_direction, plane_label in hinge_specs:
        joint = _mapped_joint(joint_map, slot)
        child = _mapped_joint(joint_map, child_slot)
        normal = frame.world_normal(logical_normal)
        if joint and child and cmds.objExists(joint) and cmds.objExists(child):
            joint_position = om.MVector(*cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            child_position = om.MVector(*cmds.xform(
                child, query=True, worldSpace=True, translation=True
            ))
            desired_direction = om.MVector(*bend_direction)
            hinge_direction = (child_position - joint_position) ^ desired_direction
            if hinge_direction.length() > 1.0e-8:
                hinge_direction.normalize()
                normal = (
                    hinge_direction.x,
                    hinge_direction.y,
                    hinge_direction.z,
                )
        axis = _configure_preferred_bend_axis(
            joint,
            normal,
            plane_label,
        ) if joint else None
        if axis:
            configured[slot] = axis

    for slot in ("Spine", "Spine1", "Spine2", "Spine3"):
        joint = _mapped_joint(joint_map, slot)
        axis = _configure_preferred_bend_axis(
            joint, frame.world_normal("x"), "spine_up_depth"
        ) if joint else None
        if axis:
            configured[slot] = axis

    for chain in _mapped_finger_chains(joint_map):
        _project_joint_chain_to_plane(chain)
        for joint in chain[:-1]:
            if not joint or not cmds.objExists(joint):
                continue
            # The official template defines curl as local Z; the mapped
            # hand's current plane normal must not be reinterpreted as Y.
            _set_string_attr(joint, BEND_AXIS_ATTR, "z")
            _set_string_attr(joint, BEND_PLANE_ATTR, "finger_local_z_curl")
            configured[_short_name(joint)] = "z"
    _set_string_attr(root, BEND_POLICY_ATTR, "mapped_planar_prebend_preferred_axis_unlocked")
    return configured


def _joint_translation_is_editable(joint: str) -> bool:
    for axis in "XYZ":
        plug = "{0}.translate{1}".format(joint, axis)
        if cmds.getAttr(plug, lock=True):
            return False
        if cmds.listConnections(plug, source=True, destination=False):
            return False
    return True


def _set_joint_world_translation(joint: str, position: Vector3) -> None:
    """Set a joint pivot in world space without changing its world orientation."""
    selection = om.MSelectionList()
    selection.add(joint)
    transform = om.MFnTransform(selection.getDagPath(0))
    transform.setTranslation(om.MVector(*position), om.MSpace.kWorld)


def _set_joint_world_translation_preserving_children(
    joint: str,
    position: Vector3,
) -> None:
    """Move one joint pivot while leaving every child subtree in world space."""
    child_matrices = [
        (child, cmds.xform(child, query=True, worldSpace=True, matrix=True))
        for child in (
            cmds.listRelatives(
                joint, children=True, type="joint", fullPath=True
            ) or []
        )
    ]
    _set_joint_world_translation(joint, position)
    for child, world_matrix in child_matrices:
        if cmds.objExists(child):
            cmds.xform(child, worldSpace=True, matrix=world_matrix)


def _set_joint_world_basis_preserving_children(
    joint: str,
    basis: Sequence[float],
) -> None:
    """Apply an exact world basis without disturbing any child world pose."""
    if not joint or not cmds.objExists(joint):
        return
    joint = (cmds.ls(joint, long=True) or [joint])[0]
    origin = tuple(cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    ))
    child_matrices = [
        (child, cmds.xform(child, query=True, worldSpace=True, matrix=True))
        for child in (
            cmds.listRelatives(
                joint, children=True, type="joint", fullPath=True
            ) or []
        )
    ]
    detached = [
        (cmds.parent(child, world=True, absolute=True)[0], matrix)
        for child, matrix in child_matrices
    ]
    cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
    cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)
    cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
    if cmds.objExists(joint + ".rotateAxis"):
        cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)
    cmds.xform(
        joint,
        worldSpace=True,
        matrix=list(basis) + [origin[0], origin[1], origin[2], 1.0],
    )
    cmds.makeIdentity(
        joint, apply=True, translate=False, rotate=True, scale=False
    )
    for child, world_matrix in detached:
        if not cmds.objExists(child):
            continue
        reparented = cmds.parent(child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=world_matrix)


def _set_joint_local_rotation_preserving_children(
    joint: str,
    rotation: Vector3,
) -> None:
    """Set exact rotate channels without moving any child branches."""
    if not joint or not cmds.objExists(joint):
        return
    joint = (cmds.ls(joint, long=True) or [joint])[0]
    child_matrices = [
        (child, cmds.xform(child, query=True, worldSpace=True, matrix=True))
        for child in (
            cmds.listRelatives(
                joint, children=True, type="joint", fullPath=True
            ) or []
        )
    ]
    detached = [
        (cmds.parent(child, world=True, absolute=True)[0], matrix)
        for child, matrix in child_matrices
    ]
    cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
    if cmds.objExists(joint + ".rotateAxis"):
        cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)
    cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)
    cmds.setAttr(joint + ".rotate", *rotation)
    for child, world_matrix in detached:
        if not cmds.objExists(child):
            continue
        reparented = cmds.parent(child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=world_matrix)


def _orient_joint_x_to_child(
    joint: str,
    child: str,
    world_up: Vector3 = (0.0, 1.0, 0.0),
    aim_sign: float = 1.0,
) -> None:
    """Aim signed local X at one child without moving its branches.

    Studio arm joints own twist/helper branches in addition to the primary
    chain. Maya's generic hierarchy orient can choose one of those branches
    as its aim target. Detaching every direct child lets us author the parent
    basis explicitly, then absolute reparenting restores every child subtree
    at its original world transform. The requested chain child consequently
    has translation on local X only.
    """
    if not joint or not child or not cmds.objExists(joint) or not cmds.objExists(child):
        return

    joint = (cmds.ls(joint, long=True) or [joint])[0]
    child = (cmds.ls(child, long=True) or [child])[0]
    direct_children = cmds.listRelatives(
        joint, children=True, type="joint", fullPath=True
    ) or []
    if child not in direct_children:
        return

    previous_dof = cmds.joint(joint, query=True, degreeOfFreedom=True) or "xyz"
    if previous_dof != "xyz":
        # Rebuilding an already fitted rig must be able to reorient a hinge
        # that this tool locked on the prior pass. Restore the same policy once
        # the joint basis has been frozen.
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")

    origin = om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
    target = om.MVector(*cmds.xform(child, query=True, worldSpace=True, translation=True))
    x_axis = (target - origin) * (1.0 if aim_sign >= 0.0 else -1.0)
    if x_axis.length() <= 1.0e-8:
        return
    x_axis.normalize()

    up = om.MVector(*world_up)
    up -= x_axis * (up * x_axis)
    if up.length() <= 1.0e-6:
        up = om.MVector(0.0, 0.0, 1.0)
        up -= x_axis * (up * x_axis)
    if up.length() <= 1.0e-6:
        up = om.MVector(1.0, 0.0, 0.0)
        up -= x_axis * (up * x_axis)
    up.normalize()
    z_axis = x_axis ^ up
    z_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()

    detached = []
    for direct_child in direct_children:
        matrix = cmds.xform(direct_child, query=True, worldSpace=True, matrix=True)
        short_name = _short_name(direct_child)
        world_child = cmds.parent(direct_child, world=True, absolute=True)[0]
        detached.append((short_name, world_child, matrix))

    matrix = [
        x_axis.x, x_axis.y, x_axis.z, 0.0,
        y_axis.x, y_axis.y, y_axis.z, 0.0,
        z_axis.x, z_axis.y, z_axis.z, 0.0,
        origin.x, origin.y, origin.z, 1.0,
    ]
    cmds.xform(joint, worldSpace=True, matrix=matrix)
    cmds.makeIdentity(joint, apply=True, translate=False, rotate=True, scale=False)

    for _short, world_child, world_matrix in detached:
        if not cmds.objExists(world_child):
            continue
        reparented = cmds.parent(world_child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=world_matrix)
    if previous_dof != "xyz":
        cmds.joint(joint, edit=True, degreeOfFreedom=previous_dof)


def _orient_joint_x_to_world_direction(
    joint: str,
    direction: Vector3,
    world_up: Vector3 = (0.0, 1.0, 0.0),
) -> None:
    """Aim local X at an explicit world vector while preserving child poses."""
    if not joint or not cmds.objExists(joint):
        return
    joint = (cmds.ls(joint, long=True) or [joint])[0]
    x_axis = om.MVector(*direction)
    if x_axis.length() <= 1.0e-8:
        return
    x_axis.normalize()

    up = om.MVector(*world_up)
    up -= x_axis * (up * x_axis)
    if up.length() <= 1.0e-6:
        up = om.MVector(0.0, 0.0, 1.0)
        up -= x_axis * (up * x_axis)
    if up.length() <= 1.0e-6:
        up = om.MVector(1.0, 0.0, 0.0)
        up -= x_axis * (up * x_axis)
    up.normalize()
    z_axis = x_axis ^ up
    z_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()

    previous_dof = cmds.joint(joint, query=True, degreeOfFreedom=True) or "xyz"
    if previous_dof != "xyz":
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
    origin = om.MVector(
        *cmds.xform(joint, query=True, worldSpace=True, translation=True)
    )
    detached = []
    direct_children = cmds.listRelatives(
        joint, children=True, type="joint", fullPath=True
    ) or []
    for direct_child in direct_children:
        world_matrix = cmds.xform(
            direct_child, query=True, worldSpace=True, matrix=True
        )
        short_name = _short_name(direct_child)
        world_child = cmds.parent(direct_child, world=True, absolute=True)[0]
        detached.append((short_name, world_child, world_matrix))

    matrix = [
        x_axis.x, x_axis.y, x_axis.z, 0.0,
        y_axis.x, y_axis.y, y_axis.z, 0.0,
        z_axis.x, z_axis.y, z_axis.z, 0.0,
        origin.x, origin.y, origin.z, 1.0,
    ]
    cmds.xform(joint, worldSpace=True, matrix=matrix)
    cmds.makeIdentity(
        joint, apply=True, translate=False, rotate=True, scale=False
    )
    for _short, world_child, world_matrix in detached:
        if not cmds.objExists(world_child):
            continue
        reparented = cmds.parent(world_child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=world_matrix)
    if previous_dof != "xyz":
        cmds.joint(joint, edit=True, degreeOfFreedom=previous_dof)


def _orient_joint_with_world_z_hinge(
    joint: str,
    direction: Vector3,
    world_z: Vector3,
) -> None:
    """Aim X as closely as possible down-bone while keeping an exact Z hinge."""
    if not joint or not cmds.objExists(joint):
        return
    joint = (cmds.ls(joint, long=True) or [joint])[0]
    z_axis = om.MVector(*world_z)
    if z_axis.length() <= 1.0e-8:
        return
    z_axis.normalize()
    x_axis = om.MVector(*direction)
    x_axis -= z_axis * (x_axis * z_axis)
    if x_axis.length() <= 1.0e-8:
        return
    x_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()
    origin = om.MVector(*cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    ))
    detached = []
    for child in cmds.listRelatives(
        joint, children=True, type="joint", fullPath=True
    ) or []:
        child_matrix = cmds.xform(
            child, query=True, worldSpace=True, matrix=True
        )
        world_child = cmds.parent(child, world=True, absolute=True)[0]
        detached.append((world_child, child_matrix))
    cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
    cmds.xform(joint, worldSpace=True, matrix=[
        x_axis.x, x_axis.y, x_axis.z, 0.0,
        y_axis.x, y_axis.y, y_axis.z, 0.0,
        z_axis.x, z_axis.y, z_axis.z, 0.0,
        origin.x, origin.y, origin.z, 1.0,
    ])
    cmds.makeIdentity(
        joint, apply=True, translate=False, rotate=True, scale=False
    )
    for child, child_matrix in detached:
        if not cmds.objExists(child):
            continue
        reparented = cmds.parent(child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=child_matrix)


def _move_joint_orientation_to_rotate(
    joint: str,
) -> Tuple[float, float, float]:
    """Preserve a joint's world basis while moving jointOrient onto rotate."""
    if not joint or not cmds.objExists(joint):
        return (0.0, 0.0, 0.0)

    joint = (cmds.ls(joint, long=True) or [joint])[0]
    world_matrix = cmds.xform(
        joint, query=True, worldSpace=True, matrix=True
    )
    detached = []
    for child in cmds.listRelatives(
        joint, children=True, type="joint", fullPath=True
    ) or []:
        child_matrix = cmds.xform(
            child, query=True, worldSpace=True, matrix=True
        )
        world_child = cmds.parent(child, world=True, absolute=True)[0]
        detached.append((world_child, child_matrix))

    cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
    for attribute in ("rotate", "jointOrient", "rotateAxis"):
        if not cmds.objExists("{0}.{1}".format(joint, attribute)):
            continue
        for axis in "XYZ":
            plug = "{0}.{1}{2}".format(joint, attribute, axis)
            try:
                cmds.setAttr(plug, lock=False)
            except (RuntimeError, ValueError):
                pass
        cmds.setAttr("{0}.{1}".format(joint, attribute), 0.0, 0.0, 0.0)

    cmds.xform(joint, worldSpace=True, matrix=world_matrix)

    # Maya can decompose one XYZ matrix to either a compact solution or a
    # three-axis flip such as (-150, 78, 153). The latter appears frequently
    # on lowered/A-pose upper arms. Choose the equivalent solution closest to
    # zero, but retain it only after verifying the world matrix is unchanged.
    if int(cmds.getAttr(joint + ".rotateOrder")) == 0:
        original_rotate = tuple(float(value) for value in cmds.getAttr(
            joint + ".rotate"
        )[0])

        def _bounded_degrees(value):
            return ((float(value) + 180.0) % 360.0) - 180.0

        primary = tuple(_bounded_degrees(value) for value in original_rotate)
        alternate = (
            _bounded_degrees(primary[0] + 180.0),
            _bounded_degrees(180.0 - primary[1]),
            _bounded_degrees(primary[2] + 180.0),
        )
        compact = min(
            (primary, alternate),
            key=lambda values: sum(value * value for value in values),
        )
        cmds.setAttr(joint + ".rotate", *compact)
        compact_world_matrix = cmds.xform(
            joint, query=True, worldSpace=True, matrix=True
        )
        if max(
            abs(float(before) - float(after))
            for before, after in zip(world_matrix, compact_world_matrix)
        ) > 1.0e-6:
            cmds.setAttr(joint + ".rotate", *original_rotate)

    for child, child_matrix in detached:
        if not cmds.objExists(child):
            continue
        reparented = cmds.parent(child, joint, absolute=True)[0]
        cmds.xform(reparented, worldSpace=True, matrix=child_matrix)
    return tuple(
        float(cmds.getAttr("{0}.rotate{1}".format(joint, axis)))
        for axis in "XYZ"
    )


def move_all_studio_joint_orientation_to_rotate(
    root: str,
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Zero jointOrient/rotateAxis everywhere without changing world poses."""
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    for side in ("l", "r"):
        heel = _find_template_joint("{0}_heel_RFL".format(side), namespace)
        if heel:
            joints.append(heel)
            joints.extend(cmds.listRelatives(
                heel, allDescendents=True, type="joint", fullPath=True
            ) or [])
    joints = list(dict.fromkeys(
        (cmds.ls(joint, long=True) or [joint])[0]
        for joint in joints if joint and cmds.objExists(joint)
    ))
    joints.sort(key=lambda node: node.count("|"))
    result = {}
    for joint in joints:
        short_name = _short_name(joint).split(":")[-1]
        # Brows were already authored directly onto rotate channels from a
        # mesh-aware world basis. Re-solving their Euler channels here can
        # introduce several degrees of aim drift under the scaled head chain.
        if re.match(r"^(?:l|r)_brow(?:[1-5]|_end)$", short_name, re.I):
            result[_short_name(joint)] = tuple(
                float(cmds.getAttr("{0}.rotate{1}".format(joint, axis)))
                for axis in "XYZ"
            )
            continue
        result[_short_name(joint)] = _move_joint_orientation_to_rotate(joint)
    return result


def _capture_studio_joint_positions(root: str) -> Dict[str, Vector3]:
    """Capture one stable world-space position per studio joint."""
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    return {
        _short_name(joint).split(":")[-1]: tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        for joint in joints
    }


def _capture_studio_joint_world_matrices(
    root: str,
) -> Dict[str, Sequence[float]]:
    """Capture complete approved joint frames for a deterministic rerun."""
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    return {
        _short_name(joint).split(":")[-1]: tuple(float(value) for value in cmds.xform(
            joint, query=True, worldSpace=True, matrix=True
        ))
        for joint in joints
    }


def _restore_studio_joint_world_matrices(
    root: str,
    matrices: Dict[str, Sequence[float]],
) -> int:
    """Restore full frames parent-first after a clean template rebuild."""
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    joints.sort(key=lambda joint: joint.count("|"))
    restored = 0
    for joint in joints:
        matrix = matrices.get(_short_name(joint).split(":")[-1])
        if matrix is None:
            continue
        cmds.xform(joint, worldSpace=True, matrix=list(matrix))
        restored += 1
    return restored


def _restore_studio_joint_world_positions(
    root: str,
    positions: Dict[str, Vector3],
) -> Dict[str, float]:
    """Restore approved pivots without replacing newly authored orientations.

    Existing studio skeletons are an artist-approved placement source. A
    joint-placer rerun may standardize their axes, but it must not reinterpret
    their anatomy from the mesh. Restore parents first and set every pivot in
    world space so hierarchy compensation cannot accumulate down a chain.
    """
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    joints.sort(key=lambda joint: joint.count("|"))
    restored = 0
    maximum_delta = 0.0
    for joint in joints:
        name = _short_name(joint).split(":")[-1]
        target = positions.get(name)
        if target is None:
            continue
        before = om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        _set_joint_world_translation(joint, target)
        maximum_delta = max(
            maximum_delta,
            (before - om.MVector(*target)).length(),
        )
        restored += 1
    return {
        "restored": restored,
        "maximum_pre_restore_delta": float(maximum_delta),
    }


def validate_studio_final_joint_placement(
    mesh: str,
    root: str,
    fitted_positions: Optional[Dict[str, Vector3]] = None,
    stage: str = "final",
    validate_orientations: bool = False,
    validate_center_face_alignment: bool = True,
    validate_fingertip_centering: bool = True,
    validate_neck2_midpoint: bool = True,
    validate_nose_root_local_zero: bool = True,
) -> Dict[str, object]:
    """Reject post-fit hierarchy drift and grossly displaced joint pivots."""
    bounds = get_mesh_bounds(mesh)
    height = max(float(bounds["height"]), 1.0e-8)
    position_tolerance = max(height * 1.0e-5, 1.0e-5)
    # Rotation values are degrees, not scene units.  Keeping their tolerance
    # tied to the much smaller mesh-position epsilon rejects harmless Euler
    # decomposition residue (for example 0.009 degrees on an otherwise
    # planar elbow) even when the actual frame matches the production atlas.
    rotation_tolerance = 0.02
    fingertip_tolerance = max(
        position_tolerance,
        height * (1.0e-4 if stage == "final" else 1.0e-3),
    )
    bounds_tolerance = max(height * 0.0025, 1.0e-4)
    mesh_query = _cached_mesh_interior_query(mesh)
    current = _capture_studio_joint_positions(root)
    movable_terminals = re.compile(
        r"^(?:l|r)_(?:(?:index|middle|ring|pinky)_05|thumb_04)$",
        re.IGNORECASE,
    )
    drift = {}
    for name, before in (fitted_positions or {}).items():
        after = current.get(name)
        if after is None or movable_terminals.match(name):
            continue
        delta = (om.MVector(*after) - om.MVector(*before)).length()
        if delta > position_tolerance:
            drift[name] = float(delta)

    outside_bounds = {}
    for name, point in current.items():
        if name == "origin":
            continue
        joint_bounds_tolerance = max(
            bounds_tolerance,
            height * 0.01 if name == "head1_Tip" else 0.0,
        )
        if not (
            bounds["min"].x - joint_bounds_tolerance <= point[0]
            <= bounds["max"].x + joint_bounds_tolerance
            and bounds["min"].y - joint_bounds_tolerance <= point[1]
            <= bounds["max"].y + joint_bounds_tolerance
            and bounds["min"].z - joint_bounds_tolerance <= point[2]
            <= bounds["max"].z + joint_bounds_tolerance
        ):
            outside_bounds[name] = point

    orientation_issues = {}
    if validate_orientations:
        root_leaf = root.split("|")[-1]
        root_namespace = root_leaf.rsplit(":", 1)[0] if ":" in root_leaf else ""
        locked_channels = {}
        validation_joints = [root] + (
            cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or []
        )
        for joint in validation_joints:
            locked = []
            for attribute in (
                "translateX", "translateY", "translateZ",
                "rotateX", "rotateY", "rotateZ",
                "scaleX", "scaleY", "scaleZ",
            ):
                plug = "{0}.{1}".format(joint, attribute)
                if cmds.objExists(plug) and cmds.getAttr(plug, lock=True):
                    locked.append(attribute)
            if locked:
                locked_channels[_short_name(joint)] = locked
        if locked_channels:
            orientation_issues["locked_transform_channels"] = locked_channels
        nonzero_orientation_channels = {}
        for joint in validation_joints:
            short_name = _short_name(joint).split(":")[-1]
            joint_orient = tuple(float(value) for value in cmds.getAttr(
                joint + ".jointOrient"
            )[0])
            rotate_axis = tuple(float(value) for value in cmds.getAttr(
                joint + ".rotateAxis"
            )[0])
            articulated_digit_frame = bool(re.match(
                r"^(?:l|r)_(?:thumb_0[1-4]|(?:index|middle|ring|pinky)_0[1-5])$",
                short_name,
                re.IGNORECASE,
            ))
            if (
                (
                    not articulated_digit_frame
                    and max(abs(value) for value in joint_orient) > position_tolerance
                )
                or max(abs(value) for value in rotate_axis) > position_tolerance
            ):
                nonzero_orientation_channels[_short_name(joint)] = {
                    "jointOrient": joint_orient,
                    "rotateAxis": rotate_axis,
                }
        if nonzero_orientation_channels:
            orientation_issues["nonzero_joint_orientation_channels"] = (
                nonzero_orientation_channels
            )
        # The center chain uses X down-bone and one continuous Y-forward
        # convention.  Neck/head roll must match spine5_Tip rather than an
        # unrelated local Euler value, otherwise pose matching twists at the
        # neck boundary.
        spine_tip = _find_template_joint("spine5_Tip", root_namespace)
        spine_forward = (
            _joint_world_axes(spine_tip)["y"]
            if spine_tip else om.MVector(0.0, 0.0, 1.0)
        )
        if spine_forward.length() > 1.0e-8:
            spine_forward.normalize()
        for name in ("neck1", "neck2", "head1", "head1_Tip"):
            joint = _find_template_joint(name, root_namespace)
            if not joint:
                continue
            axes = _joint_world_axes(joint)
            expected_forward = spine_forward - (
                axes["x"] * (spine_forward * axes["x"])
            )
            if expected_forward.length() <= 1.0e-8:
                continue
            expected_forward.normalize()
            forward_dot = float(axes["y"] * expected_forward)
            if forward_dot < 0.999:
                orientation_issues[name + "_forward_y"] = {
                    "spine_forward_y_dot": forward_dot,
                }
        for parent_name, child_name in (
            ("neck1", "neck2"),
            ("neck2", "head1"),
            ("head1", "head1_Tip"),
        ):
            parent = _find_template_joint(parent_name, root_namespace)
            child = _find_template_joint(child_name, root_namespace)
            if not parent or not child:
                continue
            parent_point = om.MVector(*cmds.xform(
                parent, query=True, worldSpace=True, translation=True
            ))
            child_point = om.MVector(*cmds.xform(
                child, query=True, worldSpace=True, translation=True
            ))
            direction = child_point - parent_point
            local_translate = tuple(float(value) for value in cmds.getAttr(
                child + ".translate"
            )[0])
            local_tolerance = max(abs(local_translate[0]), 1.0) * 1.0e-6
            aim_dot = (
                float(_joint_world_axes(parent)["x"] * direction.normal())
                if direction.length() > 1.0e-8 else 0.0
            )
            if (
                aim_dot < 0.999
                or local_translate[0] <= 0.0
                or abs(local_translate[1]) > local_tolerance
                or abs(local_translate[2]) > local_tolerance
            ):
                orientation_issues[parent_name] = {
                    "x_aim_dot": aim_dot,
                    "child_translate": local_translate,
                }
        neck1 = _find_template_joint("neck1", root_namespace)
        neck2 = _find_template_joint("neck2", root_namespace)
        head1 = _find_template_joint("head1", root_namespace)
        if validate_neck2_midpoint and neck1 and neck2 and head1:
            neck1_point = om.MVector(*cmds.xform(
                neck1, query=True, worldSpace=True, translation=True
            ))
            neck2_point = om.MVector(*cmds.xform(
                neck2, query=True, worldSpace=True, translation=True
            ))
            head1_point = om.MVector(*cmds.xform(
                head1, query=True, worldSpace=True, translation=True
            ))
            midpoint_error = (
                neck2_point - ((neck1_point + head1_point) * 0.5)
            ).length()
            neck1_axes = _joint_world_axes(neck1)
            neck2_axes = _joint_world_axes(neck2)
            frame_dots = {
                axis: float(neck1_axes[axis] * neck2_axes[axis])
                for axis in ("x", "y", "z")
            }
            if (
                midpoint_error > position_tolerance
                or min(frame_dots.values()) < 0.999999
            ):
                orientation_issues["neck2_midpoint_frame"] = {
                    "midpoint_error": float(midpoint_error),
                    "neck1_axis_dots": frame_dots,
                }
        center_joint = _find_template_joint("spine5_Tip", root_namespace)
        center_x = (
            float(cmds.xform(
                center_joint, query=True, worldSpace=True, translation=True
            )[0])
            if center_joint else float(bounds["center"].x)
        )
        center_body_names = (
            "spine1", "spine3", "spine5", "spine5_Tip",
            "neck1", "neck2", "head1", "head1_Tip",
        )
        for name in center_body_names:
            joint = _find_template_joint(name, root_namespace)
            if not joint:
                continue
            point_x = float(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            )[0])
            world_x_lean = abs(float(
                _joint_world_axes(joint)["x"] * om.MVector(1.0, 0.0, 0.0)
            ))
            if validate_center_face_alignment and (
                abs(point_x - center_x) > position_tolerance
                or world_x_lean > 1.0e-5
            ):
                orientation_issues[name + "_center_plane"] = {
                    "world_x": point_x,
                    "center_x": center_x,
                    "x_axis_world_x_component": world_x_lean,
                }
        grid_names = (
            "nose_root", "nose_upper", "nose_tip", "nose_base",
            "c_upper_lip", "c_lower_lip", "upper_teeth", "lower_teeth",
        )
        for name in grid_names:
            joint = _find_template_joint(name, root_namespace)
            if not joint:
                continue
            axes = _joint_world_axes(joint)
            dots = (
                float(axes["x"] * om.MVector(1.0, 0.0, 0.0)),
                float(axes["y"] * om.MVector(0.0, 1.0, 0.0)),
                float(axes["z"] * om.MVector(0.0, 0.0, 1.0)),
            )
            point_x = float(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            )[0])
            if validate_center_face_alignment and (
                min(dots) < 0.999999
                or abs(point_x - center_x) > position_tolerance
            ):
                orientation_issues[name + "_grid_alignment"] = {
                    "axis_dots": dots,
                    "world_x": point_x,
                    "center_x": center_x,
                }
        for name, axis in (
            ("nose_root", "Z"),
            ("nose_upper", "X"),
            ("nose_tip", "X"),
            ("nose_base", "X"),
        ):
            if name == "nose_root" and not validate_nose_root_local_zero:
                continue
            joint = _find_template_joint(name, root_namespace)
            if not joint:
                continue
            value = float(cmds.getAttr(
                "{0}.translate{1}".format(joint, axis)
            ))
            if abs(value) > position_tolerance:
                orientation_issues[name + "_local_translate"] = {
                    "axis": axis.lower(),
                    "value": value,
                }
        for side in ("l", "r"):
            aim_sign = 1.0 if side == "l" else -1.0
            names = [
                "{0}_clavicle".format(side),
                "{0}_upperarm".format(side),
                "{0}_lowerarm".format(side),
                "{0}_hand".format(side),
                "{0}_handTip".format(side),
            ]
            chain = [_find_template_joint(name, root_namespace) for name in names]
            desired_x = {}
            for name, parent, child in zip(names[:-1], chain[:-1], chain[1:]):
                if not parent or not child:
                    continue
                segment = om.MVector(*cmds.xform(
                    child, query=True, worldSpace=True, translation=True
                )) - om.MVector(*cmds.xform(
                    parent, query=True, worldSpace=True, translation=True
                ))
                if segment.length() > 1.0e-8:
                    desired_x[name] = segment.normal() * aim_sign
            reference_roll = solve_template_joint_roll_vectors(desired_x)
            segment_dots = {}
            for name, joint in zip(names[:-1], chain[:-1]):
                if not joint or name not in desired_x:
                    continue
                axes = _joint_world_axes(joint)
                dots = {"x": float(axes["x"] * desired_x[name])}
                if name in reference_roll and not name.endswith(
                    ("_thigh", "_knee")
                ):
                    expected = _reference_roll_basis(
                        desired_x[name], reference_roll[name]
                    )
                    dots.update({
                        "y": float(axes["y"] * expected[1]),
                        "z": float(axes["z"] * expected[2]),
                    })
                segment_dots[name] = dots
            signed_x = [
                float(cmds.getAttr(joint + ".translateX"))
                for joint in chain[1:4] if joint
            ]
            expected_sign = 1.0 if side == "l" else -1.0
            elbow_contract = {}
            lowerarm = chain[2]
            hand = chain[3]
            if lowerarm and hand:
                rotate = tuple(float(value) for value in cmds.getAttr(
                    lowerarm + ".rotate"
                )[0])
                joint_orient = tuple(float(value) for value in cmds.getAttr(
                    lowerarm + ".jointOrient"
                )[0])
                rotate_axis = tuple(float(value) for value in cmds.getAttr(
                    lowerarm + ".rotateAxis"
                )[0])
                preferred = tuple(float(value) for value in cmds.getAttr(
                    lowerarm + ".preferredAngle"
                )[0])
                elbow_translate = tuple(float(value) for value in cmds.getAttr(
                    lowerarm + ".translate"
                )[0])
                hand_translate = tuple(float(value) for value in cmds.getAttr(
                    hand + ".translate"
                )[0])
                dof = cmds.joint(
                    lowerarm, query=True, degreeOfFreedom=True
                ) or []
                dof = "".join(dof) if isinstance(dof, (list, tuple)) else str(dof)
                bend_axis = (
                    str(cmds.getAttr(lowerarm + "." + BEND_AXIS_ATTR) or "")
                    if cmds.attributeQuery(BEND_AXIS_ATTR, node=lowerarm, exists=True)
                    else ""
                )
                if (
                    bend_axis.lower() != "z"
                    or abs(elbow_translate[1]) > position_tolerance
                    or abs(elbow_translate[2]) > position_tolerance
                    or abs(hand_translate[1]) > position_tolerance
                    or abs(hand_translate[2]) > position_tolerance
                    or dof.lower() != "xyz"
                ):
                    elbow_contract = {
                        "rotate": rotate,
                        "jointOrient": joint_orient,
                        "rotateAxis": rotate_axis,
                        "preferredAngle": preferred,
                        "elbowTranslate": elbow_translate,
                        "handTranslate": hand_translate,
                        "degreesOfFreedom": dof,
                        "bendAxis": bend_axis,
                    }
            if any(
                min(dots.values()) < 0.98
                for dots in segment_dots.values()
            ) or any(
                value * expected_sign <= 0.0 for value in signed_x
            ) or elbow_contract:
                orientation_issues["{0}_arm_reference_frame".format(side)] = {
                    "axis_dots": segment_dots,
                    "signed_translate_x": signed_x,
                    "elbow_reference_contract": elbow_contract,
                }
        finger_chains = _studio_finger_chains(root_namespace)
        finger_desired_x = {}
        template_axes = extract_studio_template_joint_axes()
        for chain_name, chain in finger_chains.items():
            side = chain_name.split("_", 1)[0]
            for parent, child in zip(chain[:-1], chain[1:]):
                segment = om.MVector(*cmds.xform(
                    child, query=True, worldSpace=True, translation=True
                )) - om.MVector(*cmds.xform(
                    parent, query=True, worldSpace=True, translation=True
                ))
                if segment.length() > 1.0e-8:
                    authored_offset = template_axes.get(
                        _short_name(child), {}
                    ).get("translate")
                    aim_sign = 1.0 if side == "l" else -1.0
                    if (
                        authored_offset
                        and abs(float(authored_offset[0])) > 1.0e-8
                    ):
                        aim_sign = (
                            1.0 if float(authored_offset[0]) > 0.0 else -1.0
                        )
                    finger_desired_x[_short_name(parent)] = (
                        segment.normal() * aim_sign
                    )
            if len(chain) >= 2:
                terminal_name = _short_name(chain[-1])
                parent_name = _short_name(chain[-2])
                if parent_name in finger_desired_x:
                    finger_desired_x[terminal_name] = om.MVector(
                        finger_desired_x[parent_name]
                    )
        thumb_knuckle_z = solve_reference_thumb_knuckle_z_vectors(mesh)
        for chain_name, chain in finger_chains.items():
            side = chain_name.split("_", 1)[0]
            digit = chain_name.split("_", 1)[1]
            thumb_shared_z = None
            if digit == "thumb" and len(chain) > 1:
                thumb_base_name = _short_name(chain[1])
                authored = template_axes.get(thumb_base_name, {})
                authored_x = authored.get("x")
                authored_z = authored.get("z")
                target_x = finger_desired_x.get(thumb_base_name)
                if authored_x and authored_z and target_x is not None:
                    transported = _rotate_vector_between_directions(
                        om.MVector(*authored_z),
                        om.MVector(*authored_x),
                        om.MVector(target_x).normal(),
                    )
                    target_x = om.MVector(target_x).normal()
                    transported -= target_x * (transported * target_x)
                    if transported.length() > 1.0e-8:
                        transported.normalize()
                        thumb_shared_z = (
                            transported.x, transported.y, transported.z
                        )
            if thumb_shared_z is None and digit == "thumb" and len(chain) > 1:
                thumb_shared_z = thumb_knuckle_z.get(_short_name(chain[1]))
            chain_dots = {}
            local_offset_issues = {}
            hinge_issues = {}
            tip_center_issue = {}
            for index, joint in enumerate(chain[1:], start=1):
                name = _short_name(joint)
                if name not in finger_desired_x:
                    continue
                axes = _joint_world_axes(joint)
                dots = {"x": float(axes["x"] * finger_desired_x[name])}
                authored_axes = template_axes.get(name, {})
                authored_x = authored_axes.get("x")
                authored_y = authored_axes.get("y")
                authored_z = authored_axes.get("z")
                reference_axis = (
                    thumb_shared_z if digit == "thumb"
                    else (authored_z or authored_y)
                )
                if reference_axis and (digit == "thumb" or authored_x):
                    target_x = om.MVector(finger_desired_x[name]).normal()
                    transported = (
                        om.MVector(*reference_axis)
                        if digit == "thumb"
                        else _rotate_vector_between_directions(
                            om.MVector(*reference_axis),
                            om.MVector(*authored_x),
                            target_x,
                        )
                    )
                    transported -= target_x * (transported * target_x)
                    if transported.length() > 1.0e-8:
                        transported.normalize()
                        expected = (
                            _reference_z_basis(target_x, transported)
                            if authored_z
                            else _reference_roll_basis(target_x, transported)
                        )
                        dots.update({
                            "y": float(axes["y"] * expected[1]),
                            "z": float(axes["z"] * expected[2]),
                        })
                chain_dots[name] = dots
                if index > 0:
                    translate_y = float(cmds.getAttr(joint + ".translateY"))
                    translate_z = float(cmds.getAttr(joint + ".translateZ"))
                    if (
                        abs(translate_y) > position_tolerance
                        or abs(translate_z) > position_tolerance
                    ):
                        local_offset_issues[name] = (translate_y, translate_z)
            # Every articulated pivot, including the terminal, stays in the
            # shared 02-to-05 curl plane. The terminal is centered first, then
            # its small residual is judged against the mesh-section check.
            planar_chain = chain[1:]
            plane_deviation = _projected_chain_plane_deviation(planar_chain)
            hinge_joints = chain[1:]
            for joint in hinge_joints:
                dof = cmds.joint(
                    joint, query=True, degreeOfFreedom=True
                ) or []
                dof = "".join(dof) if isinstance(dof, (list, tuple)) else str(dof)
                bend_axis = (
                    str(cmds.getAttr(joint + "." + BEND_AXIS_ATTR) or "")
                    if cmds.attributeQuery(BEND_AXIS_ATTR, node=joint, exists=True)
                    else ""
                )
                rotate = tuple(float(value) for value in cmds.getAttr(
                    joint + ".rotate"
                )[0])
                axes = _joint_world_axes(joint)
                shared_plane_dot = 1.0
                standard_frame_dots = None
                joint_name = _short_name(joint)
                desired_x = finger_desired_x.get(joint_name)
                authored_axes = template_axes.get(joint_name, {})
                authored_x = authored_axes.get("x")
                authored_y = authored_axes.get("y")
                authored_z = authored_axes.get("z")
                reference_axis = (
                    thumb_shared_z if digit == "thumb"
                    else (authored_z or authored_y)
                )
                if (
                    desired_x is not None and reference_axis
                    and (digit == "thumb" or authored_x)
                ):
                    target_x = om.MVector(desired_x).normal()
                    transported = (
                        om.MVector(*reference_axis)
                        if digit == "thumb"
                        else _rotate_vector_between_directions(
                            om.MVector(*reference_axis),
                            om.MVector(*authored_x),
                            target_x,
                        )
                    )
                    transported -= target_x * (transported * target_x)
                    if transported.length() > 1.0e-8:
                        transported.normalize()
                        expected = (
                            _reference_z_basis(target_x, transported)
                            if authored_z
                            else _reference_roll_basis(target_x, transported)
                        )
                        if digit == "thumb":
                            shared_plane_dot = float(
                                axes["z"] * expected[2]
                            )
                        standard_frame_dots = {
                            "x": float(axes["x"] * expected[0]),
                            "y": float(axes["y"] * expected[1]),
                            "z": float(axes["z"] * expected[2]),
                        }
                # Do not lock animator channels to enforce curl-axis policy.
                # Maya therefore reports XYZ DOFs while the intended axis is
                # carried by BEND_AXIS_ATTR and the neutral rest frame.
                expected_dof = "xyz"
                if (
                    dof.lower() != expected_dof
                    or bend_axis.lower() != "z"
                    or (
                        digit != "thumb"
                        and (
                            abs(rotate[0]) > position_tolerance
                            or abs(rotate[1]) > position_tolerance
                            or abs(rotate[2]) > position_tolerance
                        )
                    )
                    or (digit == "thumb" and abs(rotate[0]) > position_tolerance)
                    or (digit == "thumb" and abs(rotate[1]) > position_tolerance)
                    or shared_plane_dot < 0.999
                    or (
                        standard_frame_dots is not None
                        and min(standard_frame_dots.values()) < 0.98
                    )
                ):
                    hinge_issues[_short_name(joint)] = {
                        "degreesOfFreedom": dof,
                        "bendAxis": bend_axis,
                        "rotate": rotate,
                        "sharedPlaneZDot": shared_plane_dot,
                        "standardFrameDots": standard_frame_dots,
                    }
            if chain and validate_fingertip_centering:
                tip = chain[-1]
                tip_position = tuple(cmds.xform(
                    tip, query=True, worldSpace=True, translation=True
                ))
                parent_position = tuple(cmds.xform(
                    chain[-2], query=True, worldSpace=True, translation=True
                )) if len(chain) > 1 else tip_position
                direction = om.MVector(*tip_position) - om.MVector(*parent_position)
                hand = _find_template_joint(
                    "{0}_hand".format(chain_name.split("_", 1)[0]),
                    root_namespace,
                )
                if direction.length() > 1.0e-8 and hand:
                    direction.normalize()
                    hand_axes = _joint_world_axes(hand)
                    up_axis = om.MVector(hand_axes["y"])
                    up_axis -= direction * (up_axis * direction)
                    if up_axis.length() > 1.0e-8:
                        up_axis.normalize()
                        side_axis = direction ^ up_axis
                        side_axis.normalize()
                        expected = tip_position
                        success = True
                        for _pass in range(2):
                            expected, _clearance, up_ok = _recenter_along_direction(
                                mesh_query, expected, up_axis
                            )
                            expected, _clearance, side_ok = _recenter_along_direction(
                                mesh_query, expected, side_axis
                            )
                            success = success and up_ok and side_ok
                        offset = om.MVector(*tip_position) - om.MVector(*expected)
                        if success and (
                            abs(offset * up_axis) > fingertip_tolerance
                            or abs(offset * side_axis) > fingertip_tolerance
                        ):
                            tip_center_issue = {
                                "joint": _short_name(tip),
                                "crossSectionOffset": (
                                    float(offset * up_axis),
                                    float(offset * side_axis),
                                ),
                                "expected": tuple(float(value) for value in expected),
                            }
            if any(
                min(dots.values()) < 0.98 for dots in chain_dots.values()
            ) or local_offset_issues or hinge_issues or tip_center_issue or plane_deviation > position_tolerance:
                orientation_issues[chain_name + "_reference_frame"] = {
                    "axis_dots": chain_dots,
                    "off_axis_local_offsets": local_offset_issues,
                    "hinge_dofs": hinge_issues,
                    "fingertip_center": tip_center_issue,
                    "plane_deviation_02_05": plane_deviation,
                }
        for side in ("l", "r"):
            aim_sign = 1.0 if side == "l" else -1.0
            names = [
                "{0}_thigh".format(side),
                "{0}_knee".format(side),
                "{0}_ankle".format(side),
                "{0}_toe".format(side),
                "{0}_toeTip".format(side),
            ]
            chain = [_find_template_joint(name, root_namespace) for name in names]
            desired_x = {}
            for name, parent, child in zip(names[:-1], chain[:-1], chain[1:]):
                if not parent or not child:
                    continue
                segment = om.MVector(*cmds.xform(
                    child, query=True, worldSpace=True, translation=True
                )) - om.MVector(*cmds.xform(
                    parent, query=True, worldSpace=True, translation=True
                ))
                if segment.length() > 1.0e-8:
                    desired_x[name] = segment.normal() * aim_sign
            reference_roll = solve_template_joint_roll_vectors(desired_x)
            segment_dots = {}
            for name, joint in zip(names[:-1], chain[:-1]):
                if not joint or name not in desired_x:
                    continue
                axes = _joint_world_axes(joint)
                dots = {"x": float(axes["x"] * desired_x[name])}
                if name in reference_roll and not name.endswith(
                    ("_thigh", "_knee")
                ):
                    expected = _reference_roll_basis(
                        desired_x[name], reference_roll[name]
                    )
                    dots.update({
                        "y": float(axes["y"] * expected[1]),
                        "z": float(axes["z"] * expected[2]),
                    })
                segment_dots[name] = dots
            signed_x = [
                float(cmds.getAttr(joint + ".translateX"))
                for joint in chain[1:] if joint
            ]
            off_axis_translates = {
                _short_name(joint): tuple(float(value) for value in cmds.getAttr(
                    joint + ".translate"
                )[0])[1:]
                for joint in chain[1:] if joint
                if max(abs(float(value)) for value in cmds.getAttr(
                    joint + ".translate"
                )[0][1:]) > position_tolerance
            }
            knee_contract = {}
            knee = chain[1]
            if knee:
                rotate = tuple(float(value) for value in cmds.getAttr(
                    knee + ".rotate"
                )[0])
                joint_orient = tuple(float(value) for value in cmds.getAttr(
                    knee + ".jointOrient"
                )[0])
                rotate_axis = tuple(float(value) for value in cmds.getAttr(
                    knee + ".rotateAxis"
                )[0])
                preferred = tuple(float(value) for value in cmds.getAttr(
                    knee + ".preferredAngle"
                )[0])
                dof = cmds.joint(knee, query=True, degreeOfFreedom=True) or []
                dof = "".join(dof) if isinstance(dof, (list, tuple)) else str(dof)
                bend_axis = (
                    str(cmds.getAttr(knee + "." + BEND_AXIS_ATTR) or "")
                    if cmds.attributeQuery(BEND_AXIS_ATTR, node=knee, exists=True)
                    else ""
                )
                # Keep transform channels editable; BEND_AXIS_ATTR carries
                # the authored knee-hinge policy without Maya DOF locks.
                expected_dof = "xyz"
                if (
                    abs(rotate[0]) > position_tolerance
                    or abs(rotate[2]) > position_tolerance
                    or max(abs(value) for value in joint_orient) > position_tolerance
                    or max(abs(value) for value in rotate_axis) > position_tolerance
                    or abs(preferred[0]) > position_tolerance
                    or abs(preferred[2]) > position_tolerance
                    or dof.lower() != expected_dof
                    or bend_axis.lower() != "y"
                ):
                    knee_contract = {
                        "rotate": rotate,
                        "jointOrient": joint_orient,
                        "rotateAxis": rotate_axis,
                        "preferredAngle": preferred,
                        "degreesOfFreedom": dof,
                        "bendAxis": bend_axis,
                    }
            expected_sign = 1.0 if side == "l" else -1.0
            if any(
                min(dots.values()) < 0.98
                for dots in segment_dots.values()
            ) or any(
                value * expected_sign <= 0.0 for value in signed_x
            ) or off_axis_translates or knee_contract:
                orientation_issues["{0}_leg_reference_frame".format(side)] = {
                    "axis_dots": segment_dots,
                    "signed_translate_x": signed_x,
                    "off_axis_local_offsets": off_axis_translates,
                    "knee_y_contract": knee_contract,
                }

    if drift or outside_bounds or orientation_issues:
        issues = []
        if drift:
            worst = sorted(
                drift.items(), key=lambda item: item[1], reverse=True
            )[:12]
            issues.append("post-fit drift: {}".format(worst))
        if outside_bounds:
            issues.append("outside mesh bounds: {}".format(
                sorted(outside_bounds)[:24]
            ))
        if orientation_issues:
            issues.append(
                "limb axes or signed local-X offsets differ from template standard: {}".format(
                    sorted(orientation_issues.items())
                )
            )
        raise RuntimeError(
            "Studio joint placement validation failed after {}; ".format(stage)
            + "; ".join(issues)
        )
    return {
        "joint_count": len(current),
        "max_allowed_position_drift": position_tolerance,
        "bounds_tolerance": bounds_tolerance,
        "post_fit_drift_count": 0,
        "outside_bounds_count": 0,
        "limb_orientation_issues": 0,
    }


def orient_studio_arm_chains(
    mesh: str = "",
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Aim arm X axes at placed children and transfer approved template roll.

    Joint placement owns every pivot.  The atlas owns only the relative frame:
    left +X runs down the arm and right -X runs down it, while Y/Z retain the
    same roll used by approved production rigs.  This avoids deriving roll from
    an almost-flat arm triangle, which was unstable and broke pose matching.
    """
    offsets = {}
    for side in ("l", "r"):
        aim_sign = 1.0 if side == "l" else -1.0
        names = [
            "{0}_clavicle".format(side),
            "{0}_upperarm".format(side),
            "{0}_lowerarm".format(side),
            "{0}_hand".format(side),
            "{0}_handTip".format(side),
        ]
        chain = [
            _find_template_joint(name, namespace) for name in names
        ]
        chain = [
            (cmds.ls(joint, long=True) or [joint])[0]
            if joint and cmds.objExists(joint) else None
            for joint in chain
        ]
        desired_x = {}
        for name, parent, child in zip(names[:-1], chain[:-1], chain[1:]):
            if not parent or not child:
                continue
            origin = om.MVector(*cmds.xform(
                parent, query=True, worldSpace=True, translation=True
            ))
            target = om.MVector(*cmds.xform(
                child, query=True, worldSpace=True, translation=True
            ))
            direction = (target - origin) * aim_sign
            if direction.length() > 1.0e-8:
                desired_x[name] = direction.normal()
        if names[-2] in desired_x:
            desired_x[names[-1]] = om.MVector(desired_x[names[-2]])
        reference_roll = solve_template_joint_roll_vectors(desired_x)

        fallback_y = om.MVector(0.0, 1.0, 0.0)
        for name, joint in zip(names, chain):
            x_axis = desired_x.get(name)
            if not joint or x_axis is None:
                continue
            y_axis = reference_roll.get(name)
            if y_axis is None:
                y_axis = om.MVector(fallback_y)
                y_axis -= x_axis * (y_axis * x_axis)
                if y_axis.length() <= 1.0e-8:
                    y_axis = om.MVector(0.0, 0.0, 1.0)
            basis = _reference_roll_basis(x_axis, y_axis)
            _set_joint_world_basis_preserving_children(
                joint,
                [
                    basis[0].x, basis[0].y, basis[0].z, 0.0,
                    basis[1].x, basis[1].y, basis[1].z, 0.0,
                    basis[2].x, basis[2].y, basis[2].z, 0.0,
                ],
            )

        # Every child in the primary arm chain must sit solely on its parent's
        # local X axis. Re-aiming above makes Y/Z numerical noise only.
        for joint in chain[1:]:
            if not joint or not cmds.objExists(joint):
                continue
            cmds.setAttr(joint + ".translateY", 0.0)
            cmds.setAttr(joint + ".translateZ", 0.0)
            offsets[_short_name(joint)] = (
                float(cmds.getAttr(joint + ".translateX")),
                float(cmds.getAttr(joint + ".translateY")),
                float(cmds.getAttr(joint + ".translateZ")),
            )
    return offsets


def orient_studio_leg_reference_frames(
    mesh: str = "",
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Transfer approved leg roll without changing fitted leg/foot pivots."""
    offsets = {}
    for side in ("l", "r"):
        aim_sign = 1.0 if side == "l" else -1.0
        names = [
            "{0}_thigh".format(side),
            "{0}_knee".format(side),
            "{0}_ankle".format(side),
            "{0}_toe".format(side),
            "{0}_toeTip".format(side),
        ]
        chain = [
            _find_template_joint(name, namespace) for name in names
        ]
        chain = [
            (cmds.ls(joint, long=True) or [joint])[0]
            if joint and cmds.objExists(joint) else None
            for joint in chain
        ]
        desired_x = {}
        for name, parent, child in zip(names[:-1], chain[:-1], chain[1:]):
            if not parent or not child:
                continue
            origin = om.MVector(*cmds.xform(
                parent, query=True, worldSpace=True, translation=True
            ))
            target = om.MVector(*cmds.xform(
                child, query=True, worldSpace=True, translation=True
            ))
            direction = (target - origin) * aim_sign
            if direction.length() > 1.0e-8:
                desired_x[name] = direction.normal()
        if names[-2] in desired_x:
            desired_x[names[-1]] = om.MVector(desired_x[names[-2]])
        reference_roll = solve_template_joint_roll_vectors(desired_x)
        for name, joint in zip(names, chain):
            x_axis = desired_x.get(name)
            y_axis = reference_roll.get(name)
            if not joint or x_axis is None or y_axis is None:
                continue
            basis = _reference_roll_basis(x_axis, y_axis)
            _set_joint_world_basis_preserving_children(
                joint,
                [
                    basis[0].x, basis[0].y, basis[0].z, 0.0,
                    basis[1].x, basis[1].y, basis[1].z, 0.0,
                    basis[2].x, basis[2].y, basis[2].z, 0.0,
                ],
            )
        for joint in chain[1:]:
            if not joint or not cmds.objExists(joint):
                continue
            cmds.setAttr(joint + ".translateY", 0.0)
            cmds.setAttr(joint + ".translateZ", 0.0)
            offsets[_short_name(joint)] = (
                float(cmds.getAttr(joint + ".translateX")),
                float(cmds.getAttr(joint + ".translateY")),
                float(cmds.getAttr(joint + ".translateZ")),
            )
    return offsets


def enforce_studio_elbow_z_hinges(
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Preserve the authored arm frame and identify its local bend axis.

    Arm roll is already transferred from approved production rigs by
    :func:`orient_studio_arm_chains`.  Do not rebuild that frame from the
    shoulder/elbow/wrist triangle here: on relaxed arms the triangle can be
    nearly degenerate and its normal can rotate local Y/Z by 90 degrees,
    separating the shoulder and elbow frames from the project standard.
    Preserve the transferred frame and record the dominant local hinge axis.
    """
    result = {}
    for side in ("l", "r"):
        joint = _find_template_joint("{0}_lowerarm".format(side), namespace)
        hand = _find_template_joint("{0}_hand".format(side), namespace)
        if not joint or not hand:
            continue
        joint = (cmds.ls(joint, long=True) or [joint])[0]
        hand = (cmds.ls(hand, long=True) or [hand])[0]
        cmds.setAttr(hand + ".translateY", 0.0)
        cmds.setAttr(hand + ".translateZ", 0.0)

        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        _set_string_attr(joint, BEND_AXIS_ATTR, "z")
        _set_string_attr(joint, BEND_PLANE_ATTR, "arm_reference_frame_pending")
        result[side] = tuple(float(value) for value in cmds.getAttr(
            joint + ".rotate"
        )[0])
    return result

def enforce_studio_knee_y_hinges(
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Express each fitted knee pose exclusively on local rotateY.

    The thigh frame comes from the hip-knee-ankle plane, with local Y normal
    to that plane. Mesh-relative pivots stay fixed while the knee and every
    child through toeTip use signed local Translate X only.
    """
    result = {}
    for side in ("l", "r"):
        thigh = _find_template_joint("{0}_thigh".format(side), namespace)
        knee = _find_template_joint("{0}_knee".format(side), namespace)
        ankle = _find_template_joint("{0}_ankle".format(side), namespace)
        if not thigh or not knee or not ankle:
            continue
        thigh = (cmds.ls(thigh, long=True) or [thigh])[0]
        knee = (cmds.ls(knee, long=True) or [knee])[0]
        ankle = (cmds.ls(ankle, long=True) or [ankle])[0]
        hip_position = om.MVector(*cmds.xform(
            thigh, query=True, worldSpace=True, translation=True
        ))
        knee_position = om.MVector(*cmds.xform(
            knee, query=True, worldSpace=True, translation=True
        ))
        ankle_position = om.MVector(*cmds.xform(
            ankle, query=True, worldSpace=True, translation=True
        ))
        upper_segment = knee_position - hip_position
        lower_segment = ankle_position - knee_position
        if upper_segment.length() <= 1.0e-8 or lower_segment.length() <= 1.0e-8:
            continue

        aim_sign = 1.0 if side == "l" else -1.0
        thigh_axes_before = _joint_world_axes(thigh)
        thigh_x = upper_segment.normal() * aim_sign
        plane_normal = upper_segment ^ lower_segment
        if plane_normal.length() <= 1.0e-8:
            thigh_y = om.MVector(thigh_axes_before["y"])
            thigh_y -= thigh_x * (thigh_y * thigh_x)
        else:
            thigh_y = plane_normal.normal()
        if thigh_y.length() <= 1.0e-8:
            continue
        thigh_y.normalize()
        thigh_z = thigh_x ^ thigh_y
        thigh_z.normalize()
        thigh_y = thigh_z ^ thigh_x
        thigh_y.normalize()
        if thigh_y * thigh_axes_before["y"] < 0.0:
            thigh_y *= -1.0
            thigh_z *= -1.0
        _set_joint_world_basis_preserving_children(
            thigh,
            [
                thigh_x.x, thigh_x.y, thigh_x.z, 0.0,
                thigh_y.x, thigh_y.y, thigh_y.z, 0.0,
                thigh_z.x, thigh_z.y, thigh_z.z, 0.0,
            ],
        )
        cmds.setAttr(knee + ".translateY", 0.0)
        cmds.setAttr(knee + ".translateZ", 0.0)

        detached = []
        for child in cmds.listRelatives(knee, children=True, fullPath=True) or []:
            if cmds.nodeType(child) not in ("joint", "transform"):
                continue
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            world_child = cmds.parent(child, world=True, absolute=True)[0]
            detached.append((world_child, child_matrix))

        for attribute in ("rotate", "jointOrient", "rotateAxis"):
            if cmds.objExists("{0}.{1}".format(knee, attribute)):
                cmds.setAttr(
                    "{0}.{1}".format(knee, attribute), 0.0, 0.0, 0.0
                )
        desired_x = lower_segment.normal() * aim_sign
        thigh_axes = _joint_world_axes(thigh)
        local_x = desired_x * thigh_axes["x"]
        local_z = desired_x * thigh_axes["z"]
        base_angle = math.degrees(math.atan2(local_z, local_x))
        candidates = (
            base_angle, -base_angle,
            base_angle + 180.0, base_angle - 180.0,
            -base_angle + 180.0, -base_angle - 180.0,
        )
        best_angle = 0.0
        best_alignment = -2.0
        for candidate in candidates:
            cmds.setAttr(knee + ".rotate", 0.0, candidate, 0.0)
            alignment = _joint_world_axes(knee)["x"] * desired_x
            if alignment > best_alignment:
                best_alignment = alignment
                best_angle = candidate
        cmds.setAttr(knee + ".rotate", 0.0, best_angle, 0.0)
        # Bend policy is metadata/orientation, never a channel lock.
        cmds.joint(knee, edit=True, degreeOfFreedom="xyz")
        cmds.setAttr(knee + ".preferredAngleX", 0.0)
        cmds.setAttr(knee + ".preferredAngleY", best_angle)
        cmds.setAttr(knee + ".preferredAngleZ", 0.0)

        for child, child_matrix in detached:
            if not cmds.objExists(child):
                continue
            reparented = cmds.parent(child, knee, absolute=True)[0]
            cmds.xform(reparented, worldSpace=True, matrix=child_matrix)

        for name in ("ankle", "toe", "toeTip"):
            joint = _find_template_joint("{0}_{1}".format(side, name), namespace)
            if joint and cmds.objExists(joint):
                cmds.setAttr(joint + ".translateY", 0.0)
                cmds.setAttr(joint + ".translateZ", 0.0)
        result[side] = (0.0, best_angle, 0.0)
    return result


def orient_studio_spine_vertical(namespace: str = "") -> Dict[str, float]:
    """Give every spine pivot one identical scene-vertical world basis."""
    result = {}
    vertical_matrix = [
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        1.0, 0.0, 0.0, 0.0,
    ]
    for name in ("spine1", "spine3", "spine5", "spine5_Tip"):
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        joint = (cmds.ls(joint, long=True) or [joint])[0]
        origin = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        detached = []
        for child in cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []:
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            world_child = cmds.parent(child, world=True, absolute=True)[0]
            detached.append((world_child, child_matrix))
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)
        if cmds.objExists(joint + ".rotateAxis"):
            cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)
        cmds.xform(
            joint,
            worldSpace=True,
            matrix=vertical_matrix + [origin[0], origin[1], origin[2], 1.0],
        )
        for child, child_matrix in detached:
            if not cmds.objExists(child):
                continue
            reparented = cmds.parent(child, joint, absolute=True)[0]
            cmds.xform(reparented, worldSpace=True, matrix=child_matrix)
        axes = _joint_world_axes(joint)
        result[name] = axes["x"] * om.MVector(0.0, 1.0, 0.0)
    return result


def orient_studio_root_pelvis_hipswing_y_up(
    namespace: str = "",
) -> Dict[str, float]:
    """Give origin, pelvis, and hipswing a shared world-Y-up basis."""
    result = {}
    pelvis_joint = _find_template_joint("pelvis", namespace)
    pelvis_position = (
        tuple(cmds.xform(
            pelvis_joint, query=True, worldSpace=True, translation=True
        ))
        if pelvis_joint and cmds.objExists(pelvis_joint) else None
    )
    identity_basis = [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
    ]
    for name in ("origin", "pelvis", "hipswing"):
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        joint = (cmds.ls(joint, long=True) or [joint])[0]
        origin = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        if name == "hipswing" and pelvis_position is not None:
            origin = pelvis_position
        detached = []
        for child in cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []:
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            world_child = cmds.parent(child, world=True, absolute=True)[0]
            detached.append((world_child, child_matrix))
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)
        if cmds.objExists(joint + ".rotateAxis"):
            cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)
        cmds.xform(
            joint,
            worldSpace=True,
            matrix=identity_basis + [origin[0], origin[1], origin[2], 1.0],
        )
        for child, child_matrix in detached:
            if not cmds.objExists(child):
                continue
            reparented = cmds.parent(child, joint, absolute=True)[0]
            cmds.xform(reparented, worldSpace=True, matrix=child_matrix)
        result[name] = (
            _joint_world_axes(joint)["y"] * om.MVector(0.0, 1.0, 0.0)
        )
    return result


def orient_studio_head_chains(
    namespace: str = "",
    include_oral: bool = True,
) -> Dict[str, float]:
    """Aim the central neck, skull, jaw, and tongue joints down-bone.

    These joints own facial and oral branches, so the generic one-child pass
    deliberately skips several of them.  Explicit primary-child pairs keep
    local X anatomical while preserving every secondary branch in world space.
    """
    spine_tip = _find_template_joint("spine5_Tip", namespace)
    spine_forward = (0.0, 0.0, 1.0)
    if spine_tip and cmds.objExists(spine_tip):
        forward_axis = _joint_world_axes(spine_tip)["y"]
        if forward_axis.length() > 1.0e-8:
            forward_axis.normalize()
            spine_forward = (
                float(forward_axis.x),
                float(forward_axis.y),
                float(forward_axis.z),
            )

    pairs = [
        ("neck1", "neck2"),
        ("neck2", "head1"),
        ("head1", "head1_Tip"),
    ]
    if include_oral:
        pairs.extend((
            ("jaw", "jaw_Tip"),
            ("tongue1", "tongue2"),
            ("tongue2", "tongue3"),
            ("tongue3", "tongue4"),
        ))
    result = {}
    for parent_name, child_name in pairs:
        parent = _find_template_joint(parent_name, namespace)
        child = _find_template_joint(child_name, namespace)
        if not parent or not child:
            continue
        world_up = (
            spine_forward
            if parent_name in {"neck1", "neck2", "head1"}
            else (0.0, 0.0, 1.0)
        )
        _orient_joint_x_to_child(parent, child, world_up=world_up)
        parent_position = om.MVector(
            *cmds.xform(parent, query=True, worldSpace=True, translation=True)
        )
        child_position = om.MVector(
            *cmds.xform(child, query=True, worldSpace=True, translation=True)
        )
        direction = child_position - parent_position
        if direction.length() <= 1.0e-8:
            continue
        result[parent_name] = abs(
            _joint_world_axes(parent)["x"] * direction.normal()
        )
    head = _find_template_joint("head1", namespace)
    tip = _find_template_joint("head1_Tip", namespace)
    if head and tip:
        tip_position = cmds.xform(
            tip, query=True, worldSpace=True, translation=True
        )
        matrix = cmds.xform(
            head, query=True, worldSpace=True, matrix=True
        )
        matrix[12:15] = tip_position
        cmds.setAttr(tip + ".jointOrient", 0.0, 0.0, 0.0)
        if cmds.objExists(tip + ".rotateAxis"):
            cmds.setAttr(tip + ".rotateAxis", 0.0, 0.0, 0.0)
        cmds.xform(tip, worldSpace=True, matrix=matrix)
        cmds.setAttr(tip + ".rotate", 0.0, 0.0, 0.0)
    return result


def orient_studio_neck1_grid_standard(
    namespace: str = "",
) -> Dict[str, Tuple[float, float, float]]:
    """Keep neck1 aimed at neck2 with the same forward-Y axis as the spine."""
    neck1 = _find_template_joint("neck1", namespace)
    neck2 = _find_template_joint("neck2", namespace)
    spine_tip = _find_template_joint("spine5_Tip", namespace)
    if not all((neck1, neck2, spine_tip)):
        return {}
    if not all(cmds.objExists(joint) for joint in (neck1, neck2, spine_tip)):
        return {}
    forward_axis = _joint_world_axes(spine_tip)["y"]
    if forward_axis.length() <= 1.0e-8:
        forward_axis = om.MVector(0.0, 0.0, 1.0)
    forward_axis.normalize()
    _orient_joint_x_to_child(
        neck1,
        neck2,
        world_up=(forward_axis.x, forward_axis.y, forward_axis.z),
    )
    neck_axes = _joint_world_axes(neck1)
    return {
        "neck1_rotate": tuple(float(value) for value in cmds.getAttr(
            neck1 + ".rotate"
        )[0]),
        "neck1_joint_orient": tuple(float(value) for value in cmds.getAttr(
            neck1 + ".jointOrient"
        )[0]),
        "neck1_forward_y": (
            float(neck_axes["y"].x),
            float(neck_axes["y"].y),
            float(neck_axes["y"].z),
        ),
        "spine_forward_y": (
            float(forward_axis.x),
            float(forward_axis.y),
            float(forward_axis.z),
        ),
    }


def orient_studio_center_face_grid_axes(
    namespace: str = "",
) -> Dict[str, Dict[str, float]]:
    """World-align center facial anchors to the scene grid axes exactly."""
    identity_basis = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
    )
    names = (
        "nose_root", "nose_upper", "nose_tip", "nose_base",
        "c_upper_lip", "c_lower_lip",
    )
    result = {}
    for name in names:
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        _set_joint_world_basis_preserving_children(joint, identity_basis)
        axes = _joint_world_axes(joint)
        result[name] = {
            "world_x_dot": float(axes["x"] * om.MVector(1.0, 0.0, 0.0)),
            "world_y_dot": float(axes["y"] * om.MVector(0.0, 1.0, 0.0)),
            "world_z_dot": float(axes["z"] * om.MVector(0.0, 0.0, 1.0)),
        }
    return result


def fit_studio_neck_head_jaw_relative(
    mesh: str,
    namespace: str = "",
    placement_names: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    """Transfer approved neck/head/jaw pivots by mesh-relative proportions."""
    query = _cached_mesh_interior_query(mesh)
    bounds = get_mesh_bounds(mesh)
    root = _find_template_joint("origin", namespace)
    spine_tip = _find_template_joint("spine5_Tip", namespace)
    neck1 = _find_template_joint("neck1", namespace)
    neck2 = _find_template_joint("neck2", namespace)
    head = _find_template_joint("head1", namespace)
    head_tip = _find_template_joint("head1_Tip", namespace)
    jaw = _find_template_joint("jaw", namespace)
    jaw_tip = _find_template_joint("jaw_Tip", namespace)
    if not all((root, spine_tip, neck1, neck2, head, head_tip, jaw, jaw_tip)):
        return {}

    minimum_y = float(bounds["min"].y)
    height = float(bounds["height"])
    center_x = float(cmds.xform(
        spine_tip, query=True, worldSpace=True, translation=True
    )[0])
    allowed_names = set(placement_names or ("neck1", "neck2", "head1", "jaw"))
    reference_points, reference_cases = solve_reference_internal_head_points(mesh)

    def section_target(joint, y_value, depth_fraction, x_value):
        current = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        interval = _choose_interval(
            query.axis_intervals((x_value, y_value, current[2]), "z"),
            current[2],
        )
        if interval is None:
            return (x_value, y_value, current[2])
        return (
            x_value,
            y_value,
            interval[0] + ((interval[1] - interval[0]) * depth_fraction),
        )

    neck1_target = tuple(cmds.xform(
        spine_tip, query=True, worldSpace=True, translation=True
    ))
    if "neck1" not in allowed_names:
        neck1_target = tuple(cmds.xform(
            neck1, query=True, worldSpace=True, translation=True
        ))
    # Start with corpus proportions, then prefer the fitted face itself. Whole
    # character height is a poor skull locator on stylized meshes with large
    # hair, hats, skirts, or unusual body proportions; the eye-to-mouth span is
    # local, anatomical, and already mesh fitted by this point in the pipeline.
    neck2_height_fraction = 0.8541008853526776
    head_height_fraction = 0.897362394215262
    neck2_target = section_target(
        neck2,
        minimum_y + (height * neck2_height_fraction),
        0.23675388116928572,
        center_x,
    )
    head_target = section_target(
        head,
        minimum_y + (height * head_height_fraction),
        0.3060402865195354,
        center_x,
    )
    # Neck2 and head1 are internal anatomical pivots. Use the corpus only when
    # fitted face landmarks are unavailable.
    if "neck2" in reference_points:
        neck2_target = (
            center_x,
            float(reference_points["neck2"][1]),
            float(reference_points["neck2"][2]),
        )
    if "head1" in reference_points:
        head_target = (
            center_x,
            float(reference_points["head1"][1]),
            float(reference_points["head1"][2]),
        )

    eye_joints = [
        _find_template_joint(name, namespace) for name in ("l_eye", "r_eye")
    ]
    mouth_joints = [
        _find_template_joint(name, namespace)
        for name in ("c_upper_lip", "c_lower_lip")
    ]
    if all(eye_joints) and all(mouth_joints):
        eye_y = sum(float(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )[1]) for joint in eye_joints) / float(len(eye_joints))
        mouth_y = sum(float(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )[1]) for joint in mouth_joints) / float(len(mouth_joints))
        face_span = eye_y - mouth_y
        if face_span > max(height * 0.01, 1.0e-5):
            head_target = section_target(
                head,
                mouth_y + (face_span * 0.43),
                0.25,
                center_x,
            )
    # The neck is a two-segment continuation of one anatomical line.  Place
    # neck2 at the exact midpoint so neck1->neck2 and neck2->head1 have the
    # same direction and therefore resolve to the same orientation frame.
    neck2_target = tuple(
        (float(neck1_target[index]) + float(head_target[index])) * 0.5
        for index in range(3)
    )
    jaw_height_fraction = 0.8971603250724067
    jaw_y = minimum_y + (height * jaw_height_fraction)
    if all(eye_joints) and all(mouth_joints):
        eye_y = sum(float(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )[1]) for joint in eye_joints) / float(len(eye_joints))
        mouth_y = sum(float(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )[1]) for joint in mouth_joints) / float(len(mouth_joints))
        face_span = eye_y - mouth_y
        if face_span > max(height * 0.01, 1.0e-5):
            jaw_y = mouth_y + (face_span * 0.56)
    jaw_target = section_target(
        jaw,
        jaw_y,
        0.28,
        center_x,
    )

    for name, joint, target in (
        ("neck1", neck1, neck1_target),
        ("neck2", neck2, neck2_target),
        ("head1", head, head_target),
        ("jaw", jaw, jaw_target),
    ):
        if name in allowed_names:
            _set_joint_world_translation_preserving_children(joint, target)
    # Head placement is authoritative. Recompute neck2 from the actual final
    # endpoints afterward so no earlier proposal or hierarchy compensation can
    # leave it anywhere except halfway between neck1 and head1.
    if "neck2" in allowed_names:
        neck1_position = cmds.xform(
            neck1, query=True, worldSpace=True, translation=True
        )
        head_position = cmds.xform(
            head, query=True, worldSpace=True, translation=True
        )
        neck2_target = tuple(
            (float(neck1_position[index]) + float(head_position[index])) * 0.5
            for index in range(3)
        )
        _set_joint_world_translation_preserving_children(neck2, neck2_target)
    _orient_joint_x_to_child(neck1, neck2, world_up=(0.0, 0.0, 1.0))
    _orient_joint_x_to_child(neck2, head, world_up=(0.0, 0.0, 1.0))
    _orient_joint_x_to_child(head, head_tip, world_up=(0.0, 0.0, 1.0))
    if "jaw" in allowed_names:
        _orient_joint_x_to_child(jaw, jaw_tip, world_up=(0.0, 0.0, 1.0))

    return {
        "neck1": neck1_target,
        "neck2": neck2_target,
        "head1": head_target,
        "jaw": jaw_target,
        "placed": sorted(allowed_names),
        "reference_cases": reference_cases,
        "height_fractions": {
            "neck2": neck2_height_fraction,
            "head1": head_height_fraction,
            "jaw": jaw_height_fraction,
        },
        "depth_fractions": {
            "neck2": 0.23675388116928572,
            "head1": 0.25,
            "jaw": 0.28,
        },
        "face_relative_height_fractions": {"head1": 0.43, "jaw": 0.56},
    }

def orient_studio_teeth_scene_y_up(
    namespace: str = "",
) -> Dict[str, float]:
    """World-align teeth joints with scene Y up and zero jointOrient.

    Teeth are rigid oral anchors rather than down-bone chain joints. Keeping
    their basis scene-aligned makes dental controls predictable even when the
    head and jaw parents carry character-specific roll.
    """
    result = {}
    for name in ("upper_teeth", "lower_teeth"):
        joint = _find_template_joint(name, namespace)
        if not joint or not cmds.objExists(joint):
            continue
        joint = (cmds.ls(joint, long=True) or [joint])[0]
        origin = tuple(cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        detached = []
        for child in cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []:
            world_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            world_child = cmds.parent(child, world=True, absolute=True)[0]
            detached.append((world_child, world_matrix))
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        for axis in "XYZ":
            cmds.setAttr(
                "{0}.jointOrient{1}".format(joint, axis), 0.0
            )
        cmds.xform(
            joint,
            worldSpace=True,
            matrix=[
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                origin[0], origin[1], origin[2], 1.0,
            ],
        )
        for child, world_matrix in detached:
            if not cmds.objExists(child):
                continue
            reparented = cmds.parent(child, joint, absolute=True)[0]
            cmds.xform(reparented, worldSpace=True, matrix=world_matrix)
        result[name] = (
            _joint_world_axes(joint)["y"] * om.MVector(0.0, 1.0, 0.0)
        )
    return result


def orient_studio_brow_joints(
    mesh: str = "",
    namespace: str = "",
) -> Dict[str, Dict[str, float]]:
    """Aim X at the next brow and keep Y tangent to the facial surface."""
    result = {}
    mesh_query = _cached_mesh_interior_query(mesh) if mesh else None
    for side in ("l", "r"):
        names = ["{0}_brow{1}".format(side, index) for index in range(1, 6)]
        names.append(side + "_brow_end")
        joints = [_find_template_joint(name, namespace) for name in names]
        if not all(joints):
            continue
        positions = [
            om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
            for joint in joints
        ]
        previous_y = None
        for index, (name, joint, origin) in enumerate(zip(names, joints, positions)):
            # Every articulated brow bone aims directly at its next landmark;
            # only the terminal marker inherits the final segment direction.
            tangent = (
                positions[index + 1] - origin
                if index < len(positions) - 1
                else origin - positions[index - 1]
            )
            if mesh_query:
                _closest, normal, _face_id = mesh_query.mesh_fn.getClosestPointAndNormal(
                    om.MPoint(origin), om.MSpace.kWorld
                )
                z_axis = om.MVector(normal)
            else:
                z_axis = om.MVector(0.0, 0.0, 1.0)
            z_axis.normalize()
            x_axis = tangent - (z_axis * (tangent * z_axis))
            if x_axis.length() <= 1.0e-8:
                continue
            x_axis.normalize()
            y_axis = z_axis ^ x_axis
            if y_axis.y < 0.0:
                z_axis *= -1.0
                y_axis = z_axis ^ x_axis
            if y_axis.length() <= 1.0e-8:
                continue
            y_axis.normalize()
            z_axis = x_axis ^ y_axis
            z_axis.normalize()

            direct_children = cmds.listRelatives(
                joint, children=True, type="joint", fullPath=True
            ) or []
            detached = []
            for child in direct_children:
                world_matrix = cmds.xform(
                    child, query=True, worldSpace=True, matrix=True
                )
                world_child = cmds.parent(child, world=True, absolute=True)[0]
                detached.append((world_child, world_matrix))

            matrix = [
                x_axis.x, x_axis.y, x_axis.z, 0.0,
                y_axis.x, y_axis.y, y_axis.z, 0.0,
                z_axis.x, z_axis.y, z_axis.z, 0.0,
                origin.x, origin.y, origin.z, 1.0,
            ]
            cmds.xform(joint, worldSpace=True, matrix=matrix)
            # Joint placer stores authored orientation on rotate channels.
            # Never bake the brow frame back into jointOrient.
            _move_joint_orientation_to_rotate(joint)
            for world_child, world_matrix in detached:
                reparented = cmds.parent(world_child, joint, absolute=True)[0]
                cmds.xform(reparented, worldSpace=True, matrix=world_matrix)

            axes = _joint_world_axes(joint)
            adjacent_y_alignment = (
                axes["y"] * previous_y if previous_y is not None else 1.0
            )
            result[name] = {
                "x_next_brow_alignment": axes["x"] * x_axis,
                "y_surface_tangent_alignment": axes["y"] * y_axis,
                "y_world_up_alignment": axes["y"] * om.MVector(0.0, 1.0, 0.0),
                "adjacent_y_alignment": adjacent_y_alignment,
            }
            previous_y = axes["y"]
    return result


def zero_studio_eyelid_tip_rotates(
    root: str,
) -> Dict[str, Tuple[float, float, float]]:
    """Zero terminal eyelid rotate channels after all orientation passes."""
    tip_pattern = re.compile(
        r"^(?:l|r)_(?:inner|outer|upper|lower)_eyelidTip\d*$",
        re.IGNORECASE,
    )
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    result = {}
    for joint in joints:
        name = _short_name(joint).split(":")[-1]
        if not tip_pattern.match(name):
            continue
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        for axis in "XYZ":
            plug = "{0}.rotate{1}".format(joint, axis)
            try:
                cmds.setAttr(plug, lock=False)
            except (RuntimeError, ValueError):
                pass
        cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        result[name] = tuple(
            float(cmds.getAttr("{0}.rotate{1}".format(joint, axis)))
            for axis in "XYZ"
        )
    return result


def orient_studio_surface_face_joints(
    mesh: str,
    root: str,
) -> Dict[str, Dict[str, float]]:
    """Keep cheek and under-eye X axes tangent to the facial surface."""
    if not mesh or not cmds.objExists(mesh):
        return {}
    query = _cached_mesh_interior_query(mesh)
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    by_name = {
        _short_name(joint).split(":")[-1]: joint for joint in joints
    }
    result = {}

    def apply(joint: str, _tangent_reference: om.MVector) -> None:
        name = _short_name(joint).split(":")[-1]
        origin = om.MVector(*cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        ))
        _closest, normal, _face_id = query.mesh_fn.getClosestPointAndNormal(
            om.MPoint(origin), om.MSpace.kWorld
        )
        z_axis = om.MVector(normal).normal()
        tangent_up = om.MVector(0.0, 1.0, 0.0)
        tangent_up -= z_axis * (tangent_up * z_axis)
        if tangent_up.length() <= 1.0e-8:
            current_y = _joint_world_axes(joint)["y"]
            tangent_up = current_y - z_axis * (current_y * z_axis)
        if tangent_up.length() <= 1.0e-8:
            return
        y_axis = tangent_up.normal()
        x_axis = (y_axis ^ z_axis).normal()
        z_axis = (x_axis ^ y_axis).normal()
        detached = []
        for child in cmds.listRelatives(
            joint, children=True, type="joint", fullPath=True
        ) or []:
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            detached.append((
                cmds.parent(child, world=True, absolute=True)[0], child_matrix
            ))
        cmds.xform(joint, worldSpace=True, matrix=[
            x_axis.x, x_axis.y, x_axis.z, 0.0,
            y_axis.x, y_axis.y, y_axis.z, 0.0,
            z_axis.x, z_axis.y, z_axis.z, 0.0,
            origin.x, origin.y, origin.z, 1.0,
        ])
        _move_joint_orientation_to_rotate(joint)
        for child, child_matrix in detached:
            if cmds.objExists(child):
                child = cmds.parent(child, joint, absolute=True)[0]
                cmds.xform(child, worldSpace=True, matrix=child_matrix)
        axes = _joint_world_axes(joint)
        result[name] = {
            "x_surface_tangent_alignment": abs(float(axes["x"] * x_axis)),
            "y_outward_view_up_alignment": float(axes["y"] * y_axis),
            "z_surface_normal_alignment": abs(float(axes["z"] * z_axis)),
        }

    for side in ("l", "r"):
        under_rows = []
        for name, joint in by_name.items():
            match = re.match(
                r"^{0}_under_?eye_?(\d+)$".format(side),
                name,
                re.IGNORECASE,
            )
            if match:
                under_rows.append((int(match.group(1)), joint))
        under_rows.sort(key=lambda row: row[0])
        under_joints = [joint for _index, joint in under_rows]
        for index, joint in enumerate(under_joints):
            if not joint:
                continue
            origin = om.MVector(*cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            neighbor = (
                under_joints[index + 1]
                if index < len(under_joints) - 1 and under_joints[index + 1]
                else under_joints[index - 1] if index > 0 else None
            )
            tangent = (
                om.MVector(*cmds.xform(
                    neighbor, query=True, worldSpace=True, translation=True
                )) - origin
                if neighbor else _joint_world_axes(joint)["x"]
            )
            apply(joint, tangent)
        for name, joint in by_name.items():
            if re.match(
                r"^{0}_.+cheek.*$".format(side), name, re.IGNORECASE
            ):
                apply(joint, _joint_world_axes(joint)["x"])
    return result


def orient_studio_face_local_y_up(root: str) -> Dict[str, Dict[str, float]]:
    """Orient side facial joints to the studio's mirrored X/Y/Z convention.

    The lateral axis is derived from the eye landmarks so this remains aligned
    to the character when the mesh is rotated in the scene. Left-side joints
    use outward lateral X, world-up Y, and forward Z; right-side joints use
    the mirrored X and Z directions with Y still up. Centerline face joints
    retain their X aim and roll Y toward projected world-up. Joint positions
    and child world matrices are preserved.
    """
    if not root or not cmds.objExists(root):
        return {}
    face_pattern = re.compile(
        r"(?:eye|brow|lid|eyelid|cheek|nose|lip|mouth|jaw|chin|ear|temple|face)",
        re.IGNORECASE,
    )
    joints = [root] + (
        cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True)
        or []
    )
    world_up = om.MVector(0.0, 1.0, 0.0)
    by_name = {
        _short_name(joint).split(":")[-1].lower(): joint
        for joint in joints
    }
    left_eye = by_name.get("l_eye")
    right_eye = by_name.get("r_eye")
    lateral_axis = None
    if left_eye and right_eye:
        left_pos = om.MVector(*cmds.xform(
            left_eye, query=True, worldSpace=True, translation=True
        ))
        right_pos = om.MVector(*cmds.xform(
            right_eye, query=True, worldSpace=True, translation=True
        ))
        lateral_axis = left_pos - right_pos
        lateral_axis -= world_up * (lateral_axis * world_up)
        if lateral_axis.length() > 1.0e-6:
            lateral_axis.normalize()
        else:
            lateral_axis = None
    if lateral_axis is None:
        # The normal production scenes are world-aligned; keep a deterministic
        # fallback for partial rigs that do not contain both eye anchors.
        lateral_axis = om.MVector(1.0, 0.0, 0.0)
    result = {}
    for joint in joints:
        name = _short_name(joint).split(":")[-1]
        if not face_pattern.search(name):
            continue
        if re.match(r"^(?:l|r)_eye$", name, re.IGNORECASE):
            # Eye socket orientation is the parent frame for the authored lid
            # arcs; preserve it so fitting other facial joints cannot rewrite
            # eyelid local orientations through their parent hierarchy.
            result[name] = {"skipped": 1.0, "reason_template_eye_socket_frame": 1.0}
            continue
        if re.search(r"(?:eyelid|lid)", name, re.IGNORECASE):
            # The eyelid chains use the template's local frames to follow the
            # eyelid arcs; do not force them into the mirrored facial side frame.
            result[name] = {"skipped": 1.0, "reason_template_eyelid_frame": 1.0}
            continue
        axes = _joint_world_axes(joint)
        side_match = re.match(r"^([lr])_", name, re.IGNORECASE)
        side = side_match.group(1).lower() if side_match else None
        if side in ("l", "r"):
            x_axis = om.MVector(lateral_axis)
            if side == "r":
                x_axis *= -1.0
        else:
            x_axis = om.MVector(axes["x"]).normal()
        y_axis = world_up - x_axis * (world_up * x_axis)
        if y_axis.length() <= 1.0e-6:
            # For a bone nearly parallel to world-up, keep its existing roll;
            # there is no well-defined projected-up direction in that case.
            result[name] = {"skipped": 1.0, "reason_parallel_to_world_up": 1.0}
            continue
        y_axis.normalize()
        z_axis = (x_axis ^ y_axis).normal()
        # Re-orthogonalize to remove numerical drift and retain a right-handed
        # frame. This changes roll only: local X remains the original vector.
        y_axis = (z_axis ^ x_axis).normal()
        origin = cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )
        basis = [
            x_axis.x, x_axis.y, x_axis.z, 0.0,
            y_axis.x, y_axis.y, y_axis.z, 0.0,
            z_axis.x, z_axis.y, z_axis.z, 0.0,
        ]
        child_matrices = [
            (child, cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            ))
            for child in (
                cmds.listRelatives(
                    joint, children=True, type="joint", fullPath=True
                ) or []
            )
        ]
        detached = [
            (cmds.parent(child, world=True, absolute=True)[0], matrix)
            for child, matrix in child_matrices
        ]
        cmds.xform(
            joint,
            worldSpace=True,
            matrix=basis + [origin[0], origin[1], origin[2], 1.0],
        )
        # Studio validation and animator-facing transforms require orientation
        # on rotate, not jointOrient. Match the established brow/surface pass.
        _move_joint_orientation_to_rotate(joint)
        for child, child_matrix in detached:
            if cmds.objExists(child):
                child = cmds.parent(child, joint, absolute=True)[0]
                cmds.xform(child, worldSpace=True, matrix=child_matrix)
        axes_after = _joint_world_axes(joint)
        result[name] = {
            "local_x_target_alignment": float(axes_after["x"] * x_axis),
            "local_y_projected_up_alignment": float(axes_after["y"] * y_axis),
            "local_y_world_up_component": float(axes_after["y"] * world_up),
            "local_z_target_alignment": float(axes_after["z"] * z_axis),
            "world_position_preserved": float((
                om.MVector(*cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                )) - om.MVector(*origin)
            ).length()),
        }
    return result


def orient_studio_leg_chains(namespace: str = "") -> Dict[str, Tuple[float, float, float]]:
    """Author studio-mirrored signed-X frames for both leg chains."""
    offsets = {}
    lateral_reference = (1.0, 0.0, 0.0)
    for side in ("l", "r"):
        aim_sign = 1.0 if side == "l" else -1.0
        chain = [
            _find_template_joint("{0}_thigh".format(side), namespace),
            _find_template_joint("{0}_knee".format(side), namespace),
            _find_template_joint("{0}_ankle".format(side), namespace),
            _find_template_joint("{0}_toe".format(side), namespace),
            _find_template_joint("{0}_toeTip".format(side), namespace),
        ]
        world_positions = {
            joint: tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
            for joint in chain if joint and cmds.objExists(joint)
        }
        thigh_joint, knee_joint, ankle_joint = chain[:3]
        bend_axis = "y"
        if knee_joint and cmds.attributeQuery(
            TEMPLATE_KNEE_BEND_AXIS_ATTR, node=knee_joint, exists=True
        ):
            bend_axis = str(cmds.getAttr(
                "{0}.{1}".format(knee_joint, TEMPLATE_KNEE_BEND_AXIS_ATTR)
            ) or "y").lower()
        hinge_direction = _studio_knee_hinge_direction(side, namespace)
        previous_y = None
        previous_z = None
        for parent, child in (
            (thigh_joint, knee_joint),
            (knee_joint, ankle_joint),
        ):
            if not parent or not child:
                continue
            segment = om.MVector(*world_positions[child]) - om.MVector(
                *world_positions[parent]
            )
            segment.normalize()
            if bend_axis == "z":
                _orient_joint_with_world_z_hinge(
                    parent,
                    (
                        segment.x * aim_sign,
                        segment.y * aim_sign,
                        segment.z * aim_sign,
                    ),
                    (
                        hinge_direction.x,
                        hinge_direction.y,
                        hinge_direction.z,
                    ),
                )
                axes = _joint_world_axes(parent)
                if previous_y is not None and axes["y"] * previous_y < 0.0:
                    raise RuntimeError(
                        "Leg Y axis flipped between joints on the {} side.".format(side)
                    )
                if previous_z is not None and axes["z"] * previous_z < 0.0:
                    raise RuntimeError(
                        "Leg Z axis flipped between joints on the {} side.".format(side)
                    )
                previous_y = axes["y"]
                previous_z = axes["z"]
                continue
            elif bend_axis == "y":
                roll_reference = hinge_direction
            else:
                # A down-bone X axis cannot also be the hinge normal. Keep the
                # imported roll for malformed/custom templates rather than
                # introducing an arbitrary ninety-degree twist.
                roll_reference = _joint_world_axes(parent)["y"]
            _orient_joint_x_to_child(
                parent,
                child,
                world_up=(
                    roll_reference.x,
                    roll_reference.y,
                    roll_reference.z,
                ),
                aim_sign=aim_sign,
            )
            axes = _joint_world_axes(parent)
            if previous_y is not None and axes["y"] * previous_y < 0.0:
                raise RuntimeError(
                    "Leg Y axis flipped between joints on the {} side.".format(side)
                )
            if previous_z is not None and axes["z"] * previous_z < 0.0:
                raise RuntimeError(
                    "Leg Z axis flipped between joints on the {} side.".format(side)
                )
            previous_y = axes["y"]
            previous_z = axes["z"]
        for joint in chain[:3]:
            if joint in world_positions and cmds.objExists(joint):
                _set_joint_world_translation(joint, world_positions[joint])

        # Parent-to-child conversion preserves both fitted world bases and
        # keeps all orientation on animator-visible rotate channels.
        for joint in (thigh_joint, knee_joint):
            if joint and cmds.objExists(joint):
                _move_joint_orientation_to_rotate(joint)
        if knee_joint and bend_axis in "yz":
            for axis in "xyz":
                if axis == bend_axis:
                    continue
                plug = "{0}.rotate{1}".format(knee_joint, axis.upper())
                if abs(float(cmds.getAttr(plug))) <= 1.0e-5:
                    cmds.setAttr(plug, 0.0)

        # Build the ankle plane from the approved ankle -> toe -> toeTip chain.
        # This preserves the authored foot roll while local X aims at the toe
        # and toeTip remains a pure local-X child of the toe.
        ankle_joint, toe_joint, tip_joint = chain[2], chain[3], chain[4]
        if ankle_joint and toe_joint and tip_joint:
            ankle_position = om.MVector(*world_positions[ankle_joint])
            toe_position = om.MVector(*world_positions[toe_joint])
            tip_position = om.MVector(*world_positions[tip_joint])
            foot_vector = toe_position - ankle_position
            toe_vector = tip_position - toe_position
            foot_length = foot_vector.length()
            toe_length = toe_vector.length()
            foot_x = (foot_vector * aim_sign).normal()
            toe_x = (toe_vector * aim_sign).normal()
            knee_position = om.MVector(*world_positions[knee_joint])
            lower_leg_vector = ankle_position - knee_position
            leg_plane_normal = foot_vector ^ toe_vector
            if leg_plane_normal.length() <= 1.0e-8:
                leg_plane_normal = (
                    previous_z
                    if previous_z is not None
                    else om.MVector(*lateral_reference)
                )
            leg_plane_normal.normalize()
            if previous_z is not None and leg_plane_normal * previous_z < 0.0:
                leg_plane_normal *= -1.0
            _orient_joint_with_world_z_hinge(
                ankle_joint,
                (
                    foot_vector.x * aim_sign,
                    foot_vector.y * aim_sign,
                    foot_vector.z * aim_sign,
                ),
                (
                    leg_plane_normal.x,
                    leg_plane_normal.y,
                    leg_plane_normal.z,
                ),
            )
            ankle_axes = _joint_world_axes(ankle_joint)
            if previous_z is not None and ankle_axes["z"] * previous_z < 0.0:
                raise RuntimeError(
                    "Leg Z axis flipped at the ankle on the {} side.".format(side)
                )
            _set_joint_world_translation(ankle_joint, world_positions[ankle_joint])
            bend_z = _joint_world_axes(ankle_joint)["z"]
            signed_angle = math.degrees(math.atan2(
                bend_z * (foot_x ^ toe_x),
                max(-1.0, min(1.0, foot_x * toe_x)),
            ))
            cmds.joint(toe_joint, edit=True, degreeOfFreedom="xyz")
            cmds.setAttr(
                toe_joint + ".translate", foot_length * aim_sign, 0.0, 0.0
            )
            cmds.setAttr(toe_joint + ".jointOrient", 0.0, 0.0, 0.0)
            cmds.setAttr(toe_joint + ".rotate", 0.0, 0.0, signed_angle)
            cmds.setAttr(
                tip_joint + ".translate", toe_length * aim_sign, 0.0, 0.0
            )
            cmds.setAttr(tip_joint + ".jointOrient", 0.0, 0.0, 0.0)
            cmds.setAttr(tip_joint + ".rotate", 0.0, 0.0, 0.0)
        for joint in chain[1:]:
            if not joint or not cmds.objExists(joint):
                continue
            values = tuple(
                float(cmds.getAttr("{0}.translate{1}".format(joint, axis)))
                for axis in "XYZ"
            )
            tolerance = max(abs(values[0]), 1.0) * 1.0e-6
            if abs(values[1]) <= tolerance:
                cmds.setAttr(joint + ".translateY", 0.0)
            if abs(values[2]) <= tolerance:
                cmds.setAttr(joint + ".translateZ", 0.0)
            offsets[_short_name(joint)] = (
                float(cmds.getAttr(joint + ".translateX")),
                float(cmds.getAttr(joint + ".translateY")),
                float(cmds.getAttr(joint + ".translateZ")),
            )
        if toe_joint and cmds.objExists(toe_joint):
            cmds.joint(toe_joint, edit=True, degreeOfFreedom="xyz")
            for axis in "XY":
                cmds.setAttr("{0}.preferredAngle{1}".format(toe_joint, axis), 0.0)
        if tip_joint and cmds.objExists(tip_joint):
            for axis in "XYZ":
                cmds.setAttr("{0}.rotate{1}".format(tip_joint, axis), 0.0)

    return offsets

def orient_studio_twist_joints_like_parents(
    root: str,
    namespace: str = "",
) -> Dict[str, str]:
    """Match every studio twist joint's world basis exactly to its parent bone."""
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    result = {}
    for joint in sorted(joints, key=lambda node: node.count("|")):
        short_name = _short_name(joint).split(":")[-1]
        lowered = short_name.lower()
        if "twist" not in lowered or "corrective" in lowered or "twistcor" in lowered:
            continue
        parent = (cmds.listRelatives(
            joint, parent=True, type="joint", fullPath=True
        ) or [None])[0]
        if not parent:
            continue
        position = cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )
        matrix = cmds.xform(
            parent, query=True, worldSpace=True, matrix=True
        )
        matrix[12:15] = position
        child_matrices = {
            child: cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            for child in (
                cmds.listRelatives(
                    joint, children=True, type="joint", fullPath=True
                ) or []
            )
        }
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        cmds.setAttr(joint + ".jointOrient", 0.0, 0.0, 0.0)
        if cmds.objExists(joint + ".rotateAxis"):
            cmds.setAttr(joint + ".rotateAxis", 0.0, 0.0, 0.0)
        cmds.xform(joint, worldSpace=True, matrix=matrix)
        cmds.setAttr(joint + ".rotate", 0.0, 0.0, 0.0)
        for child, child_matrix in child_matrices.items():
            if cmds.objExists(child):
                cmds.xform(child, worldSpace=True, matrix=child_matrix)
        result[short_name] = _short_name(parent).split(":")[-1]
    return result


def enforce_studio_twist_translate_x(
    root: str,
) -> Dict[str, Tuple[float, float, float]]:
    """Put every deformation twist joint solely on its parent's local X axis.

    Twist pivots are fitted along their parent segment and inherit that
    segment's basis. Final elbow/leg orientation cleanup can nevertheless
    leave stale local Y/Z offsets. Zero those offsets while preserving any
    children in world space so this channel cleanup cannot disturb auxiliary
    branches below a twist joint.
    """
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    result = {}
    for joint in sorted(joints, key=lambda node: node.count("|")):
        short_name = _short_name(joint).split(":")[-1]
        lowered = short_name.lower()
        if "twist" not in lowered or "corrective" in lowered or "twistcor" in lowered:
            continue

        detached = []
        for child in cmds.listRelatives(
            joint, children=True, fullPath=True
        ) or []:
            if cmds.nodeType(child) not in ("joint", "transform"):
                continue
            child_matrix = cmds.xform(
                child, query=True, worldSpace=True, matrix=True
            )
            world_child = cmds.parent(child, world=True, absolute=True)[0]
            detached.append((world_child, child_matrix))

        translate_x = float(cmds.getAttr(joint + ".translateX"))
        for axis in "XYZ":
            try:
                cmds.setAttr(
                    "{0}.translate{1}".format(joint, axis),
                    lock=False,
                )
            except (RuntimeError, ValueError):
                pass
        cmds.setAttr(joint + ".translate", translate_x, 0.0, 0.0)

        for child, child_matrix in detached:
            if not cmds.objExists(child):
                continue
            reparented = cmds.parent(child, joint, absolute=True)[0]
            cmds.xform(
                reparented,
                worldSpace=True,
                matrix=child_matrix,
            )
        result[short_name] = (translate_x, 0.0, 0.0)
    return result


def unlock_studio_joint_channels(
    root: str,
    namespace: str = "",
) -> int:
    """Leave every studio joint transform channel unlocked and keyable."""
    joints = [root] + (
        cmds.listRelatives(
            root, allDescendents=True, type="joint", fullPath=True
        ) or []
    )
    for side in ("l", "r"):
        heel = _find_template_joint("{0}_heel_RFL".format(side), namespace)
        if not heel:
            continue
        joints.append(heel)
        joints.extend(
            cmds.listRelatives(
                heel, allDescendents=True, type="joint", fullPath=True
            ) or []
        )
    joints = list(dict.fromkeys(
        (cmds.ls(joint, long=True) or [joint])[0]
        for joint in joints if joint and cmds.objExists(joint)
    ))
    for joint in joints:
        cmds.joint(joint, edit=True, degreeOfFreedom="xyz")
        for attribute in (
            "translateX", "translateY", "translateZ",
            "rotateX", "rotateY", "rotateZ",
            "scaleX", "scaleY", "scaleZ",
            "visibility",
        ):
            plug = "{0}.{1}".format(joint, attribute)
            if not cmds.objExists(plug):
                continue
            cmds.setAttr(plug, lock=False)
            cmds.setAttr(plug, keyable=True)
    return len(joints)


def _capture_mapped_twist_fractions(joint_map: dict) -> Dict[str, Tuple[str, str, float]]:
    """Remember authored twist spacing before the core hierarchy is resized."""
    result = {}
    segment_slots = (
        ("LeftArm", "LeftForeArm"), ("LeftForeArm", "LeftHand"),
        ("RightArm", "RightForeArm"), ("RightForeArm", "RightHand"),
        ("LeftUpLeg", "LeftLeg"), ("LeftLeg", "LeftFoot"),
        ("RightUpLeg", "RightLeg"), ("RightLeg", "RightFoot"),
    )
    for start_slot, end_slot in segment_slots:
        start = _mapped_joint(joint_map, start_slot)
        end = _mapped_joint(joint_map, end_slot)
        if not start or not end:
            continue
        start_position = om.MVector(*cmds.xform(start, query=True, worldSpace=True, translation=True))
        end_position = om.MVector(*cmds.xform(end, query=True, worldSpace=True, translation=True))
        segment = end_position - start_position
        denominator = segment * segment
        if denominator <= 1.0e-8:
            continue
        candidates = cmds.listRelatives(start, ad=True, type="joint", fullPath=True) or []
        for joint in candidates:
            short_name = _short_name(joint).lower()
            if (
                "twist" not in short_name
                or "twistcor" in short_name
                or short_name.endswith("_drv")
            ):
                continue
            # Only branches owned by this segment; stop before the mapped end.
            if joint == end or joint.startswith(end + "|"):
                continue
            position = om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
            fraction = ((position - start_position) * segment) / denominator
            if -0.05 <= fraction <= 1.05:
                result[joint] = (start, end, max(0.0, min(float(fraction), 1.0)))
    return result


def mapped_detail_editability_issues(root: str) -> List[str]:
    """Return driven/locked body detail joints that make a fit unsafe.

    MetaHuman body helpers must be editable in neutral-pose editing mode before
    their core skeleton is repositioned.  Detect this before any scale or joint
    move so a live RigLogic/RBF graph cannot leave a partially fitted skeleton.
    """
    all_joints = [root] + (
        cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or []
    )
    corrective_roots = [
        joint for joint in all_joints
        if "correctiveroot" in _short_name(joint).lower()
        and not _short_name(joint).lower().endswith("_drv")
    ]
    corrective_descendants = set()
    for joint in corrective_roots:
        corrective_descendants.update(
            cmds.listRelatives(joint, ad=True, type="joint", fullPath=True) or []
        )
    surface_pattern = re.compile(
        r"(?:_out_|_in_|_fwd_|_bck_|_out$|_in$|_fwd$|_bck$|kneeBack|_knee_|"
        r"_knee$|_scap_|_scap$|_pec_|_pec$|latissimus|side_out|side_in)",
        re.IGNORECASE,
    )
    candidates = set(corrective_roots) | corrective_descendants
    for joint in all_joints:
        short_name = _short_name(joint).split(":")[-1]
        lowered = short_name.lower()
        if short_name.startswith("FACIAL_") or lowered.endswith("_drv"):
            continue
        if "twist" in lowered or "corrective" in lowered or surface_pattern.search(short_name):
            candidates.add(joint)
    return sorted(
        _short_name(joint).split(":")[-1]
        for joint in candidates
        if not _joint_translation_is_editable(joint)
    )


def place_mapped_detail_joints(
    mesh: str,
    root: str,
    joint_map: dict,
    twist_fractions: Optional[Dict[str, Tuple[str, str, float]]] = None,
) -> Dict[str, object]:
    """Place and verify MetaHuman-style twist and corrective joints.

    Facial DNA joints and driver duplicates are deliberately untouched. Their
    neutral transforms belong to RigLogic/DNA and require the face mesh/DNA
    update workflow rather than a body-volume projection.
    """
    all_joints = [root] + (cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or [])
    short_names = {_short_name(joint).split(":")[-1]: joint for joint in all_joints}
    metahuman_style = any(
        "corrective" in name.lower() or "twistcor" in name.lower()
        for name in short_names
    ) or any(
        name.startswith("FACIAL_C_FacialRoot") for name in short_names
    )
    report = {
        "metahuman_style": bool(metahuman_style),
        "detected_twist_joint_count": len(twist_fractions or {}),
        "verified_twist_joint_count": 0,
        "twist_joints_placed": 0,
        "corrective_roots_placed": 0,
        "twist_correctives_placed": 0,
        "surface_correctives_placed": 0,
        "detected_corrective_joint_count": 0,
        "verified_corrective_joint_count": 0,
        "max_surface_projection_error": 0.0,
        "max_surface_distance": 0.0,
        "skipped_driven_or_locked": [],
        "skipped_twist_joints": [],
        "skipped_unverified": [],
        "unclassified_corrective_joints": [],
        "corrective_validation_errors": [],
        "twist_validation_errors": [],
        "all_correctives_verified": True,
        "all_detail_joints_verified": True,
        "protected_facial_joints": 0,
    }
    if not metahuman_style:
        return report

    protected = [
        joint for joint in (cmds.ls(type="joint", long=True) or [])
        if _short_name(joint).split(":")[-1].startswith("FACIAL_")
    ]
    report["protected_facial_joints"] = len(protected)

    for joint, (start, end, fraction) in (twist_fractions or {}).items():
        if not cmds.objExists(joint):
            continue
        if not _joint_translation_is_editable(joint):
            report["skipped_twist_joints"].append(
                _short_name(joint).split(":")[-1]
            )
            continue
        start_position = cmds.xform(start, query=True, worldSpace=True, translation=True)
        end_position = cmds.xform(end, query=True, worldSpace=True, translation=True)
        target = [
            start_position[index] + ((end_position[index] - start_position[index]) * fraction)
            for index in range(3)
        ]
        _set_joint_world_translation(joint, target)
        report["twist_joints_placed"] += 1

    corrective_root_pattern = re.compile(r"correctiveRoot", re.IGNORECASE)
    twist_corrective_pattern = re.compile(r"twistCor", re.IGNORECASE)
    surface_pattern = re.compile(
        r"(?:_out_|_in_|_fwd_|_bck_|_out$|_in$|_fwd$|_bck$|kneeBack|_knee_|"
        r"_knee$|_scap_|_scap$|_pec_|_pec$|latissimus|side_out|side_in)",
        re.IGNORECASE,
    )
    query = _cached_mesh_interior_query(mesh)
    corrective_roots = []
    twist_correctives = []
    surface_correctives = []
    unclassified = []
    root_descendants = set()

    for joint in all_joints:
        short_name = _short_name(joint).split(":")[-1]
        if short_name.startswith("FACIAL_") or short_name.endswith("_drv"):
            continue
        if corrective_root_pattern.search(short_name):
            corrective_roots.append(joint)
            root_descendants.update(
                cmds.listRelatives(joint, ad=True, type="joint", fullPath=True) or []
            )
            continue
        if twist_corrective_pattern.search(short_name):
            twist_correctives.append(joint)
            continue
        if surface_pattern.search(short_name):
            surface_correctives.append(joint)

    # Any non-driver joint below a corrective root is corrective data even if
    # a studio uses custom names.  Classify leaf/offset joints as surface
    # correctives and make genuinely ambiguous nested structures reviewable.
    classified = set(corrective_roots + twist_correctives + surface_correctives)
    for joint in sorted(root_descendants, key=lambda value: value.count("|")):
        short_name = _short_name(joint).split(":")[-1]
        if short_name.startswith("FACIAL_") or short_name.endswith("_drv") or joint in classified:
            continue
        children = cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []
        if not children:
            surface_correctives.append(joint)
            classified.add(joint)
        else:
            unclassified.append(joint)

    # A joint explicitly named as corrective must never disappear silently
    # just because it does not match one of the known MetaHuman categories.
    for joint in all_joints:
        short_name = _short_name(joint).split(":")[-1]
        lowered = short_name.lower()
        if (
            "corrective" in lowered
            and not short_name.startswith("FACIAL_")
            and not short_name.endswith("_drv")
            and joint not in classified
            and joint not in unclassified
        ):
            unclassified.append(joint)

    report["detected_corrective_joint_count"] = len(
        corrective_roots + twist_correctives + surface_correctives + unclassified
    )
    report["unclassified_corrective_joints"] = [
        _short_name(joint) for joint in unclassified
    ]

    def _place_or_record(joint, target, counter):
        short_name = _short_name(joint).split(":")[-1]
        if _joint_translation_is_editable(joint):
            _set_joint_world_translation(joint, target)
            report[counter] += 1
            return True
        report["skipped_driven_or_locked"].append(short_name)
        return False

    for joint in corrective_roots:
        parent = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
        if parent:
            target = cmds.xform(parent[0], query=True, worldSpace=True, translation=True)
            _place_or_record(joint, target, "corrective_roots_placed")

    for joint in twist_correctives:
        parent = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
        if parent:
            target = cmds.xform(parent[0], query=True, worldSpace=True, translation=True)
            _place_or_record(joint, target, "twist_correctives_placed")

    for joint in surface_correctives:
        position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
        closest, _normal = query.mesh_fn.getClosestPoint(
            om.MPoint(*position), om.MSpace.kWorld
        )
        was_placed = _place_or_record(
            joint,
            (closest.x, closest.y, closest.z),
            "surface_correctives_placed",
        )
        actual = cmds.xform(joint, query=True, worldSpace=True, translation=True)
        projection_error = om.MVector(
            actual[0] - closest.x,
            actual[1] - closest.y,
            actual[2] - closest.z,
        ).length()
        if was_placed:
            report["max_surface_projection_error"] = max(
                report["max_surface_projection_error"],
                float(projection_error),
            )
    # Audit final evaluated transforms.  Driven correctives are acceptable only
    # when their driver has already produced the required neutral relationship.
    positional_tolerance = max(query.diagonal * 1.0e-5, 1.0e-5)
    # Editable correctives are projected exactly. Existing RigLogic/RBF-driven
    # neutral positions are accepted within a small character-scale envelope:
    # stock MetaHuman body correctives intentionally sit close to, rather than
    # numerically on, the polygon shell used for this check.
    surface_tolerance = max(query.diagonal * 0.015, 1.0e-4)
    verified = set()
    validation_errors = []

    for joint in corrective_roots + twist_correctives:
        parent = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
        short_name = _short_name(joint).split(":")[-1]
        if not parent:
            validation_errors.append("{0}: missing joint parent".format(short_name))
            continue
        position = om.MVector(*cmds.xform(joint, query=True, worldSpace=True, translation=True))
        target = om.MVector(*cmds.xform(parent[0], query=True, worldSpace=True, translation=True))
        error = (position - target).length()
        if error <= positional_tolerance:
            verified.add(joint)
        else:
            validation_errors.append(
                "{0}: {1:.6f} from parent".format(short_name, error)
            )

    for joint in surface_correctives:
        short_name = _short_name(joint).split(":")[-1]
        position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
        closest, _normal = query.mesh_fn.getClosestPoint(
            om.MPoint(*position), om.MSpace.kWorld
        )
        error = om.MVector(
            position[0] - closest.x,
            position[1] - closest.y,
            position[2] - closest.z,
        ).length()
        report["max_surface_distance"] = max(
            report["max_surface_distance"], float(error)
        )
        if error <= surface_tolerance:
            verified.add(joint)
        else:
            validation_errors.append(
                "{0}: {1:.6f} from body surface".format(short_name, error)
            )

    report["verified_corrective_joint_count"] = len(verified)
    report["corrective_validation_errors"] = validation_errors
    report["skipped_unverified"] = sorted(
        short_name
        for short_name in report["skipped_driven_or_locked"]
        if short_name not in {
            _short_name(joint).split(":")[-1] for joint in verified
        }
    )
    report["all_correctives_verified"] = bool(
        report["detected_corrective_joint_count"]
        and not unclassified
        and not validation_errors
        and report["verified_corrective_joint_count"]
        == report["detected_corrective_joint_count"]
    )
    twist_validation_errors = []
    verified_twists = 0
    for joint, (start, end, fraction) in (twist_fractions or {}).items():
        if not cmds.objExists(joint) or not cmds.objExists(start) or not cmds.objExists(end):
            twist_validation_errors.append(
                "{0}: missing twist or segment joint".format(_short_name(joint))
            )
            continue
        start_position = om.MVector(
            *cmds.xform(start, query=True, worldSpace=True, translation=True)
        )
        end_position = om.MVector(
            *cmds.xform(end, query=True, worldSpace=True, translation=True)
        )
        expected = start_position + ((end_position - start_position) * fraction)
        actual = om.MVector(
            *cmds.xform(joint, query=True, worldSpace=True, translation=True)
        )
        error = (actual - expected).length()
        if error <= positional_tolerance:
            verified_twists += 1
        else:
            twist_validation_errors.append(
                "{0}: {1:.6f} from authored segment fraction".format(
                    _short_name(joint).split(":")[-1], error
                )
            )
    report["verified_twist_joint_count"] = verified_twists
    report["twist_validation_errors"] = twist_validation_errors
    report["all_detail_joints_verified"] = bool(
        report["all_correctives_verified"]
        and not twist_validation_errors
        and verified_twists == report["detected_twist_joint_count"]
    )
    return report


def fit_mapped_skeleton(
    mesh: str,
    points: Dict[str, Vector3],
    joint_map: dict,
) -> Tuple[str, int, int, Dict[str, object]]:
    """Fit solved anatomical roles onto an existing user-defined hierarchy."""
    missing = mapped_hierarchy_missing_slots(joint_map)
    if missing:
        cmds.error(
            "Mapped hierarchy placement requires these HIK slots: {0}".format(
                ", ".join(missing)
            )
        )
    canonical_joints = mapped_anatomical_joints(joint_map)
    unique_joints = list(dict.fromkeys(canonical_joints.values()))
    root = _mapped_joint(joint_map, "Reference") or _common_mapped_root(unique_joints)
    if not root:
        cmds.error("Could not resolve a joint root for the active rig mapping.")
    root = (cmds.ls(root, long=True) or [root])[0]
    all_joints = [root] + (cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or [])
    source_positions = {
        name: tuple(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        for name, joint in canonical_joints.items()
        if name in points
    }
    # Legacy studio rigs predate the mesh-signature attribute. If their
    # mapped anchors already span and sit within the selected body mesh, treat
    # those scene-authored positions as the approved mesh-dependent baseline
    # instead of replacing them with a coarse generic solve. Once this fit is
    # accepted, _connect_placement_mesh records a signature so later runs can
    # distinguish the same mesh from a different target.
    has_mesh_signature = cmds.attributeQuery(
        PLACEMENT_MESH_SIGNATURE_ATTR, node=root, exists=True
    )
    preserve_existing_positions = _approved_placement_matches_mesh(root, mesh)
    if (
        not preserve_existing_positions
        and not has_mesh_signature
    ):
        preserve_existing_positions = _legacy_studio_pose_matches_mesh(
            root,
            mesh,
            anchor_names=source_positions.keys(),
            allow_mapped_hierarchy=True,
        )
    detail_editability_issues = mapped_detail_editability_issues(root)
    if detail_editability_issues and preserve_existing_positions:
        # A locked production rig can still be used safely as its own
        # same-mesh placement baseline. Do not try to edit RigLogic/twist
        # branches merely to re-apply a pose that already matches this mesh;
        # the caller records the mesh signature after this no-op result.
        detail_report = {
            "mapped_existing_positions_preserved": True,
            "mapped_pose_preserved_due_locked_details": True,
            "mapped_detail_placement_skipped": True,
            "locked_detail_joint_count": len(detail_editability_issues),
            "locked_detail_joints": detail_editability_issues,
            "skip_reason": "approved same-mesh placement contains driven or locked detail joints",
        }
        _set_string_attr(
            root, DETAIL_REPORT_ATTR, json.dumps(detail_report, sort_keys=True)
        )
        return root, len(all_joints), 0, detail_report
    if detail_editability_issues:
        preview = ", ".join(detail_editability_issues[:8])
        if len(detail_editability_issues) > 8:
            preview += ", ..."
        cmds.error(
            "Mapped skeleton fit was not started: {0} body twist/corrective joints "
            "are locked or driven ({1}). Enter neutral-pose editing mode and remove "
            "or disable RigLogic/RBF/SwingTwist drivers, then run the fit again. "
            "No skeleton joints were changed.".format(
                len(detail_editability_issues), preview
            )
        )
    twist_fractions = _capture_mapped_twist_fractions(joint_map)
    placement_frame = placement_frame_from_mapping(joint_map)
    if not preserve_existing_positions and len(source_positions) >= 2:
        logical_source_positions = [
            placement_frame.world_to_logical(point) for point in source_positions.values()
        ]
        source_height = max(point[1] for point in logical_source_positions) - min(
            point[1] for point in logical_source_positions
        )
        target_positions = [
            placement_frame.world_to_logical(points[name]) for name in source_positions
        ]
        target_height = max(point[1] for point in target_positions) - min(
            point[1] for point in target_positions
        )
        scale_multiplier = target_height / max(source_height, 1.0e-6)
        _multiply_joint_local_translations(all_joints[1:], scale_multiplier)

    # Parents first. Each mapped descendant is subsequently restored to its own
    # solved anatomical target, while unmapped twist/facial/detail branches keep
    # the hierarchy and relative transforms authored by the user.
    ordered = sorted(
        canonical_joints.items(),
        key=lambda item: (cmds.ls(item[1], long=True) or [item[1]])[0].count("|"),
    )
    for canonical_name, joint in ordered:
        target = points.get(canonical_name)
        if target and not preserve_existing_positions:
            _set_joint_world_translation(joint, target)

    detail_report = place_mapped_detail_joints(
        mesh,
        root,
        joint_map,
        twist_fractions=twist_fractions,
    )
    root_short_name = _short_name(root)
    namespace = (
        root_short_name.rsplit(":", 1)[0]
        if ":" in root_short_name else ""
    )
    # Preferred bend axes are authored only after every mapped primary and
    # detail joint has reached its final placement/orientation. Set T-Pose does
    # not own or overwrite these values.
    orient_studio_twist_joints_like_parents(root)
    arm_frame_report = orient_studio_arm_chains(
        mesh, namespace=namespace
    )
    leg_frame_report = orient_studio_leg_reference_frames(
        mesh, namespace=namespace
    )
    configure_mapped_bend_axes(root, joint_map)
    digit_report = orient_studio_digit_chains(
        mesh,
        namespace=namespace,
        preserve_positions=preserve_existing_positions,
        preserve_knuckle_positions=True,
    )
    # Approved legacy mappings retain their authored knuckles, but the mesh
    # still owns the final fingertip cross-section. A single centering pass is
    # not sufficient on asymmetric caps (notably the ring and pinky on
    # Coolaid); recenter iteratively until the independent section audit
    # converges, just as the generated-template path does below.
    mapped_tip_iterations = []
    if mesh:
        mesh_height = max(float(get_mesh_bounds(mesh)["height"]), 1.0e-8)
        tip_tolerance = max(mesh_height * 1.0e-4, 1.0e-5)
        for iteration in range(6):
            offsets = _studio_fingertip_center_offsets(
                mesh, namespace=namespace
            )
            maximum_offset = max(
                (max(value) for value in offsets.values()), default=0.0
            )
            if maximum_offset <= tip_tolerance:
                break
            digit_report = orient_studio_digit_chains(
                mesh,
                namespace=namespace,
                preserve_positions=False,
                preserve_knuckle_positions=True,
            )
            mapped_tip_iterations.append({
                "iteration": iteration + 1,
                "max_offset_before": float(maximum_offset),
                "max_offset_after": float(max(
                    (
                        max(value)
                        for value in _studio_fingertip_center_offsets(
                            mesh, namespace=namespace
                        ).values()
                    ),
                    default=0.0,
                )),
            })
        final_offsets = _studio_fingertip_center_offsets(
            mesh, namespace=namespace
        )
        final_maximum_offset = max(
            (max(value) for value in final_offsets.values()), default=0.0
        )
        digit_report["mesh_tip_centering_iterations"] = mapped_tip_iterations
        digit_report["mesh_tip_centering_tolerance"] = float(tip_tolerance)
        digit_report["mesh_tip_centering_final_offsets"] = final_offsets
        digit_report["mesh_tip_centering_converged"] = bool(
            final_maximum_offset <= tip_tolerance
        )
        if final_maximum_offset > tip_tolerance:
            cmds.error(
                "Mapped skeleton fit failed fingertip centering: maximum "
                "cross-section offset {0:.6f} exceeds {1:.6f}.".format(
                    final_maximum_offset, tip_tolerance
                )
            )
    mapped_face_frame_report = orient_studio_face_local_y_up(root)
    mapped_brow_fit_report = (
        fit_studio_brow_arcs_to_surface(mesh, root, namespace=namespace)
        if mesh else {"skipped": True, "reason": "no_mesh"}
    )
    mapped_brow_orientation_report = orient_studio_brow_joints(
        mesh=mesh or "", namespace=namespace
    )
    animator_dof_report = enforce_studio_joint_dof_policy(
        namespace=namespace
    )
    mapped_eyelid_frame_report = orient_studio_eyelid_chains_to_tips(root)
    unlock_studio_joint_channels(root, namespace=namespace)
    detail_report["mapped_digit_orientation"] = digit_report
    detail_report["mapped_face_local_y_up"] = mapped_face_frame_report
    detail_report["mapped_brow_surface_fit"] = mapped_brow_fit_report
    detail_report["mapped_brow_orientation"] = mapped_brow_orientation_report
    detail_report["mapped_eyelid_x_to_tip"] = mapped_eyelid_frame_report
    detail_report["mapped_arm_reference_orientation"] = arm_frame_report
    detail_report["mapped_leg_reference_orientation"] = leg_frame_report
    detail_report["mapped_animator_dof_policy"] = animator_dof_report
    detail_report["mapped_existing_positions_preserved"] = bool(
        preserve_existing_positions
    )
    capture_current_pose_as_preferred_angles(root)
    _set_string_attr(root, TEMPLATE_SOURCE_ATTR, "active_hik_rig_mapping")
    _set_string_attr(root, DETAIL_REPORT_ATTR, json.dumps(detail_report, sort_keys=True))
    return root, len(all_joints), 0, detail_report


@undoable("Fit Studio Skeleton")
@cleanup_temp_bones
def fit_studio_template_skeleton(
    points: Dict[str, Vector3],
    mesh: str = "",
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    namespace: str = "",
    replace_existing: bool = True,
    approved_world_matrices: Optional[Dict[str, Sequence[float]]] = None,
) -> Tuple[str, int, int]:
    """Load or reuse the complete studio skeleton and fit it to solved anchors."""
    root = _find_template_joint("origin", namespace=namespace)
    if root:
        if not is_studio_template_skeleton(root, namespace=namespace):
            if _is_generated_joint(root) and replace_existing:
                cmds.delete(root)
                root = None
            else:
                cmds.error(
                    "Existing origin joint is not the studio template skeleton; refusing to replace it."
                )
        elif not replace_existing:
            cmds.error("The studio template skeleton already exists in this namespace.")
        else:
            # Update an existing approved hierarchy in place. Re-importing the
            # template leaves its supporting namespaces behind and Maya then
            # silently suffixes the requested namespace (for example,
            # jpLive -> jpLive1), so the placer no longer updates the same
            # skeleton on the next run. Approved world matrices below provide
            # the stable baseline for iterative corrections without replacing
            # the hierarchy or accumulating detailed-fit drift.
            root = (cmds.ls(root, long=True) or [root])[0]

    if not root:
        rig_template.load_biped_rig_template(
            template_path=template_path,
            namespace=namespace,
            reference=False,
            merge_namespaces_on_clash=False,
        )
        root = _find_template_joint("origin", namespace=namespace)
        if not root or not is_studio_template_skeleton(root, namespace=namespace):
            cmds.error("Loaded rig template did not produce the expected studio skeleton hierarchy.")

    root = (cmds.ls(root, long=True) or [root])[0]
    all_joints = [root] + (cmds.listRelatives(root, ad=True, type="joint", fullPath=True) or [])
    capture_studio_template_knee_bend_axes(namespace=namespace)
    current_scale = 1.0
    if cmds.attributeQuery(TEMPLATE_SCALE_ATTR, node=root, exists=True):
        current_scale = float(cmds.getAttr("{0}.{1}".format(root, TEMPLATE_SCALE_ATTR)) or 1.0)

    authored = extract_studio_template_core_points(template_path)
    authored_height = max(point[1] for point in authored.values()) - min(
        point[1] for point in authored.values()
    )
    target_height = max(point[1] for point in points.values()) - min(
        point[1] for point in points.values()
    )
    desired_scale = target_height / max(authored_height, 1.0e-6)
    scale_multiplier = desired_scale / max(current_scale, 1.0e-6)
    _multiply_joint_local_translations(all_joints[1:], scale_multiplier)

    detail_targets = {}
    topology_targets = {}
    reference_cases = []
    if mesh:
        # When the target has an approved exact-topology placement, keep its
        # transferred joints as the final authority.  The generic proportional
        # anchors below are useful for unseen topology, but can pull an
        # already-good shoulder, elbow, neck, head, or brow away from its
        # mesh-corresponded production position.
        topology_targets, reference_cases = solve_topology_reference_points(mesh)
        if topology_targets:
            detail_targets = dict(topology_targets)
        else:
            detail_targets, reference_cases = solve_reference_detail_points(mesh)
    # Keep exact-topology landmarks authoritative through the final frame
    # solvers.  Center-face X is re-centered below while retaining its
    # topology-matched Y/Z; neck2 remains the artist-approved mesh pivot even
    # when it is not the generic neck1/head1 midpoint.  Only distal digits are
    # delegated to the dedicated terminal-centering solvers.
    topology_restore_targets = {
        name: target
        for name, target in topology_targets.items()
        if name not in {
            "l_thumb_04", "r_thumb_04",
            "l_index_05", "l_middle_05", "l_ring_05", "l_pinky_05",
            "r_index_05", "r_middle_05", "r_ring_05", "r_pinky_05",
        }
    }
    if topology_restore_targets:
        spine_tip = _find_template_joint("spine5_Tip", namespace)
        if spine_tip and cmds.objExists(spine_tip):
            center_x = float(cmds.xform(
                spine_tip, query=True, worldSpace=True, translation=True
            )[0])
            for name in ("nose_root", "nose_upper", "nose_tip", "nose_base"):
                target = topology_restore_targets.get(name)
                if target is not None:
                    topology_restore_targets[name] = (
                        center_x, float(target[1]), float(target[2])
                    )
    if mesh and topology_restore_targets:
        bounds = get_mesh_bounds(mesh)
        bounds_tolerance = max(float(bounds["height"]) * 0.005, 1.0e-4)
        minimum = (bounds["min"].x, bounds["min"].y, bounds["min"].z)
        maximum = (bounds["max"].x, bounds["max"].y, bounds["max"].z)
        head_tip_tolerance = max(float(bounds["height"]) * 0.01, 1.0e-4)
        validated_bounds_tolerance = max(
            float(bounds["height"]) * 0.0025, 1.0e-4
        )
        bounded_targets = {}
        for name, target in topology_restore_targets.items():
            allowed_tolerance = (
                head_tip_tolerance if name == "head1_Tip" else bounds_tolerance
            )
            if not all(
                minimum[axis] - allowed_tolerance
                <= float(target[axis])
                <= maximum[axis] + allowed_tolerance
                for axis in range(3)
            ):
                continue
            if name == "head1_Tip":
                # Keep the approved crown-tip depth, but clamp its small
                # vertical overrun to the final validator's tighter margin.
                target = tuple(
                    min(
                        maximum[axis] + validated_bounds_tolerance - 1.0e-3,
                        max(
                            minimum[axis] - validated_bounds_tolerance + 1.0e-3,
                            float(target[axis]),
                        ),
                    )
                    for axis in range(3)
                )
            bounded_targets[name] = target
        topology_restore_targets = bounded_targets
    complete_topology_brows = bool(topology_targets) and all(
        "{0}_{1}".format(side, suffix) in topology_targets
        for side in ("l", "r")
        for suffix in (
            "brow1", "brow2", "brow3", "brow4", "brow5", "brow_end"
        )
    )
    if not complete_topology_brows:
        topology_restore_targets = {
            name: target
            for name, target in topology_restore_targets.items()
            if not re.match(r"^(?:l|r)_brow(?:[1-5]|_end)$", name, re.I)
        }
    targets_by_name = dict(detail_targets)
    for canonical_name in BUILD_ORDER:
        template_name = TEMPLATE_CORE_JOINTS.get(canonical_name)
        target = points.get(canonical_name)
        if template_name and target:
            targets_by_name[template_name] = target
    if topology_targets:
        targets_by_name.update(topology_targets)

    internal_head_targets = {}
    if mesh:
        internal_head_targets, internal_head_references = (
            solve_reference_internal_head_points(mesh)
        )
        targets_by_name.update(internal_head_targets)
        targets_by_name.update(solve_scene_eye_mesh_centers(mesh))
        targets_by_name.update(solve_scene_oral_mesh_points(mesh))
        toe_targets, toe_references = solve_reference_toe_points(mesh)
        targets_by_name.update(toe_targets)
        reference_cases = list(dict.fromkeys(
            list(reference_cases)
            + list(internal_head_references)
            + list(toe_references)
        ))

    if mesh and all(
        name in targets_by_name
        for name in ("spine5", "l_clavicle", "r_clavicle")
    ):
        # Local surface-affine transfer is excellent for limbs and digits, but
        # an internal upper-thoracic point is far from a well-conditioned
        # surface patch. Anchor the branch point to the reliable clavicle pair:
        # approved studio rigs place spine5_Tip about 2.44% of body height above
        # their average, at the base of the neck. Keep X/Z exactly above spine5.
        bounds = get_mesh_bounds(mesh)
        query = _cached_mesh_interior_query(mesh)
        spine5_point = targets_by_name["spine5"]
        clavicle_y = (
            targets_by_name["l_clavicle"][1]
            + targets_by_name["r_clavicle"][1]
        ) * 0.5
        preferred_y = clavicle_y + (bounds["height"] * 0.0244)
        y_candidates = [preferred_y]
        for step in range(1, 7):
            offset = bounds["height"] * 0.0025 * step
            y_candidates.extend((preferred_y - offset, preferred_y + offset))
        tip_target = next(
            (
                (spine5_point[0], y_value, spine5_point[2])
                for y_value in y_candidates
                if query.point_inside((spine5_point[0], y_value, spine5_point[2]))
            ),
            (spine5_point[0], preferred_y, spine5_point[2]),
        )
        targets_by_name["spine5_Tip"] = tip_target
        neck_offset = max(bounds["height"] * 0.001, query.tolerance * 20.0)
        neck_target = (
            tip_target[0],
            tip_target[1] + neck_offset,
            tip_target[2],
        )
        if query.point_inside(neck_target):
            targets_by_name["neck1"] = neck_target

    if mesh:
        # The reference transfer tends to settle the medial clavicle pivots on
        # the upper-chest row. Raise them slightly toward the palpable
        # clavicular ridge while leaving spine5_Tip and the shoulders fixed.
        bounds = get_mesh_bounds(mesh)
        query = _cached_mesh_interior_query(mesh)
        clavicle_lift = bounds["height"] * STUDIO_CLAVICLE_LIFT_HEIGHT_RATIO
        for clavicle_name in ("l_clavicle", "r_clavicle"):
            clavicle_target = targets_by_name.get(clavicle_name)
            if not clavicle_target:
                continue
            for multiplier in (1.0, 0.75, 0.5, 0.25):
                candidate = (
                    clavicle_target[0],
                    clavicle_target[1] + clavicle_lift * multiplier,
                    clavicle_target[2],
                )
                if query.point_inside(candidate):
                    targets_by_name[clavicle_name] = candidate
                    break

        # The compact-section solver finds the top of the knee transition on
        # this topology. The actual flexion axis sits slightly lower, through
        # the center of the knee bend. Preserve X/Z (and therefore the leg IK
        # plane) while applying a character-scale vertical correction.
        knee_drop = bounds["height"] * STUDIO_KNEE_DROP_HEIGHT_RATIO
        for knee_name in ("l_knee", "r_knee"):
            knee_target = targets_by_name.get(knee_name)
            if not knee_target:
                continue
            for multiplier in (1.0, 0.75, 0.5, 0.25):
                candidate = (
                    knee_target[0],
                    knee_target[1] - knee_drop * multiplier,
                    knee_target[2],
                )
                if query.point_inside(candidate):
                    targets_by_name[knee_name] = candidate
                    break

    core_refinement_report = {}
    if mesh:
        core_refinement_report = refine_studio_core_targets_for_mesh(
            targets_by_name, mesh
        )

    # Apply every target exactly once, parents first. Repositioning core joints
    # in a second pass would otherwise drag the atlas-seeded fingers, face, and
    # corrective branches away from their approved world-space locations.
    for joint in sorted(all_joints, key=lambda node: node.count("|")):
        target = targets_by_name.get(_short_name(joint).split(":")[-1])
        if target:
            _set_joint_world_translation(joint, target)

    template_joint_nodes = set(all_joints)
    # Reverse-foot helpers remain in their imported template pose here. They
    # are snapped only after skin weights have been imported, when the final
    # deformation ankle/toe chain is authoritative.
    for side in ("l", "r"):
        heel = _find_template_joint("{0}_heel_RFL".format(side), namespace)
        if heel:
            _tag_generated_joint(heel)
            template_joint_nodes.add(heel)
            template_joint_nodes.update(
                cmds.listRelatives(heel, ad=True, type="joint", fullPath=True) or []
            )

    _tag_generated_joint(root)
    _set_float_attr(root, TEMPLATE_SCALE_ATTR, desired_scale)
    _set_string_attr(
        root,
        TEMPLATE_SOURCE_ATTR,
        str(Path(template_path).expanduser().resolve()).replace("\\", "/"),
    )
    _set_string_attr(root, REFERENCE_ATLAS_ATTR, json.dumps(reference_cases))
    if not detail_targets:
        enforce_studio_finger_planarity(root, namespace=namespace)
    brow_reference_positions = {}
    if mesh:
        fit_studio_hand_joints(
            mesh,
            root,
            namespace=namespace,
            preserve_reference_layout=bool(detail_targets),
        )
        volume_report = fit_studio_detail_joints_to_volume(
            mesh,
            root,
            namespace=namespace,
            preserve_reference_layout=bool(detail_targets),
        )
        volume_report["distal_thumbs"] = fit_studio_distal_thumb_joints(
            mesh,
            namespace=namespace,
        )
        volume_report["finger_knuckle_height"] = fit_studio_finger_knuckle_height(
            mesh,
            namespace=namespace,
        )
        volume_report["arm_red_dot_refinement"] = fit_studio_arm_red_dot_refinement(
            mesh,
            namespace=namespace,
        )
        volume_report["scene_feature_meshes"] = fit_studio_scene_feature_joints(
            mesh,
            namespace=namespace,
        )
        volume_report["core_refinement"] = core_refinement_report
        volume_report["brows"] = fit_studio_brow_arcs_to_surface(
            mesh,
            root,
            namespace=namespace,
        )
        brow_profile_report = (
            {
                "source": "exact_topology_reference_preserved",
                "placed_count": 0,
            }
            if complete_topology_brows
            else fit_studio_brows_from_left_profile(
                mesh,
                namespace=namespace,
            )
        )
        volume_report["brow_profile"] = brow_profile_report
        if complete_topology_brows:
            brow_reference_positions = {
                name: target
                for name, target in topology_targets.items()
                if re.match(r"^(?:l|r)_brow(?:[1-5]|_end)$", name, re.I)
            }
        else:
            brow_reference_positions = dict(
                brow_profile_report.get("placed") or {}
            )
        volume_report["lips"] = fit_studio_lip_joints_to_surface(
            mesh,
            namespace=namespace,
        )
        volume_report["eyelids"] = fit_studio_eyelid_joints_to_surface(
            mesh,
            root,
            namespace=namespace,
        )
        validate_studio_final_joint_placement(
            mesh, root, stage="facial feature placement"
        )
        volume_report["foot_front_flare"] = fit_studio_foot_front_flare(
            mesh,
            namespace=namespace,
        )
        volume_report["toe_volume_centers"] = fit_studio_toe_pivots_to_volume(
            mesh,
            namespace=namespace,
        )
        volume_report["pelvis_ridge"] = fit_studio_pelvis_ridge(
            mesh,
            namespace=namespace,
        )
    mirror_studio_right_leg_from_left(namespace=namespace)
    volume_report["thigh_pelvis_depth"] = align_studio_thigh_roots_to_pelvis_depth(
        namespace=namespace
    )
    if mesh:
        volume_report["leg_front_projection"] = align_studio_leg_front_projection(
            mesh,
            namespace=namespace,
        )
        volume_report["spine_neck_head_final"] = finalize_studio_spine_neck_head(
            mesh,
            namespace=namespace,
        )
        validate_studio_final_joint_placement(
            mesh, root, stage="spine/neck/head final placement"
        )
        volume_report["neck_head_jaw_relative"] = fit_studio_neck_head_jaw_relative(
            mesh,
            namespace=namespace,
        )
        volume_report["center_face_positions"] = align_studio_center_face_positions(
            mesh,
            namespace=namespace,
        )
        validate_studio_final_joint_placement(
            mesh, root, stage="neck/head/jaw relative placement"
        )
        volume_report["leg_twists"] = _fit_studio_twist_segments(namespace)
        _set_string_attr(
            root,
            STUDIO_VOLUME_REPORT_ATTR,
            json.dumps(volume_report, sort_keys=True),
        )
    approved_rerun = bool(approved_world_matrices)
    approved_positions = None
    if approved_world_matrices:
        volume_report["approved_frames_restored"] = (
            _restore_studio_joint_world_matrices(
                root, approved_world_matrices
            )
        )
        volume_report["approved_positions_locked"] = len(approved_world_matrices)

    # Fresh builds apply topology-relative arm, hand, and digit landmarks.
    # Reruns retain approved pivots except for narrowly specified anatomical
    # corrections, currently the deterministic distal-thumb rest bend below.
    if mesh and not approved_rerun:
        volume_report["arm_hand_reference_landmarks"] = (
            fit_studio_arm_hand_from_reference(
                mesh,
                namespace=namespace,
                reference_targets=detail_targets,
            )
        )
        volume_report["arm_mesh_hinge_plane"] = (
            fit_studio_arm_hinge_plane_to_mesh(
                mesh,
                namespace=namespace,
            )
        )
        volume_report["arm_hand_reference_volume_conform"] = (
            fit_studio_hand_joints(
                mesh,
                root,
                namespace=namespace,
                preserve_reference_layout=bool(detail_targets),
            )
        )
        # The final hand conform pass deliberately centers each digit through
        # its local mesh section. Restore the studio dorsal pivot convention
        # afterward: each joint 02 sits two thirds from the lower surface,
        # joints 03-04 follow the mesh pose, and joint 05 remains centered in
        # the fingertip.
        volume_report["finger_knuckle_height_after_arm_refit"] = (
            fit_studio_finger_knuckle_height(
                mesh,
                namespace=namespace,
                upper_fraction=2.0 / 3.0,
            )
        )
        # Elbow and wrist are the endpoints for both forearm twist chains.
        # Rebuild their fractions immediately so validation compares one
        # coherent corrected arm rather than the former atlas-height twists.
        volume_report["arm_twists_after_reference_restore"] = (
            _fit_studio_twist_segments(namespace)
        )
        # Atlas placement owns digit proportions and palm spread. Flatten only
        # joints 02-terminal afterward so the articulated phalanges share one
        # bend plane without changing the metacarpal fan.
        volume_report["finger_02_terminal_planarity"] = (
            enforce_studio_finger_planarity(
                root,
                namespace=namespace,
                mesh=mesh,
            )
        )

    # Thumb 02-04 must remain in one curl plane, while topology-transferred
    # thumb02/thumb03 landmarks remain authoritative for the visible knuckles.
    # Apply this narrow correction on approved reruns as well; every other
    # approved digit pivot remains locked.
    if mesh:
        volume_report["distal_thumb_rest_bend"] = (
            fit_studio_distal_thumb_joints(
                mesh,
                namespace=namespace,
                smoothing=1.0,
            )
        )
    if mesh:
        volume_report["thumb_root_depth"] = fit_studio_thumb_root_depth(
            mesh,
            namespace=namespace,
            dorsal_fraction=0.45,
        )

    # ``origin`` is the rig-space/world reference, not an anatomical
    # landmark. Its translate channels must remain exactly zero; compensate
    # the child matrix so this does not disturb any fitted joint positions.
    zero_origin_translation_preserving_children(root)
    if approved_rerun:
        approved_positions = _capture_studio_joint_positions(root)
    if topology_targets and not approved_rerun:
        # Restore mesh-corresponded targets after all positional refinement but
        # before any frame solver runs.  This lets the head, neck, arm, and
        # digit orientations use their final approved pivot locations.
        volume_report["topology_reference_positions_before_orientation"] = (
            _restore_studio_joint_world_positions(root, topology_restore_targets)
        )
    fitted_positions = _capture_studio_joint_positions(root)
    if not brow_reference_positions:
        brow_reference_positions = {
            name: point
            for name, point in fitted_positions.items()
            if re.match(r"^(?:l|r)_brow(?:[1-5]|_end)$", name, re.I)
        }
    if not approved_rerun:
        orient_studio_single_child_chains(root, namespace=namespace)
    if mesh and not approved_rerun:
        validate_studio_final_joint_placement(
            mesh,
            root,
            fitted_positions=fitted_positions,
            stage="generic single-child orientation",
        )
    if not approved_rerun:
        orient_studio_root_pelvis_hipswing_y_up(namespace=namespace)
    # The generic pass cannot know which child is the primary arm chain and can
    # roll a joint toward a twist branch. Re-author the complete clavicle-to-
    # hand chain afterward so its X/Y/Z frame is authoritative.
    orient_studio_spine_vertical(namespace=namespace)
    # The generic single-child pass also sees ankle/toe chains and freezes
    # their bend into jointOrient. Re-author the leg chain afterward so toe
    # bend remains on animator-facing rotateZ, jointOrient stays zero, and
    # toe/toeTip offsets remain signed local-X only.
    orient_studio_leg_chains(namespace=namespace)
    # Head fitting and approved-matrix restoration are both complete now.
    # Reassert the anatomical midpoint immediately before orienting the neck so
    # every later frame is solved from the final neck1/head1 endpoints.
    if not approved_rerun:
        volume_report["neck2_final_midpoint"] = enforce_studio_neck2_midpoint(
            namespace=namespace
        )
    fitted_positions = _capture_studio_joint_positions(root)
    orient_studio_head_chains(
        namespace=namespace,
        include_oral=not approved_rerun,
    )
    if not approved_rerun:
        orient_studio_teeth_scene_y_up(namespace=namespace)
    volume_report["neck1_grid_standard"] = orient_studio_neck1_grid_standard(
        namespace=namespace
    )
    if not approved_rerun:
        volume_report["center_face_grid_axes"] = orient_studio_center_face_grid_axes(
            namespace=namespace
        )
    volume_report["center_face_local_zeroes"] = (
        enforce_studio_center_face_local_zeroes(
            namespace=namespace,
            preserve_nose_root_depth=bool(topology_targets),
        )
    )
    # Local-zero enforcement can move the joint itself while preserving its
    # children. Refresh every affected nose target so final drift validation
    # compares against the actual authored standard, including nose_base X=0.
    for name in ("nose_root", "nose_upper", "nose_tip", "nose_base"):
        joint = _find_template_joint(name, namespace)
        if joint:
            fitted_positions[name] = tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
    # Run arms first and preserve the transferred production frame exactly.
    # The elbow policy pass tags local Z without rerolling the arm. Digits
    # follow afterward so hand orientation cannot alter finished finger frames.
    volume_report["arm_reference_orientation"] = orient_studio_arm_chains(
        mesh=mesh or "",
        namespace=namespace,
    )
    volume_report["elbow_z_hinges"] = enforce_studio_elbow_z_hinges(
        namespace=namespace,
    )
    volume_report["leg_reference_orientation"] = orient_studio_leg_reference_frames(
        mesh=mesh or "",
        namespace=namespace,
    )
    volume_report["knee_y_hinges"] = enforce_studio_knee_y_hinges(
        namespace=namespace,
    )
    volume_report["digit_reference_orientation"] = orient_studio_digit_chains(
        mesh=mesh or "",
        namespace=namespace,
        preserve_positions=approved_rerun,
        preserve_knuckle_positions=bool(detail_targets),
    )
    # Twist joints inherit their parent's exact world orientation. They must
    # not duplicate the parent's Euler values locally or the rotation is
    # applied twice. Re-align after the parent orientation cleanup so every
    # twist ends with jointOrient/rotateAxis/rotate all at zero.
    orient_studio_twist_joints_like_parents(root, namespace=namespace)
    enforce_studio_twist_translate_x(root)
    configure_studio_bend_axes(root, namespace=namespace)
    volume_report["orientation_channels"] = (
        move_all_studio_joint_orientation_to_rotate(
            root,
            namespace=namespace,
        )
    )
    volume_report["elbow_reference_bend_axes"] = (
        configure_studio_elbow_bend_axes_from_channels(namespace=namespace)
    )
    volume_report["thumb_z_only_rotates"] = (
        enforce_studio_thumb_z_only_rotates(namespace=namespace)
    )
    # Author brows last: reorienting the scaled head parent while converting
    # channels can slightly shear sibling world matrices. The final mesh-aware
    # pass guarantees exact X-to-next aim on both fresh and approved reruns.
    volume_report["brow_orientation"] = orient_studio_brow_joints(
        mesh=mesh or "", namespace=namespace
    )
    volume_report["surface_face_orientation"] = (
        orient_studio_surface_face_joints(mesh or "", root)
    )
    volume_report["eyelid_tip_zero_rotates"] = (
        zero_studio_eyelid_tip_rotates(root)
    )
    if brow_reference_positions:
        volume_report["brow_positions_final_restore"] = (
            _restore_studio_joint_world_positions(
                root, brow_reference_positions
            )
        )
    if approved_positions:
        volume_report["approved_positions_final_restore"] = (
            _restore_studio_joint_world_positions(root, approved_positions)
        )
        fitted_positions = dict(approved_positions)
        volume_report["approved_center_face_local_zeroes_final_restore"] = (
            enforce_studio_center_face_local_zeroes(
                namespace=namespace,
                preserve_nose_root_depth=bool(topology_targets),
            )
        )
        for name in ("nose_root", "nose_upper", "nose_tip", "nose_base"):
            joint = _find_template_joint(name, namespace)
            if joint:
                fitted_positions[name] = tuple(cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                ))
    elif topology_restore_targets:
        volume_report["topology_reference_positions_final_restore"] = (
            _restore_studio_joint_world_positions(root, topology_restore_targets)
        )
        if "neck2" in topology_restore_targets:
            neck1 = _find_template_joint("neck1", namespace)
            neck2 = _find_template_joint("neck2", namespace)
            head1 = _find_template_joint("head1", namespace)
            if neck1 and neck2:
                _orient_joint_x_to_child(
                    neck1, neck2, world_up=(0.0, 0.0, 1.0)
                )
            if neck2 and head1:
                _orient_joint_x_to_child(
                    neck2, head1, world_up=(0.0, 0.0, 1.0)
                )
            # The topology restore changes the neck2 aim direction. Re-author
            # the neck frames from those final pivots, then return orientation
            # from jointOrient to animator-facing rotate channels.
            volume_report["neck_reference_orientation_after_restore"] = (
                move_all_studio_joint_orientation_to_rotate(
                    root, namespace=namespace
                )
            )
        fitted_positions = _capture_studio_joint_positions(root)
    volume_report["face_local_y_up_relative_to_x"] = (
        orient_studio_face_local_y_up(root)
    )
    capture_current_pose_as_preferred_angles(root)
    volume_report["digit_rest_frames_zeroed"] = (
        zero_studio_digit_non_curl_rotations(namespace=namespace)
    )
    # Parent-frame conversion above can change the hand's world dorsal normal.
    # Refit the digit curl frames against that final hand frame, after all
    # orientation cleanup, and recenter terminal tips in their final sections.
    volume_report["final_digit_dorsal_frame"] = orient_studio_digit_chains(
        mesh=mesh or "",
        namespace=namespace,
        preserve_positions=False,
        preserve_knuckle_positions=True,
    )
    # The terminal recentering above may move joint 05 slightly off the
    # articulated curl plane. Re-project the complete 02-05 chain, then update
    # its local frames without moving the now-centered pivots. This guarantees
    # X-only offsets and a shared Z curl plane all the way through the tip.
    final_digit_planes = {}
    final_digit_query = _cached_mesh_interior_query(mesh) if mesh else None
    for name, chain in _studio_finger_chains(namespace).items():
        final_digit_planes[name] = _project_finger_chain_to_tip_plane(
            chain, query=final_digit_query
        )
    volume_report["final_finger_02_05_planarity"] = final_digit_planes
    volume_report["final_finger_02_05_frames"] = orient_studio_digit_chains(
        mesh=mesh or "",
        namespace=namespace,
        preserve_positions=True,
        preserve_knuckle_positions=True,
    )
    final_fingertip_tolerance = max(
        float(get_mesh_bounds(mesh)["height"]) * 1.0e-4,
        1.0e-5,
    ) if mesh else 1.0e-5
    fingertip_iterations = []
    for iteration in range(5):
        offsets_before = _studio_fingertip_center_offsets(
            mesh, namespace=namespace
        ) if mesh else {}
        maximum_before = max(
            (max(value) for value in offsets_before.values()),
            default=0.0,
        )
        if maximum_before <= final_fingertip_tolerance:
            break
        # Recenter against the current terminal segment, then refit the plane
        # through the recentered tip. Iterate because moving joint 04 changes
        # the final segment's local cross-section direction.
        volume_report["final_digit_dorsal_frame"] = orient_studio_digit_chains(
            mesh=mesh or "",
            namespace=namespace,
            preserve_positions=False,
            preserve_knuckle_positions=True,
        )
        iteration_planes = {}
        final_digit_query = _cached_mesh_interior_query(mesh) if mesh else None
        for name, chain in _studio_finger_chains(namespace).items():
            iteration_planes[name] = _project_finger_chain_to_tip_plane(
                chain, query=final_digit_query
            )
        volume_report["final_finger_02_05_planarity"] = iteration_planes
        volume_report["final_finger_02_05_frames"] = orient_studio_digit_chains(
            mesh=mesh or "",
            namespace=namespace,
            preserve_positions=True,
            preserve_knuckle_positions=True,
        )
        offsets_after = _studio_fingertip_center_offsets(
            mesh, namespace=namespace
        ) if mesh else {}
        fingertip_iterations.append({
            "iteration": iteration + 1,
            "max_offset_before": float(maximum_before),
            "max_offset_after": float(max(
                (max(value) for value in offsets_after.values()),
                default=0.0,
            )),
        })
    volume_report["fingertip_centering_iterations"] = {
        "iterations": fingertip_iterations,
        "tolerance": float(final_fingertip_tolerance),
        "final_offsets": _studio_fingertip_center_offsets(
            mesh, namespace=namespace
        ) if mesh else {},
    }
    # These terminal corrections are intentional, topology-aware digit
    # placement. Refresh only the digit baseline after them; the final audit
    # still checks their X-only offsets, shared bend plane, Z curl axis, and
    # actual mesh-section tip centering.
    for chain in _studio_finger_chains(namespace).values():
        for joint in chain:
            name = _short_name(joint).split(":")[-1]
            fitted_positions[name] = tuple(cmds.xform(
                joint, query=True, worldSpace=True, translation=True
            ))
    volume_report["animator_dof_policy"] = enforce_studio_joint_dof_policy(
        namespace=namespace
    )
    # Maya's joint DoF flags may relock their corresponding rotate plugs.
    # Keep the intended bend axes in the joint metadata while leaving every
    # transform channel directly editable for the rigging workflow.
    unlock_studio_joint_channels(root, namespace=namespace)
    volume_report["eyelid_x_to_tip"] = orient_studio_eyelid_chains_to_tips(root)
    unlock_studio_joint_channels(root, namespace=namespace)
    if mesh:
        volume_report["final_joint_placement"] = validate_studio_final_joint_placement(
            mesh,
            root,
            fitted_positions=fitted_positions,
            validate_orientations=True,
            validate_center_face_alignment=not (approved_rerun or topology_targets),
            validate_fingertip_centering=True,
            validate_neck2_midpoint="neck2" not in topology_restore_targets,
            validate_nose_root_local_zero="nose_root" not in topology_restore_targets,
        )
        _set_string_attr(
            root,
            STUDIO_VOLUME_REPORT_ATTR,
            json.dumps(volume_report, sort_keys=True),
        )
    return root, len(all_joints), len(template_joint_nodes) - len(all_joints)


@undoable("Preview Joint Placement")
def preview_biped_joint_placement(
    mesh: str,
    solver: str = "production",
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    create_guides: bool = True,
    joint_map: Optional[dict] = None,
) -> PlacementPreview:
    """Solve and validate placement without creating or replacing a skeleton."""
    clear_mesh_query_cache()
    mesh = _as_mesh_transform(mesh)
    solver_name = str(solver or "production").strip().lower()
    placement_frame = (
        placement_frame_from_mapping(joint_map)
        if mapped_hierarchy_requested(joint_map)
        else PlacementFrame()
    )
    if solver_name in {"production", "hybrid", "volume", "ml_hybrid"}:
        points, confidence, mesh_report, outside_joints, clearance = solve_production_biped_points(
            mesh,
            landmark_points=landmark_points,
            template_path=template_path,
            joint_map=joint_map,
        )
        method = "production_hybrid"
        resolved_template_path = str(Path(template_path).expanduser().resolve()).replace("\\", "/")
    elif solver_name in {"basic", "proportional", "legacy"}:
        points, confidence = solve_basic_biped_points(mesh)
        mesh_report = analyze_mesh_for_joint_placement(mesh)
        outside_joints = validate_points_inside_mesh(mesh, points)
        clearance = {}
        method = "legacy_proportional"
        resolved_template_path = ""
    else:
        cmds.error("Unknown joint placement solver: {0}".format(solver))

    anatomical_issues = validate_anatomical_layout(
        points,
        get_mesh_bounds(mesh),
        frame=placement_frame,
    )
    requires_review = bool(
        outside_joints or anatomical_issues or not mesh_report.is_closed_manifold
    )
    pose_type, pose_angle_degrees = classify_arm_pose(points, frame=placement_frame)
    planar_deviation = measure_planar_deviation(points, frame=placement_frame)
    guides = []
    if create_guides:
        guides = create_guides_from_points(
            points,
            confidence=confidence,
            outside_joints=outside_joints,
        )

    return PlacementPreview(
        mesh=mesh,
        points=points,
        confidence=confidence,
        clearance=clearance,
        geometry_report=mesh_report.as_dict(),
        outside_joints=outside_joints,
        anatomical_issues=anatomical_issues,
        pose_type=pose_type,
        pose_angle_degrees=pose_angle_degrees,
        planar_deviation=planar_deviation,
        method=method,
        template_path=resolved_template_path,
        requires_review=requires_review,
        guides=guides,
    )


@undoable("Place Biped Joints")
@cleanup_temp_bones
def build_basic_biped_skeleton(
    mesh: str,
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
    solver: str = "production",
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    template_namespace: str = "",
    require_interior: bool = False,
    joint_map: Optional[dict] = None,
    import_skin_weights: bool = False,
) -> PlacementResult:
    approved_world_matrices = None
    existing_root = _find_template_joint("origin", namespace=template_namespace)
    if (
        replace_existing
        and not mapped_hierarchy_requested(joint_map)
        and existing_root
        and cmds.objExists(existing_root)
        and is_studio_template_skeleton(
            existing_root, namespace=template_namespace
        )
    ):
        if _approved_placement_matches_mesh(existing_root, mesh):
            approved_world_matrices = _capture_studio_joint_world_matrices(
                existing_root
            )
        else:
            has_signature = cmds.attributeQuery(
                PLACEMENT_MESH_SIGNATURE_ATTR,
                node=existing_root,
                exists=True,
            )
            if not has_signature and _legacy_studio_pose_matches_mesh(
                existing_root,
                mesh,
                anchor_names=extract_studio_template_core_points(
                    template_path
                ).keys(),
            ):
                approved_world_matrices = _capture_studio_joint_world_matrices(
                    existing_root
                )
                cmds.warning(
                    "[joint_placer] Preserving the existing legacy studio pose "
                    "because its core anchors already fit the selected mesh."
                )
            else:
                cmds.warning(
                    "[joint_placer] Existing approved positions belong to a different "
                    "mesh; refitting the hierarchy from the selected mesh."
                )

    preview = preview_biped_joint_placement(
        mesh,
        solver=solver,
        landmark_points=landmark_points,
        template_path=template_path,
        create_guides=create_guides,
        joint_map=joint_map,
    )
    if require_interior and preview.outside_joints:
        cmds.error(
            "Joint placement could not prove these joints are inside the mesh: {0}".format(
                ", ".join(preview.outside_joints)
            )
        )
    if preview.requires_review:
        reasons = []
        if not preview.geometry_report["is_closed_manifold"]:
            reasons.append("mesh is not one closed manifold shell")
        if preview.outside_joints:
            reasons.append("unverified joints: {0}".format(", ".join(preview.outside_joints)))
        if preview.anatomical_issues:
            reasons.append("anatomy checks: {0}".format("; ".join(preview.anatomical_issues)))
        cmds.warning("[joint_placer] Review required: {0}.".format("; ".join(reasons)))

    template_joint_count = 0
    reverse_foot_joint_count = 0
    detail_placement_report = {}
    use_mapped_hierarchy = (
        preview.method == "production_hybrid"
        and mapped_hierarchy_requested(joint_map)
    )
    if preview.method == "production_hybrid":
        if use_mapped_hierarchy:
            root_joint, template_joint_count, reverse_foot_joint_count, detail_placement_report = fit_mapped_skeleton(
                mesh,
                preview.points,
                joint_map,
            )
        else:
            root_joint, template_joint_count, reverse_foot_joint_count = fit_studio_template_skeleton(
                preview.points,
                mesh=mesh,
                template_path=template_path,
                namespace=template_namespace,
                replace_existing=replace_existing,
                approved_world_matrices=approved_world_matrices,
            )
        tag_pose_metadata(root_joint, preview.pose_type, preview.pose_angle_degrees)
        _connect_placement_mesh(root_joint, preview.mesh)
    else:
        # The proportional hierarchy remains an internal fallback for the
        # explicitly requested legacy solver; it is not a selectable layout.
        root_joint = build_skeleton_from_points(
            preview.points,
            root_name="origin",
            orient=orient,
            replace_existing=replace_existing,
            pose_type=preview.pose_type,
            pose_angle_degrees=preview.pose_angle_degrees,
        )

    result_outside_joints = list(preview.outside_joints)
    if (
        not use_mapped_hierarchy
        and root_joint
        and cmds.attributeQuery(HAND_FIT_REPORT_ATTR, node=root_joint, exists=True)
    ):
        try:
            hand_report = json.loads(
                cmds.getAttr("{0}.{1}".format(root_joint, HAND_FIT_REPORT_ATTR)) or "{}"
            )
        except (TypeError, ValueError):
            hand_report = {}
        detail_placement_report["studio_hand_fit"] = hand_report
        result_outside_joints.extend(hand_report.get("outside_joints") or [])
        if cmds.attributeQuery(STUDIO_VOLUME_REPORT_ATTR, node=root_joint, exists=True):
            try:
                volume_report = json.loads(
                    cmds.getAttr(
                        "{0}.{1}".format(root_joint, STUDIO_VOLUME_REPORT_ATTR)
                    ) or "{}"
                )
            except (TypeError, ValueError):
                volume_report = {}
            detail_placement_report["studio_volume_fit"] = volume_report
            result_outside_joints.extend(volume_report.get("outside_joints") or [])
    result_outside_joints = list(dict.fromkeys(result_outside_joints))
    if require_interior and result_outside_joints:
        cmds.error(
            "Joint placement could not prove these joints are inside the mesh: {0}".format(
                ", ".join(result_outside_joints)
            )
        )

    if use_mapped_hierarchy:
        body_joint_map = joint_map
        face_joint_map = setup_hik.populate_default_face_map_from_scene()
        missing_slots = mapped_hierarchy_missing_slots(body_joint_map)
    else:
        body_joint_map, face_joint_map = make_hik_maps_from_root(root_joint)
        missing_slots = validate_body_joint_map(body_joint_map)
    if missing_slots:
        cmds.warning(
            "[joint_placer] Generated skeleton did not fill HIK slots: {0}".format(
                ", ".join(missing_slots)
            )
        )

    if import_skin_weights:
        detail_placement_report["skin_weight_import"] = import_matching_skin_weights(
            preview.mesh
        )
    else:
        detail_placement_report["skin_weight_import"] = {
            "mesh": _short_name(preview.mesh),
            "imported": False,
            "skipped": True,
            "reason": "disabled_for_joint_placement_performance",
        }

    preserved_approved_mapped_pose = bool(
        use_mapped_hierarchy
        and detail_placement_report.get(
            "mapped_pose_preserved_due_locked_details"
        )
    )
    detail_placement_report["removed_auto_joint_guides"] = (
        0 if preserved_approved_mapped_pose else delete_auto_joint_guides()
    )
    if preserved_approved_mapped_pose:
        detail_placement_report["auto_joint_guides_cleanup_skipped"] = (
            "approved same-mesh pose preserved without scene cleanup"
        )
    result_points = dict(preview.points)
    result_anatomical_issues = list(preview.anatomical_issues)
    if preserved_approved_mapped_pose:
        # This was a deliberate no-op on a same-mesh approved pose. Generic
        # solver diagnostics describe hypothetical target points, not the
        # unchanged rig, so report the actual mapped pivots and keep those
        # preview-only warnings from mislabeling the preserved production rig.
        result_outside_joints = []
        result_anatomical_issues = []
        for canonical_name, joint in mapped_anatomical_joints(
            body_joint_map
        ).items():
            if canonical_name in result_points and cmds.objExists(joint):
                result_points[canonical_name] = tuple(cmds.xform(
                    joint, query=True, worldSpace=True, translation=True
                ))
        detail_placement_report["hypothetical_preview_diagnostics"] = {
            "outside_joints": list(preview.outside_joints),
            "anatomical_issues": list(preview.anatomical_issues),
            "suppressed_for_preserved_pose": True,
        }
        _set_string_attr(
            root_joint,
            DETAIL_REPORT_ATTR,
            json.dumps(detail_placement_report, sort_keys=True),
        )

    return PlacementResult(
        root_joint=root_joint,
        body_joint_map=body_joint_map,
        face_joint_map=face_joint_map,
        points=result_points,
        confidence=preview.confidence,
        pose_type=preview.pose_type,
        pose_angle_degrees=preview.pose_angle_degrees,
        planar_deviation=preview.planar_deviation,
        method=(preview.method + "_mapped") if use_mapped_hierarchy else preview.method,
        template_path=preview.template_path,
        geometry_report=preview.geometry_report,
        outside_joints=result_outside_joints,
        anatomical_issues=result_anatomical_issues,
        clearance=preview.clearance,
        template_joint_count=template_joint_count,
        reverse_foot_joint_count=reverse_foot_joint_count,
        requires_review=(
            (preview.requires_review and not preserved_approved_mapped_pose)
            or bool(result_outside_joints)
            or bool(detail_placement_report.get("skipped_unverified"))
            or bool(detail_placement_report.get("unclassified_corrective_joints"))
            or bool(detail_placement_report.get("corrective_validation_errors"))
            or bool(detail_placement_report.get("twist_validation_errors"))
        ),
        detail_placement_report=detail_placement_report,
    )


def create_auto_joints_for_mesh(
    mesh: str,
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
    solver: str = "production",
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    template_namespace: str = "",
    require_interior: bool = False,
    joint_map: Optional[dict] = None,
    import_skin_weights: bool = False,
) -> Tuple[dict, dict]:
    result = build_basic_biped_skeleton(
        mesh=mesh,
        orient=orient,
        replace_existing=replace_existing,
        create_guides=create_guides,
        solver=solver,
        landmark_points=landmark_points,
        template_path=template_path,
        template_namespace=template_namespace,
        require_interior=require_interior,
        joint_map=joint_map,
        import_skin_weights=import_skin_weights,
    )
    return result.body_joint_map, result.face_joint_map


def preview_selected_mesh_joint_placement(
    solver: str = "production",
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    create_guides: bool = True,
    joint_map: Optional[dict] = None,
) -> PlacementPreview:
    """Preview the selected mesh without creating or replacing rig joints."""
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select a mesh transform first.")
    return preview_biped_joint_placement(
        _as_mesh_transform(selection[0]),
        solver=solver,
        landmark_points=landmark_points,
        template_path=template_path,
        create_guides=create_guides,
        joint_map=joint_map,
    )


def create_auto_joints_for_selected_mesh(
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
    solver: str = "production",
    landmark_points: Optional[Dict[str, Vector3]] = None,
    template_path: str = DEFAULT_PLACEMENT_TEMPLATE,
    template_namespace: str = "",
    require_interior: bool = False,
    joint_map: Optional[dict] = None,
) -> Tuple[dict, dict]:
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select a mesh transform first.")

    mesh = _as_mesh_transform(selection[0])
    return create_auto_joints_for_mesh(
        mesh=mesh,
        orient=orient,
        replace_existing=replace_existing,
        create_guides=create_guides,
        solver=solver,
        landmark_points=landmark_points,
        template_path=template_path,
        template_namespace=template_namespace,
        require_interior=require_interior,
        joint_map=joint_map,
    )
