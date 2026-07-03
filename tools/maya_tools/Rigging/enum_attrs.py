import os
import json
import maya.cmds as cmds


# =========================================================
# ENUM QUERY / STORAGE
# =========================================================

def get_enum_labels(node, attr):
    data = cmds.attributeQuery(attr, node=node, listEnum=True)
    if not data:
        return []
    return data[0].split(":")


def get_enum_attrs(node):
    attrs = cmds.listAttr(node, scalar=True) or []
    result = []
    for attr in attrs:
        plug = "{}.{}".format(node, attr)
        try:
            if cmds.getAttr(plug, type=True) == "enum":
                result.append(attr)
        except Exception:
            pass
    return result


def collect_enum_data(nodes=None, attr_filter=None, strip_namespaces=True):
    """
    Collect enum definitions from nodes.

    Parameters
    ----------
    nodes : list[str] or None
        Nodes to inspect. If None, uses selection.
    attr_filter : list[str] or None
        If provided, only these enum attrs are exported.
    strip_namespaces : bool
        If True, stores short node names without namespaces.

    Returns
    -------
    dict
    """
    if nodes is None:
        nodes = cmds.ls(sl=True, long=True) or []

    export_data = {}

    for node in nodes:
        if not cmds.objExists(node):
            continue

        enum_attrs = get_enum_attrs(node)
        if attr_filter:
            enum_attrs = [a for a in enum_attrs if a in attr_filter]

        if strip_namespaces:
            key_node = node.split("|")[-1].split(":")[-1]
        else:
            key_node = node

        node_data = {}

        for attr in enum_attrs:
            labels = get_enum_labels(node, attr)
            if not labels:
                continue

            plug = "{}.{}".format(node, attr)
            try:
                current_value = cmds.getAttr(plug)
            except Exception:
                current_value = None

            node_data[attr] = {
                "labels": labels,
                "value": current_value,
            }

        if node_data:
            export_data[key_node] = node_data

    return export_data


def save_enum_data_to_json(filepath, nodes=None, attr_filter=None, strip_namespaces=True):
    data = collect_enum_data(
        nodes=nodes,
        attr_filter=attr_filter,
        strip_namespaces=strip_namespaces
    )

    folder = os.path.dirname(filepath)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)

    print("Saved enum data to: {}".format(filepath))
    return filepath


def load_enum_data_from_json(filepath):
    if not os.path.exists(filepath):
        raise RuntimeError("JSON file does not exist: {}".format(filepath))

    with open(filepath, "r") as f:
        return json.load(f)


# =========================================================
# CONNECTION HELPERS
# =========================================================

def get_attr_connections(plug):
    """
    Returns incoming and outgoing connections for an attribute plug.
    """
    incoming = cmds.connectionInfo(plug, sourceFromDestination=True) or None
    outgoing = cmds.connectionInfo(plug, destinationFromSource=True) or []
    return incoming, outgoing


def disconnect_attr_connections(plug):
    incoming, outgoing = get_attr_connections(plug)

    if incoming and cmds.isConnected(incoming, plug):
        cmds.disconnectAttr(incoming, plug)

    for dst in outgoing:
        if cmds.isConnected(plug, dst):
            cmds.disconnectAttr(plug, dst)

    return incoming, outgoing


def reconnect_attr_connections(plug, incoming, outgoing):
    if incoming:
        try:
            cmds.connectAttr(incoming, plug, force=True)
        except Exception as exc:
            print("Failed reconnect incoming {} -> {} : {}".format(incoming, plug, exc))

    for dst in outgoing:
        try:
            cmds.connectAttr(plug, dst, force=True)
        except Exception as exc:
            print("Failed reconnect outgoing {} -> {} : {}".format(plug, dst, exc))


# =========================================================
# ENUM REBUILD
# =========================================================

def rebuild_enum_attr_with_order(node, attr, new_labels, preserve_value_by_label=True, verbose=True):
    """
    Rebuild enum order on an existing attr while preserving connections.

    Notes
    -----
    - This preserves raw connections by disconnecting and reconnecting them.
    - It remaps the attr's local current value by label when possible.
    - It does NOT remap animated/int-driven upstream values by semantic label.
      If you need that too, this can be expanded later.
    """
    plug = "{}.{}".format(node, attr)

    if not cmds.objExists(plug):
        if verbose:
            print("Missing attr: {}".format(plug))
        return False

    try:
        attr_type = cmds.getAttr(plug, type=True)
    except Exception as exc:
        if verbose:
            print("Could not read type for {} : {}".format(plug, exc))
        return False

    if attr_type != "enum":
        if verbose:
            print("Skipping non-enum: {}".format(plug))
        return False

    old_labels = get_enum_labels(node, attr)
    if not old_labels:
        if verbose:
            print("No enum labels found on {}".format(plug))
        return False

    old_value = None
    old_label = None
    try:
        old_value = cmds.getAttr(plug)
        if 0 <= old_value < len(old_labels):
            old_label = old_labels[old_value]
    except Exception:
        pass

    incoming, outgoing = disconnect_attr_connections(plug)

    was_locked = False
    try:
        was_locked = cmds.getAttr(plug, lock=True)
        if was_locked:
            cmds.setAttr(plug, lock=False)
    except Exception:
        pass

    success = True

    try:
        cmds.addAttr(plug, edit=True, enumName=":".join(new_labels))

        if preserve_value_by_label and old_label in new_labels:
            try:
                cmds.setAttr(plug, new_labels.index(old_label))
            except Exception as exc:
                if verbose:
                    print("Could not restore value for {} : {}".format(plug, exc))
    except Exception as exc:
        success = False
        if verbose:
            print("Failed rebuilding {} : {}".format(plug, exc))

    reconnect_attr_connections(plug, incoming, outgoing)

    if was_locked:
        try:
            cmds.setAttr(plug, lock=True)
        except Exception:
            pass

    if verbose:
        print("Rebuilt {} | old={} | new={}".format(plug, old_labels, new_labels))

    return success


# =========================================================
# APPLY TO TARGET SCENE
# =========================================================

def build_node_lookup(strip_namespaces=True):
    """
    Build a lookup of scene nodes by short name.
    """
    nodes = cmds.ls(long=True) or []
    lookup = {}

    for node in nodes:
        if strip_namespaces:
            key = node.split("|")[-1].split(":")[-1]
        else:
            key = node

        if key not in lookup:
            lookup[key] = []
        lookup[key].append(node)

    return lookup


def apply_enum_data(data, prefer_first_match=True, strip_namespaces=True, verbose=True):
    """
    Apply stored enum data to matching nodes in the current scene.
    """
    node_lookup = build_node_lookup(strip_namespaces=strip_namespaces)

    results = {
        "updated": [],
        "missing_nodes": [],
        "missing_attrs": [],
        "failed": [],
    }

    for stored_node, attr_map in data.items():
        matches = node_lookup.get(stored_node, [])

        if not matches:
            results["missing_nodes"].append(stored_node)
            if verbose:
                print("No matching node found for: {}".format(stored_node))
            continue

        target_node = matches[0] if prefer_first_match else matches

        if isinstance(target_node, list):
            target_node = target_node[0]

        for attr, attr_data in attr_map.items():
            plug = "{}.{}".format(target_node, attr)

            if not cmds.objExists(plug):
                results["missing_attrs"].append(plug)
                if verbose:
                    print("Missing attr: {}".format(plug))
                continue

            labels = attr_data.get("labels", [])
            if not labels:
                continue

            ok = rebuild_enum_attr_with_order(
                target_node,
                attr,
                labels,
                preserve_value_by_label=True,
                verbose=verbose
            )

            if ok:
                results["updated"].append(plug)
            else:
                results["failed"].append(plug)

    return results


# =========================================================
# CONVENIENCE WRAPPERS
# =========================================================

def export_selected_enum_orders(filepath, attr_filter=None):
    """
    Export enum label orders from selected nodes to JSON.
    """
    return save_enum_data_to_json(
        filepath=filepath,
        nodes=cmds.ls(sl=True, long=True),
        attr_filter=attr_filter,
        strip_namespaces=True
    )


def import_enum_orders(filepath):
    """
    Import enum label orders from JSON and apply them to matching nodes
    in the currently opened scene.
    """
    data = load_enum_data_from_json(filepath)
    return apply_enum_data(
        data,
        prefer_first_match=True,
        strip_namespaces=True,
        verbose=True
    )


# =========================================================
# EXAMPLE USAGE
# =========================================================

# 1. In the source file:
# Select the controls you want to export, then run:
#
# export_selected_enum_orders(
#     r"C:/temp/enum_orders.json",
#     attr_filter=None
# )
#
# or restrict to common space-switch attrs:
#
# export_selected_enum_orders(
#     r"C:/temp/enum_orders.json",
#     attr_filter=["space", "follow", "parent", "orientSpace"]
# )


# 2. Open the target file:
# Then run:
#
import_enum_orders(r"C:/temp/enum_orders.json")
#
# This will:
# - find matching nodes by short name
# - find matching enum attrs by attr name
# - rebuild the enum labels in the exported order
# - disconnect and reconnect existing incoming/outgoing connections
# - restore the current enum value by matching the label when possible