"""Project-level Unreal inspection/refactor helpers."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def find_references(target_name, folder_path="/Game/"):
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = registry.get_assets_by_path(folder_path or "/Game/", recursive=True)
    except Exception:
        assets = registry.get_all_assets(True)
    needle = str(target_name or "").lower()
    matches = []
    for data in assets:
        package = str(data.package_name)
        name = str(data.asset_name)
        haystack = f"{name} {package} {dict(data.tags_and_values)}".lower()
        if needle and needle in haystack:
            matches.append({"asset_name": name, "package": package, "class": str(data.asset_class_path.asset_name)})
    return _result(ok=True, target_name=target_name, folder_path=folder_path, matches=matches, count=len(matches))


def rename_symbol(old_name, new_name, folder_path=""):
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    folder = str(folder_path or "/Game/")
    assets = registry.get_assets_by_path(folder, recursive=True)
    results = []
    changed = []
    failures = []
    for data in assets:
        if str(data.asset_class_path.asset_name) not in {
            "Blueprint",
            "AnimBlueprint",
            "WidgetBlueprint",
        }:
            continue
        blueprint = data.get_asset()
        if blueprint is None:
            continue
        raw = unreal.AIStudioBridgeLibrary.rename_blueprint_symbol(
            blueprint,
            str(old_name),
            str(new_name),
            True,
        )
        try:
            row = json.loads(raw)
        except Exception:
            row = {"ok": False, "raw": str(raw)}
        results.append(row)
        if row.get("changed"):
            changed.append(str(data.get_soft_object_path()))
        if row.get("changed") and not row.get("ok"):
            failures.append(row)
    return _result(
        ok=not failures,
        status="renamed" if changed else "symbol_not_found",
        old_name=old_name,
        new_name=new_name,
        folder_path=folder,
        changed_assets=changed,
        changed_count=len(changed),
        scanned_blueprints=len(results),
        failures=failures,
        results=results,
    )
