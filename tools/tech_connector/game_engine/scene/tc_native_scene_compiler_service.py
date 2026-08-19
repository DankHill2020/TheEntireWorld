"""Compile provider-neutral graph packets into authoritative TC-native identities."""

from __future__ import annotations

import hashlib
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph


_NODE_CLASS_MAP = {
    "dag.transform": "tc.scene.transform",
    "dag.joint": "tc.rig.joint",
    "dag.control": "tc.rig.control",
    "control.curve": "tc.rig.control_shape",
    "dag.mesh": "tc.geometry.mesh",
    "geometry.mesh": "tc.geometry.mesh",
    "geometry.nurbs_surface": "tc.geometry.surface",
    "animation.curve": "tc.function.curve",
    "utility.pose_reader": "tc.rig.pose_reader",
    "deformer.skin": "tc.deform.skin",
    "source.opaque": "tc.extension.source_proxy",
}


def stable_tc_id(kind: str, provider: str, source_id: str) -> str:
    """Return a stable TC identity without exposing a provider path as runtime identity."""
    source = f"{str(provider).lower()}\0{source_id}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(source).hexdigest()[:24]
    return f"tc.{str(kind).strip().lower()}.{digest}"


def tc_node_class(contract_node_type: str) -> str:
    contract = str(contract_node_type or "source.opaque")
    if contract in _NODE_CLASS_MAP:
        return _NODE_CLASS_MAP[contract]
    if contract.startswith("constraint."):
        return "tc.rig." + contract
    if contract.startswith("solver."):
        return "tc.rig." + contract
    if contract.startswith("math.") or contract.startswith("matrix.") or contract.startswith("logic."):
        return "tc.compute." + contract
    return "tc.extension.source_proxy"


def compile_graph_to_tc_native(graph: EditableRigGraph, provider: str) -> dict[str, Any]:
    """Replace source-scoped executable IDs while preserving lossless provenance."""
    provider = str(provider or "source").strip().lower().split(":", 1)[0]
    node_ids = {old: stable_tc_id("node", provider, _source_identity(item, old)) for old, item in graph.nodes.items()}
    joint_ids = {old: node_ids.get(old, stable_tc_id("node", provider, _source_identity(item, old))) for old, item in graph.joints.items()}
    connection_ids = {
        old: stable_tc_id("connection", provider, _source_identity(item, old))
        for old, item in graph.connections.items()
    }
    skin_ids = {old: stable_tc_id("skin", provider, _source_identity(item, old)) for old, item in graph.skins.items()}
    constraint_ids = {
        old: node_ids.get(old, stable_tc_id("constraint", provider, _source_identity(item, old)))
        for old, item in graph.constraints.items()
    }
    deformer_ids = {
        old: node_ids.get(old, stable_tc_id("deformer", provider, _source_identity(item, old)))
        for old, item in graph.deformers.items()
    }

    remapped_nodes: dict[str, dict[str, Any]] = {}
    for old_id, source in graph.nodes.items():
        item = dict(source)
        new_id = node_ids[old_id]
        contract_type = str(item.get("contract_node_type") or item.get("node_type") or "source.opaque")
        source_ref = dict(item.get("source_ref") or {})
        source_ref.setdefault("provider_id", provider)
        source_ref.setdefault("native_id", str(item.get("native_id") or old_id))
        item.update({
            "id": new_id,
            "native_id": new_id,
            "node_type": tc_node_class(contract_type),
            "contract_node_type": contract_type,
            "dag_parent_id": node_ids.get(str(item.get("dag_parent_id") or ""), ""),
            "source_ref": source_ref,
        })
        remapped_nodes[new_id] = item

    remapped_connections: dict[str, dict[str, Any]] = {}
    for old_id, source in graph.connections.items():
        item = dict(source)
        new_id = connection_ids[old_id]
        item.update({
            "id": new_id,
            "source_node": node_ids.get(str(item.get("source_node") or ""), str(item.get("source_node") or "")),
            "target_node": node_ids.get(str(item.get("target_node") or ""), str(item.get("target_node") or "")),
            "source_ref": _provenance(item, provider, old_id),
        })
        remapped_connections[new_id] = item

    remapped_joints: dict[str, dict[str, Any]] = {}
    for old_id, source in graph.joints.items():
        item = dict(source)
        new_id = joint_ids[old_id]
        item.update({
            "id": new_id,
            "parent_id": joint_ids.get(str(item.get("parent_id") or ""), ""),
            "source_ref": _provenance(item, provider, old_id),
        })
        remapped_joints[new_id] = item

    remapped_skins: dict[str, dict[str, Any]] = {}
    for old_id, source in graph.skins.items():
        item = dict(source)
        new_id = skin_ids[old_id]
        item.update({
            "id": new_id,
            "mesh_id": node_ids.get(str(item.get("mesh_id") or ""), str(item.get("mesh_id") or "")),
            "joint_ids": [joint_ids.get(str(value), str(value)) for value in item.get("joint_ids") or []],
            "source_ref": _provenance(item, provider, old_id),
        })
        overrides = item.get("weight_overrides")
        if isinstance(overrides, dict):
            item["weight_overrides"] = {
                str(vertex): {joint_ids.get(str(joint), str(joint)): weight for joint, weight in weights.items()}
                for vertex, weights in overrides.items() if isinstance(weights, dict)
            }
        if isinstance(item.get("fleshy"), dict):
            fleshy = dict(item["fleshy"])
            old_deformer = str(fleshy.get("deformer_id") or "")
            fleshy["deformer_id"] = deformer_ids.get(old_deformer, old_deformer)
            item["fleshy"] = fleshy
        deformation_ids = {**node_ids, **skin_ids, **deformer_ids}
        if isinstance(item.get("secondary_motion"), list):
            item["secondary_motion"] = _remap_nested_ids(item["secondary_motion"], deformation_ids)
        if isinstance(item.get("secondary_motion_presets"), list):
            item["secondary_motion_presets"] = _remap_nested_ids(
                item["secondary_motion_presets"], deformation_ids
            )
        remapped_skins[new_id] = item

    remapped_constraints: dict[str, dict[str, Any]] = {}
    for old_id, source in graph.constraints.items():
        item = dict(source)
        new_id = constraint_ids[old_id]
        item.update({
            "id": new_id,
            "source_ids": [node_ids.get(str(value), str(value)) for value in item.get("source_ids") or []],
            "target_id": node_ids.get(str(item.get("target_id") or ""), str(item.get("target_id") or "")),
            "settings": _remap_nested_ids(item.get("settings"), node_ids),
            "source_ref": _provenance(item, provider, old_id),
        })
        remapped_constraints[new_id] = item

    remapped_deformers: dict[str, dict[str, Any]] = {}
    deformation_ids = {**node_ids, **skin_ids, **deformer_ids}
    for old_id, source in graph.deformers.items():
        item = _remap_nested_ids(dict(source), deformation_ids)
        new_id = deformer_ids[old_id]
        item.update({"id": new_id, "source_ref": _provenance(source, provider, old_id)})
        remapped_deformers[new_id] = item

    graph.nodes = remapped_nodes
    graph.connections = remapped_connections
    graph.joints = remapped_joints
    graph.skins = remapped_skins
    graph.constraints = remapped_constraints
    graph.deformers = remapped_deformers
    _remap_animation(graph.animation, node_ids, provider)

    receipt = {
        "schema": "tech_connector.native_conversion_receipt.v1",
        "source_provider": provider,
        "node_ids": node_ids,
        "connection_ids": connection_ids,
        "joint_ids": joint_ids,
        "skin_ids": skin_ids,
        "constraint_ids": constraint_ids,
        "deformer_ids": deformer_ids,
    }
    graph.metadata["native_conversion_receipt"] = receipt
    graph.metadata["identity_authority"] = "tech_connector"
    return receipt


def _source_identity(item: dict[str, Any], fallback: str) -> str:
    source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), dict) else {}
    return str(source_ref.get("native_id") or item.get("native_id") or fallback)


def _provenance(item: dict[str, Any], provider: str, source_id: str) -> dict[str, Any]:
    source_ref = dict(item.get("source_ref") or {})
    source_ref.setdefault("provider_id", provider)
    source_ref.setdefault("native_id", _source_identity(item, source_id))
    return source_ref


def _remap_nested_ids(value: Any, node_ids: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [_remap_nested_ids(item, node_ids) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key.endswith("_id") and isinstance(item, str):
            result[key] = node_ids.get(item, item)
        elif key.endswith("_ids") and isinstance(item, list):
            result[key] = [node_ids.get(str(entry), str(entry)) for entry in item]
        else:
            result[key] = _remap_nested_ids(item, node_ids)
    return result


def _remap_animation(animation: dict[str, dict[str, Any]], node_ids: dict[str, str], provider: str) -> None:
    for take in animation.values():
        for layer in (take.get("layers") or {}).values():
            curves = layer.get("curves") if isinstance(layer, dict) else None
            if not isinstance(curves, dict):
                continue
            remapped: dict[str, dict[str, Any]] = {}
            for old_curve_id, curve in curves.items():
                item = dict(curve)
                old_node = str(item.get("node_id") or "")
                item["node_id"] = node_ids.get(old_node, old_node)
                item["source_ref"] = {"provider_id": provider, "native_id": str(item.get("source_curve") or old_curve_id)}
                attribute = str(item.get("attribute") or "")
                remapped[f"{item['node_id']}.{attribute}"] = item
            layer["curves"] = remapped

