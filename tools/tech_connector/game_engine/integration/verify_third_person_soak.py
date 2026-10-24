"""Verify a long D3D11 third-person profile for sustained timing and rendering.

Usage: python -m tech_connector.game_engine.integration.verify_third_person_soak PROFILE.jsonl REPORT.json
"""

from __future__ import annotations

import json
import argparse
import math
from pathlib import Path


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


def verify_soak(profile_path: Path, *, warmup: int = 60, min_draw_calls: int = 260,
                scope: str = "same-device synthetic 256-prop D3D11 soak",
                require_motion_search: bool = False,
                require_mixed_motion: bool = False,
                require_unsynced_gpu_samples: bool = False,
                require_vsynced_pacing: bool = False) -> dict:
    if warmup < 0 or min_draw_calls < 1:
        raise ValueError("warmup must be nonnegative and min_draw_calls must be positive")
    rows = [json.loads(line) for line in profile_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")]
    frames = [row for row in rows if row.get("type") == "frame"]
    errors = [row for row in rows if row.get("type") != "frame" and
              not (row.get("type") == "audio_event" and row.get("status") == "played")]
    steady = frames[warmup:]
    midpoint = len(steady) // 2
    early, late = steady[:midpoint], steady[midpoint:]
    gpu_early = _p95([float(row["gpu_ms"]) for row in early]) if early else float("inf")
    gpu_late = _p95([float(row["gpu_ms"]) for row in late]) if late else float("inf")
    frame_p95 = _p95([float(row["frame_ms"]) for row in steady]) if steady else float("inf")
    intervals = [float(row["frame_interval_ms"]) for row in steady
                 if "frame_interval_ms" in row]
    valid_intervals = len(intervals) == len(steady) and bool(intervals) and all(
        math.isfinite(value) and value > 0 for value in intervals)
    interval_p95 = _p95(intervals) if valid_intervals else None
    interval_p99 = sorted(intervals)[min(len(intervals) - 1, int(0.99 * len(intervals)))] \
        if valid_intervals else None
    private_early = [float(row["private_bytes"]) for row in early if "private_bytes" in row]
    private_late = [float(row["private_bytes"]) for row in late if "private_bytes" in row]
    private_early_p95 = _p95(private_early) if private_early else None
    private_late_p95 = _p95(private_late) if private_late else None
    motion_searches = [int(row.get("motion_match_searches", -1)) for row in frames]
    gpu_samples = [float(sample) for row in steady
                   for sample in row.get("gpu_samples_ms", [])]
    gpu_sample_coverage = min(1.0, len(gpu_samples) / len(steady)) if steady else 0.0
    gpu_sample_p95 = _p95(gpu_samples) if gpu_samples else None
    mixed_cycles = [frames[start:start + 240] for start in range(380, len(frames) - 239, 240)]
    mixed_clips = {"tc_idle", "tc_strafe_right", "tc_strafe_left",
                   "tc_crouch_idle", "tc_crawl_idle",
                   "tc_jump_start", "tc_jump_air", "tc_jump_land"}
    # The scripted route alternates its lead direction on every cycle. Clip
    # presence alone would pass even if one direction were stuck for most of
    # the run, so inspect the first traversal window separately.
    alternating_leads = all(
        sum(row.get("active_animation") == ("tc_strafe_right" if index % 2 == 0
                                             else "tc_strafe_left")
            for row in cycle[:30]) >
        sum(row.get("active_animation") == ("tc_strafe_left" if index % 2 == 0
                                             else "tc_strafe_right")
            for row in cycle[:30])
        for index, cycle in enumerate(mixed_cycles))
    ordered_mixed_phases = all(
        "tc_crouch_idle" in {row.get("active_animation") for row in cycle[60:120]} and
        "tc_crawl_idle" in {row.get("active_animation") for row in cycle[120:180]} and
        "tc_jump_start" in {row.get("active_animation") for row in cycle[180:210]} and
        "tc_jump_air" in {row.get("active_animation") for row in cycle[180:240]} and
        "tc_jump_land" in {row.get("active_animation") for row in cycle[200:240]}
        for cycle in mixed_cycles)
    checks = {
        "full_3600_frame_run": len(frames) >= 3600,
        "stable_gpu_p95": gpu_late <= gpu_early * 1.25,
        "gpu_budget_60fps": max(gpu_early, gpu_late) <= 16.667,
        "frame_budget_60fps": frame_p95 <= 16.667,
        "stress_draws_sustained": bool(steady) and
            min(int(row.get("draw_calls", 0)) for row in steady) >= min_draw_calls,
        "gpu_skinning_sustained": bool(steady) and
            min(int(row.get("gpu_skinned_draws", 0)) for row in steady) >= 2,
        "stable_private_memory": len(private_early) >= 10 and len(private_late) >= 10 and
            private_early_p95 is not None and private_late_p95 is not None and
            private_late_p95 <= private_early_p95 + 16 * 1024 * 1024,
        "no_error_events": not errors,
        "motion_search_each_frame": not require_motion_search or (
            bool(motion_searches) and all(value == index + 1
                                          for index, value in enumerate(motion_searches))),
        "mixed_action_cycles": not require_mixed_motion or (
            len(mixed_cycles) >= 10 and all(
                mixed_clips <= {str(row.get("active_animation")) for row in cycle}
                for cycle in mixed_cycles)),
        "alternating_strafe_leads": not require_mixed_motion or (
            len(mixed_cycles) >= 10 and alternating_leads),
        "ordered_mixed_phases": not require_mixed_motion or (
            len(mixed_cycles) >= 10 and ordered_mixed_phases),
        "bounded_player_path": not require_mixed_motion or (
            bool(frames) and all(abs(float(row.get("player_x", float("inf")))) <= 5.0 and
                                 0.5 <= float(row.get("player_y", 0)) <= 4.0 and
                                 abs(float(row.get("player_z", float("inf")))) <= 12.0
                                 for row in frames)),
        "unsynced_gpu_samples": not require_unsynced_gpu_samples or (
            gpu_sample_coverage >= 0.95 and gpu_sample_p95 is not None and
            gpu_sample_p95 <= 16.667 and
            all(row.get("vsync") is False for row in steady)),
        "vsynced_frame_pacing": not require_vsynced_pacing or (
            interval_p95 is not None and interval_p99 is not None and
            interval_p95 <= 17.167 and interval_p99 <= 33.334 and
            all(row.get("vsync") is True for row in steady)),
    }
    return {
        "schema": "tech_connector.third_person_soak.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "scope": scope, "min_draw_calls": min_draw_calls,
        "requires_motion_search": require_motion_search,
        "requires_mixed_motion": require_mixed_motion, "mixed_cycles": len(mixed_cycles),
        "requires_unsynced_gpu_samples": require_unsynced_gpu_samples,
        "requires_vsynced_pacing": require_vsynced_pacing,
        "gpu_sample_coverage": gpu_sample_coverage, "gpu_sample_p95_ms": gpu_sample_p95,
        "frame_interval_p95_ms": interval_p95, "frame_interval_p99_ms": interval_p99,
        "frames": len(frames), "warmup": warmup, "checks": checks,
        "gpu_p95_first_half_ms": gpu_early, "gpu_p95_second_half_ms": gpu_late,
        "private_bytes_p95_first_half": private_early_p95,
        "private_bytes_p95_second_half": private_late_p95,
        "private_memory_samples": len(private_early) + len(private_late),
        "frame_p95_ms": frame_p95, "errors": errors,
        "profile": str(profile_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument("--min-draw-calls", type=int, default=260)
    parser.add_argument("--scope", default="same-device synthetic 256-prop D3D11 soak")
    parser.add_argument("--require-motion-search", action="store_true")
    parser.add_argument("--require-mixed-motion", action="store_true")
    parser.add_argument("--require-unsynced-gpu-samples", action="store_true")
    parser.add_argument("--require-vsynced-pacing", action="store_true")
    args = parser.parse_args()
    receipt = verify_soak(args.profile, warmup=args.warmup,
                          min_draw_calls=args.min_draw_calls, scope=args.scope,
                          require_motion_search=args.require_motion_search,
                          require_mixed_motion=args.require_mixed_motion,
                          require_unsynced_gpu_samples=args.require_unsynced_gpu_samples,
                          require_vsynced_pacing=args.require_vsynced_pacing)
    target = args.report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "checks": receipt["checks"]}))
    raise SystemExit(0 if receipt["status"] == "passed" else 1)
