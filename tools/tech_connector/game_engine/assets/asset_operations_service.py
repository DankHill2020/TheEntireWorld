"""Reference-safe project asset creation, import, and relocation operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable

from .asset_database_service import AssetDatabase, AssetRecord
from .asset_metadata_service import asset_metadata_path, read_asset_metadata, write_asset_metadata
from .asset_schema_service import merge_asset_properties, merge_import_settings
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry


@dataclass(frozen=True)
class AssetOperationReceipt:
    operation: str
    asset_id: str
    type_id: str
    source_path: str
    destination_path: str
    previous_paths: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetReferenceFixupReceipt:
    asset_id: str
    current_path: str
    aliases: tuple[str, ...]
    scanned_assets: int
    updated_assets: tuple[str, ...]
    replacements: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetReferenceReplacementPlan:
    asset_id: str
    replacement_asset_id: str
    referencers: tuple[str, ...]
    authored_replacements: int
    blockers: tuple[str, ...] = ()

    @property
    def can_execute(self) -> bool:
        return bool(self.referencers) and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "can_execute": self.can_execute}


@dataclass(frozen=True)
class AssetReferenceReplacementReceipt:
    asset_id: str
    replacement_asset_id: str
    updated_assets: tuple[str, ...]
    authored_replacements: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetDeleteReceipt:
    asset_id: str
    type_id: str
    original_path: str
    trash_path: str
    replaced_referencers: tuple[str, ...] = ()
    replacement_asset_id: str = ""
    recoverable: bool = True


@dataclass(frozen=True)
class AssetValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class AssetValidationReport:
    asset_id: str
    valid: bool
    issues: tuple[AssetValidationIssue, ...]


class AssetInUseError(ValueError):
    def __init__(self, asset_id: str, referencers: tuple[str, ...]) -> None:
        self.asset_id = str(asset_id)
        self.referencers = tuple(referencers)
        super().__init__(
            f"Asset is used by {len(self.referencers)} asset(s). Choose a replacement or cancel deletion."
        )


class AssetImportCancelled(RuntimeError):
    """Raised when an import is cancelled before its atomic destination commit."""


class AssetOperationsService:
    def __init__(
        self,
        project_root: str | Path,
        database: AssetDatabase,
        registry: AssetTypeRegistry | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self._undo_stack: list[tuple[str, Callable[[], Any]]] = []
        self._redirector_path = self.project_root / ".tech_connector" / "asset_redirectors.json"

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def undo_label(self) -> str:
        return self._undo_stack[-1][0] if self._undo_stack else ""

    def undo_last(self) -> Any:
        if not self._undo_stack:
            raise RuntimeError("There is no asset operation to undo.")
        _label, callback = self._undo_stack.pop()
        return callback()

    @contextmanager
    def undo_group(self, label: str):
        """Collapse child operations into one undo and roll all of them back on failure."""
        start = len(self._undo_stack)
        try:
            yield
        except Exception:
            entries = self._undo_stack[start:]; del self._undo_stack[start:]
            for _child_label, callback in reversed(entries):
                callback()
            raise
        entries = self._undo_stack[start:]; del self._undo_stack[start:]
        if entries:
            callbacks = tuple(callback for _child_label, callback in entries)
            self._remember_undo(str(label), lambda: tuple(callback() for callback in reversed(callbacks)))

    def create_asset(
        self,
        type_id: str,
        name: str,
        *,
        folder: str | Path = "Assets",
        properties: dict[str, Any] | None = None,
    ) -> AssetOperationReceipt:
        descriptor = self.registry.require(type_id)
        if not descriptor.creatable:
            raise ValueError(f"{descriptor.display_name} assets must be imported.")
        extension = descriptor.extensions[0] if descriptor.extensions else ".tcasset"
        safe_name = _safe_asset_name(name)
        destination = self._project_destination(folder, safe_name + extension)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if descriptor.type_id == "tc.level":
            from tech_connector.game_engine.scene.federated_scene_service import (
                FederatedSceneDocument,
                save_federated_scene,
            )

            save_federated_scene(destination, FederatedSceneDocument(name=safe_name))
        else:
            payload = {
                "schema": f"tech_connector.asset.{descriptor.type_id.removeprefix('tc.')}.v1",
                "type_id": descriptor.type_id,
                "name": safe_name,
                "properties": merge_asset_properties(descriptor.type_id, properties),
            }
            destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        record = self.database.register_asset(destination, descriptor.type_id)
        self._remember_undo(
            f"Create {safe_name}",
            lambda value=record.asset_id: self.delete_asset(value, _record_undo=False),
        )
        return AssetOperationReceipt(
            "create", record.asset_id, descriptor.type_id, "", str(destination), (),
            f"Created {descriptor.display_name} '{safe_name}'.",
        )

    def import_asset(
        self,
        source_path: str | Path,
        *,
        folder: str | Path = "Assets",
        type_id: str = "",
        importer_settings: dict[str, Any] | None = None,
        conflict_policy: str = "error",
        cancellation_event: Any | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> AssetOperationReceipt:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        descriptor = self.registry.require(type_id) if type_id else self.registry.infer(source)
        if descriptor is None:
            raise ValueError(f"No registered importer recognizes '{source.suffix}'.")
        if not descriptor.importable:
            raise ValueError(f"{descriptor.display_name} does not support source import.")
        resolved_importer_settings = merge_import_settings(descriptor.type_id, importer_settings)
        destination = self._project_destination(folder, source.name)
        policy = str(conflict_policy or "error").strip().casefold()
        if policy not in {"error", "rename", "replace", "skip"}:
            raise ValueError(f"Unknown import conflict policy: {conflict_policy}")
        if destination.exists() and policy == "rename":
            destination = _unique_copy_path(destination)
        if destination.exists() and policy == "skip":
            existing = self.database.asset_for_path(destination)
            return AssetOperationReceipt(
                "skip_import", existing.asset_id if existing else "",
                existing.asset_type if existing else descriptor.type_id,
                str(source), str(destination), (), f"Skipped {source.name}; destination already exists.",
            )
        replacing = self.database.asset_for_path(destination) if destination.exists() and policy == "replace" else None
        if destination.exists() and policy == "error":
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_cancellable(
            source, destination, cancellation_event=cancellation_event,
            progress_callback=progress_callback,
        )
        record = self.database.register_asset(
            destination,
            descriptor.type_id,
            asset_id=replacing.asset_id if replacing else "",
            metadata={
                **(replacing.metadata if replacing else {}),
                "import_source": str(source),
                "import_source_modified_ns": source.stat().st_mtime_ns,
                "importer_settings": resolved_importer_settings,
            },
            dependencies=self.database.dependency_edges(replacing.asset_id) if replacing else (),
        )
        metadata = read_asset_metadata(destination)
        write_asset_metadata(
            destination,
            asset_id=record.asset_id,
            type_id=descriptor.type_id,
            importer=f"builtin:{descriptor.type_id}",
            importer_settings=resolved_importer_settings,
        )
        self._remember_undo(
            f"Import {source.name}",
            lambda value=record.asset_id: self.delete_asset(value, _record_undo=False),
        )
        return AssetOperationReceipt(
            "import", record.asset_id, descriptor.type_id, str(source), str(destination), (),
            f"{'Replaced' if replacing else 'Imported'} {source.name} as {descriptor.display_name}.",
        )

    def move_asset(
        self, asset_id: str, destination: str | Path, *, _record_undo: bool = True
    ) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        source = record.source_path.resolve()
        target = self._resolve_project_path(destination)
        if target.is_dir() or not target.suffix:
            target = target / source.name
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata = read_asset_metadata(source)
        previous_paths = list(metadata.get("previous_paths") or ())
        previous_paths.append(self._project_relative(source))
        source_sidecar = asset_metadata_path(source)
        shutil.move(str(source), str(target))
        target_sidecar = asset_metadata_path(target)
        if source_sidecar.is_file():
            shutil.move(str(source_sidecar), str(target_sidecar))
        write_asset_metadata(
            target,
            asset_id=record.asset_id,
            type_id=record.asset_type,
            importer=str(metadata.get("importer") or ""),
            importer_settings=dict(metadata.get("importer_settings") or {}),
            previous_paths=previous_paths,
        )
        updated = self.database.register_asset(
            target,
            record.asset_type,
            asset_id=record.asset_id,
            metadata={**record.metadata, "previous_paths": previous_paths},
            dependencies=self.database.dependency_edges(record.asset_id),
        )
        self._write_redirector(self._project_relative(source), updated.asset_id, self._project_relative(target))
        if _record_undo:
            self._remember_undo(
                f"Move {source.name}",
                lambda value=updated.asset_id, prior=source: self.move_asset(
                    value, prior, _record_undo=False
                ),
            )
        return AssetOperationReceipt(
            "move", updated.asset_id, updated.asset_type, str(source), str(target), tuple(previous_paths),
            f"Moved {source.name}; UUID references remain valid.",
        )

    def rename_asset(self, asset_id: str, new_name: str) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        safe_name = _safe_asset_name(new_name)
        suffix = "".join(record.source_path.suffixes)
        return self.move_asset(asset_id, record.source_path.with_name(safe_name + suffix))

    def duplicate_asset(
        self, asset_id: str, *, destination: str | Path | None = None
    ) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        target = self._resolve_project_path(destination) if destination is not None else _unique_copy_path(record.source_path)
        if target.is_dir() or not target.suffix:
            target = _unique_copy_path(target / record.source_path.name)
        if target.exists():
            raise FileExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record.source_path, target)
        duplicated = self.database.register_asset(
            target,
            record.asset_type,
            metadata={**record.metadata, "duplicated_from": record.asset_id},
            dependencies=self.database.dependency_edges(record.asset_id),
        )
        self._remember_undo(
            f"Duplicate {record.source_path.name}",
            lambda value=duplicated.asset_id: self.delete_asset(value, _record_undo=False),
        )
        return AssetOperationReceipt(
            "duplicate", duplicated.asset_id, duplicated.asset_type, str(record.source_path), str(target), (),
            f"Duplicated {record.source_path.name} with a new UUID.",
        )

    def reimport_asset(self, asset_id: str) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        import_source = Path(str(record.metadata.get("import_source") or "")).expanduser()
        if not import_source.is_file():
            raise FileNotFoundError(
                f"The original import source is unavailable: {import_source or '(not recorded)'}"
            )
        destination = record.source_path.resolve()
        previous_payload = destination.read_bytes()
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.reimport")
        shutil.copy2(import_source, temporary)
        os.replace(temporary, destination)
        updated = self.database.register_asset(
            destination,
            record.asset_type,
            asset_id=record.asset_id,
            metadata={**record.metadata, "import_source_modified_ns": import_source.stat().st_mtime_ns},
            dependencies=self.database.dependency_edges(record.asset_id),
        )
        self._remember_undo(
            f"Reimport {destination.name}",
            lambda target=destination, payload=previous_payload, value=record.asset_id: self._restore_payload(
                target, payload, value
            ),
        )
        return AssetOperationReceipt(
            "reimport", updated.asset_id, updated.asset_type, str(import_source), str(destination), (),
            f"Reimported {destination.name} and invalidated affected derived data.",
        )

    def set_asset_tags(
        self, asset_id: str, *, add: tuple[str, ...] = (), remove: tuple[str, ...] = (),
        _record_undo: bool = True,
    ) -> AssetOperationReceipt:
        record = self._require_asset(asset_id); previous = dict(record.metadata)
        tags = {str(value).strip() for value in previous.get("tags") or () if str(value).strip()}
        tags.update(str(value).strip() for value in add if str(value).strip())
        tags.difference_update(str(value).strip() for value in remove if str(value).strip())
        metadata = {**previous, "tags": sorted(tags)}
        updated = self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata=metadata, dependencies=self.database.dependency_edges(record.asset_id),
        )
        if _record_undo:
            self._remember_undo(
                f"Tag {record.source_path.name}",
                lambda value=record.asset_id, state=previous: self._restore_metadata(value, state),
            )
        return AssetOperationReceipt(
            "tag", updated.asset_id, updated.asset_type, str(updated.source_path), str(updated.source_path), (),
            f"Updated tags for {updated.source_path.name}.",
        )

    def delete_asset(
        self,
        asset_id: str,
        *,
        replacement_asset_id: str = "",
        _record_undo: bool = True,
    ) -> AssetDeleteReceipt:
        record = self._require_asset(asset_id)
        referencers = self.database.referencers(asset_id)
        replacement = self._require_asset(replacement_asset_id) if replacement_asset_id else None
        if replacement is not None and replacement.asset_id == record.asset_id:
            raise ValueError("The replacement must be a different asset.")
        if replacement is not None and replacement.asset_type != record.asset_type:
            raise ValueError("Replacement assets must have the same registered type.")
        if referencers and replacement is None:
            raise AssetInUseError(record.asset_id, referencers)

        outgoing_edges = self.database.dependency_edges(record.asset_id)
        referencer_snapshots: dict[str, tuple[tuple[tuple[str, str], ...], bytes | None]] = {}
        for owner_id in referencers:
            owner = self._require_asset(owner_id)
            payload = owner.source_path.read_bytes() if _is_json_authored_asset(owner.source_path) else None
            referencer_snapshots[owner_id] = (self.database.dependency_edges(owner_id), payload)
            assert replacement is not None
            self.database.replace_dependency(owner_id, record.asset_id, replacement.asset_id)
            if payload is not None:
                replacement_values = {
                    record.asset_id.casefold(): replacement.asset_id,
                    self._project_relative(record.source_path).casefold(): self._project_relative(replacement.source_path),
                    str(record.source_path).replace("\\", "/").casefold(): str(replacement.source_path).replace("\\", "/"),
                }
                try:
                    authored = json.loads(payload.decode("utf-8"))
                    authored, count = _replace_legacy_paths(authored, replacement_values)
                    if count:
                        owner.source_path.write_text(
                            json.dumps(authored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                        )
                        self.database.register_asset(
                            owner.source_path, owner.asset_type, asset_id=owner.asset_id,
                            metadata=owner.metadata, dependencies=self.database.dependency_edges(owner.asset_id),
                        )
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass

        trash_directory = self.project_root / ".tech_connector" / "trash" / record.asset_id / str(time.time_ns())
        trash_directory.mkdir(parents=True, exist_ok=False)
        trash_path = trash_directory / record.source_path.name
        sidecar = asset_metadata_path(record.source_path)
        trash_sidecar = asset_metadata_path(trash_path)
        shutil.move(str(record.source_path), str(trash_path))
        if sidecar.is_file():
            shutil.move(str(sidecar), str(trash_sidecar))
        self.database.unregister_asset(record.asset_id)
        receipt = AssetDeleteReceipt(
            record.asset_id, record.asset_type, str(record.source_path), str(trash_path),
            tuple(referencers), replacement.asset_id if replacement else "", True,
        )
        if _record_undo:
            self._remember_undo(
                f"Delete {record.source_path.name}",
                lambda deleted=record, trashed=trash_path, edges=outgoing_edges,
                snapshots=referencer_snapshots: self._restore_deleted(deleted, trashed, edges, snapshots),
            )
        return receipt

    def plan_reference_replacement(
        self, asset_id: str, replacement_asset_id: str, *, owner_asset_ids: tuple[str, ...] = (),
    ) -> AssetReferenceReplacementPlan:
        target = self._require_asset(asset_id)
        replacement = self._require_asset(replacement_asset_id)
        blockers: list[str] = []
        if target.asset_id == replacement.asset_id:
            blockers.append("The replacement must be a different asset.")
        if target.asset_type != replacement.asset_type:
            blockers.append("Replacement assets must have the same registered type.")
        available = set(self.database.referencers(target.asset_id))
        owners = tuple(dict.fromkeys(str(value) for value in owner_asset_ids)) if owner_asset_ids else tuple(sorted(available))
        unknown = sorted(set(owners) - available)
        if unknown:
            blockers.append("These assets do not reference the target: " + ", ".join(unknown))
        replacement_closure = set(self.database.dependency_closure((replacement.asset_id,)))
        risks = sorted(owner for owner in owners if owner == replacement.asset_id or owner in replacement_closure)
        if risks:
            blockers.append("Replacement would create a dependency cycle for: " + ", ".join(risks))
        replacements = 0
        values = {
            target.asset_id.casefold(): replacement.asset_id,
            self._project_relative(target.source_path).casefold(): self._project_relative(replacement.source_path),
            str(target.source_path).replace("\\", "/").casefold(): str(replacement.source_path).replace("\\", "/"),
        }
        for owner_id in owners:
            owner = self.database.asset(owner_id)
            if owner is None or not _is_json_authored_asset(owner.source_path):
                continue
            try:
                authored = json.loads(owner.source_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            _updated, count = _replace_legacy_paths(authored, values)
            replacements += count
        return AssetReferenceReplacementPlan(
            target.asset_id, replacement.asset_id, owners, replacements, tuple(blockers),
        )

    def replace_asset_references(
        self, asset_id: str, replacement_asset_id: str, *, owner_asset_ids: tuple[str, ...] = (),
        _record_undo: bool = True,
    ) -> AssetReferenceReplacementReceipt:
        plan = self.plan_reference_replacement(
            asset_id, replacement_asset_id, owner_asset_ids=owner_asset_ids,
        )
        if plan.blockers:
            raise ValueError(" ".join(plan.blockers))
        target = self._require_asset(plan.asset_id)
        replacement = self._require_asset(plan.replacement_asset_id)
        snapshots: dict[str, tuple[tuple[tuple[str, str], ...], bytes | None]] = {}
        updated: list[str] = []
        replacements = 0
        values = {
            target.asset_id.casefold(): replacement.asset_id,
            self._project_relative(target.source_path).casefold(): self._project_relative(replacement.source_path),
            str(target.source_path).replace("\\", "/").casefold(): str(replacement.source_path).replace("\\", "/"),
        }
        try:
            for owner_id in plan.referencers:
                owner = self._require_asset(owner_id)
                payload = owner.source_path.read_bytes() if _is_json_authored_asset(owner.source_path) else None
                snapshots[owner_id] = (self.database.dependency_edges(owner_id), payload)
                if not self.database.replace_dependency(owner_id, target.asset_id, replacement.asset_id):
                    continue
                if payload is not None:
                    try:
                        authored = json.loads(payload.decode("utf-8"))
                        authored, count = _replace_legacy_paths(authored, values)
                        replacements += count
                        if count:
                            owner.source_path.write_text(
                                json.dumps(authored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                            )
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                self.database.register_asset(
                    owner.source_path, owner.asset_type, asset_id=owner.asset_id,
                    metadata=owner.metadata, dependencies=self.database.dependency_edges(owner.asset_id),
                )
                updated.append(owner_id)
        except Exception:
            self._restore_reference_snapshots(snapshots)
            raise
        if _record_undo and snapshots:
            self._remember_undo(
                f"Replace references to {target.source_path.name}",
                lambda states=snapshots: self._restore_reference_snapshots(states),
            )
        return AssetReferenceReplacementReceipt(
            target.asset_id, replacement.asset_id, tuple(updated), replacements,
        )

    def validate_asset(self, asset_id: str) -> AssetValidationReport:
        record = self._require_asset(asset_id)
        issues: list[AssetValidationIssue] = []
        descriptor = self.registry.descriptor(record.asset_type)
        if descriptor is None:
            issues.append(AssetValidationIssue("error", "unregistered_type", f"Unknown type: {record.asset_type}"))
        if not record.source_path.is_file():
            issues.append(AssetValidationIssue("error", "missing_source", "The authored source file is missing."))
        try:
            metadata = read_asset_metadata(record.source_path)
        except ValueError as exc:
            issues.append(AssetValidationIssue("error", "invalid_metadata", str(exc)))
            metadata = {}
        if not metadata:
            issues.append(AssetValidationIssue("warning", "missing_metadata", "Persistent UUID sidecar is missing."))
        elif metadata.get("asset_id") != record.asset_id:
            issues.append(AssetValidationIssue("error", "identity_mismatch", "Database and sidecar UUIDs differ."))
        for dependency_id in self.database.dependencies(record.asset_id):
            dependency = self.database.asset(dependency_id)
            if dependency is None or dependency.status != "ready":
                issues.append(AssetValidationIssue("error", "missing_dependency", dependency_id))
        import_source = str(record.metadata.get("import_source") or "")
        if import_source and not Path(import_source).is_file():
            issues.append(AssetValidationIssue("warning", "missing_import_source", import_source))
        if record.asset_type == "tc.cloth" and record.source_path.is_file():
            from .cloth_asset_service import validate_cloth_properties

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                cloth_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                cloth_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_cloth", "Cloth source is not valid authored JSON."))
            for issue in validate_cloth_properties(cloth_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type in {"tc.physics_asset", "tc.physics_constraint"} and record.source_path.is_file():
            from .physics_asset_service import validate_constraint_properties, validate_physics_asset_properties

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                physics_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                physics_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_physics_asset", "Physics source is not valid authored JSON."))
            validator = validate_physics_asset_properties if record.asset_type == "tc.physics_asset" else validate_constraint_properties
            for issue in validator(physics_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type in {"tc.skeletal_mesh", "tc.skin_binding"} and record.source_path.is_file():
            from .character_asset_service import validate_character_lods, validate_skin_binding_properties

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                character_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                character_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_character_asset", "Character source is not valid authored JSON."))
            validator = validate_character_lods if record.asset_type == "tc.skeletal_mesh" else validate_skin_binding_properties
            for issue in validator(character_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type in {"tc.control_rig", "tc.ik_rig", "tc.ik_retargeter"} and record.source_path.is_file():
            from .rig_asset_service import (
                validate_control_rig_properties, validate_ik_retargeter_properties, validate_ik_rig_properties,
            )

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                rig_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                rig_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_rig_asset", "Rig source is not valid authored JSON."))
            validator = {"tc.control_rig": validate_control_rig_properties, "tc.ik_rig": validate_ik_rig_properties,
                         "tc.ik_retargeter": validate_ik_retargeter_properties}[record.asset_type]
            for issue in validator(rig_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type == "tc.geometry_optimization_profile" and record.source_path.is_file():
            from .geometry_optimization_service import validate_geometry_optimization_profile

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                optimization_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                optimization_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_geometry_optimization", "Geometry optimization source is not valid authored JSON."))
            for issue in validate_geometry_optimization_profile(optimization_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type in {"tc.groom", "tc.groom_binding", "tc.hair_material"} and record.source_path.is_file():
            from .groom_asset_service import (
                validate_groom_binding_properties, validate_groom_properties, validate_hair_material_properties,
            )

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                groom_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                groom_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_groom_asset", "Groom source is not valid authored JSON."))
            validator = {"tc.groom": validate_groom_properties, "tc.groom_binding": validate_groom_binding_properties,
                         "tc.hair_material": validate_hair_material_properties}[record.asset_type]
            for issue in validator(groom_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type == "tc.level_sequence" and record.source_path.is_file():
            from .sequence_asset_service import SequenceAssetService

            try:
                json.loads(record.source_path.read_text(encoding="utf-8"))
                sequence_issues = SequenceAssetService(self.project_root, self.database).validate(record.asset_id)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                sequence_issues = ()
                issues.append(AssetValidationIssue("error", "invalid_level_sequence", "Level Sequence source is not valid authored JSON."))
            for issue in sequence_issues:
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type in {
            "tc.terrain", "tc.foliage_type", "tc.biome", "tc.navigation_mesh",
            "tc.lighting_scenario", "tc.data_layer", "tc.hlod_layer", "tc.world_partition",
        } and record.source_path.is_file():
            from .world_asset_service import validate_world_asset

            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                world_properties = dict(payload.get("properties") or {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                world_properties = {}
                issues.append(AssetValidationIssue("error", "invalid_world_asset", "World asset source is not valid authored JSON."))
            for issue in validate_world_asset(record.asset_type, world_properties):
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        if record.asset_type == "tc.procedural_graph" and record.source_path.is_file():
            from .procedural_graph_asset_service import ProceduralGraphAssetService

            try:
                procedural_issues = ProceduralGraphAssetService(self.project_root, self.database).validate(record.asset_id)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                procedural_issues = ()
                issues.append(AssetValidationIssue("error", "invalid_procedural_graph", str(exc)))
            for issue in procedural_issues:
                issues.append(AssetValidationIssue(issue.severity, issue.code, issue.message))
        return AssetValidationReport(record.asset_id, not any(i.severity == "error" for i in issues), tuple(issues))

    def validate_all(self) -> tuple[AssetValidationReport, ...]:
        return tuple(self.validate_asset(record.asset_id) for record in self.database.list_assets())

    def move_assets(self, asset_ids: list[str] | tuple[str, ...], destination_folder: str | Path) -> tuple[AssetOperationReceipt, ...]:
        folder = self._resolve_project_path(destination_folder)
        identifiers = tuple(dict.fromkeys(asset_ids)); receipts: list[AssetOperationReceipt] = []
        with self.undo_group(f"Bulk Move ({len(identifiers)} assets)"):
            for asset_id in identifiers:
                receipts.append(self.move_asset(asset_id, folder))
        return tuple(receipts)

    def resolve_redirect(self, previous_path: str | Path) -> AssetRecord | None:
        key = str(previous_path).replace("\\", "/").casefold()
        entry = self._read_redirectors().get(key)
        return self.database.asset(str(entry.get("asset_id") or "")) if isinstance(entry, dict) else None

    def redirector_report(self) -> tuple[dict[str, Any], ...]:
        """Describe every recorded path redirect and whether it still resolves."""

        rows = []
        for previous_path, entry in sorted(self._read_redirectors().items()):
            asset_id = str(entry.get("asset_id") or "") if isinstance(entry, dict) else ""
            record = self.database.asset(asset_id) if asset_id else None
            rows.append({
                "previous_path": previous_path,
                "asset_id": asset_id,
                "current_path": str(entry.get("current_path") or "") if isinstance(entry, dict) else "",
                "resolved_path": self._project_relative(record.source_path) if record else "",
                "valid": bool(record and record.source_path.is_file()),
            })
        return tuple(rows)

    def repair_project_references(self, *, prune_stale_redirectors: bool = True) -> dict[str, Any]:
        """Repair all known legacy path aliases and optionally remove dead redirectors."""

        receipts = []
        for record in self.database.list_assets(status="ready"):
            metadata = read_asset_metadata(record.source_path)
            aliases = metadata.get("previous_paths") or record.metadata.get("previous_paths") or ()
            if aliases:
                receipts.append(self.fix_legacy_path_references(record.asset_id))
        redirectors = self._read_redirectors()
        scanned_redirectors = len(redirectors)
        stale = [
            key for key, entry in redirectors.items()
            if not isinstance(entry, dict) or self.database.asset(str(entry.get("asset_id") or "")) is None
        ]
        if prune_stale_redirectors and stale:
            for key in stale:
                redirectors.pop(key, None)
            self._save_redirectors(redirectors)
        return {
            "schema": "tech_connector.asset_reference_repair.v1",
            "scanned_redirectors": scanned_redirectors,
            "pruned_redirectors": len(stale) if prune_stale_redirectors else 0,
            "scanned_assets": sum(receipt.scanned_assets for receipt in receipts),
            "updated_assets": tuple(sorted({value for receipt in receipts for value in receipt.updated_assets})),
            "replacements": sum(receipt.replacements for receipt in receipts),
        }

    def reference_report(self, asset_id: str) -> dict[str, Any]:
        record = self._require_asset(asset_id)
        dependencies = [self.database.asset(value) for value in self.database.dependencies(asset_id)]
        referencers = [self.database.asset(value) for value in self.database.referencers(asset_id)]
        recursive = [self.database.asset(value) for value in self.database.referencers(asset_id, recursive=True)]

        def summary(value: AssetRecord | None) -> dict[str, str]:
            return {
                "asset_id": value.asset_id,
                "type_id": value.asset_type,
                "path": str(value.source_path),
            } if value is not None else {}

        return {
            "asset": summary(record),
            "dependencies": [summary(value) for value in dependencies if value is not None],
            "referencers": [summary(value) for value in referencers if value is not None],
            "recursive_referencers": [summary(value) for value in recursive if value is not None],
        }

    def fix_legacy_path_references(self, asset_id: str) -> AssetReferenceFixupReceipt:
        target = self._require_asset(asset_id)
        metadata = read_asset_metadata(target.source_path)
        aliases = list(metadata.get("previous_paths") or target.metadata.get("previous_paths") or ())
        current = self._project_relative(target.source_path)
        alias_map = {str(value).replace("\\", "/").casefold(): current for value in aliases if value}
        if not alias_map:
            return AssetReferenceFixupReceipt(asset_id, current, (), 0, (), 0)
        updated_assets: list[str] = []
        replacements = 0
        scanned = 0
        for record in self.database.list_assets(status="ready"):
            if record.asset_id == target.asset_id or not _is_json_authored_asset(record.source_path):
                continue
            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scanned += 1
            replaced_payload, count = _replace_legacy_paths(payload, alias_map)
            if count <= 0:
                continue
            record.source_path.write_text(
                json.dumps(replaced_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            edges = list(self.database.dependency_edges(record.asset_id))
            if target.asset_id not in {value for value, _kind in edges}:
                edges.append((target.asset_id, "legacy_path_fixup"))
            self.database.register_asset(
                record.source_path,
                record.asset_type,
                asset_id=record.asset_id,
                metadata=record.metadata,
                dependencies=edges,
            )
            updated_assets.append(record.asset_id)
            replacements += count
        return AssetReferenceFixupReceipt(
            target.asset_id,
            current,
            tuple(str(value) for value in aliases),
            scanned,
            tuple(updated_assets),
            replacements,
        )

    def _require_asset(self, asset_id: str) -> AssetRecord:
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown asset: {asset_id}")
        return record

    def _project_destination(self, folder: str | Path, filename: str) -> Path:
        return self._resolve_project_path(folder) / filename

    def _resolve_project_path(self, value: str | Path) -> Path:
        candidate = Path(value).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Asset destination must stay inside the project: {resolved}") from exc
        return resolved

    def _project_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path.resolve())

    def _remember_undo(self, label: str, callback: Callable[[], Any]) -> None:
        self._undo_stack.append((str(label), callback))
        del self._undo_stack[:-50]

    def _restore_payload(self, path: Path, payload: bytes, asset_id: str) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.undo")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        restored = self.database.register_asset(
            path, record.asset_type, asset_id=asset_id, metadata=record.metadata,
            dependencies=self.database.dependency_edges(asset_id),
        )
        return AssetOperationReceipt(
            "undo_reimport", restored.asset_id, restored.asset_type, "", str(path), (),
            f"Restored the previous content for {path.name}.",
        )

    def _restore_metadata(self, asset_id: str, metadata: dict[str, Any]) -> AssetOperationReceipt:
        record = self._require_asset(asset_id)
        restored = self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata=metadata, dependencies=self.database.dependency_edges(record.asset_id),
        )
        return AssetOperationReceipt(
            "undo_metadata", restored.asset_id, restored.asset_type, str(restored.source_path),
            str(restored.source_path), (), f"Restored metadata for {restored.source_path.name}.",
        )

    def _restore_deleted(
        self,
        record: AssetRecord,
        trash_path: Path,
        outgoing_edges: tuple[tuple[str, str], ...],
        referencer_snapshots: dict[str, tuple[tuple[tuple[str, str], ...], bytes | None]],
    ) -> AssetOperationReceipt:
        if record.source_path.exists():
            raise FileExistsError(record.source_path)
        record.source_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_path), str(record.source_path))
        trash_sidecar = asset_metadata_path(trash_path)
        if trash_sidecar.is_file():
            shutil.move(str(trash_sidecar), str(asset_metadata_path(record.source_path)))
        restored = self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata=record.metadata, dependencies=outgoing_edges,
        )
        for owner_id, (edges, payload) in referencer_snapshots.items():
            owner = self.database.asset(owner_id)
            if owner is None:
                continue
            if payload is not None:
                owner.source_path.write_bytes(payload)
            self.database.register_asset(
                owner.source_path, owner.asset_type, asset_id=owner.asset_id,
                metadata=owner.metadata, dependencies=edges,
            )
        return AssetOperationReceipt(
            "undo_delete", restored.asset_id, restored.asset_type, str(trash_path), str(record.source_path), (),
            f"Restored {record.source_path.name} from project trash.",
        )

    def _restore_reference_snapshots(
        self, snapshots: dict[str, tuple[tuple[tuple[str, str], ...], bytes | None]],
    ) -> tuple[str, ...]:
        restored = []
        for owner_id, (edges, payload) in snapshots.items():
            owner = self.database.asset(owner_id)
            if owner is None:
                continue
            if payload is not None:
                owner.source_path.write_bytes(payload)
            self.database.register_asset(
                owner.source_path, owner.asset_type, asset_id=owner.asset_id,
                metadata=owner.metadata, dependencies=edges,
            )
            restored.append(owner_id)
        return tuple(restored)

    def _read_redirectors(self) -> dict[str, dict[str, str]]:
        if not self._redirector_path.is_file():
            return {}
        try:
            payload = json.loads(self._redirector_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(payload.get("redirectors") or {}) if isinstance(payload, dict) else {}

    def _write_redirector(self, previous_path: str, asset_id: str, current_path: str) -> None:
        redirectors = self._read_redirectors()
        redirectors[str(previous_path).replace("\\", "/").casefold()] = {
            "asset_id": str(asset_id), "current_path": str(current_path),
        }
        self._save_redirectors(redirectors)

    def _save_redirectors(self, redirectors: dict[str, dict[str, str]]) -> None:
        self._redirector_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._redirector_path.with_name(f".{self._redirector_path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"schema": "tech_connector.asset_redirectors.v1", "redirectors": redirectors}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self._redirector_path)


def _safe_asset_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip()).strip("._")
    if not name:
        raise ValueError("Asset name must contain a letter or number.")
    return name


def _copy_file_cancellable(
    source: Path, destination: Path, *, cancellation_event: Any | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Copy in chunks and atomically publish only a fully completed import."""

    total = int(source.stat().st_size)
    completed = 0
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{time.time_ns()}.import")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while True:
                if cancellation_event is not None and cancellation_event.is_set():
                    raise AssetImportCancelled(f"Import cancelled: {source.name}")
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                completed += len(chunk)
                if progress_callback is not None:
                    progress_callback(completed, total)
            writer.flush()
            os.fsync(writer.fileno())
        if cancellation_event is not None and cancellation_event.is_set():
            raise AssetImportCancelled(f"Import cancelled: {source.name}")
        shutil.copystat(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _unique_copy_path(source: Path) -> Path:
    suffix = "".join(source.suffixes)
    stem = source.name[:-len(suffix)] if suffix else source.name
    candidate = source.with_name(f"{stem}_Copy{suffix}")
    index = 2
    while candidate.exists():
        candidate = source.with_name(f"{stem}_Copy_{index}{suffix}")
        index += 1
    return candidate


def _is_json_authored_asset(path: Path) -> bool:
    suffix = path.suffix.casefold()
    return suffix == ".json" or suffix.startswith(".tc")


def _replace_legacy_paths(value: Any, aliases: dict[str, str]) -> tuple[Any, int]:
    if isinstance(value, str):
        replacement = aliases.get(value.replace("\\", "/").casefold())
        return (replacement, 1) if replacement is not None else (value, 0)
    if isinstance(value, list):
        result = []
        count = 0
        for item in value:
            replaced, changes = _replace_legacy_paths(item, aliases)
            result.append(replaced)
            count += changes
        return result, count
    if isinstance(value, dict):
        result = {}
        count = 0
        for key, item in value.items():
            replaced, changes = _replace_legacy_paths(item, aliases)
            result[key] = replaced
            count += changes
        return result, count
    return value, 0
