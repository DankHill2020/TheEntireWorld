from __future__ import annotations

"""Evidence-backed maturity assessments for TC game-engine capabilities."""

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


MATURITY_LEVELS = ("contract", "reference", "interactive", "production", "qualified")


@dataclass(frozen=True)
class CapabilityEvidence:
    capability: str
    local_executor: bool = False
    deterministic_tests: tuple[str, ...] = ()
    user_entry_points: tuple[str, ...] = ()
    persistence_tests: tuple[str, ...] = ()
    transfer_readback_tests: tuple[str, ...] = ()
    native_backend: str = ""
    performance_baselines: tuple[str, ...] = ()
    recovery_tests: tuple[str, ...] = ()
    golden_scenes: tuple[str, ...] = ()
    stress_tests: tuple[str, ...] = ()
    qualified_platforms: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityMaturityAssessment:
    capability: str
    declared_status: str
    verified_maturity: str
    next_maturity: str
    satisfied_gates: tuple[str, ...] = ()
    missing_gates: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CAPABILITY_EVIDENCE: dict[str, CapabilityEvidence] = {
    "engine.audit_capability_maturity": CapabilityEvidence(
        "engine.audit_capability_maturity",
        local_executor=True,
        deterministic_tests=("test_capability_maturity_service.py",),
        user_entry_points=("python_api", "chat"),
        notes=("Reports evidence only; it never promotes capabilities automatically.",),
    ),
    "engine.audit_dcc_hosts": CapabilityEvidence(
        "engine.audit_dcc_hosts",
        local_executor=True,
        deterministic_tests=("test_dcc_capability_audit_service.py", "test_image_host_operation_profiles.py", "test_3dsmax_bridge.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        notes=("Host-specific profiles distinguish intentional scope from missing implementation and live qualification.",),
    ),
    "engine.qualify_dcc_host": CapabilityEvidence(
        "engine.qualify_dcc_host",
        local_executor=True,
        deterministic_tests=("test_dcc_host_qualification_service.py", "test_bridge_session_discovery.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_qualification_receipt_round_trips_atomically",),
        notes=("Live qualification remains host- and machine-specific; receipts never promote an untested host globally.",),
    ),
    "engine.qualify_dcc_source_parity": CapabilityEvidence(
        "engine.qualify_dcc_source_parity",
        local_executor=True,
        deterministic_tests=("test_dcc_source_parity_qualification_service.py", "test_bridge_session_discovery.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_source_parity_receipt_round_trips_atomically",),
        transfer_readback_tests=("exact-session role-aware source snapshot",),
        notes=("Material evidence is required only for hosts whose production role includes 3D look development.",),
    ),
    "engine.audit_dcc_workflows": CapabilityEvidence(
        "engine.audit_dcc_workflows",
        local_executor=True,
        deterministic_tests=("test_dcc_production_workflow_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        notes=("Every external host has a role-specific workflow with portability, restoration, and parity gates.",),
    ),
    "engine.run_dcc_workflow": CapabilityEvidence(
        "engine.run_dcc_workflow",
        local_executor=True,
        deterministic_tests=("test_dcc_production_workflow_service.py", "test_pipeline_operation_session_routing.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_dcc_scene_restoration_service.py",),
        notes=("Mutation confirmation and endpoint pinning are enforced; native-host golden readbacks remain machine-specific.",),
    ),
    "simulation.step": CapabilityEvidence(
        "simulation.step",
        local_executor=True,
        deterministic_tests=("test_tc_simulation_service.py", "test_viewer_simulation.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        notes=("The installed executor is the deterministic Python reference backend.",),
    ),
    "simulation.paint_emission_source": CapabilityEvidence(
        "simulation.paint_emission_source",
        local_executor=True,
        deterministic_tests=("test_tc_simulation_service.py",),
        user_entry_points=("viewer_brush", "python_api", "chat"),
        persistence_tests=("test_emission_source_map_round_trips_through_tcscene",),
        transfer_readback_tests=("simulation transfer manifest validation",),
        notes=("Destination manifests exist; target-engine plugin readback is not yet qualified.",),
    ),
    "procedural.erode_terrain": CapabilityEvidence(
        "procedural.erode_terrain",
        local_executor=True,
        deterministic_tests=("test_hydraulic_erosion_preserves_terrain_sediment_mass_and_exposes_flow_fields",),
        user_entry_points=("python_api", "procedural_graph"),
        transfer_readback_tests=("procedural transfer manifest validation",),
        notes=("Reference CPU graph operation; no interactive terrain editor or native job backend yet.",),
    ),
    "scene.convert_to_tc": CapabilityEvidence(
        "scene.convert_to_tc",
        local_executor=True,
        deterministic_tests=("test_tc_scene_conversion_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_federated_scene_service.py", "test_tc_scene_conversion_service.py"),
        notes=("Production qualification still requires golden-scene and target readback coverage.",),
    ),
    "scene.compose_usd": CapabilityEvidence(
        "scene.compose_usd",
        local_executor=True,
        deterministic_tests=("test_usd_composition_service.py", "test_usd_composition_command_service.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_tcscene_round_trips_usd_composition_and_source_fingerprints",),
        transfer_readback_tests=("test_live_openusd_backend_composes_layers_variants_and_overrides",),
        native_backend="Blender 5.1 / OpenUSD 25.8 isolated worker",
        recovery_tests=("test_pre_canceled_composition_never_launches_backend", "test_live_backend_rejects_a_malformed_source_layer"),
        notes=("Interactive and recovery tested; production qualification still needs performance baselines, golden stages, and stress coverage.",),
    ),
    "skinning.export_weights": CapabilityEvidence(
        "skinning.export_weights",
        local_executor=True,
        deterministic_tests=("test_skinning_tool_service.py", "test_skin_weight_file_interchange.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_tcskin_file_preserves_eight_influences_and_round_trips",),
        transfer_readback_tests=("test_tcskin_file_preserves_eight_influences_and_round_trips",),
        native_backend="TC native atomic JSON worker",
        performance_baselines=("test_tcskin_20k_vertex_eight_influence_baseline",),
        recovery_tests=("test_tcskin_rejects_corruption_wrong_topology_and_missing_influences",),
        notes=("Checksummed portable contract; native FBX/USD target readback qualification remains open.",),
    ),
    "skinning.import_weights": CapabilityEvidence(
        "skinning.import_weights",
        local_executor=True,
        deterministic_tests=("test_skinning_tool_service.py", "test_skin_weight_file_interchange.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_tcskin_file_preserves_eight_influences_and_round_trips",),
        transfer_readback_tests=("test_tcskin_remaps_influences_without_losing_normalization",),
        native_backend="TC native atomic JSON worker",
        performance_baselines=("test_tcskin_20k_vertex_eight_influence_baseline",),
        recovery_tests=("test_tcskin_rejects_corruption_wrong_topology_and_missing_influences",),
        notes=("Strict by default; partial or remapped imports require an explicit caller policy.",),
    ),
    "characters.create": CapabilityEvidence(
        "characters.create",
        local_executor=True,
        deterministic_tests=("test_character_intelligence_service.py", "test_viewer_character_intelligence.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
        notes=("Serializable TC-native profile and state; no language model is required.",),
    ),
    "characters.set_parameter": CapabilityEvidence(
        "characters.set_parameter",
        local_executor=True,
        deterministic_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
    ),
    "characters.add_rule": CapabilityEvidence(
        "characters.add_rule",
        local_executor=True,
        deterministic_tests=("test_authored_rules_objectives_and_affordances_override_model_proposals",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
        notes=("Authored deny rules remain authoritative over optional model proposals.",),
    ),
    "characters.add_objective": CapabilityEvidence(
        "characters.add_objective",
        local_executor=True,
        deterministic_tests=("test_authored_rules_objectives_and_affordances_override_model_proposals",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
    ),
    "characters.set_relationship": CapabilityEvidence(
        "characters.set_relationship",
        local_executor=True,
        deterministic_tests=("test_viewer_character_intelligence.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
    ),
    "characters.record_memory": CapabilityEvidence(
        "characters.record_memory",
        local_executor=True,
        deterministic_tests=("test_memory_merges_tracks_provenance_and_decays",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
    ),
    "characters.choose_action": CapabilityEvidence(
        "characters.choose_action",
        local_executor=True,
        deterministic_tests=(
            "test_authored_rules_objectives_and_affordances_override_model_proposals",
            "test_viewer_character_intelligence.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
        notes=("Produces an inspectable why-receipt before validated effects can mutate world state.",),
    ),
    "narrative.set_world_fact": CapabilityEvidence(
        "narrative.set_world_fact",
        local_executor=True,
        deterministic_tests=("test_viewer_character_intelligence.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
    ),
    "narrative.add_beat": CapabilityEvidence(
        "narrative.add_beat",
        local_executor=True,
        deterministic_tests=("test_narrative_beats_are_conditional_repeat_safe_and_assign_objectives",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
    ),
    "narrative.select_beat": CapabilityEvidence(
        "narrative.select_beat",
        local_executor=True,
        deterministic_tests=(
            "test_narrative_beats_are_conditional_repeat_safe_and_assign_objectives",
            "test_viewer_character_intelligence.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_character_intelligence.py",),
    ),
}

for _capability in (
    "skinning.bind_skin",
    "skinning.auto_skin",
    "skinning.paint_weights",
    "skinning.normalize_weights",
    "skinning.prune_weights",
    "skinning.smooth_weights",
    "skinning.mirror_weights",
    "skinning.copy_weights",
    "skinning.transfer_weights",
    "skinning.add_influence",
    "skinning.remove_influence",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_skinning_tool_service.py", "test_viewer_skinning_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_native_bind_and_weight_commands_mutate_rig_graph",),
        notes=("TC-native executor is interactive; native host readback and production-scale baselines remain open.",),
    )

for _capability in ("rigging.constrain_to_mesh", "rigging.constrain_to_normal"):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_surface_attachment_service.py", "test_viewer_surface_constraint_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_surface_constraint_round_trips_in_editable_rig_graph",),
        notes=("Stable barycentric attachment and local tangent-frame evaluation; deforming-source refresh is externally driven.",),
    )

CAPABILITY_EVIDENCE["rigging.create_mechanical_ik"] = CapabilityEvidence(
    "rigging.create_mechanical_ik",
    local_executor=True,
    deterministic_tests=("test_mechanical_rig_service.py", "test_viewer_mechanical_rig_command.py"),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_mechanical_graph_round_trips_and_re_evaluates",),
    notes=("Portable live graph relationships; native host transfer/readback qualification remains open.",),
)

CAPABILITY_EVIDENCE["rigging.create_quadruped_leg_ik"] = CapabilityEvidence(
    "rigging.create_quadruped_leg_ik",
    local_executor=True,
    deterministic_tests=("test_quadruped_leg_rig_service.py",),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_quadruped_leg_graph_round_trips_and_evaluates",),
    notes=("Four-joint two-stage RP IK reference implementation; native host readback and production animation stress remain open.",),
)

for _capability in (
    "rigging.parent_constraint",
    "rigging.create_joint",
    "rigging.create_ik_handle",
    "rigging.create_ribbon_ik",
    "rigging.create_motion_path_ik",
    "rigging.create_pose_reader",
    "rigging.create_space_switch",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_rigging_workspace_service.py", "test_viewer_adaptive_rigging_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("EditableRigGraph round-trip tests",),
        notes=("Shared native rigging controller is live; host transfer/readback and scale qualification remain open.",),
    )

CAPABILITY_EVIDENCE["engine.generate_mesh_lods"] = CapabilityEvidence(
    "engine.generate_mesh_lods",
    local_executor=True,
    deterministic_tests=("test_mesh_lod_service.py", "test_viewer_mesh_lod_command.py"),
    user_entry_points=("viewer", "python_api", "chat"),
    transfer_readback_tests=("test_live_blender_backend_generates_valid_glb_lod_chain",),
    native_backend="Blender 5.1 Decimate + glTF exporter isolated worker",
    performance_baselines=("test_live_blender_backend_generates_valid_glb_lod_chain",),
    recovery_tests=("test_pre_canceled_lod_generation_does_not_launch",),
    notes=("Interactive isolated compiler; production promotion still requires representative performance baselines.",),
)

for _capability in ("engine.compile_point_runtime_proxy", "engine.compile_virtualized_hard_surface"):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_runtime_geometry_compiler_service.py", "test_viewer_runtime_geometry_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("atomic runtime geometry binary package",),
        transfer_readback_tests=("test_runtime_geometry_compiler_service.py",),
        native_backend="TC NumPy deterministic runtime geometry compiler",
        performance_baselines=("test_runtime_geometry_65k_triangle_performance_baseline",),
        recovery_tests=("test_runtime_geometry_compilers_reject_bad_geometry_and_cancel",),
        notes=("Interactive reference compiler; production promotion still requires representative scale baselines.",),
    )

for _capability in (
    "procedural.create_scatter_graph",
    "procedural.generate_terrain",
    "procedural.erode_terrain",
    "procedural.generate_biome",
    "procedural.generate_spline_layout",
    "procedural.create_mesh_graph",
    "procedural.cook_graph",
    "procedural.cook_task_graph",
    "procedural.attach_to_scene",
    "procedural.build_transfer_manifest",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_procedural_generation_service.py", "test_viewer_procedural_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_task_graph_payload_round_trips_and_cooks_in_viewer", "test_procedural_workspace_round_trips_editable_graphs_and_scene_attachment"),
        transfer_readback_tests=("test_mesh_graph_attaches_and_builds_native_transfer_manifest",),
        notes=("Retained deterministic graph workspace with incremental cooks; representative world-scale and native-host readback qualification remain open.",),
    )

for _capability in (
    "scene.inspect_usd_composition",
    "scene.set_usd_variant",
    "scene.set_usd_payload",
    "scene.set_usd_override",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_usd_composition_service.py", "test_usd_composition_command_service.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_tcscene_round_trips_usd_composition_and_source_fingerprints",),
        notes=("Edits share the cancellable OpenUSD composition worker; production qualification remains tracked on scene.compose_usd.",),
    )

CAPABILITY_EVIDENCE["scene.convert_selection_to_tc"] = CapabilityEvidence(
    "scene.convert_selection_to_tc",
    local_executor=True,
    deterministic_tests=("test_tc_scene_conversion_service.py",),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_federated_scene_service.py", "test_tc_scene_conversion_service.py"),
    notes=("Selection-scoped promotion uses the same retained TC-native scene contract as full-scene conversion.",),
)

for _capability in (
    "modeling.restore_default_pose",
    "modeling.update_default_pose",
    "modeling.split_edge_loop",
    "modeling.bevel_edges",
    "modeling.extrude_faces",
    "modeling.delete_faces",
    "modeling.triangulate_faces",
    "modeling.merge_vertices",
    "modeling.bridge_edge_loops",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_tc_mesh_modeling_service.py", "test_viewer_adaptive_authoring_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        notes=("Stable topology edits preserve source mappings and participate in Viewer undo; production mesh-scale and golden-asset coverage remain open.",),
    )

for _capability in ("animation.set_keyframe", "animation.create_take", "animation.add_layer"):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_tc_animation_take_service.py", "test_viewer_adaptive_authoring_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("EditableRigGraph animation take round-trip tests",),
        notes=("Native takes, layers, and keyframes share the editable rig graph; curve-editor depth and host readback remain open.",),
    )

for _capability in (
    "simulation.create_cloth",
    "simulation.create_fluid",
    "simulation.fill_geometry_fluid",
    "simulation.create_soft_body",
    "simulation.create_reformable_dough",
    "simulation.create_breakable_solid",
    "simulation.create_volume",
    "simulation.create_effect",
    "simulation.set_effect_renderer",
    "simulation.set_effect_parameter",
    "simulation.add_effect_jiggle",
    "simulation.bake_effect",
    "simulation.renderer_stats",
    "simulation.configure_renderer_budget",
    "simulation.create_deformable_surface",
    "simulation.apply_footprint",
    "simulation.apply_projectile",
    "simulation.add_geometry_emitter",
    "simulation.add_geometry_collider",
    "simulation.add_gravity_source",
    "simulation.add_curve_flow",
    "simulation.add_temperature_source",
    "simulation.build_transfer_manifest",
    "simulation.compile_runtime_profile",
    "simulation.inspect_execution_plan",
    "simulation.create_data_channel",
    "simulation.publish_data_channel",
    "simulation.inspect_fx_profiler",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_tc_simulation_service.py", "test_tc_simulation_runtime_service.py", "test_viewer_simulation.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_emission_source_map_round_trips_through_tcscene",),
        transfer_readback_tests=("simulation transfer manifest validation",),
        notes=("Deterministic TC reference runtime with asynchronous effect baking; native GPU/backend scale qualification remains open.",),
    )

for _capability in (
    "deformation.add_jiggle", "deformation.add_secondary_motion_preset", "deformation.paint_influence"
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_engine_deformation_package.py", "test_viewer_adaptive_authoring_commands.py"),
        user_entry_points=("viewer", "viewer_brush", "python_api", "chat"),
        persistence_tests=("test_emission_source_map_round_trips_through_tcscene",),
        notes=("Editable weight maps and graph deformers are live; dense production deformation baselines remain open.",),
    )

for _capability in (
    "engine.build_runtime_geometry_plan",
    "engine.configure_runtime",
    "engine.live_update_scene",
    "engine.plan_playtest",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_engine_runtime_experience_service.py", "test_tc_live_game_sync_service.py", "test_viewer_adaptive_authoring_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_simulation.py", "test_tc_player_vertical_slice.py"),
        notes=("Runtime plans and incremental playtest receipts are executable; the Windows player package now verifies asset hashes, smoke output, and profile summaries, while external target-engine readback remains open.",),
    )

for _capability in (
    "world_ai.add_sensor",
    "world_ai.add_navigation_graph",
    "world_ai.add_smart_object",
    "world_ai.add_behavior_graph",
    "world_ai.add_dialogue_set",
    "world_ai.add_group",
    "world_ai.sense",
    "world_ai.find_path",
    "world_ai.reserve_smart_object",
    "world_ai.evaluate_behavior",
    "world_ai.choose_dialogue",
    "world_ai.tick_group",
    "world_ai.authorize_mutation",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=(
            "test_world_intelligence_runtime_service.py",
            "test_world_intelligence_command_service.py",
            "test_viewer_world_intelligence.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_crowd_steering_and_world_intelligence_round_trip_deterministically",),
        notes=("Interactive deterministic reference implementation; native scale and network qualification remain open.",),
    )

for _capability in (
    "gameplay.configure_experience",
    "gameplay.validate_experience",
    "gameplay.runtime_budget",
    "gameplay.set_visual_style",
    "gameplay.update_visual_setting",
    "gameplay.explain_visual_settings",
    "gameplay.preview_visual_plan",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_game_experience_service.py", "test_world_intelligence_command_service.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_world_intelligence.py",),
        notes=("Composable design and budgeting contract; individual gameplay modules mature independently.",),
    )


def register_capability_evidence(evidence: CapabilityEvidence) -> None:
    CAPABILITY_EVIDENCE[str(evidence.capability)] = evidence


def assess_capability(command: Any, evidence: CapabilityEvidence | None = None) -> CapabilityMaturityAssessment:
    key = str(getattr(command, "key", "") or (command.get("key") if isinstance(command, dict) else ""))
    declared = str(
        getattr(command, "tc_native_status", "")
        or (command.get("tc_native_status") if isinstance(command, dict) else "")
        or "planned"
    )
    record = evidence or CAPABILITY_EVIDENCE.get(key) or CapabilityEvidence(key)
    satisfied = ["registered_contract"]
    maturity_index = 0

    reference_ready = bool(record.local_executor and record.deterministic_tests)
    if declared == "implemented" and reference_ready:
        maturity_index = 1
        satisfied.extend(("local_executor", "deterministic_tests"))

    interactive_ready = bool(reference_ready and record.user_entry_points)
    if declared == "implemented" and interactive_ready:
        maturity_index = 2
        satisfied.append("user_entry_points")
        if record.persistence_tests:
            satisfied.append("persistence_tests")

    production_ready = bool(
        interactive_ready
        and record.native_backend
        and record.performance_baselines
        and record.recovery_tests
        and record.transfer_readback_tests
    )
    if declared == "implemented" and production_ready:
        maturity_index = 3
        satisfied.extend(("native_backend", "performance_baselines", "recovery_tests", "transfer_readback_tests"))

    qualified_ready = bool(
        production_ready
        and record.golden_scenes
        and record.stress_tests
        and len(record.qualified_platforms) >= 2
    )
    if declared == "implemented" and qualified_ready:
        maturity_index = 4
        satisfied.extend(("golden_scenes", "stress_tests", "multi_platform_qualification"))

    next_index = min(len(MATURITY_LEVELS) - 1, maturity_index + 1)
    next_maturity = "" if maturity_index == len(MATURITY_LEVELS) - 1 else MATURITY_LEVELS[next_index]
    requirements = {
        "reference": ("local_executor", "deterministic_tests"),
        "interactive": ("user_entry_points",),
        "production": ("native_backend", "performance_baselines", "recovery_tests", "transfer_readback_tests"),
        "qualified": ("golden_scenes", "stress_tests", "multi_platform_qualification"),
    }
    missing: list[str] = []
    if next_maturity:
        for gate in requirements[next_maturity]:
            present = (
                len(record.qualified_platforms) >= 2
                if gate == "multi_platform_qualification"
                else bool(getattr(record, gate, ()))
            )
            if not present:
                missing.append(gate)
    if declared != "implemented" and maturity_index == 0:
        missing.insert(0, "implemented_executor")
    return CapabilityMaturityAssessment(
        capability=key,
        declared_status=declared,
        verified_maturity=MATURITY_LEVELS[maturity_index],
        next_maturity=next_maturity,
        satisfied_gates=tuple(dict.fromkeys(satisfied)),
        missing_gates=tuple(dict.fromkeys(missing)),
        evidence=record.to_dict(),
    )


def audit_capability_maturity(commands: Iterable[Any]) -> dict[str, Any]:
    assessments = [assess_capability(command).to_dict() for command in commands]
    counts = {
        level: sum(row["verified_maturity"] == level for row in assessments)
        for level in MATURITY_LEVELS
    }
    declared_implemented = sum(row["declared_status"] == "implemented" for row in assessments)
    production_ready = counts["production"] + counts["qualified"]
    return {
        "schema": "tech_connector.capability_maturity_audit.v1",
        "maturity_order": list(MATURITY_LEVELS),
        "counts": counts,
        "declared_implemented": declared_implemented,
        "production_ready": production_ready,
        "declaration_gap": max(0, declared_implemented - production_ready),
        "capabilities": assessments,
    }
