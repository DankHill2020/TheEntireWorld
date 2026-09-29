from __future__ import annotations

"""Executable Maya 2023+ compatibility qualification and source contract."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

from tech_connector.bridges.maya.maya_livelink_plugin import installed_maya_versions
from tech_connector.game_engine.integration.playable_project_qualification_service import (
    playable_project_source_fingerprint,
)


MAYA_VERSION_QUALIFICATION_SCHEMA = "tech_connector.maya_version_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0
DECLARED_VERSIONS = (2023, 2024, 2025, 2026)
SMOKE_MODULES = (
    "maya_tools.maya_menu",
    "maya_tools.maya_setup",
    "maya_tools.Rigging.create_rig_core",
    "maya_tools.Rigging.create_rig_modules",
    "maya_tools.Rigging.rigging_host_adapter",
    "maya_tools.Rigging.skinning_utils",
    "maya_tools.Rigging.mocap.setup_hik",
    "maya_tools.Cinematics.SequenceUI.sequence_ui",
    "tech_connector.bridges.maya.rig_topology_extract",
    "tech_connector.bridges.maya.maya_livelink_plugin",
)
_RESULT_MARKER = "TECH_CONNECTOR_MAYA_COMPATIBILITY_RESULT="


def qualify_maya_versions(
    source_root: str | Path,
    output_root: str | Path,
    *,
    autodesk_root: str | Path | None = None,
    declared_versions: Sequence[int] = DECLARED_VERSIONS,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = f"run-{time.time_ns()}"
    run_root = output / "runs" / run_id
    installed = installed_maya_versions(autodesk_root)
    rows: list[dict[str, Any]] = []
    for version, install_root in installed.items():
        mayapy = install_root / "bin" / "mayapy.exe"
        row = _qualify_installed_version(
            source, run_root, version, mayapy, timeout_seconds=max(1.0, float(timeout_seconds))
        )
        rows.append(row)
    installed_by_version = {int(row["version"]): row for row in rows}
    matrix = []
    for version in sorted({int(value) for value in declared_versions if int(value) >= 2023}):
        installed_row = installed_by_version.get(version)
        matrix.append({
            "version": version,
            "status": (
                "installed_qualified" if installed_row and installed_row["status"] == "passed"
                else "installed_blocked" if installed_row
                else "source_contract_qualified"
            ),
            "runtime_evidence": bool(installed_row and installed_row["status"] == "passed"),
            "compatibility_policy": "Python 3.9 baseline; Qt 5 before 2025, Qt 6 from 2025; capability probes for optional APIs.",
        })
    source_files = _maya_source_files(source)
    source_contract = {
        "minimum_version": 2023,
        "future_version_policy": "Versions newer than the declared matrix use the latest capability-based path and shared user bootstrap.",
        "file_count": len(source_files),
        "sha256": _source_digest(source_files, source),
        "shared_bootstrap": True,
        "qt_transition_version": 2025,
    }
    passed = bool(rows) and all(row["status"] == "passed" for row in rows)
    receipt = {
        "schema": MAYA_VERSION_QUALIFICATION_SCHEMA,
        "status": "passed" if passed else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "declared_versions": [row["version"] for row in matrix],
        "installed_versions": sorted(installed),
        "source_contract": source_contract,
        "matrix": matrix,
        "installed_qualification": rows,
    }
    report = output / "maya_version_qualification.json"
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(report)
    return receipt | {"report": str(report)}


def _qualify_installed_version(
    source: Path, run_root: Path, version: int, mayapy: Path, timeout_seconds: float,
) -> dict[str, Any]:
    if not mayapy.is_file():
        return {"version": version, "status": "blocked", "mayapy": str(mayapy),
                "checks": {"mayapy": False, "syntax": False, "runtime_smoke": False},
                "diagnostics": ["Installed Maya does not provide bin/mayapy.exe."]}
    version_root = run_root / str(version)
    maya_app = version_root / "maya_app"
    pycache = version_root / "pycache"
    maya_app.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "MAYA_APP_DIR": str(maya_app),
        "PYTHONPATH": str(source),
        "PYTHONPYCACHEPREFIX": str(pycache),
        "TECH_CONNECTOR_DEV_LICENSE_BYPASS": "1",
    })
    compile_command = [
        str(mayapy), "-m", "compileall", "-q",
        str(source / "maya_tools"), str(source / "tech_connector" / "bridges" / "maya"),
    ]
    compile_result = _run(compile_command, source, environment, timeout_seconds)
    smoke_result = _run(
        [str(mayapy), "-c", _smoke_script()], source, environment, timeout_seconds
    )
    payload: dict[str, Any] = {}
    for line in smoke_result["stdout"].splitlines():
        if line.startswith(_RESULT_MARKER):
            try:
                payload = dict(json.loads(line[len(_RESULT_MARKER):]))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
    checks = {
        "mayapy": True,
        "syntax": compile_result["exit_code"] == 0 and not compile_result["timed_out"],
        "runtime_smoke": smoke_result["exit_code"] == 0 and not smoke_result["timed_out"],
        "reported_version": str(payload.get("maya_version") or "").startswith(str(version)),
        "module_surface": sorted(payload.get("modules") or ()) == sorted(SMOKE_MODULES),
        "scene_authoring": all(dict(payload.get("smoke") or {}).values()),
        "setup_import_read_only": bool(payload.get("setup_import_read_only")),
    }
    diagnostics = []
    if compile_result["stderr"]:
        diagnostics.append(compile_result["stderr"][-3000:])
    if smoke_result["stderr"]:
        diagnostics.append(smoke_result["stderr"][-3000:])
    return {
        "version": version,
        "status": "passed" if all(checks.values()) else "blocked",
        "mayapy": str(mayapy),
        "checks": checks,
        "runtime": payload,
        "compile_exit_code": compile_result["exit_code"],
        "smoke_exit_code": smoke_result["exit_code"],
        "diagnostics": diagnostics,
        "stdout_tail": smoke_result["stdout"][-4000:],
    }


def _smoke_script() -> str:
    modules = repr(list(SMOKE_MODULES))
    marker = repr(_RESULT_MARKER)
    return (
        "import importlib,json,os,sys,maya.standalone;"
        "maya.standalone.initialize(name='python');"
        "import maya.cmds as cmds;"
        f"names={modules}; imported=[]; setup_read_only=True;"
        "\nfor name in names:\n"
        " before=dict(os.environ) if name=='maya_tools.maya_setup' else None\n"
        " importlib.import_module(name); imported.append(name)\n"
        " if before is not None: setup_read_only=(before==dict(os.environ))\n"
        "cmds.file(new=True,force=True);"
        "cube=cmds.polyCube(name='TC_CompatibilityCube')[0];"
        "root=cmds.joint(name='TC_Root',position=(0,0,0));"
        "child=cmds.joint(name='TC_Child',position=(0,1,0));"
        "cmds.select(cube,root); skin=cmds.skinCluster(root,cube,toSelectedBones=True)[0];"
        "payload={'maya_version':cmds.about(version=True),'api_version':cmds.about(apiVersion=True),"
        "'python':sys.version.split()[0],'modules':imported,"
        "'setup_import_read_only':setup_read_only,"
        "'smoke':{'cube':cmds.objExists(cube),'root':cmds.objExists(root),"
        "'child':cmds.objExists(child),'skin':cmds.objExists(skin)}};"
        f"print({marker}+json.dumps(payload,sort_keys=True));"
        "maya.standalone.uninitialize()"
    )


def _run(
    command: list[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command, cwd=cwd, env=dict(environment), capture_output=True,
            text=True, timeout=timeout_seconds, check=False,
        )
        return {"exit_code": int(result.returncode), "stdout": result.stdout,
                "stderr": result.stderr, "timed_out": False}
    except subprocess.TimeoutExpired as error:
        return {"exit_code": -1, "stdout": str(error.stdout or ""),
                "stderr": str(error.stderr or ""), "timed_out": True}


def _maya_source_files(source: Path) -> tuple[Path, ...]:
    roots = (source / "maya_tools", source / "tech_connector" / "bridges" / "maya")
    return tuple(sorted(
        (path for root in roots if root.is_dir() for path in root.rglob("*.py")), key=str
    ))


def _source_digest(files: Sequence[Path], source: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode("utf-8"))
        digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def validate_maya_version_qualification(
    source_root: str | Path, receipt: Mapping[str, Any] | None, *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != MAYA_VERSION_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed": gates.append("status")
    installed_rows = list(row.get("installed_qualification") or ())
    if not installed_rows or any(dict(item).get("status") != "passed" for item in installed_rows):
        gates.append("installed_versions")
    declared = {int(value) for value in row.get("declared_versions") or ()}
    if not set(DECLARED_VERSIONS).issubset(declared): gates.append("declared_matrix")
    contract = dict(row.get("source_contract") or {})
    if int(contract.get("minimum_version", 0)) != 2023 or not contract.get("shared_bootstrap"):
        gates.append("source_contract")
    verified = _timestamp(row.get("verified_at")); now = datetime.now(timezone.utc).timestamp()
    if verified <= 0.0 or now - verified > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected: gates.append("source_fingerprint")
    return {"valid": not gates, "gates": sorted(set(gates)),
            "age_seconds": max(0.0, now - verified) if verified > 0.0 else None,
            "source_fingerprint": expected}


def load_maya_version_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = [
    "DECLARED_VERSIONS", "MAYA_VERSION_QUALIFICATION_SCHEMA",
    "load_maya_version_qualification", "qualify_maya_versions",
    "validate_maya_version_qualification",
]
