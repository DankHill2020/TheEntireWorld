from installers.install_substance_painter_bridge import (
    default_plugin_dir,
    install_to_plugin_dir,
    plugin_dir_candidates,
    plugin_needs_install,
)
from services.dcc_bridge_setup import substance_painter_script_editor_snippet


def test_substance_painter_installer_uses_adobe_documents_path(tmp_path):
    candidates = plugin_dir_candidates(tmp_path)

    assert candidates[0] == tmp_path / "Documents" / "Adobe" / "Adobe Substance 3D Painter" / "python" / "plugins"
    assert default_plugin_dir(tmp_path) == candidates[0]


def test_substance_painter_installer_writes_plugin(tmp_path):
    plugin_dir = tmp_path / "Documents" / "Adobe" / "Adobe Substance 3D Painter" / "python" / "plugins"

    assert plugin_needs_install(plugin_dir) is True
    target = install_to_plugin_dir(plugin_dir)

    assert target == plugin_dir / "the_entire_world_ai_studio_bridge.py"
    assert target.exists()
    assert plugin_needs_install(plugin_dir) is False


def test_substance_painter_script_editor_snippet_installs_and_starts_bridge(tmp_path):
    snippet = substance_painter_script_editor_snippet(tmp_path)

    assert str(tmp_path) in snippet
    assert "install_substance_painter_bridge.install_to_plugin_dir" in snippet
    assert "substance_painter_ai_studio_bridge.start_plugin()" in snippet
