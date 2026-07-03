import maya.mel as mel
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math

DEFAULT_FACE_JOINT_MAP = {

    # ---------- BROWS (up to 5 per side) ----------
    "LeftBrow": {
        "index": 0,
        "joints": []   # e.g. l_brow1 → l_brow5
    },
    "RightBrow": {
        "index": 1,
        "joints": []   # e.g. r_brow1 → r_brow5
    },

    # ---------- EYELIDS ----------
    "LeftEyelid": {
        "index": 10,
        "outer": {"joint": ""},
        "upper": {"joints": []},
        "inner": {"joint": ""},
        "lower": {"joints": []},
        "joints": []
    },

    "RightEyelid": {
        "index": 20,
        "outer": {"joint": ""},
        "upper": {"joints": []},
        "inner": {"joint": ""},
        "lower": {"joints": []},
        "joints": []
    },

    "LeftEye": {"index": 70, "joint": ""},
    "RightEye": {"index": 71, "joint": ""},

    # ---------- LIPS ----------
    "LipChain": {
        "index": 30,
        "joints": []
    },

    "UpperLipCenter": {"index": 31, "joint": ""},
    "LowerLipCenter": {"index": 32, "joint": ""},
    "LeftLipCorner":  {"index": 33, "joint": ""},
    "RightLipCorner": {"index": 34, "joint": ""},

    # ---------- JAW ----------
    "Jaw": {"index": 40, "joint": ""},

    # ---------- TONGUE ----------
    "TongueChain": {
        "index": 50,
        "joints": []   # tongue1 → tongueN
    },

    # ---------- TEETH ----------
    "UpperTeeth": {"index": 60, "joint": ""},
    "LowerTeeth": {"index": 61, "joint": ""},

    # ---------- NOSE ----------
    "NoseRoot": {"index": 80, "joint": ""},

    # ---------- EVERYTHING ELSE ----------
    "OtherFaceJoints": {
        "index": 100,
        "joints": []
    }
}

DEFAULT_JOINT_MAP = {
    "Reference": {"index": 0, "joint": ""},
    "Hips": {"index": 1, "joint": ""},
    "LeftUpLeg": {"index": 2, "joint": ""},
    "LeftLeg": {"index": 3, "joint": ""},
    "LeftFoot": {"index": 4, "joint": ""},
    "LeftToeBase": {"index": 16, "joint": ""},
    "RightUpLeg": {"index": 5, "joint": ""},
    "RightLeg": {"index": 6, "joint": ""},
    "RightFoot": {"index": 7, "joint": ""},
    "RightToeBase": {"index": 17, "joint": ""},
    "Spine": {"index": 8, "joint": ""},
    "Spine1": {"index": 23, "joint": ""},
    "Spine2": {"index": 24, "joint": ""},
    "Spine3": {"index": 25, "joint": ""},
    "Neck": {"index": 20, "joint": ""},
    "Neck1": {"index": 32, "joint": ""},
    "Head": {"index": 15, "joint": ""},
    "LeftShoulder": {"index": 18, "joint": ""},
    "LeftArm": {"index": 9, "joint": ""},
    "LeftForeArm": {"index": 10, "joint": ""},
    "LeftHand": {"index": 11, "joint": ""},
    "LeftInHandIndex": {"index": 147, "joint": ""},
    "LeftInHandMiddle": {"index": 148, "joint": ""},
    "LeftInHandRing": {"index": 149, "joint": ""},
    "LeftInHandPinky": {"index": 150, "joint": ""},
    "LeftHandThumb1": {"index": 50, "joint": ""},
    "LeftHandIndex1": {"index": 54, "joint": ""},
    "LeftHandMiddle1": {"index": 58, "joint": ""},
    "LeftHandRing1": {"index": 62, "joint": ""},
    "LeftHandPinky1": {"index": 66, "joint": ""},
    "LeftHandThumb2": {"index": 51, "joint": ""},
    "LeftHandIndex2": {"index": 55, "joint": ""},
    "LeftHandMiddle2": {"index": 59, "joint": ""},
    "LeftHandRing2": {"index": 63, "joint": ""},
    "LeftHandPinky2": {"index": 67, "joint": ""},
    "LeftHandThumb3": {"index": 52, "joint": ""},
    "LeftHandIndex3": {"index": 56, "joint": ""},
    "LeftHandMiddle3": {"index": 60, "joint": ""},
    "LeftHandRing3": {"index": 64, "joint": ""},
    "LeftHandPinky3": {"index": 68, "joint": ""},
    "LeftHandThumb4": {"index": 53, "joint": ""},
    "LeftHandIndex4": {"index": 57, "joint": ""},
    "LeftHandMiddle4": {"index": 61, "joint": ""},
    "LeftHandRing4": {"index": 65, "joint": ""},
    "LeftHandPinky4": {"index": 69, "joint": ""},
    "RightShoulder": {"index": 19, "joint": ""},
    "RightArm": {"index": 12, "joint": ""},
    "RightForeArm": {"index": 13, "joint": ""},
    "RightHand": {"index": 14, "joint": ""},
    "RightInHandIndex": {"index": 153, "joint": ""},
    "RightInHandMiddle": {"index": 154, "joint": ""},
    "RightInHandRing": {"index": 155, "joint": ""},
    "RightInHandPinky": {"index": 156, "joint": ""},
    "RightHandThumb1": {"index": 74, "joint": ""},
    "RightHandIndex1": {"index": 78, "joint": ""},
    "RightHandMiddle1": {"index": 82, "joint": ""},
    "RightHandRing1": {"index": 86, "joint": ""},
    "RightHandPinky1": {"index": 90, "joint": ""},
    "RightHandThumb2": {"index": 75, "joint": ""},
    "RightHandIndex2": {"index": 79, "joint": ""},
    "RightHandMiddle2": {"index": 83, "joint": ""},
    "RightHandRing2": {"index": 87, "joint": ""},
    "RightHandPinky2": {"index": 91, "joint": ""},
    "RightHandThumb3": {"index": 76, "joint": ""},
    "RightHandIndex3": {"index": 80, "joint": ""},
    "RightHandMiddle3": {"index": 84, "joint": ""},
    "RightHandRing3": {"index": 88, "joint": ""},
    "RightHandPinky3": {"index": 92, "joint": ""},
    "RightHandThumb4": {"index": 77, "joint": ""},
    "RightHandIndex4": {"index": 81, "joint": ""},
    "RightHandMiddle4": {"index": 85, "joint": ""},
    "RightHandRing4": {"index": 89, "joint": ""},
    "RightHandPinky4": {"index": 93, "joint": ""},

    "LeftArmRoll": {"index": 45, "joint": ""},
    "LeafLeftArmRoll1": {"index": 176, "joint": ""},
    "LeafLeftArmRoll2": {"index": 184, "joint": ""},
    "LeafLeftArmRoll3": {"index": 192, "joint": ""},

    "RightArmRoll": {"index": 47, "joint": ""},
    "LeafRightArmRoll1": {"index": 178, "joint": ""},
    "LeafRightArmRoll2": {"index": 186, "joint": ""},
    "LeafRightArmRoll3": {"index": 194, "joint": ""},

    "LeftForeArmRoll": {"index": 46, "joint": ""},
    "LeafLeftForearmRoll1": {"index": 177, "joint": ""},
    "LeafLeftForearmRoll2": {"index": 185, "joint": ""},
    "LeafLeftForearmRoll3": {"index": 193, "joint": ""},

    "RightForeArmRoll": {"index": 48, "joint": ""},
    "LeafRightForearmRoll1": {"index": 179, "joint": ""},
    "LeafRightForearmRoll2": {"index": 187, "joint": ""},
    "LeafRightForearmRoll3": {"index": 195, "joint": ""},

    "LeftUpLegRoll": {"index": 41, "joint": ""},
    "LeafLeftUpLegRoll1": {"index": 172, "joint": ""},
    "LeafLeftUpLegRoll2": {"index": 180, "joint": ""},
    "LeafLeftUpLegRoll3": {"index": 188, "joint": ""},

    "RightUpLegRoll": {"index": 43, "joint": ""},
    "LeafRightUpLegRoll1": {"index": 174, "joint": ""},
    "LeafRightUpLegRoll2": {"index": 182, "joint": ""},
    "LeafRightUpLegRoll3": {"index": 190, "joint": ""},

    "LeftLegRoll": {"index": 42, "joint": ""},
    "LeafLeftLegRoll1": {"index": 173, "joint": ""},
    "LeafLeftLegRoll2": {"index": 181, "joint": ""},

    "RightLegRoll": {"index": 44, "joint": ""},
    "LeafRightLegRoll1": {"index": 175, "joint": ""},
    "LeafRightLegRoll2": {"index": 183, "joint": ""}

}


def get_descendant_joints(root_joint):
    """Returns all descendant joints of root_joint (including root)."""
    if not root_joint or not cmds.objExists(root_joint):
        return []
    return [root_joint] + cmds.listRelatives(root_joint, allDescendents=True, type="joint") or []


def find_face_joints(pattern, face_joints):
    """Return joints in the scene matching the pattern that are descendants of the face root."""
    all_matches = cmds.ls(pattern, type="joint") or []
    return [j for j in all_matches if j in face_joints]


def _exists(j):
    return j if j and cmds.objExists(j) else None


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
    return joint_map


joint_map = {
    "Hips": "root_joint",
    "LeftUpLeg": "l_thigh",
    "LeftLeg": "l_knee",
    "LeftFoot": "l_ankle",
    "RightUpLeg": "r_thigh",
    "RightLeg": "r_knee",
    "RightFoot": "r_ankle",
    "Spine": "spine_1",
    "Spine1": "spine3",
    "Neck": "neck",
    "Head": "head",
    "LeftArm": "l_upperarm",
    "LeftForeArm": "l_lowerarm",
    "LeftHand": "l_hand",
    "RightArm": "r_upperarm",
    "RightForeArm": "r_lowerarm",
    "RightHand": "r_hand"
}

