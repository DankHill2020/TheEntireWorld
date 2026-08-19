"""Planning contracts for scalable mesh and point-based engine geometry."""

from __future__ import annotations

from typing import Any


RUNTIME_GEOMETRY_PLAN_SCHEMA = "tech_connector.runtime_geometry_plan.v1"


def build_runtime_geometry_plan(
    asset_id: str,
    *,
    triangle_count: int,
    material_features: list[str] | tuple[str, ...] = (),
    deforming: bool = False,
    collision_required: bool = True,
    target_platforms: list[str] | tuple[str, ...] = ("desktop",),
) -> dict[str, Any]:
    """Build a measurable hybrid LOD/point-runtime plan without claiming conversion exists yet."""
    triangles = max(0, int(triangle_count))
    features = sorted({str(item).strip().lower() for item in material_features if str(item).strip()})
    targets = [str(item).strip().lower() for item in target_platforms if str(item).strip()] or ["desktop"]
    difficult_materials = sorted(set(features) & {"translucent", "masked", "subsurface", "anisotropic", "clearcoat"})
    point_candidate = triangles >= 100_000 and not deforming and not difficult_materials
    return {
        "schema": RUNTIME_GEOMETRY_PLAN_SCHEMA,
        "asset_id": str(asset_id or "asset"),
        "status": "planned",
        "source_of_truth": "tc_native_mesh_with_material_graph",
        "inputs": {
            "triangle_count": triangles,
            "material_features": features,
            "deforming": bool(deforming),
            "collision_required": bool(collision_required),
            "target_platforms": targets,
        },
        "representations": [
            {
                "kind": "mesh_lod_chain",
                "required": True,
                "levels": [
                    {"name": "LOD0", "triangle_ratio": 1.0, "screen_error_px": 0.5},
                    {"name": "LOD1", "triangle_ratio": 0.5, "screen_error_px": 1.0},
                    {"name": "LOD2", "triangle_ratio": 0.2, "screen_error_px": 2.0},
                    {"name": "LOD3", "triangle_ratio": 0.05, "screen_error_px": 4.0},
                ],
                "preserve": ["silhouette", "UV seams", "hard normals", "material boundaries", "skin weights"],
            },
            {
                "kind": "clustered_mesh_runtime",
                "required": True,
                "product_role": "TC virtualized hard-surface geometry (Nanite-comparable goal)",
                "strategy": "micro-clusters and meshlets with hierarchical screen-space error",
                "streaming": "cluster pages with GPU-driven visibility and occlusion",
                "hard_surface_features": [
                    "automatic cluster hierarchy",
                    "GPU instance and cluster culling",
                    "fine-grained occlusion",
                    "page-level residency and asynchronous streaming",
                    "material-boundary, hard-normal, UV-seam, and silhouette preservation",
                    "fallback mesh for unsupported materials, collision, ray queries, and external engines",
                ],
            },
            {
                "kind": "surfel_point_runtime",
                "required": False,
                "candidate": point_candidate,
                "strategy": "oriented surfels clustered into streamable spatial pages",
                "point_payload": [
                    "position", "normal", "radius", "base_color", "roughness", "metalness",
                    "emission", "opacity", "material_id", "source_primitive_id",
                ],
                "material_bake": "sample the source material in surface/UV space and retain atlas references for view-dependent detail",
                "limitations": [
                    "translucency, masking, subsurface, anisotropy, and clearcoat require dedicated shaders or mesh fallback",
                    "skinned/deforming assets require deformation-aware points or mesh fallback",
                    "point overdraw and sorting can be slower than clustered meshes at close range",
                ],
            },
        ],
        "runtime_selection": {
            "mode": "per-view measured hybrid",
            "never_assume_points_are_faster": True,
            "inputs": [
                "projected size", "screen-space error", "visibility", "material class", "motion",
                "GPU timing history", "memory residency", "streaming bandwidth", "platform profile",
            ],
            "fallback_order": ["clustered_mesh_runtime", "mesh_lod_chain"],
        },
        "non_render_fallbacks": {
            "collision": "authored or generated low-poly mesh" if collision_required else "optional bounds/SDF",
            "navigation": "mesh or signed-distance proxy",
            "ray_queries": "mesh BVH or conservative surfel BVH with mesh fallback",
            "selection_and_editing": "stable source primitive IDs mapped back to the TC-native mesh",
        },
        "validation_gates": [
            "silhouette and depth error stay below the platform screen-space threshold",
            "normal and PBR channel error stay below authored tolerances",
            "temporal shimmer and disocclusion holes pass camera-motion tests",
            "GPU frame time improves against clustered mesh and conventional LOD baselines",
            "resident memory and streaming bandwidth fit the platform budget",
            "collision, navigation, shadows, picking, and ray queries use verified fallbacks",
            "conversion receipt maps every runtime page back to source asset/version/materials",
        ],
        "engine_transfer": {
            "tc_engine": "native clustered mesh plus optional surfel pages",
            "unreal": "StaticMesh/SkeletalMesh LODs or Nanite-ready mesh; point proxy remains TC-plugin-specific",
            "unity": "Mesh LODGroup/Entities Graphics fallback; point proxy remains TC-plugin-specific",
            "portable": "glTF/USD/FBX mesh LODs plus baked PBR textures",
        },
        "build_chunks": {
            "policy": "compile each asset and each representation independently",
            "chunks": [
                "source mesh and material inventory",
                "mesh LOD levels",
                "virtualized hard-surface cluster hierarchy",
                "optional surfel point pages",
                "collision/navigation/ray-query fallback",
                "material atlases and shader variants",
            ],
            "retry_scope": "one asset representation chunk",
        },
    }


def validate_runtime_geometry_plan(plan: dict[str, Any]) -> list[str]:
    """Return structural planning errors before a future compiler accepts the plan."""
    errors: list[str] = []
    if str(plan.get("schema") or "") != RUNTIME_GEOMETRY_PLAN_SCHEMA:
        errors.append("unsupported runtime geometry plan schema")
    kinds = {
        str(item.get("kind") or "")
        for item in plan.get("representations") or []
        if isinstance(item, dict)
    }
    for required in ("mesh_lod_chain", "clustered_mesh_runtime", "surfel_point_runtime"):
        if required not in kinds:
            errors.append(f"missing representation plan: {required}")
    selection = plan.get("runtime_selection") if isinstance(plan.get("runtime_selection"), dict) else {}
    if not selection.get("never_assume_points_are_faster"):
        errors.append("point runtime must be benchmark-gated")
    if not plan.get("validation_gates"):
        errors.append("validation gates are required")
    return errors
