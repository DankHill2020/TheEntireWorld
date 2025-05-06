import pyfbsdk as fb
import os
import sys
import logging
tools_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(tools_dir)


def export_animation(motionbuilder_file, export_path, namespace, start_frame, end_frame, nodes=None):
    """
    Opens MotionBuilder scene and exports animation to FBX.
    :param motionbuilder_file: (str): Path to the Maya scene file (if you need it).
    :param export_path: (str): Path where the FBX should be saved.
    :param namespace: (str): Namespace of the skeleton.
    :param start_frame: (int): Start frame of the animation.
    :param end_frame: (int): End frame of the animation.
    :param nodes: (list, optional): Specific nodes to export instead.
    :return:
    """

    try:
        app = fb.FBApplication()
        current_scene = app.FBXFileName
        if current_scene != motionbuilder_file:
            app.FileOpen(motionbuilder_file)

        full_ns = namespace + ':'
        roots = find_skinned_or_top_joints(full_ns)

        root = None
        root_joint = None
        if roots:
            root = roots[0]
            root_joint = root.split(":")[-1]

        if not nodes:
            if roots and len(roots) > 1:
                children = fb.FBModelList()
                root_model = fb.FBFindModelByName(root)
                if root_model:
                    nodes = root_model
                    children = root_model.GetChildren(children)
                    nodes = nodes + children

        if root_joint and fb.FBFindModelByLabelName(root_joint):
            root_model = fb.FBFindModelByLabelName(root_joint)
            children = root_model.Children
            select_models(children)
        else:
            if not nodes:
                nodes = list_joints_by_namespace(namespace)
            else:
                nodes = [fb.FBFindModelByLabelName(node) for node in nodes]
            select_models(nodes)

        plot_selected_models(nodes, start_frame, end_frame)

        # Prepare for FBX export
        export_dir = os.path.dirname(export_path)
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
        current_take = fb.FBSystem().CurrentTake
        save_options = fb.FBFbxOptions(False)
        save_options.FileFormatAndVersion = fb.FBFileFormatAndVersion.kFBFBX2018
        save_options.SetAll(fb.FBElementAction.kFBElementActionDiscard, False)
        save_options.EmbedMedia = False
        save_options.Bones = fb.FBElementAction.kFBElementActionSave
        save_options.BonesAnimation = True
        save_options.SaveCharacter = True
        save_options.SaveCharacterExtention = True
        save_options.Models = fb.FBElementAction.kFBElementActionSave
        save_options.ModelsAnimation = True
        save_options.TransportSettings = True
        save_options.Cameras = fb.FBElementAction.kFBElementActionSave
        save_options.CamerasAnimation = True
        save_options.SaveSelectedModelsOnly = True
        save_options.UseASCIIFormat = False
        for index in range(save_options.GetTakeCount()):
            if save_options.GetTakeName(index) == current_take.Name:
                save_options.SetTakeSelect(index, True)
            else:
                save_options.SetTakeSelect(index, False)
        fb.FBApplication().FileSave(export_path, save_options)

    except Exception as e:
        logging.error(f"Export failed: {e}", exc_info=True)
    return export_path


def list_joints_by_namespace(namespace):
    """
    Finds all joints in a namespace
    :param namespace: namespace to find joints for
    :return:
    """
    return [
        model for model in fb.FBSystem().Scene.Components
        if model.ClassName() == "FBModelSkeleton" and f"{namespace}:" in model.LongName
    ]


def get_all_descendants(model):
    """
    Gets all children of a selected model
    :param model: Model to search for children under
    :return:
    """
    all_models = []
    for child in model.Children:
        all_models.append(child)
        all_models.extend(get_all_descendants(child))
    return all_models


def find_top_joint(model):
    """
    Finds the top joint of the model (simulating the 'origin' joint check).
    :param model: FBModel object to check
    :return: True if it's a top joint, False otherwise
    """
    if isinstance(model, fb.FBModelSkeleton):
        return model.Parent is None

    return False


def find_skinned_or_top_joints(namespace):
    """
    Detects the top-level joint in a given namespace. It looks for the joint with no parent,
    or the joint closest to the top in the hierarchy.
    :param namespace: (str): The namespace to search for joints.
    :return: (list): List of top-level joints in the namespace.
    """
    top_joints = []
    candidate_joints = []

    scene_root = fb.FBSystem().Scene.RootModel
    all_nodes = get_all_descendants(scene_root)
    for node in all_nodes:
        if isinstance(node, fb.FBModelSkeleton):
            if namespace in node.Name:
                candidate_joints.append(node)
    for node in candidate_joints:
        if node.Parent is None:
            top_joints.append(node.Name)
    if not top_joints:
        closest_to_root = None
        min_parents = float('inf')

        for node in candidate_joints:
            parent = node.Parent
            parent_count = 0
            while parent is not None:
                parent_count += 1
                parent = parent.Parent

            if parent_count < min_parents:
                min_parents = parent_count
                closest_to_root = node.Name

        if closest_to_root:
            top_joints.append(closest_to_root)

    return top_joints


def get_selected_models():
    """
    Get selected models
    :return FBModelList: list of selected models
    """
    selected = fb.FBModelList()
    fb.FBGetSelectedModels(selected)
    return selected


def deselect_all_models():
    """
    Deselect all models
    :return:
    """
    selected = get_selected_models()
    for sel in selected:
        sel.Selected = False


def select_models(models):
    """
    :param models: List of models
    :return:
    """
    deselect_all_models()

    for model in models:
        model.Selected = True


def plot_selected_models(models, start_frame, end_frame):
    """
    :param models: models to plot
    :param start_frame: start frame to plot
    :param end_frame: end frame to plot
    :return:
    """
    selected = get_selected_models()
    deselect_all_models()
    for model in models:
        model.Selected = True

    start_time = fb.FBTime(0, 0, 0, start_frame)
    end_time = fb.FBTime(0, 0, 0, end_frame)
    time_span = fb.FBTimeSpan(start_time, end_time)

    plot_options = fb.FBPlotOptions()
    plot_options.ConstantKeyReducerKeepOneKey = False
    plot_options.PlotAllTakes = False
    plot_options.PlotOnFrame = True
    plot_options.PlotPeriod = fb.FBTime(0, 0, 0, 1)
    plot_options.PlotTranslationOnRootOnly = False
    plot_options.PreciseTimeDiscontinuities = False
    plot_options.RotationFilterToApply = fb.FBRotationFilter.kFBRotationFilterUnroll
    plot_options.UseConstantKeyReducer = False
    plot_options.TimeSpan = time_span

    fb.FBSystem().CurrentTake.PlotTakeOnSelected(plot_options)

    deselect_all_models()
    for sel in selected:
        sel.Selected = True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export animation to FBX in Maya.")
    parser.add_argument("--maya_file", required=True)
    parser.add_argument("--export_path", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--start_frame", type=int, required=True)
    parser.add_argument("--end_frame", type=int, required=True)
    parser.add_argument("--nodes", nargs="*", default=None)
    parser.add_argument("--reference_paths", nargs="*", default=None)


    args = parser.parse_args()
    export_animation(
        args.maya_file,
        args.export_path,
        args.namespace,
        args.start_frame,
        args.end_frame,
        args.nodes,
        args.reference_paths
    )
