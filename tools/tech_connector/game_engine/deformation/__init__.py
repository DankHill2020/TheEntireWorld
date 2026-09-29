"""Public deformation API shared by the game runtime and The Entire Scene."""

from tech_connector.game_engine.deformation.jiggle import (
    JiggleDeformerSettings,
    JiggleRuntimeState,
    attach_jiggle_deformer,
    evaluate_jiggle,
    secondary_motion_export_contract,
)
from tech_connector.game_engine.deformation.flesh import (
    FleshDeformerSettings,
    FleshRuntimeState,
    attach_flesh_deformer,
    evaluate_flesh,
    flesh_export_contract,
)
from tech_connector.game_engine.deformation.deformation_stack import (
    DeformationStackRuntime,
    DeformationStackTelemetry,
)
from tech_connector.game_engine.deformation.secondary_motion import (
    SECONDARY_MOTION_PRESETS,
    SecondaryMotionPreset,
    attach_secondary_motion_preset,
    secondary_motion_preset,
)
from tech_connector.game_engine.deformation.weight_map import (
    DeformationWeightMap,
    SimulationMeshBinding,
    SimulationMeshBindingEntry,
    attach_deformation_map,
    blend_deformation,
    sample_simulation_mesh,
)
from tech_connector.game_engine.deformation.collision_projection import project_character_point
from tech_connector.game_engine.deformation.tc_deformation_gpu_service import (
    DeformationLodController,
    GpuSecondaryMotionState,
    evaluate_gpu_deformation_stack,
)
from tech_connector.game_engine.deformation.muscle import (
    MuscleDeformerSettings,
    MuscleRuntimeState,
    PoseSpaceTissueDriver,
    attach_muscle_deformer,
    evaluate_muscle,
    muscle_export_contract,
    set_muscle_activation,
)
from tech_connector.game_engine.deformation.deformation_interchange_service import (
    DESTINATIONS as DEFORMATION_TRANSFER_DESTINATIONS,
    DeformationTransferArtifact,
    build_deformation_transfer_plan,
    qualify_deformation_point_cache,
)
from tech_connector.game_engine.deformation.blend_shape import (
    BlendShapeCorrectiveDriver,
    BlendShapeFrame,
    BlendShapeTarget,
    BlendShapeTelemetry,
    attach_blend_shape_deformer,
    blend_shape_export_contract,
    blend_shape_payload,
    blend_shape_target_from_positions,
    blend_shape_target_from_dict,
    blend_shape_targets_from_payload,
    build_blend_shape_destination_manifest,
    blend_shape_targets_from_destination_manifest,
    evaluate_blend_shape,
    set_blend_shape_weights,
)

# Detailed skinning and GPU contracts remain available as submodules. Keeping
# them lazy here avoids loading the full rig graph for lightweight runtime use.

__all__ = [
    "DeformationWeightMap",
    "DeformationStackRuntime",
    "DeformationStackTelemetry",
    "DeformationLodController",
    "FleshDeformerSettings",
    "FleshRuntimeState",
    "JiggleDeformerSettings",
    "JiggleRuntimeState",
    "MuscleDeformerSettings",
    "MuscleRuntimeState",
    "PoseSpaceTissueDriver",
    "GpuSecondaryMotionState",
    "SECONDARY_MOTION_PRESETS",
    "SecondaryMotionPreset",
    "SimulationMeshBinding",
    "SimulationMeshBindingEntry",
    "attach_jiggle_deformer",
    "attach_muscle_deformer",
    "attach_flesh_deformer",
    "attach_secondary_motion_preset",
    "attach_deformation_map",
    "blend_deformation",
    "evaluate_jiggle",
    "evaluate_muscle",
    "evaluate_flesh",
    "evaluate_gpu_deformation_stack",
    "flesh_export_contract",
    "secondary_motion_export_contract",
    "secondary_motion_preset",
    "sample_simulation_mesh",
    "muscle_export_contract",
    "set_muscle_activation",
    "project_character_point",
    "DEFORMATION_TRANSFER_DESTINATIONS",
    "DeformationTransferArtifact",
    "build_deformation_transfer_plan",
    "qualify_deformation_point_cache",
    "BlendShapeCorrectiveDriver",
    "BlendShapeFrame",
    "BlendShapeTarget",
    "BlendShapeTelemetry",
    "attach_blend_shape_deformer",
    "blend_shape_export_contract",
    "blend_shape_payload",
    "blend_shape_target_from_positions",
    "blend_shape_target_from_dict",
    "blend_shape_targets_from_payload",
    "build_blend_shape_destination_manifest",
    "blend_shape_targets_from_destination_manifest",
    "evaluate_blend_shape",
    "set_blend_shape_weights",
]
