"""Direct-manipulation coverage for live viewport FX emitters."""

from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF

from tech_connector.game_engine.runtime.tc_effect_system_service import (
    create_effect_world,
    effect_emitter_anchor,
)
from tech_connector.ui.dcc_viewer.mesh_painter.geometry import MayaViewportCamera
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_01 import ThreeDMeshPainterViewportMixin01


class _Canvas:
    def dcc_viewport_projection_rect(self) -> QRectF:
        return QRectF(0.0, 0.0, 800.0, 600.0)

    def update(self) -> None:
        pass


class _InteractionHost(ThreeDMeshPainterViewportMixin01):
    def __init__(self) -> None:
        self.simulation_world = create_effect_world("sparks", quality="realtime", seed=7)
        self.simulation_initial_world = copy.deepcopy(self.simulation_world)
        self.viewport_camera = MayaViewportCamera()
        self.viewer_coord_space = "maya"
        self.viewer_coord_up_axis = "y"
        self.canvas = _Canvas()
        self._fx_manipulator_emitter_id = self.simulation_world.effect_system.emitters[0].emitter_id
        self._fx_manipulator_move_particles = False
        self._fx_emitter_drag = None
        self._resolved_shaded_status = ""

    def update_viewport_status(self) -> None:
        pass


def test_screen_space_emitter_drag_updates_live_and_reset_worlds() -> None:
    host = _InteractionHost()
    emitter = host.active_fx_emitter()
    original = effect_emitter_anchor(emitter)
    handle = host.fx_emitter_screen_handle()
    assert handle is not None

    assert host.begin_fx_emitter_drag(handle["screen"])
    moved = host.update_fx_emitter_drag(QPointF(handle["screen"].x() + 120.0, handle["screen"].y() - 45.0))
    committed = host.end_fx_emitter_drag()

    assert moved is not None and committed == moved
    assert effect_emitter_anchor(emitter) != original
    initial_emitter = host.simulation_initial_world.effect_system.emitters[0]
    assert effect_emitter_anchor(initial_emitter) == moved
    assert host._fx_emitter_drag is None
