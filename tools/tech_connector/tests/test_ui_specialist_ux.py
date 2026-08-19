"""Regression coverage for cleaned specialist authoring surfaces."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world, set_effect_parameter
from tech_connector.ui.dcc_viewer.driver_widget import DccDriverDialog
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport
from tech_connector.ui.game_engine.animation_timeline import AnimationFrameSequence, AnimationTimelineBar
from tech_connector.ui.game_engine.fx_properties import FxPropertiesDialog
from tech_connector.ui.image_viewer.editor import ImageEditorWidget


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


class _DriverHost(QWidget):
    def _dcc_bridge_port_for_host(self, _host: str):
        return None

    def append(self, _message: str) -> None:
        return None


def test_dcc_driver_prioritizes_connection_state_and_relevant_setup() -> None:
    _application()
    host = _DriverHost()
    dialog = DccDriverDialog(host)

    assert dialog.windowTitle() == "DCC Control Center"
    assert dialog.status_label.property("statusState") == "error"
    assert dialog.setup_group.isHidden()

    dialog._select_host("blender")
    assert not dialog.setup_group.isHidden()
    assert len(dialog.setup_buttons) == 2
    dialog.close()
    host.close()


def test_image_editor_uses_stable_modes_and_exclusive_visual_tool_state() -> None:
    _application()
    editor = ImageEditorWidget()

    assert editor.mode_combo.currentData() == "standard"
    assert editor.tool_buttons["brush"].isChecked()

    editor._set_active_tool("eraser")
    assert editor.tool_buttons["eraser"].isChecked()
    assert not editor.tool_buttons["brush"].isChecked()

    editor.mode_combo.setCurrentIndex(1)
    assert editor.diagnostic_mode == "pbr_albedo"
    editor.close()


def test_mesh_painter_exposes_fx_and_fluids_as_primary_workflows() -> None:
    _application()
    viewer = ThreeDMeshPainterViewport()

    assert viewer.fx_btn.text() == "FX"
    assert viewer.fluids_btn.text() == "Water & Fluids"
    assert viewer.dynamics_btn.text() == "Dynamics"
    assert viewer.simulation_btn.text() == "Simulation"
    assert viewer.fx_btn.menu() is not None
    assert viewer.fluids_btn.menu() is not None
    assert viewer.dynamics_btn.menu() is not None
    assert "Bake Active FX (Timeline Range)" in [action.text() for action in viewer.fx_btn.menu().actions()]
    assert "FX Properties..." in [action.text() for action in viewer.fx_btn.menu().actions()]
    assert "Liquid presets" in [action.text() for action in viewer.fluids_btn.menu().actions()]
    dynamics_sections = [action.text() for action in viewer.dynamics_btn.menu().actions()]
    assert "Soft bodies & reformable matter" in dynamics_sections
    assert "Destruction & phase change" in dynamics_sections
    assert "Reactive surfaces" in dynamics_sections
    assert viewer._mesh_toolbar_frame.height() == 46
    viewer.create_simulation_preset_from_payload(
        "simulation.create_effect", {"preset": "explosion", "quality": "realtime", "seed": 7}
    )
    assert viewer.fx_btn.property("uiRole") == "primary"
    assert "Active FX" in viewer.fx_btn.toolTip()
    emitters = viewer.simulation_world.effect_system.emitters
    viewer._solo_fx_emitter_from_dialog(emitters[0].emitter_id, True)
    assert emitters[0].enabled
    assert not any(emitter.enabled for emitter in emitters[1:])
    viewer._solo_fx_emitter_from_dialog(emitters[0].emitter_id, False)
    budget_result = viewer.create_simulation_preset_from_payload(
        "simulation.configure_renderer_budget",
        {"target_upload_ms": 3.0, "particle_budget": 12000, "mesh_instance_budget": 24000, "adaptive": True},
    )
    assert budget_result["budget"]["particle_budget_per_stream"] == 12000
    viewer.close()


def test_timeline_uses_clear_playback_and_onion_skin_states() -> None:
    _application()
    timeline = AnimationTimelineBar(AnimationFrameSequence())

    assert timeline.play_btn.text() == "Play"
    assert timeline.onion_btn.text() == "Onion skin on"
    assert timeline.onion_btn.isChecked()

    timeline.toggle_playback()
    assert timeline.play_btn.text() == "Pause"
    timeline.toggle_playback()
    timeline.toggle_onion_skin()
    assert timeline.onion_btn.text() == "Onion skin off"
    assert not timeline.onion_btn.isChecked()
    timeline.close()


def test_fx_properties_exposes_quality_emitters_and_live_module_values() -> None:
    _application()
    world = create_effect_world("sparks", quality="cinematic", seed=42)
    dialog = FxPropertiesDialog(world.effect_system)

    assert dialog.quality_combo.currentData() == "cinematic"
    assert dialog.seed_spin.value() == 42
    assert dialog.emitter_combo.count() == len(world.effect_system.emitters)
    assert dialog.module_tree.topLevelItemCount() > 0
    assert "emitters" in dialog.active_summary.text()
    assert dialog.property_tabs.count() == 5
    assert dialog.solver_profile_combo.currentData() == "particle_realtime"
    assert dialog.workflow_tree.topLevelItemCount() >= 4
    assert dialog.solver_controls_tree.topLevelItemCount() >= 3
    assert "CPU preview" in dialog.backend_status.text()
    dialog.set_execution_telemetry({
        "backend": "d3d11", "dispatch_ms": 1.25, "particle_count": 100_000,
        "gpu_resident": False, "readback_bytes": 3_200_000,
    })
    assert "100,000 particles" in dialog.backend_status.text()
    assert "synchronized" in dialog.backend_status.text()

    changes = []
    dialog.parameter_changed.connect(lambda path, value: changes.append((path, value)))
    dialog.quality_combo.setCurrentIndex(dialog.quality_combo.findData("mobile"))
    assert changes[-1] == ("quality", "mobile")
    assert "lights disabled" in dialog.quality_details.text()
    dialog.spawn_rate.setValue(dialog.spawn_rate.value() + 1.0)
    assert changes[-1][0].endswith(".spawn_rate")

    renderer_changes = []
    dialog.renderer_changed.connect(lambda emitter_id, renderer: renderer_changes.append((emitter_id, renderer)))
    dialog.renderer_combo.setCurrentIndex(dialog.renderer_combo.findData("mesh"))
    assert renderer_changes[-1][1] == "mesh"

    solo_changes = []
    dialog.solo_emitter_requested.connect(lambda emitter_id, solo: solo_changes.append((emitter_id, solo)))
    dialog.solo_btn.setChecked(True)
    assert solo_changes[-1][1] is True

    manipulation_changes = []
    dialog.emitter_manipulation_requested.connect(
        lambda emitter_id, active, carry: manipulation_changes.append((emitter_id, active, carry))
    )
    dialog.manipulate_emitter_btn.setChecked(True)
    assert manipulation_changes[-1][1:] == (True, False)
    assert dialog.manipulate_emitter_btn.text() == "Stop manipulating"
    dialog.carry_emitter_particles.setChecked(True)
    assert manipulation_changes[-1][1:] == (True, True)
    dialog.manipulate_emitter_btn.setChecked(False)
    assert manipulation_changes[-1][1] is False

    budgets = []
    dialog.renderer_budget_changed.connect(lambda budget: budgets.append(dict(budget)))
    dialog.upload_budget_ms.setValue(4.0)
    dialog.particle_budget.setValue(16000)
    dialog.cull_distance.setValue(140.0)
    dialog._emit_renderer_budget()
    assert budgets[-1]["particle_budget"] == 16000
    assert budgets[-1]["cull_distance"] == 140.0
    dialog.set_renderer_stats({"total_rendered": 14000, "total_dropped": 500, "draw_calls": 8, "upload_ema_ms": 6.0})
    assert dialog.budget_pressure.value() == 100
    assert "over budget" in dialog.telemetry_label.text()
    assert "500 culled" in dialog.telemetry_label.text()

    dialog.performance_preset.setCurrentIndex(dialog.performance_preset.findData("mobile"))
    assert dialog.particle_budget.value() == 3500
    assert dialog.cull_distance.value() == 80.0

    assert set_effect_parameter(world.effect_system, "quality", "mobile") == "mobile"
    assert set_effect_parameter(world.effect_system, "deterministic_seed", 99) == 99
    dialog.close()
