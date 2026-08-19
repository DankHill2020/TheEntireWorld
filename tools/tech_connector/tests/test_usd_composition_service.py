from __future__ import annotations

from pathlib import Path
import threading

import pytest

from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    load_federated_scene,
    save_federated_scene,
)
from tech_connector.game_engine.scene.usd_composition_service import (
    UsdComposition,
    UsdLayerSpec,
    UsdPayloadRule,
    UsdPropertyOverride,
    UsdVariantSelection,
    attach_usd_composition,
    compose_usd_stage,
    usd_composition_capabilities,
    usd_composition_from_document,
)


def _write_usd_layers(directory: Path) -> tuple[Path, Path]:
    base = directory / "base.usda"
    overlay = directory / "overlay.usda"
    base.write_text(
        '''#usda 1.0
def Xform "World" {
    def Xform "Asset" (
        variants = { string look = "red" }
        prepend variantSets = "look"
    ) {
        float userProperties:weight = 1
        variantSet "look" = {
            "red" {
                color3f userProperties:displayColor = (1, 0, 0)
            }
            "blue" {
                color3f userProperties:displayColor = (0, 0, 1)
            }
        }
    }
}
''',
        encoding="utf-8",
    )
    overlay.write_text(
        '''#usda 1.0
over "World" {
    over "Asset" {
        float userProperties:weight = 2
    }
}
''',
        encoding="utf-8",
    )
    return base, overlay


def test_contract_rejects_missing_layers_and_invalid_prim_paths(tmp_path: Path) -> None:
    composition = UsdComposition(
        [UsdLayerSpec(str(tmp_path / "missing.usda"))],
        variants=[UsdVariantSelection("relative/path", "look", "blue")],
    )

    errors = composition.validate()

    assert any("missing" in error for error in errors)
    assert any("invalid absolute prim path" in error for error in errors)


def test_pre_canceled_composition_never_launches_backend(tmp_path: Path) -> None:
    base, _overlay = _write_usd_layers(tmp_path)
    canceled = threading.Event()
    canceled.set()

    with pytest.raises(RuntimeError, match="canceled"):
        compose_usd_stage(
            UsdComposition([UsdLayerSpec(str(base))]),
            tmp_path / "result.usda",
            cancel_event=canceled,
        )


def test_tcscene_round_trips_usd_composition_and_source_fingerprints(tmp_path: Path) -> None:
    base, overlay = _write_usd_layers(tmp_path)
    composition = UsdComposition([
        UsdLayerSpec(str(overlay), role="shot_override"),
        UsdLayerSpec(str(base), role="asset"),
    ], variants=[UsdVariantSelection("/World/Asset", "look", "blue")])
    document = FederatedSceneDocument(name="USD Shot")
    attach_usd_composition(document, composition)
    path = save_federated_scene(tmp_path / "shot.tcscene", document)

    restored, _blobs = load_federated_scene(path)
    restored_composition = usd_composition_from_document(restored)

    assert restored_composition is not None
    assert [item.role for item in restored_composition.layers] == ["shot_override", "asset"]
    assert restored_composition.variants[0].selection == "blue"
    assert all(item.fingerprint.get("exists") for item in restored_composition.layers)
    assert not any(item["changed"] for item in restored_composition.source_changes())
    overlay.write_text(overlay.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert restored_composition.source_changes()[0]["changed"] is True


def test_live_openusd_backend_composes_layers_variants_and_overrides(tmp_path: Path) -> None:
    capabilities = usd_composition_capabilities()
    if not capabilities["available"]:
        pytest.skip("No isolated OpenUSD backend is installed.")
    base, overlay = _write_usd_layers(tmp_path)
    composition = UsdComposition(
        [
            UsdLayerSpec(str(overlay), role="shot_override"),
            UsdLayerSpec(str(base), role="asset"),
        ],
        variants=[UsdVariantSelection("/World/Asset", "look", "blue")],
        payload_rules=[UsdPayloadRule("/World/Asset", loaded=True)],
        overrides=[UsdPropertyOverride(
            "/World/Asset", "userProperties:weight", 3.5, value_type="float"
        )],
    )
    output = tmp_path / "composed.usda"

    result = compose_usd_stage(composition, output, timeout=60.0)

    assert result.prim_count == 2
    assert result.manifest["usd_version"][:2] == [0, 25]
    asset = next(item for item in result.manifest["prims"] if item["path"] == "/World/Asset")
    assert asset["variants"]["look"]["selection"] == "blue"
    text = output.read_text(encoding="utf-8")
    assert "userProperties:weight = 3.5" in text
    assert 'string look = "blue"' in text


def test_live_backend_rejects_a_malformed_source_layer(tmp_path: Path) -> None:
    capabilities = usd_composition_capabilities()
    if not capabilities["available"]:
        pytest.skip("No isolated OpenUSD backend is installed.")
    malformed = tmp_path / "broken.usda"
    malformed.write_text('#usda 1.0\ndef Xform "Broken" { float value = 2 }\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid OpenUSD source layer"):
        compose_usd_stage(
            UsdComposition([UsdLayerSpec(str(malformed))]),
            tmp_path / "should_not_exist.usda",
            timeout=60.0,
        )
