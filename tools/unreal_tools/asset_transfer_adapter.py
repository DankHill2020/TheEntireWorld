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
) -> dict[str, Any]:
    """Import an FBX with explicit UE 5.8 options and return asset readback."""
    import os
    import unreal

    source_file = os.path.abspath(os.path.expandvars(str(source_file or "")))
    if not os.path.isfile(source_file):
        raise FileNotFoundError(f"FBX source does not exist: {source_file}")
    destination_path, destination_source = resolve_import_destination(destination_path)
    if not destination_path.startswith("/Game/"):
        raise ValueError("destination_path must be an Unreal /Game/ package folder")

    normalized_subject = str(subject or "asset").strip().lower()
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
        if not skeleton:
            raise ValueError(f"Skeleton could not be loaded: {skeleton_path}")
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
    if save:
        for path in imported_paths:
            unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False)
    return {
        "source_file": source_file,
        "destination_path": destination_path,
        "destination_source": destination_source,
        "subject": normalized_subject,
        "imported_paths": imported_paths,
        "asset_path": imported_paths[0],
        "asset_count": len(imported_paths),
    }


def registry_readback(
    imported_paths: list[str] | tuple[str, ...] | None = None,
    destination_path: str = "",
) -> dict[str, Any]:
    """Prove imported packages resolve through the Asset Registry."""
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    paths = [str(path) for path in (imported_paths or []) if str(path)]
    assets = []
    for path in paths:
        package_name = path.split(".", 1)[0]
        data = registry.get_asset_by_object_path(unreal.SoftObjectPath(path))
        if not data or not data.is_valid():
            data = registry.get_asset_by_object_path(
                unreal.SoftObjectPath(f"{package_name}.{package_name.rsplit('/', 1)[-1]}")
            )
        if data and data.is_valid():
            assets.append(str(data.get_soft_object_path()))
    if destination_path and not paths:
        folder = "/" + str(destination_path).strip("/")
        assets = [
            str(item.get_soft_object_path())
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
