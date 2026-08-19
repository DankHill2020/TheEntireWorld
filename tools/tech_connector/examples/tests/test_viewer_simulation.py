import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector import viewer_cmds
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_chat_creates_steps_displays_and_transfers_viewer_simulation() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        created = viewer_cmds.execute_active(
            "simulation.create_cloth", material="silk", columns=4, rows=4, force_local=True
        )
        cloth_particle_count = len(viewer.simulation_world.particles)
        stepped = viewer_cmds.execute_active("simulation.step", frames=2, force_local=True)
        collider = viewer_cmds.execute_active("simulation.add_geometry_collider", force_local=True)
        transfer = viewer_cmds.execute_active(
            "simulation.build_transfer_manifest", target="unreal", force_local=True
        )
        dough = viewer_cmds.execute_active(
            "simulation.create_reformable_dough", spacing=0.3, max_particles=512, force_local=True
        )
        dough_particle_count = len(viewer.simulation_world.particles)
        dough_bond_count = len(viewer.simulation_world.constraints)
        effect = viewer_cmds.execute_active(
            "simulation.create_effect", preset="electrical_storm", quality="low", force_local=True
        )
        parameter = viewer_cmds.execute_active(
            "simulation.set_effect_parameter", path="emitter.storm_bolts.spawn_rate", value=12.0, force_local=True
        )
        mesh_particle = viewer_cmds.execute_active(
            "simulation.set_effect_renderer", emitter_id="storm_bolts", renderer_type="mesh", force_local=True
        )
        viewer_cmds.execute_active("simulation.step", frames=1, force_local=True)
        renderer_stats = viewer_cmds.execute_active("simulation.renderer_stats", force_local=True)
        renderer_budget = viewer_cmds.execute_active(
            "simulation.configure_renderer_budget",
            target_upload_ms=3.0,
            particle_budget=8000,
            mesh_instance_budget=20000,
            adaptive=False,
            force_local=True,
        )
        reactive = viewer_cmds.execute_active(
            "simulation.create_deformable_surface", material="snow", columns=12, rows=12, cell_size=0.2, force_local=True
        )
        footprint = viewer_cmds.execute_active(
            "simulation.apply_footprint", position=(0, 0, 0), depth=0.06, force_local=True
        )
        projectile = viewer_cmds.execute_active(
            "simulation.apply_projectile", position=(0, 0, 0), energy=5.0, force_local=True
        )
        soup = viewer_cmds.execute_active(
            "simulation.create_fluid", material="soup", dimensions=(1, 1, 1), force_local=True
        )
        curve = viewer_cmds.execute_active(
            "simulation.add_curve_flow",
            points=((-1, 0, 0), (1, 0, 0)),
            flow_strength=10.0,
            force_local=True,
        )
        vertex_count = len(viewer.mesh.vertices)
        emission_values = [1.0 if index < 8 else 0.0 for index in range(vertex_count)]
        painted_emission = viewer_cmds.execute_active(
            "simulation.paint_emission_source", values=emission_values, force_local=True
        )
        geometry_emitter = viewer_cmds.execute_active(
            "simulation.add_geometry_emitter", material="water", force_local=True
        )
        maturity_audit = viewer_cmds.execute_active(
            "engine.audit_capability_maturity", department="simulation", force_local=True
        )

        assert created["executed"]
        assert cloth_particle_count == 16
        assert stepped["frame"] == 3
        assert collider["collider_faces"] == 400
        assert any(item["destination_feature"] == "Chaos Cloth" for item in transfer["manifest"]["artifacts"])
        assert dough["executed"] and dough_particle_count > 0 and dough_bond_count > 0
        assert effect["executed"] and len(effect["effect_system"]["emitters"]) == 2
        assert parameter["value"] == 12.0
        assert mesh_particle["renderer"]["source_face_count"] == 400
        assert renderer_stats["executed"] and renderer_stats["stats"]["total_rendered"] >= 0
        assert renderer_budget["budget"]["particle_budget_per_stream"] == 8000
        assert reactive["executed"] and footprint["mark"]["kind"] == "footprint"
        assert projectile["mark"]["kind"] in {"impact", "penetration"}
        assert soup["executed"] and viewer.simulation_world.particles[0].phase == "fluid"
        assert curve["executed"] and len(viewer.simulation_world.curve_fields) == 1
        assert painted_emission["executed"] and len(painted_emission["changed_vertices"]) == 8
        assert geometry_emitter["executed"]
        assert viewer.simulation_world.emitters[-1].source_weights == emission_values
        assert viewer.paint_target_combo.currentData() == "emission_source"
        assert maturity_audit["executed"]
        assert maturity_audit["capability_audit"]["filtered_count"] > 0
        assert all(
            row["capability"].startswith("simulation.")
            for row in maturity_audit["capability_audit"]["capabilities"]
        )
    finally:
        viewer.close()
        app.processEvents()


def test_effect_bake_runs_off_the_qt_thread_and_installs_cache() -> None:
    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        viewer_cmds.execute_active(
            "simulation.create_effect", preset="sparks", quality="low", force_local=True
        )
        started_at = time.perf_counter()
        result = viewer_cmds.execute_active(
            "simulation.bake_effect",
            start_frame=1,
            end_frame=24,
            frame_rate=24.0,
            force_local=True,
        )
        dispatch_seconds = time.perf_counter() - started_at
        deadline = time.perf_counter() + 5.0
        while viewer._effect_bake_thread is not None and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

        assert result["started"]
        assert dispatch_seconds < 0.5
        assert viewer._effect_bake_thread is None
        assert len(viewer.simulation_cache.frames) == 24
        assert viewer.simulation_cache.metadata["kind"] == "effect_bake"
    finally:
        viewer.close()
        app.processEvents()


def test_emission_source_map_round_trips_through_tcscene(tmp_path) -> None:
    from tech_connector.game_engine.scene.federated_scene_service import save_federated_scene

    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        source_map = viewer.deformation_weight_map("emission_source")
        source_map.values[:4] = [1.0, 0.75, 0.25, 0.0]
        source_map.revision = 6
        path = tmp_path / "painted_emitter.tcscene"
        save_federated_scene(path, viewer.build_federated_scene_document())

        viewer.deformation_weight_maps = {}
        loaded, _message = viewer.load_federated_scene_file(str(path), interactive=False)

        restored = viewer.deformation_weight_maps["emission_source"]
        assert loaded
        assert restored.values[:4] == [1.0, 0.75, 0.25, 0.0]
        assert restored.semantics == "mesh_emission_density"
        assert restored.revision == 6
    finally:
        viewer.close()
        app.processEvents()
