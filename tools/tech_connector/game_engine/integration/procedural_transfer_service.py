from __future__ import annotations

"""Translate TC procedural intent or deterministic results to DCC/game targets."""

from copy import deepcopy
from typing import Any

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralCookResult,
    ProceduralGraph,
)


TARGET_NODE_MAPPINGS: dict[str, dict[str, str]] = {
    "unreal": {
        "grid_points": "PCG Create Points Grid",
        "scatter_bounds": "PCG Create Points / Spatial Sampler",
        "spline_sample": "PCG Get Spline Data + Spline Sampler",
        "transform_points": "PCG Transform Points",
        "noise_attribute": "PCG Attribute Noise",
        "filter_attribute": "PCG Attribute Filter",
        "select_asset": "PCG weighted mesh selector attributes",
        "instance_on_points": "PCG Static Mesh Spawner",
        "project_heightfield": "PCG Projection / Landscape Data",
        "filter_slope": "PCG Normal To Density + Attribute Filter",
        "filter_heightfield_mask": "PCG Landscape Layer / Attribute Filter",
        "filter_polygon": "PCG Polygon 2D Operations",
        "point_neighborhood": "PCG Point Neighborhood",
        "biome_scatter": "PCG Biome Core recursive subgraph",
        "terrain_hydraulic_erosion": "Landscape Patch + PCG water-flow field adapter",
        "shape_grammar_spline": "PCG Subdivide Spline + Shape Grammar",
        "merge": "PCG Union",
        "output": "PCG Output",
    },
    "blender": {
        "grid_points": "Geometry Nodes Grid",
        "scatter_bounds": "Distribute Points in Volume",
        "spline_sample": "Resample Curve",
        "transform_points": "Set Position / Transform Geometry",
        "repeat_transform": "Repeat Zone",
        "noise_attribute": "Noise Texture field",
        "filter_attribute": "Compare + Separate Geometry",
        "select_asset": "Index Switch / Collection Info",
        "instance_on_points": "Instance on Points",
        "project_heightfield": "Raycast / Sample Nearest Surface",
        "filter_slope": "Normal field + Compare",
        "filter_heightfield_mask": "Named Attribute + Compare",
        "filter_polygon": "Geometry proximity / curve fill selection",
        "point_neighborhood": "Index of Nearest / Geometry Proximity",
        "biome_scatter": "Geometry Nodes biome node group",
        "terrain_hydraulic_erosion": "Simulation Zone hydraulic erosion node group",
        "shape_grammar_spline": "Resample Curve + Instance on Points node group",
        "merge": "Join Geometry",
        "output": "Group Output",
    },
    "houdini": {
        "grid_points": "Grid/Points SOP",
        "scatter_bounds": "Scatter SOP",
        "spline_sample": "Resample SOP",
        "transform_points": "Transform/Point Wrangle SOP",
        "repeat_transform": "For-Each SOP block",
        "noise_attribute": "Attribute Noise SOP",
        "filter_attribute": "Blast/Group Expression SOP",
        "select_asset": "Attribute Randomize/Wrangle SOP",
        "instance_on_points": "Copy to Points SOP",
        "project_heightfield": "Ray SOP / HeightField Project",
        "filter_slope": "Group Expression SOP",
        "filter_heightfield_mask": "HeightField Mask by Feature SOP",
        "filter_polygon": "Group/Boolean SOP mask",
        "point_neighborhood": "Point Cloud Neighborhood VOP/Wrangle",
        "biome_scatter": "HeightField Scatter / Copy to Points biome HDA",
        "terrain_hydraulic_erosion": "HeightField Erode SOP",
        "shape_grammar_spline": "Resample/Copy to Points SOP grammar HDA",
        "merge": "Merge SOP",
        "output": "Null SOP output",
    },
    "unity": {
        "grid_points": "TCProcedural GridPoints job",
        "scatter_bounds": "TCProcedural deterministic scatter job",
        "spline_sample": "Unity Splines sampler adapter",
        "transform_points": "Burst transform job",
        "repeat_transform": "Burst repeat job",
        "noise_attribute": "Burst noise attribute job",
        "filter_attribute": "Burst filter job",
        "select_asset": "weighted prefab selector",
        "instance_on_points": "GPU instancing / Entities Graphics",
        "project_heightfield": "TerrainData height sampler job",
        "filter_slope": "Terrain normal/slope filter job",
        "filter_heightfield_mask": "TerrainLayer/mask sampling job",
        "filter_polygon": "polygon mask Burst job",
        "point_neighborhood": "spatial-hash neighborhood job",
        "biome_scatter": "Terrain/Splines biome Burst jobs",
        "terrain_hydraulic_erosion": "Terrain hydraulic erosion compute job",
        "shape_grammar_spline": "Unity Splines modular layout adapter",
        "merge": "Native container merge",
        "output": "TCProceduralAsset output",
    },
    "godot": {
        "grid_points": "TCProcedural grid generator",
        "scatter_bounds": "deterministic GDScript/C# scatter",
        "spline_sample": "Curve3D sampler",
        "transform_points": "Transform3D point operation",
        "repeat_transform": "TCProcedural repeat operation",
        "noise_attribute": "FastNoiseLite attribute",
        "filter_attribute": "typed point filter",
        "select_asset": "weighted resource selector",
        "instance_on_points": "MultiMeshInstance3D",
        "project_heightfield": "HeightMapShape/Terrain adapter projection",
        "filter_slope": "sampled normal slope filter",
        "filter_heightfield_mask": "heightfield attribute mask",
        "filter_polygon": "Polygon2D sampling mask",
        "point_neighborhood": "spatial-hash neighborhood query",
        "biome_scatter": "FastNoiseLite biome resource + MultiMeshInstance3D",
        "terrain_hydraulic_erosion": "TC terrain erosion compute adapter",
        "shape_grammar_spline": "Curve3D modular MultiMesh layout",
        "merge": "point/instance array merge",
        "output": "TCProceduralResource output",
    },
}

_MESH_NODE_MAPPINGS = {
    "unreal": ("Geometry Script Cube", "Geometry Script Grid", "Geometry Script Transform", "Geometry Script Extrude", "Geometry Script Triangulate"),
    "blender": ("Geometry Nodes Cube", "Geometry Nodes Grid", "Transform Geometry", "Extrude Mesh", "Triangulate"),
    "houdini": ("Box SOP", "Grid SOP", "Transform SOP", "PolyExtrude SOP", "Divide SOP"),
    "unity": ("TC cube mesh job", "TC grid mesh job", "Burst mesh transform", "TC topology extrude", "TC triangulation job"),
    "godot": ("ArrayMesh cube", "ArrayMesh grid", "ArrayMesh transform", "TC topology extrude", "SurfaceTool triangles"),
}
for _target, _nodes in _MESH_NODE_MAPPINGS.items():
    TARGET_NODE_MAPPINGS[_target].update(dict(zip(
        ("mesh_cube", "mesh_grid", "mesh_transform", "mesh_extrude_faces", "mesh_triangulate"),
        _nodes,
    )))


def procedural_target_capabilities(target: str) -> dict[str, Any]:
    normalized = str(target or "").strip().lower()
    if normalized not in TARGET_NODE_MAPPINGS:
        raise ValueError(f"Unsupported procedural transfer target: {target}")
    runtime_graph = normalized in {"unreal", "unity", "godot"}
    return {
        "target": normalized,
        "runtime_graph": runtime_graph,
        "editor_graph": normalized in {"unreal", "blender", "houdini"},
        "deterministic_instances": True,
        "incremental_recook": normalized in {"unreal", "blender", "houdini", "unity"},
        "bake_fallbacks": ["instance_manifest", "usd_point_instancer", "baked_mesh"],
    }


def build_procedural_transfer_manifest(
    graph: ProceduralGraph,
    result: ProceduralCookResult,
    target: str,
) -> dict[str, Any]:
    normalized = str(target or "").strip().lower()
    capabilities = procedural_target_capabilities(normalized)
    mapping = TARGET_NODE_MAPPINGS[normalized]
    nodes: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for node_id in graph.to_dict()["nodes"]:
        operation = str(node_id["operation"])
        target_node = mapping.get(operation, "")
        support = "native" if target_node else "bake"
        if not target_node:
            unsupported.append(str(node_id["node_id"]))
        nodes.append(
            {
                "node_id": node_id["node_id"],
                "operation": operation,
                "target_node": target_node,
                "support": support,
                "parameters": deepcopy(node_id.get("parameters") or {}),
            }
        )
    instances = [instance.to_dict() for instance in result.payload.instances]
    meshes = deepcopy(result.payload.meshes)
    return {
        "schema": "tc.procedural_transfer.v1",
        "target": normalized,
        "graph_id": graph.graph_id,
        "graph_fingerprint": result.graph_fingerprint,
        "output_fingerprint": result.payload.fingerprint,
        "capabilities": capabilities,
        "nodes": nodes,
        "unsupported_nodes": unsupported,
        "translation_mode": "native_graph" if not unsupported else "hybrid_graph_and_bake",
        "instance_manifest": instances,
        "mesh_manifest": meshes,
        "field_manifest": deepcopy(result.payload.metadata.get("heightfield") or {}),
        "counts": {
            "points": len(result.payload.points),
            "instances": len(instances),
            "meshes": len(meshes),
            "nodes": len(nodes),
        },
        "validation": [
            "target instance count matches the TC deterministic cook",
            "stable IDs and source asset references survive transfer",
            "target-space bounds match after unit and axis conversion",
            "same seed produces the same output fingerprint",
        ],
    }
