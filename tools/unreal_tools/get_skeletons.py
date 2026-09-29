import unreal


def get_all_assets_of_type(type='Skeleton', directory="/Game/"):
    """Return stable Asset Registry identities for one Unreal asset class."""
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_dict = dict()
    for data in [asset_data for asset_data in asset_registry.get_assets_by_path(directory, True)]:
        asset_name = str(data.asset_name)
        if str(data.asset_class_path.asset_name) == type:
            package_name = str(data.package_name)
            object_path = f"{package_name}.{asset_name}"
            asset_dict[object_path] = {
                "asset_name": asset_name,
                "package_name": package_name,
                "object_path": object_path,
                "class_name": str(data.asset_class_path.asset_name),
                "class_path": str(data.asset_class_path),
            }

    return asset_dict


if __name__ == "__main__":
    import json
    import sys
    asset_type = sys.argv[1] if len(sys.argv) > 1 else "Skeleton"
    unreal.AssetRegistryHelpers.get_asset_registry().search_all_assets(True)
    assets = get_all_assets_of_type(type=asset_type, directory="/Game/")
    print("HIK_ASSETS_JSON=" + json.dumps(assets))
