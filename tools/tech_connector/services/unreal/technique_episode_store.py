"""Persist and retrieve evidence-backed Unreal technique episodes.

Episodes are execution traces, not mechanic dispatch rules. A failed episode is
useful diagnostic history, while only an episode with every declared verification
gate satisfied may be reused as implementation knowledge.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable

from tech_connector.models.constants import APP_DIR


EPISODE_PATH = APP_DIR / "unreal_technique_episodes.jsonl"
REQUIRED_REUSE_GATES = (
    "capabilities_resolved",
    "assets_validated",
    "contextual_assets_passed",
    "blueprints_compiled",
    "graph_postconditions_passed",
    "construction_validated",
    "runtime_path_passed",
    "runtime_scenarios_passed",
    "gameplay_outcome_observed",
    "negative_paths_passed",
    "regressions_passed",
    "new_log_errors_absent",
)

TRUSTED_PROOF_ORIGINS = {
    "unreal_editor",
    "unreal_runtime",
    "unreal_automation",
    "unreal_functional_test",
    "human_observation",
}


def assess_system_proof(verification: dict[str, Any] | None) -> dict[str, Any]:
    """Require an observed Level 1-6 proof ladder for reusable systems."""

    verification = dict(verification or {})
    proof = dict(
        verification.get("gameplay_proof_contract")
        or verification.get("proof_contract")
        or {}
    )
    claims = [dict(row) for row in proof.get("proof_claims") or [] if isinstance(row, dict)]
    levels = {int(row.get("evidence_level") or 0) for row in claims}
    invalid_claims = [
        str(row.get("claim_id") or "unnamed_claim")
        for row in claims
        if row.get("status") != "passed"
        or row.get("evidence_origin") not in TRUSTED_PROOF_ORIGINS
        or not str(row.get("evidence_observed") or "").strip()
    ]
    missing_levels = sorted(set(range(1, 7)) - levels)
    return {
        "ok": bool(claims) and not missing_levels and not invalid_claims,
        "claim_count": len(claims),
        "covered_levels": sorted(levels),
        "missing_levels": missing_levels,
        "invalid_claims": invalid_claims,
    }


def _tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9_+.-]{2,}", str(value or "").lower())
        if token not in {"build", "create", "make", "system", "feature", "unreal", "engine"}
    }


def _read_rows(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, limit) :]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def record_technique_episode(
    *,
    request: str,
    technique_keys: Iterable[str],
    operations: Iterable[dict[str, Any]],
    verification: dict[str, Any] | None = None,
    project_context: dict[str, Any] | None = None,
    evidence: Iterable[dict[str, Any]] | None = None,
    decisions: Iterable[dict[str, Any]] | None = None,
    repairs: Iterable[dict[str, Any]] | None = None,
    scope: str = "system",
    required_gates: Iterable[str] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Record what happened and mark reuse eligibility from explicit gates."""

    verification = dict(verification or {})
    required = tuple(dict.fromkeys(str(gate) for gate in (required_gates or REQUIRED_REUSE_GATES)))
    gates = {gate: bool(verification.get(gate)) for gate in required}
    proof_assessment = assess_system_proof(verification)
    system_scope = str(scope or "system") in {"system", "feature", "system_recipe"}
    reusable = all(gates.values()) and (proof_assessment["ok"] if system_scope else True)
    row = {
        "schema": "ai_studio.unreal_technique_episode.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "request": str(request or ""),
        "scope": str(scope or "system"),
        "required_gates": list(required),
        "technique_keys": list(dict.fromkeys(str(key) for key in technique_keys if key)),
        "project_context": dict(project_context or {}),
        "evidence": [dict(item) for item in evidence or []],
        "decisions": [dict(item) for item in decisions or []],
        "operations": [dict(item) for item in operations or []],
        "repairs": [dict(item) for item in repairs or []],
        "verification": {
            **verification,
            "gates": gates,
            "system_proof": proof_assessment,
            "all_gates_passed": reusable,
        },
        "reusable": reusable,
    }
    episode_path = Path(path or EPISODE_PATH)
    episode_path.parent.mkdir(parents=True, exist_ok=True)
    with episode_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
    return row


def match_technique_episodes(
    request: str,
    *,
    technique_keys: Iterable[str] | None = None,
    project_context: dict[str, Any] | None = None,
    include_failed: bool = False,
    path: str | Path | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank episodes by intent, technique, engine, and target compatibility."""

    wanted = _tokens(request)
    wanted_keys = {str(key) for key in technique_keys or []}
    context = dict(project_context or {})
    engine_version = str(context.get("engine_version") or "")
    target_skeleton = str(context.get("target_skeleton") or "")
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in _read_rows(Path(path or EPISODE_PATH), 2000):
        if not include_failed:
            verification = dict(row.get("verification") or {})
            scope = str(row.get("scope") or "system")
            reusable = bool(row.get("reusable"))
            if scope in {"system", "feature", "system_recipe"}:
                reusable = bool(
                    reusable
                    and dict(verification.get("system_proof") or {}).get("ok")
                    and all(bool(dict(verification.get("gates") or {}).get(gate)) for gate in REQUIRED_REUSE_GATES)
                )
            if not reusable:
                continue
        row_keys = {str(key) for key in row.get("technique_keys") or []}
        if wanted_keys and not wanted_keys.intersection(row_keys):
            continue
        row_context = dict(row.get("project_context") or {})
        searchable = " ".join(
            (
                str(row.get("request") or ""),
                " ".join(row_keys),
                json.dumps(row.get("decisions") or [], default=str),
                json.dumps(row.get("repairs") or [], default=str),
            )
        )
        score = 2 * len(wanted.intersection(_tokens(searchable)))
        score += 4 * len(wanted_keys.intersection(row_keys))
        if engine_version and engine_version == str(row_context.get("engine_version") or ""):
            score += 3
        if target_skeleton and target_skeleton == str(row_context.get("target_skeleton") or ""):
            score += 5
        if score:
            ranked.append((score, str(row.get("recorded_at") or ""), row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [{**row, "match_score": score} for score, _date, row in ranked[: max(1, limit)]]
