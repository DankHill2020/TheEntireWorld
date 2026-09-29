"""Typed project, data, component, and gameplay-framework asset authoring."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


GAMEPLAY_FOUNDATION_SCHEMA = "tech_connector.gameplay_foundation.v1"
GAMEPLAY_FOUNDATION_RUNTIME_SCHEMA = "tech_connector.gameplay_foundation_runtime.v1"
GAMEPLAY_FOUNDATION_TYPES = frozenset({
    "tc.project_settings", "tc.data_schema", "tc.struct", "tc.enum", "tc.data",
    "tc.data_table", "tc.component_archetype", "tc.character_definition",
})
FIELD_TYPES = frozenset({
    "bool", "int", "float", "string", "name", "vector2", "vector3", "color",
    "asset_ref", "enum", "struct", "array", "map",
})
COMPONENT_TYPES = frozenset({
    "transform", "static_mesh", "skeletal_mesh", "collision", "character_movement",
    "camera", "spring_arm", "audio", "input", "gameplay", "animation", "physics",
    "navigation", "network", "ui_anchor",
})


@dataclass(frozen=True)
class GameplayFoundationIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def data_schema_defaults() -> dict[str, Any]:
    return {"version": 1, "parent_schema_id": "", "fields": [], "tags": [], "documentation": ""}


def enum_defaults() -> dict[str, Any]:
    return {"version": 1, "flags": False, "entries": [{"name": "Default", "value": 0, "description": ""}]}


def data_asset_defaults() -> dict[str, Any]:
    return {"version": 1, "schema_asset_id": "", "values": {}, "primary_asset": False, "bundle_labels": [], "tags": []}


def data_table_defaults() -> dict[str, Any]:
    return {"version": 1, "row_schema_id": "", "key_field": "id", "rows": [], "source_csv": "", "tags": []}


def component_archetype_defaults() -> dict[str, Any]:
    return {
        "version": 1, "parent_archetype_id": "", "tags": [], "replication": "inherit",
        "components": [{"id": "root", "name": "Root", "type": "transform", "parent_id": "", "enabled": True, "properties": {}}],
        "exposed_properties": [],
    }


def character_definition_defaults() -> dict[str, Any]:
    return {
        "version": 1, "archetype_asset_id": "", "skeletal_mesh_asset_id": "",
        "skeleton_asset_id": "", "skin_binding_asset_id": "", "animation_controller_asset_id": "",
        "input_map_asset_id": "", "camera_archetype_asset_id": "", "physics_asset_id": "",
        "movement": {"mode": "walking", "maximum_speed": 6.0, "acceleration": 24.0, "deceleration": 30.0, "jump_height": 1.2, "air_control": 0.35, "rotation_mode": "orient_to_movement"},
        "abilities": [], "attributes": {}, "tags": ["character.player"], "network": {"replicated": True, "prediction": True},
    }


def project_settings_defaults() -> dict[str, Any]:
    return {
        "version": 1,
        "project": {"display_name": "Game", "company": "", "version": "0.1.0", "description": ""},
        "startup": {"default_level_asset_id": "", "loading_level_asset_id": ""},
        "gameplay": {"ruleset_asset_id": "", "default_character_asset_id": "", "input_map_asset_id": "", "game_instance_asset_id": ""},
        "rendering": {"quality_profile": "high", "frame_rate_limit": 0, "hdr": True},
        "physics": {"physics_scene_asset_id": "", "fixed_time_step": 0.0166667},
        "audio": {"mixer_asset_id": "", "master_volume": 1.0},
        "build": {"default_build_profile_asset_id": ""},
        "platform_overrides": {},
    }


def defaults_for(type_id: str) -> dict[str, Any]:
    return {
        "tc.project_settings": project_settings_defaults,
        "tc.data_schema": data_schema_defaults, "tc.struct": data_schema_defaults,
        "tc.enum": enum_defaults, "tc.data": data_asset_defaults,
        "tc.data_table": data_table_defaults, "tc.component_archetype": component_archetype_defaults,
        "tc.character_definition": character_definition_defaults,
    }[type_id]()


class GameplayFoundationService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create_project_settings(self, name: str = "ProjectSettings", *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Settings"):
        existing = [row for row in self.database.list_assets() if row.asset_type == "tc.project_settings"]
        if existing: raise ValueError("A project can have only one Project Settings asset.")
        return self._create("tc.project_settings", name, properties, folder)

    def create_schema(self, name: str, *, fields: Sequence[Mapping[str, Any]] = (), parent_schema_id: str = "", folder: str | Path = "Assets/Data/Schemas"):
        return self._create("tc.data_schema", name, {"fields": list(fields), "parent_schema_id": parent_schema_id}, folder)

    def create_struct(self, name: str, *, fields: Sequence[Mapping[str, Any]] = (), parent_schema_id: str = "", folder: str | Path = "Assets/Data/Structs"):
        return self._create("tc.struct", name, {"fields": list(fields), "parent_schema_id": parent_schema_id}, folder)

    def create_enum(self, name: str, *, entries: Sequence[Mapping[str, Any] | str] = (), flags: bool = False, folder: str | Path = "Assets/Data/Enums"):
        normalized = [dict(row) if isinstance(row, Mapping) else {"name": str(row), "value": index, "description": ""} for index, row in enumerate(entries)]
        return self._create("tc.enum", name, {"entries": normalized or enum_defaults()["entries"], "flags": flags}, folder)

    def create_data_asset(self, name: str, *, schema_asset_id: str = "", values: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Data"):
        return self._create("tc.data", name, {"schema_asset_id": schema_asset_id, "values": dict(values or {})}, folder)

    def create_data_table(self, name: str, *, row_schema_id: str = "", rows: Sequence[Mapping[str, Any]] = (), key_field: str = "id", folder: str | Path = "Assets/Data/Tables"):
        return self._create("tc.data_table", name, {"row_schema_id": row_schema_id, "rows": list(rows), "key_field": key_field}, folder)

    def create_component_archetype(self, name: str, *, components: Sequence[Mapping[str, Any]] = (), parent_archetype_id: str = "", folder: str | Path = "Assets/Gameplay/Components"):
        values: dict[str, Any] = {"parent_archetype_id": parent_archetype_id}
        if components: values["components"] = list(components)
        return self._create("tc.component_archetype", name, values, folder)

    def create_character_definition(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Gameplay/Characters"):
        return self._create("tc.character_definition", name, properties, folder)

    def properties(self, asset_id: str) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        values = defaults_for(record.asset_type); values.update(deepcopy(dict(payload.get("properties") or {})))
        return values

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        properties = defaults_for(record.asset_type) if replace else self.properties(asset_id)
        properties.update(deepcopy(dict(values or {}))); payload["properties"] = properties
        self._write(record.source_path, payload)
        dependencies = [(ref, kind) for ref, kind in _references(record.asset_type, properties) if self.database.asset(ref) is not None and ref != asset_id]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata, dependencies=dependencies)
        return properties

    def validate(self, asset_id: str) -> list[GameplayFoundationIssue]:
        record = self._require(asset_id); values = self.properties(asset_id)
        issues = validate_foundation_asset(record.asset_type, values)
        for reference, _kind in _references(record.asset_type, values):
            if reference and self.database.asset(reference) is None:
                issues.append(GameplayFoundationIssue("error", "missing_reference", f"Referenced asset does not exist: {reference}", reference))
        for subject, reference, expected in _expected_references(record.asset_type, values):
            target = self.database.asset(reference) if reference else None
            if target is not None and target.asset_type not in expected:
                issues.append(GameplayFoundationIssue("error", "reference_type", f"{subject} requires {', '.join(sorted(expected))}, not {target.asset_type}.", subject))
        if record.asset_type in {"tc.data_schema", "tc.struct"}:
            try: self.resolve_schema(asset_id)
            except ValueError as exc: issues.append(GameplayFoundationIssue("error", "schema_cycle", str(exc), "parent_schema_id"))
        if record.asset_type == "tc.project_settings" and len([row for row in self.database.list_assets() if row.asset_type == "tc.project_settings"]) > 1:
            issues.append(GameplayFoundationIssue("error", "duplicate_project_settings", "A project can have only one Project Settings asset."))
        if record.asset_type == "tc.data":
            schema_id = str(values.get("schema_asset_id") or "")
            if schema_id and self.database.asset(schema_id): issues.extend(self._validate_values(schema_id, dict(values.get("values") or {})))
        if record.asset_type == "tc.data_table":
            schema_id = str(values.get("row_schema_id") or "")
            if schema_id and self.database.asset(schema_id):
                for index, row in enumerate(values.get("rows") or []):
                    issues.extend(GameplayFoundationIssue(item.severity, item.code, item.message, f"row {index}: {item.subject}") for item in self._validate_values(schema_id, dict(row)))
        return issues

    def resolve_schema(self, asset_id: str) -> dict[str, Any]:
        record = self._require(asset_id)
        if record.asset_type not in {"tc.data_schema", "tc.struct"}: raise ValueError("Asset is not a schema or struct.")
        chain: list[str] = []; fields: dict[str, dict[str, Any]] = {}; current = asset_id
        while current:
            if current in chain: raise ValueError("Schema inheritance contains a cycle.")
            chain.append(current); values = self.properties(current)
            for field in reversed(list(values.get("fields") or [])): fields[str(field.get("name") or "")] = deepcopy(dict(field))
            current = str(values.get("parent_schema_id") or "")
        ordered = list(reversed(chain)); merged: dict[str, dict[str, Any]] = {}
        for schema_id in ordered:
            for field in self.properties(schema_id).get("fields") or []: merged[str(field.get("name") or "")] = deepcopy(dict(field))
        return {"schema_ids": ordered, "fields": list(merged.values())}

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self._require(asset_id); issues = self.validate(asset_id)
        errors = [item.message for item in issues if item.severity == "error"]
        if errors: raise ValueError("Gameplay foundation asset is not cookable: " + " ".join(errors))
        payload = {"schema": GAMEPLAY_FOUNDATION_RUNTIME_SCHEMA, "type_id": record.asset_type, "asset_id": asset_id, "platform": platform, "quality": quality, "properties": self.properties(asset_id)}
        if record.asset_type in {"tc.data_schema", "tc.struct"}: payload["resolved_schema"] = self.resolve_schema(asset_id)
        return self.database.store_derived(asset_id, f"gameplay_foundation:{platform}:{quality}", json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), metadata={"type_id": record.asset_type, "platform": platform, "quality": quality}, extension=".tcdata")

    def convert_unreal(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Data/Converted/Unreal") -> dict[str, Any]:
        created = []; mapping = {}
        for row in exported_data.get("data_assets") or []:
            name = str(row.get("name") or "UnrealDataAsset"); fields = _infer_fields(dict(row.get("values") or row.get("properties") or {}))
            schema = self.create_schema(name + "Schema", fields=fields, folder=Path(folder) / "Schemas")
            asset = self.create_data_asset(name, schema_asset_id=schema.asset_id, values=dict(row.get("values") or row.get("properties") or {}), folder=folder)
            created += [schema.asset_id, asset.asset_id]; mapping[str(row.get("object_path") or name)] = asset.asset_id
        return {"provider": "unreal", "version": str(exported_data.get("engine_version") or ""), "asset_ids": created, "source_to_asset": mapping}

    def convert_unity(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Data/Converted/Unity") -> dict[str, Any]:
        created = []; mapping = {}
        for row in exported_data.get("scriptable_objects") or []:
            name = str(row.get("name") or "ScriptableObject"); values = dict(row.get("fields") or row.get("values") or {})
            schema = self.create_schema(str(row.get("type") or name) + "Schema", fields=_infer_fields(values), folder=Path(folder) / "Schemas")
            asset = self.create_data_asset(name, schema_asset_id=schema.asset_id, values=values, folder=folder)
            created += [schema.asset_id, asset.asset_id]; mapping[str(row.get("guid") or name)] = asset.asset_id
        return {"provider": "unity", "version": str(exported_data.get("unity_version") or ""), "asset_ids": created, "source_to_asset": mapping}

    def _create(self, type_id: str, name: str, properties: Mapping[str, Any] | None, folder: str | Path):
        receipt = self.operations.create_asset(type_id, name, folder=folder, properties=defaults_for(type_id))
        self.update(receipt.asset_id, properties or {}); return receipt

    def _require(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None: raise KeyError(f"Unknown gameplay foundation asset: {asset_id}")
        if record.asset_type not in GAMEPLAY_FOUNDATION_TYPES: raise ValueError(f"Asset is not a gameplay foundation asset: {asset_id}")
        return record

    def _load(self, asset_id: str):
        record = self._require(asset_id)
        try: payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError(f"Unreadable authored asset: {record.source_path}") from exc
        return record, payload

    def _validate_values(self, schema_id: str, values: Mapping[str, Any]) -> list[GameplayFoundationIssue]:
        issues = []
        for field in self.resolve_schema(schema_id)["fields"]:
            name = str(field.get("name") or ""); required = bool(field.get("required"))
            if required and name not in values: issues.append(GameplayFoundationIssue("error", "required_field", f"Required field '{name}' is missing.", name)); continue
            if name in values and not _matches_type(values[name], str(field.get("type") or "string")): issues.append(GameplayFoundationIssue("error", "field_type", f"Field '{name}' does not match type {field.get('type')}.", name))
        return issues

    @staticmethod
    def _write(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp"); temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, path)


def validate_foundation_asset(type_id: str, values: Mapping[str, Any]) -> list[GameplayFoundationIssue]:
    issues: list[GameplayFoundationIssue] = []
    if type_id in {"tc.data_schema", "tc.struct"}:
        fields = [dict(row) for row in values.get("fields") or []]; names = [str(row.get("name") or "") for row in fields]
        if any(not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) for name in names): issues.append(GameplayFoundationIssue("error", "invalid_field_name", "Field names must be stable identifiers.", "fields"))
        if len(names) != len(set(names)): issues.append(GameplayFoundationIssue("error", "duplicate_field", "Schema field names must be unique.", "fields"))
        for field in fields:
            if str(field.get("type") or "") not in FIELD_TYPES: issues.append(GameplayFoundationIssue("error", "invalid_field_type", f"Unsupported field type: {field.get('type')}", str(field.get("name") or "")))
    elif type_id == "tc.enum":
        entries = [dict(row) for row in values.get("entries") or []]; names = [str(row.get("name") or "") for row in entries]; numbers = [int(row.get("value", 0)) for row in entries]
        if not entries: issues.append(GameplayFoundationIssue("error", "empty_enum", "Enum requires at least one entry."))
        if len(names) != len(set(names)) or len(numbers) != len(set(numbers)): issues.append(GameplayFoundationIssue("error", "duplicate_enum_entry", "Enum names and numeric values must be unique."))
    elif type_id == "tc.data_table":
        key = str(values.get("key_field") or "id"); keys = [str(dict(row).get(key) or "") for row in values.get("rows") or []]
        if any(not value for value in keys): issues.append(GameplayFoundationIssue("error", "missing_row_key", f"Every table row requires '{key}'."))
        if len(keys) != len(set(keys)): issues.append(GameplayFoundationIssue("error", "duplicate_row_key", "Data-table row keys must be unique."))
    elif type_id == "tc.component_archetype":
        components = [dict(row) for row in values.get("components") or []]; ids = [str(row.get("id") or "") for row in components]
        if len(ids) != len(set(ids)) or any(not value for value in ids): issues.append(GameplayFoundationIssue("error", "component_identity", "Components require unique stable IDs."))
        for row in components:
            if str(row.get("type") or "") not in COMPONENT_TYPES: issues.append(GameplayFoundationIssue("warning", "custom_component", f"Custom component type '{row.get('type')}' requires a registered runtime factory.", str(row.get("id") or "")))
            parent = str(row.get("parent_id") or "")
            if parent and parent not in ids: issues.append(GameplayFoundationIssue("error", "missing_component_parent", f"Component parent '{parent}' does not exist.", str(row.get("id") or "")))
        parents = {str(row.get("id") or ""): str(row.get("parent_id") or "") for row in components}
        for component_id in ids:
            seen: set[str] = set(); current = component_id
            while current:
                if current in seen:
                    issues.append(GameplayFoundationIssue("error", "component_cycle", "Component hierarchy contains a parent cycle.", component_id)); break
                seen.add(current); current = parents.get(current, "")
    elif type_id == "tc.character_definition":
        movement = dict(values.get("movement") or {})
        if float(movement.get("maximum_speed", 0.0)) < 0: issues.append(GameplayFoundationIssue("error", "negative_speed", "Character maximum speed cannot be negative.", "movement"))
    elif type_id == "tc.project_settings":
        master = float(dict(values.get("audio") or {}).get("master_volume", 1.0))
        if not 0.0 <= master <= 1.0: issues.append(GameplayFoundationIssue("error", "master_volume", "Master volume must be between zero and one.", "audio"))
    return issues


def _references(type_id: str, values: Mapping[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    def visit(value: Any, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child in value.items(): visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value: visit(child, key)
        elif isinstance(value, str) and value and (key.endswith("_asset_id") or key.endswith("_schema_id")):
            result.append((value, "hard"))
    visit(values)
    return list(dict.fromkeys(result))


def _expected_references(type_id: str, values: Mapping[str, Any]) -> list[tuple[str, str, frozenset[str]]]:
    specs: dict[str, dict[str, frozenset[str]]] = {
        "tc.data": {"schema_asset_id": frozenset({"tc.data_schema", "tc.struct"})},
        "tc.data_table": {"row_schema_id": frozenset({"tc.data_schema", "tc.struct"})},
        "tc.data_schema": {"parent_schema_id": frozenset({"tc.data_schema", "tc.struct"})},
        "tc.struct": {"parent_schema_id": frozenset({"tc.data_schema", "tc.struct"})},
        "tc.component_archetype": {"parent_archetype_id": frozenset({"tc.component_archetype"})},
        "tc.character_definition": {
            "archetype_asset_id": frozenset({"tc.component_archetype"}), "skeletal_mesh_asset_id": frozenset({"tc.skeletal_mesh"}),
            "skeleton_asset_id": frozenset({"tc.skeleton"}), "skin_binding_asset_id": frozenset({"tc.skin_binding"}),
            "animation_controller_asset_id": frozenset({"tc.animation_controller"}), "input_map_asset_id": frozenset({"tc.input_map"}),
            "camera_archetype_asset_id": frozenset({"tc.component_archetype"}), "physics_asset_id": frozenset({"tc.physics_asset"}),
        },
    }
    result = []
    for key, expected in specs.get(type_id, {}).items():
        reference = str(values.get(key) or "")
        if reference: result.append((key, reference, expected))
    if type_id == "tc.project_settings":
        nested_specs = (
            ("startup.default_level_asset_id", "startup", "default_level_asset_id", frozenset({"tc.level"})),
            ("gameplay.ruleset_asset_id", "gameplay", "ruleset_asset_id", frozenset({"tc.game_ruleset"})),
            ("gameplay.default_character_asset_id", "gameplay", "default_character_asset_id", frozenset({"tc.character_definition", "tc.prefab"})),
            ("gameplay.input_map_asset_id", "gameplay", "input_map_asset_id", frozenset({"tc.input_map"})),
            ("physics.physics_scene_asset_id", "physics", "physics_scene_asset_id", frozenset({"tc.physics_scene"})),
            ("audio.mixer_asset_id", "audio", "mixer_asset_id", frozenset({"tc.audio_mixer"})),
            ("build.default_build_profile_asset_id", "build", "default_build_profile_asset_id", frozenset({"tc.build_profile"})),
        )
        for subject, section, key, expected in nested_specs:
            reference = str(dict(values.get(section) or {}).get(key) or "")
            if reference: result.append((subject, reference, expected))
    return result


def _matches_type(value: Any, kind: str) -> bool:
    if value is None: return True
    return {
        "bool": lambda row: isinstance(row, bool), "int": lambda row: isinstance(row, int) and not isinstance(row, bool),
        "float": lambda row: isinstance(row, (int, float)) and not isinstance(row, bool), "string": lambda row: isinstance(row, str),
        "name": lambda row: isinstance(row, str), "vector2": lambda row: isinstance(row, list) and len(row) == 2,
        "vector3": lambda row: isinstance(row, list) and len(row) == 3, "color": lambda row: isinstance(row, (str, list)),
        "asset_ref": lambda row: isinstance(row, str), "enum": lambda row: isinstance(row, (str, int)),
        "struct": lambda row: isinstance(row, Mapping), "array": lambda row: isinstance(row, list), "map": lambda row: isinstance(row, Mapping),
    }.get(kind, lambda _row: False)(value)


def _infer_fields(values: Mapping[str, Any]) -> list[dict[str, Any]]:
    def kind(value: Any) -> str:
        if isinstance(value, bool): return "bool"
        if isinstance(value, int): return "int"
        if isinstance(value, float): return "float"
        if isinstance(value, list): return "array"
        if isinstance(value, Mapping): return "struct"
        return "string"
    return [{"name": str(name), "type": kind(value), "required": False, "default": deepcopy(value), "description": "Imported field"} for name, value in values.items()]


__all__ = [
    "COMPONENT_TYPES", "FIELD_TYPES", "GAMEPLAY_FOUNDATION_RUNTIME_SCHEMA", "GAMEPLAY_FOUNDATION_SCHEMA",
    "GAMEPLAY_FOUNDATION_TYPES", "GameplayFoundationIssue", "GameplayFoundationService",
    "character_definition_defaults", "component_archetype_defaults", "data_asset_defaults", "data_schema_defaults",
    "data_table_defaults", "defaults_for", "enum_defaults", "project_settings_defaults", "validate_foundation_asset",
]
