"""Exercise prompt planning through a real isolated Blender bridge and FBX export.

This uses a temporary headless Blender process; it never edits the user's open scene.
The JSON report excludes the bridge capability token.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import time
import uuid

from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.session_authorization import bridge_session_token
from tech_connector.services.action_execution_engine import ActionExecutionEngine, ExecutionContext
from tech_connector.services.action_planner_service import plan_prompt_to_action_graph
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(os.environ.get(
    "TC_BENCHMARK_RESULTS_DIR",
    str(ROOT / "tech_connector" / "benchmarks" / "results" / "blender_prompt_live_20261020"),
))
BLENDER_EXE = Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")
PORT = 7031


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    session_path = RESULTS / "bridge_session.json"
    os.environ["TECH_CONNECTOR_BRIDGE_SESSION_FILE"] = str(session_path)
    os.environ["BLENDER_COMMAND_PORT"] = str(PORT)
    os.environ["BLENDER_COMMAND_PORT_SCAN_COUNT"] = "1"
    os.environ["TECH_CONNECTOR_APP_ROOT"] = str(RESULTS)
    os.environ["LOCALAPPDATA"] = str(RESULTS / "localappdata")
    assert bridge_session_token("blender"), "Could not establish isolated bridge authorization"

    fbx = RESULTS / "prompt_prop.fbx"
    prompt = (
        "In Blender clean names of selected prop meshes, apply transforms, "
        f"generate LOD0 and LOD1, then export FBX to {fbx.as_posix()}."
    )
    route = classify_prompt_route(prompt).route
    plan = plan_prompt_to_action_graph(prompt, [str(ROOT)])
    report = {
        "schema": "tech_connector.live_blender_tc_prompt.v1",
        "prompt": prompt,
        "route": route,
        "plan_success": bool(plan.get("success")),
        "plan_execution_ready": bool(plan.get("execution_ready")),
        "required_inputs": plan.get("required_inputs"),
        "stages": [
            {"id": row["id"], "operation": row["operation"], "params": row["params"]}
            for row in plan.get("stages") or []
        ],
    }
    if route != "pipeline_graph" or not report["plan_success"] or not report["plan_execution_ready"]:
        (RESULTS / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        session_path.unlink(missing_ok=True)
        return 1

    env = os.environ.copy()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with (RESULTS / "blender_host.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(BLENDER_EXE), "--background", "--python", str(Path(__file__).with_name("live_blender_pipeline_host.py"))],
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        try:
            bridge = BlenderBridge()
            deadline = time.monotonic() + 20.0
            info = {"ok": False, "error": "bridge did not respond"}
            while time.monotonic() < deadline and process.poll() is None:
                info = bridge.session_info(port=PORT, timeout=1.0)
                if info.get("ok"):
                    break
                time.sleep(0.1)
            report["session"] = info
            if not info.get("ok"):
                return 1
            execution = ActionExecutionEngine().execute_plan(
                plan,
                ExecutionContext(
                    approved=True,
                    policy={
                        "original_prompt": prompt,
                        "pipeline_live_preflight": "required",
                        "dcc_session_ports": {"blender": PORT},
                    },
                ),
            )
            report["execution_status"] = execution.get("status")
            report["status_counts"] = execution.get("status_counts")
            report["preflight"] = execution.get("preflight")
            report["export_exists"] = fbx.is_file()
            report["export_bytes"] = fbx.stat().st_size if fbx.is_file() else 0
            report["export_sha256"] = hashlib.sha256(fbx.read_bytes()).hexdigest() if fbx.is_file() else ""
            report["result_summary"] = {
                key: {
                    "ok": value.get("ok"),
                    "status": value.get("status"),
                    "error": value.get("error"),
                    "result": value.get("result"),
                }
                for key, value in (execution.get("results") or {}).items()
                if isinstance(value, dict)
            }
            if os.environ.get("TC_BENCHMARK_GENERATED_EXPORT") == "1":
                from tech_connector.game_engine.integration.dcc_operation_service import blender_operation_code

                generated_fbx = RESULTS / "generated_static.fbx"
                generated_code = blender_operation_code(
                    "blender.export_fbx",
                    {
                        "output_path": str(generated_fbx),
                        "selection": ["Demo_Prompt_Cube"],
                        "settings": {"bake_animation": False},
                    },
                )
                generated_ok, _generated_response = bridge.execute_on_port(
                    generated_code, port=PORT, timeout=20.0,
                )
                rejected_missing_path, _rejection = bridge.execute_on_port(
                    blender_operation_code("blender.export_fbx", {}),
                    port=PORT, timeout=5.0,
                )
                report["generated_export"] = {
                    "ok": generated_ok,
                    "bytes": generated_fbx.stat().st_size if generated_fbx.is_file() else 0,
                    "missing_path_rejected": not rejected_missing_path,
                }
                if not generated_ok or not report["generated_export"]["bytes"] or rejected_missing_path:
                    return 1
            reimport_code = (
                "import bpy,json; "
                f"bpy.ops.import_scene.fbx(filepath={str(fbx)!r}); "
                "print('TC_REIMPORT_MESHES',json.dumps([o.name for o in bpy.data.objects "
                "if o.type=='MESH' and o.name!='Cube']))"
            )
            reimport = subprocess.run(
                [str(BLENDER_EXE), "--background", "--factory-startup", "--python-expr", reimport_code],
                cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30.0,
                creationflags=creation_flags,
            )
            report["reimport_exit_code"] = reimport.returncode
            report["reimport_meshes"] = []
            for line in reimport.stdout.splitlines():
                if line.startswith("TC_REIMPORT_MESHES "):
                    report["reimport_meshes"] = json.loads(line.removeprefix("TC_REIMPORT_MESHES "))
            report["reimport_error"] = reimport.stderr.strip() if reimport.returncode else ""
            engine_project = RESULTS / f"engine_project_{uuid.uuid4().hex[:8]}"
            engine_project.mkdir(exist_ok=True)
            if os.environ.get("TC_BENCHMARK_DESELECT_BEFORE_CROSS") == "1":
                deselected, deselect_result = bridge.execute_on_port(
                    "import bpy; bpy.ops.object.select_all(action='DESELECT'); print('TC_DESELECTED')",
                    port=PORT,
                    timeout=5.0,
                )
                report["cross_scope_setup"] = {
                    "deselected": deselected,
                    "result": deselect_result,
                }
                if not deselected:
                    return 1
            cross_prompt = (
                "Export a static mesh from Blender into the Tech Connector engine project "
                f"at {engine_project.as_posix()}."
            )
            cross_plan = plan_prompt_to_action_graph(cross_prompt, [str(ROOT)])
            engine_stage = next(
                (stage for stage in cross_plan.get("stages") or [] if stage.get("host") == "tech_connector"),
                {},
            )
            report["cross_host"] = {
                "prompt": cross_prompt,
                "plan_success": bool(cross_plan.get("success")),
                "plan_execution_ready": bool(cross_plan.get("execution_ready")),
                "engine_project_root": (engine_stage.get("params") or {}).get("project_root"),
                "required_inputs": cross_plan.get("required_inputs"),
                "stages": [
                    {"id": stage["id"], "host": stage["host"], "operation": stage["operation"], "params": stage["params"]}
                    for stage in cross_plan.get("stages") or []
                ],
            }
            if report["cross_host"]["engine_project_root"] == engine_project.as_posix():
                cross_execution = ActionExecutionEngine().execute_plan(
                    cross_plan,
                    ExecutionContext(
                        approved=True,
                        policy={
                            "original_prompt": cross_prompt,
                            "pipeline_live_preflight": "required",
                            "dcc_session_ports": {"blender": PORT},
                        },
                    ),
                )
                report["cross_host"]["execution_status"] = cross_execution.get("status")
                report["cross_host"]["status_counts"] = cross_execution.get("status_counts")
                report["cross_host"]["preflight"] = cross_execution.get("preflight")
                report["cross_host"]["action_results"] = {
                    key: {
                        "ok": value.get("ok"),
                        "status": value.get("status"),
                        "error": value.get("error"),
                        "exception_message": value.get("exception_message"),
                        "keys": sorted(value),
                        "output": value.get("output"),
                        "raw_result": value.get("raw_result"),
                    }
                    for key, value in (cross_execution.get("results") or {}).items()
                    if isinstance(value, dict)
                }
            report["cross_host"]["asset_database_exists"] = (
                engine_project / ".tech_connector" / "assets.sqlite3"
            ).is_file()
            report["cross_host"]["imported_fbx_paths"] = [
                path.relative_to(engine_project).as_posix()
                for path in (engine_project / "Assets").rglob("*.fbx")
            ]
            export_result = (
                report["cross_host"].get("action_results", {})
                .get("stage_01_blender_io_export_fbx", {})
                .get("raw_result", {})
                .get("result", {})
            )
            cross_source = Path(str(export_result.get("fbx_path") or ""))
            imported_paths = report["cross_host"]["imported_fbx_paths"]
            imported_fbx = engine_project / imported_paths[0] if imported_paths else None
            report["cross_host"]["byte_match"] = bool(
                cross_source.is_file()
                and imported_fbx is not None
                and imported_fbx.is_file()
                and hashlib.sha256(cross_source.read_bytes()).digest()
                == hashlib.sha256(imported_fbx.read_bytes()).digest()
            )
            return 0 if (
                execution.get("status") == "completed"
                and report["export_bytes"] > 0
                and reimport.returncode == 0
                and len(report["reimport_meshes"]) >= 2
                and any(name.endswith("_LOD1") for name in report["reimport_meshes"])
                and report["cross_host"].get("execution_status") == "completed"
                and report["cross_host"]["asset_database_exists"]
                and report["cross_host"]["imported_fbx_paths"]
                and report["cross_host"]["byte_match"]
            ) else 1
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
            (RESULTS / "report.json").write_text(
                json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
            )
            session_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
