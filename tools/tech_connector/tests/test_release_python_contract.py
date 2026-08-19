import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tech_connector.packaging.stage_package import copy_tree_entry, matches_any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_reasoning_runtime_includes_current_application_packages() -> None:
    manifest = json.loads(
        (PACKAGE_ROOT / "packaging" / "package_tiers.json").read_text(encoding="utf-8")
    )
    includes = manifest["tiers"]["reasoning-runtime"]["include"]
    assert "tech_connector/game_engine" in includes
    assert "tech_connector/installers" in includes
    assert "tech_connector/project_analysis" in includes


def test_windows_release_requires_current_python_and_bundles_native_runtime() -> None:
    script = (
        PACKAGE_ROOT / "packaging" / "windows" / "build_windows_package.ps1"
    ).read_text(encoding="utf-8-sig")
    assert '[string]$Python = "auto"' in script
    assert "Resolve-ReleasePython $Python" in script
    assert "Assert-ReleasePython $pythonInfo" in script
    assert "Build-NativeGraphRuntime" in script
    assert '"--add-binary", "$nativeGraphDll;tech_connector\\game_engine\\native\\bin"' in script


def test_release_dependency_floors_support_python_314() -> None:
    build = (PACKAGE_ROOT / "packaging" / "requirements-build.txt").read_text(encoding="utf-8")
    runtime = (PACKAGE_ROOT / "packaging" / "requirements-runtime.txt").read_text(encoding="utf-8")
    assert "pyinstaller>=6.21,<7" in build.lower()
    assert "PySide6>=6.10.1,<6.12" in runtime


def test_release_tiers_exclude_generated_runtime_state() -> None:
    manifest = json.loads(
        (PACKAGE_ROOT / "packaging" / "package_tiers.json").read_text(encoding="utf-8")
    )
    generated_paths = (
        "tech_connector/.ai_studio/unreal_request_log.jsonl",
        "plugins/AIStudioBridge/.build/output/HostProject/Intermediate/plugin.obj",
        "tech_connector/game_engine/native/.tech_connector/build.ninja",
        "tech_connector/knowledge/index/legacy/knowledge_index.sqlite",
        "tech_connector/project_analysis/project_analysis.db",
        "tech_connector/project_analysis/project_analysis.db-wal",
        "tech_connector/services/__pycache__/service.cpython-314.pyc",
    )
    for tier in manifest["tiers"].values():
        excludes = tier["exclude"]
        assert all(matches_any(path, excludes) for path in generated_paths)


def test_staging_skips_generated_state_but_keeps_source() -> None:
    excludes = [
        "**/.ai_studio",
        "**/.tech_connector",
        "**/*.pyc",
        "tech_connector/project_analysis/*.db",
    ]
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "source"
        output = Path(temp_dir) / "output"
        source = root / "tech_connector"
        (source / ".ai_studio").mkdir(parents=True)
        (source / "game_engine" / "native" / ".tech_connector").mkdir(parents=True)
        (source / "project_analysis").mkdir(parents=True)
        (source / "services" / "__pycache__").mkdir(parents=True)
        (source / "services" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
        (source / ".ai_studio" / "request.log").write_text("generated", encoding="utf-8")
        (source / "game_engine" / "native" / ".tech_connector" / "build.ninja").write_text(
            "generated", encoding="utf-8"
        )
        (source / "project_analysis" / "project_analysis.db").write_bytes(b"generated")
        (source / "services" / "__pycache__" / "runtime.pyc").write_bytes(b"generated")

        copy_tree_entry(root, "tech_connector", output, excludes)

        assert (output / "tech_connector" / "services" / "runtime.py").is_file()
        assert not (output / "tech_connector" / ".ai_studio").exists()
        assert not (
            output / "tech_connector" / "game_engine" / "native" / ".tech_connector"
        ).exists()
        assert not (
            output / "tech_connector" / "project_analysis" / "project_analysis.db"
        ).exists()
        assert not (output / "tech_connector" / "services" / "__pycache__").exists()
