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
    # Compatibility fields. The canonical source is conversation_workspace.
    selected_file: str = ""
    selected_callable: str = ""
    selected_objects: list[str] = field(default_factory=list)
    selected_assets: list[str] = field(default_factory=list)
    output_directory: str = ""
    selected_project: str = ""
    resolved_slots: dict[str, Any] = field(default_factory=dict)
    recent_results: list[dict[str, Any]] = field(default_factory=list)
    conversation_workspace: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        try:
            from tech_connector.services.conversation_workspace_service import compatibility_snapshot

            compat = compatibility_snapshot(self.conversation_workspace)
            for key, value in compat.items():
                if value not in ("", [], None):
                    data[key] = value
        except Exception:
            pass
        return data


def operation_memory_from_dict(data: dict[str, Any] | None) -> OperationMemory:
    data = dict(data or {})
    allowed = set(OperationMemory.__dataclass_fields__.keys())
    memory = OperationMemory(**{key: value for key, value in data.items() if key in allowed})
    if not memory.conversation_workspace:
        try:
            from tech_connector.services.conversation_workspace_service import merge_workspace_update, file_entity_payload

            entities = []
            if memory.selected_file:
                entities.append(file_entity_payload(memory.selected_file, source="operation_memory", confidence=0.9))
            update = {
                "entities": entities,
                "selected_assets": list(memory.selected_assets or []),
                "selected_actors": list(memory.selected_objects or []),
                "result_summary": "Legacy operation memory import" if entities or memory.selected_assets or memory.selected_objects else "",
            }
            if entities or memory.selected_assets or memory.selected_objects:
                memory.conversation_workspace = merge_workspace_update({}, update)
        except Exception:
            pass
    return memory


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
        try:
            from tech_connector.services.conversation_workspace_service import file_entity_payload, merge_workspace_update

            current.conversation_workspace = merge_workspace_update(
                current.conversation_workspace,
                {
                    "entities": [file_entity_payload(current.selected_file, source="route_decision", confidence=0.92)],
                    "result_summary": "Resolved route file",
                },
            )
        except Exception as exc:
            current.resolved_slots.setdefault("workspace_merge_error", str(exc))
    target = route_decision.get("target_identifier") or execution_request.get("target_identifier")
    if target and not current.operation_id:
        current.operation_id = str(target)

    if binding.get("accepted") and binding.get("slot"):
        current.resolved_slots[str(binding.get("slot"))] = binding.get("value")
    for key, value in dict(route_decision.get("keyword_args") or execution_request.get("keyword_args") or {}).items():
        current.resolved_slots[str(key)] = value

    if result:
        try:
            from tech_connector.services.conversation_workspace_service import (
                compatibility_snapshot,
                merge_workspace_update,
                workspace_update_from_legacy_metadata,
            )

            update = result.get("workspace_update") or workspace_update_from_legacy_metadata(result)
            if update:
                current.conversation_workspace = merge_workspace_update(
                    current.conversation_workspace,
                    update,
                    request_id=str(result.get("request_id") or route_decision.get("request_id") or ""),
                )
            compat = compatibility_snapshot(current.conversation_workspace)
        except Exception as exc:
            current.resolved_slots.setdefault("workspace_merge_error", str(exc))
            compat = {}
        entities = result.get("conversation_entities") or {}
        selected_file = (
            compat.get("selected_file")
            or result.get("selected_file")
            or result.get("resolved_target_file")
            or (entities.get("selected_file") if isinstance(entities, dict) else "")
        )
        selected_callable = result.get("selected_callable") or (entities.get("selected_callable") if isinstance(entities, dict) else "")
        if selected_file:
            current.selected_file = str(selected_file)
            current.resolved_slots["target_file"] = current.selected_file
            current.resolved_slots["file"] = current.selected_file
        current.selected_assets = list(compat.get("selected_assets") or current.selected_assets or [])
        current.selected_objects = list(compat.get("selected_objects") or current.selected_objects or [])
        if selected_callable:
            current.selected_callable = str(selected_callable)
        current.recent_results.append(
            {
                "status": result.get("status") or result.get("result_type") or "",
                "operation_mode": result.get("operation_mode") or execution_request.get("operation_mode") or "",
                "target": selected_file or target or callable_name or "",
                "selected_file": str(selected_file or ""),
                "selected_callable": str(selected_callable or ""),
                "timestamp": time.time(),
            }
        )
        current.recent_results = current.recent_results[-8:]
    current.updated_at = time.time()
    return current.to_dict()


def apply_operation_memory_to_decision(decision: dict[str, Any], memory: dict[str, Any] | None) -> dict[str, Any]:
    updated = dict(decision or {})
    mem = operation_memory_from_dict(memory)
    try:
        from tech_connector.services.conversation_workspace_service import resolve_reference

        prompt_text_for_resolution = str(updated.get("original_prompt") or updated.get("prompt") or updated.get("request_text") or "")
        if prompt_text_for_resolution:
            resolution = resolve_reference(mem.conversation_workspace, prompt_text_for_resolution)
            if resolution.status == "resolved" and resolution.kind == "file":
                from tech_connector.services.conversation_workspace_service import workspace_from_dict

                workspace = workspace_from_dict(mem.conversation_workspace)
                entity = workspace.entities.get(resolution.entity_id)
                if entity and entity.ref:
                    mem.selected_file = entity.ref
                    updated["resolved_target_file"] = entity.ref
                    updated["target_file"] = entity.ref
                    updated["file"] = entity.ref
                    updated["scope"] = "file"
                    updated["reference_scope_locked"] = True
                    updated["reference_resolution"] = {
                        **resolution.to_dict(),
                        "resolved_value": entity.ref,
                    }
    except Exception:
        pass
    missing = list(updated.get("missing_info") or [])
    if "execution_environment" in missing and mem.selected_host:
        updated["host"] = mem.selected_host
        updated["execution_environment"] = mem.selected_host
        missing = [item for item in missing if item != "execution_environment"]
    prompt_text = str(updated.get("original_prompt") or updated.get("prompt") or updated.get("request_text") or "")
    if mem.selected_file and __import__("re").search(
        r"\b(?:in|inside|within|from)\s+(?:that|this|the previous|the selected|the found)\s+file\b|"
        r"\b(?:that|this|the previous|the selected|the found)\s+file\b",
        prompt_text, __import__("re").IGNORECASE,
    ):
        updated["resolved_target_file"] = mem.selected_file
        updated["target_file"] = mem.selected_file
        updated["file"] = mem.selected_file
        updated["scope"] = "file"
        updated["reference_scope_locked"] = True
        updated["reference_resolution"] = {
            "reference": "that file", "resolved_value": mem.selected_file,
            "kind": "file", "source": "prior_answer", "confidence": 0.98,
        }
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
