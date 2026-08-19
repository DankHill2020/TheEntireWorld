"""Verified lifecycle operations for Unreal domain-specific editor assets."""

from __future__ import annotations

import json

from unreal_tools.assets import load_asset


DOMAIN_ASSET_TYPES = {
    "behavior_tree": ("BehaviorTree", "BehaviorTreeFactory"),
    "blackboard": ("BlackboardData", "BlackboardDataFactory"),
    "level_sequence": ("LevelSequence", "LevelSequenceFactoryNew"),
    "metasound_source": ("MetaSoundSource", "MetaSoundSourceFactory"),
    "pcg_graph": ("PCGGraph", "PCGGraphFactory"),
    "widget_blueprint": ("WidgetBlueprint", "WidgetBlueprintFactory"),
}


def _asset_parts(asset_path):
    """
    Gets the package path and asset name.

    :param asset_path: Unreal content path
    :return: package path and asset name
    """
    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("Domain asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    if not asset_name:
        raise ValueError("Domain asset name cannot be blank")
    return package_path, asset_name


def _type_classes(unreal, asset_type):
    """
    Resolves the reflected asset and factory classes for a supported type.

    :param unreal: Unreal Python module
    :param asset_type: supported Tech Connector domain asset type
    :return: reflected asset class and factory class
    """
    key = str(asset_type or "").strip().lower()
    names = DOMAIN_ASSET_TYPES.get(key)
    if names is None:
        raise ValueError(
            "Unsupported domain asset type. Expected one of: "
            + ", ".join(sorted(DOMAIN_ASSET_TYPES))
        )
    asset_class = getattr(unreal, names[0], None)
    factory_class = getattr(unreal, names[1], None)
    if asset_class is None or factory_class is None:
        raise RuntimeError(
            f"Unreal editor support is unavailable for {key}: {names[0]} / {names[1]}"
        )
    return key, asset_class, factory_class


def _factory_compatibility(unreal, asset_class, factory):
    """
    Checks that an Unreal factory supports the exact requested asset class.

    :param unreal: Unreal Python module
    :param asset_class: requested Unreal Python asset class
    :param factory: instantiated Unreal factory
    :return: compatibility flag, requested path, and supported path
    """
    requested = asset_class.static_class()
    try:
        supported = factory.get_editor_property("supported_class")
    except Exception:
        supported = None
    requested_path = str(requested.get_path_name()) if requested else ""
    supported_path = str(supported.get_path_name()) if supported else ""
    compatible = False
    if requested is not None and supported is not None:
        try:
            compatible = bool(requested.is_child_of(supported))
        except Exception:
            try:
                compatible = bool(unreal.SystemLibrary.class_is_child_of(requested, supported))
            except Exception:
                compatible = requested_path == supported_path
    return compatible, requested_path, supported_path


def inspect_domain_asset(asset_path, expected_type=""):
    """
    Inspects a supported domain asset through registry and reflected readback.

    :param asset_path: Unreal content path
    :param expected_type: optional supported Tech Connector domain asset type
    :return: JSON inspection receipt
    """
    import unreal

    asset = load_asset(unreal, asset_path)
    if asset is None:
        return json.dumps({
            "ok": False,
            "status": "asset_not_found",
            "asset_path": asset_path,
        }, indent=2)
    expected_class_path = ""
    type_match = True
    if expected_type:
        _, asset_class, _ = _type_classes(unreal, expected_type)
        expected_class_path = str(asset_class.static_class().get_path_name())
        type_match = isinstance(asset, asset_class)
    data = unreal.AssetRegistryHelpers.get_asset_registry().get_asset_by_object_path(
        asset.get_path_name()
    )
    class_path = str(asset.get_class().get_path_name())
    return json.dumps({
        "ok": bool(type_match and data),
        "status": "inspected" if type_match else "class_mismatch",
        "asset_path": asset_path,
        "object_path": str(asset.get_path_name()),
        "asset_name": str(asset.get_name()),
        "class_path": class_path,
        "expected_class_path": expected_class_path,
        "class_match": type_match,
        "registry_readback": data is not None,
    }, indent=2, default=str)


def create_domain_asset(
    asset_type,
    asset_path,
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
    Creates a supported domain asset with class, save, and registry readback.

    :param asset_type: supported Tech Connector domain asset type
    :param asset_path: destination Unreal content path
    :param overwrite: whether to delete the exact existing asset first
    :param dry_run: whether to validate without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON creation receipt
    """
    import unreal

    key, asset_class, factory_class = _type_classes(unreal, asset_type)
    package_path, asset_name = _asset_parts(asset_path)
    factory = factory_class()
    compatible, requested_class_path, supported_class_path = _factory_compatibility(
        unreal, asset_class, factory
    )
    if not compatible:
        raise RuntimeError(
            f"Unreal factory {factory_class.__name__} does not support {requested_class_path}; "
            f"it advertises {supported_class_path or 'no supported class'}. "
            "Use a domain-native builder instead of AssetTools.create_asset."
        )
    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_type": key,
            "asset_path": asset_path,
            "asset_class_path": requested_class_path,
            "factory_class_path": str(factory_class.static_class().get_path_name()),
            "factory_supported_class_path": supported_class_path,
            "factory_compatible": True,
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
        }, indent=2)
    if exists_before and not overwrite:
        inspection = json.loads(inspect_domain_asset(asset_path, key))
        if not inspection.get("ok"):
            raise ValueError("Existing asset does not match requested type: " + asset_path)
        inspection.update({"created": False, "status": "already_exists", "asset_type": key})
        return json.dumps(inspection, indent=2, default=str)
    if exists_before and overwrite and not unreal.EditorAssetLibrary.delete_asset(asset_path):
        raise RuntimeError("Could not delete exact existing asset: " + asset_path)

    created = False
    try:
        if key == "widget_blueprint" and hasattr(factory, "set_editor_property"):
            try:
                factory.set_editor_property("parent_class", unreal.UserWidget)
            except Exception:
                pass
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name,
            package_path,
            asset_class,
            factory,
        )
        created = asset is not None
        if not created:
            raise RuntimeError("Unreal factory returned no asset for: " + asset_path)
        compiled = False
        if isinstance(asset, unreal.Blueprint):
            compile_result = unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            if compile_result is False:
                raise RuntimeError("Blueprint compilation failed for: " + asset_path)
            compiled = True
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
        inspection = json.loads(inspect_domain_asset(asset_path, key))
        if not saved or not inspection.get("ok"):
            raise RuntimeError("Domain asset save/readback failed: " + asset_path)
        return json.dumps({
            "ok": True,
            "status": "created_compiled_saved" if compiled else "created_and_saved",
            "asset_type": key,
            "asset_path": asset_path,
            "created": True,
            "compiled": compiled,
            "saved": saved,
            "inspection": inspection,
            "postconditions": {
                "class_match": True,
                "registry_readback": True,
                "saved": True,
                "compiled_if_blueprint": not isinstance(asset, unreal.Blueprint) or compiled,
            },
        }, indent=2, default=str)
    except Exception:
        if created and cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        raise
