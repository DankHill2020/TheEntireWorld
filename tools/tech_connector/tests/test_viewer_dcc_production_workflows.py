from __future__ import annotations

import pytest

from tech_connector.game_engine.integration import dcc_production_workflow_service as workflows
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewportHarness:
    pass


def test_viewer_audits_role_specific_workflows_for_all_ten_hosts() -> None:
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(), "engine.audit_dcc_workflows", {},
    )

    audit = result["dcc_workflow_audit"]
    assert audit["valid"]
    assert audit["workflow_count"] == 10
    assert audit["filtered_count"] == 10
    assert audit["release_readiness"]["summary"]["host_count"] == 10
    assert audit["release_readiness"]["summary"]["release_qualified"] == 0
    motionbuilder = next(row for row in audit["workflows"] if row["host"] == "motionbuilder")
    assert [step["operation"] for step in motionbuilder["steps"]] == [
        "io.import_fbx", "character.create_character", "character.plot_animation", "io.export_fbx", "character.inspect",
    ]


def test_viewer_workflow_audit_filters_release_readiness_by_host() -> None:
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(), "engine.audit_dcc_workflows", {"host": "unity"},
    )

    readiness = result["dcc_workflow_audit"]["release_readiness"]
    assert [row["host"] for row in readiness["hosts"]] == ["unity"]
    assert readiness["hosts"][0]["status"] == "structural"


def test_viewer_requires_confirmation_before_running_mutating_workflow(tmp_path) -> None:
    with pytest.raises(PermissionError, match="explicit confirmation"):
        ThreeDMeshPainterViewport._execute_tc_engine_command(
            _ViewportHarness(),
            "engine.run_dcc_workflow",
            {
                "workflow": "motionbuilder.retarget_plot",
                "workspace": str(tmp_path),
                "session_port": 7011,
            },
        )


def test_viewer_parses_selected_session_and_returns_workflow_receipt(monkeypatch, tmp_path) -> None:
    calls = []
    receipt = workflows.DccWorkflowReceipt(
        workflow="motionbuilder.retarget_plot",
        host="motionbuilder",
        session_port=7014,
        status="verified",
        steps=({"operation": "character.plot_animation", "ok": True},),
        artifacts=({"path": str(tmp_path / "motionbuilder_plotted.fbx")},),
        readback_complete=True,
        duration_ms=12.0,
        artifact_readback_complete=True,
        parity_results={check: True for check in workflows.PRODUCTION_WORKFLOWS["motionbuilder.retarget_plot"].parity_checks},
        parity_readback_complete=True,
    )

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return receipt

    monkeypatch.setattr(workflows, "execute_dcc_workflow", execute)
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        _ViewportHarness(),
        "engine.run_dcc_workflow",
        {
            "workflow": "motionbuilder.retarget_plot",
            "workspace": str(tmp_path),
            "session_key": "motionbuilder:7014",
            "confirm_mutating": True,
        },
    )

    assert calls[0][1]["session_port"] == 7014
    assert calls[0][1]["confirm_mutating"] is True
    assert result["dcc_workflow_receipt"]["status"] == "verified"
