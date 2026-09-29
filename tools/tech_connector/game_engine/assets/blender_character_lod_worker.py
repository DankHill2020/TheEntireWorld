"""Isolated Blender worker for static and skinned Mesh LOD generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _triangles(mesh): return sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons)


def _meshes(bpy):
    return [{"name": obj.name, "vertices": len(obj.data.vertices), "triangles": _triangles(obj.data),
             "uv_layers": len(obj.data.uv_layers), "material_slots": len(obj.material_slots),
             "vertex_groups": len(obj.vertex_groups), "weighted_vertices": sum(1 for vertex in obj.data.vertices if vertex.groups),
             "max_influences": max((len(vertex.groups) for vertex in obj.data.vertices), default=0),
             "armature_modifiers": sum(1 for modifier in obj.modifiers if modifier.type == "ARMATURE"),
             "shape_keys": max(0, len(obj.data.shape_keys.key_blocks) - 1) if obj.data.shape_keys else 0}
            for obj in sorted((item for item in bpy.context.scene.objects if item.type == "MESH"), key=lambda item: item.name)]


def _armatures(bpy):
    return [{"name": obj.name, "bones": [bone.name for bone in obj.data.bones]}
            for obj in sorted((item for item in bpy.context.scene.objects if item.type == "ARMATURE"), key=lambda item: item.name)]


def _errors(before, after, preserve_skinning):
    result = []; after_by_name = {item["name"]: item for item in after}
    for source in before:
        target = after_by_name.get(source["name"])
        if target is None: result.append({"severity": "error", "object": source["name"], "message": "Mesh object was removed."}); continue
        for key, label in (("uv_layers", "UV layers"), ("material_slots", "material slots")):
            if source[key] != target[key]: result.append({"severity": "error", "object": source["name"], "message": f"{label} changed."})
        if preserve_skinning and source["armature_modifiers"] and (not target["armature_modifiers"] or not target["vertex_groups"] or not target["weighted_vertices"]):
            result.append({"severity": "error", "object": source["name"], "message": "Skinned LOD lost its armature binding or weights."})
    return result


def generate(request_path, result_path):
    import bpy
    request = json.loads(Path(request_path).read_text(encoding="utf-8")); source = str(Path(request["source_path"]).resolve())
    output = Path(request["output_dir"]).resolve(); output.mkdir(parents=True, exist_ok=True)
    integration = Path(__file__).resolve().parents[1] / "integration"
    if str(integration) not in sys.path: sys.path.insert(0, str(integration))
    from blender_fbx_extract import _import_source_scene
    levels = []
    for specification in request["levels"]:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        custom = str(specification.get("source_path") or ""); level_source = str(Path(custom).resolve()) if custom else source
        _import_source_scene(bpy, level_source); before = _meshes(bpy); armatures_before = _armatures(bpy); diagnostics = []
        ratio = float(specification["triangle_ratio"])
        if not custom and ratio < 0.999999:
            for obj in [item for item in bpy.context.scene.objects if item.type == "MESH" and item.data.polygons]:
                if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1:
                    diagnostics.append({"severity": "error", "object": obj.name,
                                        "message": "Generated reduction cannot safely remap shape keys yet; provide a custom LOD for this level."})
                    continue
                bpy.ops.object.select_all(action="DESELECT")
                bpy.context.view_layer.objects.active = obj; obj.select_set(True)
                modifier = obj.modifiers.new(name="TC_CharacterLOD", type="DECIMATE"); modifier.decimate_type = "COLLAPSE"
                modifier.ratio = ratio; modifier.use_collapse_triangulate = True
                # Evaluate reduction on the rest mesh before the Armature modifier;
                # otherwise applying Decimate can bake a posed deformation.
                obj.modifiers.move(obj.modifiers.find(modifier.name), 0)
                try: bpy.ops.object.modifier_apply(modifier=modifier.name)
                except Exception as exc: diagnostics.append({"severity": "error", "object": obj.name, "message": str(exc)})
                finally: obj.select_set(False)
        after = _meshes(bpy); armatures_after = _armatures(bpy)
        diagnostics.extend(_errors(before, after, bool(request.get("preserve_skinning", True))))
        if request.get("preserve_skinning", True) and armatures_before != armatures_after:
            diagnostics.append({"severity": "error", "object": "Skeleton", "message": "Armature hierarchy changed."})
        path = output / f"{Path(source).stem}_{specification['name']}.glb"
        skinned = any(item["armature_modifiers"] for item in after)
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_apply=not skinned,
                                  export_animations=bool(request.get("include_animation", False)))
        source_triangles = sum(item["triangles"] for item in before); result_triangles = sum(item["triangles"] for item in after)
        levels.append({"name": specification["name"], "source_kind": "custom" if custom else "generated", "output_path": str(path),
                       "triangle_ratio": ratio, "source_triangles": source_triangles, "output_triangles": result_triangles,
                       "achieved_ratio": result_triangles / source_triangles if source_triangles else 0.0,
                       "objects_before": before, "objects_after": after, "armatures": armatures_after, "diagnostics": diagnostics,
                       "succeeded": not any(item["severity"] == "error" for item in diagnostics),
                       "skinning_preserved": not any(item["severity"] == "error" for item in diagnostics), "output_bytes": path.stat().st_size})
    reference = levels[0]["armatures"] if levels else []
    for level in levels[1:]:
        if level["armatures"] != reference:
            level["diagnostics"].append({"severity": "error", "object": "Skeleton", "message": "LOD skeleton differs from LOD0."})
            level["skinning_preserved"] = False
    result = {"schema": "tech_connector.character_mesh_lod_result.v1", "backend": "blender_character_decimate_glb",
              "source_path": source, "blender_version": list(bpy.app.version), "levels": levels,
              "skinned_meshes": any(item["armature_modifiers"] for item in levels[0]["objects_before"]) if levels else False,
              "skinning_preserved": all(level["skinning_preserved"] for level in levels),
              "succeeded": all(level["succeeded"] for level in levels)}
    Path(result_path).write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--request", required=True); parser.add_argument("--result", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None); generate(args.request, args.result)
