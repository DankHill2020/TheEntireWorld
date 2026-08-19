from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.game_engine.integration.adaptive_scene_command_service import (
    SceneCommandTarget,
    resolve_adaptive_scene_command,
)
from tech_connector.game_engine.scene.usd_composition_command_service import (
    apply_usd_composition_command,
)
from tech_connector.game_engine.scene.usd_composition_service import (
    UsdComposition,
    UsdCompositionResult,
    UsdLayerSpec,
)


def _layer(tmp_path: Path) -> Path:
    path = tmp_path / "asset.usda"
    path.write_text('#usda 1.0\ndef Xform "Asset" {}\n', encoding="utf-8")
    return path


def test_usd_commands_are_scene_wide_even_for_a_maya_selection(tmp_path: Path) -> None:
    source = _layer(tmp_path)
    route = resolve_adaptive_scene_command(
        "scene.compose_usd",
        SceneCommandTarget(provider="maya:7001", native_id="|Hero|Body"),
        {"layers": [str(source)]},
    ).to_dict()

    assert route["host"] == "tech_connector"
    assert route["execution_mode"] == "tc_openusd_composition"
    assert route["required_payload"]["layers"] == [str(source)]


def test_compose_command_builds_contract_and_default_output(tmp_path: Path) -> None:
    source = _layer(tmp_path)

    outcome = apply_usd_composition_command("scene.compose_usd", {
        "layers": [str(source)],
        "variants": [{"prim_path": "/Asset", "variant_set": "look", "selection": "blue"}],
        "flatten": True,
    })

    assert outcome.requires_compose is True
    assert outcome.composition.layers[0].role == "strongest_override"
    assert outcome.composition.variants[0].selection == "blue"
    assert outcome.composition.flatten is True
    assert outcome.output_path == str(tmp_path / "asset_composed.usda")


def test_edit_commands_copy_composition_replace_opinions_and_reuse_output(tmp_path: Path) -> None:
    source = _layer(tmp_path)
    original = UsdComposition([UsdLayerSpec(str(source))])
    previous = UsdCompositionResult(str(tmp_path / "shot.usdc"), {"prim_count": 3})

    variant = apply_usd_composition_command(
        "scene.set_usd_variant",
        {"prim_path": "/Asset", "variant_set": "look", "selection": "red"},
        composition=original,
        result=previous,
    )
    replaced = apply_usd_composition_command(
        "scene.set_usd_variant",
        {"prim_path": "/Asset", "variant_set": "look", "selection": "blue"},
        composition=variant.composition,
        result=previous,
    )
    payload = apply_usd_composition_command(
        "scene.set_usd_payload",
        {"prim_path": "/Asset", "loaded": False},
        composition=replaced.composition,
        result=previous,
    )
    override = apply_usd_composition_command(
        "scene.set_usd_override",
        {"prim_path": "/Asset", "property_name": "visibility", "value": "invisible", "value_type": "token"},
        composition=payload.composition,
        result=previous,
    )

    assert original.variants == []
    assert [(item.variant_set, item.selection) for item in override.composition.variants] == [("look", "blue")]
    assert override.composition.payload_rules[0].loaded is False
    assert override.composition.overrides[0].value_type == "token"
    assert override.output_path == previous.output_path

    removed = apply_usd_composition_command(
        "scene.set_usd_override",
        {"prim_path": "/Asset", "property_name": "visibility", "action": "remove"},
        composition=override.composition,
        result=previous,
    )
    assert removed.composition.overrides == []


def test_inspect_reports_source_changes_without_requesting_recompose(tmp_path: Path) -> None:
    source = _layer(tmp_path)
    composition = UsdComposition([UsdLayerSpec(str(source))])
    source.write_text(source.read_text(encoding="utf-8") + "# edit\n", encoding="utf-8")

    outcome = apply_usd_composition_command(
        "scene.inspect_usd_composition",
        composition=composition,
        result=UsdCompositionResult(str(tmp_path / "result.usda"), {"prim_count": 1}),
    )

    assert outcome.requires_compose is False
    assert outcome.response["changed_source_count"] == 1
    assert outcome.response["manifest"]["prim_count"] == 1


def test_edit_commands_require_an_attached_composition() -> None:
    with pytest.raises(ValueError, match="No OpenUSD composition"):
        apply_usd_composition_command(
            "scene.set_usd_payload",
            {"prim_path": "/Asset", "loaded": False},
        )
