"""Pose/trajectory search over a baked humanoid clip library.

This is a host-side selector. It produces a clip and sample time for animation
playback; a native player must explicitly consume its decision to display it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "tech_connector.retargeted_motion_library.v1"
_VELOCITIES = {
    "idle": (0.0, 0.0), "walk": (0.0, 2.2), "run": (0.0, 5.5),
    "walk_back": (0.0, -2.0), "strafe_left": (-3.5, 0.0),
    "strafe_right": (3.5, 0.0), "crouch_idle": (0.0, 0.0),
    "crouch_move": (0.0, 1.2), "crawl_idle": (0.0, 0.0), "crawl": (0.0, 0.65),
    "jump_start": (0.0, 0.0), "jump_air": (0.0, 0.0),
    "jump_land": (0.0, 0.0),
}
_JOINTS = ("l_hand", "r_hand", "l_ankle", "r_ankle")


@dataclass(frozen=True)
class MotionDecision:
    clip_id: str
    frame: int
    time_seconds: float
    cost: float
    blend_seconds: float


def load_motion_library(path: str | Path) -> dict[str, Any]:
    library = json.loads(Path(path).read_text(encoding="utf-8"))
    if library.get("schema") != SCHEMA:
        raise ValueError("Unsupported motion library schema")
    if not library.get("clips"):
        raise ValueError("Motion library has no clips")
    for clip_id, clip in library["clips"].items():
        if clip_id not in _VELOCITIES:
            raise ValueError(f"Unknown motion clip role: {clip_id}")
        frames = clip.get("pose_features") or []
        if len(frames) != clip.get("frames"):
            raise ValueError(f"Missing per-frame pose data: {clip_id}")
        if not Path(clip["path"]).is_file():
            raise FileNotFoundError(clip["path"])
        if clip.get("sha256"):
            digest = hashlib.sha256()
            with Path(clip["path"]).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != clip["sha256"]:
                raise ValueError(f"Motion clip has changed since baking: {clip_id}")
    return library


def select_motion_frame(
    library: Mapping[str, Any], *, stance: str, desired_velocity: tuple[float, float],
    current_pose: Mapping[str, Any] | None = None, current_clip: str = "",
    current_frame: int = -1, jump_phase: str = "",
) -> MotionDecision:
    """Choose a frame by desired 0.2/0.4s trajectory and four-joint pose.

    Horizontal velocity uses character-local (right, forward) metres/second.
    Jump phases are hard constraints, preventing a ground/crawl pose in midair.
    Clip/frame continuity lowers oscillation; locomotion still changes when the
    trajectory benefit exceeds that hysteresis.
    """
    if jump_phase:
        if jump_phase not in {"start", "air", "land"}:
            raise ValueError(f"Unknown jump phase: {jump_phase}")
        candidates = [f"jump_{jump_phase}"]
    elif stance == "stand":
        candidates = ["idle", "walk", "run", "walk_back", "strafe_left", "strafe_right"]
    elif stance == "crouch":
        candidates = ["crouch_idle", "crouch_move"]
    elif stance == "crawl":
        candidates = ["crawl_idle", "crawl"]
    else:
        raise ValueError(f"Unknown stance: {stance}")
    best: MotionDecision | None = None
    for clip_id in candidates:
        clip = library["clips"].get(clip_id)
        if not clip:
            continue
        velocity = _VELOCITIES[clip_id]
        # Two future trajectory horizons, in metres, discriminate starts,
        # sprinting, backward motion and strafing without relying on clip names.
        trajectory_cost = sum(
            ((desired_velocity[0] - velocity[0]) * horizon) ** 2
            + ((desired_velocity[1] - velocity[1]) * horizon) ** 2
            for horizon in (0.2, 0.4)
        ) * 5.0
        for feature in clip["pose_features"]:
            frame = int(feature["frame"])
            cost = trajectory_cost
            if current_pose:
                cost += 2.0 * (float(current_pose.get("pelvis_height", 0.0))
                               - float(feature["pelvis_height"])) ** 2
                current_joints = current_pose.get("joints") or {}
                for name in _JOINTS:
                    if name in current_joints and name in feature["joints"]:
                        cost += sum((float(a) - float(b)) ** 2 for a, b in
                                    zip(current_joints[name], feature["joints"][name]))
            if clip_id == current_clip:
                cost -= 0.06
                if current_frame >= 0:
                    frame_count = int(clip["frames"])
                    if clip.get("loop"):
                        predicted = (current_frame + 1) % frame_count
                        distance = abs(frame - predicted)
                        distance = min(distance, frame_count - distance)
                    else:
                        predicted = min(current_frame + 1, frame_count - 1)
                        distance = abs(frame - predicted)
                    cost += distance * 0.005
            decision = MotionDecision(clip_id, frame, frame / float(clip["fps"]),
                                      cost, 0.08 if clip_id.startswith("jump") else 0.14)
            if best is None or (decision.cost, decision.clip_id, decision.frame) < (
                    best.cost, best.clip_id, best.frame):
                best = decision
    if best is None:
        raise ValueError(f"No clips available for {jump_phase or stance}")
    return best
