from __future__ import annotations

"""Deterministic character decisions, narrative control, memory, and AI LOD."""

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from tech_connector.game_engine.authoring.character_intelligence_service import (
    CharacterMemory,
    CharacterObjective,
    CharacterRule,
    CharacterState,
    CharacterWorldAsset,
    FactCondition,
    NarrativeBeat,
)


@dataclass(frozen=True)
class CharacterAction:
    action_id: str
    description: str
    tags: tuple[str, ...] = ()
    preconditions: tuple[FactCondition, ...] = ()
    effects: dict[str, Any] = field(default_factory=dict)
    base_utility: float = 0.0
    parameter_weights: dict[str, float] = field(default_factory=dict)
    required_affordance: str = ""
    target_character: str = ""
    cost: float = 0.0


@dataclass(frozen=True)
class ModelActionProposal:
    action_id: str
    rationale: str = ""
    confidence: float = 0.0
    provider: str = "optional_model"


@dataclass(frozen=True)
class ActionCandidateReceipt:
    action_id: str
    accepted: bool
    score: float
    reasons: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterDecisionReceipt:
    character_id: str
    chosen_action: str
    candidates: tuple[ActionCandidateReceipt, ...]
    model_proposal: dict[str, Any] | None = None
    model_proposal_accepted: bool = False
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NarrativeDecisionReceipt:
    chosen_beat: str
    candidates: tuple[dict[str, Any], ...]
    explanation: str


@dataclass(frozen=True)
class CharacterLODDecision:
    character_id: str
    level: str
    update_interval: float
    reason: str


def choose_character_action(
    character: CharacterState,
    world: CharacterWorldAsset,
    actions: Iterable[CharacterAction],
    *,
    available_affordances: Iterable[str] = (),
    now: float = 0.0,
    model_proposal: ModelActionProposal | None = None,
) -> CharacterDecisionReceipt:
    """Choose an action deterministically; model proposals receive no authority bypass."""
    context = build_character_context(character, world, now=now)
    affordances = {str(value) for value in available_affordances}
    active_objectives = [
        objective for objective in character.objectives
        if objective.status == "active" and (objective.deadline is None or now <= objective.deadline)
    ]
    rules = sorted((*world.world_rules, *character.profile.rules), key=lambda item: (-item.priority, item.rule_id))
    receipts: list[ActionCandidateReceipt] = []
    for action in sorted(actions, key=lambda item: item.action_id):
        blocked: list[str] = []
        reasons: list[str] = []
        if action.required_affordance and action.required_affordance not in affordances:
            blocked.append(f"missing_affordance:{action.required_affordance}")
        failed_conditions = [condition.path for condition in action.preconditions if not evaluate_condition(condition, context)]
        blocked.extend(f"precondition:{path}" for path in failed_conditions)
        score = float(action.base_utility) - max(0.0, float(action.cost))

        for name, weight in sorted(action.parameter_weights.items()):
            value = _character_parameter(character, name)
            contribution = value * float(weight)
            score += contribution
            reasons.append(f"parameter:{name}={contribution:.4f}")
        for objective in active_objectives:
            matches = sum(
                1 for path, desired in objective.desired_facts.items()
                if path in action.effects and action.effects[path] == desired
            )
            if matches:
                contribution = max(0.0, min(1.0, float(objective.priority))) * matches
                score += contribution
                reasons.append(f"objective:{objective.objective_id}={contribution:.4f}")
        if action.target_character:
            relationship = character.relationships.get(action.target_character)
            if relationship is not None:
                social = (relationship.trust + relationship.affection + relationship.respect - relationship.fear) * 0.125
                score += social
                reasons.append(f"relationship:{action.target_character}={social:.4f}")

        for rule in rules:
            if rule.action_tags and not set(rule.action_tags).intersection(action.tags):
                continue
            if not all(evaluate_condition(condition, context) for condition in rule.conditions):
                continue
            if rule.outcome == "deny":
                blocked.append(f"rule:{rule.rule_id}")
            elif rule.outcome == "require":
                reasons.append(f"required_rule:{rule.rule_id}")
            elif rule.outcome == "utility":
                score += float(rule.utility_delta)
                reasons.append(f"rule:{rule.rule_id}={float(rule.utility_delta):.4f}")

        if model_proposal is not None and model_proposal.action_id == action.action_id:
            model_bonus = max(0.0, min(1.0, float(model_proposal.confidence))) * 0.1
            score += model_bonus
            reasons.append(f"model_suggestion={model_bonus:.4f}")
        receipts.append(ActionCandidateReceipt(action.action_id, not blocked, score, tuple(reasons), tuple(blocked)))

    valid = [receipt for receipt in receipts if receipt.accepted]
    chosen = max(valid, key=lambda item: (item.score, item.action_id)) if valid else None
    chosen_action = chosen.action_id if chosen else ""
    proposal_accepted = bool(model_proposal and chosen_action == model_proposal.action_id)
    if chosen is None:
        explanation = "No action passed authored preconditions, affordances, and hard rules."
    else:
        explanation = f"Selected {chosen.action_id} at utility {chosen.score:.4f}."
        if model_proposal and not proposal_accepted:
            matching = next((item for item in receipts if item.action_id == model_proposal.action_id), None)
            if matching and matching.blocked_by:
                explanation += f" Model proposal was rejected by {', '.join(matching.blocked_by)}."
    return CharacterDecisionReceipt(
        character.character_id,
        chosen_action,
        tuple(receipts),
        asdict(model_proposal) if model_proposal else None,
        proposal_accepted,
        explanation,
    )


def execute_character_action(
    character: CharacterState,
    world: CharacterWorldAsset,
    action: CharacterAction,
    decision: CharacterDecisionReceipt,
) -> dict[str, Any]:
    if decision.character_id != character.character_id or decision.chosen_action != action.action_id:
        raise PermissionError("Only the validated chosen action may mutate world state.")
    before = {path: world.world_facts.get(path) for path in action.effects}
    for path, value in action.effects.items():
        world.world_facts[str(path)] = value
    character.current_action = action.action_id
    character.revision += 1
    return {
        "schema": "tech_connector.character_action_receipt.v1",
        "character_id": character.character_id,
        "action_id": action.action_id,
        "before": before,
        "after": dict(action.effects),
        "character_revision": character.revision,
        "decision": decision.to_dict(),
    }


def record_character_memory(character: CharacterState, memory: CharacterMemory) -> CharacterMemory:
    existing = next(
        (
            item for item in character.memories
            if item.kind == memory.kind and item.subject == memory.subject and item.predicate == memory.predicate
        ),
        None,
    )
    if existing is None:
        character.memories.append(memory)
        result = memory
    else:
        existing.value = memory.value
        existing.confidence = max(0.0, min(1.0, memory.confidence))
        existing.salience = max(existing.salience, memory.salience)
        existing.created_at = memory.created_at
        existing.expires_at = memory.expires_at
        existing.source = memory.source
        result = existing
    character.revision += 1
    return result


def decay_character_memories(
    character: CharacterState,
    *,
    now: float,
    elapsed: float,
    decay_rate: float = 0.01,
) -> int:
    retained: list[CharacterMemory] = []
    removed = 0
    for memory in character.memories:
        if not memory.active(now):
            removed += 1
            continue
        memory.salience = max(0.0, memory.salience - max(0.0, decay_rate) * max(0.0, elapsed))
        if memory.salience <= 1.0e-5:
            removed += 1
        else:
            retained.append(memory)
    if removed:
        character.memories = retained
        character.revision += 1
    return removed


def select_narrative_beat(
    world: CharacterWorldAsset,
    *,
    now: float,
    focus_character: str = "",
) -> NarrativeDecisionReceipt:
    history = dict(world.metadata.get("narrative_history") or {})
    context = {"world": world.world_facts, "time": now}
    candidates: list[dict[str, Any]] = []
    for beat in sorted(world.narrative_beats.values(), key=lambda item: item.beat_id):
        blockers: list[str] = []
        if beat.eligible_characters and focus_character not in beat.eligible_characters:
            blockers.append("ineligible_character")
        previous = history.get(beat.beat_id)
        if previous is not None and beat.once:
            blockers.append("already_played")
        if previous is not None and now - float(previous) < beat.cooldown:
            blockers.append("cooldown")
        blockers.extend(
            f"condition:{condition.path}"
            for condition in beat.conditions
            if not evaluate_condition(condition, context)
        )
        candidates.append({"beat_id": beat.beat_id, "accepted": not blockers, "score": beat.priority, "blocked_by": blockers})
    valid = [row for row in candidates if row["accepted"]]
    chosen = max(valid, key=lambda row: (float(row["score"]), str(row["beat_id"]))) if valid else None
    return NarrativeDecisionReceipt(
        str(chosen["beat_id"]) if chosen else "",
        tuple(candidates),
        f"Selected narrative beat {chosen['beat_id']}." if chosen else "No narrative beat passed authored constraints.",
    )


def apply_narrative_beat(
    world: CharacterWorldAsset,
    beat: NarrativeBeat,
    receipt: NarrativeDecisionReceipt,
    *,
    now: float,
    focus_character: str = "",
) -> dict[str, Any]:
    if receipt.chosen_beat != beat.beat_id:
        raise PermissionError("Only the validated narrative beat may mutate world state.")
    world.world_facts.update(beat.effects)
    targets = beat.eligible_characters or ((focus_character,) if focus_character else tuple(world.characters))
    for character_id in targets:
        character = world.characters.get(character_id)
        if character is None:
            continue
        existing = {item.objective_id for item in character.objectives}
        character.objectives.extend(
            copy.deepcopy(objective)
            for objective in beat.objectives
            if objective.objective_id not in existing
        )
        character.current_narrative_beat = beat.beat_id
        character.revision += 1
    history = world.metadata.setdefault("narrative_history", {})
    history[beat.beat_id] = float(now)
    return {"beat_id": beat.beat_id, "effects": dict(beat.effects), "targets": list(targets), "time": float(now)}


def choose_character_lod(
    character_id: str,
    *,
    distance: float,
    significance: float = 0.5,
    conversing: bool = False,
    quest_critical: bool = False,
) -> CharacterLODDecision:
    if conversing or quest_critical or distance <= 25.0:
        return CharacterLODDecision(character_id, "full", 0.0, "nearby or narratively critical")
    if distance <= 150.0 or significance >= 0.65:
        return CharacterLODDecision(character_id, "scheduled", 0.5, "periodic goal and schedule evaluation")
    return CharacterLODDecision(character_id, "statistical", 10.0, "aggregate off-screen world simulation")


def build_character_context(character: CharacterState, world: CharacterWorldAsset, *, now: float) -> dict[str, Any]:
    return {
        "world": world.world_facts,
        "time": float(now),
        "character": {
            "parameters": character.profile.parameters,
            "traits": character.profile.traits,
            "drives": character.profile.drives,
            "values": character.profile.values,
            "blackboard": character.blackboard,
            "knowledge_tags": sorted(character.profile.knowledge_tags),
            "faction_tags": sorted(character.profile.faction_tags),
        },
        "relationships": {key: asdict(value) for key, value in character.relationships.items()},
        "memories": [asdict(item) for item in character.memories if item.active(now)],
    }


def evaluate_condition(condition: FactCondition, context: dict[str, Any]) -> bool:
    actual = _resolve_path(context, condition.path)
    expected = condition.value
    operator = str(condition.operator or "equals").lower()
    if operator in {"equals", "eq", "=="}:
        return actual == expected
    if operator in {"not_equals", "ne", "!="}:
        return actual != expected
    if operator in {"greater", "gt", ">"}:
        return _compare(actual, expected, lambda a, b: a > b)
    if operator in {"greater_equal", "gte", ">="}:
        return _compare(actual, expected, lambda a, b: a >= b)
    if operator in {"less", "lt", "<"}:
        return _compare(actual, expected, lambda a, b: a < b)
    if operator in {"less_equal", "lte", "<="}:
        return _compare(actual, expected, lambda a, b: a <= b)
    if operator == "contains":
        try:
            return expected in actual
        except TypeError:
            return False
    if operator == "in":
        try:
            return actual in expected
        except TypeError:
            return False
    if operator == "truthy":
        return bool(actual)
    if operator == "exists":
        return actual is not None
    raise ValueError(f"Unsupported character condition operator: {condition.operator}")


def _resolve_path(value: Any, path: str) -> Any:
    current = value
    tokens = str(path).split(".")
    for index, token in enumerate(tokens):
        if isinstance(current, dict):
            remainder = ".".join(tokens[index:])
            if remainder in current:
                return current[remainder]
            current = current.get(token)
        else:
            current = getattr(current, token, None)
        if current is None:
            break
    return current


def _compare(first: Any, second: Any, operation: Any) -> bool:
    try:
        return bool(operation(float(first), float(second)))
    except (TypeError, ValueError):
        return False


def _character_parameter(character: CharacterState, name: str) -> float:
    for source in (
        character.profile.parameters,
        character.profile.traits,
        character.profile.drives,
        character.profile.values,
    ):
        if name in source:
            return float(source[name])
    return 0.0
