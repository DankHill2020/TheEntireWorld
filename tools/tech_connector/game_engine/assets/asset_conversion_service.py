"""Truthful conversion planning and coverage for every registered asset type."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .asset_type_registry import AssetTypeDescriptor, AssetTypeRegistry, builtin_asset_type_registry


CONVERSION_TARGETS = ("generic", "unreal", "unity", "blender", "maya", "houdini")

DIRECT_IMPORT_EXTENSIONS: dict[str, frozenset[str]] = {
    "unreal": frozenset({
        ".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc", ".abc",
        ".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".hdr",
        ".wav", ".ogg", ".mp3", ".flac", ".ttf", ".otf",
    }),
    "unity": frozenset({
        ".fbx", ".obj", ".gltf", ".glb", ".abc", ".png", ".jpg", ".jpeg",
        ".tga", ".tif", ".tiff", ".exr", ".hdr", ".wav", ".ogg", ".mp3",
        ".flac", ".ttf", ".otf", ".mp4", ".mov", ".webm",
    }),
    "blender": frozenset({
        ".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc", ".abc",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".wav",
    }),
    "maya": frozenset({
        ".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc", ".abc",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".wav",
    }),
    "houdini": frozenset({
        ".fbx", ".obj", ".gltf", ".glb", ".usd", ".usda", ".usdc", ".abc",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".wav",
    }),
}

TARGET_TYPE_BY_FAMILY: dict[str, dict[str, str]] = {
    "unreal": {
        "World": "Level/World asset", "Cinematics": "Level Sequence",
        "Geometry": "StaticMesh/SkeletalMesh", "Animation": "Animation asset",
        "Rendering": "Material/Texture", "Physics": "Physics asset",
        "FX": "Niagara asset", "Audio": "Sound asset", "Gameplay": "Data/Gameplay asset",
        "Project": "Project settings", "Build": "Build configuration",
        "Media": "Media asset", "UI": "Font/UI asset",
    },
    "unity": {
        "World": "Scene/World asset", "Cinematics": "Timeline asset",
        "Geometry": "Mesh/SkinnedMesh", "Animation": "Animation asset",
        "Rendering": "Material/Texture", "Physics": "Physics asset",
        "FX": "Visual Effect asset", "Audio": "Audio asset",
        "Gameplay": "ScriptableObject/Gameplay asset", "Project": "Project settings",
        "Build": "Build configuration", "Media": "VideoClip", "UI": "Font/UI asset",
    },
}


@dataclass(frozen=True)
class AssetConversionPlan:
    type_id: str
    target: str
    source_extension: str
    mode: str
    ready: bool
    target_type: str
    required_actions: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_asset_conversion(
    type_id: str,
    source_path: str | Path,
    target: str,
    *,
    registry: AssetTypeRegistry | None = None,
) -> AssetConversionPlan:
    registry = registry or builtin_asset_type_registry()
    provider = str(target or "generic").casefold()
    if provider not in CONVERSION_TARGETS:
        raise ValueError(f"Unsupported conversion target: {target}")
    descriptor = registry.descriptor(type_id)
    extension = _matched_extension(Path(source_path), descriptor)
    if descriptor is None:
        return AssetConversionPlan(
            str(type_id), provider, extension, "unsupported", False, "Unknown",
            ("register_asset_type",), f"Asset type is not registered: {type_id}",
        )
    if provider == "generic":
        return AssetConversionPlan(
            descriptor.type_id, provider, extension, "portable_package", True,
            descriptor.display_name, ("copy_source", "preserve_metadata", "preserve_dependencies"),
            "The generic package preserves the authoritative source and dependency metadata.",
        )
    target_type = TARGET_TYPE_BY_FAMILY.get(provider, {}).get(descriptor.family, descriptor.display_name)
    if extension in DIRECT_IMPORT_EXTENSIONS.get(provider, frozenset()):
        return AssetConversionPlan(
            descriptor.type_id, provider, extension, "direct_import", True, target_type,
            ("copy_source", "import_in_target", "validate_target_asset"),
            f"{extension or 'Source'} is supported by the generated {provider.title()} importer.",
        )
    if descriptor.bake_modes:
        preferred = tuple(mode for mode in descriptor.bake_modes if mode != "runtime")
        return AssetConversionPlan(
            descriptor.type_id, provider, extension, "bake_required", False, target_type,
            ("cook_or_bake", *(preferred[:3] or ("runtime",)), "import_baked_artifact", "validate_target_asset"),
            "The editable TC source is preserved, but this target needs a cooked/baked interchange artifact.",
        )
    return AssetConversionPlan(
        descriptor.type_id, provider, extension, "native_adapter_required", False, target_type,
        ("install_or_implement_target_adapter", "translate_native_properties", "validate_target_asset"),
        "No direct interchange format or verified native target adapter is available for this source file.",
    )


def conversion_coverage_report(
    *, registry: AssetTypeRegistry | None = None,
    targets: Iterable[str] = CONVERSION_TARGETS,
) -> dict[str, Any]:
    registry = registry or builtin_asset_type_registry()
    providers = tuple(dict.fromkeys(str(value).casefold() for value in targets))
    rows: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for descriptor in registry.all():
        sample = _best_sample_path(descriptor, providers)
        for provider in providers:
            plan = plan_asset_conversion(descriptor.type_id, sample, provider, registry=registry)
            rows.append(plan.to_dict())
            bucket = counts.setdefault(provider, {"total": 0, "ready": 0, "bake_required": 0, "adapter_required": 0, "unsupported": 0})
            bucket["total"] += 1
            if plan.ready:
                bucket["ready"] += 1
            elif plan.mode == "bake_required":
                bucket["bake_required"] += 1
            elif plan.mode == "native_adapter_required":
                bucket["adapter_required"] += 1
            else:
                bucket["unsupported"] += 1
    uncovered = [row for row in rows if not row.get("mode")]
    return {
        "schema": "tech_connector.asset_conversion_coverage.v1",
        "asset_type_count": len(registry.all()),
        "targets": list(providers),
        "counts": counts,
        "classified": len(rows) - len(uncovered),
        "uncovered": uncovered,
        "rows": rows,
    }


def _matched_extension(path: Path, descriptor: AssetTypeDescriptor | None) -> str:
    suffixes = ["".join(path.suffixes[-count:]).casefold() for count in range(len(path.suffixes), 0, -1)]
    if descriptor is not None:
        for suffix in suffixes:
            if suffix in descriptor.extensions:
                return suffix
    return path.suffix.casefold()


def _best_sample_path(descriptor: AssetTypeDescriptor, targets: tuple[str, ...]) -> Path:
    for extension in descriptor.extensions:
        if any(extension in DIRECT_IMPORT_EXTENSIONS.get(target, frozenset()) for target in targets):
            return Path(f"sample{extension}")
    extension = descriptor.extensions[0] if descriptor.extensions else ".tcasset"
    return Path(f"sample{extension}")
