import maya.cmds as cmds
import maya.OpenMayaUI as omui
import maya.api.OpenMaya as om
from maya_tools.Utilities import joints
import os

_callbacks = {}


def add_file_open_callback(widget):
    def _on_file_open_completed(*args):
        if hasattr(widget, 'file_opened'):
            widget.file_opened.emit()

    _callbacks['file_open'] = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterOpen, _on_file_open_completed)
    _callbacks['file_new'] = om.MSceneMessage.addCallback(
        om.MSceneMessage.kAfterNew, _on_file_open_completed)


def remove_file_open_callback():
    """
    Removes all previously registered Maya scene callbacks.
    """
    try:
        for key, cb_id in _callbacks.items():
            om.MMessage.removeCallback(cb_id)
        _callbacks.clear()
    except Exception as e:
        print("Failed to remove callbacks:", e)


def get_main_window_pointer():
    """
    Get the Maya main window pointer
    :return:
    """
    main_window_ptr = omui.MQtUtil.mainWindow()
    return int(main_window_ptr)


def get_camera_sequencer_data():
    """
    Retrieves all shots, shot ranges, and corresponding shot cameras from Maya's Camera Sequencer.
    :return: List of tuples (shot_number, start_frame, end_frame, camera)
    """
    shots = cmds.ls(type='shot')
    shot_data = []
    for shot in shots:
        shot_number = cmds.getAttr(f"{shot}.shotName")
        start_frame = cmds.getAttr(f"{shot}.startFrame")
        end_frame = cmds.getAttr(f"{shot}.endFrame")
        camera = cmds.listConnections(f"{shot}.currentCamera", source=True, destination=False)
        if camera:
            shot_data.append((shot_number, start_frame, end_frame, camera[0]))
    return shot_data


def export_node_exists():
    return cmds.objExists('ExportData')


def get_display_range():
    """

    :return: start and end frames of the time slider
    """
    start_frame = cmds.playbackOptions(q=True, min=True)
    end_frame = cmds.playbackOptions(q=True, max=True)
    return [start_frame, end_frame]


def set_display_range(start_frame, end_frame):
    """

    :param start_frame:
    :param end_frame:
    :return:
    """
    cmds.playbackOptions(min=start_frame, max=end_frame)
    cmds.currentTime(start_frame)
    cmds.inViewMessage(amg=f"<hl>Scene Range Set:</hl> {start_frame} - {end_frame}", pos="topCenter", fade=True)


def display_warning(warning):
    """

    :param warning: Warning to display
    :return:
    """
    cmds.warning(warning)


def get_cameras_from_selection():
    sel = cmds.ls(sl=True)
    camera = None
    for each in sel:
        shapes = cmds.listRelatives(each, s=1)
        if shapes:
            for shape in shapes:
                if cmds.objectType(shape) == 'camera':
                    return each
    return camera


def get_scene_path():
    maya_file_path = cmds.file(sceneName=True, q=True)

    return maya_file_path


def get_rig_namespaces(selection = True):
    """
    Detects namespaces of selected rigs that contain joints with 'origin' as the top joint.
    :return: Set of valid namespaces
    """
    namespaces = set()
    if selection:
        selected = cmds.ls(selection=True)
        for obj in selected:
            if ":" in obj:
                namespace = obj.split(":")[0]
                if namespace not in namespaces:
                    top_joint = joints.find_skinned_or_top_joints(namespace)
                    if top_joint:
                        namespaces.add(namespace)
    else:
        assembly_nodes = cmds.ls(assemblies=True)
        for node in assembly_nodes:
            namespace = node.split(":")[0]
            if namespace not in namespaces:
                if cmds.objectType(node) == "joint":
                    namespaces.add(namespace)
                else:
                    top_joint = joints.find_skinned_or_top_joints(namespace)
                    if top_joint:
                        namespaces.add(namespace)



    return namespaces


def get_shot_name_from_path(export_path):
    """
    Extracts the shot name from the export path.

    If the 'shot' part does not contain digits, appends the next part.

    :param export_path: The export path (e.g., '/Game/Cinematics/Shot_Animation_01.fbx').
    :return: The shot name (e.g., 'Shot_Animation' or 'Shot_01').
    """
    parts = os.path.basename(export_path).split('_')
    for i, part in enumerate(parts):
        if 'shot' in part.lower():
            if any(char.isdigit() for char in part):
                return part
            elif any(char.isdigit() for char in parts[i+1]):
                return f"{part}_{parts[i + 1]}"
            else:
                return part

    return 'Unknown_Shot'


def generate_sequence_dict_from_anim_dict(anim_dict):
    """
    Generates a new dictionary with shot_number as the key, and a list of animations as the value.
    Each animation has export path, skeleton, blueprint (default to None), nodes, start frame, and end frame.
    :param anim_dict: The original animation dictionary, where the key is the export path and the value contains
                       start frame, end frame, namespace, skeleton, color, and nodes.
    :return: new dictionary with shot_number as keys.
    """
    new_dict = {}

    for export_path, data in anim_dict.items():
        shot_number = get_shot_name_from_path(export_path)

        start_value, end_value, namespace, skeleton, color, nodes = data

        # Blueprint is optional, so default to None if not provided unless we later decide to store it
        blueprint = None

        animation_data = {
            'export_path': export_path,
            'name_space': namespace,
            'skeleton': skeleton,
            'blueprint': blueprint,
            'nodes': nodes,
            'start_frame': start_value,
            'end_frame': end_value,
            'fps': get_maya_fps()
        }

        if shot_number not in new_dict:
            new_dict[shot_number] = []

        new_dict[shot_number].append(animation_data)

    return new_dict


def get_maya_fps():
    time_unit = cmds.currentUnit(query=True, time=True)
    time_map = {
        'game': 15,
        'film': 24,
        'pal': 25,
        'ntsc': 30,
        'show': 48,
        'palf': 50,
        'ntscf': 60,
        '2fps': 2,
        '3fps': 3,
        '4fps': 4,
        '5fps': 5,
        '6fps': 6,
        '8fps': 8,
        '10fps': 10,
        '12fps': 12,
        '16fps': 16,
        '20fps': 20,
        '40fps': 40,
        '75fps': 75,
        '80fps': 80,
        '100fps': 100,
        '120fps': 120,
        '125fps': 125,
        '150fps': 150,
        '200fps': 200,
        '240fps': 240,
        '250fps': 250,
        '300fps': 300,
        '375fps': 375,
        '400fps': 400,
        '500fps': 500,
        '600fps': 600
    }
    return time_map.get(time_unit, 24)


def create_and_populate_export_node(anim_dict, skeletons, uproject, log_path, cmd_path, export_directory, namespace_skeleton_map):
    """
    Data is passed from the UI, likely wont need to call from Maya directly (just separating out cmds calls into this file)
    :param anim_dict:
    :param skeletons:
    :param uproject:
    :param log_path:
    :param cmd_path:
    :param export_directory:
    :param namespace_skeleton_map:
    :return:
    """
    if not cmds.objExists('ExportData'):
        export_node = cmds.createNode("transform", name='ExportData')
        cmds.addAttr('ExportData', longName='anims', dataType="string")
        cmds.addAttr('ExportData', longName='skeletons', dataType="string")
        cmds.addAttr('ExportData', longName='uproject', dataType="string")
        cmds.addAttr('ExportData', longName='export_directory', dataType="string")
        cmds.addAttr('ExportData', longName='namespace_map', dataType="string")

    cmds.setAttr('ExportData.anims', anim_dict, type="string")
    cmds.setAttr('ExportData.skeletons', skeletons, type="string")
    cmds.setAttr('ExportData.uproject', [uproject, log_path, cmd_path], type="string")
    cmds.setAttr('ExportData.export_directory', export_directory, type="string")
    cmds.setAttr('ExportData.namespace_map', namespace_skeleton_map, type="string")


def get_export_node_data():
    anim_dict = None
    skeletons = None
    namespace_skeleton_map = None
    uproject = None
    log_path = None
    cmd_path = None
    export_dir = None
    if cmds.objExists('ExportData'):
        anim_dict = eval(cmds.getAttr('ExportData.anims'))

        skeletons = eval(cmds.getAttr('ExportData.skeletons'))
        namespace_skeleton_map = eval(cmds.getAttr('ExportData.namespace_map'))
        uproject, log_path, cmd_path = eval(cmds.getAttr('ExportData.uproject'))
        export_dir = cmds.getAttr('ExportData.export_directory')
    return [anim_dict, skeletons, namespace_skeleton_map, uproject, log_path, cmd_path, export_dir]