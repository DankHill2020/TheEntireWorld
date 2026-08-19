from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any, Iterable, MutableMapping

from tech_connector.game_engine.authoring.tc_physics_joint_service import (
    create_physics_joint,
    remove_physics_joint,
    validate_physics_joint,
)


@dataclass
class PhysicsJointEditorModel:
    """Transactional authoring model shared by UI, chat, and scripted tools."""

    runtime_world: MutableMapping[str, Any]
    undo_limit: int = 100
    selected_ids: list[str] = field(default_factory=list)
    _undo: list[list[dict[str, Any]]] = field(default_factory=list, repr=False)
    _redo: list[list[dict[str, Any]]] = field(default_factory=list, repr=False)
    _interaction_snapshot: list[dict[str, Any]] | None = field(default=None, repr=False)

    @property
    def joints(self) -> list[dict[str, Any]]:
        joints = self.runtime_world.setdefault("physics_joints", [])
        if not isinstance(joints, list):
            raise TypeError("runtime_world.physics_joints must be a list.")
        return joints

    def _snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.joints)

    def _commit(self) -> None:
        self._undo.append(self._snapshot())
        del self._undo[:-max(1, int(self.undo_limit))]
        self._redo.clear()

    def _restore(self, snapshot: list[dict[str, Any]]) -> None:
        self.runtime_world["physics_joints"] = deepcopy(snapshot)
        available = {str(joint.get("id") or "") for joint in snapshot}
        self.selected_ids = [joint_id for joint_id in self.selected_ids if joint_id in available]

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        return True

    def create(self, joint_id: str, first: str, second: str, *, preset: str = "weld", settings: dict[str, Any] | None = None) -> dict[str, Any]:
        self._commit()
        joint = create_physics_joint(self.runtime_world, joint_id, first, second, preset=preset, settings=settings)
        self.selected_ids = [str(joint["id"])]
        return joint

    def remove_selected(self) -> int:
        targets = set(self.selected_ids)
        if not targets:
            return 0
        self._commit()
        removed = sum(1 for joint_id in targets if remove_physics_joint(self.runtime_world, joint_id))
        self.selected_ids = []
        return removed

    def duplicate_selected(self, suffix: str = " Copy") -> list[dict[str, Any]]:
        selected = [joint for joint in self.joints if str(joint.get("id") or "") in set(self.selected_ids)]
        if not selected:
            return []
        self._commit()
        existing = {str(joint.get("id") or "") for joint in self.joints}
        copies: list[dict[str, Any]] = []
        for source in selected:
            base = str(source.get("id") or "Joint") + suffix
            identifier, index = base, 2
            while identifier in existing:
                identifier, index = f"{base} {index}", index + 1
            clone = deepcopy(source)
            clone["id"] = identifier
            clone["broken"] = False
            self.joints.append(clone)
            existing.add(identifier)
            copies.append(clone)
        self.selected_ids = [str(item["id"]) for item in copies]
        return copies

    def edit_selected(self, changes: dict[str, Any]) -> int:
        targets = set(self.selected_ids)
        if not targets or not changes:
            return 0
        self._commit()
        changed = 0
        for index, source in enumerate(self.joints):
            if str(source.get("id") or "") not in targets:
                continue
            candidate = dict(source)
            candidate.update(changes)
            self.joints[index] = validate_physics_joint(candidate)
            changed += 1
        return changed

    def begin_interaction(self) -> None:
        """Start a continuous viewport edit that becomes one undo operation."""
        if self._interaction_snapshot is None:
            self._interaction_snapshot = self._snapshot()

    def preview_selected(self, changes: dict[str, Any]) -> int:
        targets = set(self.selected_ids)
        if not targets or not changes:
            return 0
        changed = 0
        for index, source in enumerate(self.joints):
            if str(source.get("id") or "") not in targets:
                continue
            candidate = dict(source)
            candidate.update(changes)
            self.joints[index] = validate_physics_joint(candidate)
            changed += 1
        return changed

    def end_interaction(self, commit: bool = True) -> bool:
        snapshot = self._interaction_snapshot
        self._interaction_snapshot = None
        if snapshot is None:
            return False
        if not commit:
            self._restore(snapshot)
            return True
        if snapshot == self.joints:
            return False
        self._undo.append(snapshot)
        del self._undo[:-max(1, int(self.undo_limit))]
        self._redo.clear()
        return True

    def set_anchor(self, joint_id: str, body: str, local_position: Iterable[float]) -> dict[str, Any]:
        key = "first_anchor" if str(body).casefold() in {"first", "a", "body_a"} else "second_anchor"
        self.selected_ids = [str(joint_id)]
        self.edit_selected({key: list(local_position)})
        return next(joint for joint in self.joints if str(joint.get("id") or "") == str(joint_id))

    def visual_guides(self, entity_positions: dict[str, Iterable[float]], segments: int = 32) -> list[dict[str, Any]]:
        """Build bounded anchor, limit-arc, axis, and motor-preview geometry."""

        guides: list[dict[str, Any]] = []
        for joint in self.joints:
            first_position = tuple(float(value) for value in entity_positions.get(str(joint.get("first") or ""), (0.0, 0.0, 0.0)))
            second_position = tuple(float(value) for value in entity_positions.get(str(joint.get("second") or ""), (0.0, 0.0, 0.0)))
            first_anchor = tuple(first_position[i] + float(joint.get("first_anchor", [0.0] * 3)[i]) for i in range(3))
            second_anchor = tuple(second_position[i] + float(joint.get("second_anchor", [0.0] * 3)[i]) for i in range(3))
            axis = tuple(float(value) for value in joint.get("axis", (1.0, 0.0, 0.0)))
            arc: list[tuple[float, float, float]] = []
            if bool(joint.get("limits_enabled")) and str(joint.get("type")) in {"hinge", "cone_twist"}:
                minimum = math.radians(float(joint.get("minimum_limit", 0.0)))
                maximum = math.radians(float(joint.get("maximum_limit", 0.0)))
                count = max(4, min(128, int(segments)))
                arc = [(first_anchor[0] + math.cos(minimum + (maximum - minimum) * i / count) * 0.75,
                        first_anchor[1] + math.sin(minimum + (maximum - minimum) * i / count) * 0.75,
                        first_anchor[2]) for i in range(count + 1)]
            guides.append({
                "id": str(joint.get("id") or ""), "type": str(joint.get("type") or "fixed"),
                "first_anchor": first_anchor, "second_anchor": second_anchor, "axis": axis,
                "limit_arc": arc, "motor_enabled": bool(joint.get("motor_enabled")),
                "motor_speed": float(joint.get("motor_target_velocity", 0.0)),
                "broken": bool(joint.get("broken", False)),
            })
        return guides


__all__ = ["PhysicsJointEditorModel"]
