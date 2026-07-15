"""Asset inspection helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


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
        haystack = f"{asset_name} {package_name} {class_name}".lower()
        score = 0
        if needle == asset_name.lower():
            score += 100
        if needle == package_name.lower():
            score += 90
        if needle in haystack:
            score += 40
        if needle.replace("_", "") in haystack.replace("_", ""):
            score += 30

        # Tokenized word matching for fuzzy/unclear queries (e.g. "metahuman retargeter")
        query_words = [w for w in needle.replace("_", " ").replace("-", " ").split() if len(w) > 1]
        if query_words:
            matched_words = sum(1 for w in query_words if w in haystack)
            if matched_words == len(query_words):
                score += 50
            elif matched_words > 0:
                score += matched_words * 15

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
