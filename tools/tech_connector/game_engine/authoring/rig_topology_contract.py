"""Provider-neutral, editable rig hierarchy and dependency graph contracts."""

from __future__ import annotations

import hashlib
from typing import Any


RIG_TOPOLOGY_SCHEMA = "tech_connector.rig_topology.v1"


def stable_connection_id(
    source_node: str,
    source_attribute: str,
    target_node: str,
    target_attribute: str,
) -> str:
    payload = "\0".join((source_node, source_attribute, target_node, target_attribute))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def normalize_rig_topology(packet: dict[str, Any], provider_id: str = "") -> dict[str, Any]:
    """Normalize a DCC rig packet while preserving provider-specific node data."""
    if not isinstance(packet, dict):
        raise TypeError("A rig topology packet must be a dictionary.")
    normalized = dict(packet)
    source_schema = str(normalized.get("schema") or "")
    if source_schema and source_schema != RIG_TOPOLOGY_SCHEMA:
        normalized["source_schema"] = source_schema
    normalized["schema"] = RIG_TOPOLOGY_SCHEMA
    normalized["provider_id"] = str(provider_id or normalized.get("provider_id") or "").strip().lower()

    nodes: list[dict[str, Any]] = []
    for source in normalized.get("nodes") or []:
        if not isinstance(source, dict):
            continue
        node = dict(source)
        node["native_id"] = str(node.get("native_id") or "")
        node["name"] = str(node.get("name") or node["native_id"].split("|")[-1])
        node["node_type"] = str(node.get("node_type") or "source.opaque")
        node["source_type"] = str(node.get("source_type") or "unknown")
        node["dag_parent_native_id"] = str(node.get("dag_parent_native_id") or "")
        node["source_order"] = int(node.get("source_order", 0) or 0)
        node["attributes"] = dict(node.get("attributes") or {})
        node["portable"] = bool(node.get("portable", False))
        node["evaluation_mode"] = str(node.get("evaluation_mode") or "source_proxy")
        nodes.append(node)
    normalized["nodes"] = nodes

    connections: list[dict[str, Any]] = []
    for source in normalized.get("connections") or []:
        if not isinstance(source, dict):
            continue
        connection = dict(source)
        source_node = str(connection.get("source_node") or "")
        source_attribute = str(connection.get("source_attribute") or "")
        target_node = str(connection.get("target_node") or "")
        target_attribute = str(connection.get("target_attribute") or "")
        connection.update({
            "id": str(connection.get("id") or stable_connection_id(
                source_node, source_attribute, target_node, target_attribute
            )),
            "source_node": source_node,
            "source_attribute": source_attribute,
            "target_node": target_node,
            "target_attribute": target_attribute,
            "connection_type": str(connection.get("connection_type") or "attribute"),
        })
        connections.append(connection)
    normalized["connections"] = connections
    normalized["constraints"] = [dict(item) for item in normalized.get("constraints") or [] if isinstance(item, dict)]
    normalized["contract_errors"] = validate_rig_topology(normalized)
    order, cyclic = dependency_evaluation_order(normalized)
    normalized["evaluation_order"] = order
    normalized["cyclic_node_ids"] = cyclic
    return normalized


def validate_rig_topology(packet: dict[str, Any]) -> list[str]:
    """Return bounded structural errors without rejecting valid DCC feedback graphs."""
    errors: list[str] = []
    if str(packet.get("schema") or "") != RIG_TOPOLOGY_SCHEMA:
        errors.append("unsupported schema")
    if not str(packet.get("provider_id") or ""):
        errors.append("provider_id is required")

    node_ids: set[str] = set()
    nodes_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(packet.get("nodes") or []):
        if not isinstance(node, dict):
            errors.append(f"node[{index}] is not a dictionary")
            continue
        native_id = str(node.get("native_id") or "")
        if not native_id:
            errors.append(f"node[{index}] has no native_id")
        elif native_id in node_ids:
            errors.append(f"duplicate node {native_id}")
        else:
            node_ids.add(native_id)
            nodes_by_id[native_id] = node

    for native_id, node in nodes_by_id.items():
        parent_id = str(node.get("dag_parent_native_id") or "")
        if parent_id and parent_id not in node_ids:
            errors.append(f"{native_id}: missing DAG parent {parent_id}")
        seen = {native_id}
        cursor = parent_id
        while cursor:
            if cursor in seen:
                errors.append(f"{native_id}: cyclic DAG hierarchy")
                break
            seen.add(cursor)
            cursor = str(nodes_by_id.get(cursor, {}).get("dag_parent_native_id") or "")

    connection_ids: set[str] = set()
    for index, connection in enumerate(packet.get("connections") or []):
        if not isinstance(connection, dict):
            errors.append(f"connection[{index}] is not a dictionary")
            continue
        connection_id = str(connection.get("id") or "")
        source_node = str(connection.get("source_node") or "")
        target_node = str(connection.get("target_node") or "")
        if connection_id and connection_id in connection_ids:
            errors.append(f"duplicate connection {connection_id}")
        connection_ids.add(connection_id)
        if source_node not in node_ids:
            errors.append(f"connection[{index}] has unknown source {source_node}")
        if target_node not in node_ids:
            errors.append(f"connection[{index}] has unknown target {target_node}")
        if not str(connection.get("source_attribute") or ""):
            errors.append(f"connection[{index}] has no source attribute")
        if not str(connection.get("target_attribute") or ""):
            errors.append(f"connection[{index}] has no target attribute")
        if len(errors) >= 32:
            errors.append("additional contract errors omitted")
            break
    return errors


def dependency_evaluation_order(packet: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Topologically order the acyclic portion and report feedback-cycle nodes."""
    node_ids = [
        str(node.get("native_id") or "")
        for node in packet.get("nodes") or []
        if isinstance(node, dict) and str(node.get("native_id") or "")
    ]
    indegree = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for connection in packet.get("connections") or []:
        if not isinstance(connection, dict):
            continue
        source = str(connection.get("source_node") or "")
        target = str(connection.get("target_node") or "")
        source_attribute = str(connection.get("source_attribute") or "")
        target_attribute = str(connection.get("target_attribute") or "")
        if source_attribute == "message" or target_attribute == "message":
            continue
        if source == target or source not in indegree or target not in indegree:
            continue
        if target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    queue = [node_id for node_id in node_ids if indegree[node_id] == 0]
    order: list[str] = []
    for node_id in queue:
        order.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    cyclic = [node_id for node_id in node_ids if indegree[node_id] > 0]
    return order, cyclic
