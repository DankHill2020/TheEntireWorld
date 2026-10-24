"""Verify the scripted SKM_Test motion-search and crawl-clearance demo pass.

Usage: python verify_skm_motion_demo.py PROFILE.jsonl REPORT.json MOTION_REPORT.json
The profile is produced by TCPlayer --scripted-motion-demo --frames 380.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys


REQUIRED_CLIPS = {
    "tc_run", "tc_crouch_move", "tc_crawl_walk", "tc_idle",
    "tc_jump_start", "tc_jump_air", "tc_jump_land",
}


def grounded_ankle_local_motion(clips: dict) -> dict:
    """Report low-ankle local motion; root travel is needed to measure foot slide."""
    result = {}
    for role in ("walk", "run", "walk_back", "strafe_left", "strafe_right",
                 "crouch_move", "crawl"):
        clip = clips.get(role, {})
        features = clip.get("pose_features", [])
        fps = float(clip.get("fps", 0))
        if fps <= 0 or len(features) < 2:
            continue
        threshold = 0.09 if role == "crawl" else 0.12
        feet = {}
        for joint in ("l_ankle", "r_ankle"):
            speeds = []
            for before, after in zip(features, features[1:]):
                if int(after["frame"]) != int(before["frame"]) + 1:
                    continue
                old = before["joints"][joint]
                new = after["joints"][joint]
                old_height = float(before["pelvis_height"]) + float(old[2])
                new_height = float(after["pelvis_height"]) + float(new[2])
                if max(old_height, new_height) <= threshold:
                    speeds.append(math.hypot(float(new[0]) - float(old[0]),
                                             float(new[1]) - float(old[1])) * fps)
            feet[joint] = {"low_contact_pairs": len(speeds),
                           "mean_local_planar_speed_mps":
                           round(sum(speeds) / len(speeds), 3) if speeds else None,
                           "max_local_planar_speed_mps":
                           round(max(speeds), 3) if speeds else None}
        result[role] = feet
    return result


def low_ankle_world_drift(frames: list[dict]) -> dict:
    """Measure rendered-bone drift near its lowest sampled height, not true contact."""
    positions: dict[str, dict[str, list[tuple[int, float, float, float, float, float, float]]]] = {}
    for row in frames:
        rotation = row.get("player_visual_rotation_degrees")
        scale = row.get("player_visual_scale")
        ankles = row.get("ankle_model_positions")
        delta = float(row.get("simulation_delta_seconds", 0.0))
        if (not isinstance(rotation, list) or len(rotation) != 3 or
                abs(float(rotation[0]) + 90.0) > 0.01 or
                abs(float(rotation[1])) > 0.01 or abs(float(rotation[2])) > 0.01 or
                not isinstance(scale, list) or len(scale) != 3 or
                not isinstance(ankles, dict) or delta <= 0.0):
            continue  # The DCC demo's X=-90 transform is the only qualified mapping here.
        clip = str(row.get("active_animation", ""))
        if clip not in {"tc_walk", "tc_run", "tc_walk_back", "tc_strafe_left",
                        "tc_strafe_right", "tc_crouch_move", "tc_crawl_walk"}:
            continue
        for foot in ("l_ankle", "r_ankle"):
            bone = ankles.get(foot)
            if not isinstance(bone, list) or len(bone) != 3:
                continue
            # Renderer model transform: scale, X=-90 degrees, then translate.
            point = (int(row["frame"]),
                     float(row["player_x"]) + float(scale[0]) * float(bone[0]),
                     float(row["player_y"]) + float(scale[2]) * float(bone[2]),
                     float(row["player_z"]) - float(scale[1]) * float(bone[1]), delta,
                     float(row["player_x"]), float(row["player_z"]))
            positions.setdefault(clip, {}).setdefault(foot, []).append(point)
    result = {}
    for clip, feet in positions.items():
        result[clip] = {}
        for foot, points in feet.items():
            minimum = min(point[2] for point in points)
            pairs = [(math.hypot(after[1] - before[1], after[3] - before[3]) / after[4],
                      before[0], after[0], after[1] - before[1], after[3] - before[3])
                     for before, after in zip(points, points[1:])
                     if after[0] == before[0] + 1 and
                     max(before[2], after[2]) <= minimum + 0.15]
            opposing = []
            for before, after in zip(points, points[1:]):
                if after[0] != before[0] + 1 or max(before[2], after[2]) > minimum + 0.15:
                    continue
                root_x, root_z = after[5] - before[5], after[6] - before[6]
                foot_x, foot_z = after[1] - before[1], after[3] - before[3]
                if (math.hypot(root_x, root_z) >= 0.03 and
                        (foot_x - root_x) * root_x + (foot_z - root_z) * root_z < -0.001):
                    opposing.append(math.hypot(foot_x, foot_z) / after[4])
            worst = max(pairs, key=lambda item: item[0]) if pairs else None
            result[clip][foot] = {
                "near_lowest_pairs": len(pairs),
                "mean_world_planar_speed_mps":
                round(sum(item[0] for item in pairs) / len(pairs), 3) if pairs else None,
                "max_world_planar_speed_mps": round(worst[0], 3) if worst else None,
                "worst_pair_frames": [worst[1], worst[2]] if worst else None,
                "worst_pair_world_delta_xz_m": [round(worst[3], 4), round(worst[4], 4)]
                if worst else None,
                "minimum_bone_height_m": round(minimum, 3),
                "opposing_root_pairs": len(opposing),
                "mean_opposing_root_world_speed_mps":
                round(sum(opposing) / len(opposing), 3) if opposing else None,
                "max_opposing_root_world_speed_mps":
                round(max(opposing), 3) if opposing else None,
            }
    return result


def reverse_motion_observed(frames: list[dict]) -> bool:
    if len(frames) < 440:
        return False
    clear = frames[379:400]
    reverse = frames[400:430]
    return (float(frames[399].get("player_z", 0)) -
            float(frames[379].get("player_z", 0)) >= 0.5 and
            any(row.get("active_animation") == "tc_walk_back" for row in reverse) and
            float(frames[399].get("player_z", 0)) -
            float(frames[429].get("player_z", 0)) >= 0.5 and
            all(float(row.get("player_z", 0)) >= 9.5 for row in reverse) and
            all(abs(float(row.get("player_x", 0))) < 0.2 for row in clear + reverse))


def reverse_canopy_contact_observed(frames: list[dict]) -> bool:
    if len(frames) < 420:
        return False
    approach = frames[380:410]
    return (any(row.get("active_animation") == "tc_walk_back" for row in approach) and
            any("Player:CrawlCanopy" in row.get("contact_pairs", []) for row in approach) and
            all(float(row.get("player_z", 0)) >= 9.2 for row in approach) and
            abs(float(frames[399].get("player_z", 0)) -
                float(frames[419].get("player_z", 0))) <= 0.05)


def verify(profile_path: Path, motion_report_path: Path | None = None,
           *, require_reverse_motion: bool = False,
           require_reverse_canopy_contact: bool = False) -> dict:
    rows = [json.loads(line) for line in profile_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")]
    starts = [index for index, row in enumerate(rows)
              if row.get("type") == "frame" and row.get("frame") == 1]
    if starts:
        rows = rows[starts[-1]:]
    frames = [row for row in rows if row.get("type") == "frame"]
    diagnostics = [row for row in rows if row.get("type") != "frame"]
    clips = {str(row.get("active_animation")) for row in frames}
    transitions = [str(row.get("active_animation")) for index, row in enumerate(frames)
                   if index == 0 or row.get("active_animation") != frames[index - 1].get("active_animation")]
    jump_start = transitions.index("tc_jump_start") if "tc_jump_start" in transitions else -1
    checks = {
        "full_380_frame_run": len(frames) >= 380,
        "native_search_each_frame": bool(frames) and
        int(frames[-1].get("motion_match_searches", 0)) >= len(frames),
        "all_motion_phases": REQUIRED_CLIPS <= clips,
        "crawl_under_canopy": len(frames) >= 200 and
        str(frames[149].get("active_animation")) == "tc_crawl_walk" and
        float(frames[79].get("player_z", 0)) < 7.0 and
        float(frames[199].get("player_z", 0)) > 9.0,
        "stands_after_exit": len(frames) >= 230 and
        str(frames[229].get("active_animation")) != "tc_crawl_walk",
        "jump_after_canopy": len(frames) >= 310 and
        any(row.get("active_animation") == "tc_jump_land" for row in frames[250:310]),
        "clean_jump_phases": jump_start >= 0 and
        transitions[jump_start:jump_start + 4] ==
        ["tc_jump_start", "tc_jump_air", "tc_jump_land", "tc_idle"],
        "gpu_renderer_active": bool(frames) and all(
            float(row.get("render_width", 0)) > 0 and "gpu_ms" in row for row in frames),
        "gpu_skinning_active": bool(frames) and all(
            int(row.get("gpu_skinned_draws", 0)) >= 1 and
            int(row.get("cpu_skinned_draws", 0)) == 0 for row in frames),
        "no_diagnostics": not diagnostics,
    }
    if require_reverse_motion:
        checks["reverse_locomotion_after_traversal"] = reverse_motion_observed(frames)
    if require_reverse_canopy_contact:
        checks["reverse_stops_at_canopy_collider"] = reverse_canopy_contact_observed(frames)
    contact_heights = None
    ankle_local_motion = None
    if motion_report_path is not None:
        library = json.loads(motion_report_path.read_text(encoding="utf-8"))
        ankle_local_motion = grounded_ankle_local_motion(library["clips"])
        contact_heights = [
            float(feature["pelvis_height"]) + float(feature["joints"][joint][2])
            for role in ("crawl_idle", "crawl")
            for feature in library["clips"][role]["pose_features"]
            for joint in ("l_hand", "r_hand", "l_ankle", "r_ankle")
        ]
        checks["four_point_crawl_contacts"] = bool(contact_heights) and \
            min(contact_heights) >= 0.025 and max(contact_heights) <= 0.09
    return {
        "schema": "tech_connector.skm_motion_demo_acceptance.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "scope": "scripted SKM_Test motion-search and canopy traversal demo",
        "checks": checks,
        "frames": len(frames),
        "motion_searches": int(frames[-1].get("motion_match_searches", 0)) if frames else 0,
        "clips_seen": sorted(clips),
        "transitions": transitions,
        "contact_joint_height_range_m": ([round(min(contact_heights), 4), round(max(contact_heights), 4)]
                                         if contact_heights else None),
        "grounded_ankle_local_motion_diagnostic": ankle_local_motion,
        "low_ankle_world_drift_diagnostic": low_ankle_world_drift(frames),
        "foot_slide_qualified": False,
        "diagnostics": diagnostics,
    }


if __name__ == "__main__":
    if len(sys.argv) not in {4, 5} or (len(sys.argv) == 5 and sys.argv[4] not in
                                    {"--require-reverse-motion", "--require-reverse-canopy-contact"}):
        raise SystemExit("Expected PROFILE.jsonl REPORT.json MOTION_REPORT.json "
                         "[--require-reverse-motion|--require-reverse-canopy-contact]")
    result = verify(Path(sys.argv[1]), Path(sys.argv[3]),
                    require_reverse_motion=sys.argv[-1] == "--require-reverse-motion",
                    require_reverse_canopy_contact=sys.argv[-1] == "--require-reverse-canopy-contact")
    destination = Path(sys.argv[2])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": result["checks"]}))
    raise SystemExit(0 if result["status"] == "passed" else 1)
