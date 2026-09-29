"""Evidence-backed release gates for the ten external DCC production journeys."""

from __future__ import annotations

from typing import Any

from tech_connector.game_engine.integration.dcc_capability_audit_service import audit_dcc_capabilities
from tech_connector.game_engine.integration.dcc_host_qualification_service import (
    DEFAULT_QUALIFICATION_MAX_AGE_SECONDS,
    HOST_ROLE_PROFILES,
    qualification_ledger,
    validate_host_qualification_receipt,
)
from tech_connector.game_engine.integration.dcc_production_workflow_service import (
    DEFAULT_WORKFLOW_RECEIPT_MAX_AGE_SECONDS,
    PRODUCTION_WORKFLOWS,
    workflow_receipt_ledger,
    validate_workflow_receipt,
    validate_workflow_catalog,
)
from tech_connector.game_engine.rendering.material_contract import provider_lookdev_capture_profile
from tech_connector.game_engine.integration.dcc_source_parity_qualification_service import (
    DEFAULT_SOURCE_PARITY_MAX_AGE_SECONDS,
    source_parity_ledger,
    validate_source_parity_receipt,
)


READINESS_SCHEMA = "tech_connector.dcc_release_readiness.v1"


def audit_dcc_release_readiness(
    *,
    qualification_receipts: dict[str, Any] | None = None,
    workflow_receipts: dict[str, Any] | None = None,
    source_parity_receipts: dict[str, Any] | None = None,
    source_parity_max_age_seconds: float = DEFAULT_SOURCE_PARITY_MAX_AGE_SECONDS,
    verify_live_source_sessions: bool = True,
    qualification_max_age_seconds: float = DEFAULT_QUALIFICATION_MAX_AGE_SECONDS,
    verify_live_host_sessions: bool = True,
    workflow_receipt_max_age_seconds: float = DEFAULT_WORKFLOW_RECEIPT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    qualifications = dict(
        qualification_ledger()["receipts"] if qualification_receipts is None else qualification_receipts
    )
    receipts = dict(
        workflow_receipt_ledger()["receipts"] if workflow_receipts is None else workflow_receipts
    )
    parity_receipts = dict(
        source_parity_ledger()["receipts"] if source_parity_receipts is None else source_parity_receipts
    )
    capability_rows = {
        row["host"]: row for row in audit_dcc_capabilities()["hosts"]
        if row["host"] != "tech_connector"
    }
    catalog = validate_workflow_catalog()
    hosts: list[dict[str, Any]] = []
    for host, profile in HOST_ROLE_PROFILES.items():
        capability = capability_rows.get(host, {})
        workflows = [workflow for workflow in PRODUCTION_WORKFLOWS.values() if workflow.host == host]
        structural_gates: list[str] = []
        evidence_gates: list[str] = []
        missing_operations = [
            operation
            for department in capability.get("departments") or []
            for operation in department.get("missing_operations") or []
        ]
        delegated_operations = [
            operation
            for department in capability.get("departments") or []
            for operation in department.get("delegated_operations") or []
        ]
        if not capability or capability.get("status") == "unsupported" or missing_operations:
            structural_gates.append("executable_operation_contract")
        if not workflows:
            structural_gates.append("production_workflow_contract")
        workflow_rows = []
        for workflow in workflows:
            workflow_gates: list[str] = []
            if not any(step.readback for step in workflow.steps):
                workflow_gates.append("workflow_readback_contract")
            if not any(step.artifact_parameters or step.output_artifact_keys for step in workflow.steps):
                workflow_gates.append("workflow_artifact_readback_contract")
            if not workflow.parity_checks:
                workflow_gates.append("workflow_parity_contract")
            if not workflow.restoration_requirements:
                workflow_gates.append("workflow_restoration_contract")
            structural_gates.extend(workflow_gates)
            receipt = _workflow_receipt(receipts.get(workflow.key))
            receipt_validation = validate_workflow_receipt(
                workflow.key,
                receipt,
                max_age_seconds=workflow_receipt_max_age_seconds,
            )
            receipt_status = "verified" if receipt_validation["valid"] else (
                "unrecorded" if not receipt else "invalid"
            )
            receipt_gates = []
            if not receipt_validation["valid"]:
                receipt_gates.append("verified_workflow_receipt")
                receipt_gates.extend(
                    f"workflow_receipt.{gate}" for gate in receipt_validation["gates"]
                )
            evidence_gates.extend(receipt_gates)
            workflow_rows.append({
                "workflow": workflow.key,
                "portable_outputs": list(workflow.portable_outputs),
                "parity_checks": list(workflow.parity_checks),
                "delegated_steps": list(catalog.get("delegated_steps", {}).get(workflow.key) or []),
                "structural_gates": sorted(set(workflow_gates)),
                "receipt_status": receipt_status,
                "receipt_gates": sorted(set(receipt_gates)),
                "receipt_validation": receipt_validation,
                "session_port": receipt.get("session_port"),
            })
        qualification = dict(qualifications.get(host) or {})
        qualification_validation = validate_host_qualification_receipt(
            host,
            qualification,
            max_age_seconds=qualification_max_age_seconds,
            require_live_sessions=verify_live_host_sessions,
        )
        qualification_status = "qualified" if qualification_validation["valid"] else (
            "unrecorded" if not qualification else "invalid"
        )
        if not qualification_validation["valid"]:
            evidence_gates.append("live_host_qualification")
            evidence_gates.extend(
                f"host_qualification.{gate}" for gate in qualification_validation["gates"]
            )
        source_parity = _nested_receipt(parity_receipts.get(host))
        source_parity_validation = validate_source_parity_receipt(
            host,
            source_parity,
            max_age_seconds=source_parity_max_age_seconds,
            require_live_session=verify_live_source_sessions,
        )
        source_parity_status = "qualified" if source_parity_validation["valid"] else (
            "unrecorded" if not source_parity else "invalid"
        )
        if not source_parity_validation["valid"]:
            evidence_gates.append("live_source_parity")
            evidence_gates.extend(
                f"source_parity.{gate}" for gate in source_parity_validation["gates"]
            )
        qualified_ports = {
            int(row.get("port") or 0)
            for row in qualification.get("responding_sessions") or []
            if isinstance(row, dict) and row.get("port")
        }
        source_port = int(source_parity.get("port") or 0)
        for workflow_row in workflow_rows:
            workflow_port = int(workflow_row.get("session_port") or 0)
            if workflow_row["receipt_status"] != "verified":
                continue
            if not workflow_port or workflow_port != source_port or workflow_port not in qualified_ports:
                workflow_row["receipt_gates"] = sorted(set([
                    *workflow_row["receipt_gates"], "cross_receipt_session_binding",
                ]))
                evidence_gates.append("cross_receipt_session_binding")
        structural_gates = sorted(set(structural_gates))
        evidence_gates = sorted(set(evidence_gates))
        if structural_gates:
            status = "incomplete"
        elif evidence_gates:
            status = "structural"
        else:
            status = "release_qualified"
        hosts.append({
            "host": host,
            "role": profile.role,
            "status": status,
            "capability_status": capability.get("status", "unsupported"),
            "declared_operations": int(capability.get("declared_operation_count") or 0),
            "executable_operations": int(capability.get("executable_operation_count") or 0),
            "missing_operations": missing_operations,
            "delegated_operations": delegated_operations,
            "lookdev_capture": provider_lookdev_capture_profile(host),
            "qualification_status": qualification_status,
            "qualification_validation": qualification_validation,
            "source_parity_status": source_parity_status,
            "source_parity_receipt": source_parity,
            "source_parity_validation": source_parity_validation,
            "workflows": workflow_rows,
            "structural_gates": structural_gates,
            "evidence_gates": evidence_gates,
        })
    return {
        "schema": READINESS_SCHEMA,
        "hosts": hosts,
        "summary": {
            "host_count": len(hosts),
            "release_qualified": sum(row["status"] == "release_qualified" for row in hosts),
            "structural": sum(row["status"] == "structural" for row in hosts),
            "incomplete": sum(row["status"] == "incomplete" for row in hosts),
            "delegated_operations": sum(len(row["delegated_operations"]) for row in hosts),
            "native_or_partial_lookdev_capture": sum(
                row["lookdev_capture"]["capture_status"] in {"native", "partial", "lookdev_only"}
                for row in hosts
            ),
            "unverified_workflows": sum(
                workflow["receipt_status"] != "verified"
                for row in hosts
                for workflow in row["workflows"]
            ),
            "unverified_source_parity": sum(
                row["source_parity_status"] != "qualified" for row in hosts
            ),
        },
    }


def _workflow_receipt(value: Any) -> dict[str, Any]:
    row = dict(value or {}) if isinstance(value, dict) else {}
    nested = row.get("receipt")
    return dict(nested) if isinstance(nested, dict) else row


def _nested_receipt(value: Any) -> dict[str, Any]:
    row = dict(value or {}) if isinstance(value, dict) else {}
    nested = row.get("receipt")
    return dict(nested) if isinstance(nested, dict) else row


__all__ = ["READINESS_SCHEMA", "audit_dcc_release_readiness"]
