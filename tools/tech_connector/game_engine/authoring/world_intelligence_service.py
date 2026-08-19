from __future__ import annotations

"""Serializable world-intelligence assets shared by authoring and runtime."""

from dataclasses import asdict, dataclass, field
from typing import Any


WORLD_INTELLIGENCE_SCHEMA = "tech_connector.world_intelligence.v1"


@dataclass(frozen=True)
class PerceptionSensor:
    sensor_id: str
    modality: str
    range: float = 25.0
    field_of_view: float = 360.0
    sensitivity: float = 1.0
    accepted_tags: tuple[str, ...] = ()
    blocked_tags: tuple[str, ...] = ()
    memory_duration: float = 10.0


@dataclass(frozen=True)
class NavNode:
    node_id: str
    position: tuple[float, float, float]
    tags: tuple[str, ...] = ()
    capacity: int = 1


@dataclass(frozen=True)
class NavEdge:
    source: str
    target: str
    cost: float = 1.0
    bidirectional: bool = True
    required_tags: tuple[str, ...] = ()
    blocked: bool = False


@dataclass
class NavigationGraph:
    graph_id: str
    nodes: dict[str, NavNode] = field(default_factory=dict)
    edges: list[NavEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SmartObjectSlot:
    slot_id: str
    actions: tuple[str, ...]
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    capacity: int = 1
    tags: tuple[str, ...] = ()
    required_character_tags: tuple[str, ...] = ()


@dataclass
class SmartObjectDefinition:
    object_id: str
    slots: dict[str, SmartObjectSlot] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BehaviorNode:
    node_id: str
    kind: str
    children: tuple[str, ...] = ()
    conditions: tuple[dict[str, Any], ...] = ()
    action_id: str = ""
    utility: float = 0.0
    parameter_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class BehaviorGraph:
    graph_id: str
    root_node: str
    nodes: dict[str, BehaviorNode] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DialogueAct:
    act_id: str
    intent: str
    authored_text: str
    conditions: tuple[dict[str, Any], ...] = ()
    effects: dict[str, Any] = field(default_factory=dict)
    priority: float = 0.5
    tags: tuple[str, ...] = ()
    allow_model_realization: bool = False


@dataclass
class DialogueSet:
    set_id: str
    acts: dict[str, DialogueAct] = field(default_factory=dict)
    fallback_act: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CharacterGroup:
    group_id: str
    members: list[str] = field(default_factory=list)
    leader: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    shared_facts: dict[str, Any] = field(default_factory=dict)
    cohesion: float = 0.5
    morale: float = 0.5
    resources: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorityPolicy:
    mode: str = "server_authoritative"
    server_writer: str = "server"
    allowed_editor_writers: tuple[str, ...] = ("editor",)
    client_predictable_fields: tuple[str, ...] = ("movement.intent", "animation.intent")
    replicated_fields: tuple[str, ...] = ("world_facts", "characters", "groups", "reservations")


@dataclass
class WorldIntelligenceAsset:
    sensors: dict[str, list[PerceptionSensor]] = field(default_factory=dict)
    navigation_graphs: dict[str, NavigationGraph] = field(default_factory=dict)
    smart_objects: dict[str, SmartObjectDefinition] = field(default_factory=dict)
    behavior_graphs: dict[str, BehaviorGraph] = field(default_factory=dict)
    dialogue_sets: dict[str, DialogueSet] = field(default_factory=dict)
    groups: dict[str, CharacterGroup] = field(default_factory=dict)
    authority: AuthorityPolicy = field(default_factory=AuthorityPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": WORLD_INTELLIGENCE_SCHEMA,
            "sensors": {
                key: [asdict(sensor) for sensor in sensors]
                for key, sensors in self.sensors.items()
            },
            "navigation_graphs": {
                key: {
                    "graph_id": graph.graph_id,
                    "nodes": {node_id: asdict(node) for node_id, node in graph.nodes.items()},
                    "edges": [asdict(edge) for edge in graph.edges],
                    "metadata": dict(graph.metadata),
                }
                for key, graph in self.navigation_graphs.items()
            },
            "smart_objects": {
                key: {
                    "object_id": item.object_id,
                    "slots": {slot_id: asdict(slot) for slot_id, slot in item.slots.items()},
                    "enabled": item.enabled,
                    "metadata": dict(item.metadata),
                }
                for key, item in self.smart_objects.items()
            },
            "behavior_graphs": {
                key: {
                    "graph_id": graph.graph_id,
                    "root_node": graph.root_node,
                    "nodes": {node_id: asdict(node) for node_id, node in graph.nodes.items()},
                    "metadata": dict(graph.metadata),
                }
                for key, graph in self.behavior_graphs.items()
            },
            "dialogue_sets": {
                key: {
                    "set_id": value.set_id,
                    "acts": {act_id: asdict(act) for act_id, act in value.acts.items()},
                    "fallback_act": value.fallback_act,
                    "metadata": dict(value.metadata),
                }
                for key, value in self.dialogue_sets.items()
            },
            "groups": {key: asdict(value) for key, value in self.groups.items()},
            "authority": asdict(self.authority),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldIntelligenceAsset":
        if str(data.get("schema") or "") != WORLD_INTELLIGENCE_SCHEMA:
            raise ValueError("Unsupported world-intelligence schema.")
        return cls(
            sensors={
                str(key): [_sensor_from_dict(row) for row in rows]
                for key, rows in dict(data.get("sensors") or {}).items()
            },
            navigation_graphs={
                str(key): _navigation_from_dict(value)
                for key, value in dict(data.get("navigation_graphs") or {}).items()
            },
            smart_objects={
                str(key): _smart_object_from_dict(value)
                for key, value in dict(data.get("smart_objects") or {}).items()
            },
            behavior_graphs={
                str(key): _behavior_graph_from_dict(value)
                for key, value in dict(data.get("behavior_graphs") or {}).items()
            },
            dialogue_sets={
                str(key): _dialogue_set_from_dict(value)
                for key, value in dict(data.get("dialogue_sets") or {}).items()
            },
            groups={
                str(key): CharacterGroup(**dict(value))
                for key, value in dict(data.get("groups") or {}).items()
            },
            authority=_authority_from_dict(dict(data.get("authority") or {})),
            metadata=dict(data.get("metadata") or {}),
        )


def _sensor_from_dict(data: dict[str, Any]) -> PerceptionSensor:
    values = dict(data)
    values["accepted_tags"] = tuple(values.get("accepted_tags") or ())
    values["blocked_tags"] = tuple(values.get("blocked_tags") or ())
    return PerceptionSensor(**values)


def _navigation_from_dict(data: dict[str, Any]) -> NavigationGraph:
    return NavigationGraph(
        graph_id=str(data.get("graph_id") or "navigation"),
        nodes={
            str(key): NavNode(
                node_id=str(value.get("node_id") or key),
                position=tuple(value.get("position") or (0.0, 0.0, 0.0)),
                tags=tuple(value.get("tags") or ()),
                capacity=int(value.get("capacity", 1)),
            )
            for key, value in dict(data.get("nodes") or {}).items()
        },
        edges=[
            NavEdge(
                source=str(row.get("source") or ""),
                target=str(row.get("target") or ""),
                cost=float(row.get("cost", 1.0)),
                bidirectional=bool(row.get("bidirectional", True)),
                required_tags=tuple(row.get("required_tags") or ()),
                blocked=bool(row.get("blocked", False)),
            )
            for row in data.get("edges") or ()
        ],
        metadata=dict(data.get("metadata") or {}),
    )


def _smart_object_from_dict(data: dict[str, Any]) -> SmartObjectDefinition:
    return SmartObjectDefinition(
        object_id=str(data.get("object_id") or "smart_object"),
        slots={
            str(key): SmartObjectSlot(
                slot_id=str(value.get("slot_id") or key),
                actions=tuple(value.get("actions") or ()),
                position=tuple(value.get("position") or (0.0, 0.0, 0.0)),
                capacity=int(value.get("capacity", 1)),
                tags=tuple(value.get("tags") or ()),
                required_character_tags=tuple(value.get("required_character_tags") or ()),
            )
            for key, value in dict(data.get("slots") or {}).items()
        },
        enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata") or {}),
    )


def _behavior_graph_from_dict(data: dict[str, Any]) -> BehaviorGraph:
    return BehaviorGraph(
        graph_id=str(data.get("graph_id") or "behavior"),
        root_node=str(data.get("root_node") or ""),
        nodes={
            str(key): BehaviorNode(
                node_id=str(value.get("node_id") or key),
                kind=str(value.get("kind") or "action"),
                children=tuple(value.get("children") or ()),
                conditions=tuple(dict(row) for row in value.get("conditions") or ()),
                action_id=str(value.get("action_id") or ""),
                utility=float(value.get("utility", 0.0)),
                parameter_weights=dict(value.get("parameter_weights") or {}),
            )
            for key, value in dict(data.get("nodes") or {}).items()
        },
        metadata=dict(data.get("metadata") or {}),
    )


def _dialogue_set_from_dict(data: dict[str, Any]) -> DialogueSet:
    return DialogueSet(
        set_id=str(data.get("set_id") or "dialogue"),
        acts={
            str(key): DialogueAct(
                act_id=str(value.get("act_id") or key),
                intent=str(value.get("intent") or "inform"),
                authored_text=str(value.get("authored_text") or ""),
                conditions=tuple(dict(row) for row in value.get("conditions") or ()),
                effects=dict(value.get("effects") or {}),
                priority=float(value.get("priority", 0.5)),
                tags=tuple(value.get("tags") or ()),
                allow_model_realization=bool(value.get("allow_model_realization", False)),
            )
            for key, value in dict(data.get("acts") or {}).items()
        },
        fallback_act=str(data.get("fallback_act") or ""),
        metadata=dict(data.get("metadata") or {}),
    )


def _authority_from_dict(data: dict[str, Any]) -> AuthorityPolicy:
    return AuthorityPolicy(
        mode=str(data.get("mode") or "server_authoritative"),
        server_writer=str(data.get("server_writer") or "server"),
        allowed_editor_writers=tuple(data.get("allowed_editor_writers") or ("editor",)),
        client_predictable_fields=tuple(data.get("client_predictable_fields") or ("movement.intent", "animation.intent")),
        replicated_fields=tuple(data.get("replicated_fields") or ("world_facts", "characters", "groups", "reservations")),
    )
