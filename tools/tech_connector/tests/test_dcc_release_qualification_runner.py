from __future__ import annotations

from types import SimpleNamespace

from tech_connector.game_engine.integration import dcc_release_qualification_runner as runner


class _Bridge:
    pass


def _host_receipt(ports):
    return SimpleNamespace(
        responding_sessions=tuple({"port": port, "ok": True} for port in ports),
        to_dict=lambda: {"host": "maya", "status": "qualified", "responding_sessions": [{"port": port} for port in ports]},
    )


def test_release_runner_requires_exact_selection_when_multiple_sessions_exist(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runner, "probe_dcc_host", lambda *_args, **_kwargs: _host_receipt([7001, 7002]))
    monkeypatch.setattr(runner, "store_qualification_receipt", lambda *_args, **_kwargs: {})

    result = runner.qualify_dcc_release_host(
        "maya", workspace=tmp_path, bridge=_Bridge(), install_recovery_verified=True,
    )

    assert result["status"] == "selection_required"
    assert result["available_ports"] == [7001, 7002]


def test_release_runner_collects_all_receipts_for_one_pinned_session(monkeypatch, tmp_path) -> None:
    workflow = SimpleNamespace(key="maya.character_asset", host="maya", label="Character")
    workflow_receipt = SimpleNamespace(
        status="verified",
        to_dict=lambda: {"workflow": workflow.key, "host": "maya", "status": "verified"},
    )
    monkeypatch.setattr(runner, "PRODUCTION_WORKFLOWS", {workflow.key: workflow})
    monkeypatch.setattr(runner, "probe_dcc_host", lambda *_args, **_kwargs: _host_receipt([7001]))
    monkeypatch.setattr(runner, "store_qualification_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "qualify_dcc_source_parity", lambda *_args, **_kwargs: {"host": "maya", "status": "qualified"})
    monkeypatch.setattr(runner, "store_source_parity_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "execute_dcc_workflow", lambda *_args, **_kwargs: workflow_receipt)
    monkeypatch.setattr(runner, "store_workflow_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "qualification_ledger", lambda: {"receipts": {"maya": {}}})
    monkeypatch.setattr(runner, "source_parity_ledger", lambda: {"receipts": {"maya": {}}})
    monkeypatch.setattr(runner, "workflow_receipt_ledger", lambda: {"receipts": {workflow.key: {}}})
    monkeypatch.setattr(
        runner,
        "audit_dcc_release_readiness",
        lambda **_kwargs: {"hosts": [{"host": "maya", "status": "release_qualified", "evidence_gates": []}]},
    )
    events = []

    result = runner.qualify_dcc_release_host(
        "maya",
        workspace=tmp_path,
        bridge=_Bridge(),
        confirm_mutating=True,
        install_recovery_verified=True,
        progress_callback=events.append,
    )

    assert result["status"] == "release_qualified"
    assert result["session_port"] == 7001
    assert result["workflow_receipts"][workflow.key]["status"] == "verified"
    assert events[-1]["progress_percent"] == 100.0


def test_release_runner_passes_explicit_port_into_identity_probe(monkeypatch, tmp_path) -> None:
    observed = {}

    def probe(*_args, **kwargs):
        observed.update(kwargs)
        return _host_receipt([7001])

    monkeypatch.setattr(runner, "probe_dcc_host", probe)
    monkeypatch.setattr(runner, "store_qualification_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "qualify_dcc_source_parity", lambda *_args, **_kwargs: {"status": "qualified"})
    monkeypatch.setattr(runner, "store_source_parity_receipt", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "PRODUCTION_WORKFLOWS", {})
    monkeypatch.setattr(runner, "qualification_ledger", lambda: {"receipts": {"maya": {}}})
    monkeypatch.setattr(runner, "source_parity_ledger", lambda: {"receipts": {"maya": {}}})
    monkeypatch.setattr(runner, "workflow_receipt_ledger", lambda: {"receipts": {}})
    monkeypatch.setattr(
        runner,
        "audit_dcc_release_readiness",
        lambda **_kwargs: {"hosts": [{"host": "maya", "status": "blocked"}]},
    )

    result = runner.qualify_dcc_release_host(
        "maya",
        workspace=tmp_path,
        bridge=_Bridge(),
        session_port=7001,
        install_recovery_verified=True,
    )

    assert observed["requested_ports"] == (7001,)
    assert result["session_port"] == 7001
