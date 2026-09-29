from __future__ import annotations

"""Source-bound qualification for the complete Tech Connector regression suite."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any, Mapping

from tech_connector.game_engine.integration.playable_project_qualification_service import (
    playable_project_source_fingerprint,
)


RELEASE_REGRESSION_QUALIFICATION_SCHEMA = "tech_connector.release_regression_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0
MINIMUM_PYTHON = (3, 10)


def qualify_release_regression(
    source_root: str | Path,
    output_root: str | Path,
    *,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = f"run-{time.time_ns()}"
    suite = source / "tech_connector" / "tests"
    started = time.perf_counter()
    stdout = ""; stderr = ""; exit_code = -1; timed_out = False
    interpreter_supported = tuple(sys.version_info[:2]) >= MINIMUM_PYTHON
    if suite.is_dir() and interpreter_supported:
        command = [
            sys.executable, "-m", "pytest", str(suite), "-q",
            "--basetemp", str(source / ".pytest_release_qualification"),
            "-o", "faulthandler_timeout=60",
        ]
        environment = os.environ.copy()
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            result = subprocess.run(
                command, cwd=source, env=environment, capture_output=True,
                text=True, timeout=max(1.0, float(timeout_seconds)), check=False,
            )
            stdout, stderr, exit_code = result.stdout, result.stderr, int(result.returncode)
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout, stderr = str(error.stdout or ""), str(error.stderr or "")
    passed_match = re.search(r"(\d+) passed", stdout)
    skipped_match = re.search(r"(\d+) skipped", stdout)
    failed_match = re.search(r"(\d+) failed", stdout)
    passed_tests = int(passed_match.group(1)) if passed_match else 0
    skipped_tests = int(skipped_match.group(1)) if skipped_match else 0
    failed_tests = int(failed_match.group(1)) if failed_match else 0
    passed = bool(
        suite.is_dir() and interpreter_supported and not timed_out
        and exit_code == 0 and passed_tests > 0 and failed_tests == 0
    )
    receipt = {
        "schema": RELEASE_REGRESSION_QUALIFICATION_SCHEMA,
        "status": "passed" if passed else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "timeout_seconds": float(timeout_seconds),
        "suite": str(suite.relative_to(source).as_posix()),
        "passed_tests": passed_tests,
        "skipped_tests": skipped_tests,
        "failed_tests": failed_tests,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "interpreter": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "minimum_version": ".".join(map(str, MINIMUM_PYTHON)),
            "supported": interpreter_supported,
        },
        "stdout_tail": stdout[-6000:],
        "stderr_tail": stderr[-6000:],
    }
    report = output / "release_regression_qualification.json"
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_release_regression_qualification(
    source_root: str | Path,
    receipt: Mapping[str, Any] | None,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    row = dict(receipt or {})
    gates: list[str] = []
    if row.get("schema") != RELEASE_REGRESSION_QUALIFICATION_SCHEMA:
        gates.append("schema")
    if row.get("status") != "passed" or int(row.get("exit_code", -1)) != 0:
        gates.append("tests")
    if int(row.get("passed_tests", 0)) <= 0 or int(row.get("failed_tests", 0)) != 0:
        gates.append("test_counts")
    if bool(row.get("timed_out")):
        gates.append("timeout")
    if not bool(dict(row.get("interpreter") or {}).get("supported")):
        gates.append("interpreter")
    verified_at = _timestamp(row.get("verified_at"))
    now = datetime.now(timezone.utc).timestamp()
    if verified_at <= 0.0 or now - verified_at > max(0.0, float(max_age_seconds)):
        gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected:
        gates.append("source_fingerprint")
    return {
        "valid": not gates,
        "gates": sorted(set(gates)),
        "age_seconds": max(0.0, now - verified_at) if verified_at > 0.0 else None,
        "source_fingerprint": expected,
    }


def load_release_regression_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "RELEASE_REGRESSION_QUALIFICATION_SCHEMA",
    "load_release_regression_qualification",
    "qualify_release_regression",
    "validate_release_regression_qualification",
]
