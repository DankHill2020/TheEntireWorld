"""Portable still-image, animated-image, and video texture-source contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


MEDIA_TEXTURE_SCHEMA = "tech_connector.media_texture_source.v1"
IMAGE_EXTENSIONS = frozenset({".bmp", ".dds", ".exr", ".hdr", ".jpeg", ".jpg", ".ktx", ".ktx2", ".png", ".tga", ".tif", ".tiff", ".webp"})
ANIMATED_IMAGE_EXTENSIONS = frozenset({".gif", ".apng"})
VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".webm", ".wmv"})
SOURCE_TYPES = frozenset({"image", "animated_image", "image_sequence", "video"})


@dataclass(frozen=True)
class MediaTextureSource:
    path: str
    source_type: str
    autoplay: bool = True
    loop: bool = True
    playback_rate: float = 1.0
    start_time_seconds: float = 0.0
    end_time_seconds: float | None = None
    frame_rate: float = 0.0
    muted: bool = True
    synchronization: str = "timeline"
    fallback_frame: str = "first"
    sequence_start: int = 0
    sequence_end: int = 0
    sequence_padding: int = 4
    schema: str = MEDIA_TEXTURE_SCHEMA

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("A media texture source requires a path or URL.")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"Unknown media texture source type: {self.source_type}")
        if not 0.05 <= float(self.playback_rate) <= 8.0:
            raise ValueError("Media texture playback rate must be between 0.05 and 8.0.")
        if float(self.start_time_seconds) < 0.0:
            raise ValueError("Media texture start time cannot be negative.")
        if self.end_time_seconds is not None and float(self.end_time_seconds) <= float(self.start_time_seconds):
            raise ValueError("Media texture end time must be greater than its start time.")
        if self.synchronization not in {"timeline", "realtime", "manual"}:
            raise ValueError(f"Unknown media texture synchronization mode: {self.synchronization}")
        if self.fallback_frame not in {"first", "last_valid", "checkerboard", "transparent"}:
            raise ValueError(f"Unknown media texture fallback frame: {self.fallback_frame}")

    @property
    def animated(self) -> bool:
        return self.source_type != "image"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_media_source_type(path: str, *, declared_type: str = "") -> str:
    declared = str(declared_type or "").strip().lower().replace("gif", "animated_image")
    aliases = {"still": "image", "animated": "animated_image", "gif": "animated_image", "movie": "video", "sequence": "image_sequence"}
    declared = aliases.get(declared, declared)
    if declared:
        if declared not in SOURCE_TYPES:
            raise ValueError(f"Unknown media texture source type: {declared_type}")
        return declared
    raw_path = str(path)
    parsed_path = urlparse(raw_path).path
    if "#" in raw_path or "%0" in raw_path:
        return "image_sequence"
    suffix = Path(parsed_path).suffix.lower()
    if suffix in ANIMATED_IMAGE_EXTENSIONS:
        return "animated_image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "image"


def normalize_media_texture_source(
    payload: str | dict[str, Any] | MediaTextureSource,
    *,
    source_path: str = "",
) -> MediaTextureSource:
    if isinstance(payload, MediaTextureSource):
        return payload
    raw = {"path": payload} if isinstance(payload, str) else dict(payload or {})
    path = str(raw.get("path") or raw.get("file") or raw.get("url") or "").strip()
    if not path:
        raise ValueError("A media texture source requires 'path', 'file', or 'url'.")
    parsed = urlparse(path)
    if not parsed.scheme and source_path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            path = str(Path(source_path).expanduser().resolve().parent / candidate)
    source_type = infer_media_source_type(path, declared_type=str(raw.get("source_type") or raw.get("media_type") or raw.get("type") or ""))
    playback = raw.get("playback") if isinstance(raw.get("playback"), dict) else {}

    def option(name: str, default: Any) -> Any:
        return raw[name] if name in raw else playback.get(name, default)

    end_value = option("end_time_seconds", None)
    return MediaTextureSource(
        path=path,
        source_type=source_type,
        autoplay=bool(option("autoplay", True)),
        loop=bool(option("loop", True)),
        playback_rate=float(option("playback_rate", 1.0)),
        start_time_seconds=float(option("start_time_seconds", 0.0)),
        end_time_seconds=None if end_value in (None, "") else float(end_value),
        frame_rate=max(0.0, float(option("frame_rate", 0.0))),
        muted=bool(option("muted", True)),
        synchronization=str(option("synchronization", "timeline")),
        fallback_frame=str(option("fallback_frame", "first")),
        sequence_start=int(option("sequence_start", 0)),
        sequence_end=int(option("sequence_end", 0)),
        sequence_padding=max(1, min(12, int(option("sequence_padding", 4)))),
    )


def media_texture_runtime_capabilities() -> dict[str, Any]:
    qt_multimedia = importlib.util.find_spec("PySide6.QtMultimedia") is not None
    qt_quick = importlib.util.find_spec("PySide6.QtQuick") is not None
    return {
        "schema": "tech_connector.media_texture_capabilities.v1",
        "static_images": qt_quick,
        "animated_images": qt_quick,
        "video": qt_multimedia,
        "timeline_synchronization": True,
        "hardware_decode": "runtime_and_codec_dependent",
        "supported_contract_types": sorted(SOURCE_TYPES),
    }


def qualify_media_texture_source(source: MediaTextureSource | dict[str, Any]) -> dict[str, Any]:
    item = source if isinstance(source, MediaTextureSource) else normalize_media_texture_source(source)
    capabilities = media_texture_runtime_capabilities()
    parsed = urlparse(item.path)
    remote = parsed.scheme in {"http", "https"}
    local = parsed.scheme in {"", "file"} or Path(item.path).is_absolute()
    local_path = Path(parsed.path.lstrip("/") if parsed.scheme == "file" and len(parsed.path) > 2 and parsed.path[2] == ":" else parsed.path) if parsed.scheme == "file" else Path(item.path)
    blockers: list[str] = []
    warnings: list[str] = []
    if local:
        candidate = local_path.expanduser()
        if item.source_type == "image_sequence":
            token = "#" * item.sequence_padding
            frame_path = str(candidate).replace(token, str(item.sequence_start).zfill(item.sequence_padding))
            if "%0" in frame_path:
                try:
                    frame_path = frame_path % item.sequence_start
                except (TypeError, ValueError):
                    pass
            if not Path(frame_path).is_file():
                blockers.append("sequence_frame_missing")
        elif not candidate.is_file():
            blockers.append("source_missing")
    if item.source_type == "video" and not capabilities["video"]:
        blockers.append("video_runtime")
    if remote:
        warnings.append("Remote media depends on network availability and is not archive-portable until embedded.")
    if item.source_type == "video":
        warnings.append("Video codec and hardware decoding support are runtime/platform dependent.")
    return {
        "schema": "tech_connector.media_texture_qualification.v1",
        "qualified": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "source": item.to_dict(),
        "capabilities": capabilities,
    }


def plan_media_texture_residency(
    sources: dict[str, MediaTextureSource | dict[str, Any]],
    *,
    maximum_video_decoders: int = 4,
    maximum_animated_sources: int = 8,
) -> dict[str, Any]:
    """Bound concurrent decoders while preserving deterministic slot priority."""
    normalized = {str(slot): normalize_media_texture_source(source) for slot, source in sources.items() if source}
    active: list[str] = []
    deferred: list[str] = []
    video_count = 0
    animated_count = 0
    for slot, source in normalized.items():
        if not source.animated:
            active.append(slot)
            continue
        over_animated = animated_count >= max(0, int(maximum_animated_sources))
        over_video = source.source_type == "video" and video_count >= max(0, int(maximum_video_decoders))
        if over_animated or over_video:
            deferred.append(slot)
            continue
        active.append(slot)
        animated_count += 1
        video_count += int(source.source_type == "video")
    return {
        "schema": "tech_connector.media_texture_residency_plan.v1",
        "active_slots": active,
        "deferred_slots": deferred,
        "video_decoder_count": video_count,
        "animated_source_count": animated_count,
        "maximum_video_decoders": max(0, int(maximum_video_decoders)),
        "maximum_animated_sources": max(0, int(maximum_animated_sources)),
        "fallback_policy": "last_valid_frame_or_transparent_until_available",
        "budget_satisfied": not deferred,
    }


__all__ = [
    "ANIMATED_IMAGE_EXTENSIONS", "IMAGE_EXTENSIONS", "MEDIA_TEXTURE_SCHEMA", "MediaTextureSource",
    "SOURCE_TYPES", "VIDEO_EXTENSIONS", "infer_media_source_type", "media_texture_runtime_capabilities",
    "normalize_media_texture_source", "plan_media_texture_residency", "qualify_media_texture_source",
]
