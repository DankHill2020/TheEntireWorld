from __future__ import annotations

import ast
import importlib
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = PACKAGE_ROOT / "services" / "dcc"
CORE_ROOTS = (
    PACKAGE_ROOT / "game_engine" / "scene",
    PACKAGE_ROOT / "game_engine" / "authoring",
    PACKAGE_ROOT / "game_engine" / "deformation",
    PACKAGE_ROOT / "game_engine" / "runtime",
)


def _legacy_target(path: Path) -> str:
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


def test_legacy_dcc_modules_are_true_game_engine_aliases() -> None:
    wrappers = sorted(path for path in LEGACY_ROOT.glob("*.py") if path.name != "__init__.py")
    assert wrappers

    for path in wrappers:
        target = _legacy_target(path)
        assert target.startswith("tech_connector.game_engine."), path.name
        legacy_name = f"tech_connector.services.dcc.{path.stem}"
        assert importlib.import_module(legacy_name) is importlib.import_module(target)


def test_headless_game_engine_core_has_no_legacy_qt_or_integration_imports() -> None:
    forbidden = (
        "tech_connector.services.dcc",
        "tech_connector.game_engine.integration",
        "PyQt",
        "PySide",
    )
    for root in CORE_ROOTS:
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            assert not any(token in source for token in forbidden), path
