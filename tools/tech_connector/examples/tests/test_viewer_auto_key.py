import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_auto_key_keys_only_committed_transform_group_at_current_frame() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        viewer.editable_rig_graph.add_node("Control", "dag.control", node_id="control")
        viewer.auto_key_enabled = True
        viewer._current_dcc_frame = 17
        proxy = {
            "provider_id": "tech_connector",
            "native_id": "control",
            "local_transform": {
                "translation": [4.0, 5.0, 6.0],
                "rotation": [10.0, 20.0, 30.0],
                "scale": [1.0, 1.0, 1.0],
            },
        }

        ok, _message = viewer.auto_key_committed_transform(proxy, "translate")
        take = viewer.editable_rig_graph.animation[viewer.active_animation_take_id]
        curves = take["layers"]["BaseAnimation"]["curves"]

        assert ok
        assert sorted(curves) == ["control.translateX", "control.translateY", "control.translateZ"]
        assert [curves[f"control.translate{axis}"]["keys"][0]["value"] for axis in "XYZ"] == [4.0, 5.0, 6.0]
        assert all(curves[f"control.translate{axis}"]["keys"][0]["frame"] == 17 for axis in "XYZ")
    finally:
        viewer.close()
        app.processEvents()
