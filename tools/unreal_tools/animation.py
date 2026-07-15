"""Animation helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def find_compatible_animations(skeleton_path, directory="/Game/"):
    import unreal

    skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_path(directory, recursive=True)
    matches = []
    for data in assets:
        if str(data.asset_class_path.asset_name) != "AnimSequence":
            continue
        try:
            anim = data.get_asset()
            if getattr(anim, "skeleton", None) == skeleton:
                matches.append(str(data.object_path))
        except Exception:
            pass
    return json.dumps({"skeleton_path": skeleton_path, "animations": matches}, indent=2)


def create_or_update_animation_blueprint(skeleton_path, asset_path, template="locomotion"):
    return json.dumps({
        "created": False,
        "skeleton_path": skeleton_path,
        "asset_path": asset_path,
        "template": template,
        "message": "Animation Blueprint endpoint reached. Add template-specific AnimGraph construction here.",
    }, indent=2)
