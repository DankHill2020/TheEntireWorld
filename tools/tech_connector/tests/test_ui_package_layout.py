"""Architecture tests for domain-owned viewer and editor UI packages."""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TECH_CONNECTOR_GPU_VIEWPORT", "0")
os.environ.setdefault("TECH_CONNECTOR_DCC_VIEWPORT_STREAM", "0")

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = PACKAGE_ROOT / "ui"

EXPECTED_PACKAGES = {
    "dcc_viewer": UI_ROOT / "dcc_viewer",
    "mesh_painter": UI_ROOT / "dcc_viewer" / "mesh_painter",
    "game_engine": UI_ROOT / "game_engine",
    "image_viewer": UI_ROOT / "image_viewer",
}

REPRESENTATIVE_ALIASES = {
    "tech_connector.ui.scene_document_lifecycle": (
        "tech_connector.ui.dcc_viewer.scene_document_lifecycle"
    ),
    "tech_connector.ui.three_d_mesh_painter_widget": (
        "tech_connector.ui.dcc_viewer.mesh_painter.widget"
    ),
    "tech_connector.ui.animation_timeline_widget": (
        "tech_connector.ui.game_engine.animation_timeline"
    ),
    "tech_connector.ui.image_editor_canvas": (
        "tech_connector.ui.image_viewer.canvas"
    ),
    "tech_connector.services.engine_console_service": (
        "tech_connector.game_engine.runtime.engine_console_service"
    ),
    "tech_connector.viewer_cmds": (
        "tech_connector.game_engine.integration.viewer_commands"
    ),
}


def _alias_target(path: Path) -> str:
    """Read the canonical target from a compatibility alias.

    :param path: Alias module path.
    :return: Canonical import target.
    """

    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_import_module" or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""


def test_viewer_packages_have_clear_documented_ownership() -> None:
    """Every viewer domain should be a documented Python package.

    :return: None.
    """

    for path in EXPECTED_PACKAGES.values():
        assert (path / "__init__.py").is_file(), path
    assert (UI_ROOT / "README.md").is_file()


def test_legacy_entry_points_are_small_aliases() -> None:
    """Compatibility paths should contain no duplicate implementation.

    :return: None.
    """

    for legacy_name, canonical_name in REPRESENTATIVE_ALIASES.items():
        path = PACKAGE_ROOT.parent.joinpath(*legacy_name.split(".")).with_suffix(".py")
        assert path.is_file(), legacy_name
        assert len(path.read_text(encoding="utf-8-sig").splitlines()) <= 12
        assert _alias_target(path) == canonical_name


def test_representative_legacy_imports_share_canonical_module_identity() -> None:
    """Legacy imports must preserve monkeypatch and singleton behavior.

    :return: None.
    """

    for legacy_name, canonical_name in REPRESENTATIVE_ALIASES.items():
        assert importlib.import_module(legacy_name) is importlib.import_module(
            canonical_name
        )


def test_canonical_packages_do_not_import_legacy_viewer_paths() -> None:
    """New implementations should depend only on canonical domain paths.

    :return: None.
    """

    forbidden = (
        "tech_connector.ui.three_d_mesh_painter_",
        "tech_connector.ui.image_editor_",
        "tech_connector.ui.sequence_viewport_workspace_widget",
        "tech_connector.ui.animation_timeline_widget",
        "tech_connector.ui.scene_document_",
        "tech_connector.ui.mesh_component_picker",
    )
    for root in EXPECTED_PACKAGES.values():
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            assert not any(value in source for value in forbidden), path

