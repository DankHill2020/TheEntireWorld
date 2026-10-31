"""Run one static-mesh bevel prompt through the real three-host action engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.services.action_execution_engine import ActionExecutionEngine, ExecutionContext
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph


ROOT = Path(__file__).resolve().parents[2]
PROOF = Path(os.environ["TC_BEVEL_ACTION_ROOT"]).resolve()
PROJECT = Path(os.environ["TC_BEVEL_ACTION_PROJECT"]).resolve()
MAYAPY = Path(r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe")
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
UNREAL = Path(r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe")
PORTS = {"maya": 17031, "blender": 17032, "unreal": 17033}


def _ready(port: int, process: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        with socket.socket() as connection:
            connection.settimeout(0.2)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _stop(process: subprocess.Popen, stop_file: Path | None = None) -> None:
    if stop_file is not None:
        stop_file.write_text("stop", encoding="utf-8")
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    mesh_count = int(os.environ.get("TC_BEVEL_ACTION_MESH_COUNT", "1"))
    if mesh_count not in {1, 2}:
        raise ValueError("This proof fixture supports one or two static meshes")
    names = ("MayaPromptCube",) if mesh_count == 1 else ("Crate_A", "Barrel_B")
    destination = (
        "MayaBlenderBevelActionV1" if mesh_count == 1 else "TwoBeveledPropsActionV1"
    )
    if PROOF.exists() and any(PROOF.iterdir()):
        raise FileExistsError(f"Refusing nonempty action proof workspace: {PROOF}")
    if not PROJECT.is_file():
        raise FileNotFoundError(PROJECT)
    content = PROJECT.parent / "Content" / "TCProbe" / destination
    if content.exists() and any(content.iterdir()):
        raise FileExistsError(f"Refusing nonempty Unreal proof destination: {content}")
    PROOF.mkdir(parents=True, exist_ok=True)
    maya_fbx = PROOF / "maya_source.fbx"
    blender_fbx = PROOF / "blender_edited.fbx"
    prompt = (
        "Export the static mesh MayaPromptCube from Maya as FBX to "
        f"{maya_fbx.as_posix()}, import into Blender, bevel its edges by 0.1 "
        "with 3 segments, re-export FBX to "
        f"{blender_fbx.as_posix()}, then import into Unreal "
        f"/Game/TCProbe/{destination} and verify registry readback."
        if mesh_count == 1 else
        "Export two separate static meshes named Crate_A and Barrel_B from Maya "
        "as separate FBX files, import each into Blender, bevel each mesh by 0.1 "
        "with 3 segments, re-export each as FBX, then import both into Unreal "
        f"/Game/TCProbe/{destination} and verify registry readback."
    )
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    operations = [row["operation"] for row in plan.get("stages") or []]
    expected = [
        "animation.export", "io.import_fbx", "pipeline.process_meshes_for_transfer",
        "blender.export_fbx", "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    ]
    if (not plan.get("success") or not plan.get("execution_ready")
            or plan.get("gaps") or plan.get("required_inputs")
            or operations != expected * mesh_count
            or ([row.get("asset_lane") for row in plan["stages"]]
                != [name for name in names for _ in range(6)] if mesh_count == 2 else False)):
        raise RuntimeError(f"Prompt did not compile to the expected six-stage plan: {plan}")
    session = PROOF / "bridge_session.json"
    stop_file = PROOF / "stop_unreal_persistent_host.txt"
    os.environ.update({
        "TECH_CONNECTOR_BRIDGE_SESSION_FILE": str(session),
        "TECH_CONNECTOR_UNREAL_PROOF_ROOT": str(PROOF),
        "TECH_CONNECTOR_APP_ROOT": str(PROOF),
        "LOCALAPPDATA": str(PROOF / "localappdata"),
        "TEMP": str(PROOF), "TMP": str(PROOF),
        "MAYA_COMMAND_PORT": str(PORTS["maya"]),
        "MAYA_COMMAND_PORT_SCAN_COUNT": "1",
        "MAYA_COMMAND_PORT_FILE": str(PROOF / "maya_port.txt"),
        "MAYA_COMMAND_SESSION_FILE": str(PROOF / "maya_sessions.json"),
        "TC_MAYA_BENCHMARK_STATIC_CUBE": "1" if mesh_count == 1 else "0",
        "TC_MAYA_BENCHMARK_MESHES": "two_props" if mesh_count == 2 else "",
        "BLENDER_COMMAND_PORT": str(PORTS["blender"]),
        "BLENDER_COMMAND_PORT_SCAN_COUNT": "1",
        "UNREAL_HTTP_PORT": str(PORTS["unreal"]),
        "UNREAL_HTTP_PORT_SCAN_COUNT": "1",
    })
    assert all(bridge_session_token(host) for host in PORTS)
    env = os.environ.copy()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    report = {
        "schema": (
            "tech_connector.maya_blender_unreal_bevel_action.v1"
            if mesh_count == 1 else "tech_connector.two_maya_blender_unreal_bevel_action.v1"
        ),
        "prompt": prompt,
        "project": str(PROJECT),
        "stages": [{"id": row["id"], "host": row["host"],
                    "operation": row["operation"], "params": row["params"]}
                   for row in plan["stages"]],
    }
    started = time.monotonic()
    with (PROOF / "maya.log").open("w", encoding="utf-8") as maya_log, \
            (PROOF / "blender.log").open("w", encoding="utf-8") as blender_log, \
            (PROOF / "unreal.log").open("w", encoding="utf-8") as unreal_log:
        maya = subprocess.Popen(
            [str(MAYAPY), str(ROOT / "tech_connector" / "benchmarks" / "live_maya_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=maya_log, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        blender = subprocess.Popen(
            [str(BLENDER), "--background", "--python",
             str(ROOT / "tech_connector" / "benchmarks" / "live_blender_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=blender_log, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        unreal = subprocess.Popen(
            [str(UNREAL), str(PROJECT),
             f"-ExecutePythonScript={ROOT / 'tech_connector' / 'benchmarks' / 'live_unreal_commandlet_http_host.py'}",
             "-unattended", "-nop4", "-nosplash", "-nullrhi",
             "-ddc=InstalledNoZenLocalFallback",
             f"-LocalDataCachePath={PROOF / 'cache' / 'DDC'}",
             f"-ZenDataPath={PROOF / 'cache' / 'Zen'}"],
            cwd=str(PROJECT.parent), env=env, stdout=unreal_log,
            stderr=subprocess.STDOUT, creationflags=flags,
        )
        try:
            report["hosts_ready"] = {
                "maya": _ready(PORTS["maya"], maya, 35),
                "blender": _ready(PORTS["blender"], blender, 30),
                "unreal": _ready(PORTS["unreal"], unreal, 65),
            }
            if not all(report["hosts_ready"].values()):
                raise RuntimeError(f"A DCC host did not become ready: {report['hosts_ready']}")
            execution = ActionExecutionEngine().execute_plan(
                plan, ExecutionContext(approved=True, policy={
                    "original_prompt": prompt,
                    "pipeline_live_preflight": "required",
                    "dcc_session_ports": PORTS,
                    "pipeline_workspace": str(PROOF),
                }),
            )
            report["action_report"] = execution
            report["status"] = execution.get("status")
            report["status_counts"] = execution.get("status_counts")
            expected_fbx = (
                (maya_fbx, blender_fbx) if mesh_count == 1 else tuple(
                    PROOF / f"{name}_{host}.fbx"
                    for name in names for host in ("maya", "blender")
                )
            )
            report["artifacts"] = {
                path.name: {"bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in expected_fbx if path.is_file()
            }
            expected_assets = (
                (content / "blender_edited.uasset",) if mesh_count == 1
                else tuple(content / f"{name}_blender.uasset" for name in names)
            )
            report["asset_exists"] = all(path.is_file() for path in expected_assets)
            report["passed"] = (
                report["status"] == "completed"
                and set(report["artifacts"]) == {path.name for path in expected_fbx}
                and report["asset_exists"]
            )
        except Exception as exc:
            report["passed"] = False
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _stop(maya)
            _stop(blender)
            _stop(unreal, stop_file=stop_file)
            report["elapsed_seconds"] = round(time.monotonic() - started, 2)
            (PROOF / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            session.unlink(missing_ok=True)
            stop_file.unlink(missing_ok=True)
    print(json.dumps({"passed": report["passed"], "status": report.get("status"),
                      "error": report.get("error"), "report": str(PROOF / "report.json")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
