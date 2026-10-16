"""Regressions for avoiding redundant DCC/engine viewport work."""

from __future__ import annotations

from types import SimpleNamespace

from tech_connector.ui.dcc_viewer.gpu_viewport import ThreeDGpuViewport


class _Root:
    def __init__(self):
        self.properties = []

    def setProperty(self, name, value):
        self.properties.append((name, value))


def test_unchanged_camera_does_not_resend_qml_properties() -> None:
    root = _Root()
    viewport = SimpleNamespace(
        _last_camera_state=None,
        _camera_eye=(0.0, 0.0, 0.0),
        _camera_target=(0.0, 0.0, 0.0),
        rootObject=lambda: root,
    )

    ThreeDGpuViewport.set_camera(viewport, (1, 2, 3), (0, 0, 0), 45.0, 1.5)
    ThreeDGpuViewport.set_camera(viewport, (1, 2, 3), (0, 0, 0), 45.0, 1.5)

    assert len(root.properties) == 4


def test_unchanged_lighting_profile_does_not_resend_qml_properties() -> None:
    root = _Root()
    viewport = SimpleNamespace(
        _last_lighting_profile="",
        _pending_lighting_profile="",
        rootObject=lambda: root,
    )

    ThreeDGpuViewport.set_lighting_profile(viewport, "daylight")
    first_property_count = len(root.properties)
    ThreeDGpuViewport.set_lighting_profile(viewport, "daylight")

    assert first_property_count > 0
    assert len(root.properties) == first_property_count
    ThreeDGpuViewport.set_lighting_profile(viewport, "unlit_reference")
    properties = dict(root.properties)
    assert properties["lightingModel"] == "unlit"


def test_viewport_visualization_options_reach_the_renderer() -> None:
    root = _Root()
    viewport = SimpleNamespace(
        _viewport_mode="lit",
        _viewport_exposure=1.0,
        _grid_visible=True,
        rootObject=lambda: root,
    )

    assert ThreeDGpuViewport.set_viewport_mode(viewport, "Lighting Only") == "lighting_only"
    assert ThreeDGpuViewport.set_viewport_exposure(viewport, 20.0) == 8.0
    assert ThreeDGpuViewport.set_grid_visible(viewport, False) is False
    properties = dict(root.properties)
    assert properties == {
        "viewportMode": "lighting_only",
        "viewportExposure": 8.0,
        "showEditorGrid": False,
    }


def test_scene_uploads_coalesce_and_position_only_changes_avoid_static_rebuild() -> None:
    mesh = object()
    calls = []
    viewport = SimpleNamespace(
        geometry=SimpleNamespace(),
        _last_scene_key=None,
        _pending_scene_key=None,
        _pending_deformation_bindings={},
        update_positions=lambda _mesh: calls.append("positions") or True,
        set_mesh=lambda _mesh, topology_signature="": calls.append(("static", topology_signature)),
    )

    ThreeDGpuViewport.set_scene(viewport, mesh, {}, topology_signature="10:12", geometry_revision=1)
    ThreeDGpuViewport.set_scene(viewport, mesh, {}, topology_signature="10:12", geometry_revision=1)
    assert calls == [("static", "10:12")]

    viewport._last_scene_key = viewport._pending_scene_key
    viewport._pending_scene_key = None
    ThreeDGpuViewport.set_scene(viewport, mesh, {}, topology_signature="10:12", geometry_revision=2)
    assert calls == [("static", "10:12"), "positions"]
