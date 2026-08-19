from tech_connector.game_engine.integration.adaptive_scene_command_service import ADAPTIVE_SCENE_COMMANDS
from tech_connector.game_engine.integration.capability_maturity_service import audit_capability_maturity
from tech_connector.game_engine.integration import dcc_host_qualification_service as qualification
from tech_connector.game_engine.integration import dcc_source_parity_qualification_service as source_parity
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewportHarness:
    pass


def test_viewer_dcc_host_audit_reports_all_external_profiles() -> None:
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.audit_dcc_hosts",
        {},
    )

    audit = result["dcc_host_audit"]
    external = [row for row in audit["hosts"] if row["host"] != "tech_connector"]
    assert len(external) == 10
    assert audit["filtered_count"] == 11
    assert all(row["status"] in {"translated", "native", "partial"} for row in external)
    painter = next(row for row in external if row["host"] == "substance_painter")
    assert painter["status"] == "partial"
    assert "live-host qualification is tracked separately" in result["message"]


def test_viewer_dcc_host_audit_filters_by_host_and_department() -> None:
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.audit_dcc_hosts",
        {"host": "motionbuilder", "department": "rigging"},
    )

    hosts = result["dcc_host_audit"]["hosts"]
    assert len(hosts) == 1
    assert hosts[0]["host"] == "motionbuilder"
    assert [row["department"] for row in hosts[0]["departments"]] == ["rigging"]
    rigging = hosts[0]["departments"][0]
    assert not rigging["missing_operations"]
    assert "rig.create_ribbon" in rigging["out_of_scope_operations"]


def test_dcc_host_audit_command_has_interactive_evidence() -> None:
    assert "engine.audit_dcc_hosts" in ADAPTIVE_SCENE_COMMANDS
    audit = audit_capability_maturity([ADAPTIVE_SCENE_COMMANDS["engine.audit_dcc_hosts"]])
    capability = audit["capabilities"][0]
    assert capability["verified_maturity"] == "interactive"
    assert audit["declaration_gap"] == 1
    assert "native_backend" in capability["missing_gates"]


def test_viewer_live_qualification_persists_the_host_receipt(monkeypatch, tmp_path) -> None:
    receipt = qualification.DccHostQualificationReceipt(
        host="motionbuilder",
        role=qualification.HOST_ROLE_PROFILES["motionbuilder"].role,
        checked_at="2026-08-03T00:00:00+00:00",
        protocol="socket-json",
        representative_operations=("character.plot_animation",),
        missing_representative_operations=(),
        discovered_ports=(7011,),
        responding_sessions=({"ok": True, "port": 7011, "scene": "walk.fbx"},),
        preferred_port=7011,
        preferred_session_honored=True,
        multi_session_supported=True,
        multi_session_verified=False,
        live_readback=True,
        status="live",
        missing_gates=("install_recovery_readback",),
    )
    monkeypatch.setattr(qualification, "probe_dcc_host", lambda *_args, **_kwargs: receipt)
    ledger_path = tmp_path / "receipts.json"

    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.qualify_dcc_host",
        {"host": "motionbuilder", "ledger_path": str(ledger_path)},
    )

    assert result["dcc_host_qualification"]["status"] == "live"
    assert result["qualification_summary"]["recorded_hosts"] == 1
    assert qualification.qualification_ledger(ledger_path)["receipts"]["motionbuilder"]["preferred_session_honored"]


def test_viewer_source_parity_qualification_pins_and_persists_session(monkeypatch, tmp_path) -> None:
    class Bridge:
        def find_ports(self):
            return [7011, 7014]

    receipt = {
        "schema": source_parity.SOURCE_PARITY_QUALIFICATION_SCHEMA,
        "receipt_id": "source-proof",
        "host": "motionbuilder",
        "port": 7014,
        "status": "qualified",
        "missing_gates": [],
    }
    calls = []
    monkeypatch.setattr(qualification, "bridge_for_host", lambda _host: Bridge())
    monkeypatch.setattr(
        source_parity,
        "qualify_dcc_source_parity",
        lambda host, port, **kwargs: calls.append((host, port, kwargs)) or receipt,
    )
    ledger_path = tmp_path / "source-parity.json"

    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.qualify_dcc_source_parity",
        {
            "host": "motionbuilder",
            "session_port": 7014,
            "source_parity_ledger_path": str(ledger_path),
        },
    )

    assert calls[0][:2] == ("motionbuilder", 7014)
    assert result["dcc_source_parity_qualification"]["status"] == "qualified"
    assert source_parity.source_parity_ledger(ledger_path)["receipts"]["motionbuilder"]["port"] == 7014


def test_viewer_can_batch_qualify_available_sources_without_guessing_sessions(monkeypatch) -> None:
    batch = {
        "schema": "tech_connector.dcc_source_parity_batch.v1",
        "hosts": [
            {"host": "maya", "status": "qualified", "selected_port": 7002},
            {"host": "blender", "status": "selection_required", "ports": [7012, 7013]},
        ],
        "summary": {"qualified": 1, "selection_required": 1, "unavailable": 0, "failed": 0},
    }
    calls = []
    monkeypatch.setattr(
        source_parity,
        "qualify_available_dcc_sources",
        lambda **kwargs: calls.append(kwargs) or batch,
    )

    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.qualify_dcc_source_parity",
        {"all_available": True, "session_ports": {"maya": 7002}},
    )

    assert calls[0]["persist"] is True
    assert calls[0]["session_ports"] == {"maya": 7002}
    assert result["dcc_source_parity_batch"]["summary"]["selection_required"] == 1
    assert "1 require session selection" in result["message"]
