from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService, builtin_asset_type_registry
from tech_connector.game_engine.runtime import (
    GroundIKSettings,
    ProceduralAnimationRuntime,
    VehicleControlInput,
    VehicleDynamicsRuntime,
    VehicleRigSettings,
    WheelRigSettings,
    solve_two_bone_ik,
)


def _flat_ground(origin, _direction, maximum_distance, _mask):
    if origin[1] < 0.0 or origin[1] > maximum_distance:
        return None
    return {
        "hit": True,
        "point": (origin[0], 0.0, origin[2]),
        "normal": (0.0, 1.0, 0.0),
        "distance": origin[1],
        "collider": "ground",
    }


def test_two_bone_solver_reaches_target_and_respects_stretch_limit() -> None:
    joint, end, stretch = solve_two_bone_ik(
        (0.0, 2.0, 0.0), (0.0, 1.0, 0.25), (0.0, 0.0, 0.0),
        (0.4, 0.2, 0.0), (0.0, 1.0, 1.0), maximum_stretch=1.05,
    )
    assert end == pytest.approx((0.4, 0.2, 0.0))
    assert 1.0 <= stretch <= 1.05
    assert joint != end


def test_ground_ik_probes_plants_and_requests_pelvis_compensation() -> None:
    runtime = ProceduralAnimationRuntime()
    settings = {
        "left": GroundIKSettings("hip_l", "knee_l", "foot_l", foot_offset=0.05),
        "right": GroundIKSettings("hip_r", "knee_r", "foot_r", foot_offset=0.05),
    }
    bones = {
        "hip_l": (-0.2, 1.9, 0.0), "knee_l": (-0.2, 1.0, 0.15), "foot_l": (-0.2, 0.2, 0.0),
        "hip_r": (0.2, 1.9, 0.0), "knee_r": (0.2, 1.0, 0.15), "foot_r": (0.2, 0.3, 0.0),
    }
    frame = runtime.step_ground_ik(
        settings, bones, _flat_ground, delta_time=1.0 / 60.0, character_speed=0.0,
    )
    assert frame.limbs["left"].grounded and frame.limbs["left"].planted
    assert frame.limbs["left"].end_position[1] < bones["foot_l"][1]
    assert frame.pelvis_offset < 0.0
    assert frame.limbs["right"].collider == "ground"


def test_vehicle_raycast_wheels_generate_suspension_drive_and_braking() -> None:
    settings = VehicleRigSettings(engine_force=8000.0, anti_roll_stiffness=5000.0)
    runtime = VehicleDynamicsRuntime(settings)
    wheels = (
        WheelRigSettings("front_l", (-0.8, 0.0, 1.2), steerable=True, axle="front"),
        WheelRigSettings("front_r", (0.8, 0.0, 1.2), steerable=True, axle="front"),
        WheelRigSettings("rear_l", (-0.8, 0.0, -1.2), axle="rear"),
        WheelRigSettings("rear_r", (0.8, 0.0, -1.2), axle="rear"),
    )
    driven = runtime.step(
        wheels, (0.0, 0.55, 0.0), (0.0, 0.0, 4.0),
        VehicleControlInput(throttle=1.0, steering=0.5), _flat_ground,
        delta_time=1.0 / 60.0,
    )
    assert driven.grounded_wheels == 4
    assert driven.total_force[1] > 0.0
    assert sum(wheel.drive_force for wheel in driven.wheels) == pytest.approx(8000.0)
    assert driven.wheels[0].steering_angle > 0.0

    braking = runtime.step(
        wheels, (0.0, 0.55, 0.0), (0.0, 0.0, 4.0),
        VehicleControlInput(brake=1.0), _flat_ground, delta_time=1.0 / 60.0,
    )
    assert sum(wheel.brake_force for wheel in braking.wheels) < 0.0


def test_procedural_animation_and_vehicle_assets_are_first_class(tmp_path) -> None:
    registry = builtin_asset_type_registry()
    assert registry.require("tc.procedural_animation_profile").runtime_loader_id == "procedural_animation"
    assert registry.require("tc.vehicle_rig").runtime_loader_id == "vehicle_rig"
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database, registry)
    procedural = operations.create_asset("tc.procedural_animation_profile", "PA_HumanoidGrounding")
    vehicle = operations.create_asset("tc.vehicle_rig", "VR_SportsCar")
    assert Path(procedural.destination_path).name.endswith(".procanim.tcasset")
    assert Path(vehicle.destination_path).name.endswith(".vehicle.tcasset")
    assert operations.validate_asset(procedural.asset_id).valid
    assert operations.validate_asset(vehicle.asset_id).valid
