"""Blender-side isolated mesh LOD generator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _triangle_count(mesh) -> int:
    return sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons)


def _mesh_inventory(bpy):
    rows = []
    for obj in sorted((item for item in bpy.context.scene.objects if item.type == "MESH"), key=lambda item: item.name):
        rows.append({
            "name": str(obj.name),
            "vertices": len(obj.data.vertices),
            "triangles": _triangle_count(obj.data),
            "uv_layers": len(obj.data.uv_layers),
            "material_slots": len(obj.material_slots),
            "vertex_groups": len(obj.vertex_groups),
        })
    return rows


def _generate(request_path: str, result_path: str) -> None:
    import bpy

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    source_path = str(Path(request["source_path"]).resolve())
    output_dir = Path(request["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_dir = Path(__file__).resolve().parent
    if str(worker_dir) not in sys.path:
        sys.path.insert(0, str(worker_dir))
    from blender_fbx_extract import _import_source_scene

    levels = []
    for level in request["levels"]:
        name = str(level["name"])
        ratio = float(level["triangle_ratio"])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _import_source_scene(bpy, source_path)
        before = _mesh_inventory(bpy)
        diagnostics = []
        if ratio < 0.999999:
            for obj in [item for item in bpy.context.scene.objects if item.type == "MESH"]:
                if not obj.data.polygons:
                    continue
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                modifier = obj.modifiers.new(name="TechConnector_LOD", type="DECIMATE")
                modifier.decimate_type = "COLLAPSE"
                modifier.ratio = ratio
                modifier.use_collapse_triangulate = True
                try:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                except Exception as exc:
                    diagnostics.append({"object": str(obj.name), "severity": "error", "message": str(exc)})
                    if modifier.name in obj.modifiers:
                        obj.modifiers.remove(modifier)
                finally:
                    obj.select_set(False)
        after = _mesh_inventory(bpy)
        output_path = output_dir / f"{Path(source_path).stem}_{name}.glb"
        bpy.ops.export_scene.gltf(
            filepath=str(output_path),
            export_format="GLB",
            export_apply=True,
            export_animations=bool(request.get("include_animation", False)),
        )
        before_triangles = sum(item["triangles"] for item in before)
        after_triangles = sum(item["triangles"] for item in after)
        levels.append({
            "name": name,
            "triangle_ratio": ratio,
            "output_path": str(output_path),
            "source_triangles": before_triangles,
            "output_triangles": after_triangles,
            "achieved_ratio": (after_triangles / before_triangles) if before_triangles else 0.0,
            "objects_before": before,
            "objects_after": after,
            "diagnostics": diagnostics,
            "output_bytes": output_path.stat().st_size,
        })
    result = {
        "schema": "tech_connector.mesh_lod_result.v1",
        "source_path": source_path,
        "backend": "blender_decimate_glb",
        "blender_version": list(bpy.app.version),
        "levels": levels,
    }
    Path(result_path).write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    _generate(args.request, args.result)


if __name__ == "__main__":
    main()
