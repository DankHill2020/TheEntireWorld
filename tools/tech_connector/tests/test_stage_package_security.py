"""Release staging security-boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.packaging.stage_package import stage_package, validate_staged_package


def _valid_package(root: Path) -> Path:
    package = root / "package"
    required = (
        "README.md",
        "LICENSE",
        "tech_connector/LICENSE.md",
        "tech_connector/PRIVACY.md",
        "tech_connector/README.md",
        "tech_connector/CONTRIBUTING.md",
        "tech_connector/packaging/requirements-runtime.txt",
    )
    for relative in required:
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("release fixture\n", encoding="utf-8")
    return package


def test_staging_scanner_does_not_flag_its_own_source(tmp_path: Path) -> None:
    package = _valid_package(tmp_path)
    destination = package / "tech_connector/packaging/stage_package.py"
    destination.write_text(
        Path(__file__).parents[1].joinpath("packaging/stage_package.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    validate_staged_package(package)


def test_staging_scanner_rejects_private_key_material(tmp_path: Path) -> None:
    package = _valid_package(tmp_path)
    key_path = package / "unexpected.pem"
    key_path.write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="private key"):
        validate_staged_package(package)


@pytest.mark.parametrize(
    "relative",
    ("maya_tools/Utilities/dag.py~", "blender_tools/blender_port.txt"),
)
def test_staging_scanner_rejects_generated_or_runtime_state(
    tmp_path: Path,
    relative: str,
) -> None:
    package = _valid_package(tmp_path)
    artifact = package / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("local state\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="runtime-state"):
        validate_staged_package(package)


def test_official_tools_stage_has_repository_surface_without_local_state(
    tmp_path: Path,
) -> None:
    package = stage_package("official-tools", tmp_path)

    assert (package / "README.md").is_file()
    assert (package / "LICENSE").is_file()
    assert not any(path.name.endswith("~") for path in package.rglob("*"))
    assert not any(path.name.casefold().endswith("_port.txt") for path in package.rglob("*"))
