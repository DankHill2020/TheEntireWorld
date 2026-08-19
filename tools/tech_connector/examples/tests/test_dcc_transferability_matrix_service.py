from __future__ import annotations

from tech_connector.services.dcc.transferability_matrix_service import (
    analyze_feature_transferability,
    build_cross_dcc_chat_context,
    build_dcc_transferability_matrix,
    department_transfer_summary,
    infer_native_feature_keys,
)


def test_transferability_matrix_uses_existing_operation_contracts() -> None:
    matrix = build_dcc_transferability_matrix()

    assert matrix["schema"] == "tech_connector.dcc_transferability_matrix.v1"
    assert matrix["feature_count"] >= 6
    assert "retargeting" in matrix["features"]
    assert "dcc_to_tc_migration" in matrix["features"]
    assert "cloth_physics" in matrix["features"]
    assert "destruction_fracture" in matrix["features"]
    assert "procedural_generation" in matrix["features"]
    assert "skinning_weights" in matrix["features"]
    assert "unreal" in matrix["hosts"]
    assert matrix["summary"]["animation_takes"]["transfer_formats"]
    assert matrix["summary"]["cloth_physics"]["engine_readiness"]["ready"]
    assert matrix["summary"]["destruction_fracture"]["engine_readiness"]["engine_paths"]
    assert matrix["summary"]["dcc_to_tc_migration"]["engine_readiness"]["ready"]


def test_feature_report_exposes_hosts_formats_and_gaps() -> None:
    report = analyze_feature_transferability("retargeting").to_dict()

    assert report["feature"]["key"] == "retargeting"
    assert "unreal" in report["hosts"]
    assert report["hosts"]["unreal"]["roles"]
    assert report["engine_readiness"]["priority"] == "required"
    assert report["engine_readiness"]["ready"]
    assert isinstance(report["critical_gaps"], list)


def test_chat_context_infers_relevant_cross_dcc_features() -> None:
    keys = infer_native_feature_keys("retarget mocap to unreal sequencer camera shot with timecode and cloth destruction paint skin weights")
    context = build_cross_dcc_chat_context("retarget mocap to unreal sequencer camera shot with timecode and cloth destruction paint skin weights")

    assert "retargeting" in keys
    assert "shots_cameras" in keys
    assert "animation_takes" in keys
    assert "cloth_physics" in keys
    assert "destruction_fracture" in keys
    assert "skinning_weights" in keys
    assert "Cross-DCC transferability context" in context
    assert "Retargeting" in context
    assert "Shots / Cameras / Sequencer" in context
    assert "Cloth / Soft Body Physics" in context
    assert "Skinning / Weight Painting" in context
    assert "engine path:" in context


def test_department_summary_returns_department_features() -> None:
    summary = department_transfer_summary("simulation")

    assert summary["department"] == "simulation"
    assert "cloth_physics" in summary["features"]
    assert "destruction_fracture" in summary["features"]
    assert summary["features"]["cloth_physics"]["benchmark_tools"]
