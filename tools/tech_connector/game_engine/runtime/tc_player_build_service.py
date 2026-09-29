"""Compile ``.tcscene`` archives into native TC player packages."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene
from tech_connector.game_engine.rendering.upscaling_service import create_upscaling_profile
from tech_connector.game_engine.rendering.lighting_profile_service import resolve_lighting_settings


RUNTIME_MANIFEST_SCHEMA = "tech_connector.runtime_manifest.v1"
SUPPORTED_RUNTIME_GRAPH_OPERATIONS = frozenset({
    "variable.set",
    "variable.add",
    "branch.greater",
    "event.emit",
    "entity.spawn",
    "component.set_position",
    "component.get_position",
    "input.move",
    "character.move",
    "character.jump",
    "camera.follow",
    "input.read_axis",
    "movement.calculate_velocity",
    "actor.set_velocity",
    "time.accumulate",
    "ui.set_text",
    "audio.play",
    "save.write",
    "animation.play",
    "animation.locomotion",
    "animation.stop",
    "animation.set_speed",
})


@dataclass(frozen=True)
class PlayerBuildReceipt:
    scene: Path
    runtime_manifest: Path
    player_executable: Path | None = None
    output_directory: Path | None = None
    assets: tuple[str, ...] = ()
    entities: int = 0
    graph_operations: int = 0
    warnings: tuple[str, ...] = ()
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": str(self.scene),
            "runtime_manifest": str(self.runtime_manifest),
            "player_executable": str(self.player_executable) if self.player_executable else "",
            "output_directory": str(self.output_directory) if self.output_directory else "",
            "assets": list(self.assets),
            "entities": self.entities,
            "graph_operations": self.graph_operations,
            "warnings": list(self.warnings),
            "validation": dict(self.validation),
        }


@dataclass(frozen=True)
class PlayInEditorSession:
    process: subprocess.Popen[str]
    receipt: PlayerBuildReceipt
    profile_log: Path

    def stop(self, timeout: float = 3.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()


def stable_runtime_asset_id(asset_type: str, source: str) -> str:
    payload = f"{asset_type.casefold()}\0{_canonical_asset_source(source)}".encode("utf-8")
    value = 1469598103934665603
    for byte in payload:
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"tc.asset.{value:016x}"


def compile_tcscene_for_runtime(
    scene_path: str | Path,
    output_path: str | Path | None = None,
) -> PlayerBuildReceipt:
    """Compile bounded player data from the authoritative scene archive."""

    source = Path(scene_path).expanduser().resolve()
    document, blobs = load_federated_scene(source)
    destination = Path(output_path).expanduser().resolve() if output_path else source.with_suffix(".tcruntime")
    destination.parent.mkdir(parents=True, exist_ok=True)
    runtime = dict(document.metadata.get("runtime_world") or {})
    rendering, sun_defaults = resolve_lighting_settings(runtime.get("rendering"))
    runtime["rendering"] = rendering
    rig_graph = document.rig_graph.to_dict()
    _materialize_rig_blobs(rig_graph, blobs, destination)
    graphs = _runtime_graphs(document.metadata, runtime)
    entities = _runtime_entities(rig_graph, runtime)
    for entity in entities:
        if not isinstance(entity.get("light"), dict):
            continue
        light = dict(sun_defaults)
        light.update(entity["light"])
        entity["light"] = light
    assets = _runtime_assets(entities, runtime, blobs, graphs, rig_graph)
    warnings: list[str] = []
    records = ["TCRUNTIME\t1"]
    for asset in assets:
        records.append("\t".join((
            "ASSET", asset["id"], asset["type"], _encode(asset["source"]), asset["content_hash"],
        )))
    for entity in entities:
        records.extend(_entity_records(entity, assets, warnings))
    records.extend(_physics_joint_records(
        runtime,
        {str(item.get("name") or item.get("id") or "Entity") for item in entities},
        warnings,
    ))
    records.extend(_rig_animation_records(rig_graph, warnings))
    records.extend(_skin_binding_records(rig_graph, assets, warnings))
    records.extend(_physical_animation_records(entities, rig_graph, warnings))
    records.append("HUD\t" + _encode(str(runtime.get("hud_text") or document.name)))
    records.append("SAVE\t" + _encode(str(runtime.get("save_slot") or "autosave")))
    rendering = dict(runtime.get("rendering") or {})
    profile_options: dict[str, Any] = {
        "sharpness": float(rendering.get("sharpness", 0.2)),
        "dynamic_resolution": bool(rendering.get("dynamic_resolution", False)),
        "minimum_scale": float(rendering.get("minimum_render_scale", 0.5)),
        "maximum_scale": float(rendering.get("maximum_render_scale", 1.0)),
    }
    if "render_scale" in rendering:
        profile_options["render_scale"] = float(rendering["render_scale"])
    profile = create_upscaling_profile(
        backend=str(rendering.get("upscaler") or "native"), quality=str(rendering.get("quality") or "native"),
        output_width=max(1, int(rendering.get("output_width") or 1920)), output_height=max(1, int(rendering.get("output_height") or 1080)),
        **profile_options,
    )
    environment_source = str(rendering.get("environment_texture") or "")
    environment_id = stable_runtime_asset_id("texture", environment_source) if environment_source else ""
    records.append("\t".join((
        "RENDERSETTINGS", _encode(profile.backend), _encode(profile.quality), _number(profile.render_scale),
        _number(rendering.get("exposure", 1.0)), _number(profile.sharpness), environment_id,
        _number(rendering.get("environment_intensity", 1.0)), _flag(profile.dynamic_resolution),
        _number(profile.minimum_scale), _number(profile.maximum_scale), _number(rendering.get("target_frame_ms", 16.6667)),
        _encode(str(rendering.get("lighting_model") or "physically_based")),
        _encode(str(rendering.get("global_illumination") or "probe")),
        *map(_number, _vector(rendering.get("sky_color"), 3, (0.08, 0.18, 0.42))),
        *map(_number, _vector(rendering.get("ground_color"), 3, (0.025, 0.035, 0.045))),
        _number(rendering.get("indirect_intensity", 1.0)), _number(rendering.get("toon_bands", 4.0)),
        _number(rendering.get("rim_intensity", 0.15)),
        _flag(rendering.get("dynamic_diffuse_gi", False)),
        _number(rendering.get("dynamic_gi_intensity", 0.35)),
        _number(rendering.get("dynamic_gi_distance", 12.0)),
        str(max(0, min(8, int(rendering.get("maximum_dynamic_gi_sources", 8))))),
        _flag(rendering.get("atmosphere_enabled", True)),
        _number(rendering.get("atmosphere_density", 1.0)),
        _number(rendering.get("atmospheric_haze", 1.0)),
        _number(rendering.get("horizon_falloff", 4.0)),
    )))
    simulation = dict(runtime.get("simulation") or {})
    gravity = _vector(simulation.get("gravity_meters_per_second_squared"), 3, (0.0, -9.80665, 0.0))
    records.append("\t".join((
        "SIMULATION", _encode(str(simulation.get("domain") or "everyday")),
        _real(simulation.get("meters_per_world_unit", 1.0)), _real(simulation.get("time_scale", 1.0)),
        *map(_real, gravity), _real(simulation.get("fixed_timestep_seconds", 1.0 / 120.0)),
        str(max(1, int(simulation.get("maximum_substeps", 8)))),
        _real(simulation.get("render_origin_threshold_world_units", 10000.0)),
        _real(simulation.get("gravity_softening_meters", 1.0)), _flag(simulation.get("floor_enabled", True)),
        _real(simulation.get("temperature_kelvin", 293.15)),
        _real(simulation.get("medium_viscosity_pascal_seconds", 0.001)),
        _real(simulation.get("relative_permittivity", 1.0)), str(max(0, int(simulation.get("random_seed", 1)))),
        _real(simulation.get("long_range_approximation_theta", 0.6)),
        str(max(1, int(simulation.get("joint_solver_iterations", 12)))),
        _real(simulation.get("sleep_linear_threshold", 0.05)),
        _real(simulation.get("sleep_angular_threshold", 0.05)),
        _real(simulation.get("sleep_delay_seconds", 0.5)),
        str(max(1, min(16, int(simulation.get("contact_solver_iterations", 4))))),
        _real(max(0.0, min(1.0, float(simulation.get("shock_propagation_factor", 0.35))))),
    )))
    operation_count = 0
    for phase, instruction in graphs:
        operation = str(instruction.get("operation") or "")
        if operation not in SUPPORTED_RUNTIME_GRAPH_OPERATIONS:
            warnings.append(f"Graph node {instruction.get('node_id') or '?'} uses unsupported runtime operation '{operation}'.")
            continue
        arguments = _graph_arguments(operation, instruction)
        source_location = dict(instruction.get("source") or {})
        records.append("\t".join((
            "GRAPH", phase,
            _encode(str(instruction.get("node_id") or f"node_{operation_count + 1}")),
            operation,
            _encode(str(source_location.get("file") or source.name)),
            str(max(0, int(source_location.get("line") or 0))),
            *(_encode(str(item)) for item in arguments),
        )))
        operation_count += 1
    destination.write_text("\n".join(records) + "\n", encoding="utf-8")
    return PlayerBuildReceipt(
        scene=source,
        runtime_manifest=destination,
        assets=tuple(asset["id"] for asset in assets),
        entities=len(entities),
        graph_operations=operation_count,
        warnings=tuple(warnings),
    )


def _physical_animation_records(
    entities: list[dict[str, Any]], rig_graph: dict[str, Any], warnings: list[str]
) -> list[str]:
    skeleton_id = str(dict(rig_graph.get("metadata") or {}).get("runtime_skeleton_id") or "tc.skeleton.scene")
    joint_rows = rig_graph.get("joints") or ()
    joint_values = joint_rows.values() if isinstance(joint_rows, dict) else joint_rows
    joint_ids = {
        str(item.get("id") or item.get("native_id") or "")
        for item in joint_values if isinstance(item, dict)
    }
    records: list[str] = []
    for entity in entities:
        settings = dict(entity.get("physical_animation") or {})
        if not settings:
            continue
        joint_id = str(settings.get("joint_id") or "")
        if joint_id not in joint_ids:
            warnings.append(f"Physical-animation body {entity.get('name') or '?'} references unknown joint '{joint_id}'.")
            continue
        records.append("\t".join((
            "PHYSANIM", _encode(skeleton_id), _encode(joint_id), _encode(str(entity.get("name") or "")),
            _real(settings.get("pose_drive_strength", 0.8)), _real(settings.get("damping", 0.5)),
            _real(settings.get("maximum_force", 10000.0)), _real(settings.get("physics_blend", 1.0)),
            _real(settings.get("muscle_strength", 1.0)),
        )))
    return records


def _rig_animation_records(rig_graph: dict[str, Any], warnings: list[str]) -> list[str]:
    raw_joints = rig_graph.get("joints") or ()
    joint_rows = raw_joints.values() if isinstance(raw_joints, dict) else raw_joints
    joints = {
        str(joint.get("id") or joint.get("native_id") or ""): dict(joint)
        for joint in joint_rows if isinstance(joint, dict) and str(joint.get("id") or joint.get("native_id") or "")
    }
    if not joints:
        return []
    if len(joints) > 65535:
        raise ValueError("Native runtime skeletons support at most 65,535 joints.")
    skeleton_id = str(dict(rig_graph.get("metadata") or {}).get("runtime_skeleton_id") or "tc.skeleton.scene")
    ordered: list[str] = []
    remaining = set(joints)
    while remaining:
        ready = sorted(joint_id for joint_id in remaining if not str(joints[joint_id].get("parent_id") or "") or str(joints[joint_id].get("parent_id") or "") in ordered)
        if not ready:
            raise ValueError("The runtime skeleton contains a parent cycle or missing parent joint.")
        ordered.extend(ready)
        remaining.difference_update(ready)
    records = ["\t".join(("SKELETON", _encode(skeleton_id), str(len(ordered))))]
    for joint_id in ordered:
        joint = joints[joint_id]
        matrix = list(joint.get("local_matrix") or ())
        if len(matrix) != 16:
            raise ValueError(f"Joint {joint_id} has no valid 4x4 local matrix.")
        records.append("\t".join((
            "JOINT", _encode(skeleton_id), _encode(joint_id),
            _encode(str(joint.get("parent_id") or "")), _encode(str(joint.get("name") or joint_id)),
            *(_real(value) for value in matrix),
        )))
    raw_animation = rig_graph.get("animation") or ()
    animation_rows = raw_animation.values() if isinstance(raw_animation, dict) else raw_animation
    takes = {
        str(item.get("id") or ""): dict(item)
        for item in animation_rows if isinstance(item, dict) and str(item.get("id") or "")
    }
    for take_id, raw_take in sorted(takes.items()):
        take = dict(raw_take or {})
        if str(take.get("type") or "") != "animation_take":
            continue
        start = int(take.get("start_frame", 1) or 1)
        end = int(take.get("end_frame", start) or start)
        fps = max(1.0e-6, float(take.get("frame_rate", 24.0) or 24.0))
        records.append("\t".join((
            "ANIMATION", _encode(str(take_id)), _encode(str(take.get("name") or take_id)),
            _encode(skeleton_id), str(start), str(max(start, end)), _real(fps), _flag(take.get("loop", True)),
        )))
        layers = dict(take.get("layers") or {})
        soloed = {name for name, layer in layers.items() if isinstance(layer, dict) and bool(layer.get("solo"))}
        for layer_name, raw_layer in layers.items():
            layer = dict(raw_layer or {})
            if bool(layer.get("muted")) or (soloed and layer_name not in soloed):
                continue
            weight = max(0.0, min(1.0, float(layer.get("weight", 1.0) or 0.0)))
            for curve_id, raw_curve in sorted(dict(layer.get("curves") or {}).items()):
                curve = dict(raw_curve or {})
                node_id = str(curve.get("node_id") or "")
                if node_id not in joints:
                    warnings.append(f"Animation curve {curve_id} targets non-joint node {node_id}; bake the control rig to joints for runtime.")
                    continue
                keys = sorted((dict(item) for item in curve.get("keys") or () if isinstance(item, dict)), key=lambda item: float(item.get("frame", 0.0)))
                if not keys:
                    continue
                if len(keys) > 1_000_000:
                    raise ValueError(f"Animation curve {curve_id} exceeds the runtime key limit.")
                key_values: list[str] = []
                for key in keys:
                    key_values.extend((
                        _real(key.get("frame", 0.0)), _real(key.get("value", 0.0)),
                        _encode(str(key.get("interpolation") or "auto")),
                    ))
                records.append("\t".join((
                    "ANIMCURVE", _encode(str(take_id)), _encode(node_id),
                    _encode(str(curve.get("attribute") or "")), _real(weight),
                    _flag(layer.get("additive", False)), str(len(keys)), *key_values,
                )))
    return records


_RIG_BLOB_FIELDS = (
    "inverse_bind_blob", "rest_positions_blob", "influence_offsets_blob", "joint_indices_blob", "weights_blob",
)


def _rig_rows(rig_graph: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = rig_graph.get(key) or ()
    rows = values.values() if isinstance(values, dict) else values
    return [dict(item) for item in rows if isinstance(item, dict)]


def _materialize_rig_blobs(rig_graph: dict[str, Any], blobs: dict[str, bytes], destination: Path) -> None:
    # Sidecars use a manifest-relative, content-addressed name. Absolute output
    # paths made identical scene compiles produce different asset IDs and bytes.
    asset_directory = destination.parent / "RuntimeAssets"
    for skin in _rig_rows(rig_graph, "skins"):
        source_skin = next((item for item in rig_graph.get("skins", ()) if isinstance(item, dict) and str(item.get("id")) == str(skin.get("id"))), None) if not isinstance(rig_graph.get("skins"), dict) else rig_graph["skins"].get(str(skin.get("id")))
        if not isinstance(source_skin, dict):
            continue
        for field_name in _RIG_BLOB_FIELDS:
            key = str(source_skin.get(field_name) or "").removeprefix("blobs/")
            payload = blobs.get(key)
            if payload is None:
                continue
            asset_directory.mkdir(parents=True, exist_ok=True)
            target = asset_directory / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}_{Path(key).name}"
            target.write_bytes(payload)
            logical_source = f"RuntimeAssets/{target.name}"
            blobs[logical_source] = payload
            source_skin[field_name] = logical_source


def _skin_binding_records(rig_graph: dict[str, Any], assets: list[dict[str, str]], warnings: list[str]) -> list[str]:
    asset_ids = {(item["type"], _canonical_asset_source(item["source"])): item["id"] for item in assets}
    records: list[str] = []
    for skin in _rig_rows(rig_graph, "skins"):
        joint_ids = [str(item) for item in skin.get("joint_ids") or ()]
        if not joint_ids:
            warnings.append(f"Skin {skin.get('id') or '?'} has no joints and was omitted from the runtime.")
            continue
        paths = [str(skin.get(field_name) or "") for field_name in _RIG_BLOB_FIELDS]
        if any(not value for value in paths):
            warnings.append(f"Skin {skin.get('id') or '?'} is missing one or more runtime sidecars.")
            continue
        ids = [asset_ids.get(("rig_blob", _canonical_asset_source(value)), "") for value in paths]
        if any(not value for value in ids):
            warnings.append(f"Skin {skin.get('id') or '?'} could not resolve its runtime sidecar assets.")
            continue
        records.append("\t".join((
            "SKIN", _encode(str(skin.get("id") or "")), _encode(str(skin.get("mesh_id") or "")),
            _encode("tc.skeleton.scene"), _encode(str(skin.get("deformation_mode") or "linear_blend_skinning")),
            str(max(0, int(skin.get("vertex_count", 0) or 0))),
            str(max(0, int(skin.get("max_influences_per_vertex", 0) or 0))), str(len(joint_ids)),
            *(_encode(joint_id) for joint_id in joint_ids), *ids,
        )))
    return records


def build_windows_player(
    scene_path: str | Path,
    output_directory: str | Path,
    *,
    player_executable: str | Path | None = None,
) -> PlayerBuildReceipt:
    """Create a self-contained Windows player folder from a ``.tcscene``."""

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = _resolve_player_executable(player_executable)
    compiled = compile_tcscene_for_runtime(scene_path, output / "Content" / "main.tcruntime")
    _collect_player_assets(compiled.runtime_manifest, output)
    asset_validation = validate_packaged_assets(compiled.runtime_manifest, output)
    target_executable = output / "TCPlayer.exe"
    shutil.copy2(executable, target_executable)
    runtime_dll = executable.with_name("tc_graph_runtime.dll")
    if not runtime_dll.is_file():
        raise FileNotFoundError(f"Native runtime DLL is missing beside the player: {runtime_dll}")
    shutil.copy2(runtime_dll, output / runtime_dll.name)
    launch_script = output / "Play.cmd"
    launch_script.write_text('@echo off\r\n"%~dp0TCPlayer.exe" --scene "%~dp0Content\\main.tcruntime"\r\n', encoding="ascii")
    validation = validate_player_package(output)
    validation["assets"] = asset_validation
    build_info = {
        "schema": "tech_connector.windows_player_build.v1",
        "source_scene": str(compiled.scene),
        "runtime_manifest": "Content/main.tcruntime",
        "player": "TCPlayer.exe",
        "entities": compiled.entities,
        "assets": list(compiled.assets),
        "graph_operations": compiled.graph_operations,
        "warnings": list(compiled.warnings),
        "platform_capabilities": runtime_platform_capabilities(),
        "validation": validation,
    }
    (output / "TC_PLAYER_BUILD.json").write_text(json.dumps(build_info, indent=2), encoding="utf-8")
    return PlayerBuildReceipt(
        scene=compiled.scene,
        runtime_manifest=compiled.runtime_manifest,
        player_executable=target_executable,
        output_directory=output,
        assets=compiled.assets,
        entities=compiled.entities,
        graph_operations=compiled.graph_operations,
        warnings=compiled.warnings,
        validation=validation,
    )


def runtime_platform_capabilities(platform_name: str | None = None) -> dict[str, Any]:
    """Report shipped runtime support without implying unimplemented renderer backends."""
    current = str(platform_name or ("windows" if os.name == "nt" else os.name)).casefold()
    return {
        "schema": "tech_connector.runtime_platform_capabilities.v1",
        "build_host": current,
        "targets": {
            "windows": {
                "package_builder": True,
                "windowed_player": True,
                "headless_player": True,
                "renderer": "Direct3D 11",
            },
            "linux": {
                "package_builder": False,
                "windowed_player": False,
                "headless_player": True,
                "renderer": "none",
            },
            "macos": {
                "package_builder": False,
                "windowed_player": False,
                "headless_player": True,
                "renderer": "none",
            },
        },
        "limitations": [
            "Packaged graphical builds currently target Windows and Direct3D 11 only.",
            "Non-Windows native builds provide the headless runtime; Vulkan and Metal backends are not implemented.",
        ],
    }


def validate_player_package(output_directory: str | Path, *, frames: int = 2, timeout: float = 30.0) -> dict[str, Any]:
    """Run the packaged executable headlessly and reject loader or graph failures."""
    output = Path(output_directory).expanduser().resolve()
    executable = output / "TCPlayer.exe"
    manifest = output / "Content" / "main.tcruntime"
    profile = output / "Content" / "build-validation-profile.jsonl"
    if not executable.is_file() or not manifest.is_file():
        raise FileNotFoundError("Player package validation requires TCPlayer.exe and Content/main.tcruntime.")
    profile.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(executable), "--scene", str(manifest), "--headless", "--frames", str(max(1, int(frames))), "--trace-graph", "--log", str(profile)],
        cwd=output,
        capture_output=True,
        text=True,
        timeout=max(1.0, float(timeout)),
        check=False,
    )
    diagnostic = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    profile_lines = profile.read_text(encoding="utf-8").splitlines() if profile.is_file() else []
    graph_errors = [line for line in diagnostic.splitlines() + profile_lines if "error:" in line.casefold()]
    if completed.returncode != 0 or "TC_PLAYER_OK" not in completed.stdout or graph_errors:
        detail = "\n".join(graph_errors or diagnostic.splitlines()[-20:])
        raise RuntimeError(f"Packaged player validation failed (exit {completed.returncode}).\n{detail}")
    summary = summarize_player_profile(profile)
    frame_profiles = summary["frame_profiles"]
    if len(frame_profiles) < max(1, int(frames)):
        raise RuntimeError("Packaged player validation did not produce the expected frame profiles.")
    return {
        "status": "passed",
        "frames": len(frame_profiles),
        "exit_code": completed.returncode,
        "profile": "Content/build-validation-profile.jsonl",
        "profile_summary": {key: value for key, value in summary.items() if key != "frame_profiles"},
    }


def summarize_player_profile(profile_path: str | Path) -> dict[str, Any]:
    """Parse mixed JSON frame profiles and graph diagnostics into useful timing evidence."""
    path = Path(profile_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    frame_profiles: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    graph_trace: list[str] = []
    for line in lines:
        if not line.startswith("{"):
            stripped = line.strip()
            if stripped.startswith("OK "):
                graph_trace.append(stripped)
            elif stripped:
                diagnostics.append(stripped)
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"Malformed profile row: {line[:240]}")
            continue
        if isinstance(row, dict) and row.get("type") == "frame":
            frame_profiles.append(row)
    def timing(name: str) -> dict[str, float]:
        values = sorted(float(row.get(name, 0.0) or 0.0) for row in frame_profiles)
        if not values:
            return {"average_ms": 0.0, "p95_ms": 0.0, "maximum_ms": 0.0}
        p95_index = min(len(values) - 1, max(0, int((len(values) * 0.95) + 0.999999) - 1))
        return {
            "average_ms": sum(values) / len(values),
            "p95_ms": values[p95_index],
            "maximum_ms": values[-1],
        }
    return {
        "frames": len(frame_profiles),
        "frame": timing("frame_ms"),
        "graph": timing("graph_ms"),
        "physics": timing("physics_ms"),
        "gpu": timing("gpu_ms"),
        "diagnostics": diagnostics,
        "graph_trace": graph_trace,
        "frame_profiles": frame_profiles,
    }


def validate_packaged_assets(manifest_path: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Verify every copied content asset against the compiler's content hash."""
    manifest = Path(manifest_path)
    output = Path(output_directory).resolve()
    verified: list[str] = []
    total_bytes = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        row = line.split("\t")
        if len(row) < 5 or row[0] != "ASSET":
            continue
        source = _decode(row[3]).replace("\\", "/")
        if not source.startswith("Content/Assets/"):
            continue
        target = (output / Path(source)).resolve()
        try:
            target.relative_to(output)
        except ValueError as exc:
            raise RuntimeError(f"Packaged asset escapes the output directory: {source}") from exc
        if not target.is_file():
            raise FileNotFoundError(f"Packaged asset is missing: {source}")
        actual_hash = _source_hash(str(target), {})
        if actual_hash != row[4]:
            raise RuntimeError(f"Packaged asset hash mismatch: {row[1]}")
        verified.append(row[1])
        total_bytes += target.stat().st_size
    return {"status": "passed", "verified_assets": verified, "verified_count": len(verified), "verified_bytes": total_bytes}


def launch_play_in_editor(
    scene_path: str | Path,
    *,
    player_executable: str | Path | None = None,
    working_directory: str | Path | None = None,
) -> PlayInEditorSession:
    """Launch PIE through the standalone player executable, never an editor-only loop."""

    executable = _resolve_player_executable(player_executable)
    workspace = Path(working_directory).expanduser().resolve() if working_directory else Path(scene_path).resolve().parent / ".tech_connector" / "pie"
    workspace.mkdir(parents=True, exist_ok=True)
    receipt = compile_tcscene_for_runtime(scene_path, workspace / "current.tcruntime")
    profile_log = workspace / "runtime-profile.jsonl"
    profile_log.unlink(missing_ok=True)
    process = subprocess.Popen(
        [str(executable), "--scene", str(receipt.runtime_manifest), "--pie", "--log", str(profile_log)],
        cwd=executable.parent,
        text=True,
    )
    return PlayInEditorSession(process=process, receipt=receipt, profile_log=profile_log)


def _runtime_entities(rig_graph: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = [dict(item) for item in runtime.get("entities") or () if isinstance(item, dict)]
    if explicit:
        return explicit
    entities: list[dict[str, Any]] = []
    for node_id, node in dict(rig_graph.get("nodes") or {}).items():
        node = dict(node or {})
        node_type = str(node.get("node_type") or node.get("contract_node_type") or "")
        if "mesh" not in node_type and "transform" not in node_type:
            continue
        transform = dict(node.get("transform") or node.get("local_transform") or {})
        entities.append({
            "name": str(node.get("name") or node_id),
            "transform": transform,
            "render": {"mesh": str(node.get("mesh_asset") or "builtin:cube")},
            "collider": {"half_extents": [0.5, 0.5, 0.5]},
        })
    if not entities:
        entities.append({
            "name": "Player",
            "transform": {"position": [0.0, 2.0, 0.0]},
            "render": {"mesh": "builtin:cube", "base_color": [0.08, 0.62, 0.88], "roughness": 0.32},
            "rigid_body": {"dynamic": True, "mass": 1.0},
            "collider": {"half_extents": [0.5, 0.5, 0.5]},
        })
    names = {str(item.get("name") or "") for item in entities}
    if "RuntimeCamera" not in names:
        entities.append({"name": "RuntimeCamera", "transform": {"position": [0.0, 4.0, -14.0]}, "camera": {"active": True}})
    if "Sun" not in names:
        entities.append({"name": "Sun", "light": {"direction": [-0.4, -1.0, -0.25], "intensity": 4.0, "casts_shadow": True}})
    return entities


def _runtime_assets(
    entities: list[dict[str, Any]],
    runtime: dict[str, Any],
    blobs: dict[str, bytes],
    graphs: list[tuple[str, dict[str, Any]]],
    rig_graph: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    declared = [dict(item) for item in runtime.get("assets") or () if isinstance(item, dict)]
    for item in declared:
        asset_type = str(item.get("type") or "data")
        source = str(item.get("source") or "")
        asset_id = str(item.get("id") or stable_runtime_asset_id(asset_type, source))
        rows[asset_id] = {
            "id": asset_id, "type": asset_type, "source": source,
            "content_hash": str(item.get("content_hash") or _source_hash(source, blobs)),
        }
    for entity in entities:
        render = dict(entity.get("render") or {})
        for key, asset_type, default in (("mesh", "mesh", "builtin:cube"), ("material", "material", "builtin:default_pbr")):
            source = str(render.get(key) or default)
            asset_id = stable_runtime_asset_id(asset_type, source)
            rows.setdefault(asset_id, {"id": asset_id, "type": asset_type, "source": source, "content_hash": _source_hash(source, blobs)})
        for key in ("base_color_texture", "normal_texture", "roughness_texture", "metallic_texture", "emission_texture"):
            source = str(render.get(key) or "")
            if source:
                asset_id = stable_runtime_asset_id("texture", source)
                rows.setdefault(asset_id, {"id": asset_id, "type": "texture", "source": source, "content_hash": _source_hash(source, blobs)})
        collider_source = str(dict(entity.get("collider") or {}).get("collision_asset") or "")
        if collider_source:
            asset_id = stable_runtime_asset_id("collision", collider_source)
            rows.setdefault(asset_id, {
                "id": asset_id, "type": "collision", "source": collider_source,
                "content_hash": _source_hash(collider_source, blobs),
            })
        probe_source = str(dict(entity.get("reflection_probe") or {}).get("environment_texture") or "")
        if probe_source:
            asset_id = stable_runtime_asset_id("texture", probe_source)
            rows.setdefault(asset_id, {"id": asset_id, "type": "texture", "source": probe_source, "content_hash": _source_hash(probe_source, blobs)})
    environment_source = str(dict(runtime.get("rendering") or {}).get("environment_texture") or "")
    if environment_source:
        asset_id = stable_runtime_asset_id("texture", environment_source)
        rows.setdefault(asset_id, {"id": asset_id, "type": "texture", "source": environment_source, "content_hash": _source_hash(environment_source, blobs)})
    for _, instruction in graphs:
        if str(instruction.get("operation") or "") != "audio.play":
            continue
        raw = instruction.get("arguments")
        source = str(raw[0]) if isinstance(raw, list) and raw else str(dict(dict(instruction.get("inputs") or {}).get("asset") or {}).get("literal") or "")
        if source:
            asset_id = stable_runtime_asset_id("audio", source)
            rows.setdefault(asset_id, {"id": asset_id, "type": "audio", "source": source, "content_hash": _source_hash(source, blobs)})
    for skin in _rig_rows(dict(rig_graph or {}), "skins"):
        for field_name in _RIG_BLOB_FIELDS:
            source = str(skin.get(field_name) or "")
            if not source:
                continue
            asset_id = stable_runtime_asset_id("rig_blob", source)
            rows.setdefault(asset_id, {"id": asset_id, "type": "rig_blob", "source": source, "content_hash": _source_hash(source, blobs)})
    return [rows[key] for key in sorted(rows)]


def _runtime_graphs(metadata: dict[str, Any], runtime: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    for phase_key, phase in (("begin_play", "begin"), ("tick", "tick")):
        for instruction in runtime.get(phase_key) or ():
            if isinstance(instruction, dict):
                result.append((phase, dict(instruction)))
    stored_programs = metadata.get("engine_graph_programs") or ()
    program_values = stored_programs.values() if isinstance(stored_programs, dict) else stored_programs
    for stored_program in program_values:
        if not isinstance(stored_program, dict):
            continue
        program = stored_program.get("program", stored_program)
        if not isinstance(program, dict):
            continue
        phase = "begin" if str(program.get("entry_event") or "").casefold() == "on begin play" else "tick"
        nodes = {str(item.get("node_id") or ""): item for item in program.get("nodes") or () if isinstance(item, dict)}
        for node_id in program.get("flow") or nodes:
            if str(node_id) in nodes:
                result.append((phase, dict(nodes[str(node_id)])))
    return result


def _physics_joint_records(
    runtime: dict[str, Any], entity_names: set[str], warnings: list[str],
) -> list[str]:
    """Compile body constraints separately from skeletal rig joints."""

    records: list[str] = []
    supported = {"fixed", "ball", "hinge", "slider", "distance", "spring", "cone_twist", "six_dof"}
    seen: set[str] = set()
    for index, source in enumerate(runtime.get("physics_joints") or ()):
        if not isinstance(source, dict):
            warnings.append(f"Physics joint {index + 1} is not an object and was skipped.")
            continue
        joint = dict(source)
        joint_id = str(joint.get("id") or f"physics_joint_{index + 1}")
        kind = str(joint.get("type") or "fixed").casefold().replace("-", "_")
        first = str(joint.get("first") or joint.get("body_a") or "")
        second = str(joint.get("second") or joint.get("body_b") or "")
        if joint_id in seen:
            warnings.append(f"Duplicate physics joint id '{joint_id}' was skipped.")
            continue
        if kind not in supported:
            warnings.append(f"Physics joint '{joint_id}' has unsupported type '{kind}' and was skipped.")
            continue
        if not first or not second or first == second or first not in entity_names or second not in entity_names:
            warnings.append(f"Physics joint '{joint_id}' must connect two different runtime entities and was skipped.")
            continue
        seen.add(joint_id)
        first_anchor = _vector(joint.get("first_anchor") or joint.get("anchor_a"), 3, (0.0, 0.0, 0.0))
        second_anchor = _vector(joint.get("second_anchor") or joint.get("anchor_b"), 3, (0.0, 0.0, 0.0))
        axis = _vector(joint.get("axis"), 3, (1.0, 0.0, 0.0))
        records.append("\t".join((
            "PHYSICSJOINT", _encode(joint_id), kind, _encode(first), _encode(second),
            *map(_real, first_anchor + second_anchor + axis),
            _real(joint.get("minimum_limit", joint.get("min_limit", 0.0))),
            _real(joint.get("maximum_limit", joint.get("max_limit", 0.0))),
            _number(joint.get("stiffness", 1.0)), _number(joint.get("damping", 0.1)),
            _real(joint.get("motor_target_velocity", 0.0)), _real(joint.get("motor_maximum_force", 0.0)),
            _real(joint.get("break_force", 0.0)), _real(joint.get("break_torque", 0.0)),
            _flag(joint.get("limits_enabled", False)), _flag(joint.get("motor_enabled", False)),
            _flag(joint.get("collision_enabled", False)), _flag(joint.get("enabled", True)),
        )))
        if kind == "six_dof":
            records.append("\t".join((
                "JOINT6DOF", _encode(joint_id),
                *map(_real, _vector(joint.get("linear_lower_limit"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("linear_upper_limit"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_lower_limit"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_upper_limit"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("linear_spring_stiffness"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("linear_spring_damping"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_spring_stiffness"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_spring_damping"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("linear_drive_velocity"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_drive_velocity"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("linear_drive_maximum_force"), 3, (0.0, 0.0, 0.0))),
                *map(_real, _vector(joint.get("angular_drive_maximum_force"), 3, (0.0, 0.0, 0.0))),
            )))
    return records


def _entity_records(entity: dict[str, Any], assets: list[dict[str, str]], warnings: list[str]) -> list[str]:
    name = str(entity.get("name") or entity.get("id") or "Entity")
    transform = dict(entity.get("transform") or {})
    position = _vector(transform.get("position"), 3, (0.0, 0.0, 0.0))
    rotation = _vector(transform.get("rotation"), 3, (0.0, 0.0, 0.0))
    scale = _vector(transform.get("scale"), 3, (1.0, 1.0, 1.0))
    records = ["ENTITY\t" + _encode(name), "\t".join((
        "TRANSFORM", _encode(name), *map(_real, position), *map(_number, rotation + scale),
    ))]
    render = dict(entity.get("render") or {})
    if render:
        mesh = str(render.get("mesh") or "builtin:cube")
        material = str(render.get("material") or "builtin:default_pbr")
        base = _vector(render.get("base_color"), 3, (0.18, 0.62, 0.82))
        texture_ids = [stable_runtime_asset_id("texture", str(render.get(key))) if render.get(key) else "" for key in (
            "base_color_texture", "normal_texture", "roughness_texture", "metallic_texture", "emission_texture",
        )]
        records.append("\t".join((
            "RENDER", _encode(name), stable_runtime_asset_id("mesh", mesh), stable_runtime_asset_id("material", material),
            *map(_number, base), _number(render.get("metallic", 0.0)), _number(render.get("roughness", 0.45)), _flag(render.get("casts_shadow", True)), *texture_ids,
            _encode(str(render.get("skin_binding") or "")),
        )))
    rigid = dict(entity.get("rigid_body") or {})
    if rigid:
        velocity = _vector(rigid.get("velocity"), 3, (0.0, 0.0, 0.0))
        angular_velocity = _vector(rigid.get("angular_velocity"), 3, (0.0, 0.0, 0.0))
        records.append("\t".join((
            "RIGID", _encode(name), *map(_real, velocity), _real(rigid.get("mass", 1.0)),
            _number(rigid.get("restitution", 0.2)), _flag(rigid.get("dynamic", True)),
            *map(_real, angular_velocity), _number(rigid.get("linear_damping", 0.01)),
            _number(rigid.get("angular_damping", 0.05)), _number(rigid.get("gravity_scale", 1.0)),
            _flag(rigid.get("kinematic", False)), _flag(rigid.get("continuous_collision", False)),
            *map(_real, _vector(rigid.get("inertia_diagonal"), 3, (1.0, 1.0, 1.0))),
            _flag(rigid.get("allow_sleep", True)), _flag(rigid.get("start_sleeping", False)),
        )))
    collider = dict(entity.get("collider") or {})
    if collider:
        extents = _vector(collider.get("half_extents"), 3, (0.5, 0.5, 0.5))
        collision_source = str(collider.get("collision_asset") or "")
        records.append("\t".join((
            "COLLIDER", _encode(name), *map(_real, extents), _flag(collider.get("trigger", False)),
            _encode(str(collider.get("shape") or "box")), _real(collider.get("radius", 0.5)),
            _real(collider.get("half_height", 0.5)), str(max(0, int(collider.get("layer", 1)))),
            str(max(0, int(collider.get("mask", 0xFFFFFFFF)))), _number(collider.get("friction", 0.5)),
            _number(collider.get("restitution", 0.2)),
            stable_runtime_asset_id("collision", collision_source) if collision_source else "",
        )))
    particle = dict(entity.get("particle_physics") or {})
    if particle:
        records.append("\t".join((
            "PARTICLE", _encode(name), _real(particle.get("radius_meters", 1.0e-9)),
            _real(particle.get("charge_coulombs", 0.0)), _real(particle.get("lennard_jones_epsilon_joules", 0.0)),
            _real(particle.get("lennard_jones_sigma_meters", 1.0e-9)),
            _real(particle.get("rest_density_kg_per_m3", 1000.0)),
            _real(particle.get("viscosity_pascal_seconds", 0.001)),
            _real(particle.get("pressure_stiffness", 2000.0)), _flag(particle.get("thermal_motion", True)), "0",
        )))
    camera = dict(entity.get("camera") or {})
    if camera:
        look_at = _vector(camera.get("look_at"), 3, (0.0, 1.0, 0.0))
        records.append("\t".join(("CAMERA", _encode(name), _number(camera.get("field_of_view", 55.0)), _number(camera.get("near_plane", 0.05)), _number(camera.get("far_plane", 5000.0)), _flag(camera.get("active", True)), *map(_real, look_at))))
    light = dict(entity.get("light") or {})
    if light:
        direction = _vector(light.get("direction"), 3, (-0.4, -1.0, -0.25))
        color = _vector(light.get("color"), 3, (1.0, 0.95, 0.85))
        records.append("\t".join(("LIGHT", _encode(name), *map(_number, direction + color), _number(light.get("intensity", 4.0)), _flag(light.get("casts_shadow", True)), _number(light.get("angular_radius_degrees", 0.266)))))
    probe = dict(entity.get("reflection_probe") or {})
    if probe:
        source = str(probe.get("environment_texture") or "")
        extents = _vector(probe.get("half_extents"), 3, (5.0, 5.0, 5.0))
        records.append("\t".join((
            "PROBE", _encode(name), stable_runtime_asset_id("texture", source) if source else "",
            *map(_number, extents), _number(probe.get("intensity", 1.0)), str(int(probe.get("priority", 0))),
        )))
    return records


def _graph_arguments(operation: str, instruction: dict[str, Any]) -> list[Any]:
    raw = instruction.get("arguments")
    if isinstance(raw, list):
        values = raw
        if operation == "audio.play" and values:
            return [stable_runtime_asset_id("audio", str(values[0]))]
        return values
    inputs = dict(instruction.get("inputs") or {})
    def binding_value(key: str, default: Any = "") -> Any:
        binding = dict(inputs.get(key) or {})
        if str(binding.get("mode") or "").casefold() == "link" and binding.get("source_node"):
            output = str(binding.get("source_output") or "result")
            return f"@graph:{binding['source_node']}:{output}"
        return binding.get("literal", default)

    keys = {
        "variable.set": ("name", "value"), "variable.add": ("name", "amount"),
        "branch.greater": ("name", "threshold", "event"), "event.emit": ("event",),
        "entity.spawn": ("name", "x", "y", "z"), "component.set_position": ("target", "x", "y", "z"),
        "component.get_position": ("target", "variable"), "input.move": ("target", "speed"),
        "character.move": ("target", "speed", "acceleration", "deceleration", "air_control", "movement_mode"),
        "character.jump": ("target", "impulse", "coyote_time", "jump_buffer"),
        "camera.follow": ("camera", "target", "offset_x", "offset_y", "offset_z", "look_height", "look_distance", "smoothing"),
        "input.read_axis": ("axis",),
        "movement.calculate_velocity": ("direction", "speed", "acceleration", "target"),
        "actor.set_velocity": ("target", "velocity"),
        "time.accumulate": ("name",),
        "ui.set_text": ("text",), "audio.play": ("asset",), "save.write": (),
        "animation.play": ("clip", "restart"), "animation.stop": (), "animation.set_speed": ("speed",),
        "animation.locomotion": (
            "target", "idle", "walk_forward", "walk_forward_right", "walk_right", "walk_backward_right",
            "walk_backward", "walk_backward_left", "walk_left", "walk_forward_left", "run", "jump", "land",
            "walk_threshold", "run_threshold", "blend_seconds",
        ),
    }[operation]
    values = [binding_value(key) for key in keys]
    if operation == "audio.play" and values:
        return [stable_runtime_asset_id("audio", str(values[0]))]
    return values


def _collect_player_assets(manifest: Path, output: Path) -> None:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    changed = False
    assets_directory = output / "Content" / "Assets"
    for index, line in enumerate(lines):
        row = line.split("\t")
        if len(row) < 5 or row[0] != "ASSET":
            continue
        source = Path(_decode(row[3])).expanduser()
        if not source.is_absolute():
            source = manifest.parent / source
        if not source.is_file():
            continue
        assets_directory.mkdir(parents=True, exist_ok=True)
        target = assets_directory / f"{row[1]}{source.suffix.lower()}"
        shutil.copy2(source, target)
        row[3] = _encode(f"Content/Assets/{target.name}")
        lines[index] = "\t".join(row)
        changed = True
    if changed:
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_player_executable(value: str | Path | None) -> Path:
    if value:
        candidate = Path(value).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"TC player executable does not exist: {candidate}")
    native = Path(__file__).resolve().parents[1] / "native"
    candidates = sorted(native.glob(".tech_connector/cmake/**/tc_player.exe"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if candidates:
        return candidates[0]
    packaged = native / "bin" / "tc_player.exe"
    if packaged.is_file():
        return packaged
    raise FileNotFoundError("Build tc_player first; no native player executable was found.")


def _canonical_asset_source(source: str) -> str:
    text = str(source).replace("\\", "/").strip()
    return text.casefold() if len(text) > 1 and text[1:2] == ":" else text


def _source_hash(source: str, blobs: dict[str, bytes]) -> str:
    key = source.removeprefix("blobs/")
    payload = blobs.get(key)
    if payload is not None:
        return hashlib.sha256(payload).hexdigest()
    path = Path(source)
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _encode(value: str) -> str:
    return str(value).replace("%", "%25").replace("\t", "%09").replace("\r", "%0D").replace("\n", "%0A")


def _decode(value: str) -> str:
    result = str(value)
    for encoded, plain in (("%0A", "\n"), ("%0D", "\r"), ("%09", "\t"), ("%25", "%")):
        result = result.replace(encoded, plain)
    return result


def _vector(value: Any, size: int, default: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return default
    return tuple(float(item) for item in value)


def _number(value: Any) -> str:
    return format(float(value), ".9g")


def _real(value: Any) -> str:
    return format(float(value), ".17g")


def _flag(value: Any) -> str:
    return "1" if bool(value) else "0"


__all__ = [
    "PlayInEditorSession", "PlayerBuildReceipt", "RUNTIME_MANIFEST_SCHEMA",
    "SUPPORTED_RUNTIME_GRAPH_OPERATIONS", "build_windows_player", "compile_tcscene_for_runtime",
    "launch_play_in_editor", "runtime_platform_capabilities", "stable_runtime_asset_id",
    "summarize_player_profile", "validate_packaged_assets", "validate_player_package",
]
