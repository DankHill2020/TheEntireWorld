"""Unreal Skeletal Mesh import/update workflow used by the Rigging tool."""

from __future__ import annotations

import os
import re
from typing import Any


def sanitize_rig_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    name = re.sub(r"_+", "_", name).strip("_")
    for prefix in ("SKM_", "SK_", "PHYS_"):
        if name.upper().startswith(prefix):
            name = name[len(prefix):]
            break
    if not name:
        raise ValueError("Rig name is required.")
    if name[0].isdigit():
        name = "Rig_" + name
    return name


def character_asset_folder(parent_path: str, rig_name: str) -> str:
    """Return the per-character Unreal folder below *parent_path*."""
    name = sanitize_rig_name(rig_name)
    parent = "/" + str(parent_path or "/Game/Characters").strip("/")
    if parent.rsplit("/", 1)[-1].lower() == name.lower():
        return parent
    return f"{parent}/{name}"


def _asset_path(asset: Any) -> str:
    if not asset:
        return ""
    return str(asset.get_path_name()).split(".", 1)[0]


def list_skeletal_import_targets(directory: str = "/Game") -> dict[str, Any]:
    import unreal

    folder = "/" + str(directory or "/Game").strip("/")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.search_all_assets(True)
    classes = {"SkeletalMesh", "Skeleton", "PhysicsAsset"}
    grouped = {"skeletal_meshes": [], "skeletons": [], "physics_assets": []}
    keys = {"SkeletalMesh": "skeletal_meshes", "Skeleton": "skeletons", "PhysicsAsset": "physics_assets"}
    for data in registry.get_assets_by_path(folder, recursive=True):
        class_name = str(data.asset_class_path.asset_name)
        if class_name not in classes:
            continue
        package_name = str(data.package_name)
        row = {"name": str(data.asset_name), "path": package_name, "object_path": f"{package_name}.{data.asset_name}"}
        if class_name == "SkeletalMesh":
            mesh = data.get_asset()
            try:
                row["skeleton"] = _asset_path(mesh.get_editor_property("skeleton"))
                row["physics_asset"] = _asset_path(mesh.get_editor_property("physics_asset"))
            except Exception:
                row["skeleton"], row["physics_asset"] = "", ""
        grouped[keys[class_name]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["path"].lower())
    return {"ok": True, "directory": folder, **grouped}


def _rename_asset(unreal: Any, source: str, destination: str) -> str:
    source, destination = source.split(".", 1)[0], destination.split(".", 1)[0]
    if not source or source == destination:
        return source
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        raise RuntimeError(f"Target Unreal asset already exists: {destination}")
    if not unreal.EditorAssetLibrary.rename_asset(source, destination):
        raise RuntimeError(f"Could not rename Unreal asset {source} to {destination}")
    return destination


def import_skeletal_mesh_fbx(
    source_file: str,
    rig_name: str,
    destination_path: str = "/Game/Characters",
    *,
    existing_skeletal_mesh_path: str = "",
    skeleton_mode: str = "create_new",
    existing_skeleton_path: str = "",
    create_physics_asset: bool = True,
) -> dict[str, Any]:
    """Import or update one Skeletal Mesh with an explicit skeleton policy."""
    import unreal

    source_file = os.path.abspath(os.path.expandvars(str(source_file or "")))
    if not os.path.isfile(source_file):
        raise FileNotFoundError(f"FBX source does not exist: {source_file}")
    name = sanitize_rig_name(rig_name)
    mode = str(skeleton_mode or "").strip().lower()
    if mode not in {"create_new", "use_existing"}:
        raise ValueError("skeleton_mode must be 'create_new' or 'use_existing'.")

    existing_mesh = unreal.EditorAssetLibrary.load_asset(existing_skeletal_mesh_path) if existing_skeletal_mesh_path else None
    if existing_skeletal_mesh_path and existing_mesh is None:
        raise ValueError(f"Existing Skeletal Mesh could not be loaded: {existing_skeletal_mesh_path}")
    if existing_mesh:
        mesh_package = _asset_path(existing_mesh)
        destination_path, _, mesh_name = mesh_package.rpartition("/")
    else:
        destination_path = character_asset_folder(destination_path, name)
        if not unreal.EditorAssetLibrary.does_directory_exist(destination_path):
            if not unreal.EditorAssetLibrary.make_directory(destination_path):
                raise RuntimeError(f"Could not create Unreal character folder: {destination_path}")
        mesh_name = f"SKM_{name}"

    skeleton = None
    if mode == "use_existing":
        if existing_skeleton_path:
            skeleton = unreal.EditorAssetLibrary.load_asset(existing_skeleton_path)
        elif existing_mesh:
            skeleton = existing_mesh.get_editor_property("skeleton")
        if skeleton is None:
            raise ValueError("Select an existing Skeleton before importing with 'Use Existing Skeleton'.")
        if existing_mesh:
            mesh_skeleton = existing_mesh.get_editor_property("skeleton")
            if mesh_skeleton is None:
                raise ValueError("The selected existing Skeletal Mesh has no Skeleton assigned.")
            if skeleton != mesh_skeleton:
                raise ValueError(
                    "The selected Skeleton does not match the existing Skeletal Mesh. "
                    "Create a new Skeletal Mesh to use a different Skeleton."
                )
            skeleton = mesh_skeleton
    elif existing_mesh:
        raise ValueError("Updating an existing Skeletal Mesh requires its existing Skeleton; choose 'Use Existing Skeleton'.")

    import_ui = unreal.FbxImportUI()
    import_ui.set_editor_property("automated_import_should_detect_type", False)
    import_ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    import_ui.set_editor_property("import_as_skeletal", True)
    import_ui.set_editor_property("import_mesh", True)
    import_ui.set_editor_property("import_animations", False)
    import_ui.set_editor_property("import_materials", False)
    import_ui.set_editor_property("import_textures", False)
    if skeleton is not None:
        import_ui.set_editor_property("skeleton", skeleton)
    import_ui.set_editor_property("create_physics_asset", bool(create_physics_asset and not existing_mesh))
    try:
        skeletal_data = import_ui.get_editor_property("skeletal_mesh_import_data")
        skeletal_data.set_editor_property("import_meshes_in_bone_hierarchy", True)
    except Exception:
        pass

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source_file)
    task.set_editor_property("destination_path", destination_path)
    task.set_editor_property("destination_name", mesh_name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", bool(existing_mesh))
    task.set_editor_property("save", True)
    task.set_editor_property("options", import_ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    mesh_path = f"{destination_path}/{mesh_name}"
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    if mesh is None:
        imported = [str(path).split(".", 1)[0] for path in (task.get_editor_property("imported_object_paths") or [])]
        for path in imported:
            candidate = unreal.EditorAssetLibrary.load_asset(path)
            if candidate is not None and candidate.get_class().get_name() == "SkeletalMesh":
                mesh = candidate
                break
    if mesh is None:
        raise RuntimeError("Unreal did not produce or update the requested Skeletal Mesh.")
    mesh_path = _asset_path(mesh)

    imported_skeleton = mesh.get_editor_property("skeleton")
    skeleton_path = _asset_path(imported_skeleton)
    if mode == "create_new":
        skeleton_path = _rename_asset(unreal, skeleton_path, f"{destination_path}/SK_{name}")
        imported_skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)

    physics_asset = None
    try:
        physics_asset = mesh.get_editor_property("physics_asset")
    except Exception:
        pass
    physics_path = _asset_path(physics_asset)
    warnings = []
    if create_physics_asset and not physics_path:
        bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
        if bridge:
            raw = bridge.create_physics_asset(mesh_path, f"{destination_path}/PHYS_{name}", True)
            physics_asset = mesh.get_editor_property("physics_asset")
            physics_path = _asset_path(physics_asset)
            if not physics_path:
                warnings.append(f"PhysicsAsset bridge returned without assigning an asset: {raw}")
        else:
            warnings.append("PhysicsAsset was not generated because AIStudioBridgeLibrary is unavailable.")
    elif physics_path and mode == "create_new":
        desired_physics = f"{destination_path}/PHYS_{name}"
        if physics_path != desired_physics and not unreal.EditorAssetLibrary.does_asset_exist(desired_physics):
            physics_path = _rename_asset(unreal, physics_path, desired_physics)

    unreal.EditorAssetLibrary.save_asset(mesh_path, only_if_is_dirty=False)
    if skeleton_path:
        unreal.EditorAssetLibrary.save_asset(skeleton_path, only_if_is_dirty=False)
    if physics_path:
        unreal.EditorAssetLibrary.save_asset(physics_path, only_if_is_dirty=False)
    return {
        "ok": True,
        "status": "updated_existing_mesh" if existing_mesh else "created_new_mesh",
        "source_file": source_file,
        "rig_name": name,
        "skeletal_mesh_path": mesh_path,
        "skeleton_path": skeleton_path,
        "physics_asset_path": physics_path,
        "skeleton_mode": mode,
        "warnings": warnings,
    }


__all__ = [
    "character_asset_folder",
    "import_skeletal_mesh_fbx",
    "list_skeletal_import_targets",
    "sanitize_rig_name",
]
