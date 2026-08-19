from __future__ import annotations

import time
from types import SimpleNamespace

from tech_connector.game_engine.integration import dcc_host_qualification_service as qualification


class _FakeMultiSessionBridge:
    info = SimpleNamespace(protocol="socket-json")

    def find_ports(self):
        return [7011, 7012]

    def session_info(self, *, port: int, timeout: float):
        return {
            "ok": True,
            "port": port,
            "pid": 10000 + port,
            "session_id": f"motionbuilder:{10000 + port}:scene_{port}.fbx",
            "scene": f"scene_{port}.fbx",
            "timeout": timeout,
        }

    def health_check(self, *, timeout: float):
        return {"connected": True, "project": "qualification", "timeout": timeout}


def test_motionbuilder_is_qualified_against_its_animation_role() -> None:
    receipt = qualification.probe_dcc_host(
        "motionbuilder",
        bridge=_FakeMultiSessionBridge(),
        install_recovery_verified=True,
    )

    assert receipt.status == "qualified"
    assert receipt.live_readback
    assert receipt.multi_session_verified
    assert receipt.exact_session_identity_verified
    assert receipt.identity_latency_budget_met
    assert receipt.identity_latency_sample_count == 3
    assert all(len(row["identity_latency_samples_ms"]) == 3 for row in receipt.responding_sessions)
    assert not receipt.missing_representative_operations
    assert "character.plot_animation" in receipt.representative_operations
    assert "rig.create_ribbon" not in receipt.representative_operations
    assert "rig.create_ribbon" in qualification.HOST_ROLE_PROFILES["motionbuilder"].intentionally_out_of_scope
    assert set(receipt.qualification_scope) == {
        "characterization", "retargeting", "take_management", "animation_cleanup",
        "plotting", "native_constraints", "native_control_rig", "fbx_interchange",
    }
    assert "rig.build_full" in receipt.intentionally_out_of_scope
    assert "native constraints/control rigs" in receipt.role
    assert receipt.receipt_id
    assert receipt.integrity["status"] == "qualified"


def test_host_qualification_receipt_validates_and_rejects_tampering() -> None:
    bridge = _FakeMultiSessionBridge()
    receipt = qualification.probe_dcc_host(
        "motionbuilder", bridge=bridge, install_recovery_verified=True,
    )

    valid = qualification.validate_host_qualification_receipt(
        "motionbuilder", receipt, bridge=bridge,
    )
    tampered = receipt.to_dict()
    tampered["responding_sessions"][0]["pid"] = 9999
    invalid = qualification.validate_host_qualification_receipt(
        "motionbuilder", tampered, bridge=bridge,
    )

    assert valid["valid"]
    assert "receipt_binding" in invalid["gates"]


def test_qualification_does_not_claim_live_status_without_identity_readback() -> None:
    class UnresponsiveBridge(_FakeMultiSessionBridge):
        def session_info(self, *, port: int, timeout: float):
            return {"ok": False, "port": port, "error": "host busy"}

    receipt = qualification.probe_dcc_host("motionbuilder", bridge=UnresponsiveBridge())

    assert receipt.status == "structural"
    assert not receipt.live_readback
    assert "live_identity_readback" in receipt.missing_gates
    assert "install_recovery_readback" in receipt.missing_gates


def test_qualification_fails_closed_when_identity_latency_exceeds_budget() -> None:
    class SlowBridge(_FakeMultiSessionBridge):
        def session_info(self, *, port: int, timeout: float):
            time.sleep(0.015)
            return super().session_info(port=port, timeout=timeout)

    receipt = qualification.probe_dcc_host(
        "motionbuilder",
        bridge=SlowBridge(),
        install_recovery_verified=True,
        identity_latency_budget_ms=5.0,
    )

    assert receipt.status == "structural"
    assert not receipt.identity_latency_budget_met
    assert "identity_latency_budget" in receipt.missing_gates
    assert all(row["identity_latency_ms"] >= 5.0 for row in receipt.responding_sessions)


def test_multi_session_verification_rejects_duplicate_host_identity() -> None:
    class DuplicateIdentityBridge(_FakeMultiSessionBridge):
        def session_info(self, *, port: int, timeout: float):
            row = super().session_info(port=port, timeout=timeout)
            row.update({"pid": 1234, "session_id": "motionbuilder:1234:same_scene.fbx"})
            return row

    receipt = qualification.probe_dcc_host(
        "motionbuilder",
        bridge=DuplicateIdentityBridge(),
        install_recovery_verified=True,
    )

    assert receipt.live_readback
    assert not receipt.exact_session_identity_verified
    assert not receipt.multi_session_verified
    assert receipt.status == "structural"
    assert "exact_session_identity_readback" in receipt.missing_gates


def test_maya_install_recovery_is_proven_only_when_disk_and_runtime_versions_match(monkeypatch) -> None:
    class CurrentMayaBridge(_FakeMultiSessionBridge):
        def session_info(self, *, port: int, timeout: float):
            row = super().session_info(port=port, timeout=timeout)
            row.update({
                "bridge_bootstrap_version": "2",
                "bridge_bootstrap_source": "C:/Maya/2026/scripts/userSetup.py",
                "bridge_capture_installed": True,
            })
            return row

    monkeypatch.setattr(
        "tech_connector.bridges.maya.maya_livelink_plugin.verify_maya_livelink_installation",
        lambda: {
            "ok": True,
            "paths": [{"path": "C:/Maya/2026/scripts/userSetup.py", "current": True}],
        },
    )

    receipt = qualification.probe_dcc_host("maya", bridge=CurrentMayaBridge())

    assert receipt.status == "qualified"
    assert receipt.install_recovery_verified
    assert receipt.install_recovery_evidence["disk_bootstrap_verified"]
    assert receipt.install_recovery_evidence["runtime_bootstrap_current"]
    assert receipt.install_recovery_evidence["runtime_started_from_managed_setup"]
    assert receipt.install_recovery_evidence["fresh_reconnect_verified"]
    assert "install_recovery_readback" not in receipt.missing_gates


def test_qualification_receipt_round_trips_atomically(tmp_path) -> None:
    path = tmp_path / "qualification.json"
    receipt = qualification.probe_dcc_host(
        "motionbuilder",
        bridge=_FakeMultiSessionBridge(),
        install_recovery_verified=True,
    )

    ledger = qualification.store_qualification_receipt(receipt, path)
    reloaded = qualification.qualification_ledger(path)

    assert ledger["receipts"]["motionbuilder"]["status"] == "qualified"
    assert reloaded["summary"]["qualified_hosts"] == 1
    assert reloaded["receipts"]["motionbuilder"]["responding_sessions"][1]["port"] == 7012


def test_all_external_hosts_have_distinct_role_profiles_and_registered_workflows() -> None:
    assert len(qualification.HOST_ROLE_PROFILES) == 10
    assert len({profile.role for profile in qualification.HOST_ROLE_PROFILES.values()}) == 10
    for host, profile in qualification.HOST_ROLE_PROFILES.items():
        receipt = qualification.probe_dcc_host(host, bridge=_FakeMultiSessionBridge())
        assert not receipt.missing_representative_operations, host
        assert profile.representative_operations
