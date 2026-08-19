"""The Entire World scene authoring and game-runtime package.

This package is intentionally independent from ``tech_connector.engine``, which
owns AI request reasoning. Qt windows consume these headless systems but do not
live here, so the same scene can run in the desktop DCC, tools, tests, or a game.
Game-engine editor surfaces live in ``tech_connector.ui.game_engine`` and the
connected scene viewer lives in ``tech_connector.ui.dcc_viewer``.
"""

from tech_connector.game_engine import authoring, deformation, integration, runtime, scene
from tech_connector.game_engine.deformation import (
    DeformationWeightMap,
    DeformationStackRuntime,
    DeformationStackTelemetry,
    FleshDeformerSettings,
    FleshRuntimeState,
    JiggleDeformerSettings,
    JiggleRuntimeState,
    SECONDARY_MOTION_PRESETS,
    SecondaryMotionPreset,
    SimulationMeshBinding,
    SimulationMeshBindingEntry,
    attach_deformation_map,
    attach_flesh_deformer,
    attach_jiggle_deformer,
    attach_secondary_motion_preset,
    blend_deformation,
    evaluate_jiggle,
    evaluate_flesh,
    flesh_export_contract,
    secondary_motion_export_contract,
    secondary_motion_preset,
    sample_simulation_mesh,
)

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
    "attach_deformation_map",
    "attach_flesh_deformer",
    "attach_jiggle_deformer",
    "attach_secondary_motion_preset",
    "authoring",
    "blend_deformation",
    "deformation",
    "evaluate_jiggle",
    "evaluate_flesh",
    "flesh_export_contract",
    "secondary_motion_export_contract",
    "secondary_motion_preset",
    "integration",
    "runtime",
    "sample_simulation_mesh",
    "scene",
]
