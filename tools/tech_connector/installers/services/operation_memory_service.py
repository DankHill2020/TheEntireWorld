"""Short-lived operation memory for active routed requests.

This is not long-term user memory. It is a small working context for the active
operation so follow-up replies like "use Maya" or "preview it first" can modify
the current request without restarting from scratch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any


@dataclass
class OperationMemory:
    operation_id: str = ""
    selected_host: str = ""
    selected_workflow: str = ""
    selected_graph: str = ""
    selected_file: str = ""
    selected_callable: str = ""
    selected_objects: list[str] = field(default_factory=list)
    selected_assets: list[str] = field(default_factory=list)
    output_directory: str = ""
    selected_project: str = ""
    resolved_slots: dict[str, Any] = field(default_factory=dict)
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def operation_memory_from_dict(data: dict[str, Any] | None) -> OperationMemory:
    data = dict(data or {})
    allowed = set(OperationMemory.__dataclass_fields__.keys())
    return OperationMemory(**{key: value for key, value in data.items() if key in allowed})


def update_operation_memory(
    memory: dict[str, Any] | OperationMemory | None,
    *,
    route_decision: dict[str, Any] | None = None,
    execution_request: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = memory if isinstance(memory, OperationMemory) else operation_memory_from_dict(memory)
    route_decision = route_decision or {}
    execution_request = execution_request or {}
    binding = binding or {}

    host = route_decision.get("host") or route_decision.get("execution_environment") or execution_request.get("execution_environment")
    if host:
        current.selected_host = str(host).lower()
        current.resolved_slots["execution_environment"] = current.selected_host
    callable_name = route_decision.get("callable_name") or execution_request.get("callable_name")
    if callable_name:
        current.selected_callable = str(callable_name)
    file_path = route_decision.get("file") or execution_request.get("file")
    if file_path:
        current.selected_file = str(file_path)
    target = route_decision.get("target_identifier") or execution_request.get("target_identifier")
    if target and not current.operation_id:
        current.operation_id = str(target)

    if binding.get("accepted") and binding.get("slot"):
        current.resolved_slots[str(binding.get("slot"))] = binding.get("value")
    for key, value in dict(route_decision.get("keyword_args") or execution_request.get("keyword_args") or {}).items():
        current.resolved_slots[str(key)] = value

    if result:
        current.recent_results.append(
            {
                "status": result.get("status") or result.get("result_type") or "",
                "operation_mode": result.get("operation_mode") or execution_request.get("operation_mode") or "",
                "target": target or callable_name or "",
                "timestamp": time.time(),
            }
        )
        current.recent_results = current.recent_results[-8:]
    current.updated_at = time.time()
    return current.to_dict()


def apply_operation_memory_to_decision(decision: dict[str, Any], memory: dict[str, Any] | None) -> dict[str, Any]:
    updated = dict(decision or {})
    mem = operation_memory_from_dict(memory)
    missing = list(updated.get("missing_info") or [])
    if "execution_environment" in missing and mem.selected_host:
        updated["host"] = mem.selected_host
        updated["execution_environment"] = mem.selected_host
        missing = [item for item in missing if item != "execution_environment"]
    keyword_args = dict(updated.get("keyword_args") or {})
    for slot in list(missing):
        if slot in mem.resolved_slots:
            keyword_args[slot] = mem.resolved_slots[slot]
            missing.remove(slot)
    if keyword_args:
        updated["keyword_args"] = keyword_args
    updated["missing_info"] = missing
    return updated


def clear_operation_memory(memory: dict[str, Any] | None, *, reason: str = "") -> dict[str, Any]:
    current = operation_memory_from_dict(memory)
    current.status = "cleared"
    current.updated_at = time.time()
    if reason:
        current.recent_results.append({"status": "cleared", "reason": reason, "timestamp": current.updated_at})
    return current.to_dict()
