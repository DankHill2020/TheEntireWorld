"""Prefab authoring, inheritance, nested resolution, and runtime compilation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
import uuid

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


PREFAB_SCHEMA = "tech_connector.asset.prefab.v2"
PREFAB_RUNTIME_SCHEMA = "tech_connector.runtime.prefab.v1"


@dataclass(frozen=True)
class PrefabIssue:
    severity: str
    code: str
    message: str
    path: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PrefabResolution:
    asset_id: str
    entities: tuple[dict[str, Any], ...]
    exposed_properties: dict[str, Any]
    inheritance_chain: tuple[str, ...]
    nested_asset_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "entities": deepcopy(list(self.entities)),
            "exposed_properties": deepcopy(self.exposed_properties),
            "inheritance_chain": list(self.inheritance_chain),
            "nested_asset_ids": list(self.nested_asset_ids),
            "dependencies": list(self.dependencies),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class PrefabInstance:
    instance_id: str
    source_asset_id: str
    entities: tuple[dict[str, Any], ...]
    overrides: dict[str, Any]
    nested_asset_ids: tuple[str, ...]
    inheritance_chain: tuple[str, ...] = ()
    source_fingerprint: str = ""
    conflicts: tuple[str, ...] = ()

    @property
    def override_state(self) -> str:
        if self.conflicts:
            return "conflicted"
        return "overridden" if self.overrides else "inherited"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "source_asset_id": self.source_asset_id,
            "entities": deepcopy(list(self.entities)),
            "overrides": deepcopy(self.overrides),
            "nested_asset_ids": list(self.nested_asset_ids),
            "inheritance_chain": list(self.inheritance_chain),
            "source_fingerprint": self.source_fingerprint,
            "conflicts": list(self.conflicts),
            "override_state": self.override_state,
        }


class PrefabService:
    """Project-scoped prefab API shared by the editor, Python, and cooker."""

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create_from_entities(
        self, name: str, entities: Iterable[Mapping[str, Any]], *,
        folder: str | Path = "Assets/World",
        exposed_properties: Mapping[str, Any] | None = None,
        dependencies: Iterable[str] = (),
    ):
        receipt = self.operations.create_asset("tc.prefab", name, folder=folder)
        self._save(receipt.asset_id, {
            "prefab_version": 2,
            "entities": _normalize_entities(entities),
            "exposed_properties": deepcopy(dict(exposed_properties or {})),
            "base_prefab_id": "",
            "variant_overrides": {},
            "removed_entity_ids": [],
            "added_entities": [],
        }, extra_dependencies=dependencies)
        return receipt

    def create_variant(
        self, name: str, base_prefab_id: str, *,
        overrides: Mapping[str, Any] | None = None,
        added_entities: Iterable[Mapping[str, Any]] = (),
        removed_entity_ids: Iterable[str] = (),
        exposed_properties: Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/World/Variants",
    ):
        base = self.resolve(base_prefab_id)
        normalized_added = _normalize_entities(added_entities)
        inherited_ids = {str(item.get("entity_id") or "") for item in base.entities}
        for entity in normalized_added:
            original = str(entity.get("entity_id") or "")
            candidate, suffix = original, 2
            while candidate in inherited_ids:
                candidate, suffix = f"{original}_{suffix}", suffix + 1
            entity["entity_id"] = candidate
            inherited_ids.add(candidate)
        trial_entities = deepcopy(list(base.entities))
        removed = {str(value) for value in removed_entity_ids}
        trial_entities = [item for item in trial_entities if str(item.get("entity_id") or "") not in removed]
        trial_entities.extend(deepcopy(normalized_added))
        for path, value in dict(overrides or {}).items():
            _set_property_path(trial_entities, str(path), deepcopy(value))
        receipt = self.operations.create_asset("tc.prefab", name, folder=folder)
        self._save(receipt.asset_id, {
            "prefab_version": 2,
            "entities": [],
            "exposed_properties": deepcopy(dict(exposed_properties or {})),
            "base_prefab_id": str(base_prefab_id),
            "variant_overrides": deepcopy(dict(overrides or {})),
            "removed_entity_ids": sorted(removed),
            "added_entities": normalized_added,
        })
        self.resolve(receipt.asset_id)
        return receipt

    def resolve(self, prefab_asset_id: str, *, expand_nested: bool = False) -> PrefabResolution:
        return self._resolve(str(prefab_asset_id), expand_nested=expand_nested, stack=())

    def instantiate(
        self, prefab_asset_id: str, *, overrides: Mapping[str, Any] | None = None,
        expand_nested: bool = False,
    ) -> PrefabInstance:
        resolution = self.resolve(prefab_asset_id, expand_nested=expand_nested)
        resolved_overrides = deepcopy(dict(overrides or {}))
        entities = deepcopy(list(resolution.entities))
        for path, value in resolved_overrides.items():
            _set_property_path(entities, str(path), deepcopy(value))
        return PrefabInstance(
            f"tc.prefab_instance.{uuid.uuid4().hex}", resolution.asset_id, tuple(entities),
            resolved_overrides, resolution.nested_asset_ids, resolution.inheritance_chain,
            resolution.fingerprint,
        )

    def refresh_instance(self, instance: PrefabInstance, *, expand_nested: bool = False) -> PrefabInstance:
        """Hot-reload a source while retaining valid instance overrides."""
        resolution = self.resolve(instance.source_asset_id, expand_nested=expand_nested)
        entities = deepcopy(list(resolution.entities))
        conflicts: list[str] = []
        for path, value in instance.overrides.items():
            try:
                _set_property_path(entities, path, deepcopy(value))
            except (KeyError, IndexError, TypeError, ValueError):
                conflicts.append(path)
        return replace(
            instance, entities=tuple(entities), nested_asset_ids=resolution.nested_asset_ids,
            inheritance_chain=resolution.inheritance_chain, source_fingerprint=resolution.fingerprint,
            conflicts=tuple(sorted(conflicts)),
        )

    def revert_overrides(
        self, instance: PrefabInstance, paths: Iterable[str] | None = None, *,
        expand_nested: bool = False,
    ) -> PrefabInstance:
        selected = {str(value) for value in paths or ()}
        remaining = {path: deepcopy(value) for path, value in instance.overrides.items()
                     if selected and path not in selected}
        return self.instantiate(instance.source_asset_id, overrides=remaining, expand_nested=expand_nested)

    def apply_overrides(self, instance: PrefabInstance, paths: Iterable[str] | None = None) -> PrefabInstance:
        """Apply selected overrides to the source or its variant override layer."""
        _record, properties = self._load(instance.source_asset_id)
        selected = {str(value) for value in paths or ()}
        applying = {path: deepcopy(value) for path, value in instance.overrides.items()
                    if not selected or path in selected}
        if properties.get("base_prefab_id"):
            layer = dict(properties.get("variant_overrides") or {})
            layer.update(applying)
            properties["variant_overrides"] = layer
        else:
            entities = deepcopy(list(properties.get("entities") or ()))
            for path, value in applying.items():
                _set_property_path(entities, path, value)
            properties["entities"] = entities
        self._save(instance.source_asset_id, properties)
        remaining = {path: deepcopy(value) for path, value in instance.overrides.items() if path not in applying}
        return self.instantiate(instance.source_asset_id, overrides=remaining)

    def override_diff(self, instance: PrefabInstance) -> tuple[dict[str, Any], ...]:
        inherited = list(self.resolve(instance.source_asset_id).entities)
        rows: list[dict[str, Any]] = []
        for path, value in sorted(instance.overrides.items()):
            try:
                previous, state = _get_property_path(inherited, path), "modified"
            except (KeyError, IndexError, TypeError, ValueError):
                previous, state = None, "conflicted"
            rows.append({"path": path, "inherited": deepcopy(previous), "value": deepcopy(value), "state": state})
        return tuple(rows)

    def validate(self, prefab_asset_id: str) -> tuple[PrefabIssue, ...]:
        issues: list[PrefabIssue] = []
        try:
            _record, properties = self._load(prefab_asset_id)
        except (KeyError, ValueError) as exc:
            return (PrefabIssue("error", "invalid_source", str(exc), fix="Restore or recreate the Prefab asset."),)
        entity_ids: set[str] = set()
        authored = [*(properties.get("entities") or ()), *(properties.get("added_entities") or ())]
        for index, entity in enumerate(authored):
            path = f"entities.{index}"
            if not isinstance(entity, dict):
                issues.append(PrefabIssue("error", "invalid_entity", "Entity templates must be objects.", path, "Replace this entry with an entity object."))
                continue
            entity_id = str(entity.get("entity_id") or "")
            if entity_id in entity_ids:
                issues.append(PrefabIssue("error", "duplicate_entity_id", f"Duplicate entity_id: {entity_id}", path, "Assign a unique entity_id."))
            entity_ids.add(entity_id)
            nested_id = str(entity.get("prefab_asset_id") or entity.get("source_asset_id") or "")
            if nested_id:
                nested = self.database.asset(nested_id)
                if nested is None or nested.asset_type != "tc.prefab":
                    issues.append(PrefabIssue("error", "missing_nested_prefab", f"Nested Prefab is unavailable: {nested_id}", path, "Choose an existing Prefab asset."))
        try:
            resolved = self.resolve(prefab_asset_id, expand_nested=True)
            resolved_ids: set[str] = set()
            for entity in resolved.entities:
                entity_id = str(entity.get("entity_id") or "")
                if entity_id in resolved_ids:
                    issues.append(PrefabIssue(
                        "error", "duplicate_resolved_entity_id",
                        f"Resolved Prefab contains duplicate entity_id: {entity_id}",
                        fix="Rename the added entity so instance overrides remain unambiguous.",
                    ))
                resolved_ids.add(entity_id)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            message = str(exc)
            code = "prefab_cycle" if "cycle" in message.casefold() else "invalid_override"
            issues.append(PrefabIssue("error", code, message, fix="Repair the inheritance/nesting chain or override path."))
        return tuple(issues)

    def rebuild_dependencies(self, prefab_asset_id: str) -> tuple[tuple[str, str], ...]:
        _record, properties = self._load(prefab_asset_id)
        return self._save(prefab_asset_id, properties)

    def cook(self, prefab_asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        errors = [item.message for item in self.validate(prefab_asset_id) if item.severity == "error"]
        if errors:
            raise ValueError("; ".join(errors))
        resolution = self.resolve(prefab_asset_id, expand_nested=True)
        return self.database.store_derived(
            prefab_asset_id, f"prefab_runtime:{platform}:{quality}",
            compile_prefab_payload(resolution, platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality, "fingerprint": resolution.fingerprint,
                      "inheritance_depth": len(resolution.inheritance_chain)},
            extension=".tcprefabbin",
        )

    def _resolve(self, asset_id: str, *, expand_nested: bool, stack: tuple[str, ...]) -> PrefabResolution:
        if asset_id in stack:
            raise ValueError(f"Prefab inheritance or nesting cycle detected: {' -> '.join((*stack, asset_id))}")
        _record, properties = self._load(asset_id)
        next_stack = (*stack, asset_id)
        base_id = str(properties.get("base_prefab_id") or "")
        if base_id:
            base = self._resolve(base_id, expand_nested=False, stack=next_stack)
            entities, exposed = deepcopy(list(base.entities)), deepcopy(base.exposed_properties)
            chain = (*base.inheritance_chain, asset_id)
        else:
            entities, exposed, chain = _normalize_entities(properties.get("entities") or ()), {}, (asset_id,)
        removed = {str(value) for value in properties.get("removed_entity_ids") or ()}
        entities = [entity for entity in entities if str(entity.get("entity_id") or "") not in removed]
        entities.extend(_normalize_entities(properties.get("added_entities") or ()))
        for path, value in dict(properties.get("variant_overrides") or {}).items():
            _set_property_path(entities, str(path), deepcopy(value))
        exposed.update(deepcopy(dict(properties.get("exposed_properties") or {})))
        direct_nested: set[str] = set()
        recursive_nested: set[str] = set()
        for entity in entities:
            nested_id = str(entity.get("prefab_asset_id") or entity.get("source_asset_id") or "")
            if not nested_id:
                continue
            direct_nested.add(nested_id)
            if expand_nested:
                nested = self._resolve(nested_id, expand_nested=True, stack=next_stack)
                nested_entities = deepcopy(list(nested.entities))
                for path, value in dict(entity.get("prefab_overrides") or {}).items():
                    _set_property_path(nested_entities, str(path), deepcopy(value))
                entity["resolved_prefab_entities"] = nested_entities
                entity["prefab_fingerprint"] = nested.fingerprint
                recursive_nested.update(nested.nested_asset_ids)
        nested_ids = tuple(sorted(direct_nested | recursive_nested))
        dependencies = tuple(sorted(set(self.database.dependencies(asset_id)) | set(chain[:-1]) | set(nested_ids)))
        fingerprint = _fingerprint({"asset_id": asset_id, "entities": entities,
                                    "exposed_properties": exposed, "inheritance_chain": chain})
        return PrefabResolution(asset_id, tuple(entities), exposed, chain, nested_ids, dependencies, fingerprint)

    def _load(self, prefab_asset_id: str):
        record = self.database.asset(prefab_asset_id)
        if record is None or record.asset_type != "tc.prefab":
            raise KeyError(f"Unknown prefab asset: {prefab_asset_id}")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Prefab source is unreadable: {record.source_path}") from exc
        properties = payload.get("properties")
        if not isinstance(properties, dict) or not isinstance(properties.get("entities"), list):
            raise ValueError(f"Prefab is missing an entity template: {record.source_path}")
        return record, _migrate_properties(properties)

    def _save(
        self, prefab_asset_id: str, properties: Mapping[str, Any], *,
        extra_dependencies: Iterable[str] = (),
    ) -> tuple[tuple[str, str], ...]:
        record = self.database.asset(prefab_asset_id)
        if record is None or record.asset_type != "tc.prefab":
            raise KeyError(f"Unknown prefab asset: {prefab_asset_id}")
        clean = _migrate_properties(properties)
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        payload["schema"], payload["properties"] = PREFAB_SCHEMA, clean
        _atomic_json_write(record.source_path, payload)
        edges = [
            edge for edge in _dependency_edges(clean, extra_dependencies)
            if self.database.asset(edge[0]) is not None
        ]
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id,
                                     metadata=record.metadata, dependencies=edges)
        return tuple(edges)


def compile_prefab_payload(
    prefab: PrefabResolution | Mapping[str, Any], *, platform: str = "desktop", quality: str = "high",
) -> bytes:
    """Compile a fully resolved Prefab into deterministic runtime JSON."""
    resolved = prefab.to_dict() if isinstance(prefab, PrefabResolution) else deepcopy(dict(prefab))
    payload = {
        "schema": PREFAB_RUNTIME_SCHEMA, "platform": str(platform), "quality": str(quality),
        "asset_id": str(resolved.get("asset_id") or ""),
        "fingerprint": str(resolved.get("fingerprint") or _fingerprint(resolved)),
        "inheritance_chain": list(resolved.get("inheritance_chain") or ()),
        "dependencies": list(resolved.get("dependencies") or ()),
        "exposed_properties": deepcopy(dict(resolved.get("exposed_properties") or {})),
        "entities": deepcopy(list(resolved.get("entities") or ())),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _migrate_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(properties))
    result["prefab_version"] = 2
    result["entities"] = _normalize_entities(result.get("entities") or ())
    result["exposed_properties"] = deepcopy(dict(result.get("exposed_properties") or {}))
    result["base_prefab_id"] = str(result.get("base_prefab_id") or "")
    result["variant_overrides"] = deepcopy(dict(result.get("variant_overrides") or {}))
    result["removed_entity_ids"] = [str(value) for value in result.get("removed_entity_ids") or ()]
    result["added_entities"] = _normalize_entities(result.get("added_entities") or ())
    return result


def _normalize_entities(entities: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, source in enumerate(entities):
        if not isinstance(source, Mapping):
            raise ValueError(f"Prefab entity {index} must be an object.")
        entity = deepcopy(dict(source))
        entity_id = str(entity.get("entity_id") or "").strip()
        if not entity_id:
            label = re.sub(r"[^a-zA-Z0-9_]+", "_", str(entity.get("name") or "Entity")).strip("_") or "Entity"
            entity_id = f"{label}_{index}"
        candidate, suffix = entity_id, 2
        while candidate in used:
            candidate, suffix = f"{entity_id}_{suffix}", suffix + 1
        entity["entity_id"] = candidate
        used.add(candidate)
        result.append(entity)
    return result


def _dependency_edges(properties: Mapping[str, Any], extra: Iterable[str]) -> list[tuple[str, str]]:
    edges: dict[str, str] = {str(value): "prefab_reference" for value in extra if str(value)}
    base_id = str(properties.get("base_prefab_id") or "")
    if base_id:
        edges[base_id] = "base_prefab"
    for entity in [*(properties.get("entities") or ()), *(properties.get("added_entities") or ())]:
        if not isinstance(entity, Mapping):
            continue
        nested_id = str(entity.get("prefab_asset_id") or entity.get("source_asset_id") or "")
        if nested_id:
            edges[nested_id] = "nested_prefab"
        for value in _asset_references(entity):
            edges.setdefault(value, "component_asset")
    return sorted(edges.items())


def _asset_references(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            name = str(child_key)
            if (name.endswith("_asset_id") or name == "asset_id") and isinstance(child, str) and child:
                found.add(child)
            else:
                found.update(_asset_references(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_asset_references(child))
    return found


def _path_parts(path: str) -> list[str]:
    return [part for part in str(path).replace("[", ".").replace("]", "").split(".") if part]


def _entity_index(entities: list[Any], selector: str) -> int:
    try:
        return int(selector)
    except ValueError:
        for index, entity in enumerate(entities):
            if isinstance(entity, Mapping) and str(entity.get("entity_id") or "") == selector:
                return index
    raise KeyError(f"Unknown Prefab entity selector: {selector}")


def _get_property_path(root: list[dict[str, Any]], path: str) -> Any:
    parts = _path_parts(path)
    if len(parts) < 2:
        raise ValueError(f"Prefab override paths must identify an entity and property: {path}")
    current: Any = root
    for part in parts:
        if isinstance(current, list):
            current = current[_entity_index(current, part) if current is root else int(part)]
        elif isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Prefab override path does not exist: {path}")
    return deepcopy(current)


def _set_property_path(root: list[dict[str, Any]], path: str, value: Any) -> None:
    parts = _path_parts(path)
    if len(parts) < 2:
        raise ValueError(f"Prefab override paths must identify an entity and property: {path}")
    current: Any = root
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[_entity_index(current, part) if current is root else int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Prefab override path does not exist: {path}")
    final = parts[-1]
    if isinstance(current, list):
        current[int(final)] = value
    elif isinstance(current, dict) and final in current:
        current[final] = value
    else:
        raise KeyError(f"Prefab override path does not exist: {path}")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
