"""Artist-facing secondary-motion presets layered over portable skinning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tech_connector.game_engine.deformation.flesh import FleshDeformerSettings, attach_flesh_deformer
from tech_connector.game_engine.deformation.jiggle import JiggleDeformerSettings, attach_jiggle_deformer
from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap


@dataclass(frozen=True)
class SecondaryMotionPreset:
    preset_id: str
    label: str
    description: str
    jiggle: JiggleDeformerSettings | None = None
    flesh: FleshDeformerSettings | None = None
    suggested_regions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id, "label": self.label, "description": self.description,
            "jiggle": asdict(self.jiggle) if self.jiggle else None,
            "flesh": asdict(self.flesh) if self.flesh else None,
            "suggested_regions": list(self.suggested_regions),
        }


SECONDARY_MOTION_PRESETS: dict[str, SecondaryMotionPreset] = {
    "subtle_skin": SecondaryMotionPreset(
        "subtle_skin", "Subtle Skin", "Tight, quickly settling surface follow-through.",
        JiggleDeformerSettings(stiffness=150, damping=25, max_offset=0.025, follow=0.9, substeps=3),
        suggested_regions=("face", "neck", "limbs"),
    ),
    "soft_tissue": SecondaryMotionPreset(
        "soft_tissue", "Soft Tissue", "Collision-aware skin, fat, and muscle surface motion.",
        JiggleDeformerSettings(stiffness=95, damping=17, max_offset=0.12, follow=0.78, substeps=3),
        FleshDeformerSettings(stiffness=125, damping=21, shape_stiffness=28, max_offset=0.12),
        ("torso", "upper arms", "thighs"),
    ),
    "belly_chest": SecondaryMotionPreset(
        "belly_chest", "Belly / Chest", "Heavier soft tissue with controlled vertical and lateral travel.",
        JiggleDeformerSettings(stiffness=58, damping=12, mass=1.35, max_offset=0.22, follow=0.66,
                              axis_weights=(1.0, 0.75, 1.0), substeps=4),
        FleshDeformerSettings(stiffness=90, damping=17, shape_stiffness=24, volume_preservation=0.78,
                             max_offset=0.2, substeps=5),
        ("abdomen", "chest", "flanks"),
    ),
    "face_flesh": SecondaryMotionPreset(
        "face_flesh", "Facial Soft Tissue", "Small-scale cheek, lip, brow, and under-chin response.",
        JiggleDeformerSettings(stiffness=175, damping=27, max_offset=0.035, follow=0.92, substeps=4,
                              collision_radius=0.002),
        FleshDeformerSettings(stiffness=180, damping=28, shape_stiffness=38, volume_preservation=0.82,
                             collision_radius=0.002, max_offset=0.04, substeps=5),
        ("cheeks", "lips", "brow", "under chin"),
    ),
    "cartilage": SecondaryMotionPreset(
        "cartilage", "Cartilage", "Springy, low-travel response for noses, ears, and flexible plates.",
        JiggleDeformerSettings(stiffness=125, damping=11, mass=0.65, max_offset=0.08, follow=0.86,
                              restitution=0.14, substeps=3),
        suggested_regions=("ears", "nose", "fins", "plates"),
    ),
    "ears_tendrils": SecondaryMotionPreset(
        "ears_tendrils", "Ears / Tendrils", "Readable delayed overlap for long, light appendages.",
        JiggleDeformerSettings(stiffness=42, damping=7.5, mass=0.7, max_offset=0.4, follow=0.58,
                              max_velocity=12, substeps=4),
        suggested_regions=("long ears", "antennae", "whiskers", "tendrils"),
    ),
    "tail_overlap": SecondaryMotionPreset(
        "tail_overlap", "Tail Overlap", "Stable broad secondary arcs for tails and trunk-like parts.",
        JiggleDeformerSettings(stiffness=68, damping=10, mass=1.1, max_offset=0.55, follow=0.64,
                              max_velocity=15, substeps=4),
        suggested_regions=("tails", "trunks", "tentacles"),
    ),
    "muscle_follow": SecondaryMotionPreset(
        "muscle_follow", "Muscle Follow-through", "Tight inertial response layered over muscle-driven skin.",
        JiggleDeformerSettings(stiffness=165, damping=22, mass=1.15, max_offset=0.065, follow=0.88,
                              axis_weights=(1.0, 0.8, 1.0), substeps=4),
        FleshDeformerSettings(stiffness=155, damping=24, shape_stiffness=42, volume_preservation=0.88,
                             max_offset=0.075, substeps=5),
        ("pectorals", "deltoids", "biceps", "quadriceps", "calves"),
    ),
    "stylized_goop": SecondaryMotionPreset(
        "stylized_goop", "Stylized Goop", "Loose, bouncy deformation for slime and gelatinous characters.",
        JiggleDeformerSettings(stiffness=28, damping=5.5, mass=1.4, max_offset=0.5, follow=0.48,
                              restitution=0.3, friction=0.12, max_velocity=10, substeps=5),
        FleshDeformerSettings(stiffness=48, damping=8, shape_stiffness=12, volume_preservation=0.93,
                             restitution=0.2, friction=0.15, max_offset=0.42, substeps=6),
        ("slime", "jello", "goop creatures"),
    ),
}


def secondary_motion_preset(preset_id: str) -> SecondaryMotionPreset:
    key = str(preset_id).strip().lower()
    if key not in SECONDARY_MOTION_PRESETS:
        raise KeyError(f"Unknown secondary-motion preset: {preset_id}")
    return SECONDARY_MOTION_PRESETS[key]


def attach_secondary_motion_preset(rig_graph: Any, skin_id: str, mesh_id: str,
                                   influence_map: DeformationWeightMap, preset_id: str) -> list[str]:
    """Attach an editable preset stack while retaining authoritative skin weights."""
    skin = (getattr(rig_graph, "skins", {}) or {}).get(str(skin_id))
    if skin is None:
        raise KeyError(f"Secondary motion must start from a skin cluster: {skin_id}")
    preset = secondary_motion_preset(preset_id)
    identifiers: list[str] = []
    if preset.jiggle:
        identifiers.append(attach_jiggle_deformer(rig_graph, skin_id, mesh_id, influence_map,
                                                  settings=preset.jiggle))
    if preset.flesh:
        identifiers.append(attach_flesh_deformer(rig_graph, skin_id, mesh_id, influence_map,
                                                 settings=preset.flesh))
    skin.setdefault("secondary_motion_presets", []).append({
        "schema": "tech_connector.secondary_motion_preset.v1", "preset_id": preset.preset_id,
        "label": preset.label, "deformer_ids": list(identifiers), "canonical_skin_preserved": True,
        "editable": True,
    })
    return identifiers


__all__ = ["SECONDARY_MOTION_PRESETS", "SecondaryMotionPreset",
           "attach_secondary_motion_preset", "secondary_motion_preset"]
