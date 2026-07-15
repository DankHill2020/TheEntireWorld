"""Gameplay prototype helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json
import re


def _tokens(text):
    return [token for token in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if len(token) >= 3]


def _asset_class_name(data):
    try:
        return str(data.asset_class_path.asset_name)
    except Exception:
        try:
            return str(data.asset_class)
        except Exception:
            return ""


def _asset_name(data):
    try:
        return str(data.asset_name)
    except Exception:
        try:
            return str(data.get_asset().get_name())
        except Exception:
            return ""


def _package_name(data):
    try:
        return str(data.package_name)
    except Exception:
        return ""


def _object_path(data):
    for attr in ("object_path", "package_name"):
        try:
            value = getattr(data, attr)
            if value:
                text = str(value)
                if attr == "package_name":
                    name = _asset_name(data)
                    return f"{text}.{name}" if name and "." not in text.rsplit("/", 1)[-1] else text
                return text
        except Exception:
            pass
    try:
        return str(data.get_soft_object_path())
    except Exception:
        pass
    try:
        asset = data.get_asset()
        return asset.get_path_name() if asset else ""
    except Exception:
        return ""


def _asset_index(unreal, directory="/Game/"):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    by_class = {}
    for data in registry.get_assets_by_path(directory, recursive=True):
        class_name = _asset_class_name(data)
        by_class.setdefault(class_name, []).append({
            "name": _asset_name(data),
            "object_path": _object_path(data),
            "package": _package_name(data),
            "class": class_name,
        })
    return by_class


def _rank(items, words):
    ranked = []
    for item in items:
        haystack = f"{item.get('name', '')} {item.get('object_path', '')}".lower()
        score = sum(1 for word in words if word in haystack)
        if "third" in words and "person" in words and "thirdperson" in haystack.replace("_", ""):
            score += 5
        if "climb" in words and any(term in haystack for term in ("climb", "mantle", "ledge")):
            score += 5
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in ranked]


def _rock_climbing_plan(candidate_blueprints, candidate_anim_bps, candidate_anims):
    target_bp = candidate_blueprints[0]["object_path"] if candidate_blueprints else ""
    target_anim_bp = candidate_anim_bps[0]["object_path"] if candidate_anim_bps else ""
    return [
        {
            "operation": "inspect target character Blueprint",
            "target": target_bp,
            "reason": "Confirm movement component, mesh, AnimBP assignment, interfaces, variables, and callable functions.",
        },
        {
            "operation": "inspect or create animation state/slot data",
            "target": target_anim_bp,
            "reason": "Find existing locomotion graph, cached poses, slots, montage usage, and transition variables.",
        },
        {
            "operation": "create climbing variables",
            "target": target_bp,
            "variables": ["bIsClimbing", "ClimbSurfaceNormal", "ClimbTargetLocation", "ClimbState"],
        },
        {
            "operation": "create animation slots",
            "target": target_anim_bp,
            "slots": ["ClimbStart", "ClimbLoop", "ClimbMantle", "ClimbDrop"],
            "compatible_animation_candidates": [item["object_path"] for item in candidate_anims[:20]],
        },
        {
            "operation": "validate",
            "target": target_bp or target_anim_bp,
            "reason": "Compile touched Blueprints and report unresolved graph/function/asset references.",
        },
    ]


def prototype_from_template(template, target_path, parameters=None):
    """Create a scan-backed prototype plan from a controlled template."""
    import unreal

    parameters = parameters or {}
    goal = parameters.get("feature_goal", "")
    words = _tokens(f"{template} {goal}")
    directory = parameters.get("directory") or "/Game/"
    assets = _asset_index(unreal, directory=directory)

    blueprints = assets.get("Blueprint", []) + assets.get("GameplayAbilityBlueprint", [])
    anim_bps = assets.get("AnimBlueprint", [])
    anims = assets.get("AnimSequence", [])
    skeletons = assets.get("Skeleton", [])
    skeletal_meshes = assets.get("SkeletalMesh", [])

    candidate_blueprints = _rank(blueprints, words)[:20]
    candidate_anim_bps = _rank(anim_bps, words)[:20]
    candidate_anims = _rank(anims, words)[:50]
    if not candidate_blueprints:
        candidate_blueprints = blueprints[:20]
    if not candidate_anim_bps:
        candidate_anim_bps = anim_bps[:20]
    if not candidate_anims:
        candidate_anims = anims[:50]

    if template == "rock_climbing":
        operation_plan = _rock_climbing_plan(candidate_blueprints, candidate_anim_bps, candidate_anims)
    else:
        operation_plan = [
            {"operation": "inspect candidate assets", "targets": [item["object_path"] for item in candidate_blueprints[:5]]},
            {"operation": "inspect animation candidates", "targets": [item["object_path"] for item in candidate_anims[:10]]},
            {"operation": "apply controlled template", "template": template, "target_path": target_path},
            {"operation": "validate references and compile Blueprints", "target_path": target_path},
        ]

    return json.dumps({
        "status": "planned",
        "template": template,
        "target_path": target_path,
        "feature_goal": goal,
        "asset_summary": {
            "blueprints": len(blueprints),
            "anim_blueprints": len(anim_bps),
            "animation_sequences": len(anims),
            "skeletons": len(skeletons),
            "skeletal_meshes": len(skeletal_meshes),
        },
        "candidate_assets": {
            "blueprints": candidate_blueprints[:10],
            "anim_blueprints": candidate_anim_bps[:10],
            "animation_sequences": candidate_anims[:20],
            "skeletons": skeletons[:10],
            "skeletal_meshes": skeletal_meshes[:10],
        },
        "operation_plan": operation_plan,
        "created_or_modified_assets": [],
        "animation_slots": ["ClimbStart", "ClimbLoop", "ClimbMantle", "ClimbDrop"] if template == "rock_climbing" else [],
        "validation_report": "No mutation was performed. This endpoint produced a project-aware plan from live assets.",
        "rollback_token": "",
    }, indent=2, default=str)
