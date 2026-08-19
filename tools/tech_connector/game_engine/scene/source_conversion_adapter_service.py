"""Truthful source-adapter capability registry for TC-native scene conversion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceConversionAdapter:
    provider: str
    implementation_state: str
    live_bridge: bool
    scene_hierarchy: bool
    geometry: bool
    materials: bool
    cameras_lights: bool
    rig_topology: bool
    skin_weights: bool
    animation: bool
    references: bool
    interchange_fallbacks: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def readiness(self) -> dict[str, Any]:
        data = asdict(self)
        data["interchange_fallbacks"] = list(self.interchange_fallbacks)
        data["limitations"] = list(self.limitations)
        required = (self.scene_hierarchy, self.geometry, self.materials, self.rig_topology, self.skin_weights, self.animation)
        data["standalone_character_conversion_ready"] = all(required)
        data["static_scene_conversion_ready"] = self.scene_hierarchy and self.geometry
        return data


_ADAPTERS = {
    "maya": SourceConversionAdapter(
        "maya", "implemented", True, True, True, True, True, True, True, True, True,
        ("usd", "fbx", "alembic"),
        ("Unsupported plug-in nodes remain explicit source proxies until baked or replaced.",),
    ),
    "blender": SourceConversionAdapter(
        "blender", "partial", True, True, True, True, True, False, False, False, False,
        ("usd", "gltf", "fbx", "alembic"),
        ("Armature topology, exact skin weights, animation curves, and linked-library boundaries still need bridge extractors.",),
    ),
    "motionbuilder": SourceConversionAdapter(
        "motionbuilder", "partial", True, True, False, False, True, False, False, True, False,
        ("fbx",),
        ("The bridge exposes takes and character metadata but not render geometry, rig topology, or exact skin bindings.",),
    ),
    "3dsmax": SourceConversionAdapter(
        "3dsmax", "blocked", False, False, False, False, False, False, False, False, False,
        ("usd", "fbx", "alembic"),
        ("A native 3ds Max live bridge has not been implemented yet.",),
    ),
    "unreal": SourceConversionAdapter(
        "unreal", "federated_partial", True, True, True, True, True, False, False, True, True,
        ("usd", "fbx", "gltf", "alembic"),
        ("Blueprints, Niagara graphs, custom materials, and gameplay code require translation or baking.",),
    ),
    "unity": SourceConversionAdapter(
        "unity", "federated_partial", True, True, True, True, True, False, False, True, True,
        ("usd", "fbx", "gltf", "alembic"),
        ("MonoBehaviours, Shader Graphs, and custom runtime components require translation or replacement.",),
    ),
}


def source_conversion_adapters() -> dict[str, dict[str, Any]]:
    return {provider: adapter.readiness() for provider, adapter in _ADAPTERS.items()}


def conversion_readiness(provider: str) -> dict[str, Any]:
    key = str(provider or "").strip().lower().split(":", 1)[0]
    if key == "max":
        key = "3dsmax"
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        return {
            "provider": key,
            "implementation_state": "unknown",
            "standalone_character_conversion_ready": False,
            "static_scene_conversion_ready": False,
            "limitations": ["No registered TC source adapter."],
        }
    return adapter.readiness()
