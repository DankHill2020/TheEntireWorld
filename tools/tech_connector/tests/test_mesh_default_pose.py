from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel, MeshDefaultPose


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def test_mesh_restores_default_positions_without_replacing_uvs_or_paint() -> None:
    mesh = FBXMeshModel("pose_test")
    original = (mesh.vertices[0].x, mesh.vertices[0].y, mesh.vertices[0].z)
    original_uv = (mesh.vertices[0].u, mesh.vertices[0].v)
    mesh.quad_face_colors.append(QColor(17, 80, 90))

    mesh.vertices[0].x += 4.0
    mesh.vertices[0].u = 0.375
    restored = mesh.restore_default_pose()

    assert restored == len(mesh.vertices)
    assert (mesh.vertices[0].x, mesh.vertices[0].y, mesh.vertices[0].z) == original
    assert (mesh.vertices[0].u, mesh.vertices[0].v) == (0.375, original_uv[1])
    assert mesh.quad_face_colors[0].red() == 17


def test_mesh_can_replace_its_default_pose() -> None:
    mesh = FBXMeshModel("pose_test")
    old_revision = mesh.default_pose.revision
    mesh.vertices[0].y = 12.5

    pose = mesh.update_default_pose()
    mesh.vertices[0].y = -2.0
    mesh.restore_default_pose()

    assert pose.revision == old_revision + 1
    assert mesh.vertices[0].y == 12.5


def test_mesh_refuses_to_restore_pose_after_topology_changes() -> None:
    mesh = FBXMeshModel("pose_test")
    mesh.faces.pop()

    with pytest.raises(ValueError, match="topology has changed"):
        mesh.restore_default_pose()


def test_mesh_default_pose_round_trips_and_rejects_another_topology() -> None:
    source = FBXMeshModel("source")
    source.vertices[0].z = 3.25
    source.update_default_pose()
    serialized = source.default_pose_to_dict()

    restored = FBXMeshModel("restored")
    assert restored.load_default_pose(serialized) is True
    assert isinstance(restored.default_pose, MeshDefaultPose)
    assert restored.default_pose.positions[0][2] == 3.25

    restored.faces.pop()
    previous = restored.default_pose
    assert restored.load_default_pose(serialized) is False
    assert restored.default_pose is previous
