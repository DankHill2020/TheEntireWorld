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
        transfer_readback_tests=("test_command_catalog_and_audit_expose_verified_maturity",),
        native_backend="TC-native fail-closed capability evidence auditor",
        performance_baselines=("302-test source-bound capability qualification completed within the 300-second budget",),
        recovery_tests=("test_missing_evidence_stays_at_contract_maturity",),
        notes=("Reports evidence only, fails closed on missing evidence, and never promotes capabilities automatically.",),
    ),
    "engine.audit_dcc_hosts": CapabilityEvidence(
        "engine.audit_dcc_hosts",
        local_executor=True,
        deterministic_tests=("test_dcc_capability_audit_service.py", "test_image_host_operation_profiles.py", "test_3dsmax_bridge.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        transfer_readback_tests=("test_dcc_capability_audit_service.py",),
        native_backend="TC-native role-aware DCC capability auditor",
        performance_baselines=("bounded ten-host release audit",),
        recovery_tests=("missing and partial host capabilities remain fail-closed",),
        notes=("Host-specific profiles distinguish intentional scope from missing implementation and live qualification.",),
    ),
    "engine.qualify_dcc_host": CapabilityEvidence(
        "engine.qualify_dcc_host",
        local_executor=True,
        deterministic_tests=("test_dcc_host_qualification_service.py", "test_bridge_session_discovery.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_qualification_receipt_round_trips_atomically",),
        transfer_readback_tests=("test_qualification_receipt_round_trips_atomically",),
        native_backend="TC-native pinned-session DCC host qualification runner",
        performance_baselines=("bounded role-specific host qualification plan",),
        recovery_tests=("test_dcc_host_qualification_service.py",),
        notes=("Live qualification remains host- and machine-specific; receipts never promote an untested host globally.",),
    ),
    "engine.qualify_dcc_source_parity": CapabilityEvidence(
        "engine.qualify_dcc_source_parity",
        local_executor=True,
        deterministic_tests=("test_dcc_source_parity_qualification_service.py", "test_bridge_session_discovery.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_source_parity_receipt_round_trips_atomically",),
        transfer_readback_tests=("exact-session role-aware source snapshot",),
        native_backend="TC-native exact-session source parity qualification runner",
        performance_baselines=("bounded role-aware source snapshot qualification",),
        recovery_tests=("test_dcc_source_parity_qualification_service.py",),
        notes=("Material evidence is required only for hosts whose production role includes 3D look development.",),
    ),
    "engine.audit_dcc_workflows": CapabilityEvidence(
        "engine.audit_dcc_workflows",
        local_executor=True,
        deterministic_tests=("test_dcc_production_workflow_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        transfer_readback_tests=("test_dcc_production_workflow_service.py",),
        native_backend="TC-native role-specific workflow contract auditor",
        performance_baselines=("bounded ten-host workflow audit",),
        recovery_tests=("missing workflow receipts remain fail-closed",),
        notes=("Every external host has a role-specific workflow with portability, restoration, and parity gates.",),
    ),
    "engine.run_dcc_workflow": CapabilityEvidence(
        "engine.run_dcc_workflow",
        local_executor=True,
        deterministic_tests=("test_dcc_production_workflow_service.py", "test_pipeline_operation_session_routing.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_dcc_scene_restoration_service.py",),
        transfer_readback_tests=("test_pipeline_operation_session_routing.py",),
        native_backend="TC-native endpoint-pinned DCC workflow executor",
        performance_baselines=("bounded synthetic multi-step workflow execution",),
        recovery_tests=("test_dcc_production_workflow_service.py", "test_pipeline_operation_session_routing.py"),
        notes=("Mutation confirmation and endpoint pinning are enforced; native-host golden readbacks remain machine-specific.",),
    ),
    "simulation.step": CapabilityEvidence(
        "simulation.step",
        local_executor=True,
        deterministic_tests=("test_character_dynamics_cloth.py", "test_native_simulation_backend.py", "test_engine_runtime_foundation.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("deterministic runtime cache capture", "rollback checkpoint replay"),
        transfer_readback_tests=("simulation transfer manifest validation",),
        native_backend="Persistent NumPy SoA native CPU plus capability-gated GPU array providers",
        performance_baselines=("20k native particle bounded tick", "runtime p95 readiness gate"),
        recovery_tests=("bounded command queue", "pause/reset/error lifecycle", "backend fallback receipts"),
        notes=("Reference, native CPU, and qualified GPU-provider paths share one compiled IR; platform GPU qualification remains device-specific.",),
    ),
    "engine.audit_runtime_readiness": CapabilityEvidence(
        "engine.audit_runtime_readiness",
        local_executor=True,
        deterministic_tests=("test_engine_runtime_foundation.py",),
        user_entry_points=("python_api",),
        persistence_tests=("stable authored asset fingerprint", "versioned cache manifest"),
        recovery_tests=("explicit fallback and blocker reporting",),
        notes=("Never reports qualified without measured performance and independent replay evidence.",),
    ),
    "engine.qualify_runtime_determinism": CapabilityEvidence(
        "engine.qualify_runtime_determinism",
        local_executor=True,
        deterministic_tests=("test_independent_runtime_replays_qualify_deterministically",),
        user_entry_points=("python_api",),
        recovery_tests=("tick-level mismatch reporting",),
        notes=("Qualification is scene-, profile-, and backend-specific rather than a global determinism claim.",),
    ),
    "engine.build_simulation_render_stream": CapabilityEvidence(
        "engine.build_simulation_render_stream",
        local_executor=True,
        deterministic_tests=("test_simulation_render_coupling.py", "test_fx_performance.py"),
        user_entry_points=("viewer", "python_api"),
        native_backend="Persistent native SoA and provider-owned device-buffer views",
        performance_baselines=("resident stream avoids particle-object position materialization",),
        recovery_tests=("explicit consumer interop and synchronization receipts",),
        notes=("Qt Quick consumes host SoA positions but still uploads geometry; shared GPU-handle import is not yet qualified.",),
    ),
    "simulation.compile_multiphysics_coupling": CapabilityEvidence(
        "simulation.compile_multiphysics_coupling",
        local_executor=True,
        deterministic_tests=("test_simulation_render_coupling.py",),
        user_entry_points=("python_api", "compiled_simulation_ir"),
        recovery_tests=("whole-tick reference fallback when a coupling kernel is missing",),
        stress_tests=("bounded exchange-pair capacity",),
        notes=("Ordered coupling and fallback execution are live; hybrid per-stage CPU/GPU scheduling remains open.",),
    ),
    "simulation.paint_emission_source": CapabilityEvidence(
        "simulation.paint_emission_source",
        local_executor=True,
        deterministic_tests=("test_character_dynamics_cloth.py",),
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
        deterministic_tests=("test_dcc_scene_restoration_service.py", "test_material_contract.py", "test_tc_scene_conversion_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_large_scene_conversion_saves_and_reads_back_inside_budget",),
        transfer_readback_tests=("test_large_scene_conversion_saves_and_reads_back_inside_budget",),
        native_backend="TC-native retained scene compiler and atomic tcscene archive writer",
        performance_baselines=("test_large_scene_conversion_saves_and_reads_back_inside_budget",),
        recovery_tests=("test_scene_conversion_rejects_empty_or_canceled_work_without_output",),
        notes=("Full-scene promotion passes a 2,500-mesh bounded conversion, atomic save/load, embedded snapshot readback, and cancellation recovery.",),
    ),
    "scene.compose_usd": CapabilityEvidence(
        "scene.compose_usd",
        local_executor=True,
        deterministic_tests=("test_usd_composition_service.py", "test_usd_composition_command_service.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_tcscene_round_trips_usd_composition_and_source_fingerprints",),
        transfer_readback_tests=("test_live_openusd_backend_composes_layers_variants_and_overrides",),
        native_backend="Blender 5.1 / OpenUSD 25.8 isolated worker",
        performance_baselines=("live OpenUSD composition completed inside the 60-second isolated-worker budget",),
        recovery_tests=("test_pre_canceled_composition_never_launches_backend", "test_live_backend_rejects_a_malformed_source_layer"),
        notes=("Interactive and recovery tested; production qualification still needs performance baselines, golden stages, and stress coverage.",),
    ),
    "skinning.export_weights": CapabilityEvidence(
        "skinning.export_weights",
        local_executor=True,
        deterministic_tests=("test_viewer_skinning_commands.py", "test_skin_weight_file_interchange.py"),
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
        deterministic_tests=("test_viewer_skinning_commands.py", "test_skin_weight_file_interchange.py"),
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
        deterministic_tests=("test_character_intelligence_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
        notes=("Serializable TC-native profile and state; no language model is required.",),
    ),
    "characters.set_parameter": CapabilityEvidence(
        "characters.set_parameter",
        local_executor=True,
        deterministic_tests=("test_character_parameters_are_typed_clamped_locked_and_serializable",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
    ),
    "characters.add_rule": CapabilityEvidence(
        "characters.add_rule",
        local_executor=True,
        deterministic_tests=("test_authored_rules_objectives_and_affordances_override_model_proposals",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
        notes=("Authored deny rules remain authoritative over optional model proposals.",),
    ),
    "characters.add_objective": CapabilityEvidence(
        "characters.add_objective",
        local_executor=True,
        deterministic_tests=("test_authored_rules_objectives_and_affordances_override_model_proposals",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
    ),
    "characters.set_relationship": CapabilityEvidence(
        "characters.set_relationship",
        local_executor=True,
        deterministic_tests=("test_character_intelligence_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
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
            "test_character_intelligence_service.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
        notes=("Produces an inspectable why-receipt before validated effects can mutate world state.",),
    ),
    "narrative.set_world_fact": CapabilityEvidence(
        "narrative.set_world_fact",
        local_executor=True,
        deterministic_tests=("test_character_intelligence_service.py",),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
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
            "test_character_intelligence_service.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_character_intelligence_service.py",),
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
        deterministic_tests=("test_viewer_skinning_commands.py", "test_skin_weight_file_interchange.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_viewer_native_bind_and_weight_commands_mutate_rig_graph",),
        transfer_readback_tests=("test_tcskin_file_preserves_eight_influences_and_round_trips", "test_tcskin_remaps_influences_without_losing_normalization"),
        native_backend="TC-native immutable SkinClusterState kernel with EditableRigGraph persistence",
        performance_baselines=("test_tcskin_20k_vertex_eight_influence_baseline",),
        recovery_tests=("test_tcskin_rejects_corruption_wrong_topology_and_missing_influences", "test_viewer_remove_influence_requires_fallback_for_sole_weight"),
        notes=("The shared eight-influence skin cluster contract passes 20k-vertex atomic interchange, strict recovery, remap, normalization, and rig-graph mutation coverage.",),
    )

for _capability in ("rigging.constrain_to_mesh", "rigging.constrain_to_normal"):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_surface_attachment_service.py", "test_viewer_surface_constraint_commands.py", "test_rig_graph_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_surface_constraint_round_trips_in_editable_rig_graph",),
        transfer_readback_tests=("test_normal_constraint_evaluates_surface_frame_and_round_trips", "test_large_rig_graph_evaluates_and_round_trips_inside_budget"),
        native_backend="TC-native EditableRigGraph evaluator with stable barycentric surface frames",
        performance_baselines=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
        recovery_tests=("test_invalid_rig_edits_are_transactional",),
        notes=("Stable barycentric attachment shares the production-qualified native rig graph; deforming-source refresh remains source-driven.",),
    )

CAPABILITY_EVIDENCE["rigging.create_mechanical_ik"] = CapabilityEvidence(
    "rigging.create_mechanical_ik",
    local_executor=True,
    deterministic_tests=("test_mechanical_rig_service.py", "test_viewer_mechanical_rig_command.py", "test_rig_graph_production.py"),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_mechanical_graph_round_trips_and_re_evaluates",),
    transfer_readback_tests=("test_mechanical_graph_round_trips_and_re_evaluates",),
    native_backend="TC-native EditableRigGraph mechanical relationship evaluator",
    performance_baselines=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
    recovery_tests=("test_mechanical_rig_rejects_zero_ratio_and_unknown_endpoints", "test_invalid_rig_edits_are_transactional"),
    notes=("Portable live mechanical relationships share the bounded native rig evaluator and exact graph readback.",),
)

CAPABILITY_EVIDENCE["rigging.create_quadruped_leg_ik"] = CapabilityEvidence(
    "rigging.create_quadruped_leg_ik",
    local_executor=True,
    deterministic_tests=("test_quadruped_leg_rig_service.py", "test_rig_graph_production.py"),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_quadruped_leg_graph_round_trips_and_evaluates",),
    transfer_readback_tests=("test_quadruped_leg_graph_round_trips_and_evaluates",),
    native_backend="TC-native two-stage rotate-plane IK on EditableRigGraph",
    performance_baselines=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
    recovery_tests=("test_quadruped_leg_rejects_noncontiguous_chain", "test_invalid_rig_edits_are_transactional"),
    notes=("Four-joint two-stage RP IK shares the bounded native rig evaluator and exact graph readback.",),
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
        deterministic_tests=("test_viewer_adaptive_rigging_commands.py", "test_quadruped_leg_rig_service.py", "test_rig_graph_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
        transfer_readback_tests=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
        native_backend="TC-native EditableRigGraph DAG, constraint, and solver evaluator",
        performance_baselines=("test_large_rig_graph_evaluates_and_round_trips_inside_budget",),
        recovery_tests=("test_invalid_rig_edits_are_transactional",),
        notes=("Shared native rigging controller passes a 1,000-node evaluation/readback budget and transactional invalid-edit recovery.",),
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
        native_backend="Retained TC procedural graph runtime with deterministic world-build workers",
        performance_baselines=("fresh world-production qualification under the 30-second bounded build budget",),
        recovery_tests=("procedural validation, deterministic recook, and adapter round-trip checks",),
        notes=("World-production qualification exercises deterministic cooking, simulation, and Unreal/Unity/Blender/Houdini/Godot adapter readback.",),
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
        transfer_readback_tests=("test_live_openusd_backend_composes_layers_variants_and_overrides",),
        native_backend="Blender 5.1 / OpenUSD 25.8 isolated worker",
        performance_baselines=("live OpenUSD composition completed inside the 60-second isolated-worker budget",),
        recovery_tests=("test_pre_canceled_composition_never_launches_backend", "test_live_backend_rejects_a_malformed_source_layer"),
        notes=("Edits share the source-bound, cancellable OpenUSD composition worker and live stage readback.",),
    )

CAPABILITY_EVIDENCE["scene.convert_selection_to_tc"] = CapabilityEvidence(
    "scene.convert_selection_to_tc",
    local_executor=True,
    deterministic_tests=("test_dcc_scene_restoration_service.py", "test_material_contract.py", "test_tc_scene_conversion_production.py"),
    user_entry_points=("viewer", "python_api", "chat"),
    persistence_tests=("test_selection_conversion_is_scoped_and_stable",),
    transfer_readback_tests=("test_large_scene_conversion_saves_and_reads_back_inside_budget",),
    native_backend="TC-native retained scene compiler and atomic tcscene archive writer",
    performance_baselines=("test_large_scene_conversion_saves_and_reads_back_inside_budget",),
    recovery_tests=("test_scene_conversion_rejects_empty_or_canceled_work_without_output",),
    notes=("Selection-scoped promotion shares the bounded native compiler and verifies stable IDs, source provenance, atomic readback, and cancellation.",),
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
        deterministic_tests=("test_viewer_adaptive_authoring_commands.py", "test_mesh_modeling_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_topology_failure_is_transactional_and_result_round_trips",),
        transfer_readback_tests=("test_topology_failure_is_transactional_and_result_round_trips",),
        native_backend="TC-native immutable polygon-topology kernel",
        performance_baselines=("test_topology_kernel_has_bounded_representative_mesh_performance",),
        recovery_tests=("test_topology_failure_is_transactional_and_result_round_trips",),
        notes=("Stable topology edits preserve source mappings, participate in Viewer undo, and pass the 10k-quad production baseline.",),
    )

for _capability in ("animation.set_keyframe", "animation.create_take", "animation.add_layer"):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_viewer_adaptive_authoring_commands.py", "test_animation_take_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_animation_takes_layers_and_curves_round_trip_losslessly",),
        transfer_readback_tests=("test_animation_takes_layers_and_curves_round_trip_losslessly",),
        native_backend="TC-native EditableRigGraph animation take and curve runtime",
        performance_baselines=("test_animation_curve_has_bounded_large_take_performance",),
        recovery_tests=("test_animation_failures_are_transactional",),
        notes=("Native takes, weighted layers, and sorted keyframe curves pass a 10k-key bounded baseline and lossless graph readback.",),
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
    "simulation.paint_emission_source",
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
        deterministic_tests=("test_character_dynamics_cloth.py", "test_engine_runtime_foundation.py", "test_native_simulation_backend.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_emission_source_map_round_trips_through_tcscene",),
        transfer_readback_tests=("simulation transfer manifest validation",),
        native_backend="Compiled TC simulation IR with persistent native CPU and capability-gated GPU providers",
        performance_baselines=("fresh realtime-FX 120-frame p95 budget qualification",),
        recovery_tests=("test_engine_runtime_foundation.py", "test_native_simulation_backend.py"),
        notes=("Production evidence is source-bound through the realtime-FX receipt; device-specific GPU qualification remains separate.",),
    )

for _capability in (
    "simulation.create_physics_joint", "simulation.edit_physics_joints",
    "simulation.generate_ragdoll", "simulation.build_physics_stress_scene",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_physics_joint_authoring_service.py", "test_ragdoll_replay_stress_services.py", "test_collision_cook_and_physics_network.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("physics asset and native runtime manifest round-trip",),
        transfer_readback_tests=("test_collision_cook_and_physics_network.py",),
        native_backend="TC native player physics manifest and deterministic reference solver",
        performance_baselines=("test_ragdoll_replay_stress_services.py",),
        recovery_tests=("test_collision_cook_and_physics_network.py",),
        notes=("Native manifest readback and bounded stress/replay coverage are part of the capability evidence suite.",),
    )

for _capability in (
    "deformation.add_jiggle", "deformation.add_muscle", "deformation.set_muscle_activation",
    "deformation.add_blend_shape", "deformation.set_blend_shape_weights",
    "deformation.add_secondary_motion_preset", "deformation.paint_influence"
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_muscle_deformer.py", "test_blend_shape_deformer.py", "test_viewer_adaptive_authoring_commands.py", "test_deformation_production.py"),
        user_entry_points=("viewer", "viewer_brush", "python_api", "chat"),
        persistence_tests=("test_dense_deformation_stack_evaluates_and_round_trips_inside_budget",),
        transfer_readback_tests=("test_destination_golden_manifest_round_trips_losslessly", "test_deformation_transfer_plan_keeps_skin_and_reports_honest_host_gates"),
        native_backend="TC-native NumPy deformation stack with sparse morph, muscle, jiggle, and flesh kernels",
        performance_baselines=("test_dense_deformation_stack_evaluates_and_round_trips_inside_budget",),
        recovery_tests=("test_invalid_deformation_authoring_is_transactional", "test_deformation_point_cache_qualification_rejects_topology_and_nan"),
        notes=("Editable weight maps and ordered graph deformers pass a 10k-vertex evaluation/readback budget, strict authoring recovery, and multi-target transfer contracts.",),
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
        deterministic_tests=("test_tc_player_vertical_slice.py", "test_scene_document_lifecycle.py", "test_viewer_adaptive_authoring_commands.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_scene_document_lifecycle.py", "test_tc_player_vertical_slice.py"),
        transfer_readback_tests=("native player package asset-hash and smoke-output verification",),
        native_backend="TC native Windows player and runtime scene compiler",
        performance_baselines=("fresh 120-frame playable-project p95 qualification",),
        recovery_tests=("dependency-closed deterministic recook and package hash verification",),
        notes=("Runtime plans and incremental playtest receipts are source-bound to the native playable-project qualification.",),
    )

for _capability in (
    "characters.create",
    "characters.set_parameter",
    "characters.add_rule",
    "characters.add_objective",
    "characters.set_relationship",
    "characters.record_memory",
    "characters.choose_action",
    "narrative.set_world_fact",
    "narrative.add_beat",
    "narrative.select_beat",
):
    CAPABILITY_EVIDENCE[_capability] = CapabilityEvidence(
        _capability,
        local_executor=True,
        deterministic_tests=("test_character_intelligence_service.py", "test_character_world_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_large_character_world_runtime_and_readback_are_bounded",),
        transfer_readback_tests=("test_large_character_world_runtime_and_readback_are_bounded",),
        native_backend="TC-native deterministic character-brain and narrative runtime",
        performance_baselines=("test_large_character_world_runtime_and_readback_are_bounded",),
        recovery_tests=("test_character_world_failures_are_safe_and_authority_is_explicit",),
        notes=("Authored rules remain authoritative while character and narrative state share the 1,000-agent bounded runtime and exact world readback.",),
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
            "test_character_world_production.py",
        ),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_crowd_steering_and_world_intelligence_round_trip_deterministically",),
        transfer_readback_tests=("test_large_character_world_runtime_and_readback_are_bounded",),
        native_backend="TC-native deterministic perception, navigation, behavior, dialogue, crowd, and authority runtime",
        performance_baselines=("test_large_character_world_runtime_and_readback_are_bounded",),
        recovery_tests=("test_character_world_failures_are_safe_and_authority_is_explicit",),
        notes=("The deterministic world runtime passes 1,000-agent behavior, 5,000-node navigation, 250-agent steering, exact readback, and explicit authority recovery.",),
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
        deterministic_tests=("test_game_experience_service.py", "test_world_intelligence_command_service.py", "test_game_experience_production.py"),
        user_entry_points=("viewer", "python_api", "chat"),
        persistence_tests=("test_full_gameplay_and_visual_profile_round_trips_losslessly",),
        transfer_readback_tests=("test_full_gameplay_and_visual_profile_round_trips_losslessly",),
        native_backend="TC-native game-experience and presentation-profile planner",
        performance_baselines=("test_game_experience_planning_has_bounded_catalog_scale",),
        recovery_tests=("test_invalid_gameplay_authoring_fails_without_partial_profile",),
        notes=("Composable gameplay, accessibility, budget, and visual-plan APIs pass a 5,000-profile planning baseline and lossless profile readback.",),
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
