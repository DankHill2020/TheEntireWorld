from __future__ import annotations

"""Target-native procedural graph documents with lossless TC round-tripping."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from tech_connector.game_engine.authoring.procedural_generation_service import ProceduralGraph
from .procedural_transfer_service import TARGET_NODE_MAPPINGS, procedural_target_capabilities


@dataclass(frozen=True)
class ProceduralNativeDocument:
    target: str
    schema: str
    graph_id: str
    nodes: tuple[dict[str, Any], ...]
    links: tuple[dict[str, Any], ...]
    unsupported_nodes: tuple[str, ...]
    fallback: str
    tc_source_graph: dict[str, Any]

    @property
    def lossless(self) -> bool: return not self.unsupported_nodes
    def to_dict(self) -> dict[str, Any]: return asdict(self) | {"lossless": self.lossless}


TARGET_GRAPH_SCHEMAS = {
    "unreal": "unreal.pcg.graph.adapter.v1",
    "blender": "blender.geometry_nodes.adapter.v1",
    "houdini": "houdini.sop.network.adapter.v1",
    "unity": "unity.tc.procedural.graph.v1",
    "godot": "godot.tc.procedural.resource.v1",
}


def serialize_native_procedural_graph(graph: ProceduralGraph, target: str) -> ProceduralNativeDocument:
    normalized = str(target or "").strip().lower()
    procedural_target_capabilities(normalized)
    mapping = TARGET_NODE_MAPPINGS[normalized]; nodes: list[dict[str, Any]] = []; links: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for node_id in _order(graph):
        node = graph.nodes[node_id]; native_type = mapping.get(node.operation, "")
        if not native_type: unsupported.append(node_id)
        nodes.append({"id": node_id, "native_type": native_type or "TC_BakedGeometry",
                      "tc_operation": node.operation, "label": node.label, "enabled": node.enabled,
                      "position": [node.x, node.y], "parameters": deepcopy(node.parameters),
                      "execution": "native" if native_type else "baked_fallback"})
        links.extend({"source_node": source, "source_socket": "geometry", "target_node": node_id,
                      "target_socket": f"input_{index}"} for index, source in enumerate(node.inputs))
    return ProceduralNativeDocument(normalized, TARGET_GRAPH_SCHEMAS[normalized], graph.graph_id,
                                    tuple(nodes), tuple(links), tuple(unsupported),
                                    "baked_mesh_and_instance_manifest" if unsupported else "none",
                                    graph.to_dict())


def deserialize_native_procedural_graph(document: Mapping[str, Any]) -> ProceduralGraph:
    source = dict(document.get("tc_source_graph") or {})
    if source:
        return ProceduralGraph.from_dict(source)
    target = str(document.get("target") or "").lower(); reverse = {
        value: key for key, value in TARGET_NODE_MAPPINGS.get(target, {}).items()
    }
    graph = ProceduralGraph(name=str(document.get("name") or "Imported Procedural Graph"),
                            graph_id=str(document.get("graph_id") or "imported_procedural"))
    for row in document.get("nodes") or ():
        operation = str(row.get("tc_operation") or reverse.get(str(row.get("native_type") or ""), ""))
        if not operation: continue
        graph.add_node(str(row.get("id") or "node"), operation, parameters=deepcopy(dict(row.get("parameters") or {})),
                       label=str(row.get("label") or ""))
        graph.nodes[str(row.get("id") or "node")].enabled = bool(row.get("enabled", True))
    for link in document.get("links") or ():
        source, target_node = str(link.get("source_node") or ""), str(link.get("target_node") or "")
        if source in graph.nodes and target_node in graph.nodes: graph.connect(source, target_node)
    graph.output_node = str(document.get("output_node") or graph.output_node)
    return graph


def write_native_procedural_graph(graph: ProceduralGraph, target: str, path: str | Path) -> Path:
    destination = Path(path).expanduser().resolve(); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(serialize_native_procedural_graph(graph, target).to_dict(), indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return destination


def _order(graph: ProceduralGraph) -> list[str]:
    ordered: list[str] = []; visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visited: return
        for source in graph.nodes[node_id].inputs:
            if source in graph.nodes: visit(source)
        visited.add(node_id); ordered.append(node_id)
    for node_id in sorted(graph.nodes): visit(node_id)
    return ordered


__all__ = ["ProceduralNativeDocument", "TARGET_GRAPH_SCHEMAS", "deserialize_native_procedural_graph",
           "serialize_native_procedural_graph", "write_native_procedural_graph"]
