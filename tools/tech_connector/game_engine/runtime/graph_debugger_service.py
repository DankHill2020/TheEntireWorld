"""Pausable, source-mapped debugging for compiled engine graph manifests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from threading import RLock
import time
from typing import Any, Mapping, MutableMapping

from .graph_execution_service import (
    GraphExecutionContext,
    GraphExecutionError,
    GraphNodeTrace,
    GraphOperationRegistry,
    NATIVE_GRAPH_ABI,
    NATIVE_GRAPH_MANIFEST_SCHEMA,
    create_default_graph_operation_registry,
)


@dataclass
class GraphDebugSnapshot:
    session_id: str
    instance_id: str
    program_id: str
    status: str
    pause_reason: str
    current_node_id: str
    next_node_id: str
    instruction_index: int
    instruction_count: int
    revision: int
    breakpoints: tuple[str, ...] = ()
    traces: list[GraphNodeTrace] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    watches: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "traces": [asdict(row) for row in self.traces],
            "outputs": deepcopy(self.outputs),
            "watches": deepcopy(self.watches),
            "runtime_state": deepcopy(self.runtime_state),
            "error": deepcopy(self.error),
        }


class GraphDebugSession:
    """Own one debuggable graph instance with breakpoints and staged node execution."""

    def __init__(
        self, session_id: str, instance_id: str, manifest: Mapping[str, Any],
        context: GraphExecutionContext | Mapping[str, Any], *, registry: GraphOperationRegistry | None = None,
    ) -> None:
        _validate_manifest(manifest)
        self.session_id = str(session_id)
        self.instance_id = str(instance_id)
        self.manifest = deepcopy(dict(manifest))
        self._external_context = context if isinstance(context, MutableMapping) else None
        self.context = GraphExecutionContext.from_value(context)
        self._initial_context = self.context.staged_copy()
        self.registry = registry or create_default_graph_operation_registry()
        self.breakpoints: set[str] = set()
        self.watch_paths: list[str] = []
        self.outputs: dict[str, Any] = {}
        self.traces: list[GraphNodeTrace] = []
        self.index = 0
        self.status = "idle"
        self.pause_reason = ""
        self.error: dict[str, Any] | None = None
        self.revision = 1
        self._lock = RLock()

    @property
    def program_id(self) -> str:
        return str(self.manifest.get("program_id") or "graph_program")

    @property
    def execution_order(self) -> list[str]:
        return [str(row) for row in self.manifest.get("execution_order") or ()]

    def set_breakpoints(self, node_ids) -> GraphDebugSnapshot:
        known = set(self.execution_order)
        requested = {str(row) for row in node_ids if str(row)}
        unknown = sorted(requested - known)
        if unknown:
            raise KeyError("Unknown graph breakpoint nodes: " + ", ".join(unknown))
        self.breakpoints = requested
        return self.snapshot()

    def set_watches(self, paths) -> GraphDebugSnapshot:
        self.watch_paths = list(dict.fromkeys(str(row).strip() for row in paths if str(row).strip()))
        return self.snapshot()

    def start(self) -> GraphDebugSnapshot:
        with self._lock:
            if self.status in {"complete", "failed", "stopped"}:
                self.restart()
            self.status = "running"; self.pause_reason = ""; self.error = None
            return self._run_until_pause()

    def continue_execution(self) -> GraphDebugSnapshot:
        with self._lock:
            if self.status in {"complete", "failed", "stopped"}:
                return self.snapshot()
            skip_node = self._next_node_id() if self.status == "paused" and self.pause_reason == "breakpoint" else ""
            self.status = "running"; self.pause_reason = ""
            return self._run_until_pause(skip_breakpoint=skip_node)

    def step(self) -> GraphDebugSnapshot:
        with self._lock:
            if self.status in {"complete", "failed", "stopped"}:
                return self.snapshot()
            self.status = "running"; self.pause_reason = ""
            self._execute_next()
            if self.status == "running":
                if self.index >= len(self.execution_order):
                    self.status = "complete"
                else:
                    self.status = "paused"; self.pause_reason = "step"
            return self.snapshot()

    def pause(self) -> GraphDebugSnapshot:
        with self._lock:
            if self.status in {"idle", "running"}:
                self.status = "paused"; self.pause_reason = "user"
            return self.snapshot()

    def restart(self) -> GraphDebugSnapshot:
        with self._lock:
            self.context = self._initial_context.staged_copy(); self.outputs.clear(); self.traces.clear(); self.index = 0
            self.status = "idle"; self.pause_reason = ""; self.error = None; self.revision += 1
            self._publish_external_context()
            return self.snapshot()

    def stop(self, *, keep_changes: bool = False) -> GraphDebugSnapshot:
        with self._lock:
            if not keep_changes:
                self.context = self._initial_context.staged_copy()
            self.status = "stopped"; self.pause_reason = "user"; self.revision += 1
            self._publish_external_context()
            return self.snapshot()

    def hot_swap(self, manifest: Mapping[str, Any]) -> GraphDebugSnapshot:
        with self._lock:
            _validate_manifest(manifest)
            incoming = str(manifest.get("program_id") or "")
            if incoming != self.program_id:
                raise ValueError(f"Hot swap expected program '{self.program_id}', not '{incoming}'.")
            last_node = self.traces[-1].node_id if self.traces else ""
            self.manifest = deepcopy(dict(manifest))
            order = self.execution_order
            self.index = order.index(last_node) + 1 if last_node in order else min(self.index, len(order))
            self.breakpoints.intersection_update(order)
            self.status = "paused" if self.index < len(order) else "complete"
            self.pause_reason = "hot_swap"; self.error = None; self.revision += 1
            return self.snapshot()

    def snapshot(self) -> GraphDebugSnapshot:
        return GraphDebugSnapshot(
            self.session_id, self.instance_id, self.program_id, self.status, self.pause_reason,
            self.traces[-1].node_id if self.traces else "", self._next_node_id(), self.index,
            len(self.execution_order), self.revision, tuple(sorted(self.breakpoints)), list(self.traces),
            deepcopy(self.outputs), {path: _watch_value(path, self.context, self.outputs) for path in self.watch_paths},
            {"actors": deepcopy(self.context.actors), "events": deepcopy(self.context.events), "metadata": deepcopy(self.context.metadata)},
            deepcopy(self.error),
        )

    def _run_until_pause(self, *, skip_breakpoint: str = "") -> GraphDebugSnapshot:
        while self.status == "running" and self.index < len(self.execution_order):
            node_id = self._next_node_id()
            if node_id in self.breakpoints and node_id != skip_breakpoint:
                self.status = "paused"; self.pause_reason = "breakpoint"; break
            skip_breakpoint = ""
            self._execute_next()
        if self.status == "running" and self.index >= len(self.execution_order):
            self.status = "complete"; self.pause_reason = ""
        return self.snapshot()

    def _execute_next(self) -> None:
        order = self.execution_order
        if self.index >= len(order):
            self.status = "complete"; return
        node_id = order[self.index]
        nodes = {str(row.get("node_id") or ""): dict(row) for row in self.manifest.get("nodes") or () if isinstance(row, Mapping)}
        node = nodes.get(node_id)
        if node is None:
            self._fail(GraphExecutionError("missing_node", f"Execution references missing node '{node_id}'.", node_id=node_id)); return
        operation = str(node.get("operation") or "")
        handler = self.context.graph_operations.get(operation) or self.registry.resolve(operation)
        if handler is None:
            self._fail(GraphExecutionError("operation_unavailable", f"Operation '{operation}' is not installed.", node_id=node_id, operation=operation)); return
        allowed = tuple(str(row) for row in dict(self.manifest.get("operation_contracts") or {}).get(node_id, {}).get("authorities") or ())
        if allowed and self.context.authority not in allowed:
            self._fail(GraphExecutionError("authority_denied", f"{operation} allows {', '.join(allowed)} authority, not {self.context.authority}.", node_id=node_id, operation=operation)); return
        try:
            inputs = _resolve_inputs(node, self.outputs)
            staged = self.context.staged_copy(); started = time.perf_counter(); result = handler(context=staged, **inputs)
            self.context.commit_from(staged); self._publish_external_context(); self.outputs[node_id] = result
            self.traces.append(GraphNodeTrace(node_id, operation, (time.perf_counter() - started) * 1000.0, tuple(sorted(inputs)), _summarize(result)))
            self.index += 1; self.revision += 1
        except GraphExecutionError as exc:
            self._fail(exc)
        except Exception as exc:
            self._fail(GraphExecutionError("operation_failed", f"{operation} failed: {exc}", node_id=node_id, operation=operation))

    def _fail(self, error: GraphExecutionError) -> None:
        self.status = "failed"; self.pause_reason = "error"; self.error = error.to_dict(); self.revision += 1

    def _next_node_id(self) -> str:
        order = self.execution_order
        return order[self.index] if self.index < len(order) else ""

    def _publish_external_context(self) -> None:
        if self._external_context is None:
            return
        self._external_context["actors"] = deepcopy(self.context.actors)
        self._external_context["events"] = deepcopy(self.context.events)
        self._external_context["metadata"] = deepcopy(self.context.metadata)


class GraphDebugSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, GraphDebugSession] = {}
        self._lock = RLock()

    def attach(self, session_id: str, instance_id: str, manifest: Mapping[str, Any], context: Mapping[str, Any] | GraphExecutionContext) -> GraphDebugSession:
        session = GraphDebugSession(session_id, instance_id, manifest, context)
        with self._lock:
            self._sessions[str(session_id)] = session
        return session

    def session(self, session_id: str) -> GraphDebugSession:
        with self._lock:
            session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"Unknown graph debug session: {session_id}")
        return session

    def list_sessions(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            sessions = tuple(self._sessions.values())
        return tuple(session.snapshot().to_dict() for session in sessions)

    def detach(self, session_id: str, *, keep_changes: bool = False) -> GraphDebugSnapshot:
        with self._lock:
            session = self._sessions.pop(str(session_id), None)
        if session is None:
            raise KeyError(f"Unknown graph debug session: {session_id}")
        return session.stop(keep_changes=keep_changes)


_DEFAULT_DEBUG_SESSION_MANAGER = GraphDebugSessionManager()


def default_graph_debug_session_manager() -> GraphDebugSessionManager:
    """Return the process-wide registry shared by editor windows and Python automation."""
    return _DEFAULT_DEBUG_SESSION_MANAGER


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != NATIVE_GRAPH_MANIFEST_SCHEMA or manifest.get("abi") != NATIVE_GRAPH_ABI:
        raise ValueError("Graph debugger requires a supported native graph manifest.")
    if not manifest.get("valid"):
        raise ValueError("Graph debugger cannot attach to an invalid graph manifest.")


def _resolve_inputs(node: Mapping[str, Any], outputs: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, raw in dict(node.get("inputs") or {}).items():
        binding = dict(raw or {})
        if binding.get("mode") == "link":
            source = str(binding.get("source_node") or "")
            if source not in outputs:
                raise GraphExecutionError("source_value_unavailable", f"{name} needs output from '{source}'.", node_id=str(node.get("node_id") or ""), operation=str(node.get("operation") or ""))
            values[str(name)] = deepcopy(outputs[source])
        else:
            values[str(name)] = deepcopy(binding.get("literal"))
    return values


def _watch_value(path: str, context: GraphExecutionContext, outputs: Mapping[str, Any]) -> Any:
    root: Any = {"actors": context.actors, "events": context.events, "metadata": context.metadata, "outputs": outputs}
    for part in str(path).split("."):
        if isinstance(root, Mapping) and part in root:
            root = root[part]
        elif isinstance(root, (list, tuple)) and part.isdigit() and int(part) < len(root):
            root = root[int(part)]
        else:
            return "<unavailable>"
    return deepcopy(root)


def _summarize(value: Any) -> str:
    rendered = repr(value)
    return rendered if len(rendered) <= 160 else rendered[:157] + "..."


__all__ = ["GraphDebugSession", "GraphDebugSessionManager", "GraphDebugSnapshot", "default_graph_debug_session_manager"]
