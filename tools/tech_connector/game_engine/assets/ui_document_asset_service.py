"""Authored UI documents and deterministic responsive layout previews."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService, AssetOperationReceipt, AssetValidationIssue


WIDGET_TYPES = frozenset({"panel", "text", "button", "image"})


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pair(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    return (
        isinstance(value, (list, tuple)) and len(value) == 2
        and all(_number(part) and (minimum is None or part >= minimum)
                and (maximum is None or part <= maximum) for part in value)
    )


def validate_ui_document(values: Mapping[str, Any]) -> tuple[AssetValidationIssue, ...]:
    issues: list[AssetValidationIssue] = []
    canvas = values.get("canvas")
    if not isinstance(canvas, Mapping) or not _pair(canvas.get("size"), minimum=1):
        issues.append(AssetValidationIssue("error", "ui_canvas_size", "Canvas size must contain two positive numbers."))
    elif "safe_area" in canvas:
        safe = canvas["safe_area"]
        if (not isinstance(safe, (list, tuple)) or len(safe) != 4
                or not all(_number(part) and part >= 0 for part in safe)
                or safe[0] + safe[2] >= canvas["size"][0]
                or safe[1] + safe[3] >= canvas["size"][1]):
            issues.append(AssetValidationIssue("error", "ui_safe_area",
                                               "Safe area must be four nonnegative pixel insets within the canvas."))
    widgets = values.get("widgets")
    if not isinstance(widgets, list):
        return tuple(issues + [AssetValidationIssue("error", "ui_widgets", "Widgets must be a list.")])
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, widget in enumerate(widgets):
        if not isinstance(widget, Mapping):
            issues.append(AssetValidationIssue("error", "ui_widget", f"Widget {index} must be an object."))
            continue
        identifier = str(widget.get("id") or "").strip()
        if not identifier or not identifier.isidentifier():
            issues.append(AssetValidationIssue("error", "ui_widget_id", f"Widget {index} needs an identifier-style ID."))
        elif identifier in by_id:
            issues.append(AssetValidationIssue("error", "ui_duplicate_id", f"Duplicate widget ID: {identifier}."))
        else:
            by_id[identifier] = widget
        kind = str(widget.get("type") or "")
        if kind not in WIDGET_TYPES:
            issues.append(AssetValidationIssue("error", "ui_widget_type", f"{identifier or index}: unsupported widget type {kind!r}."))
        for key, minimum, maximum in (("anchor", 0, 1), ("pivot", 0, 1), ("offset", None, None), ("size", 0, None)):
            if not _pair(widget.get(key), minimum=minimum, maximum=maximum):
                issues.append(AssetValidationIssue("error", f"ui_{key}", f"{identifier or index}: {key} must contain two valid numbers."))
        threshold = widget.get("min_viewport_width", 0)
        if not _number(threshold) or threshold < 0:
            issues.append(AssetValidationIssue("error", "ui_min_viewport_width",
                                               f"{identifier or index}: min_viewport_width must be nonnegative."))
        if kind == "button" and not str(widget.get("accessible_name") or "").strip():
            issues.append(AssetValidationIssue("error", "ui_accessible_name", f"{identifier or index}: buttons need an accessible name."))
        event = str(widget.get("on_activate") or "").strip()
        if event and not event.isidentifier():
            issues.append(AssetValidationIssue("error", "ui_event", f"{identifier or index}: event name must be an identifier."))
        if kind == "image" and not str(widget.get("image_asset_id") or "").strip():
            issues.append(AssetValidationIssue("error", "ui_image", f"{identifier or index}: image asset ID is required."))
    for identifier, widget in by_id.items():
        parent_id = str(widget.get("parent_id") or "")
        if parent_id and parent_id not in by_id:
            issues.append(AssetValidationIssue("error", "ui_parent", f"{identifier}: parent {parent_id!r} is missing."))
        elif parent_id and str(by_id[parent_id].get("type") or "") != "panel":
            issues.append(AssetValidationIssue("error", "ui_parent_type", f"{identifier}: parent must be a panel."))
        seen = {identifier}
        current = parent_id
        while current and current in by_id:
            if current in seen:
                issues.append(AssetValidationIssue("error", "ui_cycle", f"{identifier}: widget hierarchy contains a cycle."))
                break
            seen.add(current)
            current = str(by_id[current].get("parent_id") or "")
    return tuple(issues)


def layout_ui_document(values: Mapping[str, Any], *, viewport: tuple[int, int] | None = None) -> dict[str, Any]:
    issues = validate_ui_document(values)
    errors = [item.message for item in issues if item.severity == "error"]
    if errors:
        raise ValueError("Invalid UI document: " + "; ".join(errors))
    canvas_size = tuple(values["canvas"]["size"])
    width, height = viewport or canvas_size
    if not _pair((width, height), minimum=1):
        raise ValueError("Viewport dimensions must be positive finite numbers.")
    safe = tuple(float(part) for part in values["canvas"].get("safe_area", (0, 0, 0, 0)))
    if safe[0] + safe[2] >= width or safe[1] + safe[3] >= height:
        raise ValueError("Safe area leaves no usable viewport space.")
    by_id = {str(item["id"]): item for item in values["widgets"]}
    resolved: dict[str, dict[str, Any]] = {}

    def place(identifier: str) -> dict[str, Any]:
        if identifier in resolved:
            return resolved[identifier]
        widget = by_id[identifier]
        parent_id = str(widget.get("parent_id") or "")
        parent = place(parent_id) if parent_id else {
            "rect": [safe[0], safe[1], float(width) - safe[0] - safe[2],
                     float(height) - safe[1] - safe[3]]}
        px, py, pw, ph = parent["rect"]
        ww, wh = (float(part) for part in widget["size"])
        ax, ay = (float(part) for part in widget["anchor"])
        ox, oy = (float(part) for part in widget["offset"])
        vx, vy = (float(part) for part in widget["pivot"])
        rect = [px + ax * pw + ox - vx * ww, py + ay * ph + oy - vy * wh, ww, wh]
        row = {
            "id": identifier, "type": str(widget["type"]), "parent_id": parent_id,
            "rect": [round(part, 3) for part in rect],
            "visible": bool(parent.get("visible", True) and width >= float(widget.get("min_viewport_width", 0))),
            "text": str(widget.get("text") or ""),
            "accessible_name": str(widget.get("accessible_name") or ""),
            "on_activate": str(widget.get("on_activate") or ""),
            "image_asset_id": str(widget.get("image_asset_id") or ""),
        }
        resolved[identifier] = row
        return row

    for identifier in by_id:
        place(identifier)
    return {
        "schema": "tech_connector.ui_layout_preview.v1",
        "viewport": [float(width), float(height)],
        "safe_area": list(safe),
        "widgets": [resolved[str(widget["id"])] for widget in values["widgets"]],
    }


class UIDocumentAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(self, name: str, *, folder: str | Path = "Assets/UI", values: Mapping[str, Any] | None = None) -> AssetOperationReceipt:
        properties = {"canvas": {"size": [1920, 1080]}, "widgets": []}
        properties.update(dict(values or {}))
        self._require_valid(properties)
        return self.operations.create_asset("tc.ui_document", name, folder=folder, properties=properties)

    def properties(self, asset_id: str) -> dict[str, Any]:
        record = self._require_record(asset_id)
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid UI document source: {record.source_path.name}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("properties"), dict):
            raise ValueError(f"Invalid UI document properties: {record.source_path.name}")
        return dict(payload["properties"])

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record = self._require_record(asset_id)
        properties = {} if replace else self.properties(asset_id)
        properties.update(dict(values))
        self._require_valid(properties)
        self._dependency_edges(asset_id, properties)
        payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        payload["properties"] = properties
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, record.source_path)
        finally:
            temporary.unlink(missing_ok=True)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)
        self._set_dependencies(asset_id, properties)
        return properties

    def validate(self, asset_id: str) -> tuple[AssetValidationIssue, ...]:
        try:
            values = self.properties(asset_id)
        except ValueError as exc:
            return (AssetValidationIssue("error", "invalid_ui_document", str(exc)),)
        issues = list(validate_ui_document(values))
        if not any(issue.severity == "error" for issue in issues):
            try:
                self._dependency_edges(asset_id, values)
            except ValueError as exc:
                issues.append(AssetValidationIssue("error", "ui_dependency", str(exc)))
        return tuple(issues)

    def preview(self, asset_id: str, *, viewport: tuple[int, int] | None = None) -> dict[str, Any]:
        return layout_ui_document(self.properties(asset_id), viewport=viewport)

    def cook(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        values = self.properties(asset_id)
        self._require_valid(values)
        self._dependency_edges(asset_id, values)
        layout = layout_ui_document(values)
        payload = json.dumps({"platform": str(platform), "quality": str(quality), **layout}, sort_keys=True).encode("utf-8")
        return self.database.store_derived(
            asset_id, f"ui_layout_preview:{platform}:{quality}", payload,
            metadata={"platform": platform, "quality": quality, "runtime_qualified": False},
            extension=".tcuilayout",
        )

    def _require_record(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.ui_document":
            raise KeyError(f"Unknown UI document: {asset_id}")
        return record

    @staticmethod
    def _require_valid(values: Mapping[str, Any]) -> None:
        errors = [issue.message for issue in validate_ui_document(values) if issue.severity == "error"]
        if errors:
            raise ValueError("Invalid UI document: " + "; ".join(errors))

    def _dependency_edges(self, asset_id: str, values: Mapping[str, Any]) -> list[tuple[str, str]]:
        edges = []
        for widget in values.get("widgets", ()):
            for key, expected in (("image_asset_id", "tc.texture"), ("font_asset_id", "tc.font")):
                target = str(widget.get(key) or "")
                if not target:
                    continue
                record = self.database.asset(target)
                if target == asset_id or record is None or record.asset_type != expected:
                    raise ValueError(f"{widget['id']}: {key} must reference a registered {expected} asset.")
                edges.append((target, key))
        return sorted(set(edges))

    def _set_dependencies(self, asset_id: str, values: Mapping[str, Any]) -> None:
        self.database.set_dependencies(asset_id, self._dependency_edges(asset_id, values))


__all__ = ["UIDocumentAssetService", "layout_ui_document", "validate_ui_document"]
