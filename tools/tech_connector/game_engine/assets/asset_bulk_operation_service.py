"""Dry-run-first, transaction-grouped bulk asset operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .asset_database_service import AssetDatabase
from .asset_export_service import AssetExportService
from .asset_operations_service import AssetOperationsService
from .asset_production_service import AssetProductionService


BULK_ASSET_OPERATIONS = ("rename", "move", "tag", "reimport", "validate", "cook", "export")
_MUTATING_OPERATIONS = frozenset({"rename", "move", "tag", "reimport"})


@dataclass(frozen=True)
class BulkAssetPlanItem:
    asset_id: str
    type_id: str
    source_path: str
    destination_path: str
    revision: int
    state_token: str
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BulkAssetPlan:
    operation: str
    options: dict[str, Any]
    items: tuple[BulkAssetPlanItem, ...]
    executable: bool
    selected_count: int
    ready_count: int
    blocked_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.bulk_asset_plan.v1", "operation": self.operation,
            "options": dict(self.options), "items": [item.to_dict() for item in self.items],
            "executable": self.executable, "selected_count": self.selected_count,
            "ready_count": self.ready_count, "blocked_count": self.blocked_count,
        }


@dataclass(frozen=True)
class BulkAssetReceipt:
    operation: str
    asset_ids: tuple[str, ...]
    results: tuple[dict[str, Any], ...]
    undoable: bool
    undo_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.bulk_asset_receipt.v1", "operation": self.operation,
            "asset_ids": list(self.asset_ids), "results": [dict(row) for row in self.results],
            "undoable": self.undoable, "undo_label": self.undo_label,
        }


class BulkAssetOperationService:
    """Plan and execute consistent multi-asset operations with one undo boundary."""

    def __init__(
        self, project_root: str | Path, database: AssetDatabase, *,
        operations: AssetOperationsService | None = None,
        production: AssetProductionService | None = None,
        exports: AssetExportService | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = operations or AssetOperationsService(self.project_root, database)
        self.production = production or AssetProductionService(self.project_root, database)
        self.exports = exports or AssetExportService(self.project_root, database)

    def plan(
        self, operation: str, asset_ids: Iterable[str], *,
        options: Mapping[str, Any] | None = None,
    ) -> BulkAssetPlan:
        action = str(operation or "").strip().casefold()
        if action not in BULK_ASSET_OPERATIONS:
            raise ValueError(f"Unsupported bulk asset operation: {operation}")
        identifiers = tuple(dict.fromkeys(str(value) for value in asset_ids if str(value)))
        if not identifiers:
            raise ValueError("Select at least one asset.")
        settings = dict(options or {}); items: list[BulkAssetPlanItem] = []
        destinations: dict[str, str] = {}
        for index, asset_id in enumerate(identifiers, start=int(settings.get("start_index", 1))):
            record = self.database.asset(asset_id)
            if record is None:
                items.append(BulkAssetPlanItem(asset_id, "", "", "", 0, "", "blocked", "Asset is no longer registered."))
                continue
            source = record.source_path.resolve(); destination = source
            status, message = "ready", _action_summary(action)
            if not source.is_file():
                status, message = "blocked", "Authored source file is missing."
            elif action == "rename":
                suffix = "".join(source.suffixes); base = source.name[:-len(suffix)] if suffix else source.name
                name = _bulk_name(base, record.asset_type, index, settings)
                destination = source.with_name(name + suffix)
                if not name:
                    status, message = "blocked", "Generated name is empty."
                elif destination == source:
                    status, message = "blocked", "Generated name is unchanged."
                elif destination.exists():
                    status, message = "blocked", f"Destination already exists: {destination.name}"
            elif action == "move":
                folder = self._project_path(settings.get("destination_folder") or "Assets")
                destination = folder / source.name
                if destination == source:
                    status, message = "blocked", "Asset is already in this folder."
                elif destination.exists():
                    status, message = "blocked", f"Destination already exists: {destination.name}"
            elif action == "tag":
                add = _tags(settings.get("add_tags")); remove = _tags(settings.get("remove_tags"))
                if not add and not remove:
                    status, message = "blocked", "Add or remove at least one tag."
                else:
                    message = f"Add {len(add)} and remove {len(remove)} tag(s)."
            elif action == "reimport":
                import_source = Path(str(record.metadata.get("import_source") or "")).expanduser()
                if not import_source.is_file():
                    status, message = "blocked", "Original import source is unavailable."
                else:
                    message = f"Refresh from {import_source.name}."
            elif action == "export":
                if not str(settings.get("destination") or "").strip():
                    status, message = "blocked", "Choose an export destination."
                else:
                    message = f"Export for {str(settings.get('target') or 'generic').casefold()}."
            key = str(destination).casefold()
            if status == "ready" and action in {"rename", "move"}:
                if key in destinations and destinations[key] != asset_id:
                    status, message = "blocked", "Another selected asset resolves to the same destination."
                destinations[key] = asset_id
            items.append(BulkAssetPlanItem(
                asset_id, record.asset_type, str(source), str(destination), int(record.revision),
                _record_token(record), status, message,
            ))
        ready = sum(item.status == "ready" for item in items); blocked = len(items) - ready
        return BulkAssetPlan(action, settings, tuple(items), blocked == 0, len(items), ready, blocked)

    def execute(self, plan: BulkAssetPlan) -> BulkAssetReceipt:
        if not plan.executable:
            raise ValueError(f"Bulk {plan.operation} is blocked; resolve every preflight issue first.")
        for item in plan.items:
            record = self.database.asset(item.asset_id)
            if (record is None or int(record.revision) != item.revision
                    or str(record.source_path.resolve()) != item.source_path
                    or _record_token(record) != item.state_token):
                raise RuntimeError(f"Bulk plan is stale for asset {item.asset_id}; preview it again.")
        action = plan.operation; identifiers = tuple(item.asset_id for item in plan.items)
        label = f"Bulk {action.title()} ({len(identifiers)} assets)"
        if action in _MUTATING_OPERATIONS:
            results: list[dict[str, Any]] = []
            with self.operations.undo_group(label):
                for item in plan.items:
                    if action == "rename":
                        source = Path(item.source_path); destination = Path(item.destination_path)
                        suffix = "".join(source.suffixes); name = destination.name[:-len(suffix)] if suffix else destination.name
                        receipt = self.operations.rename_asset(item.asset_id, name)
                    elif action == "move":
                        receipt = self.operations.move_asset(item.asset_id, item.destination_path)
                    elif action == "tag":
                        receipt = self.operations.set_asset_tags(
                            item.asset_id, add=_tags(plan.options.get("add_tags")),
                            remove=_tags(plan.options.get("remove_tags")),
                        )
                    else:
                        receipt = self.operations.reimport_asset(item.asset_id)
                    results.append(_result_dict(receipt))
            return BulkAssetReceipt(action, identifiers, tuple(results), True, label)
        if action == "validate":
            results = tuple(_result_dict(self.operations.validate_asset(asset_id)) for asset_id in identifiers)
        elif action == "cook":
            receipt = self.production.cook_manifest(
                identifiers, platform=str(plan.options.get("platform") or "windows"),
                quality=str(plan.options.get("quality") or "high"),
            )
            results = (_result_dict(receipt),)
        else:
            receipt = self.exports.export_assets(
                identifiers, str(plan.options.get("destination")),
                target=str(plan.options.get("target") or "generic"),
                include_dependencies=bool(plan.options.get("include_dependencies", True)),
                require_ready=bool(plan.options.get("require_ready", False)),
            )
            results = (_result_dict(receipt),)
        return BulkAssetReceipt(action, identifiers, results, False, "")

    def _project_path(self, value: Any) -> Path:
        candidate = Path(str(value)).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()
        try:
            resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Bulk destination must stay inside the project: {resolved}") from exc
        return resolved


def _bulk_name(base: str, type_id: str, index: int, options: Mapping[str, Any]) -> str:
    find = str(options.get("find") or ""); replace = str(options.get("replace") or "")
    name = base.replace(find, replace) if find else base
    digits = max(1, min(12, int(options.get("digits", 3))))
    template = str(options.get("template") or "{prefix}{name}{suffix}")
    replacements = {
        "{prefix}": str(options.get("prefix") or ""), "{name}": name,
        "{suffix}": str(options.get("suffix") or ""), "{index}": f"{index:0{digits}d}",
        "{type}": str(type_id).removeprefix("tc."),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", template.strip()).strip("._")


def _tags(value: Any) -> tuple[str, ...]:
    rows = str(value or "").split(",") if isinstance(value, str) else value or ()
    return tuple(dict.fromkeys(str(row).strip() for row in rows if str(row).strip()))


def _action_summary(action: str) -> str:
    return {
        "validate": "Validate source, metadata, identity, and dependencies.",
        "cook": "Cook with the selected dependency closure.",
    }.get(action, action.title())


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {"result": str(value)}


def _record_token(record: Any) -> str:
    return json.dumps({
        "content_hash": str(record.content_hash), "metadata": dict(record.metadata),
        "dependencies": list(getattr(record, "dependencies", ()) or ()),
    }, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "BULK_ASSET_OPERATIONS", "BulkAssetOperationService", "BulkAssetPlan",
    "BulkAssetPlanItem", "BulkAssetReceipt",
]
