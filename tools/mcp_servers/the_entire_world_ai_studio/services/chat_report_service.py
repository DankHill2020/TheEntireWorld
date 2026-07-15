"""Friendly chat reports for deterministic Tech Connector operations."""

from __future__ import annotations

import difflib
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote


def simple_chat_enabled(settings: dict[str, Any] | None) -> bool:
    return bool((settings or {}).get("simple_chat_responses", False))


QUALITY_REPORT_SECTIONS = (
    "What happened",
    "User impact",
    "Evidence",
    "Likely cause",
    "Recovery / next action",
    "Validation",
)


def documentation_quality_checklist(*, include_error_reporting: bool = True) -> list[str]:
    """Return the shared quality bar for docs and error reports.

    This is intentionally compact and deterministic so UI code, docs tools, and
    job reporting can reuse the same standard instead of each inventing wording.
    """
    items = [
        "State the user-facing outcome first, not the internal implementation detail.",
        "Name exact files, assets, operations, jobs, or hosts whenever they are known.",
        "Separate verified facts from assumptions, unknowns, and recommendations.",
        "Include validation performed, validation unavailable, or validation still required.",
        "Include recovery, rollback, retry, or escalation options when something fails.",
        "Prefer concise sections that can be scanned quickly in the chat log or mobile job log.",
    ]
    if include_error_reporting:
        items.extend(
            [
                "For exceptions, preserve the traceback as evidence but do not make it the lead message.",
                "For user-actionable failures, include the smallest next step that can unblock the user.",
            ]
        )
    return items


def _clip_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 38)].rstrip() + f"\n... truncated {len(text) - limit} more character(s) ..."


def format_error_report(
    *,
    title: str = "Operation Failed",
    summary: str = "",
    exception: BaseException | None = None,
    operation: str = "",
    context: dict[str, Any] | None = None,
    evidence: list[str] | None = None,
    recovery: list[str] | None = None,
    validation: list[str] | None = None,
    include_traceback: bool = True,
) -> str:
    """Render a high-signal error report for chat, jobs, and workflow logs."""
    context = context or {}
    evidence = [str(item) for item in (evidence or []) if str(item).strip()]
    recovery = [str(item) for item in (recovery or []) if str(item).strip()]
    validation = [str(item) for item in (validation or []) if str(item).strip()]

    exc_type = type(exception).__name__ if exception else ""
    exc_message = str(exception or "").strip()
    likely_cause = exc_message or summary or "The operation did not provide a detailed failure reason."
    if exception:
        evidence.append(f"Exception type: `{exc_type}`")
        if exc_message:
            evidence.append(f"Exception message: {exc_message}")

    if not recovery:
        recovery = [
            "Retry after checking the active project/tool context.",
            "If this repeats, capture this report and the last action you attempted.",
        ]
    if not validation:
        validation = [
            "No successful mutation should be assumed until the affected file, graph, job, or DCC state is inspected.",
        ]

    lines = [f"**{title}**", ""]
    lines.extend(["**What happened**", summary or likely_cause])
    if operation:
        lines.extend(["", "**Operation**", f"`{operation}`"])

    lines.extend(["", "**User impact**"])
    lines.append("The requested action did not complete. Tech Connector should keep the current project state inspectable and avoid claiming success.")

    if context:
        lines.extend(["", "**Context**"])
        for key, value in context.items():
            if value in (None, "", [], {}):
                continue
            lines.append(f"- {key}: `{_clip_text(value, 220)}`")

    lines.extend(["", "**Evidence**"])
    if evidence:
        lines.extend(f"- {item}" for item in evidence[:10])
    else:
        lines.append("- No structured evidence was provided by the failing component.")

    lines.extend(["", "**Likely cause**", likely_cause])

    lines.extend(["", "**Recovery / next action**"])
    lines.extend(f"- {item}" for item in recovery[:8])

    lines.extend(["", "**Validation**"])
    lines.extend(f"- {item}" for item in validation[:8])

    if exception and include_traceback:
        tb = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        if tb.strip():
            lines.extend(["", "**Traceback**", "```text", _clip_text(tb, 5000), "```"])

    lines.extend(["", "**Reporting quality bar**"])
    lines.extend(f"- {item}" for item in documentation_quality_checklist(include_error_reporting=True)[:4])
    return "\n".join(lines)


def format_documentation_report(
    *,
    title: str = "Documentation Quality Report",
    topic: str = "",
    summary: str = "",
    evidence: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    validation: list[str] | None = None,
) -> str:
    """Render docs/status notes with the same quality standard as errors."""
    evidence = [str(item) for item in (evidence or []) if str(item).strip()]
    gaps = [str(item) for item in (gaps or []) if str(item).strip()]
    next_actions = [str(item) for item in (next_actions or []) if str(item).strip()]
    validation = [str(item) for item in (validation or []) if str(item).strip()]

    lines = [f"**{title}**", ""]
    if topic:
        lines.extend(["**Topic**", topic, ""])
    lines.extend(["**Summary**", summary or "No summary was provided."])
    lines.extend(["", "**Quality Standard**"])
    lines.extend(f"- {item}" for item in documentation_quality_checklist(include_error_reporting=False))
    if evidence:
        lines.extend(["", "**Evidence**", *[f"- {item}" for item in evidence[:10]]])
    if gaps:
        lines.extend(["", "**Gaps / Unknowns**", *[f"- {item}" for item in gaps[:10]]])
    if validation:
        lines.extend(["", "**Validation**", *[f"- {item}" for item in validation[:10]]])
    if next_actions:
        lines.extend(["", "**Next Actions**", *[f"- {item}" for item in next_actions[:10]]])
    return "\n".join(lines)


def _label_action(action_type: str) -> str:
    labels = {
        "resolve_symbol": "resolve a symbol",
        "resolve_function": "resolve a function",
        "resolve_class": "resolve a class",
        "resolve_file": "resolve a file",
        "open_file": "open a file",
        "open_symbol": "open a symbol",
        "search_project": "search the project index",
        "create_pipeline_node": "create a pipeline node",
        "connect_data": "connect data ports",
        "connect_flow": "connect flow",
        "bind_literal": "bind a literal value",
        "generate_python": "generate Python",
        "generate_workflow_code": "generate workflow code",
        "validate_graph": "validate the graph",
        "index_project": "index the project",
        "refresh_unreal": "refresh Unreal metadata",
        "github_search": "search GitHub",
        "github_ingest": "ingest a GitHub repository",
    }
    return labels.get(action_type, action_type.replace("_", " "))


def _action_args(action: dict[str, Any]) -> dict[str, Any]:
    value = action.get("args") or action.get("input") or {}
    return value if isinstance(value, dict) else {}


def _action_name(action: dict[str, Any]) -> str:
    args = _action_args(action)
    for key in ("query", "name", "character_name", "mesh_name", "primitive_type", "template", "material_name", "gameobject_name", "prefab_path", "path", "file_hint", "symbol"):
        value = args.get(key)
        if isinstance(value, dict):
            value = value.get("qualname") or value.get("name") or value.get("file_path")
        if value:
            return str(value)
    return str(action.get("title") or action.get("id") or action.get("action_id") or "")


def _action_line(action: dict[str, Any], index: int) -> str:
    action_type = str(action.get("type") or action.get("action_type") or "action")
    name = _action_name(action)
    suffix = f": `{name}`" if name else ""
    return f"{index}. {_label_action(action_type)}{suffix}"


def _summarize_errors(report: dict[str, Any], limit: int = 5) -> list[str]:
    validation = report.get("validation") or {}
    errors = [str(item) for item in validation.get("errors") or []]
    for action_id, status in (report.get("action_statuses") or {}).items():
        if status.get("status") in {"failed", "skipped"}:
            result = status.get("result") or {}
            reason = result.get("error") or status.get("reason") or "failed"
            errors.append(f"{action_id}: {reason}")
    return errors[:limit]


def format_action_plan_chat_report(
    plan: dict[str, Any],
    report: dict[str, Any],
    *,
    simple: bool = False,
) -> str:
    """Turn an action graph execution report into readable chat text."""
    actions = list(plan.get("actions") or [])
    status = str(report.get("status") or "unknown")
    goal = str(plan.get("goal") or "").strip()
    counts = report.get("status_counts") or {}
    completed = int(counts.get("completed") or 0)
    approval = report.get("approval") or {}
    mutating = approval.get("mutating_actions") or []

    if simple:
        if status == "approval_required":
            return (
                f"I've put together a plan with {len(actions)} steps, but before I execute any changes, I'll need your go-ahead. "
                f"Specifically, {len(mutating)} of these steps will modify files or tools in your project."
            )
        if status in {"completed", "dry_run"}:
            return f"All done! The plan was executed successfully (status: `{status}`). I completed {completed} out of {len(actions)} steps."
        errors = _summarize_errors(report, limit=2)
        tail = f" The first issue was: {errors[0]}" if errors else ""
        return f"The plan finished with status `{status}`.{tail}"

    if status == "approval_required":
        lead = "I've mapped out the necessary steps to achieve this, pausing right before any modifications are applied."
    elif status == "completed":
        lead = "Success! I've executed the plan and completed all the steps."
    elif status == "dry_run":
        lead = "I've performed a dry run to validate the plan, and everything looks good to go."
    elif status == "rejected":
        lead = "I couldn't run the plan because it didn't pass validation."
    else:
        lead = f"The plan execution finished with status `{status}`."

    lines: list[str] = [lead]
    if goal:
        lines.extend(["", "**What I Understood**", goal])

    lines.extend(["", "**Plan**"])
    for index, action in enumerate(actions[:10], start=1):
        lines.append(_action_line(action, index))
    if len(actions) > 10:
        lines.append(f"...plus {len(actions) - 10} more step(s).")

    if status == "approval_required":
        lines.extend(["", "**Why I Paused**"])
        if mutating:
            lines.append("The following steps require your approval because they will modify files, configurations, or connected tools:")
            action_map = {act.get("id"): act for act in actions if act.get("id")}
            for item in mutating[:8]:
                action_id = item.get("action_id")
                action_type = str(item.get("action_type") or "action")
                full_act = action_map.get(action_id)
                name = _action_name(full_act) if full_act else ""
                suffix = f": `{name}`" if name else f" `{action_id}`"
                lines.append(f"- {_label_action(action_type)}{suffix}")
            if len(mutating) > 8:
                lines.append(f"- ...and {len(mutating) - 8} more approval-gated step(s).")
        else:
            lines.append("Some steps in this plan were marked as approval-gated by the engine.")
        lines.extend(["", "**What's Next**", "Please review the proposed plan, and click approve whenever you're ready to run it."])
        return "\n".join(lines)

    lines.extend(["", "**Execution Details**"])
    lines.append(f"- Status: `{status}`")
    lines.append(f"- Completed steps: `{completed}/{len(actions)}`")
    if counts:
        count_bits = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        lines.append(f"- Step states: {count_bits}")

    errors = _summarize_errors(report)
    if errors:
        lines.extend(["", "**What Needs Attention**"])
        lines.extend(f"- {item}" for item in errors)

    return "\n".join(lines)


def _open_file_link(path: str, line: int = 1, label: str | None = None) -> str:
    path_text = str(path or "")
    line_no = max(1, int(line or 1))
    label_text = label or f"{Path(path_text).name} line {line_no}"
    return (
        f"[{label_text}]"
        f"(action://open_file?path={quote(path_text)}&line={line_no})"
    )


def _first_changed_line(before: str, after: str) -> int:
    before_lines = (before or "").splitlines()
    after_lines = (after or "").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
        if tag != "equal":
            return max(1, j1 + 1)
    return 1


def _change_counts(before: str, after: str) -> tuple[int, int]:
    before_lines = (before or "").splitlines()
    after_lines = (after or "").splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    added = 0
    removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            removed += i2 - i1
        if tag in {"replace", "insert"}:
            added += j2 - j1
    return added, removed


def _path_display(path: str, max_parts: int = 3) -> str:
    parts = Path(str(path or "")).parts
    if len(parts) <= max_parts:
        return str(Path(str(path or "")).as_posix())
    return "/".join(parts[-max_parts:])


def _short_diff(before: str, after: str, *, limit: int = 38) -> str:
    diff = list(
        difflib.unified_diff(
            (before or "").splitlines(),
            (after or "").splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    if len(diff) > limit:
        diff = diff[:limit] + [f"... truncated {len(diff) - limit} more diff line(s) ..."]
    return "\n".join(diff)


def format_code_change_report(
    changes: list[dict[str, Any]],
    *,
    title: str = "Code Changes Applied",
    undo_hint: str = "Use **Undo Last Change** if QA finds a regression.",
    validation: list[str] | None = None,
    include_diff: bool = True,
) -> str:
    """Render code edits with direct file/line anchors and QA context."""
    normalized = []
    for change in changes:
        path = str(change.get("path") or "")
        action = str(change.get("action") or "modify")
        before = str(change.get("before") or change.get("original_content") or "")
        after = str(change.get("after") or change.get("new_content") or change.get("current") or "")
        summary = str(change.get("summary") or "").strip()
        line = int(change.get("line") or _first_changed_line(before, after))
        added, removed = _change_counts(before, after)
        normalized.append(
            {
                "path": path,
                "action": action,
                "before": before,
                "after": after,
                "summary": summary,
                "line": line,
                "added": added,
                "removed": removed,
            }
        )

    lines = [f"**{title}**", ""]
    if not normalized:
        lines.append("No changed files were reported.")
        return "\n".join(lines)

    total_added = sum(int(item["added"]) for item in normalized)
    total_removed = sum(int(item["removed"]) for item in normalized)
    noun = "file" if len(normalized) == 1 else "files"
    first_review_link = _open_file_link(
        normalized[0]["path"],
        normalized[0]["line"],
        "Review changed file" if len(normalized) == 1 else "Review first changed file",
    )
    lines.extend(
        [
            f"**Edited {len(normalized)} {noun}**",
            f"`+{total_added}` `-{total_removed}`",
            "",
            f"[Undo last change](action://undo_last_applied) | {first_review_link}",
            "",
            "**Changed Files**",
        ]
    )
    for item in normalized:
        link = _open_file_link(item["path"], item["line"], _path_display(item["path"]))
        lines.append(f"- {link} `+{item['added']}` `-{item['removed']}`")
    lines.append("")

    lines.extend(["**What Changed**"])
    for item in normalized:
        link = _open_file_link(item["path"], item["line"])
        counts = f"+{item['added']} / -{item['removed']}" if item["action"] != "create" else f"+{len(item['after'].splitlines())}"
        summary = item["summary"] or (
            "Created a new file." if item["action"] == "create" else "Updated existing code."
        )
        lines.append(f"- {link} - `{item['action']}` ({counts} lines): {summary}")

    lines.extend(["", "**Impact vs Before**"])
    for item in normalized:
        if item["action"] == "create":
            lines.append(f"- `{Path(item['path']).name}` did not exist before; it now adds the new behavior in one inspectable file.")
        elif item["added"] or item["removed"]:
            lines.append(
                f"- `{Path(item['path']).name}` changed around line `{item['line']}`; "
                f"the previous implementation was replaced with the updated behavior shown in the diff."
            )
        else:
            lines.append(f"- `{Path(item['path']).name}` was touched, but no textual delta was detected by the report formatter.")

    lines.extend(["", "**QA / Debug Handles**"])
    for item in normalized:
        lines.append(f"- Open { _open_file_link(item['path'], item['line'], 'changed code') } and inspect the surrounding logic.")
    lines.append(f"- {undo_hint}")

    if validation:
        lines.extend(["", "**Verification**"])
        lines.extend(f"- {entry}" for entry in validation if str(entry).strip())

    if include_diff:
        diff_blocks = []
        for item in normalized[:3]:
            diff = _short_diff(item["before"], item["after"])
            if diff.strip():
                diff_blocks.append(f"### {Path(item['path']).name}\n```diff\n{diff}\n```")
        if diff_blocks:
            lines.extend(["", "**Review Diff**", *diff_blocks])
    return "\n".join(lines)


def format_unreal_change_report(result: dict[str, Any] | None) -> str:
    """Render Unreal asset/graph edits with validation and rollback details."""
    if not result:
        return "No Unreal change result was reported."
    request = result.get("request") or {}
    patch = result.get("patch") or {}
    preview = result.get("preview") or {}
    rollback = result.get("rollback") or {}
    validation = result.get("validation") or {}
    operations = list((patch.get("operations") or []))
    target_asset = request.get("target_asset") or patch.get("target_asset") or ""
    target_graph = request.get("target_graph") or patch.get("target_graph") or ""
    applied = bool(result.get("applied"))
    mode = str(result.get("mode") or "unknown")

    lines = [
        "**Unreal Change Report**",
        "",
        "**What Changed**",
        f"- Target asset: `{target_asset or 'unknown'}`",
        f"- Target graph: `{target_graph or 'unknown'}`",
        f"- Mode: `{mode}`; applied: `{'yes' if applied else 'no'}`",
        f"- Operations: `{preview.get('operation_count', len(operations))}`",
    ]
    for idx, op in enumerate(operations[:8], start=1):
        action = op.get("op") or op.get("type") or "operation"
        subject = op.get("node") or op.get("from_node") or op.get("to_node") or op.get("pin") or ""
        detail = f" `{subject}`" if subject else ""
        lines.append(f"  {idx}. `{action}`{detail}")
    if len(operations) > 8:
        lines.append(f"  ...plus {len(operations) - 8} more operation(s).")

    lines.extend(["", "**Impact vs Before**"])
    if applied:
        lines.append("- The Blueprint graph was changed in the live Unreal project, after preflight checks and backup creation.")
    else:
        lines.append("- No live graph edit was applied; this is a plan/blocked/partial result that should be reviewed before retrying.")
    if rollback.get("backup_asset"):
        lines.append(f"- Backup asset for rollback/inspection: `{rollback.get('backup_asset')}`")

    lines.extend(["", "**Validation / QA**"])
    lines.append(f"- Preflight ok: `{'yes' if (result.get('preflight') or {}).get('ok') else 'no'}`")
    if validation:
        lines.append(f"- Compile ok: `{'yes' if validation.get('compile_ok') else 'no'}`")
        if validation.get("graph_snapshot_after"):
            lines.append("- A post-change graph snapshot was captured for inspection.")
    for label, values in (
        ("Errors", result.get("errors") or []),
        ("Warnings", result.get("warnings") or []),
        ("Compile errors", validation.get("compile_errors") or []),
        ("Validation errors", validation.get("validation_errors") or []),
    ):
        if values:
            lines.append(f"- {label}:")
            lines.extend(f"  - {item}" for item in values[:8])

    lines.extend(
        [
            "",
            "**Next QA Steps**",
            "- Open the target Blueprint in Unreal and inspect the graph around the changed nodes/pins.",
            "- Compile the Blueprint and run the affected gameplay/editor workflow once.",
            "- If behavior regresses, restore from the backup asset or rerun with a narrower patch request.",
        ]
    )
    return "\n".join(lines)


def format_unreal_operation_report(
    raw: Any,
    *,
    operation: str = "",
    ok: bool = True,
    request: dict[str, Any] | None = None,
    detail_text: str = "",
) -> str:
    """Render non-graph Unreal operations with QA and asset traceability."""
    payload = raw
    if isinstance(payload, str):
        try:
            import json

            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            pass
    data = payload if isinstance(payload, dict) else {}
    request = request or {}
    asset_path = (
        data.get("asset_path")
        or data.get("created_asset")
        or data.get("target_asset")
        or request.get("asset_path")
        or request.get("target_path")
        or request.get("blueprint_path")
        or ""
    )
    created = data.get("created")
    steps = list(data.get("steps_executed") or data.get("steps") or [])
    warnings = list(data.get("warnings") or [])
    errors = list(data.get("errors") or [])
    message = str(data.get("message") or detail_text or payload or "")

    lines = [
        "**Unreal Operation Report**",
        "",
        "**What Changed**",
        f"- Operation: `{operation or data.get('operation') or 'unreal operation'}`",
        f"- Status: `{'completed' if ok else 'failed'}`",
    ]
    if asset_path:
        lines.append(f"- Asset: `{asset_path}`")
    if created not in (None, ""):
        lines.append(f"- Created/modified: `{created}`")
    if message:
        lines.append(f"- Result: {message}")

    resolved = data.get("resolved")
    if not resolved:
        resolved = data.get("bridge_result", {}).get("data", {}).get("resolved")
    if not resolved:
        resolved = data.get("result", {}).get("resolved")
    if isinstance(resolved, dict) and resolved:
        lines.extend(["", "**Dynamic Argument Resolution & Type Conversions**"])
        for param_name, res in resolved.items():
            if isinstance(res, dict):
                kind = res.get("kind") or "object"
                source = res.get("source") or "resolver"
                name = res.get("name") or "unknown name"
                cls = res.get("class") or ""
                path = res.get("path") or res.get("ref") or ""
                query = res.get("query") or ""
                lines.append(f"- Parameter `{param_name}` resolved from query text: `\"{query or name}\"`")
                lines.append(f"  - System dynamically converted input using `{source}` to locate the `{kind}`:")
                lines.append(f"    - Target object: `{name}` (`{cls}`)")
                if path:
                    lines.append(f"    - Object path: `{path}`")

    if steps:
        lines.extend(["", "**Execution Details**"])
        lines.extend(f"{idx}. {step}" for idx, step in enumerate(steps[:10], start=1))
        if len(steps) > 10:
            lines.append(f"...plus {len(steps) - 10} more step(s).")

    lines.extend(["", "**Impact vs Before**"])
    if ok and asset_path:
        lines.append("- The operation changed or created a concrete Unreal asset that can be inspected directly in the editor.")
    elif ok:
        lines.append("- The operation completed in Unreal; inspect the listed result data for the affected object or subsystem.")
    else:
        lines.append("- The operation did not complete successfully; no successful mutation should be assumed until Unreal is inspected.")

    lines.extend(["", "**Validation / QA**"])
    if data.get("compile_ok") is not None:
        lines.append(f"- Compile ok: `{'yes' if data.get('compile_ok') else 'no'}`")
    if data.get("validation_report"):
        lines.append("- Validation report returned by Unreal.")
    for label, values in (("Warnings", warnings), ("Errors", errors)):
        if values:
            lines.append(f"- {label}:")
            lines.extend(f"  - {item}" for item in values[:8])
    lines.extend(
        [
            "- Open the affected asset or level in Unreal and verify the visible result.",
            "- Run the affected editor/gameplay path once before treating this as complete.",
        ]
    )
    return "\n".join(lines)
