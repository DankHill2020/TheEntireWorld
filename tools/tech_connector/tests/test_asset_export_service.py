from __future__ import annotations

import json

import pytest

from tech_connector.game_engine.assets import (
    BUILTIN_ASSET_TYPES, AssetDatabase, AssetExportService,
    TCEditorAPI, conversion_coverage_report, plan_asset_conversion,
)


def test_export_package_is_dependency_closed_and_writes_unreal_adapter(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir(); assets = project / "Assets"; assets.mkdir()
    texture = assets / "T_Character.png"; texture.write_bytes(b"png")
    mesh = assets / "SK_Character.fbx"; mesh.write_bytes(b"fbx")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture_record = database.register_asset(texture, "tc.texture")
    mesh_record = database.register_asset(mesh, "tc.skeletal_mesh", dependencies=[texture_record.asset_id])
    receipt = AssetExportService(project, database).export_assets([mesh_record.asset_id], tmp_path / "Export", target="unreal")

    assert receipt.asset_ids == (texture_record.asset_id, mesh_record.asset_id)
    assert (receipt.destination / "Content" / "Assets" / mesh.name).is_file()
    assert (receipt.destination / "ImportToUnreal.py").is_file()
    manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
    assert manifest["target"] == "unreal" and manifest["dependency_closed"] is True
    assert manifest["assets"][1]["dependencies"] == [texture_record.asset_id]
    assert receipt.ready is True
    assert manifest["schema"] == "tech_connector.export_package.v2"
    assert all(row["conversion"]["mode"] == "direct_import" for row in manifest["assets"])
    unreal_adapter = (receipt.destination / "ImportToUnreal.py").read_text(encoding="utf-8")
    assert "task.filename =" in unreal_adapter
    assert "task.filenames" not in unreal_adapter
    assert receipt.conversion_report_path.is_file()


def test_export_rejects_unknown_target(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir(); source = project / "asset.bin"; source.write_bytes(b"asset")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3"); record = database.register_asset(source, "tc.data")
    try: AssetExportService(project, database).export_assets([record.asset_id], tmp_path / "Export", target="mystery")
    except ValueError as exc: assert "Unsupported export target" in str(exc)
    else: raise AssertionError("unknown targets must fail")


def test_every_registered_asset_type_has_a_conversion_classification_for_every_target() -> None:
    report = conversion_coverage_report()

    assert report["asset_type_count"] == len(BUILTIN_ASSET_TYPES)
    assert report["uncovered"] == []
    assert report["classified"] == len(BUILTIN_ASSET_TYPES) * len(report["targets"])
    for target, counts in report["counts"].items():
        assert counts["total"] == len(BUILTIN_ASSET_TYPES), target
        assert sum(counts[key] for key in ("ready", "bake_required", "adapter_required", "unsupported")) == counts["total"]


def test_native_asset_export_is_truthful_and_ready_only_mode_blocks_it(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir(); assets = project / "Assets"; assets.mkdir()
    material = assets / "Hero.material.tcasset"; material.write_text("{}", encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    record = database.register_asset(material, "tc.material")
    service = AssetExportService(project, database)

    receipt = service.export_assets([record.asset_id], tmp_path / "Export", target="unity")
    manifest = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))
    assert receipt.ready is False
    assert manifest["conversion_ready"] is False
    assert manifest["assets"][0]["conversion"]["mode"] == "bake_required"
    assert (receipt.destination / "ImportToUnity.cs").is_file()

    with pytest.raises(ValueError, match="not conversion-ready"):
        service.export_assets(
            [record.asset_id], tmp_path / "StrictExport", target="unity", require_ready=True,
        )
    assert not (tmp_path / "StrictExport").exists()


def test_direct_conversion_plan_uses_compound_extensions() -> None:
    skin = plan_asset_conversion("tc.skin_binding", "Hero.tcskin.json", "unreal")
    texture = plan_asset_conversion("tc.texture", "Hero_BaseColor.png", "unity")

    assert skin.source_extension == ".tcskin.json"
    assert skin.ready is False
    assert skin.mode in {"bake_required", "native_adapter_required"}
    assert texture.ready is True and texture.mode == "direct_import"


def test_conversion_coverage_and_strict_export_are_exposed_through_python_api(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir()
    api = TCEditorAPI(project)

    coverage = api.asset_conversion_coverage()
    assert coverage["asset_type_count"] == len(BUILTIN_ASSET_TYPES)
    assert coverage["uncovered"] == []
    assert "asset_conversion_coverage" in api.capability_contract()["asset_operations"]
