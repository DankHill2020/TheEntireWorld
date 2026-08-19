from __future__ import annotations

import math
from pathlib import Path
import json
import statistics
import subprocess
import tempfile
from typing import Any


STRESS_SCENARIOS = ("chain", "bridge", "vehicle", "machinery", "ragdoll", "constraint_grid")
COLLISION_STRESS_SCENARIOS = ("large_stack", "collision_torture")
ALL_STRESS_SCENARIOS = STRESS_SCENARIOS + COLLISION_STRESS_SCENARIOS


def build_physics_stress_scene(scenario: str, count: int = 1000) -> dict[str, Any]:
    kind = str(scenario).casefold()
    if kind not in ALL_STRESS_SCENARIOS:
        raise ValueError(f"Unknown physics stress scenario: {scenario}")
    count = max(2, min(100_000, int(count)))
    entities: list[dict[str, Any]] = []
    joints: list[dict[str, Any]] = []
    columns = max(2, int(math.sqrt(count))) if kind in {"constraint_grid", "large_stack", "collision_torture"} else count
    for index in range(count + 1):
        x = float(index % columns) * 0.52 if kind in {"constraint_grid", "large_stack", "collision_torture"} else float(index) * 0.55
        y = float(index // columns) * 0.52 + 0.3 if kind in {"large_stack", "collision_torture"} else float(index // columns) + 2.0 if kind == "constraint_grid" else 3.0
        name = f"StressBody::{index:06d}"
        shape = ("box", "sphere", "capsule")[index % 3] if kind == "collision_torture" else "box"
        collider = {"shape": shape, "half_extents": [0.24, 0.24, 0.24], "friction": 0.65}
        if shape != "box":
            collider.update({"radius": 0.22, "half_height": 0.2})
        entities.append({
            "name": name, "transform": {"position": [x, y, float(index % 5) * 0.03], "rotation": [index % 17, index % 29, index % 37]},
            "rigid_body": {"dynamic": index != 0, "mass": 1.0, "linear_damping": 0.03, "angular_damping": 0.08,
                           "continuous_collision": kind == "collision_torture" and index % 11 == 0,
                           "velocity": [18.0, -2.0, 0.0] if kind == "collision_torture" and index % 11 == 0 else [0.0, 0.0, 0.0]},
            "collider": collider,
        })
        if index == 0 or kind in {"large_stack", "collision_torture"}:
            continue
        parent = index - 1
        joint_type, limits = "ball", (-35.0, 35.0)
        if kind == "vehicle":
            joint_type, limits = "hinge", (-180.0, 180.0)
        elif kind == "machinery":
            joint_type, limits = ("slider", (-0.25, 0.25)) if index % 2 else ("hinge", (-90.0, 90.0))
        elif kind == "bridge":
            joint_type, limits = "cone_twist", (-12.0, 12.0)
        elif kind == "ragdoll":
            joint_type, limits = ("hinge", (-5.0, 145.0)) if index % 3 == 0 else ("cone_twist", (-35.0, 35.0))
        elif kind == "constraint_grid" and index >= columns:
            parent = index - columns
        joints.append({
            "id": f"StressJoint::{index:06d}", "type": joint_type,
            "first": f"StressBody::{parent:06d}", "second": name,
            "first_anchor": [0.25, 0.0, 0.0], "second_anchor": [-0.25, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0], "minimum_limit": limits[0], "maximum_limit": limits[1],
            "limits_enabled": True, "stiffness": 0.92, "damping": 0.3,
            "collision_enabled": False, "enabled": True,
            "motor_enabled": kind in {"vehicle", "machinery"},
            "motor_target_velocity": 2.0 if kind == "vehicle" else 0.5,
            "motor_maximum_force": 150.0 if kind in {"vehicle", "machinery"} else 0.0,
        })
    return {
        "schema": "tech_connector.physics_stress_scene.v1", "scenario": kind,
        "entities": entities, "physics_joints": joints,
        "simulation": {"fixed_timestep_seconds": 1.0 / 120.0, "maximum_substeps": 8, "joint_solver_iterations": 16,
                       "contact_solver_iterations": 6, "shock_propagation_factor": 0.45},
    }


def write_physics_stress_manifest(runtime_world: dict[str, Any], path: str | Path) -> Path:
    from tech_connector.game_engine.runtime.tc_player_build_service import _entity_records, _physics_joint_records

    warnings: list[str] = []
    entities = [dict(item) for item in runtime_world.get("entities") or () if isinstance(item, dict)]
    records = ["TCRUNTIME\t1"]
    for entity in entities:
        records.extend(_entity_records(entity, [], warnings))
    records.extend(_physics_joint_records(runtime_world, {str(item.get("name") or "") for item in entities}, warnings))
    simulation = dict(runtime_world.get("simulation") or {})
    records.append("\t".join((
        "SIMULATION", "everyday", "1", "1", "0", "-9.80665", "0",
        str(float(simulation.get("fixed_timestep_seconds", 1.0 / 120.0))),
        str(int(simulation.get("maximum_substeps", 8))), "10000", "1", "1", "293.15", "0.001", "1", "1", "0.6",
        str(int(simulation.get("joint_solver_iterations", 16))), "0.05", "0.05", "0.5",
        str(int(simulation.get("contact_solver_iterations", 6))), str(float(simulation.get("shock_propagation_factor", 0.45))),
    )))
    target = Path(path)
    target.write_text("\n".join(records) + "\n", encoding="utf-8")
    return target


def qualify_physics_stress_scenarios(
    *, executable: str | Path | None = None, count: int = 1000, frames: int = 180,
    warmup_frames: int = 30, target_frame_ms: float = 16.6667,
    maximum_joint_position_error: float = 5.0,
    working_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Run every stress scene in the native headless player and qualify measured physics cost."""
    from tech_connector.game_engine.runtime.tc_player_build_service import _resolve_player_executable

    player = _resolve_player_executable(executable)
    results: dict[str, Any] = {}
    temporary_parent = Path(working_directory) if working_directory else None
    if temporary_parent is not None:
        temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tc_physics_qualification_", dir=temporary_parent) as directory:
        root = Path(directory)
        for scenario in ALL_STRESS_SCENARIOS:
            manifest = write_physics_stress_manifest(build_physics_stress_scene(scenario, count), root / f"{scenario}.tcruntime")
            log = root / f"{scenario}.jsonl"
            completed = subprocess.run(
                [str(player), "--headless", "--scene", str(manifest), "--frames", str(max(frames, warmup_frames + 1)), "--log", str(log)],
                capture_output=True, text=True, timeout=180, check=False,
            )
            telemetry = [
                json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
                if line.startswith("{")
            ][warmup_frames:]
            samples = [float(row["physics_ms"]) for row in telemetry]
            if completed.returncode != 0 or not telemetry:
                results[scenario] = {"qualified": False, "error": completed.stderr.strip() or "No frame telemetry."}
                continue
            ordered = sorted(float(value) for value in samples)
            p95 = ordered[min(len(ordered) - 1, int(math.ceil(len(ordered) * 0.95)) - 1)]
            def distribution(key: str) -> dict[str, float]:
                values = sorted(float(row.get(key, 0.0) or 0.0) for row in telemetry)
                index = min(len(values) - 1, int(math.ceil(len(values) * 0.95)) - 1)
                return {"median": statistics.median(values), "p95": values[index], "worst": max(values)}

            integration = distribution("physics_integration_ms")
            joints = distribution("physics_joint_ms")
            collision = distribution("physics_collision_ms")
            worst_joint_error = max(float(row.get("maximum_joint_position_error", 0.0) or 0.0) for row in telemetry)
            stable = math.isfinite(worst_joint_error) and worst_joint_error <= maximum_joint_position_error
            results[scenario] = {
                "qualified": p95 <= target_frame_ms and stable, "sample_count": len(samples),
                "median_physics_ms": statistics.median(ordered), "p95_physics_ms": p95,
                "worst_physics_ms": max(ordered), "target_frame_ms": float(target_frame_ms),
                "median_integration_ms": integration["median"], "p95_integration_ms": integration["p95"],
                "median_joint_ms": joints["median"], "p95_joint_ms": joints["p95"],
                "median_collision_ms": collision["median"], "p95_collision_ms": collision["p95"],
                "joint_solver_iterations": max(int(row.get("physics_joint_iterations", 0) or 0) for row in telemetry),
                "maximum_joint_position_error": worst_joint_error,
                "joint_position_error_limit": float(maximum_joint_position_error),
                "stable": stable,
            }
    return {
        "schema": "tech_connector.physics_stress_qualification.v1", "player": str(player),
        "entity_count": int(count), "frames": int(frames), "scenarios": results,
        "targets": {
            "physics_p95_ms": float(target_frame_ms),
            "maximum_joint_position_error": float(maximum_joint_position_error),
        },
        "qualified": bool(results) and all(item.get("qualified") for item in results.values()),
    }


def audit_physics_stress_scene(runtime_world: dict[str, Any]) -> dict[str, Any]:
    entities = [item for item in runtime_world.get("entities") or () if isinstance(item, dict)]
    joints = [item for item in runtime_world.get("physics_joints") or () if isinstance(item, dict)]
    names = {str(item.get("name") or "") for item in entities}
    invalid = [str(item.get("id") or "") for item in joints if str(item.get("first") or "") not in names or str(item.get("second") or "") not in names]
    duplicate_ids = len(joints) - len({str(item.get("id") or "") for item in joints})
    return {
        "schema": "tech_connector.physics_stress_audit.v1", "entity_count": len(entities),
        "constraint_count": len(joints), "invalid_constraint_ids": invalid,
        "duplicate_constraint_id_count": duplicate_ids,
        "ready": not invalid and duplicate_ids == 0 and bool(entities),
        "qualification_targets": {"60_fps_ms": 16.6667, "120_fps_ms": 8.3333, "deterministic_replays": 3},
    }


__all__ = [
    "ALL_STRESS_SCENARIOS", "COLLISION_STRESS_SCENARIOS", "STRESS_SCENARIOS",
    "audit_physics_stress_scene", "build_physics_stress_scene",
    "qualify_physics_stress_scenarios", "write_physics_stress_manifest",
]
