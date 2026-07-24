"""Niagara helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json


def _result(**payload):
    return json.dumps(payload, indent=2, default=str)


def _load(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Niagara asset not found: {asset_path}")
    return asset


def _bridge(unreal):
    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if not bridge:
        raise RuntimeError("AIStudioBridgeLibrary is unavailable; install/enable AIStudioBridge and restart Unreal.")
    return bridge


def _compact_value(value, depth=0):
    if depth >= 4:
        return str(value)[:160]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, depth + 1)
            for key, item in list(value.items())[:16]
            if key != "exported_json"
        }
    if isinstance(value, list):
        return [_compact_value(item, depth + 1) for item in value[:16]]
    if isinstance(value, str) and len(value) > 240:
        return value[:237] + "..."
    return value


def _short_type_name(value):
    text = str(value or "")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.strip("'\"")


def _display_niagara_value(value):
    if not isinstance(value, dict):
        return _compact_value(value)
    for key in (
        "value",
        "enumEntryName",
        "dynamicInputAsset",
        "objectPath",
        "assetPath",
    ):
        candidate = value.get(key)
        if candidate is not None and not isinstance(candidate, (dict, list)):
            return _compact_value(candidate)
    return {
        str(key): _compact_value(item, 2)
        for key, item in list(value.items())[:6]
    }


def _value_type(value, value_type):
    if str(value_type or "auto").lower() != "auto":
        return str(value_type).lower()
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, (list, tuple)) and len(value) in {3, 4}:
        return "vector" if len(value) == 3 else "color"
    return "float"


def _split_package_asset_path(asset_path):
    normalized = str(asset_path or "").strip().replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/Game/" + normalized.lstrip("/")
    normalized = normalized.rsplit(".", 1)[0]
    package_path, _, asset_name = normalized.rpartition("/")
    if not package_path or not asset_name:
        raise ValueError(f"Expected Unreal package path like /Game/FX/NE_Name, got: {asset_path}")
    return package_path, asset_name, package_path + "/" + asset_name


def _readback_asset(unreal, asset_path):
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        return {"exists": False, "asset_path": asset_path}
    row = {
        "exists": True,
        "asset_path": asset_path,
        "name": asset.get_name(),
        "class": asset.get_class().get_name(),
        "properties": [],
    }
    for prop in ("exposed_parameters", "fixed_bounds", "warmup_time", "warmup_tick_count"):
        try:
            value = asset.get_editor_property(prop)
            row["properties"].append({"name": prop, "value": str(value)})
        except Exception:
            pass
    return row


def _set_requested_properties(asset, parameters):
    applied = []
    rejected = []
    for name, value in (parameters or {}).items():
        try:
            asset.set_editor_property(str(name), value)
            applied.append(str(name))
        except Exception as exc:
            rejected.append({"name": str(name), "error": str(exc)})
    return applied, rejected


def inspect_system(asset_path):
    import unreal

    asset = _load(unreal, asset_path)
    rows = {
        "asset_path": asset_path,
        "name": asset.get_name(),
        "class": asset.get_class().get_name(),
        "properties": [],
    }
    for name in ("exposed_parameters", "fixed_bounds", "warmup_time", "warmup_tick_count"):
        try:
            rows["properties"].append({"name": name, "value": asset.get_editor_property(name)})
        except Exception:
            pass
    return _result(ok=True, **rows)


def list_module_inputs(
    asset_path: str,
    emitter_name: str = "",
    include_topology: bool = False,
) -> str:
    import unreal

    raw = _bridge(unreal).list_niagara_module_inputs(
        asset_path,
        unreal.Name(str(emitter_name)) if emitter_name else unreal.Name(),
    )
    if include_topology:
        return raw
    result = json.loads(raw)
    emitters = []
    for emitter in result.get("emitters") or []:
        topology = {}
        try:
            topology = json.loads(emitter.get("topology_json") or "{}")
        except (TypeError, ValueError):
            pass
        modules = []
        for module in emitter.get("input_values") or []:
            inputs = []
            for input_row in module.get("inputs") or []:
                wrapped_value = input_row.get("value") or {}
                inputs.append(
                    {
                        "name": input_row.get("name"),
                        "type": _short_type_name(wrapped_value.get("type")),
                        "value": _display_niagara_value(wrapped_value.get("value")),
                    }
                )
            modules.append(
                {
                    "module_name": module.get("moduleName"),
                    "input_count": len(inputs),
                    "inputs": inputs,
                }
            )
        emitters.append(
            {
                "emitter_name": emitter.get("emitter_name"),
                "enabled": topology.get("bEnabled"),
                "simulation_target": topology.get("simTarget"),
                "renderer_classes": list(topology.get("rendererClasses") or []),
                "modules": modules,
                "module_count": len(modules),
            }
        )
    return _result(
        ok=bool(result.get("ok")),
        status=result.get("status"),
        errors=list(result.get("errors") or []),
        emitter_count=len(emitters),
        emitters=emitters,
        full_topology_available=True,
    )


def create_emitter(asset_path, template="empty", parameters=None):
    import unreal

    package_path, asset_name, normalized_path = _split_package_asset_path(asset_path)
    parameters = parameters or {}
    if isinstance(parameters, str):
        parameters = json.loads(parameters or "{}")
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dict or JSON object string")

    existing = unreal.EditorAssetLibrary.load_asset(normalized_path)
    if existing:
        return _result(
            ok=False,
            status="asset_already_exists",
            asset_path=normalized_path,
            readback=_readback_asset(unreal, normalized_path),
        )

    template_asset = None
    if isinstance(template, str) and template.startswith(("/Game/", "/Engine/", "/Plugin/")):
        template_asset = unreal.EditorAssetLibrary.load_asset(template)
        if not template_asset:
            return _result(ok=False, status="template_not_found", asset_path=normalized_path, template=template)
        asset = unreal.EditorAssetLibrary.duplicate_asset(template, normalized_path)
        creation_strategy = "duplicate_template_asset"
    else:
        factory_cls = getattr(unreal, "NiagaraEmitterFactoryNew", None)
        emitter_cls = getattr(unreal, "NiagaraEmitter", None)
        if not factory_cls or not emitter_cls:
            return _result(
                ok=False,
                status="api_unavailable",
                asset_path=normalized_path,
                missing=[
                    name
                    for name, value in (
                        ("NiagaraEmitterFactoryNew", factory_cls),
                        ("NiagaraEmitter", emitter_cls),
                    )
                    if not value
                ],
            )
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = factory_cls()
        for prop, value in (
            ("create_new", True),
            ("edit_after_new", False),
        ):
            try:
                factory.set_editor_property(prop, value)
            except Exception:
                pass
        asset = asset_tools.create_asset(asset_name, package_path, emitter_cls, factory)
        creation_strategy = "niagara_emitter_factory_new"

    if not asset:
        return _result(ok=False, status="create_asset_failed", asset_path=normalized_path, template=template)

    applied, rejected = _set_requested_properties(asset, parameters)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
    readback = _readback_asset(unreal, normalized_path)
    return _result(
        ok=bool(saved and readback.get("exists")),
        status="created" if saved and readback.get("exists") else "created_but_save_or_readback_failed",
        asset_path=normalized_path,
        template=template,
        template_asset=template_asset.get_path_name() if template_asset else "",
        strategy=creation_strategy,
        parameters_applied=applied,
        parameters_rejected=rejected,
        saved=saved,
        readback=readback,
    )


def set_user_parameter(
    asset_path: str,
    parameter_name: str,
    value,
    value_type: str = "auto",
) -> str:
    import unreal

    return _bridge(unreal).set_niagara_user_parameter(
        asset_path,
        unreal.Name(str(parameter_name)),
        json.dumps(value),
        _value_type(value, value_type),
    )


def set_renderer_property(
    asset_path: str,
    property_name: str,
    value,
    emitter_name: str = "",
    renderer_index: int = 0,
    value_type: str = "auto",
) -> str:
    import unreal

    if not emitter_name:
        raise ValueError("emitter_name is required for renderer mutation")
    return _bridge(unreal).set_niagara_renderer_property(
        asset_path,
        unreal.Name(str(emitter_name)),
        int(renderer_index),
        unreal.Name(str(property_name)),
        json.dumps(value),
    )


def set_module_input(
    asset_path: str,
    module_name: str,
    input_name: str,
    value,
    emitter_name: str = "",
    script_usage: str = "",
    value_type: str = "auto",
) -> str:
    import unreal

    if not emitter_name or not script_usage:
        raise ValueError("emitter_name and script_usage are required for unambiguous Niagara module mutation")
    return _bridge(unreal).set_niagara_module_input(
        asset_path,
        unreal.Name(str(emitter_name)),
        unreal.Name(str(script_usage)),
        unreal.Name(str(module_name)),
        unreal.Name(str(input_name)),
        json.dumps(value),
    )


def add_to_level(asset_path, location=None, attach_to_selected_actor=False):
    import unreal

    system = _load(unreal, asset_path)
    location = location or [0.0, 0.0, 0.0]
    cls = getattr(unreal, "NiagaraActor", None)
    if not cls:
        return _result(ok=False, status="api_unavailable", api="NiagaraActor", asset_path=asset_path)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, unreal.Vector(float(location[0]), float(location[1]), float(location[2])))
    if not actor:
        return _result(ok=False, error="spawn_failed", asset_path=asset_path)
    try:
        comp = actor.get_component_by_class(unreal.NiagaraComponent)
        if comp:
            comp.set_asset(system)
    except Exception:
        pass
    return _result(ok=True, asset_path=asset_path, actor_path=actor.get_path_name(), location=location, attach_to_selected_actor=bool(attach_to_selected_actor))


def attach_editable_character_fx(
    blueprint_path,
    source_system_path="/Game/Variant_Platforming/VFX/NS_Jump_Trail",
    system_path="/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CharacterAura",
    component_name="AIStudio_AuraFX",
    socket_name="spine_03",
    parameters=None,
    extra_components=None,
    native_binding_chunk_size=2,
    disable_native_graph_binding=False,
    save=True,
):
    return _result(
        ok=True,
        execution_channel="command_router.execute_unreal_operation",
        operation="niagara.attach_editable_character_fx",
        blueprint_path=blueprint_path,
        source_system_path=source_system_path,
        system_path=system_path,
        component_name=component_name,
        socket_name=socket_name,
        parameters=parameters or {},
        extra_components=extra_components or [],
        native_binding_chunk_size=int(native_binding_chunk_size or 2),
        disable_native_graph_binding=bool(disable_native_graph_binding),
        save=bool(save),
    )


def delete_emitter(system_path: str, emitter_name: str) -> str:
    import unreal

    return _bridge(unreal).remove_niagara_emitter(system_path, unreal.Name(str(emitter_name)))


def set_emitter_property(
    system_path: str,
    emitter_name: str,
    property_name: str,
    value,
) -> str:
    import unreal

    return _bridge(unreal).set_niagara_emitter_property(
        system_path,
        unreal.Name(str(emitter_name)),
        unreal.Name(str(property_name)),
        json.dumps(value),
    )
