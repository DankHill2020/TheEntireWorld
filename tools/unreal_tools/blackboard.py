"""Blackboard schema authoring helpers for Unreal Editor."""

from __future__ import annotations

import json


SUPPORTED_KEY_TYPES = {
    "bool": "Bool",
    "class": "Class",
    "enum": "Enum",
    "float": "Float",
    "int": "Int",
    "name": "Name",
    "object": "Object",
    "rotator": "Rotator",
    "string": "String",
    "vector": "Vector",
}


def _load_blackboard(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(str(asset_path or ""))
    if asset is None or not isinstance(asset, unreal.BlackboardData):
        raise ValueError("Blackboard Data asset not found: " + str(asset_path or ""))
    return asset


def inspect_schema(asset_path):
    """
        Inspects Blackboard keys and their reflected types.
    :param asset_path: Unreal Blackboard Data content path
    :return: JSON schema inspection receipt
    """
    import unreal

    asset = _load_blackboard(unreal, asset_path)
    rows = []
    for entry in list(asset.get_editor_property("keys")):
        key_type = entry.get_editor_property("key_type")
        rows.append({
            "name": str(entry.get_editor_property("entry_name")),
            "description": str(entry.get_editor_property("entry_description")),
            "category": str(entry.get_editor_property("entry_category")),
            "instance_synced": bool(entry.get_editor_property("instance_synced")),
            "type_class": str(key_type.get_class().get_path_name()) if key_type else "",
        })
    return json.dumps({
        "ok": True,
        "status": "inspected",
        "asset_path": asset_path,
        "key_count": len(rows),
        "keys": rows,
    }, indent=2, default=str)


def set_schema(asset_path, keys, replace_existing=True, save=True):
    """
        Sets a Blackboard schema using reflected key-type subobjects.
    :param asset_path: Unreal Blackboard Data content path
    :param keys: key specification dictionaries
    :param replace_existing: whether to replace all existing keys
    :param save: whether to save the Blackboard package
    :return: JSON authoring and schema readback receipt
    """
    import unreal

    asset = _load_blackboard(unreal, asset_path)
    existing = list(asset.get_editor_property("keys"))
    rows = [] if replace_existing else existing
    names = {
        str(entry.get_editor_property("entry_name")).casefold()
        for entry in rows
    }
    for index, spec in enumerate(list(keys or [])):
        if not isinstance(spec, dict):
            raise TypeError("Blackboard keys must be dictionaries")
        name = str(spec.get("name") or "").strip()
        if not name:
            raise ValueError("Blackboard key name cannot be blank")
        if name.casefold() in names:
            raise ValueError("Duplicate Blackboard key name: " + name)
        type_name = str(spec.get("type") or "").strip().lower()
        reflected_suffix = SUPPORTED_KEY_TYPES.get(type_name)
        if reflected_suffix is None:
            raise ValueError(
                "Unsupported Blackboard key type. Expected one of: "
                + ", ".join(sorted(SUPPORTED_KEY_TYPES))
            )
        key_class = unreal.load_class(
            None,
            "/Script/AIModule.BlackboardKeyType_" + reflected_suffix,
        )
        if key_class is None:
            raise RuntimeError("Blackboard key class unavailable: " + reflected_suffix)
        key_type = unreal.new_object(
            key_class,
            outer=asset,
            name=f"TC_{name}_{index}",
        )
        entry = unreal.BlackboardEntry()
        entry.set_editor_property("entry_name", name)
        entry.set_editor_property("entry_description", str(spec.get("description") or ""))
        entry.set_editor_property("entry_category", str(spec.get("category") or "Tech Connector"))
        entry.set_editor_property("instance_synced", bool(spec.get("instance_synced", False)))
        entry.set_editor_property("key_type", key_type)
        rows.append(entry)
        names.add(name.casefold())
    if not rows:
        raise ValueError("Blackboard schema requires at least one key")
    asset.modify()
    asset.set_editor_property("keys", rows)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False)) if save else False
    inspection = json.loads(inspect_schema(asset_path))
    return json.dumps({
        "ok": bool(inspection.get("key_count") == len(rows) and (saved or not save)),
        "status": "authored_and_saved" if saved else "authored",
        "asset_path": asset_path,
        "saved": saved,
        "inspection": inspection,
    }, indent=2, default=str)
