"""Project root model."""

from pathlib import Path
from typing import Optional

from tech_connector.models.constants import ASSUMED_DIRS, EXTERNAL_TOOLS_DIR, TOOLS_ROOT


def _unique_roots(paths) -> list[str]:
    """Normalize roots once while preserving their user-visible priority."""
    roots: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_project_path(path)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            roots.append(normalized)
    return roots


def all_roots(settings: dict) -> list[str]:
    active_proj = settings.get("active_project", "")
    ext_tools = settings.get("external_tools_dir", "") or str(EXTERNAL_TOOLS_DIR)
    try:
        from tech_connector.services.project_directory_service import resolve_project_directories

        directories = resolve_project_directories(settings)
        workspace_roots = [
            str(directories.tools_project),
            str(directories.game_project),
            str(directories.art_source),
        ]
    except Exception:
        workspace_roots = []
    candidates = [
        active_proj,
        *settings.get("extra_dirs", []),
        TOOLS_ROOT,
        *workspace_roots,
        ext_tools,
        *ASSUMED_DIRS,
    ]
    return _unique_roots(candidates)



def normalize_project_path(path: str) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(Path(path).expanduser())


def recent_projects(settings: dict) -> list[str]:
    seen = set()
    projects = []
    for path in settings.get("recent_projects", []):
        normalized = normalize_project_path(path)
        if normalized and normalized not in seen:
            seen.add(normalized)
            projects.append(normalized)
    return projects


def set_active_project(settings: dict, path: str, limit: int = 12) -> str:
    normalized = normalize_project_path(path)
    settings["active_project"] = normalized
    if normalized:
        recents = [normalized]
        for existing in recent_projects(settings):
            if existing != normalized:
                recents.append(existing)
        settings["recent_projects"] = recents[:limit]
    return normalized


def project_roots(settings: dict) -> list[str]:
    """Return the ordered multi-folder project scope.

    The active folder is the write/default root. Extra folders are user-owned
    read/search roots. The installed Tech Connector tools root is permanent so
    prompts and pipelines can always resolve the product's own APIs.
    """
    active = normalize_project_path(settings.get("active_project", ""))
    return _unique_roots(
        [active, *settings.get("extra_dirs", []), TOOLS_ROOT]
    )


def dcc_tool_roots(settings: Optional[dict] = None) -> list[str]:
    roots = []
    for path in ASSUMED_DIRS:
        name = Path(path).name.lower()
        if name.endswith("_tools") or name == "mobu_tools":
            normalized = normalize_project_path(path)
            if normalized and normalized not in roots:
                roots.append(normalized)
    return roots


def search_scope_roots(settings: dict, scope: str = "project") -> list[str]:
    """Return roots appropriate for project-scoped indexed search.

    The active project should be preferred for editor questions. Broader roots
    can still be indexed, but search/ranking should not treat installed engines,
    stdlib, or third-party packages as first-party project code.
    """
    active = normalize_project_path(settings.get("active_project", ""))
    if scope in {"project", "strict_project"} and active:
        return [active]
    return all_roots(settings)
