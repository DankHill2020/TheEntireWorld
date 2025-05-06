import pyfbsdk as fb
from pyfbsdk_additions import *
import os
import sys

_callbacks = {}


def add_file_open_callback(widget):
    def on_scene_change(control, event):
        if hasattr(widget, 'file_opened'):
            widget.file_opened.emit()

    app = fb.FBApplication()
    cb = app.OnFileOpenCompleted.Add(on_scene_change)
    cb_new = app.OnFileNewCompleted.Add(on_scene_change)
    _callbacks['file_open'] = cb
    _callbacks['file_new'] = cb_new


def remove_file_open_callback():
    try:
        app = fb.FBApplication()
        if 'file_open' in _callbacks:
            app.OnFileOpenCompleted.Remove(_callbacks['file_open'])
            app.OnFileNewCompleted.Remove(_callbacks['file_new'])
            _callbacks.clear()
    except Exception as e:
        print("Failed to remove callbacks:", e)


def get_main_window_pointer():
    return fb.FBGetMainWindow()


def get_camera_sequencer_data():
    """
    Retrieves all shots, shot ranges, and corresponding shot cameras from MotionBuilder's CameraSwitcher.
    :return: List of tuples (shot_number, start_frame, end_frame, camera)
    """
    try:
        shot_data = get_story_camera_shots()

        return shot_data

    except Exception as e:
        print(f"Error retrieving camera sequencer data: {e}", file=sys.stderr)
        return []


def get_story_camera_shots():
    """
    Retrieves all clips in the Shot Track (kFBStoryTrackShot), including camera assignments.
    Returns a list of tuples: (clip_name, start_frame, end_frame, camera_name)
    """
    shot_data = []
    story = fb.FBStory()

    def iterate_tracks(folder):
        tracks = list(folder.Tracks)
        for subfolder in folder.Childs:
            tracks.extend(iterate_tracks(subfolder))
        return tracks

    all_tracks = iterate_tracks(story.RootEditFolder)

    for track in all_tracks:

        if track.Type == fb.FBStoryTrackType.kFBStoryTrackShot:
            for clip in track.Clips:

                try:
                    camera = clip.ShotCamera
                    cam_name = camera.Name if camera else "No camera"
                    start = clip.Start.GetFrame()
                    end = clip.Stop.GetFrame()
                    shot_data.append((clip.Name, start, end, cam_name))
                except Exception as e:
                    print(f"Error reading clip '{clip.Name}': {e}", file=sys.stderr)

    return shot_data


def export_node_exists():
    return fb.FBFindModelByLabelName('ExportData')


def get_display_range():
    player = fb.FBPlayerControl()
    return [player.LoopStart.GetFrame(), player.LoopStop.GetFrame()]


def set_display_range(start_frame, end_frame):
    start_time = fb.FBTime()
    start_time.SetFrame(start_frame)

    end_time = fb.FBTime()
    end_time.SetFrame(end_frame)

    player = fb.FBPlayerControl()
    player.LoopStart = start_time
    player.LoopStop = end_time
    player.Goto(start_time)


def display_warning(warning):
    fb.FBMessageBox("Warning", warning, "OK")


def get_cameras_from_selection():
    selected = fb.FBModelList()
    fb.FBGetSelectedModels(selected)
    for model in selected:
        if isinstance(model, fb.FBCamera):
            return model.Name
    return None


def get_scene_path():
    return fb.FBApplication().FBXFileName


def get_components_in_namespace(namespace):
    """
    Returns all components in the scene that belong to the given namespace.
    Namespace format should be: 'MyNamespace::'
    """
    if not namespace.endswith(":"):
        namespace += ":"

    scene = fb.FBSystem().Scene
    components = []

    for comp in scene.Components:
        if namespace in comp.LongName:
            components.append(comp)

    return components


def get_rig_namespaces(selection=True):
    """
    Detects namespaces of selected rigs that contain joints with 'origin' as the top joint.
    :return: Set of valid namespaces
    """
    namespaces = set()

    if selection:
        selected = fb.FBModelList()
        fb.FBGetSelectedModels(selected)
        for obj in selected:
            namespace = obj.LongName.split(":")[0]
            if namespace not in namespaces:
                ns_nodes = get_components_in_namespace(namespace)
                for node in ns_nodes:
                    if isinstance(node, fb.FBModelSkeleton) or isinstance(node, fb.FBModelRoot):
                        top_joint = find_top_joint(node)
                        if top_joint:
                            namespaces.add(namespace)

    else:
        for node in fb.FBSystem().Scene.Components:
            if isinstance(node, fb.FBModelSkeleton) or isinstance(node, fb.FBModelRoot):
                namespace = node.LongName.split(":")[0]
                if namespace not in namespaces:
                    top_joint = find_top_joint(node)
                    if top_joint:
                        namespaces.add(namespace)

    return namespaces


def find_top_joint(model):
    """
    Finds the top joint of the model (simulating the 'origin' joint check).
    :param model: FBModel object to check
    :return: True if it's a top joint, False otherwise
    """
    if isinstance(model, fb.FBModelSkeleton) or isinstance(model, fb.FBModelRoot):
        return model.Parent is None
    return False


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

        blueprint = None

        animation_data = {
            'export_path': export_path,
            'name_space': namespace,
            'skeleton': skeleton,
            'blueprint': blueprint,
            'nodes': nodes,
            'start_frame': start_value,
            'end_frame': end_value,
            'fps': get_motionbuilder_fps()
        }

        if shot_number not in new_dict:
            new_dict[shot_number] = []

        new_dict[shot_number].append(animation_data)

    return new_dict


def get_motionbuilder_fps():
    time_mode_to_fps = {
        fb.FBTimeMode.kFBTimeModeCustom: 30.0,
        fb.FBTimeMode.kFBTimeMode24Frames: 24.0,
        fb.FBTimeMode.kFBTimeMode25Frames: 25.0,
        fb.FBTimeMode.kFBTimeMode30Frames: 30.0,
        fb.FBTimeMode.kFBTimeMode50Frames: 50.0,
        fb.FBTimeMode.kFBTimeMode60Frames: 60.0,
        fb.FBTimeMode.kFBTimeMode100Frames: 100.0,
        fb.FBTimeMode.kFBTimeMode120Frames: 120.0,
    }

    fps_mode = fb.FBPlayerControl().GetTransportFps()

    return time_mode_to_fps.get(fps_mode)


def create_property(model, prop_name, value):
    existing_prop = model.PropertyList.Find(prop_name)
    if existing_prop:
        existing_prop.Data = value
    else:
        prop = model.PropertyCreate(prop_name, fb.FBPropertyType.kFBPT_charptr, "String", False, None, None)
        prop.Data = value


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
    export_node = fb.FBFindModelByLabelName('ExportData')

    if not export_node:
        export_node = fb.FBModelNull('ExportData')
        if export_node not in fb.FBSystem().Scene.Components:
            fb.FBSystem().Scene.Components.append(export_node)
    else:
        if export_node not in fb.FBSystem().Scene.Components:
            fb.FBSystem().Scene.Components.append(export_node)
    create_property(export_node, 'anims', str(anim_dict))
    create_property(export_node, 'skeletons', str(skeletons))
    create_property(export_node, 'uproject', f"{uproject},{log_path},{cmd_path}")
    create_property(export_node, 'export_directory', export_directory)
    create_property(export_node, 'namespace_map', str(namespace_skeleton_map))

    return export_node


def get_export_node_data():
    anim_dict = None
    skeletons = None
    namespace_skeleton_map = None
    uproject = None
    log_path = None
    cmd_path = None
    export_dir = None
    export_node = fb.FBFindModelByLabelName('ExportData')
    if export_node:
        anim_dict = eval(export_node.PropertyList.Find('anims').Data)
        try:
            skeletons = eval(export_node.PropertyList.Find('skeletons').Data)
        except:
            skeletons = None
        namespace_skeleton_map = eval(export_node.PropertyList.Find('namespace_map').Data)
        uproject_log_cmd = export_node.PropertyList.Find('uproject').Data
        uproject, log_path, cmd_path = uproject_log_cmd.split(',', 2)
        export_dir = export_node.PropertyList.Find('export_directory').Data

    return [anim_dict, skeletons, namespace_skeleton_map, uproject, log_path, cmd_path, export_dir]