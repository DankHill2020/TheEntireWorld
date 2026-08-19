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

# Detailed skinning and GPU contracts remain available as submodules. Keeping
# them lazy here avoids loading the full rig graph for lightweight runtime use.

__all__ = [
    "DeformationWeightMap",
    "DeformationStackRuntime",
    "DeformationStackTelemetry",
    "FleshDeformerSettings",
    "FleshRuntimeState",
    "JiggleDeformerSettings",
    "JiggleRuntimeState",
    "SECONDARY_MOTION_PRESETS",
    "SecondaryMotionPreset",
    "SimulationMeshBinding",
    "SimulationMeshBindingEntry",
    "attach_jiggle_deformer",
    "attach_flesh_deformer",
    "attach_secondary_motion_preset",
    "attach_deformation_map",
    "blend_deformation",
    "evaluate_jiggle",
    "evaluate_flesh",
    "flesh_export_contract",
    "secondary_motion_export_contract",
    "secondary_motion_preset",
    "sample_simulation_mesh",
]
