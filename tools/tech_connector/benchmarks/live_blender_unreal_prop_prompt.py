"""Run one explicit Blender-to-Unreal prop prompt through the live action engine.

Uses isolated Blender and Unreal processes plus a disposable Unreal project.
The script refuses pre-existing output artifacts and never edits the user's DCC UI.
"""

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
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ["TC_BLENDER_UNREAL_PROOF_ROOT"]).resolve()
PROJECT = Path(os.environ["TC_BLENDER_UNREAL_PROJECT"]).resolve()
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
UNREAL = Path(r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe")
BLENDER_PORT = 7032
UNREAL_PORT = 12449


def _port_ready(port: int, process: subprocess.Popen, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and process.poll() is None:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def _stop(process: subprocess.Popen, *, stop_file: Path | None = None) -> None:
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
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if not PROJECT.is_file():
        raise FileNotFoundError(PROJECT)
    suffix = str(os.environ.get("TC_BLENDER_UNREAL_PROOF_SUFFIX") or "v1")
    if suffix not in {"v1", "v2", "v3", "v4", "v5"}:
        raise ValueError("Unsupported proof suffix")
    fbx = SCRATCH / f"blender_prop_unreal_{suffix}.fbx"
    destination = f"/Game/TCProbe/BlenderProp{suffix.upper()}"
    asset_folder = PROJECT.parent / "Content" / "TCProbe" / f"BlenderProp{suffix.upper()}"
    asset = asset_folder / "Demo_Prompt_Cube.uasset" if suffix in {"v4", "v5"} else asset_folder / f"blender_prop_unreal_{suffix}.uasset"
    report_path = SCRATCH / f"blender_unreal_prop_prompt_{suffix}.json"
    for path in (fbx, asset, report_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite proof artifact: {path}")
    if asset_folder.exists() and any(asset_folder.iterdir()):
        raise FileExistsError(f"Refusing nonempty proof destination: {asset_folder}")
    prompt = (
        "Build a Blender to Unreal prop pipeline: clean names, apply transforms, "
        f"generate LOD0 and LOD1, export to {fbx.as_posix()}, "
        f"import into {destination}, create collision, save, and validate registry readback."
        if suffix in {"v4", "v5"} else
        "In Blender, export selected static prop meshes as FBX to "
        f"{fbx.as_posix()}, then import that FBX into Unreal at {destination}, "
        "save, and validate registry readback."
    )
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    stages = list(plan.get("stages") or [])
    expected = (["pipeline.process_meshes_for_transfer"] if suffix in {"v4", "v5"} else []) + [
        "blender.export_fbx",
        "unreal_tools.asset_transfer_adapter.import_fbx_verified",
        "unreal_tools.asset_transfer_adapter.registry_readback",
    ]
    if (classify_prompt_route(prompt).route != "pipeline_graph"
            or not plan.get("success") or not plan.get("execution_ready")
            or plan.get("gaps") or plan.get("required_inputs")
            or [row.get("operation") for row in stages] != expected
            or [row.get("host") for row in stages] !=
            (["blender"] if suffix in {"v4", "v5"} else []) + ["blender", "unreal", "unreal"]):
        raise RuntimeError("Custom prompt did not compile into the selected three-stage handoff")
    session_file = SCRATCH / "blender_unreal_session.json"
    stop_file = SCRATCH / "blender_unreal_stop.txt"
    if stop_file.exists():
        raise FileExistsError(stop_file)
    os.environ["TECH_CONNECTOR_BRIDGE_SESSION_FILE"] = str(session_file)
    os.environ["BLENDER_COMMAND_PORT"] = str(BLENDER_PORT)
    os.environ["BLENDER_COMMAND_PORT_SCAN_COUNT"] = "1"
    os.environ["UNREAL_HTTP_PORT"] = str(UNREAL_PORT)
    os.environ["UNREAL_HTTP_PORT_SCAN_COUNT"] = "1"
    os.environ["TECH_CONNECTOR_APP_ROOT"] = str(SCRATCH)
    os.environ["LOCALAPPDATA"] = str(SCRATCH / "localappdata")
    os.environ["TEMP"] = str(SCRATCH)
    os.environ["TMP"] = str(SCRATCH)
    assert bridge_session_token("blender") and bridge_session_token("unreal")
    env = os.environ.copy()
    env["TC_BLENDER_UNREAL_STOP"] = str(stop_file)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    report = {
        "schema": "tech_connector.blender_unreal_prop_prompt.v1",
        "prompt": prompt,
        "route": "pipeline_graph",
        "project": str(PROJECT),
        "fbx_path": str(fbx),
        "asset_file": str(asset),
        "stages": [{"id": row["id"], "host": row["host"], "operation": row["operation"],
                    "params": row["params"]} for row in stages],
    }
    with (SCRATCH / "blender_unreal_blender.log").open("w", encoding="utf-8") as blender_log, \
            (SCRATCH / "blender_unreal_unreal.log").open("w", encoding="utf-8") as unreal_log:
        blender_process = subprocess.Popen(
            [str(BLENDER), "--background", "--python",
             str(ROOT / "tech_connector" / "benchmarks" / "live_blender_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=blender_log, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        unreal_process = subprocess.Popen(
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
            report["blender_ready"] = _port_ready(BLENDER_PORT, blender_process, 30)
            report["unreal_ready"] = _port_ready(UNREAL_PORT, unreal_process, 60)
            if not report["blender_ready"] or not report["unreal_ready"]:
                raise RuntimeError("Isolated DCC host did not become ready")
            execution = ActionExecutionEngine().execute_plan(
                plan,
                ExecutionContext(approved=True, policy={
                    "original_prompt": prompt,
                    "pipeline_live_preflight": "required",
                    "dcc_session_ports": {"blender": BLENDER_PORT, "unreal": UNREAL_PORT},
                }),
            )
            report["action_report"] = execution
            report["fbx_bytes"] = fbx.stat().st_size if fbx.is_file() else 0
            report["fbx_sha256"] = hashlib.sha256(fbx.read_bytes()).hexdigest() if fbx.is_file() else ""
            report["asset_bytes"] = asset.stat().st_size if asset.is_file() else 0
            report["asset_sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest() if asset.is_file() else ""
            report["asset_files"] = {
                path.name: {"bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(asset_folder.glob("*.uasset"))
            }
            report["ok"] = (execution.get("status") == "completed"
                            and report["fbx_bytes"] > 0 and report["asset_bytes"] > 0)
        except Exception as exc:
            report["ok"] = False
            report["error"] = str(exc)
        finally:
            _stop(blender_process)
            _stop(unreal_process, stop_file=stop_file)
            session_file.unlink(missing_ok=True)
            stop_file.unlink(missing_ok=True)
            report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(report_path),
                      "status": (report.get("action_report") or {}).get("status"),
                      "error": report.get("error", "")}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
