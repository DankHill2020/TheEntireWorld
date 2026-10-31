"""Build a playable SKM_Test scene from a starter third-person scene and baked FBXs.

Usage: python build_skm_motion_demo.py BASE.tcscene MOTION_REPORT.json OUTPUT_DIR
Creates a new scene/mesh/pose caches; neither the base scene nor source FBXs change.
"""

from __future__ import annotations

from array import array
import json
from pathlib import Path
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tech_connector.game_engine.scene.federated_scene_service import (  # noqa: E402
    load_federated_scene, save_federated_scene,
)
from tech_connector.game_engine.scene.native_fbx_service import import_native_fbx  # noqa: E402
from tech_connector.game_engine.assets.motion_matching_service import load_motion_library  # noqa: E402


RUNTIME_CLIPS = {
    "idle": "tc_idle", "walk": "tc_walk", "run": "tc_run", "walk_back": "tc_walk_back",
    "strafe_left": "tc_strafe_left", "strafe_right": "tc_strafe_right",
    "jump_start": "tc_jump_start", "jump_air": "tc_jump_air", "jump_land": "tc_jump_land",
    "crouch_idle": "tc_crouch_idle", "crouch_move": "tc_crouch_move",
    "crawl_idle": "tc_crawl_idle", "crawl": "tc_crawl_walk",
}
MOTION_VELOCITIES = {
    "idle": (0.0, 0.0), "walk": (0.0, 2.2), "run": (0.0, 5.5),
    "walk_back": (0.0, -2.0), "strafe_left": (-3.5, 0.0),
    "strafe_right": (3.5, 0.0), "crouch_idle": (0.0, 0.0),
    "crouch_move": (0.0, 1.2), "crawl_idle": (0.0, 0.0),
    "crawl": (0.0, 0.65), "jump_start": (0.0, 0.0),
    "jump_air": (0.0, 0.0), "jump_land": (0.0, 0.0),
}
VISUAL_SCALE = 0.014
VISUAL_ORIGIN_HEIGHT = 1.25


def _write_skin_mesh(path: Path, native, binding: dict) -> None:
    mesh = native.manifest["meshes"][0]
    skin = binding["meshes"][0]
    count = int(mesh["vertex_count"])
    triangles = int(mesh["triangle_count"])
    positions = np.frombuffer(skin["bind_vertices_f32"], dtype=np.float32).reshape((-1, 3))
    indices = np.asarray(native.integers[int(mesh["triangle_index_offset"]):
                                         int(mesh["triangle_index_offset"]) + triangles * 3],
                         dtype=np.int64).reshape((-1, 3))
    if len(positions) != count or len(indices) != triangles or indices.max() >= count:
        raise ValueError("FBX skin mesh has invalid indexed geometry")
    normals = np.zeros_like(positions)
    face_normals = np.cross(positions[indices[:, 1]] - positions[indices[:, 0]],
                            positions[indices[:, 2]] - positions[indices[:, 0]])
    for corner in range(3):
        np.add.at(normals, indices[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(lengths[:, None], 1.0e-12)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as output:
        output.write("# SKM_Test baked skin mesh\no SKM_Test\n")
        for x, y, z in positions:
            output.write(f"v {x:.9g} {y:.9g} {z:.9g}\n")
        for x, y, z in normals:
            output.write(f"vn {x:.9g} {y:.9g} {z:.9g}\n")
        for a, b, c in indices + 1:
            output.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")


def _validate_skin_influences(binding: dict) -> dict:
    """Preserve the source skin weights on the native 32-influence GPU path."""
    mesh = binding["meshes"][0]
    offsets = np.frombuffer(mesh["influence_offsets_u32"], dtype=np.uint32)
    joints = np.frombuffer(mesh["joint_indices_u32"], dtype=np.uint32)
    weights = np.frombuffer(mesh["weights_f32"], dtype=np.float32)
    if len(offsets) != int(mesh["vertex_count"]) + 1 or int(offsets[-1]) != len(joints) or len(joints) != len(weights):
        raise ValueError("Invalid SKM_Test sparse skin influences")
    maximum = 0
    for start, end in zip(offsets[:-1], offsets[1:]):
        begin, finish = int(start), int(end)
        count = finish - begin
        if count < 0 or count > 32:
            raise ValueError("SKM_Test skin exceeds the 32-influence GPU limit")
        if float(sum(weights[begin:finish])) <= 0.0:
            raise ValueError("SKM_Test skin contains an unweighted vertex")
        maximum = max(maximum, count)
    return {"preserved_vertices": int(mesh["vertex_count"]),
            "maximum_influences": maximum, "influences": len(joints),
            "discarded_influences": 0}


def _validate_motion_skeleton(reference: dict, candidate: dict, role: str) -> None:
    """Every clip must use the rendered mesh's joint hierarchy and bind pose."""
    topology = lambda skeleton: [(joint["native_id"], joint["name"], joint["parent_native_id"])
                                 for joint in skeleton["joints"]]
    if topology(candidate) != topology(reference):
        raise ValueError(f"Skeleton joint hierarchy differs in {role}")
    expected = len(reference["joints"]) * 16
    first = np.frombuffer(reference["inverse_bind_matrices_f32"], dtype=np.float32)
    other = np.frombuffer(candidate["inverse_bind_matrices_f32"], dtype=np.float32)
    if (len(first) != expected or len(other) != expected or
            not np.all(np.isfinite(first)) or not np.all(np.isfinite(other)) or
            not np.allclose(first, other, rtol=0.0, atol=1.0e-5)):
        raise ValueError(f"Skeleton inverse bind pose differs in {role}")


def build_demo(base_scene: Path, report_path: Path, output_dir: Path) -> dict:
    base_scene, report_path, output_dir = (path.resolve() for path in (base_scene, report_path, output_dir))
    library = load_motion_library(report_path)
    if set(library["clips"]) != set(RUNTIME_CLIPS):
        raise ValueError("Demo requires all thirteen SKM_Test motion roles")
    document, blobs = load_federated_scene(base_scene)
    first = import_native_fbx(library["clips"]["idle"]["path"])
    binding = first.build_deformation_binding()
    if binding["contract_errors"] or len(binding["meshes"]) != 1 or len(binding["skeletons"]) != 1:
        raise ValueError("SKM_Test skin contract is not suitable for player playback")
    # FBX mesh vertices are mesh-local while the inverse-bind matrices are in
    # armature/world space. The generic native skin record has no bind-geometry
    # field, so bake that matrix into the rest positions before GPU upload.
    skin_mesh = binding["meshes"][0]
    raw = np.frombuffer(skin_mesh["bind_vertices_f32"], dtype=np.float32).reshape((-1, 3))
    geometry = np.asarray(skin_mesh["bind_geometry_matrix"], dtype=np.float64).reshape((4, 4))
    homogeneous = np.ones((len(raw), 4), dtype=np.float64)
    homogeneous[:, :3] = raw
    normalized = (homogeneous @ geometry)[:, :3]
    skin_mesh["bind_vertices_f32"] = normalized.astype(np.float32).tobytes()
    skin_mesh["bind_vertex_float_offset"] = 0
    influence_report = _validate_skin_influences(binding)
    source_joints = binding["skeletons"][0]["joints"]
    joint_ids = [f"native_fbx::{item['native_id']}" for item in source_joints]
    document.rig_graph.joints.clear()
    document.rig_graph.skins.clear()
    document.rig_graph.animation.clear()
    blobs.update(document.rig_graph.merge_deformation_binding(binding))
    if set(joint_ids) != set(document.rig_graph.joints):
        raise ValueError("Merged rig does not match FBX joint identities")
    assets_dir = output_dir / "Assets" / "MotionDemo"
    assets_dir.mkdir(parents=True, exist_ok=True)
    obj = assets_dir / "SKM_Test.obj"
    _write_skin_mesh(obj, first, binding)
    for role, clip_id in RUNTIME_CLIPS.items():
        metadata = library["clips"][role]
        native = first if role == "idle" else import_native_fbx(metadata["path"])
        _validate_motion_skeleton(binding["skeletons"][0],
                                  native.build_deformation_binding()["skeletons"][0], role)
        matrices = array("f")
        for frame in range(1, int(metadata["frames"]) + 1):
            pose = native.deformation_pose_at_frame(binding, frame=frame)
            if pose["pose_source"] != "baked_exact":
                raise ValueError(f"No exact pose cache for {role} frame {frame}")
            world_matrices = np.frombuffer(
                pose["skeletons"][0]["joint_matrices_f32"], dtype=np.float32,
            ).copy().reshape((-1, 4, 4))
            # The physics capsule is centre-based while this FBX is feet-based.
            # Offset the visual rig, leaving the collision actor untouched.
            world_matrices[:, 3, 2] -= VISUAL_ORIGIN_HEIGHT / VISUAL_SCALE
            matrices.frombytes(world_matrices.tobytes())
        expected = int(metadata["frames"]) * len(joint_ids) * 16
        if len(matrices) != expected:
            raise ValueError(f"Incomplete pose cache for {role}")
        cache = assets_dir / f"{clip_id}.pose.f32"
        cache.write_bytes(matrices.tobytes())
        document.rig_graph.animation[clip_id] = {
            "id": clip_id, "type": "animation_take", "name": clip_id,
            "start_frame": 1, "end_frame": int(metadata["frames"]), "frame_rate": 30,
            "loop": bool(metadata["loop"]), "layers": {},
            "pose_cache": {"source": str(cache), "frame_count": int(metadata["frames"]),
                           "joint_ids": joint_ids},
        }
        print(f"TC_DEMO_POSE_CACHE {role} {metadata['frames']} {cache}", flush=True)
    runtime = dict(document.metadata.get("runtime_world") or {})
    runtime["motion_database"] = {"frames": [
        {"clip_id": RUNTIME_CLIPS[role], "frame": feature["frame"],
         "family": (role.removeprefix("jump_") if role.startswith("jump_")
                    else ("crawl" if role.startswith("crawl") else
                          "crouch" if role.startswith("crouch") else "stand")),
         "velocity": MOTION_VELOCITIES[role],
         "pelvis_height": feature["pelvis_height"], "joints": feature["joints"]}
        for role, metadata in library["clips"].items()
        for feature in metadata["pose_features"]
    ]}
    player = next((entity for entity in runtime.get("entities") or () if entity.get("name") == "Player"), None)
    if player is None:
        raise ValueError("Starter scene has no Player entity")
    skin = binding["meshes"][0]
    skin_id = f"native_fbx::{binding['skeletons'][0]['native_id']}::{skin['native_id']}"
    player["render"] = {"mesh": str(obj), "skin_binding": skin_id,
                        "base_color": [0.08, 0.35, 0.9], "roughness": 0.65}
    player.setdefault("transform", {})["scale"] = [VISUAL_SCALE] * 3
    player["transform"]["rotation"] = [-90.0, 0.0, 0.0]
    player.setdefault("collider", {})["world_up"] = True
    runtime["entities"].extend([
        {"name": "CrawlCanopy", "role": "crawl_clearance_demo",
         "transform": {"position": [0.0, 1.55, 8.0], "scale": [2.2, 0.3, 1.6]},
         "collider": {"shape": "box", "half_extents": [1.1, 0.15, 0.8], "layer": 1}},
        {"name": "CrawlCanopyEntryBeam", "role": "crawl_clearance_demo",
         "transform": {"position": [0.0, 1.55, 7.2], "scale": [2.2, 0.3, 0.12]},
         "render": {"mesh": "builtin:cube", "base_color": [0.8, 0.48, 0.18], "roughness": 0.72}},
        {"name": "CrawlCanopyExitBeam", "role": "crawl_clearance_demo",
         "transform": {"position": [0.0, 1.55, 8.8], "scale": [2.2, 0.3, 0.12]},
         "render": {"mesh": "builtin:cube", "base_color": [0.8, 0.48, 0.18], "roughness": 0.72}},
        {"name": "CrawlCanopyLeftPost", "role": "crawl_clearance_demo",
         "transform": {"position": [-1.2, 0.7, 7.2], "scale": [0.15, 1.4, 0.15]},
         "render": {"mesh": "builtin:cube", "base_color": [0.68, 0.38, 0.15], "roughness": 0.75},
         "collider": {"shape": "box", "half_extents": [0.075, 0.7, 0.075], "layer": 1}},
        {"name": "CrawlCanopyRightPost", "role": "crawl_clearance_demo",
         "transform": {"position": [1.2, 0.7, 7.2], "scale": [0.15, 1.4, 0.15]},
         "render": {"mesh": "builtin:cube", "base_color": [0.68, 0.38, 0.15], "roughness": 0.75},
         "collider": {"shape": "box", "half_extents": [0.075, 0.7, 0.075], "layer": 1}},
        {"name": "CrawlCanopyLeftExitPost", "role": "crawl_clearance_demo",
         "transform": {"position": [-1.2, 0.7, 8.8], "scale": [0.15, 1.4, 0.15]},
         "render": {"mesh": "builtin:cube", "base_color": [0.68, 0.38, 0.15], "roughness": 0.75},
         "collider": {"shape": "box", "half_extents": [0.075, 0.7, 0.075], "layer": 1}},
        {"name": "CrawlCanopyRightExitPost", "role": "crawl_clearance_demo",
         "transform": {"position": [1.2, 0.7, 8.8], "scale": [0.15, 1.4, 0.15]},
         "render": {"mesh": "builtin:cube", "base_color": [0.68, 0.38, 0.15], "roughness": 0.75},
         "collider": {"shape": "box", "half_extents": [0.075, 0.7, 0.075], "layer": 1}},
    ])
    for instruction in runtime.get("tick") or ():
        if instruction.get("operation") == "camera.follow":
            instruction["arguments"][2] = 4.2
            instruction["arguments"][3] = 1.7
            instruction["arguments"][4] = -3.0
            instruction["arguments"][5] = 0.2
        if instruction.get("operation") != "animation.locomotion":
            continue
        instruction["arguments"] = [
            "Player", "tc_idle", "tc_walk", "tc_walk", "tc_strafe_right",
            "tc_walk_back", "tc_walk_back", "tc_walk_back", "tc_strafe_left",
            "tc_walk", "tc_run", "tc_jump_air", "tc_jump_land", 0.15, 3.4, 0.16,
            "tc_crouch_idle", "tc_crouch_move", "tc_crawl_idle", "tc_crawl_walk",
            "tc_jump_start",
        ]
    runtime["hud_text"] = "SKM_Test Motion Demo — WASD move, Space jump, hold C crouch, hold V crawl"
    runtime["ui_document"] = {
        "canvas": {"size": [1280, 720], "safe_area": [96, 54, 96, 54]},
        "widgets": [
            {"id": "controls_panel", "type": "panel", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [20, 20], "size": [420, 132]},
            {"id": "controls_title", "type": "text", "parent_id": "controls_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [16, 12], "size": [388, 38],
             "text": "SKM_Test motion demo"},
            {"id": "controls_move", "type": "text", "parent_id": "controls_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [16, 54], "size": [388, 30],
             "text": "WASD/stick move   Space/A jump"},
            {"id": "controls_stance", "type": "text", "parent_id": "controls_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [16, 89], "size": [388, 30],
             "text": "Hold C/B crouch   V/X crawl"},
        ],
    }
    rendering = runtime.setdefault("rendering", {})
    rendering["lighting_model"] = "stylized"
    rendering["global_illumination"] = "hemisphere"
    rendering["indirect_intensity"] = 1.1
    rendering["sky_color"] = [0.20, 0.32, 0.52]
    rendering["ground_color"] = [0.17, 0.20, 0.25]
    camera = next((entity for entity in runtime.get("entities") or ()
                   if entity.get("name") == "RuntimeCamera"), None)
    if camera:
        camera.setdefault("transform", {})["position"] = [4.2, 2.35, -3.0]
    document.metadata["runtime_world"] = runtime
    scene = output_dir / "SKM_Test_Motion_Demo.tcscene"
    save_federated_scene(scene, document, blobs=blobs)
    return {"scene": str(scene), "clips": len(RUNTIME_CLIPS), "joints": len(joint_ids),
            "mesh": str(obj), "skin_binding": skin_id, "gpu_skin_weights": influence_report}


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 3:
        raise SystemExit("Expected base scene, motion report, and output directory")
    print("TC_MOTION_DEMO_OK " + json.dumps(build_demo(*(Path(value) for value in args))), flush=True)
