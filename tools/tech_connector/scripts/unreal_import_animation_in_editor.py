"""Import one animation-only FBX in a full Unreal Editor Python session.

Launched by run_unreal_fbx_import_proof.py with -ExecutePythonScript. The
Python commandlet (-run=pythonscript) is not interchangeable on UE 5.7: its
Interchange importer can touch Slate after saving and crash headlessly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    import unreal

    config = json.loads(os.environ["TC_UNREAL_IMPORT_CONFIG_JSON"])
    source = Path(config["animation_fbx"])
    report_path = Path(config["report_json"])
    destination = str(config["destination_path"]).rstrip("/")
    name = str(config["asset_name"])
    skeleton_path = str(config["skeleton_asset_path"])
    if not source.is_file() or source.suffix.lower() != ".fbx":
        raise ValueError(f"Animation FBX is missing or not .fbx: {source}")
    if not destination.startswith("/Game/") or not name or "/" in name:
        raise ValueError("Destination must be under /Game and asset name must be a single segment")
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite proof report: {report_path}")
    asset_path = destination + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise FileExistsError(f"Refusing to overwrite Unreal asset: {asset_path}")
    skeleton = unreal.load_asset(skeleton_path)
    if not isinstance(skeleton, unreal.Skeleton):
        raise TypeError(f"Target asset is not a Skeleton: {skeleton_path}")

    options = unreal.FbxImportUI()
    options.set_editor_property("automated_import_should_detect_type", False)
    options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
    options.set_editor_property("import_as_skeletal", True)
    options.set_editor_property("import_mesh", False)
    options.set_editor_property("import_animations", True)
    options.set_editor_property("skeleton", skeleton)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(source))
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    imported = list(task.get_objects())
    asset = unreal.load_asset(asset_path)
    if not isinstance(asset, unreal.AnimSequence) or not any(
        isinstance(item, unreal.AnimSequence) for item in imported
    ):
        raise RuntimeError(f"FBX did not import as an AnimSequence: {asset_path}")
    assigned = asset.get_editor_property("skeleton")
    if assigned != skeleton:
        raise RuntimeError("Imported AnimSequence is not assigned to the requested Skeleton")
    names = {str(value) for value in unreal.AnimationLibrary.get_animation_track_names(asset)}
    required = set(config.get("required_bones") or ())
    minimum = int(config.get("minimum_track_count", 1))
    frames = int(unreal.AnimationLibrary.get_num_frames(asset))
    minimum_frames = int(config.get("minimum_frame_count", 1))
    if len(names) < minimum or not required.issubset(names) or frames < minimum_frames:
        raise RuntimeError(
            f"Imported animation failed track/frame gate: {len(names)} tracks, {frames} frames, "
            f"missing={sorted(required - names)}"
        )
    proof = {
        "ok": True,
        "unreal_version": unreal.SystemLibrary.get_engine_version(),
        "animation_fbx": str(source),
        "anim_sequence": asset.get_path_name(),
        "skeleton": skeleton.get_path_name(),
        "track_count": len(names),
        "frame_count": frames,
        "play_length_seconds": float(asset.get_play_length()),
        "required_bones_present": sorted(required),
        "imported_object_paths": list(task.get_editor_property("imported_object_paths")),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("TC_UNREAL_IMPORT_PROOF=" + json.dumps(proof))


main()
