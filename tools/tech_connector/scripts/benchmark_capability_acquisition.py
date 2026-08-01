"""Benchmark one real capability-acquisition run without writing its patch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time
from typing import Any
from datetime import datetime, timezone


APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = next(candidate for candidate in (APP_ROOT, *APP_ROOT.parents) if candidate.name.lower() == "tools")
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.services.capability_acquisition_coordinator import AcquisitionJob
from tech_connector.services.capability_implementation_provider import ModelBackedCapabilityImplementationProvider
from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace
from tech_connector.models.constants import temp_output_path
from tech_connector.services.project_edit_agent_service import preview_project_edit_agent_response
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--project-root", default=str(TOOLS_ROOT))
    parser.add_argument(
        "--report",
        default=str(temp_output_path("capability_acquisition_benchmark.json", subdir="reports")),
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "prompt": args.prompt,
        "project_root": str(Path(args.project_root).resolve()),
        "safety": "capture_only_no_project_apply",
        "stages": [],
        "model_calls": [],
        "previews": [],
        "disposable_validations": [],
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def persist() -> None:
        report["elapsed_seconds_at_last_event"] = _elapsed(total_started)
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    total_started = time.perf_counter()
    started = time.perf_counter()
    decision = classify_prompt_route(args.prompt, project_roots=[args.project_root])
    route = decision.to_dict()
    report["route_timing_seconds"] = _elapsed(started)
    report["route"] = route
    persist()
    plan = dict(route.get("capability_gap_plan") or {})
    if route.get("operation_mode") != "acquire_then_resume" or not plan:
        report["error"] = "Prompt did not reach capability acquisition."
        report["total_seconds"] = _elapsed(total_started)
        persist()
        print(json.dumps(report, indent=2, default=str))
        return 2

    captured_preview: dict[str, Any] = {}

    def model_query(stage: Any, model: str, prompt: str | None = None) -> str:
        started_call = time.perf_counter()
        row = {
            "stage": stage.key,
            "profile": stage.coder_preference,
            "model": model,
            "started_at": _now(),
            "num_ctx": stage.num_ctx,
            "num_predict": stage.num_predict,
            "timeout": stage.timeout,
            "response_format": stage.response_format,
            "system_prompt": stage.system_prompt,
            "user_prompt": prompt if prompt is not None else stage.user_prompt,
            "status": "running",
        }
        report["model_calls"].append(row)
        persist()
        try:
            from tech_connector.knowledge.search import query_ollama_text

            output = query_ollama_text(
                model=model,
                system_prompt=stage.system_prompt,
                user_prompt=prompt if prompt is not None else stage.user_prompt,
                num_ctx=stage.num_ctx,
                num_predict=stage.num_predict,
                timeout=stage.timeout,
                prefer_coder=stage.prefer_coder,
                coder_preference=stage.coder_preference,
                think=False,
                response_format=stage.response_format or None,
                temperature=0.0,
                telemetry_callback=lambda data: row.update({"ollama_telemetry": data}),
            )
        except Exception as exc:
            row.update({"seconds": _elapsed(started_call), "status": "failed", "error": repr(exc), "ended_at": _now()})
            persist()
            raise
        row.update({"seconds": _elapsed(started_call), "status": "completed", "output": output, "ended_at": _now()})
        persist()
        return output

    def previewer(output: str, **kwargs: Any) -> Any:
        started_preview = time.perf_counter()
        preview = preview_project_edit_agent_response(output, **kwargs)
        captured_preview["value"] = preview
        report["previews"].append({
            "seconds": _elapsed(started_preview),
            "ok": bool(preview.ok),
            "errors": list(preview.errors or []),
            "changes": list(preview.changes or []),
        })
        persist()
        return preview

    def temp_validator(**kwargs: Any) -> dict[str, Any]:
        started_validation = time.perf_counter()
        result = validate_patch_in_temp_workspace(**kwargs)
        report["disposable_validations"].append({
            "seconds": _elapsed(started_validation),
            **result,
        })
        persist()
        return result

    def capture_apply(_output: str, **_kwargs: Any) -> Any:
        preview = captured_preview.get("value")
        changes = list(getattr(preview, "changes", []) or [])
        report["captured_apply"] = {
            "seconds": 0.0,
            "written": False,
            "change_count": len(changes),
            "changes": changes,
        }
        persist()
        return SimpleNamespace(ok=True, errors=[], changes=changes, change_session_path="")

    provider = ModelBackedCapabilityImplementationProvider(
        args.project_root,
        model_query=model_query,
        previewer=previewer,
        temp_validator=temp_validator,
        applier=capture_apply,
    )
    job = AcquisitionJob(plan=plan, original_request=args.prompt)
    for step in list(plan.get("steps") or []):
        if str(step.get("step_id") or "") == "validate_dcc_adapter":
            break
        started_stage = time.perf_counter()
        try:
            result = provider.run_stage(step, job)
        except Exception as exc:
            result = {"ok": False, "error": repr(exc), "exception_type": type(exc).__name__}
        report["stages"].append({
            "step_id": step.get("step_id"),
            "objective": step.get("objective"),
            "seconds": _elapsed(started_stage),
            "result": result,
        })
        edit_plan = provider._state.get("edit_plan")
        if edit_plan is not None:
            report["grounded_edit_plan"] = {
                "prompt": getattr(edit_plan, "prompt", ""),
                "active_path": getattr(edit_plan, "active_path", ""),
                "discovery": getattr(edit_plan, "discovery", {}),
                "discovery_context": getattr(edit_plan, "discovery_context", ""),
                "model_prompt": getattr(edit_plan, "model_prompt", ""),
                "capability_source_evidence": getattr(edit_plan, "capability_source_evidence", ""),
            }
        persist()
        if not result.get("ok"):
            break

    report["total_seconds"] = _elapsed(total_started)
    persist()
    print(json.dumps({
        "report": str(report_path),
        "route": report["route"],
        "route_timing_seconds": report["route_timing_seconds"],
        "stages": [{key: row.get(key) for key in ("step_id", "seconds")} for row in report["stages"]],
        "model_calls": [
            {key: row.get(key) for key in ("stage", "profile", "model", "seconds")}
            for row in report["model_calls"]
        ],
        "previews": [
            {key: row.get(key) for key in ("seconds", "ok", "errors")}
            for row in report["previews"]
        ],
        "disposable_validations": [
            {key: row.get(key) for key in ("seconds", "ok", "errors", "commands")}
            for row in report["disposable_validations"]
        ],
        "total_seconds": report["total_seconds"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
