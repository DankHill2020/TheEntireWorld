"""Inherited gameplay classes with components, variables, events, and executable graphs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphInputBinding,
    compile_engine_graph_manifest,
    validate_engine_graph_program,
)
from tech_connector.game_engine.runtime.graph_execution_service import (
    GraphExecutionContext,
    execute_graph_manifest,
)

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService
from .gameplay_foundation_service import FIELD_TYPES, validate_foundation_asset


GAMEPLAY_CLASS_SCHEMA = "tech_connector.gameplay_class.v1"
GAMEPLAY_CLASS_RUNTIME_SCHEMA = "tech_connector.gameplay_class_runtime.v1"
GAMEPLAY_CLASS_KINDS = frozenset({"actor", "pawn", "character", "controller", "component", "object", "game_instance"})
REPLICATION_MODES = frozenset({"local", "replicated", "server", "owner", "skip_owner"})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class GameplayClassIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gameplay_class_defaults(*, class_kind: str = "actor", parent_class_id: str = "") -> dict[str, Any]:
    return {
        "class_version": 1,
        "class_kind": str(class_kind),
        "parent_class_id": str(parent_class_id),
        "abstract": False,
        "interfaces": [],
        "components": [
            {"id": "root", "name": "Root", "type": "transform", "parent_id": "", "enabled": True, "properties": {}},
        ],
        "variables": [],
        "functions": [],
        "events": ["On Begin Play"],
        "event_graph": {"entry_event": "On Begin Play", "nodes": [], "connections": []},
        "defaults": {},
        "replication": {"mode": "local", "replicate_movement": False, "network_frequency": 30.0, "dormancy": "awake"},
        "tags": [],
    }


class GameplayClassService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(
        self, name: str, *, class_kind: str = "actor", parent_class_id: str = "",
        components: Sequence[Mapping[str, Any]] = (), variables: Sequence[Mapping[str, Any]] = (),
        folder: str | Path = "Assets/Gameplay/Classes",
    ):
        values = gameplay_class_defaults(class_kind=class_kind, parent_class_id=parent_class_id)
        if components:
            values["components"] = [deepcopy(dict(row)) for row in components]
        if variables:
            values["variables"] = [deepcopy(dict(row)) for row in variables]
        receipt = self.operations.create_asset("tc.gameplay_class", name, folder=folder, properties=values)
        self.update(receipt.asset_id, values, replace=True)
        return receipt

    def properties(self, asset_id: str) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        values = gameplay_class_defaults()
        values.update(deepcopy(dict(payload.get("properties") or {})))
        return values

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        properties = gameplay_class_defaults() if replace else self.properties(asset_id)
        properties.update(deepcopy(dict(values or {})))
        parent_candidate = str(properties.get("parent_class_id") or "")
        if self._would_create_inheritance_cycle(asset_id, parent_candidate):
            raise ValueError("Gameplay Class inheritance contains a cycle.")
        payload["properties"] = properties
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, record.source_path)
        dependencies: dict[str, str] = {}
        parent = str(properties.get("parent_class_id") or "")
        if parent and self.database.asset(parent) is not None:
            dependencies[parent] = "parent_class"
        for reference in _asset_references(properties):
            if reference != asset_id and self.database.asset(reference) is not None:
                dependencies.setdefault(reference, "class_reference")
        self.database.register_asset(record.source_path, record.asset_type, asset_id=asset_id, metadata=record.metadata, dependencies=tuple(dependencies.items()))
        return properties

    def validate(self, asset_id: str) -> list[GameplayClassIssue]:
        values = self.properties(asset_id)
        issues = validate_gameplay_class(values)
        parent = str(values.get("parent_class_id") or "")
        if parent:
            record = self.database.asset(parent)
            if record is None:
                issues.append(GameplayClassIssue("error", "missing_parent", "Parent Gameplay Class does not exist.", "parent_class_id"))
            elif record.asset_type != "tc.gameplay_class":
                issues.append(GameplayClassIssue("error", "invalid_parent", "Parent must be another Gameplay Class.", "parent_class_id"))
        try:
            self.resolve(asset_id)
        except ValueError as exc:
            issues.append(GameplayClassIssue("error", "inheritance", str(exc), "parent_class_id"))
        program = graph_program_from_class(asset_id, values)
        issues.extend(
            GameplayClassIssue(str(row.get("severity") or "error"), str(row.get("code") or "graph"), str(row.get("message") or "Graph error."), str(row.get("node_id") or "event_graph"))
            for row in validate_engine_graph_program(program)
        )
        return _unique_issues(issues)

    def resolve(self, asset_id: str) -> dict[str, Any]:
        chain: list[str] = []
        current = str(asset_id)
        while current:
            if current in chain:
                raise ValueError("Gameplay Class inheritance contains a cycle.")
            record = self.database.asset(current)
            if record is None or record.asset_type != "tc.gameplay_class":
                raise ValueError(f"Gameplay Class inheritance references an unavailable class: {current}")
            chain.append(current)
            current = str(self.properties(current).get("parent_class_id") or "")
        resolved = gameplay_class_defaults()
        resolved["components"] = []
        resolved["variables"] = []
        resolved["functions"] = []
        resolved["events"] = []
        resolved["interfaces"] = []
        resolved["defaults"] = {}
        provenance: dict[str, dict[str, str]] = {"components": {}, "variables": {}, "functions": {}}
        for class_id in reversed(chain):
            values = self.properties(class_id)
            for scalar in ("class_version", "class_kind", "abstract", "event_graph", "replication", "tags"):
                if scalar in values:
                    resolved[scalar] = deepcopy(values[scalar])
            for collection, key in (("components", "id"), ("variables", "name"), ("functions", "name")):
                merged = {str(row.get(key) or ""): deepcopy(dict(row)) for row in resolved[collection] if str(row.get(key) or "")}
                for row in values.get(collection) or ():
                    identifier = str(dict(row).get(key) or "")
                    if identifier:
                        merged[identifier] = deepcopy(dict(row)); provenance[collection][identifier] = class_id
                resolved[collection] = list(merged.values())
            resolved["events"] = list(dict.fromkeys([*resolved["events"], *(str(row) for row in values.get("events") or () if str(row))]))
            resolved["interfaces"] = list(dict.fromkeys([*resolved["interfaces"], *(str(row) for row in values.get("interfaces") or () if str(row))]))
            resolved["defaults"].update(deepcopy(dict(values.get("defaults") or {})))
        resolved["asset_id"] = asset_id
        resolved["inheritance_chain"] = list(reversed(chain))
        resolved["provenance"] = provenance
        return resolved

    def compile(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        issues = self.validate(asset_id)
        errors = [item.message for item in issues if item.severity == "error"]
        if errors:
            raise ValueError("Gameplay Class is not cookable: " + " ".join(errors))
        resolved = self.resolve(asset_id)
        manifest = compile_engine_graph_manifest(graph_program_from_class(asset_id, resolved))
        payload = {
            "schema": GAMEPLAY_CLASS_RUNTIME_SCHEMA,
            "asset_id": asset_id,
            "platform": str(platform),
            "quality": str(quality),
            "class": resolved,
            "event_manifest": manifest,
        }
        return self.database.store_derived(asset_id, f"gameplay_class:{platform}:{quality}", json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"), metadata={"platform": platform, "quality": quality, "class_kind": resolved["class_kind"]}, extension=".tcclass")

    def debug_manifest(self, asset_id: str) -> dict[str, Any]:
        values = self.resolve(asset_id)
        manifest = compile_engine_graph_manifest(graph_program_from_class(asset_id, values))
        if not manifest.get("valid"):
            messages = [str(row.get("message") or "Graph error") for row in manifest.get("diagnostics") or () if row.get("severity") == "error"]
            raise ValueError("Gameplay Class graph is not debuggable: " + "; ".join(messages))
        return manifest

    def debug_context(self, asset_id: str, context: Mapping[str, Any] | None = None) -> GraphExecutionContext:
        values = self.resolve(asset_id)
        runtime_context = GraphExecutionContext.from_value(context or {})
        variables = runtime_context.metadata.setdefault("variables", {})
        if not isinstance(variables, dict):
            raise ValueError("Gameplay Class debugger metadata.variables must be a mapping.")
        for row in values.get("variables") or ():
            variable = dict(row); name = str(variable.get("name") or "")
            if name:
                variables.setdefault(name, deepcopy(variable.get("default")))
        return runtime_context

    def debug_event(self, asset_id: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        manifest = self.debug_manifest(asset_id)
        runtime_context = self.debug_context(asset_id, context)
        result = execute_graph_manifest(manifest, runtime_context).to_dict()
        result["runtime_state"] = {
            "actors": deepcopy(runtime_context.actors),
            "events": deepcopy(runtime_context.events),
            "metadata": deepcopy(runtime_context.metadata),
        }
        return result

    def _would_create_inheritance_cycle(self, asset_id: str, parent_id: str) -> bool:
        seen = {str(asset_id)}
        current = str(parent_id)
        while current:
            if current in seen:
                return True
            seen.add(current)
            record = self.database.asset(current)
            if record is None or record.asset_type != "tc.gameplay_class":
                return False
            current = str(self.properties(current).get("parent_class_id") or "")
        return False

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown Gameplay Class: {asset_id}")
        if record.asset_type != "tc.gameplay_class":
            raise ValueError(f"Asset is not a Gameplay Class: {asset_id}")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unreadable Gameplay Class: {record.source_path}") from exc
        return record, payload


def graph_program_from_class(asset_id: str, values: Mapping[str, Any]) -> EngineGraphProgram:
    graph = dict(values.get("event_graph") or {})
    nodes: list[EngineGraphNode] = []
    for row in graph.get("nodes") or ():
        source = dict(row)
        operation = str(source.get("opcode") or source.get("operation") or "")
        if operation in {"", "event"}:
            continue
        parameters = dict(source.get("parameters") or {})
        bindings = {str(name): GraphInputBinding(literal=deepcopy(value)) for name, value in parameters.items()}
        for pin in source.get("inputs") or ():
            name = str(pin).split(":", 1)[0]
            bindings.setdefault(name, GraphInputBinding())
        nodes.append(EngineGraphNode(str(source.get("id") or source.get("node_id") or ""), operation, str(source.get("title") or operation), bindings, position=(float(source.get("x", 0.0)), float(source.get("y", 0.0)))))
    by_id = {node.node_id: node for node in nodes}
    for edge in graph.get("connections") or ():
        link = dict(edge); target = by_id.get(str(link.get("target") or "")); source_id = str(link.get("source") or "")
        if target is None or source_id not in by_id:
            continue
        target_pin = str(link.get("target_pin") or "value").split(":", 1)[0]
        source_pin = str(link.get("source_pin") or "result").split(":", 1)[0]
        target.inputs[target_pin] = GraphInputBinding("link", None, source_id, source_pin)
    return EngineGraphProgram(
        program_id=f"gameplay_class_{asset_id}",
        display_name=str(values.get("display_name") or "Gameplay Class Event Graph"),
        entry_event=str(graph.get("entry_event") or "On Begin Play"),
        nodes=nodes,
        flow=[node.node_id for node in nodes],
    )


def validate_gameplay_class(values: Mapping[str, Any]) -> list[GameplayClassIssue]:
    issues: list[GameplayClassIssue] = []
    if str(values.get("class_kind") or "") not in GAMEPLAY_CLASS_KINDS:
        issues.append(GameplayClassIssue("error", "class_kind", "Choose a supported Gameplay Class kind.", "class_kind"))
    component_issues = validate_foundation_asset("tc.component_archetype", {"components": values.get("components") or ()})
    issues.extend(GameplayClassIssue(row.severity, row.code, row.message, row.subject) for row in component_issues)
    for collection in ("variables", "functions"):
        rows = [dict(row) for row in values.get(collection) or ()]
        names = [str(row.get("name") or "") for row in rows]
        if any(not _IDENTIFIER.match(name) for name in names):
            issues.append(GameplayClassIssue("error", f"invalid_{collection}", f"{collection.title()} require stable identifier names.", collection))
        if len(names) != len(set(names)):
            issues.append(GameplayClassIssue("error", f"duplicate_{collection}", f"{collection.title()} names must be unique.", collection))
    for variable in values.get("variables") or ():
        row = dict(variable); kind = str(row.get("type") or "")
        if kind not in FIELD_TYPES:
            issues.append(GameplayClassIssue("error", "variable_type", f"Unsupported variable type: {kind}", str(row.get("name") or "variables")))
        mode = str(row.get("replication") or "local")
        if mode not in REPLICATION_MODES:
            issues.append(GameplayClassIssue("error", "variable_replication", f"Unsupported replication mode: {mode}", str(row.get("name") or "variables")))
    replication = dict(values.get("replication") or {})
    if str(replication.get("mode") or "local") not in REPLICATION_MODES:
        issues.append(GameplayClassIssue("error", "replication_mode", "Choose a supported class replication mode.", "replication"))
    if float(replication.get("network_frequency", 30.0) or 0.0) <= 0.0:
        issues.append(GameplayClassIssue("error", "network_frequency", "Network frequency must be greater than zero.", "replication"))
    return issues


def _asset_references(value: Any, key: str = "") -> list[str]:
    result: list[str] = []
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            result.extend(_asset_references(child, str(child_key)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(_asset_references(child, key))
    elif isinstance(value, str) and value and (key.endswith("_asset_id") or key.endswith("_class_id")):
        result.append(value)
    return list(dict.fromkeys(result))


def _unique_issues(values: Sequence[GameplayClassIssue]) -> list[GameplayClassIssue]:
    return list({(row.severity, row.code, row.message, row.subject): row for row in values}.values())


__all__ = [
    "GAMEPLAY_CLASS_KINDS", "GAMEPLAY_CLASS_RUNTIME_SCHEMA", "GAMEPLAY_CLASS_SCHEMA",
    "REPLICATION_MODES", "GameplayClassIssue", "GameplayClassService",
    "gameplay_class_defaults", "graph_program_from_class", "validate_gameplay_class",
]
