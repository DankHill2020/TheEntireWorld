from __future__ import annotations

from pathlib import Path

from tech_connector.api import _project_roots as api_project_roots
from tech_connector.models.constants import TOOLS_ROOT
from tech_connector.models.project import project_roots
from tech_connector.services.application_service import ApplicationService


def _resolved(path: Path) -> str:
    return str(path.resolve())


def test_project_scope_keeps_primary_extras_and_installed_tools(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    art = tmp_path / "art"
    primary.mkdir()
    art.mkdir()

    roots = project_roots(
        {
            "active_project": str(primary),
            "extra_dirs": [str(art), str(primary), str(art)],
        }
    )

    assert roots == [_resolved(primary), _resolved(art), _resolved(TOOLS_ROOT)]


def test_headless_api_uses_the_same_multi_folder_scope(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    art = tmp_path / "art"
    primary.mkdir()
    art.mkdir()

    roots = api_project_roots(
        primary,
        {"active_project": str(primary), "extra_dirs": [str(art)]},
    )

    assert roots == [_resolved(primary), _resolved(art), _resolved(TOOLS_ROOT)]


def test_secondary_folders_can_be_added_and_removed_without_changing_primary(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    art = tmp_path / "art"
    primary.mkdir()
    art.mkdir()
    saved: list[dict] = []
    service = ApplicationService.__new__(ApplicationService)
    service.settings = {"active_project": str(primary), "extra_dirs": []}
    service.project_directories = type("Directories", (), {"tools_project": primary})()
    service.save_settings = lambda settings=None: saved.append(dict(service.settings))

    assert service.add_project_folder(str(art)) == _resolved(art)
    assert service.add_project_folder(str(art)) == _resolved(art)
    assert service.settings["active_project"] == str(primary)
    assert service.settings["extra_dirs"] == [_resolved(art)]
    assert service.remove_project_folder(str(primary)) is False
    assert service.remove_project_folder(str(TOOLS_ROOT)) is False
    assert service.remove_project_folder(str(art)) is True
    assert service.settings["extra_dirs"] == []
    assert len(saved) == 2
