"""Match inspected animation hierarchies to verified retarget source profiles."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "knowledge" / "animation_source_profiles.json"
)


def load_animation_source_profiles(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load data-only source profiles from the knowledge directory."""

    source = Path(path).resolve() if path else DEFAULT_PROFILE_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [dict(row) for row in payload.get("profiles") or [] if isinstance(row, dict)]


def _base_name(value: Any) -> str:
    return str(value or "").split("|")[-1].split(":")[-1]


def match_animation_source_profile(
    hierarchy: dict[str, Any],
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require exact required names and parent edges before exposing a HIK map."""

    joints = [dict(row) for row in hierarchy.get("joints") or [] if isinstance(row, dict)]
    bone_names = {_base_name(row.get("name") or row.get("path")) for row in joints}
    parent_by_bone = {
        _base_name(row.get("name") or row.get("path")): _base_name(row.get("parent"))
        for row in joints
    }
    attempts = []
    for raw in profiles if profiles is not None else load_animation_source_profiles():
        profile = deepcopy(raw)
        required = {str(value) for value in profile.get("required_bones") or []}
        missing = sorted(required - bone_names)
        failed_edges = []
        for parent, child in profile.get("parent_constraints") or []:
            if parent_by_bone.get(str(child)) != str(parent):
                failed_edges.append([str(parent), str(child)])
        accepted = bool(required) and not missing and not failed_edges
        attempts.append(
            {
                "profile_id": str(profile.get("id") or ""),
                "accepted": accepted,
                "missing_bones": missing,
                "failed_parent_constraints": failed_edges,
            }
        )
        if accepted:
            return {
                "ok": True,
                "profile": profile,
                "profile_id": str(profile.get("id") or ""),
                "source_mapping": deepcopy(profile.get("hik_mapping") or {}),
                "observed_bone_count": len(bone_names),
                "attempts": attempts,
            }
    return {
        "ok": False,
        "profile": {},
        "profile_id": "",
        "source_mapping": {},
        "observed_bone_count": len(bone_names),
        "attempts": attempts,
        "requires_knowledge": True,
        "reason": "No verified source hierarchy profile matched exactly.",
    }
