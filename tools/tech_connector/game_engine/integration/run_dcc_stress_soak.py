"""Qualify sustained imported-character motion under a synthetic draw load.

This combines an already packaged DCC player with render-only stress entities
from a separately compiled acceptance scene. It does not claim a production
content or representative-hardware benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .verify_third_person_soak import verify_soak


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stress_entity_rows(dcc_scene: Path, stress_scene: Path) -> tuple[list[str], int]:
    """Select complete prop triples only when their assets exist in the DCC scene."""
    destination = dcc_scene.read_text(encoding="utf-8").splitlines()
    source = stress_scene.read_text(encoding="utf-8").splitlines()
    assets = {row.split("\t", 2)[1] for row in destination if row.startswith("ASSET\t")}
    existing = {row.split("\t", 2)[1] for row in destination if row.startswith("ENTITY\t")}
    selected: dict[str, dict[str, str]] = {}
    for row in source:
        fields = row.split("\t")
        if len(fields) < 2 or fields[0] not in {"ENTITY", "TRANSFORM", "RENDER"}:
            continue
        name = fields[1]
        if not name.startswith("AcceptanceStressProp"):
            continue
        if name in existing or fields[0] in selected.setdefault(name, {}):
            raise ValueError(f"Duplicate stress entity or row: {name}")
        selected[name][fields[0]] = row
        if fields[0] == "RENDER" and (len(fields) < 4 or fields[2] not in assets or fields[3] not in assets):
            raise ValueError(f"Stress entity has an asset absent from the DCC package: {name}")
    if not selected or any(set(rows) != {"ENTITY", "TRANSFORM", "RENDER"} for rows in selected.values()):
        raise ValueError("The stress scene must contain complete render-only prop triples.")
    result = [selected[name][kind] for name in sorted(selected)
              for kind in ("ENTITY", "TRANSFORM", "RENDER")]
    return result, len(selected)


def run(package_source: Path, stress_scene: Path, player: Path, output: Path,
        frames: int = 3600, unsynced: bool = False, render_scale: float | None = None,
        window_width: int = 1280, window_height: int = 720) -> dict:
    if frames < 3600:
        raise ValueError("A mixed-action sustained soak requires at least 3,600 frames.")
    if render_scale is not None and not (0.25 <= render_scale <= 1.0):
        raise ValueError("Render scale must be between 0.25 and 1.0.")
    package_source = package_source.resolve()
    stress_scene = stress_scene.resolve()
    player = player.resolve()
    # Python 3.9 on Windows may leave a nonexistent relative path relative after
    # resolve(); anchor it before creating the output and changing the child cwd.
    output = (Path.cwd() / output).resolve()
    source_scene = package_source / "Content" / "main.tcruntime"
    for required in (source_scene, stress_scene, player):
        if not required.is_file():
            raise FileNotFoundError(required)
    rows, count = stress_entity_rows(source_scene, stress_scene)
    if count != 2000:
        raise ValueError(f"Expected exactly 2,000 stress props, found {count}.")
    package = output / "package"
    if package.exists():
        raise FileExistsError(f"Refusing to overwrite existing soak output: {package}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package_source, package)
    shutil.copy2(player, package / "TCPlayer.exe")
    scene = package / "Content" / "main.tcruntime"
    if render_scale is not None:
        manifest_rows = scene.read_text(encoding="utf-8").splitlines()
        settings = [index for index, row in enumerate(manifest_rows)
                    if row.startswith("RENDERSETTINGS\t")]
        if len(settings) != 1:
            raise ValueError("Expected exactly one packaged RENDERSETTINGS row.")
        fields = manifest_rows[settings[0]].split("\t")
        fields[3] = str(render_scale)
        manifest_rows[settings[0]] = "\t".join(fields)
        scene.write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")
    with scene.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(rows) + "\n")
    profile = output / "dcc_stress_3600_profile.jsonl"
    command = [str(package / "TCPlayer.exe"), "--scene", str(scene),
               "--renderer", "d3d11", "--require-renderer", "--scripted-motion-soak",
               "--frames", str(frames), "--log", str(profile)]
    command.extend(("--window-width", str(window_width),
                    "--window-height", str(window_height)))
    if unsynced:
        command.append("--benchmark-unsynced")
    if not all(path.is_absolute() for path in (package, scene, profile)):
        raise AssertionError("Combined soak paths must be absolute before changing cwd: " +
                             repr([(str(path), path.is_absolute())
                                   for path in (package, scene, profile)]))
    (output / "launch.json").write_text(json.dumps({"command": command,
                                                    "cwd": str(package)}, indent=2) + "\n",
                                          encoding="utf-8")
    completed = subprocess.run(command, cwd=package, capture_output=True, text=True,
                               timeout=240, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode != 0 or not profile.is_file():
        raise RuntimeError("Combined DCC stress Player failed: " +
                           (completed.stderr or completed.stdout)[-1500:])
    receipt = verify_soak(profile, warmup=60, min_draw_calls=count + 10,
                          scope="single-PC DCC mixed-action 2,000-prop D3D11 " +
                                ("unsynced GPU-work soak" if unsynced else "vsynced soak"),
                          require_motion_search=True, require_mixed_motion=True,
                          require_unsynced_gpu_samples=unsynced,
                          require_vsynced_pacing=not unsynced)
    receipt.update({"dcc_source_scene_sha256": _sha256(source_scene),
                    "stress_source_scene_sha256": _sha256(stress_scene),
                    "player_sha256": _sha256(player), "combined_scene_sha256": _sha256(scene),
                    "synthetic_props": count, "command": command,
                    "mode": "unsynced_gpu_work" if unsynced else "vsynced_frame_pacing"})
    if render_scale == 1.0 and window_width >= 1920 and window_height >= 1080:
        frames_logged = [json.loads(line) for line in profile.read_text(encoding="utf-8").splitlines()
                         if line.startswith("{") and '"type":"frame"' in line]
        steady = frames_logged[60:]
        minimum_width = min((int(row.get("render_width", 0)) for row in steady), default=0)
        minimum_height = min((int(row.get("render_height", 0)) for row in steady), default=0)
        receipt["render_width_min"] = minimum_width
        receipt["render_height_min"] = minimum_height
        receipt["checks"]["near_1080p_render_target"] = minimum_width >= 1800 and minimum_height >= 1000
        receipt["status"] = "passed" if all(receipt["checks"].values()) else "failed"
    report = output / "dcc_stress_3600_soak.json"
    report.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--stress-scene", required=True, type=Path)
    parser.add_argument("--player", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=3600)
    parser.add_argument("--unsynced", action="store_true")
    parser.add_argument("--render-scale", type=float)
    parser.add_argument("--window-width", type=int, default=1280)
    parser.add_argument("--window-height", type=int, default=720)
    args = parser.parse_args()
    result = run(args.package, args.stress_scene, args.player, args.output,
                 args.frames, args.unsynced, args.render_scale,
                 args.window_width, args.window_height)
    print(json.dumps({"status": result["status"], "checks": result["checks"]}))
    raise SystemExit(0 if result["status"] == "passed" else 1)
