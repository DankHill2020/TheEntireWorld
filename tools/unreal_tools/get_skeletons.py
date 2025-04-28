import unreal


def get_all_assets_of_type(type='Skeleton', directory="/Game/"):

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_dict = dict()
    for data in [asset_data for asset_data in asset_registry.get_assets_by_path(directory, True)]:
        asset_name = str(data.asset_name)
        if str(data.asset_class_path.asset_name) == type:
            asset_dict[asset_name] = dict()
            asset_dict[asset_name]['class'] = str(data.asset_class)
            asset_dict[asset_name]['class_name'] = str(data.asset_class_path.asset_name)
            asset_dict[asset_name]['class'] = str(data.asset_name)

    return asset_dict


if __name__ == "__main__":
    assets = get_all_assets_of_type(type='Skeleton', directory="/Game/")
    print(assets)
