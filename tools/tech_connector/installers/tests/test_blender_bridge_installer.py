from pathlib import Path

from installers.install_blender_bridge import discover_versions, install_to_version, select_versions, version_needs_install
from services.dcc_bridge_setup import blender_script_editor_snippet


def test_blender_installer_selects_latest_version(tmp_path):
    root = tmp_path / "Blender Foundation" / "Blender"
    (root / "3.6").mkdir(parents=True)
    (root / "4.1").mkdir()
    (root / "4.0").mkdir()

    assert discover_versions(root) == ["3.6", "4.0", "4.1"]
    assert select_versions(root) == ["4.1"]


def test_blender_installer_writes_addon_and_startup_hook(tmp_path):
    version_root = tmp_path / "Blender Foundation" / "Blender" / "4.1"

    assert version_needs_install(version_root) is True

    addon_target, startup_target = install_to_version(version_root)

    assert addon_target == version_root / "scripts" / "addons" / "the_entire_world_ai_studio_bridge.py"
    assert startup_target == version_root / "scripts" / "startup" / "the_entire_world_ai_studio_bridge_startup.py"
    assert addon_target.exists()
    assert startup_target.exists()

    startup_code = startup_target.read_text(encoding="utf-8")
    assert "the_entire_world_ai_studio_bridge" in startup_code
    assert "module.register()" in startup_code
    assert version_needs_install(version_root) is False


def test_blender_script_editor_snippet_installs_and_starts_bridge(tmp_path):
    snippet = blender_script_editor_snippet(tmp_path)

    assert str(tmp_path) in snippet
    assert "install_blender_bridge.install_to_version" in snippet
    assert "blender_ai_studio_bridge_addon.register()" in snippet
