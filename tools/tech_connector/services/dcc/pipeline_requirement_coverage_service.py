from __future__ import annotations

"""Requirement ledger for proving that pipeline plans preserve every clause."""

import json
import re
from typing import Any

from tech_connector.services.prompt.prompt_task_splitter_service import compose_request


_STOPWORDS = {
    "about",
    "after",
    "before",
    "create",
    "from",
    "have",
    "into",
    "make",
    "pipeline",
    "please",
    "should",
    "that",
    "then",
    "this",
    "through",
    "using",
    "validation",
    "with",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split()
        if len(token) > 3 and token not in _STOPWORDS
    }


def _stage_evidence(stage: dict[str, Any]) -> str:
    return " ".join(
        [
            str(stage.get("host") or ""),
            str(stage.get("role") or ""),
            str(stage.get("operation") or ""),
            str(stage.get("callable") or ""),
            json.dumps(stage.get("params") or {}, default=str),
            json.dumps(stage.get("produces") or [], default=str),
            json.dumps(stage.get("validation") or [], default=str),
        ]
    )


def build_pipeline_requirement_manifest(prompt: str) -> dict[str, Any]:
    composed = compose_request(prompt).to_dict()
    requirements = []
    for index, clause in enumerate(composed.get("clauses") or [], start=1):
        requirements.append(
            {
                "id": str(clause.get("clause_id") or f"clause_{index}"),
                "requirement": str(
                    clause.get("source_text")
                    or clause.get("normalized_text")
                    or ""
                ).strip(),
                "role": str(clause.get("role") or ""),
                "action": str(clause.get("action") or ""),
                "attaches_to": str(clause.get("attaches_to") or ""),
                "depends_on": list(clause.get("depends_on") or []),
                "arguments": dict(clause.get("arguments") or {}),
                "references": dict(clause.get("references") or {}),
                "source_span": list(clause.get("source_span") or []),
            }
        )
    return {
        "framework": "pipeline_requirement_manifest_v1",
        "original_prompt": str(prompt or ""),
        "requirements": requirements,
        "requirement_count": len(requirements),
        "composed_request_confidence": composed.get("confidence"),
    }


def build_pipeline_requirement_ledger(
    prompt: str,
    stages: list[dict[str, Any]],
    *,
    requirement_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = dict(
        requirement_manifest or build_pipeline_requirement_manifest(prompt)
    )
    clauses = list(manifest.get("requirements") or [])
    rows = []
    for clause in clauses:
        text = str(clause.get("requirement") or "").strip()
        requirement_tokens = _tokens(text)
        candidates = []
        for stage in stages:
            evidence = _stage_evidence(stage)
            evidence_tokens = _tokens(evidence)
            overlap = sorted(requirement_tokens & evidence_tokens)
            coverage = len(overlap) / max(1, len(requirement_tokens))
            params_text = json.dumps(stage.get("params") or {}, default=str).lower()
            active_parameter_terms = [
                token
                for token in overlap
                if re.search(
                    rf'"[^"]*{re.escape(token)}[^"]*"\s*:\s*(?:true|[1-9]\d*)',
                    params_text,
                )
            ]
            host = str(stage.get("host") or "").replace("_", " ")
            host_match = bool(host and re.search(rf"\b{re.escape(host)}\b", text, re.I))
            score = (
                coverage
                + (0.2 if host_match else 0.0)
                + (0.2 if active_parameter_terms else 0.0)
            )
            if overlap or host_match:
                candidates.append(
                    {
                        "stage": stage.get("id"),
                        "operation": stage.get("operation"),
                        "score": round(score, 4),
                        "matched_terms": overlap,
                        "active_parameter_terms": active_parameter_terms,
                        "evidence": evidence[:1200],
                    }
                )
        candidates.sort(key=lambda item: (-item["score"], str(item["stage"])))
        best = candidates[0] if candidates else {}
        # This is retrieval evidence, not the semantic verdict. Ambiguous rows
        # are retained for the bounded plan critic instead of being discarded.
        rows.append(
            {
                "id": str(clause.get("clause_id") or f"clause_{len(rows) + 1}"),
                "requirement": text,
                "role": str(clause.get("role") or ""),
                "action": str(clause.get("action") or ""),
                "attaches_to": str(clause.get("attaches_to") or ""),
                "status": "evidence_found" if best.get("score", 0.0) >= 0.25 else "needs_semantic_check",
                "evidence": best,
                "alternates": candidates[1:3],
            }
        )
    return {
        "framework": "pipeline_requirement_ledger_v1",
        "requirements": rows,
        "requirement_count": len(rows),
        "evidence_found": sum(row["status"] == "evidence_found" for row in rows),
        "needs_semantic_check": sum(
            row["status"] == "needs_semantic_check" for row in rows
        ),
        "all_requirements_accounted_for": bool(rows)
        and all(row.get("evidence") for row in rows),
    }


def verify_pipeline_requirement_ledger(
    prompt: str,
    stages: list[dict[str, Any]],
    *,
    requirement_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = build_pipeline_requirement_ledger(
        prompt,
        stages,
        requirement_manifest=requirement_manifest,
    )
    from tech_connector.services.prompt.prompt_plan_verification_service import (
        verify_prompt_plan_alignment,
    )

    candidate_steps = [
        (
            f"{stage.get('host')}:{stage.get('operation')} "
            f"params={json.dumps(stage.get('params') or {}, default=str)} "
            f"validation={json.dumps(stage.get('validation') or [], default=str)}"
        )
        for stage in stages
    ]
    verdict = verify_prompt_plan_alignment(
        prompt,
        {
            "operation_plan": {
                "operation": "dynamic_cross_dcc_pipeline",
                "steps": candidate_steps,
            },
            "requirement_ledger": ledger,
        },
    )
    return {
        "framework": "verified_pipeline_requirement_ledger_v1",
        "ledger": ledger,
        "semantic_verdict": verdict,
        "matches_request": bool(verdict.get("matches_request")),
        "verification_available": verdict.get("status") != "verifier_unavailable",
    }
