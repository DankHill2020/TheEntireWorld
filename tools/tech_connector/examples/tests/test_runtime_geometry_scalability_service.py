from tech_connector.services.dcc.runtime_geometry_scalability_service import (
    build_runtime_geometry_plan,
    validate_runtime_geometry_plan,
)


def test_builds_hybrid_point_candidate_for_large_static_opaque_mesh() -> None:
    plan = build_runtime_geometry_plan(
        "city_block",
        triangle_count=4_000_000,
        material_features=["opaque", "emission"],
        target_platforms=["desktop", "console"],
    )

    assert validate_runtime_geometry_plan(plan) == []
    representations = {item["kind"]: item for item in plan["representations"]}
    assert representations["surfel_point_runtime"]["candidate"] is True
    assert representations["mesh_lod_chain"]["required"] is True
    assert plan["runtime_selection"]["never_assume_points_are_faster"] is True
    assert "material_id" in representations["surfel_point_runtime"]["point_payload"]
    assert "source_primitive_id" in representations["surfel_point_runtime"]["point_payload"]
    assert "Nanite-comparable" in representations["clustered_mesh_runtime"]["product_role"]
    assert plan["build_chunks"]["retry_scope"] == "one asset representation chunk"


def test_keeps_translucent_or_deforming_assets_on_mesh_fallback() -> None:
    plan = build_runtime_geometry_plan(
        "hero_hair",
        triangle_count=500_000,
        material_features=["masked", "anisotropic"],
        deforming=True,
    )

    representations = {item["kind"]: item for item in plan["representations"]}
    assert representations["surfel_point_runtime"]["candidate"] is False
    assert plan["runtime_selection"]["fallback_order"][0] == "clustered_mesh_runtime"
    assert plan["non_render_fallbacks"]["collision"] == "authored or generated low-poly mesh"
