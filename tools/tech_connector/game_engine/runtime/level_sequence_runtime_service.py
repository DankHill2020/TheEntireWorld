"""Runtime director for sequence-driven level streaming and reality blending."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.sequence_asset_service import SequenceAssetService, evaluate_sequence


@dataclass(frozen=True)
class SequenceRuntimeCommand:
    operation: str
    level_asset_id: str
    level_source: str
    weight: float = 0.0
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SequenceRuntimeFrame:
    sequence_asset_id: str
    frame: int
    active_camera: dict[str, Any] | None
    commands: tuple[SequenceRuntimeCommand, ...]
    events: tuple[dict[str, Any], ...]
    loaded_levels: tuple[str, ...]


class LevelSequenceRuntimeDirector:
    """Turns authored Level Blend tracks into executable streaming/blend commands."""

    def __init__(
        self, project_root: str | Path, database: AssetDatabase, *,
        command_sink: Callable[[SequenceRuntimeCommand], Any] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.sequences = SequenceAssetService(self.project_root, database)
        self.command_sink = command_sink
        self._loaded_levels: set[str] = set()
        self._active_levels: set[str] = set()

    def tick(self, sequence_asset_id: str, frame: int, *, execute: bool = True) -> SequenceRuntimeFrame:
        values = self.sequences.properties(sequence_asset_id)
        evaluation = evaluate_sequence(values, int(frame))
        commands: list[SequenceRuntimeCommand] = []
        wanted_preload = self._preload_levels(values, int(frame))
        active = {str(item.get("level_asset_id") or "") for item in evaluation["level_blends"] if item.get("level_asset_id")}
        for level_id in sorted(wanted_preload | active):
            if level_id not in self._loaded_levels:
                commands.append(self._command("preload_level", level_id, payload={"asynchronous": True}))
                self._loaded_levels.add(level_id)
        for blend in evaluation["level_blends"]:
            level_id = str(blend.get("level_asset_id") or "")
            if not level_id: continue
            transition = dict(blend.get("transition") or {})
            commands.append(self._command("set_level_blend", level_id, weight=float(blend.get("weight") or 0.0), payload={
                "blend_mode": blend.get("blend_mode"), "world_partition": bool(transition.get("world_partition", True)),
                "data_layers": list(transition.get("data_layers") or ()),
                "blend_lighting": bool(transition.get("blend_lighting", True)),
                "blend_post_process": bool(transition.get("blend_post_process", True)),
                "blend_audio": bool(transition.get("blend_audio", True)),
                "blend_gameplay": bool(transition.get("blend_gameplay", False)),
                "preserve_player_state": bool(transition.get("preserve_player_state", True)),
                "preserve_persistent_actors": bool(transition.get("preserve_persistent_actors", True)),
            }))
        for level_id in sorted(self._active_levels - active):
            if level_id not in wanted_preload and self._unload_when_inactive(values, level_id):
                commands.append(self._command("unload_level", level_id))
                self._loaded_levels.discard(level_id)
        self._active_levels = active
        if execute and self.command_sink is not None:
            for command in commands: self.command_sink(command)
        return SequenceRuntimeFrame(
            str(sequence_asset_id), int(frame), evaluation.get("camera_cut"), tuple(commands),
            tuple(evaluation.get("events") or ()), tuple(sorted(self._loaded_levels)),
        )

    def reset(self, *, execute: bool = True) -> tuple[SequenceRuntimeCommand, ...]:
        commands = tuple(self._command("unload_level", level_id) for level_id in sorted(self._loaded_levels))
        if execute and self.command_sink is not None:
            for command in commands: self.command_sink(command)
        self._loaded_levels.clear(); self._active_levels.clear()
        return commands

    def _command(self, operation: str, level_id: str, *, weight: float = 0.0, payload: dict[str, Any] | None = None) -> SequenceRuntimeCommand:
        record = self.database.asset(level_id)
        if record is None or record.asset_type != "tc.level":
            raise KeyError(f"Sequence Level Blend references an unavailable Level asset: {level_id}")
        return SequenceRuntimeCommand(operation, level_id, str(record.source_path), float(weight), payload)

    @staticmethod
    def _preload_levels(values: Mapping[str, Any], frame: int) -> set[str]:
        result: set[str] = set()
        for track in values.get("tracks") or ():
            if not isinstance(track, Mapping) or track.get("type") != "level_blend" or track.get("muted"): continue
            for section in track.get("sections") or ():
                if not isinstance(section, Mapping): continue
                start, end = int(section.get("start_frame") or 0), int(section.get("end_frame") or 0)
                pre_roll = max(0, int(section.get("pre_roll") or 0))
                if start - pre_roll <= frame < end and section.get("asset_id"): result.add(str(section["asset_id"]))
        return result

    @staticmethod
    def _unload_when_inactive(values: Mapping[str, Any], level_id: str) -> bool:
        for track in values.get("tracks") or ():
            if not isinstance(track, Mapping) or track.get("type") != "level_blend": continue
            for section in track.get("sections") or ():
                if isinstance(section, Mapping) and str(section.get("asset_id") or "") == level_id:
                    return bool(dict(section.get("level_transition") or {}).get("unload_when_inactive", True))
        return True
