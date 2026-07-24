"""Niagara operation facade for first-party Unreal routing.

The live Unreal execution is currently owned by ``CommandRouter.execute_unreal_operation``.
These functions provide importable, documented contracts for operation discovery,
planning, autocomplete, and validation so the catalog does not advertise phantom
modules while the router-backed implementation remains centralized.
"""

from __future__ import annotations

from typing import Any


def _operation_contract(operation: str, **params: Any) -> dict[str, Any]:
    """
        Build operation contract.
    :param operation: operation key handled by the Unreal command router
    :param params: operation parameters
    :return: serializable operation contract
    """

    return {
        "operation": operation,
        "execution_channel": "command_router.execute_unreal_operation",
        "params": dict(params),
        "implemented": True,
    }


def create_emitter(asset_path: str, template: str = "empty", parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """
        Create Niagara emitter.
    :param asset_path: package path for the Niagara emitter or system asset
    :param template: emitter/system template name
    :param parameters: creation parameters such as target blueprint, attach bone, or requested color
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.create_emitter",
        asset_path=asset_path,
        template=template,
        parameters=dict(parameters or {}),
    )


def create_system(asset_path: str, template: str = "empty", parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """
        Create Niagara system.
    :param asset_path: package path for the Niagara system asset
    :param template: system template name
    :param parameters: creation parameters
    :return: command router operation contract
    """

    merged_parameters = dict(parameters or {})
    merged_parameters.setdefault("asset_kind", "system")
    return _operation_contract(
        "niagara.create_system",
        asset_path=asset_path,
        template=template,
        parameters=merged_parameters,
    )


def inspect_system(asset_path: str) -> dict[str, Any]:
    """
        Inspect Niagara system.
    :param asset_path: Niagara asset package path
    :return: command router operation contract
    """

    return _operation_contract("niagara.inspect_system", asset_path=asset_path)


def list_module_inputs(asset_path: str, emitter_name: str = "") -> dict[str, Any]:
    """
        List Niagara module inputs.
    :param asset_path: Niagara asset package path
    :param emitter_name: optional emitter name filter
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.list_module_inputs",
        asset_path=asset_path,
        emitter_name=emitter_name,
    )


def set_user_parameter(asset_path: str, parameter_name: str, value: Any, value_type: str = "auto") -> dict[str, Any]:
    """
        Set Niagara user parameter.
    :param asset_path: Niagara asset package path
    :param parameter_name: user parameter name
    :param value: value to apply
    :param value_type: explicit value coercion mode
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.set_user_parameter",
        asset_path=asset_path,
        parameter_name=parameter_name,
        value=value,
        value_type=value_type,
    )


def set_renderer_property(
    asset_path: str,
    property_name: str,
    value: Any,
    emitter_name: str = "",
    renderer_index: int = 0,
    value_type: str = "auto",
) -> dict[str, Any]:
    """
        Set Niagara renderer property.
    :param asset_path: Niagara asset package path
    :param property_name: renderer property name
    :param value: value to apply
    :param emitter_name: optional emitter name filter
    :param renderer_index: renderer index when multiple renderers are present
    :param value_type: explicit value coercion mode
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.set_renderer_property",
        asset_path=asset_path,
        property_name=property_name,
        value=value,
        emitter_name=emitter_name,
        renderer_index=renderer_index,
        value_type=value_type,
    )


def set_module_input(
    asset_path: str,
    module_name: str,
    input_name: str,
    value: Any,
    emitter_name: str = "",
    script_usage: str = "",
    value_type: str = "auto",
) -> dict[str, Any]:
    """
        Set Niagara module input.
    :param asset_path: Niagara asset package path
    :param module_name: module or script name
    :param input_name: input property name
    :param value: value to apply
    :param emitter_name: optional emitter name filter
    :param script_usage: optional Niagara script usage filter
    :param value_type: explicit value coercion mode
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.set_module_input",
        asset_path=asset_path,
        module_name=module_name,
        input_name=input_name,
        value=value,
        emitter_name=emitter_name,
        script_usage=script_usage,
        value_type=value_type,
    )


def add_to_level(asset_path: str, location: Any = None, attach_to_selected_actor: bool = False) -> dict[str, Any]:
    """
        Add Niagara asset to level.
    :param asset_path: Niagara asset package path
    :param location: optional spawn location
    :param attach_to_selected_actor: whether to attach to current selection
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.add_to_level",
        asset_path=asset_path,
        location=location,
        attach_to_selected_actor=attach_to_selected_actor,
    )


def compile_asset(asset_path: str) -> dict[str, Any]:
    """
        Compile Niagara asset.
    :param asset_path: Niagara asset package path
    :return: command router operation contract
    """

    return _operation_contract("niagara.compile", asset_path=asset_path)


def delete_emitter(system_path: str, emitter_name: str) -> dict[str, Any]:
    """
        Delete Niagara emitter.
    :param system_path: Niagara system package path
    :param emitter_name: emitter name to remove
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.delete_emitter",
        system_path=system_path,
        emitter_name=emitter_name,
    )


def set_emitter_property(system_path: str, emitter_name: str, property_name: str, value: Any) -> dict[str, Any]:
    """
        Set Niagara emitter property.
    :param system_path: Niagara system package path
    :param emitter_name: emitter name to edit
    :param property_name: emitter property name
    :param value: value to apply
    :return: command router operation contract
    """

    return _operation_contract(
        "niagara.set_emitter_property",
        system_path=system_path,
        emitter_name=emitter_name,
        property_name=property_name,
        value=value,
    )
