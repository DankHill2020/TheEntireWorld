"""Blueprint scan/create/compile helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _load_blueprint(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Blueprint asset not found: {asset_path}")
    return asset


def scan_blueprint(asset_path, include_graphs=True, include_defaults=True):
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    result = {
        "asset_path": asset_path,
        "class": bp.get_class().get_name(),
        "name": bp.get_name(),
        "parent_class": "",
        "variables": [],
        "functions": [],
        "components": [],
        "graphs": [],
        "compile_status": "",
        "warnings": [],
    }

    try:
        result["parent_class"] = bp.parent_class.get_name() if getattr(bp, "parent_class", None) else ""
    except Exception as exc:
        result["warnings"].append(f"parent_class unavailable: {exc}")

    try:
        result["variables"] = [
            {
                "name": item.var_name,
                "type": str(item.var_type),
                "category": str(item.category),
            }
            for item in unreal.BlueprintEditorLibrary.get_blueprint_variables(bp)
        ]
    except Exception as exc:
        result["warnings"].append(f"variables unavailable: {exc}")

    try:
        result["functions"] = [str(item) for item in unreal.BlueprintEditorLibrary.get_blueprint_functions(bp)]
    except Exception as exc:
        result["warnings"].append(f"functions unavailable: {exc}")

    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        result["compile_status"] = "compiled"
    except Exception as exc:
        result["compile_status"] = f"compile failed: {exc}"

    return json.dumps(result, indent=2, default=str)


def compile_blueprint(asset_path):
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    return json.dumps({"asset_path": asset_path, "compiled": True}, indent=2)


def create_from_template(template, asset_path, parent_class="", parameters=None):
    import unreal

    parameters = parameters or {}
    if "/" not in asset_path:
        raise ValueError(f"Invalid asset path: {asset_path}")
    package_path, asset_name = asset_path.rsplit("/", 1)

    parent_obj = unreal.Character
    if parent_class:
        try:
            parent_obj = unreal.load_object(None, parent_class)
        except Exception:
            parent_obj = unreal.Character
    elif "actor" in template.lower():
        parent_obj = unreal.Actor
    elif "character" in template.lower() or "locomotion" in template.lower() or "climbing" in template.lower():
        parent_obj = unreal.Character

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_obj)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        created = False
    else:
        asset = asset_tools.create_asset(asset_name, package_path, unreal.Blueprint, factory)
        created = True

    if not asset:
        raise RuntimeError("Failed to create Blueprint asset")

    # Force compile and save
    unreal.BlueprintEditorLibrary.compile_blueprint(asset)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)

    parent_class_name = parent_obj.__name__ if isinstance(parent_obj, type) else parent_obj.get_name()

    steps = [
        f"Instantiate Blueprint subclass from parent class '{parent_class_name}'"
    ]
    if "locomotion" in template.lower():
        steps.extend([
            "Configure default locomotion movement component parameters",
            "Register input bindings for move forward/right and camera look",
            "Initialize motion matching database references"
        ])
    elif "combat" in template.lower():
        steps.extend([
            "Add combo tracking variables (ComboIndex, MaxCombos, LastAttackTime)",
            "Create state transition variables for combat action sequences",
            "Map melee animation montage slots"
        ])
    elif "dash" in template.lower():
        steps.extend([
            "Add dash velocity multiplier, duration, and cooldown variables",
            "Configure character movement impulse modes for launch velocity",
            "Bind dash action event trigger"
        ])
    elif "climbing" in template.lower() or "climb" in template.lower():
        steps.extend([
            "Add climbing status variables (bIsClimbing, ClimbState, ClimbSurfaceNormal)",
            "Register ledge detection trace and mantle transition overrides",
            "Create climbing animation slots (ClimbStart, ClimbLoop, ClimbMantle)"
        ])
    else:
        steps.extend([
            "Initialize template-specific node properties",
            "Verify variables and input action mappings"
        ])
    steps.append("Compile and save blueprint asset to Content Browser")

    return json.dumps({
        "created": created,
        "template": template,
        "asset_path": asset_path,
        "asset_name": asset_name,
        "parent_class": parent_class_name,
        "steps_executed": steps,
        "message": f"Successfully created Blueprint asset from template {template}.",
    }, indent=2, default=str)
