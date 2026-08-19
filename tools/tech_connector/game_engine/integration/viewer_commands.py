from __future__ import annotations

"""Public Tech Connector viewer command facade.

This module is intentionally shaped like a small, host-neutral cousin of
maya.cmds. It does not assume the target lives in the local viewer; commands are
resolved against TC-native objects, bridge-backed DCC objects, or engine/plugin
conversion targets.
"""

from typing import Any

from tech_connector.game_engine.integration.adaptive_scene_command_service import (
    SceneCommandRoute,
    SceneCommandTarget,
    list_adaptive_scene_commands,
    resolve_adaptive_scene_command,
    target_from_scene_proxy,
)


def commands() -> list[dict[str, Any]]:
    return list_adaptive_scene_commands()


def target(
    provider: str = "tech_connector",
    native_id: str = "",
    *,
    source_key: str = "",
    object_type: str = "mesh",
    component_type: str = "object",
    components: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SceneCommandTarget:
    return SceneCommandTarget(
        provider=provider,
        native_id=native_id,
        source_key=source_key,
        object_type=object_type,
        component_type=component_type,
        components=tuple(str(value) for value in (components or ())),
        metadata=dict(metadata or {}),
    )


def target_from_proxy(
    proxy: dict[str, Any],
    *,
    component_type: str = "object",
    components: list[str] | tuple[str, ...] | None = None,
) -> SceneCommandTarget:
    return target_from_scene_proxy(proxy, component_type=component_type, components=components)


def route(command: str, command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return resolve_adaptive_scene_command(command, command_target, kwargs).to_dict()


def execute_active(command: str, **kwargs: Any) -> dict[str, Any]:
    """Execute an undoable command in the currently open Scene Viewer."""
    from tech_connector.game_engine.integration.active_viewer_command_service import execute_active_viewer_command

    return execute_active_viewer_command(command, **kwargs)


def convert_to_tc(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.convert_to_tc", command_target, **kwargs)


def convert_selection_to_tc(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.convert_selection_to_tc", command_target, **kwargs)


def compose_usd(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.compose_usd", command_target, **kwargs)


def inspect_usd_composition(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.inspect_usd_composition", command_target, **kwargs)


def set_usd_variant(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.set_usd_variant", command_target, **kwargs)


def set_usd_payload(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.set_usd_payload", command_target, **kwargs)


def set_usd_override(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("scene.set_usd_override", command_target, **kwargs)


def split_edge_loop(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.split_edge_loop", command_target, **kwargs)


def bevel_edges(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.bevel_edges", command_target, **kwargs)


def extrude_faces(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.extrude_faces", command_target, **kwargs)


def delete_faces(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.delete_faces", command_target, **kwargs)


def triangulate_faces(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.triangulate_faces", command_target, **kwargs)


def merge_vertices(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.merge_vertices", command_target, **kwargs)


def bridge_edge_loops(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("modeling.bridge_edge_loops", command_target, **kwargs)


def parent_constraint(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.parent_constraint", command_target, **kwargs)


def create_joint(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_joint", command_target, **kwargs)


def create_ik_handle(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_ik_handle", command_target, **kwargs)


def create_ribbon_ik(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_ribbon_ik", command_target, **kwargs)


def create_motion_path_ik(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_motion_path_ik", command_target, **kwargs)


def create_quadruped_leg_ik(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_quadruped_leg_ik", command_target, **kwargs)


def create_mechanical_ik(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_mechanical_ik", command_target, **kwargs)


def constrain_to_mesh(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.constrain_to_mesh", command_target, **kwargs)


def constrain_to_normal(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.constrain_to_normal", command_target, **kwargs)


def create_pose_reader(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_pose_reader", command_target, **kwargs)


def create_space_switch(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("rigging.create_space_switch", command_target, **kwargs)


def bind_skin(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.bind_skin", command_target, **kwargs)


def auto_skin(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.auto_skin", command_target, **kwargs)


def paint_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.paint_weights", command_target, **kwargs)


def normalize_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.normalize_weights", command_target, **kwargs)


def prune_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.prune_weights", command_target, **kwargs)


def smooth_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.smooth_weights", command_target, **kwargs)


def mirror_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.mirror_weights", command_target, **kwargs)


def copy_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.copy_weights", command_target, **kwargs)


def transfer_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.transfer_weights", command_target, **kwargs)


def add_influence(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.add_influence", command_target, **kwargs)


def remove_influence(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.remove_influence", command_target, **kwargs)


def export_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.export_weights", command_target, **kwargs)


def import_weights(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("skinning.import_weights", command_target, **kwargs)


def set_keyframe(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("animation.set_keyframe", command_target, **kwargs)


def create_take(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("animation.create_take", command_target, **kwargs)


def add_animation_layer(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("animation.add_layer", command_target, **kwargs)


def create_cloth(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_cloth", command_target, **kwargs)


def create_fluid(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_fluid", command_target, **kwargs)


def create_volume(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_volume", command_target, **kwargs)


def create_effect(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_effect", command_target, **kwargs)


def set_effect_parameter(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.set_effect_parameter", command_target, **kwargs)


def bake_effect(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.bake_effect", command_target, **kwargs)


def renderer_stats(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.renderer_stats", command_target, **kwargs)


def configure_renderer_budget(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.configure_renderer_budget", command_target, **kwargs)


def create_deformable_surface(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_deformable_surface", command_target, **kwargs)


def apply_footprint(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.apply_footprint", command_target, **kwargs)


def apply_projectile(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.apply_projectile", command_target, **kwargs)


def create_soft_body(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_soft_body", command_target, **kwargs)


def create_reformable_dough(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_reformable_dough", command_target, **kwargs)


def create_breakable_solid(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.create_breakable_solid", command_target, **kwargs)


def fill_geometry_fluid(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.fill_geometry_fluid", command_target, **kwargs)


def add_curve_flow(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.add_curve_flow", command_target, **kwargs)


def step_simulation(command_target: SceneCommandTarget | dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return route("simulation.step", command_target, **kwargs)


__all__ = [
    "SceneCommandRoute",
    "SceneCommandTarget",
    "add_influence",
    "add_animation_layer",
    "auto_skin",
    "bevel_edges",
    "bridge_edge_loops",
    "bind_skin",
    "bake_effect",
    "commands",
    "convert_selection_to_tc",
    "convert_to_tc",
    "constrain_to_mesh",
    "constrain_to_normal",
    "create_ik_handle",
    "create_joint",
    "create_mechanical_ik",
    "create_motion_path_ik",
    "create_pose_reader",
    "create_quadruped_leg_ik",
    "create_ribbon_ik",
    "create_space_switch",
    "create_take",
    "create_cloth",
    "create_deformable_surface",
    "create_effect",
    "create_breakable_solid",
    "create_fluid",
    "create_reformable_dough",
    "create_soft_body",
    "create_volume",
    "delete_faces",
    "copy_weights",
    "export_weights",
    "execute_active",
    "extrude_faces",
    "fill_geometry_fluid",
    "import_weights",
    "mirror_weights",
    "merge_vertices",
    "normalize_weights",
    "parent_constraint",
    "paint_weights",
    "apply_footprint",
    "apply_projectile",
    "prune_weights",
    "route",
    "set_keyframe",
    "set_effect_parameter",
    "remove_influence",
    "smooth_weights",
    "split_edge_loop",
    "step_simulation",
    "add_curve_flow",
    "target",
    "target_from_proxy",
    "triangulate_faces",
    "transfer_weights",
]
