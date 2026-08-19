"""TC-native runtime contracts shared by the DCC workspace and future engine."""

from __future__ import annotations

from typing import Any


def runtime_authoring_contract() -> dict[str, Any]:
    """Describe one authored asset with scalable runtime presentation and simulation."""
    return {
        "schema": "tech_connector.runtime_authoring_contract.v1",
        "authority": "tech_connector",
        "simulation_ir": {
            "schema": "tech_connector.simulation_ir.v1",
            "profiles": ["cinematic", "photoreal", "realtime", "mobile", "toony", "stylized", "retro"],
            "backends": ["reference_cpu", "native_cpu", "gpu_compute"],
            "fallback_policy": "compile receipts must expose every unavailable backend and representation change",
        },
        "experience_contract": {
            "states": ["live", "dirty", "compiling", "baking", "cached", "fallback", "error"],
            "interaction": ["direct_manipulation", "painted_masks", "summary_controls", "advanced_graph", "a_b_compare"],
            "diagnostics": ["constraint_overlays", "grid_slices", "stage_timings", "memory", "cache_throughput"],
        },
        "asset_contracts": {
            "rig": {
                "runtime_native": True,
                "data": ["skeleton", "skin_weights", "constraints", "ik", "deformers", "animation_graph"],
                "quality_profiles": ["cinematic", "realtime", "mobile", "retro"],
                "engine_export": ["baked_skeleton", "animation_clips", "control_rig_recipe", "deformation_cache"],
            },
            "cloth": {
                "runtime_native": True,
                "data": ["simulation_mesh", "render_mesh", "attachments", "collision", "tear_map", "material_response"],
                "quality_profiles": ["photoreal", "realtime", "toony", "retro_simple"],
                "engine_export": ["tc_runtime_cloth", "geometry_cache", "vertex_animation_texture", "skeletal_proxy"],
            },
            "effects": {
                "runtime_native": True,
                "data": ["emitters", "fields", "colliders", "solvers", "materials", "events", "lod_policy"],
                "quality_profiles": ["photoreal", "toony", "stylized", "retro_simple"],
                "engine_export": ["tc_effect_graph", "vdb", "geometry_cache", "flipbook", "point_cache"],
            },
        },
        "principles": [
            "Art direction is independent from simulation fidelity.",
            "The same source asset can compile to deterministic quality tiers.",
            "Interactive preview and baked playback share the same authored graph.",
            "Unsupported target-engine features compile to an explicit fallback rather than disappearing.",
            "Performance budgets and UX states are authored contracts, not backend implementation details.",
        ],
    }
