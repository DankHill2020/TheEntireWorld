"""Named, overridable lighting starting points for TC scenes and games."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LightingProfile:
    profile_id: str
    display_name: str
    description: str
    rendering: Mapping[str, Any]
    sun: Mapping[str, Any]


_PROFILES = {
    profile.profile_id: profile
    for profile in (
        LightingProfile("daylight", "Natural Daylight", "Clear physically based daylight with a readable horizon.", {
            "lighting_model": "physically_based", "global_illumination": "probe", "exposure": 1.0,
            "sky_color": [0.08, 0.18, 0.42], "ground_color": [0.025, 0.035, 0.045],
            "indirect_intensity": 1.0, "atmosphere_enabled": True, "atmosphere_density": 1.0,
            "atmospheric_haze": 0.75, "horizon_falloff": 4.0,
        }, {"direction": [-0.45, -1.0, -0.3], "color": [1.0, 0.95, 0.86], "intensity": 4.2, "angular_radius_degrees": 0.266, "casts_shadow": True}),
        LightingProfile("overcast", "Soft Overcast", "Broad cool daylight with gentle contrast and soft shadows.", {
            "lighting_model": "physically_based", "global_illumination": "probe", "exposure": 1.12,
            "sky_color": [0.2, 0.28, 0.38], "ground_color": [0.055, 0.06, 0.065],
            "indirect_intensity": 1.35, "atmosphere_enabled": True, "atmosphere_density": 1.45,
            "atmospheric_haze": 1.4, "horizon_falloff": 2.4,
        }, {"direction": [-0.3, -1.0, -0.15], "color": [0.76, 0.84, 1.0], "intensity": 2.0, "angular_radius_degrees": 2.2, "casts_shadow": True}),
        LightingProfile("golden_hour", "Golden Hour", "Low warm sun with long shadows and saturated atmospheric haze.", {
            "lighting_model": "physically_based", "global_illumination": "probe", "exposure": 1.05,
            "sky_color": [0.12, 0.2, 0.48], "ground_color": [0.055, 0.025, 0.018],
            "indirect_intensity": 0.9, "atmosphere_enabled": True, "atmosphere_density": 1.15,
            "atmospheric_haze": 1.8, "horizon_falloff": 3.0,
        }, {"direction": [-0.82, -0.18, -0.36], "color": [1.0, 0.48, 0.18], "intensity": 5.0, "angular_radius_degrees": 0.3, "casts_shadow": True}),
        LightingProfile("moonlight", "Moonlight", "Cool low-key night lighting that preserves readable silhouettes.", {
            "lighting_model": "physically_based", "global_illumination": "probe", "exposure": 1.35,
            "sky_color": [0.008, 0.018, 0.065], "ground_color": [0.006, 0.009, 0.018],
            "indirect_intensity": 0.45, "atmosphere_enabled": True, "atmosphere_density": 0.65,
            "atmospheric_haze": 0.2, "horizon_falloff": 5.0,
        }, {"direction": [0.35, -0.7, -0.55], "color": [0.46, 0.62, 1.0], "intensity": 0.38, "angular_radius_degrees": 0.26, "casts_shadow": True}),
        LightingProfile("studio_neutral", "Neutral Studio", "Color-neutral asset review lighting without an atmospheric horizon.", {
            "lighting_model": "physically_based", "global_illumination": "probe", "exposure": 1.0,
            "sky_color": [0.18, 0.18, 0.18], "ground_color": [0.035, 0.035, 0.035],
            "indirect_intensity": 1.2, "atmosphere_enabled": False,
        }, {"direction": [-0.55, -1.0, -0.4], "color": [1.0, 1.0, 1.0], "intensity": 3.25, "angular_radius_degrees": 1.0, "casts_shadow": True}),
        LightingProfile("toon", "Graphic Toon", "Stepped lighting, strong rim response, and a clean illustrative sky.", {
            "lighting_model": "toon", "global_illumination": "hemisphere", "exposure": 1.0,
            "sky_color": [0.12, 0.3, 0.62], "ground_color": [0.08, 0.12, 0.18],
            "indirect_intensity": 0.85, "toon_bands": 3, "rim_intensity": 0.34,
            "atmosphere_enabled": False,
        }, {"direction": [-0.5, -1.0, -0.25], "color": [1.0, 0.9, 0.72], "intensity": 3.6, "angular_radius_degrees": 0.8, "casts_shadow": True}),
        LightingProfile("unlit_reference", "Unlit Reference", "Texture and color inspection without modeled illumination.", {
            "lighting_model": "unlit", "global_illumination": "off", "exposure": 1.0,
            "sky_color": [0.055, 0.055, 0.055], "ground_color": [0.055, 0.055, 0.055],
            "indirect_intensity": 0.0, "atmosphere_enabled": False,
        }, {"direction": [0.0, -1.0, 0.0], "color": [1.0, 1.0, 1.0], "intensity": 0.0, "angular_radius_degrees": 0.266, "casts_shadow": False}),
    )
}


def lighting_profiles() -> tuple[LightingProfile, ...]:
    """Return profiles in stable user-facing order."""
    return tuple(_PROFILES.values())


def lighting_profile(profile_id: str | None) -> LightingProfile:
    """Resolve a profile id, defaulting to natural daylight."""
    key = str(profile_id or "daylight").strip().casefold().replace(" ", "_").replace("-", "_")
    if key not in _PROFILES:
        choices = ", ".join(_PROFILES)
        raise ValueError(f"Unknown lighting profile '{profile_id}'. Available profiles: {choices}.")
    return _PROFILES[key]


def resolve_lighting_settings(settings: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply profile defaults while preserving every explicit scene override."""
    overrides = dict(settings or {})
    profile = lighting_profile(overrides.get("lighting_profile"))
    rendering = deepcopy(dict(profile.rendering))
    rendering.update(overrides)
    rendering["lighting_profile"] = profile.profile_id
    return rendering, deepcopy(dict(profile.sun))
