"""Isolated worker for one Tech Connector code-agent attempt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any


def _safe_change_path(workspace: Path, raw_path: str) -> Path:
    """Resolve a generated change path without permitting workspace escape.

    :param workspace: Isolated benchmark workspace.
    :param raw_path: Generated absolute or relative path.
    :return: Resolved path below the workspace.
    """

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    resolved.relative_to(workspace)
    return resolved


def _sum_inference_metrics(value: Any) -> dict[str, int]:
    """Recursively sum token telemetry embedded in workflow timings.

    :param value: Arbitrarily nested workflow result data.
    :return: Summed input and output token counts.
    """

    totals = {"input_tokens": 0, "output_tokens": 0}
    seen: set[int] = set()

    def visit(item: Any) -> None:
        if isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in seen:
                return
            seen.add(identity)
        if isinstance(item, dict):
            inference = item.get("inference")
            if isinstance(inference, dict):
                totals["input_tokens"] += int(inference.get("input_tokens") or 0)
                totals["output_tokens"] += int(inference.get("output_tokens") or 0)
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return totals


def run_worker(request_path: Path, result_path: Path) -> int:
    """Run Tech Connector and write a machine-readable attempt result.

    :param request_path: JSON request containing workspace, prompt, and model.
    :param result_path: Destination JSON result path.
    :return: Process exit code.
    """

    request = json.loads(request_path.read_text(encoding="utf-8"))
    workspace = Path(request["workspace"]).resolve()
    prompt = str(request["prompt"])
    model = str(request["model"])
    timeout = int(request.get("llm_timeout") or 300)
    max_attempts = int(request.get("max_attempts") or 5)
    os.chdir(workspace)

    from tech_connector.services.project_edit_workflow_service import (
        run_multi_file_project_edit_workflow,
    )
    from tech_connector.services.settings_service import load_settings

    settings = dict(load_settings())
    if model.startswith("ollama:"):
        settings["model_source_mode"] = "local_only"
        selected_model = model.removeprefix("ollama:")
    else:
        selected_model = model
    settings["model"] = selected_model
    settings["cloud_provider_model"] = selected_model
    settings["openai_store_responses"] = False

    started = time.perf_counter()
    workflows = []

    def report_status(message: str) -> None:
        """Stream one user-visible workflow status into the attempt log.

        :param message: workflow progress message
        :return: None
        """

        print(f"Workflow status: {message}", flush=True)

    try:
        workflow = run_multi_file_project_edit_workflow(
            prompt,
            project_root=str(workspace),
            selected_model=selected_model,
            settings=settings,
            timeout=timeout,
            dry_run=True,
            max_attempts=max_attempts,
            original_prompt=prompt,
            status_callback=report_status,
        )
        workflows.append(workflow)
        if workflow.status == "plan_approval_required" and workflow.approval_id:
            workflow = run_multi_file_project_edit_workflow(
                prompt,
                project_root=str(workspace),
                selected_model=selected_model,
                settings=settings,
                timeout=timeout,
                dry_run=True,
                max_attempts=max_attempts,
                approved_plan_id=workflow.approval_id,
                original_prompt=prompt,
                status_callback=report_status,
            )
            workflows.append(workflow)

        applied_paths: list[str] = []
        rejected_paths: list[str] = []
        changes = list(workflow.preview.changes if workflow.preview else [])
        for change in changes:
            raw_path = str(change.get("path") or "")
            new_content = change.get("new_content")
            try:
                target = _safe_change_path(workspace, raw_path)
            except (OSError, ValueError):
                rejected_paths.append(raw_path)
                continue
            if not isinstance(new_content, str):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
            applied_paths.append(target.relative_to(workspace).as_posix())

        all_timings = [timing for item in workflows for timing in item.timings]
        tokens = _sum_inference_metrics(all_timings)
        payload = {
            "status": workflow.status,
            "ok": bool(workflow.ok),
            "model": selected_model,
            "wall_seconds": round(time.perf_counter() - started, 6),
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "applied_paths": applied_paths,
            "rejected_paths": rejected_paths,
            "errors": list(workflow.errors),
            "approval_round_trips": max(0, len(workflows) - 1),
            "workflow_statuses": [item.status for item in workflows],
            "timings": all_timings,
            "implementation_plan": workflow.implementation_plan,
        }
        result_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return 0 if applied_paths else 2
    except Exception as exc:
        payload = {
            "status": "worker_error",
            "ok": False,
            "model": selected_model,
            "wall_seconds": round(time.perf_counter() - started, 6),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1


def main() -> int:
    """Parse worker arguments and execute one attempt.

    :return: Process exit code.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    return run_worker(args.request.resolve(), args.result.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
