from __future__ import annotations

"""Source-bound execution receipts for the capability maturity evidence suite."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping

from tech_connector.game_engine.integration.adaptive_scene_command_service import ADAPTIVE_SCENE_COMMANDS
from tech_connector.game_engine.integration.capability_maturity_service import CAPABILITY_EVIDENCE, audit_capability_maturity
from tech_connector.game_engine.integration.playable_project_qualification_service import playable_project_source_fingerprint


CAPABILITY_QUALIFICATION_SCHEMA = "tech_connector.capability_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0


def capability_test_files(source_root: str | Path) -> tuple[Path, ...]:
    root = Path(source_root).expanduser().resolve()
    names = sorted({
        str(value) for evidence in CAPABILITY_EVIDENCE.values()
        for value in (*evidence.deterministic_tests, *evidence.persistence_tests,
                      *evidence.transfer_readback_tests, *evidence.performance_baselines,
                      *evidence.recovery_tests)
        if str(value).endswith(".py")
    })
    return tuple(root / "tech_connector" / "tests" / name for name in names)


def qualify_capability_evidence(
    source_root: str | Path, output_root: str | Path, *, timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve(); output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True); run_id = f"run-{time.time_ns()}"
    files = capability_test_files(source); missing = [str(path) for path in files if not path.is_file()]
    started = time.perf_counter(); stdout = ""; stderr = ""; exit_code = -1; timed_out = False
    if not missing:
        # Keep the pytest root shallow. Several generated player/scene filenames
        # are already descriptive; nesting them below the receipt run ID can
        # exceed Windows path limits and turn valid evidence into setup errors.
        command = [sys.executable, "-m", "pytest", "-q", *(str(path) for path in files),
                   "--basetemp", str(source / ".pytest_capability_qualification"), "-o", "faulthandler_timeout=60"]
        environment = os.environ.copy(); environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            result = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True,
                                    timeout=max(1.0, float(timeout_seconds)), check=False)
            stdout, stderr, exit_code = result.stdout, result.stderr, int(result.returncode)
        except subprocess.TimeoutExpired as exc:
            timed_out = True; stdout = str(exc.stdout or ""); stderr = str(exc.stderr or "")
    elapsed = time.perf_counter() - started
    match = re.search(r"(\d+) passed", stdout)
    passed_tests = int(match.group(1)) if match else 0
    maturity = audit_capability_maturity(ADAPTIVE_SCENE_COMMANDS.values())
    production = sorted(row["capability"] for row in maturity["capabilities"] if row["verified_maturity"] in {"production", "qualified"})
    passed = not missing and not timed_out and exit_code == 0 and passed_tests > 0
    receipt = {
        "schema": CAPABILITY_QUALIFICATION_SCHEMA, "status": "passed" if passed else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "elapsed_seconds": round(elapsed, 6), "timeout_seconds": float(timeout_seconds),
        "test_files": [str(path.relative_to(source).as_posix()) for path in files], "missing_test_files": missing,
        "passed_tests": passed_tests, "exit_code": exit_code, "timed_out": timed_out,
        "production_capabilities": production, "maturity_counts": maturity["counts"],
        "stdout_tail": stdout[-4000:], "stderr_tail": stderr[-4000:],
    }
    report = output / "capability_qualification.json"; temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8"); temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_capability_qualification(source_root: str | Path, receipt: Mapping[str, Any] | None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != CAPABILITY_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed" or int(row.get("exit_code", -1)) != 0 or int(row.get("passed_tests", 0)) <= 0: gates.append("tests")
    if row.get("missing_test_files"): gates.append("missing_test_files")
    verified = _timestamp(row.get("verified_at")); now = datetime.now(timezone.utc).timestamp()
    if verified <= 0.0 or now - verified > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected: gates.append("source_fingerprint")
    return {"valid": not gates, "gates": sorted(set(gates)), "age_seconds": max(0.0, now - verified) if verified > 0 else None,
            "source_fingerprint": expected}


def load_capability_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = ["CAPABILITY_QUALIFICATION_SCHEMA", "capability_test_files", "load_capability_qualification",
           "qualify_capability_evidence", "validate_capability_qualification"]
