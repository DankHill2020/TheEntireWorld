"""Create the source-independent Unreal conversion acceptance scene."""

from __future__ import annotations

from pathlib import Path

from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    save_federated_scene,
)


def create_sample(
    path: str | Path,
    *,
    texture_path: str | Path | None = None,
    lighting_model: str = "physically_based",
    global_illumination: str = "probe",
    simulation: dict[str, object] | None = None,
    world_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    player_particle_physics: dict[str, object] | None = None,
    dynamic_diffuse_gi: bool = True,
) -> Path:
    destination = Path(path).expanduser().resolve()
    imported_mesh = Path(__file__).with_name("assets") / "film_pyramid.obj"
    offset = tuple(float(item) for item in world_offset)
    position = lambda x, y, z: [x + offset[0], y + offset[1], z + offset[2]]  # noqa: E731
    document = FederatedSceneDocument(
        name="Unreal Third Person Conversion",
        sources=[{
            "provider": "unreal",
            "source_path": "/Game/ThirdPerson/Maps/ThirdPersonMap",
            "conversion_state": "converted",
            "runtime_dependency": False,
        }],
        metadata={
            "conversion_receipt": {
                "source_provider": "unreal",
                "source_asset": "/Game/ThirdPerson/Maps/ThirdPersonMap",
                "target_authority": "tech_connector",
                "runtime_dependencies": [],
                "standalone_runtime_ready": True,
            },
            "runtime_world": {
                "hud_text": "TC Native Third Person Sample",
                "save_slot": "third_person_sample",
                "rendering": {
                    "upscaler": "tc_temporal",
                    "quality": "quality",
                    "exposure": 1.15,
                    "sharpness": 0.18,
                    "lighting_model": lighting_model,
                    "global_illumination": global_illumination,
                    "sky_color": [0.08, 0.18, 0.42] if lighting_model != "toon" else [0.12, 0.3, 0.62],
                    "ground_color": [0.025, 0.035, 0.045] if lighting_model != "toon" else [0.08, 0.12, 0.18],
                    "indirect_intensity": 1.0,
                    "toon_bands": 3,
                    "rim_intensity": 0.32 if lighting_model == "toon" else 0.12,
                    "dynamic_diffuse_gi": dynamic_diffuse_gi,
                    "dynamic_gi_intensity": 0.3,
                    "dynamic_gi_distance": 14.0,
                    "maximum_dynamic_gi_sources": 8,
                },
                "simulation": dict(simulation or {}),
                "entities": [
                    {
                        "name": "Player",
                        "transform": {"position": position(0.0, 2.5, 0.0)},
                        "render": {
                            "mesh": str(imported_mesh),
                            "material": "converted://unreal/M_Mannequin",
                            "base_color": [0.04, 0.52, 0.9],
                            "metallic": 0.15,
                            "roughness": 0.3,
                            **({"base_color_texture": str(Path(texture_path).resolve())} if texture_path else {}),
                        },
                        "rigid_body": {"mass": 80.0, "restitution": 0.05, "dynamic": True},
                        "collider": {"half_extents": [0.45, 0.9, 0.45]},
                        **({"particle_physics": dict(player_particle_physics)} if player_particle_physics else {}),
                    },
                    {
                        "name": "Goal",
                        "transform": {"position": position(3.5, 0.8, 3.0), "scale": [1.2, 1.2, 1.2]},
                        "render": {"mesh": "builtin:cube", "base_color": [0.85, 0.2, 0.08], "roughness": 0.55},
                        "collider": {"half_extents": [0.6, 0.6, 0.6]},
                    },
                    {
                        "name": "Ground",
                        "transform": {"position": position(0.0, -0.25, 2.0), "scale": [18.0, 0.5, 18.0]},
                        "render": {"mesh": "builtin:cube", "base_color": [0.12, 0.16, 0.18], "roughness": 0.82},
                        "collider": {"half_extents": [9.0, 0.25, 9.0]},
                    },
                    {"name": "RuntimeCamera", "transform": {"position": position(0.0, 4.0, -14.0)}, "camera": {"active": True, "field_of_view": 58.0, "look_at": position(0.0, 1.0, 0.0)}},
                    {"name": "Sun", "light": {"direction": [-0.45, -1.0, -0.3], "color": [1.0, 0.93, 0.78], "intensity": 4.5, "casts_shadow": True, "angular_radius_degrees": 0.266}},
                    *([{
                        "name": "LightLabProbe",
                        "transform": {"position": position(0.0, 2.0, 1.0)},
                        "reflection_probe": {
                            "environment_texture": str(Path(texture_path).resolve()),
                            "half_extents": [8.0, 5.0, 8.0],
                            "intensity": 0.8,
                            "priority": 1,
                        },
                    }] if texture_path else []),
                ],
                "begin_play": [
                    {"node_id": "set_score", "operation": "variable.set", "arguments": ["score", 0], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 3}},
                    {"node_id": "spawn_marker", "operation": "entity.spawn", "arguments": ["SpawnedMarker", 1.5, 1.0, 2.0], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 4}},
                    {"node_id": "welcome", "operation": "event.emit", "arguments": ["SampleStarted"], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 5}},
                ],
                "tick": [
                    {"node_id": "clock", "operation": "time.accumulate", "arguments": ["elapsed"], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 9}},
                    {"node_id": "move", "operation": "input.move", "arguments": ["Player", 5.5], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 10}},
                    {"node_id": "read_player", "operation": "component.get_position", "arguments": ["Player", "player_position"], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 11}},
                    {"node_id": "ready", "operation": "branch.greater", "arguments": ["elapsed", 0.05, "RuntimeReady"], "source": {"file": "ConvertedThirdPerson.tcgraph", "line": 12}},
                ],
            },
        },
    )
    return save_federated_scene(destination, document)


if __name__ == "__main__":
    print(create_sample(Path(__file__).with_name("converted_unreal_vertical_slice.tcscene")))
