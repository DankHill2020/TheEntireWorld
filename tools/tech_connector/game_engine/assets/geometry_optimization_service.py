"""Simplygon-style, backend-neutral geometry optimization pipeline contracts.

The contract deliberately separates *what* an artist requests from *which*
backend can execute it.  This keeps presets portable and prevents a basic
triangle decimator from being presented as a proxy/remeshing solution.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class GeometryOptimizationIssue:
    severity: str
    code: str
    message: str
    stage_id: str = ""


GEOMETRY_PROCESSORS: dict[str, dict[str, Any]] = {
    "reduction": {
        "display_name": "Geometry Reduction", "output": "preserved_topology_lod",
        "compatible_components": ("material_baking", "skinning", "visibility", "geometry_culling"),
        "backend": "blender_decimate", "maturity": "runtime_ready",
    },
    "quad_reduction": {
        "display_name": "Quad Reduction", "output": "preserved_quad_lod",
        "compatible_components": ("material_baking", "visibility"),
        "backend": "recipe_only", "maturity": "experimental",
    },
    "remeshing": {
        "display_name": "Remeshing / Proxy Geometry", "output": "closed_proxy_mesh",
        "compatible_components": ("material_baking", "skinning", "visibility", "geometry_culling"),
        "backend": "recipe_only", "maturity": "experimental",
    },
    "aggregation": {
        "display_name": "Geometry Aggregation", "output": "merged_atlased_mesh",
        "compatible_components": ("material_baking",),
        "backend": "recipe_only", "maturity": "experimental",
    },
    "impostor": {
        "display_name": "Impostor", "output": "billboard_geometry",
        "compatible_components": ("material_baking", "visibility"),
        "backend": "recipe_only", "maturity": "experimental",
    },
    "occlusion_mesh": {
        "display_name": "Occlusion Mesh", "output": "silhouette_proxy",
        "compatible_components": ("geometry_culling",),
        "backend": "recipe_only", "maturity": "experimental",
    },
}

GEOMETRY_COMPONENTS: dict[str, dict[str, Any]] = {
    "material_baking": {"display_name": "Material Baking", "maturity": "authoring_preview"},
    "skinning": {"display_name": "Skinning & Bone Reduction", "maturity": "authoring_preview"},
    "visibility": {"display_name": "Visibility Weighting", "maturity": "experimental"},
    "geometry_culling": {"display_name": "Geometry Culling", "maturity": "experimental"},
}

MATERIAL_CASTERS = (
    "base_color", "normal", "roughness", "metallic", "specular", "emissive",
    "opacity", "ambient_occlusion", "displacement", "geometry_data", "vertex_color",
)

GEOMETRY_EXECUTION_MODES: dict[str, dict[str, Any]] = {
    "in_process": {"display_name": "In Process", "backend": "local", "available": True},
    "isolated_process": {"display_name": "Isolated Process", "backend": "local", "available": True},
    "distributed_grid": {"display_name": "Distributed Grid", "backend": "grid", "available": False},
    "distributed_fastbuild": {"display_name": "Distributed FASTBuild", "backend": "fastbuild", "available": False},
    "distributed_incredibuild": {"display_name": "Distributed Incredibuild", "backend": "incredibuild", "available": False},
}


def _stage(stage_id: str, processor: str, *, components: Iterable[str] = (), **settings: Any) -> dict[str, Any]:
    return {"stage_id": stage_id, "processor": processor, "enabled": True,
            "components": list(components), "settings": settings}


GEOMETRY_OPTIMIZATION_PRESETS: dict[str, dict[str, Any]] = {
    "character_balanced": {
        "description": "Four skinning-safe LODs with progressive bone reduction.",
        "stages": [
            _stage("lod1", "reduction", components=("skinning",), triangle_ratio=0.55, max_deviation=0.01),
            _stage("lod2", "reduction", components=("skinning",), triangle_ratio=0.30, max_deviation=0.03),
            _stage("lod3", "reduction", components=("skinning",), triangle_ratio=0.15, max_deviation=0.07),
        ],
        "components": {"skinning": {"preserve_weights": True, "bone_reduction": True,
                                        "preserve_bones": []}},
    },
    "character_mobile": {
        "description": "Aggressive skinned reduction and compact bone palettes for mobile.",
        "stages": [
            _stage("lod1", "reduction", components=("skinning",), triangle_ratio=0.40, max_deviation=0.02),
            _stage("lod2", "reduction", components=("skinning",), triangle_ratio=0.18, max_deviation=0.06),
            _stage("lod3", "reduction", components=("skinning",), triangle_ratio=0.07, max_deviation=0.14),
        ],
        "components": {"skinning": {"preserve_weights": True, "bone_reduction": True,
                                        "max_influences": 4, "preserve_bones": []}},
    },
    "prop_hlod": {
        "description": "Merge a prop cluster, atlas materials, then produce a proxy.",
        "stages": [_stage("aggregate", "aggregation", components=("material_baking",), merge_geometry=True),
                   _stage("proxy", "remeshing", components=("material_baking", "visibility"), on_screen_size=512, hole_filling="automatic")],
        "components": {"material_baking": {"texture_size": 2048,
                                               "casters": ["base_color", "normal", "roughness", "metallic", "ambient_occlusion"]},
                       "visibility": {"mode": "automatic"}},
    },
    "distant_impostor": {
        "description": "Billboard replacement with color, normal, opacity, and depth data.",
        "stages": [_stage("impostor", "impostor", components=("material_baking",), mode="view_cluster", views=16)],
        "components": {"material_baking": {"texture_size": 1024,
                                               "casters": ["base_color", "normal", "opacity", "geometry_data"]}},
    },
    "occluder": {
        "description": "Conservative silhouette mesh intended only for occlusion culling.",
        "stages": [_stage("occluder", "occlusion_mesh", components=("geometry_culling",), on_screen_size=256)],
        "components": {"geometry_culling": {"selection_sets": [], "mode": "outside"}},
    },
}


def geometry_optimization_preset(name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    if key not in GEOMETRY_OPTIMIZATION_PRESETS:
        raise KeyError(f"Unknown geometry optimization preset: {name}")
    result = deepcopy(GEOMETRY_OPTIMIZATION_PRESETS[key])
    result["preset"] = key
    return result


def validate_geometry_optimization_profile(properties: Mapping[str, Any]) -> list[GeometryOptimizationIssue]:
    issues: list[GeometryOptimizationIssue] = []
    stages = list(properties.get("stages") or ())
    components = dict(properties.get("components") or {})
    if not stages:
        issues.append(GeometryOptimizationIssue("error", "missing_stages", "Add at least one optimization stage."))
    seen: set[str] = set()
    for index, value in enumerate(stages):
        stage = dict(value or {})
        stage_id = str(stage.get("stage_id") or f"stage_{index}")
        if stage_id in seen:
            issues.append(GeometryOptimizationIssue("error", "duplicate_stage_id", f"Duplicate stage ID: {stage_id}", stage_id))
        seen.add(stage_id)
        processor = str(stage.get("processor") or "").casefold()
        descriptor = GEOMETRY_PROCESSORS.get(processor)
        if descriptor is None:
            issues.append(GeometryOptimizationIssue("error", "unknown_processor", f"Unknown processor: {processor or '<empty>'}", stage_id))
            continue
        settings = dict(stage.get("settings") or {})
        if processor in {"reduction", "quad_reduction"}:
            ratio = float(settings.get("triangle_ratio", 1.0))
            if not 0.0 < ratio <= 1.0:
                issues.append(GeometryOptimizationIssue("error", "invalid_triangle_ratio", "Triangle ratio must be greater than zero and at most one.", stage_id))
        if processor in {"remeshing", "occlusion_mesh"} and int(settings.get("on_screen_size", 0)) <= 0:
            issues.append(GeometryOptimizationIssue("error", "invalid_on_screen_size", "On-screen size must be a positive pixel count.", stage_id))
        requested = set(stage.get("components") or ())
        incompatible = requested - set(descriptor["compatible_components"])
        for component in sorted(incompatible):
            issues.append(GeometryOptimizationIssue("error", "incompatible_component",
                                                     f"{component} is not compatible with {processor}.", stage_id))
        if descriptor["backend"] == "recipe_only" and bool(stage.get("enabled", True)):
            issues.append(GeometryOptimizationIssue("warning", "backend_unavailable",
                                                     f"{descriptor['display_name']} is authored and cookable but has no local execution backend yet.", stage_id))
    baking = dict(components.get("material_baking") or {})
    unknown_casters = set(baking.get("casters") or ()) - set(MATERIAL_CASTERS)
    if unknown_casters:
        issues.append(GeometryOptimizationIssue("error", "unknown_material_caster",
                                                 "Unknown material casters: " + ", ".join(sorted(unknown_casters))))
    execution = dict(properties.get("execution") or {})
    mode = str(execution.get("mode") or "isolated_process").casefold()
    if mode not in GEOMETRY_EXECUTION_MODES:
        issues.append(GeometryOptimizationIssue("error", "unknown_execution_mode", f"Unknown execution mode: {mode}"))
    elif not GEOMETRY_EXECUTION_MODES[mode]["available"]:
        issues.append(GeometryOptimizationIssue("warning", "execution_backend_unavailable",
                                                 f"{GEOMETRY_EXECUTION_MODES[mode]['display_name']} is configured but no coordinator is installed."))
    if int(execution.get("workers", 1) or 1) < 1:
        issues.append(GeometryOptimizationIssue("error", "invalid_worker_count", "Worker count must be at least one."))
    return issues


def plan_geometry_optimization(properties: Mapping[str, Any]) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    components = deepcopy(dict(properties.get("components") or {}))
    for index, raw in enumerate(properties.get("stages") or ()):
        stage = deepcopy(dict(raw or {}))
        processor = str(stage.get("processor") or "").casefold()
        descriptor = GEOMETRY_PROCESSORS.get(processor, {})
        stage.setdefault("stage_id", f"stage_{index}")
        stage["processor"] = processor
        stage["execution_backend"] = descriptor.get("backend", "unavailable")
        stage["maturity"] = descriptor.get("maturity", "experimental")
        stage["output_kind"] = descriptor.get("output", "unknown")
        stages.append(stage)
    issues = validate_geometry_optimization_profile(properties)
    execution = {"mode": "isolated_process", "workers": 1, "cache": True, "retry_limit": 2,
                 "progress_events": True} | dict(properties.get("execution") or {})
    mode = str(execution["mode"]).casefold()
    return {
        "schema": "tech_connector.geometry_optimization_plan.v1",
        "source_asset_ids": list(dict.fromkeys(str(value) for value in properties.get("source_asset_ids") or () if str(value))),
        "selection_sets": deepcopy(list(properties.get("selection_sets") or ())),
        "components": components, "stages": stages,
        "execution": execution,
        "execution_backend_ready": bool(GEOMETRY_EXECUTION_MODES.get(mode, {}).get("available", False)),
        "issues": [asdict(issue) for issue in issues],
        "executable": not any(issue.severity == "error" for issue in issues),
        "fully_local": all(stage["execution_backend"] != "recipe_only" for stage in stages if stage.get("enabled", True)),
    }


def compile_geometry_optimization_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    plan = plan_geometry_optimization(properties)
    errors = [issue["message"] for issue in plan["issues"] if issue["severity"] == "error"]
    if errors:
        raise ValueError("Invalid Geometry Optimization Profile: " + "; ".join(errors))
    plan["platform"] = str(platform)
    plan["quality"] = str(quality)
    return json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "GEOMETRY_COMPONENTS", "GEOMETRY_EXECUTION_MODES", "GEOMETRY_OPTIMIZATION_PRESETS", "GEOMETRY_PROCESSORS", "MATERIAL_CASTERS",
    "GeometryOptimizationIssue", "compile_geometry_optimization_payload", "geometry_optimization_preset",
    "plan_geometry_optimization", "validate_geometry_optimization_profile",
]
