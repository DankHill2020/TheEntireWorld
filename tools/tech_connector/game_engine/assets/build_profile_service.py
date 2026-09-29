"""Build-profile validation and dependency-closed package planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .asset_database_service import AssetDatabase


SUPPORTED_BUILD_PLATFORMS = ("windows", "linux", "macos", "android", "ios", "web")
SUPPORTED_BUILD_CONFIGURATIONS = ("development", "test", "shipping")


@dataclass(frozen=True)
class BuildProfileDiagnostic:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class BuildProfilePlan:
    platform: str
    configuration: str
    quality_profile: str
    entry_level: str
    included_levels: tuple[str, ...]
    asset_ids: tuple[str, ...]
    incremental: bool
    output_directory: str
    diagnostics: tuple[BuildProfileDiagnostic, ...]

    @property
    def ready(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"ready": self.ready}


def plan_build_profile(database: AssetDatabase, properties: Mapping[str, Any]) -> BuildProfilePlan:
    platform = str(properties.get("platform") or "windows").casefold()
    configuration = str(properties.get("configuration") or "development").casefold()
    quality = str(properties.get("quality_profile") or "high")
    entry = str(properties.get("entry_level") or "")
    included = tuple(dict.fromkeys(str(item) for item in properties.get("included_levels") or () if str(item)))
    roots = tuple(dict.fromkeys((entry, *included))) if entry else included
    diagnostics: list[BuildProfileDiagnostic] = []
    if platform not in SUPPORTED_BUILD_PLATFORMS:
        diagnostics.append(BuildProfileDiagnostic("error", "unsupported_platform", f"Unsupported build platform: {platform}."))
    if configuration not in SUPPORTED_BUILD_CONFIGURATIONS:
        diagnostics.append(BuildProfileDiagnostic("error", "unsupported_configuration", f"Unsupported build configuration: {configuration}."))
    if not entry:
        diagnostics.append(BuildProfileDiagnostic("error", "missing_entry_level", "Choose an entry level before packaging."))
    for asset_id in roots:
        record = database.asset(asset_id)
        if record is None:
            diagnostics.append(BuildProfileDiagnostic("error", "missing_level", f"Included level is unavailable: {asset_id}."))
        elif record.asset_type != "tc.level":
            diagnostics.append(BuildProfileDiagnostic("error", "invalid_level_type", f"{record.source_path.name} is not a level asset."))
    asset_ids: tuple[str, ...] = ()
    available_roots = tuple(asset_id for asset_id in roots if database.asset(asset_id) is not None)
    if available_roots:
        asset_ids = database.dependency_closure(available_roots)
    if configuration == "shipping" and bool(properties.get("include_debug_symbols", False)):
        diagnostics.append(BuildProfileDiagnostic("warning", "shipping_debug_symbols", "Shipping build includes debug symbols."))
    return BuildProfilePlan(
        platform, configuration, quality, entry, included, asset_ids,
        bool(properties.get("incremental", True)), str(properties.get("output_directory") or "Build"),
        tuple(diagnostics),
    )


__all__ = [
    "BuildProfileDiagnostic", "BuildProfilePlan", "SUPPORTED_BUILD_CONFIGURATIONS",
    "SUPPORTED_BUILD_PLATFORMS", "plan_build_profile",
]
