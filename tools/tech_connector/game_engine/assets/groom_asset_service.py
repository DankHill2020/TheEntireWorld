"""First-class strand groom, binding, material, LOD, and cook contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class GroomIssue:
    severity: str
    code: str
    message: str
    group: str = ""


HAIR_GEOMETRY_TYPES = ("strands", "cards", "mesh")
HAIR_BINDING_TYPES = ("rigid", "skinning", "rbf")
HAIR_SOLVERS = {
    "angular_spring": {"display_name": "Angular Spring", "maturity": "authoring_preview"},
    "cosserat_rod": {"display_name": "Cosserat Rod", "maturity": "experimental"},
    "position_based": {"display_name": "Position Based", "maturity": "authoring_preview"},
}

HAIR_MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "black_hair": {"base_color": [0.012, 0.008, 0.006], "melanin": 0.95, "melanin_redness": 0.15,
                   "roughness": 0.32, "radial_roughness": 0.42, "scatter": 0.15, "specular": 0.5},
    "brown_hair": {"base_color": [0.08, 0.03, 0.012], "melanin": 0.75, "melanin_redness": 0.35,
                   "roughness": 0.34, "radial_roughness": 0.44, "scatter": 0.2, "specular": 0.5},
    "blonde_hair": {"base_color": [0.62, 0.38, 0.12], "melanin": 0.25, "melanin_redness": 0.28,
                    "roughness": 0.38, "radial_roughness": 0.48, "scatter": 0.42, "specular": 0.48},
    "red_hair": {"base_color": [0.32, 0.055, 0.012], "melanin": 0.42, "melanin_redness": 0.86,
                 "roughness": 0.36, "radial_roughness": 0.46, "scatter": 0.28, "specular": 0.5},
    "gray_hair": {"base_color": [0.42, 0.43, 0.44], "melanin": 0.04, "melanin_redness": 0.05,
                  "roughness": 0.42, "radial_roughness": 0.52, "scatter": 0.62, "specular": 0.45},
    "fur": {"base_color": [0.12, 0.06, 0.025], "melanin": 0.68, "melanin_redness": 0.2,
            "roughness": 0.48, "radial_roughness": 0.55, "scatter": 0.35, "specular": 0.38},
}

GROOM_GROUP_PRESETS: dict[str, dict[str, Any]] = {
    "scalp": {"width_mm": 0.07, "root_scale": 1.0, "tip_scale": 0.2, "simulation": True,
              "solver": "angular_spring", "bend_stiffness": 0.05, "stretch_stiffness": 0.95, "damping": 0.08},
    "beard": {"width_mm": 0.09, "root_scale": 1.0, "tip_scale": 0.25, "simulation": True,
              "solver": "position_based", "bend_stiffness": 0.12, "stretch_stiffness": 0.98, "damping": 0.12},
    "brows": {"width_mm": 0.06, "root_scale": 1.0, "tip_scale": 0.15, "simulation": False,
              "solver": "angular_spring", "bend_stiffness": 0.5, "stretch_stiffness": 1.0, "damping": 0.2},
    "lashes": {"width_mm": 0.05, "root_scale": 1.0, "tip_scale": 0.08, "simulation": False,
               "solver": "angular_spring", "bend_stiffness": 0.8, "stretch_stiffness": 1.0, "damping": 0.25},
    "fur": {"width_mm": 0.08, "root_scale": 1.0, "tip_scale": 0.25, "simulation": True,
            "solver": "position_based", "bend_stiffness": 0.16, "stretch_stiffness": 0.95, "damping": 0.16},
}


def hair_material_preset(name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    if key not in HAIR_MATERIAL_PRESETS:
        raise KeyError(f"Unknown hair material preset: {name}")
    return {"preset": key, **deepcopy(HAIR_MATERIAL_PRESETS[key])}


def groom_group_preset(name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    if key not in GROOM_GROUP_PRESETS:
        raise KeyError(f"Unknown groom group preset: {name}")
    return {"preset": key, **deepcopy(GROOM_GROUP_PRESETS[key])}


def automatic_groom_lods(
    *, count: int = 5, include_cards: bool = True, include_mesh: bool = True,
) -> list[dict[str, Any]]:
    count = max(1, min(8, int(count)))
    lods: list[dict[str, Any]] = []
    for index in range(count):
        t = index / max(1, count - 1)
        geometry = "strands"
        if include_mesh and index == count - 1 and count >= 4:
            geometry = "mesh"
        elif include_cards and index >= max(2, math.ceil(count * 0.55)):
            geometry = "cards"
        curve = max(0.025, 0.5 ** index)
        point = max(0.15, 1.0 - t * 0.72)
        lods.append({
            "lod": index, "screen_size": round(max(0.01, 1.0 - t * 0.95), 4),
            "geometry_type": geometry, "curve_decimation": round(curve, 4),
            "vertex_decimation": round(point, 4), "angular_threshold_degrees": round(2.0 + 18.0 * t, 3),
            "thickness_scale": round(min(3.0, 1.0 / math.sqrt(curve)), 4),
            "binding_type": "skinning" if geometry != "mesh" else "rbf",
            "simulation": bool(index < max(2, count // 2)), "visible": True,
        })
    return lods


def validate_groom_properties(properties: Mapping[str, Any]) -> list[GroomIssue]:
    issues: list[GroomIssue] = []
    groups = list(properties.get("groups") or ())
    if not groups:
        issues.append(GroomIssue("error", "missing_groups", "A Groom needs at least one hair group."))
    names: set[str] = set()
    for index, raw in enumerate(groups):
        group = dict(raw or {}); name = str(group.get("name") or f"Group {index}")
        if name in names: issues.append(GroomIssue("error", "duplicate_group", f"Duplicate hair group: {name}", name))
        names.add(name)
        curves = int(group.get("curve_count", 0) or 0); points = int(group.get("point_count", 0) or 0)
        if curves <= 0: issues.append(GroomIssue("error", "missing_curves", "Hair group has no render curves.", name))
        if points < curves * 2: issues.append(GroomIssue("error", "insufficient_points", "Each render curve needs at least two points.", name))
        guides = int(group.get("guide_count", 0) or 0)
        simulation = dict(group.get("simulation") or {})
        if bool(simulation.get("enabled", False)) and guides <= 0:
            issues.append(GroomIssue("error", "missing_guides", "Simulated hair requires guide curves.", name))
        if str(simulation.get("solver") or "angular_spring") not in HAIR_SOLVERS:
            issues.append(GroomIssue("error", "unknown_solver", "Hair group uses an unknown solver.", name))
        if float(group.get("width_mm", 0.0) or 0.0) <= 0.0:
            issues.append(GroomIssue("error", "invalid_width", "Hair width must be greater than zero.", name))
    lods = list(properties.get("lods") or ())
    if not lods: issues.append(GroomIssue("error", "missing_lods", "Create at least one Groom LOD."))
    previous = float("inf")
    for raw in lods:
        lod = dict(raw or {}); screen = float(lod.get("screen_size", 0.0))
        if screen <= 0.0 or screen > previous:
            issues.append(GroomIssue("error", "invalid_lod_order", "LOD screen sizes must be positive and descend."))
        previous = screen
        if str(lod.get("geometry_type") or "") not in HAIR_GEOMETRY_TYPES:
            issues.append(GroomIssue("error", "unknown_geometry_type", "LOD geometry must be strands, cards, or mesh."))
        if str(lod.get("binding_type") or "") not in HAIR_BINDING_TYPES:
            issues.append(GroomIssue("error", "unknown_binding_type", "LOD binding must be rigid, skinning, or RBF."))
    cards = dict(properties.get("cards") or {})
    if any(str(lod.get("geometry_type")) == "cards" for lod in lods) and not cards.get("entries"):
        issues.append(GroomIssue("warning", "cards_not_built", "Card LODs are configured but card geometry has not been imported or generated."))
    return issues


def validate_groom_binding_properties(properties: Mapping[str, Any]) -> list[GroomIssue]:
    issues: list[GroomIssue] = []
    for key, label in (("groom_id", "Groom"), ("target_skeletal_mesh_id", "target Skeletal Mesh")):
        if not str(properties.get(key) or ""):
            issues.append(GroomIssue("error", f"missing_{key}", f"Select a {label}."))
    projections = list(properties.get("root_projections") or ())
    expected = int(properties.get("root_count", 0) or 0)
    if expected and len(projections) != expected:
        issues.append(GroomIssue("error", "projection_count_mismatch", "Every strand root must have a cached surface projection."))
    maximum = float(properties.get("maximum_projection_distance", 0.05) or 0.05)
    if any(float(item.get("distance", 0.0)) > maximum for item in projections):
        issues.append(GroomIssue("warning", "distant_root_projection", "Some strand roots project beyond the configured safe distance."))
    return issues


def validate_hair_material_properties(properties: Mapping[str, Any]) -> list[GroomIssue]:
    issues: list[GroomIssue] = []
    for key in ("melanin", "melanin_redness", "roughness", "radial_roughness", "scatter", "specular"):
        value = float(properties.get(key, 0.0))
        if not 0.0 <= value <= 1.0:
            issues.append(GroomIssue("error", f"invalid_{key}", f"{key.replace('_', ' ').title()} must be between zero and one."))
    return issues


def _closest_point_triangle(point, a, b, c):
    # Real-Time Collision Detection, closest point on triangle regions.
    def sub(x, y): return tuple(float(x[i]) - float(y[i]) for i in range(3))
    def add(x, y): return tuple(float(x[i]) + float(y[i]) for i in range(3))
    def mul(x, scale): return tuple(float(v) * scale for v in x)
    def dot(x, y): return sum(float(x[i]) * float(y[i]) for i in range(3))
    ab, ac, ap = sub(b, a), sub(c, a), sub(point, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0: return tuple(a), (1.0, 0.0, 0.0)
    bp = sub(point, b); d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3: return tuple(b), (0.0, 1.0, 0.0)
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3); return add(a, mul(ab, v)), (1.0 - v, v, 0.0)
    cp = sub(point, c); d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6: return tuple(c), (0.0, 0.0, 1.0)
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6); return add(a, mul(ac, w)), (1.0 - w, 0.0, w)
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6)); return add(b, mul(sub(c, b), w)), (0.0, 1.0 - w, w)
    denominator = 1.0 / (va + vb + vc); v, w = vb * denominator, vc * denominator
    return add(add(a, mul(ab, v)), mul(ac, w)), (1.0 - v - w, v, w)


def project_groom_roots(
    roots: Sequence[Sequence[float]], vertices: Sequence[Sequence[float]], triangles: Sequence[Sequence[int]],
) -> list[dict[str, Any]]:
    if not vertices or not triangles:
        raise ValueError("Target binding mesh needs vertices and triangles.")
    result: list[dict[str, Any]] = []
    for root_index, root in enumerate(roots):
        if len(root) != 3: raise ValueError(f"Root {root_index} is not a 3D point.")
        best = None
        for face_index, face in enumerate(triangles):
            if len(face) != 3 or any(int(index) < 0 or int(index) >= len(vertices) for index in face):
                raise ValueError(f"Triangle {face_index} has invalid vertex indices.")
            point, barycentric = _closest_point_triangle(root, vertices[int(face[0])], vertices[int(face[1])], vertices[int(face[2])])
            distance = math.dist(tuple(float(value) for value in root), point)
            if best is None or distance < best[0]: best = (distance, face_index, barycentric, point)
        assert best is not None
        result.append({"root": root_index, "triangle": best[1], "barycentric": [round(value, 9) for value in best[2]],
                       "surface_position": [round(value, 9) for value in best[3]], "distance": round(best[0], 9)})
    return result


def _compile(type_id: str, properties: Mapping[str, Any], validator, *, platform: str, quality: str) -> bytes:
    issues = validator(properties); errors = [issue.message for issue in issues if issue.severity == "error"]
    if errors: raise ValueError(f"Invalid {type_id}: " + "; ".join(errors))
    payload = {"schema": f"tech_connector.{type_id}.v1", "platform": str(platform), "quality": str(quality),
               "properties": deepcopy(dict(properties)), "diagnostics": [asdict(issue) for issue in issues]}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compile_groom_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    return _compile("groom_runtime", properties, validate_groom_properties, platform=platform, quality=quality)


def compile_groom_binding_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    return _compile("groom_binding_runtime", properties, validate_groom_binding_properties, platform=platform, quality=quality)


def compile_hair_material_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    return _compile("hair_material_runtime", properties, validate_hair_material_properties, platform=platform, quality=quality)


__all__ = [
    "GROOM_GROUP_PRESETS", "HAIR_BINDING_TYPES", "HAIR_GEOMETRY_TYPES", "HAIR_MATERIAL_PRESETS", "HAIR_SOLVERS",
    "GroomIssue", "automatic_groom_lods", "compile_groom_binding_payload", "compile_groom_payload",
    "compile_hair_material_payload", "groom_group_preset", "hair_material_preset", "project_groom_roots",
    "validate_groom_binding_properties", "validate_groom_properties", "validate_hair_material_properties",
]
