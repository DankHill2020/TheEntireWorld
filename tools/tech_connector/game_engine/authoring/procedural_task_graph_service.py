from __future__ import annotations

"""Dependency-aware procedural work items for scalable content generation."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import itertools
import json
import time
from typing import Any, Callable, Iterable


TaskProcessor = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProceduralWorkItem:
    work_item_id: str
    node_id: str
    index: int
    attributes: dict[str, Any] = field(default_factory=dict)
    parent_ids: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        return _digest(asdict(self))


@dataclass
class ProceduralTaskNode:
    node_id: str
    processor: str = "passthrough"
    inputs: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    fan_out: int = 1
    partition_by: tuple[str, ...] = ()
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProceduralTaskGraph:
    graph_id: str
    nodes: dict[str, ProceduralTaskNode] = field(default_factory=dict)
    output_node: str = ""

    def add_node(
        self,
        node_id: str,
        processor: str = "passthrough",
        *,
        inputs: Iterable[str] = (),
        parameters: dict[str, Any] | None = None,
        fan_out: int = 1,
        partition_by: Iterable[str] = (),
    ) -> ProceduralTaskNode:
        if not node_id or node_id in self.nodes:
            raise ValueError(f"Task node ID is empty or already exists: {node_id}")
        node = ProceduralTaskNode(
            node_id=node_id,
            processor=processor,
            inputs=list(inputs),
            parameters=deepcopy(parameters or {}),
            fan_out=max(1, int(fan_out)),
            partition_by=tuple(str(value) for value in partition_by),
        )
        self.nodes[node_id] = node
        self.output_node = node_id
        return node

    def validate(self) -> list[str]:
        errors: list[str] = []
        for node in self.nodes.values():
            for source in node.inputs:
                if source not in self.nodes:
                    errors.append(f"{node.node_id}: missing input {source}")
        try:
            _task_order(self)
        except ValueError as exc:
            errors.append(str(exc))
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tc.procedural_task_graph.v1",
            "graph_id": self.graph_id,
            "nodes": [self.nodes[key].to_dict() for key in sorted(self.nodes)],
            "output_node": self.output_node,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProceduralTaskGraph":
        if str(data.get("schema") or "") != "tc.procedural_task_graph.v1":
            raise ValueError("Unsupported TC procedural task graph schema.")
        graph = cls(str(data.get("graph_id") or "procedural_tasks"))
        for row in data.get("nodes") or ():
            if not isinstance(row, dict):
                continue
            graph.add_node(
                str(row.get("node_id") or ""),
                str(row.get("processor") or "passthrough"),
                inputs=row.get("inputs") or (),
                parameters=dict(row.get("parameters") or {}),
                fan_out=int(row.get("fan_out", 1)),
                partition_by=row.get("partition_by") or (),
            ).enabled = bool(row.get("enabled", True))
        graph.output_node = str(data.get("output_node") or graph.output_node)
        return graph


@dataclass(frozen=True)
class WorkItemDiagnostic:
    work_item_id: str
    node_id: str
    elapsed_ms: float
    cache_hit: bool
    fingerprint: str
    state: str = "complete"
    message: str = ""


@dataclass
class ProceduralTaskCookResult:
    graph_id: str
    output_node: str
    work_items: list[ProceduralWorkItem]
    node_items: dict[str, list[ProceduralWorkItem]]
    diagnostics: list[WorkItemDiagnostic]

    @property
    def cache_hits(self) -> int:
        return sum(1 for row in self.diagnostics if row.cache_hit)


def _task_order(graph: ProceduralTaskGraph) -> list[str]:
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise ValueError(f"Procedural task graph cycle detected at {node_id}")
        visiting.add(node_id)
        for source in graph.nodes[node_id].inputs:
            if source in graph.nodes:
                visit(source)
        visiting.remove(node_id)
        visited.add(node_id)
        ordered.append(node_id)

    for node_id in sorted(graph.nodes):
        visit(node_id)
    return ordered


def wedge_parameters(values: dict[str, Iterable[Any]]) -> list[dict[str, Any]]:
    names = sorted(values)
    rows = [list(values[name]) for name in names]
    return [dict(zip(names, combination)) for combination in itertools.product(*rows)] if names else [{}]


def _passthrough(attributes: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    return {**attributes, **deepcopy(parameters.get("attributes") or {})}


class ProceduralTaskCooker:
    """Cook dependency work items locally while preserving a farm-ready contract."""

    def __init__(self, *, max_workers: int = 1) -> None:
        self.max_workers = max(1, int(max_workers))
        self.processors: dict[str, TaskProcessor] = {"passthrough": _passthrough}
        self._cache: dict[tuple[str, str], tuple[str, ProceduralWorkItem]] = {}

    def register_processor(self, name: str, processor: TaskProcessor) -> None:
        if not name or not callable(processor):
            raise ValueError("Task processors require a name and callable.")
        self.processors[name] = processor

    def clear(self, graph_id: str = "") -> None:
        if not graph_id:
            self._cache.clear()
            return
        for key in [key for key in self._cache if key[0] == graph_id]:
            self._cache.pop(key, None)

    @staticmethod
    def _partition(node: ProceduralTaskNode, parents: list[ProceduralWorkItem]) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
        if not node.partition_by:
            return [(deepcopy(parent.attributes), (parent.work_item_id,)) for parent in parents]
        groups: dict[tuple[Any, ...], list[ProceduralWorkItem]] = {}
        for parent in parents:
            key = tuple(parent.attributes.get(name) for name in node.partition_by)
            groups.setdefault(key, []).append(parent)
        rows: list[tuple[dict[str, Any], tuple[str, ...]]] = []
        for key, items in sorted(groups.items(), key=lambda row: repr(row[0])):
            attributes = {name: value for name, value in zip(node.partition_by, key)}
            attributes["partition_size"] = len(items)
            attributes["partition_items"] = [deepcopy(item.attributes) for item in items]
            rows.append((attributes, tuple(item.work_item_id for item in items)))
        return rows

    @staticmethod
    def _expand(node: ProceduralTaskNode, parents: list[ProceduralWorkItem]) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
        base = ProceduralTaskCooker._partition(node, parents)
        wedges = wedge_parameters(node.parameters.get("wedges") or {})
        rows: list[tuple[dict[str, Any], tuple[str, ...]]] = []
        for attributes, parent_ids in base:
            for fan_index in range(node.fan_out):
                for wedge_index, wedge in enumerate(wedges):
                    rows.append(({
                        **attributes,
                        **deepcopy(wedge),
                        "fan_index": fan_index,
                        "wedge_index": wedge_index,
                    }, parent_ids))
        return rows

    def cook(
        self,
        graph: ProceduralTaskGraph,
        *,
        initial_attributes: dict[str, Any] | None = None,
    ) -> ProceduralTaskCookResult:
        errors = graph.validate()
        if errors:
            raise ValueError("; ".join(errors))
        node_items: dict[str, list[ProceduralWorkItem]] = {}
        diagnostics: list[WorkItemDiagnostic] = []
        root = ProceduralWorkItem("root", "root", 0, deepcopy(initial_attributes or {}))
        for node_id in _task_order(graph):
            node = graph.nodes[node_id]
            parents = [item for source in node.inputs for item in node_items[source]] if node.inputs else [root]
            pending = self._expand(node, parents)
            processor = self.processors.get(node.processor)
            if processor is None:
                raise KeyError(f"Unknown procedural task processor: {node.processor}")

            def execute(row: tuple[int, tuple[dict[str, Any], tuple[str, ...]]]):
                index, (attributes, parent_ids) = row
                item_id = f"{node.node_id}:{index}"
                signature = _digest({
                    "node": node.to_dict(),
                    "attributes": attributes,
                    "parents": parent_ids,
                })
                started = time.perf_counter()
                cached = self._cache.get((graph.graph_id, item_id))
                cache_hit = bool(cached and cached[0] == signature)
                if cache_hit:
                    item = deepcopy(cached[1])
                else:
                    output = attributes if not node.enabled else processor(deepcopy(attributes), deepcopy(node.parameters))
                    item = ProceduralWorkItem(item_id, node.node_id, index, dict(output or {}), parent_ids)
                    self._cache[(graph.graph_id, item_id)] = (signature, deepcopy(item))
                diagnostic = WorkItemDiagnostic(
                    item_id,
                    node.node_id,
                    (time.perf_counter() - started) * 1000.0,
                    cache_hit,
                    item.fingerprint,
                )
                return index, item, diagnostic

            indexed = list(enumerate(pending))
            if self.max_workers > 1 and len(indexed) > 1:
                with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="TCProcedural") as pool:
                    completed = list(pool.map(execute, indexed))
            else:
                completed = [execute(row) for row in indexed]
            completed.sort(key=lambda row: row[0])
            node_items[node_id] = [row[1] for row in completed]
            diagnostics.extend(row[2] for row in completed)
        output_node = graph.output_node or (_task_order(graph)[-1] if graph.nodes else "")
        return ProceduralTaskCookResult(
            graph.graph_id,
            output_node,
            list(node_items.get(output_node, ())),
            node_items,
            diagnostics,
        )
