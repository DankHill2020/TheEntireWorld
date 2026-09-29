"""Versioned TC-native skeleton template loading."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX


TC_RIG_TEMPLATE_SCHEMA = "tech_connector.rig_template.v1"
DEFAULT_TC_BIPED_TEMPLATE = str(
    Path(__file__).resolve().parents[2] / "assets" / "templates" / "tc_biped_v1.tcrig.json"
)


def load_tc_rig_template(path: str | Path = DEFAULT_TC_BIPED_TEMPLATE) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if str(payload.get("schema") or "") != TC_RIG_TEMPLATE_SCHEMA:
        raise ValueError("Unsupported TC rig template schema.")
    if not isinstance(payload.get("joints"), list) or not payload["joints"]:
        raise ValueError("A TC rig template must contain joints.")
    payload["source_path"] = str(source)
    return payload


def expanded_tc_rig_template_joints(
    path: str | Path = DEFAULT_TC_BIPED_TEMPLATE,
) -> list[dict[str, Any]]:
    """Return the complete authored hierarchy, including generated finger chains."""

    rows = _expanded_joint_rows(load_tc_rig_template(path))
    _validate_rows(rows)
    return copy.deepcopy(rows)


def instantiate_tc_rig_template(
    graph: EditableRigGraph,
    *,
    template_path: str | Path = DEFAULT_TC_BIPED_TEMPLATE,
    namespace: str = "",
) -> dict[str, Any]:
    template = load_tc_rig_template(template_path)
    rows = _expanded_joint_rows(template)
    _validate_rows(rows)
    prefix = _namespace_prefix(namespace)
    id_map = {str(row["id"]): prefix + str(row["id"]) for row in rows}
    collisions = sorted(set(id_map.values()) & set(graph.joints))
    if collisions:
        raise ValueError(
            "The TC biped template is already present in this namespace: "
            + ", ".join(collisions[:5])
        )

    created = []
    for row in rows:
        source_id = str(row["id"])
        parent = id_map.get(str(row.get("parent") or ""), "")
        joint_id = graph.add_joint(
            id_map[source_id],
            parent_id=parent,
            joint_id=id_map[source_id],
            local_matrix=_translation_matrix(row.get("t") or (0.0, 0.0, 0.0)),
        )
        graph.nodes[joint_id].setdefault("attributes", {}).update({
            "rig_template": str(template.get("id") or "tc_biped"),
            "joint_role": str(row.get("slot") or row.get("face_slot") or "helper"),
            "display_radius": float(row.get("radius", 1.0) or 1.0),
        })
        created.append(joint_id)

    body_slots = {
        str(row["slot"]): id_map[str(row["id"])]
        for row in rows if row.get("slot")
    }
    face_slots = {
        str(row["face_slot"]): id_map[str(row["id"])]
        for row in rows if row.get("face_slot")
    }
    face_chains = {
        str(slot): [id_map[str(value)] for value in values]
        for slot, values in dict(template.get("face_chains") or {}).items()
    }
    root_ids = [id_map[str(row["id"])] for row in rows if not row.get("parent")]
    instance = {
        "template_id": str(template.get("id") or "tc_biped"),
        "template_name": str(template.get("name") or "TC Biped"),
        "template_path": str(template["source_path"]),
        "namespace": str(namespace or ""),
        "joint_ids": created,
        "root_joints": root_ids,
        "joint_map": body_slots,
        "face_slots": face_slots,
        "face_chains": face_chains,
        "new_node_count": len(created),
        "roll_joint_count": sum(1 for row in rows if "Roll" in str(row.get("slot") or "")),
        "finger_joint_count": sum(1 for row in rows if row.get("category") == "finger"),
        "coordinate_system": copy.deepcopy(template.get("coordinate_system") or {}),
    }
    graph.metadata.setdefault("rig_templates", []).append(copy.deepcopy(instance))
    return instance


def _expanded_joint_rows(template: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in template.get("joints") or []]
    profile = dict(template.get("finger_profile") or {})
    segments = int(profile.get("segments", 4) or 4)
    digits = [str(value) for value in profile.get("digits") or []]
    metacarpals = {str(value) for value in profile.get("metacarpals") or []}
    spread = dict(profile.get("spread_z") or {})
    for short_side, slot_side, sign in (("l", "Left", 1.0), ("r", "Right", -1.0)):
        hand = f"tc_{short_side}_hand"
        for digit in digits:
            parent = hand
            z = float(spread.get(digit, 0.0) or 0.0)
            if digit in metacarpals:
                metacarp = f"tc_{short_side}_inhand_{digit.lower()}"
                rows.append({
                    "id": metacarp,
                    "parent": hand,
                    "t": [sign * 3.0, -1.0, z],
                    "slot": f"{slot_side}InHand{digit}",
                    "radius": 0.7,
                    "category": "finger",
                })
                parent = metacarp
            for index in range(1, segments + 1):
                joint_id = f"tc_{short_side}_{digit.lower()}_{index:02d}"
                first_offset = [sign * (4.0 if digit == "Thumb" else 3.2), -2.0 if digit == "Thumb" else 0.0,
                                z if digit == "Thumb" else 0.0]
                rows.append({
                    "id": joint_id,
                    "parent": parent,
                    "t": first_offset if index == 1 else [sign * 3.0, 0.0, 0.0],
                    "slot": f"{slot_side}Hand{digit}{index}",
                    "radius": 0.6,
                    "category": "finger",
                })
                parent = joint_id
    return rows


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    ids = [str(row.get("id") or "") for row in rows]
    if any(not value for value in ids):
        raise ValueError("Every TC template joint requires an id.")
    if len(ids) != len(set(ids)):
        raise ValueError("A TC rig template contains duplicate joint ids.")
    known = set(ids)
    seen = set()
    for row in rows:
        parent = str(row.get("parent") or "")
        if parent and parent not in known:
            raise ValueError(f"Unknown template parent: {parent}")
        if parent and parent not in seen:
            raise ValueError(f"Template parent must appear before its child: {parent}")
        translation = row.get("t") or []
        if not isinstance(translation, (list, tuple)) or len(translation) != 3:
            raise ValueError(f"Template joint {row['id']} requires a three-value translation.")
        seen.add(str(row["id"]))


def _translation_matrix(values) -> list[float]:
    matrix = list(IDENTITY_MATRIX)
    matrix[12:15] = [float(value) for value in values]
    return matrix


def _namespace_prefix(namespace: str) -> str:
    value = str(namespace or "").strip().strip(":")
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not cleaned:
        raise ValueError("The TC template namespace contains no usable characters.")
    return cleaned + ":"


__all__ = [
    "DEFAULT_TC_BIPED_TEMPLATE",
    "TC_RIG_TEMPLATE_SCHEMA",
    "expanded_tc_rig_template_joints",
    "instantiate_tc_rig_template",
    "load_tc_rig_template",
]

