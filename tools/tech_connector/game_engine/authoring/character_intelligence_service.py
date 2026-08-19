from __future__ import annotations

"""Serializable, designer-authored character and narrative intelligence assets."""

from dataclasses import asdict, dataclass, field
from typing import Any

from tech_connector.game_engine.authoring.world_intelligence_service import WorldIntelligenceAsset


CHARACTER_WORLD_SCHEMA = "tech_connector.character_world.v1"


@dataclass(frozen=True)
class CharacterParameterSpec:
    name: str
    default: float = 0.5
    minimum: float = 0.0
    maximum: float = 1.0
    description: str = ""
    designer_locked: bool = False

    def clamp(self, value: float) -> float:
        return max(float(self.minimum), min(float(self.maximum), float(value)))


@dataclass(frozen=True)
class FactCondition:
    path: str
    operator: str = "equals"
    value: Any = True


@dataclass(frozen=True)
class CharacterRule:
    rule_id: str
    conditions: tuple[FactCondition, ...] = ()
    action_tags: tuple[str, ...] = ()
    outcome: str = "deny"
    utility_delta: float = 0.0
    priority: int = 0
    explanation: str = ""


@dataclass
class CharacterMemory:
    memory_id: str
    kind: str
    subject: str
    predicate: str
    value: Any
    confidence: float = 1.0
    salience: float = 0.5
    created_at: float = 0.0
    expires_at: float | None = None
    source: str = "experience"
    private: bool = False

    def active(self, now: float) -> bool:
        return self.expires_at is None or float(now) < float(self.expires_at)


@dataclass
class RelationshipState:
    character_id: str
    trust: float = 0.0
    affection: float = 0.0
    fear: float = 0.0
    respect: float = 0.0
    familiarity: float = 0.0
    obligations: dict[str, float] = field(default_factory=dict)


@dataclass
class CharacterObjective:
    objective_id: str
    description: str
    desired_facts: dict[str, Any]
    priority: float = 0.5
    status: str = "active"
    deadline: float | None = None
    source: str = "designer"
    parent_objective: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class CharacterProfile:
    character_id: str
    display_name: str
    parameter_specs: dict[str, CharacterParameterSpec] = field(default_factory=dict)
    parameters: dict[str, float] = field(default_factory=dict)
    traits: dict[str, float] = field(default_factory=dict)
    drives: dict[str, float] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)
    rules: list[CharacterRule] = field(default_factory=list)
    knowledge_tags: set[str] = field(default_factory=set)
    faction_tags: set[str] = field(default_factory=set)
    dialogue_style: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, spec in self.parameter_specs.items():
            self.parameters[name] = spec.clamp(self.parameters.get(name, spec.default))
        self.traits = _normalized_map(self.traits)
        self.drives = _normalized_map(self.drives)
        self.values = _normalized_map(self.values)

    def set_parameter(self, name: str, value: float, *, override_lock: bool = False) -> float:
        spec = self.parameter_specs.get(str(name))
        if spec is None:
            raise KeyError(f"Unknown character parameter: {name}")
        if spec.designer_locked and not override_lock:
            raise PermissionError(f"Character parameter is designer-locked: {name}")
        resolved = spec.clamp(value)
        self.parameters[str(name)] = resolved
        return resolved

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["knowledge_tags"] = sorted(self.knowledge_tags)
        data["faction_tags"] = sorted(self.faction_tags)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterProfile":
        return cls(
            character_id=str(data.get("character_id") or "character"),
            display_name=str(data.get("display_name") or "Character"),
            parameter_specs={
                str(key): CharacterParameterSpec(**dict(value))
                for key, value in dict(data.get("parameter_specs") or {}).items()
            },
            parameters={str(key): float(value) for key, value in dict(data.get("parameters") or {}).items()},
            traits=dict(data.get("traits") or {}),
            drives=dict(data.get("drives") or {}),
            values=dict(data.get("values") or {}),
            rules=[_rule_from_dict(row) for row in data.get("rules") or ()],
            knowledge_tags=set(data.get("knowledge_tags") or ()),
            faction_tags=set(data.get("faction_tags") or ()),
            dialogue_style=dict(data.get("dialogue_style") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class CharacterState:
    profile: CharacterProfile
    memories: list[CharacterMemory] = field(default_factory=list)
    relationships: dict[str, RelationshipState] = field(default_factory=dict)
    objectives: list[CharacterObjective] = field(default_factory=list)
    blackboard: dict[str, Any] = field(default_factory=dict)
    current_action: str = ""
    current_narrative_beat: str = ""
    revision: int = 0

    @property
    def character_id(self) -> str:
        return self.profile.character_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "memories": [asdict(item) for item in self.memories],
            "relationships": {key: asdict(value) for key, value in self.relationships.items()},
            "objectives": [asdict(item) for item in self.objectives],
            "blackboard": dict(self.blackboard),
            "current_action": self.current_action,
            "current_narrative_beat": self.current_narrative_beat,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterState":
        return cls(
            profile=CharacterProfile.from_dict(dict(data.get("profile") or {})),
            memories=[CharacterMemory(**dict(row)) for row in data.get("memories") or ()],
            relationships={
                str(key): RelationshipState(**dict(value))
                for key, value in dict(data.get("relationships") or {}).items()
            },
            objectives=[_objective_from_dict(dict(row)) for row in data.get("objectives") or ()],
            blackboard=dict(data.get("blackboard") or {}),
            current_action=str(data.get("current_action") or ""),
            current_narrative_beat=str(data.get("current_narrative_beat") or ""),
            revision=int(data.get("revision", 0)),
        )


@dataclass(frozen=True)
class NarrativeBeat:
    beat_id: str
    description: str
    conditions: tuple[FactCondition, ...] = ()
    effects: dict[str, Any] = field(default_factory=dict)
    objectives: tuple[CharacterObjective, ...] = ()
    eligible_characters: tuple[str, ...] = ()
    priority: float = 0.5
    cooldown: float = 0.0
    once: bool = False
    tags: tuple[str, ...] = ()


@dataclass
class CharacterWorldAsset:
    characters: dict[str, CharacterState] = field(default_factory=dict)
    world_facts: dict[str, Any] = field(default_factory=dict)
    narrative_beats: dict[str, NarrativeBeat] = field(default_factory=dict)
    world_rules: list[CharacterRule] = field(default_factory=list)
    intelligence: WorldIntelligenceAsset = field(default_factory=WorldIntelligenceAsset)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CHARACTER_WORLD_SCHEMA,
            "characters": {key: value.to_dict() for key, value in self.characters.items()},
            "world_facts": dict(self.world_facts),
            "narrative_beats": {key: asdict(value) for key, value in self.narrative_beats.items()},
            "world_rules": [asdict(value) for value in self.world_rules],
            "intelligence": self.intelligence.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterWorldAsset":
        if str(data.get("schema") or "") != CHARACTER_WORLD_SCHEMA:
            raise ValueError("Unsupported character-world schema.")
        return cls(
            characters={
                str(key): CharacterState.from_dict(dict(value))
                for key, value in dict(data.get("characters") or {}).items()
            },
            world_facts=dict(data.get("world_facts") or {}),
            narrative_beats={
                str(key): _beat_from_dict(dict(value))
                for key, value in dict(data.get("narrative_beats") or {}).items()
            },
            world_rules=[_rule_from_dict(row) for row in data.get("world_rules") or ()],
            intelligence=(
                WorldIntelligenceAsset.from_dict(dict(data["intelligence"]))
                if isinstance(data.get("intelligence"), dict)
                else WorldIntelligenceAsset()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


def attach_character_world(scene_document: Any, world: CharacterWorldAsset) -> dict[str, Any]:
    metadata = getattr(scene_document, "metadata", None)
    if not isinstance(metadata, dict):
        raise TypeError("Scene document must expose mutable metadata.")
    payload = world.to_dict()
    metadata["character_world"] = payload
    return payload


def _normalized_map(values: dict[str, Any]) -> dict[str, float]:
    return {str(key): max(0.0, min(1.0, float(value))) for key, value in values.items()}


def _condition_from_dict(data: dict[str, Any]) -> FactCondition:
    return FactCondition(str(data.get("path") or ""), str(data.get("operator") or "equals"), data.get("value"))


def _rule_from_dict(data: dict[str, Any]) -> CharacterRule:
    return CharacterRule(
        rule_id=str(data.get("rule_id") or "rule"),
        conditions=tuple(_condition_from_dict(row) for row in data.get("conditions") or ()),
        action_tags=tuple(data.get("action_tags") or ()),
        outcome=str(data.get("outcome") or "deny"),
        utility_delta=float(data.get("utility_delta", 0.0)),
        priority=int(data.get("priority", 0)),
        explanation=str(data.get("explanation") or ""),
    )


def _objective_from_dict(data: dict[str, Any]) -> CharacterObjective:
    data = dict(data)
    data["tags"] = tuple(data.get("tags") or ())
    return CharacterObjective(**data)


def _beat_from_dict(data: dict[str, Any]) -> NarrativeBeat:
    return NarrativeBeat(
        beat_id=str(data.get("beat_id") or "beat"),
        description=str(data.get("description") or ""),
        conditions=tuple(_condition_from_dict(row) for row in data.get("conditions") or ()),
        effects=dict(data.get("effects") or {}),
        objectives=tuple(_objective_from_dict(row) for row in data.get("objectives") or ()),
        eligible_characters=tuple(data.get("eligible_characters") or ()),
        priority=float(data.get("priority", 0.5)),
        cooldown=float(data.get("cooldown", 0.0)),
        once=bool(data.get("once", False)),
        tags=tuple(data.get("tags") or ()),
    )
