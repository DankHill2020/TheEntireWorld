"""Check a live Maya selected-joint query receipt without trusting its success flag."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROMPT = "List the selected joints in Maya without changing the scene."
JOINTS = ["demo_root_jnt", "demo_child_jnt"]


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_maya_joint_query_prompt_proof(report_path: str | Path) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(report, dict)
             and report.get("schema") == "tech_connector.maya_joint_query_prompt.v1"
             and report.get("prompt") == PROMPT
             and report.get("ok") is True, "Invalid Maya query receipt")
    session = report.get("session") or {}
    _require(session.get("ok") is True and session.get("version") == "2023"
             and isinstance(session.get("pid"), int) and session["pid"] > 0
             and session.get("port") == report.get("port"),
             "Authenticated Maya session missing")
    before = report.get("before") or {}
    after = report.get("after") or {}
    _require(before == after
             and before.get("selection") == JOINTS
             and set(before.get("joints") or []) == set(JOINTS)
             and before.get("modified") is True
             and before.get("root_translation") == [0.0, 0.0, 0.0]
             and before.get("child_translation") == [0.0, 4.0, 0.0],
             "Maya scene or selection changed during read-only query")
    result = report.get("result") or {}
    metadata = result.get("metadata") or {}
    request = metadata.get("dcc_request") or {}
    dispatch = metadata.get("dispatch_result") or {}
    data = dispatch.get("structured_data") or {}
    query = data.get("ls_query") or {}
    _require(result.get("action") == "answer"
             and metadata.get("result_type") == "dcc_completed"
             and request.get("original_prompt") == PROMPT
             and request.get("execution_environment") == "maya"
             and request.get("operation_mode") == "query"
             and request.get("target_identifier") == "scene.ls"
             and request.get("mutation_scope") == "read_only"
             and dispatch.get("status") == "completed"
             and dispatch.get("execution_environment") == "maya"
             and dispatch.get("operation_mode") == "query"
             and dispatch.get("affected_targets") == []
             and dispatch.get("executed_code") == ""
             and data.get("operation") == "scene.ls"
             and query.get("kind") == "maya.cmds.ls"
             and query.get("flags") == {"selection": True, "type": "joint"}
             and query.get("items") == JOINTS
             and query.get("count") == len(JOINTS)
             and all(f"`{name}`" in result.get("text", "") for name in JOINTS),
             "Maya query result does not match prompt or live selection")
    _require(0 < float(report.get("elapsed_seconds") or 0) < 60,
             "Query duration is implausible")
    host_log = path.parent / "maya_host.log"
    _require(host_log.is_file() and host_log.stat().st_size > 0,
             "Maya host log missing")
    return {"verified": True, "selected_joints": JOINTS,
            "elapsed_seconds": float(report["elapsed_seconds"]),
            "maya_version": session["version"], "scene_unchanged": True}
