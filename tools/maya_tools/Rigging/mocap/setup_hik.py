import maya.mel as mel
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math


def get_world_position(obj):
    """
    Gets the world position
    :param obj: name of object
    :return:
    """
    pos = cmds.xform(obj, q=True, ws=True, t=True)
    return om.MVector(pos)


def align_clavicle_Y_by_rotateY(clavicle_joint, sample_range=30.0, step=0.1):
    """
    Rotates Y up until the upper arm and clavicle are as close to the same in Translate Y world position
    :param clavicle_joint: joint name
    :param sample_range: how far of rotation range to test against base pose
    :param step: how small of increments to test
    :return:
    """
    children = cmds.listRelatives(clavicle_joint, type="joint", children=True, fullPath=True)
    if not children:
        print(f"No child joint found for {clavicle_joint}")
        return

    child_joint = children[0]

    orig_rot = cmds.getAttr(clavicle_joint + ".rotate")[0]
    base_x, base_y, base_z = orig_rot

    best_y = base_y
    smallest_diff = float("inf")

    for offset in range(int(-sample_range / step), int(sample_range / step) + 1):
        test_y = base_y + offset * step
        cmds.setAttr(clavicle_joint + ".rotate", base_x, test_y, base_z)

        clav_y = get_world_position(clavicle_joint).y
        child_y = get_world_position(child_joint).y
        diff = abs(clav_y - child_y)

        if diff < smallest_diff:
            smallest_diff = diff
            best_y = test_y

    cmds.setAttr(clavicle_joint + ".rotate", base_x, best_y, base_z)


def aim_joint_x_axis_to_world_x(joint_name):
    """
    Aligns the joint to +X or -X
    :param joint_name: joint to align
    :return:
    """
    dup_joint = cmds.duplicate(joint_name, parentOnly=True, name=joint_name + "_worldAlignTemp")[0]

    cmds.parent(dup_joint, world=True)


    joint_pos = cmds.xform(dup_joint, q=True, ws=True, t=True)
    aim_target = [joint_pos[0] + 1, joint_pos[1], joint_pos[2]]

    aim_loc = cmds.spaceLocator(name="aim_target_loc")[0]
    cmds.xform(aim_loc, ws=True, t=aim_target)

    val = -1
    if "r_" in joint_name:
        val = 1
    aim_constraint = cmds.aimConstraint(
        aim_loc, dup_joint,
        aimVector=[1, 0, 0],
        upVector=[0, 0, val],
        worldUpType="vector", worldUpVector=[0, 1, 0]
    )

    cmds.delete(aim_constraint)
    cmds.delete(aim_loc)

    final_rot = cmds.xform(dup_joint, q=True, ro=True, ws=True)

    parent = cmds.listRelatives(joint_name, parent=True, fullPath=True)
    if parent:
        parent_matrix = om.MMatrix(cmds.xform(parent[0], q=True, m=True, ws=True))
        joint_matrix = om.MMatrix(cmds.xform(dup_joint, q=True, m=True, ws=True))
        local_matrix = joint_matrix * parent_matrix.inverse()
        tm = om.MTransformationMatrix(local_matrix)
        local_rot = tm.rotation(asQuaternion=False)
    else:
        local_rot = om.MEulerRotation(
            math.radians(final_rot[0]),
            math.radians(final_rot[1]),
            math.radians(final_rot[2])
        )

    cmds.setAttr(joint_name + ".rotate",
                 math.degrees(local_rot.x),
                 math.degrees(local_rot.y),
                 math.degrees(local_rot.z))


    cmds.delete(dup_joint)

def t_pose_character(l_upperarm, r_upperarm, l_clav, r_clav, l_elbow, r_elbow, l_hand, r_hand):
    """
    Tposes the arms, currently pointed down X
    :param l_upperarm: actual joint name for slot
    :param r_upperarm: actual joint name for slot
    :param l_clav: actual joint name for slot
    :param r_clav: actual joint name for slot
    :param l_elbow: actual joint name for slot
    :param r_elbow: actual joint name for slot
    :param l_hand: actual joint name for slot
    :param r_hand: actual joint name for slot
    :return:
    """
    align_clavicle_Y_by_rotateY(l_clav)
    align_clavicle_Y_by_rotateY(r_clav)
    aim_joint_x_axis_to_world_x(l_upperarm)
    aim_joint_x_axis_to_world_x(r_upperarm)
    joint_names = {
        "l_elbow": l_elbow,
        "r_elbow": r_elbow,
        "l_hand": l_hand,
        "r_hand": r_hand
    }

    for label, joint in joint_names.items():
        if cmds.objExists(joint):
            for axis in ["X", "Y", "Z"]:
                attr = f"{joint}.rotate{axis}"
                cmds.setAttr(attr, 0)
        else:
            print(f"{label} not found: {joint}")


def setup_hik_character(character_name, joint_map, fbx_export_path, namespace):
    """
    Setup a HIK character definition and export to FBX for MotionBuilder.

    :param character_name: Name of the HIK character to create.
    :param joint_map: Mapping of HIK slots to joint names.
    :param fbx_export_path: Full path to export the FBX file.
    :param namespace: namespace to apply on export
    :return:
    """

    mel.eval("DisableAll")
    for grp_name in ["DNT", "do_not_touch", "rig"]:
        if cmds.objExists(grp_name):
            try:
                cmds.delete(grp_name)
                print(f"[INFO] Deleted group: {grp_name}")
            except Exception as e:
                print(f"[WARNING] Could not delete group '{grp_name}': {e}")
    mel.eval("EnableAll")

    if "LeftArm" in joint_map and "RightArm" in joint_map:
        t_pose_character(joint_map["LeftArm"][0], joint_map["RightArm"][0],
                         joint_map["LeftShoulder"][0], joint_map["RightShoulder"][0],
                         joint_map["LeftForeArm"][0], joint_map["RightForeArm"][0],
                         joint_map["LeftHand"][0], joint_map["RightHand"][0])

    # Step 1: Create HumanIK character
    MAYA_LOCATION = os.environ['MAYA_LOCATION']
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikGlobalUtils.mel"')
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikCharacterControlsUI.mel"')
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikDefinitionOperations.mel"')

    if not cmds.objExists(character_name):
        mel.eval(f'hikCreateCharacter "{character_name}"')
    else:
        if not cmds.control("hikCharacterControls", exists=True):
            mel.eval('HIKCharacterControlsTool;')

        mel.eval('hikUpdateCharacterList();')

    for hik_slot, value in joint_map.items():
        if isinstance(value, dict):
            joint_name, index = value
        else:
            joint_name, index = value

        try:
            mel.eval(f'setCharacterObject "{joint_name}" "{character_name}" "{index}" 0;')

        except Exception as e:
            print(f"Failed to map {hik_slot} -> {value}: {e}")
    mel.eval('hikUpdateDefinitionUI;')
    mel.eval('hikToggleLockDefinition()')

    os.makedirs(os.path.dirname(fbx_export_path), exist_ok=True)
    cmds.select(all=True)

    if not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    excluded = {'persp', 'top', 'front', 'side'}
    all_nodes = cmds.ls(dag=True, type=["transform", "joint"], long=True)
    all_nodes = [n for n in all_nodes if cmds.nodeType(n) != "shape"]
    all_nodes.sort(key=lambda n: len(n.split('|')), reverse=True)
    renamed = {}
    for node in all_nodes:
        short_name = node.split('|')[-1]
        if short_name in excluded:
            continue

        base_name = short_name
        final_name = f"{namespace}:{base_name}"
        try:
            new_name = cmds.rename(node, final_name)
            renamed[new_name] = node
        except Exception as e:
            print(f"[WARNING] Could not rename {node} to {final_name}: {e}")

    mel.eval('FBXResetExport;')
    mel.eval('FBXExportSkeletonDefinitions -v true')
    mel.eval('FBXExportInputConnections -v false')
    mel.eval('FBXExportConstraints -v false')
    mel.eval('FBXExport -f "{}" -s;'.format(fbx_export_path.replace('\\', '/')))
    print(f"[Maya] Character exported to: {fbx_export_path}")


joint_map = {
    "Hips": "root_joint",
    "LeftUpLeg": "l_thigh",
    "LeftLeg": "l_knee",
    "LeftFoot": "l_ankle",
    "RightUpLeg": "r_thigh",
    "RightLeg": "r_knee",
    "RightFoot": "r_ankle",
    "Spine": "spine_01",
    "Spine1": "spine_02",
    "Neck": "neck",
    "Head": "head",
    "LeftArm": "l_upperarm",
    "LeftForeArm": "l_forearm",
    "LeftHand": "l_hand",
    "RightArm": "r_upperarm",
    "RightForeArm": "r_forearm",
    "RightHand": "r_hand"
}

