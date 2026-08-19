from __future__ import annotations

import time
import subprocess
import pytest

from tech_connector.game_engine.assets.tc_collision_cook_service import cook_collision_asset, inspect_collision_asset
from tech_connector.game_engine.runtime.tc_physics_network_service import PhysicsDatagramTransport, PhysicsReplicationSession
from tech_connector.game_engine.runtime.tc_physics_replay_service import DeterministicPhysicsRecorder
from tech_connector.game_engine.runtime.tc_physics_stress_service import build_physics_stress_scene, write_physics_stress_manifest
from tech_connector.game_engine.runtime.tc_player_build_service import _resolve_player_executable
from tech_connector.examples.game_engine.converted_unreal_vertical_slice import create_sample
from tech_connector.game_engine.runtime.tc_player_build_service import compile_tcscene_for_runtime, stable_runtime_asset_id
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene


def test_collision_cook_round_trip_for_mesh_and_compound(tmp_path) -> None:
    mesh_path = tmp_path / "tetra.tccollider"
    summary = cook_collision_asset(
        mesh_path, kind="convex_hull",
        vertices=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        triangles=((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
    )
    assert summary == inspect_collision_asset(mesh_path)
    compound = cook_collision_asset(
        tmp_path / "compound.tccollider", kind="compound",
        children=({"shape": "box", "translation": [0, 0, 0]}, {"shape": "capsule", "translation": [0, 1, 0]}),
    )
    assert compound.child_count == 2


def test_udp_replication_acknowledges_and_records_authoritative_frame() -> None:
    first = PhysicsDatagramTransport("test")
    second = PhysicsDatagramTransport("test")
    try:
        sender = PhysicsReplicationSession(first)
        receiver = PhysicsReplicationSession(second)
        frame = DeterministicPhysicsRecorder().record(1, {"body": {"x": 2}}, [{"move": 1}])
        sender.send_frame(second.address, frame)
        for _ in range(20):
            receiver.poll()
            first.poll(lambda *_args: None)
            if receiver.latest_authoritative_frame == 1 and first.unacknowledged_count == 0:
                break
            time.sleep(0.005)
        assert receiver.recorder.rollback(1) == {"body": {"x": 2}}
        assert first.unacknowledged_count == 0
    finally:
        first.close()
        second.close()


def test_stack_and_collision_torture_emit_native_manifests(tmp_path) -> None:
    for scenario in ("large_stack", "collision_torture"):
        world = build_physics_stress_scene(scenario, 64)
        manifest = write_physics_stress_manifest(world, tmp_path / f"{scenario}.tcruntime")
        text = manifest.read_text(encoding="utf-8")
        assert text.count("\nENTITY\t") == 65
        assert "\nSIMULATION\t" in text


def test_native_player_loads_cooked_collision_and_physical_animation(tmp_path) -> None:
    try:
        player = _resolve_player_executable(None)
    except FileNotFoundError:
        pytest.skip("Native player has not been built.")
    collision = tmp_path / "floor.tccollider"
    cook_collision_asset(
        collision, kind="triangle_mesh",
        vertices=((-2, 0, -2), (2, 0, -2), (2, 0, 2), (-2, 0, 2)),
        triangles=((0, 1, 2), (0, 2, 3)),
    )
    manifest = tmp_path / "native_features.tcruntime"
    manifest.write_text(
        "TCRUNTIME\t1\n"
        f"ASSET\ttc.asset.collision\tcollision\t{collision}\tstable\n"
        "ENTITY\tSurface\nTRANSFORM\tSurface\t0\t0\t0\t0\t0\t0\t1\t1\t1\nRIGID\tSurface\t0\t0\t0\t1\t0\t0\n"
        "COLLIDER\tSurface\t2\t0.01\t2\t0\ttriangle_mesh\t0.5\t0.5\t1\t4294967295\t0.5\t0.2\ttc.asset.collision\n"
        "ENTITY\tBody\nTRANSFORM\tBody\t0\t0.2\t0\t0\t0\t0\t1\t1\t1\nRIGID\tBody\t0\t0\t0\t1\t0\t1\n"
        "COLLIDER\tBody\t0.5\t0.5\t0.5\t0\tsphere\t0.5\t0.5\t1\t4294967295\t0.5\t0.2\t\n"
        "SKELETON\tSkeleton\t1\nJOINT\tSkeleton\tRoot\t\tRoot\t1\t0\t0\t0\t0\t1\t0\t0\t0\t0\t1\t0\t2\t0\t0\t1\n"
        "PHYSANIM\tSkeleton\tRoot\tBody\t1\t0.5\t10000\t1\t1\n"
        "SIMULATION\teveryday\t1\t1\t0\t0\t0\t0.008333333333333333\t2\t10000\t1\t0\t293.15\t0.001\t1\t1\t0.6\t12\t0.05\t0.05\t0.5\t6\t0.45\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [str(player), "--headless", "--scene", str(manifest), "--frames", "4"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "TC_PLAYER_OK frames=4" in completed.stdout


def test_scene_compiler_packages_collision_and_physical_animation_records(tmp_path) -> None:
    collision = tmp_path / "hero.tccollider"
    cook_collision_asset(
        collision, kind="convex_hull",
        vertices=((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        triangles=((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
    )
    source = create_sample(tmp_path / "source.tcscene")
    document, blobs = load_federated_scene(source)
    document.rig_graph.add_joint("Root", joint_id="root")
    player = next(item for item in document.metadata["runtime_world"]["entities"] if item.get("name") == "Player")
    player["collider"].update({"shape": "convex_hull", "collision_asset": str(collision)})
    player["physical_animation"] = {"joint_id": "root", "physics_blend": 0.75}
    compiled = compile_tcscene_for_runtime(save_federated_scene(tmp_path / "compiled.tcscene", document, blobs=blobs))
    manifest = compiled.runtime_manifest.read_text(encoding="utf-8")
    asset_id = stable_runtime_asset_id("collision", str(collision))
    assert f"ASSET\t{asset_id}\tcollision\t" in manifest
    assert next(line for line in manifest.splitlines() if line.startswith("COLLIDER\tPlayer")).endswith(asset_id)
    physical = next(line.split("\t") for line in manifest.splitlines() if line.startswith("PHYSANIM\t"))
    assert physical[:4] == ["PHYSANIM", "tc.skeleton.scene", "root", "Player"]
    assert [float(value) for value in physical[4:]] == [0.8, 0.5, 10000.0, 0.75, 1.0]
