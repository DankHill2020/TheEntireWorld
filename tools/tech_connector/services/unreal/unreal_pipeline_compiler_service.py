from __future__ import annotations

"""Compile explicit single-host Unreal workflows into editable pipeline nodes."""

from typing import Any

from tech_connector.services.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.services.dcc.operation_contract_service import (
    resolve_operation_contract,
)
from tech_connector.services.unreal.feature_planning_service import (
    build_unreal_requirement_preview,
)


def compile_unreal_operation_pipeline(
    prompt: str,
    *,
    requirement_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preview = build_unreal_requirement_preview(prompt)
    operation_rows = list(preview.get("operations") or [])
    graph = ActionGraph(
        goal=prompt,
        intent="dynamic_unreal_operation_pipeline",
        confidence=0.9,
        diagnostics=[
            (
                f"Expanded the Unreal request into {len(operation_rows)} operation "
                "contracts from the canonical feature planner."
            )
        ],
    )
    gaps = []
    required_inputs = []
    stages = []
    selected_contracts = []
    previous_id = ""

    for index, row in enumerate(operation_rows, start=1):
        operation = str(row.get("operation") or "").strip()
        if not operation:
            continue
        if not row.get("callable") or not str(row.get("function") or "").strip():
            gaps.append(
                {
                    "kind": "operation_evidence_gap",
                    "host": "unreal",
                    "operation": operation,
                    "required_capability": operation,
                    "phase": str(row.get("phase") or ""),
                    "request_fragment": str(row.get("postcondition") or ""),
                    "reason": (
                        f"The Unreal requirement planner selected `{operation}`, but "
                        "the canonical operation inventory has no executable callable."
                    ),
                    "execution_blocked": True,
                    "acquisition": {
                        "strategy": "confirm_or_implement_then_resume",
                        "search_order": [
                            "canonical Unreal operation inventory",
                            "unreal_tools Python adapters",
                            "reflected Unreal Python API",
                            "AIStudioBridge native wrappers",
                        ],
                        "required_proof": [
                            "callable implementation",
                            "non-placeholder behavior",
                            "disposable Unreal fixture",
                            "structured mutation/readback evidence",
                        ],
                        "resume_original_request": True,
                    },
                }
            )
            continue

        resolved = resolve_operation_contract(operation, host="unreal")
        contract = dict(resolved.get("contract") or {})
        required = list(
            contract.get("required")
            or row.get("required_arguments")
            or []
        )
        optional = dict(
            contract.get("optional")
            or row.get("optional_arguments")
            or {}
        )
        params = {
            **optional,
            **dict(row.get("planned_arguments") or {}),
        }
        stage_id = str(row.get("id") or f"unreal_operation_{index:02d}")
        for argument in required:
            if params.get(argument) not in (None, "", [], {}):
                continue
            params.setdefault(argument, None)
            required_inputs.append(
                {
                    "stage": stage_id,
                    "host": "unreal",
                    "operation": operation,
                    "argument": argument,
                    "question": (
                        f"What should `{argument}` use for `{operation}`?"
                    ),
                }
            )

        metadata = dict(contract.get("metadata") or {})
        produces = list(contract.get("produces") or ["result"])
        action = graph.add(
            "execute_dcc",
            {
                "host": "unreal",
                "operation": operation,
                "callable": str(
                    contract.get("callable")
                    or row.get("function")
                    or ""
                ),
                "params": params,
                "operation_contract": contract,
                "produces": produces,
                "consumes": list(contract.get("consumes") or []),
                "validation": list(
                    contract.get("validation")
                    or [str(row.get("postcondition") or "operation result")]
                ),
                "rollback": list(contract.get("rollback") or []),
            },
            depends_on=[previous_id] if previous_id else [],
            id=stage_id,
            title=str(row.get("phase") or operation),
            requires_approval=bool(
                contract.get("mutates_project")
                or row.get("mutates_project")
            ),
        )
        previous_id = action.id
        evidence = {
            "level": metadata.get("evidence_level", "registered_callable"),
            "live_validated": bool(metadata.get("live_validated", False)),
            "validation_receipt": dict(
                metadata.get("validation_receipt") or {}
            ),
        }
        stages.append(
            {
                "id": stage_id,
                "host": "unreal",
                "phase": str(row.get("phase") or ""),
                "domain": str(row.get("domain") or ""),
                "operation": operation,
                "callable": str(
                    contract.get("callable")
                    or row.get("function")
                    or ""
                ),
                "params": params,
                "produces": produces,
                "validation": list(
                    contract.get("validation")
                    or [str(row.get("postcondition") or "operation result")]
                ),
                "rollback": list(contract.get("rollback") or []),
                "evidence": evidence,
            }
        )
        selected_contracts.append(contract or dict(row))

    data = graph.to_dict()
    evidence_rows = [
        {
            "stage": stage["id"],
            "operation": stage["operation"],
            **stage["evidence"],
        }
        for stage in stages
    ]
    data.update(
        {
            "framework": "dynamic_unreal_operation_pipeline_v1",
            "success": bool(stages) and not required_inputs and not gaps,
            "execution_ready": bool(stages) and not required_inputs and not gaps,
            "hosts": ["unreal"],
            "stages": stages,
            "required_inputs": required_inputs,
            "capability_gaps": gaps,
            "gaps": gaps,
            "selected_contracts": selected_contracts,
            "requirement_manifest": dict(requirement_manifest or {}),
            "requirement_preview": preview,
            "evidence_summary": {
                "stage_count": len(evidence_rows),
                "live_validated_count": sum(
                    bool(row["live_validated"]) for row in evidence_rows
                ),
                "not_live_validated_count": sum(
                    not bool(row["live_validated"]) for row in evidence_rows
                ),
                "stages": evidence_rows,
            },
        }
    )
    data["validation"] = validate_action_graph(data)
    return data
