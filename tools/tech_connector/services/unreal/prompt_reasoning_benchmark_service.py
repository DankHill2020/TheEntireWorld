"""Evidence-oriented benchmark for prompt-built Unreal feature plans."""

from __future__ import annotations

from typing import Any


TRUSTED_RUNTIME_ORIGINS = {
    "unreal_runtime",
    "unreal_automation",
    "unreal_functional_test",
    "human_observation",
}


def _row(key: str, score: int, evidence: str) -> dict[str, Any]:
    return {"key": key, "score": max(0, min(2, int(score))), "max_score": 2, "evidence": evidence}


def evaluate_unreal_prompt_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Score planning and proof integrity without treating planned work as executed proof."""

    plan = dict(plan or {})
    evidence = dict(plan.get("evidence") or {})
    explicit = dict(dict(plan.get("requirement_contract") or {}).get("explicit") or {})
    proof = dict(plan.get("gameplay_proof_contract") or {})
    claims = list(proof.get("proof_claims") or [])
    architecture = dict(plan.get("architecture_decision") or {})
    candidates = list(evidence.get("related_animation_candidates") or [])
    techniques = list(dict(plan.get("expert_technique_selection") or {}).get("techniques") or [])
    fulfillment = list(plan.get("requirement_fulfillment") or [])
    operation_status = list(plan.get("operation_status") or [])
    generated_artifacts = list(plan.get("generated_artifacts") or plan.get("artifacts") or [])
    validation_evidence = list(plan.get("validation_evidence") or [])

    explicit_count = sum(bool(explicit.get(key)) for key in ("activation", "inputs", "timing", "scope"))
    rows = [
        _row(
            "requirement_preservation",
            2 if explicit_count == 4 else 1 if explicit_count else 0,
            f"Preserved {explicit_count}/4 explicit activation, input, timing, and scope fields.",
        ),
        _row(
            "live_project_grounding",
            2 if plan.get("target_asset") and evidence.get("skeletal_mesh") and evidence.get("animation_blueprint") else 1 if plan.get("target_asset") else 0,
            f"Target={plan.get('target_asset') or 'missing'}, mesh={evidence.get('skeletal_mesh') or 'missing'}, AnimBP={evidence.get('animation_blueprint') or 'missing'}.",
        ),
        _row(
            "architecture_integration",
            2 if architecture.get("current_animation_blueprint") and "Do not replace" in str(architecture.get("rejected_shortcut") or "") else 1 if architecture else 0,
            str(architecture.get("animation_integration") or "No integration decision recorded."),
        ),
        _row(
            "source_grounded_techniques",
            2 if any(row.get("sources") for row in techniques) else 1 if techniques else 0,
            f"Selected {len(techniques)} techniques; {sum(bool(row.get('sources')) for row in techniques)} include source records.",
        ),
        _row(
            "operation_executability",
            2 if not list(dict(plan.get("build_readiness") or {}).get("blocked_by") or []) and bool(dict(plan.get("self_review") or {}).get("all_operations_verified")) else 1 if plan.get("capability_acquisition") is not None else 0,
            (
                "Blocked operations: " + ", ".join(dict(plan.get("build_readiness") or {}).get("blocked_by") or [])
                if dict(plan.get("build_readiness") or {}).get("blocked_by")
                else "All selected operations resolve to callables."
            ),
        ),
        _row(
            "animation_contextuality",
            2 if candidates and all(row.get("acceptance") == "candidate_only" and any("contextual" in str(value).lower() for value in row.get("required_evidence") or []) for row in candidates) else 1 if candidates else 0,
            f"{len(candidates)} candidates remain gated by compatibility and contextual-use evidence.",
        ),
    ]

    levels = {int(claim.get("evidence_level") or 0) for claim in claims}
    rows.append(
        _row(
            "proof_contract_coverage",
            2 if set(range(1, 7)).issubset(levels) else 1 if levels else 0,
            "Covered evidence levels: " + ", ".join(str(value) for value in sorted(levels)),
        )
    )
    fulfilled = [
        row for row in fulfillment
        if str(dict(row or {}).get("status") or "") in {"planned", "implemented", "validated"}
    ]
    validated = [
        row for row in fulfillment
        if str(dict(row or {}).get("status") or "") == "validated"
    ]
    rows.extend(
        [
            _row(
                "requirement_fulfillment_trace",
                2 if fulfillment and len(fulfilled) == len(fulfillment) else 1 if fulfillment else 0,
                f"{len(fulfilled)}/{len(fulfillment)} requirements link to plan, implementation, or proof evidence.",
            ),
            _row(
                "requirement_validation_trace",
                2 if fulfillment and len(validated) == len(fulfillment) else 1 if validated else 0,
                f"{len(validated)}/{len(fulfillment)} requirements have validation evidence.",
            ),
            _row(
                "callable_chain_readiness",
                (
                    2
                    if operation_status and all(dict(row or {}).get("callable_found") for row in operation_status)
                    else 1
                    if operation_status
                    else 0
                ),
                f"{sum(bool(dict(row or {}).get('callable_found')) for row in operation_status)}/{len(operation_status)} operations resolve to callables.",
            ),
            _row(
                "generated_artifact_proof",
                2 if generated_artifacts and validation_evidence else 1 if generated_artifacts else 0,
                f"Artifacts={len(generated_artifacts)}, validation evidence rows={len(validation_evidence)}.",
            ),
        ]
    )

    def evidence_score(levels_wanted: set[int]) -> tuple[int, str]:
        relevant = [claim for claim in claims if int(claim.get("evidence_level") or 0) in levels_wanted]
        trusted_passes = [
            claim for claim in relevant
            if claim.get("status") == "passed" and claim.get("evidence_origin") in TRUSTED_RUNTIME_ORIGINS
        ]
        score = 2 if relevant and len(trusted_passes) == len(relevant) else 1 if relevant else 0
        return score, f"{len(trusted_passes)}/{len(relevant)} claims have trusted passing evidence."

    runtime_score, runtime_detail = evidence_score({3, 4})
    negative_score, negative_detail = evidence_score({5})
    regression_score, regression_detail = evidence_score({6})
    rows.extend(
        [
            _row("runtime_and_gameplay_evidence", runtime_score, runtime_detail),
            _row("negative_and_boundary_evidence", negative_score, negative_detail),
            _row("regression_evidence", regression_score, regression_detail),
        ]
    )
    pending = [claim for claim in claims if claim.get("status") != "passed"]
    completion_claimed = str(plan.get("status") or "").lower() in {"completed", "working", "verified", "shippable_candidate"}
    honest = (not completion_claimed and bool(pending)) or (completion_claimed and not pending)
    rows.append(
        _row(
            "completion_honesty",
            2 if honest else 0,
            f"Plan status={plan.get('status')}; pending claims={len(pending)}; completion claimed={completion_claimed}.",
        )
    )
    score = sum(row["score"] for row in rows)
    maximum = sum(row["max_score"] for row in rows)
    return {
        "framework": "unreal_prompt_reasoning_benchmark_v1",
        "score": score,
        "max_score": maximum,
        "ratio": score / maximum if maximum else 0.0,
        "categories": rows,
        "verified_complete": not pending and bool(claims),
    }


def compare_benchmark_assessments(
    candidate: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    candidate_rows = {row["key"]: row for row in candidate.get("categories") or []}
    reference_rows = {row["key"]: row for row in reference.get("categories") or []}
    keys = list(dict.fromkeys([*candidate_rows, *reference_rows]))
    deltas = []
    for key in keys:
        ours = int(candidate_rows.get(key, {}).get("score") or 0)
        theirs = int(reference_rows.get(key, {}).get("score") or 0)
        deltas.append({"key": key, "candidate": ours, "reference": theirs, "delta": ours - theirs})
    return {
        "framework": "unreal_prompt_reasoning_comparison_v1",
        "candidate_score": candidate.get("score", 0),
        "reference_score": reference.get("score", 0),
        "deltas": deltas,
    }
