from __future__ import annotations

import json

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.asset_graph_compile_service import AssetGraphCompileService
from tech_connector.game_engine.assets.effect_asset_service import (
    EFFECT_RUNTIME_SCHEMA,
    MODULE_LIBRARY,
    compile_effect_payload,
    effect_system_defaults,
    estimate_effect_cost,
    normalize_effect_properties,
    validate_effect_properties,
)


def test_all_runtime_presets_normalize_to_structured_module_stacks() -> None:
    values = effect_system_defaults(preset="sparks", quality="high", seed=42)
    assert values["effect_version"] == 2
    assert values["simulation"]["seed"] == 42
    assert values["emitters"][0]["modules"][0]["phase"] == "particle_spawn"
    assert all(isinstance(module, dict) for emitter in values["emitters"] for module in emitter["modules"])
    assert not [item for item in validate_effect_properties(values) if item.severity == "error"]


def test_validation_blocks_cpu_events_on_gpu_emitters() -> None:
    values = effect_system_defaults(preset="sparks")
    emitter = values["emitters"][0]
    emitter["simulation_target"] = "gpu"
    emitter["modules"].append({
        "id": "event", "type": "event_generator", "phase": "event_handler",
        "enabled": True, "parameters": {}, "version": 1,
    })
    codes = {item.code for item in validate_effect_properties(values)}
    assert "cpu_only_module" in codes


def test_cost_estimator_reports_memory_and_quality_budget() -> None:
    values = effect_system_defaults(preset="sparks")
    values["emitters"][0]["capacity"] = 100_000
    values["emitters"][0]["spawn_rate"] = 100_000
    values["emitters"][0]["lifetime"] = 5.0
    estimate = estimate_effect_cost(values, quality="mobile")
    assert estimate.status == "over_budget"
    assert estimate.estimated_memory_bytes == 9_600_000
    assert estimate.alu_operations_per_second > 0
    assert estimate.recommendations


def test_compile_applies_quality_overrides_and_builds_phase_stacks() -> None:
    values = effect_system_defaults(preset="sparks")
    source_rate = values["emitters"][0]["spawn_rate"]
    payload = json.loads(compile_effect_payload(values, platform="android", quality="mobile"))
    assert payload["schema"] == EFFECT_RUNTIME_SCHEMA
    assert payload["emitters"][0]["spawn_rate"] == source_rate * 0.3
    assert payload["emitters"][0]["module_stacks"]["particle_spawn"]
    assert "modules" not in payload["emitters"][0]


def test_legacy_effect_payload_migrates_without_losing_renderer_or_modules() -> None:
    values = normalize_effect_properties({
        "duration": 2.0, "emitters": [{
            "id": "legacy", "name": "Legacy", "spawn_rate": 10,
            "modules": ["initialize", "forces", "render"],
            "renderer": {"type": "mesh", "mesh_asset_id": "mesh-id", "blend": "opaque"},
        }],
    })
    emitter = values["emitters"][0]
    assert [item["type"] for item in emitter["modules"]] == ["initialize", "gravity", "color_over_life"]
    assert emitter["renderers"][0]["type"] == "mesh"
    assert emitter["renderers"][0]["blend_mode"] == "opaque"


def test_editor_python_api_has_full_effect_parity_and_manifest_output(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_effect_system("Portal", preset="portal", quality="high", seed=7)
    assert receipt.type_id == "tc.effect_system"
    assert "curl_noise" in api.effect_module_library()
    assert "portal" in api.effect_presets()
    assert not [item for item in api.validate_effect_system(receipt.asset_id) if item["severity"] == "error"]
    cost = api.estimate_effect_cost(receipt.asset_id)
    assert cost["emitter_count"] >= 1
    artifact = api.cook_effect_system(receipt.asset_id, platform="windows", quality="high")
    assert json.loads(artifact.path.read_text(encoding="utf-8"))["schema"] == EFFECT_RUNTIME_SCHEMA
    preview_compile = AssetGraphCompileService(api.database, api.registry).compile_asset(receipt.asset_id)
    assert preview_compile.succeeded
    assert preview_compile.ir["executable"]["emitters"][0]["module_ops"][0]["phase"] == "particle_spawn"
    manifest = json.loads(api.cook([receipt.asset_id]).artifact.path.read_text(encoding="utf-8"))
    effect = next(row for row in manifest["assets"] if row["asset_id"] == receipt.asset_id)
    assert effect["derived_outputs"][0]["kind"] == "effect_runtime"
    assert "cook_effect_system" in api.capability_contract()["effect_operations"]


def test_unreal_niagara_export_converts_to_native_stack_and_preserves_unknown_modules(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unreal_effects({
        "engine_version": "5.8", "niagara_systems": [{
            "name": "NS_Impact", "object_path": "/Game/VFX/NS_Impact",
            "parameters": {"Intensity": {"type": "float", "default": 1.0}},
            "emitters": [{
                "id": "sparks", "name": "Sparks", "sim_target": "gpu", "capacity": 2048, "spawn_rate": 120,
                "modules": [
                    {"name": "Initialize Particle", "group": "Particle Spawn"},
                    {"name": "Gravity Force", "group": "Particle Update", "parameters": {"strength": -9.81}},
                    {"name": "Proprietary Studio Module", "group": "Particle Update", "parameters": {"gain": 2}},
                ],
                "renderers": [{"type": "SpriteRenderer", "properties": {"material_asset_id": "material-id"}}],
            }],
        }],
    })
    assert receipt["succeeded"]
    assert any(item["code"] == "unsupported_niagara_module" for item in receipt["diagnostics"])
    values = api.effect_properties(receipt["source_to_asset"]["/Game/VFX/NS_Impact"])
    assert [item["type"] for item in values["emitters"][0]["modules"][:2]] == ["initialize", "gravity"]
    assert values["emitters"][0]["modules"][2]["source_extensions"]
    assert values["emitters"][0]["renderers"][0]["type"] == "sprite"


def test_unity_vfx_graph_export_converts_contexts_blocks_and_output(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.convert_unity_effects({
        "unity_version": "6000.0", "visual_effect_graphs": [{
            "name": "MagicTrail", "guid": "vfx-guid", "parameters": {"Rate": {"type": "float", "default": 50}},
            "systems": [{
                "name": "Trail", "capacity": 4096, "spawn_rate": 50,
                "contexts": [
                    {"type": "Initialize", "blocks": [{"name": "Set Lifetime", "settings": {"lifetime": 2.0}}]},
                    {"type": "Update", "blocks": [{"name": "Turbulence", "settings": {"intensity": 3.0}}]},
                    {"type": "Output", "output_type": "Output Particle Quad", "settings": {"blend_mode": "additive"}},
                ],
            }],
        }],
    })
    values = api.effect_properties(receipt["source_to_asset"]["vfx-guid"])
    emitter = values["emitters"][0]
    assert emitter["simulation_target"] == "gpu"
    assert [item["type"] for item in emitter["modules"]] == ["initialize", "curl_noise"]
    assert emitter["renderers"][0]["type"] == "sprite"
    assert not [item for item in api.validate_effect_system(receipt["asset_ids"][0]) if item["severity"] == "error"]
