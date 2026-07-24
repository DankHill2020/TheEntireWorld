"""Verified UE 5.8 animation-only FBX import adapter."""

from __future__ import annotations


def import_animation_verified(
    anim_path,
    skeleton_path,
    destination_path,
    destination_name="",
):
    """Import animation-only FBX data and verify the final Asset Registry path."""
    import unreal

    from unreal_tools.asset_transfer_adapter import import_fbx_verified

    result = import_fbx_verified(
        source_file=str(anim_path),
        destination_path=str(destination_path),
        subject="animation",
        skeleton_path=str(skeleton_path),
        replace_existing=True,
        save=True,
    )
    imported_paths = list(result.get("imported_paths") or [])
    if destination_name and imported_paths:
        source_path = str(imported_paths[0]).split(".", 1)[0]
        target_path = (
            f"{str(destination_path).rstrip('/')}/{str(destination_name).strip()}"
        )
        if source_path != target_path:
            if not unreal.EditorAssetLibrary.rename_asset(source_path, target_path):
                raise RuntimeError(
                    f"Imported animation could not be renamed from {source_path} "
                    f"to {target_path}"
                )
            unreal.EditorAssetLibrary.save_asset(
                target_path,
                only_if_is_dirty=False,
            )
            imported_paths[0] = target_path
    missing = [
        path
        for path in imported_paths
        if not unreal.EditorAssetLibrary.does_asset_exist(path)
    ]
    if missing:
        raise RuntimeError(f"Imported animation failed readback: {missing}")
    return {
        **result,
        "ok": bool(imported_paths),
        "asset_path": imported_paths[0] if imported_paths else "",
        "imported_paths": imported_paths,
        "destination_name": str(destination_name or ""),
    }
