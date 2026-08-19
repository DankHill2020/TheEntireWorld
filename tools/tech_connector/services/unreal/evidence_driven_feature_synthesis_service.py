"""Generic, evidence-driven synthesis policy for prompt-built Unreal systems.

This module deliberately knows nothing about individual mechanics.  It defines
the evidence, contract, capability, and runtime gates that every generated
system must satisfy before it can be learned as a reusable recipe.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from tech_connector.models.constants import APP_DIR
from tech_connector.services.jsonl_retention_service import append_jsonl_record
from tech_connector.services.task_playbook_service import best_practice_research_query


VERIFIED_RECIPE_PATH = APP_DIR / "unreal_verified_feature_recipes.jsonl"

CONTRACT_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {"id": "stimulus", "question": "What input, event, overlap, trace, timer, or gameplay message activates the system?"},
    {"id": "observations", "question": "What world, actor, component, network, and asset facts must be measured?"},
    {"id": "guards", "question": "What conditions make activation valid, invalid, interruptible, or mutually exclusive?"},
    {"id": "state", "question": "What authoritative states and transitions exist, including enter, update, exit, cancel, and recovery?"},
    {"id": "effects", "question": "What gameplay, movement, spawn, damage, puzzle, camera, audio, or visual effects occur?"},
    {"id": "presentation", "question": "What animation, montage slot, state machine, VFX, audio, and UI contracts represent the state?"},
    {"id": "assets", "question": "Which concrete assets are required and what compatibility, provenance, and license checks apply?"},
    {"id": "authority", "question": "Which object owns state and what replication, prediction, save/load, and multiplayer rules apply?"},
    {"id": "failure", "question": "How does the system recover from misses, interruption, missing assets, invalid references, and partial execution?"},
    {"id": "verification", "question": "Which compile, topology, asset, runtime, visual, log, and boundary assertions prove the behavior?"},
)

REQUIRED_EVIDENCE_FIELDS = ("source_url", "source_kind", "claim", "applies_to_version")
REQUIRED_SPEC_FIELDS = (
    "stimuli",
    "observations",
    "guards",
    "states",
    "effects",
    "presentation",
    "assets",
    "failure_paths",
    "runtime_scenarios",
)
REQUIRED_VERIFICATION_GATES = (
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


def derive_prompt_requirement_contract(prompt: str) -> dict[str, Any]:
    """Preserve explicit behavior clauses before any architecture is selected."""

    text = " ".join(str(prompt or "").split())
    lower = text.lower()
    timing = []
    for match in re.finditer(
        r"\b(?:for\s+)?(?:more\s+than|at\s+least|after|over)\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b",
        lower,
    ):
        source_text = re.sub(r"^for\s+", "", match.group(0)).strip()
        timing.append(
            {
                "operator": "greater_than_or_equal" if "at least" in match.group(0) else "greater_than",
                "seconds": float(match.group(1)),
                "source_text": source_text,
            }
        )
    inputs = []
    input_match = re.search(
        r"\b(?:hold|holding|press|pressing)\s+([a-z0-9_ +/]+?)(?=\s+(?:for|more|at|while|when|to)\b|[.,;]|$)",
        lower,
    )
    if input_match:
        raw = input_match.group(1).strip()
        inputs = [value.strip().upper() for value in re.split(r"\s+or\s+|\s*/\s*", raw) if value.strip()]
    scopes = [
        match.group(0).strip()
        for match in re.finditer(
            r"\b(?:any|every|all)\s+(?:[a-z][a-z0-9_-]*\s+){0,2}"
            r"(?:wall|surface|obstacle|actor|target|enemy|object|level|character|mesh|skeleton|asset)\b",
            lower,
        )
    ]
    activation = ""
    activation_match = re.search(r"\b(?:by|when)\s+(.+?)(?=[.;]|$)", text, re.I)
    if activation_match:
        activation = activation_match.group(1).strip()
    if not activation:
        for sentence in re.split(r"(?<=[.!?;])\s+", text):
            causal = re.search(r"^(.+?)\s+(?:starts?|triggers?|activates?|begins?|causes?)\b", sentence, re.I)
            if causal:
                activation = causal.group(1).strip()
                break
    requested_artifacts = []
    if re.search(r"\b(?:abp|animation blueprint)\b", lower):
        requested_artifacts.append("Animation Blueprint")
    if re.search(r"\b(?:component|actor component)\b", lower):
        requested_artifacts.append("Actor Component")

    explicit = {
        "activation": activation,
        "inputs": inputs,
        "timing": timing,
        "scope": scopes,
        "requested_artifacts": requested_artifacts,
    }
    unresolved = [
        "Authoritative gameplay owner and animation presentation boundary",
        "Enter, active update, exit, cancellation, interruption, and recovery states",
        "World-query shape, distance, collision policy, normal/geometry acceptance, and contact-loss hysteresis",
        "Movement model, speed, orientation, root-motion policy, and network authority",
        "Animation role set and contextual acceptance criteria for each role",
        "Positive, negative, boundary, regression, and player-visible runtime scenarios",
    ]
    return {
        "framework": "prompt_requirement_contract_v1",
        "source_prompt": text,
        "explicit": explicit,
        "unresolved_before_mutation": unresolved,
        "dimensions": [
            {
                "id": row["id"],
                "question": row["question"],
                "status": "partially_resolved" if row["id"] in {"stimulus", "assets", "presentation"} else "unresolved",
            }
            for row in CONTRACT_DIMENSIONS
        ],
        "mutation_allowed": False,
        "reason": "The prompt contract is preserved, but architecture and executable proof details still require project evidence.",
    }


def _keywords(prompt: str, limit: int = 18) -> list[str]:
    stop = {
        "build", "create", "make", "add", "system", "feature", "unreal", "engine",
        "with", "from", "into", "that", "this", "should", "need", "needs", "user",
        "prompt", "using", "work", "working", "able", "every", "anything",
    }
    values: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", prompt or ""):
        normalized = token.lower()
        if normalized in stop or normalized in values:
            continue
        values.append(normalized)
        if len(values) >= limit:
            break
    return values


def load_verified_feature_recipes(
    *, path: str | Path | None = None, limit: int = 500
) -> list[dict[str, Any]]:
    recipe_path = Path(path or VERIFIED_RECIPE_PATH)
    if not recipe_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in recipe_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        verification = dict(row.get("verification") or {}) if isinstance(row, dict) else {}
        gate_values_present = all(gate in verification for gate in REQUIRED_VERIFICATION_GATES)
        system_proof = dict(verification.get("system_proof") or {})
        if (
            isinstance(row, dict)
            and verification.get("all_gates_passed")
            and gate_values_present
            and all(bool(verification.get(gate)) for gate in REQUIRED_VERIFICATION_GATES)
            and system_proof.get("ok")
        ):
            rows.append(row)
    return rows[-max(1, int(limit or 500)):]


def match_verified_feature_recipes(
    prompt: str, *, path: str | Path | None = None, limit: int = 5
) -> list[dict[str, Any]]:
    wanted = set(_keywords(prompt))
    ranked = []
    for recipe in load_verified_feature_recipes(path=path):
        searchable = " ".join(
            str(recipe.get(key) or "") for key in ("request", "title", "summary", "tags")
        ).lower()
        score = sum(1 for token in wanted if token in searchable)
        if score:
            ranked.append((score, recipe))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("verified_at") or "")), reverse=False)
    return [{**row, "match_score": score} for score, row in ranked[:max(1, limit)]]


def build_feature_research_plan(
    prompt: str,
    *,
    engine_version: str = "5.8",
    project_evidence: dict[str, Any] | None = None,
    research_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe how to learn an unknown system without guessing its implementation."""

    project_evidence = dict(project_evidence or {})
    research_mode = dict(research_mode or {})
    terms = " ".join(_keywords(prompt)) or "gameplay feature"
    base_query = best_practice_research_query(
        f"Unreal Engine {engine_version} {prompt}", host="unreal"
    )
    queries = [
        {
            "purpose": "engine_contract",
            "query": base_query,
            "source_policy": "Epic documentation and Unreal Engine API references only",
            "enabled": bool(research_mode.get("official_docs", True)),
        },
        {
            "purpose": "architecture_comparison",
            "query": f"Unreal Engine {engine_version} {terms} implementation architecture runtime validation",
            "source_policy": "Primary repositories or clearly licensed technical references",
            "enabled": bool(research_mode.get("web_techniques", False) or research_mode.get("github_examples", False)),
        },
        {
            "purpose": "asset_acquisition",
            "query": f"{terms} animation asset Unreal compatible license download",
            "source_policy": "Provider page must expose format, license, source identity, and contextual preview or description",
            "enabled": True,
        },
    ]
    learned = match_verified_feature_recipes(prompt)
    return {
        "framework": "unreal_evidence_driven_synthesis_v1",
        "request": prompt,
        "engine_version": engine_version,
        "contract_dimensions": list(CONTRACT_DIMENSIONS),
        "requirement_contract": derive_prompt_requirement_contract(prompt),
        "research_queries": queries,
        "matched_verified_recipes": learned,
        "project_evidence_present": bool(project_evidence),
        "source_acceptance": {
            "engine_api": "official_or_live_reflection_required",
            "architecture": "at_least_one_primary_or_two_independent_sources",
            "third_party_code": "identity_and_license_required",
            "external_assets": "context_preview_format_license_hash_and_provenance_required",
            "unknown_claims": "remain_explicit_and_block_mutation",
        },
        "knowledge_choice": {
            "required": not bool(learned),
            "options": ["add_knowledge_first", "run_with_current_knowledge"],
            "default": "add_knowledge_first",
            "run_with_current_knowledge_constraint": "May prototype only in isolated assets; cannot report completion without every verification gate.",
        },
    }


def validate_synthesized_feature_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Reject a model-authored feature spec that lacks executable evidence."""

    spec = dict(spec or {})
    missing_fields = [field for field in REQUIRED_SPEC_FIELDS if not spec.get(field)]
    evidence_rows = list(spec.get("evidence") or [])
    invalid_evidence = [
        index
        for index, row in enumerate(evidence_rows)
        if not isinstance(row, dict) or any(not row.get(field) for field in REQUIRED_EVIDENCE_FIELDS)
    ]
    operations = list(spec.get("operations") or [])
    unresolved_operations = [
        row.get("operation") or row.get("id") or f"operation_{index}"
        for index, row in enumerate(operations)
        if not isinstance(row, dict)
        or not row.get("callable")
        or not row.get("postconditions")
    ]
    asset_failures = [
        row.get("role") or row.get("path") or f"asset_{index}"
        for index, row in enumerate(spec.get("assets") or [])
        if not isinstance(row, dict)
        or not row.get("compatibility_checks")
        or (row.get("external") and not row.get("provenance"))
    ]
    ok = not (missing_fields or invalid_evidence or unresolved_operations or asset_failures)
    return {
        "ok": ok,
        "missing_contract_fields": missing_fields,
        "invalid_evidence_rows": invalid_evidence,
        "unresolved_operations": unresolved_operations,
        "invalid_assets": asset_failures,
        "mutation_allowed": ok,
    }


def promote_verified_feature_recipe(
    spec: dict[str, Any],
    verification: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Learn only systems proven by all static and runtime gates."""

    spec_validation = validate_synthesized_feature_spec(spec)
    gate_status = {
        gate: bool(verification.get(gate)) for gate in REQUIRED_VERIFICATION_GATES
    }
    from tech_connector.services.unreal.technique_episode_store import assess_system_proof

    system_proof = assess_system_proof(verification)
    all_gates = bool(
        spec_validation.get("ok")
        and all(gate_status.values())
        and system_proof.get("ok")
    )
    result = {
        "ok": all_gates,
        "learned": False,
        "spec_validation": spec_validation,
        "verification": {
            **gate_status,
            "system_proof": system_proof,
            "all_gates_passed": all_gates,
        },
    }
    if not all_gates:
        result["error"] = "Feature recipe was not learned because one or more evidence/runtime gates failed."
        return result
    row = {
        "schema": "ai_studio.unreal_verified_feature_recipe.v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "request": spec.get("request") or "",
        "title": spec.get("title") or "",
        "summary": spec.get("summary") or "",
        "tags": spec.get("tags") or [],
        "spec": spec,
        "verification": {
            **gate_status,
            "system_proof": system_proof,
            "all_gates_passed": True,
        },
    }
    recipe_path = Path(path or VERIFIED_RECIPE_PATH)
    append_jsonl_record(
        recipe_path,
        row,
        max_bytes=16 * 1024 * 1024,
        archive_count=3,
    )
    from tech_connector.services.unreal.technique_episode_store import record_technique_episode

    episode = record_technique_episode(
        request=str(spec.get("request") or ""),
        technique_keys=list(spec.get("technique_keys") or []),
        operations=list(spec.get("operations") or []),
        verification=verification,
        project_context=dict(spec.get("project_context") or {}),
        evidence=list(spec.get("evidence") or []),
        decisions=list(spec.get("decisions") or []),
        repairs=list(spec.get("repairs") or []),
    )
    result.update({"learned": True, "path": str(recipe_path), "recipe": row, "technique_episode": episode})
    return result
