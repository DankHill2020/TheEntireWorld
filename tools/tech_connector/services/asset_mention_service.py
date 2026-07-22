from __future__ import annotations

"""Build typed @mention candidates from chat, project, and DCC context."""

from dataclasses import dataclass
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from tech_connector.models.constants import project_index_db_path


_DCC_SCENE_CACHE = {}
_DCC_SCENE_CACHE_TTL = 5.0  # seconds


@dataclass(frozen=True)
class MentionCandidate:
    token: str
    label: str
    kind: str
    value: str
    source: str
    detail: str = ""
    priority: int = 50

    def display(self) -> str:
        suffix = f" - {self.detail}" if self.detail else ""
        display_name = self.label or self.token
        return f"@{display_name}  [{self.kind} | {self.source}]{suffix}"

    def prompt_line(self) -> str:
        detail = f"; detail={self.detail}" if self.detail else ""
        return f"- @{self.token}: kind={self.kind}; source={self.source}; value={self.value}{detail}"


UNREAL_PATH_RE = re.compile(r"/Game/[A-Za-z0-9_./]+")
ASSET_NAME_RE = re.compile(
    r"\b(?:BP|BPI|BO|ABP|SM|SK|M|MI|NS|PS|CR|CR_|IK|DA|DT|WBP|GA|GE)_[A-Za-z0-9_]+\b"
)
PROPERTY_RE = re.compile(
    r"\b(?:[lr]_[A-Za-z0-9_]+|[A-Za-z0-9_]+_(?:hand|foot|head|finger|arm|leg|clavicle|spine|root|pelvis)|[A-Za-z_][A-Za-z0-9_]*\.(?:[A-Za-z_][A-Za-z0-9_]*))\b"
)
FILE_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s`'\"<>|]+")
MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_./\\:-]+)")


def _safe_token(value: str, *, keep_qualified: bool = False) -> str:
    text = str(value or "").strip().strip("`'\"")
    if not text:
        return ""
    if text.startswith("@"):
        text = text[1:]
    text = text.replace("\\", "/").rstrip(".,;:)")
    if "/" in text and not keep_qualified:
        text = text.rsplit("/", 1)[-1]
    if "." in text and not keep_qualified:
        parts = [part for part in text.split(".") if part]
        if parts:
            text = parts[-1]
    allowed = r"[^A-Za-z0-9_.:/-]+" if keep_qualified else r"[^A-Za-z0-9_:-]+"
    text = re.sub(allowed, "_", text).strip("_")
    return text[:80]


def _project_file_token(rel_path: str) -> str:
    text = str(rel_path or "").replace("\\", "/").strip("/")
    if text.lower().endswith(".py"):
        text = text[:-3]
    return text.replace("/", ".")


def _asset_name_from_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    name = text.rsplit("/", 1)[-1]
    if "." in name:
        name = name.split(".")[-1]
    return name or text


def _add_candidate(
    candidates: dict[str, MentionCandidate],
    value: str,
    *,
    kind: str,
    source: str,
    detail: str = "",
    priority: int = 50,
    label: str = "",
    token: str = "",
) -> None:
    value = str(value or "").strip().strip("`")
    token = _safe_token(token, keep_qualified=True) if token else _safe_token(label or value)
    if not value or not token:
        return
    existing = candidates.get(token.lower())
    candidate = MentionCandidate(
        token=token,
        label=label or token,
        kind=kind,
        value=value,
        source=source,
        detail=detail,
        priority=priority,
    )
    if existing is None or candidate.priority > existing.priority:
        candidates[token.lower()] = candidate


def _iter_session_text(session: Iterable[dict[str, Any]] | None) -> Iterable[str]:
    for turn in session or []:
        if isinstance(turn, dict):
            content = turn.get("content") or ""
            if content:
                yield str(content)


def candidates_from_thread(session: Iterable[dict[str, Any]] | None) -> list[MentionCandidate]:
    candidates: dict[str, MentionCandidate] = {}
    for content in _iter_session_text(session):
        for path in UNREAL_PATH_RE.findall(content):
            _add_candidate(
                candidates,
                path,
                kind="unreal_asset_path",
                source="thread",
                label=_asset_name_from_path(path),
                priority=95,
            )
        for name in ASSET_NAME_RE.findall(content):
            _add_candidate(candidates, name, kind="asset", source="thread", priority=80)
        for prop in PROPERTY_RE.findall(content):
            _add_candidate(candidates, prop, kind="property", source="thread", priority=60)
        for path in FILE_PATH_RE.findall(content):
            _add_candidate(
                candidates,
                path,
                kind="file_path",
                source="thread",
                label=Path(path).name,
                priority=70,
            )
    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))


def _coerce_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _walk_snapshot_assets(value: Any) -> Iterable[tuple[str, str]]:
    value = _coerce_json(value)
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"selected_assets", "assets", "blueprints", "skeletal_meshes", "static_meshes", "materials", "animations", "levels"}:
                for item in _walk_snapshot_assets(child):
                    yield item
            elif key in {"path", "object_path", "package_name", "asset_path"} and isinstance(child, str):
                if child.startswith("/Game/"):
                    yield child, key
            elif key in {"name", "asset_name"} and isinstance(child, str):
                if ASSET_NAME_RE.search(child):
                    yield child, key
            else:
                for item in _walk_snapshot_assets(child):
                    yield item
    elif isinstance(value, list):
        for child in value[:300]:
            for item in _walk_snapshot_assets(child):
                yield item
    elif isinstance(value, str):
        for path in UNREAL_PATH_RE.findall(value):
            yield path, "snapshot_text"
        for name in ASSET_NAME_RE.findall(value):
            yield name, "snapshot_text"


def candidates_from_unreal_snapshot(snapshot: Any, *, limit: int = 80) -> list[MentionCandidate]:
    candidates: dict[str, MentionCandidate] = {}
    for value, source_key in _walk_snapshot_assets(snapshot):
        kind = "unreal_asset_path" if str(value).startswith("/Game/") else "asset"
        _add_candidate(
            candidates,
            value,
            kind=kind,
            source="unreal_snapshot",
            detail=source_key,
            label=_asset_name_from_path(value),
            priority=75,
        )
        if len(candidates) >= limit:
            break
    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))


def candidates_from_selected_assets(selected_assets: Iterable[str] | None) -> list[MentionCandidate]:
    candidates: dict[str, MentionCandidate] = {}
    for value in selected_assets or []:
        _add_candidate(
            candidates,
            str(value),
            kind="unreal_selection",
            source="live_selection",
            label=_asset_name_from_path(str(value)),
            priority=100,
        )
    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))


def candidates_from_index(query: str, *, limit: int = 12) -> list[MentionCandidate]:
    if not project_index_db_path().exists():
        return []
    q = f"%{query}%" if query else "%"
    candidates: dict[str, MentionCandidate] = {}
    try:
        conn = sqlite3.connect(str(project_index_db_path()))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM symbols WHERE name LIKE ? LIMIT ?", (q, limit))
            for (name,) in cursor.fetchall():
                _add_candidate(candidates, name, kind="symbol", source="knowledge_index", priority=45)
            cursor.execute("SELECT rel_path FROM files WHERE rel_path LIKE ? LIMIT ?", (q, limit))
            for (rel_path,) in cursor.fetchall():
                _add_candidate(
                    candidates,
                    rel_path,
                    kind="project_file",
                    source="knowledge_index",
                    label=Path(str(rel_path)).stem,
                    token=_project_file_token(str(rel_path)),
                    detail=str(rel_path),
                    priority=40,
                )
        finally:
            conn.close()
    except Exception:
        return []
    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))[:limit]


def _parse_python_list_output(raw_str: str) -> list[str]:
    text = (raw_str or "").strip()
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1:
        content = text[start+1:end]
        items = []
        for part in content.split(','):
            part = part.strip().strip("'\"`").strip()
            if part:
                if part.startswith("u'") or part.startswith('u"'):
                    part = part[1:].strip("'\"")
                items.append(part)
        return items
    return [line.strip() for line in text.splitlines() if line.strip()]


def candidates_from_dcc_scene(query_str: str, command_router: Any, text_context: str = "") -> list[MentionCandidate]:
    if not command_router:
        return []
    
    hosts = command_router.detect_dcc_hosts(text_context)
    if not hosts:
        hosts = ["unreal", "maya", "blender", "houdini", "substance_painter"]
        
    now = time.monotonic()
    candidates: dict[str, MentionCandidate] = {}
    
    for host in hosts:
        bridge = command_router._host_bridge_for_operation(host)
        if not bridge or not hasattr(bridge, "find_port"):
            continue
            
        port = bridge.find_port()
        if not port:
            continue
            
        cache_key = f"{host}_{port}"
        cached = _DCC_SCENE_CACHE.get(cache_key)
        if cached and now - cached["time"] < _DCC_SCENE_CACHE_TTL:
            for c in cached["candidates"]:
                candidates[c.token.lower()] = c
            continue
            
        host_candidates_dict: dict[str, MentionCandidate] = {}
        
        try:
            if host == "maya":
                ok_sel, res_sel = bridge.execute("import maya.cmds as cmds\nprint(cmds.ls(sl=True) or [])", timeout=0.25)
                if ok_sel:
                    for item in _parse_python_list_output(res_sel):
                        _add_candidate(host_candidates_dict, item, kind="maya_selection", source="maya_live", priority=100)
                
                ok_objs, res_objs = bridge.execute("import maya.cmds as cmds\nprint(cmds.ls(dagObjects=True, assemblies=True) or [])", timeout=0.25)
                if ok_objs:
                    for item in _parse_python_list_output(res_objs):
                        _add_candidate(host_candidates_dict, item, kind="maya_object", source="maya_live", priority=85)
                        
            elif host == "blender":
                ok_sel, res_sel = bridge.execute("import bpy\nprint([obj.name for obj in bpy.context.selected_objects])", timeout=0.25)
                if ok_sel:
                    for item in _parse_python_list_output(res_sel):
                        _add_candidate(host_candidates_dict, item, kind="blender_selection", source="blender_live", priority=100)
                
                ok_objs, res_objs = bridge.execute("import bpy\nprint(list(bpy.data.objects.keys())[:200])", timeout=0.25)
                if ok_objs:
                    for item in _parse_python_list_output(res_objs):
                        _add_candidate(host_candidates_dict, item, kind="blender_object", source="blender_live", priority=85)
                        
            elif host == "houdini":
                ok_sel, res_sel = bridge.execute("import hou\nprint([n.path() for n in hou.selectedNodes()])", timeout=0.25)
                if ok_sel:
                    for item in _parse_python_list_output(res_sel):
                        _add_candidate(host_candidates_dict, item, kind="houdini_selection", source="houdini_live", priority=100)
                
                ok_objs, res_objs = bridge.execute("import hou\nprint([n.path() for n in hou.node('/').allSubChildren()][:200])", timeout=0.25)
                if ok_objs:
                    for item in _parse_python_list_output(res_objs):
                        _add_candidate(host_candidates_dict, item, kind="houdini_node", source="houdini_live", priority=85)
                        
            elif host == "substance_painter":
                ok_objs, res_objs = bridge.execute("import substance_painter.textureset as ts\nprint([s.name() for s in ts.all_texture_sets()])", timeout=0.25)
                if ok_objs:
                    for item in _parse_python_list_output(res_objs):
                        _add_candidate(host_candidates_dict, item, kind="substance_textureset", source="substance_live", priority=85)
                        
        except Exception:
            pass
            
        host_candidates = list(host_candidates_dict.values())
        _DCC_SCENE_CACHE[cache_key] = {"time": now, "candidates": host_candidates}
        
        for c in host_candidates:
            candidates[c.token.lower()] = c
            
    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))


def candidates_from_app_context(app_context: Any, settings: dict | None = None) -> list[MentionCandidate]:
    if not app_context:
        return []
    settings = settings or {}
    app_id = getattr(app_context, "id", "")
    candidates: dict[str, MentionCandidate] = {}

    if app_id == "slack":
        default = settings.get("slack_default_channel", "") or settings.get("slack_channel", "")
        cached_channels = settings.get("slack_channels") or []
        cached_users = settings.get("slack_users") or []
        for value, detail in [
            (default, "configured default channel"),
            *[(channel, "live Slack channel") for channel in cached_channels],
            *[(user, "live Slack user") for user in cached_users],
            ("here", "current/default Slack destination"),
        ]:
            _add_candidate(candidates, value, kind="slack_channel", source="slack", detail=detail, priority=85)
    elif app_id == "discord":
        default = settings.get("discord_default_channel", "") or settings.get("discord_username", "")
        cached_channels = settings.get("discord_channels") or []
        cached_users = settings.get("discord_users") or []
        for value, detail in [
            (default, "configured default target"),
            *[(channel, "live Discord channel") for channel in cached_channels],
            *[(user, "live Discord user") for user in cached_users],
        ]:
            _add_candidate(candidates, value, kind="discord_target", source="discord", detail=detail, priority=85)
    elif app_id == "jira":
        for value, detail in [
            (settings.get("jira_project_key", ""), "configured Jira project"),
            *[(project, "live Jira project") for project in settings.get("jira_projects", []) or []],
            *[(user, "live Atlassian user") for user in settings.get("atlassian_users", []) or []],
            ("task", "new Jira task"),
            ("bug", "new Jira bug"),
        ]:
            _add_candidate(candidates, value, kind="jira_target", source="jira", detail=detail, priority=85)
    elif app_id == "confluence":
        for value, detail in [
            (settings.get("confluence_space_id", ""), "configured Confluence space"),
            (settings.get("confluence_parent_id", ""), "configured parent page"),
            *[(space, "live Confluence space") for space in settings.get("confluence_spaces", []) or []],
            ("page", "new Confluence page"),
        ]:
            _add_candidate(candidates, value, kind="confluence_target", source="confluence", detail=detail, priority=85)
    elif getattr(app_context, "source", "") == "integration_package":
        _add_candidate(candidates, app_context.name, kind="integration", source="integration_package", detail="installed package", priority=80)
        for kind in getattr(app_context, "mention_kinds", ()) or ():
            _add_candidate(candidates, kind, kind="integration_reference", source=app_context.name, detail="placeholder", priority=45)

    return sorted(candidates.values(), key=lambda item: (-item.priority, item.token.lower()))


def merge_candidates(*groups: Iterable[MentionCandidate], query: str = "", limit: int = 20) -> list[MentionCandidate]:
    merged: dict[str, MentionCandidate] = {}
    query_lower = (query or "").lower()
    for group in groups:
        for candidate in group:
            haystack = " ".join([candidate.token, candidate.label, candidate.value, candidate.detail]).lower()
            if query_lower and query_lower not in haystack:
                continue
            existing = merged.get(candidate.token.lower())
            if existing is None or candidate.priority > existing.priority:
                merged[candidate.token.lower()] = candidate
    return sorted(merged.values(), key=lambda item: (-item.priority, item.token.lower()))[:limit]


def extract_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    mentions: list[str] = []
    for match in MENTION_RE.finditer(text or ""):
        raw_token = match.group(1)
        lower = raw_token.lower()
        if re.match(
            r"^(?:maya|unreal(?:_engine)?|blender|houdini|substance(?:_painter)?|motionbuilder|mobu|unity)\.",
            lower,
        ) or re.match(r"^[a-z0-9_]+_tools[/.]", lower):
            # Smart Search resolves these references while preserving hierarchy.
            continue
        token = _safe_token(raw_token)
        if token and token.lower() not in seen:
            seen.add(token.lower())
            mentions.append(token)
    return mentions


def mention_context_block(text: str, candidates: Iterable[MentionCandidate]) -> str:
    mentions = extract_mentions(text)
    if not mentions:
        return ""
    by_token = {candidate.token.lower(): candidate for candidate in candidates}
    lines: list[str] = []
    unresolved: list[str] = []
    for token in mentions:
        candidate = by_token.get(token.lower())
        if candidate:
            lines.append(candidate.prompt_line())
        else:
            unresolved.append(f"- @{token}: unresolved mention from user input")
    if not lines and not unresolved:
        return ""
    return "Tagged Reference Context:\n" + "\n".join(lines + unresolved)
