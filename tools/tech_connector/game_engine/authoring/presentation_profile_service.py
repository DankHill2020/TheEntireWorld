from __future__ import annotations

"""Project-owned presentation profiles independent from gameplay and simulation."""

from dataclasses import asdict, dataclass, field
from typing import Any


PRESENTATION_PROFILE_SCHEMA = "tech_connector.presentation_profile.v1"
DIMENSIONALITIES = ("2d", "2.5d", "3d", "mixed")

VISUAL_STYLE_LABELS = {
    "pixel_8bit": "8-Bit Pixel Art",
    "pixel_16bit": "16-Bit Pixel Art",
    "vector_flat": "Clean Vector",
    "hand_painted": "Hand Painted",
    "toon": "Toon / Cel Shaded",
    "low_poly": "Low Poly",
    "retro_3d": "Retro 3D",
    "stylized_pbr": "Stylized Real-Time",
    "photoreal": "Photoreal",
    "hyperreal": "Hyper Real",
}

_STYLE_ALIASES = {
    "8bit": "pixel_8bit", "8-bit": "pixel_8bit", "8 bit": "pixel_8bit", "pixel art": "pixel_8bit",
    "16bit": "pixel_16bit", "16-bit": "pixel_16bit", "16 bit": "pixel_16bit",
    "cel": "toon", "cel shaded": "toon", "cartoon": "toon",
    "realistic": "photoreal", "hyper realistic": "hyperreal", "hyper-realistic": "hyperreal",
    "ps1": "retro_3d", "psx": "retro_3d",
}

_DIMENSION_ALIASES = {
    "2": "2d", "2d": "2d", "flat": "2d",
    "2.5": "2.5d", "2.5d": "2.5d", "two and a half d": "2.5d",
    "3": "3d", "3d": "3d", "full 3d": "3d",
    "mixed": "mixed", "hybrid": "mixed",
}


@dataclass(frozen=True)
class ResolutionPolicy:
    base_width: int = 1920
    base_height: int = 1080
    integer_scaling: bool = False
    pixel_snap: bool = False
    subpixel_camera: bool = True
    palette_limit: int = 0
    dithering: str = "none"
    texture_filter: str = "linear"


@dataclass(frozen=True)
class CameraPresentationPolicy:
    projection: str = "perspective"
    billboard_mode: str = "none"
    depth_sort: str = "opaque_then_transparent"
    parallax_layers: bool = False
    fixed_pixel_density: bool = False


@dataclass
class PresentationProfile:
    profile_id: str
    visual_style: str
    dimensionality: str = "3d"
    presentation_fidelity: float = 0.75
    geometry: dict[str, Any] = field(default_factory=dict)
    materials: dict[str, Any] = field(default_factory=dict)
    lighting: dict[str, Any] = field(default_factory=dict)
    animation: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)
    ui: dict[str, Any] = field(default_factory=dict)
    post_process: dict[str, Any] = field(default_factory=dict)
    camera: CameraPresentationPolicy = field(default_factory=CameraPresentationPolicy)
    resolution: ResolutionPolicy = field(default_factory=ResolutionPolicy)
    source_preservation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PRESENTATION_PROFILE_SCHEMA,
            "profile_id": self.profile_id,
            "visual_style": self.visual_style,
            "dimensionality": self.dimensionality,
            "presentation_fidelity": _clamp01(self.presentation_fidelity),
            "geometry": dict(self.geometry),
            "materials": dict(self.materials),
            "lighting": dict(self.lighting),
            "animation": dict(self.animation),
            "effects": dict(self.effects),
            "ui": dict(self.ui),
            "post_process": dict(self.post_process),
            "camera": asdict(self.camera),
            "resolution": asdict(self.resolution),
            "source_preservation": dict(self.source_preservation),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PresentationProfile":
        if str(data.get("schema") or "") != PRESENTATION_PROFILE_SCHEMA:
            raise ValueError("Unsupported presentation-profile schema.")
        dimensionality = str(data.get("dimensionality") or "3d")
        if dimensionality not in DIMENSIONALITIES:
            raise ValueError(f"Unsupported presentation dimensionality: {dimensionality}")
        return cls(
            profile_id=str(data.get("profile_id") or "presentation"),
            visual_style=str(data.get("visual_style") or "stylized_pbr"),
            dimensionality=dimensionality,
            presentation_fidelity=_clamp01(data.get("presentation_fidelity", 0.75)),
            geometry=dict(data.get("geometry") or {}),
            materials=dict(data.get("materials") or {}),
            lighting=dict(data.get("lighting") or {}),
            animation=dict(data.get("animation") or {}),
            effects=dict(data.get("effects") or {}),
            ui=dict(data.get("ui") or {}),
            post_process=dict(data.get("post_process") or {}),
            camera=CameraPresentationPolicy(**dict(data.get("camera") or {})),
            resolution=ResolutionPolicy(**dict(data.get("resolution") or {})),
            source_preservation=dict(data.get("source_preservation") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "pixel_8bit": {
        "fidelity": 0.35,
        "resolution": ResolutionPolicy(320, 180, True, True, False, 32, "ordered", "nearest"),
        "materials": {"model": "indexed_palette", "shading": "unlit_or_ramp", "normal_maps": False},
        "lighting": {"mode": "palette_ramp", "dynamic_lights": 4, "shadows": "blob_or_hard"},
        "animation": {"sampling": "stepped", "display_fps": 12, "subpixel_motion": False},
        "effects": {"representation": "pixel_particles", "soft_particles": False, "palette_quantize": True},
        "post_process": {"palette_quantization": True, "crt_optional": True, "temporal_aa": False},
    },
    "pixel_16bit": {
        "fidelity": 0.45,
        "resolution": ResolutionPolicy(426, 240, True, True, False, 256, "ordered", "nearest"),
        "materials": {"model": "extended_palette", "shading": "ramp", "normal_maps": "optional_sprite_normals"},
        "lighting": {"mode": "ramp_or_sprite_normal", "dynamic_lights": 8, "shadows": "hard"},
        "animation": {"sampling": "stepped", "display_fps": 15, "subpixel_motion": False},
        "effects": {"representation": "pixel_particles", "palette_quantize": True},
        "post_process": {"palette_quantization": True, "crt_optional": True, "temporal_aa": False},
    },
    "vector_flat": {
        "fidelity": 0.6,
        "materials": {"model": "flat_vector", "shading": "unlit", "edge_aa": "analytic"},
        "lighting": {"mode": "graphic", "dynamic_lights": 0, "shadows": "graphic"},
        "animation": {"sampling": "continuous", "deformation": "vector_or_skeletal"},
        "effects": {"representation": "shape_particles"},
        "post_process": {"temporal_aa": False, "color_management": "display_referred"},
    },
    "hand_painted": {
        "fidelity": 0.7,
        "materials": {"model": "painted_maps", "shading": "soft_ramp", "brush_detail": True},
        "lighting": {"mode": "baked_plus_key", "dynamic_lights": 8, "shadows": "soft_stylized"},
        "animation": {"sampling": "continuous", "deformation": "skeletal_or_frame"},
        "effects": {"representation": "painted_flipbook_or_particles"},
        "post_process": {"color_management": "art_directed", "paper_grain_optional": True},
    },
    "toon": {
        "fidelity": 0.75,
        "materials": {"model": "toon_pbr_hybrid", "shading": "bands", "outlines": True},
        "lighting": {"mode": "clustered_ramp", "dynamic_lights": 32, "shadows": "art_directed"},
        "animation": {"sampling": "continuous_or_stepped", "deformation": "skeletal"},
        "effects": {"representation": "toon_particles_and_meshes"},
        "post_process": {"outlines": True, "temporal_aa": "optional"},
    },
    "low_poly": {
        "fidelity": 0.55,
        "materials": {"model": "simple_pbr_or_vertex_color", "shading": "flat_or_smooth"},
        "lighting": {"mode": "baked_or_clustered", "dynamic_lights": 16, "shadows": "medium"},
        "animation": {"sampling": "continuous", "deformation": "skeletal"},
        "effects": {"representation": "simple_mesh_and_particles"},
        "post_process": {"temporal_aa": "optional", "color_management": "filmic_or_display"},
    },
    "retro_3d": {
        "fidelity": 0.4,
        "resolution": ResolutionPolicy(640, 360, True, True, False, 0, "ordered", "nearest"),
        "geometry": {"representation": "quantized_mesh", "vertex_jitter": "optional", "affine_uv": "optional"},
        "materials": {"model": "texture_or_vertex_color", "shading": "vertex_lit"},
        "lighting": {"mode": "vertex", "dynamic_lights": 8, "shadows": "blob_or_hard"},
        "animation": {"sampling": "stepped", "display_fps": 15},
        "effects": {"representation": "billboards_and_simple_meshes"},
        "post_process": {"color_depth": "configurable", "temporal_aa": False},
    },
    "stylized_pbr": {
        "fidelity": 0.8,
        "materials": {"model": "art_directed_pbr", "shading": "customizable"},
        "lighting": {"mode": "clustered", "dynamic_lights": 128, "shadows": "scalable"},
        "animation": {"sampling": "continuous", "deformation": "skeletal_and_vertex"},
        "effects": {"representation": "particles_meshes_volumes"},
        "post_process": {"color_management": "filmic", "temporal_aa": "optional"},
    },
    "photoreal": {
        "fidelity": 0.95,
        "materials": {"model": "openpbr_materialx", "shading": "physically_based", "virtual_textures": True},
        "lighting": {"mode": "clustered_gi", "dynamic_lights": 512, "shadows": "virtual_or_ray_traced"},
        "animation": {"sampling": "continuous", "deformation": "high_precision_skeletal_and_vertex"},
        "effects": {"representation": "volumetric_particles_meshes_fluids"},
        "post_process": {"color_management": "aces", "temporal_aa": True, "motion_blur": "physical"},
    },
    "hyperreal": {
        "fidelity": 1.0,
        "materials": {"model": "spectral_openpbr", "shading": "physically_based", "microgeometry": True, "virtual_textures": True},
        "lighting": {"mode": "ray_traced_gi", "dynamic_lights": 1024, "shadows": "ray_traced"},
        "animation": {"sampling": "continuous", "deformation": "muscle_skin_cloth_coupled", "motion_vectors": True},
        "effects": {"representation": "spectral_volumes_particles_fluids", "deep_compositing": True},
        "post_process": {"color_management": "aces", "temporal_aa": True, "path_trace_reference": True},
    },
}


def create_presentation_profile(
    profile_id: str,
    visual_style: str,
    *,
    dimensionality: str = "3d",
    overrides: dict[str, Any] | None = None,
) -> PresentationProfile:
    style_input = str(visual_style).strip().lower().replace("_", " ")
    style = _STYLE_ALIASES.get(style_input, style_input.replace(" ", "_"))
    if style not in _STYLE_PRESETS:
        raise KeyError(f"Unknown visual style: {visual_style}")
    dimension_input = str(dimensionality).strip().lower()
    dimension = _DIMENSION_ALIASES.get(dimension_input, dimension_input)
    if dimension not in DIMENSIONALITIES:
        raise KeyError(f"Unknown dimensionality: {dimensionality}")
    preset = _STYLE_PRESETS[style]
    geometry = {"representation": "mesh", "lod": "adaptive", "source_asset": "preserve"}
    camera = CameraPresentationPolicy()
    if dimension == "2d":
        geometry.update({"representation": "sprites_or_vectors", "depth": "layers"})
        camera = CameraPresentationPolicy("orthographic", "none", "explicit_layers", False, True)
    elif dimension == "2.5d":
        geometry.update({"representation": "layered_cards_meshes_and_sprites", "depth": "world", "sprite_facing": "authored"})
        camera = CameraPresentationPolicy("orthographic_or_perspective", "authored_axis", "stable_depth_then_material", True, style.startswith("pixel_"))
    elif dimension == "mixed":
        geometry.update({"representation": "sprites_vectors_cards_and_meshes", "depth": "world_and_ui"})
        camera = CameraPresentationPolicy("per_view", "authored_axis", "stable_depth_then_material", True, style.startswith("pixel_"))
    geometry.update(dict(preset.get("geometry") or {}))
    resolution = preset.get("resolution") or ResolutionPolicy()
    profile = PresentationProfile(
        profile_id=str(profile_id),
        visual_style=style,
        dimensionality=dimension,
        presentation_fidelity=float(preset.get("fidelity", 0.75)),
        geometry=geometry,
        materials=dict(preset.get("materials") or {}),
        lighting=dict(preset.get("lighting") or {}),
        animation=dict(preset.get("animation") or {}),
        effects=dict(preset.get("effects") or {}),
        ui={"scale_mode": "resolution_independent", "safe_area": True, "style_inherits_world": False},
        post_process=dict(preset.get("post_process") or {}),
        camera=camera,
        resolution=resolution,
        source_preservation={
            "keep_highest_fidelity_source": True,
            "compile_style_variants": True,
            "non_destructive": True,
            "switchable_at_runtime": True,
        },
    )
    _apply_overrides(profile, dict(overrides or {}))
    return profile


def compile_presentation_plan(
    profile: PresentationProfile,
    *,
    target: str = "desktop",
    viewport_size: tuple[int, int] = (1920, 1080),
) -> dict[str, Any]:
    target_key = str(target).lower()
    target_scale = {"mobile": 0.5, "web": 0.65, "vr": 0.7, "console": 0.9, "desktop": 1.0, "cinematic": 2.0}.get(target_key, 1.0)
    pixel_style = profile.visual_style.startswith("pixel_") or profile.visual_style == "retro_3d"
    base = (profile.resolution.base_width, profile.resolution.base_height)
    viewport = (max(1, int(viewport_size[0])), max(1, int(viewport_size[1])))
    integer_scale = max(1, min(viewport[0] // max(1, base[0]), viewport[1] // max(1, base[1]))) if profile.resolution.integer_scaling else 1
    internal_resolution = (
        base if profile.resolution.integer_scaling
        else (max(1, round(viewport[0] * target_scale)), max(1, round(viewport[1] * target_scale)))
    )
    passes = ["visibility", "geometry", "materials", "lighting", "effects", "ui", "present"]
    if profile.materials.get("outlines") or profile.post_process.get("outlines"):
        passes.insert(-2, "outlines")
    if profile.lighting.get("mode") in {"ray_traced_gi", "clustered_gi"}:
        passes.insert(-2, "global_illumination")
    unavailable_preview_features: list[str] = []
    if profile.visual_style == "photoreal":
        unavailable_preview_features.extend(("production global illumination", "production virtual shadows"))
    elif profile.visual_style == "hyperreal":
        unavailable_preview_features.extend(("spectral materials", "ray-traced global illumination", "coupled muscle/skin/cloth rendering"))
    return {
        "schema": "tech_connector.presentation_compile_plan.v1",
        "profile": profile.to_dict(),
        "target": target_key,
        "viewport_size": list(viewport),
        "internal_resolution": list(internal_resolution),
        "integer_present_scale": integer_scale,
        "render_passes": passes,
        "asset_representations": _asset_representations(profile),
        "shader_family": str(profile.materials.get("model") or "custom"),
        "camera": asdict(profile.camera),
        "animation": dict(profile.animation),
        "effects": dict(profile.effects),
        "budgets": {
            "presentation_scale": target_scale,
            "dynamic_lights": max(0, round(float(profile.lighting.get("dynamic_lights", 0)) * target_scale)),
            "texture_filter": profile.resolution.texture_filter,
            "pixel_exact": pixel_style and profile.resolution.pixel_snap,
        },
        "gameplay_contract": "unchanged",
        "simulation_contract": "unchanged",
        "source_assets": "preserved",
        "viewport_preview": {
            "status": "reference" if unavailable_preview_features else "interactive",
            "backend": "TC GPU material preview" if profile.visual_style not in {"pixel_8bit", "pixel_16bit", "retro_3d", "toon", "vector_flat"} else "TC pixel/stylized CPU preview",
            "unavailable_features": unavailable_preview_features,
        },
    }


def validate_presentation_profile(profile: PresentationProfile, game_experience: Any = None) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if profile.visual_style.startswith("pixel_"):
        if not profile.resolution.integer_scaling or profile.resolution.texture_filter != "nearest":
            issues.append({"severity": "warning", "code": "pixel_sampling", "message": "Pixel styles should use integer scaling and nearest filtering for stable pixels."})
        if profile.resolution.palette_limit <= 0:
            issues.append({"severity": "warning", "code": "pixel_palette", "message": "Pixel style has no authored palette limit."})
    if profile.dimensionality == "2.5d":
        if not profile.camera.parallax_layers:
            issues.append({"severity": "warning", "code": "parallax_disabled", "message": "2.5D presentation has no parallax-layer policy."})
        if "depth" not in profile.geometry:
            issues.append({"severity": "error", "code": "depth_policy_missing", "message": "2.5D presentation requires an explicit world-depth policy."})
    if profile.visual_style in {"photoreal", "hyperreal"} and "pbr" not in str(profile.materials.get("model", "")):
        issues.append({"severity": "error", "code": "physical_materials_missing", "message": "Realistic presentation requires a physically based material model."})
    simulation_fidelity = getattr(getattr(game_experience, "axes", None), "simulation_fidelity", None)
    return {
        "schema": "tech_connector.presentation_validation.v1",
        "profile_id": profile.profile_id,
        "valid": not any(row["severity"] == "error" for row in issues),
        "issues": issues,
        "independence": {
            "presentation_fidelity": profile.presentation_fidelity,
            "simulation_fidelity": simulation_fidelity,
            "coupled": False,
        },
    }


def available_visual_styles() -> tuple[str, ...]:
    return tuple(sorted(_STYLE_PRESETS))


def presentation_controls(profile: PresentationProfile) -> list[dict[str, Any]]:
    """Return friendly controls; renderer vocabulary stays out of the default UX."""
    return [
        {
            "key": "visual_style",
            "label": "Visual Style",
            "description": "Choose how the game looks without changing its rules or simulation.",
            "kind": "choice",
            "value": profile.visual_style,
            "display_value": VISUAL_STYLE_LABELS.get(profile.visual_style, profile.visual_style),
            "choices": [{"value": key, "label": VISUAL_STYLE_LABELS[key]} for key in available_visual_styles()],
        },
        {
            "key": "world_layout",
            "label": "World Layout",
            "description": "Choose a flat 2D world, layered 2.5D space, full 3D, or a per-view mixture.",
            "kind": "choice",
            "value": profile.dimensionality,
            "choices": [
                {"value": "2d", "label": "2D"},
                {"value": "2.5d", "label": "2.5D"},
                {"value": "3d", "label": "3D"},
                {"value": "mixed", "label": "Mixed"},
            ],
        },
        {
            "key": "visual_detail",
            "label": "Visual Detail",
            "description": "Controls presentation detail and cost. It never lowers simulation accuracy.",
            "kind": "slider",
            "minimum": 0.0,
            "maximum": 1.0,
            "value": profile.presentation_fidelity,
        },
        {
            "key": "pixel_perfect",
            "label": "Pixel Perfect",
            "description": "Keeps pixels aligned and scales the image by whole-number steps.",
            "kind": "toggle",
            "value": bool(profile.resolution.pixel_snap and profile.resolution.integer_scaling),
        },
        {
            "key": "pixel_canvas",
            "label": "Pixel Canvas",
            "description": "The small internal canvas that is enlarged cleanly for pixel-art projects.",
            "kind": "size",
            "value": [profile.resolution.base_width, profile.resolution.base_height],
            "visible_when": {"pixel_perfect": True},
        },
        {
            "key": "animation_feel",
            "label": "Animation Feel",
            "description": "Use crisp stepped frames, smooth motion, or let each asset choose.",
            "kind": "choice",
            "value": str(profile.animation.get("sampling") or "continuous"),
            "choices": [
                {"value": "stepped", "label": "Crisp / Stepped"},
                {"value": "continuous", "label": "Smooth"},
                {"value": "continuous_or_stepped", "label": "Per Asset"},
            ],
        },
        {
            "key": "camera_projection",
            "label": "Camera Projection",
            "description": "Controls perspective without changing world coordinates or gameplay collision.",
            "kind": "choice",
            "value": profile.camera.projection,
            "choices": [
                {"value": "orthographic", "label": "Flat / Orthographic"},
                {"value": "perspective", "label": "Perspective"},
                {"value": "orthographic_or_perspective", "label": "Shot Controlled"},
                {"value": "per_view", "label": "Per View"},
            ],
        },
        {
            "key": "sprite_facing",
            "label": "Sprite Facing",
            "description": "Choose whether layered characters face the camera, a fixed axis, or an authored direction.",
            "kind": "choice",
            "value": profile.camera.billboard_mode,
            "choices": [
                {"value": "none", "label": "Do Not Turn"},
                {"value": "camera", "label": "Face Camera"},
                {"value": "authored_axis", "label": "Authored Axis"},
            ],
            "visible_when": {"world_layout": ["2.5d", "mixed"]},
        },
    ]


def presentation_summary(profile: PresentationProfile) -> dict[str, Any]:
    return {
        "title": f"{VISUAL_STYLE_LABELS.get(profile.visual_style, profile.visual_style)} in {profile.dimensionality.upper()}",
        "description": _plain_description(profile),
        "controls": presentation_controls(profile),
        "advanced": {
            "geometry": dict(profile.geometry),
            "materials": dict(profile.materials),
            "lighting": dict(profile.lighting),
            "effects": dict(profile.effects),
            "post_process": dict(profile.post_process),
        },
    }


def update_presentation_control(profile: PresentationProfile, key: str, value: Any) -> PresentationProfile:
    control = str(key).strip().lower()
    if control == "visual_style":
        replacement = create_presentation_profile(
            profile.profile_id,
            value,
            dimensionality=profile.dimensionality,
        )
        replacement.metadata.update(profile.metadata)
        profile.__dict__.update(replacement.__dict__)
    elif control == "world_layout":
        replacement = create_presentation_profile(
            profile.profile_id,
            profile.visual_style,
            dimensionality=value,
        )
        replacement.presentation_fidelity = profile.presentation_fidelity
        replacement.materials = dict(profile.materials)
        replacement.lighting = dict(profile.lighting)
        replacement.animation = dict(profile.animation)
        replacement.effects = dict(profile.effects)
        replacement.ui = dict(profile.ui)
        replacement.post_process = dict(profile.post_process)
        replacement.resolution = profile.resolution
        replacement.source_preservation = dict(profile.source_preservation)
        replacement.metadata = dict(profile.metadata)
        profile.__dict__.update(replacement.__dict__)
    elif control == "visual_detail":
        profile.presentation_fidelity = _clamp01(value)
    elif control == "pixel_perfect":
        enabled = bool(value)
        profile.resolution = ResolutionPolicy(
            **{**asdict(profile.resolution), "integer_scaling": enabled, "pixel_snap": enabled, "subpixel_camera": not enabled, "texture_filter": "nearest" if enabled else "linear"}
        )
    elif control == "pixel_canvas":
        width, height = value
        profile.resolution = ResolutionPolicy(**{**asdict(profile.resolution), "base_width": max(1, int(width)), "base_height": max(1, int(height))})
    elif control == "animation_feel":
        if str(value) not in {"stepped", "continuous", "continuous_or_stepped"}:
            raise ValueError("Animation Feel must be stepped, continuous, or continuous_or_stepped.")
        profile.animation["sampling"] = str(value)
    elif control == "camera_projection":
        profile.camera = CameraPresentationPolicy(**{**asdict(profile.camera), "projection": str(value)})
    elif control == "sprite_facing":
        profile.camera = CameraPresentationPolicy(**{**asdict(profile.camera), "billboard_mode": str(value)})
    else:
        raise KeyError(f"Unknown presentation control: {key}")
    return profile


def _asset_representations(profile: PresentationProfile) -> dict[str, str]:
    dimension = profile.dimensionality
    if dimension == "2d":
        return {"characters": "sprite_or_vector", "world": "tile_layer_or_vector", "effects": str(profile.effects.get("representation") or "sprite")}
    if dimension == "2.5d":
        return {"characters": "sprite_card_or_mesh", "world": "layered_cards_and_meshes", "effects": str(profile.effects.get("representation") or "mixed")}
    if dimension == "mixed":
        return {"characters": "per_asset", "world": "mixed", "effects": str(profile.effects.get("representation") or "mixed")}
    return {"characters": "mesh", "world": "mesh_and_volume", "effects": str(profile.effects.get("representation") or "particles_and_meshes")}


def _apply_overrides(profile: PresentationProfile, overrides: dict[str, Any]) -> None:
    for name in ("geometry", "materials", "lighting", "animation", "effects", "ui", "post_process", "source_preservation", "metadata"):
        value = overrides.get(name)
        if isinstance(value, dict):
            getattr(profile, name).update(value)
    if isinstance(overrides.get("camera"), dict):
        profile.camera = CameraPresentationPolicy(**{**asdict(profile.camera), **overrides["camera"]})
    if isinstance(overrides.get("resolution"), dict):
        profile.resolution = ResolutionPolicy(**{**asdict(profile.resolution), **overrides["resolution"]})
    if "presentation_fidelity" in overrides:
        profile.presentation_fidelity = _clamp01(overrides["presentation_fidelity"])


def _clamp01(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _plain_description(profile: PresentationProfile) -> str:
    layout = {
        "2d": "a flat layered world",
        "2.5d": "a layered world with real depth and parallax",
        "3d": "a fully three-dimensional world",
        "mixed": "a mixture chosen per view and asset",
    }[profile.dimensionality]
    return f"Uses {VISUAL_STYLE_LABELS.get(profile.visual_style, profile.visual_style)} presentation in {layout}. Gameplay and simulation remain unchanged."
