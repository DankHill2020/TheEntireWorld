import maya.mel as mel
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math
import re
import copy
from maya_tools.Utilities import joints as joints_util

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
    if not clavicle_joint or not cmds.objExists(clavicle_joint):
        return

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
    Aligns the joint X-axis pointing towards the world X direction (+X for left side, -X for right side).
    """
    if not joint_name or not cmds.objExists(joint_name):
        return

    name_lower = joint_name.lower().split("|")[-1].split(":")[-1]
    is_right = any(tok in name_lower for tok in ["r_", "_r", "right"]) or name_lower.startswith("r")

    dup_joint = cmds.duplicate(joint_name, parentOnly=True, name=joint_name + "_worldAlignTemp")[0]
    cmds.parent(dup_joint, world=True)

    joint_pos = cmds.xform(dup_joint, q=True, ws=True, t=True)

    # Left arm points to +X, Right arm points to -X
    x_offset = -10.0 if is_right else 10.0
    aim_target = [joint_pos[0] + x_offset, joint_pos[1], joint_pos[2]]

    aim_loc = cmds.spaceLocator(name="aim_target_loc")[0]
    cmds.xform(aim_loc, ws=True, t=aim_target)

    up_val = 1 if is_right else -1
    aim_vec = [-1, 0, 0] if is_right else [1, 0, 0]

    aim_constraint = cmds.aimConstraint(
        aim_loc, dup_joint,
        aimVector=aim_vec,
        upVector=[0, 0, up_val],
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


def set_t_pose(l_upperarm=None, r_upperarm=None, l_clav=None, r_clav=None, l_elbow=None, r_elbow=None, l_hand=None, r_hand=None, joint_map=None):
    """
    T-poses character arms (aligned to X axis). Accepts individual joint names,
    a list of joint names, or a joint_map dictionary. Auto-detects from scene if unmapped.
    """
    if not joint_map and not (l_upperarm or r_upperarm):
        try:
            top_joints = joints_util.find_skinned_or_top_joints(namespace='')
            if top_joints:
                joint_map = guess_joint_map_from_root(top_joints[0])
        except Exception:
            pass

    if joint_map and isinstance(joint_map, dict):
        def _extract(*slots):
            for slot in slots:
                val = joint_map.get(slot)
                if val:
                    if isinstance(val, (list, tuple)) and val:
                        return val[0]
                    elif isinstance(val, dict):
                        j = val.get("joint")
                        if j:
                            return j
                    elif isinstance(val, str):
                        return val
            return None

        l_upperarm = l_upperarm or _extract("LeftArm", "LeftArmJoint", "l_upperarm", "arm_l")
        r_upperarm = r_upperarm or _extract("RightArm", "RightArmJoint", "r_upperarm", "arm_r")
        l_clav = l_clav or _extract("LeftShoulder", "LeftClavicle", "l_clavicle", "clavicle_l")
        r_clav = r_clav or _extract("RightShoulder", "RightClavicle", "r_clavicle", "clavicle_r")
        l_elbow = l_elbow or _extract("LeftForeArm", "LeftElbow", "l_lowerarm", "forearm_l")
        r_elbow = r_elbow or _extract("RightForeArm", "RightElbow", "r_lowerarm", "forearm_r")
        l_hand = l_hand or _extract("LeftHand", "LeftWrist", "l_hand", "hand_l")
        r_hand = r_hand or _extract("RightHand", "RightWrist", "r_hand", "hand_r")

    print("[setup_hik.set_t_pose] Executing T-pose alignment:")
    print(f"  Left Arm: clav={l_clav}, upperarm={l_upperarm}, elbow={l_elbow}, hand={l_hand}")
    print(f"  Right Arm: clav={r_clav}, upperarm={r_upperarm}, elbow={r_elbow}, hand={r_hand}")

    if l_clav and cmds.objExists(l_clav):
        align_clavicle_Y_by_rotateY(l_clav)
    if r_clav and cmds.objExists(r_clav):
        align_clavicle_Y_by_rotateY(r_clav)

    if l_upperarm and cmds.objExists(l_upperarm):
        aim_joint_x_axis_to_world_x(l_upperarm)
    if r_upperarm and cmds.objExists(r_upperarm):
        aim_joint_x_axis_to_world_x(r_upperarm)

    joint_names = {
        "l_elbow": l_elbow,
        "r_elbow": r_elbow,
        "l_hand": l_hand,
        "r_hand": r_hand
    }

    for label, joint in joint_names.items():
        if joint and cmds.objExists(joint):
            for axis in ["X", "Y", "Z"]:
                attr = f"{joint}.rotate{axis}"
                try:
                    cmds.setAttr(attr, 0)
                except Exception as exc:
                    print(f"Could not zero rotation for {attr}: {exc}")
        else:
            if joint:
                print(f"{label} not found: {joint}")


t_pose_character = set_t_pose


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


def populate_default_face_map_from_scene(base_face_map=None):
    """Fill face map with default scene joints under HIK head reference."""
    if base_face_map is None:
        dm = copy.deepcopy(DEFAULT_FACE_JOINT_MAP)
    else:
        dm = base_face_map

    side = "l"
    dm["LeftBrow"]["joints"] = [f"{side}_brow{i}" for i in range(1, 6)]
    dm["LeftEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
    dm["LeftEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
    dm["LeftEyelid"]["joints"] = [
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
    
    side = "r"
    dm["RightBrow"]["joints"] = [f"{side}_brow{i}" for i in range(1, 6)]
    dm["RightEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
    dm["RightEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
    dm["RightEyelid"]["joints"] = [
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

    # ---------- Lips ----------
    dm["LipChain"]["joints"] = [
        'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
        'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
        'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
        'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
    ]
    dm["UpperLipCenter"]["joint"] = "c_upper_lip"
    dm["LowerLipCenter"]["joint"] = "c_lower_lip"
    dm["LeftLipCorner"]["joint"] = "l_lip_corner1"
    dm["RightLipCorner"]["joint"] = "r_lip_corner1"

    # ---------- Jaw ----------
    dm["Jaw"]["joint"] = "jaw"

    # ---------- Tongue ----------
    dm["TongueChain"]["joints"] = ["tongue1", "tongue2", "tongue3", "tongue4"]

    # ---------- Teeth ----------
    dm["UpperTeeth"]["joint"] = "upper_teeth"
    dm["LowerTeeth"]["joint"] = "lower_teeth"

    # ---------- Eyes ----------
    dm["LeftEye"]["joint"] = "l_eye"
    dm["RightEye"]["joint"] = "r_eye"

    # ---------- Nose ----------
    dm["NoseRoot"]["joint"] = "nose_root"

    # ---------- Other Face Joints ----------
    dm["OtherFaceJoints"]["joints"] = [
        'r_undereye_3', 'r_undereye_4', 'r_undereye_5', 'r_undereye_1',
        'r_ear_base1', 'r_ear_base', 'l_upper_cheek', 'r_undereye_2',
        'l_lower_cheek', 'l_inner_cheek', 'r_upper_nose',
        'l_inner_cheek_smile', 'r_inner_cheek_smile', 'r_inner_cheek',
        'r_upper_cheek', 'r_lower_cheek',
        'r_undereye_8', 'r_undereye_7', 'r_undereye_6',
        'l_undereye_8', 'l_undereye_7', 'l_undereye_6',
        'l_undereye_5', 'l_undereye_4', 'l_undereye_3',
        'l_undereye_2', 'l_undereye_1',
        'l_ear_base1', 'l_upper_nose', 'l_ear_base'
    ]
    return dm


def guess_joint_map_from_root(root_joint, base_joint_map=None):
    """
    Guesses HIK joint slots from a root joint based on name matching.
    
    :param root_joint: The root joint of the skeleton.
    :param base_joint_map: Optional dict to write results into (e.g. self.default_map).
                           If None, a deep copy of setup_hik.DEFAULT_JOINT_MAP is used.
    :return: A dict with HIK slots and their mapped joint names.
    """
    if not cmds.objExists(root_joint):
        return {}

    if base_joint_map is None:
        joint_map = copy.deepcopy(DEFAULT_JOINT_MAP)
    else:
        joint_map = base_joint_map

    # Reset any existing joint mappings to avoid stale cache from previous runs
    for key in joint_map:
        joint_map[key]["joint"] = ""

    def is_twist_bone(name):
        return "twist" in name or "roll" in name

    all_joints = cmds.listRelatives(root_joint, ad=True, type="joint") or []
    all_joints = list(reversed(all_joints))
    all_joints.insert(0, root_joint)

    spines = []
    necks = []

    fingers = {
        "Left": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []},
        "Right": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []}
    }

    # Check if upperarm joint exists to distinguish shoulder vs upperarm
    has_l_upperarm = any("l_upper" in j.lower() or "upper_l" in j.lower() or "l_arm" in j.lower() or "arm_l" in j.lower() or "l_upperarm" in j.lower() or "upperarm_l" in j.lower() for j in all_joints)
    has_r_upperarm = any("r_upper" in j.lower() or "upper_r" in j.lower() or "r_arm" in j.lower() or "arm_r" in j.lower() or "r_upperarm" in j.lower() or "upperarm_r" in j.lower() for j in all_joints)

    twist_map = {
        # arms
        "upperarm": ("ArmRoll", 3),
        "lowerarm": ("ForeArmRoll", 3),
        # legs
        "thigh": ("UpLegRoll", 3),
        "knee": ("LegRoll", 2),
    }
    side_prefix = {"l": "Left", "r": "Right"}

    for jnt in all_joints:
        name = jnt.lower()

        def set_slot(slot):
            if slot in joint_map and not joint_map[slot].get("joint"):
                joint_map[slot]["joint"] = jnt

        # 1. Twist joints mapping
        is_twist = is_twist_bone(name)
        if is_twist:
            for side in ("l", "r"):
                for limb, (slot_base, count) in twist_map.items():
                    if limb in name:
                        # Match side prefix or suffix
                        is_side = False
                        if side == "l":
                            is_side = name.startswith("l_") or "l_upper" in name or "l_lower" in name or name.endswith("_l") or "_l_" in name or "left" in name
                        else:
                            is_side = name.startswith("r_") or "r_upper" in name or "r_lower" in name or name.endswith("_r") or "_r_" in name or "right" in name
                        
                        if is_side:
                            match = re.search(r'(\d+)', name)
                            num = int(match.group(1)) if match else 1
                            
                            slot_base_fixed = slot_base.replace('ForeArm', "Forearm")
                            if num == 1:
                                joint_map_key = f"{side_prefix[side]}{slot_base}"
                                if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                    joint_map[joint_map_key]["joint"] = jnt
                            else:
                                leaf_idx = num - 1
                                joint_map_key = f"Leaf{side_prefix[side]}{slot_base_fixed}{leaf_idx}"
                                if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                    joint_map[joint_map_key]["joint"] = jnt
            continue

        # 2. Main skeleton joints mapping
        if "spine" in name or "spn" in name:
            spines.append(jnt)

        elif "origin" in name or "root" in name:
            set_slot("Reference")

        elif "pelvis" in name:
            set_slot("Hips")

        elif "hipswing" in name or "hip_swing" in name:
            set_slot("HipSwing")

        elif "l_clavicle" in name or "clavicle_l" in name or ("l_shoulder" in name and has_l_upperarm):
            set_slot("LeftShoulder")
        elif ("l_upper" in name or "upper_l" in name or "l_upperarm" in name or "upperarm_l" in name or "l_upper_arm" in name or "upper_arm_l" in name or ("l_shoulder" in name and not has_l_upperarm) or "l_arm" in name or "arm_l" in name):
            set_slot("LeftArm")
        elif ("l_lower" in name or "lower_l" in name or "l_lowerarm" in name or "lowerarm_l" in name or "l_lower_arm" in name or "lower_arm_l" in name or "l_forearm" in name or "forearm_l" in name or "l_elbow" in name):
            set_slot("LeftForeArm")

        elif "l_hand" in name or "hand_l" in name and "ik" not in name:
            set_slot("LeftHand")

        elif "r_clavicle" in name or "clavicle_r" in name or ("r_shoulder" in name and has_r_upperarm):
            set_slot("RightShoulder")
        elif ("r_upper" in name or "upper_r" in name or "r_upperarm" in name or "upperarm_r" in name or "r_upper_arm" in name or "upper_arm_r" in name or ("r_shoulder" in name and not has_r_upperarm) or "r_arm" in name or "arm_r" in name):
            set_slot("RightArm")
        elif ("r_lower" in name or "lower_r" in name or "r_lowerarm" in name or "lowerarm_r" in name or "r_lower_arm" in name or "lower_arm_r" in name or "r_forearm" in name or "forearm_r" in name or "r_elbow" in name):
            set_slot("RightForeArm")

        elif "r_hand" in name or "hand_r" in name and "ik" not in name:
            set_slot("RightHand")

        elif ("l_thigh" in name or "thigh_l" in name or "l_upperleg" in name):
            set_slot("LeftUpLeg")

        elif ("l_knee" in name or "knee_l" in name or "calf_l" in name or "l_lowerleg" in name):
            set_slot("LeftLeg")

        elif "l_ankle" in name or "ankle_l" in name or "foot_l" in name and "ik" not in name:
            set_slot("LeftFoot")

        elif "l_toe" in name and "tip" not in name or "ball_l" in name:
            set_slot("LeftToeBase")

        elif ("r_thigh" in name or "thigh_r" in name or "r_upperleg" in name):
            set_slot("RightUpLeg")

        elif ("r_knee" in name or "knee_r" in name or "calf_r" in name or "r_lowerleg" in name):
            set_slot("RightLeg")

        elif "r_ankle" in name or "ankle_r" in name or "foot_r" in name and "ik" not in name:
            set_slot("RightFoot")
        elif "r_toe" in name and "tip" not in name or "ball_r" in name:
            set_slot("RightToeBase")

        if "neck" in name:
            necks.append(jnt)
        elif "head" in name:
            set_slot("Head")

        for side_prefix_str, side in [("l_", "Left"), ("r_", "Right")]:
            if name.startswith(side_prefix_str):
                for finger in fingers[side].keys():
                    if finger.lower() in name:
                        fingers[side][finger].append(jnt)
            elif name.endswith("_" + side[0].lower()):
                for finger in fingers[side].keys():
                    if not len(fingers[side][finger]):
                        if cmds.objExists(f"{finger.lower()}_metacarpal_{side[0].lower()}"):
                            fingers[side][finger].append(f"{finger.lower()}_metacarpal_{side[0].lower()}")
                        if cmds.objExists(f"{finger.lower()}_01_{side[0].lower()}"):
                            fingers[side][finger].append(f"{finger.lower()}_01_{side[0].lower()}")
                            fingers[side][finger].append(f"{finger.lower()}_02_{side[0].lower()}")
                            fingers[side][finger].append(f"{finger.lower()}_03_{side[0].lower()}")

    for i, spine in enumerate(spines):
        key = "Spine" if i == 0 else f"Spine{i}"
        if key in joint_map and not joint_map[key].get("joint"):
            joint_map[key]["joint"] = spine

    for i, neck in enumerate(necks):
        key = "Neck" if i == 0 else f"Neck{i}"
        if key in joint_map and not joint_map[key].get("joint"):
            joint_map[key]["joint"] = neck

    for side in ["Left", "Right"]:
        for finger in ["Thumb", "Index", "Middle", "Ring", "Pinky"]:
            joints_list = fingers[side][finger]
            if not joints_list:
                continue
            if "_metacarpal_" not in joints_list[0]:
                joints_sorted = sorted(joints_list, key=lambda x: x.lower())
            else:
                joints_sorted = joints_list
            if "Thumb" not in finger:
                in_hand_key = f"{side}InHand{finger}"
                if in_hand_key in joint_map and not joint_map[in_hand_key].get("joint"):
                    joint_map[in_hand_key]["joint"] = joints_sorted[0]
            else:
                if len(joints_list) > 4:
                    thumb4_key = f"{side}Hand{finger}4"
                else:
                    thumb4_key = f"{side}Hand{finger}3"
                joint_map[thumb4_key]["joint"] = joints_sorted[-1]
            for i in range(1, min(5, len(joints_sorted))):
                num = i
                if "Thumb" in finger:
                    num = i - 1
                key = f"{side}Hand{finger}{i}"
                if key in joint_map and not joint_map[key].get("joint"):
                    joint_map[key]["joint"] = joints_sorted[num]
                    
    return joint_map


def create_rig_mapping(root_joint=None):
    """
    Standalone HIK mapping function. Auto-detects the skeleton root if none is provided,
    then runs guess_joint_map_from_root and populate_default_face_map_from_scene.
    Returns a tuple of (body_joint_map, face_joint_map) suitable for passing to
    create_rig.hik_map_to_rig_args.

    :param root_joint: Optional root joint name. If None, auto-detected from scene.
    :return: (body_joint_map dict, face_joint_map dict)
    """
    if root_joint is None:
        top_joints = joints_util.find_skinned_or_top_joints(namespace='')
        if not top_joints:
            print("[create_rig_mapping] No root joint found in scene.")
            return None, None
        root_joint = top_joints[0]

    body_joint_map = guess_joint_map_from_root(root_joint)
    face_joint_map = populate_default_face_map_from_scene()
    return body_joint_map, face_joint_map
