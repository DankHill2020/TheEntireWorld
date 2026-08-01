"""Dependency-ordered Unreal task sequences and bounded semantic verification."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Callable


TaskEventCallback = Callable[[dict[str, Any]], None]


def _parse_verdict_rows(raw: str) -> list[dict[str, Any]]:
    """Recover complete verdict objects even when a small model truncates the envelope."""

    source = str(raw or "")
    try:
        parsed = json.loads(source)
        rows = list(parsed.get("verdicts") or []) if isinstance(parsed, dict) else []
    except Exception:
        rows = []
        decoder = json.JSONDecoder()
        cursor = 0
        while True:
            start = source.find('{"id"', cursor)
            if start < 0:
                break
            try:
                value, consumed = decoder.raw_decode(source[start:])
            except Exception:
                cursor = start + 5
                continue
            if isinstance(value, dict):
                rows.append(value)
            cursor = start + consumed
    normalized = []
    seen = set()
    for raw_row in rows:
        row = dict(raw_row or {})
        clause_id = str(row.get("id") or "")
        if not clause_id or clause_id in seen:
            continue
        seen.add(clause_id)
        confidence = max(0.0, min(1.0, float(row.get("confidence") or 0.0)))
        missing_terms = [str(value) for value in row.get("missing_terms") or [] if value]
        matches = bool(row.get("match"))
        normalized.append(
            {
                "id": clause_id,
                "match": matches,
                "missing_terms": [] if matches else missing_terms,
                "dismissed_missing_terms": missing_terms if matches else [],
                "confidence": confidence,
            }
        )
    return normalized


def build_unreal_task_sequence(
    requirements: list[dict[str, Any]],
    clause_coverage: dict[str, Any],
    operation_status: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Convert requirement chains into concrete, resumable tasks."""

    requirement_tasks: dict[str, dict[str, Any]] = {}
    ordered_tasks: list[dict[str, Any]] = []
    previous_task_id = ""
    for requirement_index, requirement in enumerate(requirements, 1):
        requirement_id = f"requirement_{requirement_index:02d}"
        operation_arguments = dict(requirement.get("operation_arguments") or {})
        task_operations = []
        for operation_index, operation in enumerate(requirement.get("operations") or [], 1):
            status = dict(operation_status.get(str(operation)) or {})
            task_operations.append(
                {
                    "sequence": operation_index,
                    "operation": operation,
                    "function": status.get("function") or "",
                    "arguments": dict(operation_arguments.get(operation) or {}),
                    "callable": bool(status.get("callable_found")),
                    "postcondition": requirement.get("success") or "",
                }
            )
        task_id = f"task_{requirement_index:02d}"
        source_clause_ids = [
            str(row.get("clause_id") or "")
            for row in clause_coverage.get("clauses") or []
            if requirement_id in (row.get("covered_by") or [])
        ]
        task = {
            "task_id": task_id,
            "requirement_id": requirement_id,
            "sequence": requirement_index,
            "title": requirement.get("title") or requirement_id,
            "domain": requirement.get("domain") or "",
            "source_clause_ids": source_clause_ids,
            "depends_on": [previous_task_id] if previous_task_id else [],
            "operations": task_operations,
            "postcondition": requirement.get("success") or "",
            "status": "pending",
            "pause_checkpoint": True,
            "resume_from": task_id,
        }
        requirement_tasks[requirement_id] = task
        ordered_tasks.append(task)
        previous_task_id = task_id

    clause_sequences = []
    for row in clause_coverage.get("clauses") or []:
        tasks = [
            requirement_tasks[requirement_id]
            for requirement_id in row.get("covered_by") or []
            if requirement_id in requirement_tasks
        ]
        clause_sequences.append(
            {
                "clause_id": row.get("clause_id"),
                "source_clause": row.get("source_clause"),
                "task_ids": [task["task_id"] for task in tasks],
                "tasks": [
                    {
                        "task_id": task["task_id"],
                        "title": task["title"],
                        "domain": task["domain"],
                        "operations": [
                            {
                                "operation": operation["operation"],
                                "function": operation["function"],
                                "arguments": operation["arguments"],
                            }
                            for operation in task["operations"]
                        ],
                        "postcondition": task["postcondition"],
                    }
                    for task in tasks
                ],
            }
        )
    return {
        "framework": "unreal_dependency_task_sequence_v1",
        "task_count": len(ordered_tasks),
        "tasks": ordered_tasks,
        "clause_sequences": clause_sequences,
        "pause_resume": {
            "supported": True,
            "checkpoint_granularity": "task",
            "context_merge_policy": "append user context to the active task and reverify only that task",
            "completed_task_policy": "retain passed task evidence unless its inputs or dependencies changed",
        },
    }


def verify_unreal_task_sequence(
    task_sequence: dict[str, Any],
    *,
    model: str = "qwen3:4b-instruct",
    batch_size: int = 4,
    timeout: int = 12,
    event: TaskEventCallback | None = None,
) -> dict[str, Any]:
    """Verify focused clause/task alignment without asking the model to plan."""

    from tech_connector.services.llm_router_service import _query_ollama

    started = perf_counter()
    sequences = list(task_sequence.get("clause_sequences") or [])
    verdicts = []
    batches = []
    schema = {
        "type": "object",
        "required": ["verdicts"],
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "match", "missing_terms", "confidence"],
                    "properties": {
                        "id": {"type": "string"},
                        "match": {"type": "boolean"},
                        "missing_terms": {
                            "type": "array",
                            "maxItems": 4,
                            "items": {"type": "string"},
                        },
                        "confidence": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    system = (
        "Verify each independent Unreal requirement against only its proposed task sequence. "
        "Do not plan, rewrite, explain, or add implied requirements. Match is true only when "
        "the explicit request is represented by operations, arguments, and postconditions. "
        "Return one compact verdict per input id in the same order."
    )
    for start in range(0, len(sequences), max(1, int(batch_size))):
        batch = sequences[start : start + max(1, int(batch_size))]
        batch_number = (start // max(1, int(batch_size))) + 1
        batch_total = (len(sequences) + max(1, int(batch_size)) - 1) // max(
            1, int(batch_size)
        )
        if event:
            event(
                {
                    "type": "verification_batch_started",
                    "first_clause": start + 1,
                    "last_clause": start + len(batch),
                    "clause_count": len(sequences),
                    "batch_number": batch_number,
                    "batch_total": batch_total,
                }
            )
        packet = {
            "checks": [
                {
                    "id": row.get("clause_id"),
                    "requirement": row.get("source_clause"),
                    "tasks": [
                        {
                            "title": task.get("title"),
                            "operations": [
                                operation.get("operation")
                                for operation in task.get("operations") or []
                            ],
                            "argument_keys": sorted(
                                {
                                    key
                                    for operation in task.get("operations") or []
                                    for key in dict(
                                        operation.get("arguments") or {}
                                    )
                                }
                            ),
                            "postcondition": task.get("postcondition"),
                        }
                        for task in row.get("tasks") or []
                    ],
                }
                for row in batch
            ]
        }
        batch_started = perf_counter()
        raw = _query_ollama(
            model=model,
            prompt=json.dumps(packet, separators=(",", ":"), default=str),
            system=system,
            response_format=schema,
            options={
                "temperature": 0.0,
                "num_ctx": 3072,
                "num_predict": 240,
                "top_k": 1,
                "top_p": 0.1,
                "repeat_penalty": 1.0,
            },
            timeout=max(3, int(timeout)),
        )
        elapsed_ms = round((perf_counter() - batch_started) * 1000.0, 3)
        rows = _parse_verdict_rows(str(raw or ""))
        by_id = {str(row.get("id") or ""): dict(row) for row in rows if isinstance(row, dict)}
        for source in batch:
            clause_id = str(source.get("clause_id") or "")
            row = by_id.get(clause_id)
            if row is None:
                row = {
                    "id": clause_id,
                    "match": False,
                    "missing_terms": ["verifier_result_missing"],
                    "confidence": 0.0,
                }
            verdicts.append(row)
        batches.append(
            {
                "clause_ids": [str(row.get("clause_id") or "") for row in batch],
                "elapsed_ms": elapsed_ms,
                "parsed": bool(rows),
                "raw": str(raw or "")[:1000],
            }
        )
        if event:
            batch_failures = [
                str(row.get("id") or "")
                for row in verdicts[-len(batch) :]
                if not row.get("match")
            ]
            event(
                {
                    "type": "verification_batch_finished",
                    "batch_number": batch_number,
                    "batch_total": batch_total,
                    "elapsed_ms": elapsed_ms,
                    "failed_clause_ids": batch_failures,
                }
            )
    failed = [
        str(row.get("id") or "")
        for row in verdicts
        if not row.get("match") or float(row.get("confidence") or 0.0) < 0.6
    ]
    return {
        "framework": "unreal_task_sequence_verification_v1",
        "model": model,
        "status": "verified" if not failed else "targeted_repair_required",
        "verified": not failed,
        "verdicts": verdicts,
        "failed_clause_ids": failed,
        "batches": batches,
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }
