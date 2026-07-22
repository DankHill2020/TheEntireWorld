"""Versioned character-to-DCC-rig manifests for animation source workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


MANIFEST_NAME = "character_rig.json"


def character_slug(character_key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(character_key or "").strip()).strip("_.")
    if not slug:
        raise ValueError("character_key is required")
    return slug


def character_source_dir(artsource_root: str | Path, character_key: str) -> Path:
    return Path(artsource_root).expanduser().resolve() / "Characters" / character_slug(character_key)


def character_rig_scene_path(
    artsource_root: str | Path,
    character_key: str,
    *,
    version: int = 1,
    extension: str = ".mb",
) -> Path:
    suffix = extension if str(extension).startswith(".") else "." + str(extension)
    return character_source_dir(artsource_root, character_key) / "Rig" / (
        f"{character_slug(character_key)}_Rig_v{int(version):03d}{suffix}"
    )


def animation_source_paths(
    artsource_root: str | Path,
    character_key: str,
    animation_name: str,
) -> dict[str, Path]:
    base = character_source_dir(artsource_root, character_key) / "Animations"
    clip = character_slug(animation_name)
    return {
        "scene": base / "Source" / f"{clip}.mb",
        "fbx": base / "Export" / f"{clip}.fbx",
    }


def build_manifest(
    *,
    character_key: str,
    unreal_skeletal_mesh: str,
    unreal_skeleton: str,
    rig_scene: str | Path,
    mapping_profile: str | Path,
    rig_adapter: str,
    rig_namespace: str,
    target_skeleton_source: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "character_key": character_slug(character_key),
        "unreal": {
            "skeletal_mesh": str(unreal_skeletal_mesh),
            "skeleton": str(unreal_skeleton),
        },
        "maya": {
            "rig_scene": str(Path(rig_scene).expanduser().resolve()),
            "mapping_profile": str(Path(mapping_profile).expanduser().resolve()),
            "rig_adapter": str(rig_adapter),
            "rig_namespace": str(rig_namespace),
            "target_skeleton_source": (
                str(Path(target_skeleton_source).expanduser().resolve())
                if target_skeleton_source else ""
            ),
            "reference_required": True,
        },
    }


def validate_manifest(manifest: dict[str, Any], *, require_files: bool = True) -> dict[str, Any]:
    maya = dict(manifest.get("maya") or {})
    unreal = dict(manifest.get("unreal") or {})
    errors = []
    if not manifest.get("character_key"):
        errors.append("character_key is missing")
    for key in ("skeletal_mesh", "skeleton"):
        if not unreal.get(key):
            errors.append(f"unreal.{key} is missing")
    for key in ("rig_scene", "mapping_profile", "rig_adapter", "rig_namespace"):
        if not maya.get(key):
            errors.append(f"maya.{key} is missing")
    if maya.get("reference_required") is not True:
        errors.append("maya.reference_required must be true")
    if require_files:
        for key in ("rig_scene", "mapping_profile"):
            value = maya.get(key)
            if value and not Path(value).is_file():
                errors.append(f"maya.{key} does not exist: {value}")
    return {"ok": not errors, "errors": errors}


def save_manifest(artsource_root: str | Path, manifest: dict[str, Any]) -> Path:
    validation = validate_manifest(manifest)
    if not validation["ok"]:
        raise ValueError("Invalid character rig manifest: " + "; ".join(validation["errors"]))
    path = character_source_dir(artsource_root, manifest["character_key"]) / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def load_manifest(path: str | Path, *, require_files: bool = True) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    validation = validate_manifest(manifest, require_files=require_files)
    if not validation["ok"]:
        raise ValueError("Invalid character rig manifest: " + "; ".join(validation["errors"]))
    manifest["manifest_path"] = str(resolved)
    return manifest


def discover_manifests(artsource_roots: Iterable[str | Path]) -> list[dict[str, Any]]:
    results = []
    for root in artsource_roots:
        characters = Path(root).expanduser().resolve() / "Characters"
        if not characters.is_dir():
            continue
        for path in sorted(characters.glob(f"*/{MANIFEST_NAME}")):
            try:
                results.append(load_manifest(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return results

