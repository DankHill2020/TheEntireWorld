"""Lifecycle guards for chat operations, provider jobs, and UI actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any
from uuid import uuid4


@dataclass
class ProviderGeneration:
    request_id: str
    operation_id: str
    continuation_id: str
    slot_name: str
    generation: int
    status: str = "running"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OperationState:
    operation_id: str
    continuation_id: str = ""
    origin_message_id: str = ""
    status: str = "active"
    revision: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    provider_generations: dict[str, int] = field(default_factory=dict)
    provider_requests: dict[str, ProviderGeneration] = field(default_factory=dict)
    claimed_actions: dict[str, str] = field(default_factory=dict)
    cancellation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_requests"] = {key: value.to_dict() for key, value in self.provider_requests.items()}
        return payload


class InteractionLifecycleManager:
    """Owns operation identity, stale-result checks, and action idempotency."""

    def __init__(self):
        self._operations: dict[str, OperationState] = {}
        self._active_operation_id = ""

    def start_operation(self, *, continuation_id: str = "", origin_message_id: str = "") -> OperationState:
        operation = OperationState(
            operation_id=f"op_{uuid4().hex[:12]}",
            continuation_id=str(continuation_id or ""),
            origin_message_id=str(origin_message_id or ""),
        )
        if self._active_operation_id:
            self.cancel_operation(self._active_operation_id, reason="superseded")
        self._operations[operation.operation_id] = operation
        self._active_operation_id = operation.operation_id
        return operation

    def current_operation(self) -> OperationState | None:
        if not self._active_operation_id:
            return None
        operation = self._operations.get(self._active_operation_id)
        if operation and operation.status == "active":
            return operation
        return None

    def get_operation(self, operation_id: str) -> OperationState | None:
        return self._operations.get(str(operation_id or ""))

    def cancel_operation(self, operation_id: str, *, reason: str = "cancelled") -> bool:
        operation = self.get_operation(operation_id)
        if not operation:
            return False
        operation.status = "cancelled"
        operation.cancellation_reason = reason
        operation.updated_at = time.time()
        for request in operation.provider_requests.values():
            if request.status == "running":
                request.status = "cancelled"
        if self._active_operation_id == operation.operation_id:
            self._active_operation_id = ""
        return True

    def cancel_current(self, *, reason: str = "cancelled") -> bool:
        if not self._active_operation_id:
            return False
        return self.cancel_operation(self._active_operation_id, reason=reason)

    def start_provider_request(self, *, operation_id: str, continuation_id: str, slot_name: str) -> ProviderGeneration:
        operation = self.get_operation(operation_id)
        if not operation or operation.status != "active":
            raise ValueError("Cannot start provider request for inactive operation.")
        slot = str(slot_name or "")
        generation = int(operation.provider_generations.get(slot, 0)) + 1
        operation.provider_generations[slot] = generation
        operation.updated_at = time.time()
        request = ProviderGeneration(
            request_id=f"choice_{uuid4().hex[:12]}",
            operation_id=operation.operation_id,
            continuation_id=str(continuation_id or operation.continuation_id or ""),
            slot_name=slot,
            generation=generation,
        )
        operation.provider_requests[request.request_id] = request
        return request

    def can_apply_provider_result(
        self,
        *,
        operation_id: str,
        continuation_id: str,
        request_id: str,
        slot_name: str,
        generation: int,
    ) -> bool:
        operation = self.get_operation(operation_id)
        if not operation or operation.status != "active":
            return False
        if str(continuation_id or "") != str(operation.continuation_id or ""):
            return False
        request = operation.provider_requests.get(str(request_id or ""))
        if not request or request.status == "cancelled":
            return False
        if request.slot_name != str(slot_name or ""):
            return False
        latest = int(operation.provider_generations.get(request.slot_name, 0))
        return int(generation or 0) == latest and int(request.generation) == latest

    def finish_provider_request(self, request_id: str, *, status: str) -> None:
        for operation in self._operations.values():
            request = operation.provider_requests.get(str(request_id or ""))
            if request:
                request.status = str(status or "completed")
                operation.updated_at = time.time()
                return

    def claim_action(self, *, operation_id: str, action_id: str, idempotency_key: str = "") -> bool:
        operation = self.get_operation(operation_id)
        if not operation or operation.status != "active":
            return False
        key = str(idempotency_key or action_id or "")
        if not key:
            return False
        if key in operation.claimed_actions:
            return False
        operation.claimed_actions[key] = str(action_id or key)
        operation.updated_at = time.time()
        return True

    def action_count(self, operation_id: str) -> int:
        operation = self.get_operation(operation_id)
        return len(operation.claimed_actions) if operation else 0
