"""Renderer-neutral temporal reconstruction and upscaling contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


UPSCALING_SCHEMA = "tech_connector.upscaling_profile.v1"


@dataclass(frozen=True)
class UpscalingBackend:
    key: str
    display_name: str
    graphics_apis: tuple[str, ...]
    required_inputs: tuple[str, ...]
    optional_runtime: str = ""
    temporal: bool = True
    frame_generation: bool = False


@dataclass(frozen=True)
class UpscalingProfile:
    backend: str = "native"
    quality: str = "native"
    output_width: int = 1920
    output_height: int = 1080
    render_scale: float = 1.0
    sharpness: float = 0.2
    reactive_mask: bool = True
    transparency_mask: bool = True
    dynamic_resolution: bool = False
    minimum_scale: float = 0.5
    maximum_scale: float = 1.0

    def __post_init__(self) -> None:
        if self.backend not in UPSCALING_BACKENDS:
            raise ValueError(f"Unknown upscaling backend: {self.backend}")
        if self.quality not in QUALITY_SCALES:
            raise ValueError(f"Unknown upscaling quality: {self.quality}")
        if self.output_width < 1 or self.output_height < 1:
            raise ValueError("Upscaling output dimensions must be positive.")
        if not 0.25 <= float(self.render_scale) <= 1.0:
            raise ValueError("Render scale must be between 0.25 and 1.0.")
        if not 0.0 <= float(self.sharpness) <= 1.0:
            raise ValueError("Upscaling sharpness must be between zero and one.")
        if not 0.25 <= float(self.minimum_scale) <= float(self.maximum_scale) <= 1.0:
            raise ValueError("Dynamic-resolution bounds must satisfy 0.25 <= minimum <= maximum <= 1.0.")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": UPSCALING_SCHEMA, **asdict(self), **render_dimensions(self)}


QUALITY_SCALES = {
    "native": 1.0,
    "quality": 2.0 / 3.0,
    "balanced": 0.58,
    "performance": 0.5,
    "ultra_performance": 1.0 / 3.0,
}

_TEMPORAL_INPUTS = ("hdr_color", "depth", "motion_vectors", "exposure", "camera_jitter")
UPSCALING_BACKENDS = {
    "native": UpscalingBackend("native", "Native Resolution", ("d3d11", "d3d12", "vulkan", "metal"), (), temporal=False),
    "tc_temporal": UpscalingBackend("tc_temporal", "TC Temporal Reconstruction", ("d3d11", "d3d12", "vulkan", "metal"), _TEMPORAL_INPUTS + ("reactive_mask",)),
    "directsr": UpscalingBackend("directsr", "Microsoft DirectSR", ("d3d12",), _TEMPORAL_INPUTS, "directsr"),
    "dlss": UpscalingBackend("dlss", "NVIDIA DLSS", ("d3d11", "d3d12", "vulkan"), _TEMPORAL_INPUTS + ("transparency_mask",), "streamline"),
    "fsr": UpscalingBackend("fsr", "AMD FidelityFX Super Resolution", ("d3d12", "vulkan"), _TEMPORAL_INPUTS + ("reactive_mask", "transparency_mask"), "fidelityfx"),
    "xess": UpscalingBackend("xess", "Intel XeSS", ("d3d11", "d3d12", "vulkan"), _TEMPORAL_INPUTS + ("responsive_mask",), "xess"),
}


def create_upscaling_profile(
    *,
    backend: str = "native",
    quality: str = "native",
    output_width: int = 1920,
    output_height: int = 1080,
    **overrides: Any,
) -> UpscalingProfile:
    scale = QUALITY_SCALES[str(quality)]
    return UpscalingProfile(
        backend=str(backend), quality=str(quality), output_width=int(output_width), output_height=int(output_height),
        render_scale=float(overrides.pop("render_scale", scale)), **overrides,
    )


def choose_upscaling_backend(
    requested: str,
    *,
    graphics_api: str,
    installed_runtimes: Iterable[str] = (),
) -> tuple[str, tuple[str, ...]]:
    """Resolve a requested backend without making the player unlaunchable."""

    key = str(requested or "tc_temporal").casefold()
    backend = UPSCALING_BACKENDS.get(key)
    reasons: list[str] = []
    runtimes = {str(item).casefold() for item in installed_runtimes}
    if backend is None:
        reasons.append(f"Unknown backend '{requested}'.")
    elif str(graphics_api).casefold() not in backend.graphics_apis:
        reasons.append(f"{backend.display_name} does not support {graphics_api}.")
    elif backend.optional_runtime and backend.optional_runtime not in runtimes:
        reasons.append(f"{backend.display_name} runtime '{backend.optional_runtime}' is not installed.")
    if reasons:
        return "tc_temporal", tuple(reasons + ["Using TC Temporal Reconstruction fallback."])
    return key, ()


def render_dimensions(profile: UpscalingProfile) -> dict[str, int]:
    return {
        "render_width": max(1, int(round(profile.output_width * profile.render_scale))),
        "render_height": max(1, int(round(profile.output_height * profile.render_scale))),
    }


def required_frame_resources(backend: str) -> tuple[str, ...]:
    return UPSCALING_BACKENDS[str(backend)].required_inputs


__all__ = [
    "QUALITY_SCALES", "UPSCALING_BACKENDS", "UPSCALING_SCHEMA", "UpscalingBackend", "UpscalingProfile",
    "choose_upscaling_backend", "create_upscaling_profile", "render_dimensions", "required_frame_resources",
]
