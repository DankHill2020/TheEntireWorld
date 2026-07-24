"""Asset inspection helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def object_path(asset_path):
    """Return an Unreal object path for either a package or object path input."""

    value = str(asset_path or "").strip()
    leaf = value.rsplit("/", 1)[-1]
    if not value or "." in leaf:
        return value
    return f"{value}.{leaf}"


def load_asset(unreal, asset_path):
    """Load an asset even when EditorAssetLibrary rejects a package-only path."""

    value = str(asset_path or "").strip()
    if not value:
        return None
    try:
        asset = unreal.EditorAssetLibrary.load_asset(value)
        if asset:
            return asset
    except Exception:
        pass
    try:
        return unreal.load_object(None, object_path(value))
    except Exception:
        return None


def load_blueprint_class(unreal, asset_path):
    """Resolve a generated class from package, object, or generated-class paths."""

    value = str(asset_path or "").strip()
    if not value:
        return None
    try:
        resolved = unreal.EditorAssetLibrary.load_blueprint_class(value)
        if resolved:
            return resolved
    except Exception:
        pass

    generated_path = object_path(value)
    if not generated_path.endswith("_C"):
        generated_path += "_C"
    try:
        resolved = unreal.load_class(None, generated_path)
        if resolved:
            return resolved
    except Exception:
        pass

    asset = load_asset(unreal, value)
    if not asset:
        return None
    try:
        return asset.generated_class()
    except Exception:
        try:
            return asset.get_editor_property("generated_class")
        except Exception:
            return None


def get_dependencies(asset_path, recursive=True):
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions()
    deps = registry.get_dependencies(asset_path, options)
    refs = registry.get_referencers(asset_path, options)
    return json.dumps({
        "asset_path": asset_path,
        "recursive": bool(recursive),
        "dependencies": [str(item) for item in deps],
        "referencers": [str(item) for item in refs],
    }, indent=2, default=str)


def inspect_asset(asset_path):
    import unreal

    editor = unreal.EditorAssetLibrary
    if not editor.does_asset_exist(asset_path):
        return json.dumps({"asset_path": asset_path, "exists": False}, indent=2)

    asset = editor.load_asset(asset_path)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    data = registry.get_asset_by_object_path(asset_path)
    result = {
        "asset_path": asset_path,
        "exists": True,
        "name": asset.get_name() if asset else "",
        "class": asset.get_class().get_name() if asset else "",
        "package": str(data.package_name) if data else "",
        "tags": dict(data.tags_and_values) if data else {},
        "dependencies": json.loads(get_dependencies(asset_path)),
    }
    return json.dumps(result, indent=2, default=str)


def find_asset_path_by_name(file_name, expected_class="", directory="/Game", allow_engine=False):
    """Resolve a user-facing Unreal asset name/path to a package path.

    This is the shared version of the old `find_uasset_path` pattern. It accepts
    `/Game/...`, `/Game/Asset.Asset`, or a bare asset name such as `Run_Fwd`.
    Returns the package path form expected by most EditorAssetLibrary/load_asset
    APIs, for example `/Game/Animations/Run_Fwd`.
    """
    import unreal

    text = str(file_name or "").strip().replace(".uasset", "")
    if not text:
        return None

    def _package(path):
        return str(path or "").split(".", 1)[0]

    for candidate in (text, _package(text)):
        try:
            if candidate and unreal.EditorAssetLibrary.does_asset_exist(candidate):
                return _package(candidate)
        except Exception:
            pass
        try:
            asset = unreal.load_asset(candidate)
            if asset:
                return _package(asset.get_path_name())
        except Exception:
            pass

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = registry.get_assets_by_path(directory or "/Game", recursive=True)
    except Exception:
        assets = registry.get_all_assets(True)

    needle = text.lower()
    best = None
    best_score = -1
    for data in assets:
        try:
            package_name = str(data.package_name)
            asset_name = str(data.asset_name)
            class_name = str(data.asset_class_path.asset_name)
        except Exception:
            continue
        if not allow_engine and package_name.startswith("/Engine"):
            continue
        if expected_class and expected_class.lower() not in class_name.lower():
            continue
        haystack = f"{asset_name} {package_name}".lower()
        score = 0
        if needle == asset_name.lower():
            score += 100
        if needle == package_name.lower():
            score += 90
        if needle in haystack:
            score += 25
        if needle.replace("_", "") in haystack.replace("_", ""):
            score += 10
        if score > best_score:
            best_score = score
            best = package_name
    return best if best_score > 0 else None


def resolve_asset(file_name, expected_class="", directory="/Game"):
    """Return a compact serializable asset handle by name/path."""
    import json
    import unreal

    path = find_asset_path_by_name(file_name, expected_class=expected_class, directory=directory)
    if not path:
        return json.dumps({"ok": False, "query": file_name, "matches": []}, indent=2)
    asset = unreal.EditorAssetLibrary.load_asset(path)
    return json.dumps(
        {
            "ok": bool(asset),
            "query": file_name,
            "asset_path": path,
            "object_path": asset.get_path_name() if asset else "",
            "name": asset.get_name() if asset else path.rsplit("/", 1)[-1],
            "class": asset.get_class().get_name() if asset else "",
        },
        indent=2,
        default=str,
    )


def delete_assets(asset_paths, dry_run=False):
    import unreal

    paths = asset_paths if isinstance(asset_paths, list) else [asset_paths]
    rows = []
    ok = True
    for path in paths:
        path = str(path or "")
        exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
        deleted = False
        if exists_before and not dry_run:
            deleted = bool(unreal.EditorAssetLibrary.delete_asset(path))
        exists_after = bool(unreal.EditorAssetLibrary.does_asset_exist(path))
        row_ok = exists_before and (dry_run or deleted) and (dry_run or not exists_after)
        ok = ok and row_ok
        rows.append({"asset_path": path, "exists_before": exists_before, "deleted": deleted, "exists_after": exists_after, "ok": row_ok})
    return json.dumps({"ok": ok, "dry_run": bool(dry_run), "results": rows}, indent=2, default=str)


def rename_asset(asset_path, new_asset_path, dry_run=False):
    import unreal

    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    renamed = False
    if exists_before and not dry_run:
        renamed = bool(unreal.EditorAssetLibrary.rename_asset(asset_path, new_asset_path))
    return json.dumps({
        "ok": bool(exists_before and (dry_run or renamed) and (dry_run or unreal.EditorAssetLibrary.does_asset_exist(new_asset_path))),
        "asset_path": asset_path,
        "new_asset_path": new_asset_path,
        "exists_before": exists_before,
        "renamed": renamed,
        "dry_run": bool(dry_run),
    }, indent=2, default=str)


def duplicate_asset(source_asset_path, target_asset_path, dry_run=False):
    import unreal

    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(source_asset_path))
    duplicated = False
    if exists_before and not dry_run:
        duplicated = bool(unreal.EditorAssetLibrary.duplicate_asset(source_asset_path, target_asset_path))
    return json.dumps({
        "ok": bool(exists_before and (dry_run or duplicated) and (dry_run or unreal.EditorAssetLibrary.does_asset_exist(target_asset_path))),
        "source_asset_path": source_asset_path,
        "target_asset_path": target_asset_path,
        "source_exists": exists_before,
        "duplicated": duplicated,
        "dry_run": bool(dry_run),
    }, indent=2, default=str)


def save_assets(asset_paths, only_if_is_dirty=False):
    import unreal

    paths = asset_paths if isinstance(asset_paths, list) else [asset_paths]
    rows = []
    ok = True
    for path in paths:
        asset = load_asset(unreal, path)
        saved = bool(asset and unreal.EditorAssetLibrary.save_loaded_asset(asset, bool(only_if_is_dirty)))
        ok = ok and saved
        rows.append({"asset_path": str(path), "loaded": bool(asset), "saved": saved})
    return json.dumps({"ok": ok, "results": rows}, indent=2, default=str)


def create_by_class_path(asset_path, class_path, initial_properties=None):
    import unreal

    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable"}, indent=2)
    return unreal.AIStudioBridgeLibrary.create_known_asset_by_class_path(
        asset_path,
        class_path,
        json.dumps(initial_properties or {}),
    )


def inspect_reflected(asset_path, property_names=None):
    import unreal

    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable"}, indent=2)
    return unreal.AIStudioBridgeLibrary.inspect_reflected_asset(asset_path, property_names or [])


def set_reflected_property(asset_path, property_name, value):
    import unreal

    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable"}, indent=2)
    return unreal.AIStudioBridgeLibrary.set_reflected_asset_property(
        asset_path,
        property_name,
        json.dumps(value),
    )


def array_add_object_reference(asset_path, property_name, object_path):
    import unreal

    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable"}, indent=2)
    return unreal.AIStudioBridgeLibrary.add_object_reference_to_reflected_array(
        asset_path,
        property_name,
        object_path,
    )


def array_remove_object_reference(asset_path, property_name, object_path):
    import unreal

    if not hasattr(unreal, "AIStudioBridgeLibrary"):
        return json.dumps({"ok": False, "status": "AIStudioBridgeLibrary_unavailable"}, indent=2)
    return unreal.AIStudioBridgeLibrary.remove_object_reference_from_reflected_array(
        asset_path,
        property_name,
        object_path,
    )
