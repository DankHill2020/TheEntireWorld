import os
import sys

import pytest

from tech_connector.services.perspective_guide_solver_service import solve_perspective_guides


def test_two_point_guides_solve_rectilinear_camera_settings():
    result = solve_perspective_guides(
        "2-Point Perspective",
        {
            "VP1": (-384.0, 302.0),
            "VP2": (1664.0, 302.0),
            "VP5": (640.0, 360.0),
        },
        1280.0,
        720.0,
    )

    assert result.projection_model == "rectilinear"
    assert result.camera_settings["fov_degrees"] == pytest.approx(38.8, abs=0.2)
    assert result.camera_settings["focal_length_mm"] == pytest.approx(34.0, abs=0.3)
    assert result.confidence >= 0.8


def test_four_point_guides_solve_non_linear_projection_profile():
    result = solve_perspective_guides(
        "4-Point Perspective (Curvilinear)",
        {
            "VP1": (100.0, 360.0),
            "VP2": (1180.0, 360.0),
            "VP3": (640.0, 80.0),
            "VP4": (640.0, 640.0),
            "VP5": (640.0, 360.0),
        },
        1280.0,
        720.0,
    )

    assert result.projection_model == "four_point_curvilinear"
    assert result.projection_settings["projection_blend"] == 1.0
    assert result.projection_settings["curvature"] == pytest.approx(1.0)
    assert "focal_length_mm" in result.camera_settings


def test_mesh_viewer_guides_apply_to_camera():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["TECH_CONNECTOR_GPU_VIEWPORT"] = "0"
    os.environ["TECH_CONNECTOR_DCC_VIEWPORT_STREAM"] = "0"

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None

    from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport

    widget = ThreeDMeshPainterViewport()
    widget.resize(1280, 720)
    widget.set_shot_guide_mode("2-Point Perspective")
    result = widget.solve_shot_guides(apply_camera=True)

    assert result["projection_model"] == "rectilinear"
    assert widget.shot_guides_enabled is True
    assert widget.viewport_camera.fov_degrees == pytest.approx(result["camera_settings"]["fov_degrees"])
