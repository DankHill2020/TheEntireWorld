from __future__ import annotations

from tech_connector.game_engine.integration.dcc_host_qualification_service import HOST_ROLE_PROFILES
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS
from tech_connector.game_engine.integration.dcc_release_readiness_service import audit_dcc_release_readiness
from tech_connector.game_engine.integration import dcc_release_readiness_service as readiness_service


def test_release_readiness_separates_structural_and_live_evidence_gates() -> None:
    audit = audit_dcc_release_readiness()

    assert audit["summary"]["host_count"] == 10
    assert audit["summary"]["release_qualified"] == 0
    assert audit["summary"]["unverified_workflows"] == 10
    assert audit["summary"]["unverified_source_parity"] == 10
    assert audit["summary"]["native_or_partial_lookdev_capture"] == 7
    painter = next(row for row in audit["hosts"] if row["host"] == "substance_painter")
    assert painter["delegated_operations"] == ["material.apply"]
    assert "executable_operation_contract" not in painter["structural_gates"]
    assert "live_host_qualification" in painter["evidence_gates"]
    assert "live_source_parity" in painter["evidence_gates"]
    assert all(not row["structural_gates"] for row in audit["hosts"])
    motionbuilder = next(row for row in audit["hosts"] if row["host"] == "motionbuilder")
    assert motionbuilder["lookdev_capture"]["capture_status"] == "not_role_required"


def test_release_qualification_requires_verified_pinned_receipts_for_every_host(monkeypatch) -> None:
    host_ports = {
        workflow.host: 7000 + index
        for index, workflow in enumerate(PRODUCTION_WORKFLOWS.values())
    }
    qualifications = {
        host: {"status": "qualified", "responding_sessions": [{"port": host_ports[host]}]}
        for host in HOST_ROLE_PROFILES
    }
    receipts = {
        key: {"receipt": {"status": "verified", "session_port": host_ports[workflow.host]}}
        for key, workflow in PRODUCTION_WORKFLOWS.items()
    }
    source_parity = {
        host: {"status": "qualified", "port": host_ports[host]}
        for host in HOST_ROLE_PROFILES
    }
    monkeypatch.setattr(
        readiness_service,
        "validate_source_parity_receipt",
        lambda host, receipt, **_kwargs: {"host": host, "valid": True, "gates": [], "status": "valid"},
    )
    monkeypatch.setattr(
        readiness_service,
        "validate_host_qualification_receipt",
        lambda host, receipt, **_kwargs: {"host": host, "valid": True, "gates": [], "status": "valid"},
    )
    monkeypatch.setattr(
        readiness_service,
        "validate_workflow_receipt",
        lambda workflow, receipt, **_kwargs: {
            "workflow": workflow, "valid": True, "gates": [], "status": "valid",
        },
    )

    audit = audit_dcc_release_readiness(
        qualification_receipts=qualifications,
        workflow_receipts=receipts,
        source_parity_receipts=source_parity,
    )

    qualified = {row["host"] for row in audit["hosts"] if row["status"] == "release_qualified"}
    assert qualified == set(HOST_ROLE_PROFILES)
    assert audit["summary"]["release_qualified"] == 10
    assert audit["summary"]["unverified_source_parity"] == 0


def test_release_readiness_rejects_unsigned_source_parity_status() -> None:
    audit = audit_dcc_release_readiness(
        source_parity_receipts={"maya": {"status": "qualified"}},
    )
    maya = next(row for row in audit["hosts"] if row["host"] == "maya")

    assert maya["source_parity_status"] == "invalid"
    assert not maya["source_parity_validation"]["valid"]
    assert "source_parity.receipt_integrity" in maya["evidence_gates"]


def test_release_readiness_rejects_unsigned_host_qualification_status() -> None:
    audit = audit_dcc_release_readiness(
        qualification_receipts={"maya": {"status": "qualified"}},
    )
    maya = next(row for row in audit["hosts"] if row["host"] == "maya")

    assert maya["qualification_status"] == "invalid"
    assert not maya["qualification_validation"]["valid"]
    assert "host_qualification.receipt_integrity" in maya["evidence_gates"]


def test_release_readiness_requires_all_receipts_to_bind_the_same_session(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness_service,
        "validate_source_parity_receipt",
        lambda host, receipt, **_kwargs: {"host": host, "valid": True, "gates": []},
    )
    monkeypatch.setattr(
        readiness_service,
        "validate_host_qualification_receipt",
        lambda host, receipt, **_kwargs: {"host": host, "valid": True, "gates": []},
    )
    monkeypatch.setattr(
        readiness_service,
        "validate_workflow_receipt",
        lambda workflow, receipt, **_kwargs: {"workflow": workflow, "valid": True, "gates": []},
    )

    audit = audit_dcc_release_readiness(
        qualification_receipts={
            "unity": {"status": "qualified", "responding_sessions": [{"port": 7041}]},
        },
        workflow_receipts={
            "unity.prefab_asset": {"status": "verified", "session_port": 7042},
        },
        source_parity_receipts={"unity": {"status": "qualified", "port": 7041}},
    )
    unity = next(row for row in audit["hosts"] if row["host"] == "unity")

    assert unity["status"] == "structural"
    assert "cross_receipt_session_binding" in unity["evidence_gates"]
    assert "cross_receipt_session_binding" in unity["workflows"][0]["receipt_gates"]


def test_live_host_and_workflow_receipts_do_not_replace_source_parity() -> None:
    qualifications = {"unity": {"status": "qualified"}}
    receipts = {"unity.prefab_asset": {"status": "verified", "session_port": 7001}}

    audit = audit_dcc_release_readiness(
        qualification_receipts=qualifications,
        workflow_receipts=receipts,
    )
    unity = next(row for row in audit["hosts"] if row["host"] == "unity")

    assert unity["status"] == "structural"
    assert unity["source_parity_status"] == "unrecorded"
    assert "live_source_parity" in unity["evidence_gates"]


def test_verified_receipt_without_a_session_pin_remains_unqualified() -> None:
    qualifications = {"unity": {"status": "qualified"}}
    receipts = {"unity.prefab_asset": {"status": "verified", "session_port": None}}

    audit = audit_dcc_release_readiness(
        qualification_receipts=qualifications,
        workflow_receipts=receipts,
    )
    unity = next(row for row in audit["hosts"] if row["host"] == "unity")

    assert unity["status"] == "structural"
    assert "workflow_receipt.pinned_session_receipt" in unity["evidence_gates"]


def test_release_readiness_discovers_default_receipt_ledgers_only_when_unspecified(monkeypatch) -> None:
    calls = []

    def ledger(name):
        def load():
            calls.append(name)
            return {"receipts": {}}
        return load

    monkeypatch.setattr(readiness_service, "qualification_ledger", ledger("qualification"))
    monkeypatch.setattr(readiness_service, "workflow_receipt_ledger", ledger("workflow"))
    monkeypatch.setattr(readiness_service, "source_parity_ledger", ledger("source_parity"))

    audit_dcc_release_readiness(
        verify_live_source_sessions=False,
        verify_live_host_sessions=False,
    )
    assert calls == ["qualification", "workflow", "source_parity"]

    calls.clear()
    audit_dcc_release_readiness(
        qualification_receipts={},
        workflow_receipts={},
        source_parity_receipts={},
        verify_live_source_sessions=False,
        verify_live_host_sessions=False,
    )
    assert calls == []
