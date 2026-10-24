"""Verified Unreal asset-transfer operations used by composed pipelines."""

from __future__ import annotations

from typing import Any


CURRENT_CONTENT_BROWSER_DESTINATION = "__CURRENT_CONTENT_BROWSER__"


def resolve_import_destination(destination_path: str) -> tuple[str, str]:
    """Resolve an explicit package path or the current Content Browser folder."""
    import unreal

    requested = str(destination_path or "").strip()
    if requested != CURRENT_CONTENT_BROWSER_DESTINATION:
        return "/" + requested.strip("/"), "explicit"
    selected = list(unreal.EditorUtilityLibrary.get_selected_folder_paths() or [])
    selected = [str(path) for path in selected if str(path).startswith("/Game")]
    if selected:
        return selected[0].rstrip("/"), "current_content_browser_selection"
    try:
        current = str(unreal.EditorUtilityLibrary.get_current_content_browser_path() or "")
    except Exception:
        current = ""
    if current.startswith("/Game"):
        return current.rstrip("/"), "current_content_browser_path"
    return "/Game/AIStudio/Imports", "default_fallback"


def import_fbx_verified(
    source_file: str,
    destination_path: str = "/Game/AIStudio/Imports",
    *,
    subject: str = "asset",
    skeleton_path: str = "",
    replace_existing: bool = False,
    save: bool = True,
    assemble_lods: bool = False,
) -> dict[str, Any]:
    """Import an FBX with explicit options and verify the resulting asset."""
    import os
    from pathlib import Path
    import re
    import unreal

    source_file = os.path.abspath(os.path.expandvars(str(source_file or "")))
    if not os.path.isfile(source_file):
        raise FileNotFoundError(f"FBX source does not exist: {source_file}")
    destination_path, destination_source = resolve_import_destination(destination_path)
    if not destination_path.startswith("/Game/"):
        raise ValueError("destination_path must be an Unreal /Game/ package folder")
    asset_name = Path(source_file).stem
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", asset_name):
        raise ValueError("FBX basename must be a safe Unreal asset name")
    expected_path = f"{destination_path}/{asset_name}"
    if unreal.EditorAssetLibrary.does_asset_exist(expected_path) and not replace_existing:
        raise FileExistsError(f"Refusing to overwrite Unreal asset: {expected_path}")

    normalized_subject = str(subject or "asset").strip().lower()
    if normalized_subject not in {
        "animation", "anim", "skeletal_mesh", "skeleton", "rigged",
        "asset", "static_mesh", "static", "prop", "mesh",
    }:
        raise ValueError(f"Unsupported FBX import subject: {subject!r}")
    import_ui = unreal.FbxImportUI()
    import_ui.set_editor_property("automated_import_should_detect_type", False)
    import_ui.set_editor_property("import_materials", False)
    import_ui.set_editor_property("import_textures", False)

    if normalized_subject in {"animation", "anim"}:
        import_ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
        import_ui.set_editor_property("import_animations", True)
        import_ui.set_editor_property("import_mesh", False)
        if not skeleton_path:
            raise ValueError("skeleton_path is required for animation-only FBX import")
    elif normalized_subject in {"skeletal_mesh", "skeleton", "rigged"}:
        import_ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
        import_ui.set_editor_property("import_as_skeletal", True)
        import_ui.set_editor_property("import_mesh", True)
        import_ui.set_editor_property("import_animations", True)
    else:
        import_ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_STATIC_MESH)
        import_ui.set_editor_property("import_as_skeletal", False)
        import_ui.set_editor_property("import_mesh", True)
        import_ui.set_editor_property("import_animations", False)

    if skeleton_path:
        skeleton = unreal.load_asset(str(skeleton_path))
        if not isinstance(skeleton, unreal.Skeleton):
            raise TypeError(f"Selected asset is not a Skeleton: {skeleton_path}")
        import_ui.set_editor_property("skeleton", skeleton)

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_file)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", bool(replace_existing))
    task.set_editor_property("save", bool(save))
    task.set_editor_property("options", import_ui)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported_paths = [str(path) for path in (task.get_editor_property("imported_object_paths") or [])]
    if not imported_paths:
        raise RuntimeError(
            f"Unreal imported no objects from {source_file!r} into {destination_path!r}"
        )
    missing = [path for path in imported_paths if not unreal.EditorAssetLibrary.does_asset_exist(path)]
    if missing:
        raise RuntimeError(f"Imported assets failed readback: {missing}")
    if normalized_subject in {"asset", "static_mesh", "static", "prop", "mesh"}:
        wrong_type = [path for path in imported_paths
                      if not isinstance(unreal.load_asset(path), unreal.StaticMesh)]
        if wrong_type:
            raise RuntimeError(f"Static FBX import did not create StaticMesh assets: {wrong_type}")
    elif assemble_lods:
        raise ValueError("assemble_lods requires a static mesh import")
    lod_assemblies: list[dict[str, Any]] = []
    if assemble_lods:
        # Blender's FBX exporter emits named LOD objects as separate meshes.
        # Attach them explicitly; an import succeeding does not prove UE LODs exist.
        imported_by_name = {
            path.rsplit("/", 1)[-1].split(".", 1)[0]: path for path in imported_paths
        }
        lod_sources = []
        for name, path in imported_by_name.items():
            match = re.fullmatch(r"(.+)_LOD([1-9][0-9]*)", name, re.IGNORECASE)
            if match:
                lod_sources.append((match.group(1), int(match.group(2)), path))
        if not lod_sources:
            raise RuntimeError("LOD assembly requested but FBX imported no named LOD meshes")
        editor = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        if editor is None:
            raise RuntimeError("StaticMeshEditorSubsystem unavailable for LOD assembly")
        for base_name, lod_index, source_path in sorted(lod_sources, key=lambda row: row[1]):
            base_path = imported_by_name.get(base_name)
            if not base_path:
                raise RuntimeError(f"LOD{lod_index} has no imported base mesh: {base_name}")
            base_mesh = unreal.load_asset(base_path)
            source_mesh = unreal.load_asset(source_path)
            result = editor.set_lod_from_static_mesh(base_mesh, lod_index, source_mesh, 0, True)
            actual_lods = int(base_mesh.get_num_lods())
            if int(result) != lod_index or actual_lods < lod_index + 1:
                raise RuntimeError(
                    f"LOD assembly failed for {base_path} LOD{lod_index}: "
                    f"result={result}, actual_lods={actual_lods}"
                )
            lod_assemblies.append({"base_path": base_path, "source_path": source_path,
                                   "lod_index": lod_index, "actual_lods": actual_lods})
    animation_proof: dict[str, Any] = {}
    if normalized_subject in {"animation", "anim"}:
        expected_object = f"{expected_path}.{asset_name}"
        if imported_paths != [expected_object]:
            raise RuntimeError(
                f"Animation import did not produce exactly the requested asset: {imported_paths}"
            )
        animation = unreal.load_asset(expected_path)
        if not isinstance(animation, unreal.AnimSequence):
            raise RuntimeError(f"Animation FBX did not create an AnimSequence: {expected_path}")
        if animation.get_editor_property("skeleton") != skeleton:
            raise RuntimeError("Imported animation is not assigned to the selected Skeleton")
        track_count = len(unreal.AnimationLibrary.get_animation_track_names(animation))
        frame_count = int(unreal.AnimationLibrary.get_num_frames(animation))
        if track_count < 1 or frame_count < 1:
            raise RuntimeError("Imported animation has no bone tracks or frames")
        animation_proof = {
            "skeleton_path": skeleton.get_path_name(),
            "track_count": track_count,
            "frame_count": frame_count,
        }
    if save:
        for path in imported_paths:
            if unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False) is False:
                raise RuntimeError(f"Unreal failed to save imported asset: {path}")
    return {
        "source_file": source_file,
        "destination_path": destination_path,
        "destination_source": destination_source,
        "subject": normalized_subject,
        "imported_paths": imported_paths,
        "asset_path": imported_paths[0],
        "asset_count": len(imported_paths),
        "lod_assemblies": lod_assemblies,
        **animation_proof,
    }


def registry_readback(
    imported_paths: list[str] | tuple[str, ...] | None = None,
    destination_path: str = "",
) -> dict[str, Any]:
    """Prove imported packages resolve through the Asset Registry."""
    import unreal

    def object_path(data: Any) -> str:
        # AssetData.get_soft_object_path is not exposed by every supported
        # Unreal Python binding. Package and asset names are stable readback
        # fields and form the canonical object path returned by FBX import.
        package = str(data.package_name)
        asset = str(data.asset_name)
        return f"{package}.{asset}" if package and asset else ""

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    paths = [str(path) for path in (imported_paths or []) if str(path)]
    assets = []
    for path in paths:
        package_name = path.split(".", 1)[0]
        # UE 5.8's Python binding expects an ObjectPath/Name here, not a
        # SoftObjectPath instance. A string is coerced to Name by the binding.
        data = registry.get_asset_by_object_path(path)
        if not data or not data.is_valid():
            data = registry.get_asset_by_object_path(
                f"{package_name}.{package_name.rsplit('/', 1)[-1]}"
            )
        if data and data.is_valid():
            assets.append(object_path(data))
    if destination_path and not paths:
        folder = "/" + str(destination_path).strip("/")
        assets = [
            object_path(item)
            for item in registry.get_assets_by_path(folder, recursive=True)
        ]
    missing = [path for path in paths if path not in assets and path.split(".", 1)[0] not in assets]
    return {
        "ok": not missing and bool(assets),
        "assets": assets,
        "asset_count": len(assets),
        "missing": missing,
        "destination_path": destination_path,
    }


def rollback_imported_assets(imported_paths: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Delete only the assets returned by this adapter's import result."""
    import unreal

    deleted = []
    failed = []
    for path in imported_paths or []:
        asset_path = str(path).split(".", 1)[0]
        if unreal.EditorAssetLibrary.delete_asset(asset_path):
            deleted.append(asset_path)
        else:
            failed.append(asset_path)
    return {"ok": not failed, "deleted": deleted, "failed": failed}
