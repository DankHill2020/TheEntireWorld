"""Run a real read-only selected-joint prompt against isolated Maya 2023."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ["TC_MAYA_QUERY_PROOF_ROOT"]).resolve()
FOLDER = SCRATCH / "maya_live_query_v1"
MAYAPY = Path(r"C:\Program Files\Autodesk\Maya2023\bin\mayapy.exe")
PORT = 7011
PROMPT = "List the selected joints in Maya without changing the scene."


def main() -> int:
    if FOLDER.exists() and any(FOLDER.iterdir()):
        raise FileExistsError(f"Refusing nonempty proof output: {FOLDER}")
    FOLDER.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "TECH_CONNECTOR_BRIDGE_SESSION_FILE": str(FOLDER / "bridge_session.json"),
        "MAYA_COMMAND_PORT": str(PORT),
        "MAYA_COMMAND_PORT_SCAN_COUNT": "1",
        "MAYA_COMMAND_PORT_FILE": str(FOLDER / "maya_port.txt"),
        "MAYA_COMMAND_SESSION_FILE": str(FOLDER / "maya_sessions.json"),
        "TEMP": str(SCRATCH), "TMP": str(SCRATCH),
    })
    from tech_connector.bridges.maya.maya_bridge import MayaBridge
    from tech_connector.bridges.session_authorization import bridge_session_token
    from tech_connector.engine.request_engine import RequestEngine
    from tech_connector.engine.request_context import RequestContext

    assert bridge_session_token("maya")
    env = os.environ.copy()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    report = {"schema": "tech_connector.maya_joint_query_prompt.v1", "prompt": PROMPT,
              "maya_version": "2023", "port": PORT}
    snapshot_code = """
import json
import maya.cmds as cmds
print(json.dumps({
    'joints': cmds.ls(type='joint') or [],
    'selection': cmds.ls(selection=True) or [],
    'modified': bool(cmds.file(q=True, modified=True)),
    'root_translation': cmds.getAttr('demo_root_jnt.translate')[0],
    'child_translation': cmds.getAttr('demo_child_jnt.translate')[0],
}))
"""
    with (FOLDER / "maya_host.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(MAYAPY), str(ROOT / "tech_connector" / "benchmarks" / "live_maya_pipeline_host.py")],
            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        try:
            bridge = MayaBridge()
            deadline = time.monotonic() + 55
            session = {"ok": False}
            while time.monotonic() < deadline and process.poll() is None:
                session = bridge.session_info(port=PORT, timeout=3)
                if session.get("ok"):
                    break
                time.sleep(0.1)
            report["session"] = session
            if not session.get("ok"):
                raise RuntimeError("Maya bridge did not become ready")
            setup = """
import maya.cmds as cmds
cmds.file(new=True, force=True)
cmds.select(clear=True)
cmds.joint(name='demo_root_jnt', position=(0, 0, 0))
cmds.joint(name='demo_child_jnt', position=(0, 4, 0))
cmds.select('demo_root_jnt', 'demo_child_jnt')
print('TC_JOINT_QUERY_SCENE_READY')
"""
            ok, raw = bridge.execute_on_port(setup, port=PORT, timeout=20)
            if not ok or "TC_JOINT_QUERY_SCENE_READY" not in raw:
                raise RuntimeError(f"Maya fixture setup failed: {raw}")
            ok, raw = bridge.execute_on_port(snapshot_code, port=PORT, timeout=10)
            if not ok:
                raise RuntimeError(f"Maya pre-query snapshot failed: {raw}")
            report["before"] = json.loads(raw)
            started = time.monotonic()
            result = RequestEngine(progress=lambda _event: None).process(
                RequestContext(text=PROMPT, project_roots=[str(ROOT)])
            )
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            report["result"] = {
                "action": result.action,
                "text": result.text,
                "metadata": result.metadata,
            }
            ok, raw = bridge.execute_on_port(snapshot_code, port=PORT, timeout=10)
            if not ok:
                raise RuntimeError(f"Maya post-query snapshot failed: {raw}")
            report["after"] = json.loads(raw)
            dispatch = (result.metadata or {}).get("dispatch_result") or {}
            query = (dispatch.get("structured_data") or {}).get("ls_query") or {}
            report["ok"] = (
                result.action == "answer"
                and (result.metadata or {}).get("result_type") == "dcc_completed"
                and query.get("flags") == {"selection": True, "type": "joint"}
                and query.get("items") == ["demo_root_jnt", "demo_child_jnt"]
                and report["before"] == report["after"]
            )
        except Exception as exc:
            report["ok"] = False
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            (FOLDER / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(FOLDER / "report.json"),
                      "error": report.get("error", "")}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
