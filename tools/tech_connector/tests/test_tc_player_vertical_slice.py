from __future__ import annotations

from pathlib import Path
import array
import subprocess

from tech_connector.examples.game_engine.converted_unreal_vertical_slice import create_sample
from tech_connector.examples.game_engine.native_skinned_character_slice import create_skinned_character_sample
from tech_connector.game_engine.runtime.tc_player_build_service import (
    compile_tcscene_for_runtime,
    runtime_platform_capabilities,
    stable_runtime_asset_id,
    summarize_player_profile,
    validate_packaged_assets,
    validate_player_package,
)
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene
from tech_connector.game_engine.authoring.tc_animation_take_service import create_take, set_keyframe
from tech_connector.game_engine.authoring.engine_graph_program_service import (
    EngineGraphNode,
    EngineGraphProgram,
    GraphInputBinding,
    attach_engine_graph_program,
)


def test_unreal_sample_compiles_without_source_engine(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "converted.tcscene")
    receipt = compile_tcscene_for_runtime(scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    assert receipt.entities == 5
    assert receipt.graph_operations == 7
    assert not receipt.warnings
    assert "unreal" not in "\n".join(line for line in manifest.splitlines() if line.startswith("GRAPH"))
    assert "RIGID\tPlayer" in manifest
    assert "CAMERA\tRuntimeCamera" in manifest
    assert "LIGHT\tSun" in manifest
    assert "RENDER\tGround" in manifest
    assert "RENDERSETTINGS\ttc_temporal\tquality\t0.666666667" in manifest
    assert "\tphysically_based\tprobe\t0.08\t0.18\t0.42" in manifest
    assert "\t0.12\t1\t0.3\t14\t8" in next(line for line in manifest.splitlines() if line.startswith("RENDERSETTINGS"))
    assert "LIGHT\tSun\t-0.45\t-1\t-0.3\t1\t0.93\t0.78\t4.5\t1\t0.266" in manifest
    assert "SIMULATION\teveryday\t1\t1\t0\t-9.8066499999999994\t0" in manifest
    assert "\t1\t0\t0.5\t1\t16.6667" in next(line for line in manifest.splitlines() if line.startswith("RENDERSETTINGS"))
    assert "GRAPH\ttick\tmove\tinput.move" in manifest


def test_authored_linked_movement_graph_compiles_for_packaged_runtime(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "authored_graph_source.tcscene")
    document, blobs = load_federated_scene(scene)
    document.metadata["runtime_world"].pop("tick", None)
    program = EngineGraphProgram(
        program_id="player_movement",
        display_name="Player Movement",
        entry_event="While Playing",
        nodes=[
            EngineGraphNode("read", "input.read_axis", "Read", {"axis": GraphInputBinding(literal="Move")}, output_name="value"),
            EngineGraphNode("calculate", "movement.calculate_velocity", "Calculate", {
                "direction": GraphInputBinding(mode="link", source_node="read", source_output="value"),
                "speed": GraphInputBinding(literal=7.5),
                "acceleration": GraphInputBinding(literal=30.0),
                "target": GraphInputBinding(literal="Self"),
            }, output_name="velocity"),
            EngineGraphNode("apply", "actor.set_velocity", "Apply", {
                "target": GraphInputBinding(literal="Self"),
                "velocity": GraphInputBinding(mode="link", source_node="calculate", source_output="velocity"),
            }),
        ],
        flow=["read", "calculate", "apply"],
    )
    attach_engine_graph_program(document, program)
    authored_scene = save_federated_scene(tmp_path / "authored_graph.tcscene", document, blobs=blobs)

    receipt = compile_tcscene_for_runtime(authored_scene)
    graph_lines = [
        line for line in receipt.runtime_manifest.read_text(encoding="utf-8").splitlines()
        if line.startswith("GRAPH") and line.split("\t")[2] in {"read", "calculate", "apply"}
    ]

    assert receipt.graph_operations == 6
    assert not receipt.warnings
    assert [line.split("\t")[3] for line in graph_lines] == [
        "input.read_axis", "movement.calculate_velocity", "actor.set_velocity",
    ]
    assert "@graph:read:value" in graph_lines[1]
    assert "@graph:calculate:velocity" in graph_lines[2]


def test_asset_ids_are_stable_and_type_scoped() -> None:
    first = stable_runtime_asset_id("mesh", r"C:\Project\Content\Hero.fbx")
    second = stable_runtime_asset_id("mesh", "c:/project/content/hero.fbx")
    material = stable_runtime_asset_id("material", "c:/project/content/hero.fbx")

    assert first == second
    assert first != material


def test_runtime_platform_report_does_not_claim_unimplemented_renderers() -> None:
    capabilities = runtime_platform_capabilities("linux")

    assert capabilities["targets"]["windows"]["renderer"] == "Direct3D 11"
    assert capabilities["targets"]["linux"]["renderer"] == "none"
    assert capabilities["targets"]["linux"]["headless_player"] is True
    assert capabilities["targets"]["macos"]["windowed_player"] is False


def test_package_validation_requires_success_marker_and_frame_profiles(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "TCPlayer.exe").write_bytes(b"player")
    content = tmp_path / "Content"
    content.mkdir()
    (content / "main.tcruntime").write_text("TCRUNTIME\t1\n", encoding="utf-8")

    def successful_run(arguments, **_kwargs):
        profile = Path(arguments[arguments.index("--log") + 1])
        profile.write_text('{"type":"frame","frame":0}\n{"type":"frame","frame":1}\n', encoding="utf-8")
        return subprocess.CompletedProcess(arguments, 0, "TC_PLAYER_OK frames=2 entities=1 events=0\n", "")

    monkeypatch.setattr(subprocess, "run", successful_run)

    validation = validate_player_package(tmp_path)

    assert validation["status"] == "passed"
    assert validation["frames"] == 2
    assert validation["profile_summary"]["frame"]["maximum_ms"] == 0.0


def test_profile_summary_reports_percentiles_and_graph_diagnostics(tmp_path: Path) -> None:
    profile = tmp_path / "profile.jsonl"
    profile.write_text(
        '\n'.join([
            '{"type":"frame","frame":0,"frame_ms":10,"graph_ms":2,"physics_ms":5}',
            '{"type":"frame","frame":1,"frame_ms":20,"graph_ms":4,"physics_ms":8}',
            'scene.tcgraph:4:1: error: bad node',
        ]) + '\n',
        encoding="utf-8",
    )

    summary = summarize_player_profile(profile)

    assert summary["frames"] == 2
    assert summary["frame"] == {"average_ms": 15.0, "p95_ms": 20.0, "maximum_ms": 20.0}
    assert summary["graph"]["average_ms"] == 3.0
    assert summary["diagnostics"] == ["scene.tcgraph:4:1: error: bad node"]


def test_profile_summary_separates_successful_graph_trace_from_diagnostics(tmp_path: Path) -> None:
    profile = tmp_path / "profile.jsonl"
    profile.write_text(
        '{"type":"frame","frame":0,"frame_ms":1}\nOK move input.move\n',
        encoding="utf-8",
    )

    summary = summarize_player_profile(profile)

    assert summary["diagnostics"] == []
    assert summary["graph_trace"] == ["OK move input.move"]


def test_packaged_assets_are_hash_validated(tmp_path: Path) -> None:
    content = tmp_path / "Content" / "Assets"
    content.mkdir(parents=True)
    asset = content / "mesh.bin"
    asset.write_bytes(b"verified mesh")
    import hashlib
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = tmp_path / "Content" / "main.tcruntime"
    manifest.write_text(f"TCRUNTIME\t1\nASSET\tmesh\tmesh\tContent/Assets/mesh.bin\t{digest}\n", encoding="utf-8")

    result = validate_packaged_assets(manifest, tmp_path)

    assert result["verified_count"] == 1
    assert result["verified_assets"] == ["mesh"]


def test_lighting_profile_compiles_rendering_and_sun_defaults(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "profile_source.tcscene")
    document, blobs = load_federated_scene(scene)
    runtime = document.metadata["runtime_world"]
    runtime["rendering"] = {"lighting_profile": "moonlight"}
    sun = next(item for item in runtime["entities"] if item.get("name") == "Sun")
    sun["light"] = {}
    profiled_scene = save_federated_scene(tmp_path / "profiled.tcscene", document, blobs=blobs)

    manifest = compile_tcscene_for_runtime(profiled_scene).runtime_manifest.read_text(encoding="utf-8")

    assert "LIGHT\tSun\t0.35\t-0.7\t-0.55\t0.46\t0.62\t1\t0.38\t1\t0.26" in manifest
    render_settings = next(line for line in manifest.splitlines() if line.startswith("RENDERSETTINGS"))
    assert "\tphysically_based\tprobe\t0.008\t0.018\t0.065" in render_settings
    assert render_settings.endswith("\t1\t0.65\t0.2\t5")


def test_native_skeleton_and_animation_records_compile_from_editable_rig(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "character_source.tcscene")
    document, blobs = load_federated_scene(scene)
    root = document.rig_graph.add_joint("Root", joint_id="root")
    document.rig_graph.add_joint(
        "Hip", parent_id=root, joint_id="hip",
        local_matrix=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1],
    )
    take = create_take(document.rig_graph, "Walk", start_frame=1, end_frame=25, frame_rate=24.0)
    set_keyframe(document.rig_graph, take, "hip", "translateY", 1, 1.0, interpolation="stepped")
    set_keyframe(document.rig_graph, take, "hip", "translateY", 25, 1.2)
    character_scene = save_federated_scene(tmp_path / "character.tcscene", document, blobs=blobs)

    receipt = compile_tcscene_for_runtime(character_scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    assert "SKELETON\ttc.skeleton.scene\t2" in manifest
    assert "JOINT\ttc.skeleton.scene\thip\troot\tHip" in manifest
    assert f"ANIMATION\t{take}\tWalk\ttc.skeleton.scene\t1\t25\t24\t1" in manifest
    assert f"ANIMCURVE\t{take}\thip\ttranslateY\t1\t0\t2\t1\t1\tstepped\t25\t1.2\tauto" in manifest


def test_sparse_skin_sidecars_become_bounded_runtime_assets(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "skin_source.tcscene")
    document, _ = load_federated_scene(scene)
    identity = array.array("f", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
    binding = {
        "provider_id": "native_fbx",
        "skeletons": [{
            "native_id": "character_rig", "joints": [{"native_id": "root", "name": "Root"}],
            "inverse_bind_matrices_f32": identity,
        }],
        "meshes": [{
            "native_id": "character_mesh", "skeleton_id": "character_rig",
            "deformation_mode": "linear_blend_skinning", "runtime_mode": "skeletal",
            "vertex_count": 1, "bind_vertices_f32": array.array("f", [0, 1, 0]),
            "influence_offsets_u32": array.array("I", [0, 1]),
            "joint_indices_u32": array.array("I", [0]), "weights_f32": array.array("f", [1]),
            "sparse_influence_count": 1, "max_influences_per_vertex": 1,
        }],
    }
    blobs = document.rig_graph.merge_deformation_binding(binding)
    skinned_scene = save_federated_scene(tmp_path / "skinned.tcscene", document, blobs=blobs)

    receipt = compile_tcscene_for_runtime(skinned_scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    assert manifest.count("\nASSET\t") >= 5
    assert "\trig_blob\t" in manifest
    assert "SKIN\tnative_fbx::character_rig::character_mesh\tnative_fbx::character_mesh\ttc.skeleton.scene\tlinear_blend_skinning\t1\t1\t1\tnative_fbx::root" in manifest
    assert len(list(receipt.runtime_manifest.with_suffix(".assets").glob("*"))) == 5


def test_native_skinned_character_acceptance_scene_compiles_end_to_end(tmp_path: Path) -> None:
    scene = create_skinned_character_sample(tmp_path / "native_character.tcscene")
    receipt = compile_tcscene_for_runtime(scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    assert not receipt.warnings
    assert "ANIMATION\twave\tWave\ttc.skeleton.scene\t1\t49\t24\t1" in manifest
    assert "SKIN\tnative_fbx::character_rig::character_mesh" in manifest
    character_render = next(line for line in manifest.splitlines() if line.startswith("RENDER\tCharacter"))
    assert character_render.endswith("\tnative_fbx::character_rig::character_mesh")
    assert "GRAPH\tbegin\tplay\tanimation.play" in manifest


def test_reflection_probe_compiles_with_packaged_environment(tmp_path: Path) -> None:
    environment = tmp_path / "studio.png"
    environment.write_bytes(b"test texture payload")
    scene = create_sample(tmp_path / "probe.tcscene", texture_path=environment)
    receipt = compile_tcscene_for_runtime(scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    environment_id = stable_runtime_asset_id("texture", str(environment.resolve()))
    assert receipt.entities == 6
    assert f"PROBE\tLightLabProbe\t{environment_id}\t8\t5\t8\t0.8\t1" in manifest
    assert f"ASSET\t{environment_id}\ttexture" in manifest


def test_astronomical_simulation_settings_survive_scene_compilation(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "astronomical.tcscene", simulation={
        "domain": "astronomical",
        "meters_per_world_unit": 1.0e9,
        "time_scale": 86400.0,
        "gravity_meters_per_second_squared": [0.0, 0.0, 0.0],
        "fixed_timestep_seconds": 0.001,
        "maximum_substeps": 64,
        "render_origin_threshold_world_units": 1.0e6,
        "gravity_softening_meters": 1.0e6,
        "floor_enabled": False,
    })
    manifest = compile_tcscene_for_runtime(scene).runtime_manifest.read_text(encoding="utf-8")

    assert "SIMULATION\tastronomical\t1000000000\t86400\t0\t0\t0\t0.001\t64\t1000000\t1000000\t0" in manifest


def test_physics_joints_compile_separately_from_skeletal_joints(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "physics_joint_source.tcscene")
    document, blobs = load_federated_scene(scene)
    runtime = document.metadata["runtime_world"]
    runtime["physics_joints"] = [{
        "id": "door_hinge",
        "type": "hinge",
        "first": "Ground",
        "second": "Player",
        "first_anchor": [0.0, 1.0, 0.0],
        "second_anchor": [0.0, -0.5, 0.0],
        "axis": [0.0, 1.0, 0.0],
        "minimum_limit": -85.0,
        "maximum_limit": 85.0,
        "limits_enabled": True,
        "motor_enabled": True,
        "motor_target_velocity": 1.5,
        "motor_maximum_force": 20.0,
        "break_force": 5000.0,
        "collision_enabled": False,
    }]
    runtime["simulation"]["joint_solver_iterations"] = 18
    compiled_scene = save_federated_scene(tmp_path / "physics_joint.tcscene", document, blobs=blobs)

    receipt = compile_tcscene_for_runtime(compiled_scene)
    manifest = receipt.runtime_manifest.read_text(encoding="utf-8")

    joint_line = next(line for line in manifest.splitlines() if line.startswith("PHYSICSJOINT"))
    assert joint_line.startswith("PHYSICSJOINT\tdoor_hinge\thinge\tGround\tPlayer")
    assert "\t-85\t85\t1\t0.1\t1.5\t20\t5000\t0\t1\t1\t0\t1" in joint_line
    simulation_fields = next(
        line for line in manifest.splitlines() if line.startswith("SIMULATION")
    ).split("\t")
    assert simulation_fields[17] == "18"
    assert not any(line.startswith("JOINT\tdoor_hinge") for line in manifest.splitlines())


def test_six_dof_axes_springs_and_drives_compile(tmp_path: Path) -> None:
    scene = create_sample(tmp_path / "six_dof_source.tcscene")
    document, blobs = load_federated_scene(scene)
    document.metadata["runtime_world"]["physics_joints"] = [{
        "id": "robot_axis", "type": "six_dof", "first": "Ground", "second": "Player",
        "linear_lower_limit": [-1.0, 0.0, 0.0], "linear_upper_limit": [1.0, 0.0, 0.0],
        "angular_lower_limit": [0.0, -45.0, 0.0], "angular_upper_limit": [0.0, 45.0, 0.0],
        "linear_spring_stiffness": [20.0, 0.0, 0.0], "linear_spring_damping": [2.0, 0.0, 0.0],
        "angular_spring_stiffness": [0.0, 10.0, 0.0], "angular_spring_damping": [0.0, 1.0, 0.0],
        "linear_drive_velocity": [2.0, 0.0, 0.0], "linear_drive_maximum_force": [100.0, 0.0, 0.0],
        "angular_drive_velocity": [0.0, 1.5, 0.0], "angular_drive_maximum_force": [0.0, 50.0, 0.0],
    }]
    compiled_scene = save_federated_scene(tmp_path / "six_dof.tcscene", document, blobs=blobs)
    manifest = compile_tcscene_for_runtime(compiled_scene).runtime_manifest.read_text(encoding="utf-8")
    row = next(line for line in manifest.splitlines() if line.startswith("JOINT6DOF\trobot_axis"))
    assert "\t-1\t0\t0\t1\t0\t0\t0\t-45\t0\t0\t45\t0" in row
    assert row.endswith("\t0\t50\t0")


def test_microscopic_particle_material_survives_scene_compilation(tmp_path: Path) -> None:
    scene = create_sample(
        tmp_path / "microscopic.tcscene",
        simulation={
            "domain": "molecular",
            "meters_per_world_unit": 1.0e-9,
            "temperature_kelvin": 310.0,
            "medium_viscosity_pascal_seconds": 0.0007,
            "relative_permittivity": 78.4,
            "random_seed": 17,
            "floor_enabled": False,
        },
        player_particle_physics={
            "radius_meters": 1.2e-9,
            "charge_coulombs": -1.602176634e-19,
            "lennard_jones_epsilon_joules": 1.1e-21,
            "lennard_jones_sigma_meters": 3.4e-10,
            "rest_density_kg_per_m3": 997.0,
            "viscosity_pascal_seconds": 0.0007,
            "pressure_stiffness": 2200.0,
            "thermal_motion": True,
        },
    )
    manifest = compile_tcscene_for_runtime(scene).runtime_manifest.read_text(encoding="utf-8")

    assert "SIMULATION\tmolecular\t1.0000000000000001e-09" in manifest
    assert "\t310\t0.00069999999999999999\t78.400000000000006\t17" in manifest
    assert "PARTICLE\tPlayer\t1.2e-09\t-1.6021766339999999e-19\t1.1e-21" in manifest
