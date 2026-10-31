"""Reproducible packaged-player evidence for the third-person acceptance project."""

from __future__ import annotations

import argparse
import array
from collections import Counter
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
import re
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import time
from typing import Any
import wave

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.motion_matching_service import load_motion_library
from tech_connector.game_engine.scene.native_fbx_service import find_blender_executable, import_native_fbx
from tech_connector.game_engine.runtime.tc_player_build_service import (
    build_windows_player,
    compile_tcscene_for_runtime,
    summarize_player_profile,
    validate_packaged_assets,
    validate_player_package,
    validate_windowed_player,
)
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene
from tech_connector.game_engine.integration.verify_skm_motion_demo import verify as verify_skm_motion_demo
from tech_connector.game_engine.integration.verify_skm_ui_capture import blue_character_bounds, verify_control_card
from tech_connector.game_engine.integration.build_skm_motion_demo import RUNTIME_CLIPS


SCHEMA = "tech_connector.third_person_acceptance.v1"
DEFAULT_FRAMES = 600
DEFAULT_WARMUP_FRAMES = 60


def release_target_assessment(technical_pass: bool, host_system: str) -> dict[str, Any]:
    """Keep a successful Windows demo from implicitly qualifying release targets."""
    windows_gates = {
        "packaged_technical_baseline": "passed" if technical_pass and host_system == "Windows" else "not_proven",
        "contact_aware_foot_lock_root_motion_turning": "not_proven",
        "complete_gameplay_and_runtime_ui": "not_proven",
        "physical_controller_gameplay_ui_rebind": "not_proven",
        "representative_pc_hardware_performance": "not_proven",
        "audio_device_change_and_mixing": "not_proven",
        "accessibility_and_visual_signoff": "not_proven",
        "production_content_and_save_upgrade": "not_proven",
        "save_recovery_and_migration_matrix": "not_proven",
    }
    console_gates = {
        "native_render": "not_proven",
        "native_input": "not_proven",
        "native_audio": "not_proven",
        "native_storage": "not_proven",
        "native_lifecycle": "not_proven",
        "native_packaging": "not_proven",
        "sdk_devkit_validation": "not_proven",
        "platform_certification": "not_proven",
    }
    def target(gates: dict[str, str]) -> dict[str, Any]:
        return {"status": "ready" if all(value == "passed" for value in gates.values()) else "not_ready",
                "gates": gates}
    return {"windows_pc": target(windows_gates),
            "xbox_series_xs": target(console_gates.copy()),
            "ps5": target(console_gates.copy())}


def host_hardware_receipt(graphics_adapter: dict[str, Any]) -> dict[str, Any]:
    """Describe this diagnostic host without treating one machine as a device matrix."""
    physical_memory_bytes: int | None = None
    graphics_driver: dict[str, Any] = {"status": "unavailable"}
    adapter_name = str(graphics_adapter.get("gpu_adapter_name", ""))
    if "NVIDIA" in adapter_name.upper() and shutil.which("nvidia-smi"):
        try:
            probe = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for row in probe.stdout.splitlines() if probe.returncode == 0 else ():
                name, separator, version = row.rpartition(",")
                if separator and name.strip().casefold() == adapter_name.casefold() and version.strip():
                    graphics_driver = {"status": "measured", "version": version.strip(),
                                       "source": "nvidia-smi"}
                    break
        except (OSError, subprocess.TimeoutExpired):
            pass
    if platform.system() == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in (
                            "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                            "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                physical_memory_bytes = int(status.ullTotalPhys)
        except (AttributeError, OSError):
            pass
    return {
        "scope": "single_host_diagnostic",
        "os_system": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine_architecture": platform.machine(),
        "cpu_description": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or "unavailable",
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": physical_memory_bytes,
        "graphics_adapter": graphics_adapter,
        "graphics_driver": graphics_driver,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999999) - 1))]


def memory_trend(frame_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Report sparse process-memory samples without claiming leak qualification."""
    samples = [(int(row["frame"]), int(row["private_bytes"]), int(row["working_set_bytes"]))
               for row in frame_rows if isinstance(row.get("private_bytes"), int)
               and isinstance(row.get("working_set_bytes"), int)
               and row["private_bytes"] > 0 and row["working_set_bytes"] > 0]
    if len(samples) < 6:
        return {"status": "not_proven", "sample_count": len(samples)}
    window = max(3, len(samples) // 5)
    first = int(statistics.median(sample[1] for sample in samples[:window]))
    last = int(statistics.median(sample[1] for sample in samples[-window:]))
    return {"status": "measured", "sample_count": len(samples),
            "first_frame": samples[0][0], "last_frame": samples[-1][0],
            "first_window_private_median_bytes": first,
            "last_window_private_median_bytes": last,
            "private_growth_bytes": last - first,
            "peak_private_bytes": max(sample[1] for sample in samples),
            "peak_working_set_bytes": max(sample[2] for sample in samples)}


def steady_profile(profile_path: str | Path, *, warmup_frames: int) -> dict[str, Any]:
    rows = summarize_player_profile(profile_path)["frame_profiles"]
    steady = rows[max(0, int(warmup_frames)):]
    if not steady or any("gpu_ms" not in row for row in steady):
        raise RuntimeError("Sustained graphical profile is missing steady-state GPU frames.")
    if any("frame_interval_ms" not in row or not math.isfinite(float(row["frame_interval_ms"])) or
           float(row["frame_interval_ms"]) <= 0.0 for row in steady):
        raise RuntimeError("Sustained graphical profile is missing valid wall-clock frame intervals.")
    if any(not isinstance(row.get("gpu_samples_ms"), list) for row in steady):
        raise RuntimeError("Sustained graphical profile is missing raw GPU timing samples.")
    gpu_samples = [float(sample) for row in steady for sample in row["gpu_samples_ms"]]
    if any(not math.isfinite(sample) or sample <= 0.0 for sample in gpu_samples):
        raise RuntimeError("Sustained graphical profile contains invalid raw GPU timing samples.")
    skinned_draws_min = min(
        int(row.get("gpu_skinned_draws", 0)) + int(row.get("cpu_skinned_draws", 0))
        for row in steady
    )
    gpu_skinned_draws_min = min(int(row.get("gpu_skinned_draws", 0)) for row in steady)
    cpu_skinned_draws_min = min(int(row.get("cpu_skinned_draws", 0)) for row in steady)
    cpu_skinned_draws_max = max(int(row.get("cpu_skinned_draws", 0)) for row in steady)
    gpu_skin_stream_sets_max = max(int(row.get("gpu_skin_stream_sets", 0)) for row in steady)
    gpu_skin_palette_sets_min = min(int(row.get("gpu_skin_palette_sets", 0)) for row in steady)
    inverse_bind_reads_max = max(int(row.get("inverse_bind_reads", 0)) for row in steady)
    inverse_bind_reads_min = min(int(row.get("inverse_bind_reads", 0)) for row in steady)
    inverse_bind_cache_hits_min = min(int(row.get("inverse_bind_cache_hits", 0)) for row in steady)
    positions = [float(row["player_x"]) for row in steady if "player_x" in row]
    clips = sorted({str(row.get("active_animation") or "") for row in steady if row.get("active_animation")})
    route_complete = all(all(key in row for key in ("frame", "player_x", "player_z", "active_animation"))
                         for row in steady)
    route_hash = hashlib.sha256(json.dumps(
        [(row["frame"], row["player_x"], row["player_z"], row["active_animation"])
         for row in steady], separators=(",", ":")).encode("utf-8")).hexdigest() if route_complete else None
    draw_calls_min = min(int(row.get("draw_calls", 0)) for row in steady)
    submitted_geometry_draws_min = min(int(row.get("submitted_geometry_draws", 0)) for row in steady)
    submitted_shadow_draws_min = min(int(row.get("submitted_shadow_draws", 0)) for row in steady)
    metrics = {}
    for key in ("frame_interval_ms", "frame_ms", "gpu_ms", "graph_ms", "physics_ms"):
        values = [float(row.get(key, 0.0)) for row in steady]
        metrics[key] = {
            "average": sum(values) / len(values),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "maximum": max(values),
        }
    optional_wall_keys = ("render_wall_ms", "present_wall_ms", "cpu_skin_wall_ms",
                          "shadow_wall_ms", "geometry_wall_ms", "post_wall_ms")
    for key in optional_wall_keys:
        coverage = [key in row for row in steady]
        if any(coverage) and not all(coverage):
            raise RuntimeError(f"Sustained graphical profile has incomplete {key} coverage.")
        if all(coverage):
            values = [float(row[key]) for row in steady]
            if any(not math.isfinite(value) or value < 0.0 or
                   (key == "render_wall_ms" and value == 0.0) for value in values):
                raise RuntimeError(f"Sustained graphical profile has invalid {key} samples.")
            metrics[key] = {
                "average": sum(values) / len(values),
                "p95": _percentile(values, 0.95),
                "p99": _percentile(values, 0.99),
                "maximum": max(values),
            }
    if all("render_wall_ms" in row and "present_wall_ms" in row for row in steady):
        if any(float(row["present_wall_ms"]) > float(row["render_wall_ms"]) for row in steady):
            raise RuntimeError("Sustained graphical profile has Present time exceeding render time.")
        values = [max(0.0, float(row["render_wall_ms"]) - float(row["present_wall_ms"]))
                  for row in steady]
        metrics["render_nonpresent_wall_ms"] = {
            "average": sum(values) / len(values),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "maximum": max(values),
        }
    metrics["gpu_sample_ms"] = {
        "average": sum(gpu_samples) / len(gpu_samples) if gpu_samples else 0.0,
        "p95": _percentile(gpu_samples, 0.95),
        "p99": _percentile(gpu_samples, 0.99),
        "maximum": max(gpu_samples) if gpu_samples else 0.0,
    }
    adapter_keys = (
        "gpu_adapter_name", "gpu_vendor_id", "gpu_device_id",
        "gpu_dedicated_video_memory_bytes", "gpu_software_adapter",
    )
    adapter_rows = [tuple(row.get(key) for key in adapter_keys) for row in steady]
    adapter_consistent = len(set(adapter_rows)) == 1
    adapter = dict(zip(adapter_keys, adapter_rows[0])) if adapter_consistent else {}
    adapter_recorded = (
        adapter_consistent and bool(adapter.get("gpu_adapter_name"))
        and isinstance(adapter.get("gpu_vendor_id"), int) and adapter["gpu_vendor_id"] > 0
        and isinstance(adapter.get("gpu_device_id"), int) and adapter["gpu_device_id"] > 0
        and adapter.get("gpu_software_adapter") is False
    )
    render_keys = ("render_scale", "render_width", "render_height", "temporal", "dynamic_resolution")
    render_rows = [tuple(row.get(key) for key in render_keys) for row in steady]
    render_consistent = len(set(render_rows)) == 1
    render_config = dict(zip(render_keys, render_rows[0])) if render_consistent else {}
    render_recorded = (
        render_consistent and isinstance(render_config.get("render_scale"), (int, float))
        and 0.25 <= render_config["render_scale"] <= 1.0
        and isinstance(render_config.get("render_width"), int) and render_config["render_width"] > 0
        and isinstance(render_config.get("render_height"), int) and render_config["render_height"] > 0
        and isinstance(render_config.get("temporal"), bool)
        and isinstance(render_config.get("dynamic_resolution"), bool)
    )
    vsync_values = {row.get("vsync") for row in steady}
    vsync_mode = "vsynced" if vsync_values == {True} else (
        "unsynced" if vsync_values == {False} else "not_proven")
    return {
        "warmup_frames": min(len(rows), max(0, int(warmup_frames))),
        "measured_frames": len(steady), "metrics_ms": metrics,
        "process_memory": memory_trend(steady),
        "gpu_sample_count": len(gpu_samples),
        "gpu_sample_coverage": len(gpu_samples) / len(steady),
        "skinned_draws_min": skinned_draws_min,
        "gpu_skinned_draws_min": gpu_skinned_draws_min,
        "cpu_skinned_draws_min": cpu_skinned_draws_min,
        "cpu_skinned_draws_max": cpu_skinned_draws_max,
        "gpu_skin_stream_sets_max": gpu_skin_stream_sets_max,
        "gpu_skin_palette_sets_min": gpu_skin_palette_sets_min,
        "inverse_bind_reads_min": inverse_bind_reads_min,
        "inverse_bind_reads_max": inverse_bind_reads_max,
        "inverse_bind_cache_hits_min": inverse_bind_cache_hits_min,
        "windowed_player_moved": len(positions) == len(steady) and max(positions) - min(positions) > 0.5,
        "windowed_animation_transitioned": len(clips) >= 2,
        "windowed_animation_clips": clips,
        "scripted_route_hash": route_hash,
        "draw_calls_min": draw_calls_min,
        "submitted_geometry_draws_min": submitted_geometry_draws_min,
        "submitted_shadow_draws_min": submitted_shadow_draws_min,
        "graphics_adapter": {"status": "passed" if adapter_recorded else "not_proven", **adapter},
        "render_config": {"status": "passed" if render_recorded else "not_proven", **render_config},
        "vsync_mode": vsync_mode,
    }


def compare_gpu_probe_workload(vsynced: dict[str, Any], unsynced: dict[str, Any]) -> dict[str, Any]:
    """Require the work-only probe to exercise the same renderer, scene and input route."""
    def comparable_submissions(key: str) -> bool:
        first = vsynced.get(key)
        second = unsynced.get(key)
        if (not isinstance(first, int) or isinstance(first, bool) or
                not isinstance(second, int) or isinstance(second, bool)):
            return False
        return first > 0 and second > 0 and abs(first - second) <= max(first, second) * 0.1

    checks = {
        "modes_labeled": vsynced.get("vsync_mode") == "vsynced" and
            unsynced.get("vsync_mode") == "unsynced",
        "render_config_equal": vsynced.get("render_config", {}).get("status") == "passed" and
            vsynced.get("render_config") == unsynced.get("render_config"),
        "adapter_equal": vsynced.get("graphics_adapter", {}).get("status") == "passed" and
            vsynced.get("graphics_adapter") == unsynced.get("graphics_adapter"),
        "draw_load_equal": vsynced.get("draw_calls_min", 0) > 0 and
            vsynced.get("draw_calls_min") == unsynced.get("draw_calls_min") and
            vsynced.get("skinned_draws_min") == unsynced.get("skinned_draws_min"),
        "submitted_draw_load_comparable": comparable_submissions("submitted_geometry_draws_min") and
            comparable_submissions("submitted_shadow_draws_min"),
        "scripted_route_equal": bool(vsynced.get("scripted_route_hash")) and
            vsynced.get("scripted_route_hash") == unsynced.get("scripted_route_hash") and
            bool(vsynced.get("windowed_player_moved")) and
            bool(unsynced.get("windowed_player_moved")) and
            bool(vsynced.get("windowed_animation_transitioned")) and
            bool(unsynced.get("windowed_animation_transitioned")),
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks}


def measure_unsynced_gpu_work(package: Path, *, frames: int, warmup_frames: int) -> dict[str, Any]:
    """Measure render work separately from the vsynced gameplay/pacing run."""
    package = package.resolve()
    profile = package / "Content" / "unsynced-gpu-work-profile.jsonl"
    profile.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--frames", str(frames),
         "--scripted-input", "--benchmark-unsynced", "--log", str(profile)],
        cwd=package, capture_output=True, text=True, check=False,
        timeout=max(60.0, frames / 30.0 + 30.0),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Unsynced GPU-work probe failed (exit {completed.returncode}): " +
                           (completed.stderr or completed.stdout)[-700:])
    rows = summarize_player_profile(profile)["frame_profiles"]
    if len(rows) < frames or any(row.get("vsync") is not False for row in rows):
        raise RuntimeError("Unsynced GPU-work probe lacks complete explicit no-vsync frame evidence.")
    return {"mode": "unsynced_gpu_work_only", "profile": str(profile),
            **steady_profile(profile, warmup_frames=warmup_frames)}


def check_capture_write_failure(package: Path) -> dict[str, Any]:
    """A failed screenshot destination must fail the packaged player cleanly."""
    target = package / "Content" / "capture-write-failure-target"
    target.mkdir(exist_ok=True)
    try:
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--frames", "8",
             "--screenshot", str(target), "--screenshot-frame", "2"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "blocked", "exit_code": None, "error": str(exc)}
    passed = completed.returncode == 4 and (
        "renderer frame failed: Could not open the GPU capture destination." in completed.stderr
    ) and target.is_dir()
    return {"status": "passed" if passed else "blocked", "exit_code": completed.returncode,
            "stderr": completed.stderr[-700:]}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qualification_input_receipt(value: str | Path | None, *, package: bool = False) -> dict[str, Any]:
    """Identify external qualification inputs without treating a package path as evidence."""
    if value is None:
        return {"status": "not_requested"}
    path = Path(value).expanduser().resolve()
    if not package:
        return ({"status": "present", "path": str(path), "sha256": _hash(path)}
                if path.is_file() else {"status": "missing", "path": str(path)})
    receipt: dict[str, Any] = {"status": "present" if path.is_dir() else "missing", "path": str(path)}
    if path.is_dir():
        for name, relative in (("player", "TCPlayer.exe"), ("scene", "Content/main.tcruntime")):
            candidate = path / relative
            safe_candidate = (candidate.is_file() and not candidate.is_symlink() and
                              not any(parent.is_symlink() for parent in candidate.parents
                                      if path in parent.parents) and
                              path in candidate.resolve().parents)
            receipt[f"{name}_sha256"] = _hash(candidate) if safe_candidate else None
        if not receipt["player_sha256"] or not receipt["scene_sha256"]:
            receipt["status"] = "incomplete"
        files: list[Path] = []
        for candidate in path.rglob("*"):
            if candidate.is_symlink():
                receipt["status"] = "incomplete"
            elif candidate.is_file():
                if path in candidate.resolve().parents:
                    files.append(candidate)
                else:
                    receipt["status"] = "incomplete"
        files.sort(key=lambda candidate: candidate.relative_to(path).as_posix())
        tree = hashlib.sha256()
        for candidate in files:
            # Length-delimit the path so different file layouts cannot share a receipt.
            relative = candidate.relative_to(path).as_posix().encode("utf-8")
            tree.update(len(relative).to_bytes(8, "big"))
            tree.update(relative)
            tree.update(bytes.fromhex(_hash(candidate)))
        receipt["file_count"] = len(files)
        receipt["package_sha256"] = tree.hexdigest()
    return receipt


def qualification_inputs(
    dcc_fbx: str | Path | None, motion_demo_package: str | Path | None,
    motion_report: str | Path | None, motion_visual_baseline: str | Path | None,
    motion_previous_package: str | Path | None,
    player_executable: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "player_executable": qualification_input_receipt(player_executable),
        "dcc_fbx": qualification_input_receipt(dcc_fbx),
        "motion_demo_package": qualification_input_receipt(motion_demo_package, package=True),
        "motion_report": qualification_input_receipt(motion_report),
        "motion_visual_baseline": qualification_input_receipt(motion_visual_baseline),
        "motion_previous_package": qualification_input_receipt(motion_previous_package, package=True),
    }


def qualification_inputs_stable(
    initial: dict[str, dict[str, Any]], final: dict[str, dict[str, Any]],
) -> bool:
    return initial == final and all(
        row["status"] in {"present", "not_requested"} for row in final.values())


def compare_bmp_baseline(
    reference: Path, actual: Path, *,
    channel_tolerance: int = 20, max_changed_fraction: float = 0.002,
    dynamic_rect: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """Compare static pixels and, optionally, dynamic blue actor/gold obstacle landmarks."""
    def pixels(path: Path) -> tuple[tuple[int, int], bytes, int]:
        data = path.read_bytes()
        if len(data) < 54 or data[:2] != b"BM":
            raise ValueError("Visual regression requires a 24-bit BMP.")
        offset = struct.unpack_from("<I", data, 10)[0]
        width, height = struct.unpack_from("<ii", data, 18)
        planes = struct.unpack_from("<H", data, 26)[0]
        depth = struct.unpack_from("<H", data, 28)[0]
        compression = struct.unpack_from("<I", data, 30)[0]
        if (width <= 0 or height <= 0 or planes != 1 or depth != 24 or
                compression != 0 or offset < 54):
            raise ValueError("Visual regression requires an uncompressed 24-bit BMP.")
        stride = (width * 3 + 3) & ~3
        end = offset + stride * height
        if end > len(data):
            raise ValueError("Visual regression BMP is truncated.")
        return (width, height), data[offset:end], stride

    size_a, first, stride_a = pixels(reference)
    size_b, second, stride_b = pixels(actual)
    if size_a != size_b or stride_a != stride_b:
        return {"passed": False, "reason": "dimensions_changed",
                "reference_size": size_a, "actual_size": size_b}
    width, height = size_a
    if dynamic_rect is not None:
        x0, y0, x1, y1 = dynamic_rect
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError("Dynamic visual region is outside the BMP.")
        if x0 == 0 and y0 == 0 and x1 == width and y1 == height:
            raise ValueError("Dynamic visual region cannot cover the entire BMP.")
    changed = 0
    total_delta = 0
    compared = 0
    landmarks = [{"blue": [], "gold": []}, {"blue": [], "gold": []}]
    for row in range(height):
        begin = row * stride_a
        for column in range(width):
            offset = begin + column * 3
            delta = max(abs(first[offset + channel] - second[offset + channel])
                        for channel in range(3))
            inside_dynamic = dynamic_rect is not None and x0 <= column < x1 and y0 <= height - 1 - row < y1
            if inside_dynamic:
                for image_index, image in enumerate((first, second)):
                    blue, green, red = image[offset:offset + 3]
                    point = (column, height - 1 - row)
                    if blue > red + 35 and blue > green + 15 and blue > 100 and red < 150:
                        landmarks[image_index]["blue"].append(point)
                    if red > 170 and green > 140 and blue < 190 and red > blue + 20:
                        landmarks[image_index]["gold"].append(point)
                continue
            total_delta += delta
            changed += delta > channel_tolerance
            compared += 1
    fraction = changed / compared
    semantic: dict[str, Any] = {}
    if dynamic_rect is not None:
        for color in ("blue", "gold"):
            expected, observed = (landmarks[index][color] for index in (0, 1))
            def bounds(points: list[tuple[int, int]]) -> tuple[int, int, int, int]:
                return (min(point[0] for point in points), min(point[1] for point in points),
                        max(point[0] for point in points), max(point[1] for point in points))
            expected_bounds = bounds(expected) if expected else None
            observed_bounds = bounds(observed) if observed else None
            count_ratio = min(len(expected), len(observed)) / max(len(expected), len(observed)) if expected and observed else 0.0
            aligned = bool(expected_bounds and observed_bounds and all(
                abs(a - b) <= 20 for a, b in zip(expected_bounds, observed_bounds)))
            semantic[color] = {"reference_pixels": len(expected), "actual_pixels": len(observed),
                               "count_ratio": count_ratio, "reference_bounds": expected_bounds,
                               "actual_bounds": observed_bounds, "passed": count_ratio >= 0.8 and aligned}
    passed = fraction <= max_changed_fraction and all(item["passed"] for item in semantic.values())
    return {"passed": passed, "changed_fraction": fraction,
            "mean_max_channel_delta": total_delta / compared,
            "channel_tolerance": channel_tolerance,
            "max_changed_fraction": max_changed_fraction,
            "dynamic_rect": dynamic_rect, "dynamic_landmarks": semantic,
            "reference": str(reference), "actual": str(actual)}


def check_visual_landmarks(screenshot: Path, *, button_x: float = 0.16,
                           button_y: float = 0.14, panel_y: float = 0.04) -> dict[str, Any]:
    """Probe stable HUD pixels in the actual captured D3D11 back buffer."""
    with screenshot.open("rb") as stream:
        header = stream.read(54)
        if len(header) != 54 or header[:2] != b"BM":
            raise ValueError("Visual baseline requires a 24-bit BMP screenshot.")
        offset = struct.unpack_from("<I", header, 10)[0]
        width, height = struct.unpack_from("<ii", header, 18)
        planes = struct.unpack_from("<H", header, 26)[0]
        depth = struct.unpack_from("<H", header, 28)[0]
        compression = struct.unpack_from("<I", header, 30)[0]
        if (depth != 24 or planes != 1 or compression != 0 or
                width < 400 or height < 200 or offset < 54):
            raise ValueError("Visual baseline has unsupported dimensions or pixel format.")
        row_bytes = (width * 3 + 3) & ~3
        stream.seek(0, 2)
        if stream.tell() < offset + row_bytes * height:
            raise ValueError("Visual baseline BMP is truncated.")

        def pixel(x: int, y: int) -> tuple[int, int, int]:
            stream.seek(offset + (height - 1 - y) * row_bytes + x * 3)
            blue, green, red = stream.read(3)
            return red, green, blue

        panel = pixel(round(width * 0.20), round(height * panel_y))
        button = pixel(round(width * button_x), round(height * button_y))
        sky = pixel(round(width * 0.42), round(height * 0.07))
    distance = lambda left, right: sum(abs(a - b) for a, b in zip(left, right))
    passed = distance(panel, sky) > 110 and distance(button, sky) > 95 and button[2] > button[0] + 25
    return {"passed": passed, "panel_rgb": panel, "button_rgb": button, "sky_rgb": sky,
            "panel_sky_distance": distance(panel, sky), "button_sky_distance": distance(button, sky)}


def check_ui_image_pixels(screenshot: Path) -> dict[str, Any]:
    """Check that the authored image rect contains actual texture detail, not a flat placeholder."""
    with screenshot.open("rb") as stream:
        header = stream.read(54)
        if len(header) != 54 or header[:2] != b"BM" or struct.unpack_from("<H", header, 28)[0] != 24:
            raise ValueError("UI image check requires a 24-bit BMP screenshot.")
        offset = struct.unpack_from("<I", header, 10)[0]
        width, height = struct.unpack_from("<ii", header, 18)
        planes = struct.unpack_from("<H", header, 26)[0]
        compression = struct.unpack_from("<I", header, 30)[0]
        if width < 400 or height < 200 or planes != 1 or compression != 0 or offset < 54:
            raise ValueError("UI image capture has unsupported dimensions or pixel format.")
        row_bytes = (width * 3 + 3) & ~3
        stream.seek(0, 2)
        if stream.tell() < offset + row_bytes * height:
            raise ValueError("UI image capture BMP is truncated.")
        # Interior of character_icon's 248,76,56,42 canvas rectangle.
        colors = []
        for canvas_y in (84, 92, 100, 108):
            for canvas_x in (255, 265, 275, 285, 295):
                x = round(canvas_x * width / 1280)
                y = round(canvas_y * height / 720)
                stream.seek(offset + (height - 1 - y) * row_bytes + x * 3)
                colors.append(tuple(stream.read(3)))
    luminance = [sum(color) for color in colors]
    spread = max(luminance) - min(luminance)
    return {"passed": len(set(colors)) >= 6 and spread >= 60,
            "distinct_colors": len(set(colors)), "luminance_spread": spread}


def _nudge_first_obj_vertex(source: Path) -> None:
    lines = source.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("v "):
            parts = line.split()
            if len(parts) != 4:
                continue
            parts[1] = format(float(parts[1]) + 0.005, ".9g")
            lines[index] = " ".join(parts)
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise ValueError("Character OBJ has no vertex to reimport.")


def reimport_player_mesh(api: TCEditorAPI, level_asset_id: str, run: Path) -> dict[str, Any]:
    """Route a topology-preserving character mesh change through the public API."""
    players = [actor for actor in api.level_actors(level_asset_id) if actor.get("name") == "Player"]
    if len(players) != 1:
        raise RuntimeError("Third-person Level must have one Player actor.")
    original = Path(str(dict(players[0].get("render") or {}).get("mesh") or ""))
    if not original.is_file():
        raise FileNotFoundError(f"Starter character mesh is unavailable: {original}")
    source = run / "character-source" / "AcceptanceMannequin.obj"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, source)
    imported = api.import_asset(source, folder="Assets/Characters/Imported", type_id="tc.static_mesh")
    mesh_id = imported.asset_id
    before = api.database.asset(mesh_id)
    if before is None:
        raise RuntimeError("Imported character mesh is absent from the asset database.")
    before_hash = _hash(before.source_path)
    vertex_count = sum(1 for line in source.read_text(encoding="utf-8").splitlines() if line.startswith("v "))
    _nudge_first_obj_vertex(source)
    reimported = api.reimport_asset(mesh_id)
    after = api.database.asset(mesh_id)
    if after is None:
        raise RuntimeError("Reimported character mesh disappeared from the asset database.")
    binding = api.set_level_actor_render_mesh(level_asset_id, "Player", mesh_id)
    revised_vertex_count = sum(1 for line in after.source_path.read_text(encoding="utf-8").splitlines() if line.startswith("v "))
    return {
        "asset_id": mesh_id,
        "source": str(source),
        "mesh_source": str(after.source_path),
        "before_sha256": before_hash,
        "after_sha256": _hash(after.source_path),
        "identity_preserved": reimported.asset_id == mesh_id,
        "revision_advanced": after.revision > before.revision,
        "topology_preserved": vertex_count > 0 and vertex_count == revised_vertex_count,
        "level_linked": binding["mesh_asset_id"] == mesh_id,
    }


def check_skeletal_fbx_reimport(api: TCEditorAPI, source_path: str | Path, run: Path) -> dict[str, Any]:
    """Qualify a real skinning source and a topology-preserving FBX revision."""
    original = Path(source_path).expanduser().resolve()
    if not original.is_file() or original.suffix.lower() != ".fbx":
        raise FileNotFoundError(f"A readable skeletal FBX source is required: {original}")
    original_sha256 = _hash(original)
    source = run / "dcc-fbx-source" / original.name
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, source)
    first = import_native_fbx(source)
    first_binding = first.build_deformation_binding()
    imported = api.import_asset(source, folder="Assets/Characters/DccImported", type_id="tc.static_mesh")
    before = api.database.asset(imported.asset_id)
    if before is None:
        raise RuntimeError("The imported skeletal FBX is absent from the asset database.")
    before_revision = before.revision
    before_sha256 = _hash(before.source_path)
    blender = find_blender_executable()
    if blender is None:
        raise RuntimeError("Blender is required to revise the disposable FBX source.")
    revised = source.with_name(source.stem + "_revised.fbx")
    fixture = Path(__file__).with_name("blender_fbx_reimport_fixture.py")
    completed = subprocess.run(
        [str(blender), "--background", "--factory-startup", "--python", str(fixture),
         "--", str(source), str(revised)],
        cwd=run, capture_output=True, text=True, timeout=180, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or "TC_FBX_REIMPORT_FIXTURE_OK" not in completed.stdout or not revised.is_file():
        raise RuntimeError("Could not create the skeletal FBX revision: " + (completed.stderr or completed.stdout)[-1500:])
    os.replace(revised, source)
    reimported = api.reimport_asset(imported.asset_id)
    after = api.database.asset(imported.asset_id)
    if after is None:
        raise RuntimeError("The reimported skeletal FBX disappeared from the asset database.")
    second = import_native_fbx(after.source_path)
    second_binding = second.build_deformation_binding()
    first_mesh = (first.manifest.get("meshes") or [None])[0]
    second_mesh = (second.manifest.get("meshes") or [None])[0]
    first_armature = (first.manifest.get("armatures") or [None])[0]
    second_armature = (second.manifest.get("armatures") or [None])[0]
    if not all((first_mesh, second_mesh, first_armature, second_armature)):
        raise RuntimeError("The FBX does not contain a mesh and armature in both revisions.")
    first_bones = [item.get("name") for item in first_armature.get("bones") or []]
    second_bones = [item.get("name") for item in second_armature.get("bones") or []]
    counts_preserved = (
        first_mesh.get("vertex_count") == second_mesh.get("vertex_count")
        and first_mesh.get("influence_count") == second_mesh.get("influence_count")
        and first_bones == second_bones
    )
    position_changed = any(a != b for a, b in zip(first.floats[:3], second.floats[:3]))
    return {
        "source": str(original), "source_sha256": original_sha256,
        "original_unchanged": _hash(original) == original_sha256,
        "asset_id": imported.asset_id, "identity_preserved": reimported.asset_id == imported.asset_id,
        "revision_advanced": after.revision > before_revision,
        "before_sha256": before_sha256, "after_sha256": _hash(after.source_path),
        "source_changed": before_sha256 != _hash(after.source_path) and position_changed,
        "topology_and_joint_names_preserved": counts_preserved,
        "bones": len(first_bones), "vertices": int(first_mesh["vertex_count"]),
        "influences": int(first_mesh["influence_count"]),
        "skin_contract_valid": not first_binding["contract_errors"] and not second_binding["contract_errors"],
        "animation_clips": len(first.manifest.get("actions") or []),
    }


def probe_packaged_skeletal_fbx(
    level_source: Path, imported_fbx: Path, run: Path, player: Path,
) -> dict[str, Any]:
    """Package the imported mesh and sparse skin as an additional rendered actor."""
    native = import_native_fbx(imported_fbx)
    binding = native.build_deformation_binding()
    if binding["contract_errors"] or len(binding["meshes"]) != 1:
        raise ValueError("The imported FBX has no single valid skinned mesh.")
    mesh = native.manifest["meshes"][0]
    skin = binding["meshes"][0]
    vertex_count = int(mesh["vertex_count"])
    triangle_count = int(mesh["triangle_count"])
    positions = array.array("f")
    positions.frombytes(skin["bind_vertices_f32"])
    indices = native.integers[int(mesh["triangle_index_offset"]):
                              int(mesh["triangle_index_offset"]) + triangle_count * 3]
    if len(positions) != vertex_count * 3 or len(indices) != triangle_count * 3 or max(indices) >= vertex_count:
        raise ValueError("FBX mesh buffers do not meet the indexed OBJ playback contract.")
    obj = run / "dcc-playback" / "SKM_Test_runtime.obj"
    obj.parent.mkdir(parents=True, exist_ok=True)
    normals = [0.0] * (vertex_count * 3)
    for index in range(triangle_count):
        a, b, c = (int(indices[index * 3 + corner]) for corner in range(3))
        ax, ay, az = positions[a * 3:a * 3 + 3]
        bx, by, bz = positions[b * 3:b * 3 + 3]
        cx, cy, cz = positions[c * 3:c * 3 + 3]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for vertex in (a, b, c):
            normals[vertex * 3] += nx
            normals[vertex * 3 + 1] += ny
            normals[vertex * 3 + 2] += nz
    with obj.open("w", encoding="ascii", newline="\n") as output:
        for index in range(vertex_count):
            output.write(f"v {positions[index * 3]:.9g} {positions[index * 3 + 1]:.9g} {positions[index * 3 + 2]:.9g}\n")
        for index in range(vertex_count):
            nx, ny, nz = normals[index * 3:index * 3 + 3]
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            output.write(f"vn {nx / length:.9g} {ny / length:.9g} {nz / length:.9g}\n")
        for index in range(triangle_count):
            corners = (int(indices[index * 3 + corner]) + 1 for corner in range(3))
            output.write("f " + " ".join(f"{corner}//{corner}" for corner in corners) + "\n")
    document, blobs = load_federated_scene(level_source)
    blobs.update(document.rig_graph.merge_deformation_binding(binding))
    skin_id = f"native_fbx::{binding['skeletons'][0]['native_id']}::{skin['native_id']}"
    runtime = dict(document.metadata.get("runtime_world") or {})
    rendering = dict(runtime.get("rendering") or {})
    rendering["lighting_model"] = "unlit"
    runtime["rendering"] = rendering
    entities = list(runtime.get("entities") or [])
    entities.append({
        "name": "DccCharacterProbe",
        "transform": {"position": [2.4, 0.0, 0.0], "scale": [0.0002, 0.0002, 0.0002]},
        "render": {"mesh": str(obj), "skin_binding": skin_id,
                   "base_color": [0.95, 0.45, 0.1], "roughness": 0.55},
    })
    runtime["entities"] = entities
    document.metadata["runtime_world"] = runtime
    scene = run / "dcc-playback" / "dcc-playback.tcscene"
    save_federated_scene(scene, document, blobs=blobs)
    package = run / "dcc-playback" / "package"
    built = build_windows_player(scene, package, player_executable=player)
    graphical = validate_windowed_player(package, frames=30, scripted_input=True)
    summary = summarize_player_profile(package / graphical["profile"])
    gpu_draws = min(int(row.get("gpu_skinned_draws", 0)) for row in summary["frame_profiles"])
    cpu_draws = min(int(row.get("cpu_skinned_draws", 0)) for row in summary["frame_profiles"])
    screenshot = package / graphical["screenshot"]
    with screenshot.open("rb") as stream:
        header = stream.read(54)
        width, height = struct.unpack_from("<ii", header, 18)
        offset = struct.unpack_from("<I", header, 10)[0]
        stride = (width * 3 + 3) & ~3
        amber_pixels = 0
        for y in range(round(height * 0.43), round(height * 0.76)):
            stream.seek(offset + (height - 1 - y) * stride + round(width * 0.56) * 3)
            row = stream.read((round(width * 0.72) - round(width * 0.56)) * 3)
            amber_pixels += sum(
                row[index + 2] > 200 and row[index + 1] > 170 and row[index] < 140
                for index in range(0, len(row), 3)
            )
    passed = gpu_draws + cpu_draws >= 2 and amber_pixels > 500 and built.validation.get("assets", {}).get("status") == "passed"
    return {"status": "passed" if passed else "blocked", "cpu_skinned_draws_min": cpu_draws,
            "gpu_skinned_draws_min": gpu_draws,
            "bones": len(binding["skeletons"][0]["joints"]), "vertices": vertex_count,
            "triangle_count": triangle_count, "skin_binding": skin_id, "amber_character_pixels": amber_pixels,
            "asset_integrity": built.validation.get("assets", {}).get("status"),
            "screenshot": str(screenshot), "package": str(package)}


def check_dcc_narrow_control_card(package: Path, wide_screenshot: Path,
                                  manifest_rows: list[str], ui_offset: tuple[int, int]) -> dict[str, Any]:
    """Exercise the real imported-character card at a narrow PC viewport."""
    width, height = 640, 480
    screenshot = package / "Content" / "dcc-motion-narrow.bmp"
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-motion-demo",
         "--frames", "150", "--window-width", str(width), "--window-height", str(height),
         "--borderless", "--screenshot", str(screenshot), "--screenshot-frame", "150"],
        cwd=package, capture_output=True, text=True, timeout=120, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    panel = next((row.split("\t") for row in manifest_rows
                  if row.startswith("UIWIDGET\tcontrols_panel\t")), None)
    safe = next((row.split("\t") for row in manifest_rows
                 if row.startswith("UISAFEAREA\t")), None)
    panel_fits = False
    if panel is not None and len(panel) >= 7 and safe is not None and len(safe) >= 5:
        x, y, panel_width, panel_height = (float(value) for value in panel[3:7])
        safe_left, safe_top, safe_right, safe_bottom = (float(value) for value in safe[1:5])
        panel_fits = (x >= safe_left and y >= safe_top and
                      x + panel_width <= width - safe_right and
                      y + panel_height <= height - safe_bottom)
    captured_size = None
    if screenshot.is_file():
        header = screenshot.read_bytes()[:54]
        if len(header) == 54 and header[:2] == b"BM":
            captured_size = struct.unpack_from("<ii", header, 18)
    try:
        text_result = verify_control_card([wide_screenshot, screenshot], offset=ui_offset)
    except (OSError, ValueError) as exc:
        text_result = {"status": "blocked", "error": str(exc)}
    checks = {
        "render_completed": completed.returncode == 0,
        "exact_640x480_capture": captured_size == (width, height),
        "panel_inside_safe_area": bool(panel_fits),
        "text_visible_and_stable": text_result["status"] == "passed",
    }
    return {"status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "screenshot": str(screenshot),
            "control_card": text_result, "stderr": completed.stderr[-1000:]}


def check_dcc_motion_phase_visibility(package: Path, reference_card: Path,
                                      ui_offset: tuple[int, int]) -> dict[str, Any]:
    """Capture each major motion phase and require an in-frame character and HUD."""
    phases = ((20, "tc_run"), (60, "tc_crouch_move"), (150, "tc_crawl_walk"),
              (270, "tc_jump_air"), (335, "tc_idle"), (420, "tc_walk_back"))
    results = []
    for frame, expected_clip in phases:
        screenshot = package / "Content" / f"dcc-phase-{frame}.bmp"
        profile = package / "Content" / f"dcc-phase-{frame}.jsonl"
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-motion-demo",
             "--frames", str(frame), "--window-width", "1280", "--window-height", "720",
             "--borderless", "--screenshot", str(screenshot), "--screenshot-frame", str(frame),
             "--log", str(profile)],
            cwd=package, capture_output=True, text=True, timeout=120, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not screenshot.is_file() or not profile.is_file():
            results.append({"frame": frame, "expected_clip": expected_clip, "status": "blocked",
                            "reason": (completed.stderr or completed.stdout)[-1000:]})
            continue
        frames = [json.loads(line) for line in profile.read_text(encoding="utf-8").splitlines()
                  if line.startswith("{")]
        observed = next((row.get("active_animation") for row in reversed(frames)
                         if row.get("type") == "frame"), None)
        actor = blue_character_bounds(screenshot, (400, 200, 800, 650))
        bounds = actor["bounds"]
        card = verify_control_card([reference_card, screenshot], offset=ui_offset)
        checks = {
            "expected_animation": observed == expected_clip,
            "character_visible": actor["pixels"] >= 2500 and bool(bounds) and
                bounds[0] > 420 and bounds[1] > 220 and bounds[2] < 780 and bounds[3] < 630,
            "controls_stable": card["status"] == "passed",
        }
        results.append({"frame": frame, "expected_clip": expected_clip,
                        "observed_clip": observed, "status": "passed" if all(checks.values()) else "blocked",
                        "checks": checks, "actor": actor, "screenshot": str(screenshot)})
    return {"status": "passed" if len(results) == len(phases) and all(
                result["status"] == "passed" for result in results) else "blocked",
            "phases": results}


def verify_motion_source_receipt(report_path: Path) -> dict[str, Any]:
    """Fail closed if a packaged demo is paired with stale or unreceipted FBXs."""
    library = load_motion_library(report_path)
    if set(library["clips"]) != set(RUNTIME_CLIPS):
        raise ValueError("DCC acceptance requires the complete thirteen-clip motion library")
    if any(len(str(clip.get("sha256") or "")) != 64 for clip in library["clips"].values()):
        raise ValueError("DCC acceptance requires a SHA-256 receipt for every motion clip")
    return library


def qualify_dcc_motion_player(
    package_source: str | Path, motion_report: str | Path, run: Path, player_executable: Path,
    source_fbx: str | Path | None = None,
    visual_baseline: str | Path | None = None,
    previous_package: str | Path | None = None,
) -> dict[str, Any]:
    """Run the packaged SKM_Test Player, not just a side-by-side rig probe."""
    source = Path(package_source).expanduser().resolve()
    library = Path(motion_report).expanduser().resolve()
    if not (source / "TCPlayer.exe").is_file() or not (source / "Content" / "main.tcruntime").is_file():
        raise FileNotFoundError("A built SKM_Test Windows player package is required.")
    if not library.is_file():
        raise FileNotFoundError(f"SKM_Test motion report is missing: {library}")
    # A prebuilt package is not evidence that the supplied DCC motion sources
    # still match the report; recheck every clip digest at acceptance time.
    library_record = verify_motion_source_receipt(library)
    source_matches = source_fbx is None or (
        str(library_record.get("target_sha256") or "") ==
        _hash(Path(source_fbx).expanduser().resolve())
    )
    package = run / "dcc-motion-player"
    shutil.copytree(source, package)
    shutil.copy2(player_executable, package / "TCPlayer.exe")
    manifest = package / "Content" / "main.tcruntime"
    # Qualify a non-default controller layout without mutating the supplied demo package.
    rebound_rows = (
        "GAMEPADBIND\tjump\tNORTH", "GAMEPADBIND\tcrouch\tLEFT_SHOULDER",
        "GAMEPADBIND\tcrawl\tRIGHT_SHOULDER", "GAMEPADBIND\tui_confirm\tWEST",
    )
    with manifest.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(rebound_rows) + "\n")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    scene_bound_save = sum(line.startswith("SCENEID\t") for line in lines) == 1
    dcc_player = any(line.startswith("RENDER\tPlayer\t") and "native_fbx::" in line
                     for line in lines)
    motion_database = any(line.startswith("MOTIONFRAME\t") for line in lines)
    control_card_present = any(line.startswith("UICANVAS\t") for line in lines)
    profile = package / "Content" / "dcc-motion-profile.jsonl"
    screenshot = package / "Content" / "dcc-motion-crawl.bmp"
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(manifest),
         "--renderer", "d3d11", "--require-renderer", "--scripted-motion-demo",
         "--frames", "460", "--log", str(profile), "--screenshot", str(screenshot),
         "--screenshot-frame", "150"],
        cwd=package, capture_output=True, text=True, timeout=120, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not profile.is_file() or not screenshot.is_file():
        raise RuntimeError("The packaged DCC Player did not complete: " +
                           (completed.stderr or completed.stdout)[-1500:])
    motion = verify_skm_motion_demo(profile, library, require_reverse_motion=True)
    gamepad_profile = package / "Content" / "dcc-gamepad-profile.jsonl"
    gamepad_screenshot = package / "Content" / "dcc-gamepad-crawl.bmp"
    gamepad_run = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(manifest),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-demo",
         "--frames", "380", "--log", str(gamepad_profile),
         "--screenshot", str(gamepad_screenshot), "--screenshot-frame", "150"],
        cwd=package, capture_output=True, text=True, timeout=120, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    gamepad_verified = gamepad_run.returncode == 0 and gamepad_profile.is_file() and gamepad_screenshot.is_file() and (
        "TC_GAMEPAD_INPUT source=simulated index=0" in gamepad_run.stdout
    )
    gamepad_motion = verify_skm_motion_demo(gamepad_profile, library) if gamepad_verified else {
        "status": "blocked", "error": (gamepad_run.stderr or gamepad_run.stdout)[-1500:],
    }
    safe_area_row = next((line.split("\t") for line in lines if line.startswith("UISAFEAREA\t")), None)
    ui_offset = (int(float(safe_area_row[1])), int(float(safe_area_row[2]))) if safe_area_row else (0, 0)
    control_card = verify_control_card([screenshot, gamepad_screenshot], offset=ui_offset) if control_card_present and gamepad_verified else {
        "status": "blocked", "reason": "missing_control_card_or_gamepad_capture",
    }
    narrow_control_card = check_dcc_narrow_control_card(package, screenshot, lines, ui_offset)
    phase_visibility = check_dcc_motion_phase_visibility(package, screenshot, ui_offset)
    baseline = (Path(visual_baseline).expanduser().resolve() if visual_baseline is not None
                else source / "Content" / "full-skin-crawl.bmp")
    # In-place crawl has phase-dependent limbs and shadows; allow their local
    # variation while catching large scene, camera, or material regressions.
    visual = compare_bmp_baseline(
        baseline, screenshot, max_changed_fraction=0.003,
        dynamic_rect=(300, 330, 850, 681),
    ) if baseline.is_file() else {
        "passed": False, "reason": "baseline_missing",
    }
    dcc_save = check_dcc_save_roundtrip(package)
    dcc_legacy_migration = check_dcc_legacy_unbound_migration(package)
    dcc_upgrade = check_dcc_content_upgrade(package, Path(dcc_save["save_dir"]))
    binary_upgrade = check_dcc_binary_upgrade(
        Path(previous_package).expanduser().resolve() if previous_package is not None else source,
        package, run)
    dcc_user_save = check_dcc_user_scoped_save(package, dcc_upgrade)
    dcc_default_legacy_save = check_dcc_default_legacy_save_migration(package, dcc_upgrade)
    passed = (dcc_player and motion_database and source_matches and scene_bound_save and
              motion["status"] == "passed" and gamepad_motion["status"] == "passed" and
              control_card["status"] == "passed" and narrow_control_card["status"] == "passed" and
              phase_visibility["status"] == "passed" and
              visual["passed"] and
              dcc_save["status"] == "passed" and dcc_legacy_migration["status"] == "passed" and
              dcc_upgrade["status"] == "passed" and
              binary_upgrade_satisfied(binary_upgrade, required=previous_package is not None) and
              dcc_user_save["status"] == "passed" and
              dcc_default_legacy_save["status"] == "passed")
    return {
        "status": "passed" if passed else "blocked",
        "dcc_player": dcc_player, "native_motion_database": motion_database,
        "source_fbx_matches": source_matches,
        "scene_bound_save": scene_bound_save,
        "motion": motion, "simulated_xbox_motion": gamepad_motion,
        "rebound_gamepad_buttons": list(rebound_rows),
        "control_card": control_card,
        "narrow_control_card": narrow_control_card,
        "motion_phase_visibility": phase_visibility,
        "visual_regression": visual, "package": str(package),
        "windowed_save_reload": dcc_save,
        "legacy_unbound_save_migration": dcc_legacy_migration,
        "compatible_content_upgrade": dcc_upgrade,
        "different_binary_save_upgrade": binary_upgrade,
        "user_scoped_save_across_install": dcc_user_save,
        "default_legacy_save_migration": dcc_default_legacy_save,
        "screenshot": str(screenshot), "profile": str(profile),
    }


def check_dcc_save_roundtrip(package: Path) -> dict[str, Any]:
    """Prove the imported character's save survives a packaged process exit."""
    package = package.resolve()
    scene = package / "Content" / "main.tcruntime"
    save_dir = package / "dcc-save-acceptance"
    save_profile = package / "Content" / "dcc-save-profile.jsonl"
    load_profile = package / "Content" / "dcc-reload-profile.jsonl"
    common = [str(package / "TCPlayer.exe"), "--scene", str(scene),
              "--renderer", "d3d11", "--require-renderer",
              "--save-dir", str(save_dir), "--input-profile", str(package / "dcc-input-profile.json"),
              "--audio-profile", str(package / "dcc-audio-profile.json")]
    saved = subprocess.run(
        common + ["--scripted-save-load", "--frames", "20", "--log", str(save_profile)],
        cwd=package, capture_output=True, text=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    reloaded = subprocess.run(
        common + ["--scripted-load-only", "--frames", "12", "--log", str(load_profile)],
        cwd=package, capture_output=True, text=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) if saved.returncode == 0 else None
    def frame_positions(path: Path) -> list[float]:
        if not path.is_file():
            return []
        return [float(row["player_x"]) for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("{") for row in [json.loads(line)]
                if row.get("type") == "frame" and "player_x" in row]
    saved_positions = frame_positions(save_profile)
    loaded_positions = frame_positions(load_profile)
    save_files = list(save_dir.glob("*.tcsave")) if save_dir.is_dir() else []
    recovery_dir = package / "dcc-save-recovery-acceptance"
    recovery_profile = package / "Content" / "dcc-recovery-profile.jsonl"
    recovered = None
    recovered_positions: list[float] = []
    if len(save_files) == 1 and reloaded is not None and reloaded.returncode == 0:
        recovery_dir.mkdir(exist_ok=True)
        recovery_save = recovery_dir / save_files[0].name
        # Keep the real acceptance save intact. Simulate a torn primary write
        # in a separate slot and require the packaged player to load .bak.
        shutil.copyfile(save_files[0], Path(str(recovery_save) + ".bak"))
        recovery_save.write_bytes(b"TCSAVE\t3\ntruncated primary")
        recovery_args = common.copy()
        recovery_args[recovery_args.index("--save-dir") + 1] = str(recovery_dir)
        recovered = subprocess.run(
            recovery_args + ["--scripted-load-only", "--frames", "12", "--log", str(recovery_profile)],
            cwd=package, capture_output=True, text=True, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        recovered_positions = frame_positions(recovery_profile)
    checks = {
        "windowed_save_and_load": saved.returncode == 0 and
            "TC_SAVE_WRITTEN source=hotkey" in saved.stdout and
            "TC_SAVE_LOADED source=hotkey" in saved.stdout and len(save_files) == 1,
        "cross_process_load": reloaded is not None and reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in reloaded.stdout,
        "moved_position_restored": len(saved_positions) >= 6 and len(loaded_positions) >= 4 and
            saved_positions[4] > 0.2 and loaded_positions[0] < 0.1 and
            abs(loaded_positions[3] - saved_positions[4]) < 0.15,
        "corrupt_primary_recovers_backup": recovered is not None and recovered.returncode == 0 and
            "TC_SAVE_RECOVERED source=hotkey" in recovered.stdout and
            "TC_SAVE_LOADED source=hotkey" in recovered.stdout and
            len(recovered_positions) >= 4 and len(saved_positions) >= 6 and
            abs(recovered_positions[3] - saved_positions[4]) < 0.15,
    }
    return {"status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "saved_x": saved_positions[4] if len(saved_positions) >= 6 else None,
            "reloaded_x": loaded_positions[3] if len(loaded_positions) >= 4 else None,
            "save_profile": str(save_profile), "reload_profile": str(load_profile),
            "recovery_profile": str(recovery_profile),
            "save_dir": str(save_dir), "save_stdout": saved.stdout[-500:],
            "reload_stdout": reloaded.stdout[-500:] if reloaded else "",
            "recovery_stdout": recovered.stdout[-500:] if recovered else "",
            "save_stderr": saved.stderr[-500:],
            "reload_stderr": reloaded.stderr[-500:] if reloaded else ""}


def check_dcc_legacy_unbound_migration(package: Path) -> dict[str, Any]:
    """Migrate a real pre-scene-ID character save while preserving its bytes."""
    package = package.resolve()
    scene = package / "Content" / "main.tcruntime"
    rows = scene.read_text(encoding="utf-8").splitlines()
    scene_ids = [row for row in rows if row.startswith("SCENEID\t")]
    if len(scene_ids) != 1:
        return {"status": "blocked", "reason": "scene_identity_missing_or_ambiguous"}
    legacy_scene = package / "Content" / "legacy-unbound.tcruntime"
    legacy_scene.write_text("\n".join(row for row in rows if not row.startswith("SCENEID\t")) + "\n",
                            encoding="utf-8")
    # Keep the slot outside the copied package; source-package test artifacts
    # must never become input to a later acceptance run.
    save_dir = package.parent / "dcc-legacy-migration-acceptance"
    def run(scene_path: Path, action: str, slot: Path = save_dir) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(scene_path),
             "--renderer", "d3d11", "--require-renderer", "--save-dir", str(slot),
             "--input-profile", str(package / "dcc-legacy-input-profile.json"),
             "--audio-profile", str(package / "dcc-legacy-audio-profile.json"),
             action, "--frames", "20" if action == "--scripted-save-load" else "8"],
            cwd=package, capture_output=True, text=True, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    created = run(legacy_scene, "--scripted-save-load")
    saves = list(save_dir.glob("*.tcsave")) if save_dir.is_dir() else []
    old_save = saves[0].read_bytes() if len(saves) == 1 else b""
    migrated = run(scene, "--scripted-load-then-save") if old_save else None
    new_save = saves[0].read_bytes() if old_save else b""
    backup = Path(str(saves[0]) + ".bak") if old_save else None
    reloaded = run(scene, "--scripted-load-only") if migrated and migrated.returncode == 0 else None
    def player_x(data: bytes) -> float | None:
        for row in data.decode("utf-8", errors="replace").splitlines():
            if row.startswith("BODY\tPlayer\t"):
                try:
                    return float(row.split("\t")[2])
                except (IndexError, ValueError):
                    return None
        return None
    old_x, new_x = player_x(old_save), player_x(new_save)
    retired_scene = package / "Content" / "legacy-retired-actor.tcruntime"
    retired_scene.write_text(legacy_scene.read_text(encoding="utf-8") +
                             "ENTITY\tRetiredActor\n"
                             "TRANSFORM\tRetiredActor\t0\t0\t0\t0\t0\t0\t1\t1\t1\n",
                             encoding="utf-8")
    retired_dir = package.parent / "dcc-legacy-retired-actor-acceptance"
    retired_created = run(retired_scene, "--scripted-save-load", retired_dir)
    retired_saves = list(retired_dir.glob("*.tcsave")) if retired_dir.is_dir() else []
    retired_original = retired_saves[0].read_bytes() if len(retired_saves) == 1 else b""
    retired_load = run(scene, "--scripted-load-only", retired_dir) if retired_original else None
    retired_overwrite = run(scene, "--scripted-save-load", retired_dir) if retired_original else None
    retired_unchanged = len(retired_saves) == 1 and retired_saves[0].read_bytes() == retired_original
    retired_backup = Path(str(retired_saves[0]) + ".bak") if retired_original else None
    checks = {
        "legacy_save_is_unbound": created.returncode == 0 and len(saves) == 1 and
            b"\nSCENE\t" not in old_save and b"TCSAVE\t3\n" in old_save and
            "TC_SAVE_WRITTEN source=hotkey" in created.stdout,
        "bound_scene_loads_and_resaves": migrated is not None and migrated.returncode == 0 and
            migrated.stdout.find("TC_SAVE_LOADED source=hotkey") >= 0 and
            migrated.stdout.find("TC_SAVE_WRITTEN source=hotkey") >
            migrated.stdout.find("TC_SAVE_LOADED source=hotkey"),
        "character_progress_preserved": old_x is not None and new_x is not None and
            old_x > 0.2 and abs(new_x - old_x) < 0.25,
        "new_save_has_scene_identity": ("\nSCENE\t" + scene_ids[0].split("\t", 1)[1] + "\n").encode() in new_save,
        "original_save_backed_up": backup is not None and backup.is_file() and
            backup.read_bytes() == old_save,
        "migrated_save_reloads": reloaded is not None and reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in reloaded.stdout,
        "removed_legacy_actor_rejected_without_overwrite": retired_created.returncode == 0 and
            b"BODY\tRetiredActor\t" in retired_original and b"\nSCENE\t" not in retired_original and
            retired_load is not None and retired_load.returncode == 0 and
            "TC_LOAD_FAILED source=hotkey reason=TC save game references missing scene entities or joints" in
            retired_load.stderr and
            retired_overwrite is not None and retired_overwrite.returncode == 0 and
            "TC_SAVE_FAILED source=hotkey reason=Existing save game references missing scene entities or joints" in
            retired_overwrite.stderr and retired_unchanged and
            retired_backup is not None and not retired_backup.exists(),
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "legacy_scene": str(legacy_scene), "save_dir": str(save_dir),
            "retired_scene": str(retired_scene), "retired_save_dir": str(retired_dir),
            "old_x": old_x, "new_x": new_x,
            "created_stderr": created.stderr[-500:],
            "migrated_stderr": migrated.stderr[-500:] if migrated else "",
            "reloaded_stderr": reloaded.stderr[-500:] if reloaded else "",
            "retired_created_stderr": retired_created.stderr[-500:],
            "retired_load_stderr": retired_load.stderr[-500:] if retired_load else "",
            "retired_overwrite_stderr": retired_overwrite.stderr[-500:] if retired_overwrite else ""}


def check_dcc_content_upgrade(package: Path, save_dir: Path) -> dict[str, Any]:
    """Load the character's progress after a compatible authored content update."""
    scene = package / "Content" / "main.tcruntime"
    rows = scene.read_text(encoding="utf-8").splitlines()
    scene_ids = [row for row in rows if row.startswith("SCENEID\t")]
    titles = [index for index, row in enumerate(rows)
              if row.startswith("UIWIDGET\tcontrols_title\ttext\t")]
    saves = list(save_dir.glob("*.tcsave")) if save_dir.is_dir() else []
    if len(scene_ids) != 1 or len(titles) != 1 or len(saves) != 1:
        return {"status": "blocked", "reason": "scene_id_title_or_save_missing"}
    old_save = saves[0].read_bytes()
    upgraded = package.parent / "dcc-motion-player-v2"
    content = upgraded / "Content"
    content.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package / "Content" / "Assets", content / "Assets", dirs_exist_ok=True)
    for name in ("TCPlayer.exe", "tc_graph_runtime.dll"):
        shutil.copy2(package / name, upgraded / name)
    fields = rows[titles[0]].split("\t")
    fields[7] += " — Updated"
    rows[titles[0]] = "\t".join(fields)
    updated_scene = content / "main.tcruntime"
    updated_scene.write_text("\n".join(rows) + "\n", encoding="utf-8")
    def run(*arguments: str, scene_path: Path = updated_scene) -> subprocess.CompletedProcess[str]:
        command = [str(upgraded / "TCPlayer.exe"), "--scene", str(scene_path),
                   "--renderer", "d3d11", "--require-renderer", "--save-dir", str(save_dir)]
        return subprocess.run(command + list(arguments), cwd=upgraded, capture_output=True,
                              text=True, timeout=20, check=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    migrated = run("--scripted-load-then-save", "--frames", "8")
    new_save = saves[0].read_bytes()
    backup = Path(str(saves[0]) + ".bak")
    reloaded = run("--scripted-load-only", "--frames", "8")
    uppercase_scene = content / "uppercase-scene-id.tcruntime"
    uppercase_scene.write_text("\n".join(
        "SCENEID\t" + row.split("\t", 1)[1].upper() if row.startswith("SCENEID\t") else row
        for row in rows) + "\n", encoding="utf-8")
    uppercase_reloaded = run("--scripted-load-only", "--frames", "8",
                             scene_path=uppercase_scene)
    foreign_key = "0" * 24 if scene_ids[0] != "SCENEID\t" + "0" * 24 else "1" * 24
    foreign_scene = content / "foreign-scene.tcruntime"
    foreign_scene.write_text("\n".join(
        "SCENEID\t" + foreign_key if row.startswith("SCENEID\t") else row
        for row in rows) + "\n", encoding="utf-8")
    save_before_foreign = saves[0].read_bytes()
    backup_before_foreign = backup.read_bytes() if backup.is_file() else b""
    foreign_load = run("--scripted-load-only", "--frames", "8", scene_path=foreign_scene)
    foreign_save = run("--scripted-save-load", "--frames", "12", scene_path=foreign_scene)
    def player_x(data: bytes) -> float | None:
        for row in data.decode("utf-8", errors="replace").splitlines():
            if row.startswith("BODY\tPlayer\t"):
                try:
                    return float(row.split("\t")[2])
                except (IndexError, ValueError):
                    return None
        return None
    old_x, new_x = player_x(old_save), player_x(new_save)
    checks = {
        "separate_install_with_stable_scene": upgraded.resolve() != package.resolve() and
            len([row for row in rows if row.startswith("SCENEID\t")]) == 1 and
            scene_ids[0] in rows and fields[7].endswith(" — Updated"),
        "upgraded_content_loaded_and_saved": migrated.returncode == 0 and
            migrated.stdout.find("TC_SAVE_LOADED source=hotkey") >= 0 and
            migrated.stdout.find("TC_SAVE_WRITTEN source=hotkey") >
            migrated.stdout.find("TC_SAVE_LOADED source=hotkey"),
        "character_progress_preserved": old_x is not None and new_x is not None and
            old_x > 0.2 and new_x > 0.2 and abs(new_x - old_x) < 0.25,
        "preupgrade_backup_preserved": backup.is_file() and backup.read_bytes() == old_save,
        "upgraded_save_reloads": reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in reloaded.stdout and
            "TC_LOAD_FAILED" not in reloaded.stderr,
        "scene_id_case_does_not_strand_save": uppercase_reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in uppercase_reloaded.stdout and
            "TC_LOAD_FAILED" not in uppercase_reloaded.stderr,
        "foreign_scene_cannot_load_or_overwrite": foreign_load.returncode == 0 and
            foreign_save.returncode == 0 and
            "TC_LOAD_FAILED source=hotkey reason=TC save game belongs to another scene" in
            foreign_load.stderr and
            "TC_SAVE_FAILED source=hotkey reason=Existing save game belongs to another scene" in
            foreign_save.stderr and
            saves[0].read_bytes() == save_before_foreign and
            (backup.read_bytes() if backup.is_file() else b"") == backup_before_foreign,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "old_x": old_x, "new_x": new_x, "updated_scene": str(updated_scene),
            "migrated_stdout": migrated.stdout[-500:], "migrated_stderr": migrated.stderr[-500:],
            "reloaded_stdout": reloaded.stdout[-500:], "reloaded_stderr": reloaded.stderr[-500:],
            "uppercase_scene": str(uppercase_scene),
            "uppercase_reloaded_stderr": uppercase_reloaded.stderr[-500:],
            "foreign_load_stderr": foreign_load.stderr[-500:],
            "foreign_save_stderr": foreign_save.stderr[-500:]}


def check_dcc_binary_upgrade(old_package: Path, new_package: Path, run: Path) -> dict[str, Any]:
    """Load and rotate a save made by the prior player binary using the new binary."""
    old_package, new_package, run = (
        (Path.cwd() / old_package).resolve(), (Path.cwd() / new_package).resolve(),
        (Path.cwd() / run).resolve())
    old_player = old_package / "TCPlayer.exe"
    new_player = new_package / "TCPlayer.exe"
    old_scene = old_package / "Content" / "main.tcruntime"
    new_scene = new_package / "Content" / "main.tcruntime"
    if not all(path.is_file() for path in (old_player, new_player, old_scene, new_scene)):
        return {"status": "blocked", "reason": "binary_or_scene_missing"}
    if _hash(old_player) == _hash(new_player):
        return {"status": "not_run", "reason": "player_binaries_identical"}
    def scene_identity(path: Path) -> tuple[list[str], list[str]]:
        rows = path.read_text(encoding="utf-8").splitlines()
        return ([row for row in rows if row.startswith("SCENEID\t")],
                [row for row in rows if row.startswith("SAVE\t")])
    old_identity, new_identity = scene_identity(old_scene), scene_identity(new_scene)
    if old_identity != new_identity or any(len(rows) != 1 for rows in old_identity):
        return {"status": "blocked", "reason": "scene_or_save_identity_mismatch"}
    save_dir = run / "dcc-binary-upgrade-saves"
    save_dir.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, "LOCALAPPDATA": str(run / "dcc-binary-upgrade-user")}
    def launch(player: Path, scene: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(player), "--scene", str(scene), "--renderer", "d3d11",
             "--require-renderer", "--save-dir", str(save_dir), *arguments],
            cwd=player.parent, env=environment, capture_output=True, text=True,
            timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    created = launch(old_player, old_scene, "--scripted-save-load", "--frames", "12")
    saves = list(save_dir.glob("*.tcsave"))
    old_bytes = saves[0].read_bytes() if len(saves) == 1 else b""
    loaded = launch(new_player, new_scene, "--scripted-load-only", "--frames", "8") if old_bytes else None
    unchanged = len(saves) == 1 and saves[0].read_bytes() == old_bytes
    rotated = launch(new_player, new_scene, "--scripted-load-then-save", "--frames", "10") if old_bytes else None
    backup = Path(str(saves[0]) + ".bak") if saves else None
    checks = {
        "different_player_binaries": _hash(old_player) != _hash(new_player),
        "stable_scene_and_slot": old_identity == new_identity,
        "old_binary_writes_save": created.returncode == 0 and bool(old_bytes) and
            "TC_SAVE_WRITTEN source=hotkey" in created.stdout,
        "new_binary_loads_without_mutation": loaded is not None and loaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in loaded.stdout and unchanged,
        "new_binary_rotates_old_save_to_backup": rotated is not None and
            rotated.returncode == 0 and "TC_SAVE_LOADED source=hotkey" in rotated.stdout and
            "TC_SAVE_WRITTEN source=hotkey" in rotated.stdout and
            backup is not None and backup.is_file() and backup.read_bytes() == old_bytes,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "old_player_sha256": _hash(old_player), "new_player_sha256": _hash(new_player),
            "old_save_sha256": hashlib.sha256(old_bytes).hexdigest() if old_bytes else "",
            "save": str(saves[0]) if saves else "", "created_stdout": created.stdout[-500:],
            "created_stderr": created.stderr[-500:],
            "created_returncode": created.returncode,
            "loaded_stdout": loaded.stdout[-500:] if loaded else "",
            "loaded_stderr": loaded.stderr[-500:] if loaded else "",
            "rotated_stdout": rotated.stdout[-500:] if rotated else "",
            "rotated_stderr": rotated.stderr[-500:] if rotated else ""}


def binary_upgrade_satisfied(receipt: dict[str, Any], *, required: bool) -> bool:
    """Never silently skip an explicitly requested prior-binary qualification."""
    status = receipt.get("status")
    return status == "passed" or (not required and status == "not_run")


def check_dcc_user_scoped_save(package: Path, upgrade: dict[str, Any]) -> dict[str, Any]:
    """Use the real Windows default save path across character install roots."""
    rows = (package / "Content" / "main.tcruntime").read_text(encoding="utf-8").splitlines()
    scene_ids = [row.split("\t", 1)[1] for row in rows if row.startswith("SCENEID\t")]
    slots = [row.split("\t", 1)[1] for row in rows if row.startswith("SAVE\t")]
    updated_scene = Path(str(upgrade.get("updated_scene") or ""))
    if len(scene_ids) != 1 or len(slots) != 1 or not updated_scene.is_file():
        return {"status": "blocked", "reason": "scene_id_slot_or_upgrade_missing"}
    local_data = package.parent / "dcc-localappdata"
    environment = {**os.environ, "LOCALAPPDATA": str(local_data)}
    save = local_data / "TechConnector" / "TCPlayer" / "saves" / scene_ids[0] / (slots[0] + ".tcsave")
    packaged_save = package / "Content" / (slots[0] + ".tcsave")
    def run(executable: Path, scene: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), "--scene", str(scene), "--renderer", "d3d11",
             "--require-renderer", *arguments], cwd=executable.parent, env=environment,
            capture_output=True, text=True, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    created = run(package / "TCPlayer.exe", package / "Content" / "main.tcruntime",
                  "--scripted-save-load", "--frames", "12")
    bytes_before = save.read_bytes() if save.is_file() else b""
    loaded = run(updated_scene.parent.parent / "TCPlayer.exe", updated_scene,
                 "--scripted-load-only", "--frames", "8")
    checks = {
        "save_in_user_scope_not_package": created.returncode == 0 and bool(bytes_before) and
            str(save) in created.stdout and not packaged_save.exists(),
        "updated_install_loads_user_save": loaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in loaded.stdout and str(save) in loaded.stdout and
            save.is_file() and save.read_bytes() == bytes_before,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "save": str(save), "created_stdout": created.stdout[-500:],
            "created_stderr": created.stderr[-500:], "loaded_stdout": loaded.stdout[-500:],
            "loaded_stderr": loaded.stderr[-500:]}


def check_dcc_default_legacy_save_migration(package: Path, upgrade: dict[str, Any]) -> dict[str, Any]:
    """Migrate a pre-scene-ID default Windows save into scene-ID user storage."""
    scene = package / "Content" / "main.tcruntime"
    rows = scene.read_text(encoding="utf-8").splitlines()
    scene_ids = [row.split("\t", 1)[1] for row in rows if row.startswith("SCENEID\t")]
    slots = [row.split("\t", 1)[1] for row in rows if row.startswith("SAVE\t")]
    updated_scene = Path(str(upgrade.get("updated_scene") or ""))
    if len(scene_ids) != 1 or len(slots) != 1 or not updated_scene.is_file():
        return {"status": "blocked", "reason": "scene_id_slot_or_upgrade_missing"}
    # The pre-binding default directory was hashed from the manifest path.
    # Rehearse an in-place content upgrade at that exact path, then restore
    # the scene before launching the bound build.
    legacy_scene = scene
    local_data = package.parent / "dcc-legacy-default-localappdata"
    environment = {**os.environ, "LOCALAPPDATA": str(local_data)}
    legacy_key = str(legacy_scene.resolve()).replace("\\", "/").lower().encode("utf-8")
    legacy_hash = 1469598103934665603
    for byte in legacy_key:
        legacy_hash = ((legacy_hash ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    root = local_data / "TechConnector" / "TCPlayer" / "saves"
    legacy_save = root / f"{legacy_hash:016x}" / (slots[0] + ".tcsave")
    migrated_save = root / scene_ids[0] / (slots[0] + ".tcsave")
    def run(executable: Path, manifest: Path, action: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), "--scene", str(manifest), "--renderer", "d3d11",
             "--require-renderer", action, "--frames", "20" if action == "--scripted-save-load" else "8"],
            cwd=executable.parent, env=environment, capture_output=True, text=True,
            timeout=20, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    bound_scene_bytes = scene.read_bytes()
    try:
        scene.write_text("\n".join(row for row in rows if not row.startswith("SCENEID\t")) + "\n",
                         encoding="utf-8")
        created = run(package / "TCPlayer.exe", legacy_scene, "--scripted-save-load")
    finally:
        scene.write_bytes(bound_scene_bytes)
    old_bytes = legacy_save.read_bytes() if legacy_save.is_file() else b""
    migrated = run(package / "TCPlayer.exe", scene, "--scripted-load-only") if old_bytes else None
    new_bytes = migrated_save.read_bytes() if migrated_save.is_file() else b""
    reloaded = run(updated_scene.parent.parent / "TCPlayer.exe", updated_scene,
                   "--scripted-load-only") if new_bytes else None
    checks = {
        "legacy_default_slot_created": created.returncode == 0 and bool(old_bytes) and
            b"\nSCENE\t" not in old_bytes and str(legacy_save) in created.stdout,
        "bound_scene_migrates_to_user_slot": migrated is not None and migrated.returncode == 0 and
            "TC_SAVE_MIGRATED from=" + str(legacy_save) in migrated.stdout and
            "TC_SAVE_LOADED source=hotkey" in migrated.stdout and bool(new_bytes) and
            ("\nSCENE\t" + scene_ids[0] + "\n").encode() in new_bytes,
        "original_legacy_slot_unchanged": legacy_save.is_file() and legacy_save.read_bytes() == old_bytes,
        "updated_install_loads_migrated_slot": reloaded is not None and reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in reloaded.stdout and
            str(migrated_save) in reloaded.stdout and migrated_save.read_bytes() == new_bytes,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "legacy_save": str(legacy_save), "migrated_save": str(migrated_save),
            "created_stderr": created.stderr[-500:],
            "migrated_stderr": migrated.stderr[-500:] if migrated else "",
            "reloaded_stderr": reloaded.stderr[-500:] if reloaded else ""}


def check_user_profiles_across_install(package: Path, upgrade: dict[str, Any]) -> dict[str, Any]:
    """Keep a scene's rebinding and mute preference across install paths."""
    rows = (package / "Content" / "main.tcruntime").read_text(encoding="utf-8").splitlines()
    scene_ids = [row.split("\t", 1)[1] for row in rows if row.startswith("SCENEID\t")]
    updated_scene = Path(str(upgrade.get("updated_scene") or upgrade.get("install_v2_scene") or ""))
    if len(scene_ids) != 1 or not updated_scene.is_file():
        return {"status": "blocked", "reason": "scene_id_or_upgrade_missing"}
    local_data = package.parent / "profile-upgrade-localappdata"
    environment = {**os.environ, "LOCALAPPDATA": str(local_data)}
    profiles = local_data / "TechConnector" / "TCPlayer" / "profiles"
    input_profile = profiles / (scene_ids[0] + ".tcinput")
    audio_profile = profiles / (scene_ids[0] + ".tcaudio")
    def run(executable: Path, scene: Path, *arguments: str,
            env_override: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), "--scene", str(scene), "--renderer", "d3d11",
             "--require-renderer", *arguments], cwd=executable.parent,
            env=environment if env_override is None else env_override,
            capture_output=True, text=True, timeout=20, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    executable = package / "TCPlayer.exe"
    scene = package / "Content" / "main.tcruntime"
    rebound = run(executable, scene, "--scripted-rebind-ui", "--input-profile",
                  str(input_profile), "--frames", "20")
    muted = run(executable, scene, "--scripted-audio-mute-once", "--audio-profile",
                str(audio_profile), "--frames", "12")
    updated_executable = updated_scene.parent.parent / "TCPlayer.exe"
    restored = run(updated_executable, updated_scene, "--frames", "8")
    used = run(updated_executable, updated_scene, "--scripted-profile-check",
               "--input-profile", str(input_profile), "--frames", "12")
    migration_local_data = package.parent / "profile-migration-localappdata"
    migration_environment = {**os.environ, "LOCALAPPDATA": str(migration_local_data)}
    legacy_key = str(scene.resolve()).replace("\\", "/").lower().encode("utf-8")
    legacy_hash = 1469598103934665603
    for byte in legacy_key:
        legacy_hash = ((legacy_hash ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    migration_profiles = migration_local_data / "TechConnector" / "TCPlayer" / "profiles"
    legacy_input = migration_profiles / f"{legacy_hash:016x}.tcinput"
    legacy_audio = migration_profiles / f"{legacy_hash:016x}.tcaudio"
    migrated_input = migration_profiles / (scene_ids[0] + ".tcinput")
    migrated_audio = migration_profiles / (scene_ids[0] + ".tcaudio")
    old_rebound = run(executable, scene, "--scripted-rebind-ui", "--input-profile",
                      str(legacy_input), "--frames", "20", env_override=migration_environment)
    old_muted = run(executable, scene, "--scripted-audio-mute-once", "--audio-profile",
                    str(legacy_audio), "--frames", "12", env_override=migration_environment)
    legacy_input_bytes = legacy_input.read_bytes() if legacy_input.is_file() else b""
    legacy_audio_bytes = legacy_audio.read_bytes() if legacy_audio.is_file() else b""
    migrated = run(executable, scene, "--frames", "8", env_override=migration_environment)
    checks = {
        "input_profile_scene_scoped": rebound.returncode == 0 and input_profile.is_file() and
            "TC_GAMEPAD_PROFILE_SAVED" in rebound.stdout and
            "TC_GAMEPAD_REBOUND action=jump button=SOUTH" in rebound.stdout,
        "audio_profile_scene_scoped": muted.returncode == 0 and audio_profile.is_file() and
            "TC_AUDIO_PROFILE_SAVED muted=1" in muted.stdout,
        "updated_install_restores_both_defaults": restored.returncode == 0 and
            f"TC_GAMEPAD_PROFILE_LOADED path={input_profile}" in restored.stdout and
            "TC_AUDIO_PROFILE_LOADED muted=1" in restored.stdout and
            "TC_AUDIO_PROFILE_STATE muted=1" in restored.stdout,
        "updated_install_uses_rebinding": used.returncode == 0 and
            "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in used.stdout,
        "legacy_profiles_migrate_without_mutation": old_rebound.returncode == 0 and
            old_muted.returncode == 0 and migrated.returncode == 0 and
            "TC_GAMEPAD_PROFILE_MIGRATED from=" in migrated.stdout and
            "TC_AUDIO_PROFILE_MIGRATED from=" in migrated.stdout and
            "TC_AUDIO_PROFILE_LOADED muted=1" in migrated.stdout and
            bool(legacy_input_bytes) and bool(legacy_audio_bytes) and
            legacy_input.read_bytes() == legacy_input_bytes and
            legacy_audio.read_bytes() == legacy_audio_bytes and
            migrated_input.is_file() and migrated_audio.is_file() and
            migrated_input.read_bytes() == legacy_input_bytes and
            migrated_audio.read_bytes() == legacy_audio_bytes,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "input_profile": str(input_profile), "audio_profile": str(audio_profile),
            "rebound_stdout": rebound.stdout[-500:], "muted_stdout": muted.stdout[-500:],
            "restored_stdout": restored.stdout[-500:], "restored_stderr": restored.stderr[-500:],
            "used_stdout": used.stdout[-500:], "migration_stdout": migrated.stdout[-700:],
            "migration_stderr": migrated.stderr[-500:]}


def author_audio_cue(api: TCEditorAPI, level_asset_id: str, run: Path) -> dict[str, Any]:
    """Add overlapping mono and stereo PCM cues to the begin-play graph."""
    source = run / "audio-source" / "AcceptanceTone.wav"
    source.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        frames = 2646
        samples = bytearray()
        for index in range(frames):
            envelope = min(1.0, index / 220.0, (frames - index - 1) / 220.0)
            amplitude = int(2400 * max(0.0, envelope) * math.sin(2.0 * math.pi * 440.0 * index / 22050.0))
            samples.extend(struct.pack("<h", amplitude))
        output.writeframes(samples)
    imported = api.import_asset(source, folder="Assets/Audio", type_id="tc.audio_clip")
    audio = api.database.asset(imported.asset_id)
    stereo_source = run / "audio-source" / "AcceptanceStereo.wav"
    stereo_samples = bytearray()
    stereo_frames = 6615
    for index in range(stereo_frames):
        envelope = min(1.0, index / 220.0, (stereo_frames - index - 1) / 220.0)
        left = int(2000 * max(0.0, envelope) * math.sin(2.0 * math.pi * 330.0 * index / 22050.0))
        right = int(2000 * max(0.0, envelope) * math.sin(2.0 * math.pi * 550.0 * index / 22050.0))
        stereo_samples.extend(struct.pack("<hh", left, right))
    with wave.open(str(stereo_source), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(stereo_samples)
    stereo_imported = api.import_asset(stereo_source, folder="Assets/Audio", type_id="tc.audio_clip")
    stereo_audio = api.database.asset(stereo_imported.asset_id)
    level = api.database.asset(level_asset_id)
    if audio is None or stereo_audio is None or level is None:
        raise RuntimeError("Imported audio or Level is absent from the asset database.")
    document, blobs = load_federated_scene(level.source_path)
    runtime = dict(document.metadata.get("runtime_world") or {})
    runtime.setdefault("begin_play", []).append({
        "node_id": "acceptance_audio", "operation": "audio.play",
        "arguments": [str(audio.source_path)],
    })
    runtime["begin_play"].append({
        "node_id": "acceptance_stereo_audio", "operation": "audio.play",
        "arguments": [str(stereo_audio.source_path)],
    })
    document.metadata["runtime_world"] = runtime
    save_federated_scene(level.source_path, document, blobs=blobs)
    dependencies = list(api.database.dependency_edges(level_asset_id))
    dependencies.append((audio.asset_id, "begin_play_audio"))
    dependencies.append((stereo_audio.asset_id, "begin_play_audio"))
    api.database.register_asset(
        level.source_path, level.asset_type, asset_id=level.asset_id,
        metadata=level.metadata, dependencies=dependencies,
    )
    return {"asset_id": audio.asset_id, "asset_ids": [audio.asset_id, stereo_audio.asset_id],
            "source": str(audio.source_path), "sources": [str(audio.source_path), str(stereo_audio.source_path)],
            "sha256": _hash(audio.source_path), "stereo_sha256": _hash(stereo_audio.source_path),
            "expected_cues": 2,
            "non_silent_samples": sum(samples[index:index + 2] != b"\0\0" for index in range(0, len(samples), 2)) +
            sum(stereo_samples[index:index + 2] != b"\0\0" for index in range(0, len(stereo_samples), 2))}


def author_runtime_ui(api: TCEditorAPI, level_asset_id: str) -> dict[str, Any]:
    """Bind an authored UI Document to the packaged game's runtime scene."""
    players = [actor for actor in api.level_actors(level_asset_id) if actor.get("name") == "Player"]
    if len(players) != 1:
        raise RuntimeError("Third-person Level must have one Player actor for the UI image fixture.")
    texture_source = Path(str(dict(players[0].get("render") or {}).get("base_color_texture") or ""))
    texture = api.database.asset_for_path(texture_source)
    if texture is None or texture.asset_type != "tc.texture":
        raise RuntimeError(f"Player UI image texture is not registered: {texture_source}")
    values = {
        "canvas": {"size": [1280, 720]},
        "widgets": [
            {"id": "hud_panel", "type": "panel", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [20, 20], "size": [300, 112]},
            {"id": "objective", "type": "text", "parent_id": "hud_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [16, 12], "size": [150, 40], "text": "Explore"},
            {"id": "save_button", "type": "button", "parent_id": "hud_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [16, 56], "size": [190, 42], "text": "Save progress",
             "accessible_name": "Save progress", "on_activate": "save_game"},
            {"id": "load_button", "type": "button", "parent_id": "hud_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [174, 12], "size": [110, 40], "text": "Load",
             "accessible_name": "Load progress", "on_activate": "load_game"},
            {"id": "character_icon", "type": "image", "parent_id": "hud_panel", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [228, 56], "size": [56, 42],
             "image_asset_id": texture.asset_id, "accessible_name": "Character texture"},
            {"id": "right_status", "type": "panel", "parent_id": "", "anchor": [1, 0],
             "pivot": [1, 0], "offset": [-20, 20], "size": [150, 48],
             "accessible_name": "Status panel", "min_viewport_width": 520},
            {"id": "controls_panel", "type": "panel", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [12, 136], "size": [386, 90],
             "accessible_name": "Gameplay controls"},
            {"id": "rebind_jump", "type": "button", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [20, 144], "size": [180, 34],
             "text": "Rebind Jump", "accessible_name": "Rebind Jump button",
             "on_activate": "rebind_jump"},
            {"id": "rebind_crouch", "type": "button", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [210, 144], "size": [180, 34],
             "text": "Rebind Crouch", "accessible_name": "Rebind Crouch button",
             "on_activate": "rebind_crouch"},
            {"id": "rebind_crawl", "type": "button", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [20, 184], "size": [180, 34],
             "text": "Rebind Crawl", "accessible_name": "Rebind Crawl button",
             "on_activate": "rebind_crawl"},
            {"id": "audio_toggle", "type": "button", "parent_id": "", "anchor": [0, 0],
             "pivot": [0, 0], "offset": [210, 184], "size": [180, 34],
             "text": "Audio: On", "accessible_name": "Mute audio",
             "on_activate": "audio_toggle"},
        ],
    }
    created = api.create_ui_document("ExplorationHUD", values=values)
    layout = api.preview_ui_document(created.asset_id, viewport=(1280, 720))
    artifact = api.cook_ui_document(created.asset_id)
    level = api.database.asset(level_asset_id)
    if level is None:
        raise KeyError(level_asset_id)
    document, blobs = load_federated_scene(level.source_path)
    runtime = dict(document.metadata.get("runtime_world") or {})
    runtime["ui_document"] = api.ui_documents.properties(created.asset_id)
    runtime.setdefault("assets", []).append({
        "id": texture.asset_id, "type": "texture", "source": str(texture.source_path),
        "content_hash": _hash(texture.source_path),
    })
    runtime["input_bindings"] = {
        "move_right": "L", "move_left": "J", "move_forward": "I",
        "move_backward": "K", "jump": "SPACE",
    }
    runtime["gamepad_bindings"] = {
        "jump": "NORTH", "crouch": "LEFT_SHOULDER", "crawl": "RIGHT_SHOULDER",
        "ui_confirm": "WEST",
    }
    document.metadata["runtime_world"] = runtime
    save_federated_scene(level.source_path, document, blobs=blobs)
    dependencies = list(api.database.dependency_edges(level_asset_id))
    dependencies.append((created.asset_id, "runtime_ui"))
    api.database.register_asset(level.source_path, level.asset_type, asset_id=level.asset_id,
                                metadata=level.metadata, dependencies=dependencies)
    return {"asset_id": created.asset_id, "widgets": len(layout["widgets"]),
            "layout_cooked": artifact.path.is_file(), "button_id": "save_button",
            "rebound_move_right": "L", "rebound_ui_confirm": "WEST",
            "image_asset_id": texture.asset_id}


def author_synthetic_stress_fixture(api: TCEditorAPI, level_asset_id: str, count: int) -> dict[str, Any]:
    """Add render-only props to expose draw-call scale on one hardware path."""
    if count < 0 or count > 2000:
        raise ValueError("Synthetic stress actor count must be between 0 and 2000.")
    if count == 0:
        return {"actors": 0, "kind": "none"}
    level = api.database.asset(level_asset_id)
    if level is None:
        raise KeyError(level_asset_id)
    document, blobs = load_federated_scene(level.source_path)
    runtime = dict(document.metadata.get("runtime_world") or {})
    entities = list(runtime.get("entities") or ())
    for index in range(count):
        entities.append({
            "name": f"AcceptanceStressProp{index:04d}",
            "transform": {
                "position": [float((index % 32) - 16) * 1.8, 0.55, 7.0 + float(index // 32) * 2.0],
                "scale": [0.7, 0.7, 0.7],
            },
            "render": {"mesh": "builtin:cube", "base_color": [0.18, 0.45, 0.66]},
        })
    runtime["entities"] = entities
    document.metadata["runtime_world"] = runtime
    save_federated_scene(level.source_path, document, blobs=blobs)
    api.database.register_asset(
        level.source_path, level.asset_type, asset_id=level.asset_id,
        metadata=level.metadata, dependencies=api.database.dependency_edges(level.asset_id),
    )
    return {"actors": count, "kind": "render_only_cubes"}


def check_packaged_audio(profile_path: Path) -> dict[str, Any]:
    events = []
    for line in profile_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("type") == "audio_event":
            events.append(row)
    submitted = Counter(str(row.get("source") or "") for row in events if row.get("status") == "submitted")
    completed = Counter(str(row.get("source") or "") for row in events if row.get("status") == "completed")
    failed = [row for row in events if row.get("status") not in {"submitted", "completed"}]
    played = bool(submitted) and "" not in submitted and submitted == completed and not failed
    peak_active_voices = max((int(row.get("active_voices", 0)) for row in events), default=0)
    return {"submitted": bool(submitted), "played": played,
            "submitted_count": sum(submitted.values()), "completed_count": sum(completed.values()),
            "failed_events": len(failed), "peak_active_voices": peak_active_voices,
            "overlapping_distinct_cues": played and len(submitted) >= 2 and peak_active_voices >= 2,
            "events": events}


def check_unicode_packaged_audio(package: Path) -> dict[str, Any]:
    """Play a packaged PCM cue through a Unicode asset path on real D3D11/XAudio2."""
    package = package.resolve()
    content = package / "Content"
    manifest = content / "main.tcruntime"
    scene = content / "acceptance-unicode-audio.tcruntime"
    profile = content / "acceptance-unicode-audio-profile.jsonl"
    unicode_asset = content / "Assets" / "acceptance-音声.wav"
    if any(path.exists() for path in (scene, profile, unicode_asset)):
        raise FileExistsError("Unicode audio fixture names are already in use.")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    audio_rows = [(index, line.split("\t")) for index, line in enumerate(lines)
                  if line.startswith("ASSET\t") and len(line.split("\t")) >= 5
                  and line.split("\t")[2] == "audio"]
    if len(audio_rows) < 2:
        raise ValueError("Unicode audio rehearsal requires two packaged PCM cues.")
    begin_play_audio = [parts[6] for line in lines if line.startswith("GRAPH\tbegin\t")
                        if (parts := line.split("\t")) and len(parts) >= 7
                        and parts[3] == "audio.play"]
    selected = next(((index, fields) for index, fields in audio_rows
                     if begin_play_audio and fields[1] == begin_play_audio[0]), None)
    if selected is None:
        raise ValueError("Unicode audio rehearsal requires a packaged begin-play cue.")
    index, fields = selected
    original = content / fields[3]
    if not original.is_file() or _hash(original) != fields[4]:
        raise ValueError("Unicode audio rehearsal source is missing or has a bad receipt.")
    shutil.copy2(original, unicode_asset)
    fields[3] = "Assets/acceptance-音声.wav"
    lines[index] = "\t".join(fields)
    scene.write_text("\n".join(lines) + "\n", encoding="utf-8")
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--frames", "120",
         "--log", str(profile)],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    audio = check_packaged_audio(profile) if profile.is_file() else {"played": False, "events": []}
    submitted_sources = {str(event.get("source", "")) for event in audio["events"]
                         if event.get("status") == "submitted"}
    checks = {
        "asset_receipt_preserved": _hash(unicode_asset) == fields[4],
        "windowed_d3d11_completed": completed.returncode == 0,
        "unicode_source_submitted": any("acceptance-音声.wav" in source for source in submitted_sources),
        "both_cues_played": bool(audio["played"]) and
            audio.get("submitted_count", 0) >= 2 and audio.get("overlapping_distinct_cues", False),
    }
    restart_profile = content / "acceptance-unicode-audio-restart-profile.jsonl"
    if restart_profile.exists():
        raise FileExistsError("Unicode audio restart profile name is already in use.")
    restarted = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-restart",
         "--frames", "120", "--log", str(restart_profile)],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    restart_events = []
    if restart_profile.is_file():
        for line in restart_profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                try:
                    restart_events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    restart = assess_audio_restart_events(restart_events)
    replay_index = next((i for i, row in enumerate(restart_events)
                         if row.get("type") == "audio_restart" and row.get("phase") == "replay"), -1)
    checks["unicode_source_survives_output_restart"] = (
        restarted.returncode == 0 and restart["status"] == "passed" and replay_index >= 0 and
        any(row.get("type") == "audio_event" and row.get("status") == "completed" and
            "acceptance-音声.wav" in str(row.get("source", ""))
            for row in restart_events[replay_index + 1:]))
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "scene": str(scene), "scene_sha256": _hash(scene),
            "asset": str(unicode_asset), "asset_sha256": _hash(unicode_asset),
            "profile": str(profile), "audio": audio, "exit_code": completed.returncode,
            "restart_profile": str(restart_profile), "restart": restart,
            "restart_exit_code": restarted.returncode,
            "stdout": completed.stdout[-400:], "stderr": completed.stderr[-400:]}


def assess_audio_restart_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate ordering as well as success of an intentional output restart."""
    requested = next((index for index, row in enumerate(events)
                      if row.get("type") == "audio_restart" and row.get("phase") == "requested"), -1)
    replay = next((index for index, row in enumerate(events)
                   if row.get("type") == "audio_restart" and row.get("phase") == "replay"), -1)
    failed = [row for row in events[requested + 1:replay]
              if row.get("type") == "audio_event" and row.get("status") == "failed"] if 0 <= requested < replay else []
    completed = [row for row in events[replay + 1:]
                 if row.get("type") == "audio_event" and row.get("status") == "completed"] if replay >= 0 else []
    checks = {
        "active_voices_at_request": requested >= 0 and events[requested].get("succeeded") is True
            and int(events[requested].get("active_voices", 0)) >= 2
            and events[requested].get("muted") is True,
        "active_voices_failed_and_drained": len({row.get("source") for row in failed}) >= 2
            and all(row.get("error") == "XAudio2 output restart requested" and
                    int(row.get("active_voices", -1)) == 0 for row in failed),
        "reinitialized_and_replayed": replay > requested >= 0 and events[replay].get("succeeded") is True
            and int(events[replay].get("active_voices", 0)) == 1
            and events[replay].get("muted") == events[requested].get("muted"),
        "default_endpoint_monitor_registered": replay > requested >= 0 and
            events[requested].get("endpoint_monitoring") is True and
            events[replay].get("endpoint_monitoring") is True,
        "replay_completed": any(row.get("source") in {failed_row.get("source") for failed_row in failed}
                                for row in completed),
        "no_unexpected_audio_failures": replay >= 0 and not any(
            row.get("type") == "audio_event" and row.get("status") == "failed"
            for row in events[replay + 1:]),
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "restart_events": [row for row in events if row.get("type") in {"audio_event", "audio_restart"}]}


def check_packaged_audio_restart(package: Path) -> dict[str, Any]:
    """Exercise software-requested XAudio2 teardown/recreation in the D3D11 player."""
    package = package.resolve()
    content = package / "Content"
    profile = content / "audio-output-restart-profile.jsonl"
    profile.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-restart",
         "--frames", "120", "--log", str(profile)],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    events = []
    if profile.is_file():
        for line in profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    result = assess_audio_restart_events(events)
    result["status"] = "passed" if completed.returncode == 0 and result["status"] == "passed" else "blocked"
    result.update({"profile": str(profile), "exit_code": completed.returncode,
                   "stdout": completed.stdout[-400:], "stderr": completed.stderr[-400:]})
    return result


def check_windowed_scene_failure(package: Path) -> dict[str, Any]:
    """A finite graphical test must exit on bad input without a modal dialog."""
    package = package.resolve()
    content = package / "Content"
    missing = content / "acceptance-missing-manifest.tcruntime"
    invalid = content / "acceptance-invalid-manifest.tcruntime"
    duplicate = content / "acceptance-duplicate-scene-id.tcruntime"
    if missing.exists() or invalid.exists() or duplicate.exists():
        raise FileExistsError("Windowed negative-fixture names are already in use.")
    invalid.write_text("TCRUNTIME\t0\n", encoding="utf-8")
    duplicate.write_text("TCRUNTIME\t1\nSCENEID\t" + "0" * 24 +
                         "\nSCENEID\t" + "1" * 24 + "\n", encoding="utf-8")
    checks: dict[str, bool] = {}
    results: dict[str, Any] = {}
    for name, scene, diagnostic in (
        ("missing", missing, "Could not open runtime manifest"),
        ("invalid", invalid, "Unsupported or invalid TC runtime manifest"),
        ("duplicate_scene_id", duplicate, "Duplicate scene identity."),
    ):
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(scene),
             "--renderer", "d3d11", "--require-renderer", "--frames", "2"],
            cwd=package, capture_output=True, text=True, timeout=8, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        checks[name] = completed.returncode == 2 and diagnostic in completed.stderr
        results[name] = {"exit_code": completed.returncode,
                         "stderr": completed.stderr[-500:]}
    return {"status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "results": results}


def check_unicode_scene_default_paths(package: Path) -> dict[str, Any]:
    """Exercise the normal user profile/save path setup with a Unicode scene filename."""
    package = package.resolve()
    content = package / "Content"
    scene = content / "acceptance-保存.tcruntime"
    profile = content / "acceptance-unicode-default-profile.jsonl"
    screenshot = content / "acceptance-unicode-default.bmp"
    if any(path.exists() for path in (scene, profile, screenshot)):
        raise FileExistsError("Unicode default-path fixture names are already in use.")
    shutil.copy2(content / "main.tcruntime", scene)
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(package / "AcceptanceLocalAppData")
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--frames", "120",
         "--log", str(profile), "--screenshot", str(screenshot),
         "--screenshot-frame", "60"],
        cwd=package, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    summary = summarize_player_profile(profile)
    passed = (completed.returncode == 0 and
              len(summary["frame_profiles"]) == 120 and not summary["diagnostics"] and
              screenshot.is_file() and screenshot.read_bytes()[:2] == b"BM")
    return {"status": "passed" if passed else "blocked", "exit_code": completed.returncode,
            "frames": len(summary["frame_profiles"]), "scene": str(scene),
            "scene_sha256": _hash(scene), "screenshot": str(screenshot),
            "stdout": completed.stdout[-400:], "stderr": completed.stderr[-400:]}


def check_windowed_skin_failure(package: Path) -> dict[str, Any]:
    """A missing Player skin must fail the frame, never present a rest mesh."""
    package = package.resolve()
    content = package / "Content"
    source = content / "main.tcruntime"
    invalid = content / "acceptance-missing-skin.tcruntime"
    screenshot = content / "acceptance-missing-skin.bmp"
    if invalid.exists() or screenshot.exists():
        raise FileExistsError("Windowed skin negative-fixture names are already in use.")
    lines = source.read_text(encoding="utf-8").splitlines()
    player_rows = [index for index, line in enumerate(lines)
                   if line.startswith("RENDER\tPlayer\t")]
    if len(player_rows) != 1:
        raise ValueError("Skin failure rehearsal requires exactly one Player renderable.")
    row = lines[player_rows[0]].split("\t")
    if len(row) < 16 or not row[15]:
        raise ValueError("Skin failure rehearsal requires a skinned Player renderable.")
    row[15] = "__tc_acceptance_missing_skin__"
    lines[player_rows[0]] = "\t".join(row)
    invalid.write_text("\n".join(lines) + "\n", encoding="utf-8")
    modes: dict[str, dict[str, Any]] = {}
    for mode, extra in (("gpu", ()), ("cpu_fallback", ("--cpu-skinning-diagnostic",))):
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(invalid),
             "--renderer", "d3d11", "--require-renderer", "--frames", "4",
             "--screenshot", str(screenshot), "--screenshot-frame", "1", *extra],
            cwd=package, capture_output=True, text=True, timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        modes[mode] = {
            "passed": completed.returncode == 4 and not screenshot.exists() and
                "renderer frame failed: Could not render skin binding: __tc_acceptance_missing_skin__"
                in completed.stderr,
            "exit_code": completed.returncode, "screenshot_created": screenshot.exists(),
            "stderr": completed.stderr[-500:],
        }
        if screenshot.exists():
            break
    return {"status": "passed" if len(modes) == 2 and all(row["passed"] for row in modes.values())
            else "blocked", "modes": modes}


def _first_packaged_asset(manifest: Path, package: Path) -> Path:
    for line in manifest.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) >= 5 and fields[0] == "ASSET" and fields[3].startswith(("Assets/", "Content/Assets/")):
            candidate = (manifest.parent / fields[3]).resolve() if fields[3].startswith("Assets/") else (package / fields[3]).resolve()
            candidate.relative_to(package.resolve())
            if candidate.is_file():
                return candidate
    raise RuntimeError("Third-person package has no copied content asset to test recovery.")


def check_asset_recovery(manifest: Path, package: Path) -> dict[str, Any]:
    """Corrupt one generated package asset, demand rejection, then restore it."""
    target = _first_packaged_asset(manifest, package)
    original = target.read_bytes()
    detected = False
    try:
        target.write_bytes(b"TC_ACCEPTANCE_CORRUPTION")
        try:
            validate_packaged_assets(manifest, package)
        except (FileNotFoundError, RuntimeError):
            detected = True
    finally:
        target.write_bytes(original)
    restored = validate_packaged_assets(manifest, package)
    return {
        "corruption_detected": detected,
        "restored_integrity": restored.get("status") == "passed",
        "asset": str(target.relative_to(package.resolve())),
        "restored_sha256": _hash(target),
    }


def check_packaged_gameplay(package: Path, *, frames: int) -> dict[str, Any]:
    """Prove movement, clip transitions, and native save/load in a packaged player."""
    package = package.resolve()
    executable = package / "TCPlayer.exe"
    manifest = package / "Content" / "main.tcruntime"
    profile = package / "Content" / "gameplay-acceptance-profile.jsonl"
    save = package / "Content" / "gameplay-acceptance.tcsave"
    profile.unlink(missing_ok=True)
    save.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(executable), "--scene", str(manifest), "--headless", "--frames", str(frames),
         "--log", str(profile), "--verify-save-roundtrip", str(save)],
        cwd=package, capture_output=True, text=True,
        timeout=max(30.0, frames / 30.0 + 15.0), check=False,
    )
    if completed.returncode != 0 or "TC_PLAYER_OK" not in completed.stdout:
        diagnostic = "\n".join((completed.stdout, completed.stderr)).strip()
        raise RuntimeError(f"Packaged gameplay run failed (exit {completed.returncode}).\n{diagnostic[-2000:]}")
    summary = summarize_player_profile(profile)
    rows = summary["frame_profiles"]
    if len(rows) < frames or summary["diagnostics"]:
        raise RuntimeError("Packaged gameplay profile is incomplete or contains diagnostics.")
    positions = [float(row["player_x"]) for row in rows if "player_x" in row]
    clips = sorted({str(row.get("active_animation") or "") for row in rows if row.get("active_animation")})
    moved = len(positions) == len(rows) and max(positions) - min(positions) > 0.5
    transitioned = len(clips) >= 2 and "tc_idle" in clips and any(clip != "tc_idle" for clip in clips)
    saved = save.is_file() and save.read_bytes().startswith(b"TCSAVE\t3\n")
    roundtrip = saved and "TC_SAVE_ROUNDTRIP_OK" in completed.stdout
    migrated = (
        "TC_SAVE_LEGACY_MIGRATION_OK from=1 to=3" in completed.stdout
        and Path(str(save) + ".migrated-v3").is_file()
    )
    migrated_v2 = (
        "TC_SAVE_LEGACY_MIGRATION_OK from=2 to=3" in completed.stdout
        and Path(str(save) + ".v2-migrated-v3").is_file()
    )
    malformed_legacy_rejected = "TC_SAVE_LEGACY_MALFORMED_REJECTED cases=3" in completed.stdout
    malformed_legacy_recovered = "TC_SAVE_LEGACY_BACKUP_RECOVERED" in completed.stdout
    corruption_rejected = "TC_SAVE_CORRUPTION_REJECTED" in completed.stdout
    semantic_rejected = "TC_SAVE_SEMANTIC_REJECTED" in completed.stdout
    semantic_recovered = "TC_SAVE_SEMANTIC_RECOVERED" in completed.stdout
    partial_write_recovered = "TC_SAVE_PARTIAL_WRITE_RECOVERED" in completed.stdout
    pending_write_recovered = "TC_SAVE_PENDING_WRITE_RECOVERED" in completed.stdout
    backup_preserved = "TC_SAVE_BACKUP_PRESERVED" in completed.stdout
    return {
        "frames": len(rows), "player_moved": moved,
        "player_x_min": min(positions) if positions else None,
        "player_x_max": max(positions) if positions else None,
        "animation_transitioned": transitioned, "animation_clips_observed": clips,
        "save_roundtrip": roundtrip,
        "legacy_save_migrated": migrated,
        "legacy_v2_save_migrated": migrated_v2,
        "malformed_legacy_rejected": malformed_legacy_rejected,
        "malformed_legacy_recovered": malformed_legacy_recovered,
        "corrupt_save_rejected": corruption_rejected,
        "semantic_save_rejected": semantic_rejected,
        "semantic_save_recovered": semantic_recovered,
        "partial_write_recovered": partial_write_recovered,
        "pending_write_recovered": pending_write_recovered,
        "backup_preserved": backup_preserved,
        "save": str(save.relative_to(package)),
        "profile": str(profile.relative_to(package)),
    }


def packaged_save_path(package: Path) -> Path:
    """Resolve the authored save slot for either packaged third-person variant."""
    scene = package / "Content" / "main.tcruntime"
    slot = "third_person_exploration_autosave"
    if scene.is_file():
        slot = next((row.split("\t", 1)[1] for row in scene.read_text(encoding="utf-8").splitlines()
                     if row.startswith("SAVE\t")), slot)
    if Path(slot).name != slot or not slot:
        raise ValueError("Packaged save slot must be a nonempty filename stem.")
    return package / "Content" / f"{slot}.tcsave"


def check_keyboard_ui_navigation(package: Path) -> dict[str, Any]:
    """Exercise windowed keyboard focus, Save/Load activation, and Escape dismissal."""
    package = package.resolve()
    content = package / "Content"
    scene = content / "main.tcruntime"
    slot = next((row.split("\t", 1)[1] for row in scene.read_text(encoding="utf-8").splitlines()
                 if row.startswith("SAVE\t")), "autosave")
    save_dir = package.parent / "keyboard-ui-save-acceptance"
    screenshot = content / "keyboard-ui-focus.bmp"
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-keyboard-ui",
         "--save-dir", str(save_dir), "--frames", "10",
         "--screenshot", str(screenshot), "--screenshot-frame", "3"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    save = save_dir / f"{slot}.tcsave"
    checks = {
        "rendered": completed.returncode == 0 and screenshot.is_file(),
        "tab_focus_order": completed.stdout.find("TC_UI_FOCUS id=save_button") >= 0 and
            completed.stdout.find("TC_UI_FOCUS id=load_button") >
            completed.stdout.find("TC_UI_FOCUS id=save_button"),
        "enter_saved": completed.stdout.count("TC_UI_ACTIVATED id=save_button event=save_game") == 1 and
            "TC_SAVE_WRITTEN source=ui" in completed.stdout and save.is_file(),
        "enter_loaded": completed.stdout.count("TC_UI_ACTIVATED id=load_button event=load_game") == 1 and
            "TC_SAVE_LOADED source=ui" in completed.stdout,
        "escape_dismissed_focus": completed.stdout.count("TC_UI_ACTIVATED") == 2 and
            "TC_LOAD_FAILED" not in completed.stderr,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "screenshot": str(screenshot), "save": str(save),
            "stdout": completed.stdout[-900:], "stderr": completed.stderr[-600:]}


def check_focus_loss_rebind(package: Path) -> dict[str, Any]:
    """Ensure window focus loss cancels UI focus and a pending controller rebind."""
    package = package.resolve()
    content = package / "Content"
    profile = content / "focus-loss-rebind.tcinput"
    profile.unlink(missing_ok=True)
    screenshot = content / "focus-loss-rebind.bmp"
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-focus-loss-rebind",
         "--input-profile", str(profile), "--frames", "12",
         "--screenshot", str(screenshot), "--screenshot-frame", "4"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks = {
        "rendered": completed.returncode == 0 and screenshot.is_file(),
        "rebind_was_pending": "TC_UI_FOCUS id=rebind_jump" in completed.stdout and
            "TC_GAMEPAD_REBIND_PENDING action=jump" in completed.stdout,
        "focus_loss_cancelled": "TC_UI_FOCUS_LOST pending_rebind_cancelled=1" in completed.stdout,
        "delayed_button_ignored": completed.stdout.count("TC_UI_ACTIVATED") == 1 and
            "TC_GAMEPAD_REBOUND" not in completed.stdout and
            "TC_GAMEPAD_PROFILE_SAVED" not in completed.stdout and not profile.exists(),
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "screenshot": str(screenshot), "profile": str(profile),
            "stdout": completed.stdout[-900:], "stderr": completed.stderr[-600:]}


def check_gamepad_ui_navigation(package: Path) -> dict[str, Any]:
    """Exercise focus, highlighted selection, and activation through Xbox input mapping."""
    package = package.resolve()
    screenshot = package / "Content" / "gamepad-ui-focus.bmp"
    save = packaged_save_path(package)
    screenshot.unlink(missing_ok=True)
    save.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-ui",
         "--frames", "30", "--screenshot", str(screenshot), "--screenshot-frame", "2"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    visual = check_visual_landmarks(screenshot) if screenshot.is_file() else {"passed": False}
    button = visual.get("button_rgb") or (0, 0, 0)
    checks = {
        "completed": completed.returncode == 0,
        "button_focused": "TC_UI_FOCUS id=save_button" in completed.stdout,
        "button_activated": "TC_UI_ACTIVATED id=save_button event=save_game" in completed.stdout,
        "save_status": "TC_UI_STATUS text=Saved" in completed.stdout,
        "focus_visible": visual["passed"] and button[2] >= 190 and button[1] >= 135,
        "save_written": save.is_file(),
        "no_errors": "error:" not in (completed.stdout + completed.stderr).lower(),
    }
    load_screenshot = package / "Content" / "gamepad-load-ui-focus.bmp"
    load_profile = package / "Content" / "gamepad-load-ui-profile.jsonl"
    load_profile.unlink(missing_ok=True)
    try:
        loaded = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-load-ui",
             "--frames", "30", "--log", str(load_profile),
             "--screenshot", str(load_screenshot), "--screenshot-frame", "5"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        logged_frames = sum(line.startswith('{"type":"frame"') for line in
                            load_profile.read_text(encoding="utf-8").splitlines()) if load_profile.is_file() else 0
        return {"status": "blocked", "stage": "gamepad_load_ui", "error": str(exc),
                "load_profile": str(load_profile), "logged_frames": logged_frames,
                "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-500:] if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")[-500:],
                "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-500:] if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")[-500:]}
    load_visual = check_visual_landmarks(load_screenshot, button_x=0.20, button_y=0.075) if load_screenshot.is_file() else {"passed": False}
    load_button = load_visual.get("button_rgb") or (0, 0, 0)
    checks.update({
        "load_completed": loaded.returncode == 0,
        "load_button_focused": "TC_UI_FOCUS id=load_button" in loaded.stdout,
        "load_button_activated": "TC_UI_ACTIVATED id=load_button event=load_game" in loaded.stdout,
        "load_focus_visible": load_visual["passed"] and load_button[2] >= 190 and load_button[1] >= 135,
        "save_loaded": "TC_SAVE_LOADED source=ui" in loaded.stdout,
        "load_status": "TC_UI_STATUS text=Loaded" in loaded.stdout,
        "load_no_errors": "error:" not in (loaded.stdout + loaded.stderr).lower(),
    })
    failure_screenshot = package / "Content" / "gamepad-load-failed-ui.bmp"
    missing_save_dir = package / "Content" / "missing-save-ui-acceptance"
    failed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-load-ui",
         "--save-dir", str(missing_save_dir), "--frames", "30", "--screenshot", str(failure_screenshot),
         "--screenshot-frame", "5"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks.update({
        "missing_load_completed": failed.returncode == 0,
        "missing_load_reported": "TC_LOAD_FAILED source=ui" in failed.stderr,
        "missing_load_status": "TC_UI_STATUS text=Load failed" in failed.stdout,
        "missing_load_rendered": failure_screenshot.is_file(),
    })
    disconnect_profile = package / "Content" / "gamepad-disconnect-profile.jsonl"
    disconnect_profile.unlink(missing_ok=True)
    disconnected = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-disconnect-ui",
         "--frames", "28", "--log", str(disconnect_profile)],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    disconnect_frames = []
    if disconnect_profile.is_file():
        for line in disconnect_profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                if row.get("type") == "frame":
                    disconnect_frames.append(row)
    positions = [float(row["player_x"]) for row in disconnect_frames if "player_x" in row]
    forward_positions = [float(row["player_z"]) for row in disconnect_frames if "player_z" in row]
    checks.update({
        "disconnect_completed": disconnected.returncode == 0,
        "disconnect_ui_initially_focused": "TC_UI_FOCUS id=save_button" in disconnected.stdout,
        "disconnect_keyboard_fallback": "TC_GAMEPAD_INPUT_LOST keyboard_fallback=1" in disconnected.stdout,
        "disconnect_keyboard_binding_used": "TC_INPUT_BINDING_USED action=move_right" in disconnected.stdout,
        "disconnect_keyboard_moved": len(positions) == 28 and max(positions) - min(positions) > 0.1,
        "reconnect_neutral_guard": "TC_GAMEPAD_RECONNECTED neutral_guard=1" in disconnected.stdout,
        "reconnect_held_stick_ignored": len(forward_positions) == 28 and
            max(abs(value) for value in forward_positions[:20]) < 0.01,
        "reconnect_fresh_stick_works": len(forward_positions) == 28 and
            max(forward_positions[21:]) > 0.01,
        "reconnect_ui_refocused": disconnected.stdout.count("TC_UI_FOCUS id=save_button") >= 2,
    })
    rebind_profile = package / "Content" / "gamepad-disconnect-rebind-profile.jsonl"
    rebind_profile.unlink(missing_ok=True)
    rebind_screenshot = package / "Content" / "gamepad-disconnect-rebind.bmp"
    rebind_disconnected = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-disconnect-rebind",
         "--frames", "30", "--log", str(rebind_profile), "--screenshot", str(rebind_screenshot),
         "--screenshot-frame", "9"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rebind_frames = []
    if rebind_profile.is_file():
        for line in rebind_profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                if row.get("type") == "frame":
                    rebind_frames.append(row)
    rebind_positions = [float(row["player_x"]) for row in rebind_frames if "player_x" in row]
    checks.update({
        "rebind_disconnect_completed": rebind_disconnected.returncode == 0,
        "rebind_pending_before_loss": "TC_GAMEPAD_REBIND_PENDING action=jump" in rebind_disconnected.stdout,
        "rebind_cancelled_on_loss": "TC_GAMEPAD_INPUT_LOST keyboard_fallback=1" in rebind_disconnected.stdout
            and "TC_GAMEPAD_REBOUND action=jump" not in rebind_disconnected.stdout,
        "rebind_keyboard_moved": len(rebind_positions) == 30 and
            max(rebind_positions) - min(rebind_positions) > 0.1,
        "rebind_reconnect_ui_focused": rebind_disconnected.stdout.count("TC_UI_FOCUS id=save_button") >= 2,
        "rebind_label_rendered": rebind_screenshot.is_file(),
    })
    switch_profile = package / "Content" / "gamepad-owner-switch-profile.jsonl"
    switch_profile.unlink(missing_ok=True)
    switch_screenshot = package / "Content" / "gamepad-owner-switch.bmp"
    switched = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-switch-ui",
         "--frames", "20", "--log", str(switch_profile), "--screenshot", str(switch_screenshot),
         "--screenshot-frame", "18"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    switch_frames = []
    if switch_profile.is_file():
        for line in switch_profile.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                if row.get("type") == "frame":
                    switch_frames.append(row)
    switch_positions = [float(row["player_x"]) for row in switch_frames if "player_x" in row]
    switch_forward = [float(row["player_z"]) for row in switch_frames if "player_z" in row]
    switch_visual = check_visual_landmarks(switch_screenshot) if switch_screenshot.is_file() else {"passed": False}
    switch_button = switch_visual.get("button_rgb") or (0, 0, 0)
    checks.update({
        "owner_switch_completed": switched.returncode == 0,
        "owner_switch_reported": "TC_GAMEPAD_OWNER_CHANGED from=0 to=1" in switched.stdout,
        "owner_switch_keyboard_moved": len(switch_positions) == 20 and
            max(switch_positions) - min(switch_positions) > 0.1,
        "owner_switch_held_stick_ignored": len(switch_forward) == 20 and
            max(abs(value) for value in switch_forward[:6]) < 0.01,
        "owner_switch_fresh_stick_works": len(switch_forward) == 20 and
            max(switch_forward[10:]) > 0.01,
        "new_owner_ui_refocused": switched.stdout.count("TC_UI_FOCUS id=save_button") >= 2,
        "new_owner_focus_rendered": switch_visual["passed"] and
            switch_button[2] >= 190 and switch_button[1] >= 135,
    })
    return {"status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "screenshot": str(screenshot), "load_screenshot": str(load_screenshot),
            "load_profile": str(load_profile),
            "failure_screenshot": str(failure_screenshot),
            "stdout": completed.stdout[-1200:], "stderr": completed.stderr[-1200:],
            "load_stdout": loaded.stdout[-1200:], "load_stderr": loaded.stderr[-1200:],
            "failure_stdout": failed.stdout[-1200:], "failure_stderr": failed.stderr[-1200:],
            "disconnect_stdout": disconnected.stdout[-1200:],
            "disconnect_stderr": disconnected.stderr[-1200:],
            "disconnect_profile": str(disconnect_profile),
            "rebind_disconnect_stdout": rebind_disconnected.stdout[-1200:],
            "rebind_disconnect_stderr": rebind_disconnected.stderr[-1200:],
            "rebind_disconnect_profile": str(rebind_profile),
            "rebind_disconnect_screenshot": str(rebind_screenshot),
            "owner_switch_stdout": switched.stdout[-1200:],
            "owner_switch_stderr": switched.stderr[-1200:],
            "owner_switch_profile": str(switch_profile),
            "owner_switch_screenshot": str(switch_screenshot)}


def check_gamepad_load_repeatability(package: Path, *, attempts: int = 20) -> dict[str, Any]:
    """Require repeated independent load-UI frames, not one successful process."""
    if attempts < 1:
        raise ValueError("Gamepad load repeatability needs at least one attempt.")
    package = package.resolve()
    evidence = package / "AcceptanceEvidence" / "gamepad-load-repeatability"
    evidence.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for index in range(attempts):
        profile = evidence / f"load-{index + 1:02d}.jsonl"
        screenshot = evidence / f"load-{index + 1:02d}.bmp"
        profile.unlink(missing_ok=True)
        screenshot.unlink(missing_ok=True)
        command = [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
                   "--renderer", "d3d11", "--require-renderer", "--scripted-gamepad-load-ui",
                   "--frames", "30", "--log", str(profile),
                   "--screenshot", str(screenshot), "--screenshot-frame", "5"]
        try:
            completed = subprocess.run(
                command, cwd=package, capture_output=True, text=True, timeout=30, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stdout, stderr = completed.stdout, completed.stderr
            exit_code = completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            exit_code = None
            timed_out = True
        frames = sum(line.startswith('{"type":"frame"') for line in
                     profile.read_text(encoding="utf-8").splitlines()) if profile.is_file() else 0
        passed = (not timed_out and exit_code == 0 and frames == 30 and screenshot.is_file() and
                  "TC_UI_ACTIVATED id=load_button event=load_game" in stdout and
                  "TC_SAVE_LOADED source=ui" in stdout and
                  "error:" not in (stdout + stderr).lower())
        runs.append({"attempt": index + 1, "status": "passed" if passed else "blocked",
                     "timed_out": timed_out, "exit_code": exit_code, "logged_frames": frames,
                     "screenshot": str(screenshot), "profile": str(profile),
                     "stdout_tail": stdout[-500:], "stderr_tail": stderr[-500:]})
        if not passed:
            break
    return {"status": "passed" if len(runs) == attempts and all(row["status"] == "passed" for row in runs)
            else "blocked", "attempts_requested": attempts, "attempts_completed": len(runs),
            "runs": runs}


def check_gamepad_rebind_ui(package: Path) -> dict[str, Any]:
    """Exercise Jump capture and cross-process persistence with simulated input."""
    package = package.resolve()
    screenshot = package / "Content" / "gamepad-rebind-ui.bmp"
    profile = package / "Content" / "acceptance-input.tcinput"
    profile.unlink(missing_ok=True)
    Path(str(profile) + ".tmp").unlink(missing_ok=True)
    Path(str(profile) + ".bak").unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
         "--input-profile", str(profile),
         "--frames", "20", "--screenshot", str(screenshot), "--screenshot-frame", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    restarted = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    first_profile = profile.read_bytes() if profile.is_file() else b""
    rotated = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
         "--input-profile", str(profile), "--frames", "20"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    profile_backup = Path(str(profile) + ".bak")
    rotated_backup = profile_backup.read_bytes() if profile_backup.is_file() else b""
    if profile.is_file():
        damaged_primary = bytearray(profile.read_bytes())
        if damaged_primary:
            damaged_primary[0] ^= 1
        profile.write_bytes(damaged_primary)
    recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pending_profile = Path(str(profile) + ".tmp")
    if first_profile:
        pending_profile.write_bytes(first_profile)
    pending_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pending_only_profile = package / "Content" / "acceptance-pending-only.tcinput"
    pending_only_profile.unlink(missing_ok=True)
    Path(str(pending_only_profile) + ".bak").unlink(missing_ok=True)
    if first_profile:
        Path(str(pending_only_profile) + ".tmp").write_bytes(first_profile)
    pending_only_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(pending_only_profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    backup_only_profile = package / "Content" / "acceptance-backup-only.tcinput"
    backup_only_profile.unlink(missing_ok=True)
    Path(str(backup_only_profile) + ".tmp").unlink(missing_ok=True)
    if first_profile:
        Path(str(backup_only_profile) + ".bak").write_bytes(first_profile)
    backup_only_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(backup_only_profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if profile.is_file():
        pending_profile.write_bytes(profile.read_bytes())  # Invalid pending checksum.
    corrupt_pending_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    corrupt_profile = package / "Content" / "acceptance-corrupt.tcinput"
    if profile.is_file():
        corrupt_profile.write_bytes(profile.read_bytes())
    rejected = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(corrupt_profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    unwritable_profile = package / "Content" / "acceptance-unwritable.tcinput"
    unwritable_profile.mkdir(exist_ok=True)
    failed_write = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
         "--input-profile", str(unwritable_profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    additional_actions: dict[str, dict[str, Any]] = {}
    for action in ("crouch", "crawl"):
        action_profile = package / "Content" / f"acceptance-{action}.tcinput"
        action_screenshot = package / "Content" / f"gamepad-rebind-{action}.bmp"
        action_profile.unlink(missing_ok=True)
        captured = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
             "--scripted-rebind-action", action, "--input-profile", str(action_profile),
             "--frames", "20", "--screenshot", str(action_screenshot), "--screenshot-frame", "8"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        restored = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
             "--scripted-rebind-action", action, "--input-profile", str(action_profile),
             "--frames", "12"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        additional_actions[action] = {
            "passed": captured.returncode == 0 and restored.returncode == 0 and
            action_profile.is_file() and action_screenshot.is_file() and
            f"TC_UI_ACTIVATED id=rebind_{action} event=rebind_{action}" in captured.stdout and
            f"TC_GAMEPAD_REBOUND action={action} button=SOUTH" in captured.stdout and
            f"TC_GAMEPAD_REBIND_USED action={action} button=SOUTH" in captured.stdout and
            "TC_GAMEPAD_PROFILE_LOADED" in restored.stdout and
            f"TC_GAMEPAD_PROFILE_USED action={action} button=SOUTH" in restored.stdout,
            "screenshot": str(action_screenshot), "capture_stdout": captured.stdout[-600:],
            "restart_stdout": restored.stdout[-600:],
            "stderr": (captured.stderr + restored.stderr)[-600:],
        }
    unicode_profile = package / "Content" / "acceptance-\u4fdd\u5b58.tcinput"
    unicode_profile.unlink(missing_ok=True)
    unicode_saved = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
         "--input-profile", str(unicode_profile), "--frames", "20"],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    unicode_loaded = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-profile-check",
         "--input-profile", str(unicode_profile), "--frames", "12"],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks = {
        "completed": completed.returncode == 0 and screenshot.is_file(),
        "button_activated": "TC_UI_ACTIVATED id=rebind_jump event=rebind_jump" in completed.stdout,
        "capture_prompt": "TC_GAMEPAD_REBIND_PENDING action=jump" in completed.stdout,
        "binding_changed": "TC_GAMEPAD_REBOUND action=jump button=SOUTH" in completed.stdout,
        "new_binding_used": "TC_GAMEPAD_REBIND_USED action=jump button=SOUTH" in completed.stdout,
        "profile_saved": profile.is_file() and "TC_GAMEPAD_PROFILE_SAVED" in completed.stdout,
        "profile_loaded_after_restart": restarted.returncode == 0 and
        "TC_GAMEPAD_PROFILE_LOADED" in restarted.stdout,
        "profile_binding_used_after_restart":
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in restarted.stdout,
        "profile_backup_rotated_and_recovered": rotated.returncode == 0 and
        "TC_GAMEPAD_PROFILE_SAVED" in rotated.stdout and
        bool(first_profile) and rotated_backup == first_profile and
        recovered.returncode == 0 and
        "TC_GAMEPAD_PROFILE_RECOVERED source=backup" in recovered.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in recovered.stdout and
        profile_backup.is_file() and profile_backup.read_bytes() == first_profile,
        "pending_profile_recovered_before_backup": bool(first_profile) and
        pending_recovered.returncode == 0 and
        "TC_GAMEPAD_PROFILE_RECOVERED source=pending" in pending_recovered.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in pending_recovered.stdout,
        "pending_only_profile_recovered": bool(first_profile) and
        not pending_only_profile.exists() and
        not Path(str(pending_only_profile) + ".bak").exists() and
        pending_only_recovered.returncode == 0 and
        "TC_GAMEPAD_PROFILE_RECOVERED source=pending" in pending_only_recovered.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in pending_only_recovered.stdout,
        "backup_only_profile_recovered": bool(first_profile) and
        not backup_only_profile.exists() and
        not Path(str(backup_only_profile) + ".tmp").exists() and
        Path(str(backup_only_profile) + ".bak").read_bytes() == first_profile and
        backup_only_recovered.returncode == 0 and
        "TC_GAMEPAD_PROFILE_RECOVERED source=backup" in backup_only_recovered.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in backup_only_recovered.stdout,
        "corrupt_pending_profile_skipped_for_backup": bool(first_profile) and
        corrupt_pending_recovered.returncode == 0 and
        "TC_GAMEPAD_PROFILE_RECOVERED source=backup" in corrupt_pending_recovered.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in corrupt_pending_recovered.stdout,
        "corrupt_profile_rejected_without_binding": rejected.returncode == 0 and
        "TC_GAMEPAD_PROFILE_REJECTED" in rejected.stderr and
        "TC_GAMEPAD_PROFILE_USED" not in rejected.stdout,
        "failed_save_keeps_authored_binding": failed_write.returncode == 0 and
        "TC_GAMEPAD_PROFILE_SAVE_FAILED" in failed_write.stderr and
        "reason=profile_save_failed" in failed_write.stdout and
        "TC_GAMEPAD_REBOUND" not in failed_write.stdout and
        "TC_GAMEPAD_REBIND_USED" not in failed_write.stdout,
        "crouch_capture_and_restart": additional_actions["crouch"]["passed"],
        "crawl_capture_and_restart": additional_actions["crawl"]["passed"],
        "unicode_profile_saved_and_reloaded": unicode_saved.returncode == 0 and
        unicode_loaded.returncode == 0 and unicode_profile.is_file() and
        "TC_GAMEPAD_PROFILE_SAVED" in unicode_saved.stdout and
        "TC_GAMEPAD_PROFILE_LOADED" in unicode_loaded.stdout and
        "TC_GAMEPAD_PROFILE_USED action=jump button=SOUTH" in unicode_loaded.stdout,
        "no_errors": "error:" not in (completed.stdout + completed.stderr +
                                      restarted.stdout + restarted.stderr).lower(),
    }
    return {"status": "passed" if all(checks.values()) else "blocked",
            "checks": checks, "screenshot": str(screenshot), "profile": str(profile),
            "stdout": completed.stdout[-1200:], "restart_stdout": restarted.stdout[-1200:],
            "recovery_stdout": recovered.stdout[-600:], "recovery_stderr": recovered.stderr[-600:],
            "pending_recovery_stdout": pending_recovered.stdout[-600:],
            "pending_only_recovery_stdout": pending_only_recovered.stdout[-600:],
            "backup_only_recovery_stdout": backup_only_recovered.stdout[-600:],
            "corrupt_pending_recovery_stdout": corrupt_pending_recovered.stdout[-600:],
            "corrupt_stdout": rejected.stdout[-600:], "corrupt_stderr": rejected.stderr[-600:],
            "failed_write_stdout": failed_write.stdout[-600:],
            "failed_write_stderr": failed_write.stderr[-600:],
            "additional_actions": additional_actions,
            "unicode_profile": str(unicode_profile),
            "unicode_capture_stdout": unicode_saved.stdout[-600:],
            "unicode_restart_stdout": unicode_loaded.stdout[-600:],
            "stderr": (completed.stderr + restarted.stderr)[-1200:]}


def check_live_debug_step(package: Path) -> dict[str, Any]:
    """Exercise a real D3D11 pause, snapshot, one-tick step, and resume."""
    content = package / "Content"
    profile = content / "debug-step-profile.jsonl"
    snapshot = content / "debug-step-snapshot.json"
    screenshot = content / "debug-step-frame3.bmp"
    paused_screenshot = content / "debug-step-paused-inspector.bmp"
    break_profile = content / "debug-break-profile.jsonl"
    break_snapshot = content / "debug-break-snapshot.json"
    break_screenshot = content / "debug-break-frame3.bmp"
    break_paused_screenshot = content / "debug-break-paused-inspector.bmp"
    condition_profile = content / "debug-condition-profile.jsonl"
    condition_snapshot = content / "debug-condition-snapshot.json"
    condition_paused_screenshot = content / "debug-condition-paused-inspector.bmp"
    for artifact in (profile, snapshot, screenshot, paused_screenshot, break_profile,
                     break_snapshot, break_screenshot, break_paused_screenshot,
                     condition_profile, condition_snapshot, condition_paused_screenshot):
        artifact.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-debug-step",
         "--frames", "8", "--log", str(profile), "--debug-snapshot", str(snapshot),
         "--debug-paused-screenshot", str(paused_screenshot),
         "--screenshot", str(screenshot), "--screenshot-frame", "3"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    breakpoint = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-debug-step",
         "--break-frame", "1", "--frames", "8", "--log", str(break_profile),
         "--debug-snapshot", str(break_snapshot),
         "--debug-paused-screenshot", str(break_paused_screenshot),
         "--screenshot", str(break_screenshot),
         "--screenshot-frame", "3"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    condition = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-input",
         "--scripted-debug-step", "--break-player-x", "0.001", "--frames", "8",
         "--log", str(condition_profile), "--debug-snapshot", str(condition_snapshot),
         "--debug-paused-screenshot", str(condition_paused_screenshot)],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    frames = ([row for line in profile.read_text(encoding="utf-8").splitlines()
               if line.startswith("{") for row in [json.loads(line)]
               if row.get("type") == "frame"]
              if profile.is_file() else [])
    state = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot.is_file() else {}
    break_state = json.loads(break_snapshot.read_text(encoding="utf-8")) if break_snapshot.is_file() else {}
    condition_state = json.loads(condition_snapshot.read_text(encoding="utf-8")) if condition_snapshot.is_file() else {}
    break_frames = ([row for line in break_profile.read_text(encoding="utf-8").splitlines()
                     if line.startswith("{") for row in [json.loads(line)]
                     if row.get("type") == "frame"] if break_profile.is_file() else [])
    condition_frames = ([row for line in condition_profile.read_text(encoding="utf-8").splitlines()
                         if line.startswith("{") for row in [json.loads(line)]
                         if row.get("type") == "frame"] if condition_profile.is_file() else [])
    checks = {
        "clean_exit": completed.returncode == 0,
        "paused_before_step": "TC_DEBUG_PAUSED frame=1" in completed.stdout,
        "snapshot_during_pause": "TC_DEBUG_SNAPSHOT_OK frame=1" in completed.stdout and
            state.get("schema") == "tech_connector.runtime_debug_snapshot.v1" and
            state.get("frame") == 1 and
            any(entity.get("name") == "Player" for entity in state.get("entities", [])),
        "exactly_one_step": "TC_DEBUG_STEP frame=2" in completed.stdout and
            "TC_DEBUG_RESUMED frame=2" in completed.stdout,
        "frame_sequence_resumed": [row.get("frame") for row in frames] == list(range(1, 9)),
        "graphical_capture": screenshot.is_file(),
        "paused_inspector_presented": "TC_DEBUG_INSPECTOR frame=1" in completed.stdout and
            "TC_DEBUG_INSPECTOR frame=2" in completed.stdout and
            paused_screenshot.is_file() and paused_screenshot.stat().st_size > 54,
        "frame_breakpoint_step_resume": breakpoint.returncode == 0 and
            "TC_DEBUG_BREAK frame=1" in breakpoint.stdout and
            "TC_DEBUG_SNAPSHOT_OK frame=1" in breakpoint.stdout and
            "TC_DEBUG_STEP frame=2" in breakpoint.stdout and
            "TC_DEBUG_RESUMED frame=2" in breakpoint.stdout and
            break_state.get("frame") == 1 and
            [row.get("frame") for row in break_frames] == list(range(1, 9)) and
            break_screenshot.is_file() and
            "TC_DEBUG_INSPECTOR frame=1" in breakpoint.stdout and
            "TC_DEBUG_INSPECTOR frame=2" in breakpoint.stdout and
            break_paused_screenshot.is_file() and break_paused_screenshot.stat().st_size > 54,
        "player_position_breakpoint_step_resume": condition.returncode == 0 and
            "TC_DEBUG_BREAK condition=player_x frame=1" in condition.stdout and
            "TC_DEBUG_SNAPSHOT_OK frame=1" in condition.stdout and
            "TC_DEBUG_STEP frame=2" in condition.stdout and
            "TC_DEBUG_RESUMED frame=2" in condition.stdout and
            condition_state.get("frame") == 1 and
            [row.get("frame") for row in condition_frames] == list(range(1, 9)) and
            "TC_DEBUG_INSPECTOR frame=1" in condition.stdout and
            "TC_DEBUG_INSPECTOR frame=2" in condition.stdout and
            condition_paused_screenshot.is_file() and condition_paused_screenshot.stat().st_size > 54,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "profile": str(profile), "snapshot": str(snapshot), "screenshot": str(screenshot),
            "paused_inspector_screenshot": str(paused_screenshot),
            "stdout": completed.stdout[-800:], "stderr": completed.stderr[-800:],
            "breakpoint_stdout": breakpoint.stdout[-800:],
            "breakpoint_paused_inspector_screenshot": str(break_paused_screenshot),
            "breakpoint_stderr": breakpoint.stderr[-800:],
            "condition_stdout": condition.stdout[-800:],
            "condition_paused_inspector_screenshot": str(condition_paused_screenshot),
            "condition_stderr": condition.stderr[-800:]}


def check_window_minimize_restore(package: Path) -> dict[str, Any]:
    """Exercise a real window minimize/restore without advancing simulation while hidden."""
    content = package / "Content"
    profile = content / "minimize-restore-profile.jsonl"
    screenshot = content / "minimize-restore-frame8.bmp"
    profile.unlink(missing_ok=True)
    screenshot.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-minimize-restore",
         "--frames", "8", "--log", str(profile), "--screenshot", str(screenshot),
         "--screenshot-frame", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    frame_rows = ([row for line in profile.read_text(encoding="utf-8").splitlines()
                   if line.startswith("{") for row in [json.loads(line)]
                   if row.get("type") == "frame"] if profile.is_file() else [])
    frames = [row.get("frame") for row in frame_rows]
    try:
        restored_ui_pixels = check_ui_image_pixels(screenshot) if screenshot.is_file() else {"passed": False}
    except (OSError, ValueError):
        restored_ui_pixels = {"passed": False}
    checks = {
        "clean_exit": completed.returncode == 0,
        "minimized_after_frame_2": "TC_WINDOW_MINIMIZED frame=2" in completed.stdout,
        "restored_without_simulating": "TC_WINDOW_RESTORED frame=2" in completed.stdout,
        "audio_suspended_without_simulating": "TC_AUDIO_SUSPENDED frame=2" in completed.stdout,
        "audio_resumed_on_restore": "TC_AUDIO_RESUMED frame=2" in completed.stdout,
        "frame_sequence_resumed": frames == list(range(1, 9)),
        "renderer_capture_after_restore": screenshot.is_file() and screenshot.stat().st_size > 54,
        "ui_image_not_redecoded_on_restore": bool(frame_rows) and
            max(row.get("ui_compositions", 0) for row in frame_rows) >= 1 and
            max(row.get("ui_image_decodes", 0) for row in frame_rows) == 1 and
            restored_ui_pixels["passed"],
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "profile": str(profile), "screenshot": str(screenshot),
            "stdout": completed.stdout[-800:], "stderr": completed.stderr[-800:]}


def check_runtime_ui_cache(package: Path) -> dict[str, Any]:
    """Guard against decoding a static UI image on every content redraw."""
    content = package / "Content"
    profile = content / "ui-cache-acceptance.jsonl"
    profile.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-input",
         "--frames", "16", "--log", str(profile)],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rows = ([row for line in profile.read_text(encoding="utf-8").splitlines()
             if line.startswith("{") for row in [json.loads(line)]
             if row.get("type") == "frame"] if profile.is_file() else [])
    redraws = [row for index, row in enumerate(rows)
               if row.get("ui_compositions", 0) >
               (rows[index - 1].get("ui_compositions", 0) if index else 0)]
    redraw_frames = {row.get("frame") for row in redraws}
    checks = {
        "clean_exit": completed.returncode == 0,
        "frame_sequence": [row.get("frame") for row in rows] == list(range(1, 17)),
        "ui_changed_after_initial_draw": len(redraws) >= 2,
        "static_image_decoded_once": bool(rows) and rows[-1].get("ui_image_decodes") == 1,
        "gpu_ui_texture_reused": bool(rows) and rows[-1].get("ui_texture_creations") == 1,
        "timings_match_redraws": all(row.get("ui_draw_ms", 0) > 0
                                     for row in redraws) and all(
            row.get("ui_draw_ms") == 0 for row in rows
            if row.get("frame") not in redraw_frames),
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "redraws": [{"frame": row["frame"], "ui_draw_ms": row["ui_draw_ms"],
                         "render_wall_ms": row["render_wall_ms"]} for row in redraws],
            "profile": str(profile), "stdout": completed.stdout[-800:],
            "stderr": completed.stderr[-800:]}


def check_runtime_ui_resize(package: Path) -> dict[str, Any]:
    """Check both-edge layout and clickable UI at two real D3D11 window sizes."""
    package = package.resolve()
    captures = []
    for window_width, window_height in ((800, 600), (1600, 900)):
        screenshot = package / "Content" / f"ui-resize-{window_width}.bmp"
        save = packaged_save_path(package)
        screenshot.unlink(missing_ok=True)
        save.unlink(missing_ok=True)
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--frames", "8",
             "--scripted-input",
             "--window-width", str(window_width), "--window-height", str(window_height),
             "--screenshot", str(screenshot), "--screenshot-frame", "4"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not screenshot.is_file():
            raise RuntimeError(f"UI resize capture failed at {window_width}: " +
                               (completed.stderr or completed.stdout)[-900:])
        with screenshot.open("rb") as stream:
            header = stream.read(54)
            if len(header) != 54 or header[:2] != b"BM" or struct.unpack_from("<H", header, 28)[0] != 24:
                raise ValueError("UI resize capture is not a 24-bit BMP.")
            offset = struct.unpack_from("<I", header, 10)[0]
            width, height = struct.unpack_from("<ii", header, 18)
            row_bytes = (width * 3 + 3) & ~3
            stream.seek(offset + (height - 1 - 25) * row_bytes)
            row = stream.read(row_bytes)
            dark = [x for x in range(min(width, 500)) if sum(row[x * 3:x * 3 + 3]) < 350]
            span = [min(dark), max(dark)] if dark else [0, 0]
            right = [x for x in range(max(width // 2, width - 210), width - 4)
                     if sum(row[x * 3:x * 3 + 3]) < 350]
            right_span = [min(right), max(right)] if right else [0, 0]
        activated = "TC_UI_ACTIVATED id=save_button event=save_game" in completed.stdout
        captures.append({"window_width": window_width, "capture_width": width,
                         "panel_span": span, "right_panel_span": right_span,
                         "button_activated": activated, "save_written": save.is_file(),
                         "screenshot": str(screenshot)})
    widths = [item["panel_span"][1] - item["panel_span"][0] for item in captures]
    right_widths = [item["right_panel_span"][1] - item["right_panel_span"][0] for item in captures]
    right_margins = [item["capture_width"] - item["right_panel_span"][1] for item in captures]
    passed = (all(275 <= value <= 310 for value in widths) and abs(widths[0] - widths[1]) <= 4
              and all(135 <= value <= 155 for value in right_widths)
              and abs(right_widths[0] - right_widths[1]) <= 4
              and all(15 <= value <= 30 for value in right_margins)
              and all(item["button_activated"] and item["save_written"] for item in captures))
    return {"status": "passed" if passed else "blocked", "panel_widths": widths, "captures": captures}


def check_runtime_ui_scale(package: Path) -> dict[str, Any]:
    """Verify that manual HUD scaling also scales the live mouse hit targets."""
    package = package.resolve()
    captures: list[dict[str, Any]] = []
    for scale, window_width, window_height in ((0.75, 960, 540), (1.0, 1280, 720),
                                               (1.5, 1920, 1080), (2.0, 2560, 1440)):
        screenshot = package / "Content" / f"ui-scale-{int(scale * 100)}.bmp"
        save = packaged_save_path(package)
        screenshot.unlink(missing_ok=True)
        save.unlink(missing_ok=True)
        completed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-input", "--frames", "8",
             "--window-width", str(window_width), "--window-height", str(window_height),
             "--ui-scale", str(scale), "--screenshot", str(screenshot), "--screenshot-frame", "4"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not screenshot.is_file():
            raise RuntimeError(f"UI scale capture failed at {scale}: " +
                               (completed.stderr or completed.stdout)[-900:])
        dpi_receipt = re.search(r"TC_DPI_INITIAL dpi=(\d+) ui_scale=([0-9.]+)", completed.stdout)
        if dpi_receipt is None:
            raise RuntimeError("UI scale capture lacks an initial DPI receipt.")
        if "awareness=per_monitor_v2" not in completed.stdout:
            raise RuntimeError("UI scale capture is not running in per-monitor-v2 DPI awareness.")
        effective_scale = float(dpi_receipt.group(2))
        with screenshot.open("rb") as stream:
            header = stream.read(54)
            if len(header) != 54 or header[:2] != b"BM" or struct.unpack_from("<H", header, 28)[0] != 24:
                raise ValueError("UI scale capture is not a 24-bit BMP.")
            offset = struct.unpack_from("<I", header, 10)[0]
            width, height = struct.unpack_from("<ii", header, 18)
            row_bytes = (width * 3 + 3) & ~3
            y = round(25 * effective_scale)
            stream.seek(offset + (height - 1 - y) * row_bytes)
            row = stream.read(row_bytes)
        dark = [x for x in range(min(width, round(400 * effective_scale)))
                if sum(row[x * 3:x * 3 + 3]) < 350]
        span = [min(dark), max(dark)] if dark else [0, 0]
        # Sample the authored Save button in logical canvas coordinates; a
        # fixed screen fraction can probe the panel or sky at extreme scales.
        visual = check_visual_landmarks(screenshot, button_x=200 * effective_scale / width,
                                        button_y=107 * effective_scale / height,
                                        panel_y=50 * effective_scale / height)
        captures.append({"scale": scale, "effective_scale": effective_scale,
                         "initial_dpi": int(dpi_receipt.group(1)),
                         "capture_width": width, "panel_span": span,
                         "visual_passed": visual["passed"],
                         "button_activated": "TC_UI_ACTIVATED id=save_button event=save_game" in completed.stdout,
                         "save_written": save.is_file(), "screenshot": str(screenshot)})
    base_width = captures[1]["panel_span"][1] - captures[1]["panel_span"][0]
    ratios = {str(row["scale"]): ((row["panel_span"][1] - row["panel_span"][0]) / base_width
                                  if base_width > 0 else 0.0) for row in captures}
    dpi_changes: list[dict[str, Any]] = []
    for manual_scale in (1.0, 2.0):
        dpi_screenshot = package / "Content" / f"ui-dpi-change-{int(manual_scale * 100)}.bmp"
        save.unlink(missing_ok=True)
        dpi_screenshot.unlink(missing_ok=True)
        changed = subprocess.run(
            [str(package / "TCPlayer.exe"), "--scene", str(package / "Content" / "main.tcruntime"),
             "--renderer", "d3d11", "--require-renderer", "--scripted-input", "--scripted-dpi-change",
             "--frames", "8", "--window-width", "1280", "--window-height", "720",
             "--ui-scale", str(manual_scale), "--screenshot", str(dpi_screenshot),
             "--screenshot-frame", "4"],
            cwd=package, capture_output=True, text=True, timeout=60, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        changed_receipt = re.search(r"TC_DPI_CHANGED dpi=144 ui_scale=([0-9.]+)", changed.stdout)
        dpi_change: dict[str, Any] = {"status": "blocked", "manual_scale": manual_scale,
                                      "screenshot": str(dpi_screenshot)}
        if changed.returncode == 0 and changed_receipt is not None and dpi_screenshot.is_file():
            effective = float(changed_receipt.group(1))
            with dpi_screenshot.open("rb") as stream:
                header = stream.read(54)
                offset = struct.unpack_from("<I", header, 10)[0]
                width, height = struct.unpack_from("<ii", header, 18)
                row_bytes = (width * 3 + 3) & ~3
                stream.seek(offset + (height - 1 - round(25 * effective)) * row_bytes)
                row = stream.read(row_bytes)
            dark = [x for x in range(min(width, round(400 * effective)))
                    if sum(row[x * 3:x * 3 + 3]) < 350]
            span = [min(dark), max(dark)] if dark else [0, 0]
            visual = check_visual_landmarks(dpi_screenshot, button_x=200 * effective / width,
                                            button_y=107 * effective / height,
                                            panel_y=50 * effective / height)
            observed = (span[1] - span[0]) / base_width if base_width > 0 else 0.0
            expected = manual_scale * 144 / captures[1]["initial_dpi"]
            dpi_passed = (visual["passed"] and save.is_file() and
                          "TC_UI_ACTIVATED id=save_button event=save_game" in changed.stdout and
                          abs(observed - expected) <= 0.05 and abs(effective - expected) <= 0.01)
            dpi_change = {"status": "passed" if dpi_passed else "blocked",
                          "manual_scale": manual_scale, "initial_dpi": captures[1]["initial_dpi"],
                          "changed_dpi": 144, "effective_scale": effective,
                          "panel_width_ratio": observed, "expected_width_ratio": expected,
                          "visual_passed": visual["passed"], "save_written": save.is_file(),
                          "screenshot": str(dpi_screenshot)}
        dpi_changes.append(dpi_change)
    passed = (all(abs(ratios[str(row["scale"])] - row["scale"]) <= 0.05 for row in captures) and
              all(row["visual_passed"] and row["button_activated"] and row["save_written"]
                  for row in captures) and all(row["status"] == "passed" for row in dpi_changes))
    return {"status": "passed" if passed else "blocked", "panel_width_ratio": ratios["1.5"],
            "panel_width_ratios": ratios, "dpi_change": dpi_changes[0],
            "combined_dpi_change": dpi_changes[1],
            "captures": captures}


def check_runtime_ui_safe_area(package: Path) -> dict[str, Any]:
    """Exercise a platform-style UI inset in the actual renderer and mouse path."""
    package = package.resolve()
    content = package / "Content"
    source = (content / "main.tcruntime").read_text(encoding="utf-8")
    if "UISAFEAREA\t" in source or "UICANVAS\t" not in source:
        raise ValueError("Safe-area acceptance requires an uninset authored UI manifest.")
    rows = source.splitlines()
    index = next(index for index, row in enumerate(rows) if row.startswith("UICANVAS\t"))
    rows.insert(index + 1, "UISAFEAREA\t40\t30\t40\t30")
    scene = content / "safe-area-acceptance.tcruntime"
    scene.write_text("\n".join(rows) + "\n", encoding="utf-8")
    screenshot = content / "ui-safe-area.bmp"
    save = packaged_save_path(package)
    screenshot.unlink(missing_ok=True)
    save.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene), "--renderer", "d3d11",
         "--require-renderer", "--scripted-input", "--frames", "8",
         "--window-width", "800", "--window-height", "600",
         "--screenshot", str(screenshot), "--screenshot-frame", "4"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not screenshot.is_file():
        raise RuntimeError("Safe-area capture failed: " + (completed.stderr or completed.stdout)[-900:])
    with screenshot.open("rb") as stream:
        header = stream.read(54)
        if len(header) != 54 or header[:2] != b"BM" or struct.unpack_from("<H", header, 28)[0] != 24:
            raise ValueError("Safe-area capture is not a 24-bit BMP.")
        offset = struct.unpack_from("<I", header, 10)[0]
        width, height = struct.unpack_from("<ii", header, 18)
        row_bytes = (width * 3 + 3) & ~3
        stream.seek(offset + (height - 1 - 55) * row_bytes)
        row = stream.read(row_bytes)
        left = [x for x in range(min(400, width)) if sum(row[x * 3:x * 3 + 3]) < 350]
        right = [x for x in range(width // 2, width - 4)
                 if sum(row[x * 3:x * 3 + 3]) < 350]
    left_span = [min(left), max(left)] if left else [0, 0]
    right_span = [min(right), max(right)] if right else [0, 0]
    activated = "TC_UI_ACTIVATED id=save_button event=save_game" in completed.stdout
    passed = (55 <= left_span[0] <= 65 and 350 <= left_span[1] <= 365
              and 135 <= right_span[1] - right_span[0] <= 155
              and 55 <= width - right_span[1] <= 70 and activated and save.is_file())
    return {"status": "passed" if passed else "blocked", "left_span": left_span,
            "right_span": right_span, "capture_width": width,
            "button_activated": activated, "save_written": save.is_file(),
            "screenshot": str(screenshot)}


def check_runtime_ui_narrow(package: Path) -> dict[str, Any]:
    """Require the optional right HUD to disappear without losing Save interaction."""
    package = package.resolve()
    content = package / "Content"
    screenshot = content / "ui-narrow.bmp"
    save = packaged_save_path(package)
    screenshot.unlink(missing_ok=True)
    save.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-input", "--frames", "8",
         "--window-width", "480", "--window-height", "640",
         "--screenshot", str(screenshot), "--screenshot-frame", "4"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0 or not screenshot.is_file():
        raise RuntimeError("Narrow UI capture failed: " + (completed.stderr or completed.stdout)[-900:])
    with screenshot.open("rb") as stream:
        header = stream.read(54)
        if len(header) != 54 or header[:2] != b"BM" or struct.unpack_from("<H", header, 28)[0] != 24:
            raise ValueError("Narrow UI capture is not a 24-bit BMP.")
        offset = struct.unpack_from("<I", header, 10)[0]
        width, height = struct.unpack_from("<ii", header, 18)
        row_bytes = (width * 3 + 3) & ~3
        stream.seek(offset + (height - 1 - 30) * row_bytes)
        row = stream.read(row_bytes)
        dark = [x for x in range(width) if sum(row[x * 3:x * 3 + 3]) < 350]
    span = [min(dark), max(dark)] if dark else [0, 0]
    activated = "TC_UI_ACTIVATED id=save_button event=save_game" in completed.stdout
    passed = (20 <= span[0] <= 25 and 310 <= span[1] <= 325
              and width >= 440 and activated and save.is_file())
    return {"status": "passed" if passed else "blocked", "visible_panel_span": span,
            "capture_width": width, "button_activated": activated,
            "save_written": save.is_file(), "screenshot": str(screenshot)}


def check_runtime_ui_short(package: Path) -> dict[str, Any]:
    """Verify the lowest gameplay control remains clickable in a short D3D11 window."""
    package = package.resolve()
    content = package / "Content"
    screenshot = content / "ui-short.bmp"
    profile = content / "ui-short-input.tcinput"
    profile.unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-rebind-ui",
         "--scripted-rebind-action", "crawl", "--input-profile", str(profile),
         "--frames", "20", "--window-width", "480", "--window-height", "270",
         "--screenshot", str(screenshot), "--screenshot-frame", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    width = height = 0
    if screenshot.is_file():
        with screenshot.open("rb") as stream:
            header = stream.read(54)
            if len(header) == 54 and header[:2] == b"BM":
                candidate_width, candidate_height = struct.unpack_from("<ii", header, 18)
                offset = struct.unpack_from("<I", header, 10)[0]
                planes = struct.unpack_from("<H", header, 26)[0]
                depth = struct.unpack_from("<H", header, 28)[0]
                compression = struct.unpack_from("<I", header, 30)[0]
                if (candidate_width > 0 and candidate_height > 0 and offset >= 54 and
                        planes == 1 and depth == 24 and compression == 0):
                    row_bytes = (candidate_width * 3 + 3) & ~3
                    stream.seek(0, 2)
                    if stream.tell() >= offset + row_bytes * candidate_height:
                        width, height = candidate_width, candidate_height
    passed = (completed.returncode == 0 and width >= 440 and height >= 223 and
              "TC_UI_ACTIVATED id=rebind_crawl event=rebind_crawl" in completed.stdout and
              "TC_GAMEPAD_REBOUND action=crawl button=SOUTH" in completed.stdout and
              profile.is_file())
    return {"status": "passed" if passed else "blocked", "capture_size": [width, height],
            "crawl_button_activated": "TC_UI_ACTIVATED id=rebind_crawl" in completed.stdout,
            "binding_changed": "TC_GAMEPAD_REBOUND action=crawl button=SOUTH" in completed.stdout,
            "screenshot": str(screenshot), "stdout": completed.stdout[-600:],
            "stderr": completed.stderr[-600:]}


def check_audio_mute_ui(package: Path) -> dict[str, Any]:
    """Exercise reversible mute, persistence, and failed-profile rollback."""
    package = package.resolve()
    content = package / "Content"
    screenshot = content / "audio-muted-ui.bmp"
    profile = content / "audio-muted-ui.jsonl"
    preference = content / "audio-acceptance.tcaudio"
    profile.unlink(missing_ok=True)
    preference.unlink(missing_ok=True)
    Path(str(preference) + ".tmp").unlink(missing_ok=True)
    Path(str(preference) + ".bak").unlink(missing_ok=True)
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-mute-ui",
         "--audio-profile", str(preference),
         "--frames", "20", "--window-width", "480", "--window-height", "270",
         "--log", str(profile), "--screenshot", str(screenshot), "--screenshot-frame", "6"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    audio = check_packaged_audio(profile) if profile.is_file() else {"played": False, "submitted": False}
    saved = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-mute-once",
         "--audio-profile", str(preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    restored_screenshot = content / "audio-restored-ui.bmp"
    restored = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(preference), "--frames", "12",
         "--screenshot", str(restored_screenshot), "--screenshot-frame", "4"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    muted_preference = preference.read_bytes() if preference.is_file() else b""
    rotated = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-mute-once",
         "--audio-profile", str(preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    preference_backup = Path(str(preference) + ".bak")
    rotated_backup = preference_backup.read_bytes() if preference_backup.is_file() else b""
    if preference.is_file():
        damaged_primary = bytearray(preference.read_bytes())
        if damaged_primary:
            damaged_primary[0] ^= 1
        preference.write_bytes(damaged_primary)
    recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pending_preference = Path(str(preference) + ".tmp")
    if muted_preference:
        pending_preference.write_bytes(muted_preference)
    pending_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pending_only_preference = content / "audio-pending-only.tcaudio"
    pending_only_preference.unlink(missing_ok=True)
    Path(str(pending_only_preference) + ".bak").unlink(missing_ok=True)
    if muted_preference:
        Path(str(pending_only_preference) + ".tmp").write_bytes(muted_preference)
    pending_only_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(pending_only_preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    backup_only_preference = content / "audio-backup-only.tcaudio"
    backup_only_preference.unlink(missing_ok=True)
    Path(str(backup_only_preference) + ".tmp").unlink(missing_ok=True)
    if muted_preference:
        Path(str(backup_only_preference) + ".bak").write_bytes(muted_preference)
    backup_only_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(backup_only_preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if preference.is_file():
        pending_preference.write_bytes(preference.read_bytes())  # Invalid pending checksum.
    corrupt_pending_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    corrupt = content / "audio-corrupt.tcaudio"
    if preference.is_file():
        corrupt.write_bytes(preference.read_bytes())
    rejected = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(corrupt), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    unwritable = content / "audio-unwritable.tcaudio"
    unwritable.mkdir(exist_ok=True)
    failed_write = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-mute-once",
         "--audio-profile", str(unwritable), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    unicode_preference = content / "audio-\u4fdd\u5b58.tcaudio"
    unicode_preference.unlink(missing_ok=True)
    unicode_saved = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-mute-once",
         "--audio-profile", str(unicode_preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    unicode_loaded = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(content / "main.tcruntime"),
         "--renderer", "d3d11", "--require-renderer", "--scripted-audio-profile-check",
         "--audio-profile", str(unicode_preference), "--frames", "12"],
        cwd=package, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks = {
        "reversible_ui_and_buffer_completion": completed.returncode == 0 and screenshot.is_file() and
        completed.stdout.count("TC_UI_ACTIVATED id=audio_toggle event=audio_toggle") == 2 and
        "TC_AUDIO_MUTED muted=1" in completed.stdout and
        "TC_AUDIO_MUTED muted=0" in completed.stdout and audio["played"],
        "saved_muted_preference": saved.returncode == 0 and preference.is_file() and
        "TC_AUDIO_PROFILE_SAVED muted=1" in saved.stdout,
        "restored_muted_preference": restored.returncode == 0 and restored_screenshot.is_file() and
        "TC_AUDIO_PROFILE_LOADED muted=1" in restored.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in restored.stdout,
        "muted_preference_backup_rotated_and_recovered": rotated.returncode == 0 and
        "TC_AUDIO_PROFILE_SAVED muted=0" in rotated.stdout and
        bool(muted_preference) and rotated_backup == muted_preference and
        recovered.returncode == 0 and
        "TC_AUDIO_PROFILE_RECOVERED source=backup" in recovered.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in recovered.stdout and
        preference_backup.is_file() and preference_backup.read_bytes() == muted_preference,
        "pending_muted_preference_recovered_before_backup": bool(muted_preference) and
        pending_recovered.returncode == 0 and
        "TC_AUDIO_PROFILE_RECOVERED source=pending" in pending_recovered.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in pending_recovered.stdout,
        "pending_only_muted_preference_recovered": bool(muted_preference) and
        not pending_only_preference.exists() and
        not Path(str(pending_only_preference) + ".bak").exists() and
        pending_only_recovered.returncode == 0 and
        "TC_AUDIO_PROFILE_RECOVERED source=pending" in pending_only_recovered.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in pending_only_recovered.stdout,
        "backup_only_muted_preference_recovered": bool(muted_preference) and
        not backup_only_preference.exists() and
        not Path(str(backup_only_preference) + ".tmp").exists() and
        Path(str(backup_only_preference) + ".bak").read_bytes() == muted_preference and
        backup_only_recovered.returncode == 0 and
        "TC_AUDIO_PROFILE_RECOVERED source=backup" in backup_only_recovered.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in backup_only_recovered.stdout,
        "corrupt_pending_muted_preference_skipped_for_backup": bool(muted_preference) and
        corrupt_pending_recovered.returncode == 0 and
        "TC_AUDIO_PROFILE_RECOVERED source=backup" in corrupt_pending_recovered.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in corrupt_pending_recovered.stdout,
        "corrupt_preference_rejected": rejected.returncode == 0 and
        "TC_AUDIO_PROFILE_REJECTED" in rejected.stderr and
        "TC_AUDIO_PROFILE_STATE muted=0" in rejected.stdout,
        "failed_save_rolls_back": failed_write.returncode == 0 and
        "TC_AUDIO_MUTE_FAILED" in failed_write.stderr and
        "TC_AUDIO_MUTED muted=1" not in failed_write.stdout and
        "TC_AUDIO_PROFILE_SAVED" not in failed_write.stdout,
        "unicode_preference_saved_and_reloaded": unicode_saved.returncode == 0 and
        unicode_loaded.returncode == 0 and unicode_preference.is_file() and
        "TC_AUDIO_PROFILE_SAVED muted=1" in unicode_saved.stdout and
        "TC_AUDIO_PROFILE_LOADED muted=1" in unicode_loaded.stdout and
        "TC_AUDIO_PROFILE_STATE muted=1" in unicode_loaded.stdout,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "screenshot": str(screenshot), "restored_screenshot": str(restored_screenshot),
            "profile": str(profile), "preference": str(preference),
            "audio_buffer_completed": audio["played"],
            "stdout": completed.stdout[-700:], "saved_stdout": saved.stdout[-500:],
            "restored_stdout": restored.stdout[-500:],
            "recovery_stdout": recovered.stdout[-500:], "recovery_stderr": recovered.stderr[-500:],
            "pending_recovery_stdout": pending_recovered.stdout[-500:],
            "pending_only_recovery_stdout": pending_only_recovered.stdout[-500:],
            "backup_only_recovery_stdout": backup_only_recovered.stdout[-500:],
            "corrupt_pending_recovery_stdout": corrupt_pending_recovered.stdout[-500:],
            "corrupt_stderr": rejected.stderr[-500:], "corrupt_stdout": rejected.stdout[-500:],
            "failed_write_stdout": failed_write.stdout[-500:],
            "failed_write_stderr": failed_write.stderr[-500:],
            "unicode_preference": str(unicode_preference),
            "unicode_save_stdout": unicode_saved.stdout[-500:],
            "unicode_load_stdout": unicode_loaded.stdout[-500:],
            "stderr": completed.stderr[-700:]}


def check_user_scoped_save_load(package: Path) -> dict[str, Any]:
    """Exercise F5/F6 using a writable location outside packaged Content."""
    package = package.resolve()
    content = package / "Content"
    slot = "save_location_acceptance"
    scene = content / "save-location-acceptance.tcruntime"
    rows = (content / "main.tcruntime").read_text(encoding="utf-8").splitlines()
    rows = [f"SAVE\t{slot}" if row.startswith("SAVE\t") else row for row in rows]
    scene.write_text("\n".join(rows) + "\n", encoding="utf-8")
    save_dir = package.parent / "user-save-acceptance"
    save = save_dir / f"{slot}.tcsave"
    packaged_save = content / f"{slot}.tcsave"
    screenshot = content / "save-location-acceptance.bmp"
    completed = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(save_dir), "--frames", "14",
         "--screenshot", str(screenshot), "--screenshot-frame", "10"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    scene_key = next((row.split("\t", 1)[1] for row in rows if row.startswith("SCENEID\t")), "")
    relocated_scene = content / "save-location-relocated.tcruntime"
    relocated_scene.write_text("\n".join(rows) + "\n", encoding="utf-8")
    local_data = package.parent / "localappdata-save-acceptance"
    environment = {**os.environ, "LOCALAPPDATA": str(local_data)}
    default_save = local_data / "TechConnector" / "TCPlayer" / "saves" / scene_key / f"{slot}.tcsave"
    default_saved = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load", "--frames", "12"],
        cwd=package, env=environment, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    relocated_loaded = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(relocated_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only", "--frames", "8"],
        cwd=package, env=environment, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    migration_slot = "save_migration_acceptance"
    migration_scene = content / "save-migration-acceptance.tcruntime"
    migration_rows = [f"SAVE\t{migration_slot}" if row.startswith("SAVE\t") else row for row in rows]
    migration_scene.write_text("\n".join(migration_rows) + "\n", encoding="utf-8")
    legacy_save = content / f"{migration_slot}.tcsave"
    legacy_written = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(migration_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(content), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    migration_data = package.parent / f"localappdata-migration-acceptance-{os.getpid()}-{time.time_ns()}"
    migration_environment = {**os.environ, "LOCALAPPDATA": str(migration_data)}
    migrated_save = migration_data / "TechConnector" / "TCPlayer" / "saves" / scene_key / f"{migration_slot}.tcsave"
    migrated_loaded = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(migration_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only", "--frames", "8"],
        cwd=package, env=migration_environment, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    blocked_local_data = content / "migration-localappdata-blocker"
    blocked_local_data.write_text("not a directory\n", encoding="utf-8")
    # This checks the status receipt; the UI screenshot matrix separately
    # exercises D3D11. Avoid another device/window lifetime in this save test.
    blocked_migration = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(migration_scene),
         "--renderer", "null", "--scripted-load-only", "--frames", "8"],
        cwd=package, env={**os.environ, "LOCALAPPDATA": str(blocked_local_data)},
        capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    foreign_scene = content / "foreign-scene-acceptance.tcruntime"
    foreign_key = "0" * 24 if scene_key != "0" * 24 else "f" * 24
    foreign_scene.write_text("\n".join(
        f"SCENEID\t{foreign_key}" if row.startswith("SCENEID\t") else row for row in rows
    ) + "\n", encoding="utf-8")
    shared_save_dir = package.parent / "cross-scene-save-acceptance"
    shared_save = shared_save_dir / f"{slot}.tcsave"
    bound_written = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(shared_save_dir), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    bound_written_again = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(shared_save_dir), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    bound_bytes = shared_save.read_bytes() if shared_save.is_file() else b""
    backup = Path(str(shared_save) + ".bak")
    backup_bytes = backup.read_bytes() if backup.is_file() else b""
    foreign_rejected = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(foreign_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    foreign_overwrite = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(foreign_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(shared_save_dir), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks = {
        "saved_outside_package": save.is_file() and save.read_bytes().startswith(b"TCSAVE\t3\n")
        and not packaged_save.exists(),
        "windowed_save_and_load": completed.returncode == 0 and
        "TC_SAVE_WRITTEN source=hotkey" in completed.stdout and
        "TC_SAVE_LOADED source=hotkey" in completed.stdout and screenshot.is_file(),
        "no_save_errors": "TC_SAVE_FAILED" not in completed.stderr and
        "TC_LOAD_FAILED" not in completed.stderr,
        "default_path_survives_scene_relocation": bool(scene_key) and default_save.is_file() and
        default_saved.returncode == 0 and relocated_loaded.returncode == 0 and
        "TC_SAVE_WRITTEN source=hotkey" in default_saved.stdout and
        "TC_SAVE_LOADED source=hotkey" in relocated_loaded.stdout and
        "TC_LOAD_FAILED" not in relocated_loaded.stderr,
        "legacy_content_save_migrated": legacy_written.returncode == 0 and
        migrated_loaded.returncode == 0 and legacy_save.is_file() and migrated_save.is_file() and
        "TC_SAVE_MIGRATED from=" in migrated_loaded.stdout and
        "TC_SAVE_LOADED source=hotkey" in migrated_loaded.stdout,
        "failed_migration_warns_player": blocked_migration.returncode == 0 and
        "TC_SAVE_MIGRATION_FAILED from=" in blocked_migration.stderr and
        "TC_UI_STATUS text=Upgrade failed" in blocked_migration.stdout and
        "TC_SAVE_MIGRATED from=" not in blocked_migration.stdout,
        "foreign_scene_save_rejected": bool(scene_key) and bound_written.returncode == 0 and
        bound_written_again.returncode == 0 and
        foreign_rejected.returncode == 0 and bool(bound_bytes) and bool(backup_bytes) and
        f"SCENE\t{scene_key}\n".encode() in bound_bytes and
        "TC_LOAD_FAILED source=hotkey reason=TC save game belongs to another scene" in
        foreign_rejected.stderr and
        "TC_SAVE_LOADED source=hotkey" not in foreign_rejected.stdout and
        shared_save.read_bytes() == bound_bytes and backup.read_bytes() == backup_bytes,
        "foreign_scene_overwrite_rejected": foreign_overwrite.returncode == 0 and
        "TC_SAVE_FAILED source=hotkey reason=Existing save game belongs to another scene:" in
        foreign_overwrite.stderr and "TC_SAVE_WRITTEN source=hotkey" not in foreign_overwrite.stdout and
        shared_save.read_bytes() == bound_bytes and backup.read_bytes() == backup_bytes,
    }
    foreign_save_dir = package.parent / "foreign-save-acceptance"
    foreign_written = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(foreign_scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-save-load",
         "--save-dir", str(foreign_save_dir), "--frames", "12"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    foreign_save = foreign_save_dir / f"{slot}.tcsave"
    foreign_bytes = foreign_save.read_bytes() if foreign_save.is_file() else b""
    temporary = Path(str(shared_save) + ".tmp")
    temporary.write_bytes(foreign_bytes)
    primary_preferred = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["valid_primary_ignores_foreign_pending_save"] = (
        bool(foreign_bytes) and primary_preferred.returncode == 0 and
        "TC_SAVE_LOADED source=hotkey" in primary_preferred.stdout and
        "TC_SAVE_RECOVERED" not in primary_preferred.stdout and
        "TC_LOAD_FAILED" not in primary_preferred.stderr and
        shared_save.read_bytes() == bound_bytes and backup.read_bytes() == backup_bytes and
        temporary.read_bytes() == foreign_bytes
    )
    temporary.unlink()
    if foreign_bytes and shared_save.is_file():
        shared_save.write_bytes(foreign_bytes)
    compatible_backup = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["foreign_primary_compatible_backup_recovered"] = (
        bool(scene_key) and foreign_written.returncode == 0 and bool(foreign_bytes) and
        f"SCENE\t{foreign_key}\n".encode() in foreign_bytes and
        compatible_backup.returncode == 0 and
        "TC_SAVE_LOADED source=hotkey" in compatible_backup.stdout and
        "TC_SAVE_RECOVERED source=hotkey reason=Recovered previous TC save game from backup" in
        compatible_backup.stdout and
        shared_save.read_bytes() == foreign_bytes and backup.read_bytes() == backup_bytes
    )
    temporary.write_bytes(backup_bytes)
    pending_recovered = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["foreign_primary_valid_pending_save_recovered"] = (
        bool(backup_bytes) and pending_recovered.returncode == 0 and
        "TC_SAVE_LOADED source=hotkey" in pending_recovered.stdout and
        "TC_SAVE_RECOVERED source=hotkey reason=Recovered pending TC save game from temporary file" in
        pending_recovered.stdout and shared_save.read_bytes() == foreign_bytes and
        backup.read_bytes() == backup_bytes and temporary.read_bytes() == backup_bytes
    )
    invalid_temporary = b"TCSAVE\t3\nINCOMPLETE_PENDING_WRITE"
    temporary.write_bytes(invalid_temporary)
    invalid_pending_fallback = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["invalid_pending_save_falls_back_to_backup"] = (
        bool(backup_bytes) and invalid_pending_fallback.returncode == 0 and
        "TC_SAVE_LOADED source=hotkey" in invalid_pending_fallback.stdout and
        "TC_SAVE_RECOVERED source=hotkey reason=Recovered previous TC save game from backup" in
        invalid_pending_fallback.stdout and shared_save.read_bytes() == foreign_bytes and
        backup.read_bytes() == backup_bytes and temporary.read_bytes() == invalid_temporary
    )
    temporary.unlink()
    shared_save.unlink()
    backup_only = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["missing_primary_valid_backup_recovered"] = (
        bool(backup_bytes) and backup_only.returncode == 0 and
        "TC_SAVE_LOADED source=hotkey" in backup_only.stdout and
        "TC_SAVE_RECOVERED source=hotkey reason=Recovered previous TC save game from backup" in
        backup_only.stdout and not shared_save.exists() and backup.read_bytes() == backup_bytes
    )
    invalid_primary = b"TCSAVE\t3\nTRUNCATED"
    invalid_backup = b"TCSAVE\t3\nBROKEN_BACKUP"
    shared_save.write_bytes(invalid_primary)
    backup.write_bytes(invalid_backup)
    both_invalid = subprocess.run(
        [str(package / "TCPlayer.exe"), "--scene", str(scene),
         "--renderer", "d3d11", "--require-renderer", "--scripted-load-only",
         "--save-dir", str(shared_save_dir), "--frames", "8"],
        cwd=package, capture_output=True, text=True, timeout=60, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    checks["invalid_primary_and_backup_rejected_without_mutation"] = (
        both_invalid.returncode == 0 and
        "TC_LOAD_FAILED source=hotkey" in both_invalid.stderr and
        "TC_SAVE_LOADED source=hotkey" not in both_invalid.stdout and
        "TC_SAVE_RECOVERED source=hotkey" not in both_invalid.stdout and
        shared_save.read_bytes() == invalid_primary and backup.read_bytes() == invalid_backup
    )
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "save": str(save), "default_save": str(default_save),
            "legacy_save": str(legacy_save), "migrated_save": str(migrated_save),
            "foreign_scene": str(foreign_scene), "shared_save": str(shared_save),
            "screenshot": str(screenshot),
            "stdout": completed.stdout[-700:], "stderr": completed.stderr[-700:],
            "relocated_stdout": relocated_loaded.stdout[-500:],
            "relocated_stderr": relocated_loaded.stderr[-500:],
            "migration_stdout": migrated_loaded.stdout[-500:],
            "migration_stderr": migrated_loaded.stderr[-500:],
            "blocked_migration_stdout": blocked_migration.stdout[-500:],
            "blocked_migration_stderr": blocked_migration.stderr[-500:],
            "foreign_stderr": foreign_rejected.stderr[-500:],
            "foreign_overwrite_stderr": foreign_overwrite.stderr[-500:],
            "backup_only_stdout": backup_only.stdout[-500:],
            "backup_only_stderr": backup_only.stderr[-500:],
            "pending_recovery_stdout": pending_recovered.stdout[-500:],
            "pending_recovery_stderr": pending_recovered.stderr[-500:],
            "invalid_pending_fallback_stdout": invalid_pending_fallback.stdout[-500:],
            "invalid_pending_fallback_stderr": invalid_pending_fallback.stderr[-500:],
            "invalid_primary_and_backup_stderr": both_invalid.stderr[-500:]}


def check_cross_install_save_upgrade(package: Path) -> dict[str, Any]:
    """Rehearse a compatible content update across separate install roots."""
    package = package.resolve()
    content = package / "Content"
    rows = (content / "main.tcruntime").read_text(encoding="utf-8").splitlines()
    scene_key = next((row.split("\t", 1)[1] for row in rows if row.startswith("SCENEID\t")), "")
    if not scene_key:
        raise ValueError("Upgrade rehearsal requires a stable scene ID.")
    slot = "install_upgrade_acceptance"
    original_rows = [f"SAVE\t{slot}" if row.startswith("SAVE\t") else row for row in rows]
    objective_rows = [index for index, row in enumerate(original_rows)
                      if row.startswith("UIWIDGET\tobjective\ttext\t")]
    if len(objective_rows) != 1:
        raise ValueError("Upgrade rehearsal requires exactly one authored objective label.")
    old_objective = original_rows[objective_rows[0]].split("\t")
    updated_objective = old_objective.copy()
    updated_objective[7] = old_objective[7] + " Again"
    updated_rows = original_rows.copy()
    updated_rows[objective_rows[0]] = "\t".join(updated_objective)
    install_v1_scene = content / "install-upgrade-v1.tcruntime"
    install_v1_scene.write_text("\n".join(original_rows) + "\n", encoding="utf-8")

    install_v2 = package.parent / "install-upgrade-v2"
    updated_content = install_v2 / "Content"
    updated_content.mkdir(parents=True, exist_ok=True)
    shutil.copytree(content / "Assets", updated_content / "Assets", dirs_exist_ok=True)
    for name in ("TCPlayer.exe", "tc_graph_runtime.dll"):
        shutil.copy2(package / name, install_v2 / name)
    updated_scene = updated_content / "main.tcruntime"
    updated_scene.write_text("\n".join(updated_rows) + "\n", encoding="utf-8")
    incompatible_rows = [row for row in updated_rows if not row.startswith((
        "ENTITY\tPhysicsCube", "TRANSFORM\tPhysicsCube\t", "RENDER\tPhysicsCube\t",
        "RIGID\tPhysicsCube\t", "COLLIDER\tPhysicsCube\t",
    ))]
    if len(incompatible_rows) == len(updated_rows):
        raise ValueError("Upgrade rehearsal requires the authored PhysicsCube entity.")
    incompatible_scene = updated_content / "install-upgrade-removed-entity.tcruntime"
    incompatible_scene.write_text("\n".join(incompatible_rows) + "\n", encoding="utf-8")

    local_data = package.parent / "localappdata-install-upgrade"
    environment = {**os.environ, "LOCALAPPDATA": str(local_data)}
    save = local_data / "TechConnector" / "TCPlayer" / "saves" / scene_key / f"{slot}.tcsave"
    backup = Path(str(save) + ".bak")

    def run(executable: Path, scene: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), "--scene", str(scene), "--renderer", "d3d11", "--require-renderer",
             *arguments], cwd=executable.parent, env=environment, capture_output=True, text=True,
            timeout=60, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    created = run(package / "TCPlayer.exe", install_v1_scene, "--scripted-save-load", "--frames", "12")
    before = save.read_bytes() if save.is_file() else b""
    upgraded = run(install_v2 / "TCPlayer.exe", updated_scene,
                   "--scripted-load-then-save", "--frames", "8")
    after = save.read_bytes() if save.is_file() else b""
    reloaded = run(install_v2 / "TCPlayer.exe", updated_scene, "--scripted-load-only", "--frames", "8")
    before_incompatible_load = save.read_bytes() if save.is_file() else b""
    incompatible_load = run(install_v2 / "TCPlayer.exe", incompatible_scene,
                            "--scripted-load-only", "--frames", "8")
    after_incompatible_load = save.read_bytes() if save.is_file() else b""
    backup_before_incompatible_save = backup.read_bytes() if backup.is_file() else b""
    pending = Path(str(save) + ".tmp")
    pending.write_bytes(after_incompatible_load)
    pending_before_incompatible_save = pending.read_bytes()
    incompatible_save = run(install_v2 / "TCPlayer.exe", incompatible_scene,
                            "--scripted-save-load", "--frames", "12")
    after_incompatible_save = save.read_bytes() if save.is_file() else b""

    def player_x(data: bytes) -> float | None:
        for row in data.decode("utf-8", errors="replace").splitlines():
            if row.startswith("BODY\tPlayer\t"):
                try:
                    return float(row.split("\t")[2])
                except (IndexError, ValueError):
                    return None
        return None

    old_x, new_x = player_x(before), player_x(after)
    checks = {
        "separate_install_roots": install_v2.resolve() != package and
            (updated_content / "Assets").is_dir() and updated_scene.is_file(),
        "compatible_content_revision": updated_rows != original_rows and
            f"SCENEID\t{scene_key}" in updated_rows and
            f"SCENEID\t{scene_key}" in original_rows,
        "first_install_save": created.returncode == 0 and bool(before) and
            before.startswith(b"TCSAVE\t3\n") and
            "TC_SAVE_WRITTEN source=hotkey" in created.stdout,
        "upgraded_install_loaded_then_saved": upgraded.returncode == 0 and
            upgraded.stdout.find("TC_SAVE_LOADED source=hotkey") >= 0 and
            upgraded.stdout.find("TC_SAVE_WRITTEN source=hotkey") >
            upgraded.stdout.find("TC_SAVE_LOADED source=hotkey") and bool(after),
        "progress_preserved": old_x is not None and new_x is not None and
            old_x > 0.1 and new_x > 0.1 and abs(new_x - old_x) < 0.5,
        "preupgrade_backup_preserved": backup.is_file() and backup.read_bytes() == before,
        "upgraded_save_reloads": reloaded.returncode == 0 and
            "TC_SAVE_LOADED source=hotkey" in reloaded.stdout and
            "TC_LOAD_FAILED" not in reloaded.stderr,
        "removed_entity_rejected_without_save_mutation":
            incompatible_load.returncode == 0 and
            "TC_LOAD_FAILED source=hotkey reason=TC save game references missing scene entities or joints" in incompatible_load.stderr and
            "TC_SAVE_LOADED" not in incompatible_load.stdout and
            bool(before_incompatible_load) and before_incompatible_load == after_incompatible_load,
        "removed_entity_cannot_overwrite_existing_save":
            incompatible_save.returncode == 0 and
            "TC_SAVE_FAILED source=hotkey reason=Existing save game references missing scene entities or joints:" in incompatible_save.stderr and
            "TC_SAVE_WRITTEN" not in incompatible_save.stdout and
            before_incompatible_load == after_incompatible_save and
            (backup.read_bytes() if backup.is_file() else b"") == backup_before_incompatible_save,
        "rejected_save_preserves_pending_recovery": pending.is_file() and
            pending.read_bytes() == pending_before_incompatible_save,
    }
    return {"status": "passed" if all(checks.values()) else "blocked", "checks": checks,
            "install_v1_scene": str(install_v1_scene), "install_v2_scene": str(updated_scene),
            "save": str(save), "backup": str(backup), "player_x_before": old_x,
            "player_x_after": new_x, "created_stdout": created.stdout[-600:],
            "upgraded_stdout": upgraded.stdout[-600:], "upgraded_stderr": upgraded.stderr[-600:],
            "reloaded_stdout": reloaded.stdout[-400:], "reloaded_stderr": reloaded.stderr[-400:],
            "incompatible_stderr": incompatible_load.stderr[-400:],
            "incompatible_save_stderr": incompatible_save.stderr[-400:]}


def qualify_third_person(
    output_root: str | Path,
    player_executable: str | Path,
    *,
    variant_id: str = "exploration",
    frames: int = DEFAULT_FRAMES,
    warmup_frames: int = DEFAULT_WARMUP_FRAMES,
    frame_budget_ms: float = 16.667,
    gpu_budget_ms: float = 16.667,
    stress_actors: int = 0,
    dcc_fbx: str | Path | None = None,
    motion_demo_package: str | Path | None = None,
    motion_report: str | Path | None = None,
    motion_visual_baseline: str | Path | None = None,
    motion_previous_package: str | Path | None = None,
) -> dict[str, Any]:
    """Create, cook, package, run, stress, and recover a third-person template."""
    if variant_id not in {"exploration", "combat"}:
        raise ValueError("Third-person acceptance variant must be exploration or combat.")
    count = int(frames)
    warmup = int(warmup_frames)
    if count < 120 or warmup < 0 or warmup >= count:
        raise ValueError("Use at least 120 frames and fewer warmup frames than total frames.")
    output = Path(output_root).expanduser().resolve()
    player = Path(player_executable).expanduser().resolve()
    if not player.is_file():
        raise FileNotFoundError(player)
    initial_qualification_inputs = qualification_inputs(
        dcc_fbx, motion_demo_package, motion_report, motion_visual_baseline, motion_previous_package,
        player)
    run = output / "runs" / f"{variant_id}-{time.time_ns()}"
    workspace = run / "workspace"
    package = run / "package"
    api = TCEditorAPI(workspace)
    template = api.create_game_project_from_template(
        project_name="ThirdPersonAcceptance", template_id="third_person", variant_id=variant_id,
    )
    level = api.database.asset(str(template["level_asset_id"]))
    if level is None:
        raise RuntimeError("Third-person template has no entry level.")
    reimport = reimport_player_mesh(api, level.asset_id, run)
    dcc_reimport: dict[str, Any] = {"status": "not_requested"}
    if dcc_fbx:
        try:
            dcc_reimport = check_skeletal_fbx_reimport(api, dcc_fbx, run)
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            dcc_reimport = {"status": "blocked", "error": str(exc)}
    audio_fixture = author_audio_cue(api, level.asset_id, run)
    ui_fixture = author_runtime_ui(api, level.asset_id)
    stress_fixture = author_synthetic_stress_fixture(api, level.asset_id, int(stress_actors))
    ids = tuple(str(value) for value in template["created_asset_ids"]) + (reimport["asset_id"], *audio_fixture["asset_ids"], ui_fixture["asset_id"])
    if dcc_reimport.get("asset_id"):
        ids += (str(dcc_reimport["asset_id"]),)
    cooked = api.cook(ids)
    first = compile_tcscene_for_runtime(level.source_path, run / "compile-a" / "main.tcruntime")
    second = compile_tcscene_for_runtime(level.source_path, run / "compile-b" / "main.tcruntime")
    deterministic = first.runtime_manifest.read_bytes() == second.runtime_manifest.read_bytes()
    built = build_windows_player(level.source_path, package, player_executable=player)
    reimported_mesh_packaged = any(
        row.startswith("ASSET\t") and row.split("\t")[2] == "mesh" and row.split("\t")[4] == reimport["after_sha256"]
        for row in built.runtime_manifest.read_text(encoding="utf-8").splitlines()
        if len(row.split("\t")) >= 5
    )
    headless = validate_player_package(package, frames=count)
    gameplay_error = ""
    try:
        gameplay = check_packaged_gameplay(package, frames=count)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        gameplay = {"player_moved": False, "animation_transitioned": False, "save_roundtrip": False,
                    "legacy_save_migrated": False, "legacy_v2_save_migrated": False,
                    "malformed_legacy_rejected": False, "malformed_legacy_recovered": False,
                    "corrupt_save_rejected": False,
                    "semantic_save_rejected": False, "semantic_save_recovered": False,
                    "partial_write_recovered": False}
        gameplay_error = str(exc)
    graphical_error = ""
    try:
        graphical = validate_windowed_player(
            package, frames=count, timeout=max(60.0, count / 30.0 + 30.0), scripted_input=True,
        )
        sustained = steady_profile(package / graphical["profile"], warmup_frames=warmup)
        audio_result = check_packaged_audio(package / graphical["profile"])
        visual_result = check_visual_landmarks(package / graphical["screenshot"])
        ui_image_result = check_ui_image_pixels(package / graphical["screenshot"])
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        graphical = {"status": "blocked", "profile": "", "screenshot": ""}
        sustained = {}
        audio_result = {"submitted": False, "played": False, "events": []}
        visual_result = {"passed": False}
        ui_image_result = {"passed": False}
        graphical_error = str(exc)
    gpu_work_error = ""
    try:
        gpu_work = measure_unsynced_gpu_work(package, frames=count, warmup_frames=warmup)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        gpu_work = {}
        gpu_work_error = str(exc)
    try:
        capture_write_failure = check_capture_write_failure(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        capture_write_failure = {"status": "blocked", "error": str(exc)}
    try:
        live_debug_step = check_live_debug_step(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        live_debug_step = {"status": "blocked", "error": str(exc)}
    try:
        window_minimize_restore = check_window_minimize_restore(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        window_minimize_restore = {"status": "blocked", "error": str(exc)}
    try:
        keyboard_ui = check_keyboard_ui_navigation(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        keyboard_ui = {"status": "blocked", "error": str(exc)}
    try:
        focus_loss_rebind = check_focus_loss_rebind(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        focus_loss_rebind = {"status": "blocked", "error": str(exc)}
    try:
        gamepad_ui = check_gamepad_ui_navigation(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        gamepad_ui = {"status": "blocked", "error": str(exc)}
    try:
        gamepad_load_repeatability = check_gamepad_load_repeatability(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        gamepad_load_repeatability = {"status": "blocked", "error": str(exc)}
    try:
        gamepad_rebind_ui = check_gamepad_rebind_ui(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        gamepad_rebind_ui = {"status": "blocked", "error": str(exc)}
    try:
        ui_resize = check_runtime_ui_resize(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_resize = {"status": "blocked", "error": str(exc)}
    try:
        ui_cache = check_runtime_ui_cache(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_cache = {"status": "blocked", "error": str(exc)}
    try:
        ui_scale = check_runtime_ui_scale(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_scale = {"status": "blocked", "error": str(exc)}
    try:
        ui_safe_area = check_runtime_ui_safe_area(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_safe_area = {"status": "blocked", "error": str(exc)}
    try:
        ui_narrow = check_runtime_ui_narrow(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_narrow = {"status": "blocked", "error": str(exc)}
    try:
        ui_short = check_runtime_ui_short(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ui_short = {"status": "blocked", "error": str(exc)}
    try:
        audio_mute_ui = check_audio_mute_ui(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        audio_mute_ui = {"status": "blocked", "error": str(exc)}
    try:
        audio_restart = check_packaged_audio_restart(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        audio_restart = {"status": "blocked", "error": str(exc)}
    try:
        unicode_packaged_audio = check_unicode_packaged_audio(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        unicode_packaged_audio = {"status": "blocked", "error": str(exc)}
    try:
        windowed_scene_failure = check_windowed_scene_failure(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        windowed_scene_failure = {"status": "blocked", "error": str(exc)}
    try:
        unicode_scene_default_paths = check_unicode_scene_default_paths(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        unicode_scene_default_paths = {"status": "blocked", "error": str(exc)}
    try:
        windowed_skin_failure = check_windowed_skin_failure(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        windowed_skin_failure = {"status": "blocked", "error": str(exc)}
    try:
        user_save_load = check_user_scoped_save_load(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        user_save_load = {"status": "blocked", "error": str(exc)}
    try:
        cross_install_upgrade = check_cross_install_save_upgrade(package)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        cross_install_upgrade = {"status": "blocked", "error": str(exc)}
    try:
        user_profiles_upgrade = check_user_profiles_across_install(package, cross_install_upgrade)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        user_profiles_upgrade = {"status": "blocked", "error": str(exc)}
    recovery = check_asset_recovery(built.runtime_manifest, package)
    resumed_package = run / "resumed-package"
    checkpoint = compile_tcscene_for_runtime(level.source_path, resumed_package / "Content" / "main.tcruntime")
    resumed = build_windows_player(level.source_path, resumed_package, player_executable=player, compiled_receipt=checkpoint)
    resume_matches = _hash(resumed.runtime_manifest) == _hash(built.runtime_manifest)
    dcc_package: dict[str, Any] = {"status": "not_requested"}
    if dcc_reimport.get("asset_id"):
        try:
            imported_fbx = api.database.asset(str(dcc_reimport["asset_id"]))
            if imported_fbx is None:
                raise RuntimeError("Reimported FBX is missing before package qualification.")
            dcc_package = probe_packaged_skeletal_fbx(level.source_path, imported_fbx.source_path, run, player)
        except (OSError, RuntimeError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
            dcc_package = {"status": "blocked", "error": str(exc)}
    dcc_motion: dict[str, Any] = {"status": "not_requested"}
    if motion_demo_package and motion_report:
        try:
            dcc_motion = qualify_dcc_motion_player(
                motion_demo_package, motion_report, run, player, dcc_fbx,
                motion_visual_baseline, motion_previous_package)
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            dcc_motion = {"status": "blocked", "error": str(exc)}
    timings = dict(sustained.get("metrics_ms") or {})
    gpu_work_timings = dict(gpu_work.get("metrics_ms") or {})
    gpu_probe_equivalence = compare_gpu_probe_workload(sustained, gpu_work)
    save_slot = next(
        (row.split("\t", 1)[1] for row in built.runtime_manifest.read_text(encoding="utf-8").splitlines()
         if row.startswith("SAVE\t")), "autosave",
    )
    checks = {
        "template_ready": bool(template["ready_to_play"]),
        "character_mesh_reimport": all(reimport[key] for key in ("identity_preserved", "revision_advanced", "topology_preserved", "level_linked")),
        "reimported_mesh_packaged": reimported_mesh_packaged,
        "asset_cook": cooked.artifact.path.is_file() and set(cooked.asset_ids) == set(ids),
        "deterministic_compile": deterministic,
        "packaged_integrity": dict(built.validation.get("assets") or {}).get("status") == "passed",
        "headless_runtime": headless.get("status") == "passed",
        "player_movement": bool(gameplay["player_moved"]),
        "locomotion_animation": bool(gameplay["animation_transitioned"]),
        "save_load_roundtrip": bool(gameplay["save_roundtrip"]),
        "legacy_save_migration": bool(gameplay["legacy_save_migrated"]),
        "legacy_v2_save_migration": bool(gameplay["legacy_v2_save_migrated"]),
        "malformed_legacy_save_rejected": bool(gameplay["malformed_legacy_rejected"]),
        "malformed_legacy_backup_recovered": bool(gameplay["malformed_legacy_recovered"]),
        "corrupt_save_rejected": bool(gameplay["corrupt_save_rejected"]),
        "semantic_save_rejected": bool(gameplay["semantic_save_rejected"]),
        "semantic_save_recovered": bool(gameplay["semantic_save_recovered"]),
        "partial_write_recovered": bool(gameplay["partial_write_recovered"]),
        "pending_write_recovered": bool(gameplay["pending_write_recovered"]),
        "valid_backup_preserved": bool(gameplay["backup_preserved"]),
        "runtime_ui_document_packaged": ui_fixture["layout_cooked"] and "UIWIDGET\t" in built.runtime_manifest.read_text(encoding="utf-8"),
        "runtime_ui_image_rendered": bool(ui_image_result["passed"]),
        "runtime_ui_resize_matrix": ui_resize["status"] == "passed",
        "runtime_ui_cached_recomposition": ui_cache["status"] == "passed",
        "runtime_ui_manual_scale": ui_scale["status"] == "passed",
        "runtime_ui_simulated_dpi_change": ui_scale.get("dpi_change", {}).get("status") == "passed",
        "runtime_ui_combined_dpi_manual_scale": ui_scale.get("combined_dpi_change", {}).get("status") == "passed",
        "runtime_ui_safe_area": ui_safe_area["status"] == "passed",
        "runtime_ui_narrow_layout": ui_narrow["status"] == "passed",
        "runtime_ui_short_layout": ui_short["status"] == "passed",
        "runtime_audio_mute_ui": audio_mute_ui["status"] == "passed",
        "backup_only_audio_preference_recovered": bool(
            audio_mute_ui.get("checks", {}).get("backup_only_muted_preference_recovered")),
        "software_audio_output_restart": audio_restart["status"] == "passed",
        "unicode_packaged_audio_playback": unicode_packaged_audio["status"] == "passed",
        "windowed_bad_scene_exits_without_modal": windowed_scene_failure["status"] == "passed",
        "unicode_scene_default_paths": unicode_scene_default_paths["status"] == "passed",
        "windowed_missing_skin_fails_closed": windowed_skin_failure["status"] == "passed",
        "duplicate_scene_identity_rejected": bool(
            windowed_scene_failure.get("checks", {}).get("duplicate_scene_id")),
        "user_scoped_windowed_save_load": user_save_load["status"] == "passed",
        "synthetic_cross_install_save_upgrade": cross_install_upgrade["status"] == "passed",
        "user_profiles_across_install": user_profiles_upgrade["status"] == "passed",
        "foreign_scene_save_rejected": bool(user_save_load.get("checks", {}).get("foreign_scene_save_rejected")),
        "foreign_scene_overwrite_rejected": bool(user_save_load.get("checks", {}).get("foreign_scene_overwrite_rejected")),
        "foreign_primary_compatible_backup_recovered": bool(
            user_save_load.get("checks", {}).get("foreign_primary_compatible_backup_recovered")),
        "missing_primary_valid_backup_recovered": bool(
            user_save_load.get("checks", {}).get("missing_primary_valid_backup_recovered")),
        "runtime_ui_button_activated": any(
            "id=save_button event=save_game" in line for line in graphical.get("ui_activations", [])
        ) and (package / "Content" / f"{save_slot}.tcsave").is_file(),
        "keyboard_ui_navigation": keyboard_ui["status"] == "passed",
        "focus_loss_cancels_pending_rebind": focus_loss_rebind["status"] == "passed",
        "simulated_xbox_ui_navigation": gamepad_ui["status"] == "passed",
        "simulated_xbox_load_repeatability": gamepad_load_repeatability["status"] == "passed",
        "simulated_gamepad_rebind_ui": gamepad_rebind_ui["status"] == "passed",
        "backup_only_gamepad_profile_recovered": bool(
            gamepad_rebind_ui.get("checks", {}).get("backup_only_profile_recovered")),
        "rebound_gamepad_ui_input": gamepad_ui["status"] == "passed" and
            "GAMEPADBIND\tui_confirm\tWEST" in built.runtime_manifest.read_text(encoding="utf-8"),
        "rebound_keyboard_input": "INPUTBIND\tmove_right\t76" in built.runtime_manifest.read_text(encoding="utf-8")
            and any("action=move_right key=76" in line for line in graphical.get("input_bindings_used", []))
            and bool(sustained) and sustained["windowed_player_moved"],
        "interactive_debug_snapshot": bool(graphical.get("debug_snapshot_written")) and (
            lambda snapshot: snapshot.get("schema") == "tech_connector.runtime_debug_snapshot.v1"
            and any(entity.get("name") == "Player" for entity in snapshot.get("entities", []))
        )(json.loads((package / graphical["debug_snapshot"]).read_text(encoding="utf-8"))),
        "live_debug_pause_step_resume": live_debug_step["status"] == "passed",
        "window_minimize_restore": window_minimize_restore["status"] == "passed",
        "hud_visual_landmarks": bool(visual_result["passed"]),
        "windowed_d3d11": graphical.get("status") == "passed",
        "capture_write_failure_rejected": capture_write_failure["status"] == "passed",
        "skinned_character_rendered": bool(sustained) and sustained["skinned_draws_min"] > 0,
        "windowed_scripted_control": bool(sustained) and sustained["windowed_player_moved"],
        "windowed_locomotion_transition": bool(sustained) and sustained["windowed_animation_transitioned"],
        "packaged_audio_playback": bool(audio_result["played"]),
        "packaged_audio_overlap": bool(audio_result.get("overlapping_distinct_cues")) and
            audio_result.get("submitted_count", 0) >= audio_fixture["expected_cues"],
        "packaged_audio_submitted": bool(audio_result["submitted"]),
        "non_silent_audio_asset": audio_fixture["non_silent_samples"] > 0,
        "sustained_frame_budget": bool(timings) and
        timings["frame_interval_ms"]["p95"] <= frame_budget_ms + 0.5 and
        timings["frame_ms"]["p95"] <= frame_budget_ms,
        "sustained_frame_pacing": bool(timings) and
        timings["frame_interval_ms"]["p99"] <= frame_budget_ms * 2.0,
        "gpu_probe_equivalent": gpu_probe_equivalence["status"] == "passed",
        "sustained_gpu_budget": gpu_probe_equivalence["status"] == "passed" and
        bool(gpu_work_timings) and
        gpu_work.get("gpu_sample_coverage", 0.0) >= 0.9 and
        gpu_work_timings["gpu_sample_ms"]["p95"] <= gpu_budget_ms,
        "render_adapter_identified": sustained.get("graphics_adapter", {}).get("status") == "passed",
        "actual_submitted_draws_recorded": bool(sustained) and
            sustained["submitted_geometry_draws_min"] > 0 and
            sustained["submitted_shadow_draws_min"] > 0,
        "corruption_detected": recovery["corruption_detected"],
        "package_restored": recovery["restored_integrity"],
        "checkpoint_resume": resume_matches and resumed.validation.get("status") == "passed",
    }
    if stress_fixture["actors"]:
        checks["synthetic_stress_draws"] = bool(sustained) and sustained["draw_calls_min"] >= stress_fixture["actors"] + 4
    if dcc_fbx:
        checks["skeletal_fbx_import_reimport"] = all(dcc_reimport.get(key) for key in (
            "original_unchanged", "identity_preserved", "revision_advanced", "source_changed",
            "topology_and_joint_names_preserved", "skin_contract_valid",
        )) and dcc_reimport.get("bones", 0) > 0 and dcc_reimport.get("influences", 0) > 0
        checks["packaged_dcc_skeletal_render"] = dcc_package.get("status") == "passed"
    if motion_demo_package or motion_report:
        checks["dcc_character_locomotion_player"] = dcc_motion.get("status") == "passed"
        checks["dcc_character_reverse_locomotion"] = bool(
            dcc_motion.get("motion", {}).get("checks", {}).get(
                "reverse_locomotion_after_traversal"))
        checks["dcc_character_narrow_controls_safe"] = (
            dcc_motion.get("narrow_control_card", {}).get("status") == "passed")
        checks["dcc_character_motion_phases_visible"] = (
            dcc_motion.get("motion_phase_visibility", {}).get("status") == "passed")
        checks["dcc_character_cross_process_save_reload"] = (
            dcc_motion.get("windowed_save_reload", {}).get("status") == "passed")
        checks["dcc_character_scene_bound_save"] = bool(dcc_motion.get("scene_bound_save"))
        checks["dcc_character_legacy_unbound_save_migrated"] = (
            dcc_motion.get("legacy_unbound_save_migration", {}).get("status") == "passed")
        checks["dcc_character_compatible_content_upgrade"] = (
            dcc_motion.get("compatible_content_upgrade", {}).get("status") == "passed")
        if motion_previous_package is not None or dcc_motion.get("different_binary_save_upgrade", {}).get("status") != "not_run":
            checks["dcc_character_different_binary_save_upgrade"] = (
                dcc_motion.get("different_binary_save_upgrade", {}).get("status") == "passed")
        checks["dcc_character_foreign_scene_save_rejected"] = bool(
            dcc_motion.get("compatible_content_upgrade", {}).get("checks", {}).get(
                "foreign_scene_cannot_load_or_overwrite"))
        checks["dcc_character_user_scoped_save_across_install"] = (
            dcc_motion.get("user_scoped_save_across_install", {}).get("status") == "passed")
        checks["dcc_character_default_legacy_save_migrated"] = (
            dcc_motion.get("default_legacy_save_migration", {}).get("status") == "passed")
        checks["dcc_character_corrupt_save_backup_recovered"] = bool(
            dcc_motion.get("windowed_save_reload", {}).get("checks", {}).get(
                "corrupt_primary_recovers_backup"))
        checks["rebound_gamepad_motion_input"] = dcc_motion.get("status") == "passed" and bool(
            dcc_motion.get("rebound_gamepad_buttons"))
    final_qualification_inputs = qualification_inputs(
        dcc_fbx, motion_demo_package, motion_report, motion_visual_baseline, motion_previous_package,
        player)
    checks["qualification_inputs_stable"] = qualification_inputs_stable(
        initial_qualification_inputs, final_qualification_inputs)
    technical_pass = all(checks.values())
    # A template/package pass is not a full game: these require authored gameplay receipts.
    remaining = [
        *([] if checks.get("dcc_character_locomotion_player") else [
            "DCC character locomotion and full replacement of starter Player" if checks.get("packaged_dcc_skeletal_render") else
            ("packaged third-person replacement with DCC rig" if checks.get("skeletal_fbx_import_reimport") else "skeletal DCC import/reimport beyond OBJ mesh")
        ]),
        "contact-aware foot locking, root motion, and turning", "physical Xbox controller and UI-navigation gamepad rebinding UX",
        "runtime UI accessibility, DPI/broader-device matrix and console-safe-area policy", "audio UX and device matrix beyond a PCM tone", "broader save migration and recovery matrix", "in-app inspector and breakpoints beyond pause/step/snapshot",
        "representative scene and hardware stress", "visual golden-image review",
    ]
    result = {
        "schema": SCHEMA,
        "status": "partial" if technical_pass else "blocked",
        "technical_baseline": "passed" if technical_pass else "blocked",
        "full_third_person_acceptance": "not_proven",
        "release_targets": release_target_assessment(technical_pass, platform.system()),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "variant_id": variant_id,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "host_hardware": host_hardware_receipt(sustained.get("graphics_adapter", {})),
        "player_sha256": _hash(player),
        "qualification_inputs": final_qualification_inputs,
        "qualification_inputs_at_start": initial_qualification_inputs,
        "frames": count,
        "warmup_frames": warmup,
        "budgets_ms": {"frame_interval_p95_target": frame_budget_ms,
                       "frame_interval_p95_tolerance": 0.5,
                       "frame_interval_p99": frame_budget_ms * 2.0,
                       "cpu_frame_p95": frame_budget_ms,
                       "unsynced_gpu_work_p95": gpu_budget_ms},
        "checks": checks,
        "created_asset_types": sorted({api.database.asset(asset_id).asset_type for asset_id in ids}),
        "packaged_asset_count": dict(built.validation.get("assets") or {}).get("verified_count", 0),
        "sustained_profile": sustained,
        "unsynced_gpu_work_profile": gpu_work,
        "gpu_probe_equivalence": gpu_probe_equivalence,
        "unsynced_gpu_work_error": gpu_work_error,
        "capture_write_failure": capture_write_failure,
        "live_debug_step": live_debug_step,
        "window_minimize_restore": window_minimize_restore,
        "gameplay": gameplay,
        "character_reimport": reimport,
        "skeletal_dcc_reimport": dcc_reimport,
        "skeletal_dcc_package": dcc_package,
        "skeletal_dcc_motion_player": dcc_motion,
        "runtime_ui": ui_fixture,
        "runtime_ui_resize": ui_resize,
        "runtime_ui_cache": ui_cache,
        "runtime_ui_scale": ui_scale,
        "runtime_ui_safe_area": ui_safe_area,
        "runtime_ui_narrow": ui_narrow,
        "runtime_ui_short": ui_short,
        "runtime_audio_mute_ui": audio_mute_ui,
        "software_audio_output_restart": audio_restart,
        "unicode_packaged_audio": unicode_packaged_audio,
        "windowed_bad_scene": windowed_scene_failure,
        "unicode_scene_default_paths": unicode_scene_default_paths,
        "windowed_missing_skin": windowed_skin_failure,
        "user_scoped_windowed_save_load": user_save_load,
        "cross_install_save_upgrade": cross_install_upgrade,
        "user_profiles_across_install": user_profiles_upgrade,
        "keyboard_ui": keyboard_ui,
        "focus_loss_rebind": focus_loss_rebind,
        "gamepad_ui": gamepad_ui,
        "gamepad_load_repeatability": gamepad_load_repeatability,
        "gamepad_rebind_ui": gamepad_rebind_ui,
        "audio_fixture": audio_fixture,
        "audio_result": audio_result,
        "visual_landmarks": visual_result,
        "ui_image_pixels": ui_image_result,
        "stress_fixture": stress_fixture,
        "gameplay_error": gameplay_error,
        "graphical_error": graphical_error,
        "graphical_screenshot": graphical.get("screenshot", ""),
        "recovery": recovery,
        "remaining_requirements": remaining,
        "run_root": str(run),
    }
    output.mkdir(parents=True, exist_ok=True)
    report = output / f"third_person_{variant_id}_acceptance.json"
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(report)
    return result | {"report": str(report)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run packaged third-person acceptance on Windows/D3D11.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--variant", choices=("exploration", "combat"), default="exploration")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    parser.add_argument("--warmup-frames", type=int, default=DEFAULT_WARMUP_FRAMES)
    parser.add_argument("--stress-actors", type=int, default=0,
                        help="Add up to 2000 render-only props for a synthetic D3D11 scale probe.")
    parser.add_argument("--dcc-fbx", help="Optional user-provided rigged FBX for skeletal import/reimport qualification.")
    parser.add_argument("--motion-demo-package", help="Packaged SKM_Test DCC Player for actual locomotion qualification.")
    parser.add_argument("--motion-report", help="Retargeted SKM_Test motion_library_report.json.")
    parser.add_argument("--motion-visual-baseline", help="Reviewed DCC crawl image outside the player package.")
    parser.add_argument("--motion-previous-package", help="Prior compatible DCC build for two-binary save upgrade testing.")
    args = parser.parse_args()
    receipt = qualify_third_person(
        args.output, args.player, variant_id=args.variant,
        frames=args.frames, warmup_frames=args.warmup_frames, stress_actors=args.stress_actors,
        dcc_fbx=args.dcc_fbx,
        motion_demo_package=args.motion_demo_package, motion_report=args.motion_report,
        motion_visual_baseline=args.motion_visual_baseline,
        motion_previous_package=args.motion_previous_package,
    )
    print(json.dumps({key: receipt[key] for key in ("status", "technical_baseline", "checks", "report")}, indent=2))
    return 0 if receipt["technical_baseline"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
