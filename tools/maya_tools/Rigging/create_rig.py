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

    fk_chain = cmds.duplicate(top_joint, rc=True)
    ik_chain = cmds.duplicate(top_joint, rc=True)
    driver_chain = cmds.duplicate(top_joint, rc=True)
    cmds.parent(fk_chain[0], root_parent)
    cmds.parent(ik_chain[0], root_parent)
    cmds.parent(driver_chain[0], root_parent)

    def rename_chain(chain, suffix, count):
        """
            Rename chain.
        :param chain: chain
        :param suffix: suffix
        :param count: count
        :return: result
        """
        new_chain = []
        for jnt in chain[:count]:
            base = jnt.split("|")[-1]
            base = re.sub(r'\d+$', '', base)
            base = base.replace("_jnt", "")
            new_name = f"{base}_{suffix}"
            if cmds.objExists(new_name):
                cmds.delete(new_name)
            new_chain.append(cmds.rename(jnt, new_name))

        # remove unexpected children after renaming using long names
        expected = set(cmds.ls(new_chain, long=True) or [])
        for jnt in new_chain:
            kids = cmds.listRelatives(jnt, c=True, type="joint", fullPath=True) or []
            for kid in kids:
                if kid not in expected:
                    cmds.delete(kid)

        return new_chain

    fk_joints = rename_chain(fk_chain, "fk", joint_count)
    ik_joints = rename_chain(ik_chain, "ik", joint_count)
    driver_joints = rename_chain(driver_chain, "driver", joint_count)

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

    print("✅ IK/FK limb created (joint-count driven).")

    return {
        "fk_chain": fk_joints,
        "ik_chain": ik_joints,
        "driver_chain": driver_joints,
        "fk_controls": fk_ctrls,
        "ik_ctrl": ik_ctrl,
        "pv_ctrl": pv_ctrl,
        "ik_handle": ik_handle,
        "blend_constraints": blend_constraints
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
    loft_surf = cmds.loft(curves_to_loft, ch=True, u=True, c=False, ar=True, d=deg, ss=1, rn=False, po=0, name=name)[0]

    # Delete the curves if you want to clean up
    cmds.delete(curves_to_loft)

    min_u = cmds.getAttr(loft_surf + ".minValueU")
    max_u = cmds.getAttr(loft_surf + ".maxValueU")
    min_v = cmds.getAttr(loft_surf + ".minValueV")
    max_v = cmds.getAttr(loft_surf + ".maxValueV")

    follicle_joints = []

    for jnt in joint_chain:
        pos = cmds.xform(jnt, q=True, ws=True, t=True)

        cps = cmds.createNode("closestPointOnSurface")
        cmds.connectAttr(loft_surf + ".local", cps + ".inputSurface", f=True)
        cmds.setAttr(cps + ".inPosition", *pos)

        u_real = cmds.getAttr(cps + ".parameterU")
        v_real = cmds.getAttr(cps + ".parameterV")

        cmds.delete(cps)

        u_norm = (u_real - min_u) / (max_u - min_u)
        v_norm = (v_real - min_v) / (max_v - min_v)

        fol_shape = cmds.createNode("follicle", name=f"{name}_{jnt}_folShape")
        fol_tr = cmds.listRelatives(fol_shape, parent=True)[0]

        cmds.connectAttr(loft_surf + ".local", fol_shape + ".inputSurface", f=True)
        cmds.connectAttr(loft_surf + ".worldMatrix[0]", fol_shape + ".inputWorldMatrix", f=True)

        cmds.setAttr(fol_shape + ".parameterU", u_norm)
        cmds.setAttr(fol_shape + ".parameterV", v_norm)

        cmds.connectAttr(fol_shape + ".outTranslate", fol_tr + ".translate", f=True)
        cmds.connectAttr(fol_shape + ".outRotate", fol_tr + ".rotate", f=True)

        fol_joint = cmds.joint(name=f"{name}_{jnt}_folJoint")
        cmds.delete(cmds.parentConstraint(fol_tr, fol_joint, mo=False))

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
    loft_surf = cmds.loft(fwd_crv, bwd_crv, ch=True, u=True, c=False, ar=True, d=deg, ss=1, name=f"{name}_surf")[0]

    # Optional: delete curves
    cmds.delete(fwd_crv, bwd_crv)

    # Surface param ranges
    min_u = cmds.getAttr(loft_surf + ".minValueU")
    max_u = cmds.getAttr(loft_surf + ".maxValueU")
    min_v = cmds.getAttr(loft_surf + ".minValueV")
    max_v = cmds.getAttr(loft_surf + ".maxValueV")

    follicle_joints = []

    for jnt in joint_chain:
        pos = cmds.xform(jnt, q=True, ws=True, t=True)

        cps = cmds.createNode("closestPointOnSurface")
        cmds.connectAttr(loft_surf + ".local", cps + ".inputSurface")
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
        cmds.connectAttr(loft_surf + ".local", fol_shape + ".inputSurface", f=True)
        cmds.connectAttr(loft_surf + ".worldMatrix[0]", fol_shape + ".inputWorldMatrix", f=True)
        cmds.setAttr(fol_shape + ".parameterU", u_norm)
        cmds.setAttr(fol_shape + ".parameterV", v_norm)
        cmds.connectAttr(fol_shape + ".outTranslate", fol_tr + ".translate", f=True)
        cmds.connectAttr(fol_shape + ".outRotate", fol_tr + ".rotate", f=True)

        # Create a follicle joint at the follicle transform
        fol_joint = cmds.joint(name=f"{name}_{jnt}_folJoint")
        cmds.delete(cmds.parentConstraint(fol_tr, fol_joint, mo=False))

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
    if region == "eyelid":
        joint_chain = joint_chain + [temp_joint]
        side = temp_joint[0]
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)
    elif region == "mouth":
        joint_chain = joint_chain + [temp_joint]
        side = temp_joint[0]
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)
    else:
        loft_surf, follicle_joints = create_surface_from_joints_original(joint_chain, name=loft_name)

    group = cmds.group(loft_surf, n=loft_surf + "_surface_grp")
    if not cmds.objExists("Do_Not_Touch"):
        dnt = cmds.group(em=True, name="Do_Not_Touch")
        cmds.setAttr(dnt + ".visibility", 0)
    cmds.parent(group, "Do_Not_Touch")
    for fj in follicle_joints:
        parent = cmds.listRelatives(fj, p=1, ap=1)[0]
        cmds.parent(parent, group)
    if region == "eyelid" or region == "mouth":
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
    if region in ("eyelid", "mouth") and cmds.objExists(temp_joint):
        try:
            cmds.delete(temp_joint)
        except Exception:
            pass

    return loft_surf, follicle_joints, joint_to_ctrl


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
    is_twist_surface = (
            "twist" in loft_name.lower()
            or "twist" in region.lower()
            or region.lower() in ("upperarm", "lowerarm", "thigh", "knee")
            or any("_twist" in str(j).lower() for j in joint_list)
    )
    if region == "eyelid":
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

        # World parent
        cmds.parent(driver_joint, world=True)

        control_shape = "circle"
        if region == "mouth":
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
        cmds.parent(driver_joint, ctrl)
        driver_data[semantic] = {
            "joint": driver_joint,
            "ctrl": ctrl,
            "pad": pad
        }
        scale_ctrl_cvs_local(ctrl, [.5, .5, .5])
        driver_joints.append(driver_joint)

    if driver_joints:
        cmds.skinCluster(
            loft_surf,
            driver_joints,
            tsb=True,
            bindMethod=0,
            skinMethod=0,
            normalizeWeights=1
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
        root_parent=head_ctrl
    )[0]
    main_ctrl = main_ctrl_dict["ctrl"]
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

    if "lower" in driver_bone or "knee" in driver_bone:
        parent = child_bone
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
                       worldUpObject=parent,
                       worldUpVector=wuv,
                       mo=True)

    if surface and cmds.objExists(surface):
        skin = cmds.skinCluster(twist_bone, driver_bone, surface, toSelectedBones=True)[0]

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


def _mapped_existing_joint(mapping, slot):
    """
        Return a mapped joint only when it exists in the Maya scene.
    :param mapping: mapping for mapping
    :param slot: slot
    :return: result
    """
    if not mapping:
        return None

    data = mapping.get(slot, {})
    if isinstance(data, dict):
        joint = data.get("joint")
    elif isinstance(data, str):
        joint = data
    else:
        joint = None

    return joint if joint and cmds.objExists(joint) else None


def _mapped_existing_joints(mapping, slot):
    """
        Return only existing joints from a mapped multi-joint slot.
    :param mapping: mapping for mapping
    :param slot: slot
    :return: result
    """
    if not mapping:
        return []

    data = mapping.get(slot, {})
    if isinstance(data, dict):
        joints = data.get("joints", []) or []
    elif isinstance(data, (list, tuple)):
        joints = data
    else:
        joints = []

    return [joint for joint in joints if joint and cmds.objExists(joint)]


def _filter_existing_face_joint_map(face_joint_map):
    """
    Copy a face mapping while removing joints that do not exist.

    Missing single-joint slots become None. Missing joints are removed from
    multi-joint slots so modules never receive invalid scene nodes.
    :param face_joint_map: mapping for face joint map
    :return: result
    """
    filtered = {}

    for slot, data in (face_joint_map or {}).items():
        if isinstance(data, dict):
            clean = dict(data)

            if "joint" in clean:
                joint = clean.get("joint")
                clean["joint"] = joint if joint and cmds.objExists(joint) else None

            if "joints" in clean:
                clean["joints"] = [
                    joint for joint in (clean.get("joints") or [])
                    if joint and cmds.objExists(joint)
                ]

            filtered[slot] = clean
        elif isinstance(data, (list, tuple)):
            filtered[slot] = [
                joint for joint in data
                if joint and cmds.objExists(joint)
            ]
        elif isinstance(data, str):
            filtered[slot] = data if cmds.objExists(data) else None
        else:
            filtered[slot] = data

    return filtered


def hik_map_to_rig_args(body_joint_map, face_joint_map):
    """
    Translate body and face mappings into rig arguments.

    Only joints that exist in the scene are included. Face slots are read from
    face_joint_map rather than body_joint_map.
    :param body_joint_map: mapping for body joint map
    :param face_joint_map: mapping for face joint map
    :return: result
    """
    face_joint_map = _filter_existing_face_joint_map(face_joint_map)

    def body_j(slot):
        """
            Body j.
        :param slot: slot
        :return: result
        """
        return _mapped_existing_joint(body_joint_map, slot)

    def face_j(slot):
        """
            Face j.
        :param slot: slot
        :return: result
        """
        return _mapped_existing_joint(face_joint_map, slot)

    def toe_tip(toe_joint):
        """
            Toe tip.
        :param toe_joint: toe joint
        :return: result
        """
        if not toe_joint or not cmds.objExists(toe_joint):
            return None
        children = cmds.listRelatives(toe_joint, c=True, type="joint") or []
        return children[0] if children else None

    left_toe = body_j("LeftToeBase")
    right_toe = body_j("RightToeBase")

    arm_joints = [
        body_j("LeftArm"), body_j("RightArm"),
        body_j("LeftShoulder"), body_j("RightShoulder"),
        body_j("LeftForeArm"), body_j("RightForeArm"),
        body_j("LeftHand"), body_j("RightHand")
    ]

    leg_joints = {
        "l": [
            body_j("LeftUpLeg"),
            body_j("LeftLeg"),
            body_j("LeftFoot"),
            left_toe,
            toe_tip(left_toe),
        ],
        "r": [
            body_j("RightUpLeg"),
            body_j("RightLeg"),
            body_j("RightFoot"),
            right_toe,
            toe_tip(right_toe),
        ]
    }

    spine_joints = [
        joint for joint in (
            body_j("Spine"),
            body_j("Spine1"),
            body_j("Spine2"),
            body_j("Spine3"),
        )
        if joint
    ]

    root_joints = [
        joint for joint in (body_j("Reference"), body_j("Hips"))
        if joint
    ]

    body_dict = {
        "arm_joints": [joint for joint in arm_joints if joint],
        "leg_joints": leg_joints,
        "spine_joints": spine_joints,
        "root_joints": root_joints,
    }

    face_dict = {
        "brows": {
            "left": face_j("LeftBrow"),
            "right": face_j("RightBrow"),
        },
        "eyelids": {
            "left": {
                "outer": face_j("LeftEyeLidOuter"),
                "upper": face_j("LeftEyeLidUpper"),
                "inner": face_j("LeftEyeLidInner"),
                "lower": face_j("LeftEyeLidLower"),
            },
            "right": {
                "outer": face_j("RightEyeLidOuter"),
                "upper": face_j("RightEyeLidUpper"),
                "inner": face_j("RightEyeLidInner"),
                "lower": face_j("RightEyeLidLower"),
            },
        },
        "lips": {
            "chain": _mapped_existing_joints(face_joint_map, "LipChain"),
            "upper_center": face_j("UpperLipCenter"),
            "lower_center": face_j("LowerLipCenter"),
            "left_corner": face_j("LeftLipCorner"),
            "right_corner": face_j("RightLipCorner"),
        },
        "jaw": face_j("Jaw"),
        "tongue": {
            "chain": _mapped_existing_joints(face_joint_map, "TongueChain"),
        },
        "teeth": {
            "upper": face_j("UpperTeeth"),
            "lower": face_j("LowerTeeth"),
        },
        "other_face_joints": _mapped_existing_joints(
            face_joint_map,
            "OtherFaceJoints"
        ),
    }

    return [body_dict, face_dict]


def create_brow_main_setup(side, root_parent='head1_ctrl'):
    """
        Creates the main eyebrows setup, snapping it to the middle brow control.
    :param side: Left or right side (l/r)
    :param root_parent: Parent control node name
    :return: dict
    """

    if not side:
        cmds.error("A side value is required.")

    snap_target = side + "_brow3_ctrl"
    brow_main = side + "_brow_main"

    if not cmds.objExists(snap_target):
        cmds.error("Snap target does not exist: {0}".format(snap_target))

    if not cmds.objExists(root_parent):
        cmds.error("Root parent does not exist: {0}".format(root_parent))

    # Create transform if it does not already exist
    if cmds.objExists(brow_main):
        brow_main_transform = brow_main
    else:
        brow_main_transform = cmds.createNode("transform", name=brow_main)

    # Snap transform to brow3 ctrl
    tmp_constraint = cmds.parentConstraint(snap_target, brow_main_transform, mo=False)
    if tmp_constraint:
        cmds.delete(tmp_constraint)

    # Create control setup
    ctrl_data = create_joint_controls(
        [brow_main_transform],
        control_shape="circle",
        root_parent=root_parent,
        sub_ctrls=False,
        keep_constraint=True
    )

    if not ctrl_data or "ctrl" not in ctrl_data[0]:
        cmds.error("create_joint_controls did not return expected ctrl_data.")

    main_ctrl = ctrl_data[0]["ctrl"]

    # Scale cvs
    scale_ctrl_cvs_local(main_ctrl, [3, 3, 3])

    # Parent pads underneath the new main control
    child_nodes = []

    for i in range(1, 6):
        child_nodes.append("{0}_brow{1}_driver_pad".format(side, i))
    for i in range(1, 6):
        child_nodes.append("{0}_brow{1}_ctrl_pad".format(side, i))

    existing_children = [node for node in child_nodes if cmds.objExists(node)]
    missing_children = [node for node in child_nodes if not cmds.objExists(node)]

    if missing_children:
        cmds.warning(
            "Some brow nodes were not found and were skipped: {0}".format(", ".join(missing_children))
        )

    if existing_children:
        cmds.parent(existing_children, main_ctrl)
        for i in range(1, 6):
            driver_pad = "{0}_brow{1}_driver_pad".format(side, i)
            if cmds.objExists(driver_pad):
                cmds.setAttr(driver_pad + ".visibility", 0)

    return {
        "group": brow_main_transform,
        "ctrl_data": ctrl_data,
        "parent_target": main_ctrl
    }


def _safe_rename_hierarchy_tokens(root_node, replacements, delete_shapes_on_driver=True):
    """
        Rename an entire hierarchy by applying ordered token replacements to every node name, leaf-to-root.
    :param root_node: Root transform of hierarchy
    :param replacements: Ordered string replacements list of tuples
    :param delete_shapes_on_driver: Delete shapes under transforms containing 'driver'
    :return: dict
    """
    if not cmds.objExists(root_node):
        cmds.warning("Node does not exist, skipping: {0}".format(root_node))
        return {}

    # Gather all descendants + root as long names
    hierarchy = cmds.listRelatives(root_node, ad=True, fullPath=True) or []
    hierarchy.append(cmds.ls(root_node, long=True)[0])

    # Deepest first so parent renames do not invalidate child paths
    hierarchy.sort(key=lambda x: x.count("|"), reverse=True)

    rename_map = {}

    for old_long in hierarchy:
        if not cmds.objExists(old_long):
            continue

        short_name = old_long.split("|")[-1]
        new_name = short_name

        for old, new in replacements:
            new_name = new_name.replace(old, new)

        current_long = cmds.ls(old_long, long=True)
        if not current_long:
            continue
        current_long = current_long[0]

        final_name = current_long.split("|")[-1]

        if new_name != final_name:
            renamed = cmds.rename(current_long, new_name)
            rename_map[old_long] = renamed
            final_name = renamed
        else:
            rename_map[old_long] = final_name

        # Delete shapes for transforms renamed to driver
        if delete_shapes_on_driver and "driver" in final_name:
            current_long_after = cmds.ls(final_name, long=True) or cmds.ls(rename_map[old_long], long=True)
            if current_long_after:
                current_long_after = current_long_after[0]
                if cmds.nodeType(current_long_after) == "transform":
                    shapes = cmds.listRelatives(current_long_after, shapes=True, fullPath=True) or []
                    if shapes:
                        cmds.delete(shapes)

    return rename_map


def rename_brow_pad_hierarchies(side):
    """
    Rename these hierarchies for the given side:

    1. side_browX_ctrl_pad      -> side_browX_driver_pad
       and rename entire hierarchy ctrl -> driver

    2. side_browX_main_ctrl_pad -> side_browX_ctrl_pad
       and rename entire hierarchy main_ctrl -> ctrl

    Also deletes shapes on nodes renamed to 'driver'.

    Args:
        side (str): 'l' or 'r'

    Returns:
        dict: {
            "ctrl_to_driver": {pad_name: rename_map, ...},
            "main_ctrl_to_ctrl": {pad_name: rename_map, ...}
        }
    :param side: side
    :return: result
    """
    results = {
        "ctrl_to_driver": {},
        "main_ctrl_to_ctrl": {}
    }

    # Pass 1:
    # side_brow1_ctrl_pad -> side_brow1_driver_pad
    # hierarchy token rename: ctrl -> driver
    for i in range(1, 6):
        pad = "{0}_brow{1}_ctrl_pad".format(side, i)
        if cmds.objExists(pad):
            results["ctrl_to_driver"][pad] = _safe_rename_hierarchy_tokens(
                pad,
                replacements=[("ctrl", "driver")],
                delete_shapes_on_driver=True
            )

    for i in range(1, 6):
        pad = "{0}_brow{1}_main_ctrl_pad".format(side, i)
        if cmds.objExists(pad):
            results["main_ctrl_to_ctrl"][pad] = _safe_rename_hierarchy_tokens(
                pad,
                replacements=[("main_ctrl", "ctrl")],
                delete_shapes_on_driver=False
            )

    return results


def setup_secondary_face_constraints(face_joint_map=None, head_ctrl=None):
    """
        Setup secondary face constraints.
    :param face_joint_map: mapping for face joint map
    :param head_ctrl: head ctrl
    :return:
    """
    head_ctrl = head_ctrl or "head1_ctrl"

    l_co = "l_lip_corner1"
    r_co = "r_lip_corner1"

    if face_joint_map:
        l_co = face_joint_map.get("LeftLipCorner", {}).get("joint") or l_co
        r_co = face_joint_map.get("RightLipCorner", {}).get("joint") or r_co

    for side in ["l", "r"]:
        corner_base = l_co if side == "l" else r_co
        corner_ctrl = f"{corner_base}_main_ctrl"

        cheek_pad = f"{side}_inner_cheek_smile_ctrl_pad"
        if cmds.objExists(head_ctrl) and cmds.objExists(corner_ctrl) and cmds.objExists(cheek_pad):
            safe_constrain_two_parents(
                [cheek_pad],
                head_ctrl,
                corner_ctrl,
                parent1_value=0.5,
                parent2_value=3.0,
                maintain_offset=True
            )

        brow_main = f"{side}_brow_main_ctrl"

        brow5_pad = f"{side}_brow5_ctrl_pad"
        if cmds.objExists(head_ctrl) and cmds.objExists(brow_main) and cmds.objExists(brow5_pad):
            safe_constrain_two_parents(
                [brow5_pad],
                head_ctrl,
                brow_main,
                parent1_value=0.6666,
                parent2_value=0.3333,
                maintain_offset=True
            )

        brow4_pad = f"{side}_brow4_ctrl_pad"
        if cmds.objExists(head_ctrl) and cmds.objExists(brow_main) and cmds.objExists(brow4_pad):
            safe_constrain_two_parents(
                [brow4_pad],
                head_ctrl,
                brow_main,
                parent1_value=0.3333,
                parent2_value=0.6666,
                maintain_offset=True
            )


def safe_constrain_two_parents(controls, parent1, parent2, **kwargs):
    """
        Safe constrain two parents.
    :param controls: list of controls
    :param parent1: parent1
    :param parent2: parent2
    :param kwargs: list of kwargs
    :return:
    """
    existing_ctrls = [c for c in controls if cmds.objExists(c)]
    if existing_ctrls and cmds.objExists(parent1) and cmds.objExists(parent2):
        try:
            constrain_controls_to_two_parents(existing_ctrls, parent1, parent2, **kwargs)
        except Exception as e:
            print(f"[Warning] Failed to constrain {existing_ctrls} to {parent1} and {parent2}: {e}")


def create_full_rig(arm_joints=None, leg_joints=None, spine_joints=None, neck_joints=None, root_joints=None,
                    hip_swing="hipswing", face_joint_map=None, face_joints=None):
    """
        Builds the entire character rig by coordinating modular setup builders.
    :param arm_joints: list of mapped arm joints
    :param leg_joints: list or dict of mapped leg joints
    :param spine_joints: list of mapped spine joints
    :param neck_joints: list of mapped neck/head joints
    :param root_joints: list of mapped root/pelvis joints
    :param hip_swing: hipswing name or prefix
    :param face_joint_map: mapping dictionary for face joints
    :param face_joints: list of face joints
    :return: dict
    """
    face_joint_map = _filter_existing_face_joint_map(face_joint_map)

    # 1. T-Pose setup
    if not arm_joints and isinstance(leg_joints, dict):
        b_map = leg_joints
        def _get_j(slot):
            v = b_map.get(slot)
            if isinstance(v, dict):
                return v.get("joint")
            return v
        extracted_arm = [
            _get_j("LeftArm"), _get_j("RightArm"),
            _get_j("LeftShoulder"), _get_j("RightShoulder"),
            _get_j("LeftForeArm"), _get_j("RightForeArm"),
            _get_j("LeftHand"), _get_j("RightHand")
        ]
        if any(extracted_arm):
            arm_joints = extracted_arm

    if not arm_joints:
        arm_joints = ['l_upperarm', 'r_upperarm',
                      'l_clavicle', 'r_clavicle',
                      'l_lowerarm', 'r_lowerarm',
                      'l_hand', 'r_hand']

    arm_joints_valid = [j for j in arm_joints if j and cmds.objExists(j)]
    if len(arm_joints_valid) >= 8:
        setup_hik.set_t_pose(arm_joints_valid[0], arm_joints_valid[1], arm_joints_valid[2], arm_joints_valid[3],
                             arm_joints_valid[4], arm_joints_valid[5], arm_joints_valid[6], arm_joints_valid[7])
    elif arm_joints_valid:
        setup_hik.set_t_pose(*arm_joints)
    elif isinstance(leg_joints, dict):
        setup_hik.set_t_pose(joint_map=leg_joints)

    # Convert the inputs into unified joint maps for modules to read
    body_joint_map = {}
    if isinstance(leg_joints, dict):
        body_joint_map = leg_joints
    else:
        # Re-construct body_joint_map from arguments for backwards compatibility
        body_joint_map = {}
        if root_joints and len(root_joints) >= 2:
            body_joint_map["Root"] = {"joint": root_joints[0]}
            body_joint_map["Hips"] = {"joint": root_joints[1]}
        if spine_joints:
            for i, sj in enumerate(spine_joints):
                key = "Spine" if i == 0 else f"Spine{i}"
                body_joint_map[key] = {"joint": sj}
        if neck_joints:
            for i, nj in enumerate(neck_joints):
                if "neck" in nj.lower():
                    key = "Neck" if i == 0 else f"Neck{i}"
                    body_joint_map[key] = {"joint": nj}
                elif "head" in nj.lower():
                    body_joint_map["Head"] = {"joint": nj}
                elif "jaw" in nj.lower():
                    body_joint_map["Jaw"] = {"joint": nj}
        if arm_joints and len(arm_joints) >= 8:
            body_joint_map["LeftShoulder"] = {"joint": arm_joints[2]}
            body_joint_map["RightShoulder"] = {"joint": arm_joints[3]}
            body_joint_map["LeftArm"] = {"joint": arm_joints[0]}
            body_joint_map["RightArm"] = {"joint": arm_joints[1]}
            body_joint_map["LeftForeArm"] = {"joint": arm_joints[4]}
            body_joint_map["RightForeArm"] = {"joint": arm_joints[5]}
            body_joint_map["LeftHand"] = {"joint": arm_joints[6]}
            body_joint_map["RightHand"] = {"joint": arm_joints[7]}

    # Ensure face_joint_map is populated
    if not face_joint_map:
        face_joint_map = setup_hik.DEFAULT_FACE_JOINT_MAP
        if face_joints:
            face_joint_map["OtherFaceJoints"] = {"joints": face_joints}

    # 2. Build Root / Origin Module
    rig_root_module(body_joint_map)

    # 3. Build Pelvis / Hips Module
    rig_pelvis_module(body_joint_map)

    # 4. Build Spine Module
    rig_spine_module(body_joint_map)

    # 5. Build Neck Module
    rig_neck_module(body_joint_map)

    # 6. Build Head Module
    rig_head_module(body_joint_map, face_joint_map)

    # Build Clavicles
    rig_clavicle_module("l", body_joint_map)
    rig_clavicle_module("r", body_joint_map)

    # 7. Build Arms
    rig_arm_module("l", body_joint_map)
    rig_arm_module("r", body_joint_map)

    # 8. Build Legs
    rig_leg_module("l", body_joint_map)
    rig_leg_module("r", body_joint_map)
    # 9. Build Face modules
    head_joint = (body_joint_map.get("Head") or {}).get("joint") if body_joint_map else None
    if not head_joint or not cmds.objExists(head_joint):
        head_joint = "head1"
    head_ctrl = head_joint + "_ctrl" if cmds.objExists(head_joint) else "head1_ctrl"

    jaw_jnt = (face_joint_map.get("Jaw") or {}).get("joint") if face_joint_map else None
    if not jaw_jnt or not cmds.objExists(jaw_jnt):
        jaw_jnt = "jaw"
    jaw_ctrl = jaw_jnt + "_ctrl" if cmds.objExists(jaw_jnt) else "jaw_ctrl"

    rig_brows_module("l", face_joint_map, head_ctrl)
    rig_brows_module("r", face_joint_map, head_ctrl)

    # Mouth and lips
    rig_mouth_module(face_joint_map, head_ctrl, jaw_ctrl)

    # Eyes aim setup
    rig_eyes_module(face_joint_map, head_ctrl)

    # Eyelids parent to eye_ctrl
    rig_eyelids_module("l", face_joint_map, "l_eye1" if cmds.objExists("l_eye1") else head_ctrl)
    rig_eyelids_module("r", face_joint_map, "r_eye1" if cmds.objExists("r_eye1") else head_ctrl)
    # Tongue
    rig_tongue_module(face_joint_map, jaw_ctrl if cmds.objExists(jaw_ctrl) else head_ctrl)

    # Teeth
    rig_teeth_module(face_joint_map, head_ctrl, jaw_ctrl)

    # Other Face Joints
    rig_other_face_module(face_joint_map, head_ctrl, jaw_ctrl, jaw_jnt)

    if cmds.objExists(head_ctrl) and cmds.objExists(jaw_ctrl):
        safe_constrain_two_parents(
            ['r_lower_cheek_ctrl_pad', 'l_lower_cheek_ctrl_pad'],
            head_ctrl,
            jaw_ctrl,
            parent1_value=1.0,
            parent2_value=1.0,
            maintain_offset=True)
    if cmds.objExists(head_ctrl) and cmds.objExists('nose_upper_ctrl'):
        safe_constrain_two_parents(
            ['r_upper_nose_ctrl_pad', 'l_upper_nose_ctrl_pad'],
            head_ctrl,
            'nose_upper_ctrl',
            parent1_value=1.0,
            parent2_value=1.0,
            maintain_offset=True)

    l_co = face_joint_map.get("LeftLipCorner", {}).get("joint") or "l_lip_corner1"
    r_co = face_joint_map.get("RightLipCorner", {}).get("joint") or "r_lip_corner1"

    for side in "l", "r":
        corner_ctrl = (l_co if side == "l" else r_co) + "_main_ctrl"
        if cmds.objExists(head_ctrl) and cmds.objExists(corner_ctrl):
            safe_constrain_two_parents(
                [side + '_inner_cheek_smile_ctrl_pad'],
                head_ctrl,
                corner_ctrl,
                parent1_value=.5,
                parent2_value=3.0,
                maintain_offset=True)

        if cmds.objExists(head_ctrl) and cmds.objExists(side + '_brow_main_ctrl'):
            safe_constrain_two_parents(
                [side + '_brow5_ctrl_pad'],
                head_ctrl,
                side + '_brow_main_ctrl',
                parent1_value=.6666,
                parent2_value=.3333,
                maintain_offset=True)
            safe_constrain_two_parents(
                [side + '_brow4_ctrl_pad'],
                head_ctrl,
                side + '_brow_main_ctrl',
                parent1_value=.3333,
                parent2_value=.6666,
                maintain_offset=True)

    # 11. Restoring custom connections/space switches
    for module in [
        "Root / Origin", "Pelvis & Hips", "Spine", "Neck", "Head",
        "Left Arm", "Right Arm", "Left Leg", "Right Leg",
        "Brows (Left)", "Brows (Right)", "Eyes Aim", "Eyelids (Left)", "Eyelids (Right)",
        "Mouth & Lips", "Tongue", "Teeth", "Other Face Joints"
    ]:
        restore_rig_connections(module)

    # 12. Cleanup unused scaffold and temporary nodes
    delete_unused_scaffold_nodes()

    # 12. Import enum orders

    json_path = r"C:/temp/enum_orders.json"
    if os.path.exists(json_path):
        try:
            enum_attrs.import_enum_orders(json_path)
        except Exception as e:
            print(f"[Warning] Failed to import enum orders: {e}")


def remove_full_rig(body_joint_map, face_joint_map=None):
    """
        Removes all controls, rig nodes, and clears the Do_Not_Touch group.
    :param body_joint_map: body joint mapping dictionary
    :param face_joint_map: face joint mapping dictionary
    :return: None
    """

    def safe_run(func, *args, **kwargs):
        """
            Safe run.
        :param func: func
        :param args: list of args
        :param kwargs: list of kwargs
        :return:
        """
        try:
            func(*args, **kwargs)
        except Exception as e:
            print(f"[Warning] Teardown step {func.__name__} failed: {e}")

    # 1. Body modules
    safe_run(remove_arm_module, "l", body_joint_map)
    safe_run(remove_arm_module, "r", body_joint_map)
    safe_run(remove_clavicle_module, "l", body_joint_map)
    safe_run(remove_clavicle_module, "r", body_joint_map)
    safe_run(remove_leg_module, "l", body_joint_map)
    safe_run(remove_leg_module, "r", body_joint_map)
    safe_run(remove_head_module, body_joint_map)
    safe_run(remove_neck_module, body_joint_map)
    safe_run(remove_spine_module, body_joint_map)
    safe_run(remove_pelvis_module, body_joint_map)
    safe_run(remove_root_module, body_joint_map)

    # 2. Face modules
    safe_run(remove_brows_module, "l", face_joint_map)
    safe_run(remove_brows_module, "r", face_joint_map)
    safe_run(remove_eyelids_module, "l", face_joint_map)
    safe_run(remove_eyelids_module, "r", face_joint_map)
    safe_run(remove_mouth_module, face_joint_map)
    safe_run(remove_eyes_module, face_joint_map)
    safe_run(remove_teeth_module, face_joint_map)
    safe_run(remove_tongue_module, face_joint_map)
    safe_run(remove_other_face_module, face_joint_map)

    preserve_rfl_pivot_joints()

    # 3. Clean up the Do_Not_Touch group
    if cmds.objExists("Do_Not_Touch"):
        try:
            for child in cmds.listRelatives("Do_Not_Touch", children=True, fullPath=False) or []:
                if _is_rfl_pivot_joint(child):
                    cmds.parent(child, world=True)
                    continue
                cmds.delete(child)
            if not (cmds.listRelatives("Do_Not_Touch", children=True) or []):
                cmds.delete("Do_Not_Touch")
            else:
                cmds.setAttr("Do_Not_Touch.visibility", 0)
        except Exception as e:
            print(f"[Warning] Failed to delete Do_Not_Touch group: {e}")


def create_rig_from_mapping(body_joint_map, face_joint_map):
    """
        Runs create_full_rig using the mapped joints from HIK/Face mappings.
    :param body_joint_map: body joint mapping dictionary
    :param face_joint_map: face joint mapping dictionary
    :return: None
    """
    face_joint_map = _filter_existing_face_joint_map(face_joint_map)

    def j(slot):
        """
            J.
        :param slot: slot
        :return: result
        """
        joint = body_joint_map.get(slot, {}).get("joint")
        return joint if joint and cmds.objExists(joint) else None

    # Arm joints
    arm_joints = [
        j("LeftArm"), j("RightArm"),
        j("LeftShoulder"), j("RightShoulder"),
        j("LeftForeArm"), j("RightForeArm"),
        j("LeftHand"), j("RightHand")
    ]
    # Filter to only existing or non-empty strings
    arm_joints = [a for a in arm_joints if a and cmds.objExists(a)]

    # Spine joints
    spine_joints = [j("Spine"), j("Spine1"), j("Spine2"), j("Spine3")]
    spine_joints = [s for s in spine_joints if s and cmds.objExists(s)]

    # Root joints
    root_joints = [j("Reference"), j("Hips")]
    root_joints = [r for r in root_joints if r and cmds.objExists(r)]

    # Neck, Head, Jaw, Tongue joints for neck_joints
    neck_joints = []
    for key in sorted(body_joint_map.keys()):
        if key.startswith("Neck"):
            jnt = body_joint_map[key].get("joint")
            if jnt and cmds.objExists(jnt):
                neck_joints.append(jnt)

    if j("Head") and cmds.objExists(j("Head")):
        neck_joints.append(j("Head"))
    if j("Jaw") and cmds.objExists(j("Jaw")):
        neck_joints.append(j("Jaw"))

    tongue_chain = face_joint_map.get("TongueChain", {}).get("joints", [])
    for tj in tongue_chain:
        if tj and cmds.objExists(tj):
            neck_joints.append(tj)

    # Other face joints
    face_joints = face_joint_map.get("OtherFaceJoints", {}).get("joints", [])
    face_joints = [fj for fj in face_joints if fj and cmds.objExists(fj)]

    # Let's run create_full_rig with these arguments
    create_full_rig(
        arm_joints=arm_joints if arm_joints else None,
        leg_joints=body_joint_map,
        spine_joints=spine_joints if spine_joints else None,
        neck_joints=neck_joints if neck_joints else None,
        root_joints=root_joints if root_joints else None,
        face_joints=face_joints if face_joints else None,
        face_joint_map=face_joint_map
    )


def query_space_switches(driven):
    """
        Queries and returns any space switches driving 'driven' checking control and pad levels.
    :param driven: control node to query
    :return: list[dict]
    """
    if not cmds.objExists(driven):
        return []

    nodes_to_check = [driven]
    parents = cmds.listRelatives(driven, p=True)
    if parents:
        nodes_to_check.append(parents[0])
        grandparents = cmds.listRelatives(parents[0], p=True)
        if grandparents:
            nodes_to_check.append(grandparents[0])

    for suffix in ["_sdk_pad", "_pad"]:
        pattern = driven + suffix
        if cmds.objExists(pattern) and pattern not in nodes_to_check:
            nodes_to_check.append(pattern)

    switches = []
    seen_constraints = set()

    for node in nodes_to_check:
        constraints = cmds.listConnections(node, type="constraint") or []
        for con in list(set(constraints)):
            if con in seen_constraints:
                continue
            seen_constraints.add(con)

            con_type = cmds.objectType(con)
            if con_type not in ("parentConstraint", "orientConstraint"):
                continue
            ctype = "parent" if con_type == "parentConstraint" else "orient"

            targets = []
            try:
                con_targets = []
                if con_type == "parentConstraint":
                    con_targets = cmds.parentConstraint(con, q=True, targetList=True) or []
                elif con_type == "orientConstraint":
                    con_targets = cmds.orientConstraint(con, q=True, targetList=True) or []

                for ct in con_targets:
                    if ct.startswith(driven + "_") and "_spaceTarget" in ct:
                        p = cmds.listRelatives(ct, p=True)
                        if p and p[0] not in targets:
                            targets.append(p[0])
                    else:
                        # Direct transform targets (like composite spaces or plain target transforms)
                        shapes = cmds.listRelatives(ct, shapes=True, fullPath=True) or []
                        if not shapes:
                            if ct not in targets:
                                targets.append(ct)
            except Exception as e:
                print(f"[Warning] Failed to query constraint targetList: {e}")

            attr_name = "space"
            weight_conn = cmds.listConnections(con, type="animCurveUA") or []
            attr_from_driven = False
            for curve in weight_conn:
                plugs = cmds.listConnections(curve + ".input", plug=True) or []
                for plug in plugs:
                    if plug.startswith(driven + "."):
                        attr_name = plug.split(".")[-1]
                        attr_from_driven = True
                        break

            if not attr_from_driven or not cmds.attributeQuery(attr_name, node=driven, exists=True):
                continue

            # Query custom enum display names
            enum_names = []
            try:
                enum_str = cmds.attributeQuery(attr_name, node=driven, listEnum=True)
                if enum_str:
                    enum_names = [e.strip() for e in enum_str[0].split(":") if e.strip()]
            except Exception:
                pass

            target_enum_pairs = []
            for i, t in enumerate(targets):
                disp_name = enum_names[i] if i < len(enum_names) else t
                target_enum_pairs.append([t, disp_name])

            if targets:
                switches.append({
                    "driven": driven,
                    "target_enum_pairs": target_enum_pairs,
                    "attr_name": attr_name,
                    "constraint_type": ctype
                })

    return switches


def delete_unused_scaffold_nodes():
    """
    Finds and deletes any nodes in the scene whose names end in '_main'
    or contain '_temp'.
    """
    to_delete = []

    # 1. Gather nodes ending in '_main'
    for node in cmds.ls("*_main") or []:
        if cmds.objExists(node):
            nt = cmds.nodeType(node)
            if nt == "transform":
                shapes = cmds.listRelatives(node, shapes=True) or []
                if not shapes:
                    to_delete.append(node)
                    continue

            if nt in ("transform", "joint"):
                is_skinned = bool(cmds.listConnections(node, type="skinCluster"))
                is_constrained = bool(cmds.listConnections(node, type="constraint"))
                all_descendants = cmds.listRelatives(node, ad=True, fullPath=True) or []
                has_ctrl_descendants = any("_ctrl" in desc.lower() for desc in all_descendants)

                if not is_skinned and not is_constrained and not has_ctrl_descendants:
                    to_delete.append(node)

    # 2. Gather nodes containing '_temp'
    for node in cmds.ls("*_temp*") or []:
        if cmds.objExists(node):
            nt = cmds.nodeType(node)
            if nt == "transform":
                shapes = cmds.listRelatives(node, shapes=True) or []
                if not shapes:
                    to_delete.append(node)
                    continue

            if nt in ("transform", "joint"):
                is_skinned = bool(cmds.listConnections(node, type="skinCluster"))
                is_constrained = bool(cmds.listConnections(node, type="constraint"))
                all_descendants = cmds.listRelatives(node, ad=True, fullPath=True) or []
                has_ctrl_descendants = any("_ctrl" in desc.lower() for desc in all_descendants)

                if not is_skinned and not is_constrained and not has_ctrl_descendants:
                    to_delete.append(node)

    # Delete them
    if to_delete:
        cmds.delete(list(set(to_delete)))
        print(f"[cleanup] Deleted unused scaffold/temp nodes: {to_delete}")


def rig_brows_module(side, face_joint_map, parent_ctrl=None):
    """
        Builds the eyebrows setup with lofted surfaces and driver controls.
    :param side: left or right side (l/r)
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or "head1_ctrl"
    brow_joints = []
    if face_joint_map:
        side_prefix_title = "Left" if side == "l" else "Right"
        brow_joints = face_joint_map.get(f"{side_prefix_title}Brow", {}).get("joints", [])
    if not brow_joints:
        brow_joints = [f"{side}_brow{i}" for i in range(1, 6)]
    brow_joints = [bj for bj in brow_joints if cmds.objExists(bj)]

    if len(brow_joints) >= 2 and cmds.objExists(parent_ctrl):
        setup_surface_rig_with_drivers(
            brow_joints,
            loft_name=f"{side}_brow",
            offset=0.5,
            side=side,
            region="brow",
            driver_follicle_indices=list(range(len(brow_joints))),
            root_parent=parent_ctrl
        )
        brow_rename = rename_brow_pad_hierarchies(side)
        create_brow_main_setup(side, parent_ctrl)
    save_module_metadata(f"Brows ({'Left' if side == 'l' else 'Right'})", {
        "joints": brow_joints,
        "parent": parent_ctrl or "",
        "built": True
    })


def remove_brows_module(side, face_joint_map):
    """
        Removes all controls and constraints built for eyebrows.
    :param side: left or right side (l/r)
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    brow_joints = []
    if face_joint_map:
        side_prefix_title = "Left" if side == "l" else "Right"
        brow_joints = face_joint_map.get(f"{side_prefix_title}Brow", {}).get("joints", [])
    if not brow_joints:
        brow_joints = [f"{side}_brow{i}" for i in range(1, 6)]

    nodes_to_delete = [
        f"{side}_brow_surface",
        f"{side}_brow_follicles",
        f"{side}_brow_driver_pad",
        f"{side}_brow_main_ctrl_pad"
    ]
    for bj in brow_joints:
        nodes_to_delete.append(f"{bj}_ctrl_pad")

    module_id = f"Brows ({'Left' if side == 'l' else 'Right'})"
    return _delete_module_from_metadata(module_id, nodes_to_delete)


def rig_eyelids_module(side, face_joint_map, parent_ctrl=None):
    """
        Builds the eyelids setup with lofted surfaces and driver controls.
    :param side: left or right side (l/r)
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or (f"{side}_eye_ctrl" if cmds.objExists(f"{side}_eye_ctrl") else "head1_ctrl")
    eyelid_joints = []
    if face_joint_map:
        side_prefix_title = "Left" if side == "l" else "Right"
        eyelid_joints = face_joint_map.get(f"{side_prefix_title}Eyelid", {}).get("joints", [])
    if not eyelid_joints:
        eyelid_joints = [
            f"{side}_inner_eyelidTip",
            f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
            f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
            f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
            f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
            f"{side}_outer_eyelidTip",
            f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
            f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
            f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
        ]
    eyelid_joints = [ej for ej in eyelid_joints if cmds.objExists(ej)]

    top_pad = f"{side}_eye_ctrl_pad"

    static_root, static_nodes = duplicate_static_hierarchy(f"{side}_eye_ctrl_pad")

    eye_static = f"{side}_eye1_static"
    if cmds.objExists(eye_static):
        parent_ctrl = eye_static
    elif static_root and cmds.objExists(static_root):
        parent_ctrl = static_root
    else:
        parent_ctrl = "head1_ctrl"
        cmds.error(f"Static eye parent was not created for {side}. top_pad={top_pad}")
    if len(eyelid_joints) >= 8 and cmds.objExists(parent_ctrl):
        driver_indices = [0, 9, 6, 3, 12, 15, 18, 20]
        setup_surface_rig_with_drivers(
            eyelid_joints,
            loft_name=f"{side}_eyelid",
            region="eyelid",
            side=side,
            offset=0.5,
            driver_follicle_indices=driver_indices,
            root_parent=parent_ctrl
        )
    save_module_metadata(f"Eyelids ({'Left' if side == 'l' else 'Right'})", {
        "joints": eyelid_joints,
        "parent": parent_ctrl or "",
        "built": True
    })


def get_ordered_hierarchy(root):
    """
        Gets ordered hierarchy.
    :param root: root
    :return: result
    """
    ordered = [root]

    def walk(node):
        """
            Walk.
        :param node: node
        :return:
        """
        children = cmds.listRelatives(node, c=True, type="transform", fullPath=True) or []
        for child in children:
            ordered.append(child)
            walk(child)

    walk(root)
    return ordered


def duplicate_static_hierarchy(root, suffix="static"):
    """
        Duplicate static hierarchy.
    :param root: root
    :param suffix: suffix
    :return: result
    """
    if isinstance(root, (list, tuple)):
        root = root[0]

    source_nodes = get_ordered_hierarchy(root)

    dup_root = cmds.duplicate(root, rc=True)[0]
    dup_root = cmds.ls(dup_root, long=True)[0]
    dup_nodes = get_ordered_hierarchy(dup_root)

    pairs = list(zip(source_nodes, dup_nodes))

    renamed_by_source = {}

    # Rename deepest first so DAG paths do not break
    for source_node, dup_node in sorted(pairs, key=lambda p: p[1].count("|"), reverse=True):
        if not cmds.objExists(dup_node):
            continue

        source_short = source_node.split("|")[-1]
        source_short = re.sub(r"_(static|ik|fk|driver)$", "", source_short)

        new_short = f"{source_short}_{suffix}"

        for existing in cmds.ls(new_short, long=True) or []:
            cmds.delete(existing)

        renamed = cmds.rename(dup_node, new_short)
        renamed_by_source[source_node] = renamed

    # Return in source order: root -> child -> child
    renamed_nodes = [renamed_by_source[s] for s in source_nodes if s in renamed_by_source]
    renamed_root = renamed_nodes[0] if renamed_nodes else None

    return renamed_root, renamed_nodes


def remove_eyelids_module(side, face_joint_map):
    """
        Removes all controls and constraints built for eyelids.
    :param side: left or right side (l/r)
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    eyelid_joints = []
    if face_joint_map:
        side_prefix_title = "Left" if side == "l" else "Right"
        eyelid_joints = face_joint_map.get(f"{side_prefix_title}Eyelid", {}).get("joints", [])
    if not eyelid_joints:
        eyelid_joints = [
            f"{side}_inner_eyelidTip",
            f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
            f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
            f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
            f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
            f"{side}_outer_eyelidTip",
            f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
            f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
            f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
        ]
    nodes_to_delete = [
        f"{side}_eyelid_surface_grp"
    ]

    driver_semantics = [
        side + "_inner_eyelid",
        side + "_upper_inner_eyelid",
        side + "_upper_eyelid",
        side + "_upper_outer_eyelid",
        side + "_outer_eyelid",
        side + "_lower_outer_eyelid",
        side + "_lower_eyelid",
        side + "_lower_inner_eyelid",
    ]
    for sem in driver_semantics:
        nodes_to_delete.append(f"{sem}_ctrl_pad")
    for ej in eyelid_joints:
        base = ej.replace("_jnt", "").split("|")[-1].split(":")[-1]
        parent_base = base.replace("Tip", "")
        if cmds.objExists(ej):
            parent = cmds.listRelatives(ej, p=True)
            if parent:
                parent_base = parent[0].replace("_jnt", "").split("|")[-1].split(":")[-1]
        nodes_to_delete.append(f"{parent_base}_ctrl_pad")

    module_id = f"Eyelids ({'Left' if side == 'l' else 'Right'})"
    return _delete_module_from_metadata(module_id, nodes_to_delete)


def rig_mouth_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None):
    """
        Builds the mouth setup with lofted surfaces, follicle controls, and jaw drivers.
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :param jaw_ctrl: jaw control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or "head1_ctrl"
    jaw_ctrl = jaw_ctrl or "jaw_ctrl"
    mouth_joints = []
    if face_joint_map:
        mouth_joints = face_joint_map.get("LipChain", {}).get("joints", [])
    if not mouth_joints:
        mouth_joints = [
            'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
            'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
            'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
            'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
        ]
    mouth_joints = [mj for mj in mouth_joints if cmds.objExists(mj)]

    if len(mouth_joints) >= 8 and cmds.objExists(parent_ctrl):
        loft_surf, follicle_joints, lip_ctrls, driver_data = setup_surface_rig_with_drivers(
            mouth_joints,
            loft_name="mouth",
            offset=0.5,
            driver_follicle_indices=[0, 2, 5, 8, 10, 12, 15, 18],
            region="mouth",
            root_parent=parent_ctrl,
            face_joint_map=face_joint_map
        )

        c_up = "c_upper_lip"
        c_lo = "c_lower_lip"
        l_co = "l_lip_corner1"
        r_co = "r_lip_corner1"
        if face_joint_map:
            c_up = face_joint_map.get("UpperLipCenter", {}).get("joint") or c_up
            c_lo = face_joint_map.get("LowerLipCenter", {}).get("joint") or c_lo
            l_co = face_joint_map.get("LeftLipCorner", {}).get("joint") or l_co
            r_co = face_joint_map.get("RightLipCorner", {}).get("joint") or r_co

        drivers = [
            f"{c_up}_main_ctrl",
            f"{c_lo}_main_ctrl",
            f"{r_co}_main_ctrl",
            f"{l_co}_main_ctrl"
        ]

        if all(cmds.objExists(d) for d in drivers) and cmds.objExists(jaw_ctrl) and lip_ctrls:
            setup_jaw_lip_driver(jaw_ctrl, drivers, lip_ctrls, head_ctrl=parent_ctrl)
    save_module_metadata("Mouth & Lips", {
        "joints": mouth_joints,
        "parent": parent_ctrl or "",
        "jaw_ctrl": jaw_ctrl or "",
        "built": True
    })


def remove_mouth_module(face_joint_map):
    """
        Removes all controls and constraints built for the mouth.
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    mouth_joints = []
    if face_joint_map:
        mouth_joints = face_joint_map.get("LipChain", {}).get("joints", [])
    if not mouth_joints:
        mouth_joints = [
            'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
            'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
            'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
            'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
        ]

    c_up = "c_upper_lip"
    c_lo = "c_lower_lip"
    l_co = "l_lip_corner1"
    r_co = "r_lip_corner1"
    if face_joint_map:
        c_up = face_joint_map.get("UpperLipCenter", {}).get("joint") or c_up
        c_lo = face_joint_map.get("LowerLipCenter", {}).get("joint") or c_lo
        l_co = face_joint_map.get("LeftLipCorner", {}).get("joint") or l_co
        r_co = face_joint_map.get("RightLipCorner", {}).get("joint") or r_co

    nodes_to_delete = [
        "mouth_surface_grp"
    ]
    for mj in mouth_joints:
        nodes_to_delete.append(f"{mj}_ctrl_pad")

    def lip_name(idx, default_base):
        """
            Lip name.
        :param idx: idx
        :param default_base: default base
        :return: result
        """
        if idx < len(mouth_joints) and mouth_joints[idx]:
            return mouth_joints[idx] + "_main"
        return default_base

    driver_semantics = [
        f"{c_up}_main",
        lip_name(2, "r_upper_lip_main"),
        f"{r_co}_main",
        lip_name(8, "r_lower_lip_main"),
        f"{c_lo}_main",
        lip_name(12, "l_lower_lip_main"),
        f"{l_co}_main",
        lip_name(18, "l_upper_lip_main")
    ]
    for sem in driver_semantics:
        nodes_to_delete.append(f"{sem}_ctrl_pad")

    nodes_to_delete.append("lip_main_ctrl_pad")
    for mj in mouth_joints:
        base = mj.replace("_jnt", "").split("|")[-1].split(":")[-1]
        nodes_to_delete.append(f"{base}_ctrl_pad")

    for d in [f"{c_up}_main_ctrl", f"{c_lo}_main_ctrl", f"{r_co}_main_ctrl", f"{l_co}_main_ctrl"]:
        if cmds.objExists(d):
            con = cmds.listConnections(d, type="constraint") or []
            nodes_to_delete.extend(con)

    return _delete_module_from_metadata("Mouth & Lips", nodes_to_delete)


def rig_eyes_module(face_joint_map, parent_ctrl=None):
    """
        Builds the eye aim control setup.
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or "head1_ctrl"
    l_eye = "l_eye"
    r_eye = "r_eye"
    if face_joint_map:
        l_eye = face_joint_map.get("LeftEye", {}).get("joint") or l_eye
        r_eye = face_joint_map.get("RightEye", {}).get("joint") or r_eye

    if cmds.objExists(l_eye) and cmds.objExists(r_eye) and cmds.objExists(parent_ctrl):
        create_eye_aim_setup(l_eye, r_eye, head_ctrl=parent_ctrl)
    save_module_metadata("Eyes Aim", {
        "joints": [
            joint for joint in (l_eye, r_eye)
            if joint and cmds.objExists(joint)
        ],
        "parent": parent_ctrl or "",
        "built": True
    })


def remove_eyes_module(face_joint_map):
    """
        Removes all controls built for the eyes.
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    l_eye = "l_eye"
    r_eye = "r_eye"
    if face_joint_map:
        l_eye = face_joint_map.get("LeftEye", {}).get("joint") or l_eye
        r_eye = face_joint_map.get("RightEye", {}).get("joint") or r_eye

    nodes_to_delete = [
        "eye_aim_ctrl_pad",
        "l_eye_aim_ctrl_pad",
        "r_eye_aim_ctrl_pad"
    ]
    for prefix in [l_eye, r_eye]:
        base = prefix.replace("_jnt", "").split("|")[-1].split(":")[-1]
        nodes_to_delete.append(f"{base}1")
        pads = cmds.ls(f"{base}_ctrl_pad*", type="transform") or []
        nodes_to_delete.extend(pads)
    return _delete_module_from_metadata("Eyes Aim", nodes_to_delete)


def rig_tongue_module(face_joint_map, parent_ctrl=None):
    """
        Builds the tongue controls setup.
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or "jaw_ctrl"
    tongue_chain = []
    if face_joint_map:
        tongue_chain = face_joint_map.get("TongueChain", {}).get("joints", [])
    if not tongue_chain:
        tongue_chain = ["tongue1", "tongue2", "tongue3", "tongue4"]
    tongue_chain = [tj for tj in tongue_chain if cmds.objExists(tj)]

    if tongue_chain and cmds.objExists(parent_ctrl):
        create_joint_controls(
            joint_list=tongue_chain,
            control_shape="circle",
            root_parent=parent_ctrl
        )
    save_module_metadata("Tongue", {
        "joints": tongue_chain,
        "parent": parent_ctrl or "",
        "jaw_ctrl": parent_ctrl or "",
        "built": True
    })


def remove_tongue_module(face_joint_map):
    """
        Removes all controls built for the tongue.
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    tongue_chain = []
    if face_joint_map:
        tongue_chain = face_joint_map.get("TongueChain", {}).get("joints", [])
    if not tongue_chain:
        tongue_chain = ["tongue1", "tongue2", "tongue3", "tongue4"]

    nodes_to_delete = []
    for tj in tongue_chain:
        nodes_to_delete.append(f"{tj}_ctrl_pad")

    return _delete_module_from_metadata("Tongue", nodes_to_delete)


def rig_teeth_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None):
    """
        Builds the upper and lower teeth controls setup.
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :param jaw_ctrl: jaw control node name
    :return: None
    """
    parent_ctrl = parent_ctrl or "head1_ctrl"
    jaw_ctrl = jaw_ctrl or "jaw_ctrl"
    upper_teeth = None
    lower_teeth = None
    if face_joint_map:
        upper_teeth = face_joint_map.get("UpperTeeth", {}).get("joint")
        lower_teeth = face_joint_map.get("LowerTeeth", {}).get("joint")
    if not upper_teeth:
        upper_teeth = "upper_teeth"
    if not lower_teeth:
        lower_teeth = "lower_teeth"

    if upper_teeth and cmds.objExists(upper_teeth) and cmds.objExists(parent_ctrl):
        create_joint_controls([upper_teeth], control_shape="sphere", root_parent=parent_ctrl)
    if lower_teeth and cmds.objExists(lower_teeth) and cmds.objExists(jaw_ctrl):
        create_joint_controls([lower_teeth], control_shape="sphere", root_parent=jaw_ctrl)
    save_module_metadata("Teeth", {
        "joints": [
            joint for joint in (upper_teeth, lower_teeth)
            if joint and cmds.objExists(joint)
        ],
        "parent": parent_ctrl or "",
        "jaw_ctrl": jaw_ctrl or "",
        "built": True
    })


def remove_teeth_module(face_joint_map):
    """
        Removes all controls built for the teeth.
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    upper_teeth = None
    lower_teeth = None
    if face_joint_map:
        upper_teeth = face_joint_map.get("UpperTeeth", {}).get("joint")
        lower_teeth = face_joint_map.get("LowerTeeth", {}).get("joint")
    if not upper_teeth:
        upper_teeth = "upper_teeth"
    if not lower_teeth:
        lower_teeth = "lower_teeth"

    nodes_to_delete = [f"{upper_teeth}_ctrl_pad", f"{lower_teeth}_ctrl_pad"]
    return _delete_module_from_metadata("Teeth", nodes_to_delete)


def rig_other_face_module(face_joint_map, parent_ctrl=None, jaw_ctrl=None, jaw_joint=None):
    """
        Rig other face module.
    :param face_joint_map: mapping for face joint map
    :param parent_ctrl: parent ctrl
    :param jaw_ctrl: jaw ctrl
    :param jaw_joint: jaw joint
    :return:
    """
    parent_ctrl = parent_ctrl or "head1_ctrl"
    jaw_ctrl = jaw_ctrl or "jaw_ctrl"

    face_joints = []

    if face_joint_map:
        face_joints = face_joint_map.get("OtherFaceJoints", {}).get("joints", []) or []

    face_joints = [fj for fj in face_joints if fj and cmds.objExists(fj)]

    # Add full nose hierarchy from NoseRoot
    nose_joints = get_nose_joints(face_joint_map)
    for nj in nose_joints:
        if nj not in face_joints:
            face_joints.append(nj)

    # Force chin / mandible into this module if they exist
    jaw_driven_joints = [
        "l_chin",
        "r_chin",
        "l_mandible",
        "r_mandible",
    ]

    for jj in jaw_driven_joints:
        if cmds.objExists(jj) and jj not in face_joints:
            face_joints.append(jj)

    already_rigged = []

    if face_joint_map:
        for slot in [
            "LeftBrow",
            "RightBrow",
            "LeftEyelid",
            "RightEyelid",
            "LipChain",
            "Jaw",
            "TongueChain",
            "UpperTeeth",
            "LowerTeeth",
            # intentionally NOT NoseRoot
        ]:
            data = face_joint_map.get(slot, {})

            if isinstance(data, dict):
                already_rigged.extend(data.get("joints", []) or [])
                if data.get("joint"):
                    already_rigged.append(data["joint"])
            elif isinstance(data, list):
                already_rigged.extend(data)
            elif isinstance(data, str):
                already_rigged.append(data)

    already_rigged.extend(["lower_teeth"])

    face_joints = [
        fj for fj in face_joints
        if fj and cmds.objExists(fj) and fj not in already_rigged
    ]

    for fj in face_joints:
        if cmds.objExists(f"{fj}_ctrl_pad"):
            continue

        target_p = parent_ctrl

        if fj in jaw_driven_joints:
            target_p = jaw_ctrl
        elif jaw_joint and cmds.objExists(jaw_joint) and cmds.objExists(jaw_ctrl):
            fj_long = cmds.ls(fj, long=True)[0]
            jaw_long = cmds.ls(jaw_joint, long=True)[0]
            if fj_long.startswith(jaw_long + "|"):
                target_p = jaw_ctrl

        if not target_p or not cmds.objExists(target_p):
            continue

        ctrl_data = create_joint_controls(
            [fj],
            control_shape="sphere",
            root_parent=target_p,
            sub_ctrls=False,
            keep_constraint=True
        )

        scale_ctrl_cvs_local(ctrl_data[0]["ctrl"], [0.2, 0.2, 0.2])

    setup_secondary_face_constraints(face_joint_map, parent_ctrl)
    save_module_metadata("Other Face Joints", {
        "joints": face_joints,
        "parent": parent_ctrl or "",
        "jaw_ctrl": jaw_ctrl or "",
        "jaw_jnt": jaw_joint or "",
        "built": True
    })


def remove_other_face_module(face_joint_map):
    """
        Removes all secondary controls built for other face joints.
    :param face_joint_map: face joint mapping dictionary
    :return: int
    """
    face_joints = []
    if face_joint_map:
        face_joints = face_joint_map.get("OtherFaceJoints", {}).get("joints", [])
    nodes_to_delete = []
    for fj in face_joints:
        base = fj.replace("_jnt", "").split("|")[-1].split(":")[-1]
        nodes_to_delete.append(f"{base}_ctrl_pad")
    return _delete_module_from_metadata("Other Face Joints", nodes_to_delete)


def rig_arm_module(side, body_joint_map, parent_ctrl=None):
    """
        Rigs the Arm (IK/FK limb, Fingers, and Twist surface rigs).
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """

    def j(slot):
        """
            J.
        :param slot: slot
        :return: result
        """
        return body_joint_map.get(slot, {}).get("joint") if body_joint_map else None

    arm_chain = []
    if side == "l":
        arm_chain = [j("LeftArm"), j("LeftForeArm"), j("LeftHand")]
    else:
        arm_chain = [j("RightArm"), j("RightForeArm"), j("RightHand")]

    def is_contiguous_joint_chain(chain):
        """Return True when every item exists and each item is the direct joint parent of the next."""
        if len(chain) < 3:
            return False
        if not all(joint and cmds.objExists(joint) and cmds.nodeType(joint) == "joint" for joint in chain):
            return False

        for parent_joint, child_joint in zip(chain[:-1], chain[1:]):
            actual_parent = cmds.listRelatives(child_joint, parent=True, type="joint") or []
            if not actual_parent:
                return False

            parent_long = (cmds.ls(parent_joint, long=True) or [parent_joint])[0]
            actual_long = (cmds.ls(actual_parent[0], long=True) or [actual_parent[0]])[0]
            if actual_long != parent_long:
                return False
        return True

    mapped_arm_chain = [a for a in arm_chain if a and cmds.objExists(a)]

    # Existing mappings can contain three valid scene joints that are not an arm
    # hierarchy (for example face joints). Do not treat "three existing nodes" as
    # proof that the mapping is usable.
    if is_contiguous_joint_chain(mapped_arm_chain):
        arm_chain = mapped_arm_chain
    else:
        fallback_arm_chain = [
            f"{side}_upperarm",
            f"{side}_lowerarm",
            f"{side}_hand"
        ]

        if is_contiguous_joint_chain(fallback_arm_chain):
            print(
                f"[Arm Mapping] Ignoring invalid {side} arm mapping {mapped_arm_chain}; "
                f"using scene hierarchy {fallback_arm_chain}."
            )
            arm_chain = fallback_arm_chain
        else:
            raise RuntimeError(
                "\n".join([
                    f"Could not resolve a valid {'left' if side == 'l' else 'right'} arm chain.",
                    f"Mapped joints: {mapped_arm_chain}",
                    f"Fallback joints: {fallback_arm_chain}",
                    "The arm mapping must resolve to a direct joint hierarchy:",
                    "UpperArm -> LowerArm -> Hand",
                    "Please correct the HumanIK arm slots or use the expected scene joint names."
                ])
            )

    side_prefix_title = "Left" if side == "l" else "Right"
    clav_ctrl = parent_ctrl or f"{side}_clavicle_ctrl"

    # Clavicle Setup
    clav_jnt = body_joint_map.get(f"{side_prefix_title}Shoulder", {}).get("joint") if body_joint_map else None
    if not clav_jnt or not cmds.objExists(clav_jnt):
        clav_jnt = f"{side}_clavicle"

    if clav_jnt and cmds.objExists(clav_jnt) and not cmds.objExists(clav_ctrl):
        # Determine spine tip to parent clavicle to
        spine_tip = body_joint_map.get("Spine2", {}).get("joint") if body_joint_map else "spine5_Tip"
        if not spine_tip or not cmds.objExists(spine_tip):
            spine_tip = "spine5_Tip"
        spine_tip_ctrl = f"{spine_tip}_ctrl" if cmds.objExists(f"{spine_tip}_ctrl") else None

        created = create_joint_controls(
            [clav_jnt],
            control_shape="cube",
            root_parent=spine_tip_ctrl
        )
        if created:
            clav_ctrl = created[0]["ctrl"]
            upperarm = arm_chain[0] if arm_chain else None
            if upperarm and cmds.objExists(upperarm):
                snap_ctrl_cvs_to_child(clav_ctrl, upperarm)

    if len(arm_chain) >= 3 and cmds.objExists(clav_ctrl):
        create_ik_fk_limb(arm_chain, clav_ctrl)

    finger_slots = []
    if body_joint_map:
        for finger in ["Thumb", "Index", "Middle", "Ring", "Pinky"]:
            temp_finger_joints = []
            metacarpal_slot = None
            if finger != "Thumb":
                in_hand_slot = f"{side_prefix_title}InHand{finger}"
                metacarpal_slot = j(in_hand_slot)
                if metacarpal_slot and not cmds.objExists(metacarpal_slot):
                    metacarpal_slot = None

            for i in range(1, 5):
                slot_name = f"{side_prefix_title}Hand{finger}{i}"
                jnt = j(slot_name)
                if jnt and cmds.objExists(jnt):
                    temp_finger_joints.append(jnt)
            temp_finger_joints.reverse()
            if metacarpal_slot:
                temp_finger_joints.append(metacarpal_slot)
            finger_slots.extend(temp_finger_joints)

    if not finger_slots:
        finger_joints = [
            f"{side}_thumb_04", f"{side}_thumb_03", f"{side}_thumb_02", f"{side}_thumb_01",
            f"{side}_index_05", f"{side}_index_04", f"{side}_index_03", f"{side}_index_02", f"{side}_index_01",
            f"{side}_middle_05", f"{side}_middle_04", f"{side}_middle_03", f"{side}_middle_02", f"{side}_middle_01",
            f"{side}_ring_05", f"{side}_ring_04", f"{side}_ring_03", f"{side}_ring_02", f"{side}_ring_01",
            f"{side}_pinky_05", f"{side}_pinky_04", f"{side}_pinky_03", f"{side}_pinky_02", f"{side}_pinky_01"
        ]
    else:
        finger_joints = finger_slots
    finger_joints = [fj for fj in finger_joints if cmds.objExists(fj)]
    if finger_joints:
        bake_joint_orient_to_rotate(joints=finger_joints)
        hand_driver = arm_chain[2] + "_driver" if len(arm_chain) >= 3 else f"{side}_hand_driver"
        create_finger_rigs(finger_joints, hand_driver=hand_driver)

    def get_twists(base_slot, count):
        """
            Gets twists.
        :param base_slot: base slot
        :param count: count
        :return: result
        """
        base_slot_fixed = base_slot.replace('ForeArmRoll', 'ForearmRoll')
        slots = [base_slot] + [f"Leaf{base_slot_fixed}{i}" for i in range(1, count)]
        if body_joint_map:
            twist_list = [body_joint_map.get(sl, {}).get("joint") for sl in slots]
        else:
            twist_list = []
        twist_list = [t for t in twist_list if t and cmds.objExists(t)]
        if not twist_list:
            name_base = base_slot.replace("Roll", "").lower()
            twist_list = [f"{side}_{name_base}_twist"] + [f"{side}_{name_base}_twist{i}" for i in range(1, count)]
            twist_list = [t for t in twist_list if cmds.objExists(t)]
        return twist_list

    upperarm_joints = get_twists("LeftArmRoll" if side == "l" else "RightArmRoll", 4)
    if len(upperarm_joints) >= 2 and cmds.objExists(f"{side}_upperarm_driver"):
        setup_surface_rig_with_drivers(
            upperarm_joints,
            loft_name=f"{side}_upperarm_twist",
            offset=0.5,
            side=side,
            region="upperarm",
            driver_follicle_indices=None,
            root_parent=f"{side}_upperarm_driver"
        )

    lowerarm_joints = get_twists("LeftForeArmRoll" if side == "l" else "RightForeArmRoll", 4)
    if len(lowerarm_joints) >= 2 and cmds.objExists(f"{side}_lowerarm_driver"):
        setup_surface_rig_with_drivers(
            lowerarm_joints,
            loft_name=f"{side}_lowerarm_twist",
            offset=0.5,
            side=side,
            region="lowerarm",
            driver_follicle_indices=None,
            root_parent=f"{side}_lowerarm_driver"
        )

    create_arm_space_switches(side, body_joint_map)

    arm_twist_joints = upperarm_joints + lowerarm_joints

    if cmds.objExists(f"{side}_hand_switch_ctrl"):
        setup_show_twist_ctrls(side, "arm", twist_joints=arm_twist_joints)

    side_label = "Left Arm" if side == "l" else "Right Arm"
    save_module_metadata(side_label, {
        "joints": arm_chain,
        "fingers": finger_joints,
        "twist_upper": upperarm_joints,
        "twist_lower": lowerarm_joints,
        "parent": clav_ctrl,
        "built": True
    })


def _find_parent_joint_control(joint):
    """
        Walk up the joint hierarchy from joint and return the first ancestor control.
    :param joint: joint name to search from
    :return: str or None
    """
    if not joint or not cmds.objExists(joint):
        return None
    curr = joint
    while True:
        parents = cmds.listRelatives(curr, parent=True, type="joint") or []
        if not parents:
            # Fallback to check any transform parent
            parents = cmds.listRelatives(curr, parent=True) or []
            if not parents:
                break
        curr = parents[0]
        # Check standard and FK control suffixes
        for suffix in ["_ctrl", "_fk_ctrl"]:
            ctrl_candidate = curr.split("|")[-1] + suffix
            if cmds.objExists(ctrl_candidate):
                return ctrl_candidate
    return None


def _capture_orphaned_space_switch_roles(module_controls, module_name):
    """
    Before removing a module, scan every OTHER control in the scene for space
    switches that list any of module_controls as a target.

    The original ordered (target, display_name) pairs are stored inside
    GLOBAL_RIG_STORE[module_name]["orphaned_roles"], then each affected switch
    is rebuilt without the about-to-be-removed targets so remaining entries keep
    their original index positions.

    :param module_controls: list of control nodes belonging to the module being removed
    :param module_name:     name of the module
    :return: list[dict]
    """
    if not module_controls:
        return []

    module_ctrl_set = set(module_controls)
    all_scene_ctrls = [n for n in (cmds.ls(type="transform") or [])
                       if n.endswith("_ctrl") and n not in module_ctrl_set]

    orphan_records = []
    for driven in all_scene_ctrls:
        switches = query_space_switches(driven)
        for sw in switches:
            pairs = sw.get("target_enum_pairs", [])
            orphan_hit = [(i, t, d) for i, (t, d) in enumerate(pairs) if t in module_ctrl_set]
            if not orphan_hit:
                continue

            orphan_records.append({
                "driven": driven,
                "attr_name": sw["attr_name"],
                "constraint_type": sw["constraint_type"],
                "full_ordered_pairs": list(pairs),
                "orphaned_indices": [(i, t, d) for i, t, d in orphan_hit],
            })

            remaining_targets = [t for t, d in pairs if t not in module_ctrl_set]
            remaining_names = [d for t, d in pairs if t not in module_ctrl_set]

            if remaining_targets:
                try:
                    create_space_switch(
                        driven=driven,
                        targets=remaining_targets,
                        attr_name=sw["attr_name"],
                        constraint_type=sw["constraint_type"],
                        enum_names=remaining_names
                    )
                    an = sw["attr_name"]
                except Exception as e:
                    print("[Warning] Could not rebuild space switch on " + driven + ": " + str(e))
            else:
                an = sw["attr_name"]
                _delete_space_switch_for_ctrl(driven, an)

    if module_name not in GLOBAL_RIG_STORE:
        GLOBAL_RIG_STORE[module_name] = {"switches": [], "constraints": [], "connections": []}
    GLOBAL_RIG_STORE[module_name]["orphaned_roles"] = orphan_records

    return orphan_records


def _restore_orphaned_space_switch_roles(module_name, rebuilt_ctrl_map=None):
    """
    After a module is rebuilt, re-insert its controls into every space switch
    that previously referenced them, restoring the original enum index order.

    :param module_name:      name of the module being restored
    :param rebuilt_ctrl_map: optional dict mapping old_target_name -> new_target_name
    :return: int  number of restored switches
    """
    if rebuilt_ctrl_map is None:
        rebuilt_ctrl_map = {}

    data = GLOBAL_RIG_STORE.get(module_name, {})
    orphan_records = data.get("orphaned_roles", [])
    if not orphan_records:
        return 0

    restored = 0
    for record in orphan_records:
        driven = record["driven"]
        attr_name = record["attr_name"]
        ctype = record["constraint_type"]
        full_pairs = record["full_ordered_pairs"]

        if not cmds.objExists(driven):
            continue

        remapped_pairs = [[rebuilt_ctrl_map.get(t, t), d] for t, d in full_pairs]
        valid_targets = [t for t, d in remapped_pairs if t and cmds.objExists(t)]
        valid_names = [d for t, d in remapped_pairs if t and cmds.objExists(t)]

        if not valid_targets:
            continue

        try:
            create_space_switch(
                driven=driven,
                targets=valid_targets,
                attr_name=attr_name,
                constraint_type=ctype,
                enum_names=valid_names
            )
            restored += 1
        except Exception as e:
            print("[Warning] Could not restore orphaned space switch on " + driven + ": " + str(e))

    return restored


def _delete_space_switch_for_ctrl(ctrl, attr_name="space"):
    """
        Remove all space-switch scaffolding for ctrl by traversing the scene graph.
    :param ctrl: control node name
    :param attr_name: name of the enum attribute to delete
    :return: None
    """
    if not cmds.objExists(ctrl):
        return

    # Collect all groups in the pad hierarchy of this control (control, sdk_pad, pad)
    nodes_to_check = [ctrl]
    p1 = (cmds.listRelatives(ctrl, parent=True, fullPath=False) or [None])[0]
    if p1 and cmds.objExists(p1):
        nodes_to_check.append(p1)
        p2 = (cmds.listRelatives(p1, parent=True, fullPath=False) or [None])[0]
        if p2 and cmds.objExists(p2):
            nodes_to_check.append(p2)

    # Collect all constraint nodes that live on (or are connected to) these groups
    constraint_types = ["parentConstraint", "orientConstraint", "pointConstraint"]
    constraints = []
    for node in nodes_to_check:
        for ct in constraint_types:
            constraints += cmds.listRelatives(node, type=ct) or []
        for con in (cmds.listConnections(node, source=True, destination=False, type="constraint") or []):
            if con not in constraints:
                constraints.append(con)

    deleted_targets = []
    for con in constraints:
        if not cmds.objExists(con):
            continue
        con_type = cmds.nodeType(con)
        # Query the real target objects the constraint is driven by
        try:
            if con_type == "parentConstraint":
                targets = cmds.parentConstraint(con, q=True, targetList=True) or []
            elif con_type == "orientConstraint":
                targets = cmds.orientConstraint(con, q=True, targetList=True) or []
            elif con_type == "pointConstraint":
                targets = cmds.pointConstraint(con, q=True, targetList=True) or []
            else:
                targets = []
        except Exception:
            targets = []

        for t in targets:
            if not cmds.objExists(t):
                continue
            # Only delete scaffold transforms — real controls have shape nodes.
            # Scaffold nodes (spaceTarget dups, composite spaces) are bare transforms.
            shapes = cmds.listRelatives(t, shapes=True, fullPath=True) or []
            if not shapes:
                cmds.delete(t)
                deleted_targets.append(t)

        if cmds.objExists(con):
            cmds.delete(con)

    # Strip the space enum attr so it can be re-created on rebuild
    if cmds.objExists(ctrl) and cmds.attributeQuery(attr_name, node=ctrl, exists=True):
        cmds.deleteAttr(f"{ctrl}.{attr_name}")

    return deleted_targets


def _short_node_name(node):
    """
        Short node name.
    :param node: node
    :return: result
    """
    if not node:
        return ""
    return str(node).split("|")[-1].split(":")[-1]


def _base_from_joint(joint):
    """
        Base from joint.
    :param joint: joint
    :return: result
    """
    base = _short_node_name(joint)
    return base.replace("_jnt", "")


def _unique_existing_nodes(nodes, include_missing=False):
    """
        Unique existing nodes.
    :param nodes: list of nodes
    :param include_missing: include missing
    :return: result
    """
    result = []
    seen = set()
    for node in nodes or []:
        if not node:
            continue
        node = _short_node_name(node)
        if node in seen:
            continue
        if include_missing or cmds.objExists(node):
            result.append(node)
            seen.add(node)
    return result


def _pad_for_ctrl(ctrl):
    """
        Pad for ctrl.
    :param ctrl: ctrl
    :return: result
    """
    ctrl = _short_node_name(ctrl)
    if not ctrl:
        return None
    return ctrl[:-5] + "_ctrl_pad" if ctrl.endswith("_ctrl") else ctrl + "_pad"


def _safe_delete_nodes(nodes):
    """
        Safe delete nodes.
    :param nodes: list of nodes
    :return: result
    """
    deleted = 0
    for node in _unique_existing_nodes(nodes):
        if cmds.objExists(node):
            cmds.delete(node)
            deleted += 1
    return deleted


def _controls_from_joint_controls(joints):
    """
        Controls from joint controls.
    :param joints: list of joints
    :return: result
    """
    controls = []
    for joint in joints or []:
        base = _base_from_joint(joint)
        if not base:
            continue
        controls.extend([f"{base}_ctrl", f"{base}_fk_ctrl", f"{base}_ik_ctrl"])
    return controls


def _is_rfl_pivot_joint(node):
    """
        Is rfl pivot joint.
    :param node: node
    :return: result
    """
    short = _short_node_name(node)
    return short.endswith("_RFL") and cmds.objExists(short) and cmds.nodeType(short) == "joint"


def _rfl_pivot_joints(side=None):
    """
        Rfl pivot joints.
    :param side: side
    :return: result
    """
    sides = [side] if side else ["l", "r"]
    pivots = []
    for side_name in sides:
        pivots.extend([
            f"{side_name}_heel_RFL",
            f"{side_name}_outerBank_RFL",
            f"{side_name}_innerBank_RFL",
            f"{side_name}_toeTip_RFL",
            f"{side_name}_toe_RFL",
            f"{side_name}_ball_RFL",
            f"{side_name}_ankle_RFL",
        ])
    return _unique_existing_nodes(pivots)


def preserve_rfl_pivot_joints(side=None):
    """
        Preserve rfl pivot joints.
    :param side: side
    :return: result
    """
    preserved = []
    rfl_joints = _rfl_pivot_joints(side)
    rfl_set = set(rfl_joints)
    for rfl_jnt in rfl_joints:
        if not cmds.objExists(rfl_jnt):
            continue
        for con in (cmds.listRelatives(rfl_jnt, type="constraint") or []):
            if cmds.objExists(con):
                cmds.delete(con)
        parent = cmds.listRelatives(rfl_jnt, parent=True, fullPath=False)
        if parent and parent[0] not in rfl_set:
            cmds.parent(rfl_jnt, world=True)
        preserved.append(rfl_jnt)
    return preserved


def _metadata_joint_nodes(metadata):
    """
        Metadata joint nodes.
    :param metadata: metadata
    :return: result
    """
    joint_nodes = []
    skip_keys = {"controls", "cleanup_nodes", "nodes", "custom_space_switches", "orphaned_roles"}
    for key, value in (metadata or {}).items():
        if key in skip_keys:
            continue
        if isinstance(value, (list, tuple)):
            joint_nodes.extend(item for item in value if isinstance(item, str))
        elif key in {"joint", "jaw_jnt"} and isinstance(value, str):
            joint_nodes.append(value)
    return _unique_existing_nodes(joint_nodes, include_missing=True)


_MODULE_CLEANUP_SUFFIXES = (
    "_ctrl",
    "_ctrl_pad",
    "_ctrl_sdk_pad",
    "_sub_ctrl",
    "_sub_ctrl_pad",
    "_sub_ctrl_sdk",
    "_fk",
    "_ik",
    "_driver",
    "_driver_pad",
    "_twist_driver",
    "_folJoint",
    "_ikh",
    "_loc",
    "_md",
    "_rev",
    "_surface",
    "_surface_grp",
    "_follicles",
    "_space",
)

_MODULE_CLEANUP_NODE_TYPES = {
    "aimConstraint",
    "blendColors",
    "condition",
    "follicle",
    "ikEffector",
    "ikHandle",
    "joint",
    "multiplyDivide",
    "orientConstraint",
    "parentConstraint",
    "pointConstraint",
    "plusMinusAverage",
    "reverse",
    "scaleConstraint",
    "skinCluster",
    "transform",
}


def _safe_scene_nodes_by_prefix(prefixes):
    """
        Safe scene nodes by prefix.
    :param prefixes: list of prefixes
    :return: result
    """
    nodes = []
    for node in cmds.ls() or []:
        short = _short_node_name(node)
        if _is_rfl_pivot_joint(short):
            continue
        if not any(short.startswith(prefix) for prefix in prefixes):
            continue
        node_type = cmds.nodeType(node) if cmds.objExists(node) else ""
        is_dag_owned = node_type in {"joint", "transform", "ikHandle"} and short.endswith(_MODULE_CLEANUP_SUFFIXES)
        is_helper_owned = node_type not in {"joint", "transform",
                                            "ikHandle"} and node_type in _MODULE_CLEANUP_NODE_TYPES
        if is_dag_owned or is_helper_owned or short.endswith(_MODULE_CLEANUP_SUFFIXES):
            nodes.append(short)
    return nodes


def _module_prefixes(module_id, metadata):
    """
        Module prefixes.
    :param module_id: module id
    :param metadata: metadata
    :return: result
    """
    prefixes = []
    prefixes.extend(_base_from_joint(joint) for joint in _metadata_joint_nodes(metadata) if joint)

    if module_id in ("Left Arm", "Right Arm"):
        side = "l" if module_id.startswith("Left") else "r"
        prefixes.extend([
            f"{side}_upperarm", f"{side}_lowerarm", f"{side}_hand",
            f"{side}_thumb", f"{side}_index", f"{side}_middle", f"{side}_ring", f"{side}_pinky",
            f"{side}_arm_pv",
        ])
    elif module_id in ("Left Leg", "Right Leg"):
        side = "l" if module_id.startswith("Left") else "r"
        prefixes.extend([
            f"{side}_thigh", f"{side}_knee", f"{side}_ankle", f"{side}_toe", f"{side}_leg_pv",
            f"{side}_heel_RFL", f"{side}_outerBank_RFL", f"{side}_innerBank_RFL",
            f"{side}_toeTip_RFL", f"{side}_toe_RFL", f"{side}_ball_RFL", f"{side}_ankle_RFL",
        ])
    elif module_id in ("Brows (Left)", "Brows (Right)"):
        side = "l" if "Left" in module_id else "r"
        prefixes.append(f"{side}_brow")
    elif module_id in ("Eyelids (Left)", "Eyelids (Right)"):
        side = "l" if "Left" in module_id else "r"
        prefixes.extend(
            [f"{side}_eyelid", f"{side}_eye", f"{side}_upper", f"{side}_lower", f"{side}_inner", f"{side}_outer"])
    elif module_id == "Mouth & Lips":
        prefixes.extend(["mouth", "lip", "c_upper_lip", "c_lower_lip", "l_lip", "r_lip"])
    elif module_id == "Eyes Aim":
        prefixes.extend(["eye_aim", "l_eye_aim", "r_eye_aim"])
    elif module_id == "Tongue":
        prefixes.append("tongue")
    elif module_id == "Teeth":
        prefixes.extend(["upper_teeth", "lower_teeth"])
    elif module_id == "Other Face Joints":
        prefixes.extend(_base_from_joint(joint) for joint in metadata.get("joints", []) if joint)
    else:
        prefixes.extend(_base_from_joint(joint) for joint in metadata.get("joints", []) if joint)

    return [prefix for prefix in dict.fromkeys(prefixes) if prefix]


def _connected_module_nodes(seed_nodes, prefixes=None):
    """
        Connected module nodes.
    :param seed_nodes: list of seed nodes
    :param prefixes: list of prefixes
    :return: result
    """
    prefixes = prefixes or []
    module_nodes = set(_unique_existing_nodes(seed_nodes, include_missing=True))
    checked = set()
    queue = [node for node in module_nodes if cmds.objExists(node)]

    while queue:
        node = queue.pop(0)
        if node in checked or not cmds.objExists(node):
            continue
        checked.add(node)

        related = []
        related.extend(cmds.listConnections(node, source=True, destination=True) or [])
        related.extend(cmds.listRelatives(node, children=True, fullPath=False) or [])

        for rel in related:
            rel = _short_node_name(rel)
            if not rel or rel in module_nodes or not cmds.objExists(rel):
                continue
            if _is_rfl_pivot_joint(rel):
                continue
            node_type = cmds.nodeType(rel)
            matches_prefix = any(rel.startswith(prefix) for prefix in prefixes)
            is_owned_dag = matches_prefix and node_type in {"joint", "transform", "ikHandle"} and rel.endswith(
                _MODULE_CLEANUP_SUFFIXES)
            is_owned_helper = node_type not in {"joint", "transform",
                                                "ikHandle"} and node_type in _MODULE_CLEANUP_NODE_TYPES
            if is_owned_dag or is_owned_helper:
                module_nodes.add(rel)
                queue.append(rel)

    return list(module_nodes)


def _discover_module_controls(module_id, metadata):
    """
        Discover module controls.
    :param module_id: module id
    :param metadata: metadata
    :return: result
    """
    controls = list(metadata.get("controls", []))
    joints = _metadata_joint_nodes(metadata)
    controls.extend(_controls_from_joint_controls(joints))

    if module_id in ("Left Arm", "Right Arm"):
        side = "l" if module_id.startswith("Left") else "r"
        controls.extend([
            f"{side}_upperarm_fk_ctrl",
            f"{side}_lowerarm_fk_ctrl",
            f"{side}_hand_fk_ctrl",
            f"{side}_hand_ik_ctrl",
            f"{side}_lowerarm_pv_ctrl",
            f"{side}_hand_switch_ctrl",
        ])
        controls.extend([n for n in cmds.ls(f"{side}_*_ctrl", type="transform") or []
                         if any(term in _short_node_name(n) for term in
                                ("upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky"))])

    elif module_id in ("Left Leg", "Right Leg"):
        side = "l" if module_id.startswith("Left") else "r"
        controls.extend([
            f"{side}_thigh_fk_ctrl",
            f"{side}_knee_fk_ctrl",
            f"{side}_ankle_fk_ctrl",
            f"{side}_ankle_ik_ctrl",
            f"{side}_knee_pv_ctrl",
            f"{side}_ankle_switch_ctrl",
        ])
        controls.extend([n for n in cmds.ls(f"{side}_*_ctrl", type="transform") or []
                         if any(term in _short_node_name(n) for term in ("thigh", "knee", "ankle", "toe"))])

    elif module_id in ("Brows (Left)", "Brows (Right)"):
        side = "l" if "Left" in module_id else "r"
        controls.extend(cmds.ls(f"{side}_brow*_ctrl", type="transform") or [])

    elif module_id in ("Eyelids (Left)", "Eyelids (Right)"):
        side = "l" if "Left" in module_id else "r"
        controls.extend(cmds.ls(f"{side}_*eyelid*_ctrl", type="transform") or [])

    elif module_id == "Mouth & Lips":
        controls.extend(cmds.ls("*lip*_ctrl", type="transform") or [])

    elif module_id == "Eyes Aim":
        controls.extend(["eye_aim_ctrl", "l_eye_aim_ctrl", "r_eye_aim_ctrl"])

    controls = [ctrl for ctrl in controls if not _is_rfl_pivot_joint(ctrl)]
    return _unique_existing_nodes(controls, include_missing=True)


def _discover_module_cleanup_nodes(module_id, metadata):
    """
        Discover module cleanup nodes.
    :param module_id: module id
    :param metadata: metadata
    :return: result
    """
    nodes = list(metadata.get("cleanup_nodes", metadata.get("nodes", [])))
    controls = _discover_module_controls(module_id, metadata)
    nodes.extend(_pad_for_ctrl(ctrl) for ctrl in controls)

    joints = _metadata_joint_nodes(metadata)
    nodes.extend(f"{_base_from_joint(joint)}_ctrl_pad" for joint in joints if joint)
    prefixes = _module_prefixes(module_id, metadata)
    nodes.extend(_safe_scene_nodes_by_prefix(prefixes))

    if module_id in ("Left Arm", "Right Arm"):
        side = "l" if module_id.startswith("Left") else "r"
        nodes.extend([f"{side}_arm_pv_handClav_space"])
    elif module_id in ("Left Leg", "Right Leg"):
        side = "l" if module_id.startswith("Left") else "r"
        nodes.extend(
            [f"{side}_ankle_toe_ik", f"{side}_toe_toeTip_ik", f"{side}_knee_twist_md", f"{side}_knee_twist_loc",
             f"{side}_leg_pv_footHip_space"])
    elif module_id == "Eyes Aim":
        nodes.extend(["eye_aim_ctrl_pad", "l_eye_aim_ctrl_pad", "r_eye_aim_ctrl_pad"])

    nodes.extend(_connected_module_nodes(nodes + controls, prefixes))
    nodes = [node for node in nodes if not _is_rfl_pivot_joint(node)]
    return _unique_existing_nodes(nodes, include_missing=True)


def _prepare_module_metadata_for_save(module_id, data_dict):
    """
        Prepares module metadata for save.
    :param module_id: module id
    :param data_dict: mapping for data dict
    :return: result
    """
    data = dict(data_dict or {})
    if data.get("built"):
        data["controls"] = _discover_module_controls(module_id, data)
        data["cleanup_nodes"] = _discover_module_cleanup_nodes(module_id, data)
    return data


def _get_module_controls_for_removal(module_id, fallback_controls=None):
    """
        Gets module controls for removal.
    :param module_id: module id
    :param fallback_controls: list of fallback controls
    :return: result
    """
    meta = load_module_metadata(module_id)
    controls = meta.get("controls") or []
    if not controls:
        controls = fallback_controls or []
    return _unique_existing_nodes(controls, include_missing=True)


def get_module_controls(module_id, existing_only=True):
    """
        Return controls recorded/discovered for a stored rig module.
    :param module_id: unique module identifier
    :param existing_only: only return controls that exist in the current scene
    :return: list[str]
    """
    metadata = load_module_metadata(module_id) or {}
    controls = _discover_module_controls(module_id, metadata)
    return _unique_existing_nodes(controls, include_missing=not existing_only)


def _delete_module_from_metadata(module_id, fallback_nodes=None, fallback_controls=None):
    """
        Deletes module from metadata.
    :param module_id: module id
    :param fallback_nodes: list of fallback nodes
    :param fallback_controls: list of fallback controls
    :return: result
    """
    controls = _get_module_controls_for_removal(module_id, fallback_controls)
    _capture_orphaned_space_switch_roles(controls, module_id)
    for ctrl in controls:
        _delete_space_switch_for_ctrl(ctrl)

    meta = load_module_metadata(module_id)
    nodes = meta.get("cleanup_nodes") or meta.get("nodes") or []
    if not nodes and meta:
        nodes = _discover_module_cleanup_nodes(module_id, meta)
    if not nodes:
        nodes = fallback_nodes or []
    nodes = [node for node in nodes if not _is_rfl_pivot_joint(node)]
    deleted = _safe_delete_nodes(nodes)
    clear_module_metadata(module_id)
    return deleted


def remove_arm_module(side, body_joint_map):
    """
        Remove rig nodes and space switches for the given arm side.
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """

    arm_ctrls = [
        f"{side}_lowerarm_pv_ctrl",
        f"{side}_hand_ik_ctrl",
        f"{side}_hand_ikHandle_ctrl",
        f"{side}_upperarm_fk_ctrl",
    ]
    nodes_to_delete = [
        f"{side}_upperarm_fk_ctrl_pad", f"{side}_lowerarm_fk_ctrl_pad", f"{side}_hand_fk_ctrl_pad",
        f"{side}_hand_ik_ctrl_pad", f"{side}_lowerarm_pv_ctrl_pad", f"{side}_hand_switch_ctrl_pad",
        f"{side}_upperarm_driver_pad", f"{side}_lowerarm_driver_pad", f"{side}_hand_driver_pad",
        f"{side}_upperarm_twist_surface_grp", f"{side}_upperarm_twist_surface", f"{side}_upperarm_twist_follicles",
        f"{side}_upperarm_twist_driver_pad",
        f"{side}_lowerarm_twist_surface_grp", f"{side}_lowerarm_twist_surface", f"{side}_lowerarm_twist_follicles",
        f"{side}_lowerarm_twist_driver_pad",
        f"{side}_arm_pv_handClav_space"
    ]
    fingers = ["thumb", "index", "middle", "ring", "pinky"]
    for f in fingers:
        for i in range(1, 6):
            nodes_to_delete.append(f"{side}_{f}_0{i}_ctrl_pad")
            nodes_to_delete.append(f"{side}_{f}_0{i}_driver_pad")

    side_label = "Left Arm" if side == "l" else "Right Arm"
    return _delete_module_from_metadata(side_label, nodes_to_delete, arm_ctrls)


def resolve_rfl_joints(side):
    """
    Resolve an existing reverse-foot hierarchy.

    Supports both the newer toe pivot name and older/manual ball pivot name:
        <side>_toe_RFL
        <side>_ball_RFL

    Returns joints in the order expected by build_rfl_ik_and_constraints:
        heel, outerBank, innerBank, toeTip, toe/ball, ankle

    Returns [] when a complete setup cannot be found.
    :param side: side
    :return: result
    """
    role_candidates = {
        "heel": [f"{side}_heel_RFL"],
        "outerBank": [
            f"{side}_outerBank_RFL",
            f"{side}_outer_bank_RFL",
        ],
        "innerBank": [
            f"{side}_innerBank_RFL",
            f"{side}_inner_bank_RFL",
        ],
        "toeTip": [
            f"{side}_toeTip_RFL",
            f"{side}_toe_tip_RFL",
        ],
        "toe": [
            f"{side}_toe_RFL",
            f"{side}_ball_RFL",
        ],
        "ankle": [f"{side}_ankle_RFL"],
    }

    resolved = {}

    for role, candidates in role_candidates.items():
        for candidate in candidates:
            matches = cmds.ls(candidate, long=True, type="joint") or []
            if len(matches) == 1:
                resolved[role] = matches[0]
                break
            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple joints match RFL role '{role}' for side '{side}': "
                    + ", ".join(matches)
                )

    required_roles = ("heel", "outerBank", "innerBank", "toeTip", "toe", "ankle")
    if any(role not in resolved for role in required_roles):
        return []

    return [
        resolved["heel"],
        resolved["outerBank"],
        resolved["innerBank"],
        resolved["toeTip"],
        resolved["toe"],
        resolved["ankle"],
    ]


def create_rfl_joints_template(side, ankle_jnt, toe_jnt, toe_tip_jnt):
    """
    Creates RFL template joints heel > outerBank > innerBank > toeTip > toe > ankle.
    :param side: side
    :param ankle_jnt: ankle jnt
    :param toe_jnt: toe jnt
    :param toe_tip_jnt: toe tip jnt
    :return: result
    """
    # 1. Gather positions
    ank_pos = cmds.xform(ankle_jnt, q=True, ws=True, t=True) if ankle_jnt and cmds.objExists(ankle_jnt) else [0, 1, 0]
    toe_pos = cmds.xform(toe_jnt, q=True, ws=True, t=True) if toe_jnt and cmds.objExists(toe_jnt) else [0, 0.2, 1]
    tip_pos = cmds.xform(toe_tip_jnt, q=True, ws=True, t=True) if toe_tip_jnt and cmds.objExists(toe_tip_jnt) else [0,
                                                                                                                    0.1,
                                                                                                                    1.5]

    # Side sign multiplier
    x_mult = 1.0 if side == "l" else -1.0

    # Positions for banks and heel (on floor Y=0 or same Y as toe)
    floor_y = 0.0
    heel_pos = [ank_pos[0], floor_y, ank_pos[2] - 1.5]
    outer_pos = [toe_pos[0] - (2.5 * x_mult), floor_y, toe_pos[2]]
    inner_pos = [toe_pos[0] + (2.5 * x_mult), floor_y, toe_pos[2]]

    # 2. Create the joint hierarchy
    cmds.select(cl=True)
    heel = cmds.joint(name=f"{side}_heel_RFL", p=heel_pos)
    outer = cmds.joint(name=f"{side}_outerBank_RFL", p=outer_pos)
    inner = cmds.joint(name=f"{side}_innerBank_RFL", p=inner_pos)
    tip = cmds.joint(name=f"{side}_toeTip_RFL", p=tip_pos)
    toe = cmds.joint(name=f"{side}_toe_RFL", p=toe_pos)
    ankle = cmds.joint(name=f"{side}_ankle_RFL", p=ank_pos)

    # Orient them to world (or clean rotation)
    for jnt in [heel, outer, inner, tip, toe, ankle]:
        cmds.setAttr(jnt + ".jointOrientX", 0)
        cmds.setAttr(jnt + ".jointOrientY", 0)
        cmds.setAttr(jnt + ".jointOrientZ", 0)

    return [heel, outer, inner, tip, toe, ankle]


def rig_leg_module(side, body_joint_map, parent_ctrl=None):
    """
        Rigs the Leg (IK/FK limb, Twist surface rigs, foot roll RFL, and switches).
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """

    def j(slot):
        """
            J.
        :param slot: slot
        :return: result
        """
        return body_joint_map.get(slot, {}).get("joint") if body_joint_map else None

    leg_chain = []
    if body_joint_map and side in body_joint_map:
        leg_chain = body_joint_map[side]
    else:
        prefix = "Left" if side == "l" else "Right"
        up_leg = j(f"{prefix}UpLeg")
        leg = j(f"{prefix}Leg")
        foot = j(f"{prefix}Foot")
        toe = j(f"{prefix}ToeBase")
        toe_tip = None
        if toe and cmds.objExists(toe):
            kids = cmds.listRelatives(toe, c=True, type="joint") or []
            if kids:
                toe_tip = kids[0]
        leg_chain = [up_leg, leg, foot, toe, toe_tip]

    valid_leg = [l for l in leg_chain if l and cmds.objExists(l)]
    if len(valid_leg) < 3:
        leg_chain = [
            f"{side}_thigh",
            f"{side}_knee",
            f"{side}_ankle",
            f"{side}_toe",
            f"{side}_toeTip"
        ]
    else:
        while len(leg_chain) < 5:
            leg_chain.append(None)
        if not leg_chain[3] or not cmds.objExists(leg_chain[3]):
            leg_chain[3] = f"{side}_toe"
        if not leg_chain[4] or not cmds.objExists(leg_chain[4]):
            leg_chain[4] = f"{side}_toeTip"
    leg_chain = [l for l in leg_chain if l and cmds.objExists(l)]

    hip_ctrl = parent_ctrl
    if not hip_ctrl:
        if cmds.objExists("hipswing_ctrl"):
            hip_ctrl = "hipswing_ctrl"
        elif cmds.objExists("pelvis_ctrl"):
            hip_ctrl = "pelvis_ctrl"
        else:
            hip_ctrl = "origin_ctrl"

    if len(leg_chain) >= 3:
        create_ik_fk_limb(leg_chain, hip_ctrl)

    side_prefix_title = "Left" if side == "l" else "Right"

    def get_twists(base_slot, count):
        """
            Gets twists.
        :param base_slot: base slot
        :param count: count
        :return: result
        """
        slots = [base_slot] + [f"Leaf{base_slot}{i}" for i in range(1, count)]
        if body_joint_map:
            twist_list = [body_joint_map.get(sl, {}).get("joint") for sl in slots]
        else:
            twist_list = []
        twist_list = [t for t in twist_list if t and cmds.objExists(t)]
        if not twist_list:
            name_base = base_slot.replace("Roll", "").lower()
            twist_list = [f"{side}_{name_base}_twist"] + [f"{side}_{name_base}_twist{i}" for i in range(1, count)]
            twist_list = [t for t in twist_list if cmds.objExists(t)]
        return twist_list

    thigh_joints = get_twists("LeftUpLegRoll" if side == "l" else "RightUpLegRoll", 4)
    if len(thigh_joints) >= 2 and cmds.objExists(f"{side}_thigh_driver"):
        setup_surface_rig_with_drivers(
            thigh_joints,
            loft_name=f"{side}_thigh_twist",
            offset=0.5,
            side=side,
            region="thigh",
            driver_follicle_indices=None,
            root_parent=f"{side}_thigh_driver"
        )

    knee_joints = get_twists("LeftLegRoll" if side == "l" else "RightLegRoll", 3)
    if len(knee_joints) >= 3 and cmds.objExists(f"{side}_knee_driver") and cmds.objExists(f"{side}_ankle_driver"):
        knee_ctrl_data = create_joint_controls(
            knee_joints,
            control_shape="arrow",
            root_parent=f"{side}_knee_driver",
            sub_ctrls=False,
            keep_constraint=True
        )
        knee_twist = create_twist_driver(
            driver_bone=f"{side}_knee_driver",
            child_bone=f"{side}_ankle_driver",
            parent=f"{side}_knee_driver",
            surface=None
        )
        md_node = cmds.createNode("multiplyDivide", name=f"{side}_knee_twist_md")
        cmds.setAttr(f"{md_node}.operation", 1)

        cmds.setAttr(f"{md_node}.input2X", 0.333)
        cmds.setAttr(f"{md_node}.input2Y", 0.667)
        cmds.setAttr(f"{md_node}.input2Z", 1)

        for idx, channel in enumerate(["X", "Y", "Z"]):
            cmds.connectAttr(f"{knee_twist}.rotateX", f"{md_node}.input1{channel}")

        for i, kj in enumerate(knee_joints):
            if i != 0:
                knee_pad = knee_ctrl_data[i]["pad"]
                cmds.parent(knee_pad, f"{side}_knee_driver")
            knee_sdk = knee_ctrl_data[i]["sdk"]
            output_attr = f"output{['X', 'Y', 'Z'][i]}"
            cmds.connectAttr(f"{md_node}.{output_attr}", f"{knee_sdk}.rotateX")

    def get_ik_joint_name(jnt):
        """
            Gets ik joint name.
        :param jnt: jnt
        :return: result
        """
        if not jnt:
            return ""
        base = jnt.split("|")[-1]
        base = re.sub(r'\d+$', '', base)
        base = base.replace("_jnt", "")
        return f"{base}_ik"

    rfl_joints = resolve_rfl_joints(side)
    ik_leg_joints = []
    if len(leg_chain) >= 5:
        ik_leg_joints = [
            get_ik_joint_name(leg_chain[2]),
            get_ik_joint_name(leg_chain[3]),
            get_ik_joint_name(leg_chain[4])
        ]

    if ik_leg_joints and cmds.objExists(f"{side}_ankle_ik_ctrl"):
        if not rfl_joints:
            create_rfl_joints_template(
                side,
                leg_chain[2],
                leg_chain[3],
                leg_chain[4]
            )

            msg = (
                f"RFL (Reverse Foot Lock) joints were not found in the scene for the {side_prefix_title} Leg.\n\n"
                "A template joint hierarchy was created in the viewport.\n\n"
                "Position/orient the heel, outer bank, inner bank, toe tip, toe/ball, "
                "and ankle pivots, then click Continue Build."
            )

            dialog = custom_widgets.ModelessContinueDialog(
                "RFL Template Created",
                msg
            )

            if hasattr(dialog, "exec_non_modal"):
                result = dialog.exec_non_modal()
            elif hasattr(dialog, "exec_"):
                result = dialog.exec_()
            else:
                result = dialog.exec()

            if result not in ("Continue Build", True, 1):
                return

            rfl_joints = resolve_rfl_joints(side)

        if not rfl_joints:
            raise RuntimeError(
                f"Could not resolve a complete {side_prefix_title} Leg RFL hierarchy "
                "after template creation."
            )

        if all(cmds.objExists(joint) for joint in ik_leg_joints):
            build_rfl_ik_and_constraints(
                side=side,
                ik_leg_ctrl=f"{side}_ankle_ik_ctrl",
                ik_leg_joints=ik_leg_joints,
                rfl_joints=rfl_joints
            )

    create_leg_space_switches(side, body_joint_map)

    leg_twist_joints = thigh_joints + knee_joints

    if cmds.objExists(f"{side}_ankle_switch_ctrl"):
        setup_show_twist_ctrls(
            side,
            "leg",
            twist_joints=leg_twist_joints
        )

    side_label = "Left Leg" if side == "l" else "Right Leg"
    save_module_metadata(side_label, {
        "joints": leg_chain,
        "twist_thigh": thigh_joints,
        "twist_knee": knee_joints,
        "parent": hip_ctrl,
        "built": True
    })


def remove_leg_module(side, body_joint_map):
    """
        Remove rig nodes and RFL setups for the given leg side.
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """

    preserve_rfl_pivot_joints(side)

    leg_label = "Left Leg" if side == "l" else "Right Leg"
    leg_ctrls = [
        f"{side}_thigh_fk_ctrl", f"{side}_knee_pv_ctrl",
        f"{side}_ankle_ik_ctrl", f"{side}_ankle_switch_ctrl",
    ]
    nodes_to_delete = [
        f"{side}_thigh_fk_ctrl_pad", f"{side}_knee_fk_ctrl_pad", f"{side}_ankle_fk_ctrl_pad",
        f"{side}_ankle_ik_ctrl_pad", f"{side}_knee_pv_ctrl_pad", f"{side}_ankle_switch_ctrl_pad",
        f"{side}_thigh_driver_pad", f"{side}_knee_driver_pad", f"{side}_ankle_driver_pad",
        f"{side}_thigh_twist_surface_grp", f"{side}_thigh_twist_surface", f"{side}_thigh_twist_follicles",
        f"{side}_thigh_twist_driver_pad",
        f"{side}_knee_twist_md", f"{side}_knee_twist_loc",
        f"{side}_ankle_toe_ik", f"{side}_toe_toeTip_ik",
        f"{side}_leg_pv_footHip_space"
    ]
    side_prefix_title = "Left" if side == "l" else "Right"
    slots = ["LeftLegRoll"] + [f"Leaf{side_prefix_title}LegRoll{i}" for i in range(1, 3)]
    for sl in slots:
        jnt = body_joint_map.get(sl, {}).get("joint") if body_joint_map else None
        if jnt:
            nodes_to_delete.append(f"{jnt}_ctrl_pad")

    return _delete_module_from_metadata(leg_label, nodes_to_delete, leg_ctrls)


def rig_root_module(body_joint_map):
    """
        Builds the root origin control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: None
    """
    root_jnt = (body_joint_map.get("Root") or {}).get("joint") if body_joint_map else None
    if not root_jnt or not cmds.objExists(root_jnt):
        root_jnt = "origin"
    if cmds.objExists(root_jnt):
        create_joint_controls([root_jnt], control_shape="circle")
        ctrl_name = root_jnt + "_ctrl"
        if cmds.objExists(ctrl_name):
            scale_ctrl_cvs_local(ctrl_name, [25, 25, 25])
            orient_control_pad_to_world_safely(ctrl_name, root_jnt)
    save_module_metadata("Root / Origin", {
        "joints": [root_jnt],
        "parent": "",
        "built": True
    })


def remove_root_module(body_joint_map):
    """
        Removes the root origin control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    root_jnt = (body_joint_map.get("Root") or {}).get("joint") if body_joint_map else None
    if not root_jnt:
        root_jnt = "origin"
    return _delete_module_from_metadata("Root / Origin", [root_jnt + "_ctrl_pad"], [root_jnt + "_ctrl"])


def rig_pelvis_module(body_joint_map, parent_ctrl=None):
    """
        Builds the pelvis and hipswing control setup.
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    pelvis_jnt = (body_joint_map.get("Hips") or {}).get("joint") if body_joint_map else None
    if not pelvis_jnt or not cmds.objExists(pelvis_jnt):
        pelvis_jnt = "pelvis"

    root_jnt = (body_joint_map.get("Root") or {}).get("joint") if body_joint_map else None
    if not root_jnt:
        root_jnt = "origin"
    root_p = parent_ctrl or (root_jnt + "_ctrl" if cmds.objExists(root_jnt + "_ctrl") else None)

    joints_used = []
    if cmds.objExists(pelvis_jnt):
        create_joint_controls([pelvis_jnt], control_shape="circle", root_parent=root_p)
        ctrl_name = pelvis_jnt + "_ctrl"
        if cmds.objExists(ctrl_name):
            scale_ctrl_cvs_local(ctrl_name, [25, 25, 25])
            orient_control_pad_to_world_safely(ctrl_name, pelvis_jnt)
        joints_used.append(pelvis_jnt)

    hip_swing = (body_joint_map.get("HipSwing") or {}).get("joint") if body_joint_map else None
    if not hip_swing or not cmds.objExists(hip_swing):
        hip_swing = "hipswing"

    if cmds.objExists(hip_swing):
        root_p_swing = pelvis_jnt + "_ctrl" if cmds.objExists(pelvis_jnt + "_ctrl") else None
        create_joint_controls([hip_swing], control_shape="sphere", root_parent=root_p_swing)
        swing_ctrl = hip_swing.replace("_jnt", "").split("|")[-1] + "_ctrl"
        orient_control_pad_to_world_safely(swing_ctrl, hip_swing)
        joints_used.append(hip_swing)

    save_module_metadata("Pelvis & Hips", {
        "joints": joints_used,
        "parent": root_p or "",
        "built": True
    })


def remove_pelvis_module(body_joint_map):
    """
        Removes the pelvis and hipswing control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    pelvis_jnt = (body_joint_map.get("Hips") or {}).get("joint") if body_joint_map else None
    if not pelvis_jnt:
        pelvis_jnt = "pelvis"

    hip_swing = (body_joint_map.get("HipSwing") or {}).get("joint") if body_joint_map else None
    if not hip_swing:
        hip_swing = "hipswing"

    nodes = [pelvis_jnt + "_ctrl_pad", hip_swing + "_ctrl_pad"]
    controls = [pelvis_jnt + "_ctrl", hip_swing + "_ctrl"]
    return _delete_module_from_metadata("Pelvis & Hips", nodes, controls)


def rig_spine_module(body_joint_map, parent_ctrl=None):
    """
        Builds the spine control setup.
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    spine_joints = []
    if body_joint_map:
        for key in sorted(body_joint_map.keys()):
            if key.startswith("Spine") and not key.endswith("Tip"):
                jnt = body_joint_map[key].get("joint")
                if jnt and cmds.objExists(jnt):
                    spine_joints.append(jnt)
    if not spine_joints:
        spine_joints = ["spine1", "spine3", "spine5"]
    spine_joints = [s for s in spine_joints if cmds.objExists(s)]

    pelvis_jnt = body_joint_map.get("Hips", {}).get("joint") if body_joint_map else "pelvis"
    root_p = parent_ctrl or (pelvis_jnt + "_ctrl" if cmds.objExists(pelvis_jnt + "_ctrl") else None)

    if spine_joints:
        spine_tip = spine_joints[-1]
        spine_base = spine_joints[:-1]
        if spine_base:
            create_joint_controls(spine_base, control_shape="sphere", root_parent=root_p, sub_ctrls=True)
        tip_root = spine_base[-1] + "_ctrl" if spine_base else root_p
        if cmds.objExists(spine_tip):
            create_joint_controls([spine_tip], control_shape="sphere", root_parent=tip_root)

    save_module_metadata("Spine", {
        "joints": spine_joints,
        "parent": root_p or "",
        "built": True
    })


def remove_spine_module(body_joint_map):
    """
        Removes the spine control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    spine_joints = []
    if body_joint_map:
        for key in sorted(body_joint_map.keys()):
            if key.startswith("Spine"):
                jnt = body_joint_map[key].get("joint")
                if jnt:
                    spine_joints.append(jnt)
    if not spine_joints:
        spine_joints = ["spine1", "spine3", "spine5", "spine5_Tip"]
    nodes = [s + "_ctrl_pad" for s in spine_joints]
    controls = [s + "_ctrl" for s in spine_joints]
    return _delete_module_from_metadata("Spine", nodes, controls)


def rig_neck_module(body_joint_map, parent_ctrl=None):
    """
        Builds the neck control setup and space switches.
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    neck_joints = []
    if body_joint_map:
        for key in sorted(body_joint_map.keys()):
            if key.startswith("Neck"):
                jnt = body_joint_map[key].get("joint")
                if jnt and cmds.objExists(jnt):
                    neck_joints.append(jnt)

    # Auto-discover neck joints from head joint if mapping is empty
    if not neck_joints and body_joint_map:
        head_joint = body_joint_map.get("Head", {}).get("joint")
        if head_joint and cmds.objExists(head_joint):
            curr = head_joint
            discovered_neck = []
            stop_joint = body_joint_map.get("Spine2", {}).get("joint")
            if not stop_joint or not cmds.objExists(stop_joint):
                stop_joint = "spine5_Tip"
            while True:
                parents = cmds.listRelatives(curr, parent=True, type="joint") or []
                if not parents:
                    parents = cmds.listRelatives(curr, parent=True) or []
                    if not parents:
                        break
                curr = parents[0]
                if curr == stop_joint or "spine" in curr.lower():
                    break
                discovered_neck.append(curr)
            if discovered_neck:
                neck_joints = list(reversed(discovered_neck))

    if not neck_joints:
        neck_joints = ["neck1", "neck2"]
    neck_joints = [n for n in neck_joints if cmds.objExists(n)]

    spine_tip = body_joint_map.get("Spine2", {}).get("joint") if body_joint_map else "spine5_Tip"
    if not spine_tip or not cmds.objExists(spine_tip):
        spine_tip = "spine5_Tip"
    root_p = parent_ctrl or (spine_tip + "_ctrl" if cmds.objExists(spine_tip + "_ctrl") else None)
    if neck_joints:
        create_joint_controls(joint_list=neck_joints, control_shape="circle", root_parent=root_p)
        neck_ctrl = neck_joints[0] + "_ctrl"
        if cmds.objExists(neck_ctrl):
            targets = [t for t in ["pelvis_ctrl", "origin_ctrl", root_p] if t and cmds.objExists(t)]
            if targets:
                enum_names = build_enum_names_for_space_targets(targets, side=None)
                create_space_switch(driven=neck_ctrl, targets=targets, attr_name="space", constraint_type="orient",
                                    enum_names=enum_names)

    save_module_metadata("Neck", {
        "joints": neck_joints,
        "parent": root_p or "",
        "built": True
    })


def remove_neck_module(body_joint_map):
    """
        Removes the neck control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    neck_joints = []
    if body_joint_map:
        for key in sorted(body_joint_map.keys()):
            if key.startswith("Neck"):
                jnt = body_joint_map[key].get("joint")
                if jnt:
                    neck_joints.append(jnt)
    if not neck_joints:
        neck_joints = ["neck1", "neck2"]
    nodes = [n + "_ctrl_pad" for n in neck_joints]
    controls = [n + "_ctrl" for n in neck_joints]
    return _delete_module_from_metadata("Neck", nodes, controls)


def rig_head_module(body_joint_map, face_joint_map=None, parent_ctrl=None):
    """
        Builds the head control setup and space switches.
    :param body_joint_map: body joint mapping dictionary
    :param face_joint_map: face joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    head_joint = body_joint_map.get("Head", {}).get("joint") if body_joint_map else None
    if not head_joint or not cmds.objExists(head_joint):
        head_joint = "head1"

    neck_tip = body_joint_map.get("Neck1", {}).get("joint") if body_joint_map else "neck2"
    if not neck_tip or not cmds.objExists(neck_tip):
        neck_tip = "neck2"
    root_p = parent_ctrl or (neck_tip + "_ctrl" if cmds.objExists(neck_tip + "_ctrl") else None)

    if cmds.objExists(head_joint):
        create_joint_controls(joint_list=[head_joint], control_shape="circle", root_parent=root_p)
        head_ctrl = head_joint + "_ctrl"
        if cmds.objExists(head_ctrl):
            targets = [t for t in ["pelvis_ctrl", "origin_ctrl", root_p] if t and cmds.objExists(t)]
            if targets:
                enum_names = build_enum_names_for_space_targets(targets, side=None)
                create_space_switch(driven=head_ctrl, targets=targets, attr_name="space", constraint_type="orient",
                                    enum_names=enum_names)
    jaw_joint = _mapped_existing_joint(face_joint_map, "Jaw")
    if jaw_joint and cmds.objExists(head_ctrl):
        create_joint_controls(
            joint_list=[jaw_joint],
            control_shape="circle",
            root_parent=head_ctrl
        )
    save_module_metadata("Head", {
        "joints": [head_joint],
        "parent": root_p or "",
        "built": True
    })


def remove_head_module(body_joint_map):
    """
        Removes the head control setup.
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    head_joint = body_joint_map.get("Head", {}).get("joint") if body_joint_map else "head1"
    return _delete_module_from_metadata("Head", [head_joint + "_ctrl_pad"], [head_joint + "_ctrl"])


def _module_attr_name(module_id):
    """
        Normalise a module ID to a valid Maya attribute name.
    :param module_id: unique module identifier
    :return: str
    """
    name = module_id.replace(" ", "_").replace("(", "").replace(")", "")
    name = name.replace("&", "and").replace("/", "_")
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return "module_" + name.lower()


def save_module_metadata(module_id, data_dict):
    """
        Persist data_dict for module_id on the scene-level store node.
    :param module_id: unique module identifier
    :param data_dict: dictionary containing module properties
    :return: None
    """

    data_dict = _prepare_module_metadata_for_save(module_id, data_dict)

    if not cmds.objExists(MODULE_STORE_NODE):
        cmds.createNode("network", name=MODULE_STORE_NODE)
    attr = _module_attr_name(module_id)
    if not cmds.attributeQuery(attr, node=MODULE_STORE_NODE, exists=True):
        cmds.addAttr(MODULE_STORE_NODE, longName=attr, dataType="string")

    # Merge with existing metadata to preserve other keys
    existing = load_module_metadata(module_id)
    merged = {}
    if existing:
        merged.update(existing)
    merged.update(data_dict)

    cmds.setAttr(f"{MODULE_STORE_NODE}.{attr}", json.dumps(merged), type="string")


def load_module_metadata(module_id):
    """
        Return the stored dict for module_id, or {} if not found.
    :param module_id: unique module identifier
    :return: dict
    """

    if not cmds.objExists(MODULE_STORE_NODE):
        return {}
    attr = _module_attr_name(module_id)
    if not cmds.attributeQuery(attr, node=MODULE_STORE_NODE, exists=True):
        return {}
    raw = cmds.getAttr(f"{MODULE_STORE_NODE}.{attr}") or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {}


def get_all_module_metadata():
    """
        Return {module_id: data_dict} for every stored module.
    :return: dict
    """
    if not cmds.objExists(MODULE_STORE_NODE):
        return {}
    attrs = cmds.listAttr(MODULE_STORE_NODE, userDefined=True) or []
    result = {}
    for attr in attrs:
        if attr.startswith("module_"):
            raw = cmds.getAttr(f"{MODULE_STORE_NODE}.{attr}") or "{}"
            try:
                result[attr[len("module_"):]] = json.loads(raw)
            except Exception:
                result[attr[len("module_"):]] = {}
    return result


def clear_module_metadata(module_id):
    """
        Mark a module as not built while keeping its joint/parent info.
    :param module_id: unique module identifier
    :return: None
    """
    data = load_module_metadata(module_id)
    data["built"] = False
    save_module_metadata(module_id, data)


def store_rig_connections(controls_list, module_name):
    """
        Queries space switches, external constraints, and output connections for controls_list and stores them in GLOBAL_RIG_STORE[module_name].
    :param controls_list: list of control nodes to query
    :param module_name: name of the module
    :return: None
    """
    if module_name not in GLOBAL_RIG_STORE:
        GLOBAL_RIG_STORE[module_name] = {
            "switches": [],
            "constraints": [],
            "connections": []
        }

    internal_nodes = set(controls_list)
    for ctrl in controls_list:
        internal_nodes.add(ctrl + "_sdk_pad")
        internal_nodes.add(ctrl + "_pad")

    data = GLOBAL_RIG_STORE[module_name]
    # Clear existing stored data for this module to avoid duplicates
    data["switches"] = []
    data["constraints"] = []
    data["connections"] = []

    for ctrl in controls_list:
        if not cmds.objExists(ctrl):
            continue
        if ctrl.endswith("_switch_ctrl"):
            continue

        sw = query_space_switches(ctrl)
        if sw:
            data["switches"].extend(sw)

        conns = cmds.listConnections(ctrl, type="constraint") or []
        for con in list(set(conns)):
            if not cmds.objExists(con):
                continue
            con_type = cmds.objectType(con)
            targets = []
            if con_type == "parentConstraint":
                targets = cmds.parentConstraint(con, q=True, tl=True) or []
            elif con_type == "orientConstraint":
                targets = cmds.orientConstraint(con, q=True, tl=True) or []
            elif con_type == "pointConstraint":
                targets = cmds.pointConstraint(con, q=True, tl=True) or []
            elif con_type == "scaleConstraint":
                targets = cmds.scaleConstraint(con, q=True, tl=True) or []

            if ctrl in targets:
                driven = cmds.listRelatives(con, parent=True)
                if driven and driven[0] not in internal_nodes:
                    data["constraints"].append({
                        "constraint_type": con_type,
                        "driver": ctrl,
                        "driven": driven[0],
                        "con_name": con
                    })

        plugs = cmds.listConnections(ctrl, source=True, destination=True, connections=True, plugs=True) or []
        for i in range(0, len(plugs), 2):
            src = plugs[i]
            dst = plugs[i + 1]
            if src.startswith(ctrl + "."):
                dst_node = dst.split(".")[0]
                if dst_node not in internal_nodes and "Constraint" not in cmds.objectType(dst_node):
                    data["connections"].append({
                        "src": src,
                        "dst": dst
                    })

    return GLOBAL_RIG_STORE[module_name]


def rebuild_all_space_switches():
    """
    Rebuilds all space switches in the scene using stored connections to ensure
    they are perfectly aligned with newly oriented controls.
    """
    for module in list(GLOBAL_RIG_STORE.keys()):
        restore_rig_connections(module)


def _space_switch_targets_from_record(sw):
    """
        Space switch targets from record.
    :param sw: sw
    :return: result
    """
    target_enum_pairs = sw.get("target_enum_pairs", [])
    if not target_enum_pairs and "targets" in sw:
        target_enum_pairs = [[t, t] for t in sw["targets"]]
    return [
        [_short_node_name(target), display]
        for target, display in target_enum_pairs
        if target
    ]


def _space_switch_exists_in_scene(sw):
    """
        Space switch exists in scene.
    :param sw: sw
    :return: result
    """
    driven = sw.get("driven")
    if not driven or not cmds.objExists(driven):
        return False

    expected = _space_switch_targets_from_record(sw)
    for existing in query_space_switches(driven):
        if existing.get("attr_name") != sw.get("attr_name"):
            continue
        if existing.get("constraint_type") != sw.get("constraint_type"):
            continue
        if _space_switch_targets_from_record(existing) == expected:
            return True
    return False


def _constraint_exists(driver, driven, constraint_type):
    """
        Constraint exists.
    :param driver: driver
    :param driven: driven
    :param constraint_type: constraint type
    :return: result
    """
    if not cmds.objExists(driver) or not cmds.objExists(driven):
        return False

    constraints = cmds.listRelatives(driven, children=True, type=constraint_type) or []
    for con in constraints:
        try:
            if constraint_type == "parentConstraint":
                targets = cmds.parentConstraint(con, q=True, targetList=True) or []
            elif constraint_type == "orientConstraint":
                targets = cmds.orientConstraint(con, q=True, targetList=True) or []
            elif constraint_type == "pointConstraint":
                targets = cmds.pointConstraint(con, q=True, targetList=True) or []
            elif constraint_type == "scaleConstraint":
                targets = cmds.scaleConstraint(con, q=True, targetList=True) or []
            else:
                targets = []
        except Exception:
            targets = []

        if _short_node_name(driver) in {_short_node_name(target) for target in targets}:
            return True
    return False


def restore_rig_connections(module_name):
    """
        Restores space switches, constraints, and output connections stored for module_name.
    :param module_name: name of the module
    :return: int
    """
    data = GLOBAL_RIG_STORE.get(module_name)
    if not data:
        return 0

    restored_count = 0

    for sw in data["switches"]:
        driven = sw["driven"]
        attr_name = sw["attr_name"]
        ctype = sw["constraint_type"]

        target_enum_pairs = sw.get("target_enum_pairs", [])
        if not target_enum_pairs and "targets" in sw:
            target_enum_pairs = [[t, t] for t in sw["targets"]]

        if cmds.objExists(driven):
            if _space_switch_exists_in_scene(sw):
                continue

            valid_targets = []
            valid_enum_names = []
            for t, disp in target_enum_pairs:
                if t and cmds.objExists(t):
                    valid_targets.append(t)
                    valid_enum_names.append(disp)

            if valid_targets:
                try:
                    create_space_switch(
                        driven=driven,
                        targets=valid_targets,
                        attr_name=attr_name,
                        constraint_type=ctype,
                        enum_names=valid_enum_names
                    )
                    restored_count += 1
                except Exception as e:
                    print(f"[Warning] Failed to restore space switch on {driven}: {e}")

    for con_data in data["constraints"]:
        driver = con_data["driver"]
        driven = con_data["driven"]
        ctype = con_data["constraint_type"]
        if cmds.objExists(driver) and cmds.objExists(driven):
            try:
                if _constraint_exists(driver, driven, ctype):
                    continue
                if ctype == "parentConstraint":
                    cmds.parentConstraint(driver, driven, mo=True)
                elif ctype == "orientConstraint":
                    cmds.orientConstraint(driver, driven, mo=True)
                elif ctype == "pointConstraint":
                    cmds.pointConstraint(driver, driven, mo=True)
                elif ctype == "scaleConstraint":
                    cmds.scaleConstraint(driver, driven, mo=True)
                restored_count += 1
            except Exception as e:
                print(f"[Warning] Failed to restore external constraint {ctype} from {driver} to {driven}: {e}")

    for conn in data["connections"]:
        src = conn["src"]
        dst = conn["dst"]
        src_node = src.split(".")[0]
        dst_node = dst.split(".")[0]
        if cmds.objExists(src_node) and cmds.objExists(dst_node):
            try:
                if cmds.isConnected(src, dst):
                    continue
                attr = src.split(".")[-1]
                if not cmds.attributeQuery(attr, node=src_node, exists=True):
                    cmds.addAttr(src_node, ln=attr, at="double", k=True)
                _connect_attr_once(src, dst, force=True)
                restored_count += 1
            except Exception as e:
                print(f"[Warning] Failed to restore connection from {src} to {dst}: {e}")

    # Re-insert this module's controls into space switches on other modules
    _restore_orphaned_space_switch_roles(module_name)

    return restored_count


def rig_clavicle_module(side, body_joint_map, parent_ctrl=None):
    """
        Builds the Clavicle control setup.
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :param parent_ctrl: parent control node name
    :return: None
    """
    side_prefix_title = "Left" if side == "l" else "Right"
    clav_jnt = body_joint_map.get(f"{side_prefix_title}Shoulder", {}).get("joint") if body_joint_map else None
    if not clav_jnt or not cmds.objExists(clav_jnt):
        clav_jnt = f"{side}_clavicle"

    if not clav_jnt or not cmds.objExists(clav_jnt):
        return

    spine_tip = body_joint_map.get("Spine2", {}).get("joint") if body_joint_map else "spine5_Tip"
    if not spine_tip or not cmds.objExists(spine_tip):
        spine_tip = "spine5_Tip"
    spine_tip_ctrl = parent_ctrl or (f"{spine_tip}_ctrl" if cmds.objExists(f"{spine_tip}_ctrl") else None)

    clav_ctrl = f"{side}_clavicle_ctrl"
    if not cmds.objExists(clav_ctrl):
        created = create_joint_controls(
            [clav_jnt],
            control_shape="cube",
            root_parent=spine_tip_ctrl
        )
        if created:
            clav_ctrl = created[0]["ctrl"]
            # If arm exists, snap clavicle control to upper arm position
            upperarm_slot = f"{side_prefix_title}Arm"
            upperarm = body_joint_map.get(upperarm_slot, {}).get("joint") if body_joint_map else None
            if upperarm and cmds.objExists(upperarm):
                snap_ctrl_cvs_to_child(clav_ctrl, upperarm)

    save_module_metadata(f"{side_prefix_title} Clavicle", {
        "joints": [clav_jnt],
        "parent": spine_tip_ctrl or "",
        "built": True
    })


def remove_clavicle_module(side, body_joint_map):
    """
        Removes the Clavicle control setup.
    :param side: left or right side (l/r)
    :param body_joint_map: body joint mapping dictionary
    :return: int
    """
    side_prefix_title = "Left" if side == "l" else "Right"
    clav_jnt = body_joint_map.get(f"{side_prefix_title}Shoulder", {}).get("joint") if body_joint_map else None
    if not clav_jnt:
        clav_jnt = f"{side}_clavicle"

    return _delete_module_from_metadata(
        f"{side_prefix_title} Clavicle",
        [f"{side}_clavicle_ctrl_pad"],
        [f"{side}_clavicle_ctrl"]
    )

