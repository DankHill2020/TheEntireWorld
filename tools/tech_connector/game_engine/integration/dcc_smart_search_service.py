"""Deterministic Smart Search completion for DCC hosts and tool packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Sequence

from tech_connector.models.constants import DCC_TOOL_PACKAGE_DIRS, project_index_db_path
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.services.tool_search_ranking_service import tool_query_rank


HOST_LABELS = {
    "maya": "Maya",
    "unreal": "Unreal",
    "blender": "Blender",
    "houdini": "Houdini",
    "substance_painter": "Substance Painter",
    "motionbuilder": "MotionBuilder",
    "unity": "Unity",
    "3dsmax": "3ds Max",
    "photoshop": "Photoshop",
    "gimp": "GIMP",
    "desktop": "Desktop",
}

HOST_TOOL_PACKAGES = {
    "maya": ("maya_tools",),
    "unreal": ("unreal_tools",),
    "blender": ("blender_tools",),
    "houdini": ("houdini_tools",),
    "substance_painter": ("substance_painter_tools",),
    "motionbuilder": ("motionbuilder_tools", "mobu_tools"),
    "unity": ("unity_tools",),
    "3dsmax": ("max_tools",),
    "photoshop": (),
    "gimp": (),
    "desktop": (),
}

_CONNECTED_ACCOUNT_BY_APP = {
    "slack": "slack",
    "discord": "discord",
    "jira": "atlassian",
    "confluence": "atlassian",
}

_REFERENCE_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_./:-]+)")
_CLASS_REFERENCE_RE = re.compile(r"(?<!\w)(@?[A-Za-z0-9_]+)!([A-Za-z0-9_./:-]+)")
_FUNCTION_KINDS = {"function", "async_function", "method", "classmethod", "staticmethod"}


@dataclass(frozen=True)
class SmartSearchCandidate:
    """One insertable application action or indexed tool callable."""

    token: str
    label: str
    kind: str
    value: str
    source: str
    detail: str = ""
    priority: int = 50

    @property
    def continues(self) -> bool:
        """Whether insertion should immediately continue hierarchical completion."""

        return self.token.endswith((".", "/"))

    def display(self) -> str:
        suffix = f" - {self.detail}" if self.detail else ""
        prefix = "" if self.token.startswith("!") else "@"
        return f"{prefix}{self.token}  [{self.kind} | {self.source}]{suffix}"


def _normalized_package_dirs(
    package_dirs: Sequence[Path] | None,
) -> dict[str, Path]:
    paths = DCC_TOOL_PACKAGE_DIRS if package_dirs is None else package_dirs
    return {Path(path).name.lower(): Path(path) for path in paths}


def _host_for_name(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "unreal_engine": "unreal",
        "substance": "substance_painter",
        "mobu": "motionbuilder",
        "max": "3dsmax",
        "3ds_max": "3dsmax",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in HOST_LABELS else ""


def _matches(query: str, *values: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    return all(part in " ".join(values).lower() for part in needle.split())


def _tool_path_matches(query: str, *values: str) -> bool:
    needle = str(query or "").strip().lower().replace("\\", "/")
    if not needle:
        return True
    haystack = " ".join(str(value or "") for value in values).lower().replace("\\", "/")
    if needle in haystack:
        return True
    normalized_needle = re.sub(r"[./]+", ".", needle).strip(".")
    normalized_haystack = re.sub(r"[./]+", ".", haystack)
    if normalized_needle and normalized_needle in normalized_haystack:
        return True
    parts = [part for part in re.split(r"[\s./]+", needle) if part]
    return bool(parts) and all(part in normalized_haystack for part in parts)


def _same_tool_reference(left: str, right: str) -> bool:
    return re.sub(r"[\\/]+", ".", str(left or "").lower()).strip(".") == re.sub(
        r"[\\/]+", ".", str(right or "").lower()
    ).strip(".")


def _query_allows_private_symbols(query: str) -> bool:
    return any(part.startswith("_") for part in re.split(r"[\s./\\]+", str(query or "")) if part)


def _module_for_file(package: str, rel_path: str, module: str) -> str:
    normalized_module = str(module or "").strip(".")
    if normalized_module:
        return normalized_module
    path = str(rel_path or "").replace("\\", "/")
    marker = f"{package}/"
    index = path.lower().find(marker.lower())
    relative = path[index:] if index >= 0 else path
    if relative.lower().endswith(".py"):
        relative = relative[:-3]
    return relative.replace("/", ".").strip(".")


def _select_symbol_source_columns(connection: sqlite3.Connection) -> str:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(symbols)").fetchall()
    }
    source = "s.source" if "source" in columns else "''"
    start_line = "s.start_line" if "start_line" in columns else "0"
    return f"{source}, {start_line}"


def _class_base_text(source: str) -> str:
    match = re.search(r"\bclass\s+\w+\s*\(([^)]*)\)", source or "")
    return match.group(1) if match else ""


def _package_class_type_candidates(
    packages: Sequence[str],
    type_query: str,
    *,
    db_path: Path,
    limit: int,
    scoped: bool,
) -> list[SmartSearchCandidate]:
    """Read indexed classes whose base/type text matches ``type_query``."""

    if not db_path.exists():
        return []
    package_set = {package.lower() for package in packages}
    try:
        connection = sqlite3.connect(str(db_path), timeout=0.08)
        try:
            source_columns = _select_symbol_source_columns(connection)
            rows = connection.execute(
                f"""
                SELECT s.name, s.qualname, s.kind, s.signature, s.docstring,
                       f.rel_path, f.module, {source_columns}
                FROM symbols AS s
                JOIN files AS f ON f.id = s.file_id
                WHERE lower(s.kind) = 'class'
                ORDER BY s.name
                LIMIT 1200
                """
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return []

    query = str(type_query or "").strip().lower()
    candidates: dict[str, SmartSearchCandidate] = {}
    for name, qualname, kind, signature, docstring, rel_path, module, source, start_line in rows:
        rel = str(rel_path or "").replace("\\", "/")
        package = next((item for item in package_set if rel.lower().startswith(f"{item}/")), "")
        if not package:
            continue
        module_name = _module_for_file(package, rel, str(module or ""))
        symbol_name = str(qualname or name or "").strip(".")
        if not module_name or not symbol_name:
            continue
        full_name = symbol_name if symbol_name.startswith(f"{module_name}.") else f"{module_name}.{symbol_name}"
        if not full_name.lower().startswith(f"{package}."):
            full_name = f"{package}.{full_name}"
        relative_name = full_name[len(package) + 1 :]
        base_text = _class_base_text(str(source or ""))
        searchable = " ".join(
            [str(name or ""), relative_name, str(signature or ""), str(docstring or ""), base_text, str(source or ""), rel]
        )
        if query and query not in searchable.lower():
            continue
        token = f"{package}!{relative_name}" if scoped else f"!{full_name}"
        bases = base_text or str(signature or "")
        detail_parts = [rel]
        if start_line:
            detail_parts.append(f"line {start_line}")
        if bases:
            detail_parts.append(f"inherits {bases}")
        candidates[token.lower()] = SmartSearchCandidate(
            token=token,
            label=str(name or symbol_name),
            kind="tool class",
            value=full_name,
            source="project index",
            detail=" | ".join(detail_parts),
            priority=85,
        )
        if len(candidates) >= limit:
            break
    return list(candidates.values())


def _package_function_candidates(
    package: str,
    query: str,
    *,
    db_path: Path,
    limit: int,
) -> list[SmartSearchCandidate]:
    """Read package callables from the persistent project index without rescanning."""

    if not db_path.exists():
        return []
    rows: list[tuple[Any, ...]] = []
    try:
        connection = sqlite3.connect(str(db_path), timeout=0.08)
        try:
            rows = connection.execute(
                """
                SELECT s.name, s.qualname, s.kind, s.signature, s.docstring,
                       f.rel_path, f.module
                FROM symbols AS s
                JOIN files AS f ON f.id = s.file_id
                WHERE lower(replace(f.rel_path, '\\', '/')) LIKE ?
                ORDER BY CASE WHEN lower(s.name) = ? THEN 0
                              WHEN lower(s.name) LIKE ? THEN 1 ELSE 2 END,
                         s.name
                LIMIT 400
                """,
                (f"%{package.lower()}/%", query.lower(), f"{query.lower()}%"),
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return []

    candidates: dict[str, SmartSearchCandidate] = {}
    include_private = _query_allows_private_symbols(query)
    for name, qualname, kind, signature, docstring, rel_path, module in rows:
        if str(kind or "").lower() not in _FUNCTION_KINDS:
            continue
        if str(name or "").startswith("_") and not include_private:
            continue
        symbol_name = str(qualname or name or "").strip(".")
        if "." in symbol_name and not include_private:
            continue
        module_name = _module_for_file(package, str(rel_path or ""), str(module or ""))
        if not module_name or not symbol_name:
            continue
        full_name = symbol_name if symbol_name.startswith(f"{module_name}.") else f"{module_name}.{symbol_name}"
        if not full_name.lower().startswith(f"{package.lower()}."):
            full_name = f"{package}.{full_name}"
        relative_name = full_name[len(package) + 1 :]
    for name, qualname, kind, signature, docstring, rel_path, module in rows:
        if str(kind or "").lower() not in _FUNCTION_KINDS:
            continue
        if str(name or "").startswith("_") and not include_private:
            continue
        symbol_name = str(qualname or name or "").strip(".")
        if "." in symbol_name and not include_private:
            continue
        module_name = _module_for_file(package, str(rel_path or ""), str(module or ""))
        if not module_name or not symbol_name:
            continue
        full_name = symbol_name if symbol_name.startswith(f"{module_name}.") else f"{module_name}.{symbol_name}"
        if not full_name.lower().startswith(f"{package.lower()}."):
            full_name = f"{package}.{full_name}"
        relative_name = full_name[len(package) + 1 :]
        searchable = " ".join(
            [str(name or ""), relative_name, str(signature or ""), str(docstring or ""), str(rel_path or "")]
        )
        if not _tool_path_matches(query, searchable):
            continue
        token = f"{package}/{relative_name}"
        key = token.lower()
        candidates[key] = SmartSearchCandidate(
            token=token,
            label=str(name or symbol_name),
            kind="tool function",
            value=full_name,
            source="project index",
            detail=f"{rel_path}{signature or ''}",
            priority=80,
        )
        if len(candidates) >= max(limit * 8, 80):
            break
    terms = re.findall(r"[a-z0-9]+", str(query or "").lower().replace("_", " "))
    return sorted(
        candidates.values(),
        key=lambda item: tool_query_rank(
            {
                "name": item.label.lower(),
                "label_lower": item.token.lower(),
                "path_lower": item.detail.lower(),
                "detail_lower": item.detail.lower(),
                "priority": item.priority,
            },
            terms,
            priority_desc=True,
        ),
    )[:limit]


def _application_candidates(
    host: str,
    query: str,
    *,
    package_dirs: dict[str, Path],
    db_path: Path,
    limit: int,
) -> list[SmartSearchCandidate]:
    label = HOST_LABELS[host]
    results: list[SmartSearchCandidate] = []
    for key, operation in dcc_operation_registry(host).items():
        description = str(getattr(operation, "description", "") or "")
        operation_label = str(getattr(operation, "label", key) or key)
        if not _matches(query, key, operation_label, description):
            continue
        results.append(
            SmartSearchCandidate(
                token=f"{label}.{key}",
                label=operation_label,
                kind="DCC operation",
                value=key,
                source=f"{label} operation registry",
                detail=description,
                priority=100,
            )
        )

    for package in HOST_TOOL_PACKAGES.get(host, ()):
        if package not in package_dirs:
            continue
        results.extend(
            _package_function_candidates(
                package,
                query,
                db_path=db_path,
                limit=max(limit, 20),
            )
        )
    terms = re.findall(r"[a-z0-9]+", str(query or "").lower().replace("_", " "))
    return sorted(
        results,
        key=lambda item: tool_query_rank(
            {
                "name": item.label.lower(),
                "label_lower": item.token.lower(),
                "path_lower": item.detail.lower(),
                "detail_lower": item.detail.lower(),
                "priority": item.priority,
            },
            terms,
            priority_desc=True,
        ),
    )[:limit]


def _app_context_for_name(value: str):
    """Resolve non-DCC applications through the shared application registry."""

    try:
        from tech_connector.services.app_context_service import app_context_for_token

        return app_context_for_token(value)
    except Exception:
        return None


def _connection_detail(app_id: str, settings: dict[str, Any] | None) -> tuple[bool | None, str]:
    """Return a sanitized connection summary without ever exposing credentials."""

    account_id = _CONNECTED_ACCOUNT_BY_APP.get(str(app_id or "").lower())
    if not account_id:
        return None, "installed integration"
    try:
        from tech_connector.services.connected_account_service import connected_account_status

        status = connected_account_status(dict(settings or {}), account_id)
        connected = bool(status.get("connected"))
        mode = str(status.get("mode") or "").strip()
        if connected:
            return True, f"connected ({mode})" if mode else "connected"
        missing = ", ".join(str(item) for item in status.get("missing_fields") or [] if item)
        detail = mode or "not configured"
        if missing:
            detail = f"{detail}; missing {missing}"
        return False, detail
    except Exception:
        return False, "connection status unavailable"


def _safe_reference_segment(value: str) -> str:
    text = str(value or "").strip().lstrip("@#")
    text = re.sub(r"\s+", "_", text)
    return re.sub(r"[^A-Za-z0-9_-]+", "", text)


def _connected_application_candidates(
    context: Any,
    query: str,
    *,
    settings: dict[str, Any] | None,
    limit: int,
) -> list[SmartSearchCandidate]:
    """Build target completions for messaging, ops, and installed integrations."""

    app_id = str(getattr(context, "id", "") or "").lower()
    connected, status_detail = _connection_detail(app_id, settings)
    settings = dict(settings or {})
    if app_id == "jira":
        project_values = [
            settings.get("jira_project_key") or settings.get("atlassian_project_key"),
            *(settings.get("jira_projects") or []),
        ]
        projects = list(dict.fromkeys(_safe_reference_segment(item) for item in project_values if item))
        if "." in query:
            project_query, issue_query = query.split(".", 1)
            project = next((item for item in projects if item.casefold() == project_query.casefold()), "")
            if not project:
                return []
            actions = ("task", "bug", "story", "epic", "subtask")
            return [
                SmartSearchCandidate(
                    token=f"{context.name}.{project}.{action}",
                    label=f"Create {action.replace('subtask', 'sub-task')}",
                    kind="Jira issue target",
                    value=f"{project}.{action}",
                    source=context.name,
                    detail=f"project {project}; {status_detail}",
                    priority=95 if connected else 70,
                )
                for action in actions
                if not issue_query or action.startswith(issue_query.lower())
            ][:limit]
        return [
            SmartSearchCandidate(
                token=f"{context.name}.{project}.",
                label=project,
                kind="Jira project",
                value=project,
                source=context.name,
                detail=f"choose an issue type; {status_detail}",
                priority=95 if connected else 70,
            )
            for project in projects
            if _matches(query, project)
        ][:limit]
    if app_id == "confluence":
        space_values = [
            settings.get("confluence_space_id"),
            *(settings.get("confluence_spaces") or []),
        ]
        spaces = list(dict.fromkeys(_safe_reference_segment(item) for item in space_values if item))
        return [
            SmartSearchCandidate(
                token=f"{context.name}.{space}",
                label=space,
                kind="Confluence space",
                value=space,
                source=context.name,
                detail=f"new page destination; {status_detail}",
                priority=95 if connected else 70,
            )
            for space in spaces
            if _matches(query, space)
        ][:limit]

    try:
        from tech_connector.services.asset_mention_service import candidates_from_app_context

        targets = candidates_from_app_context(context, settings=settings)
    except Exception:
        targets = []
    results: list[SmartSearchCandidate] = []
    for target in targets:
        segment = _safe_reference_segment(getattr(target, "token", ""))
        if not segment:
            continue
        label = str(getattr(target, "label", "") or segment)
        value = str(getattr(target, "value", "") or segment)
        detail = str(getattr(target, "detail", "") or "application target")
        if not _matches(query, segment, label, value, detail):
            continue
        results.append(
            SmartSearchCandidate(
                token=f"{_safe_reference_segment(context.name) or context.id}.{segment}",
                label=label,
                kind=str(getattr(target, "kind", "integration target") or "integration target"),
                value=value,
                source=context.name,
                detail=f"{detail}; {status_detail}",
                priority=95 if connected else 70,
            )
        )
    return sorted(results, key=lambda item: (-item.priority, item.token.lower()))[:limit]


def _connected_application_roots(
    query: str,
    *,
    settings: dict[str, Any] | None,
) -> list[SmartSearchCandidate]:
    try:
        from tech_connector.services.app_context_service import installed_app_contexts

        contexts = installed_app_contexts()
    except Exception:
        return []
    results: list[SmartSearchCandidate] = []
    for context in contexts:
        if _host_for_name(context.id):
            continue
        if not _matches(query, context.id, context.name, context.category, *context.aliases):
            continue
        connected, status_detail = _connection_detail(context.id, settings)
        results.append(
            SmartSearchCandidate(
                token=f"{_safe_reference_segment(context.name) or context.id}.",
                label=context.name,
                kind=(
                    "connected application"
                    if connected is True
                    else "application setup required"
                    if connected is False
                    else "installed integration"
                ),
                value=context.id,
                source="application registry",
                detail=f"targets and references; {status_detail}",
                priority=110 if connected else 80,
            )
        )
    return results


def _global_package_function_candidates(
    query: str,
    *,
    package_dirs: dict[str, Path],
    db_path: Path,
    limit: int,
) -> list[SmartSearchCandidate]:
    results: list[SmartSearchCandidate] = []
    if not str(query or "").strip():
        return results
    for package in package_dirs:
        results.extend(
            _package_function_candidates(
                package,
                query,
                db_path=db_path,
                limit=max(limit, 12),
            )
        )
    terms = re.findall(r"[a-z0-9]+", str(query or "").lower().replace("_", " "))
    deduped: dict[str, SmartSearchCandidate] = {}
    for item in results:
        existing = deduped.get(item.token.lower())
        if existing is None or item.priority > existing.priority:
            deduped[item.token.lower()] = item
    return sorted(
        deduped.values(),
        key=lambda item: tool_query_rank(
            {
                "name": item.label.lower(),
                "label_lower": item.token.lower(),
                "path_lower": item.detail.lower(),
                "detail_lower": item.detail.lower(),
                "priority": item.priority,
            },
            terms,
            priority_desc=True,
        ),
    )[:limit]


def smart_search_suggestions(
    query: str,
    *,
    active_hosts: Iterable[str] = (),
    package_dirs: Sequence[Path] | None = None,
    db_path: Path | None = None,
    limit: int = 20,
    settings: dict[str, Any] | None = None,
) -> list[SmartSearchCandidate]:
    """Return hierarchical suggestions for text following ``@``.

    ``Application.`` searches registered host operations and associated indexed
    tools. ``package.`` searches indexed Python modules/functions beneath that
    package. Slash package references are accepted as compatibility input, but
    function suggestions are emitted as real dotted Python paths.
    """

    db_path = Path(db_path) if db_path is not None else project_index_db_path()
    text = str(query or "").strip()
    packages = _normalized_package_dirs(package_dirs)
    active = {_host_for_name(host) for host in active_hosts}

    if text.startswith("!"):
        return _package_class_type_candidates(
            tuple(packages),
            text[1:],
            db_path=Path(db_path),
            limit=limit,
            scoped=False,
        )

    if "!" in text:
        package_name, type_query = text.split("!", 1)
        package = package_name.lower()
        if package not in packages:
            return []
        return _package_class_type_candidates(
            (package,),
            type_query,
            db_path=Path(db_path),
            limit=limit,
            scoped=True,
        )

    if "/" in text:
        package_name, function_query = text.split("/", 1)
        package = package_name.lower()
        if package not in packages:
            return []
        return _package_function_candidates(
            package,
            function_query,
            db_path=Path(db_path),
            limit=limit,
        )

    if "." in text:
        owner, action_query = text.split(".", 1)
        host = _host_for_name(owner)
        if host:
            return _application_candidates(
                host,
                action_query,
                package_dirs=packages,
                db_path=Path(db_path),
                limit=limit,
            )
        app_context = _app_context_for_name(owner)
        if app_context is not None:
            return _connected_application_candidates(
                app_context,
                action_query,
                settings=settings,
                limit=limit,
            )
        package = owner.lower()
        if package in packages:
            return _package_function_candidates(
                package,
                action_query,
                db_path=Path(db_path),
                limit=limit,
            )
        return []

    roots: list[SmartSearchCandidate] = []
    for host, label in HOST_LABELS.items():
        if not _matches(text, host, label):
            continue
        connected = host in active
        roots.append(
            SmartSearchCandidate(
                token=f"{label}.",
                label=label,
                kind="active application" if connected else "application",
                value=host,
                source="DCC registry",
                detail="live session operations and available tools" if connected else "registered operations and available tools",
                priority=120 if connected else 100,
            )
        )
    for package, path in packages.items():
        if not _matches(text, package):
            continue
        roots.append(
            SmartSearchCandidate(
                token=f"{package}/",
                label=package,
                kind="tool package",
                value=str(path),
                source="project intelligence",
                detail="indexed functions only",
                priority=90,
            )
        )
    roots.extend(_connected_application_roots(text, settings=settings))
    function_matches = _global_package_function_candidates(
        text,
        package_dirs=packages,
        db_path=Path(db_path),
        limit=limit,
    )
    combined: dict[str, SmartSearchCandidate] = {}
    for item in [*function_matches, *roots]:
        existing = combined.get(item.token.lower())
        if existing is None or item.priority > existing.priority:
            combined[item.token.lower()] = item
    terms = re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))
    return sorted(
        combined.values(),
        key=lambda item: tool_query_rank(
            {
                "name": item.label.lower(),
                "label_lower": item.token.lower(),
                "path_lower": item.detail.lower(),
                "detail_lower": item.detail.lower(),
                "priority": item.priority,
            },
            terms,
            priority_desc=True,
        ),
    )[:limit]


def active_hosts_from_context(context: str) -> tuple[str, ...]:
    """Extract active hosts from the command router's cached context string."""

    lower = str(context or "").lower()
    return tuple(host for host, label in HOST_LABELS.items() if f"active dcc host: {label.lower()}" in lower)


def smart_search_context_block(
    text: str,
    *,
    db_path: Path | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    """Resolve selected Smart Search references into deterministic prompt evidence."""

    db_path = Path(db_path) if db_path is not None else project_index_db_path()
    lines: list[str] = []
    seen: set[str] = set()
    package_dirs = _normalized_package_dirs(None)
    for match in _REFERENCE_RE.finditer(text or ""):
        token = match.group(1).rstrip(".,;:")
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        if "." in token and "/" not in token:
            owner, operation_key = token.split(".", 1)
            host = _host_for_name(owner)
            operation = dcc_operation_registry(host).get(operation_key) if host else None
            if operation is not None:
                lines.append(
                    f"- @{token}: registered {HOST_LABELS[host]} operation `{operation_key}`; "
                    f"callable `{getattr(operation, 'function', '')}`"
                )
                continue
            if host:
                matches = _application_candidates(
                    host,
                    operation_key,
                    package_dirs=package_dirs,
                    db_path=Path(db_path),
                    limit=5,
                )
                item = matches[0] if matches else None
                if item:
                    if item.kind == "DCC operation":
                        lines.append(
                            f"- @{token}: matched {HOST_LABELS[host]} operation `{item.value}`; "
                            f"candidate token `@{item.token}`"
                        )
                    else:
                        lines.append(
                            f"- @{token}: matched indexed tool function `{item.value}` from `{item.detail}`"
                        )
                    continue
            app_context = _app_context_for_name(owner)
            if app_context is not None:
                connected, status_detail = _connection_detail(app_context.id, settings)
                matches = _connected_application_candidates(
                    app_context,
                    operation_key,
                    settings=settings,
                    limit=20,
                )
                exact = next(
                    (item for item in matches if item.token.lower() == token.lower()),
                    None,
                )
                if exact is not None:
                    readiness = "ready" if connected else "setup required"
                    lines.append(
                        f"- @{token}: {app_context.name} target `{exact.value}`; "
                        f"connection={readiness} ({status_detail}). Do not silently substitute another target."
                    )
                else:
                    lines.append(
                        f"- @{token}: unresolved {app_context.name} target; connection={status_detail}. "
                        "Resolve or ask for clarification before acting."
                    )
                continue
            if owner.lower() in package_dirs:
                matches = _package_function_candidates(
                    owner.lower(), operation_key, db_path=Path(db_path), limit=10
                )
                exact = next((item for item in matches if _same_tool_reference(item.token, token)), None)
                item = exact or (matches[0] if matches else None)
                if item:
                    lines.append(
                        f"- @{token}: indexed tool function `{item.value}` from `{item.detail}`"
                    )
                    continue
        if "/" in token:
            package, function_name = token.split("/", 1)
            if package.lower() in package_dirs:
                matches = _package_function_candidates(
                    package.lower(), function_name, db_path=Path(db_path), limit=10
                )
                exact = next((item for item in matches if _same_tool_reference(item.token, token)), None)
                item = exact or (matches[0] if matches else None)
                if item:
                    lines.append(
                        f"- @{token}: indexed tool function `{item.value}` from `{item.detail}`"
                    )
                    continue
                lines.append(f"- @{token}: requested function in tool package `{package}`; exact index evidence unresolved")
    for match in _CLASS_REFERENCE_RE.finditer(text or ""):
        owner = (match.group(1) or "").lstrip("@")
        class_name = match.group(2).rstrip(".,;:")
        package = owner.lower()
        if package and package in package_dirs:
            matches = _package_class_type_candidates(
                (package,), class_name, db_path=Path(db_path), limit=10, scoped=True
            )
        else:
            matches = _package_class_type_candidates(
                tuple(package_dirs), class_name, db_path=Path(db_path), limit=10, scoped=False
            )
        exact_token = f"{package}!{class_name}".lower() if package else f"!{class_name}".lower()
        exact = next((item for item in matches if item.token.lower() == exact_token), None)
        item = exact or (matches[0] if matches else None)
        if item:
            lines.append(
                f"- {item.display().split('  ', 1)[0]}: indexed tool class `{item.value}` from `{item.detail}`"
            )
    if not lines:
        return ""
    return "Smart Search DCC Context:\n" + "\n".join(lines)

