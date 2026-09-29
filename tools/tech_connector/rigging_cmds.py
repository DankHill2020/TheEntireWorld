"""Public DCC-neutral rigging API used by UI, chat, pipelines, and scripts."""

from __future__ import annotations

from typing import Any

from tech_connector.game_engine.integration.rigging_host_adapter_service import create_rigging_adapter
from tech_connector.game_engine.authoring.rigging_workspace_service import RiggingWorkspaceController, list_rigging_capabilities


def session(host: str = "tech_connector", *, graph=None, embedded: bool = False, selected_ids=None) -> RiggingWorkspaceController:
    return RiggingWorkspaceController(create_rigging_adapter(host, graph=graph, embedded=embedded, selected_ids=selected_ids))


def capabilities(host: str = "", *, graph=None, embedded: bool = False) -> list[dict[str, Any]] | dict[str, str]:
    if not host:
        return list_rigging_capabilities()
    return session(host, graph=graph, embedded=embedded).capability_status()


def run(controller: RiggingWorkspaceController, capability: str, **payload: Any) -> dict[str, Any]:
    return controller.run(capability, **payload).to_dict()


def auto_map(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "definition.auto_map", **payload)


def validate_definition(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "definition.validate", **payload)


def capture_reference_pose(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "definition.set_reference_pose", **payload)


def build_rig(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.build_full", **payload)


def build_module(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.build_module", **payload)


def remove_module(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.remove_module", **payload)


def rebuild_module(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.rebuild_module", **payload)


def create_control(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_control", **payload)


def create_constraint(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_constraint", **payload)


def create_ik_fk_limb(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_ik_fk_limb", **payload)


def create_reverse_foot(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_reverse_foot", **payload)


def create_ribbon(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_ribbon", **payload)


def create_curve_joints(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_curve_joints", **payload)


def create_twist(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_twist", **payload)


def create_space_switch(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.create_space_switch", **payload)


def set_space(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "rig.set_space", **payload)


def solve_retarget_pose(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "retarget.solve_pose", **payload)


def bake_retarget(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "retarget.bake", **payload)


def transfer_take(controller: RiggingWorkspaceController, **payload: Any) -> dict[str, Any]:
    return run(controller, "retarget.transfer_take", **payload)


__all__ = [
    "auto_map", "bake_retarget", "build_module", "build_rig", "capabilities",
    "capture_reference_pose", "create_constraint", "create_control", "create_curve_joints", "create_ik_fk_limb",
    "create_reverse_foot", "create_ribbon", "create_space_switch", "create_twist",
    "rebuild_module", "remove_module", "run", "session", "set_space",
    "solve_retarget_pose", "transfer_take", "validate_definition",
]

