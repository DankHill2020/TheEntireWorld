import re
import os
import json
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math
from custom_qt import custom_widgets
from maya_tools.Rigging.mocap import setup_hik
from maya_tools.Rigging import enum_attrs

MODULE_STORE_NODE = "rig_module_store"
GLOBAL_RIG_STORE = {}
RIG_BUILD_REVISION = "rig-centered-curve-frame-v15"


def _get_joint(body_joint_map, slot, default=None):

    """
        Gets joint.
    :param body_joint_map: mapping for body joint map
    :param slot: slot
    :param default: default
    :return: result
    """
    if not body_joint_map:
        return default
    val = body_joint_map.get(slot)
    if val is None:
        return default
    if isinstance(val, dict):
        jnt = val.get("joint")
        return jnt if jnt else default
    return val if val else default


def create_diamond_ctrl(name, size=1.0, normal=(0, 1, 0)):
    """
        Creates a diamond-shaped nurbsCurve control.
    :param name: ctrl_name
    :param size: local size mult
    :param normal: relative direction
    :return:
    """

    points = [
        (0, 0, size),
        (size, 0, 0),
        (0, 0, -size),
        (-size, 0, 0),
        (0, 0, size)
    ]

    ctrl = cmds.curve(
        d=1,
        p=points,
        k=list(range(len(points))),
        n=name
    )

    # Rotate if needed
    if normal != (0, 1, 0):
        cmds.xform(ctrl, ro=normal)

    return ctrl


def create_prism_ctrl(name, size=1.0, depth=0.5, normal=(0, 1, 0)):
    """
        Creates a prism-shaped nurbsCurve control.

    :param name: control name
    :param size: horizontal/vertical scale of diamond
    :param depth: prism depth along Y-axis
    :param normal: vector to orient the prism along (default Y-up)
    :return:
    """

    # Top face points (XZ plane at Y = +depth/2)
    top_y = depth / 2
    top_points = [
        (0, top_y, size),
        (size, top_y, 0),
        (0, top_y, -size),
        (-size, top_y, 0),
        (0, top_y, size)
    ]

    # Bottom face points (XZ plane at Y = -depth/2)
    bottom_y = -depth / 2
    bottom_points = [
        (0, bottom_y, size),
        (size, bottom_y, 0),
        (0, bottom_y, -size),
        (-size, bottom_y, 0),
        (0, bottom_y, size)
    ]

    # Side edges connecting top and bottom faces
    side_edges = []
    for i in range(4):  # connect corners
        side_edges.append(top_points[i])
        side_edges.append(bottom_points[i])

    points = top_points + bottom_points + side_edges

    ctrl = cmds.curve(d=1, p=points, n=name)

    # Rotate to align with normal if needed
    if normal != (0, 1, 0):
        cmds.xform(ctrl, ro=normal)

    return ctrl


def create_cube_ctrl(name, size=1.5):
    """
        Wireframe cube control
    :param name: control name
    :param size:  local size mult
    :return:
    """
    s = size * 0.5
    points = [
        [-s, -s, -s], [-s, -s, s], [-s, s, s], [-s, s, -s], [-s, -s, -s],
        [s, -s, -s], [s, -s, s], [s, s, s], [s, s, -s], [s, -s, -s],
        [-s, -s, -s], [-s, s, -s], [s, s, -s], [s, s, s],
        [-s, s, s], [-s, -s, s], [s, -s, s]
    ]
    ctrl = cmds.curve(d=1, p=points, n=name)
    cmds.makeIdentity(ctrl, a=True)

    return ctrl


def snap_ctrl_cvs_to_child(ctrl, child_joint, axis="x", flip_direction=False):
    """
    Snaps control CVs toward the child joint along a local axis.

    :param ctrl: control transform
    :param child_joint: child joint or pad
    :param axis: 'x', 'y', or 'z' (local axis to operate on)
    :param flip_direction: reverse child-facing side
    """

    axis_index = {"x": 0, "y": 1, "z": 2}[axis]

    # Get matrices
    ctrl_mtx = om.MMatrix(cmds.xform(ctrl, q=True, ws=True, m=True))
    ctrl_mtx_inv = ctrl_mtx.inverse()

    child_pos_ws = om.MPoint(*cmds.xform(child_joint, q=True, ws=True, t=True))
    child_pos_ls = child_pos_ws * ctrl_mtx_inv

    target = child_pos_ls[axis_index]

    if abs(target) < 1e-5:
        return

    direction = 1 if target > 0 else -1
    if flip_direction:
        direction *= -1

    # Gather CVs
    shapes = cmds.listRelatives(ctrl, s=True, ni=True) or []
    cvs = []
    for shape in shapes:
        if cmds.nodeType(shape) == "nurbsCurve":
            cvs.extend(cmds.ls(f"{shape}.cv[*]", fl=True))

    if not cvs:
        cmds.warning(f"No CVs found under {ctrl}")
        return

    # Snap CVs
    for cv in cvs:
        pos = cmds.pointPosition(cv, local=True)
        axis_val = pos[axis_index]

        if axis_val * direction > 0:
            delta = target - axis_val
        else:
            delta = -axis_val

        move = [0, 0, 0]
        move[axis_index] = delta

        cmds.xform(cv, relative=True, translation=move)


def create_sphere_ctrl(name, radius=1.5):
    """
    Creates a sphere-like control made of 3 rotated circles with proper shape parenting
    :param name: ctrl name
    :param radius: relative radius of sphere
    :return:
    """
    circle_transforms = []
    circle_shapes = []

    axes = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]

    for i, axis in enumerate(axes):
        c = cmds.circle(
            n=f"{name}_shape{i}_grp",
            ch=True,
            normal=axis,
            radius=radius
        )[0]

        shapes = cmds.listRelatives(c, s=True, f=True)
        circle_shapes.extend(shapes)

        circle_transforms.append(c)

    # create a main parent for the control
    ctrl = cmds.group(em=True, n=name)

    # reparent shapes under main ctrl, delete old transforms
    for shape, old_tr in zip(circle_shapes, circle_transforms):
        cmds.parent(shape, ctrl, r=True, s=True)
        cmds.delete(old_tr)

    cmds.makeIdentity(ctrl, a=True)
    return ctrl


def create_bi_arrow_ctrl(name, size=1.2):
    """
    Two arrows pointing in opposite directions, rotated 90° around X-axis
    :param name: ctrl name
    :param size: relative size mult
    :return:
    """
    # Original arrow points along Z
    arrow = [
        [0, 0, size],
        [size * 0.5, 0, size * 0.5],
        [size * 0.25, 0, size * 0.5],
        [size * 0.25, 0, -size * 0.5],
        [size * 0.5, 0, -size * 0.5],
        [0, 0, -size],
        [-size * 0.5, 0, -size * 0.5],
        [-size * 0.25, 0, -size * 0.5],
        [-size * 0.25, 0, size * 0.5],
        [-size * 0.5, 0, size * 0.5],
        [0, 0, size]
    ]

    rotated_arrow = [[x, z, -y] for x, y, z in arrow]

    # Create the curve
    ctrl = cmds.curve(d=1, p=rotated_arrow, n=name)
    cmds.makeIdentity(ctrl, a=True)
    return ctrl


def setup_show_twist_ctrls(side, limb, twist_joints=None, attr_nice_name="Show Twist Ctrls"):
    """
        Setup show twist ctrls.
    :param side: side
    :param limb: limb
    :param twist_joints: list of twist joints
    :param attr_nice_name: attr nice name
    :return: result
    """
    side = side.lower()
    limb = limb.lower()

    if limb == "leg":
        switch_ctrl = f"{side}_ankle_switch_ctrl"
        fallback_terms = ["knee", "thigh"]
    else:
        switch_ctrl = f"{side}_hand_switch_ctrl"
        fallback_terms = ["upperarm", "lowerarm"]

    if not cmds.objExists(switch_ctrl):
        cmds.error(f"Switch control does not exist: {switch_ctrl}")

    attr_name = "showTwistCtrls"
    full_attr = f"{switch_ctrl}.{attr_name}"

    if not cmds.attributeQuery(attr_name, node=switch_ctrl, exists=True):
        cmds.addAttr(switch_ctrl, ln=attr_name, nn=attr_nice_name, at="bool", dv=0, k=True)
    else:
        cmds.setAttr(full_attr, e=True, keyable=True)

    twist_pads = []

    if twist_joints:
        for jnt in twist_joints:
            base = jnt.split("|")[-1].split(":")[-1]
            for suffix in ["_ctrl_pad", "_main_ctrl_pad"]:
                pad = f"{base}{suffix}"
                if cmds.objExists(pad):
                    twist_pads.append(pad)

    if not twist_pads:
        for term in fallback_terms:
            twist_pads.extend(cmds.ls(f"{side}_{term}*_twist*_ctrl_pad") or [])
            twist_pads.extend(cmds.ls(f"{side}_{term}*_twist*_main_ctrl_pad") or [])

    twist_pads = list(dict.fromkeys(twist_pads))

    for pad in twist_pads:
        vis_attr = f"{pad}.visibility"
        incoming = cmds.listConnections(vis_attr, s=True, d=False, plugs=True) or []

        for src in incoming:
            if src != full_attr:
                try:
                    cmds.disconnectAttr(src, vis_attr)
                except Exception:
                    pass

        if not cmds.isConnected(full_attr, vis_attr):
            cmds.connectAttr(full_attr, vis_attr, force=True)

    return {
        "switch_ctrl": switch_ctrl,
        "attr": full_attr,
        "twist_pads": twist_pads
    }


def _stretch_node_token(node):
    """Return a short Maya-safe token for stretch helper-node names."""
    short_name = node.split("|")[-1].replace(":", "_")
    return re.sub(r"[^A-Za-z0-9_]", "_", short_name)


def _ensure_stretch_attr(control, attr_name="stretch"):
    """Create and return a keyable 0-1 stretch blend on ``control``."""
    if not control or not cmds.objExists(control):
        return None
    plug = f"{control}.{attr_name}"
    if not cmds.attributeQuery(attr_name, node=control, exists=True):
        cmds.addAttr(
            control,
            longName=attr_name,
            niceName="Stretch",
            attributeType="float",
            minValue=0.0,
            maxValue=1.0,
            defaultValue=0.0,
            keyable=True,
        )
    else:
        cmds.setAttr(plug, edit=True, keyable=True)
    return plug


def _joint_segment_axis(joint):
    """Return the dominant local translate axis and its signed rest value."""
    values = cmds.getAttr(f"{joint}.translate")[0]
    axis_index = max(range(3), key=lambda index: abs(values[index]))
    return "XYZ"[axis_index], float(values[axis_index])


def _create_stretch_ratio_network(
        prefix,
        current_distance_attr,
        rest_length,
        stretch_attr,
        scale_reference=None,
        rest_length_attr=None,
):
    """Create a scale-aware stretch/compression ratio and return its output."""
    created_nodes = []
    token = _stretch_node_token(prefix)

    rest_distance_attr = rest_length_attr
    if not rest_distance_attr:
        rest_scaled = cmds.createNode("multiplyDivide", name=f"{token}_stretch_restScale_md")
        created_nodes.append(rest_scaled)
        cmds.setAttr(f"{rest_scaled}.operation", 1)
        cmds.setAttr(f"{rest_scaled}.input1X", max(float(rest_length), 0.0001))

        if scale_reference and cmds.objExists(scale_reference):
            scale_decompose = cmds.createNode("decomposeMatrix", name=f"{token}_stretch_scale_dcm")
            created_nodes.append(scale_decompose)
            _connect_attr_once(
                f"{scale_reference}.worldMatrix[0]",
                f"{scale_decompose}.inputMatrix",
                force=True,
            )
            _connect_attr_once(
                f"{scale_decompose}.outputScaleX",
                f"{rest_scaled}.input2X",
                force=True,
            )
        else:
            cmds.setAttr(f"{rest_scaled}.input2X", 1.0)
        rest_distance_attr = f"{rest_scaled}.outputX"

    ratio = cmds.createNode("multiplyDivide", name=f"{token}_stretch_ratio_md")
    created_nodes.append(ratio)
    cmds.setAttr(f"{ratio}.operation", 2)
    _connect_attr_once(current_distance_attr, f"{ratio}.input1X", force=True)
    _connect_attr_once(rest_distance_attr, f"{ratio}.input2X", force=True)

    blend = cmds.createNode("blendColors", name=f"{token}_stretch_blend")
    created_nodes.append(blend)
    # blendColors computes color1 * blender + color2 * (1 - blender).
    cmds.setAttr(f"{blend}.color2R", 1.0)
    # Feed the measured ratio directly into the enabled side of the blend.
    # Ratios above one extend the chain and ratios below one compress it.
    _connect_attr_once(f"{ratio}.outputX", f"{blend}.color1R", force=True)
    _connect_attr_once(stretch_attr, f"{blend}.blender", force=True)

    return f"{blend}.outputR", created_nodes


def _create_distance_dimension(prefix, start_position, end_position, start_parent=None, end_parent=None):
    """Create a hidden distanceDimension and return all nodes it owns."""
    token = _stretch_node_token(prefix)
    distance_group = _ensure_distance_nodes_group()
    transform = cmds.createNode("transform", name=f"{token}_dim", parent=distance_group)
    shape = cmds.createNode("distanceDimShape", name=f"{token}_dimShape", parent=transform)
    locator_nodes = []
    for role, plug, position, parent in (
        ("start", "startPoint", start_position, start_parent),
        ("end", "endPoint", end_position, end_parent),
    ):
        locator = cmds.spaceLocator(name=f"{token}_{role}_loc")[0]
        cmds.xform(locator, worldSpace=True, translation=position)
        if parent and cmds.objExists(parent):
            cmds.parent(locator, parent, absolute=True)
        else:
            cmds.parent(locator, distance_group, absolute=True)
        locator_shape = (cmds.listRelatives(
            locator,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
        ) or [None])[0]
        if not locator_shape:
            raise RuntimeError(f"Could not create the {role} locator for {shape}.")
        _connect_attr_once(f"{locator_shape}.worldPosition[0]", f"{shape}.{plug}", force=True)
        cmds.setAttr(f"{locator}.visibility", 0)
        locator_nodes.append(locator)

    cmds.setAttr(f"{transform}.visibility", 0)
    return {
        "shape": shape,
        "transform": transform,
        "locators": locator_nodes,
        "nodes": [transform] + locator_nodes,
    }


def _ensure_distance_nodes_group():
    """Return the hidden ``Do_Not_Touch|distance_nodes`` DAG group."""
    dnt_matches = cmds.ls("Do_Not_Touch", type="transform", long=True) or []
    if dnt_matches:
        dnt = dnt_matches[0]
    else:
        dnt = cmds.group(empty=True, name="Do_Not_Touch")

    children = cmds.listRelatives(dnt, children=True, type="transform", fullPath=True) or []
    distance_group = next(
        (child for child in children if child.rsplit("|", 1)[-1] == "distance_nodes"),
        None,
    )
    if distance_group is None:
        distance_group = cmds.group(empty=True, name="distance_nodes", parent=dnt)

    distance_group_long = (cmds.ls(distance_group, long=True) or [distance_group])[0]
    for shape in cmds.ls(type="distanceDimShape", long=True) or []:
        transforms = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not transforms:
            continue
        transform = transforms[0]
        parents = cmds.listRelatives(transform, parent=True, fullPath=True) or []
        if not parents or parents[0] != distance_group_long:
            cmds.parent(transform, distance_group_long, absolute=True)

    cmds.setAttr(f"{dnt}.visibility", 0)
    cmds.setAttr(f"{distance_group_long}.visibility", 0)
    return distance_group_long


def _curve_world_up_vector(curve_shape):
    """Return a stable world-space normal for motion paths on a curve.

    Closed facial loops are especially prone to a single motionPath roll when
    Maya has to infer an up vector. A Newell-style normal computed from the
    curve CVs gives every sample the same reference frame. The fallback also
    deliberately chooses the world axis least parallel to the first tangent.
    """
    selection = om.MSelectionList()
    selection.add(curve_shape)
    curve_path = selection.getDagPath(0)
    curve_fn = om.MFnNurbsCurve(curve_path)
    points = list(curve_fn.cvPositions(om.MSpace.kWorld))

    normal = om.MVector()
    if len(points) > 2:
        center = om.MPoint()
        for point in points:
            center += om.MVector(point)
        center /= float(len(points))
        offsets = [om.MVector(point - center) for point in points]
        for current, following in zip(offsets, offsets[1:] + offsets[:1]):
            normal += current ^ following

    if normal.length() <= 1.0e-8:
        parameter = curve_fn.knotDomain[0]
        tangent = curve_fn.tangent(parameter, om.MSpace.kWorld)
        tangent.normalize()
        candidates = (
            om.MVector(1.0, 0.0, 0.0),
            om.MVector(0.0, 1.0, 0.0),
            om.MVector(0.0, 0.0, 1.0),
        )
        normal = min(candidates, key=lambda axis: abs(tangent * axis))

    normal.normalize()
    return normal.x, normal.y, normal.z


def create_joints_along_curve(curve, joint_count=5, keep_attached=True, name_prefix=None):
    """Create evenly spaced independent joints along a NURBS curve.

    When ``keep_attached`` is true, each joint is placed below a transform
    driven by its own fraction-mode motionPath node. Otherwise the evaluated
    world transforms are baked onto the joints and all helper nodes are
    removed.
    """
    joint_count = int(joint_count)
    if joint_count < 1:
        raise ValueError("Joint count must be at least 1.")

    matches = cmds.ls(curve, long=True) or []
    if not matches:
        raise ValueError(f"Curve does not exist: {curve}")
    curve_node = matches[0]
    if cmds.nodeType(curve_node) == "nurbsCurve":
        curve_shape = curve_node
        curve_transform = (cmds.listRelatives(curve_shape, parent=True, fullPath=True) or [None])[0]
    else:
        curve_transform = curve_node
        curve_shapes = cmds.listRelatives(
            curve_transform,
            shapes=True,
            noIntermediate=True,
            type="nurbsCurve",
            fullPath=True,
        ) or []
        curve_shape = curve_shapes[0] if curve_shapes else None
    if not curve_shape or not curve_transform:
        raise ValueError(f"Selected object is not a NURBS curve: {curve}")

    leaf = curve_transform.rsplit("|", 1)[-1].split(":")[-1]
    prefix = _stretch_node_token(name_prefix or leaf.removesuffix("_crv") or "curve")
    form = int(cmds.getAttr(f"{curve_shape}.form"))
    closed = form in (1, 2)
    denominator = joint_count if closed else max(1, joint_count - 1)
    fractions = [index / float(denominator) for index in range(joint_count)]
    world_up = _curve_world_up_vector(curve_shape)

    root_group = cmds.group(empty=True, name=f"{prefix}_path_joints_grp")
    joints = []
    pads = []
    motion_paths = []
    for index, fraction in enumerate(fractions, start=1):
        pad = cmds.group(empty=True, name=f"{prefix}_path_{index:02d}_pad", parent=root_group)
        cmds.select(clear=True)
        joint = cmds.joint(name=f"{prefix}_path_{index:02d}_jnt")
        joint = cmds.parent(joint, pad, relative=True)[0]

        motion_path = cmds.createNode("motionPath", name=f"{prefix}_path_{index:02d}_mp")
        cmds.setAttr(f"{motion_path}.fractionMode", True)
        cmds.setAttr(f"{motion_path}.uValue", fraction)
        cmds.setAttr(f"{motion_path}.follow", True)
        # Maya joint controls use local Y as their forward/length axis. Give
        # every path sample one explicit curve-plane up reference so a closed
        # loop cannot roll one control onto local Z at its frame seam.
        cmds.setAttr(f"{motion_path}.frontAxis", 1)
        cmds.setAttr(f"{motion_path}.upAxis", 2)
        cmds.setAttr(f"{motion_path}.worldUpType", 3)
        cmds.setAttr(f"{motion_path}.worldUpVector", *world_up, type="double3")
        _connect_attr_once(f"{curve_shape}.worldSpace[0]", f"{motion_path}.geometryPath", force=True)
        _connect_attr_once(f"{motion_path}.allCoordinates", f"{pad}.translate", force=True)
        _connect_attr_once(f"{motion_path}.rotate", f"{pad}.rotate", force=True)

        joints.append(joint)
        pads.append(pad)
        motion_paths.append(motion_path)

    if not keep_attached:
        matrices = [cmds.xform(joint, query=True, worldSpace=True, matrix=True) for joint in joints]
        baked_joints = []
        for joint, matrix in zip(joints, matrices):
            joint = cmds.parent(joint, world=True, absolute=True)[0]
            cmds.xform(joint, worldSpace=True, matrix=matrix)
            baked_joints.append(joint)
        cmds.delete(motion_paths)
        cmds.delete(root_group)
        joints = baked_joints
        pads = []
        motion_paths = []
        root_group = None

    cmds.select(joints, replace=True)
    return {
        "curve": curve_transform,
        "joints": joints,
        "pads": pads,
        "motion_paths": motion_paths,
        "group": root_group,
        "keep_attached": bool(keep_attached),
        "closed": closed,
        "parameters": fractions,
    }


def setup_spine_segment_stretch(spine_joints, control_data, pelvis_ctrl, scale_reference=None):
    """Add per-bone distance stretch without replacing the existing FK spine."""
    if len(spine_joints) < 3 or len(control_data) != len(spine_joints):
        return {"enabled": False, "reason": "requires at least three spine joints", "nodes": []}
    if not pelvis_ctrl or not cmds.objExists(pelvis_ctrl):
        return {"enabled": False, "reason": "pelvis control is unavailable", "nodes": []}

    for parent_joint, child_joint in zip(spine_joints[:-1], spine_joints[1:]):
        parents = cmds.listRelatives(child_joint, parent=True, type="joint", fullPath=True) or []
        expected = cmds.ls(parent_joint, long=True) or [parent_joint]
        if not parents or parents[0] != expected[0]:
            return {"enabled": False, "reason": "spine joints are not contiguous", "nodes": []}

    stretch_attr = _ensure_stretch_attr(pelvis_ctrl)
    controls = [row["ctrl"] for row in control_data]
    constraint_drivers = [row.get("sub_ctrl") or row["ctrl"] for row in control_data]
    created_nodes = []

    for index, (joint, child_joint) in enumerate(zip(spine_joints[:-1], spine_joints[1:]), start=1):
        prefix = f"{_stretch_node_token(joint)}_segment{index}"
        start_position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
        end_position = cmds.xform(child_joint, query=True, worldSpace=True, translation=True)
        rest_dimension = _create_distance_dimension(
            f"{prefix}_rest",
            start_position,
            end_position,
            start_parent=scale_reference,
            end_parent=scale_reference,
        )
        current_dimension = _create_distance_dimension(
            f"{prefix}_current",
            start_position,
            end_position,
            start_parent=controls[index - 1],
            end_parent=controls[index],
        )
        ratio_attr, ratio_nodes = _create_stretch_ratio_network(
            prefix,
            f"{current_dimension['shape']}.distance",
            1.0,
            stretch_attr,
            rest_length_attr=f"{rest_dimension['shape']}.distance",
        )

        driver_parent = constraint_drivers[index - 1]
        scale_driver = cmds.createNode(
            "transform",
            name=f"{prefix}_stretch_scale_driver",
            parent=driver_parent,
        )
        cmds.setAttr(f"{scale_driver}.translate", 0.0, 0.0, 0.0, type="double3")
        cmds.setAttr(f"{scale_driver}.rotate", 0.0, 0.0, 0.0, type="double3")
        cmds.setAttr(f"{scale_driver}.scale", 1.0, 1.0, 1.0, type="double3")
        cmds.setAttr(f"{scale_driver}.visibility", 0)
        axis, _rest_translate = _joint_segment_axis(child_joint)
        _connect_attr_once(ratio_attr, f"{scale_driver}.scale{axis}", force=True)

        constraints = cmds.listConnections(
            joint,
            source=True,
            destination=False,
            type="scaleConstraint",
        ) or []
        constraints = list(dict.fromkeys(constraints))
        if constraints:
            constraint = constraints[0]
            cmds.scaleConstraint(scale_driver, joint, edit=True, weight=0.0)
        else:
            constraint = cmds.scaleConstraint(
                driver_parent,
                scale_driver,
                joint,
                maintainOffset=False,
                name=f"{prefix}_stretch_scaleConstraint",
            )[0]

        weights = cmds.scaleConstraint(constraint, query=True, weightAliasList=True) or []
        targets = cmds.scaleConstraint(constraint, query=True, targetList=True) or []
        fk_weight = cmds.createNode("reverse", name=f"{prefix}_stretch_fkWeight_rev")
        _connect_attr_once(stretch_attr, f"{fk_weight}.inputX", force=True)
        driver_long = (cmds.ls(scale_driver, long=True) or [scale_driver])[0]
        for target, weight in zip(targets, weights):
            target_long = (cmds.ls(target, long=True) or [target])[0]
            weight_source = stretch_attr if target_long == driver_long else f"{fk_weight}.outputX"
            _connect_attr_once(weight_source, f"{constraint}.{weight}", force=True)

        created_nodes.extend(rest_dimension["nodes"])
        created_nodes.extend(current_dimension["nodes"])
        created_nodes.extend(ratio_nodes)
        created_nodes.extend([scale_driver, fk_weight])

    return {
        "enabled": True,
        "attr": stretch_attr,
        "nodes": created_nodes,
    }


def _drive_stretch_segments(prefix, segment_joints, ratio_attr):
    """Drive signed local joint translations from a shared stretch ratio."""
    created_nodes = []
    token = _stretch_node_token(prefix)
    for index, joint in enumerate(segment_joints, start=1):
        axis, rest_translate = _joint_segment_axis(joint)
        if abs(rest_translate) < 0.0001:
            continue
        multiplier = cmds.createNode(
            "multDoubleLinear",
            name=f"{token}_stretch_segment{index}_mdl",
        )
        created_nodes.append(multiplier)
        cmds.setAttr(f"{multiplier}.input1", rest_translate)
        _connect_attr_once(ratio_attr, f"{multiplier}.input2", force=True)
        _connect_attr_once(
            f"{multiplier}.output",
            f"{joint}.translate{axis}",
            force=True,
        )
    return created_nodes


def setup_ik_limb_stretch(ik_joints, ik_ctrl, switch_ctrl, scale_reference=None):
    """Add a 0-1 stretch/compression blend to a two-bone IK chain."""
    if len(ik_joints) < 3 or not all(cmds.objExists(node) for node in ik_joints[:3]):
        return {"enabled": False, "nodes": []}

    stretch_attr = _ensure_stretch_attr(switch_ctrl)
    if not stretch_attr:
        return {"enabled": False, "nodes": []}

    prefix = _stretch_node_token(ik_joints[0]).replace("_ik", "")
    positions = [
        cmds.xform(joint, query=True, worldSpace=True, translation=True)
        for joint in ik_joints[:3]
    ]
    upper_dimension = _create_distance_dimension(
        f"{prefix}_upper_rest",
        positions[0],
        positions[1],
        start_parent=scale_reference,
        end_parent=scale_reference,
    )
    lower_dimension = _create_distance_dimension(
        f"{prefix}_lower_rest",
        positions[1],
        positions[2],
        start_parent=scale_reference,
        end_parent=scale_reference,
    )
    reach_dimension = _create_distance_dimension(
        f"{prefix}_reach",
        positions[0],
        positions[2],
        # Never parent the measurement anchor below the IK chain it drives.
        # Doing so creates feedback through the IK solve:
        # ratio -> segment translate -> IK solve -> root matrix -> distance.
        start_parent=scale_reference,
        end_parent=ik_ctrl,
    )
    rest_sum = cmds.createNode("plusMinusAverage", name=f"{prefix}_stretch_restLength_pma")
    cmds.setAttr(f"{rest_sum}.operation", 1)
    _connect_attr_once(f"{upper_dimension['shape']}.distance", f"{rest_sum}.input1D[0]", force=True)
    _connect_attr_once(f"{lower_dimension['shape']}.distance", f"{rest_sum}.input1D[1]", force=True)

    rest_length = sum(abs(_joint_segment_axis(joint)[1]) for joint in ik_joints[1:3])
    ratio_attr, ratio_nodes = _create_stretch_ratio_network(
        prefix,
        f"{reach_dimension['shape']}.distance",
        rest_length,
        stretch_attr,
        rest_length_attr=f"{rest_sum}.output1D",
    )
    segment_nodes = _drive_stretch_segments(prefix, ik_joints[1:3], ratio_attr)
    dimension_nodes = (
        upper_dimension["nodes"]
        + lower_dimension["nodes"]
        + reach_dimension["nodes"]
    )
    return {
        "enabled": True,
        "attr": stretch_attr,
        "dimensions": [upper_dimension, lower_dimension, reach_dimension],
        "nodes": dimension_nodes + [rest_sum] + ratio_nodes + segment_nodes,
    }


def create_ik_fk_limb(sel, root_parent):
    """
        Creates an IK/FK limb from either:
      - 3 joints (arm)
      - 4+ joints (leg with extra joints)

    Behavior is determined purely by joint count.
    :param sel: list of joints in the limb chain (top -> mid -> end -> optional extras)
    :param root_parent: transform to parent FK controls / IK controls under
    :return: {
        "fk_chain": fk_joints,
        "ik_chain": ik_joints,
        "driver_chain": driver_joints,
        "fk_controls": fk_ctrls,
        "ik_ctrl": ik_ctrl,
        "pv_ctrl": pv_ctrl,
        "ik_handle": ik_handle,
        "blend_constraints": blend_constraints
    }
    """

    joint_count = len(sel)
    ik_end_index = 2

    top_joint = sel[0]
    mid_joint = sel[1]
    end_joint = sel[ik_end_index]

    def duplicate_exact_chain(source_chain, suffix):
        """Duplicate only the requested limb path, excluding twist branches."""
        target_names = []
        for source in source_chain:
            base = source.split("|")[-1].split(":")[-1].replace("_jnt", "")
            base = re.sub(r"_(fk|ik|driver)$", "", base)
            target_names.append(f"{base}_{suffix}")
        if len(set(target_names)) != len(target_names):
            raise ValueError(
                f"{suffix.upper()} limb chain produces duplicate joint names: {target_names}. "
                "Check the mapped limb path and twist branches."
            )

        for target_name in target_names:
            existing = cmds.ls(target_name, long=True, type="joint") or []
            if existing:
                cmds.delete(existing)

        duplicated = []
        previous = None
        for source, target_name in zip(source_chain, target_names):
            duplicate = cmds.duplicate(source, parentOnly=True, name=target_name)[0]
            parent_target = previous or root_parent
            if parent_target and cmds.objExists(parent_target):
                duplicate = cmds.parent(duplicate, parent_target, absolute=True)[0]
            duplicate_matches = cmds.ls(duplicate, long=True, type="joint") or []
            if len(duplicate_matches) != 1:
                raise RuntimeError(
                    f"Could not uniquely resolve duplicated {suffix.upper()} joint {target_name}: "
                    f"{duplicate_matches}"
                )
            previous = duplicate_matches[0]
            duplicated.append(previous.rsplit("|", 1)[-1])
        return duplicated

    fk_joints = duplicate_exact_chain(sel, "fk")
    ik_joints = duplicate_exact_chain(sel, "ik")
    driver_joints = duplicate_exact_chain(sel, "driver")

    for chain_name, chain in (
        ("FK", fk_joints),
        ("IK", ik_joints),
        ("Driver", driver_joints),
    ):
        if len(chain) != joint_count:
            raise RuntimeError(
                "\n".join([
                    f"{chain_name} chain duplication failed.",
                    f"Expected {joint_count} joints but duplicated {len(chain)}.",
                    f"Input chain: {sel}",
                    f"Duplicated chain: {chain}",
                    "Verify the source limb is a contiguous joint hierarchy "
                    "(UpperArm -> LowerArm -> Hand) with no transform nodes inserted."
                ])
            )
    for jnt in fk_joints + ik_joints + driver_joints:
        if cmds.objExists(jnt) and cmds.nodeType(jnt) == "joint":
            cmds.setAttr(f"{jnt}.drawStyle", 2)

    fk_ctrls = create_joint_controls(fk_joints, control_shape="cube", root_parent=root_parent)
    for i, jnt in enumerate(fk_joints):
        if joint_count > 3:
            if jnt != fk_joints[-1]:
                snap_ctrl_cvs_to_child(fk_ctrls[i]["ctrl"], fk_ctrls[i + 1]["pad"], flip_direction=False)
            else:
                cmds.delete(fk_ctrls[i]["pad"])
        else:
            if jnt != fk_joints[-1]:
                snap_ctrl_cvs_to_child(fk_ctrls[i]["ctrl"], fk_ctrls[i + 1]["pad"], flip_direction=True)
            else:
                scale_ctrl_cvs_local(fk_ctrls[i]["ctrl"], [1, 2.5, 2.5])

    temp_grp = cmds.group(name=f"{end_joint.replace('_jnt', '')}_ik", em=True)

    # Create the IK control using your joint control system
    ik_ctrl_dict = create_joint_controls(
        [temp_grp],
        control_shape="cube",
        root_parent="origin_ctrl",
        sub_ctrls=False,
        keep_constraint=True
    )[0]

    cmds.delete(temp_grp)

    # Snap the pad to the IK joint
    cmds.delete(cmds.pointConstraint(ik_joints[ik_end_index], ik_ctrl_dict["pad"]))

    # Access control and pad if needed
    ik_ctrl = ik_ctrl_dict["ctrl"]
    scale_ctrl_to_region(ik_ctrl, ik_joints)
    temp_grp = cmds.group(name=f"{mid_joint.replace('_jnt', '')}_pv", em=True)

    # Create the control using your joint control system
    pv_ctrl_dict = create_joint_controls(
        [temp_grp],
        control_shape="sphere",
        root_parent=root_parent,
        sub_ctrls=False,
        keep_constraint=True
    )[0]

    # Delete the temporary group
    cmds.delete(temp_grp)

    # Snap the pad to the mid_joint just in case
    cmds.delete(cmds.pointConstraint(mid_joint, pv_ctrl_dict["pad"]))
    apply_side_color_override(pv_ctrl_dict["pad"])

    # Access control and pad if needed
    pv_ctrl = pv_ctrl_dict["ctrl"]
    pv_pad = pv_ctrl_dict["pad"]

    ik_handle, eff = cmds.ikHandle(
        n=f"{top_joint.replace('_jnt', '')}_ikh",
        sj=ik_joints[0],
        ee=ik_joints[ik_end_index],
        sol="ikRPsolver"
    )
    cmds.parent(ik_handle, ik_ctrl)
    cmds.poleVectorConstraint(pv_ctrl, ik_handle)

    # Maya persists the global IK solver toggle between scenes and sessions.
    # A perfectly connected rig appears inert when that toggle (or the
    # handle-level blend) is off, so a rig build must establish both states.
    try:
        cmds.ikSystem(edit=True, solve=True)
    except Exception:
        pass
    if cmds.attributeQuery("ikBlend", node=ik_handle, exists=True):
        cmds.setAttr(f"{ik_handle}.ikBlend", 1.0)

    handle_parent = (cmds.listRelatives(ik_handle, parent=True, fullPath=False) or [None])[0]
    handle_parent_short = str(handle_parent or "").split("|")[-1].split(":")[-1]
    ik_ctrl_short = str(ik_ctrl or "").split("|")[-1].split(":")[-1]
    if handle_parent_short != ik_ctrl_short:
        ik_handle = cmds.parent(ik_handle, ik_ctrl)[0]

    # Pole Vector placement
    mid_pos = cmds.xform(fk_joints[1], q=True, ws=True, t=True)
    is_leg = (joint_count >= 4)
    pv_offset = 40 if is_leg else -40
    cmds.xform(pv_pad, ws=True, t=[mid_pos[0], mid_pos[1], mid_pos[2]])
    cmds.move(0, 0, pv_offset, pv_pad, r=True, ws=True)

    wrist_con = cmds.orientConstraint(ik_ctrl, ik_joints[ik_end_index], mo=True)
    if len(ik_joints) > 3:
        cmds.delete(wrist_con)

    blend_constraints = []
    blend_scale_constraints = []

    for i in range(joint_count):
        orient_con = cmds.orientConstraint(
            fk_joints[i],
            ik_joints[i],
            driver_joints[i],
            mo=False,
            n=f"{driver_joints[i]}_orientConstraint"
        )[0]

        cmds.setAttr(f"{orient_con}.interpType", 2)

        scale_con = cmds.scaleConstraint(
            fk_joints[i],
            ik_joints[i],
            driver_joints[i],
            mo=False,
            n=f"{driver_joints[i]}_scaleConstraint"
        )[0]

        blend_constraints.append(orient_con)
        blend_scale_constraints.append(scale_con)

    for i in range(joint_count):
        cmds.parentConstraint(driver_joints[i], sel[i], mo=False)
        cmds.scaleConstraint(driver_joints[i], sel[i], mo=False)
    hand_joint = driver_joints[ik_end_index].replace('_driver', '')

    switch_ctrl_name = f"{hand_joint}_switch_ctrl"

    if not cmds.objExists(switch_ctrl_name):
        temp_grp = cmds.group(name=f"{hand_joint}_switch", em=True)

        ikfk_ctrl = create_joint_controls(
            [temp_grp],
            control_shape="prism",
            root_parent=driver_joints[ik_end_index]
        )[0]
        switch_ctrl_name = ikfk_ctrl["ctrl"]
        apply_side_color_override(switch_ctrl_name)

        cmds.delete(temp_grp)

        cmds.delete(cmds.pointConstraint(driver_joints[ik_end_index], ikfk_ctrl["pad"]))
        side = fk_joints[0][0]
        if len(fk_joints) > 3:
            offset = -15 if side == "r" else 15
            cmds.move(offset, 0, 0, ikfk_ctrl["pad"], r=True)
        else:
            cmds.move(0, 0, -15, ikfk_ctrl["pad"], r=True)

    # add float attribute for blending
    if not cmds.attributeQuery("ikFkBlend", node=switch_ctrl_name, exists=True):
        cmds.addAttr(switch_ctrl_name, longName="ikFkBlend", attributeType="float", min=0, max=1, dv=1.0)
        cmds.setAttr(f"{switch_ctrl_name}.ikFkBlend", e=True, keyable=True)
    cmds.setAttr(f"{switch_ctrl_name}.ikFkBlend", 1.0)

    # connect to all orient constraints
    for con in blend_constraints:
        weights = cmds.orientConstraint(con, q=True, weightAliasList=True)
        if weights and len(weights) >= 2:
            rev_node = cmds.createNode("reverse", n=f"{con}_rev")
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{rev_node}.inputX")
            cmds.connectAttr(f"{rev_node}.outputX", f"{con}.{weights[0]}", force=True)
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{con}.{weights[1]}", force=True)

    for con in blend_scale_constraints:
        weights = cmds.scaleConstraint(con, q=True, weightAliasList=True)
        if weights and len(weights) >= 2:
            rev_node = cmds.createNode("reverse", n=f"{con}_rev")
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{rev_node}.inputX")
            cmds.connectAttr(f"{rev_node}.outputX", f"{con}.{weights[0]}", force=True)
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{con}.{weights[1]}", force=True)

    for ctrl_pad in [ik_ctrl_dict["pad"], pv_ctrl_dict["pad"]]:
        cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{ctrl_pad}.visibility")

    fk_ctrl_dict = fk_ctrls[0]
    fk_rev = cmds.createNode("reverse", n=f"{fk_ctrl_dict['ctrl']}_vis_rev")
    cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{fk_rev}.inputX")
    cmds.connectAttr(f"{fk_rev}.outputX", f"{fk_ctrl_dict['pad']}.visibility")

    stretch_data = setup_ik_limb_stretch(
        ik_joints,
        ik_ctrl,
        switch_ctrl_name,
        scale_reference=root_parent,
    )

    print("IK/FK limb created (joint-count driven).")

    return {
        "fk_chain": fk_joints,
        "ik_chain": ik_joints,
        "driver_chain": driver_joints,
        "fk_controls": fk_ctrls,
        "ik_ctrl": ik_ctrl,
        "pv_ctrl": pv_ctrl,
        "ik_handle": ik_handle,
        "blend_constraints": blend_constraints,
        "switch_ctrl": switch_ctrl_name,
        "stretch": stretch_data,
    }


def get_nose_joints(face_joint_map=None):
    """
        Gets nose joints.
    :param face_joint_map: mapping for face joint map
    :return: result
    """
    nose_root = None

    if face_joint_map:
        nose_root = face_joint_map.get("NoseRoot", {}).get("joint")

    if not nose_root:
        nose_root = "nose_root"

    if not nose_root or not cmds.objExists(nose_root):
        return []

    nose_joints = [nose_root]

    children = cmds.listRelatives(
        nose_root,
        ad=True,
        type="joint",
        fullPath=False
    ) or []

    children.reverse()  # Maya returns deepest-first; restore parent-to-child-ish order

    for child in children:
        if child and cmds.objExists(child):
            nose_joints.append(child)

    return list(dict.fromkeys(nose_joints))


def set_sdk(driver, driven_attr, keys):
    """
        set driven key function
    :param driver: 'ctrl.attr'
    :param driven_attr: 'node.attr'
    :param keys: list of tuples [(driver_value, driven_value)]
    :return:
    """
    for d_val, v_val in keys:
        cmds.setAttr(driver, d_val)
        cmds.setAttr(driven_attr, v_val)
        cmds.setDrivenKeyframe(
            driven_attr,
            cd=driver
        )


def _connect_attr_once(source_attr, dest_attr, force=False):
    """
        Connect source_attr to dest_attr only when that exact connection is missing.
    :param source_attr: source attr
    :param dest_attr: dest attr
    :param force: force
    :return: result
    """
    if cmds.isConnected(source_attr, dest_attr):
        return False
    if force:
        incoming = cmds.listConnections(dest_attr, source=True, destination=False, plugs=True) or []
        for src in incoming:
            if src != source_attr:
                try:
                    cmds.disconnectAttr(src, dest_attr)
                except Exception:
                    pass
    cmds.connectAttr(source_attr, dest_attr, force=force)
    return True


def _clear_sdk_anim_curves(driven_attrs):
    """
        Clear sdk anim curves.
    :param driven_attrs: list of driven attrs
    :return:
    """
    for driven_attr in driven_attrs:
        if not cmds.objExists(driven_attr):
            continue
        incoming = cmds.listConnections(driven_attr, source=True, destination=False, type="animCurve") or []
        for curve in incoming:
            if cmds.objExists(curve):
                cmds.delete(curve)


def ensure_rfl_attrs(ik_leg_ctrl):
    """
        Ensures the reverse foot setup attributes exist on the IK leg control.
    :param ik_leg_ctrl: name of the IK leg control node
    :return: None
    """
    # float driver attrs
    float_attrs = {
        "footRoll": (-1, 1, 0),
        "footBank": (-1, 1, 0),
        "toeSwivel": (-1, 1, 0),
    }

    for attr, (mn, mx, dv) in float_attrs.items():
        if not cmds.attributeQuery(attr, node=ik_leg_ctrl, exists=True):
            cmds.addAttr(
                ik_leg_ctrl,
                ln=attr,
                at="double",
                min=mn,
                max=mx,
                dv=dv,
                k=True
            )

    # bool attr
    if not cmds.attributeQuery("showRFLCtrls", node=ik_leg_ctrl, exists=True):
        cmds.addAttr(
            ik_leg_ctrl,
            ln="showRFLCtrls",
            at="bool",
            dv=False,
            k=True
        )


def setup_rfl_sdks(ik_leg_ctrl, rfl_joints):
    """
    Connect the reverse-foot attributes to the RFL control SDK groups.

    RFL joints may be resolved as long DAG paths, but generated controls use
    short names. Always strip the joint path before constructing control names.
    :param ik_leg_ctrl: ik leg ctrl
    :param rfl_joints: list of rfl joints
    """

    def sdk_from_joint(joint):
        """
            Sdk from joint.
        :param joint: joint
        :return: result
        """
        return f"{_short_node_name(joint)}_ctrl_sdk_pad"

    def pad_from_joint(joint):
        """
            Pad from joint.
        :param joint: joint
        :return: result
        """
        return f"{_short_node_name(joint)}_ctrl_pad"

    heel_sdk = sdk_from_joint(rfl_joints["heel"])
    toe_sdk = sdk_from_joint(rfl_joints["toe"])
    toe_tip_sdk = sdk_from_joint(rfl_joints["toeTip"])
    inner_bank_sdk = sdk_from_joint(rfl_joints["innerBank"])
    outer_bank_sdk = sdk_from_joint(rfl_joints["outerBank"])

    foot_roll = f"{ik_leg_ctrl}.footRoll"
    _clear_sdk_anim_curves([
        f"{heel_sdk}.rotateX",
        f"{toe_sdk}.rotateZ",
        f"{toe_tip_sdk}.rotateZ",
        f"{inner_bank_sdk}.rotateZ",
        f"{outer_bank_sdk}.rotateZ",
        f"{toe_tip_sdk}.rotateY",
    ])

    set_sdk(foot_roll, f"{heel_sdk}.rotateX", [(0, 0)])
    set_sdk(foot_roll, f"{toe_sdk}.rotateZ", [(0, 0)])
    set_sdk(foot_roll, f"{toe_tip_sdk}.rotateZ", [(0, 0)])

    set_sdk(foot_roll, f"{heel_sdk}.rotateX", [(-1, -45)])
    set_sdk(foot_roll, f"{toe_sdk}.rotateZ", [(0.3, 20)])
    set_sdk(foot_roll, f"{toe_tip_sdk}.rotateZ", [(1, 45)])
    set_sdk(foot_roll, f"{toe_sdk}.rotateZ", [(1, 0)])

    foot_bank = f"{ik_leg_ctrl}.footBank"
    set_sdk(foot_bank, f"{inner_bank_sdk}.rotateZ", [(0, 0)])
    set_sdk(foot_bank, f"{outer_bank_sdk}.rotateZ", [(0, 0)])
    set_sdk(foot_bank, f"{outer_bank_sdk}.rotateZ", [(-1, -45)])
    set_sdk(foot_bank, f"{inner_bank_sdk}.rotateZ", [(1, 45)])

    toe_swivel = f"{ik_leg_ctrl}.toeSwivel"
    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(0, 0)])
    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(-1, -45)])
    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(1, 45)])

    cmds.setAttr(foot_roll, 0)
    cmds.setAttr(foot_bank, 0)
    cmds.setAttr(toe_swivel, 0)

    show_rfl_ctrls = f"{ik_leg_ctrl}.showRFLCtrls"
    heel_pad = pad_from_joint(rfl_joints["heel"])
    _connect_attr_once(show_rfl_ctrls, f"{heel_pad}.visibility", force=True)


def build_rfl_ik_and_constraints(
        side,
        ik_leg_ctrl,
        ik_leg_joints,
        rfl_joints
):
    """
        creates full reverse foot setup from existing joints
    :param side: l or r
    :param ik_leg_ctrl: actual leg ik ctrl
    :param ik_leg_joints: list of ['ankle', 'toe', 'toeTip'] joints
    :param rfl_joints: list of ['heel', 'outerBank', 'innerBank', 'toe', 'toeTip', 'ankle'] joints
    :return:
    """

    dnt = "Do_Not_Touch"
    if not cmds.objExists(dnt):
        dnt = cmds.group(em=True, name=dnt)
    cmds.setAttr(dnt + ".visibility", 0)

    create_joint_controls(
        joint_list=rfl_joints,
        control_shape="sphere",
        root_parent=ik_leg_ctrl,
        sub_ctrls=False
    )

    ankle_ik, _ = cmds.ikHandle(
        sj=ik_leg_joints[0],
        ee=ik_leg_joints[1],
        sol="ikSCsolver",
        name=f"{side}_ankle_toe_ik"
    )
    print(ik_leg_joints)
    toe_ik, _ = cmds.ikHandle(
        sj=ik_leg_joints[1],
        ee=ik_leg_joints[2],
        sol="ikSCsolver",
        name=f"{side}_toe_toeTip_ik"
    )

    for ikh in (ankle_ik, toe_ik):
        cmds.setAttr(f"{ikh}.visibility", 0)
        cmds.parent(ikh, dnt)

    main_leg_ik = None

    children = cmds.listRelatives(ik_leg_ctrl, children=True, type="ikHandle") or []
    if children:
        main_leg_ik = children[0]

    pcs = cmds.listConnections(main_leg_ik, type="parentConstraint") or []
    for pc in pcs:
        cmds.delete(pc)

    if not main_leg_ik:
        cmds.warning(f"[RFL] Could not find main leg IK handle under {ik_leg_ctrl}")

    cmds.parentConstraint(rfl_joints[-1], main_leg_ik, mo=True)
    cmds.parentConstraint(rfl_joints[4], ankle_ik, mo=True)
    cmds.parentConstraint(rfl_joints[3], toe_ik, mo=True)

    cmds.parent(rfl_joints[0], ik_leg_ctrl)

    ensure_rfl_attrs(ik_leg_ctrl)

    rfl_joints_dict = {
        "heel": rfl_joints[0],
        "outerBank": rfl_joints[1],
        "innerBank": rfl_joints[2],
        "toeTip": rfl_joints[3],
        "toe": rfl_joints[4],  # Supports either *_toe_RFL or legacy *_ball_RFL.
        "ankle": rfl_joints[5],
    }

    setup_rfl_sdks(ik_leg_ctrl, rfl_joints_dict)


def find_ik_handle_constrained_by_ctrl(ctrl):
    """
        Finds the IK handle currently constrained by the given control.

    :param ctrl: actual ik ctrl
    :return: Returns the ikHandle or None.
    """

    constraints = cmds.listConnections(ctrl, type="parentConstraint") or []
    for c in constraints:
        driven = cmds.listConnections(c, d=True, s=False) or []
        for node in driven:
            if cmds.nodeType(node) == "ikHandle":
                return node
    return None


def snap_to_joint_matrix(jnt, node):
    """
        snaps node to the joint using world matrix
    :param jnt: joint to snap to
    :param node: node to snap
    :return:
    """
    m = cmds.xform(jnt, q=True, ws=True, m=True)
    cmds.xform(node, ws=True, m=m)


def orient_control_pad_to_world_safely(ctrl, jnt):
    """
    Safely orients the control's pad to world coordinate space without moving the joint,
    unparenting children first, resetting world rotation on the pad, recreating parent/scale
    constraints, and then reparenting the children back under the control.
    :param ctrl: ctrl
    :param jnt: jnt
    """
    if not cmds.objExists(ctrl) or not cmds.objExists(jnt):
        return

    pad = ctrl + "_pad"
    if not cmds.objExists(pad):
        parents = cmds.listRelatives(ctrl, p=True)
        pad = parents[0] if parents else None

    if not pad or not cmds.objExists(pad):
        return

    # 1. Store and unparent any children of the control to avoid moving them
    children = cmds.listRelatives(ctrl, children=True, type="transform") or []
    # Only keep DAG nodes that are not shapes
    children = [c for c in children if not cmds.objectType(c, isType="shape")]
    for c in children:
        cmds.parent(c, w=True)

    # 2. Store and delete any existing parent/scale constraints driving the joint from the control
    constraints = []
    con_nodes = cmds.listConnections(jnt, type="constraint") or []
    for con in con_nodes:
        targets = []
        if cmds.nodeType(con) == "parentConstraint":
            targets = cmds.parentConstraint(con, q=True, targetList=True) or []
        elif cmds.nodeType(con) == "scaleConstraint":
            targets = cmds.scaleConstraint(con, q=True, targetList=True) or []
        if ctrl in targets:
            constraints.append((cmds.nodeType(con), con))

    for c_type, con in constraints:
        if cmds.objExists(con):
            cmds.delete(con)

    # 3. Keep joint position but reset world rotation of the pad to world aligned
    pos = cmds.xform(jnt, q=True, ws=True, t=True)
    cmds.xform(pad, ws=True, ro=[0, 0, 0])
    cmds.xform(pad, ws=True, t=pos)

    # 4. Recreate parent and scale constraints from control to joint with maintainOffset=True
    cmds.parentConstraint(ctrl, jnt, mo=True)
    cmds.scaleConstraint(ctrl, jnt, mo=True)

    # 5. Reparent children back under the control
    for c in children:
        cmds.parent(c, ctrl)

    # 6. Rotate the control transform and freeze rotation to bake it into the shape CVs
    try:
        cmds.xform(ctrl, r=True, ro=[0, 0, 90])
        cmds.makeIdentity(ctrl, apply=True, t=False, r=True, s=False)
    except Exception as e:
        print(f"[Warning] Failed to freeze rotation on {ctrl}: {e}")


def apply_side_color_override(node):
    """
    Auto-detect side from name and apply viewport override color to the SHAPE.
    l_ -> blue (6)
    r_ -> red (13)
    center -> yellow (17)
    :param node: ctrl to edit
    :return:
    """

    name = node.lower()

    if name.startswith("l_"):
        color = 6
    elif name.startswith("r_"):
        color = 13
    else:
        color = 17

    # Get shapes (works for transforms, joints, surfaces, controls)
    shapes = cmds.listRelatives(node, s=True, ni=True, f=True) or []
    for shape in shapes:
        cmds.setAttr(shape + ".overrideEnabled", 1)
        cmds.setAttr(shape + ".overrideColor", color)
        cmds.setAttr(shape + ".alwaysDrawOnTop", 1)


def create_joint_controls(
        joint_list=None,
        control_shape="sphere",
        root_parent=None,
        sub_ctrls=False,
        keep_constraint=True
):
    """
        Creates a control hierarchy for the joints
    :param joint_list: list of joints to create , accepts hierarchy or single item list
    :param control_shape: shape type, can be circle, diamond, prism, arrow, cube or sphere
    :param root_parent: what to parent hierarchy to
    :param sub_ctrls: do you want local sub controls
    :param keep_constraint: do you want to keep connected to the joint or just snapped to
    :return: each ctrl gets added to a list of results, which then has a dict for each joint in the list
        results.append({
            "joint": jnt,
            "ctrl": ctrl,
            "sdk": sdk,
            "pad": pad,
            "sub_ctrl": sub_ctrl
        })
    """
    if not joint_list:
        joint_list = cmds.ls(sl=True, type="joint")
    if not joint_list:
        cmds.error("No joints provided.")

    results = []
    prev_ctrl = root_parent

    for jnt in joint_list:
        base = jnt.replace("_jnt", "").split("|")[-1]

        ctrl_name = f"{base}_ctrl"
        sdk_name = f"{base}_ctrl_sdk_pad"
        pad_name = f"{base}_ctrl_pad"

        if control_shape == "sphere":
            ctrl = create_sphere_ctrl(ctrl_name)
        elif control_shape == "cube":
            ctrl = create_cube_ctrl(ctrl_name, size=1.5)
        elif control_shape == "diamond":
            ctrl = create_diamond_ctrl(ctrl_name, size=1.0)
        elif control_shape == "prism":
            ctrl = create_prism_ctrl(ctrl_name, size=1.0)
        elif control_shape == "circle":
            ctrl = cmds.circle(n=ctrl_name, ch=False, normal=[1, 0, 0], radius=1.5)[0]
        elif control_shape == "arrow":
            ctrl = create_bi_arrow_ctrl(ctrl_name)
        else:
            cmds.error(f"Unsupported shape: {control_shape}")
        apply_side_color_override(ctrl)

        sdk = cmds.group(ctrl, n=sdk_name)
        pad = cmds.group(sdk, n=pad_name)

        snap_to_joint_matrix(jnt, pad)

        if prev_ctrl:
            cmds.parent(pad, prev_ctrl)

        driver = ctrl
        sub_ctrl = None

        if sub_ctrls:
            sub_ctrl = create_bi_arrow_ctrl(f"{base}_sub_ctrl")
            scale_ctrl_cvs_local(sub_ctrl, [10, 20, 10])
            sub_sdk = cmds.group(sub_ctrl, n=f"{base}_sub_ctrl_sdk")
            sub_pad = cmds.group(sub_sdk, n=f"{base}_sub_ctrl_pad")

            snap_to_joint_matrix(jnt, sub_pad)
            cmds.parent(sub_pad, ctrl)
            apply_side_color_override(sub_ctrl)
            driver = sub_ctrl

            if not cmds.attributeQuery("ShowSubCtrl", node=ctrl, exists=True):
                cmds.addAttr(ctrl, ln="ShowSubCtrl", at="bool", k=True)

            _connect_attr_once(f"{ctrl}.ShowSubCtrl", f"{sub_pad}.visibility", force=True)

            cmds.setAttr(f"{ctrl}.ShowSubCtrl", 1)

        if keep_constraint:
            existing_cons = set()
            for ctype in ("parentConstraint", "scaleConstraint"):
                rel = cmds.listRelatives(jnt, type=ctype) or []
                conn = cmds.listConnections(jnt, type=ctype) or []
                existing_cons.update(rel)
                existing_cons.update(conn)
            if existing_cons:
                _safe_delete_nodes(list(existing_cons))

        con = cmds.parentConstraint(driver, jnt, mo=False)
        scon = cmds.scaleConstraint(driver, jnt, mo=False)
        if not keep_constraint:
            cmds.delete(con)
            cmds.delete(scon)
        results.append({
            "joint": jnt,
            "ctrl": ctrl,
            "sdk": sdk,
            "pad": pad,
            "sub_ctrl": sub_ctrl
        })

        prev_ctrl = ctrl

    return results


def get_side_prefix(name):
    """
        gets side if it exists for node
    :param name: node to check
    :return: Returns 'l', 'r', or None based on joint naming.
    """

    short = name.split("|")[-1]
    if short.startswith("l_"):
        return "l"
    if short.startswith("r_"):
        return "r"
    return None


def scale_ctrl_cvs_local(ctrl, scale=(1.0, 1.0, 1.0)):
    """
        Scales CVs of a NURBS curve or surface relative to the control's local space.

    :param ctrl: transform of the control
    :param scale: (sx, sy, sz) local scale multiplier
    :return:
    """

    shapes = cmds.listRelatives(ctrl, s=True, ni=True) or []
    if not shapes:
        cmds.warning(f"No shapes found under {ctrl}")
        return

    for shape in shapes:
        if cmds.nodeType(shape) not in ("nurbsCurve", "nurbsSurface"):
            continue

        cvs = cmds.ls(f"{shape}.cv[*]", fl=True)

        for cv in cvs:
            pos = cmds.xform(cv, q=True, os=True, t=True)

            new_pos = [pos[i] * scale[i] for i in range(3)]

            cmds.xform(cv, os=True, t=new_pos)


def get_region_size_from_joints(joints):
    """
        Returns average spatial size of a joint region.
        Useful for auto-scaling controls (mouth, eyelids, brows).
    :param joints: list of joints
    :return: Average of results
    """

    if not joints:
        return 1.0

    positions = [
        cmds.xform(j, q=True, ws=True, t=True)
        for j in joints
    ]

    min_x = min(p[0] for p in positions)
    max_x = max(p[0] for p in positions)
    min_y = min(p[1] for p in positions)
    max_y = max(p[1] for p in positions)
    min_z = min(p[2] for p in positions)
    max_z = max(p[2] for p in positions)

    size_x = max_x - min_x
    size_y = max_y - min_y
    size_z = max_z - min_z

    return (size_x + size_y + size_z) / 30


def scale_ctrl_to_region(
        ctrl,
        region_joints,
        base_size=1.0,
        multiplier=1.0
):
    """
        Scales control CVs based on the size of a joint region.

    :param ctrl: ctrl to scale
    :param region_joints: list of joints
    :param base_size: reference size (tweak once per rig)
    :param multiplier: artistic tuning knob
    :return:
    """

    region_size = get_region_size_from_joints(region_joints)

    if base_size <= 0:
        base_size = 1.0

    scale_factor = (region_size * base_size) / multiplier

    scale_ctrl_cvs_local(
        ctrl,
        (scale_factor, scale_factor, scale_factor)
    )


def offset_pv_pad(pad, side, amount=5.0):
    """

    :param pad: pad to offset
    :param side: side of ctrl
    :param amount: offset amount
    :return:
    """
    if not pad or not side:
        return

    z_offset = amount if side == "r" else -amount
    cmds.move(0, 0, z_offset, pad, r=True, os=True)


def normalize(v):
    """
        Normalises a 3D vector.
    :param v: input 3D vector
    :return: list[float]
    """
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag else [0, 0, 0]


def cross(a, b):
    """
        Computes the cross product of two 3D vectors.
    :param a: first 3D vector
    :param b: second 3D vector
    :return: list[float]
    """
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0]
    ]


def create_surface_from_joints_original(
        joint_chain,
        name="surface",
):
    """
        Stable surface builder using nurbsPlane + CV positioning.
    - Offsets using joint local Z axis
    - Supports closed loops
    - Creates follicles + follicle joints
    :param joint_chain: list of joints
    :param name: surface name
    :return: surface, follicle_joints
    """

    if len(joint_chain) < 2:
        raise ValueError("Need at least 2 joints to create a surface.")

    # Collect joint positions
    joint_positions = [cmds.xform(jnt, q=True, ws=True, t=True) for jnt in joint_chain]

    # Create a curve through the joint positions
    deg = 3 if len(joint_positions) >= 4 else 1
    curve = cmds.curve(p=joint_positions, degree=deg, name=name + "_crv")

    offset = 0.1
    curves_to_loft = [curve]
    for i in range(1, 2):
        dup_curve = cmds.duplicate(curve, name=f"{name}_crv_dup{i}")[0]
        cmds.move(0, offset * i, 0, dup_curve, r=True)
        curves_to_loft.append(dup_curve)

    # Loft the curves to create a surface
    # The input curves are temporary, so bake the loft result instead of
    # leaving construction-history dependencies that are removed below.
    loft_surf = cmds.loft(curves_to_loft, ch=False, u=True, c=False, ar=True, d=deg, ss=1, rn=False, po=0, name=name)[0]

    # Delete the curves if you want to clean up
    cmds.delete(curves_to_loft)

    # ``cmds.loft`` returns the surface transform.  Surface attributes such as
    # ``local`` and ``minValueU`` live on its nurbsSurface shape; addressing
    # them through the transform is not reliable and raises errors such as
    # ``No object matches name: mouth.local`` in Maya.
    loft_shapes = cmds.listRelatives(
        loft_surf,
        shapes=True,
        noIntermediate=True,
        fullPath=True,
    ) or []
    if not loft_shapes:
        raise RuntimeError("Loft surface {!r} has no nurbsSurface shape.".format(loft_surf))
    loft_shape = loft_shapes[0]

    min_u = cmds.getAttr(loft_shape + ".minValueU")
    max_u = cmds.getAttr(loft_shape + ".maxValueU")
    min_v = cmds.getAttr(loft_shape + ".minValueV")
    max_v = cmds.getAttr(loft_shape + ".maxValueV")

    follicle_joints = []

    for jnt in joint_chain:
        pos = cmds.xform(jnt, q=True, ws=True, t=True)

        cps = cmds.createNode("closestPointOnSurface")
        cmds.connectAttr(loft_shape + ".local", cps + ".inputSurface", f=True)
        cmds.setAttr(cps + ".inPosition", *pos)

        u_real = cmds.getAttr(cps + ".parameterU")
        v_real = cmds.getAttr(cps + ".parameterV")

        cmds.delete(cps)

        u_norm = (u_real - min_u) / (max_u - min_u)
        v_norm = (v_real - min_v) / (max_v - min_v)

        fol_shape = cmds.createNode("follicle", name=f"{name}_{jnt}_folShape")
        fol_tr = cmds.listRelatives(fol_shape, parent=True)[0]

        cmds.connectAttr(loft_shape + ".local", fol_shape + ".inputSurface", f=True)
        cmds.connectAttr(loft_shape + ".worldMatrix[0]", fol_shape + ".inputWorldMatrix", f=True)

        cmds.setAttr(fol_shape + ".parameterU", u_norm)
        cmds.setAttr(fol_shape + ".parameterV", v_norm)

        cmds.connectAttr(fol_shape + ".outTranslate", fol_tr + ".translate", f=True)
        cmds.connectAttr(fol_shape + ".outRotate", fol_tr + ".rotate", f=True)

        cmds.select(clear=True)
        fol_joint = cmds.joint(name=f"{name}_{jnt}_folJoint")
        cmds.delete(cmds.parentConstraint(fol_tr, fol_joint, mo=False))
        cmds.parent(fol_joint, fol_tr, absolute=True)

        follicle_joints.append(fol_joint)

    return loft_surf, follicle_joints


def create_loft_surface_with_follicle_joints(joint_chain, name="surface", offset=0.5):
    """
        Create a lofted surface along a joint chain.
    Creates:
      - Lofted NURBS surface
      - Follicles attached to the surface
      - Follicle joints parented to the follicles (to drive controls)
    :param joint_chain: list of joints
    :param name: surface name
    :param offset: offset of curves
    :return:       loft_surf: name of the lofted NURBS surface
      follicle_joints: list of joints aligned to the follicles
    """
    forward_points = []
    backward_points = []

    # Build offset points
    for jnt in joint_chain:
        pos = cmds.xform(jnt, q=True, ws=True, t=True)
        forward_points.append([pos[0], pos[1], pos[2] + offset])
        backward_points.append([pos[0], pos[1], pos[2] - offset])

    # Create forward/backward curves
    fwd_crv = cmds.curve(p=forward_points, degree=1, name=f"{name}_fwd_crv")
    bwd_crv = cmds.curve(p=backward_points, degree=1, name=f"{name}_bwd_crv")

    # Loft surface
    deg = 3 if len(joint_chain) >= 4 else 1
    loft_surf = cmds.loft(fwd_crv, bwd_crv, ch=False, u=True, c=False, ar=True, d=deg, ss=1, name=f"{name}_surf")[0]

    # Optional: delete curves
    cmds.delete(fwd_crv, bwd_crv)

    loft_shapes = cmds.listRelatives(
        loft_surf,
        shapes=True,
        noIntermediate=True,
        fullPath=True,
    ) or []
    if not loft_shapes:
        raise RuntimeError("Loft surface {!r} has no nurbsSurface shape.".format(loft_surf))
    loft_shape = loft_shapes[0]

    # Surface param ranges
    min_u = cmds.getAttr(loft_shape + ".minValueU")
    max_u = cmds.getAttr(loft_shape + ".maxValueU")
    min_v = cmds.getAttr(loft_shape + ".minValueV")
    max_v = cmds.getAttr(loft_shape + ".maxValueV")

    follicle_joints = []

    for jnt in joint_chain:
        pos = cmds.xform(jnt, q=True, ws=True, t=True)

        cps = cmds.createNode("closestPointOnSurface")
        cmds.connectAttr(loft_shape + ".local", cps + ".inputSurface")
        cmds.setAttr(cps + ".inPosition", pos[0], pos[1], pos[2])
        u_real = cmds.getAttr(cps + ".parameterU")
        v_real = cmds.getAttr(cps + ".parameterV")
        cmds.delete(cps)

        # Normalize UV
        u_norm = (u_real - min_u) / (max_u - min_u)
        v_norm = (v_real - min_v) / (max_v - min_v)

        # Create follicle shape & transform
        fol_shape = cmds.createNode("follicle", name=f"{name}_{jnt}_folShape")
        fol_tr = cmds.listRelatives(fol_shape, parent=True)[0]

        # Connect inputs & outputs
        cmds.connectAttr(loft_shape + ".local", fol_shape + ".inputSurface", f=True)
        cmds.connectAttr(loft_shape + ".worldMatrix[0]", fol_shape + ".inputWorldMatrix", f=True)
        cmds.setAttr(fol_shape + ".parameterU", u_norm)
        cmds.setAttr(fol_shape + ".parameterV", v_norm)
        cmds.connectAttr(fol_shape + ".outTranslate", fol_tr + ".translate", f=True)
        cmds.connectAttr(fol_shape + ".outRotate", fol_tr + ".rotate", f=True)

        # Create a follicle joint at the follicle transform
        cmds.select(clear=True)
        fol_joint = cmds.joint(name=f"{name}_{jnt}_folJoint")
        cmds.delete(cmds.parentConstraint(fol_tr, fol_joint, mo=False))
        cmds.parent(fol_joint, fol_tr, absolute=True)

        follicle_joints.append(fol_joint)

    return loft_surf, follicle_joints


def setup_surface_rig(joint_chain, loft_name="eyelid", offset=0.5, region="eyelid", root_parent=None,
                      create_controls=True):
    """
        Sets up the eyelid rig:
      - Duplicates first joint to close the chain
      - Creates loft + follicles + follicle joints
      - Deletes temp joint
      - Creates controls and aims them at follicle joints
    :param joint_chain: list of joints
    :param loft_name: surface name
    :param offset: amount to offset
    :param region: region can be eyelid, mouth, or other(doesn't matter name)
    :param root_parent: what to parent system to
    :param create_controls: whether to create controls for each joint in the chain
    :return: dict mapping eyelid joints to their controls
    """

    # Duplicate first joint to append at end
    temp_joint = cmds.duplicate(joint_chain[0], parentOnly=True, name=joint_chain[0] + "_temp")[0]
    cmds.delete(cmds.parentConstraint(joint_chain[0], temp_joint))

    # Create loft + follicles + follicle joints
    closed_loop_region = region in ("eyelid", "mouth", "center_eyelid", "eyelid_center")
    if region == "eyelid":
        joint_chain = joint_chain + [temp_joint]
        side = temp_joint[0]
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)
    elif region in ("mouth", "center_eyelid", "eyelid_center"):
        joint_chain = joint_chain + [temp_joint]
        side = temp_joint[0]
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)
    else:
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)

    # Maya may return an absolute DAG path (for example ``|mouth``). Grouping
    # reparents the surface and immediately invalidates that path, so reacquire
    # the current path before returning it to the skinning step.
    loft_leaf = loft_surf.rsplit("|", 1)[-1]
    group = cmds.group(loft_surf, n=loft_leaf + "_surface_grp")
    if not cmds.objExists("Do_Not_Touch"):
        dnt = cmds.group(em=True, name="Do_Not_Touch")
        cmds.setAttr(dnt + ".visibility", 0)
    group = cmds.parent(group, "Do_Not_Touch")[0]
    surface_children = cmds.listRelatives(
        group,
        children=True,
        type="transform",
        fullPath=True,
    ) or []
    loft_matches = [
        child for child in surface_children
        if cmds.listRelatives(child, shapes=True, type="nurbsSurface")
    ]
    if not loft_matches:
        raise RuntimeError(
            "Could not resolve loft surface {!r} after grouping it under Do_Not_Touch.".format(loft_leaf)
        )
    loft_surf = loft_matches[0]
    for fj in follicle_joints:
        parent = cmds.listRelatives(fj, p=1, ap=1)[0]
        cmds.parent(parent, group)
    if closed_loop_region:
        follicle_joints = follicle_joints[:-1]

    # Create controls and aim them at follicle joints
    joint_to_ctrl = {}
    if create_controls:
        for idx, joint in enumerate(joint_chain[:-1]):
            if region == "eyelid":
                ctrl_data = create_joint_controls(
                    joint_list=[cmds.listRelatives(joint, p=1)[0]],
                    control_shape="circle",
                    root_parent=root_parent,
                    sub_ctrls=False,
                    keep_constraint=True
                )
                ctrl_name = ctrl_data[0]['ctrl']
                ctrl_pad = ctrl_data[0]['pad']
                cmds.setAttr(ctrl_pad + ".visibility", 0)
                # Aim control pad at follicle joint
                aim = cmds.aimConstraint(
                    follicle_joints[idx],
                    ctrl_pad,
                    aimVector=(1, 0, 0),
                    upVector=(0, 1, 0),
                    worldUpType="objectrotation",
                    worldUpObject=root_parent,
                    worldUpVector=(0, -1, 0),
                    mo=True
                )

                # Delete other constraints on joint not part of this aim
                constraints = cmds.listRelatives(joint, type="constraint", allDescendents=False) or []
                for c in constraints:
                    if c not in aim:
                        cmds.delete(c)
            else:
                control_shape = "circle"
                local_root_parent = root_parent
                if region == "mouth":
                    if "upper" in joint:
                        local_root_parent = root_parent or "head1_ctrl"
                    else:
                        local_root_parent = "jaw_ctrl" if cmds.objExists("jaw_ctrl") else (root_parent or "head1_ctrl")
                elif "twist" in region:
                    control_shape = "arrow"
                ctrl_data = create_joint_controls(
                    joint_list=[joint],
                    control_shape=control_shape,
                    root_parent=local_root_parent,
                    sub_ctrls=False,
                    # The follicle drives the control pad; the control must in
                    # turn remain constrained to the original bind joint.
                    keep_constraint=True
                )
                ctrl_name = ctrl_data[0]['ctrl']
                ctrl_pad = ctrl_data[0]['pad']

                cmds.parentConstraint(follicle_joints[idx], ctrl_pad, mo=True)

            joint_to_ctrl[joint] = ctrl_name

            scale_ctrl_to_region(
                ctrl_name,
                follicle_joints,
                base_size=1.0,
                multiplier=1.0
            )
        if region not in ("eyelid", "mouth"):
            ctrl_data = create_joint_controls(
                joint_list=[joint_chain[-1]],
                control_shape="circle",
                root_parent=root_parent,
                sub_ctrls=False,
                keep_constraint=True
            )
            ctrl_name = ctrl_data[0]['ctrl']
            ctrl_pad = ctrl_data[0]['pad']
            cmds.parentConstraint(follicle_joints[-1], ctrl_pad, mo=True)
            scale_ctrl_to_region(
                ctrl_name,
                follicle_joints,
                base_size=1.0,
                multiplier=1.0
            )

    # Clean up the temporary joint used for closed loops
    if closed_loop_region and cmds.objExists(temp_joint):
        try:
            cmds.delete(temp_joint)
        except Exception:
            pass

    return loft_surf, follicle_joints, joint_to_ctrl


def _bind_surface_to_joints(surface, influences, **skin_options):
    """Bind a NURBS surface in place using an explicit transform DAG path."""
    surface_matches = cmds.ls(surface, long=True) or []
    if not surface_matches:
        raise RuntimeError(f"Surface does not exist: {surface}")
    surface = surface_matches[0]

    # Always parent the owning transform.  Passing a mesh/NURBS shape to
    # ``parent -world`` raises a generic Maya command error, which is easy to
    # hit when callers supply the result of a shape query.
    if cmds.nodeType(surface) in ("mesh", "nurbsSurface", "subdiv"):
        owners = cmds.listRelatives(surface, parent=True, fullPath=True) or []
        if not owners:
            raise RuntimeError(f"Surface shape has no transform: {surface}")
        surface = owners[0]

    bind_surface = (cmds.ls(surface, long=True) or [surface])[0]
    try:
        skin = cmds.skinCluster(*(list(influences) + [bind_surface]), **skin_options)[0]
    except RuntimeError as exc:
        raise RuntimeError(
            "Could not bind surface {!r} to drivers {}: {}".format(
                bind_surface,
                ", ".join(str(node) for node in influences),
                exc,
            )
        ) from exc
    return skin, (cmds.ls(bind_surface, long=True) or [bind_surface])[0]


def _group_center_surface_controls(loft_name, root_parent, driver_data, joint_to_ctrl):
    """Group centered main controls and share their scale with joint controls."""
    main_pads = []
    for data in driver_data.values():
        pad = data.get("pad") if isinstance(data, dict) else None
        if pad and cmds.objExists(pad) and pad not in main_pads:
            main_pads.append(pad)
    if not main_pads:
        return None

    group_name = f"{_stretch_node_token(loft_name)}_main_ctrls_grp"
    matches = cmds.ls(group_name, type="transform", long=True) or []
    created_group = not bool(matches)
    if matches:
        main_group = matches[0]
    elif root_parent and cmds.objExists(root_parent):
        main_group = cmds.group(empty=True, name=group_name, parent=root_parent)
    else:
        main_group = cmds.group(empty=True, name=group_name)

    main_group = (cmds.ls(main_group, long=True) or [main_group])[0]
    if created_group:
        positions = [cmds.xform(pad, query=True, worldSpace=True, translation=True) for pad in main_pads]
        center = [sum(position[axis] for position in positions) / len(positions) for axis in range(3)]
        cmds.xform(main_group, worldSpace=True, translation=center)
    for pad in main_pads:
        pad_long = (cmds.ls(pad, long=True) or [pad])[0]
        current_parent = cmds.listRelatives(pad_long, parent=True, fullPath=True) or []
        if not current_parent or current_parent[0] != main_group:
            cmds.parent(pad_long, main_group, absolute=True)

    for ctrl in joint_to_ctrl.values():
        if not ctrl or not cmds.objExists(ctrl):
            continue
        sdk = cmds.listRelatives(ctrl, parent=True, fullPath=True) or []
        pads = cmds.listRelatives(sdk[0], parent=True, fullPath=True) if sdk else []
        if not pads:
            continue
        pad = pads[0]
        for axis in "XYZ":
            _connect_attr_once(
                f"{main_group}.scale{axis}",
                f"{pad}.scale{axis}",
                force=True,
            )
    return main_group


def setup_surface_rig_with_drivers(
        joint_list,
        loft_name="eyelid",
        offset=0.5,
        driver_follicle_indices=None,
        side="r",
        region="eyelid",
        root_parent=None,
        face_joint_map=None
):
    """
        Sets up a driver based surface rig (great for Mouth and eyelid setups)
    :param joint_list: list of joints
    :param loft_name: surface name
    :param offset: amount to offset curves to loft from joints
    :param driver_follicle_indices: mapping indices; if None, they are auto-detected
    :param side: right or left
    :param region: mouth, eyelid, or other
    :param root_parent: what to parent system to
    :param face_joint_map: dictionary containing face mapping data
    :return: tuple
    """
    N = len(joint_list)
    region = str(region or "other").lower()
    side = str(side or "c").lower()
    centered_eyelid = region in ("center_eyelid", "eyelid_center") or (
        region == "eyelid" and side in ("c", "center", "centre")
    )
    if centered_eyelid:
        region = "center_eyelid"
        side = "c"
    is_twist_surface = (
            "twist" in loft_name.lower()
            or "twist" in region.lower()
            or region.lower() in ("upperarm", "lowerarm", "thigh", "knee")
            or any("_twist" in str(j).lower() for j in joint_list)
    )
    if region == "center_eyelid":
        if driver_follicle_indices is None:
            default_indices = [0, 2, 5, 8, 10, 12, 15, 18]
            driver_follicle_indices = [
                int(round(idx * (N - 1) / 19.0)) for idx in default_indices
            ]
        driver_follicle_indices = list(dict.fromkeys(driver_follicle_indices))
        # A centered eyelid uses the closed-loop, direct-control layout used by
        # the mouth, but derives neutral c_ driver names from the selected
        # joints instead of inventing left/right eyelid semantics.
        driver_index_map = {
            idx: f"{_stretch_node_token(joint_list[idx])}_main"
            for idx in driver_follicle_indices
            if 0 <= idx < N
        }
    elif region == "eyelid":
        if driver_follicle_indices is None:
            default_indices = [0, 3, 6, 9, 12, 15, 18, 20]
            scaled_indices = [int(round(idx * (N - 1) / 20.0)) for idx in default_indices]
            driver_follicle_indices = scaled_indices

            driver_index_map = {
                scaled_indices[0]: side + "_inner_eyelid",
                scaled_indices[1]: side + "_upper_inner_eyelid",
                scaled_indices[2]: side + "_upper_eyelid",
                scaled_indices[3]: side + "_upper_outer_eyelid",
                scaled_indices[4]: side + "_outer_eyelid",
                scaled_indices[5]: side + "_lower_outer_eyelid",
                scaled_indices[6]: side + "_lower_eyelid",
                scaled_indices[7]: side + "_lower_inner_eyelid",
            }
        else:
            driver_index_map = {
                0: side + "_inner_eyelid",
                3: side + "_upper_inner_eyelid",
                6: side + "_upper_eyelid",
                9: side + "_upper_outer_eyelid",
                12: side + "_outer_eyelid",
                15: side + "_lower_outer_eyelid",
                18: side + "_lower_eyelid",
                20: side + "_lower_inner_eyelid",
            }
    elif region == "mouth":
        c_up = "c_upper_lip"
        c_lo = "c_lower_lip"
        l_co = "l_lip_corner1"
        r_co = "r_lip_corner1"

        if face_joint_map:
            c_up = face_joint_map.get("UpperLipCenter", {}).get("joint") or c_up
            c_lo = face_joint_map.get("LowerLipCenter", {}).get("joint") or c_lo
            l_co = face_joint_map.get("LeftLipCorner", {}).get("joint") or l_co
            r_co = face_joint_map.get("RightLipCorner", {}).get("joint") or r_co

        def lip_name(idx, default_base):
            """
                Lip name.
            :param idx: idx
            :param default_base: default base
            :return: result
            """
            if idx < len(joint_list) and joint_list[idx]:
                return joint_list[idx] + "_main"
            return default_base

        if driver_follicle_indices is None:
            default_indices = [0, 2, 5, 8, 10, 12, 15, 18]
            scaled_indices = [int(round(idx * (N - 1) / 19.0)) for idx in default_indices]
            driver_follicle_indices = scaled_indices

            driver_index_map = {
                scaled_indices[0]: f"{c_up}_main",
                scaled_indices[1]: lip_name(scaled_indices[1], "r_upper_lip_main"),
                scaled_indices[2]: f"{r_co}_main",
                scaled_indices[3]: lip_name(scaled_indices[3], "r_lower_lip_main"),
                scaled_indices[4]: f"{c_lo}_main",
                scaled_indices[5]: lip_name(scaled_indices[5], "l_lower_lip_main"),
                scaled_indices[6]: f"{l_co}_main",
                scaled_indices[7]: lip_name(scaled_indices[7], "l_upper_lip_main"),
            }
        else:
            driver_index_map = {
                0: f"{c_up}_main",
                2: lip_name(2, "r_upper_lip_main"),
                5: f"{r_co}_main",
                8: lip_name(8, "r_lower_lip_main"),
                10: f"{c_lo}_main",
                12: lip_name(12, "l_lower_lip_main"),
                15: f"{l_co}_main",
                18: lip_name(18, "l_upper_lip_main"),
            }
    else:
        if driver_follicle_indices is None:
            if is_twist_surface:
                driver_follicle_indices = []
            else:
                driver_follicle_indices = list(range(len(joint_list)))
        driver_index_map = {
            i: f"{joint_list[i]}_driver" if is_twist_surface else joint_list[i] + "_main"
            for i in range(len(joint_list))
        }

    loft_surf, follicle_joints, joint_to_ctrl = setup_surface_rig(
        joint_list,
        loft_name=loft_name,
        offset=offset,
        region=region,
        root_parent=root_parent
    )

    driver_joints = []
    driver_data = {}

    if not driver_follicle_indices:
        driver_name = joint_list[0]
        if "1_twist" in driver_name:
            driver_bone = driver_name.split("1_twist")[0] + "_driver"
        elif "_twist" in driver_name:
            driver_bone = driver_name.split("_twist")[0] + "_driver"
        else:
            driver_bone = driver_name + "_driver"

        child_bone = cmds.listRelatives(driver_bone, c=1)[0]
        parent_transform = cmds.listRelatives(driver_bone, p=1)[0]
        create_twist_driver(driver_bone, child_bone, parent_transform, loft_surf)
        return loft_surf, follicle_joints, joint_to_ctrl, {}

    for idx in driver_follicle_indices:
        if idx not in driver_index_map:
            cmds.warning(f"Index {idx} not defined in driver_index_map — skipping")
            continue

        if idx >= len(follicle_joints):
            cmds.warning(f"Index {idx} is out of range for follicle_joints — skipping")
            continue
        base_joint = joint_list[idx]
        semantic = driver_index_map[idx]
        if region == "eyelid":
            driver_name = f"{semantic}"
        else:
            driver_name = f"{semantic}"

        # Duplicate follicle joint
        driver_joint = cmds.duplicate(
            base_joint,
            parentOnly=True,
            name=driver_name
        )[0]

        # Duplicate preserves the source joint's parent. Detach only when it
        # actually has one; ``parent -world`` on an existing world child emits
        # the misleading "already a child" warning seen with baked path joints.
        if cmds.listRelatives(driver_joint, parent=True):
            driver_joint = cmds.parent(driver_joint, world=True, absolute=True)[0]

        control_shape = "circle"
        if region in ("mouth", "center_eyelid"):
            control_shape = "cube"

        # Create control
        ctrl_data = create_joint_controls(
            joint_list=[driver_joint],
            control_shape=control_shape,
            root_parent=root_parent,
            sub_ctrls=False,
            keep_constraint=False
        )

        ctrl = ctrl_data[0]["ctrl"]
        apply_side_color_override(ctrl)
        pad = ctrl_data[0]["pad"]
        current_parent = (cmds.listRelatives(driver_joint, parent=True, fullPath=True) or [None])[0]
        ctrl_long = (cmds.ls(ctrl, long=True) or [ctrl])[0]
        if current_parent != ctrl_long:
            cmds.parent(driver_joint, ctrl)
        driver_data[semantic] = {
            "joint": driver_joint,
            "ctrl": ctrl,
            "pad": pad
        }
        scale_ctrl_cvs_local(ctrl, [.5, .5, .5])
        driver_joints.append(driver_joint)

    if region == "center_eyelid":
        _group_center_surface_controls(
            loft_name,
            root_parent,
            driver_data,
            joint_to_ctrl,
        )

    if driver_joints:
        _skin, loft_surf = _bind_surface_to_joints(
            loft_surf,
            driver_joints,
            tsb=True,
            bindMethod=0,
            skinMethod=0,
            normalizeWeights=1,
        )

    def constrain_pad(pad, driver_joints):
        """
            Constrain pad.
        :param pad: pad
        :param driver_joints: list of driver joints
        :return: result
        """
        constraint = cmds.parentConstraint(
            driver_joints,
            pad,
            mo=True
        )[0]

        cmds.setAttr(constraint + ".interpType", 2)
        return constraint

    if region == "eyelid":
        if side + "_upper_inner_eyelid" in driver_data:
            con = constrain_pad(
                driver_data[side + "_upper_inner_eyelid"]["pad"],
                [
                    driver_data[side + "_inner_eyelid"]["ctrl"],
                    driver_data[side + "_upper_eyelid"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            upper_w = [w for w in weights if "upper_eyelid" in w][0]
            inner_w = [w for w in weights if "inner_eyelid" in w][0]

            cmds.setAttr(f"{con}.{upper_w}", 0.55)
            cmds.setAttr(f"{con}.{inner_w}", 0.45)

        if side + "_upper_outer_eyelid" in driver_data:
            con = constrain_pad(
                driver_data[side + "_upper_outer_eyelid"]["pad"],
                [
                    driver_data[side + "_upper_eyelid"]["ctrl"],
                    driver_data[side + "_outer_eyelid"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            upper_w = [w for w in weights if "upper_eyelid" in w][0]
            outer_w = [w for w in weights if "outer_eyelid" in w][0]

            cmds.setAttr(f"{con}.{upper_w}", 0.65)
            cmds.setAttr(f"{con}.{outer_w}", 0.35)

        if side + "_lower_inner_eyelid" in driver_data:
            con = constrain_pad(
                driver_data[side + "_lower_inner_eyelid"]["pad"],
                [
                    driver_data[side + "_lower_eyelid"]["ctrl"],
                    driver_data[side + "_inner_eyelid"]["ctrl"],
                ]
            )

        if side + "_lower_outer_eyelid" in driver_data:
            con = constrain_pad(
                driver_data[side + "_lower_outer_eyelid"]["pad"],
                [
                    driver_data[side + "_lower_eyelid"]["ctrl"],
                    driver_data[side + "_outer_eyelid"]["ctrl"],
                ]
            )

    elif region == "mouth":
        c_up_main = f"{c_up}_main"
        c_lo_main = f"{c_lo}_main"
        l_co_main = f"{l_co}_main"
        r_co_main = f"{r_co}_main"

        r_up_main = lip_name(2, "r_upper_lip_main")
        r_lo_main = lip_name(8, "r_lower_lip_main")
        l_lo_main = lip_name(12, "l_lower_lip_main")
        l_up_main = lip_name(18, "l_upper_lip_main")

        if r_up_main in driver_data:
            con = constrain_pad(
                driver_data[r_up_main]["pad"],
                [
                    driver_data[c_up_main]["ctrl"],
                    driver_data[r_co_main]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if c_up_main in w][0]
            corner_w = [w for w in weights if r_co_main in w or "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.9)
            cmds.setAttr(f"{con}.{corner_w}", 0.1)

        if l_up_main in driver_data:
            con = constrain_pad(
                driver_data[l_up_main]["pad"],
                [
                    driver_data[c_up_main]["ctrl"],
                    driver_data[l_co_main]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if c_up_main in w][0]
            corner_w = [w for w in weights if l_co_main in w or "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.9)
            cmds.setAttr(f"{con}.{corner_w}", 0.1)

        if r_lo_main in driver_data:
            con = constrain_pad(
                driver_data[r_lo_main]["pad"],
                [
                    driver_data[c_lo_main]["ctrl"],
                    driver_data[r_co_main]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if c_lo_main in w][0]
            corner_w = [w for w in weights if r_co_main in w or "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.7)
            cmds.setAttr(f"{con}.{corner_w}", 0.3)

        if l_lo_main in driver_data:
            con = constrain_pad(
                driver_data[l_lo_main]["pad"],
                [
                    driver_data[c_lo_main]["ctrl"],
                    driver_data[l_co_main]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if c_lo_main in w][0]
            corner_w = [w for w in weights if l_co_main in w or "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.7)
            cmds.setAttr(f"{con}.{corner_w}", 0.3)

        if cmds.objExists(f"{c_up}_ctrl_pad") and c_up_main in driver_data:
            cmds.parent(f"{c_up}_ctrl_pad", driver_data[c_up_main]["ctrl"])
        if cmds.objExists(f"{c_lo}_ctrl_pad") and c_lo_main in driver_data:
            cmds.parent(f"{c_lo}_ctrl_pad", driver_data[c_lo_main]["ctrl"])
        if cmds.objExists(f"{l_co}_ctrl_pad") and l_co_main in driver_data:
            cmds.parent(f"{l_co}_ctrl_pad", driver_data[l_co_main]["ctrl"])
        if cmds.objExists(f"{r_co}_ctrl_pad") and r_co_main in driver_data:
            cmds.parent(f"{r_co}_ctrl_pad", driver_data[r_co_main]["ctrl"])

        for each in [f"{c_up}_ctrl_pad_parentConstraint1",
                     f"{c_lo}_ctrl_pad_parentConstraint1",
                     f"{r_co}_ctrl_pad_parentConstraint1",
                     f"{l_co}_ctrl_pad_parentConstraint1"]:
            if cmds.objExists(each):
                cmds.delete(each)

    return loft_surf, follicle_joints, joint_to_ctrl, driver_data


def constrain_controls_to_two_parents(
        controls,
        parent1,
        parent2,
        parent1_value=1.0,
        parent2_value=0.0,
        maintain_offset=True
):
    """
        Apply a parentConstraint to each control in the list using parent1 and parent2 as drivers.
    :param controls: Controls to constrain
    :param parent1: First parent/driver
    :param parent2: Second parent/driver
    :param parent1_value: Weight value for parent1
    :param parent2_value: Weight value for parent2
    :param maintain_offset: Whether to maintain offset
    :return: list[str]
    """

    if not controls:
        cmds.error("No controls were provided.")

    for node in [parent1, parent2]:
        if not cmds.objExists(node):
            cmds.error("Driver does not exist: {}".format(node))

    created_constraints = []

    for ctrl in controls:
        if not cmds.objExists(ctrl):
            cmds.warning("Skipping missing control: {}".format(ctrl))
            continue

        # Create parent constraint
        constraint = cmds.parentConstraint(
            parent1,
            parent2,
            ctrl,
            mo=maintain_offset
        )[0]

        if cmds.attributeQuery("interpType", node=constraint, exists=True):
            cmds.setAttr("{}.interpType".format(constraint), 2)

        # Set weight values
        weight_aliases = cmds.parentConstraint(constraint, q=True, weightAliasList=True) or []
        targets = cmds.parentConstraint(constraint, q=True, targetList=True) or []

        target_to_weight_attr = dict(zip(targets, weight_aliases))

        if parent1 in target_to_weight_attr:
            cmds.setAttr(
                "{}.{}".format(constraint, target_to_weight_attr[parent1]),
                parent1_value
            )

        if parent2 in target_to_weight_attr:
            cmds.setAttr(
                "{}.{}".format(constraint, target_to_weight_attr[parent2]),
                parent2_value
            )

        created_constraints.append(constraint)

    return created_constraints


def bake_joint_orient_to_rotate(joints=None):
    """
        Moves jointOrient values into rotate channels while preserving world-space pose.
    :param joints: list of joints to bake; all joints if None
    :return: None
    """

    if joints is None:
        joints = cmds.ls(type="joint")

    for jnt in joints:
        if not cmds.objExists(jnt):
            continue

        # Get DAG path
        sel = om.MSelectionList()
        sel.add(jnt)
        dag = sel.getDagPath(0)
        fn = om.MFnTransform(dag)

        # Store world transform
        world_matrix = fn.transformation().asMatrix()

        # Zero joint orient
        cmds.setAttr(jnt + ".jointOrientX", 0)
        cmds.setAttr(jnt + ".jointOrientY", 0)
        cmds.setAttr(jnt + ".jointOrientZ", 0)

        # Restore world transform
        fn.setTransformation(om.MTransformationMatrix(world_matrix))

    cmds.select(joints)


def create_finger_rigs(finger_joints, hand_driver=None):
    """
        Creates IK driven FK system for finger joints
    :param finger_joints: finger joints
    :param hand_driver: parent transform/joint name to parent finger rigs under
    :return:
    """
    finger_names = ['thumb', 'index', 'middle', 'ring', 'pinky']
    fingers = {}

    def get_side_prefix(name):
        """
            gets prefix of ctrl
        :param name: ctrl name
        :return: l, r,or None
        """
        short = name.split("|")[-1]
        if short.startswith("l_"):
            return "l"
        if short.startswith("r_"):
            return "r"
        return None

    def rename_finger_chain_from_source(source_chain, dup_chain, suffix, side):
        """
            Rename finger chain from source.
        :param source_chain: source chain
        :param dup_chain: dup chain
        :param suffix: suffix
        :param side: side
        :return: result
        """
        new_chain = []

        dup_chain = dup_chain[:len(source_chain)]

        for i, (src, dup) in enumerate(zip(source_chain, dup_chain), start=1):
            src_short = src.split("|")[-1]

            base = src_short
            if side and src_short.startswith(f"{side}_"):
                base = src_short[len(side) + 1:]

            base = base.replace("_jnt", "")
            base = re.sub(r"_(fk|ik|driver)$", "", base)

            match = re.match(r"(.*?)(?:_(\d+))?$", base)
            if match:
                name_part = match.group(1)
                index_part = match.group(2) or str(i)
            else:
                name_part = base
                index_part = str(i)

            new_name = f"{side}_{name_part}_{index_part}_{suffix}".replace("__", "_")

            for existing in cmds.ls(new_name, long=True) or []:
                cmds.delete(existing)

            new_chain.append(cmds.rename(dup, new_name))

        return new_chain

    for finger in finger_names:
        fk_chain = [j for j in finger_joints if finger in j.lower()]
        fk_chain.reverse()
        if not fk_chain:
            continue

        side = get_side_prefix(fk_chain[0])

        actual_hand_driver = hand_driver if hand_driver else f"{side}_hand_driver"
        if not cmds.objExists(actual_hand_driver):
            if cmds.objExists(f"{side}_hand"):
                actual_hand_driver = f"{side}_hand"
            else:
                actual_hand_driver = None

        duplicate_source = fk_chain if finger == "thumb" else fk_chain[1:]
        ik_root, ik_chain = duplicate_static_hierarchy(duplicate_source, suffix="ik")

        if actual_hand_driver and ik_chain:
            cmds.parent(ik_chain[0], actual_hand_driver)

        for jnt in ik_chain:
            if cmds.objExists(jnt):
                cmds.setAttr(f"{jnt}.drawStyle", 2)
        for jnt in ik_chain:
            if jnt == ik_chain[0] and "thumb" not in jnt:
                continue
            rot = cmds.getAttr(f"{jnt}.rotate")[0]
            j_orient = cmds.getAttr(f"{jnt}.jointOrient")[0]

            baked_rot = [
                rot[0] + j_orient[0],
                rot[1] + j_orient[1],
                rot[2] + j_orient[2]]

            # Apply baked rotation
            cmds.setAttr(f"{jnt}.rotate", baked_rot[0], baked_rot[1], baked_rot[2])

            # Zero joint orient
            cmds.setAttr(f"{jnt}.jointOrient", 0, 0, 0)

        fk_ctrls = create_joint_controls(fk_chain, control_shape="cube", root_parent=actual_hand_driver)
        for i, jnt in enumerate(fk_chain):
            if jnt != fk_chain[-1]:

                snap_ctrl_cvs_to_child(fk_ctrls[i]["ctrl"], fk_chain[i + 1])
            else:
                cmds.delete(fk_ctrls[i]["pad"])

        pv_joint = ik_chain[1] if len(ik_chain) > 1 else ik_chain[0]
        pv_ctrl_info = create_joint_controls([pv_joint], control_shape="diamond", root_parent=actual_hand_driver)[0]
        pv_ctrl = pv_ctrl_info['ctrl']

        for c in cmds.listRelatives(pv_joint, type="constraint") or []:
            cmds.delete(c)
        pv_pad = pv_ctrl_info['pad']
        cmds.xform(pv_ctrl, ws=True, t=cmds.xform(pv_joint, q=True, ws=True, t=True))

        offset_pv_pad(pv_pad, side, amount=-5.0)

        start_joint = ik_chain[0]
        ikh_name = f"{side}_{finger}_ikh" if side else f"{finger}_ikh"

        ik_handle, _ = cmds.ikHandle(
            n=ikh_name,
            sj=start_joint,
            ee=ik_chain[-1],
            sol="ikRPsolver"
        )

        ik_ctrl_info = create_joint_controls([ik_handle], control_shape="cube")[0]
        cmds.xform(
            ik_ctrl_info['pad'],
            ws=True,
            t=cmds.xform(ik_handle, q=True, ws=True, t=True)
        )
        if actual_hand_driver:
            cmds.parent(ik_ctrl_info['pad'], actual_hand_driver)
        cmds.parent(ik_handle, ik_ctrl_info['ctrl'])
        cmds.poleVectorConstraint(pv_ctrl, ik_handle)

        for ik_jnt in ik_chain:
            if ik_jnt == ik_chain[0] and "thumb" not in ik_jnt:
                continue
            fk_jnt = ik_jnt.replace("_ik", "")
            pad = f"{fk_jnt}_ctrl_pad"

            if not cmds.objExists(pad):
                continue

            cmds.delete(cmds.parentConstraint(ik_jnt, pad, mo=False))

            for axis in "XYZ":
                src = f"{ik_jnt}.translate{axis}"
                dst = f"{pad}.translate{axis}"
                if not cmds.isConnected(src, dst):
                    cmds.connectAttr(src, dst, f=True)

            for axis in "XYZ":
                src = f"{ik_jnt}.rotate{axis}"
                dst = f"{pad}.rotate{axis}"
                if not cmds.isConnected(src, dst):
                    cmds.connectAttr(src, dst, f=True)

        if "thumb" in ik_chain[0]:
            root_ctrl = actual_hand_driver
        else:
            root_ctrl = fk_ctrls[0]["ctrl"]
        finger_pv_space = create_composite_space(
            name=pv_pad + "_space",
            parents=[ik_ctrl_info['ctrl'], root_ctrl],
            match_to=pv_ctrl,
            parent_node=actual_hand_driver
        )
        create_space_switch(
            driven=pv_ctrl,
            targets=[
                ik_ctrl_info['ctrl'],
                root_ctrl,
                finger_pv_space
            ],
            attr_name="space",
            constraint_type="parent"
        )
        fingers[f"{side}_{finger}" if side else finger] = {
            'fk_chain': fk_chain,
            'ik_chain': ik_chain,
            'fk_ctrls': fk_ctrls,
            'joints': fk_chain
        }

    print("✅ Finger rigs created with side-safe naming.")
    return fingers


def mirror_face_joints(
        joints,
        search_replace=("l_", "r_"),
        mirror_axis="YZ",
        rotate_z_180=True
):
    """
    Mirrors face joints and optionally rotates them 180 degrees in Z (object space).

    :param joints: list of joint names to mirror
    :param search_replace: tuple (search, replace) for naming
    :param mirror_axis: 'YZ', 'XZ', or 'XY'
    :param rotate_z_180: bool, apply local Z 180 rotation after mirror
    :return: list of mirrored joints
    """

    if not joints:
        return []

    axis_map = {
        "YZ": (1, 0, 0),
        "XZ": (0, 1, 0),
        "XY": (0, 0, 1),
    }

    if mirror_axis not in axis_map:
        raise ValueError("mirror_axis must be 'YZ', 'XZ', or 'XY'")

    mirror_vector = axis_map[mirror_axis]

    mirrored_joints = []

    for jnt in joints:
        if not cmds.objExists(jnt):
            continue

        mirrored = cmds.mirrorJoint(
            jnt,
            mirrorBehavior=True,
            mirrorYZ=(mirror_axis == "YZ"),
            mirrorXZ=(mirror_axis == "XZ"),
            mirrorXY=(mirror_axis == "XY"),
            searchReplace=search_replace
        )

        mirrored_joints.extend(mirrored)

    if rotate_z_180:
        for jnt in mirrored_joints:
            # Apply object-space rotation
            cmds.rotate(
                0, 0, 180,
                jnt,
                objectSpace=True,
                relative=True
            )

    return mirrored_joints


def create_composite_space(name, parents, match_to, parent_node=None):
    """
        Creates a transform constrained to multiple parents, matched to the driven group.
    :param name: name of the composite space node to create
    :param parents: list of parent control nodes
    :param match_to: node to match position/orientation to
    :param parent_node: optional node to parent the created space transform under before constraining
    :return: str or None
    """
    if not match_to or not cmds.objExists(match_to):
        return None
    valid_parents = [p for p in parents if p and cmds.objExists(p)]
    if not valid_parents:
        return None

    short_name = name.split("|")[-1]

    # Delete existing node if any to avoid name collisions (e.g. grp1, grp2)
    if cmds.objExists(short_name):
        try:
            existing_nodes = cmds.ls(short_name, long=True) or []
            for n in existing_nodes:
                if cmds.objExists(n):
                    cmds.delete(n)
        except Exception:
            pass

    grp = cmds.createNode("transform", name=short_name)

    cmds.delete(cmds.parentConstraint(match_to, grp))

    if parent_node and cmds.objExists(parent_node):
        grp = cmds.parent(grp, parent_node)[0]

    # Get absolute long path of the group to avoid any name resolution ambiguity in Maya
    grp_long = cmds.ls(grp, long=True)[0]

    cmds.parentConstraint(valid_parents, grp_long, mo=True)

    return grp_long


def create_space_switch(
        driven,
        targets,
        attr_name="space",
        dup_suffix="_spaceTarget",
        constraint_type="parent",
        enum_names=None
):
    """
        Builds a space switch where each target gets a matched child transform,
        and those children are the actual constraint drivers.
        Constraint is applied to the driven control's parent group.
    :param driven: control name that drives space switching (e.g. "r_lowerarm_low_pv_ctrl")
    :param targets: list of target control names (e.g. ["r_clavicle1_ctrl", "pelvis_ctrl", "origin_ctrl"])
    :param attr_name: name of the enum attribute created on the driven control
    :param dup_suffix: suffix appended to duplicated space target transforms
    :param constraint_type: type of constraint to use ("parent" or "orient")
    :param enum_names: optional list of custom enum display names for options
    :return: dict
    """

    if constraint_type not in ("parent", "orient"):
        cmds.error("constraint_type must be 'parent' or 'orient'")

    if not cmds.objExists(driven):
        cmds.error(f"Driven object does not exist: {driven}")

    driven_parent = cmds.listRelatives(driven, p=True)
    if not driven_parent:
        cmds.error(f"Driven object '{driven}' has no parent group to constrain.")

    driven_grp = driven_parent[0]

    valid_targets = []
    valid_enum_names = []

    for i, t in enumerate(targets):
        if not t or not cmds.objExists(t):
            continue

        if t in valid_targets:
            continue

        valid_targets.append(t)

        if enum_names and i < len(enum_names):
            valid_enum_names.append(enum_names[i])

    # Clean up any existing space switch setup on this control first (breaks connections so attribute can be deleted safely)
    _delete_space_switch_for_ctrl(driven, attr_name)

    # Create enum attribute (recreate if exists to match current targets)
    if cmds.attributeQuery(attr_name, node=driven, exists=True):
        try:
            cmds.deleteAttr(f"{driven}.{attr_name}")
        except Exception:
            pass
    if enum_names and len(enum_names) == len(valid_targets):
        enum_string = ":".join(enum_names)
    else:
        enum_string = ":".join(build_enum_names_for_space_targets(valid_targets, side=get_side_prefix(driven)))
    cmds.addAttr(driven, ln=attr_name, at="enum", enumName=enum_string, k=True)

    driver_children = []

    # Pick constraint commands dynamically
    constraint_cmd = cmds.parentConstraint if constraint_type == "parent" else cmds.orientConstraint

    driven_short = driven.split("|")[-1]
    for t in valid_targets:
        t_short = t.split("|")[-1]
        dup_name = f"{driven_short}_{t_short}{dup_suffix}"
        # Delete existing space target transform to avoid naming collisions
        if cmds.objExists(dup_name):
            try:
                cmds.delete(dup_name)
            except Exception:
                pass

        dup = cmds.createNode(
            "transform",
            name=dup_name
        )
        dup = cmds.parent(dup, t)[0]

        # Match driven group
        cmds.delete(constraint_cmd(driven_grp, dup))

        driver_children.append(dup)

    # Create final constraint
    constraint = constraint_cmd(driver_children, driven_grp, mo=True)[0]

    # Query weights
    weights = (
        cmds.parentConstraint(constraint, q=True, wal=True)
        if constraint_type == "parent"
        else cmds.orientConstraint(constraint, q=True, wal=True)
    )

    driver_attr = f"{driven}.{attr_name}"

    # Driven keys
    for i, w in enumerate(weights):
        cmds.setDrivenKeyframe(
            f"{constraint}.{w}",
            cd=driver_attr,
            dv=i,
            v=1
        )

        cmds.setDrivenKeyframe(
            f"{constraint}.{w}",
            cd=driver_attr,
            dv=i - 1,
            v=0
        )
        cmds.setDrivenKeyframe(
            f"{constraint}.{w}",
            cd=driver_attr,
            dv=i + 1,
            v=0
        )
        cmds.setAttr(driver_attr, i)

    return {
        "drivers": driver_children,
        "constraint": constraint,
        "driven_grp": driven_grp,
        "attribute": driver_attr,
        "type": constraint_type
    }


def build_enum_names_for_space_targets(targets, side=None):
    """
    Build enum display names in the SAME ORDER as the incoming targets.
    Do not reorder here. Target order must drive enum order.
    :param targets: list of targets
    :param side: side
    :return: result
    """

    def short_name(node):
        """
            Short name.
        :param node: node
        :return: result
        """
        return node.split("|")[-1].split(":")[-1]

    def label_for_target(target):
        """
            Label for target.
        :param target: target
        :return: result
        """
        short = short_name(target).lower()

        if short in ("origin_ctrl", "origin"):
            return "World"

        if short in ("pelvis_ctrl", "pelvis"):
            return "Pelvis"

        if short in ("neck2_ctrl", "neck_ctrl"):
            return "Neck"

        if short in ("spine5_tip_ctrl", "spine5_tip"):
            return "Spine5"

        if side:
            if short == f"{side}_clavicle_ctrl":
                return "Clav"

            if short == f"{side}_hand_ik_ctrl":
                return "Hand"

            if short == f"{side}_arm_pv_handclav_space".lower():
                return "Hand and Clav"

            if short == f"{side}_ankle_ik_ctrl":
                return "Foot"

            if short == f"{side}_leg_pv_foothip_space".lower():
                return "Foot And Hip"

        if short.endswith("_clavicle_ctrl"):
            return "Clav"

        if short.endswith("_hand_ik_ctrl"):
            return "Hand"

        if "_arm_pv_handclav_space" in short:
            return "Hand and Clav"

        if short.endswith("_ankle_ik_ctrl"):
            return "Foot"

        if "_leg_pv_foothip_space" in short:
            return "Foot And Hip"

        pretty = short_name(target)
        if pretty.endswith("_ctrl"):
            pretty = pretty[:-5]
        return pretty.replace("_", " ").strip()

    return [label_for_target(t) for t in targets]


def _swap_first_lr_character(name):
    """
        Swaps the first character of the name if it is l, r, L, or R.
    :param name: joint or node name
    :return: str
    """
    if not name:
        return name

    first = name[0]
    if first == "l":
        return "r" + name[1:]
    elif first == "r":
        return "l" + name[1:]
    elif first == "L":
        return "R" + name[1:]
    elif first == "R":
        return "L" + name[1:]

    return name


def get_ctrl_shape_cvs(ctrl):
    """
        Gets ctrl shape cvs.
    :param ctrl: ctrl
    :return: result
    """
    data = {}

    shapes = cmds.listRelatives(ctrl, s=True, ni=True, fullPath=True) or []
    for shape in shapes:
        if cmds.nodeType(shape) != "nurbsCurve":
            continue

        short_shape = shape.split("|")[-1]
        cvs = cmds.ls(f"{shape}.cv[*]", fl=True) or []

        data[short_shape] = [
            cmds.xform(cv, q=True, os=True, t=True)
            for cv in cvs
        ]

    return data


def store_all_control_cv_positions(store_node=MODULE_STORE_NODE):
    """
        Store all control cv positions.
    :param store_node: store node
    :return: result
    """
    if not cmds.objExists(store_node):
        store_node = cmds.createNode("network", name=store_node)

    attr = "controlCvPositions"
    if not cmds.attributeQuery(attr, node=store_node, exists=True):
        cmds.addAttr(store_node, ln=attr, dt="string")

    ctrls = cmds.ls("*_ctrl", type="transform") or []
    data = {}

    for ctrl in ctrls:
        cv_data = get_ctrl_shape_cvs(ctrl)
        if cv_data:
            data[ctrl] = cv_data

    cmds.setAttr(f"{store_node}.{attr}", json.dumps(data), type="string")
    print(f"[CV Store] Stored CVs for {len(data)} controls.")
    return data


def restore_all_control_cv_positions(store_node=MODULE_STORE_NODE):
    """
        Restore all control cv positions.
    :param store_node: store node
    :return: result
    """
    attr = f"{store_node}.controlCvPositions"

    if not cmds.objExists(attr):
        print("[CV Restore] No stored control CV data found.")
        return {}

    raw = cmds.getAttr(attr)
    if not raw:
        return {}

    data = json.loads(raw)
    restored = {}

    for ctrl, shape_map in data.items():
        if not cmds.objExists(ctrl):
            continue

        shapes = cmds.listRelatives(ctrl, s=True, ni=True, fullPath=True) or []
        current_shapes = {
            s.split("|")[-1]: s
            for s in shapes
            if cmds.nodeType(s) == "nurbsCurve"
        }

        for shape_name, positions in shape_map.items():
            shape = current_shapes.get(shape_name)

            # fallback if rebuilt shape has different numbered suffix
            if not shape and len(current_shapes) == 1:
                shape = list(current_shapes.values())[0]

            if not shape:
                continue

            cvs = cmds.ls(f"{shape}.cv[*]", fl=True) or []
            if len(cvs) != len(positions):
                continue

            for cv, pos in zip(cvs, positions):
                cmds.xform(cv, os=True, t=pos)

            restored.setdefault(ctrl, []).append(shape_name)

    return restored


def _get_side_enum_map(joint):
    """
        Gets a name-to-index mapping dictionary for the 'side' attribute enum.
    :param joint: joint name to query
    :return: dict
    """
    enum_data = cmds.attributeQuery("side", node=joint, listEnum=True)
    if not enum_data:
        return {}

    enum_names = enum_data[0].split(":")
    return {name: i for i, name in enumerate(enum_names)}


def _flip_joint_label_side(joint):
    """
        Flips the joint label side attribute value from Left to Right or vice versa.
    :param joint: joint name to flip
    :return: None
    """
    if not cmds.attributeQuery("side", node=joint, exists=True):
        return

    enum_map = _get_side_enum_map(joint)
    if not enum_map:
        return

    current_value = cmds.getAttr(joint + ".side")
    left_value = enum_map.get("Left")
    right_value = enum_map.get("Right")

    if left_value is None or right_value is None:
        return

    if current_value == left_value:
        cmds.setAttr(joint + ".side", right_value)
    elif current_value == right_value:
        cmds.setAttr(joint + ".side", left_value)


def _get_joint_hierarchy(root_joint):
    """
        Returns all child joints under root_joint in hierarchical order.
    :param root_joint: root joint name
    :return: list[str]
    """
    joints = cmds.listRelatives(root_joint, ad=True, type="joint", fullPath=True) or []
    joints.append(cmds.ls(root_joint, long=True)[0])
    joints.reverse()
    return joints


def mirror_joint_yz_behavior_with_label_flip(root_joint=None, rename_first_char=True):
    """
        Mirror a joint chain across YZ using behavior mirroring.
        Then flip joint label Side from Left<->Right on the mirrored chain.
        Optionally swaps first character of the mirrored names: l/r/L/R.
    :param root_joint: root joint name to mirror; sl=True if None
    :param rename_first_char: whether to swap first character l/r
    :return: list[str]
    """

    if not root_joint:
        sel = cmds.ls(sl=True, type="joint", long=True)
        if not sel:
            cmds.error("Select a root joint or pass one in.")
        root_joint = sel[0]
    else:
        found = cmds.ls(root_joint, long=True, type="joint")
        if not found:
            cmds.error("Joint does not exist: {0}".format(root_joint))
        root_joint = found[0]

    original_chain = _get_joint_hierarchy(root_joint)

    mirrored_roots = cmds.mirrorJoint(
        root_joint,
        mirrorYZ=True,
        mirrorBehavior=True
    )

    if not mirrored_roots:
        return []

    mirrored_root = cmds.ls(mirrored_roots[0], long=True)[0]
    mirrored_chain = _get_joint_hierarchy(mirrored_root)

    if rename_first_char:
        # Rename bottom-up so parent path changes do not invalidate child paths
        for orig_joint, mirrored_joint in zip(reversed(original_chain), reversed(mirrored_chain)):
            if not cmds.objExists(mirrored_joint):
                continue

            orig_name = orig_joint.split("|")[-1]
            new_name = _swap_first_lr_character(orig_name)

            if new_name != mirrored_joint.split("|")[-1]:
                cmds.rename(mirrored_joint, new_name)

        # Rebuild hierarchy after renaming
        mirrored_chain = _get_joint_hierarchy(mirrored_root.split("|")[-1])

    for joint in mirrored_chain:
        _flip_joint_label_side(joint)

    return mirrored_chain


def create_leg_space_switches(side, body_joint_map=None):
    """
        Builds space switches (including composite spaces) for the Leg module.
    :param side: left or right side (l/r)
    :param body_joint_map: optional body joint mapping dictionary
    :return: None
    """
    pv_ctrl = side + "_knee_pv_ctrl"
    pv_grp = pv_ctrl + "_pad"
    hip_ctrl = "pelvis_ctrl"
    origin_ctrl = "origin_ctrl"

    # Resolve hip_ctrl dynamically
    hip_jnt = None
    if body_joint_map:
        hip_jnt = (body_joint_map.get("Hips") or {}).get("joint")
    if hip_jnt:
        base_name = hip_jnt.replace('_jnt', '').split(':')[-1]
        candidates_hip = [
            f"{hip_jnt.replace('_jnt', '')}_ctrl",
            f"{base_name}_ctrl",
            "pelvis_ctrl"
        ]
        for c in candidates_hip:
            if cmds.objExists(c):
                hip_ctrl = c
                break

    # Resolve origin_ctrl dynamically
    root_jnt = None
    if body_joint_map:
        root_jnt = (body_joint_map.get("Root") or {}).get("joint")
    if root_jnt:
        base_name = root_jnt.replace('_jnt', '').split(':')[-1]
        candidates_root = [
            f"{root_jnt.replace('_jnt', '')}_ctrl",
            f"{base_name}_ctrl",
            "origin_ctrl"
        ]
        for c in candidates_root:
            if cmds.objExists(c):
                origin_ctrl = c
                break

    module_label = "Left Leg" if side == "l" else "Right Leg"
    meta = load_module_metadata(module_label)
    custom_sw = meta.get("custom_space_switches", {}) if meta else {}

    foot_ctrl = side + "_ankle_ik_ctrl"
    foot_jnt = None
    if body_joint_map:
        foot_jnt = (body_joint_map.get("LeftFoot" if side == "l" else "RightFoot") or {}).get("joint")
    elif meta and "joints" in meta and len(meta["joints"]) >= 3:
        foot_jnt = meta["joints"][2]

    if foot_jnt:
        base_name = foot_jnt.replace('_jnt', '').split(':')[-1]
        candidates = [
            f"{foot_jnt.replace('_jnt', '')}_ik_ctrl",
            f"{base_name}_ik_ctrl",
            side + "_ankle_ik_ctrl"
        ]
        for c in candidates:
            if cmds.objExists(c):
                foot_ctrl = c
                break

    # Knee PV space switch & composite space
    if cmds.objExists(pv_ctrl) and cmds.objExists(pv_grp) and cmds.objExists(foot_ctrl):
        dnt = "Do_Not_Touch"
        if not cmds.objExists(dnt):
            dnt = cmds.group(em=True, name=dnt)
            cmds.setAttr(dnt + ".visibility", 0)

        foot_hip_space = create_composite_space(
            name=side + "_leg_pv_footHip_space",
            parents=[foot_ctrl, hip_ctrl],
            match_to=pv_grp,
            parent_node=dnt
        )

        pv_targets = custom_sw.get(pv_ctrl)
        if pv_targets is None:
            pv_targets = [hip_ctrl, origin_ctrl, foot_ctrl, foot_hip_space]
        else:
            pv_targets = [foot_hip_space if "footHip" in t or t == "COMPOSITE" else t for t in pv_targets]

        pv_targets = [t for t in pv_targets if cmds.objExists(t)]
        if pv_targets:
            enum_names = build_enum_names_for_space_targets(pv_targets, side=side)
            create_space_switch(
                driven=pv_ctrl,
                targets=pv_targets,
                attr_name="space",
                enum_names=enum_names
            )

    # FK Thigh space switch
    fk_thigh = side + '_thigh_fk_ctrl'
    if cmds.objExists(fk_thigh):
        fk_targets = custom_sw.get(fk_thigh)
        if fk_targets is None:
            fk_targets = ['pelvis_ctrl', 'origin_ctrl']
        fk_targets = [t for t in fk_targets if cmds.objExists(t)]
        if fk_targets:
            enum_names = build_enum_names_for_space_targets(fk_targets, side=side)
            create_space_switch(
                fk_thigh,
                fk_targets,
                attr_name="space",
                dup_suffix="_spaceTarget",
                constraint_type="orient",
                enum_names=enum_names
            )

    # Ankle IK space switches
    for each in [side + '_ankle_ik_ctrl', side + '_ankle_ikHandle_ctrl']:
        if cmds.objExists(each):
            ik_targets = custom_sw.get(side + '_ankle_ik_ctrl') or custom_sw.get(each)
            if ik_targets is None:
                ik_targets = ['pelvis_ctrl', 'origin_ctrl']
            ik_targets = [t for t in ik_targets if cmds.objExists(t)]
            if ik_targets:
                enum_names = build_enum_names_for_space_targets(ik_targets, side=side)
                create_space_switch(
                    each,
                    ik_targets,
                    attr_name="space",
                    dup_suffix="_spaceTarget",
                    constraint_type="parent",
                    enum_names=enum_names
                )


def create_arm_space_switches(side, body_joint_map=None):
    """
        Builds space switches (including composite spaces) for the Arm module.
    :param side: left or right side (l/r)
    :param body_joint_map: optional body joint mapping dictionary
    :return: None
    """
    arm_pv_ctrl = side + "_lowerarm_pv_ctrl"
    arm_pv_grp = arm_pv_ctrl + "_pad"
    clav_ctrl = side + "_clavicle_ctrl"

    # Resolve clav_ctrl dynamically
    clav_jnt = None
    if body_joint_map:
        clav_jnt = (body_joint_map.get("LeftShoulder" if side == "l" else "RightShoulder") or {}).get("joint")
    if clav_jnt:
        base_name = clav_jnt.replace('_jnt', '').split(':')[-1]
        candidates_clav = [
            f"{clav_jnt.replace('_jnt', '')}_ctrl",
            f"{base_name}_ctrl",
            f"{side}_clavicle_ctrl"
        ]
        for c in candidates_clav:
            if cmds.objExists(c):
                clav_ctrl = c
                break

    module_label = "Left Arm" if side == "l" else "Right Arm"
    meta = load_module_metadata(module_label)
    custom_sw = meta.get("custom_space_switches", {}) if meta else {}

    hand_ctrl = side + "_hand_ik_ctrl"
    hand_jnt = None
    if body_joint_map:
        hand_jnt = (body_joint_map.get("LeftHand" if side == "l" else "RightHand") or {}).get("joint")
    elif meta and "joints" in meta and len(meta["joints"]) >= 3:
        hand_jnt = meta["joints"][2]

    if hand_jnt:
        base_name = hand_jnt.replace('_jnt', '').split(':')[-1]
        candidates = [
            f"{hand_jnt.replace('_jnt', '')}_ik_ctrl",
            f"{base_name}_ik_ctrl",
            f"{side}_arm_ik_ctrl",
            side + "_hand_ik_ctrl"
        ]
        for c in candidates:
            if cmds.objExists(c):
                hand_ctrl = c
                break

    # Lowerarm PV space switch & composite space
    if cmds.objExists(arm_pv_ctrl) and cmds.objExists(arm_pv_grp) and cmds.objExists(clav_ctrl) and cmds.objExists(
            hand_ctrl):
        dnt = "Do_Not_Touch"
        if not cmds.objExists(dnt):
            dnt = cmds.group(em=True, name=dnt)
            cmds.setAttr(dnt + ".visibility", 0)

        hand_clav_space = create_composite_space(
            name=side + "_arm_pv_handClav_space",
            parents=[hand_ctrl, clav_ctrl],
            match_to=arm_pv_grp,
            parent_node=dnt
        )

        pv_targets = custom_sw.get(arm_pv_ctrl)
        if pv_targets is None:
            pv_targets = [clav_ctrl, hand_clav_space, "pelvis_ctrl", "origin_ctrl"]
        else:
            pv_targets = [hand_clav_space if "handClav" in t or t == "COMPOSITE" else t for t in pv_targets]
        pv_targets = [t for t in pv_targets if cmds.objExists(t)]

        if pv_targets:
            enum_names = build_enum_names_for_space_targets(pv_targets, side=side)
            create_space_switch(
                driven=arm_pv_ctrl,
                targets=pv_targets,
                attr_name="space",
                enum_names=enum_names
            )

    # FK Upperarm space switch
    fk_upper = side + '_upperarm_fk_ctrl'
    if cmds.objExists(fk_upper) and cmds.objExists(side + '_clavicle_ctrl'):
        fk_targets = custom_sw.get(fk_upper)
        if fk_targets is None:
            fk_targets = [side + '_clavicle_ctrl', 'pelvis_ctrl', 'origin_ctrl']
        fk_targets = [t for t in fk_targets if cmds.objExists(t)]
        if fk_targets:
            enum_names = build_enum_names_for_space_targets(fk_targets, side=side)
            create_space_switch(
                fk_upper,
                fk_targets,
                attr_name="space",
                dup_suffix="_spaceTarget",
                constraint_type="orient",
                enum_names=enum_names
            )

    # Hand IK space switches
    for each in [side + '_hand_ik_ctrl', side + '_hand_ikHandle_ctrl']:
        if cmds.objExists(each) and cmds.objExists(side + '_clavicle_ctrl'):
            ik_targets = custom_sw.get(side + '_hand_ik_ctrl') or custom_sw.get(each)
            if ik_targets is None:
                ik_targets = [side + '_clavicle_ctrl', 'spine5_Tip_ctrl', 'pelvis_ctrl', 'origin_ctrl']
            ik_targets = [t for t in ik_targets if cmds.objExists(t)]
            if ik_targets:
                enum_names = build_enum_names_for_space_targets(ik_targets, side=side)
                create_space_switch(
                    each,
                    ik_targets,
                    attr_name="space",
                    dup_suffix="_spaceTarget",
                    constraint_type="parent",
                    enum_names=enum_names
                )
    # Ensure the hand IK joint is orient-constrained to the hand IK control
    hand_ik_jnt = f"{side}_hand_ik"
    if meta and "joints" in meta and len(meta["joints"]) >= 3:
        hand_jnt = meta["joints"][2]
        if hand_jnt:
            base_name = hand_jnt.replace('_jnt', '').split(':')[-1]
            candidates_ik = [
                f"{hand_jnt.replace('_jnt', '')}_ik",
                f"{base_name}_ik",
                f"{side}_hand_ik"
            ]
            for c in candidates_ik:
                if cmds.objExists(c):
                    hand_ik_jnt = c
                    break

    if cmds.objExists(hand_ctrl) and cmds.objExists(hand_ik_jnt):
        has_con = False
        con_nodes = cmds.listConnections(hand_ik_jnt, type="orientConstraint") or []
        for con in con_nodes:
            targets = cmds.orientConstraint(con, q=True, targetList=True) or []
            if hand_ctrl in targets:
                has_con = True
                break
        if not has_con:
            oc = cmds.orientConstraint(hand_ctrl, hand_ik_jnt, mo=True)[0]
            cmds.setAttr(f"{oc}.interpType", 2)


def create_rig_space_switches(side):
    """
        Builds the base space switches for both Leg and Arm modules on this side.
    :param side: left or right side (l/r)
    :return: None
    """
    create_leg_space_switches(side)
    create_arm_space_switches(side)


def create_eye_aim_setup(
        left_eye_joint="l_eye",
        right_eye_joint="r_eye",
        aim_distance=25,
        head_ctrl="head1_ctrl"
):
    """
        Creates a standard left/right eye aim setup with a shared center aim control.
    :param left_eye_joint: left eye joint name
    :param right_eye_joint: right eye joint name
    :param aim_distance: local aim control distance offset
    :param head_ctrl: head parent control name
    :return: dict
    """

    for jnt in (left_eye_joint, right_eye_joint):
        if not cmds.objExists(jnt):
            raise RuntimeError(f"Eye joint does not exist: {jnt}")

    created = {}

    l_eye_ctrl_dict = create_joint_controls([left_eye_joint], control_shape="circle", root_parent=head_ctrl)
    r_eye_ctrl_dict = create_joint_controls([right_eye_joint], control_shape="circle", root_parent=head_ctrl)

    def create_eye_aim(joint, side):
        # Aim transform
        """
            Creates eye aim.
        :param joint: joint
        :param side: side
        :return: result
        """
        aim_xform = cmds.createNode(
            "transform",
            name=f"{side}_eye_aim"
        )

        # Match joint
        cmds.delete(cmds.pointConstraint(joint, aim_xform, mo=False))

        # Move forward in local Z
        cmds.move(0, 0, aim_distance, aim_xform, r=True, os=True)

        aim_ctrl = create_joint_controls([aim_xform], control_shape="circle", root_parent=head_ctrl)

        return aim_xform, aim_ctrl

    l_aim_xform, l_aim_ctrl = create_eye_aim(left_eye_joint, "l")
    r_aim_xform, r_aim_ctrl = create_eye_aim(right_eye_joint, "r")

    cmds.aimConstraint(
        l_aim_ctrl[0]["ctrl"],
        l_eye_ctrl_dict[0]["pad"],
        aimVector=(0, 0, 1),
        upVector=(0, 1, 0),
        worldUpType="objectrotation",
        worldUpObject=head_ctrl,
        worldUpVector=(0, 1, 0),
        mo=True
    )
    cmds.aimConstraint(
        r_aim_ctrl[0]["ctrl"],
        r_eye_ctrl_dict[0]["pad"],
        aimVector=(0, 0, 1),
        upVector=(0, -1, 0),
        worldUpType="objectrotation",
        worldUpObject=head_ctrl,
        worldUpVector=(0, 1, 0),
        mo=True
    )
    created["l_eye_aim_xform"] = l_aim_xform
    created["r_eye_aim_xform"] = r_aim_xform
    created["l_eye_aim_ctrl"] = l_eye_ctrl_dict[0]["ctrl"]
    created["r_eye_aim_ctrl"] = r_eye_ctrl_dict[0]["ctrl"]

    center_aim = cmds.createNode(
        "transform",
        name="eye_aim"
    )

    cmds.delete(cmds.pointConstraint(
        l_aim_xform,
        r_aim_xform,
        center_aim,
        mo=False
    ))

    created["eye_aim"] = center_aim
    eye_ctrl_dict = create_joint_controls(["eye_aim"], control_shape="circle", root_parent=head_ctrl)
    cmds.parent(l_aim_ctrl[0]["pad"], r_aim_ctrl[0]["pad"], eye_ctrl_dict[0]["ctrl"])

    r_eye_ctrl = r_eye_ctrl_dict[0]["ctrl"]
    l_eye_ctrl = l_eye_ctrl_dict[0]["ctrl"]
    new_name = strip_ctrl_shape_and_rename(r_eye_ctrl)
    new_name1 = strip_ctrl_shape_and_rename(l_eye_ctrl)
    cmds.delete([l_aim_xform, r_aim_xform, center_aim])

    return created


def strip_ctrl_shape_and_rename(ctrl):
    """
    Delete all shapes under the transform and rename it.

    Args:
        ctrl (str): Control node name to process.

    Returns:
        str: The new node name.
    :param ctrl: ctrl
    :return: result
    """
    if not cmds.objExists(ctrl):
        raise RuntimeError(f"Control does not exist: {ctrl}")

    # Delete all shapes under the transform
    shapes = cmds.listRelatives(ctrl, s=True, ni=False, f=True) or []
    if shapes:
        cmds.delete(shapes)

    # Rename transform: replace "_ctrl" with "1"
    if "_ctrl" in ctrl:
        new_name = ctrl.replace("_ctrl", "1")
    else:
        new_name = f"{ctrl}1"

    new_name = cmds.rename(ctrl, new_name)
    return new_name


def setup_jaw_lip_driver(jaw_ctrl, lip_driver_ctrls, lip_ctrl_dict, head_ctrl="head1_ctrl"):
    """
    Initial setup for driving mouth and lips via the jaw control.

    Args:
        jaw_ctrl (str): Name of the jaw control.
        lip_driver_ctrls (list[str]): List of driver controls for the lips.
        lip_ctrl_dict (dict): Dictionary mapping joints to lip controls.
        head_ctrl (str): Name of the head control.

    Returns:
        None
    :param jaw_ctrl: jaw ctrl
    :param lip_driver_ctrls: list of lip driver ctrls
    :param lip_ctrl_dict: mapping for lip ctrl dict
    :param head_ctrl: head ctrl
    :return: result
    """

    if not cmds.objExists(jaw_ctrl):
        raise RuntimeError(f"Jaw control does not exist: {jaw_ctrl}")

    def add_attr(attr, **kwargs):
        """
            Adds attr.
        :param attr: attr
        :param kwargs: list of kwargs
        :return:
        """
        if not cmds.attributeQuery(attr, node=jaw_ctrl, exists=True):
            cmds.addAttr(jaw_ctrl, longName=attr, **kwargs)
            cmds.setAttr(f"{jaw_ctrl}.{attr}", e=True, keyable=True)

    add_attr("jawOpen", at="double", min=0, max=1, dv=0)
    add_attr("lipShut", at="double", min=0, max=1, dv=0)
    add_attr("lipSubControls", at="bool", dv=0)

    for jnt in lip_ctrl_dict.keys():
        lip_pad = lip_ctrl_dict[jnt]
        _connect_attr_once(jaw_ctrl + ".lipSubControls", lip_pad + '.visibility', force=True)
    jaw_pad = jaw_ctrl + "_sdk_pad"
    _clear_sdk_anim_curves([f"{jaw_pad}.rotateZ"])
    cmds.setDrivenKeyframe(
        f"{jaw_pad}.rotateZ",
        cd=f"{jaw_ctrl}.jawOpen",
        dv=0, v=0
    )
    cmds.setDrivenKeyframe(
        f"{jaw_pad}.rotateZ",
        cd=f"{jaw_ctrl}.jawOpen",
        dv=1, v=-31.923
    )
    upper_ctrl = lip_driver_ctrls[0]
    lower_ctrl = lip_driver_ctrls[1]
    l_corner_ctrl = lip_driver_ctrls[2]
    r_corner_ctrl = lip_driver_ctrls[3]

    for i, ctrl in enumerate(lip_driver_ctrls):
        pad = ctrl + "_pad"
        old_constraints = cmds.listRelatives(pad, children=True, type="parentConstraint") or []
        _safe_delete_nodes(old_constraints)
        upper_con = cmds.parentConstraint(
            [head_ctrl, jaw_ctrl],
            pad,
            mo=True
        )[0]
        cmds.setAttr(f"{upper_con}.interpType", 2)
        upper_weights = cmds.parentConstraint(upper_con, q=True, wal=True)

        head_short = head_ctrl.split("|")[-1].split(":")[-1]
        jaw_short = jaw_ctrl.split("|")[-1].split(":")[-1]
        upper_head_w = [w for w in upper_weights if head_short in w or head_short.replace("_ctrl", "") in w][0]
        upper_jaw_w = [w for w in upper_weights if jaw_short in w or jaw_short.replace("_ctrl", "") in w][0]
        jaw_attr = f"{jaw_ctrl}.lipShut"
        _clear_sdk_anim_curves([
            f"{upper_con}.{upper_head_w}",
            f"{upper_con}.{upper_jaw_w}",
        ])

        if i == 0:
            cmds.setAttr(f"{upper_con}.{upper_head_w}", 0)
            cmds.setAttr(f"{upper_con}.{upper_jaw_w}", 1)

            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_head_w}",
                cd=jaw_attr,
                dv=0, v=1
            )
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_head_w}",
                cd=jaw_attr,
                dv=1, v=1
            )

            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_jaw_w}",
                cd=jaw_attr,
                dv=0, v=0
            )
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_jaw_w}",
                cd=jaw_attr,
                dv=1, v=1
            )

        elif i == 1:
            cmds.setAttr(f"{upper_con}.{upper_head_w}", 1)
            cmds.setAttr(f"{upper_con}.{upper_jaw_w}", 1)

            # head comes in with jaw
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_head_w}",
                cd=jaw_attr,
                dv=0, v=0
            )
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_head_w}",
                cd=jaw_attr,
                dv=1, v=1
            )

            # jaw already on
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_jaw_w}",
                cd=jaw_attr,
                dv=0, v=1
            )
            cmds.setDrivenKeyframe(
                f"{upper_con}.{upper_jaw_w}",
                cd=jaw_attr,
                dv=1, v=1
            )

    temp_grp = cmds.group(em=True, name="lip_main")

    # Point constrain between upper & lower lips
    cmds.delete(cmds.pointConstraint(
        upper_ctrl,
        lower_ctrl,
        temp_grp,
        mo=False
    ))

    # Move forward in world Z by 2
    cmds.move(0, 0, 2, temp_grp, r=True, ws=True)

    main_ctrl_dict = create_joint_controls(
        [temp_grp],
        control_shape="circle",
        root_parent=head_ctrl,
        keep_constraint=False,
    )[0]
    main_ctrl = main_ctrl_dict["ctrl"]
    cmds.delete(temp_grp)
    temp_grp = ""
    main_con = cmds.parentConstraint(head_ctrl, jaw_ctrl, main_ctrl_dict["pad"], mo=True)[0]
    cmds.setAttr(f"{main_con}.interpType", 2)
    for each in [upper_ctrl, lower_ctrl]:
        sdk_pad = each + "_sdk_pad"
        _connect_attr_once(f"{main_ctrl}.translate", f"{sdk_pad}.translate", force=True)
        _connect_attr_once(f"{main_ctrl}.rotate", f"{sdk_pad}.rotate", force=True)

    for each in [l_corner_ctrl, r_corner_ctrl]:
        sdk_pad = f"{each}_sdk_pad"

        # Names
        parent_grp = f"{sdk_pad}_world_grp"
        child_grp = f"{sdk_pad}_world_drv"

        # Create groups if needed
        if not cmds.objExists(parent_grp):
            parent_grp = cmds.createNode("transform", name=parent_grp)

        if not cmds.objExists(child_grp):
            child_grp = cmds.createNode("transform", name=child_grp)

        cmds.parent(child_grp, parent_grp)
        cmds.parent(parent_grp, each + "_pad")
        cmds.delete(cmds.pointConstraint(sdk_pad, parent_grp))
        cmds.delete(cmds.pointConstraint(sdk_pad, child_grp))

        cmds.parent(sdk_pad, child_grp)

        cmds.connectAttr(f"{main_ctrl}.translate", f"{child_grp}.translate", f=True)
        cmds.connectAttr(f"{main_ctrl}.rotate", f"{child_grp}.rotate", f=True)

    return {
        "jaw_ctrl": jaw_ctrl,
        "upper_lip_ctrl": upper_ctrl,
        "lower_lip_ctrl": lower_ctrl,
        "main_ctrl": main_ctrl,
        "temp_group": temp_grp
    }


def create_twist_driver(driver_bone="l_thigh_driver",
                        child_bone="l_knee_driver",
                        parent="hipswing_ctrl",
                        surface="l_thigh_surface"):
    """
    Creates a twist driver setup for a limb segment.

    Args:
        driver_bone (str): Name of the driver bone.
        child_bone (str): Name of the child bone.
        parent (str): Parent control or group name.
        surface (str): Name of the lofted surface.

    Returns:
        str: Name of the created twist driver joint.
    :param driver_bone: driver bone
    :param child_bone: child bone
    :param parent: parent
    :param surface: surface
    :return: result
    """
    twist_bone = cmds.duplicate(driver_bone, name=driver_bone.replace("driver", "twist_driver"))[0]
    children = cmds.listRelatives(twist_bone, c=True, f=True) or []
    if children:
        cmds.delete(children)

    # duplicate() normally leaves the joint beside the source hierarchy. Honor
    # the requested rig parent explicitly (notably knee_twist_driver beneath
    # knee_driver) while preserving the duplicate's world-space pose.
    if parent and cmds.objExists(parent):
        desired_matches = cmds.ls(parent, long=True) or []
        twist_matches = cmds.ls(twist_bone, long=True) or []
        if len(desired_matches) != 1 or len(twist_matches) != 1:
            raise RuntimeError(
                "Could not uniquely resolve twist parenting: twist={!r}, parent={!r}".format(
                    twist_matches, desired_matches,
                )
            )
        desired_parent = desired_matches[0]
        twist_bone = twist_matches[0]
        current_parent = cmds.listRelatives(twist_bone, parent=True, fullPath=True) or []
        if not current_parent or current_parent[0] != desired_parent:
            twist_bone = cmds.parent(twist_bone, desired_parent, absolute=True)[0]

    world_up_object = parent
    if "lower" in driver_bone or "knee" in driver_bone:
        world_up_object = child_bone
    cmds.pointConstraint(child_bone, twist_bone, mo=False)

    x_val = 1
    if "knee" in driver_bone and driver_bone[0] == "l":
        x_val = -1

    if "thigh" in driver_bone:
        wuv = (1, 0, 0)
    else:
        wuv = (0, 1, 0)

    cmds.aimConstraint(driver_bone, twist_bone,
                       aimVector=(x_val, 0, 0),
                       upVector=(0, 1, 0),
                       worldUpType="objectrotation",
                       worldUpObject=world_up_object,
                       worldUpVector=wuv,
                       mo=True)

    if surface and cmds.objExists(surface):
        skin, surface = _bind_surface_to_joints(
            surface,
            [twist_bone, driver_bone],
            tsb=True,
            bindMethod=0,
            skinMethod=0,
            normalizeWeights=1,
        )

        num_cvs = 4

        for i in range(num_cvs):
            # Proper string formatting for i
            cvs = cmds.ls(f"{surface}.cv[0:3][{i}]", flatten=True)
            if 'lowerarm' not in driver_bone:
                weight_twist = 1.0 - (i / float(num_cvs - 1))
                weight_driver = 1.0 - weight_twist
            else:
                weight_driver = 1.0 - (i / float(num_cvs - 1))
                weight_twist = 1.0 - weight_driver

            for cv in cvs:
                cmds.skinPercent(
                    skin,
                    cv,
                    transformValue=[
                        (twist_bone, weight_twist),
                        (driver_bone, weight_driver)
                    ]
                )

    return twist_bone
