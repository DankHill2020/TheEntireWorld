"""Audit whether a declared Unreal expert has earned its label."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tech_connector.services.unreal.technique_episode_store import match_technique_episodes


def _registered_operations() -> set[str]:
    from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS

    return set(UNREAL_OPERATIONS)


def audit_expert_techniques(
    selection: dict[str, Any],
    *,
    project_context: dict[str, Any] | None = None,
    isolated_probe_evidence: dict[str, bool] | None = None,
    episode_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return qualification evidence without upgrading unresolved experts."""

    project_context = dict(project_context or {})
    probe_evidence = dict(isolated_probe_evidence or {})
    registered = _registered_operations()
    rows = []
    for technique in selection.get("techniques") or []:
        key = str(technique.get("key") or "")
        operations = [str(value) for value in technique.get("operations") or []]
        unresolved = [operation for operation in operations if operation not in registered]
        sources = [dict(value) for value in technique.get("sources") or []]
        source_rows_valid = bool(sources) and all(
            row.get("url") and row.get("kind") and row.get("claim") for row in sources
        )
        episodes = match_technique_episodes(
            str(selection.get("request") or key),
            technique_keys=[key],
            project_context=project_context,
            path=episode_path,
            limit=3,
        )
        checks = {
            "sources_validated": source_rows_valid,
            "operations_resolved": bool(operations) and not unresolved,
            "isolated_probe_passed": bool(probe_evidence.get(key)) or bool(episodes),
            "verified_episode_exists": bool(episodes),
        }
        qualified = all(checks.values())
        rows.append(
            {
                "technique_key": key,
                "expert": technique.get("expert"),
                "status": "verified_expert" if qualified else "provisional",
                "checks": checks,
                "unresolved_operations": unresolved,
                "matched_verified_episodes": episodes,
                "missing_qualifications": [name for name, passed in checks.items() if not passed],
            }
        )
    return {
        "framework": "unreal_expert_qualification_v1",
        "engine_version": str(project_context.get("engine_version") or ""),
        "all_experts_verified": bool(rows) and all(row["status"] == "verified_expert" for row in rows),
        "experts": rows,
    }
