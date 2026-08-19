"""Agent adapters for the isolated code-agent benchmark."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from .models import AgentRun, BenchmarkCase


_CODEX_INFRASTRUCTURE_MARKERS = (
    "code mode is unavailable",
    "failed to spawn code-mode host",
    "code-mode host executable was not found",
    "codex-code-mode-host.exe was not found",
)


def _codex_infrastructure_errors(
    events: list[dict[str, Any]],
    stderr_text: str,
) -> list[str]:
    """Return adapter failures that make a Codex attempt ineligible.

    :param events: Parsed Codex JSONL events.
    :param stderr_text: Raw Codex standard-error text.
    :return: Unique infrastructure failure messages.
    """

    candidates = [stderr_text]
    for event in events:
        if str(event.get("type") or "") == "error":
            candidates.append(json.dumps(event, sort_keys=True, default=str))
        item = event.get("item")
        if isinstance(item, dict) and str(item.get("type") or "") == "error":
            candidates.append(json.dumps(item, sort_keys=True, default=str))
    failures: list[str] = []
    for candidate in candidates:
        normalized = candidate.casefold()
        if not any(marker in normalized for marker in _CODEX_INFRASTRUCTURE_MARKERS):
            continue
        message = " ".join(candidate.split())[-2000:]
        if message and message not in failures:
            failures.append(message)
    return failures


def _hidden_process_options() -> dict[str, Any]:
    """Return platform-specific subprocess options for background attempts.

        :return: keyword arguments accepted by subprocess.Popen
    """

    if os.name != "nt":
        return {}
    return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}


def _run_streamed_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> tuple[int | None, str, str, float, float | None, bool]:
    """Run a process while preserving flushed output and timeout evidence.

    :param command: Executable and argument sequence.
    :param cwd: Isolated process working directory.
    :param environment: Complete child-process environment.
    :param stdout_path: Live standard-output log destination.
    :param stderr_path: Live standard-error log destination.
    :param timeout_seconds: Whole-process timeout.
    :return: Exit code, output, errors, wall time, first output time, timeout flag.
    """

    started = time.perf_counter()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    first_output: float | None = None
    first_output_lock = threading.Lock()
    process: subprocess.Popen[str] | None = None
    timed_out = False

    def consume(
        stream: Any,
        destination: Path,
        lines: list[str],
        *,
        marks_first_output: bool,
    ) -> None:
        nonlocal first_output
        with destination.open("w", encoding="utf-8") as handle:
            if stream is None:
                return
            for line in stream:
                if marks_first_output:
                    with first_output_lock:
                        if first_output is None:
                            first_output = time.perf_counter() - started
                lines.append(line)
                handle.write(line)
                handle.flush()

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_hidden_process_options(),
        )
        stdout_thread = threading.Thread(
            target=consume,
            args=(process.stdout, stdout_path, stdout_lines),
            kwargs={"marks_first_output": True},
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=consume,
            args=(process.stderr, stderr_path, stderr_lines),
            kwargs={"marks_first_output": False},
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        deadline = started + timeout_seconds
        while process.poll() is None:
            if time.perf_counter() >= deadline:
                process.kill()
                timed_out = True
                break
            time.sleep(0.05)
        process.wait(timeout=10)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None and process.poll() is None:
            process.kill()
        timed_out = timed_out or isinstance(exc, subprocess.TimeoutExpired)
        message = f"{type(exc).__name__}: {exc}\n"
        stderr_lines.append(message)
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write(message)
    return (
        process.returncode if process is not None else None,
        "".join(stdout_lines),
        "".join(stderr_lines),
        time.perf_counter() - started,
        first_output,
        timed_out,
    )


def run_tech_connector(
    case: BenchmarkCase,
    workspace: Path,
    attempt_dir: Path,
    *,
    model: str,
    repetition: int,
    timeout_seconds: int,
    llm_timeout_seconds: int,
) -> AgentRun:
    """Run Tech Connector's production project-edit workflow in a subprocess.

    :param case: Coding case to execute.
    :param workspace: Disposable source workspace.
    :param attempt_dir: Directory for adapter logs and metadata.
    :param model: Tech Connector model route.
    :param repetition: One-based repetition number.
    :param timeout_seconds: Whole-attempt timeout.
    :param llm_timeout_seconds: Per-model-call timeout.
    :return: Captured agent attempt.
    """

    request_path = attempt_dir / "tech_request.json"
    result_path = attempt_dir / "tech_result.json"
    request_path.write_text(
        json.dumps(
            {
                "workspace": str(workspace),
                "prompt": case.prompt,
                "model": model,
                "llm_timeout": llm_timeout_seconds,
                "max_attempts": 5,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    repository_root = str(Path(__file__).resolve().parents[3])
    current_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (repository_root, current_python_path) if item
    )
    command = [
        sys.executable,
        "-u",
        "-m",
        "tech_connector.benchmarks.code_agent.tech_worker",
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    return_code, stdout, stderr, wall, first_output, timed_out = (
        _run_streamed_process(
            command,
            cwd=workspace,
            environment=environment,
            stdout_path=attempt_dir / "tech_stdout.log",
            stderr_path=attempt_dir / "tech_stderr.log",
            timeout_seconds=timeout_seconds,
        )
    )
    payload = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.exists()
        else {}
    )
    error = str(payload.get("error") or "")
    if timed_out:
        error = f"Attempt exceeded {timeout_seconds} seconds. " + error
    elif return_code and not error:
        error = (stderr or stdout)[-2000:]
    status = "timeout" if timed_out else str(payload.get("status") or "process_failed")
    eligible = status in {"ok", "preview_ok"} and return_code == 0
    return AgentRun(
        agent="tech_connector",
        model=str(payload.get("model") or model),
        case_id=case.case_id,
        repetition=repetition,
        status=status,
        wall_seconds=round(wall, 6),
        exit_code=return_code,
        timed_out=timed_out,
        eligible=eligible,
        ineligibility_reason="" if eligible else error or f"Adapter status: {status}",
        error=error,
        input_tokens=int(payload.get("input_tokens") or 0),
        output_tokens=int(payload.get("output_tokens") or 0),
        time_to_first_output_seconds=(
            round(first_output, 6) if first_output is not None else None
        ),
        file_change_events=len(payload.get("applied_paths") or []),
        metadata={
            **payload,
            "partial_output_preserved": True,
        },
    )


def _codex_command(
    model: str,
    prompt: str,
    executable: str = "",
) -> list[str]:
    """Build the documented non-interactive Codex command.

    :param model: Optional explicit Codex model.
    :param prompt: Exact benchmark task prompt.
    :param executable: Optional explicit Codex executable path.
    :return: Command arguments.
    """

    executable = (
        executable
        or os.environ.get("TECH_CONNECTOR_CODEX_EXECUTABLE", "")
        or shutil.which("codex")
        or "codex"
    )
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--json",
        "--approve-for-me",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
    ]
    if model and model != "default":
        command.extend(["--model", model])
    command.append(prompt)
    return command


def run_codex(
    case: BenchmarkCase,
    workspace: Path,
    attempt_dir: Path,
    *,
    model: str,
    repetition: int,
    timeout_seconds: int,
    executable: str = "",
) -> AgentRun:
    """Run Codex non-interactively and parse its JSONL event stream.

    :param case: Coding case to execute.
    :param workspace: Disposable source workspace.
    :param attempt_dir: Directory for adapter logs and metadata.
    :param model: Optional explicit Codex model.
    :param repetition: One-based repetition number.
    :param timeout_seconds: Whole-attempt timeout.
    :param executable: Optional explicit Codex executable path.
    :return: Captured agent attempt. The documented approve-for-me mode supplies
        its own workspace-write sandbox and cannot be combined with --sandbox.
    """

    command = _codex_command(model, case.prompt, executable)
    environment = dict(os.environ)
    environment["NO_COLOR"] = "1"
    events: list[dict[str, Any]] = []
    return_code, stdout_text, stderr_text, wall, first_output, timed_out = (
        _run_streamed_process(
            command,
            cwd=workspace,
            environment=environment,
            stdout_path=attempt_dir / "codex_events.jsonl",
            stderr_path=attempt_dir / "codex_stderr.log",
            timeout_seconds=timeout_seconds,
        )
    )
    for line in stdout_text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    usage: dict[str, Any] = {}
    final_message = ""
    tool_calls = 0
    command_calls = 0
    file_events = 0
    reported_model = model
    for event in events:
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = dict(event["usage"])
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type") or "")
            if event.get("type") == "item.completed" and item_type == "agent_message":
                final_message = str(item.get("text") or final_message)
            if item_type in {"command_execution", "mcp_tool_call", "web_search"}:
                tool_calls += 1
            if item_type == "command_execution":
                command_calls += 1
            if item_type == "file_change":
                file_events += 1
        if isinstance(event.get("model"), str):
            reported_model = event["model"]
    infrastructure_errors = _codex_infrastructure_errors(events, stderr_text)
    if timed_out:
        status = "timeout"
    elif infrastructure_errors:
        status = "infrastructure_failed"
    elif return_code == 0:
        status = "ok"
    else:
        status = "process_failed"
    eligible = status == "ok"
    error = "\n".join(infrastructure_errors)
    if not error and return_code != 0:
        error = stderr_text[-2000:]
    return AgentRun(
        agent="codex",
        model=reported_model or "default",
        case_id=case.case_id,
        repetition=repetition,
        status=status,
        wall_seconds=round(wall, 6),
        exit_code=return_code,
        timed_out=timed_out,
        eligible=eligible,
        ineligibility_reason="" if eligible else error or f"Adapter status: {status}",
        error=error,
        final_message=final_message,
        input_tokens=int(usage.get("input_tokens") or 0),
        cached_input_tokens=int(usage.get("cached_input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        reasoning_output_tokens=int(usage.get("reasoning_output_tokens") or 0),
        time_to_first_output_seconds=(
            round(first_output, 6) if first_output is not None else None
        ),
        tool_calls=tool_calls,
        command_calls=command_calls,
        file_change_events=file_events,
        metadata={
            "event_count": len(events),
            "command": command[:-1],
            "infrastructure_errors": infrastructure_errors,
        },
    )
