"""First-party Unreal Blueprint operation facade."""

from __future__ import annotations

from typing import Any


def add_component(
    blueprint_path: str,
    component_class: str,
    component_name: str,
    asset_path: str = "",
    attach_bone: str = "",
    socket_name: str = "",
    save: bool = True,
) -> dict[str, Any]:
    """
        Add Blueprint component.
    :param blueprint_path: Blueprint package path
    :param component_class: component class name to add
    :param component_name: new component instance name
    :param asset_path: optional asset assigned to the component
    :param attach_bone: optional skeletal bone attachment name
    :param socket_name: optional skeletal socket attachment name
    :param save: whether the Blueprint should be saved after mutation
    :return: command router operation contract
    """

    return {
        "operation": "blueprint.add_component",
        "execution_channel": "command_router.execute_unreal_operation",
        "params": {
            "blueprint_path": blueprint_path,
            "component_class": component_class,
            "component_name": component_name,
            "asset_path": asset_path,
            "attach_bone": attach_bone,
            "socket_name": socket_name,
            "save": save,
        },
        "implemented": True,
    }

