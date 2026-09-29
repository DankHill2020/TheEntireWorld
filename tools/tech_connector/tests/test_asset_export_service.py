from __future__ import annotations

import json

from tech_connector.game_engine.assets import AssetDatabase, AssetExportService


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


def test_export_rejects_unknown_target(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir(); source = project / "asset.bin"; source.write_bytes(b"asset")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3"); record = database.register_asset(source, "tc.data")
    try: AssetExportService(project, database).export_assets([record.asset_id], tmp_path / "Export", target="mystery")
    except ValueError as exc: assert "Unsupported export target" in str(exc)
    else: raise AssertionError("unknown targets must fail")
