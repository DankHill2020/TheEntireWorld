"""Canonical conversation workspace for connected prompt context.

The workspace stores serializable, package-aware entity handles. Legacy
operation-memory fields are derived from this state for old call sites.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import time
import uuid
from typing import Any


ENTITY_KINDS = {
    "file",
    "function",
    "class",
    "method",
    "helper",
    "symbol",
    "asset",
    "actor",
    "component",
    "graph",
    "control",
    "control_rig",
    "skeleton",
    "widget",
    "package",
    "edit",
    "change_session",
}


@dataclass
class WorkspaceEntity:
    entity_id: str
    kind: str
    host: str = "project_code"
    project: str = ""
    package: str = ""
    ref: str = ""
    name: str = ""
    source: str = "unknown"
    confidence: float = 0.8
    related: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspacePackage:
    package_id: str
    host: str = "project_code"
    project: str = ""
    entity_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceRelationship:
    relationship_id: str
    source_entity_id: str
    relation: str
    target_entity_id: str
    source: str = "unknown"
    confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceEdit:
    edit_id: str
    change_session_id: str = ""
    file_entity_ids: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    summary: str = ""
    source: str = "change_history"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkspaceResultFrame:
    frame_id: str
    request_id: str = ""
    parent_request_id: str = ""
    relationship: str = "follow_up"
    summary: str = ""
    primary_entity_ids: list[str] = field(default_factory=list)
    selected_entity_ids: list[str] = field(default_factory=list)
    package_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    edit_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReferenceResolution:
    status: str
    reference: str
    kind: str = ""
    entity_ids: list[str] = field(default_factory=list)
    source: str = ""
    confidence: float = 0.0
    reason: str = ""

    @property
    def entity_id(self) -> str:
        return self.entity_ids[0] if self.entity_ids else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationWorkspace:
    workspace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    active_request_id: str = ""
    revision: int = 0
    packages: dict[str, WorkspacePackage] = field(default_factory=dict)
    entities: dict[str, WorkspaceEntity] = field(default_factory=dict)
    relationships: dict[str, WorkspaceRelationship] = field(default_factory=dict)
    result_frames: list[WorkspaceResultFrame] = field(default_factory=list)
    recent_edits: list[WorkspaceEdit] = field(default_factory=list)
    recent_change_sessions: list[str] = field(default_factory=list)
    reference_aliases: dict[str, list[str]] = field(default_factory=dict)
    primary_entities: dict[str, str] = field(default_factory=dict)
    selected_entity_sets: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    max_result_frames: int = 32
    updated_at: str = field(default_factory=lambda: _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "conversation_id": self.conversation_id,
            "active_request_id": self.active_request_id,
            "revision": self.revision,
            "packages": {key: item.to_dict() for key, item in self.packages.items()},
            "entities": {key: item.to_dict() for key, item in self.entities.items()},
            "relationships": {key: item.to_dict() for key, item in self.relationships.items()},
            "result_frames": [item.to_dict() for item in self.result_frames],
            "recent_edits": [item.to_dict() for item in self.recent_edits],
            "recent_change_sessions": list(self.recent_change_sessions),
            "reference_aliases": {key: list(value) for key, value in self.reference_aliases.items()},
            "primary_entities": dict(self.primary_entities),
            "selected_entity_sets": {key: list(value) for key, value in self.selected_entity_sets.items()},
            "diagnostics": list(self.diagnostics),
            "max_result_frames": self.max_result_frames,
            "updated_at": self.updated_at,
        }


def workspace_from_dict(data: dict[str, Any] | ConversationWorkspace | None) -> ConversationWorkspace:
    if isinstance(data, ConversationWorkspace):
        return data
    raw = dict(data or {})
    workspace = ConversationWorkspace(
        workspace_id=str(raw.get("workspace_id") or uuid.uuid4()),
        conversation_id=str(raw.get("conversation_id") or ""),
        active_request_id=str(raw.get("active_request_id") or ""),
        revision=int(raw.get("revision") or 0),
        recent_change_sessions=[str(x) for x in raw.get("recent_change_sessions") or []],
        reference_aliases={str(k): [str(x) for x in v or []] for k, v in dict(raw.get("reference_aliases") or {}).items()},
        primary_entities={str(k): str(v) for k, v in dict(raw.get("primary_entities") or {}).items() if v},
        selected_entity_sets={str(k): [str(x) for x in v or []] for k, v in dict(raw.get("selected_entity_sets") or {}).items()},
        diagnostics=list(raw.get("diagnostics") or []),
        max_result_frames=int(raw.get("max_result_frames") or 32),
        updated_at=str(raw.get("updated_at") or _utc_now()),
    )
    workspace.packages = {
        str(key): WorkspacePackage(**_filter_dataclass(WorkspacePackage, value))
        for key, value in dict(raw.get("packages") or {}).items()
        if isinstance(value, dict)
    }
    workspace.entities = {
        str(key): WorkspaceEntity(**_filter_dataclass(WorkspaceEntity, value))
        for key, value in dict(raw.get("entities") or {}).items()
        if isinstance(value, dict)
    }
    workspace.relationships = {
        str(key): WorkspaceRelationship(**_filter_dataclass(WorkspaceRelationship, value))
        for key, value in dict(raw.get("relationships") or {}).items()
        if isinstance(value, dict)
    }
    workspace.result_frames = [
        WorkspaceResultFrame(**_filter_dataclass(WorkspaceResultFrame, item))
        for item in raw.get("result_frames") or []
        if isinstance(item, dict)
    ][-workspace.max_result_frames :]
    workspace.recent_edits = [
        WorkspaceEdit(**_filter_dataclass(WorkspaceEdit, item))
        for item in raw.get("recent_edits") or []
        if isinstance(item, dict)
    ][-20:]
    return workspace


def merge_workspace_update(
    workspace: dict[str, Any] | ConversationWorkspace | None,
    update: dict[str, Any] | None,
    *,
    request_id: str = "",
    parent_request_id: str = "",
    relationship: str = "follow_up",
) -> dict[str, Any]:
    current = workspace_from_dict(workspace)
    update = dict(update or {})
    diagnostics: list[dict[str, Any]] = []
    primary_ids = _as_list(update.get("primary_entity_ids"))
    selected_ids = _as_list(update.get("selected_entity_ids"))
    package_ids = _as_list(update.get("package_ids"))
    relationship_ids = _as_list(update.get("relationship_ids"))
    edit_ids = _as_list(update.get("edit_ids"))

    for entity in _entity_payloads_from_update(update):
        try:
            normalized = normalize_entity(entity)
            existing = current.entities.get(normalized.entity_id)
            if existing:
                normalized.metadata = {**existing.metadata, **normalized.metadata}
                normalized.related = _dedupe([*existing.related, *normalized.related])
                normalized.confidence = max(existing.confidence, normalized.confidence)
            current.entities[normalized.entity_id] = normalized
            selected_ids.append(normalized.entity_id)
            kind = normalized.kind
            if normalized.entity_id in _as_list(update.get("primary_entity_ids")) or not current.primary_entities.get(kind):
                current.primary_entities[kind] = normalized.entity_id
            if normalized.package:
                package_ids.append(normalized.package)
                package = current.packages.get(normalized.package) or WorkspacePackage(
                    package_id=normalized.package,
                    host=normalized.host,
                    project=normalized.project,
                )
                package.host = package.host or normalized.host
                package.project = package.project or normalized.project
                package.entity_ids = _dedupe([*package.entity_ids, normalized.entity_id])
                package.updated_at = _utc_now()
                current.packages[package.package_id] = package
            _add_aliases(current, normalized)
        except Exception as exc:
            diagnostics.append({"error": f"entity merge failed: {exc}", "payload": entity})

    for package_payload in update.get("packages") or []:
        if not isinstance(package_payload, dict):
            continue
        package_id = str(package_payload.get("package_id") or package_payload.get("id") or package_payload.get("package") or "")
        if not package_id:
            continue
        package = current.packages.get(package_id) or WorkspacePackage(package_id=package_id)
        package.host = str(package_payload.get("host") or package.host or "")
        package.project = str(package_payload.get("project") or package.project or "")
        package.entity_ids = _dedupe([*package.entity_ids, *_as_list(package_payload.get("entity_ids") or package_payload.get("entities"))])
        package.metadata.update(dict(package_payload.get("metadata") or {}))
        package.updated_at = _utc_now()
        current.packages[package_id] = package
        package_ids.append(package_id)

    for rel_payload in update.get("relationships") or []:
        if not isinstance(rel_payload, dict):
            continue
        source_id = str(rel_payload.get("source_entity_id") or rel_payload.get("source") or "")
        target_id = str(rel_payload.get("target_entity_id") or rel_payload.get("target") or "")
        relation = str(rel_payload.get("relation") or "references")
        if not source_id or not target_id:
            continue
        rel_id = str(rel_payload.get("relationship_id") or _relationship_id(source_id, relation, target_id))
        current.relationships[rel_id] = WorkspaceRelationship(
            relationship_id=rel_id,
            source_entity_id=source_id,
            relation=relation,
            target_entity_id=target_id,
            source=str(rel_payload.get("source_name") or rel_payload.get("source_kind") or rel_payload.get("source_system") or rel_payload.get("source") or "workspace_update"),
            confidence=float(rel_payload.get("confidence") or 0.8),
            metadata=dict(rel_payload.get("metadata") or {}),
        )
        relationship_ids.append(rel_id)

    for edit_payload in update.get("edits") or []:
        if not isinstance(edit_payload, dict):
            continue
        edit = WorkspaceEdit(**_filter_dataclass(WorkspaceEdit, {
            "edit_id": edit_payload.get("edit_id") or edit_payload.get("id") or f"edit:{uuid.uuid4()}",
            **edit_payload,
        }))
        current.recent_edits.append(edit)
        current.recent_edits = current.recent_edits[-20:]
        edit_ids.append(edit.edit_id)
        if edit.change_session_id:
            current.recent_change_sessions = _dedupe([edit.change_session_id, *current.recent_change_sessions])[:20]

    for kind, entity_id in dict(update.get("primary_entities") or {}).items():
        if entity_id:
            current.primary_entities[str(kind)] = str(entity_id)
            primary_ids.append(str(entity_id))
    for kind, ids in dict(update.get("selected_entity_sets") or {}).items():
        current.selected_entity_sets[str(kind)] = _dedupe([str(x) for x in ids or [] if x])

    for entity_id in primary_ids:
        entity = current.entities.get(entity_id)
        if entity:
            current.primary_entities[entity.kind] = entity_id
    by_kind: dict[str, list[str]] = {}
    for entity_id in selected_ids:
        entity = current.entities.get(entity_id)
        if entity:
            by_kind.setdefault(entity.kind, []).append(entity_id)
    for kind, ids in by_kind.items():
        current.selected_entity_sets[kind] = _dedupe(ids)

    frame_needed = bool(update.get("result_summary") or selected_ids or primary_ids or relationship_ids or edit_ids)
    if frame_needed:
        frame = WorkspaceResultFrame(
            frame_id=str(update.get("frame_id") or uuid.uuid4()),
            request_id=str(update.get("request_id") or request_id or ""),
            parent_request_id=str(update.get("parent_request_id") or parent_request_id or ""),
            relationship=str(update.get("relationship") or relationship or "follow_up"),
            summary=str(update.get("result_summary") or update.get("summary") or ""),
            primary_entity_ids=_dedupe(primary_ids),
            selected_entity_ids=_dedupe(selected_ids),
            package_ids=_dedupe(package_ids),
            relationship_ids=_dedupe(relationship_ids),
            edit_ids=_dedupe(edit_ids),
        )
        current.result_frames.append(frame)
        current.result_frames = current.result_frames[-current.max_result_frames :]

    current.diagnostics.extend(diagnostics)
    current.diagnostics = current.diagnostics[-20:]
    current.revision += 1
    current.updated_at = _utc_now()
    return current.to_dict()


def workspace_update_from_legacy_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(metadata or {})
    update = dict(metadata.get("workspace_update") or {})
    if update:
        return update
    entities: list[dict[str, Any]] = []
    selected_file = str(metadata.get("selected_file") or metadata.get("resolved_target_file") or "")
    if selected_file:
        entities.append(file_entity_payload(selected_file, source=str(metadata.get("engine_path") or "result_metadata"), confidence=0.98))
    for path in _as_list(metadata.get("selected_files")):
        entities.append(file_entity_payload(path, source=str(metadata.get("engine_path") or "result_metadata"), confidence=0.92))
    for asset in _as_list(metadata.get("selected_assets") or metadata.get("affected_assets") or metadata.get("created_assets") or metadata.get("modified_assets")):
        entities.append(unreal_entity_payload(asset, kind="asset", source=str(metadata.get("engine_path") or "result_metadata")))
    for actor in _as_list(metadata.get("selected_actors")):
        entities.append(unreal_entity_payload(actor, kind="actor", source=str(metadata.get("engine_path") or "result_metadata")))
    return {
        "entities": entities,
        "primary_entity_ids": [],
        "selected_entity_ids": [],
        "result_summary": str(metadata.get("result_summary") or metadata.get("result_type") or ""),
    }


def compatibility_snapshot(workspace: dict[str, Any] | ConversationWorkspace | None) -> dict[str, Any]:
    current = workspace_from_dict(workspace)
    primary_file = _entity_ref(current, current.primary_entities.get("file"))
    selected_files = [_entity_ref(current, entity_id) for entity_id in current.selected_entity_sets.get("file", [])]
    selected_assets = [_entity_ref(current, entity_id) for entity_id in current.selected_entity_sets.get("asset", [])]
    selected_objects = [
        _entity_ref(current, entity_id)
        for kind in ("actor", "object", "component")
        for entity_id in current.selected_entity_sets.get(kind, [])
    ]
    return {
        "selected_file": primary_file,
        "recent_file": primary_file,
        "active_file": primary_file,
        "selected_files": [x for x in selected_files if x],
        "selected_assets": [x for x in selected_assets if x],
        "selected_objects": [x for x in selected_objects if x],
        "recent_results": [frame.to_dict() for frame in current.result_frames[-8:]],
        "workspace_id": current.workspace_id,
        "workspace_revision": current.revision,
    }


def resolve_reference(
    workspace: dict[str, Any] | ConversationWorkspace | None,
    text: str,
    *,
    kind: str = "",
) -> ReferenceResolution:
    current = workspace_from_dict(workspace)
    lower = str(text or "").lower()
    wanted_kind = _kind_from_text(lower, kind)
    plural = bool(re.search(r"\b(those|these|files|assets|actors|changes)\b", lower))
    other = bool(re.search(r"\bother\b", lower))
    previous = bool(re.search(r"\b(previous|last)\b", lower))
    ordinal = _ordinal_from_text(lower)

    if "change" in lower or "edit" in lower:
        if current.recent_edits:
            edit = current.recent_edits[-1 if previous else -1]
            ids = list(edit.file_entity_ids)
            return ReferenceResolution("resolved", "recent edits", "edit", ids, "recent_edits", 0.96)
        return ReferenceResolution("unresolved", "recent edits", "edit", [], "recent_edits", 0.0, "No recent edits in workspace.")

    ids = list(current.selected_entity_sets.get(wanted_kind, []))
    primary = current.primary_entities.get(wanted_kind, "")
    if other and primary:
        ids = [entity_id for entity_id in ids if entity_id != primary]
    elif not plural:
        if ordinal is not None and ids:
            ids = ids[ordinal : ordinal + 1]
        elif primary:
            ids = [primary]
        elif ids:
            ids = ids[:1]
    if ids:
        return ReferenceResolution("resolved", text, wanted_kind, ids, "conversation_workspace", 0.98)

    for frame in reversed(current.result_frames):
        frame_ids = [
            entity_id for entity_id in frame.selected_entity_ids
            if current.entities.get(entity_id) and current.entities[entity_id].kind == wanted_kind
        ]
        if frame_ids:
            if other and primary:
                frame_ids = [entity_id for entity_id in frame_ids if entity_id != primary]
            elif not plural:
                frame_ids = frame_ids[:1]
            return ReferenceResolution("resolved", text, wanted_kind, frame_ids, "result_frame", 0.9)
    return ReferenceResolution("unresolved", text, wanted_kind, [], "conversation_workspace", 0.0, "No matching workspace entity.")


def file_entity_payload(path: str, *, source: str = "project_search", confidence: float = 0.9, project: str = "") -> dict[str, Any]:
    ref = str(path or "").replace("\\", "/")
    name = Path(ref).name or ref
    package = _code_package(ref)
    return {
        "kind": "file",
        "host": "project_code",
        "project": project or _project_from_path(ref),
        "package": package,
        "ref": ref,
        "name": name,
        "source": source,
        "confidence": confidence,
    }


def unreal_entity_payload(value: Any, *, kind: str = "asset", source: str = "unreal_resolver", project: str = "") -> dict[str, Any]:
    raw = dict(value) if isinstance(value, dict) else {"ref": str(value or "")}
    ref = str(raw.get("ref") or raw.get("path") or raw.get("object_path") or raw.get("asset_path") or raw.get("name") or "")
    if kind == "asset":
        ref = _unreal_package_ref(ref)
    name = str(raw.get("name") or _name_from_ref(ref))
    return {
        "kind": str(raw.get("kind") or kind),
        "host": "unreal",
        "project": project or str(raw.get("project") or ""),
        "package": _unreal_package(ref) if ref.startswith("/Game/") else str(raw.get("package") or ""),
        "ref": ref,
        "name": name,
        "source": str(raw.get("source") or source),
        "confidence": float(raw.get("confidence") or 1.0),
        "metadata": {k: v for k, v in raw.items() if k not in {"kind", "ref", "path", "object_path", "name", "source", "confidence"}},
    }


def normalize_entity(payload: WorkspaceEntity | dict[str, Any]) -> WorkspaceEntity:
    if isinstance(payload, WorkspaceEntity):
        data = payload.to_dict()
    else:
        data = dict(payload or {})
    kind = str(data.get("kind") or "file").lower()
    if kind not in ENTITY_KINDS:
        kind = "symbol" if kind in {"method", "helper"} else kind
    host = str(data.get("host") or data.get("dcc") or ("unreal" if str(data.get("ref") or data.get("path") or "").startswith("/Game/") else "project_code"))
    ref = str(data.get("ref") or data.get("path") or data.get("object_path") or data.get("file") or "")
    if host == "unreal" and kind == "asset":
        ref = _unreal_package_ref(ref)
    package = str(data.get("package") or (_unreal_package(ref) if host == "unreal" and ref.startswith("/Game/") else _code_package(ref)))
    name = str(data.get("name") or _name_from_ref(ref))
    project = str(data.get("project") or _project_from_path(ref))
    entity_id = str(data.get("entity_id") or _entity_id(host, project, package, kind, ref or name))
    return WorkspaceEntity(
        entity_id=entity_id,
        kind=kind,
        host=host,
        project=project,
        package=package,
        ref=ref,
        name=name,
        source=str(data.get("source") or "unknown"),
        confidence=float(data.get("confidence") or 0.8),
        related=[str(x) for x in data.get("related") or []],
        metadata=dict(data.get("metadata") or {}),
        updated_at=str(data.get("updated_at") or _utc_now()),
    )


def workspace_update_from_change_session(session: Any, session_path: str = "") -> dict[str, Any]:
    files = list(getattr(session, "files", []) or [])
    entities = []
    file_ids = []
    created_files = []
    modified_files = []
    for item in files:
        path = str(getattr(item, "path", "") or "")
        action = str(getattr(item, "action", "") or "modify")
        payload = file_entity_payload(path, source="change_history", confidence=1.0)
        entity = normalize_entity(payload)
        entities.append(entity.to_dict())
        file_ids.append(entity.entity_id)
        if action == "create":
            created_files.append(path)
        else:
            modified_files.append(path)
    session_id = str(getattr(session, "session_id", "") or Path(session_path).stem)
    edit = WorkspaceEdit(
        edit_id=f"change_session:{session_id}",
        change_session_id=session_id,
        file_entity_ids=file_ids,
        changed_files=[*created_files, *modified_files],
        created_files=created_files,
        modified_files=modified_files,
        summary=str(getattr(session, "summary", "") or "AI code changes"),
        metadata={"change_session_path": session_path},
    )
    session_entity = {
        "kind": "change_session",
        "host": "project_code",
        "project": "",
        "package": "change_history",
        "ref": session_id,
        "name": session_id,
        "source": "change_history",
        "confidence": 1.0,
        "metadata": {"change_session_path": session_path},
    }
    return {
        "entities": [*entities, session_entity],
        "edits": [edit.to_dict()],
        "primary_entity_ids": file_ids[:1],
        "selected_entity_ids": file_ids,
        "result_summary": edit.summary,
    }


def _entity_payloads_from_update(update: dict[str, Any]) -> list[dict[str, Any]]:
    payloads = [item for item in update.get("entities") or [] if isinstance(item, dict)]
    for key, kind in (
        ("files", "file"),
        ("selected_files", "file"),
        ("assets", "asset"),
        ("selected_assets", "asset"),
        ("actors", "actor"),
        ("selected_actors", "actor"),
        ("components", "component"),
        ("selected_components", "component"),
        ("graphs", "graph"),
        ("controls", "control"),
        ("widgets", "widget"),
    ):
        for value in _as_list(update.get(key)):
            if kind == "file":
                payloads.append(file_entity_payload(str(value), source=str(update.get("source") or "workspace_update")))
            elif kind in {"asset", "actor", "component"}:
                payloads.append(unreal_entity_payload(value, kind=kind, source=str(update.get("source") or "workspace_update")))
            else:
                payloads.append({"kind": kind, "ref": str(value), "name": _name_from_ref(str(value)), "source": str(update.get("source") or "workspace_update")})
    return payloads


def _filter_dataclass(cls: Any, data: dict[str, Any]) -> dict[str, Any]:
    allowed = set(cls.__dataclass_fields__.keys())
    return {key: value for key, value in dict(data or {}).items() if key in allowed}


def _add_aliases(workspace: ConversationWorkspace, entity: WorkspaceEntity) -> None:
    for alias in {entity.name, entity.ref, Path(entity.ref).name if entity.ref else ""}:
        alias = str(alias or "").strip().casefold()
        if alias:
            workspace.reference_aliases[alias] = _dedupe([entity.entity_id, *workspace.reference_aliases.get(alias, [])])[:8]


def _entity_ref(workspace: ConversationWorkspace, entity_id: str | None) -> str:
    entity = workspace.entities.get(str(entity_id or ""))
    return entity.ref if entity else ""


def _relationship_id(source_id: str, relation: str, target_id: str) -> str:
    return "rel:" + _safe_key(f"{source_id}:{relation}:{target_id}")


def _entity_id(host: str, project: str, package: str, kind: str, ref: str) -> str:
    return ":".join(_safe_key(part) for part in (host, project, package, kind, ref))


def _safe_key(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"\s+", "_", text)
    return text or "_"


def _code_package(path: str) -> str:
    ref = str(path or "").replace("\\", "/")
    parent = Path(ref).parent.as_posix()
    if not parent or parent == ".":
        return "project"
    parts = [part for part in parent.split("/") if part and part not in {".", ".."}]
    return ".".join(parts[-3:]) if parts else "project"


def _project_from_path(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").split("/") if part]
    return parts[1] if len(parts) > 2 and re.match(r"^[A-Za-z]:$", parts[0]) else (parts[0] if parts else "")


def _unreal_package_ref(path: str) -> str:
    text = str(path or "").replace("\\", "/")
    if "." in text:
        return text.split(".", 1)[0]
    return text


def _unreal_package(path: str) -> str:
    ref = _unreal_package_ref(path)
    if not ref.startswith("/Game/"):
        return ""
    return ref.rsplit("/", 1)[0]


def _name_from_ref(ref: str) -> str:
    text = str(ref or "").rstrip("/")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.rsplit("/", 1)[-1] if "/" in text else text


def _as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _dedupe(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _kind_from_text(text: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    mapping = (
        ("file", ("file", "files")),
        ("asset", ("asset", "assets", "blueprint", "blueprints", "skeleton", "effect")),
        ("actor", ("actor", "actors", "character")),
        ("function", ("function", "functions", "helper", "helpers")),
        ("class", ("class", "classes")),
        ("graph", ("graph", "graphs")),
    )
    for kind, terms in mapping:
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            return kind
    return "file"


def _ordinal_from_text(text: str) -> int | None:
    for word, index in (("first", 0), ("second", 1), ("third", 2), ("fourth", 3)):
        if re.search(rf"\b{word}\b", text):
            return index
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

