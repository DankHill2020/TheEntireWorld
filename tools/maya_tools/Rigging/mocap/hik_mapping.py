"""HumanIK mapping profiles resolved and validated against Maya skeletons."""

from __future__ import annotations

import copy
import json

from maya import cmds

from maya_tools.Rigging.mocap import setup_hik


REQUIRED_BODY_SLOTS = {
    "Reference", "Hips", "Spine", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
    "RightUpLeg", "RightLeg", "RightFoot",
}

# Missing middle slots can be repaired only when mapped endpoints prove one
# unique joint. These relationships are part of the HumanIK schema.
TOPOLOGY_REPAIRS = {
    "LeftForeArm": ("LeftArm", "LeftHand"),
    "RightForeArm": ("RightArm", "RightHand"),
}


def unqualified_name(node):
    """Return a DAG and namespace independent Maya node name."""

    return str(node).split("|")[-1].split(":")[-1]


def stable_node_name(node):
    """Return the shortest namespace-qualified name stable under reparenting."""

    return str(node).split("|")[-1]


def load_profile(json_path, base_joint_map=None):
    """Load a serialized HumanIK map without modifying the shared default."""

    with open(json_path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("HumanIK mapping JSON must contain an object of slot records")
    # Generated profiles carry provenance beside the mapping. Legacy/UI files
    # remain plain slot dictionaries and continue to load unchanged.
    if "mapping" in data:
        if not isinstance(data["mapping"], dict):
            raise ValueError("HumanIK profile mapping must contain an object")
        data = data["mapping"]

    result = copy.deepcopy(base_joint_map or setup_hik.DEFAULT_JOINT_MAP)
    for slot, value in data.items():
        if not isinstance(value, dict):
            raise ValueError(f"HumanIK slot {slot!r} must contain an object")
        if "index" not in value or "joint" not in value:
            raise ValueError(f"HumanIK slot {slot!r} requires index and joint fields")
        try:
            index = int(value["index"])
        except (TypeError, ValueError):
            raise ValueError(f"HumanIK slot {slot!r} has an invalid index")
        result[slot] = {"index": index, "joint": str(value["joint"] or "").strip()}
    return result


def from_character_definition(character, base_joint_map=None):
    """Read slot connections supported by the active Maya HIK node version."""

    if not character or not cmds.objExists(character):
        return {}
    result = copy.deepcopy(base_joint_map or setup_hik.DEFAULT_JOINT_MAP)
    for slot, row in result.items():
        plug = f"{character}.{slot}"
        if not cmds.objExists(plug):
            row["joint"] = ""
            continue
        matches = cmds.listConnections(
            plug, source=True, destination=False, type="joint"
        ) or []
        row["joint"] = matches[0] if len(matches) == 1 else ""
    return result


def _hierarchy(root_joint):
    if not root_joint or not cmds.objExists(root_joint):
        return []
    roots = cmds.ls(root_joint, long=True) or [root_joint]
    descendants = cmds.listRelatives(
        root_joint, allDescendents=True, type="joint", fullPath=True
    ) or []
    return roots[:1] + descendants


def _resolve_unique(name, hierarchy):
    matches = [joint for joint in hierarchy if unqualified_name(joint) == unqualified_name(name)]
    if len(matches) > 1:
        raise ValueError(f"Joint mapping {name!r} is ambiguous under the selected root")
    return matches[0] if matches else ""


def _between(ancestor, descendant):
    chain = []
    current = descendant
    while current and current != ancestor:
        parents = cmds.listRelatives(
            current, parent=True, type="joint", fullPath=True
        ) or []
        if not parents:
            return []
        current = parents[0]
        if current != ancestor:
            chain.append(current)
    return list(reversed(chain)) if current == ancestor else []


def resolve_to_scene(joint_map, root_joint, repair_required=True):
    """Resolve one mapping to one hierarchy and return validation provenance."""

    hierarchy = _hierarchy(root_joint)
    if not hierarchy:
        raise ValueError(f"Skeleton root does not exist: {root_joint}")

    resolved = copy.deepcopy(joint_map)
    unresolved = []
    for slot, row in resolved.items():
        joint = str((row or {}).get("joint") or "").strip()
        if not joint:
            row["joint"] = ""
            continue
        scene_joint = _resolve_unique(joint, hierarchy)
        if scene_joint:
            row["joint"] = scene_joint
        else:
            unresolved.append({"slot": slot, "joint": joint})
            row["joint"] = ""

    repairs = []
    if repair_required:
        for slot, (parent_slot, child_slot) in TOPOLOGY_REPAIRS.items():
            if (resolved.get(slot) or {}).get("joint"):
                continue
            parent = (resolved.get(parent_slot) or {}).get("joint")
            child = (resolved.get(child_slot) or {}).get("joint")
            between = _between(parent, child) if parent and child else []
            if len(between) == 1:
                resolved[slot]["joint"] = between[0]
                repairs.append({
                    "slot": slot,
                    "joint": between[0],
                    "evidence": f"unique path between {parent_slot} and {child_slot}",
                })

    missing_required = sorted(
        slot for slot in REQUIRED_BODY_SLOTS
        if not (resolved.get(slot) or {}).get("joint")
    )
    for row in resolved.values():
        if (row or {}).get("joint"):
            row["joint"] = stable_node_name(row["joint"])
    for repair in repairs:
        repair["joint"] = stable_node_name(repair["joint"])
    return resolved, {
        "root": hierarchy[0],
        "mapped_slot_count": sum(bool((row or {}).get("joint")) for row in resolved.values()),
        "repairs": repairs,
        "unresolved": unresolved,
        "missing_required": missing_required,
    }
