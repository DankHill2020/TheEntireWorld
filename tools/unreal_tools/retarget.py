"""IK Retargeter helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def _load(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Retarget asset not found: {asset_path}")
    return asset


def _split_path(asset_path, default_name):
    package = str(asset_path or "").split(".", 1)[0].rstrip("/")
    if not package:
        package = f"/Game/AIStudio/Retarget/{default_name}"
    folder, _, name = package.rpartition("/")
    if not folder or not name:
        raise ValueError(f"Invalid Unreal asset path: {asset_path!r}")
    return folder, name, package


def _save(unreal, asset):
    return bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))


def _set_struct_property(value, property_name, property_value):
    setter = getattr(value, "set_editor_property", None)
    if callable(setter):
        setter(str(property_name), property_value)
    else:
        setattr(value, str(property_name), property_value)
    return value


def inspect(retargeter_path):
    import unreal

    asset = _load(unreal, retargeter_path)
    fields = {}
    for name in ("source_ik_rig_asset", "target_ik_rig_asset", "current_retarget_profile"):
        try:
            value = asset.get_editor_property(name)
            fields[name] = value.get_path_name() if hasattr(value, "get_path_name") else value
        except Exception:
            pass
    return _result(ok=True, retargeter_path=retargeter_path, class_name=asset.get_class().get_name(), fields=fields)


def create_ik_rig(skeletal_mesh_path, save_path=""):
    import unreal

    mesh = _load(unreal, skeletal_mesh_path)
    folder, name, package = _split_path(save_path, f"IK_{mesh.get_name()}")
    rig = unreal.EditorAssetLibrary.load_asset(package)
    created = rig is None
    if created:
        rig = unreal.IKRigDefinitionFactory().create_new_ik_rig_asset(folder, name)
    if rig is None:
        return _result(ok=False, status="create_failed", save_path=package)
    controller = unreal.IKRigController.get_controller(rig)
    mesh_assigned = bool(controller.set_skeletal_mesh(mesh))
    saved = _save(unreal, rig)
    readback_mesh = controller.get_skeletal_mesh()
    return _result(
        ok=bool(saved and readback_mesh == mesh),
        status="created" if created else "reused",
        ik_rig_path=rig.get_path_name(),
        skeletal_mesh_path=mesh.get_path_name(),
        skeletal_mesh_assigned=mesh_assigned,
        readback_skeletal_mesh=(
            readback_mesh.get_path_name() if readback_mesh else ""
        ),
        saved=saved,
    )


def add_ik_chain(ik_rig_path, chain_name, start_bone, end_bone):
    import unreal

    rig = _load(unreal, ik_rig_path)
    controller = unreal.IKRigController.get_controller(rig)
    existing = {
        str(chain.chain_name): chain
        for chain in controller.get_retarget_chains() or []
    }
    created_name = (
        str(chain_name)
        if str(chain_name) in existing
        else str(
            controller.add_retarget_chain(
                str(chain_name),
                str(start_bone),
                str(end_bone),
                "",
            )
        )
    )
    chains = {
        str(chain.chain_name): {
            "start_bone": str(chain.start_bone),
            "end_bone": str(chain.end_bone),
        }
        for chain in controller.get_retarget_chains() or []
    }
    saved = _save(unreal, rig)
    row = chains.get(str(chain_name), {})
    return _result(
        ok=bool(
            saved
            and row.get("start_bone") == str(start_bone)
            and row.get("end_bone") == str(end_bone)
        ),
        ik_rig_path=rig.get_path_name(),
        chain_name=created_name,
        chains=chains,
        saved=saved,
    )


def create_ik_retargeter(source_ik_rig_path, target_ik_rig_path, save_path=""):
    import unreal

    source = _load(unreal, source_ik_rig_path)
    target = _load(unreal, target_ik_rig_path)
    folder, name, package = _split_path(save_path, "RTG_AIStudio")
    asset = unreal.EditorAssetLibrary.load_asset(package)
    created = asset is None
    if created:
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name,
            folder,
            unreal.IKRetargeter,
            unreal.IKRetargetFactory(),
        )
    if asset is None:
        return _result(ok=False, status="create_failed", save_path=package)
    controller = unreal.IKRetargeterController.get_controller(asset)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.SOURCE, source)
    controller.set_ik_rig(unreal.RetargetSourceOrTarget.TARGET, target)
    saved = _save(unreal, asset)
    source_readback = controller.get_ik_rig(
        unreal.RetargetSourceOrTarget.SOURCE
    )
    target_readback = controller.get_ik_rig(
        unreal.RetargetSourceOrTarget.TARGET
    )
    return _result(
        ok=bool(saved and source_readback == source and target_readback == target),
        status="created" if created else "reused",
        retargeter_path=asset.get_path_name(),
        source_ik_rig_path=source_readback.get_path_name(),
        target_ik_rig_path=target_readback.get_path_name(),
        saved=saved,
    )


def set_chain_mapping(retargeter_path, source_chain, target_chain):
    import unreal

    asset = _load(unreal, retargeter_path)
    controller = unreal.IKRetargeterController.get_controller(asset)
    changed = bool(
        controller.set_source_chain(
            str(source_chain),
            str(target_chain),
        )
    )
    saved = _save(unreal, asset)
    readback = str(controller.get_source_chain(str(target_chain)))
    return _result(
        ok=bool(saved and readback == str(source_chain)),
        retargeter_path=asset.get_path_name(),
        source_chain=source_chain,
        target_chain=target_chain,
        changed=changed,
        readback_source_chain=readback,
        saved=saved,
    )


def set_root_settings(retargeter_path, blend_height=1.0, scale_factor=1.0):
    import unreal

    asset = _load(unreal, retargeter_path)
    controller = unreal.IKRetargeterController.get_controller(asset)
    settings = controller.get_root_settings()
    applied = {}
    for name, value in (
        ("blend_to_source", float(blend_height)),
        ("scale_horizontal", float(scale_factor)),
        ("scale_vertical", float(scale_factor)),
    ):
        try:
            _set_struct_property(settings, name, value)
            applied[name] = value
        except Exception:
            continue
    if not applied:
        raise RuntimeError("No writable UE 5.8 root settings were found")
    controller.set_root_settings(settings)
    saved = _save(unreal, asset)
    readback = controller.get_root_settings()
    values = {}
    for name in applied:
        try:
            values[name] = readback.get_editor_property(name)
        except Exception:
            values[name] = getattr(readback, name, None)
    return _result(
        ok=bool(saved and all(values.get(k) == v for k, v in applied.items())),
        retargeter_path=asset.get_path_name(),
        applied=applied,
        readback=values,
        saved=saved,
    )


def set_profile_property(retargeter_path, profile_name, property_name, value):
    import unreal

    asset = _load(unreal, retargeter_path)
    controller = unreal.IKRetargeterController.get_controller(asset)
    profile = str(profile_name or "").strip()
    if profile.lower() == "root":
        settings = controller.get_root_settings()
        _set_struct_property(settings, property_name, value)
        controller.set_root_settings(settings)
        readback_struct = controller.get_root_settings()
    elif profile.lower() == "global":
        settings = controller.get_global_settings()
        _set_struct_property(settings, property_name, value)
        controller.set_global_settings(settings)
        readback_struct = controller.get_global_settings()
    else:
        settings = controller.get_retarget_chain_settings(profile)
        _set_struct_property(settings, property_name, value)
        if not controller.set_retarget_chain_settings(profile, settings):
            raise RuntimeError(f"Could not update retarget chain settings: {profile}")
        readback_struct = controller.get_retarget_chain_settings(profile)
    try:
        readback = readback_struct.get_editor_property(str(property_name))
    except Exception:
        readback = getattr(readback_struct, str(property_name), None)
    saved = _save(unreal, asset)
    return _result(
        ok=bool(saved and readback == value),
        retargeter_path=asset.get_path_name(),
        profile_name=profile,
        property_name=property_name,
        value=value,
        readback=readback,
        saved=saved,
    )
