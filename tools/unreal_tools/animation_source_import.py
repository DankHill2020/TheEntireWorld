"""Import external FBX animation sources without assuming a project Skeleton."""

from __future__ import annotations

import os


def _asset_path(value: str) -> str:
    return str(value or "").split(".")[0]


def import_animation_source(
    source_path: str,
    destination_path: str,
    destination_name: str,
    replace_existing: bool = False,
    save: bool = True,
) -> dict:
    """Import an FBX's own mesh, Skeleton, and animations for editor retargeting.

    A motion-only FBX may create a Skeleton/AnimSequence but no SkeletalMesh. The
    report keeps that distinction explicit because IK Retargeter baking needs a
    source SkeletalMesh, not merely a Skeleton asset.
    """

    import unreal

    report = {
        "ok": False,
        "retarget_ready": False,
        "source_path": source_path,
        "destination_path": destination_path,
        "destination_name": destination_name,
        "imported_object_paths": [],
        "skeletal_mesh_paths": [],
        "skeleton_paths": [],
        "animation_paths": [],
        "asset_checks": [],
        "errors": [],
    }
    if not os.path.isfile(source_path):
        report["errors"].append(f"FBX source does not exist: {source_path}")
        return report

    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
    task = unreal.AssetImportTask()
    task.set_editor_property("automated", True)
    task.set_editor_property("filename", source_path)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("destination_name", destination_name)
    task.set_editor_property("replace_existing", bool(replace_existing))
    task.set_editor_property("save", bool(save))

    options = unreal.FbxImportUI()
    options.original_import_type = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_SKELETAL_MESH
    options.import_as_skeletal = True
    options.import_mesh = True
    options.import_animations = True
    options.create_physics_asset = False
    options.import_materials = False
    options.import_textures = False
    options.skeleton = None
    options.anim_sequence_import_data.set_editor_property("import_bone_tracks", True)
    options.anim_sequence_import_data.set_editor_property("remove_redundant_keys", False)
    options.anim_sequence_import_data.set_editor_property(
        "animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME
    )
    task.set_editor_property("options", options)

    try:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    imported = [_asset_path(value) for value in task.get_editor_property("imported_object_paths") or []]
    report["imported_object_paths"] = list(dict.fromkeys(imported))
    discovered_skeletons = set()
    for path in report["imported_object_paths"]:
        asset = unreal.EditorAssetLibrary.load_asset(path)
        class_name = asset.get_class().get_name() if asset else ""
        skeleton = None
        if asset and class_name in {"SkeletalMesh", "AnimSequence"}:
            skeleton = asset.get_editor_property("skeleton")
        skeleton_path = _asset_path(skeleton.get_path_name()) if skeleton else ""
        if skeleton_path:
            discovered_skeletons.add(skeleton_path)
        report["asset_checks"].append(
            {"asset_path": path, "class": class_name, "skeleton": skeleton_path}
        )
        if class_name == "SkeletalMesh":
            report["skeletal_mesh_paths"].append(path)
        elif class_name == "Skeleton":
            report["skeleton_paths"].append(path)
        elif class_name == "AnimSequence":
            report["animation_paths"].append(path)
        if asset and save:
            unreal.EditorAssetLibrary.save_loaded_asset(asset, False)

    report["skeleton_paths"] = list(
        dict.fromkeys(report["skeleton_paths"] + sorted(discovered_skeletons))
    )
    report["ok"] = bool(report["animation_paths"] and report["skeleton_paths"])
    report["retarget_ready"] = bool(report["ok"] and report["skeletal_mesh_paths"])
    if not report["animation_paths"]:
        report["errors"].append("Source import created no AnimSequence.")
    if not report["skeletal_mesh_paths"]:
        report["errors"].append(
            "Source import created no SkeletalMesh; editor IK retarget baking requires a source mesh."
        )
    return report
