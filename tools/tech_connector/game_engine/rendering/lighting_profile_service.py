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


def _environment_profile(
    profile_id: str,
    display_name: str,
    description: str,
    *,
    sky: tuple[float, float, float],
    ground: tuple[float, float, float],
    sun_color: tuple[float, float, float],
    sun_direction: tuple[float, float, float],
    sun_intensity: float,
    exposure: float = 1.0,
    indirect: float = 1.0,
    atmosphere: bool = False,
    lighting_model: str = "physically_based",
    global_illumination: str = "probe",
    angular_radius: float = 0.5,
) -> LightingProfile:
    """Build a complete renderer-safe preset with consistent contract fields."""
    return LightingProfile(profile_id, display_name, description, {
        "lighting_model": lighting_model,
        "global_illumination": global_illumination,
        "exposure": exposure,
        "sky_color": list(sky),
        "ground_color": list(ground),
        "indirect_intensity": indirect,
        "atmosphere_enabled": atmosphere,
    }, {
        "direction": list(sun_direction),
        "color": list(sun_color),
        "intensity": sun_intensity,
        "angular_radius_degrees": angular_radius,
        "casts_shadow": sun_intensity > 0.0,
    })


# Additional production presets intentionally share the same compact contract:
# they work in Garden, Kingdom, and packaged runtime builds without adapters.
for _profile in (
    _environment_profile("sunrise", "Sunrise", "Soft peach sunrise with long readable shadows.", sky=(0.22, 0.30, 0.58), ground=(0.08, 0.035, 0.025), sun_color=(1.0, 0.58, 0.32), sun_direction=(0.78, -0.16, -0.42), sun_intensity=4.1, exposure=1.08, indirect=0.9, atmosphere=True),
    _environment_profile("midday_hard", "Hard Midday", "Bright overhead sun for strong form and shadow readability.", sky=(0.06, 0.22, 0.55), ground=(0.04, 0.05, 0.04), sun_color=(1.0, 0.98, 0.9), sun_direction=(-0.12, -1.0, -0.18), sun_intensity=5.8, exposure=0.92, indirect=0.72, atmosphere=True, angular_radius=0.18),
    _environment_profile("sunset", "Deep Sunset", "A red-orange horizon for silhouettes and cinematic exteriors.", sky=(0.16, 0.08, 0.30), ground=(0.06, 0.018, 0.012), sun_color=(1.0, 0.25, 0.08), sun_direction=(-0.9, -0.08, -0.25), sun_intensity=4.7, exposure=1.12, indirect=0.68, atmosphere=True),
    _environment_profile("blue_hour", "Blue Hour", "Cool post-sunset ambience with a restrained warm key.", sky=(0.025, 0.07, 0.20), ground=(0.012, 0.018, 0.035), sun_color=(1.0, 0.58, 0.32), sun_direction=(0.7, -0.18, -0.5), sun_intensity=0.85, exposure=1.28, indirect=0.72, atmosphere=True, angular_radius=0.8),
    _environment_profile("storm", "Storm Front", "Dark desaturated sky with hard directional breaks.", sky=(0.07, 0.09, 0.11), ground=(0.022, 0.025, 0.027), sun_color=(0.62, 0.72, 0.86), sun_direction=(-0.72, -0.62, 0.12), sun_intensity=1.7, exposure=1.22, indirect=0.7, atmosphere=True, angular_radius=1.8),
    _environment_profile("desert", "Desert Sun", "Hot high-contrast sun with warm sand bounce.", sky=(0.16, 0.35, 0.62), ground=(0.20, 0.105, 0.045), sun_color=(1.0, 0.78, 0.48), sun_direction=(-0.25, -0.92, -0.18), sun_intensity=5.5, exposure=0.9, indirect=1.05, atmosphere=True, angular_radius=0.22),
    _environment_profile("snow", "Snow Day", "Cool bright exterior with strong diffuse ground bounce.", sky=(0.32, 0.48, 0.70), ground=(0.55, 0.62, 0.70), sun_color=(0.86, 0.92, 1.0), sun_direction=(-0.38, -0.78, -0.42), sun_intensity=3.6, exposure=0.82, indirect=1.65, atmosphere=True, angular_radius=0.8),
    _environment_profile("studio_softbox", "Studio Softbox", "Broad flattering key and neutral fill for characters and props.", sky=(0.22, 0.23, 0.25), ground=(0.045, 0.045, 0.048), sun_color=(1.0, 0.97, 0.94), sun_direction=(-0.62, -0.62, -0.48), sun_intensity=2.6, exposure=1.04, indirect=1.55, angular_radius=4.0),
    _environment_profile("studio_warm", "Warm Studio", "Warm portrait key with a subdued cool-gray environment.", sky=(0.16, 0.15, 0.15), ground=(0.035, 0.028, 0.025), sun_color=(1.0, 0.68, 0.42), sun_direction=(-0.68, -0.58, -0.34), sun_intensity=3.1, exposure=1.02, indirect=1.1, angular_radius=2.4),
    _environment_profile("studio_cool", "Cool Studio", "Crisp cool key for technical, metallic, and sci-fi assets.", sky=(0.10, 0.14, 0.20), ground=(0.025, 0.032, 0.045), sun_color=(0.58, 0.78, 1.0), sun_direction=(0.55, -0.72, -0.4), sun_intensity=3.25, exposure=1.04, indirect=1.2, angular_radius=1.8),
    _environment_profile("product_high_key", "Product High Key", "Bright low-contrast product lighting on a clean background.", sky=(0.68, 0.70, 0.74), ground=(0.45, 0.46, 0.48), sun_color=(1.0, 1.0, 1.0), sun_direction=(-0.45, -0.72, -0.42), sun_intensity=2.45, exposure=0.88, indirect=1.9, angular_radius=5.0),
    _environment_profile("product_low_key", "Product Low Key", "Dark glossy product lighting with controlled highlights.", sky=(0.008, 0.01, 0.014), ground=(0.004, 0.005, 0.007), sun_color=(0.82, 0.9, 1.0), sun_direction=(-0.8, -0.35, -0.25), sun_intensity=4.8, exposure=1.18, indirect=0.28, angular_radius=0.35),
    _environment_profile("rim_showcase", "Rim Showcase", "Strong side-back key for silhouette and surface inspection.", sky=(0.025, 0.03, 0.045), ground=(0.01, 0.012, 0.018), sun_color=(0.5, 0.72, 1.0), sun_direction=(0.82, -0.3, 0.5), sun_intensity=4.4, exposure=1.1, indirect=0.55, angular_radius=0.45),
    _environment_profile("cinematic_teal_orange", "Cinematic Teal + Orange", "Warm key against cool ambience for cinematic blocking.", sky=(0.015, 0.12, 0.15), ground=(0.012, 0.025, 0.028), sun_color=(1.0, 0.42, 0.16), sun_direction=(-0.72, -0.5, -0.34), sun_intensity=3.8, exposure=1.08, indirect=0.82, angular_radius=0.7),
    _environment_profile("noir", "Film Noir", "Hard monochrome-inspired key with deep negative fill.", sky=(0.018, 0.018, 0.02), ground=(0.004, 0.004, 0.005), sun_color=(0.92, 0.94, 1.0), sun_direction=(-0.9, -0.28, -0.18), sun_intensity=5.0, exposure=1.14, indirect=0.18, angular_radius=0.12),
    _environment_profile("horror", "Horror Underlight", "Unnatural low red key with cold ambient separation.", sky=(0.018, 0.025, 0.06), ground=(0.07, 0.008, 0.006), sun_color=(1.0, 0.08, 0.025), sun_direction=(0.12, 0.82, -0.35), sun_intensity=2.8, exposure=1.3, indirect=0.38, angular_radius=0.4),
    _environment_profile("sci_fi", "Sci-Fi Cyan", "Cool cyan technical lighting with a deep blue environment.", sky=(0.008, 0.04, 0.09), ground=(0.006, 0.018, 0.03), sun_color=(0.12, 0.85, 1.0), sun_direction=(0.62, -0.44, -0.52), sun_intensity=3.6, exposure=1.16, indirect=0.76, angular_radius=0.55),
    _environment_profile("candlelight", "Candlelight", "Very warm intimate light with near-black surroundings.", sky=(0.018, 0.008, 0.004), ground=(0.012, 0.004, 0.002), sun_color=(1.0, 0.25, 0.035), sun_direction=(-0.2, 0.7, -0.4), sun_intensity=1.35, exposure=1.48, indirect=0.2, angular_radius=2.8),
    _environment_profile("anime_day", "Anime Day", "Bright saturated sky and clean graphic directional light.", sky=(0.16, 0.44, 0.86), ground=(0.12, 0.18, 0.22), sun_color=(1.0, 0.92, 0.70), sun_direction=(-0.36, -0.9, -0.24), sun_intensity=4.2, exposure=0.96, indirect=1.05, lighting_model="toon", global_illumination="hemisphere", angular_radius=0.4),
    _environment_profile("neon_night", "Neon Night", "Magenta-cyan nightlife palette for emissive and reflective assets.", sky=(0.035, 0.008, 0.09), ground=(0.006, 0.025, 0.04), sun_color=(1.0, 0.05, 0.65), sun_direction=(-0.68, -0.38, -0.42), sun_intensity=3.25, exposure=1.34, indirect=0.72, angular_radius=0.5),
    _environment_profile("silhouette", "Silhouette", "Near-black subjects against a bright readable background.", sky=(0.52, 0.20, 0.08), ground=(0.01, 0.006, 0.004), sun_color=(1.0, 0.35, 0.08), sun_direction=(0.1, -0.2, 0.98), sun_intensity=0.08, exposure=0.95, indirect=0.0, atmosphere=True, global_illumination="off", angular_radius=0.3),
):
    _PROFILES[_profile.profile_id] = _profile


def lighting_profiles() -> tuple[LightingProfile, ...]:
    """Return profiles in stable user-facing order."""
    return tuple(_PROFILES.values())


_PROFILE_CATEGORIES = {
    "Outdoor": {
        "daylight", "sunrise", "midday_hard", "overcast", "golden_hour", "sunset",
        "blue_hour", "moonlight", "storm", "desert", "snow",
    },
    "Studio": {
        "studio_neutral", "studio_softbox", "studio_warm", "studio_cool",
        "product_high_key", "product_low_key", "rim_showcase",
    },
    "Cinematic": {
        "cinematic_teal_orange", "noir", "horror", "sci_fi", "candlelight",
        "neon_night", "silhouette",
    },
    "Stylized": {"toon", "anime_day"},
    "Reference": {"unlit_reference"},
}


def lighting_profile_category(profile_id: str) -> str:
    """Return the stable user-facing category for a lighting profile."""
    key = str(profile_id or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return next((name for name, profile_ids in _PROFILE_CATEGORIES.items() if key in profile_ids), "Other")


def lighting_profile_groups() -> tuple[tuple[str, tuple[LightingProfile, ...]], ...]:
    """Return all presets in practical UI groups while preserving profile order within each group."""
    profiles = lighting_profiles()
    groups = []
    for category in (*_PROFILE_CATEGORIES, "Other"):
        members = tuple(profile for profile in profiles if lighting_profile_category(profile.profile_id) == category)
        if members:
            groups.append((category, members))
    return tuple(groups)


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
