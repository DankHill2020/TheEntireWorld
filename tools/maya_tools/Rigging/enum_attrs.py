import os
import json
import maya.cmds as cmds

SPACE_TARGET_MAP = {
    "World": "origin_ctrl",
    "Pelvis": "pelvis_ctrl",
    "Hip": "pelvis_ctrl",
    "Neck": "neck2_ctrl",
    "Spine5": "spine5_Tip_ctrl",
}

SIDE_SPACE_TARGET_MAP = {
    "Clav": "{side}_clavicle_ctrl",
    "Hand": "{side}_hand_ik_ctrl",
    "Foot": "{side}_ankle_ik_ctrl",
    "Hand and Clav": "{side}_arm_pv_handClav_space",
    "Foot And Hip": "{side}_leg_pv_footHip_space",
    "Foot and Hip": "{side}_leg_pv_footHip_space",
    "Foot Hip": "{side}_leg_pv_footHip_space",
}

def get_side_from_node(node):
    short = node.split("|")[-1].split(":")[-1]
    if short.startswith("l_"):
        return "l"
    if short.startswith("r_"):
        return "r"
    return None


def resolve_space_target(label, node=None, side=None):
    if label in SPACE_TARGET_MAP:
        return SPACE_TARGET_MAP[label]

    if side is None and node:
        side = get_side_from_node(node)

    template = SIDE_SPACE_TARGET_MAP.get(label)
    if template and side:
        return template.format(side=side)

    return None


def resolve_space_targets_from_labels(labels, node=None, side=None, require_existing=True):
    targets = []

    for label in labels:
        target = resolve_space_target(label, node=node, side=side)

        if not target:
            cmds.warning("No space target mapping found for label: {}".format(label))
            targets.append(None)
            continue

        if require_existing and not cmds.objExists(target):
            cmds.warning("Mapped space target does not exist: {} -> {}".format(label, target))
            targets.append(None)
            continue

        targets.append(target)

    return targets

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

            current_label = None
            if isinstance(current_value, int) and 0 <= current_value < len(labels):
                current_label = labels[current_value]

            node_data[attr] = {
                "labels": labels,
                "value": current_value,
                "label": current_label,
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


def rebuild_enum_attr_with_order(node, attr, new_labels, preserve_value_by_label=True, stored_label=None, stored_value=None, verbose=True):
    """
    Rebuild enum order on an existing attr while preserving connections.

    Notes
    -----
    - This preserves raw connections by disconnecting and reconnecting them.
    - It remaps the attr's local current value by label when possible.
    - If stored_label is supplied, it will restore the saved enum selection by label.
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

        restored = False

        def apply_label(label):
            if label not in new_labels:
                return False
            try:
                cmds.setAttr(plug, new_labels.index(label))
                return True
            except Exception:
                try:
                    cmds.setAttr(plug, label, type="enum")
                    return True
                except Exception:
                    return False

        if stored_label and apply_label(stored_label):
            restored = True
        elif preserve_value_by_label and old_label and apply_label(old_label):
            restored = True
        elif isinstance(stored_value, int) and 0 <= stored_value < len(new_labels):
            try:
                cmds.setAttr(plug, stored_value)
                restored = True
            except Exception:
                pass
        elif isinstance(old_value, int) and 0 <= old_value < len(new_labels):
            try:
                cmds.setAttr(plug, old_value)
                restored = True
            except Exception:
                pass

        if not restored and verbose:
            print("Could not restore enum value for {} | stored_label={} stored_value={} old_label={} old_value={}".format(
                plug, stored_label, stored_value, old_label, old_value
            ))
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
            if attr == "space":
                targets = resolve_space_targets_from_labels(
                    labels,
                    node=target_node,
                    require_existing=True
                )

                attr_data["targets"] = targets

                if verbose:
                    print("Resolved space targets for {}.{} : {}".format(
                        target_node,
                        attr,
                        list(zip(labels, targets))
                    ))
            stored_label = attr_data.get("label")
            stored_value = attr_data.get("value")
            if stored_label is None and isinstance(stored_value, int) and 0 <= stored_value < len(labels):
                stored_label = labels[stored_value]
            elif stored_label is None and isinstance(stored_value, str) and stored_value in labels:
                stored_label = stored_value

            ok = rebuild_enum_attr_with_order(
                target_node,
                attr,
                labels,
                preserve_value_by_label=True,
                stored_label=stored_label,
                stored_value=stored_value,
                verbose=verbose
            )

            if ok:
                results["updated"].append(plug)
            else:
                results["failed"].append(plug)

    return results


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
#import_enum_orders(r"C:/temp/enum_orders.json")
#
# This will:
# - find matching nodes by short name
# - find matching enum attrs by attr name
# - rebuild the enum labels in the exported order
# - disconnect and reconnect existing incoming/outgoing connections
