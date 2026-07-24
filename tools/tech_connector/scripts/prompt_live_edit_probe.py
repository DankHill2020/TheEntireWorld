"""Run one Tech Connector prompt through the deterministic engine with optional approval.

This is a temporary developer probe for live Maya/Unreal validation. It uses the
same RequestEngine dispatch path as the app, but can set the approved flag so
approved bridge mutations can be tested without clicking the UI approval button.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = next(
    candidate for candidate in (APP_ROOT, *APP_ROOT.parents) if candidate.name.lower() == "tools"
)
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


def _shorten(value: Any, limit: int = 3000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"\n... <truncated {len(value) - limit} chars>"
    if isinstance(value, list):
        return [_shorten(item, limit) for item in value[:20]]
    if isinstance(value, dict):
        return {key: _shorten(item, limit) for key, item in value.items()}
    return value


def _route_summary(route: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "route",
        "intent_category",
        "host",
        "target_identifier",
        "callable_name",
        "operation_mode",
        "mutation_scope",
        "risk_level",
        "requires_confirmation",
        "approved",
        "confidence",
        "keyword_args",
        "missing_info",
    )
    return {key: route.get(key) for key in keys if key in route}


def _result_summary(result: Any) -> dict[str, Any]:
    metadata = dict(getattr(result, "metadata", {}) or {})
    dispatch = metadata.get("dispatch_result") or metadata.get("dcc_dispatch_result") or {}
    if hasattr(dispatch, "to_dict"):
        dispatch = dispatch.to_dict()
    summary = {
        "action": getattr(result, "action", ""),
        "label": getattr(result, "label", ""),
        "result_type": getattr(result, "result_type", ""),
        "text": _shorten(getattr(result, "text", ""), 3000),
    }
    if isinstance(dispatch, dict) and dispatch:
        structured = dict(dispatch.get("structured_data") or {})
        request = structured.get("request")
        if isinstance(request, dict):
            structured["request"] = {
                "execution_environment": request.get("execution_environment"),
                "operation_mode": request.get("operation_mode"),
                "target_type": request.get("target_type"),
                "target_identifier": request.get("target_identifier"),
                "callable_name": request.get("callable_name"),
                "keyword_args": request.get("keyword_args"),
                "mutation_scope": request.get("mutation_scope"),
                "risk_level": request.get("risk_level"),
                "approved": request.get("approved"),
            }
        patch_result = structured.get("patch_result")
        if isinstance(patch_result, dict):
            apply_result = patch_result.get("apply_result") or {}
            validation = dict(patch_result.get("validation") or {})
            if "graph_snapshot_after" in validation:
                validation["graph_snapshot_after"] = {"summary": "omitted from compact probe output"}
            structured["patch_result"] = {
                "ok": patch_result.get("ok"),
                "mode": patch_result.get("mode"),
                "applied": patch_result.get("applied"),
                "errors": patch_result.get("errors"),
                "warnings": patch_result.get("warnings"),
                "validation": validation,
                "created_nodes": apply_result.get("created_nodes") if isinstance(apply_result, dict) else None,
                "applied_operations": apply_result.get("applied_operations") if isinstance(apply_result, dict) else None,
            }
        preview = structured.get("preview")
        if isinstance(preview, dict):
            structured["preview"] = {
                "summary": preview.get("summary"),
                "operation_count": preview.get("operation_count"),
                "node_additions": preview.get("node_additions"),
                "pin_links_to_create": preview.get("pin_links_to_create"),
                "risk_level": preview.get("risk_level"),
                "visible_state": preview.get("visible_state"),
                "next_state": preview.get("next_state"),
            }
        confirmation_request = dispatch.get("confirmation_request")
        if isinstance(confirmation_request, dict) and confirmation_request:
            confirmation_request = {
                "operation": confirmation_request.get("operation"),
                "target_asset": confirmation_request.get("target_asset"),
                "target_graph": confirmation_request.get("target_graph"),
                "risk_level": confirmation_request.get("risk_level"),
                "mutation_scope": confirmation_request.get("mutation_scope"),
                "preview": {
                    "summary": (confirmation_request.get("preview") or {}).get("summary")
                    if isinstance(confirmation_request.get("preview"), dict)
                    else "",
                    "operation_count": (confirmation_request.get("preview") or {}).get("operation_count")
                    if isinstance(confirmation_request.get("preview"), dict)
                    else 0,
                },
            }
        if "graph_snapshot" in structured:
            snapshot = structured.get("graph_snapshot")
            structured["graph_snapshot"] = {
                "type": type(snapshot).__name__,
                "summary": "omitted from compact probe output",
            }
        for key in ("graph_snapshot_before", "graph_snapshot_after"):
            if key in structured:
                structured[key] = {"summary": "omitted from compact probe output"}
        for key in ("graph_understanding", "semantic_graph_understanding"):
            if key in structured:
                structured[key] = {"summary": "omitted from compact probe output"}
        rewrite_plan = structured.get("rewrite_plan")
        if isinstance(rewrite_plan, dict):
            candidate = rewrite_plan.get("graph_patch_candidate") or {}
            operations = list(candidate.get("operations") or [])
            structured["rewrite_plan"] = {
                "ok": rewrite_plan.get("ok"),
                "plan_kind": rewrite_plan.get("plan_kind"),
                "target_asset": rewrite_plan.get("target_asset"),
                "target_graph": rewrite_plan.get("target_graph"),
                "graph_exists": rewrite_plan.get("graph_exists"),
                "operation_count": len(operations),
                "operations": operations[:3],
                "warnings": rewrite_plan.get("warnings"),
            }
        summary["dispatch_result"] = _shorten(
            {
                "status": dispatch.get("status"),
                "operation_mode": dispatch.get("operation_mode"),
                "user_message": dispatch.get("user_message"),
                "rendered_output": dispatch.get("rendered_output"),
                "structured_data": structured,
                "affected_targets": dispatch.get("affected_targets"),
                "mutation_summary": dispatch.get("mutation_summary"),
                "warnings": dispatch.get("warnings"),
                "missing_slots": dispatch.get("missing_slots"),
                "confirmation_request": confirmation_request or {},
                "raw_result": {"summary": "omitted from compact probe output"} if dispatch.get("raw_result") else {},
            },
            3000,
        )
    return summary


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": event.get("stage"),
        "message": event.get("message"),
        "detail": _shorten(event.get("detail") or "", 500),
        "current": event.get("current"),
        "total": event.get("total"),
    }


def _activity_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": event.get("kind"),
        "title": event.get("title"),
        "detail": _shorten(event.get("detail") or "", 500),
        "status": event.get("status"),
        "path": event.get("path"),
        "line": event.get("line"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--project-root", default=str(TOOLS_ROOT))
    parser.add_argument("--active-path", default="")
    parser.add_argument("--model", default="qwen2.5-coder:14b")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    route = classify_prompt_route(
        args.prompt,
        project_roots=[args.project_root],
        active_path=args.active_path or None,
    ).to_dict()
    if args.approve:
        route["approved"] = True
        route["confirmation_accepted"] = True
        route["requires_confirmation"] = False

    progress_rows: list[dict] = []
    activity_rows: list[dict] = []

    started = time.perf_counter()
    context = RequestContext(
        text=args.prompt,
        active_tab="Probe",
        current_file_path=args.active_path,
        project_roots=(args.project_root,),
        model=args.model,
        index_state="Index ready",
        extras={"prompt_route_decision": route},
    )
    result = RequestEngine(
        progress=lambda event: progress_rows.append(event.__dict__),
        activity=lambda event: activity_rows.append(event.__dict__),
    ).process(context)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    if args.full:
        payload = {
            "prompt": args.prompt,
            "approved": bool(args.approve),
            "elapsed_ms": elapsed_ms,
            "route": route,
            "result": {
                "action": result.action,
                "label": result.label,
                "text": result.text,
                "result_type": result.result_type,
                "metadata": result.metadata,
            },
            "progress": progress_rows,
            "activity": activity_rows,
        }
    else:
        payload = {
            "prompt": args.prompt,
            "approved": bool(args.approve),
            "elapsed_ms": elapsed_ms,
            "route": _route_summary(route),
            "result": _result_summary(result),
            "progress_tail": [_event_summary(event) for event in progress_rows[-8:]],
            "activity_tail": [_activity_summary(event) for event in activity_rows[-8:]],
        }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
