from __future__ import annotations

"""Composable game-experience profiles for varied genres and audiences."""

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from tech_connector.game_engine.authoring.presentation_profile_service import PresentationProfile


GAME_EXPERIENCE_SCHEMA = "tech_connector.game_experience.v1"


@dataclass(frozen=True)
class ExperienceAxes:
    simulation_fidelity: float = 0.5
    systemic_depth: float = 0.5
    narrative_agency: float = 0.5
    player_expression: float = 0.5
    competition: float = 0.0
    cooperation: float = 0.0
    learning: float = 0.0
    accessibility: float = 0.75
    content_scale: float = 0.5

    def normalized(self) -> "ExperienceAxes":
        return ExperienceAxes(**{key: _clamp01(value) for key, value in asdict(self).items()})


@dataclass(frozen=True)
class SimulationPolicy:
    units: str = "SI"
    deterministic: bool = True
    real_time: bool = True
    solver_tolerance: float = 1.0e-4
    minimum_tick_rate: int = 30
    maximum_substeps: int = 8
    time_scale: float = 1.0
    allow_time_scrub: bool = False
    authoritative_domain: str = "server"


@dataclass(frozen=True)
class LearningObjective:
    objective_id: str
    description: str
    evidence: tuple[str, ...]
    mastery_threshold: float = 0.8
    attempts_before_scaffold: int = 2
    standards: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameplayModule:
    module_id: str
    category: str
    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    fallback: str = ""


@dataclass
class GameExperienceProfile:
    profile_id: str
    game_types: tuple[str, ...]
    axes: ExperienceAxes = field(default_factory=ExperienceAxes)
    simulation: SimulationPolicy = field(default_factory=SimulationPolicy)
    presentation: PresentationProfile | None = None
    learning_objectives: list[LearningObjective] = field(default_factory=list)
    modules: list[GameplayModule] = field(default_factory=list)
    audience: dict[str, Any] = field(default_factory=dict)
    accessibility: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GAME_EXPERIENCE_SCHEMA,
            "profile_id": self.profile_id,
            "game_types": list(self.game_types),
            "axes": asdict(self.axes.normalized()),
            "simulation": asdict(self.simulation),
            "presentation": self.presentation.to_dict() if self.presentation is not None else None,
            "learning_objectives": [asdict(value) for value in self.learning_objectives],
            "modules": [asdict(value) for value in self.modules],
            "audience": dict(self.audience),
            "accessibility": dict(self.accessibility),
            "session": dict(self.session),
            "safety": dict(self.safety),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameExperienceProfile":
        if str(data.get("schema") or "") != GAME_EXPERIENCE_SCHEMA:
            raise ValueError("Unsupported game-experience schema.")
        simulation = dict(data.get("simulation") or {})
        return cls(
            profile_id=str(data.get("profile_id") or "game"),
            game_types=tuple(data.get("game_types") or ()),
            axes=ExperienceAxes(**dict(data.get("axes") or {})).normalized(),
            simulation=SimulationPolicy(**simulation),
            presentation=(
                PresentationProfile.from_dict(dict(data["presentation"]))
                if isinstance(data.get("presentation"), dict)
                else None
            ),
            learning_objectives=[_learning_objective(row) for row in data.get("learning_objectives") or ()],
            modules=[_gameplay_module(row) for row in data.get("modules") or ()],
            audience=dict(data.get("audience") or {}),
            accessibility=dict(data.get("accessibility") or {}),
            session=dict(data.get("session") or {}),
            safety=dict(data.get("safety") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


_PRESETS: dict[str, dict[str, Any]] = {
    "realistic_simulation": {
        "axes": {"simulation_fidelity": 1.0, "systemic_depth": 0.95, "content_scale": 0.85},
        "modules": (
            GameplayModule("physical_world", "simulation", ("fixed_tick", "unit_aware_physics", "deterministic_replay")),
            GameplayModule("scientific_instruments", "interface", ("data_plotting", "time_control")),
        ),
        "simulation": {"minimum_tick_rate": 60, "maximum_substeps": 16, "allow_time_scrub": True},
    },
    "educational": {
        "axes": {"learning": 1.0, "accessibility": 1.0, "systemic_depth": 0.7},
        "modules": (
            GameplayModule("mastery_model", "learning", ("evidence_events", "adaptive_scaffolding", "teacher_controls")),
            GameplayModule("safe_classroom", "safety", ("privacy_controls", "content_guardrails", "offline_mode")),
        ),
    },
    "sandbox": {
        "axes": {"player_expression": 1.0, "systemic_depth": 0.9, "content_scale": 0.8},
        "modules": (GameplayModule("creation_tools", "creation", ("runtime_authoring", "undo", "shareable_assets")),),
    },
    "action": {
        "axes": {"player_expression": 0.75, "competition": 0.65, "simulation_fidelity": 0.65},
        "modules": (GameplayModule("responsive_action", "action", ("input_buffering", "prediction", "animation_matching")),),
    },
    "rpg": {
        "axes": {"narrative_agency": 1.0, "systemic_depth": 0.85, "content_scale": 0.85},
        "modules": (GameplayModule("living_characters", "characters", ("character_rules", "memory", "relationships", "narrative_beats")),),
    },
    "strategy": {
        "axes": {"systemic_depth": 1.0, "competition": 0.7, "content_scale": 0.9},
        "modules": (GameplayModule("strategic_simulation", "strategy", ("groups", "economy", "fog_of_war", "deterministic_replay")),),
    },
    "puzzle": {
        "axes": {"systemic_depth": 0.7, "learning": 0.35, "accessibility": 0.9},
        "modules": (GameplayModule("puzzle_state", "puzzle", ("state_graph", "hints", "solution_validation")),),
    },
    "platformer": {
        "axes": {"player_expression": 0.8, "simulation_fidelity": 0.5, "accessibility": 0.85},
        "modules": (GameplayModule("precision_traversal", "movement", ("coyote_time", "input_buffering", "moving_platforms")),),
    },
    "racing": {
        "axes": {"competition": 0.9, "simulation_fidelity": 0.8, "content_scale": 0.65},
        "modules": (GameplayModule("vehicle_competition", "vehicle", ("vehicle_dynamics", "race_rules", "ghost_replay")),),
    },
    "social": {
        "axes": {"cooperation": 1.0, "narrative_agency": 0.7, "accessibility": 0.9},
        "modules": (GameplayModule("social_world", "social", ("presence", "moderation", "permissions")),),
    },
    "party": {
        "axes": {"competition": 0.65, "cooperation": 0.65, "accessibility": 1.0},
        "modules": (GameplayModule("rapid_minigames", "party", ("fast_reset", "simple_controls", "local_multiplayer")),),
    },
}


def create_game_experience_profile(
    profile_id: str,
    game_types: Iterable[str],
    *,
    axis_overrides: dict[str, float] | None = None,
    simulation_overrides: dict[str, Any] | None = None,
) -> GameExperienceProfile:
    types = tuple(dict.fromkeys(str(value).strip().lower() for value in game_types if str(value).strip()))
    if not types:
        types = ("sandbox",)
    unknown = [value for value in types if value not in _PRESETS]
    if unknown:
        raise KeyError(f"Unknown game type(s): {', '.join(unknown)}")
    axes = asdict(ExperienceAxes())
    modules: list[GameplayModule] = []
    simulation = asdict(SimulationPolicy())
    for game_type in types:
        preset = _PRESETS[game_type]
        for key, value in dict(preset.get("axes") or {}).items():
            axes[key] = max(float(axes[key]), float(value))
        for module in preset.get("modules") or ():
            if module.module_id not in {value.module_id for value in modules}:
                modules.append(module)
        simulation.update(dict(preset.get("simulation") or {}))
    axes.update(dict(axis_overrides or {}))
    simulation.update(dict(simulation_overrides or {}))
    profile = GameExperienceProfile(
        profile_id=str(profile_id),
        game_types=types,
        axes=ExperienceAxes(**axes).normalized(),
        simulation=SimulationPolicy(**simulation),
        modules=modules,
        audience={"minimum_age": 6 if "educational" in types else 13, "maximum_age": 120, "skill": "adaptive"},
        accessibility={
            "remappable_input": True,
            "subtitles": True,
            "text_scaling": True,
            "color_independent_cues": True,
            "difficulty_assists": True,
        },
        session={"duration_minutes": 30, "drop_in": "social" in types or "party" in types, "save_anywhere": True},
        safety={"telemetry_consent": True, "minor_privacy": "educational" in types, "content_rating": "author_defined"},
    )
    return profile


def validate_game_experience(profile: GameExperienceProfile) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    capabilities = {capability for module in profile.modules for capability in module.required_capabilities}
    if profile.axes.learning >= 0.5 and not profile.learning_objectives:
        issues.append({"severity": "warning", "code": "learning_objectives_missing", "message": "Learning is emphasized but no measurable objectives are authored."})
    if profile.axes.competition >= 0.5 and "deterministic_replay" not in capabilities and "ghost_replay" not in capabilities:
        issues.append({"severity": "warning", "code": "competition_replay_missing", "message": "Competitive outcomes need replayable evidence or authoritative match records."})
    if profile.axes.simulation_fidelity >= 0.8 and not profile.simulation.deterministic:
        issues.append({"severity": "warning", "code": "simulation_reproducibility", "message": "High-fidelity simulation is not configured for deterministic replay."})
    if profile.audience.get("minimum_age", 0) < 13 and not profile.safety.get("minor_privacy"):
        issues.append({"severity": "error", "code": "minor_privacy_missing", "message": "Experiences for children require explicit minor privacy controls."})
    return {
        "schema": "tech_connector.game_experience_validation.v1",
        "profile_id": profile.profile_id,
        "valid": not any(row["severity"] == "error" for row in issues),
        "issues": issues,
        "required_capabilities": sorted(capabilities),
    }


def build_gameplay_runtime_budget(profile: GameExperienceProfile, *, target: str = "desktop") -> dict[str, Any]:
    target_scale = {"mobile": 0.55, "web": 0.65, "console": 0.9, "desktop": 1.0, "server": 1.25}.get(str(target), 1.0)
    fidelity = profile.axes.simulation_fidelity
    scale = profile.axes.content_scale
    tick_rate = max(profile.simulation.minimum_tick_rate, round(30 + 30 * fidelity))
    return {
        "schema": "tech_connector.gameplay_runtime_budget.v1",
        "profile_id": profile.profile_id,
        "target": str(target),
        "tick_rate": tick_rate,
        "simulation_substeps": min(profile.simulation.maximum_substeps, max(1, round(1 + 7 * fidelity * target_scale))),
        "full_character_budget": max(4, round((16 + 112 * scale) * target_scale)),
        "scheduled_character_budget": max(32, round((128 + 896 * scale) * target_scale)),
        "background_population_budget": max(1000, round((5000 + 95000 * scale) * target_scale)),
        "requires_deterministic_replay": profile.simulation.deterministic,
        "quality_scaling": "preserve_gameplay_reduce_presentation_first",
    }


def available_game_types() -> tuple[str, ...]:
    return tuple(sorted(_PRESETS))


def attach_game_experience(scene_document: Any, profile: GameExperienceProfile) -> dict[str, Any]:
    metadata = getattr(scene_document, "metadata", None)
    if not isinstance(metadata, dict):
        raise TypeError("Scene document must expose mutable metadata.")
    payload = profile.to_dict()
    metadata["game_experience"] = payload
    return payload


def _learning_objective(data: dict[str, Any]) -> LearningObjective:
    values = dict(data)
    values["evidence"] = tuple(values.get("evidence") or ())
    values["standards"] = tuple(values.get("standards") or ())
    return LearningObjective(**values)


def _gameplay_module(data: dict[str, Any]) -> GameplayModule:
    values = dict(data)
    values["required_capabilities"] = tuple(values.get("required_capabilities") or ())
    values["optional_capabilities"] = tuple(values.get("optional_capabilities") or ())
    return GameplayModule(**values)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
