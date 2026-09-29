from __future__ import annotations

"""Executable qualification for common authored game-content workflows."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.asset_graph_compile_service import AssetGraphCompileService
from tech_connector.game_engine.assets.tc_collision_cook_service import cook_collision_asset, inspect_collision_asset
from tech_connector.game_engine.integration.playable_project_qualification_service import playable_project_source_fingerprint
from tech_connector.game_engine.runtime import (
    ProceduralAnimationRuntime, VehicleControlInput, VehicleDynamicsRuntime,
    VehicleRigSettings, WheelRigSettings, solve_two_bone_ik,
)
from tech_connector.game_engine.runtime.tc_simulation_service import create_cloth_grid


CONTENT_PRODUCTION_QUALIFICATION_SCHEMA = "tech_connector.content_production_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0


def qualify_content_production(
    source_root: str | Path, output_root: str | Path, *, maximum_total_seconds: float = 30.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    run_id = f"run-{time.time_ns()}"
    workspace = output / "runs" / run_id / "workspace"
    output.mkdir(parents=True, exist_ok=True)
    api = TCEditorAPI(workspace)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []

    def qualify(asset: Any, validate: Callable[[str], list[dict[str, Any]]], cook: Callable[[str], Any], *, extra: Mapping[str, bool] | None = None) -> None:
        record = api.database.asset(asset.asset_id)
        assert record is not None
        item_started = time.perf_counter()
        issues = validate(asset.asset_id)
        first = cook(asset.asset_id)
        first_bytes = first.path.read_bytes()
        second_bytes = cook(asset.asset_id).path.read_bytes()
        checks = {
            "validation": not any(str(issue.get("severity") or "").casefold() == "error" for issue in issues),
            "deterministic_cook": first_bytes == second_bytes,
            **dict(extra or {}),
        }
        rows.append({
            "asset_id": asset.asset_id, "type_id": record.asset_type,
            "status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "cook_sha256": hashlib.sha256(first_bytes).hexdigest(),
            "elapsed_seconds": round(time.perf_counter() - item_started, 6),
        })

    clip = api.create_animation_clip("Run", duration_seconds=0.8, sample_rate=30.0)
    blend = api.create_blend_space("Locomotion", samples=[{"clip_asset_id": clip.asset_id, "position": [0.0, 0.0]}])
    mask = api.create_animation_mask("UpperBody", weights={"spine": 1.0, "pelvis": 0.0})
    controller = api.create_animation_controller("HeroController")
    for asset in (clip, blend, mask, controller):
        extra = {"preview_evaluation": bool(api.evaluate_blend_space(asset.asset_id, 0.0))} if asset.asset_id == blend.asset_id else None
        qualify(asset, api.validate_animation_asset, api.cook_animation_asset, extra=extra)
    animation_interchange = api.export_animation_interchange([clip.asset_id, blend.asset_id, mask.asset_id, controller.asset_id])
    animation_roundtrip = api.import_animation_interchange(animation_interchange)

    cue = api.create_sound_cue("PlayerCue")
    mixer = api.create_audio_mixer("MainMixer")
    attenuation = api.create_audio_attenuation("WorldAttenuation")
    reverb = api.create_audio_reverb("RoomReverb", preset="room")
    for asset in (cue, mixer, attenuation, reverb):
        qualify(asset, api.validate_audio_asset, api.cook_audio_asset)
    unreal_audio = api.convert_unreal_audio({"engine_version": "qualification", "sound_cues": []})
    unity_audio = api.convert_unity_audio({"unity_version": "qualification", "audio_mixers": []})

    fields = [
        {"name": "id", "type": "string", "required": True, "default": ""},
        {"name": "power", "type": "int", "required": True, "default": 0},
    ]
    settings = api.create_project_settings("ProjectSettings")
    schema = api.create_data_schema("ItemSchema", fields=fields)
    struct = api.create_struct("ItemStruct", fields=fields)
    enum = api.create_enum("ItemRarity", entries=("Common", "Rare", "Legendary"))
    data = api.create_typed_data_asset("Sword", schema_asset_id=schema.asset_id, values={"id": "sword", "power": 10})
    table = api.create_data_table("Items", row_schema_id=schema.asset_id, rows=[{"id": "sword", "power": 10}])
    archetype = api.create_component_archetype("Pickup")
    character = api.create_character_definition("Hero")
    for asset in (settings, schema, struct, enum, data, table, archetype, character):
        qualify(asset, api.validate_gameplay_foundation_asset, api.cook_gameplay_foundation_asset)
    gameplay_class = api.create_gameplay_class("PickupActor", components=[{"id": "root", "name": "Root", "type": "transform", "parent_id": "", "properties": {}}])
    qualify(gameplay_class, api.validate_gameplay_class, api.compile_gameplay_class,
            extra={"debug_runtime": bool(api.debug_gameplay_class(gameplay_class.asset_id))})
    unreal_data = api.convert_unreal_data_assets({"engine_version": "qualification", "data_assets": [{"name": "UEItem", "object_path": "/Game/UEItem", "values": {"power": 7}}]})
    unity_data = api.convert_unity_scriptable_objects({"unity_version": "qualification", "scriptable_objects": [{"name": "UnityItem", "guid": "unity-item", "fields": {"power": 8}}]})

    material = api.create_material("HeroMaterial", preset="default_lit")
    instance = api.create_material_instance("HeroMaterialBlue", material.asset_id, overrides={"base_color": "#4080ff"})
    for asset in (material, instance):
        qualify(asset, api.validate_material, api.cook_material, extra={"resolved": bool(api.resolve_material(asset.asset_id))})
    shader = api.create_shader_graph("SurfaceShader", graph={
        "nodes": [{"id": "color", "title": "Uniform Parameter", "opcode": "parameter"},
                  {"id": "out", "title": "Shader Output", "opcode": "shader_output"}],
        "connections": [{"source": "color", "target": "out"}],
    })
    shader_first = api.compile_shader_graph(shader.asset_id, target="windows")
    shader_second = api.compile_shader_graph(shader.asset_id, target="windows")
    shader_checks = {"validation": not api.validate_shader_graph(shader.asset_id), "compile": bool(shader_first.get("succeeded")),
                     "deterministic_compile": json.dumps(shader_first, sort_keys=True, default=str) == json.dumps(shader_second, sort_keys=True, default=str)}
    rows.append({"asset_id": shader.asset_id, "type_id": "tc.shader_graph", "status": "passed" if all(shader_checks.values()) else "blocked", "checks": shader_checks})

    sequence = api.create_level_sequence("GameplayIntro", duration_frames=150, fps=30)
    binding = api.add_sequence_binding(sequence.asset_id, "Hero", object_id="level.hero")
    track = api.add_sequence_track(sequence.asset_id, "translation", "Hero Translation", binding_id=binding["id"])
    section = api.add_sequence_section(sequence.asset_id, track["id"], "Move", 0, 60)
    api.add_sequence_key(sequence.asset_id, track["id"], section["id"], "translation.x", 0, 0.0)
    api.add_sequence_key(sequence.asset_id, track["id"], section["id"], "translation.x", 30, 10.0)
    qualify(sequence, lambda asset_id: [], api.cook_level_sequence, extra={
        "timeline_evaluation": api.evaluate_level_sequence(sequence.asset_id, 15)["active_sections"][0]["evaluated_channels"]["translation.x"] == 5.0,
        "unreal_export": bool(api.sequence_to_unreal(api.get_level_sequence(sequence.asset_id))),
        "unity_export": bool(api.sequence_to_unity(api.get_level_sequence(sequence.asset_id))),
    })

    # Character simulation and optimization assets use direct editors rather
    # than generic node graphs.  Exercise their authored dependencies and
    # deterministic runtime products as one dependency-connected character.
    bones = [
        {"name": "pelvis", "parent": ""}, {"name": "spine", "parent": "pelvis"},
        {"name": "head", "parent": "spine"},
        {"name": "upperarm_l", "parent": "spine"}, {"name": "lowerarm_l", "parent": "upperarm_l"},
        {"name": "hand_l", "parent": "lowerarm_l"},
        {"name": "upperarm_r", "parent": "spine"}, {"name": "lowerarm_r", "parent": "upperarm_r"},
        {"name": "hand_r", "parent": "lowerarm_r"},
        {"name": "thigh_l", "parent": "pelvis"}, {"name": "calf_l", "parent": "thigh_l"},
        {"name": "foot_l", "parent": "calf_l"},
        {"name": "thigh_r", "parent": "pelvis"}, {"name": "calf_r", "parent": "thigh_r"},
        {"name": "foot_r", "parent": "calf_r"},
    ]
    source_skeleton = api.create_asset("tc.skeleton", "SourceSkeleton", properties={"bones": bones})
    target_skeleton = api.create_asset("tc.skeleton", "TargetSkeleton", properties={"bones": bones})
    source_ik = api.create_ik_rig("SourceIK", skeleton_id=source_skeleton.asset_id, bones=bones, retarget_root="pelvis")
    target_ik = api.create_ik_rig("TargetIK", skeleton_id=target_skeleton.asset_id, bones=bones, retarget_root="pelvis")
    retargeter = api.create_ik_retargeter("SourceToTarget", source_ik_rig_id=source_ik.asset_id, target_ik_rig_id=target_ik.asset_id)
    qualify(retargeter, api.validate_rig_asset, api.cook_rig_asset,
            extra={"automatic_mapping": bool(api.auto_map_ik_retargeter(retargeter.asset_id))})

    mesh = api.create_skeletal_mesh_asset("GarmentMesh", skeleton_id=target_skeleton.asset_id, bones=bones)
    skin = api.create_skin_binding("GarmentSkin", mesh_id=mesh.asset_id, skeleton_id=target_skeleton.asset_id,
                                   dcc_payload={"topology": {"vertex_count": 4, "face_count": 2, "fingerprint": "qualification"},
                                                "cluster": {"influences": [{"name": "pelvis"}],
                                                            "vertex_weights": [{"vertex_index": index, "weights": {"pelvis": 1.0}} for index in range(4)],
                                                            "max_influences": 4, "normalize": True}})
    api.assign_skin_binding(mesh.asset_id, skin.asset_id)
    fabric = api.create_fabric_material("Denim", preset="denim")
    graph_compiler = AssetGraphCompileService(api.database, api.registry)
    qualify(fabric, lambda asset_id: [], lambda asset_id: graph_compiler.compile_asset(asset_id, target="windows").artifact)
    cloth = api.create_cloth("Jacket", source_mesh_id=mesh.asset_id, skin_binding_id=skin.asset_id,
                             fabric_material_id=fabric.asset_id, vertex_count=4, fixed_vertices=[0],
                             transition_vertices={1: 0.5})
    api.set_cloth_map(cloth.asset_id, "drag", [1.0, 0.8, 0.6, 0.4])
    qualify(cloth, lambda asset_id: api.validate_cloth(asset_id, vertex_count=4), api.cook_cloth,
            extra={"skinning_preserved": bool(api.properties(cloth.asset_id).get("preserve_imported_skinning"))})

    hair = api.create_hair_material("BrownHair", preset="brown_hair")
    groom = api.create_groom("HeroGroom", groups=[{"name": "Scalp", "preset": "scalp", "curve_count": 1200,
                                                   "point_count": 19200, "guide_count": 120}],
                             material_ids=[hair.asset_id], lod_count=5)
    binding_asset = api.create_groom_binding("HeroGroomBinding", groom_id=groom.asset_id,
                                             target_skeletal_mesh_id=mesh.asset_id)
    projections = api.project_groom_binding(binding_asset.asset_id, [(0.2, 0.2, 0.02)],
                                            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)])
    for asset in (hair, groom, binding_asset):
        qualify(asset, api.validate_groom, api.cook_groom,
                extra={"root_projection": bool(projections)} if asset.asset_id == binding_asset.asset_id else None)

    optimization = api.create_geometry_optimization_profile("CharacterOptimization", source_asset_ids=[mesh.asset_id])
    qualify(optimization, api.validate_geometry_optimization, api.cook_geometry_optimization,
            extra={"execution_plan": bool(api.plan_geometry_optimization(optimization.asset_id))})
    constraint = api.create_physics_constraint("DoorHinge", first_body="Frame", second_body="Door", preset="door_hinge")
    qualify(constraint, api.validate_physics, api.cook_physics)

    # Direct-runtime asset families: compile the authored asset to stable IR and
    # execute the corresponding runtime backend, rather than treating a valid
    # property sheet as production evidence.
    def compiled(asset_id: str):
        receipt = AssetGraphCompileService(api.database, api.registry).compile_asset(asset_id, target="windows")
        if not receipt.succeeded or receipt.artifact is None:
            raise ValueError(f"Asset IR compilation failed for {asset_id}: {receipt.diagnostics}")
        return receipt.artifact

    procedural_animation = api.create_asset("tc.procedural_animation_profile", "Grounding", properties={
        "limbs": [{"name": "left", "root": "thigh_l", "joint": "calf_l", "end": "foot_l", "pole": [0, 0, 1]}],
        "pelvis_smoothing": 14.0, "maximum_pelvis_drop": 0.45, "global_weight": 1.0,
    })
    solved_joint, solved_end, stretch = solve_two_bone_ik(
        (0.0, 2.0, 0.0), (0.0, 1.0, 0.25), (0.0, 0.0, 0.0),
        (0.4, 0.2, 0.0), (0.0, 1.0, 1.0), maximum_stretch=1.05,
    )
    qualify(procedural_animation, lambda asset_id: [], compiled,
            extra={"runtime_solver": bool(ProceduralAnimationRuntime()) and solved_joint != solved_end and 1.0 <= stretch <= 1.05})

    simulation_profile = api.create_asset("tc.simulation_profile", "RealtimeCloth", properties={
        "solver": "cloth", "time_step": 1.0 / 60.0, "substeps": 2, "cache_policy": "live",
        "solver_graph": {"nodes": [], "connections": []},
    })
    simulation_world = create_cloth_grid(3, 3, spacing=0.25)
    before_y = simulation_world.particles[-1].position[1]
    simulation_world.step(1.0 / 60.0)
    qualify(simulation_profile, lambda asset_id: [], compiled,
            extra={"runtime_step": simulation_world.particles[-1].position[1] < before_y})

    collision = api.create_asset("tc.collision", "QualificationCollision", properties={
        "kind": "triangle_mesh", "source": "authored", "usage": ["query", "simulation"],
    })
    collision_path = workspace / "Derived" / "QualificationCollision.tccollision"
    collision_vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    collision_triangles = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    cook_collision_asset(collision_path, kind="triangle_mesh", vertices=collision_vertices, triangles=collision_triangles)
    first_collision = collision_path.read_bytes()
    cook_collision_asset(collision_path, kind="triangle_mesh", vertices=collision_vertices, triangles=collision_triangles)
    summary = inspect_collision_asset(collision_path)
    qualify(collision, lambda asset_id: [], compiled, extra={
        "native_collision_cook": first_collision == collision_path.read_bytes(),
        "native_collision_load": summary.vertex_count == 4 and summary.triangle_count == 4,
    })

    physical_material = api.create_asset("tc.physical_material", "Rubber", properties={
        "friction": 0.9, "restitution": 0.65, "density": 1100.0, "surface_type": "rubber",
    })
    material_values = api.properties(physical_material.asset_id)
    qualify(physical_material, lambda asset_id: [], compiled, extra={
        "runtime_coefficients": 0.0 <= float(material_values["friction"]) <= 1.0
                                and 0.0 <= float(material_values["restitution"]) <= 1.0
                                and float(material_values["density"]) > 0.0,
    })

    wheels = [
        {"name": "front_l", "mount": [-0.8, 0.0, 1.2], "steerable": True, "axle": "front"},
        {"name": "front_r", "mount": [0.8, 0.0, 1.2], "steerable": True, "axle": "front"},
        {"name": "rear_l", "mount": [-0.8, 0.0, -1.2], "axle": "rear"},
        {"name": "rear_r", "mount": [0.8, 0.0, -1.2], "axle": "rear"},
    ]
    vehicle = api.create_asset("tc.vehicle_rig", "SportsCar", properties={"mass": 1350.0, "engine_force": 8000.0, "wheels": wheels})
    runtime = VehicleDynamicsRuntime(VehicleRigSettings(engine_force=8000.0, anti_roll_stiffness=5000.0))
    wheel_settings = tuple(WheelRigSettings(row["name"], tuple(row["mount"]), steerable=bool(row.get("steerable")), axle=row["axle"]) for row in wheels)
    def flat_ground(origin, _direction, maximum_distance, _mask):
        if origin[1] < 0.0 or origin[1] > maximum_distance: return None
        return {"hit": True, "point": (origin[0], 0.0, origin[2]), "normal": (0.0, 1.0, 0.0),
                "distance": origin[1], "collider": "ground"}
    vehicle_frame = runtime.step(wheel_settings, (0.0, 0.55, 0.0), (0.0, 0.0, 4.0),
                                 VehicleControlInput(throttle=1.0, steering=0.5), flat_ground, delta_time=1.0 / 60.0)
    qualify(vehicle, lambda asset_id: [], compiled,
            extra={"runtime_dynamics": vehicle_frame.grounded_wheels == 4 and sum(w.drive_force for w in vehicle_frame.wheels) > 0.0})

    behavior_program = {
        "schema": "tech_connector.engine_graph_program.v1", "program_id": "qualification_behavior",
        "display_name": "Qualification Behavior", "entry_event": "On Begin Play", "version": 1,
        "flow": ["set_ready"], "nodes": [{
            "node_id": "set_ready", "operation": "variable.set", "display_name": "Set Ready",
            "inputs": {"name": {"mode": "literal", "literal": "ready"},
                       "value": {"mode": "literal", "literal": True}},
            "output_name": "result", "position": [0, 0], "enabled": True,
        }],
    }
    behavior = api.create_behavior("ReadyBehavior", program=behavior_program)
    behavior_run = api.execute_behavior_graph(behavior.asset_id)
    qualify(behavior, api.validate_behavior_graph, api.cook_behavior_graph, extra={
        "runtime_execution": behavior_run["status"] == "complete"
                             and behavior_run["runtime_state"]["metadata"]["variables"]["ready"] is True,
    })
    gameplay_program = {
        "schema": "tech_connector.engine_graph_program.v1", "program_id": "qualification_gameplay",
        "display_name": "Qualification Gameplay", "entry_event": "On Begin Play", "version": 1,
        "flow": ["emit_started"], "nodes": [{
            "node_id": "emit_started", "operation": "event.emit", "display_name": "Emit Started",
            "inputs": {"event": {"mode": "literal", "literal": "qualification.started"},
                       "payload": {"mode": "literal", "literal": {"source": "gameplay_graph"}}},
            "output_name": "result", "position": [0, 0], "enabled": True,
        }],
    }
    gameplay_graph = api.create_gameplay_graph("StartupGameplay", program=gameplay_program)
    gameplay_run = api.execute_behavior_graph(gameplay_graph.asset_id)
    qualify(gameplay_graph, api.validate_behavior_graph, api.cook_behavior_graph,
            extra={"runtime_execution": gameplay_run["status"] == "complete" and gameplay_run["events_emitted"] == 1})

    image_project = api.create_image_project("HeroIcon", width=32, height=32, layers=[
        {"name": "Background", "color": [20, 24, 32, 255]},
        {"name": "Accent", "color": [64, 128, 255, 192], "opacity": 0.75, "blend_mode": "Screen"},
    ])
    flattened = api.flatten_image_project(image_project.asset_id)
    qualify(image_project, api.validate_image_project, api.cook_image_project, extra={
        "ophanim_schema": api.properties(image_project.asset_id).get("schema") == "tech_connector_image_project_v1",
        "flattened_png": flattened.startswith(b"\x89PNG\r\n\x1a\n"),
    })

    interchange_checks = {
        "animation_roundtrip": bool(animation_roundtrip.get("succeeded")) and len(animation_roundtrip.get("asset_ids") or ()) == 4,
        "unreal_audio": bool(unreal_audio.get("succeeded")), "unity_audio": bool(unity_audio.get("succeeded")),
        "unreal_data": len(unreal_data.get("asset_ids") or ()) == 2, "unity_data": len(unity_data.get("asset_ids") or ()) == 2,
    }
    elapsed = time.perf_counter() - started
    qualified = sorted({row["type_id"] for row in rows})
    passed = all(row["status"] == "passed" for row in rows) and all(interchange_checks.values()) and elapsed <= float(maximum_total_seconds)
    receipt = {
        "schema": CONTENT_PRODUCTION_QUALIFICATION_SCHEMA, "status": "passed" if passed else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "maximum_total_seconds": float(maximum_total_seconds), "elapsed_seconds": round(elapsed, 6),
        "assets": rows, "interchange_checks": interchange_checks,
        "qualified_asset_types": qualified if passed else [],
    }
    report = output / "content_production_qualification.json"
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_content_production_qualification(source_root: str | Path, receipt: Mapping[str, Any] | None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != CONTENT_PRODUCTION_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed": gates.append("status")
    if not row.get("assets") or any(dict(item).get("status") != "passed" for item in row.get("assets") or ()): gates.append("assets")
    if not all(dict(row.get("interchange_checks") or {}).values()): gates.append("interchange")
    verified = _timestamp(row.get("verified_at")); now = datetime.now(timezone.utc).timestamp()
    if verified <= 0.0 or now - verified > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected: gates.append("source_fingerprint")
    return {"valid": not gates, "gates": sorted(set(gates)), "age_seconds": max(0.0, now - verified) if verified > 0 else None,
            "source_fingerprint": expected}


def load_content_production_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = ["CONTENT_PRODUCTION_QUALIFICATION_SCHEMA", "load_content_production_qualification", "qualify_content_production", "validate_content_production_qualification"]
