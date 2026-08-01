"""After Effects Motion Graphics & Keyframe Compositing Engine for Tech Connector.

Includes Transform Keyframing (Position, Scale, Rotation, Opacity), Bézier Easing Curves,
Layer Parenting (Pick Whip), and Adjustment Layer Compositing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass
class TransformKeyframe:
    """A single transform keyframe on the timeline."""

    frame: int
    pos_x: float = 0.0
    pos_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0  # degrees
    opacity: float = 1.0  # 0.0 to 1.0
    easing: str = "EaseInOut"  # Linear, EaseIn, EaseOut, EaseInOut

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "rotation": self.rotation,
            "opacity": self.opacity,
            "easing": self.easing,
        }


def interpolate_keyframe_value(v0: float, v1: float, t: float, easing: str = "Linear") -> float:
    """Interpolate between two keyframe values using linear or cubic Bézier easing curves."""
    t = max(0.0, min(1.0, t))
    if easing == "EaseIn":
        factor = t * t
    elif easing == "EaseOut":
        factor = t * (2.0 - t)
    elif easing == "EaseInOut":
        factor = t * t * (3.0 - 2.0 * t)
    else:  # Linear
        factor = t
    return v0 + (v1 - v0) * factor


class MotionLayerPropertyTrack:
    """Keyframe property track for a motion graphics layer."""

    def __init__(self, layer_name: str):
        self.layer_name = layer_name
        self.parent_layer_name: str = ""  # After Effects Pick Whip Parenting
        self.is_adjustment_layer: bool = False
        self.keyframes: list[TransformKeyframe] = []

    def add_keyframe(self, keyframe: TransformKeyframe):
        self.keyframes.append(keyframe)
        self.keyframes.sort(key=lambda k: k.frame)

    def get_interpolated_transform(self, frame_index: int) -> TransformKeyframe:
        """Sample interpolated transform at any given frame in the timeline."""
        if not self.keyframes:
            return TransformKeyframe(frame=frame_index)

        if frame_index <= self.keyframes[0].frame:
            return self.keyframes[0]
        if frame_index >= self.keyframes[-1].frame:
            return self.keyframes[-1]

        # Find keyframe interval
        for i in range(len(self.keyframes) - 1):
            k0 = self.keyframes[i]
            k1 = self.keyframes[i + 1]
            if k0.frame <= frame_index <= k1.frame:
                t = float(frame_index - k0.frame) / max(1.0, float(k1.frame - k0.frame))
                return TransformKeyframe(
                    frame=frame_index,
                    pos_x=interpolate_keyframe_value(k0.pos_x, k1.pos_x, t, k0.easing),
                    pos_y=interpolate_keyframe_value(k0.pos_y, k1.pos_y, t, k0.easing),
                    scale_x=interpolate_keyframe_value(k0.scale_x, k1.scale_x, t, k0.easing),
                    scale_y=interpolate_keyframe_value(k0.scale_y, k1.scale_y, t, k0.easing),
                    rotation=interpolate_keyframe_value(k0.rotation, k1.rotation, t, k0.easing),
                    opacity=interpolate_keyframe_value(k0.opacity, k1.opacity, t, k0.easing),
                    easing=k0.easing,
                )

        return self.keyframes[-1]



@dataclass
class VectorPoint2D:
    """A single 2D control point on a vector path."""

    x: float
    y: float
    handle_in_x: float = 0.0
    handle_in_y: float = 0.0
    handle_out_x: float = 0.0
    handle_out_y: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "handle_in": (self.handle_in_x, self.handle_in_y),
            "handle_out": (self.handle_out_x, self.handle_out_y),
        }


@dataclass
class VectorPathKeyframe:
    """A keyframe storing an ordered array of 2D control points for shape morphing."""

    frame: int
    points: list[VectorPoint2D]
    easing: str = "EaseInOut"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "points": [p.to_dict() for p in self.points],
            "easing": self.easing,
        }


class UniversalVectorPointTrack:
    """Keyframe track for morphing 2D vector paths and shape control points over time."""

    def __init__(self, property_name: str = "MaskPath"):
        self.property_name = property_name
        self.keyframes: list[VectorPathKeyframe] = []

    def add_path_keyframe(self, keyframe: VectorPathKeyframe):
        self.keyframes.append(keyframe)
        self.keyframes.sort(key=lambda k: k.frame)

    def get_interpolated_path(self, frame_index: int) -> list[VectorPoint2D]:
        """Interpolate all 2D vector control points at any frame in the timeline."""
        if not self.keyframes:
            return []
        if frame_index <= self.keyframes[0].frame:
            return self.keyframes[0].points
        if frame_index >= self.keyframes[-1].frame:
            return self.keyframes[-1].points

        for i in range(len(self.keyframes) - 1):
            k0 = self.keyframes[i]
            k1 = self.keyframes[i + 1]
            if k0.frame <= frame_index <= k1.frame:
                t = float(frame_index - k0.frame) / max(1.0, float(k1.frame - k0.frame))
                
                # Morph corresponding control points
                morphed_points = []
                num_points = min(len(k0.points), len(k1.points))
                for idx in range(num_points):
                    p0 = k0.points[idx]
                    p1 = k1.points[idx]
                    morphed_points.append(VectorPoint2D(
                        x=interpolate_keyframe_value(p0.x, p1.x, t, k0.easing),
                        y=interpolate_keyframe_value(p0.y, p1.y, t, k0.easing),
                        handle_in_x=interpolate_keyframe_value(p0.handle_in_x, p1.handle_in_x, t, k0.easing),
                        handle_in_y=interpolate_keyframe_value(p0.handle_in_y, p1.handle_in_y, t, k0.easing),
                        handle_out_x=interpolate_keyframe_value(p0.handle_out_x, p1.handle_out_x, t, k0.easing),
                        handle_out_y=interpolate_keyframe_value(p0.handle_out_y, p1.handle_out_y, t, k0.easing),
                    ))
                return morphed_points

        return self.keyframes[-1].points


class UniversalPropertyKeyframeEngine:
    """Universal keyframe engine allowing ANY float, color, or vector parameter to be keyframed."""

    def __init__(self):
        self.tracks: dict[str, UniversalVectorPointTrack | MotionLayerPropertyTrack] = {}

    def get_or_create_vector_track(self, prop_name: str) -> UniversalVectorPointTrack:
        if prop_name not in self.tracks:
            self.tracks[prop_name] = UniversalVectorPointTrack(prop_name)
        return self.tracks[prop_name]  # type: ignore
