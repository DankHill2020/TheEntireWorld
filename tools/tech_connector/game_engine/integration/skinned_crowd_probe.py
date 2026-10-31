"""Stress actual DCC skin draws on Windows without modifying the source package.

This is a repeated-instance GPU probe, not representative game content or
multi-character animation/AI qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess

from tech_connector.game_engine.integration.third_person_acceptance_service import (
    compare_bmp_baseline, host_hardware_receipt, steady_profile,
)


def author_crowd_manifest(source: Path, destination: Path | None, count: int,
                          *, crowd_shadows: bool = True,
                          shadow_casters: int | None = None,
                          unique_rigs: int = 0,
                          source_actor: str = "Player") -> str:
    if count < 1 or count > 512:
        raise ValueError("Skinned crowd count must be between 1 and 512")
    if shadow_casters is None:
        shadow_casters = count if crowd_shadows else 0
    if not 0 <= shadow_casters <= count:
        raise ValueError("Skinned shadow caster count must be between 0 and crowd count")
    if not 0 <= unique_rigs <= count:
        raise ValueError("Unique rig count must be between 0 and crowd count")
    lines = source.read_text(encoding="utf-8").splitlines()
    if not source_actor or any(ord(character) < 32 for character in source_actor):
        raise ValueError("Crowd source actor must be a single manifest identifier")
    player_render = next((row for row in lines if row.startswith(f"RENDER\t{source_actor}\t") and
                          "native_fbx::" in row), None)
    player_transform = next((row for row in lines if row.startswith(f"TRANSFORM\t{source_actor}\t")), None)
    scene_ids = [index for index, row in enumerate(lines) if row.startswith("SCENEID\t")]
    if player_render is None or player_transform is None or len(scene_ids) != 1:
        raise ValueError(f"Crowd probe requires a scene-bound DCC-skinned {source_actor}")
    original_scene = lines[scene_ids[0]].split("\t", 1)[1]
    scene_id = hashlib.sha256(
        f"{original_scene}:skinned-crowd:{source_actor}:{count}:shadow-casters={shadow_casters}:rigs={unique_rigs}".encode()
    ).hexdigest()[:24]
    lines[scene_ids[0]] = f"SCENEID\t{scene_id}"
    render_parts = player_render.split("\t")
    transform_parts = player_transform.split("\t")
    if unique_rigs:
        binding_id = render_parts[15]
        binding = next((row.split("\t") for row in lines
                        if row.startswith(f"SKIN\t{binding_id}\t")), None)
        if binding is None or len(binding) < 8:
            raise ValueError("Unique rig probe requires a packaged skin binding")
        joint_count = int(binding[7])
        if len(binding) != 8 + joint_count + 5:
            raise ValueError("Unique rig probe requires a complete skin binding")
        skeleton_id = binding[3]
        skeleton = next((row.split("\t") for row in lines
                         if row.startswith(f"SKELETON\t{skeleton_id}\t")), None)
        joints = [row.split("\t") for row in lines
                  if row.startswith(f"JOINT\t{skeleton_id}\t")]
        if (skeleton is None or len(joints) != int(skeleton[2]) or
                not {binding[index] for index in range(8, 8 + joint_count)}.issubset(
                    {joint[2] for joint in joints})):
            raise ValueError("Unique rig probe requires the complete source skeleton")
        for rig_index in range(unique_rigs):
            new_skeleton_id = f"CrowdSkeleton_{rig_index:03d}"
            new_binding_id = f"CrowdSkin_{rig_index:03d}"
            new_skeleton = skeleton.copy()
            new_skeleton[1] = new_skeleton_id
            lines.append("\t".join(new_skeleton))
            for joint in joints:
                clone = joint.copy()
                clone[1] = new_skeleton_id
                clone[2] = f"{new_skeleton_id}::{joint[2]}"
                clone[3] = f"{new_skeleton_id}::{joint[3]}" if joint[3] else ""
                lines.append("\t".join(clone))
            new_binding = binding.copy()
            new_binding[1] = new_binding_id
            new_binding[3] = new_skeleton_id
            for joint_index in range(8, 8 + joint_count):
                new_binding[joint_index] = f"{new_skeleton_id}::{binding[joint_index]}"
            lines.append("\t".join(new_binding))
    columns = math.ceil(math.sqrt(count))
    for index in range(count):
        actor = f"CrowdRig_{index:03d}"
        transform = transform_parts.copy()
        transform[1] = actor
        transform[2] = f"{(index % columns - (columns - 1) / 2) * 1.6:.4f}"
        transform[3] = "1.25"
        transform[4] = f"{3.0 + (index // columns) * 1.6:.4f}"
        render = render_parts.copy()
        render[1] = actor
        render[9] = "1" if index < shadow_casters else "0"
        if unique_rigs:
            render[15] = f"CrowdSkin_{index % unique_rigs:03d}"
        lines.extend((f"ENTITY\t{actor}", "\t".join(transform), "\t".join(render)))
    manifest = "\n".join(lines) + "\n"
    if destination is not None:
        destination.write_text(manifest, encoding="utf-8")
    return manifest


def author_unicode_mesh_source(scene: Path) -> dict[str, str]:
    """Relocate the rendered Player OBJ within a copied package for a path probe."""
    lines = scene.read_text(encoding="utf-8").splitlines()
    render = next((row.split("\t") for row in lines if row.startswith("RENDER\tPlayer\t")), None)
    if render is None:
        raise ValueError("Unicode mesh probe requires a Player render record")
    asset_index = next((index for index, row in enumerate(lines)
                        if row.startswith(f"ASSET\t{render[2]}\tmesh\t")), None)
    if asset_index is None:
        raise ValueError("Unicode mesh probe requires a packaged Player mesh")
    asset = lines[asset_index].split("\t")
    original = (scene.parent / asset[3]).resolve()
    if scene.parent.resolve() not in original.parents or not original.is_file():
        raise ValueError("Unicode mesh probe requires a package-local mesh file")
    relocated = original.with_name("mesh-保存" + original.suffix)
    if relocated.exists():
        raise FileExistsError(relocated)
    shutil.copy2(original, relocated)
    asset[3] = relocated.relative_to(scene.parent).as_posix()
    lines[asset_index] = "\t".join(asset)
    scene.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"source": asset[3], "sha256": hashlib.sha256(relocated.read_bytes()).hexdigest()}


def crowd_draw_coverage(steady: dict, count: int, shadow_casters: int,
                        *, unsynced: bool = False, unique_rigs: int = 0,
                        cpu_skinning: bool = False,
                        base_skin_sets: int = 1) -> bool:
    return (steady["skinned_draws_min"] >= count + shadow_casters + 1 and
            ((steady["gpu_skinned_draws_min"] == 0 and
              steady["cpu_skinned_draws_min"] >= count + shadow_casters + 1)
             if cpu_skinning else
             (steady["gpu_skinned_draws_min"] >= count + shadow_casters + 1 and
              steady["cpu_skinned_draws_max"] == 0)) and
            (cpu_skinning or unique_rigs == 0 or
             (steady["gpu_skin_stream_sets_max"] == base_skin_sets and
              steady["gpu_skin_palette_sets_min"] >= unique_rigs + base_skin_sets)) and
            (unique_rigs == 0 or
             (steady["inverse_bind_reads_min"] == base_skin_sets and
              steady["inverse_bind_reads_max"] == base_skin_sets and
              steady["inverse_bind_cache_hits_min"] >= unique_rigs)) and
            steady["submitted_geometry_draws_min"] >= count + 1 and
            steady["submitted_shadow_draws_min"] >= shadow_casters and
            steady["graphics_adapter"]["status"] == "passed" and
            steady["vsync_mode"] == ("unsynced" if unsynced else "vsynced"))


def crowd_visual_coverage(screenshot: Path, *, static_dcc_scene: bool = False) -> dict:
    """Require the fixture's lit floor in the lower half, not just draw calls/HUD.

    A malformed skin palette can submit every draw while a giant blue mesh
    hides the whole scene. This is a coarse fixture-specific smoke check, not
    a substitute for image comparison or a human graphical review.
    """
    data = screenshot.read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("Crowd visual check requires a 24-bit BMP screenshot")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    depth = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if width < 400 or height < 200 or depth != 24 or compression != 0 or offset < 54:
        raise ValueError("Crowd screenshot has unsupported dimensions or pixel format")
    row_bytes = (width * 3 + 3) & ~3
    if len(data) < offset + row_bytes * height:
        raise ValueError("Crowd screenshot is truncated")
    floor = actor = sampled = actor_region_samples = 0
    for y in range(height // 2, height, 4):
        row = offset + (height - 1 - y) * row_bytes
        for x in range(0, width, 4):
            blue, green, red = data[row + x * 3:row + x * 3 + 3]
            if static_dcc_scene:
                floor += (80 <= red <= 175 and 95 <= green <= 185 and
                          105 <= blue <= 195 and abs(red - green) <= 30)
            else:
                floor += red > 180 and green > 180 and blue > 180
            sampled += 1
            if width * 0.30 <= x < width * 0.70 and y < height * 0.95:
                actor_region_samples += 1
                if static_dcc_scene:
                    actor += red > 185 and 140 < green < 235 and blue < 160
                else:
                    actor += (red < 100 and green < 160 and blue > 140 and
                              blue > red + 60 and green > red + 30)
    fraction = floor / sampled
    actor_fraction = actor / actor_region_samples
    return {"passed": fraction >= 0.10 and actor_fraction >= 0.0015,
            "lit_floor_fraction": fraction, "blue_actor_fraction": actor_fraction,
            "minimum_lit_floor_fraction": 0.10,
            "minimum_blue_actor_fraction": 0.0015, "sampled_pixels": sampled,
            "palette": "static_dcc_gray_yellow" if static_dcc_scene else "starter_bright_blue"}


def classify_probe(*, draw_coverage: bool, visual_coverage: bool, budget_pass: bool,
                   shadow_casters: int, count: int, unsynced: bool,
                   unique_rigs: int = 0, cpu_skinning: bool = False,
                   unicode_mesh_source: bool = False,
                   source_actor: str = "Player") -> str:
    if not draw_coverage or not visual_coverage:
        return "blocked"
    if not unsynced and not budget_pass:
        return "performance_failed"
    if (unsynced or shadow_casters != count or unique_rigs or cpu_skinning or
            unicode_mesh_source or source_actor != "Player"):
        return "diagnostic_only"
    return "passed" if budget_pass else "performance_failed"


def run_probe(package: Path, player: Path, output: Path, *, count: int, frames: int,
              crowd_shadows: bool = True, shadow_casters: int | None = None,
              unsynced: bool = False, unique_rigs: int = 0,
              cpu_skinning: bool = False, unicode_mesh_source: bool = False,
              visual_reference: Path | None = None,
              source_actor: str = "Player") -> dict:
    package, player, output = package.resolve(), player.resolve(), output.resolve()
    if visual_reference is not None:
        visual_reference = visual_reference.resolve()
        if not visual_reference.is_file():
            raise FileNotFoundError(f"Crowd visual reference does not exist: {visual_reference}")
    if output.exists():
        raise FileExistsError(f"Probe output already exists: {output}")
    if package in output.parents:
        raise ValueError("Probe output must be outside the source package")
    if not (package / "Content" / "main.tcruntime").is_file() or not player.is_file():
        raise FileNotFoundError("A built motion-demo package and native Player are required")
    source_scene = package / "Content" / "main.tcruntime"
    base_skin_sets = len({parts[15] for row in source_scene.read_text(encoding="utf-8").splitlines()
                          if row.startswith("RENDER\t") and len(parts := row.split("\t")) > 15
                          and parts[15]})
    if shadow_casters is None:
        shadow_casters = count if crowd_shadows else 0
    authored_manifest = author_crowd_manifest(
        source_scene, None, count, shadow_casters=shadow_casters,
        unique_rigs=unique_rigs, source_actor=source_actor)
    shutil.copytree(package, output)
    scene = output / "Content" / "main.tcruntime"
    scene.write_text(authored_manifest, encoding="utf-8")
    unicode_mesh = author_unicode_mesh_source(scene) if unicode_mesh_source else None
    profile = output / "Content" / "skinned-crowd-profile.jsonl"
    screenshot = output / "Content" / "skinned-crowd.bmp"
    command = [str(player), "--scene", str(scene), "--renderer", "d3d11", "--require-renderer",
               "--frames", str(frames), "--log", str(profile), "--screenshot", str(screenshot),
               "--screenshot-frame", "60", "--save-dir", str(output / "ProbeSaves")]
    if unsynced:
        command.append("--benchmark-unsynced")
    if cpu_skinning:
        command.append("--cpu-skinning-diagnostic")
    completed = subprocess.run(
        command,
        cwd=output, capture_output=True, text=True, timeout=max(120, frames // 10), check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not profile.is_file() or not screenshot.is_file():
        raise RuntimeError("Skinned crowd Player run failed: " +
                           (completed.stderr or completed.stdout)[-1200:])
    steady = steady_profile(profile, warmup_frames=min(60, frames // 4))
    draw_coverage = crowd_draw_coverage(steady, count, shadow_casters,
                                        unsynced=unsynced, unique_rigs=unique_rigs,
                                        cpu_skinning=cpu_skinning,
                                        base_skin_sets=base_skin_sets)
    visual_coverage = crowd_visual_coverage(
        screenshot, static_dcc_scene=source_actor != "Player")
    visual_parity = (compare_bmp_baseline(visual_reference, screenshot)
                     if visual_reference is not None else None)
    frame_p95 = steady["metrics_ms"]["frame_interval_ms"]["p95"]
    gpu_p95 = steady["metrics_ms"]["gpu_sample_ms"]["p95"]
    budget_pass = frame_p95 <= 17.167 and gpu_p95 <= 17.167
    result = {
        "schema": "tech_connector.skinned_crowd_probe.v1",
        "status": classify_probe(draw_coverage=draw_coverage,
                                 visual_coverage=(visual_coverage["passed"] and
                                                  (visual_parity is None or visual_parity["passed"])),
                                 budget_pass=budget_pass,
                                 shadow_casters=shadow_casters, count=count,
                                 unsynced=unsynced, unique_rigs=unique_rigs,
                                 cpu_skinning=cpu_skinning,
                                 unicode_mesh_source=unicode_mesh_source,
                                 source_actor=source_actor),
        "scope": "single-PC repeated DCC skin instances; not release qualification",
        "release_gate_status": "not_proven",
        "actors_added": count, "crowd_shadows": shadow_casters == count,
        "shadow_casters": shadow_casters, "frames": frames,
        "independent_static_rigs": unique_rigs,
        "source_actor": source_actor,
        "base_skin_sets": base_skin_sets,
        "unsynced_diagnostic": unsynced,
        "cpu_skinning_diagnostic": cpu_skinning,
        "unicode_mesh_source": unicode_mesh,
        "scene_id": scene_id_from_manifest(scene),
        "draw_coverage": draw_coverage,
        "visual_coverage": visual_coverage,
        "visual_parity": visual_parity,
        "visual_reference_sha256": (hashlib.sha256(visual_reference.read_bytes()).hexdigest()
                                    if visual_reference is not None else None),
        "budget_ms": {"frame_interval_p95": 16.667, "gpu_sample_p95": 16.667,
                      "tolerance": 0.5},
        "performance_budget": "passed" if budget_pass else "failed",
        "host_hardware": host_hardware_receipt(steady["graphics_adapter"]),
        "player_sha256": hashlib.sha256(player.read_bytes()).hexdigest(),
        "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
        "profile": str(profile), "screenshot": str(screenshot), "steady": steady,
    }
    (output / "skinned_crowd_probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def scene_id_from_manifest(path: Path) -> str:
    return next(row.split("\t", 1)[1] for row in path.read_text(encoding="utf-8").splitlines()
                if row.startswith("SCENEID\t"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("player", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=64)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--no-crowd-shadows", action="store_true",
                        help="Separate crowd shadow cost from geometry skinning cost.")
    parser.add_argument("--shadow-casters", type=int,
                        help="Diagnostic number of crowd rigs that cast shadows (first N).")
    parser.add_argument("--unsynced", action="store_true",
                        help="GPU-work diagnostic only; never qualifies frame pacing.")
    parser.add_argument("--unique-rigs", type=int, default=0,
                        help="Diagnostic independent skeleton/skin bindings; no independent animation.")
    parser.add_argument("--source-actor", default="Player",
                        help="Scene-bound DCC-skinned actor to instance; non-Player sources are diagnostic only.")
    parser.add_argument("--cpu-skinning", action="store_true",
                        help="Force CPU fallback for visual/draw correctness; diagnostic only.")
    parser.add_argument("--unicode-mesh-source", action="store_true",
                        help="Render the packaged Player mesh from a relocated Unicode filename; diagnostic only.")
    parser.add_argument("--visual-reference", type=Path,
                        help="Optional same-scene BMP baseline; image mismatch blocks the probe.")
    args = parser.parse_args()
    if args.no_crowd_shadows and args.shadow_casters is not None:
        parser.error("--no-crowd-shadows cannot be combined with --shadow-casters")
    result = run_probe(args.package, args.player, args.output, count=args.count,
                       frames=args.frames, crowd_shadows=not args.no_crowd_shadows,
                       shadow_casters=args.shadow_casters, unsynced=args.unsynced,
                       unique_rigs=args.unique_rigs, cpu_skinning=args.cpu_skinning,
                       unicode_mesh_source=args.unicode_mesh_source,
                       visual_reference=args.visual_reference,
                       source_actor=args.source_actor)
    print(json.dumps({"status": result["status"], "actors_added": result["actors_added"],
                      "report": str(args.output / "skinned_crowd_probe.json")}))
    return 0 if result["status"] in {"passed", "diagnostic_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
