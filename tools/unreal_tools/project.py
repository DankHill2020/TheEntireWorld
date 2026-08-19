"""Project-level Unreal inspection/refactor helpers."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def project_snapshot(directory="/Game/", mode="standard", limit=1000):
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = list(registry.get_assets_by_path(str(directory or "/Game/"), recursive=True) or [])
    rows = [
        {
            "name": str(data.asset_name),
            "package": str(data.package_name),
            "class": str(data.asset_class_path.asset_name),
        }
        for data in assets[: max(1, int(limit))]
    ]
    actors = []
    try:
        for actor in unreal.EditorLevelLibrary.get_all_level_actors() or []:
            actors.append({
                "name": str(actor.get_actor_label()),
                "class": str(actor.get_class().get_name()),
                "path": str(actor.get_path_name()),
            })
    except Exception:
        pass
    try:
        project_file = str(unreal.Paths.get_project_file_path())
    except Exception:
        project_file = ""
    return _result(
        ok=True,
        mode=str(mode or "standard"),
        directory=str(directory or "/Game/"),
        project_file=project_file,
        assets=rows,
        asset_count=len(assets),
        actors=actors,
        actor_count=len(actors),
    )


def project_debug(directory="/Game/", paths=None, compile_blueprints=True, save=False):
    import unreal

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    requested = [str(value) for value in paths or [] if value]
    if requested:
        data_rows = [registry.get_asset_by_object_path(path) for path in requested]
        data_rows = [row for row in data_rows if row]
    else:
        data_rows = list(registry.get_assets_by_path(str(directory or "/Game/"), recursive=True) or [])
    options = unreal.AssetRegistryDependencyOptions()
    rows = []
    failures = []
    for data in data_rows:
        package = str(data.package_name)
        asset = data.get_asset()
        class_name = str(data.asset_class_path.asset_name)
        dependencies = [str(value) for value in registry.get_dependencies(package, options) or []]
        missing_dependencies = [
            value for value in dependencies
            if value.startswith("/Game/") and not unreal.EditorAssetLibrary.does_asset_exist(value)
        ]
        compiled = None
        compile_error = ""
        if compile_blueprints and "Blueprint" in class_name and asset is not None:
            try:
                unreal.BlueprintEditorLibrary.compile_blueprint(asset)
                compiled = True
                if save:
                    compiled = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
            except Exception as exc:
                compiled = False
                compile_error = str(exc)
        row = {
            "package": package,
            "class": class_name,
            "loaded": asset is not None,
            "compiled": compiled,
            "saved": bool(save and compiled),
            "missing_dependencies": missing_dependencies,
            "compile_error": compile_error,
        }
        if not row["loaded"] or missing_dependencies or compiled is False:
            failures.append(package)
        rows.append(row)
    return _result(
        ok=not failures,
        directory=str(directory or "/Game/"),
        scanned=len(rows),
        failures=failures,
        assets=rows,
    )


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
