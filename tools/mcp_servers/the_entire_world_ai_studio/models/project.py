"""Project root model."""

from pathlib import Path
from typing import Optional

from models.constants import ASSUMED_DIRS, TOOLS_ROOT


def all_roots(settings: dict) -> list[str]:
    roots = []
    active_proj = settings.get("active_project", "")
    ext_tools = settings.get("external_tools_dir", "") or str(TOOLS_ROOT / "external_tools")
    candidates = [active_proj, ext_tools]
    for r in candidates + ASSUMED_DIRS + settings.get("extra_dirs", []):
        normalized = normalize_project_path(r)
        if normalized and normalized not in roots:
            roots.append(normalized)
    return [r for r in roots if r]



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
    active = normalize_project_path(settings.get("active_project", ""))
    if active:
        return [active]
    return all_roots(settings)


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
