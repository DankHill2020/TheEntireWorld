from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PhysicsFrame:
    frame: int
    state: dict[str, Any]
    inputs: tuple[dict[str, Any], ...]
    state_hash: str


class DeterministicPhysicsRecorder:
    def __init__(self, capacity: int = 600) -> None:
        if capacity < 2:
            raise ValueError("Physics recording capacity must be at least two frames.")
        self.frames: deque[PhysicsFrame] = deque(maxlen=int(capacity))

    def record(self, frame: int, state: dict[str, Any], inputs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = ()) -> PhysicsFrame:
        snapshot = deepcopy(state)
        item = PhysicsFrame(int(frame), snapshot, tuple(deepcopy(list(inputs))), _canonical_hash(snapshot))
        if self.frames and item.frame <= self.frames[-1].frame:
            raise ValueError("Recorded physics frame numbers must increase monotonically.")
        self.frames.append(item)
        return item

    def rollback(self, frame: int) -> dict[str, Any]:
        found = next((item for item in reversed(self.frames) if item.frame == int(frame)), None)
        if found is None:
            raise KeyError(f"Physics frame is outside the rollback window: {frame}")
        return deepcopy(found.state)

    def replay(self, start_frame: int, step: Callable[[dict[str, Any], tuple[dict[str, Any], ...]], dict[str, Any]]) -> dict[str, Any]:
        selected = [item for item in self.frames if item.frame >= int(start_frame)]
        if not selected:
            raise KeyError(f"Physics frame is outside the replay window: {start_frame}")
        state = deepcopy(selected[0].state)
        for item in selected[1:]:
            state = step(state, item.inputs)
        return state

    def verify(self) -> list[int]:
        return [item.frame for item in self.frames if _canonical_hash(item.state) != item.state_hash]


def hot_reload_joint_state(current: dict[str, Any], authored_joints: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply authored properties while preserving compatible accumulated runtime state."""

    runtime_by_id = {str(item.get("id") or ""): item for item in current.get("physics_joints") or () if isinstance(item, dict)}
    merged = []
    for source in authored_joints:
        joint = deepcopy(source)
        previous = runtime_by_id.get(str(joint.get("id") or ""), {})
        if previous.get("type") == joint.get("type") and previous.get("first") == joint.get("first") and previous.get("second") == joint.get("second"):
            for key in ("broken", "accumulated_linear_impulse", "accumulated_angular_impulse"):
                if key in previous:
                    joint[key] = deepcopy(previous[key])
        merged.append(joint)
    result = deepcopy(current)
    result["physics_joints"] = merged
    result["physics_revision"] = int(current.get("physics_revision", 0)) + 1
    return result


def replication_packet(frame: PhysicsFrame, baseline: PhysicsFrame | None = None) -> dict[str, Any]:
    return {
        "schema": "tech_connector.physics_replication.v1", "frame": frame.frame,
        "baseline_frame": baseline.frame if baseline else -1, "state_hash": frame.state_hash,
        "state": deepcopy(frame.state), "inputs": deepcopy(list(frame.inputs)),
    }


__all__ = ["DeterministicPhysicsRecorder", "PhysicsFrame", "hot_reload_joint_state", "replication_packet"]
