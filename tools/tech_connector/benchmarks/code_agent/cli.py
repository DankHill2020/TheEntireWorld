"""Run reproducible Tech Connector versus Codex coding benchmarks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from .cases import benchmark_cases
from .models import BenchmarkReport
from .reporting import aggregate_runs, write_report
from .runners import run_codex, run_tech_connector
from .scoring import materialize_case, score_attempt


BENCHMARK_VERSION = "1.3.0"


def _slug(value: str) -> str:
    """Convert an identifier into a filesystem-safe label.

    :param value: Raw model or agent identifier.
    :return: Filesystem-safe label.
    """

    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "default"


def _codex_version(executable_override: str = "") -> str:
    """Return the installed Codex version without failing the benchmark.

    :param executable_override: Optional explicit executable path.
    :return: Version output or an availability explanation.
    """

    executable = (
        executable_override
        or os.environ.get("TECH_CONNECTOR_CODEX_EXECUTABLE", "")
        or shutil.which("codex")
    )
    if not executable:
        return "not found"
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (completed.stdout or completed.stderr).strip() or f"exit {completed.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"


def _selected_cases(case_ids: list[str]) -> list[Any]:
    """Resolve requested cases and reject unknown identifiers.

    :param case_ids: Optional requested case identifiers.
    :return: Selected benchmark cases.
    """

    available = {case.case_id: case for case in benchmark_cases()}
    if not case_ids:
        return list(available.values())
    unknown = sorted(set(case_ids) - set(available))
    if unknown:
        raise ValueError(
            f"Unknown cases: {', '.join(unknown)}. Available: {', '.join(available)}"
        )
    return [available[case_id] for case_id in case_ids]


def _attempt_root(
    output_dir: Path,
    case_id: str,
    agent: str,
    model: str,
    repetition: int,
) -> Path:
    """Return the deterministic artifact directory for one attempt.

    :param output_dir: Benchmark output root.
    :param case_id: Case identifier.
    :param agent: Agent adapter name.
    :param model: Model identifier.
    :param repetition: One-based repetition number.
    :return: Attempt artifact path.
    """

    return output_dir / "attempts" / case_id / agent / _slug(model) / f"run_{repetition:02d}"


def run_benchmark(args: argparse.Namespace) -> BenchmarkReport:
    """Execute the requested benchmark matrix.

    :param args: Parsed command-line arguments.
    :return: Completed report.
    """

    started = datetime.now(timezone.utc)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = _selected_cases(args.case)
    agents = [args.agent] if args.agent != "both" else ["tech", "codex"]
    codex_models = args.codex_model or ["default"]
    records: list[dict[str, Any]] = []

    for case in cases:
        for agent in agents:
            models = [args.tech_model] if agent == "tech" else codex_models
            for model in models:
                for repetition in range(1, args.repeat + 1):
                    attempt_dir = _attempt_root(
                        output_dir, case.case_id, agent, model, repetition
                    )
                    attempt_dir.mkdir(parents=True, exist_ok=False)
                    workspace = attempt_dir / "workspace"
                    before = materialize_case(case, workspace)
                    print(
                        f"[{case.case_id}] {agent}:{model} run {repetition}/{args.repeat}",
                        flush=True,
                    )
                    if agent == "tech":
                        run = run_tech_connector(
                            case,
                            workspace,
                            attempt_dir,
                            model=model,
                            repetition=repetition,
                            timeout_seconds=args.tech_timeout,
                            llm_timeout_seconds=args.llm_timeout,
                        )
                    else:
                        run = run_codex(
                            case,
                            workspace,
                            attempt_dir,
                            model=model,
                            repetition=repetition,
                            timeout_seconds=args.codex_timeout,
                            executable=args.codex_executable,
                        )
                    score = score_attempt(case, run, workspace, attempt_dir, before)
                    record = {**run.to_dict(), "score": score.to_dict()}
                    records.append(record)
                    (attempt_dir / "attempt.json").write_text(
                        json.dumps(record, indent=2, default=str), encoding="utf-8"
                    )
                    print(
                        f"  status={run.status} score={score.total_points:.1f} "
                        f"assertions={score.assertions_passed}/{score.assertions_total} "
                        f"time={run.wall_seconds:.2f}s",
                        flush=True,
                    )
                    if not args.keep_workspaces:
                        shutil.rmtree(workspace, ignore_errors=True)

    finished = datetime.now(timezone.utc)
    return BenchmarkReport(
        benchmark_version=BENCHMARK_VERSION,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        environment={
            "platform": platform.platform(),
            "python": sys.version,
            "python_executable": sys.executable,
            "codex_version": _codex_version(args.codex_executable),
            "codex_executable": (
                args.codex_executable
                or os.environ.get("TECH_CONNECTOR_CODEX_EXECUTABLE", "")
                or shutil.which("codex")
                or ""
            ),
            "openai_api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
            "codex_api_key_present": bool(os.environ.get("CODEX_API_KEY")),
            "case_ids": [case.case_id for case in cases],
            "repetitions": args.repeat,
        },
        runs=records,
        summary=aggregate_runs(records),
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the benchmark command-line parser.

    :return: Configured argument parser.
    """

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = (
        Path(tempfile.gettempdir())
        / "tech_connector_code_agent_benchmarks"
        / timestamp
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("tech", "codex", "both"), default="both")
    parser.add_argument("--case", action="append", default=[], help="Case ID; repeat to select multiple cases.")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--tech-model", default="ollama:qwen2.5-coder:7b")
    parser.add_argument("--codex-model", action="append", default=[], help="Codex model; repeat for a model matrix. Default uses the CLI default.")
    parser.add_argument(
        "--codex-executable",
        default="",
        help=(
            "Explicit Codex CLI path. Also configurable with "
            "TECH_CONNECTOR_CODEX_EXECUTABLE."
        ),
    )
    parser.add_argument("--tech-timeout", type=int, default=1200)
    parser.add_argument("--codex-timeout", type=int, default=900)
    parser.add_argument("--llm-timeout", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--keep-workspaces", action="store_true")
    return parser


def main() -> int:
    """Run the benchmark CLI and print report locations.

    :return: Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least one")
    try:
        report = run_benchmark(args)
    except ValueError as exc:
        parser.error(str(exc))
    json_path, markdown_path = write_report(report, args.output_dir.resolve())
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
