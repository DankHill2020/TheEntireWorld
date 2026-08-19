"""Progressive provider manifest for user-added 3D applications."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROVIDER_SCHEMA = "tech_connector.3d_app_provider.v1"


@dataclass(frozen=True)
class ProviderValidationResult:
    ok: bool
    level: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    enabled_features: list[str] = field(default_factory=list)
    optional_next_steps: list[str] = field(default_factory=list)


def build_3d_app_provider_manifest(
    *,
    app_id: str,
    display_name: str,
    executable_path: str,
    api_docs: list[str] | str,
    aliases: list[str] | None = None,
    version: str = "",
    api_bootstrap: dict[str, Any] | None = None,
    bridge: dict[str, Any] | None = None,
    internal_tools: list[dict[str, Any]] | None = None,
    scene_snapshot: dict[str, Any] | None = None,
    smart_menu: dict[str, Any] | None = None,
    icon_path: str = "",
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a progressive 3D app provider manifest.

    Only app identity, executable path, and API docs are required. Everything
    else upgrades the provider from launchable/docs-aware into connected,
    inspectable, viewport-capable, and smart-menu capable.
    """
    docs = [api_docs] if isinstance(api_docs, str) else list(api_docs or [])
    return {
        "schema": PROVIDER_SCHEMA,
        "app_id": _slug(app_id or display_name),
        "display_name": display_name.strip() or app_id,
        "aliases": list(aliases or []),
        "version": version,
        "required": {
            "executable_path": executable_path,
            "api_docs": docs,
        },
        "optional": {
            "api_bootstrap": dict(api_bootstrap or {}),
            "bridge": dict(bridge or {}),
            "internal_tools": list(internal_tools or []),
            "scene_snapshot": dict(scene_snapshot or {}),
            "smart_menu": dict(smart_menu or {}),
            "icon_path": icon_path,
            "validation": dict(validation or {}),
        },
        "feature_levels": {
            "launchable": False,
            "docs_indexable": False,
            "api_aware": False,
            "bridge_connectable": False,
            "internal_tools_indexable": False,
            "scene_inspectable": False,
            "viewport_capable": False,
            "smart_menu_capable": False,
            "validated": False,
        },
    }


def validate_3d_app_provider_manifest(manifest: dict[str, Any]) -> ProviderValidationResult:
    """Validate a provider manifest and report progressive feature level."""
    errors: list[str] = []
    warnings: list[str] = []
    enabled: list[str] = []
    next_steps: list[str] = []

    if manifest.get("schema") != PROVIDER_SCHEMA:
        errors.append(f"schema must be {PROVIDER_SCHEMA}")

    display_name = str(manifest.get("display_name") or "").strip()
    if not display_name:
        errors.append("display_name is required")

    required = manifest.get("required") or {}
    executable_path = str(required.get("executable_path") or "").strip()
    api_docs = [str(item).strip() for item in (required.get("api_docs") or []) if str(item).strip()]

    if not executable_path:
        errors.append("required.executable_path is required")
    else:
        enabled.append("launchable")
        if not Path(executable_path).exists():
            warnings.append(f"Executable path does not exist yet: {executable_path}")

    if api_docs:
        enabled.append("docs_indexable")
        if any(_looks_like_api_doc(path) for path in api_docs):
            enabled.append("api_aware")
        else:
            warnings.append("API docs were provided, but none look like a local file, URL, or markdown reference.")
    else:
        errors.append("required.api_docs must contain at least one API documentation path, URL, or note")

    optional = manifest.get("optional") or {}
    bridge = optional.get("bridge") or {}
    if bridge.get("protocol") and (bridge.get("adapter_module") or bridge.get("setup_script") or bridge.get("port")):
        enabled.append("bridge_connectable")
    else:
        next_steps.append("Add an optional bridge protocol, adapter module, setup script, or port to enable live commands.")

    internal_tools = optional.get("internal_tools") or []
    if internal_tools:
        enabled.append("internal_tools_indexable")
    else:
        next_steps.append("Add optional internal tool folders/modules to expose app-specific functions in smart menus.")

    scene_snapshot = optional.get("scene_snapshot") or {}
    if scene_snapshot.get("method") or scene_snapshot.get("code_generator"):
        enabled.append("scene_inspectable")
        if scene_snapshot.get("returns_geometry") or scene_snapshot.get("returns_bounds"):
            enabled.append("viewport_capable")
    else:
        next_steps.append("Add an optional scene snapshot method to make the app appear in the federated viewport.")

    smart_menu = optional.get("smart_menu") or {}
    if smart_menu.get("actions") or smart_menu.get("menu_label"):
        enabled.append("smart_menu_capable")
    else:
        next_steps.append("Add optional smart-menu actions for common app workflows.")

    validation = optional.get("validation") or {}
    if validation.get("smoke_prompts") or validation.get("health_check"):
        enabled.append("validated")
    else:
        next_steps.append("Add optional health checks or smoke prompts to make setup foolproof.")

    level = _provider_level(enabled)
    return ProviderValidationResult(
        ok=not errors,
        level=level,
        errors=errors,
        warnings=warnings,
        enabled_features=sorted(set(enabled)),
        optional_next_steps=next_steps,
    )


def provider_menu_contributions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return smart-menu contributions declared by a provider."""
    optional = manifest.get("optional") or {}
    smart_menu = optional.get("smart_menu") or {}
    app_id = manifest.get("app_id") or _slug(manifest.get("display_name", "app"))
    label = smart_menu.get("menu_label") or manifest.get("display_name") or app_id
    actions = []
    for item in smart_menu.get("actions") or []:
        if not isinstance(item, dict):
            continue
        action_id = str(item.get("id") or item.get("label") or "").strip()
        if not action_id:
            continue
        actions.append({
            "app_id": app_id,
            "menu": label,
            "id": action_id,
            "label": item.get("label") or action_id.replace("_", " ").title(),
            "capability": item.get("capability") or "",
            "requires_bridge": bool(item.get("requires_bridge", True)),
            "mutates_scene": bool(item.get("mutates_scene", False)),
        })
    return actions


def _provider_level(enabled: list[str]) -> str:
    features = set(enabled)
    if "smart_menu_capable" in features and "validated" in features:
        return "smart_menu_ready"
    if "viewport_capable" in features:
        return "viewport_ready"
    if "bridge_connectable" in features:
        return "connected_app_ready"
    if {"launchable", "docs_indexable"} <= features:
        return "minimum_viable"
    return "incomplete"


def _looks_like_api_doc(value: str) -> bool:
    text = value.lower()
    return (
        text.startswith("http://")
        or text.startswith("https://")
        or text.endswith((".md", ".txt", ".pdf", ".html", ".json", ".pyi"))
        or "\\" in value
        or "/" in value
    )


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")[:64] or "3d_app"
