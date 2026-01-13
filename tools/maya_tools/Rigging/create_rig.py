import re
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math
from maya_tools.Rigging.mocap import setup_hik

def get_world_position(obj):
    """
    Gets the world position
    :param obj: name of object
    :return:
    """
    pos = cmds.xform(obj, q=True, ws=True, t=True)
    return om.MVector(pos)


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


def snap_ctrl_cvs_to_child(ctrl, child_joint, flip_direction=False):
    """
        Snaps control CVs so that:
      - Child-facing CVs align to the child joint X
      - Opposite CVs align to the control pivot X
    :param ctrl: ctrl to edit
    :param child_joint: child joint to offset cvs towards
    :param flip_direction: If True, reverses which side is considered child-facing (useful for legs or mirrored controls)
    :return:
    """

    # Get the control pivot position in world space
    ctrl_pos = cmds.xform(ctrl, q=True, ws=True, t=True)

    # Get child joint position in world space
    child_pos = cmds.xform(child_joint, q=True, ws=True, t=True)

    # Compute child X relative to control pivot
    target_x = child_pos[0] - ctrl_pos[0]

    if abs(target_x) < 1e-5:
        return

    direction = 1 if target_x > 0 else -1
    if flip_direction:
        direction *= -1

    # Get all CVs
    shapes = cmds.listRelatives(ctrl, s=True, ni=True) or []
    cvs = []
    for shape in shapes:
        if cmds.nodeType(shape) != "nurbsCurve":
            continue
        cvs.extend(cmds.ls(f"{shape}.cv[*]", fl=True))

    if not cvs:
        cmds.warning(f"No CVs found under {ctrl}")
        return

    # Snap CVs
    for cv in cvs:
        cv_pos = cmds.pointPosition(cv, local=True)
        if cv_pos[0] * direction > 0:
            delta_x = target_x - cv_pos[0]
        else:
            delta_x = -cv_pos[0]
        cmds.xform(cv, relative=True, translation=(delta_x, 0, 0))


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
        new_chain = []
        for jnt in chain[:count]:
            base = jnt.split("|")[-1]
            base = re.sub(r'\d+$', '', base)
            base = base.replace("_jnt", "")
            new_name = f"{base}_{suffix}"
            if cmds.objExists(new_name):
                cmds.delete(new_name)
            new_chain.append(cmds.rename(jnt, new_name))

        # remove any children outside this chain
        for jnt in new_chain:
            kids = cmds.listRelatives(jnt, c=True, type="joint") or []
            for k in kids:
                if k not in new_chain:
                    cmds.delete(k)

        return new_chain

    fk_joints = rename_chain(fk_chain, "fk", joint_count)
    ik_joints = rename_chain(ik_chain, "ik", joint_count)
    driver_joints = rename_chain(driver_chain, "driver", joint_count)
    for jnt in fk_joints + ik_joints + driver_joints:
        if cmds.objExists(jnt) and cmds.nodeType(jnt) == "joint":
            cmds.setAttr(f"{jnt}.drawStyle", 2)

    fk_ctrls = create_joint_controls(fk_joints, control_shape="cube", root_parent=root_parent)
    for i, jnt in enumerate(fk_joints):
        if joint_count > 3:
            if jnt != fk_joints[-1]:
                snap_ctrl_cvs_to_child(fk_ctrls[i]["ctrl"], fk_ctrls[i + 1]["pad"], flip_direction=True)
                if jnt != fk_joints[-2]:
                    scale_ctrl_cvs_local(fk_ctrls[i]["ctrl"], scale=(1500, 1.0, 1.0))
                else:
                    scale_ctrl_cvs_local(fk_ctrls[i]["ctrl"], [-2.5, 1, 1])
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
    for i in range(joint_count):
        con = cmds.orientConstraint(
            fk_joints[i],
            ik_joints[i],
            driver_joints[i],
            mo=False,
            n=f"{driver_joints[i]}_orientConstraint"
        )[0]

        # Set shortest rotation path
        cmds.setAttr(f"{con}.interpType", 2)

        cmds.scaleConstraint(
            fk_joints[i],
            ik_joints[i],
            driver_joints[i],
            mo=False
        )
        blend_constraints.append(con)

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
        cmds.addAttr(switch_ctrl_name, longName="ikFkBlend", attributeType="float", min=0, max=1, dv=0)
        cmds.setAttr(f"{switch_ctrl_name}.ikFkBlend", e=True, keyable=True)

    # connect to all orient constraints
    for con in blend_constraints:
        weights = cmds.orientConstraint(con, q=True, weightAliasList=True)

        if weights and len(weights) >= 2:
            rev_node = cmds.createNode("reverse", n=f"{con}_rev")
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{rev_node}.inputX")
            cmds.connectAttr(f"{rev_node}.outputX", f"{con}.{weights[0]}")
            cmds.connectAttr(f"{switch_ctrl_name}.ikFkBlend", f"{con}.{weights[1]}")

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


def ensure_rfl_attrs(ik_leg_ctrl):
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
        connects the attrs for the reverse foot lock setup
    :param ik_leg_ctrl: actual ik leg ctrl
    :param rfl_joints: heel > ankle RFL bones
    :return:
    """

    heel_sdk = f"{rfl_joints['heel']}_ctrl_sdk_pad"
    toe_sdk = f"{rfl_joints['toe']}_ctrl_sdk_pad"
    toe_tip_sdk = f"{rfl_joints['toeTip']}_ctrl_sdk_pad"
    inner_bank_sdk = f"{rfl_joints['innerBank']}_ctrl_sdk_pad"
    outer_bank_sdk = f"{rfl_joints['outerBank']}_ctrl_sdk_pad"

    foot_roll = f"{ik_leg_ctrl}.footRoll"

    set_sdk(foot_roll, f"{heel_sdk}.rotateX", [(0, 0)])
    set_sdk(foot_roll, f"{toe_sdk}.rotateZ", [(0, 0)])
    set_sdk(foot_roll, f"{toe_tip_sdk}.rotateZ", [(0, 0)])

    # Heel down (-1)
    set_sdk(
        foot_roll,
        f"{heel_sdk}.rotateX",
        [(-1, -45)]
    )

    # Toe roll (.3)
    set_sdk(
        foot_roll,
        f"{toe_sdk}.rotateZ",
        [(0.3, 20)]
    )

    # Toe tip (1)
    set_sdk(
        foot_roll,
        f"{toe_tip_sdk}.rotateZ",
        [(1, 45)]
    )

    # Lock toe at end
    set_sdk(
        foot_roll,
        f"{toe_sdk}.rotateZ",
        [(1, 0)]
    )

    foot_bank = f"{ik_leg_ctrl}.footBank"

    # Zero
    set_sdk(foot_bank, f"{inner_bank_sdk}.rotateZ", [(0, 0)])
    set_sdk(foot_bank, f"{outer_bank_sdk}.rotateZ", [(0, 0)])

    # Bank out (-1)
    set_sdk(
        foot_bank,
        f"{outer_bank_sdk}.rotateZ",
        [(-1, -45)]
    )

    # Bank in (1)
    set_sdk(
        foot_bank,
        f"{inner_bank_sdk}.rotateZ",
        [(1, 45)]
    )

    toe_swivel = f"{ik_leg_ctrl}.toeSwivel"

    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(0, 0)])
    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(-1, -45)])
    set_sdk(toe_swivel, f"{toe_tip_sdk}.rotateY", [(1, 45)])

    cmds.setAttr(foot_roll, 0)
    cmds.setAttr(foot_bank, 0)
    cmds.setAttr(toe_swivel, 0)
    show_rfl_ctrls = f"{ik_leg_ctrl}.showRFLCtrls"
    heel_pad = f"{rfl_joints['heel']}_ctrl_pad"
    cmds.connectAttr(show_rfl_ctrls, heel_pad + ".visibility")
    print("[RFL] Set driven keys created successfully.")


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

    rfl_joints_dict = {"heel": side + "_heel_RFL", "ankle": side + "_ankle_RFL", "toe": side + "_toe_RFL",
                       "toeTip": side + "_toeTip_RFL",
                       "innerBank": side + "_innerBank_RFL", "outerBank": side + "_outerBank_RFL", }

    setup_rfl_sdks(ik_leg_ctrl, rfl_joints_dict)
    print(f"[RFL] IK, controls, and constraints built for {side}")


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

            cmds.connectAttr(f"{ctrl}.ShowSubCtrl", f"{sub_pad}.visibility", force=True)

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
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag else [0, 0, 0]


def cross(a, b):
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
    curve = cmds.curve(p=joint_positions, degree=3, name=name + "_crv")

    offset = 0.1
    curves_to_loft = [curve]
    for i in range(1, 2):
        dup_curve = cmds.duplicate(curve, name=f"{name}_crv_dup{i}")[0]
        cmds.move(0, offset * i, 0, dup_curve, r=True)
        curves_to_loft.append(dup_curve)

    # Loft the curves to create a surface
    loft_surf = cmds.loft(curves_to_loft, ch=True, u=True, c=False, ar=True, d=3, ss=1, rn=False, po=0, name=name)[0]

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
    loft_surf = cmds.loft(fwd_crv, bwd_crv, ch=True, u=True, c=False, ar=True, d=3, ss=1, name=f"{name}_surf")[0]

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


def setup_surface_rig(joint_chain, loft_name="eyelid", offset=0.5, region="eyelid", root_parent=None):
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
    cmds.parent(group, "Do_Not_Touch")
    for fj in follicle_joints:
        parent = cmds.listRelatives(fj, p=1, ap=1)[0]
        cmds.parent(parent, group)
    if region == "eyelid" or region == "mouth":
        follicle_joints = follicle_joints[:-1]

    # Create controls and aim them at follicle joints
    joint_to_ctrl = {}
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
                worldUpObject=side + "_eye1",
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
            if region == "mouth":
                if "upper" in joint:
                    root_parent = "head1_ctrl"
                else:
                    root_parent = "jaw_ctrl"
            elif "twist" in region:
                control_shape = "arrow"
            ctrl_data = create_joint_controls(
                joint_list=[joint],
                control_shape=control_shape,
                root_parent=root_parent,
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
    if not region == "eyelid":
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

    return loft_surf, follicle_joints, joint_to_ctrl


def setup_surface_rig_with_drivers(
        joint_list,
        loft_name="eyelid",
        offset=0.5,
        driver_follicle_indices=None,
        side="r",
        region="eyelid",
        root_parent=None
):
    """
        Sets up a driver based surface rig (great for Mouth and eyelid setups)
    :param joint_list: list of joints
    :param loft_name: surface name
    :param offset: amount to offset curves to loft from joints
    :param driver_follicle_indices: mapping indices; see example ( driver_indices = [0, 9, 6, 3, 12, 15, 18, 20])
    :param side: right or left
    :param region: mouth ,eyelid, or other(doesnt matter name)
    :param root_parent: what to parent system to
    :return:
    """
    if region == "eyelid":
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
        driver_index_map = {
            0: "c_upper_lip_main",
            2: "r_upper_lip_main",
            5: "r_lip_corner_main",
            8: "r_lower_lip_main",
            10: "c_lower_lip_main",
            12: "l_lower_lip_main",
            15: "l_lip_corner_main",
            18: "l_upper_lip_main",
        }
    else:
        driver_index_map = {i: joint_list[i] + "_main" for i in range(len(joint_list))}
    """
    Sets up eyelid rig with:
      - Lofted surface
      - Follicles + follicle joints
      - Controls aimed at follicle joints
      - Driver joints duplicated from specific follicle joints
        - Semantic renaming
        - World parent
        - Side-based orientation
        - Skinned to loft surface
        - Controls created
        - Driver-pair constraints to PADs
    """

    loft_surf, follicle_joints, joint_to_ctrl = setup_surface_rig(
        joint_list, loft_name=loft_name, offset=offset, region=region, root_parent=root_parent
    )

    driver_joints = []
    driver_data = {}

    if not driver_follicle_indices:
        driver_bone = joint_list[0].split("1_twist")[0] + "_driver"
        if not cmds.objExists(driver_bone):
            driver_bone = joint_list[0].split("_twist1")[0] + "_driver"

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

        if "r_upper_lip_main" in driver_data:
            con = constrain_pad(
                driver_data["r_upper_lip_main"]["pad"],
                [
                    driver_data["c_upper_lip_main"]["ctrl"],
                    driver_data["r_lip_corner_main"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if "c_upper_lip_main" in w][0]
            corner_w = [w for w in weights if "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.9)
            cmds.setAttr(f"{con}.{corner_w}", 0.1)

        if "l_upper_lip_main" in driver_data:
            con = constrain_pad(
                driver_data["l_upper_lip_main"]["pad"],
                [
                    driver_data["c_upper_lip_main"]["ctrl"],
                    driver_data["l_lip_corner_main"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if "c_upper_lip_main" in w][0]
            corner_w = [w for w in weights if "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.9)
            cmds.setAttr(f"{con}.{corner_w}", 0.1)

        if "r_lower_lip_main" in driver_data:
            con = constrain_pad(
                driver_data["r_lower_lip_main"]["pad"],
                [
                    driver_data["c_lower_lip_main"]["ctrl"],
                    driver_data["r_lip_corner_main"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if "c_lower_lip_main" in w][0]
            corner_w = [w for w in weights if "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.7)
            cmds.setAttr(f"{con}.{corner_w}", 0.3)

        if "l_lower_lip_main" in driver_data:
            con = constrain_pad(
                driver_data["l_lower_lip_main"]["pad"],
                [
                    driver_data["c_lower_lip_main"]["ctrl"],
                    driver_data["l_lip_corner_main"]["ctrl"],
                ]
            )
            weights = cmds.parentConstraint(con, q=True, wal=True)

            center_w = [w for w in weights if "c_lower_lip_main" in w][0]
            corner_w = [w for w in weights if "lip_corner" in w][0]

            cmds.setAttr(f"{con}.{center_w}", 0.7)
            cmds.setAttr(f"{con}.{corner_w}", 0.3)

        cmds.parent("c_upper_lip_ctrl_pad", driver_data["c_upper_lip_main"]["ctrl"])
        cmds.parent("c_lower_lip_ctrl_pad", driver_data["c_lower_lip_main"]["ctrl"])
        cmds.parent("l_lip_corner1_ctrl_pad", driver_data["l_lip_corner_main"]["ctrl"])
        cmds.parent("r_lip_corner1_ctrl_pad", driver_data["r_lip_corner_main"]["ctrl"])
        for each in ["c_upper_lip_ctrl_pad_parentConstraint1",
                     "c_lower_lip_ctrl_pad_parentConstraint1",
                     "r_lip_corner1_ctrl_pad_parentConstraint1",
                     "l_lip_corner1_ctrl_pad_parentConstraint1"]:
            cmds.delete(each)

    return loft_surf, follicle_joints, joint_to_ctrl, driver_data


def create_finger_rigs(finger_joints):
    """
        Creates IK driven FK system for finger joints
    :param finger_joints: finger joints
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
        Renames duplicated finger joints using the ORIGINAL joint names,
        preserving finger indices like _01, _02, _03 exactly.
        """
        new_chain = []

        for src, dup in zip(source_chain, dup_chain):
            src_short = src.split("|")[-1]

            # Detect side
            base = src_short
            if side and src_short.startswith(f"{side}_"):
                base = src_short[len(side) + 1:]

            # Extract finger name and index (thumb_01)
            match = re.match(r"(.*?)(_\d+)$", base)
            if match:
                name_part = match.group(1)
                index_part = match.group(2)
            else:
                name_part = base
                index_part = ""

            new_name = f"{side}_{name_part}{index_part}_{suffix}"
            new_name = new_name.replace("__", "_")

            if cmds.objExists(new_name):
                cmds.delete(new_name)

            new_chain.append(cmds.rename(dup, new_name))

        return new_chain

    for finger in finger_names:
        fk_chain = [j for j in finger_joints if f"_{finger}_" in j]
        fk_chain.reverse()
        if not fk_chain:
            continue

        side = get_side_prefix(fk_chain[0])

        ik_chain = cmds.duplicate(fk_chain, rc=True)
        cmds.parent(ik_chain[0], f"{side}_hand_driver")

        ik_chain = rename_finger_chain_from_source(
            source_chain=fk_chain,
            dup_chain=ik_chain,
            suffix="ik",
            side=side
        )
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

        fk_ctrls = create_joint_controls(fk_chain, control_shape="cube", root_parent=side + "_hand_driver")
        for i, jnt in enumerate(fk_chain):
            if jnt != fk_chain[-1]:

                snap_ctrl_cvs_to_child(fk_ctrls[i]["ctrl"], fk_chain[i + 1])
            else:
                cmds.delete(fk_ctrls[i]["pad"])

        pv_joint = ik_chain[1] if finger == "thumb" else ik_chain[2]
        pv_ctrl_info = create_joint_controls([pv_joint], control_shape="diamond", root_parent=side + "_hand_driver")[0]
        pv_ctrl = pv_ctrl_info['ctrl']

        for c in cmds.listRelatives(pv_joint, type="constraint") or []:
            cmds.delete(c)
        pv_pad = pv_ctrl_info['pad']
        cmds.xform(pv_ctrl, ws=True, t=cmds.xform(pv_joint, q=True, ws=True, t=True))

        offset_pv_pad(pv_pad, side, amount=-5.0)

        start_joint = ik_chain[0] if finger == "thumb" else ik_chain[1]
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
        cmds.parent(ik_ctrl_info['pad'], side + "_hand_driver")
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
            root_ctrl = side + "_hand_driver"
        else:
            root_ctrl = fk_ctrls[0]["ctrl"]
        finger_pv_space = create_composite_space(
            name=pv_pad + "_space",
            parents=[ik_ctrl_info['ctrl'], root_ctrl],
            match_to=pv_ctrl
        )
        cmds.parent(finger_pv_space, side + "_hand_driver")
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


def create_composite_space(name, parents, match_to):
    """
    Creates a transform constrained to multiple parents,
    matched to the driven group.
    """
    grp = cmds.createNode("transform", name=name)

    cmds.delete(cmds.parentConstraint(match_to, grp))
    cmds.parentConstraint(parents, grp, mo=True)

    return grp


def create_space_switch(
        driven,
        targets,
        attr_name="space",
        dup_suffix="_spaceTarget",
        constraint_type="parent"
):
    """
    Builds a space switch where each target gets a matched child transform,
    and those children are the actual constraint drivers.

    Constraint is applied to the driven control's parent group.

    driven = "r_lowerarm_low_pv_ctrl"
    targets = ["r_clavicle1_ctrl", "pelvis_ctrl", "origin_ctrl"]

    create_space_switch(driven, targets, constraint_type="parent")
    create_space_switch(driven, targets, constraint_type="orient")
    """

    if constraint_type not in ("parent", "orient"):
        cmds.error("constraint_type must be 'parent' or 'orient'")

    if not cmds.objExists(driven):
        cmds.error(f"Driven object does not exist: {driven}")

    driven_parent = cmds.listRelatives(driven, p=True)
    if not driven_parent:
        cmds.error(f"Driven object '{driven}' has no parent group to constrain.")

    driven_grp = driven_parent[0]

    # Create enum attribute if missing
    if not cmds.attributeQuery(attr_name, node=driven, exists=True):
        enum_string = ":".join([t.replace("|", "_") for t in targets])
        cmds.addAttr(driven, ln=attr_name, at="enum", enumName=enum_string, k=True)
    else:
        cmds.warning(f"Attribute already exists: {driven}.{attr_name}")

    driver_children = []

    # Pick constraint commands dynamically
    constraint_cmd = cmds.parentConstraint if constraint_type == "parent" else cmds.orientConstraint

    for t in targets:
        if not cmds.objExists(t):
            cmds.error(f"Target does not exist: {t}")

        dup = cmds.createNode(
            "transform",
            name=f"{driven}_{t}{dup_suffix}"
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


def create_rig_space_switches(side):
    """
        base space switches for each side
    :param side: side for setups
    :return:
    """
    pv_ctrl = side + "_knee_pv_ctrl"
    pv_grp = pv_ctrl + "_pad"

    hip_ctrl = "hipswing_ctrl"
    foot_ctrl = side + "_ankle_ik_ctrl"
    origin_ctrl = "origin_ctrl"

    foot_hip_space = create_composite_space(
        name=side + "_leg_pv_footHip_space",
        parents=[foot_ctrl, hip_ctrl],
        match_to=pv_grp
    )
    cmds.parent(foot_hip_space, "Do_Not_Touch")
    create_space_switch(
        driven=pv_ctrl,
        targets=[
            hip_ctrl,
            foot_ctrl,
            origin_ctrl,
            foot_hip_space
        ],
        attr_name="space"
    )

    create_space_switch(
        driven=side + "_clavicle_ctrl",
        targets=[
            "hipswing_ctrl",
            "origin_ctrl",
            "spine5_Tip_ctrl"
        ],
        attr_name="space",
        constraint_type="orient"
    )
    hand_clav_space = create_composite_space(
        name=side + "_arm_pv_handClav_space",
        parents=[side + "_hand_ik_ctrl", side + "_clavicle_ctrl"],
        match_to=side + "_lowerarm_pv_ctrl_pad"
    )
    cmds.parent(hand_clav_space, "Do_Not_Touch")

    create_space_switch(
        driven=side + "_lowerarm_pv_ctrl",
        targets=[
            "hipswing_ctrl",
            "origin_ctrl",
            side + "_clavicle_ctrl",
            hand_clav_space
        ],
        attr_name="space"
    )


def create_eye_aim_setup(
        left_eye_joint="l_eye",
        right_eye_joint="r_eye",
        aim_distance=25
):
    """
    Creates a standard left/right eye aim setup with a shared center aim control.
    """

    for jnt in (left_eye_joint, right_eye_joint):
        if not cmds.objExists(jnt):
            raise RuntimeError(f"Eye joint does not exist: {jnt}")

    created = {}

    l_eye_ctrl_dict = create_joint_controls([left_eye_joint], control_shape="circle", root_parent="head1_ctrl")
    r_eye_ctrl_dict = create_joint_controls([right_eye_joint], control_shape="circle", root_parent="head1_ctrl")

    def create_eye_aim(joint, side):
        # Aim transform
        aim_xform = cmds.createNode(
            "transform",
            name=f"{side}_eye_aim"
        )

        # Match joint
        cmds.delete(cmds.pointConstraint(joint, aim_xform, mo=False))

        # Move forward in local Z
        cmds.move(0, 0, aim_distance, aim_xform, r=True, os=True)

        aim_ctrl = create_joint_controls([aim_xform], control_shape="circle", root_parent="head1_ctrl")

        return aim_xform, aim_ctrl

    l_aim_xform, l_aim_ctrl = create_eye_aim(left_eye_joint, "l")
    r_aim_xform, r_aim_ctrl = create_eye_aim(right_eye_joint, "r")

    cmds.aimConstraint(
        l_aim_ctrl[0]["ctrl"],
        l_eye_ctrl_dict[0]["pad"],
        aimVector=(0, 0, 1),
        upVector=(0, 1, 0),
        worldUpType="objectrotation",
        worldUpObject="head1_ctrl",
        worldUpVector=(0, 1, 0),
        mo=True
    )
    cmds.aimConstraint(
        r_aim_ctrl[0]["ctrl"],
        r_eye_ctrl_dict[0]["pad"],
        aimVector=(0, 0, 1),
        upVector=(0, -1, 0),
        worldUpType="objectrotation",
        worldUpObject="head1_ctrl",
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
    eye_ctrl_dict = create_joint_controls(["eye_aim"], control_shape="circle", root_parent="head1_ctrl")
    cmds.parent(l_aim_ctrl[0]["ctrl"], r_aim_ctrl[0]["ctrl"], eye_ctrl_dict[0]["ctrl"])

    r_eye_ctrl = r_eye_ctrl_dict[0]["ctrl"]
    l_eye_ctrl = l_eye_ctrl_dict[0]["ctrl"]
    strip_ctrl_shape_and_rename(r_eye_ctrl)
    strip_ctrl_shape_and_rename(l_eye_ctrl)
    cmds.delete([l_aim_xform, r_aim_xform, center_aim])

    return created


def strip_ctrl_shape_and_rename(ctrl):
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


def setup_jaw_lip_driver(jaw_ctrl, lip_driver_ctrls, lip_ctrl_dict):
    """
    Initial setup for jaw/lip driving.
    """

    if not cmds.objExists(jaw_ctrl):
        raise RuntimeError(f"Jaw control does not exist: {jaw_ctrl}")

    def add_attr(attr, **kwargs):
        if not cmds.attributeQuery(attr, node=jaw_ctrl, exists=True):
            cmds.addAttr(jaw_ctrl, longName=attr, **kwargs)
            cmds.setAttr(f"{jaw_ctrl}.{attr}", e=True, keyable=True)

    add_attr("jawOpen", at="double", min=0, max=1, dv=0)
    add_attr("lipShut", at="double", min=0, max=1, dv=0)
    add_attr("lipSubControls", at="bool", dv=0)

    for jnt in lip_ctrl_dict.keys():
        lip_pad = lip_ctrl_dict[jnt]
        cmds.connectAttr(jaw_ctrl + ".lipSubControls", lip_pad + '.visibility')
    jaw_pad = jaw_ctrl + "_sdk_pad"
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
        upper_con = cmds.parentConstraint(
            ['head1_ctrl', jaw_ctrl],
            ctrl + "_pad",
            mo=True
        )[0]
        cmds.setAttr(f"{upper_con}.interpType", 2)
        upper_weights = cmds.parentConstraint(upper_con, q=True, wal=True)

        # Upper
        upper_head_w = [w for w in upper_weights if "head1" in w][0]
        upper_jaw_w = [w for w in upper_weights if "jaw" in w][0]
        jaw_attr = f"{jaw_ctrl}.lipShut"

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
        root_parent="head1_ctrl"
    )[0]
    main_ctrl = main_ctrl_dict["ctrl"]
    main_con = cmds.parentConstraint("head1_ctrl", jaw_ctrl, main_ctrl_dict["pad"], mo=True)[0]
    cmds.setAttr(f"{main_con}.interpType", 2)
    for each in [upper_ctrl, lower_ctrl]:
        sdk_pad = each + "_sdk_pad"
        cmds.connectAttr(f"{main_ctrl}.translate", f"{sdk_pad}.translate")
        cmds.connectAttr(f"{main_ctrl}.rotate", f"{sdk_pad}.rotate")

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
    twist_bone = cmds.duplicate(driver_bone, name=driver_bone.replace("driver", "twist_driver"))[0]
    children = cmds.listRelatives(twist_bone, c=True, f=True) or []
    if children:
        cmds.delete(children)

    if "lower" in driver_bone or "knee" in driver_bone:
        parent = child_bone
    cmds.pointConstraint(child_bone, twist_bone, mo=False)

    x_val=1
    if "knee" in driver_bone and driver_bone[0] == "l":
        x_val = -1
    cmds.aimConstraint(driver_bone, twist_bone,
                       aimVector=(x_val, 0, 0),
                       upVector=(0, 1, 0),
                       worldUpType="objectrotation",
                       worldUpObject=parent,
                       worldUpVector=(0, 1, 0),
                       mo=True)

    if cmds.objExists(surface):
        skin = cmds.skinCluster(twist_bone, driver_bone, surface, toSelectedBones=True)[0]

        cvs = cmds.ls(f"{surface}.cv[0:3][0:3]", flatten=True)

        num_cvs = len(cvs)

        for i, cv in enumerate(cvs):
            weight_twist = 1.0 - (i / (num_cvs - 1))
            weight_driver = 1.0 - weight_twist
            cmds.skinPercent(skin, cv, transformValue=[(twist_bone, weight_twist), (driver_bone, weight_driver)])

    return twist_bone


def hik_map_to_rig_args(joint_map):
    def j(slot):
        return joint_map.get(slot, {}).get("joint")

    arm_joints = [
        j("LeftArm"), j("RightArm"),
        j("LeftShoulder"), j("RightShoulder"),
        j("LeftForeArm"), j("RightForeArm"),
        j("LeftHand"), j("RightHand")
    ]

    leg_joints = {
        "l": [j("LeftUpLeg"), j("LeftLeg"), j("LeftFoot"), j("LeftToeBase"), None],
        "r": [j("RightUpLeg"), j("RightLeg"), j("RightFoot"), j("RightToeBase"), None]
    }

    spine_joints = [j("Spine"), j("Spine1"), j("Spine2"), j("Spine3")]
    spine_joints = [s for s in spine_joints if s]

    return {
        "arm_joints": arm_joints,
        "leg_joints": leg_joints,
        "spine_joints": spine_joints,
        "root_joint": j("Hips") or "pelvis"
    }


def create_full_rig(arm_joints=['l_upperarm', 'r_upperarm',
        'l_clavicle', 'r_clavicle',
        'l_lowerarm', 'r_lowerarm',
        'l_hand', 'r_hand']):
    setup_hik.t_pose_character(arm_joints[0], arm_joints[1], arm_joints[2], arm_joints[3], arm_joints[4], arm_joints[5],
                               arm_joints[6], arm_joints[7])

    create_joint_controls(
        joint_list=["origin", "pelvis"],
        control_shape="circle"
    )

    for ctrl_name in ["origin_ctrl", "pelvis_ctrl"]:
        scale_ctrl_cvs_local(ctrl_name, [25, 25, 25])

    create_joint_controls(
        ["spine1", "spine3", "spine5"],
        control_shape="sphere",
        root_parent="pelvis_ctrl",
        sub_ctrls=True
    )

    create_joint_controls(
        ["hipswing"],
        control_shape="sphere",
        root_parent="spine1_ctrl"
    )

    create_joint_controls(
        ["spine5_Tip"],
        control_shape="sphere",
        root_parent="spine5_ctrl"
    )

    create_joint_controls(
        joint_list=[
            "neck1", "neck2", "head1", "jaw",
            "tongue1", "tongue2", "tongue3", "tongue4"
        ],
        control_shape="circle",
        root_parent="spine5_Tip_ctrl"
    )
    create_space_switch(
        driven="neck1_ctrl",
        targets=[
            "hipswing_ctrl",
            "origin_ctrl",
            "spine5_Tip_ctrl"
        ],
        attr_name="space",
        constraint_type="orient"
    )
    create_space_switch(
        driven="head1_ctrl",
        targets=[
            "hipswing_ctrl",
            "origin_ctrl",
            "neck2_ctrl",
            "spine5_Tip_ctrl"
        ],
        attr_name="space",
        constraint_type="orient"
    )

    create_eye_aim_setup("l_eye", "r_eye")

    for side in ["l", "r"]:
        clav_ctrl = create_joint_controls(
            [f"{side}_clavicle"],
            control_shape="cube",
            root_parent="spine5_Tip_ctrl"
        )[0]

        snap_ctrl_cvs_to_child(
            clav_ctrl["ctrl"],
            f"{side}_upperarm"
        )

        arm_chain = [
            f"{side}_upperarm",
            f"{side}_lowerarm",
            f"{side}_hand"
        ]

        leg_chain = [
            f"{side}_thigh",
            f"{side}_knee",
            f"{side}_ankle",
            f"{side}_toe",
            f"{side}_toeTip"
        ]

        create_ik_fk_limb(arm_chain, f"{side}_clavicle_ctrl")
        create_ik_fk_limb(leg_chain, "hipswing_ctrl")

        finger_joints = [
            f"{side}_thumb_04", f"{side}_thumb_03", f"{side}_thumb_02", f"{side}_thumb_01",
            f"{side}_index_05", f"{side}_index_04", f"{side}_index_03", f"{side}_index_02", f"{side}_index_01",
            f"{side}_middle_05", f"{side}_middle_04", f"{side}_middle_03", f"{side}_middle_02", f"{side}_middle_01",
            f"{side}_ring_05", f"{side}_ring_04", f"{side}_ring_03", f"{side}_ring_02", f"{side}_ring_01",
            f"{side}_pinky_05", f"{side}_pinky_04", f"{side}_pinky_03", f"{side}_pinky_02", f"{side}_pinky_01"
        ]

        create_finger_rigs(finger_joints)

        build_rfl_ik_and_constraints(
            side=side,
            ik_leg_ctrl=f"{side}_ankle_ik_ctrl",
            ik_leg_joints=[
                f"{side}_ankle_ik",
                f"{side}_toe_ik",
                f"{side}_toeTip_ik"
            ],
            rfl_joints=[
                f"{side}_heel_RFL",
                f"{side}_outerBank_RFL",
                f"{side}_innerBank_RFL",
                f"{side}_toe_RFL",
                f"{side}_toeTip_RFL",
                f"{side}_ankle_RFL"
            ]
        )

        create_rig_space_switches(side)

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

        driver_indices = [0, 9, 6, 3, 12, 15, 18, 20]

        setup_surface_rig_with_drivers(
            eyelid_joints,
            loft_name=f"{side}_eyelid",
            region="eyelid",
            side=side,
            offset=0.5,
            driver_follicle_indices=driver_indices,
            root_parent=f"{side}_eye1"
        )

        brow_joints = [f"{side}_brow{i}" for i in range(1, 6)]
        setup_surface_rig_with_drivers(
            brow_joints,
            loft_name=f"{side}_brow",
            offset=0.5,
            side=side,
            region="brow",
            driver_follicle_indices=list(range(len(brow_joints))),
            root_parent="head1_ctrl"
        )

        upperarm_joints = [side + "_upperarm1_twist", side + "_upperarm2_twist", side + "_upperarm3_twist",
                           side + "_upperarm4_twist"]
        setup_surface_rig_with_drivers(
            upperarm_joints,
            loft_name=f"{side}_upperarm_twist",
            offset=0.5,
            side=side,
            region="upperarm",
            driver_follicle_indices=None,
            root_parent=side + "_upperarm_driver"
        )

        lowerarm_joints = [side + "_lowerarm1_twist", side + "_lowerarm2_twist", side + "_lowerarm3_twist",
                           side + "_lowerarm4_twist"]
        setup_surface_rig_with_drivers(
            lowerarm_joints,
            loft_name=f"{side}_lowerarm_twist",
            offset=0.5,
            side=side,
            region="lowerarm",
            driver_follicle_indices=None,
            root_parent=side + "_lowerarm_driver"
        )

        thigh_joints = [side + "_thigh_twist1", side + "_thigh_twist2", side + "_thigh_twist3", side + "_thigh_twist4"]
        setup_surface_rig_with_drivers(
            thigh_joints,
            loft_name=f"{side}_thigh_twist",
            offset=0.5,
            side=side,
            region="thigh",
            driver_follicle_indices=None,
            root_parent="hipswing_ctrl"
        )
        knee_joints = [side + "_knee_twist1", side + "_knee_twist2", side + "_knee_twist3"]
        knee_ctrl_data = create_joint_controls(
            knee_joints,
            control_shape="arrow",
            root_parent=side + "_knee_driver",
            sub_ctrls=False,
            keep_constraint=True
        )
        knee_twist = create_twist_driver(driver_bone=side + "_knee_driver",
                                         child_bone=side + "_ankle_driver",
                                         parent=side + "_thigh_driver",
                                         surface=side + "_knee_surface")
        md_node = cmds.createNode("multiplyDivide", name=f"{side}_knee_twist_md")
        cmds.setAttr(f"{md_node}.operation", 1)

        # Set Input2 values as in your screenshot
        cmds.setAttr(f"{md_node}.input2X", 0.333)
        cmds.setAttr(f"{md_node}.input2Y", 0.667)
        cmds.setAttr(f"{md_node}.input2Z", 1)

        # Connect knee_twist.rotateX to all Input1 channels
        for idx, channel in enumerate(["X", "Y", "Z"]):
            cmds.connectAttr(f"{knee_twist}.rotateX", f"{md_node}.input1{channel}")

        # Connect outputs to each corresponding knee_pad.rotateX
        for i, kj in enumerate(knee_joints):
            knee_pad = knee_ctrl_data[i]["sdk"]
            output_attr = f"output{['X', 'Y', 'Z'][i]}"
            cmds.connectAttr(f"{md_node}.{output_attr}", f"{knee_pad}.rotateX")

    mouth_joints = [
        'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
        'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
        'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
        'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
    ]

    loft_surf, follicle_joints, lip_ctrls, driver_data = setup_surface_rig_with_drivers(
        mouth_joints,
        loft_name="mouth",
        offset=0.5,
        driver_follicle_indices=[0, 2, 5, 8, 10, 12, 15, 18],
        region="mouth",
        root_parent="head1_ctrl"
    )

    face_joints = [
        'r_undereye_3', 'r_undereye_4', 'r_undereye_5', 'r_undereye_1',
        'r_ear_base1', 'r_ear_base', 'l_upper_cheek', 'r_undereye_2',
        'l_lower_cheek', 'l_inner_cheek', 'r_upper_nose',
        'l_inner_cheek_smile', 'r_inner_cheek_smile', 'r_inner_cheek',
        'r_upper_cheek', 'r_lower_cheek',
        'r_undereye_8', 'r_undereye_7', 'r_undereye_6',
        'l_undereye_8', 'l_undereye_7', 'l_undereye_6',
        'l_undereye_5', 'l_undereye_4', 'l_undereye_3',
        'l_undereye_2', 'l_undereye_1', "l_mandible", "r_mandible",
        'l_ear_base1', 'upper_teeth', 'l_upper_nose', 'l_ear_base', "nose_root"
    ]

    for fj in face_joints:
        ctrl_data = create_joint_controls(
            [fj],
            control_shape="sphere",
            root_parent="head1_ctrl",
            sub_ctrls=False,
            keep_constraint=True
        )
        scale_ctrl_cvs_local(ctrl_data[0]["ctrl"], [0.2, 0.2, 0.2])
    nose_children = cmds.listRelatives("nose_root", c=1, type="joint")
    for fj in nose_children:
        ctrl_data = create_joint_controls(
            [fj],
            control_shape="sphere",
            root_parent="nose_root_ctrl",
            sub_ctrls=False,
            keep_constraint=True
        )
        scale_ctrl_cvs_local(ctrl_data[0]["ctrl"], [0.2, 0.2, 0.2])
    jaw_joints =['r_chin', "l_chin", "lower_teeth", "l_mandible", "r_mandible"]
    for jj in jaw_joints:
        ctrl_data = create_joint_controls(
            [jj],
            control_shape="sphere",
            root_parent="jaw_ctrl",
            sub_ctrls=False,
            keep_constraint=True
        )
        scale_ctrl_cvs_local(ctrl_data[0]["ctrl"], [0.2, 0.2, 0.2])
    setup_jaw_lip_driver("jaw_ctrl",
                         ["c_upper_lip_main_ctrl", "c_lower_lip_main_ctrl", "r_lip_corner_main_ctrl",
                          "l_lip_corner_main_ctrl"], lip_ctrls)


create_full_rig()
