from __future__ import annotations

"""Rig template loading helpers for Maya rigging workflows."""

import json
import re
from pathlib import Path

import maya.cmds as cmds


DEFAULT_BIPED_RIG_TEMPLATE = "C:/depot/ArtSource/Rigs/rig_template.ma"
DEFAULT_VEHICLE_RIG_TEMPLATE = str(
    Path(__file__).resolve().parent / "templates" / "vehicle_rig_template.ma"
).replace("\\", "/")
VEHICLE_RIG_SCHEMA = "tech_connector.vehicle_rig.v1"


def _short_name(node: str) -> str:
    return str(node or "").split("|")[-1].split(":")[-1]


def _is_rfl_joint(node: str) -> bool:
    return _short_name(node).endswith("_RFL")


def _top_level_anim_bot_containers():
    result = []
    for node in cmds.ls("animBot*", type="dagContainer", long=True) or []:
        if cmds.listRelatives(node, parent=True):
            continue
        if re.search(r"(?:^|_)animBot\d*$", _short_name(node), re.IGNORECASE):
            result.append(node)
    for node in cmds.ls("*_animBot*", type="dagContainer", long=True) or []:
        if node in result or cmds.listRelatives(node, parent=True):
            continue
        if re.search(r"(?:^|_)animBot\d*$", _short_name(node), re.IGNORECASE):
            result.append(node)
    return result


def _remove_duplicate_anim_bot_containers():
    containers = _top_level_anim_bot_containers()
    if len(containers) <= 1:
        return []
    canonical = next(
        (node for node in containers if _short_name(node).lower() == "animbot"),
        containers[0],
    )
    removed = []
    for node in containers:
        if node == canonical or cmds.referenceQuery(node, isNodeReferenced=True):
            continue
        removed.append(node)
        cmds.delete(node)
    return removed


def _top_level_display_point_helpers():
    helpers = []
    for node in cmds.ls(assemblies=True, type="transform", long=True) or []:
        children = cmds.listRelatives(node, children=True, fullPath=True) or []
        if not children:
            continue
        if not all(cmds.nodeType(child) == "displayPoints" for child in children):
            continue
        if any(cmds.listConnections(child) for child in children):
            continue
        helpers.append(node)
    return helpers


def _remove_duplicate_display_point_helpers():
    """Keep one disconnected template displayPoints helper across imports."""
    helpers = _top_level_display_point_helpers()
    if len(helpers) <= 1:
        return []
    canonical = next(
        (node for node in helpers if _short_name(node).lower() == "transform1"),
        helpers[0],
    )
    removed = []
    for node in helpers:
        if node == canonical:
            continue
        try:
            referenced = cmds.referenceQuery(node, isNodeReferenced=True)
        except RuntimeError:
            referenced = False
        if not referenced:
            removed.append(node)

    # Delete the full set in one Maya command. Deleting these one by one can
    # cause Maya to rename a collision-suffixed sibling after each deletion,
    # invalidating the remaining long DAG paths before the loop reaches them.
    if removed:
        cmds.delete(removed)
    return removed


def _template_display_layer_role(node: str) -> str:
    """Return the template role for Maya's collision-renamed display layers."""
    short_name = _short_name(node)
    match = re.match(
        r"^(?:rig_template_)?_(geo|joints)[0-9]*$",
        short_name,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else ""


def _make_display_layer_editable(layer: str) -> None:
    """Leave placement layers visible and selectable after template import."""
    try:
        cmds.lockNode(layer, lock=False)
    except Exception:
        pass
    for attribute in ("visibility", "displayType"):
        plug = "{0}.{1}".format(layer, attribute)
        if not cmds.objExists(plug):
            continue
        try:
            cmds.setAttr(plug, lock=False)
        except Exception:
            pass
    cmds.setAttr("{0}.visibility".format(layer), True)
    cmds.setAttr("{0}.displayType".format(layer), 0)


def _consolidate_template_display_layers():
    """Merge repeated template-import layers into one geo/joints layer pair.

    Maya does not merge display layers during scene import. When _geo and
    _joints already exist, it creates rig_template__geo, then
    rig_template__geo1 and so on. Move every member to the stable base
    layer before deleting only the redundant layer nodes.
    """
    by_role = {"geo": [], "joints": []}
    for layer in cmds.ls(type="displayLayer") or []:
        role = _template_display_layer_role(layer)
        if role:
            by_role[role].append(layer)

    removed = []
    canonical_layers = {}
    for role, layers in by_role.items():
        if not layers:
            continue
        preferred = "_{0}".format(role)
        canonical = next(
            (layer for layer in layers if _short_name(layer).lower() == preferred),
            sorted(layers, key=lambda value: (_short_name(value).lower(), value))[0],
        )
        _make_display_layer_editable(canonical)
        for layer in layers:
            if layer == canonical or cmds.referenceQuery(layer, isNodeReferenced=True):
                continue
            members = cmds.editDisplayLayerMembers(layer, q=True, fullNames=True) or []
            if members:
                cmds.editDisplayLayerMembers(canonical, members, noRecurse=True)
            cmds.delete(layer)
            removed.append(layer)
        _make_display_layer_editable(canonical)
        canonical_layers[role] = canonical
    return {"canonical": canonical_layers, "removed": removed}


def load_biped_rig_template(
    template_path: str = DEFAULT_BIPED_RIG_TEMPLATE,
    namespace: str = "",
    reference: bool = False,
    merge_namespaces_on_clash: bool = False,
) -> dict:
    """Import or reference the biped rig template and report skeleton/RFL joints."""
    path = Path(template_path).expanduser()
    if not path.exists():
        raise RuntimeError("Rig template does not exist: {0}".format(path))

    removed_duplicate_anim_bot = (
        _remove_duplicate_anim_bot_containers() if not namespace else []
    )
    removed_duplicate_display_points = (
        _remove_duplicate_display_point_helpers()
        if not namespace and not reference
        else []
    )
    display_layer_cleanup = (
        _consolidate_template_display_layers()
        if not namespace and not reference
        else {"canonical": {}, "removed": []}
    )
    before = set(cmds.ls(long=True) or [])
    existing_anim_bot = _top_level_anim_bot_containers() if not namespace else []
    kwargs = {
        "ignoreVersion": True,
        "returnNewNodes": True,
        "preserveReferences": True,
    }
    if namespace:
        kwargs["namespace"] = namespace
    if reference:
        new_nodes = cmds.file(str(path), reference=True, **kwargs) or []
    else:
        kwargs["mergeNamespacesOnClash"] = bool(merge_namespaces_on_clash)
        new_nodes = cmds.file(str(path), i=True, **kwargs) or []

    if existing_anim_bot and not reference and not namespace:
        # animBot is scene-global helper state, not part of the fitted skeleton.
        # Repeated template imports must preserve the existing container rather
        # than allowing Maya to create animBot1, animBot2, and so on.
        for node in list(new_nodes):
            if not cmds.objExists(node) or cmds.nodeType(node) != "dagContainer":
                continue
            long_name = (cmds.ls(node, long=True) or [node])[0]
            if long_name in before or cmds.listRelatives(long_name, parent=True):
                continue
            if not re.search(r"(?:^|_)animBot\d*$", _short_name(long_name), re.IGNORECASE):
                continue
            if long_name not in removed_duplicate_anim_bot:
                removed_duplicate_anim_bot.append(long_name)
            cmds.delete(long_name)
        new_nodes = [node for node in new_nodes if cmds.objExists(node)]

    if not namespace and not reference:
        post_import_cleanup = _consolidate_template_display_layers()
        display_layer_cleanup["canonical"].update(post_import_cleanup["canonical"])
        display_layer_cleanup["removed"].extend(post_import_cleanup["removed"])
        removed_duplicate_display_points.extend(
            _remove_duplicate_display_point_helpers()
        )
        new_nodes = [node for node in new_nodes if cmds.objExists(node)]

    if not new_nodes:
        after = set(cmds.ls(long=True) or [])
        new_nodes = sorted(after - before)

    joints = [node for node in new_nodes if cmds.objExists(node) and cmds.nodeType(node) == "joint"]
    if not joints:
        joints = cmds.ls(type="joint", long=True) or []
    rfl_joints = [node for node in joints if _is_rfl_joint(node)]
    child_joints = set(cmds.listRelatives(joints, children=True, type="joint", fullPath=True) or [])
    root_joints = [node for node in joints if node not in child_joints]

    report = {
        "ok": True,
        "template_path": str(path).replace("\\", "/"),
        "reference": bool(reference),
        "namespace": namespace,
        "new_node_count": len(new_nodes),
        "removed_duplicate_anim_bot": removed_duplicate_anim_bot,
        "removed_duplicate_display_points": removed_duplicate_display_points,
        "display_layers": display_layer_cleanup["canonical"],
        "removed_duplicate_display_layers": display_layer_cleanup["removed"],
        "joint_count": len(joints),
        "root_joints": root_joints,
        "rfl_joints": rfl_joints,
        "rfl_joint_count": len(rfl_joints),
        "sample_joints": joints[:40],
    }
    print(json.dumps(report, indent=2))
    return report


def load_default_biped_rig_template(reference: bool = False, namespace: str = "") -> dict:
    return load_biped_rig_template(
        DEFAULT_BIPED_RIG_TEMPLATE,
        namespace=namespace,
        reference=reference,
    )


def _vehicle_role(node: str) -> str:
    plug = "{0}.tcVehicleRole".format(node)
    if not cmds.objExists(plug):
        return ""
    try:
        return str(cmds.getAttr(plug) or "")
    except (RuntimeError, ValueError):
        return ""


def load_vehicle_rig_template(
    template_path: str = DEFAULT_VEHICLE_RIG_TEMPLATE,
    namespace: str = "",
    reference: bool = False,
    merge_namespaces_on_clash: bool = False,
) -> dict:
    """Import the joint-only vehicle template and report its portable roles.

    SI-unit configuration is stored as attributes on the joints. Controls,
    geometry, constraints, and ground-query nodes are created later by the
    host vehicle-rig builder.
    """
    path = Path(template_path).expanduser()
    if not path.exists():
        raise RuntimeError("Vehicle rig template does not exist: {0}".format(path))

    before = set(cmds.ls(long=True) or [])
    kwargs = {
        "ignoreVersion": True,
        "returnNewNodes": True,
        "preserveReferences": True,
    }
    if namespace:
        kwargs["namespace"] = namespace
    if reference:
        new_nodes = cmds.file(str(path), reference=True, **kwargs) or []
    else:
        kwargs["mergeNamespacesOnClash"] = bool(merge_namespaces_on_clash)
        new_nodes = cmds.file(str(path), i=True, **kwargs) or []
    if not new_nodes:
        new_nodes = sorted(set(cmds.ls(long=True) or []) - before)

    existing_nodes = [node for node in new_nodes if cmds.objExists(node)]
    roles = {}
    for node in existing_nodes:
        role = _vehicle_role(node)
        if role:
            roles.setdefault(role, []).append(node)

    roots = roles.get("root", [])
    schemas = []
    for root in roots:
        plug = "{0}.tcVehicleSchema".format(root)
        if cmds.objExists(plug):
            schemas.append(str(cmds.getAttr(plug) or ""))
    if roots and VEHICLE_RIG_SCHEMA not in schemas:
        raise RuntimeError("Unsupported vehicle rig template schema: {0}".format(schemas))

    definitions = []
    for node in roots:
        plug = "{0}.tcVehicleDefinition".format(node)
        if not cmds.objExists(plug):
            continue
        try:
            definitions.append(json.loads(cmds.getAttr(plug)))
        except (TypeError, ValueError, RuntimeError):
            pass

    report = {
        "ok": bool(roots),
        "schema": schemas[0] if schemas else "",
        "template_path": str(path).replace("\\", "/"),
        "reference": bool(reference),
        "namespace": namespace,
        "new_node_count": len(existing_nodes),
        "roles": roles,
        "root_joints": roots,
        "chassis_joints": roles.get("chassis", []),
        "wheel_mounts": roles.get("wheel_mount", []),
        "wheel_joints": roles.get("wheel", []),
        "ground_contacts": roles.get("ground_contact", []),
        "definition": definitions[0] if definitions else {},
    }
    print(json.dumps(report, indent=2))
    return report


def load_default_vehicle_rig_template(reference: bool = False, namespace: str = "") -> dict:
    return load_vehicle_rig_template(
        DEFAULT_VEHICLE_RIG_TEMPLATE,
        namespace=namespace,
        reference=reference,
    )
