from __future__ import annotations

"""Deterministic reference runtime for compiled TC graph manifests."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
from threading import RLock
import time
from typing import Any, Callable, Mapping, MutableMapping


NATIVE_GRAPH_MANIFEST_SCHEMA = "tech_connector.native_graph_manifest.v1"
NATIVE_GRAPH_ABI = "tc_graph_c_v1"

GraphOperationHandler = Callable[..., Any]
CancellationCheck = Callable[[], bool]


class GraphExecutionError(RuntimeError):
    """Structured graph failure that retains the responsible node and operation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        node_id: str = "",
        operation: str = "",
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.node_id = str(node_id)
        self.operation = str(operation)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": str(self),
            "node_id": self.node_id,
            "operation": self.operation,
        }


@dataclass(frozen=True)
class GraphExecutionLimits:
    max_operations: int = 4096
    max_elapsed_ms: float = 100.0
    max_events: int = 1024

    def __post_init__(self) -> None:
        if self.max_operations < 1:
            raise ValueError("Graph operation budget must be at least one.")
        if not math.isfinite(self.max_elapsed_ms) or self.max_elapsed_ms <= 0.0:
            raise ValueError("Graph time budget must be a positive finite number.")
        if self.max_events < 0:
            raise ValueError("Graph event budget cannot be negative.")


@dataclass
class GraphExecutionContext:
    delta_seconds: float = 1.0 / 60.0
    authority: str = "local"
    input_actions: dict[str, Any] = field(default_factory=dict)
    actors: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    graph_operations: dict[str, GraphOperationHandler] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.delta_seconds = float(self.delta_seconds)
        if not math.isfinite(self.delta_seconds) or self.delta_seconds < 0.0:
            raise ValueError("Delta Seconds must be a finite value of zero or greater.")
        self.authority = str(self.authority or "local")

    @classmethod
    def from_value(cls, value: "GraphExecutionContext | Mapping[str, Any]") -> "GraphExecutionContext":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("Graph execution context must be GraphExecutionContext or a mapping.")
        return cls(
            delta_seconds=float(value.get("delta_seconds", 1.0 / 60.0)),
            authority=str(value.get("authority") or "local"),
            input_actions=deepcopy(dict(value.get("input_actions") or {})),
            actors=deepcopy(dict(value.get("actors") or {})),
            events=deepcopy(list(value.get("events") or [])),
            graph_operations=dict(value.get("graph_operations") or {}),
            metadata=deepcopy(dict(value.get("metadata") or {})),
        )

    def staged_copy(self) -> "GraphExecutionContext":
        return GraphExecutionContext(
            delta_seconds=self.delta_seconds,
            authority=self.authority,
            input_actions=deepcopy(self.input_actions),
            actors=deepcopy(self.actors),
            events=deepcopy(self.events),
            graph_operations=dict(self.graph_operations),
            metadata=deepcopy(self.metadata),
        )

    def commit_from(self, staged: "GraphExecutionContext") -> None:
        self.actors = staged.actors
        self.events = staged.events
        self.metadata = staged.metadata


@dataclass(frozen=True)
class GraphNodeTrace:
    node_id: str
    operation: str
    elapsed_ms: float
    input_names: tuple[str, ...]
    output_summary: str


@dataclass
class GraphExecutionReceipt:
    program_id: str
    status: str
    committed: bool
    operation_count: int
    elapsed_ms: float
    traces: list[GraphNodeTrace] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    events_emitted: int = 0
    error: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "complete" and self.committed

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.graph_execution_receipt.v1",
            "program_id": self.program_id,
            "status": self.status,
            "committed": self.committed,
            "operation_count": self.operation_count,
            "elapsed_ms": self.elapsed_ms,
            "traces": [asdict(trace) for trace in self.traces],
            "outputs": deepcopy(self.outputs),
            "events_emitted": self.events_emitted,
            "error": deepcopy(self.error),
        }


class GraphOperationRegistry:
    """Thread-safe operation table used by editor previews and native parity tests."""

    def __init__(self) -> None:
        self._handlers: dict[str, GraphOperationHandler] = {}
        self._lock = RLock()

    def register(
        self,
        operation: str,
        handler: GraphOperationHandler,
        *,
        replace: bool = False,
    ) -> None:
        key = str(operation).strip()
        if not key or not callable(handler):
            raise ValueError("Graph operations require a non-empty key and callable handler.")
        with self._lock:
            if key in self._handlers and not replace:
                raise KeyError(f"Graph operation '{key}' is already registered.")
            self._handlers[key] = handler

    def resolve(self, operation: str) -> GraphOperationHandler | None:
        with self._lock:
            return self._handlers.get(str(operation))

    def operation_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))


def create_default_graph_operation_registry() -> GraphOperationRegistry:
    registry = GraphOperationRegistry()
    registry.register("input.read_axis", _read_input_action)
    registry.register("movement.calculate_velocity", _calculate_movement_velocity)
    registry.register("actor.set_velocity", _set_actor_velocity)
    registry.register("event.emit", _emit_gameplay_event)
    registry.register("variable.set", _set_variable)
    registry.register("variable.add", _add_variable)
    registry.register("branch.greater", _branch_greater)
    registry.register("entity.spawn", _spawn_entity)
    registry.register("component.get_position", _get_component_position)
    registry.register("component.set_position", _set_component_position)
    registry.register("ui.set_text", _set_runtime_ui_text)
    registry.register("audio.play", _play_audio)
    registry.register("save.write", _request_save)
    return registry


def execute_graph_manifest(
    manifest: Mapping[str, Any],
    context: GraphExecutionContext | MutableMapping[str, Any],
    *,
    registry: GraphOperationRegistry | None = None,
    limits: GraphExecutionLimits | None = None,
    cancellation_check: CancellationCheck | None = None,
    raise_on_error: bool = False,
) -> GraphExecutionReceipt:
    """Execute a manifest transactionally and return a source-mapped receipt."""

    started = time.perf_counter()
    source_context = GraphExecutionContext.from_value(context)
    staged = source_context.staged_copy()
    operation_registry = registry or create_default_graph_operation_registry()
    execution_limits = limits or GraphExecutionLimits()
    traces: list[GraphNodeTrace] = []
    outputs: dict[str, Any] = {}
    initial_event_count = len(staged.events)
    program_id = str(manifest.get("program_id") or "graph_program")
    try:
        _validate_manifest_header(manifest)
        nodes = {
            str(node.get("node_id") or ""): dict(node)
            for node in manifest.get("nodes") or ()
            if isinstance(node, Mapping)
        }
        execution_order = [str(item) for item in manifest.get("execution_order") or ()]
        contracts = dict(manifest.get("operation_contracts") or {})
        if len(execution_order) > execution_limits.max_operations:
            raise GraphExecutionError(
                "operation_budget_exceeded",
                f"Graph contains {len(execution_order)} operations; this run allows {execution_limits.max_operations}.",
            )
        for node_id in execution_order:
            _check_runtime_limits(
                started,
                execution_limits,
                len(traces),
                cancellation_check,
            )
            node = nodes.get(node_id)
            if node is None:
                raise GraphExecutionError(
                    "missing_node",
                    f"Execution order references missing node '{node_id}'.",
                    node_id=node_id,
                )
            if not bool(node.get("enabled", True)):
                continue
            operation = str(node.get("operation") or "")
            _check_authority(staged.authority, contracts.get(node_id), node_id, operation)
            handler = staged.graph_operations.get(operation) or operation_registry.resolve(operation)
            if handler is None:
                raise GraphExecutionError(
                    "operation_unavailable",
                    f"Operation '{operation}' is not installed in this runtime.",
                    node_id=node_id,
                    operation=operation,
                )
            resolved_inputs = _resolve_node_inputs(node, outputs)
            node_started = time.perf_counter()
            try:
                result = handler(context=staged, **resolved_inputs)
            except GraphExecutionError as exc:
                if exc.node_id and exc.operation:
                    raise
                raise GraphExecutionError(
                    exc.code,
                    str(exc),
                    node_id=exc.node_id or node_id,
                    operation=exc.operation or operation,
                ) from exc
            except Exception as exc:
                raise GraphExecutionError(
                    "operation_failed",
                    f"{operation} failed: {exc}",
                    node_id=node_id,
                    operation=operation,
                ) from exc
            outputs[node_id] = result
            traces.append(
                GraphNodeTrace(
                    node_id=node_id,
                    operation=operation,
                    elapsed_ms=_elapsed_ms(node_started),
                    input_names=tuple(sorted(resolved_inputs)),
                    output_summary=_summarize_value(result),
                )
            )
            _check_after_operation(started, execution_limits, cancellation_check)
            if len(staged.events) - initial_event_count > execution_limits.max_events:
                raise GraphExecutionError(
                    "event_budget_exceeded",
                    f"Graph emitted more than {execution_limits.max_events} events in one run.",
                    node_id=node_id,
                    operation=operation,
                )
        _commit_context(context, source_context, staged)
        return GraphExecutionReceipt(
            program_id=program_id,
            status="complete",
            committed=True,
            operation_count=len(traces),
            elapsed_ms=_elapsed_ms(started),
            traces=traces,
            outputs=outputs,
            events_emitted=len(staged.events) - initial_event_count,
        )
    except GraphExecutionError as exc:
        receipt = GraphExecutionReceipt(
            program_id=program_id,
            status="canceled" if exc.code == "canceled" else "failed",
            committed=False,
            operation_count=len(traces),
            elapsed_ms=_elapsed_ms(started),
            traces=traces,
            outputs=outputs,
            events_emitted=0,
            error=exc.to_dict(),
        )
        if raise_on_error:
            raise
        return receipt


def _validate_manifest_header(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != NATIVE_GRAPH_MANIFEST_SCHEMA:
        raise GraphExecutionError(
            "unsupported_schema",
            f"Expected {NATIVE_GRAPH_MANIFEST_SCHEMA}; received {manifest.get('schema') or 'no schema'}.",
        )
    if manifest.get("abi") != NATIVE_GRAPH_ABI:
        raise GraphExecutionError(
            "unsupported_abi",
            f"Expected {NATIVE_GRAPH_ABI}; received {manifest.get('abi') or 'no ABI'}.",
        )
    if not bool(manifest.get("valid", False)):
        raise GraphExecutionError(
            "invalid_manifest",
            "The graph manifest did not pass authoring validation.",
        )


def _resolve_node_inputs(
    node: Mapping[str, Any],
    outputs: Mapping[str, Any],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for input_name, raw_binding in dict(node.get("inputs") or {}).items():
        binding = dict(raw_binding or {})
        if binding.get("mode") == "link":
            source_node = str(binding.get("source_node") or "")
            if source_node not in outputs:
                raise GraphExecutionError(
                    "source_value_unavailable",
                    f"{input_name} needs output from '{source_node}', but that node has not produced a value.",
                    node_id=str(node.get("node_id") or ""),
                    operation=str(node.get("operation") or ""),
                )
            resolved[str(input_name)] = outputs[source_node]
        else:
            resolved[str(input_name)] = deepcopy(binding.get("literal"))
    return resolved


def _check_runtime_limits(
    started: float,
    limits: GraphExecutionLimits,
    operation_count: int,
    cancellation_check: CancellationCheck | None,
) -> None:
    if cancellation_check is not None and cancellation_check():
        raise GraphExecutionError("canceled", "Graph execution was canceled before the next operation.")
    if operation_count >= limits.max_operations:
        raise GraphExecutionError(
            "operation_budget_exceeded",
            f"Graph exceeded its {limits.max_operations}-operation budget.",
        )
    if _elapsed_ms(started) > limits.max_elapsed_ms:
        raise GraphExecutionError(
            "time_budget_exceeded",
            f"Graph exceeded its {limits.max_elapsed_ms:g} ms execution budget.",
        )


def _check_after_operation(
    started: float,
    limits: GraphExecutionLimits,
    cancellation_check: CancellationCheck | None,
) -> None:
    if cancellation_check is not None and cancellation_check():
        raise GraphExecutionError(
            "canceled",
            "Graph execution was canceled before its staged changes were committed.",
        )
    if _elapsed_ms(started) > limits.max_elapsed_ms:
        raise GraphExecutionError(
            "time_budget_exceeded",
            f"Graph exceeded its {limits.max_elapsed_ms:g} ms execution budget.",
        )


def _check_authority(
    authority: str,
    raw_contract: Any,
    node_id: str,
    operation: str,
) -> None:
    contract = dict(raw_contract or {})
    allowed = tuple(str(item) for item in contract.get("authorities") or ())
    if allowed and authority not in allowed:
        raise GraphExecutionError(
            "authority_denied",
            f"{operation} allows {', '.join(allowed)} authority, not {authority}.",
            node_id=node_id,
            operation=operation,
        )


def _read_input_action(
    *,
    context: GraphExecutionContext,
    axis: str = "Move",
) -> tuple[float, float]:
    action = str(axis or "Move")
    raw = context.input_actions.get(action, (0.0, 0.0))
    values = _finite_vector(raw, 2, f"Input action '{action}'")
    return tuple(max(-1.0, min(1.0, component)) for component in values)


def _calculate_movement_velocity(
    *,
    context: GraphExecutionContext,
    direction: Any,
    speed: float = 6.0,
    acceleration: float = 24.0,
    target: str = "Self",
) -> tuple[float, float, float]:
    x, y = _finite_vector(direction, 2, "Movement direction")
    magnitude = math.hypot(x, y)
    if magnitude > 1.0:
        x, y = x / magnitude, y / magnitude
    maximum_speed = _non_negative_finite(speed, "Movement Speed")
    acceleration_value = _non_negative_finite(acceleration, "Acceleration")
    desired = (x * maximum_speed, 0.0, y * maximum_speed)
    actor = context.actors.get(str(target), {})
    current = _finite_vector(actor.get("velocity", (0.0, 0.0, 0.0)), 3, "Current velocity")
    maximum_change = acceleration_value * context.delta_seconds
    return _move_toward(current, desired, maximum_change)


def _set_actor_velocity(
    *,
    context: GraphExecutionContext,
    target: str = "Self",
    velocity: Any,
) -> None:
    actor_id = str(target or "Self")
    actor = context.actors.get(actor_id)
    if actor is None:
        raise GraphExecutionError(
            "actor_not_found",
            f"Actor '{actor_id}' is not present in the execution context.",
            operation="actor.set_velocity",
        )
    actor["velocity"] = _finite_vector(velocity, 3, "Velocity")


def _emit_gameplay_event(
    *,
    context: GraphExecutionContext,
    event: str,
    payload: Mapping[str, Any] | None = None,
) -> None:
    event_name = str(event).strip()
    if not event_name:
        raise GraphExecutionError(
            "event_name_required",
            "Gameplay events need a readable event name.",
            operation="event.emit",
        )
    if payload is not None and not isinstance(payload, Mapping):
        raise GraphExecutionError(
            "invalid_event_payload",
            "Event Details must be a mapping.",
            operation="event.emit",
        )
    context.events.append(
        {
            "event": event_name,
            "payload": deepcopy(dict(payload or {})),
            "authority": context.authority,
        }
    )


def _variables(context: GraphExecutionContext) -> dict[str, Any]:
    value = context.metadata.setdefault("variables", {})
    if not isinstance(value, dict):
        raise GraphExecutionError("invalid_variables", "Runtime variables must be stored as named values.")
    return value


def _set_variable(*, context: GraphExecutionContext, name: str, value: Any) -> Any:
    variable_name = str(name).strip()
    if not variable_name:
        raise GraphExecutionError("variable_name_required", "Variables need a readable name.", operation="variable.set")
    _variables(context)[variable_name] = deepcopy(value)
    return deepcopy(value)


def _add_variable(*, context: GraphExecutionContext, name: str, amount: float = 1.0) -> float:
    variable_name = str(name).strip()
    variables = _variables(context)
    current = float(variables.get(variable_name, 0.0))
    increment = float(amount)
    if not math.isfinite(current) or not math.isfinite(increment):
        raise GraphExecutionError("invalid_number", "Variable arithmetic requires finite numbers.", operation="variable.add")
    variables[variable_name] = current + increment
    return variables[variable_name]


def _branch_greater(*, context: GraphExecutionContext, name: str, threshold: float, event: str = "") -> bool:
    value = float(_variables(context).get(str(name), 0.0))
    result = value > float(threshold)
    if result and str(event).strip():
        _emit_gameplay_event(context=context, event=str(event))
    return result


def _spawn_entity(
    *, context: GraphExecutionContext, name: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
) -> str:
    entity_name = str(name).strip()
    if not entity_name:
        raise GraphExecutionError("entity_name_required", "Spawn Entity needs a readable name.", operation="entity.spawn")
    if entity_name in context.actors:
        raise GraphExecutionError("entity_exists", f"Entity '{entity_name}' already exists.", operation="entity.spawn")
    context.actors[entity_name] = {"position": _finite_vector((x, y, z), 3, "Position"), "velocity": (0.0, 0.0, 0.0)}
    return entity_name


def _get_component_position(*, context: GraphExecutionContext, target: str = "Self") -> tuple[float, float, float]:
    actor = context.actors.get(str(target))
    if actor is None:
        raise GraphExecutionError("actor_not_found", f"Actor '{target}' is not present.", operation="component.get_position")
    return _finite_vector(actor.get("position", (0.0, 0.0, 0.0)), 3, "Position")


def _set_component_position(
    *, context: GraphExecutionContext, target: str = "Self", x: float = 0.0, y: float = 0.0, z: float = 0.0,
) -> None:
    actor = context.actors.get(str(target))
    if actor is None:
        raise GraphExecutionError("actor_not_found", f"Actor '{target}' is not present.", operation="component.set_position")
    actor["position"] = _finite_vector((x, y, z), 3, "Position")


def _set_runtime_ui_text(*, context: GraphExecutionContext, text: str) -> str:
    context.metadata["hud_text"] = str(text)
    return str(text)


def _play_audio(*, context: GraphExecutionContext, asset: str) -> None:
    audio_asset = str(asset).strip()
    if not audio_asset:
        raise GraphExecutionError("audio_asset_required", "Play Audio needs an audio asset.", operation="audio.play")
    context.events.append({"event": "Audio", "payload": {"asset": audio_asset}, "authority": context.authority})


def _request_save(*, context: GraphExecutionContext) -> None:
    context.events.append({"event": "SaveRequested", "payload": {}, "authority": context.authority})


def _finite_vector(value: Any, size: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"{label} must contain exactly {size} numeric values.")
    result = tuple(float(component) for component in value)
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{label} must contain only finite values.")
    return result


def _non_negative_finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be a finite value of zero or greater.")
    return result


def _move_toward(
    current: tuple[float, ...],
    target: tuple[float, ...],
    maximum_change: float,
) -> tuple[float, ...]:
    delta = tuple(destination - source for source, destination in zip(current, target))
    distance = math.sqrt(sum(component * component for component in delta))
    if distance <= maximum_change or distance <= 1.0e-9:
        return target
    scale = maximum_change / distance
    return tuple(source + component * scale for source, component in zip(current, delta))


def _commit_context(
    original: GraphExecutionContext | MutableMapping[str, Any],
    source: GraphExecutionContext,
    staged: GraphExecutionContext,
) -> None:
    source.commit_from(staged)
    if isinstance(original, GraphExecutionContext):
        return
    original["actors"] = deepcopy(source.actors)
    original["events"] = deepcopy(source.events)
    original["metadata"] = deepcopy(source.metadata)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 4)


def _summarize_value(value: Any) -> str:
    if value is None:
        return "No output"
    if isinstance(value, (str, int, float, bool)):
        return repr(value)[:120]
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}[{len(value)}] {repr(value)[:96]}"
    if isinstance(value, Mapping):
        return f"mapping[{len(value)}]"
    return type(value).__name__


__all__ = [
    "GraphExecutionContext",
    "GraphExecutionError",
    "GraphExecutionLimits",
    "GraphExecutionReceipt",
    "GraphNodeTrace",
    "GraphOperationRegistry",
    "NATIVE_GRAPH_ABI",
    "NATIVE_GRAPH_MANIFEST_SCHEMA",
    "create_default_graph_operation_registry",
    "execute_graph_manifest",
]
