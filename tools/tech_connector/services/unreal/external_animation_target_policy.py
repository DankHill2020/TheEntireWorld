"""Default target and acceptance gates for externally acquired character motion."""

from __future__ import annotations

from typing import Any


def _measured_proportions_match(evidence: dict[str, Any]) -> bool:
    metrics = evidence.get("proportion_metrics") or {}
    if not isinstance(metrics, dict) or not metrics:
        return False
    for value in metrics.values():
        row = dict(value or {})
        source = row.get("source")
        target = row.get("target")
        if source is None or target in (None, 0):
            return False
        relative_error = abs(float(source) - float(target)) / abs(float(target))
        if relative_error > float(row.get("tolerance_ratio", 0.05)):
            return False
    return True


def decide_external_animation_target(
    source_evidence: dict[str, Any] | None,
    *,
    selected_target_mesh: str = "",
    selected_target_skeleton: str = "",
    project_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Require retargeting unless compatibility with the selected target is proven."""

    evidence = dict(source_evidence or {})
    project_target = dict(project_target or {})
    target_mesh = str(selected_target_mesh or project_target.get("mesh_path") or "")
    target_skeleton = str(selected_target_skeleton or project_target.get("skeleton_path") or "")
    target_resolved = bool(target_skeleton)
    target_source = (
        "user_selected"
        if selected_target_mesh or selected_target_skeleton
        else ("project_knowledge" if target_resolved else "unresolved")
    )
    source_fingerprint = str(evidence.get("source_hierarchy_fingerprint") or "")
    target_fingerprint = str(evidence.get("target_hierarchy_fingerprint") or "")
    source_bones = {str(value) for value in evidence.get("source_bones") or []}
    required_bones = {str(value) for value in evidence.get("required_target_bones") or []}
    pose_error = evidence.get("reference_pose_max_error_degrees")
    pose_tolerance = float(evidence.get("reference_pose_tolerance_degrees") or 5.0)
    checks = {
        "hierarchy_fingerprint_match": bool(source_fingerprint and source_fingerprint == target_fingerprint),
        "required_bones_match": bool(required_bones and required_bones.issubset(source_bones)),
        "proportions_match": _measured_proportions_match(evidence),
        "reference_pose_match": pose_error is not None and float(pose_error) <= pose_tolerance,
    }
    already_imported_skeleton = str(evidence.get("unreal_skeleton_path") or "")
    if already_imported_skeleton:
        checks["selected_skeleton_match"] = already_imported_skeleton == target_skeleton
    direct_import_allowed = target_resolved and all(checks.values())
    return {
        "policy": "external_animation_target_v1",
        "target_mesh": target_mesh,
        "target_skeleton": target_skeleton,
        "target_source": target_source,
        "target_resolved": target_resolved,
        "checks": checks,
        "measurements": {
            "source_hierarchy_fingerprint": source_fingerprint,
            "target_hierarchy_fingerprint": target_fingerprint,
            "source_bone_count": len(source_bones),
            "required_bone_count": len(required_bones),
            "proportion_metrics": evidence.get("proportion_metrics") or {},
            "reference_pose_max_error_degrees": pose_error,
            "reference_pose_tolerance_degrees": pose_tolerance,
        },
        "direct_import_allowed": direct_import_allowed,
        "retargeting_required": target_resolved and not direct_import_allowed,
        "mutation_allowed": target_resolved,
        "action": (
            "direct_import_on_selected_skeleton"
            if direct_import_allowed
            else ("retarget_before_gameplay_import" if target_resolved else "resolve_target_skeleton")
        ),
        "missing_or_failed_evidence": [name for name, passed in checks.items() if not passed],
        "target_resolution_order": [
            "explicit user-selected target",
            "live selected character or AnimBlueprint Skeleton",
            "validated project knowledge profile",
            "request target selection",
        ],
        "postconditions": [
            "Imported AnimSequence Skeleton identity equals target_skeleton.",
            "Independent motion round trip preserves scale, orientation, connected limbs, and root/pelvis behavior.",
            "Contextual role acceptance passes before montage, AnimGraph, Motion Matching, or gameplay use.",
        ],
    }
