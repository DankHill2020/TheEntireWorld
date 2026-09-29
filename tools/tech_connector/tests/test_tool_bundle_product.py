from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tech_connector.licensing.products import (
    CORE_PRODUCT_ID,
    OFFICIAL_TOOLS_PRODUCT_ID,
    evaluate_product_access,
)
from tech_connector.services.tool_bundle_service import (
    authorized_tool_roots,
    connector_version_is_compatible,
    compose_project_roots_with_bundles,
    configured_bundle_roots,
    discover_tool_bundles,
    evaluate_tool_bundles,
    load_tool_bundle,
)


def _write_bundle(root: Path, *, tool_roots=("maya_tools", "unreal_tools")) -> Path:
    root.mkdir(parents=True)
    for relative in tool_roots:
        (root / relative).mkdir(parents=True)
    (root / "official_tools_bundle.json").write_text(
        json.dumps(
            {
                "schema": "tech_connector.tool_bundle.v1",
                "package_id": "the_entire_world.official_tools",
                "display_name": "Official Tools",
                "version": "6.7",
                "compatible_connector_versions": ">=6.7,<7.0",
                "required_capability": "official_tools_bundle",
                "tool_roots": list(tool_roots),
            }
        ),
        encoding="utf-8",
    )
    return root


def test_separate_bundle_is_discovered_through_existing_extra_dirs(tmp_path) -> None:
    bundle_root = _write_bundle(tmp_path / "OfficialTools")
    ordinary_project = tmp_path / "CustomerProject"
    ordinary_project.mkdir()
    settings = {"extra_dirs": [str(ordinary_project), str(bundle_root)]}

    assert configured_bundle_roots(settings) == (bundle_root.resolve(),)
    bundles = discover_tool_bundles(settings)
    assert len(bundles) == 1
    assert bundles[0].package_id == "the_entire_world.official_tools"
    assert bundles[0].tool_roots == (
        (bundle_root / "maya_tools").resolve(),
        (bundle_root / "unreal_tools").resolve(),
    )


def test_official_bundle_requires_one_signed_bundle_capability(tmp_path) -> None:
    bundle_root = _write_bundle(tmp_path / "OfficialTools")
    settings = {"tool_bundle_dirs": [str(bundle_root)]}

    denied = evaluate_tool_bundles(settings, SimpleNamespace(capabilities=()))[0]
    assert not denied.decision.allowed
    assert denied.decision.code == "product_capability_missing"
    assert authorized_tool_roots(settings, SimpleNamespace(capabilities=())) == ()

    claims = SimpleNamespace(capabilities=(OFFICIAL_TOOLS_PRODUCT_ID,))
    allowed = evaluate_tool_bundles(settings, claims)[0]
    assert allowed.decision.allowed
    assert authorized_tool_roots(settings, claims) == allowed.bundle.tool_roots


def test_bundle_filter_preserves_user_roots_and_adds_only_authorized_tools(tmp_path) -> None:
    bundle_root = _write_bundle(tmp_path / "OfficialTools")
    customer_root = tmp_path / "CustomerTools"
    customer_root.mkdir()
    settings = {
        "extra_dirs": [str(customer_root), str(bundle_root)],
        "tool_bundle_dirs": [str(bundle_root)],
    }
    base = [str(customer_root), str(bundle_root)]

    denied = compose_project_roots_with_bundles(
        settings,
        base,
        SimpleNamespace(capabilities=()),
    )
    assert denied == (str(customer_root.resolve()),)

    allowed = compose_project_roots_with_bundles(
        settings,
        base,
        SimpleNamespace(capabilities=(OFFICIAL_TOOLS_PRODUCT_ID,)),
    )
    assert allowed == (
        str(customer_root.resolve()),
        str((bundle_root / "maya_tools").resolve()),
        str((bundle_root / "unreal_tools").resolve()),
    )


def test_core_and_tools_are_separate_product_decisions() -> None:
    claims = SimpleNamespace(capabilities=())
    assert evaluate_product_access(claims, CORE_PRODUCT_ID).allowed
    assert not evaluate_product_access(claims, OFFICIAL_TOOLS_PRODUCT_ID).allowed


def test_bundle_connector_version_range_is_enforced(tmp_path) -> None:
    bundle_root = _write_bundle(tmp_path / "OfficialTools")
    settings = {"tool_bundle_dirs": [str(bundle_root)]}
    claims = SimpleNamespace(capabilities=(OFFICIAL_TOOLS_PRODUCT_ID,))

    assert connector_version_is_compatible("v6.7", ">=6.7,<7.0")
    assert connector_version_is_compatible("6.9.2", ">=6.7,<7.0")
    assert not connector_version_is_compatible("7.0", ">=6.7,<7.0")
    denied = evaluate_tool_bundles(settings, claims, "7.0")[0]
    assert not denied.decision.allowed
    assert denied.decision.code == "bundle_version_incompatible"


def test_bundle_manifest_rejects_directory_escape(tmp_path) -> None:
    root = tmp_path / "OfficialTools"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    (root / "official_tools_bundle.json").write_text(
        json.dumps(
            {
                "schema": "tech_connector.tool_bundle.v1",
                "package_id": "the_entire_world.official_tools",
                "display_name": "Official Tools",
                "version": "6.7",
                "compatible_connector_versions": ">=6.7,<7.0",
                "required_capability": "official_tools_bundle",
                "tool_roots": ["../outside"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe relative"):
        load_tool_bundle(root)
