from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
NATIVE_ROOT = ROOT / "tech_connector" / "game_engine" / "native"
DEFAULT_OUTPUT_ROOT = ROOT / ".tech_connector" / "acceptance"
MODULE_NAME = "tech_connector.acceptance.tomorrow_readiness"


@dataclass
class AcceptanceCheck:
    key: str
    label: str
    status: str
    required: bool
    duration_seconds: float
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _environment(**updates: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        normalized = "PATH" if key.casefold() == "path" else key
        if normalized == "PATH" and normalized in result:
            continue
        result[normalized] = value
    result.update(updates)
    return result


def _command_check(
    key: str, label: str, command: list[str], *, required: bool = True,
    timeout: int = 180, environment: dict[str, str] | None = None,
) -> AcceptanceCheck:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=environment or _environment(), capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        status = "pass" if completed.returncode == 0 else "fail"
        summary = output.splitlines()[-1] if output else f"Exited with code {completed.returncode}."
        return AcceptanceCheck(key, label, status, required, time.perf_counter() - started, summary, {
            "command": command, "return_code": completed.returncode, "output_tail": output.splitlines()[-40:],
        })
    except (OSError, subprocess.TimeoutExpired) as exc:
        return AcceptanceCheck(key, label, "fail", required, time.perf_counter() - started, str(exc), {"command": command})


def _ui_probe() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport

    app = QApplication.instance() or QApplication(sys.argv)
    started = time.perf_counter()
    widget = ThreeDMeshPainterViewport()
    app.processEvents()
    evidence = {
        "construction_ms": (time.perf_counter() - started) * 1000.0,
        "default_mode": widget.viewport_mode,
        "has_canvas": bool(getattr(widget, "canvas", None)),
        "runtime_entities": len(widget._runtime_world_state.get("entities") or ()),
    }
    widget.close()
    app.processEvents()
    if evidence["default_mode"] != "Selection" or not evidence["has_canvas"]:
        print(json.dumps(evidence))
        return 2
    print(json.dumps(evidence, sort_keys=True))
    return 0


class TomorrowReadinessRunner:
    def __init__(self, output_directory: Path, *, full: bool = False) -> None:
        self.output_directory = output_directory
        self.full = bool(full)
        self.output_directory.mkdir(parents=True, exist_ok=True)
        self.checks: list[AcceptanceCheck] = []

    def run(self) -> dict[str, Any]:
        self._python_suite()
        self._native_suite()
        self._ui_smoke()
        self._vertical_slice()
        self._physics_qualification()
        self._dcc_structure()
        report = self._report()
        self._write_report(report)
        return report

    def _python_suite(self) -> None:
        base = self.output_directory / "pytest"
        self.checks.append(_command_check(
            "python_suite", "Engine and DCC Python suite",
            [sys.executable, "-m", "pytest", "tech_connector/tests", "-q", "--basetemp", str(base)],
            timeout=300 if self.full else 180,
        ))

    def _native_suite(self) -> None:
        build = NATIVE_ROOT / ".tech_connector" / "cmake" / "Release"
        if not (build / "CMakeCache.txt").is_file():
            self.checks.append(_command_check(
                "native_configure", "Configure native runtime",
                ["cmake", "-S", str(NATIVE_ROOT), "-B", str(build), "-DTC_GRAPH_BUILD_TESTS=ON", "-DTC_RUNTIME_BUILD_PLAYER=ON"],
            ))
            if self.checks[-1].status != "pass":
                return
        self.checks.append(_command_check(
            "native_build", "Build native runtime and player",
            ["cmake", "--build", str(build), "--config", "Release"], timeout=300,
        ))
        if self.checks[-1].status == "pass":
            self.checks.append(_command_check(
                "native_tests", "Native runtime tests",
                ["ctest", "--test-dir", str(build), "-C", "Release", "--output-on-failure"],
            ))

    def _ui_smoke(self) -> None:
        self.checks.append(_command_check(
            "scene_ui_smoke", "The Entire Scene offscreen construction",
            [sys.executable, "-m", MODULE_NAME, "--probe-ui"], timeout=60,
            environment=_environment(QT_QPA_PLATFORM="offscreen"),
        ))

    def _vertical_slice(self) -> None:
        from tech_connector.examples.game_engine.converted_unreal_vertical_slice import create_sample
        from tech_connector.game_engine.runtime.tc_player_build_service import compile_tcscene_for_runtime, _resolve_player_executable

        started = time.perf_counter()
        try:
            scene = create_sample(self.output_directory / "vertical_slice.tcscene")
            receipt = compile_tcscene_for_runtime(scene, self.output_directory / "vertical_slice.tcruntime")
            log = self.output_directory / "vertical_slice.jsonl"
            log.unlink(missing_ok=True)
            player = _resolve_player_executable(None)
            frames = 300 if self.full else 90
            completed = subprocess.run(
                [str(player), "--headless", "--scene", str(receipt.runtime_manifest), "--frames", str(frames), "--log", str(log)],
                cwd=ROOT, env=_environment(), capture_output=True, text=True, timeout=120, check=False,
            )
            telemetry = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
            passed = completed.returncode == 0 and len(telemetry) == frames and receipt.graph_operations > 0
            self.checks.append(AcceptanceCheck(
                "native_vertical_slice", "Converted scene in standalone player", "pass" if passed else "fail", True,
                time.perf_counter() - started,
                f"{len(telemetry)}/{frames} frames, {receipt.entities} entities, {receipt.graph_operations} graph operations.",
                {"scene": str(scene), "manifest": str(receipt.runtime_manifest), "player": str(player),
                 "warnings": list(receipt.warnings), "stderr": completed.stderr.splitlines()[-20:]},
            ))
        except Exception as exc:
            self.checks.append(AcceptanceCheck(
                "native_vertical_slice", "Converted scene in standalone player", "fail", True,
                time.perf_counter() - started, str(exc), {},
            ))

    def _physics_qualification(self) -> None:
        from tech_connector.game_engine.runtime.tc_physics_stress_service import qualify_physics_stress_scenarios

        started = time.perf_counter()
        try:
            qualification = qualify_physics_stress_scenarios(
                count=1000 if self.full else 64, frames=180 if self.full else 45,
                warmup_frames=30 if self.full else 10,
                working_directory=self.output_directory / "physics",
            )
            scenarios = qualification["scenarios"]
            worst_name, worst = max(
                scenarios.items(), key=lambda item: float(item[1].get("p95_physics_ms", float("inf"))))
            maximum_error = max(float(row.get("maximum_joint_position_error", 0.0)) for row in scenarios.values())
            targets = dict(qualification.get("targets") or {})
            self.checks.append(AcceptanceCheck(
                "physics_qualification", "Native physics frame budgets", "pass" if qualification["qualified"] else "fail", True,
                time.perf_counter() - started,
                f"{sum(row.get('qualified', False) for row in scenarios.values())}/{len(scenarios)} qualified; "
                f"worst p95 {worst_name} {float(worst.get('p95_physics_ms', 0.0)):.2f}/"
                f"{float(targets.get('physics_p95_ms', 0.0)):.2f} ms; residual "
                f"{maximum_error:.3f}/{float(targets.get('maximum_joint_position_error', 0.0)):.3f}.",
                qualification,
            ))
        except Exception as exc:
            self.checks.append(AcceptanceCheck(
                "physics_qualification", "Native physics frame budgets", "fail", True,
                time.perf_counter() - started, str(exc), {},
            ))

    def _dcc_structure(self) -> None:
        from tech_connector.game_engine.integration.dcc_release_readiness_service import audit_dcc_release_readiness

        started = time.perf_counter()
        audit = audit_dcc_release_readiness(verify_live_host_sessions=False, verify_live_source_sessions=False)
        incomplete = [row["host"] for row in audit["hosts"] if row["status"] == "incomplete"]
        status = "fail" if incomplete else "warn"
        self.checks.append(AcceptanceCheck(
            "external_dcc_readiness", "External DCC structural readiness", status, False,
            time.perf_counter() - started,
            "Structural contracts pass; live host/workflow receipts are still required." if not incomplete else f"Incomplete hosts: {', '.join(incomplete)}",
            audit,
        ))

    def _report(self) -> dict[str, Any]:
        required_failures = [check.key for check in self.checks if check.required and check.status != "pass"]
        return {
            "schema": "tech_connector.tomorrow_readiness.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "full" if self.full else "quick",
            "ready_for_local_testing": not required_failures,
            "required_failures": required_failures,
            "warnings": [check.key for check in self.checks if check.status == "warn"],
            "checks": [asdict(check) for check in self.checks],
        }

    def _write_report(self, report: dict[str, Any]) -> None:
        json_path = self.output_directory / "readiness.json"
        markdown_path = self.output_directory / "TEST_CHECKLIST.md"
        json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [
            "# Tomorrow Test Readiness", "",
            f"Mode: **{report['mode']}**", f"Local testing: **{'READY' if report['ready_for_local_testing'] else 'NOT READY'}**", "",
            "## Automated Gates", "",
        ]
        for check in self.checks:
            lines.append(f"- [{ 'x' if check.status == 'pass' else ' ' }] **{check.label}** - {check.status.upper()}: {check.summary}")
        lines.extend([
            "", "## Hands-On Pass", "",
            "- [ ] Launch Tech Connector and confirm the splash never reveals or minimizes the main window early.",
            "- [ ] Open The Entire Scene; orbit, pan, dolly, select, translate, rotate, and scale on isolated axes.",
            "- [ ] Paint one surface stroke, undo/redo it, and confirm paint remains inside the brush footprint.",
            "- [ ] Deform a mesh, set its current shape as default, deform again, restore default shape, then undo once.",
            "- [ ] Create a physics joint; drag both anchors and its axis handle; undo the drag once.",
            "- [ ] Run play-in-editor and verify input, collision, animation, audio, UI, save, and error navigation.",
            "- [ ] Save the scene and confirm the connected player receives the changed runtime-world chunk.",
            "- [ ] Convert one real Maya scene in chunks: geometry, skeleton, skinning, animation, then rig build.",
            "- [ ] Connect each available DCC and record live host, source-parity, and workflow receipts.",
            "", "## Known Evidence Boundary", "",
            "Automated local readiness does not qualify unavailable external DCC sessions, visual fidelity, or subjective interaction quality. Those remain explicit hands-on checks.",
        ])
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        latest = DEFAULT_OUTPUT_ROOT / "latest.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, latest)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Tech Connector's tomorrow test-readiness acceptance suite.")
    parser.add_argument("--full", action="store_true", help="Use 1,000-body physics qualification and longer player execution.")
    parser.add_argument("--output", type=Path, help="Directory for evidence and the hands-on checklist.")
    parser.add_argument("--probe-ui", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.probe_ui:
        return _ui_probe()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = arguments.output or DEFAULT_OUTPUT_ROOT / timestamp
    report = TomorrowReadinessRunner(output, full=arguments.full).run()
    print(json.dumps({
        "ready_for_local_testing": report["ready_for_local_testing"],
        "report": str(output / "readiness.json"), "checklist": str(output / "TEST_CHECKLIST.md"),
        "required_failures": report["required_failures"], "warnings": report["warnings"],
    }, indent=2))
    return 0 if report["ready_for_local_testing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["AcceptanceCheck", "TomorrowReadinessRunner", "main"]
