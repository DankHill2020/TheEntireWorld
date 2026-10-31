"""Independently reimport both FBX lanes from a completed 12-stage action."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import bpy


def _polygons(path: Path) -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path))
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one mesh in {path.name}; found {len(meshes)}")
    return len(meshes[0].data.polygons)


def main() -> None:
    proof = Path(os.environ["TC_BEVEL_ACTION_ROOT"]).resolve()
    output = proof / "geometry_reimport.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.two_maya_blender_unreal_bevel_action.v1" or not report.get("passed"):
        raise RuntimeError("Two-lane action report did not pass")
    results = report["action_report"]["results"]
    lanes = []
    for name, stage in (("Crate_A", 3), ("Barrel_B", 9)):
        process = results[f"stage_{stage:02d}_blender_pipeline_process_meshes_for_transfer"]["raw_result"]["result"]
        expected_bevel = [{"object": name, "width": 0.1, "segments": 3}]
        if process.get("bevels") != expected_bevel or process.get("export_objects") != [name]:
            raise RuntimeError(f"Wrong bevel/export scope for {name}: {process}")
        files = [proof / f"{name}_maya.fbx", proof / f"{name}_blender.fbx"]
        for path in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != report["artifacts"][path.name]["sha256"]:
                raise RuntimeError(f"FBX hash changed: {path}")
        source_polygons, edited_polygons = map(_polygons, files)
        if edited_polygons <= source_polygons:
            raise RuntimeError(f"Bevel geometry missing in exported {name}")
        lanes.append({"name": name, "source_polygons": source_polygons, "edited_polygons": edited_polygons,
                      "bevel_receipt": expected_bevel,
                      "source_sha256": report["artifacts"][files[0].name]["sha256"],
                      "edited_sha256": report["artifacts"][files[1].name]["sha256"]})
    result = {"schema": "tech_connector.two_maya_blender_bevel_action_geometry.v1",
              "lanes": lanes, "blender_version": bpy.app.version_string}
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
