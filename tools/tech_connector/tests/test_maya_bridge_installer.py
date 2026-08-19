import base64
from pathlib import Path
import sys
from types import ModuleType

from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.maya.maya_livelink_plugin import (
    BLOCK_BEGIN,
    BLOCK_END,
    LEGACY_MAYA_USER_SETUP_CODE,
    MAYA_USER_SETUP_CODE,
    install_maya_livelink_plugin,
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
    assert "def maya_execute_and_capture" in rendered
    assert render_user_setup(rendered) == rendered


def test_legacy_bootstrap_is_migrated_without_duplication() -> None:
    rendered = render_user_setup(LEGACY_MAYA_USER_SETUP_CODE)

    assert "Tech Connector Maya Live Link Startup Script" not in rendered
    assert rendered.count(BLOCK_BEGIN) == 1
    assert "TECH_CONNECTOR_MAYA_BRIDGE_VERSION = \"2\"" in rendered
    assert "MAYA_COMMAND_PORT_SCAN_COUNT" in rendered


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


def test_generated_bootstrap_falls_back_to_free_port_and_installs_capture(monkeypatch) -> None:
    maya_module = ModuleType("maya")
    cmds_module = ModuleType("maya.cmds")
    opened = []

    def command_port(name=None, q=False, **_kwargs):
        if q:
            return name in opened
        if name == ":7001":
            raise RuntimeError("address already in use")
        opened.append(name)
        return name

    cmds_module.commandPort = command_port
    cmds_module.evalDeferred = lambda callback: callback()
    cmds_module.pluginInfo = lambda *_args, **_kwargs: True
    cmds_module.loadPlugin = lambda *_args, **_kwargs: None
    cmds_module.warning = lambda _message: None
    maya_module.cmds = cmds_module
    monkeypatch.setitem(sys.modules, "maya", maya_module)
    monkeypatch.setitem(sys.modules, "maya.cmds", cmds_module)

    namespace = {"__file__": "C:/Maya/2026/scripts/userSetup.py"}
    exec(compile(MAYA_USER_SETUP_CODE, "<test_maya_bootstrap>", "exec"), namespace, namespace)
    payload = base64.b64encode(b"print('capture-ok')").decode("ascii")

    assert opened == [":7002"]
    assert namespace["TECH_CONNECTOR_MAYA_BRIDGE_VERSION"] == "2"
    assert namespace["TECH_CONNECTOR_MAYA_BRIDGE_BOOT_SOURCE"].endswith("userSetup.py")
    assert namespace["maya_execute_and_capture"](payload).strip() == "capture-ok"
