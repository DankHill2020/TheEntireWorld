"""Isolated Blender 5.x FBX round-trip proof for the prompt-driven bevel edit.

Run with Blender --background --python this_file and TC_BEVEL_PROOF_ROOT set to
an empty disposable directory. No user scene or project is opened.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import bpy


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from blender_tools.io import export_fbx, import_fbx  # noqa: E402
from blender_tools.pipeline_transfer import process_meshes_for_transfer  # noqa: E402


def _generated_export(path: Path, object_names: list[str]) -> None:
    # Load the code generator directly: importing the entire desktop package
    # inside Blender would unnecessarily require Qt/Pillow dependencies.
    source = ROOT / "tech_connector" / "game_engine" / "integration" / "dcc_operation_service.py"
    spec = importlib.util.spec_from_file_location("tc_blender_proof_operations", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Blender operation code generator is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    script = module.blender_operation_code("blender.export_fbx", {
        "output_path": str(path),
        "selection": object_names,
        "settings": {"bake_animation": False},
    })
    exec(script, {"__name__": "__main__"})


def _reimport_polygons(path: Path) -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    receipt = import_fbx(str(path))
    meshes = [bpy.data.objects[name] for name in receipt["meshes"]]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one reimported mesh in {path.name}: {receipt}")
    return len(meshes[0].data.polygons)


def main() -> None:
    destination = Path(os.environ["TC_BEVEL_PROOF_ROOT"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    baseline = destination / "plain_cube.fbx"
    beveled = destination / "beveled_cube.fbx"
    report_path = destination / "blender_bevel_roundtrip.json"
    if any(path.exists() for path in (baseline, beveled, report_path)):
        raise FileExistsError("Refusing to overwrite an existing Blender proof artifact")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    maya_source = os.environ.get("TC_BEVEL_MAYA_SOURCE_FBX")
    if maya_source:
        imported = import_fbx(maya_source)
        if len(imported["meshes"]) != 1:
            raise RuntimeError(f"Expected exactly one Maya source mesh: {imported}")
        target = bpy.data.objects[imported["meshes"][0]]
    else:
        bpy.ops.mesh.primitive_cube_add()
        target = bpy.context.object
        target.name = "PromptCube"
    bpy.ops.mesh.primitive_cube_add(location=(4, 0, 0))
    unrelated = bpy.context.object
    unrelated.name = "UnrelatedCube"
    unrelated.scale = (2, 2, 2)
    target.select_set(True)
    bpy.context.view_layer.objects.active = unrelated
    incoming_selection = sorted(obj.name for obj in bpy.context.selected_objects)
    incoming_active = bpy.context.view_layer.objects.active.name
    target_name = target.name

    export_fbx(str(baseline), object_names=[target.name], bake_animation=False)
    # Export sets its own selection; restore the adversarial two-object
    # selection before exercising the transfer processor.
    unrelated.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = unrelated
    receipt = process_meshes_for_transfer(
        objects=[target.name], clean_names=False, apply_transforms=True,
        bevel_width=0.1, bevel_segments=3,
    )
    after_selection = sorted(obj.name for obj in bpy.context.selected_objects)
    after_active = bpy.context.view_layer.objects.active.name
    if (after_selection != incoming_selection or after_active != incoming_active
            or tuple(unrelated.scale) != (2.0, 2.0, 2.0)
            or len(unrelated.modifiers) != 0
            or receipt["bevels"] != [
                {"object": target_name, "width": 0.1, "segments": 3}
            ]):
        raise RuntimeError("Bevel transfer changed an unrelated object or lost selection")
    _generated_export(beveled, receipt["export_objects"])

    plain_polygons = _reimport_polygons(baseline)
    beveled_polygons = _reimport_polygons(beveled)
    if beveled_polygons <= plain_polygons:
        raise RuntimeError("FBX reimport did not retain the bevel geometry")
    report = {
        "schema": "tech_connector.blender_bevel_roundtrip.v1",
        "blender_version": bpy.app.version_string,
        "selection_isolated": True,
        "incoming_selection": incoming_selection,
        "restored_selection": after_selection,
        "unrelated_scale_preserved": True,
        "bevel_receipt": receipt["bevels"],
        "beveled_exporter": "blender.export_fbx generated operation",
        "maya_source": (
            {"path": str(Path(maya_source).resolve()),
             "sha256": hashlib.sha256(Path(maya_source).read_bytes()).hexdigest()}
            if maya_source else None
        ),
        "plain_polygons": plain_polygons,
        "beveled_polygons": beveled_polygons,
        "artifacts": {
            path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (baseline, beveled)
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
