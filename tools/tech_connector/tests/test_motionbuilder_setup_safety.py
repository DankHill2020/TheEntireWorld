from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace


def _load_setup(monkeypatch):
    pyfbsdk = ModuleType("pyfbsdk")
    pyfbsdk.FBSystem = lambda: SimpleNamespace(Version=24000)
    monkeypatch.setitem(sys.modules, "pyfbsdk", pyfbsdk)
    path = Path(__file__).resolve().parents[2] / "motionbuilder_tools" / "motionbuilder_setup.py"
    spec = importlib.util.spec_from_file_location("tc_test_motionbuilder_setup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_motionbuilder_setup_import_has_no_install_side_effect(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: calls.append(True))

    module = _load_setup(monkeypatch)

    assert calls == []
    assert module.get_motionbuilder_version_string() == "MotionBuilder 2024"


def test_motionbuilder_setup_skips_dependency_install_when_ready(monkeypatch) -> None:
    module = _load_setup(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "_requests_available", lambda: True)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: calls.append(True))

    result = module.install_current_motionbuilder_tools()

    assert result["status"] == "ready"
    assert result["changed"] is False
    assert calls == []


def test_motionbuilder_dependency_install_is_bounded_and_does_not_upgrade_pip(monkeypatch, tmp_path) -> None:
    module = _load_setup(monkeypatch)
    python = tmp_path / "python.exe"
    python.touch()
    calls = []
    monkeypatch.setattr(module, "_requests_available", lambda: False)
    monkeypatch.setattr(module, "motionbuilder_python_path", lambda: python)

    def run(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)

    result = module.install_current_motionbuilder_tools(timeout_seconds=30)

    assert result["changed"] is True
    assert [call[0][2:] for call in calls] == [
        ["ensurepip", "--upgrade"], ["pip", "install", "requests"],
    ]
    assert all(call[1]["timeout"] == 30.0 for call in calls)
    assert not any("pip" in command and "--upgrade" in command for command, _options in calls)
