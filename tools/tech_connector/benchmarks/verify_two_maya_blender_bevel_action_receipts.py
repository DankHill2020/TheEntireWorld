"""Cross-check one prompt's two independent Maya→Blender→Unreal receipt chains."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _stage(results: dict, number: int, operation: str) -> dict:
    key = f"stage_{number:02d}_{operation}"
    row = results[key]
    if row.get("status") != "succeeded":
        raise RuntimeError(f"Stage did not succeed: {key}")
    return row["raw_result"]["result"]


def main() -> None:
    proof = Path(os.environ["TC_BEVEL_ACTION_ROOT"]).resolve()
    output = proof / "receipt_chain.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    geometry = json.loads((proof / "geometry_reimport.json").read_text(encoding="utf-8"))
    unreal = json.loads((proof / "unreal_reopen_clean.json").read_text(encoding="utf-8"))
    if report.get("status_counts") != {"completed": 12} or not report.get("passed"):
        raise RuntimeError("Twelve-stage action did not complete")
    if len(geometry.get("lanes", [])) != 2 or len(unreal.get("assets", [])) != 2:
        raise RuntimeError("Independent geometry or Unreal readback is incomplete")
    results = report["action_report"]["results"]
    lanes = []
    for index, name in enumerate(("Crate_A", "Barrel_B")):
        offset = index * 6
        maya = _stage(results, 1 + offset, "maya_animation_export")
        imported = _stage(results, 2 + offset, "blender_io_import_fbx")
        processed = _stage(results, 3 + offset, "blender_pipeline_process_meshes_for_transfer")
        exported = _stage(results, 4 + offset, "blender_blender_export_fbx")
        unreal_import = _stage(results, 5 + offset, "unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified")
        readback = _stage(results, 6 + offset, "unreal_unreal_tools_asset_transfer_adapter_registry_readback")
        geom = geometry["lanes"][index]
        asset = unreal["assets"][index]
        source = proof / f"{name}_maya.fbx"
        edited = proof / f"{name}_blender.fbx"
        for path in (source, edited):
            expected = report["artifacts"][path.name]["sha256"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Changed FBX artifact: {path}")
        expected_asset = f"/Game/TCProbe/TwoBeveledPropsActionV1/{name}_blender.{name}_blender"
        if not (
            maya["nodes"] == [f"|{name}"]
            and maya["fbx_path"] == str(source)
            and imported["filepath"] == maya["fbx_path"]
            and imported["objects"] == [name]
            and processed["export_objects"] == [name]
            and processed["bevels"] == [{"object": name, "width": 0.1, "segments": 3}]
            and exported["selected"] == [name]
            and exported["settings"]["use_mesh_modifiers"] is True
            and exported["fbx_path"] == str(edited)
            and unreal_import["source_file"] == exported["fbx_path"]
            and unreal_import["asset_path"] == expected_asset
            and readback["assets"] == [expected_asset]
            and geom["name"] == name
            and geom["edited_polygons"] > geom["source_polygons"]
            and geom["source_sha256"] == report["artifacts"][source.name]["sha256"]
            and geom["edited_sha256"] == report["artifacts"][edited.name]["sha256"]
            and asset["name"] == name
            and asset["asset_path"] == expected_asset
            and asset["asset_class"] == "StaticMesh"
            and asset["source_sha256"] == report["artifacts"][edited.name]["sha256"]
        ):
            raise RuntimeError(f"Receipt chain mismatch for {name}")
        lanes.append({"name": name, "source_polygons": geom["source_polygons"],
                      "edited_polygons": geom["edited_polygons"], "asset_path": expected_asset})
    if (len({row["asset_path"] for row in lanes}) != 2
            or not unreal["registry_readback"]["ok"]
            or set(unreal["registry_readback"]["assets"]) != {row["asset_path"] for row in lanes}):
        raise RuntimeError("Fresh Unreal readback did not preserve both distinct assets")
    payload = {"schema": "tech_connector.two_maya_blender_bevel_action_receipt_chain.v1",
               "passed": True, "stages_completed": 12, "lanes": lanes}
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
