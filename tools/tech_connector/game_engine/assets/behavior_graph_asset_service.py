from __future__ import annotations

"""Executable Behavior and Gameplay Graph assets backed by the native graph ABI."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphProgram, compile_engine_graph_manifest, validate_engine_graph_program,
)
from tech_connector.game_engine.runtime.graph_execution_service import GraphExecutionContext, execute_graph_manifest

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


BEHAVIOR_GRAPH_RUNTIME_SCHEMA = "tech_connector.behavior_graph_runtime.v1"
BEHAVIOR_GRAPH_TYPES = frozenset({"tc.behavior", "tc.gameplay_graph"})


@dataclass(frozen=True)
class BehaviorGraphIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class BehaviorGraphAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(
        self, type_id: str, name: str, *, program: EngineGraphProgram | Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/Gameplay/Graphs",
    ):
        if type_id not in BEHAVIOR_GRAPH_TYPES:
            raise ValueError(f"Unsupported executable graph type: {type_id}")
        graph = program if isinstance(program, EngineGraphProgram) else EngineGraphProgram.from_dict(dict(program or {}))
        graph.program_id = graph.program_id or _identifier(name)
        graph.display_name = graph.display_name or str(name)
        receipt = self.operations.create_asset(type_id, name, folder=folder, properties={"program": graph.to_dict()})
        self.update(receipt.asset_id, graph)
        return receipt

    def properties(self, asset_id: str) -> dict[str, Any]:
        _record, payload = self._load(asset_id)
        return deepcopy(dict(payload.get("properties") or {}))

    def program(self, asset_id: str) -> EngineGraphProgram:
        return EngineGraphProgram.from_dict(dict(self.properties(asset_id).get("program") or {}))

    def update(self, asset_id: str, program: EngineGraphProgram | Mapping[str, Any]) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        graph = program if isinstance(program, EngineGraphProgram) else EngineGraphProgram.from_dict(dict(program))
        payload["properties"] = {"program": graph.to_dict()}
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, record.source_path)
        dependencies = tuple((value, "graph_reference") for value in _asset_references(graph.to_dict()) if self.database.asset(value) is not None and value != asset_id)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=asset_id, metadata=record.metadata, dependencies=dependencies)
        return self.properties(asset_id)

    def validate(self, asset_id: str) -> list[BehaviorGraphIssue]:
        return [BehaviorGraphIssue(str(row.get("severity") or "error"), str(row.get("code") or "graph"),
                                   str(row.get("message") or "Graph validation failed."), str(row.get("node_id") or ""))
                for row in validate_engine_graph_program(self.program(asset_id))]

    def manifest(self, asset_id: str) -> dict[str, Any]:
        manifest = compile_engine_graph_manifest(self.program(asset_id))
        if not manifest.get("valid"):
            errors = [str(row.get("message") or "Graph error") for row in manifest.get("diagnostics") or () if row.get("severity") == "error"]
            raise ValueError("Executable graph is invalid: " + "; ".join(errors))
        return manifest

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record, _payload = self._load(asset_id)
        payload = {"schema": BEHAVIOR_GRAPH_RUNTIME_SCHEMA, "asset_id": asset_id, "type_id": record.asset_type,
                   "platform": str(platform), "quality": str(quality), "manifest": self.manifest(asset_id)}
        return self.database.store_derived(asset_id, f"behavior_graph:{platform}:{quality}",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            metadata={"platform": platform, "quality": quality, "type_id": record.asset_type}, extension=".tcgraph")

    def execute(self, asset_id: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        runtime_context = GraphExecutionContext.from_value(context or {})
        receipt = execute_graph_manifest(self.manifest(asset_id), runtime_context)
        result = receipt.to_dict()
        result["runtime_state"] = {"actors": deepcopy(runtime_context.actors), "events": deepcopy(runtime_context.events),
                                   "metadata": deepcopy(runtime_context.metadata)}
        return result

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown executable graph: {asset_id}")
        if record.asset_type not in BEHAVIOR_GRAPH_TYPES: raise ValueError(f"Asset is not an executable Behavior or Gameplay Graph: {asset_id}")
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Unreadable executable graph: {record.source_path}") from exc
        return record, payload


def _identifier(value: str) -> str:
    return "".join(character.casefold() if character.isalnum() else "_" for character in str(value)).strip("_") or "graph"


def _asset_references(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).endswith("_asset_id") and str(nested): refs.add(str(nested))
            refs.update(_asset_references(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value: refs.update(_asset_references(nested))
    return refs


__all__ = ["BEHAVIOR_GRAPH_RUNTIME_SCHEMA", "BEHAVIOR_GRAPH_TYPES", "BehaviorGraphAssetService", "BehaviorGraphIssue"]
