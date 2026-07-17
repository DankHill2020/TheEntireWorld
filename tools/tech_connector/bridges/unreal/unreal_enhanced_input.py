"""Verified UE 5.8 Enhanced Input asset operations.

These functions run on Unreal's main Python thread through the HTTP bridge. Each
mutation is idempotent and checks the authored asset state before reporting
success.
"""

from __future__ import annotations


def _asset_path(value):
    path = str(value or "").strip().split(".", 1)[0].rstrip("/")
    if not path.startswith("/Game/") or "/" not in path[6:]:
        raise ValueError("Expected a /Game/... asset path, got: " + str(value))
    return path


def _object_path(value):
    try:
        return str(value.get_path_name()).split(".", 1)[0]
    except Exception:
        return str(value)


def _value_type(unreal, value):
    key = str(value or "boolean").strip().lower().replace("_", "")
    aliases = {
        "bool": "BOOLEAN",
        "boolean": "BOOLEAN",
        "axis1d": "AXIS1D",
        "float": "AXIS1D",
        "axis2d": "AXIS2D",
        "vector2d": "AXIS2D",
        "axis3d": "AXIS3D",
        "vector": "AXIS3D",
    }
    enum_name = aliases.get(key)
    if not enum_name:
        raise ValueError("Unsupported InputAction value type: " + str(value))
    return getattr(unreal.InputActionValueType, enum_name)


def _key(unreal, key_name):
    value = unreal.Key()
    value.set_editor_property("key_name", str(key_name or "").strip())
    if not value.export_text():
        raise ValueError("Unreal did not recognize input key: " + str(key_name))
    return value


def _mapping_rows(mapping_context):
    """Return authored mappings; UE 5.8 stores these in default_key_mappings."""

    try:
        data = mapping_context.get_editor_property("default_key_mappings")
        rows = data.get_editor_property("mappings")
        if rows is not None:
            return list(rows)
    except Exception:
        pass
    try:
        return list(mapping_context.get_editor_property("mappings") or [])
    except Exception:
        return []


def _mapping_identity(mapping):
    action = mapping.get_editor_property("action")
    key = mapping.get_editor_property("key")
    return _object_path(action), str(key.export_text())


def create_input_action(asset_path, value_type="boolean", description="", save=True, dry_run=False):
    """Create or validate an Enhanced Input Action asset."""

    import unreal

    path = _asset_path(asset_path)
    package_path, asset_name = path.rsplit("/", 1)
    expected_type = _value_type(unreal, value_type)
    existing = unreal.EditorAssetLibrary.load_asset(path)
    if existing and not isinstance(existing, unreal.InputAction):
        raise TypeError(path + " exists but is not an InputAction")
    if dry_run:
        return {
            "ok": True,
            "operation": "input.create_action",
            "asset_path": path,
            "would_create": existing is None,
            "value_type": str(expected_type),
            "verified": True,
        }

    created = False
    action = existing
    try:
        if action is None:
            factory = unreal.InputAction_Factory()
            action = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                asset_name, package_path, unreal.InputAction, factory
            )
            created = True
        if action is None:
            raise RuntimeError("Unreal failed to create InputAction: " + path)
        action.set_editor_property("value_type", expected_type)
        if description:
            action.set_editor_property("action_description", str(description))
        if save and not unreal.EditorAssetLibrary.save_loaded_asset(action, False):
            raise RuntimeError("Unreal failed to save InputAction: " + path)
        verified = unreal.EditorAssetLibrary.load_asset(path)
        if not verified or not isinstance(verified, unreal.InputAction):
            raise RuntimeError("InputAction postcondition failed: " + path)
        actual_type = verified.get_editor_property("value_type")
        if actual_type != expected_type:
            raise RuntimeError("InputAction value type postcondition failed: " + str(actual_type))
        return {
            "ok": True,
            "operation": "input.create_action",
            "asset_path": path,
            "created": created,
            "value_type": str(actual_type),
            "saved": bool(save),
            "verified": True,
        }
    except Exception:
        if created and unreal.EditorAssetLibrary.does_asset_exist(path):
            unreal.EditorAssetLibrary.delete_asset(path)
        raise


def add_mapping(mapping_context_path, action_path, key_name, save=True, dry_run=False):
    """Idempotently map one key to an InputAction in an InputMappingContext."""

    import unreal

    context_path = _asset_path(mapping_context_path)
    input_action_path = _asset_path(action_path)
    context = unreal.EditorAssetLibrary.load_asset(context_path)
    action = unreal.EditorAssetLibrary.load_asset(input_action_path)
    if not isinstance(context, unreal.InputMappingContext):
        raise TypeError(context_path + " is not an InputMappingContext")
    if not isinstance(action, unreal.InputAction):
        raise TypeError(input_action_path + " is not an InputAction")
    key = _key(unreal, key_name)
    identity = (_object_path(action), str(key.export_text()))
    before = {_mapping_identity(row) for row in _mapping_rows(context)}
    if dry_run:
        return {
            "ok": True,
            "operation": "input.add_mapping",
            "mapping_context_path": context_path,
            "action_path": input_action_path,
            "key": identity[1],
            "would_add": identity not in before,
            "verified": True,
        }
    if identity in before:
        return {
            "ok": True,
            "operation": "input.add_mapping",
            "mapping_context_path": context_path,
            "action_path": input_action_path,
            "key": identity[1],
            "created": False,
            "saved": False,
            "verified": True,
        }

    context.modify()
    context.map_key(action, key)
    after = {_mapping_identity(row) for row in _mapping_rows(context)}
    if identity not in after:
        try:
            context.unmap_key(action, key)
        except Exception:
            pass
        raise RuntimeError("Input mapping postcondition failed for " + repr(identity))
    if save and not unreal.EditorAssetLibrary.save_loaded_asset(context, False):
        context.unmap_key(action, key)
        raise RuntimeError("Unreal failed to save InputMappingContext: " + context_path)
    return {
        "ok": True,
        "operation": "input.add_mapping",
        "mapping_context_path": context_path,
        "action_path": input_action_path,
        "key": identity[1],
        "created": True,
        "saved": bool(save),
        "verified": True,
        "mapping_count": len(after),
    }
