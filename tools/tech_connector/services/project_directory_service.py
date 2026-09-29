"""Resolve the tools, game, and art roots for a Tech Connector workspace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from tech_connector.models.constants import TOOLS_ROOT


TOOLS_PROJECT_ENV = "TECH_CONNECTOR_TOOLS_PROJECT_ROOT"
GAME_PROJECT_ENV = "TECH_CONNECTOR_GAME_PROJECT_ROOT"
ART_SOURCE_ENV = "TECH_CONNECTOR_ART_SOURCE_ROOT"


def _resolved(value: Any, fallback: Path) -> Path:
    text = str(value or "").strip()
    try:
        return Path(text).expanduser().resolve() if text else fallback.resolve()
    except (OSError, RuntimeError):
        return Path(text).expanduser() if text else fallback


@dataclass(frozen=True)
class ProjectDirectories:
    tools_project: Path
    game_project: Path
    art_source: Path
    custom_game_project: bool = False
    custom_art_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("tools_project", "game_project", "art_source"):
            data[key] = str(data[key])
        data["game_project_kind"] = detect_game_project_kind(self.game_project)
        data["asset_search_roots"] = [str(path) for path in self.asset_search_roots()]
        return data

    def asset_search_roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        for path in (self.art_source, self.game_project, self.tools_project):
            if path not in roots:
                roots.append(path)
        return tuple(roots)


def resolve_project_directories(settings: Mapping[str, Any] | None = None) -> ProjectDirectories:
    values = settings or {}
    tools = _resolved(
        values.get("tools_project_dir") or values.get("active_project"),
        TOOLS_ROOT,
    )
    custom_game = bool(values.get("custom_game_project_dir", False))
    custom_art = bool(values.get("custom_art_source_dir", False))
    game_default = tools / "TCGame"
    game = _resolved(values.get("game_project_dir"), game_default) if custom_game else game_default
    art_default = game / "ArtSource"
    art = _resolved(values.get("art_source_dir"), art_default) if custom_art else art_default
    return ProjectDirectories(tools, game, art, custom_game, custom_art)


def update_project_directory_settings(
    settings: MutableMapping[str, Any],
    *,
    tools_project: str | os.PathLike[str],
    custom_game_project: bool = False,
    game_project: str | os.PathLike[str] | None = None,
    custom_art_source: bool = False,
    art_source: str | os.PathLike[str] | None = None,
) -> ProjectDirectories:
    tools = _resolved(tools_project, TOOLS_ROOT)
    settings["tools_project_dir"] = str(tools)
    settings["active_project"] = str(tools)
    settings["custom_game_project_dir"] = bool(custom_game_project)
    settings["custom_art_source_dir"] = bool(custom_art_source)
    if game_project is not None:
        settings["game_project_dir"] = str(_resolved(game_project, tools / "TCGame"))
    if art_source is not None:
        game_fallback = _resolved(game_project, tools / "TCGame")
        settings["art_source_dir"] = str(_resolved(art_source, game_fallback / "ArtSource"))
    directories = resolve_project_directories(settings)
    apply_project_directory_environment(directories)
    return directories


def apply_project_directory_environment(
    directories: ProjectDirectories | Mapping[str, Any],
) -> ProjectDirectories:
    resolved = (
        directories
        if isinstance(directories, ProjectDirectories)
        else resolve_project_directories(directories)
    )
    os.environ[TOOLS_PROJECT_ENV] = str(resolved.tools_project)
    os.environ[GAME_PROJECT_ENV] = str(resolved.game_project)
    os.environ[ART_SOURCE_ENV] = str(resolved.art_source)
    return resolved


def detect_game_project_kind(path: str | os.PathLike[str]) -> str:
    root = Path(path)
    if root.suffix.casefold() == ".uproject" or any(root.glob("*.uproject")):
        return "unreal"
    if (root / "ProjectSettings" / "ProjectVersion.txt").exists() and (root / "Assets").is_dir():
        return "unity"
    if (root / "project.godot").is_file():
        return "godot"
    if any(root.glob("*.tcscene")) or (root / ".tech_connector_project").exists():
        return "tech_connector"
    return "folder"


def initialize_tc_project_directories(
    directories: ProjectDirectories,
    *,
    create_game: bool = True,
    create_art: bool = True,
) -> tuple[Path, ...]:
    created: list[Path] = []
    for enabled, path in (
        (create_game and not directories.custom_game_project, directories.game_project),
        (create_art and not directories.custom_art_source, directories.art_source),
    ):
        if enabled:
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    if create_game and not directories.custom_game_project:
        from tech_connector.licensing.project_identity import ensure_project_identity

        ensure_project_identity(directories.game_project)
    return tuple(created)


def project_directories_from_environment() -> ProjectDirectories:
    tools = _resolved(os.environ.get(TOOLS_PROJECT_ENV), TOOLS_ROOT)
    game = _resolved(os.environ.get(GAME_PROJECT_ENV), tools / "TCGame")
    art = _resolved(os.environ.get(ART_SOURCE_ENV), game / "ArtSource")
    return ProjectDirectories(
        tools,
        game,
        art,
        bool(os.environ.get(GAME_PROJECT_ENV)),
        bool(os.environ.get(ART_SOURCE_ENV)),
    )


def resolve_project_asset_path(
    value: str | os.PathLike[str] | None,
    directories: ProjectDirectories | None = None,
) -> Path | None:
    """Resolve an authored asset using Art, Game, then Tools search precedence."""
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve() if candidate.is_file() else None
    roots = directories or project_directories_from_environment()
    for root in roots.asset_search_roots():
        resolved = (root / candidate).resolve()
        if resolved.is_file():
            return resolved
    return None
