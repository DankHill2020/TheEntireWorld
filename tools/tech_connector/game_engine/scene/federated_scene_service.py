"""Persistent multi-DCC scenes and an editable provider-neutral rig graph."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import copy
from pathlib import Path
from typing import Any
import uuid
import zipfile

from tech_connector.game_engine.authoring.rig_topology_contract import normalize_rig_topology, stable_connection_id


FEDERATED_SCENE_SCHEMA = "tech_connector.federated_scene.v1"
DCC_SESSION_STATE_SCHEMA = "tech_connector.dcc_session_state.v1"
RIG_GRAPH_SCHEMA = "tech_connector.editable_rig_graph.v1"
SUPPORTED_CONSTRAINTS = {
    "parent", "point", "orient", "rotate", "scale", "aim", "ik", "spine_stretch", "pole_vector",
    "geometry", "normal", "tangent", "motion_path", "ribbon", "opaque",
}
SUPPORTED_DEFORMERS = {
    "linear_blend_skinning", "dual_quaternion_skinning", "blend_shape", "cluster",
    "lattice", "wrap", "curve", "delta_mush", "nonlinear", "source_proxy",
    "muscle", "jiggle", "flesh",
}
IDENTITY_MATRIX = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _finite_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def normalize_dcc_session_state(
    state: dict[str, Any] | None,
    *,
    provider: str = "",
) -> dict[str, Any]:
    """Normalize portable per-source UI/timeline state without transient ports."""

    source = dict(state or {})
    provider_key = str(provider or source.get("provider") or "").strip().lower().split(":", 1)[0]
    timeline_source = source.get("timeline") if isinstance(source.get("timeline"), dict) else {}
    start = _finite_float(timeline_source.get("start"), 1.0)
    end = _finite_float(timeline_source.get("end"), start)
    if end < start:
        start, end = end, start
    current = min(end, max(start, _finite_float(timeline_source.get("current"), start)))
    fps = min(1000.0, max(0.001, _finite_float(timeline_source.get("fps"), 24.0)))
    camera_source = source.get("camera") if isinstance(source.get("camera"), dict) else {}
    selection = source.get("selection_native_ids") if isinstance(source.get("selection_native_ids"), list) else []
    return {
        "schema": DCC_SESSION_STATE_SCHEMA,
        "provider": provider_key,
        "camera": {
            "native_id": str(camera_source.get("native_id") or ""),
            "display_name": str(camera_source.get("display_name") or ""),
        },
        "timeline": {
            "current": current,
            "start": start,
            "end": end,
            "fps": fps,
            "time_unit": str(timeline_source.get("time_unit") or ""),
            "playing": False,
        },
        "selection_native_ids": list(dict.fromkeys(
            str(value) for value in selection[:4096] if str(value or "").strip()
        )),
        "scene_revision": source.get("scene_revision"),
        "scene_modified_at_capture": bool(source.get("scene_modified_at_capture", False)),
    }


def dcc_session_state_from_snapshot(
    snapshot: dict[str, Any] | None,
    *,
    provider: str = "",
) -> dict[str, Any]:
    """Extract portable camera/timeline state from a host scene snapshot."""

    source = dict(snapshot or {})
    provider_key = str(provider or source.get("provider_id") or "").strip().lower().split(":", 1)[0]
    camera_id = str(source.get("active_camera") or source.get("camera") or "")
    selection = source.get("selection") or source.get("selected") or []
    return normalize_dcc_session_state({
        "provider": provider_key,
        "camera": {"native_id": camera_id, "display_name": camera_id.split("|")[-1]},
        "timeline": {
            "current": source.get("current_time", source.get("frame", 1.0)),
            "start": source.get("frame_start", source.get("start", 1.0)),
            "end": source.get("frame_end", source.get("end", 1.0)),
            "fps": source.get("fps", 24.0),
            "time_unit": source.get("time_unit", ""),
        },
        "selection_native_ids": selection if isinstance(selection, list) else [],
        "scene_revision": source.get("scene_revision"),
        "scene_modified_at_capture": bool(source.get("scene_modified", False)),
    }, provider=provider_key)


def normalize_federated_scene_source(source: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional portable source state while accepting legacy manifests."""

    result = copy.deepcopy(source)
    provider = str(result.get("provider") or "").strip().lower().split(":", 1)[0]
    if isinstance(result.get("session_state"), dict):
        result["session_state"] = normalize_dcc_session_state(result["session_state"], provider=provider)
    if isinstance(result.get("lookdev_state"), dict):
        from tech_connector.game_engine.rendering.material_contract import normalize_portable_lookdev_state

        result["lookdev_state"] = normalize_portable_lookdev_state(
            result["lookdev_state"],
            source_provider=provider,
            source_path=str(result.get("source_path") or ""),
        ).to_dict()
    return result


def federated_scene_lookdev_report(document: "FederatedSceneDocument") -> dict[str, Any]:
    """Summarize saved lookdev evidence without treating absent legacy data as parity."""

    entries: list[dict[str, Any]] = []
    for source in document.sources:
        state = source.get("lookdev_state") if isinstance(source.get("lookdev_state"), dict) else None
        if state is None:
            continue
        parity = state.get("parity") if isinstance(state.get("parity"), dict) else {}
        entries.append({
            "source_id": str(source.get("source_id") or ""),
            "provider": str(source.get("provider") or ""),
            "status": str(parity.get("overall") or "unavailable"),
            "material_count": len(state.get("materials") or {}),
            "assignment_count": len(state.get("assignments") or []),
            "texture_asset_count": len(state.get("texture_assets") or {}),
            "limitations": list(parity.get("limitations") or []),
        })
    status_counts = {
        status: sum(1 for entry in entries if entry["status"] == status)
        for status in ("complete", "partial", "unavailable")
    }
    return {
        "schema": "tech_connector.lookdev_parity_report.v1",
        "source_count": len(entries),
        "status_counts": status_counts,
        "entries": entries,
    }


def _source_ownership(source_ref: dict[str, Any] | None) -> tuple[str, str]:
    provider = str((source_ref or {}).get("provider_id") or "").strip().lower().split(":", 1)[0]
    if provider and provider != "native_fbx":
        return "linked", "source_driven"
    return "native", "full"


@dataclass
class EditableRigGraph:
    """Authoritative editable DAG, dependency graph, deformation, and animation data."""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    connections: dict[str, dict[str, Any]] = field(default_factory=dict)
    joints: dict[str, dict[str, Any]] = field(default_factory=dict)
    skins: dict[str, dict[str, Any]] = field(default_factory=dict)
    constraints: dict[str, dict[str, Any]] = field(default_factory=dict)
    deformers: dict[str, dict[str, Any]] = field(default_factory=dict)
    animation: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(
        self,
        name: str,
        node_type: str,
        *,
        parent_id: str = "",
        attributes: dict[str, Any] | None = None,
        node_id: str | None = None,
        source_type: str = "",
        source_ref: dict[str, str] | None = None,
        portable: bool = True,
    ) -> str:
        """Create one native or linked rig node in the editable DAG/DG."""
        if parent_id and parent_id not in self.nodes:
            raise KeyError(f"Unknown parent rig node: {parent_id}")
        native_id = str(node_id or uuid.uuid4())
        if native_id in self.nodes:
            raise ValueError(f"Rig node already exists: {native_id}")
        ownership, edit_policy = _source_ownership(source_ref)
        sibling_order = 1 + max(
            (
                int(item.get("source_order", 0) or 0)
                for item in self.nodes.values()
                if str(item.get("dag_parent_id") or "") == str(parent_id or "")
            ),
            default=-1,
        )
        self.nodes[native_id] = {
            "id": native_id,
            "native_id": str((source_ref or {}).get("native_id") or native_id),
            "name": str(name or "Rig Node"),
            "node_type": str(node_type or "source.opaque"),
            "source_type": str(source_type or node_type or "unknown"),
            "dag_parent_id": str(parent_id or ""),
            "source_order": sibling_order,
            "attributes": dict(attributes or {}),
            "attribute_specs": {},
            "portable": bool(portable),
            "evaluation_mode": "local" if ownership == "native" else "source_proxy",
            "source_ref": dict(source_ref or {}),
            "ownership": ownership,
            "edit_policy": edit_policy,
        }
        return native_id

    def connect_attributes(
        self,
        source_node: str,
        source_attribute: str,
        target_node: str,
        target_attribute: str,
        *,
        connection_type: str = "attribute",
        connection_id: str | None = None,
    ) -> str:
        """Author a portable directed plug connection without evaluating it eagerly."""
        if source_node not in self.nodes:
            raise KeyError(f"Unknown source rig node: {source_node}")
        if target_node not in self.nodes:
            raise KeyError(f"Unknown target rig node: {target_node}")
        if not str(source_attribute or "") or not str(target_attribute or ""):
            raise ValueError("Source and target attributes are required.")
        native_id = str(connection_id or stable_connection_id(
            str(source_node), str(source_attribute), str(target_node), str(target_attribute)
        ))
        existing = self.connections.get(native_id)
        if existing:
            if (
                existing.get("source_node") == source_node
                and existing.get("source_attribute") == source_attribute
                and existing.get("target_node") == target_node
                and existing.get("target_attribute") == target_attribute
            ):
                return native_id
            raise ValueError(f"Rig connection already exists: {native_id}")
        self.connections[native_id] = {
            "id": native_id,
            "source_node": str(source_node),
            "source_attribute": str(source_attribute),
            "target_node": str(target_node),
            "target_attribute": str(target_attribute),
            "connection_type": str(connection_type or "attribute"),
            "ownership": "native",
            "edit_policy": "full",
        }
        return native_id

    def set_node_attribute(self, node_id: str, attribute: str, value: Any) -> None:
        """Set a native node input; linked nodes remain authoritative in their DCC."""
        node = self.nodes.get(str(node_id))
        if node is None:
            raise KeyError(f"Unknown rig node: {node_id}")
        if str(node.get("edit_policy") or "full") != "full":
            raise PermissionError("Linked DCC attributes must be edited through their source session.")
        attribute = str(attribute or "")
        if not attribute:
            raise ValueError("An attribute name is required.")
        node.setdefault("attributes", {})[attribute] = value

    def evaluate_direct_attribute_connections(self) -> list[str]:
        """Propagate portable attr-to-attr links and report cyclic local nodes."""
        local_nodes = {
            node_id: node
            for node_id, node in self.nodes.items()
            if str(node.get("evaluation_mode") or "local") == "local"
        }
        outgoing: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in local_nodes}
        indegree = {node_id: 0 for node_id in local_nodes}
        for connection in self.connections.values():
            if str(connection.get("connection_type") or "attribute") != "attribute":
                continue
            source_id = str(connection.get("source_node") or "")
            target_id = str(connection.get("target_node") or "")
            if source_id not in local_nodes or target_id not in local_nodes:
                continue
            outgoing[source_id].append(connection)
            indegree[target_id] += 1

        queue = [node_id for node_id in local_nodes if indegree[node_id] == 0]
        visited: set[str] = set()
        for source_id in queue:
            visited.add(source_id)
            source_attributes = local_nodes[source_id].setdefault("attributes", {})
            for connection in outgoing[source_id]:
                target_id = str(connection.get("target_node") or "")
                source_attribute = str(connection.get("source_attribute") or "")
                target_attribute = str(connection.get("target_attribute") or "")
                if source_attribute in source_attributes:
                    local_nodes[target_id].setdefault("attributes", {})[target_attribute] = source_attributes[source_attribute]
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    queue.append(target_id)
        return [node_id for node_id in local_nodes if node_id not in visited]

    def evaluate_local(self):
        """Evaluate native rig nodes locally while leaving linked source-proxy nodes authoritative."""
        from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph

        return evaluate_rig_graph(self)

    def disconnect_attributes(self, connection_id: str) -> None:
        if connection_id not in self.connections:
            raise KeyError(f"Unknown rig connection: {connection_id}")
        connection = self.connections[connection_id]
        if str(connection.get("edit_policy") or "full") != "full":
            raise PermissionError("Linked DCC connections must be edited in their source scene.")
        del self.connections[connection_id]

    def reparent_node(self, node_id: str, parent_id: str = "") -> None:
        if node_id not in self.nodes:
            raise KeyError(f"Unknown rig node: {node_id}")
        node = self.nodes[node_id]
        if str(node.get("edit_policy") or "full") != "full":
            raise PermissionError("Linked DCC hierarchy must be edited in its source scene.")
        if parent_id and parent_id not in self.nodes:
            raise KeyError(f"Unknown parent rig node: {parent_id}")
        cursor = str(parent_id or "")
        while cursor:
            if cursor == node_id:
                raise ValueError("A rig node cannot be parented beneath its descendant.")
            cursor = str(self.nodes.get(cursor, {}).get("dag_parent_id") or "")
        node["dag_parent_id"] = str(parent_id or "")

    def merge_rig_topology(
        self,
        topology: dict[str, Any],
        *,
        provider_id: str = "",
    ) -> None:
        """Merge an ordered provider DAG and its lossless plug-level rig graph."""
        provider = str(provider_id or topology.get("provider_id") or "").strip().lower()
        normalized = normalize_rig_topology(topology, provider_id=provider)
        if normalized.get("contract_errors"):
            raise ValueError("Invalid rig topology: " + "; ".join(normalized["contract_errors"][:8]))

        source_to_id = {
            str(node.get("native_id") or ""): f"{provider}::{str(node.get('native_id') or '')}"
            for node in normalized.get("nodes") or []
            if str(node.get("native_id") or "")
        }
        incoming_node_ids = set(source_to_id.values())
        incoming_connection_ids = {
            f"{provider}::{str(item.get('id') or '')}"
            for item in normalized.get("connections") or []
            if str(item.get("id") or "")
        }
        incoming_constraint_ids = {
            f"{provider}::{str(item.get('native_id') or item.get('id') or '')}"
            for item in normalized.get("constraints") or []
            if str(item.get("native_id") or item.get("id") or "")
        }
        for node_id, node in list(self.nodes.items()):
            source_ref = node.get("source_ref") if isinstance(node.get("source_ref"), dict) else {}
            if str(source_ref.get("provider_id") or "").lower() == provider and node_id not in incoming_node_ids:
                del self.nodes[node_id]
        for connection_id, connection in list(self.connections.items()):
            source_ref = connection.get("source_ref") if isinstance(connection.get("source_ref"), dict) else {}
            if (
                str(source_ref.get("provider_id") or "").lower() == provider
                and connection_id not in incoming_connection_ids
            ):
                del self.connections[connection_id]
        for constraint_id, constraint in list(self.constraints.items()):
            source_ref = constraint.get("source_ref") if isinstance(constraint.get("source_ref"), dict) else {}
            if (
                str(source_ref.get("provider_id") or "").lower() == provider
                and constraint_id not in incoming_constraint_ids
            ):
                del self.constraints[constraint_id]
        for source in normalized.get("nodes") or []:
            native_id = str(source.get("native_id") or "")
            node_id = source_to_id[native_id]
            source_parent = str(source.get("dag_parent_native_id") or "")
            ownership, edit_policy = _source_ownership({"provider_id": provider, "native_id": native_id})
            self.nodes[node_id] = {
                **dict(source),
                "id": node_id,
                "dag_parent_id": source_to_id.get(source_parent, ""),
                "source_ref": {"provider_id": provider, "native_id": native_id},
                "ownership": ownership,
                "edit_policy": edit_policy,
            }

        for source in normalized.get("connections") or []:
            source_node = source_to_id.get(str(source.get("source_node") or ""), "")
            target_node = source_to_id.get(str(source.get("target_node") or ""), "")
            if not source_node or not target_node:
                continue
            connection_id = f"{provider}::{str(source.get('id') or '')}"
            self.connections[connection_id] = {
                **dict(source),
                "id": connection_id,
                "source_node": source_node,
                "target_node": target_node,
                "source_ref": {"provider_id": provider, "native_id": str(source.get("id") or "")},
                "ownership": "linked",
                "edit_policy": "source_driven",
            }

        for source in normalized.get("constraints") or []:
            native_id = str(source.get("native_id") or source.get("id") or "")
            if not native_id:
                continue
            constraint_id = f"{provider}::{native_id}"
            target_ids = [
                source_to_id.get(str(item.get("native_id") or ""), "")
                for item in source.get("targets") or []
                if isinstance(item, dict)
            ]
            driven_id = source_to_id.get(str(source.get("driven_native_id") or ""), "")
            self.constraints[constraint_id] = {
                **dict(source),
                "id": constraint_id,
                "source_ids": [item for item in target_ids if item],
                "target_id": driven_id,
                "source_ref": {"provider_id": provider, "native_id": native_id},
                "ownership": "linked",
                "edit_policy": "source_driven",
                "enabled": bool(source.get("enabled", True)),
            }

        cyclic_sources = set(normalized.get("cyclic_node_ids") or [])
        for native_id in cyclic_sources:
            node = self.nodes.get(source_to_id.get(str(native_id), ""))
            if node is not None:
                node["evaluation_mode"] = "source_proxy"
                node["evaluation_note"] = "Dependency feedback cycle is evaluated by the source DCC."

        for joint in self.joints.values():
            source_ref = joint.get("source_ref") if isinstance(joint.get("source_ref"), dict) else {}
            if str(source_ref.get("provider_id") or "").lower() != provider:
                continue
            source_node = self.nodes.get(source_to_id.get(str(source_ref.get("native_id") or ""), ""), {})
            if source_node:
                joint["source_order"] = int(source_node.get("source_order", 0) or 0)

    def add_joint(
        self,
        name: str,
        *,
        parent_id: str = "",
        local_matrix: list[float] | tuple[float, ...] | None = None,
        joint_id: str | None = None,
        source_ref: dict[str, str] | None = None,
    ) -> str:
        if parent_id and parent_id not in self.joints:
            raise KeyError(f"Unknown parent joint: {parent_id}")
        matrix = [float(value) for value in (local_matrix or IDENTITY_MATRIX)]
        if len(matrix) != 16:
            raise ValueError("A joint local matrix must contain 16 values.")
        native_id = str(joint_id or uuid.uuid4())
        if native_id in self.joints:
            raise ValueError(f"Joint already exists: {native_id}")
        ownership, edit_policy = _source_ownership(source_ref)
        self.joints[native_id] = {
            "id": native_id,
            "name": str(name or "Joint"),
            "parent_id": str(parent_id or ""),
            "local_matrix": matrix,
            "source_ref": dict(source_ref or {}),
            "ownership": ownership,
            "edit_policy": edit_policy,
        }
        if native_id not in self.nodes:
            self.add_node(
                str(name or "Joint"),
                "dag.joint",
                parent_id=parent_id if parent_id in self.nodes else "",
                attributes={"matrix": matrix},
                node_id=native_id,
                source_type="joint",
                source_ref=source_ref,
            )
        return native_id

    def joint_edit_policy(self, joint_id: str) -> str:
        joint = self.joints.get(str(joint_id))
        if joint is None:
            raise KeyError(f"Unknown joint: {joint_id}")
        explicit = str(joint.get("edit_policy") or "").strip().lower()
        return explicit or _source_ownership(joint.get("source_ref"))[1]

    def joint_is_structurally_editable(self, joint_id: str) -> bool:
        return self.joint_edit_policy(joint_id) == "full"

    def _require_structurally_editable_joint(self, joint_id: str) -> None:
        if not self.joint_is_structurally_editable(joint_id):
            raise PermissionError(
                "This joint is driven by a linked DCC scene. Edit its hierarchy in the source DCC, "
                "or create a native Tech Connector joint/constraint override."
            )

    def reparent_joint(self, joint_id: str, parent_id: str = "") -> None:
        if joint_id not in self.joints:
            raise KeyError(f"Unknown joint: {joint_id}")
        self._require_structurally_editable_joint(joint_id)
        if parent_id and parent_id not in self.joints:
            raise KeyError(f"Unknown parent joint: {parent_id}")
        cursor = str(parent_id or "")
        while cursor:
            if cursor == joint_id:
                raise ValueError("A joint cannot be parented beneath its descendant.")
            cursor = str(self.joints.get(cursor, {}).get("parent_id") or "")
        self.joints[joint_id]["parent_id"] = str(parent_id or "")
        if joint_id in self.nodes:
            self.nodes[joint_id]["dag_parent_id"] = str(parent_id or "")

    def remove_joint(self, joint_id: str) -> None:
        if joint_id not in self.joints:
            raise KeyError(f"Unknown joint: {joint_id}")
        self._require_structurally_editable_joint(joint_id)
        children = [key for key, item in self.joints.items() if str(item.get("parent_id") or "") == joint_id]
        if children:
            raise ValueError("Reparent or remove this joint's children first.")
        affected_skins = [skin_id for skin_id, skin in self.skins.items() if joint_id in (skin.get("joint_ids") or [])]
        if affected_skins:
            raise ValueError("Remove the joint from its skin influences before deleting it.")
        affected_connections = [
            connection_id for connection_id, connection in self.connections.items()
            if joint_id in {str(connection.get("source_node") or ""), str(connection.get("target_node") or "")}
        ]
        if affected_connections:
            raise ValueError("Disconnect this joint from the dependency graph before deleting it.")
        del self.joints[joint_id]
        self.nodes.pop(joint_id, None)

    def add_skin(
        self,
        mesh_id: str,
        joint_ids: list[str] | tuple[str, ...],
        *,
        skin_id: str | None = None,
        inverse_bind_blob: str = "",
        weights_blob: str = "",
        source_ref: dict[str, str] | None = None,
    ) -> str:
        missing = [joint_id for joint_id in joint_ids if joint_id not in self.joints]
        if missing:
            raise KeyError("Unknown skin joints: " + ", ".join(missing[:8]))
        native_id = str(skin_id or uuid.uuid4())
        if native_id in self.skins:
            raise ValueError(f"Skin already exists: {native_id}")
        ownership, edit_policy = _source_ownership(source_ref)
        self.skins[native_id] = {
            "id": native_id,
            "mesh_id": str(mesh_id or ""),
            "joint_ids": [str(value) for value in joint_ids],
            "inverse_bind_blob": str(inverse_bind_blob or ""),
            "weights_blob": str(weights_blob or ""),
            "weight_overrides": {},
            "source_ref": dict(source_ref or {}),
            "ownership": ownership,
            "edit_policy": edit_policy,
        }
        return native_id

    def set_vertex_weights(self, skin_id: str, vertex_index: int, weights: dict[str, float]) -> None:
        skin = self.skins.get(str(skin_id))
        if skin is None:
            raise KeyError(f"Unknown skin: {skin_id}")
        if int(vertex_index) < 0:
            raise ValueError("A skin vertex index cannot be negative.")
        allowed = set(skin.get("joint_ids") or [])
        cleaned = {str(joint): float(value) for joint, value in weights.items() if float(value) > 0.0}
        unknown = set(cleaned) - allowed
        if unknown:
            raise KeyError("Weights reference unknown skin joints: " + ", ".join(sorted(unknown)[:8]))
        total = sum(cleaned.values())
        if total <= 0.0:
            raise ValueError("At least one positive skin weight is required.")
        skin.setdefault("weight_overrides", {})[str(int(vertex_index))] = {
            joint: value / total for joint, value in cleaned.items()
        }

    def add_constraint(
        self,
        constraint_type: str,
        source_ids: list[str] | tuple[str, ...],
        target_id: str,
        *,
        constraint_id: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        kind = str(constraint_type or "").strip().lower()
        if kind not in SUPPORTED_CONSTRAINTS:
            raise ValueError(f"Unsupported rig constraint: {kind}")
        native_id = str(constraint_id or uuid.uuid4())
        self.constraints[native_id] = {
            "id": native_id,
            "type": kind,
            "source_ids": [str(value) for value in source_ids],
            "target_id": str(target_id or ""),
            "settings": dict(settings or {}),
            "enabled": True,
        }
        return native_id

    def add_ik_solver(
        self,
        start_joint_id: str,
        mid_joint_id: str,
        end_joint_id: str,
        target_node_id: str,
        *,
        pole_node_id: str = "",
        solver_id: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        """Author a native two-bone rotate-plane IK solver in the neutral rig graph."""
        joint_ids = [str(start_joint_id), str(mid_joint_id), str(end_joint_id)]
        missing_joints = [joint_id for joint_id in joint_ids if joint_id not in self.joints]
        if missing_joints:
            raise KeyError("Unknown IK joints: " + ", ".join(missing_joints))
        if str(self.joints[mid_joint_id].get("parent_id") or "") != str(start_joint_id):
            raise ValueError("The IK mid joint must be parented directly beneath the start joint.")
        if str(self.joints[end_joint_id].get("parent_id") or "") != str(mid_joint_id):
            raise ValueError("The IK end joint must be parented directly beneath the mid joint.")
        for node_id in [str(target_node_id), str(pole_node_id or "")]:
            if node_id and node_id not in self.nodes:
                raise KeyError(f"Unknown IK control node: {node_id}")
        native_id = str(solver_id or uuid.uuid4())
        solver_settings = {
            "start_joint_id": str(start_joint_id),
            "mid_joint_id": str(mid_joint_id),
            "end_joint_id": str(end_joint_id),
            "target_node_id": str(target_node_id),
            "pole_node_id": str(pole_node_id or ""),
            **dict(settings or {}),
        }
        self.add_node(
            "Rotate Plane IK",
            "solver.ik_rotate_plane",
            node_id=native_id,
            attributes=solver_settings,
            source_type="ikRotatePlane",
        )
        self.constraints[native_id] = {
            "id": native_id,
            "type": "ik",
            "source_ids": [str(target_node_id)] + ([str(pole_node_id)] if pole_node_id else []),
            "target_id": str(end_joint_id),
            "settings": solver_settings,
            "enabled": True,
            "ownership": "native",
            "edit_policy": "full",
        }
        return native_id

    def add_motion_path(
        self,
        target_node_id: str,
        control_points: list[list[float]] | tuple[tuple[float, ...], ...],
        *,
        parameter: float = 0.0,
        follow: bool = True,
        closed: bool = False,
        up_vector: tuple[float, float, float] = (0.0, 1.0, 0.0),
        solver_id: str | None = None,
    ) -> str:
        """Author a portable arc-length motion path for one native transform."""
        if target_node_id not in self.nodes:
            raise KeyError(f"Unknown motion-path target node: {target_node_id}")
        points = [[float(value) for value in point[:3]] for point in control_points]
        if len(points) < 2 or any(len(point) != 3 for point in points):
            raise ValueError("A motion path requires at least two 3D control points.")
        native_id = str(solver_id or uuid.uuid4())
        settings = {
            "target_node_id": str(target_node_id),
            "control_points": points,
            "parameter": float(parameter),
            "follow": bool(follow),
            "closed": bool(closed),
            "up_vector": [float(value) for value in up_vector[:3]],
            "interpolation": "arc_length_linear",
        }
        self.add_node(
            "Motion Path",
            "solver.motion_path",
            node_id=native_id,
            attributes=settings,
            source_type="motionPath",
        )
        self.constraints[native_id] = {
            "id": native_id,
            "type": "motion_path",
            "source_ids": [],
            "target_id": str(target_node_id),
            "settings": settings,
            "enabled": True,
            "ownership": "native",
            "edit_policy": "full",
        }
        return native_id

    def add_ribbon_attachment(
        self,
        target_node_id: str,
        control_grid: list[list[list[float]]],
        *,
        u: float = 0.5,
        v: float = 0.5,
        follow: bool = True,
        frame_method: str = "surface",
        up_vector: tuple[float, float, float] = (0.0, 1.0, 0.0),
        solver_id: str | None = None,
    ) -> str:
        """Author a portable bilinear ribbon attachment with stable U/V coordinates."""
        if target_node_id not in self.nodes:
            raise KeyError(f"Unknown ribbon target node: {target_node_id}")
        grid = [
            [[float(value) for value in point[:3]] for point in row]
            for row in control_grid
        ]
        width = len(grid[0]) if grid else 0
        if len(grid) < 2 or width < 2 or any(len(row) != width for row in grid):
            raise ValueError("A ribbon requires a rectangular control grid of at least 2 by 2 points.")
        if any(len(point) != 3 for row in grid for point in row):
            raise ValueError("Every ribbon control point must contain three values.")
        native_id = str(solver_id or uuid.uuid4())
        settings = {
            "target_node_id": str(target_node_id),
            "control_grid": grid,
            "u": float(u),
            "v": float(v),
            "follow": bool(follow),
            "interpolation": "piecewise_bilinear",
            "frame_method": str(frame_method or "surface"),
            "up_vector": [float(value) for value in up_vector[:3]],
        }
        self.add_node(
            "Ribbon Attachment",
            "solver.ribbon_attachment",
            node_id=native_id,
            attributes=settings,
            source_type="ribbonAttachment",
        )
        self.constraints[native_id] = {
            "id": native_id,
            "type": "ribbon",
            "source_ids": [],
            "target_id": str(target_node_id),
            "settings": settings,
            "enabled": True,
            "ownership": "native",
            "edit_policy": "full",
        }
        return native_id

    def add_deformer(
        self,
        mesh_id: str,
        deformer_type: str,
        *,
        settings: dict[str, Any] | None = None,
        deformer_id: str | None = None,
        source_ref: dict[str, str] | None = None,
    ) -> str:
        """Append one ordered deformer without claiming local parity for unsupported types."""
        kind = str(deformer_type or "").strip().lower()
        if kind not in SUPPORTED_DEFORMERS:
            raise ValueError(f"Unsupported deformer type: {deformer_type}")
        native_id = str(deformer_id or uuid.uuid4())
        if native_id in self.deformers:
            raise ValueError(f"Deformer already exists: {native_id}")
        ownership, edit_policy = _source_ownership(source_ref)
        order = 1 + max(
            (
                int(item.get("order", -1)) if item.get("order") is not None else -1
                for item in self.deformers.values()
                if str(item.get("mesh_id") or "") == str(mesh_id)
            ),
            default=-1,
        )
        self.deformers[native_id] = {
            "id": native_id,
            "mesh_id": str(mesh_id or ""),
            "type": kind,
            "order": order,
            "settings": dict(settings or {}),
            "enabled": True,
            "source_ref": dict(source_ref or {}),
            "ownership": ownership,
            "edit_policy": edit_policy,
            "evaluation_mode": (
                "gpu_local" if ownership == "native" and kind == "linear_blend_skinning"
                else "runtime_local" if ownership == "native" and kind in {"blend_shape", "muscle", "jiggle", "flesh"}
                else "source_proxy"
            ),
        }
        return native_id

    def merge_deformation_binding(
        self,
        binding: dict[str, Any],
        *,
        provider_id: str = "",
    ) -> dict[str, bytes]:
        """Import a linked DCC skin as editable joints and versioned binary sidecars."""
        provider = str(provider_id or binding.get("provider_id") or "").strip().lower()
        blobs: dict[str, bytes] = {}
        for skeleton in binding.get("skeletons") or []:
            skeleton_native_id = str(skeleton.get("native_id") or "")
            joints = list(skeleton.get("joints") or [])
            inverse_buffer = skeleton.get("inverse_bind_matrices_f32")
            inverse_offset = int(skeleton.get("inverse_bind_float_offset", 0) or 0)
            inverse_count = len(joints) * 16
            token = hashlib.sha1(f"{provider}:{skeleton_native_id}".encode("utf-8")).hexdigest()[:16]
            inverse_blob = f"rig/{token}/inverse_bind.f32"
            if inverse_buffer is not None and inverse_count:
                blobs[inverse_blob] = _buffer_bytes(inverse_buffer, inverse_offset, inverse_count, 4)
            source_to_joint_id = {
                str(item.get("native_id") or ""): f"{provider}::{str(item.get('native_id') or '')}"
                for item in joints
                if str(item.get("native_id") or "")
            }
            bind_world_matrices = _bind_world_matrices(inverse_buffer, inverse_offset, len(joints))
            for index, item in enumerate(joints):
                source_joint_id = str(item.get("native_id") or "")
                if not source_joint_id:
                    continue
                joint_id = source_to_joint_id[source_joint_id]
                parent_id = source_to_joint_id.get(str(item.get("parent_native_id") or ""), "")
                local_matrix = _local_bind_matrix(bind_world_matrices, index, joints, source_to_joint_id)
                if joint_id in self.joints:
                    self.joints[joint_id].update({
                        "name": str(item.get("name") or source_joint_id.split("|")[-1]),
                        "parent_id": parent_id,
                        "local_matrix": local_matrix,
                        "bind_world_matrix": bind_world_matrices[index] if index < len(bind_world_matrices) else IDENTITY_MATRIX[:],
                        "source_ref": {"provider_id": provider, "native_id": source_joint_id},
                        "ownership": "linked",
                        "edit_policy": "source_driven",
                    })
                else:
                    self.add_joint(
                        str(item.get("name") or source_joint_id.split("|")[-1]),
                        parent_id=parent_id if parent_id in self.joints else "",
                        local_matrix=local_matrix,
                        joint_id=joint_id,
                        source_ref={"provider_id": provider, "native_id": source_joint_id},
                    )
                    self.joints[joint_id]["bind_world_matrix"] = (
                        bind_world_matrices[index] if index < len(bind_world_matrices) else IDENTITY_MATRIX[:]
                    )
            for item in joints:
                source_joint_id = str(item.get("native_id") or "")
                joint_id = source_to_joint_id.get(source_joint_id, "")
                parent_id = source_to_joint_id.get(str(item.get("parent_native_id") or ""), "")
                if joint_id in self.joints:
                    self.joints[joint_id]["parent_id"] = parent_id
                    if joint_id in self.nodes:
                        self.nodes[joint_id]["dag_parent_id"] = parent_id

            joint_ids = [
                source_to_joint_id[str(item.get("native_id") or "")]
                for item in joints
                if str(item.get("native_id") or "") in source_to_joint_id
            ]
            for mesh in binding.get("meshes") or []:
                if str(mesh.get("skeleton_id") or "") != skeleton_native_id:
                    continue
                mesh_native_id = str(mesh.get("native_id") or "")
                mesh_token = hashlib.sha1(f"{provider}:{mesh_native_id}".encode("utf-8")).hexdigest()[:16]
                rest_blob = f"rig/{mesh_token}/rest_positions.f32"
                offsets_blob = f"rig/{mesh_token}/influence_offsets.u32"
                indices_blob = f"rig/{mesh_token}/joint_indices.u32"
                weights_blob = f"rig/{mesh_token}/weights.f32"
                vertex_count = int(mesh.get("vertex_count", 0) or 0)
                influence_count = int(mesh.get("sparse_influence_count", 0) or 0)
                blobs[rest_blob] = _buffer_bytes(
                    mesh.get("bind_vertices_f32"),
                    int(mesh.get("bind_vertex_float_offset", 0) or 0),
                    vertex_count * 3,
                    4,
                )
                blobs[offsets_blob] = _buffer_bytes(
                    mesh.get("influence_offsets_u32"),
                    int(mesh.get("influence_offset_offset", 0) or 0),
                    vertex_count + 1,
                    4,
                )
                blobs[indices_blob] = _buffer_bytes(
                    mesh.get("joint_indices_u32"),
                    int(mesh.get("joint_index_offset", 0) or 0),
                    influence_count,
                    4,
                )
                blobs[weights_blob] = _buffer_bytes(
                    mesh.get("weights_f32"),
                    int(mesh.get("weight_float_offset", 0) or 0),
                    influence_count,
                    4,
                )
                skin_id = f"{provider}::{skeleton_native_id}::{mesh_native_id}"
                if skin_id not in self.skins:
                    self.add_skin(
                        f"{provider}::{mesh_native_id}",
                        joint_ids,
                        skin_id=skin_id,
                        inverse_bind_blob=inverse_blob,
                        weights_blob=weights_blob,
                        source_ref={
                            "provider_id": provider,
                            "native_id": skeleton_native_id,
                            "mesh_native_id": mesh_native_id,
                        },
                    )
                self.skins[skin_id].update({
                    "vertex_count": vertex_count,
                    "bind_geometry_matrix": [
                        float(value) for value in (mesh.get("bind_geometry_matrix") or IDENTITY_MATRIX)
                    ],
                    "rest_positions_blob": rest_blob,
                    "influence_offsets_blob": offsets_blob,
                    "joint_indices_blob": indices_blob,
                    "weights_blob": weights_blob,
                    "weight_encoding": "sparse_csr_f32_u32",
                    "deformation_mode": str(mesh.get("deformation_mode") or "point_cache"),
                    "runtime_mode": str(mesh.get("runtime_mode") or "point_cache"),
                    "max_influences_per_vertex": int(mesh.get("max_influences_per_vertex", 0) or 0),
                })
        return blobs

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RIG_GRAPH_SCHEMA,
            "nodes": list(self.nodes.values()),
            "connections": list(self.connections.values()),
            "joints": list(self.joints.values()),
            "skins": list(self.skins.values()),
            "constraints": list(self.constraints.values()),
            "deformers": list(self.deformers.values()),
            "animation": list(self.animation.values()),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EditableRigGraph":
        source = data if isinstance(data, dict) else {}
        graph = cls()
        graph.nodes = {str(item.get("id")): dict(item) for item in source.get("nodes") or [] if item.get("id")}
        graph.connections = {
            str(item.get("id")): dict(item) for item in source.get("connections") or [] if item.get("id")
        }
        graph.joints = {str(item.get("id")): dict(item) for item in source.get("joints") or [] if item.get("id")}
        graph.skins = {str(item.get("id")): dict(item) for item in source.get("skins") or [] if item.get("id")}
        graph.constraints = {
            str(item.get("id")): dict(item) for item in source.get("constraints") or [] if item.get("id")
        }
        graph.deformers = {
            str(item.get("id")): dict(item) for item in source.get("deformers") or [] if item.get("id")
        }
        graph.animation = {
            str(item.get("id")): dict(item) for item in source.get("animation") or [] if item.get("id")
        }
        graph.metadata = copy.deepcopy(source.get("metadata") or {})
        errors = graph.validate()
        if errors:
            raise ValueError("Invalid editable rig graph: " + "; ".join(errors[:8]))
        return graph

    def validate(self) -> list[str]:
        errors: list[str] = []
        for node_id, node in self.nodes.items():
            parent_id = str(node.get("dag_parent_id") or "")
            if parent_id and parent_id not in self.nodes:
                errors.append(f"{node_id}: missing DAG parent {parent_id}")
            seen = {node_id}
            cursor = parent_id
            while cursor:
                if cursor in seen:
                    errors.append(f"{node_id}: cyclic DAG hierarchy")
                    break
                seen.add(cursor)
                cursor = str(self.nodes.get(cursor, {}).get("dag_parent_id") or "")
        for connection_id, connection in self.connections.items():
            if str(connection.get("source_node") or "") not in self.nodes:
                errors.append(f"{connection_id}: missing source node")
            if str(connection.get("target_node") or "") not in self.nodes:
                errors.append(f"{connection_id}: missing target node")
        for joint_id, joint in self.joints.items():
            parent_id = str(joint.get("parent_id") or "")
            if parent_id and parent_id not in self.joints:
                errors.append(f"{joint_id}: missing parent {parent_id}")
            seen = {joint_id}
            cursor = parent_id
            while cursor:
                if cursor in seen:
                    errors.append(f"{joint_id}: cyclic hierarchy")
                    break
                seen.add(cursor)
                cursor = str(self.joints.get(cursor, {}).get("parent_id") or "")
        for skin_id, skin in self.skins.items():
            missing = [joint for joint in skin.get("joint_ids") or [] if joint not in self.joints]
            if missing:
                errors.append(f"{skin_id}: missing joints")
        for constraint_id, constraint in self.constraints.items():
            if str(constraint.get("type") or "") not in SUPPORTED_CONSTRAINTS:
                errors.append(f"{constraint_id}: unsupported constraint")
        for deformer_id, deformer in self.deformers.items():
            if str(deformer.get("type") or "") not in SUPPORTED_DEFORMERS:
                errors.append(f"{deformer_id}: unsupported deformer")
        return errors


@dataclass
class FederatedSceneDocument:
    name: str = "Untitled Federated Scene"
    scene_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sources: list[dict[str, Any]] = field(default_factory=list)
    rig_graph: EditableRigGraph = field(default_factory=EditableRigGraph)
    cross_dcc_constraints: list[dict[str, Any]] = field(default_factory=list)
    viewport: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    restoration: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FEDERATED_SCENE_SCHEMA,
            "scene_id": self.scene_id,
            "name": self.name,
            "sources": self.sources,
            "rig_graph": self.rig_graph.to_dict(),
            "cross_dcc_constraints": self.cross_dcc_constraints,
            "viewport": self.viewport,
            "timeline": self.timeline,
            "restoration": self.restoration,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FederatedSceneDocument":
        if str(data.get("schema") or "") != FEDERATED_SCENE_SCHEMA:
            raise ValueError("Unsupported Tech Connector scene schema.")
        return cls(
            name=str(data.get("name") or "Untitled Federated Scene"),
            scene_id=str(data.get("scene_id") or uuid.uuid4()),
            sources=[normalize_federated_scene_source(item) for item in data.get("sources") or [] if isinstance(item, dict)],
            rig_graph=EditableRigGraph.from_dict(data.get("rig_graph")),
            cross_dcc_constraints=[
                dict(item) for item in data.get("cross_dcc_constraints") or [] if isinstance(item, dict)
            ],
            viewport=dict(data.get("viewport") or {}),
            timeline=dict(data.get("timeline") or {}),
            restoration=dict(data.get("restoration") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


def stable_scene_source_id(provider: str, source_path: str = "", session_key: str = "") -> str:
    """Return a stable archive-safe identity that does not depend on a transient bridge port."""
    provider_key = str(provider or "unknown").strip().lower().split(":", 1)[0]
    path_key = ""
    if source_path:
        path_key = os.path.normcase(os.path.abspath(os.path.expanduser(str(source_path))))
    identity = f"{provider_key}|{path_key or str(session_key or '').strip().lower()}"
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{provider_key}-{digest}"


def source_snapshot_blob_name(source_id: str) -> str:
    safe_id = "".join(character if character.isalnum() or character in "-_" else "_" for character in source_id)
    return f"scene_sources/{safe_id or 'source'}/snapshot.json"


def save_federated_scene(
    path: str | os.PathLike[str],
    document: FederatedSceneDocument,
    *,
    blobs: dict[str, bytes | bytearray | memoryview] | None = None,
) -> Path:
    """Atomically save a versioned `.tcscene` archive."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Avoid tempfile's unbounded random-name retry loop here.  Sandboxed or
    # policy-controlled recovery directories can report denied creations as
    # collisions, which previously hung editor shutdown.  A UUID path gives us
    # a single bounded create attempt and lets the caller surface/fallback on a
    # real filesystem error.
    temporary_name = destination.with_name(
        f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with zipfile.ZipFile(temporary_name, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            archive.writestr("manifest.json", json.dumps(document.to_dict(), indent=2, sort_keys=True))
            for name, payload in (blobs or {}).items():
                entry = _safe_blob_name(name)
                compress_type = zipfile.ZIP_DEFLATED if entry.lower().endswith((".json", ".txt", ".xml")) else zipfile.ZIP_STORED
                archive.writestr("blobs/" + entry, bytes(payload), compress_type=compress_type)
        os.replace(temporary_name, destination)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return destination


def load_federated_scene(
    path: str | os.PathLike[str],
    *,
    max_manifest_bytes: int = 32 * 1024 * 1024,
    max_blob_bytes: int = 8 * 1024 * 1024 * 1024,
) -> tuple[FederatedSceneDocument, dict[str, bytes]]:
    """Load and validate a `.tcscene` archive with bounded allocations."""
    source = Path(path).expanduser().resolve()
    with zipfile.ZipFile(source, "r") as archive:
        infos = {item.filename: item for item in archive.infolist()}
        manifest_info = infos.get("manifest.json")
        if manifest_info is None or manifest_info.file_size > int(max_manifest_bytes):
            raise ValueError("The Tech Connector scene manifest is missing or too large.")
        manifest = json.loads(archive.read(manifest_info).decode("utf-8"))
        blobs: dict[str, bytes] = {}
        total = 0
        for name, info in infos.items():
            if not name.startswith("blobs/") or name.endswith("/"):
                continue
            key = _safe_blob_name(name[6:])
            total += int(info.file_size)
            if total > int(max_blob_bytes):
                raise ValueError("The Tech Connector scene binary cache exceeds the safety limit.")
            blobs[key] = archive.read(info)
    return FederatedSceneDocument.from_dict(manifest), blobs


def source_file_fingerprint(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path).expanduser()
    if source.is_dir():
        stat = source.stat()
        digest = hashlib.sha256()
        entries = []
        try:
            entries = sorted(source.iterdir(), key=lambda item: item.name.lower())[:256]
        except OSError:
            pass
        for item in entries:
            try:
                item_stat = item.stat()
                digest.update(item.name.encode("utf-8", errors="replace"))
                digest.update(str(int(item_stat.st_size)).encode("ascii"))
                digest.update(str(int(item_stat.st_mtime_ns)).encode("ascii"))
            except OSError:
                continue
        return {
            "exists": True,
            "kind": "directory",
            "size": len(entries),
            "mtime_ns": int(stat.st_mtime_ns),
            "head_sha256": digest.hexdigest(),
        }
    if not source.is_file():
        return {"exists": False}
    stat = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
    return {
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "head_sha256": digest.hexdigest(),
    }


def reconcile_scene_sources(
    document: FederatedSceneDocument,
    available_sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match stable source paths first and ephemeral ports only as a hint."""
    sessions = [dict(item) for item in available_sessions if isinstance(item, dict)]
    results: list[dict[str, Any]] = []
    for source in document.sources:
        provider = str(source.get("provider") or "").strip().lower().split(":", 1)[0]
        session_hint = str(source.get("session_key") or "").strip().lower()
        source_path = str(source.get("source_path") or "")
        provider_sessions = [
            item for item in sessions if str(item.get("provider") or "").strip().lower().split(":", 1)[0] == provider
        ]
        path_match = next(
            (item for item in provider_sessions if source_path and _same_path(source_path, str(item.get("scene") or ""))),
            None,
        )
        hint_match = next(
            (item for item in provider_sessions if str(item.get("key") or "").strip().lower() == session_hint),
            None,
        )
        clean_idle_match = next(
            (
                item for item in provider_sessions
                if not str(item.get("scene") or "").strip()
                and item.get("scene_modified") is False
            ),
            None,
        )
        match = path_match or (hint_match if not source_path else None) or clean_idle_match
        source_exists = bool(source_path and Path(source_path).exists())
        saved_fingerprint = source.get("source_fingerprint") if isinstance(source.get("source_fingerprint"), dict) else {}
        current_fingerprint = source_file_fingerprint(source_path) if source_exists else {"exists": False}
        source_changed = bool(
            saved_fingerprint.get("exists")
            and current_fingerprint.get("exists")
            and any(
                saved_fingerprint.get(key) != current_fingerprint.get(key)
                for key in ("size", "mtime_ns", "head_sha256")
                if saved_fingerprint.get(key) is not None
            )
        )
        if path_match is not None or (match is not None and not source_path):
            action = "attach"
        elif clean_idle_match is not None and source_exists:
            action = "open_source"
            match = clean_idle_match
        elif source_exists:
            action = "launch_source"
            match = None
        elif source_path:
            action = "missing_source"
        else:
            action = "offline"
        results.append({
            "source": source,
            "provider": provider,
            "action": action,
            "session": match,
            "session_key": str((match or {}).get("key") or session_hint),
            "source_exists": source_exists,
            "source_changed": source_changed,
            "current_fingerprint": current_fingerprint,
        })
    return results


def _same_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(os.path.expanduser(left))) == os.path.normcase(
        os.path.abspath(os.path.expanduser(right))
    )


def _safe_blob_name(name: str) -> str:
    normalized = str(name or "").replace("\\", "/").strip("/")
    if not normalized or normalized.startswith(".") or ".." in normalized.split("/"):
        raise ValueError(f"Unsafe scene blob name: {name}")
    return normalized


def _buffer_bytes(buffer: Any, offset: int, count: int, item_size: int) -> bytes:
    if buffer is None or int(count) <= 0:
        return b""
    try:
        raw = memoryview(buffer).cast("B")
        start = int(offset) * int(item_size)
        return bytes(raw[start:start + int(count) * int(item_size)])
    except (TypeError, ValueError):
        import array

        typecode = "f" if int(item_size) == 4 else "d"
        values = array.array(typecode, buffer[int(offset):int(offset) + int(count)])
        return values.tobytes()


def _bind_world_matrices(buffer: Any, offset: int, joint_count: int) -> list[list[float]]:
    try:
        import numpy as np

        inverse_bind = np.frombuffer(buffer, dtype=np.float32, count=int(joint_count) * 16, offset=int(offset) * 4)
        inverse_bind = inverse_bind.reshape((-1, 4, 4)).astype(np.float64)
        return [matrix.reshape(-1).tolist() for matrix in np.linalg.inv(inverse_bind)]
    except Exception:
        return [IDENTITY_MATRIX[:] for _ in range(int(joint_count))]


def _local_bind_matrix(
    bind_world_matrices: list[list[float]],
    index: int,
    joints: list[dict[str, Any]],
    source_to_joint_id: dict[str, str],
) -> list[float]:
    if index >= len(bind_world_matrices):
        return IDENTITY_MATRIX[:]
    parent_source_id = str(joints[index].get("parent_native_id") or "")
    parent_index = next(
        (candidate for candidate, item in enumerate(joints) if str(item.get("native_id") or "") == parent_source_id),
        -1,
    )
    if parent_index < 0 or parent_index >= len(bind_world_matrices):
        return list(bind_world_matrices[index])
    try:
        import numpy as np

        world = np.asarray(bind_world_matrices[index], dtype=np.float64).reshape((4, 4))
        parent_world = np.asarray(bind_world_matrices[parent_index], dtype=np.float64).reshape((4, 4))
        return (world @ np.linalg.inv(parent_world)).reshape(-1).tolist()
    except Exception:
        return list(bind_world_matrices[index])

