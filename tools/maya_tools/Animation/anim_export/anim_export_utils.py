import maya.cmds as cmds


def get_facial_sliders(namespace=None):
    """
    Detects the 'FacialControls' set under any namespace (including nested ones) and returns
    the slider nodes and the actual namespace they belong to.

    :param namespace: (optional) A base namespace to filter by.
    :return: Tuple (slider_nodes, actual_namespace) or None if not found.
    """
    sets = cmds.ls(type='objectSet')
    facial_sets = [s for s in sets if s.endswith(":FacialControls")]

    if namespace:
        facial_sets = [s for s in facial_sets if s.startswith(namespace.split(":")[0] + ":")]

    for s in facial_sets:
        members = cmds.sets(s, q=True)
        if members:
            actual_namespace = s.rsplit(":", 1)[0]
            return members, actual_namespace

    cmds.warning(f"No members found in any FacialControls set matching '{namespace or '*'}'.")
    return None, None


def get_facial_joints(namespace):
    """
    Detects joints with 'FACIAL_' in their name within the given namespace (including nested ones).
    Returns the list of joints and the actual namespace.

    :param namespace: Base namespace to filter by (e.g., 'MyChar')
    :return: Tuple (facial_joints, actual_namespace) or (None, None) if not found.
    """
    all_joints = cmds.ls(type ="joint", long=True)
    facial_joints = []
    for joint in all_joints:
        if namespace == "":
            if "FACIAL_" in joint and ":" not in joint:
                facial_joints.append(joint)
        else:
            if "FACIAL_" in joint and namespace in joint:
                facial_joints.append(joint)
    if not facial_joints:
        cmds.warning(f"No facial joints found matching 'FACIAL_' under namespace '{namespace or '*'}'.")
        return [], None

    actual_namespace = facial_joints[0].rsplit(":", 1)[0] if ":" in facial_joints[0] else ""

    actual_namespace = actual_namespace.split('|')[-1]
    return facial_joints, actual_namespace


def open_scene_with_specific_references(maya_file, reference_list):
    """
    Opens a Maya scene and loads only the specified references, ignoring any others.

    :param maya_file: Full path to the .ma or .mb file
    :param reference_list: List of dictionaries [{"path": "...", "namespace": "..."}, ...]
    """

    maya_file = maya_file.replace('\\', '/')

    current_scene = cmds.file(query=True, sceneName=True).replace('\\', '/')

    if current_scene != maya_file:
        cmds.file(maya_file, open=True, force=True, loadReferenceDepth="none", prompt=False)
    all_refs = cmds.ls(type='reference') or []
    for ref in reference_list:
        ref_path = ref[0]
        ref_node = ref[1]

        if not cmds.referenceQuery(ref_node, isLoaded=True) and ref_node in all_refs:
            try:
                cmds.file(ref_path, loadReference=ref_node)
            except:
                print("LOAD FAILED")


def find_references_from_namespace(namespace):
    """
    Find all reference nodes (including sub-references) associated with a given namespace.
    This ensures that each ref_node and ref_path is included only once.

    :param namespace: The namespace you want to check, e.g., 'Test:sub_rig'.
    :return: List of dictionaries with "ref_node" and "ref_path" for each matching reference node.
    """
    reference_info = []
    ref_nodes = cmds.ls(type="reference")

    seen_ref_nodes = set()
    seen_ref_paths = set()

    for ref_node in ref_nodes:
        try:
            ref_namespace = cmds.referenceQuery(ref_node, namespace=True)
            ref_namespace_clean = ref_namespace.lstrip(':')
            if ref_namespace_clean.startswith(namespace):
                ref_path = cmds.referenceQuery(ref_node, filename=True, unresolvedName=False)

                if ref_node not in seen_ref_nodes and ref_path not in seen_ref_paths:
                    reference_info.append([ref_path.split('{')[0], ref_node])
                    seen_ref_nodes.add(ref_node)
                    seen_ref_paths.add(ref_path.split('{')[0])

                all_ref_nodes = cmds.ls(type="reference")
                for other_ref_node in all_ref_nodes:
                    try:
                        other_ref_path = cmds.referenceQuery(other_ref_node, filename=True, unresolvedName=False)
                        if other_ref_path == ref_path and other_ref_node != ref_node:
                            if other_ref_node not in seen_ref_nodes and other_ref_path not in seen_ref_paths:
                                reference_info.append([other_ref_path.split('{')[0], other_ref_node])
                                seen_ref_nodes.add(other_ref_node)
                                seen_ref_paths.add(other_ref_path.split('{')[0])
                    except Exception as e:
                        continue

        except Exception as e:
            continue

    return reference_info