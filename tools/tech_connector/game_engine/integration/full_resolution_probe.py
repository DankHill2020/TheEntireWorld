"""Isolated native-resolution Windows Player GPU-work and pacing diagnostic.

This is one-device synthetic-scene evidence, not a release qualification.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

from tech_connector.game_engine.integration.third_person_acceptance_service import steady_profile


def pacing_windows(profile: Path, *, warmup_frames: int, window_frames: int = 300) -> list[dict]:
    """Expose sustained pacing regressions that an all-run percentile can hide."""
    records = [json.loads(row) for row in profile.read_text(encoding="utf-8").splitlines()
               if row.startswith("{")]
    frames = [row for row in records if row.get("type") == "frame"]
    measured = frames[warmup_frames:]
    windows = []
    for start in range(0, len(measured), window_frames):
        sample = measured[start:start + window_frames]
        if len(sample) < min(150, window_frames):
            continue
        values = sorted(float(row["frame_interval_ms"]) for row in sample)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Paced profile contains invalid frame intervals.")
        percentile = lambda fraction: values[math.ceil(len(values) * fraction) - 1]
        windows.append({"first_frame": sample[0]["frame"],
                        "last_frame": sample[-1]["frame"],
                        "count": len(sample), "p95_ms": percentile(0.95),
                        "p99_ms": percentile(0.99), "maximum_ms": values[-1]})
    return windows


def add_stress_props(rows: list[str], count: int) -> list[str]:
    """Add render-only cubes to an isolated packaged scene, retaining its DCC character."""
    if not 0 <= count <= 2000:
        raise ValueError("Stress actor count must be between 0 and 2000.")
    if count == 0:
        return rows
    cube = next((row.split("\t") for row in rows if row.startswith("RENDER\tGround\t")), None)
    if cube is None or len(cube) < 7:
        raise ValueError("Stress actors require a packaged Ground cube render.")
    result = list(rows)
    for index in range(count):
        name = f"ProbeStressProp{index:04d}"
        x = ((index % 32) - 16) * 1.8
        z = 7.0 + (index // 32) * 2.0
        render = list(cube)
        render[1] = name
        render[4:7] = ["0.18", "0.45", "0.66"]
        result.extend((f"ENTITY\t{name}",
                       f"TRANSFORM\t{name}\t{x:.6g}\t0.55\t{z:.6g}\t0\t0\t0\t0.7\t0.7\t0.7",
                       "\t".join(render)))
    return result


def run_probe(package: Path, output: Path, *, width: int = 1920, height: int = 1080,
              frames: int = 360, warmup_frames: int = 60,
              player_executable: Path | None = None, route: str = "input",
              stress_actors: int = 0) -> dict:
    if width < 320 or height < 240 or frames <= warmup_frames or warmup_frames < 0:
        raise ValueError("Invalid native-resolution probe dimensions or frame count.")
    if route not in {"input", "motion"}:
        raise ValueError("Route must be 'input' or 'motion'.")
    package = package.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    if not (package / "TCPlayer.exe").is_file() or not (package / "Content" / "main.tcruntime").is_file():
        raise FileNotFoundError("A packaged Windows Player is required.")
    trial = output / "package"
    shutil.copytree(package, trial)
    if player_executable is not None:
        shutil.copy2(player_executable.resolve(), trial / "TCPlayer.exe")
    scene = trial / "Content" / "main.tcruntime"
    rows = scene.read_text(encoding="utf-8").splitlines()
    render_rows = [index for index, row in enumerate(rows) if row.startswith("RENDERSETTINGS\t")]
    if len(render_rows) != 1:
        raise ValueError("Expected one authored RENDERSETTINGS record.")
    fields = rows[render_rows[0]].split("\t")
    if len(fields) < 4:
        raise ValueError("Malformed RENDERSETTINGS record.")
    authored_scale = fields[3]
    fields[3] = "1"
    rows[render_rows[0]] = "\t".join(fields)
    rows = add_stress_props(rows, stress_actors)
    scene.write_text("\n".join(rows) + "\n", encoding="utf-8")
    def measure(name: str, *, unsynced: bool) -> tuple[Path, subprocess.CompletedProcess[str], dict, str]:
        profile = output / f"full-resolution-{name}-profile.jsonl"
        command = [str(trial / "TCPlayer.exe"), "--scene", str(scene),
                   "--renderer", "d3d11", "--require-renderer", "--frames", str(frames),
                   "--window-width", str(width), "--window-height", str(height), "--borderless",
                   "--scripted-motion-demo" if route == "motion" else "--scripted-input"]
        if unsynced:
            command.append("--benchmark-unsynced")
        command.extend(("--log", str(profile)))
        completed = subprocess.run(command, cwd=trial, capture_output=True, text=True,
                                   timeout=max(90.0, frames / 15.0 + 60.0), check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        summary: dict = {}
        error = ""
        if completed.returncode == 0 and profile.is_file():
            try:
                summary = steady_profile(profile, warmup_frames=warmup_frames)
            except (OSError, ValueError, RuntimeError) as exc:
                error = str(exc)
        return profile, completed, summary, error
    profile, completed, summary, profile_error = measure("gpu-work", unsynced=True)
    paced_profile, paced, paced_summary, paced_error = measure("paced", unsynced=False)
    # Capturing a BMP stalls the next frame; keep it out of the pacing sample.
    capture_frame = max(1, min(frames, frames // 2))
    screenshot = output / "full-resolution-paced.bmp"
    capture_command = [str(trial / "TCPlayer.exe"), "--scene", str(scene),
                       "--renderer", "d3d11", "--require-renderer", "--frames", str(capture_frame),
                       "--window-width", str(width), "--window-height", str(height), "--borderless",
                       "--scripted-motion-demo" if route == "motion" else "--scripted-input",
                       "--screenshot", str(screenshot), "--screenshot-frame", str(capture_frame)]
    capture = subprocess.run(capture_command, cwd=trial, capture_output=True, text=True,
                             timeout=max(90.0, capture_frame / 15.0 + 60.0), check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    render = summary.get("render_config", {})
    metrics = summary.get("metrics_ms", {})
    paced_metrics = paced_summary.get("metrics_ms", {})
    window_results = pacing_windows(paced_profile, warmup_frames=warmup_frames) if paced_profile.is_file() else []
    captured_size: tuple[int, int] | None = None
    if screenshot.is_file():
        header = screenshot.read_bytes()[:54]
        if len(header) == 54 and header[:2] == b"BM":
            captured_size = struct.unpack_from("<ii", header, 18)
    checks = {
        "players_completed": completed.returncode == 0 and paced.returncode == 0,
        "visual_capture_completed": capture.returncode == 0 and screenshot.is_file(),
        "native_resolution": render.get("render_scale") == 1.0 and
            render.get("render_width") == width and render.get("render_height") == height and
            paced_summary.get("render_config") == render,
        "native_size_visual_capture": captured_size is not None and
            (captured_size[0], abs(captured_size[1])) == (width, height),
        "real_adapter": summary.get("graphics_adapter", {}).get("status") == "passed" and
            paced_summary.get("graphics_adapter") == summary.get("graphics_adapter"),
        "same_draw_load": summary.get("draw_calls_min", 0) > 0 and
            paced_summary.get("draw_calls_min") == summary.get("draw_calls_min") and
            paced_summary.get("skinned_draws_min") == summary.get("skinned_draws_min"),
        "stress_draws_present": stress_actors == 0 or
            (summary.get("draw_calls_min", 0) >= stress_actors + 2 and
             summary.get("skinned_draws_min", 0) >= 2),
        "scripted_route_exercised": (
            len(paced_summary.get("windowed_animation_clips", [])) >= 4 and
            len(summary.get("windowed_animation_clips", [])) >= 4
            if route == "motion" else
            bool(paced_summary.get("windowed_player_moved")) and
            bool(summary.get("windowed_player_moved"))),
        "unsynced_gpu_work": summary.get("vsync_mode") == "unsynced" and
            summary.get("gpu_sample_coverage", 0) >= 0.95 and
            summary.get("measured_frames", 0) >= frames - warmup_frames,
        "gpu_work_p95_within_60fps_budget": metrics.get("gpu_ms", {}).get("p95", float("inf")) <= 16.667,
        "paced_vsync_run": paced_summary.get("vsync_mode") == "vsynced" and
            paced_summary.get("measured_frames", 0) >= frames - warmup_frames,
        "paced_interval_p95_within_budget":
            paced_metrics.get("frame_interval_ms", {}).get("p95", float("inf")) <= 17.167,
        "paced_interval_p99_within_budget":
            paced_metrics.get("frame_interval_ms", {}).get("p99", float("inf")) <= 33.334,
        "paced_windows_within_budget": bool(window_results) and all(
            window["p95_ms"] <= 17.167 and window["p99_ms"] <= 33.334
            for window in window_results),
    }
    report = {"status": "passed" if all(checks.values()) else "failed",
              "scope": "one-Windows-PC synthetic-scene GPU-work and pacing diagnostic; not release qualification",
              "checks": checks, "authored_render_scale": authored_scale,
              "target_window": [width, height], "frames": frames, "warmup_frames": warmup_frames,
              "route": route, "stress_actors": stress_actors,
              "paced_windows": window_results,
              "visual_capture": str(screenshot), "visual_capture_exit_code": capture.returncode,
              "visual_capture_stderr": capture.stderr[-1500:], "captured_size": captured_size,
              "gpu_work": {"profile": str(profile), "summary": summary,
                           "exit_code": completed.returncode, "stderr": completed.stderr[-1500:],
                           "profile_error": profile_error},
              "paced": {"profile": str(paced_profile), "summary": paced_summary,
                        "exit_code": paced.returncode, "stderr": paced.stderr[-1500:],
                        "profile_error": paced_error}}
    (output / "full_resolution_probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--player", type=Path, help="Optional freshly built TCPlayer.exe")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--frames", type=int, default=360)
    parser.add_argument("--warmup-frames", type=int, default=60)
    parser.add_argument("--route", choices=("input", "motion"), default="input")
    parser.add_argument("--stress-actors", type=int, default=0,
                        help="Isolated render-only cube load (0-2000) combined with the package scene")
    args = parser.parse_args()
    report = run_probe(args.package, args.output, width=args.width, height=args.height,
                       frames=args.frames, warmup_frames=args.warmup_frames,
                       player_executable=args.player, route=args.route,
                       stress_actors=args.stress_actors)
    print(json.dumps({"status": report["status"], "checks": report["checks"],
                      "gpu_p95_ms": report["gpu_work"]["summary"].get("metrics_ms", {}).get("gpu_ms", {}).get("p95"),
                      "paced_interval_p95_ms": report["paced"]["summary"].get("metrics_ms", {}).get("frame_interval_ms", {}).get("p95"),
                      "report": str(args.output / "full_resolution_probe.json")}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
