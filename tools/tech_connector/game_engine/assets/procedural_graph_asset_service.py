"""First-class procedural geometry graph assets and runtime cooks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from tech_connector.game_engine.authoring.procedural_generation_service import (
    PROCEDURAL_GRAPH_SCHEMA, PROCEDURAL_OPERATIONS, ProceduralGraph, ProceduralGraphCooker,
)
from tech_connector.game_engine.authoring.procedural_graph_tooling_service import (
    ProceduralNodeGroup, build_procedural_execution_plan,
)
from tech_connector.game_engine.authoring.procedural_task_graph_service import ProceduralTaskGraph

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


PROCEDURAL_ASSET_SCHEMA = "tech_connector.procedural_graph_asset.v1"
PROCEDURAL_RUNTIME_SCHEMA = "tech_connector.procedural_geometry_runtime.v1"


@dataclass(frozen=True)
class ProceduralGraphIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def procedural_graph_defaults(name: str = "ProceduralGraph") -> dict[str, Any]:
    return {
        "procedural_version": 1,
        "graph": ProceduralGraph(name=name, graph_id=name.casefold().replace(" ", "_")).to_dict(),
        "exposed_parameters": [],
        "node_groups": [],
        "task_graph": ProceduralTaskGraph(f"{name.casefold().replace(' ', '_')}_tasks").to_dict(),
        "simulation": {"enabled": False, "fixed_timestep": 0.016666667, "substeps": 1,
                       "gravity": [0.0, -9.81, 0.0], "damping": 0.02},
        "execution": {"mode": "editor_and_runtime", "partitioned": True, "grid_size": 6400.0,
                      "cache": "content_addressed", "backend": "auto", "frame_budget_ms": 8.0},
        "outputs": {"geometry": True, "instances": True, "collision": False, "navigation": False},
        "interchange": {"preserve_native_graph": True, "fallback": "baked_mesh"},
    }


class ProceduralGraphAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase, cooker: ProceduralGraphCooker | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database
        self.operations = AssetOperationsService(self.project_root, database); self.cooker = cooker or ProceduralGraphCooker()

    def create(self, name: str, *, graph: ProceduralGraph | None = None, folder: str | Path = "Assets/Procedural"):
        values = procedural_graph_defaults(name)
        if graph is not None: values["graph"] = graph.to_dict()
        receipt = self.operations.create_asset("tc.procedural_graph", name, folder=folder, properties=values)
        self.update(receipt.asset_id, values, replace=True); return receipt

    def properties(self, asset_id: str) -> dict[str, Any]:
        record, payload = self._load(asset_id); values = procedural_graph_defaults(record.source_path.stem.split(".")[0])
        values.update(deepcopy(dict(payload.get("properties") or {}))); return values

    def graph(self, asset_id: str) -> ProceduralGraph:
        return ProceduralGraph.from_dict(dict(self.properties(asset_id).get("graph") or {}))

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record, payload = self._load(asset_id); properties = procedural_graph_defaults() if replace else self.properties(asset_id)
        properties.update(deepcopy(dict(values or {})))
        graph = ProceduralGraph.from_dict(dict(properties.get("graph") or {})); properties["graph"] = graph.to_dict()
        payload["properties"] = properties; temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, record.source_path)
        dependencies = [(reference, "procedural_reference") for reference in sorted(_references(properties)) if self.database.asset(reference)]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=asset_id, metadata=record.metadata, dependencies=dependencies)
        self.cooker.clear(graph.graph_id); return properties

    def validate(self, asset_id: str) -> list[ProceduralGraphIssue]:
        values = self.properties(asset_id); graph = ProceduralGraph.from_dict(dict(values.get("graph") or {}))
        issues = [ProceduralGraphIssue("error", "graph", message, graph.graph_id) for message in graph.validate()]
        execution = dict(values.get("execution") or {})
        if str(execution.get("mode") or "") not in {"editor", "runtime", "editor_and_runtime", "baked"}:
            issues.append(ProceduralGraphIssue("error", "execution_mode", "Choose editor, runtime, editor_and_runtime, or baked execution.", "execution.mode"))
        if float(execution.get("frame_budget_ms", 0.0)) <= 0.0:
            issues.append(ProceduralGraphIssue("error", "frame_budget", "Runtime frame budget must be positive.", "execution.frame_budget_ms"))
        for index, row in enumerate(values.get("node_groups") or ()):
            try: ProceduralNodeGroup.from_dict(dict(row))
            except (TypeError, ValueError) as exc:
                issues.append(ProceduralGraphIssue("error", "node_group", str(exc), f"node_groups[{index}]"))
        try:
            task_errors = ProceduralTaskGraph.from_dict(dict(values.get("task_graph") or {})).validate()
        except (TypeError, ValueError) as exc:
            task_errors = [str(exc)]
        issues.extend(ProceduralGraphIssue("error", "task_graph", message, "task_graph") for message in task_errors)
        return issues

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        errors = [item.message for item in self.validate(asset_id) if item.severity == "error"]
        if errors: raise ValueError("Procedural Graph is not cookable: " + "; ".join(errors))
        values = self.properties(asset_id); result = self.cooker.cook(ProceduralGraph.from_dict(dict(values["graph"])))
        plan = build_procedural_execution_plan(ProceduralGraph.from_dict(dict(values["graph"])),
                                               backend=str(values["execution"].get("backend") or "auto"))
        # Runtime artifacts must be byte-for-byte reproducible.  The interactive
        # diagnostics intentionally contain wall-clock timings and cache-hit state,
        # so serialize only their semantic fields into the cooked payload.  Full
        # performance diagnostics remain available through ``diagnostics()``.
        cooked = result.to_dict()
        cooked["diagnostics"] = [
            {
                "node_id": row.node_id,
                "operation": row.operation,
                "point_count": row.point_count,
                "instance_count": row.instance_count,
                "fingerprint": row.fingerprint,
                "warnings": list(row.warnings),
            }
            for row in result.diagnostics
        ]
        payload = {"schema": PROCEDURAL_RUNTIME_SCHEMA, "asset_id": asset_id, "platform": platform, "quality": quality,
                   "execution": values["execution"], "execution_plan": plan.to_dict(),
                   "outputs": values["outputs"], "simulation": values["simulation"], "cook": cooked}
        return self.database.store_derived(asset_id, f"procedural_geometry:{platform}:{quality}",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            metadata={"platform": platform, "quality": quality, "graph_fingerprint": result.graph_fingerprint,
                      "operation_count": len(result.diagnostics), "mesh_count": len(result.payload.meshes),
                      "instance_count": len(result.payload.instances)}, extension=".tcproc")

    def operation_catalog(self) -> tuple[str, ...]: return tuple(sorted(PROCEDURAL_OPERATIONS))

    def diagnostics(self, asset_id: str) -> dict[str, Any]:
        result = self.cooker.cook(self.graph(asset_id))
        rows = [item.to_dict() if hasattr(item, "to_dict") else asdict(item) for item in result.diagnostics]
        return {"graph_id": result.graph_id, "graph_fingerprint": result.graph_fingerprint,
                "output_node": result.output_node, "total_ms": sum(float(row["elapsed_ms"]) for row in rows),
                "cache_hits": sum(bool(row["cache_hit"]) for row in rows), "nodes": rows,
                "counts": {"points": len(result.payload.points), "instances": len(result.payload.instances),
                           "meshes": len(result.payload.meshes)}}

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.procedural_graph": raise KeyError(f"Unknown Procedural Graph: {asset_id}")
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Could not read Procedural Graph: {exc}") from exc
        return record, payload


def _references(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).endswith("_asset_id") and str(nested): refs.add(str(nested))
            refs.update(_references(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value: refs.update(_references(nested))
    return refs


__all__ = ["PROCEDURAL_ASSET_SCHEMA", "PROCEDURAL_RUNTIME_SCHEMA", "ProceduralGraphAssetService", "ProceduralGraphIssue", "procedural_graph_defaults"]
