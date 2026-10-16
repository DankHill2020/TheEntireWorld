"""One-session orchestration for complete external-DCC release evidence."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Callable

from tech_connector.game_engine.integration.dcc_host_qualification_service import (
    HOST_ROLE_PROFILES,
    bridge_for_host,
    probe_dcc_host,
    qualification_ledger,
    store_qualification_receipt,
)
from tech_connector.game_engine.integration.dcc_production_workflow_service import (
    PRODUCTION_WORKFLOWS,
    execute_dcc_workflow,
    store_workflow_receipt,
    workflow_receipt_ledger,
)
from tech_connector.game_engine.integration.dcc_release_readiness_service import (
    audit_dcc_release_readiness,
)
from tech_connector.game_engine.integration.dcc_source_parity_qualification_service import (
    qualify_dcc_source_parity,
    source_parity_ledger,
    store_source_parity_receipt,
)


DCC_RELEASE_RUN_SCHEMA = "tech_connector.dcc_release_qualification_run.v1"


def qualify_dcc_release_host(
    host: str,
    *,
    workspace: str | Path,
    session_port: int | None = None,
    confirm_mutating: bool = False,
    install_recovery_verified: bool = False,
    bridge: Any | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancellation_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Collect every release receipt for one host against one pinned session.

    Host identity and source parity are read-only. Production workflows run only
    when ``confirm_mutating`` is explicit, and every stage retains its normal
    signed/fingerprinted receipt in the canonical ledger.
    """

    key = str(host or "").strip().lower()
    if key not in HOST_ROLE_PROFILES:
        raise ValueError(f"Unsupported DCC qualification host: {host}")
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = bridge if bridge is not None else bridge_for_host(key)
    events: list[dict[str, Any]] = []

    def cancelled() -> bool:
        return bool(cancellation_event is not None and cancellation_event.is_set())

    def publish(stage: str, message: str, percent: float) -> None:
        event = {
            "schema": DCC_RELEASE_RUN_SCHEMA,
            "host": key,
            "stage": stage,
            "message": message,
            "progress_percent": max(0.0, min(100.0, float(percent))),
        }
        events.append(event)
        if progress_callback is not None:
            progress_callback(dict(event))

    publish("host_qualification", f"Checking {key} bridge identity and recovery evidence.", 5.0)
    host_receipt = probe_dcc_host(
        key,
        bridge=target,
        requested_ports=(int(session_port),) if session_port is not None else (),
        install_recovery_verified=bool(install_recovery_verified),
    )
    store_qualification_receipt(host_receipt)
    if cancelled():
        return _cancelled_result(key, events, "Cancelled after host qualification.")

    ports = [int(row.get("port") or 0) for row in host_receipt.responding_sessions if int(row.get("port") or 0) > 0]
    selected_port = int(session_port) if session_port is not None else None
    if selected_port is not None and selected_port not in ports:
        return {
            "schema": DCC_RELEASE_RUN_SCHEMA,
            "status": "selected_session_unavailable",
            "host": key,
            "available_ports": ports,
            "selected_port": selected_port,
            "events": events,
            "host_receipt": host_receipt.to_dict(),
        }
    if selected_port is None:
        if len(ports) == 1:
            selected_port = ports[0]
        elif len(ports) > 1:
            return {
                "schema": DCC_RELEASE_RUN_SCHEMA,
                "status": "selection_required",
                "host": key,
                "available_ports": ports,
                "events": events,
                "host_receipt": host_receipt.to_dict(),
            }
        else:
            return {
                "schema": DCC_RELEASE_RUN_SCHEMA,
                "status": "host_unavailable",
                "host": key,
                "available_ports": [],
                "events": events,
                "host_receipt": host_receipt.to_dict(),
            }

    publish("source_parity", f"Capturing read-only source parity from {key}:{selected_port}.", 25.0)
    parity_receipt = qualify_dcc_source_parity(key, selected_port, bridge=target)
    store_source_parity_receipt(parity_receipt)
    if cancelled():
        return _cancelled_result(key, events, "Cancelled after source-parity qualification.")

    workflows = [workflow for workflow in PRODUCTION_WORKFLOWS.values() if workflow.host == key]
    workflow_receipts: dict[str, dict[str, Any]] = {}
    if confirm_mutating:
        for index, workflow in enumerate(workflows):
            if cancelled():
                return _cancelled_result(key, events, "Cancelled before the next production workflow.")
            start_percent = 45.0 + (45.0 * index / max(1, len(workflows)))
            publish("production_workflow", f"Running {workflow.label} on {key}:{selected_port}.", start_percent)
            receipt = execute_dcc_workflow(
                workflow.key,
                workspace=root / workflow.key.replace(".", "_"),
                session_port=selected_port,
                confirm_mutating=True,
                cancellation_event=cancellation_event,
                progress_callback=progress_callback,
            )
            workflow_receipts[workflow.key] = receipt.to_dict()
            if receipt.status == "verified":
                store_workflow_receipt(receipt)
    else:
        publish(
            "production_workflow",
            "Read-only evidence is complete. Explicit mutation approval is still required for the production workflow.",
            70.0,
        )

    publish("readiness_audit", "Validating pinned receipts and live-session continuity.", 95.0)
    readiness = audit_dcc_release_readiness(
        qualification_receipts=qualification_ledger()["receipts"],
        source_parity_receipts=source_parity_ledger()["receipts"],
        workflow_receipts=workflow_receipt_ledger()["receipts"],
    )
    host_readiness = next((row for row in readiness["hosts"] if row["host"] == key), {})
    status = str(host_readiness.get("status") or "blocked")
    publish("completed", f"{key} release qualification is {status.replace('_', ' ')}.", 100.0)
    return {
        "schema": DCC_RELEASE_RUN_SCHEMA,
        "status": status,
        "host": key,
        "session_port": selected_port,
        "mutating_workflows_approved": bool(confirm_mutating),
        "host_receipt": host_receipt.to_dict(),
        "source_parity_receipt": parity_receipt,
        "workflow_receipts": workflow_receipts,
        "host_readiness": host_readiness,
        "events": events,
    }


def _cancelled_result(host: str, events: list[dict[str, Any]], message: str) -> dict[str, Any]:
    return {
        "schema": DCC_RELEASE_RUN_SCHEMA,
        "status": "cancelled",
        "host": host,
        "message": message,
        "events": list(events),
    }


__all__ = ["DCC_RELEASE_RUN_SCHEMA", "qualify_dcc_release_host"]
