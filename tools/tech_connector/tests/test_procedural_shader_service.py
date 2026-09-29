"""Portable procedural shader graph and preview regression coverage."""

from __future__ import annotations

import numpy as np

from tech_connector.game_engine.rendering.material_contract import normalize_portable_material, viewer_material_approximation
from tech_connector.game_engine.rendering.procedural_shader_service import (
    compile_procedural_shader_graph,
    lower_qt_quick3d_shader,
    procedural_shader_presets,
    render_procedural_preview,
    shader_node_catalog,
    validate_procedural_shader_graph,
)


def test_catalog_covers_industry_baseline_procedural_families() -> None:
    catalog = shader_node_catalog()

    assert {"ramp", "gradient_noise", "voronoi", "fbm", "turbulence", "ridged"} <= set(catalog)
    assert {"transform2d", "panner", "triplanar", "normal_from_height", "fresnel"} <= set(catalog)
    assert catalog["fbm"]["category"] == "Fractal"


def test_presets_validate_and_render_bounded_rgba_previews() -> None:
    for key, graph in procedural_shader_presets().items():
        validation = validate_procedural_shader_graph(graph)
        pixels, receipt = render_procedural_preview(graph, width=96, height=64, time_seconds=0.5)

        assert validation["valid"], key
        assert pixels.shape == (64, 96, 4)
        assert pixels.dtype == np.uint8
        assert pixels[..., :3].max() > pixels[..., :3].min()
        assert receipt["fallback"] == "cpu_baked_preview"


def test_graph_validation_reports_unknown_references_cycles_and_cost() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "fbm", "inputs": {"coordinate": {"node": "b"}}, "parameters": {"octaves": 12}},
            {"id": "b", "type": "multiply", "inputs": {"a": {"node": "a"}, "b": {"node": "missing"}}},
        ],
        "outputs": {"base_color": {"node": "b"}},
    }
    validation = validate_procedural_shader_graph(graph, maximum_cost=100)

    assert not validation["valid"]
    assert any("unknown node 'missing'" in error for error in validation["errors"])
    assert any("cycle" in error for error in validation["errors"])
    assert not validation["within_budget"]
    assert any("consider baking" in warning for warning in validation["warnings"])


def test_portable_material_retains_procedural_graph_and_target_receipts() -> None:
    graph = procedural_shader_presets()["fractal_marble"]
    material = normalize_portable_material({"name": "Marble", "procedural_shader": graph})
    approximation = viewer_material_approximation(material)
    glsl = compile_procedural_shader_graph(graph, target="glsl")
    materialx = compile_procedural_shader_graph(graph, target="materialx")

    assert material.procedural_graph["name"] == "Fractal Marble"
    assert approximation["procedural_shader"]["outputs"]["base_color"]["node"] == "veins"
    assert glsl["compiled"] and "tc_procedural" in glsl["source"]
    assert materialx["compiled"] and '<materialx version="1.38">' in materialx["source"]
    assert not glsl["runtime_executable"] and glsl["requires_backend_lowering"]
    assert glsl["fingerprint"] != materialx["fingerprint"]


def test_ramp_interpolates_authored_colors() -> None:
    graph = procedural_shader_presets()["sunset_ramp"]
    pixels, _receipt = render_procedural_preview(graph, width=32, height=8)

    assert not np.array_equal(pixels[:, 0, :], pixels[:, -1, :])
    assert pixels[:, -1, 0].mean() > pixels[:, 0, 0].mean()


def test_timeline_time_animates_procedural_coordinates_deterministically() -> None:
    graph = procedural_shader_presets()["lava"]
    first, _ = render_procedural_preview(graph, width=48, height=48, time_seconds=0.0)
    repeated, _ = render_procedural_preview(graph, width=48, height=48, time_seconds=0.0)
    later, _ = render_procedural_preview(graph, width=48, height=48, time_seconds=1.0)

    assert np.array_equal(first, repeated)
    assert not np.array_equal(first, later)


def test_qt_native_lowering_is_content_addressed_and_cacheable(tmp_path) -> None:
    graph = procedural_shader_presets()["fractal_marble"]
    first = lower_qt_quick3d_shader(graph, cache_root=tmp_path)
    second = lower_qt_quick3d_shader(graph, cache_root=tmp_path)

    assert first["native_executable"]
    assert first["gpu_execution"] and first["pipeline_qualification"] == "deferred_to_first_rhi_draw"
    assert not first["cache_hit"] and second["cache_hit"]
    assert first["fingerprint"] == second["fingerprint"]
    assert first["shader_path"] == second["shader_path"]
    source = (tmp_path / ("tc_procedural_" + first["fingerprint"][:24] + ".frag")).read_text()
    assert "void MAIN()" in source
    assert "BASE_COLOR" in source
    assert "tc_fractal" in source


def test_unsupported_native_node_uses_explicit_preview_fallback(tmp_path) -> None:
    graph = {
        "nodes": [{"id": "surface", "type": "fresnel"}],
        "outputs": {"base_color": {"node": "surface"}},
    }
    receipt = lower_qt_quick3d_shader(graph, cache_root=tmp_path)

    assert not receipt["native_executable"]
    assert receipt["fallback"] == "cpu_baked_preview"
    assert receipt["unsupported_nodes"] == ["fresnel"]
