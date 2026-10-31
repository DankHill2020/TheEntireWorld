"""Run a prompt-driven Maya rig export through a real Blender import bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.services.action_execution_engine import ActionExecutionEngine, ExecutionContext
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(os.environ.get(
    "TC_BENCHMARK_RESULTS_DIR",
    str(ROOT / "tech_connector" / "benchmarks" / "results" / "maya_blender_live_20261020"),
)).resolve()
MAYAPY = Path(r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe")
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
MAYA_PORT = 7008
BLENDER_PORT = 7033


def _wait_session(bridge, port: int, process: subprocess.Popen, timeout: float = 40.0) -> dict:
    deadline = time.monotonic() + timeout
    info = {"ok": False, "error": "host did not respond"}
    while time.monotonic() < deadline and process.poll() is None:
        info = bridge.session_info(port=port, timeout=10.0)
        if info.get("ok"):
            return info
        time.sleep(0.1)
    return info


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    token_path = RESULTS / "bridge_session.json"
    os.environ["TECH_CONNECTOR_BRIDGE_SESSION_FILE"] = str(token_path)
    assert bridge_session_token("maya") and bridge_session_token("blender")
    output = RESULTS / "maya_proxy.fbx"
    prompt = (
        "Create a rigged animated proxy in Maya from frames 1 to 24, "
        f"export it to {output.as_posix()}, and import the FBX into Blender."
    )
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    report = {
        "prompt": prompt,
        "route": classify_prompt_route(prompt).route,
        "plan_success": bool(plan.get("success")),
        "plan_execution_ready": bool(plan.get("execution_ready")),
        "required_inputs": plan.get("required_inputs"),
        "gaps": plan.get("gaps"),
        "stages": [
            {"id": row["id"], "host": row["host"], "operation": row["operation"], "params": row["params"]}
            for row in plan.get("stages") or []
        ],
    }
    maya_process = None
    blender_process = None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        if not plan.get("success") or not plan.get("execution_ready"):
            return 1
        maya_env = os.environ.copy()
        maya_env.update({
            "MAYA_COMMAND_PORT": str(MAYA_PORT),
            "MAYA_COMMAND_PORT_SCAN_COUNT": "1",
            "MAYA_COMMAND_PORT_FILE": str(RESULTS / "maya_port.txt"),
            "MAYA_COMMAND_SESSION_FILE": str(RESULTS / "maya_sessions.json"),
        })
        blender_env = os.environ.copy()
        blender_env.update({
            "BLENDER_COMMAND_PORT": str(BLENDER_PORT),
            "BLENDER_COMMAND_PORT_SCAN_COUNT": "1",
            "TECH_CONNECTOR_APP_ROOT": str(RESULTS),
            "LOCALAPPDATA": str(RESULTS / "localappdata"),
        })
        with (RESULTS / "maya_host.log").open("w", encoding="utf-8") as maya_log, (
            RESULTS / "blender_host.log"
        ).open("w", encoding="utf-8") as blender_log:
            maya_process = subprocess.Popen(
                [str(MAYAPY), str(Path(__file__).with_name("live_maya_pipeline_host.py"))],
                cwd=str(ROOT), env=maya_env, stdout=maya_log, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            blender_process = subprocess.Popen(
                [str(BLENDER), "--background", "--python", str(Path(__file__).with_name("live_blender_pipeline_host.py"))],
                cwd=str(ROOT), env=blender_env, stdout=blender_log, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            maya = MayaBridge()
            blender = BlenderBridge()
            report["maya_session"] = _wait_session(maya, MAYA_PORT, maya_process)
            report["blender_session"] = _wait_session(blender, BLENDER_PORT, blender_process)
            if not report["maya_session"].get("ok") or not report["blender_session"].get("ok"):
                return 1
            execution = ActionExecutionEngine().execute_plan(
                plan,
                ExecutionContext(
                    approved=True,
                    policy={
                        "original_prompt": prompt,
                        "pipeline_live_preflight": "required",
                        "dcc_session_ports": {"maya": MAYA_PORT, "blender": BLENDER_PORT},
                    },
                ),
            )
            report["execution_status"] = execution.get("status")
            report["preflight"] = execution.get("preflight")
            report["status_counts"] = execution.get("status_counts")
            report["action_results"] = {
                key: {
                    "ok": value.get("ok"),
                    "status": value.get("status"),
                    "error": value.get("error"),
                    "exception_message": value.get("exception_message"),
                    "raw_result": value.get("raw_result"),
                }
                for key, value in (execution.get("results") or {}).items()
                if isinstance(value, dict)
            }
            report["fbx_exists"] = output.is_file()
            report["fbx_bytes"] = output.stat().st_size if output.is_file() else 0
            ok, raw = blender.execute_on_port(
                "import bpy,json; print(json.dumps({"
                "'meshes':[o.name for o in bpy.data.objects if o.type=='MESH'],"
                "'armatures':[o.name for o in bpy.data.objects if o.type=='ARMATURE'],"
                "'actions':[a.name for a in bpy.data.actions]}))",
                port=BLENDER_PORT,
                timeout=5.0,
            )
            report["blender_readback"] = json.loads(raw) if ok else {"error": raw}
            return 0 if (
                execution.get("status") == "completed"
                and report["fbx_bytes"] > 0
                and report["blender_readback"].get("armatures")
                and report["blender_readback"].get("actions")
            ) else 1
    finally:
        if blender_process is not None:
            _stop_process(blender_process)
        if maya_process is not None:
            _stop_process(maya_process)
        (RESULTS / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        token_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
