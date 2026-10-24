"""Run one selected FBX→Maya controls→Unreal animation prompt in live hosts."""

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
PROOF = Path(os.environ["TC_ANIMATION_ACTION_ROOT"]).resolve()
PROJECT = Path(os.environ["TC_ANIMATION_ACTION_PROJECT"]).resolve()
MAYAPY = Path(r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe")
UNREAL = Path(r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe")
CLIP = os.environ.get("TC_ANIMATION_ACTION_CLIP", "TesBoi")
if CLIP not in {"TesBoi", "FakeGameplay"}:
    raise ValueError("This live benchmark supports TesBoi or FakeGameplay")
SOURCE = Path(r"C:\depot\ArtSource\Exports\Animation\Gameplay") / f"{CLIP}.fbx"
RIG = Path(r"C:\depot\ArtSource\Rigs\Juice_rig_update.ma")
HIK = Path(r"C:\depot\ArtSource\Rigs\mocap_rigs\Juice_rig_update.fbx")
DESTINATION = f"/Game/TCProbe/{CLIP}ActionV1"
SKELETON = "/Game/TCProbe/Rig/Juice_rig_update_Skeleton"
PORTS = {"maya": 17041, "unreal": 17043}


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
    if PROOF.exists() and any(PROOF.iterdir()):
        raise FileExistsError(f"Refusing nonempty proof workspace: {PROOF}")
    for path in (PROJECT, SOURCE, RIG, HIK):
        if not path.is_file():
            raise FileNotFoundError(path)
    asset_dir = PROJECT.parent / "Content" / "TCProbe" / f"{CLIP}ActionV1"
    if asset_dir.exists() and any(asset_dir.iterdir()):
        raise FileExistsError(f"Refusing nonempty Unreal destination: {asset_dir}")
    PROOF.mkdir(parents=True, exist_ok=True)
    scene = PROOF / f"{CLIP}_controls.ma"
    fbx = PROOF / f"{CLIP}_engine.fbx"
    prompt = (
        f'In Maya transfer animation FBX "{SOURCE.as_posix()}" onto control rig '
        f'"{RIG.as_posix()}" using target HIK "{HIK.as_posix()}"; '
        f'save scene "{scene.as_posix()}" and export baked skeleton FBX '
        f'"{fbx.as_posix()}"; then import the animation into Unreal at '
        f'{DESTINATION} on Skeleton {SKELETON} and verify registry readback.'
    )
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    expected = [
        "animation.fbx_to_engine",
        "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    ]
    if (not plan.get("success") or not plan.get("execution_ready")
            or plan.get("gaps") or plan.get("required_inputs")
            or [row["operation"] for row in plan.get("stages") or []] != expected):
        raise RuntimeError(f"Prompt did not compile to the expected three-stage plan: {plan}")
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
        "TC_MAYA_BENCHMARK_LONG_OPERATION": "1",
        "UNREAL_HTTP_PORT": str(PORTS["unreal"]),
        "UNREAL_HTTP_PORT_SCAN_COUNT": "1",
    })
    assert all(bridge_session_token(host) for host in PORTS)
    env = os.environ.copy()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    report = {
        "schema": "tech_connector.maya_unreal_animation_action.v1",
        "clip": CLIP,
        "prompt": prompt,
        "project": str(PROJECT),
        "input_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (SOURCE, RIG, HIK)},
        "stages": [{"id": row["id"], "host": row["host"], "operation": row["operation"],
                    "params": row["params"]} for row in plan["stages"]],
    }
    started = time.monotonic()
    with (PROOF / "maya.log").open("w", encoding="utf-8") as maya_log, \
            (PROOF / "unreal.log").open("w", encoding="utf-8") as unreal_log:
        maya = subprocess.Popen(
            [str(MAYAPY), str(ROOT / "tech_connector" / "benchmarks" / "live_maya_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=maya_log, stderr=subprocess.STDOUT,
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
                "unreal": _ready(PORTS["unreal"], unreal, 65),
            }
            if not all(report["hosts_ready"].values()):
                raise RuntimeError(f"A host did not become ready: {report['hosts_ready']}")
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
            report["artifacts"] = {
                path.name: {"bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in (scene, fbx) if path.is_file()
            }
            report["asset_files"] = [str(path) for path in asset_dir.glob("*.uasset")]
            report["passed"] = (report["status_counts"] == {"completed": 3}
                                and set(report["artifacts"]) == {scene.name, fbx.name}
                                and bool(report["asset_files"]))
        except Exception as exc:
            report["passed"] = False
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            _stop(maya)
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
