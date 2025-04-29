import maya.standalone
maya.standalone.initialize()
import maya.cmds as cmds
import maya.mel as mel
import os
import sys
from maya_tools.Animation.anim_export import anim_export_utils
from maya_tools.Utilities import joints


def export_animation(maya_file, export_path, namespace, start_frame, end_frame, nodes=None, reference_paths=None):
    """
    Opens Maya file and exports animation to FBX using `mayapy`.
    :param maya_file: (str): Path to the Maya scene file.
    :param export_path: (str): Path where the FBX should be saved.
    :param namespace: (str): Namespace of the skeleton.
    :param start_frame: (int): Start frame of the animation.
    :param end_frame: (int): End frame of the animation.
    :param nodes: (list, optional): Specific nodes to export instead.
    :param reference_paths: (str, optional): Specific reference path to load
    :return:
    """
    full_ns = namespace + ':'
    reference_paths = eval(reference_paths[0])
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        try:
            cmds.loadPlugin("fbxmaya")
        except RuntimeError as e:
            raise RuntimeError(f"Failed to load FBX plugin: {e}")
    try:
        if not reference_paths:
            if cmds.file(query=True, sceneName=True).replace('\\', '/') != maya_file:
                cmds.file(maya_file, open=True, force=True)
        else:
            anim_export_utils.open_scene_with_specific_references(maya_file, reference_paths)
        roots = joints.find_skinned_or_top_joints(full_ns)
        root=None
        root_joint = None
        if roots:
            root = roots[0]
            root_joint = root.split(":")[-1]

        if not nodes:
            if roots and len(roots) > 1:
                children = cmds.listRelatives(root, c=1, ad=1) or []
                if any("FACIAL" in child for child in children):
                    root = roots[1]
            if cmds.objExists(root):
                nodes = import_reference_and_strip_namespace_test(namespace, root)

                facial_joints = anim_export_utils.get_facial_joints("")

                facial_joints = facial_joints[0]
                delete_list = add_missing_parents_with_long_names(facial_joints)
                cmds.delete(delete_list)
            else:
                raise ValueError(f"Skeleton root '{root}' does not exist.")
        else:

            if "FacialJoints" in nodes:
                import_reference_and_strip_namespace_test(namespace, root)
                facial_joints = anim_export_utils.get_facial_joints("")[0]
                nodes = update_joint_setup_for_import(facial_joints)
            else:
                if root and namespace != "CAM":
                    import_reference_and_strip_namespace_test(namespace, root)

        if "FacialSliders" not in nodes and root_joint:
            if cmds.objExists(root_joint.split(":")[-1]):
                if root_joint not in nodes:
                    nodes.insert(0, root_joint)

        if cmds.objExists(root):
            cmds.parent(root, w=1)
        export_path = export_path.replace("\\", "/")
        export_dir = os.path.dirname(export_path)

        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        if 'FacialSliders' in nodes and cmds.objExists('FacialControls'):

            export_metahuman_sliders_as_fbx(slider_set='FacialControls', fbx_path=export_path, start_frame=start_frame, end_frame=end_frame)
        else:
            try:
                cmds.select(nodes)
            except:
                cmds.select(d=1)
                for node in nodes:
                    if cmds.objExists(node):
                        cmds.select(node, add=True)
                    else:
                        if cmds.objExists(node.split('|')[-1]):
                            cmds.select(node.split('|')[-1], add=1)

            bake_all_keyable_attributes(cmds.ls(sl=True), start_frame, end_frame)
            mel.eval("FBXResetExport;")
            mel.eval("FBXExportCameras -v 1;")
            mel.eval('FBXExportAnimationOnly -v 0')
            mel.eval("FBXExportBakeComplexAnimation -v 1;")
            mel.eval("FBXExportConstraints -v 0;")
            mel.eval("FBXExportApplyConstantKeyReducer -v 0;")
            mel.eval(f'FBXExport -f "{export_path}" -s')
    except Exception as e:
        print(f"Export failed: {e}", file=sys.stderr)
    finally:
        cmds.quit(force=True)


def bake_all_keyable_attributes(nodes, start_frame, end_frame):
    all_attrs_to_bake = []

    for node in nodes:
        for attr in ['translateX', 'translateY', 'translateZ',
                     'rotateX', 'rotateY', 'rotateZ',
                     'scaleX', 'scaleY', 'scaleZ']:
            full_attr = f"{node}.{attr}"
            if cmds.objExists(full_attr):
                all_attrs_to_bake.append(full_attr)

        user_attrs = cmds.listAttr(node, userDefined=True, keyable=True) or []
        for attr in user_attrs:
            full_attr = f"{node}.{attr}"
            all_attrs_to_bake.append(full_attr)

    all_attrs_to_bake = list(set(all_attrs_to_bake))
    cmds.bakeResults(all_attrs_to_bake, time=(start_frame, end_frame), simulation=True)


def export_metahuman_sliders_as_fbx(slider_set='FacialControls', fbx_path='', start_frame=None, end_frame=None):
    """
    Bakes facial slider animation and exports it as an FBX.

    :param slider_set: Name of the set containing facial sliders.
    :param fbx_path: Full file path for the FBX export.
    :param start_frame: Start frame of baking range. Defaults to timeline start.
    :param end_frame: End frame of baking range. Defaults to timeline end.
    """
    if not cmds.objExists(slider_set):
        cmds.error(f"Slider set '{slider_set}' does not exist.")
        return
    if not fbx_path:
        cmds.error("You must provide an FBX export path.")
        return

    start = start_frame if start_frame is not None else cmds.playbackOptions(q=True, min=True)
    end = end_frame if end_frame is not None else cmds.playbackOptions(q=True, max=True)

    slider_nodes = cmds.sets(slider_set, q=True)
    if not slider_nodes:
        cmds.warning(f"No members found in set '{slider_set}'.")
        return

    slider_attrs = []
    for node in slider_nodes:
        attrs = cmds.listAttr(node, keyable=True, scalar=True, unlocked=True)
        if attrs:
            slider_attrs.extend([f"{node}.{a}" for a in attrs])

    if not slider_attrs:
        cmds.warning("No keyable slider attributes found.")
        return

    cmds.bakeResults(slider_attrs, t=(start, end), simulation=True, preserveOutsideKeys=True)

    cmds.select(slider_nodes, replace=True)

    mel.eval('FBXExportBakeComplexAnimation -v true')
    mel.eval(f'FBXExport -f "{fbx_path}" -s')

    print(f"Exported facial slider animation to: {fbx_path}")


def update_joint_setup_for_import(facial_joints):
    """
    Sets up hierachy to match the Face Archetype Skeleton
    :param facial_joints: list of facial joints
    :return:
    """
    no_ns_nodes = []
    for node in facial_joints:
        if node.split(":")[-1]:
            no_ns_nodes.append(node.split(":")[-1])
    nodes = no_ns_nodes
    nodes = add_missing_parents_with_long_names(nodes)
    nodes = sort_reverse_hierarchy(nodes)
    for node in nodes:
        duplicate_test = cmds.ls("*" + node.split('|')[-1])
        if len(duplicate_test) > 1:
            for name in duplicate_test:
                if name not in node and "FACIAL_C_Forehead" not in name:
                    cmds.rename(name, name.split('|')[-1] + "_rename")
    cmds.parent(nodes[-1], w=1)
    cmds.select(d=1)
    facial_parents = ["root", "pelvis", "spine_01", "spine_02", "spine_03"]
    if facial_parents not in nodes:
        for i, f_joint in enumerate(facial_parents):
            old_name = f_joint
            cmds.rename(f_joint, f_joint + "_rename")
            cmds.joint(n=old_name)
            cmds.delete(cmds.parentConstraint(f_joint + "_rename", old_name, mo=False))
            if i == 0:
                cmds.parent(old_name, w=1)
            elif i == 4:
                cmds.parent(nodes[-1].split('|')[-1], old_name)
            else:
                cmds.parent(old_name, facial_parents[i - 1])
    facial_parents.reverse()
    for each in facial_parents:
        nodes.append(each)

    return nodes


def import_reference_and_strip_namespace_test(namespace, root):
    """
    Imports objects from a reference associated with the given namespace,
    imports any nested references, strips all namespaces, renames duplicates,
    and returns a list of renamed transform nodes.

    :param namespace: The namespace of the reference.
    :param root: Root transform node to collect hierarchy from.
    :return: List of renamed transform nodes.
    """
    import_reference_nodes = []

    for ref_node in cmds.ls(type='reference'):
        try:
            ref_namespace = cmds.referenceQuery(ref_node, namespace=True)
            if ref_namespace.strip(':') in namespace:
                import_reference_nodes.append(ref_node)
        except RuntimeError:
            continue

    if not import_reference_nodes:
        cmds.warning(f"No reference nodes found for namespace '{namespace}' or its nested namespaces.")
        return []

    for ref_node in import_reference_nodes:
        try:
            cmds.file(importReference=True, referenceNode=ref_node)
        except RuntimeError as e:
            cmds.warning(f"Failed to import reference '{ref_node}': {e}")

    nodes = cmds.listRelatives(root, allDescendents=True, type="joint") or []
    nodes.append(root)

    renamed_nodes = []
    for node in nodes:
        if ":" in node:
            base_name = node.split(":")[-1]
            new_name = base_name
            suffix = 1

            while cmds.objExists(new_name):
                new_name = f"{base_name}_{suffix}"
                suffix += 1

            try:
                new_node = cmds.rename(node, new_name)
                renamed_nodes.append(new_node)
            except RuntimeError as e:
                cmds.warning(f"Failed to rename node {node}: {e}")
                renamed_nodes.append(node)
        else:
            renamed_nodes.append(node)

    def remove_namespace_recursive(ns):
        try:
            children = cmds.namespaceInfo(ns, listNamespace=True) or []
            for child_ns in children:
                remove_namespace_recursive(child_ns)
            try:
                cmds.namespace(removeNamespace=ns, mergeNamespaceWithRoot=True)
            except RuntimeError as e:
                cmds.warning(f"Failed to remove namespace '{ns}': {e}")
        except:
            pass

    top_level_ns = namespace.split(':')[0]
    remove_namespace_recursive(top_level_ns.strip(":"))

    return renamed_nodes


def add_missing_parents_with_long_names(joint_list):
    """
    Given a list of joints, return the full DAG paths including all parent joints.
    Ensures all names are long paths to avoid ambiguity.

    :param joint_list: List of joint names (can be short or long)
    :return: List of joints including all parents, with long names
    """
    long_joint_list = cmds.ls(joint_list, long=True) or []
    all_joints = set(long_joint_list)
    for joint in long_joint_list:
        current = joint
        while True:
            parent = cmds.listRelatives(current, parent=True, fullPath=True, type="joint")
            if not parent:
                break
            current = parent[0]
            if current not in all_joints:
                all_joints.add(current)

    return list(all_joints)


def sort_reverse_hierarchy(node_list):
    """
    Sorts DAG nodes in reverse hierarchy order (children before parents).
    Assumes all nodes are given as full paths or unique enough to convert to full paths.
    """
    full_paths = cmds.ls(node_list, long=True) or []
    return sorted(full_paths, key=lambda x: x.count('|'), reverse=True)


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
