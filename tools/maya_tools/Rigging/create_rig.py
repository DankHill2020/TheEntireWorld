"""Composable Maya rig construction and module lifecycle operations."""

from __future__ import annotations

from maya_tools.Rigging import create_rig_core as _core
from maya_tools.Rigging.create_rig_core import (
    GLOBAL_RIG_STORE,
    MODULE_STORE_NODE,
    _connect_attr_once,
    _clear_sdk_anim_curves,
    _flip_joint_label_side,
    _get_joint,
    _get_joint_hierarchy,
    _get_side_enum_map,
    _swap_first_lr_character,
    apply_side_color_override,
    bake_joint_orient_to_rotate,
    build_enum_names_for_space_targets,
    build_rfl_ik_and_constraints,
    cmds,
    constrain_controls_to_two_parents,
    create_bi_arrow_ctrl,
    create_composite_space,
    create_cube_ctrl,
    create_diamond_ctrl,
    create_arm_space_switches,
    create_eye_aim_setup,
    create_finger_rigs,
    create_ik_fk_limb,
    create_joints_along_curve,
    create_joint_controls,
    create_leg_space_switches,
    create_loft_surface_with_follicle_joints,
    create_prism_ctrl,
    create_rig_space_switches,
    create_sphere_ctrl,
    create_space_switch,
    create_surface_from_joints_original,
    create_twist_driver,
    cross,
    custom_widgets,
    enum_attrs,
    ensure_rfl_attrs,
    find_ik_handle_constrained_by_ctrl,
    get_ctrl_shape_cvs,
    get_nose_joints,
    get_region_size_from_joints,
    get_side_prefix,
    json,
    mirror_face_joints,
    mirror_joint_yz_behavior_with_label_flip,
    normalize,
    offset_pv_pad,
    orient_control_pad_to_world_safely,
    os,
    re,
    restore_all_control_cv_positions,
    scale_ctrl_to_region,
    scale_ctrl_cvs_local,
    set_sdk,
    setup_hik,
    setup_jaw_lip_driver,
    setup_rfl_sdks,
    setup_show_twist_ctrls,
    setup_spine_segment_stretch,
    setup_surface_rig,
    setup_surface_rig_with_drivers,
    snap_to_joint_matrix,
    snap_ctrl_cvs_to_child,
    store_all_control_cv_positions,
    strip_ctrl_shape_and_rename,
)

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
        keep_constraint=False
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

    # brow_main is only a snap target used to place the real control hierarchy.
    # Leaving it in world creates an inert top-level scaffold node.
    if cmds.objExists(brow_main_transform):
        cmds.delete(brow_main_transform)

    return {
        "group": "",
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


# Keep the historical import surface stable while the larger modular builders live
# in a focused implementation module.  The binding supplies the low-level helpers
# above to that module without duplicating their definitions.
from maya_tools.Rigging import create_rig_modules as _create_rig_modules

_create_rig_modules.bind_runtime(globals())
__all__ = list(_create_rig_modules.__all__)
from maya_tools.Rigging.create_rig_modules import *  # noqa: F401,F403,E402


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
    Delete unused scaffold and temporary nodes without removing rig drivers.

    A ``*_main`` joint with a matching control (or parented beneath a control)
    is a persistent surface driver used by the lips, brows, and eyelids.  It
    must survive even if Maya does not report its skinCluster through a direct
    ``listConnections`` query.
    """
    to_delete = []
    legacy_snap_nodes = {"l_brow_main", "r_brow_main", "lip_main"}

    def is_unused_scaffold(node):
        nt = cmds.nodeType(node)
        short_name = node.rsplit("|", 1)[-1].split(":")[-1]
        if short_name in legacy_snap_nodes and nt in ("transform", "joint"):
            return True
        if nt == "transform":
            shapes = cmds.listRelatives(node, shapes=True) or []
            if not shapes:
                return True

        if nt not in ("transform", "joint"):
            return False

        is_skinned = bool(cmds.listConnections(node, type="skinCluster"))
        is_constrained = bool(cmds.listConnections(node, type="constraint"))
        all_descendants = cmds.listRelatives(node, ad=True, fullPath=True) or []
        has_ctrl_descendants = any("_ctrl" in desc.lower() for desc in all_descendants)
        has_matching_ctrl = cmds.objExists(node + "_ctrl")
        parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
        is_parented_to_ctrl = any("_ctrl" in parent.lower() for parent in parents)

        return not any((
            is_skinned,
            is_constrained,
            has_ctrl_descendants,
            has_matching_ctrl,
            is_parented_to_ctrl,
        ))

    # 1. Gather nodes ending in '_main'
    for node in cmds.ls("*_main") or []:
        if cmds.objExists(node) and not cmds.objExists(node + "_ctrl") and is_unused_scaffold(node):
            to_delete.append(node)

    # 2. Gather nodes containing '_temp'
    for node in cmds.ls("*_temp*") or []:
        if cmds.objExists(node) and is_unused_scaffold(node):
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

        missing_drivers = [driver for driver in drivers if not cmds.objExists(driver)]
        if missing_drivers:
            raise RuntimeError(
                "Mouth surface was created without required main lip controls: {}".format(
                    ", ".join(missing_drivers)
                )
            )
        if not cmds.objExists(jaw_ctrl):
            raise RuntimeError("Mouth setup requires jaw control: {}".format(jaw_ctrl))
        if not lip_ctrls:
            raise RuntimeError("Mouth setup did not create any lip sub-controls.")

        jaw_lip_data = setup_jaw_lip_driver(
            jaw_ctrl,
            drivers,
            lip_ctrls,
            head_ctrl=parent_ctrl,
        )
        main_ctrl = (jaw_lip_data or {}).get("main_ctrl", "lip_main_ctrl")
        if not cmds.objExists(main_ctrl):
            raise RuntimeError("Mouth setup did not create the main lip control: {}".format(main_ctrl))
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

    # Keep the principal nose controls together beneath the root control. The
    # pads preserve their world transforms and remain the animation offsets.
    nose_root_ctrl = "nose_root_ctrl"
    nose_control_pads = (
        "nose_upper_ctrl_pad",
        "nose_base_ctrl_pad",
        "nose_tip_ctrl_pad",
        "l_nostril_ctrl_pad",
        "r_nostril_ctrl_pad",
    )
    if cmds.objExists(nose_root_ctrl):
        root_long = (cmds.ls(nose_root_ctrl, long=True) or [nose_root_ctrl])[0]
        for pad in nose_control_pads:
            if not cmds.objExists(pad):
                continue
            pad_long = (cmds.ls(pad, long=True) or [pad])[0]
            current_parent = cmds.listRelatives(pad_long, parent=True, fullPath=True) or []
            if not current_parent or current_parent[0] != root_long:
                cmds.parent(pad_long, root_long, absolute=True)

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

    limb_data = {}
    if len(arm_chain) >= 3 and cmds.objExists(clav_ctrl):
        limb_data = create_ik_fk_limb(arm_chain, clav_ctrl)

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
        "cleanup_nodes": (limb_data.get("stretch") or {}).get("nodes", []),
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
    "multDoubleLinear",
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

        for related_node in related:
            # Keep Maya's resolved DAG path for API queries. Converting a
            # nested node such as |Do_Not_Touch|mouth_surface_grp|mouth to the
            # short name "mouth" can make nodeType fail even when objExists
            # previously reported a match.
            resolved_nodes = cmds.ls(related_node, long=True) or []
            for resolved in resolved_nodes:
                rel = _short_node_name(resolved)
                if not rel or rel in module_nodes:
                    continue
                try:
                    node_type = cmds.nodeType(resolved)
                except RuntimeError:
                    # Cleanup metadata is advisory. A stale history/DAG entry
                    # must never fail an otherwise successful rig build.
                    continue
                if _is_rfl_pivot_joint(rel):
                    continue
                matches_prefix = any(rel.startswith(prefix) for prefix in prefixes)
                is_owned_dag = matches_prefix and node_type in {"joint", "transform", "ikHandle"} and rel.endswith(
                    _MODULE_CLEANUP_SUFFIXES)
                is_owned_helper = node_type not in {"joint", "transform",
                                                    "ikHandle"} and node_type in _MODULE_CLEANUP_NODE_TYPES
                if is_owned_dag or is_owned_helper:
                    module_nodes.add(rel)
                    queue.append(resolved)

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

    limb_data = {}
    if len(leg_chain) >= 3:
        limb_data = create_ik_fk_limb(leg_chain, hip_ctrl)

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
        "cleanup_nodes": (limb_data.get("stretch") or {}).get("nodes", []),
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
    def spine_slot_key(slot):
        match = re.fullmatch(r"Spine(\d*)", slot)
        return int(match.group(1) or 0) if match else 9999

    spine_joints = []
    if body_joint_map:
        for key in sorted(body_joint_map.keys(), key=spine_slot_key):
            if key.startswith("Spine") and not key.endswith("Tip"):
                jnt = body_joint_map[key].get("joint")
                if jnt and cmds.objExists(jnt):
                    spine_joints.append(jnt)
    if not spine_joints:
        spine_joints = ["spine1", "spine3", "spine5"]
    spine_joints = [s for s in spine_joints if cmds.objExists(s)]

    pelvis_jnt = body_joint_map.get("Hips", {}).get("joint") if body_joint_map else "pelvis"
    root_p = parent_ctrl or (pelvis_jnt + "_ctrl" if cmds.objExists(pelvis_jnt + "_ctrl") else None)

    stretch_data = {"enabled": False, "nodes": []}
    eligible_for_spline = len(spine_joints) >= 3
    if eligible_for_spline:
        for parent_joint, child_joint in zip(spine_joints[:-1], spine_joints[1:]):
            actual_parent = cmds.listRelatives(child_joint, parent=True, type="joint", fullPath=True) or []
            expected_parent = cmds.ls(parent_joint, long=True) or [parent_joint]
            if not actual_parent or actual_parent[0] != expected_parent[0]:
                eligible_for_spline = False
                break

    pelvis_ctrl = pelvis_jnt + "_ctrl" if pelvis_jnt else ""
    eligible_for_spline = eligible_for_spline and cmds.objExists(pelvis_ctrl)

    if spine_joints and eligible_for_spline:
        spine_tip = spine_joints[-1]
        spine_base = spine_joints[:-1]
        control_data = create_joint_controls(
            spine_base,
            control_shape="sphere",
            root_parent=root_p,
            sub_ctrls=True,
        )
        tip_root = spine_base[-1] + "_ctrl" if spine_base else root_p
        control_data.extend(create_joint_controls(
            [spine_tip],
            control_shape="sphere",
            root_parent=tip_root,
        ))
        stretch_data = setup_spine_segment_stretch(
            spine_joints,
            control_data,
            pelvis_ctrl,
            scale_reference=root_p or pelvis_ctrl,
        )
    elif spine_joints:
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
        "stretch_enabled": bool(stretch_data.get("enabled")),
        "cleanup_nodes": stretch_data.get("nodes", []),
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



# Core functions resolve these later lifecycle helpers at call time.
_core._delete_space_switch_for_ctrl = _delete_space_switch_for_ctrl
_core._safe_delete_nodes = _safe_delete_nodes
_core._short_node_name = _short_node_name
_core.duplicate_static_hierarchy = duplicate_static_hierarchy
_core.load_module_metadata = load_module_metadata
