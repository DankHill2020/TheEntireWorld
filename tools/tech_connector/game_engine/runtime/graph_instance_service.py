from __future__ import annotations

"""Stateful fixed-step ownership for compiled TC graph programs."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, MutableMapping

from tech_connector.game_engine.runtime.graph_execution_service import (
    GraphExecutionContext,
    GraphExecutionLimits,
    GraphExecutionReceipt,
    GraphOperationRegistry,
    NATIVE_GRAPH_ABI,
    NATIVE_GRAPH_MANIFEST_SCHEMA,
    execute_graph_manifest,
)


@dataclass
class GraphTickReceipt:
    status: str
    steps_executed: int
    simulated_seconds: float
    dropped_seconds: float
    accumulator_seconds: float
    executions: list[GraphExecutionReceipt] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"complete", "idle", "paused"} and all(
            receipt.ok for receipt in self.executions
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.graph_tick_receipt.v1",
            **asdict(self),
            "executions": [receipt.to_dict() for receipt in self.executions],
            "ok": self.ok,
        }


class GraphRuntimeInstance:
    """Own one graph's state, event lifecycle, and deterministic tick schedule."""

    def __init__(
        self,
        manifest: Mapping[str, Any],
        context: GraphExecutionContext | Mapping[str, Any],
        *,
        registry: GraphOperationRegistry | None = None,
        limits: GraphExecutionLimits | None = None,
        fixed_step_seconds: float = 1.0 / 60.0,
        max_substeps: int = 4,
        max_frame_delta: float = 0.25,
    ) -> None:
        self._validate_manifest(manifest)
        self.manifest = deepcopy(dict(manifest))
        self._external_context = context if isinstance(context, MutableMapping) else None
        self.context = GraphExecutionContext.from_value(context)
        self.registry = registry
        self.limits = limits
        self.fixed_step_seconds = _positive_finite(
            fixed_step_seconds,
            "Fixed Step Seconds",
        )
        self.max_substeps = max(1, int(max_substeps))
        self.max_frame_delta = _positive_finite(
            max_frame_delta,
            "Maximum Frame Delta",
        )
        self.accumulator_seconds = 0.0
        self.elapsed_seconds = 0.0
        self.paused = False
        self.begin_play_complete = False

    @property
    def entry_event(self) -> str:
        return str(self.manifest.get("entry_event") or "On Begin Play")

    def begin_play(self) -> GraphExecutionReceipt:
        if self.begin_play_complete:
            return _idle_execution_receipt(
                str(self.manifest.get("program_id") or "graph_program"),
                "Begin Play already completed.",
            )
        receipt = self.run_event("On Begin Play")
        if receipt.ok:
            self.begin_play_complete = True
        return receipt

    def run_event(
        self,
        event_name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> GraphExecutionReceipt:
        self._refresh_external_context()
        requested = _event_key(event_name)
        expected = _event_key(self.entry_event)
        if requested != expected:
            return _idle_execution_receipt(
                str(self.manifest.get("program_id") or "graph_program"),
                f"This graph listens for {self.entry_event}, not {event_name}.",
            )
        previous_event = self.context.metadata.get("current_graph_event")
        self.context.metadata["current_graph_event"] = {
            "name": str(event_name),
            "payload": dict(payload or {}),
        }
        receipt = execute_graph_manifest(
            self.manifest,
            self.context,
            registry=self.registry,
            limits=self.limits,
        )
        if previous_event is None:
            self.context.metadata.pop("current_graph_event", None)
        else:
            self.context.metadata["current_graph_event"] = previous_event
        self._publish_external_context()
        return receipt

    def tick(self, frame_delta_seconds: float) -> GraphTickReceipt:
        frame_delta = _non_negative_finite(frame_delta_seconds, "Frame Delta Seconds")
        if self.paused:
            return GraphTickReceipt(
                "paused",
                0,
                0.0,
                0.0,
                self.accumulator_seconds,
                message="Graph execution is paused.",
            )
        if _event_key(self.entry_event) not in {"whileplaying", "tick", "update"}:
            return GraphTickReceipt(
                "idle",
                0,
                0.0,
                0.0,
                self.accumulator_seconds,
                message=f"{self.entry_event} is event-driven and does not run every frame.",
            )
        self._refresh_external_context()
        accepted_delta = min(frame_delta, self.max_frame_delta)
        dropped = max(0.0, frame_delta - accepted_delta)
        self.accumulator_seconds += accepted_delta
        executions: list[GraphExecutionReceipt] = []
        while (
            self.accumulator_seconds + 1.0e-12 >= self.fixed_step_seconds
            and len(executions) < self.max_substeps
        ):
            self.context.delta_seconds = self.fixed_step_seconds
            receipt = execute_graph_manifest(
                self.manifest,
                self.context,
                registry=self.registry,
                limits=self.limits,
            )
            executions.append(receipt)
            if not receipt.ok:
                break
            self.accumulator_seconds -= self.fixed_step_seconds
            self.elapsed_seconds += self.fixed_step_seconds
        if len(executions) == self.max_substeps:
            excess_steps = math.floor(
                (self.accumulator_seconds + 1.0e-12) / self.fixed_step_seconds
            )
            if excess_steps > 0:
                excess = excess_steps * self.fixed_step_seconds
                dropped += excess
                self.accumulator_seconds -= excess
        failed = next((receipt for receipt in executions if not receipt.ok), None)
        self._publish_external_context()
        return GraphTickReceipt(
            "failed" if failed else ("complete" if executions else "idle"),
            sum(1 for receipt in executions if receipt.ok),
            sum(self.fixed_step_seconds for receipt in executions if receipt.ok),
            dropped,
            max(0.0, self.accumulator_seconds),
            executions,
            failed.error["message"] if failed and failed.error else "",
        )

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)

    def reset_timing(self) -> None:
        self.accumulator_seconds = 0.0
        self.elapsed_seconds = 0.0
        self.begin_play_complete = False

    def hot_swap(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        try:
            self._validate_manifest(manifest)
        except ValueError as exc:
            return {
                "accepted": False,
                "message": str(exc),
                "program_id": self.manifest.get("program_id"),
            }
        previous_id = str(self.manifest.get("program_id") or "")
        incoming_id = str(manifest.get("program_id") or "")
        if incoming_id != previous_id:
            return {
                "accepted": False,
                "message": (
                    f"Hot swap expected program '{previous_id}', not '{incoming_id}'. "
                    "Create a separate runtime instance for a different program."
                ),
                "program_id": previous_id,
            }
        self.manifest = deepcopy(dict(manifest))
        return {
            "accepted": True,
            "message": "Graph update accepted; runtime state and timing were preserved.",
            "program_id": self.manifest.get("program_id"),
            "previous_program_id": previous_id,
        }

    def _refresh_external_context(self) -> None:
        external = self._external_context
        if external is None:
            return
        self.context.authority = str(external.get("authority") or self.context.authority)
        self.context.input_actions = deepcopy(
            dict(external.get("input_actions") or {})
        )
        self.context.actors = deepcopy(dict(external.get("actors") or {}))
        self.context.events = deepcopy(list(external.get("events") or []))
        self.context.graph_operations = dict(
            external.get("graph_operations") or self.context.graph_operations
        )
        self.context.metadata = deepcopy(dict(external.get("metadata") or {}))

    def _publish_external_context(self) -> None:
        external = self._external_context
        if external is None:
            return
        external["actors"] = deepcopy(self.context.actors)
        external["events"] = deepcopy(self.context.events)
        external["metadata"] = deepcopy(self.context.metadata)

    @staticmethod
    def _validate_manifest(manifest: Mapping[str, Any]) -> None:
        if not isinstance(manifest, Mapping):
            raise TypeError("Graph runtime instances require a manifest mapping.")
        if manifest.get("schema") != NATIVE_GRAPH_MANIFEST_SCHEMA:
            raise ValueError(f"Unsupported graph manifest schema: {manifest.get('schema')}")
        if manifest.get("abi") != NATIVE_GRAPH_ABI:
            raise ValueError(f"Unsupported graph ABI: {manifest.get('abi')}")
        if not bool(manifest.get("valid", False)):
            raise ValueError("Graph manifest must pass validation before it can run.")


def _idle_execution_receipt(
    program_id: str,
    message: str,
) -> GraphExecutionReceipt:
    return GraphExecutionReceipt(
        program_id=program_id,
        status="idle",
        committed=False,
        operation_count=0,
        elapsed_ms=0.0,
        error={"code": "event_not_active", "message": message},
    )


def _event_key(value: str) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _positive_finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{label} must be a positive finite value.")
    return result


def _non_negative_finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be a finite value of zero or greater.")
    return result


__all__ = ["GraphRuntimeInstance", "GraphTickReceipt"]
