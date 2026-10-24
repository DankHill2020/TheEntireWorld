"""Fresh Blender reimport check of a completed three-host bevel action report."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import bpy


def _mesh_polygons(path: Path) -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path))
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one mesh in {path.name}; got {len(meshes)}")
    return len(meshes[0].data.polygons)


def main() -> None:
    proof = Path(os.environ["TC_BEVEL_ACTION_ROOT"]).resolve()
    output = proof / "geometry_reimport.json"
    if output.exists():
        raise FileExistsError(output)
    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    if report.get("schema") != "tech_connector.maya_blender_unreal_bevel_action.v1" or not report.get("passed"):
        raise RuntimeError("Action report did not pass")
    results = report["action_report"]["results"]
    processing = results["stage_03_blender_pipeline_process_meshes_for_transfer"]["raw_result"]["result"]
    if processing.get("bevels") != [{"object": "MayaPromptCube", "width": 0.1, "segments": 3}]:
        raise RuntimeError(f"Bevel receipt did not match the prompt: {processing.get('bevels')}")
    source = proof / "maya_source.fbx"
    edited = proof / "blender_edited.fbx"
    for path in (source, edited):
        expected = report["artifacts"][path.name]["sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"FBX artifact hash changed: {path}")
    plain_polygons = _mesh_polygons(source)
    edited_polygons = _mesh_polygons(edited)
    if edited_polygons <= plain_polygons:
        raise RuntimeError("Bevel geometry did not survive the action-engine FBX export")
    proof_result = {
        "schema": "tech_connector.maya_blender_bevel_action_geometry.v1",
        "source_polygons": plain_polygons,
        "edited_polygons": edited_polygons,
        "bevel_receipt": processing["bevels"],
        "source_sha256": report["artifacts"][source.name]["sha256"],
        "edited_sha256": report["artifacts"][edited.name]["sha256"],
        "blender_version": bpy.app.version_string,
    }
    output.write_text(json.dumps(proof_result, indent=2), encoding="utf-8")
    print(json.dumps(proof_result))


if __name__ == "__main__":
    main()
