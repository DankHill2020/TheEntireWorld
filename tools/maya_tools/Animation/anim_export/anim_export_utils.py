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
    Find all reference nodes (including sub-references and constraint dependencies)
    associated with a given namespace.

    :param namespace: The namespace you want to check, e.g., 'Test:sub_rig'.
    :return: List of [ref_path, ref_node] pairs.
    """

    reference_info = []
    seen_ref_nodes = set()
    seen_ref_paths = set()

    all_ref_nodes = cmds.ls(type="reference") or []

    def add_reference(ref_path, ref_node):
        clean_path = ref_path.split('{')[0]
        if ref_node not in seen_ref_nodes and clean_path not in seen_ref_paths:
            reference_info.append([clean_path, ref_node])
            seen_ref_nodes.add(ref_node)
            seen_ref_paths.add(clean_path)

    def get_ref_node(node):
        try:
            return cmds.referenceQuery(node, referenceNode=True)
        except:
            return None

    for ref_node in all_ref_nodes:
        try:
            ref_namespace = cmds.referenceQuery(ref_node, namespace=True).lstrip(':')
            if ref_namespace.startswith(namespace):
                ref_path = cmds.referenceQuery(ref_node, filename=True, unresolvedName=False)
                add_reference(ref_path, ref_node)

                # Also get sub-reference nodes using same file
                for other_ref_node in all_ref_nodes:
                    try:
                        other_path = cmds.referenceQuery(other_ref_node, filename=True, unresolvedName=False)
                        if other_path == ref_path and other_ref_node != ref_node:
                            add_reference(other_path, other_ref_node)
                    except:
                        continue

                # Find constraint dependencies
                nodes = cmds.referenceQuery(ref_node, nodes=True, dp=True) or []
                for node in nodes:
                    incoming = cmds.listConnections(node, source=True, destination=False, plugs=False) or []
                    for src_node in incoming:
                        if cmds.nodeType(src_node).endswith("Constraint"):
                            drivers = cmds.listConnections(src_node + ".target[0].targetParentMatrix", source=True, destination=False) or []
                            for driver in drivers:
                                driver_ref_node = get_ref_node(driver)
                                if driver_ref_node and driver_ref_node not in seen_ref_nodes:
                                    driver_ref_path = cmds.referenceQuery(driver_ref_node, filename=True, unresolvedName=False)
                                    add_reference(driver_ref_path, driver_ref_node)

        except:
            continue

    return reference_info