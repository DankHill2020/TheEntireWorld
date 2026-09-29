"""Authoring contracts for skinned cloth assets and reusable fabric materials."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping, Sequence


CLOTH_MAPS = (
    "skin_simulation", "animation_drive", "max_distance", "backstop_distance",
    "backstop_radius", "pin", "mass_scale", "stretch_stiffness",
    "bend_stiffness", "collision_thickness", "drag",
)

FABRIC_PRESETS: dict[str, dict[str, float]] = {
    "silk": {"density": 0.10, "damping": 0.012, "friction": 0.18, "warp_stiffness": 0.45, "weft_stiffness": 0.36, "shear_stiffness": 0.18, "bend_stiffness": 0.08, "thickness": 0.00018, "drag": 0.05, "lift": 0.02},
    "cotton": {"density": 0.20, "damping": 0.025, "friction": 0.45, "warp_stiffness": 0.80, "weft_stiffness": 0.68, "shear_stiffness": 0.42, "bend_stiffness": 0.35, "thickness": 0.00060, "drag": 0.035, "lift": 0.01},
    "denim": {"density": 0.40, "damping": 0.040, "friction": 0.55, "warp_stiffness": 0.94, "weft_stiffness": 0.88, "shear_stiffness": 0.66, "bend_stiffness": 0.75, "thickness": 0.00090, "drag": 0.02, "lift": 0.0},
    "wool": {"density": 0.32, "damping": 0.050, "friction": 0.62, "warp_stiffness": 0.62, "weft_stiffness": 0.58, "shear_stiffness": 0.50, "bend_stiffness": 0.55, "thickness": 0.00120, "drag": 0.06, "lift": 0.01},
    "leather": {"density": 0.55, "damping": 0.060, "friction": 0.70, "warp_stiffness": 0.97, "weft_stiffness": 0.95, "shear_stiffness": 0.86, "bend_stiffness": 0.90, "thickness": 0.00150, "drag": 0.015, "lift": 0.0},
    "rubber": {"density": 0.80, "damping": 0.090, "friction": 0.88, "warp_stiffness": 0.72, "weft_stiffness": 0.72, "shear_stiffness": 0.68, "bend_stiffness": 0.62, "thickness": 0.00100, "drag": 0.025, "lift": 0.0},
    "nylon": {"density": 0.12, "damping": 0.018, "friction": 0.22, "warp_stiffness": 0.70, "weft_stiffness": 0.66, "shear_stiffness": 0.30, "bend_stiffness": 0.18, "thickness": 0.00025, "drag": 0.045, "lift": 0.025},
    "canvas": {"density": 0.48, "damping": 0.045, "friction": 0.58, "warp_stiffness": 0.91, "weft_stiffness": 0.86, "shear_stiffness": 0.65, "bend_stiffness": 0.72, "thickness": 0.00110, "drag": 0.025, "lift": 0.0},
    "burlap": {"density": 0.36, "damping": 0.055, "friction": 0.72, "warp_stiffness": 0.60, "weft_stiffness": 0.52, "shear_stiffness": 0.35, "bend_stiffness": 0.40, "thickness": 0.00130, "drag": 0.055, "lift": 0.0},
    "chainmail": {"density": 2.80, "damping": 0.035, "friction": 0.48, "warp_stiffness": 0.28, "weft_stiffness": 0.28, "shear_stiffness": 0.12, "bend_stiffness": 0.08, "thickness": 0.00300, "drag": 0.01, "lift": 0.0},
}


@dataclass(frozen=True)
class ClothAuthoringIssue:
    severity: str
    code: str
    message: str
    fix: str = ""


@dataclass(frozen=True)
class ClothAutoSetupReceipt:
    vertex_count: int
    fixed_vertices: tuple[int, ...]
    transition_vertices: tuple[int, ...]
    property_maps: dict[str, list[float]]
    preserved_imported_skinning: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fabric_preset(name: str) -> dict[str, Any]:
    key = str(name).strip().casefold()
    if key not in FABRIC_PRESETS:
        raise KeyError(f"Unknown fabric preset: {name}")
    return {"preset": key, **FABRIC_PRESETS[key]}


def automatic_cloth_maps(
    vertex_count: int,
    *,
    fixed_vertices: Iterable[int] = (),
    transition_vertices: Mapping[int, float] | None = None,
    max_distance: float = 1.0,
) -> ClothAutoSetupReceipt:
    """Create a reversible starting mask without modifying imported bone weights."""
    count = int(vertex_count)
    if count <= 0:
        raise ValueError("Cloth setup requires at least one vertex.")
    if float(max_distance) < 0.0:
        raise ValueError("Maximum distance cannot be negative.")
    fixed = tuple(sorted({int(value) for value in fixed_vertices}))
    if any(index < 0 or index >= count for index in fixed):
        raise IndexError("A fixed cloth vertex is outside the mesh vertex range.")
    transitions = {int(index): float(value) for index, value in dict(transition_vertices or {}).items()}
    if any(index < 0 or index >= count for index in transitions):
        raise IndexError("A transition cloth vertex is outside the mesh vertex range.")
    if any(not 0.0 <= value <= 1.0 for value in transitions.values()):
        raise ValueError("Skin-to-simulation transition values must be between zero and one.")
    influence = [1.0] * count
    for index in fixed:
        influence[index] = 0.0
    for index, value in transitions.items():
        influence[index] = value
    maps = {
        "skin_simulation": influence,
        "animation_drive": [1.0 - value for value in influence],
        "max_distance": [float(max_distance) * value for value in influence],
    }
    return ClothAutoSetupReceipt(count, fixed, tuple(sorted(transitions)), maps)


def validate_cloth_properties(properties: Mapping[str, Any], *, vertex_count: int | None = None) -> tuple[ClothAuthoringIssue, ...]:
    values = dict(properties or {})
    issues: list[ClothAuthoringIssue] = []
    if not values.get("source_mesh_id"):
        issues.append(ClothAuthoringIssue("error", "missing_source_mesh", "Choose a skinned source mesh.", "Assign Source Skeletal Mesh."))
    if not values.get("skin_binding_id"):
        issues.append(ClothAuthoringIssue("error", "missing_skin_binding", "The garment has no imported skin binding.", "Import or explicitly transfer skinning."))
    if values.get("preserve_imported_skinning") is not True:
        issues.append(ClothAuthoringIssue("error", "skinning_not_preserved", "Cloth painting must not overwrite imported bone weights.", "Enable Preserve Imported Skinning."))
    maps = dict(values.get("property_maps") or {})
    for name, samples in maps.items():
        if name not in CLOTH_MAPS:
            issues.append(ClothAuthoringIssue("warning", "unknown_map", f"Unknown cloth map '{name}'."))
            continue
        if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
            issues.append(ClothAuthoringIssue("error", "invalid_map", f"Cloth map '{name}' must contain numeric vertex samples."))
            continue
        if vertex_count is not None and len(samples) != int(vertex_count):
            issues.append(ClothAuthoringIssue("error", "map_size", f"Cloth map '{name}' has {len(samples)} values; expected {vertex_count}.", "Remap maps to the current topology."))
    if "skin_simulation" not in maps:
        issues.append(ClothAuthoringIssue("warning", "missing_simulation_map", "No Skin ↔ Simulation map is authored; the garment defaults to fully simulated.", "Run Auto Setup or paint Skin ↔ Simulation."))
    return tuple(issues)


def compile_cloth_payload(properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    """Compile deterministic runtime cloth data while retaining the source skin binding."""
    values = dict(properties or {})
    errors = [issue.message for issue in validate_cloth_properties(values) if issue.severity == "error"]
    if errors:
        raise ValueError("Cloth cannot be cooked: " + "; ".join(errors))
    payload = {
        "schema": "tech_connector.cooked_cloth.v1",
        "platform": str(platform),
        "quality": str(quality),
        "source_mesh_id": str(values["source_mesh_id"]),
        "skin_binding_id": str(values["skin_binding_id"]),
        "fabric_material_id": str(values.get("fabric_material_id") or ""),
        "quality_profile": str(values.get("quality_profile") or "realtime"),
        "property_maps": dict(values.get("property_maps") or {}),
        "seams": list(values.get("seams") or ()),
        "collision_layers": list(values.get("collision_layers") or ()),
        "lods": list(values.get("lods") or ()),
        "preserve_imported_skinning": True,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "CLOTH_MAPS", "FABRIC_PRESETS", "ClothAuthoringIssue", "ClothAutoSetupReceipt",
    "automatic_cloth_maps", "compile_cloth_payload", "fabric_preset", "validate_cloth_properties",
]
