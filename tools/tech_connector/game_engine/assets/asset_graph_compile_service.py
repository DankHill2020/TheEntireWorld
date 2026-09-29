"""Deterministic compiler from interactive asset-editor models to runtime IR."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry


COMPILED_ASSET_IR_SCHEMA = "tech_connector.compiled_asset_ir.v1"
GRAPH_ASSET_TYPES = frozenset({
    "tc.material", "tc.shader_graph", "tc.gameplay_graph", "tc.animation_controller",
    "tc.simulation_profile", "tc.sound_cue",
})


@dataclass(frozen=True)
class AssetCompileDiagnostic:
    severity: str
    code: str
    message: str
    subject: str = ""


@dataclass(frozen=True)
class AssetCompileReceipt:
    asset_id: str
    type_id: str
    target: str
    operation_count: int
    diagnostics: tuple[AssetCompileDiagnostic, ...]
    artifact: DerivedArtifact | None
    ir: dict[str, Any]

    @property
    def succeeded(self) -> bool:
        return self.artifact is not None and not any(item.severity == "error" for item in self.diagnostics)


class AssetGraphCompileService:
    def __init__(
        self, database: AssetDatabase, registry: AssetTypeRegistry | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or builtin_asset_type_registry()

    def compile_asset(self, asset_id: str, *, target: str = "runtime") -> AssetCompileReceipt:
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown asset: {asset_id}")
        descriptor = self.registry.descriptor(record.asset_type)
        if descriptor is None:
            raise ValueError(f"No compiler is registered for {record.asset_type}.")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Compiled assets require readable authored JSON: {record.source_path}") from exc
        properties = dict(payload.get("properties") or {})
        diagnostics: list[AssetCompileDiagnostic] = []
        if record.asset_type in GRAPH_ASSET_TYPES:
            graph_key = "solver_graph" if record.asset_type == "tc.simulation_profile" else "graph"
            operations, graph_diagnostics = _compile_graph(
                dict(properties.get(graph_key) or {}), allow_cycles=record.asset_type in {"tc.gameplay_graph", "tc.animation_controller"}
            )
            diagnostics.extend(graph_diagnostics)
            executable = {"operations": operations, "entry_points": _entry_points(operations)}
            if record.asset_type in {"tc.material", "tc.shader_graph"}:
                from .material_asset_service import analyze_material_graph, shader_backend_capabilities

                material_issues, statistics = analyze_material_graph(
                    dict(properties.get(graph_key) or {}), platform=str(target),
                )
                diagnostics.extend(
                    AssetCompileDiagnostic(item.severity, item.code, item.message, item.subject)
                    for item in material_issues
                )
                executable["statistics"] = statistics
                executable["backend_capabilities"] = shader_backend_capabilities()
                executable["generated_source"] = _generate_shader_graph_source(
                    record.asset_type, operations, target=str(target),
                )
        elif record.asset_type == "tc.effect_system":
            executable, fx_diagnostics = _compile_emitters(list(properties.get("emitters") or ()))
            diagnostics.extend(fx_diagnostics)
        elif record.asset_type == "tc.animation_clip":
            executable, curve_diagnostics = _compile_curves(list(properties.get("curves") or ()))
            diagnostics.extend(curve_diagnostics)
        else:
            executable = {"properties": properties}
            diagnostics.append(AssetCompileDiagnostic(
                "info", "data_compile", "Compiled through the deterministic typed-data path."
            ))
        ir = {
            "schema": COMPILED_ASSET_IR_SCHEMA,
            "asset_id": record.asset_id,
            "type_id": record.asset_type,
            "revision": record.revision,
            "source_hash": record.content_hash,
            "target": str(target),
            "runtime_loader": descriptor.runtime_loader_id,
            "cooker": descriptor.cooker_id,
            "dependencies": [
                {"asset_id": dependency, "kind": kind}
                for dependency, kind in self.database.dependency_edges(record.asset_id)
            ],
            "executable": executable,
        }
        operation_count = _operation_count(executable)
        if any(item.severity == "error" for item in diagnostics):
            return AssetCompileReceipt(
                record.asset_id, record.asset_type, str(target), operation_count,
                tuple(diagnostics), None, ir,
            )
        encoded = json.dumps(ir, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifact = self.database.store_derived(
            record.asset_id, f"compiled_ir:{target}", encoded,
            metadata={
                "schema": COMPILED_ASSET_IR_SCHEMA, "type_id": record.asset_type,
                "operation_count": operation_count, "target": str(target),
            },
            extension=".tcir",
        )
        return AssetCompileReceipt(
            record.asset_id, record.asset_type, str(target), operation_count,
            tuple(diagnostics), artifact, ir,
        )


def _compile_graph(
    graph: dict[str, Any], *, allow_cycles: bool,
) -> tuple[list[dict[str, Any]], list[AssetCompileDiagnostic]]:
    nodes = [dict(item) for item in graph.get("nodes") or [] if isinstance(item, dict)]
    connections = [dict(item) for item in graph.get("connections") or [] if isinstance(item, dict)]
    diagnostics: list[AssetCompileDiagnostic] = []
    by_id = {str(item.get("id") or ""): item for item in nodes if str(item.get("id") or "")}
    if len(by_id) != len(nodes):
        diagnostics.append(AssetCompileDiagnostic("error", "duplicate_node_id", "Every graph node needs a unique ID."))
    incoming = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    valid_edges = []
    for edge in connections:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in by_id or target not in by_id:
            diagnostics.append(AssetCompileDiagnostic("error", "dangling_edge", "Connection targets a missing node."))
            continue
        compiled_edge = {"source": source, "target": target}
        for key in ("source_pin", "target_pin"):
            if edge.get(key):
                compiled_edge[key] = str(edge[key])
        source_type = _pin_type(by_id[source].get("outputs") or (), str(edge.get("source_pin") or ""))
        target_type = _pin_type(by_id[target].get("inputs") or (), str(edge.get("target_pin") or ""))
        if source_type and target_type and source_type != target_type and "any" not in {source_type, target_type}:
            diagnostics.append(AssetCompileDiagnostic(
                "error", "pin_type_mismatch",
                f"Cannot connect {source_type} to {target_type}.",
                f"{source}:{edge.get('source_pin', '')} -> {target}:{edge.get('target_pin', '')}",
            ))
        valid_edges.append(compiled_edge)
        outgoing[source].append(target)
        incoming[target] += 1
    ready = sorted(node_id for node_id, count in incoming.items() if count == 0)
    ordered = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for target in sorted(outgoing[node_id]):
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort()
    cyclic = sorted(set(by_id) - set(ordered))
    if cyclic and not allow_cycles:
        diagnostics.append(AssetCompileDiagnostic(
            "error", "dependency_cycle", "Graph contains a dependency cycle.", ", ".join(cyclic)
        ))
    if cyclic and allow_cycles:
        diagnostics.append(AssetCompileDiagnostic(
            "info", "control_flow_cycle", "Control-flow cycle retained for runtime execution.", ", ".join(cyclic)
        ))
        ordered.extend(cyclic)
    operations = []
    for order, node_id in enumerate(ordered):
        node = by_id[node_id]
        operations.append({
            "op_index": order, "node_id": node_id,
            "opcode": str(node.get("opcode") or _opcode(str(node.get("title") or "node"))),
            "parameters": dict(node.get("parameters") or {}),
            "inputs": sorted(edge["source"] for edge in valid_edges if edge["target"] == node_id),
            "outputs": sorted(edge["target"] for edge in valid_edges if edge["source"] == node_id),
        })
    if not operations:
        diagnostics.append(AssetCompileDiagnostic("warning", "empty_graph", "Graph has no executable nodes."))
    return operations, diagnostics


def _compile_emitters(
    emitters: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[AssetCompileDiagnostic]]:
    diagnostics: list[AssetCompileDiagnostic] = []
    compiled = []
    for index, emitter in enumerate(emitters):
        name = str(emitter.get("name") or f"Emitter {index + 1}")
        rate = float(emitter.get("spawn_rate", 0.0))
        modules = []
        for module_index, value in enumerate(emitter.get("modules") or ()):
            if isinstance(value, Mapping):
                row = dict(value)
                modules.append({
                    "module_index": module_index,
                    "id": str(row.get("id") or f"module_{module_index}"),
                    "opcode": _opcode(str(row.get("type") or row.get("module_type") or "module")),
                    "phase": str(row.get("phase") or "particle_update"),
                    "enabled": bool(row.get("enabled", True)),
                    "parameters": dict(row.get("parameters") or {}),
                    "version": int(row.get("version", 1)),
                })
            else:
                modules.append({
                    "module_index": module_index, "id": f"module_{module_index}",
                    "opcode": _opcode(str(value)), "phase": "particle_update",
                    "enabled": True, "parameters": {}, "version": 1,
                })
        if rate < 0.0:
            diagnostics.append(AssetCompileDiagnostic("error", "negative_spawn_rate", "Spawn rate cannot be negative.", name))
        if not modules:
            diagnostics.append(AssetCompileDiagnostic("error", "missing_modules", "Emitter has no executable modules.", name))
        compiled.append({
            "emitter_index": index, "id": str(emitter.get("id") or emitter.get("emitter_id") or f"emitter_{index}"),
            "name": name, "enabled": bool(emitter.get("enabled", True)),
            "simulation_target": str(emitter.get("simulation_target") or "auto"),
            "capacity": int(emitter.get("capacity") or emitter.get("max_particles") or 0),
            "spawn_rate": rate, "module_ops": modules,
            "renderers": list(emitter.get("renderers") or ([emitter.get("renderer")] if emitter.get("renderer") else [])),
        })
    if not compiled:
        diagnostics.append(AssetCompileDiagnostic("warning", "empty_effect", "Effect has no emitters."))
    return {"emitters": compiled}, diagnostics


def _compile_curves(
    curves: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[AssetCompileDiagnostic]]:
    diagnostics: list[AssetCompileDiagnostic] = []
    ordered = sorted(
        ({
            "frame": float(item.get("frame", 0.0)), "value": float(item.get("value", 0.0)),
            "interpolation": str(item.get("interpolation") or "linear"),
            "in_tangent": float(item.get("in_tangent", 0.0)),
            "out_tangent": float(item.get("out_tangent", 0.0)),
        } for item in curves),
        key=lambda item: item["frame"],
    )
    frames = [item["frame"] for item in ordered]
    if len(frames) != len(set(frames)):
        diagnostics.append(AssetCompileDiagnostic("error", "duplicate_key_frame", "Curve keys cannot share a frame."))
    segments = [
        {"start": ordered[index], "end": ordered[index + 1], "mode": ordered[index]["interpolation"]}
        for index in range(max(0, len(ordered) - 1))
    ]
    return {"keys": ordered, "segments": segments}, diagnostics


def _entry_points(operations: list[dict[str, Any]]) -> list[int]:
    return [int(item["op_index"]) for item in operations if not item.get("inputs")]


def _opcode(title: str) -> str:
    value = "_".join(part for part in "".join(char if char.isalnum() else " " for char in title).casefold().split() if part)
    return value or "node"


def _operation_count(executable: dict[str, Any]) -> int:
    if isinstance(executable.get("operations"), list):
        return len(executable["operations"])
    if isinstance(executable.get("emitters"), list):
        return sum(len(item.get("module_ops") or ()) for item in executable["emitters"])
    if isinstance(executable.get("segments"), list):
        return len(executable["segments"])
    return len(executable.get("properties") or {})


def _pin_type(pins: list[Any] | tuple[Any, ...], pin_name: str) -> str:
    if not pin_name:
        return ""
    for value in pins:
        name, _separator, kind = str(value).partition(":")
        if name == pin_name:
            return kind or "any"
    return ""


def _generate_shader_graph_source(type_id: str, operations: list[dict[str, Any]], *, target: str) -> str:
    entry_point = "TC_ShaderMain" if type_id == "tc.shader_graph" else "TC_Evaluate"
    lines = [
        "// Tech Connector generated shader graph",
        f"// type={type_id} target={target}",
        f"float4 {entry_point}(float2 uv0) {{",
        "  float4 result = float4(1.0, 1.0, 1.0, 1.0);",
    ]
    for operation in operations:
        lines.append(f"  // [{operation['op_index']}] {operation['opcode']} ({operation['node_id']})")
    lines.extend(["  return result;", "}"])
    return "\n".join(lines) + "\n"
