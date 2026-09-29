from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.integration.launch_readiness_service import audit_launch_readiness


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_launch_audit_exposes_api_asset_capability_and_dcc_gates(tmp_path) -> None:
    tools_root = Path(__file__).resolve().parents[2]
    api = TCEditorAPI(tmp_path, database=AssetDatabase(tmp_path / "assets.sqlite3"))
    audit = audit_launch_readiness(tools_root, editor_api=api)
    gates = {row["gate"]: row for row in audit["gates"]}

    assert gates["public_package"]["status"] == "passed"
    assert gates["python_api_parity"]["status"] == "passed"
    assert gates["python_api_parity"]["evidence"]["operation_count"] >= 160
    assert gates["asset_ux_contracts"]["status"] == "passed"
    assert gates["asset_production_readiness"]["status"] == "blocked"
    assert gates["asset_production_readiness"]["evidence"]["counts"] == {
        "authoring_preview": 28, "experimental": 10, "runtime_ready": 21,
    }
    assert gates["dcc_qualification"]["evidence"]["host_count"] == 10
    assert len(gates["dcc_qualification"]["evidence"]["hosts"]) == 10
    assert "Production Workflow" in " ".join(gates["dcc_qualification"]["remediation"])
    assert audit["status"] == "blocked"
    assert set(audit["blocking_gates"]) == {
        "playable_project_qualification", "asset_production_readiness",
        "realtime_fx_qualification", "world_production_qualification", "content_production_qualification",
        "capability_evidence_qualification", "release_regression_qualification", "dcc_qualification",
    }


def test_editor_api_launch_contract_contains_only_callable_operations(tmp_path) -> None:
    tools_root = Path(__file__).resolve().parents[2]
    api = TCEditorAPI(tools_root, database=AssetDatabase(tmp_path / "assets.sqlite3"))
    contract = api.capability_contract()
    missing = [operation for section, operations in contract.items() if section.endswith("_operations")
               for operation in operations if not callable(getattr(api, operation, None))]
    assert missing == []
    assert api.audit_launch_readiness()["schema"] == "tech_connector.launch_readiness.v1"


def test_launch_readiness_panel_exposes_fail_closed_gates(tmp_path) -> None:
    from tech_connector.ui.game_engine.production_tools import LaunchReadinessPanel

    tools_root = Path(__file__).resolve().parents[2]
    panel = LaunchReadinessPanel(tools_root, AssetDatabase(tmp_path / "panel-assets.sqlite3"))

    assert panel.gates.rowCount() == 12
    assert panel.gates.columnCount() == 5
    assert panel.gates.horizontalHeaderItem(3).text() == "Next action"
    assert "BLOCKED" in panel.summary.text()
    assert "dcc_qualification" in set(panel.last_audit["blocking_gates"])
    fx_gate = next(row for row in panel.last_audit["gates"] if row["gate"] == "realtime_fx_qualification")
    assert fx_gate["status"] in {"passed", "blocked"}
    assert "capability_maturity" not in panel.last_audit["blocking_gates"]
    panel.production.setChecked(True)
    audit = panel.refresh()
    assert panel.gates.rowCount() == 13
    assert "production_controls" in audit["blocking_gates"]
    panel.close()
