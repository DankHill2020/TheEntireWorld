"""Typed, bounded communication channels for effects, gameplay, and simulation graphs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
from typing import Any, Mapping, Sequence


_VALUE_TYPES = {"bool", "int", "float", "vec2", "vec3", "vec4", "color", "string", "id"}


@dataclass(frozen=True)
class FxChannelField:
    name: str
    value_type: str
    default: Any = None
    required: bool = True
    semantic: str = ""

    def validated(self) -> "FxChannelField":
        if not str(self.name).strip():
            raise ValueError("Data-channel fields require a name.")
        if self.value_type not in _VALUE_TYPES:
            raise ValueError(f"Unsupported data-channel value type: {self.value_type}")
        if self.default is not None:
            _coerce_value(self.default, self.value_type)
        return self


@dataclass(frozen=True)
class FxDataChannelSchema:
    channel_id: str
    fields: tuple[FxChannelField, ...]
    capacity: int = 4096
    scope: str = "world"
    retention_ticks: int = 2
    overflow_policy: str = "drop_oldest"

    def validated(self) -> "FxDataChannelSchema":
        if not str(self.channel_id).strip():
            raise ValueError("Data channels require an identifier.")
        if self.capacity <= 0 or self.retention_ticks < 0:
            raise ValueError("Data-channel capacity must be positive and retention cannot be negative.")
        if self.scope not in {"system", "world", "scene", "network"}:
            raise ValueError("Data-channel scope must be system, world, scene, or network.")
        if self.overflow_policy not in {"drop_oldest", "drop_newest", "error"}:
            raise ValueError("Unknown data-channel overflow policy.")
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("Data-channel field names must be unique.")
        for channel_field in self.fields:
            channel_field.validated()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"channel_id": self.channel_id, "fields": [asdict(item) for item in self.fields],
                "capacity": self.capacity, "scope": self.scope, "retention_ticks": self.retention_ticks,
                "overflow_policy": self.overflow_policy}


@dataclass(frozen=True)
class FxDataChannelEvent:
    sequence: int
    tick: int
    values: dict[str, Any]
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "tick": self.tick,
                "values": copy.deepcopy(self.values), "source": self.source}


@dataclass(frozen=True)
class FxDataChannelBinding:
    event_type: str
    channel_id: str
    source_emitter: str = "*"
    field_map: dict[str, str] = field(default_factory=dict)
    constants: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FxDataChannelConsumer:
    channel_id: str
    target_emitter: str
    spawn_count: int = 1
    spawn_count_field: str = ""
    position_field: str = "position"
    velocity_field: str = "velocity"
    velocity_scale: float = 1.0


@dataclass(frozen=True)
class FxGraphPort:
    name: str
    value_type: str
    default: Any = None

    def validated(self) -> "FxGraphPort":
        FxChannelField(self.name, self.value_type, self.default, False).validated()
        return self


@dataclass(frozen=True)
class FxGraphNode:
    node_id: str
    operation: str
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FxGraphConnection:
    source_node: str
    source_port: str
    target_node: str
    target_port: str


@dataclass(frozen=True)
class FxSubgraphDefinition:
    subgraph_id: str
    inputs: tuple[FxGraphPort, ...] = ()
    outputs: tuple[FxGraphPort, ...] = ()
    nodes: tuple[FxGraphNode, ...] = ()
    connections: tuple[FxGraphConnection, ...] = ()
    version: int = 1
    description: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.subgraph_id or self.version <= 0:
            errors.append("Subgraphs require an identifier and positive version.")
        for port in self.inputs + self.outputs:
            try: port.validated()
            except ValueError as exc: errors.append(str(exc))
        node_map = {node.node_id: node for node in self.nodes}
        if len(node_map) != len(self.nodes) or any(not key for key in node_map):
            errors.append("Subgraph node identifiers must be non-empty and unique.")
        incoming: dict[str, set[str]] = {key: set() for key in node_map}
        outgoing: dict[str, set[str]] = {key: set() for key in node_map}
        for connection in self.connections:
            source_type = self._port_type(connection.source_node, connection.source_port, node_map, output=True)
            target_type = self._port_type(connection.target_node, connection.target_port, node_map, output=False)
            if source_type is None:
                errors.append(f"Unknown source socket: {connection.source_node}.{connection.source_port}")
            if target_type is None:
                errors.append(f"Unknown target socket: {connection.target_node}.{connection.target_port}")
            if source_type is not None and target_type is not None and source_type != target_type:
                errors.append(f"Socket type mismatch: {source_type} -> {target_type}")
            if connection.source_node in node_map and connection.target_node in node_map:
                outgoing[connection.source_node].add(connection.target_node)
                incoming[connection.target_node].add(connection.source_node)
        ready = [key for key, dependencies in incoming.items() if not dependencies]
        visited = 0
        while ready:
            current = ready.pop()
            visited += 1
            for target in outgoing[current]:
                incoming[target].discard(current)
                if not incoming[target]: ready.append(target)
        if visited != len(node_map):
            errors.append("Subgraph contains a dependency cycle.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "tech_connector.fx_subgraph.v1", "subgraph_id": self.subgraph_id,
                "version": self.version, "description": self.description,
                "inputs": [asdict(item) for item in self.inputs], "outputs": [asdict(item) for item in self.outputs],
                "nodes": [asdict(item) for item in self.nodes],
                "connections": [asdict(item) for item in self.connections]}

    def _port_type(self, node_id: str, port_name: str, nodes: dict[str, FxGraphNode], *, output: bool) -> str | None:
        if node_id == "$input" and output:
            return next((item.value_type for item in self.inputs if item.name == port_name), None)
        if node_id == "$output" and not output:
            return next((item.value_type for item in self.outputs if item.name == port_name), None)
        node = nodes.get(node_id)
        sockets = node.outputs if output and node else node.inputs if node else {}
        return sockets.get(port_name)


@dataclass
class FxDataChannel:
    schema: FxDataChannelSchema
    events: list[FxDataChannelEvent] = field(default_factory=list)
    next_sequence: int = 0
    published_count: int = 0
    dropped_count: int = 0

    def __post_init__(self) -> None:
        self.schema.validated()

    def publish(self, values: Mapping[str, Any], *, tick: int, source: str = "") -> FxDataChannelEvent | None:
        payload = self._validated_payload(values)
        if len(self.events) >= self.schema.capacity:
            if self.schema.overflow_policy == "error":
                raise OverflowError(f"Data channel {self.schema.channel_id} is full.")
            self.dropped_count += 1
            if self.schema.overflow_policy == "drop_newest":
                return None
            del self.events[:len(self.events) - self.schema.capacity + 1]
        event = FxDataChannelEvent(self.next_sequence, max(0, int(tick)), payload, str(source))
        self.next_sequence += 1
        self.published_count += 1
        self.events.append(event)
        return event

    def read_since(self, sequence: int = -1, *, through_tick: int | None = None,
                   limit: int | None = None) -> list[FxDataChannelEvent]:
        result = [item for item in self.events if item.sequence > int(sequence)
                  and (through_tick is None or item.tick <= int(through_tick))]
        return result[:max(0, int(limit))] if limit is not None else result

    def expire(self, current_tick: int) -> int:
        if self.schema.retention_ticks == 0:
            minimum = int(current_tick)
        else:
            minimum = int(current_tick) - self.schema.retention_ticks
        before = len(self.events)
        self.events = [item for item in self.events if item.tick >= minimum]
        return before - len(self.events)

    def statistics(self) -> dict[str, Any]:
        return {"channel_id": self.schema.channel_id, "buffered": len(self.events),
                "capacity": self.schema.capacity, "published": self.published_count,
                "dropped": self.dropped_count, "next_sequence": self.next_sequence,
                "pressure": len(self.events) / max(1, self.schema.capacity)}

    def to_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        result = {"schema": "tech_connector.fx_data_channel.v1",
                  "definition": self.schema.to_dict(), "statistics": self.statistics()}
        if include_events:
            result["events"] = [item.to_dict() for item in self.events]
        return result

    def _validated_payload(self, values: Mapping[str, Any]) -> dict[str, Any]:
        supplied = dict(values)
        known = {item.name for item in self.schema.fields}
        unknown = sorted(set(supplied) - known)
        if unknown:
            raise ValueError(f"Unknown fields for {self.schema.channel_id}: {', '.join(unknown)}")
        result: dict[str, Any] = {}
        for channel_field in self.schema.fields:
            value = supplied.get(channel_field.name, channel_field.default)
            if value is None and channel_field.required:
                raise ValueError(f"Missing required channel field: {channel_field.name}")
            result[channel_field.name] = None if value is None else _coerce_value(value, channel_field.value_type)
        return result


def impact_data_channel(channel_id: str = "fx.impacts", *, capacity: int = 8192) -> FxDataChannel:
    return FxDataChannel(FxDataChannelSchema(channel_id, (
        FxChannelField("position", "vec3", (0.0, 0.0, 0.0), semantic="world_position"),
        FxChannelField("velocity", "vec3", (0.0, 0.0, 0.0), semantic="world_velocity"),
        FxChannelField("normal", "vec3", (0.0, 1.0, 0.0), semantic="surface_normal"),
        FxChannelField("magnitude", "float", 1.0),
        FxChannelField("surface", "string", "default", required=False),
        FxChannelField("source_id", "id", "", required=False),
    ), capacity=capacity, scope="world", retention_ticks=2))


def publish_bound_effect_events(system: Any, *, tick: int) -> list[dict[str, Any]]:
    """Map newly emitted effect events into shared typed channels."""
    published: list[dict[str, Any]] = []
    channels = getattr(system, "data_channels", {}) or {}
    for event in getattr(system, "emitted_events", ()) or ():
        for binding in getattr(system, "data_channel_bindings", ()) or ():
            if binding.event_type != str(event.get("type") or ""):
                continue
            emitter_id = str(event.get("emitter_id") or "")
            if binding.source_emitter not in {"", "*", emitter_id}:
                continue
            channel = channels.get(binding.channel_id)
            if channel is None:
                continue
            values = dict(binding.constants)
            for destination, source_key in binding.field_map.items():
                values[destination] = _nested_value(event, source_key)
            emitted = channel.publish(values, tick=tick, source=f"effect:{emitter_id}")
            if emitted is not None:
                published.append({"channel_id": binding.channel_id, **emitted.to_dict()})
    return published


def _nested_value(values: Mapping[str, Any], path: str) -> Any:
    result: Any = values
    for part in str(path).split("."):
        if not isinstance(result, Mapping) or part not in result:
            raise KeyError(f"Event payload does not contain {path}")
        result = result[part]
    return result


def _coerce_value(value: Any, value_type: str) -> Any:
    if value_type == "bool": return bool(value)
    if value_type == "int": return int(value)
    if value_type == "float": return float(value)
    if value_type in {"string", "id"}: return str(value)
    widths = {"vec2": 2, "vec3": 3, "vec4": 4, "color": 4}
    if value_type in widths:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != widths[value_type]:
            raise ValueError(f"{value_type} requires {widths[value_type]} components.")
        return tuple(float(item) for item in value)
    raise ValueError(f"Unsupported data-channel value type: {value_type}")


__all__ = ["FxChannelField", "FxDataChannel", "FxDataChannelBinding", "FxDataChannelConsumer", "FxDataChannelEvent",
           "FxDataChannelSchema", "FxGraphConnection", "FxGraphNode", "FxGraphPort",
           "FxSubgraphDefinition", "impact_data_channel", "publish_bound_effect_events"]
