from __future__ import annotations

"""Deterministic runtime services for perception, behavior, navigation, and authority."""

import heapq
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

from tech_connector.game_engine.authoring.character_intelligence_service import (
    CharacterMemory,
    CharacterState,
    CharacterWorldAsset,
    FactCondition,
)
from tech_connector.game_engine.authoring.world_intelligence_service import (
    AuthorityPolicy,
    BehaviorGraph,
    DialogueSet,
    NavigationGraph,
    PerceptionSensor,
    SmartObjectDefinition,
)
from tech_connector.game_engine.runtime.character_brain_service import (
    build_character_context,
    evaluate_condition,
    record_character_memory,
)


@dataclass(frozen=True)
class PerceivedStimulus:
    stimulus_id: str
    modality: str
    source_id: str
    position: tuple[float, float, float]
    strength: float = 1.0
    tags: tuple[str, ...] = ()
    value: Any = True
    timestamp: float = 0.0


@dataclass(frozen=True)
class PerceptionObservation:
    stimulus_id: str
    sensor_id: str
    detected: bool
    confidence: float
    distance: float
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class PerceptionReceipt:
    character_id: str
    observations: tuple[PerceptionObservation, ...]


@dataclass(frozen=True)
class NavigationReceipt:
    graph_id: str
    start: str
    goal: str
    path: tuple[str, ...]
    total_cost: float
    visited_nodes: int
    blocked_reason: str = ""


@dataclass(frozen=True)
class CrowdAgentIntent:
    character_id: str
    position: tuple[float, float, float]
    goal: tuple[float, float, float]
    preferred_speed: float = 1.0
    radius: float = 0.5


@dataclass(frozen=True)
class CrowdSteeringReceipt:
    character_id: str
    velocity: tuple[float, float, float]
    avoided: tuple[str, ...]


@dataclass(frozen=True)
class SmartObjectReservation:
    reservation_id: str
    object_id: str
    slot_id: str
    character_id: str
    action: str
    created_at: float
    expires_at: float


@dataclass
class SmartObjectReservationManager:
    reservations: dict[str, SmartObjectReservation] = field(default_factory=dict)

    def release_expired(self, now: float) -> int:
        expired = [key for key, value in self.reservations.items() if value.expires_at <= now]
        for key in expired:
            del self.reservations[key]
        return len(expired)

    def reserve(
        self,
        definition: SmartObjectDefinition,
        *,
        character_id: str,
        action: str,
        character_tags: Iterable[str] = (),
        now: float = 0.0,
        duration: float = 5.0,
        preferred_slot: str = "",
    ) -> SmartObjectReservation:
        if not definition.enabled:
            raise PermissionError(f"Smart object is disabled: {definition.object_id}")
        self.release_expired(now)
        tags = set(character_tags)
        candidates = []
        for slot in sorted(definition.slots.values(), key=lambda value: value.slot_id):
            if preferred_slot and slot.slot_id != preferred_slot:
                continue
            if action not in slot.actions:
                continue
            if not set(slot.required_character_tags).issubset(tags):
                continue
            occupied = sum(
                item.object_id == definition.object_id and item.slot_id == slot.slot_id
                for item in self.reservations.values()
            )
            if occupied < max(1, slot.capacity):
                candidates.append(slot)
        if not candidates:
            raise PermissionError(f"No compatible slot is available for {definition.object_id}:{action}")
        slot = candidates[0]
        reservation_id = f"{definition.object_id}:{slot.slot_id}:{character_id}"
        reservation = SmartObjectReservation(
            reservation_id,
            definition.object_id,
            slot.slot_id,
            character_id,
            action,
            float(now),
            float(now) + max(0.001, float(duration)),
        )
        self.reservations[reservation_id] = reservation
        return reservation

    def release(self, reservation_id: str, *, character_id: str = "") -> bool:
        reservation = self.reservations.get(str(reservation_id))
        if reservation is None:
            return False
        if character_id and reservation.character_id != character_id:
            raise PermissionError("Only the reservation owner may release this smart-object slot.")
        del self.reservations[str(reservation_id)]
        return True

    def to_dict(self) -> dict[str, Any]:
        return {key: asdict(value) for key, value in self.reservations.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SmartObjectReservationManager":
        return cls({str(key): SmartObjectReservation(**dict(value)) for key, value in data.items()})


@dataclass(frozen=True)
class BehaviorDecisionReceipt:
    graph_id: str
    character_id: str
    selected_action: str
    score: float
    trace: tuple[dict[str, Any], ...]
    explanation: str


@dataclass(frozen=True)
class DialogueDecisionReceipt:
    set_id: str
    character_id: str
    act_id: str
    intent: str
    line: str
    canonical_effects: dict[str, Any]
    used_model_realization: bool
    blocked_acts: tuple[str, ...]


@dataclass(frozen=True)
class AuthorityReceipt:
    accepted: bool
    writer: str
    field_path: str
    revision_before: int
    revision_after: int
    predicted: bool
    reason: str


def sense_stimuli(
    character: CharacterState,
    sensors: Iterable[PerceptionSensor],
    stimuli: Iterable[PerceivedStimulus],
    *,
    occlusion_test: Callable[[tuple[float, float, float], tuple[float, float, float]], bool] | None = None,
) -> PerceptionReceipt:
    origin = _vec3(character.blackboard.get("position", (0.0, 0.0, 0.0)))
    forward = _normalized(_vec3(character.blackboard.get("forward", (0.0, 0.0, 1.0))))
    observations: list[PerceptionObservation] = []
    for stimulus in sorted(stimuli, key=lambda item: item.stimulus_id):
        matching = [sensor for sensor in sensors if sensor.modality in {"any", stimulus.modality}]
        if not matching:
            observations.append(PerceptionObservation(stimulus.stimulus_id, "", False, 0.0, _distance(origin, stimulus.position), ("no_sensor",)))
            continue
        for sensor in sorted(matching, key=lambda item: item.sensor_id):
            blockers: list[str] = []
            distance = _distance(origin, stimulus.position)
            if distance > max(0.0, sensor.range):
                blockers.append("out_of_range")
            stimulus_tags = set(stimulus.tags)
            if sensor.accepted_tags and not stimulus_tags.intersection(sensor.accepted_tags):
                blockers.append("unaccepted_tags")
            if stimulus_tags.intersection(sensor.blocked_tags):
                blockers.append("blocked_tags")
            if sensor.field_of_view < 359.999 and distance > 1.0e-8:
                direction = _normalized(_subtract(stimulus.position, origin))
                threshold = math.cos(math.radians(max(0.0, sensor.field_of_view) * 0.5))
                if _dot(forward, direction) < threshold:
                    blockers.append("outside_field_of_view")
            if occlusion_test is not None and occlusion_test(origin, stimulus.position):
                blockers.append("occluded")
            confidence = 0.0
            if not blockers:
                falloff = 1.0 - min(1.0, distance / max(1.0e-8, sensor.range))
                confidence = max(0.0, min(1.0, stimulus.strength * sensor.sensitivity * (0.25 + 0.75 * falloff)))
                if confidence <= 0.0:
                    blockers.append("below_threshold")
            observations.append(
                PerceptionObservation(
                    stimulus.stimulus_id,
                    sensor.sensor_id,
                    not blockers,
                    confidence,
                    distance,
                    tuple(blockers),
                )
            )
    return PerceptionReceipt(character.character_id, tuple(observations))


def apply_perception_receipt(
    character: CharacterState,
    receipt: PerceptionReceipt,
    stimuli: Iterable[PerceivedStimulus],
    sensors: Iterable[PerceptionSensor],
) -> int:
    if receipt.character_id != character.character_id:
        raise PermissionError("Perception receipt belongs to another character.")
    stimulus_map = {item.stimulus_id: item for item in stimuli}
    sensor_map = {item.sensor_id: item for item in sensors}
    applied = 0
    for observation in receipt.observations:
        if not observation.detected:
            continue
        stimulus = stimulus_map.get(observation.stimulus_id)
        sensor = sensor_map.get(observation.sensor_id)
        if stimulus is None or sensor is None:
            continue
        record_character_memory(
            character,
            CharacterMemory(
                memory_id=f"perception:{stimulus.stimulus_id}",
                kind="perception",
                subject=stimulus.source_id,
                predicate=stimulus.modality,
                value=stimulus.value,
                confidence=observation.confidence,
                salience=max(0.1, observation.confidence),
                created_at=stimulus.timestamp,
                expires_at=stimulus.timestamp + max(0.0, sensor.memory_duration),
                source=f"sensor:{sensor.sensor_id}",
            ),
        )
        applied += 1
    return applied


def find_navigation_path(
    graph: NavigationGraph,
    start: str,
    goal: str,
    *,
    traversal_tags: Iterable[str] = (),
) -> NavigationReceipt:
    if start not in graph.nodes or goal not in graph.nodes:
        return NavigationReceipt(graph.graph_id, start, goal, (), math.inf, 0, "unknown_endpoint")
    tags = set(traversal_tags)
    neighbors: dict[str, list[tuple[str, float]]] = {key: [] for key in graph.nodes}
    for edge in graph.edges:
        if edge.blocked or not set(edge.required_tags).issubset(tags):
            continue
        if edge.source not in neighbors or edge.target not in neighbors:
            continue
        cost = max(0.0, float(edge.cost))
        neighbors[edge.source].append((edge.target, cost))
        if edge.bidirectional:
            neighbors[edge.target].append((edge.source, cost))
    frontier: list[tuple[float, str]] = [(0.0, start)]
    costs = {start: 0.0}
    previous: dict[str, str] = {}
    visited = 0
    while frontier:
        cost, node = heapq.heappop(frontier)
        if cost != costs.get(node):
            continue
        visited += 1
        if node == goal:
            break
        for target, edge_cost in sorted(neighbors[node]):
            candidate = cost + edge_cost
            if candidate < costs.get(target, math.inf):
                costs[target] = candidate
                previous[target] = node
                heapq.heappush(frontier, (candidate, target))
    if goal not in costs:
        return NavigationReceipt(graph.graph_id, start, goal, (), math.inf, visited, "unreachable")
    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return NavigationReceipt(graph.graph_id, start, goal, tuple(path), costs[goal], visited)


def solve_crowd_steering(intents: Iterable[CrowdAgentIntent], *, neighbor_distance: float = 2.0) -> tuple[CrowdSteeringReceipt, ...]:
    rows = sorted(intents, key=lambda item: item.character_id)
    receipts = []
    for item in rows:
        desired = _scale(_normalized(_subtract(item.goal, item.position)), max(0.0, item.preferred_speed))
        avoidance = (0.0, 0.0, 0.0)
        avoided: list[str] = []
        for other in rows:
            if other.character_id == item.character_id:
                continue
            offset = _subtract(item.position, other.position)
            distance = _length(offset)
            safe_distance = max(0.01, item.radius + other.radius)
            if distance < max(safe_distance, neighbor_distance):
                strength = (max(safe_distance, neighbor_distance) - distance) / max(safe_distance, neighbor_distance)
                direction = _normalized(offset) if distance > 1.0e-8 else ((-1.0, 0.0, 0.0) if item.character_id < other.character_id else (1.0, 0.0, 0.0))
                avoidance = _add(avoidance, _scale(direction, strength * item.preferred_speed))
                avoided.append(other.character_id)
        velocity = _clamp_length(_add(desired, avoidance), max(0.0, item.preferred_speed))
        receipts.append(CrowdSteeringReceipt(item.character_id, velocity, tuple(sorted(avoided))))
    return tuple(receipts)


def evaluate_behavior_graph(
    graph: BehaviorGraph,
    character: CharacterState,
    world: CharacterWorldAsset,
    *,
    now: float = 0.0,
) -> BehaviorDecisionReceipt:
    context = build_character_context(character, world, now=now)
    trace: list[dict[str, Any]] = []
    visiting: set[str] = set()

    def visit(node_id: str) -> tuple[bool, str, float]:
        if node_id in visiting:
            trace.append({"node_id": node_id, "status": "blocked", "reason": "cycle"})
            return False, "", 0.0
        node = graph.nodes.get(node_id)
        if node is None:
            trace.append({"node_id": node_id, "status": "blocked", "reason": "missing_node"})
            return False, "", 0.0
        visiting.add(node_id)
        conditions = tuple(
            FactCondition(str(row.get("path") or ""), str(row.get("operator") or "equals"), row.get("value"))
            for row in node.conditions
        )
        if not all(evaluate_condition(condition, context) for condition in conditions):
            visiting.remove(node_id)
            trace.append({"node_id": node_id, "status": "blocked", "reason": "conditions"})
            return False, "", 0.0
        score = float(node.utility) + sum(
            _character_value(character, name) * float(weight)
            for name, weight in node.parameter_weights.items()
        )
        kind = node.kind.lower()
        if kind == "action":
            result = (bool(node.action_id), node.action_id, score)
        elif kind in {"selector", "sequence"}:
            children = [visit(child) for child in node.children]
            successful = [item for item in children if item[0]]
            if kind == "sequence" and len(successful) != len(children):
                result = (False, "", score)
            else:
                result = successful[0] if successful else (False, "", score)
        elif kind == "utility_selector":
            successful = [visit(child) for child in node.children]
            successful = [item for item in successful if item[0]]
            result = max(successful, key=lambda item: (item[2], item[1])) if successful else (False, "", score)
        else:
            result = (False, "", score)
        visiting.remove(node_id)
        trace.append({"node_id": node_id, "status": "passed" if result[0] else "failed", "action": result[1], "score": result[2]})
        return result

    success, action, score = visit(graph.root_node)
    return BehaviorDecisionReceipt(
        graph.graph_id,
        character.character_id,
        action if success else "",
        score,
        tuple(trace),
        f"Selected behavior action {action}." if success else "No behavior branch passed authored conditions.",
    )


def choose_dialogue_act(
    dialogue: DialogueSet,
    character: CharacterState,
    world: CharacterWorldAsset,
    *,
    now: float = 0.0,
    model_realizations: dict[str, str] | None = None,
) -> DialogueDecisionReceipt:
    context = build_character_context(character, world, now=now)
    valid = []
    blocked = []
    for act in sorted(dialogue.acts.values(), key=lambda value: value.act_id):
        conditions = (
            FactCondition(str(row.get("path") or ""), str(row.get("operator") or "equals"), row.get("value"))
            for row in act.conditions
        )
        if all(evaluate_condition(condition, context) for condition in conditions):
            valid.append(act)
        else:
            blocked.append(act.act_id)
    selected = max(valid, key=lambda value: (value.priority, value.act_id)) if valid else dialogue.acts.get(dialogue.fallback_act)
    if selected is None:
        return DialogueDecisionReceipt(dialogue.set_id, character.character_id, "", "", "", {}, False, tuple(blocked))
    proposal = (model_realizations or {}).get(selected.act_id, "")
    use_model = bool(proposal and selected.allow_model_realization)
    return DialogueDecisionReceipt(
        dialogue.set_id,
        character.character_id,
        selected.act_id,
        selected.intent,
        proposal if use_model else selected.authored_text,
        dict(selected.effects),
        use_model,
        tuple(blocked),
    )


def simulate_group_tick(group: Any, *, elapsed: float, events: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    before = {"cohesion": group.cohesion, "morale": group.morale, "resources": dict(group.resources)}
    event_rows = sorted((dict(row) for row in events), key=lambda row: str(row.get("event_id") or ""))
    group.cohesion = _clamp01(group.cohesion + sum(float(row.get("cohesion_delta", 0.0)) for row in event_rows))
    group.morale = _clamp01(group.morale + sum(float(row.get("morale_delta", 0.0)) for row in event_rows))
    consumption = max(0.0, float(elapsed)) * max(1, len(group.members))
    for resource, amount in list(group.resources.items()):
        rate = float(group.shared_facts.get(f"consumption.{resource}", 0.0))
        group.resources[resource] = max(0.0, float(amount) - rate * consumption)
    return {
        "schema": "tech_connector.group_tick_receipt.v1",
        "group_id": group.group_id,
        "before": before,
        "after": {"cohesion": group.cohesion, "morale": group.morale, "resources": dict(group.resources)},
        "events": event_rows,
    }


def authorize_world_mutation(
    policy: AuthorityPolicy,
    *,
    writer: str,
    field_path: str,
    current_revision: int,
    expected_revision: int,
    predicted: bool = False,
) -> AuthorityReceipt:
    if expected_revision != current_revision:
        return AuthorityReceipt(False, writer, field_path, current_revision, current_revision, predicted, "revision_conflict")
    if writer == policy.server_writer or writer in policy.allowed_editor_writers:
        return AuthorityReceipt(True, writer, field_path, current_revision, current_revision + 1, predicted, "authoritative_writer")
    if predicted and field_path in policy.client_predictable_fields:
        return AuthorityReceipt(True, writer, field_path, current_revision, current_revision, True, "client_prediction_only")
    return AuthorityReceipt(False, writer, field_path, current_revision, current_revision, predicted, "writer_not_authorized")


def _character_value(character: CharacterState, name: str) -> float:
    for source in (character.profile.parameters, character.profile.traits, character.profile.drives, character.profile.values):
        if name in source:
            return float(source[name])
    return 0.0


def _vec3(value: Any) -> tuple[float, float, float]:
    values = tuple(value) if isinstance(value, (list, tuple)) else (0.0, 0.0, 0.0)
    return tuple(float(values[index]) if index < len(values) else 0.0 for index in range(3))


def _add(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(first[index] + second[index] for index in range(3))


def _subtract(first: tuple[float, float, float], second: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(first[index] - second[index] for index in range(3))


def _scale(value: tuple[float, float, float], amount: float) -> tuple[float, float, float]:
    return tuple(component * amount for component in value)


def _dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _length(value: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(value, value))


def _normalized(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-8 else (0.0, 0.0, 0.0)


def _clamp_length(value: tuple[float, float, float], maximum: float) -> tuple[float, float, float]:
    length = _length(value)
    return _scale(value, maximum / length) if length > maximum > 0.0 else value


def _distance(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return _length(_subtract(first, second))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
