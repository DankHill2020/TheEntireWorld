"""Validation helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _asset_exists(unreal, path: str) -> bool:
    if not path:
        return False
    editor = unreal.EditorAssetLibrary
    return bool(editor.does_asset_exist(path) or editor.does_directory_exist(path))


def references(paths=None, compile_blueprints=True, save=False):
    """Validate paths and optionally compile Blueprints without saving by default."""
    import unreal

    paths = paths or []
    report = {
        "checked_paths": paths,
        "missing": [],
        "dependencies": {},
        "blueprints": {},
        "warnings": [],
        "save": bool(save),
    }

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    editor = unreal.EditorAssetLibrary
    if not paths:
        paths = []
        for data in registry.get_assets_by_path("/Game", recursive=True):
            class_name = str(data.asset_class_path.asset_name)
            if class_name in {"Blueprint", "AnimBlueprint", "WidgetBlueprint", "GameplayAbilityBlueprint"}:
                paths.append(str(data.object_path))
        report["checked_paths"] = paths

    for path in paths:
        if not _asset_exists(unreal, path):
            report["missing"].append(path)
            continue
        try:
            deps = registry.get_dependencies(path, unreal.AssetRegistryDependencyOptions())
            refs = registry.get_referencers(path, unreal.AssetRegistryDependencyOptions())
            missing_deps = []
            for dep in deps:
                dep_path = str(dep)
                if dep_path.startswith("/Game") and not _asset_exists(unreal, dep_path):
                    missing_deps.append(dep_path)
            report["dependencies"][path] = {
                "dependencies": [str(item) for item in deps],
                "referencers": [str(item) for item in refs],
                "missing_dependencies": missing_deps,
            }
            report["missing"].extend(item for item in missing_deps if item not in report["missing"])
        except Exception as exc:
            report["warnings"].append(f"{path}: dependency scan failed: {exc}")

        if compile_blueprints and editor.does_asset_exist(path):
            try:
                asset = editor.load_asset(path)
                if asset and asset.get_class().get_name() in {"Blueprint", "AnimBlueprint", "WidgetBlueprint"}:
                    unreal.BlueprintEditorLibrary.compile_blueprint(asset)
                    report["blueprints"][path] = {"compiled": True, "class": asset.get_class().get_name()}
            except Exception as exc:
                report["blueprints"][path] = {"compiled": False, "error": str(exc)}

    report["summary"] = {
        "checked_count": len(paths),
        "missing_count": len(report["missing"]),
        "blueprint_count": len(report["blueprints"]),
        "warning_count": len(report["warnings"]),
        "recommended_fix_order": [
            "Restore or redirect missing assets.",
            "Fix invalid parent classes and missing interfaces.",
            "Fix Blueprint compiler errors.",
            "Re-run validation.",
            "Save only after the report is clean.",
        ],
    }
    return json.dumps(report, indent=2, default=str)
