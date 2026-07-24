from __future__ import annotations

"""Compatibility facade over the unified typed operation contract graph."""

from dataclasses import asdict, dataclass
from typing import Any

from tech_connector.services.dcc.dynamic_pipeline_compiler_service import (
    compile_dynamic_pipeline,
    extract_ordered_hosts,
    infer_pipeline_format,
    infer_pipeline_subject,
)
from tech_connector.services.dcc.operation_contract_service import (
    OperationContract,
    transfer_contracts,
)


@dataclass(frozen=True)
class TransferTemplate:
    key: str
    host: str
    role: str
    format: str
    operation: str
    callable: str
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    supports_animation: bool = False
    supports_static_mesh: bool = False
    supports_skeletal_mesh: bool = False
    validation: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _template(contract: OperationContract, format_name: str = "") -> TransferTemplate:
    return TransferTemplate(
        key=contract.key,
        host=contract.host,
        role=contract.role,
        format=format_name or (contract.formats[0] if contract.formats else "scene"),
        operation=contract.operation,
        callable=contract.callable,
        consumes=contract.consumes,
        produces=contract.produces,
        labels=(contract.label,),
        supports_animation="animation" in contract.subjects,
        supports_static_mesh="static_mesh" in contract.subjects,
        supports_skeletal_mesh="skeletal_mesh" in contract.subjects,
        validation=contract.validation,
    )


def _all_templates() -> tuple[TransferTemplate, ...]:
    rows = []
    for contract in transfer_contracts():
        formats = contract.formats or ("scene",)
        rows.extend(_template(contract, format_name) for format_name in formats)
    return tuple(rows)


# Preserved for older importers. It is generated from the authoritative
# operation contracts and is no longer maintained independently.
TRANSFER_TEMPLATES = _all_templates()


def extract_host_sequence(prompt: str) -> list[str]:
    return extract_ordered_hosts(prompt)


def infer_transfer_format(prompt: str) -> str:
    return infer_pipeline_format(prompt)


def infer_transfer_subject(prompt: str) -> str:
    return infer_pipeline_subject(prompt)


def templates_for(
    host: str,
    *,
    role: str | None = None,
    format: str | None = None,
    subject: str = "asset",
) -> list[TransferTemplate]:
    rows = []
    for contract in transfer_contracts():
        if contract.host != host:
            continue
        if role and contract.role != role:
            continue
        if format and format not in contract.formats:
            continue
        if subject != "asset" and subject not in contract.subjects:
            continue
        rows.append(_template(contract, format or ""))
    return rows


def plan_transfer_permutation(prompt: str) -> dict[str, Any]:
    plan = compile_dynamic_pipeline(prompt)
    return {
        "success": bool(plan.get("selected_contracts")) and not bool(plan.get("gaps")),
        "hosts": list(plan.get("hosts") or []),
        "format": str(plan.get("format") or ""),
        "subject": str(plan.get("subject") or ""),
        "steps": [
            {
                "key": row["key"],
                "host": row["host"],
                "role": row["role"],
                "format": (row.get("formats") or ["scene"])[0],
                "operation": row["operation"],
                "callable": row["callable"],
                "consumes": list(row.get("consumes") or []),
                "produces": list(row.get("produces") or []),
                "labels": [row["label"]],
                "supports_animation": "animation" in (row.get("subjects") or []),
                "supports_static_mesh": "static_mesh" in (row.get("subjects") or []),
                "supports_skeletal_mesh": "skeletal_mesh" in (row.get("subjects") or []),
                "validation": list(row.get("validation") or []),
            }
            for row in plan.get("selected_contracts") or []
        ],
        "data_edges": list(plan.get("data_edges") or []),
        "required_inputs": list(plan.get("required_inputs") or []),
        "reason": "; ".join(
            str(gap.get("message") or gap.get("reason") or "")
            for gap in plan.get("gaps") or []
        ),
        "gaps": list(plan.get("gaps") or []),
        "framework": plan.get("framework"),
    }
