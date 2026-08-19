import os
from pathlib import Path

from tech_connector.services.project_directory_service import (
    ART_SOURCE_ENV,
    GAME_PROJECT_ENV,
    TOOLS_PROJECT_ENV,
    apply_project_directory_environment,
    detect_game_project_kind,
    initialize_tc_project_directories,
    resolve_project_asset_path,
    resolve_project_directories,
    update_project_directory_settings,
)


def test_tc_defaults_follow_tools_project() -> None:
    directories = resolve_project_directories({"active_project": "C:/work/tools"})
    assert directories.tools_project == Path("C:/work/tools")
    assert directories.game_project == Path("C:/work/tools/TCGame")
    assert directories.art_source == Path("C:/work/tools/TCGame/ArtSource")
    assert directories.asset_search_roots() == (
        directories.art_source,
        directories.game_project,
        directories.tools_project,
    )


def test_custom_roots_can_be_toggled_without_discarding_values() -> None:
    settings = {}
    update_project_directory_settings(
        settings,
        tools_project="C:/work/tools",
        custom_game_project=True,
        game_project="D:/games/Example",
        custom_art_source=True,
        art_source="E:/art/Example",
    )
    assert resolve_project_directories(settings).game_project == Path("D:/games/Example")
    settings["custom_game_project_dir"] = False
    settings["custom_art_source_dir"] = False
    defaults = resolve_project_directories(settings)
    assert defaults.game_project == Path("C:/work/tools/TCGame")
    assert settings["game_project_dir"] == "D:\\games\\Example"


def test_environment_and_engine_detection(tmp_path) -> None:
    unreal = tmp_path / "UnrealProject"
    unreal.mkdir()
    (unreal / "Example.uproject").write_text("{}", encoding="utf-8")
    settings = {}
    directories = update_project_directory_settings(
        settings,
        tools_project=tmp_path / "tools",
        custom_game_project=True,
        game_project=unreal,
    )
    apply_project_directory_environment(directories)
    assert detect_game_project_kind(unreal) == "unreal"
    assert Path(os.environ[TOOLS_PROJECT_ENV]) == directories.tools_project
    assert Path(os.environ[GAME_PROJECT_ENV]) == directories.game_project
    assert Path(os.environ[ART_SOURCE_ENV]) == directories.art_source


def test_asset_paths_prefer_art_then_game_then_tools(tmp_path) -> None:
    directories = update_project_directory_settings(
        {},
        tools_project=tmp_path / "tools",
        custom_game_project=True,
        game_project=tmp_path / "game",
        custom_art_source=True,
        art_source=tmp_path / "art",
    )
    for root in directories.asset_search_roots():
        (root / "Materials").mkdir(parents=True)
        (root / "Materials" / "surface.png").write_text(root.name, encoding="utf-8")
    assert resolve_project_asset_path("Materials/surface.png", directories) == (
        directories.art_source / "Materials" / "surface.png"
    )


def test_default_tc_project_is_initialized_and_detectable(tmp_path) -> None:
    directories = resolve_project_directories({"active_project": str(tmp_path)})
    initialize_tc_project_directories(directories)
    assert directories.art_source.is_dir()
    assert detect_game_project_kind(directories.game_project) == "tech_connector"
