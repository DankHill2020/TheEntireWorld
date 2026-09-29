from pathlib import Path
import sys
from types import ModuleType

from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.maya.maya_livelink_plugin import (
    BLOCK_BEGIN,
    BLOCK_END,
    LEGACY_MAYA_USER_SETUP_CODE,
    MAYA_USER_SETUP_CODE,
    find_maya_script_dirs,
    install_maya_livelink_plugin,
    installed_maya_versions,
    managed_bootstrap_block,
    render_user_setup,
    verify_maya_livelink_installation,
)


def test_managed_bootstrap_is_idempotent_and_preserves_unrelated_user_code() -> None:
    existing = "print('before')\n\nprint('after')\n"

    rendered = render_user_setup(existing)

    assert "print('before')" in rendered
    assert "print('after')" in rendered
    assert rendered.count(BLOCK_BEGIN) == 1
    assert rendered.count(BLOCK_END) == 1
    assert "maya_menu.initialize_command_port()" in rendered
    assert "Authenticated JSON Bridge Startup Script v3" in rendered
    assert render_user_setup(rendered) == rendered


def test_legacy_bootstrap_is_migrated_without_duplication() -> None:
    rendered = render_user_setup(LEGACY_MAYA_USER_SETUP_CODE)

    assert "Tech Connector Maya Live Link Startup Script" not in rendered
    assert rendered.count(BLOCK_BEGIN) == 1
    assert "TECH_CONNECTOR_MAYA_BRIDGE_VERSION = \"3\"" in rendered
    assert "maya_menu.initialize_command_port()" in rendered


def test_dry_run_reports_changes_without_touching_user_setup(tmp_path) -> None:
    script_dir = tmp_path / "maya" / "2026" / "scripts"

    result = install_maya_livelink_plugin([script_dir], dry_run=True)

    assert result["ok"]
    assert result["planned_paths"] == [str(script_dir / "userSetup.py")]
    assert not (script_dir / "userSetup.py").exists()


def test_install_is_atomic_verified_and_does_not_rewrite_current_file(tmp_path) -> None:
    script_dir = tmp_path / "maya" / "2026" / "scripts"
    script_dir.mkdir(parents=True)
    user_setup = script_dir / "userSetup.py"
    user_setup.write_text("print('studio startup')\n", encoding="utf-8")

    first = install_maya_livelink_plugin([script_dir])
    first_mtime = user_setup.stat().st_mtime_ns
    second = install_maya_livelink_plugin([script_dir])

    assert first["ok"]
    assert first["changed_paths"] == [str(user_setup)]
    assert second["ok"]
    assert second["changed_paths"] == []
    assert second["unchanged_paths"] == [str(user_setup)]
    assert user_setup.stat().st_mtime_ns == first_mtime
    assert verify_maya_livelink_installation([script_dir])["ok"]
    assert managed_bootstrap_block().strip() in user_setup.read_text(encoding="utf-8")


def test_malformed_managed_block_fails_closed(tmp_path) -> None:
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    user_setup = script_dir / "userSetup.py"
    user_setup.write_text(BLOCK_BEGIN + "\nprint('partial')\n", encoding="utf-8")

    result = install_maya_livelink_plugin([script_dir])

    assert not result["ok"]
    assert result["errors"]
    assert user_setup.read_text(encoding="utf-8").endswith("print('partial')\n")


def test_maya_bridge_constructor_does_not_mutate_installation_by_default(monkeypatch) -> None:
    called = []
    monkeypatch.delenv("TECH_CONNECTOR_AUTO_INSTALL_MAYA_BRIDGE", raising=False)
    monkeypatch.setattr(MayaBridge, "_auto_install_livelink_plugin", lambda self: called.append(True))

    MayaBridge()

    assert called == []


def test_generated_bootstrap_uses_authenticated_json_bridge_module(monkeypatch) -> None:
    maya_module = ModuleType("maya")
    cmds_module = ModuleType("maya.cmds")
    opened = []

    cmds_module.commandPort = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("raw Maya commandPort must not be used")
    )
    cmds_module.evalDeferred = lambda callback: callback()
    cmds_module.pluginInfo = lambda *_args, **_kwargs: True
    cmds_module.loadPlugin = lambda *_args, **_kwargs: None
    cmds_module.warning = lambda _message: None
    maya_module.cmds = cmds_module
    maya_tools_module = ModuleType("maya_tools")
    menu_module = ModuleType("maya_tools.maya_menu")
    menu_module.initialize_command_port = lambda: opened.append(7002) or 7002
    maya_tools_module.maya_menu = menu_module
    monkeypatch.setitem(sys.modules, "maya", maya_module)
    monkeypatch.setitem(sys.modules, "maya.cmds", cmds_module)
    monkeypatch.setitem(sys.modules, "maya_tools", maya_tools_module)
    monkeypatch.setitem(sys.modules, "maya_tools.maya_menu", menu_module)

    namespace = {"__file__": "C:/Maya/2026/scripts/userSetup.py"}
    exec(compile(MAYA_USER_SETUP_CODE, "<test_maya_bootstrap>", "exec"), namespace, namespace)

    assert opened == [7002]
    assert namespace["TECH_CONNECTOR_MAYA_BRIDGE_VERSION"] == "3"
    assert namespace["TECH_CONNECTOR_MAYA_BRIDGE_BOOT_SOURCE"].endswith("userSetup.py")


def test_current_bootstrap_never_opens_a_raw_maya_command_port() -> None:
    assert "cmds.commandPort" not in MAYA_USER_SETUP_CODE
    assert "sourceType=" not in MAYA_USER_SETUP_CODE


def test_install_discovery_ignores_stale_preference_folders(tmp_path) -> None:
    autodesk = tmp_path / "Autodesk"
    maya_root = tmp_path / "maya"
    for version in ("2022", "2023", "2025"):
        (maya_root / version / "scripts").mkdir(parents=True)
    (maya_root / "scripts").mkdir()
    installed = autodesk / "Maya2023" / "bin"
    installed.mkdir(parents=True)
    (installed / "mayapy.exe").touch()
    (autodesk / "Maya2025" / "plug-ins").mkdir(parents=True)

    assert installed_maya_versions(autodesk) == {2023: (autodesk / "Maya2023").resolve()}
    assert find_maya_script_dirs(autodesk_root=autodesk, maya_root=maya_root) == [
        (maya_root / "2023" / "scripts").resolve(),
        (maya_root / "scripts").resolve(),
    ]
