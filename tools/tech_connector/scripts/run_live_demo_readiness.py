"""Run prompt and direct-UI demo-readiness lanes without project-local artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter


TOOLS_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = TOOLS_ROOT / "tech_connector" / "examples" / "tests"


@dataclass(frozen=True)
class DemoLane:
    name: str
    purpose: str
    tests: tuple[str, ...]
    live: bool = False


LANES = (
    DemoLane(
        name="direct_ui",
        purpose="Prompt editing, streaming, autocomplete, model selection, and editor progress.",
        tests=(
            "test_growing_prompt_edit.py",
            "test_chat_stream_freeze_guard.py",
            "test_chat_autocomplete_popup.py",
            "test_model_selector_ui.py",
            "test_editor_assist_progress.py",
        ),
    ),
    DemoLane(
        name="pipeline_ui",
        purpose="Smart menus, source-aware search, graph intelligence, and safe Python materialization.",
        tests=(
            "test_pipeline_tool_menu.py",
            "test_pipeline_function_search_ranking.py",
            "test_pipeline_graph_intelligence_service.py",
            "test_pipeline_prompt_materialization.py",
            "test_pipeline_python_paste_safety.py",
        ),
    ),
    DemoLane(
        name="prompt_runtime",
        purpose="Prompt progress, routing availability, fast previews, understanding, and index fast paths.",
        tests=(
            "test_prompt_progress_service.py",
            "test_prompt_dispatch_availability.py",
            "test_prompt_execution_context_fast_preview.py",
            "test_prompt_understanding_matrix.py",
            "test_project_index_engine_fast_path.py",
        ),
    ),
    DemoLane(
        name="api_runtime",
        purpose="Headless parity, modular providers, model resolution, and API feature discovery.",
        tests=(
            "test_headless_api.py",
            "test_modular_provider_contracts.py",
            "test_ollama_model_resolution.py",
            "test_prompt_smoke_ollama.py",
        ),
    ),
    DemoLane(
        name="live_model",
        purpose="Real local-model synthesis with first-token and total inference timing.",
        tests=(),
        live=True,
    ),
)


def _lane_map() -> dict[str, DemoLane]:
    return {lane.name: lane for lane in LANES}


def _selected_lanes(names: list[str], include_live: bool) -> list[DemoLane]:
    lanes = _lane_map()
    if not names or "all" in names:
        selected = [lane for lane in LANES if not lane.live]
    else:
        unknown = sorted(set(names) - set(lanes))
        if unknown:
            raise ValueError(f"Unknown demo lane(s): {', '.join(unknown)}")
        selected = [lanes[name] for name in names]
    if include_live and not any(lane.name == "live_model" for lane in selected):
        selected.append(lanes["live_model"])
    return selected


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["QT_QPA_PLATFORM"] = environment.get("QT_QPA_PLATFORM", "offscreen")
    environment["PYTEST_ADDOPTS"] = "-p no:cacheprovider"
    python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(TOOLS_ROOT)
        if not python_path
        else os.pathsep.join((str(TOOLS_ROOT), python_path))
    )
    return environment


def _run_lane(lane: DemoLane, run_root: Path) -> dict[str, object]:
    missing = [name for name in lane.tests if not (TEST_ROOT / name).is_file()]
    if missing:
        return {
            "name": lane.name,
            "purpose": lane.purpose,
            "status": "failed",
            "duration_seconds": 0.0,
            "return_code": 2,
            "error": f"Missing test files: {', '.join(missing)}",
            "tests": list(lane.tests),
        }

    lane_root = run_root / lane.name
    lane_root.mkdir(parents=True, exist_ok=True)
    if lane.live:
        command = [
            sys.executable,
            str(TOOLS_ROOT / "tech_connector" / "scripts" / "prompt_smoke_ollama.py"),
            "--require-synthesis",
            "--model",
            "qwen2.5-coder:7b",
            "--project-root",
            str(TOOLS_ROOT),
            "--active-path",
            str(TOOLS_ROOT / "custom_qt" / "custom_widgets.py"),
            "--summary-json",
            str(lane_root / "summary.json"),
            (
                "Write complete runnable PySide6 code for a QWidget containing "
                "a QPushButton and QLabel. Connect the button's clicked signal "
                "to a create_material method. The method must have a real body "
                "that updates the label. Include imports, the class, construction "
                "time signal hookup, and an if __name__ == '__main__' launch block."
            ),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--durations=15",
            "--basetemp",
            str(lane_root / "pytest"),
            *(str(TEST_ROOT / name) for name in lane.tests),
        ]
    print(f"\n[{lane.name}] {lane.purpose}", flush=True)
    check_count = 1 if lane.live else len(lane.tests)
    print(f"[{lane.name}] checks={check_count}", flush=True)
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=TOOLS_ROOT,
        env=_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    duration = perf_counter() - started
    if completed.stdout:
        print(completed.stdout.rstrip(), flush=True)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr, flush=True)
    status = "passed" if completed.returncode == 0 else "failed"
    print(f"[{lane.name}] {status} in {duration:.2f}s", flush=True)
    return {
        "name": lane.name,
        "purpose": lane.purpose,
        "status": status,
        "duration_seconds": round(duration, 3),
        "return_code": completed.returncode,
        "tests": list(lane.tests),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        help="Lane to run; repeat for multiple lanes. Default: all non-live lanes.",
    )
    parser.add_argument(
        "--include-live",
        action="store_true",
        help="Also run the real local-model prompt lane.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available lanes without running them.",
    )
    args = parser.parse_args()

    if args.list:
        for lane in LANES:
            suffix = " (live)" if lane.live else ""
            print(f"{lane.name}{suffix}: {lane.purpose}")
        return 0

    try:
        selected = _selected_lanes(args.lane, args.include_live)
    except ValueError as exc:
        parser.error(str(exc))

    run_root = Path(tempfile.mkdtemp(prefix="tech_connector_demo_readiness_"))
    print(f"Demo artifacts: {run_root}", flush=True)
    started = perf_counter()
    results = [_run_lane(lane, run_root) for lane in selected]
    duration = perf_counter() - started
    status = "passed" if all(row["status"] == "passed" for row in results) else "failed"
    report = {
        "schema": "tech_connector.live_demo_readiness.v1",
        "status": status,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3),
        "python": sys.executable,
        "tools_root": str(TOOLS_ROOT),
        "lanes": results,
    }
    report_path = run_root / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nDemo readiness summary", flush=True)
    for row in results:
        print(
            f"- {row['name']}: {row['status']} in {row['duration_seconds']:.2f}s",
            flush=True,
        )
    print(f"Overall: {status} in {duration:.2f}s", flush=True)
    print(f"Report: {report_path}", flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
