"""Live, prompt-driven two-lane Blender-to-Unreal static-mesh benchmark."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from tech_connector.benchmarks.live_blender_unreal_prop_prompt import (
    BLENDER, BLENDER_PORT, PROJECT, ROOT, SCRATCH, UNREAL, UNREAL_PORT,
    _port_ready, _stop,
)
from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.services.action_execution_engine import ActionExecutionEngine, ExecutionContext
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph


def main() -> int:
    mesh_count = int(os.environ.get("TC_BLENDER_UNREAL_MESH_COUNT", "2"))
    if mesh_count not in {2, 3}:
        raise ValueError("This live fixture supports exactly two or three distinct meshes")
    label = "two_props" if mesh_count == 2 else "three_props"
    names = ("Crate_A", "Barrel_B") if mesh_count == 2 else ("Crate_A", "Barrel_B", "Cone_C")
    destination = "/Game/TCProbe/TwoPropsV1" if mesh_count == 2 else "/Game/TCProbe/ThreePropsV1"
    folder = SCRATCH / f"{label}_v1"
    content = PROJECT.parent / "Content" / "TCProbe" / destination.rsplit("/", 1)[-1]
    report_path = folder / f"{label}_prompt_report.json"
    for path in (folder, content):
        if path.exists() and any(path.iterdir()):
            raise FileExistsError(f"Refusing nonempty benchmark output: {path}")
    folder.mkdir(parents=True, exist_ok=True)
    paths = {name: folder / f"{name}.fbx" for name in names}
    if mesh_count == 2:
        prompt = (
            "Export two separate static meshes named Crate_A and Barrel_B from Blender "
            f"as FBX to {paths['Barrel_B'].as_posix()} and {paths['Crate_A'].as_posix()}, "
            f"import both into Unreal {destination}, save and validate registry readback."
        )
    else:
        prompt = (
            "Export three separate static meshes named Crate_A, Barrel_B, and Cone_C "
            "from Blender as FBX to "
            f"{paths['Cone_C'].as_posix()}, {paths['Crate_A'].as_posix()}, "
            f"and {paths['Barrel_B'].as_posix()}, import all into Unreal {destination}, "
            "save and validate registry readback."
        )
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    stages = list(plan.get("stages") or [])
    expected = [
        "blender.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    ] * mesh_count
    if (not plan.get("success") or not plan.get("execution_ready")
            or [stage["operation"] for stage in stages] != expected
            or [stage["asset_lane"] for stage in stages] != [name for name in names for _ in range(3)]
            or [stage["params"]["output_path"] for stage in stages if stage["host"] == "blender"]
            != [str(paths[name]).replace("\\", "/") for name in paths]):
        raise RuntimeError("Custom multi-asset prompt did not compile to bound lanes")
    session_file = SCRATCH / "blender_unreal_session.json"
    stop_file = SCRATCH / "blender_unreal_stop.txt"
    if session_file.exists() or stop_file.exists():
        raise FileExistsError("Existing DCC benchmark bridge session")
    os.environ.update({
        "TECH_CONNECTOR_BRIDGE_SESSION_FILE": str(session_file),
        "BLENDER_COMMAND_PORT": str(BLENDER_PORT),
        "BLENDER_COMMAND_PORT_SCAN_COUNT": "1",
        "UNREAL_HTTP_PORT": str(UNREAL_PORT),
        "UNREAL_HTTP_PORT_SCAN_COUNT": "1",
        "TECH_CONNECTOR_APP_ROOT": str(SCRATCH),
        "LOCALAPPDATA": str(SCRATCH / "localappdata"),
        "TEMP": str(SCRATCH), "TMP": str(SCRATCH),
    })
    assert bridge_session_token("blender") and bridge_session_token("unreal")
    env = os.environ.copy()
    env["TC_BLENDER_BENCHMARK_MESHES"] = label
    env["TC_BLENDER_UNREAL_STOP"] = str(stop_file)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    report = {
        "schema": f"tech_connector.blender_unreal_{label}_prompt.v1",
        "prompt": prompt, "project": str(PROJECT),
        "stages": [{"id": stage["id"], "host": stage["host"],
                    "operation": stage["operation"], "asset_lane": stage["asset_lane"],
                    "params": stage["params"]} for stage in stages],
    }
    with (folder / "blender.log").open("w", encoding="utf-8") as blender_log, \
            (folder / "unreal.log").open("w", encoding="utf-8") as unreal_log:
        blender = subprocess.Popen(
            [str(BLENDER), "--background", "--python",
             str(ROOT / "tech_connector" / "benchmarks" / "live_blender_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=blender_log, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        unreal = subprocess.Popen(
            [str(UNREAL), str(PROJECT),
             f"-ExecutePythonScript={SCRATCH / 'blender_unreal_persistent_host_20261024.py'}",
             "-unattended", "-nop4", "-nosplash", "-nullrhi",
             "-ddc=InstalledNoZenLocalFallback",
             f"-LocalDataCachePath={SCRATCH / 'blender_unreal_cache' / 'DDC'}",
             f"-ZenDataPath={SCRATCH / 'blender_unreal_cache' / 'Zen'}"],
            cwd=str(PROJECT.parent), env=env, stdout=unreal_log,
            stderr=subprocess.STDOUT, creationflags=flags,
        )
        try:
            report["blender_ready"] = _port_ready(BLENDER_PORT, blender, 30)
            report["unreal_ready"] = _port_ready(UNREAL_PORT, unreal, 60)
            if not report["blender_ready"] or not report["unreal_ready"]:
                raise RuntimeError("Isolated DCC host did not become ready")
            execution = ActionExecutionEngine().execute_plan(
                plan, ExecutionContext(approved=True, policy={
                    "original_prompt": prompt,
                    "pipeline_live_preflight": "required",
                    "dcc_session_ports": {"blender": BLENDER_PORT, "unreal": UNREAL_PORT},
                }),
            )
            report["action_report"] = execution
            report["fbx"] = {
                name: {"path": str(path), "bytes": path.stat().st_size,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for name, path in paths.items() if path.is_file()
            }
            report["uasset"] = {
                name: {"path": str(content / f"{name}.uasset"),
                       "bytes": (content / f"{name}.uasset").stat().st_size,
                       "sha256": hashlib.sha256((content / f"{name}.uasset").read_bytes()).hexdigest()}
                for name in paths if (content / f"{name}.uasset").is_file()
            }
            report["ok"] = (execution.get("status") == "completed"
                            and set(report["fbx"]) == set(paths)
                            and set(report["uasset"]) == set(paths))
        except Exception as exc:
            report["ok"] = False
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _stop(blender)
            _stop(unreal, stop_file=stop_file)
            session_file.unlink(missing_ok=True)
            stop_file.unlink(missing_ok=True)
            report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(report_path),
                      "status": (report.get("action_report") or {}).get("status"),
                      "error": report.get("error", "")}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
